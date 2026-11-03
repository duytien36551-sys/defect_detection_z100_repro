"""V8-specific, versioned board client. No host-side model execution."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import socket
import struct
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .preprocess import SIZE, ImageMapping

PROTOCOL = "pin9-v8/2-input640"
TENSOR_BYTES = SIZE * SIZE * 3
MAX_JSON_BYTES = 1_048_576
IP_UNICAST_IF = getattr(socket, "IP_UNICAST_IF", 31)
TASKS = frozenset(("all", "pin"))


class BoardProtocolError(RuntimeError):
    pass


class BoardIdentityError(BoardProtocolError):
    pass


class BoardResultUnknown(BoardProtocolError):
    """Submission may have reached the board; this client never resends it."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def class_domain(name: str) -> str | None:
    if name.startswith("PIN_"):
        return "pin"
    return None


def validate_class_names(names: Any) -> list[str]:
    if (not isinstance(names, list) or len(names) != 9
            or not all(isinstance(value, str) and value.strip() == value
                       and value.startswith("PIN_") and len(value) > len("PIN_") for value in names)
            or len(set(names)) != 9):
        raise ValueError("PIN640 requires nine unique ordered PIN_ class names")
    return list(names)


def model_domain(names: list[str]) -> str:
    validate_class_names(names)
    return "pin"


def load_class_names(path: str | Path) -> list[str]:
    # data.yaml in this project is JSON-compatible YAML.
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_class_names(data["names"])


def _read_exact(sock: socket.socket, count: int, *, deadline: float | None = None) -> bytes:
    out = bytearray()
    while len(out) < count:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("board HELLO deadline exceeded")
            sock.settimeout(remaining)
        block = sock.recv(count - len(out))
        if not block:
            raise BoardProtocolError("connection closed before complete response")
        out.extend(block)
    return bytes(out)


def _send_json(sock: socket.socket, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if not 0 < len(data) <= MAX_JSON_BYTES:
        raise BoardProtocolError("JSON frame exceeds limit")
    sock.sendall(struct.pack("!I", len(data)) + data)


def _read_json(sock: socket.socket, *, deadline: float | None = None) -> dict[str, Any]:
    (length,) = struct.unpack("!I", _read_exact(sock, 4, deadline=deadline))
    if not 0 < length <= MAX_JSON_BYTES:
        raise BoardProtocolError("invalid JSON frame size")
    try:
        value = json.loads(_read_exact(sock, length, deadline=deadline))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoardProtocolError("invalid JSON response") from exc
    if not isinstance(value, dict):
        raise BoardProtocolError("JSON response must be an object")
    return value


def validate_detections(raw: Any, mapping: ImageMapping, task: str, names: list[str]) -> list[dict[str, Any]]:
    if task not in TASKS:
        raise ValueError(f"unknown task: {task}")
    names = validate_class_names(names)
    domain = model_domain(names)
    if len(names) == 9 and task not in ("all", domain):
        raise BoardProtocolError(f"requested {task} task does not match the {domain} model")
    if not isinstance(raw, list) or len(raw) > 10000:
        raise BoardProtocolError("detections must be a bounded list")
    output: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise BoardProtocolError("detection must be an object")
        class_id, score, box = item.get("class_id"), item.get("score"), item.get("xyxy")
        if type(class_id) is not int or not 0 <= class_id < len(names):
            raise BoardProtocolError("detection class_id is invalid")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise BoardProtocolError("detection score is invalid")
        if not isinstance(box, list) or len(box) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in box):
            raise BoardProtocolError("detection xyxy is invalid")
        try:
            projected = mapping.project(box)
        except ValueError as exc:
            raise BoardProtocolError(str(exc)) from exc
        class_matches = task == "all" or class_domain(names[class_id]) == task
        if class_matches and projected[2] > projected[0] and projected[3] > projected[1]:
            output.append({"class_id": class_id, "class_name": names[class_id], "score": float(score), "xyxy": projected})
    return sorted(output, key=lambda x: x["score"], reverse=True)


class BoardClient:
    def __init__(self, host: str, port: int, *, model_sha256: str, class_names: list[str], timeout: float = 30.0,
                 allow_host_reference: bool = False, local_address: str | None = None,
                 interface_index: int | None = None):
        if not host or not 1 <= port <= 65535 or timeout <= 0:
            raise ValueError("invalid endpoint or timeout")
        if len(model_sha256) != 64 or any(c not in "0123456789abcdef" for c in model_sha256):
            raise ValueError("model_sha256 must be lower-case SHA256")
        class_names = validate_class_names(class_names)
        if local_address is not None:
            if not isinstance(local_address, str):
                raise ValueError("local_address must be an IPv4 address")
            try:
                local_address = str(ipaddress.IPv4Address(local_address))
            except ipaddress.AddressValueError as exc:
                raise ValueError("local_address must be an IPv4 address") from exc
        if interface_index is not None:
            if type(interface_index) is not int or not 1 <= interface_index <= 0xFFFFFFFF:
                raise ValueError("interface_index must be a positive 32-bit integer")
            if sys.platform != "win32":
                raise NotImplementedError("interface_index binding is supported on Windows only")
        self.host, self.port, self.timeout = host, port, timeout
        self.model_sha256 = model_sha256
        self.class_names = class_names
        self.class_count = len(class_names)
        self.class_domain = model_domain(class_names)
        self.classes_sha256 = canonical_sha256(class_names)
        self.allow_host_reference = allow_host_reference
        self.local_address, self.interface_index = local_address, interface_index

    def _open_connection(self) -> socket.socket:
        if self.local_address is None and self.interface_index is None:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
            return sock

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            if self.interface_index is not None:
                sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", self.interface_index))
            if self.local_address is not None:
                sock.bind((self.local_address, 0))
            sock.connect((self.host, self.port))
            return sock
        except Exception:
            sock.close()
            raise

    def _send_hello(self, sock: socket.socket, *, deadline: float | None = None) -> dict[str, Any]:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("board HELLO deadline exceeded")
            sock.settimeout(remaining)
        _send_json(sock, {"type": "HELLO", "protocol": PROTOCOL,
                          "model_sha256": self.model_sha256, "classes_sha256": self.classes_sha256})
        return _read_json(sock, deadline=deadline)

    def _validate_hello(self, hello: dict[str, Any], *, allow_host_reference: bool) -> str:
        if hello.get("type") != "HELLO_OK" or hello.get("protocol") != PROTOCOL:
            raise BoardIdentityError("board does not support the V8 protocol")
        if hello.get("model_sha256") != self.model_sha256 or hello.get("classes_sha256") != self.classes_sha256:
            raise BoardIdentityError("board V8 model or classes do not match")
        advertised_count = hello.get("class_count")
        advertised_domain = hello.get("class_domain")
        if self.class_count == 9 or advertised_count is not None or advertised_domain is not None:
            if (type(advertised_count) is not int or advertised_count != self.class_count
                    or advertised_domain != self.class_domain):
                raise BoardIdentityError("board V8 class count or model domain does not match")
        if hello.get("input") != "rgb-u8-640-letterbox114" or hello.get("box_space") != "normalized-model-xyxy":
            raise BoardIdentityError("board image or result semantics do not match")
        runtime = hello.get("runtime")
        if runtime != "board" and not (allow_host_reference and runtime == "host_reference"):
            raise BoardIdentityError("runtime is not verified as a board; host reference requires explicit opt-in")
        return runtime

    def probe_identity(self) -> tuple[dict[str, Any], tuple[str, int], tuple[str, int]]:
        """Exchange HELLO only and return the raw reply plus local/peer socket addresses."""
        deadline = time.monotonic() + self.timeout
        try:
            with self._open_connection() as sock:
                hello = self._send_hello(sock, deadline=deadline)
                return hello, sock.getsockname(), sock.getpeername()
        except BoardProtocolError:
            raise
        except OSError as exc:
            raise BoardProtocolError(f"board connection failed: {exc}") from exc

    def infer(self, tensor_rgb: bytes, mapping: ImageMapping, task: str = "all") -> list[dict[str, Any]]:
        if task not in TASKS or len(tensor_rgb) != TENSOR_BYTES:
            raise ValueError("invalid task or 640x640 RGB tensor")
        if self.class_count == 9 and task not in ("all", self.class_domain):
            raise ValueError(f"requested {task} task does not match the {self.class_domain} model")
        # `all` is a UI convenience; the wire task remains bound to this PIN model.
        wire_task = self.class_domain if task == "all" else task
        request_id = uuid.uuid4().hex
        try:
            with self._open_connection() as sock:
                hello = self._send_hello(sock)
                runtime = self._validate_hello(hello, allow_host_reference=self.allow_host_reference)
                try:
                    _send_json(sock, {"type": "INFER", "protocol": PROTOCOL, "request_id": request_id,
                                      "task": wire_task, "tensor_bytes": TENSOR_BYTES,
                                      "tensor_sha256": hashlib.sha256(tensor_rgb).hexdigest()})
                    sock.sendall(tensor_rgb)
                    result = _read_json(sock)
                except (OSError, BoardProtocolError) as exc:
                    raise BoardResultUnknown(f"result unknown for request {request_id}: {exc}") from exc
        except BoardProtocolError:
            raise
        except OSError as exc:
            raise BoardProtocolError(f"board connection failed: {exc}") from exc
        if result.get("protocol") != PROTOCOL or result.get("request_id") != request_id:
            raise BoardProtocolError("result version or request identity does not match")
        if result.get("type") == "ERROR":
            raise BoardProtocolError(f"board rejected inference: {result.get('message', 'unknown error')}")
        if result.get("type") != "RESULT" or result.get("box_space") != "normalized-model-xyxy" or result.get("runtime") != runtime:
            raise BoardProtocolError("invalid V8 result envelope")
        # Model output always contains its complete class set. Task selection
        # affects presentation and report rows after identity is verified.
        return validate_detections(result.get("detections"), mapping, task, self.class_names)
