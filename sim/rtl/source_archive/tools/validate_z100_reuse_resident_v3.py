#!/usr/bin/env python3
"""Run and review a hash-bound Vivado implementation of resident-v3 timing fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "deployment/hardware/z100_2026/tile_reuse_resident_v3"
RTL = FIXTURE / "z100_tile_reuse_resident_v3.v"
TIMING_TOP = FIXTURE / "z100_tile_reuse_resident_v3_timing_top.sv"
TIMING_TB = FIXTURE / "tb_z100_tile_reuse_resident_v3_timing_top.sv"
SIM_BUFG = ROOT / "deployment/hardware/z100_2026/reuse_sync_fixture/sim_bufg.v"
CONSTRAINTS = FIXTURE / "resident_v3_constraints.xdc"
TCL = FIXTURE / "dsp_impl_v3.tcl"
BUILD_ROOT = ROOT / "deployment/build/z100_reuse_resident_v3"
EVIDENCE_ROOT = ROOT / "validation/board_z100/reuse_resident_v3"
VIVADO_DEFAULT = Path(r"C:\appload\2026.1\Vivado\bin\vivado.bat")
FROZEN_RTL_SHA256 = "f32bf6994d7041979db1b0b2115ba21c01905d23841fea63cfae8d452d98f082"
NUMERIC_GATE_RUN = "validation/board_z100/reuse_resident_v3/20261023T110921.693678Z_lane_reference_fix_xsim"
NUMERIC_GATE_TB_SHA256 = "07f6955d9a8c86b107d198b517559e27c77da9ad602237871b17d856fbc8d485"
SOURCES = (RTL, TIMING_TOP, TIMING_TB, SIM_BUFG, CONSTRAINTS, TCL, Path(__file__).resolve())

CHECK_CATEGORIES = (
    "no_clock", "constant_clock", "pulse_width_clock",
    "unconstrained_internal_endpoints", "no_input_delay", "no_output_delay",
    "multiple_clock", "generated_clocks", "loops", "partial_input_delay",
    "partial_output_delay", "latch_loops",
)
METRIC_RE = re.compile(r"^RESIDENT_V3_RESULT\s+(.*)$", re.MULTILINE)
SMOKE_RE = re.compile(r"^TIMING_FIXTURE_SMOKE_PASS\s+(.*)$", re.MULTILINE)
FIELD_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^\s]+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_metric_line(text: str) -> dict[str, int | float]:
    matches = METRIC_RE.findall(text)
    if len(matches) != 1:
        raise ValueError("Vivado output must contain exactly one RESIDENT_V3_RESULT line")
    raw = dict(FIELD_RE.findall(matches[0]))
    required = {
        "frequency_mhz", "internal_wns_ns", "internal_whs_ns", "routable",
        "routed", "route_errors", "lut", "ff", "dsp", "bram36_equivalent",
        "bufg", "registers", "multiply_dsp",
    }
    if set(raw) != required:
        raise ValueError(f"Result fields differ from schema: {sorted(raw)}")
    try:
        result: dict[str, int | float] = {
            key: (float(value) if key in {"internal_wns_ns", "internal_whs_ns", "bram36_equivalent"} else int(value))
            for key, value in raw.items()
        }
    except ValueError as exc:
        raise ValueError("Result line contains a nonnumeric value") from exc
    if not all(math.isfinite(float(value)) for value in result.values()):
        raise ValueError("Result line contains a nonfinite value")
    return result


def parse_fixture_smoke(text: str) -> dict[str, int]:
    matches = SMOKE_RE.findall(text)
    if len(matches) != 1:
        raise ValueError("Timing-fixture XSim log must contain exactly one PASS marker")
    raw = dict(FIELD_RE.findall(matches[0]))
    expected_keys = {
        "outputs", "runs", "accepted", "w_begin", "w_data", "bias", "w_commit",
        "act_begin", "act_data", "act_commit", "run", "stalls", "nonzero_words",
        "protocol_fault", "done",
    }
    if set(raw) != expected_keys:
        raise ValueError(f"Timing-fixture PASS marker fields differ: {sorted(raw)}")
    try:
        values = {key: int(value) for key, value in raw.items()}
    except ValueError as exc:
        raise ValueError("Timing-fixture PASS marker contains a non-integer value") from exc
    expected = {
        "outputs": 380, "runs": 5, "accepted": 184, "w_begin": 4, "w_data": 65,
        "bias": 4, "w_commit": 4, "act_begin": 5, "act_data": 92,
        "act_commit": 5, "run": 5, "protocol_fault": 0, "done": 1,
    }
    for key, value in expected.items():
        if values[key] != value:
            raise ValueError(f"Timing-fixture smoke {key}={values[key]}, expected {value}")
    if values["stalls"] <= 0 or values["nonzero_words"] <= 0:
        raise ValueError("Timing-fixture smoke did not exercise backpressure and live arithmetic output")
    return values


def parse_check_timing(text: str) -> dict[str, int]:
    if "Table of Contents" in text:
        first = text.find("1. checking no_clock")
        second = text.find("1. checking no_clock", first + 1)
        if second < 0:
            raise ValueError("check_timing report is missing its body")
        text = text[second:]
    result: dict[str, int] = {}
    for category in CHECK_CATEGORIES:
        found = re.findall(rf"checking\s+{re.escape(category)}\s+\((\d+)\)", text)
        if len(found) != 1:
            raise ValueError(f"check_timing report must contain exactly one {category} count")
        result[category] = int(found[0])
    all_categories = re.findall(r"checking\s+([A-Za-z0-9_]+)\s+\((\d+)\)", text)
    if len(all_categories) != len(CHECK_CATEGORIES):
        raise ValueError("check_timing report contains an unknown or duplicate category")
    return result


def parse_timing_summary(text: str) -> dict[str, float]:
    parts = text.split("| Design Timing Summary", 1)
    if len(parts) != 2:
        raise ValueError("Timing summary section missing")
    rows = re.findall(r"^\s*(-?\d+\.\d+(?:\s+-?\d+(?:\.\d+)?){11})\s*$", parts[1], re.MULTILINE)
    if len(rows) != 1:
        raise ValueError(f"Expected one twelve-column timing summary row; found {len(rows)}")
    values = [float(value) for value in rows[0].split()]
    names = (
        "wns_ns", "tns_ns", "setup_failing", "setup_endpoints",
        "whs_ns", "ths_ns", "hold_failing", "hold_endpoints",
        "wpws_ns", "tpws_ns", "pulse_failing", "pulse_endpoints",
    )
    return dict(zip(names, values))


def parse_pulse_width(text: str) -> dict[str, float]:
    wanted = {"Min Period", "Low Pulse Width", "High Pulse Width"}
    result: dict[str, float] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        label = " ".join(fields[:3]) if fields[:3] == ["Low", "Pulse", "Width"] else " ".join(fields[:3])
        if fields[0] == "Min" and fields[1:2] == ["Period"]:
            label = "Min Period"
        if label not in wanted:
            continue
        if len(fields) < 9:
            raise ValueError(f"Malformed pulse-width row: {line}")
        try:
            # Columns: check type, corner, library pin, reference pin, required,
            # actual, slack, location, pin. Min Period has a two-token label;
            # the pulse-width rows have a three-token label.
            slack_index = 7 if label == "Min Period" else 8
            slack = float(fields[slack_index])
        except ValueError as exc:
            raise ValueError(f"Non-numeric pulse-width slack: {line}") from exc
        result[label] = min(result.get(label, math.inf), slack)
    missing = wanted - set(result)
    if missing:
        raise ValueError(f"Pulse-width report missing rows: {sorted(missing)}")
    return {"min_period_slack_ns": result["Min Period"],
            "low_pulse_slack_ns": result["Low Pulse Width"],
            "high_pulse_slack_ns": result["High Pulse Width"]}


def parse_route_status(text: str) -> dict[str, int]:
    patterns = {
        "routable": r"# of routable nets\.+\s*:\s*(\d+)",
        "routed": r"# of fully routed nets\.+\s*:\s*(\d+)",
        "errors": r"# of nets with routing errors\.+\s*:\s*(\d+)",
    }
    result = {}
    for name, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if len(matches) != 1:
            raise ValueError(f"route report must contain one {name} count")
        result[name] = int(matches[0])
    return result


def parse_resources(path: Path) -> dict[str, int | float]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^RESOURCES\s+phase=routed\s+(.*)$", text, re.MULTILINE)
    if not match:
        raise ValueError("Routed resource summary missing")
    raw = dict(FIELD_RE.findall(match.group(1)))
    expected = {"lut", "ff", "dsp48e1", "dsp_total", "ramb36", "ramb18", "bram36_equivalent", "bufg", "latches"}
    if set(raw) != expected:
        raise ValueError(f"Routed resource schema differs: {sorted(raw)}")
    values: dict[str, int | float] = {key: int(value) for key, value in raw.items() if key != "bram36_equivalent"}
    values["bram36_equivalent"] = float(raw["bram36_equivalent"])
    return values


def parse_dsp_census(path: Path) -> dict[str, Any]:
    rows = path.read_text(encoding="utf-8").splitlines()
    if not rows or rows[0].split("\t") != ["cell", "AREG", "BREG", "ADREG", "ALUMODEREG", "OPMODEREG", "MREG", "PREG", "USE_MULT", "USE_SIMD"]:
        raise ValueError("DSP census header invalid")
    groups: Counter[tuple[str, ...]] = Counter()
    use_mult: Counter[str] = Counter()
    for row in rows[1:]:
        fields = row.split("\t")
        if len(fields) != 10 or not fields[0]:
            raise ValueError("Malformed DSP census row")
        groups[tuple(fields[1:])] += 1
        use_mult[fields[8]] += 1
    return {
        "count": sum(groups.values()),
        "use_mult": dict(sorted(use_mult.items())),
        "register_groups": [{"properties": list(properties), "count": count}
                            for properties, count in sorted(groups.items())],
    }


def parse_drc(text: str) -> dict[str, dict[str, Any]]:
    if "REPORT SUMMARY" not in text or "REPORT DETAILS" not in text:
        raise ValueError("DRC summary/detail sections missing")
    summary = text.split("REPORT SUMMARY", 1)[1].split("REPORT DETAILS", 1)[0]
    rows = re.findall(
        r"^\|\s*([A-Z][A-Z0-9]+-\d+)\s*\|\s*(Critical Warning|Warning|Error|Advisory)\s*\|[^|]*\|\s*(\d+)\s*\|",
        summary, re.MULTILINE,
    )
    result: dict[str, dict[str, Any]] = {}
    for rule, severity, count in rows:
        if rule in result:
            raise ValueError(f"Duplicate DRC summary row: {rule}")
        result[rule] = {"severity": severity, "count": int(count)}
    return result


def classify_drc(drc: dict[str, dict[str, Any]], dsp_census: dict[str, Any]) -> dict[str, Any]:
    # These are expected for an isolated device-level fixture with no PS7
    # instance and no board package/pin file. They remain open and unaccepted.
    open_expected: dict[str, str] = {
        "NSTD-1": "Critical Warning",
        "UCIO-1": "Critical Warning",
        "ZPS7-1": "Warning",
    }
    dsp_count = dsp_census["count"]
    use_mult = dsp_census["use_mult"].get("MULTIPLY", 0)
    unexpected = []
    unaccepted = []
    for rule, item in sorted(drc.items()):
        severity, count = item["severity"], item["count"]
        if rule in open_expected:
            if severity != open_expected[rule] or count != 1:
                unexpected.append({"rule": rule, **item, "reason": "expected standalone finding has changed"})
            else:
                unaccepted.append({"rule": rule, **item, "reason": "standalone fixture has no board I/O or PS7"})
        elif rule == "DPIP-1":
            if severity != "Warning" or count > 2 * use_mult:
                unexpected.append({"rule": rule, **item, "reason": "DSP input pipelining warning exceeds multiplier census"})
            else:
                unaccepted.append({"rule": rule, **item, "reason": "unregistered DSP input path; timing is reported separately"})
        elif rule == "DPOP-2":
            if severity != "Warning" or count > use_mult:
                unexpected.append({"rule": rule, **item, "reason": "DSP output pipelining warning exceeds multiplier census"})
            else:
                unaccepted.append({"rule": rule, **item, "reason": "DSP MREG configuration; timing is reported separately"})
        else:
            unexpected.append({"rule": rule, **item, "reason": "not an identified standalone or DSP finding"})
    if dsp_count != 512 or use_mult != 512:
        unexpected.append({"rule": "DSP_CENSUS", "severity": "Error", "count": dsp_count,
                           "reason": "expected exactly 512 observed MULTIPLY DSP48E1 cells"})
    return {"open_unaccepted": unaccepted, "unexpected": unexpected,
            "status": "UNEXPLAINED_DRC" if unexpected else "OPEN_UNACCEPTED_STANDALONE_DRC"}


def run_command(command: list[str], cwd: Path, log_path: Path) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        subprocess.list2cmdline(command), cwd=str(cwd), shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {
        "command": command, "cwd": str(cwd), "return_code": completed.returncode,
        "log": str(log_path),
        "warning_mentions": len(re.findall(r"\bWARNING\b", completed.stdout, re.IGNORECASE)),
        "output": completed.stdout,
    }


def run_fixture_smoke(evidence: Path, build: Path, tool_dir: Path,
                      expected_hashes: dict[str, str]) -> dict[str, Any]:
    sim_work = build / "timing_fixture_smoke"
    sim_work.mkdir(parents=True, exist_ok=False)
    xvlog = tool_dir / "xvlog.bat"
    xelab = tool_dir / "xelab.bat"
    xsim = tool_dir / "xsim.bat"
    commands: list[dict[str, Any]] = []
    for name, executable, args in (
        ("xvlog", xvlog, ["-sv", str(SIM_BUFG), str(RTL), str(TIMING_TOP), str(TIMING_TB)]),
        ("xelab", xelab, ["-debug", "typical", "tb_z100_tile_reuse_resident_v3_timing_top", "-s", "resident_v3_timing_fixture_smoke"]),
        ("xsim", xsim, ["resident_v3_timing_fixture_smoke", "-runall"]),
    ):
        if not executable.is_file():
            return {"status": "MISSING_XSIM_TOOL", "missing": str(executable), "commands": commands}
        result = run_command([str(executable.resolve()), *args], sim_work,
                             evidence / f"timing_fixture_{name}.log")
        commands.append({key: value for key, value in result.items() if key != "output"})
        if result["return_code"] != 0:
            return {"status": f"{name.upper()}_FAILED", "commands": commands}
        if name == "xsim":
            try:
                metrics = parse_fixture_smoke(result["output"])
            except Exception as exc:
                return {"status": "SMOKE_REVIEW_FAILED", "commands": commands,
                        "review_error": f"{type(exc).__name__}: {exc}"}
    after_hashes = source_hashes()
    if after_hashes != expected_hashes:
        return {"status": "SOURCE_HASH_CHANGED_DURING_SMOKE", "commands": commands,
                "source_sha256_before": expected_hashes, "source_sha256_after": after_hashes}
    return {"status": "PASS", "metrics": metrics, "commands": commands,
            "source_sha256": expected_hashes,
            "coverage": "five runs across lane/site shapes 9x1, 17x3, 32x2, 32x4, 32x4; all serialized lane/site words checked; activation replay retains committed weights; per-op accepted-command census and output stability under stalls checked"}


def source_hashes() -> dict[str, str]:
    missing = [path for path in SOURCES if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing source files: " + ", ".join(map(str, missing)))
    hashes = {str(path.relative_to(ROOT)): sha256(path) for path in SOURCES}
    rtl_key = str(RTL.relative_to(ROOT))
    if hashes[rtl_key] != FROZEN_RTL_SHA256:
        raise ValueError(f"Frozen RTL SHA mismatch: expected {FROZEN_RTL_SHA256}, found {hashes[rtl_key]}")
    return hashes


def prior_100_pass(path: Path, current_hashes: dict[str, str]) -> dict[str, Any]:
    path = path.resolve()
    if EVIDENCE_ROOT not in path.parents or not path.is_file():
        raise ValueError("--baseline-100 must be an existing result.json under the resident-v3 evidence root")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") != "PASS_100MHZ_COMPONENT_TIMING_RESOURCE_DRC_OPEN_UNACCEPTED":
        raise ValueError("150 MHz is gated on a routed 100 MHz timing/resource pass")
    if result.get("source_sha256") != current_hashes:
        raise ValueError("150 MHz baseline source hashes differ from current inputs")
    return result


def review_outputs(evidence: Path, frequency: int, expected_hashes: dict[str, str], vivado_result: dict[str, Any]) -> dict[str, Any]:
    log_text = Path(vivado_result["log"]).read_text(encoding="utf-8", errors="replace")
    metrics = parse_metric_line(log_text)
    resources = parse_resources(evidence / "resources_routed.txt")
    route = parse_route_status((evidence / "route_status.rpt").read_text(encoding="utf-8"))
    check_timing = parse_check_timing((evidence / "check_timing_routed.rpt").read_text(encoding="utf-8"))
    timing = parse_timing_summary((evidence / "timing_routed.rpt").read_text(encoding="utf-8"))
    pulse = parse_pulse_width((evidence / "pulse_width_routed.rpt").read_text(encoding="utf-8"))
    drc = parse_drc((evidence / "drc_routed.rpt").read_text(encoding="utf-8", errors="replace"))
    dsp_census = parse_dsp_census(evidence / "dsp48e1_routed.tsv")
    topology = (evidence / "routed_clock_topology.txt").read_text(encoding="utf-8")
    observability = (evidence / "synth_observability.txt").read_text(encoding="utf-8")

    if metrics["frequency_mhz"] != frequency:
        raise ValueError("Vivado result frequency does not match requested frequency")
    if route != {"routable": int(metrics["routable"]), "routed": int(metrics["routed"]), "errors": int(metrics["route_errors"])}:
        raise ValueError("Route report and Vivado result marker disagree")
    resource_map = {
        "lut": "lut", "ff": "ff", "dsp": "dsp48e1",
        "bram36_equivalent": "bram36_equivalent", "bufg": "bufg",
    }
    for metric_name, resource_name in resource_map.items():
        if not math.isclose(float(metrics[metric_name]), float(resources[resource_name]), abs_tol=0.001):
            raise ValueError(f"Resource marker/report mismatch for {metric_name}")
    if int(metrics["multiply_dsp"]) != dsp_census["use_mult"].get("MULTIPLY", 0):
        raise ValueError("DSP MULTIPLY census and Vivado result marker disagree")

    route_complete = route["routable"] > 0 and route["routed"] == route["routable"] and route["errors"] == 0
    timing_pass = (
        timing["wns_ns"] >= 0 and timing["tns_ns"] == 0 and timing["setup_failing"] == 0
        and timing["whs_ns"] >= 0 and timing["ths_ns"] == 0 and timing["hold_failing"] == 0
        and timing["wpws_ns"] >= 0 and timing["tpws_ns"] == 0 and timing["pulse_failing"] == 0
        and timing["setup_endpoints"] > 0 and timing["hold_endpoints"] > 0 and timing["pulse_endpoints"] > 0
        and metrics["internal_wns_ns"] >= 0 and metrics["internal_whs_ns"] >= 0
        and all(value >= 0 for value in pulse.values())
    )
    constraints_pass = set(check_timing) == set(CHECK_CATEGORIES) and all(value == 0 for value in check_timing.values())
    resource_pass = (
        resources["lut"] <= 50000 and resources["dsp48e1"] <= 640
        and resources["bram36_equivalent"] <= 96 and resources["bram36_equivalent"] >= 32
        and resources["dsp48e1"] == 512 and resources["dsp_total"] == 512
        and resources["latches"] == 0 and resources["bufg"] == 1
        and dsp_census["count"] == 512 and dsp_census["use_mult"].get("MULTIPLY", 0) == 512
    )
    fixture_pass = (
        "BLACKBOX_COUNT 0" in observability
        and "OUTPUT_PORT_COUNT 8" in observability
        and "BUFG_COUNT 1" in topology
        and "REGISTER_COUNT " in topology
    )
    drc_review = classify_drc(drc, dsp_census)
    source_after = source_hashes()
    source_stable = source_after == expected_hashes

    passed = route_complete and timing_pass and constraints_pass and resource_pass and fixture_pass and not drc_review["unexpected"] and source_stable
    status = (f"PASS_{frequency}MHZ_COMPONENT_TIMING_RESOURCE_DRC_OPEN_UNACCEPTED" if passed
              else "FAIL_IMPLEMENTATION_REVIEW")
    return {
        "status": status,
        "frequency_mhz": frequency,
        "metrics": metrics,
        "routed_resources": resources,
        "route": route,
        "timing_summary": timing,
        "pulse_width_slacks_ns": pulse,
        "check_timing": check_timing,
        "dsp48e1_census": dsp_census,
        "drc_review": drc_review,
        "checks": {
            "route_complete": route_complete, "timing_pass": timing_pass,
            "all_check_timing_categories_zero": constraints_pass,
            "resource_screen_pass": resource_pass, "fixture_observability_pass": fixture_pass,
            "source_hashes_stable": source_stable,
        },
        "source_sha256": expected_hashes,
        "source_sha256_after": source_after,
        "physical_board_tested": False,
        "board_eligible": False,
        "bitstream_created": False,
        "fps_measured": False,
        "drc_accepted": False,
        "scope": "Routed standalone synchronous component fixture only; no PS7, board I/O pin map, DDR, DMA, full model, or physical-board timing signoff",
        "numeric_equivalence": "Independent frozen XSim evidence is retained separately; this report does not replace all-output numeric simulation",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frequency", type=int, choices=(100, 150), default=100)
    parser.add_argument("--baseline-100", type=Path, help="required to run150MHz after a same-source 100MHz timing/resource pass")
    parser.add_argument("--vivado", type=Path, default=VIVADO_DEFAULT)
    parser.add_argument("--run-vivado", action="store_true",
                        help="after the fixture smoke, run implementation; use only after root clears the separate numeric gate")
    args = parser.parse_args()
    try:
        if ROOT not in FIXTURE.resolve().parents:
            raise ValueError("Fixture escaped the project root")
        if args.frequency == 150 and (args.baseline_100 is None or not args.run_vivado):
            raise ValueError("150MHz requires --baseline-100 from a genuine same-source 100MHz pass")
        if not args.vivado.is_file():
            raise FileNotFoundError(f"Vivado 2026.1 launcher not found: {args.vivado}")
        tool_dir = args.vivado.resolve().parent
        for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
            if not (tool_dir / tool).is_file():
                raise FileNotFoundError(f"Required XSim 2026.1 tool not found: {tool_dir / tool}")
        hashes = source_hashes()
        baseline = prior_100_pass(args.baseline_100, hashes) if args.frequency == 150 else None
    except Exception as exc:
        parser.error(str(exc))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    launch = {
        "status": "RUNNING", "run_id": run_id, "frequency_mhz": args.frequency,
        "part": "xc7z100ffg900-2", "vivado_launcher": str(args.vivado.resolve()),
        "source_sha256": hashes, "build_dir": str(build), "evidence_dir": str(evidence),
        "threads": 2, "board_access": False, "bitstream_creation": False,
        "numeric_gate_status": "50-case frozen XSim pass is separate evidence; the fixture smoke does not establish arithmetic equivalence",
        "numeric_gate_snapshot": NUMERIC_GATE_RUN,
        "numeric_gate_rtl_sha256": FROZEN_RTL_SHA256,
        "numeric_gate_tb_sha256": NUMERIC_GATE_TB_SHA256,
        "implementation_requested": args.run_vivado,
        "prior_100_run": (str(args.baseline_100.resolve()) if baseline is not None else None),
    }
    (evidence / "launch.json").write_text(json.dumps(launch, indent=2) + "\n", encoding="utf-8")

    smoke = run_fixture_smoke(evidence, build, tool_dir, hashes)
    launch["timing_fixture_smoke"] = smoke
    smoke_pass = smoke.get("status") == "PASS"
    if not smoke_pass:
        result: dict[str, Any] = dict(launch)
        result["status"] = "TIMING_FIXTURE_SMOKE_FAILED"
        result["artifact_sha256"] = {
            str(path.relative_to(ROOT)): sha256(path)
            for path in sorted(evidence.rglob("*")) if path.is_file() and path.name != "result.json"
        }
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "run_id": run_id,
                          "report": str(evidence / "result.json")}))
        return 2

    if not args.run_vivado:
        result = dict(launch)
        result["status"] = "PASS_TIMING_FIXTURE_SMOKE_ONLY"
        result["artifact_sha256"] = {
            str(path.relative_to(ROOT)): sha256(path)
            for path in sorted(evidence.rglob("*")) if path.is_file() and path.name != "result.json"
        }
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "run_id": run_id,
                          "report": str(evidence / "result.json"), "vivado_run": False}))
        return 0

    command = [str(args.vivado.resolve()), "-mode", "batch", "-log", str(evidence / "vivado.log"),
               "-journal", str(evidence / "vivado.jou"), "-source", str(TCL), "-tclargs",
               str(args.frequency), str(build), str(evidence)]
    vivado_result = run_command(command, ROOT, evidence / "stdout.log")
    launch["vivado"] = {key: value for key, value in vivado_result.items() if key != "output"}

    result: dict[str, Any] = dict(launch)
    result["status"] = "VIVADO_EXECUTION_FAILED" if vivado_result["return_code"] else "VIVADO_COMPLETED_REVIEW_PENDING"
    if vivado_result["return_code"] == 0:
        try:
            result.update(review_outputs(evidence, args.frequency, hashes, vivado_result))
        except Exception as exc:
            result["status"] = "EVIDENCE_PARSE_OR_REVIEW_FAILED"
            result["review_error"] = f"{type(exc).__name__}: {exc}"
    result["artifact_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted(evidence.rglob("*")) if path.is_file() and path.name != "result.json"
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "run_id": run_id,
                      "report": str(evidence / "result.json"),
                      "vivado_return_code": vivado_result["return_code"]}))
    return 0 if result["status"] == f"PASS_{args.frequency}MHZ_COMPONENT_TIMING_RESOURCE_DRC_OPEN_UNACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
