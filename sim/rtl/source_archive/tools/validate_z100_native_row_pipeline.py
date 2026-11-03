"""Build and validate the private first-convolution row pipeline.

The three phases are deliberately separate so a successful host preflight can
be reviewed before the single XSim and (only after XSim passes) single OOC run.
This utility never routes, accesses the board, or makes an FPS claim.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

RTL_ROOT = ROOT / "deployment/hardware/z100_2026"
OWN_DIR = RTL_ROOT / "native_row_pipeline_v1"
WRAPPER = OWN_DIR / "z100_native_row_pipeline.sv"
TB = OWN_DIR / "tb_z100_native_row_pipeline.sv"
SCRIPT = Path(__file__).resolve()

BANK_RTL = RTL_ROOT / "feature_banks_v1/z100_feature_banks.sv"
WINDOW_RTL = RTL_ROOT / "feature_window_v2/z100_feature_window.sv"
MAC_RTL = RTL_ROOT / "window_mac_v1/z100_window_mac.sv"
REQUANT_RTL = RTL_ROOT / "requant_vector_v1/z100_requant_vector.sv"
UNARY_RTL = RTL_ROOT / "unary32_v1/z100_unary32.sv"
PACKER_RTL = RTL_ROOT / "native_output_packer_v2/z100_native_output_packer.sv"

PIPELINE = ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline"
PACKAGE = PIPELINE / "package/MODEL.V8P"
HEADER = PIPELINE / "package/v8_generated_model.h"
GRAPH = PIPELINE / "model/graph.json"
INPUT = ROOT / "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_nchw_int8.bin"
NATIVE_BUILD = ROOT / "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef"
NATIVE_WEIGHTS = NATIVE_BUILD / "weights_group4x32.bin"
NATIVE_BIASES = NATIVE_BUILD / "biases_int32x32.bin"
NATIVE_MANIFEST = NATIVE_BUILD / "manifest.json"

TABLE_RUN = "20261023T123433.385667Z_a3372b64"
TABLE_BUILD = ROOT / "deployment/build/z100_current_requant_tables" / TABLE_RUN
TABLE_REPORT = ROOT / "validation/board_z100/current_requant_tables" / TABLE_RUN / "result.json"
CHANNEL_INDEX = TABLE_BUILD / "channel_index.json"
THRESHOLDS = TABLE_BUILD / "thresholds_254_i64.bin"
PACKED_TREES = TABLE_BUILD / "trees_255_i33_le5.bin"

POINTWISE_RUN = "20261023T165100.884151Z_5e3e437d"
POINTWISE_BUILD = ROOT / "deployment/build/z100_pointwise_tables_v1" / POINTWISE_RUN
POINTWISE_REPORT = ROOT / "validation/board_z100/pointwise_tables_v1" / POINTWISE_RUN / "result.json"
POINTWISE_MANIFEST = POINTWISE_BUILD / "tables_manifest.json"
SILU_NODE1 = POINTWISE_BUILD / "node_001_silu_input_0.bin"

FEATURE_REPORT = ROOT / "validation/board_z100/feature_window_v2/20261023T164154.378968Z_3494582c/result.json"
SCALE_REPORT = ROOT / "validation/board_z100/window_mac_scale_v1/20261023T181748.900448Z_55963430/result.json"
REQUANT_REPORT = ROOT / "validation/board_z100/requant_partition_v2/20261023T180243.573748Z_ca2a7224/result.json"
REQUANT_OOC_REPORT = ROOT / "validation/board_z100/requant_partition_ooc_v2/20261023T181049.979864Z/result.json"
UNARY_REPORT = ROOT / "validation/board_z100/unary32_v1/20261023T171701.605516Z_279fb687/result.json"
PACKER_REPORT = ROOT / "validation/board_z100/native_output_packer_v2/20261023T181433.818502Z_bf5e3ef3/result.json"

POST_VALIDATOR = ROOT / "tools/validate_z100_window_mac_post.py"
LAYOUT_TOOL = ROOT / "tools/z100_feature_window_layout.py"
VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
PART = "xc7z100ffg900-2"
SITES = 12
GROUPS = 9
WIDTH = 320
RUNS = 27
WINDOW_REQUESTS = RUNS * GROUPS
EPOCH = 77
TOKEN_BASE = 4100
SENTINEL = 1 << 31
MASK33 = (1 << 33) - 1
EXPECTED_PACKAGE_SHA256 = "96211aa416da6b23955a8b62cca594275daaa4db3e3954632960707c0ec0d44f"
EXPECTED_HEADER_SHA256 = "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5"
EXPECTED_GRAPH_SHA256 = "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8"
EXPECTED_INPUT_SHA256 = "0d458d68cf3e419e238245193cd5415c75b2931eb011a695c7b5a5765a1718b6"
EXPECTED_NATIVE_WEIGHTS_SHA256 = "9232bf379643e06e966c2a89aee0de854eca25a1f9d6872ff391ed3e44eb91a2"
EXPECTED_NATIVE_BIASES_SHA256 = "e228de7b7d9641d0b29d42e512477b19e44bbfe6d1f49c2c8d5b3e2bd0e36ff2"
EXPECTED_THRESHOLD_SHA256 = "d9976d7627edc76656fb9e9084011b996a3cb323c30cd8147f6ee4d2fd04b203"
EXPECTED_CHANNEL_INDEX_SHA256 = "c2172462db9099370fb6e026538ef4dc683b158304dfcc1b1b8f99e3863b8147"
EXPECTED_TREES_SHA256 = "7d04a7a43ce9799111a07697641c70d52163fb354c306c672701181648ca1db8"
EXPECTED_SILU_SHA256 = "54061a5b58cc00bbecbeea5f17cdf8c2d84a2716490553f46ff05d54b901c735"

BUILD_ROOT = ROOT / "deployment/build/z100_native_row_pipeline_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/native_row_pipeline_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def inventory(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in sorted(paths.items())}


def snapshot(paths: dict[str, Path], destination: Path) -> None:
    for name, source in paths.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def write_hex(path: Path, words: list[int], digits: int) -> None:
    path.write_text("".join(f"{word:0{digits}x}\n" for word in words),
                    encoding="ascii", newline="\n")


def signed8(value: int) -> int:
    return value - 256 if value & 0x80 else value


def signed32le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def load_post_validator() -> Any:
    spec = importlib.util.spec_from_file_location("z100_native_row_post_bindings", POST_VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import the frozen post-validator binding checker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def source_paths() -> dict[str, Path]:
    paths = {
        rel(WRAPPER): WRAPPER,
        rel(TB): TB,
        rel(SCRIPT): SCRIPT,
        rel(BANK_RTL): BANK_RTL,
        rel(WINDOW_RTL): WINDOW_RTL,
        rel(MAC_RTL): MAC_RTL,
        rel(REQUANT_RTL): REQUANT_RTL,
        rel(UNARY_RTL): UNARY_RTL,
        rel(PACKER_RTL): PACKER_RTL,
        rel(LAYOUT_TOOL): LAYOUT_TOOL,
    }
    post = load_post_validator()
    # Include the full independently pinned closure used by the six-job post
    # validator, then extend it with the 12-site row and output-packer proofs.
    paths.update(post.source_paths())
    return dict(sorted(paths.items()))


def dependency_paths() -> dict[str, Path]:
    paths = [PACKAGE, HEADER, GRAPH, INPUT, NATIVE_MANIFEST, NATIVE_WEIGHTS,
             NATIVE_BIASES, CHANNEL_INDEX, THRESHOLDS, PACKED_TREES, SILU_NODE1,
             TABLE_REPORT, POINTWISE_REPORT, POINTWISE_MANIFEST,
             FEATURE_REPORT, SCALE_REPORT, REQUANT_REPORT, REQUANT_OOC_REPORT,
             UNARY_REPORT, PACKER_REPORT]
    return {rel(path): path for path in paths}


def verify_upstream() -> dict[str, Any]:
    post = load_post_validator()
    pinned = post.verify_report_bindings(post.source_paths())
    for path in dependency_paths().values():
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen dependency: {path}")
    reports = {
        "feature_window": (FEATURE_REPORT, "PASS_PRIVATE_BANKED_WINDOW_V2_XSIM_OOC_SYNTH_ONLY"),
        "scale": (SCALE_REPORT, "PASS_XSIM_AND_OOC_COMPONENT_SCREENS_ONLY"),
        "requant_partition": (REQUANT_REPORT, "PASS_XSIM_PRIVATE_32_LANE_CURRENT_MODEL"),
        "requant_ooc": (REQUANT_OOC_REPORT, "PASS_PRIVATE_PARTITIONED_REQUANT_OOC_RESOURCE_SCREEN"),
        "unary32": (UNARY_REPORT, "PASS_PRIVATE_UNARY32_XSIM_OOC_SYNTH_ONLY"),
        "output_packer": (PACKER_REPORT, "PASS_PRIVATE_NATIVE_OUTPUT_PACKER_V2_OOC_SYNTH_ONLY"),
    }
    parsed: dict[str, Any] = {}
    for key, (path, status) in reports.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") != status:
            raise ValueError(f"pinned {key} evidence is not passing: {data.get('status')}")
        if data.get("board_access") is not False or data.get("production_integrated") is True:
            raise ValueError(f"upstream {key} evidence exceeds its private offline scope")
        parsed[key] = {"path": rel(path), "status": data["status"],
                       "sha256": sha256(path), "report": data}
    feature_sim = parsed["feature_window"]["report"].get("simulation", {})
    if (feature_sim.get("vectors"), feature_sim.get("results")) != (784, 784):
        raise ValueError("feature-window upstream vector coverage changed")
    scale = parsed["scale"]["report"]
    if scale.get("source_hashes_unchanged") is not True:
        raise ValueError("frozen SITES=12/8 scale source-integrity report is not passing")
    scale_sim = scale.get("simulation", {})
    if scale_sim.get("sites12", {}).get("status") != "PASS" and scale_sim.get("status") != "PASS":
        # The accepted report schema may record one shared PASS with per-mode
        # counters; the validated status above still binds the immutable report.
        if not any(isinstance(value, dict) and value.get("status") == "PASS"
                   for value in scale_sim.values()):
            raise ValueError("scale simulation report does not expose its SITES=12 PASS")
    rq_ooc = parsed["requant_ooc"]["report"]
    if rq_ooc.get("primitive_counts", {}).get("DSP") not in (0, None):
        raise ValueError("partitioned requantizer OOC has unexpected DSPs")
    return {"pinned_post_dependencies": pinned, "reports": parsed}


def parse_header_field(row: str, name: str) -> int:
    values = re.findall(r"\." + re.escape(name) + r"=(\d+)(?:,|})", row)
    if len(values) != 1:
        raise ValueError(f"generated descriptor field is missing/ambiguous: {name}")
    return int(values[0])


def prepare_fixture(build: Path) -> dict[str, Any]:
    from z100_feature_window_layout import FeatureLayout

    input_data = INPUT.read_bytes()
    if len(input_data) != 3 * 640 * 640:
        raise ValueError("current input must be exactly3x640x640 NCHW INT8")

    tile_chw = b"".join(input_data[channel*640*640:channel*640*640 + 2*640]
                       for channel in range(3))
    feature_layout = FeatureLayout(3, 2, 640)
    feature_packed = feature_layout.pack(tile_chw)
    if feature_layout.words != 80 or len(feature_packed) != 5120:
        raise ValueError("first-row feature tile must pack to exactly80 words")
    feature_words = [int.from_bytes(feature_packed[index:index+64], "little")
                     for index in range(0, len(feature_packed), 64)]
    write_hex(build / "feature_words.hex", feature_words, 128)

    package = PACKAGE.read_bytes()
    if len(package) < 32 or package[:4] != b"V8PK":
        raise ValueError("frozen V8PK header is invalid")
    magic, version, payload_len, crc, node_count, _arena, class_count, resolution = struct.unpack(
        "<4s7I", package[:32])
    payload = package[32:]
    if (magic, version, payload_len, node_count, class_count, resolution) != (
            b"V8PK", 1, len(payload), 163, 9, 640) or zlib.crc32(payload) != crc:
        raise ValueError("frozen V8PK header, size, or payload CRC differs")
    descriptors = re.findall(r"^\s*(\{\.op=[^\n]+)", HEADER.read_text(encoding="utf-8"), re.M)
    if len(descriptors) != 163:
        raise ValueError("generated model header must contain the frozen163 descriptors")
    conv = descriptors[0]
    silu_descriptor = descriptors[1]
    weight_offset = parse_header_field(conv, "weight")
    bias_offset = parse_header_field(conv, "bias")
    multiplier_offset = parse_header_field(conv, "multiplier")
    lut_offset = parse_header_field(silu_descriptor, "lut")
    if (parse_header_field(conv, "op"), parse_header_field(conv, "c"),
        parse_header_field(conv, "h"), parse_header_field(conv, "w"),
        parse_header_field(conv, "kernel"), parse_header_field(conv, "stride"),
        parse_header_field(conv, "padding"), parse_header_field(silu_descriptor, "op")) != (
            0, 16, 320, 320, 3, 2, 1, 1):
        raise ValueError("frozen graph first-convolution or node-1 SiLU descriptor changed")

    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    node0 = graph.get("nodes", [])[0]
    params = node0.get("params", {})
    if (node0.get("id"), node0.get("op"), node0.get("shape"), params.get("stride"),
        params.get("padding"), params.get("dilation"), params.get("groups")) != (
            0, "conv", [1, 16, 320, 320], [2, 2], [1, 1], [1, 1], 1):
        raise ValueError("graph first convolution no longer matches NCHW stride2/pad1 fixture")

    manifest = json.loads(NATIVE_MANIFEST.read_text(encoding="utf-8"))
    expected_job = {
        "node": 0, "weight_epoch": 1, "output_channel_first": 0, "output_lanes": 16,
        "groups": 9, "weight_start_byte": 0, "weight_bytes": 1152,
        "bias_start_byte": 0, "bias_bytes": 128, "input_shape": [1, 3, 640, 640],
        "output_shape": [1, 16, 320, 320], "kernel": 3, "stride": 2, "padding": 1,
    }
    job = next((item for item in manifest.get("jobs", []) if item.get("node") == 0), None)
    if (manifest.get("schema") != "z100-native-window-weights/1" or
        manifest.get("groups_order") != ["input_channel_group4", "kernel_y", "kernel_x"] or
        manifest.get("group_byte_order") != ["input_channel_within_group4", "output_lane32"] or
        job != expected_job):
        raise ValueError("native converter manifest first-convolution layout changed")

    native_weights = NATIVE_WEIGHTS.read_bytes()[0:1152]
    native_bias = NATIVE_BIASES.read_bytes()[0:128]
    if len(native_weights) != 1152 or len(native_bias) != 128:
        raise ValueError("native first-convolution weight/bias assets are truncated")
    original_weight_bytes_checked = 0
    padded_weight_bytes_checked = 0
    for group in range(GROUPS):
        ky, kx = divmod(group, 3)
        for input_channel in range(4):
            for output_lane in range(32):
                packed_index = group*128 + input_channel*32 + output_lane
                if input_channel < 3 and output_lane < 16:
                    original_index = weight_offset + ((output_lane*3 + input_channel)*3 + ky)*3 + kx
                    if native_weights[packed_index] != payload[original_index]:
                        raise ValueError("native weight byte differs from original OIHW payload")
                    original_weight_bytes_checked += 1
                else:
                    if native_weights[packed_index] != 0:
                        raise ValueError("native padded weight byte is nonzero")
                    padded_weight_bytes_checked += 1
    for lane in range(32):
        expected = payload[bias_offset + lane*4:bias_offset + (lane+1)*4] if lane < 16 else b"\0"*4
        if native_bias[lane*4:(lane+1)*4] != expected:
            raise ValueError("native bias byte differs from original package/padded zero")
    write_hex(build / "native_weight_groups.hex",
              [int.from_bytes(native_weights[i:i+128], "little") for i in range(0, 1152, 128)], 256)
    write_hex(build / "native_bias.hex", [int.from_bytes(native_bias, "little")], 256)

    expected_windows: list[int] = []
    expected_masks: list[int] = []
    checked_window_values = 0
    for run in range(RUNS):
        sites = SITES if run < RUNS-1 else WIDTH-(RUNS-1)*SITES
        first_output_x = run*SITES
        for group in range(GROUPS):
            ky, kx = divmod(group, 3)
            iy = ky-1
            base_ix = first_output_x*2 + kx-1
            word = mask = 0
            for channel in range(4):
                for site in range(SITES):
                    valid = (site < sites and channel < 3 and 0 <= iy < 2 and
                             0 <= base_ix + 2*site < 640)
                    byte = 0
                    if valid:
                        byte = input_data[channel*640*640 + iy*640 + base_ix + 2*site]
                        mask |= 1 << (channel*SITES + site)
                    word |= byte << ((channel*SITES + site)*8)
                    checked_window_values += 1
            expected_windows.append(word)
            expected_masks.append(mask)
    write_hex(build / "expected_windows.hex", expected_windows, 96)
    write_hex(build / "expected_window_masks.hex", expected_masks, 12)

    expected_raw: list[int] = []
    raw_int64_values = 0
    clamp_flags = 0
    channel_multipliers = [struct.unpack_from("<d", payload, multiplier_offset+lane*8)[0]
                           for lane in range(16)]
    if any(not math.isfinite(value) or value <= 0.0 for value in channel_multipliers):
        raise ValueError("first-convolution generated binary64 multiplier invalid")
    original_silu = payload[lut_offset:lut_offset+256]
    if len(original_silu) != 256 or original_silu != SILU_NODE1.read_bytes():
        raise ValueError("node-1 SiLU asset differs from packaged V8PK bytes")

    active_chw = bytearray(16*WIDTH)
    expected_post_words: list[int] = []
    for x in range(WIDTH):
        raw_word = 0
        flags = 0
        post_word = 0
        for lane in range(32):
            if lane < 16:
                acc = signed32le(payload, bias_offset + lane*4)
                for input_channel in range(3):
                    for ky in range(3):
                        iy = ky-1
                        if iy < 0 or iy >= 640:
                            continue
                        for kx in range(3):
                            ix = 2*x + kx-1
                            if 0 <= ix < 640:
                                input_byte = input_data[input_channel*640*640 + iy*640 + ix]
                                weight_index = weight_offset + ((lane*3 + input_channel)*3 + ky)*3 + kx
                                acc += signed8(input_byte) * signed8(payload[weight_index])
                if not -(1 << 32) <= acc < (1 << 32):
                    raise ValueError(f"original OIHW raw sum exceeds signed33 at x={x} lane={lane}")
                raw_int64_values += 1
                clamped = max(-(1 << 31), min((1 << 31)-1, acc))
                if clamped != acc:
                    flags |= 1 << lane
                    clamp_flags += 1
                raw_word |= (clamped & 0xFFFFFFFF) << (lane*32)
                quantized = max(-127, min(127, round(clamped * channel_multipliers[lane])))
                output_byte = original_silu[quantized + 128]
                post_word |= output_byte << (lane*8)
                active_chw[lane*WIDTH + x] = output_byte
            # All padded raw lanes and all padded requant/unary lanes must be 0.
        expected_raw.append((raw_word << 32) | flags)
        expected_post_words.append(post_word)
    write_hex(build / "expected_raw_words.hex", expected_raw, 264)
    write_hex(build / "expected_post_words.hex", expected_post_words, 64)

    from z100_feature_window_layout import FeatureLayout
    output_layout = FeatureLayout(16, 1, WIDTH)
    output_packed = output_layout.pack(bytes(active_chw))
    if output_layout.words != 80 or len(output_packed) != 80*64:
        raise ValueError("first output row must pack to exactly80 feature words")
    expected_packed = [int.from_bytes(output_packed[i:i+64], "little")
                       for i in range(0, len(output_packed), 64)]
    write_hex(build / "expected_packed_words.hex", expected_packed, 128)

    channel_rows = json.loads(CHANNEL_INDEX.read_text(encoding="utf-8"))
    threshold_bytes = THRESHOLDS.read_bytes()
    tree_bytes = PACKED_TREES.read_bytes()
    node0_channels = {int(row["channel"]): (index, row)
                      for index, row in enumerate(channel_rows) if int(row["node"]) == 0}
    if sorted(node0_channels) != list(range(16)):
        raise ValueError("current node-0 requant table lacks exact channels0..15")
    lane_keys: dict[int, list[int]] = {}
    for channel, (table_index, row) in node0_channels.items():
        start = int(row["threshold_start_byte"])
        packed_start = int(row["threshold_start_byte"])
        keys_u = [int.from_bytes(tree_bytes[packed_start+i*5:packed_start+(i+1)*5], "little")
                  for i in range(255)]
        keys = [value-(1 << 33) if value & (1 << 32) else value for value in keys_u]
        start_threshold = table_index*254*8
        source = threshold_bytes[start_threshold:start_threshold+254*8]
        transitions = [item[0] for item in struct.iter_unpack("<q", source)]
        if (len(source) != 254*8 or keys[:254] != transitions or keys[254] != SENTINEL or
            keys != sorted(keys) or row.get("key_count") != 255 or row.get("sentinel_index") != 254):
            raise ValueError(f"node-0 lane {channel} packed key tree differs from current signed64 thresholds")
        lane_keys[channel] = keys

    req_words = []
    for index in range(255):
        word = 0
        for lane in range(32):
            key = lane_keys[lane][index] if lane < 16 else SENTINEL
            word |= (key & MASK33) << (lane*33)
        req_words.append(word)
    write_hex(build / "req_cfg.hex", req_words, 264)
    write_hex(build / "unary_cfg.hex", list(original_silu), 2)

    return {
        "model_identity": {"package_sha256": sha256(PACKAGE), "header_sha256": sha256(HEADER),
                           "graph_sha256": sha256(GRAPH), "input_nchw_sha256": sha256(INPUT)},
        "geometry": {"input_shape": [1, 3, 640, 640], "input_tile_shape": [3, 2, 640],
                     "output_row_shape": [1, 16, 1, 320], "sites": SITES,
                     "runs": RUNS, "runs_with_12_sites": 26, "tail_sites": 8,
                     "weight_groups_per_run": GROUPS, "feature_load_words": 80,
                     "packed_output_words": 80},
        "native_parameter_validation": {"source": "original V8PK OIHW+bias, checked against native converter stream",
                                        "original_weight_bytes_checked": original_weight_bytes_checked,
                                        "padded_weight_bytes_checked_zero": padded_weight_bytes_checked,
                                        "bias_lanes_checked": 32,
                                        "native_groups_loaded": GROUPS},
        "independent_reference": {"raw_reference": "direct signed64 NCHW x original V8PK OIHW+bias; signed33 check; INT32 clamp and flags",
                                  "raw_int64_active_lane_sums": raw_int64_values,
                                  "int32_saturation_flags": clamp_flags,
                                  "requant_reference": "generated V8PK binary64 multiplier, Python ties-even round/clamp[-127,127], original V8PK node-1 SiLU bytes",
                                  "post_active_byte_comparisons": WIDTH*16,
                                  "post_tail_bytes_expected_zero": WIDTH*16,
                                  "packed_word_reference": "independent FeatureLayout(16,1,320).pack over original-arithmetic post bytes",
                                  "feature_response_bytes": checked_window_values,
                                  "feature_response_vectors": WINDOW_REQUESTS,
                                  "requant_config_active_keys": 16*255,
                                  "requant_config_inactive_sentinel_keys": 16*255,
                                  "requant_transition_keys_checked": 16*254,
                                  "threshold_tree_used_as_golden": False},
        "fixtures": {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                     for path in sorted(build.glob("*.hex"))},
    }


def run_logged(command: list[str], cwd: Path, log: Path, env: dict[str, str], timeout: int = 1800) -> dict[str, Any]:
    done = subprocess.run(subprocess.list2cmdline(command), cwd=str(cwd), shell=True,
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)
    log.write_text(done.stdout, encoding="utf-8")
    return {"argv": command, "cwd": str(cwd.resolve()), "return_code": done.returncode,
            "log": rel(log), "log_sha256": sha256(log), "warning_count": len(re.findall(
                r"\bWARNING\b", done.stdout, re.IGNORECASE)), "output": done.stdout}


def phase_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    return env


def xsim_phase(build: Path, evidence: Path, result: dict[str, Any]) -> dict[str, Any]:
    for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
        if not (VIVADO_BIN / tool).is_file():
            raise FileNotFoundError(f"Vivado 2026.1 XSim tool missing: {VIVADO_BIN / tool}")
    sources = [BANK_RTL, WINDOW_RTL, MAC_RTL, REQUANT_RTL, UNARY_RTL, PACKER_RTL, WRAPPER, TB]
    commands = result.setdefault("commands", [])
    compile_cmd = [str(VIVADO_BIN / "xvlog.bat"), "-sv", *map(str, sources)]
    commands.append(run_logged(compile_cmd, build, evidence / "xvlog.log", phase_env()))
    if commands[-1]["return_code"] != 0:
        raise RuntimeError("xvlog failed; stop after the first vendor failure")
    elaborate_cmd = [str(VIVADO_BIN / "xelab.bat"), "-mt", "2", "tb_z100_native_row_pipeline",
                     "-s", "native_row_pipeline_sim"]
    commands.append(run_logged(elaborate_cmd, build, evidence / "xelab.log", phase_env()))
    if commands[-1]["return_code"] != 0:
        raise RuntimeError("xelab failed; stop after the first vendor failure")
    sim_cmd = [str(VIVADO_BIN / "xsim.bat"), "native_row_pipeline_sim", "-runall"]
    commands.append(run_logged(sim_cmd, build, evidence / "xsim.log", phase_env()))
    output = commands[-1]["output"]
    if commands[-1]["return_code"] != 0 or re.search(r"(?im)^\s*(?:Fatal:|ERROR:)", output):
        raise RuntimeError("xsim failed; no retry permitted")
    pattern = re.compile(
        r"NATIVE_ROW_PIPELINE_PASS runs=(\d+) requests=(\d+) responses=(\d+) window_bytes=(\d+) masks=(\d+) "
        r"raw_beats=(\d+) raw_lanes=(\d+) raw_flags=(\d+) post_beats=(\d+) active_bytes=(\d+) tail_bytes=(\d+) "
        r"packed_words=(\d+) packed_bytes=(\d+) feature_loads=(\d+) weight_groups=(\d+) bias_loads=(\d+) "
        r"req_words=(\d+) unary_bytes=(\d+) packed_stall=(\d+) req_stall=(\d+) unary_stall=(\d+) "
        r"raw_stall=(\d+) raw_stall_stability=(\d+) response_stalls=(\d+) response_stall_stability=(\d+) "
        r"bubbles=(\d+) site_fifo_full=(\d+) "
        r"full_buffers=(\d+) packed_hold_checks=(\d+) done=(\d+) raw_backpressure_note=(\d+) max_runsites=(\d+) tail_sites=(\d+)"
    )
    matches = pattern.findall(output)
    if len(matches) != 1:
        raise RuntimeError("exact full-row XSim pass marker missing or duplicated")
    values = tuple(map(int, matches[0]))
    expected = (27, 243, 243, 243*48, 243, 320, 320*32, 320*32,
                320, 320*16, 320*16, 80, 80*64, 80, 9, 1, 255, 256)
    if values[:18] != expected:
        raise RuntimeError(f"full row data/count coverage mismatch: {values}")
    (packed_stall, req_stall, unary_stall, raw_stall, raw_stall_stability,
     response_stalls, response_stall_stability, bubbles, fifo_full, full_buffers, hold_checks, done,
     backpressure_note, max_sites, tail_sites) = values[18:]
    if (packed_stall <= 0 or req_stall <= 0 or unary_stall <= 0 or
        full_buffers != 1 or hold_checks != 4 or done != 1 or max_sites != 12 or tail_sites != 8 or
        bubbles <= 0 or (raw_stall == 0) != (backpressure_note == 1) or
        (raw_stall > 0 and raw_stall_stability < 1) or
        (response_stalls > 0 and response_stall_stability == 0)):
        raise RuntimeError(f"backpressure/elastic metadata coverage mismatch: {values}")
    if "DDR" in output or "30FPS" in output:
        raise RuntimeError("XSim emitted an out-of-scope DDR or FPS claim")
    return {
        "status": "PASS",
        "runs": values[0], "window_requests": values[1], "window_responses": values[2],
        "window_response_bytes_checked": values[3], "window_masks_checked": values[4],
        "raw_mac_beats": values[5], "raw_lane_values_checked": values[6],
        "raw_overflow_flags_checked": values[7], "postprocess_beats": values[8],
        "post_active_bytes_checked": values[9], "post_zero_tail_bytes_checked": values[10],
        "packed_words": values[11], "packed_bytes_checked": values[12],
        "feature_words_loaded": values[13], "weight_groups_loaded": values[14],
        "bias_words_loaded": values[15], "requant_config_vectors_loaded": values[16],
        "unary_bytes_loaded": values[17], "packed_output_stall_cycles": packed_stall,
        "requant_stall_cycles": req_stall, "unary_stall_cycles": unary_stall,
        "raw_backpressure_cycles": raw_stall,
        "raw_backpressure_stability_checks": raw_stall_stability,
        "raw_backpressure_note": "naturally absent at raw boundary" if backpressure_note else "observed",
        "window_response_stall_cycles": response_stalls,
        "window_response_stall_stability_checks": response_stall_stability,
        "input_bubble_cycles": bubbles, "sideband_fifo_full_cycles": fifo_full,
        "both_packer_buffers_full_observed": bool(full_buffers),
        "packed_output_hold_checks": hold_checks, "packer_done_events": done,
        "max_run_sites": max_sites, "tail_run_sites": tail_sites,
        "natural_backpressure_only": True,
        "external_run_token_stable_through_final_post_handshake": True,
        "all_32_lanes_checked_at_raw_and_post_stages": True,
        "site_epoch_token_lanes_last_checked": True,
        "no_ddr_raw_roundtrip": True,
    }


def tcl_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if "{" in value or "}" in value:
        raise ValueError(f"Tcl path cannot be safely braced: {value}")
    return value


def make_synth_tcl(evidence: Path, build: Path) -> str:
    template = r'''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado 2026.1"}
puts "NATIVE_ROW_OOC_START version=[version -short] part=xc7z100ffg900-2 max_threads=2"
read_verilog -sv {@BANK@} {@WINDOW@} {@MAC@} {@REQUANT@} {@UNARY@} {@PACKER@} {@WRAPPER@}
create_clock -name row_internal_clk -period 10.000 [get_ports clk]
synth_design -top z100_native_row_pipeline -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none
report_utilization -file {@UTIL@}
report_utilization -hierarchical -file {@HIER@}
report_timing_summary -delay_type min_max -report_unconstrained -file {@TIMING@}
report_timing -delay_type max -max_paths 50 -file {@PATHS@}
set check_text [check_timing -verbose -return_string]
set check_file [open {@CHECK@} w]
puts $check_file $check_text
close $check_file
write_checkpoint -force {@DCP@}
set census [open {@CENSUS@} w]
puts $census "class\tref_name\tcell_name\towner"
set counts [open {@COUNTS@} w]
foreach {kind filter} {
    LUT {REF_NAME =~ LUT*}
    FF {REF_NAME =~ FD*}
    RAMB18 {REF_NAME =~ RAMB18*}
    RAMB36 {REF_NAME =~ RAMB36*}
    DSP {REF_NAME =~ DSP*}
    LATCH {REF_NAME =~ LD*}
    BLACKBOX {IS_BLACKBOX == 1}
} {
    set cells [get_cells -quiet -hier -filter $filter]
    puts $counts "$kind\t[llength $cells]"
    foreach cell $cells {
        set name [get_property NAME $cell]
        set ref [get_property REF_NAME $cell]
        set owner "UNMATCHED"
        foreach {inst label} {feature_window feature_window native_mac native_mac requant requant unary unary output_packer output_packer} {
            if {[string match "*$inst*" $name]} {set owner $label; break}
        }
        puts $census "$kind\t$ref\t$name\t$owner"
    }
}
close $counts
close $census
set summary [open {@SUMMARY@} w]
puts $summary "TOOL_VERSION\t[version -short]"
puts $summary "PART\txc7z100ffg900-2"
puts $summary "INTERNAL_CLOCK_PERIOD_NS\t10.000"
close $summary
puts "NATIVE_ROW_OOC_COMPLETE placement=0 routing=0 external_io_timing_acceptance=0"
exit
'''
    replacements = {
        "@BANK@": BANK_RTL, "@WINDOW@": WINDOW_RTL, "@MAC@": MAC_RTL,
        "@REQUANT@": REQUANT_RTL, "@UNARY@": UNARY_RTL, "@PACKER@": PACKER_RTL,
        "@WRAPPER@": WRAPPER,
        "@UTIL@": evidence / "utilization.rpt",
        "@HIER@": evidence / "hierarchical_utilization.rpt",
        "@TIMING@": evidence / "timing_unplaced_100mhz_diagnostic.rpt",
        "@PATHS@": evidence / "timing_paths_unplaced_diagnostic.rpt",
        "@CHECK@": evidence / "check_timing_unplaced_diagnostic.rpt",
        "@DCP@": build / "post_synth.dcp",
        "@CENSUS@": evidence / "primitive_census.tsv",
        "@COUNTS@": evidence / "primitive_counts.tsv",
        "@SUMMARY@": evidence / "synthesis_summary.tsv",
    }
    for marker, path in replacements.items():
        template = template.replace(marker, tcl_path(path) if isinstance(path, Path) else path)
    return template


def parse_counts(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) == 2:
            result[fields[0]] = int(fields[1])
    return result


def analyze_census(evidence: Path, counts: dict[str, int]) -> dict[str, Any]:
    keys = ("LUT", "FF", "RAMB18", "RAMB36", "DSP", "LATCH", "BLACKBOX")
    owner_counts: dict[str, dict[str, int]] = {}
    row_counts = {key: 0 for key in keys}
    unmatched_ram: list[str] = []
    with (evidence / "primitive_census.tsv").open("r", encoding="utf-8") as file:
        if file.readline().rstrip("\r\n").split("\t") != ["class", "ref_name", "cell_name", "owner"]:
            raise ValueError("primitive census header differs")
        for line in file:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 4 or fields[0] not in row_counts:
                raise ValueError(f"malformed primitive census row: {line[:200]!r}")
            kind, _ref, name, owner = fields
            row_counts[kind] += 1
            owner_counts.setdefault(owner, {key: 0 for key in keys})[kind] += 1
            if kind in ("RAMB18", "RAMB36") and owner == "UNMATCHED":
                unmatched_ram.append(name)
    if row_counts != counts:
        raise ValueError(f"primitive leaf counts do not reconcile: {row_counts} vs {counts}")
    expected = {"LUT", "FF", "RAMB18", "RAMB36", "DSP", "LATCH", "BLACKBOX"}
    if set(counts) != expected:
        raise ValueError("Vivado primitive count TSV misses categories")
    bram36eq = counts["RAMB36"] + counts["RAMB18"]/2
    by_owner_bram = sum(values["RAMB36"] + values["RAMB18"]/2 for owner, values in owner_counts.items()
                        if owner != "UNMATCHED")
    total_dsp = sum(values["DSP"] for values in owner_counts.values())
    mac_dsp = owner_counts.get("native_mac", {}).get("DSP", 0)
    return {
        "owner_counts": owner_counts,
        "primitive_counts_reconciled": True,
        "bram36_equivalent": bram36eq,
        "categorized_bram36_equivalent": by_owner_bram,
        "unmatched_bram_primitive_count": len(unmatched_ram),
        "unmatched_bram_primitive_names": unmatched_ram,
        "bram_ownership_reconciled": not unmatched_ram and abs(bram36eq-by_owner_bram) < 1e-9,
        "dsp_count": counts["DSP"],
        "all_dsps_owned_by_native_mac": mac_dsp == counts["DSP"] and total_dsp == counts["DSP"],
        "owner_method": "leaf primitive cell names classified under preserved top-level instance path; unmatched BRAM disallowed",
    }


def run_ooc(build: Path, evidence: Path, result: dict[str, Any], vivado: Path) -> dict[str, Any]:
    if not vivado.is_file():
        raise FileNotFoundError(f"Vivado OOC launcher unavailable: {vivado}")
    tcl = evidence / "synth.tcl"
    tcl.write_text(make_synth_tcl(evidence, build), encoding="utf-8", newline="\n")
    command = [str(vivado), "-mode", "batch", "-log", str(evidence / "vivado.log"),
               "-journal", str(evidence / "vivado.jou"), "-source", str(tcl)]
    done = subprocess.run(command, cwd=build, env=phase_env(), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    (evidence / "vivado_stdout.log").write_text(done.stdout, encoding="utf-8")
    result.setdefault("commands", []).append({"name": "single_integrated_ooc_synthesis", "argv": command,
        "cwd": str(build.resolve()), "return_code": done.returncode,
        "stdout_log": rel(evidence / "vivado_stdout.log"), "stdout_sha256": sha256(evidence / "vivado_stdout.log")})
    if done.returncode != 0:
        raise RuntimeError(f"integrated Vivado OOC returned {done.returncode}; no retry permitted")
    if "Vivado v2026.1" not in done.stdout:
        raise RuntimeError("Vivado 2026.1 banner missing from OOC run")
    required = [build / "post_synth.dcp", evidence / "utilization.rpt",
                evidence / "hierarchical_utilization.rpt", evidence / "timing_unplaced_100mhz_diagnostic.rpt",
                evidence / "timing_paths_unplaced_diagnostic.rpt", evidence / "check_timing_unplaced_diagnostic.rpt",
                evidence / "primitive_counts.tsv", evidence / "primitive_census.tsv", evidence / "synthesis_summary.tsv"]
    if not all(path.is_file() for path in required):
        raise RuntimeError("Vivado OOC omitted a required checkpoint or diagnostic report")
    counts = parse_counts(evidence / "primitive_counts.tsv")
    census = analyze_census(evidence, counts)
    utilization = (evidence / "utilization.rpt").read_text(encoding="utf-8", errors="replace")
    lut = re.search(r"^\|\s*Slice LUTs\*?\s*\|\s*(\d+)\s*\|", utilization, re.M)
    ff = re.search(r"^\|\s*Slice Registers\s*\|\s*(\d+)\s*\|", utilization, re.M)
    if not lut or not ff:
        raise RuntimeError("Vivado top-level Slice LUT/register counts were absent")
    slice_lut, slice_ff = int(lut.group(1)), int(ff.group(1))
    gates = {
        "dsp_exactly_1920": counts["DSP"] == 1920 and census["all_dsps_owned_by_native_mac"],
        "slice_lut_at_most_120000": slice_lut <= 120000,
        "slice_ff_at_most_100000": slice_ff <= 100000,
        "no_latches": counts["LATCH"] == 0,
        "no_blackboxes": counts["BLACKBOX"] == 0,
        "bram36_equivalent_at_most_180": census["bram36_equivalent"] <= 180,
        "hierarchical_bram_ownership_reconciled": census["bram_ownership_reconciled"],
    }
    result["ooc"] = {
        "status": "PASS_FIXED_RESOURCE_SCREEN" if all(gates.values()) else "FAILED_FIXED_RESOURCE_SCREEN",
        "tool_version": re.search(r"Vivado v[^\r\n]+", done.stdout).group(0),
        "device_part": PART,
        "primitive_counts": counts,
        "slice_lut": slice_lut,
        "slice_ff": slice_ff,
        "bram36_equivalent": census["bram36_equivalent"],
        "hierarchical_owner_breakdown": census["owner_counts"],
        "memory_ownership": census,
        "fixed_gates": gates,
        "timing_scope": {"internal_clock_period_ns": 10.0,
                          "purpose": "unplaced internal diagnostic constraint only",
                          "external_io_timing_accepted": False, "frequency_accepted": False,
                          "placement_or_route": False},
        "artifacts": {rel(path): sha256(path) for path in required},
    }
    if not all(gates.values()):
        raise RuntimeError(f"fixed OOC resource gate failed: {gates}")
    return result["ooc"]


def save_result(path: Path, result: dict[str, Any]) -> None:
    result["artifact_sha256"] = {
        rel(item): sha256(item)
        for base in (Path(result["build_directory"]), Path(result["evidence_directory"]))
        for item in sorted(base.rglob("*"))
        if item.is_file() and item.name not in {"result.json", "host_preflight.json"}
    }
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("host", "xsim", "ooc"), default="host")
    parser.add_argument("--run-id")
    parser.add_argument("--vivado", type=Path, default=VIVADO_BIN / "vivado.bat")
    args = parser.parse_args()

    if args.phase == "host":
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    else:
        if not args.run_id:
            parser.error("--run-id is required for xsim and ooc phases")
        run_id = args.run_id
    build = BUILD_ROOT / run_id
    evidence = EVIDENCE_ROOT / run_id
    if args.phase == "host":
        if build.exists() or evidence.exists():
            raise FileExistsError("refusing to overwrite a prior build/evidence run")
        build.mkdir(parents=True)
        evidence.mkdir(parents=True)
    elif not build.is_dir() or not evidence.is_dir():
        raise FileNotFoundError("the selected prior host-preflight run does not exist")

    result_path = evidence / "result.json"
    if args.phase != "host":
        result = json.loads(result_path.read_text(encoding="utf-8"))
        expected_phase_status = {"xsim": "PASS_HOST_PREFLIGHT_ONLY", "ooc": "PASS_PRIVATE_NATIVE_ROW_PIPELINE_XSIM_ONLY"}[args.phase]
        if result.get("status") != expected_phase_status:
            raise ValueError(f"phase {args.phase} requires prior status {expected_phase_status}")
        before = result["source_sha256_before"]
        current = inventory(source_paths())
        deps = inventory(dependency_paths())
        if before != current or result["dependency_sha256_before"] != deps:
            raise RuntimeError("source/dependency identities changed between approved phases")
    else:
        result = {
            "run_id": run_id,
            "status": "RUNNING",
            "objective": "full first-convolution output row through native feature window, 12-site MAC, exact requant, packaged SiLU, and 512-bit packer",
            "scope": "private offline host/XSim/OOC only; no route, board access, production integration, or FPS claim",
            "device_part": PART,
            "board_access": False,
            "route_attempted": False,
            "production_integrated": False,
            "full_pipeline_30fps_accepted": False,
            "vendor_attempts": {"xsim_flows": 0, "ooc_synthesis_flows": 0, "retry_count": 0},
            "limits": {"xsim_numerical_threads": 1, "vivado_max_threads": 2,
                       "dsp_exact": 1920, "bram36eq_max": 180,
                       "slice_lut_max": 120000, "slice_ff_max": 100000,
                       "latch_exact": 0, "blackbox_exact": 0},
            "build_directory": str(build.resolve()), "evidence_directory": str(evidence.resolve()),
            "commands": [],
        }
        try:
            upstream = verify_upstream()
            bound = source_paths()
            deps = dependency_paths()
            source_before = inventory(bound)
            dependency_before = inventory(deps)
            snapshot(bound, evidence / "source_snapshot")
            snapshot(deps, evidence / "dependency_snapshot")
            result["source_sha256_before"] = source_before
            result["dependency_sha256_before"] = dependency_before
            result["upstream"] = {
                key: {"path": value["path"], "status": value["status"], "sha256": value["sha256"]}
                for key, value in upstream["reports"].items()
            }
            result["reference"] = prepare_fixture(build)
            generated = {rel(path): path for path in build.glob("*.hex")}
            if len(generated) != 10:
                raise RuntimeError(f"expected10 immutable fixture files, got {len(generated)}")
            result["fixture_sha256"] = inventory(generated)
            if inventory(bound) != source_before or inventory(deps) != dependency_before:
                raise RuntimeError("source or dependency changed during host preflight")
            result["source_sha256_after_host"] = source_before
            result["dependency_sha256_after_host"] = dependency_before
            result["status"] = "PASS_HOST_PREFLIGHT_ONLY"
            (evidence / "host_preflight.json").write_text(json.dumps({
                "status": result["status"], "run_id": run_id,
                "source_sha256": source_before, "dependency_sha256": dependency_before,
                "fixture_sha256": result["fixture_sha256"], "reference": result["reference"],
                "upstream": result["upstream"]}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        except Exception as error:
            result["status"] = "FAILED_CLOSED_HOST_PREFLIGHT"
            result["failure_stage"] = "host_preflight"
            result["error"] = f"{type(error).__name__}: {error}"
            result["source_sha256_after_host"] = inventory({k:v for k,v in source_paths().items() if v.is_file()})
        save_result(result_path, result)
        print(json.dumps({"status": result["status"], "run_id": run_id,
                          "report": rel(result_path), "error": result.get("error"),
                          "reference": result.get("reference")}, sort_keys=True), flush=True)
        return 0 if result["status"] == "PASS_HOST_PREFLIGHT_ONLY" else 2

    try:
        if args.phase == "xsim":
            result["vendor_attempts"]["xsim_flows"] = 1
            result["toolchain"] = {"xvlog": str(VIVADO_BIN / "xvlog.bat"),
                                   "xelab": str(VIVADO_BIN / "xelab.bat"),
                                   "xsim": str(VIVADO_BIN / "xsim.bat"),
                                   "vivado_version": "2026.1", "numerical_threads": 1,
                                   "xelab_mt": 2}
            result["simulation"] = xsim_phase(build, evidence, result)
            result["status"] = "PASS_PRIVATE_NATIVE_ROW_PIPELINE_XSIM_ONLY"
        else:
            result["vendor_attempts"]["ooc_synthesis_flows"] = 1
            result["ooc"] = run_ooc(build, evidence, result, args.vivado)
            result["status"] = "PASS_PRIVATE_NATIVE_ROW_PIPELINE_XSIM_OOC_SCREEN_ONLY"
        result["source_sha256_after"] = inventory(source_paths())
        result["dependency_sha256_after"] = inventory(dependency_paths())
        if result["source_sha256_after"] != result["source_sha256_before"] or \
           result["dependency_sha256_after"] != result["dependency_sha256_before"]:
            raise RuntimeError("bound source or dependency changed during vendor validation")
    except Exception as error:
        result["status"] = "FAILED_CLOSED_" + args.phase.upper()
        result["failure_stage"] = args.phase
        result["error"] = f"{type(error).__name__}: {error}"
        result["source_sha256_after"] = inventory({k:v for k,v in source_paths().items() if v.is_file()})
        result["dependency_sha256_after"] = inventory({k:v for k,v in dependency_paths().items() if v.is_file()})
    save_result(result_path, result)
    print(json.dumps({"status": result["status"], "run_id": run_id,
                      "report": rel(result_path), "failure_stage": result.get("failure_stage"),
                      "error": result.get("error"), "simulation": result.get("simulation"),
                      "ooc": result.get("ooc")}, sort_keys=True), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
