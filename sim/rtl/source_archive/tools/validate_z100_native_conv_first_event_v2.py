"""Prepare a source-bound native Conv first-event numerical regression.

--prepare-only validates frozen inputs and stages the regression.  An optional
local Icarus compile checks exact source/port closure; this tool never runs the
simulation, Vivado, XSim, synthesis, or hardware.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from typing import Any
from review_z100_native_conv_v2_elaboration import warning_class


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "deployment/build/z100_native_conv_backend_v3_review/20261026T063511.355431Z/source_manifest.json"
DEFAULT_ROOT_REVIEW = ROOT / "validation/board_z100/native_conv_backend_v3_elab_review/20261026T063511.355431Z/result.json"
FIRST_FIXTURE = ROOT / "validation/board_z100/first_conv_full_node_fixture/20261025T190809.773575Z/result.json"
C_REFERENCE = ROOT / "validation/board_z100/first_conv_full_node_c_reference/20261025T190827.057066Z/result.json"
GENERIC_NUMERIC = ROOT / "validation/board_z100/generic_first_conv_event/20261026T004830.167160Z/result.json"
ROM_PREFETCH = ROOT / "validation/board_z100/rom_prefetch_first_conv/20261026T022810.468946Z/result.json"
FULL_FIXTURE_DIR = ROOT / "deployment/build/z100_first_conv_full_node/20261025T190809.773575Z"
ROM_BUILD_DIR = ROOT / "build/rompfce_022810.468946Z"
TB_SOURCE = ROOT / "deployment/simulation/native_conv_first_event_v1/tb_z100_native_conv_first_event_v1.sv"
DOC = ROOT / "docs/z100_native_deployment_preparation.md"
LOCAL_TOOLS = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64"
VENDOR = Path("C:/appload/2026.1/Vivado/data/verilog/src")
SOURCE_BEATS = 25600
DIRECTORY_BEATS = 696
PARAMETER_BYTES = 3122432
PARAMETER_BEATS = PARAMETER_BYTES // 8
PACKED_WORDS = 25600
EXPECTED_ARTIFACTS = {
    "input_native_DDR.hex": FULL_FIXTURE_DIR / "input_native_DDR.hex",
    "directory.hex": ROM_BUILD_DIR / "directory.hex",
    "parameter_memory.hex": ROM_BUILD_DIR / "parameter_memory.hex",
    "expected_raw_words.hex": FULL_FIXTURE_DIR / "expected_raw_words.hex",
    "expected_post_words.hex": FULL_FIXTURE_DIR / "expected_post_words.hex",
    "expected_packed_words.hex": FULL_FIXTURE_DIR / "expected_packed_words.hex",
    "expected_native_DDR.hex": FULL_FIXTURE_DIR / "expected_native_DDR.hex",
}
V2_ROM_SOURCE = {
    "conv_event_map.hex": ROOT / "deployment/hardware/z100_2026/native_conv_backend_v2/conv_event_map.hex",
    "conv_tiles.hex": ROOT / "deployment/hardware/z100_2026/native_conv_backend_v2/conv_tiles.hex",
}
PROOF_PATHS = {
    "first_conv_full_node_fixture": FIRST_FIXTURE,
    "first_conv_full_node_c_reference": C_REFERENCE,
    "generic_first_conv_event_numeric": GENERIC_NUMERIC,
    "rom_prefetch_first_conv_preparation": ROM_PREFETCH,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def report_path(name: str) -> Path:
    posix = PurePosixPath(name.replace("\\", "/"))
    if posix.parts and posix.parts[0] == "external":
        require(len(posix.parts) >= 3, "Malformed external proof path: " + name)
        return Path(posix.parts[1] + ":/", *posix.parts[2:])
    path = ROOT.joinpath(*posix.parts)
    resolved = path.resolve()
    require(resolved.is_relative_to(ROOT), "Proof path escapes workspace: " + name)
    return resolved


def project_path(name: str) -> Path:
    path = Path(name)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    require(resolved.is_relative_to(ROOT), "Backend source manifest/review must be inside the workspace")
    return resolved


def verify_hash_map(values: dict[str, str], label: str) -> dict[str, str]:
    checked: dict[str, str] = {}
    for name, expected in values.items():
        path = report_path(name)
        require(path.is_file(), f"{label} missing bound file: {name}")
        actual = sha256(path)
        require(actual == expected, f"{label} hash mismatch: {name}")
        checked[name.replace("\\", "/")] = actual
    return checked


def verify_proof(report_path_: Path, expected_status: str, label: str) -> dict[str, Any]:
    require(report_path_.is_file(), f"Missing frozen {label} report")
    report = json.loads(report_path_.read_text(encoding="utf-8"))
    require(report.get("status") == expected_status,
            f"Unexpected {label} status: {report.get('status')}")
    before = report.get("source_sha256_before", {})
    after = report.get("source_sha256_after", {})
    require(before == after, f"{label} source hashes were not stable")
    checked = verify_hash_map(after, label + " source")
    checked.update(verify_hash_map(report.get("artifact_sha256", {}), label + " artifact"))
    return {
        "report": report_path_.relative_to(ROOT).as_posix(),
        "report_sha256": sha256(report_path_),
        "status": report["status"],
        "checked_bound_file_count": len(checked),
        "bound_files_sha256": checked,
        "report_data": report,
    }


def fresh_output_dirs() -> tuple[str, Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    validation_root = ROOT / "validation/board_z100/native_conv_first_event_v2"
    build_root = ROOT / "deployment/build/native_conv_first_event_v2"
    validation_root.mkdir(parents=True, exist_ok=True)
    build_root.mkdir(parents=True, exist_ok=True)
    while True:
        validation_dir = validation_root / stamp
        build_dir = build_root / stamp
        if not validation_dir.exists() and not build_dir.exists():
            validation_dir.mkdir()
            build_dir.mkdir()
            return stamp, validation_dir, build_dir
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def stage_file(source: Path, target: Path, expected_hash: str | None = None) -> dict[str, Any]:
    require(source.is_file(), "Missing preparation input: " + str(source))
    source_hash = sha256(source)
    if expected_hash is not None:
        require(source_hash == expected_hash, "Input hash differs from frozen proof: " + str(source))
    shutil.copyfile(source, target)
    staged_hash = sha256(target)
    require(source_hash == staged_hash, "Staged asset copy hash mismatch: " + target.name)
    return {
        "source": source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else str(source),
        "staged": target.name,
        "size_bytes": target.stat().st_size,
        "sha256": staged_hash,
    }


def hex_shape(path: Path) -> tuple[int, int]:
    line_count = 0
    width: int | None = None
    with path.open("r", encoding="ascii") as stream:
        for raw_line in stream:
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            if width is None:
                width = len(line)
            require(len(line) == width, "Inconsistent hex line width in " + str(path))
            line_count += 1
    require(width is not None, "Empty hex memory image: " + str(path))
    return line_count, width


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", required=True,
                        help="stage source-bound inputs; never run numerical simulation")
    parser.add_argument("--elaborate-local", action="store_true",
                        help="run one bounded Icarus compile only (no vvp/simulation)")
    parser.add_argument("--backend-top", default="z100_native_conv_backend_v3",
                        help="module name recorded by the selected reviewed source manifest")
    parser.add_argument("--source-manifest", default=str(DEFAULT_MANIFEST.relative_to(ROOT)),
                        help="reviewed source manifest path relative to the workspace")
    parser.add_argument("--root-review", default=str(DEFAULT_ROOT_REVIEW.relative_to(ROOT)),
                        help="root review report for the selected source manifest")
    args = parser.parse_args()

    manifest_path = project_path(args.source_manifest)
    root_review_path = project_path(args.root_review)

    stamp, validation_dir, build_dir = fresh_output_dirs()
    result: dict[str, Any] = {
        "schema": "z100-native-conv-first-event-preparation/1",
        "status": "PREPARING",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": stamp,
        "board_access": False,
        "vendor_flow_run": False,
        "numerical_simulation_run": False,
        "synthesis_run": False,
        "hardware_access": False,
        "full_tensor_publication_claimed": False,
        "build_dir": build_dir.relative_to(ROOT).as_posix(),
        "validation_dir": validation_dir.relative_to(ROOT).as_posix(),
        "commands": {},
        "errors": [],
    }
    result_path = validation_dir / "result.json"

    try:
        require(DOC.is_file(), "Missing current deployment preparation documentation")
        doc_hash = sha256(DOC)

        require(manifest_path.is_file() and root_review_path.is_file(),
                "Missing immutable backend source manifest/root review")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        review = json.loads(root_review_path.read_text(encoding="utf-8"))
        require(manifest.get("schema") == "z100-native-conv-source-closure/1", "Unexpected V2 manifest schema")
        require(manifest.get("top") == args.backend_top, "Backend top differs from reviewed source manifest")
        require(manifest.get("status") == "LOCAL_ELABORATION_REVIEWED_NOT_FUNCTIONAL_OR_SYNTHESIS",
                "V2 manifest is not local-elaboration-only evidence")
        require(review.get("status", "").startswith("REVIEWED_NATIVE_CONV_") and
                review.get("status", "").endswith("_LOCAL_ELABORATION_ONLY_NOT_FUNCTIONAL_OR_SYNTHESIS"),
                "Backend root review is not an elaboration-only review")
        require(review.get("source_manifest", "").replace("\\", "/") ==
                manifest_path.relative_to(ROOT).as_posix(), "Root review references another manifest")
        require(review.get("numerical_parity_accepted") is False and
                review.get("synthesis_accepted") is False and
                review.get("board_access") is False and
                review.get("simulation_run") is False and
                review.get("vendor_flow_run") is False,
                "V2 root review reports a scope outside its accepted limits")
        manifest_sha = sha256(manifest_path)
        manifest_in_review = next((value for name, value in review.get("artifact_sha256", {}).items()
                                   if name.replace("\\", "/") == manifest_path.relative_to(ROOT).as_posix()), None)
        require(manifest_sha == manifest_in_review, "Root review does not bind the current V2 source manifest")
        backend_sources = verify_hash_map(manifest.get("synthesis_sources", {}), "Backend RTL")
        backend_roms = verify_hash_map(manifest.get("rom_assets", {}), "Backend ROM")
        rom_sources = {Path(name).name: report_path(name) for name in manifest["rom_assets"]}
        require(len(rom_sources) == 2 and set(rom_sources) == {"conv_event_map.hex", "conv_tiles.hex"},
                "Exactly two reviewed model ROM assets")
        require(len(backend_sources) > 0, "Backend source closure is empty")
        require(manifest.get("source_files_exclude_vendor_behavioral_models") is True,
                "V2 manifest unexpectedly includes vendor behavioral models")

        frozen: dict[str, Any] = {}
        expected_statuses = {
            "first_conv_full_node_fixture": "PASS_HOST_FIRST_CONV_FULL320ROW_NODE_ORIGINAL_OIHW_BINARY64_EXACT_FACTOR_AND_LAYOUT_NOT_RTL",
            "first_conv_full_node_c_reference": "PASS_HOST_UNMODIFIED_C_RUNTIME_PREFIX_FULL_NODE1638400_RAW_AND_POST_MATCH_INDEPENDENT_GOLDEN_NOT_PL",
            "generic_first_conv_event_numeric": "PASS_PRIVATE_GENERIC_FIRST_CONV_EVENT16_TILES_FULL_NATIVE_DDR_OIHW_C_PARITY_NOT_FULLGRAPH",
            "rom_prefetch_first_conv_preparation": "PREPARED_ROM_PREFETCH_FIRST_CONV16_V4_NOT_RTL_EXECUTED",
        }
        for key, proof_path in PROOF_PATHS.items():
            frozen[key] = verify_proof(proof_path, expected_statuses[key], key)

        first = frozen["first_conv_full_node_fixture"]["report_data"]
        cref = frozen["first_conv_full_node_c_reference"]["report_data"]
        generic = frozen["generic_first_conv_event_numeric"]["report_data"]
        rom = frozen["rom_prefetch_first_conv_preparation"]["report_data"]
        geometry = first.get("geometry", {})
        require(geometry.get("input_channels") == 3 and geometry.get("input_height") == 640 and
                geometry.get("input_width") == 640 and geometry.get("output_channels") == 16 and
                geometry.get("output_rows") == 320 and geometry.get("output_width") == 320 and
                geometry.get("kernel") == 3 and geometry.get("stride") == 2 and geometry.get("padding") == 1,
                "Frozen first Conv fixture geometry differs")
        require(first.get("feature_words") == SOURCE_BEATS and first.get("output_words") == PACKED_WORDS and
                first.get("raw_pixels") == 102400 and first.get("active_raw_lanes") == 1638400 and
                first.get("exact_factor_values") == 1638400,
                "Frozen first Conv fixture coverage differs")
        require(cref.get("raw_values") == 1638400 and cref.get("post_bytes") == 1638400,
                "Frozen C reference is not a full first Conv node")
        sim_counts = generic.get("simulation", {})
        for key, value in {
            "tiles": 16, "rows": 320, "runs": 5120, "descriptors": 46080,
            "raw_records": 102400, "post_records": 102400, "packed_words": 25600,
            "input_R": 209600, "parameter_directory_R": 3712,
            "output_W": 204800, "output_B": 12800, "guards": 57344,
        }.items():
            require(sim_counts.get(key) == value, f"Frozen generic numeric proof count changed: {key}")
        rom_context = rom.get("integration", {}).get("producer_context_matches_c_plan_assertion_oracle", {})
        for key, value in {
            "cin": 3, "input_height": 640, "input_width": 640,
            "output_y": 0, "output_rows": 20, "output_height": 320, "output_width": 320,
            "cout": 16, "kernel": 3, "stride": 2, "padding": 1, "parameter_first": 0,
        }.items():
            require(rom_context.get(key) == value, f"Prepared ROM fixture context changed: {key}")

        original_rom = rom.get("integration", {}).get("rom_fixtures", {})
        for basename, source in rom_sources.items():
            frozen_rom_entry = original_rom.get(basename, {})
            expected_rom_hash = backend_roms.get(source.relative_to(ROOT).as_posix())
            require(expected_rom_hash is not None and frozen_rom_entry.get("sha256") == expected_rom_hash,
                    "V2 ROM differs from frozen ROM producer fixture: " + basename)

        rom_artifacts = rom.get("artifact_sha256", {})
        fixture_artifacts = first.get("artifact_sha256", {})
        staged: dict[str, Any] = {}
        staged["input_native_DDR.hex"] = stage_file(
            EXPECTED_ARTIFACTS["input_native_DDR.hex"], build_dir / "input_native_DDR.hex",
            fixture_artifacts.get("deployment\\build\\z100_first_conv_full_node\\20261025T190809.773575Z\\input_native_DDR.hex"))
        for name in ("directory.hex", "parameter_memory.hex"):
            key = (ROOT / "build/rompfce_022810.468946Z" / name).relative_to(ROOT).as_posix()
            report_key = key
            expected_hash = next((h for n, h in rom_artifacts.items() if n.replace("\\", "/") == report_key), None)
            require(expected_hash is not None, "ROM prepared proof does not bind " + name)
            staged[name] = stage_file(EXPECTED_ARTIFACTS[name], build_dir / name, expected_hash)
        for name in ("expected_raw_words.hex", "expected_post_words.hex",
                     "expected_packed_words.hex", "expected_native_DDR.hex"):
            source = EXPECTED_ARTIFACTS[name]
            source_key = source.relative_to(ROOT).as_posix()
            expected_hash = next((h for n, h in fixture_artifacts.items()
                                  if n.replace("\\", "/") == source_key), None)
            require(expected_hash is not None, "First Conv fixture does not bind " + name)
            staged[name] = stage_file(source, build_dir / name, expected_hash)
        for basename, source in rom_sources.items():
            staged[basename] = stage_file(source, build_dir / basename,
                                          backend_roms[source.relative_to(ROOT).as_posix()])

        source_image_hash = sha256(EXPECTED_ARTIFACTS["input_native_DDR.hex"])
        generic_feature_hash = next((h for n, h in generic.get("artifact_sha256", {}).items()
                                     if n.replace("\\", "/") == "build/gce_004830.167160Z/feature_DDR.hex"), None)
        require(generic_feature_hash == source_image_hash,
                "Generic full-event input does not match original first Conv native DDR source")
        expected_shapes = {
            "input_native_DDR.hex": (SOURCE_BEATS, 128),
            "directory.hex": (DIRECTORY_BEATS, 16),
            "parameter_memory.hex": (PARAMETER_BEATS, 16),
            "expected_raw_words.hex": (102400, 264),
            "expected_post_words.hex": (102400, 64),
            "expected_packed_words.hex": (PACKED_WORDS, 128),
            "expected_native_DDR.hex": (PACKED_WORDS, 128),
        }
        for name, expected_shape in expected_shapes.items():
            actual_shape = hex_shape(build_dir / name)
            require(actual_shape == expected_shape,
                    f"{name} hex shape {actual_shape} != expected {expected_shape}")
        require(staged["parameter_memory.hex"]["size_bytes"] == PARAMETER_BEATS * 18,
                "Parameter payload text serialization differs from 3,122,432 bytes/390,304 64-bit beats")

        shutil.copyfile(TB_SOURCE, build_dir / TB_SOURCE.name)
        staged[TB_SOURCE.name] = {
            "source": TB_SOURCE.relative_to(ROOT).as_posix(),
            "staged": TB_SOURCE.name,
            "size_bytes": (build_dir / TB_SOURCE.name).stat().st_size,
            "sha256": sha256(build_dir / TB_SOURCE.name),
        }
        require(staged[TB_SOURCE.name]["sha256"] == sha256(TB_SOURCE), "Testbench copy hash mismatch")

        vendor_sources = [VENDOR / "unisims/DSP48E1.v", VENDOR / "unimacro/MULT_MACRO.v", VENDOR / "glbl.v"]
        require(all(path.is_file() for path in vendor_sources), "Required local vendor primitive model unavailable")
        rtl_paths = [report_path(name) for name in manifest["synthesis_sources"]]
        compiler = LOCAL_TOOLS / "bin/iverilog.exe"
        vvp = LOCAL_TOOLS / "bin/vvp.exe"
        require(compiler.is_file() and vvp.is_file(), "Pinned project-local Icarus tool unavailable")
        compile_argv = [str(compiler), "-B", str(LOCAL_TOOLS / "lib/ivl"), "-g2012", "-Wall", "-DNATIVE_CONV_BACKEND_TOP=" + args.backend_top,
                        "-s", "tb_z100_native_conv_first_event_v1", "-s", "glbl",
                        "-o", str(build_dir / "native_conv_first_event_v1.vvp")]
        compile_argv.extend(str(path) for path in rtl_paths)
        compile_argv.extend(str(path) for path in vendor_sources)
        compile_argv.append(str(build_dir / TB_SOURCE.name))
        run_argv = [str(vvp), "-M", str(LOCAL_TOOLS / "lib/ivl"), str(build_dir / "native_conv_first_event_v1.vvp")]
        doc_snapshot = build_dir / "preparation_scope_snapshot.md"
        shutil.copyfile(DOC, doc_snapshot)
        result["source_binding"] = {
            "docs": {"path": doc_snapshot.relative_to(ROOT).as_posix(), "sha256": doc_hash,
                     "original_document": DOC.relative_to(ROOT).as_posix()},
            "backend_top": args.backend_top,
            "backend_manifest": {"path": manifest_path.relative_to(ROOT).as_posix(), "sha256": manifest_sha},
            "backend_root_review": {"path": root_review_path.relative_to(ROOT).as_posix(), "sha256": sha256(root_review_path),
                               "status": review["status"]},
            "backend_rtl_source_count": len(backend_sources),
            "backend_rtl_sha256": backend_sources,
            "backend_rom_sha256": backend_roms,
            "frozen_proofs": {key: {k: v for k, v in proof.items() if k != "report_data"}
                              for key, proof in frozen.items()},
            "staged_assets": staged,
        }
        result["geometry_and_expected_coverage"] = {
            "event": 1, "model_crc": 2213989717, "epoch": 200,
            "cin": 3, "input": [640, 640], "cout": 16, "output": [320, 320],
            "kernel": 3, "stride": 2, "padding": 1, "rom_tiles": 16,
            "raw_records": 102400, "post_records": 102400, "packed_words": 25600,
            "source_R_beats": 209600, "parameter_R_beats_combined": 3712,
            "parameter_directory_file_beats": DIRECTORY_BEATS,
            "parameter_payload_bytes": PARAMETER_BYTES,
            "parameter_payload_file_beats": PARAMETER_BEATS,
            "output_W_beats": 204800, "output_AW_B_bursts": 12800,
            "output_region_bytes": 2097152, "guard_64bit_words": 57344,
        }
        result["contract"] = {
            "producer_complete": "All 16 tiles have completed their physical AXI write B responses; this is raw producer completion only.",
            "publication": "The containing runtime must publish the complete tensor through its actual ledger and await the ledger acknowledgement. This regression does not provide or assert that ledger.",
            "lease_and_reservation": "External testbench fixture inputs stay valid for the successful run; they are not evidence of formal lease or reservation ledger behavior.",
            "safety_gaps": [
                "This positive numerical event uses disjoint regions. Separate mock-arithmetic tests cover the V3 interval guards; no integrated caller ledger is exercised here.",
                "No lease-loss, cancellation, timeout, write-error or coordinated-reset recovery case is executed by the success-only numerical event.",
                "Full-graph operation, other node types, firmware/AXI-Lite integration, board platform, synthesis, timing and physical performance remain outside scope.",
                "The previous V2 root review accepted source/port elaboration only; numerical and synthesis acceptance remain false until later gates pass.",
            ],
        }
        result["commands"] = {
            "local_elaboration": {"argv": compile_argv, "cwd": str(build_dir),
                                  "executed": False, "log": str(validation_dir / "iverilog.log")},
            "numerical_execution": {"argv": run_argv, "cwd": str(build_dir), "executed": False,
                                    "expected_pass_marker": "NATIVE_CONV_FIRST_EVENT_PASS"},
        }
        vendor_bin = Path("C:/appload/2026.1/Vivado/bin")
        snapshot = "native_conv_first_event_v2_sim"
        result["commands"]["vendor_numerical"] = {
            "cwd": str(build_dir), "executed": False,
            "steps": [
                [str(vendor_bin / "xvlog.bat"), "-sv", "-d", "NATIVE_CONV_BACKEND_TOP=" + args.backend_top,
                 *map(str, rtl_paths), str(VENDOR / "glbl.v"), str(build_dir / TB_SOURCE.name)],
                [str(vendor_bin / "xelab.bat"), "-mt", "2", "-L", "unimacro_ver", "-L", "unisims_ver",
                 "tb_z100_native_conv_first_event_v1", "glbl", "-s", snapshot],
                [str(vendor_bin / "xsim.bat"), snapshot, "-runall"]],
            "expected_pass_marker": "NATIVE_CONV_FIRST_EVENT_PASS"}
        closed: dict[str, str] = {}
        closed.update(backend_sources)
        closed.update(backend_roms)
        for item in frozen.values():
            closed.update(item["bound_files_sha256"])
            closed[item["report"]] = item["report_sha256"]
        for path in [Path(__file__), TB_SOURCE, manifest_path, root_review_path, doc_snapshot,
                     ROOT / "tools/review_z100_native_conv_v2_elaboration.py", compiler, vvp, *vendor_sources]:
            name = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else "external/" + path.as_posix().replace(":", "")
            closed[name] = sha256(path)
        for path in build_dir.iterdir():
            if path.is_file():
                closed[path.relative_to(ROOT).as_posix()] = sha256(path)
        result["source_sha256_before"] = closed
        result["status"] = "RUNNING_LOCAL_ELABORATION" if args.elaborate_local else "STAGED_NOT_EXECUTED"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        elaboration = {"status": "NOT_RUN", "return_code": None, "log": None}
        if args.elaborate_local:
            log_path = validation_dir / "iverilog.log"
            try:
                with log_path.open("w", encoding="utf-8") as stream:
                    process = subprocess.Popen(compile_argv, cwd=build_dir, stdout=stream, stderr=subprocess.STDOUT)
                    result["commands"]["local_elaboration"].update(executed=True, pid=process.pid)
                    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                    print(json.dumps({"status": "RUNNING_LOCAL_ELABORATION", "pid": process.pid,
                                      "report": str(result_path.relative_to(ROOT))}), flush=True)
                    return_code = process.wait()
                compiler_log = log_path.read_text(errors="replace")
                require(not re.search(r"error:|dangling input|floating|implicit definition|Unable to bind|Unknown module|expects .*got", compiler_log, re.I),
                        "Unclosed actual numerical testbench ports/modules/widths")
                warning_lines = [line for line in compiler_log.splitlines() if "warning:" in line.lower()]
                require(all(warning_class(line) is not None for line in warning_lines), "Unclassified local elaboration warning")
                elaboration = {
                    "status": "PASS_LOCAL_ICARUS_SOURCE_AND_PORT_ELABORATION" if return_code == 0 else
                             "FAIL_LOCAL_ICARUS_SOURCE_AND_PORT_ELABORATION",
                    "return_code": return_code,
                    "log": log_path.relative_to(ROOT).as_posix(),
                    "log_sha256": sha256(log_path),
                    "compiled_output_sha256": sha256(build_dir / "native_conv_first_event_v1.vvp")
                    if (build_dir / "native_conv_first_event_v1.vvp").is_file() else None,
                }
            except subprocess.TimeoutExpired as exc:
                output = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                log_path.write_text(output + "\nLOCAL_ICARUS_COMPILE_TIMEOUT after 90 seconds; no retry.\n", encoding="utf-8")
                elaboration = {"status": "TIMEOUT_LOCAL_ICARUS_SOURCE_AND_PORT_ELABORATION",
                               "return_code": None, "log": log_path.relative_to(ROOT).as_posix(),
                               "log_sha256": sha256(log_path)}
            result["local_elaboration"] = elaboration
        else:
            result["local_elaboration"] = elaboration

        if args.elaborate_local and elaboration["status"] != "PASS_LOCAL_ICARUS_SOURCE_AND_PORT_ELABORATION":
            result["status"] = "PREPARED_LOCAL_ELABORATION_FAILED_NUMERICAL_UNEXECUTED"
        elif args.elaborate_local:
            result["status"] = "PREPARED_LOCAL_ELABORATION_PASS_NUMERICAL_UNEXECUTED"
        else:
            result["status"] = "PREPARED_NUMERICAL_AND_ELABORATION_UNEXECUTED"

        # Recheck all authored/staged RTL and assets before binding the report.
        require(sha256(TB_SOURCE) == staged[TB_SOURCE.name]["sha256"], "Testbench changed during preparation")
        result["validation_summary"] = {
            "source_hash_gates": "PASS",
            "source_assets_staged_and_hash_matched": len(staged),
            "local_elaboration": elaboration["status"],
            "numerical_simulation": "NOT_EXECUTED",
            "vendor_flow": "NOT_EXECUTED",
        }
    except Exception as exc:  # Preserve preparation failure evidence in its unique run directory.
        result["status"] = "PREPARATION_FAILED_CLOSED"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["validation_summary"] = {"source_hash_gates": "FAILED", "numerical_simulation": "NOT_EXECUTED"}

    try:
        if result.get("source_sha256_before"):
            result["source_sha256_after"] = verify_hash_map(result["source_sha256_before"], "Final closed input")
            require(result["source_sha256_before"] == result["source_sha256_after"], "Preparation source drift")
    except Exception as exc:
        result["status"] = "PREPARATION_FAILED_CLOSED"
        result["errors"].append(f"Final source binding: {type(exc).__name__}: {exc}")
    result["artifact_sha256"] = {path.relative_to(ROOT).as_posix(): sha256(path)
                                for folder in [validation_dir, build_dir] for path in folder.rglob("*")
                                if path.is_file() and path != result_path}
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "result": str(result_path),
                      "build_dir": str(build_dir), "errors": result["errors"]}, indent=2))
    return 0 if result["status"] in {"PREPARED_NUMERICAL_AND_ELABORATION_UNEXECUTED", "PREPARED_LOCAL_ELABORATION_PASS_NUMERICAL_UNEXECUTED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
