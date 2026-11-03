"""Run the isolated dynamic handshaking and full-output observation fixture.

Phases are deliberately separate: simulate, synthesize and inspect, then route
once. This prevents a routed implementation from starting before its netlist
has passed the explicit multiplier/bank/accumulator review gates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "deployment/hardware/z100_2026/reuse_handshake_fixture_v1"
CORE = ROOT / "deployment/hardware/z100_2026/tile_reuse_core_v2/z100_tile_reuse_core.v"
EVIDENCE_ROOT = ROOT / "validation/board_z100/reuse_handshake_fixture_v1"
BUILD_ROOT = ROOT / "deployment/build/z100_reuse_handshake_fixture_v1"
VIVADO_BIN = Path(r"C:\appload\2026.1\Vivado\bin")
SOURCE_FILES = (
    CORE,
    FIXTURE / "z100_tile_reuse_handshake_fixture_top.sv",
    FIXTURE / "tb_z100_tile_reuse_handshake_fixture.sv",
    FIXTURE / "sim_bufg.v",
    FIXTURE / "handshake_constraints.xdc",
    FIXTURE / "handshake_impl.tcl",
    Path(__file__).resolve(),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest() -> dict[str, str]:
    missing = [str(path) for path in SOURCE_FILES if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing fixture source(s): " + ", ".join(missing))
    return {str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES}


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def result_artifacts(evidence: Path, build: Path) -> dict[str, str]:
    paths = [p for p in evidence.rglob("*") if p.is_file() and p.name != "result.json"]
    paths += [p for p in (build / "post_synth.dcp", build / "post_place.dcp", build / "routed.dcp") if p.is_file()]
    return {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted(set(paths))
    }


def parse_sim_output(output: str) -> dict:
    if re.search(r"(?im)^(?:FAIL:|FATAL:|ERROR:)", output) or "HANDSHAKE_SIM_PASS" not in output:
        raise ValueError("simulation lacks the required pass marker or contains FAIL")
    match = re.search(
        r"HANDSHAKE_SIM_PASS accepted_jobs=(\d+) completed_jobs=(\d+) scanned_words=(\d+) "
        r"blocked_request_cycles=(\d+) output_stall_cycles=(\d+) total_cycles=(\d+)",
        output,
    )
    if not match:
        raise ValueError("simulation pass marker is missing required metrics")
    metrics = {
        "accepted_jobs": int(match.group(1)),
        "completed_jobs": int(match.group(2)),
        "scanned_words": int(match.group(3)),
        "blocked_request_cycles": int(match.group(4)),
        "output_stall_cycles": int(match.group(5)),
        "total_cycles": int(match.group(6)),
        "job_lines": len(re.findall(r"^JOB_PASS ", output, re.MULTILINE)),
        "cancel_reload_pass": "CANCEL_RELOAD_PASS" in output,
        "reset_stalled_result_pass": "RESET_STALLED_RESULT_PASS" in output,
    }
    if (
        metrics["accepted_jobs"] != 6
        or metrics["completed_jobs"] != 4
        or metrics["scanned_words"] != 512
        or metrics["blocked_request_cycles"] < 10
        or metrics["output_stall_cycles"] < 20
        or metrics["job_lines"] != 4
        or not metrics["cancel_reload_pass"]
        or not metrics["reset_stalled_result_pass"]
    ):
        raise ValueError("simulation metrics do not satisfy fixture coverage gates")
    jobs = []
    for line in re.findall(r"^JOB_PASS .*?$", output, re.MULTILINE):
        job = {key: int(value) for key, value in re.findall(r"(taps|scanned_words|stalls|scan_cycles)=(\d+)", line)}
        jobs.append(job)
    metrics["jobs"] = jobs
    return metrics


def parse_route_marker(output: str) -> dict:
    match = re.search(
        r"HANDSHAKE_ROUTE_RESULT all_setup_ns=([^ ]+) all_hold_ns=([^ ]+) "
        r"internal_setup_ns=([^ ]+) internal_hold_ns=([^ ]+) "
        r"core_setup_ns=([^ ]+) core_hold_ns=([^ ]+) "
        r"input_setup_ns=([^ ]+) input_hold_ns=([^ ]+) "
        r"output_setup_ns=([^ ]+) output_hold_ns=([^ ]+) "
        r"routable=(\d+) routed=(\d+) route_errors=(\d+) lut=(\d+) dsp=(\d+) "
        r"bram36_equivalent=([^ ]+) bufg=(\d+) registers=(\d+) core_registers=(\d+)",
        output,
    )
    if not match:
        raise ValueError("Vivado route output lacks all-design, core, input, output setup/hold metrics")
    return {
        "all_design_setup_slack_ns": float(match.group(1)),
        "all_design_hold_slack_ns": float(match.group(2)),
        "internal_setup_slack_ns": float(match.group(3)),
        "internal_hold_slack_ns": float(match.group(4)),
        "core_setup_slack_ns": float(match.group(5)),
        "core_hold_slack_ns": float(match.group(6)),
        "input_setup_slack_ns": float(match.group(7)),
        "input_hold_slack_ns": float(match.group(8)),
        "sequential_to_output_setup_slack_ns": float(match.group(9)),
        "sequential_to_output_hold_slack_ns": float(match.group(10)),
        "routable_nets": int(match.group(11)),
        "routed_nets": int(match.group(12)),
        "route_errors": int(match.group(13)),
        "lut": int(match.group(14)),
        "dsp": int(match.group(15)),
        "bram36_equivalent": float(match.group(16)),
        "bufg": int(match.group(17)),
        "registers": int(match.group(18)),
        "core_registers": int(match.group(19)),
    }


TIMING_CHECK_CATEGORIES = (
    "no_clock", "constant_clock", "pulse_width_clock", "unconstrained_internal_endpoints",
    "no_input_delay", "no_output_delay", "multiple_clock", "generated_clocks", "loops",
    "partial_input_delay", "partial_output_delay", "latch_loops",
)


def parse_check_timing_report(report: str) -> dict[str, int]:
    counts = {name: int(count) for name, count in re.findall(r"checking\s+([a-z_]+)\s+\((\d+)\)", report)}
    missing = sorted(set(TIMING_CHECK_CATEGORIES) - set(counts))
    if missing:
        raise ValueError("check_timing report misses categories: " + ", ".join(missing))
    nonzero = {name: counts[name] for name in TIMING_CHECK_CATEGORIES if counts[name] != 0}
    if nonzero:
        raise ValueError("check_timing has nonzero categories: " + repr(nonzero))
    return {name: counts[name] for name in TIMING_CHECK_CATEGORIES}


def parse_timing_check_marker(output: str, phase: str) -> dict[str, float | int]:
    match = re.search(
        rf"HANDSHAKE_TIMING_CHECK phase={re.escape(phase)} bufg=(\d+) registers=(\d+) core_regs=(\d+) check_categories=(\d+) "
        r"all_setup_ns=([-+0-9.eE]+) all_hold_ns=([-+0-9.eE]+) "
        r"core_setup_ns=([-+0-9.eE]+) core_hold_ns=([-+0-9.eE]+) "
        r"input_setup_ns=([-+0-9.eE]+) input_hold_ns=([-+0-9.eE]+) "
        r"output_setup_ns=([-+0-9.eE]+) output_hold_ns=([-+0-9.eE]+) status=PASS",
        output,
    )
    if not match:
        raise ValueError(f"Vivado output lacks complete {phase} timing classification")
    return {
        "bufg": int(match.group(1)),
        "registers": int(match.group(2)),
        "core_registers": int(match.group(3)),
        "check_timing_category_count": int(match.group(4)),
        "all_design_setup_slack_ns": float(match.group(5)),
        "all_design_hold_slack_ns": float(match.group(6)),
        "core_setup_slack_ns": float(match.group(7)),
        "core_hold_slack_ns": float(match.group(8)),
        "input_setup_slack_ns": float(match.group(9)),
        "input_hold_slack_ns": float(match.group(10)),
        "output_setup_slack_ns": float(match.group(11)),
        "output_hold_slack_ns": float(match.group(12)),
    }


def parse_drc_summary(report: str) -> dict:
    entries = re.findall(
        r"(?m)^\|\s*([A-Z0-9-]+)\s*\|\s*(Critical Warning|Warning|Error)\s*\|\s*(.*?)\s*\|\s*(\d+)\s*\|$",
        report,
    )
    if not entries and "No violations found" not in report:
        raise ValueError("DRC report does not contain a recognizable summary")
    violations = [
        {"rule": rule, "severity": severity, "description": description, "checks": int(checks)}
        for rule, severity, description, checks in entries
    ]
    return {
        "critical_warning_checks": sum(item["checks"] for item in violations if item["severity"] == "Critical Warning"),
        "warning_checks": sum(item["checks"] for item in violations if item["severity"] == "Warning"),
        "error_checks": sum(item["checks"] for item in violations if item["severity"] == "Error"),
        "violations": violations,
    }


def command_result(command: list[str], cwd: Path, log: Path, timeout: int | None = None) -> dict:
    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    started = datetime.now(timezone.utc).isoformat()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        output = completed.stdout or ""
        log.write_text(output, encoding="utf-8", errors="replace")
        return {
            "command": command,
            "cwd": str(cwd),
            "started_utc": started,
            "return_code": completed.returncode,
            "log": str(log),
            "output": output,
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        log.write_text(output + "\nCOMMAND_TIMEOUT\n", encoding="utf-8", errors="replace")
        return {
            "command": command,
            "cwd": str(cwd),
            "started_utc": started,
            "return_code": None,
            "timed_out": True,
            "log": str(log),
            "output": output,
        }


def get_run(run_id: str | None) -> tuple[str, Path, Path, dict]:
    if not run_id:
        raise ValueError("--run-id is required for synth and route")
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    launch_path = evidence / "launch.json"
    if not launch_path.is_file():
        raise FileNotFoundError(f"No simulation launch record for run {run_id}")
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    if launch.get("source_sha256") != source_manifest():
        raise RuntimeError("Fixture source identity changed since simulation; refusing to continue")
    return run_id, evidence, build, launch


def phase_simulate() -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    sim_dir = build / "sim"
    evidence.mkdir(parents=True, exist_ok=False)
    sim_dir.mkdir(parents=True, exist_ok=False)
    sources = source_manifest()
    launch = {
        "status": "SIMULATION_RUNNING",
        "run_id": run_id,
        "device": "xc7z100ffg900-2",
        "frequency_mhz": 200,
        "fixture": "dynamic-valid-ready-full-output-scan",
        "source_sha256": sources,
        "input_delay_assumption_ns": {"min": 0.0, "max": 1.0},
        "output_observation_budget_ns": {"min": 0.0, "max": 0.5, "load_pf": 5.0},
        "clock_uncertainty_ns": 0.1,
        "physical_board_tested": False,
        "bit_or_boot_generated": False,
        "release_eligible": False,
        "build_dir": str(build),
    }
    save_json(evidence / "launch.json", launch)
    xvlog = VIVADO_BIN / "xvlog.bat"
    xelab = VIVADO_BIN / "xelab.bat"
    xsim = VIVADO_BIN / "xsim.bat"
    commands = [
        [str(xvlog), "-sv", str(CORE), str(FIXTURE / "sim_bufg.v"),
         str(FIXTURE / "z100_tile_reuse_handshake_fixture_top.sv"),
         str(FIXTURE / "tb_z100_tile_reuse_handshake_fixture.sv")],
        [str(xelab), "-mt", "2", "tb_z100_tile_reuse_handshake_fixture", "-s", "handshake_fixture_sim"],
        [str(xsim), "handshake_fixture_sim", "-runall"],
    ]
    phases = []
    for index, command in enumerate(commands):
        names = ("xvlog", "xelab", "xsim")
        log = evidence / f"{names[index]}.log"
        run = command_result(command, sim_dir, log)
        run.pop("output", None)
        phases.append(run)
        if run["return_code"] != 0:
            break
    report = {
        "status": "SIMULATION_FAILED",
        "run_id": run_id,
        "source_sha256": sources,
        "simulation_commands": phases,
        "build_dir": str(build),
    }
    sim_output = ""
    sim_log = evidence / "xsim.log"
    if phases and phases[-1]["return_code"] == 0 and sim_log.exists():
        sim_output = sim_log.read_text(encoding="utf-8", errors="replace")
        try:
            report["simulation_metrics"] = parse_sim_output(sim_output)
            report["status"] = "PASS_DYNAMIC_HANDSHAKE_FULL_OUTPUT_SIMULATION"
        except ValueError as exc:
            report["simulation_parse_error"] = str(exc)
    launch["status"] = report["status"]
    save_json(evidence / "launch.json", launch)
    report["artifact_sha256"] = result_artifacts(evidence, build)
    save_json(evidence / "result.json", report)
    print(json.dumps({"run_id": run_id, "status": report["status"], "evidence": str(evidence),
                      "simulation_metrics": report.get("simulation_metrics")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS_DYNAMIC_HANDSHAKE_FULL_OUTPUT_SIMULATION" else 1


def phase_synth(run_id: str) -> int:
    _, evidence, build, launch = get_run(run_id)
    previous = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
    if previous.get("status") != "PASS_DYNAMIC_HANDSHAKE_FULL_OUTPUT_SIMULATION":
        raise RuntimeError("Synthesis is gated on a passing full-output simulation")
    command = [str(VIVADO_BIN / "vivado.bat"), "-mode", "batch",
               "-log", str(evidence / "synth_vivado.log"),
               "-journal", str(evidence / "synth_vivado.jou"),
               "-source", str(FIXTURE / "handshake_impl.tcl"),
               "-tclargs", "200", str(build), str(evidence), "synth"]
    run = command_result(command, ROOT, evidence / "synth_stdout.log", timeout=7200)
    output = run.pop("output", "")
    report = previous
    report["synthesis_command"] = run
    vivado_log_path = evidence / "synth_vivado.log"
    vivado_log = vivado_log_path.read_text(encoding="utf-8", errors="replace") if vivado_log_path.is_file() else ""
    quality = {
        "error_lines": len(re.findall(r"(?m)^ERROR:", vivado_log)),
        "critical_warning_lines": len(re.findall(r"(?m)^CRITICAL WARNING:", vivado_log)),
        "warning_lines": len(re.findall(r"(?m)^WARNING:", vivado_log)),
    }
    report["synthesis_log_quality"] = quality
    try:
        check_timing = parse_check_timing_report((evidence / "check_timing_synth.rpt").read_text(encoding="utf-8"))
        report["synthesis_check_timing"] = check_timing
        report["synthesis_timing"] = parse_timing_check_marker(output, "synth")
    except (OSError, ValueError) as exc:
        report["synthesis_review_error"] = str(exc)
    structure = re.search(
        r"HANDSHAKE_STRUCTURE phase=synth dsp=(\d+) ram_cells=(\d+) weight_banks=(\d+) activation_bank_sites=(\d+)", output
    )
    if structure:
        report["synthesis_structure"] = {
            "dsp_cells": int(structure.group(1)),
            "ram_cells": int(structure.group(2)),
            "weight_banks": int(structure.group(3)),
            "activation_bank_sites": int(structure.group(4)),
        }
    synthesis_marker = re.search(r"HANDSHAKE_SYNTHESIS_REVIEW_READY .*", output)
    synthesis_resources = None
    if synthesis_marker:
        resource_match = re.search(r"dsp=(\d+) bram36_equivalent=([0-9.]+) lut=(\d+)", synthesis_marker.group(0))
        if resource_match:
            synthesis_resources = {
                "dsp": int(resource_match.group(1)),
                "bram36_equivalent": float(resource_match.group(2)),
                "lut": int(resource_match.group(3)),
            }
            report["synthesis_resources"] = synthesis_resources
    constraints_text = (evidence / "synth_clock_topology.txt").read_text(encoding="utf-8", errors="replace") if (evidence / "synth_clock_topology.txt").is_file() else ""
    constraints_evidenced = all(
        required in constraints_text
        for required in (
            "INPUT_DELAY_NS min=0.000 max=1.000",
            "OUTPUT_DELAY_NS min=0.000 max=0.500 load_pf=5.000",
            "CLOCK_UNCERTAINTY_NS 0.100",
            "DONT_TOUCH_CELL_COUNT 0",
            "BUFG_COUNT 1",
        )
    )
    review_complete = (
        run["return_code"] == 0
        and synthesis_marker is not None
        and (build / "post_synth.dcp").is_file()
        and quality["error_lines"] == 0
        and quality["critical_warning_lines"] == 0
        and constraints_evidenced
        and "synthesis_check_timing" in report
        and report.get("synthesis_timing", {}).get("check_timing_category_count") == len(TIMING_CHECK_CATEGORIES)
        and report.get("synthesis_structure", {}).get("dsp_cells") == 512
        and report.get("synthesis_structure", {}).get("weight_banks") == 4
        and report.get("synthesis_structure", {}).get("activation_bank_sites") == 16
        and synthesis_resources is not None
        and synthesis_resources.get("dsp") == 512
        and abs(synthesis_resources.get("bram36_equivalent", -1.0) - 38.0) < 0.01
    )
    if review_complete:
        report["status"] = "SYNTHESIS_REVIEW_READY"
        report["synthesis_marker"] = synthesis_marker.group(0)
        report["synthesis_constraints_evidenced"] = True
    else:
        report["status"] = "SYNTHESIS_FAILED_OR_REVIEW_INCOMPLETE"
    report["artifact_sha256"] = result_artifacts(evidence, build)
    save_json(evidence / "result.json", report)
    print(json.dumps({"run_id": run_id, "status": report["status"],
                      "synthesis_marker": report.get("synthesis_marker"),
                      "evidence": str(evidence)}, ensure_ascii=False))
    return 0 if report["status"] == "SYNTHESIS_REVIEW_READY" else 1


def phase_route(run_id: str) -> int:
    _, evidence, build, launch = get_run(run_id)
    previous = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
    if previous.get("status") != "SYNTHESIS_REVIEW_READY":
        raise RuntimeError("Routing is gated on a passed, reviewed synthesis phase")
    marker = evidence / "route_launch.json"
    try:
        with marker.open("x", encoding="utf-8") as stream:
            json.dump({"status": "ROUTE_ATTEMPTED_ONCE", "run_id": run_id,
                       "checkpoint_sha256": sha256(build / "post_synth.dcp"),
                       "started_utc": datetime.now(timezone.utc).isoformat()}, stream, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise RuntimeError("This evidence directory already contains the one permitted route attempt") from exc
    command = [str(VIVADO_BIN / "vivado.bat"), "-mode", "batch",
               "-log", str(evidence / "route_vivado.log"),
               "-journal", str(evidence / "route_vivado.jou"),
               "-source", str(FIXTURE / "handshake_impl.tcl"),
               "-tclargs", "200", str(build), str(evidence), "route", str(build / "post_synth.dcp")]
    run = command_result(command, ROOT, evidence / "route_stdout.log", timeout=14400)
    output = run.pop("output", "")
    report = previous
    report["route_command"] = run
    try:
        if run["return_code"] != 0:
            raise ValueError("Vivado route command failed")
        route_metrics = parse_route_marker(output)
        report["route_metrics"] = route_metrics
        drc_path = evidence / "drc_routed.rpt"
        report["drc_summary"] = parse_drc_summary(drc_path.read_text(encoding="utf-8", errors="replace"))
        report["status"] = "ROUTE_COMPLETED_REQUIRES_TIMING_REVIEW"
        if route_metrics["routable_nets"] != route_metrics["routed_nets"] or route_metrics["route_errors"] != 0:
            report["status"] = "ROUTE_COMPLETED_WITH_ROUTING_ERRORS"
            report["timing_assessment"] = "FAIL_ROUTE_COMPLETENESS"
        else:
            reviewed_slack_fields = (
                "all_design_setup_slack_ns", "all_design_hold_slack_ns",
                "internal_setup_slack_ns", "internal_hold_slack_ns",
                "core_setup_slack_ns", "core_hold_slack_ns",
                "input_setup_slack_ns", "input_hold_slack_ns",
                "sequential_to_output_setup_slack_ns", "sequential_to_output_hold_slack_ns",
            )
            negative = [name for name in reviewed_slack_fields if route_metrics[name] < 0]
            report["timing_assessment"] = (
                "FAIL_SETUP_OR_HOLD:" + ",".join(negative)
                if negative
                else "PASS_REPORTED_SETUP_AND_HOLD_PENDING_PULSE_DRC_REVIEW"
            )
        report["drc_assessment"] = (
            "HAS_DRC_ERRORS" if report["drc_summary"]["error_checks"]
            else "HAS_CRITICAL_WARNINGS" if report["drc_summary"]["critical_warning_checks"]
            else "NO_DRC_ERRORS_OR_CRITICAL_WARNINGS"
        )
    except ValueError as exc:
        report["status"] = "ROUTE_ATTEMPT_FAILED_PRESERVED"
        report["route_parse_error"] = str(exc)
    report["artifact_sha256"] = result_artifacts(evidence, build)
    save_json(evidence / "result.json", report)
    print(json.dumps({"run_id": run_id, "status": report["status"],
                      "timing_assessment": report.get("timing_assessment"),
                      "route_metrics": report.get("route_metrics"),
                      "evidence": str(evidence)}, ensure_ascii=False))
    return 0 if report["status"] == "ROUTE_COMPLETED_REQUIRES_TIMING_REVIEW" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("simulate", "synth", "route"), required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        if args.phase == "simulate":
            return phase_simulate()
        if args.phase == "synth":
            return phase_synth(args.run_id)
        return phase_route(args.run_id)
    except Exception as exc:  # The report/logs remain in place when a phase fails.
        print(f"VALIDATION_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
