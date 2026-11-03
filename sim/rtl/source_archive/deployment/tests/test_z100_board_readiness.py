"""Fail-closed physical identity intake and offline evidence checks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import z100_board_readiness as readiness  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_record(root: Path) -> dict:
    evidence = []
    for kind in sorted(readiness.EXPECTED_EVIDENCE):
        file = root / "photos" / f"{kind}.txt"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"literal evidence capture: {kind}\n", encoding="utf-8")
        evidence.append({"kind": kind, "path": file.relative_to(root).as_posix(), "sha256": sha(file)})
    return {
        "schema_version": 1,
        "candidate_board": "ATK Z100 7100",
        "board": {
            "core_revision": "V1.1",
            "carrier_revision": "V1.2",
            "serial_number": "TEST-0001",
            "fpga_marking": "XC7Z100-2FFG900I",
            "fpga_part": "xc7z100ffg900-2",
        },
        "ddr": {
            "u5_marking": "NT5CC256M16ER-EK",
            "u6_marking": "NT5CC256M16ER-EK",
            "manufacturer": "Nanya",
            "full_part_number": "NT5CC256M16ER-EK",
            "speed_bin": "DDR3L-1066F",
            "temperature_grade": "commercial",
            "operating_temperature_c": 25,
            "voltage_v": 1.35,
            "device_width_bits": 16,
            "device_count": 2,
            "bus_width_bits": 32,
        },
        "ethernet_phy": {
            "u7_marking": "YT8531C",
            "manufacturer": "Motorcomm",
            "full_part_number": "YT8531C",
            "phy_id": "0x4f51e91b",
            "mdio_address": 7,
            "mac_interface": "RGMII",
            "rx_delay_owner": "phy",
            "tx_delay_owner": "phy",
        },
        "evidence": evidence,
    }


class Z100BoardReadinessTests(unittest.TestCase):
    def test_actual_offline_ddr_phy_evidence_is_consistent_and_still_open(self):
        with tempfile.TemporaryDirectory() as temp:
            result = readiness.collect_offline_evidence(ROOT, Path(temp), run_host_tests=False)
        self.assertEqual([], result["blockers"])
        self.assertTrue(result["offline_evidence_identity_sha256"])
        self.assertEqual("REVIEW_COMPLETE_WITH_CONDITIONAL_DDR_MISMATCH",
                         result["ddr_review"]["status"])
        self.assertTrue(result["ddr_review"]["conditional_tFAW_mismatch"])
        self.assertFalse(result["phy_review"]["active_firmware_integration"])

    def test_corrupt_ddr_declared_input_hash_blocks_offline_readiness(self):
        original_read = readiness._read_json

        def corrupt_ddr_hash(root, relative):
            value, path = original_read(root, relative)
            if relative.endswith("ddr_review/reference_review.json"):
                value["inputs"][0]["sha256"] = "0" * 64
            return value, path

        with tempfile.TemporaryDirectory() as temp, patch.object(
                readiness, "_read_json", side_effect=corrupt_ddr_hash):
            result = readiness.collect_offline_evidence(ROOT, Path(temp), run_host_tests=False)
        failed = {check["name"] for check in result["checks"] if not check["pass"]}
        self.assertIn("DDR review XSA and PS initialization hashes", failed)
        self.assertIn("all declared DDR review hashes match", failed)
        self.assertTrue(result["blockers"])

    def test_incomplete_template_fails_closed(self):
        result = readiness.validate_board_record(
            ROOT, ROOT / "deployment/board_support/z100_offline_readiness/board_record.template.json")
        self.assertEqual("BLOCKED_BOARD_IDENTITY_INPUTS", result["status"])
        self.assertFalse(result.get("activation_permitted", False))
        self.assertTrue(result["blockers"])

    def test_malformed_arm_object_collection_blocks_offline_readiness(self):
        original_loads = json.loads

        def malformed_objects(raw, *args, **kwargs):
            value = original_loads(raw, *args, **kwargs)
            if isinstance(value, dict) and value.get("status") == "PASS" and "objects" in value:
                value["objects"] = {"not": "an object list"}
            return value

        with tempfile.TemporaryDirectory() as temp, patch.object(
                readiness.json, "loads", side_effect=malformed_objects):
            result = readiness.collect_offline_evidence(ROOT, Path(temp), run_host_tests=False)
        check = next(row for row in result["checks"] if row["name"].startswith("YT8531 ARM object"))
        self.assertFalse(check["pass"])
        self.assertTrue(result["blockers"])

    def test_complete_identity_is_captured_but_never_activated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = valid_record(root)
            record_file = root / "board_record.json"
            record_file.write_text(json.dumps(record), encoding="utf-8")
            result = readiness.validate_board_record(root, record_file)
        self.assertEqual("IDENTITY_CAPTURED_WAITING_FOR_QUALIFICATION", result["status"])
        self.assertFalse(result["activation_permitted"])
        self.assertTrue(any("does not authorize activation" in item for item in result["blockers"]))

    def test_changed_photo_hash_blocks_identity_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = valid_record(root)
            record["evidence"][0]["sha256"] = "0" * 64
            record_file = root / "board_record.json"
            record_file.write_text(json.dumps(record), encoding="utf-8")
            result = readiness.validate_board_record(root, record_file)
        self.assertEqual("BLOCKED_BOARD_IDENTITY_INPUTS", result["status"])
        self.assertTrue(any("mismatched SHA-256" in item for item in result["blockers"]))

    def test_unknown_or_wrong_full_ddr_suffix_blocks_identity_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = valid_record(root)
            record["ddr"]["full_part_number"] = "NT5CC256M16"
            record_file = root / "board_record.json"
            record_file.write_text(json.dumps(record), encoding="utf-8")
            result = readiness.validate_board_record(root, record_file)
        self.assertEqual("BLOCKED_BOARD_IDENTITY_INPUTS", result["status"])
        self.assertTrue(any("full Nanya suffix" in item["detail"] for item in result["checks"] if not item["pass"]))

    def test_evidence_path_outside_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            record = valid_record(root)
            external = Path(outside) / "external-photo.txt"
            external.write_text("not project evidence", encoding="utf-8")
            record["evidence"][0]["path"] = str(external)
            record["evidence"][0]["sha256"] = sha(external)
            record_file = root / "board_record.json"
            record_file.write_text(json.dumps(record), encoding="utf-8")
            result = readiness.validate_board_record(root, record_file)
        self.assertEqual("BLOCKED_BOARD_IDENTITY_INPUTS", result["status"])
        self.assertTrue(any("outside the project" in item for item in result["blockers"]))

    def test_malformed_record_types_fail_closed_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = valid_record(root)
            record["board"]["core_revision"] = ["V1.1"]
            record["board"]["fpga_marking"] = {"marking": "XC7Z100-2FFG900I"}
            record["ddr"]["speed_bin"] = ["DDR3L-1066F"]
            record["ethernet_phy"]["mdio_address"] = "7"
            record["evidence"][0]["path"] = ["photos/core_marking.txt"]
            record_file = root / "board_record.json"
            record_file.write_text(json.dumps(record), encoding="utf-8")
            result = readiness.validate_board_record(root, record_file)
        self.assertEqual("BLOCKED_BOARD_IDENTITY_INPUTS", result["status"])
        self.assertTrue(result["blockers"])

    def test_duplicate_evidence_category_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = valid_record(root)
            record["evidence"].append(dict(record["evidence"][0]))
            record_file = root / "board_record.json"
            record_file.write_text(json.dumps(record), encoding="utf-8")
            result = readiness.validate_board_record(root, record_file)
        self.assertEqual("BLOCKED_BOARD_IDENTITY_INPUTS", result["status"])
        check = next(row for row in result["checks"] if row["name"].startswith("all six physical"))
        self.assertFalse(check["pass"])
        self.assertIn("duplicate kinds", check["detail"])

    def test_literal_markings_must_match_reported_part_numbers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = valid_record(root)
            record["board"]["fpga_marking"] = "XC7Z035-2FFG900I"
            record["ddr"]["u5_marking"] = "MT41K256M16RE-125"
            record["ethernet_phy"]["u7_marking"] = "YT8511"
            record_file = root / "board_record.json"
            record_file.write_text(json.dumps(record), encoding="utf-8")
            result = readiness.validate_board_record(root, record_file)
        self.assertEqual("BLOCKED_BOARD_IDENTITY_INPUTS", result["status"])
        failed_names = {check["name"] for check in result["checks"] if not check["pass"]}
        self.assertIn("core/carrier/serial and complete FPGA identity recorded", failed_names)
        self.assertIn("full U5/U6 DDR identity and documented geometry recorded", failed_names)
        self.assertIn("U7 YT8531C identity, MDIO address and RGMII ownership recorded", failed_names)

    @unittest.skipUnless(os.name == "nt", "Win32 long-path handling applies only on Windows")
    def test_windows_long_path_io_keeps_canonical_project_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            long_path = root.joinpath(*[f"segment_{index}_" + "x" * 36 for index in range(7)], "evidence.bin")
            self.assertGreater(len(str(long_path)), 260)
            try:
                readiness._io_path(long_path).parent.mkdir(parents=True, exist_ok=True)
                readiness._io_path(long_path).write_bytes(b"long path evidence")
                artifacts = {}
                resolved = readiness._add_artifact(root, artifacts, long_path, "long-path evidence")
                self.assertEqual(long_path.relative_to(root).as_posix(), resolved.relative_to(root).as_posix())
                self.assertEqual(hashlib.sha256(b"long path evidence").hexdigest(), readiness.sha256_file(resolved))
            finally:
                # Only remove the exact file and parents created above, using
                # long-path I/O. TemporaryDirectory then sees an empty root.
                self.assertTrue(root in long_path.resolve().parents)
                readiness._io_path(long_path).unlink(missing_ok=True)
                parent=long_path.parent
                while parent!=root:
                    readiness._io_path(parent).rmdir()
                    parent=parent.parent


if __name__ == "__main__":
    unittest.main()
