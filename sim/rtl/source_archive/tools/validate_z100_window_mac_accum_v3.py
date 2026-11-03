"""Host-preflight and validate the private scalar DSP-feedback native-window MAC v3.

The candidate is a constrained structural transform of v2: each generated
site/lane owns one scalar 48-bit feedback register/add; sum_q stays registered
in fabric. Default invocation is host-only. The optional vendor flow runs XSim
first and exactly one OOC synthesis only after XSim passes; it never places or
routes the design.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
RTL_DIR = ROOT / "deployment/hardware/z100_2026"
FIXTURE_DIR = RTL_DIR / "window_mac_accum_v3"
BASELINE_RTL = RTL_DIR / "window_mac_accum_v2/z100_window_mac_accum_v2.sv"
BASELINE_TB = RTL_DIR / "window_mac_accum_v2/tb_z100_window_mac_accum_v2.sv"
BASELINE_VALIDATOR = ROOT / "tools/validate_z100_window_mac_accum.py"
CORE_RTL = FIXTURE_DIR / "z100_window_mac_accum_v3.sv"
TB_RTL = FIXTURE_DIR / "tb_z100_window_mac_accum_v3.sv"
OOC_TCL = FIXTURE_DIR / "window_mac_accum_ooc_v3.tcl"
SELF = Path(__file__).resolve()
BUILD_ROOT = ROOT / "deployment/build/window_mac_accum_v3"
EVIDENCE_ROOT = ROOT / "validation/board_z100/window_mac_accum_v3"
PYTHON = ROOT / '.venv/Scripts/python.exe'
VIVADO_BIN = Path(r"C:\appload\2026.1\Vivado\bin")
BASELINE_SHA256 = "3a44251cfdfd6148d859139b5fc9afdad0292105b7aaf2e1472dbbaa33ccd20e"
PART = "xc7z100ffg900-2"
MAX_GROUPS = 1024
SITES = 4
TOTAL_GROUPS = 1657
CASE_COUNT = 8
EXPECTED_OUTPUTS = 16
BUNDLE_WIDTH = 1099
MASK33 = (1 << 33) - 1
SIGN33 = 1 << 32
MIN33 = -(1 << 32)
MAX33 = (1 << 32) - 1
MIN32 = -(1 << 31)
MAX32 = (1 << 31) - 1


CASES = (
    {"groups": 1, "lanes": 1, "sites": 1, "epoch": 101, "token": 0x4D410101, "kind": "numeric"},
    {"groups": 9, "lanes": 3, "sites": 2, "epoch": 102, "token": 0x4D410102, "kind": "numeric"},
    {"groups": 36, "lanes": 9, "sites": 3, "epoch": 103, "token": 0x4D410103, "kind": "numeric"},
    {"groups": 576, "lanes": 16, "sites": 4, "epoch": 104, "token": 0x4D410104, "kind": "numeric"},
    {"groups": 1024, "lanes": 32, "sites": 4, "epoch": 105, "token": 0x4D410105, "kind": "numeric"},
    {"groups": 9, "lanes": 32, "sites": 4, "epoch": 106, "token": 0x4D410106, "kind": "cancel"},
    {"groups": 1, "lanes": 3, "sites": 2, "epoch": 107, "token": 0x4D410107, "kind": "reset"},
    {"groups": 1, "lanes": 3, "sites": 2, "epoch": 108, "token": 0x4D410108, "kind": "recovery"},
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def replace_once(source: str, before: str, after: str, label: str) -> str:
    count = source.count(before)
    if count != 1:
        raise ValueError(f"Expected one {label} source seam, found {count}")
    return source.replace(before, after, 1)


def expected_candidate_from_v2(source: str) -> str:
    """Rebuild the only allowed v2-to-v3 scalar-feedback RTL transform."""
    source = replace_once(source, "module z100_window_mac_accum_v2 #(",
                          "module z100_window_mac_accum_v3 #(", "module name")
    source = replace_once(
        source,
        "    // One 48-bit DSP feedback accumulator per site/lane. Only bits [32:0]\n"
        "    // participate in the existing 33-bit wrap, clamp, and overflow behavior.\n"
        "    (* use_dsp = \"yes\" *) reg signed [47:0] accum_dsp[0:SITES-1][0:31];\n"
        "    (* use_dsp = \"yes\" *) wire signed [47:0] accum_plus_sum[0:SITES-1][0:31];",
        "    // Per-generated-lane accumulator values are exposed through this\n"
        "    // read-only view; the scalar DSP objects live in gen_lane.\n"
        "    wire signed [47:0] accum_read[0:SITES-1][0:31];",
        "accumulator declarations")
    source = replace_once(
        source,
        "    wire input_good=input_fire && act_token==token && act_last==expected_last;\n",
        "    wire input_good=input_fire && act_token==token && act_last==expected_last;\n"
        "    wire run_start_good=run_valid && run_ready && run_epoch==weights_epoch &&\n"
        "        run_token!=0 && run_lanes!=0 && run_lanes<=32 && run_sites!=0 && run_sites<=SITES;\n",
        "valid run-start qualifier")
    old_lane_seam = (
        "            assign accum_plus_sum[site][lane]=\n"
        "                accum_dsp[site][lane]+$signed({{29{sum_q[site][lane][18]}},sum_q[site][lane]});\n"
        "            always @(posedge clk) begin"
    )
    new_lane_seam = (
        "            // Scalar per-site/lane feedback objects keep the 48-bit add and\n"
        "            // accumulator register visible to DSP inference independently.\n"
        "            (* use_dsp = \"yes\" *) reg signed [47:0] feedback_accum;\n"
        "            (* use_dsp = \"yes\" *) wire signed [47:0] feedback_next=\n"
        "                feedback_accum+$signed({{29{sum_q[site][lane][18]}},sum_q[site][lane]});\n"
        "            assign accum_read[site][lane]=feedback_accum;\n"
        "            always @(posedge clk) begin\n"
        "                if(rst_n && !cancel) begin\n"
        "                    if(run_start_good)\n"
        "                        feedback_accum<= (site<run_sites && lane<run_lanes) ?\n"
        "                            $signed({{16{bias[lane][31]}},bias[lane]}) : 48'sd0;\n"
        "                    if(p3_valid && (state==INPUTS || state==FLUSH) && site<sites && lane<lanes)\n"
        "                        feedback_accum<=feedback_next;\n"
        "                end\n"
        "            end\n"
        "            always @(posedge clk) begin"
    )
    source = replace_once(source, old_lane_seam, new_lane_seam, "scalar feedback generate block")
    source = replace_once(
        source,
        "wire signed [32:0] value=accum_dsp[drain_site][lane][32:0];",
        "wire signed [32:0] value=accum_read[drain_site][lane][32:0];",
        "read-only accumulator output view")
    source = replace_once(
        source,
        "                    for(s=0;s<SITES;s=s+1)\n"
        "                        for(l=0;l<32;l=l+1)\n"
        "                            accum_dsp[s][l]<= (s<run_sites && l<run_lanes) ?\n"
        "                                $signed({{16{bias[l][31]}},bias[l]}) : 48'sd0;\n",
        "",
        "global accumulator initialization removal")
    source = replace_once(
        source,
        "                for(s=0;s<SITES;s=s+1)\n"
        "                    for(l=0;l<32;l=l+1)\n"
        "                        if(s<sites && l<lanes)\n"
        "                            accum_dsp[s][l]<=accum_plus_sum[s][l];\n",
        "",
        "global accumulator feedback removal")
    return source


def signed8(value: int) -> int:
    value &= 0xFF
    return value - 256 if value & 0x80 else value


def weight_byte(case_index: int, group: int, tap: int, lane: int) -> int:
    if case_index == 0:
        return -128
    if case_index == 4 and lane == 0:
        return 127
    if case_index == 4 and lane == 1:
        return -128
    if case_index == 4 and lane == 2:
        return -128 if group < 512 else 127
    if case_index == 4 and lane == 3:
        return 127 if group < 512 else -128
    mix = (case_index * 53 + group * 29 + tap * 71 + lane * 17) & 0xFF
    return signed8(mix)


def activation_byte(case_index: int, group: int, tap: int, site: int) -> int:
    if case_index == 0:
        return -128
    if case_index == 4 and site == 0:
        return -128
    mix = (case_index * 31 + group * 11 + tap * 47 + site * 23) & 0xFF
    return signed8(mix)


def bias_value(case_index: int, lane: int) -> int:
    if case_index == 0 and lane == 0:
        return MAX32 - 16
    if case_index == 4 and lane == 0:
        return MIN32 + 1000
    if case_index == 4 and lane == 1:
        return MAX32 - 1000
    if case_index == 4 and lane == 2:
        return MAX32 - 600_000
    if case_index == 4 and lane == 3:
        return MIN32 + 600_000
    return ((lane * 1151 + case_index * 7919) % 100_001) - 50_000


def pack_weight_word(case_index: int, group: int) -> int:
    word = 0
    for tap in range(4):
        for lane in range(32):
            word |= (weight_byte(case_index, group, tap, lane) & 0xFF) << (tap * 256 + lane * 8)
    return word


def pack_activation_word(case_index: int, group: int) -> int:
    word = 0
    for tap in range(4):
        for site in range(SITES):
            word |= (activation_byte(case_index, group, tap, site) & 0xFF) << ((tap * SITES + site) * 8)
    return word


def signed33(raw: int) -> int:
    value = raw & MASK33
    return value - (1 << 33) if value & SIGN33 else value


def clamp33_to_32(raw: int) -> tuple[int, bool, int]:
    value = signed33(raw)
    overflow = value < MIN32 or value > MAX32
    clipped = min(MAX32, max(MIN32, value))
    return clipped & 0xFFFFFFFF, overflow, value


def encode_output(token: int, site: int, last: bool, lanes: int,
                  overflow_mask: int, data_word: int) -> int:
    value = token & 0xFFFFFFFF
    value = (value << 4) | (site & 0xF)
    value = (value << 1) | int(last)
    value = (value << 6) | (lanes & 0x3F)
    value = (value << 32) | (overflow_mask & 0xFFFFFFFF)
    value = (value << 1024) | (data_word & ((1 << 1024) - 1))
    if value.bit_length() > BUNDLE_WIDTH:
        raise ValueError("Expected bundle exceeds the 1099-bit core interface")
    return value


def create_vectors(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    weight_words: list[int] = []
    activation_words: list[int] = []
    bias_words: list[int] = []
    case_words: list[int] = []
    offsets: list[int] = []

    for case_index, case in enumerate(CASES):
        offsets.append(len(weight_words))
        for group in range(case["groups"]):
            weight_words.append(pack_weight_word(case_index, group))
            activation_words.append(pack_activation_word(case_index, group))
        bias_word = 0
        for lane in range(32):
            bias_word |= (bias_value(case_index, lane) & 0xFFFFFFFF) << (lane * 32)
        bias_words.append(bias_word)
        desc = (case["groups"] << 85) | (case["lanes"] << 79) | (case["sites"] << 75)
        desc |= case["epoch"] << 43
        desc |= case["token"] << 11
        desc |= offsets[-1]
        case_words.append(desc)

    output_words: list[int] = []
    raw_min: int | None = None
    raw_max: int | None = None
    overflow_count = 0
    active_channel_outputs = 0
    inactive_channel_outputs = 0
    product_checks = 0
    transient_crossings: dict[str, dict] = {}
    run_output_counts: list[dict] = []

    for case_index in [0, 1, 2, 3, 4, 7]:
        case = CASES[case_index]
        case_overflows = 0
        case_product_checks = 0
        for site in range(case["sites"]):
            data_word = 0
            overflow_mask = 0
            for lane in range(32):
                if lane < case["lanes"]:
                    raw = bias_value(case_index, lane)
                    accumulator = raw
                    crossed_high = False
                    crossed_low = False
                    for group in range(case["groups"]):
                        group_sum = 0
                        for tap in range(4):
                            group_sum += activation_byte(case_index, group, tap, site) * weight_byte(case_index, group, tap, lane)
                            product_checks += 1
                            case_product_checks += 1
                        raw += group_sum
                        accumulator = signed33(accumulator + group_sum)
                        if accumulator != raw:
                            raise ValueError(
                                f"Legal API vector wrapped signed33 mid-run: case={case_index} site={site} lane={lane} group={group + 1}")
                        if accumulator > MAX32:
                            crossed_high = True
                        if accumulator < MIN32:
                            crossed_low = True
                    value = signed33(raw)
                    if value != raw:
                        raise ValueError(f"Legal API vector wrapped 33-bit accumulator: case={case_index} site={site} lane={lane} raw={raw}")
                    if not MIN33 <= value <= MAX33:
                        raise ValueError(f"Legal API result exceeds signed33: case={case_index} site={site} lane={lane} raw={value}")
                    data, overflow, _ = clamp33_to_32(raw)
                    raw_min = value if raw_min is None else min(raw_min, value)
                    raw_max = value if raw_max is None else max(raw_max, value)
                    active_channel_outputs += 1
                    if overflow:
                        case_overflows += 1
                        overflow_count += 1
                        overflow_mask |= 1 << lane
                else:
                    data = 0
                    inactive_channel_outputs += 1
                data_word |= data << (lane * 32)
            output_words.append(encode_output(
                token=case["token"], site=site, last=(site == case["sites"] - 1),
                lanes=case["lanes"], overflow_mask=overflow_mask, data_word=data_word))
        run_output_counts.append({
            "case": case_index,
            "groups": case["groups"],
            "lanes": case["lanes"],
            "sites": case["sites"],
            "output_beats": case["sites"],
            "active_channel_outputs": case["sites"] * case["lanes"],
            "inactive_zero_channel_outputs": case["sites"] * (32 - case["lanes"]),
            "signed32_overflow_flags": case_overflows,
            "independent_product_checks": case_product_checks,
        })
        if case_index == 4:
            for lane, key, predicate in (
                (2, "positive_cross_then_recover", lambda v: v > MAX32),
                (3, "negative_cross_then_recover", lambda v: v < MIN32),
            ):
                value = bias_value(case_index, lane)
                first_cross = None
                for group in range(case["groups"]):
                    group_sum = sum(
                        activation_byte(case_index, group, tap, 0) *
                        weight_byte(case_index, group, tap, lane)
                        for tap in range(4))
                    value = signed33(value + group_sum)
                    if first_cross is None and predicate(value):
                        first_cross = group + 1
                transient_crossings[key] = {
                    "case": case_index,
                    "site": 0,
                    "lane": lane,
                    "first_crossing_group": first_cross,
                    "final_signed33": value,
                    "final_within_signed32": MIN32 <= value <= MAX32,
                }

    if len(weight_words) != TOTAL_GROUPS or len(bias_words) != CASE_COUNT:
        raise AssertionError("Unexpected generated configuration vector counts")
    if len(output_words) != EXPECTED_OUTPUTS:
        raise AssertionError(f"Expected {EXPECTED_OUTPUTS} outputs, generated {len(output_words)}")
    for name, words, width in (
        ("weights.hex", weight_words, 1024),
        ("activations.hex", activation_words, 128),
        ("biases.hex", bias_words, 1024),
        ("cases.hex", case_words, 96),
        ("expected_outputs.hex", output_words, BUNDLE_WIDTH),
    ):
        digits = (width + 3) // 4
        (directory / name).write_text("".join(f"{word:0{digits}x}\n" for word in words), encoding="ascii")

    line_counts = {
        "weights.hex": TOTAL_GROUPS,
        "activations.hex": TOTAL_GROUPS,
        "biases.hex": CASE_COUNT,
        "cases.hex": CASE_COUNT,
        "expected_outputs.hex": EXPECTED_OUTPUTS,
    }
    for filename, count in line_counts.items():
        if len((directory / filename).read_text(encoding="ascii").splitlines()) != count:
            raise ValueError(f"Generated {filename} line count is incorrect")
    expected_file_widths = {
        "weights.hex": 256,
        "activations.hex": 32,
        "biases.hex": 256,
        "cases.hex": 24,
        "expected_outputs.hex": 275,
    }
    for filename, digits in expected_file_widths.items():
        lines = (directory / filename).read_text(encoding="ascii").splitlines()
        if any(len(line) != digits for line in lines):
            raise ValueError(f"Generated {filename} has a malformed word width")
    for case_index, (case, encoded, first_word) in enumerate(zip(CASES, case_words, offsets)):
        actual = {
            "groups": (encoded >> 85) & 0x7FF,
            "lanes": (encoded >> 79) & 0x3F,
            "sites": (encoded >> 75) & 0xF,
            "epoch": (encoded >> 43) & 0xFFFFFFFF,
            "token": (encoded >> 11) & 0xFFFFFFFF,
            "first_word": encoded & 0x7FF,
        }
        wanted = {key: case[key] for key in ("groups", "lanes", "sites", "epoch", "token")}
        wanted["first_word"] = first_word
        if actual != wanted:
            raise ValueError(f"Case descriptor {case_index} field encoding mismatch: {actual} != {wanted}")

    modulo_tests = []
    for raw in ((1 << 32), -(1 << 32) - 1, (1 << 33) + 7, -(1 << 33) - 9):
        modulo_tests.append({"input": raw, "signed33": signed33(raw)})
    if [item["signed33"] for item in modulo_tests] != [-(1 << 32), (1 << 32) - 1, 7, -9]:
        raise AssertionError("Host modulo-2^33 edge model self-check failed")

    legal_min = MIN32 + MAX_GROUPS * 4 * (-128 * 127)
    legal_max = MAX32 + MAX_GROUPS * 4 * (-128 * -128)
    if legal_min != -2_214_068_224 or legal_max != 2_214_592_511:
        raise AssertionError("Legal 1024-group bound changed unexpectedly")
    if legal_min <= MIN33 or legal_max > MAX33:
        raise AssertionError("Theoretical legal input bound reaches signed33 wrap")
    if not transient_crossings["positive_cross_then_recover"]["first_crossing_group"] or not transient_crossings["positive_cross_then_recover"]["final_within_signed32"]:
        raise AssertionError("Positive signed32 transient crossing/recovery case missing")
    if not transient_crossings["negative_cross_then_recover"]["first_crossing_group"] or not transient_crossings["negative_cross_then_recover"]["final_within_signed32"]:
        raise AssertionError("Negative signed32 transient crossing/recovery case missing")

    summary = {
        "configuration_words": {"weight_groups": len(weight_words), "bias_words": len(bias_words)},
        "activation_vector_groups": len(activation_words),
        "output_beats": len(output_words),
        "independent_oihw_signed_product_checks": product_checks,
        "active_channel_outputs": active_channel_outputs,
        "inactive_channels_forced_zero": inactive_channel_outputs,
        "final_signed32_overflow_flags": overflow_count,
        "final_raw_signed33_min": raw_min,
        "final_raw_signed33_max": raw_max,
        "profiles": run_output_counts,
        "modulo_2_to_33_host_edge_vectors": modulo_tests,
        "legal_1024_group_bound": {
            "formula_min": "INT32_MIN + 1024*4*(-128*127)",
            "formula_max": "INT32_MAX + 1024*4*(-128*-128)",
            "minimum": legal_min,
            "maximum": legal_max,
            "signed33_range": [MIN33, MAX33],
            "wrap_reachable_through_legal_api": False,
            "interpretation": "all legal products and bias fit signed33, so the host also tests modulo-2^33 edges without claiming a legal RTL input can reach wrap",
        },
        "legal_signed32_transient_crossings": transient_crossings,
        "stimulus_notes": [
            "first case drives signed max product (-128 * -128) and positive final saturation",
            "1024-group case drives minimum product (-128 * 127), maximum positive product, and signed32 crossing followed by recovery in both directions",
            "deterministic mixed signed-byte values cover all four taps, sites, and active lanes",
            "one/tail/non-multiple-of-eight lane counts and site counts 1, 2, 3, 4 are compared",
        ],
    }
    (directory / "host_reference.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def source_contract() -> dict:
    required = (BASELINE_RTL, BASELINE_TB, BASELINE_VALIDATOR, CORE_RTL, TB_RTL, OOC_TCL, SELF)
    missing = [rel(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing frozen v2 or candidate v3 source files: {missing}")
    hashes = {rel(path): sha256(path) for path in required}
    if hashes[rel(BASELINE_RTL)] != BASELINE_SHA256:
        raise ValueError("Frozen accumulator v2 RTL hash differs from the pinned input")
    baseline = BASELINE_RTL.read_text(encoding="utf-8")
    candidate = CORE_RTL.read_text(encoding="utf-8")
    if expected_candidate_from_v2(baseline) != candidate:
        raise ValueError("v3 RTL contains a change outside the reviewed scalar-feedback transform")
    baseline_header = baseline[:baseline.index("\n    localparam")]
    candidate_header = candidate[:candidate.index("\n    localparam")]
    if baseline_header.replace("z100_window_mac_accum_v2", "z100_window_mac_accum_vX") != candidate_header.replace(
            "z100_window_mac_accum_v3", "z100_window_mac_accum_vX"):
        raise ValueError("v3 module interface differs from frozen v2")
    baseline_tb = BASELINE_TB.read_text(encoding="utf-8")
    candidate_tb = TB_RTL.read_text(encoding="utf-8")
    expected_tb = replace_once(
        baseline_tb,
        "module tb_z100_window_mac_accum_v2;",
        "module tb_z100_window_mac_accum_v3;",
        "testbench module name")
    expected_tb = replace_once(
        expected_tb,
        "z100_window_mac_accum_v2 #(.SITES(4)) dut (",
        "z100_window_mac_accum_v3 #(.SITES(4)) dut (",
        "testbench DUT module type")
    expected_tb = replace_once(expected_tb, "WINDOW_MAC_ACCUM_V2_PASS", "WINDOW_MAC_ACCUM_V3_PASS",
                               "testbench pass marker")
    if expected_tb != candidate_tb:
        raise ValueError("v3 testbench differs from frozen v2 beyond private top/DUT/PASS renaming")
    if candidate.count("module z100_window_mac_accum_v3 #(") != 1:
        raise ValueError("v3 candidate does not declare exactly one expected module top")
    if candidate_tb.count("module tb_z100_window_mac_accum_v3;") != 1:
        raise ValueError("v3 testbench does not declare exactly one expected simulation top")
    if candidate_tb.count("z100_window_mac_accum_v3 #(.SITES(4)) dut (") != 1:
        raise ValueError("v3 testbench DUT type/instance does not bind to the candidate module")
    if "z100_window_mac_accum_v2 #(.SITES(4)) dut (" in candidate_tb:
        raise ValueError("v3 testbench still refers to the frozen v2 module")
    baseline_validator_source = BASELINE_VALIDATOR.read_text(encoding="utf-8")
    candidate_validator_source = SELF.read_text(encoding="utf-8")
    def function_segment(text: str, name: str) -> str:
        tree = ast.parse(text)
        node = next(item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
        return ast.get_source_segment(text, node) or ""
    if function_segment(baseline_validator_source, "create_vectors") != function_segment(candidate_validator_source, "create_vectors"):
        raise ValueError("v3 host vector generator differs from frozen v2 generator")
    for marker in (
        "reg p0_valid,p1_valid,p2_valid,p3_valid;",
        "p0_valid<=input_good; p1_valid<=p0_valid; p2_valid<=p1_valid; p3_valid<=p2_valid;",
        "if(p3_valid && (state==INPUTS || state==FLUSH))",
        "if(p3_last) begin state<=OUTPUTS;drain_site<=0;end",
        "wire signed [32:0] value=accum_read[drain_site][lane][32:0];",
        "(* use_dsp = \"no\" *) reg signed [18:0] sum_q",
        "(* use_dsp = \"yes\" *) reg signed [47:0] feedback_accum;",
        "(* use_dsp = \"yes\" *) wire signed [47:0] feedback_next=",
        "feedback_accum<=feedback_next;",
        "if(value[32]!=value[31])",
    ):
        if marker not in candidate:
            raise ValueError(f"Candidate RTL is missing structural contract {marker!r}")
    if "accum_dsp" in candidate or "accum_plus_sum" in candidate:
        raise ValueError("v3 retained the multidimensional v2 accumulator feedback object")
    if candidate.count("feedback_accum<=") != 2:
        raise ValueError("v3 feedback state must have only bias-init and p3-update assignments")
    if "place_design" in OOC_TCL.read_text(encoding="utf-8") or "route_design" in OOC_TCL.read_text(encoding="utf-8"):
        raise ValueError("OOC script must not place or route the design")
    return {
        "dependency_hashes": hashes,
        "baseline_sha256": hashes[rel(BASELINE_RTL)],
        "baseline_testbench_sha256": hashes[rel(BASELINE_TB)],
        "baseline_validator_sha256": hashes[rel(BASELINE_VALIDATOR)],
        "candidate_sha256": hashes[rel(CORE_RTL)],
        "baseline_to_candidate": "candidate reconstructed exactly from frozen v2 by adding the validated run-start predicate, replacing the multidimensional feedback declarations with a read-only view, moving feedback init/update into each generated lane, removing the former global writes, and changing only the private module name",
        "interface": "all ports and widths/order match frozen v2; the private module name alone differs",
        "testbench_delta": "frozen v2 testbench identical apart from private module name and PASS marker",
        "vector_generator": "create_vectors AST/source identical to frozen v2 validator",
        "pipeline": "p0-p3 valid/last chain, registered sum_q boundary, and p3 accumulation enable are preserved",
        "arithmetic": "each generated lane has one scalar signed48 feedback register and signed48 adder with use_dsp=yes; feedback init/update preserves v2 enables and priority; output and overflow inspect exactly low33 bits",
    }


def timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]


def snapshot_sources(directory: Path, paths: tuple[Path, ...]) -> dict[str, str]:
    snapshot_dir = directory / "source_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for source in paths:
        relative = rel(source)
        digest = sha256(source)
        target = snapshot_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[relative] = digest
    (directory / "source_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return hashes


def run_logged(command: list[str], cwd: Path, log_path: Path, env: dict[str, str]) -> dict:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("COMMAND " + json.dumps(command) + "\n")
        log.flush()
        result = subprocess.run(command, cwd=str(cwd), env=env, stdout=log,
                                stderr=subprocess.STDOUT, check=False)
    return {"command": command, "cwd": str(cwd), "log": str(log_path), "returncode": result.returncode}


def batch_command(batch: Path, arguments: list[str]) -> list[str]:
    commandline = subprocess.list2cmdline([str(batch), *arguments])
    return ["cmd.exe", "/d", "/s", "/c", commandline]


def check_ooc_evidence(directory: Path) -> dict:
    resource_path = directory / "resources_synth.txt"
    summary_path = directory / "dsp48e1_synth_summary.txt"
    census_path = directory / "dsp48e1_synth.tsv"
    if not all(path.is_file() for path in (resource_path, summary_path, census_path)):
        raise FileNotFoundError("OOC resource or DSP census artifact missing")
    resource_text = resource_path.read_text(encoding="utf-8")
    resource_values = {key: value for key, value in __import__("re").findall(r"([a-z0-9_]+)=([0-9.]+)", resource_text)}
    lut = int(resource_values["lut"])
    ff = int(resource_values["ff"])
    dsp = int(resource_values["dsp48e1"])
    bram = float(resource_values["bram36_equivalent"])
    latches = int(resource_values["latches"])
    blackboxes = int(resource_values["blackboxes"])
    summary_text = summary_path.read_text(encoding="utf-8")
    modes = {}
    for line in summary_text.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "USE_MULT_MODE":
            modes[fields[1]] = int(fields[2])
    rows = census_path.read_text(encoding="utf-8").splitlines()[1:]
    none_names = [row.split("\t", 1)[0] for row in rows if len(row.split("\t")) > 1 and row.split("\t")[1] == "NONE"]
    accum_none = [name for name in none_names if "feedback_accum" in name.lower() or "feedback_next" in name.lower()]
    checks = {
        "total_dsp48e1": dsp == 640,
        "multiply_dsp": modes.get("MULTIPLY", 0) == 512,
        "none_dsp": modes.get("NONE", 0) == 128,
        "other_dsp": sum(count for mode, count in modes.items() if mode not in ("MULTIPLY", "NONE")) == 0,
        "none_dsp_owned_by_scalar_feedback": len(accum_none) == 128,
        "lut_le_35000": lut <= 35000,
        "ff_le_25000": ff <= 25000,
        "bram36_eq_le_30": bram <= 30.0,
        "latches_zero": latches == 0,
        "blackboxes_zero": blackboxes == 0,
    }
    if not all(checks.values()):
        raise ValueError(f"OOC resource contract failed: {checks}")
    return {
        "resources": {"lut": lut, "ff": ff, "dsp48e1": dsp, "bram36_equivalent": bram,
                      "latches": latches, "blackboxes": blackboxes},
        "dsp_modes": modes,
        "none_dsp_owner_count": len(accum_none),
        "none_dsp_owner_names": accum_none,
        "checks": checks,
    }


def run_vendor(build_dir: Path, evidence_dir: Path, vector_dir: Path) -> dict:
    if not PYTHON.is_file():
        raise FileNotFoundError(f"Pinned Python is unavailable: {PYTHON}")
    for tool in ("xvlog.bat", "xelab.bat", "xsim.bat", "vivado.bat"):
        if not (VIVADO_BIN / tool).is_file():
            raise FileNotFoundError(f"Required 2026.1 tool is unavailable: {VIVADO_BIN / tool}")
    environment = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[name] = "1"
    xsim_dir = build_dir / "xsim"
    xsim_dir.mkdir(parents=True, exist_ok=True)
    for vector in vector_dir.glob("*.hex"):
        shutil.copyfile(vector, xsim_dir / vector.name)
    reports: dict[str, dict] = {"xsim_commands": []}
    commands = (
        ("xvlog", ["-sv", str(CORE_RTL), str(TB_RTL)]),
        ("xelab", ["-debug", "typical", "-mt", "2", "tb_z100_window_mac_accum_v3", "-s", "window_mac_accum_v3_snapshot"]),
        ("xsim", ["window_mac_accum_v3_snapshot", "-runall"]),
    )
    for label, arguments in commands:
        tool = VIVADO_BIN / f"{label}.bat"
        command = batch_command(tool, arguments)
        record = run_logged(command, xsim_dir, evidence_dir / f"{label}.log", environment)
        reports["xsim_commands"].append(record)
        if record["returncode"] != 0:
            raise RuntimeError(f"{label} failed with return code {record['returncode']}")
    xsim_log = (evidence_dir / "xsim.log").read_text(encoding="utf-8", errors="replace")
    if xsim_log.count("WINDOW_MAC_ACCUM_V3_PASS") != 1 or "FAIL:" in xsim_log:
        raise RuntimeError("XSim did not emit exactly one accumulator v3 PASS without FAIL diagnostics")
    reports["xsim_pass"] = True

    tcl_command = batch_command(
        VIVADO_BIN / "vivado.bat",
        ["-mode", "batch", "-source", str(OOC_TCL), "-tclargs", str(build_dir / "ooc"), str(evidence_dir / "ooc")],
    )
    (evidence_dir / "ooc").mkdir(parents=True, exist_ok=True)
    ooc_record = run_logged(tcl_command, ROOT, evidence_dir / "vivado_ooc.log", environment)
    reports["ooc_command"] = ooc_record
    if ooc_record["returncode"] != 0:
        raise RuntimeError(f"Vivado OOC synthesis failed with return code {ooc_record['returncode']}")
    vivado_log = (evidence_dir / "vivado_ooc.log").read_text(encoding="utf-8", errors="replace")
    if vivado_log.count("WINDOW_MAC_ACCUM_V3_OOC_PASS") != 1:
        raise RuntimeError("Vivado OOC run did not emit exactly one resource PASS marker")
    reports["ooc_pass"] = check_ooc_evidence(evidence_dir / "ooc")
    reports["route_or_board_run"] = False
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-vendor", action="store_true",
                        help="after host preflight, run one XSim then one OOC synthesis if XSim passes")
    args = parser.parse_args()
    if Path(sys.executable).resolve() != PYTHON.resolve():
        print(f"ERROR: use pinned Python interpreter {PYTHON}; running {sys.executable}", file=sys.stderr)
        return 2
    run_id = timestamp_id()
    build_dir = BUILD_ROOT / run_id
    evidence_dir = EVIDENCE_ROOT / run_id
    build_dir.mkdir(parents=True, exist_ok=False)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "commands.txt").write_text(
        f"INVOCATION {json.dumps([str(PYTHON), '-B', '-X', 'utf8', str(SELF), *sys.argv[1:]])}\n",
        encoding="utf-8")

    dependencies = (BASELINE_RTL, BASELINE_TB, BASELINE_VALIDATOR, CORE_RTL, TB_RTL, OOC_TCL, SELF)
    result = {
        "schema": "z100-window-mac-accum-v3-validation-v1",
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "private SITES=4 native-window MAC scalar-feedback mapping candidate",
        "device": PART,
        "vendor_requested": args.run_vendor,
        "vendor_executed": False,
        "status": "HOST_PREFLIGHT_RUNNING",
        "limits": {"max_dsp48e1": 640, "dsp48e1_modes": {"MULTIPLY": 512, "NONE": 128, "OTHER": 0},
                   "max_lut": 35000, "max_ff": 25000, "max_bram36_equivalent": 30,
                   "max_latches": 0, "max_blackboxes": 0, "route_or_board": False},
    }
    try:
        source_before = snapshot_sources(evidence_dir, dependencies)
        result["source_hashes_before"] = source_before
        result["source_contract"] = source_contract()
        vector_dir = build_dir / "vectors"
        result["host_reference"] = create_vectors(vector_dir)
        result["host_preflight"] = {
            "status": "PASS",
            "vector_sha256": {path.name: sha256(path) for path in sorted(vector_dir.iterdir()) if path.is_file()},
            "expected_output_bundle_width": BUNDLE_WIDTH,
            "all_case_descriptors_valid": True,
            "source_delta_exactly_scoped": True,
        }
        result["status"] = "HOST_PREFLIGHT_PASS"
        if args.run_vendor:
            result["vendor_executed"] = True
            result["vendor"] = run_vendor(build_dir, evidence_dir, vector_dir)
            result["status"] = "VENDOR_PASS"
        source_after = {rel(path): sha256(path) for path in dependencies}
        result["source_hashes_after"] = source_after
        result["sources_unchanged"] = source_before == source_after
        if not result["sources_unchanged"]:
            raise RuntimeError("One or more source dependencies changed during validation")
    except Exception as exc:  # Preserve every failed preflight/vendor artifact.
        result["status"] = "VENDOR_FAIL" if result.get("vendor_executed") else "HOST_PREFLIGHT_FAIL"
        result["failure"] = f"{type(exc).__name__}: {exc}"
        try:
            result["source_hashes_after"] = {rel(path): sha256(path) for path in dependencies if path.is_file()}
            result["sources_unchanged"] = result.get("source_hashes_before") == result["source_hashes_after"]
        except Exception as snapshot_exc:
            result["source_snapshot_error"] = f"{type(snapshot_exc).__name__}: {snapshot_exc}"
        (evidence_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{result['status']}: {evidence_dir / 'result.json'}")
        print(result["failure"], file=sys.stderr)
        return 1

    (evidence_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['status']}: {evidence_dir / 'result.json'}")
    print(json.dumps(result.get("host_reference", {}), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
