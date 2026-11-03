#!/usr/bin/env python3
"""Run a bounded Icarus integration harness for the real parameter-loader RTL.

The testbench instantiates the real guard and parameter reader. Its AXI read
source and configuration bridge are protocol models, so this is not DDR,
full-backend quiet-fence, numeric Conv, Vivado, or board evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
GUARD_DIR = HW / "native_conv_backend_v3_resident_guard_v2"
TEST_DIR = HW / "guard_loader_integration_test"
GUARD_RTL = GUARD_DIR / "z100_parameter_residency_guard_v2.sv"
LOADER_RTL = HW / "native_parameter_reader_v1/z100_native_parameter_reader.sv"
TB = TEST_DIR / "tb_z100_guard_parameter_loader_integration.sv"
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64"
EVIDENCE_ROOT = ROOT / "validation/board_z100/guard_loader_integration"
EXPECTED = {
    GUARD_RTL: "9e58d3048e45cc70fedc3c29f76669661fd9ac33c66455070140422c36080617",
    LOADER_RTL: "bf6779eded3740c57140526681f0f403964b6c54836076d469a25499bc1914a4",
}
PASS = "Z100_GUARD_PARAMETER_LOADER_INTEGRATION_PASS"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def run(name: str, argv: list[str], output: Path) -> dict[str, object]:
    try:
        proc = subprocess.run(
            argv, cwd=str(ROOT), text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
        )
        output.write_text(proc.stdout, encoding="utf-8")
        return {"name": name, "argv": argv, "return_code": proc.returncode,
                "log": rel(output), "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        output.write_text(str(partial) + "\nTIMEOUT after 180 seconds\n", encoding="utf-8")
        return {"name": name, "argv": argv, "return_code": None,
                "log": rel(output), "timed_out": True}


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence = EVIDENCE_ROOT / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    report: dict[str, object] = {
        "schema": "z100-guard-parameter-loader-integration/1",
        "status": "RUNNING",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": [
            "actual z100_parameter_residency_guard_v2 RTL",
            "actual z100_native_parameter_reader RTL",
            "protocol-model AXI read source with held-response drain",
            "protocol-model config bridge with ready/response handshake",
        ],
        "coverage": [
            "guard miss forwards a command into the real parameter loader",
            "loader config request stays stable during bridge backpressure",
            "loader reads all four parameter segments and emits completion",
            "guard retains the loader's one-cycle done pulse under consumer backpressure",
            "resident hit avoids starting another parameter-loader job",
            "cancel clears the cached job while an AXI response is still owned",
            "replacement request waits until the modeled outstanding read drains",
        ],
        "limits": [
            "AXI read source and configuration bridge are testbench protocol models",
            "quiet fence is only the modeled reader-busy component, not backend all_io_quiet",
            "no numeric parameter/Conv output comparison or physical DDR validation",
            "guard interface does not include parameter directory/content version; a same-key directory change is outside this test and remains a cache-identity risk",
            "no Vivado synthesis/route, board access, full graph, FPS, or performance acceptance",
        ],
        "board_access": False,
        "vivado_run": False,
        "commands": [],
        "issues": [],
    }
    try:
        compiler = LOCAL / "bin/iverilog.exe"
        vvp = LOCAL / "bin/vvp.exe"
        lib = LOCAL / "lib/ivl"
        for path in (compiler, vvp, lib, GUARD_RTL, LOADER_RTL, TB):
            if not path.exists():
                raise FileNotFoundError(f"required validation input missing: {path}")
        source_hashes = {rel(path): sha256(path) for path in (GUARD_RTL, LOADER_RTL, TB)}
        for path, expected in EXPECTED.items():
            if source_hashes[rel(path)] != expected:
                raise RuntimeError(f"pinned input changed: {rel(path)}")
        report["source_sha256"] = source_hashes

        binary = evidence / "guard_parameter_loader_integration.vvp"
        compile_argv = [
            str(compiler), "-B", str(lib), "-g2012", "-Wall", "-s",
            "tb_z100_guard_parameter_loader_integration", "-o", str(binary),
            str(GUARD_RTL), str(LOADER_RTL), str(TB),
        ]
        compile_result = run("compile", compile_argv, evidence / "compile.log")
        report["commands"].append(compile_result)
        if compile_result["return_code"] != 0 or not binary.is_file():
            raise RuntimeError("Icarus compilation failed")

        sim_argv = [str(vvp), str(binary)]
        sim_result = run("simulation", sim_argv, evidence / "simulation.log")
        report["commands"].append(sim_result)
        sim_output = (evidence / "simulation.log").read_text(encoding="utf-8")
        report["simulation_output"] = sim_output.strip()
        if (sim_result["return_code"] != 0 or sim_result["timed_out"] or
                sim_output.count(PASS) != 1 or re.search(r"FAIL |_FAIL", sim_output)):
            raise RuntimeError("integration testbench assertions failed")
        report["status"] = "PASS_REAL_LOADER_RTL_HARNESS_ONLY"
    except Exception as exc:  # always retain the partial evidence
        report["status"] = "FAIL_CLOSED"
        report["issues"] = [f"{type(exc).__name__}: {exc}"]

    report["artifact_sha256"] = {
        rel(path): sha256(path) for path in evidence.iterdir() if path.is_file()
    }
    result_path = evidence / "result.json"
    result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "result": rel(result_path),
                      "issues": report["issues"]}, indent=2))
    return 0 if report["status"] == "PASS_REAL_LOADER_RTL_HARNESS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
