"""Read-only review of the completed native-MAC 100 MHz v2 route evidence.

This script does not invoke vendor tools or modify the source/run evidence. It
binds all source and artifact hashes from the original attempt, independently
checks its numerical, timing, resource, route, and DRC-detail evidence, and
records standalone DRC findings as open implementation-methodology limits.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import uuid


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20261023T175933.957672Z_3cb6fdde"
PRIMARY_RUN = ROOT / "validation/board_z100/native_mac_timing_v2" / RUN_ID
PRIMARY_RESULT = PRIMARY_RUN / "result.json"
PRECHECK_RESULT = ROOT / "validation/board_z100/native_mac_timing_v2/20261023T175917.456936Z_67b3765b/result.json"
PRIMARY_BUILD = ROOT / "deployment/build/z100_native_mac_timing_v2" / RUN_ID
PRIMARY_TOP = ROOT / "deployment/hardware/z100_2026/native_mac_timing_v2/z100_native_mac_timing_top_v2.sv"
PRIMARY_XDC = ROOT / "deployment/hardware/z100_2026/native_mac_timing_v2/native_mac_timing_constraints_v2.xdc"
PRIMARY_TCL = ROOT / "deployment/hardware/z100_2026/native_mac_timing_v2/native_mac_timing_impl_v2.tcl"
PRIMARY_TB = ROOT / "deployment/hardware/z100_2026/native_mac_timing_v2/tb_z100_native_mac_timing_v2.sv"
PRIMARY_VALIDATOR = ROOT / "tools/validate_z100_native_mac_timing_v2.py"
REVIEW_EVIDENCE_ROOT = ROOT / "validation/board_z100/native_mac_timing_v2_review_v1"
CHECK_TIMING_CATEGORIES = (
    "no_clock", "constant_clock", "pulse_width_clock",
    "unconstrained_internal_endpoints", "no_input_delay", "no_output_delay",
    "multiple_clock", "generated_clocks", "loops", "partial_input_delay",
    "partial_output_delay", "latch_loops",
)
EXPECTED_DRC_SUMMARY = {
    "NSTD-1": ("Critical Warning", 1),
    "UCIO-1": ("Critical Warning", 1),
    "DPIP-1": ("Warning", 1280),
    "DPOP-1": ("Warning", 128),
    "ZPS7-1": ("Warning", 1),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def bind_inventory(label: str, hashes: dict[str, str], root: Path = ROOT) -> dict[str, str]:
    verified = {}
    for name, expected in sorted(hashes.items()):
        path = root / Path(name)
        require(path.is_file(), f"{label} inventory file is missing: {name}")
        actual = sha256(path)
        require(actual == expected, f"{label} hash mismatch: {name} expected {expected} got {actual}")
        verified[name] = actual
    return verified


def source_snapshot_path(result: dict, relative_source: str) -> Path:
    return ROOT / Path(result["source_snapshot"]) / Path(relative_source)


def parse_top_ports(top: str) -> dict[str, dict[str, object]]:
    header = top.split(");", 1)[0]
    ports: dict[str, dict[str, object]] = {}
    for match in re.finditer(
            r"\b(input|output)\s+(?:(?:wire|reg)\s+)?(?:\[(\d+):(\d+)\]\s+)?([A-Za-z_]\w*)",
            header):
        direction, high, low, name = match.groups()
        width = abs(int(high) - int(low)) + 1 if high is not None else 1
        ports[name] = {"direction": direction, "width": width,
                       "display": f"{name}[{high}:{low}]" if high is not None else name}
    require(ports, "Could not parse v2 top module I/O ports")
    return ports


def parse_resource(path: Path) -> dict[str, float | int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"RESOURCES phase=(\S+) lut=(\d+) ff=(\d+) dsp48e1=(\d+) dsp_total=(\d+) "
        r"ramb36=(\d+) ramb18=(\d+) bram36_equivalent=([0-9.]+) bufg=(\d+) "
        r"latches=(\d+) blackboxes=(\d+)", text)
    require(match is not None, f"Unrecognized resource report: {path}")
    v = match.groups()
    return {
        "phase": v[0], "lut": int(v[1]), "ff": int(v[2]), "dsp48e1": int(v[3]),
        "dsp_total": int(v[4]), "ramb36": int(v[5]), "ramb18": int(v[6]),
        "bram36_equivalent": float(v[7]), "bufg": int(v[8]),
        "latches": int(v[9]), "blackboxes": int(v[10]),
    }


def parse_dsp_census(path: Path) -> dict[str, dict[str, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    require(lines and lines[0].split("\t") ==
            ["cell", "USE_MULT", "USE_SIMD", "AREG", "BREG", "ADREG", "MREG", "PREG"],
            f"Unexpected DSP census header: {path}")
    rows = {}
    for line in lines[1:]:
        fields = line.split("\t")
        require(len(fields) == 8, f"Malformed DSP census row: {line}")
        require(fields[0] not in rows, f"Duplicate DSP census cell: {fields[0]}")
        rows[fields[0]] = dict(zip(
            ("cell", "USE_MULT", "USE_SIMD", "AREG", "BREG", "ADREG", "MREG", "PREG"), fields))
    return rows


def parse_dsp_summary(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    required = {
        "DSP48E1_TOTAL": "total", "USE_MULT_MULTIPLY": "multiply",
        "USE_MULT_NONE": "none", "USE_MULT_OTHER": "other",
    }
    values = {}
    for source, target in required.items():
        match = re.search(rf"^{source}\s+(\d+)\s*$", text, re.MULTILINE)
        require(match is not None, f"DSP summary lacks {source}: {path}")
        values[target] = int(match.group(1))
    return values


def parse_route_status(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    patterns = {
        "routable": r"# of routable nets\.+\s*:\s*(\d+)",
        "routed": r"# of fully routed nets\.+\s*:\s*(\d+)",
        "errors": r"# of nets with routing errors\.+\s*:\s*(\d+)",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        require(match is not None, f"Route status lacks {key} count")
        result[key] = int(match.group(1))
    return result


def parse_check_timing(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    values = {}
    for category in CHECK_TIMING_CATEGORIES:
        matches = re.findall(
            rf"^\d+\. checking\s+{re.escape(category)}\s+\((\d+)\)\s*\n-+",
            text, re.MULTILINE)
        require(len(matches) == 1, f"Expected one check_timing result for {category} in {path}")
        values[category] = int(matches[0])
    return values


def parse_drc(path: Path) -> tuple[dict[str, dict[str, object]], dict[str, list[dict[str, object]]]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    summary_match = re.search(
        r"(?ms)^1\. REPORT SUMMARY\s*\n-+\s*\n(.*?)"
        r"(?=^2\. REPORT DETAILS\s*\n-+\s*$)", text)
    require(summary_match is not None, "DRC report lacks the numbered summary/details sections")
    summary_rows = re.findall(
        r"^\|\s*([A-Z][A-Z0-9]+-\d+)\s*\|\s*(Critical Warning|Warning|Error|Advisory)\s*\|"
        r"\s*([^|]*?)\s*\|\s*(\d+)\s*\|\s*$",
        summary_match.group(1), re.MULTILINE)
    summary: dict[str, dict[str, object]] = {}
    for rule, severity, description, count in summary_rows:
        require(rule not in summary, f"Duplicate DRC summary row: {rule}")
        summary[rule] = {"severity": severity, "description": description.strip(), "count": int(count)}
    require(summary, "DRC summary contains no rules")

    detail_start = re.search(r"(?m)^2\. REPORT DETAILS\s*\n-+\s*$", text)
    require(detail_start is not None, "DRC report lacks its details header")
    detail_text = text[detail_start.end():]
    headers = list(re.finditer(
        r"(?m)^([A-Z][A-Z0-9]+-\d+)#(\d+) (Critical Warning|Warning|Error|Advisory)\s*$",
        detail_text))
    details: dict[str, list[dict[str, object]]] = defaultdict(list)
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(detail_text)
        details[header.group(1)].append({
            "index": int(header.group(2)), "severity": header.group(3),
            "body": detail_text[header.end():end].strip(),
        })
    require(set(details) == set(summary),
            f"DRC summary/detail rule sets differ: summary={sorted(summary)} details={sorted(details)}")
    for rule, item in summary.items():
        entries = details[rule]
        require(len(entries) == item["count"],
                f"DRC {rule} detail count {len(entries)} does not match summary {item['count']}")
        require([entry["index"] for entry in entries] == list(range(1, int(item["count"]) + 1)),
                f"DRC {rule} detail indexes are incomplete or duplicated")
        require(all(entry["severity"] == item["severity"] for entry in entries),
                f"DRC {rule} detail severity differs from its summary")
    return summary, details


def extract_problem_ports(body: str, rule: str) -> tuple[int, int, list[str]]:
    count = re.search(r"(\d+) out of (\d+) logical ports", body)
    require(count is not None, f"{rule} lacks a logical-port count")
    start = body.find("Problem ports:")
    require(start >= 0, f"{rule} lacks a Problem ports list")
    start += len("Problem ports:")
    end = body.find("Related violations:", start)
    if end < 0:
        end = len(body)
    raw = body[start:end].replace("\r", " ").replace("\n", " ")
    ports = [part.strip().rstrip(".") for part in raw.split(",") if part.strip()]
    return int(count.group(1)), int(count.group(2)), ports


def parse_marker(line: str) -> dict[str, object]:
    pattern = re.compile(
        r"^NATIVE_MAC_TIMING_V2_ROUTE_DATA frequency_mhz=100 "
        r"setup_slack_ns=(-?\d+(?:\.\d+)?) hold_slack_ns=(-?\d+(?:\.\d+)?) "
        r"pulse_checks=(\d+) pulse_nonnegative=([01]) routable=(\d+) routed=(\d+) route_errors=(\d+) "
        r"lut=(\d+) ff=(\d+) dsp_total=(\d+) dsp_multiply=(\d+) dsp_none=(\d+) "
        r"bram36_equivalent=(\d+(?:\.\d+)?) bufg=(\d+) latches=(\d+) blackboxes=(\d+) "
        r"check_timing_zero_categories=12\s*$")
    match = pattern.match(line)
    require(match is not None, "The emitted route-data marker is malformed")
    values = match.groups()
    return {
        "frequency_mhz": 100,
        "setup_slack_ns": float(values[0]), "hold_slack_ns": float(values[1]),
        "pulse_checks": int(values[2]), "pulse_nonnegative": values[3] == "1",
        "routable_nets": int(values[4]), "fully_routed_nets": int(values[5]),
        "route_errors": int(values[6]), "lut": int(values[7]), "ff": int(values[8]),
        "dsp_total": int(values[9]), "dsp_multiply": int(values[10]),
        "dsp_none": int(values[11]), "bram36_equivalent": float(values[12]),
        "bufg": int(values[13]), "latches": int(values[14]), "blackboxes": int(values[15]),
        "check_timing_zero_categories": 12,
    }


def inspect_drc(top_path: Path, drc_path: Path, census_path: Path) -> dict[str, object]:
    top = top_path.read_text(encoding="utf-8")
    ports = parse_top_ports(top)
    port_bits = sum(int(item["width"]) for item in ports.values())
    summary, details = parse_drc(drc_path)
    require({rule: (item["severity"], item["count"]) for rule, item in summary.items()} == EXPECTED_DRC_SUMMARY,
            "Routed DRC summary contains an unknown rule, count, or severity")

    port_claims = {}
    expected_port_names = {item["display"] for item in ports.values()}
    for rule in ("NSTD-1", "UCIO-1"):
        n_bad, n_total, listed = extract_problem_ports(details[rule][0]["body"], rule)
        require(n_bad == port_bits == n_total == 115,
                f"{rule} does not identify all 115 standalone top-level I/O bits")
        require(set(listed) == expected_port_names and len(listed) == len(expected_port_names),
                f"{rule} problem-port list does not exactly match the v2 top: {listed}")
        port_claims[rule] = {"severity": summary[rule]["severity"], "count": 1,
                             "affected_logical_port_bits": n_bad, "affected_ports": listed,
                             "disposition": "OPEN_STANDALONE_IO_ASSIGNMENT",
                             "closed": False}

    require("PS7" not in top, "Standalone top unexpectedly contains a PS7 instance")
    zps7_body = details["ZPS7-1"][0]["body"]
    require("PS7 cell must be used" in zps7_body,
            "ZPS7-1 detail does not describe the standalone PS7 requirement")

    dsp = parse_dsp_census(census_path)
    require(len(dsp) == 640, f"Routed DSP census has {len(dsp)} rows, expected 640")
    mode_counts = Counter(row["USE_MULT"] for row in dsp.values())
    require(mode_counts == Counter({"MULTIPLY": 512, "NONE": 128}),
            f"Unexpected DSP modes: {dict(mode_counts)}")
    require(all(row["AREG"] == "0" and row["BREG"] == "0" for row in dsp.values()),
            "DPIP-1 warning census disagrees with DSP AREG/BREG properties")
    require(sum(int(row["AREG"]) == 0 for row in dsp.values()) == 640 and
            sum(int(row["BREG"]) == 0 for row in dsp.values()) == 640,
            "Not all 640 DSPs have unpipelined A and B input registers")

    dpip_rows = []
    for entry in details["DPIP-1"]:
        match = re.search(
            r"^DSP\s+(\S+)\s+input\s+\S+/(A|B)\[[^]]+\]\s+is not pipelined\.",
            entry["body"], re.MULTILINE)
        require(match is not None, f"Unparsed DPIP-1 detail #{entry['index']}")
        cell, port = match.groups()
        require(cell in dsp, f"DPIP-1 references a cell absent from DSP census: {cell}")
        dpip_rows.append({"index": entry["index"], "cell": cell, "port": port,
                          "input_register": "AREG" if port == "A" else "BREG",
                          "register_value": int(dsp[cell]["AREG" if port == "A" else "BREG"]),
                          "USE_MULT": dsp[cell]["USE_MULT"]})
    observed_dpip = {(row["cell"], row["port"]) for row in dpip_rows}
    expected_dpip = {(cell, port) for cell, row in dsp.items() for port, prop in (("A", "AREG"), ("B", "BREG"))
                     if row[prop] == "0"}
    require(len(dpip_rows) == 1280 and len(observed_dpip) == 1280 and observed_dpip == expected_dpip,
            "DPIP-1 details are not exactly one A and B finding for each affected DSP")
    dpip_by_cell: dict[str, list[str]] = defaultdict(list)
    for row in dpip_rows:
        dpip_by_cell[str(row["cell"])].append(str(row["port"]))
    require(all(sorted(ports_for_cell) == ["A", "B"] for ports_for_cell in dpip_by_cell.values()) and
            len(dpip_by_cell) == 640,
            "DPIP-1 cell/port detail pairing is incomplete")
    dpip_affected = [
        {"cell": cell, "ports": sorted(dpip_by_cell[cell]), "USE_MULT": dsp[cell]["USE_MULT"],
         "AREG": int(dsp[cell]["AREG"]), "BREG": int(dsp[cell]["BREG"])}
        for cell in sorted(dpip_by_cell)
    ]

    dpop_rows = []
    for entry in details["DPOP-1"]:
        match = re.search(
            r"^DSP\s+(\S+)\s+output\s+\S+/P\[[^]]+\]\s+is not pipelined \(PREG=0\)\.",
            entry["body"], re.MULTILINE)
        require(match is not None, f"Unparsed DPOP-1 detail #{entry['index']}")
        cell = match.group(1)
        require(cell in dsp, f"DPOP-1 references a cell absent from DSP census: {cell}")
        row = dsp[cell]
        require(cell.endswith(".pair0") and row["USE_MULT"] == "MULTIPLY" and row["PREG"] == "0",
                f"DPOP-1 cell is not an exact pair0/MULTIPLY/PREG0 finding: {cell} {row}")
        dpop_rows.append({"index": entry["index"], "cell": cell, "USE_MULT": row["USE_MULT"],
                          "PREG": int(row["PREG"]), "USE_SIMD": row["USE_SIMD"]})
    dpop_cells = {str(row["cell"]) for row in dpop_rows}
    require(len(dpop_rows) == 128 and len(dpop_cells) == 128,
            "DPOP-1 detail cell count is not exactly 128 unique cells")
    dpop_affected = [{key: row[key] for key in ("cell", "USE_MULT", "PREG", "USE_SIMD")}
                     for row in sorted(dpop_rows, key=lambda item: str(item["cell"]))]

    return {
        "summary": summary,
        "standalone_io_open_findings": port_claims,
        "standalone_ps_open_finding": {
            "rule": "ZPS7-1", "severity": summary["ZPS7-1"]["severity"], "count": 1,
            "disposition": "OPEN_STANDALONE_PS_REQUIREMENT", "closed": False,
        },
        "implementation_methodology_open_findings": {
            "DPIP-1": {"severity": "Warning", "detail_count": len(dpip_rows),
                       "affected_dsp_cells": len(dpip_affected), "per_cell_ports": ["A", "B"],
                       "register_values": {"AREG": 0, "BREG": 0},
                       "disposition": "OPEN_IMPLEMENTATION_METHODOLOGY", "closed": False,
                       "affected_cells": dpip_affected},
            "DPOP-1": {"severity": "Warning", "detail_count": len(dpop_rows),
                       "affected_dsp_cells": len(dpop_affected), "cell_pattern": "pair0",
                       "USE_MULT": "MULTIPLY", "PREG": 0,
                       "disposition": "OPEN_IMPLEMENTATION_METHODOLOGY", "closed": False,
                       "affected_cells": dpop_affected},
        },
        "dsp_census": {"total": len(dsp), "mode_counts": dict(mode_counts),
                       "routed_census_sha256": sha256(census_path)},
        "severity_downgrade_or_suppression_present": False,
        "bitstream_or_board_signoff": False,
    }


def inspect_timing(run: Path, build: Path, xdc_path: Path, tcl_path: Path) -> dict[str, object]:
    xdc = xdc_path.read_text(encoding="utf-8")
    tcl = tcl_path.read_text(encoding="utf-8")
    combined = xdc + "\n" + tcl
    require("create_clock -name core_clk -period 10.000 [get_ports clk]" in xdc,
            "XDC does not constrain the core clock to 10.000 ns")
    for line in (
        "set_input_delay -clock [get_clocks core_clk] -min 0.000 [get_ports rst_n]",
        "set_input_delay -clock [get_clocks core_clk] -max 1.000 [get_ports rst_n]",
        "set_output_delay -clock [get_clocks core_clk] -min 0.000 $fixture_outputs",
        "set_output_delay -clock [get_clocks core_clk] -max 1.000 $fixture_outputs",
    ):
        require(line in xdc, f"XDC lacks required exact delay: {line}")
    require(not re.search(r"\b(set_false_path|set_multicycle_path|set_clock_groups|set_disable_timing)\b", combined),
            "XDC or implementation Tcl includes a timing exception")
    require(not re.search(r"\bset_property\s+SEVERITY\b|\bset_msg_config\b", combined, re.IGNORECASE),
            "XDC or implementation Tcl downgrades/suppresses findings")
    require("write_bitstream" not in tcl, "Standalone review flow unexpectedly writes a bitstream")

    clock_topology = {}
    for phase in ("synth", "placed", "routed"):
        path = run / f"{phase}_clock_reset_topology.txt"
        text = path.read_text(encoding="utf-8", errors="replace")
        require(re.search(r"^CLOCK core_clk PERIOD_NS 10\.0 SOURCE clk$", text, re.MULTILINE) is not None,
                f"{phase} clock topology does not prove the 10 ns core clock")
        require(re.search(r"^BUFG_COUNT 1$", text, re.MULTILINE) is not None,
                f"{phase} topology does not contain exactly one BUFG")
        require(re.search(r"^RESET_ASYNC_REG_COUNT 2$", text, re.MULTILINE) is not None,
                f"{phase} topology does not contain exactly two sampled-reset flops")
        clock_topology[phase] = {
            "period_ns": 10.0, "bufg_count": 1, "reset_async_reg_count": 2,
            "register_count": int(re.search(r"^REGISTER_COUNT (\d+)$", text, re.MULTILINE).group(1)),
        }
        checks = parse_check_timing(run / f"check_timing_{phase}.rpt")
        require(all(value == 0 for value in checks.values()),
                f"{phase} check_timing has nonzero endpoint/category counts: {checks}")
        clock_topology[phase]["check_timing"] = checks

    resources = {}
    dsp_census = {}
    for phase in ("synth", "placed", "routed"):
        resource = parse_resource(run / f"resources_{phase}.txt")
        census = parse_dsp_summary(run / f"dsp48e1_{phase}_summary.txt")
        require(resource["phase"] == phase, f"Resource file phase mismatch: {phase}")
        require(resource["dsp_total"] == 640 and census ==
                {"total": 640, "multiply": 512, "none": 128, "other": 0},
                f"{phase} DSP census differs from 640=512 MULTIPLY+128 NONE")
        require(resource["lut"] <= 40000 and resource["ff"] <= 25000 and
                28.0 <= resource["bram36_equivalent"] <= 40.0 and
                resource["bufg"] == 1 and resource["latches"] == 0 and resource["blackboxes"] == 0,
                f"{phase} resource screen failed: {resource}")
        resources[phase] = resource
        dsp_census[phase] = census

    timing_slack = (run / "timing_slack_routed.txt").read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"TIMING phase=routed setup_slack_ns=(-?\d+(?:\.\d+)?) hold_slack_ns=(-?\d+(?:\.\d+)?) "
        r"pulse_checks=(\d+) pulse_min_slack_nonnegative=([01])", timing_slack)
    require(m is not None, "Routed detailed timing slack file is malformed")
    setup, hold, pulse_checks, pulse_nonnegative = float(m.group(1)), float(m.group(2)), int(m.group(3)), m.group(4) == "1"
    pulse_lines = (run / "pulse_width_routed.rpt").read_text(encoding="utf-8", errors="replace").splitlines()
    pulse_values = []
    for line in pulse_lines:
        match = re.search(r"^\s*(Min Period|Low Pulse Width|High Pulse Width)\s+.*\s+(-?\d+\.\d+)\s+\S+\s+\S+\s*$", line)
        if match:
            pulse_values.append({"check": match.group(1), "slack_ns": float(match.group(2))})
    require(len(pulse_values) == pulse_checks == 3 and all(item["slack_ns"] >= 0 for item in pulse_values) and
            pulse_nonnegative, "Routed pulse-width report is incomplete or negative")

    def path_summary(name: str) -> dict[str, object]:
        text = (run / name).read_text(encoding="utf-8", errors="replace")
        slack_match = re.search(r"Slack \(MET\)\s*:\s*(-?\d+\.\d+)ns", text)
        source_match = re.search(r"^\s*Source:\s+(.+?)\s*$", text, re.MULTILINE)
        destination_match = re.search(r"^\s*Destination:\s+(.+?)\s*$", text, re.MULTILINE)
        require(slack_match and source_match and destination_match, f"Could not parse critical path in {name}")
        return {"slack_ns": float(slack_match.group(1)), "source": source_match.group(1),
                "destination": destination_match.group(1)}

    setup_path = path_summary("all_setup_max_routed.rpt")
    hold_path = path_summary("all_hold_min_routed.rpt")
    require(abs(float(setup_path["slack_ns"]) - setup) < 0.001 and
            abs(float(hold_path["slack_ns"]) - hold) < 0.001 and setup >= 0 and hold >= 0,
            "Detailed setup/hold paths do not match slack values or are negative")

    timing_report = (run / "timing_routed.rpt").read_text(encoding="utf-8", errors="replace")
    timing_section = timing_report.split("| Design Timing Summary", 1)[-1].split("| Clock Summary", 1)[0]
    rows = re.findall(
        r"(?m)^\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+"
        r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+"
        r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s*$", timing_section)
    require(len(rows) == 1 and abs(float(rows[0][0]) - setup) < 0.001 and
            abs(float(rows[0][4]) - hold) < 0.001,
            "Routed Vivado timing-summary row does not match detailed path reports")

    route_status = parse_route_status(run / "route_status.rpt")
    require(route_status == {"routable": 38615, "routed": 38615, "errors": 0},
            f"Route status is incomplete: {route_status}")
    vivado_text = (run / "vivado_100mhz_implementation.log").read_text(encoding="utf-8", errors="replace")
    marker_lines = re.findall(r"^NATIVE_MAC_TIMING_V2_ROUTE_DATA .*?$", vivado_text, re.MULTILINE)
    pass_lines = re.findall(r"^NATIVE_MAC_TIMING_V2_IMPL_PASS frequency_mhz=100\s*$", vivado_text, re.MULTILINE)
    fail_lines = re.findall(r"^NATIVE_MAC_TIMING_V2_FAIL .+$", vivado_text, re.MULTILINE)
    require(len(marker_lines) == 1 and len(pass_lines) == 1 and not fail_lines,
            "Vivado log does not contain exactly one actual 100 MHz pass marker and route-data marker")
    route_marker = parse_marker(marker_lines[0])
    require(route_marker["setup_slack_ns"] == setup and route_marker["hold_slack_ns"] == hold and
            route_marker["pulse_checks"] == pulse_checks and route_marker["pulse_nonnegative"] and
            route_marker["routable_nets"] == route_status["routable"] and
            route_marker["fully_routed_nets"] == route_status["routed"] and
            route_marker["route_errors"] == route_status["errors"],
            "Anchored Vivado route marker disagrees with emitted reports")
    for phase, resource in resources.items():
        require(route_marker["lut"] == resources["routed"]["lut"] and
                route_marker["ff"] == resources["routed"]["ff"],
                "Route marker and routed resource census disagree")
    require(route_marker["dsp_total"] == 640 and route_marker["dsp_multiply"] == 512 and
            route_marker["dsp_none"] == 128 and route_marker["bram36_equivalent"] == 28.5 and
            route_marker["bufg"] == 1 and route_marker["latches"] == 0 and
            route_marker["blackboxes"] == 0 and route_marker["check_timing_zero_categories"] == 12,
            "Route marker resource/clock-check fields differ from the fixed screen")

    checkpoint = build / "routed.dcp"
    require(checkpoint.is_file(), "Routed DCP is missing")
    return {
        "clock_and_constraints": {
            "frequency_mhz": 100, "period_ns": 10.0,
            "input_delay_ns": {"min": 0.0, "max": 1.0},
            "output_delay_ns": {"min": 0.0, "max": 1.0},
            "exceptions": [], "severity_downgrade_or_suppression": False,
            "phase_topology_and_check_timing": clock_topology,
        },
        "resources_by_phase": resources,
        "dsp_census_by_phase": dsp_census,
        "timing": {"setup_slack_ns": setup, "hold_slack_ns": hold,
                   "setup_critical_path": setup_path, "hold_critical_path": hold_path,
                   "pulse_width_checks": pulse_values, "timing_summary_row": list(rows[0])},
        "route": {**route_status, "route_marker": route_marker,
                  "routed_dcp": rel(checkpoint), "routed_dcp_sha256": sha256(checkpoint)},
        "vivado_pass_marker": pass_lines[0],
    }


def inspect_simulation(primary: dict, build: Path, run: Path) -> dict[str, object]:
    sim = primary.get("simulation")
    require(isinstance(sim, dict) and sim.get("status") == "PASS",
            "Original run did not record XSim PASS")
    validator_spec = importlib.util.spec_from_file_location("pinned_native_mac_validator", PRIMARY_VALIDATOR)
    require(validator_spec is not None and validator_spec.loader is not None,
            "Could not load the pinned source-bound reference generator")
    module = importlib.util.module_from_spec(validator_spec)
    validator_spec.loader.exec_module(module)
    reference, summary = module.build_reference(tuple(module.SMOKE_GROUPS))
    expected_path = build / "expected_serial.hex"
    expected_words = [int(line, 16) for line in expected_path.read_text(encoding="ascii").splitlines() if line.strip()]
    require(len(reference) == len(expected_words) == 960 and reference == expected_words,
            "Saved XSim expected words do not match the pinned direct signed-64 reference")
    reference_summary = read_json(build / "reference_summary.json")
    require(reference_summary["expected_serial_sha256"] == sha256(expected_path) and
            reference_summary["smoke"]["serialized_words"] == 960,
            "Expected-word file hash/count differs from its saved reference summary")
    tb = PRIMARY_TB.read_text(encoding="utf-8")
    require("!== expected_serial[expected_read]" in tb and "EXPECTED_WORDS = 960" in tb and
            "serialized MAC output changed during backpressure" in tb and
            "monitor observation stage retained stale outputs across reset" in tb,
            "The bench source does not check all output words, stalls, and reset flush")
    xsim = (run / "xsim.log").read_text(encoding="utf-8", errors="replace")
    reset = re.findall(
        r"^NATIVE_MAC_TIMING_V2_RESET_FLUSH_PASS partial_words=(\d+) reset_zero_cycles=(\d+)\s*$",
        xsim, re.MULTILINE)
    smoke = re.findall(
        r"^NATIVE_MAC_TIMING_V2_SMOKE_PASS words=(\d+) runs=(\d+) weight_groups=(\d+) bias_words=(\d+) "
        r"activation_groups=(\d+) input_bubbles=(\d+) output_stalls=(\d+) overflow_words=(\d+) nonzero_words=(\d+)\s*$",
        xsim, re.MULTILINE)
    require(len(reset) == len(smoke) == 1, "XSim log lacks unique anchored pass markers")
    reset_values = list(map(int, reset[0]))
    values = list(map(int, smoke[0]))
    require(reset_values[0] >= 64 and reset_values[1] >= 4 and
            values == [960, 8, 22, 4, 44, 2, 146, 60, 832],
            f"XSim counters differ from expected coverage: reset={reset_values} smoke={values}")
    sim_expected = {
        "status": "PASS", "midrun_reset_partial_words": reset_values[0],
        "reset_zero_cycles": reset_values[1], "words": values[0], "runs": values[1],
        "weight_groups": values[2], "bias_loads": values[3], "activation_groups": values[4],
        "input_bubbles": values[5], "output_stalls": values[6],
        "overflow_words": values[7], "nonzero_words": values[8],
        "expected_reference": summary,
        "expected_serial_sha256": sha256(expected_path),
        "checked": ["all 960 data/overflow and token/site/lane/lanes/last words",
                    "output stability under backpressure", "reset flush of all monitor outputs",
                    "resident-weight replays across eight runs"],
    }
    for key, value in (("words", 960), ("runs", 8), ("weight_groups", 22),
                       ("bias_loads", 4), ("activation_groups", 44),
                       ("input_bubbles", 2), ("output_stalls", 146),
                       ("overflow_words", 60), ("nonzero_words", 832)):
        primary_key = "bias_words" if key == "bias_loads" else key
        require(sim.get(primary_key) == value, f"Original result simulation counter mismatch: {primary_key}")
    require(primary["commands"][:3] and all(cmd["return_code"] == 0 for cmd in primary["commands"][:3]),
            "XSim compile/elaboration/simulation command return code is not zero")
    return sim_expected


def review() -> dict[str, object]:
    require(PRIMARY_RESULT.is_file() and PRECHECK_RESULT.is_file(), "Pinned prior result/preflight is missing")
    primary = read_json(PRIMARY_RESULT)
    precheck = read_json(PRECHECK_RESULT)
    require(primary["run_id"] == RUN_ID, "Primary run ID differs from the pinned route evidence")
    require(primary["status"] == "FAILED_CLOSED" and
            str(primary.get("error", "")).startswith("ValueError: Unexpected routed DRC findings:"),
            "Original attempt did not fail solely at the known DRC classifier boundary")
    require(primary.get("source_sha256") == primary.get("source_sha256_after"),
            "Primary source hashes changed during its vendor run")
    require(precheck["status"] == "PASS_NATIVE_MAC_TIMING_V2_HOST_PREFLIGHT_VENDOR_NOT_RUN" and
            precheck.get("source_sha256") == primary["source_sha256"],
            "Source-bound host preflight does not match the vendor-run source snapshot")
    require(primary.get("route_frequency_mhz") == 100 and
            primary.get("board_access") is False and primary.get("production_integrated") is False,
            "Original run scope is not restricted to 100 MHz standalone review")
    require(primary.get("toolchain", {}).get("max_threads") == 2 and
            primary.get("toolchain", {}).get("numerical_threads") == 1,
            "Original run thread limits differ from the authorized fixture")

    sources = bind_inventory("primary source", primary["source_sha256"])
    source_after = bind_inventory("source-after", primary["source_sha256_after"])
    require(sources == source_after, "Source hashes differ after execution")
    snapshot_verified = {}
    for relative, expected in sources.items():
        snapshot = source_snapshot_path(primary, relative)
        require(snapshot.is_file() and sha256(snapshot) == expected,
                f"Source snapshot does not match pinned source: {relative}")
        snapshot_verified[relative] = sha256(snapshot)
    artifacts = bind_inventory("primary artifact", primary["artifact_sha256"])
    precheck_sources = bind_inventory("preflight source", precheck["source_sha256"])
    require(precheck_sources == sources, "Host preflight source hashes differ from the implementation run")
    precheck_artifacts = bind_inventory("preflight artifact", precheck["artifact_sha256"])

    sim = inspect_simulation(primary, PRIMARY_BUILD, PRIMARY_RUN)
    timing = inspect_timing(PRIMARY_RUN, PRIMARY_BUILD, PRIMARY_XDC, PRIMARY_TCL)
    drc = inspect_drc(PRIMARY_TOP, PRIMARY_RUN / "drc_routed.rpt", PRIMARY_RUN / "dsp48e1_routed.tsv")
    require(all(command["return_code"] == 0 for command in primary["commands"]),
            "At least one original XSim/Vivado command returned nonzero")
    require("NATIVE_MAC_TIMING_V2_FAIL" not in timing["vivado_pass_marker"],
            "Unexpected failed implementation marker")

    combined_hashes = dict(sources)
    for inventory in (artifacts, precheck_artifacts):
        for name, value in inventory.items():
            if name in combined_hashes:
                require(combined_hashes[name] == value, f"Conflicting bound hash for {name}")
            combined_hashes[name] = value
    primary_result_sha = sha256(PRIMARY_RESULT)
    precheck_result_sha = sha256(PRECHECK_RESULT)
    combined_hashes[rel(PRIMARY_RESULT)] = primary_result_sha
    combined_hashes[rel(PRECHECK_RESULT)] = precheck_result_sha
    require(sha256(PRIMARY_BUILD / "routed.dcp") == timing["route"]["routed_dcp_sha256"],
            "Routed DCP hash differs from the route review")

    return {
        "status": "ROOT_REVIEW_NATIVE_MAC100_TIMING_NUMERIC_PASS_STANDALONE_DRC_OPEN",
        "review_scope": "read-only classification of one completed standalone 100 MHz native-MAC v2 implementation run",
        "primary_run_id": RUN_ID,
        "primary_result": rel(PRIMARY_RESULT),
        "primary_result_sha256": primary_result_sha,
        "primary_original_status": primary["status"],
        "primary_original_failure": primary["error"],
        "preflight_result": rel(PRECHECK_RESULT),
        "preflight_result_sha256": precheck_result_sha,
        "review_script": rel(Path(__file__).resolve()),
        "review_script_sha256": sha256(Path(__file__).resolve()),
        "source_sha256": sources,
        "source_snapshot_sha256": snapshot_verified,
        "primary_artifact_sha256": artifacts,
        "preflight_artifact_sha256": precheck_artifacts,
        "bound_input_sha256": combined_hashes,
        "bound_input_count": len(combined_hashes),
        "simulation": sim,
        "implementation": timing,
        "drc_review": drc,
        "claims": {
            "frequency_scope_mhz": 100,
            "higher_frequency_attempted": False,
            "full_pipeline_or_model_claim": False,
            "board_or_production_claim": False,
            "drc_closed": False,
            "bitstream_ready": False,
            "severity_downgrade": False,
        },
        "review_checks": {
            "all_source_and_artifact_hashes_match": True,
            "source_snapshot_and_after_hashes_match": True,
            "xsim_numeric_metadata_stalls_reset": True,
            "clock_constraints_and_topology_10ns_no_exceptions": True,
            "all_12_check_timing_categories_zero_all_phases": True,
            "positive_setup_hold_and_all_pulse_checks": True,
            "route_complete_38615_zero_errors": True,
            "exact_dsp_census_and_drc_detail_reconciliation": True,
            "all_drc_findings_remain_open": True,
        },
    }


def main() -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    output_dir = REVIEW_EVIDENCE_ROOT / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    output = output_dir / "review.json"
    review_script = Path(__file__).resolve()
    before_hash = sha256(review_script)
    result: dict[str, object] = {
        "status": "RUNNING", "review_run_id": run_id,
        "evidence_path": rel(output), "review_script": rel(review_script),
        "review_script_sha256": before_hash,
    }
    try:
        result.update(review())
        require(sha256(review_script) == before_hash, "Review script changed while the review was running")
        result["review_script_sha256_after"] = sha256(review_script)
        result["status"] = "ROOT_REVIEW_NATIVE_MAC100_TIMING_NUMERIC_PASS_STANDALONE_DRC_OPEN"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED_REVIEW"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["review_script_sha256_after"] = sha256(review_script) if review_script.is_file() else None
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(output),
                      "error": result.get("error")}, ensure_ascii=False))
    return 0 if result["status"] == "ROOT_REVIEW_NATIVE_MAC100_TIMING_NUMERIC_PASS_STANDALONE_DRC_OPEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
