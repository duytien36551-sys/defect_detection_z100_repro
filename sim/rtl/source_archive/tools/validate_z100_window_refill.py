"""Run the isolated one-row refill ownership RTL under Vivado 2026.1 XSim."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RTL_DIR = ROOT / "deployment/hardware/z100_2026/window_refill_v1"
RTL = RTL_DIR / "z100_window_refill_slot.sv"
TB = RTL_DIR / "tb_z100_window_refill_slot.sv"
VALIDATOR = Path(__file__).resolve()
TEST = ROOT / "deployment/tests/test_z100_window_refill.py"
DOC = ROOT / "docs/z100_window_refill.md"
SOURCE_FILES = (RTL, TB, VALIDATOR, TEST, DOC)
BUILD_ROOT = ROOT / "deployment/build/z100_window_refill_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/window_refill_v1"
VIVADO_BIN = Path(r"C:\appload\2026.1\Vivado\bin")
EXPECTED_BUILD = "6511674"
EXPECTED_SIM_METRICS = {
    "cancel_filling": 1,
    "cancel_in_use": 1,
    "generation_wrap": 1,
    "reset_filling": 1,
    "reset_in_use": 1,
    "reset_ready": 1,
    "same_address_dual": 1,
}


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest() -> dict[str, str]:
    missing = [str(path) for path in SOURCE_FILES if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing window-refill source(s): " + ", ".join(missing))
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in SOURCE_FILES}


def parse_sim_output(output: str) -> dict[str, int]:
    if re.search(r"(?im)^(?:FAIL:|FATAL:|ERROR:)", output):
        raise ValueError("XSim output contains a failure marker")
    matches = re.findall(
        r"(?m)^WINDOW_REFILL_SIM_PASS accepted_reads=(\d+) consumed_reads=(\d+) "
        r"randomized_stall_cycles=(\d+) cancel_filling=(\d+) cancel_ready=(\d+) "
        r"cancel_in_use=(\d+) reset_filling=(\d+) reset_ready=(\d+) reset_in_use=(\d+) "
        r"generation_wrap=(\d+) wrong_order_rejects=(\d+) ownership_rejects=(\d+) "
        r"same_address_dual=(\d+)\s*$", output)
    if len(matches) != 1:
        raise ValueError(f"expected one anchored WINDOW_REFILL_SIM_PASS summary, got {len(matches)}")
    names = (
        "accepted_reads", "consumed_reads", "randomized_stall_cycles", "cancel_filling",
        "cancel_ready", "cancel_in_use", "reset_filling", "reset_ready", "reset_in_use",
        "generation_wrap", "wrong_order_rejects", "ownership_rejects", "same_address_dual",
    )
    metrics = dict(zip(names, (int(value) for value in matches[0])))
    if metrics["accepted_reads"] < 32 or metrics["consumed_reads"] < 32:
        raise ValueError("read scoreboard covered too few handshakes")
    if metrics["randomized_stall_cycles"] < 3:
        raise ValueError("read-result backpressure coverage is missing")
    if metrics["cancel_ready"] < 2 or metrics["wrong_order_rejects"] < 2 or metrics["ownership_rejects"] < 3:
        raise ValueError("cancel or rejection coverage is below the declared minimum")
    for key, expected in EXPECTED_SIM_METRICS.items():
        if metrics[key] != expected:
            raise ValueError(f"simulation metric {key}={metrics[key]}, expected {expected}")
    edges=re.findall(r'^WINDOW_REFILL_EDGE_SCORE accepted=(\d+) consumed=(\d+) aborted=(\d+) pending=(\d+)\s*$',output,re.M)
    if len(edges)!=1:raise ValueError('Missing independent edge scoreboard')
    accepted,consumed,aborted,pending=map(int,edges[0])
    if accepted!=consumed+aborted+pending or pending!=0 or aborted!=2:
        raise ValueError('Read ownership conservation or abort count failed')
    if accepted!=metrics['accepted_reads'] or consumed!=metrics['consumed_reads']:
        raise ValueError('Independent edge scoreboard differs from summary')
    metrics.update(aborted_reads=aborted,pending_reads=pending)
    return metrics


def _run(command: list[str], cwd: Path, log_path: Path, commands: list[dict[str, Any]]) -> str:
    import os
    import subprocess

    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    started = datetime.now(timezone.utc).isoformat()
    import subprocess
    completed = subprocess.run(subprocess.list2cmdline(command), cwd=cwd, env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=300, check=False, shell=True, encoding="utf-8", errors="replace")
    output = completed.stdout or ""
    log_path.write_text(output, encoding="utf-8", errors="replace")
    commands.append({
        "command": command,
        "cwd": cwd.relative_to(ROOT).as_posix(),
        "started_utc": started,
        "return_code": completed.returncode,
        "log": log_path.relative_to(ROOT).as_posix(),
        "log_sha256": sha256(log_path),
    })
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {Path(command[0]).name} returned {completed.returncode}")
    return output


def run_validation(run_id: str | None = None) -> Path:
    identity = run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", identity):
        raise ValueError("run id must contain 8-64 safe filename characters")
    evidence = EVIDENCE_ROOT / identity
    build = BUILD_ROOT / identity
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)

    before = source_manifest()
    report: dict[str, Any] = {
        "run_id": identity,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "source_sha256": before,
        "scope": {
            "row_slots": 1,
            "data_width_bits": 32,
            "slot_depth_words": 16,
            "synchronous_read_ports": 2,
            "reorder_or_axi_scheduler": False,
            "full_32_bank_mapping": False,
            "synthesis_run": False,
            "route_run": False,
            "full_graph_implemented": False,
            "timing_accepted": False,
            "physical_board_tested": False,
        },
        "resource_result": None,
        "timing_result": None,
    }
    commands: list[dict[str, Any]] = []
    logs = []
    try:
        # The installed version-only launcher consistently returns1, including
        # the retained baseline. Reuse its explicitly identified banner, not a
        # failed command as a successful build. All actual simulator commands
        # below must return0 and identify their version independently.
        version_log = EVIDENCE_ROOT / '20261022T073446Z_3a1d6cd9/vivado_version.log'
        if sha256(version_log) != 'd9c5f86048682884b08d8713000cc82096a8e28a15b2910f4b351d6e3e7843dd':
            raise RuntimeError('Retained version banner changed')
        launcher = VIVADO_BIN / 'vivado.bat'
        if sha256(launcher) != 'a5f91ee867cea61be4355caf9f7a784c6c34351c5c1d1618562ddda299e38a8b':
            raise RuntimeError('Vivado launcher differs from retained version identity')
        version_output = version_log.read_text(encoding='utf-8')
        version_match = re.search(r"(?im)^vivado v(\S+) \(64-bit\)", version_output)
        build_match = re.search(r"(?im)^SW Build (\d+)", version_output)
        if (not version_match or version_match.group(1) != "2026.1" or
                not build_match or build_match.group(1) != EXPECTED_BUILD):
            raise RuntimeError("installed Vivado version/build did not match pinned 2026.1 toolchain")
        report["toolchain"] = {"name": "Vivado", "version": version_match.group(1), "build": build_match.group(1)}
        report['toolchain']['retained_banner'] = version_log.relative_to(ROOT).as_posix()
        report['toolchain']['retained_banner_sha256'] = sha256(version_log)
        report['toolchain']['launcher_sha256'] = sha256(launcher)
        report['toolchain']['version_only_exit_code'] = 1
        report['toolchain']['version_command_rerun'] = False

        calls = (
            ("xvlog", [str(VIVADO_BIN / "xvlog.bat"), "-sv", str(RTL), str(TB)]),
            ("xelab", [str(VIVADO_BIN / "xelab.bat"), "-mt", "2", "tb_z100_window_refill_slot",
                        "-s", "window_refill_slot_sim"]),
            ("xsim", [str(VIVADO_BIN / "xsim.bat"), "window_refill_slot_sim", "-runall"]),
        )
        outputs: dict[str, str] = {}
        for name, command in calls:
            output = _run(command, build, evidence / f"{name}.log", commands)
            outputs[name] = output
            logs.append(output)
            # xvlog reports VRFC compilation records, without a version banner;
            # xelab and xsim identify the running simulator version.
            if name != 'xvlog' and "Vivado Simulator v2026.1" not in output:
                raise RuntimeError(f"{name} log does not identify Vivado Simulator v2026.1")
        simulation = parse_sim_output(outputs["xsim"])
        report["simulation"] = {
            "status": "PASS_SCOREBOARD_AND_OWNERSHIP",
            "metrics": simulation,
            "checks": [
                "full sequential refill before commit",
                "explicit early commit, wrong row, out-of-order and duplicate-write rejection",
                "independent same-address dual-read scoreboard",
                "randomized per-port output backpressure with stable data and generation tags",
                "read ownership excludes writes, begin and release while results are pending",
                "8-bit generation wrap paired with changing absolute row identity",
                "cancel and reset from FILLING, READY and IN_USE, including stalled results",
            ],
        }
        after = source_manifest()
        if after != before:
            raise RuntimeError("bound source changed during XSim validation")
        report["source_sha256_after"] = after
        artifact_paths = sorted(path for path in build.rglob("*") if path.is_file())
        artifact_paths.extend(path for path in evidence.glob("*.log") if path.is_file())
        report["artifact_sha256"] = {
            path.relative_to(ROOT).as_posix(): sha256(path) for path in artifact_paths
        }
        report["commands"] = commands
        report["status"] = "XSim_PASS_SINGLE_ROW_SLOT_SCOPE_ONLY"
    except Exception as exc:  # Preserve logs and a terminal report for every allocated run.
        report["status"] = "FAILED"
        report["failure"] = f"{type(exc).__name__}: {exc}"
        report["commands"] = commands
        try:
            report["source_sha256_after"] = source_manifest()
        except Exception as source_exc:
            report["source_manifest_failure"] = f"{type(source_exc).__name__}: {source_exc}"
        report["artifact_sha256"] = {
            path.relative_to(ROOT).as_posix(): sha256(path)
            for path in sorted([*build.rglob("*"), *evidence.glob("*.log")]) if path.is_file()
        }
    report_path = evidence / "result.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="optional unique evidence directory name")
    args = parser.parse_args()
    try:
        path = run_validation(args.run_id)
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WINDOW_REFILL_VALIDATION_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "report": path.relative_to(ROOT).as_posix()}, indent=2))
    return 0 if report["status"] == "XSim_PASS_SINGLE_ROW_SLOT_SCOPE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
