"""PIN640 desktop protocol, preprocessing, loopback, and C service guards."""

from __future__ import annotations

import hashlib
import json
import pathlib
import socket
import struct
import subprocess
import sys
import threading
import tkinter as tk
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
CANDIDATE = ROOT / "candidates" / "pin640"
PIN_CLASSES = PROJECT / "examples" / "data" / "pin_classes.json"
PIN_MODEL_PACKAGE = CANDIDATE / "validation" / "20261021_final" / "pin" / "pipeline" / "package" / "MODEL.V8P"
sys.path.insert(0, str(PROJECT))

from deployment.candidates.pin640.desktop import protocol  # noqa: E402
from deployment.candidates.pin640.desktop import app as desktop_app  # noqa: E402
from deployment.candidates.pin640.desktop.preprocess import ImageMapping, prepare_bgr  # noqa: E402
from deployment.candidates.pin640.desktop.reference_server import serve_connection  # noqa: E402


NAMES = [f"PIN_{index}" for index in range(9)]
MODEL_SHA256 = "a" * 64


class _Values:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class _FakeModel:
    def predict(self, *, source, imgsz, conf, iou, device, verbose):
        assert source.shape == (640, 640, 3)
        assert imgsz == 640 and device == "cpu" and verbose is False
        assert conf == 0.25 and iou == 0.45
        boxes = SimpleNamespace(
            xyxy=_Values([[64.0, 128.0, 320.0, 512.0]]),
            cls=_Values([2.0]),
            conf=_Values([0.75]),
        )
        return [SimpleNamespace(boxes=boxes)]


def _fragmented_json(sock: socket.socket, value: dict) -> None:
    body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    frame = struct.pack("!I", len(body)) + body
    for offset in range(0, len(frame), 3):
        sock.sendall(frame[offset : offset + 3])


class Pin640ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_dir = CANDIDATE / "build" / "protocol_tests"
        cls.build_dir.mkdir(parents=True, exist_ok=True)
        cls.service_exe = cls.build_dir / "service_guards.exe"
        gcc = pathlib.Path(r"C:\cbian\mingw64\bin\gcc.exe")
        command = [
            str(gcc), "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-I", str(CANDIDATE / "firmware"),
            str(CANDIDATE / "tests" / "service_guards.c"),
            str(CANDIDATE / "firmware" / "v8_service.c"),
            str(CANDIDATE / "firmware" / "v8_sha256.c"),
            "-lm", "-o", str(cls.service_exe),
        ]
        subprocess.run(command, cwd=PROJECT, check=True, capture_output=True, text=True)

    def test_pin_only_protocol_identity_and_task_selection(self):
        self.assertEqual(protocol.PROTOCOL, "pin9-v8/2-input640")
        self.assertEqual(protocol.TENSOR_BYTES, 1_228_800)
        self.assertEqual(protocol.validate_class_names(NAMES), NAMES)
        self.assertEqual(protocol.model_domain(NAMES), "pin")
        self.assertIsNone(protocol.class_domain("PCB_SH"))
        empty_suffix = ["PIN_"] + [f"PIN_{i}" for i in range(1, 9)]
        for invalid in ([f"PIN_{i}" for i in range(18)], [f"PCB_{i}" for i in range(9)],
                        empty_suffix,
                        ["PIN_0"] * 9, ["PIN_0", "PIN_1"]):
            with self.subTest(invalid_count=len(invalid)):
                with self.assertRaises(ValueError):
                    protocol.validate_class_names(invalid)
        client = protocol.BoardClient("127.0.0.1", 5002, model_sha256=MODEL_SHA256,
                                      class_names=NAMES, allow_host_reference=True)
        with self.assertRaises(ValueError):
            client.infer(b"x", ImageMapping(1, 1, 1, 0, 0, 1, 1), "all")
        with self.assertRaises(ValueError):
            client.infer(bytes(protocol.TENSOR_BYTES), ImageMapping(1, 1, 1, 0, 0, 1, 1), "pcb")

    def test_preprocess_is_rgb_640_letterbox_and_rejects_bad_images(self):
        image = np.empty((1, 2, 3), dtype=np.uint8)
        image[:, 0, :] = [10, 20, 30]
        image[:, 1, :] = [40, 50, 60]
        tensor, mapping = prepare_bgr(image)
        self.assertEqual(len(tensor), protocol.TENSOR_BYTES)
        rgb = np.frombuffer(tensor, dtype=np.uint8).reshape(640, 640, 3)
        self.assertEqual(mapping, ImageMapping(2, 1, 320.0, 0, 160, 640, 320))
        np.testing.assert_array_equal(rgb[0, 0], [114, 114, 114])
        np.testing.assert_array_equal(rgb[160, 0], [30, 20, 10])
        np.testing.assert_array_equal(rgb[160, 639], [60, 50, 40])
        np.testing.assert_array_equal(rgb[639, 0], [114, 114, 114])
        self.assertEqual(mapping.project([0.1, 0.25, 0.9, 0.75]), [0.2, 0.0, 1.8, 1.0])
        for bad in (np.zeros((3, 4), dtype=np.uint8),
                    np.zeros((2, 2, 4), dtype=np.uint8),
                    np.zeros((2, 2, 3), dtype=np.float32),
                    np.zeros((1, 10_000, 3), dtype=np.uint8),
                    np.zeros((10_000, 1, 3), dtype=np.uint8)):
            with self.subTest(shape=bad.shape, dtype=bad.dtype):
                with self.assertRaises(ValueError):
                    prepare_bgr(bad)

    def test_board_client_loopback_to_reference_service_handles_fragmented_reply(self):
        source = np.full((640, 640, 3), [7, 19, 31], dtype=np.uint8)
        tensor, mapping = prepare_bgr(source)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        endpoint = listener.getsockname()
        errors: list[BaseException] = []

        def server():
            try:
                conn, _ = listener.accept()
                with conn:
                    conn.settimeout(10)
                    hello = protocol._read_json(conn)
                    self.assertEqual(hello["protocol"], "pin9-v8/2-input640")
                    self.assertEqual(hello["classes_sha256"], protocol.canonical_sha256(NAMES))
                    _fragmented_json(conn, {
                        "type": "HELLO_OK", "protocol": protocol.PROTOCOL,
                        "runtime": "host_reference", "model_sha256": MODEL_SHA256,
                        "classes_sha256": protocol.canonical_sha256(NAMES), "class_count": 9,
                        "class_domain": "pin", "input": "rgb-u8-640-letterbox114",
                        "box_space": "normalized-model-xyxy",
                    })
                    request = protocol._read_json(conn)
                    self.assertEqual(request["type"], "INFER")
                    self.assertEqual(request["task"], "pin")
                    self.assertEqual(request["tensor_bytes"], 1_228_800)
                    payload = protocol._read_exact(conn, 1_228_800)
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), request["tensor_sha256"])
                    _fragmented_json(conn, {
                        "type": "RESULT", "protocol": protocol.PROTOCOL,
                        "runtime": "host_reference", "request_id": request["request_id"],
                        "box_space": "normalized-model-xyxy",
                        "detections": [{"class_id": 2, "score": 0.75,
                                        "xyxy": [0.1, 0.2, 0.5, 0.8]}],
                    })
            except BaseException as exc:  # propagate thread failures to the test
                errors.append(exc)
            finally:
                listener.close()

        worker = threading.Thread(target=server, daemon=True)
        worker.start()
        client = protocol.BoardClient("127.0.0.1", endpoint[1], model_sha256=MODEL_SHA256,
                                      class_names=NAMES, timeout=10, allow_host_reference=True)
        detections = client.infer(tensor, mapping, "all")
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "loopback service did not finish")
        if errors:
            raise errors[0]
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0]["class_name"], "PIN_2")
        self.assertEqual(detections[0]["xyxy"], [64.0, 128.0, 320.0, 512.0])

    def test_board_client_rejects_old_protocol_and_wrong_identity(self):
        for reply_overrides, error_type in (
            ({"protocol": "joint18-v8/1"}, protocol.BoardIdentityError),
            ({"model_sha256": "b" * 64}, protocol.BoardIdentityError),
            ({"classes_sha256": "c" * 64}, protocol.BoardIdentityError),
            ({"class_count": 18}, protocol.BoardIdentityError),
            ({"class_domain": "pcb"}, protocol.BoardIdentityError),
            ({"input": "rgb-u8-416-letterbox114"}, protocol.BoardIdentityError),
        ):
            with self.subTest(reply_overrides=reply_overrides):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                endpoint = listener.getsockname()

                def server():
                    conn, _ = listener.accept()
                    with conn:
                        hello = protocol._read_json(conn)
                        reply = {
                            "type": "HELLO_OK", "protocol": protocol.PROTOCOL,
                            "runtime": "board", "model_sha256": MODEL_SHA256,
                            "classes_sha256": protocol.canonical_sha256(NAMES), "class_count": 9,
                            "class_domain": "pin", "input": "rgb-u8-640-letterbox114",
                            "box_space": "normalized-model-xyxy",
                        }
                        self.assertEqual(hello["type"], "HELLO")
                        reply.update(reply_overrides)
                        _fragmented_json(conn, reply)
                    listener.close()

                worker = threading.Thread(target=server, daemon=True)
                worker.start()
                client = protocol.BoardClient("127.0.0.1", endpoint[1], model_sha256=MODEL_SHA256,
                                              class_names=NAMES, timeout=5)
                with self.assertRaises(error_type):
                    client.infer(bytes(protocol.TENSOR_BYTES), ImageMapping(640, 640, 1, 0, 0, 640, 640), "pin")
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

    def test_reference_server_mock_inference_roundtrip(self):
        tensor = bytes([114]) * protocol.TENSOR_BYTES
        names_hash = protocol.canonical_sha256(NAMES)
        left, right = socket.socketpair()
        left.settimeout(10)
        right.settimeout(10)
        errors: list[BaseException] = []

        def serve():
            try:
                serve_connection(right, _FakeModel(), MODEL_SHA256, NAMES)
            except BaseException as exc:
                errors.append(exc)
            finally:
                right.close()

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        protocol._send_json(left, {"type": "HELLO", "protocol": protocol.PROTOCOL,
                                   "model_sha256": MODEL_SHA256, "classes_sha256": names_hash})
        hello = protocol._read_json(left)
        self.assertEqual(hello["class_count"], 9)
        self.assertEqual(hello["input"], "rgb-u8-640-letterbox114")
        request_id = "0123456789abcdef0123456789abcdef"
        protocol._send_json(left, {"type": "INFER", "protocol": protocol.PROTOCOL,
                                   "request_id": request_id, "task": "pin",
                                   "tensor_bytes": protocol.TENSOR_BYTES,
                                   "tensor_sha256": hashlib.sha256(tensor).hexdigest()})
        left.sendall(tensor)
        result = protocol._read_json(left)
        left.close()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        if errors:
            raise errors[0]
        self.assertEqual(result["request_id"], request_id)
        self.assertEqual(result["detections"][0]["class_id"], 2)
        self.assertEqual(result["detections"][0]["xyxy"], [0.1, 0.2, 0.5, 0.8])

    def test_reference_server_rejects_old_protocol_and_bad_tensor_digest(self):
        names_hash = protocol.canonical_sha256(NAMES)
        for old_protocol, bad_digest in ((True, False), (False, True)):
            with self.subTest(old_protocol=old_protocol, bad_digest=bad_digest):
                left, right = socket.socketpair()
                left.settimeout(10)
                right.settimeout(10)
                errors: list[BaseException] = []

                def serve():
                    try:
                        serve_connection(right, _FakeModel(), MODEL_SHA256, NAMES)
                    except BaseException as exc:
                        errors.append(exc)
                    finally:
                        right.close()

                worker = threading.Thread(target=serve, daemon=True)
                worker.start()
                protocol_name = "joint18-v8/1" if old_protocol else protocol.PROTOCOL
                protocol._send_json(left, {"type": "HELLO", "protocol": protocol_name,
                                           "model_sha256": MODEL_SHA256, "classes_sha256": names_hash})
                hello_result = protocol._read_json(left)
                if old_protocol:
                    self.assertEqual(hello_result["type"], "ERROR")
                    self.assertIn("identity mismatch", hello_result["message"])
                else:
                    self.assertEqual(hello_result["type"], "HELLO_OK")
                    tensor = bytes([114]) * protocol.TENSOR_BYTES
                    request_id = "fedcba9876543210fedcba9876543210"
                    digest = "0" * 64 if bad_digest else hashlib.sha256(tensor).hexdigest()
                    protocol._send_json(left, {"type": "INFER", "protocol": protocol.PROTOCOL,
                                               "request_id": request_id, "task": "pin",
                                               "tensor_bytes": protocol.TENSOR_BYTES,
                                               "tensor_sha256": digest})
                    left.sendall(tensor)
                    error = protocol._read_json(left)
                    self.assertEqual(error["type"], "ERROR")
                    self.assertEqual(error["request_id"], request_id)
                    self.assertIn("checksum mismatch", error["message"])
                left.close()
                worker.join(timeout=10)
                self.assertFalse(worker.is_alive())
                if errors:
                    raise errors[0]

    def test_candidate_cli_help_is_pin9_and_640_specific(self):
        for module in ("deployment.candidates.pin640.desktop.app",
                       "deployment.candidates.pin640.desktop.reference_server"):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-B", "-X", "utf8", "-m", module, "--help"],
                    cwd=PROJECT, capture_output=True, text=True, check=True, timeout=30,
                )
                help_text = result.stdout.lower()
                self.assertIn("pin", help_text)
                self.assertIn("640", help_text)
                self.assertNotIn("18-class", help_text)
                self.assertNotIn("eighteen-class", help_text)
                self.assertNotIn("single-domain", help_text)

    def test_headless_app_uses_pin9_640_model_identity_without_network(self):
        names = protocol.load_class_names(PIN_CLASSES)
        self.assertEqual(len(names), 9)
        self.assertEqual(protocol.model_domain(names), "pin")
        self.assertTrue(PIN_MODEL_PACKAGE.is_file(), PIN_MODEL_PACKAGE)
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk cannot initialize in this environment: {exc}")
        app = None
        destroyed = False
        root.withdraw()
        try:
            with ExitStack() as patches:
                patches.enter_context(mock.patch.object(
                    protocol.BoardClient, "_open_connection",
                    side_effect=AssertionError("headless smoke attempted a network connection")))
                patches.enter_context(mock.patch.object(
                    protocol.socket, "create_connection",
                    side_effect=AssertionError("headless smoke opened a TCP connection")))
                patches.enter_context(mock.patch.object(
                    protocol.socket, "socket",
                    side_effect=AssertionError("headless smoke opened a socket")))
                patches.enter_context(mock.patch.object(
                    desktop_app, "diagnose_connection",
                    side_effect=AssertionError("headless smoke started diagnostics")))
                patches.enter_context(mock.patch.object(root, "after", return_value="stub-after"))
                patches.enter_context(mock.patch.object(root, "after_idle", return_value="stub-after-idle"))
                app = desktop_app.App(root, host="127.0.0.1", port=5001,
                                      model=PIN_MODEL_PACKAGE, names=names,
                                      allow_host_reference=False, timeout=5)
                client = app._client(timeout=5)
                root.update_idletasks()
                self.assertFalse(root.winfo_viewable(), "withdrawn app window became visible")
                self.assertEqual(app.names, names)
                self.assertEqual(app.model_hash, hashlib.sha256(PIN_MODEL_PACKAGE.read_bytes()).hexdigest())
                self.assertEqual(client.model_sha256, app.model_hash)
                self.assertEqual(client.class_names, names)
                self.assertEqual(client.class_count, 9)
                self.assertEqual(client.class_domain, "pin")
                self.assertEqual(client.classes_sha256, protocol.canonical_sha256(names))
                self.assertEqual(protocol.PROTOCOL, "pin9-v8/2-input640")
                self.assertEqual(app.resource_info['device'], 'xc7z100ffg900-2')
                self.assertFalse(app.resource_info['available'])
            try:
                app._close()
            finally:
                destroyed = True
            self.assertTrue(app._closed)
        finally:
            if not destroyed:
                root.destroy()

    def test_c_service_fragmentation_faults_canaries_and_recovery(self):
        result = subprocess.run([str(self.service_exe)], cwd=PROJECT, check=False,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
