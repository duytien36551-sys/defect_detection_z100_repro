import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import validate_z100_reuse_handshake as fixture


class ReuseHandshakeFixtureTests(unittest.TestCase):
    def test_full_simulation_metrics_require_every_scanned_lane_and_backpressure(self):
        output = """JOB_PASS taps=4091 sites=4 lanes=32 scanned_words=128 stalls=44 scan_cycles=172
JOB_PASS taps=5 sites=4 lanes=32 scanned_words=128 stalls=40 scan_cycles=168
JOB_PASS taps=129 sites=4 lanes=32 scanned_words=128 stalls=42 scan_cycles=170
JOB_PASS taps=128 sites=4 lanes=32 scanned_words=128 stalls=42 scan_cycles=170
CANCEL_RELOAD_PASS cycles=4092
RESET_STALLED_RESULT_PASS wait_cycles=42
HANDSHAKE_SIM_PASS accepted_jobs=6 completed_jobs=4 scanned_words=512 blocked_request_cycles=120 output_stall_cycles=168 total_cycles=60000
"""
        metrics = fixture.parse_sim_output(output)
        self.assertEqual(metrics["scanned_words"], 512)
        self.assertEqual([job["taps"] for job in metrics["jobs"]], [4091, 5, 129, 128])
        self.assertTrue(metrics["cancel_reload_pass"])
        self.assertTrue(metrics["reset_stalled_result_pass"])

    def test_simulation_parser_rejects_incomplete_output_capture(self):
        output = "HANDSHAKE_SIM_PASS accepted_jobs=6 completed_jobs=4 scanned_words=128 blocked_request_cycles=120 output_stall_cycles=168 total_cycles=60000"
        with self.assertRaises(ValueError):
            fixture.parse_sim_output(output)

    def test_simulation_parser_rejects_failure_marker(self):
        output = "FAIL: output mismatch\nHANDSHAKE_SIM_PASS accepted_jobs=6 completed_jobs=4 scanned_words=512 blocked_request_cycles=120 output_stall_cycles=168 total_cycles=60000"
        with self.assertRaises(ValueError):
            fixture.parse_sim_output(output)

    def test_route_parser_keeps_core_and_external_output_results_separate(self):
        output = "HANDSHAKE_ROUTE_RESULT all_setup_ns=-1.20 all_hold_ns=0.02 internal_setup_ns=-0.25 internal_hold_ns=0.03 core_setup_ns=-0.10 core_hold_ns=0.04 input_setup_ns=0.15 input_hold_ns=0.01 output_setup_ns=-1.20 output_hold_ns=0.00 routable=35000 routed=35000 route_errors=0 lut=23000 dsp=512 bram36_equivalent=38.0 bufg=1 registers=15000 core_registers=14000"
        metrics = fixture.parse_route_marker(output)
        self.assertEqual(metrics["core_setup_slack_ns"], -0.10)
        self.assertEqual(metrics["sequential_to_output_setup_slack_ns"], -1.20)
        self.assertEqual(metrics["sequential_to_output_hold_slack_ns"], 0.0)
        self.assertEqual(metrics["input_setup_slack_ns"], 0.15)
        self.assertEqual(metrics["dsp"], 512)
        self.assertEqual(metrics["bram36_equivalent"], 38.0)

    def test_route_parser_rejects_missing_external_output_measurement(self):
        output = "HANDSHAKE_ROUTE_RESULT all_setup_ns=-0.25 all_hold_ns=0.03 internal_setup_ns=-0.25 internal_hold_ns=0.03 core_setup_ns=-0.10 core_hold_ns=0.04 input_setup_ns=0.15 input_hold_ns=0.01 routable=35000 routed=35000 route_errors=0 lut=23000 dsp=512 bram36_equivalent=38.0 bufg=1 registers=15000 core_registers=14000"
        with self.assertRaises(ValueError):
            fixture.parse_route_marker(output)

    def test_check_timing_parser_requires_all_twelve_zero_categories(self):
        report = "\n".join(
            f"checking {category} (0)"
            for category in fixture.TIMING_CHECK_CATEGORIES
        )
        self.assertEqual(len(fixture.parse_check_timing_report(report)), 12)
        with self.assertRaises(ValueError):
            fixture.parse_check_timing_report(report.replace("checking no_input_delay (0)", "checking no_input_delay (1)"))

    def test_timing_marker_requires_global_core_input_and_output_setup_hold(self):
        output = "HANDSHAKE_TIMING_CHECK phase=synth bufg=1 registers=16000 core_regs=14500 check_categories=12 all_setup_ns=-0.12 all_hold_ns=0.03 core_setup_ns=-0.10 core_hold_ns=0.04 input_setup_ns=0.20 input_hold_ns=0.01 output_setup_ns=-0.50 output_hold_ns=0.00 status=PASS"
        metrics = fixture.parse_timing_check_marker(output, "synth")
        self.assertEqual(metrics["check_timing_category_count"], 12)
        self.assertEqual(metrics["output_setup_slack_ns"], -0.50)
        self.assertEqual(metrics["input_hold_slack_ns"], 0.01)

    def test_source_manifest_binds_core_fixture_and_runner(self):
        manifest = fixture.source_manifest()
        self.assertIn("deployment\\hardware\\z100_2026\\tile_reuse_core_v2\\z100_tile_reuse_core.v", manifest)
        self.assertIn("deployment\\hardware\\z100_2026\\reuse_handshake_fixture_v1\\handshake_constraints.xdc", manifest)
        self.assertIn("tools\\validate_z100_reuse_handshake.py", manifest)
        self.assertEqual(len(set(manifest.values())), len(manifest))

    def test_xdc_explicitly_constrains_all_fixture_io_without_exceptions(self):
        xdc = (fixture.FIXTURE / "handshake_constraints.xdc").read_text(encoding="utf-8")
        self.assertIn("set_input_delay -clock [get_clocks core_clk] -max 1.000", xdc)
        self.assertIn("set_output_delay -clock [get_clocks core_clk] -max 0.500", xdc)
        self.assertIn("set_load 5.000 $fixture_outputs", xdc)
        self.assertNotIn("set_data_inputs", xdc)
        self.assertNotIn("set_false_path", xdc)
        self.assertNotIn("set_multicycle_path", xdc)


if __name__ == "__main__":
    unittest.main()
