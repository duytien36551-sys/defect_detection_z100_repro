#!/usr/bin/env python3
"""Run isolated synchronous timing-fixture simulation and Vivado OOC routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "deployment/hardware/z100_2026/reuse_sync_fixture"
CORE_DIR = ROOT / "deployment/hardware/z100_2026/tile_reuse_core_v0"
BUILD_ROOT = ROOT / "deployment/build/z100_reuse_sync_fixture"
EVIDENCE_ROOT = ROOT / "validation/board_z100/reuse_sync_fixture"
AUDIT_DIR = EVIDENCE_ROOT / "old_dcp_audit"
OLD_DCP = (
    ROOT
    / "deployment/build/z100_reuse_core_v0/20261021T074636Z_23e81169/ooc_100mhz/routed.dcp"
)
OLD_DCP_SHA256 = "e56893ba9645f9829a9fbc5fafbc6cb5cd5ab81e26b30fa4154dd4d424d03862"
OLD_CORE_SHA256 = "03f3cc56e2e2c1fe91e57288890675b90ada5e3053448bfeddc0cb894ab682c9"
VIVADO_DEFAULT = Path(r"C:\appload\2026.1\Vivado\bin\vivado.bat")
METRIC_RE = re.compile(r"^SYNC_FIXTURE_RESULT\s+(.*)$", re.MULTILINE)
FIELD_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^\s]+)")
CHECK_CATEGORIES = (
    "no_clock",
    "constant_clock",
    "pulse_width_clock",
    "unconstrained_internal_endpoints",
    "no_input_delay",
    "no_output_delay",
    "multiple_clock",
    "generated_clocks",
    "loops",
    "partial_input_delay",
    "partial_output_delay",
    "latch_loops",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_route_status(text: str) -> dict[str, int]:
    patterns = {
        "routable": r"# of routable nets\.+\s*:\s*(\d+)",
        "routed": r"# of fully routed nets\.+\s*:\s*(\d+)",
        "errors": r"# of nets with routing errors\.+\s*:\s*(\d+)",
    }
    result: dict[str, int] = {}
    for name, pattern in patterns.items():
        found = re.findall(pattern, text)
        if len(found) != 1:
            raise ValueError(f"route report must contain exactly one {name} count")
        result[name] = int(found[0])
    return result


def parse_check_timing(text: str) -> dict[str, int]:
    # Vivado emits each category in both its table of contents and body.
    # Parse the body when the actual report has a TOC; synthetic fragments
    # remain useful for rejecting missing/duplicate categories in tests.
    if "Table of Contents" in text:
        first = text.find("1. checking no_clock")
        second = text.find("1. checking no_clock", first + 1)
        if second < 0:
            raise ValueError("check_timing report is missing its body")
        text = text[second:]
    result: dict[str, int] = {}
    for category in CHECK_CATEGORIES:
        found = re.findall(rf"checking\s+{re.escape(category)}\s+\((\d+)\)", text)
        if len(found) != 1:
            raise ValueError(f"check_timing report must contain exactly one {category} count")
        result[category] = int(found[0])
    if re.search(r"checking\s+[a-zA-Z0-9_]+\s+\(", text) and len(
        re.findall(r"checking\s+[a-zA-Z0-9_]+\s+\(\d+\)", text)
    ) != len(CHECK_CATEGORIES):
        raise ValueError("check_timing report contains unknown or duplicate categories")
    return result


def parse_sync_result(text: str) -> dict[str, int | float]:
    matches = METRIC_RE.findall(text)
    if len(matches) != 1:
        raise ValueError("Vivado log must contain exactly one SYNC_FIXTURE_RESULT line")
    raw = dict(FIELD_RE.findall(matches[0]))
    required = {
        "frequency_mhz",
        "internal_wns_ns",
        "internal_whs_ns",
        "routable",
        "routed",
        "route_errors",
        "lut",
        "dsp",
        "bram36_equivalent",
        "bufg",
        "registers",
    }
    if set(raw) != required:
        raise ValueError(f"SYNC_FIXTURE_RESULT fields differ from schema: {sorted(raw)}")
    try:
        result: dict[str, int | float] = {
            key: (float(value) if key in {"internal_wns_ns", "internal_whs_ns", "bram36_equivalent"} else int(value))
            for key, value in raw.items()
        }
    except ValueError as exc:
        raise ValueError("SYNC_FIXTURE_RESULT contains a nonnumeric value") from exc
    if not all(math.isfinite(float(value)) for value in result.values()):
        raise ValueError("SYNC_FIXTURE_RESULT contains a nonfinite value")
    if result["frequency_mhz"] not in (100, 200):
        raise ValueError("unsupported fixture frequency")
    return result


def classify_run(
    metrics: dict[str, int | float],
    route: dict[str, int],
    check_timing: dict[str, int],
    sim: dict[str, int | str],
) -> str:
    if sim.get("status") != "PASS":
        return "SIMULATION_FAIL"
    if metrics["bufg"] != 1 or metrics["registers"] < 20000:
        return "CLOCK_TOPOLOGY_OR_CORE_LOST"
    if route != {
        "routable": int(metrics["routable"]),
        "routed": int(metrics["routed"]),
        "errors": int(metrics["route_errors"]),
    }:
        return "ROUTE_REPORT_MISMATCH"
    if route["routable"] <= 0 or route["routable"] != route["routed"] or route["errors"] != 0:
        return "ROUTE_INCOMPLETE"
    if set(check_timing) != set(CHECK_CATEGORIES) or any(check_timing.values()):
        return "CHECK_TIMING_FAIL"
    if float(metrics["internal_wns_ns"]) < 0 or float(metrics["internal_whs_ns"]) < 0:
        return "INTERNAL_TIMING_FAIL"
    return "PASS_SYNC_FIXTURE_TIMING"


def run_command(command: list[str], cwd: Path, log_path: Path) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        subprocess.list2cmdline(command),
        cwd=str(cwd),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {
        "command": command,
        "cwd": str(cwd),
        "return_code": completed.returncode,
        "log": str(log_path),
        "warning_mentions": len(re.findall(r"\bWARNING\b", completed.stdout, re.IGNORECASE)),
        "output": completed.stdout,
    }


def run_simulation(run_id: str, vivado: Path) -> dict[str, Any]:
    bindir = vivado.parent
    xvlog, xelab, xsim = (bindir / f"{tool}.bat" for tool in ("xvlog", "xelab", "xsim"))
    for tool in (xvlog, xelab, xsim):
        if not tool.is_file():
            raise FileNotFoundError(f"Required Vivado tool is unavailable: {tool}")
    work = BUILD_ROOT / run_id / "sim"
    evidence = EVIDENCE_ROOT / run_id
    work.mkdir(parents=True, exist_ok=True)
    sources = [
        FIXTURE_DIR / "sim_bufg.v",
        CORE_DIR / "z100_tile_reuse_core.v",
        FIXTURE_DIR / "z100_tile_reuse_sync_fixture_top.v",
        FIXTURE_DIR / "tb_z100_tile_reuse_sync_fixture.sv",
    ]
    phases = [
        ("xvlog", [str(xvlog), "-sv", *map(str, sources)]),
        ("xelab", [str(xelab), "-mt", "2", "tb_z100_tile_reuse_sync_fixture", "-s", "sync_fixture_sim"]),
        ("xsim", [str(xsim), "sync_fixture_sim", "-runall"]),
    ]
    results = []
    parsed: dict[str, int | str] | None = None
    for name, command in phases:
        result = run_command(command, work, evidence / f"{name}.log")
        results.append({key: value for key, value in result.items() if key != "output"})
        if result["return_code"] != 0:
            return {"status": "FAIL", "failed_phase": name, "phases": results}
        if name == "xsim":
            matches = re.findall(
                r"SYNC_FIXTURE_SIM_PASS cycles=(\d+) changes=(\d+) signature=([0-9a-fA-F]{8})",
                result["output"],
            )
            if len(matches) != 1 or "SYNC_FIXTURE_SIM_FAIL" in result["output"]:
                return {"status": "FAIL", "failed_phase": name, "reason": "simulation pass marker missing or duplicated", "phases": results}
            cycles, changes, signature = matches[0]
            parsed = {"status": "PASS", "cycles": int(cycles), "changes": int(changes), "signature": signature}
            if parsed["cycles"] != 800 or parsed["changes"] < 8 or int(signature, 16) == 0:
                return {"status": "FAIL", "failed_phase": name, "reason": "simulation observability criteria failed", "phases": results, **parsed}
    assert parsed is not None
    return {**parsed, "phases": results}


def validate_old_audit() -> dict[str, Any]:
    summary_path = AUDIT_DIR / "audit_summary.txt"
    if not summary_path.is_file() or not OLD_DCP.is_file():
        raise FileNotFoundError("Read-only old routed-DCP audit or its source checkpoint is missing")
    dcp_sha = sha256(OLD_DCP)
    core_sha = sha256(CORE_DIR / "z100_tile_reuse_core.v")
    text = summary_path.read_text(encoding="utf-8")
    if dcp_sha != OLD_DCP_SHA256 or core_sha != OLD_CORE_SHA256:
        raise ValueError("Old DCP or reuse-core identity changed since the audited baseline")
    required_lines = (
        "CLOCK core_clk PERIOD_NS 10.000 SOURCE clk",
        "BUFG_CELL_COUNT 0",
        "ALL_FAILING_HOLD_PATH_COUNT 1370",
        "INTERNAL_FAILING_HOLD_PATH_COUNT 0",
    )
    if any(line not in text for line in required_lines):
        raise ValueError("Old DCP audit no longer shows the recorded boundary-only hold failures")
    return {
        "checkpoint": str(OLD_DCP),
        "checkpoint_sha256": dcp_sha,
        "core_sha256": core_sha,
        "clock_period_ns": 10.0,
        "bufg_cells": 0,
        "all_failing_hold_paths": 1370,
        "internal_failing_hold_paths": 0,
        "audit_summary": str(summary_path),
        "failing_paths_report": str(AUDIT_DIR / "all_failing_min_paths.rpt"),
        "internal_min_paths_report": str(AUDIT_DIR / "internal_min_paths.rpt"),
        "clock_networks_report": str(AUDIT_DIR / "clock_networks.rpt"),
    }


def source_hashes() -> dict[str, str]:
    paths = [
        CORE_DIR / "z100_tile_reuse_core.v",
        FIXTURE_DIR / "z100_tile_reuse_sync_fixture_top.v",
        FIXTURE_DIR / "tb_z100_tile_reuse_sync_fixture.sv",
        FIXTURE_DIR / "sim_bufg.v",
        FIXTURE_DIR / "sync_constraints.xdc",
        FIXTURE_DIR / "sync_impl.tcl",
        Path(__file__).resolve(),
    ]
    return {str(path.relative_to(ROOT)): sha256(path) for path in paths}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frequency", type=int, choices=(100, 200), default=100)
    parser.add_argument("--vivado", type=Path, default=VIVADO_DEFAULT)
    parser.add_argument("--simulate-only", action="store_true")
    parser.add_argument("--skip-simulation", action="store_true")
    args = parser.parse_args(argv)
    if args.simulate_only and args.skip_simulation:
        parser.error("--simulate-only and --skip-simulation are mutually exclusive")
    vivado = args.vivado.resolve()
    if not vivado.is_file():
        parser.error(f"Vivado launcher not found: {vivado}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    evidence_dir = EVIDENCE_ROOT / run_id
    build_dir = BUILD_ROOT / run_id / f"{args.frequency}mhz"
    evidence_dir.mkdir(parents=True, exist_ok=False)
    launch_sources = source_hashes()
    base: dict[str, Any] = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": "xc7z100ffg900-2",
        "frequency_mhz": args.frequency,
        "vivado_launcher": str(vivado),
        "source_sha256_at_launch": launch_sources,
        "source_sha256": launch_sources,
        "old_dcp_audit": validate_old_audit(),
        "scope": "isolated synchronous timing fixture; no production bridge, board, or FPS claim",
        "build_dir": str(build_dir),
    }

    if args.skip_simulation:
        simulation: dict[str, Any] = {"status": "SKIPPED_BY_REQUEST"}
    else:
        simulation = run_simulation(run_id, vivado)
    base["simulation"] = {key: value for key, value in simulation.items() if key != "phases"}
    base["simulation_phases"] = simulation.get("phases", [])
    if args.simulate_only:
        base["source_sha256"] = source_hashes()
        base["status"] = "SIMULATION_PASS" if simulation.get("status") == "PASS" else "SIMULATION_FAIL"
        (evidence_dir / "manifest.json").write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(base, indent=2))
        return 0 if base["status"] == "SIMULATION_PASS" else 1

    if simulation.get("status") != "PASS" and not args.skip_simulation:
        base["source_sha256"] = source_hashes()
        base["status"] = "SIMULATION_FAIL"
        (evidence_dir / "manifest.json").write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(base, indent=2))
        return 1

    command = [
        str(vivado),
        "-mode",
        "batch",
        "-source",
        str(FIXTURE_DIR / "sync_impl.tcl"),
        "-tclargs",
        str(args.frequency),
        str(build_dir),
        str(evidence_dir),
    ]
    impl = run_command(command, ROOT, evidence_dir / "vivado_impl.log")
    base["implementation"] = {key: value for key, value in impl.items() if key != "output"}
    base["vivado_version"] = next(
        (match.group(1) for match in [re.search(r"Vivado v([0-9.]+)", impl["output"])] if match), None
    )
    try:
        metrics = parse_sync_result(impl["output"])
        route = parse_route_status((evidence_dir / "route_status.rpt").read_text(encoding="utf-8"))
        check = parse_check_timing((evidence_dir / "check_timing_routed.rpt").read_text(encoding="utf-8"))
        base["metrics"] = metrics
        base["route_status"] = route
        base["check_timing"] = check
        base["timing_reports"] = {
            "summary": str(evidence_dir / "timing_routed.rpt"),
            "internal_max_paths": str(evidence_dir / "internal_max_paths.rpt"),
            "internal_min_paths": str(evidence_dir / "internal_min_paths.rpt"),
            "all_failing_min_paths": str(evidence_dir / "all_failing_min_paths.rpt"),
            "output_max_paths": str(evidence_dir / "output_max_paths.rpt"),
            "clock_networks": str(evidence_dir / "clock_networks.rpt"),
            "drc": str(evidence_dir / "drc_routed.rpt"),
        }
        if impl["return_code"] != 0:
            base["status"] = "VIVADO_IMPLEMENTATION_FAILED"
        else:
            base["status"] = classify_run(metrics, route, check, simulation)
    except (OSError, ValueError) as exc:
        base["status"] = "EVIDENCE_PARSE_FAILED"
        base["parse_error"] = str(exc)
    base["source_sha256"] = source_hashes()
    (evidence_dir / "manifest.json").write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(base, indent=2))
    return 0 if base["status"] == "PASS_SYNC_FIXTURE_TIMING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
