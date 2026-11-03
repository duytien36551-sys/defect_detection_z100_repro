#!/usr/bin/env python3
"""Run the isolated Z100 tap/site reuse-core simulation and OOC flow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "deployment/hardware/z100_2026/tile_reuse_core_v0"
BUILD_ROOT = ROOT / "deployment/build/z100_reuse_core_v0"
EVIDENCE_ROOT = ROOT / "validation/board_z100/reuse_core_v0"
VIVADO_DEFAULT = Path(r"C:\appload\2026.1\Vivado\bin\vivado.bat")
METRIC_RE = re.compile(r"^METRIC\s+(.*)$", re.MULTILINE)
FIELD_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^\s]+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_metrics(text: str) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for line in METRIC_RE.findall(text):
        row: dict[str, Any] = {}
        for key, value in FIELD_RE.findall(line):
            try:
                row[key] = int(value)
            except ValueError:
                row[key] = value
        if row:
            metrics.append(row)
    return metrics


def parse_sim_output(text: str) -> dict[str, Any]:
    if "FAIL:" in text or "global simulation timeout" in text:
        raise ValueError("xsim log contains a self-check failure")
    pass_match = re.search(r"SIM_PASS\s+jobs=(\d+)\s+preload_cycles=(\d+)\s+sim_cycles=(\d+)", text)
    if not pass_match:
        raise ValueError("xsim log is missing the SIM_PASS completion marker")
    metrics = parse_metrics(text)
    if not metrics:
        raise ValueError("xsim log contains no per-job cycle metrics")
    for row in metrics:
        taps = row["taps"]
        groups = (taps + 3) // 4
        if row["groups"] != groups or row["issue_cycles"] != groups:
            raise ValueError(f"group count disagrees with ceil(taps/4): {row}")
        if row["pipeline_flush"] != 3:
            raise ValueError(f"pipeline drain is not three measured cycles: {row}")
        if row["start_to_result"] != groups + 3:
            raise ValueError(f"start-to-result cycle formula mismatch: {row}")
        if row["readback_handshakes"] != row["sites"]:
            raise ValueError(f"readback count differs from active sites: {row}")
    jobs, preload_cycles, sim_cycles = (int(value) for value in pass_match.groups())
    if jobs != len(metrics):
        raise ValueError(f"reported jobs={jobs} but parsed {len(metrics)} metrics")
    return {
        "status": "PASS",
        "jobs": jobs,
        "preload_cycles": preload_cycles,
        "simulation_cycles": sim_cycles,
        "metrics": metrics,
        "cases_passed": len(re.findall(r"^CASE_PASS\b", text, re.MULTILINE)),
        "abort_checks_passed": len(re.findall(r"^ABORT_PASS\b", text, re.MULTILINE)),
    }


def run_command(command: list[str], cwd: Path, log_path: Path) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    quoted = subprocess.list2cmdline(command)
    completed = subprocess.run(
        quoted,
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
        "command_line": quoted,
        "cwd": str(cwd),
        "return_code": completed.returncode,
        "log": str(log_path),
        "warning_mentions": len(re.findall(r"\bWARNING\b", completed.stdout, re.IGNORECASE)),
        "output": completed.stdout,
    }


def vivado_tools(vivado: Path) -> dict[str, Path]:
    vivado = vivado.resolve()
    if not vivado.is_file():
        raise FileNotFoundError(f"Vivado launcher is unavailable: {vivado}")
    bindir = vivado.parent
    tools = {name: bindir / f"{name}.bat" for name in ("xvlog", "xelab", "xsim")}
    tools["vivado"] = vivado
    for name, path in tools.items():
        if not path.is_file():
            raise FileNotFoundError(f"Required Vivado tool {name} is unavailable: {path}")
    return tools


def source_hashes() -> dict[str, str]:
    paths = [
        CORE_DIR / "z100_tile_reuse_core.v",
        CORE_DIR / "tb_z100_tile_reuse_core.sv",
        CORE_DIR / "z100_tile_reuse_core_ooc_top.v",
        CORE_DIR / "ooc_constraints.xdc",
        CORE_DIR / "ooc_impl.tcl",
        Path(__file__).resolve(),
        ROOT / "deployment/tests/test_z100_reuse_core_validation.py",
        ROOT / "docs/z100_reuse_core_v0.md",
    ]
    return {str(path.relative_to(ROOT)): sha256(path) for path in paths}


def run_sim(tools: dict[str, Path], run_id: str, evidence_dir: Path) -> dict[str, Any]:
    work = BUILD_ROOT / run_id / "sim"
    work.mkdir(parents=True, exist_ok=True)
    sources = [
        CORE_DIR / "z100_tile_reuse_core.v",
        CORE_DIR / "tb_z100_tile_reuse_core.sv",
    ]
    phases = [
        ("xvlog", [str(tools["xvlog"]), "-sv", *map(str, sources)]),
        ("xelab", [str(tools["xelab"]), "-mt", "2", "tb_z100_tile_reuse_core", "-s", "reuse_sim"]),
        ("xsim", [str(tools["xsim"]), "reuse_sim", "-runall"]),
    ]
    results: list[dict[str, Any]] = []
    for name, command in phases:
        result = run_command(command, work, evidence_dir / f"{name}.log")
        results.append({key: value for key, value in result.items() if key != "output"})
        if result["return_code"] != 0:
            return {"status": "FAIL", "failed_phase": name, "phases": results}
        if name == "xsim":
            try:
                parsed = parse_sim_output(result["output"])
            except ValueError as exc:
                return {"status": "FAIL", "failed_phase": name, "reason": str(exc), "phases": results}
            (evidence_dir / "sim_metrics.json").write_text(
                json.dumps(parsed, indent=2) + "\n", encoding="utf-8"
            )
            return {"status": "PASS", "phases": results, "summary": parsed}
    return {"status": "FAIL", "reason": "simulation phases did not execute", "phases": results}


def parse_ooc_summary(text: str) -> dict[str, Any] | None:
    matches = re.findall(
        r"REUSE_OOC_RESULT\s+frequency_mhz=(\d+)\s+setup_slack_ns=([^\s]+)\s+hold_slack_ns=([^\s]+)\s+route=([^\s]+)\s+part=([^\s]+)",
        text,
    )
    if not matches:
        return None
    freq, setup, hold, route, part = matches[-1]
    return {
        "frequency_mhz": int(freq),
        "setup_slack_ns": None if setup == "NA" else float(setup),
        "hold_slack_ns": None if hold == "NA" else float(hold),
        "route": route,
        "part": part,
    }


def parse_check_timing_report(text: str, unconstrained_text: str) -> dict[str, Any]:
    categories = {
        "no_clock_register_pins": ("no_clock", (
            r"There are\s+(\d+)\s+register/latch pins with no clock",
        )),
        "constant_clock_register_pins": ("constant_clock", (
            r"There are\s+(\d+)\s+register/latch pins with constant_clock",
        )),
        "pulse_width_clock_pins": ("pulse_width_clock", (
            r"There are\s+(\d+)\s+register/latch pins which need pulse_width check",
        )),
        "unconstrained_internal_endpoints": ("unconstrained_internal_endpoints", (
            r"There are\s+(\d+)\s+pins that are not constrained for maximum delay",
        )),
        "ports_without_input_delay": ("no_input_delay", (
            r"There are\s+(\d+)\s+ports? with no input delay",
            r"There are\s+(\d+)\s+input ports? with no input delay",
            r"There are\s+(\d+)\s+input ports? without (?:an? )?input delay",
        )),
        "ports_without_output_delay": ("no_output_delay", (
            r"There are\s+(\d+)\s+ports? with no output delay",
            r"There are\s+(\d+)\s+output ports? without (?:an? )?output delay",
        )),
        "multiple_clock_register_pins": ("multiple_clock", (
            r"There are\s+(\d+)\s+register/latch pins with multiple clocks",
        )),
        "generated_clocks_without_source": ("generated_clocks", (
            r"There are\s+(\d+)\s+generated clocks that are not connected to a clock source",
        )),
        "combinational_loops": ("loops", (
            r"There are\s+(\d+)\s+combinational loops in the design",
        )),
        "partial_input_delay_ports": ("partial_input_delay", (
            r"There are\s+(\d+)\s+ports? with partial input delay",
            r"There are\s+(\d+)\s+input ports? with partial input delay",
        )),
        "partial_output_delay_ports": ("partial_output_delay", (
            r"There are\s+(\d+)\s+ports? with partial output delay",
        )),
        "latch_loops": ("latch_loops", (
            r"There are\s+(\d+)\s+combinational latch loops in the design",
        )),
    }
    counts: dict[str, int | None] = {}
    for key, (check_name, patterns) in categories.items():
        source = text
        match = re.search(
            rf"checking\s+{re.escape(check_name)}\s+\((\d+)\)",
            source,
            re.IGNORECASE,
        )
        if match:
            counts[key] = int(match.group(1))
            continue
        if key == "unconstrained_internal_endpoints":
            source = unconstrained_text
            match = re.search(
                rf"checking\s+{re.escape(check_name)}\s+\((\d+)\)",
                source,
                re.IGNORECASE,
            )
            if match:
                counts[key] = int(match.group(1))
                continue
        found = None
        for pattern in patterns:
            match = re.search(pattern, source, re.IGNORECASE)
            if match:
                found = int(match.group(1))
                break
        if key == "unconstrained_internal_endpoints" and found is None:
            endpoint_match = re.search(
                r"There are\s+(\d+)\s+(?:internal )?endpoints? which are unconstrained",
                source,
                re.IGNORECASE,
            )
            if endpoint_match:
                found = int(endpoint_match.group(1))
        counts[key] = found
    missing = sorted(key for key, value in counts.items() if value is None)
    nonzero = {key: value for key, value in counts.items() if value not in (None, 0)}
    return {
        "status": "FAIL" if nonzero else ("UNKNOWN" if missing else "PASS"),
        "counts": counts,
        "missing_counts": missing,
        "nonzero_counts": nonzero,
    }


def parse_resource_report(text: str) -> dict[str, int | float]:
    wanted = {
        "Slice LUTs": "LUT",
        "Block RAM Tile": "BRAM36",
        "DSPs": "DSP",
    }
    found: dict[str, int] = {}
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        if len(columns) < 2 or columns[0] not in wanted:
            continue
        numeric = re.match(r"[\d,]+(?:\.\d+)?", columns[1])
        if numeric:
            value = numeric.group(0).replace(",", "")
            found[wanted[columns[0]]] = float(value) if "." in value else int(value)
    return found


def evaluate_resource_screen(resources: dict[str, int | float]) -> dict[str, Any]:
    limits = {"DSP": 1024, "BRAM36": 256, "LUT": 100000}
    missing = sorted(set(limits) - set(resources))
    if missing:
        return {"status": "UNKNOWN", "missing": missing, "limits": limits, "resources": resources}
    over_budget = {name: resources[name] for name, maximum in limits.items() if resources[name] > maximum}
    return {
        "status": "FAIL" if over_budget else "PASS",
        "limits": limits,
        "resources": resources,
        "over_budget": over_budget,
    }


def parse_route_report(text: str) -> dict[str, Any]:
    fields = {}
    for key, label in [('routable', 'routable nets'), ('routed', 'fully routed nets'),
                       ('errors', 'nets with routing errors')]:
        match = re.search(r'# of ' + label + r'\.+\s*:\s*([\d,]+)', text)
        fields[key] = int(match.group(1).replace(',', '')) if match else None
    valid = (all(value is not None for value in fields.values())
             and fields['routable'] > 0 and fields['routable'] == fields['routed']
             and fields['errors'] == 0)
    return dict(status='PASS' if valid else 'FAIL_OR_UNKNOWN', counts=fields)


def parse_design_timing(text: str) -> dict[str, Any]:
    # The twelve-number design summary reports worst/total slack and failing
    # endpoint counts for setup, hold and pulse width. Missing data never passes.
    match = re.search(r'WNS\(ns\).*?WPWS\(ns\).*?\n\s*-[-\s]+\n\s*([^\n]+)', text, re.S)
    if not match:
        return dict(status='UNKNOWN')
    columns = match.group(1).split()
    if len(columns) != 12:
        return dict(status='UNKNOWN', summary_line=match.group(1))
    try:
        values = dict(wns=float(columns[0]), tns=float(columns[1]), setup_failing=int(columns[2]),
                      whs=float(columns[4]), ths=float(columns[5]), hold_failing=int(columns[6]),
                      wpws=float(columns[8]), tpws=float(columns[9]), pulse_failing=int(columns[10]))
    except ValueError:
        return dict(status='UNKNOWN', summary_line=match.group(1))
    passed = all(values[key] >= 0 for key in ('wns', 'whs', 'wpws')) and all(
        values[key] == 0 for key in ('tns', 'ths', 'tpws', 'setup_failing', 'hold_failing', 'pulse_failing'))
    return dict(status='PASS' if passed else 'FAIL', **values)


def run_ooc(tools: dict[str, Path], run_id: str, evidence_dir: Path, frequencies: list[int]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for frequency in frequencies:
        work = BUILD_ROOT / run_id / f"ooc_{frequency}mhz"
        report_dir = evidence_dir / f"ooc_{frequency}mhz"
        work.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(tools["vivado"]),
            "-mode", "batch",
            "-source", str(CORE_DIR / "ooc_impl.tcl"),
            "-tclargs", str(frequency), str(work), str(report_dir),
        ]
        result = run_command(command, work, evidence_dir / f"vivado_{frequency}mhz.log")
        summary = parse_ooc_summary(result["output"])
        results.append({
            "frequency_mhz": frequency,
            "return_code": result["return_code"],
            "warning_mentions": result["warning_mentions"],
            "summary": summary,
            "log": result["log"],
            "command": result["command"],
            "constraints_sha256": source_hashes()[
                str((CORE_DIR / "ooc_constraints.xdc").relative_to(ROOT))
            ],
        })
    completed = [item for item in results if item["return_code"] == 0 and item["summary"]]
    for item in results:
        report_dir = evidence_dir / f"ooc_{item['frequency_mhz']}mhz"
        resource_file = report_dir / "utilization_routed.rpt"
        check_file = report_dir / "check_timing_routed.rpt"
        unconstrained_file = report_dir / "unconstrained_internal_routed.rpt"
        timing_file = report_dir / "timing_routed.rpt"
        route_file = report_dir / "route_status.rpt"
        item['route_validation'] = parse_route_report(route_file.read_text()) if route_file.is_file() else dict(status='UNKNOWN')
        item['design_timing'] = parse_design_timing(timing_file.read_text()) if timing_file.is_file() else dict(status='UNKNOWN')
        if resource_file.is_file():
            resources = parse_resource_report(resource_file.read_text(encoding="utf-8", errors="replace"))
            item["resource_screen"] = evaluate_resource_screen(resources)
            item["routed_resources"] = resources
        else:
            item["resource_screen"] = evaluate_resource_screen({})
        if check_file.is_file() and unconstrained_file.is_file():
            item["routed_check_timing"] = parse_check_timing_report(
                check_file.read_text(encoding="utf-8", errors="replace"),
                unconstrained_file.read_text(encoding="utf-8", errors="replace"),
            )
        else:
            item["routed_check_timing"] = {
                "status": "UNKNOWN",
                "missing_reports": [
                    name for name, path in (
                        ("check_timing_routed.rpt", check_file),
                        ("unconstrained_internal_routed.rpt", unconstrained_file),
                    ) if not path.is_file()
                ],
            }
        summary = item.get("summary")
        checks = item["routed_check_timing"]
        if not summary or checks["status"] == "UNKNOWN" or summary["setup_slack_ns"] is None or summary["hold_slack_ns"] is None or item['design_timing']['status'] == 'UNKNOWN':
            item["timing_closure"] = "UNKNOWN"
        elif checks["status"] == "FAIL" or summary["setup_slack_ns"] < 0 or summary["hold_slack_ns"] < 0 or item['design_timing']['status'] != 'PASS' or item['route_validation']['status'] != 'PASS':
            item["timing_closure"] = "FAIL"
        else:
            item["timing_closure"] = "PASS"
        item["routed_timing_report"] = str(timing_file) if timing_file.is_file() else None
    return {
        "status": "PASS" if len(completed) == len(frequencies) and all(x['route_validation']['status']=='PASS' for x in results) else "INCOMPLETE",
        "runs": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "sim", "ooc"), default="all")
    parser.add_argument("--vivado", type=Path, default=Path(os.environ.get("VIVADO_BAT", VIVADO_DEFAULT)))
    parser.add_argument("--frequencies", type=int, nargs="+", choices=(100, 200), default=[200, 100])
    args = parser.parse_args(argv)

    if os.name != "nt":
        parser.error("This validation driver requires Windows Vivado .bat launchers")
    tools = vivado_tools(args.vivado)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    evidence_dir = EVIDENCE_ROOT / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "vivado_launcher": str(args.vivado.resolve()),
        "device": "xc7z100ffg900-2",
        "simulation_seed": "0x51f15eed (xorshift32 in the SystemVerilog adapter)",
        "source_sha256": source_hashes(),
        "commands": [],
        "sim": None,
        "ooc": None,
    }
    manifest_path = evidence_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if args.mode in ("all", "sim"):
        manifest["sim"] = run_sim(tools, run_id, evidence_dir)
        if manifest["sim"]["status"] != "PASS":
            manifest["status"] = "SIM_FAIL"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            print(f"SIM_FAIL evidence={evidence_dir}")
            return 1
    if args.mode in ("all", "ooc"):
        manifest["ooc"] = run_ooc(tools, run_id, evidence_dir, args.frequencies)

    if args.mode == "all":
        manifest["status"] = (
            "SIM_PASS_OOC_RUNS_COMPLETE"
            if manifest["ooc"]["status"] == "PASS"
            else "SIM_PASS_OOC_INCOMPLETE"
        )
    elif args.mode == "sim":
        manifest["status"] = "SIM_PASS"
    else:
        manifest["status"] = "OOC_RUNS_COMPLETE" if manifest["ooc"]["status"] == "PASS" else "OOC_INCOMPLETE"

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{manifest['status']} evidence={evidence_dir}")
    return 0 if manifest["status"] in {"SIM_PASS", "OOC_RUNS_COMPLETE", "SIM_PASS_OOC_RUNS_COMPLETE"} else 2


if __name__ == "__main__":
    sys.exit(main())
