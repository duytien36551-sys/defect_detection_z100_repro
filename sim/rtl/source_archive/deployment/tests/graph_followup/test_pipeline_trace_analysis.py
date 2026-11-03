"""Synthetic checks of reporting arithmetic; never a board benchmark."""
import copy
from datetime import datetime, timezone
import hashlib
import heapq
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"tools"))
import analyze_z100_pipeline_trace as a


def fixture(latency_ns=20_000_000):
    rows = []
    now = 0
    for group, count in [(-1, 20), (0, 1000), (1, 1000), (2, 1000)]:
        for frame in range(count):
            rows.append({"frame_id": f"{group}:{frame}", "group": group, "input_start_ns": now,
                         "terminal_ns": now+latency_ns, "status": "ok", "queue_depth_before": 0})
            now += 30_000_000
        now = max(now, rows[-1]["terminal_ns"])
    outstanding = []
    for row in rows:
        while outstanding and outstanding[0] <= row["input_start_ns"]:
            heapq.heappop(outstanding)
        row["queue_depth_before"] = len(outstanding)
        heapq.heappush(outstanding, row["terminal_ns"])
    return {"schema": "z100-full-pipeline-trace/1", "batch_size": 1, "capture_kind": "synthetic",
            "model_identity": copy.deepcopy(a.IDENTITY), "timer": {"unit": "ns", "monotonic": True, "clock_id": "synthetic"},
            "start_boundary": "sender_before_first_input_byte", "end_boundary": "sender_after_complete_result",
            "included_stages": sorted(a.STAGES), "ui_dwell_included": False, "frames": rows}


def with_milestones(trace):
    for row in trace["frames"]:
        for key, offset in zip(a.SENDER_MILESTONES, (1, 3, 4, 9, 19)):
            row[key] = row["input_start_ns"]+offset*1_000_000
    return trace


class TraceChecks(unittest.TestCase):
    def test_sender_stages_account_for_latency_and_all_serial_gaps(self):
        report = a.analyze(with_milestones(fixture()))
        for group in report["groups"]:
            profile = group["sender_profile"]
            self.assertEqual(profile["status"], "COMPLETE_SUCCESSFUL_FRAMES")
            self.assertEqual(profile["profiled_frames"], 1000)
            self.assertEqual([profile["intervals"][key]["p50_ms"] for key in a.SENDER_INTERVALS], [1,2,1,5,10,1])
            stage_total = sum(v["total_ns"] for v in profile["intervals"].values())
            wall = profile["serial_wall_accounting"]
            self.assertEqual(stage_total, 20_000_000_000)
            self.assertEqual(wall["attempt_interval_total_ns"], stage_total)
            self.assertEqual(wall["interframe_gaps"]["samples"], 999)
            self.assertEqual(stage_total+wall["interframe_gaps"]["total_ns"], group["wall_span_ns"])
        self.assertFalse(report["physical_30fps_accepted"])

    def test_legacy_missing_and_partial_frame_coverage_are_explicit(self):
        trace = fixture()
        profile = a.analyze(trace)["groups"][0]["sender_profile"]
        self.assertEqual(profile["status"], "NOT_EVALUATED_MILESTONES_MISSING")
        self.assertIsNone(profile["intervals"]["rgb_send"]["p95_ms"])
        decorated = with_milestones(fixture())
        trace["frames"][20] = decorated["frames"][20]
        profile = a.analyze(trace)["groups"][0]["sender_profile"]
        self.assertEqual((profile["profiled_frames"], profile["missing_successful_frames"]), (1,999))
        self.assertEqual(profile["status"], "PARTIAL_SUCCESSFUL_FRAMES")

    def test_invalid_sender_milestones_cannot_produce_stage_metrics(self):
        mutations = [lambda row: row.pop("connected_ns"),
                     lambda row: row.update(rgb_send_start_ns=row["hello_complete_ns"]-1),
                     lambda row: row.update(connected_ns=row["input_start_ns"]-1),
                     lambda row: row.update(result_complete_ns=row["terminal_ns"]+1),
                     lambda row: row.update(hello_complete_ns=True)]
        for mutate in mutations:
            trace = with_milestones(fixture())
            mutate(trace["frames"][20])
            with self.assertRaises(ValueError):
                a.analyze(trace)

    def test_equal_milestones_allowed_at_timer_resolution(self):
        trace = with_milestones(fixture())
        for row in trace["frames"]:
            row["rgb_send_start_ns"] = row["rgb_send_end_ns"]
        profile = a.analyze(trace)["groups"][0]["sender_profile"]
        self.assertEqual(profile["intervals"]["rgb_send"]["p50_ms"], 0)

    def test_error_duration_stays_in_wall_accounting_not_success_profile(self):
        trace = with_milestones(fixture())
        trace["frames"][21]["status"] = "error"
        trace["frames"][21].pop("result_complete_ns")
        group = a.analyze(trace)["groups"][0]
        profile = group["sender_profile"]
        self.assertEqual(profile["profiled_frames"], 999)
        self.assertEqual(profile["serial_wall_accounting"]["attempt_interval_total_ns"], 20_000_000_000)
        self.assertEqual(group["performance_gate"], "FAIL")

    def test_pipeline_intervals_never_summed_as_serial_wall_time(self):
        profile = a.analyze(with_milestones(fixture(100_000_000)))["groups"][0]["sender_profile"]
        wall = profile["serial_wall_accounting"]
        self.assertEqual(wall["status"], "NOT_ADDITIVE_OVERLAPPING_REQUESTS")
        self.assertIsNone(wall["attempt_interval_total_ns"])
        self.assertIsNone(wall["interframe_gaps"])

    def test_sender_stage_p95_uses_individual_samples(self):
        trace = with_milestones(fixture())
        for index, row in enumerate(trace["frames"][20:1020]):
            row["connected_ns"] = row["input_start_ns"]+(index+1)*1000
        values = a.analyze(trace)["groups"][0]["sender_profile"]["intervals"]["input_load_and_connect"]
        self.assertEqual((values["p50_ms"],values["p95_ms"],values["samples"]), (.5005,.95,1000))

    def test_exact_span_quantile_and_synthetic_is_not_board(self):
        r = a.analyze(fixture())
        self.assertEqual(r["trace_performance_gate"], "SIMULATION_ONLY")
        self.assertFalse(r["physical_30fps_accepted"])
        for g in r["groups"]:
            self.assertEqual(g["wall_span_ns"], 999*30_000_000+20_000_000)
            self.assertAlmostEqual(g["sustained_fps"], 1e12/g["wall_span_ns"])
            self.assertEqual((g["latency_p50_ms"], g["latency_p95_ms"]), (20, 20))

    def test_overlapping_frames_latency_is_not_inverse_fps(self):
        r = a.analyze(fixture(100_000_000))
        self.assertGreater(r["groups"][0]["sustained_fps"], 30)
        self.assertEqual(r["groups"][0]["latency_p95_ms"], 100)
        self.assertEqual(r["groups"][0]["queue_depth_max"], 3)

    def test_idle_gap_counts_against_throughput(self):
        t = fixture()
        for row in t["frames"][520:]:
            row["input_start_ns"] += 5_000_000_000
            row["terminal_ns"] += 5_000_000_000
        self.assertEqual(a.analyze(t)["groups"][0]["performance_gate"], "FAIL")

    def test_errors_and_drops_remain_in_submitted_count(self):
        t = fixture()
        t["frames"][21]["status"] = "error"
        t["frames"][22]["status"] = "dropped"
        g = a.analyze(t)["groups"][0]
        self.assertEqual((g["submitted"], g["completed_ok"], g["errors"], g["dropped"]), (1000, 998, 1, 1))
        self.assertEqual(g["performance_gate"], "FAIL")

    def test_bad_evidence_rejected(self):
        for mutate in [lambda t: t["frames"][21].update(frame_id=t["frames"][20]["frame_id"]),
                       lambda t: t["frames"][21].update(terminal_ns=0),
                       lambda t: t["frames"].pop(),
                       lambda t: t.update(start_boundary="compute_only"),
                       lambda t: t["model_identity"].update(package_sha256="0"*64),
                       lambda t: t.update(ui_dwell_included=True),
                       lambda t: t["frames"][21].update(queue_depth_before=9),
                       lambda t: t.update(batch_size=True),
                       lambda t: t["frames"][19].update(terminal_ns=10**12)]:
            t = fixture()
            mutate(t)
            with self.assertRaises(ValueError):
                a.analyze(t)

    def test_imported_declaration_does_not_grant_physical_acceptance(self):
        t = fixture()
        t["capture_kind"] = "physical_board"
        r = a.analyze(t)
        self.assertEqual(r["trace_performance_gate"], "PASS")
        self.assertFalse(r["physical_30fps_accepted"])

    def test_p95_nearest_rank(self):
        t = fixture()
        for i, row in enumerate(t["frames"][20:1020]):
            row["terminal_ns"] = row["input_start_ns"] + (i+1)*1000
        g = a.analyze(t)["groups"][0]
        self.assertEqual(g["latency_p95_ms"], .95)
        self.assertEqual(g["latency_p50_ms"], .5005)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TraceChecks))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = ROOT/"validation/board_z100/pipeline_trace_analyzer_selfcheck"/stamp
    out.mkdir(parents=True)
    report = {"status": "PASS_SYNTHETIC_ANALYZER_CHECKS_ONLY" if result.wasSuccessful() else "FAIL",
              "tests": result.testsRun, "board_access": False, "physical_30fps_accepted": False,
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [Path(__file__), Path(a.__file__)]}}
    (out/"result.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf8")
    print(json.dumps({"report": str(out/"result.json"), **report}))
    sys.exit(0 if result.wasSuccessful() else 1)
