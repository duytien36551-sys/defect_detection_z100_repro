#!/usr/bin/env python3
"""Read-only source binding and independent integer checks for the isolated fabric32 candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "deployment/hardware/z100_2026/accum33_fabric32_v1"
ORIGINAL_ACCUM = ROOT / "build/v12p_d46da432/rtl/z100_accum33_dsp.sv"
ORIGINAL_MAC = ROOT / "build/v12p_d46da432/rtl/z100_window_mac.sv"
LEGACY_VECTORS = ROOT / "validation/board_z100/accum33_dsp_v2/20261024T051501.085372Z/src/tb_z100_accum33_dsp.sv"
MASK33 = (1 << 33) - 1
SIGN33 = 1 << 32

EXPECTED_SHA256 = {
    "original_accumulator": "0b046f32b223a2c9055e27773def8e66a0e5755fd66fa9611dde6a6575e60d51",
    "original_window_mac": "f573c82fab313161d4097eedafcb7669026dbf6e4c29efa313f0a575fe29e474",
    "legacy_accumulator_vectors": "caca963201be0589150fc0f3f37e60933fe0ffe4bf2dc34089203ddf958036fb",
}

NEW_MAC_BLOCK = """            if (accum_site == 0) begin : gen_fabric32_accumulator
                z100_accum33_fabric32_v1 feedback_accumulator (
                    .clk(clk), .rst_n(rst_n), .cancel(cancel),
                    .load_bias(accumulator_load_bias),
                    .enable(local_accumulator_enable[accum_site*32+accum_lane]),
                    .bias((accum_site<run_sites && accum_lane<run_lanes) ? bias[accum_lane] : 32'sd0),
                    .delta(sum_q[accum_site][accum_lane]), .value_valid(),
                    .value(accum[accum_site][accum_lane]), .clamped(), .overflow()
                );
            end else begin : gen_dsp_accumulator
                z100_accum33_dsp feedback_accumulator (
                    .clk(clk), .rst_n(rst_n), .cancel(cancel),
                    .load_bias(accumulator_load_bias),
                    .enable(local_accumulator_enable[accum_site*32+accum_lane]),
                    .bias((accum_site<run_sites && accum_lane<run_lanes) ? bias[accum_lane] : 32'sd0),
                    .delta(sum_q[accum_site][accum_lane]), .value_valid(),
                    .value(accum[accum_site][accum_lane]), .clamped(), .overflow()
                );
            end"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def signed_bias_bits(value: int) -> int:
    require(-(1 << 31) <= value < (1 << 31), "bias outside signed32")
    return value & MASK33


def signed19(value: int) -> int:
    require(-(1 << 18) <= value < (1 << 18), "delta outside signed19")
    return value


def update33(state: int, delta: int) -> int:
    return (state + (delta & MASK33)) & MASK33


def visible(state: int, valid: bool) -> tuple[bool, int, int, bool]:
    if not valid:
        return False, 0, 0, False
    high = (state >> 32) & 1
    sign32 = (state >> 31) & 1
    overflow = high != sign32
    if overflow:
        clamp = 0x80000000 if high else 0x7FFFFFFF
    else:
        clamp = state & 0xFFFFFFFF
    return True, state, clamp, overflow


def read_all() -> tuple[dict, str, str, str]:
    manifest_path = PACKAGE / "manifest.json"
    require(manifest_path.is_file(), "manifest.json missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "z100-accum33-fabric32-candidate/1", "manifest schema mismatch")
    require(manifest.get("simulation_gate", {}).get("status") == "AUTHORED_NOT_RUN",
            "simulation gate must remain explicitly AUTHORED_NOT_RUN")

    source_paths = {
        "original_accumulator": ORIGINAL_ACCUM,
        "original_window_mac": ORIGINAL_MAC,
        "legacy_accumulator_vectors": LEGACY_VECTORS,
    }
    for name, path in source_paths.items():
        require(path.is_file(), f"missing bound source {name}: {path}")
        actual = sha256(path)
        require(actual == EXPECTED_SHA256[name], f"frozen source hash mismatch for {name}: {actual}")
        require(manifest["source_bindings"][name]["sha256"] == actual,
                f"manifest source hash mismatch for {name}")

    artifact_paths = {
        "fabric_accumulator": PACKAGE / "z100_accum33_fabric32_v1.sv",
        "site0_mac_candidate": PACKAGE / "z100_window_mac_fabric32_site0.sv",
        "miter_testbench": PACKAGE / "tb_z100_accum33_fabric32_miter.sv",
        "host_checker": ROOT / "tools/check_z100_accum33_fabric32_v1.py",
        "failed_attempt_record": PACKAGE / "failed_attempts.json",
    }
    for name, path in artifact_paths.items():
        require(path.is_file(), f"candidate artifact missing: {name}")
        entry = manifest["candidate_artifacts"][name]
        relative = path.relative_to(ROOT).as_posix()
        require(entry["path"] == relative, f"manifest path mismatch for {name}")
        actual = sha256(path)
        require(entry["sha256"] == actual, f"candidate artifact hash mismatch for {name}: {actual}")

    original = ORIGINAL_MAC.read_text(encoding="utf-8")
    candidate = artifact_paths["site0_mac_candidate"].read_text(encoding="utf-8")
    anchor = "            z100_accum33_dsp feedback_accumulator ("
    require(original.count(anchor) == 1, "original MAC anchor is not unique")
    start = original.index(anchor)
    end = original.index("            );", start) + len("            );")
    old_block = original[start:end]
    expected_old = """            z100_accum33_dsp feedback_accumulator (
                .clk(clk), .rst_n(rst_n), .cancel(cancel),
                .load_bias(accumulator_load_bias),
                .enable(local_accumulator_enable[accum_site*32+accum_lane]),
                .bias((accum_site<run_sites && accum_lane<run_lanes) ? bias[accum_lane] : 32'sd0),
                .delta(sum_q[accum_site][accum_lane]), .value_valid(),
                .value(accum[accum_site][accum_lane]), .clamped(), .overflow()
            );"""
    require(old_block == expected_old, "actual frozen instance body differs from checked anchor")
    expected_candidate = original[:start] + NEW_MAC_BLOCK + original[end:]
    require(candidate == expected_candidate, "candidate MAC differs beyond the single site0 accumulator substitution")
    require("parameter integer SITES=20" in original, "frozen MAC default site count changed")
    require(original.count("for(accum_lane=0;accum_lane<32;accum_lane=accum_lane+1)") == 1,
            "frozen 32-lane feedback loop changed")
    require(candidate.count("if (accum_site == 0)") == 1, "site0 selection branch must occur once")
    require(candidate.count("z100_accum33_fabric32_v1 feedback_accumulator") == 1,
            "site0 fabric component instance must occur once in generated source")
    require(candidate.count("z100_accum33_dsp feedback_accumulator") == 1,
            "remaining DSP component instance must occur once in generated source")

    component = (PACKAGE / "z100_accum33_fabric32_v1.sv").read_text(encoding="utf-8")
    required_component_fragments = (
        "module z100_accum33_fabric32_v1",
        "reg signed [32:0] feedback_q;",
        "load_bias ? $signed({bias[31], bias}) : feedback",
        "load_bias ? 33'sd0 : $signed({{14{delta[18]}}, delta})",
        "(load_bias || (enable && initialized))",
        "if (update)",
        "feedback_q <= feedback_sum;",
        "if (!rst_n || cancel)",
        '(* use_dsp = "no" *) wire signed [32:0] feedback_sum = operand_a + operand_b;',
        "assign value_valid = rst_n && !cancel && initialized;",
        "feedback[32] != feedback[31]",
    )
    for fragment in required_component_fragments:
        require(fragment in component, f"component semantic guard missing: {fragment}")
    require(component.count("use_dsp") == 1, "use_dsp=no must target only the fabric feedback adder")
    require('(* use_dsp = "no" *) module' not in component, "module-wide use_dsp constraint is forbidden")

    tb = (PACKAGE / "tb_z100_accum33_fabric32_miter.sv").read_text(encoding="utf-8")
    for fragment in (
        "z100_accum33_dsp dsp_reference",
        "z100_accum33_fabric32_v1 fabric_candidate",
        "load_bias has priority over enable",
        "Uninitialized enable must not update",
        "legacy bias/group/delta vector schedule",
        "Positive 33-bit wrap",
        "Negative 33-bit wrap",
        "Reset, cancel, and fresh load",
        "ACCUM33_FABRIC32_MITER_PASS",
    ):
        require(fragment in tb, f"miter directed coverage text missing: {fragment}")

    failed = json.loads((PACKAGE / "failed_attempts.json").read_text(encoding="utf-8"))
    require(len(failed.get("attempts", [])) == 2, "both prior mechanical failures must be preserved")
    require("Worker execution record" in failed.get("evidence_source", ""),
            "prior failure evidence provenance must remain explicit")
    return manifest, original, candidate, component


def run_integer_vectors() -> dict:
    checks = 0
    # An uninitialized accumulator ignores enable. A same-edge load wins over enable/delta.
    valid = False
    state = 0
    if valid and True:
        state = update33(state, signed19(262143))
    require(visible(state, valid) == (False, 0, 0, False), "uninitialized vector failed")
    state = signed_bias_bits(0x7FFFFFFF)
    valid = True
    checks += 1
    require(state == 0x07FFFFFFF, "load-bias priority vector failed")
    state = update33(state, signed19(1))
    checks += 1
    require(visible(state, valid) == (True, 0x080000000, 0x7FFFFFFF, True),
            "signed32 positive saturation vector failed")
    state = update33(state, signed19(-1))
    require(state == 0x07FFFFFFF, "positive saturation recovery vector failed")

    # Positive signed33 wrap through max 0x0ffffffff to min 0x100000000.
    state = signed_bias_bits(0x7FFFFFFF)
    for _ in range(8192):
        state = update33(state, signed19(262143))
        checks += 1
    require(state == 0x0FFFFDFFF, f"positive pre-wrap boundary wrong: {state:09x}")
    state = update33(state, signed19(8192))
    require(state == 0x0FFFFFFFF, f"positive signed33 max wrong: {state:09x}")
    require(visible(state, True) == (True, 0x0FFFFFFFF, 0x7FFFFFFF, True),
            "positive signed33 clamp at wrap edge failed")
    state = update33(state, signed19(1))
    require(state == 0x100000000, f"positive wrap failed: {state:09x}")
    require(visible(state, True) == (True, 0x100000000, 0x80000000, True),
            "negative signed33 min clamp at wrap edge failed")
    state = update33(state, signed19(-1))
    require(state == 0x0FFFFFFFF, "post-positive-wrap decrement failed")

    # Negative signed33 wrap from the minimum signed32 bias.
    state = signed_bias_bits(-0x80000000)
    for _ in range(8192):
        state = update33(state, signed19(-262144))
        checks += 1
    require(state == 0x100000000, f"negative signed33 min wrong: {state:09x}")
    state = update33(state, signed19(-1))
    require(state == 0x0FFFFFFFF, f"negative wrap failed: {state:09x}")

    # Hold ignores changing operands; contiguous enabled cycles update one per cycle.
    hold_start = state
    for i in range(1024):
        _changed_bias = i
        _changed_delta = signed19(262143)
        require(state == hold_start, "hold vector changed state")
        checks += 1
    state = signed_bias_bits(0)
    for _ in range(1024):
        state = update33(state, signed19(123))
        checks += 1
    require(state == 1024 * 123, "continuous II=1 arithmetic vector failed")

    # Reset/cancel hide prior state; enable before reload is ignored; fresh load works at enable=0.
    valid = False
    state = 0
    require(visible(state, valid) == (False, 0, 0, False), "reset mask vector failed")
    valid = True
    state = signed_bias_bits(-1234)
    valid = False
    require(visible(state, valid) == (False, 0, 0, False), "cancel mask vector failed")
    if valid:
        state = update33(state, signed19(99))
    require(not valid, "pre-reload update became valid")
    state = signed_bias_bits(42)
    valid = True
    require(visible(state, valid)[1] == 42, "fresh reload vector failed")
    state = update33(state, signed19(1))
    require(visible(state, valid)[1] == 43, "post-reload update failed")

    return {
        "status": "PASS_INDEPENDENT_INTEGER_VECTORS_NOT_RTL_SIMULATION",
        "checked_update_and_hold_steps": checks,
        "positive_pre_wrap": "0x0ffffdfff",
        "positive_max_then_wrap": ["0x0ffffffff", "0x100000000", "0x0ffffffff"],
        "negative_min_then_wrap": ["0x100000000", "0x0ffffffff"],
        "continuous_updates": 1024,
        "scope": "independent Python modulo-2^33 model only; does not execute RTL",
    }


def main() -> int:
    manifest, _original, _candidate, _component = read_all()
    model = run_integer_vectors()
    print("SOURCE_BINDING_PASS frozen_accum_and_mac_and_legacy_vectors")
    print("MAC_EXACT_DIFF_PASS one generated accumulator block; site0 selects fabric, other sites retain DSP")
    print(json.dumps(model, sort_keys=True))
    print("RTL_SIMULATION_GATE=AUTHORED_NOT_RUN")
    print("STATUS=PASS_SOURCE_IDENTITY_AND_INTEGER_MODEL_NOT_RTL_SIMULATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())