"""Prepare and validate the mirror-wide-admission four-read feature-bank wrapper.

--host-only runs the direct-CHW fixture and dependency checks.
--run-vendor performs one XSim run, then one OOC synthesis only after XSim PASS.
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

ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / "deployment/hardware/z100_2026/feature_banks_4read_v4"
RTL = OWNED / "z100_feature_banks_4read.sv"
TB = OWNED / "tb_z100_feature_banks_4read_v4.sv"
BANK_RTL = ROOT / "deployment/hardware/z100_2026/feature_banks_addressed_v1/z100_feature_banks_addressed.sv"
FEATURE_LAYOUT = ROOT / "tools/z100_feature_window_layout.py"
BANK_RESULT = ROOT / "validation/board_z100/feature_banks_addressed_v1/20261023T183839.445577Z_9c859c25/result.json"
ROOT_REVIEW = ROOT / "validation/board_z100/acceleration_resource_review/20261023T184429.878019Z/addressed_reuse_review.json"
V1_OWNED = ROOT / "deployment/hardware/z100_2026/feature_banks_4read_v1"
V1_RTL = V1_OWNED / "z100_feature_banks_4read.sv"
V1_TB = V1_OWNED / "tb_z100_feature_banks_4read.sv"
V1_VALIDATOR = ROOT / "tools/validate_z100_feature_banks_4read.py"
V1_FAIL_REPORT = ROOT / "validation/board_z100/feature_banks_4read_v1/20261024T051747.374990Z_9fe23b3f/result.json"
V1_DIAG_REPORT = ROOT / "validation/board_z100/feature_banks_4read_diag_v1/20261024T052319.902382Z_f5d86376/result.json"
VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
EXPECTED_BANK_RTL_SHA256 = "62c30b0487a54edd6125affa492b3d79c2987203f8cba992fae6560051df656a"
EXPECTED_LAYOUT_SHA256 = "54ec4f90867ec9f043fae52270e3b46dc8caf996655abd546c9630333048231a"
EXPECTED_BANK_RESULT_SHA256 = "bf120ba4c98115fef893dc3bc93e5ea65cc612784887a141fd067dc1c7a0996b"
EXPECTED_ROOT_REVIEW_SHA256 = "06fb18a31d98de9699fea8bb07dcbee1201c11b4cbd1c6f7ccf3729d957a7eb7"
EXPECTED_V1_RTL_SHA256 = "a39aa15ddc256a796e78a54b1c71abee12801617a07e440738658f2a49e072bc"
EXPECTED_V1_TB_SHA256 = "580d7c9e2778ec88ffed9f30819f6242de90a02bac440ccd620737bea9894d69"
EXPECTED_V1_VALIDATOR_SHA256 = "56a2fff05734b04259e13284e2f851390e27ea1bf2384013722502ed690a2a3b"
EXPECTED_V1_FAIL_REPORT_SHA256 = "e8adab661ef2261774ef40dab7321b6ec857ecdea7da3c5a8ab98e1caf117581"
EXPECTED_V1_DIAG_REPORT_SHA256 = "ee599e75def3c4ce5b0f69afdde8e17d33e90ee09686468a578b8114f3910151"
CHANNELS = (1, 3, 4, 16, 33, 64)
WIDTHS = (1, 16, 17, 20, 40)
HEIGHTS = (1, 2, 3)
CAPACITY_SHAPE = (4, 256, 512)
MATRIX_CASES = 90
CASE_COUNT = 91
TOTAL_WORDS = 9920
TOTAL_READ_BYTES = TOTAL_WORDS * 256
FULL_CAPACITY_WORDS = 8192


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(paths: tuple[Path, ...]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)).replace("/", "\\"): sha(path) for path in paths}


def snapshot_sources(paths: tuple[Path, ...], target: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    for path in paths:
        destination = target / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def deterministic_chw(channels: int, height: int, width: int, salt: int) -> bytes:
    size = channels * height * width
    return bytes((((index * 37 + (index >> 5) * 11 + salt * 83) ^
                   (index >> 11) ^ salt) & 255) for index in range(size))


def load_order(layout: FeatureLayout) -> list[int]:
    """Independent group32,row,xword,subgroup ordering accepted by the child."""
    addresses: list[int] = []
    for group_base in range(0, layout.channels, 32):
        active_channels = min(32, layout.channels - group_base)
        subgroups = (active_channels + 3) // 4
        for row in range(layout.height):
            for xword in range(layout.x_words):
                for subgroup in range(subgroups):
                    addresses.append(
                        ((group_base // 4 + subgroup) * layout.height + row) *
                        layout.x_words + xword)
    return addresses


def fixture_cases() -> list[tuple[int, int, int, bool]]:
    rows = [(channels, height, width, False)
            for channels in CHANNELS for width in WIDTHS for height in HEIGHTS]
    rows.append((*CAPACITY_SHAPE, True))
    return rows


def generate_fixtures(build: Path) -> dict:
    case_path = build / "feature_banks_4read_cases.hex"
    load_words_path = build / "feature_banks_4read_load_words.hex"
    load_addresses_path = build / "feature_banks_4read_load_addresses.hex"
    expected_path = build / "feature_banks_4read_expected_words.hex"
    records = []
    load_cursor = 0
    expected_cursor = 0
    total_words = 0
    total_chw_bytes = 0
    direct_expected_bytes = 0
    checked_load_addresses = 0
    unique_port_address_checks = 0

    with (case_path.open("w", encoding="ascii", newline="\n") as case_file,
          load_words_path.open("w", encoding="ascii", newline="\n") as load_words_file,
          load_addresses_path.open("w", encoding="ascii", newline="\n") as load_addresses_file,
          expected_path.open("w", encoding="ascii", newline="\n") as expected_file):
        for case_index, (channels, height, width, is_capacity) in enumerate(fixture_cases()):
            layout = FeatureLayout(channels, height, width)
            if layout.words > layout.bank_depth:
                raise ValueError(f"Fixture exceeds the configured bank depth: {channels, height, width}")
            if is_capacity and layout.words != FULL_CAPACITY_WORDS:
                raise ValueError("The capacity case must use every one of the 8192 words")

            chw = deterministic_chw(channels, height, width, case_index + 29)
            packed = layout.pack(chw)
            if len(packed) != layout.words * 64:
                raise ValueError("FeatureLayout returned an unexpected packed length")
            addresses = load_order(layout)
            if (len(addresses) != layout.words or len(set(addresses)) != layout.words or
                    sorted(addresses) != list(range(layout.words))):
                raise ValueError("Independent write order has an address hole or duplicate")
            checked_load_addresses += len(addresses)

            for address in range(layout.words):
                word = packed[address * 64:(address + 1) * 64]
                expected_file_word = int.from_bytes(word, "little")
                expected_file.write(f"{expected_file_word:0128x}\n")
            for address in addresses:
                word = packed[address * 64:(address + 1) * 64]
                load_words_file.write(f"{int.from_bytes(word, 'little'):0128x}\n")
                load_addresses_file.write(f"{address:04x}\n")

            epoch = 0x4A00 + case_index
            # Case fields: C[10:0], H[20:11], W[30:21], epoch[62:31],
            # words[76:63], load_start[90:77], expected_start[104:91], full[105].
            packed_case = (channels | (height << 11) | (width << 21) |
                           (epoch << 31) | (layout.words << 63) |
                           (load_cursor << 77) | (expected_cursor << 91) |
                           (int(is_capacity) << 105))
            case_file.write(f"{packed_case:064x}\n")

            for bank in range(64):
                for port in range(4):
                    observed = {(request + port + bank * 11) % layout.words
                                for request in range(layout.words)}
                    if observed != set(range(layout.words)):
                        raise ValueError(f"Logical bank/port did not cover all addresses: {bank}/{port}")
                    unique_port_address_checks += layout.words
            if layout.words >= 4:
                for bank in range(64):
                    first = [(port + bank * 11) % layout.words for port in range(4)]
                    if len(set(first)) != 4:
                        raise ValueError(f"Four simultaneous ports alias at bank {bank}")

            records.append({
                "case": case_index,
                "shape_chw": [channels, height, width],
                "epoch": epoch,
                "words": layout.words,
                "full_capacity": is_capacity,
                "write_order": "independent group32,row,xword,subgroup formula",
                "golden": "FeatureLayout.pack applied directly to deterministic CHW bytes",
                "source_chw_sha256": hashlib.sha256(chw).hexdigest(),
                "packed_sha256": hashlib.sha256(packed).hexdigest(),
            })
            load_cursor += layout.words
            expected_cursor += layout.words
            total_words += layout.words
            total_chw_bytes += len(chw)
            direct_expected_bytes += len(packed)

    if len(records) != CASE_COUNT or len(records[:-1]) != MATRIX_CASES:
        raise ValueError("Expected 90 matrix cases and one full-capacity case")
    if total_words != TOTAL_WORDS or records[-1]["shape_chw"] != list(CAPACITY_SHAPE):
        raise ValueError("Fixture total or full-capacity shape differs from the fixed contract")
    return {
        "cases": len(records), "matrix_cases": len(records) - 1,
        "matrix_channels": list(CHANNELS), "matrix_heights": list(HEIGHTS),
        "matrix_widths": list(WIDTHS), "capacity_shape_chw": list(CAPACITY_SHAPE),
        "capacity_words": FULL_CAPACITY_WORDS, "capacity_bytes": FULL_CAPACITY_WORDS * 64,
        "total_configuration_words": total_words,
        "total_request_beats": total_words,
        "total_response_beats": total_words,
        "total_checked_logical_bytes": total_words * 256,
        "total_chw_input_bytes": total_chw_bytes,
        "total_packed_golden_bytes": direct_expected_bytes,
        "independent_load_address_checks": checked_load_addresses,
        "all_logical_port_address_visits": unique_port_address_checks,
        "active_ports_per_bank_per_request": 4,
        "port_mapping": "logical port 0/1 -> frozen copy A; logical port 2/3 -> frozen copy B",
        "case_records": records,
        "fixture_sha256": {
            case_path.name: sha(case_path),
            load_words_path.name: sha(load_words_path),
            load_addresses_path.name: sha(load_addresses_path),
            expected_path.name: sha(expected_path),
        },
    }


def verify_frozen_references() -> dict:
    if sha(BANK_RTL) != EXPECTED_BANK_RTL_SHA256:
        raise ValueError("Frozen addressed-bank RTL hash mismatch")
    if sha(FEATURE_LAYOUT) != EXPECTED_LAYOUT_SHA256:
        raise ValueError("Frozen FeatureLayout source hash mismatch")
    if sha(BANK_RESULT) != EXPECTED_BANK_RESULT_SHA256:
        raise ValueError("Frozen addressed-bank XSim/OOC report hash mismatch")
    if sha(ROOT_REVIEW) != EXPECTED_ROOT_REVIEW_SHA256:
        raise ValueError("Frozen root addressed-bank review hash mismatch")
    bank_result = json.loads(BANK_RESULT.read_text(encoding="utf-8"))
    review = json.loads(ROOT_REVIEW.read_text(encoding="utf-8"))
    if bank_result.get("status") != "PASS_PRIVATE_ADDRESSED_FEATURE_BANK_XSIM_OOC_ONLY":
        raise ValueError("Frozen addressed-bank result does not report the accepted XSim/OOC status")
    source_key = "deployment\\hardware\\z100_2026\\feature_banks_addressed_v1\\z100_feature_banks_addressed.sv"
    if bank_result.get("source_sha256_before", {}).get(source_key) != EXPECTED_BANK_RTL_SHA256:
        raise ValueError("Frozen bank result does not bind the expected child RTL hash")
    bank_fixtures = bank_result.get("fixtures", {})
    bank_simulation = bank_result.get("simulation", {})
    bank_synth = bank_result.get("synthesis", {})
    if (bank_fixtures.get("full_capacity_words") != FULL_CAPACITY_WORDS or
            bank_simulation.get("full_capacity", {}).get("bytes_read_back") != 524288 or
            bank_synth.get("bram36_equivalent") != 128 or bank_synth.get("dsp") != 0):
        raise ValueError("Frozen addressed-bank full-capacity/resource evidence is inconsistent")
    if (review.get("bank_report_sha256") != EXPECTED_BANK_RESULT_SHA256 or
            review.get("bank_full_capacity_readback_bytes") != 524288 or
            review.get("bank_bram36eq") != 128 or review.get("bank_dsp") != 0 or
            review.get("status") != "ROOT_ACCEPT_PRIVATE_ADDRESSED_BANK_AND_NEXT_WINDOW_REUSE_BOUNDED_ONLY"):
        raise ValueError("Frozen root review does not bind the accepted bank evidence")
    return {
        "addressed_bank_rtl_sha256": EXPECTED_BANK_RTL_SHA256,
        "addressed_bank_result_sha256": EXPECTED_BANK_RESULT_SHA256,
        "root_review_sha256": EXPECTED_ROOT_REVIEW_SHA256,
        "feature_layout_sha256": EXPECTED_LAYOUT_SHA256,
        "addressed_bank_status": bank_result["status"],
        "addressed_bank_full_capacity_readback_bytes": 524288,
        "addressed_bank_bram36_equivalent": 128,
        "addressed_bank_dsp": 0,
        "root_review_status": review["status"],
    }


def verify_v1_and_diagnostic_bindings() -> dict:
    expected = {
        V1_RTL: EXPECTED_V1_RTL_SHA256,
        V1_TB: EXPECTED_V1_TB_SHA256,
        V1_VALIDATOR: EXPECTED_V1_VALIDATOR_SHA256,
        V1_FAIL_REPORT: EXPECTED_V1_FAIL_REPORT_SHA256,
        V1_DIAG_REPORT: EXPECTED_V1_DIAG_REPORT_SHA256,
    }
    for path, digest in expected.items():
        if sha(path) != digest:
            raise ValueError(f"Frozen v1/diagnostic binding changed: {path}")
    failed = json.loads(V1_FAIL_REPORT.read_text(encoding="utf-8"))
    diag = json.loads(V1_DIAG_REPORT.read_text(encoding="utf-8"))
    if (failed.get("status") != "FAILED_CLOSED" or
            failed.get("error") != "ValueError: XSim did not emit exactly one complete 4-read-port PASS marker"):
        raise ValueError("Frozen v1 run is not the documented XSim failure")
    v1_key = "deployment\\hardware\\z100_2026\\feature_banks_4read_v1\\z100_feature_banks_4read.sv"
    if failed.get("source_sha256_before", {}).get(v1_key) != EXPECTED_V1_RTL_SHA256:
        raise ValueError("Frozen v1 failure does not bind its wrapper RTL")
    diag_hashes = diag.get("source_sha256_before", {})
    if (diag.get("prior_failure_report_sha256") != EXPECTED_V1_FAIL_REPORT_SHA256 or
            diag_hashes.get(v1_key) != EXPECTED_V1_RTL_SHA256 or
            diag.get("status") != "CAPTURED_POST_WRONG_EPOCH_DIVERGENCE"):
        raise ValueError("Frozen diagnostic run does not bind the documented v1 failure")
    snapshots = diag.get("diagnostic_snapshots", [])
    if (not any("phase=PREEDGE" in line and "req_epoch=7012" in line for line in snapshots) or
            not any("phase=POSTEDGE" in line and "req_epoch=7012" in line for line in snapshots)):
        raise ValueError("Frozen diagnostic report lacks the 7012 wrong-epoch snapshots")
    return {
        "v1_wrapper_sha256": EXPECTED_V1_RTL_SHA256,
        "v1_tb_sha256": EXPECTED_V1_TB_SHA256,
        "v1_validator_sha256": EXPECTED_V1_VALIDATOR_SHA256,
        "v1_failure_report_sha256": EXPECTED_V1_FAIL_REPORT_SHA256,
        "v1_diagnostic_report_sha256": EXPECTED_V1_DIAG_REPORT_SHA256,
        "v1_diagnostic_caveat": (
            "The preserved diagnostic snapshots cover the 7012 wrong-epoch request; "
            "the later 323076 ns fatal is the 7013 wrong-address probe. The old report "
            "status is retained unchanged and is not treated as proof of the 7013 state."
        ),
    }


def verify_static_closure() -> dict:
    source = RTL.read_text(encoding="utf-8")
    old_source = V1_RTL.read_text(encoding="utf-8")
    header_pattern = re.compile(
        r"module\s+z100_feature_banks_4read\s*#\s*\((.*?)\)\s*\((.*?)\);",
        re.S)
    new_header = header_pattern.search(source)
    old_header = header_pattern.search(old_source)
    if not new_header or not old_header:
        raise ValueError("Could not statically identify the frozen wrapper interface")
    normalize = lambda value: re.sub(r"\s+", "", value)
    if (normalize(new_header.group(1)) != normalize(old_header.group(1)) or
            normalize(new_header.group(2)) != normalize(old_header.group(2))):
        raise ValueError("v3 wrapper changed the frozen external interface")
    if len(re.findall(r"\bz100_feature_banks_addressed\s*#", source)) != 2:
        raise ValueError("v3 wrapper must contain exactly two frozen child instances")
    if len(re.findall(r"\.req_valid\(req_valid_i\)", source)) != 2:
        raise ValueError("both child copies must receive the same admitted request-valid")
    if len(re.findall(r"\.cancel\(child_cancel\)", source)) != 2:
        raise ValueError("both child copies must receive the common cancel")
    required = (
        "for (read_check_port = 0; read_check_port < 256;",
        "req_mask[read_check_port]",
        "req_addresses[read_check_port*ADDR_BITS +: ADDR_BITS]",
        "req_valid_i = req_valid && command_admission && !global_read_bad",
        "wire bad_read_fire = req_valid && req_ready && global_read_bad",
        "pending_words <= cfg_geometry_ok ? cfg_words_calc[13:0] : 14'b0",
        "active_words_q <= pending_words",
        "child_cancel = cancel || local_badread_pulse || mirror_fault_latched",
        "else if (mirror_mismatch)",
    )
    missing = [needle for needle in required if needle not in source]
    if missing:
        raise ValueError("v3 wrapper misses static admission/cancel invariant(s): " + repr(missing))
    if "!mirror_mismatch && req_ready_a && req_ready_b" not in source:
        raise ValueError("v3 wrapper must preserve the strict mirror mismatch ready gate")
    if not re.search(r"if\s*\(cfg_begin_i && cfg_begin_ready\)\s*begin\s*pending_words\s*<=", source, re.S):
        raise ValueError("pending geometry is not latched on the accepted begin command")
    if not re.search(r"else if\s*\(cfg_commit_i && cfg_commit_ready\)\s*begin\s*active_words_q\s*<=\s*pending_words", source):
        raise ValueError("active word count is not committed from the latched geometry")
    return {
        "external_interface_identical_to_v1": True,
        "frozen_children": 2,
        "common_request_valid_and_cancel": True,
        "masked_logical_addresses_checked": 256,
        "pending_geometry_latched_on_begin": True,
        "active_words_latched_on_commit": True,
        "bad_read_cancel_pulse_and_strict_mirror_fault": True,
    }


def run_logged(name: str, argv: list[str], cwd: Path,
               evidence: Path, result: dict, env: dict[str, str]) -> str:
    proc = subprocess.run(argv, cwd=cwd, env=env, text=True,
                          encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (evidence / f"{name}.log").write_text(proc.stdout, encoding="utf-8")
    result["commands"].append({"name": name, "argv": argv, "cwd": str(cwd),
                               "return_code": proc.returncode})
    if proc.returncode:
        raise RuntimeError(f"{name} failed with exit code {proc.returncode}")
    return proc.stdout


def run_xsim(build: Path, evidence: Path, result: dict, env: dict[str, str]) -> str:
    for binary in ("xvlog.bat", "xelab.bat", "xsim.bat"):
        if not (VIVADO_BIN / binary).is_file():
            raise FileNotFoundError(f"Vivado executable missing: {VIVADO_BIN / binary}")
    run_logged("xvlog", [str(VIVADO_BIN / "xvlog.bat"), "-sv",
                          str(BANK_RTL), str(RTL), str(TB)],
               build, evidence, result, env)
    run_logged("xelab", [str(VIVADO_BIN / "xelab.bat"), "-mt", "2",
                          "tb_z100_feature_banks_4read", "-s",
                          "feature_banks_4read_sim"],
               build, evidence, result, env)
    return run_logged("xsim", [str(VIVADO_BIN / "xsim.bat"),
                                "feature_banks_4read_sim", "-runall"],
                      build, evidence, result, env)


def run_vendor(build: Path, evidence: Path, result: dict, env: dict[str, str]) -> None:
    sim = run_xsim(build, evidence, result, env)
    marker = re.findall(
        r"^FEATURE_BANKS_4READ_V4_PASS cases=(\d+) writes=(\d+) requests=(\d+) "
        r"responses=(\d+) bytes=(\d+) cfg_read_rejects=(\d+) conflicts=(\d+) "
        r"cfg_bubbles=(\d+) "
        r"req_stalls=(\d+) req_stability=(\d+) out_stalls=(\d+) out_stability=(\d+) "
        r"ii1_burst=(\d+) errors=(\d+) e1=(\d+) e2=(\d+) e3=(\d+) e4=(\d+) "
        r"e5=(\d+) e6=(\d+) e7=(\d+) recoveries=(\d+) capacity_words=(\d+) "
        r"capacity_bytes=(\d+) global_bad_reads=(\d+) child_suppressed=(\d+) "
        r"flushed_copies=(\d+) masked_bad_accepted=(\d+)$", sim, re.MULTILINE)
    if len(marker) != 1 or re.search(r"^(?:Fatal|ERROR):", sim, re.MULTILINE):
        raise ValueError("XSim did not emit exactly one complete v3 4-read-port PASS marker")
    seam = re.findall(r"^MIRROR_CANCEL_SEAM_PASS immediate_public_block=1 suppressed_child_requests=1 registered_flush=1 sticky_until_cancel=1$", sim, re.M)
    if len(seam) != 1:
        raise ValueError("Registered mirror cancel seam coverage missing")
    result["mirror_cancel_seam"] = {"immediate_public_block": True, "suppressed_child_requests": True,
                                    "registered_flush": True, "sticky_until_external_cancel": True}
    if len(re.findall(r"^COMMAND_ADMISSION_V4_PASS conflict_subsets=22 held_cycles=66 unaccepted_begin_cycles=4$", sim, re.M)) != 1:
        raise ValueError("Missing independent valid/admission adversarial checks")
    result["admission_depth_checks"] = dict(conflict_subsets=22, held_cycles=66, unaccepted_begin_cycles=4)
    values = list(map(int, marker[0]))
    (cases, writes, requests, responses, checked_bytes, read_rejects, conflicts, bubbles,
     req_stalls, req_stability, out_stalls, out_stability, ii1_burst,
      errors, e1, e2, e3, e4, e5, e6, e7, recoveries, cap_words, cap_bytes,
      global_bad_reads, child_suppressed, flushed_copies, masked_bad_accepted) = values
    fixtures = result["fixtures"]
    if (cases != CASE_COUNT or writes != TOTAL_WORDS or requests != TOTAL_WORDS or
            responses != TOTAL_WORDS or checked_bytes != TOTAL_READ_BYTES or
            read_rejects != CASE_COUNT or conflicts != 1 or min(bubbles, req_stalls, req_stability,
            out_stalls, out_stability) <= 0 or ii1_burst < 32 or errors != 9 or
            [e1, e2, e3, e4, e5, e6, e7] != [1, 2, 1, 1, 1, 1, 2] or
            recoveries != 5 or cap_words != FULL_CAPACITY_WORDS or cap_bytes != 524288 or
            global_bad_reads != 2 or child_suppressed != 2 or flushed_copies != 2 or
            masked_bad_accepted != 1 or
            fixtures["total_configuration_words"] != writes):
        raise ValueError("XSim counts differ from the fixed coverage gates")
    result["simulation"] = {
        "status": "PASS",
        "cases": cases, "configuration_words": writes,
        "read_requests": requests, "read_responses": responses,
        "checked_logical_output_bytes": checked_bytes,
        "active_logical_ports_per_request": 256,
        "read_ports_per_physical_bank": 4,
        "read_during_load_rejections": read_rejects,
        "simultaneous_command_conflict_rejections": conflicts,
        "configuration_bubble_cycles": bubbles,
        "request_backpressure_cycles": req_stalls,
        "request_stability_checks": req_stability,
        "output_backpressure_cycles": out_stalls,
        "output_stability_checks": out_stability,
        "maximum_contiguous_II1_response_burst": ii1_burst,
        "errors": {"total": errors, "bad_config": e1, "bad_order_or_epoch": e2,
                   "bad_last": e3, "bad_padding": e4, "early_commit": e5,
                   "extra_word": e6, "bad_read": e7},
        "cancel_reset_mirror_fault_recovery_checks": recoveries,
        "global_bad_read_admissions": global_bad_reads,
        "both_child_requests_suppressed": child_suppressed,
        "both_physical_stores_flushed": flushed_copies,
        "masked_out_of_range_address_accepts": masked_bad_accepted,
        "full_capacity": {"words_per_bank": cap_words,
                           "logical_bytes_read": cap_bytes},
    }

    tcl = build / "synth.tcl"
    tcl.write_text(f"""set_param general.maxThreads 2
if {{![string match 2026.1* [version -short]]}} {{error "Requires Vivado 2026.1"}}
read_verilog -sv {{{BANK_RTL.as_posix()}}}
read_verilog -sv {{{RTL.as_posix()}}}
synth_design -top z100_feature_banks_4read -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none
create_clock -name feature_banks_4read_clk -period 10.000 [get_ports clk]
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
puts "FEATURE_BANKS_4READ_SYNTH lut=$lut ff=$ff ram36=$ram36 ram18=$ram18 dsp=$dsp latch=$latch blackbox=$blackbox"
exit
""", encoding="utf-8")
    synth = run_logged("synth", [str(VIVADO_BIN / "vivado.bat"), "-mode", "batch",
                                   "-log", str(evidence / "vivado.log"),
                                   "-journal", str(evidence / "vivado.jou"),
                                   "-source", str(tcl)], build, evidence, result, env)
    rows = re.findall(
        r"^FEATURE_BANKS_4READ_SYNTH lut=(\d+) ff=(\d+) ram36=(\d+) "
        r"ram18=(\d+) dsp=(\d+) latch=(\d+) blackbox=(\d+)$", synth, re.MULTILINE)
    if len(rows) != 1:
        raise ValueError("OOC synthesis did not emit one anchored resource census")
    lut, ff, ram36, ram18, dsp, latch, blackbox = map(int, rows[0])
    bram36_equiv = ram36 + ram18 / 2
    resource_pass = (bram36_equiv == 256 and dsp == 0 and lut <= 24000 and
                     ff <= 6000 and latch == 0 and blackbox == 0)
    result["synthesis"] = {
        "status": "PASS_SCREEN" if resource_pass else "FAIL_SCREEN",
        "scope": "one out-of-context synthesis only; no placement, routing, timing, or board validation",
        "slice_lut_census": lut, "ff_census": ff,
        "ram36": ram36, "ram18": ram18, "bram36_equivalent": bram36_equiv,
        "dsp": dsp, "latches": latch, "blackboxes": blackbox,
        "fixed_limits": {"bram36_equivalent_exact": 256, "dsp": 0,
                         "slice_lut_max": 24000, "ff_max": 6000,
                         "latch": 0, "blackbox": 0},
        "post_synthesis_checkpoint": str((build / "post_synth.dcp").relative_to(ROOT)),
    }
    if not resource_pass:
        raise ValueError("OOC synthesis failed the fixed 4-read-port resource screen")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--host-only", action="store_true")
    mode.add_argument("--run-vendor", action="store_true",
                      help="after host pass, run one XSim then one OOC synthesis")
    args = parser.parse_args()

    sources = (Path(__file__).resolve(), RTL, TB, BANK_RTL, FEATURE_LAYOUT,
               BANK_RESULT, ROOT_REVIEW, V1_RTL, V1_TB, V1_VALIDATOR,
               V1_FAIL_REPORT, V1_DIAG_REPORT)
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        parser.error("Required owned/frozen source is missing: " + ", ".join(missing))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/feature_banks_4read_v4" / run_id
    build = ROOT / "build" / ("fb4v4_" + run_id)
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    before = inventory(sources)
    snapshot_sources(sources, evidence / "source_snapshot")
    result = {
        "status": "RUNNING", "run_id": run_id, "phase": "HOST_PREFLIGHT",
        "source_sha256_before": before, "commands": [],
        "board_access": False, "routing_attempted": False,
        "bitstream_created": False, "production_integrated": False,
        "firmware_or_production_modified": False, "fps_claim": False,
        "scope": "private mirrored 4-read-port wrapper with mirror-wide bad-read admission; no board or timing claim",
        "fixed_resource_limits": {"bram36_equivalent_exact": 256, "dsp": 0,
                                  "slice_lut_max": 24000, "ff_max": 6000,
                                  "latch": 0, "blackbox": 0},
    }
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        env[key] = "1"

    try:
        result["frozen_references"] = verify_frozen_references()
        result["v1_and_failure_bindings"] = verify_v1_and_diagnostic_bindings()
        result["static_closure"] = verify_static_closure()
        result["fixtures"] = generate_fixtures(build)
        result["host_preflight"] = {
            "status": "PASS",
            "shape_cases": CASE_COUNT,
            "independent_CHW_golden": "FeatureLayout.pack(deterministic CHW bytes)",
            "full_capacity_words": FULL_CAPACITY_WORDS,
            "four_active_read_ports_per_bank": True,
            "global_masked_address_admission": "all 256 ports checked before shared child request-valid",
            "bad_read_semantics": "error7; both children suppressed then synchronously flushed",
            "configuration_atomicity_and_directed_error_vectors": "bound in testbench",
        }
        result["phase"] = "HOST_PREFLIGHT_PASS"
        (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n",
                                               encoding="utf-8")
        if args.run_vendor:
            result["phase"] = "XSIM_THEN_ONE_OOC_SYNTH"
            run_vendor(build, evidence, result, env)
            result["status"] = "PASS_PRIVATE_FOUR_READ_FEATURE_BANK_XSIM_OOC_ONLY"
        else:
            result["status"] = "PASS_HOST_PREFLIGHT_ONLY_VENDOR_NOT_RUN"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"

    after = inventory(sources)
    result["source_sha256_after"] = after
    if before != after and result["status"].startswith("PASS_"):
        result["status"] = "FAILED_CLOSED"
        result["error"] = "A bound source or frozen dependency changed during validation"
    artifacts = {}
    for folder in (build, evidence):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.name != "result.json":
                artifacts[str(path.relative_to(ROOT)).replace("/", "\\")] = sha(path)
    result["artifact_sha256"] = artifacts
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps({"status": result["status"],
                      "report": str(evidence / "result.json"),
                      "error": result.get("error")}), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
