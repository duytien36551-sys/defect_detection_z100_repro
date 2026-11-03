"""CPU host reference service for testing the V8 desktop workflow.

This service performs model inference on the PC. Its runtime identity is
``host_reference`` and must never be reported as FPGA or board execution.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import socket

import cv2
import numpy as np
from ultralytics import YOLO

from .protocol import (PROTOCOL, SIZE, TENSOR_BYTES, _read_exact, _read_json,
                       _send_json, canonical_sha256, load_class_names, model_domain)


def serve_connection(sock: socket.socket, model: YOLO, model_sha256: str, names: list[str]):
    hello = _read_json(sock)
    names_hash = canonical_sha256(names)
    if (hello.get("type") != "HELLO" or hello.get("protocol") != PROTOCOL
            or hello.get("model_sha256") != model_sha256 or hello.get("classes_sha256") != names_hash):
        _send_json(sock, {"type": "ERROR", "protocol": PROTOCOL, "message": "V8 protocol/model/class identity mismatch"})
        return
    _send_json(sock, {"type": "HELLO_OK", "protocol": PROTOCOL, "runtime": "host_reference",
                      "model_sha256": model_sha256, "classes_sha256": names_hash,
                      "class_count": len(names), "class_domain": model_domain(names),
                      "input": "rgb-u8-640-letterbox114", "box_space": "normalized-model-xyxy"})
    request = _read_json(sock)
    if request.get("type") != "INFER" or request.get("protocol") != PROTOCOL or request.get("tensor_bytes") != TENSOR_BYTES:
        return
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or len(request_id) != 32 or request.get("task") not in ("pin",):
        return
    domain = model_domain(names)
    if request.get("task") != domain:
        _send_json(sock, {"type": "ERROR", "protocol": PROTOCOL, "runtime": "host_reference",
                          "request_id": request_id,
                          "message": f"requested task does not match the {domain} model"})
        return
    tensor = _read_exact(sock, TENSOR_BYTES)
    if hashlib.sha256(tensor).hexdigest() != request.get("tensor_sha256"):
        _send_json(sock, {"type": "ERROR", "protocol": PROTOCOL, "runtime": "host_reference",
                          "request_id": request_id, "message": "input checksum mismatch"})
        return
    rgb = np.frombuffer(tensor, dtype=np.uint8).reshape(SIZE, SIZE, 3)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    predictions = model.predict(source=bgr, imgsz=SIZE, conf=0.25, iou=0.45,
                                device="cpu", verbose=False)
    boxes = predictions[0].boxes
    detections = []
    for coords, class_id, score in zip(boxes.xyxy.cpu().tolist(), boxes.cls.cpu().tolist(), boxes.conf.cpu().tolist()):
        detections.append({"class_id": int(class_id), "score": float(score),
                           "xyxy": [max(0.0, min(1.0, float(v) / SIZE)) for v in coords]})
    _send_json(sock, {"type": "RESULT", "protocol": PROTOCOL, "runtime": "host_reference",
                      "request_id": request_id, "box_space": "normalized-model-xyxy", "detections": detections})


def main():
    parser = argparse.ArgumentParser(description="PIN9 640x640 host reference service; never board evidence")
    parser.add_argument("--model", type=Path, required=True, help="PIN9 640 checkpoint (.pt)")
    parser.add_argument("--classes", type=Path, required=True, help="matching ordered nine-class PIN names config")
    parser.add_argument("--port", type=int, default=5002)
    args = parser.parse_args()
    if not args.model.is_file():
        parser.error("--model must point to the PIN9 640 checkpoint (.pt)")
    if not args.classes.is_file():
        parser.error("--classes must point to the matching data configuration")
    try:
        names = load_class_names(args.classes)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(f"invalid --classes configuration: {exc}")
    model = YOLO(str(args.model))
    if [model.names[i] for i in range(len(model.names))] != names:
        parser.error("loaded model class order differs from the data config")
    model_sha256 = hashlib.sha256(args.model.read_bytes()).hexdigest()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", args.port))
        listener.listen(4)
        print(f"HOST_REFERENCE only: 127.0.0.1:{args.port}, model={model_sha256}", flush=True)
        while True:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(120)
                try:
                    serve_connection(conn, model, model_sha256, names)
                except Exception as exc:
                    print(f"reference request failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
