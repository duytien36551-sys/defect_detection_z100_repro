"""Run the focused dual-bank ownership/cancel-drain regression against the real RTL.

The RTL DUT is actual. Loader, compute, and write-drain peers are synthetic
handshake/ownership models. This is not numerical inference, DDR traffic,
Vivado implementation, board acceptance, or an FPS measurement.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "deployment/hardware/z100_2026/conv_prefetch_control_v2/z100_conv_prefetch_control_v2.sv"
TB = ROOT / "deployment/hardware/z100_2026/bank_overlap_followup/tb_z100_bank_overlap_followup.sv"
SIM_ROOT = ROOT / "deployment/build/local_tools/iverilog13_msys2"
SIM_BIN = SIM_ROOT / "ucrt64/bin"
SIM_LIB = SIM_ROOT / "ucrt64/lib/ivl"
IVERILOG = SIM_BIN / "iverilog.exe"
VVP = SIM_BIN / "vvp.exe"
IVL_RUNTIME = SIM_LIB / "ivl.exe"
SIM_MANIFEST = SIM_ROOT / "manifest.json"
BASELINE = ROOT / "validation/board_z100/icarus_control/20261026T011555.727758Z/result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalized_sources(source_map: dict) -> dict[str, str]:
    return {str(name).replace("\\", "/"): value for name, value in source_map.items()}


def run(label: str, argv: list[str], cwd: Path, log_path: Path, result: dict) -> str:
    process = subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log_path.write_text(process.stdout, encoding="utf-8", errors="replace")
    result["commands"].append({
        "label": label,
        "argv": argv,
        "cwd": str(cwd.relative_to(ROOT)),
        "return_code": process.returncode,
        "log": str(log_path.relative_to(ROOT)),
    })
    require(process.returncode == 0, f"{label} exited with {process.returncode}")
    return process.stdout


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    generated_at = datetime.now(timezone.utc).isoformat()
    output = ROOT / "validation/board_z100/bank_overlap_followup" / stamp
    build = ROOT / "build/z100_bank_overlap_followup" / stamp
    output.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report_path = output / "result.json"

    result: dict = {
        "status": "RUNNING",
        "generated_at_utc": generated_at,
        "dut": str(RTL.relative_to(ROOT)),
        "testbench": str(TB.relative_to(ROOT)),
        "build_dir": str(build.relative_to(ROOT)),
        "commands": [],
        "scope": (
            "Directed dynamic test of the actual z100_conv_prefetch_control_v2 RTL. "
            "Loader, compute and output-writer peers are synthetic handshake/ownership models. "
            "Covers same-bank descriptor blocking across compute and write drain, opposite-bank "
            "load/compute overlap, cancel with both children accepted, staged external drain, "
            "drained recovery gating and same-epoch/job replay rejection."
        ),
        "board_access": False,
        "vivado_started": False,
        "numerical_compute": False,
        "ddr_transactions_executed": False,
        "full_pipeline_30fps_accepted": False,
    }
    source_before: dict[str, str] = {}
    simulator_before: dict[str, str] = {}
    try:
        require(RTL.is_file() and TB.is_file(), "DUT or dedicated testbench missing")
        require(SIM_MANIFEST.is_file(), "project-local Icarus manifest missing")
        require(all(path.is_file() for path in (IVERILOG, VVP, IVL_RUNTIME)),
                "project-local Icarus executable/runtime missing")

        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        require(baseline.get("status") == "PASS_PROJECT_LOCAL_ICARUS_SOURCE_BOUND_CONTROL_TB_ONLY",
                "prior Icarus source-bound controller baseline is unavailable")
        baseline_sources = normalized_sources(baseline.get("source_sha256_after", {}))
        rtl_rel = str(RTL.relative_to(ROOT)).replace("\\", "/")
        require(baseline_sources.get(rtl_rel) == sha256(RTL),
                "current DUT no longer matches the source-bound v3 controller result")

        manifest = json.loads(SIM_MANIFEST.read_text(encoding="utf-8"))
        manifest_files = manifest.get("files")
        require(isinstance(manifest_files, dict), "Icarus manifest file digest map missing")
        simulator_files = {
            IVERILOG: "ucrt64\\bin\\iverilog.exe",
            VVP: "ucrt64\\bin\\vvp.exe",
            IVL_RUNTIME: "ucrt64\\lib\\ivl\\ivl.exe",
        }
        for path, manifest_name in simulator_files.items():
            expected = manifest_files.get(manifest_name)
            require(isinstance(expected, str) and sha256(path) == expected,
                    f"project-local simulator hash mismatch: {manifest_name}")
        source_paths = [Path(__file__).resolve(), TB, RTL, SIM_MANIFEST, BASELINE]
        source_before = {str(path.relative_to(ROOT)): sha256(path) for path in source_paths}
        simulator_before = {str(path.relative_to(ROOT)): sha256(path) for path in simulator_files}
        result.update(
            source_sha256_before=source_before,
            simulator_sha256_before=simulator_before,
            baseline_result=str(BASELINE.relative_to(ROOT)),
            simulator_version="Icarus Verilog 13.0 project-local package",
        )

        version_log = run(
            "iverilog_version",
            [str(IVERILOG), "-V"],
            build,
            output / "iverilog_version.log",
            result,
        )
        require("Icarus Verilog version 13.0" in version_log, "unexpected Icarus version")

        executable = build / "bank_overlap_followup.vvp"
        run(
            "iverilog_compile",
            [
                str(IVERILOG),
                "-B", str(SIM_LIB),
                "-g2012",
                "-s", "tb_z100_bank_overlap_followup",
                "-o", str(executable),
                str(TB),
                str(RTL),
            ],
            build,
            output / "iverilog_compile.log",
            result,
        )
        simulation_log = run(
            "vvp_simulation",
            [str(VVP), "-M", str(SIM_LIB), str(executable)],
            build,
            output / "vvp_simulation.log",
            result,
        )
        markers = re.findall(
            r"^BANK_OVERLAP_FOLLOWUP_PASS (.+)$",
            simulation_log,
            re.M,
        )
        require(len(markers) == 1, "missing or duplicated directed coverage marker")
        coverage = {
            key: int(value)
            for key, value in re.findall(r"([A-Za-z_]+)=(\d+)", markers[0])
        }
        require(
            coverage.get("same_bank_block_cycles", 0) >= 3
            and coverage.get("load_compute_overlap_cycles", 0) >= 2
            and coverage.get("recovery_gate_checks", 0) >= 3
            and coverage.get("drain_phase_checks", 0) >= 2
            and coverage.get("replay_rejected") == 1,
            "directed scenario coverage incomplete",
        )
        result.update(
            status="PASS_ACTUAL_V2_CONTROL_RTL_SYNTHETIC_CHILD_DDR_MODELS",
            simulation=coverage,
        )
    except Exception as exc:
        result.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")

    source_after = {
        name: sha256(ROOT / name)
        for name in source_before
    }
    result["source_sha256_before"] = source_before
    result["source_sha256_after"] = source_after
    if source_before and source_after != source_before:
        result.update(status="FAILED_SOURCE_INTEGRITY", error="source changed during focused validation")
    simulator_after = {
        name: sha256(ROOT / name)
        for name in simulator_before
    }
    result["simulator_sha256_before"] = simulator_before
    result["simulator_sha256_after"] = simulator_after
    if simulator_before and simulator_after != simulator_before:
        result.update(status="FAILED_SIMULATOR_INTEGRITY", error="simulator package changed during focused validation")
    result["artifact_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path)
        for folder in (output, build)
        for path in folder.rglob("*")
        if path.is_file() and path != report_path
    }
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "report": str(report_path.relative_to(ROOT)),
        "error": result.get("error"),
        "simulation": result.get("simulation"),
    }))
    return int(result["status"].startswith("FAILED"))


if __name__ == "__main__":
    raise SystemExit(main())

