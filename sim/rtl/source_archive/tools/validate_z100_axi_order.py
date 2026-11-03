#!/usr/bin/env python3
"""Run a bounded actual AXI DMA/response-slice outstanding-order experiment."""

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
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VIVADO_BIN = Path(r"C:\appload\2026.1\Vivado\bin")
EXPORT_DIR = ROOT / "deployment/build/z100_dma_integration/s1/e/xsim"
EXPORT_ROOT = ROOT / "deployment/build/z100_dma_integration/s1"
TB_PATH = ROOT / "deployment/hardware/z100_2026/axi_order_validation/tb_z100_axi_order.sv"
DMA_VHDL = EXPORT_ROOT / "p/z100_compute.gen/sources_1/bd/system/ip/system_axi_dma_0_0/sim/system_axi_dma_0_0.vhd"
SLICE_VERILOG = EXPORT_ROOT / "p/z100_compute.gen/sources_1/bd/system/ip/system_mm2s_response_slice_0/sim/system_mm2s_response_slice_0.v"
BASE_ADDR = 0x1000
TRANSFER_BYTES = 1024
BURST_BYTES = 64
EXPECTED_PASS = "PASS z100 actual DMA/slice multiple-outstanding ordered read"


class EvidenceError(ValueError):
    """Raised when evidence is missing, malformed, or contradicts the contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _single_interface_attribute(text: str, port: str) -> str:
    pattern = re.compile(
        rf"ATTRIBUTE\s+X_INTERFACE_PARAMETER\s+OF\s+{re.escape(port)}\s*:\s*SIGNAL\s+IS\s+(.*?);",
        re.IGNORECASE | re.DOTALL,
    )
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise EvidenceError(f"expected exactly one X_INTERFACE_PARAMETER for {port}, found {len(matches)}")
    chunks = re.findall(r'"([^\"]*)"', matches[0])
    if not chunks:
        raise EvidenceError(f"interface attribute for {port} has no quoted value")
    return "".join(chunks)


def _single_verilog_interface_attribute(text: str, port: str) -> str:
    declaration = re.search(
        rf"\b(?:input|output)\s+wire(?:\s+\[[^]]+\])?\s+{re.escape(port)}\s*;",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not declaration:
        raise EvidenceError(f"generated Verilog port declaration is missing for {port}")
    attrs = list(re.finditer(r"\(\*\s*X_INTERFACE_PARAMETER\s*=\s*\"([^\"]*)\"\s*\*\)", text[: declaration.start()], re.I | re.S))
    if not attrs:
        raise EvidenceError(f"generated Verilog interface attribute is missing for {port}")
    chosen = attrs[-1]
    between = text[chosen.end() : declaration.start()]
    if re.search(r"\b(?:input|output)\s+wire\b", between, re.I):
        raise EvidenceError(f"could not bind the closest X_INTERFACE_PARAMETER to {port}")
    return chosen.group(1)


def _integer_parameter(attribute: str, name: str) -> int:
    matches = re.findall(rf"(?:^|,\s*){re.escape(name)}\s+(\d+)(?=,|$)", attribute, re.IGNORECASE)
    if len(matches) != 1:
        raise EvidenceError(f"expected one numeric {name}, found {len(matches)}")
    return int(matches[0])


def parse_axi_contract(dma_vhdl: str, slice_verilog: str) -> dict[str, Any]:
    """Fail closed while reading generated interface attributes and port IDs."""
    dma_params = _single_interface_attribute(dma_vhdl, "m_axi_mm2s_araddr")
    slice_s_params = _single_verilog_interface_attribute(slice_verilog, "s_axi_araddr")
    slice_m_params = _single_verilog_interface_attribute(slice_verilog, "m_axi_araddr")

    interfaces = {
        "dma_mm2s": dma_params,
        "response_slice_s": slice_s_params,
        "response_slice_m": slice_m_params,
    }
    parsed: dict[str, dict[str, int]] = {}
    for name, params in interfaces.items():
        parsed[name] = {
            "num_read_outstanding": _integer_parameter(params, "NUM_READ_OUTSTANDING"),
            "id_width": _integer_parameter(params, "ID_WIDTH"),
        }
    if parsed["dma_mm2s"]["num_read_outstanding"] != 16:
        raise EvidenceError("DMA MM2S outstanding declaration changed from the reviewed value 16")
    if parsed["dma_mm2s"]["id_width"] != 0:
        raise EvidenceError("DMA MM2S ID width changed; this checker assumes an untagged ordered interface")
    if parsed["response_slice_s"]["num_read_outstanding"] != 16 or parsed["response_slice_m"]["num_read_outstanding"] != 16:
        raise EvidenceError("response slice outstanding declaration is not 16 on both sides")
    if parsed["response_slice_s"]["id_width"] != 0 or parsed["response_slice_m"]["id_width"] != 0:
        raise EvidenceError("response slice ID width changed; this checker assumes ordered untagged responses")

    entity = re.search(r"ENTITY\s+system_axi_dma_0_0\s+IS\s+PORT\s*\((.*?)\)\s*;", dma_vhdl, re.I | re.S)
    if not entity:
        raise EvidenceError("generated DMA entity port list is missing")
    port_list = entity.group(1).lower()
    if re.search(r"\b(?:m_axi_mm2s_arid|m_axi_mm2s_rid)\b", port_list):
        raise EvidenceError("DMA entity unexpectedly exposes MM2S ARID/RID")

    return {
        "interfaces": parsed,
        "dma_mm2s_ports_have_arid_rid": False,
        "interpretation": "The generated DMA and response-slice interfaces declare up to 16 outstanding reads but carry no AXI ID. The simulation must preserve the single ordered response stream; ID-based reordering is outside this interface contract.",
    }


def parse_trace_lines(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if line.startswith("AXI_ORDER_AR "):
            match = re.fullmatch(r"AXI_ORDER_AR seq=(\d+) addr=([0-9a-fA-F]{8}) beats=(\d+) id=(\S+)", line)
            if not match:
                raise EvidenceError(f"malformed AR trace: {line}")
            events.append({"kind": "AR", "seq": int(match.group(1)), "addr": int(match.group(2), 16), "beats": int(match.group(3)), "id": match.group(4)})
        elif line.startswith("AXI_ORDER_R "):
            match = re.fullmatch(r"AXI_ORDER_R seq=(\d+) beat=(\d+) data=([0-9a-fA-F]{8}) last=([01]) id=(\S+)", line)
            if not match:
                raise EvidenceError(f"malformed R trace: {line}")
            events.append({"kind": "R", "seq": int(match.group(1)), "beat": int(match.group(2)), "data": int(match.group(3), 16), "last": int(match.group(4)), "id": match.group(5)})
        elif line.startswith("AXI_ORDER_AXIS "):
            match = re.fullmatch(r"AXI_ORDER_AXIS beat=(\d+) data=([0-9a-fA-F]{8}) last=([01])", line)
            if not match:
                raise EvidenceError(f"malformed AXIS trace: {line}")
            events.append({"kind": "AXIS", "beat": int(match.group(1)), "data": int(match.group(2), 16), "last": int(match.group(3))})
    if not events:
        raise EvidenceError("no machine-readable AXI_ORDER trace events found")
    return events


def validate_scoreboard(
    events: Iterable[dict[str, Any]],
    *,
    transfer_addr: int = BASE_ADDR,
    total_words: int = TRANSFER_BYTES // 4,
    burst_words: int = BURST_BYTES // 4,
    required_peak: int = 2,
    reported_peak: int | None = None,
) -> dict[str, int]:
    """Validate every request, ordered response beat, and delivered stream beat."""
    ordered = list(events)
    ar_events = [event for event in ordered if event.get("kind") == "AR"]
    r_events = [event for event in ordered if event.get("kind") == "R"]
    axis_events = [event for event in ordered if event.get("kind") == "AXIS"]
    expected_bursts = (total_words + burst_words - 1) // burst_words
    if len(ar_events) != expected_bursts:
        raise EvidenceError(f"expected {expected_bursts} AR bursts, found {len(ar_events)}")
    if len(r_events) != total_words:
        raise EvidenceError(f"expected {total_words} R beats, found {len(r_events)}")
    if len(axis_events) != total_words:
        raise EvidenceError(f"expected {total_words} AXIS beats, found {len(axis_events)}")

    for seq, event in enumerate(ar_events):
        if event.get("seq") != seq:
            raise EvidenceError(f"AR sequence discontinuity: expected {seq}, got {event.get('seq')}")
        if event.get("addr") != transfer_addr + seq * burst_words * 4:
            raise EvidenceError(f"AR address out of order at sequence {seq}")
        expected_len = min(burst_words, total_words - seq * burst_words)
        if event.get("beats") != expected_len:
            raise EvidenceError(f"AR length mismatch at sequence {seq}")
        if event.get("id") != "none":
            raise EvidenceError(f"unexpected AXI ID on ID_WIDTH=0 interface at AR sequence {seq}")

    first_r_index = next((index for index, event in enumerate(ordered) if event.get("kind") == "R"), None)
    if first_r_index is None:
        raise EvidenceError("no R responses in event stream")
    accepted_before_r = sum(1 for event in ordered[:first_r_index] if event.get("kind") == "AR")
    if accepted_before_r < required_peak:
        raise EvidenceError(f"only {accepted_before_r} AR bursts were accepted before the first R response")

    for word_index, event in enumerate(r_events):
        expected_seq, expected_beat = divmod(word_index, burst_words)
        expected_data = transfer_addr + word_index * 4
        expected_last = int(expected_beat == min(burst_words, total_words - expected_seq * burst_words) - 1)
        if event.get("seq") != expected_seq or event.get("beat") != expected_beat:
            raise EvidenceError(f"R burst/beat order mismatch at stream word {word_index}")
        if event.get("data") != expected_data:
            raise EvidenceError(f"R data/address mismatch at stream word {word_index}")
        if event.get("last") != expected_last:
            raise EvidenceError(f"R LAST mismatch at stream word {word_index}")
        if event.get("id") != "none":
            raise EvidenceError(f"unexpected AXI ID on ID_WIDTH=0 interface at R beat {word_index}")

    for word_index, event in enumerate(axis_events):
        if event.get("beat") != word_index or event.get("data") != transfer_addr + word_index * 4:
            raise EvidenceError(f"AXIS stream order/data mismatch at beat {word_index}")
        if event.get("last") != int(word_index == total_words - 1):
            raise EvidenceError(f"AXIS TLAST mismatch at beat {word_index}")

    peak = reported_peak if reported_peak is not None else accepted_before_r
    if peak < required_peak:
        raise EvidenceError(f"reported peak outstanding {peak} is below required {required_peak}")
    return {"ar_bursts": len(ar_events), "r_beats": len(r_events), "axis_beats": len(axis_events), "accepted_before_first_r": accepted_before_r, "reported_peak_outstanding": peak}


def _synthetic_trace(total_words: int = 4, burst_words: int = 2) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    bursts = (total_words + burst_words - 1) // burst_words
    for seq in range(bursts):
        events.append({"kind": "AR", "seq": seq, "addr": BASE_ADDR + seq * burst_words * 4, "beats": min(burst_words, total_words - seq * burst_words), "id": "none"})
    for word in range(total_words):
        seq, beat = divmod(word, burst_words)
        events.append({"kind": "R", "seq": seq, "beat": beat, "data": BASE_ADDR + word * 4, "last": int(beat == min(burst_words, total_words - seq * burst_words) - 1), "id": "none"})
    for word in range(total_words):
        events.append({"kind": "AXIS", "beat": word, "data": BASE_ADDR + word * 4, "last": int(word == total_words - 1)})
    return events


def run_checker_selftests() -> dict[str, int]:
    positive = _synthetic_trace()
    validate_scoreboard(positive, total_words=4, burst_words=2, required_peak=2)

    reordered = _synthetic_trace()
    first_r = next(i for i, event in enumerate(reordered) if event["kind"] == "R")
    reordered[first_r]["seq"] = 1
    _must_reject(lambda: validate_scoreboard(reordered, total_words=4, burst_words=2, required_peak=2), "reordered response")

    unexpected_id = _synthetic_trace()
    unexpected_id[0]["id"] = "0"
    _must_reject(lambda: validate_scoreboard(unexpected_id, total_words=4, burst_words=2, required_peak=2), "unexpected ID")

    too_few = _synthetic_trace()
    _must_reject(lambda: validate_scoreboard(too_few, total_words=4, burst_words=2, required_peak=3), "insufficient pre-response outstanding")

    return {"positive": 1, "malformed_order_rejected": 1, "unexpected_id_rejected": 1, "insufficient_activity_rejected": 1}


def _must_reject(callable_: Any, label: str) -> None:
    try:
        callable_()
    except EvidenceError:
        return
    raise AssertionError(f"scoreboard accepted malformed {label}")


def _source_manifest(export_dir: Path, export_root: Path, tb_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for project_name in ("vlog.prj", "vhdl.prj"):
        project_path = export_dir / project_name
        project_text = project_path.read_text(encoding="utf-8", errors="replace")
        raw_paths = re.findall(r'"([^\"]+)"', project_text)
        raw_paths.extend([str(project_path), str(export_dir / "xsim.ini")])
        for raw in raw_paths:
            normalized = raw.replace("\\", "/")
            if not normalized.lower().endswith((".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl", ".prj", ".ini")):
                continue
            low = normalized.lower()
            if low.startswith(("x:/p/", "x:/e/")):
                tail = normalized[3:].lstrip("/").split("/")
                physical = export_root.joinpath(*tail)
            else:
                physical = Path(raw.replace("/", os.sep))
            key = str(physical).casefold()
            if key in seen:
                continue
            seen.add(key)
            if not physical.is_file():
                raise EvidenceError(f"project source is missing: {physical}")
            entries.append({"path": str(physical), "sha256": sha256(physical)})
    for path in (tb_path, Path(__file__).resolve(), DMA_VHDL, SLICE_VERILOG):
        if not path.is_file():
            raise EvidenceError(f"required source is missing: {path}")
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            entries.append({"path": str(path), "sha256": sha256(path)})
    return entries


def _command_tokens(exe: Path, args: list[str]) -> tuple[list[str], str]:
    tokens = [str(exe), *args]
    return ["cmd.exe", "/d", "/c", subprocess.list2cmdline(tokens)], subprocess.list2cmdline(tokens)


def run_actual_sim(timeout_seconds: int = 1800) -> dict[str, Any]:
    for path in (EXPORT_DIR / "vlog.prj", EXPORT_DIR / "vhdl.prj", EXPORT_DIR / "xsim.ini", TB_PATH, DMA_VHDL, SLICE_VERILOG):
        if not path.is_file():
            raise EvidenceError(f"required simulation input is missing: {path}")
    if not VIVADO_BIN.is_dir():
        raise EvidenceError(f"Vivado 2026.1 bin directory missing: {VIVADO_BIN}")

    checker_selftests = run_checker_selftests()
    contract = parse_axi_contract(DMA_VHDL.read_text(encoding="utf-8", errors="replace"), SLICE_VERILOG.read_text(encoding="utf-8", errors="replace"))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    build_dir = ROOT / "deployment/build/z100_axi_order" / run_id
    evidence_dir = ROOT / "validation/board_z100/axi_order_validation" / run_id
    build_dir.mkdir(parents=True, exist_ok=False)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(EXPORT_DIR / "xsim.ini", build_dir / "xsim.ini")
    tb_snapshot = evidence_dir / TB_PATH.name
    shutil.copy2(TB_PATH, tb_snapshot)
    sources_before = _source_manifest(EXPORT_DIR, EXPORT_ROOT, TB_PATH)
    runner_path = Path(__file__).resolve()
    runner_hash_before = sha256(runner_path)
    tb_hash_before = sha256(TB_PATH)

    subst_lines = subprocess.run(["subst"], capture_output=True, text=True, check=False).stdout.splitlines()
    existing_x = next((line for line in subst_lines if re.match(r"(?i)^X:\\", line.strip())), None)
    created_subst = False
    if existing_x:
        existing_target = existing_x.split("=>", 1)[-1].strip().rstrip("\\/")
        if Path(existing_target).resolve() != EXPORT_ROOT.resolve():
            raise EvidenceError(f"X: is already mapped to a different path: {existing_x}")
    else:
        mapped = subprocess.run(["subst", "X:", str(EXPORT_ROOT)], capture_output=True, text=True, check=False)
        if mapped.returncode != 0:
            raise EvidenceError(f"could not map X: to the frozen actual-IP export tree: {mapped.stderr}")
        created_subst = True

    libraries = [
        "xil_defaultlib", "axi_infrastructure_v1_1_0", "axi_vip_v1_1_23",
        "processing_system7_vip_v1_0_25", "axi_datamover_v5_1_38", "axi_sg_v4_1_21",
        "axi_dma_v7_1_38", "generic_baseblocks_v2_1_2", "axi_register_slice_v2_1_37",
        "fifo_generator_v13_2_15", "axi_data_fifo_v2_1_37", "axi_crossbar_v2_1_39",
        "axi_protocol_converter_v2_1_38", "proc_sys_reset_v5_0_17", "xlconstant_v1_1_11",
        "uvm", "xilinx_vip", "unisims_ver", "unimacro_ver", "secureip", "xpm",
    ]
    steps = [
        ("xvlog_project", VIVADO_BIN / "xvlog.bat", ["--incr", "--relax", "-L", "uvm", "-L", "axi_vip_v1_1_23", "-L", "processing_system7_vip_v1_0_25", "-L", "xilinx_vip", "-prj", str(EXPORT_DIR / "vlog.prj")]),
        ("xvhdl_project", VIVADO_BIN / "xvhdl.bat", ["--incr", "--relax", "-prj", str(EXPORT_DIR / "vhdl.prj")]),
        ("xvlog_testbench", VIVADO_BIN / "xvlog.bat", ["--incr", "--relax", "-sv", "-work", "xil_defaultlib", "-L", "uvm", "-L", "axi_vip_v1_1_23", "-L", "processing_system7_vip_v1_0_25", "-L", "xilinx_vip", str(TB_PATH)]),
        ("xelab", VIVADO_BIN / "xelab.bat", ["--incr", "--debug", "typical", "--relax", "--mt", "2", *[arg for lib in libraries for arg in ("-L", lib)], "--snapshot", "tb_z100_axi_order", "xil_defaultlib.tb_z100_axi_order", "xil_defaultlib.glbl", "-log", "xelab.log"]),
        ("xsim", VIVADO_BIN / "xsim.bat", ["tb_z100_axi_order", "-runall", "-log", "xsim.log"]),
    ]
    env = os.environ.copy()
    env["RDI_DATADIR"] = str(VIVADO_BIN.parent / "data")
    env["PATH"] = str(VIVADO_BIN) + os.pathsep + env.get("PATH", "")
    command_results: list[dict[str, Any]] = []
    try:
        for name, exe, args in steps:
            argv, shell_command = _command_tokens(exe, args)
            log_path = evidence_dir / f"{name}.stdout.log"
            started = time.monotonic()
            try:
                with log_path.open("wb") as stream:
                    proc = subprocess.run(argv, cwd=build_dir, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout_seconds, check=False)
                result = {"name": name, "argv": argv, "shell_command": shell_command, "return_code": proc.returncode, "timed_out": False}
            except subprocess.TimeoutExpired:
                result = {"name": name, "argv": argv, "shell_command": shell_command, "return_code": None, "timed_out": True}
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            result["stdout_log"] = str(log_path)
            result["stdout_sha256"] = sha256(log_path)
            command_results.append(result)
            if result["return_code"] != 0 or result["timed_out"]:
                break
    finally:
        if created_subst:
            subprocess.run(["subst", "X:", "/d"], capture_output=True, text=True, check=False)

    sim_path = evidence_dir / "xsim.stdout.log"
    sim_text = sim_path.read_text(encoding="utf-8", errors="replace") if sim_path.is_file() else ""
    events = parse_trace_lines(sim_text)
    coverage_match = re.search(r"COVERAGE AXI_ORDER accepted=(\d+) completed=(\d+) returned_beats=(\d+) stream_beats=(\d+) peak_outstanding=(\d+) id_width=(\d+)", sim_text)
    if not coverage_match:
        raise EvidenceError("actual simulation omitted the required AXI_ORDER coverage record")
    coverage = {"ar_bursts": int(coverage_match.group(1)), "completed_bursts": int(coverage_match.group(2)), "r_beats": int(coverage_match.group(3)), "axis_beats": int(coverage_match.group(4)), "peak_outstanding": int(coverage_match.group(5)), "id_width": int(coverage_match.group(6))}
    checked = validate_scoreboard(events, reported_peak=coverage["peak_outstanding"])
    if coverage["ar_bursts"] != checked["ar_bursts"] or coverage["completed_bursts"] != checked["ar_bursts"]:
        raise EvidenceError("coverage counters disagree with the machine-readable transaction trace")
    if coverage["r_beats"] != checked["r_beats"] or coverage["axis_beats"] != checked["axis_beats"]:
        raise EvidenceError("coverage beat counters disagree with the machine-readable transaction trace")
    if coverage["id_width"] != 0:
        raise EvidenceError("simulation reported an unexpected AXI ID width")

    sources_after = _source_manifest(EXPORT_DIR, EXPORT_ROOT, TB_PATH)
    if sources_before != sources_after or sha256(runner_path) != runner_hash_before or sha256(TB_PATH) != tb_hash_before:
        raise EvidenceError("a pinned simulation input changed during the run")
    if any(result["return_code"] != 0 or result["timed_out"] for result in command_results):
        raise EvidenceError("one or more Vivado simulation commands failed")
    if EXPECTED_PASS not in sim_text or "FAIL " in sim_text or "Fatal:" in sim_text:
        raise EvidenceError("actual RTL simulation did not emit a clean expected PASS")

    report = {
        "schema": "z100-axi-order-validation-v1",
        "status": "PASS_ACTUAL_DMA_SLICE_ORDERED_MULTI_OUTSTANDING",
        "run_id": run_id,
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actual_ip_contract": contract,
        "checker_selftests": checker_selftests,
        "scoreboard": checked,
        "coverage": coverage,
        "commands": command_results,
        "simulation_log": str(sim_path),
        "simulation_log_sha256": sha256(sim_path),
        "runner_path": str(runner_path),
        "runner_sha256": runner_hash_before,
        "testbench_path": str(TB_PATH),
        "testbench_sha256": tb_hash_before,
        "testbench_snapshot": str(tb_snapshot),
        "testbench_snapshot_sha256": sha256(tb_snapshot),
        "input_sources": sources_before,
        "scope": "Actual generated AXI DMA and MM2S response-slice RTL simulation. Behavioral AXI-Lite master, ordered memory FIFO, and AXI-Stream sink. Demonstrates multiple outstanding untagged reads and ordered response/data delivery for one 1,024-byte transfer (16 64-byte bursts). No PS7 or physical DDR simulation, no AXI ID reorder, no randomized stress, and no vendor finding disposition.",
        "physical_board_tested": False,
        "bitstream_or_boot_artifact_created": False,
        "vendor_findings_dispositioned": False,
    }
    report_path = evidence_dir / "result.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"report": str(report_path), "sha256": sha256(report_path), "status": report["status"], "coverage": coverage}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="run the checker-only positive and negative fixtures")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    try:
        if args.self_test:
            result = {"status": "PASS_CHECKER_SELFTESTS", "selftests": run_checker_selftests()}
        else:
            result = run_actual_sim(args.timeout_seconds)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (EvidenceError, AssertionError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
