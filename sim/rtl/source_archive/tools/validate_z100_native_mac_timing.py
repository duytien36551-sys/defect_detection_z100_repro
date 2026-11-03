"""Prepare and validate the standalone native-window MAC timing fixture.

Default mode performs host-only source/timing-contract/reference preflight.
Vendor runs are opt-in and must be separately authorized before invocation.
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
FIXTURE_DIR = RTL_DIR / "native_mac_timing_v1"
CORE_RTL = RTL_DIR / "window_mac_v1/z100_window_mac.sv"
TOP_RTL = FIXTURE_DIR / "z100_native_mac_timing_top.sv"
TB_RTL = FIXTURE_DIR / "tb_z100_native_mac_timing.sv"
SIM_BUFG = RTL_DIR / "reuse_sync_fixture/sim_bufg.v"
XDC = FIXTURE_DIR / "native_mac_timing_constraints.xdc"
IMPL_TCL = FIXTURE_DIR / "native_mac_timing_impl.tcl"
SELF = Path(__file__).resolve()
PYTHON = ROOT / '.venv/Scripts/python.exe'
VIVADO_BIN = Path(r"C:\appload\2026.1\Vivado\bin")
CORE_SHA256 = "c2de472f539276da097e5ccd5bc7d44f2695dbff55ecb73458ea0105accbb643"
SIM_BUFG_SHA256 = "c82537f3f4a6025e0f89fd263718b13fcdc52292f0e4fc1dbf7912a98f8e12af"
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
    required = (CORE_RTL, TOP_RTL, TB_RTL, SIM_BUFG, XDC, IMPL_TCL, SELF)
    missing = [rel(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing fixture sources: {missing}")
    hashes = {rel(path): sha256(path) for path in required}
    if hashes[rel(CORE_RTL)] != CORE_SHA256:
        raise ValueError("Frozen native MAC source hash differs from the pinned component")
    if hashes[rel(SIM_BUFG)] != SIM_BUFG_SHA256:
        raise ValueError("Frozen simulation-only BUFG model hash differs from the pinned primitive stub")

    top = TOP_RTL.read_text(encoding="utf-8")
    tb = TB_RTL.read_text(encoding="utf-8")
    xdc = XDC.read_text(encoding="utf-8")
    tcl = IMPL_TCL.read_text(encoding="utf-8")
    for marker in (
        "BUFG clock_buffer", "reset_meta", "reset_local", "FAST_SMOKE",
        "make_weight_byte", "make_activation_byte", "make_bias_word",
        "out_data[(scan_lane * 32) +: 32]", "out_overflow[scan_lane]",
        "monitor_token", "monitor_lanes", "monitor_last",
    ):
        if marker not in top:
            raise ValueError(f"Top is missing required structural marker {marker!r}")
    for marker in (
        "group_index[7:0] ^ {5'd0, group_index[10:8]}",
        "lane_index[7:0] ^ {4'd0, tap_index[3:0]} ^ {6'd0, shape}",
        "((lane_index * 37 + shape * 101) & 2047) - 1024",
        "wire final_output_lane = scan_lane == 5'd31",
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

    normalized_xdc = "\n".join(line.strip() for line in xdc.splitlines() if line.strip() and not line.lstrip().startswith("#"))
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
    if 'stage eq "ooc"' not in tcl or "NATIVE_MAC_TIMING_OOC_PASS" not in tcl:
        raise ValueError("Implementation Tcl does not provide an OOC-only synthesis stop")
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
               evidence: Path, env: dict[str, str], result: dict) -> str:
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
    if completed.returncode:
        raise RuntimeError(f"{name} returned {completed.returncode}")
    return output


def artifact_hashes(evidence: Path, build: Path) -> dict[str, str]:
    entries = {}
    for folder in (evidence, build):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.name not in {"result.json", "launch.json"}:
                entries[rel(path)] = sha256(path)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-xsim", action="store_true", help="Run the authorized FAST_SMOKE XSim after host preflight")
    parser.add_argument("--run-ooc-100mhz", action="store_true", help="Run FAST_SMOKE XSim then stop Vivado after 100 MHz OOC synthesis/census")
    parser.add_argument("--run-implementation-100mhz", action="store_true", help="Run Vivado 100 MHz synth/place/route after a passing XSim in this invocation")
    args = parser.parse_args()
    if args.run_ooc_100mhz and args.run_implementation_100mhz:
        parser.error("OOC-only synthesis and full implementation are separate validation stages")
    if args.run_implementation_100mhz and not args.run_xsim:
        parser.error("100 MHz implementation requires --run-xsim to pass first in the same run")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/native_mac_timing_v1" / run_id
    build = ROOT / "deployment/build/z100_native_mac_timing_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    result: dict = {
        "status": "RUNNING",
        "run_id": run_id,
        "scope": "standalone frozen 512-product native-window MAC; host preflight, optional FAST_SMOKE XSim, 100 MHz OOC synthesis, or full implementation",
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
        inputs = (CORE_RTL, TOP_RTL, TB_RTL, SIM_BUFG, XDC, IMPL_TCL, SELF)
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

        run_simulation = args.run_xsim or args.run_ooc_100mhz or args.run_implementation_100mhz
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
            xvlog = run_logged("xvlog", [str(VIVADO_BIN / "xvlog.bat"), "-sv",
                                         str(SIM_BUFG), str(CORE_RTL), str(TOP_RTL), str(TB_RTL)],
                               build, evidence, env, result)
            if "ERROR:" in xvlog or "Fatal:" in xvlog:
                raise ValueError("XSim compile log contains an error despite a zero exit status")
            run_logged("xelab", [str(VIVADO_BIN / "xelab.bat"), "-mt", "2",
                                  "tb_z100_native_mac_timing", "-s", "native_mac_timing_sim"],
                       build, evidence, env, result)
            simulation = run_logged("xsim", [str(VIVADO_BIN / "xsim.bat"),
                                             "native_mac_timing_sim", "-runall"],
                                    build, evidence, env, result)
            marker = re.findall(
                r"NATIVE_MAC_TIMING_SMOKE_PASS words=(\d+) runs=(\d+) weight_groups=(\d+) bias_words=(\d+) activation_groups=(\d+) input_bubbles=(\d+) output_stalls=(\d+) overflow_words=(\d+) nonzero_words=(\d+)",
                simulation,
            )
            if len(marker) != 1 or "Fatal:" in simulation or "FATAL:" in simulation:
                raise ValueError("XSim did not complete the native-MAC smoke coverage marker")
            values = list(map(int, marker[0]))
            expected_prefix = [EXPECTED_SMOKE["words"], EXPECTED_SMOKE["runs"],
                               EXPECTED_SMOKE["weight_groups"], EXPECTED_SMOKE["bias_words"],
                               EXPECTED_SMOKE["activation_groups"]]
            if values[:5] != expected_prefix or any(value <= 0 for value in values[5:]):
                raise ValueError(f"XSim smoke coverage differs from host preflight: {values}")
            result["simulation"] = {
                "status": "PASS",
                "words": values[0], "runs": values[1], "weight_groups": values[2],
                "bias_words": values[3], "activation_groups": values[4],
                "input_bubbles": values[5], "output_stalls": values[6],
                "overflow_words": values[7], "nonzero_words": values[8],
                "checked": ["all serialized 32-bit lane values and overflow flags",
                            "token/site/lane/lane-count/last metadata",
                            "output stability during backpressure",
                            "two resident-weight replays for each shape",
                            "traffic counts and reset/done status"],
            }

        if args.run_ooc_100mhz or args.run_implementation_100mhz:
            vivado = VIVADO_BIN / "vivado.bat"
            if not vivado.is_file():
                raise FileNotFoundError(f"Missing Vivado implementation executable: {vivado}")
            command = [str(vivado), "-mode", "batch", "-log", str(evidence / "vivado.log"),
                       "-journal", str(evidence / "vivado.jou"), "-source", str(IMPL_TCL),
                       "-tclargs", "100", str(build), str(evidence),
                       "ooc" if args.run_ooc_100mhz else "route"]
            stage = "ooc" if args.run_ooc_100mhz else "implementation"
            implementation = run_logged(f"vivado_100mhz_{stage}", command, build, evidence, env, result)
            if args.run_ooc_100mhz:
                match = re.findall(
                    r"NATIVE_MAC_TIMING_OOC_PASS frequency_mhz=100 lut=(\d+) ff=(\d+) dsp_total=(\d+) dsp_multiply=(\d+) dsp_none=(\d+) bram36_equivalent=([^ ]+) bufg=(\d+) latches=(\d+) blackboxes=(\d+)",
                    implementation,
                )
                observability_path = evidence / "synth_observability.txt"
                if len(match) != 1 or "NATIVE_MAC_TIMING_FAIL" in implementation:
                    raise ValueError("Vivado did not report a completed 100 MHz OOC synthesis census")
                if not observability_path.is_file() or "BLACKBOX_COUNT 0" not in observability_path.read_text(encoding="utf-8"):
                    raise ValueError("OOC synthesis observability report is missing or has a black box")
                fields = match[0]
                lut, ff, dsp, multiply, none = map(int, fields[:5])
                bram = float(fields[5])
                bufg, latches, blackboxes = map(int, fields[6:])
                if (lut > 40000 or ff > 25000 or dsp != 640 or multiply != 512 or none != 128 or
                        not 28.0 <= bram <= 40.0 or bufg != 1 or latches != 0 or blackboxes != 0):
                    raise ValueError(f"Vivado OOC result violates fixed synthesis screen: {fields}")
                result["ooc_synthesis"] = {
                    "status": "PASS",
                    "frequency_mhz": 100,
                    "lut": lut, "ff": ff, "dsp_total": dsp,
                    "dsp_multiply": multiply, "dsp_none": none,
                    "bram36_equivalent": bram, "bufg": bufg,
                    "latches": latches, "blackboxes": blackboxes,
                    "checkpoint": rel(build / "post_synth.dcp"),
                    "observability_report": rel(observability_path),
                }
            else:
                match = re.findall(
                    r"NATIVE_MAC_TIMING_IMPL_PASS frequency_mhz=100 setup_slack_ns=([^ ]+) hold_slack_ns=([^ ]+) pulse_checks=(\d+) routable=(\d+) routed=(\d+) route_errors=(\d+) lut=(\d+) ff=(\d+) dsp_total=(\d+) dsp_multiply=(\d+) dsp_none=(\d+) bram36_equivalent=([^ ]+) bufg=(\d+)",
                    implementation,
                )
                if len(match) != 1 or "NATIVE_MAC_TIMING_FAIL" in implementation:
                    raise ValueError("Vivado did not report a completed 100 MHz implementation screen")
                fields = match[0]
                setup, hold = float(fields[0]), float(fields[1])
                pulse_checks, routable, routed, route_errors = map(int, fields[2:6])
                lut, ff, dsp, multiply, none = map(int, fields[6:11])
                bram, bufg = float(fields[11]), int(fields[12])
                if (setup < 0 or hold < 0 or pulse_checks < 3 or routable != routed or route_errors != 0 or
                        lut > 40000 or ff > 25000 or dsp != 640 or multiply != 512 or none != 128 or
                        not 28.0 <= bram <= 40.0 or bufg != 1):
                    raise ValueError(f"Vivado result violates fixed 100 MHz implementation screen: {match[0]}")
                result["implementation"] = {
                    "status": "PASS",
                    "frequency_mhz": 100,
                    "setup_slack_ns": setup,
                    "hold_slack_ns": hold,
                    "pulse_checks": pulse_checks,
                    "routable_nets": routable,
                    "fully_routed_nets": routed,
                    "route_errors": route_errors,
                    "lut": lut, "ff": ff, "dsp_total": dsp,
                    "dsp_multiply": multiply, "dsp_none": none,
                    "bram36_equivalent": bram, "bufg": bufg,
                    "check_timing_zero_categories": 12,
                }

        after_hashes = {rel(path): sha256(path) for path in inputs}
        if after_hashes != source_hashes:
            raise ValueError("Source-bound dependencies changed during the validation run")
        result["source_sha256_after"] = after_hashes
        if args.run_implementation_100mhz:
            result["status"] = "PASS_NATIVE_MAC_100MHZ_IMPLEMENTATION_SCREEN"
        elif args.run_ooc_100mhz:
            result["status"] = "PASS_NATIVE_MAC_100MHZ_OOC_SYNTH_SCREEN"
        elif args.run_xsim:
            result["status"] = "PASS_NATIVE_MAC_FAST_SMOKE_XSIM_ONLY"
        else:
            result["status"] = "PASS_NATIVE_MAC_HOST_PREFLIGHT_VENDOR_NOT_RUN"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["source_sha256_after"] = {
            rel(path): sha256(path) for path in (CORE_RTL, TOP_RTL, TB_RTL, SIM_BUFG, XDC, IMPL_TCL, SELF)
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
