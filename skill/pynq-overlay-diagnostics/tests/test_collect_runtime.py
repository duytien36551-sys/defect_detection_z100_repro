"""Simulation-only unit tests; these mocks do not exercise or verify a board."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "collect_runtime.py"
SPEC = importlib.util.spec_from_file_location("collect_runtime", MODULE_PATH)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class RuntimeCollectorSimulationTests(unittest.TestCase):
    """All cases use simulated dependency objects, never PYNQ hardware."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bit = self.root / "fixture.bit"
        self.hwh = self.root / "fixture.hwh"
        self.bit.write_bytes(b"simulated-bit-bytes")
        self.hwh.write_bytes(b"simulated-hwh-bytes")

    def tearDown(self):
        self.temp.cleanup()

    def _collect(self, loaded_value, infer_hwh=False):
        calls = []
        overlays = []

        class FakeOverlay:
            def __init__(self):
                self.looked_up_names = []
                self.ip_dict = {
                    "axi_dma_0": {
                        "type": "xilinx.com:ip:axi_dma:7.1",
                        "phys_addr": 4096,
                        "registers": {"DMACR": {"address_offset": 48, "size": 32}},
                    },
                    "metadata_only": {"type": "example:ip:metadata_only:1.0"},
                }
                overlays.append(self)

            def is_loaded(self):
                return loaded_value

            def __getattr__(self, name):
                self.looked_up_names.append(name)
                raise AssertionError("unexpected dynamic IP/driver lookup: " + name)

        def fake_overlay(bit, *, download):
            calls.append((bit, download))
            return FakeOverlay()

        fake_pynq = SimpleNamespace(__version__="simulation-only", Overlay=fake_overlay)
        fake_numpy = SimpleNamespace(__version__="simulation-only")
        report = collector.collect_runtime(
            self.bit,
            None if infer_hwh else self.hwh,
            pynq_module=fake_pynq,
            numpy_module=fake_numpy,
        )
        return report, calls, overlays

    def test_download_false_hashes_metadata_and_is_loaded_false(self):
        report, calls, overlays = self._collect(False)
        self.assertEqual(report["status"], "observed")
        self.assertEqual(report["collection_context"], "injected_dependencies_simulation")
        self.assertEqual(calls, [(str(self.bit), False)])
        self.assertEqual(report["artifacts"]["bit"]["sha256"], hashlib.sha256(self.bit.read_bytes()).hexdigest())
        self.assertEqual(report["artifacts"]["hwh"]["sha256"], hashlib.sha256(self.hwh.read_bytes()).hexdigest())
        self.assertIn("axi_dma_0", report["overlay"]["ip_dict"])
        self.assertEqual(report["overlay"]["register_metadata"]["by_ip"]["axi_dma_0"]["DMACR"]["address_offset"], 48)
        self.assertTrue(report["overlay"]["is_loaded"]["observed"])
        self.assertIs(report["overlay"]["is_loaded"]["value"], False)
        self.assertFalse(report["hardware_actions"]["functional_outputs_verified"])
        self.assertEqual(overlays[0].looked_up_names, [])

    def test_is_loaded_none_is_recorded_as_observed_none(self):
        report, calls, _ = self._collect(None)
        self.assertEqual(calls[0][1], False)
        self.assertTrue(report["overlay"]["is_loaded"]["observed"])
        self.assertIsNone(report["overlay"]["is_loaded"]["value"])
        self.assertIn("not output verification", report["overlay"]["is_loaded"]["provenance"])

    def test_default_hwh_candidate_is_hashed_without_claiming_consumption(self):
        report, calls, _ = self._collect(False, infer_hwh=True)
        self.assertEqual(calls, [(str(self.bit), False)])
        hwh = report["artifacts"]["hwh"]
        self.assertEqual(hwh["selection"], "adjacent_candidate")
        self.assertEqual(hwh["sha256"], hashlib.sha256(self.hwh.read_bytes()).hexdigest())
        self.assertFalse(hwh["consumption_claim"])

    def test_adjacent_hwh_is_hashed_as_candidate_without_claiming_consumption(self):
        report, _, _ = self._collect(False)
        hwh = report["artifacts"]["hwh"]
        self.assertEqual(hwh["selection"], "explicit_path")
        self.assertFalse(hwh["consumption_claim"])
        self.assertEqual(hwh["sha256"], hashlib.sha256(self.hwh.read_bytes()).hexdigest())
        self.assertIn("does not prove Overlay consumed", report["artifacts"]["hwh_note"])

    def test_cli_refuses_output_alias_before_collecting_even_for_missing_input(self):
        output = self.root / "missing.bit"
        with mock.patch.object(collector, "collect_runtime") as collect:
            with self.assertRaises(SystemExit) as raised:
                collector.main(["--bit", str(output), "--out", str(output)])
        self.assertEqual(raised.exception.code, 2)
        collect.assert_not_called()

    def test_absent_adjacent_hwh_is_reported_as_candidate_not_error(self):
        other_bit = self.root / "other.bit"
        other_bit.write_bytes(b"simulation")
        report, _, _ = self._collect(False)
        inferred, error = collector._hwh_artifact(other_bit, None)
        self.assertIsNone(error)
        self.assertEqual(inferred["selection"], "adjacent_candidate")
        self.assertEqual(inferred["state"], "candidate_not_found")
        self.assertIsNone(inferred["sha256"])

    def test_missing_pynq_writes_unavailable_report_and_nonzero_cli_status(self):
        output = self.root / "unavailable.json"

        def fake_import(name):
            if name == "numpy":
                return SimpleNamespace(__version__="simulation-only")
            raise ModuleNotFoundError("No module named 'pynq'", name="pynq")

        with mock.patch.object(collector.importlib, "import_module", side_effect=fake_import):
            status = collector.main(["--bit", str(self.bit), "--hwh", str(self.hwh), "--out", str(output)])
        self.assertEqual(status, 2)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "unavailable")
        self.assertIsNone(report["versions"]["pynq"])
        self.assertFalse(report["overlay"]["constructed"])
        self.assertEqual(report["collection_context"], "runtime")


if __name__ == "__main__":
    unittest.main()
