"""Route the root-reviewed native MAC post-synthesis checkpoint at 100 MHz.

Default execution performs a source/report/checkpoint-only preflight. The
--route-100mhz flag authorizes one placement-and-route attempt; it never runs
XSim or synthesis and never edits the source checkpoint.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
RTL_DIR = ROOT / "deployment/hardware/z100_2026"
ROUTE_DIR = RTL_DIR / "native_mac_route_v1"
ROUTE_TCL = ROUTE_DIR / "route_existing_checkpoint.tcl"
ORIGINAL_DIR = ROOT / "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8"
ORIGINAL_RESULT = ORIGINAL_DIR / "result.json"
ROOT_REVIEW = ROOT / "validation/board_z100/acceleration_resource_review/20261023T173439.995978Z/native_mac_timing_ooc_review.json"
ORIGINAL_TCL = RTL_DIR / "native_mac_timing_v1/native_mac_timing_impl.tcl"
DCP = ROOT / "deployment/build/z100_native_mac_timing_v1/20261023T172941.408185Z_acf099d8/post_synth.dcp"
BUILD_ROOT = ROOT / "deployment/build/z100_native_mac_route_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/native_mac_route_v1"
SELF = Path(__file__).resolve()
PYTHON = ROOT / '.venv/Scripts/python.exe'
VIVADO_BIN = Path(r"C:\appload\2026.1\Vivado\bin")

ROOT_REVIEW_SHA256 = "41b269bf46289cd9ee6d52d86c9ff721cd723668c8f94a9a82e614c70c156a58"
REVIEWER_SHA256 = "feda2e8ec06c4a6257b2b6c74820a85744f28cf76fbc19feac14e2db9bee19de"
ORIGINAL_RESULT_SHA256 = "debb14f251b0b05e52a8148399273f70b08bd2c7d66e1ee71932bd250141ca01"
DCP_SHA256 = "1690bf41149405aaccf58bb8ca057ea98d88cf5d7dd66effa731856d2dd6d95b"

FROZEN_SOURCE_SHA256 = {
    "deployment/hardware/z100_2026/window_mac_v1/z100_window_mac.sv": "c2de472f539276da097e5ccd5bc7d44f2695dbff55ecb73458ea0105accbb643",
    "deployment/hardware/z100_2026/native_mac_timing_v1/z100_native_mac_timing_top.sv": "3c09e83320ce788400052e07cf50145782a7781072dbc42ef12578132f3146b1",
    "deployment/hardware/z100_2026/native_mac_timing_v1/tb_z100_native_mac_timing.sv": "8f26b042046899186a2351abe7d525bc9a6a75e6e74aca33c1bbd45b4f0284c8",
    "deployment/hardware/z100_2026/reuse_sync_fixture/sim_bufg.v": "c82537f3f4a6025e0f89fd263718b13fcdc52292f0e4fc1dbf7912a98f8e12af",
    "deployment/hardware/z100_2026/native_mac_timing_v1/native_mac_timing_constraints.xdc": "312250a15fee0eb126889bd1fec07ea093eb04d34911ee814bcc8a413f18d6b7",
    "deployment/hardware/z100_2026/native_mac_timing_v1/native_mac_timing_impl.tcl": "cdc2eb2a07344c058ca47b7b995d2cc54629a07421caea3205c8ac7c7df3a92f",
    "tools/validate_z100_native_mac_timing.py": "4a522256a5e7f2b1f256bc679f4165bde595fd2b1b64914ac94f18ef466fc07b",
}

ORIGINAL_ARTIFACT_SHA256 = {
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/check_timing_synth.rpt": "a3900e12e4624bbd85d42db72297441fbc04f9e90cfb15ebc81d5670ee15044a",
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/dsp48e1_synth_summary.txt": "a278c374f652f065307ef4c971b2f5bb55c3e189eba8647dd9aff0407a306a4f",
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/resources_synth.txt": "de4a462583c6394c6c68941fb3aae2f385e9d9466295407109eb529875b9604b",
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/synth_clock_reset_topology.txt": "69411f16748f26168fc7ae7d47a54a289e6527cc37e82ec06d4bba6951332671",
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/synth_critical.rpt": "10fe73e34f3f89818d81a60033425f04d608b43c840dbfa3c67a19cc804142b3",
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/synth_errors.rpt": "e7f2412e678d72c86f2b130a2517888702235b454617088560c6775426b3f91a",
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/synth_observability.txt": "a4f919e7658603e2ebcbf810c4e21ac5b9bfc33d8871264a04563b4e2e4ce84d",
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/timing_synth.rpt": "c7945c9f52ae6533570feeeb61f050ec478be78480098568e12fefcf8ebd3106",
    "validation/board_z100/native_mac_timing_v1/20261023T172941.408185Z_acf099d8/utilization_synth.rpt": "c2ddee81834721223aceda78f46a036bf4088c2f7bda204bae0efbe2d1b5f175",
}

RESOURCE_EXPECTED = {
    "lut": 11894,
    "ff": 6296,
    "dsp_total": 640,
    "dsp_multiply": 512,
    "dsp_none": 128,
    "bram36_equivalent": 28.5,
    "bufg": 1,
    "latches": 0,
    "blackboxes": 0,
}
CHECK_TIMING_CATEGORIES = (
    "no_clock", "constant_clock", "pulse_width_clock",
    "unconstrained_internal_endpoints", "no_input_delay", "no_output_delay",
    "multiple_clock", "generated_clocks", "loops", "partial_input_delay",
    "partial_output_delay", "latch_loops",
)
ROUTE_MARKER = re.compile(
    r"^NATIVE_MAC_ROUTE_PASS frequency_mhz=100 "
    r"setup_slack_ns=(-?\d+(?:\.\d+)?) hold_slack_ns=(-?\d+(?:\.\d+)?) "
    r"pulse_checks=(\d+) routable=(\d+) routed=(\d+) route_errors=(\d+) "
    r"lut=(\d+) ff=(\d+) dsp_total=(\d+) dsp_multiply=(\d+) dsp_none=(\d+) "
    r"bram36_equivalent=(\d+(?:\.\d+)?) bufg=(\d+) latches=(\d+) blackboxes=(\d+) "
    r"checkpoint_dsp_total=(\d+) placed_dsp_total=(\d+) check_timing_zero_categories=12\r?$",
    re.MULTILINE,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_check_timing(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    values: dict[str, int] = {}
    for category in CHECK_TIMING_CATEGORIES:
        matches = [int(value) for value in re.findall(
            rf"checking\s+{re.escape(category)}\s+\((\d+)\)", text)]
        require(bool(matches), f"{path.name}: missing check_timing row for {category}")
        require(len(set(matches)) == 1,
                f"{path.name}: repeated check_timing values disagree for {category}: {matches}")
        values[category] = matches[-1]
        require(values[category] == 0, f"{path.name}: {category} count is {values[category]}")
    return values


def parse_resource_text(path: Path) -> dict[str, float | int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"RESOURCES phase=\S+ lut=(\d+) ff=(\d+) dsp48e1=(\d+) dsp_total=(\d+) "
        r"ramb36=(\d+) ramb18=(\d+) bram36_equivalent=([0-9.]+) bufg=(\d+) latches=(\d+) blackboxes=(\d+)",
        text,
    )
    require(match is not None, f"Unrecognized resource report format: {path}")
    fields = match.groups()
    return {
        "lut": int(fields[0]), "ff": int(fields[1]), "dsp48e1": int(fields[2]),
        "dsp_total": int(fields[3]), "ramb36": int(fields[4]), "ramb18": int(fields[5]),
        "bram36_equivalent": float(fields[6]), "bufg": int(fields[7]),
        "latches": int(fields[8]), "blackboxes": int(fields[9]),
    }


def parse_dsp_summary(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    expected_keys = {
        "DSP48E1_TOTAL": "total", "USE_MULT_MULTIPLY": "multiply",
        "USE_MULT_NONE": "none", "USE_MULT_OTHER": "other",
    }
    parsed = {}
    for key, field in expected_keys.items():
        match = re.search(rf"^{key}\s+(\d+)\s*$", text, re.MULTILINE)
        require(match is not None, f"Missing {key} in {path}")
        parsed[field] = int(match.group(1))
    return parsed


def validate_resource_screen(resources: dict[str, float | int], dsp: dict[str, int], phase: str) -> None:
    require(int(resources["lut"]) <= 40000, f"{phase} LUT screen exceeded")
    require(int(resources["ff"]) <= 25000, f"{phase} FF screen exceeded")
    require(int(resources["dsp_total"]) == 640, f"{phase} DSP48E1 count changed")
    require(float(resources["bram36_equivalent"]) >= 28.0 and float(resources["bram36_equivalent"]) <= 40.0,
            f"{phase} BRAM36-equivalent count is outside 28..40")
    require(int(resources["bufg"]) == 1 and int(resources["latches"]) == 0 and int(resources["blackboxes"]) == 0,
            f"{phase} clock/latch/blackbox census changed")
    require(dsp == {"total": 640, "multiply": 512, "none": 128, "other": 0},
            f"{phase} DSP mode census changed: {dsp}")


def parse_drc(path: Path) -> dict[str, dict[str, object]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    require("REPORT SUMMARY" in text and "REPORT DETAILS" in text, "DRC summary/detail sections are missing")
    summary = text.split("REPORT SUMMARY", 1)[1].split("REPORT DETAILS", 1)[0]
    rows = re.findall(
        r"^\|\s*([A-Z][A-Z0-9]+-\d+)\s*\|\s*(Critical Warning|Warning|Error|Advisory)\s*\|[^|]*\|\s*(\d+)\s*\|",
        summary, re.MULTILINE,
    )
    result: dict[str, dict[str, object]] = {}
    for rule, severity, count in rows:
        require(rule not in result, f"Duplicate DRC summary row: {rule}")
        result[rule] = {"severity": severity, "count": int(count)}
    require(bool(result), "DRC summary contains no parsed rule rows")
    return result


def classify_drc(drc: dict[str, dict[str, object]]) -> dict[str, object]:
    expected_open = {
        "NSTD-1": ("Critical Warning", 1, "standalone fixture has no board I/O standard assignment"),
        "UCIO-1": ("Critical Warning", 1, "standalone fixture has no board pin locations"),
        "ZPS7-1": ("Warning", 1, "standalone fixture contains no PS7 block"),
    }
    open_unaccepted = []
    unexpected = []
    multiply_count = RESOURCE_EXPECTED["dsp_multiply"]
    for rule, item in sorted(drc.items()):
        severity, count = item["severity"], int(item["count"])
        if rule in expected_open:
            exp_severity, exp_count, reason = expected_open[rule]
            if severity != exp_severity or count != exp_count:
                unexpected.append({"rule": rule, **item, "reason": "expected standalone finding changed"})
            else:
                open_unaccepted.append({"rule": rule, **item, "reason": reason})
        elif rule == "DPIP-1":
            if severity != "Warning" or count > 2 * multiply_count:
                unexpected.append({"rule": rule, **item, "reason": "DSP input-pipeline finding exceeds frozen multiplier census"})
            else:
                open_unaccepted.append({"rule": rule, **item, "reason": "DSP A/B input pipeline setting; timing is reported independently"})
        elif rule == "DPOP-2":
            if severity != "Warning" or count > multiply_count:
                unexpected.append({"rule": rule, **item, "reason": "DSP output-pipeline finding exceeds frozen multiplier census"})
            else:
                open_unaccepted.append({"rule": rule, **item, "reason": "DSP MREG setting; timing is reported independently"})
        else:
            unexpected.append({"rule": rule, **item, "reason": "unreviewed DRC rule or severity"})
    return {
        "status": "UNEXPECTED_DRC" if unexpected else "OPEN_UNACCEPTED_STANDALONE_DRC",
        "open_unaccepted": open_unaccepted,
        "unexpected": unexpected,
        "board_signoff": False,
    }


def extract_helper_prefix(original_tcl: Path, build: Path) -> tuple[Path, str]:
    source = original_tcl.read_bytes()
    marker = b"proc main {frequency_mhz build_dir evidence_dir stage} {"
    offset = source.find(marker)
    require(offset >= 0 and source.find(marker, offset + 1) < 0, "Frozen implementation Tcl main boundary changed")
    prefix = source[:offset]
    for name in (b"proc require ", b"proc check_fixture ", b"proc screen_resources ",
                 b"proc write_dsp_census ", b"proc check_timing_slack "):
        require(name in prefix, f"Frozen helper prefix is missing {name.decode('ascii')}")
    require(b"proc main" not in prefix and b"main {*}$argv" not in prefix,
            "Helper snapshot must exclude main and the original Tcl footer")
    path = build / "frozen_native_mac_helper_prefix.tcl"
    path.write_bytes(prefix)
    return path, hashlib.sha256(prefix).hexdigest()


def validate_inputs() -> dict[str, object]:
    require(sha256(ROOT_REVIEW) == ROOT_REVIEW_SHA256, "Root OOC review SHA changed")
    require(sha256(ORIGINAL_RESULT) == ORIGINAL_RESULT_SHA256, "Original OOC result SHA changed")
    require(sha256(DCP) == DCP_SHA256, "Frozen post-synthesis DCP SHA changed")
    review = json_file(ROOT_REVIEW)
    original = json_file(ORIGINAL_RESULT)
    require(review.get("status") == "ROOT_REVIEW_NATIVE_MAC_TIMING_WRAPPER_XSIM_OOC_PASS_ROUTE_UNACCEPTED",
            "Root review does not authorize routing this OOC checkpoint")
    require(review.get("reviewer_sha256") == REVIEWER_SHA256, "Root reviewer digest differs from the pinned review")
    require(review.get("original_report_sha256") == ORIGINAL_RESULT_SHA256, "Root review does not bind the original result")
    require(review.get("dcp_sha256") == DCP_SHA256, "Root review does not bind this checkpoint")
    require(review.get("dcp", "").replace("\\", "/") == rel(DCP), "Root review points at a different checkpoint")
    require(review.get("source_count") == len(FROZEN_SOURCE_SHA256), "Root review source count changed")
    require(review.get("artifact_count") == 59, "Root review artifact count changed")
    require(review.get("resource_counts") == RESOURCE_EXPECTED, "Root review OOC resources differ from the frozen gate")
    require(review.get("all12_synth_clock_coverage_classes_zero") is True, "Root review lacks the 12-class clock check")
    require(review.get("simulation", {}).get("status") == "PASS" and review["simulation"].get("words") == 960,
            "Root review does not bind the numerical smoke pass")
    require(original.get("status") == "FAILED_CLOSED", "Original report changed from the immutable parser-failure result")
    require(original.get("error") == "ValueError: Vivado did not report a completed 100 MHz OOC synthesis census",
            "Original report failure cause changed")
    require(original.get("source_sha256") == FROZEN_SOURCE_SHA256 and
            original.get("source_sha256_after") == FROZEN_SOURCE_SHA256,
            "Original OOC result source hashes differ from the pinned source set")
    require(len(original.get("artifact_sha256", {})) == 59, "Original artifact inventory no longer has 59 entries")
    require(all(command.get("return_code") == 0 for command in original.get("commands", [])),
            "Original OOC/XSim run had a nonzero tool return code")
    require(original.get("simulation", {}).get("status") == "PASS", "Original numerical smoke pass is missing")

    current_source_hashes = {name: sha256(ROOT / name) for name in FROZEN_SOURCE_SHA256}
    require(current_source_hashes == FROZEN_SOURCE_SHA256, "One or more frozen native MAC sources changed")
    require(ROUTE_TCL.is_file(), "Missing checkpoint route Tcl")
    route_tcl = ROUTE_TCL.read_text(encoding="utf-8")
    xdc_path = RTL_DIR / "native_mac_timing_v1/native_mac_timing_constraints.xdc"
    xdc = xdc_path.read_text(encoding="utf-8")
    require("create_clock -name core_clk -period 10.000 [get_ports clk]" in xdc,
            "Source-bound clock constraint is not the reviewed 100 MHz period")
    require(not re.search(r"\b(set_false_path|set_multicycle_path|set_clock_groups|set_disable_timing)\b", xdc, re.I),
            "Source-bound timing constraints contain an exception")
    require("synth_design" not in route_tcl and "read_verilog" not in route_tcl,
            "Checkpoint route Tcl must not resynthesize or reread RTL")
    require("open_checkpoint" in route_tcl and "route_design" in route_tcl and "opt_design" in route_tcl,
            "Checkpoint route Tcl is missing the checkpoint-only implementation stages")

    for name, expected in ORIGINAL_ARTIFACT_SHA256.items():
        path = ROOT / name
        require(path.is_file() and sha256(path) == expected, f"Bound original OOC artifact changed: {name}")
    report_dir = ORIGINAL_DIR
    synth_critical = report_dir / "synth_critical.rpt"
    synth_errors = report_dir / "synth_errors.rpt"
    for path in (synth_critical, synth_errors):
        meaningful = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                      if line.strip() and not line.lstrip().startswith("#")]
        require(not meaningful, f"Original synthesis message report is not clean: {path.name}")
    check_timing = validate_check_timing(report_dir / "check_timing_synth.rpt")
    topology = (report_dir / "synth_clock_reset_topology.txt").read_text(encoding="utf-8")
    require("CLOCK core_clk PERIOD_NS 10.0" in topology and "BUFG_COUNT 1" in topology and
            "RESET_ASYNC_REG_COUNT 2" in topology, "Original OOC clock/reset topology differs")
    resources = parse_resource_text(report_dir / "resources_synth.txt")
    dsp = parse_dsp_summary(report_dir / "dsp48e1_synth_summary.txt")
    validate_resource_screen(resources, dsp, "frozen OOC checkpoint")
    observability = (report_dir / "synth_observability.txt").read_text(encoding="utf-8")
    for marker in ("BLACKBOX_COUNT 0", "SERIAL_DATA_WIDTH 32; SCANNED_LANES 32; CORE_DATA_WIDTH 1024",
                   "SERIAL_OVERFLOW_SCANNED_LANES 32; CORE_OVERFLOW_WIDTH 32",
                   "DSP_TOTAL 640; DSP_MULTIPLY 512; DSP_NONE 128"):
        require(marker in observability, f"OOC observability report lacks {marker}")

    bound_hashes = {
        rel(ROOT_REVIEW): sha256(ROOT_REVIEW),
        rel(ORIGINAL_RESULT): sha256(ORIGINAL_RESULT),
        rel(DCP): sha256(DCP),
        **{name: current_source_hashes[name] for name in current_source_hashes},
        rel(ROUTE_TCL): sha256(ROUTE_TCL),
        rel(SELF): sha256(SELF),
        **{name: sha256(ROOT / name) for name in ORIGINAL_ARTIFACT_SHA256},
    }
    return {
        "review": review,
        "original": original,
        "source_sha256": current_source_hashes,
        "bound_input_sha256": bound_hashes,
        "original_artifact_sha256": ORIGINAL_ARTIFACT_SHA256,
        "original_synth_resources": resources,
        "original_synth_dsp": dsp,
        "original_check_timing": check_timing,
    }


def write_source_snapshot(evidence: Path) -> None:
    source_files = [ROOT / name for name in FROZEN_SOURCE_SHA256]
    source_files.extend((ROOT_REVIEW, ORIGINAL_RESULT, ROUTE_TCL, SELF))
    snapshot = evidence / "source_snapshot"
    for path in source_files:
        target = snapshot / rel(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def run_route(command: list[str], build: Path, evidence: Path, result: dict) -> str:
    completed = subprocess.run(
        subprocess.list2cmdline(command), cwd=build, shell=True,
        env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    output = completed.stdout
    (evidence / "vivado_route.log").write_text(output, encoding="utf-8")
    result["commands"].append({"name": "vivado_route_100mhz", "args": command,
                               "return_code": completed.returncode})
    if completed.returncode != 0:
        raise RuntimeError(f"Vivado route process returned {completed.returncode}")
    return output


def artifact_hashes(evidence: Path, build: Path) -> dict[str, str]:
    entries = {}
    for folder in (evidence, build):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.name not in {"result.json", "launch.json"}:
                entries[rel(path)] = sha256(path)
    return entries


def validate_routed_outputs(evidence: Path, build: Path, vivado_output: str) -> dict[str, object]:
    matches = ROUTE_MARKER.findall(vivado_output)
    require(len(matches) == 1, f"Expected exactly one anchored emitted route-pass marker, found {len(matches)}")
    fields = matches[0]
    setup_slack, hold_slack = float(fields[0]), float(fields[1])
    pulse_checks, routable, routed, route_errors = map(int, fields[2:6])
    lut, ff, dsp, multiply, none = map(int, fields[6:11])
    bram = float(fields[11])
    bufg, latches, blackboxes, checkpoint_dsp, placed_dsp = map(int, fields[12:17])
    require(setup_slack >= 0.0 and hold_slack >= 0.0 and pulse_checks >= 3,
            "Routed setup/hold/pulse-width timing screen failed")
    require(routable > 0 and routable == routed and route_errors == 0,
            "Vivado route status has no nets, unrouted nets, or route errors")
    require(lut <= 40000 and ff <= 25000 and dsp == 640 and multiply == 512 and none == 128,
            "Routed LUT/FF/DSP resource screen changed")
    require(28.0 <= bram <= 40.0 and bufg == 1 and latches == 0 and blackboxes == 0,
            "Routed BRAM/BUFG/latch/blackbox screen changed")
    require(checkpoint_dsp == 640 and placed_dsp == 640, "Checkpoint or placed DSP count changed")

    checked_categories = {}
    phase_resources = {}
    phase_dsp = {}
    for phase in ("checkpoint", "placed", "routed"):
        checked_categories[phase] = validate_check_timing(evidence / f"check_timing_{phase}.rpt")
        phase_resources[phase] = parse_resource_text(evidence / f"resources_{phase}.txt")
        phase_dsp[phase] = parse_dsp_summary(evidence / f"dsp48e1_{phase}_summary.txt")
        validate_resource_screen(phase_resources[phase], phase_dsp[phase], phase)
    require((build / "post_place.dcp").is_file() and (build / "routed.dcp").is_file(),
            "Placed or routed checkpoint is missing")

    drc_review = classify_drc(parse_drc(evidence / "drc_routed.rpt"))
    require(not drc_review["unexpected"], f"Unexpected DRC findings: {drc_review['unexpected']}")
    for filename in ("checkpoint_critical.rpt", "checkpoint_errors.rpt", "placed_critical.rpt", "placed_errors.rpt",
                     "routed_critical.rpt", "routed_errors.rpt"):
        path = evidence / filename
        require(path.is_file(), f"Missing critical/error message report: {filename}")
        meaningful = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                      if line.strip() and not line.lstrip().startswith("#")]
        require(not meaningful, f"Critical warning/error messages reported in {filename}: {meaningful[:3]}")

    route_status = (evidence / "route_status.rpt").read_text(encoding="utf-8", errors="replace")
    require(re.search(rf"# of routable nets\.+\s*:\s*{routable}\b", route_status) is not None,
            "Route report and marker disagree on routable nets")
    require(re.search(rf"# of fully routed nets\.+\s*:\s*{routed}\b", route_status) is not None,
            "Route report and marker disagree on routed nets")
    require(re.search(rf"# of nets with routing errors\.+\s*:\s*{route_errors}\b", route_status) is not None,
            "Route report and marker disagree on routing errors")

    return {
        "status": "PASS_100MHZ_ROUTE_TIMING_RESOURCE_DRC_OPEN_UNACCEPTED",
        "frequency_mhz": 100,
        "period_ns": 10.0,
        "higher_frequency_attempted": False,
        "setup_slack_ns": setup_slack,
        "hold_slack_ns": hold_slack,
        "pulse_width_checks": pulse_checks,
        "routable_nets": routable,
        "fully_routed_nets": routed,
        "route_errors": route_errors,
        "resources": {"lut": lut, "ff": ff, "dsp_total": dsp, "dsp_multiply": multiply,
                      "dsp_none": none, "bram36_equivalent": bram, "bufg": bufg,
                      "latches": latches, "blackboxes": blackboxes},
        "drc_review": drc_review,
        "check_timing_zero_categories": checked_categories,
        "phase_resources": phase_resources,
        "phase_dsp_census": phase_dsp,
        "checkpoint": rel(DCP),
        "placed_checkpoint": rel(build / "post_place.dcp"),
        "routed_checkpoint": rel(build / "routed.dcp"),
        "reports": {name: rel(evidence / name) for name in (
            "check_timing_checkpoint.rpt", "check_timing_placed.rpt", "check_timing_routed.rpt",
            "checkpoint_clock_reset_topology.txt", "placed_clock_reset_topology.txt",
            "routed_clock_reset_topology.txt", "timing_checkpoint.rpt", "timing_placed.rpt",
            "timing_routed.rpt", "all_setup_max_routed.rpt", "all_hold_min_routed.rpt",
            "pulse_width_routed.rpt", "timing_slack_routed.txt", "route_status.rpt",
            "drc_routed.rpt", "clock_networks.rpt", "resources_checkpoint.txt",
            "resources_placed.txt", "resources_routed.txt", "utilization_checkpoint.rpt",
            "utilization_placed.rpt", "utilization_routed.rpt", "utilization_hierarchical_routed.rpt",
            "dsp48e1_checkpoint.tsv", "dsp48e1_placed.tsv", "dsp48e1_routed.tsv",
            "dsp48e1_checkpoint_summary.txt", "dsp48e1_placed_summary.txt",
            "dsp48e1_routed_summary.txt", "checkpoint_critical.rpt", "checkpoint_errors.rpt",
            "placed_critical.rpt", "placed_errors.rpt", "routed_critical.rpt", "routed_errors.rpt",
        )},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-100mhz", action="store_true",
                        help="Run one 100 MHz implementation attempt from the frozen post_synth.dcp")
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    result: dict[str, object] = {
        "status": "RUNNING",
        "run_id": run_id,
        "scope": "single 100 MHz place-and-route attempt from root-reviewed frozen post_synth.dcp; no XSim, resynthesis, board or production writes",
        "route_attempts": 0,
        "board_access": False,
        "production_integrated": False,
        "clock_scope": {"frequency_mhz": 100, "period_ns": 10.0, "higher_frequency_attempted": False},
        "commands": [],
    }
    (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    try:
        require(Path(sys.executable).resolve() == PYTHON.resolve(), f"Use pinned Python interpreter {PYTHON}")
        evidence_binding = validate_inputs()
        helper_path, helper_sha256 = extract_helper_prefix(ORIGINAL_TCL, build)
        write_source_snapshot(evidence)
        source_hashes_before = {
            rel(path): sha256(path) for path in (ROUTE_TCL, SELF, *(ROOT / name for name in FROZEN_SOURCE_SHA256))
        }
        bound_hashes_before = evidence_binding["bound_input_sha256"]
        helper_sha256_file = sha256(helper_path)
        require(helper_sha256_file == helper_sha256, "Generated frozen helper prefix hash changed")
        result["bindings"] = {
            "root_review": {"path": rel(ROOT_REVIEW), "sha256": ROOT_REVIEW_SHA256,
                            "reviewer_sha256": REVIEWER_SHA256},
            "original_result": {"path": rel(ORIGINAL_RESULT), "sha256": ORIGINAL_RESULT_SHA256,
                                "preserved_status": "FAILED_CLOSED_ROOT_REVIEWED_OOC_PASS"},
            "frozen_checkpoint": {"path": rel(DCP), "sha256": DCP_SHA256},
            "frozen_source_sha256": evidence_binding["source_sha256"],
            "original_ooc_artifact_sha256": evidence_binding["original_artifact_sha256"],
            "helper_prefix_sha256": helper_sha256,
            "source_sha256": source_hashes_before,
            "bound_input_sha256": bound_hashes_before,
        }
        result["source_snapshot"] = rel(evidence / "source_snapshot")
        result["helper_prefix_snapshot"] = rel(helper_path)
        result["preflight"] = {
            "status": "PASS",
            "original_ooc_resources": evidence_binding["original_synth_resources"],
            "original_ooc_dsp": evidence_binding["original_synth_dsp"],
            "original_ooc_check_timing_zero_categories": evidence_binding["original_check_timing"],
            "tools_planned": ["vivado.bat -mode batch; open frozen post_synth.dcp; opt/place/physopt/route"],
            "synthesis": "not invoked",
            "xsim": "not invoked",
            "constraints": "inherited from the hash-bound checkpoint; original 10.000 ns clock and 0/1 ns I/O delays",
        }

        if args.route_100mhz:
            vivado = VIVADO_BIN / "vivado.bat"
            require(vivado.is_file(), f"Missing Vivado executable {vivado}")
            command = [str(vivado), "-mode", "batch", "-log", str(evidence / "vivado.log"),
                       "-journal", str(evidence / "vivado.jou"), "-source", str(ROUTE_TCL),
                       "-tclargs", str(DCP), str(build), str(evidence), str(helper_path),
                       str(RTL_DIR / "native_mac_timing_v1/native_mac_timing_constraints.xdc")]
            result["route_attempts"] = 1
            vivado_output = run_route(command, build, evidence, result)
            route_result = validate_routed_outputs(evidence, build, vivado_output)
            result["route"] = route_result
            result["status"] = route_result["status"]
        else:
            result["status"] = "PASS_NATIVE_MAC_ROUTE_HOST_PREFLIGHT_VENDOR_NOT_RUN"

        source_hashes_after = {
            rel(path): sha256(path) for path in (ROUTE_TCL, SELF, *(ROOT / name for name in FROZEN_SOURCE_SHA256))
        }
        require(source_hashes_after == source_hashes_before, "Source-bound route inputs changed during this run")
        bound_hashes_after = {name: sha256(ROOT / name) if (ROOT / name).is_file() else None
                              for name in bound_hashes_before}
        require(bound_hashes_after == bound_hashes_before, "A bound OOC review/report/checkpoint/artifact changed during route")
        require(sha256(helper_path) == helper_sha256, "Frozen Tcl helper prefix changed during route")
        result["source_sha256_after"] = source_hashes_after
        result["bound_input_sha256_after"] = bound_hashes_after
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result.setdefault("source_sha256_after", {
            rel(path): sha256(path) for path in (ROUTE_TCL, SELF, *(ROOT / name for name in FROZEN_SOURCE_SHA256))
            if path.is_file()
        })
        if "bindings" in result:
            result["bound_input_sha256_after"] = {
                name: sha256(ROOT / name) if (ROOT / name).is_file() else None
                for name in result["bindings"].get("bound_input_sha256", {})
            }
    result["artifact_sha256"] = artifact_hashes(evidence, build)
    report = evidence / "result.json"
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(report),
                      "error": result.get("error")}, ensure_ascii=False))
    return 0 if str(result["status"]).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
