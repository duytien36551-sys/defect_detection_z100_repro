"""Tests for strict PIN640 package admission before a Vitis build is started."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
import zlib

import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
import vitis2026_build_pin640 as build  # noqa: E402


class Pin640PackageAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pin640_build_test_")
        self.original_candidate_root = build.PIN640_ROOT
        build.PIN640_ROOT = Path(self.temp.name)
        self.package = Path(self.temp.name) / "package"
        self.package.mkdir()
        self._write_valid_package()

    def tearDown(self):
        build.PIN640_ROOT = self.original_candidate_root
        self.temp.cleanup()

    def _write_valid_package(self):
        classes = [f"PIN_class_{index}" for index in range(9)]
        class_hash = hashlib.sha256(
            json.dumps(classes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        payload = b"fixture parameters"
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        node_count = 1
        arena_bytes = 1024
        scratch_count = 1
        blob = struct.pack("<4s7I", b"V8PK", 1, len(payload), crc, node_count,
                           arena_bytes, 9, 640) + payload
        metadata = {
            "format": "V8PK",
            "version": 1,
            "protocol": build.PROTOCOL,
            "domain": "pin",
            "class_count": 9,
            "classes": classes,
            "source_class_ids": list(range(9, 18)),
            "model_sha256": "a" * 64,
            "input_size": 640,
            "input_shape": [1, 3, 640, 640],
            "input_bytes": 1228800,
            "rgb_input_bytes": 1228800,
            "nchw_input_bytes": 1228800,
            "parameter_bytes": len(payload),
            "parameter_crc32": crc,
            "node_count": node_count,
            "reg_max": 16,
            "arena_bytes": arena_bytes,
            "scratch_bytes": scratch_count * 4,
            "float_head_bytes": 613200 * 4,
            "total_runtime_buffers": arena_bytes + 2 * 1228800 + 4 + 613200 * 4,
            "accuracy_accepted": False,
        }
        header = "\n".join([
            '#define V8_CLASS_DOMAIN "pin"',
            "#define V8_CLASS_COUNT 9u",
            "#define V8_INPUT_SIZE 640u",
            "#define V8_REG_MAX 16u",
            f"#define V8_PACKAGE_BYTES {len(blob)}u",
            f"#define V8_ARENA_BYTES {arena_bytes}u",
            f"#define V8_SCRATCH_COUNT {scratch_count}u",
            "#define V8_HEAD_ELEMENTS 613200u",
            f'#define V8_CLASSES_SHA256 "{class_hash}"',
            "static const V8Node v8_nodes[1] = {",
            "};",
        ]) + "\n"
        (self.package / "package.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        (self.package / "MODEL.V8P").write_bytes(blob)
        (self.package / "v8_generated_model.h").write_text(header, encoding="utf-8")

    def _mutate_metadata(self, **changes):
        path = self.package / "package.json"
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata.update(changes)
        path.write_text(json.dumps(metadata), encoding="utf-8")

    def test_accepts_matching_pin640_metadata_binary_and_header(self):
        contract = build.validate_pin640_package(self.package)
        self.assertEqual(contract["protocol"], "pin9-v8/2-input640")
        self.assertEqual(contract["input_bytes"], 1228800)
        self.assertEqual(contract["float_head_bytes"], 2452800)
        self.assertFalse(contract["accuracy_accepted"])

    def test_rejects_legacy_416_package_before_sdk_preflight(self):
        self._mutate_metadata(input_size=416, input_shape=[1, 3, 416, 416],
                              input_bytes=519168, rgb_input_bytes=519168,
                              nchw_input_bytes=519168)
        with self.assertRaisesRegex(build.Pin640BuildInputError, "input shape"):
            build.validate_pin640_package(self.package)

    def test_legacy_416_request_is_rejected_before_base_build_preflight(self):
        self._mutate_metadata(input_size=416, input_shape=[1, 3, 416, 416],
                              input_bytes=519168, rgb_input_bytes=519168,
                              nchw_input_bytes=519168)
        base = importlib.import_module("vitis2026_build")
        original_validate = base.validate_request
        base.validate_request = lambda args: self.fail("base build preflight must not run")
        args = SimpleNamespace(
            domain="pin", package=self.package, preflight_only=False,
            xsa=Path("unreached.xsa"), hardware_report=Path("unreached.json"))
        try:
            with self.assertRaisesRegex(base.BuildInputError, "input shape"):
                build._strict_validate_request(args)
        finally:
            base.validate_request = original_validate

    def test_rejects_other_protocol_even_when_shape_is_640(self):
        self._mutate_metadata(protocol="joint18-v8/1")
        with self.assertRaisesRegex(build.Pin640BuildInputError, "protocol"):
            build.validate_pin640_package(self.package)

    def test_rejects_empty_pin_class_suffix(self):
        classes = [f"PIN_class_{index}" for index in range(9)]
        classes[0] = "PIN_"
        digest = hashlib.sha256(
            json.dumps(classes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self._mutate_metadata(classes=classes)
        header = self.package / "v8_generated_model.h"
        text = header.read_text(encoding="utf-8")
        line = next(item for item in text.splitlines() if item.startswith("#define V8_CLASSES_SHA256 "))
        header.write_text(text.replace(line.split('"')[1], digest), encoding="utf-8")
        with self.assertRaisesRegex(build.Pin640BuildInputError, r"PIN_\* names"):
            build.validate_pin640_package(self.package)

    def test_rejects_unsupported_reg_max(self):
        self._mutate_metadata(reg_max=8)
        header = self.package / "v8_generated_model.h"
        header.write_text(header.read_text(encoding="utf-8").replace(
            "#define V8_REG_MAX 16u", "#define V8_REG_MAX 8u"), encoding="utf-8")
        with self.assertRaisesRegex(build.Pin640BuildInputError, "reg_max=16"):
            build.validate_pin640_package(self.package)

    def test_main_restores_base_vitis_globals_after_return(self):
        base = importlib.import_module("vitis2026_build")
        original_driver = base.DRIVER
        original_validate = base.validate_request
        original_failures = base._build_report_failures
        original_main = base.main
        original_contract_validate = build._BASE_VALIDATE_REQUEST
        base.main = lambda argv=None: 7
        try:
            self.assertEqual(build.main([]), 7)
            self.assertEqual(base.DRIVER, original_driver)
            self.assertIs(base.validate_request, original_validate)
            self.assertIs(base._build_report_failures, original_failures)
            self.assertIs(build._BASE_VALIDATE_REQUEST, original_contract_validate)
        finally:
            base.main = original_main

    def test_rejects_package_crc_mismatch(self):
        blob_path = self.package / "MODEL.V8P"
        blob_path.write_bytes(blob_path.read_bytes()[:-1] + b"X")
        with self.assertRaisesRegex(build.Pin640BuildInputError, "CRC"):
            build.validate_pin640_package(self.package)

    def test_rejects_header_input_size_mismatch(self):
        header = self.package / "v8_generated_model.h"
        header.write_text(header.read_text(encoding="utf-8").replace(
            "#define V8_INPUT_SIZE 640u", "#define V8_INPUT_SIZE 416u"), encoding="utf-8")
        with self.assertRaisesRegex(build.Pin640BuildInputError, "V8_INPUT_SIZE"):
            build.validate_pin640_package(self.package)

    def test_rejects_class_order_hash_mismatch(self):
        header = self.package / "v8_generated_model.h"
        text = header.read_text(encoding="utf-8")
        line = next(item for item in text.splitlines() if item.startswith("#define V8_CLASSES_SHA256 "))
        digest = line.split('"')[1]
        header.write_text(text.replace(digest, "b" * 64), encoding="utf-8")
        with self.assertRaisesRegex(build.Pin640BuildInputError, "class-order hash"):
            build.validate_pin640_package(self.package)


if __name__ == "__main__":
    unittest.main()
