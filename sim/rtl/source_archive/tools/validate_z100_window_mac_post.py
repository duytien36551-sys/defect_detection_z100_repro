"""Validate the private first-convolution window/MAC/requant/SiLU XSim flow."""
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
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

RTL_ROOT = ROOT / "deployment/hardware/z100_2026"
OUT_DIR = RTL_ROOT / "window_mac_post_v1"
WRAPPER = OUT_DIR / "z100_window_mac_post.sv"
TB = OUT_DIR / "tb_z100_window_mac_post.sv"
SCRIPT = Path(__file__).resolve()

BANK_RTL = RTL_ROOT / "feature_banks_v1/z100_feature_banks.sv"
WINDOW_RTL = RTL_ROOT / "feature_window_v2/z100_feature_window.sv"
MAC_RTL = RTL_ROOT / "window_mac_v1/z100_window_mac.sv"
BRIDGE_RTL = RTL_ROOT / "window_mac_integration_v1/z100_window_mac_bridge.sv"
PREVIOUS_TB = RTL_ROOT / "window_mac_integration_v1/tb_z100_window_mac_integration.sv"
REQUANT_RTL = RTL_ROOT / "requant_vector_v1/z100_requant_vector.sv"
REQUANT_TB = RTL_ROOT / "requant_vector_v1/tb_z100_requant_vector.sv"
UNARY_RTL = RTL_ROOT / "unary32_v1/z100_unary32.sv"
UNARY_TB = RTL_ROOT / "unary32_v1/tb_z100_unary32.sv"

INTEGRATION_RUN = "20261023T170656.575146Z_6a293ada"
INTEGRATION_REPORT = ROOT / "validation/board_z100/window_mac_integration_v1" / INTEGRATION_RUN / "result.json"
REQUANT_RUN = "20261023T170603.603537Z_1260c0c7"
REQUANT_REPORT = ROOT / "validation/board_z100/requant_vector_v1" / REQUANT_RUN / "result.json"
UNARY_RUN = "20261023T171701.605516Z_279fb687"
UNARY_REPORT = ROOT / "validation/board_z100/unary32_v1" / UNARY_RUN / "result.json"
UNARY_REVIEW = ROOT / "validation/board_z100/acceleration_resource_review/20261023T171930.525770Z/unary32_review.json"
TABLE_RUN = "20261023T123433.385667Z_a3372b64"
TABLE_BUILD = ROOT / "deployment/build/z100_current_requant_tables" / TABLE_RUN
TABLE_REPORT = ROOT / "validation/board_z100/current_requant_tables" / TABLE_RUN / "result.json"
POINTWISE_RUN = "20261023T165100.884151Z_5e3e437d"
POINTWISE_BUILD = ROOT / "deployment/build/z100_pointwise_tables_v1" / POINTWISE_RUN
POINTWISE_REPORT = ROOT / "validation/board_z100/pointwise_tables_v1" / POINTWISE_RUN / "result.json"
POINTWISE_MANIFEST = POINTWISE_BUILD / "tables_manifest.json"
SILU_NODE1 = POINTWISE_BUILD / "node_001_silu_input_0.bin"

PIPELINE = ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline"
PACKAGE = PIPELINE / "package/MODEL.V8P"
HEADER = PIPELINE / "package/v8_generated_model.h"
GRAPH = PIPELINE / "model/graph.json"
INPUT = ROOT / "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_nchw_int8.bin"
HOST_PARITY = INPUT.parent / "result.json"
NATIVE_BUILD = ROOT / "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef"
NATIVE_WEIGHTS = NATIVE_BUILD / "weights_group4x32.bin"
NATIVE_BIASES = NATIVE_BUILD / "biases_int32x32.bin"
NATIVE_MANIFEST = NATIVE_BUILD / "manifest.json"
NATIVE_REPORT = ROOT / "validation/board_z100/native_window_weights/20261023T163945.127217Z_2b86c9ef/result.json"
COMPONENT_REVIEW = ROOT / "validation/board_z100/acceleration_resource_review/20261023T165119.142697Z/native_components_review.json"

CHANNEL_INDEX = TABLE_BUILD / "channel_index.json"
THRESHOLDS = TABLE_BUILD / "thresholds_254_i64.bin"
PACKED_TREES = TABLE_BUILD / "trees_255_i33_le5.bin"
REQUANT_ORACLE_C = RTL_ROOT / "requant_threshold_v0/oracle.c"
REQUANT_ORACLE_PY = TOOLS / "z100_requant_thresholds.py"
REQUANT_VALIDATOR = TOOLS / "validate_z100_requant_thresholds.py"
POINTWISE_ORACLE_C = RTL_ROOT / "pointwise_tables_v1/oracle.c"
POINTWISE_PREPARER = TOOLS / "prepare_z100_pointwise_tables.py"
LAYOUT_TOOL = TOOLS / "z100_feature_window_layout.py"
WEIGHT_CONVERTER = TOOLS / "prepare_z100_native_window_weights.py"
PREVIOUS_VALIDATOR = TOOLS / "validate_z100_window_mac_integration.py"
REQUANT_VALIDATOR = TOOLS / "validate_z100_requant_vector.py"
UNARY_VALIDATOR = TOOLS / "validate_z100_unary32.py"

EXPECTED = {
    "integration_report_sha256": "fdc2ec1d705f4e8b6c46836311982dd74e985569705ab609f9d0df6579f59c89",
    "requant_report_sha256": "48f8097f7e7c1878e384151560454626dc62f44f42686157284e6a7550e8972e",
    "unary_report_sha256": "ccfe44b7a8f74b1ffb8128e38d4b9c310d0227f8badef573f09b729d85aafb63",
    "unary_review_sha256": "0bb72303f03571ba9e87eb236881e038efcf017d2e66553a4d0479802b068aa1",
    "table_report_sha256": "28d255401c637fc23519da5199a785e849958aaaa74868a98b7f077d050056c9",
    "pointwise_report_sha256": "204435c287d9a9fe21fbd3f87afd322078f8f8b4dee87666d715da714fed5f17",
    "pointwise_manifest_sha256": "69470ca5d7eb8a19a8f48d9002b6d63cddc5787e57e0a09b44a724711307e2fc",
    "package_sha256": "96211aa416da6b23955a8b62cca594275daaa4db3e3954632960707c0ec0d44f",
    "header_sha256": "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5",
    "graph_sha256": "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8",
    "input_sha256": "0d458d68cf3e419e238245193cd5415c75b2931eb011a695c7b5a5765a1718b6",
    "native_manifest_sha256": "081aff4a32bc27123863ebf0d44d543d2561feffcd72e378233c974597f6a3e5",
    "native_weights_sha256": "9232bf379643e06e966c2a89aee0de854eca25a1f9d6872ff391ed3e44eb91a2",
    "native_biases_sha256": "e228de7b7d9641d0b29d42e512477b19e44bbfe6d1f49c2c8d5b3e2bd0e36ff2",
    "thresholds_sha256": "d9976d7627edc76656fb9e9084011b996a3cb323c30cd8147f6ee4d2fd04b203",
    "channel_index_sha256": "c2172462db9099370fb6e026538ef4dc683b158304dfcc1b1b8f99e3863b8147",
    "packed_trees_sha256": "7d04a7a43ce9799111a07697641c70d52163fb354c306c672701181648ca1db8",
    "silu_node1_sha256": "54061a5b58cc00bbecbeea5f17cdf8c2d84a2716490553f46ff05d54b901c735",
    "bank_rtl_sha256": "1120057983cc822d35f56b2245174d11734307a485cdb20966aba0579ae22310",
    "window_rtl_sha256": "d6208a8b0f40f36c407c6ccc883f34fa70fc026025181015d7dc16bca92a9857",
    "mac_rtl_sha256": "c2de472f539276da097e5ccd5bc7d44f2695dbff55ecb73458ea0105accbb643",
    "bridge_rtl_sha256": "9a1e234f9ed9208c39e777c6fca33b39d2742a59ef1f8ba7e5af3ec62fc589d5",
    "requant_rtl_sha256": "9b54f28143369f5ea037253ad181eb69895126bb58bd37776539fd9fd496e1c1",
    "unary_rtl_sha256": "847163d56b6e52cf25846d10cd8761bdb4a5058bec1a2d65b9c3743a4e14ed3d",
}

VIVADO = Path("C:/appload/2026.1/Vivado/bin/vivado.bat")
JOBS = ((0, 0), (0, 317), (1, 11), (100, 40), (101, 0), (101, 317))
SENTINEL = 1 << 31
MASK33 = (1 << 33) - 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def signed8(byte: int) -> int:
    return byte - 256 if byte >= 128 else byte


def signed32(value: int) -> int:
    return value - (1 << 32) if value & (1 << 31) else value


def inventory(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in paths.items()}


def load_previous_validator() -> Any:
    spec = importlib.util.spec_from_file_location("z100_previous_window_mac_validation", PREVIOUS_VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the frozen direct-OIHW vector generator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def source_paths() -> dict[str, Path]:
    return {
        relative(WRAPPER): WRAPPER,
        relative(TB): TB,
        relative(SCRIPT): SCRIPT,
        relative(BANK_RTL): BANK_RTL,
        relative(WINDOW_RTL): WINDOW_RTL,
        relative(MAC_RTL): MAC_RTL,
        relative(BRIDGE_RTL): BRIDGE_RTL,
        relative(PREVIOUS_TB): PREVIOUS_TB,
        relative(REQUANT_RTL): REQUANT_RTL,
        relative(REQUANT_TB): REQUANT_TB,
        relative(UNARY_RTL): UNARY_RTL,
        relative(UNARY_TB): UNARY_TB,
        relative(PREVIOUS_VALIDATOR): PREVIOUS_VALIDATOR,
        relative(REQUANT_VALIDATOR): REQUANT_VALIDATOR,
        relative(UNARY_VALIDATOR): UNARY_VALIDATOR,
        relative(LAYOUT_TOOL): LAYOUT_TOOL,
        relative(WEIGHT_CONVERTER): WEIGHT_CONVERTER,
        relative(REQUANT_ORACLE_C): REQUANT_ORACLE_C,
        relative(REQUANT_ORACLE_PY): REQUANT_ORACLE_PY,
        relative(REQUANT_VALIDATOR.parent / "validate_z100_requant_thresholds.py"):
            REQUANT_VALIDATOR.parent / "validate_z100_requant_thresholds.py",
        relative(POINTWISE_ORACLE_C): POINTWISE_ORACLE_C,
        relative(POINTWISE_PREPARER): POINTWISE_PREPARER,
        relative(INTEGRATION_REPORT): INTEGRATION_REPORT,
        relative(REQUANT_REPORT): REQUANT_REPORT,
        relative(UNARY_REPORT): UNARY_REPORT,
        relative(UNARY_REVIEW): UNARY_REVIEW,
        relative(TABLE_REPORT): TABLE_REPORT,
        relative(POINTWISE_REPORT): POINTWISE_REPORT,
        relative(POINTWISE_MANIFEST): POINTWISE_MANIFEST,
        relative(PACKAGE): PACKAGE,
        relative(HEADER): HEADER,
        relative(GRAPH): GRAPH,
        relative(INPUT): INPUT,
        relative(HOST_PARITY): HOST_PARITY,
        relative(NATIVE_MANIFEST): NATIVE_MANIFEST,
        relative(NATIVE_WEIGHTS): NATIVE_WEIGHTS,
        relative(NATIVE_BIASES): NATIVE_BIASES,
        relative(NATIVE_REPORT): NATIVE_REPORT,
        relative(COMPONENT_REVIEW): COMPONENT_REVIEW,
        relative(CHANNEL_INDEX): CHANNEL_INDEX,
        relative(THRESHOLDS): THRESHOLDS,
        relative(PACKED_TREES): PACKED_TREES,
        relative(SILU_NODE1): SILU_NODE1,
    }


def verify_report_bindings(paths: dict[str, Path]) -> dict[str, Any]:
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen source/evidence dependency: {path}")
    actual_hashes = {name: sha256(path) for name, path in paths.items()}
    direct_expected = {
        relative(BANK_RTL): EXPECTED["bank_rtl_sha256"],
        relative(WINDOW_RTL): EXPECTED["window_rtl_sha256"],
        relative(MAC_RTL): EXPECTED["mac_rtl_sha256"],
        relative(BRIDGE_RTL): EXPECTED["bridge_rtl_sha256"],
        relative(REQUANT_RTL): EXPECTED["requant_rtl_sha256"],
        relative(UNARY_RTL): EXPECTED["unary_rtl_sha256"],
        relative(PACKAGE): EXPECTED["package_sha256"],
        relative(HEADER): EXPECTED["header_sha256"],
        relative(GRAPH): EXPECTED["graph_sha256"],
        relative(INPUT): EXPECTED["input_sha256"],
        relative(NATIVE_MANIFEST): EXPECTED["native_manifest_sha256"],
        relative(NATIVE_WEIGHTS): EXPECTED["native_weights_sha256"],
        relative(NATIVE_BIASES): EXPECTED["native_biases_sha256"],
        relative(THRESHOLDS): EXPECTED["thresholds_sha256"],
        relative(CHANNEL_INDEX): EXPECTED["channel_index_sha256"],
        relative(PACKED_TREES): EXPECTED["packed_trees_sha256"],
        relative(SILU_NODE1): EXPECTED["silu_node1_sha256"],
    }
    for name, expected in direct_expected.items():
        if actual_hashes[name] != expected:
            raise ValueError(f"pinned dependency hash changed: {name}")
    for name, expected in (
        (relative(INTEGRATION_REPORT), EXPECTED["integration_report_sha256"]),
        (relative(REQUANT_REPORT), EXPECTED["requant_report_sha256"]),
        (relative(UNARY_REPORT), EXPECTED["unary_report_sha256"]),
        (relative(UNARY_REVIEW), EXPECTED["unary_review_sha256"]),
        (relative(TABLE_REPORT), EXPECTED["table_report_sha256"]),
        (relative(POINTWISE_REPORT), EXPECTED["pointwise_report_sha256"]),
        (relative(POINTWISE_MANIFEST), EXPECTED["pointwise_manifest_sha256"]),
    ):
        if actual_hashes[name] != expected:
            raise ValueError(f"pinned evidence hash changed: {name}")

    integration = json.loads(INTEGRATION_REPORT.read_text(encoding="utf-8"))
    if integration.get("status") != "PASS_PRIVATE_CURRENT_NATIVE_WINDOW_MAC_INTEGRATION_XSIM_ONLY":
        raise ValueError("frozen six-job bridge/window/MAC evidence is not passing")
    sim = integration.get("simulation", {})
    if (sim.get("jobs"), sim.get("requests"), sim.get("responses"), sim.get("outputs"),
        sim.get("raw_words"), sim.get("flags"), sim.get("load_words"),
        sim.get("weight_groups"), sim.get("bias_loads")) != (6, 54, 54, 22, 704, 704, 8160, 9, 1):
        raise ValueError("frozen bridge/window/MAC evidence counts changed")
    for name, expected in integration.get("source_sha256", {}).items():
        normalized = name.replace("\\", "/")
        path = ROOT / normalized
        if path.is_file() and sha256(path) != expected:
            raise ValueError(f"bridge/window/MAC report source changed: {name}")

    requant = json.loads(REQUANT_REPORT.read_text(encoding="utf-8"))
    if requant.get("status") != "PASS_XSIM_PRIVATE_32_LANE_CURRENT_MODEL":
        raise ValueError("frozen exact requantizer XSim evidence is not passing")
    rq_sim = requant.get("simulation", {})
    if (rq_sim.get("jobs"), rq_sim.get("channels"), rq_sim.get("accept_ii_failures"),
        rq_sim.get("output_ii_failures")) != (173, 5419, 0, 0):
        raise ValueError("frozen requantizer evidence counts changed")
    for key, data in requant.get("source_sha256_before", {}).items():
        path = ROOT / key.replace("\\", "/")
        if not path.is_file() or sha256(path) != data["sha256"]:
            raise ValueError(f"requantizer report source mismatch: {key}")
    if requant.get("source_sha256_before") != requant.get("source_sha256_after"):
        raise ValueError("requantizer source changed during its accepted run")

    unary = json.loads(UNARY_REPORT.read_text(encoding="utf-8"))
    if unary.get("status") != "PASS_PRIVATE_UNARY32_XSIM_OOC_SYNTH_ONLY":
        raise ValueError("frozen unary32 XSim/OOC evidence is not passing")
    unary_sim = unary.get("simulation", {})
    if (unary_sim.get("tables"), unary_sim.get("exhaustive_active_bytes"),
        unary_sim.get("max_consecutive_accepts_ii1")) != (57, 466944, 256):
        raise ValueError("frozen unary32 simulation counts changed")
    for key, digest in unary.get("source_sha256_before", {}).items():
        role_to_path = {"rtl": UNARY_RTL, "testbench": UNARY_TB, "validator": UNARY_VALIDATOR}
        path = role_to_path[key]
        if sha256(path) != digest:
            raise ValueError(f"unary32 report source mismatch: {path}")
    if unary.get("source_sha256_before") != unary.get("source_sha256_after"):
        raise ValueError("unary32 source changed during its accepted run")
    unary_review = json.loads(UNARY_REVIEW.read_text(encoding="utf-8"))
    if (unary_review.get("status") != "ROOT_REVIEW_UNARY32_XSIM_OOC_PASS_ONLY" or
        unary_review.get("report_sha256") != sha256(UNARY_REPORT) or
        unary_review.get("production_integrated") is not False or
        unary_review.get("full_pipeline_30fps_accepted") is not False):
        raise ValueError("root unary32 review does not bind the accepted private-only evidence")

    table_report = json.loads(TABLE_REPORT.read_text(encoding="utf-8"))
    if (table_report.get("status"), table_report.get("channels"),
        table_report.get("convolution_nodes"), table_report.get("c_boundary_vectors"),
        table_report.get("keys_per_channel"), table_report.get("threshold_bits"),
        table_report.get("sentinel_index")) != (
            "PASS_CURRENT_PACKAGE_EXACT_THRESHOLDS_HOST_ONLY", 5419, 63, 4_156_373, 255, 33, 254):
        raise ValueError("current C-verified requant threshold evidence differs")
    pointwise = json.loads(POINTWISE_REPORT.read_text(encoding="utf-8"))
    if (pointwise.get("status") != "PASS_PIN640_POINTWISE_TABLES_HOST_ONLY" or
        pointwise.get("manifest_sha256") != EXPECTED["pointwise_manifest_sha256"] or
        pointwise.get("unary_c_comparisons") != 31_232 or
        pointwise.get("add_c_comparisons") != 393_216 or
        pointwise.get("silu_exact_package_bytes_checked") != 14_592):
        raise ValueError("C-verified pointwise asset evidence differs")
    if integration.get("board_access") is not False or integration.get("synthesis_attempted") is not False or \
       integration.get("production_integrated") is not False:
        raise ValueError("upstream bridge/window/MAC evidence exceeds its frozen scope")
    return {
        "hashes": actual_hashes,
        "integration": integration,
        "requant": requant,
        "unary": unary,
        "unary_review": unary_review,
        "table_report": table_report,
        "pointwise_report": pointwise,
    }


def prepare_tables_and_goldens(build: Path, prior_validator: Any) -> dict[str, Any]:
    old_hashes, old_deps = prior_validator.verify_source_bindings()
    direct_reference = prior_validator.generate_fixture(build, old_deps)

    package_file = PACKAGE.read_bytes()
    if len(package_file) < 32 or package_file[:4] != b"V8PK":
        raise ValueError("frozen model package header is invalid")
    magic, version, payload_size, crc, nodes, arena, classes, resolution = struct.unpack(
        "<4s7I", package_file[:32])
    payload = package_file[32:]
    if (magic, version, payload_size, nodes, classes, resolution) != (
            b"V8PK", 1, len(payload), 163, 9, 640) or zlib.crc32(payload) != crc:
        raise ValueError("frozen V8PK header or payload CRC mismatch")

    descriptors = re.findall(r"^\s*(\{\.op=[^\n]+)", HEADER.read_text(encoding="utf-8"), re.M)
    if len(descriptors) != 163:
        raise ValueError("expected the frozen 163 generated-header descriptors")

    def field(row: str, name: str) -> int:
        values = re.findall(r"\." + re.escape(name) + r"=(\d+)(?:,|})", row)
        if len(values) != 1:
            raise ValueError(f"generated descriptor field is missing or ambiguous: {name}")
        return int(values[0])

    conv = descriptors[0]
    silu = descriptors[1]
    multiplier_offset = field(conv, "multiplier")
    lut_offset = field(silu, "lut")
    if field(conv, "op") != 0 or field(conv, "c") != 16 or field(conv, "kernel") != 3 or \
       field(conv, "stride") != 2 or field(conv, "padding") != 1 or \
       field(silu, "op") != 1 or field(silu, "c") != 16:
        raise ValueError("generated first-convolution or node-1 SiLU metadata changed")
    if multiplier_offset + 16*8 > len(payload) or lut_offset + 256 > len(payload):
        raise ValueError("generated multiplier or LUT range exceeds the V8PK payload")
    package_silu = payload[lut_offset:lut_offset+256]
    point_manifest = json.loads(POINTWISE_MANIFEST.read_text(encoding="utf-8"))
    point_entry = next((row for row in point_manifest.get("tables", [])
                        if row.get("node_id") == 1 and row.get("operator") == "silu" and
                        row.get("input_index") == 0), None)
    if point_entry is None or point_entry.get("asset_file") != SILU_NODE1.name or \
       point_entry.get("byte_length") != 256 or point_entry.get("exact_package_bytes") is not True or \
       point_entry.get("package_parameter_range_half_open") != [lut_offset, lut_offset+256]:
        raise ValueError("C-verified node-1 SiLU asset metadata does not match generated package")
    silu_asset = SILU_NODE1.read_bytes()
    if silu_asset != package_silu or len(silu_asset) != 256:
        raise ValueError("node-1 SiLU asset does not exactly equal the original V8PK bytes")
    (build / "unary_cfg.hex").write_text(
        "".join(f"{byte:02x}\n" for byte in silu_asset), encoding="ascii", newline="\n")

    channel_rows = json.loads(CHANNEL_INDEX.read_text(encoding="utf-8"))
    thresholds = THRESHOLDS.read_bytes()
    packed_tree = PACKED_TREES.read_bytes()
    by_channel = {int(row["channel"]): (index, row)
                  for index, row in enumerate(channel_rows) if int(row["node"]) == 0}
    if sorted(by_channel) != list(range(16)):
        raise ValueError("current first-convolution transition table does not have channels 0..15")
    channel_keys: dict[int, list[int]] = {}
    multipliers: dict[int, float] = {}
    for channel, (channel_index, row) in by_channel.items():
        multiplier_bytes = payload[multiplier_offset + channel*8:multiplier_offset + (channel+1)*8]
        multiplier = struct.unpack("<d", multiplier_bytes)[0]
        if not math.isfinite(multiplier) or multiplier <= 0.0 or \
           row.get("multiplier_binary64_le_hex") != multiplier_bytes.hex():
            raise ValueError(f"channel {channel} binary64 multiplier differs from generated V8PK")
        start = int(row["threshold_start_byte"])
        keys_unsigned = [int.from_bytes(packed_tree[start + index*5:start + (index+1)*5], "little")
                         for index in range(255)]
        keys = [value - (1 << 33) if value & (1 << 32) else value for value in keys_unsigned]
        threshold_start = channel_index * 254 * 8
        transition_bytes = thresholds[threshold_start:threshold_start + 254*8]
        if len(transition_bytes) != 254*8:
            raise ValueError(f"channel {channel} transition table is truncated")
        original_thresholds = [value[0] for value in struct.iter_unpack("<q", transition_bytes)]
        if keys[:254] != original_thresholds or keys[254] != SENTINEL or \
           keys != sorted(keys) or row.get("key_count") != 255 or row.get("sentinel_index") != 254:
            raise ValueError(f"channel {channel} packed 33-bit key tree differs from current threshold bytes")
        channel_keys[channel] = keys
        multipliers[channel] = multiplier

    def config_word(index: int) -> int:
        result = 0
        for lane in range(32):
            key = channel_keys[lane][index] if lane < 16 else SENTINEL
            result |= (key & MASK33) << (lane * 33)
        return result

    (build / "req_cfg.hex").write_text(
        "".join(f"{config_word(index):0264x}\n" for index in range(255)),
        encoding="ascii", newline="\n")

    raw_words = [int(line.strip(), 16) for line in (build / "expected_raw_words.hex").read_text(
        encoding="ascii").splitlines() if line.strip()]
    if len(raw_words) != 22:
        raise ValueError("direct OIHW generator did not produce the 22 expected raw sites")
    post_words: list[int] = []
    active_comparisons = 0
    for raw_word in raw_words:
        packed_post = 0
        for lane in range(32):
            output_byte = 0
            if lane < 16:
                raw_value = signed32((raw_word >> (32 + lane*32)) & 0xFFFFFFFF)
                # Match the packaged binary64 scalar path directly. The C-verified
                # transition table is configuration only and is never the oracle.
                scaled = raw_value * multipliers[lane]
                quantized = round(scaled)
                quantized = max(-127, min(127, quantized))
                output_byte = package_silu[quantized + 128]
                active_comparisons += 1
            packed_post |= output_byte << (lane*8)
        post_words.append(packed_post)
    if active_comparisons != 352:
        raise ValueError(f"original arithmetic/LUT golden byte count changed: {active_comparisons}")
    (build / "expected_post_words.hex").write_text(
        "".join(f"{word:064x}\n" for word in post_words), encoding="ascii", newline="\n")

    return {
        "direct_reference": direct_reference,
        "active_channels": 16,
        "requant_config_words": 255,
        "requant_config_keys": 255*32,
        "requant_active_channel_key_count": 16*255,
        "requant_inactive_lane_sentinel_keys": 16*255,
        "requant_transition_keys_checked_against_current_i64_tables": 16*254,
        "original_header_binary64_multipliers": 16,
        "packaged_node1_silu_bytes": len(package_silu),
        "packaged_silu_sha256": hashlib.sha256(package_silu).hexdigest(),
        "postprocess_original_arithmetic_lut_byte_comparisons": active_comparisons,
        "postprocess_expected_tail_bytes": 22*16,
        "postprocess_reference": "direct original OIHW+bias raw -> generated-header binary64 multiplier -> Python binary64 ties-even round/clamp[-127,127] -> original V8PK node-1 SiLU LUT bytes",
        "transition_keys_used_only_for_hardware_configuration": True,
        "native_feature_words": 8160,
        "native_weight_groups": 9,
        "native_bias_words": 1,
        "jobs": [{"oy": y, "ox": x, "sites": min(4, 320-x), "groups": 9}
                 for y, x in JOBS],
    }


def run_command(command: list[str], cwd: Path, log_path: Path, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        subprocess.list2cmdline(command), cwd=str(cwd), shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=1800,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {
        "args": command,
        "cwd": str(cwd.resolve()),
        "return_code": completed.returncode,
        "log": relative(log_path),
        "log_sha256": sha256(log_path),
        "warning_mentions": len(re.findall(r"\bWARNING\b", completed.stdout, re.I)),
        "output": completed.stdout,
    }


def run_xsim(build: Path, evidence: Path, env: dict[str, str], result: dict[str, Any]) -> dict[str, Any]:
    bindir = VIVADO.parent
    xvlog, xelab, xsim = (bindir / "xvlog.bat", bindir / "xelab.bat", bindir / "xsim.bat")
    for tool in (xvlog, xelab, xsim):
        if not tool.is_file():
            raise FileNotFoundError(f"Vivado 2026.1 XSim executable is missing: {tool}")

    sources = [BANK_RTL, WINDOW_RTL, MAC_RTL, BRIDGE_RTL, REQUANT_RTL, UNARY_RTL, WRAPPER, TB]
    result["vendor_attempts"]["xsim_flows"] = 1
    command_records = result["commands"]
    command_records.append(run_command([str(xvlog), "-sv", *map(str, sources)], build, evidence / "xvlog.log", env))
    if command_records[-1]["return_code"] != 0:
        raise RuntimeError("xvlog failed; stop after this first vendor failure")
    command_records.append(run_command([str(xelab), "-mt", "2", "tb_z100_window_mac_post",
                                        "-s", "window_mac_post_sim"], build, evidence / "xelab.log", env))
    if command_records[-1]["return_code"] != 0:
        raise RuntimeError("xelab failed; stop after this first vendor failure")
    command_records.append(run_command([str(xsim), "window_mac_post_sim", "-runall"],
                                        build, evidence / "xsim.log", env))
    simulation = command_records[-1]["output"]
    if command_records[-1]["return_code"] != 0 or re.search(r"(?im)^\s*(?:Fatal:|ERROR:)", simulation):
        raise RuntimeError("xsim failed; stop after this first vendor failure")
    pattern = re.compile(
        r"WINDOW_MAC_POST_PASS jobs=(\d+) requests=(\d+) responses=(\d+) raw_beats=(\d+) "
        r"raw_lanes=(\d+) flags=(\d+) post_beats=(\d+) active_bytes=(\d+) masked_tails=(\d+) "
        r"load_words=(\d+) weight_groups=(\d+) bias_loads=(\d+) req_words=(\d+) unary_bytes=(\d+) "
        r"input_bubbles=(\d+) response_stalls=(\d+) raw_stalls=(\d+) post_stalls=(\d+) metadata=(\d+) residency=(\d+) "
        r"pause_mode=INJECTED_REQ_IN_READY_LOW injected_pause_cycles=(\d+) "
        r"injected_pause_stability=(\d+) raw_stall_stability=(\d+)"
    )
    found = pattern.findall(simulation)
    if len(found) != 1:
        raise RuntimeError("XSim pass marker with exact full-flow coverage is missing or repeated")
    values = tuple(map(int, found[0]))
    expected = (6, 54, 54, 22, 704, 704, 22, 352, 352, 8160, 9, 1, 255, 256)
    if values[:14] != expected or values[14] <= 0 or values[15] < 3 or values[16] < 1 or \
       values[17] < 3 or values[18:20] != (22, 6) or values[20] != 3 or \
       values[21] != 3 or values[22] < 2:
        raise RuntimeError(f"XSim full-flow coverage mismatch: {values}")
    if "DDR raw" in simulation or "DDR" in simulation:
        raise RuntimeError("unexpected DDR-related XSim output")
    return {
        "status": "PASS",
        "jobs": values[0], "requests": values[1], "responses": values[2],
        "raw_mac_beats": values[3], "raw_lane_comparisons": values[4],
        "raw_overflow_flag_comparisons": values[5], "postprocess_beats": values[6],
        "active_int8_byte_comparisons": values[7], "masked_tail_byte_comparisons": values[8],
        "feature_words_loaded_once": values[9], "weight_groups_loaded_once": values[10],
        "bias_words_loaded_once": values[11], "requant_config_words_loaded_once": values[12],
        "unary_lut_bytes_loaded_once": values[13], "input_bubble_cycles": values[14],
        "window_response_stall_cycles": values[15], "raw_mac_backpressure_cycles": values[16],
        "post_output_stall_cycles": values[17], "metadata_checks": values[18],
        "resident_job_boundaries": values[19],
        "artificial_consumer_pause": {
            "mechanism": "testbench force on dut.req_in_ready before the first raw handshake",
            "pause_cycles": values[20],
            "raw_payload_and_metadata_stability_checks_during_pause": values[21],
            "raw_mac_stability_checks_during_stall": values[22],
            "natural_full_buffer_backpressure_claimed": False,
            "throughput_claimed": False,
        },
        "site_epoch_token_lanes_last_checked": True,
        "tail_bytes_zero_checked": True,
        "raw_accumulation_flags_checked_against_original_oihw": True,
        "post_golden_independent_of_threshold_tree": True,
        "no_ddr_raw_roundtrip": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado", type=Path, default=VIVADO)
    parser.add_argument("--host-only", action="store_true",
                        help="prepare source-bound vectors and stop before invoking Vivado")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    build = ROOT / "deployment/build/z100_window_mac_post_v1" / run_id
    evidence = ROOT / "validation/board_z100/window_mac_post_v1" / run_id
    build.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "status": "RUNNING",
        "run_id": run_id,
        "objective": "private six-job first-convolution native-window/MAC -> exact 32-lane requant -> node-1 SiLU; XSim only",
        "scope": "private RTL and validation fixture; no synthesis, route, board, production, or FPS claims",
        "commands": [],
        "vendor_attempts": {"xsim_flows": 0, "retry_count": 0, "synthesis_flows": 0},
        "limits": {"vivado_max_threads": 2, "numerical_threads": 1},
        "board_access": False,
        "route_attempted": False,
        "synthesis_attempted": False,
        "bitstream_created": False,
        "production_integrated": False,
        "ddr_raw_roundtrip": False,
    }
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    stage = "host_preflight"
    source_map = source_paths()
    dependency_map: dict[str, Path] = {}

    def snapshot(path_map: dict[str, Path], destination: Path) -> None:
        for name, path in path_map.items():
            out = destination / name
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)

    try:
        upstream = verify_report_bindings(source_map)
        source_before = inventory(source_map)
        snapshot(source_map, evidence / "source_snapshot")
        previous_validator = load_previous_validator()
        reference = prepare_tables_and_goldens(build, previous_validator)
        generated = [build / name for name in (
            "feature_words.hex", "integration_counts.svh", "native_weight_groups.hex",
            "native_bias.hex", "expected_raw_words.hex", "expected_post_words.hex",
            "req_cfg.hex", "unary_cfg.hex")]
        if any(not path.is_file() for path in generated):
            raise ValueError("host golden/config fixture generation omitted required files")
        dependency_map = {
            relative(PACKAGE): PACKAGE,
            relative(HEADER): HEADER,
            relative(GRAPH): GRAPH,
            relative(INPUT): INPUT,
            relative(NATIVE_MANIFEST): NATIVE_MANIFEST,
            relative(NATIVE_WEIGHTS): NATIVE_WEIGHTS,
            relative(NATIVE_BIASES): NATIVE_BIASES,
            relative(NATIVE_REPORT): NATIVE_REPORT,
            relative(COMPONENT_REVIEW): COMPONENT_REVIEW,
            relative(INTEGRATION_REPORT): INTEGRATION_REPORT,
            relative(REQUANT_REPORT): REQUANT_REPORT,
            relative(UNARY_REPORT): UNARY_REPORT,
            relative(UNARY_REVIEW): UNARY_REVIEW,
            relative(TABLE_REPORT): TABLE_REPORT,
            relative(POINTWISE_REPORT): POINTWISE_REPORT,
            relative(POINTWISE_MANIFEST): POINTWISE_MANIFEST,
            relative(CHANNEL_INDEX): CHANNEL_INDEX,
            relative(THRESHOLDS): THRESHOLDS,
            relative(PACKED_TREES): PACKED_TREES,
            relative(SILU_NODE1): SILU_NODE1,
        }
        dependency_before = inventory(dependency_map)
        snapshot(dependency_map, evidence / "dependency_snapshot")
        result["upstream"] = {
            "window_mac_integration": {"report": relative(INTEGRATION_REPORT),
                                       "report_sha256": sha256(INTEGRATION_REPORT),
                                       "simulation": upstream["integration"]["simulation"]},
            "requant_vector": {"report": relative(REQUANT_REPORT),
                               "report_sha256": sha256(REQUANT_REPORT),
                               "status": upstream["requant"]["status"],
                               "simulation": upstream["requant"]["simulation"]},
            "unary32": {"report": relative(UNARY_REPORT),
                        "report_sha256": sha256(UNARY_REPORT),
                        "root_review": relative(UNARY_REVIEW),
                        "root_review_sha256": sha256(UNARY_REVIEW),
                        "simulation": upstream["unary"]["simulation"]},
            "pointwise_tables": {"manifest": relative(POINTWISE_MANIFEST),
                                 "manifest_sha256": sha256(POINTWISE_MANIFEST),
                                 "c_oracle_report": relative(POINTWISE_REPORT),
                                 "c_oracle_report_sha256": sha256(POINTWISE_REPORT),
                                 "c_unary_comparisons": upstream["pointwise_report"]["unary_c_comparisons"],
                                 "c_add_comparisons": upstream["pointwise_report"]["add_c_comparisons"]},
        }
        result["reference"] = reference
        result["source_sha256_before"] = source_before
        result["dependency_sha256_before"] = dependency_before
        result["fixtures"] = {relative(path): {"bytes": path.stat().st_size, "sha256": sha256(path)}
                              for path in generated}
        (evidence / "host_preflight.json").write_text(
            json.dumps({"status": "PASS_HOST_PREFLIGHT", "run_id": run_id,
                        "source_sha256": source_before, "dependency_sha256": dependency_before,
                        "reference": reference}, indent=2) + "\n", encoding="utf-8")

        if not args.host_only:
            stage = "xsim"
            result["toolchain"] = {
                "vivado_bin": str(args.vivado.resolve().parent),
                "vivado_launcher": str(args.vivado.resolve()),
                "python": "C:/Users/Administrator/Desktop/v8/.venv/Scripts/python.exe",
                "vivado_max_threads": 2,
                "numerical_threads": 1,
            }
            result["simulation"] = run_xsim(build, evidence, env, result)

        source_after = inventory(source_map)
        dependency_after = inventory(dependency_map)
        if source_after != source_before or dependency_after != dependency_before:
            raise ValueError("bound sources or current package/table dependencies changed during validation")
        result["source_sha256_after"] = source_after
        result["dependency_sha256_after"] = dependency_after
        result["status"] = ("PASS_HOST_PREFLIGHT_ONLY" if args.host_only else
                             "PASS_PRIVATE_WINDOW_MAC_POST_XSIM_ONLY")
        stage = "complete"
    except Exception as error:  # one immutable attempt; never retry vendor work here
        result["status"] = "FAILED_CLOSED"
        result["failure_stage"] = stage
        result["error"] = f"{type(error).__name__}: {error}"
        result["source_sha256_after"] = inventory({key: path for key, path in source_map.items()
                                                    if path.is_file()})
        if dependency_map:
            result["dependency_sha256_after"] = inventory({key: path for key, path in dependency_map.items()
                                                            if path.is_file()})

    result["artifact_sha256"] = {
        relative(path): sha256(path)
        for folder in (build, evidence)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "result.json"
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "run_id": run_id,
        "report": relative(evidence / "result.json"),
        "failure_stage": result.get("failure_stage"),
        "error": result.get("error"),
        "simulation": result.get("simulation"),
    }), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
