"""Strict binding and monkeypatch-restoration tests for the 466-MHz PIN640 build entry."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zlib
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
import vitis2026_build_pin640_jtag466 as build466  # noqa: E402
import vitis2026_driver_pin640_jtag466 as driver466  # noqa: E402


class Pin640Jtag466BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pin640_jtag466_test_")
        self.temp_root = Path(self.temp.name)
        self.package_root = self.temp_root / "candidate"
        self.package_root.mkdir()
        self.package = self.package_root / "package"
        self.package.mkdir()
        self._write_valid_package()

        self.base = importlib.import_module("vitis2026_build")
        self.pin = importlib.import_module("vitis2026_build_pin640")
        self.legacy_child = importlib.import_module("vitis2026_driver_pin640")
        self.original_pin_root = self.pin.PIN640_ROOT
        self.pin.PIN640_ROOT = self.package_root
        self.original_pin_binding = (
            self.pin.EXPECTED_XSA,
            self.pin.EXPECTED_XSA_SHA256,
            self.pin.EXPECTED_HARDWARE_REPORT,
            self.pin._BASE_VALIDATE_REQUEST,
        )
        self.original_child_binding = (
            self.legacy_child.EXPECTED_XSA,
            self.legacy_child.EXPECTED_XSA_SHA256,
            self.legacy_child.EXPECTED_HARDWARE_REPORT,
        )

    def tearDown(self):
        (self.pin.EXPECTED_XSA,
         self.pin.EXPECTED_XSA_SHA256,
         self.pin.EXPECTED_HARDWARE_REPORT,
         self.pin._BASE_VALIDATE_REQUEST) = self.original_pin_binding
        (self.legacy_child.EXPECTED_XSA,
         self.legacy_child.EXPECTED_XSA_SHA256,
         self.legacy_child.EXPECTED_HARDWARE_REPORT) = self.original_child_binding
        self.pin.PIN640_ROOT = self.original_pin_root
        self.temp.cleanup()

    def _write_valid_package(self):
        classes = [f"PIN_class_{index}" for index in range(9)]
        classes_hash = hashlib.sha256(
            json.dumps(classes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        payload = b"pin640 test parameter payload"
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        node_count = 1
        arena_bytes = 1024
        scratch_bytes = 4
        blob = struct.pack("<4s7I", b"V8PK", 1, len(payload), crc, node_count,
                           arena_bytes, 9, 640) + payload
        metadata = {
            "format": "V8PK", "version": 1, "protocol": "pin9-v8/2-input640",
            "domain": "pin", "class_count": 9, "classes": classes,
            "source_class_ids": list(range(9, 18)), "model_sha256": "a" * 64,
            "input_size": 640, "input_shape": [1, 3, 640, 640],
            "input_bytes": 1228800, "rgb_input_bytes": 1228800,
            "nchw_input_bytes": 1228800, "parameter_bytes": len(payload),
            "parameter_crc32": crc, "node_count": node_count, "reg_max": 16,
            "arena_bytes": arena_bytes, "scratch_bytes": scratch_bytes,
            "float_head_bytes": 613200 * 4,
            "total_runtime_buffers": arena_bytes + 2 * 1228800 + scratch_bytes + 613200 * 4,
            "accuracy_accepted": False,
        }
        header = "\n".join([
            '#define V8_CLASS_DOMAIN "pin"', "#define V8_CLASS_COUNT 9u",
            "#define V8_INPUT_SIZE 640u", "#define V8_REG_MAX 16u",
            f"#define V8_PACKAGE_BYTES {len(blob)}u", f"#define V8_ARENA_BYTES {arena_bytes}u",
            f"#define V8_SCRATCH_COUNT {scratch_bytes // 4}u", "#define V8_HEAD_ELEMENTS 613200u",
            f'#define V8_CLASSES_SHA256 "{classes_hash}"',
            "static const V8Node v8_nodes[1] = {", "};", "",
        ])
        (self.package / "package.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        (self.package / "MODEL.V8P").write_bytes(blob)
        (self.package / "v8_generated_model.h").write_text(header, encoding="utf-8")

    def _args(self, *, xsa=None, hardware_report=None, domain="pin", package=None):
        return SimpleNamespace(
            domain=domain,
            package=self.package if package is None else Path(package),
            preflight_only=False,
            xsa=build466.EXPECTED_XSA if xsa is None else Path(xsa),
            hardware_report=(build466.EXPECTED_HARDWARE_REPORT if hardware_report is None
                             else Path(hardware_report)),
        )

    def _child_argv(self, *, xsa=None, hardware_report=None, domain="pin", package=None):
        selected_xsa = build466.EXPECTED_XSA if xsa is None else Path(xsa)
        selected_report = (build466.EXPECTED_HARDWARE_REPORT if hardware_report is None
                           else Path(hardware_report))
        selected_package = self.package if package is None else Path(package)
        return ["--xsa", str(selected_xsa), "--package", str(selected_package),
                "--domain", domain, "--hardware-report", str(selected_report)]

    def _assert_original_pin_binding(self):
        self.assertEqual((self.pin.EXPECTED_XSA, self.pin.EXPECTED_XSA_SHA256,
                          self.pin.EXPECTED_HARDWARE_REPORT, self.pin._BASE_VALIDATE_REQUEST),
                         self.original_pin_binding)

    def _assert_original_child_binding(self):
        self.assertEqual((self.legacy_child.EXPECTED_XSA,
                          self.legacy_child.EXPECTED_XSA_SHA256,
                          self.legacy_child.EXPECTED_HARDWARE_REPORT),
                         self.original_child_binding)

    def test_parent_accepts_exact_466_xsa_and_report_then_restores_original_binding(self):
        base_info = lambda args: {
            "xsa": Path(args.xsa).resolve(),
            "xsa_sha256": build466.EXPECTED_XSA_SHA256,
        }
        info = build466._strict_validate_request(self._args(), base_validate=base_info)
        self.assertEqual(info["pin640_package_contract"]["protocol"], "pin9-v8/2-input640")
        self.assertEqual(info["xsa"], build466.EXPECTED_XSA.resolve())
        self.assertEqual(info["xsa_sha256"], build466.EXPECTED_XSA_SHA256)
        self._assert_original_pin_binding()

    def test_parent_rejects_old_and_other_xsa_paths(self):
        old_xsa = PROJECT_ROOT / "deployment" / "build" / "z100_2026" / "c08a6449" / "system.xsa"
        for wrong_xsa in (old_xsa, self.temp_root / "other.xsa"):
            with self.subTest(xsa=wrong_xsa):
                with self.assertRaisesRegex(self.base.BuildInputError, "XSA path or SHA-256"):
                    build466._strict_validate_request(
                        self._args(xsa=wrong_xsa), base_validate=lambda args: {})
                self._assert_original_pin_binding()

    def test_parent_rejects_wrong_hardware_report_path(self):
        with self.assertRaisesRegex(self.base.BuildInputError, "not the report bound"):
            build466._strict_validate_request(
                self._args(hardware_report=self.temp_root / "wrong_report.json"),
                base_validate=lambda args: {})
        self._assert_original_pin_binding()

    def test_parent_rejects_non_pin_domain_and_non_pin640_package(self):
        with self.assertRaisesRegex(self.base.BuildInputError, "require --domain pin"):
            build466._strict_validate_request(
                self._args(domain="pcb"), base_validate=lambda args: {})
        self._assert_original_pin_binding()
        metadata_path = self.package / "package.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["domain"] = "pcb"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(self.base.BuildInputError, "local PIN classes"):
            build466._strict_validate_request(self._args(), base_validate=lambda args: {})
        self._assert_original_pin_binding()

    def test_child_accepts_exact_466_platform_and_restores_original_binding(self):
        package, contract = driver466._validate_child_request_for_466(self._child_argv())
        self.assertEqual(package, self.package.resolve())
        self.assertEqual(contract["protocol"], "pin9-v8/2-input640")
        self._assert_original_child_binding()

    def test_child_rejects_old_and_other_xsa_paths(self):
        old_xsa = PROJECT_ROOT / "deployment" / "build" / "z100_2026" / "c08a6449" / "system.xsa"
        for wrong_xsa in (old_xsa, self.temp_root / "other.xsa"):
            with self.subTest(xsa=wrong_xsa):
                with self.assertRaisesRegex(ValueError, "XSA path or SHA-256 mismatch"):
                    driver466._validate_child_request_for_466(
                        self._child_argv(xsa=wrong_xsa))
                self._assert_original_child_binding()

    def test_child_rejects_wrong_hardware_report_path(self):
        with self.assertRaisesRegex(ValueError, "hardware report path mismatch"):
            driver466._validate_child_request_for_466(
                self._child_argv(hardware_report=self.temp_root / "wrong_report.json"))
        self._assert_original_child_binding()

    def test_child_rejects_non_pin_domain_and_non_pin640_package(self):
        with self.assertRaisesRegex(ValueError, "requires --domain pin"):
            driver466._validate_child_request_for_466(self._child_argv(domain="pcb"))
        self._assert_original_child_binding()
        metadata_path = self.package / "package.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["domain"] = "pcb"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(self.pin.Pin640BuildInputError, "local PIN classes"):
            driver466._validate_child_request_for_466(self._child_argv())
        self._assert_original_child_binding()

    def test_parent_restores_generic_builder_globals_and_checks_package_binding(self):
        original_driver = self.base.DRIVER
        original_validate = self.base.validate_request
        original_failures = self.base._build_report_failures
        fake_validate = lambda args: {"xsa_sha256": build466.EXPECTED_XSA_SHA256}
        fake_failures = lambda *args: []

        def fake_main(argv=None):
            self.assertEqual(self.base.DRIVER, build466.PIN640_CHILD_DRIVER)
            info = self.base.validate_request(self._args())
            failures = self.base._build_report_failures(
                {"pin640_package_contract": {"wrong": "package"}}, 0, info)
            self.assertIn("driver report PIN640 package contract differs from host preflight", failures)
            return 7

        with mock.patch.object(self.base, "validate_request", fake_validate), \
                mock.patch.object(self.base, "_build_report_failures", fake_failures), \
                mock.patch.object(self.base, "main", fake_main):
            status = build466.main(["test-only"])
            self.assertEqual(status, 7)
            self.assertIs(self.base.validate_request, fake_validate)
            self.assertIs(self.base._build_report_failures, fake_failures)
            self.assertEqual(self.base.DRIVER, original_driver)
        self.assertIs(self.base.validate_request, original_validate)
        self.assertIs(self.base._build_report_failures, original_failures)
        self._assert_original_pin_binding()

    def test_child_main_restores_original_pin_driver_constants_on_return(self):
        original_main = self.legacy_child.main

        def fake_main(argv=None):
            self.assertEqual(self.legacy_child.EXPECTED_XSA, build466.EXPECTED_XSA)
            self.assertEqual(self.legacy_child.EXPECTED_XSA_SHA256,
                             build466.EXPECTED_XSA_SHA256)
            self.assertEqual(self.legacy_child.EXPECTED_HARDWARE_REPORT,
                             build466.EXPECTED_HARDWARE_REPORT)
            return 7

        with mock.patch.object(self.legacy_child, "main", fake_main):
            self.assertEqual(driver466.main(["test-only"]), 7)
        self.assertIs(self.legacy_child.main, original_main)
        self._assert_original_child_binding()


if __name__ == "__main__":
    unittest.main()
