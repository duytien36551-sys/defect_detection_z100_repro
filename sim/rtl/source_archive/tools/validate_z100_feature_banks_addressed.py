"""Validate the addressed native-output to 64-bank feature-store seam.

--host-only runs the independent CHW fixture and scatter checks.
--diagnostic-xsim repeats host preflight and runs XSim only, preserving bounded
wait diagnostics without starting synthesis. --run-vendor repeats that
preflight, then runs exactly one XSim flow followed by one OOC Vivado synthesis
if and only if XSim reaches its complete PASS marker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

for _key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"

from z100_feature_window_layout import FeatureLayout  # noqa: E402
from z100_native_output_layout import (  # noqa: E402
    assemble_scatter, scatter_site_words,
)

ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / "deployment/hardware/z100_2026/feature_banks_addressed_v1"
RTL = OWNED / "z100_feature_banks_addressed.sv"
TB = OWNED / "tb_z100_feature_banks_addressed.sv"
PACKER = ROOT / "deployment/hardware/z100_2026/native_output_packer_v2/z100_native_output_packer.sv"
V1_BANK = ROOT / "deployment/hardware/z100_2026/feature_banks_v1/z100_feature_banks.sv"
FEATURE_LAYOUT = ROOT / "tools/z100_feature_window_layout.py"
NATIVE_LAYOUT = ROOT / "tools/z100_native_output_layout.py"
VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
EXPECTED_PACKER_SHA256 = "c9ffe9ddef856ba93faf4285eb425605ba3a2da7e97e0c8932e78f91df35d4ae"
CHANNELS = (1, 3, 4, 16, 33, 64)
WIDTHS = (1, 16, 17, 20, 40)
HEIGHTS = (1, 2, 3)
SITES = 4
CAPACITY_SHAPE = (4, 256, 512)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path, paths: tuple[Path, ...]) -> dict[str, str]:
    return {str(path.relative_to(root)).replace("/", "\\"): sha(path)
            for path in paths}


def snapshot_sources(root: Path, paths: tuple[Path, ...], target: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    for path in paths:
        destination = target / path.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def deterministic_chw(channels: int, height: int, width: int, salt: int) -> bytes:
    size = channels * height * width
    return bytes((((i * 37 + (i >> 5) * 11 + salt * 83) ^ (i >> 11) ^ salt) & 255)
                 for i in range(size))


def input_vectors(layout: FeatureLayout, chw: bytes, case_index: int):
    """Yield packer input beats: 32 channel bytes per spatial site."""
    for group_base in range(0, layout.channels, 32):
        active = min(32, layout.channels - group_base)
        for y in range(layout.height):
            for x in range(layout.width):
                lanes = bytearray(32)
                for lane in range(32):
                    if lane < active:
                        channel = group_base + lane
                        lanes[lane] = chw[(channel * layout.height + y) * layout.width + x]
                    else:
                        lanes[lane] = (0xA5 + lane + x + y + case_index) & 255
                yield int.from_bytes(lanes, "little")


def configurations() -> list[tuple[int, int, int, bool]]:
    cases = [(channels, height, width, False)
             for channels in CHANNELS for width in WIDTHS for height in HEIGHTS]
    cases.append((*CAPACITY_SHAPE, True))
    return cases


def generate_fixtures(build: Path) -> dict:
    input_path = build / "feature_banks_input.hex"
    expected_path = build / "feature_banks_expected.hex"
    cases_path = build / "feature_banks_cases.hex"
    input_cursor = 0
    output_cursor = 0
    records = []
    inputs_total = 0
    words_total = 0
    bytes_total = 0
    matrix_sequence_checks = 0
    expected_word_capacity = 0
    with input_path.open("w", encoding="ascii", newline="\n") as input_file, \
            expected_path.open("w", encoding="ascii", newline="\n") as expected_file, \
            cases_path.open("w", encoding="ascii", newline="\n") as cases_file:
        for case_index, (channels, height, width, full_capacity) in enumerate(configurations()):
            layout = FeatureLayout(channels, height, width)
            if layout.words > layout.bank_depth:
                raise ValueError(f"Fixture exceeds bank capacity: {(channels, height, width)}")
            if full_capacity and layout.words != 8192:
                raise ValueError("Full-capacity fixture must contain exactly 8192 words")
            chw = deterministic_chw(channels, height, width, case_index + 17)
            packed = layout.pack(chw)  # Independent direct-CHW golden.
            scatter = list(scatter_site_words(layout, chw, SITES))
            if len(scatter) != layout.words:
                raise ValueError("Packer scatter word count differs from FeatureLayout")
            expected_addresses = []
            for group_base in range(0, channels, 32):
                active_channels = min(32, channels - group_base)
                subgroups = (active_channels + 3) // 4
                for row in range(height):
                    for xword in range(layout.x_words):
                        for subgroup in range(subgroups):
                            expected_addresses.append(
                                ((group_base // 4 + subgroup) * height + row) *
                                layout.x_words + xword)
            if len(expected_addresses) != layout.words:
                raise ValueError("Independent addressed-order formula has a coverage hole")
            seen = set()
            for expected_address, (address, data) in zip(expected_addresses, scatter):
                if address != expected_address or address in seen:
                    raise ValueError("Native scatter differs from independent group32,row,xword,subgroup order")
                if data != packed[address * 64:(address + 1) * 64]:
                    raise ValueError("Independent CHW golden differs from native output scatter")
                seen.add(address)
            if len(seen) != layout.words or assemble_scatter(layout, scatter) != packed:
                raise ValueError("Native output scatter contains an address hole or duplicate")
            matrix_sequence_checks += 1

            encoded = list(input_vectors(layout, chw, case_index))
            expected_inputs = ((channels + 31) // 32) * height * width
            if len(encoded) != expected_inputs:
                raise ValueError("Packer input vector count differs from direct CHW geometry")
            for value in encoded:
                input_file.write(f"{value:064x}\n")
            for address in range(layout.words):
                data = packed[address * 64:(address + 1) * 64]
                expected_file.write(f"{int.from_bytes(data, 'little'):0128x}\n")

            epoch = 0x1200 + case_index
            token_base = 0x01000000 + case_index * 0x100000
            token_count = ((channels + 31) // 32) * height * ((width + SITES - 1) // SITES)
            if token_base + token_count >= (1 << 32):
                raise ValueError("Packer token range exceeds the 32-bit field")
            # TB case-table bit fields: C[10:0],H[20:11],W[30:21],epoch[62:31],
            # token[94:63],input-start[126:95],input-count[146:127],
            # expected-start[178:147],word-count[192:179],pause[193],capacity[194].
            packed_case = (channels | (height << 11) | (width << 21) |
                           (epoch << 31) | (token_base << 63) |
                           (input_cursor << 95) | (expected_inputs << 127) |
                           (output_cursor << 147) | (layout.words << 179) |
                           (int(full_capacity) << 194) | (int(full_capacity) << 193))
            cases_file.write(f"{packed_case:064x}\n")
            records.append({
                "case": case_index,
                "shape_chw": [channels, height, width],
                "epoch": epoch,
                "token_base": token_base,
                "input_beats": expected_inputs,
                "output_words": layout.words,
                "active_chw_bytes": len(chw),
                "expected_packed_bytes": len(packed),
                "source_chw_sha256": hashlib.sha256(chw).hexdigest(),
                "full_capacity": full_capacity,
                "artificial_pause": full_capacity,
                "golden": "FeatureLayout.pack applied directly to deterministic CHW bytes",
            })
            input_cursor += expected_inputs
            output_cursor += layout.words
            inputs_total += expected_inputs
            words_total += layout.words
            bytes_total += layout.words * 64
            expected_word_capacity = max(expected_word_capacity, layout.words)

    if len(records) != 91 or len(records[:-1]) != 90:
        raise ValueError("Fixture matrix must have 90 requested shapes plus one capacity case")
    if records[-1]["shape_chw"] != list(CAPACITY_SHAPE) or words_total < 8192:
        raise ValueError("Full-capacity case is missing from the matrix")
    return {
        "cases": len(records), "matrix_cases": len(records) - 1,
        "matrix_channels": list(CHANNELS), "matrix_heights": list(HEIGHTS),
        "matrix_widths": list(WIDTHS), "packer_sites": SITES,
        "input_beats": inputs_total, "output_words": words_total,
        "readback_bytes": bytes_total, "full_capacity_shape_chw": list(CAPACITY_SHAPE),
        "full_capacity_words": 8192, "largest_case_words": expected_word_capacity,
        "native_scatter_sequence_checks": matrix_sequence_checks,
        "independent_golden": "FeatureLayout.pack(direct_chw_bytes)",
        "artificial_full_buffer_pause": "one forced 8-cycle consumer hold after both packer buffers fill",
        "case_records": records,
        "fixture_sha256": {
            input_path.name: sha(input_path), expected_path.name: sha(expected_path),
            cases_path.name: sha(cases_path),
        },
    }


def run_logged(name: str, command: list[str], cwd: Path, evidence: Path,
               result: dict, env: dict[str, str]) -> str:
    proc = subprocess.run(command, cwd=cwd, env=env, text=True,
                          encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (evidence / f"{name}.log").write_text(proc.stdout, encoding="utf-8")
    result["commands"].append({"name": name, "argv": command, "cwd": str(cwd),
                               "return_code": proc.returncode})
    if proc.returncode:
        raise RuntimeError(f"{name} failed with exit code {proc.returncode}")
    return proc.stdout


def run_xsim(build: Path, evidence: Path, result: dict, env: dict[str, str]) -> str:
    for binary in ("xvlog.bat", "xelab.bat", "xsim.bat"):
        if not (VIVADO_BIN / binary).is_file():
            raise FileNotFoundError(f"Vivado 2026.1 executable missing: {VIVADO_BIN / binary}")
    run_logged("xvlog", [str(VIVADO_BIN / "xvlog.bat"), "-sv",
                          str(PACKER), str(RTL), str(TB)], build, evidence, result, env)
    run_logged("xelab", [str(VIVADO_BIN / "xelab.bat"), "-mt", "2",
                          "tb_z100_feature_banks_addressed", "-s",
                          "feature_banks_addressed_sim"], build, evidence, result, env)
    sim = run_logged("xsim", [str(VIVADO_BIN / "xsim.bat"),
                               "feature_banks_addressed_sim", "-runall"],
                     build, evidence, result, env)
    return sim


def run_diagnostic_xsim(build: Path, evidence: Path, result: dict,
                        env: dict[str, str]) -> None:
    sim = run_xsim(build, evidence, result, env)
    stall_lines = re.findall(r"^FEATURE_BANKS_DIAG_STALL .*?$", sim, re.MULTILINE)
    watchdog_lines = re.findall(r"^FEATURE_BANKS_DIAG_WATCHDOG .*?$", sim, re.MULTILINE)
    phase_lines = re.findall(r"^FEATURE_BANKS_PHASE .*?$", sim, re.MULTILINE)
    fatal_lines = re.findall(r"^(?:Fatal|ERROR):.*?$", sim, re.MULTILINE)
    pass_lines = re.findall(r"^FEATURE_BANKS_ADDRESSED_PASS .*?$", sim, re.MULTILINE)
    result["diagnostic_xsim"] = {
        "scope": "bounded-wait localization only; no OOC synthesis attempted",
        "bounded_stalls": stall_lines,
        "watchdog_snapshots": watchdog_lines,
        "phase_trace": phase_lines,
        "fatal_lines": fatal_lines,
        "full_pass_marker_seen": len(pass_lines) == 1,
    }
    if stall_lines:
        result["diagnostic_xsim"]["status"] = "LOCALIZED_BOUNDED_WAIT_STALL"
        result["diagnostic_xsim"]["first_stall"] = stall_lines[0]
        result["status"] = "DIAGNOSTIC_LOCALIZED_BOUNDED_WAIT_STALL"
    elif watchdog_lines:
        result["diagnostic_xsim"]["status"] = "WATCHDOG_REACHED_WITH_STATE_SNAPSHOT"
        result["status"] = "DIAGNOSTIC_WATCHDOG_REACHED"
    elif len(pass_lines) == 1 and not fatal_lines:
        result["diagnostic_xsim"]["status"] = "FULL_XSIM_PASS_NO_OOC"
        result["status"] = "DIAGNOSTIC_FULL_XSIM_PASS_NO_OOC"
    else:
        result["diagnostic_xsim"]["status"] = "ASSERTION_OR_UNCLASSIFIED_STOP"
        result["status"] = "DIAGNOSTIC_ASSERTION_OR_UNCLASSIFIED_STOP"


def run_vendor(build: Path, evidence: Path, result: dict, env: dict[str, str]) -> None:
    if not (VIVADO_BIN / "vivado.bat").is_file():
        raise FileNotFoundError(f"Vivado 2026.1 executable missing: {VIVADO_BIN / 'vivado.bat'}")
    sim = run_xsim(build, evidence, result, env)
    marker = re.findall(
        r"^FEATURE_BANKS_ADDRESSED_PASS cases=(\d+) matrix_cases=(\d+) inputs=(\d+) "
        r"words=(\d+) requests=(\d+) responses=(\d+) bytes=(\d+) bubbles=(\d+) "
        r"input_stalls=(\d+) input_stability=(\d+) output_stalls=(\d+) "
        r"output_stability=(\d+) full_buffer_checks=(\d+) pause_cycles=(\d+) "
        r"errors=(\d+) e1=(\d+) e2=(\d+) e3=(\d+) e4=(\d+) e5=(\d+) e6=(\d+) "
        r"e7=(\d+) recovery=(\d+) capacity_words=(\d+) capacity_bytes=(\d+)$",
        sim, re.MULTILINE)
    if len(marker) != 1 or "Fatal:" in sim or "ERROR:" in sim:
        raise ValueError("One anchored feature-bank XSim PASS marker is required")
    values = list(map(int, marker[0]))
    (cases, matrix_cases, inputs, words, requests, responses, checked_bytes, bubbles,
     input_stalls, input_stability, output_stalls, output_stability, full_checks,
     pause_cycles, errors, e1, e2, e3, e4, e5, e6, e7, recovery, cap_words,
     cap_bytes) = values
    fixtures = result["fixtures"]
    if (cases != fixtures["cases"] or matrix_cases != fixtures["matrix_cases"] or
            inputs != fixtures["input_beats"] or words != fixtures["output_words"] or
            requests != responses or checked_bytes != fixtures["readback_bytes"] or
            min(bubbles, input_stalls, input_stability, output_stalls,
                output_stability, full_checks) <= 0 or pause_cycles != 8 or
            errors != 11 or [e1, e2, e3, e4, e5, e6, e7] != [1, 3, 1, 2, 1, 1, 2] or
            recovery != 3 or cap_words != 8192 or cap_bytes != 524288):
        raise ValueError("XSim coverage counts do not satisfy the fixed acceptance gates")
    result["simulation"] = {
        "status": "PASS", "cases": cases, "matrix_cases": matrix_cases,
        "input_beats": inputs, "packer_output_words": words,
        "read_requests": requests, "read_responses": responses,
        "readback_bytes_checked": checked_bytes,
        "input_bubble_cycles": bubbles, "input_stall_cycles": input_stalls,
        "input_stability_checks": input_stability,
        "output_stall_cycles_including_artificial_pause": output_stalls,
        "output_stability_checks": output_stability,
        "two_buffer_full_cycles_during_artificial_pause": full_checks,
        "forced_consumer_pause_cycles": pause_cycles,
        "errors": {"total": errors, "bad_config": e1, "address_order_epoch": e2,
                   "last": e3, "padding": e4, "early_commit": e5,
                   "extra_word": e6, "bad_read": e7},
        "cancel_reset_and_output_stall_recovery_checks": recovery,
        "full_capacity": {"words": cap_words, "bytes_read_back": cap_bytes},
    }

    tcl = build / "synth.tcl"
    tcl.write_text(f"""set_param general.maxThreads 2
if {{![string match 2026.1* [version -short]]}} {{error "Requires Vivado 2026.1"}}
read_verilog -sv {{{RTL.as_posix()}}}
synth_design -top z100_feature_banks_addressed -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none
create_clock -name feature_banks_addressed_clk -period 10.000 [get_ports clk]
report_utilization -file {{{(evidence / 'utilization.rpt').as_posix()}}}
report_utilization -hierarchical -file {{{(evidence / 'utilization_hierarchical.rpt').as_posix()}}}
write_checkpoint -force {{{(build / 'post_synth.dcp').as_posix()}}}
set lut [llength [get_cells -hier -filter {{REF_NAME =~ LUT*}}]]
set ff [llength [get_cells -hier -filter {{REF_NAME =~ FD*}}]]
set ram36 [llength [get_cells -hier -filter {{REF_NAME =~ RAMB36*}}]]
set ram18 [llength [get_cells -hier -filter {{REF_NAME =~ RAMB18*}}]]
set dsp [llength [get_cells -hier -filter {{REF_NAME =~ DSP*}}]]
set latch [llength [get_cells -hier -filter {{REF_NAME =~ LD*}}]]
set blackbox [llength [get_cells -hier -filter {{IS_BLACKBOX == 1}}]]
puts "FEATURE_BANKS_ADDRESSED_SYNTH lut=$lut ff=$ff ram36=$ram36 ram18=$ram18 dsp=$dsp latch=$latch blackbox=$blackbox"
exit
""", encoding="utf-8")
    synthesis = run_logged(
        "synth", [str(VIVADO_BIN / "vivado.bat"), "-mode", "batch",
                  "-log", str(evidence / "vivado.log"), "-journal",
                  str(evidence / "vivado.jou"), "-source", str(tcl)],
        build, evidence, result, env)
    synth_rows = re.findall(
        r"^FEATURE_BANKS_ADDRESSED_SYNTH lut=(\d+) ff=(\d+) ram36=(\d+) "
        r"ram18=(\d+) dsp=(\d+) latch=(\d+) blackbox=(\d+)$",
        synthesis, re.MULTILINE)
    if len(synth_rows) != 1:
        raise ValueError("OOC synthesis resource census is missing its anchored marker")
    lut, ff, ram36, ram18, dsp, latch, blackbox = map(int, synth_rows[0])
    bram36_equiv = ram36 + ram18 / 2
    resource_pass = (lut <= 12000 and ff <= 6000 and bram36_equiv == 128 and
                     dsp == 0 and latch == 0 and blackbox == 0)
    result["synthesis"] = {
        "status": "PASS_SCREEN" if resource_pass else "FAIL_SCREEN",
        "scope": "single-module out-of-context synthesis only; no place, route, board, or production integration",
        "lut": lut, "ff": ff, "ram36": ram36, "ram18": ram18,
        "bram36_equivalent": bram36_equiv, "dsp": dsp,
        "latch": latch, "blackbox": blackbox,
        "fixed_limits": {"lut_max": 12000, "ff_max": 6000,
                         "bram36_equivalent_exact": 128, "dsp": 0,
                         "latch": 0, "blackbox": 0},
        "post_synth_checkpoint": str((build / "post_synth.dcp").relative_to(ROOT)),
    }
    if not resource_pass:
        raise ValueError("OOC synthesis did not meet the fixed feature-bank resource screen")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--host-only", action="store_true")
    mode.add_argument("--diagnostic-xsim", action="store_true",
                      help="run bounded wait diagnostics with XSim only; never synthesize")
    mode.add_argument("--run-vendor", action="store_true",
                      help="after host PASS, run exactly one XSim then one OOC synthesis")
    args = parser.parse_args()

    sources = (Path(__file__).resolve(), RTL, TB, PACKER, V1_BANK,
               FEATURE_LAYOUT, NATIVE_LAYOUT)
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        parser.error(f"Required frozen or owned source is missing: {missing}")
    if sha(PACKER) != EXPECTED_PACKER_SHA256:
        parser.error("Frozen native output packer v2 hash mismatch")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/feature_banks_addressed_v1" / run_id
    build = ROOT / "deployment/build/z100_feature_banks_addressed_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    before = inventory(ROOT, sources)
    snapshot_sources(ROOT, sources, evidence / "source_snapshot")
    result = {
        "status": "RUNNING", "run_id": run_id, "phase": "HOST_PREFLIGHT",
        "source_sha256_before": before,
        "frozen_native_packer_expected_sha256": EXPECTED_PACKER_SHA256,
        "commands": [], "board_access": False, "routing_attempted": False,
        "bitstream_created": False, "firmware_or_production_modified": False,
        "production_integrated": False, "fps_claim": False,
    }
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        env[key] = "1"

    try:
        fixtures = generate_fixtures(build)
        result["fixtures"] = fixtures
        result["host_preflight"] = {
            "status": "PASS", "fixture_matrix_shapes": fixtures["matrix_cases"],
            "including_full_capacity_shape": fixtures["full_capacity_shape_chw"],
            "native_scatter_address_sequences_checked": fixtures["native_scatter_sequence_checks"],
            "direct_chw_golden_bytes": sum(row["expected_packed_bytes"]
                                            for row in fixtures["case_records"]),
            "packer_source_sha256": sha(PACKER),
            "independent_golden": "FeatureLayout.pack from direct deterministic CHW bytes",
        }
        result["phase"] = "HOST_PREFLIGHT_PASS"
        (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n",
                                               encoding="utf-8")
        if args.diagnostic_xsim:
            result["phase"] = "DIAGNOSTIC_XSIM_ONLY"
            run_diagnostic_xsim(build, evidence, result, env)
        elif args.run_vendor:
            result["phase"] = "XSIM_THEN_OOC_SYNTH"
            run_vendor(build, evidence, result, env)
            result["status"] = "PASS_PRIVATE_ADDRESSED_FEATURE_BANK_XSIM_OOC_ONLY"
        else:
            result["status"] = "PASS_HOST_PREFLIGHT_ONLY_VENDOR_NOT_RUN"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"

    after = inventory(ROOT, sources)
    result["source_sha256_after"] = after
    if before != after and result["status"].startswith("PASS_"):
        result["status"] = "FAILED_CLOSED"
        result["error"] = "A source dependency changed during validation"
    result["artifact_sha256"] = {
        str(path.relative_to(ROOT)).replace("/", "\\"): sha(path)
        for folder in (build, evidence)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "result.json"
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps({"status": result["status"],
                      "report": str(evidence / "result.json"),
                      "error": result.get("error")}), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
