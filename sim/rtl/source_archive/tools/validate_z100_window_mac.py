"""Run the private native-window MAC reference simulation and OOC synth screen.

This flow is component evidence only. It does not replicate, route, or integrate
the MAC with production RTL or firmware.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "deployment/hardware/z100_2026/window_mac_v1"
RTL = FIXTURE / "z100_window_mac.sv"
TB = FIXTURE / "tb_z100_window_mac.sv"
VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
PART = "xc7z100ffg900-2"
MAX_THREADS = 2


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_logged(name: str, command: list[str], cwd: Path, env: dict[str, str], evidence: Path,
               result: dict) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout
    (evidence / f"{name}.log").write_text(output, encoding="utf-8")
    result["commands"].append({"name": name, "args": list(map(str, command)),
                               "return_code": completed.returncode})
    if completed.returncode:
        raise RuntimeError(f"{name} returned {completed.returncode}")
    return output


def make_synthesis_tcl(evidence: Path, build: Path) -> Path:
    tcl = r'''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {@RTL@}
synth_design -top z100_window_mac -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none
create_clock -name mac_clk -period 10.000 [get_ports clk]
report_utilization -file {@UTIL@}
report_utilization -hierarchical -file {@HIER@}
report_timing_summary -delay_type min_max -report_unconstrained -file {@TIMING@}
write_checkpoint -force {@DCP@}
set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
set ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
set ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
set dsps [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]
set dsp48 [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]
set latch [llength [get_cells -quiet -hier -filter {REF_NAME =~ LD*}]]
set blackboxes [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]
array set use_mult_counts {}
set census [open {@DSP_CENSUS@} w]
puts $census "cell\tAREG\tBREG\tMREG\tPREG\tUSE_MULT\tUSE_SIMD"
foreach cell $dsp48 {
    set name [get_property NAME $cell]
    set values {}
    foreach property {AREG BREG MREG PREG USE_MULT USE_SIMD} {
        set value [get_property -quiet $property $cell]
        if {$value eq ""} {set value "UNAVAILABLE"}
        lappend values $value
    }
    set mode [string toupper [lindex $values 4]]
    if {![info exists use_mult_counts($mode)]} {set use_mult_counts($mode) 0}
    incr use_mult_counts($mode)
    puts $census "$name\t[join $values \t]"
}
close $census
set multiply 0
if {[info exists use_mult_counts(MULTIPLY)]} {set multiply $use_mult_counts(MULTIPLY)}
set dsp_other [expr {[llength $dsp48] - $multiply}]
set bram36eq [expr {$ram36 + $ram18 / 2.0}]
set f [open {@DSP_SUMMARY@} w]
puts $f "DSP_TOTAL [llength $dsps]"
puts $f "DSP48E1_COUNT [llength $dsp48]"
foreach mode [lsort [array names use_mult_counts]] {puts $f "USE_MULT $mode $use_mult_counts($mode)"}
close $f
set obs [open {@OBSERVABILITY@} w]
puts $obs "BLACKBOX_COUNT [llength $blackboxes]"
puts $obs "DSP_TOTAL [llength $dsps]"
puts $obs "DSP48E1_COUNT [llength $dsp48]"
puts $obs "DSP_MULTIPLY_COUNT $multiply"
puts $obs "DSP_OTHER_MODE_COUNT $dsp_other"
puts $obs "LATCH_COUNT $latch"
close $obs
puts "WINDOW_MAC_SYNTH version=[version -short] part=xc7z100ffg900-2 lut=$lut ff=$ff ram36=$ram36 ram18=$ram18 bram36eq=$bram36eq dsp_total=[llength $dsps] dsp48=[llength $dsp48] dsp_multiply=$multiply dsp_other=$dsp_other latches=$latch blackbox=[llength $blackboxes]"
if {$lut > 40000 || $ff > 25000 || $bram36eq < 28.0 || $bram36eq > 40.0 || [llength $dsps] != 512 || [llength $dsp48] != 512 || $multiply != 512 || $dsp_other != 0 || $latch != 0 || [llength $blackboxes] != 0} {
    error "Native-window MAC failed the fixed OOC component screen"
}
exit
'''
    replacements = {
        "@RTL@": RTL.as_posix(),
        "@UTIL@": (evidence / "utilization.rpt").as_posix(),
        "@HIER@": (evidence / "hierarchical_utilization.rpt").as_posix(),
        "@TIMING@": (evidence / "synth_timing.rpt").as_posix(),
        "@DCP@": (build / "post_synth.dcp").as_posix(),
        "@DSP_CENSUS@": (evidence / "dsp48e1_census.tsv").as_posix(),
        "@DSP_SUMMARY@": (evidence / "dsp48e1_summary.txt").as_posix(),
        "@OBSERVABILITY@": (evidence / "observability.txt").as_posix(),
    }
    for marker, value in replacements.items():
        tcl = tcl.replace(marker, value)
    path = evidence / "synth.tcl"
    path.write_text(tcl, encoding="utf-8")
    return path


def main() -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/window_mac_v1" / run_id
    build = ROOT / "deployment/build/z100_window_mac_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)

    source_paths = (RTL, TB, Path(__file__).resolve())
    source_hashes = {str(path.relative_to(ROOT)): sha256(path) for path in source_paths}
    snapshot = evidence / "source_snapshot"
    snapshot.mkdir()
    for path in source_paths:
        shutil.copy2(path, snapshot / path.name)

    result: dict = {
        "status": "RUNNING",
        "run_id": run_id,
        "scope": "private native-window MAC; XSim then OOC synthesis only",
        "sources_sha256": source_hashes,
        "source_snapshot": str(snapshot),
        "device_part": PART,
        "toolchain": {"vivado_bin": str(VIVADO_BIN), "python": sys.executable,
                      "max_threads": MAX_THREADS, "numerical_threads": 1},
        "limits": {"dsp48e1_multiply_exact": 512, "bram36_equivalent": [28, 40],
                   "lut_max": 40000, "ff_max": 25000, "latches": 0, "blackboxes": 0},
        "board_access": False,
        "route_attempted": False,
        "bitstream_created": False,
        "commands": [],
    }
    (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    bindir = VIVADO_BIN

    try:
        for tool in ("xvlog.bat", "xelab.bat", "xsim.bat", "vivado.bat"):
            path = bindir / tool
            if not path.is_file():
                raise FileNotFoundError(f"Missing Vivado2026.1 executable: {path}")
        for path in source_paths:
            if not path.is_file():
                raise FileNotFoundError(f"Missing source: {path}")

        compile_output = run_logged("xvlog", [str(bindir / "xvlog.bat"), "-sv", str(RTL), str(TB)],
                                    build, env, evidence, result)
        if "overflow of 32-bit signed integer" in compile_output:
            raise ValueError("Testbench contains an overflowing 32-bit signed boundary constant")
        run_logged("xelab", [str(bindir / "xelab.bat"), "-mt", str(MAX_THREADS),
                              "tb_z100_window_mac", "-s", "window_mac_sim"],
                   build, env, evidence, result)
        sim_output = run_logged("xsim", [str(bindir / "xsim.bat"), "window_mac_sim", "-runall"],
                                build, env, evidence, result)
        marker = re.findall(
            r"WINDOW_MAC_PASS jobs=(\d+) replays=(\d+) raw_words=(\d+) overflow_flags=(\d+) "
            r"metadata_sites=(\d+) stalls=(\d+) stream_errors=(\d+) config_errors=(\d+) "
            r"run_errors=(\d+) cross_checks=(\d+) saturation_checks=(\d+) "
            r"cancel_offsets=(\d+) reset_offsets=(\d+) max_groups=(\d+)",
            sim_output,
        )
        if len(marker) != 1 or "Fatal:" in sim_output or "FATAL:" in sim_output:
            fatal_line = next((line.strip() for line in sim_output.splitlines()
                               if "Fatal:" in line or "FATAL:" in line), "coverage marker missing")
            raise ValueError(f"XSim failed numerical coverage: {fatal_line}")
        names = ("jobs", "replays", "raw_words", "overflow_flags", "metadata_sites", "stalls",
                 "stream_errors", "config_errors", "run_errors", "cross_checks", "saturation_checks",
                 "cancel_offsets", "reset_offsets", "max_groups")
        simulation = dict(zip(names, map(int, marker[0])))
        expected = {"jobs": 50, "replays": 25, "raw_words": 5152, "overflow_flags": 5152,
                    "metadata_sites": 161, "stream_errors": 3, "config_errors": 7,
                    "run_errors": 6, "cancel_offsets": 5, "reset_offsets": 5, "max_groups": 1024}
        for name, value in expected.items():
            if simulation[name] != value:
                raise ValueError(f"XSim coverage {name}={simulation[name]}, expected {value}")
        if simulation["stalls"] <= 0 or simulation["cross_checks"] <= 0 or simulation["saturation_checks"] <= 0:
            raise ValueError("XSim omitted stalls or signed-boundary coverage")
        simulation.update({
            "status": "PASS",
            "reference": "independent signed 64-bit scalar sum, per site/output lane",
            "checked": ["every output data word", "every overflow flag", "token/site/lanes/last metadata",
                        "stalled output stability", "configuration and run errors", "cancel/reset recovery",
                        "late malformed stream rejection"],
        })
        result["simulation"] = simulation

        tcl = make_synthesis_tcl(evidence, build)
        synth_output = run_logged(
            "vivado_ooc_synth",
            [str(bindir / "vivado.bat"), "-mode", "batch", "-log", str(evidence / "vivado.log"),
             "-journal", str(evidence / "vivado.jou"), "-source", str(tcl)],
            build, env, evidence, result,
        )
        synth_markers = re.findall(
            r"WINDOW_MAC_SYNTH version=(\S+) part=(\S+) lut=(\d+) ff=(\d+) ram36=(\d+) "
            r"ram18=(\d+) bram36eq=([0-9.]+) dsp_total=(\d+) dsp48=(\d+) "
            r"dsp_multiply=(\d+) dsp_other=(\d+) latches=(\d+) blackbox=(\d+)",
            synth_output,
        )
        if len(synth_markers) != 1:
            raise ValueError("Vivado did not emit exactly one OOC primitive census marker")
        fields = ("vivado_version", "part", "lut", "ff", "ram36", "ram18", "bram36_equivalent",
                  "dsp_total", "dsp48e1", "dsp_multiply", "dsp_other_modes", "latches", "blackboxes")
        raw = dict(zip(fields, synth_markers[0]))
        synthesis = {key: (float(value) if key == "bram36_equivalent" else
                           value if key in ("vivado_version", "part") else int(value))
                     for key, value in raw.items()}
        if not synthesis["vivado_version"].startswith("2026.1") or synthesis["part"] != PART:
            raise ValueError("OOC synthesis used an unexpected Vivado version or device")
        if (synthesis["dsp_total"] != 512 or synthesis["dsp48e1"] != 512 or
                synthesis["dsp_multiply"] != 512 or synthesis["dsp_other_modes"] != 0):
            raise ValueError("Primitive census did not map exactly 512 products to DSP48E1 MULTIPLY")
        if not 28.0 <= synthesis["bram36_equivalent"] <= 40.0:
            raise ValueError("BRAM36-equivalent count fell outside 28..40")
        if synthesis["lut"] > 40000 or synthesis["ff"] > 25000:
            raise ValueError("OOC LUT or FF count exceeded the component screen")
        if synthesis["latches"] != 0 or synthesis["blackboxes"] != 0:
            raise ValueError("OOC netlist contains inferred latches or black boxes")
        if not (evidence / "dsp48e1_census.tsv").is_file() or not (evidence / "utilization.rpt").is_file():
            raise ValueError("Expected primitive census or utilization report is missing")
        synthesis["status"] = "PASS"
        result["synthesis"] = synthesis
        result["status"] = "PASS_PRIVATE_WINDOW_MAC_XSIM_OOC_SYNTH_ONLY"
    except Exception as exc:  # Persist failure evidence, but never turn it into a pass.
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"

    final_hashes = {str(path.relative_to(ROOT)): sha256(path) for path in source_paths if path.is_file()}
    result["sources_sha256_after"] = final_hashes
    if final_hashes != source_hashes and result["status"].startswith("PASS_"):
        result["status"] = "FAILED_CLOSED"
        result["error"] = "A source changed during the validation run"
    result["artifact_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path)
        for folder in (evidence, build)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name not in {"result.json", "launch.json"}
    }
    report = evidence / "result.json"
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(report),
                      "error": result.get("error")}), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
