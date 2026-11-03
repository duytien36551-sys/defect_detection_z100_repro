"""Validate the private 32-lane exact requantizer against current C-checked tables."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import z100_requant_thresholds as rq  # noqa: E402
from validate_z100_requant_thresholds import probes  # noqa: E402

FIXTURE = ROOT / "deployment/hardware/z100_2026/requant_vector_v1"
RTL = FIXTURE / "z100_requant_vector.sv"
TB = FIXTURE / "tb_z100_requant_vector.sv"
BUILD_ROOT = ROOT / "deployment/build/z100_requant_vector_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/requant_vector_v1"
CURRENT_RUN = "20261023T123433.385667Z_a3372b64"
CURRENT_BUILD = ROOT / "deployment/build/z100_current_requant_tables" / CURRENT_RUN
CURRENT_EVIDENCE = ROOT / "validation/board_z100/current_requant_tables" / CURRENT_RUN
PACKAGE = ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package"
GRAPH = PACKAGE.parent / "model/graph.json"
NATIVE = ROOT / "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef/manifest.json"
TABLE_REPORT = CURRENT_EVIDENCE / "result.json"
TABLES = CURRENT_BUILD / "thresholds_254_i64.bin"
BOUNDARIES = CURRENT_BUILD / "boundaries.bin"
PACKED_TREES = CURRENT_BUILD / "trees_255_i33_le5.bin"
CHANNEL_INDEX = CURRENT_BUILD / "channel_index.json"
ORACLE_C = ROOT / "deployment/hardware/z100_2026/requant_threshold_v0/oracle.c"
ORACLE_PY = ROOT / "tools/z100_requant_thresholds.py"
PROBE_PY = ROOT / "tools/validate_z100_requant_thresholds.py"
SENTINEL = 1 << 31
KEY_MIN = -(1 << 31)
MAX_LANES = 32
EXPECTED_PACKAGE_SHA256 = "96211aa416da6b23955a8b62cca594275daaa4db3e3954632960707c0ec0d44f"
EXPECTED_HEADER_SHA256 = "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5"
EXPECTED_GRAPH_SHA256 = "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8"
EXPECTED_TABLE_ARTIFACTS = {
    "deployment\\build\\z100_current_requant_tables\\20261023T123433.385667Z_a3372b64\\boundaries.bin":
        "1c1d1ace7326729b8aa375709973ad28499b5af1464fd50543c0f57b5c01cc97",
    "deployment\\build\\z100_current_requant_tables\\20261023T123433.385667Z_a3372b64\\channel_index.json":
        "c2172462db9099370fb6e026538ef4dc683b158304dfcc1b1b8f99e3863b8147",
    "deployment\\build\\z100_current_requant_tables\\20261023T123433.385667Z_a3372b64\\thresholds_254_i64.bin":
        "d9976d7627edc76656fb9e9084011b996a3cb323c30cd8147f6ee4d2fd04b203",
    "deployment\\build\\z100_current_requant_tables\\20261023T123433.385667Z_a3372b64\\trees_255_i33_le5.bin":
        "7d04a7a43ce9799111a07697641c70d52163fb354c306c672701181648ca1db8",
}
EXPECTED_XSIM = Path("C:/appload/2026.1/Vivado/bin")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(paths: list[Path]) -> dict[str, dict[str, Any]]:
    return {
        str(path.relative_to(ROOT)).replace("/", "\\"): {
            "bytes": path.stat().st_size,
            "sha256": sha(path),
        }
        for path in paths
    }


def _report_artifact(report: dict[str, Any], relative_windows_path: str) -> str | None:
    values = report.get("artifact_sha256", {})
    if relative_windows_path in values:
        return values[relative_windows_path]
    return values.get(relative_windows_path.replace("\\", "/"))


def source_paths() -> list[Path]:
    return [
        RTL, TB, Path(__file__).resolve(), PACKAGE / "MODEL.V8P",
        PACKAGE / "v8_generated_model.h", GRAPH, NATIVE, TABLE_REPORT,
        TABLES, BOUNDARIES, PACKED_TREES, CHANNEL_INDEX,
        ORACLE_C, ORACLE_PY, PROBE_PY,
    ]


def validate_frozen_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    report = json.loads(TABLE_REPORT.read_text(encoding="utf-8"))
    if report.get("status") != "PASS_CURRENT_PACKAGE_EXACT_THRESHOLDS_HOST_ONLY":
        raise ValueError("current table evidence is not passing")
    if (report.get("channels"), report.get("convolution_nodes"), report.get("c_boundary_vectors"),
        report.get("keys_per_channel"), report.get("threshold_bits"), report.get("sentinel_index")) != (
        5419, 63, 4_156_373, 255, 33, 254
    ):
        raise ValueError("current table evidence has unexpected coverage")
    if sha(PACKAGE / "MODEL.V8P") != EXPECTED_PACKAGE_SHA256:
        raise ValueError("frozen package hash mismatch")
    if sha(PACKAGE / "v8_generated_model.h") != EXPECTED_HEADER_SHA256:
        raise ValueError("frozen package header hash mismatch")
    if sha(GRAPH) != EXPECTED_GRAPH_SHA256:
        raise ValueError("frozen graph hash mismatch")
    for relative, expected_hash in EXPECTED_TABLE_ARTIFACTS.items():
        path = ROOT / Path(relative.replace("\\", "/"))
        if sha(path) != expected_hash or _report_artifact(report, relative) != expected_hash:
            raise ValueError(f"current table artifact hash mismatch: {relative}")
    if sha(ORACLE_C) != report["source_sha256"]["deployment\\hardware\\z100_2026\\requant_threshold_v0\\oracle.c"]:
        raise ValueError("C oracle source is no longer the source bound by table evidence")

    channel_rows = json.loads(CHANNEL_INDEX.read_text(encoding="utf-8"))
    if len(channel_rows) != report["channels"]:
        raise ValueError("channel index length mismatch")
    if TABLES.stat().st_size != len(channel_rows) * 254 * 8:
        raise ValueError("original 254-key table byte count mismatch")
    if PACKED_TREES.stat().st_size != len(channel_rows) * 255 * 5:
        raise ValueError("packed 255-key tree byte count mismatch")
    native = json.loads(NATIVE.read_text(encoding="utf-8"))
    if native.get("source_package_sha256") != EXPECTED_PACKAGE_SHA256 or \
       native.get("source_header_sha256") != EXPECTED_HEADER_SHA256 or \
       native.get("source_graph_sha256") != EXPECTED_GRAPH_SHA256:
        raise ValueError("native job manifest is not bound to the current model")
    return report, channel_rows, native.get("jobs", [])


def _read_current_tables(channel_rows: list[dict[str, Any]]) -> list[tuple[int, ...]]:
    payload = TABLES.read_bytes()
    return [tuple(v[0] for v in struct.iter_unpack("<q", payload[i * 254 * 8:(i + 1) * 254 * 8]))
            for i in range(len(channel_rows))]


def _validate_groups(channel_rows: list[dict[str, Any]], manifest_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_node: dict[int, list[int]] = {}
    for index, row in enumerate(channel_rows):
        by_node.setdefault(int(row["node"]), []).append(index)
    groups: list[dict[str, Any]] = []
    for node, indices in by_node.items():
        channel_numbers = [int(channel_rows[index]["channel"]) for index in indices]
        if channel_numbers != list(range(len(indices))):
            raise ValueError(f"channel index order is not contiguous at node {node}")
        for offset in range(0, len(indices), MAX_LANES):
            chunk = indices[offset:offset + MAX_LANES]
            groups.append({
                "node": node,
                "first_channel": offset,
                "lanes": len(chunk),
                "channel_indices": chunk,
            })
    if len(groups) != 173 or len(manifest_jobs) != len(groups):
        raise ValueError("native output-job count does not equal the 173 per-node requant groups")
    if sum(group["lanes"] for group in groups) != len(channel_rows):
        raise ValueError("per-node output groups do not cover every current channel")
    for job_index, (group, native) in enumerate(zip(groups, manifest_jobs, strict=True), start=1):
        expected = (group["node"], job_index, group["first_channel"], group["lanes"])
        actual = (int(native["node"]), int(native["weight_epoch"]),
                  int(native["output_channel_first"]), int(native["output_lanes"]))
        if actual != expected:
            raise ValueError(f"native job grouping mismatch at job {job_index}: {actual} != {expected}")
        group["epoch"] = job_index
        group["native_weight_bytes"] = int(native["weight_bytes"])
    return groups


def _signed33_bits(value: int) -> int:
    return value & ((1 << 33) - 1)


def _pack_config_word(keys: list[int]) -> int:
    if len(keys) != MAX_LANES:
        raise ValueError("expected 32 configured lane keys")
    packed = 0
    for lane, key in enumerate(keys):
        if not -(1 << 32) <= key < (1 << 32):
            raise ValueError("key is outside signed 33-bit representation")
        packed |= _signed33_bits(key) << (lane * 33)
    return packed


def prepare_fixtures(build: Path, channel_rows: list[dict[str, Any]],
                     manifest_jobs: list[dict[str, Any]], tables: list[tuple[int, ...]]) -> dict[str, Any]:
    groups = _validate_groups(channel_rows, manifest_jobs)
    if len(tables) != len(channel_rows):
        raise ValueError("table count mismatch")
    channel_probes: list[array] = []
    channel_results: list[array] = []
    channel_coverage: list[dict[str, Any]] = []
    c_records_checked = 0
    boundary_bytes_consumed = 0
    tree_payload = PACKED_TREES.read_bytes()

    boundary_stream = BOUNDARIES.open("rb")
    try:
        for index, (metadata, table) in enumerate(zip(channel_rows, tables, strict=True)):
            if len(table) != 254 or tuple(sorted(table)) != table:
                raise ValueError(f"invalid original transition table at channel index {index}")
            multiplier = struct.unpack("<d", bytes.fromhex(metadata["multiplier_binary64_le_hex"]))[0]
            if not math.isfinite(multiplier) or not (multiplier > 0.0):
                raise ValueError(f"non-positive current multiplier at channel index {index}")
            packed_start = int(metadata["threshold_start_byte"])
            packed_keys = [int.from_bytes(tree_payload[packed_start + k * 5:packed_start + (k + 1) * 5], "little")
                           for k in range(255)]
            unpacked_keys = [value - (1 << 33) if value & (1 << 32) else value for value in packed_keys]
            expected_keys = list(table) + [SENTINEL]
            if unpacked_keys != expected_keys:
                raise ValueError(f"packed current transition keys differ at channel index {index}")

            raw_values = probes(table)
            raw_array = array("i")
            result_array = array("b")
            probe_digest = hashlib.sha256()
            for raw in raw_values:
                record = boundary_stream.read(13)
                if len(record) != 13:
                    raise ValueError("C-verified boundary stream ended early")
                c_multiplier, c_raw, c_result = struct.unpack("<dib", record)
                expected = rq.oracle(raw, multiplier)
                if struct.pack("<d", c_multiplier) != struct.pack("<d", multiplier) or \
                   c_raw != raw or c_result != expected or rq.evaluate(raw, table) != expected:
                    raise ValueError(f"C-record/Python-oracle mismatch channel={index} raw={raw}")
                raw_array.append(raw)
                result_array.append(expected)
                probe_digest.update(struct.pack("<ib", raw, expected))
                c_records_checked += 1
            channel_probes.append(raw_array)
            channel_results.append(result_array)
            channel_coverage.append({
                "channel_index": index,
                "node": int(metadata["node"]),
                "channel": int(metadata["channel"]),
                "probe_count": len(raw_array),
                "probe_pairs_sha256": probe_digest.hexdigest(),
                "first_probe": raw_array[0],
                "last_probe": raw_array[-1],
            })
        boundary_bytes_consumed = boundary_stream.tell()
    finally:
        boundary_stream.close()
    if boundary_bytes_consumed != BOUNDARIES.stat().st_size:
        raise ValueError("unused bytes remain in C-verified boundary stream")
    if c_records_checked != 4_156_373:
        raise ValueError(f"C boundary coverage changed: {c_records_checked}")

    jobs: list[dict[str, Any]] = []
    total_beats = 0
    first_job_cfg_words: list[int] = []
    first_job_record_words: list[int] = []
    with (build / "cfg.mem").open("w", encoding="ascii", newline="\n") as cfg_out, \
         (build / "vectors.mem").open("w", encoding="ascii", newline="\n") as data_out, \
         (build / "jobs.txt").open("w", encoding="ascii", newline="\n") as jobs_out:
        for job_number, group in enumerate(groups):
            active_indices = group["channel_indices"]
            max_beats = max(len(channel_probes[index]) for index in active_indices)
            group["vector_beats"] = max_beats
            group["channel_probe_counts"] = [len(channel_probes[index]) for index in active_indices]
            jobs.append(group)
            jobs_out.write(f"{group['epoch']} {group['lanes']} {max_beats} {group['node']} {group['first_channel']}\n")
            for word_index in range(255):
                keys = []
                for lane in range(MAX_LANES):
                    if lane < len(active_indices):
                        keys.append(tables[active_indices[lane]][word_index] if word_index < 254 else SENTINEL)
                    else:
                        keys.append(SENTINEL)
                word = _pack_config_word(keys)
                cfg_out.write(f"{word:0264x}\n")
                if job_number == 0:
                    first_job_cfg_words.append(word)

            for beat in range(max_beats):
                input_word = 0
                output_word = 0
                for lane, channel_index in enumerate(active_indices):
                    probes_for_lane = channel_probes[channel_index]
                    expected_for_lane = channel_results[channel_index]
                    raw = probes_for_lane[beat] if beat < len(probes_for_lane) else 0
                    expected = expected_for_lane[beat] if beat < len(expected_for_lane) else 0
                    input_word |= (raw & 0xFFFFFFFF) << (lane * 32)
                    output_word |= (expected & 0xFF) << (lane * 8)
                # The DUT masks all inactive lanes to zero; their configured keys are all +2^31.
                data_word = (output_word << 1024) | input_word
                data_out.write(f"{data_word:0320x}\n")
                if job_number == 0 and beat < 32:
                    first_job_record_words.append(data_word)
            total_beats += max_beats

    if len(first_job_cfg_words) != 255 or len(first_job_record_words) != 32:
        raise AssertionError("first group did not provide recovery fixture inputs")
    (build / "coverage.txt").write_text(f"{len(groups)} {total_beats} {len(channel_rows)}\n",
                                        encoding="ascii", newline="\n")
    (build / "recovery_cfg.mem").write_text(
        "".join(f"{word:0264x}\n" for word in first_job_cfg_words), encoding="ascii", newline="\n")
    (build / "extra_records.mem").write_text(
        "".join(f"{word:0320x}\n" for word in first_job_record_words), encoding="ascii", newline="\n")
    synthetic_words = []
    for word_index in range(255):
        key = SENTINEL if word_index == 254 else 0
        synthetic_words.append(_pack_config_word([key] * MAX_LANES))
    (build / "synthetic_cfg.mem").write_text(
        "".join(f"{word:0264x}\n" for word in synthetic_words), encoding="ascii", newline="\n")

    return {
        "status": "HOST_FIXTURES_READY",
        "channels": len(channel_rows),
        "convolution_nodes": len({int(row["node"]) for row in channel_rows}),
        "native_jobs": len(jobs),
        "native_output_lanes": sum(int(job["lanes"]) for job in jobs),
        "c_verified_boundary_records_checked_against_python": c_records_checked,
        "python_oracle_and_upper_bound_matches": c_records_checked,
        "keys_per_lane": 255,
        "signed_key_bits": 33,
        "inactive_lane_key": SENTINEL,
        "main_vector_beats": total_beats,
        "jobs": jobs,
        "channel_coverage": channel_coverage,
    }


def _run(command: list[str], cwd: Path, log_path: Path, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        subprocess.list2cmdline(command), cwd=str(cwd), shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=1800,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {
        "command": command,
        "cwd": str(cwd),
        "return_code": completed.returncode,
        "log": str(log_path.relative_to(ROOT)).replace("/", "\\"),
        "log_sha256": sha(log_path),
        "warning_mentions": len(re.findall(r"\bWARNING\b", completed.stdout, re.IGNORECASE)),
        "output": completed.stdout,
    }


def run_xsim(run_id: str, build: Path, evidence: Path,
             source_before: dict[str, dict[str, Any]], prepared: dict[str, Any],
             commands: list[dict[str, Any]]) -> dict[str, Any]:
    bindir = EXPECTED_XSIM
    tools = [bindir / "xvlog.bat", bindir / "xelab.bat", bindir / "xsim.bat"]
    for tool in tools:
        if not tool.is_file():
            raise FileNotFoundError(f"Vivado XSim tool is unavailable: {tool}")
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    commands.append(_run([str(tools[0]), "-sv", str(RTL), str(TB)], build, evidence / "xvlog.log", env))
    if commands[-1]["return_code"] != 0:
        raise RuntimeError("xvlog failed")
    commands.append(_run([str(tools[1]), "-mt", "2", "tb_z100_requant_vector",
                          "-s", "requant_vector_sim"], build, evidence / "xelab.log", env))
    if commands[-1]["return_code"] != 0:
        raise RuntimeError("xelab failed")
    command = [str(tools[2]), "requant_vector_sim", "-runall"]
    commands.append(_run(command, build, evidence / "xsim.log", env))
    output = commands[-1]["output"]
    if commands[-1]["return_code"] != 0 or "Fatal:" in output or "Error:" in output:
        raise RuntimeError("xsim reported a fatal error or returned nonzero")
    match = re.search(
        r"REQUANT_VECTOR_PASS jobs=(\d+) channels=(\d+) main_beats=(\d+) main_outputs=(\d+) "
        r"all_outputs=(\d+) first_job_latency=(\d+) active_lane_checks=(\d+) tail_lane_checks=(\d+) "
        r"accept_ii_checks=(\d+) output_ii_checks=(\d+) accept_ii_failures=(\d+) "
        r"output_ii_failures=(\d+) stall_checks=(\d+) bubble_cycles=(\d+) reload_blocked=(\d+) "
        r"cancel_stages=(\d+) reset_stages=(\d+) recovery_checks=(\d+) invalid_configs=(\d+) invalid_inputs=(\d+)",
        output,
    )
    if not match:
        raise RuntimeError("XSim pass marker or exact coverage summary is missing")
    values = tuple(map(int, match.groups()))
    expected = (prepared["native_jobs"], prepared["channels"], prepared["main_vector_beats"],
                prepared["main_vector_beats"], None, None, None, None, None, None,
                0, 0, None, None, 1, 8, 8, None, None, 3)
    for index, wanted in enumerate(expected):
        if wanted is not None and values[index] != wanted:
            raise RuntimeError(f"XSim coverage field {index} mismatch: {values[index]} != {wanted}")
    if values[4] != values[3] + 20:
        raise RuntimeError(f"XSim output count does not include the exact 20 recovery/flow-control transfers: {values[4]}")
    if values[8] != values[9] or values[8] < prepared["native_jobs"]:
        raise RuntimeError("XSim did not check input/output II=1 over the full stream")
    if values[6] < prepared["channels"] or values[7] == 0 or values[12] < 4:
        raise RuntimeError("XSim did not check every lane, inactive tails, and stalled output stability")
    if values[13] < 2 or values[17] < 17 or values[18] < 8:
        raise RuntimeError("XSim control-flow coverage summary is incomplete")
    simulation = {
        "status": "PASS_XSIM_PRIVATE_32_LANE_CURRENT_MODEL",
        "jobs": values[0], "channels": values[1],
        "main_vector_beats": values[2], "main_outputs": values[3],
        "all_outputs": values[4], "first_job_accept_to_output_cycles": values[5],
        "active_lane_result_checks": values[6], "inactive_tail_zero_checks": values[7],
        "accept_ii1_intervals_checked": values[8], "output_ii1_intervals_checked": values[9],
        "accept_ii_failures": values[10], "output_ii_failures": values[11],
        "output_stall_stability_checks": values[12], "input_bubble_cycles": values[13],
        "reload_blocked_while_inflight_checks": values[14], "cancel_stage_flushes": values[15],
        "reset_stage_flushes": values[16], "recovery_transfers": values[17],
        "invalid_configuration_cases": values[18], "invalid_input_cases": values[19],
        "vendor_scope": "Vivado XSim only; no synthesis, implementation, board access, or production integration",
    }
    after = inventory(source_paths())
    if after != source_before:
        raise RuntimeError("one or more read-only or test sources changed during XSim")
    return {"simulation": simulation, "commands": commands, "source_sha256_after": after}


def _artifact_inventory(build: Path, evidence: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for folder in (build, evidence):
        for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.name != "result.json"):
            result[str(path.relative_to(ROOT)).replace("/", "\\")] = {
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", help="continue or allocate this unique run ID")
    parser.add_argument("--prepare-only", action="store_true", help="prepare and validate host fixtures without launching XSim")
    parser.add_argument("--run-prepared", action="store_true", help="launch XSim for an existing prepared run")
    args = parser.parse_args()
    run_id = args.run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8])
    build = BUILD_ROOT / run_id
    evidence = EVIDENCE_ROOT / run_id
    if args.run_prepared:
        if not build.is_dir() or not evidence.is_dir():
            raise FileNotFoundError("requested prepared build/evidence run does not exist")
        prepared = json.loads((build / "prepared.json").read_text(encoding="utf-8"))
        source_before = prepared["source_inventory_before"]
        if inventory(source_paths()) != source_before:
            raise ValueError("source inventory changed since host-fixture preparation")
    else:
        build.mkdir(parents=True, exist_ok=False)
        evidence.mkdir(parents=True, exist_ok=False)
        frozen_report, channel_rows, manifest_jobs = validate_frozen_inputs()
        source_before = inventory(source_paths())
        (evidence / "source_inventory_before.json").write_text(
            json.dumps(source_before, indent=2) + "\n", encoding="utf-8")
        tables = _read_current_tables(channel_rows)
        coverage = prepare_fixtures(build, channel_rows, manifest_jobs, tables)
        if inventory(source_paths()) != source_before:
            raise RuntimeError("source files changed during host fixture preparation")
        prepared = {
            **coverage,
            "run_id": run_id,
            "table_evidence_report": str(TABLE_REPORT.relative_to(ROOT)).replace("/", "\\"),
            "table_evidence_status": frozen_report["status"],
            "source_inventory_before": source_before,
            "source_inventory_after_host_fixture": inventory(source_paths()),
        }
        (build / "prepared.json").write_text(json.dumps(prepared, indent=2) + "\n", encoding="utf-8")
        (evidence / "launch.json").write_text(json.dumps({
            "run_id": run_id,
            "phase": "private_current_model_requant_vector_xsim",
            "vivado_tool_dir": str(EXPECTED_XSIM),
            "max_elaboration_threads": 2,
            "numerical_worker_threads": 1,
            "board_access": False,
            "synthesis_or_route": False,
            "production_integrated": False,
            "source_sha256": source_before,
            "exact_coverage": {key: prepared[key] for key in (
                "channels", "convolution_nodes", "native_jobs", "native_output_lanes",
                "c_verified_boundary_records_checked_against_python", "main_vector_beats")},
        }, indent=2) + "\n", encoding="utf-8")
        if args.prepare_only:
            print(json.dumps({"status": "HOST_FIXTURES_READY", "run_id": run_id,
                              "build": str(build), "evidence": str(evidence),
                              "channels": prepared["channels"], "jobs": prepared["native_jobs"],
                              "c_records": prepared["c_verified_boundary_records_checked_against_python"],
                              "main_beats": prepared["main_vector_beats"]}, indent=2))
            return 0

    result: dict[str, Any] = {
        "run_id": run_id,
        "status": "RUNNING",
        "board_access": False,
        "synthesis_or_route": False,
        "production_integrated": False,
        "accuracy_gate_passed": False,
        "release_eligible": False,
        "host_fixture_status": prepared["status"],
        "source_sha256_before": source_before,
        "coverage": {key: prepared[key] for key in (
            "channels", "convolution_nodes", "native_jobs", "native_output_lanes",
            "c_verified_boundary_records_checked_against_python", "python_oracle_and_upper_bound_matches",
            "keys_per_lane", "signed_key_bits", "inactive_lane_key", "main_vector_beats", "jobs", "channel_coverage")},
    }
    commands: list[dict[str, Any]] = []
    try:
        executed = run_xsim(run_id, build, evidence, source_before, prepared, commands)
        result["status"] = executed["simulation"]["status"]
        result["simulation"] = executed["simulation"]
        result["source_sha256_after"] = executed["source_sha256_after"]
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["failure"] = f"{type(exc).__name__}: {exc}"
        result["source_sha256_after"] = inventory(source_paths())
    result["commands"] = [{key: value for key, value in command.items() if key != "output"}
                           for command in commands]
    result["artifact_inventory"] = _artifact_inventory(build, evidence)
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "run_id": run_id,
                      "report": str(evidence / "result.json"),
                      "simulation": result.get("simulation"), "failure": result.get("failure")}, indent=2))
    return 0 if result["status"] == "PASS_XSIM_PRIVATE_32_LANE_CURRENT_MODEL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
