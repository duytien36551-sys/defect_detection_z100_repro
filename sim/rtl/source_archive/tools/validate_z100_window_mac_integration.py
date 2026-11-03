"""Run a source-bound current-model feature-window to native-MAC XSim check."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from z100_feature_window_layout import FeatureLayout

ROOT = Path(__file__).resolve().parents[1]
RTL_DIR = ROOT / "deployment/hardware/z100_2026"
FIXTURE = RTL_DIR / "window_mac_integration_v1"
BANK_RTL = RTL_DIR / "feature_banks_v1/z100_feature_banks.sv"
WINDOW_RTL = RTL_DIR / "feature_window_v2/z100_feature_window.sv"
MAC_RTL = RTL_DIR / "window_mac_v1/z100_window_mac.sv"
BRIDGE_RTL = FIXTURE / "z100_window_mac_bridge.sv"
TB = FIXTURE / "tb_z100_window_mac_integration.sv"
LAYOUT_TOOL = ROOT / "tools/z100_feature_window_layout.py"
CONVERTER = ROOT / "tools/prepare_z100_native_window_weights.py"
REQUANT_TOOL = ROOT / "tools/z100_requant_thresholds.py"

PIPELINE = ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline"
PACKAGE = PIPELINE / "package"
MODEL_PACKAGE = PACKAGE / "MODEL.V8P"
MODEL_HEADER = PACKAGE / "v8_generated_model.h"
MODEL_GRAPH = PIPELINE / "model/graph.json"
INPUT = ROOT / "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_nchw_int8.bin"
HOST_PARITY = INPUT.parent / "result.json"
NATIVE_BUILD = ROOT / "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef"
NATIVE_WEIGHTS = NATIVE_BUILD / "weights_group4x32.bin"
NATIVE_BIASES = NATIVE_BUILD / "biases_int32x32.bin"
NATIVE_MANIFEST = NATIVE_BUILD / "manifest.json"
NATIVE_REPORT = ROOT / "validation/board_z100/native_window_weights/20261023T163945.127217Z_2b86c9ef/result.json"
COMPONENT_REVIEW = ROOT / "validation/board_z100/acceleration_resource_review/20261023T165119.142697Z/native_components_review.json"

EXPECTED_HASHES = {
    "deployment/hardware/z100_2026/feature_banks_v1/z100_feature_banks.sv":
        "1120057983cc822d35f56b2245174d11734307a485cdb20966aba0579ae22310",
    "deployment/hardware/z100_2026/feature_window_v2/z100_feature_window.sv":
        "d6208a8b0f40f36c407c6ccc883f34fa70fc026025181015d7dc16bca92a9857",
    "deployment/hardware/z100_2026/window_mac_v1/z100_window_mac.sv":
        "c2de472f539276da097e5ccd5bc7d44f2695dbff55ecb73458ea0105accbb643",
    "tools/z100_feature_window_layout.py":
        "54ec4f90867ec9f043fae52270e3b46dc8caf996655abd546c9630333048231a",
    "tools/prepare_z100_native_window_weights.py":
        "6d10d785e0a8eda98e4282b2ec38397706b10ccfc385da1c65eecb47d2e637f3",
    "tools/z100_requant_thresholds.py":
        "e4b18bffcb23299794b726121ebec174420e3a3232e21ab5562ee27c535693b2",
    "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package/MODEL.V8P":
        "96211aa416da6b23955a8b62cca594275daaa4db3e3954632960707c0ec0d44f",
    "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package/v8_generated_model.h":
        "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5",
    "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/model/graph.json":
        "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8",
    "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_nchw_int8.bin":
        "0d458d68cf3e419e238245193cd5415c75b2931eb011a695c7b5a5765a1718b6",
    "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/result.json":
        "331d8a3dfb78042898ab860ecd0098d5e1b20d986cfdda0d9dba2a2db0b977e6",
    "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef/manifest.json":
        "081aff4a32bc27123863ebf0d44d543d2561feffcd72e378233c974597f6a3e5",
    "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef/weights_group4x32.bin":
        "9232bf379643e06e966c2a89aee0de854eca25a1f9d6872ff391ed3e44eb91a2",
    "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef/biases_int32x32.bin":
        "e228de7b7d9641d0b29d42e512477b19e44bbfe6d1f49c2c8d5b3e2bd0e36ff2",
}

VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
PYTHON = Path("C:/Users/Administrator/Desktop/v8/.venv/Scripts/python.exe")
JOBS = ((0, 0), (0, 317), (1, 11), (100, 40), (101, 0), (101, 317))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def signed8(value: int) -> int:
    return value - 256 if value >= 128 else value


def signed32le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def parse_header_field(row: str, name: str) -> int:
    hits = re.findall(r"\." + re.escape(name) + r"=(\d+)(?:,|})", row)
    if len(hits) != 1:
        raise ValueError(f"Missing or ambiguous model-header field {name}")
    return int(hits[0])


def run_logged(name: str, command: list[str], build: Path, evidence: Path,
               env: dict[str, str], result: dict) -> str:
    completed = subprocess.run(
        command,
        cwd=build,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout
    (evidence / f"{name}.log").write_text(output, encoding="utf-8")
    result["commands"].append({"name": name, "args": list(map(str, command)),
                               "return_code": completed.returncode})
    if completed.returncode:
        raise RuntimeError(f"{name} returned {completed.returncode}")
    return output


def verify_source_bindings() -> tuple[dict[str, str], dict]:
    paths = {
        "deployment/hardware/z100_2026/feature_banks_v1/z100_feature_banks.sv": BANK_RTL,
        "deployment/hardware/z100_2026/feature_window_v2/z100_feature_window.sv": WINDOW_RTL,
        "deployment/hardware/z100_2026/window_mac_v1/z100_window_mac.sv": MAC_RTL,
        "deployment/hardware/z100_2026/window_mac_integration_v1/z100_window_mac_bridge.sv": BRIDGE_RTL,
        "deployment/hardware/z100_2026/window_mac_integration_v1/tb_z100_window_mac_integration.sv": TB,
        "tools/z100_feature_window_layout.py": LAYOUT_TOOL,
        "tools/prepare_z100_native_window_weights.py": CONVERTER,
        "tools/z100_requant_thresholds.py": REQUANT_TOOL,
        "tools/validate_z100_window_mac_integration.py": Path(__file__).resolve(),
        "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package/MODEL.V8P": MODEL_PACKAGE,
        "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package/v8_generated_model.h": MODEL_HEADER,
        "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/model/graph.json": MODEL_GRAPH,
        "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_nchw_int8.bin": INPUT,
        "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/result.json": HOST_PARITY,
        "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef/manifest.json": NATIVE_MANIFEST,
        "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef/weights_group4x32.bin": NATIVE_WEIGHTS,
        "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef/biases_int32x32.bin": NATIVE_BIASES,
        "validation/board_z100/native_window_weights/20261023T163945.127217Z_2b86c9ef/result.json": NATIVE_REPORT,
        "validation/board_z100/acceleration_resource_review/20261023T165119.142697Z/native_components_review.json": COMPONENT_REVIEW,
    }
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"Missing source-bound dependency: {path}")
    hashes = {name: sha256(path) for name, path in paths.items()}
    for name, expected in EXPECTED_HASHES.items():
        if hashes.get(name) != expected:
            raise ValueError(f"Pinned source/artifact hash differs for {name}")

    parity = json.loads(HOST_PARITY.read_text(encoding="utf-8"))
    if parity.get("status") != "PASS" or parity.get("physical_board_tested") is not False:
        raise ValueError("Accepted host-parity report is not the expected host-only pass")
    image = parity.get("image", {})
    if (image.get("quantized_nchw_input_path") != INPUT.name or
            image.get("quantized_nchw_input_sha256") != EXPECTED_HASHES[rel(INPUT)] or
            image.get("quantized_nchw_input_bytes") != 1_228_800):
        raise ValueError("Host-parity report does not bind the accepted NCHW input")

    native_report = json.loads(NATIVE_REPORT.read_text(encoding="utf-8"))
    if native_report.get("status") != "PASS_CURRENT_NATIVE_WEIGHT_PERMUTATION_HOST_ONLY":
        raise ValueError("Native-window converter report is not the expected host-only pass")
    native_artifacts = native_report.get("artifact_sha256", {})
    for name, expected in EXPECTED_HASHES.items():
        if name.startswith("deployment/build/z100_native_window_weights/") and native_artifacts.get(
                name.replace("/", "\\")) != expected:
            raise ValueError(f"Native converter report does not bind {name}")

    review = json.loads(COMPONENT_REVIEW.read_text(encoding="utf-8"))
    if (review.get("status") != "ROOT_REVIEW_ORIGINAL_COMPONENT_SCREEN_PASS_TIMING_UNACCEPTED" or
            review.get("protected_sources_verified") != 49 or
            review.get("production_integrated") is not False):
        raise ValueError("Pinned root component review differs from the bounded XSim context")
    return hashes, {"host_parity": parity, "native_weights": native_report,
                    "component_review": review}


def generate_fixture(build: Path, dependencies: dict) -> dict:
    input_data = INPUT.read_bytes()
    if len(input_data) != 3 * 640 * 640:
        raise ValueError(f"Expected 1,228,800 accepted NCHW bytes, got {len(input_data)}")

    # The feature loader uses one byte from each of64 banks per 512-bit word.
    tile_chw = b"".join(input_data[c * 640 * 640:c * 640 * 640 + 204 * 640]
                         for c in range(3))
    layout = FeatureLayout(3, 204, 640)
    packed_features = layout.pack(tile_chw)
    if layout.words != 8160 or len(packed_features) != 522_240:
        raise ValueError("Unexpected FeatureLayout(3,204,640) packing size")
    (build / "feature_words.hex").write_text(
        "".join(f"{int.from_bytes(packed_features[i:i + 64], 'little'):0128x}\n"
                for i in range(0, len(packed_features), 64)), encoding="ascii")
    (build / "integration_counts.svh").write_text(
        f"localparam integer LOAD_WORDS={layout.words};\n", encoding="ascii")

    native_manifest = json.loads(NATIVE_MANIFEST.read_text(encoding="utf-8"))
    if (native_manifest.get("schema") != "z100-native-window-weights/1" or
            native_manifest.get("source_package_sha256") != EXPECTED_HASHES[rel(MODEL_PACKAGE)] or
            native_manifest.get("groups_order") != ["input_channel_group4", "kernel_y", "kernel_x"] or
            native_manifest.get("group_byte_order") != ["input_channel_within_group4", "output_lane32"]):
        raise ValueError("Native-weight manifest does not match the frozen first-convolution stream")
    jobs = native_manifest.get("jobs", [])
    job = next((entry for entry in jobs if entry.get("node") == 0), None)
    if job != {
        "node": 0, "weight_epoch": 1, "output_channel_first": 0, "output_lanes": 16,
        "groups": 9, "weight_start_byte": 0, "weight_bytes": 1152,
        "bias_start_byte": 0, "bias_bytes": 128, "input_shape": [1, 3, 640, 640],
        "output_shape": [1, 16, 320, 320], "kernel": 3, "stride": 2, "padding": 1,
    }:
        raise ValueError("Native-weight manifest first-convolution job differs")

    native_weight_bytes = NATIVE_WEIGHTS.read_bytes()[job["weight_start_byte"]:
                                                     job["weight_start_byte"] + job["weight_bytes"]]
    native_bias_bytes = NATIVE_BIASES.read_bytes()[job["bias_start_byte"]:
                                                  job["bias_start_byte"] + job["bias_bytes"]]
    if len(native_weight_bytes) != 1152 or len(native_bias_bytes) != 128:
        raise ValueError("First-convolution native weight/bias segment has the wrong size")

    # The reference reads OIHW parameter bytes directly from the original
    # V8PK payload, never from the converter's reordered byte stream.
    package = MODEL_PACKAGE.read_bytes()
    if len(package) < 32 or package[:4] != b"V8PK":
        raise ValueError("Frozen model package header is invalid")
    magic, version, payload_size, crc, node_count, arena, classes, resolution = struct.unpack(
        "<4s7I", package[:32])
    payload = package[32:]
    if (magic, version, payload_size, node_count, classes, resolution) != (
            b"V8PK", 1, len(payload), 163, 9, 640):
        raise ValueError("Frozen model package metadata differs")
    import zlib
    if zlib.crc32(payload) != crc:
        raise ValueError("Frozen model payload CRC mismatch")
    header_text = MODEL_HEADER.read_text(encoding="utf-8")
    descriptors = re.findall(r"^\s*\{\.op=([^\n]+)", header_text, re.M)
    if len(descriptors) != 163:
        raise ValueError("Expected 163 frozen model header descriptors")
    first_conv = descriptors[0]
    weight_offset = parse_header_field(first_conv, "weight")
    bias_offset = parse_header_field(first_conv, "bias")
    if (parse_header_field(first_conv, "c"), parse_header_field(first_conv, "h"),
            parse_header_field(first_conv, "w"), parse_header_field(first_conv, "kernel"),
            parse_header_field(first_conv, "stride"), parse_header_field(first_conv, "padding")) != (
            16, 320, 320, 3, 2, 1):
        raise ValueError("Frozen original OIHW descriptor is not the expected first convolution")
    graph = json.loads(MODEL_GRAPH.read_text(encoding="utf-8"))
    graph_node = graph.get("nodes", [])[0]
    graph_params = graph_node.get("params", {})
    if (graph_node.get("id"), graph_node.get("op"), graph_node.get("shape"),
            graph_params.get("stride"), graph_params.get("padding"),
            graph_params.get("dilation"), graph_params.get("groups")) != (
            0, "conv", [1, 16, 320, 320], [2, 2], [1, 1], [1, 1], 1):
        raise ValueError("Frozen graph descriptor is not the expected first convolution")
    if weight_offset + 16*3*3*3 > len(payload) or bias_offset + 16*4 > len(payload):
        raise ValueError("Original OIHW parameters exceed the frozen package payload")

    valid_weight_bytes = 0
    padded_weight_bytes = 0
    for group in range(9):
        ky, kx = divmod(group, 3)
        for input_channel in range(4):
            for output_lane in range(32):
                packed_index = group*128 + input_channel*32 + output_lane
                output_channel = output_lane
                if input_channel < 3 and output_channel < 16:
                    original_index = weight_offset + (output_channel*3 + input_channel)*9 + ky*3 + kx
                    if native_weight_bytes[packed_index] != payload[original_index]:
                        raise ValueError("First-convolution converter byte differs from original OIHW")
                    valid_weight_bytes += 1
                else:
                    if native_weight_bytes[packed_index] != 0:
                        raise ValueError("First-convolution padded native weight is not zero")
                    padded_weight_bytes += 1
    for lane in range(32):
        expected_bias = payload[bias_offset + lane*4:bias_offset + (lane+1)*4] if lane < 16 else b"\0"*4
        if native_bias_bytes[lane*4:(lane+1)*4] != expected_bias:
            raise ValueError("First-convolution converter bias differs from original package")

    weights_hex = [native_weight_bytes[i:i+128] for i in range(0, len(native_weight_bytes), 128)]
    (build / "native_weight_groups.hex").write_text(
        "".join(f"{int.from_bytes(word, 'little'):0256x}\n" for word in weights_hex),
        encoding="ascii")
    (build / "native_bias.hex").write_text(
        f"{int.from_bytes(native_bias_bytes, 'little'):0256x}\n", encoding="ascii")

    expected_words = []
    oracle_raw_values = []
    overflow_count = 0
    for output_y, output_x in JOBS:
        sites = min(4, 320-output_x)
        for site in range(sites):
            packed_data = 0
            overflow_mask = 0
            for output_channel in range(32):
                if output_channel >= 16:
                    raw_sum = 0
                else:
                    raw_sum = signed32le(payload, bias_offset + output_channel*4)
                    for input_channel in range(3):
                        for ky in range(3):
                            for kx in range(3):
                                iy = output_y*2 + ky - 1
                                ix = (output_x+site)*2 + kx - 1
                                if 0 <= iy < 640 and 0 <= ix < 640:
                                    input_offset = input_channel*640*640 + iy*640 + ix
                                    activation = signed8(input_data[input_offset])
                                    original_weight_index = weight_offset + (
                                        (output_channel*3 + input_channel)*3 + ky)*3 + kx
                                    weight = signed8(payload[original_weight_index])
                                    raw_sum += activation*weight
                    if not -(1 << 32) <= raw_sum < (1 << 32):
                        raise ValueError("Original first-convolution sum exceeds signed 33-bit range")
                    oracle_raw_values.append(raw_sum)
                saturated = max(-(1 << 31), min((1 << 31)-1, raw_sum))
                if saturated != raw_sum:
                    overflow_mask |= 1 << output_channel
                    overflow_count += 1
                packed_data |= (saturated & 0xffffffff) << (output_channel*32)
            expected_words.append((packed_data << 32) | overflow_mask)
    if len(expected_words) != 22 or len(oracle_raw_values) != 352:
        raise ValueError("Expected 22 output sites and 352 direct OIHW lane sums")
    (build / "expected_raw_words.hex").write_text(
        "".join(f"{word:0264x}\n" for word in expected_words), encoding="ascii")

    return {
        "input_nchw_sha256": EXPECTED_HASHES[rel(INPUT)],
        "model_package_sha256": EXPECTED_HASHES[rel(MODEL_PACKAGE)],
        "header_sha256": EXPECTED_HASHES[rel(MODEL_HEADER)],
        "graph_sha256": EXPECTED_HASHES[rel(MODEL_GRAPH)],
        "feature_tile_chw_shape": [3, 204, 640],
        "feature_loader_words": layout.words,
        "feature_loader_bytes": len(packed_features),
        "feature_tile_rows": [0, 203],
        "native_weight_manifest_sha256": EXPECTED_HASHES[rel(NATIVE_MANIFEST)],
        "native_weight_group_count": len(weights_hex),
        "native_weight_bytes_checked_against_original_oihw": valid_weight_bytes,
        "native_padded_weight_bytes_checked_zero": padded_weight_bytes,
        "native_bias_bytes_checked_against_original_package": 16*4,
        "native_padded_bias_bytes_checked_zero": 16*4,
        "output_jobs": [{"oy": y, "ox": x, "sites": min(4, 320-x), "groups": 9}
                        for y, x in JOBS],
        "output_sites": len(expected_words),
        "raw_output_words": len(expected_words)*32,
        "valid_raw_lane_sums_from_direct_oihw": len(oracle_raw_values),
        "int32_overflow_flags_set": overflow_count,
        "reference": "signed64 direct NCHW x original V8PK OIHW+bias; signed33 range check; INT32 saturation/flags",
        "preloaded_im2col": False,
        "feature_and_weight_loads_resident_across_jobs": True,
    }


def main() -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/window_mac_integration_v1" / run_id
    build = ROOT / "deployment/build/z100_window_mac_integration_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)

    result: dict = {
        "status": "RUNNING",
        "run_id": run_id,
        "scope": "current-model native-window to MAC private integration; XSim only",
        "source_sha256": {},
        "source_snapshot": str((evidence / "source_snapshot").relative_to(ROOT)),
        "toolchain": {"vivado_bin": str(VIVADO_BIN), "python": str(PYTHON),
                      "max_threads": 2, "numerical_threads": 1},
        "input_geometry": {"channels": 3, "height": 640, "width": 640,
                           "first_convolution": {"outputs": 16, "kernel": 3, "stride": 2,
                                                  "padding": 1, "groups": 9}},
        "board_access": False,
        "route_attempted": False,
        "synthesis_attempted": False,
        "bitstream_created": False,
        "production_integrated": False,
        "commands": [],
    }
    try:
        source_hashes, dependencies = verify_source_bindings()
        source_hashes[rel(COMPONENT_REVIEW)] = sha256(COMPONENT_REVIEW)
        result["source_sha256"] = source_hashes
        snapshot = evidence / "source_snapshot"
        for name, path in {
            rel(BANK_RTL): BANK_RTL, rel(WINDOW_RTL): WINDOW_RTL, rel(MAC_RTL): MAC_RTL,
            rel(BRIDGE_RTL): BRIDGE_RTL, rel(TB): TB, rel(LAYOUT_TOOL): LAYOUT_TOOL,
            rel(CONVERTER): CONVERTER, rel(REQUANT_TOOL): REQUANT_TOOL,
            rel(Path(__file__).resolve()): Path(__file__).resolve(),
            rel(MODEL_PACKAGE): MODEL_PACKAGE, rel(MODEL_HEADER): MODEL_HEADER,
            rel(MODEL_GRAPH): MODEL_GRAPH, rel(INPUT): INPUT, rel(HOST_PARITY): HOST_PARITY,
            rel(NATIVE_WEIGHTS): NATIVE_WEIGHTS, rel(NATIVE_BIASES): NATIVE_BIASES,
            rel(NATIVE_MANIFEST): NATIVE_MANIFEST, rel(NATIVE_REPORT): NATIVE_REPORT,
            rel(COMPONENT_REVIEW): COMPONENT_REVIEW,
        }.items():
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        result["dependencies"] = {
            "host_parity_status": dependencies["host_parity"]["status"],
            "host_parity_report_sha256": sha256(HOST_PARITY),
            "native_weight_conversion_status": dependencies["native_weights"]["status"],
            "native_weight_conversion_report_sha256": sha256(NATIVE_REPORT),
            "component_review_status": dependencies["component_review"]["status"],
            "component_review_sha256": sha256(COMPONENT_REVIEW),
            "root_review_protected_source_count": dependencies["component_review"]["protected_sources_verified"],
            "current_rtl_sha256": {rel(BANK_RTL): sha256(BANK_RTL),
                                    rel(WINDOW_RTL): sha256(WINDOW_RTL),
                                    rel(MAC_RTL): sha256(MAC_RTL)},
        }
        result["reference"] = generate_fixture(build, dependencies)
        (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
            path = VIVADO_BIN / tool
            if not path.is_file():
                raise FileNotFoundError(f"Missing Vivado2026.1 XSim executable: {path}")
        for path in (BANK_RTL, WINDOW_RTL, MAC_RTL, BRIDGE_RTL, TB):
            if not path.is_file():
                raise FileNotFoundError(f"Missing simulation source: {path}")

        env = dict(os.environ)
        for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            env[key] = "1"
        compile_output = run_logged(
            "xvlog",
            [str(VIVADO_BIN / "xvlog.bat"), "-sv", str(BANK_RTL), str(WINDOW_RTL),
             str(MAC_RTL), str(BRIDGE_RTL), str(TB)], build, evidence, env, result)
        if "ERROR:" in compile_output or "Fatal:" in compile_output:
            raise ValueError("XSim compile reported an error despite its exit status")
        run_logged("xelab", [str(VIVADO_BIN / "xelab.bat"), "-mt", "2",
                             "tb_z100_window_mac_integration", "-s", "window_mac_integration_sim"],
                   build, evidence, env, result)
        simulation = run_logged(
            "xsim", [str(VIVADO_BIN / "xsim.bat"), "window_mac_integration_sim", "-runall"],
            build, evidence, env, result)
        match = re.findall(
            r"WINDOW_MAC_INTEGRATION_PASS jobs=(\d+) requests=(\d+) responses=(\d+) outputs=(\d+) "
            r"raw_words=(\d+) flags=(\d+) load_words=(\d+) weight_groups=(\d+) bias_loads=(\d+) "
            r"input_bubbles=(\d+) response_stalls=(\d+) output_stalls=(\d+) metadata=(\d+) residency=(\d+)",
            simulation)
        if len(match) != 1 or "Fatal:" in simulation or "FATAL:" in simulation:
            raise ValueError("XSim did not complete the integration coverage marker")
        keys = ("jobs", "requests", "responses", "outputs", "raw_words", "flags",
                "load_words", "weight_groups", "bias_loads", "input_bubbles",
                "response_stalls", "output_stalls", "metadata", "residency")
        counts = dict(zip(keys, map(int, match[0])))
        expected = {"jobs": 6, "requests": 54, "responses": 54, "outputs": 22,
                    "raw_words": 704, "flags": 704, "load_words": 8160,
                    "weight_groups": 9, "bias_loads": 1, "metadata": 22, "residency": 6}
        for key, value in expected.items():
            if counts[key] != value:
                raise ValueError(f"XSim coverage {key}={counts[key]}, expected {value}")
        for key in ("input_bubbles", "response_stalls", "output_stalls"):
            if counts[key] <= 0:
                raise ValueError(f"XSim omitted {key} coverage")
        result["simulation"] = {
            "status": "PASS",
            **counts,
            "checks": ["all 54 accepted feature descriptors and ordered response tags",
                       "all response masks, run tokens, and ninth-response last markers",
                       "all 704 raw output lanes and overflow flags against direct OIHW reference",
                       "all output token/site/lane/last metadata and stalled-output stability",
                       "response stability while the MAC is idle and backpressures the window",
                       "input bubbles and output stalls", "feature/weight load counts and epoch residency",
                       "job-to-job drain before next run"],
        }
        if source_hashes != {name: sha256(path) for name, path in {
                rel(BANK_RTL): BANK_RTL, rel(WINDOW_RTL): WINDOW_RTL, rel(MAC_RTL): MAC_RTL,
                rel(BRIDGE_RTL): BRIDGE_RTL, rel(TB): TB, rel(LAYOUT_TOOL): LAYOUT_TOOL,
                rel(CONVERTER): CONVERTER, rel(REQUANT_TOOL): REQUANT_TOOL,
                rel(Path(__file__).resolve()): Path(__file__).resolve(),
                rel(MODEL_PACKAGE): MODEL_PACKAGE, rel(MODEL_HEADER): MODEL_HEADER,
                rel(MODEL_GRAPH): MODEL_GRAPH, rel(INPUT): INPUT, rel(HOST_PARITY): HOST_PARITY,
                rel(NATIVE_MANIFEST): NATIVE_MANIFEST, rel(NATIVE_WEIGHTS): NATIVE_WEIGHTS,
                rel(NATIVE_BIASES): NATIVE_BIASES, rel(NATIVE_REPORT): NATIVE_REPORT,
                rel(COMPONENT_REVIEW): COMPONENT_REVIEW,
        }.items()}:
            raise ValueError("A source-bound dependency changed during the simulation")
        result["status"] = "PASS_PRIVATE_CURRENT_NATIVE_WINDOW_MAC_INTEGRATION_XSIM_ONLY"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"

    after = {}
    for name in result.get("source_sha256", {}):
        path = ROOT / name
        after[name] = sha256(path) if path.is_file() else "MISSING"
    result["source_sha256_after"] = after
    if result["status"].startswith("PASS_") and after != result["source_sha256"]:
        result["status"] = "FAILED_CLOSED"
        result["error"] = "A source-bound dependency changed during the simulation"
    result["artifact_sha256"] = {
        path.relative_to(ROOT).as_posix(): sha256(path)
        for folder in (evidence, build)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name not in {"result.json", "launch.json"}
    }
    report = evidence / "result.json"
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(report),
                      "error": result.get("error")}), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
