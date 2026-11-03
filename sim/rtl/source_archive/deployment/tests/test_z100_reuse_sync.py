from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/validate_z100_reuse_sync.py"
SPEC = importlib.util.spec_from_file_location("validate_z100_reuse_sync", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def check_report(*, values: dict[str, int] | None = None, omitted: str | None = None) -> str:
    rows = []
    for name in validator.CHECK_CATEGORIES:
        if name == omitted:
            continue
        count = (values or {}).get(name, 0)
        rows.append(f"{len(rows) + 1}. checking {name} ({count})")
    return "\n".join(rows) + "\n"


class ReuseSyncValidationTests(unittest.TestCase):
    def test_actual_vivado_toc_is_not_duplicate_body(self) -> None:
        path = ROOT / 'validation/board_z100/reuse_sync_fixture/20261021T130404Z_2da5e005/check_timing_routed.rpt'
        self.assertTrue(all(x == 0 for x in validator.parse_check_timing(path.read_text()).values()))
        with self.assertRaises(ValueError):
            validator.parse_check_timing('Table of Contents\n' + check_report())

    def test_route_counts_are_parsed_from_actual_report_fields(self) -> None:
        report = """
       # of routable nets..................... :       68088
           # of fully routed nets............. :       68088
       # of nets with routing errors.......... :           0
"""
        self.assertEqual(
            validator.parse_route_status(report),
            {"routable": 68088, "routed": 68088, "errors": 0},
        )

    def test_route_parser_rejects_missing_or_duplicate_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "routable"):
            validator.parse_route_status("# of fully routed nets............. : 1\n# of nets with routing errors.......... : 0")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validator.parse_route_status(
                "# of routable nets..................... : 1\n"
                "# of routable nets..................... : 1\n"
                "# of fully routed nets............. : 1\n"
                "# of nets with routing errors.......... : 0"
            )

    def test_check_timing_requires_all_twelve_categories_zero(self) -> None:
        parsed = validator.parse_check_timing(check_report())
        self.assertEqual(set(parsed), set(validator.CHECK_CATEGORIES))
        self.assertTrue(all(count == 0 for count in parsed.values()))
        parsed_nonzero = validator.parse_check_timing(check_report(values={"no_clock": 1}))
        self.assertEqual(parsed_nonzero["no_clock"], 1)
        self.assertEqual(
            validator.classify_run(
                {
                    "frequency_mhz": 100,
                    "internal_wns_ns": 1.0,
                    "internal_whs_ns": 1.0,
                    "routable": 100,
                    "routed": 100,
                    "route_errors": 0,
                    "lut": 1000,
                    "dsp": 0,
                    "bram36_equivalent": 1.0,
                    "bufg": 1,
                    "registers": 20000,
                },
                {"routable": 100, "routed": 100, "errors": 0},
                parsed_nonzero,
                {"status": "PASS"},
            ),
            "CHECK_TIMING_FAIL",
        )
        with self.assertRaisesRegex(ValueError, "partial_output_delay"):
            validator.parse_check_timing(check_report(omitted="partial_output_delay"))

    def test_sync_result_requires_exact_fields_and_finite_numbers(self) -> None:
        line = (
            "SYNC_FIXTURE_RESULT frequency_mhz=100 internal_wns_ns=0.129 "
            "internal_whs_ns=0.056 routable=68088 routed=68088 route_errors=0 "
            "lut=49380 dsp=0 bram36_equivalent=38.0 bufg=1 registers=21528"
        )
        parsed = validator.parse_sync_result(line)
        self.assertEqual(parsed["frequency_mhz"], 100)
        self.assertEqual(parsed["internal_whs_ns"], 0.056)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validator.parse_sync_result(line + "\n" + line)
        with self.assertRaisesRegex(ValueError, "fields differ"):
            validator.parse_sync_result(line.replace(" bufg=1", ""))
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            validator.parse_sync_result(line.replace("internal_wns_ns=0.129", "internal_wns_ns=NaN"))

    def test_classifier_requires_real_clock_route_and_internal_timing_pass(self) -> None:
        metrics = {
            "frequency_mhz": 100,
            "internal_wns_ns": 0.129,
            "internal_whs_ns": 0.056,
            "routable": 100,
            "routed": 100,
            "route_errors": 0,
            "lut": 1000,
            "dsp": 0,
            "bram36_equivalent": 1.0,
            "bufg": 1,
            "registers": 20000,
        }
        route = {"routable": 100, "routed": 100, "errors": 0}
        checks = {key: 0 for key in validator.CHECK_CATEGORIES}
        sim = {"status": "PASS"}
        self.assertEqual(validator.classify_run(metrics, route, checks, sim), "PASS_SYNC_FIXTURE_TIMING")
        bad_hold = {**metrics, "internal_whs_ns": -0.001}
        self.assertEqual(validator.classify_run(bad_hold, route, checks, sim), "INTERNAL_TIMING_FAIL")
        bad_clock = {**metrics, "bufg": 0}
        self.assertEqual(validator.classify_run(bad_clock, route, checks, sim), "CLOCK_TOPOLOGY_OR_CORE_LOST")
        bad_route = {**route, "routed": 99}
        self.assertEqual(validator.classify_run(metrics, bad_route, checks, sim), "ROUTE_REPORT_MISMATCH")


if __name__ == "__main__":
    unittest.main()
