"""Host-preflight and single-XSim validation for a private dynamic-group row pipeline.

The original 27-run first-convolution fixture remains the arithmetic baseline.
Additional 1, 3, 9, 36, 576, and 1024-group stress cases isolate the MAC group's
runtime last-marker/control contract with zero-feature input. No OOC, route,
board access, production integration, or FPS acceptance is performed here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
OWN_DIR = ROOT / "deployment/hardware/z100_2026/native_row_runtime_v1"
RUNTIME_RTL = OWN_DIR / "z100_native_row_runtime.sv"
RUNTIME_TB = OWN_DIR / "tb_z100_native_row_runtime.sv"
PARTITION_ADAPTER = ROOT / "tools/validate_z100_native_row_partition.py"
ROWSTORE_VALIDATOR = ROOT / "tools/validate_z100_native_row_store.py"
ROWSTORE_RUN = "20261024Tcounter_latch_9f32d6c1"
ROWSTORE_RESULT = ROOT / "validation/board_z100/nrs" / ROWSTORE_RUN / "result.json"
ROWSTORE_RESULT_SHA256 = "3477e2cef4cd781d7c67068db1b53cafbcb86246eca1eb7d94c785ac1fe6ef5d"
BUILD_ROOT = ROOT / "deployment/build/nrr"
EVIDENCE_ROOT = ROOT / "validation/board_z100/nrr"
PASS_XSIM_STATUS = "PASS_PRIVATE_NATIVE_ROW_RUNTIME_GROUPS_XSIM_ONLY"
MAX_GROUPS = 1024
EXPECTED_GROUP_COUNTS = (1, 3, 9, 36, 576, 1024)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def inventory(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in sorted(paths.items())}


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import validator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def context() -> tuple[Any, Any, Any]:
    partition = load_module("nrr_partition_adapter", PARTITION_ADAPTER)
    frozen = partition.load_frozen()
    store_validator = load_module("nrr_rowstore_validator", ROWSTORE_VALIDATOR)
    return partition, frozen, store_validator


def add_path(mapping: dict[str, Path], path: Path) -> None:
    key = rel(path)
    if key in mapping and mapping[key].resolve() != path.resolve():
        raise RuntimeError(f"path key aliases a different file: {key}")
    mapping[key] = path


def source_maps(partition: Any, frozen: Any) -> tuple[dict[str, Path], dict[str, Path]]:
    sources = dict(frozen.source_paths())
    if len(sources) != 48:
        raise RuntimeError(f"frozen model source closure changed: expected 48, found {len(sources)}")
    for path in (RUNTIME_RTL, RUNTIME_TB, SCRIPT):
        add_path(sources, path)

    dependencies = dict(frozen.dependency_paths())
    if len(dependencies) != 20:
        raise RuntimeError(f"frozen model dependency closure changed: expected 20, found {len(dependencies)}")
    for path in (PARTITION_ADAPTER, partition.PRIOR_ROW_REVIEW,
                 ROWSTORE_VALIDATOR, ROWSTORE_RESULT):
        add_path(dependencies, path)
    return dict(sorted(sources.items())), dict(sorted(dependencies.items()))


def verify_file_map(values: dict[str, str], label: str) -> int:
    if not isinstance(values, dict) or not values:
        raise RuntimeError(f"{label} has no artifact hash map")
    for name, expected in values.items():
        path = ROOT / Path(name.replace("\\", "/"))
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"{label} artifact hash mismatch: {name}")
    return len(values)


def accepted_rowstore_binding() -> dict[str, Any]:
    if not ROWSTORE_RESULT.is_file() or sha256(ROWSTORE_RESULT) != ROWSTORE_RESULT_SHA256:
        raise RuntimeError("passed native row-store result is missing or changed")
    result = json.loads(ROWSTORE_RESULT.read_text(encoding="utf-8"))
    required_integrity = (
        "sources_unchanged", "dependencies_unchanged", "prior_reports_unchanged",
        "addressed_prerequisite_reports_unchanged", "previous_failed_rowstore_run_unchanged",
        "authorized_tb_expected_index_fix_unchanged", "authorized_tb_counter_latch_fix_unchanged",
        "snapshot_unchanged",
    )
    store_coverage = result.get("xsim_coverage", {}).get("row_store", {})
    full_coverage = result.get("xsim_coverage", {}).get("frozen_full_row", {})
    store_counts = store_coverage.get("counts", {})
    if (result.get("status") != "PASS_NATIVE_ROW_STORE_ROW_AND_RELOAD_XSIM_ONLY" or
        result.get("xsim_attempt_policy") != {"xsim_attempts": 1, "ooc_attempts": 0, "route_attempts": 0} or
        result.get("scope", {}).get("board_access") is not False or
        result.get("scope", {}).get("route") is not False or
        result.get("scope", {}).get("full_pipeline_30fps_accepted") is not False or
        full_coverage.get("status") != "PASS" or store_coverage.get("status") != "PASS" or
        store_counts.get("partial_cancel_runs") != 2 or
        store_counts.get("partial_cancel_requests") != 18 or
        store_counts.get("partial_cancel_responses") != 18 or
        store_counts.get("partial_cancel_raw") != 24 or
        store_counts.get("partial_cancel_post") != 17 or
        store_counts.get("partial_cancel_packed") != 1 or
        store_counts.get("reset_partial_active_confirmed") != 1 or
        store_counts.get("reset_reload_runs") != 27 or
        not all(result.get("xsim_integrity", {}).get(key) is True for key in required_integrity)):
        raise RuntimeError("passed row-store scope, recovery coverage, or integrity binding differs")
    artifact_count = verify_file_map(result.get("new_artifact_sha256", {}), "passed row-store")
    if artifact_count != 122:
        raise RuntimeError(f"passed row-store artifact count changed: {artifact_count}")
    return {
        "path": rel(ROWSTORE_RESULT), "sha256": ROWSTORE_RESULT_SHA256,
        "status": result["status"], "run_id": result.get("run_id"),
        "verified_artifact_count": artifact_count,
        "partial_cancel_counts": {key: store_counts[key] for key in (
            "partial_cancel_runs", "partial_cancel_requests", "partial_cancel_responses",
            "partial_cancel_raw", "partial_cancel_post", "partial_cancel_packed")},
        "active_reset_and_full_reload_passed": True,
        "source_and_report_integrity_passed": True,
        "board_route_ooc_fps_claims": False,
    }


def verify_row_runtime_clone(frozen: Any) -> dict[str, Any]:
    original = frozen.WRAPPER
    original_bytes = original.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    if sha256(original) != "4de11c79472a48dea9553b136a22cca9765d4e31a006dedf141d355a1ec4d436":
        raise RuntimeError("frozen original row-pipeline RTL changed")
    candidate = RUNTIME_RTL.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')

    transforms = (
        (b"module z100_native_row_pipeline #(", b"module z100_native_row_runtime #("),
        (b"    parameter integer GROUPS_PER_RUN = 9,\r\n", b""),
        (b"    reg [10:0] accepted_responses;\r\n",
         b"    reg [10:0] accepted_responses;\r\n"
         b"    reg [10:0] pending_groups;\r\n"
         b"    reg [10:0] committed_groups;\r\n"),
        (b"    assign stream_last = (accepted_responses == GROUPS_PER_RUN-1);",
         b"    assign stream_last = mac_weights_valid && (committed_groups != 0) &&\r\n"
         b"                         (accepted_responses == committed_groups-11'd1);"),
    )
    expected = original_bytes
    for before, after in transforms:
        if expected.count(before) != 1:
            raise RuntimeError("frozen RTL clone transform anchor is absent or duplicated")
        expected = expected.replace(before, after, 1)
    counter_block = (
        b"    always @(posedge clk) begin\r\n"
        b"        if (!rst_n || cancel)\r\n"
        b"            accepted_responses <= 0;\r\n"
        b"        else if (run_valid && run_ready)\r\n"
        b"            accepted_responses <= 0;\r\n"
        b"        else if (stream_valid && stream_ready)\r\n"
        b"            accepted_responses <= accepted_responses + 1'b1;\r\n"
        b"    end\r\n"
    )
    dynamic_control = (
        b"\r\n    always @(posedge clk) begin\r\n"
        b"        if (!rst_n || cancel) begin\r\n"
        b"            pending_groups <= 0;\r\n"
        b"            committed_groups <= 0;\r\n"
        b"        end else if (mac_cfg_begin && mac_cfg_begin_ready) begin\r\n"
        b"            pending_groups <= mac_cfg_groups;\r\n"
        b"            committed_groups <= 0;\r\n"
        b"        end else if (mac_error_valid) begin\r\n"
        b"            pending_groups <= 0;\r\n"
        b"            committed_groups <= 0;\r\n"
        b"        end else if (mac_cfg_commit && mac_cfg_commit_ready) begin\r\n"
        b"            committed_groups <= pending_groups;\r\n"
        b"        end\r\n"
        b"    end\r\n"
    )
    if expected.count(counter_block) != 1:
        raise RuntimeError("accepted-response counter block differs from frozen row pipeline")
    expected = expected.replace(counter_block, counter_block + dynamic_control, 1)
    if candidate != expected:
        raise RuntimeError("runtime RTL clone contains changes outside the exact group-latch/last-marker delta")
    if b"GROUPS_PER_RUN" in candidate:
        raise RuntimeError("runtime RTL retained a fixed groups-per-run barrier")
    return {
        "original_path": rel(original), "original_sha256": sha256(original),
        "runtime_path": rel(RUNTIME_RTL), "runtime_sha256": sha256(RUNTIME_RTL),
        "runtime_module": "z100_native_row_runtime",
        "fixed_group_parameter_removed": True,
        "exact_control_changes": ["latch pending groups on MAC begin",
                                   "commit pending groups on MAC commit",
                                   "clear group state on reset/cancel/new begin/MAC error",
                                   "stream_last uses committed group count and weights_valid"],
        "pipeline_arithmetic_and_all_other_source_bytes_unchanged_after_explicit_CRLF_normalization": True,
    }


def verify_runtime_testbench(frozen: Any) -> dict[str, Any]:
    original = frozen.TB.read_text(encoding="utf-8")
    testbench = RUNTIME_TB.read_text(encoding="utf-8")
    required_baseline = (
        "localparam integer SITES = 12;", "localparam integer GROUPS = 9;",
        "localparam integer ROW_WIDTH = 320;", "localparam integer RUNS = 27;",
        "localparam integer WINDOW_REQUESTS = RUNS * GROUPS;",
        "consumer_hold_checks != 4", "packed_stall_hold_checks < 4",
        "packed_address_seen !== {80{1'b1}}", "packed_beats != 80",
        "packed_byte_checks != 80*64", "raw_lane_checks != ROW_WIDTH*32",
        "raw_flag_checks != ROW_WIDTH*32", "expected_raw_words[idx][32+result_lane*32 +: 32]",
        "expected_post_words[idx][result_lane*8 +: 8]",
        "expected_packed_words[packed_address]",
    )
    marker_start = original.find('$display("NATIVE_ROW_PIPELINE_PASS')
    candidate_marker_start = testbench.find('$display("NATIVE_ROW_PIPELINE_PASS')
    if marker_start < 0 or candidate_marker_start < 0:
        raise RuntimeError("frozen full-row pass marker is absent")
    marker_end = original.find(";", marker_start)+1
    candidate_marker_end = testbench.find(";", candidate_marker_start)+1
    if (marker_end <= marker_start or candidate_marker_end <= candidate_marker_start or
        original[marker_start:marker_end] != testbench[candidate_marker_start:candidate_marker_end]):
        raise RuntimeError("original 27-run full-row marker arguments changed")
    if any(text not in testbench or testbench.find(text) > candidate_marker_start
           for text in required_baseline):
        raise RuntimeError("baseline arithmetic/coverage assertion is missing or moved after its pass marker")

    runtime_requirements = (
        "module tb_z100_native_row_runtime;",
        "z100_native_row_runtime #(.SITES(SITES), .SITE_FIFO_DEPTH(4)) dut (.*);",
        "reg baseline_scoreboard_enable = 1'b1;",
        "end else if (baseline_scoreboard_enable) begin",
        "runtime_response_count==runtime_group_count-1",
        "stream_last !== (runtime_response_count==runtime_group_count-1)",
        "dut.committed_groups!==groups_to_send",
        "mac_cfg_groups=mutate_external_groups;",
        "window_stride_two=1; window_y_valid=0; window_valid=1;",
        "bias_word[0][runtime_channel_index*32+:32]",
        "runtime_channel_index=16;runtime_channel_index<32",
        "expect_invalid_runtime_config(0);", "expect_invalid_runtime_config(1025);",
        "reset_during_pending_runtime_config();", "cancel_runtime_configuration();",
        "run_runtime_replay(1024,10,0);", "run_runtime_replay(1024,11,1);",
        "group_counts=1,3,9,36,576,1024", "NATIVE_ROW_RUNTIME_PASS",
    )
    if any(item not in testbench for item in runtime_requirements):
        raise RuntimeError("runtime group control/reset/cancel/replay checks are incomplete")
    if testbench.find("baseline_scoreboard_enable=0;") < candidate_marker_end:
        raise RuntimeError("runtime phase is not isolated from the completed baseline scoreboard")
    return {
        "original_tb_path": rel(frozen.TB), "original_tb_sha256": sha256(frozen.TB),
        "runtime_tb_path": rel(RUNTIME_TB), "runtime_tb_sha256": sha256(RUNTIME_TB),
        "baseline_numeric_and_coverage_assertions_preserved": len(required_baseline),
        "baseline_marker_byte_identical": True,
        "dynamic_group_cases": list(EXPECTED_GROUP_COUNTS),
        "resident_replays_per_group_count": 2,
        "external_cfg_mutated_after_commit_for_each_replay": True,
        "invalid_zero_and_over_limit_groups_checked": True,
        "pending_config_active_reset_and_committed_config_cancel_checked": True,
        "raw_oracle_is_real_bias_with_zero_feature_products": True,
        "stress_scope_is_control_metadata_and_retirement_only": True,
    }


def compile_keys(partition: Any, frozen: Any) -> list[str]:
    return [rel(frozen.BANK_RTL), rel(frozen.WINDOW_RTL), rel(frozen.MAC_RTL),
            rel(partition.PARTITION_RTL), rel(frozen.UNARY_RTL), rel(frozen.PACKER_RTL),
            rel(RUNTIME_RTL), rel(RUNTIME_TB)]


def make_snapshot(sources: dict[str, Path], dependencies: dict[str, Path], evidence: Path) -> dict[str, Any]:
    root = evidence / "src"
    root.mkdir(parents=True, exist_ok=False)
    items: dict[str, dict[str, Any]] = {}
    for role, mapping in (("source", sources), ("dependency", dependencies)):
        for original, path in mapping.items():
            entry = items.setdefault(original, {"path": str(path.resolve()), "roles": []})
            if entry["path"] != str(path.resolve()):
                raise RuntimeError(f"snapshot path collision: {original}")
            entry["roles"].append(role)
    destinations: list[str] = []
    for index, (original, entry) in enumerate(sorted(items.items())):
        source = Path(entry["path"])
        digest = sha256(source)
        suffix = source.suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix or ""):
            suffix = ".dat"
        name = f"{index:03d}_{digest[:12]}{suffix}"
        destination = root / name
        shutil.copyfile(source, destination)
        if destination.stat().st_size != source.stat().st_size or sha256(destination) != digest:
            raise RuntimeError(f"snapshot byte verification failed: {original}")
        entry.update({"snapshot_name": name, "bytes": source.stat().st_size, "sha256": digest})
        destinations.append(name)
    if len(destinations) != len(set(destinations)) or len(destinations) != len(items):
        raise RuntimeError("source snapshot is not a bijection")
    manifest = {
        "format": "z100_native_row_runtime_source_snapshot_v1",
        "all_bytes_verified": True, "bijection_verified": True,
        "source_count": len(sources), "dependency_count": len(dependencies),
        "snapshot_file_count": len(destinations),
        "maximum_destination_path_characters": max(len(str((root / name).resolve())) for name in destinations),
        "original_path_to_snapshot": items,
    }
    manifest_path = evidence / "snapshot.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return {"path": rel(manifest_path), "sha256": sha256(manifest_path),
            "snapshot_file_count": len(destinations),
            "maximum_destination_path_characters": manifest["maximum_destination_path_characters"],
            "all_bytes_verified": True, "bijection_verified": True}


def verify_snapshot(sources: dict[str, Path], dependencies: dict[str, Path], evidence: Path) -> dict[str, Any]:
    manifest_path = evidence / "snapshot.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapping = manifest.get("original_path_to_snapshot", {})
    expected = {**sources, **dependencies}
    if set(mapping) != set(expected):
        raise RuntimeError("snapshot source/dependency path closure changed")
    names: list[str] = []
    for original, source in expected.items():
        entry = mapping[original]
        name = entry.get("snapshot_name")
        if not isinstance(name, str) or Path(name).name != name:
            raise RuntimeError(f"unsafe snapshot filename for {original}")
        copied = evidence / "src" / name
        names.append(name)
        if (not copied.is_file() or entry.get("bytes") != source.stat().st_size or
            entry.get("sha256") != sha256(source) or copied.stat().st_size != source.stat().st_size or
            sha256(copied) != sha256(source)):
            raise RuntimeError(f"snapshot bytes differ from frozen file: {original}")
    actual = sorted(path.name for path in (evidence / "src").iterdir() if path.is_file())
    if len(names) != len(set(names)) or sorted(names) != actual or len(actual) != len(expected):
        raise RuntimeError("snapshot directory is not a one-to-one full closure")
    if manifest.get("all_bytes_verified") is not True or manifest.get("bijection_verified") is not True:
        raise RuntimeError("snapshot verification flags are false")
    return {"path": rel(manifest_path), "sha256": sha256(manifest_path),
            "snapshot_file_count": len(actual),
            "maximum_destination_path_characters": manifest.get("maximum_destination_path_characters")}


def module_closure(paths: list[Path], store_validator: Any) -> dict[str, Any]:
    return store_validator.check_module_closure(paths)


def check_fixture(build: Path, fixture: dict[str, Any]) -> dict[str, Any]:
    expected_names = {
        "feature_words.hex", "native_weight_groups.hex", "native_bias.hex", "req_cfg.hex",
        "unary_cfg.hex", "expected_windows.hex", "expected_window_masks.hex",
        "expected_raw_words.hex", "expected_post_words.hex", "expected_packed_words.hex",
    }
    rows = fixture.get("fixtures", {})
    if set(rows) != expected_names:
        raise RuntimeError("independent original-arithmetic fixture file set changed")
    for name, item in rows.items():
        path = build / name
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise RuntimeError(f"fixture hash/size mismatch: {name}")
    if (fixture.get("geometry", {}).get("runs") != 27 or
        fixture.get("geometry", {}).get("runs_with_12_sites") != 26 or
        fixture.get("geometry", {}).get("tail_sites") != 8 or
        "signed64 NCHW" not in fixture.get("independent_reference", {}).get("raw_reference", "") or
        fixture.get("independent_reference", {}).get("threshold_tree_used_as_golden") is not False):
        raise RuntimeError("fixture no longer binds the independent signed64 first-row oracle")
    return fixture


def preflight(run_id: str) -> dict[str, Any]:
    partition, frozen, store_validator = context()
    upstream = frozen.verify_upstream()
    partition_report = partition.partition_bindings(frozen)
    row_review = partition.previous_row_review_binding()
    rowstore = accepted_rowstore_binding()
    runtime_clone = verify_row_runtime_clone(frozen)
    runtime_tb = verify_runtime_testbench(frozen)
    sources, dependencies = source_maps(partition, frozen)
    source_before = inventory(sources)
    dependency_before = inventory(dependencies)
    source_keys = compile_keys(partition, frozen)
    if len(source_keys) != 8 or any(key not in sources for key in source_keys):
        raise RuntimeError("runtime XSim compile source closure is incomplete")
    closure = module_closure([sources[key] for key in source_keys], store_validator)

    build = BUILD_ROOT / run_id
    evidence = EVIDENCE_ROOT / run_id
    if build.exists() or evidence.exists():
        raise FileExistsError("refusing to overwrite prior runtime-group evidence")
    build.mkdir(parents=True)
    evidence.mkdir(parents=True)
    fixture = check_fixture(build, frozen.prepare_fixture(build))
    snapshot = make_snapshot(sources, dependencies, evidence)
    verified_snapshot = verify_snapshot(sources, dependencies, evidence)
    if snapshot["sha256"] != verified_snapshot["sha256"]:
        raise RuntimeError("fresh source snapshot changed during preflight")
    if (inventory(sources) != source_before or inventory(dependencies) != dependency_before or
        accepted_rowstore_binding() != rowstore):
        raise RuntimeError("bound sources, dependencies, or accepted row-store report changed during host phase")

    upstream_summary = {name: {"path": value.get("path"), "sha256": value.get("sha256"),
                               "status": value.get("status")}
                        for name, value in upstream.get("reports", {}).items()}
    report = {
        "status": "PASS_HOST_PREFLIGHT_ONLY", "run_id": run_id,
        "scope": {"board_access": False, "ooc": False, "route": False,
                  "production_integrated": False, "full_pipeline_30fps_accepted": False},
        "host": {"python_version": sys.version.split()[0], "numerical_threads": 1},
        "source_count": len(sources), "dependency_count": len(dependencies),
        "source_sha256_before_xsim": source_before,
        "dependency_sha256_before_xsim": dependency_before,
        "runtime_rtl_clone_binding": runtime_clone,
        "runtime_testbench_static_binding": runtime_tb,
        "previous_rowstore_pass_binding": rowstore,
        "partition_v2_bindings": partition_report,
        "previous_original_row_review_binding": row_review,
        "upstream_report_bindings": upstream_summary,
        "xsim_source_paths": source_keys,
        "xsim_module_closure": closure,
        "snapshot": verified_snapshot,
        "fixture": fixture,
        "xsim_attempt_policy": {"xsim_attempts": 0, "ooc_attempts": 0, "route_attempts": 0},
        "expected_runtime_control_coverage": {
            "groups": list(EXPECTED_GROUP_COUNTS), "resident_replays_per_group_count": 2,
            "expected_runs": 12, "expected_group_responses": 3298,
            "expected_last_true": 12, "expected_last_false": 3286,
            "expected_raw_beats": 12, "expected_post_beats": 12,
            "expected_packer_words": 48, "invalid_group_configs": [0, 1025],
            "reset_during_pending_config": True, "cancel_invalidates_committed_config": True,
            "dynamic_stress_arithmetic_acceptance": False,
        },
    }
    host_path = evidence / "host_preflight.json"
    host_path.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    result = {
        "run_id": run_id, "status": "PASS_HOST_PREFLIGHT_ONLY",
        "build_directory": str(build.resolve()), "evidence_directory": str(evidence.resolve()),
        "host_preflight_path": rel(host_path), "host_preflight_sha256": sha256(host_path),
        "xsim_attempt_policy": report["xsim_attempt_policy"], "scope": report["scope"],
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return result


def run_logged(command: list[str], cwd: Path, log_path: Path, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(subprocess.list2cmdline(command), cwd=str(cwd), shell=True, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", timeout=1800)
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {"argv": command, "cwd": str(cwd.resolve()), "return_code": completed.returncode,
            "log": rel(log_path), "log_sha256": sha256(log_path), "output": completed.stdout,
            "warning_count": len(re.findall(r"\bWARNING\b", completed.stdout, re.I))}


def parse_runtime_marker(output: str) -> dict[str, Any]:
    pattern = re.compile(
        r"(?m)^NATIVE_ROW_RUNTIME_PASS group_counts=1,3,9,36,576,1024 replays=(\d+) "
        r"requests=(\d+) responses=(\d+) last_true=(\d+) last_false=(\d+) "
        r"raw_beats=(\d+) post_beats=(\d+) packed_words=(\d+) done=(\d+) "
        r"weight_words=(\d+) invalid_cfgs=(\d+) cancel_events=(\d+) reset_events=(\d+) "
        r"independent_bias_raw=1 active_lanes=16 zero_tail_lanes=16$")
    matches = pattern.findall(output)
    if len(matches) != 1:
        raise RuntimeError("runtime group pass marker missing, duplicated, or malformed")
    values = tuple(map(int, matches[0]))
    expected = (12, 3298, 3298, 12, 3286, 12, 12, 48, 12, 1649, 2, 1, 1)
    if values != expected:
        raise RuntimeError(f"runtime group control/retirement coverage mismatch: {values}")
    return {
        "status": "PASS", "group_counts": list(EXPECTED_GROUP_COUNTS),
        "counts": dict(zip(("replays", "requests", "responses", "last_true", "last_false",
                             "raw_beats", "post_beats", "packed_words", "done",
                             "weight_words", "invalid_cfgs", "cancel_events", "reset_events"), values)),
        "every_response_checked_for_metadata_token_and_last_index": True,
        "raw_results_match_independent_real_bias_with_zero_products": True,
        "stress_phase_makes_no_real_model_arithmetic_claim": True,
    }


def artifact_hashes(build: Path, evidence: Path, result_path: Path) -> dict[str, str]:
    return {rel(path): sha256(path) for base in (build, evidence)
            for path in sorted(item for item in base.rglob("*") if item.is_file() and item != result_path)}


def xsim(run_id: str) -> dict[str, Any]:
    partition, frozen, store_validator = context()
    build = BUILD_ROOT / run_id
    evidence = EVIDENCE_ROOT / run_id
    result_path = evidence / "result.json"
    host_path = evidence / "host_preflight.json"
    if not (build.is_dir() and evidence.is_dir() and result_path.is_file() and host_path.is_file()):
        raise FileNotFoundError("matching runtime-group host preflight is required")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    host = json.loads(host_path.read_text(encoding="utf-8"))
    if result.get("status") != "PASS_HOST_PREFLIGHT_ONLY" or host.get("status") != "PASS_HOST_PREFLIGHT_ONLY":
        raise RuntimeError("XSim requires the matching passing host preflight")
    attempt_path = evidence / "xsim_attempt_started.json"
    if attempt_path.exists():
        raise FileExistsError("the single runtime-group XSim attempt has already started")

    sources, dependencies = source_maps(partition, frozen)
    source_before = inventory(sources)
    dependency_before = inventory(dependencies)
    rowstore_before = accepted_rowstore_binding()
    partition_before = partition.partition_bindings(frozen)
    row_review_before = partition.previous_row_review_binding()
    clone_before = verify_row_runtime_clone(frozen)
    tb_before = verify_runtime_testbench(frozen)
    source_keys = compile_keys(partition, frozen)
    closure = module_closure([sources[key] for key in source_keys], store_validator)
    snapshot = verify_snapshot(sources, dependencies, evidence)
    if (source_before != host.get("source_sha256_before_xsim") or
        dependency_before != host.get("dependency_sha256_before_xsim") or
        rowstore_before != host.get("previous_rowstore_pass_binding") or
        partition_before != host.get("partition_v2_bindings") or
        row_review_before != host.get("previous_original_row_review_binding") or
        clone_before != host.get("runtime_rtl_clone_binding") or
        tb_before != host.get("runtime_testbench_static_binding") or
        source_keys != host.get("xsim_source_paths") or
        closure != host.get("xsim_module_closure") or
        snapshot.get("sha256") != host.get("snapshot", {}).get("sha256")):
        raise RuntimeError("runtime source/dependency/upstream/snapshot identity changed after host preflight")

    mapping = json.loads((evidence / "snapshot.json").read_text(encoding="utf-8"))["original_path_to_snapshot"]
    vendor_sources = [evidence / "src" / mapping[key]["snapshot_name"] for key in source_keys]
    if not all(path.is_file() for path in vendor_sources):
        raise RuntimeError("short runtime XSim source snapshot is incomplete")
    for name in ("xvlog.bat", "xelab.bat", "xsim.bat"):
        if not (frozen.VIVADO_BIN / name).is_file():
            raise FileNotFoundError(f"Vivado 2026.1 XSim tool unavailable: {frozen.VIVADO_BIN / name}")

    attempt_path.write_text(json.dumps({
        "run_id": run_id, "attempt": 1, "started_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot_sha256": snapshot["sha256"], "compile_source_paths": source_keys,
        "policy": "one XSim only; no OOC, route, board, or retry"}, indent=2, sort_keys=True)+"\n",
        encoding="utf-8")
    result["status"] = "XSIM_RUNNING"
    result["xsim_attempt_policy"] = {"xsim_attempts": 1, "ooc_attempts": 0, "route_attempts": 0}
    result["source_sha256_before_xsim"] = source_before
    result["dependency_sha256_before_xsim"] = dependency_before
    result["xsim_source_paths"] = source_keys
    result["xsim_module_closure"] = closure
    (evidence / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")

    commands: list[dict[str, Any]] = []
    try:
        env = frozen.phase_env()
        commands.append(run_logged([str(frozen.VIVADO_BIN / "xvlog.bat"), "-sv", *map(str, vendor_sources)],
                                   build, evidence / "xvlog.log", env))
        if commands[-1]["return_code"] != 0:
            raise RuntimeError("single runtime xvlog invocation failed; attempt consumed")
        commands.append(run_logged([str(frozen.VIVADO_BIN / "xelab.bat"), "-mt", "2",
                                    "tb_z100_native_row_runtime", "-s", "nrr_sim"],
                                   build, evidence / "xelab.log", env))
        if commands[-1]["return_code"] != 0:
            raise RuntimeError("single runtime xelab invocation failed; attempt consumed")
        commands.append(run_logged([str(frozen.VIVADO_BIN / "xsim.bat"), "nrr_sim", "-runall"],
                                   build, evidence / "xsim.log", env))
        output = commands[-1]["output"]
        if commands[-1]["return_code"] != 0 or re.search(r"(?im)^\s*(?:Fatal:|ERROR:)", output):
            raise RuntimeError("runtime XSim failed; retry is not permitted")
        if output.count("NATIVE_ROW_PIPELINE_PASS") != 1 or output.count("NATIVE_ROW_RUNTIME_PASS") != 1:
            raise RuntimeError("runtime simulation pass markers are missing or duplicated")
        static_checks = partition.check_static_row_assertions(frozen)
        baseline_coverage = partition.parse_full_row_pass(output, static_checks)
        runtime_coverage = parse_runtime_marker(output)
        result.update({
            "status": PASS_XSIM_STATUS,
            "xsim_vendor_arguments": [command["argv"] for command in commands],
            "xsim_tool_return_codes": [command["return_code"] for command in commands],
            "xsim_log_sha256": commands[-1]["log_sha256"],
            "xsim_coverage": {"frozen_full_row": baseline_coverage,
                              "runtime_groups_control_only": runtime_coverage},
        })
    except Exception as error:
        result["status"] = "FAILED_CLOSED_NATIVE_ROW_RUNTIME_XSIM"
        result["failure"] = f"{type(error).__name__}: {error}"
    finally:
        result["commands"] = commands
        result["xsim_attempt_policy"] = {"xsim_attempts": 1, "ooc_attempts": 0, "route_attempts": 0}
        source_after = inventory(sources)
        dependency_after = inventory(dependencies)
        rowstore_after = accepted_rowstore_binding()
        partition_after = partition.partition_bindings(frozen)
        row_review_after = partition.previous_row_review_binding()
        clone_after = verify_row_runtime_clone(frozen)
        tb_after = verify_runtime_testbench(frozen)
        snapshot_after = verify_snapshot(sources, dependencies, evidence)
        integrity = {
            "sources_unchanged": source_after == source_before,
            "dependencies_unchanged": dependency_after == dependency_before,
            "accepted_rowstore_report_unchanged": rowstore_after == rowstore_before,
            "partition_v2_reports_unchanged": partition_after == partition_before,
            "original_row_review_unchanged": row_review_after == row_review_before,
            "runtime_rtl_clone_unchanged": clone_after == clone_before,
            "runtime_testbench_unchanged": tb_after == tb_before,
            "snapshot_unchanged": snapshot_after["sha256"] == snapshot["sha256"],
        }
        result["xsim_integrity"] = integrity
        result["source_sha256_after_xsim"] = source_after
        result["dependency_sha256_after_xsim"] = dependency_after
        if not all(integrity.values()):
            result["status"] = "FAILED_CLOSED_NATIVE_ROW_RUNTIME_XSIM_INTEGRITY"
            result["failure"] = result.get("failure", "source or prerequisite integrity changed during XSim")
        if result.get("status") == PASS_XSIM_STATUS:
            result["scope"] = {"board_access": False, "ooc": False, "route": False,
                               "production_integrated": False, "full_pipeline_30fps_accepted": False,
                               "runtime_group_stress_arithmetic_accepted": False}
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        result["artifact_sha256"] = artifact_hashes(build, evidence, result_path)
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("host", "xsim"), default="host")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.phase == "host":
        run_id = args.run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+
                                 "_"+uuid.uuid4().hex[:8])
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", run_id):
            parser.error("unsafe run id")
        result = preflight(run_id)
    else:
        if not args.run_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", args.run_id):
            parser.error("--phase xsim requires a safe --run-id")
        result = xsim(args.run_id)
    print(json.dumps({"status": result.get("status"), "run_id": result.get("run_id"),
                      "evidence_directory": result.get("evidence_directory"),
                      "failure": result.get("failure")}, sort_keys=True), flush=True)
    return 0 if result.get("status") in {"PASS_HOST_PREFLIGHT_ONLY", PASS_XSIM_STATUS} else 1


if __name__ == "__main__":
    raise SystemExit(main())
