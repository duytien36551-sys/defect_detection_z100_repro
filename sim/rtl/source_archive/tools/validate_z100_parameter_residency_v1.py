#!/usr/bin/env python3
"""Compile and simulate the source-bound parameter residency candidate."""

from __future__ import annotations

import hashlib
import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "deployment/hardware/z100_2026/parameter_residency_v1/z100_parameter_residency_v1.sv"
TB = ROOT / "deployment/hardware/z100_2026/parameter_residency_v1/tb_z100_parameter_residency_v1.sv"
IVERILOG = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64/bin/iverilog.exe"
VVP = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64/bin/vvp.exe"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-resident", action="store_true",
                        help="Validate the isolated native resident RTL and ownership regression fixture")
    args = parser.parse_args()
    rtl, tb = RTL, TB
    if args.native_resident:
        candidate = ROOT / "deployment/hardware/z100_2026/native_conv_backend_v3_resident"
        rtl, tb = candidate / RTL.name, candidate / TB.name
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = ROOT / "validation/board_z100/parameter_residency_v1" / stamp
    out.mkdir(parents=True, exist_ok=False)
    binary = out / "parameter_residency.vvp"
    compile_log = out / "iverilog.log"
    run_log = out / "vvp.log"
    report = {
        "schema": "z100-parameter-residency-validation/1",
        "status": "RUNNING",
        "board_access": False,
        "synthesis_executed": False,
        "rtl_integrated": False,
        "full_pipeline_30fps_accepted": False,
        "native_resident_candidate": args.native_resident,
        "source_sha256_before": {str(path.relative_to(ROOT)): sha256(path) for path in (rtl, tb, Path(__file__))},
        "commands": [],
        "scope_limits": [
            "module-level Icarus simulation only",
            "one-entry event-local cache module; backend execution is not exercised",
            "no DDR bandwidth, timing, resource, or board result",
        ],
    }
    snapshots = out / "sources"
    snapshots.mkdir()
    for path in (rtl, tb, Path(__file__)):
        shutil.copyfile(path, snapshots / path.name)
    report["source_snapshots"] = {
        str(path.relative_to(ROOT)): str((snapshots / path.name).relative_to(ROOT))
        for path in (rtl, tb, Path(__file__))
    }
    report["tool_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path) for path in (IVERILOG, VVP) if path.is_file()
    }
    compile_cmd = [str(IVERILOG), "-g2012", "-Wall", "-s", "tb_z100_parameter_residency_v1",
                   "-o", str(binary), str(rtl), str(tb)]
    if not IVERILOG.is_file() or not VVP.is_file():
        report["status"] = "UNAVAILABLE_LOCAL_SIMULATOR"
        report["errors"] = ["Pinned Icarus/VVP executable is missing"]
    else:
        compiled = subprocess.run(compile_cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        compile_log.write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
        report["commands"].append({"label": "iverilog", "argv": compile_cmd,
                                    "return_code": compiled.returncode,
                                    "log": str(compile_log.relative_to(ROOT))})
        if compiled.returncode == 0:
            executed = subprocess.run([str(VVP), str(binary)], cwd=ROOT,
                                      capture_output=True, text=True, check=False)
            run_log.write_text(executed.stdout + executed.stderr, encoding="utf-8")
            report["commands"].append({"label": "vvp", "argv": [str(VVP), str(binary)],
                                        "return_code": executed.returncode,
                                        "log": str(run_log.relative_to(ROOT))})
            report["simulation_output"] = executed.stdout.strip()
            report["status"] = (
                "PASS_MODULE_HANDSHAKE_HIT_MISS_INVALIDATION_SIMULATION_ONLY"
                if executed.returncode == 0 and "Z100_PARAMETER_RESIDENCY_V1_PASS" in executed.stdout
                else "FAILED_SIMULATION"
            )
        else:
            report["status"] = "FAILED_COMPILE"
    report["source_sha256_after"] = {str(path.relative_to(ROOT)): sha256(path) for path in (rtl, tb, Path(__file__))}
    report["source_inputs_unchanged"] = (
        report["source_sha256_before"] == report["source_sha256_after"]
    )
    report["artifact_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in out.rglob("*") if path.is_file()
    }
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(out / "result.json"),
                      "simulation_output": report.get("simulation_output", "")}))
    return 0 if report["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())

