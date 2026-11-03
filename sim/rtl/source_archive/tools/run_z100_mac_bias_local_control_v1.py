"""Run isolated old/new MAC bias miter and strict original V12 golden XSim."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "deployment/hardware/z100_2026/mac_bias_local_control_v1"
CANDIDATE = PKG / "z100_window_mac.sv"
TB = PKG / "tb_z100_mac_bias_local_control_v1.sv"
STATIC_REVIEW = PKG / "static_review.json"
STATIC_MANIFEST = PKG / "manifest.json"
BASE_MAC = ROOT / "build/v12p_d46da432/rtl/z100_window_mac.sv"
BASE_MAC_RELEASE = ROOT / "deployment/hardware/z100_2026/window_mac20_v1/z100_window_mac.sv"
PAIR_RTL = ROOT / "build/v12p_d46da432/rtl/z100_int8_pair_packing.sv"
ACCUM_RTL = ROOT / "build/v12p_d46da432/rtl/z100_accum33_dsp.sv"
CORE_PREP = ROOT / "validation/board_z100/mac_local_control_core_v1/20261026T084049.798285Z/result.json"
CORE_PREP_SHA = "437cf9314192f1bcafc1a6b14ecdabea9629ade55a02662071012d6d9fe4f669"
STAGE1_REVIEW = ROOT / "validation/board_z100/v12_A_default_physopt_primary_review/20261027T142935.035621Z/result.json"
STAGE1_ROUTE = ROOT / "validation/board_z100/v12_A_default_physopt_route/20261027t212850z_default_physopt"
STAGE1_RESULT = STAGE1_ROUTE / "result.json"
STAGE1_DCP = STAGE1_ROUTE / "post_route.dcp"
STAGE1_DCP_SHA = "a0583c88f4f8ff99ad98b39a1c37bd7d17d4774c2ec45fc8fe087d37303521da"
EXPECTED_BASE_MAC = "f573c82fab313161d4097eedafcb7669026dbf6e4c29efa313f0a575fe29e474"
VENDOR = Path("C:/appload/2026.1/Vivado/bin")
XVLOG = VENDOR / "xvlog.bat"
XELAB = VENDOR / "xelab.bat"
XSIM = VENDOR / "xsim.bat"
LOCKED_HELPER = ROOT / "tools/run_z100_registered_response_bank_v2.py"
V12_HELPER = ROOT / "tools/validate_z100_feature_input_capture_v12.py"
OUTPUT_ROOT = ROOT / "validation/board_z100/mac_bias_local_control_v1"
BUILD_ROOT = ROOT / "build/mac_bias_local_control_v1"


class GateError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise GateError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import helper {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPER = load_module("z100_registered_bank_v2_primitives", LOCKED_HELPER)
V12 = load_module("z100_original_v12_golden_helper", V12_HELPER)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def report_json(path: Path, value: dict[str, Any]) -> None:
    HELPER.atomic_json(path, value)


def bound_static_inputs() -> dict[str, str]:
    paths = (CANDIDATE, TB, STATIC_REVIEW, STATIC_MANIFEST, BASE_MAC, BASE_MAC_RELEASE,
             PAIR_RTL, ACCUM_RTL, CORE_PREP, STAGE1_REVIEW, STAGE1_RESULT, STAGE1_DCP,
             LOCKED_HELPER, V12_HELPER, XVLOG, XELAB, XSIM)
    for path in paths:
        require(path.is_file(), f"required input missing: {path}")
    require(sha(BASE_MAC) == EXPECTED_BASE_MAC and sha(BASE_MAC_RELEASE) == EXPECTED_BASE_MAC,
            "frozen MAC baseline SHA changed")
    static = HELPER.load_json(STATIC_REVIEW)
    manifest = HELPER.load_json(STATIC_MANIFEST)
    require(static.get("status") == "PASS_STATIC_SOURCE_AND_FINITE_STATE_MODEL_ONLY" and
            static.get("finite_state_model", {}).get("transitions_checked") == 4096,
            "offline source/FSM audit is not passing")
    require(manifest.get("status") == "CANDIDATE_PREPARED_STATIC_ONLY" and
            manifest.get("baseline", {}).get("sha256") == EXPECTED_BASE_MAC and
            manifest.get("candidate", {}).get("sha256") == sha(CANDIDATE) and
            manifest.get("directed_tb", {}).get("sha256") == sha(TB),
            "static manifest does not bind current candidate")
    for item in (manifest["baseline"], manifest["candidate"], manifest["directed_tb"],
                 manifest["checker"], manifest["report"]):
        bound = HELPER.resolve_binding(item["path"])
        require(bound.is_file() and sha(bound) == item["sha256"],
                f"static manifest hash mismatch: {item['path']}")
    require(sha(CORE_PREP) == CORE_PREP_SHA, "frozen 28-source A preparation changed")
    core = HELPER.load_json(CORE_PREP)
    require(core.get("status") == "PREPARED_LOCAL_CONTROL_CORE_V1_NOT_EXECUTED" and
            len(core.get("source_closure", [])) == 28,
            "expected original 28-source closure is unavailable")
    review = HELPER.load_json(STAGE1_REVIEW)
    require(review.get("status") == "LEGAL_ROUTE_SETUP_TIMING_FAILED" and
            review.get("timing", {}).get("setup_worst_slack_ns") == -0.92 and
            review.get("route", {}).get("fully_routed_nets") == 350720,
            "best completed A route baseline changed")
    stage1 = HELPER.load_json(STAGE1_RESULT)
    require(stage1.get("source_rtl_changed") is False and stage1.get("clock_changed") is False and
            stage1.get("input_dcp_sha256_expected") ==
            "17e7027aa9f72e7c2faeb8d06255dc32f44a8e67bf0f4a6743c7da992f78ad56",
            "A route input identity changed")
    require(sha(STAGE1_DCP) == STAGE1_DCP_SHA, "A routed checkpoint SHA changed")
    return {HELPER.rel(path): sha(path) for path in paths}


def stage_instrumented_tb(source: Path, target: Path) -> tuple[list[dict[str, str]], str]:
    text = source.read_text(encoding="utf-8-sig")
    edits: list[dict[str, str]] = []

    def replace_once(old: str, new: str, label: str) -> None:
        nonlocal text
        count = text.count(old)
        require(count == 1, f"TB instrumentation anchor {label}: count={count}")
        text = text.replace(old, new, 1)
        edits.append({"label": label,
                      "before_sha256": hashlib.sha256(old.encode()).hexdigest(),
                      "after_sha256": hashlib.sha256(new.encode()).hexdigest()})

    replace_once("    integer lane, wait_count, stall_count;",
                 "    integer lane, wait_count, stall_count;\n"
                 "    integer error_checks=0, valid_jobs=0, measured_stall_cycles=0;",
                 "add_runtime_coverage_counters")
    replace_once('                $fatal(1,"Expected matching error %0d old=%b/%0d new=%b/%0d",code,\n'
                 '                    old_error_valid,old_error_code,new_error_valid,new_error_code);\n'
                 "        end",
                 '                $fatal(1,"Expected matching error %0d old=%b/%0d new=%b/%0d",code,\n'
                 '                    old_error_valid,old_error_code,new_error_valid,new_error_code);\n'
                 "            error_checks=error_checks+1;\n"
                 "        end",
                 "count_successful_error_checks")
    replace_once('            $fatal(1,"Valid transaction timed out or metadata mismatch");\n'
                 "        for(lane=0;lane<32;lane=lane+1) begin",
                 '            $fatal(1,"Valid transaction timed out or metadata mismatch");\n'
                 "        valid_jobs=valid_jobs+1;\n"
                 "        for(lane=0;lane<32;lane=lane+1) begin",
                 "count_valid_output_job")
    replace_once('                $fatal(1,"Output changed under backpressure");\n'
                 "        end",
                 '                $fatal(1,"Output changed under backpressure");\n'
                 "            measured_stall_cycles=measured_stall_cycles+1;\n"
                 "        end",
                 "count_valid_stall_cycles")
    replace_once('$display("MAC_BIAS_LOCAL_CONTROL_PASS groups=4 lanes_per_group=8 bias_lanes=32 cfg_errors=3 overflow_bias_nba=1 valid_jobs=1 stall_cycles=3");',
                 '$display("MAC_BIAS_LOCAL_CONTROL_PASS groups=4 lanes_per_group=8 bias_lanes=32 cfg_errors=%0d overflow_bias_nba=1 valid_jobs=%0d stall_cycles=%0d",error_checks,valid_jobs,measured_stall_cycles);',
                 "print_measured_marker_counts")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return edits, text


def stage_miter(build_dir: Path, prep: dict[str, Any],
                bindings: dict[str, str], staged: dict[str, str]):
    rtl = build_dir / "miter" / "rtl"
    rtl.mkdir(parents=True, exist_ok=False)
    old_argv = prep["commands"]["xvlog"]["argv"]
    glbls = [V12.resolve(path) for path in old_argv[2:]
             if Path(str(path)).name.lower() == "glbl.v"]
    require(len(glbls) == 1 and glbls[0].is_file(), "original compile closure must identify one glbl.v")
    glbl = glbls[0]
    for path in (BASE_MAC, CANDIDATE, PAIR_RTL, ACCUM_RTL, TB, glbl):
        bindings[HELPER.rel(path)] = sha(path)

    old_text = BASE_MAC.read_text(encoding="utf-8")
    old_decl = "module z100_window_mac_local_control_v1 #("
    new_decl = "module z100_window_mac_local_control_v1_baseline #("
    require(old_text.count(old_decl) == 1, "baseline module rename anchor is not unique")
    baseline_text = old_text.replace(old_decl, new_decl, 1)
    old_target = rtl / "z100_window_mac_local_control_v1_baseline.sv"
    old_target.write_text(baseline_text, encoding="utf-8", newline="\n")
    staged[HELPER.rel(old_target)] = sha(old_target)
    copied = []
    for source, name in ((glbl, "glbl.v"), (ACCUM_RTL, ACCUM_RTL.name),
                         (PAIR_RTL, PAIR_RTL.name), (CANDIDATE, CANDIDATE.name)):
        target = rtl / name
        shutil.copyfile(source, target)
        require(sha(target) == sha(source), f"miter source copy mismatch: {name}")
        staged[HELPER.rel(target)] = sha(target)
        copied.append(target)
    tb_target = rtl / TB.name
    edits, staged_text = stage_instrumented_tb(TB, tb_target)
    staged[HELPER.rel(tb_target)] = sha(tb_target)
    sources = [copied[0], copied[1], copied[2], old_target, copied[3], tb_target]
    details = {
        "baseline_rename": {"from": old_decl, "to": new_decl, "staged_sha256": sha(old_target)},
        "testbench_instrumentation": {"source_sha256": sha(TB), "staged_sha256": sha(tb_target),
                                     "edits": edits, "DUT_sequence_or_assertions_changed": False},
        "sources": [{"path": HELPER.rel(path), "sha256": sha(path)} for path in sources],
        "top": "tb_z100_mac_bias_local_control_v1",
    }
    return sources, details


def parse_marker(text: str, marker: str) -> dict[str, int]:
    rows = re.findall(r"^" + re.escape(marker) + r"\s+(.+)$", text, re.MULTILINE)
    require(len(rows) == 1, f"expected exactly one {marker} marker, saw {len(rows)}")
    return {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", rows[0])}


def hash_artifacts(run_dir: Path, build_dir: Path, result_path: Path) -> dict[str, str]:
    out = {}
    for folder in (run_dir, build_dir):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path != result_path:
                out[HELPER.rel(path)] = sha(path)
    return out


def run_validation(run_id: str) -> int:
    require(re.fullmatch(r"[A-Za-z0-9_.-]{8,80}", run_id) is not None, "invalid run id")
    run_dir = OUTPUT_ROOT / run_id
    build_dir = BUILD_ROOT / run_id
    require(not run_dir.exists() and not build_dir.exists(), "run/build directory already exists")
    run_dir.mkdir(parents=True, exist_ok=False)
    build_dir.mkdir(parents=True, exist_ok=False)
    result_path = run_dir / "validation_result.json"
    report: dict[str, Any] = {
        "schema": "z100-mac-bias-local-control-validation/1",
        "run_id": run_id, "created_at_utc": now(), "status": "PREPARING",
        "runner_sha256": sha(Path(__file__).resolve()), "board_access": False,
        "synthesis_started": False, "route_started": False,
        "full_pipeline_30fps_accepted": False, "commands": [],
        "checks": [], "source_before": {}, "staged_artifacts": {}, "errors": [],
    }
    report_json(result_path, report)
    mutex = None
    try:
        bindings = bound_static_inputs()
        prep, baseline, core, markers = V12.load_numeric_inputs(bindings)
        require(len(markers) == 7, "accepted original V12 baseline must contain exactly seven markers")
        resources = HELPER.system_resources()
        report["preflight"] = resources
        require(resources["available_ram_gib"] >= 8.0 and resources["c_free_gib"] >= 20.0,
                f"validation resource gate failed: {resources}")
        require(not HELPER.vendor_inventory(), "vendor/simulation process is active")
        V12.require_quiescent()
        mutex = HELPER.NamedMutex(timeout_ms=0)
        mutex.__enter__()
        resources = HELPER.system_resources()
        require(resources["available_ram_gib"] >= 8.0 and resources["c_free_gib"] >= 20.0,
                f"validation resources changed after lock: {resources}")
        require(not HELPER.vendor_inventory(), "vendor process became active after shared lock")
        V12.require_quiescent()
        report["source_before"] = dict(sorted(bindings.items()))
        report["xsim_tools"] = {HELPER.rel(path): sha(path) for path in (XVLOG, XELAB, XSIM)}

        staged: dict[str, str] = {}
        compile_sources, miter_details = stage_miter(build_dir, prep, bindings, staged)
        report["source_before"] = dict(sorted(bindings.items()))
        report["miter_stage"] = miter_details
        report["staged_artifacts"].update(staged)
        miter_out = run_dir / "miter"
        miter_out.mkdir()

        log = HELPER.run_tool("bias_miter_xvlog",
                              [str(XVLOG), "-sv", *map(str, compile_sources)],
                              build_dir / "miter", miter_out / "xvlog.log", result_path, report)
        require("ERROR:" not in log, "bias miter xvlog returned an ERROR")
        snapshot = "z100_mac_bias_local_control_miter_v1"
        HELPER.run_tool("bias_miter_xelab",
                        [str(XELAB), "-mt", "2", "-L", "unimacro_ver", "-L",
                         "unisims_ver", "glbl", miter_details["top"], "-s", snapshot],
                        build_dir / "miter", miter_out / "xelab.log", result_path, report)
        miter_log = HELPER.run_tool("bias_miter_xsim", [str(XSIM), snapshot, "-runall"],
                                    build_dir / "miter", miter_out / "xsim.log", result_path, report)
        measured = parse_marker(miter_log, "MAC_BIAS_LOCAL_CONTROL_PASS")
        expected = {"groups": 4, "lanes_per_group": 8, "bias_lanes": 32, "cfg_errors": 4,
                    "overflow_bias_nba": 1, "valid_jobs": 1, "stall_cycles": 3}
        require(measured == expected, f"dynamic miter coverage mismatch: {measured}")
        report["checks"].append({
            "check": "original_vs_local_bias_control_full_mac_xsim_miter", "status": "PASS",
            "measured_counts": measured, "four_local_state_mirrors_checked_each_tick": True,
            "all_32_bias_words_compared_to_lane_oracle": True,
            "valid_output_and_stall_stability_compared": True,
        })

        report["status"] = "STAGING_STRICT_ORIGINAL_V12_GOLDEN"
        report_json(result_path, report)
        numeric_out = run_dir / "numeric"
        numeric_build = build_dir / "numeric"
        numeric_out.mkdir()
        numeric_build.mkdir()
        artifacts: dict[str, str] = {}
        compile_files, top, rewrites = V12.prepare_numeric(
            numeric_build, numeric_out, bindings, artifacts, prep, core)
        report["source_before"] = dict(sorted(bindings.items()))
        mac_targets = [path for path in compile_files if path.name == "z100_window_mac.sv"]
        require(len(mac_targets) == 1, "V12 compile closure must contain exactly one MAC source")
        mac_target = mac_targets[0]
        require(sha(mac_target) == EXPECTED_BASE_MAC, "V12 staged MAC is not original baseline")
        shutil.copyfile(CANDIDATE, mac_target)
        require(sha(mac_target) == sha(CANDIDATE), "candidate MAC override did not stage exactly")
        artifacts[HELPER.rel(mac_target)] = sha(mac_target)

        numeric_pairs = []
        for row in core["source_closure"]:
            source = row["source"]
            basename = Path(source).name
            if source == V12.ADAPTER_SOURCE:
                staged_name, digest = V12.ADAPTER_V12.name, sha(V12.ADAPTER_V12)
            elif source == V12.TOP_SOURCE:
                staged_name, digest = V12.TOP_V12.name, sha(V12.TOP_V12)
            elif basename == "z100_window_mac.sv":
                staged_name, digest = "z100_window_mac.sv", sha(CANDIDATE)
            else:
                staged_name, digest = basename, row["sha256"]
            staged_file = numeric_build / "rtl" / staged_name
            require(staged_file.is_file() and sha(staged_file) == digest,
                    f"V12 staged source hash mismatch: {source} -> {staged_name}")
            numeric_pairs.append({"source": source, "staged": staged_name, "sha256": digest,
                                  "candidate_mac_override": basename == "z100_window_mac.sv"})
        require(len(numeric_pairs) == 28 and sum(x["candidate_mac_override"] for x in numeric_pairs) == 1,
                "V12 full-core golden is not 28 sources with one MAC override")
        report["numeric_goldens"] = {
            "baseline_report": V12.project_name(V12.BASE_NUMERIC),
            "baseline_sha256": sha(V12.BASE_NUMERIC), "baseline_status": baseline["status"],
            "expected_markers": markers, "required_exact_marker_count": 7,
            "compile_file_count": len(compile_files), "rtl_closure_count": 28,
            "source_pairs": numeric_pairs, "candidate_override": HELPER.rel(CANDIDATE),
            "established_testbench_rewrites": rewrites,
        }
        report["staged_artifacts"].update(artifacts)
        report_json(result_path, report)
        log = HELPER.run_tool("strict_v12_numeric_xvlog", [str(XVLOG), "-sv", *map(str, compile_files)],
                              numeric_build, numeric_out / "xvlog.log", result_path, report)
        require("ERROR:" not in log, "original V12 compile emitted an ERROR")
        snapshot = "z100_mac_bias_local_control_original_v12_golden_v1"
        HELPER.run_tool("strict_v12_numeric_xelab",
                        [str(XELAB), "-mt", "2", "-L", "unimacro_ver", "-L",
                         "unisims_ver", "glbl", top, "-s", snapshot],
                        numeric_build, numeric_out / "xelab.log", result_path, report)
        numeric_log = HELPER.run_tool("strict_v12_numeric_xsim", [str(XSIM), snapshot, "-runall"],
                                      numeric_build, numeric_out / "xsim.log", result_path, report)
        for marker in markers:
            require(numeric_log.splitlines().count(marker) == 1,
                    "strict original V12 marker mismatch: " + marker.split(" ", 1)[0])
        require(len(markers) == 7, "original golden does not have seven markers")
        report["checks"].append({"check": "original_v12_strict_numeric_golden", "status": "PASS",
                                 "exact_marker_count": 7, "changed_markers": 0,
                                 "count_whitelist": False})
        report["source_after"] = {name: sha(HELPER.resolve_binding(name)) for name in bindings}
        require(report["source_after"] == report["source_before"], "bound source changed during XSim")
        report["artifact_sha256"] = hash_artifacts(run_dir, build_dir, result_path)
        report["status"] = "PASS_BIAS_LOCAL_MAC_MITER_AND_STRICT_V12_GOLDEN_XSIM_ONLY"
        report["scope"] = "Directed MAC miter and strict original V12 seven-marker numerical regression; no synthesis/route/board/FPS acceptance."
        report_json(result_path, report)
        return 0
    except Exception as exc:
        report["status"] = "FAILED_CLOSED"
        report.setdefault("errors", []).append(f"{type(exc).__name__}: {exc}")
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        report["source_after"] = {name: sha(HELPER.resolve_binding(name))
                                  for name in report.get("source_before", {})
                                  if HELPER.resolve_binding(name).is_file()}
        report["artifact_sha256"] = hash_artifacts(run_dir, build_dir, result_path)
        report_json(result_path, report)
        return 1
    finally:
        if mutex is not None:
            mutex.__exit__(None, None, None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    return run_validation(args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
