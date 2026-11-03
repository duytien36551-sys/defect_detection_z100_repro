"""Validate the private row-to-addressed-store and next-window path.

The host phase derives the existing independent first-row fixture and freezes
all source/dependency bytes into short indexed paths. The single XSim phase
checks the unchanged full-row oracle, precommit isolation, downstream bank
reads, and cancel/reset reload recovery. No synthesis, route, board access, or
FPS acceptance is part of this tool.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
PARTITION_ADAPTER = ROOT / "tools/validate_z100_native_row_partition.py"
STORE_DIR = ROOT / "deployment/hardware/z100_2026/native_row_store_v1"
STORE_RTL = STORE_DIR / "z100_native_row_store.sv"
STORE_TB = STORE_DIR / "tb_z100_native_row_store.sv"
ADDRESSED_BANK_RTL = ROOT / "deployment/hardware/z100_2026/feature_banks_addressed_v1/z100_feature_banks_addressed.sv"
ADDRESSED_WINDOW_RTL = ROOT / "deployment/hardware/z100_2026/feature_window_addressed_v3/z100_feature_window_addressed.sv"
REVIEW_ROOT = ROOT / "validation/board_z100/nrowp_review"
ROW_PARTITION_RUN = "20261024T044106.631331Z_844a2330"
ROW_PARTITION_RESULT = ROOT / "validation/board_z100/nrowpart" / ROW_PARTITION_RUN / "result.json"
ROW_PARTITION_REVIEW = REVIEW_ROOT / "20261024T045220.047881Z_bedfdf9d/review.json"
ROW_PARTITION_REVIEW_SHA256 = "e114e7ccef68580812b9e8fb8b2d95a3329d90ca42f295c72ed71cf099e13d3f"
ROW_REVIEW_HELPER = ROOT / "tools/review_z100_native_row_partition_ooc.py"
ADDRESSED_ROOT_REVIEW = ROOT / "validation/board_z100/acceleration_resource_review/20261023T184429.878019Z/addressed_reuse_review.json"
ADDRESSED_ROOT_REVIEW_SHA256 = "06fb18a31d98de9699fea8bb07dcbee1201c11b4cbd1c6f7ccf3729d957a7eb7"
ADDRESSED_REVIEW_HELPER = ROOT / "tools/review_z100_addressed_reuse.py"
ADDRESSED_BANK_RESULT = ROOT / "validation/board_z100/feature_banks_addressed_v1/20261023T183839.445577Z_9c859c25/result.json"
ADDRESSED_BANK_RESULT_SHA256 = "bf120ba4c98115fef893dc3bc93e5ea65cc612784887a141fd067dc1c7a0996b"
ADDRESSED_BANK_DIAGNOSIS = ROOT / "validation/board_z100/feature_banks_addressed_v1/corrective_review_20261023T183839.445577Z_9c859c25/review.json"
ADDRESSED_BANK_DIAGNOSIS_SHA256 = "637d082e394d1264e4df463bc9d41041d80f575ac1841c8604903cac8e6e9a6f"
ADDRESSED_WINDOW_RESULT = ROOT / "validation/board_z100/feature_window_addressed_v3/20261023T184114.781081Z/result.json"
ADDRESSED_WINDOW_RESULT_SHA256 = "328736a36015d34353034109150e64da992334fbbd1bb9a6a4f8e41f20ef7b91"
ADDRESSED_BANK_RTL_SHA256 = "62c30b0487a54edd6125affa492b3d79c2987203f8cba992fae6560051df656a"
ADDRESSED_WINDOW_RTL_SHA256 = "2476ab7b407249ccb79fd085a18db3b9303bdb803f7589646b40c784129b483f"
PREVIOUS_RUN_ID = "20261024T045952.415724Z_5badc0df"
PREVIOUS_ACTIVE_RESET_RUN_ID = "20261024T050435.590800Z_6e9f93e7"
PREVIOUS_COUNTER_LOSS_RUN_ID = "20261024T050710.394848Z_aed76fe3"
BUILD_ROOT = ROOT / "deployment/build/nrs"
EVIDENCE_ROOT = ROOT / "validation/board_z100/nrs"
PREVIOUS_RESULT = EVIDENCE_ROOT / PREVIOUS_RUN_ID / "result.json"
PREVIOUS_ACTIVE_RESET_EVIDENCE = EVIDENCE_ROOT / PREVIOUS_ACTIVE_RESET_RUN_ID
PREVIOUS_ACTIVE_RESET_RESULT = PREVIOUS_ACTIVE_RESET_EVIDENCE / "result.json"
PREVIOUS_COUNTER_LOSS_EVIDENCE = EVIDENCE_ROOT / PREVIOUS_COUNTER_LOSS_RUN_ID
PREVIOUS_COUNTER_LOSS_RESULT = PREVIOUS_COUNTER_LOSS_EVIDENCE / "result.json"
PASS_XSIM_STATUS = "PASS_NATIVE_ROW_STORE_ROW_AND_RELOAD_XSIM_ONLY"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def inventory(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in sorted(paths.items())}


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import required validator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def modules() -> tuple[Any, Any]:
    part = load_module("z100_native_row_store_partition_adapter", PARTITION_ADAPTER)
    frozen = part.load_frozen()
    return part, frozen


def source_maps(part: Any, frozen: Any) -> tuple[dict[str, Path], dict[str, Path]]:
    sources = dict(frozen.source_paths())
    for path in (PARTITION_ADAPTER, STORE_RTL, STORE_TB, ADDRESSED_BANK_RTL,
                 ADDRESSED_WINDOW_RTL, SCRIPT):
        key = rel(path)
        if key in sources and sources[key].resolve() != path.resolve():
            raise RuntimeError(f"source path aliases a different file: {key}")
        sources[key] = path
    if len(frozen.source_paths()) != 48:
        raise RuntimeError("frozen first-row source closure no longer contains48 paths")
    dependencies = dict(frozen.dependency_paths())
    for path in (ROW_PARTITION_RESULT, ROW_PARTITION_REVIEW, ROW_REVIEW_HELPER):
        key = rel(path)
        if key in dependencies and dependencies[key].resolve() != path.resolve():
            raise RuntimeError(f"dependency path aliases a different file: {key}")
        dependencies[key] = path
    for path in (ROW_PARTITION_RESULT, ROW_PARTITION_REVIEW, ROW_REVIEW_HELPER,
                 ADDRESSED_ROOT_REVIEW, ADDRESSED_REVIEW_HELPER, ADDRESSED_BANK_RESULT,
                 ADDRESSED_BANK_DIAGNOSIS, ADDRESSED_WINDOW_RESULT, PREVIOUS_RESULT,
                 PREVIOUS_ACTIVE_RESET_RESULT, PREVIOUS_COUNTER_LOSS_RESULT):
        key = rel(path)
        if key in dependencies and dependencies[key].resolve() != path.resolve():
            raise RuntimeError(f"dependency path aliases a different file: {key}")
        dependencies[key] = path
    if len(dependencies) != 31:
        raise RuntimeError(f"expected31 model/upstream/review dependencies, found {len(dependencies)}")
    return dict(sorted(sources.items())), dict(sorted(dependencies.items()))


def check_partition_review(part: Any) -> dict[str, Any]:
    if not ROW_PARTITION_REVIEW.is_file() or sha256(ROW_PARTITION_REVIEW) != ROW_PARTITION_REVIEW_SHA256:
        raise RuntimeError("passing source-bound partition-v2 full-row review is missing or changed")
    review = json.loads(ROW_PARTITION_REVIEW.read_text(encoding="utf-8"))
    original = json.loads(ROW_PARTITION_RESULT.read_text(encoding="utf-8"))
    if (review.get("status") != "PASS_BOUNDED_PARTITION_V2_FULL_ROW_XSIM_OOC_RESOURCE_SCREEN_REVIEW" or
        not review.get("checks") or not all(review["checks"].values()) or
        review.get("ooc", {}).get("partition_source") != part.rel(part.PARTITION_RTL) or
        review.get("ooc", {}).get("partition_source_sha256") != part.PARTITION_RTL_SHA256 or
        review.get("original_result", {}).get("sha256_before_review") != sha256(ROW_PARTITION_RESULT) or
        original.get("status") != "FAILED_CLOSED_PARTITION_V2_OOC" or
        original.get("scope", {}).get("board_access") is not False or
        original.get("scope", {}).get("full_pipeline_30fps_accepted") is not False):
        raise RuntimeError("saved partition-v2 full-row/XSim/OOC review binding or scope differs")
    if sha256(ROW_REVIEW_HELPER) != review.get("review_helper_sha256"):
        raise RuntimeError("partition-v2 offline review helper no longer matches its report")
    artifact_map = review.get("integrity", {}).get("all_saved_artifact_sha256", {})
    if len(artifact_map) != 118:
        raise RuntimeError("partition-v2 run report no longer binds its 118 artifacts")
    for name, expected in artifact_map.items():
        artifact = ROOT / Path(name.replace("\\", "/"))
        if not artifact.is_file() or sha256(artifact) != expected:
            raise RuntimeError(f"prior partition-v2 row artifact changed: {name}")
    return {
        "path": rel(ROW_PARTITION_REVIEW),
        "sha256": ROW_PARTITION_REVIEW_SHA256,
        "status": review["status"],
        "all_checks_passed": len(review["checks"]),
        "actual_partition_source": review["ooc"]["partition_source"],
        "actual_partition_source_sha256": review["ooc"]["partition_source_sha256"],
        "original_row_result_sha256": sha256(ROW_PARTITION_RESULT),
        "original_row_artifact_count_and_hashes_verified": len(artifact_map),
        "scope": review["scope"],
    }


def verify_report_file_map(values: dict[str, str], label: str) -> int:
    if not isinstance(values, dict) or not values:
        raise RuntimeError(f"{label} has no bound file hash map")
    for name, expected in values.items():
        path = ROOT / Path(name.replace("\\", "/"))
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"{label} hash mismatch: {name}")
    return len(values)


def check_addressed_prerequisite() -> dict[str, Any]:
    exact_files = {
        ADDRESSED_ROOT_REVIEW: ADDRESSED_ROOT_REVIEW_SHA256,
        ADDRESSED_BANK_RESULT: ADDRESSED_BANK_RESULT_SHA256,
        ADDRESSED_BANK_DIAGNOSIS: ADDRESSED_BANK_DIAGNOSIS_SHA256,
        ADDRESSED_WINDOW_RESULT: ADDRESSED_WINDOW_RESULT_SHA256,
        ADDRESSED_REVIEW_HELPER: "8d3115dba771388632f58e9ab914e53ca473782a00c2b9ae12f27b73190eee94",
        ADDRESSED_BANK_RTL: ADDRESSED_BANK_RTL_SHA256,
        ADDRESSED_WINDOW_RTL: ADDRESSED_WINDOW_RTL_SHA256,
    }
    for path, expected in exact_files.items():
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"addressed-bank/window prerequisite changed: {rel(path)}")

    review = json.loads(ADDRESSED_ROOT_REVIEW.read_text(encoding="utf-8"))
    bank = json.loads(ADDRESSED_BANK_RESULT.read_text(encoding="utf-8"))
    diagnosis = json.loads(ADDRESSED_BANK_DIAGNOSIS.read_text(encoding="utf-8"))
    window = json.loads(ADDRESSED_WINDOW_RESULT.read_text(encoding="utf-8"))
    if (review.get("status") != "ROOT_ACCEPT_PRIVATE_ADDRESSED_BANK_AND_NEXT_WINDOW_REUSE_BOUNDED_ONLY" or
        review.get("bank_report_sha256") != ADDRESSED_BANK_RESULT_SHA256 or
        review.get("bank_diagnosis_sha256") != ADDRESSED_BANK_DIAGNOSIS_SHA256 or
        review.get("window_report_sha256") != ADDRESSED_WINDOW_RESULT_SHA256 or
        review.get("window_original_status") != "FAILED_SOURCE_INTEGRITY" or
        review.get("exact_report_only_drift_reconciled") is not True or
        review.get("vendor_repeated") is not False or
        review.get("window_vectors") != 784 or
        review.get("complete_row_to_store_or_pingpong_scheduler_accepted") is not False or
        review.get("clock_route_board_or_30fps_accepted") is not False):
        raise RuntimeError("root addressed-store reuse review/status/scope binding differs")
    if (bank.get("status") != "PASS_PRIVATE_ADDRESSED_FEATURE_BANK_XSIM_OOC_ONLY" or
        bank.get("source_sha256_before") != bank.get("source_sha256_after") or
        bank.get("source_sha256_after", {}).get(
            "deployment\\hardware\\z100_2026\\feature_banks_addressed_v1\\z100_feature_banks_addressed.sv"
        ) != ADDRESSED_BANK_RTL_SHA256 or
        diagnosis.get("status") != "PASS_EVIDENCE_PENDING_PRIMARY_REVIEW" or
        diagnosis.get("vendor_result_immutable") is not True or
        diagnosis.get("vendor_result_sha256") != ADDRESSED_BANK_RESULT_SHA256):
        raise RuntimeError("addressed-bank source/result/corrective diagnosis binding differs")
    drift = {name for name in window.get("source_sha256_before", {})
             if window["source_sha256_before"].get(name) != window.get("source_sha256_after", {}).get(name)}
    window_key = str(ADDRESSED_BANK_RESULT.relative_to(ROOT)).replace("/", "\\")
    if (window.get("status") != "FAILED_SOURCE_INTEGRITY" or
        drift != {window_key} or
        window.get("source_sha256_after", {}).get(
            "deployment\\hardware\\z100_2026\\feature_window_addressed_v3\\z100_feature_window_addressed.sv"
        ) != ADDRESSED_WINDOW_RTL_SHA256 or
        window.get("source_sha256_after", {}).get(
            "deployment\\hardware\\z100_2026\\feature_banks_addressed_v1\\z100_feature_banks_addressed.sv"
        ) != ADDRESSED_BANK_RTL_SHA256 or
        window.get("simulation") != {"status": "PASS", "windows": 784, "stalls": 291,
                                     "max_consecutive_results": 24,
                                     "scatter_to_next_window": True}):
        raise RuntimeError("addressed-window source-bound report drift or simulation evidence differs")

    bank_hashes = verify_report_file_map(bank.get("source_sha256_after", {}), "addressed bank sources")
    bank_artifacts = verify_report_file_map(bank.get("artifact_sha256", {}), "addressed bank artifacts")
    window_hashes = verify_report_file_map(window.get("source_sha256_after", {}), "addressed window sources")
    window_artifacts = verify_report_file_map(window.get("artifact_sha256", {}), "addressed window artifacts")
    return {
        "root_review_path": rel(ADDRESSED_ROOT_REVIEW),
        "root_review_sha256": ADDRESSED_ROOT_REVIEW_SHA256,
        "root_review_status": review["status"],
        "addressed_bank_rtl_sha256": ADDRESSED_BANK_RTL_SHA256,
        "addressed_window_rtl_sha256": ADDRESSED_WINDOW_RTL_SHA256,
        "bank_report_sha256": ADDRESSED_BANK_RESULT_SHA256,
        "bank_diagnosis_sha256": ADDRESSED_BANK_DIAGNOSIS_SHA256,
        "window_report_sha256": ADDRESSED_WINDOW_RESULT_SHA256,
        "bank_source_hashes_verified": bank_hashes,
        "bank_artifact_hashes_verified": bank_artifacts,
        "window_source_hashes_verified": window_hashes,
        "window_artifact_hashes_verified": window_artifacts,
        "window_numeric_simulation": window["simulation"],
        "whole_row_store_or_30fps_acceptance": False,
    }


def check_previous_failed_runs() -> dict[str, Any]:
    if (not PREVIOUS_RESULT.is_file() or not PREVIOUS_ACTIVE_RESET_RESULT.is_file() or
        not PREVIOUS_COUNTER_LOSS_RESULT.is_file()):
        raise RuntimeError("one of the three previous failed row-store runs disappeared")
    first = json.loads(PREVIOUS_RESULT.read_text(encoding="utf-8"))
    active = json.loads(PREVIOUS_ACTIVE_RESET_RESULT.read_text(encoding="utf-8"))
    counter_loss = json.loads(PREVIOUS_COUNTER_LOSS_RESULT.read_text(encoding="utf-8"))
    expected_policy = {"xsim_attempts": 1, "ooc_attempts": 0, "route_attempts": 0}
    if (first.get("status") != "FAILED_CLOSED_NATIVE_ROW_STORE_XSIM" or
        first.get("failure") != "RuntimeError: single xelab run failed; the XSim attempt is consumed" or
        first.get("xsim_attempt_policy") != expected_policy or
        "Module <z100_feature_window_addressed> not found" not in first["commands"][1]["output"]):
        raise RuntimeError("first failed row-store source-closure run is missing or changed")
    if (active.get("status") != "FAILED_CLOSED_NATIVE_ROW_STORE_XSIM" or
        active.get("failure") != "RuntimeError: single xsim run failed; no retry is permitted" or
        active.get("xsim_attempt_policy") != expected_policy or
        any(command.get("return_code") != 0 for command in active.get("commands", []))):
        raise RuntimeError("active-reset oracle-index failure run is missing or changed")
    active_output = active["commands"][-1]["output"]
    expected_failure = "Fatal: reloaded bank direct CHW mismatch channel=1 site=0"
    if (expected_failure not in active_output or "NATIVE_ROW_PIPELINE_PASS" not in active_output or
        "NATIVE_ROW_STORE_PASS" in active_output or active.get("xsim_coverage")):
        raise RuntimeError("previous row-store run was promoted or its exact first failure changed")

    counter_loss_expected = "RuntimeError: row-store coverage mismatch partial_cancel_runs: 0 != 2"
    counter_loss_output = counter_loss.get("commands", [{}])[-1].get("output", "")
    counter_loss_markers = re.findall(r"(?m)^NATIVE_ROW_(?:PIPELINE|STORE)_PASS .+$", counter_loss_output)
    if (counter_loss.get("status") != "FAILED_CLOSED_NATIVE_ROW_STORE_XSIM" or
        counter_loss.get("failure") != counter_loss_expected or
        counter_loss.get("xsim_attempt_policy") != expected_policy or
        any(command.get("return_code") != 0 for command in counter_loss.get("commands", [])) or
        len(counter_loss_markers) != 2 or
        "NATIVE_ROW_PIPELINE_PASS" not in counter_loss_output or
        "NATIVE_ROW_STORE_PASS" not in counter_loss_output or
        not all(f"{key}=0" in counter_loss_output for key in (
            "partial_cancel_runs", "partial_cancel_requests", "partial_cancel_responses",
            "partial_cancel_raw", "partial_cancel_post", "partial_cancel_packed")) or
        not all(f"{key}={value}" in counter_loss_output for key, value in (
            ("reset_partial_runs", 2), ("reset_partial_requests", 18),
            ("reset_partial_responses", 18), ("reset_partial_raw", 24),
            ("reset_partial_post", 18), ("reset_partial_packed", 2),
            ("reset_reload_runs", 27), ("reset_reload_requests", 243),
            ("reset_reload_raw", 320), ("reset_reload_post", 320),
            ("reset_reload_packed", 80))) or counter_loss.get("xsim_coverage")):
        raise RuntimeError("third failed row-store counter-loss report or original pass markers changed")

    summaries: list[dict[str, Any]] = []
    for result_path, result in ((PREVIOUS_RESULT, first),
                                (PREVIOUS_ACTIVE_RESET_RESULT, active),
                                (PREVIOUS_COUNTER_LOSS_RESULT, counter_loss)):
        expected_artifacts = result.get("new_artifact_sha256")
        if not isinstance(expected_artifacts, dict) or not expected_artifacts:
            raise RuntimeError(f"previous row-store run has no immutable artifact map: {result_path}")
        verified = verify_report_file_map(expected_artifacts, "previous row-store run artifacts")
        summaries.append({"path": rel(result_path), "result_sha256": sha256(result_path),
                          "status": result["status"], "failure": result["failure"],
                          "artifact_count_and_hashes_verified": verified,
                          "pass_markers_emitted_without_acceptance": (
                              result_path == PREVIOUS_COUNTER_LOSS_RESULT and
                              len(counter_loss_markers) == 2),
                          "counter_loss_parser_failure_preserved": (
                              result_path == PREVIOUS_COUNTER_LOSS_RESULT and
                              result.get("failure") == counter_loss_expected),
                          "last_vendor_log_sha256": next(
                              command["log_sha256"] for command in reversed(result["commands"])
                              if command["argv"][0].endswith("xsim.bat") or
                                 command["argv"][0].endswith("xelab.bat"))})
    return {"runs": summaries, "first_source_closure_failure_preserved": True,
            "second_expected_index_failure_preserved": True,
            "third_counter_loss_parser_failure_preserved": True,
            "third_run_emitted_both_pass_markers_but_was_not_promoted": True,
            "second_failure_was_not_promoted_to_pass": True,
            "active_reset_failure_excerpt": expected_failure,
            "counter_loss_failure_excerpt": counter_loss_expected,
            "counter_loss_partial_counters": {key: 0 for key in (
                "partial_cancel_runs", "partial_cancel_requests", "partial_cancel_responses",
                "partial_cancel_raw", "partial_cancel_post", "partial_cancel_packed")}}


def check_recovery_expected_byte_fix() -> dict[str, Any]:
    snapshot_manifest_path = PREVIOUS_ACTIVE_RESET_EVIDENCE / "snapshot.json"
    manifest = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
    key = "deployment/hardware/z100_2026/native_row_store_v1/tb_z100_native_row_store.sv"
    item = manifest["original_path_to_snapshot"].get(key)
    if not isinstance(item, dict):
        raise RuntimeError("prior active-reset testbench snapshot binding is missing")
    prior_tb_snapshot = PREVIOUS_ACTIVE_RESET_EVIDENCE / "s" / item["snapshot_name"]
    before = prior_tb_snapshot.read_bytes()
    counter_loss_manifest = json.loads((PREVIOUS_COUNTER_LOSS_EVIDENCE / "snapshot.json").read_text(encoding="utf-8"))
    counter_loss_item = counter_loss_manifest["original_path_to_snapshot"].get(key)
    if not isinstance(counter_loss_item, dict):
        raise RuntimeError("prior counter-loss testbench snapshot binding is missing")
    counter_loss_tb_snapshot = PREVIOUS_COUNTER_LOSS_EVIDENCE / "s" / counter_loss_item["snapshot_name"]
    corrected_prior = counter_loss_tb_snapshot.read_bytes()
    current = STORE_TB.read_bytes()
    old = b"expected_next_byte=expected_post_words[ns][(nc*4)*8+:8];"
    new = b"expected_next_byte=expected_post_words[ns][nc*8+:8];"
    if (sha256(prior_tb_snapshot) != item.get("sha256") or before.count(old) != 1 or
        sha256(counter_loss_tb_snapshot) != counter_loss_item.get("sha256") or
        before.replace(old, new, 1) != corrected_prior or current.count(new) != 1):
        raise RuntimeError("saved expected-index correction chain or current corrected expression differs")
    return {"pre_index_tb_snapshot_sha256": item["sha256"],
            "counter_loss_tb_snapshot_sha256": counter_loss_item["sha256"],
            "current_tb_sha256": sha256(STORE_TB),
            "exact_changed_expression_count": 1, "old_expression": old.decode(),
            "new_expression": new.decode(),
            "saved_index_only_diff_matches_counter_loss_snapshot": True,
            "baseline_assertions_and_other_recovery_logic_unchanged": True}


def check_partial_cancel_counter_latch_fix() -> dict[str, Any]:
    snapshot_manifest_path = PREVIOUS_COUNTER_LOSS_EVIDENCE / "snapshot.json"
    manifest = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
    key = "deployment/hardware/z100_2026/native_row_store_v1/tb_z100_native_row_store.sv"
    item = manifest["original_path_to_snapshot"].get(key)
    if not isinstance(item, dict):
        raise RuntimeError("prior counter-loss testbench snapshot binding is missing")
    prior_tb_snapshot = PREVIOUS_COUNTER_LOSS_EVIDENCE / "s" / item["snapshot_name"]
    before = prior_tb_snapshot.read_bytes()
    after = STORE_TB.read_bytes()
    if sha256(prior_tb_snapshot) != item.get("sha256"):
        raise RuntimeError("prior counter-loss testbench snapshot hash changed")

    declaration_old = b"    integer partial_post_beats = 0, partial_packed_beats = 0;"
    declaration_new = declaration_old + (
        b"\r\n    integer partial_cancel_evidence_runs = 0, partial_cancel_evidence_requests = 0;"
        b"\r\n    integer partial_cancel_evidence_responses = 0, partial_cancel_evidence_raw = 0;"
        b"\r\n    integer partial_cancel_evidence_post = 0, partial_cancel_evidence_packed = 0;"
    )
    checkpoint_old = b"        @(negedge clk); next_window_epoch=EPOCH; next_window_tag=32'h73000001;"
    checkpoint_new = (
        b"        partial_cancel_evidence_runs=partial_run_accepts;\r\n"
        b"        partial_cancel_evidence_requests=partial_window_requests;\r\n"
        b"        partial_cancel_evidence_responses=partial_window_responses;\r\n"
        b"        partial_cancel_evidence_raw=partial_raw_beats;\r\n"
        b"        partial_cancel_evidence_post=partial_post_beats;\r\n"
        b"        partial_cancel_evidence_packed=partial_packed_beats;\r\n" + checkpoint_old
    )
    marker_old = (
        b"                 partial_run_accepts,partial_window_requests,partial_window_responses,\r\n"
        b"                 partial_raw_beats,partial_post_beats,partial_packed_beats,\r\n"
    )
    marker_new = (
        b"                 partial_cancel_evidence_runs,partial_cancel_evidence_requests,\r\n"
        b"                 partial_cancel_evidence_responses,partial_cancel_evidence_raw,\r\n"
        b"                 partial_cancel_evidence_post,partial_cancel_evidence_packed,\r\n"
    )
    if (before.count(declaration_old) != 1 or before.count(checkpoint_old) != 1 or
        before.count(marker_old) != 1):
        raise RuntimeError("prior testbench no longer has the exact authorized counter-latch anchors")
    expected = before.replace(declaration_old, declaration_new, 1)
    expected = expected.replace(checkpoint_old, checkpoint_new, 1)
    expected = expected.replace(marker_old, marker_new, 1)
    if expected != after:
        raise RuntimeError("row-store testbench differs beyond the authorized counter snapshot and marker edits")
    if after.count(b"partial_cancel_evidence_runs=") != 1:
        raise RuntimeError("counter evidence latch is not a unique pre-cancel checkpoint")
    return {
        "previous_tb_snapshot_sha256": item["sha256"],
        "current_tb_sha256": sha256(STORE_TB),
        "authorized_exact_replacements": 3,
        "captured_counters": ["runs", "requests", "responses", "raw", "post", "packed"],
        "checkpoint_is_after_partial_traffic_guard_before_cancel": True,
        "evidence_variables_are_not_reset_by_dut_reset": True,
        "only_final_marker_arguments_use_latched_values": True,
        "all_other_tb_bytes_unchanged": True,
    }


def parse_module_ports(text: str, module_name: str) -> list[str]:
    start = re.search(r"\bmodule\s+" + re.escape(module_name) + r"\b", text)
    if not start:
        raise ValueError(f"module declaration absent: {module_name}")
    first_open = text.find("(", start.end())
    if first_open < 0:
        raise ValueError(f"module has no parameter/port parenthesis: {module_name}")

    def matching_close(open_at: int) -> int:
        depth = 0
        for index in range(open_at, len(text)):
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    return index
        raise ValueError(f"unclosed module declaration parentheses: {module_name}")

    first_close = matching_close(first_open)
    after_first = first_close + 1
    second_open = text.find("(", after_first)
    if second_open < 0 or text[after_first:second_open].strip() not in ("", "#"):
        raise ValueError(f"cannot locate ANSI port declaration: {module_name}")
    second_close = matching_close(second_open)
    ports: list[str] = []
    for token in text[second_open+1:second_close].split(","):
        token = re.sub(r"/\*.*?\*/|//[^\n]*", " ", token, flags=re.S)
        token = re.sub(r"\[[^\]]*\]", " ", token)
        identifiers = re.findall(r"[A-Za-z_]\w*", token)
        if not identifiers:
            raise ValueError(f"unparsed port declaration in {module_name}: {token!r}")
        ports.append(identifiers[-1])
    return ports


def module_instantiations(source: str) -> list[tuple[str, str]]:
    code = re.sub(r"/\*.*?\*/|//[^\n]*", " ", source, flags=re.S)
    code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)
    keywords = {
        "always", "always_comb", "always_ff", "always_latch", "and", "assign", "automatic",
        "begin", "buf", "case", "casex", "casez", "default", "default_nettype", "do", "else",
        "end", "endcase", "endfunction", "endgenerate", "endmodule", "endtask", "event", "for",
        "foreach", "fork", "function", "generate", "if", "initial", "inout", "input", "integer",
        "join", "join_any", "join_none", "localparam", "logic", "macromodule", "module", "negedge",
        "or", "output", "parameter", "posedge", "reg", "repeat", "return", "signed", "string", "task",
        "time", "typedef", "union", "unsigned", "var", "wait", "wand", "wire", "while", "wor",
    }
    instances: list[tuple[str, str]] = []
    for line_start in re.finditer(r"(?m)^[ \t]*([A-Za-z_]\w*)", code):
        module_type = line_start.group(1)
        if module_type in keywords:
            continue
        cursor = line_start.end()
        while cursor < len(code) and code[cursor].isspace():
            cursor += 1
        if cursor < len(code) and code[cursor] == "#":
            cursor += 1
            while cursor < len(code) and code[cursor].isspace():
                cursor += 1
            if cursor >= len(code) or code[cursor] != "(":
                continue
            depth = 0
            while cursor < len(code):
                if code[cursor] == "(":
                    depth += 1
                elif code[cursor] == ")":
                    depth -= 1
                    if depth == 0:
                        cursor += 1
                        break
                cursor += 1
            if depth != 0:
                continue
        while cursor < len(code) and code[cursor].isspace():
            cursor += 1
        instance = re.match(r"[A-Za-z_]\w*", code[cursor:])
        if instance is None:
            continue
        instance_name = instance.group(0)
        cursor += instance.end()
        while cursor < len(code) and code[cursor].isspace():
            cursor += 1
        if cursor < len(code) and code[cursor] == "(":
            instances.append((module_type, instance_name))
    return instances


def check_module_closure(source_paths: list[Path]) -> dict[str, Any]:
    declarations: dict[str, str] = {}
    source_texts: dict[Path, str] = {}
    for path in source_paths:
        if path.suffix.lower() != ".sv":
            continue
        text = path.read_text(encoding="utf-8")
        source_texts[path] = text
        for name in re.findall(r"(?m)^\s*module\s+([A-Za-z_]\w*)", text):
            if name in declarations:
                raise RuntimeError(f"duplicate compiled module declaration {name}")
            declarations[name] = rel(path)
    if not declarations:
        raise RuntimeError("XSim compile source closure contains no module declarations")
    missing: list[dict[str, str]] = []
    instances: list[dict[str, str]] = []
    for path, text in source_texts.items():
        for module_type, instance_name in module_instantiations(text):
            item = {"source": rel(path), "module_type": module_type, "instance": instance_name}
            instances.append(item)
            if module_type not in declarations:
                missing.append(item)
    if missing:
        compact = ", ".join(f"{item['module_type']}({item['instance']}) from {item['source']}"
                             for item in missing)
        raise RuntimeError(f"XSim compile-source module closure is incomplete: {compact}")
    return {"compiled_module_count": len(declarations), "compiled_modules": declarations,
            "module_instantiation_count": len(instances), "all_instantiated_modules_defined": True,
            "instances": instances}


def xsim_source_keys(part: Any, frozen: Any) -> list[str]:
    return [
        rel(frozen.BANK_RTL), rel(ADDRESSED_BANK_RTL),
        rel(frozen.WINDOW_RTL), rel(ADDRESSED_WINDOW_RTL),
        rel(frozen.MAC_RTL), rel(part.PARTITION_RTL), rel(frozen.UNARY_RTL),
        rel(frozen.PACKER_RTL), rel(frozen.WRAPPER), rel(STORE_RTL), rel(STORE_TB),
    ]


def check_wrapper_and_testbench(frozen: Any) -> dict[str, Any]:
    row_text = frozen.WRAPPER.read_text(encoding="utf-8")
    store_text = STORE_RTL.read_text(encoding="utf-8")
    tb_text = STORE_TB.read_text(encoding="utf-8")
    row_ports = parse_module_ports(row_text, "z100_native_row_pipeline")
    instance = re.search(r"z100_native_row_pipeline\s*#\(.*?\)\s*row\s*\((.*?)\)\s*;",
                         store_text, re.S)
    if instance is None:
        raise RuntimeError("row store does not contain the direct frozen row-pipeline instance")
    row_connections = re.findall(r"\.([A-Za-z_]\w*)\s*\(", instance.group(1))
    if (len(row_ports) != 116 or len(row_connections) != 116 or
        len(set(row_connections)) != 116 or set(row_ports) != set(row_connections)):
        raise RuntimeError("row store must preserve exactly all116 row ports, once each")
    store_ports = parse_module_ports(store_text, "z100_native_row_store")
    if len(set(store_ports)) != len(store_ports):
        raise RuntimeError("row store module has duplicate top-level ports")
    tb_names = set(re.findall(r"\b[A-Za-z_]\w*\b", tb_text))
    missing_tb_names = sorted(set(store_ports) - tb_names)
    if missing_tb_names or "dut (.*);" not in tb_text:
        raise RuntimeError(f"row-store testbench wildcard connection is incomplete: {missing_tb_names}")

    baseline_assertions = (
        "consumer_hold_checks != 4", "packed_address_seen !== {80{1'b1}}",
        "packed_beats != 80", "packed_byte_checks != 80*64",
        "raw_lane_checks != ROW_WIDTH*32", "raw_flag_checks != ROW_WIDTH*32",
        "post_active_byte_checks != ROW_WIDTH*16", "post_tail_byte_checks != ROW_WIDTH*16",
        "expected_raw_words[idx][32+result_lane*32 +: 32]",
        "expected_post_words[idx][result_lane*8 +: 8]",
        "expected_packed_words[packed_address]", "expected_window_data[idx]",
        "packed_expected_address = (idx % 4)*20 + (idx / 4);",
    )
    marker_at = tb_text.find("NATIVE_ROW_PIPELINE_PASS")
    if marker_at < 0 or any(tb_text.find(assertion) < 0 or tb_text.find(assertion) > marker_at
                            for assertion in baseline_assertions):
        raise RuntimeError("unchanged full-row golden/assertion set is absent before the baseline pass marker")
    recovery_assertions = (
        "partial_packed_beats>=FEATURE_WORDS", "partial cancel did not invalidate every exposed frame/store",
        "reset_partial_packed_beats>=FEATURE_WORDS", "!dut.bank_loading",
        "active reset did not immediately invalidate partial row/store state",
        "active reset did not return row/store interfaces to clean idle",
        "recovery_raw_lane_checks!=ROW_WIDTH*32", "recovery_raw_flag_checks!=ROW_WIDTH*32",
        "recovery_post_active_checks!=ROW_WIDTH*16", "recovery_post_tail_checks!=ROW_WIDTH*16",
        "recovery_address_seen!=={FEATURE_WORDS{1'b1}}", "reset_reload_next_window=1",
    )
    if any(assertion not in tb_text for assertion in recovery_assertions):
        raise RuntimeError("partial-cancel/reset-reload oracle/assertions are incomplete")
    return {
        "frozen_row_port_count": len(row_ports),
        "direct_row_port_connections": len(row_connections),
        "row_ports_exact_once": True,
        "row_store_top_port_count": len(store_ports),
        "testbench_wildcard_ports_bound": len(store_ports),
        "baseline_numeric_assertions_preserved_before_original_pass_marker": len(baseline_assertions),
        "partial_cancel_reset_reload_static_assertions": len(recovery_assertions),
        "store_wrapper_sha256": sha256(STORE_RTL),
        "store_testbench_sha256": sha256(STORE_TB),
    }


def snapshot_paths(sources: dict[str, Path], dependencies: dict[str, Path], evidence: Path) -> dict[str, Any]:
    snapshot_root = evidence / "s"
    snapshot_root.mkdir(parents=True, exist_ok=False)
    entries: dict[str, dict[str, Any]] = {}
    for role, mapping in (("source", sources), ("dependency", dependencies)):
        for original, path in mapping.items():
            resolved = str(path.resolve())
            entry = entries.setdefault(original, {"path": resolved, "roles": []})
            if entry["path"] != resolved:
                raise RuntimeError(f"snapshot key aliases different source files: {original}")
            entry["roles"].append(role)
    destinations: list[str] = []
    for index, (original, entry) in enumerate(sorted(entries.items())):
        source = Path(entry["path"])
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = sha256(source)
        suffix = source.suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", source.suffix or "") else ".bin"
        name = f"{index:02x}_{digest[:16]}{suffix}"
        target = snapshot_root / name
        shutil.copyfile(source, target)
        if target.stat().st_size != source.stat().st_size or sha256(target) != digest:
            raise RuntimeError(f"short snapshot byte check failed: {original}")
        entry.update({"snapshot_name": name, "bytes": source.stat().st_size, "sha256": digest})
        destinations.append(name)
    manifest = {
        "format": "z100_native_row_store_indexed_source_snapshot_v1",
        "original_path_to_snapshot": entries,
        "snapshot_file_count": len(destinations),
        "unique_original_path_count": len(entries),
        "maximum_destination_path_characters": max(len(str((snapshot_root / name).resolve()))
                                                        for name in destinations),
        "all_bytes_verified": True,
        "bijection_verified": len(destinations) == len(set(destinations)) == len(entries),
    }
    if not manifest["bijection_verified"]:
        raise RuntimeError("short source snapshot names are not a one-to-one map")
    manifest_path = evidence / "snapshot.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest_sha256"] = sha256(manifest_path)
    return manifest


def verify_snapshot(evidence: Path, sources: dict[str, Path], dependencies: dict[str, Path]) -> dict[str, Any]:
    path = evidence / "snapshot.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mapping = manifest.get("original_path_to_snapshot")
    expected = {**sources, **dependencies}
    if not isinstance(mapping, dict) or set(mapping) != set(expected):
        raise RuntimeError("short indexed snapshot source/dependency key set changed")
    names: list[str] = []
    for original, source in expected.items():
        item = mapping[original]
        name = item.get("snapshot_name")
        if not isinstance(name, str) or Path(name).name != name:
            raise RuntimeError(f"unsafe snapshot name for {original}")
        target = evidence / "s" / name
        names.append(name)
        if (not target.is_file() or item.get("bytes") != source.stat().st_size or
            item.get("sha256") != sha256(source) or target.stat().st_size != source.stat().st_size or
            sha256(target) != sha256(source)):
            raise RuntimeError(f"snapshot content differs from source: {original}")
    actual = sorted(p.name for p in (evidence / "s").iterdir() if p.is_file())
    if sorted(names) != actual or len(names) != len(set(names)):
        raise RuntimeError("snapshot directory is not an exact bijection")
    if manifest.get("all_bytes_verified") is not True or manifest.get("bijection_verified") is not True:
        raise RuntimeError("snapshot manifest verification flags are not true")
    return {"manifest_sha256": sha256(path), "snapshot_file_count": len(actual),
            "maximum_destination_path_characters": manifest["maximum_destination_path_characters"]}


def preserved_inventory(part: Any) -> dict[str, Any]:
    return {
        "prior_row_review_outputs": part.file_inventory(REVIEW_ROOT),
        "partition_adapter_preserved_report_roots": part.preserved_reports_inventory(),
    }


def verify_prior_report_state(part: Any, expected: dict[str, Any]) -> bool:
    return preserved_inventory(part) == expected


def check_fixture_binding(build: Path, fixture: dict[str, Any]) -> None:
    required = {"feature_words.hex", "native_weight_groups.hex", "native_bias.hex",
                "req_cfg.hex", "unary_cfg.hex", "expected_windows.hex",
                "expected_window_masks.hex", "expected_raw_words.hex",
                "expected_post_words.hex", "expected_packed_words.hex"}
    if set(fixture.get("fixtures", {})) != required:
        raise RuntimeError("frozen original-arithmetic fixture output set changed")
    for name, item in fixture["fixtures"].items():
        path = build / name
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise RuntimeError(f"prepared original-model fixture hash mismatch: {name}")
    if (fixture.get("geometry", {}).get("runs") != 27 or
        fixture.get("geometry", {}).get("runs_with_12_sites") != 26 or
        fixture.get("geometry", {}).get("tail_sites") != 8 or
        fixture.get("independent_reference", {}).get("raw_reference", "").find("signed64 NCHW") < 0 or
        fixture.get("independent_reference", {}).get("threshold_tree_used_as_golden") is not False):
        raise RuntimeError("fixture lost its frozen 27-run/OIHW/signed64 independent golden identity")


def host_phase(run_id: str) -> dict[str, Any]:
    part, frozen = modules()
    bindings = part.partition_bindings(frozen)
    review_binding = check_partition_review(part)
    addressed_binding = check_addressed_prerequisite()
    previous_binding = check_previous_failed_runs()
    sources, dependencies = source_maps(part, frozen)
    dependencies = dict(dependencies)
    # Bind the exact downstream-approved row-store predecessor separately from
    # the original row result, which intentionally retains its parser failure.
    store_structure = check_wrapper_and_testbench(frozen)
    expected_index_fix = check_recovery_expected_byte_fix()
    counter_latch_fix = check_partial_cancel_counter_latch_fix()
    upstream = part.summarize_upstream(frozen, bindings)
    compile_keys = xsim_source_keys(part, frozen)
    compile_paths = [sources[key] for key in compile_keys]
    module_closure = check_module_closure(compile_paths)
    build = BUILD_ROOT / run_id
    evidence = EVIDENCE_ROOT / run_id
    if build.exists() or evidence.exists():
        raise FileExistsError("refusing to overwrite an earlier row-store run")
    build.mkdir(parents=True)
    evidence.mkdir(parents=True)
    fixture = frozen.prepare_fixture(build)
    check_fixture_binding(build, fixture)
    diagnosis = {
        "status": "DIAGNOSED_PREVIOUS_TESTBENCH_EXPECTED_INDEX_BUG_ONLY_NOT_ACCEPTANCE",
        "failed_run": PREVIOUS_ACTIVE_RESET_RUN_ID,
        "failed_result_path": rel(PREVIOUS_ACTIVE_RESET_RESULT),
        "failed_result_sha256": sha256(PREVIOUS_ACTIVE_RESET_RESULT),
        "first_failure": "Fatal: reloaded bank direct CHW mismatch channel=1 site=0",
        "evidence": "The prior simulation emitted NATIVE_ROW_PIPELINE_PASS but no NATIVE_ROW_STORE_PASS.",
        "expected_byte_change": expected_index_fix,
        "previous_failures_promoted_to_pass": False,
        "no_simulation_claim_from_this_diagnosis": True,
    }
    diagnosis_path = evidence / "previous_expected_index_failure_diagnosis.json"
    diagnosis_path.write_text(json.dumps(diagnosis, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    counter_loss_diagnosis = {
        "status": "DIAGNOSED_PREVIOUS_PARTIAL_CANCEL_COUNTER_LOSS_ONLY_NOT_ACCEPTANCE",
        "failed_run": PREVIOUS_COUNTER_LOSS_RUN_ID,
        "failed_result_path": rel(PREVIOUS_COUNTER_LOSS_RESULT),
        "failed_result_sha256": sha256(PREVIOUS_COUNTER_LOSS_RESULT),
        "failed_xsim_log_sha256": json.loads(PREVIOUS_COUNTER_LOSS_RESULT.read_text(encoding="utf-8"))[
            "commands"][-1]["log_sha256"],
        "both_pass_markers_were_emitted": True,
        "parser_failure": "row-store coverage mismatch partial_cancel_runs: 0 != 2",
        "partial_cancel_counters_after_later_dut_reset": {
            key: 0 for key in ("runs", "requests", "responses", "raw", "post", "packed")},
        "independent_reset_partial_and_full_reload_coverage_was_present": True,
        "earlier_run_promoted_to_acceptance": False,
    }
    counter_loss_diagnosis_path = evidence / "prior_partial_cancel_counterloss_diagnosis.json"
    counter_loss_diagnosis_path.write_text(
        json.dumps(counter_loss_diagnosis, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    source_before = inventory(sources)
    dependency_before = inventory(dependencies)
    preserved_before = preserved_inventory(part)
    snapshot = snapshot_paths(sources, dependencies, evidence)
    verified_snapshot = verify_snapshot(evidence, sources, dependencies)
    if verified_snapshot["manifest_sha256"] != snapshot["manifest_sha256"]:
        raise RuntimeError("fresh indexed source snapshot changed during host verification")
    report = {
        "status": "PASS_HOST_PREFLIGHT_ONLY",
        "run_id": run_id,
        "scope": {"board_access": False, "route": False, "frequency_acceptance": False,
                  "production_integrated": False, "full_pipeline_30fps_accepted": False},
        "host": {"python_version": sys.version.split()[0], "numerical_threads": 1},
        "source_path_count": len(sources),
        "dependency_path_count": len(dependencies),
        "source_sha256_before_xsim": source_before,
        "dependency_sha256_before_xsim": dependency_before,
        "preserved_report_inventories_before_xsim": preserved_before,
        "snapshot": verified_snapshot,
        "store_structure": store_structure,
        "upstream_prerequisites": upstream,
        "partition_row_review_binding": review_binding,
        "addressed_bank_window_root_review_binding": addressed_binding,
        "previous_failed_rowstore_run_preserved": previous_binding,
        "exact_recovery_read_expected_index_fix": expected_index_fix,
        "exact_pre_cancel_counter_latch_fix": counter_latch_fix,
        "previous_expected_index_failure_diagnosis": {
            "path": rel(diagnosis_path), "sha256": sha256(diagnosis_path),
            "status": diagnosis["status"], "previous_failures_promoted_to_pass": False,
        },
        "prior_partial_cancel_counter_loss_diagnosis": {
            "path": rel(counter_loss_diagnosis_path), "sha256": sha256(counter_loss_diagnosis_path),
            "status": counter_loss_diagnosis["status"], "earlier_run_promoted_to_acceptance": False,
        },
        "fixture": fixture,
        "xsim_source_paths": compile_keys,
        "xsim_module_closure": module_closure,
        "xsim_attempt_policy": {"xsim_attempts": 0, "ooc_attempts": 0, "route_attempts": 0},
    }
    (evidence / "host_preflight.json").write_text(json.dumps(report, indent=2, sort_keys=True)+"\n",
                                                     encoding="utf-8")
    result = {
        "status": "PASS_HOST_PREFLIGHT_ONLY", "run_id": run_id,
        "build_directory": str(build.resolve()), "evidence_directory": str(evidence.resolve()),
        "host_preflight_path": rel(evidence / "host_preflight.json"),
        "host_preflight_sha256": sha256(evidence / "host_preflight.json"),
        "xsim_attempt_policy": {"xsim_attempts": 0, "ooc_attempts": 0, "route_attempts": 0},
        "scope": report["scope"],
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n",
                                          encoding="utf-8")
    return result


def run_logged(command: list[str], cwd: Path, log: Path, env: dict[str, str], timeout: int = 1800) -> dict[str, Any]:
    completed = subprocess.run(subprocess.list2cmdline(command), cwd=str(cwd), shell=True, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
    log.write_text(completed.stdout, encoding="utf-8")
    return {"argv": command, "cwd": str(cwd.resolve()), "return_code": completed.returncode,
            "log": rel(log), "log_sha256": sha256(log),
            "warning_count": len(re.findall(r"\bWARNING\b", completed.stdout, re.I)),
            "output": completed.stdout}


def parse_store_pass(output: str) -> dict[str, Any]:
    matches = re.findall(r"(?m)^NATIVE_ROW_STORE_PASS (.+)$", output)
    if len(matches) != 1:
        raise RuntimeError("full row-store completion marker is missing or duplicated")
    values: dict[str, int] = {}
    for field in matches[0].split():
        if field.count("=") != 1:
            raise RuntimeError(f"malformed row-store marker field: {field}")
        key, value = field.split("=", 1)
        if key in values:
            raise RuntimeError(f"duplicate row-store marker field: {key}")
        values[key] = int(value)
    expected_keys = {
        "next_windows", "active_bytes", "padding_bytes", "barrier_checks", "committed_cancel",
        "partial_cancel_runs", "partial_cancel_requests", "partial_cancel_responses",
        "partial_cancel_raw", "partial_cancel_post", "partial_cancel_packed",
        "partial_cancel_output_invalid", "reset_partial_runs", "reset_partial_requests",
        "reset_partial_responses", "reset_partial_raw", "reset_partial_post",
        "reset_partial_packed", "reset_partial_active_confirmed",
        "reset_partial_commit_absent", "reset_partial_output_invalid",
        "reset_reload_runs", "reset_reload_requests",
        "reset_reload_responses", "reset_reload_window_bytes", "reset_reload_raw",
        "reset_reload_raw_lanes", "reset_reload_raw_flags", "reset_reload_post",
        "reset_reload_active_bytes", "reset_reload_tail_bytes", "reset_reload_packed",
        "reset_reload_packed_bytes", "reset_reload_done", "reset_reload_store_valid",
        "reset_reload_next_window",
    }
    if set(values) != expected_keys:
        raise RuntimeError(f"row-store marker schema differs: {sorted(values)}")
    exact = {
        "next_windows": 108, "active_bytes": 5120, "padding_bytes": 64,
        "barrier_checks": 100, "committed_cancel": 1,
        "partial_cancel_runs": 2, "partial_cancel_requests": 18,
        "partial_cancel_responses": 18, "partial_cancel_output_invalid": 1,
        "reset_partial_runs": 2, "reset_partial_requests": 18,
        "reset_partial_responses": 18, "reset_partial_active_confirmed": 1,
        "reset_partial_commit_absent": 1, "reset_partial_output_invalid": 1,
        "reset_reload_runs": 27, "reset_reload_requests": 243,
        "reset_reload_responses": 243, "reset_reload_window_bytes": 243*48,
        "reset_reload_raw": 320, "reset_reload_raw_lanes": 320*32,
        "reset_reload_raw_flags": 320*32, "reset_reload_post": 320,
        "reset_reload_active_bytes": 320*16, "reset_reload_tail_bytes": 320*16,
        "reset_reload_packed": 80, "reset_reload_packed_bytes": 80*64,
        "reset_reload_done": 1, "reset_reload_store_valid": 1,
        "reset_reload_next_window": 1,
    }
    for key, value in exact.items():
        if values[key] != value:
            raise RuntimeError(f"row-store coverage mismatch {key}: {values[key]} != {value}")
    for key in ("partial_cancel_raw", "partial_cancel_post", "partial_cancel_packed"):
        if values[key] <= 0:
            raise RuntimeError(f"in-flight cancel lacks accepted work: {key}={values[key]}")
    if values["partial_cancel_packed"] >= 80:
        raise RuntimeError("partial-cancel phase completed the full packed output instead of canceling in flight")
    for key in ("reset_partial_raw", "reset_partial_post", "reset_partial_packed"):
        if values[key] <= 0:
            raise RuntimeError(f"active-reset phase lacks accepted work: {key}={values[key]}")
    if values["reset_partial_packed"] >= 80:
        raise RuntimeError("active-reset phase completed the full packed output instead of resetting in flight")
    return {"status": "PASS", "counts": values,
            "precommit_unreadable_checks": values["barrier_checks"],
            "committed_cancel_invalidated_store": True,
            "inflight_partial_cancel_observed": True,
            "synchronous_reset_during_partial_write_observed": True,
            "synchronous_reset_followed_by_full_config_reload": True,
            "reload_matches_full_raw_post_and_pack_goldens": True,
            "reloaded_bank_direct_window_checks": 1}


def artifact_hashes(build: Path, evidence: Path, result_path: Path) -> dict[str, str]:
    return {rel(path): sha256(path) for base in (build, evidence)
            for path in sorted(p for p in base.rglob("*") if p.is_file() and p != result_path)}


def xsim_phase(run_id: str) -> dict[str, Any]:
    part, frozen = modules()
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    result_path = evidence / "result.json"
    host_path = evidence / "host_preflight.json"
    if not evidence.is_dir() or not build.is_dir() or not host_path.is_file() or not result_path.is_file():
        raise FileNotFoundError("matching row-store host preflight/build directory is required")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    host = json.loads(host_path.read_text(encoding="utf-8"))
    if result.get("status") != "PASS_HOST_PREFLIGHT_ONLY" or host.get("status") != "PASS_HOST_PREFLIGHT_ONLY":
        raise RuntimeError("one XSim is permitted only after the matching host preflight passes")
    attempt = evidence / "xsim_attempt_started.json"
    if attempt.exists():
        raise FileExistsError("one row-store XSim attempt has already started; refusing retry")
    sources, dependencies = source_maps(part, frozen)
    source_before = inventory(sources)
    dependency_before = inventory(dependencies)
    prior_before = preserved_inventory(part)
    addressed_before = check_addressed_prerequisite()
    previous_before = check_previous_failed_runs()
    expected_index_fix = check_recovery_expected_byte_fix()
    counter_latch_fix = check_partial_cancel_counter_latch_fix()
    snapshot = verify_snapshot(evidence, sources, dependencies)
    compile_keys = xsim_source_keys(part, frozen)
    compile_paths = [sources[key] for key in compile_keys]
    module_closure = check_module_closure(compile_paths)
    if (source_before != host.get("source_sha256_before_xsim") or
        dependency_before != host.get("dependency_sha256_before_xsim") or
        prior_before != host.get("preserved_report_inventories_before_xsim") or
        addressed_before != host.get("addressed_bank_window_root_review_binding") or
        previous_before != host.get("previous_failed_rowstore_run_preserved") or
        expected_index_fix != host.get("exact_recovery_read_expected_index_fix") or
        counter_latch_fix != host.get("exact_pre_cancel_counter_latch_fix") or
        module_closure != host.get("xsim_module_closure") or
        snapshot.get("manifest_sha256") != host.get("snapshot", {}).get("manifest_sha256")):
        raise RuntimeError("source/dependency/prior review/snapshot identities changed after host preflight")

    source_keys = host.get("xsim_source_paths", [])
    if source_keys != compile_keys or len(source_keys) != 11:
        raise RuntimeError("full row-store XSim source list must include addressed bank/window and partition v2")
    manifest = json.loads((evidence / "snapshot.json").read_text(encoding="utf-8"))
    snapshot_root = evidence / "s"
    vendor_sources = [snapshot_root / manifest["original_path_to_snapshot"][key]["snapshot_name"]
                      for key in source_keys]
    if not all(path.is_file() for path in vendor_sources):
        raise RuntimeError("short frozen XSim source snapshot is incomplete")
    for tool_name in ("xvlog.bat", "xelab.bat", "xsim.bat"):
        if not (frozen.VIVADO_BIN / tool_name).is_file():
            raise FileNotFoundError(f"Vivado 2026.1 XSim tool unavailable: {frozen.VIVADO_BIN / tool_name}")
    attempt.write_text(json.dumps({"run_id": run_id, "attempt": 1,
                                   "started_utc": datetime.now(timezone.utc).isoformat(),
                                   "source_snapshot_sha256": snapshot["manifest_sha256"],
                                   "vendor_source_keys": source_keys,
                                   "module_closure": module_closure,
                                   "policy": "one XSim only; no OOC, route, or board"},
                                  indent=2, sort_keys=True)+"\n", encoding="utf-8")
    result["status"] = "XSIM_RUNNING"
    result["xsim_attempt_policy"] = {"xsim_attempts": 1, "ooc_attempts": 0, "route_attempts": 0}
    result["xsim_source_paths"] = source_keys
    result["xsim_module_closure"] = module_closure
    result["xsim_source_sha256_before"] = source_before
    result["xsim_dependency_sha256_before"] = dependency_before
    result["preserved_report_inventories_before_xsim"] = prior_before
    (evidence / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")

    commands: list[dict[str, Any]] = []
    try:
        env = frozen.phase_env()
        xvlog = [str(frozen.VIVADO_BIN / "xvlog.bat"), "-sv", *map(str, vendor_sources)]
        commands.append(run_logged(xvlog, build, evidence / "xvlog.log", env))
        if commands[-1]["return_code"] != 0:
            raise RuntimeError("single xvlog run failed; the XSim attempt is consumed")
        xelab = [str(frozen.VIVADO_BIN / "xelab.bat"), "-mt", "2",
                 "tb_z100_native_row_store", "-s", "native_row_store_sim"]
        commands.append(run_logged(xelab, build, evidence / "xelab.log", env))
        if commands[-1]["return_code"] != 0:
            raise RuntimeError("single xelab run failed; the XSim attempt is consumed")
        xsim = [str(frozen.VIVADO_BIN / "xsim.bat"), "native_row_store_sim", "-runall"]
        commands.append(run_logged(xsim, build, evidence / "xsim.log", env))
        output = commands[-1]["output"]
        if commands[-1]["return_code"] != 0 or re.search(r"(?im)^\s*(?:Fatal:|ERROR:)", output):
            raise RuntimeError("single xsim run failed; no retry is permitted")
        static_checks = {
            "consumer_hold_checks_exactly4_asserted_before_pass_marker": True,
            "packed_hold_marker_is_stall_stability_and_uses_minimum4": True,
            "raw_post_and_80_word_checks_unchanged": True,
        }
        row_coverage = part.parse_full_row_pass(output, static_checks)
        store_coverage = parse_store_pass(output)
        if "NATIVE_ROW_STORE_PASS" in output and output.count("NATIVE_ROW_STORE_PASS") != 1:
            raise RuntimeError("row-store completion marker is duplicated")
        result.update({
            "status": PASS_XSIM_STATUS,
            "xsim_coverage": {"frozen_full_row": row_coverage, "row_store": store_coverage},
            "xsim_vendor_arguments": [command["argv"] for command in commands],
            "xsim_tool_return_codes": [command["return_code"] for command in commands],
            "xsim_log_sha256": commands[-1]["log_sha256"],
        })
    except Exception as error:
        result["status"] = "FAILED_CLOSED_NATIVE_ROW_STORE_XSIM"
        result["failure"] = f"{type(error).__name__}: {error}"
    finally:
        result["commands"] = commands
        result["xsim_attempt_policy"] = {"xsim_attempts": 1, "ooc_attempts": 0, "route_attempts": 0}
        source_after = inventory(sources)
        dependency_after = inventory(dependencies)
        prior_after = preserved_inventory(part)
        addressed_after = check_addressed_prerequisite()
        previous_after = check_previous_failed_runs()
        expected_index_fix_after = check_recovery_expected_byte_fix()
        counter_latch_fix_after = check_partial_cancel_counter_latch_fix()
        snapshot_after = verify_snapshot(evidence, sources, dependencies)
        result["xsim_integrity"] = {
            "sources_unchanged": source_after == source_before,
            "dependencies_unchanged": dependency_after == dependency_before,
            "prior_reports_unchanged": prior_after == prior_before,
            "addressed_prerequisite_reports_unchanged": addressed_after == addressed_before,
            "previous_failed_rowstore_run_unchanged": previous_after == previous_before,
            "authorized_tb_expected_index_fix_unchanged": expected_index_fix_after == expected_index_fix,
            "authorized_tb_counter_latch_fix_unchanged": counter_latch_fix_after == counter_latch_fix,
            "snapshot_unchanged": snapshot_after["manifest_sha256"] == snapshot["manifest_sha256"],
            "source_sha256_after": source_after,
            "dependency_sha256_after": dependency_after,
            "prior_report_inventories_after": prior_after,
            "addressed_prerequisite_after": addressed_after,
            "previous_failed_rowstore_run_after": previous_after,
            "authorized_tb_expected_index_fix_after": expected_index_fix_after,
            "authorized_tb_counter_latch_fix_after": counter_latch_fix_after,
            "snapshot_after": snapshot_after,
        }
        if not all(result["xsim_integrity"][name] for name in
                   ("sources_unchanged", "dependencies_unchanged", "prior_reports_unchanged",
                    "addressed_prerequisite_reports_unchanged", "previous_failed_rowstore_run_unchanged",
                   "authorized_tb_expected_index_fix_unchanged", "authorized_tb_counter_latch_fix_unchanged",
                   "snapshot_unchanged")):
            result["status"] = "FAILED_CLOSED_NATIVE_ROW_STORE_XSIM_INTEGRITY"
            result["failure"] = result.get("failure", "source/dependency/prior-report/snapshot integrity failed")
        if result.get("status") == PASS_XSIM_STATUS:
            result["scope"] = {"board_access": False, "route": False, "frequency_acceptance": False,
                               "production_integrated": False, "full_pipeline_30fps_accepted": False}
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        result["new_artifact_sha256"] = artifact_hashes(build, evidence, result_path)
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("host", "xsim"), default="host")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.phase == "host":
        run_id = args.run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") +
                                 "_" + uuid.uuid4().hex[:8])
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", run_id):
            parser.error("unsafe run id")
        result = host_phase(run_id)
    else:
        if not args.run_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", args.run_id):
            parser.error("--phase xsim requires a safe --run-id")
        result = xsim_phase(args.run_id)
    print(json.dumps({"status": result.get("status"), "run_id": result.get("run_id"),
                      "evidence_directory": result.get("evidence_directory"),
                      "failure": result.get("failure")}, sort_keys=True))
    return 0 if result.get("status") in {"PASS_HOST_PREFLIGHT_ONLY", PASS_XSIM_STATUS} else 1


if __name__ == "__main__":
    raise SystemExit(main())
