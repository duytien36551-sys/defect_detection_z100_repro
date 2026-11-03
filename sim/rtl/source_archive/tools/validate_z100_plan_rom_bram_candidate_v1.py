#!/usr/bin/env python3
"""Differentially validate and OOC-synthesize the isolated plan-ROM candidate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ISOLATION = ROOT / "deployment/hardware/z100_2026/platform_v13c/isolation/plan_rom_bram_v1_20261030"
BASELINE_RTL = ROOT / "deployment/hardware/z100_2026/platform_v13c/prepared/conv_pool_guard_v2_20261029/rtl/z100_conv_plan_rom.sv"
CANDIDATE_RTL = ISOLATION / "rtl/z100_conv_plan_rom_bram_v1.sv"
TB_RTL = ISOLATION / "rtl/tb_z100_conv_plan_rom_bram_v1.sv"
PROOF_REPORT = ROOT / "validation/board_z100/conv_plan_rom/20261026T002221.159778Z/result.json"
C_PLAN_REPORT = ROOT / "validation/board_z100/native_row_commands_v2/20261025T062641.961558Z/result.json"
FIXTURE_BUILD = ROOT / "build/cpr_002221.159778Z"
ICARUS_ROOT = ROOT / "deployment/build/local_tools/iverilog13_msys2"
ICARUS_MANIFEST = ICARUS_ROOT / "manifest.json"
VIVADO = Path("C:/appload/2026.1/Vivado/bin/vivado.bat")
PART = "xc7z100ffg900-2"
OOC_MIN_RAM_GIB = 4.0
OOC_MIN_C_FREE_GIB = 20.0
OOC_RESOURCE_GATE_BASIS = {
    "scope": "single isolated plan-ROM OOC synth only; no implementation/route",
    "historical_reference": "C:/z100p/tilearith_base01/vivado.log",
    "historical_reported_peak_mb": {"baseline": 2230.879, "candidate": 2228.012},
    "gate_note": "4 GiB available-RAM admission is specific to this small OOC job; full platform gates remain unchanged.",
}
BASELINE_SHA256 = "c8318cc3c254da326ddcb1ef4c3aba11cbf810ca6165790f6eda876654f7ef20"
FIXTURE_HASHES = {
    "conv_event_map.hex": "7f5dbedbc8b0487350ea40465b2e6ae1bc404e6c167da25b72cedf94e4dbaf85",
    "conv_tiles.hex": "8295ab50a944c6b8c61b97515d8a388919f287dd2c487c63c6da997a64c99f0c",
    "expected_plan.hex": "90168e06c1daf05b4cfbab4151fcaaae910cc2219679096ec570c717b2c0e808",
}
MARKER = "PLAN_ROM_BRAM_MITER_PASS"


class ValidationError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def parse_simulation_marker(text: str) -> dict[str, int]:
    lines = [line for line in text.splitlines() if line.startswith(MARKER + " ")]
    require(len(lines) == 1, "simulation must emit exactly one differential pass marker")
    values = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", lines[0])}
    expected = {"tiles": 189, "negative_cases": 12, "held_cycles": 609,
                "cancel_cases": 1, "latency_cycles": 1,
                "back_to_back_replacements": 2, "reset_request_collisions": 1,
                "cancel_request_collisions": 1}
    require(all(values.get(key) == value for key, value in expected.items()),
            f"differential coverage marker mismatch: {values}")
    return values


def parse_resource_metrics(path: Path) -> dict[str, dict[str, int]]:
    values: dict[str, dict[str, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        label, metric, count = fields
        require(label in {"baseline", "candidate"}, f"unexpected resource label: {label}")
        try:
            parsed = int(count)
        except ValueError as exc:
            raise ValidationError(f"invalid resource count: {line}") from exc
        values.setdefault(label, {})[metric] = parsed
    require(set(values) == {"baseline", "candidate"}, "resource file must contain baseline and candidate")
    for label, metrics in values.items():
        for required_metric in ("logic_lut", "bram36", "bram18", "lutram_primitives", "ff_primitives"):
            require(required_metric in metrics, f"{label} lacks {required_metric} metric")
    return values


def resource_assessment(metrics: dict[str, dict[str, int]]) -> str:
    base = metrics["baseline"]
    candidate = metrics["candidate"]
    if candidate["logic_lut"] >= base["logic_lut"]:
        return "NO_LUT_REDUCTION"
    base_bram = base["bram36"] + base["bram18"]
    candidate_bram = candidate["bram36"] + candidate["bram18"]
    if candidate_bram > base_bram:
        return "LUT_REDUCTION_BRAM_INCREASE"
    if candidate_bram == base_bram:
        return "LUT_REDUCTION_BRAM_FLAT"
    return "LUT_REDUCTION_BRAM_DECREASE"


def resource_delta(metrics: dict[str, dict[str, int]]) -> dict[str, int]:
    base = metrics["baseline"]
    candidate = metrics["candidate"]
    return {name: candidate[name] - base[name]
            for name in ("logic_lut", "bram36", "bram18", "lutram_primitives", "ff_primitives")}


def verify_inputs() -> dict[str, str]:
    required = (BASELINE_RTL, CANDIDATE_RTL, TB_RTL, PROOF_REPORT, C_PLAN_REPORT, ICARUS_MANIFEST)
    for path in required:
        require(path.is_file(), f"required input is missing: {path}")
    require(sha256(BASELINE_RTL) == BASELINE_SHA256,
            "frozen prepared baseline RTL SHA-256 differs from pinned identity")
    proof = json.loads(PROOF_REPORT.read_text(encoding="utf-8"))
    require(proof.get("status") == "PREPARED_MODEL_BOUND_CONV_ROM_C_PLAN_ONLY_NOT_RTL_EXECUTED",
            "frozen C-plan fixture report has an unexpected status")
    c_report = json.loads(C_PLAN_REPORT.read_text(encoding="utf-8"))
    require(c_report.get("tiles") == 189 and c_report.get("convolutions") == 63 and
            c_report.get("runs") == 26380 and c_report.get("window_requests") == 1659840 and
            c_report.get("execution_return_code") == 0,
            "frozen C plan does not match expected model totals")
    inputs = {str(path.resolve()): sha256(path) for path in required}
    for name, expected in FIXTURE_HASHES.items():
        path = FIXTURE_BUILD / name
        require(path.is_file() and sha256(path) == expected,
                f"C-plan fixture identity differs: {path}")
        inputs[str(path.resolve())] = expected
        require(proof.get("artifact_sha256", {}).get(str(Path("build") / FIXTURE_BUILD.name / name)) == expected,
                f"C-plan report does not bind fixture: {name}")
    manifest = json.loads(ICARUS_MANIFEST.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "project-local-iverilog/1" and
            manifest.get("global_environment_changed") is False,
            "local Icarus manifest is not the expected isolated toolchain")
    for name, expected in manifest.get("files", {}).items():
        path = ICARUS_ROOT / Path(name)
        require(path.is_file() and sha256(path) == expected,
                f"project-local Icarus tool hash differs: {name}")
        inputs[str(path.resolve())] = expected
    return inputs


def stage_fixtures(sim_dir: Path) -> dict[str, str]:
    staged: dict[str, str] = {}
    for name, expected in FIXTURE_HASHES.items():
        source = FIXTURE_BUILD / name
        target = sim_dir / name
        shutil.copyfile(source, target)
        require(sha256(target) == expected, f"staged fixture changed: {name}")
        staged[str(target.resolve())] = expected
    return staged


def run_simulation(run_dir: Path, report: dict[str, Any]) -> None:
    sim_dir = run_dir / "simulation"
    build_dir = sim_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=False)
    staged = stage_fixtures(sim_dir)
    binary = ICARUS_ROOT / "ucrt64/bin"
    backend = ICARUS_ROOT / "ucrt64/lib/ivl"
    iverilog = binary / "iverilog.exe"
    vvp = binary / "vvp.exe"
    output = build_dir / "plan_rom_bram_miter.vvp"
    compile_argv = [str(iverilog), "-B", str(backend), "-g2012", "-s", "tb_z100_conv_plan_rom_bram_v1",
                    "-o", str(output), str(BASELINE_RTL), str(CANDIDATE_RTL), str(TB_RTL)]
    env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ.get("PATH", ""), OMP_NUM_THREADS="1")
    started = time.monotonic()
    compile_run = subprocess.run(compile_argv, cwd=sim_dir, env=env, text=True,
                                 encoding="utf-8", errors="replace", capture_output=True, timeout=300)
    compile_log = compile_run.stdout + "\n" + compile_run.stderr
    (sim_dir / "iverilog.log").write_text(compile_log, encoding="utf-8")
    report["commands"].append({"label": "iverilog", "argv": compile_argv,
                               "return_code": compile_run.returncode,
                               "wall_seconds": time.monotonic() - started})
    require(compile_run.returncode == 0 and not re.search(r"(?:error:|syntax error|sorry:)", compile_log, re.I),
            "Icarus compilation failed or emitted a strict error")
    started = time.monotonic()
    sim_argv = [str(vvp), "-M", str(backend), str(output)]
    sim_run = subprocess.run(sim_argv, cwd=sim_dir, env=env, text=True,
                             encoding="utf-8", errors="replace", capture_output=True, timeout=300)
    sim_log = sim_run.stdout + "\n" + sim_run.stderr
    (sim_dir / "vvp.log").write_text(sim_log, encoding="utf-8")
    report["commands"].append({"label": "vvp", "argv": sim_argv,
                               "return_code": sim_run.returncode,
                               "wall_seconds": time.monotonic() - started})
    require(sim_run.returncode == 0 and not re.search(r"(?:ERROR:|FATAL:|Unable to open)", sim_log, re.I),
            "Icarus differential simulation failed or emitted a strict error")
    report["simulation"] = {"status": "PASS_DIFFERENTIAL_CYCLE_EQUIVALENCE", **parse_simulation_marker(sim_log),
                            "latency_changed": False, "staged_fixture_sha256": staged}


def write_synth_tcl(run_dir: Path) -> Path:
    out = run_dir / "synthesis"
    out.mkdir(parents=True, exist_ok=False)
    metrics = out / "primitive_metrics.tsv"
    tcl = out / "synth_plan_rom_pair.tcl"
    source_lines: list[str] = [
        "set_param general.maxThreads 2",
        f"create_project -in_memory -part {PART}",
        "proc synth_one {label source top output_dir metrics_file} {",
        "  read_verilog -sv $source",
        f"  synth_design -top $top -part {PART} -mode out_of_context -flatten_hierarchy none",
        "  create_clock -period 10 [get_ports clk]",
        "  report_utilization -file [file join $output_dir ${label}_utilization.rpt]",
        "  report_utilization -hierarchical -file [file join $output_dir ${label}_hierarchical_utilization.rpt]",
        "  set lut 0",
        "  foreach kind {LUT1 LUT2 LUT3 LUT4 LUT5 LUT6} {",
        "    set n [llength [get_cells -hier -filter [format {REF_NAME == %s} $kind]]]",
        "    incr lut $n",
        "  }",
        "  set bram36 [llength [get_cells -hier -filter {REF_NAME == RAMB36E1}]]",
        "  set bram18 [llength [get_cells -hier -filter {REF_NAME == RAMB18E1}]]",
        "  set lutram 0",
        "  foreach kind {RAM32M RAM32M16 RAM64M RAM64M8 RAM32X1S RAM64X1S RAMS32 RAMD32 RAMD64} {",
        "    incr lutram [llength [get_cells -hier -filter [format {REF_NAME == %s} $kind]]]",
        "  }",
        "  set ff 0",
        "  foreach kind {FDRE FDSE FDCE FDPE FD FDR} {",
        "    incr ff [llength [get_cells -hier -filter [format {REF_NAME == %s} $kind]]]",
        "  }",
        "  set f [open $metrics_file a]",
        "  set sep \"\\t\"",
        "  puts $f [join [list $label logic_lut $lut] $sep]",
        "  puts $f [join [list $label bram36 $bram36] $sep]",
        "  puts $f [join [list $label bram18 $bram18] $sep]",
        "  puts $f [join [list $label lutram_primitives $lutram] $sep]",
        "  puts $f [join [list $label ff_primitives $ff] $sep]",
        "  close $f",
        "  puts \"PLAN_ROM_OOC_ONE label=$label logic_lut=$lut bram36=$bram36 bram18=$bram18 lutram=$lutram ff=$ff\"",
        "  close_design",
        "  remove_files -quiet [get_files $source]",
        "}",
        f"set base_source {{{BASELINE_RTL.as_posix()}}}",
        f"set candidate_source {{{CANDIDATE_RTL.as_posix()}}}",
        f"set output_dir {{{out.as_posix()}}}",
        f"set metrics_file {{{metrics.as_posix()}}}",
        "synth_one baseline $base_source z100_conv_plan_rom $output_dir $metrics_file",
        "synth_one candidate $candidate_source z100_conv_plan_rom_bram_v1 $output_dir $metrics_file",
        "puts \"PLAN_ROM_BRAM_OOC_COMPLETE part=xc7z100ffg900-2 period_ns=10 threads=2\"",
        "exit",
    ]
    tcl.write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    return tcl


def run_synthesis(run_dir: Path, report: dict[str, Any]) -> bool:
    import run_z100_registered_response_bank_v2 as shared

    active = shared.vendor_inventory()
    resources = shared.system_resources()
    report["synthesis_admission"] = {
        "vendor_processes_before_lock": active,
        "resources_before_lock": resources,
        "resource_gate": {"minimum_available_ram_gib": OOC_MIN_RAM_GIB,
                          "minimum_c_free_gib": OOC_MIN_C_FREE_GIB,
                          "basis": OOC_RESOURCE_GATE_BASIS},
    }
    if (active or resources["available_ram_gib"] < OOC_MIN_RAM_GIB
            or resources["c_free_gib"] < OOC_MIN_C_FREE_GIB):
        report["synthesis"] = {"status": "DEFERRED_VENDOR_BUSY_OR_RESOURCES", "started": False}
        return False
    try:
        lock = shared.NamedMutex(timeout_ms=0)
        lock.__enter__()
    except TimeoutError:
        report["synthesis"] = {"status": "DEFERRED_MUTEX_BUSY", "started": False}
        return False
    try:
        active = shared.vendor_inventory()
        resources = shared.system_resources()
        report["synthesis_admission"]["vendor_processes_after_lock"] = active
        report["synthesis_admission"]["resources_after_lock"] = resources
        if (active or resources["available_ram_gib"] < OOC_MIN_RAM_GIB
                or resources["c_free_gib"] < OOC_MIN_C_FREE_GIB):
            report["synthesis"] = {"status": "DEFERRED_VENDOR_BUSY_OR_RESOURCES_AFTER_LOCK", "started": False}
            return False
        require(VIVADO.is_file(), f"Vivado 2026.1 batch launcher is missing: {VIVADO}")
        tcl = write_synth_tcl(run_dir)
        before = {str(path.resolve()): sha256(path) for path in (BASELINE_RTL, CANDIDATE_RTL, TB_RTL, tcl)}
        log_path = run_dir / "synthesis/vivado.log"
        argv = [str(VIVADO), "-mode", "batch", "-source", str(tcl)]
        started = time.monotonic()
        env = dict(os.environ, XILINX_LOCAL_USER_DATA="no", OMP_NUM_THREADS="1",
                   OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        proc = subprocess.run(argv, cwd=run_dir / "simulation", env=env,
                              text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=900)
        log = proc.stdout + "\n" + proc.stderr
        log_path.write_text(log, encoding="utf-8")
        after = {name: sha256(Path(name)) for name in before}
        require(before == after, "an OOC input changed while Vivado was running")
        require(proc.returncode == 0 and "PLAN_ROM_BRAM_OOC_COMPLETE part=xc7z100ffg900-2 period_ns=10 threads=2" in log,
                f"Vivado OOC failed or omitted terminal marker (exit={proc.returncode})")
        metrics = parse_resource_metrics(run_dir / "synthesis/primitive_metrics.tsv")
        report["synthesis"] = {
            "status": "PASS_OOC_SYNTH_MEASURED",
            "started": True,
            "part": PART,
            "period_ns": 10,
            "threads": 2,
            "return_code": proc.returncode,
            "wall_seconds": time.monotonic() - started,
            "argv": argv,
            "primitive_metrics": metrics,
            "resource_delta_candidate_minus_baseline": resource_delta(metrics),
            "resource_assessment": resource_assessment(metrics),
            "limits": ["OOC synthesis only; no place/route, board, or performance claim."],
        }
        report["commands"].append({"label": "vivado_ooc_pair", "argv": argv,
                                   "return_code": proc.returncode,
                                   "wall_seconds": report["synthesis"]["wall_seconds"]})
        return True
    finally:
        lock.__exit__(None, None, None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("simulate", "both"), default="both",
                        help="both runs the cycle-differential test then gated baseline/candidate OOC synthesis")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = ISOLATION / "runs" / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    report_path = run_dir / "result.json"
    report: dict[str, Any] = {
        "schema": "z100-plan-rom-bram-candidate-validation-v1/1",
        "run_id": stamp,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "candidate": str(CANDIDATE_RTL.relative_to(ROOT)),
        "baseline": str(BASELINE_RTL.relative_to(ROOT)),
        "board_access": False,
        "placement_or_routing": False,
        "commands": [],
    }
    before: dict[str, str] = {}
    try:
        before = verify_inputs()
        before[str(Path(__file__).resolve())] = sha256(Path(__file__))
        before[str(CANDIDATE_RTL.resolve())] = sha256(CANDIDATE_RTL)
        before[str(TB_RTL.resolve())] = sha256(TB_RTL)
        report["input_sha256_before"] = before
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run_simulation(run_dir, report)
        if args.phase == "both":
            started = run_synthesis(run_dir, report)
            if not started:
                report["status"] = report["synthesis"]["status"]
            else:
                report["status"] = "PASS_DIFFERENTIAL_OOC_MEASURED"
        else:
            report["status"] = "PASS_DIFFERENTIAL_ONLY_OOC_NOT_RUN"
    except Exception as exc:
        report.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")
    report["input_sha256_after"] = {name: sha256(Path(name)) for name in before if Path(name).is_file()}
    if before and report.get("input_sha256_before") != report["input_sha256_after"]:
        report["status"] = "FAILED_SOURCE_INTEGRITY"
        report["error"] = "one or more proof-bound inputs changed during validation"
    report["artifact_sha256"] = {
        str(path.resolve()): sha256(path)
        for path in run_dir.rglob("*") if path.is_file() and path != report_path
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(report_path),
                      "error": report.get("error")}, ensure_ascii=False))
    if report["status"].startswith("FAILED"):
        return 1
    if report["status"].startswith("DEFERRED"):
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
