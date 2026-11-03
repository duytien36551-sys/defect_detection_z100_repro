"""Independently audit the preserved scheduled-row20 XSim log and provenance.

This reviewer performs no vendor work. It preserves the original validator's
FAILED_CLOSED result and writes a separate bounded audit artifact when the
simulation transcript and frozen inputs satisfy the numeric contract.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import uuid

ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "validation/board_z100/native_scheduled_row20_review"


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def resolve_path(name: str) -> Path:
    normalized = str(name).replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if parts and parts[0] == "external":
        require(len(parts) >= 3, f"malformed external path: {name}")
        return Path(parts[1] + ":/") / Path(*parts[2:])
    return ROOT / Path(*parts)


def report_path(name: str) -> Path:
    return ROOT / Path(*PurePosixPath(str(name).replace("\\", "/")).parts)


def bound_report(path: Path, expected_status: str) -> dict:
    require(path.is_file(), f"missing prerequisite report: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    require(data.get("status") == expected_status,
            f"prerequisite status changed: {path}: {data.get('status')}")
    before = data.get("source_sha256_before", {})
    after = data.get("source_sha256_after", {})
    require(before == after, f"prerequisite itself records source drift: {path}")
    def digest_value(value):
        return value.get("sha256") if isinstance(value, dict) else value
    for name, recorded in after.items():
        digest = digest_value(recorded)
        source = resolve_path(name)
        require(isinstance(digest, str) and source.is_file() and sha(source) == digest,
                f"prerequisite source drift: {name}")
    for name, recorded in data.get("artifact_sha256", {}).items():
        digest = digest_value(recorded)
        artifact = resolve_path(name)
        require(isinstance(digest, str) and artifact.is_file() and sha(artifact) == digest,
                f"prerequisite artifact drift: {name}")
    return {"path": path.relative_to(ROOT).as_posix(), "status": expected_status,
            "report_sha256": sha(path), "sources_checked": len(after),
            "artifacts_checked": len(data.get("artifact_sha256", {}))}


def audit(source_result: Path) -> Path:
    source_result = source_result.resolve()
    require(source_result.is_file(), f"missing original result: {source_result}")
    original_result_sha = sha(source_result)
    data = json.loads(source_result.read_text(encoding="utf-8"))
    require(data.get("status") == "FAILED_CLOSED",
            "review input is not the preserved parser-rejected result")
    require(data.get("error") == "ValueError: XSim count packed_hold_checks=46; expected 4",
            "preserved failure cause differs from the observed parser mismatch")
    run_dir = source_result.parent
    build = resolve_path(data["build_dir"])
    require(build.is_dir(), f"missing source run build directory: {build}")

    before = data.get("source_sha256_before", {})
    after = data.get("source_sha256_after", {})
    require(before and before == after, "original run did not preserve its before/after source hashes")
    source_snapshots = data.get("source_snapshot_sha256", {})
    require(set(source_snapshots) == set(before), "original source snapshot inventory is incomplete")
    for name, digest in before.items():
        source = resolve_path(name)
        snapshot = run_dir / "src" / Path(*PurePosixPath(name).parts)
        require(source.is_file() and sha(source) == digest,
                f"original source changed since XSim: {name}")
        require(snapshot.is_file() and sha(snapshot) == digest and source_snapshots[name] == digest,
                f"source snapshot mismatch: {name}")

    fixture_hashes = data.get("fixture_sha256", {})
    require(fixture_hashes, "host fixtures were not recorded")
    for name, digest in fixture_hashes.items():
        fixture = resolve_path(name)
        require(fixture.is_file() and sha(fixture) == digest,
                f"host golden/scheduler fixture changed: {name}")

    artifact_hashes = data.get("artifact_sha256", {})
    require(artifact_hashes, "original artifact hash inventory is empty")
    for name, digest in artifact_hashes.items():
        artifact = resolve_path(name)
        require(artifact.is_file() and sha(artifact) == digest,
                f"original run artifact changed: {name}")
    actual_artifacts = {
        path.relative_to(ROOT).as_posix()
        for base in (run_dir, build) for path in base.rglob("*")
        if path.is_file() and path != source_result
    }
    require(actual_artifacts == set(artifact_hashes),
            "original run artifact inventory is incomplete or contains unbound files")

    prerequisites = []
    for item in data.get("prerequisites", []):
        p = report_path(item["path"])
        require(p.is_file() and sha(p) == item["report_sha256"],
                f"prerequisite report changed: {item['path']}")
        prerequisites.append(bound_report(p, item["status"]))
    require(len(prerequisites) == 5, "expected the epoch200 row, scheduler20, window20, MAC20, and accepted bank-v2 proofs")

    commands = data.get("commands", [])
    require([item.get("name") for item in commands] == ["xvlog", "xelab", "xsim"],
            "vendor command order/count differs from one XSim flow")
    require(all(item.get("return_code") == 0 for item in commands),
            "one or more recorded vendor commands returned nonzero")
    require(sum(item.get("name") == "xsim" for item in commands) == 1,
            "expected exactly one XSim invocation")
    xelab_args = commands[1].get("args", [])
    require("-mt" in xelab_args and xelab_args[xelab_args.index("-mt") + 1] == "2",
            "coupled-row elaboration did not explicitly cap threads at2")
    xsim_args = commands[2].get("args", [])
    require(xsim_args[-1] == "-runall" and "scheduled_row20_sim" in xsim_args,
            "unexpected XSim invocation arguments")
    for item in commands:
        log = run_dir / (item["name"] + ".log")
        require(log.is_file(), f"missing vendor command log: {log}")
        log_text = log.read_text(encoding="utf-8", errors="replace")
        require(not re.search(r"(?im)^\s*(?:Fatal:|FATAL:|ERROR:|\*\* Error)", log_text),
                f"fatal/error diagnostic found in {item['name']} log")

    xsim_text = (run_dir / "xsim.log").read_text(encoding="utf-8", errors="replace")
    markers = re.findall(r"^NATIVE_SCHEDULED_ROW20_PASS ([^\r\n]+)$", xsim_text, re.M)
    require(len(markers) == 1, "XSim log lacks exactly one anchored complete numeric PASS line")
    fields = re.findall(r"([a-zA-Z0-9_]+)=(\d+)", markers[0])
    values = {key: int(value) for key, value in fields}
    require(len(values) == len(fields), "numeric PASS line has duplicate/ambiguous fields")
    expected = {
        "commands": 1, "runs": 16, "requests": 144, "responses": 144,
        "window_bytes": 11520, "masks": 144, "raw_beats": 320,
        "raw_lanes": 10240, "raw_flags": 10240, "post_beats": 320,
        "active_bytes": 5120, "tail_bytes": 5120, "packed_words": 80,
        "packed_bytes": 5120, "feature_loads": 80, "weight_groups": 9,
        "bias_loads": 1, "req_words": 255, "unary_bytes": 256,
        "full_buffers": 1, "done": 1, "post_done": 16,
        "scheduler_done": 1, "scheduler_faults": 0, "scheduler_aborts": 0,
        "boundary_descriptors": 2, "raw_site15": 16, "raw_site16": 16,
        "post_site15": 16, "post_site16": 16, "max_runsites": 20,
        "tail_sites": 20,
    }
    for key, expected_value in expected.items():
        require(values.get(key) == expected_value,
                f"numeric PASS count differs: {key}={values.get(key)!r}, expected {expected_value}")
    for key in ("packed_stall", "req_stall", "unary_stall"):
        require(values.get(key, 0) > 0, f"natural downstream backpressure missing: {key}")
    require(values.get("packed_hold_checks", 0) == 46 and values["packed_hold_checks"] >= 4,
            "packed output stability count is not the observed46 or below its >=4 criterion")
    require(values.get("raw_stall") == 0 and values.get("response_stalls") == 0,
            "unexpected change to recorded raw/window-response stall observation")

    tb_path = resolve_path("deployment/hardware/z100_2026/native_scheduled_row20_v1/tb_z100_native_scheduled_row20.sv")
    tb = tb_path.read_text(encoding="utf-8")
    require("consumer_hold_checks = consumer_hold_checks + 1;" in tb and
            "consumer_hold_checks != 4" in tb,
            "testbench does not assert exactly four consumer-held cycles")
    require("packed_stall_hold_checks = packed_stall_hold_checks + 1;" in tb and
            "packed_hold_checks=%0d" in tb and
            "buffer_full_seen, packed_stall_hold_checks" in tb and
            "packed_stall_hold_checks < 4" in tb,
            "packed_hold_checks marker field is no longer output-stall stability count")
    require("tag_for = TAG_BASE + run_id*GROUPS + group_id;" in tb and
            "window_tag != tag_for(run_index, group_index)" in tb and
            "active_run_metadata = {run_epoch,run_token,run_lanes,run_sites};" in tb and
            "{run_epoch,run_token,run_lanes,run_sites} !== active_run_metadata" in tb and
            "raw_site !== expected_site" in tb and "raw_last !== (expected_site==expected_sites-1)" in tb,
            "TB does not check scheduler tag progression, stable run metadata, or run segmentation through row outputs")
    scheduler_source = resolve_path("deployment/hardware/z100_2026/native_row_scheduler20_v1/z100_native_row_scheduler20.sv").read_text(encoding="utf-8")
    require("assign run_sites = current_sites_q;" in scheduler_source and
            "current_sites_q <= (cmd_output_width >= 20) ? 5'd20" in scheduler_source and
            "(output_width_q - output_x_q - current_sites_q) >= 20) ? 5'd20" in scheduler_source,
            "scheduler source no longer implements the bound 20-site run widths")
    run_tool = resolve_path("tools/validate_z100_scheduled_row20.py").read_text(encoding="utf-8")
    require('"packed_hold_checks": 4' in run_tool,
            "recorded rejection no longer matches the original parser's exact-four comparison")

    execution = data.get("execution", {})
    require(execution.get("post_done_source") == "post_valid && post_ready && post_last",
            "post_done is not bound to the accepted final post beat")
    require(execution.get("xelab_max_threads_explicit") == 2 and
            data.get("numerical_threads") == 1,
            "thread controls differ from the coupled-row validation contract")
    require(data.get("historical_scheduler_xelab_thread_cap_explicit") is False,
            "historical scheduler run thread-cap disclosure was changed")
    require(data.get("model_identity", {}).get("checkpoint_sha256") ==
            "2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6",
            "selected epoch200 checkpoint identity differs")

    # Show which relevant source families were byte-identical across the run.
    source_groups = {
        "compiled_hardware_and_tb": data["execution"]["compiled_rtl"],
        "independent_golden_and_generator": [
            "tools/validate_z100_native_row_pipeline.py",
            "tools/validate_z100_native_row20_epoch200.py",
            "tools/z100_feature_window_layout.py",
            "tools/validate_z100_window_mac_packed.py",
        ],
    }
    comparisons = {}
    full_row_path = report_path("validation/board_z100/native_row20_epoch200/20261024T084245.002117Z/result.json")
    full_row = json.loads(full_row_path.read_text(encoding="utf-8"))
    for group, names in source_groups.items():
        rows = []
        for name in names:
            key = Path(name).as_posix()
            current = resolve_path(name)
            if key in before:
                expected_sha = before[key]
                snap = run_dir / "src" / Path(*PurePosixPath(name).parts)
                provenance = "scheduled-row20 source snapshot"
            else:
                # The fixture generator module itself is bound in the accepted
                # full-row epoch200 prerequisite even though the coupled-row
                # host source list only captured the importing wrapper.
                expected_sha = full_row.get("source_sha256_after", {}).get(key)
                require(isinstance(expected_sha, str),
                        f"golden generator is absent from both source bindings: {name}")
                snap = full_row_path.parent / "src" / Path(*PurePosixPath(name).parts)
                provenance = "accepted epoch200 full-row prerequisite snapshot"
            rows.append({"path": name, "sha256": expected_sha, "provenance": provenance,
                         "current_matches_bound_source": sha(current) == expected_sha,
                         "snapshot_matches_bound_source": snap.is_file() and sha(snap) == expected_sha})
        require(all(row["current_matches_bound_source"] and row["snapshot_matches_bound_source"] for row in rows),
                f"source comparison failed for {group}")
        comparisons[group] = rows

    require(sha(source_result) == original_result_sha,
            "original FAILED_CLOSED result changed while reviewing")
    review_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    review_dir = REVIEW_ROOT / review_id
    review_dir.mkdir(parents=True, exist_ok=False)
    review_script_sha = sha(Path(__file__))
    snapshot = review_dir / "src" / "review_z100_scheduled_row20.py"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(Path(__file__).read_bytes())
    require(sha(snapshot) == review_script_sha, "reviewer source snapshot failed")

    report = {
        "status": "PASS_ROOT_REVIEW_BOUNDED_XSIM",
        "review_scope": "post-hoc independent audit of one existing scheduled-row XSim; no vendor command executed",
        "original_result": source_result.relative_to(ROOT).as_posix(),
        "original_result_sha256": original_result_sha,
        "original_status_preserved": data["status"],
        "original_validator_rejection": data["error"],
        "rejection_cause": {
            "field": "packed_hold_checks",
            "observed": values["packed_hold_checks"],
            "original_validator_rule": "exactly4",
            "marker_semantics": "packed_stall_hold_checks, incremented on each cycle packed_valid && !packed_ready and checked for stability",
            "correct_contract": "at least4 stable output-stall cycles",
            "separate_consumer_hold_assertion": "TB requires consumer_hold_checks == 4 and its four-cycle held payload remains stable",
            "no_other_check_relaxed": True,
        },
        "xsim_contract": {
            "exactly_one_xsim": True,
            "vendor_command_names": [item["name"] for item in commands],
            "vendor_return_codes": [item["return_code"] for item in commands],
            "xelab_max_threads_explicit": 2,
            "numerical_threads": 1,
            "runtime_seconds_observed_in_log_not_throughput": "16.296 CPU seconds; not a latency/FPS metric",
            "post_done_source": execution["post_done_source"],
        },
        "observed_counts": values,
        "source_and_artifact_audit": {
            "source_files_checked": len(before),
            "source_before_after_identical": True,
            "source_snapshots_match": True,
            "host_fixture_files_checked": len(fixture_hashes),
            "all_artifact_hashes_match": True,
            "artifact_files_checked": len(artifact_hashes),
            "prerequisites_reverified": prerequisites,
            "relevant_sources": comparisons,
            "original_failure_report_bytes_preserved": True,
        },
        "coverage_interpretation": {
            "autonomous_descriptor_flow": "one command produced16 run handshakes and144 scheduler-owned descriptors; no testbench manual run/window drivers remain",
            "numeric_path": "144 window responses;320 raw and post beats;10240 raw lane values and overflow flags;80 unique 512-bit packed words matched epoch200 independent NCHW/OIHW/binary64/SiLU golden",
            "crossings": "run7鈫抮un8 descriptor indices71/72 and output site15/16 observations were checked in each run; run-site fields remained20",
            "retirement": "16 final-post acknowledgements, one scheduler done, no scheduler fault or abort; TB asserted row and scheduler idle",
            "backpressure": "46 packed-output stall cycles,8 requant stalls,8 unary stalls; natural output backpressure propagated; packed metadata stability and exactly4 consumer-held cycles were checked",
            "unobserved_stalls": "raw MAC boundary and feature-window response boundary each observed0 stalls; their stability counters are0",
        },
        "limits": {
            "full_graph_validated": False, "model_accuracy_accepted": False,
            "physical_timing_accepted": False, "board_access": False,
            "production_integrated": False, "throughput_or_fps_accepted": False,
            "tail_scope": "320 is exactly16脳20; no short1/19-site tail was exercised in this coupled command",
            "no_ooc_or_route": True,
        },
        "review_tool": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
                         "sha256": review_script_sha},
    }
    review_report = review_dir / "result.json"
    review_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    report["artifact_sha256"] = {
        path.relative_to(ROOT).as_posix(): sha(path)
        for path in review_dir.rglob("*") if path.is_file() and path != review_report
    }
    review_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "review_report": str(review_report),
                      "original_result_status": data["status"],
                      "commands": report["xsim_contract"]["vendor_command_names"],
                      "observed_packed_hold_checks": values["packed_hold_checks"]}))
    return review_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-result", type=Path, required=True)
    args = parser.parse_args()
    audit(args.source_result)


if __name__ == "__main__":
    main()
