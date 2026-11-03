#!/usr/bin/env python3
"""Prepare a source-bound MMIO first-event Conv simulation; never runs tools."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

SCHEMA = "z100-native-conv-mmio-first-event-preparation/1"
ROOT_REVIEW_REL = Path("validation/board_z100/native_conv_mmio_backend_elab_v1_review/20261026T112148Z_afcf99/result.json")
ROOT_REVIEW_SHA256 = "9073553a1c0a57bda0977ac5d733af762644f280f3390bf960d10ad7134a8737"
FIXTURE_REPORT_REL = Path("validation/board_z100/native_conv_first_event_v2/20261026T064115.441661Z/result.json")
FIXTURE_REPORT_SHA256 = "ff70818979fee2a6c42d40932316f1a083154a3e61e72eb52a91824c15718799"
BACKEND_MANIFEST_REL = Path("deployment/build/z100_native_conv_backend_v3_review/20261026T063511.355431Z/source_manifest.json")
BACKEND_MANIFEST_SHA256 = "eee8d10d1e2f12ee06580727e77e4745e7fccf3d87245b7e06709c35f319fe95"
FRONTEND_REL = Path("deployment/hardware/z100_2026/native_conv_mmio_v2/z100_native_conv_mmio_v2.sv")
WRAPPER_REL = Path("deployment/hardware/z100_2026/native_conv_mmio_backend_v1/z100_native_conv_mmio_backend_v1.sv")
TB_REL = Path("deployment/simulation/native_conv_mmio_first_event_v1/tb_z100_native_conv_mmio_first_event_v1.sv")
DOC_REL = Path("docs/z100_native_conv_mmio_first_event_v1.md")
TOOL_REL = Path("tools/prepare_z100_native_conv_mmio_first_event_v1.py")
ORIGINAL_TB_REL = Path("deployment/simulation/native_conv_first_event_v1/tb_z100_native_conv_first_event_v1.sv")
EXPECTED_ORIGINAL_TB_SHA256 = "feed5733142a822b5c73ec29262c79170f6b30e5cf122dc8ae28e4ad8d338172"
VENDOR_EXPECTED = {
    "DSP48E1.v": "4060111c8de44f786fdc982de9caaa88fc0b2c44fcd6d0f0f7ec188a58793bd0",
    "MULT_MACRO.v": "d8ad46e2f5c808f52d4029025695ff7f67d6526c009bcaba0a75e84eecc27a2c",
    "glbl.v": "6270251cf35e1fce3119fc79f8fb968912f7983027e43cf030409ba68f048936",
}
VENDOR_REVIEW_PATHS = {
    "DSP48E1.v": Path("C:/appload/2026.1/data/verilog/src/unisims/DSP48E1.v"),
    "MULT_MACRO.v": Path("C:/appload/2026.1/data/verilog/src/unimacro/MULT_MACRO.v"),
    "glbl.v": Path("C:/appload/2026.1/data/verilog/src/glbl.v"),
}
FIXTURE_ASSETS = (
    "conv_event_map.hex",
    "conv_tiles.hex",
    "directory.hex",
    "parameter_memory.hex",
    "input_native_DDR.hex",
    "expected_raw_words.hex",
    "expected_post_words.hex",
    "expected_packed_words.hex",
    "expected_native_DDR.hex",
)
EXPECTED_ASSET_HASHES = {
    "conv_event_map.hex": "7f5dbedbc8b0487350ea40465b2e6ae1bc404e6c167da25b72cedf94e4dbaf85",
    "conv_tiles.hex": "8295ab50a944c6b8c61b97515d8a388919f287dd2c487c63c6da997a64c99f0c",
    "directory.hex": "41dab50f4db049ee3072cf41a7cd5927368f6f7a2b2608c1396c93b6d020ac93",
    "parameter_memory.hex": "d820670a3577e08b2cce29522f6500ae59dc32298e0eae30a7685090530d1cc2",
    "input_native_DDR.hex": "4a40ee9516e069766aa1974d02a6eef09cccafa4a7e83923b5d2653f728055ce",
    "expected_raw_words.hex": "624f4417828a755b2bc71a2d63d6afc172e9a2e13abea70c799c068ad3128c56",
    "expected_post_words.hex": "48cd3d7f3cafe8d4469c14d1ecbc2af830cd747c2d0f531ec6a6ce2f267f2271",
    "expected_packed_words.hex": "06d3cf5cd1aeae8d6da0986bb2bbd83489ab89f77f1c3948a62b28793a7fa3bb",
    "expected_native_DDR.hex": "c75f14182d94f6da45829c51213000f78e1d9a2a3de90784a42ea6840c80c662",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def norm(path: Path) -> str:
    return path.resolve().as_posix()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def module_port_names(wrapper_text: str) -> list[str]:
    m = re.search(
        r"module\s+z100_native_conv_mmio_backend_v1\s*#\s*\(.*?\)\s*\((.*?)\)\s*;",
        wrapper_text,
        re.S,
    )
    require(m is not None, "Could not find wrapper parameterized module port header")
    return re.findall(
        r"\b(?:input|output|inout)\s+(?:(?:wire|reg|logic)\s+)?(?:\[[^\]]+\]\s*)?(\w+)",
        m.group(1),
    )


def instance_port_names(tb_text: str) -> list[str]:
    m = re.search(
        r"z100_native_conv_mmio_backend_v1\s*#\s*\(.*?\)\s+dut\s*\((.*?)\)\s*;",
        tb_text,
        re.S,
    )
    require(m is not None, "Could not find explicit MMIO wrapper DUT instance")
    return re.findall(r"\.(\w+)\s*\(", m.group(1))


def static_tb_checks(tb: Path, wrapper: Path) -> dict[str, Any]:
    text = tb.read_text(encoding="utf-8")
    wrapper_text = wrapper.read_text(encoding="utf-8")
    expected_signals = (
        "raw_valid", "raw_ready", "raw_data", "raw_overflow", "post_valid", "post_ready",
        "post_data", "packed_valid", "packed_ready", "packed_address", "packed_data",
        "tile_output_y", "producer_context_valid", "producer_complete", "active", "fault",
    )
    for name in expected_signals:
        alias = re.search(
            rf"\bwire\s+(?:\[[^\]]+\]\s*)?{name}\s*=\s*dut\.u_conv_backend\.{name}\s*;",
            text,
        )
        require(alias is not None, f"Missing explicit backend probe alias: {name}")
    require("wire backend_cmd_valid = dut.u_mmio_frontend.backend_cmd_valid;" in text,
            "Backend command valid is not observed from the real frontend")
    require("wire backend_cmd_ready = dut.u_conv_backend.cmd_ready;" in text,
            "Backend command ready is not observed from the real backend")
    require("NATIVE_CONV_BACKEND_TOP" not in text and "cmd_valid && cmd_ready" not in text,
            "Old direct-backend stimulus or macro remains")
    require("force " not in text.lower(), "Procedural force statement is forbidden")
    require("expected_raw" in text and "expected_post" in text and "expected_packed" in text,
            "Original numerical goldens are missing")
    require("MMIO_FIRST_EVENT_PASS" in text and "NATIVE_CONV_FIRST_EVENT_PASS" not in text,
            "Distinct future MMIO pass marker missing")
    required_tokens = (
        "mmio_write_reg(MMIO_REG_CONTROL,MMIO_CONTROL_START",
        "mmio_write_reg(MMIO_REG_CONTROL,MMIO_CONTROL_ACK",
        "for (i=0;i<27;i=i+1)",
        "for (mmio_result_index=0;mmio_result_index<10;",
        "mmio_held_b==0 || mmio_held_r==0",
        "mmio_aw_first_calls!=15 || mmio_w_first_calls!=14",
        "source_ar_count!=209600 || source_r_count!=209600",
        "directory_r_count+payload_r_count!=3712",
        "raw_count!=RAW_RECORDS || post_count!=POST_RECORDS || packed_count!=PACKED_WORDS",
        "aw_count!=12800 || w_count!=OUTPUT_W_BEATS || b_count!=12800",
    )
    for token in required_tokens:
        require(token in text, f"Missing required TB coverage check: {token}")
    for token in (
        "CMD_EPOCH = 32'd200", "CMD_EVENT = 8'd1", "CMD_MODEL_CRC = 32'd2213989717",
        "cmd_source_generation = 32'd6901", "cmd_destination_generation = 32'd8201",
        "CMD_PARAMETER_COUNT = 16'd173", "CMD_SOURCE_REGION_END = 33'h010190000",
        "CMD_DESTINATION_REGION_END = 33'h030200000", "cmd_parameter_payload_end = 33'h0202fa500",
        "CMD_COOKIE = 32'hc0decafe", "CMD_PREACCEPT_TIMEOUT = 32'd5000000",
    ):
        require(token in text, f"Command fixture identity/geometry not present in testbench: {token}")
    ports = module_port_names(wrapper_text)
    connected = instance_port_names(text)
    require(len(ports) == len(set(ports)), "Wrapper port parser found duplicate port names")
    require(len(connected) == len(set(connected)), "Wrapper instance connects a port more than once")
    require(set(ports) == set(connected),
            f"DUT port map mismatch missing={sorted(set(ports)-set(connected))} extra={sorted(set(connected)-set(ports))}")
    require(".platform_rst_n(rst_n)" in text and ".clk(clk)" in text,
            "Wrapper clock/platform reset are not connected")
    return {
        "testbench_module": "tb_z100_native_conv_mmio_first_event_v1",
        "selected_dut": "z100_native_conv_mmio_backend_v1",
        "wrapper_port_count": len(ports),
        "wrapper_ports_connected_exactly_once": True,
        "backend_internal_probes_are_explicit_aliases": True,
        "mmio_shadow_start_result_ack_static_checks": True,
        "old_direct_command_instance_absent": True,
        "goldens_assertion_only_by_source_structure": True,
        "compile_or_simulation_performed": False,
    }


def make_recipe(build_dir: Path, rtl_sources: list[Path], tb: Path, vendor: list[Path]) -> tuple[dict[str, Any], str]:
    vivado_bin = Path("C:/appload/2026.1/Vivado/bin")
    xvlog = vivado_bin / "xvlog.bat"
    xelab = vivado_bin / "xelab.bat"
    xsim = vivado_bin / "xsim.bat"
    rtl_cmd = [str(xvlog), "-sv", "-work", "xil_defaultlib", *[norm(p) for p in rtl_sources], norm(tb)]
    vendor_cmd = [str(xvlog), "-work", "xil_defaultlib", *[norm(p) for p in vendor]]
    elaborate_cmd = [str(xelab), "-mt", "2", "-debug", "typical",
                     "xil_defaultlib.tb_z100_native_conv_mmio_first_event_v1",
                     "xil_defaultlib.glbl", "-s", "z100_native_conv_mmio_first_event_v1_sim"]
    simulate_cmd = [str(xsim), "z100_native_conv_mmio_first_event_v1_sim", "-runall"]
    recipe = {
        "working_directory": norm(build_dir),
        "commands": [
            {"step": "compile_actual_vendor_and_glbl_models", "argv": vendor_cmd},
            {"step": "compile_37_rtl_sources_and_testbench", "argv": rtl_cmd},
            {"step": "elaborate_selected_testbench_and_glbl_max_2_threads", "argv": elaborate_cmd},
            {"step": "future_numerical_simulation", "argv": simulate_cmd},
        ],
        "commands_executed": 0,
    }

    def q(s: str) -> str:
        return '"' + s.replace('"', '\\"') + '"'

    lines = ["@echo off", f"cd /d {q(norm(build_dir))}"]
    for item in recipe["commands"]:
        lines.append("\nrem " + item["step"])
        lines.append(" ".join(q(x) if (" " in x or "\\" in x) else x for x in item["argv"]))
        lines.append("if errorlevel 1 exit /b %errorlevel%")
    return recipe, "\r\n".join(lines) + "\r\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", required=True,
                        help="Stage pinned inputs and emit checks/commands; never compile or simulate")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    require(root.is_dir(), f"Project root does not exist: {root}")

    root_review_path = root / ROOT_REVIEW_REL
    fixture_report_path = root / FIXTURE_REPORT_REL
    manifest_path = root / BACKEND_MANIFEST_REL
    wrapper_path = root / WRAPPER_REL
    frontend_path = root / FRONTEND_REL
    tb_path = root / TB_REL
    original_tb_path = root / ORIGINAL_TB_REL

    require(sha256(root_review_path) == ROOT_REVIEW_SHA256, "Pinned wrapper review report hash mismatch")
    require(sha256(fixture_report_path) == FIXTURE_REPORT_SHA256, "Pinned whole-Conv fixture report hash mismatch")
    require(sha256(manifest_path) == BACKEND_MANIFEST_SHA256, "Pinned backend manifest hash mismatch")
    root_review = read_json(root_review_path)
    fixture_report = read_json(fixture_report_path)
    manifest = read_json(manifest_path)
    require(root_review.get("status") == "PASS_REVIEWED_LOCAL_ELABORATION_ONLY_NOT_FUNCTIONAL_OR_SYNTHESIS",
            "MMIO wrapper review is not the pinned reviewed local-elaboration result")
    require(root_review.get("local_elaboration_review_accepted") is True and
            root_review.get("functional_integration_accepted") is False and
            root_review.get("numeric_parity_accepted") is False and
            root_review.get("synthesis_or_mapping_accepted") is False,
            "Wrapper review acceptance scope changed")
    require(fixture_report.get("status") == "PREPARED_LOCAL_ELABORATION_PASS_NUMERICAL_UNEXECUTED" and
            fixture_report.get("numerical_simulation_run") is False,
            "Whole-Conv fixture is not the pinned numerical-unexecuted preparation")
    require(fixture_report.get("full_tensor_publication_claimed") is False,
            "Pinned fixture report has a full-publication claim")
    require(manifest.get("status") == "LOCAL_ELABORATION_REVIEWED_NOT_FUNCTIONAL_OR_SYNTHESIS" and
            manifest.get("numeric_and_synthesis_accepted") is False,
            "Backend source manifest scope/status changed")
    bindings = root_review["source_bindings"]
    require(bindings["manifest_sha256"] == BACKEND_MANIFEST_SHA256,
            "Wrapper review does not bind the pinned V3 backend manifest")
    require(bindings["wrapper_sha256"] == sha256(wrapper_path), "Current MMIO wrapper differs from reviewed bytes")
    require(bindings["frontend_sha256"] == sha256(frontend_path), "Current MMIO frontend differs from reviewed bytes")
    require(bindings["backend_review_sha256"] == "958de95e4520746e3f5fe1e1a313144b17f22a1453cb1ba6b216d7c4e6fc543b",
            "Wrapper review no longer binds the pinned backend review")
    require(sha256(original_tb_path) == EXPECTED_ORIGINAL_TB_SHA256,
            "Frozen original full first-Conv testbench changed")

    vendor_review = root_review["vendor_model_identity"]
    require(vendor_review.get("exact_file_identity_matches_reviewed_v3_vendor_paths") is True,
            "Wrapper review vendor source identity was not accepted")
    vendor: list[Path] = []
    for filename, path in VENDOR_REVIEW_PATHS.items():
        require(vendor_review["sha256_by_filename"].get(filename) == VENDOR_EXPECTED[filename],
                f"Vendor model hash in wrapper review mismatches pinned identity: {filename}")
        require(Path(path).is_file(), f"Reviewed Vivado vendor model path is missing: {path}")
        require(sha256(path) == VENDOR_EXPECTED[filename], f"Reviewed Vivado vendor model content changed: {path}")
        vendor.append(path)
    actual_paths = {Path(p).name: Path(p) for p in vendor_review["actual_compile_paths"]}
    for filename, selected_path in zip(("DSP48E1.v", "MULT_MACRO.v", "glbl.v"), vendor):
        reviewed_path = actual_paths.get(filename)
        require(reviewed_path is not None and reviewed_path.is_file(),
                f"Vendor review source path unavailable: {filename}")
        require(sha256(reviewed_path) == sha256(selected_path) == VENDOR_EXPECTED[filename],
                f"Reviewed vendor source and selected installed source are not byte-identical: {filename}")

    rtl_hashes: dict[str, str] = manifest["synthesis_sources"]
    require(len(rtl_hashes) == 35, f"Expected pinned 35-file V3 RTL closure, got {len(rtl_hashes)}")
    rtl_sources: list[Path] = []
    input_paths: set[Path] = set()
    for rel, expected in rtl_hashes.items():
        path = (root / Path(rel.replace("\\", "/"))).resolve()
        require(path.is_file() and sha256(path) == expected, f"V3 RTL source hash mismatch: {rel}")
        rtl_sources.append(path)
        input_paths.add(path)
    require(len(manifest["rom_assets"]) == 2, "Expected exactly two V3 producer ROM assets")
    for rel, expected in manifest["rom_assets"].items():
        path = (root / Path(rel.replace("\\", "/"))).resolve()
        require(path.is_file() and sha256(path) == expected, f"V3 ROM source hash mismatch: {rel}")

    require(len(rtl_sources) == 35, "Backend RTL count changed")
    rtl_sources.extend((frontend_path.resolve(), wrapper_path.resolve()))
    require(len(rtl_sources) == 37 and len(set(rtl_sources)) == 37, "37-source RTL closure invalid")
    input_paths.update(p.resolve() for p in rtl_sources)
    doc_path = root / DOC_REL
    tool_path = root / TOOL_REL
    input_paths.update((root_review_path.resolve(), fixture_report_path.resolve(), manifest_path.resolve(),
                        original_tb_path.resolve(), tb_path.resolve(), doc_path.resolve(), tool_path.resolve(),
                        *[p.resolve() for p in vendor]))

    fixture_build = root / Path(fixture_report["build_dir"])
    artifact_map = fixture_report["artifact_sha256"]
    staged_source_paths: dict[str, Path] = {}
    for name in FIXTURE_ASSETS:
        rel = (Path(fixture_report["build_dir"]) / name).as_posix()
        source = root / Path(rel)
        expected = EXPECTED_ASSET_HASHES[name]
        require(artifact_map.get(rel) == expected, f"Pinned fixture report asset binding changed: {rel}")
        require(source.is_file() and sha256(source) == expected, f"Fixture source asset mismatch: {rel}")
        staged_source_paths[name] = source.resolve()
        input_paths.add(source.resolve())
    geometry = fixture_report["geometry_and_expected_coverage"]
    expected_geometry = {
        "epoch": 200, "event": 1, "model_crc": 2213989717, "cin": 3, "input": [640, 640],
        "cout": 16, "output": [320, 320], "rom_tiles": 16, "raw_records": 102400,
        "post_records": 102400, "packed_words": 25600, "source_R_beats": 209600,
        "parameter_R_beats_combined": 3712, "parameter_directory_file_beats": 696,
        "parameter_payload_bytes": 3122432, "output_W_beats": 204800,
        "output_AW_B_bursts": 12800, "guard_64bit_words": 57344,
    }
    for key, expected in expected_geometry.items():
        require(geometry.get(key) == expected, f"Pinned fixture geometry changed for {key}: {geometry.get(key)}")

    static_checks = static_tb_checks(tb_path, wrapper_path)
    input_hashes_before = {norm(p): sha256(p) for p in sorted(input_paths, key=lambda q: q.as_posix().lower())}
    require(input_hashes_before[norm(tb_path)] == sha256(tb_path), "Testbench source hash could not be captured")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    build_dir = root / "deployment" / "build" / "native_conv_mmio_first_event_v1" / stamp
    validation_dir = root / "validation" / "board_z100" / "native_conv_mmio_first_event_v1" / stamp
    require(not build_dir.exists() and not validation_dir.exists(), "Unique output directory collision")
    build_dir.mkdir(parents=True)
    validation_dir.mkdir(parents=True)

    staged_hashes: dict[str, str] = {}
    for name, source in staged_source_paths.items():
        dest = build_dir / name
        shutil.copyfile(source, dest)
        staged_hashes[name] = sha256(dest)
        require(staged_hashes[name] == EXPECTED_ASSET_HASHES[name], f"Staged fixture hash mismatch: {name}")
    source_closure = {
        "top": "z100_native_conv_mmio_backend_v1",
        "testbench_top": "tb_z100_native_conv_mmio_first_event_v1",
        "rtl_source_count": len(rtl_sources),
        "rtl_sources": [norm(p) for p in rtl_sources],
        "vendor_simulation_models": [norm(p) for p in vendor],
        "vendor_model_sha256": {Path(p).name: sha256(p) for p in vendor},
        "glbl_selected": True,
        "runtime_assets": {name: {"path": norm(build_dir / name), "sha256": staged_hashes[name]}
                           for name in FIXTURE_ASSETS},
        "testbench": {"path": norm(tb_path), "sha256": sha256(tb_path)},
        "synthesis_or_functional_claim": False,
        "numeric_simulation_executed": False,
    }
    (build_dir / "source_closure.json").write_text(json.dumps(source_closure, indent=2) + "\n", encoding="utf-8")
    recipe, recipe_text = make_recipe(build_dir, rtl_sources, tb_path, vendor)
    (build_dir / "commands.json").write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    (build_dir / "run_prepared_xsim.cmd").write_text(recipe_text, encoding="utf-8", newline="")

    # The testbench itself and every bound source must stay unchanged while staging.
    input_hashes_after = {norm(p): sha256(p) for p in sorted(input_paths, key=lambda q: q.as_posix().lower())}
    require(input_hashes_before == input_hashes_after, "Bound input source changed during prepare-only staging")
    artifacts = [build_dir / name for name in FIXTURE_ASSETS]
    artifacts.extend((build_dir / "source_closure.json", build_dir / "commands.json", build_dir / "run_prepared_xsim.cmd"))
    artifact_hashes = {norm(p): sha256(p) for p in artifacts}
    result = {
        "schema": SCHEMA,
        "status": "PREPARED_MMIO_FIRST_EVENT_NUMERICAL_RUN_PENDING",
        "run_id": stamp,
        "preparation_only": True,
        "compile_executed": False,
        "elaboration_executed": False,
        "numerical_simulation_executed": False,
        "numerical_parity_accepted": False,
        "full_tensor_publication_claimed": False,
        "board_or_hardware_access": False,
        "future_testbench_pass_marker": "MMIO_FIRST_EVENT_PASS",
        "future_pass_marker_observed": False,
        "build_dir": norm(build_dir),
        "validation_dir": norm(validation_dir),
        "pinned_inputs": {
            "wrapper_review": {"path": norm(root_review_path), "sha256": ROOT_REVIEW_SHA256,
                                "status": root_review["status"]},
            "whole_conv_fixture_report": {"path": norm(fixture_report_path), "sha256": FIXTURE_REPORT_SHA256,
                                           "status": fixture_report["status"]},
            "backend_manifest": {"path": norm(manifest_path), "sha256": BACKEND_MANIFEST_SHA256},
            "original_direct_backend_tb": {"path": norm(original_tb_path),
                                            "sha256": EXPECTED_ORIGINAL_TB_SHA256},
            "new_testbench": {"path": norm(tb_path), "sha256": sha256(tb_path)},
            "preparer": {"path": norm(tool_path), "sha256": sha256(tool_path)},
            "design_note": {"path": norm(doc_path), "sha256": sha256(doc_path)},
        },
        "source_sha256_before": input_hashes_before,
        "source_sha256_after": input_hashes_after,
        "source_hashes_before_after_equal": input_hashes_before == input_hashes_after,
        "actual_source_closure": source_closure,
        "static_checks": static_checks,
        "geometry_and_required_coverage": expected_geometry,
        "contract": {
            "DUT_command_entry": "27 words over AXI-Lite shadow registers, START through control register, results read over AXI-Lite, ACK=8",
            "memory_model": "actual AXI64 source/parameter reads and destination AXI64 writes; no fixture geometry injection",
            "goldens": "raw/post/packed/native DDR expected files are assertion-only",
            "producer_complete": "physical raw tile completion after output B drains; does not mean full tensor publication",
            "lease_reservation": "frontend-generated fixture grants are exercised; this is not ledger proof",
            "fullgraph": "not exercised or claimed",
        },
        "commands": recipe,
        "execution_scope_pending": [
            "No compile or numerical simulation has been run for this MMIO integration.",
            "The future 37-RTL/vendor/glbl simulation requires a primary-controlled execution gate.",
            "The expected MMIO_FIRST_EVENT_PASS marker is only a future testbench assertion, not observed evidence.",
        ],
        "artifact_sha256": artifact_hashes,
        "artifact_sha256_excludes_self": True,
    }
    report_path = validation_dir / "result.json"
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "build_dir": norm(build_dir),
                      "validation_dir": norm(validation_dir), "rtl_source_count": len(rtl_sources),
                      "staged_asset_count": len(staged_hashes), "commands_executed": 0,
                      "report": norm(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"PREPARATION_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
