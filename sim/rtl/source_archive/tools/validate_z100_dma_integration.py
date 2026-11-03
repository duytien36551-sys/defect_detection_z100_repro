#!/usr/bin/env python3
"""Compile/run the pinned Z100 Vivado simulation export and hash evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().upper()
    except OSError:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_manifest(
    root: Path, export_dir: Path, physical_export_root: Path, tb_path: Path
) -> list[dict[str, Any]]:
    projects = [export_dir / "vlog.prj", export_dir / "vhdl.prj"]
    raw_sources: list[str] = []
    for project in projects:
        raw_sources.extend(re.findall(r'"([^"]+)"', project.read_text(encoding="utf-8", errors="replace")))
    raw_sources.extend(
        str(export_dir / name)
        for name in ("vlog.prj", "vhdl.prj", "xsim.ini", "system_wrapper.sh")
    )
    raw_sources.append(str(tb_path))

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_sources:
        normalized = raw.replace("\\", "/")
        if not normalized.lower().endswith((".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl", ".prj", ".ini", ".sh")):
            continue
        logical = Path(raw.replace("/", os.sep))
        low = normalized.lower()
        if low.startswith("x:/p/") or low.startswith("x:/e/"):
            relative_parts = normalized[3:].lstrip("/").split("/")
            physical = physical_export_root.joinpath(*relative_parts)
        else:
            physical = logical
        key = str(physical).casefold()
        if key in seen:
            continue
        seen.add(key)
        chosen = physical if physical.is_file() else logical
        entries.append(
            {
                "export_or_source_path": raw,
                "physical_path": str(chosen),
                "exists": chosen.is_file(),
                "sha256": sha256(chosen) if chosen.is_file() else None,
            }
        )
    return entries


def command_tokens(exe: Path, args: list[str]) -> tuple[list[str], str]:
    tokens = [str(exe), *args]
    # Vivado supplies .bat launchers. Run through cmd.exe so Windows reports
    # the child tool's actual exit code instead of a shell lookup status.
    command_line = subprocess.list2cmdline(tokens)
    return ["cmd.exe", "/d", "/c", command_line], command_line


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=(
            "probe", "normal", "full", "write_reset_aw", "write_reset_b", "write_reset_both",
            "fault_partial_w", "fault_tlast_abort", "fault_persistent", "fault_bresp",
            "read_mm2s_abort", "read_rbackpressure", "read_slverr", "read_decerr",
            "retry_early_error", "retry_repeated_error", "retry_permanent_read",
            "page_normal", "page_read_reset", "page_write_reset",
        ),
        default="probe",
    )
    parser.add_argument("--export-dir", default=r"X:\e\xsim")
    parser.add_argument(
        "--physical-export-root",
        default="deployment/build/z100_dma_integration/s1",
        help="physical root behind the temporary X: mapping, relative to repository root",
    )
    parser.add_argument("--vivado-bin", default=r"C:\appload\2026.1\Vivado\bin")
    parser.add_argument("--tool-timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    runner_path = Path(__file__).resolve()
    runner_sha256_before = sha256(runner_path)
    runner_argv = [sys.executable, *sys.argv]
    runner_command = subprocess.list2cmdline(runner_argv)
    export_dir = Path(args.export_dir)
    physical_export_root = root / args.physical_export_root
    write_reset_stage = args.stage.startswith("write_reset_")
    fault_stage = args.stage.startswith("fault_")
    read_stage = args.stage.startswith("read_")
    retry_stage = args.stage.startswith("retry_")
    page_stage = args.stage.startswith("page_")
    if page_stage:
        tb_path = root / "deployment/hardware/z100_2026/dma_page_tests/tb_z100_dma_page.sv"
        test_top = "tb_z100_dma_page"
        build_parent = root / "deployment/build/z100_dma_page_tests"
        evidence_parent = root / "validation/board_z100/dma_page_tests"
    elif retry_stage:
        tb_path = root / "deployment/hardware/z100_2026/dma_retry_tests/tb_z100_dma_retry.sv"
        test_top = "tb_z100_dma_retry"
        build_parent = root / "deployment/build/z100_dma_retry_tests"
        evidence_parent = root / "validation/board_z100/dma_retry_tests"
    elif read_stage:
        tb_path = root / "deployment/hardware/z100_2026/dma_read_tests/tb_z100_dma_read.sv"
        test_top = "tb_z100_dma_read"
        build_parent = root / "deployment/build/z100_dma_read_tests"
        evidence_parent = root / "validation/board_z100/dma_read_tests"
    elif write_reset_stage:
        tb_path = root / "deployment/hardware/z100_2026/dma_write_reset_tests/tb_z100_dma_write_reset.sv"
        test_top = "tb_z100_dma_write_reset"
        build_parent = root / "deployment/build/z100_dma_write_reset"
        evidence_parent = root / "validation/board_z100/dma_write_reset"
    elif fault_stage:
        tb_path = root / "deployment/hardware/z100_2026/dma_fault_tests/tb_z100_dma_fault.sv"
        test_top = "tb_z100_dma_fault"
        build_parent = root / "deployment/build/z100_dma_fault_tests"
        evidence_parent = root / "validation/board_z100/dma_fault_tests"
    else:
        tb_path = root / "deployment/hardware/z100_2026/dma_integration_tests/tb_z100_dma_integration.sv"
        test_top = "tb_z100_dma_integration"
        build_parent = root / "deployment/build/z100_dma_integration"
        evidence_parent = root / "validation/board_z100/dma_integration"
    if not tb_path.is_file():
        print(f"ERROR missing testbench: {tb_path}", file=sys.stderr)
        return 2
    required_export = ("vlog.prj", "vhdl.prj", "xsim.ini", "system_wrapper.sh")
    missing = [name for name in required_export if not (export_dir / name).is_file()]
    if missing:
        print(f"ERROR missing XSIM export entries under {export_dir}: {missing}", file=sys.stderr)
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:12]
    build_dir = build_parent / run_id
    evidence_dir = evidence_parent / run_id
    build_dir.mkdir(parents=True, exist_ok=False)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(export_dir / "xsim.ini", build_dir / "xsim.ini")
    tb_snapshot = evidence_dir / f"{tb_path.stem}.snapshot{tb_path.suffix}"
    shutil.copy2(tb_path, tb_snapshot)
    tb_snapshot_sha256 = sha256(tb_snapshot)
    source_files_before = source_manifest(root, export_dir, physical_export_root, tb_path)

    vivado_bin = Path(args.vivado_bin)
    expected_pass = {
        "probe": "PASS z100 DMA integration PROBE_ONLY",
        "normal": "PASS z100 DMA integration NORMAL_ONLY",
        "full": "PASS z100 DMA integration and DMA-only recovery",
        "write_reset_aw": "PASS z100 DMA write reset AW_ONLY",
        "write_reset_b": "PASS z100 DMA write reset B_DELAY_ONLY",
        "write_reset_both": "PASS z100 DMA write reset BIDIR_ONLY",
        "fault_partial_w": "PASS z100 DMA fault PARTIAL_W",
        "fault_tlast_abort": "PASS z100 DMA fault TLAST_ABORT",
        "fault_persistent": "PASS z100 DMA fault PERSISTENT_PENDING",
        "fault_bresp": "PASS z100 DMA fault BRESP_ERROR_RECOVERED",
        "read_mm2s_abort": "PASS z100 DMA read MM2S_ABORT",
        "read_rbackpressure": "PASS z100 DMA read R_BACKPRESSURE",
        "read_slverr": "PASS z100 DMA read RRESP_SLVERR",
        "read_decerr": "PASS z100 DMA read RRESP_DECERR",
        "retry_early_error": "PASS z100 DMA retry EARLY_ERROR",
        "retry_repeated_error": "PASS z100 DMA retry REPEATED_ERROR",
        "retry_permanent_read": "PASS z100 DMA retry PERMANENT_READ_PENDING",
        "page_normal": "PASS z100 DMA page NORMAL",
        "page_read_reset": "PASS z100 DMA page READ_RESET",
        "page_write_reset": "PASS z100 DMA page WRITE_RESET",
    }[args.stage]
    plusarg = {
        "probe": "PROBE_ONLY", "normal": "NORMAL_ONLY", "full": None,
        "write_reset_aw": "WRITE_RESET_AW_ONLY",
        "write_reset_b": "WRITE_RESET_B_ONLY",
        "write_reset_both": "WRITE_RESET_BOTH_ONLY",
        "fault_partial_w": "FAULT_PARTIAL_W",
        "fault_tlast_abort": "FAULT_TLAST_ABORT",
        "fault_persistent": "FAULT_PERSISTENT",
        "fault_bresp": "FAULT_BRESP",
        "read_mm2s_abort": "READ_MM2S_ABORT",
        "read_rbackpressure": "READ_R_BACKPRESSURE",
        "read_slverr": "READ_RRESP_SLVERR",
        "read_decerr": "READ_RRESP_DECERR",
        "retry_early_error": "RETRY_EARLY_ERROR",
        "retry_repeated_error": "RETRY_REPEATED_ERROR",
        "retry_permanent_read": "RETRY_PERMANENT_READ",
        "page_normal": "PAGE_NORMAL",
        "page_read_reset": "PAGE_READ_RESET",
        "page_write_reset": "PAGE_WRITE_RESET",
    }[args.stage]

    library_args = [
        "-L", "xil_defaultlib", "-L", "axi_infrastructure_v1_1_0",
        "-L", "axi_vip_v1_1_23", "-L", "processing_system7_vip_v1_0_25",
        "-L", "axi_datamover_v5_1_38", "-L", "axi_sg_v4_1_21",
        "-L", "axi_dma_v7_1_38", "-L", "generic_baseblocks_v2_1_2",
        "-L", "axi_register_slice_v2_1_37", "-L", "fifo_generator_v13_2_15",
        "-L", "axi_data_fifo_v2_1_37", "-L", "axi_crossbar_v2_1_39",
        "-L", "axi_protocol_converter_v2_1_38", "-L", "proc_sys_reset_v5_0_17",
        "-L", "xlconstant_v1_1_11", "-L", "uvm", "-L", "xilinx_vip",
        "-L", "unisims_ver", "-L", "unimacro_ver", "-L", "secureip", "-L", "xpm",
    ]
    steps: list[tuple[str, Path, list[str]]] = [
        (
            "xvlog_project",
            vivado_bin / "xvlog.bat",
            ["--incr", "--relax", "-L", "uvm", "-L", "axi_vip_v1_1_23", "-L", "processing_system7_vip_v1_0_25", "-L", "xilinx_vip", "-prj", str(export_dir / "vlog.prj")],
        ),
        ("xvhdl_project", vivado_bin / "xvhdl.bat", ["--incr", "--relax", "-prj", str(export_dir / "vhdl.prj")]),
        (
            "xvlog_testbench",
            vivado_bin / "xvlog.bat",
            ["--incr", "--relax", "-sv", "-work", "xil_defaultlib", "-L", "uvm", "-L", "axi_vip_v1_1_23", "-L", "processing_system7_vip_v1_0_25", "-L", "xilinx_vip", str(tb_path)],
        ),
        (
            "xelab",
            vivado_bin / "xelab.bat",
            ["--incr", "--debug", "typical", "--relax", "--mt", "2", *library_args, "--snapshot", test_top, f"xil_defaultlib.{test_top}", "xil_defaultlib.glbl", "-log", "xelab.log"],
        ),
        (
            "xsim",
            vivado_bin / "xsim.bat",
            [test_top, *(["-testplusarg", plusarg] if plusarg else []), "-runall", "-log", "xsim.log"],
        ),
    ]

    env = os.environ.copy()
    env["RDI_DATADIR"] = str(Path(args.vivado_bin).parent / "data")
    env["PATH"] = str(vivado_bin) + os.pathsep + env.get("PATH", "")
    results: list[dict[str, Any]] = []
    failed = False
    for name, exe, tool_args in steps:
        argv, shell_line = command_tokens(exe, tool_args)
        log_path = evidence_dir / f"{name}.stdout.log"
        entry: dict[str, Any] = {
            "name": name,
            "executable": str(exe),
            "arguments": tool_args,
            "shell_command": shell_line,
            "working_directory": str(build_dir),
            "argv": argv,
            "started_utc": utc_now(),
            "return_code": None,
            "timed_out": False,
            "stdout_log": str(log_path),
        }
        start = time.monotonic()
        try:
            with log_path.open("wb") as output:
                completed = subprocess.run(
                    argv,
                    cwd=build_dir,
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=args.tool_timeout_seconds,
                    check=False,
                )
            entry["return_code"] = completed.returncode
        except subprocess.TimeoutExpired:
            entry["timed_out"] = True
            failed = True
        except OSError as exc:
            entry["exception"] = repr(exc)
            failed = True
        entry["duration_seconds"] = round(time.monotonic() - start, 3)
        entry["ended_utc"] = utc_now()
        entry["stdout_sha256"] = sha256(log_path)
        results.append(entry)
        if entry["return_code"] != 0:
            failed = True
            break

    sim_log = evidence_dir / "xsim.stdout.log"
    sim_text = sim_log.read_text(encoding="utf-8", errors="replace") if sim_log.exists() else ""
    runner_sha256_after = sha256(runner_path)
    if runner_sha256_before != runner_sha256_after:
        failed = True
    source_files_after = source_manifest(root, export_dir, physical_export_root, tb_path)
    input_missing = [
        item["export_or_source_path"]
        for item in source_files_before
        if not item["exists"]
    ]
    after_by_path = {item["physical_path"].casefold(): item for item in source_files_after}
    source_hash_changes = []
    for before in source_files_before:
        after = after_by_path.get(before["physical_path"].casefold())
        if after is None or before["exists"] != after["exists"] or before["sha256"] != after["sha256"]:
            source_hash_changes.append(
                {
                    "physical_path": before["physical_path"],
                    "before_sha256": before["sha256"],
                    "after_sha256": after["sha256"] if after else None,
                    "before_exists": before["exists"],
                    "after_exists": after["exists"] if after else False,
                }
            )
    if source_hash_changes:
        failed = True
    pass_observed = expected_pass in sim_text
    explicit_failure = "FAIL " in sim_text or "Fatal:" in sim_text
    native_logs = []
    for log in sorted(build_dir.glob("*.log")):
        native_logs.append({"path": str(log), "sha256": sha256(log)})
    command_hash = hashlib.sha256(
        json.dumps([entry["shell_command"] for entry in results], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    input_manifest = {
        "run_id": run_id,
        "stage": args.stage,
        "export_dir_logical": str(export_dir),
        "export_dir_physical_root": str(physical_export_root),
        "source_files_before_run": source_files_before,
        "source_files_after_run": source_files_after,
        "missing_source_files": input_missing,
        "source_hashes_unchanged": not source_hash_changes,
        "source_hash_changes": source_hash_changes,
        "runner_path": str(runner_path),
        "runner_sha256_before": runner_sha256_before,
        "runner_sha256_after": runner_sha256_after,
        "runner_argv": runner_argv,
        "runner_command": runner_command,
        "command_plan_sha256": command_hash,
        "testbench_sha256_before_run": next(
            (item["sha256"] for item in source_files_before if Path(item["physical_path"]).resolve() == tb_path.resolve()),
            None,
        ),
        "testbench_sha256_after_run": sha256(tb_path),
        "testbench_snapshot": str(tb_snapshot),
        "testbench_snapshot_sha256": tb_snapshot_sha256,
    }
    input_path = evidence_dir / "input_manifest.json"
    input_path.write_text(json.dumps(input_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sim_lines = [line.strip() for line in sim_text.splitlines() if line.strip().startswith(("COVERAGE", "SOURCE_CHAIN", "PASS ", "FAIL "))]
    result_name = "PASS" if not failed and not input_missing and not source_hash_changes and pass_observed and not explicit_failure else "FAIL"
    report = {
        "schema": "z100-dma-integration-run-v1",
        "run_id": run_id,
        "stage": args.stage,
        "result": result_name,
        "started_utc": results[0]["started_utc"] if results else utc_now(),
        "ended_utc": utc_now(),
        "python_executable": sys.executable,
        "python_utf8_mode": sys.flags.utf8_mode,
        "runner_path": str(runner_path),
        "runner_sha256_before": runner_sha256_before,
        "runner_sha256_after": runner_sha256_after,
        "runner_argv": runner_argv,
        "runner_command": runner_command,
        "repository_root": str(root),
        "build_working_directory": str(build_dir),
        "evidence_directory": str(evidence_dir),
        "expected_pass_marker": expected_pass,
        "pass_marker_observed": pass_observed,
        "explicit_sim_failure_observed": explicit_failure,
        "command_plan_sha256": command_hash,
        "commands": results,
        "source_coverage": sim_lines,
        "native_build_logs": native_logs,
        "input_manifest": str(input_path),
        "input_manifest_sha256": sha256(input_path),
        "testbench_sha256_before_run": next(
            (item["sha256"] for item in source_files_before if Path(item["physical_path"]).resolve() == tb_path.resolve()),
            None,
        ),
        "testbench_sha256_after_run": sha256(tb_path),
        "testbench_snapshot": str(tb_snapshot),
        "testbench_snapshot_sha256": tb_snapshot_sha256,
        "source_hashes_unchanged": not source_hash_changes,
        "source_hash_changes": source_hash_changes,
        "unresolved_coverage": {
            "probe": [
                "LOAD and RUN data path and output reference",
                "DMA-only reset while an MM2S read is outstanding",
                "persistent external AXI error response recovery",
                "multi-outstanding and out-of-order AXI3 completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
            ],
            "normal": [
                "DMA-only reset while an MM2S read is outstanding",
                "post-reset reload and RUN",
                "persistent external AXI error response recovery",
                "multi-outstanding and out-of-order AXI3 completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
            ],
            "full": [
                "persistent external AXI error response recovery",
                "multi-outstanding and out-of-order AXI3 completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
            ],
            "write_reset_aw": [
                "S2MM reset with W partially accepted (0 < W < burst length)",
                "RVALID held while RREADY is low (the reset case delays RVALID generation)",
                "persistent external AXI error response recovery",
                "more than one outstanding transaction per AXI channel and out-of-order completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
            ],
            "write_reset_b": [
                "S2MM reset after AW accepted with W stalled before the first beat",
                "simultaneous MM2S read and S2MM write outstanding reset",
                "RVALID held while RREADY is low (the reset case delays RVALID generation)",
                "persistent external AXI error response recovery",
                "more than one outstanding transaction per AXI channel and out-of-order completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
            ],
            "write_reset_both": [
                "S2MM reset after W completion with B response held",
                "S2MM reset with W partially accepted (0 < W < burst length)",
                "RVALID held while RREADY is low (the reset case delays RVALID generation)",
                "persistent external AXI error response recovery",
                "more than one outstanding transaction per AXI channel and out-of-order completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
            ],
            "fault_partial_w": [
                "TLAST-before-interruption AXIS stream boundary (covered by a separate fault_tlast_abort stage)",
                "persistent HP0 stall/reset-pending negative case (covered by a separate fault_persistent stage)",
                "real HP0 BRESP error response and DMA error status recovery",
                "RVALID held while RREADY is low",
                "more than one outstanding transaction per AXI channel and out-of-order completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
                "production C recover()/faulted/active/ready behavior (this is actual-IP SV with modeled AXI-Lite programming)",
            ],
            "fault_tlast_abort": [
                "partial HP0 W reset as a separate 2-of-5 external W case",
                "persistent HP0 stall/reset-pending negative case (covered by a separate fault_persistent stage)",
                "real HP0 BRESP error response and DMA error status recovery (covered by a separate fault_bresp stage)",
                "RVALID held while RREADY is low",
                "more than one outstanding transaction per AXI channel and out-of-order completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
                "production C recover()/faulted/active/ready behavior (this is actual-IP SV with modeled AXI-Lite programming)",
            ],
            "fault_persistent": [
                "successful ResetIsDone/closed-fence buffer release and reload (this negative case keeps ABORT asserted and does not reuse buffers)",
                "production C context faulted/active/ready fields (not instantiated in this RTL testbench; see separate C host-mock evidence)",
                "stream 2-of-5 TLAST interruption (covered by a separate fault_tlast_abort stage)",
                "real BRESP SLVERR and reset/reload (covered by a separate fault_bresp stage)",
                "RVALID held while RREADY is low",
                "multi-outstanding/out-of-order AXI3 and vendor XPM FIFO same-address collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
            ],
            "fault_bresp": [
                "persistent HP0 stall/reset-pending negative case (covered by a separate fault_persistent stage)",
                "TLAST-before-interruption S2MM stream boundary (covered by a separate fault_tlast_abort stage)",
                "RRESP error injection and MM2S TX error recovery",
                "RVALID held while RREADY is low",
                "more than one outstanding transaction per AXI channel and out-of-order completion",
                "vendor XPM FIFO same-address read/write collision observability",
                "physical DDR electrical/timing behavior (HP0 endpoint is a behavioral model)",
                "production C recover()/faulted/active/ready behavior (this is actual-IP SV with modeled AXI-Lite programming)",
            ],
        }.get(args.stage, [
            "Unbounded or additional repeated-error/permanent-read-stall variants and other reset phase relationships",
            "Multi-outstanding/out-of-order responses and additional burst/page boundaries",
            "XPM BRAM collision behavior, vendor reset methodology and physical DDR",
            "Production C execution on PS7; read interposers and HP0 endpoint are testbench models",
        ]),
        "reset_case_note": (
            "All HP0 holds are released after 40 cycles concurrently with bounded DMA status polling; "
            "these are finite delayed-response/backpressure cases, not permanent errors or stream truncation."
            if write_reset_stage or args.stage == "fault_partial_w" else
            "A test-only interposer blocks both DMA-side TVALID and core-side TREADY after the real S2MM 2-of-5 handshake. Confirmed ABORT cancels the pending third source beat before TLAST; the gate opens after 40 cycles while status polling continues. This does not exercise MM2S input stream truncation."
            if args.stage == "fault_tlast_abort" else
            "One HP0 B response is injected as SLVERR (BRESP=2) and is observed at both HP0 and DMA handshakes with S2MM RX status error 0x20 before DMA-only reset; after the error clears and fences close, new PROBE/LOAD/RUN is checked."
            if args.stage == "fault_bresp" else
            "HP0 WREADY remains permanently low through a 200-iteration testbench ResetIsDone poll window. This differs from the firmware's 5-second transfer deadline and from recover()'s default 10,000,000 poll budget (or context timeout_polls); ABORT remains held and no buffer release/reload is attempted."
            if args.stage == "fault_persistent" else
            "Test-only paired VALID/READY interposers inject MM2S pre-TLAST interruption or read return backpressure; HP0 RRESP injects SLVERR/DECERR. Read holds and injection clear 40 clocks after reset programming while bounded status polling continues. External queue/AXIS checks are verification oracles, not production C features."
            if read_stage else
            "Actual HP0/DMA SLVERR responses are held at four accepted beats of an unfinished 80-beat LOAD while TX status visibility is observed for up to 64 TB polls. Recovery is triggered by observed DMA error or the bounded TB timeout, not by an invented early error bit. Error injection persists across one/two DMA resets; it is repaired only before final healthy reload. Permanent read case instead holds the return gate through 200 polls and must leave reset pending/ABORT held. These are SV fixtures, not execution of production C timeout/state."
            if retry_stage else
            "Aligned cross-page transfers use actual DMA/HP0 burst address and LAST histories. No accepted burst may cross 4KiB. Normal LOAD/RUN checks exact byte coverage and 32 signed output values; finite reset cases stop at a new-page AR or partial second-page W and must close accepted transactions before release. This remains a single-outstanding HP0 endpoint and modeled CPU, not PS7 execution or arbitrary ordering coverage."
            if page_stage else None
        ),
    }
    report_path = evidence_dir / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "run_id": run_id,
        "result": result_name,
        "stage": args.stage,
        "report": str(report_path),
        "report_sha256": sha256(report_path),
        "build_directory": str(build_dir),
        "commands": [{"name": r["name"], "return_code": r["return_code"], "timed_out": r["timed_out"], "stdout_sha256": r["stdout_sha256"]} for r in results],
        "runner_sha256": runner_sha256_after,
        "coverage": sim_lines,
        "missing_sources": input_missing,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if result_name == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
