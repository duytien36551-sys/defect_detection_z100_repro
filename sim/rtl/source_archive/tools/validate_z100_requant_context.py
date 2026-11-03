"""Validate the isolated eight-context depth-specialized threshold-search experiment."""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import random
import re
import struct
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import z100_requant_context_map as context_map  # noqa: E402
import z100_requant_thresholds as rq  # noqa: E402
import validate_z100_requant_pipeline as pipeline_ref  # noqa: E402
from validate_z100_reuse_sync import VIVADO_DEFAULT, run_command, sha256  # noqa: E402

FIXTURE = ROOT / "deployment/hardware/z100_2026/requant_context_v1"
BUILD_ROOT = ROOT / "deployment/build/z100_requant_context_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/requant_context_v1"
PACKAGE = ROOT / "deployment/candidates/pin640/validation/20261021_verified/pin/pipeline/package"
REFERENCE_TABLES = ROOT / "deployment/build/z100_requant_threshold_v0/20261021T134827Z_a66a4f65/all_thresholds.bin"
REFERENCE_REPORT = ROOT / "validation/board_z100/requant_threshold_v0/20261021T134827Z_a66a4f65/result.json"
REFERENCE_C = ROOT / "deployment/hardware/z100_2026/requant_threshold_v0/oracle.c"
REFERENCE_TABLE_SHA256 = "f425a5e2311a6739dc5f83daaa75fc6df32d9f9e46a025268d9125964e75c2af"
REFERENCE_REPORT_SHA256 = "2af534a2f4b3ba20ce5bbefb190279c8b3b7405f9470ab1e3e84471080d2f189"
MIN_I32 = -(1 << 31)
MAX_I32 = (1 << 31) - 1
SENTINEL = 1 << 31
ACTUAL_VECTORS_PER_CONTEXT = 1024
SYNTHETIC_VECTORS_PER_CONTEXT = 1024
SYNTHETIC_COUNT = 3
PRESERVED_VECTORS_PER_CONTEXT = 256
SYNTHESIS_BUDGET = dict(slice_lut=2048, flip_flops=2048, ramb18_equivalent=9, dsp=0)


def sha(path: Path) -> str:
    return sha256(path)


def _read_reference() -> tuple[list[dict[str, Any]], list[tuple[int, ...]], dict[str, Any]]:
    proof = json.loads(REFERENCE_REPORT.read_text(encoding="utf-8"))
    if proof.get("status") != "PASS_PRIVATE_EXACT_REQUANT_THRESHOLDS":
        raise ValueError("pinned threshold proof is not passing")
    artifact_key = str(REFERENCE_TABLES.relative_to(ROOT)).replace("/", "\\")
    if proof.get("artifacts_sha256", {}).get(artifact_key) != REFERENCE_TABLE_SHA256:
        raise ValueError("pinned proof does not bind the expected threshold artifact")
    if sha(REFERENCE_TABLES) != REFERENCE_TABLE_SHA256:
        raise ValueError("verified threshold artifact hash changed")
    if sha(REFERENCE_REPORT) != REFERENCE_REPORT_SHA256:
        raise ValueError("pinned threshold report hash changed")
    package_rows = rq.package_multipliers(PACKAGE)
    if len(package_rows) != 5515:
        raise ValueError(f"expected 5515 package channels, got {len(package_rows)}")
    payload = REFERENCE_TABLES.read_bytes()
    if len(payload) != len(package_rows) * 254 * 8:
        raise ValueError("threshold artifact size does not match 5515 channels")
    tables = [tuple(row) for row in struct.iter_unpack("<254q", payload)]
    if len(tables) != len(package_rows):
        raise ValueError("threshold row count mismatch")
    return package_rows, tables, proof


def _verify_all_channel_boundaries(rows: list[dict[str, Any]], tables: list[tuple[int, ...]]) -> dict[str, int]:
    checked = 0
    for channel, (metadata, original) in enumerate(zip(rows, tables, strict=True)):
        if len(original) != 254 or tuple(sorted(original)) != original:
            raise ValueError(f"invalid threshold ordering at channel {channel}")
        tree = original + (SENTINEL,)
        banks = context_map.banked_table(tree)
        multiplier = metadata["multiplier"]
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError(f"invalid packaged multiplier at channel {channel}")
        for key in original:
            for raw in (key - 1, key, key + 1):
                if not MIN_I32 <= raw <= MAX_I32:
                    continue
                rank = context_map.search_banked_rank(banks, raw)
                expected_rank = bisect.bisect_right(original, raw)
                if rank != expected_rank:
                    raise ValueError(f"tree/bisect mismatch at channel {channel}, raw {raw}")
                exact = rq.oracle(raw, multiplier)
                if rank - 127 != exact:
                    raise ValueError(f"tree/package oracle mismatch at channel {channel}, raw {raw}")
                checked += 1
        if context_map.search_banked_rank(banks, MAX_I32) == 255:
            raise ValueError(f"INT32_MAX crossed the sentinel at channel {channel}")
    return dict(channels=len(rows), threshold_boundary_probes=checked,
                maximum_signed_int32_sentinel_crossings=0)


def _probe_values(original: tuple[int, ...], seed: int) -> list[int]:
    values = {MIN_I32, MAX_I32, -1, 0, 1}
    for key in original:
        for delta in (-1, 0, 1):
            raw = key + delta
            if MIN_I32 <= raw <= MAX_I32:
                values.add(raw)
    result = sorted(values)
    if len(result) > ACTUAL_VECTORS_PER_CONTEXT:
        raise ValueError("threshold neighborhood exceeded the stream bound")
    generator = random.Random(seed)
    while len(result) < ACTUAL_VECTORS_PER_CONTEXT:
        result.append(generator.randint(MIN_I32, MAX_I32))
    return result


def _write_hex(path: Path, values: list[int] | tuple[int, ...], bits: int, width: int) -> None:
    mask = (1 << bits) - 1
    path.write_text("".join(f"{value & mask:0{width}x}\n" for value in values), encoding="ascii")


def _tree_stream_record(context: int, raw: int, result: int) -> int:
    if not 0 <= context < 8 or not -128 <= result <= 127:
        raise ValueError("stream record field outside its representation")
    return (context << 40) | ((raw & 0xFFFFFFFF) << 8) | (result & 0xFF)


def _write_stream(path: Path, records: list[int]) -> None:
    path.write_text("".join(f"{record:011x}\n" for record in records), encoding="ascii")


def _generate_host_inputs(build: Path) -> dict[str, Any]:
    rows, tables, proof = _read_reference()
    selected = sorted({0, len(tables) // 7, 2 * len(tables) // 7,
                       3 * len(tables) // 7, 4 * len(tables) // 7,
                       5 * len(tables) // 7, 6 * len(tables) // 7, len(tables) - 1})
    if len(selected) != 8:
        raise ValueError("selected package channels did not provide eight distinct contexts")

    actual_trees: list[tuple[int, ...]] = []
    actual_probes: list[list[int]] = []
    actual_stream: list[int] = []
    c_vectors = bytearray()
    context_metadata: list[dict[str, Any]] = []
    for context, channel in enumerate(selected):
        original = tables[channel]
        tree = original + (SENTINEL,)
        banks = context_map.banked_table(tree)
        samples = _probe_values(original, 640 + context)
        expected_rows: list[int] = []
        for raw in samples:
            rank = context_map.search_banked_rank(banks, raw)
            direct = bisect.bisect_right(original, raw) - 127
            exact = rq.oracle(raw, rows[channel]["multiplier"])
            if rank - 127 != direct or direct != exact:
                raise ValueError(f"selected channel {channel} mismatch at raw {raw}")
            expected_rows.append(direct)
            c_vectors.extend(struct.pack("<dib", rows[channel]["multiplier"], raw, direct))
        actual_trees.append(tree)
        actual_probes.append(samples)
        context_metadata.append(dict(context=context, package_channel=channel,
                                     multiplier=rows[channel]["multiplier"],
                                     thresholds=254, sentinel_index=254,
                                     unique_thresholds=len(set(original))))
        _write_hex(build / f"tree_{context:02d}.hex", tree, 33, 9)

    for sample in range(ACTUAL_VECTORS_PER_CONTEXT):
        for context in range(8):
            raw = actual_probes[context][sample]
            result = context_map.search_banked_rank(context_map.banked_table(actual_trees[context]), raw) - 127
            actual_stream.append(_tree_stream_record(context, raw, result))
    _write_stream(build / "stream_actual.hex", actual_stream)

    synthetic_originals = [
        tuple([MIN_I32] * 254),
        tuple([SENTINEL] * 254),
        tuple([MIN_I32] * 5 + [-1] * 5 + [0] * 5 + [MAX_I32] * 5 + [SENTINEL] * 234),
    ]
    if any(len(row) != 254 for row in synthetic_originals):
        raise AssertionError("synthetic transition rows must contain 254 keys")
    synthetic_stream: list[int] = []
    for synthetic_id, original in enumerate(synthetic_originals):
        tree = original + (SENTINEL,)
        banks = context_map.banked_table(tree)
        samples = _probe_values(original, 780 + synthetic_id)
        _write_hex(build / f"tree_{synthetic_id + 8:02d}.hex", tree, 33, 9)
        for raw in samples:
            result = context_map.search_banked_rank(banks, raw) - 127
            if result != bisect.bisect_right(original, raw) - 127:
                raise ValueError(f"synthetic tree mismatch in case {synthetic_id}")
            synthetic_stream.append(_tree_stream_record(synthetic_id, raw, result))
    _write_stream(build / "stream_synthetic.hex", synthetic_stream)

    preserved_stream: list[int] = []
    for sample in range(PRESERVED_VECTORS_PER_CONTEXT):
        for context in range(3, 8):
            raw = actual_probes[context][sample]
            rank = context_map.search_rank(actual_trees[context], raw)
            preserved_stream.append(_tree_stream_record(context, raw, rank - 127))
    _write_stream(build / "stream_preserved.hex", preserved_stream)

    vectors_path = build / "oracle_vectors.bin"
    vectors_path.write_bytes(c_vectors)
    if len(c_vectors) % 13:
        raise AssertionError("C oracle record size is invalid")
    return dict(status="PASS_HOST_MAPPING_AND_ALL_CHANNEL_BOUNDARIES",
                complete_mapping=context_map.verify_complete_mapping(),
                all_package_channels=len(tables), selected_contexts=context_metadata,
                actual_stream_results=len(actual_stream), synthetic_stream_results=len(synthetic_stream),
                preserved_context_results=len(preserved_stream), c_oracle_vectors=len(c_vectors) // 13,
                threshold_artifact_sha256=sha(REFERENCE_TABLES),
                threshold_proof_sha256=sha(REFERENCE_REPORT),
                oracle_source_sha256=sha(REFERENCE_C),
                boundary_replay=_verify_all_channel_boundaries(rows, tables),
                config_semantics=dict(target_context_invalidated_on_begin=True,
                                      other_contexts_preserved=True,
                                      valid_only_after_complete_commit=True,
                                      reset_cancel_clear_all_contexts=True),
                source_proof_status=proof["status"])


def _tcl_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(" ", "\\ ")


def _write_synth_tcl(path: Path, build: Path) -> None:
    rtl = FIXTURE / "z100_requant_context.sv"
    rows: list[str] = [
        "set_param general.maxThreads 2",
        "create_project -in_memory -part xc7z100ffg900-2",
        f"read_verilog -sv {_tcl_path(rtl)}",
        "synth_design -top z100_requant_context -part xc7z100ffg900-2 -flatten_hierarchy none",
        "create_clock -name requant_clk -period 5.000 [get_ports clk]",
        f"report_utilization -file {_tcl_path(build / 'utilization.rpt')}",
        f"report_utilization -hierarchical -file {_tcl_path(build / 'utilization_hierarchical.rpt')}",
        f"report_timing_summary -delay_type max -max_paths 20 -file {_tcl_path(build / 'timing_summary.rpt')}",
        f"write_checkpoint -force {_tcl_path(build / 'post_synth.dcp')}",
        "set all_cells [get_cells -hier]",
        "set lut_count [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]",
        "set ff_count [llength [get_cells -hier -filter {REF_NAME =~ FD*}]]",
        "set ramb18_count [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]",
        "set ramb36_count [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]",
        "set dsp_count [llength [get_cells -hier -filter {REF_NAME =~ DSP48*}]]",
        "set unowned_ram_count 0",
        "for {set stage 0} {$stage < 8} {incr stage} {",
        "  set r18 0; set r36 0; set stage_lut 0; set stage_ff 0",
        "  set pattern [format {gen_stage_memory\\[%d\\]} $stage]",
        "  foreach cell $all_cells {",
        "    set cell_name [get_property NAME $cell]",
        "    set cell_ref [get_property REF_NAME $cell]",
        "    if {[regexp $pattern $cell_name]} {",
        "      if {[string match RAMB18* $cell_ref]} {incr r18}",
        "      if {[string match RAMB36* $cell_ref]} {incr r36}",
        "      if {[string match LUT* $cell_ref]} {incr stage_lut}",
        "      if {[string match FD* $cell_ref]} {incr stage_ff}",
        "    } elseif {[string match RAMB18* $cell_ref] || [string match RAMB36* $cell_ref]} {",
        "      incr unowned_ram_count",
        "    }",
        "  }",
        "  puts \"REQUANT_CONTEXT_STAGE stage=$stage DEPTH=[expr {8 * (1 << $stage)}] WIDTH=33 RAMB18=$r18 RAMB36=$r36 LUT=$stage_lut FF=$stage_ff\"",
        "}",
        "puts \"REQUANT_CONTEXT_SYNTH_RESULT LUT=$lut_count FF=$ff_count RAMB18=$ramb18_count RAMB36=$ramb36_count DSP=$dsp_count UNOWNED_RAM=$unowned_ram_count PERIOD_NS=5.000\"",
        "exit",
        "",
    ]
    path.write_text("\n".join(rows), encoding="utf-8")


def _run(command: list[str], cwd: Path, log: Path, commands: list[dict[str, Any]]) -> str:
    result = run_command(command, cwd, log)
    commands.append({key: value for key, value in result.items() if key != "output"})
    if result["return_code"] != 0:
        raise RuntimeError(f"command failed ({Path(command[0]).name}): {result['return_code']}")
    return str(result["output"])


def _artifact_inventory(build: Path, evidence: Path) -> dict[str, str]:
    """Hash every generated build/evidence file except the result that embeds this map."""
    paths = [path for root in (build, evidence) for path in root.rglob("*")
             if path.is_file() and path.name != "result.json"]
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}


def _synthesis_result(output: str, build: Path) -> dict[str, Any]:
    summary = re.findall(
        r"REQUANT_CONTEXT_SYNTH_RESULT LUT=(\d+) FF=(\d+) RAMB18=(\d+) RAMB36=(\d+) DSP=(\d+) UNOWNED_RAM=(\d+) PERIOD_NS=([0-9.]+)",
        output,
    )
    stage_rows = re.findall(
        r"REQUANT_CONTEXT_STAGE stage=(\d+) DEPTH=(\d+) WIDTH=(\d+) RAMB18=(\d+) RAMB36=(\d+) LUT=(\d+) FF=(\d+)",
        output,
    )
    if len(summary) != 1 or len(stage_rows) != 8:
        raise RuntimeError("Vivado output lacks one resource summary and eight stage mappings")
    lut, ff, ramb18, ramb36, dsp, unowned, period = summary[0]
    stages = [dict(stage=int(s), depth=int(d), width_bits=int(w), ramb18=int(r18), ramb36=int(r36),
                   ramb18_equivalent=int(r18) + 2 * int(r36), primitive_luts=int(slut), primitive_ffs=int(sff))
              for s, d, w, r18, r36, slut, sff in stage_rows]
    if [row["stage"] for row in stages] != list(range(8)):
        raise RuntimeError("Vivado stage mapping markers were not in depth order")
    total_eq = int(ramb18) + 2 * int(ramb36)
    utilization = (build / "utilization.rpt").read_text(encoding="utf-8", errors="replace")
    lut_match = re.search(r"^\|\s*Slice LUTs\s*\|\s*(\d+)", utilization, re.M)
    ff_match = re.search(r"^\|\s*Slice Registers\s*\|\s*(\d+)", utilization, re.M)
    dsp_match = re.search(r"^\|\s*DSPs\s*\|\s*(\d+)", utilization, re.M)
    if not lut_match or not ff_match or not dsp_match:
        raise RuntimeError("Vivado utilization report is missing Slice LUT/Register/DSP totals")
    slice_lut, slice_ff, slice_dsp = int(lut_match.group(1)), int(ff_match.group(1)), int(dsp_match.group(1))
    result = dict(status="PASS_OOC_SYNTH_ONLY", primitive_luts=int(lut), primitive_ffs=int(ff),
                  slice_luts=slice_lut, slice_flip_flops=slice_ff, ramb18=int(ramb18), ramb36=int(ramb36),
                  ramb18_equivalent=total_eq, dsp=int(dsp), utilization_report_dsp=slice_dsp,
                  unowned_ram_primitives=int(unowned), stages=stages, budget=SYNTHESIS_BUDGET,
                  period_ns=float(period), timing_scope="post-synthesis max-only estimate; no hold, placement, route or frequency acceptance",
                  hierarchy_report_sha256=sha(build / "utilization_hierarchical.rpt"),
                  timing_report_sha256=sha(build / "timing_summary.rpt"),
                  checkpoint_sha256=sha(build / "post_synth.dcp"))
    if any(stage["ramb18_equivalent"] < 1 for stage in stages):
        raise RuntimeError("one or more search stages did not map to block RAM")
    if stages[7]["ramb18_equivalent"] < 2:
        raise RuntimeError("stage 7 did not map its 1024x33 storage to at least two RAMB18 equivalents")
    if total_eq > SYNTHESIS_BUDGET["ramb18_equivalent"]:
        raise RuntimeError("OOC RAMB18-equivalent budget exceeded")
    if slice_lut > SYNTHESIS_BUDGET["slice_lut"] or slice_ff > SYNTHESIS_BUDGET["flip_flops"]:
        raise RuntimeError("OOC Slice LUT or flip-flop budget exceeded")
    if int(dsp) != 0 or slice_dsp != 0 or int(unowned) != 0:
        raise RuntimeError("OOC DSP or stage RAM ownership budget failed")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vivado", type=Path, default=VIVADO_DEFAULT)
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    evidence.mkdir(parents=True)
    build.mkdir(parents=True)
    source_files = [FIXTURE / "z100_requant_context.sv", FIXTURE / "tb_z100_requant_context.sv",
                    Path(__file__).resolve(), ROOT / "deployment/tests/test_z100_requant_context.py",
                    ROOT / "tools/z100_requant_context_map.py", ROOT / "docs/z100_requant_context.md",
                    ROOT / "tools/z100_requant_thresholds.py", ROOT / "tools/validate_z100_requant_pipeline.py",
                    REFERENCE_C, REFERENCE_TABLES, REFERENCE_REPORT,
                    PACKAGE / "MODEL.V8P", PACKAGE / "v8_generated_model.h"]
    source_hashes = {str(path.relative_to(ROOT)): sha(path) for path in source_files}
    (evidence / "launch.json").write_text(json.dumps(dict(run_id=run_id, source_sha256=source_hashes,
                                                           part="xc7z100ffg900-2",
                                                           max_threads=2,
                                                           budget=SYNTHESIS_BUDGET), indent=2) + "\n",
                                                 encoding="utf-8")
    commands: list[dict[str, Any]] = []
    result: dict[str, Any] = dict(run_id=run_id, status="RUNNING", source_sha256=source_hashes,
                                 physical_board_tested=False, production_integrated=False,
                                 final_model_accepted=False, release_eligible=False,
                                 route_or_bitstream_attempted=False)
    try:
        host = _generate_host_inputs(build)
        result["host_validation"] = host
        print(json.dumps(dict(event="host_validation_complete", channels=host["all_package_channels"],
                              boundary_probes=host["boundary_replay"]["threshold_boundary_probes"])), flush=True)

        gcc = Path("C:/cbian/mingw64/bin/gcc.exe")
        oracle_exe = build / "upper_bound_oracle.exe"
        _run([str(gcc), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-fast-math",
              "-ffp-contract=off", str(REFERENCE_C), "-lm", "-o", str(oracle_exe)],
             build, evidence / "gcc.log", commands)
        c_output = _run([str(oracle_exe), str(build / "oracle_vectors.bin")], build,
                        evidence / "c_oracle.log", commands)
        expected_c = host["c_oracle_vectors"]
        if f"C_ORACLE_PASS vectors={expected_c}" not in c_output:
            raise RuntimeError("frozen C double oracle did not validate every generated actual-context vector")
        result["c_oracle"] = dict(status="PASS", actual_context_vectors=expected_c,
                                  expected_record_bytes=13, output=c_output.strip())

        bindir = args.vivado.parent
        phases = [
            ("xvlog", [str(bindir / "xvlog.bat"), "-sv", str(FIXTURE / "z100_requant_context.sv"),
                        str(FIXTURE / "tb_z100_requant_context.sv")]),
            ("xelab", [str(bindir / "xelab.bat"), "-mt", "2", "tb_z100_requant_context", "-s", "requant_context_sim"]),
            ("xsim", [str(bindir / "xsim.bat"), "requant_context_sim", "-runall"]),
        ]
        simulation_output = ""
        for name, command in phases:
            simulation_output = _run(command, build, evidence / f"{name}.log", commands)
        if "Fatal:" in simulation_output or "FAIL" in simulation_output:
            raise RuntimeError("XSim reported a fatal/error result")
        match = re.search(
            r"REQUANT_CONTEXT_PASS actual_results=(\d+) synthetic_results=(\d+) preserved_context_results=(\d+) contexts=(\d+) mapped_indices=(\d+) sentinel_index=(\d+) config_errors=(\d+) excessive_write=(\d+) early_commit=(\d+) invalid_sentinel=(\d+) decreasing_key=(\d+) cancel_stages=(\d+) reset_stages=(\d+) config_flush_cancel=(\d+) config_flush_reset=(\d+) full_flush_cancel=(\d+) full_flush_reset=(\d+) latency_no_stall=(\d+) steady_accept_ii=(\d+) steady_result_ii=(\d+)",
            simulation_output,
        )
        expected_summary = (8192, 3072, 1280, 8, 255, 254, 4, 1, 1, 1, 1, 8, 8,
                            1, 1, 1, 1, 8, 1, 1)
        if not match or tuple(map(int, match.groups())) != expected_summary:
            raise RuntimeError("XSim coverage summary did not match eight-context acceptance criteria")
        stream_rows = [dict(stream=int(stream_id), vectors=int(vectors), latency_no_stall=int(latency),
                            latency_min=int(lat_min), latency_max=int(lat_max), input_ii=int(input_ii),
                            result_ii=int(result_ii), blocked_cycles=int(blocked))
                       for stream_id, vectors, latency, lat_min, lat_max, input_ii, result_ii, blocked
                       in re.findall(r"CONTEXT_STREAM id=(\d+) vectors=(\d+) latency_no_stall=(\d+) latency_min=(\d+) latency_max=(\d+) input_ii=(\d+) result_ii=(\d+) blocked_cycles=(\d+)", simulation_output)]
        if len(stream_rows) != 3 or any(row["input_ii"] != 1 or row["result_ii"] != 1 or
                                       row["blocked_cycles"] <= 0 or row["latency_no_stall"] != 8
                                       for row in stream_rows):
            raise RuntimeError("XSim did not prove context stream II, latency and backpressure coverage")
        stage_flushes = [(int(stage), int(reset_mode)) for stage, reset_mode in
                         re.findall(r"CONTEXT_FLUSH_PASS stage=(\d+) reset=(\d+)", simulation_output)]
        expected_stage_flushes = [(stage, reset_mode) for reset_mode in range(2) for stage in range(8)]
        config_flushes = sorted(int(mode) for mode in
                                re.findall(r"CONTEXT_CONFIG_FLUSH_PASS reset=(\d+)", simulation_output))
        full_flushes = sorted(int(mode) for mode in
                              re.findall(r"CONTEXT_FULL_FLUSH_PASS reset=(\d+)", simulation_output))
        if stage_flushes != expected_stage_flushes or config_flushes != [0, 1] or full_flushes != [0, 1]:
            raise RuntimeError("XSim is missing exact-stage, partial-config, or full-pipeline flush markers")
        result["simulation"] = dict(status="PASS", actual_results=8192, synthetic_results=3072,
                                    preserved_context_results=1280, interleaved_contexts=8,
                                    random_output_backpressure=True, context_alignment_checked=True,
                                    invalid_context_rejected=True, failed_load_preserves_other_contexts=True,
                                    configuration_errors=4, over_write_rejected=True,
                                    early_commit_rejected=True, invalid_sentinel_rejected=True,
                                    decreasing_key_rejected=True, cancellation_each_stage=8,
                                    reset_each_stage=8, no_stall_latency_cycles=8,
                                    stage_flush_markers=stage_flushes,
                                    partial_configuration_flush_modes=config_flushes,
                                    full_pipeline_flush_modes=full_flushes,
                                    full_pipeline_filled_with_output_stalled=True,
                                    partial_configuration_cancel_and_reset=True,
                                    reconfiguration_recovery_probes=4,
                                    steady_accept_interval_cycles=1, steady_result_interval_cycles=1,
                                    streams=stream_rows)

        tcl = build / "synth.tcl"
        _write_synth_tcl(tcl, build)
        synth_output = _run([str(args.vivado), "-mode", "batch", "-nojournal", "-nolog", "-source", str(tcl)],
                            build, evidence / "vivado_synth.log", commands)
        result["synthesis"] = _synthesis_result(synth_output, build)
        result["commands"] = commands
        after = {str(path.relative_to(ROOT)): sha(path) for path in source_files}
        result["source_sha256_after"] = after
        if after != source_hashes:
            raise RuntimeError("frozen input source changed during the experiment")
        result["artifact_sha256"] = _artifact_inventory(build, evidence)
        result["scope"] = dict(single_lane=True, contexts=8, table_keys=255, sentinel_index=254,
                               stage_nodes=[1, 2, 4, 8, 16, 32, 64, 128],
                               memory_depths=[8, 16, 32, 64, 128, 256, 512, 1024],
                               memory_width_bits=33, timing_closed=False, placement=False,
                               route=False, bitstream_created=False, physical_board_tested=False)
        result["status"] = "PASS_PRIVATE_8_CONTEXT_REQUANT_OOC_SYNTH"
    except Exception as exc:
        result["status"] = "FAILED"
        result["failure"] = f"{type(exc).__name__}: {exc}"
        result["commands"] = commands
        result["source_sha256_after"] = {str(path.relative_to(ROOT)): sha(path) for path in source_files if path.exists()}
        result["artifact_sha256"] = _artifact_inventory(build, evidence)
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise

    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status=result["status"], run_id=run_id, report=str(evidence / "result.json"),
                          host_validation=host, c_oracle=result["c_oracle"],
                          simulation=result["simulation"], synthesis=result["synthesis"]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
