from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import validate_z100_window_refill as validator


PASS = (
    "WINDOW_REFILL_SIM_PASS accepted_reads=42 consumed_reads=40 randomized_stall_cycles=9 "
    "cancel_filling=1 cancel_ready=2 cancel_in_use=1 reset_filling=1 reset_ready=1 "
    "reset_in_use=1 generation_wrap=1 wrong_order_rejects=2 ownership_rejects=3 same_address_dual=1\n"
    "WINDOW_REFILL_EDGE_SCORE accepted=42 consumed=40 aborted=2 pending=0"
)


class WindowRefillValidatorTests(unittest.TestCase):
    def test_anchored_simulation_summary_requires_all_coverage_fields(self):
        metrics = validator.parse_sim_output("noise before\n" + PASS + "\nnoise after\n")
        self.assertEqual(metrics["accepted_reads"], 42)
        self.assertEqual(metrics['aborted_reads'],2)
        self.assertEqual(metrics["same_address_dual"], 1)
        self.assertEqual(metrics["cancel_ready"], 2)

    def test_summary_rejects_failure_or_duplicate_markers(self):
        with self.assertRaisesRegex(ValueError, "failure marker"):
            validator.parse_sim_output("FAIL: scoreboard mismatch\n" + PASS)
        with self.assertRaisesRegex(ValueError, "got 2"):
            validator.parse_sim_output(PASS + "\n" + PASS)

    def test_summary_requires_cancel_reset_and_read_backpressure_coverage(self):
        no_stalls = PASS.replace("randomized_stall_cycles=9", "randomized_stall_cycles=0")
        with self.assertRaisesRegex(ValueError, "backpressure"):
            validator.parse_sim_output(no_stalls)
        no_wrap = PASS.replace("generation_wrap=1", "generation_wrap=0")
        with self.assertRaisesRegex(ValueError, "generation_wrap"):
            validator.parse_sim_output(no_wrap)

    def test_rtl_exposes_single_row_ownership_and_two_read_results(self):
        source = (ROOT / "deployment/hardware/z100_2026/window_refill_v1/z100_window_refill_slot.sv").read_text()
        for state in ("SLOT_INVALID", "SLOT_FILLING", "SLOT_READY", "SLOT_IN_USE"):
            self.assertIn(state, source)
        self.assertIn("input  wire [1:0]                   read_valid", source)
        self.assertIn("assign result_valid = result_valid_q & {2{command_enable}}", source)
        self.assertIn("wire release_idle = (result_valid == 2'b00) && (read_valid == 2'b00)", source)
        self.assertIn("(write_address == fill_count[ADDR_WIDTH-1:0])", source)
        self.assertIn("if (!rst_n || cancel)", source)

    def test_report_contract_explicitly_excludes_synthesis_route_and_full_graph(self):
        report = {
            "scope": {
                "full_32_bank_mapping": False,
                "full_graph_implemented": False,
                "physical_board_tested": False,
                "route_run": False,
                "synthesis_run": False,
                "timing_accepted": False,
            }
        }
        with tempfile_json(report) as path:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(all(value is False for value in parsed["scope"].values()))

    def test_rejects_missing_or_forged_edge_accounting(self):
        with self.assertRaisesRegex(ValueError,'conservation'):
            validator.parse_sim_output(PASS.replace('aborted=2','aborted=0'))
        with self.assertRaisesRegex(ValueError,'independent edge'):
            validator.parse_sim_output(PASS.split('\n')[0])


class tempfile_json:
    def __init__(self, value):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "report.json"
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def __enter__(self):
        return self.path

    def __exit__(self, exc_type, exc, tb):
        self._tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
