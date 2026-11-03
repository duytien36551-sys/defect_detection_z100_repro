"""Run source-bound native Conv MMIO shadow/address boundary tests.

This is a local Icarus frontend test with mocked backend status. It does not
run vendor CAD, actual convolution arithmetic, the board, or the full graph.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from typing import Any

from validate_z100_mac_local_control_v3 import local_runtime, source_key


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
RTL = HW / "native_conv_mmio_v2/z100_native_conv_mmio_v2.sv"
BASE_TB = HW / "native_conv_mmio_v3_validation/tb_z100_native_conv_mmio_v3.sv"
TB = HW / "native_conv_mmio_boundary_v1/tb_z100_native_conv_mmio_boundary_v1.sv"
HEADER = ROOT / "deployment/candidates/pin640/native_dispatch/native_conv_mmio_v1.h"
CONTRACT = ROOT / "docs/z100_native_conv_mmio_contract_v1.md"
DOC = ROOT / "docs/z100_native_conv_mmio_implementation_v1.md"
PRIOR_REPORT = ROOT / (
    "validation/board_z100/native_conv_mmio_v3_validation/"
    "20261026T103701.228464Z_0de16c/result.json"
)
EXPECTED_RTL_SHA = "f9c2ebc336470a2de6053b066a3e09f5a020278a845dc0981016893c55ccd239"
EXPECTED_BASE_TB_SHA = "e760780d185f519939812bcd90a1ddbe37024a7579b785c016f20c7271ae5128"
EXPECTED_HEADER_SHA = "7ab1a3dfc4c95962a873ffa549ece5d30255fd9d91c6109f6f9d9277cd590880"
EXPECTED_CONTRACT_SHA = "97e8b015975a3284af59950b4d24621b1eaf17d95c2ed4bc75c504da152bfbce"
EXPECTED_PRIOR_REPORT_SHA = "13a8fb010f91da724fd6d4a1d82354c12482d7f90bc6df369dff7ffa48878143"
EXPECTED_PRIOR_STATUS = "PASS_LOCAL_FRONTEND_CONTROL_WITH_MOCK_BACKEND_NOT_INTEGRATION"
MAX_WALL_SECONDS = 60
MAX_SIMULATION_PS = 500_000_000

EXPECTED_CASES = [
    (1, 1, 0), (2, 4, 0), (3, 5, 0), (4, 6, 0),
    (5, 2, 0x00000100), (6, 3, 0x83F6CD54),
    (7, 7, 0x0000000F), (8, 7, 0x00000005), (9, 7, 0x00000003),
    (10, 9, 0), (11, 14, 0),
    (12, 8, 0x00100001), (13, 10, 0x00100001), (14, 11, 0x00110001),
    (15, 11, 0x00100000), (16, 8, 0x00110000),
    (17, 13, 0x00200001), (18, 15, 0x00200001), (19, 16, 0x00220001),
    (20, 16, 0x00200000), (21, 13, 0x00220000),
    (22, 12, 2), (23, 12, 1), (24, 17, 2), (25, 17, 1),
    (26, 18, 0x00300001), (27, 19, 0), (28, 19, 174),
    (29, 19, 0x000100AD), (30, 18, 0xFFFFEA80),
    (31, 20, 0x00310001), (32, 21, 0x00310000),
    (33, 22, 2), (34, 22, 1),
    (35, 23, 0), (36, 24, 0), (37, 25, 0), (38, 26, 0),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def decode_sv_literal(token: str) -> int:
    match = re.fullmatch(r"32'([dh])([0-9a-fA-F]+)", token)
    require(match is not None, f"Unsupported boundary test literal: {token}")
    return int(match.group(2), 10 if match.group(1) == "d" else 16)


def verify_matrix_source(text: str) -> list[tuple[int, int, int]]:
    require("module tb_z100_native_conv_mmio_boundary_v1;" in text,
            "Boundary testbench top identity mismatch")
    require("z100_native_conv_mmio_v2 dut (" in text,
            "Boundary tests are not bound to frozen V2 RTL")
    require("initial begin #500000; $fatal(1,\"Frontend MMIO boundary watchdog\"); end" in text,
            "500 us simulation watchdog missing")
    try:
        body = text.split("// Boundary matrix:", 1)[1].split("run_valid_33bit_boundary_case();", 1)[0]
    except IndexError as exc:
        raise ValueError("Named shadow validation matrix or 33-bit positive boundary case missing") from exc
    calls = re.findall(
        r"run_invalid_shadow_case\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(32'[dh][0-9a-fA-F]+)\s*\)", body
    )
    decoded = [(int(case_id), int(index), decode_sv_literal(value))
               for case_id, index, value in calls]
    require(decoded == EXPECTED_CASES,
            f"Shadow validation case census mismatch ({len(decoded)} calls)")
    return decoded


def verify_prior_sources() -> dict[str, Any]:
    for path in (RTL, BASE_TB, TB, HEADER, CONTRACT, DOC, PRIOR_REPORT):
        require(path.is_file(), f"Required source/proof is missing: {path}")
    require(sha256(RTL) == EXPECTED_RTL_SHA, "Frozen V2 RTL changed")
    require(sha256(BASE_TB) == EXPECTED_BASE_TB_SHA, "Passing V3 control bench changed")
    require(sha256(HEADER) == EXPECTED_HEADER_SHA, "Frozen MMIO ABI header changed")
    require(sha256(CONTRACT) == EXPECTED_CONTRACT_SHA, "Frozen MMIO contract changed")
    require(sha256(PRIOR_REPORT) == EXPECTED_PRIOR_REPORT_SHA, "Prior passing report changed")
    prior = json.loads(PRIOR_REPORT.read_text(encoding="utf-8"))
    require(prior.get("status") == EXPECTED_PRIOR_STATUS,
            "Prior baseline MMIO control report is not a pass")
    prior_sources = {name.replace("\\", "/"): digest.lower()
                     for name, digest in prior.get("source_sha256_after", {}).items()}
    require(prior_sources.get(source_key(RTL)) == EXPECTED_RTL_SHA and
            prior_sources.get(source_key(BASE_TB)) == EXPECTED_BASE_TB_SHA,
            "Prior pass report does not bind the frozen RTL and V3 bench")
    matrix = verify_matrix_source(TB.read_text(encoding="utf-8"))
    return {
        "prior_pass_report": {"path": source_key(PRIOR_REPORT), "sha256": sha256(PRIOR_REPORT),
                              "status": prior["status"]},
        "frozen_rtl": {"path": source_key(RTL), "sha256": sha256(RTL)},
        "baseline_control_bench": {"path": source_key(BASE_TB), "sha256": sha256(BASE_TB)},
        "invalid_shadow_case_census": len(matrix),
        "invalid_shadow_cases": [
            {"case_id": case_id, "word_index": word_index, "bad_value": f"0x{value:08x}"}
            for case_id, word_index, value in matrix
        ],
    }


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:6]
    out = ROOT / "validation/board_z100/native_conv_mmio_boundary_v1" / stamp
    build = ROOT / "deployment/build/native_conv_mmio_boundary_v1" / stamp
    out.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    result_path = out / "result.json"
    report: dict[str, Any] = {
        "schema": "z100-native-conv-mmio-boundary-v1-validation/1",
        "status": "PREFLIGHT",
        "board_access": False,
        "vendor_cad_run": False,
        "backend_mock": True,
        "actual_backend_arithmetic_executed": False,
        "fullgraph_execution_accepted": False,
        "full_pipeline_30fps_accepted": False,
        "scope": "V2 AXI-Lite frontend shadow validation and address-boundary behavior with mocked backend readiness/status; no actual Conv or DDR qualification.",
        "simulation_limit_ps": MAX_SIMULATION_PS,
        "wall_limit_seconds": MAX_WALL_SECONDS,
        "commands": [],
    }
    sources: list[Path] = []
    before: dict[str, str] = {}
    started = time.monotonic()
    try:
        proof_context = verify_prior_sources()
        compiler, runner, backend, runtime_paths, manifest = local_runtime()
        sources = [Path(__file__).resolve(), Path(__file__).with_name("validate_z100_mac_local_control_v3.py"),
                   RTL, BASE_TB, TB, HEADER, CONTRACT, DOC, PRIOR_REPORT, *runtime_paths]
        require(all(path.is_file() for path in sources), "A source-bound input is missing")
        before = dict(sorted((source_key(path), sha256(path)) for path in sources))
        report.update(source_sha256_before=before, source_proof_context=proof_context,
                      runtime_version=manifest.get("versions", {}).get("iverilog"),
                      runtime_manifest_sha256=sha256(runtime_paths[0]),
                      build_directory=source_key(build), output_directory=source_key(out))
        env = dict(os.environ, OMP_NUM_THREADS="1")
        env["PATH"] = str(compiler.parent) + os.pathsep + env.get("PATH", "")
        executable = build / "boundary_test.vvp"
        commands = [
            ("iverilog", [str(compiler), "-B", str(backend), "-g2012", "-Wall", "-s",
                          "tb_z100_native_conv_mmio_boundary_v1", "-o", str(executable),
                          str(RTL), str(TB)]),
            ("vvp", [str(runner), "-M", str(backend), str(executable)]),
        ]
        final_log = ""
        for label, argv in commands:
            remaining = MAX_WALL_SECONDS - (time.monotonic() - started)
            require(remaining > 1, "60-second wall-time budget exhausted before " + label)
            command_start = time.monotonic()
            try:
                proc = subprocess.run(argv, cwd=build, env=env, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace",
                                      timeout=max(1, int(remaining)), check=False)
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                log_path = out / f"{label}.log"
                log_path.write_text(stdout + stderr + "\nTIMEOUT; this run will not be retried automatically.\n",
                                    encoding="utf-8")
                report["commands"].append({"label": label, "argv": argv, "return_code": None,
                                           "log": source_key(log_path), "timeout": True})
                raise ValueError(f"{label} exceeded the remaining wall-time budget") from exc
            final_log = proc.stdout + ("\n" if proc.stdout and proc.stderr else "") + proc.stderr
            log_path = out / f"{label}.log"
            log_path.write_text(final_log, encoding="utf-8")
            report["commands"].append({
                "label": label, "argv": argv, "cwd": source_key(build),
                "return_code": proc.returncode,
                "elapsed_seconds": round(time.monotonic() - command_start, 3),
                "log": source_key(log_path), "log_sha256": sha256(log_path),
            })
            require(proc.returncode == 0, f"{label} returned {proc.returncode}; see {log_path}")
            require(re.search(r"(?im)^\s*(?:error:|fatal:|FAIL_NATIVE_CONV_MMIO)", final_log) is None,
                    f"{label} emitted a failure diagnostic; see {log_path}")

        markers = re.findall(r"^PASS_NATIVE_CONV_MMIO_BOUNDARY_V1 (.+)$", final_log, re.M)
        require(len(markers) == 1 and final_log.count("$finish called at") == 1,
                "Simulation did not complete with exactly one pass marker")
        sim_time = re.search(r"\$finish called at (\d+) \(1ps\)", final_log)
        require(sim_time is not None and int(sim_time.group(1)) <= MAX_SIMULATION_PS,
                "Simulation exceeded its 500 us watchdog limit")
        coverage = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", markers[0])}
        minimum = {
            "bad_fields": 38, "unexpected_cmdvalid": 0, "unexpected_handshakes": 0,
            "exact_4g_end": 1, "awfirst": 1, "wfirst": 1, "bhold": 3, "rhold": 6,
            "partial": 1, "ro": 1, "unaligned": 1, "unmapped": 2, "zero_strobe": 4,
            "invalid": 1, "abort": 1, "timeout": 1, "abortrace": 1, "timeoutrace": 1,
            "earlyack": 1, "shadowlock": 2, "fault_active_quiet": 1, "success": 1,
            "raw_identity": 2, "grants": 3, "irq": 2, "coordinated_reset": 2,
        }
        require(all(coverage.get(name, -1) >= limit for name, limit in minimum.items()),
                "Pass marker coverage is below the required boundary/control census")
        require(coverage["bad_fields"] == 38, "Bad-field variant count must match the exact matrix")
        report.update(
            status="PASS_LOCAL_MMIO_SHADOW_BOUNDARIES_WITH_MOCK_BACKEND_NOT_INTEGRATION",
            simulation=coverage,
            simulation_finished_at_ps=int(sim_time.group(1)),
            synthesized_or_routed=False,
            backend_wrapper_mapping_validated=False,
            completion="The exact-4-GiB logical boundary was accepted as frontend PENDING, then preaccept-aborted; this does not qualify DDR or physical memory access.",
        )
    except Exception as exc:
        report.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")
    after = dict(sorted((source_key(path), sha256(path)) for path in sources if path.is_file()))
    report["source_sha256_before"] = before
    report["source_sha256_after"] = after
    if before and before != after:
        report.update(status="FAILED_SOURCE_INTEGRITY", error="An input source changed during validation")
    report["elapsed_wall_seconds"] = round(time.monotonic() - started, 3)
    report["artifact_sha256"] = {
        source_key(path): sha256(path)
        for folder in (out, build) for path in folder.rglob("*")
        if path.is_file() and path != result_path
    }
    result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": source_key(result_path),
                      "error": report.get("error")}, ensure_ascii=False))
    return 1 if report["status"].startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
