import unittest

from tools.validate_z100_reuse_core import (
    evaluate_resource_screen,
    parse_check_timing_report,
    parse_ooc_summary,
    parse_resource_report,
    parse_sim_output,
    parse_route_report,
    parse_design_timing,
)


ZERO_CHECK_TIMING = """
1. checking no_clock (0)
2. checking constant_clock (0)
3. checking pulse_width_clock (0)
4. checking unconstrained_internal_endpoints (0)
5. checking no_input_delay (0)
6. checking no_output_delay (0)
7. checking multiple_clock (0)
8. checking generated_clocks (0)
9. checking loops (0)
10. checking partial_input_delay (0)
11. checking partial_output_delay (0)
12. checking latch_loops (0)
"""


class ReuseCoreValidationParserTests(unittest.TestCase):
    def test_real_route_and_design_timing_reports(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[2]
        timing=(root/'deployment/build/z100_impl/faa9a70f/timing.rpt').read_text()
        route=(root/'deployment/build/z100_impl/faa9a70f/route_status.rpt').read_text()
        self.assertEqual(parse_design_timing(timing)['status'],'PASS')
        self.assertEqual(parse_design_timing(timing)['wns'],1.378)
        self.assertEqual(parse_route_report(route)['status'],'PASS')
        self.assertNotEqual(parse_route_report(route.replace('21984 :','21983 :',1))['status'],'PASS')
        self.assertEqual(parse_design_timing(timing.replace('1.378','-1.378'))['status'],'FAIL')
        self.assertEqual(parse_design_timing('incomplete report')['status'],'UNKNOWN')

    def test_cycle_metrics_require_formula_and_real_handshakes(self):
        text = """
METRIC case=1 block=0 taps=4091 groups=1023 sites=4 lanes=32 start_to_issue=1 issue_cycles=1023 pipeline_flush=3 start_to_result=1026 drain_cycles=15 readback_handshakes=4 stall_cycles=11 total_job_cycles=1040
SIM_PASS jobs=1 preload_cycles=4092 sim_cycles=6000
"""
        result = parse_sim_output(text)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["jobs"], 1)
        self.assertEqual(result["metrics"][0]["groups"], 1023)

    def test_cycle_metrics_reject_unjustified_group_or_latency(self):
        text = """
METRIC case=1 block=0 taps=5 groups=1 sites=4 lanes=32 start_to_issue=1 issue_cycles=1 pipeline_flush=3 start_to_result=4 drain_cycles=15 readback_handshakes=4 stall_cycles=11 total_job_cycles=18
SIM_PASS jobs=1 preload_cycles=6 sim_cycles=100
"""
        with self.assertRaisesRegex(ValueError, r"ceil\(taps/4\)"):
            parse_sim_output(text)

    def test_sim_parser_rejects_failure_even_if_finish_marker_exists(self):
        with self.assertRaisesRegex(ValueError, "failure"):
            parse_sim_output("FAIL: dropped output\nSIM_PASS jobs=0 preload_cycles=0 sim_cycles=1")

    def test_ooc_result_extracts_actual_device_and_slack(self):
        result = parse_ooc_summary(
            "REUSE_OOC_RESULT frequency_mhz=200 setup_slack_ns=-0.125 hold_slack_ns=0.042 route=complete part=xc7z100ffg900-2"
        )
        self.assertEqual(result["frequency_mhz"], 200)
        self.assertEqual(result["setup_slack_ns"], -0.125)
        self.assertEqual(result["part"], "xc7z100ffg900-2")

    def test_check_timing_report_counts_unconstrained_and_port_coverage(self):
        result = parse_check_timing_report(
            ZERO_CHECK_TIMING,
            "4. checking unconstrained_internal_endpoints (0)\n"
            "There are 0 pins that are not constrained for maximum delay.",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["counts"]["unconstrained_internal_endpoints"], 0)
        self.assertEqual(len(result["counts"]), 12)

    def test_check_timing_report_does_not_pass_nonzero_counts(self):
        result = parse_check_timing_report(
            ZERO_CHECK_TIMING.replace("no_clock (0)", "no_clock (1)", 1).replace(
                "4. checking unconstrained_internal_endpoints (0)\n", "", 1
            ),
            "There are 2 endpoints which are unconstrained.",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["counts"]["no_clock_register_pins"], 1)
        self.assertEqual(result["counts"]["unconstrained_internal_endpoints"], 2)
        self.assertEqual(result["missing_counts"], [])

    def test_check_timing_parser_reads_vivado_table_counts(self):
        result = parse_check_timing_report(
            ZERO_CHECK_TIMING.replace("no_input_delay (0)", "no_input_delay (1370)"),
            "1. checking unconstrained_internal_endpoints (0)\n"
            "There are 0 pins that are not constrained for maximum delay.",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["counts"]["ports_without_input_delay"], 1370)
        self.assertEqual(result["counts"]["unconstrained_internal_endpoints"], 0)

    def test_check_timing_parser_requires_every_vivado_category(self):
        result = parse_check_timing_report(
            "1. checking no_clock (0)\n5. checking no_input_delay (0)\n",
            "",
        )
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIn("latch_loops", result["missing_counts"])

    def test_resource_parser_applies_screen_without_treating_unknown_as_pass(self):
        report = """
| Slice LUTs | 99,999 | 100000 | 100000 |
| Block RAM Tile | 128 | 256 | 256 |
| DSPs | 1,025 | 2,020 | 2,020 |
"""
        resources = parse_resource_report(report)
        self.assertEqual(resources, {"LUT": 99999, "BRAM36": 128, "DSP": 1025})
        self.assertEqual(evaluate_resource_screen(resources)["status"], "FAIL")
        self.assertEqual(evaluate_resource_screen({"DSP": 10})["status"], "UNKNOWN")

    def test_resource_parser_preserves_half_bram_tile_usage(self):
        resources = parse_resource_report("| Block RAM Tile | 3.5 | 256 | 256 |")
        self.assertEqual(resources["BRAM36"], 3.5)


if __name__ == "__main__":
    unittest.main()
