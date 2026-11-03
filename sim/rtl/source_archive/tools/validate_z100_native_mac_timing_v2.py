"""Prepare and validate native-window MAC fixture v2 with registered monitors.

Default mode performs host-only source/timing-contract/reference preflight.
The 100 MHz implementation mode runs one XSim smoke followed by one Vivado
implementation attempt. Outputs are written only to the v2 build/evidence tree.
"""
from __future__ import annotations

import argparse
import ast
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
FIXTURE_DIR = RTL_DIR / "native_mac_timing_v2"
BASELINE_FIXTURE_DIR = RTL_DIR / "native_mac_timing_v1"
CORE_RTL = RTL_DIR / "window_mac_v1/z100_window_mac.sv"
TOP_RTL = FIXTURE_DIR / "z100_native_mac_timing_top_v2.sv"
TB_RTL = FIXTURE_DIR / "tb_z100_native_mac_timing_v2.sv"
SIM_BUFG = RTL_DIR / "reuse_sync_fixture/sim_bufg.v"
XDC = FIXTURE_DIR / "native_mac_timing_constraints_v2.xdc"
IMPL_TCL = FIXTURE_DIR / "native_mac_timing_impl_v2.tcl"
BASELINE_TOP_RTL = BASELINE_FIXTURE_DIR / "z100_native_mac_timing_top.sv"
BASELINE_XDC = BASELINE_FIXTURE_DIR / "native_mac_timing_constraints.xdc"
BASELINE_TCL = BASELINE_FIXTURE_DIR / "native_mac_timing_impl.tcl"
SELF = Path(__file__).resolve()
BUILD_ROOT = ROOT / "deployment/build/z100_native_mac_timing_v2"
EVIDENCE_ROOT = ROOT / "validation/board_z100/native_mac_timing_v2"
PYTHON = ROOT / '.venv/Scripts/python.exe'
VIVADO_BIN = Path(r"C:\appload\2026.1\Vivado\bin")
CORE_SHA256 = "c2de472f539276da097e5ccd5bc7d44f2695dbff55ecb73458ea0105accbb643"
SIM_BUFG_SHA256 = "c82537f3f4a6025e0f89fd263718b13fcdc52292f0e4fc1dbf7912a98f8e12af"
BASELINE_TOP_SHA256 = "3c09e83320ce788400052e07cf50145782a7781072dbc42ef12578132f3146b1"
BASELINE_XDC_SHA256 = "312250a15fee0eb126889bd1fec07ea093eb04d34911ee814bcc8a413f18d6b7"
SMOKE_GROUPS = (3, 4, 6, 9)
FULL_GROUPS = (9, 36, 576, 1024)
LANES = (16, 32, 32, 32)
SITES = (4, 3, 4, 4)
EXPECTED_SMOKE = {
    "words": 960,
    "runs": 8,
    "weight_groups": sum(SMOKE_GROUPS),
    "bias_words": 4,
    "activation_groups": 2 * sum(SMOKE_GROUPS),
}
CHECK_TIMING_CATEGORIES = (
    "no_clock", "constant_clock", "pulse_width_clock",
    "unconstrained_internal_endpoints", "no_input_delay", "no_output_delay",
    "multiple_clock", "generated_clocks", "loops", "partial_input_delay",
    "partial_output_delay", "latch_loops",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def signed32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def weight_byte(shape: int, group: int, tap: int, lane: int) -> int:
    if lane == 0:
        return 1 + (group & 7) + tap * 2 + shape
    if lane == 1:
        return -1 - (group & 7) - tap * 2 - shape
    value = ((group & 0xFF) ^ ((group >> 8) & 0x07) ^
             (lane & 0xFF) ^ (tap & 0x0F) ^ shape)
    return value - 256 if value & 0x80 else value


def activation_byte(shape: int, replay: int, group: int, tap: int, site: int) -> int:
    group_mix = (group & 0x3F) ^ (((group >> 6) & 0x07) << 3) ^ ((group >> 8) & 0x07)
    tap_mix = ((tap & 0x07) << 3) | (tap & 0x07)
    site_mix = ((site & 0x03) << 4) | (site & 0x0F)
    run_mix = ((replay & 1) << 5) | (shape << 3) | 0b101
    return 1 + (group_mix ^ tap_mix ^ site_mix ^ run_mix)


def bias_word(shape: int, lane: int) -> int:
    if lane == 0:
        return 0x7FFFFFDF
    if lane == 1:
        return signed32(0x80000020)
    return ((lane * 37 + shape * 101) & 2047) - 1024


def token_for(shape: int, replay: int) -> int:
    return 0x4E4D0001 + shape * 2 + replay


def encode_word(token: int, data: int, overflow: bool, site: int,
                lane: int, lanes: int, last: bool) -> int:
    value = token & 0xFFFFFFFF
    value = (value << 32) | (data & 0xFFFFFFFF)
    value = (value << 1) | int(overflow)
    value = (value << 2) | site
    value = (value << 5) | lane
    value = (value << 6) | lanes
    value = (value << 1) | int(last)
    if not 0 <= value < (1 << 79):
        raise ValueError("serialized expected word exceeds its 79-bit interface")
    return value


def build_reference(groups_by_shape: tuple[int, ...]) -> tuple[list[int], dict]:
    expected: list[int] = []
    overflow_count = 0
    nonzero_count = 0
    saturation_lanes: set[tuple[int, int]] = set()
    run_summaries = []
    for shape, groups in enumerate(groups_by_shape):
        for replay in range(2):
            token = token_for(shape, replay)
            run_overflows = 0
            run_nonzero = 0
            for site in range(SITES[shape]):
                for lane in range(32):
                    raw = 0
                    if lane < LANES[shape]:
                        raw = bias_word(shape, lane)
                        for group in range(groups):
                            for tap in range(4):
                                raw += (activation_byte(shape, replay, group, tap, site) *
                                        weight_byte(shape, group, tap, lane))
                    if not -(1 << 32) <= raw <= (1 << 32) - 1:
                        raise ValueError(f"shape {shape} replay {replay} site {site} lane {lane} exceeds signed 33-bit accumulation")
                    overflow = raw < -(1 << 31) or raw > (1 << 31) - 1
                    clipped = min((1 << 31) - 1, max(-(1 << 31), raw))
                    data = clipped & 0xFFFFFFFF
                    if data != 0:
                        run_nonzero += 1
                    if overflow:
                        run_overflows += 1
                        saturation_lanes.add((shape, lane))
                    expected.append(encode_word(
                        token=token,
                        data=data,
                        overflow=overflow,
                        site=site,
                        lane=lane,
                        lanes=LANES[shape],
                        last=(site == SITES[shape] - 1 and lane == 31),
                    ))
            overflow_count += run_overflows
            nonzero_count += run_nonzero
            run_summaries.append({
                "shape": shape,
                "replay": replay,
                "groups": groups,
                "lanes": LANES[shape],
                "sites": SITES[shape],
                "token": token,
                "serialized_words": SITES[shape] * 32,
                "overflow_words": run_overflows,
                "nonzero_words": run_nonzero,
            })
    summary = {
        "groups_by_shape": list(groups_by_shape),
        "lanes_by_shape": list(LANES),
        "sites_by_shape": list(SITES),
        "runs": len(run_summaries),
        "serialized_words": len(expected),
        "overflow_words": overflow_count,
        "nonzero_words": nonzero_count,
        "saturation_shape_lanes": sorted([list(v) for v in saturation_lanes]),
        "reference": "independent host signed-64 direct sums over four tap lanes and resident group weights; signed-33 range check; INT32 saturation and flags",
        "run_details": run_summaries,
    }
    return expected, summary


def check_source_contract() -> dict:
    required = (CORE_RTL, TOP_RTL, TB_RTL, SIM_BUFG, XDC, IMPL_TCL,
                BASELINE_TOP_RTL, BASELINE_XDC, BASELINE_TCL, SELF)
    missing = [rel(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing fixture sources: {missing}")
    hashes = {rel(path): sha256(path) for path in required}
    if hashes[rel(CORE_RTL)] != CORE_SHA256:
        raise ValueError("Frozen native MAC source hash differs from the pinned component")
    if hashes[rel(SIM_BUFG)] != SIM_BUFG_SHA256:
        raise ValueError("Frozen simulation-only BUFG model hash differs from the pinned primitive stub")
    if hashes[rel(BASELINE_TOP_RTL)] != BASELINE_TOP_SHA256:
        raise ValueError("Read-only v1 top snapshot differs from the pinned routed timing fixture")
    if hashes[rel(BASELINE_XDC)] != BASELINE_XDC_SHA256:
        raise ValueError("Read-only v1 constraints differ from the pinned 100 MHz envelope")

    top = TOP_RTL.read_text(encoding="utf-8")
    baseline_top = BASELINE_TOP_RTL.read_text(encoding="utf-8")
    tb = TB_RTL.read_text(encoding="utf-8")
    xdc = XDC.read_text(encoding="utf-8")
    tcl = IMPL_TCL.read_text(encoding="utf-8")
    baseline_xdc = BASELINE_XDC.read_text(encoding="utf-8")
    for marker in (
        "module z100_native_mac_timing_top_v2", "BUFG clock_buffer", "reset_meta", "reset_local", "FAST_SMOKE",
        "make_weight_byte", "make_activation_byte", "make_bias_word",
        "out_data[(scan_lane * 32) +: 32]", "out_overflow[scan_lane]",
        "monitor_token", "monitor_lanes", "monitor_last",
        "module scope", "monitor_observation_stage", "ONE_CYCLE_OBSERVATION_DELAY",
    ):
        if marker == "module scope":
            continue
        if marker == "ONE_CYCLE_OBSERVATION_DELAY":
            if "one-cycle observation delay" not in top.lower():
                raise ValueError("Top header must document the one-cycle monitor observation delay")
            continue
        if marker not in top:
            raise ValueError(f"Top is missing required structural marker {marker!r}")
    for marker in (
        "group_index[7:0] ^ {5'd0, group_index[10:8]}",
        "lane_index[7:0] ^ {4'd0, tap_index[3:0]} ^ {6'd0, shape}",
        "((lane_index * 37 + shape * 101) & 2047) - 1024",
        "wire final_output_lane = scan_lane == 5'd31",
        "wire serial_handshake = serial_valid && serial_ready",
        "registered_status <= {",
        "out_valid, serial_valid, serial_handshake, 1'b0",
    ):
        if marker not in top:
            raise ValueError(f"Top stimulus/observability contract lacks {marker!r}")
    if "%" in top:
        raise ValueError("Timing fixture stimulus must avoid modulo operators in the registered DSP input generators")
    if top.count('(* ASYNC_REG = "TRUE" *)') != 2:
        raise ValueError("Fixture must contain exactly two marked sampled-reset stages")
    if "repeat (6) @(posedge clk)" not in tb:
        raise ValueError("Smoke bench must hold external reset low for at least two core clocks")
    if "expected_serial.hex" not in tb or "!== expected_serial[expected_read]" not in tb:
        raise ValueError("Smoke bench must compare each serialized output against the independent host reference")
    if "NATIVE_MAC_TIMING_V2_RESET_FLUSH_PASS" not in tb or "monitor observation stage retained stale outputs across reset" not in tb:
        raise ValueError("Smoke bench must check the all-output reset flush after live traffic")
    if "was_stalled" not in tb or "serialized MAC output changed during backpressure" not in tb:
        raise ValueError("Smoke bench must check monitor data stability under backpressure")

    # The original controller block stays byte-identical. The serializer stays
    # byte-identical apart from its internal status sampling using unretimed
    # handshake signals instead of feeding delayed monitor pins back inside.
    def section(source: str, start: str, end: str) -> str:
        first = source.find(start)
        last = source.find(end, first + len(start))
        if first < 0 or last < 0:
            raise ValueError(f"Could not isolate source contract section beginning {start!r}")
        return source[first:last]

    baseline_controller = section(baseline_top, "always @(posedge core_clk) begin : controller", "    reg [31:0] ready_lfsr")
    v2_controller = section(top, "always @(posedge core_clk) begin : controller", "    reg [31:0] ready_lfsr")
    if baseline_controller != v2_controller:
        raise ValueError("v2 changed the original controller logic")
    baseline_serializer = section(baseline_top, "always @(posedge core_clk) begin : output_serializer", "endmodule")
    v2_serializer = section(top, "always @(posedge core_clk) begin : output_serializer", "endmodule")
    v2_serializer = v2_serializer.replace(
        "out_valid, serial_valid, serial_handshake, 1'b0",
        "out_valid, monitor_valid, monitor_ready, 1'b0",
    )
    if baseline_serializer != v2_serializer:
        raise ValueError("v2 changed the original serializer beyond internal raw-status sampling")

    observation_start = top.find("always @(posedge core_clk) begin : monitor_observation_stage")
    observation_end = top.find("always @(posedge core_clk) begin : output_serializer", observation_start)
    if observation_start < 0 or observation_end < 0:
        raise ValueError("Missing single external monitor observation stage")
    observation = top[observation_start:observation_end]
    output_sources = {
        "monitor_valid": "serial_valid",
        "monitor_ready": "serial_handshake",
        "monitor_token": "serial_token",
        "monitor_data": "serial_data",
        "monitor_overflow": "serial_overflow",
        "monitor_site": "serial_site",
        "monitor_lane": "serial_lane",
        "monitor_lanes": "serial_lanes",
        "monitor_last": "serial_last",
        "monitor_status": "registered_status",
    }
    for output, source in output_sources.items():
        if len(re.findall(rf"\b{output}\s*<=", observation)) != 2:
            raise ValueError(f"{output} must be reset and captured in the same observation stage")
        if not re.search(rf"\b{output}\s*<=\s*{source}\s*;", observation):
            raise ValueError(f"{output} is not aligned to its internal source {source}")
    if "assign monitor_" in top:
        raise ValueError("Monitor outputs must be registered, not combinationally assigned")
    if re.search(r"registered_status\s*<=\s*\{[^}]*monitor_(?:valid|ready)", top, re.S):
        raise ValueError("Internal status dependencies must use raw serial signals, not delayed monitors")

    normalized_xdc = "\n".join(line.strip() for line in xdc.splitlines() if line.strip() and not line.lstrip().startswith("#"))
    normalized_baseline_xdc = "\n".join(line.strip() for line in baseline_xdc.splitlines() if line.strip() and not line.lstrip().startswith("#"))
    if normalized_xdc != normalized_baseline_xdc:
        raise ValueError("v2 must preserve the frozen 100 MHz clock and 0/1 ns I/O constraints")
    for required_line in (
        "create_clock -name core_clk -period 10.000 [get_ports clk]",
        "set_input_delay -clock [get_clocks core_clk] -min 0.000 [get_ports rst_n]",
        "set_input_delay -clock [get_clocks core_clk] -max 1.000 [get_ports rst_n]",
        "set_output_delay -clock [get_clocks core_clk] -min 0.000 $fixture_outputs",
        "set_output_delay -clock [get_clocks core_clk] -max 1.000 $fixture_outputs",
    ):
        if required_line not in normalized_xdc:
            raise ValueError(f"Timing constraints lack required exact constraint: {required_line}")
    if re.search(r"\b(set_false_path|set_multicycle_path|set_clock_groups|set_disable_timing)\b", xdc + tcl, re.IGNORECASE):
        raise ValueError("Timing fixture contains a false-path, multicycle, or disable-timing exception")
    if "frequency_mhz == 100" not in tcl or "general.maxThreads 2" not in tcl:
        raise ValueError("Implementation Tcl must remain limited to 100 MHz and two threads")
    if "USE_MULT_MULTIPLY 512" in tcl or "total == 640 && $mult == 512 && $none == 128" not in tcl:
        raise ValueError("Implementation Tcl does not enforce the exact 512 MULTIPLY + 128 NONE DSP census")
    if "z100_native_mac_timing_top_v2" not in tcl or "MONITOR_OUTPUTS_REGISTERED 1" not in tcl:
        raise ValueError("Implementation Tcl does not target the v2 registered monitor top")
    if "collect_timing_slack" not in tcl or "NATIVE_MAC_TIMING_V2_ROUTE_DATA" not in tcl:
        raise ValueError("Implementation Tcl must collect detailed timing artifacts before its final gate")
    if "report_drc" not in tcl or "routed.dcp" not in tcl:
        raise ValueError("Implementation Tcl must save routed DRC and DCP evidence before timing gating")
    if "opt_design" not in tcl or "route_design" not in tcl or str(SIM_BUFG) in tcl:
        raise ValueError("Implementation Tcl must preserve the route path and exclude the simulation-only BUFG stub")
    return hashes


def write_source_snapshot(evidence: Path, paths: tuple[Path, ...]) -> None:
    snapshot = evidence / "source_snapshot"
    for path in paths:
        target = snapshot / rel(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def run_logged(name: str, command: list[str], build: Path,
               evidence: Path, env: dict[str, str], result: dict,
               allow_nonzero: bool = False) -> tuple[str, int]:
    completed = subprocess.run(
        subprocess.list2cmdline(command),
        cwd=build,
        env=env,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = completed.stdout
    (evidence / f"{name}.log").write_text(output, encoding="utf-8")
    result["commands"].append({"name": name, "args": command, "return_code": completed.returncode})
    if completed.returncode and not allow_nonzero:
        raise RuntimeError(f"{name} returned {completed.returncode}")
    return output, completed.returncode


def artifact_hashes(evidence: Path, build: Path) -> dict[str, str]:
    entries = {}
    for folder in (evidence, build):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.name not in {"result.json", "launch.json"}:
                entries[rel(path)] = sha256(path)
    return entries


def validate_check_timing(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    values: dict[str, int] = {}
    for category in CHECK_TIMING_CATEGORIES:
        matches = [int(value) for value in re.findall(
            rf"checking\s+{re.escape(category)}\s+\((\d+)\)", text)]
        if not matches or len(set(matches)) != 1 or matches[0] != 0:
            raise ValueError(f"{path.name}: {category} clock-check counts are missing, inconsistent, or nonzero: {matches}")
        values[category] = 0
    return values


def parse_resource_text(path: Path) -> dict[str, float | int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"RESOURCES phase=\S+ lut=(\d+) ff=(\d+) dsp48e1=(\d+) dsp_total=(\d+) "
        r"ramb36=(\d+) ramb18=(\d+) bram36_equivalent=([0-9.]+) bufg=(\d+) latches=(\d+) blackboxes=(\d+)", text)
    if match is None:
        raise ValueError(f"Unrecognized resource report: {path}")
    values = match.groups()
    return {
        "lut": int(values[0]), "ff": int(values[1]), "dsp48e1": int(values[2]),
        "dsp_total": int(values[3]), "ramb36": int(values[4]), "ramb18": int(values[5]),
        "bram36_equivalent": float(values[6]), "bufg": int(values[7]),
        "latches": int(values[8]), "blackboxes": int(values[9]),
    }


def parse_dsp_summary(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    expected = {"DSP48E1_TOTAL": "total", "USE_MULT_MULTIPLY": "multiply",
                "USE_MULT_NONE": "none", "USE_MULT_OTHER": "other"}
    parsed = {}
    for key, field in expected.items():
        match = re.search(rf"^{key}\s+(\d+)\s*$", text, re.MULTILINE)
        if match is None:
            raise ValueError(f"Missing {key} in {path}")
        parsed[field] = int(match.group(1))
    return parsed


def validate_resource_screen(resources: dict[str, float | int], dsp: dict[str, int], phase: str) -> None:
    if int(resources["lut"]) > 40000 or int(resources["ff"]) > 25000:
        raise ValueError(f"{phase} LUT/FF screen exceeded: {resources}")
    if dsp != {"total": 640, "multiply": 512, "none": 128, "other": 0}:
        raise ValueError(f"{phase} DSP census changed: {dsp}")
    if int(resources["dsp_total"]) != 640:
        raise ValueError(f"{phase} DSP48E1 count changed")
    if not 28.0 <= float(resources["bram36_equivalent"]) <= 40.0:
        raise ValueError(f"{phase} BRAM36-equivalent count outside 28..40")
    if (int(resources["bufg"]) != 1 or int(resources["latches"]) != 0 or
            int(resources["blackboxes"]) != 0):
        raise ValueError(f"{phase} BUFG/latch/blackbox census changed: {resources}")


def parse_route_status(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    keys = {
        "routable": r"# of routable nets\.+\s*:\s*(\d+)",
        "routed": r"# of fully routed nets\.+\s*:\s*(\d+)",
        "errors": r"# of nets with routing errors\.+\s*:\s*(\d+)",
    }
    parsed = {}
    for key, pattern in keys.items():
        match = re.search(pattern, text)
        if match is None:
            raise ValueError(f"Route status report lacks {key} count")
        parsed[key] = int(match.group(1))
    return parsed


def parse_drc(path: Path) -> dict[str, dict[str, object]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    summary_match = re.search(
        r"(?ms)^1\. REPORT SUMMARY\s*\n-+\s*\n(.*?)"
        r"(?=^2\. REPORT DETAILS\s*\n-+\s*$)",
        text,
    )
    if summary_match is None:
        raise ValueError("Routed DRC report lacks its numbered summary/details sections")
    summary = summary_match.group(1)
    rows = re.findall(
        r"^\|\s*([A-Z][A-Z0-9]+-\d+)\s*\|\s*(Critical Warning|Warning|Error|Advisory)\s*\|[^|]*\|\s*(\d+)\s*\|",
        summary, re.MULTILINE,
    )
    result: dict[str, dict[str, object]] = {}
    for rule, severity, count in rows:
        if rule in result:
            raise ValueError(f"Duplicate DRC summary row: {rule}")
        result[rule] = {"severity": severity, "count": int(count)}
    if not result:
        raise ValueError("Routed DRC summary contains no parsed rule rows")
    return result


def classify_drc(drc: dict[str, dict[str, object]]) -> dict[str, object]:
    expected_open = {
        "NSTD-1": ("Critical Warning", 1, "standalone fixture has no board I/O standard assignment"),
        "UCIO-1": ("Critical Warning", 1, "standalone fixture has no board pin locations"),
        "ZPS7-1": ("Warning", 1, "standalone fixture contains no PS7 block"),
    }
    opened = []
    unexpected = []
    for rule, item in sorted(drc.items()):
        severity, count = item["severity"], int(item["count"])
        if rule in expected_open:
            exp_severity, exp_count, reason = expected_open[rule]
            if severity == exp_severity and count == exp_count:
                opened.append({"rule": rule, **item, "reason": reason})
            else:
                unexpected.append({"rule": rule, **item, "reason": "expected standalone finding changed"})
        elif rule == "DPIP-1":
            if severity == "Warning" and 0 < count <= 2 * 512:
                opened.append({"rule": rule, **item, "reason": "DSP A/B input pipeline warning; timing is reported independently"})
            else:
                unexpected.append({"rule": rule, **item, "reason": "DSP input-pipeline finding exceeds frozen census"})
        elif rule == "DPOP-2":
            if severity == "Warning" and 0 < count <= 512:
                opened.append({"rule": rule, **item, "reason": "DSP MREG warning; timing is reported independently"})
            else:
                unexpected.append({"rule": rule, **item, "reason": "DSP output-pipeline finding exceeds frozen census"})
        else:
            unexpected.append({"rule": rule, **item, "reason": "unreviewed DRC rule or severity"})
    return {"status": "UNEXPECTED_DRC" if unexpected else "OPEN_UNACCEPTED_STANDALONE_DRC",
            "open_unaccepted": opened, "unexpected": unexpected, "board_signoff": False}


ROUTE_DATA_RE = re.compile(
    r"^NATIVE_MAC_TIMING_V2_ROUTE_DATA frequency_mhz=100 "
    r"setup_slack_ns=(-?\d+(?:\.\d+)?) hold_slack_ns=(-?\d+(?:\.\d+)?) "
    r"pulse_checks=(\d+) pulse_nonnegative=([01]) routable=(\d+) routed=(\d+) route_errors=(\d+) "
    r"lut=(\d+) ff=(\d+) dsp_total=(\d+) dsp_multiply=(\d+) dsp_none=(\d+) "
    r"bram36_equivalent=(\d+(?:\.\d+)?) bufg=(\d+) latches=(\d+) blackboxes=(\d+) "
    r"check_timing_zero_categories=12\s*$", re.MULTILINE,
)


def validate_implementation_outputs(evidence: Path, build: Path, output: str,
                                    return_code: int) -> dict[str, object]:
    markers = ROUTE_DATA_RE.findall(output)
    if len(markers) != 1:
        raise ValueError(f"Expected exactly one emitted route-data marker, found {len(markers)}")
    fields = markers[0]
    setup, hold = float(fields[0]), float(fields[1])
    pulse_checks, pulse_nonnegative = int(fields[2]), fields[3] == "1"
    routable, routed, route_errors = map(int, fields[4:7])
    lut, ff, dsp, multiply, none = map(int, fields[7:12])
    bram = float(fields[12])
    bufg, latches, blackboxes = map(int, fields[13:16])

    required_files = (
        "check_timing_synth.rpt", "check_timing_placed.rpt", "check_timing_routed.rpt",
        "synth_clock_reset_topology.txt", "placed_clock_reset_topology.txt", "routed_clock_reset_topology.txt",
        "resources_synth.txt", "resources_placed.txt", "resources_routed.txt",
        "dsp48e1_synth.tsv", "dsp48e1_placed.tsv", "dsp48e1_routed.tsv",
        "dsp48e1_synth_summary.txt", "dsp48e1_placed_summary.txt", "dsp48e1_routed_summary.txt",
        "utilization_synth.rpt", "utilization_placed.rpt", "utilization_routed.rpt",
        "utilization_hierarchical_routed.rpt", "timing_synth.rpt", "timing_placed.rpt",
        "timing_routed.rpt", "all_setup_max_routed.rpt", "all_hold_min_routed.rpt",
        "pulse_width_routed.rpt", "timing_slack_routed.txt", "route_status.rpt",
        "drc_routed.rpt", "clock_networks.rpt", "synth_critical.rpt", "synth_errors.rpt",
        "placed_critical.rpt", "placed_errors.rpt", "routed_critical.rpt", "routed_errors.rpt",
    )
    missing = [name for name in required_files if not (evidence / name).is_file()]
    if missing:
        raise ValueError(f"Completed-route evidence is missing files: {missing}")
    required_checkpoints = ("post_synth.dcp", "post_place.dcp", "routed.dcp")
    missing = [name for name in required_checkpoints if not (build / name).is_file()]
    if missing:
        raise ValueError(f"Completed-route checkpoint evidence is missing files: {missing}")

    check_timing = {phase: validate_check_timing(evidence / f"check_timing_{phase}.rpt")
                    for phase in ("synth", "placed", "routed")}
    phase_resources = {}
    phase_dsp = {}
    for phase in ("synth", "placed", "routed"):
        phase_resources[phase] = parse_resource_text(evidence / f"resources_{phase}.txt")
        phase_dsp[phase] = parse_dsp_summary(evidence / f"dsp48e1_{phase}_summary.txt")
        validate_resource_screen(phase_resources[phase], phase_dsp[phase], phase)

    route_status = parse_route_status(evidence / "route_status.rpt")
    if route_status != {"routable": routable, "routed": routed, "errors": route_errors}:
        raise ValueError(f"Route marker/status report disagree: marker={routable}/{routed}/{route_errors} report={route_status}")
    route_resources = phase_resources["routed"]
    route_dsp = phase_dsp["routed"]
    if (lut, ff, dsp, multiply, none, bram, bufg, latches, blackboxes) != (
            int(route_resources["lut"]), int(route_resources["ff"]), int(route_resources["dsp_total"]),
            route_dsp["multiply"], route_dsp["none"], float(route_resources["bram36_equivalent"]),
            int(route_resources["bufg"]), int(route_resources["latches"]), int(route_resources["blackboxes"])):
        raise ValueError("Route marker and emitted routed resource reports disagree")

    slack_line = (evidence / "timing_slack_routed.txt").read_text(encoding="utf-8", errors="replace")
    slack_match = re.search(
        r"TIMING phase=routed setup_slack_ns=(-?\d+(?:\.\d+)?) hold_slack_ns=(-?\d+(?:\.\d+)?) "
        r"pulse_checks=(\d+) pulse_min_slack_nonnegative=([01])", slack_line)
    if slack_match is None:
        raise ValueError("Detailed routed timing slack file is malformed")
    if (abs(float(slack_match.group(1)) - setup) > 0.001 or
            abs(float(slack_match.group(2)) - hold) > 0.001 or
            int(slack_match.group(3)) != pulse_checks or
            (slack_match.group(4) == "1") != pulse_nonnegative):
        raise ValueError("Route marker and detailed timing slack report disagree")

    timing_text = (evidence / "timing_routed.rpt").read_text(encoding="utf-8", errors="replace")
    timing_section = timing_text.split("| Design Timing Summary", 1)[-1].split("| Clock Summary", 1)[0]
    summary_rows = re.findall(
        r"(?m)^\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+"
        r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+"
        r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s*$", timing_section)
    if len(summary_rows) != 1:
        raise ValueError("Routed timing summary has no unique design timing row")
    summary = summary_rows[0]
    if abs(float(summary[0]) - setup) > 0.001 or abs(float(summary[4]) - hold) > 0.001:
        raise ValueError("Routed timing summary and route data disagree")

    pulse_text = (evidence / "pulse_width_routed.rpt").read_text(encoding="utf-8", errors="replace")
    pulse_values = []
    for line in pulse_text.splitlines():
        match = re.search(r"^\s*(Min Period|Low Pulse Width|High Pulse Width)\s+.*\s+(-?\d+\.\d+)\s+\S+\s+\S+\s*$", line)
        if match:
            pulse_values.append({"check": match.group(1), "slack_ns": float(match.group(2))})
    if len(pulse_values) != pulse_checks or pulse_checks < 3:
        raise ValueError(f"Pulse width report check count differs from route marker: {len(pulse_values)} vs {pulse_checks}")
    if (min(item["slack_ns"] for item in pulse_values) >= 0.0) != pulse_nonnegative:
        raise ValueError("Pulse width report and route marker disagree")

    drc = classify_drc(parse_drc(evidence / "drc_routed.rpt"))
    if drc["unexpected"]:
        raise ValueError(f"Unexpected routed DRC findings: {drc['unexpected']}")
    for filename in ("synth_critical.rpt", "synth_errors.rpt", "placed_critical.rpt", "placed_errors.rpt",
                     "routed_critical.rpt", "routed_errors.rpt"):
        meaningful = [line.strip() for line in (evidence / filename).read_text(encoding="utf-8", errors="replace").splitlines()
                      if line.strip() and not line.lstrip().startswith("#")]
        if meaningful:
            raise ValueError(f"Unexpected synthesis/implementation messages in {filename}: {meaningful[:3]}")

    gate_failures = []
    if setup < 0.0:
        gate_failures.append(f"setup slack {setup} ns")
    if hold < 0.0:
        gate_failures.append(f"hold slack {hold} ns")
    if pulse_checks < 3 or not pulse_nonnegative:
        gate_failures.append("pulse-width slack/check count")
    if routable <= 0 or routable != routed or route_errors:
        gate_failures.append("route completeness")
    pass_marker = re.findall(r"^NATIVE_MAC_TIMING_V2_IMPL_PASS frequency_mhz=100\s*$", output, re.MULTILINE)
    fail_markers = re.findall(r"^NATIVE_MAC_TIMING_V2_FAIL (.+)$", output, re.MULTILINE)
    if return_code == 0:
        if len(pass_marker) != 1 or fail_markers or gate_failures:
            raise ValueError("Vivado returned success without exactly one passing implementation marker and metrics")
    elif len(fail_markers) != 1 or pass_marker or not gate_failures:
        raise ValueError("Vivado returned nonzero without a report-complete timing/route gate failure")

    return {
        "status": "PASS_100MHZ_IMPLEMENTATION" if return_code == 0 else "FAIL_100MHZ_TIMING_OR_ROUTE_GATE",
        "frequency_mhz": 100, "period_ns": 10.0, "higher_frequency_attempted": False,
        "maximum_frequency_swept": False,
        "setup_slack_ns": setup, "hold_slack_ns": hold,
        "pulse_width_checks": pulse_values, "pulse_width_nonnegative": pulse_nonnegative,
        "routable_nets": routable, "fully_routed_nets": routed, "route_errors": route_errors,
        "resources": {"lut": lut, "ff": ff, "dsp_total": dsp, "dsp_multiply": multiply,
                      "dsp_none": none, "bram36_equivalent": bram, "bufg": bufg,
                      "latches": latches, "blackboxes": blackboxes},
        "drc_review": drc, "gate_failures": gate_failures,
        "check_timing_zero_categories": check_timing,
        "phase_resources": phase_resources, "phase_dsp_census": phase_dsp,
        "routed_checkpoint": rel(build / "routed.dcp"),
        "route_reports": {name: rel(evidence / name) for name in required_files},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-xsim", action="store_true", help="Run the v2 FAST_SMOKE simulation after host preflight")
    parser.add_argument("--run-implementation-100mhz", action="store_true",
                        help="Run one XSim smoke followed by one full Vivado 100 MHz implementation")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    result: dict = {
        "status": "RUNNING",
        "run_id": run_id,
        "scope": "v2 standalone frozen 512-product MAC with one-cycle aligned monitor observation stage; optional FAST_SMOKE XSim and one full 100 MHz implementation",
        "source_sha256": {},
        "source_snapshot": rel(evidence / "source_snapshot"),
        "toolchain": {
            "python": str(PYTHON),
            "vivado_bin": str(VIVADO_BIN),
            "max_threads": 2,
            "numerical_threads": 1,
        },
        "board_access": False,
        "production_integrated": False,
        "route_frequency_mhz": 100,
        "commands": [],
    }
    (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    try:
        if Path(sys.executable).resolve() != PYTHON.resolve():
            raise ValueError(f"Use the pinned project Python interpreter: {PYTHON}")
        ast.parse(SELF.read_text(encoding="utf-8"), filename=str(SELF))
        inputs = (CORE_RTL, TOP_RTL, TB_RTL, SIM_BUFG, XDC, IMPL_TCL,
                  BASELINE_TOP_RTL, BASELINE_XDC, BASELINE_TCL, SELF)
        source_hashes = check_source_contract()
        write_source_snapshot(evidence, inputs)
        smoke_expected, smoke_summary = build_reference(SMOKE_GROUPS)
        full_expected, full_summary = build_reference(FULL_GROUPS)
        if len(smoke_expected) != EXPECTED_SMOKE["words"] or len(full_expected) != EXPECTED_SMOKE["words"]:
            raise ValueError("All eight shape/replay runs must serialize exactly 960 32-lane words")
        if not smoke_summary["overflow_words"] or not smoke_summary["nonzero_words"]:
            raise ValueError("Smoke reference lacks nonzero arithmetic or saturation coverage")
        expected_path = build / "expected_serial.hex"
        expected_path.write_text("".join(f"{word:020x}\n" for word in smoke_expected), encoding="ascii")
        (build / "reference_summary.json").write_text(json.dumps({
            "smoke": smoke_summary,
            "full": full_summary,
            "expected_serial_sha256": sha256(expected_path),
            "host_reference_algorithm": "direct Python signed-64 sums over generated direct activation windows and group-native weights; signed-33 bound; signed-32 saturation/flags",
        }, indent=2) + "\n", encoding="utf-8")
        result["source_sha256"] = source_hashes
        result["preflight"] = {
            "status": "PASS",
            "host_reference": rel(build / "reference_summary.json"),
            "smoke_expected_words": len(smoke_expected),
            "full_expected_words": len(full_expected),
            "smoke_expected_overflow_words": smoke_summary["overflow_words"],
            "full_expected_overflow_words": full_summary["overflow_words"],
            "smoke_weight_group_loads": EXPECTED_SMOKE["weight_groups"],
            "smoke_bias_loads": EXPECTED_SMOKE["bias_words"],
            "smoke_activation_groups": EXPECTED_SMOKE["activation_groups"],
            "full_weight_group_loads": sum(FULL_GROUPS),
            "full_activation_groups": 2 * sum(FULL_GROUPS),
            "per_shape": [
                {"shape": i, "groups_smoke": SMOKE_GROUPS[i], "groups_full": FULL_GROUPS[i],
                 "lanes": LANES[i], "sites": SITES[i], "replays": 2}
                for i in range(4)
            ],
            "checked": [
                "pinned frozen core hash",
                "registered stimulus and all-lane/overflow/metadata serializer markers",
            "all 32 output lanes are selected serially from the 1024-bit core result",
                "two marked reset stages, external reset hold requirement",
                "100 MHz clock with explicit 0/1 ns input/output delays",
                "no false-path, multicycle, or disable-timing exceptions",
                "independent signed-64 host output/reference generation for smoke and full group counts",
                "expected saturation and nonzero output coverage",
            ],
        }

        run_simulation = args.run_xsim or args.run_implementation_100mhz
        if run_simulation:
            if not PYTHON.is_file():
                raise FileNotFoundError(f"Missing pinned Python interpreter: {PYTHON}")
            for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
                if not (VIVADO_BIN / tool).is_file():
                    raise FileNotFoundError(f"Missing Vivado XSim executable: {VIVADO_BIN / tool}")
            env = os.environ.copy()
            env["OPENBLAS_NUM_THREADS"] = "1"
            env["OMP_NUM_THREADS"] = "1"
            env["MKL_NUM_THREADS"] = "1"
            xvlog, _ = run_logged("xvlog", [str(VIVADO_BIN / "xvlog.bat"), "-sv",
                                            str(SIM_BUFG), str(CORE_RTL), str(TOP_RTL), str(TB_RTL)],
                                  build, evidence, env, result)
            if "ERROR:" in xvlog or "Fatal:" in xvlog:
                raise ValueError("XSim compile log contains an error despite a zero exit status")
            run_logged("xelab", [str(VIVADO_BIN / "xelab.bat"), "-mt", "2",
                                  "tb_z100_native_mac_timing_v2", "-s", "native_mac_timing_v2_sim"],
                       build, evidence, env, result)
            simulation, _ = run_logged("xsim", [str(VIVADO_BIN / "xsim.bat"),
                                                 "native_mac_timing_v2_sim", "-runall"],
                                       build, evidence, env, result)
            reset_marker = re.findall(
                r"^NATIVE_MAC_TIMING_V2_RESET_FLUSH_PASS partial_words=(\d+) reset_zero_cycles=(\d+)\s*$",
                simulation, re.MULTILINE)
            marker = re.findall(
                r"^NATIVE_MAC_TIMING_V2_SMOKE_PASS words=(\d+) runs=(\d+) weight_groups=(\d+) bias_words=(\d+) activation_groups=(\d+) input_bubbles=(\d+) output_stalls=(\d+) overflow_words=(\d+) nonzero_words=(\d+)\s*$",
                simulation, re.MULTILINE)
            if len(reset_marker) != 1 or len(marker) != 1 or "Fatal:" in simulation or "FATAL:" in simulation:
                raise ValueError("XSim did not complete the v2 smoke and reset-flush markers")
            reset_values = list(map(int, reset_marker[0]))
            values = list(map(int, marker[0]))
            expected_prefix = [EXPECTED_SMOKE["words"], EXPECTED_SMOKE["runs"],
                               EXPECTED_SMOKE["weight_groups"], EXPECTED_SMOKE["bias_words"],
                               EXPECTED_SMOKE["activation_groups"]]
            if (reset_values[0] < 64 or reset_values[1] < 4 or values[:5] != expected_prefix or
                    any(value <= 0 for value in values[5:])):
                raise ValueError(f"XSim smoke coverage differs from host preflight: {values}")
            result["simulation"] = {
                "status": "PASS",
                "midrun_reset_partial_words": reset_values[0],
                "reset_zero_cycles": reset_values[1],
                "words": values[0], "runs": values[1], "weight_groups": values[2],
                "bias_words": values[3], "activation_groups": values[4],
                "input_bubbles": values[5], "output_stalls": values[6],
                "overflow_words": values[7], "nonzero_words": values[8],
                "checked": ["all serialized 32-bit lane values and overflow flags",
                            "token/site/lane/lane-count/last metadata",
                            "output stability during backpressure",
                            "two resident-weight replays for each shape",
                            "traffic counts and reset/done status",
                            "all monitor fields flush to zero after a midrun sampled reset"],
            }

        if args.run_implementation_100mhz:
            vivado = VIVADO_BIN / "vivado.bat"
            if not vivado.is_file():
                raise FileNotFoundError(f"Missing Vivado implementation executable: {vivado}")
            command = [str(vivado), "-mode", "batch", "-log", str(evidence / "vivado.log"),
                       "-journal", str(evidence / "vivado.jou"), "-source", str(IMPL_TCL),
                       "-tclargs", "100", str(build), str(evidence)]
            implementation, implementation_return_code = run_logged(
                "vivado_100mhz_implementation", command, build, evidence, env, result,
                allow_nonzero=True)
            result["implementation"] = validate_implementation_outputs(
                evidence, build, implementation, implementation_return_code)
            if implementation_return_code == 0:
                result["status"] = "PASS_NATIVE_MAC_TIMING_V2_100MHZ_IMPLEMENTATION"
            else:
                result["status"] = "FAILED_TIMING_GATE"
                result["error"] = "Vivado wrote completed route evidence, then failed the 100 MHz setup/hold/pulse or route gate"

        after_hashes = {rel(path): sha256(path) for path in inputs}
        if after_hashes != source_hashes:
            raise ValueError("Source-bound dependencies changed during the validation run")
        result["source_sha256_after"] = after_hashes
        if result["status"] == "FAILED_TIMING_GATE":
            pass
        elif args.run_implementation_100mhz:
            result["status"] = "PASS_NATIVE_MAC_TIMING_V2_100MHZ_IMPLEMENTATION"
        elif args.run_xsim:
            result["status"] = "PASS_NATIVE_MAC_TIMING_V2_FAST_SMOKE_XSIM_ONLY"
        else:
            result["status"] = "PASS_NATIVE_MAC_TIMING_V2_HOST_PREFLIGHT_VENDOR_NOT_RUN"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["source_sha256_after"] = {
            rel(path): sha256(path) for path in (CORE_RTL, TOP_RTL, TB_RTL, SIM_BUFG, XDC, IMPL_TCL,
                                                  BASELINE_TOP_RTL, BASELINE_XDC, BASELINE_TCL, SELF)
            if path.is_file()
        }
    result["artifact_sha256"] = artifact_hashes(evidence, build)
    report = evidence / "result.json"
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(report),
                      "error": result.get("error")}, ensure_ascii=False))
    return 0 if result["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
