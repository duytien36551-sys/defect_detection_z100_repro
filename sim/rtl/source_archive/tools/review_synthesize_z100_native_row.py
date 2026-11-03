"""Source-bind the immutable native-row XSim run and run one OOC screen.

This review intentionally bypasses the existing XSim marker parser's known
field mismatch without changing that validator or either failed run. The
numeric testbench's own assertions remain the source of pass/fail for the
bounded simulation; this tool separately checks the frozen source, fixture,
tool, log, and marker bindings. The optional OOC phase imports the frozen
validator's run_ooc implementation and writes only to new directories.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools/validate_z100_native_row_pipeline.py"
TB = ROOT / "deployment/hardware/z100_2026/native_row_pipeline_v1/tb_z100_native_row_pipeline.sv"
XSIM_RUN_ID = "20261023T184444.835012Z_eed495d5"
FAILED_RUN_IDS = (
    "20261023T184135.335917Z_71fa68d6",
    XSIM_RUN_ID,
)
XSIM_EVIDENCE = ROOT / "validation/board_z100/native_row_pipeline_v1" / XSIM_RUN_ID
XSIM_BUILD = ROOT / "deployment/build/z100_native_row_pipeline_v1" / XSIM_RUN_ID
BUILD_ROOT = ROOT / "deployment/build/nrow_ooc"
EVIDENCE_ROOT = ROOT / "validation/board_z100/nrow_ooc"
PYTHON = ROOT / '.venv/Scripts/python.exe'
VIVADO = Path("C:/appload/2026.1/Vivado/bin/vivado.bat")
EXPECTED_MODEL = {
    "package_sha256": "96211aa416da6b23955a8b62cca594275daaa4db3e3954632960707c0ec0d44f",
    "header_sha256": "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5",
    "graph_sha256": "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8",
    "input_nchw_sha256": "0d458d68cf3e419e238245193cd5415c75b2931eb011a695c7b5a5765a1718b6",
}
EXPECTED_MARKER = {
    "runs": 27, "requests": 243, "responses": 243, "window_bytes": 11664,
    "masks": 243, "raw_beats": 320, "raw_lanes": 10240, "raw_flags": 10240,
    "post_beats": 320, "active_bytes": 5120, "tail_bytes": 5120,
    "packed_words": 80, "packed_bytes": 5120, "feature_loads": 80,
    "weight_groups": 9, "bias_loads": 1, "req_words": 255, "unary_bytes": 256,
    "packed_stall": 72, "req_stall": 8, "unary_stall": 8,
    "raw_stall": 0, "raw_stall_stability": 0, "response_stalls": 0,
    "response_stall_stability": 0, "bubbles": 729, "site_fifo_full": 0,
    "full_buffers": 1, "packed_hold_checks": 72, "done": 1,
    "raw_backpressure_note": 1, "max_runsites": 12, "tail_sites": 8,
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def file_inventory(root: Path) -> dict[str, dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        out[path.relative_to(root).as_posix()] = {
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
    return out


def load_validator():
    spec = importlib.util.spec_from_file_location("frozen_z100_native_row_validator", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not import frozen native-row validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_repo_path(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def verify_snapshot(snapshot_dir: Path, bound: dict[str, dict[str, Any]], name: str) -> None:
    for relpath, expected in bound.items():
        path = snapshot_dir / Path(relpath)
        if not path.is_file():
            raise FileNotFoundError(f"{name} snapshot is missing {relpath}")
        if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
            raise RuntimeError(f"{name} snapshot hash mismatch: {relpath}")


def check_artifacts(run: dict[str, Any]) -> dict[str, str]:
    verified: dict[str, str] = {}
    for relpath, expected in run.get("artifact_sha256", {}).items():
        path = resolve_repo_path(relpath)
        if not path.is_file():
            raise FileNotFoundError(f"XSim run artifact missing: {relpath}")
        actual = digest(path)
        if actual != expected:
            raise RuntimeError(f"XSim artifact hash mismatch: {relpath}")
        verified[relpath] = actual
    return verified


def inspect_tb_source(tb_text: str) -> dict[str, Any]:
    required = (
        "packed_expected_address = (idx % 4)*20 + (idx / 4);",
        "if (packed_address_seen[packed_address])",
        "if (packed_data !== expected_packed_words[packed_address])",
        "packed_address_seen[packed_address] = 1'b1;",
        "packed_address_seen !== {80{1'b1}}",
        "packed_last !== (idx==79)",
        "wait (dut.output_packer.buffer_full === 2'b11);",
        "consumer_hold_checks != 4",
        "packed_stall_hold_checks < 4",
    )
    missing = [snippet for snippet in required if snippet not in tb_text]
    if missing:
        raise RuntimeError(f"TB source review missed packed/pressure assertions: {missing}")
    assert_pos = tb_text.index("consumer_hold_checks != 4")
    pass_pos = tb_text.index('$display("NATIVE_ROW_PIPELINE_PASS')
    if assert_pos >= pass_pos:
        raise RuntimeError("four-cycle consumer hold assertion is not before the pass marker")
    increment_pos = tb_text.index("consumer_hold_checks = consumer_hold_checks + 1;")
    repeat_pos = tb_text.index("repeat (4) begin", tb_text.index("wait (dut.output_packer.buffer_full === 2'b11);"))
    if not repeat_pos < increment_pos < assert_pos:
        raise RuntimeError("consumer hold counter is not incremented by the four held-buffer checks")
    display_start = tb_text.index('$display("NATIVE_ROW_PIPELINE_PASS')
    display_end = tb_text.index(";", display_start)
    display_stmt = tb_text[display_start:display_end]
    if "buffer_full_seen, packed_stall_hold_checks, pack_done_count" not in display_stmt:
        raise RuntimeError("pass marker no longer maps packed_hold_checks to the stall counter")
    if "consumer_hold_checks" in display_stmt:
        raise RuntimeError("pass marker unexpectedly conflates consumer checks with packed stall checks")
    return {
        "address_formula": "(accepted_index % 4)*20 + (accepted_index / 4), integer division",
        "address_data_lookup_by_actual_address": True,
        "range_duplicate_and_all80_seen_assertions": True,
        "last_only_on_80th_accepted_word": True,
        "done_requires_80_unique_accepted_words": True,
        "consumer_hold_checks_asserted_before_pass": 4,
        "packed_hold_marker_source": "packed_stall_hold_checks",
        "natural_pressure_source": "wait for buffer_full == 2'b11, hold ready low for four checks, then release",
    }


def verify_xsim(run_id: str) -> dict[str, Any]:
    if run_id != XSIM_RUN_ID:
        raise ValueError(f"this packet is pinned to immutable XSim run {XSIM_RUN_ID}")
    result_path = XSIM_EVIDENCE / "result.json"
    host_path = XSIM_EVIDENCE / "host_preflight.json"
    if not result_path.is_file() or not host_path.is_file():
        raise FileNotFoundError("immutable XSim result or host preflight is missing")
    result = read_json(result_path)
    host = read_json(host_path)
    if result.get("status") != "FAILED_CLOSED_XSIM" or result.get("failure_stage") != "xsim":
        raise RuntimeError("the pinned run is not the expected fail-closed XSim run")
    if "backpressure/elastic metadata coverage mismatch" not in result.get("error", ""):
        raise RuntimeError("the pinned run did not fail on the known marker-field mismatch")
    if host.get("status") != "PASS_HOST_PREFLIGHT_ONLY" or host.get("run_id") != run_id:
        raise RuntimeError("the pinned XSim run has no matching passing host preflight")
    if result.get("device_part") != "xc7z100ffg900-2":
        raise RuntimeError("pinned XSim device-part binding differs")
    if result.get("board_access") is not False or result.get("route_attempted") is not False or \
       result.get("full_pipeline_30fps_accepted") is not False:
        raise RuntimeError("pinned run contains an out-of-scope board/route/throughput claim")
    if result.get("vendor_attempts") != {"ooc_synthesis_flows": 0, "retry_count": 0, "xsim_flows": 1}:
        raise RuntimeError("pinned XSim vendor-attempt record is unexpected")
    toolchain = result.get("toolchain", {})
    if (toolchain.get("vivado_version") != "2026.1" or toolchain.get("numerical_threads") != 1 or
        toolchain.get("xelab_mt") != 2):
        raise RuntimeError(f"pinned XSim tool settings differ: {toolchain}")
    if host.get("source_sha256") != result.get("source_sha256_before") or \
       host.get("dependency_sha256") != result.get("dependency_sha256_before") or \
       host.get("fixture_sha256") != result.get("fixture_sha256"):
        raise RuntimeError("XSim and host-preflight hash bindings differ")
    if result.get("source_sha256_before") != result.get("source_sha256_after") or \
       result.get("dependency_sha256_before") != result.get("dependency_sha256_after"):
        raise RuntimeError("XSim source/dependency inventory changed during the recorded run")

    frozen = load_validator()
    source_map = frozen.source_paths()
    dependency_map = frozen.dependency_paths()
    sources_now = frozen.inventory(source_map)
    dependencies_now = frozen.inventory(dependency_map)
    if sources_now != result["source_sha256_before"]:
        raise RuntimeError("current frozen source closure differs from the XSim source snapshot")
    if dependencies_now != result["dependency_sha256_before"]:
        raise RuntimeError("current frozen dependency closure differs from the XSim dependency snapshot")
    verify_snapshot(XSIM_EVIDENCE / "source_snapshot", result["source_sha256_before"], "source")
    verify_snapshot(XSIM_EVIDENCE / "dependency_snapshot", result["dependency_sha256_before"], "dependency")
    verified_artifacts = check_artifacts(result)
    if result.get("reference", {}).get("model_identity") != EXPECTED_MODEL:
        raise RuntimeError("host-preflight model/input identity differs from pinned values")
    fixture_paths = {p.resolve().relative_to(ROOT).as_posix(): p
                     for p in XSIM_BUILD.glob("*.hex")}
    if set(fixture_paths) != set(result.get("fixture_sha256", {})):
        raise RuntimeError("XSim fixture list differs from host-preflight fixture binding")
    fixture_hashes = {name: {"bytes": path.stat().st_size, "sha256": digest(path)}
                      for name, path in sorted(fixture_paths.items())}
    if fixture_hashes != result["fixture_sha256"]:
        raise RuntimeError("XSim fixture hash or size differs from host preflight")

    expected_sources = [
        frozen.BANK_RTL, frozen.WINDOW_RTL, frozen.MAC_RTL, frozen.REQUANT_RTL,
        frozen.UNARY_RTL, frozen.PACKER_RTL, frozen.WRAPPER, frozen.TB,
    ]
    commands = result.get("commands", [])
    if len(commands) != 3 or any(item.get("return_code") != 0 for item in commands):
        raise RuntimeError("pinned XSim command log does not show three successful vendor tools")
    expected_commands = [
        [str(frozen.VIVADO_BIN / "xvlog.bat"), "-sv", *map(str, expected_sources)],
        [str(frozen.VIVADO_BIN / "xelab.bat"), "-mt", "2", "tb_z100_native_row_pipeline",
         "-s", "native_row_pipeline_sim"],
        [str(frozen.VIVADO_BIN / "xsim.bat"), "native_row_pipeline_sim", "-runall"],
    ]
    if [item.get("argv") for item in commands] != expected_commands:
        raise RuntimeError("recorded XSim command arguments differ from the frozen build flow")
    for command in commands:
        if Path(command["cwd"]).resolve() != XSIM_BUILD.resolve():
            raise RuntimeError("XSim command working directory differs from the bound build directory")
        log_path = resolve_repo_path(command["log"])
        if not log_path.is_file() or digest(log_path) != command.get("log_sha256"):
            raise RuntimeError("XSim command log hash does not match the frozen report")
        if log_path.read_text(encoding="utf-8", errors="replace") != command.get("output"):
            raise RuntimeError("XSim command output differs from its preserved evidence log")

    xsim_command = commands[-1]
    log_path = resolve_repo_path(xsim_command["log"])
    text = log_path.read_text(encoding="utf-8", errors="replace")
    pass_lines = re.findall(r"(?m)^NATIVE_ROW_PIPELINE_PASS(?:\s+.*)?$", text)
    if len(pass_lines) != 1:
        raise RuntimeError(f"expected one anchored full-row pass marker, got {len(pass_lines)}")
    if re.search(r"(?im)^\s*(?:Fatal:|ERROR:)", text):
        raise RuntimeError("pinned XSim log contains an anchored fatal/error line")
    if not re.search(r"(?m)^\$finish called at time\b", text):
        raise RuntimeError("pinned XSim log has no terminal $finish after the pass marker")
    pairs = re.findall(r"\b([a-z_]+)=(\d+)\b", pass_lines[0])
    marker = {key: int(value) for key, value in pairs}
    if len(marker) != len(pairs) or marker != EXPECTED_MARKER:
        raise RuntimeError(f"full-row pass-marker fields differ: {marker}")
    if text.index(pass_lines[0]) > text.index("$finish called at time"):
        raise RuntimeError("pass marker occurs after simulation termination")

    tb_text = frozen.TB.read_text(encoding="utf-8")
    testbench_review = inspect_tb_source(tb_text)
    if marker["packed_hold_checks"] != marker["packed_stall"]:
        raise RuntimeError("marker value no longer matches packed output stall-stability cycles")
    if marker["full_buffers"] != 1 or marker["packed_stall"] <= 0 or \
       marker["req_stall"] <= 0 or marker["unary_stall"] <= 0:
        raise RuntimeError("natural two-buffer pressure/backpressure propagation was not observed")
    if marker["raw_stall"] != 0 or marker["response_stalls"] != 0 or \
       marker["raw_backpressure_note"] != 1:
        raise RuntimeError("raw/window stall observations or the natural-absence note differ")

    verify_upstream = frozen.verify_upstream()
    if result.get("upstream") != {
        key: {"path": value["path"], "status": value["status"], "sha256": value["sha256"]}
        for key, value in verify_upstream["reports"].items()
    }:
        raise RuntimeError("upstream component report bindings changed since XSim")

    old_report_trees = {
        failed_id: file_inventory(ROOT / "validation/board_z100/native_row_pipeline_v1" / failed_id)
        for failed_id in FAILED_RUN_IDS
    }
    return {
        "review_status": "PASS_BOUNDED_SOURCE_BOUND_XSIM_NUMERICAL_REVIEW_ONLY",
        "xsim_run_id": run_id,
        "xsim_result_path": XSIM_EVIDENCE.relative_to(ROOT).as_posix() + "/result.json",
        "xsim_result_sha256": digest(result_path),
        "xsim_host_preflight_sha256": digest(host_path),
        "xsim_log_path": log_path.relative_to(ROOT).as_posix(),
        "xsim_log_sha256": digest(log_path),
        "xsim_tool_return_codes": [item["return_code"] for item in commands],
        "toolchain": toolchain,
        "source_sha256": sources_now,
        "dependency_sha256": dependencies_now,
        "fixture_sha256": fixture_hashes,
        "artifact_sha256_verified": verified_artifacts,
        "model_identity": result["reference"]["model_identity"],
        "upstream_component_bindings": result["upstream"],
        "pass_marker_counts": marker,
        "packed_address_scoreboard_source_review": testbench_review,
        "marker_mismatch_explanation": {
            "reported_packed_hold_checks": marker["packed_hold_checks"],
            "reported_packed_stall_cycles": marker["packed_stall"],
            "testbench_asserted_consumer_hold_checks_before_pass": 4,
            "reason": "the marker argument is packed_stall_hold_checks; consumer_hold_checks is separately asserted before the marker",
            "existing_validator_status": result["status"],
            "existing_validator_error": result["error"],
        },
        "backpressure_observations": {
            "natural_both_transpose_buffers_full": True,
            "packed_output_stall_cycles": marker["packed_stall"],
            "requant_stall_cycles": marker["req_stall"],
            "unary_stall_cycles": marker["unary_stall"],
            "raw_boundary_stall_cycles": marker["raw_stall"],
            "raw_boundary_absence_note": bool(marker["raw_backpressure_note"]),
            "feature_window_response_stall_cycles": marker["response_stalls"],
            "feature_window_response_stalls_labeled_not_observed": True,
            "site_fifo_full_cycles": marker["site_fifo_full"],
            "raw_backpressure_is_naturally_absent_at_12_sites": True,
        },
        "numeric_coverage": {
            "raw_lane_sums_and_overflow_flags_checked": marker["raw_lanes"] + marker["raw_flags"],
            "raw_lane_values_checked": marker["raw_lanes"],
            "raw_overflow_flags_checked": marker["raw_flags"],
            "post_beats": marker["post_beats"],
            "post_active_bytes": marker["active_bytes"],
            "post_zero_tail_bytes": marker["tail_bytes"],
            "packed_words": marker["packed_words"],
            "packed_bytes": marker["packed_bytes"],
            "all_80_actual_addresses_checked_against_independent_golden": True,
        },
        "limitations": [
            "This evidence accepts only the bounded first-convolution row numeric flow and a later OOC resource screen.",
            "The full-row wrapper does not test in-flight cancel or reset recovery; upstream component recovery tests do not replace that integration test.",
            "Raw-boundary and feature-window response stalls were not observed in this natural run; the TB labels raw absence and this report records both zero counts.",
            "No route, placement, external timing, frequency, board, FPS, production, or abort-acceptance claim is made.",
        ],
        "preserved_failed_run_trees_before_ooc": old_report_trees,
        "xsim_source_snapshot_root": (XSIM_EVIDENCE / "source_snapshot").relative_to(ROOT).as_posix(),
        "xsim_dependency_snapshot_root": (XSIM_EVIDENCE / "dependency_snapshot").relative_to(ROOT).as_posix(),
        "frozen_validator_sha256": digest(VALIDATOR),
        "review_tool_sha256": digest(Path(__file__).resolve()),
    }


def all_source_maps(frozen) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    return frozen.inventory(frozen.source_paths()), frozen.inventory(frozen.dependency_paths())


def create_short_snapshot(frozen, evidence: Path) -> dict[str, Any]:
    source_paths = frozen.source_paths()
    dependency_paths = frozen.dependency_paths()
    source_hashes = frozen.inventory(source_paths)
    dependency_hashes = frozen.inventory(dependency_paths)
    overlap = set(source_hashes) & set(dependency_hashes)
    for relpath in overlap:
        if source_hashes[relpath] != dependency_hashes[relpath]:
            raise RuntimeError(f"overlapping source/dependency identity differs: {relpath}")
    combined = sorted(set(source_hashes) | set(dependency_hashes))
    snapshot_root = evidence / "src"
    manifest_path = evidence / "snapshot_manifest.json"
    if snapshot_root.exists() or manifest_path.exists():
        raise FileExistsError("short snapshot destination already exists; refusing overwrite")
    snapshot_root.mkdir(parents=True, exist_ok=False)
    mapping: dict[str, dict[str, Any]] = {}
    for index, relpath in enumerate(combined):
        roles = []
        if relpath in source_hashes:
            roles.append("source")
        if relpath in dependency_hashes:
            roles.append("dependency")
        expected = source_hashes.get(relpath, dependency_hashes.get(relpath))
        source = source_paths.get(relpath, dependency_paths.get(relpath))
        suffix = Path(relpath).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            suffix = ".dat"
        snapshot_name = f"{index:03d}_{expected['sha256'][:12]}{suffix}"
        target = snapshot_root / snapshot_name
        if target.exists() or snapshot_name in {entry["snapshot_name"] for entry in mapping.values()}:
            raise FileExistsError(f"short snapshot filename collision: {snapshot_name}")
        if len(str(target.resolve())) > 220:
            raise OSError(f"short snapshot path exceeds 220 characters: {target}")
        shutil.copyfile(source, target)
        actual_bytes = target.stat().st_size
        actual_sha = digest(target)
        if actual_bytes != expected["bytes"] or actual_sha != expected["sha256"]:
            raise RuntimeError(f"short snapshot copy verification failed: {relpath}")
        mapping[relpath] = {
            "roles": roles,
            "snapshot_name": snapshot_name,
            "bytes": actual_bytes,
            "sha256": actual_sha,
        }
    names = [entry["snapshot_name"] for entry in mapping.values()]
    actual_names = sorted(path.name for path in snapshot_root.iterdir() if path.is_file())
    if len(mapping) != len(combined) or len(set(names)) != len(names) or sorted(names) != actual_names:
        raise RuntimeError("short snapshot manifest is not a bijection with copied files")
    manifest = {
        "format": "z100_native_row_ooc_short_snapshot_v1",
        "root": snapshot_root.relative_to(ROOT).as_posix(),
        "source_paths": len(source_hashes),
        "dependency_paths": len(dependency_hashes),
        "unique_original_paths": len(combined),
        "shared_source_dependency_paths": len(overlap),
        "snapshot_file_count": len(actual_names),
        "bijection_verified": True,
        "all_bytes_verified": True,
        "max_destination_path_characters": max(len(str((snapshot_root / name).resolve())) for name in actual_names),
        "original_path_to_snapshot": mapping,
    }
    write_json(manifest_path, manifest)
    manifest_sha = digest(manifest_path)
    verify_short_snapshot(evidence, source_hashes, dependency_hashes)
    return {"manifest_path": manifest_path.relative_to(ROOT).as_posix(),
            "manifest_sha256": manifest_sha,
            "manifest": manifest}


def verify_short_snapshot(evidence: Path, source_hashes: dict[str, dict[str, Any]],
                          dependency_hashes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    manifest_path = evidence / "snapshot_manifest.json"
    snapshot_root = evidence / "src"
    if not manifest_path.is_file() or not snapshot_root.is_dir():
        raise FileNotFoundError("short source/dependency snapshot or manifest is missing")
    manifest = read_json(manifest_path)
    mapping = manifest.get("original_path_to_snapshot", {})
    overlap = set(source_hashes) & set(dependency_hashes)
    combined = set(source_hashes) | set(dependency_hashes)
    if set(mapping) != combined:
        raise RuntimeError("short snapshot original-path manifest coverage differs")
    expected_counts = (len(source_hashes), len(dependency_hashes), len(combined), len(overlap))
    actual_counts = (manifest.get("source_paths"), manifest.get("dependency_paths"),
                     manifest.get("unique_original_paths"), manifest.get("shared_source_dependency_paths"))
    if actual_counts != expected_counts:
        raise RuntimeError(f"short snapshot role counts differ: {actual_counts} vs {expected_counts}")
    filenames = [entry.get("snapshot_name") for entry in mapping.values()]
    if len(filenames) != len(set(filenames)):
        raise RuntimeError("short snapshot filenames are not unique")
    actual_names = sorted(path.name for path in snapshot_root.iterdir() if path.is_file())
    if sorted(filenames) != actual_names or manifest.get("snapshot_file_count") != len(combined):
        raise RuntimeError("short snapshot manifest is not a bijection with directory files")
    maximum = 0
    for original, entry in mapping.items():
        roles = []
        if original in source_hashes:
            roles.append("source")
        if original in dependency_hashes:
            roles.append("dependency")
        expected = source_hashes.get(original, dependency_hashes.get(original))
        path = snapshot_root / entry["snapshot_name"]
        maximum = max(maximum, len(str(path.resolve())))
        if entry.get("roles") != roles or not path.is_file():
            raise RuntimeError(f"short snapshot role/file mismatch: {original}")
        if (entry.get("bytes") != expected["bytes"] or entry.get("sha256") != expected["sha256"] or
            path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]):
            raise RuntimeError(f"short snapshot bytes or SHA-256 mismatch: {original}")
    if manifest.get("bijection_verified") is not True or manifest.get("all_bytes_verified") is not True or \
       manifest.get("max_destination_path_characters") != maximum or maximum > 220:
        raise RuntimeError("short snapshot verification summary is invalid")
    return {"manifest_sha256": digest(manifest_path), "snapshot_file_count": len(actual_names),
            "unique_original_paths": len(combined), "maximum_destination_path_characters": maximum}


def mode_census_extension(evidence: Path) -> str:
    census_path = evidence / "dsp48e1_mode_census.tsv"
    summary_path = evidence / "dsp48e1_mode_summary.tsv"
    for path in (census_path, summary_path):
        if "{" in path.resolve().as_posix() or "}" in path.resolve().as_posix():
            raise ValueError(f"unsafe Tcl output path: {path}")
    body = r'''set dsp48 [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]
array set dsp_mode_counts {}
set dsp_mode_file [open {@DSP_MODE_CENSUS@} w]
puts $dsp_mode_file "cell\tUSE_MULT"
foreach cell $dsp48 {
    set name [get_property NAME $cell]
    set mode [string toupper [get_property -quiet USE_MULT $cell]]
    if {$mode eq ""} {set mode "UNAVAILABLE"}
    if {![info exists dsp_mode_counts($mode)]} {set dsp_mode_counts($mode) 0}
    incr dsp_mode_counts($mode)
    puts $dsp_mode_file "$name\t$mode"
}
close $dsp_mode_file
set multiply 0
set none 0
set other 0
foreach mode [array names dsp_mode_counts] {
    if {$mode eq "MULTIPLY"} {set multiply $dsp_mode_counts($mode)} elseif {$mode eq "NONE"} {set none $dsp_mode_counts($mode)} else {incr other $dsp_mode_counts($mode)}
}
set dsp_summary_file [open {@DSP_MODE_SUMMARY@} w]
puts $dsp_summary_file "DSP48E1_COUNT\t[llength $dsp48]"
puts $dsp_summary_file "MULTIPLY\t$multiply"
puts $dsp_summary_file "NONE\t$none"
puts $dsp_summary_file "OTHER\t$other"
close $dsp_summary_file
puts "NATIVE_ROW_DSP_MODES dsp48=[llength $dsp48] multiply=$multiply none=$none other=$other"
if {[llength $dsp48] != 1920 || $multiply != 1536 || $none != 384 || $other != 0} {
    error "integrated DSP48E1 mode census differs from fixed 1920/1536/384 gate"
}
'''
    body = body.replace("@DSP_MODE_CENSUS@", census_path.resolve().as_posix())
    body = body.replace("@DSP_MODE_SUMMARY@", summary_path.resolve().as_posix())
    return body


CREATE_CLOCK_TCL = "create_clock -name row_internal_clk -period 10.000 [get_ports clk]"
SYNTH_DESIGN_TCL = "synth_design -top z100_native_row_pipeline -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none"


def move_clock_after_synthesis(text: str) -> tuple[str, dict[str, Any]]:
    """Move the sole internal-clock line across synth_design, proving a pair swap."""
    lines = text.splitlines(keepends=True)
    normalized = [line.rstrip("\r\n") for line in lines]
    clock_positions = [i for i, line in enumerate(normalized) if line == CREATE_CLOCK_TCL]
    synth_positions = [i for i, line in enumerate(normalized) if line == SYNTH_DESIGN_TCL]
    if len(clock_positions) != 1 or len(synth_positions) != 1:
        raise RuntimeError(
            "frozen Tcl must contain exactly one expected create_clock and synth_design command")
    clock_index, synth_index = clock_positions[0], synth_positions[0]
    if clock_index + 1 != synth_index:
        raise RuntimeError("create_clock is not the single line immediately preceding synth_design")

    expected = list(lines)
    expected[clock_index], expected[synth_index] = expected[synth_index], expected[clock_index]
    corrected = "".join(expected)
    explicit_swap = "".join(lines[:clock_index] + [lines[synth_index], lines[clock_index]] +
                            lines[synth_index + 1:])
    if corrected != explicit_swap:
        raise RuntimeError("Tcl clock-order change was not exactly one adjacent line-pair reorder")
    corrected_lines = [line.rstrip("\r\n") for line in corrected.splitlines(keepends=True)]
    if corrected_lines[clock_index] != SYNTH_DESIGN_TCL or \
       corrected_lines[clock_index + 1] != CREATE_CLOCK_TCL:
        raise RuntimeError("corrected Tcl does not apply the 10 ns clock immediately after synthesis")
    return corrected, {
        "transformation": "swap_adjacent_create_clock_and_synth_design_lines",
        "exact_pair_reorder_verified": True,
        "original_clock_line_1based": clock_index + 1,
        "original_synth_line_1based": synth_index + 1,
        "corrected_synth_line_1based": clock_index + 1,
        "corrected_clock_line_1based": clock_index + 2,
        "period_ns": 10.0,
        "unified_diff": "".join(difflib.unified_diff(
            lines, expected, fromfile="frozen_validator_tcl", tofile="corrected_adapter_tcl")),
    }


def run_one_ooc(run_id: str, vivado: Path) -> dict[str, Any]:
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    review_path = evidence / "review.json"
    if not review_path.is_file():
        raise FileNotFoundError("source-bound review report is missing")
    review = read_json(review_path)
    if review.get("review_status") != "PASS_BOUNDED_SOURCE_BOUND_XSIM_NUMERICAL_REVIEW_ONLY":
        raise RuntimeError("OOC requires a source-bound numeric review PASS")
    final_result_path = evidence / "result.json"
    if final_result_path.exists() or (evidence / "ooc_attempt_started.json").exists():
        raise FileExistsError("refusing a second OOC attempt for this review id")
    if not build.is_dir() or not evidence.is_dir():
        raise FileNotFoundError("review build/evidence directories disappeared")
    if any(build.iterdir()):
        raise RuntimeError("new OOC build directory is not empty")
    if any(path.name not in {"review.json"} for path in evidence.iterdir()):
        raise RuntimeError("new OOC evidence directory contains unexpected pre-existing files")
    if not vivado.is_file():
        raise FileNotFoundError(f"Vivado OOC launcher unavailable: {vivado}")

    frozen = load_validator()
    source_before, dependency_before = all_source_maps(frozen)
    if source_before != review.get("source_sha256") or dependency_before != review.get("dependency_sha256"):
        raise RuntimeError("bound source/dependency closure changed after numeric review")
    frozen_source_sha = digest(VALIDATOR)
    old_reports_before = {
        failed_id: file_inventory(ROOT / "validation/board_z100/native_row_pipeline_v1" / failed_id)
        for failed_id in FAILED_RUN_IDS
    }
    if old_reports_before != review.get("preserved_failed_run_trees_before_ooc"):
        raise RuntimeError("one or both immutable failed reports changed after review")
    short_snapshot = create_short_snapshot(frozen, evidence)

    result: dict[str, Any] = {
        "status": "OOC_RUNNING",
        "run_id": run_id,
        "review_status": review["review_status"],
        "objective": "source-bound bounded native-row numerical XSim review followed by one integrated OOC resource screen",
        "scope": "offline OOC only; no XSim rerun, route, placement acceptance, board, production, abort, frequency, or FPS claim",
        "device_part": "xc7z100ffg900-2",
        "xsim_run_id": XSIM_RUN_ID,
        "xsim_result_sha256": review["xsim_result_sha256"],
        "xsim_log_sha256": review["xsim_log_sha256"],
        "xsim_tool_return_codes": review["xsim_tool_return_codes"],
        "source_sha256_before_ooc": source_before,
        "dependency_sha256_before_ooc": dependency_before,
        "short_snapshot_before_ooc": short_snapshot,
        "frozen_validator_sha256_before_ooc": frozen_source_sha,
        "preserved_failed_run_trees_before_ooc": old_reports_before,
        "build_directory": str(build.resolve()),
        "evidence_directory": str(evidence.resolve()),
        "vivado_launcher": str(vivado.resolve()),
        "attempt_policy": {"ooc_attempts": 1, "xsim_reruns": 0, "route_attempts": 0,
                           "board_access": False, "frequency_acceptance": False},
        "fixed_gates": {"dsp_total": 1920, "dsp_use_mult_multiply": 1536,
                         "dsp_use_mult_none": 384, "bram36eq_max": 180,
                         "slice_lut_max": 120000, "slice_ff_max": 100000,
                         "latches": 0, "blackboxes": 0},
        "limitations": review["limitations"],
        "commands": [],
        "dsp_mode_census_extension_sha256": hashlib.sha256(mode_census_extension(evidence).encode()).hexdigest(),
    }
    write_json(evidence / "ooc_attempt_started.json", {
        "run_id": run_id,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_validator_sha256": frozen_source_sha,
        "policy": "exactly one run_ooc invocation; no retry",
    })
    write_json(final_result_path, result)

    original_make = frozen.make_synth_tcl
    extension = mode_census_extension(evidence)
    marker = 'puts "NATIVE_ROW_OOC_COMPLETE placement=0 routing=0 external_io_timing_acceptance=0"\nexit'

    def make_synth_tcl_with_dsp_modes(out_evidence: Path, out_build: Path) -> str:
        original_text = original_make(out_evidence, out_build)
        text, reorder_proof = move_clock_after_synthesis(original_text)
        if text.count(marker) != 1:
            raise RuntimeError("frozen OOC Tcl terminal marker is not unique")
        final_text = text.replace(marker, extension + marker)
        correction = {
            "format": "z100_native_row_ooc_tcl_clock_order_correction_v1",
            "root_cause": (
                "The prior OOC Tcl issued create_clock on get_ports clk before synth_design; "
                "Vivado completed read_verilog then stopped with [Common 17-53] No open design, "
                "before synthesis. The corrected Tcl applies the same 10 ns diagnostic clock "
                "immediately after the unchanged synth_design command."),
            "prior_failed_run_id": "20261024T042310.874855Z_85ffa7d9",
            "prior_failure_log": "validation/board_z100/nrow_ooc/20261024T042310.874855Z_85ffa7d9/vivado.log",
            "prior_failure_message": "[Common 17-53] User Exception: No open design.",
            "reorder": reorder_proof,
            "original_base_tcl_sha256": hashlib.sha256(original_text.encode("utf-8")).hexdigest(),
            "corrected_base_tcl_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "adapter_generated_tcl_sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
            "dsp_mode_census_extension_sha256": hashlib.sha256(extension.encode("utf-8")).hexdigest(),
        }
        write_json(out_evidence / "ooc_tcl_order_correction.json", correction)
        return final_text

    frozen.make_synth_tcl = make_synth_tcl_with_dsp_modes
    try:
        ooc = frozen.run_ooc(build, evidence, result, vivado)
        result["ooc"] = ooc
        result["dsp_mode_counts"] = parse_dsp_modes(evidence)
        validate_ooc(result, evidence)
        result["status"] = "PASS_BOUNDED_NATIVE_ROW_OOC_RESOURCE_SCREEN_ONLY"
    except Exception as error:
        result["status"] = "FAILED_CLOSED_OOC"
        result["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        source_after, dependency_after = all_source_maps(frozen)
        result["source_sha256_after_ooc"] = source_after
        result["dependency_sha256_after_ooc"] = dependency_after
        result["frozen_validator_sha256_after_ooc"] = digest(VALIDATOR)
        old_reports_after = {
            failed_id: file_inventory(ROOT / "validation/board_z100/native_row_pipeline_v1" / failed_id)
            for failed_id in FAILED_RUN_IDS
        }
        result["preserved_failed_run_trees_after_ooc"] = old_reports_after
        correction_path = evidence / "ooc_tcl_order_correction.json"
        if correction_path.is_file():
            correction = read_json(correction_path)
            tcl_path = evidence / "synth.tcl"
            if tcl_path.is_file():
                written_tcl = tcl_path.read_text(encoding="utf-8")
                written_lines = [line.rstrip("\r\n") for line in written_tcl.splitlines(keepends=True)]
                synth_at = [i for i, line in enumerate(written_lines) if line == SYNTH_DESIGN_TCL]
                clock_at = [i for i, line in enumerate(written_lines) if line == CREATE_CLOCK_TCL]
                correction["written_tcl_sha256"] = digest(tcl_path)
                correction["written_tcl_hash_matches_adapter"] = (
                    correction["written_tcl_sha256"] == correction["adapter_generated_tcl_sha256"])
                correction["written_tcl_clock_order_verified"] = (
                    len(synth_at) == 1 and len(clock_at) == 1 and clock_at[0] == synth_at[0] + 1)
            else:
                correction["written_tcl_sha256"] = None
                correction["written_tcl_hash_matches_adapter"] = False
                correction["written_tcl_clock_order_verified"] = False
            write_json(correction_path, correction)
            result["tcl_order_correction_report"] = {
                "path": correction_path.relative_to(ROOT).as_posix(),
                "sha256": digest(correction_path),
                "written_tcl_hash_matches_adapter": correction["written_tcl_hash_matches_adapter"],
                "written_tcl_clock_order_verified": correction["written_tcl_clock_order_verified"],
            }
        try:
            result["short_snapshot_after_ooc"] = verify_short_snapshot(
                evidence, source_before, dependency_before)
            result["short_snapshot_unchanged"] = (
                result["short_snapshot_after_ooc"]["manifest_sha256"] ==
                short_snapshot["manifest_sha256"])
        except Exception as snapshot_error:
            result["short_snapshot_unchanged"] = False
            result["short_snapshot_after_ooc_error"] = f"{type(snapshot_error).__name__}: {snapshot_error}"
        result["source_dependency_and_old_report_immutability"] = {
            "source_unchanged": source_after == source_before,
            "dependencies_unchanged": dependency_after == dependency_before,
            "validator_unchanged": result["frozen_validator_sha256_after_ooc"] == frozen_source_sha,
            "failed_reports_unchanged": old_reports_after == old_reports_before,
            "short_snapshot_unchanged": result.get("short_snapshot_unchanged") is True,
        }
        if not all(result["source_dependency_and_old_report_immutability"].values()):
            result["status"] = "FAILED_CLOSED_OOC_INTEGRITY"
            result["failure"] = result.get("failure", "source/dependency/report identity changed during OOC")
        artifact_hashes = {}
        for base in (build, evidence):
            for path in sorted(p for p in base.rglob("*") if p.is_file() and p != final_result_path):
                artifact_hashes[path.relative_to(ROOT).as_posix()] = digest(path)
        result["new_artifact_sha256"] = artifact_hashes
        write_json(final_result_path, result)
    return result


def parse_dsp_modes(evidence: Path) -> dict[str, Any]:
    census_path = evidence / "dsp48e1_mode_census.tsv"
    summary_path = evidence / "dsp48e1_mode_summary.tsv"
    if not census_path.is_file() or not summary_path.is_file():
        raise RuntimeError("integrated DSP mode census output is missing")
    lines = census_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "cell\tUSE_MULT":
        raise RuntimeError("integrated DSP mode census header differs")
    cells: set[str] = set()
    modes: Counter[str] = Counter()
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 2 or not fields[0] or fields[0] in cells:
            raise RuntimeError("integrated DSP mode census has malformed or duplicate cell rows")
        cells.add(fields[0])
        modes[fields[1]] += 1
    summary: dict[str, int] = {}
    for line in summary_path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 2:
            raise RuntimeError("integrated DSP mode summary row malformed")
        summary[fields[0]] = int(fields[1])
    counts = {"DSP48E1_COUNT": len(cells), "MULTIPLY": modes["MULTIPLY"],
              "NONE": modes["NONE"], "OTHER": len(cells)-modes["MULTIPLY"]-modes["NONE"]}
    if summary != counts or counts != {"DSP48E1_COUNT": 1920, "MULTIPLY": 1536, "NONE": 384, "OTHER": 0}:
        raise RuntimeError(f"integrated DSP mode gate failed: summary={summary}, computed={counts}")
    return {"counts": counts, "unique_cells": len(cells),
            "census_sha256": digest(census_path), "summary_sha256": digest(summary_path)}


def validate_ooc(result: dict[str, Any], evidence: Path) -> None:
    ooc = result.get("ooc")
    if not isinstance(ooc, dict) or ooc.get("status") != "PASS_FIXED_RESOURCE_SCREEN":
        raise RuntimeError("frozen OOC validator did not pass fixed resource gates")
    counts = ooc.get("primitive_counts", {})
    modes = result.get("dsp_mode_counts", {}).get("counts", {})
    memory = ooc.get("memory_ownership", {})
    gates = ooc.get("fixed_gates", {})
    if counts.get("DSP") != 1920 or modes != {"DSP48E1_COUNT": 1920, "MULTIPLY": 1536, "NONE": 384, "OTHER": 0}:
        raise RuntimeError(f"integrated DSP primitive/mode census failed: DSP={counts.get('DSP')} modes={modes}")
    if not memory.get("all_dsps_owned_by_native_mac", False):
        raise RuntimeError("integrated DSP primitive ownership was not reconciled to native MAC")
    if counts.get("LATCH") != 0 or counts.get("BLACKBOX") != 0:
        raise RuntimeError(f"latch/blackbox census differs: {counts}")
    if ooc.get("bram36_equivalent", 10**9) > 180 or not memory.get("bram_ownership_reconciled", False):
        raise RuntimeError("integrated BRAM budget or ownership reconciliation failed")
    if ooc.get("slice_lut", 10**9) > 120000 or ooc.get("slice_ff", 10**9) > 100000:
        raise RuntimeError("integrated LUT/FF resource gate failed")
    if not all(gates.values()):
        raise RuntimeError(f"frozen OOC fixed gates do not all pass: {gates}")
    if ooc.get("timing_scope", {}).get("frequency_accepted") is not False or \
       ooc.get("timing_scope", {}).get("placement_or_route") is not False:
        raise RuntimeError("OOC report unexpectedly accepts frequency or place/route")
    output = (evidence / "vivado_stdout.log").read_text(encoding="utf-8", errors="replace")
    if output.count("NATIVE_ROW_OOC_COMPLETE placement=0 routing=0 external_io_timing_acceptance=0") != 1:
        raise RuntimeError("OOC terminal marker missing or duplicated")
    mode_marker = re.findall(r"(?m)^NATIVE_ROW_DSP_MODES dsp48=(\d+) multiply=(\d+) none=(\d+) other=(\d+)$", output)
    if mode_marker != [("1920", "1536", "384", "0")]:
        raise RuntimeError(f"Vivado output does not report the required actual DSP mode census: {mode_marker}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("review", "ooc"), default="review")
    parser.add_argument("--run-id")
    parser.add_argument("--vivado", type=Path, default=VIVADO)
    args = parser.parse_args()
    if args.phase == "review":
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
        build = BUILD_ROOT / run_id
        evidence = EVIDENCE_ROOT / run_id
        build.mkdir(parents=True, exist_ok=False)
        evidence.mkdir(parents=True, exist_ok=False)
        try:
            result = verify_xsim(XSIM_RUN_ID)
            result.update({"run_id": run_id,
                           "build_directory": str(build.resolve()),
                           "evidence_directory": str(evidence.resolve()),
                           "ooc_status": "NOT_RUN_YET"})
        except Exception as error:
            result = {"review_status": "FAILED_CLOSED_SOURCE_BOUND_REVIEW",
                      "run_id": run_id,
                      "failure": f"{type(error).__name__}: {error}",
                      "xsim_run_id": XSIM_RUN_ID,
                      "build_directory": str(build.resolve()),
                      "evidence_directory": str(evidence.resolve())}
        write_json(evidence / "review.json", result)
        print(json.dumps({"review_status": result["review_status"], "run_id": run_id,
                          "review": (evidence / "review.json").relative_to(ROOT).as_posix(),
                          "failure": result.get("failure")}, sort_keys=True), flush=True)
        return 0 if result["review_status"].startswith("PASS_") else 2
    if not args.run_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", args.run_id):
        parser.error("--run-id is required for OOC and must be a safe simple identifier")
    try:
        result = run_one_ooc(args.run_id, args.vivado)
        print(json.dumps({"status": result["status"], "run_id": args.run_id,
                          "report": (EVIDENCE_ROOT / args.run_id / "result.json").relative_to(ROOT).as_posix(),
                          "ooc": result.get("ooc"), "dsp_mode_counts": result.get("dsp_mode_counts")},
                         sort_keys=True), flush=True)
        return 0 if result["status"].startswith("PASS_") else 2
    except Exception as error:
        evidence = EVIDENCE_ROOT / args.run_id
        build = BUILD_ROOT / args.run_id
        report_path = evidence / "result.json"
        if evidence.is_dir() and not (evidence / "ooc_attempt_started.json").exists() and not report_path.exists():
            partial_src = evidence / "src"
            try:
                partial_files = file_inventory(partial_src) if partial_src.is_dir() else {}
            except Exception as inventory_error:
                partial_files = {"inventory_error": {"bytes": 0, "sha256": f"{type(inventory_error).__name__}: {inventory_error}"}}
            report_path = evidence / "ooc_preflight_failure.json"
            write_json(report_path, {
                "status": "FAILED_CLOSED_OOC_PREFLIGHT",
                "run_id": args.run_id,
                "failure": f"{type(error).__name__}: {error}",
                "stage": "before_ooc_attempt_record_and_before_run_ooc",
                "vivado_launched": False,
                "run_ooc_invocations": 0,
                "xsim_rerun": False,
                "build_directory_empty": build.is_dir() and not any(build.iterdir()),
                "partial_short_snapshot_files": partial_files,
                "review_sha256": digest(evidence / "review.json") if (evidence / "review.json").is_file() else None,
            })
        print(json.dumps({"status": "FAILED_CLOSED_OOC", "run_id": args.run_id,
                          "report": report_path.relative_to(ROOT).as_posix(),
                          "error": f"{type(error).__name__}: {error}"}, sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
