"""Run the strengthened v3 local-control MAC miter on pinned Icarus/vendor models.

This is a small-SITES local simulation only. It does not run XSim, synthesis,
route, or board hardware.
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
TB = HW / "mac_local_control_v3_validation/tb_z100_mac_local_control_v3.sv"
BASE_MAC = HW / "window_mac20_v1/z100_window_mac.sv"
CANDIDATE = HW / "mac_local_control_v1/z100_window_mac_local_control_v1.sv"
PAIR = HW / "int8_pair_packing_v3/z100_int8_pair_packing.sv"
ACCUM = HW / "accum33_dsp_v2/z100_accum33_dsp.sv"
V10_PROOF = ROOT / "validation/board_z100/feature_address_shared_v10_compute/20261025T190545.372805Z/result.json"
ROUTE_REPORT = ROOT / "validation/board_z100/feature_address_shared_v10_route_recovery/20261026T051001.615861Z/result.json"
CRITICAL_PATHS = ROOT / "validation/board_z100/feature_address_shared_v10_route_recovery/20261026T051001.615861Z/critical_paths.rpt"
V1_REPORT = ROOT / "validation/board_z100/mac_local_control_v1/20261026T075337.569782Z/result.json"
LOCAL_ROOT = ROOT / "deployment/build/local_tools/iverilog13_msys2"
VENDOR = Path("C:/appload/2026.1/Vivado/data/verilog/src")
DSP48E1 = VENDOR / "unisims/DSP48E1.v"
MULT_MACRO = VENDOR / "unimacro/MULT_MACRO.v"
GLBL = VENDOR / "glbl.v"

EXPECTED_BASE_SHA = "1e37a36f339e935c0a8cb45a75ba8c17a1d806708f240c6f070739ffe2fb1c8f"
EXPECTED_PAIR_SHA = "ee927bfd9e937855fd75f17b82b078f23532d5159d395aebc3b71063160067ad"
EXPECTED_ACCUM_SHA = "0b046f32b223a2c9055e27773def8e66a0e5755fd66fa9611dde6a6575e60d51"
EXPECTED_CANDIDATE_SHA = "f573c82fab313161d4097eedafcb7669026dbf6e4c29efa313f0a575fe29e474"
EXPECTED_COVERAGE = {
    "accepted_runs": 24,
    "accepted_inputs": 28,
    "output_transfers": 2,
    "stalls": 12,
    "error4": 4,
    "error5": 5,
    "saturation_lane_checks": 8,
    "lane_tail_checks": 1,
    "public_cycles": 200,
    "p3_replica_checks": 100,
    "effective_enable_checks": 1000,
    "active_mask_checks": 1000,
    "initialized_checks": 1000,
    "delta_checks": 1000,
    "accumulator_checks": 100,
    "load_bias_checks": 1000,
    "malformed_p3_abort_checks": 1,
    "continuous_pairs": 3,
    "bubbled_gaps": 2,
    "max_lane_runs": 1,
}
ERROR_RE = re.compile(r"(?:\berror:|syntax error|unknown module|unable to bind|port .* expects)", re.I)
PASS_RE = re.compile(r"^MAC_LOCAL_CONTROL_V3_MITER_PASS (.+)$", re.M)


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


def verify_inputs() -> dict[str, Any]:
    require(all(path.is_file() for path in
                (BASE_MAC, CANDIDATE, TB, PAIR, ACCUM, V10_PROOF, ROUTE_REPORT,
                 CRITICAL_PATHS, V1_REPORT)), "A frozen source/proof or v3 bench is missing")
    require(sha256(BASE_MAC) == EXPECTED_BASE_SHA, "Frozen V10 MAC hash changed")
    require(sha256(PAIR) == EXPECTED_PAIR_SHA, "Frozen pair arithmetic hash changed")
    require(sha256(ACCUM) == EXPECTED_ACCUM_SHA, "Frozen DSP accumulator hash changed")
    require(sha256(CANDIDATE) == EXPECTED_CANDIDATE_SHA,
            "Frozen v1 local-control candidate hash changed")

    old_report = json.loads(V1_REPORT.read_text(encoding="utf-8"))
    old_hashes = old_report.get("source_sha256_after", {})
    old_hashes = {name.replace("\\", "/"): digest for name, digest in old_hashes.items()}
    require(old_report.get("status") == "FAILED_CLOSED" and
            old_hashes.get(source_key(CANDIDATE)) == EXPECTED_CANDIDATE_SHA,
            "The immutable v1 candidate provenance report changed")

    proof = json.loads(V10_PROOF.read_text(encoding="utf-8"))
    require(proof.get("status") ==
            "PASS_PRIVATE_ADDRESS_SHARED_V10_SHARED_AXI_FULL20SITE_ORIGINAL_POOL_MITER_CONV_RETAINED_DDR_GOLDEN_XSIM_ONLY",
            "Unexpected frozen V10 compute proof status")
    proof_hashes = proof.get("source_sha256_after", {})
    proof_hashes = {name.replace("\\", "/"): digest for name, digest in proof_hashes.items()}
    require(proof_hashes.get(source_key(BASE_MAC)) == EXPECTED_BASE_SHA and
            proof_hashes.get(source_key(PAIR)) == EXPECTED_PAIR_SHA and
            proof_hashes.get(source_key(ACCUM)) == EXPECTED_ACCUM_SHA,
            "The V10 proof does not bind the frozen arithmetic sources")

    route = json.loads(ROUTE_REPORT.read_text(encoding="utf-8"))
    require(route.get("status") == "PRIVATE_V10_LEGALLY_ROUTED_TIMING_NOT_MET" and
            route.get("routable_nets") == 347377 and route.get("fully_routed_nets") == 347377 and
            route.get("routing_error_nets") == 0 and route.get("setup_failing_endpoints") == 85633 and
            route.get("setup_worst_slack_ns") == -4.135 and route.get("hold_worst_slack_ns") == 0.067,
            "Frozen route result does not match the measured target path context")
    route_hashes = {name.replace("\\", "/"): digest
                    for name, digest in route.get("artifact_sha256", {}).items()}
    require(route_hashes.get(source_key(CRITICAL_PATHS)) == sha256(CRITICAL_PATHS),
            "The route result does not bind the critical-path report")
    critical = CRITICAL_PATHS.read_text(encoding="utf-8", errors="replace")
    require("native_mac/p3_valid_reg" in critical and
            "feedback_accumulator/feedback_adder/CEP" in critical and
            "Data Path Delay:        13.713ns" in critical and "route 13.318ns (97.119%)" in critical,
            "Critical-path report no longer describes the feedback enable path")
    return {
        "frozen_candidate_v1": {"path": source_key(CANDIDATE), "sha256": sha256(CANDIDATE),
                                 "status": old_report["status"]},
        "v10_compute_proof": {"path": source_key(V10_PROOF), "sha256": sha256(V10_PROOF),
                              "status": proof["status"]},
        "routed_path_context": {"path": source_key(ROUTE_REPORT), "sha256": sha256(ROUTE_REPORT),
                                "worst_setup_slack_ns": route["setup_worst_slack_ns"],
                                "critical_path_sha256": sha256(CRITICAL_PATHS)},
    }


def local_runtime() -> tuple[Path, Path, Path, list[Path], dict[str, Any]]:
    manifest_path = LOCAL_ROOT / "manifest.json"
    require(manifest_path.is_file(), "Pinned local Icarus manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "project-local-iverilog/1" and
            manifest.get("versions", {}).get("iverilog", "").startswith("Icarus Verilog version 13.0"),
            "Pinned Icarus 13.0 runtime identity mismatch")
    files = manifest.get("files", {})
    require(isinstance(files, dict) and files, "Icarus runtime manifest has no files")
    paths = [manifest_path]
    for relative, expected in files.items():
        path = LOCAL_ROOT / Path(relative.replace("\\", "/"))
        require(path.is_file() and sha256(path) == expected, "Icarus runtime hash mismatch: " + relative)
        paths.append(path)
    binary = LOCAL_ROOT / "ucrt64/bin"
    backend = LOCAL_ROOT / "ucrt64/lib/ivl"
    compiler, runner = binary / "iverilog.exe", binary / "vvp.exe"
    require(compiler.is_file() and runner.is_file() and backend.is_dir() and
            all(path.is_file() for path in (DSP48E1, MULT_MACRO, GLBL)),
            "Actual local Icarus and Vivado vendor simulation models are required")
    paths.extend((compiler, runner, DSP48E1, MULT_MACRO, GLBL))
    return compiler, runner, backend, paths, manifest


def run_command(label: str, argv: list[str], cwd: Path, out: Path, env: dict[str, str],
                commands: list[dict[str, Any]], timeout_seconds: int) -> str:
    start = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, text=True, encoding="utf-8",
                                errors="replace", capture_output=True, timeout=timeout_seconds,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        log_path = out / f"{label}.log"
        log_path.write_text(stdout + ("\n" if stdout and stderr else "") + stderr +
                             f"\nTIMEOUT after {timeout_seconds}s; no retry in this invocation.\n",
                             encoding="utf-8")
        commands.append({"name": label, "argv": argv, "cwd": str(cwd), "return_code": None,
                         "timeout_seconds": timeout_seconds, "log": source_key(log_path)})
        raise ValueError(f"{label} timed out; inspect {log_path}") from exc
    log = result.stdout + ("\n" if result.stdout and result.stderr else "") + result.stderr
    log_path = out / f"{label}.log"
    log_path.write_text(log, encoding="utf-8")
    commands.append({"name": label, "argv": argv, "cwd": str(cwd),
                     "return_code": result.returncode,
                     "elapsed_seconds": round(time.monotonic() - start, 3),
                     "log": source_key(log_path), "log_sha256": sha256(log_path)})
    require(result.returncode == 0, f"{label} returned {result.returncode}; inspect {log_path}")
    require(ERROR_RE.search(log) is None, f"{label} reported an error; inspect {log_path}")
    return log


def parse_marker(log: str, sites: int) -> dict[str, int]:
    matches = PASS_RE.findall(log)
    require(len(matches) == 1, f"SITES={sites} must emit exactly one v3 pass marker")
    values = {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", matches[0])}
    require(values.get("sites") == sites, f"SITES={sites} marker identity mismatch")
    for key, minimum in EXPECTED_COVERAGE.items():
        require(values.get(key, -1) >= minimum,
                f"SITES={sites} coverage {key}={values.get(key)} < {minimum}")
    require(values.get("site_tail_checks", -1) > 0 or sites == 1,
            f"SITES={sites} site-tail coverage missing")
    require(values.get("max_lane_output_sites", -1) >= sites,
            f"SITES={sites} maximum-lane outputs incomplete")
    require(values.get("cancel_stage_mask") == 15,
            f"SITES={sites} cancel-stage mask is not P0-P3")
    require(values.get("reset_stage_mask") == 10,
            f"SITES={sites} reset-stage mask is not P1/P3")
    return values


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out_root = ROOT / "validation/board_z100/mac_local_control_v3_validation"
    build_root = ROOT / "deployment/build/mac_local_control_v3_validation"
    out_root.mkdir(parents=True, exist_ok=True)
    build_root.mkdir(parents=True, exist_ok=True)
    out = out_root / stamp
    build = build_root / stamp
    out.mkdir(exist_ok=False)
    build.mkdir(exist_ok=False)
    report_path = out / "result.json"
    report: dict[str, Any] = {
        "schema": "z100-mac-local-control-v3-validation/1",
        "status": "RUNNING_LOCAL_VENDOR_SOURCE_CYCLE_MITER",
        "commands": [],
        "board_access": False,
        "xsim_run": False,
        "vivado_synthesis_run": False,
        "full_core_synthesis_or_route_run": False,
        "hardware_access": False,
    }
    sources: list[Path] = []
    before: dict[str, str] = {}
    try:
        proof_context = verify_inputs()
        compiler, runner, backend, runtime_paths, manifest = local_runtime()
        sources = [Path(__file__), TB, BASE_MAC, CANDIDATE, PAIR, ACCUM,
                   V10_PROOF, ROUTE_REPORT, CRITICAL_PATHS, V1_REPORT, *runtime_paths]
        require(all(path.is_file() for path in sources), "A source-bound input is missing")
        before = dict(sorted((source_key(path), sha256(path)) for path in sources))
        report.update(
            source_sha256_before=before,
            source_proof_context=proof_context,
            source_closure={
                "reference_mac": {"path": source_key(BASE_MAC), "sha256": sha256(BASE_MAC)},
                "candidate_mac_v1": {"path": source_key(CANDIDATE), "sha256": sha256(CANDIDATE)},
                "actual_accumulator": {"path": source_key(ACCUM), "sha256": sha256(ACCUM)},
                "actual_pair_multiplier": {"path": source_key(PAIR), "sha256": sha256(PAIR)},
                "vendor_models": {source_key(path): sha256(path) for path in (DSP48E1, MULT_MACRO, GLBL)},
                "runtime_manifest": {"path": source_key(LOCAL_ROOT / "manifest.json"),
                                     "sha256": sha256(LOCAL_ROOT / "manifest.json"),
                                     "versions": manifest.get("versions")},
            },
            miter_invariants=[
                "Every per-site/per-8-lane local P3-valid replica equals the original global P3-valid at each pre-rising-edge sample.",
                "Every candidate DSP enable and local active mask equals the reference state/site/lane-qualified enable over all sites/lanes.",
                "Reference/candidate initialized flags, accumulator deltas, initialized accumulator values, and leaf load-bias inputs match.",
                "Public outputs and handshakes are compared every cycle, with stalls and cancellation/reset recovery exercised.",
            ],
            scenario_plan=[
                "SITES=1 and SITES=2 actual DSP48E1/MULT_MACRO vendor-source simulations.",
                "Wrong-token abort while an older P3 is present, plus early-last and missing-last aborts.",
                "Cancel at P0/P1/P2/P3 and reset at P1/P3; reconfigure and recover on subsequent runs.",
                "Bubbled and truly consecutive input groups, a full 32-lane run, saturation, tails, stalls, and drain.",
            ],
            scope="Bounded local source simulation only; mapped resource, timing benefit, full-core synthesis/route, and hardware remain unmeasured.",
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        env = dict(os.environ)
        env["PATH"] = str(LOCAL_ROOT / "ucrt64/bin") + os.pathsep + env.get("PATH", "")
        env["OMP_NUM_THREADS"] = "1"
        run_results: dict[int, dict[str, int]] = {}
        compile_warnings: dict[int, list[str]] = {}
        for sites in (1, 2):
            executable = build / f"mac_local_control_v3_sites{sites}.vvp"
            compile_argv = [str(compiler), "-B", str(backend), "-g2012", "-Wall",
                            f"-Ptb_z100_mac_local_control_v3.SITES={sites}",
                            "-s", "tb_z100_mac_local_control_v3", "-s", "glbl",
                            "-o", str(executable), str(DSP48E1), str(MULT_MACRO), str(GLBL),
                            str(ACCUM), str(PAIR), str(BASE_MAC), str(CANDIDATE), str(TB)]
            compile_log = run_command(f"sites{sites}_iverilog", compile_argv, build, out, env,
                                      report["commands"], 120)
            compile_warnings[sites] = [line for line in compile_log.splitlines()
                                       if re.search(r"\bwarning:", line, re.I)]
            require(executable.is_file(), f"SITES={sites} Icarus executable output missing")
            run_argv = [str(runner), "-M", str(backend), str(executable)]
            run_log = run_command(f"sites{sites}_vvp", run_argv, build, out, env,
                                  report["commands"], 120)
            run_results[sites] = parse_marker(run_log, sites)
            require(len(re.findall(r"\$finish called at", run_log)) == 1,
                    f"SITES={sites} simulation did not finish normally")

        after = dict(sorted((source_key(path), sha256(path)) for path in sources))
        require(before == after, "A source, vendor model, or runtime file changed during validation")
        report.update(
            status="PASS_LOCAL_VENDOR_SOURCE_CYCLE_EQUIVALENCE_SIMULATION_ONLY",
            source_sha256_after=after,
            simulation={"sites": run_results, "compile_warnings": compile_warnings},
            cycle_equivalence="PASS for public-cycle outputs and declared internal invariants in the covered SITES=1/2 scenarios",
            synthesis_or_route="NOT_RUN",
            mapped_resources="NOT_MEASURED",
            routed_timing="NOT_MEASURED",
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
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": report["status"], "report": source_key(report_path),
                      "error": report.get("error")}, indent=2))
    return 0 if str(report["status"]).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
