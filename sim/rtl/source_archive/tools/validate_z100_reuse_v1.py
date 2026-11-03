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
CORE_DIR = ROOT / "deployment/hardware/z100_2026/tile_reuse_core_v1"
BUILD_ROOT = ROOT / "deployment/build/z100_reuse_core_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/reuse_core_v1"
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
        if row["pipeline_flush"] != 4:
            raise ValueError(f"pipeline drain is not four measured cycles: {row}")
        if row["start_to_result"] != groups + 4:
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
        ROOT / "docs/z100_reuse_core_v1.md",
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


def main():
    import uuid
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    evidence=EVIDENCE_ROOT/run_id;evidence.mkdir(parents=True)
    sources=[CORE_DIR/'z100_tile_reuse_core.v',CORE_DIR/'tb_z100_tile_reuse_core.sv',Path(__file__)]
    before={str(p.relative_to(ROOT)):sha256(p) for p in sources}
    tools={name:VIVADO_DEFAULT.parent/(name+'.bat') for name in ('xvlog','xelab','xsim')}
    result=run_sim(tools,run_id,evidence)
    if before!={str(p.relative_to(ROOT)):sha256(p) for p in sources}:raise ValueError('Sources changed')
    if result.get('status')=='PASS' and result['summary']['abort_checks_passed']!=8:
        result['status']='FAIL';result['reason']='Eight per-stage reset/cancel checks required'
    report=dict(status=result['status'],run_id=run_id,source_sha256=before,simulation=result,
                release_eligible=False,physical_board_tested=False,fps_measured=False)
    (evidence/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],report=str(evidence/'manifest.json'),reason=result.get('reason'))))
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
