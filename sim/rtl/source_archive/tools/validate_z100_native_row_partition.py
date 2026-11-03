"""Validate the frozen native first-convolution row with partitioned requant v2.

This private adapter keeps the row RTL, testbench, numeric oracle, and frozen
host dependency closure unchanged. It substitutes only the actual requant RTL
source selected for XSim and OOC, and records the source/evidence binding.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
FROZEN_VALIDATOR = ROOT / "tools/validate_z100_native_row_pipeline.py"
PARTITION_RTL = ROOT / "deployment/hardware/z100_2026/requant_partition_v2/z100_requant_vector.sv"
PARTITION_SIM_REPORT = ROOT / "validation/board_z100/requant_partition_v2/20261023T180243.573748Z_ca2a7224/result.json"
PARTITION_OOC_REPORT = ROOT / "validation/board_z100/requant_partition_ooc_v2/20261023T181049.979864Z/result.json"
PRIOR_ROW_REVIEW = ROOT / "validation/board_z100/nrow_ooc/20261024T042639.395850Z_9162160a/review.json"
BUILD_ROOT = ROOT / "deployment/build/nrowpart"
EVIDENCE_ROOT = ROOT / "validation/board_z100/nrowpart"
VIVADO = Path("C:/appload/2026.1/Vivado/bin/vivado.bat")
PARTITION_RTL_SHA256 = "970189f5e227aa278301d1f95b1299c2c339027cb4b0eb169e8fa142c174c34a"
PARTITION_SIM_SHA256 = "cf9c621881ce762a9c9ab866d0753a9921e1728adacae00bafb9c9d47a30ff8e"
PARTITION_OOC_SHA256 = "ab0be9ada37e297430ee7fcdfd6ae4519f4ca3053f59a9bdd4ab2abdee986221"
FROZEN_VALIDATOR_SHA256 = "ba1c64088f5e67628104918b8d74e2d7790e64ff7ea1bcd633edb93190e03f46"
EXPECTED_ROW_WRAPPER_SHA256 = "4de11c79472a48dea9553b136a22cca9765d4e31a006dedf141d355a1ec4d436"
EXPECTED_ROW_TB_SHA256 = "4ab9128588ac433cfc3bd9f0a84653774a2283903c80d8311a9558f31c029a12"
EXPECTED_MAC_RTL_SHA256 = "c2de472f539276da097e5ccd5bc7d44f2695dbff55ecb73458ea0105accbb643"
OLD_V1_RTL = ROOT / "deployment/hardware/z100_2026/requant_vector_v1/z100_requant_vector.sv"
PRESERVED_REPORT_ROOTS = (
    ROOT / "validation/board_z100/native_row_pipeline_v1/20261023T184135.335917Z_71fa68d6",
    ROOT / "validation/board_z100/native_row_pipeline_v1/20261023T184444.835012Z_eed495d5",
    ROOT / "validation/board_z100/native_row_pipeline_ooc_review/20261024T041914.318258Z_f12c5ada",
    ROOT / "validation/board_z100/native_row_pipeline_ooc_review/20261024T041925.151594Z_9878f495",
    ROOT / "validation/board_z100/nrow_ooc/20261024T042310.874855Z_85ffa7d9",
    ROOT / "validation/board_z100/nrow_ooc/20261024T042639.395850Z_9162160a",
)
CREATE_CLOCK_TCL = "create_clock -name row_internal_clk -period 10.000 [get_ports clk]"
SYNTH_DESIGN_TCL = "synth_design -top z100_native_row_pipeline -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none"
OOC_COMPLETE_MARKER = "NATIVE_ROW_OOC_COMPLETE placement=0 routing=0 external_io_timing_acceptance=0"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def file_inventory(root: Path) -> dict[str, dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    return {
        path.relative_to(root).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def inventory(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in sorted(paths.items())}


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_frozen() -> Any:
    if sha256(FROZEN_VALIDATOR) != FROZEN_VALIDATOR_SHA256:
        raise RuntimeError("frozen row validator hash changed")
    frozen = load_module("frozen_z100_native_row_partition_validator", FROZEN_VALIDATOR)
    frozen.REQUANT_RTL = PARTITION_RTL
    return frozen


def normalized_path_key(path_text: str) -> str:
    return path_text.replace("\\", "/").casefold()


def report_source_hash(report: dict[str, Any], source_path: Path, field: str) -> str:
    values = report.get(field)
    if not isinstance(values, dict):
        raise ValueError(f"partition report misses {field}")
    wanted = normalized_path_key(rel(source_path))
    found = [item for key, item in values.items() if normalized_path_key(key) == wanted]
    if len(found) != 1:
        raise ValueError(f"partition report does not bind exactly one source path: {source_path}")
    if isinstance(found[0], str):
        return found[0]
    if isinstance(found[0], dict):
        return found[0].get("sha256", "")
    raise ValueError(f"partition source hash value has an unsupported shape: {source_path}")


def partition_bindings(frozen: Any) -> dict[str, Any]:
    if not PARTITION_RTL.is_file() or sha256(PARTITION_RTL) != PARTITION_RTL_SHA256:
        raise RuntimeError("partition v2 RTL is missing or differs from its validated hash")
    sim = read_json(PARTITION_SIM_REPORT)
    ooc = read_json(PARTITION_OOC_REPORT)
    if (sha256(PARTITION_SIM_REPORT) != PARTITION_SIM_SHA256 or
        sim.get("status") != "PASS_XSIM_PRIVATE_32_LANE_CURRENT_MODEL" or
        sim.get("board_access") is not False or sim.get("synthesis_or_route") is not False or
        sim.get("production_integrated") is not False):
        raise RuntimeError("partition-v2 XSim prerequisite report changed or is out of scope")
    if (sha256(PARTITION_OOC_REPORT) != PARTITION_OOC_SHA256 or
        ooc.get("status") != "PASS_PRIVATE_PARTITIONED_REQUANT_OOC_RESOURCE_SCREEN" or
        ooc.get("board_access") is not False or ooc.get("placement_or_route") is not False or
        ooc.get("production_integrated") is not False):
        raise RuntimeError("partition-v2 OOC prerequisite report changed or is out of scope")
    if report_source_hash(sim, PARTITION_RTL, "source_sha256_before") != PARTITION_RTL_SHA256 or \
       report_source_hash(sim, PARTITION_RTL, "source_sha256_after") != PARTITION_RTL_SHA256:
        raise RuntimeError("partition-v2 XSim report does not bind unchanged actual RTL")
    if report_source_hash(ooc, PARTITION_RTL, "source_sha256_before") != PARTITION_RTL_SHA256 or \
       report_source_hash(ooc, PARTITION_RTL, "source_sha256_after") != PARTITION_RTL_SHA256:
        raise RuntimeError("partition-v2 OOC report does not bind unchanged actual RTL")
    if ooc.get("xsim_report_sha256") != PARTITION_SIM_SHA256:
        raise RuntimeError("partition-v2 OOC report does not bind its XSim prerequisite")
    sim_commands = sim.get("commands", [])
    part_rel = rel(PARTITION_RTL)
    v1_rtl_rel = rel(OLD_V1_RTL)
    if not any(any(normalized_path_key(str(arg)).endswith(normalized_path_key(part_rel))
                   for arg in command.get("command", [])) for command in sim_commands):
        raise RuntimeError("partition-v2 XSim vendor command does not compile the actual partition source")
    ooc_artifacts = ooc.get("artifact_sha256", {})
    synth_entries = [(key, value) for key, value in ooc_artifacts.items()
                     if normalized_path_key(key).endswith("/synth.tcl")]
    if len(synth_entries) != 1:
        raise RuntimeError("partition-v2 OOC report does not bind exactly one generated synthesis Tcl")
    synth_key, synth_sha = synth_entries[0]
    synth_path = ROOT / Path(synth_key.replace("\\", "/"))
    if not synth_path.is_file() or sha256(synth_path) != synth_sha:
        raise RuntimeError("partition-v2 OOC synthesis Tcl artifact is missing or changed")
    read_lines = [line for line in synth_path.read_text(encoding="utf-8").splitlines()
                  if line.startswith("read_verilog -sv ")]
    if len(read_lines) != 1 or str(PARTITION_RTL.resolve().as_posix()) not in read_lines[0] or \
       str(OLD_V1_RTL.resolve().as_posix()) in read_lines[0]:
        raise RuntimeError("partition-v2 OOC Tcl does not select partition RTL instead of v1")
    return {
        "partition_rtl": {"path": part_rel, "sha256": PARTITION_RTL_SHA256,
                          "bytes": PARTITION_RTL.stat().st_size},
        "partition_xsim": {"path": rel(PARTITION_SIM_REPORT), "sha256": PARTITION_SIM_SHA256,
                           "status": sim["status"], "run_id": sim.get("run_id"),
                           "vendor_source_path": part_rel},
        "partition_ooc": {"path": rel(PARTITION_OOC_REPORT), "sha256": PARTITION_OOC_SHA256,
                          "status": ooc["status"], "vendor_source_path": part_rel,
                          "synth_tcl_path": str(Path(synth_key.replace("\\", "/"))),
                          "synth_tcl_sha256": synth_sha,
                          "xsim_report_sha256": ooc["xsim_report_sha256"]},
        "v1_source_is_not_the_partition_rtl": v1_rtl_rel != part_rel,
    }


def row_source_maps(frozen: Any) -> tuple[dict[str, Path], dict[str, Path]]:
    base = frozen.source_paths()
    expected = {
        "deployment/hardware/z100_2026/native_row_pipeline_v1/z100_native_row_pipeline.sv": EXPECTED_ROW_WRAPPER_SHA256,
        "deployment/hardware/z100_2026/native_row_pipeline_v1/tb_z100_native_row_pipeline.sv": EXPECTED_ROW_TB_SHA256,
        "deployment/hardware/z100_2026/window_mac_v1/z100_window_mac.sv": EXPECTED_MAC_RTL_SHA256,
        rel(PARTITION_RTL): PARTITION_RTL_SHA256,
    }
    if len(base) != 48:
        raise RuntimeError(f"row source closure changed: expected 48 paths, found {len(base)}")
    for path, expected_sha in expected.items():
        if path not in base or sha256(base[path]) != expected_sha:
            raise RuntimeError(f"row source closure hash mismatch: {path}")
    dependencies = frozen.dependency_paths()
    if len(dependencies) != 20:
        raise RuntimeError(f"frozen host dependency closure changed: expected 20 paths, found {len(dependencies)}")
    if rel(PARTITION_SIM_REPORT) not in dependencies or rel(PARTITION_OOC_REPORT) not in dependencies:
        raise RuntimeError("frozen host dependency closure lacks partition XSim/OOC report bindings")
    sources = dict(base)
    if rel(SCRIPT) in sources or rel(SCRIPT) in dependencies:
        raise RuntimeError("adapter path unexpectedly aliases the frozen source/dependency closure")
    sources[rel(SCRIPT)] = SCRIPT
    return dict(sorted(sources.items())), dict(sorted(dependencies.items()))


def previous_row_review_binding() -> dict[str, Any]:
    review = read_json(PRIOR_ROW_REVIEW)
    if review.get("review_status") != "PASS_BOUNDED_SOURCE_BOUND_XSIM_NUMERICAL_REVIEW_ONLY":
        raise RuntimeError("prior independent row/TB review is not passing")
    prior_sources = review.get("source_sha256", {})
    expected = {
        "deployment/hardware/z100_2026/native_row_pipeline_v1/z100_native_row_pipeline.sv": EXPECTED_ROW_WRAPPER_SHA256,
        "deployment/hardware/z100_2026/native_row_pipeline_v1/tb_z100_native_row_pipeline.sv": EXPECTED_ROW_TB_SHA256,
        "deployment/hardware/z100_2026/window_mac_v1/z100_window_mac.sv": EXPECTED_MAC_RTL_SHA256,
    }
    normalized = {normalized_path_key(key): value for key, value in prior_sources.items()}
    for path, expected_sha in expected.items():
        item = normalized.get(normalized_path_key(path))
        if not isinstance(item, dict) or item.get("sha256") != expected_sha:
            raise RuntimeError(f"prior row review does not bind unchanged source {path}")
    return {"path": rel(PRIOR_ROW_REVIEW), "sha256": sha256(PRIOR_ROW_REVIEW),
            "status": review["review_status"], "original_xsim_run_id": review.get("xsim_run_id"),
            "row_source_paths_checked": len(review.get("source_sha256", {}))}


def source_inventory(frozen: Any, sources: dict[str, Path], dependencies: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    # The frozen source API deliberately includes the v1 RTL as an upstream post-validator
    # input. It is host provenance only; the row source list separately binds partition v2.
    return inventory(sources), inventory(dependencies)


def create_short_snapshot(sources: dict[str, Path], dependencies: dict[str, Path], evidence: Path,
                          row_source_count: int) -> dict[str, Any]:
    snapshot_root = evidence / "src"
    snapshot_root.mkdir(parents=True, exist_ok=False)
    entries: dict[str, dict[str, Any]] = {}
    for role, mapping in (("row_source", sources), ("host_dependency", dependencies)):
        for original, path in mapping.items():
            entry = entries.setdefault(original, {"path": str(path.resolve()), "roles": []})
            if entry["path"] != str(path.resolve()):
                raise RuntimeError(f"source/dependency key aliases different paths: {original}")
            entry["roles"].append("adapter" if original == rel(SCRIPT) else role)
    manifest_map: dict[str, dict[str, Any]] = {}
    for index, (original, entry) in enumerate(sorted(entries.items())):
        source = Path(entry["path"])
        content_hash = sha256(source)
        suffix = source.suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            suffix = ".dat"
        snapshot_name = f"{index:03d}_{content_hash[:12]}{suffix}"
        destination = snapshot_root / snapshot_name
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1 << 20)
        copied_hash = sha256(destination)
        if destination.stat().st_size != source.stat().st_size or copied_hash != content_hash:
            raise RuntimeError(f"snapshot byte verification failed: {original}")
        manifest_map[original] = {"snapshot_name": snapshot_name,
                                  "bytes": source.stat().st_size,
                                  "sha256": content_hash,
                                  "roles": sorted(entry["roles"])}
    names = [row["snapshot_name"] for row in manifest_map.values()]
    actual_names = sorted(path.name for path in snapshot_root.iterdir() if path.is_file())
    if len(names) != len(entries) or len(set(names)) != len(names) or sorted(names) != actual_names:
        raise RuntimeError("short source/dependency snapshot is not a bijection")
    maximum = max((len(str((snapshot_root / name).resolve())) for name in actual_names), default=0)
    if maximum > 220:
        raise RuntimeError(f"short source snapshot target path remains too long: {maximum}")
    manifest = {
        "format": "z100_native_row_partition_short_snapshot_v1",
        "root": rel(snapshot_root),
        "row_source_path_count": row_source_count,
        "adapter_path_count": 1,
        "host_dependency_path_count": len(dependencies),
        "unique_original_path_count": len(entries),
        "snapshot_file_count": len(actual_names),
        "all_bytes_verified": True,
        "bijection_verified": True,
        "maximum_destination_path_characters": maximum,
        "original_path_to_snapshot": manifest_map,
    }
    write_json(evidence / "snapshot_manifest.json", manifest)
    return {"path": rel(evidence / "snapshot_manifest.json"),
            "sha256": sha256(evidence / "snapshot_manifest.json"),
            "snapshot_file_count": len(actual_names),
            "unique_original_path_count": len(entries),
            "maximum_destination_path_characters": maximum,
            "all_bytes_verified": True, "bijection_verified": True}


def verify_short_snapshot(evidence: Path, sources: dict[str, Path], dependencies: dict[str, Path]) -> dict[str, Any]:
    manifest = read_json(evidence / "snapshot_manifest.json")
    mapping = manifest.get("original_path_to_snapshot")
    expected = {**sources, **dependencies}
    if not isinstance(mapping, dict) or set(mapping) != set(expected):
        raise RuntimeError("short snapshot path mapping changed")
    snapshot_root = evidence / "src"
    names: list[str] = []
    for original, source in expected.items():
        row = mapping[original]
        target_name = row.get("snapshot_name")
        if not isinstance(target_name, str) or Path(target_name).name != target_name:
            raise RuntimeError(f"short snapshot name is unsafe: {original}")
        target = snapshot_root / target_name
        names.append(target_name)
        if (not target.is_file() or row.get("bytes") != source.stat().st_size or
            row.get("sha256") != sha256(source) or target.stat().st_size != source.stat().st_size or
            sha256(target) != sha256(source)):
            raise RuntimeError(f"short snapshot verification failed: {original}")
    actual = sorted(path.name for path in snapshot_root.iterdir() if path.is_file())
    if sorted(names) != actual or len(names) != len(set(names)):
        raise RuntimeError("short snapshot is not a bijection with copied bytes")
    if manifest.get("all_bytes_verified") is not True or manifest.get("bijection_verified") is not True:
        raise RuntimeError("short snapshot summary flags are not true")
    return {"manifest_sha256": sha256(evidence / "snapshot_manifest.json"),
            "snapshot_file_count": len(actual),
            "maximum_destination_path_characters": manifest["maximum_destination_path_characters"]}


def preserved_reports_inventory() -> dict[str, Any]:
    return {rel(path): file_inventory(path) for path in PRESERVED_REPORT_ROOTS}


def summarize_upstream(frozen: Any, bindings: dict[str, Any]) -> dict[str, Any]:
    upstream = frozen.verify_upstream()
    reports = upstream.get("reports", {})
    summary = {name: {"path": item["path"], "sha256": item["sha256"], "status": item["status"]}
               for name, item in reports.items()}
    summary["partition_source_bindings"] = bindings
    return summary


def check_static_row_assertions(frozen: Any) -> dict[str, Any]:
    tb = frozen.TB.read_text(encoding="utf-8")
    required = (
        "consumer_hold_checks != 4",
        "packed_stall_hold_checks < 4",
        "packed_address_seen !== {80{1'b1}}",
        "packed_beats != 80",
        "packed_byte_checks != 80*64",
        "raw_lane_checks != ROW_WIDTH*32",
        "raw_flag_checks != ROW_WIDTH*32",
    )
    missing = [item for item in required if item not in tb]
    assertion_at = tb.find("consumer_hold_checks != 4")
    pass_at = tb.find("NATIVE_ROW_PIPELINE_PASS")
    if missing or assertion_at < 0 or pass_at < 0 or assertion_at > pass_at:
        raise RuntimeError(f"frozen row testbench acceptance assertions changed: missing={missing}")
    return {"source_sha256": sha256(frozen.TB),
            "consumer_hold_checks_exactly4_asserted_before_pass_marker": True,
            "packed_hold_marker_is_stall_stability_and_uses_minimum4": True,
            "raw_post_and_80_word_checks_unchanged": True}


def marker_pattern() -> re.Pattern[str]:
    return re.compile(
        r"NATIVE_ROW_PIPELINE_PASS runs=(\d+) requests=(\d+) responses=(\d+) window_bytes=(\d+) masks=(\d+) "
        r"raw_beats=(\d+) raw_lanes=(\d+) raw_flags=(\d+) post_beats=(\d+) active_bytes=(\d+) tail_bytes=(\d+) "
        r"packed_words=(\d+) packed_bytes=(\d+) feature_loads=(\d+) weight_groups=(\d+) bias_loads=(\d+) "
        r"req_words=(\d+) unary_bytes=(\d+) packed_stall=(\d+) req_stall=(\d+) unary_stall=(\d+) "
        r"raw_stall=(\d+) raw_stall_stability=(\d+) response_stalls=(\d+) response_stall_stability=(\d+) "
        r"bubbles=(\d+) site_fifo_full=(\d+) full_buffers=(\d+) packed_hold_checks=(\d+) done=(\d+) "
        r"raw_backpressure_note=(\d+) max_runsites=(\d+) tail_sites=(\d+)"
    )


def parse_full_row_pass(output: str, static_checks: dict[str, Any]) -> dict[str, Any]:
    matches = marker_pattern().findall(output)
    if len(matches) != 1:
        raise RuntimeError("exact full-row partition-v2 XSim pass marker missing or duplicated")
    values = tuple(map(int, matches[0]))
    expected = (27, 243, 243, 243 * 48, 243, 320, 320 * 32, 320 * 32,
                320, 320 * 16, 320 * 16, 80, 80 * 64, 80, 9, 1, 255, 256)
    if values[:18] != expected:
        raise RuntimeError(f"full-row data/count coverage mismatch: {values}")
    (packed_stall, req_stall, unary_stall, raw_stall, raw_stall_stability,
     response_stalls, response_stall_stability, bubbles, fifo_full, full_buffers,
     packed_stall_hold_checks, done, backpressure_note, max_sites, tail_sites) = values[18:]
    if (packed_stall <= 0 or req_stall <= 0 or unary_stall <= 0 or
        full_buffers != 1 or packed_stall_hold_checks < 4 or done != 1 or
        max_sites != 12 or tail_sites != 8 or bubbles <= 0 or fifo_full != 0 or
        (raw_stall == 0) != (backpressure_note == 1) or
        (raw_stall > 0 and raw_stall_stability < 1) or
        (response_stalls > 0 and response_stall_stability == 0)):
        raise RuntimeError(f"backpressure/elastic metadata coverage mismatch: {values}")
    if static_checks.get("consumer_hold_checks_exactly4_asserted_before_pass_marker") is not True:
        raise RuntimeError("frozen testbench consumer hold assertion is not bound")
    if "DDR" in output or "30FPS" in output:
        raise RuntimeError("XSim emitted an out-of-scope DDR or FPS claim")
    return {
        "status": "PASS",
        "counts": dict(zip(("runs", "window_requests", "window_responses", "window_bytes",
                             "window_masks", "raw_beats", "raw_lanes", "raw_flags", "post_beats",
                             "post_active_bytes", "post_tail_bytes", "packed_words", "packed_bytes",
                             "feature_loads", "weight_groups", "bias_loads", "requant_config_words",
                             "unary_bytes"), values[:18])),
        "packed_output_stall_cycles": packed_stall,
        "requant_stall_cycles": req_stall,
        "unary_stall_cycles": unary_stall,
        "raw_backpressure_cycles": raw_stall,
        "raw_backpressure_stability_checks": raw_stall_stability,
        "window_response_stall_cycles": response_stalls,
        "window_response_stability_checks": response_stall_stability,
        "input_bubble_cycles": bubbles,
        "site_fifo_full_cycles": fifo_full,
        "both_packer_buffers_full_observed": True,
        "packed_stall_hold_checks_marker": packed_stall_hold_checks,
        "consumer_hold_checks_exactly4_asserted_by_unchanged_tb": True,
        "done_events": done,
        "raw_backpressure_note": "naturally absent at raw boundary" if backpressure_note else "observed",
        "max_run_sites": max_sites,
        "tail_run_sites": tail_sites,
        "all_32_lanes_checked_at_raw_and_post_stages": True,
        "site_epoch_token_lanes_last_checked": True,
        "no_ddr_raw_roundtrip": True,
        "natural_backpressure_only": True,
    }


def current_file_maps(frozen: Any, sources: dict[str, Path], dependencies: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    return inventory(sources), inventory(dependencies)


def check_integrity(source_before: dict[str, Any], dependency_before: dict[str, Any],
                    preserved_before: dict[str, Any], frozen: Any, evidence: Path,
                    sources: dict[str, Path], dependencies: dict[str, Path],
                    expected_snapshot_sha256: str) -> dict[str, Any]:
    source_after, dependency_after = current_file_maps(frozen, sources, dependencies)
    preserved_after = preserved_reports_inventory()
    snapshot = verify_short_snapshot(evidence, sources, dependencies)
    return {
        "sources_unchanged": source_after == source_before,
        "dependencies_unchanged": dependency_after == dependency_before,
        "preserved_reports_unchanged": preserved_after == preserved_before,
        "short_snapshot_unchanged": snapshot["manifest_sha256"] == expected_snapshot_sha256,
        "frozen_validator_sha256": sha256(FROZEN_VALIDATOR),
        "adapter_sha256": sha256(SCRIPT),
        "short_snapshot": snapshot,
        "source_sha256_after": source_after,
        "dependency_sha256_after": dependency_after,
        "preserved_reports_after": preserved_after,
    }


def artifact_hashes(build: Path, evidence: Path, result_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for base in (build, evidence):
        for path in sorted(item for item in base.rglob("*") if item.is_file() and item != result_path):
            values[rel(path)] = sha256(path)
    return values


def run_host(run_id: str) -> dict[str, Any]:
    frozen = load_frozen()
    bindings = partition_bindings(frozen)
    host_sources, dependencies = row_source_maps(frozen)
    row_sources = frozen.source_paths()
    if len(row_sources) != 48:
        raise RuntimeError("actual row source closure is not the expected 48 paths")
    previous_review = previous_row_review_binding()
    static_checks = check_static_row_assertions(frozen)
    upstream = summarize_upstream(frozen, bindings)
    build = BUILD_ROOT / run_id
    evidence = EVIDENCE_ROOT / run_id
    if build.exists() or evidence.exists():
        raise FileExistsError("refusing to overwrite a prior partitioned-row run")
    build.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=False)
    fixture = frozen.prepare_fixture(build)
    source_before, dependency_before = current_file_maps(frozen, host_sources, dependencies)
    preserved_before = preserved_reports_inventory()
    snapshot = create_short_snapshot(host_sources, dependencies, evidence, len(row_sources))
    snapshot_verified = verify_short_snapshot(evidence, host_sources, dependencies)
    if snapshot_verified["manifest_sha256"] != snapshot["sha256"]:
        raise RuntimeError("new source/dependency snapshot hash differs after verification")
    host = {
        "status": "PASS_HOST_PREFLIGHT_ONLY",
        "run_id": run_id,
        "host": {"tool": "Python", "python_version": sys.version.split()[0],
                 "numerical_threads": 1},
        "scope": {"board_access": False, "route": False, "frequency_acceptance": False,
                  "production_integrated": False, "full_pipeline_30fps_accepted": False},
        "row_source_closure_path_count": len(row_sources),
        "host_adapter_source_path": rel(SCRIPT),
        "host_adapter_sha256": sha256(SCRIPT),
        "frozen_row_validator_sha256": sha256(FROZEN_VALIDATOR),
        "source_sha256_before_xsim": source_before,
        "dependency_sha256_before_xsim": dependency_before,
        "partition_source_and_prerequisite_bindings": bindings,
        "prior_row_review_binding": previous_review,
        "static_row_testbench_assertions": static_checks,
        "upstream_prerequisites": upstream,
        "short_snapshot": snapshot,
        "fixture": fixture,
        "preserved_report_trees_before": preserved_before,
        "attempt_policy": {"xsim_attempts": 0, "ooc_attempts": 0, "route_attempts": 0},
    }
    write_json(evidence / "host_preflight.json", host)
    result = {"status": host["status"], "run_id": run_id,
              "host_preflight_path": rel(evidence / "host_preflight.json"),
              "host_preflight_sha256": sha256(evidence / "host_preflight.json"),
              "evidence_directory": str(evidence.resolve()),
              "build_directory": str(build.resolve()),
              "attempt_policy": host["attempt_policy"],
              "scope": host["scope"],
              "row_source_closure_path_count": len(row_sources),
              "host_adapter_sha256": sha256(SCRIPT),
              "frozen_row_validator_sha256": sha256(FROZEN_VALIDATOR),
              "partition_source_and_prerequisite_bindings": bindings,
              "short_snapshot": snapshot,
              "fixture": fixture,
              "source_sha256_before_xsim": source_before,
              "dependency_sha256_before_xsim": dependency_before,
              "preserved_report_trees_before": preserved_before,
              "commands": []}
    write_json(evidence / "result.json", result)
    return result


def load_run(run_id: str) -> tuple[Any, Path, Path, dict[str, Any], Path]:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", run_id):
        raise ValueError("run id is not a safe simple identifier")
    frozen = load_frozen()
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    if not evidence.is_dir() or not build.is_dir():
        raise FileNotFoundError("host-preflight run directories do not exist")
    result_path = evidence / "result.json"
    result = read_json(result_path)
    host = read_json(evidence / "host_preflight.json")
    if host.get("status") != "PASS_HOST_PREFLIGHT_ONLY" or host.get("run_id") != run_id:
        raise RuntimeError("the matching host preflight did not pass")
    return frozen, build, evidence, result, result_path


def run_xsim(run_id: str) -> dict[str, Any]:
    frozen, build, evidence, result, result_path = load_run(run_id)
    if result.get("status") != "PASS_HOST_PREFLIGHT_ONLY":
        raise RuntimeError("XSim requires a clean host-only preflight and may run only once")
    attempt_path = evidence / "xsim_attempt_started.json"
    if attempt_path.exists():
        raise FileExistsError("refusing a second full-row XSim attempt")
    host = read_json(evidence / "host_preflight.json")
    bindings = partition_bindings(frozen)
    sources, dependencies = row_source_maps(frozen)
    source_before, dependency_before = current_file_maps(frozen, sources, dependencies)
    preserved_before = preserved_reports_inventory()
    if source_before != host["source_sha256_before_xsim"] or \
       dependency_before != host["dependency_sha256_before_xsim"] or \
       preserved_before != host["preserved_report_trees_before"]:
        raise RuntimeError("source, dependency, or prior report identity changed after host preflight")
    snapshot_before = verify_short_snapshot(evidence, sources, dependencies)
    if snapshot_before["manifest_sha256"] != host["short_snapshot"]["sha256"]:
        raise RuntimeError("short hash-bound source snapshot changed after host preflight")
    static_checks = check_static_row_assertions(frozen)
    vendor_sources = [frozen.BANK_RTL, frozen.WINDOW_RTL, frozen.MAC_RTL,
                      PARTITION_RTL, frozen.UNARY_RTL, frozen.PACKER_RTL,
                      frozen.WRAPPER, frozen.TB]
    if OLD_V1_RTL in vendor_sources or vendor_sources[3] != PARTITION_RTL:
        raise RuntimeError("full-row XSim source list does not replace v1 with actual partition v2")
    if len(vendor_sources) != 8 or not all(path.is_file() for path in vendor_sources):
        raise RuntimeError("full-row XSim source list is incomplete")
    write_json(attempt_path, {"run_id": run_id, "started_utc": datetime.now(timezone.utc).isoformat(),
                              "attempt": 1, "vendor_source_paths": [rel(path) for path in vendor_sources],
                              "partition_rtl_sha256": sha256(PARTITION_RTL),
                              "frozen_tb_sha256": sha256(frozen.TB)})
    result["status"] = "XSIM_RUNNING"
    result["xsim_source_paths"] = [rel(path) for path in vendor_sources]
    result["xsim_source_sha256_before"] = source_before
    result["xsim_dependency_sha256_before"] = dependency_before
    result["partition_source_and_prerequisite_bindings"] = bindings
    result["static_row_testbench_assertions"] = static_checks
    result["attempt_policy"] = {"xsim_attempts": 1, "ooc_attempts": 0, "route_attempts": 0}
    result["preserved_report_trees_before_xsim"] = preserved_before
    write_json(result_path, result)
    failure: str | None = None
    commands: list[dict[str, Any]] = []
    xsim_coverage: dict[str, Any] | None = None
    try:
        env = frozen.phase_env()
        for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
            if not (frozen.VIVADO_BIN / tool).is_file():
                raise FileNotFoundError(f"Vivado 2026.1 XSim tool missing: {frozen.VIVADO_BIN / tool}")
        compile_cmd = [str(frozen.VIVADO_BIN / "xvlog.bat"), "-sv", *map(str, vendor_sources)]
        commands.append(frozen.run_logged(compile_cmd, build, evidence / "xvlog.log", env))
        if commands[-1]["return_code"] != 0:
            raise RuntimeError("xvlog failed; no retry permitted")
        elaborate_cmd = [str(frozen.VIVADO_BIN / "xelab.bat"), "-mt", "2", "tb_z100_native_row_pipeline",
                         "-s", "native_row_partition_sim"]
        commands.append(frozen.run_logged(elaborate_cmd, build, evidence / "xelab.log", env))
        if commands[-1]["return_code"] != 0:
            raise RuntimeError("xelab failed; no retry permitted")
        sim_cmd = [str(frozen.VIVADO_BIN / "xsim.bat"), "native_row_partition_sim", "-runall"]
        commands.append(frozen.run_logged(sim_cmd, build, evidence / "xsim.log", env))
        output = commands[-1]["output"]
        if commands[-1]["return_code"] != 0 or re.search(r"(?im)^\s*(?:Fatal:|ERROR:)", output):
            raise RuntimeError("xsim failed; no retry permitted")
        xsim_coverage = parse_full_row_pass(output, static_checks)
        result["xsim_log_sha256"] = commands[-1]["log_sha256"]
        result["xsim_coverage"] = xsim_coverage
        result["xsim_tool_return_codes"] = [row["return_code"] for row in commands]
        result["xsim_vendor_arguments"] = [row["argv"] for row in commands]
        result["status"] = "PASS_PARTITION_V2_FULL_ROW_XSIM_ONLY"
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
        result["failure"] = failure
        result["status"] = "FAILED_CLOSED_PARTITION_V2_XSIM"
    finally:
        result["commands"] = commands
        result["xsim_attempt_policy"] = {"xsim_attempts": 1, "ooc_attempts": 0, "route_attempts": 0}
        integrity = check_integrity(source_before, dependency_before, preserved_before,
                                    frozen, evidence, sources, dependencies,
                                    host["short_snapshot"]["sha256"])
        result["xsim_integrity"] = integrity
        if not all(integrity[key] for key in ("sources_unchanged", "dependencies_unchanged",
                                              "preserved_reports_unchanged", "short_snapshot_unchanged")):
            result["status"] = "FAILED_CLOSED_PARTITION_V2_XSIM_INTEGRITY"
            result["failure"] = result.get("failure", "source/dependency/snapshot/prior report changed during XSim")
        if failure is None and result["status"] == "PASS_PARTITION_V2_FULL_ROW_XSIM_ONLY":
            result["next_phase"] = "one OOC permitted"
        result["new_artifact_sha256"] = artifact_hashes(build, evidence, result_path)
        write_json(result_path, result)
    return result


def move_clock_after_synthesis(text: str) -> tuple[str, dict[str, Any]]:
    lines = text.splitlines(keepends=True)
    normalized = [line.rstrip("\r\n") for line in lines]
    clock_positions = [i for i, line in enumerate(normalized) if line == CREATE_CLOCK_TCL]
    synth_positions = [i for i, line in enumerate(normalized) if line == SYNTH_DESIGN_TCL]
    if len(clock_positions) != 1 or len(synth_positions) != 1:
        raise RuntimeError("OOC Tcl must have one exact create_clock and synth_design line")
    clock_index, synth_index = clock_positions[0], synth_positions[0]
    if clock_index + 1 != synth_index:
        raise RuntimeError("OOC create_clock is not immediately before synth_design")
    expected = list(lines)
    expected[clock_index], expected[synth_index] = expected[synth_index], expected[clock_index]
    corrected = "".join(expected)
    explicit = "".join(lines[:clock_index] + [lines[synth_index], lines[clock_index]] + lines[synth_index + 1:])
    if corrected != explicit:
        raise RuntimeError("OOC clock repair was not exactly the adjacent two-line reorder")
    corrected_lines = [line.rstrip("\r\n") for line in corrected.splitlines(keepends=True)]
    if corrected_lines[clock_index] != SYNTH_DESIGN_TCL or corrected_lines[clock_index + 1] != CREATE_CLOCK_TCL:
        raise RuntimeError("OOC 10 ns clock was not moved immediately after synth_design")
    return corrected, {
        "transformation": "swap_adjacent_create_clock_and_synth_design_lines",
        "exact_pair_reorder_verified": True,
        "clock_period_ns": 10.0,
        "original_clock_line_1based": clock_index + 1,
        "original_synth_line_1based": synth_index + 1,
        "corrected_synth_line_1based": clock_index + 1,
        "corrected_clock_line_1based": clock_index + 2,
        "unified_diff": "".join(difflib.unified_diff(
            lines, expected, fromfile="frozen_tcl", tofile="partition_v2_tcl")),
    }


def mode_census_extension(evidence: Path) -> str:
    mode_path = evidence / "dsp48e1_mode_census.tsv"
    summary_path = evidence / "dsp48e1_mode_summary.tsv"
    for path in (mode_path, summary_path):
        if "{" in path.resolve().as_posix() or "}" in path.resolve().as_posix():
            raise ValueError(f"unsafe Tcl census path: {path}")
    body = r'''set dsp48 [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]
array set dsp_mode_counts {}
set dsp_mode_file [open {@MODE_FILE@} w]
puts $dsp_mode_file "cell\tUSE_MULT"
foreach cell $dsp48 {
    set name [get_property NAME $cell]
    set mode [string toupper [get_property -quiet USE_MULT $cell]]
    if {$mode eq ""} {set mode "UNAVAILABLE"}
    if {![info exists dsp_mode_counts($mode)]} {set dsp_mode_counts($mode) 0}
    incr dsp_mode_counts($mode)
    puts $dsp_mode_file "$name\t$mode"
}
close $dsp_mode_file
set multiply 0
set none 0
set other 0
foreach mode [array names dsp_mode_counts] {
    if {$mode eq "MULTIPLY"} {set multiply $dsp_mode_counts($mode)} elseif {$mode eq "NONE"} {set none $dsp_mode_counts($mode)} else {incr other $dsp_mode_counts($mode)}
}
set dsp_mode_summary_file [open {@SUMMARY_FILE@} w]
puts $dsp_mode_summary_file "DSP48E1_COUNT\t[llength $dsp48]"
puts $dsp_mode_summary_file "MULTIPLY\t$multiply"
puts $dsp_mode_summary_file "NONE\t$none"
puts $dsp_mode_summary_file "OTHER\t$other"
close $dsp_mode_summary_file
puts "NATIVE_ROW_DSP_MODES dsp48=[llength $dsp48] multiply=$multiply none=$none other=$other"
'''
    return body.replace("@MODE_FILE@", mode_path.resolve().as_posix()).replace(
        "@SUMMARY_FILE@", summary_path.resolve().as_posix())


def parse_mode_census(evidence: Path, primitive_census: Path) -> dict[str, Any]:
    mode_rows: dict[str, str] = {}
    lines = (evidence / "dsp48e1_mode_census.tsv").read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "cell\tUSE_MULT":
        raise ValueError("DSP mode census header differs")
    modes: Counter[str] = Counter()
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 2 or not fields[0] or fields[0] in mode_rows:
            raise ValueError("DSP mode census has malformed or duplicate cell rows")
        mode_rows[fields[0]] = fields[1]
        modes[fields[1]] += 1
    primitive_dsp_owner: dict[str, str] = {}
    with primitive_census.open("r", encoding="utf-8") as stream:
        if stream.readline().rstrip("\r\n").split("\t") != ["class", "ref_name", "cell_name", "owner"]:
            raise ValueError("primitive census header differs")
        for line in stream:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 4:
                raise ValueError("malformed primitive census row")
            if fields[0] == "DSP":
                if fields[2] in primitive_dsp_owner:
                    raise ValueError("duplicate DSP primitive cell in census")
                primitive_dsp_owner[fields[2]] = fields[3]
    if set(mode_rows) != set(primitive_dsp_owner):
        raise ValueError("USE_MULT census and primitive DSP cells do not match exactly")
    if modes.get("MULTIPLY", 0) != 1536 or modes.get("NONE", 0) != len(mode_rows) - 1536 or \
       modes.get("NONE", 0) > 384 or sum(modes.values()) != len(mode_rows) or \
       any(mode not in {"MULTIPLY", "NONE"} for mode in modes):
        # The total and remaining-adder budget gates are evaluated by the caller too;
        # this structural check rejects unavailable/other DSP modes without exact-total assumptions.
        mode_status = "FAILED_FIXED_DSP_MODE_BUDGET"
    else:
        mode_status = "PASS_FIXED_DSP_MODE_BUDGET"
    non_mac_mode_cells = sorted(cell for cell, mode in mode_rows.items()
                                if mode in {"MULTIPLY", "NONE"} and primitive_dsp_owner[cell] != "native_mac")
    summary: dict[str, int] = {}
    for line in (evidence / "dsp48e1_mode_summary.tsv").read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] in summary:
            raise ValueError("DSP mode summary is malformed")
        summary[fields[0]] = int(fields[1])
    computed = {"DSP48E1_COUNT": len(mode_rows), "MULTIPLY": modes["MULTIPLY"],
                "NONE": modes["NONE"], "OTHER": len(mode_rows)-modes["MULTIPLY"]-modes["NONE"]}
    if summary != computed:
        raise ValueError(f"DSP mode summary does not reconcile: {summary} vs {computed}")
    return {"status": mode_status, "counts": computed,
            "all_modes_match_primitive_cells": True,
            "all_dsp_modes_owned_by_native_mac": not non_mac_mode_cells,
            "non_native_mac_mode_cells": non_mac_mode_cells,
            "mode_census_sha256": sha256(evidence / "dsp48e1_mode_census.tsv"),
            "mode_summary_sha256": sha256(evidence / "dsp48e1_mode_summary.tsv")}


def parse_resources(frozen: Any, evidence: Path, build: Path, stdout: str) -> dict[str, Any]:
    required = [build / "post_synth.dcp", evidence / "utilization.rpt",
                evidence / "hierarchical_utilization.rpt", evidence / "timing_unplaced_100mhz_diagnostic.rpt",
                evidence / "timing_paths_unplaced_diagnostic.rpt", evidence / "check_timing_unplaced_diagnostic.rpt",
                evidence / "primitive_counts.tsv", evidence / "primitive_census.tsv",
                evidence / "synthesis_summary.tsv", evidence / "dsp48e1_mode_census.tsv",
                evidence / "dsp48e1_mode_summary.tsv"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Vivado omitted required pre-gate evidence: {missing}")
    # Capture and bind every required artifact before evaluating any resource gate.
    pre_gate_artifacts = {rel(path): sha256(path) for path in required}
    counts = frozen.parse_counts(evidence / "primitive_counts.tsv")
    memory = frozen.analyze_census(evidence, counts)
    modes = parse_mode_census(evidence, evidence / "primitive_census.tsv")
    utilization = (evidence / "utilization.rpt").read_text(encoding="utf-8", errors="replace")
    lut_match = re.search(r"^\|\s*Slice LUTs\*?\s*\|\s*(\d+)\s*\|", utilization, re.M)
    ff_match = re.search(r"^\|\s*Slice Registers\s*\|\s*(\d+)\s*\|", utilization, re.M)
    if not lut_match or not ff_match:
        raise RuntimeError("Vivado top-level Slice LUT/register counts were absent")
    lut, ff = int(lut_match.group(1)), int(ff_match.group(1))
    modes_count = modes["counts"]
    remaining = counts["DSP"] - 1536
    mode_gates = {
        "dsp_total_at_most_1920": counts["DSP"] <= 1920,
        "dsp_multiply_exactly_1536": modes_count["MULTIPLY"] == 1536,
        "remaining_dsp_are_none_and_at_most_384": remaining >= 0 and
            modes_count["NONE"] == remaining and modes_count["NONE"] <= 384 and modes_count["OTHER"] == 0,
        "dsp_modes_match_all_primitive_cells": modes["all_modes_match_primitive_cells"],
        "all_dsp_primitives_owned_by_native_mac": memory["all_dsps_owned_by_native_mac"],
        "all_multiply_and_none_modes_owned_by_native_mac": modes["all_dsp_modes_owned_by_native_mac"],
    }
    resource_gates = {
        **mode_gates,
        "bram36_equivalent_at_most_180": memory["bram36_equivalent"] <= 180,
        "hierarchical_bram_ownership_reconciled": memory["bram_ownership_reconciled"],
        "slice_lut_at_most_120000": lut <= 120000,
        "slice_ff_at_most_100000": ff <= 100000,
        "no_latches": counts["LATCH"] == 0,
        "no_blackboxes": counts["BLACKBOX"] == 0,
    }
    marker_modes = re.findall(
        r"(?m)^NATIVE_ROW_DSP_MODES dsp48=(\d+) multiply=(\d+) none=(\d+) other=(\d+)$", stdout)
    if marker_modes != [(str(modes_count["DSP48E1_COUNT"]), str(modes_count["MULTIPLY"]),
                         str(modes_count["NONE"]), str(modes_count["OTHER"]))]:
        raise RuntimeError(f"Vivado mode marker differs from saved census: {marker_modes}")
    if stdout.count(OOC_COMPLETE_MARKER) != 1:
        raise RuntimeError("Vivado OOC completion marker is missing or duplicated")
    summary = (evidence / "synthesis_summary.tsv").read_text(encoding="utf-8").splitlines()
    if "TOOL_VERSION\t2026.1" not in summary or f"PART\txc7z100ffg900-2" not in summary or \
       "INTERNAL_CLOCK_PERIOD_NS\t10.000" not in summary:
        raise RuntimeError("Vivado synthesis summary tool/part/clock binding differs")
    return {
        "status": "PASS_FIXED_RESOURCE_SCREEN" if all(resource_gates.values()) else "FAILED_FIXED_RESOURCE_SCREEN",
        "tool_version": "Vivado 2026.1",
        "device_part": "xc7z100ffg900-2",
        "primitive_counts": counts,
        "slice_lut": lut,
        "slice_ff": ff,
        "bram36_equivalent": memory["bram36_equivalent"],
        "hierarchical_owner_breakdown": memory["owner_counts"],
        "memory_ownership": memory,
        "dsp_mode_census": modes,
        "resource_gates": resource_gates,
        "pre_gate_artifact_sha256": pre_gate_artifacts,
        "all_required_census_checkpoint_utilization_emitted_before_gates": True,
        "timing_scope": {"internal_clock_period_ns": 10.0,
                          "purpose": "unplaced internal diagnostic constraint only",
                          "external_io_timing_accepted": False,
                          "frequency_accepted": False,
                          "placement_or_route": False},
    }


def run_ooc(run_id: str) -> dict[str, Any]:
    frozen, build, evidence, result, result_path = load_run(run_id)
    if result.get("status") != "PASS_PARTITION_V2_FULL_ROW_XSIM_ONLY":
        raise RuntimeError("OOC is allowed only after a fresh partition-v2 full-row XSim pass")
    attempt_path = evidence / "ooc_attempt_started.json"
    if attempt_path.exists():
        raise FileExistsError("refusing a second integrated row OOC attempt")
    host = read_json(evidence / "host_preflight.json")
    bindings = partition_bindings(frozen)
    sources, dependencies = row_source_maps(frozen)
    source_before, dependency_before = current_file_maps(frozen, sources, dependencies)
    preserved_before = preserved_reports_inventory()
    xsim_integrity = result.get("xsim_integrity", {})
    if source_before != xsim_integrity.get("source_sha256_after") or \
       dependency_before != xsim_integrity.get("dependency_sha256_after") or \
       preserved_before != xsim_integrity.get("preserved_reports_after"):
        raise RuntimeError("source/dependency/prior report identity changed between XSim and OOC")
    verify_short_snapshot(evidence, sources, dependencies)
    if host.get("partition_source_and_prerequisite_bindings") != bindings:
        raise RuntimeError("partition source or prerequisite binding changed after full-row XSim")
    if not VIVADO.is_file():
        raise FileNotFoundError(f"Vivado 2026.1 OOC launcher missing: {VIVADO}")
    if result.get("ooc_command") or result.get("ooc"):
        raise RuntimeError("result already contains an OOC attempt")
    original_make = frozen.make_synth_tcl
    mode_extension = mode_census_extension(evidence)
    marker = f'puts "{OOC_COMPLETE_MARKER}"\nexit'
    tcl_report_path = evidence / "partition_ooc_tcl_correction.json"

    def make_partition_tcl(out_evidence: Path, out_build: Path) -> str:
        original_text = original_make(out_evidence, out_build)
        corrected, reorder = move_clock_after_synthesis(original_text)
        read_lines = [line for line in corrected.splitlines() if line.startswith("read_verilog -sv ")]
        if len(read_lines) != 1:
            raise RuntimeError("partition-v2 Tcl must contain one read_verilog source command")
        read_line = read_lines[0]
        if str(PARTITION_RTL.resolve().as_posix()) not in read_line or \
           str(OLD_V1_RTL.resolve().as_posix()) in read_line:
            raise RuntimeError("actual OOC Tcl did not replace v1 with partition-v2 RTL")
        if corrected.count(marker) != 1:
            raise RuntimeError("frozen Tcl OOC completion marker is not unique")
        final_text = corrected.replace(marker, mode_extension + marker)
        report = {
            "format": "z100_native_row_partition_ooc_tcl_binding_v1",
            "root_cause_of_prior_failure": (
                "The earlier adapter invoked frozen row validator REQUANT_RTL (replicated-tree v1), "
                "despite partition-v2 prerequisite reports. This run explicitly substitutes the validated "
                "requant_partition_v2/z100_requant_vector.sv in XSim and OOC. The prior clock-order issue "
                "is handled by the exact adjacent create_clock/synth_design line swap."),
            "partition_rtl_path": rel(PARTITION_RTL),
            "partition_rtl_sha256": sha256(PARTITION_RTL),
            "old_v1_path_absent_from_read_verilog": True,
            "read_verilog_line": read_line,
            "create_clock_reorder": reorder,
            "original_base_tcl_sha256": hashlib.sha256(original_text.encode("utf-8")).hexdigest(),
            "corrected_base_tcl_sha256": hashlib.sha256(corrected.encode("utf-8")).hexdigest(),
            "mode_census_extension_sha256": hashlib.sha256(mode_extension.encode("utf-8")).hexdigest(),
            "adapter_generated_tcl_sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
        }
        write_json(tcl_report_path, report)
        return final_text

    frozen.make_synth_tcl = make_partition_tcl
    write_json(attempt_path, {"run_id": run_id, "started_utc": datetime.now(timezone.utc).isoformat(),
                              "attempt": 1, "partition_rtl_sha256": sha256(PARTITION_RTL),
                              "policy": "one integrated OOC after PASS partition-v2 full-row XSim; no retry"})
    result["status"] = "OOC_RUNNING"
    result["attempt_policy"] = {"xsim_attempts": 1, "ooc_attempts": 1, "route_attempts": 0}
    result["ooc_source_sha256_before"] = source_before
    result["ooc_dependency_sha256_before"] = dependency_before
    result["preserved_report_trees_before_ooc"] = preserved_before
    write_json(result_path, result)
    failure: str | None = None
    command: list[str] = []
    stdout = ""
    ooc_result: dict[str, Any] | None = None
    try:
        tcl_path = evidence / "synth.tcl"
        tcl_text = make_partition_tcl(evidence, build)
        tcl_path.write_text(tcl_text, encoding="utf-8", newline="\n")
        report = read_json(tcl_report_path)
        report["written_tcl_sha256"] = sha256(tcl_path)
        report["written_tcl_matches_adapter"] = report["written_tcl_sha256"] == report["adapter_generated_tcl_sha256"]
        written_lines = [line.rstrip("\r\n") for line in tcl_text.splitlines(keepends=True)]
        synth_pos = [i for i, line in enumerate(written_lines) if line == SYNTH_DESIGN_TCL]
        clock_pos = [i for i, line in enumerate(written_lines) if line == CREATE_CLOCK_TCL]
        report["written_clock_order_verified"] = len(synth_pos) == 1 and len(clock_pos) == 1 and clock_pos[0] == synth_pos[0] + 1
        if not report["written_tcl_matches_adapter"] or not report["written_clock_order_verified"]:
            raise RuntimeError("written partition-v2 OOC Tcl did not match exact source/clock adapter")
        write_json(tcl_report_path, report)
        command = [str(VIVADO), "-mode", "batch", "-log", str(evidence / "vivado.log"),
                   "-journal", str(evidence / "vivado.jou"), "-source", str(tcl_path)]
        done = subprocess.run(subprocess.list2cmdline(command), cwd=str(build), env=frozen.phase_env(),
                              shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace", timeout=3600)
        stdout = done.stdout
        (evidence / "vivado_stdout.log").write_text(stdout, encoding="utf-8")
        result["ooc_command"] = {"argv": command, "cwd": str(build.resolve()),
                                 "return_code": done.returncode,
                                 "stdout_log": rel(evidence / "vivado_stdout.log"),
                                 "stdout_sha256": sha256(evidence / "vivado_stdout.log")}
        if done.returncode != 0:
            raise RuntimeError(f"single integrated Vivado OOC returned {done.returncode}; no retry permitted")
        if "Vivado v2026.1" not in stdout:
            raise RuntimeError("Vivado 2026.1 banner is absent from OOC output")
        ooc_result = parse_resources(frozen, evidence, build, stdout)
        result["ooc"] = ooc_result
        result["status"] = "PASS_PARTITION_V2_FULL_ROW_OOC_RESOURCE_SCREEN" if \
            ooc_result["status"] == "PASS_FIXED_RESOURCE_SCREEN" else "FAILED_PARTITION_V2_RESOURCE_SCREEN"
        if result["status"] != "PASS_PARTITION_V2_FULL_ROW_OOC_RESOURCE_SCREEN":
            failure = "one or more fixed integrated resource gates failed"
            result["failure"] = failure
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
        result["failure"] = failure
        result["status"] = "FAILED_CLOSED_PARTITION_V2_OOC"
    finally:
        frozen.make_synth_tcl = original_make
        result["ooc_attempt_policy"] = {"xsim_attempts": 1, "ooc_attempts": 1, "route_attempts": 0}
        result["ooc_source_sha256_after"] = inventory(sources)
        result["ooc_dependency_sha256_after"] = inventory(dependencies)
        result["preserved_report_trees_after_ooc"] = preserved_reports_inventory()
        result["ooc_integrity"] = {
            "sources_unchanged": result["ooc_source_sha256_after"] == source_before,
            "dependencies_unchanged": result["ooc_dependency_sha256_after"] == dependency_before,
            "preserved_reports_unchanged": result["preserved_report_trees_after_ooc"] == preserved_before,
            "short_snapshot_unchanged": verify_short_snapshot(evidence, sources, dependencies)["manifest_sha256"] ==
                host["short_snapshot"]["sha256"],
            "frozen_validator_sha256": sha256(FROZEN_VALIDATOR),
            "adapter_sha256": sha256(SCRIPT),
        }
        if not all(result["ooc_integrity"][key] for key in ("sources_unchanged", "dependencies_unchanged",
                                                           "preserved_reports_unchanged", "short_snapshot_unchanged")):
            result["status"] = "FAILED_CLOSED_PARTITION_V2_OOC_INTEGRITY"
            result["failure"] = result.get("failure", "source/dependency/prior report/snapshot changed during OOC")
        if tcl_report_path.is_file():
            report = read_json(tcl_report_path)
            report["path"] = rel(tcl_report_path)
            report["sha256"] = sha256(tcl_report_path)
            result["ooc_tcl_binding_report"] = report
        result["new_artifact_sha256"] = artifact_hashes(build, evidence, result_path)
        write_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("host", "xsim", "ooc"), default="host")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    run_id: str | None = args.run_id
    try:
        if args.phase == "host":
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
            result = run_host(run_id)
        else:
            if not args.run_id:
                parser.error("--run-id is required for xsim and ooc phases")
            run_id = args.run_id
            result = run_xsim(run_id) if args.phase == "xsim" else run_ooc(run_id)
        print(json.dumps({"status": result["status"], "run_id": run_id,
                          "failure": result.get("failure"),
                          "evidence_directory": result.get("evidence_directory"),
                          "xsim_coverage": result.get("xsim_coverage"),
                          "ooc": result.get("ooc")}, sort_keys=True), flush=True)
        return 0 if result["status"].startswith("PASS_") else 2
    except Exception as error:
        if args.phase == "host" and run_id:
            evidence = EVIDENCE_ROOT / run_id
            build = BUILD_ROOT / run_id
            if evidence.is_dir() and not (evidence / "host_preflight.json").exists() and \
               not (evidence / "host_preflight_failure.json").exists():
                write_json(evidence / "host_preflight_failure.json", {
                    "status": "FAILED_CLOSED_HOST_PREFLIGHT",
                    "run_id": run_id,
                    "failure": f"{type(error).__name__}: {error}",
                    "vendor_attempted": False,
                    "build_fixture_files": file_inventory(build) if build.is_dir() else {},
                    "adapter_sha256_at_failure_not_captured": True,
                })
        print(json.dumps({"status": "FAILED_CLOSED_PARTITION_V2", "phase": args.phase,
                          "run_id": run_id, "error": f"{type(error).__name__}: {error}"},
                         sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
