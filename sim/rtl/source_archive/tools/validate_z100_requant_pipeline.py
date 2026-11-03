"""Validate an isolated single-lane, eight-stage exact requant search pipeline."""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
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
import z100_requant_thresholds as rq  # noqa: E402
from validate_z100_reuse_sync import VIVADO_DEFAULT, run_command, sha256  # noqa: E402

FIXTURE = ROOT / "deployment/hardware/z100_2026/requant_pipeline_v1"
BUILD_ROOT = ROOT / "deployment/build/z100_requant_pipeline_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/requant_pipeline_v1"
PACKAGE = ROOT / "deployment/candidates/pin640/validation/20261021_verified/pin/pipeline/package"
REFERENCE_TABLES = ROOT / "deployment/build/z100_requant_threshold_v0/20261021T134827Z_a66a4f65/all_thresholds.bin"
REFERENCE_REPORT = ROOT / "validation/board_z100/requant_threshold_v0/20261021T134827Z_a66a4f65/result.json"
REFERENCE_C = ROOT / "deployment/hardware/z100_2026/requant_threshold_v0/oracle.c"
REFERENCE_TABLE_SHA256 = "f425a5e2311a6739dc5f83daaa75fc6df32d9f9e46a025268d9125964e75c2af"
MIN_I32 = -(1 << 31)
MAX_I32 = (1 << 31) - 1
SENTINEL = 1 << 31
CASE_COUNT = 11
VECTORS_PER_CASE = 1024


def direct_upper_bound(original: list[int] | tuple[int, ...], raw: int) -> int:
    """Independent reference: upper_bound over 254 transitions, then clamp offset."""
    if type(raw) is not int or not MIN_I32 <= raw <= MAX_I32:
        raise ValueError("raw value must be signed INT32")
    if len(original) != 254:
        raise ValueError("expected 254 original thresholds")
    return bisect.bisect_right(original, raw) - 127


def append_sentinel(original: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    """Validate an ordered signed33 transition row and append its +2^31 key."""
    if len(original) != 254:
        raise ValueError("expected exactly 254 original thresholds")
    previous: int | None = None
    for value in original:
        if type(value) is not int or not MIN_I32 <= value <= SENTINEL:
            raise ValueError("threshold is outside signed33 transition range")
        if previous is not None and value < previous:
            raise ValueError("threshold row is not nondecreasing")
        previous = value
    tree = tuple(original) + (SENTINEL,)
    if tree[-1] != SENTINEL:
        raise AssertionError("sentinel append failed")
    return tree


def tree_search_upper_bound(tree: list[int] | tuple[int, ...], raw: int) -> int:
    """Reference for the 255-key tree's insertion count, excluding never-crossed sentinel."""
    if len(tree) != 255 or tree[-1] != SENTINEL:
        raise ValueError("expected 255 keys with the final sentinel")
    if type(raw) is not int or not MIN_I32 <= raw <= MAX_I32:
        raise ValueError("raw value must be signed INT32")
    return bisect.bisect_right(tree, raw) - 127


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
    if sha(REFERENCE_REPORT) != "2af534a2f4b3ba20ce5bbefb190279c8b3b7405f9470ab1e3e84471080d2f189":
        # The proof JSON is immutable input; this hash also catches accidental report replacement.
        raise ValueError("pinned proof report hash changed")
    package_rows = rq.package_multipliers(PACKAGE)
    if len(package_rows) != 5515:
        raise ValueError(f"expected 5515 packaged convolution channels, got {len(package_rows)}")
    payload = REFERENCE_TABLES.read_bytes()
    if len(payload) != len(package_rows) * 254 * 8:
        raise ValueError("threshold artifact byte count does not match package channels")
    tables = [tuple(row) for row in struct.iter_unpack("<254q", payload)]
    if len(tables) != len(package_rows):
        raise ValueError("threshold row count mismatch")
    for index, row in enumerate(tables):
        append_sentinel(row)
        if any(type(value) is not int for value in row):
            raise ValueError(f"non-integer table value at channel {index}")
    # Independently regenerate representative rows from the exact packaged binary64 values.
    representative = sorted({0, len(tables) // 7, 2 * len(tables) // 7,
                             3 * len(tables) // 7, 4 * len(tables) // 7,
                             5 * len(tables) // 7, 6 * len(tables) // 7, len(tables) - 1})
    for index in representative:
        if tuple(rq.thresholds(package_rows[index]["multiplier"])) != tables[index]:
            raise ValueError(f"threshold artifact differs from exact host generation at channel {index}")
    return package_rows, tables, proof


def _probes(table: tuple[int, ...], seed: int) -> list[int]:
    points = {MIN_I32, MAX_I32, -1, 0, 1}
    for key in table:
        for delta in (-1, 0, 1):
            raw = key + delta
            if MIN_I32 <= raw <= MAX_I32:
                points.add(raw)
    values = sorted(points)
    if len(values) > VECTORS_PER_CASE:
        raise ValueError("threshold neighborhood set exceeds fixture bound")
    rng = random.Random(seed)
    while len(values) < VECTORS_PER_CASE:
        values.append(rng.randint(MIN_I32, MAX_I32))
    return values


def _synthetic_tables() -> list[tuple[int, ...]]:
    all_minimum = [MIN_I32] * 254
    all_sentinel = [SENTINEL] * 254
    duplicates = [MIN_I32] * 5 + [-1] * 5 + [0] * 5 + [MAX_I32] * 5 + [SENTINEL] * 234
    if len(duplicates) != 254:
        raise AssertionError("synthetic duplicate table length")
    return [append_sentinel(row) for row in (all_minimum, all_sentinel, duplicates)]


def _write_hex(path: Path, values: list[int] | tuple[int, ...], bits: int, width: int) -> None:
    mask = (1 << bits) - 1
    path.write_text("".join(f"{value & mask:0{width}x}\n" for value in values), encoding="ascii")


def _generate_inputs(build: Path) -> dict[str, Any]:
    rows, all_tables, proof = _read_reference()
    selected = sorted({0, len(all_tables) // 7, 2 * len(all_tables) // 7,
                       3 * len(all_tables) // 7, 4 * len(all_tables) // 7,
                       5 * len(all_tables) // 7, 6 * len(all_tables) // 7, len(all_tables) - 1})
    cases: list[tuple[tuple[int, ...], float | None, str]] = []
    for index in selected:
        cases.append((append_sentinel(all_tables[index]), rows[index]["multiplier"], f"channel_{index}"))
    cases.extend((table, None, f"synthetic_{number}") for number, table in enumerate(_synthetic_tables()))

    c_vectors = bytearray()
    metadata: list[dict[str, Any]] = []
    for case_id, (tree, multiplier, label) in enumerate(cases):
        original = tree[:254]
        samples = _probes(original, 640 + case_id)
        expected: list[int] = []
        for raw in samples:
            reference = direct_upper_bound(original, raw)
            tree_reference = tree_search_upper_bound(tree, raw)
            if reference != tree_reference:
                raise ValueError(f"tree/sentinel reference mismatch in {label}")
            if multiplier is not None:
                exact_oracle = rq.oracle(raw, multiplier)
                if reference != exact_oracle:
                    raise ValueError(f"threshold result differs from packaged binary64 oracle in {label}")
                c_vectors.extend(struct.pack("<dib", multiplier, raw, reference))
            expected.append(reference)
        _write_hex(build / f"tree_{case_id:02d}.hex", tree, 33, 9)
        _write_hex(build / f"input_{case_id:02d}.hex", samples, 32, 8)
        _write_hex(build / f"expected_{case_id:02d}.hex", expected, 8, 2)
        metadata.append(dict(case_id=case_id, label=label, original_thresholds=254, tree_keys=255,
                             expected_vectors=len(samples), synthetic=multiplier is None,
                             packaged_multiplier=multiplier,
                             unique_original_thresholds=len(set(original)),
                             all_minimum=all(value == MIN_I32 for value in original),
                             all_sentinel=all(value == SENTINEL for value in original)))

    vectors_path = build / "oracle_vectors.bin"
    vectors_path.write_bytes(c_vectors)
    if len(c_vectors) % 13:
        raise AssertionError("C oracle vectors have an invalid record size")
    return dict(channels_validated=len(all_tables), selected_channels=selected, cases=metadata,
                actual_c_oracle_vectors=len(c_vectors) // 13,
                actual_threshold_sha256=sha(REFERENCE_TABLES), original_proof_status=proof["status"])


def _write_synth_tcl(path: Path, rtl: Path, build: Path) -> None:
    def tcl_path(value: Path) -> str:
        return str(value).replace("\\", "/").replace(" ", "\\ ")

    path.write_text(
        "\n".join([
            "set_param general.maxThreads 2",
            "create_project -in_memory -part xc7z100ffg900-2",
            f"read_verilog -sv {tcl_path(rtl)}",
            "synth_design -top z100_requant_pipeline -part xc7z100ffg900-2 -flatten_hierarchy none",
            "create_clock -name requant_clk -period 5.000 [get_ports clk]",
            f"report_utilization -file {tcl_path(build / 'utilization.rpt')}",
            f"report_timing_summary -delay_type max -max_paths 20 -file {tcl_path(build / 'timing_summary.rpt')}",
            f"write_checkpoint -force {tcl_path(build / 'post_synth.dcp')}",
            "set lut_count [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]",
            "set ff_count [llength [get_cells -hier -filter {REF_NAME =~ FD*}]]",
            "set ramb18_count [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]",
            "set ramb36_count [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]",
            "set dsp_count [llength [get_cells -hier -filter {REF_NAME =~ DSP48*}]]",
            "puts \"REQUANT_PIPELINE_SYNTH_RESULT LUT=$lut_count FF=$ff_count RAMB18=$ramb18_count RAMB36=$ramb36_count DSP=$dsp_count PERIOD_NS=5.000\"",
            "exit",
            "",
        ]), encoding="utf-8")


def _run(command: list[str], cwd: Path, log: Path, commands: list[dict[str, Any]]) -> str:
    result = run_command(command, cwd, log)
    commands.append({key: value for key, value in result.items() if key != "output"})
    if result["return_code"] != 0:
        raise RuntimeError(f"command failed ({Path(command[0]).name}): {result['return_code']}")
    return str(result["output"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-synth", action="store_true", help="run XSim and host checks only")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    evidence.mkdir(parents=True)
    build.mkdir(parents=True)
    source_files = [FIXTURE / "z100_requant_pipeline.sv", FIXTURE / "tb_z100_requant_pipeline.sv",
                    Path(__file__).resolve(), ROOT / "deployment/tests/test_z100_requant_pipeline.py",
                    ROOT / "docs/z100_requant_pipeline.md", ROOT / "tools/z100_requant_thresholds.py",
                    REFERENCE_C, REFERENCE_TABLES, REFERENCE_REPORT,
                    PACKAGE / "MODEL.V8P", PACKAGE / "v8_generated_model.h"]
    source_hashes = {str(path.relative_to(ROOT)): sha(path) for path in source_files}
    (evidence / "launch.json").write_text(json.dumps(dict(run_id=run_id, source_sha256=source_hashes), indent=2) + "\n", encoding="utf-8")
    commands: list[dict[str, Any]] = []
    result: dict[str, Any] = dict(run_id=run_id, status="RUNNING", source_sha256=source_hashes,
                                  physical_board_tested=False, production_integrated=False,
                                  final_model_accepted=False, release_eligible=False)
    try:
        host = _generate_inputs(build)
        result["host_validation"] = host

        gcc = Path("C:/cbian/mingw64/bin/gcc.exe")
        oracle_exe = build / "upper_bound_oracle.exe"
        compile_output = _run([str(gcc), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                               "-fno-fast-math", "-ffp-contract=off", str(REFERENCE_C), "-lm", "-o", str(oracle_exe)],
                              build, evidence / "gcc.log", commands)
        if "error:" in compile_output.lower():
            raise RuntimeError("C oracle compilation emitted an error")
        oracle_output = _run([str(oracle_exe), str(build / "oracle_vectors.bin")], build,
                             evidence / "c_oracle.log", commands)
        expected_c = host["actual_c_oracle_vectors"]
        if f"C_ORACLE_PASS vectors={expected_c}" not in oracle_output:
            raise RuntimeError("C double reference did not cover the generated actual-channel vectors")

        bindir = VIVADO_DEFAULT.parent
        commands_sim = [
            ("xvlog", [str(bindir / "xvlog.bat"), "-sv", str(FIXTURE / "z100_requant_pipeline.sv"),
                        str(FIXTURE / "tb_z100_requant_pipeline.sv")]),
            ("xelab", [str(bindir / "xelab.bat"), "-mt", "2", "tb_z100_requant_pipeline", "-s", "requant_pipeline_sim"]),
            ("xsim", [str(bindir / "xsim.bat"), "requant_pipeline_sim", "-runall"]),
        ]
        xsim_output = ""
        for name, command in commands_sim:
            xsim_output = _run(command, build, evidence / f"{name}.log", commands)
        if "Fatal:" in xsim_output or "FAIL" in xsim_output:
            raise RuntimeError("XSim reported a fatal/error result")
        match = re.search(r"REQUANT_PIPELINE_PASS cases=(\d+) actual_tables=(\d+) synthetic_tables=(\d+) config_errors=(\d+) premature_commit=(\d+) cancel=(\d+) reset=(\d+) latency_no_stall=(\d+) steady_accept_ii=(\d+) steady_result_ii=(\d+)", xsim_output)
        if not match or tuple(map(int, match.groups())) != (11264, 8, 3, 2, 1, 1, 1, 8, 1, 1):
            raise RuntimeError("XSim coverage summary did not match expected pipeline coverage")
        case_metrics = [dict(case_id=int(case), vectors=int(vectors), no_stall_latency=int(latency),
                             observed_latency_min=int(min_latency), observed_latency_max=int(max_latency),
                             accepted_interval_cycles=int(accept_ii), result_interval_cycles=int(result_ii),
                             blocked_output_cycles=int(blocked))
                        for case, vectors, latency, min_latency, max_latency, accept_ii, result_ii, blocked
                        in re.findall(r"PIPE_CASE id=(\d+) vectors=(\d+) no_stall_latency=(\d+) observed_latency_min=(\d+) observed_latency_max=(\d+) accept_ii=(\d+) result_ii=(\d+) blocked_cycles=(\d+)", xsim_output)]
        if len(case_metrics) != CASE_COUNT or any(row["no_stall_latency"] != 8 or row["accepted_interval_cycles"] != 1 or
                                                  row["result_interval_cycles"] != 1 or row["blocked_output_cycles"] == 0
                                                  for row in case_metrics):
            raise RuntimeError("XSim did not demonstrate eight-cycle no-stall latency and steady II=1 per case")
        result["simulation"] = dict(status="PASS", total_results=int(match.group(1)), actual_tables=int(match.group(2)),
                                    synthetic_tables=int(match.group(3)), configuration_errors=int(match.group(4)),
                                    premature_commit_rejections=int(match.group(5)), cancellation_tests=int(match.group(6)),
                                    reset_tests=int(match.group(7)), no_stall_latency_cycles=int(match.group(8)),
                                    steady_accept_interval_cycles=int(match.group(9)),
                                    steady_result_interval_cycles=int(match.group(10)), cases=case_metrics)

        synthesis = None
        if not args.no_synth:
            tcl = build / "synth.tcl"
            _write_synth_tcl(tcl, FIXTURE / "z100_requant_pipeline.sv", build)
            synth_output = _run([str(VIVADO_DEFAULT), "-mode", "batch", "-nojournal", "-nolog", "-source", str(tcl)],
                                build, evidence / "vivado_synth.log", commands)
            synth_match = re.findall(r"REQUANT_PIPELINE_SYNTH_RESULT LUT=(\d+) FF=(\d+) RAMB18=(\d+) RAMB36=(\d+) DSP=(\d+) PERIOD_NS=([0-9.]+)", synth_output)
            if len(synth_match) != 1:
                raise RuntimeError("Vivado synthesis resource summary was missing or duplicated")
            values = synth_match[0]
            synthesis = dict(status="PASS_OOC_SYNTH_ONLY", lut=int(values[0]), flip_flops=int(values[1]),
                             ramb18=int(values[2]), ramb36=int(values[3]), dsp=int(values[4]),
                             requested_period_ns=float(values[5]), replicated_synchronous_tables=8,
                             table_depth=255, table_width_bits=33,
                             timing_scope="post-synthesis estimate only; no placement or route")
            if synthesis["ramb18"] + 2 * synthesis["ramb36"] < 8:
                raise RuntimeError("synthesis did not preserve eight table read replicas")
        result["synthesis"] = synthesis
        result["commands"] = commands
        result["source_sha256_after"] = {str(path.relative_to(ROOT)): sha(path) for path in source_files}
        if result["source_sha256_after"] != source_hashes:
            raise RuntimeError("source changed during validation")
        artifacts = [*build.glob("*.hex"), build / "oracle_vectors.bin", oracle_exe,
                     *evidence.glob("*.log"), build / "synth.tcl"]
        artifacts.extend(path for path in (build / "utilization.rpt", build / "timing_summary.rpt", build / "post_synth.dcp") if path.exists())
        result["artifact_sha256"] = {str(path.relative_to(ROOT)): sha(path) for path in artifacts}
        result["status"] = "PASS_PRIVATE_SINGLE_LANE_REQUANT_PIPELINE"
        result["scope"] = dict(lane_count=1, fixed_binary_search_stages=8, steady_state_ii_cycles=1,
                               no_stall_accept_to_result_latency_cycles=8, external_protocol_or_dma_integrated=False,
                               timing_closed=False, bitstream_created=False)
    except Exception as exc:
        result["status"] = "FAILED"
        result["failure"] = f"{type(exc).__name__}: {exc}"
        result["commands"] = commands
        result["source_sha256_after"] = {str(path.relative_to(ROOT)): sha(path) for path in source_files if path.exists()}
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise

    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status=result["status"], run_id=run_id, report=str(evidence / "result.json"),
                          simulation=result["simulation"], synthesis=result["synthesis"]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
