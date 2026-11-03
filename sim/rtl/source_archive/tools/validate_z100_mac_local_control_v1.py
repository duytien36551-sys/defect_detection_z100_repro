"""Run the local-control candidate against the frozen window MAC.

This validator uses the pinned local Icarus runtime and installed Vivado
DSP48E1/MULT_MACRO simulation sources. It does not run XSim, synthesis, route,
or board hardware.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
OWN = HW / "mac_local_control_v1"
CANDIDATE = OWN / "z100_window_mac_local_control_v1.sv"
TESTBENCH = OWN / "tb_z100_mac_local_control_v1.sv"
BASE_MAC = HW / "window_mac20_v1/z100_window_mac.sv"
PAIR = HW / "int8_pair_packing_v3/z100_int8_pair_packing.sv"
ACCUM = HW / "accum33_dsp_v2/z100_accum33_dsp.sv"
V10_SOURCE_PROOF = ROOT / "validation/board_z100/feature_address_shared_v10_compute/20261025T190545.372805Z/result.json"
ROUTE_RESULT = ROOT / "validation/board_z100/feature_address_shared_v10_route_recovery/20261026T051001.615861Z/result.json"
CRITICAL_PATHS = ROOT / "validation/board_z100/feature_address_shared_v10_route_recovery/20261026T051001.615861Z/critical_paths.rpt"
LOCAL_ROOT = ROOT / "deployment/build/local_tools/iverilog13_msys2"
VENDOR = Path("C:/appload/2026.1/Vivado/data/verilog/src")
DSP48E1 = VENDOR / "unisims/DSP48E1.v"
MULT_MACRO = VENDOR / "unimacro/MULT_MACRO.v"
GLBL = VENDOR / "glbl.v"
EXPECTED_BASE_SHA = "1e37a36f339e935c0a8cb45a75ba8c17a1d806708f240c6f070739ffe2fb1c8f"
EXPECTED_PAIR_SHA = "ee927bfd9e937855fd75f17b82b078f23532d5159d395aebc3b71063160067ad"
EXPECTED_ACCUM_SHA = "0b046f32b223a2c9055e27773def8e66a0e5755fd66fa9611dde6a6575e60d51"
EXPECTED_COVERAGE = {
    "accepted_runs": 13,
    "accepted_inputs": 10,
    "output_transfers": 1,
    "stalls": 10,
    "error4": 4,
    "error5": 2,
    "saturation_lane_checks": 8,
    "lane_tail_checks": 1,
    "public_cycles": 100,
}
ERROR_RE = re.compile(r"(?:\berror:|syntax error|unknown module|unable to bind|port .* expects)", re.I)
PASS_RE = re.compile(r"^MAC_LOCAL_CONTROL_MITER_PASS (.+)$", re.M)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_key(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return "external/" + resolved.as_posix().replace(":", "")


def frozen_candidate(base_text: str) -> str:
    require(base_text.count("module z100_window_mac #(") == 1, "Unique frozen MAC module declaration")
    candidate = base_text.replace("module z100_window_mac #(",
                                  "module z100_window_mac_local_control_v1 #(", 1)
    needle = "    wire input_good=input_fire && act_token==token && act_last==expected_last;\n"
    require(candidate.count(needle) == 1, "Exact input-abort seam")
    candidate = candidate.replace(needle, needle + "    wire input_abort=input_fire && !input_good;\n", 1)
    needle = "    wire weight_write=cfg_weight_valid && cfg_weight_ready && written_groups<expected_groups;\n"
    require(candidate.count(needle) == 1, "Exact local-control insertion seam")
    local_control = '''    // Each site/8-lane cluster retains its own p3-valid copy. The active mask
    // is captured on the exact accepted run edge that loads accumulator bias.
    // These controls replace the high-fanout state/site/lane decode on DSP CEP;
    // the data and valid pipeline remain at the original cycle boundaries.
    wire [SITES*32-1:0] local_accumulator_enable;
    genvar control_site, control_group, control_lane;
    generate for(control_site=0;control_site<SITES;control_site=control_site+1) begin : gen_feedback_local_site
        for(control_group=0;control_group<4;control_group=control_group+1) begin : gen_feedback_local_group
            (* dont_touch="true", keep="true" *) reg local_p3_valid;
            always @(posedge clk) begin
                if(!rst_n || cancel || input_abort) local_p3_valid<=1'b0;
                else local_p3_valid<=p2_valid;
            end
            for(control_lane=0;control_lane<8;control_lane=control_lane+1) begin : gen_feedback_local_lane
                (* dont_touch="true", keep="true" *) reg local_active;
                always @(posedge clk) begin
                    if(!rst_n || cancel || input_abort || (out_valid && out_ready && out_last))
                        local_active<=1'b0;
                    else if(accumulator_load_bias)
                        local_active<=(control_site<run_sites) &&
                                      ((control_group*8+control_lane)<run_lanes);
                end
                assign local_accumulator_enable[control_site*32+control_group*8+control_lane]=
                    local_p3_valid && local_active;
            end
        end
    end endgenerate
'''
    candidate = candidate.replace(needle, needle + local_control, 1)
    old_enable = '''                .enable(p3_valid && (state==INPUTS || state==FLUSH) &&
                        accum_site<sites && accum_lane<lanes),
'''
    require(candidate.count(old_enable) == 1, "Exact original DSP enable seam")
    candidate = candidate.replace(old_enable,
        "                .enable(local_accumulator_enable[accum_site*32+accum_lane]),\n", 1)
    return candidate


def verify_source_proofs() -> dict[str, Any]:
    require(V10_SOURCE_PROOF.is_file() and ROUTE_RESULT.is_file() and CRITICAL_PATHS.is_file(),
            "Required frozen V10 source/timing evidence missing")
    source_proof = json.loads(V10_SOURCE_PROOF.read_text(encoding="utf-8"))
    require(source_proof.get("status") ==
            "PASS_PRIVATE_ADDRESS_SHARED_V10_SHARED_AXI_FULL20SITE_ORIGINAL_POOL_MITER_CONV_RETAINED_DDR_GOLDEN_XSIM_ONLY",
            "Unexpected frozen V10 source proof status")
    require(source_proof.get("source_sha256_before") == source_proof.get("source_sha256_after"),
            "V10 source proof hashes were unstable")
    source_index = {name.replace("\\", "/"): value
                    for name, value in source_proof.get("source_sha256_after", {}).items()}
    for path, expected in ((BASE_MAC, EXPECTED_BASE_SHA), (PAIR, EXPECTED_PAIR_SHA), (ACCUM, EXPECTED_ACCUM_SHA)):
        key = source_key(path)
        require(source_index.get(key) == expected, "Frozen V10 proof does not bind " + key)
        require(sha256(path) == expected, "Frozen arithmetic source hash changed: " + key)

    route = json.loads(ROUTE_RESULT.read_text(encoding="utf-8"))
    require(route.get("status") == "PRIVATE_V10_LEGALLY_ROUTED_TIMING_NOT_MET" and
            route.get("routable_nets") == 347377 and route.get("fully_routed_nets") == 347377 and
            route.get("routing_error_nets") == 0 and route.get("setup_failing_endpoints") == 85633 and
            route.get("setup_worst_slack_ns") == -4.135 and route.get("hold_worst_slack_ns") == 0.067,
            "Critical-path report does not describe the frozen routed V10 failure")
    artifact_index = {name.replace("\\", "/"): value for name, value in route.get("artifact_sha256", {}).items()}
    require(artifact_index.get(source_key(CRITICAL_PATHS)) == sha256(CRITICAL_PATHS),
            "Routed critical-path report hash mismatch")
    critical = CRITICAL_PATHS.read_text(encoding="utf-8", errors="replace")
    require("native_mac/p3_valid_reg" in critical and
            "feedback_accumulator/feedback_adder/CEP" in critical and
            "Data Path Delay:        13.713ns" in critical and "route 13.318ns (97.119%)" in critical,
            "Routed critical-path evidence differs from the target enable path")
    return {
        "v10_source_proof": {"path": source_key(V10_SOURCE_PROOF), "sha256": sha256(V10_SOURCE_PROOF),
                             "status": source_proof["status"]},
        "route_result": {"path": source_key(ROUTE_RESULT), "sha256": sha256(ROUTE_RESULT),
                         "status": route["status"], "worst_setup_slack_ns": route["setup_worst_slack_ns"],
                         "setup_failing_endpoints": route["setup_failing_endpoints"]},
        "critical_path_report": {"path": source_key(CRITICAL_PATHS), "sha256": sha256(CRITICAL_PATHS),
                                 "target": "p3_valid to feedback accumulator DSP48E1 CEP",
                                 "delay_ns": 13.713, "route_fraction_percent": 97.119},
    }


def local_runtime() -> tuple[Path, Path, Path, dict[str, str], list[Path], dict[str, Any]]:
    manifest_path = LOCAL_ROOT / "manifest.json"
    require(manifest_path.is_file(), "Pinned local Icarus manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "project-local-iverilog/1", "Unexpected local Icarus manifest")
    require(manifest.get("versions", {}).get("iverilog", "").startswith("Icarus Verilog version 13.0"),
            "Pinned Icarus 13.0 is unavailable")
    files = manifest.get("files", {})
    require(isinstance(files, dict) and len(files) > 0, "Icarus manifest file list is empty")
    paths = [manifest_path]
    hashes = {source_key(manifest_path): sha256(manifest_path)}
    for relative, expected in files.items():
        path = LOCAL_ROOT / Path(relative.replace("\\", "/"))
        require(path.is_file() and sha256(path) == expected, "Pinned Icarus runtime hash mismatch: " + relative)
        paths.append(path)
        hashes[source_key(path)] = expected
    binary = LOCAL_ROOT / "ucrt64/bin"
    backend = LOCAL_ROOT / "ucrt64/lib/ivl"
    compiler, runner = binary / "iverilog.exe", binary / "vvp.exe"
    require(compiler.is_file() and runner.is_file() and backend.is_dir() and
            all(path.is_file() for path in (DSP48E1, MULT_MACRO, GLBL)),
            "Actual local Icarus and installed vendor models are required")
    for path in (compiler, runner, DSP48E1, MULT_MACRO, GLBL):
        paths.append(path)
        hashes[source_key(path)] = sha256(path)
    return compiler, runner, backend, hashes, paths, manifest


def execute(label: str, argv: list[str], cwd: Path, out: Path,
            env: dict[str, str], commands: list[dict[str, Any]], timeout: int) -> str:
    start = time.monotonic()
    try:
        completed = subprocess.run(argv, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                                   capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        log_path = out / f"{label}.log"
        log_path.write_text(stdout + ("\n" if stdout and stderr else "") + stderr +
                            f"\nTIMEOUT after {timeout}s; no retry in this invocation.\n", encoding="utf-8")
        commands.append({"name": label, "argv": argv, "cwd": str(cwd), "return_code": None,
                         "timeout_seconds": timeout, "elapsed_seconds": round(time.monotonic()-start, 3),
                         "log": source_key(log_path)})
        raise ValueError(f"{label} timed out after {timeout}s") from exc
    log = completed.stdout + ("\n" if completed.stdout and completed.stderr else "") + completed.stderr
    log_path = out / f"{label}.log"
    log_path.write_text(log, encoding="utf-8")
    commands.append({"name": label, "argv": argv, "cwd": str(cwd), "return_code": completed.returncode,
                     "elapsed_seconds": round(time.monotonic()-start, 3), "log": source_key(log_path),
                     "log_sha256": sha256(log_path)})
    require(completed.returncode == 0, f"{label} returned {completed.returncode}; inspect {log_path}")
    require(ERROR_RE.search(log) is None, f"{label} reported an elaboration/runtime error; inspect {log_path}")
    return log


def parse_marker(log: str, sites: int) -> dict[str, int]:
    matches = PASS_RE.findall(log)
    require(len(matches) == 1, f"SITES={sites} exactly one public-cycle miter pass marker")
    values = {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", matches[0])}
    require(values.get("sites") == sites, f"SITES={sites} marker identity")
    for key, minimum in EXPECTED_COVERAGE.items():
        if key == "site_tail_checks" and sites == 1:
            continue
        require(values.get(key, -1) >= minimum,
                f"SITES={sites} miter coverage {key}={values.get(key)} < {minimum}")
    return values


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out_root = ROOT / "validation/board_z100/mac_local_control_v1"
    build_root = ROOT / "deployment/build/mac_local_control_v1"
    out_root.mkdir(parents=True, exist_ok=True)
    build_root.mkdir(parents=True, exist_ok=True)
    out = out_root / stamp
    build = build_root / stamp
    out.mkdir(exist_ok=False)
    build.mkdir(exist_ok=False)
    report_path = out / "result.json"
    report: dict[str, Any] = {
        "schema": "z100-mac-local-control-miter/1",
        "status": "RUNNING_LOCAL_VENDOR_SOURCE_MITER",
        "commands": [],
        "board_access": False,
        "xsim_run": False,
        "vendor_flow_run": False,
        "vivado_synthesis_run": False,
        "full_core_synthesis_or_route_run": False,
        "hardware_access": False,
        "baseline_mapped_dsp_count": 2016,
    }
    before: dict[str, str] = {}
    sources: list[Path] = []
    try:
        proof_context = verify_source_proofs()
        base_text = BASE_MAC.read_text(encoding="utf-8")
        candidate_text = CANDIDATE.read_text(encoding="utf-8")
        require(sha256(BASE_MAC) == EXPECTED_BASE_SHA, "Frozen original MAC source hash changed")
        require(candidate_text == frozen_candidate(base_text),
                "Candidate is not the bounded local-control transformation of the frozen MAC")
        require(sha256(PAIR) == EXPECTED_PAIR_SHA and sha256(ACCUM) == EXPECTED_ACCUM_SHA,
                "Frozen arithmetic primitive wrappers changed")

        compiler, runner, backend, runtime_hashes, runtime_paths, manifest = local_runtime()
        sources = [Path(__file__), BASE_MAC, CANDIDATE, TESTBENCH, PAIR, ACCUM,
                   V10_SOURCE_PROOF, ROUTE_RESULT, CRITICAL_PATHS, *runtime_paths]
        require(all(path.is_file() for path in sources), "Source or testbench file missing")
        before = dict(sorted((source_key(path), sha256(path)) for path in sources))
        report.update(
            source_sha256_before=before,
            source_proof_context=proof_context,
            source_closure={
                "original_window_mac": {"path": source_key(BASE_MAC), "sha256": sha256(BASE_MAC)},
                "candidate_window_mac": {"path": source_key(CANDIDATE), "sha256": sha256(CANDIDATE)},
                "actual_accumulator": {"path": source_key(ACCUM), "sha256": sha256(ACCUM)},
                "actual_pair_multiplier": {"path": source_key(PAIR), "sha256": sha256(PAIR)},
                "vendor_models": {source_key(path): sha256(path) for path in (DSP48E1, MULT_MACRO, GLBL)},
                "runtime_manifest": {"path": source_key(LOCAL_ROOT / "manifest.json"),
                                     "sha256": sha256(LOCAL_ROOT / "manifest.json"),
                                     "versions": manifest.get("versions")},
            },
            design_change={
                "public_interface_changed": False,
                "arithmetic_or_pipeline_changed": False,
                "state_site_lane_decode_removed_from_accumulator_enable": True,
                "local_p3_valid_replicas_default_sites20": 20*4,
                "local_active_lane_mask_bits_default_sites20": 20*32,
                "added_rtl_control_registers_default_sites20": 20*4+20*32,
                "mapped_resource_claim": False,
                "dsp_count_claim": "No new DSP operators are present in this source change; mapped count remains unmeasured.",
            },
            coverage_plan=[
                "SITES=1 and SITES=2 actual public-cycle miter against the frozen window_mac20_v1 module.",
                "Both instances use the actual installed DSP48E1 and MULT_MACRO vendor simulation sources.",
                "Valid/invalid runs, site/lane tails, consecutive groups, positive and negative accumulator saturation.",
                "Malformed token/last abort, cancellation in input and output, reset in-flight, output stalls and drain.",
            ],
            scope=(
                "Local small-SITES vendor-source simulation only. It establishes cycle-by-cycle equivalence for the "
                "covered vectors, not mapped replica placement, a 2016-DSP resource result, timing improvement, "
                "full-core synthesis, routed timing, full pipeline performance, or board behavior."
            ),
        )
        report_path.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")

        env = dict(os.environ)
        binary_dir = LOCAL_ROOT / "ucrt64/bin"
        env["PATH"] = str(binary_dir) + os.pathsep + env.get("PATH", "")
        env["OMP_NUM_THREADS"] = "1"
        compile_warnings: dict[int, list[str]] = {}
        runs: dict[int, dict[str, int]] = {}
        for sites in (1,2):
            executable = build / f"mac_local_control_sites{sites}.vvp"
            compile_argv = [str(compiler), "-B", str(backend), "-g2012", "-Wall",
                            f"-Ptb_z100_mac_local_control_v1.SITES={sites}",
                            "-s", "tb_z100_mac_local_control_v1", "-s", "glbl",
                            "-o", str(executable), str(DSP48E1), str(MULT_MACRO), str(GLBL),
                            str(ACCUM), str(PAIR), str(BASE_MAC), str(CANDIDATE), str(TESTBENCH)]
            compile_log = execute(f"sites{sites}_iverilog", compile_argv, build, out, env,
                                  report["commands"], 120)
            compile_warnings[sites] = [line for line in compile_log.splitlines()
                                       if re.search(r"\bwarning:", line, re.I)]
            require(executable.is_file(), f"SITES={sites} Icarus output missing")
            run_argv = [str(runner), "-M", str(backend), str(executable)]
            run_log = execute(f"sites{sites}_vvp", run_argv, build, out, env,
                              report["commands"], 90)
            runs[sites] = parse_marker(run_log, sites)
            require(len(re.findall(r"\$finish called at", run_log)) == 1,
                    f"SITES={sites} miter did not reach one normal finish")

        after = dict(sorted((source_key(path), sha256(path)) for path in sources))
        require(before == after, "Source, primitive model, or runtime changed during validation")
        report.update(
            status="PASS_LOCAL_VENDOR_SOURCE_CYCLE_EQUIVALENCE_SIMULATION_ONLY",
            source_sha256_after=after,
            simulation={"sites": runs, "compile_warnings": compile_warnings},
            numerical_equivalence="PASS for public outputs every compared cycle for the covered SITES=1/2 scenarios",
            mapped_resources="NOT_MEASURED",
            routed_timing="NOT_MEASURED",
            synthesis_or_route="NOT_RUN",
        )
    except Exception as exc:
        report.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")
        if before:
            report["source_sha256_before"] = before
            report["source_sha256_after"] = dict(sorted((source_key(path), sha256(path)) for path in sources))
    finally:
        report["artifact_sha256"] = {
            source_key(path): sha256(path)
            for folder in (out, build)
            for path in folder.rglob("*")
            if path.is_file() and path != report_path
        }
        report_path.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")

    print(json.dumps({"status": report["status"], "report": source_key(report_path),
                      "error": report.get("error")}, indent=2))
    return 0 if str(report["status"]).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
