"""Simulate and synthesize the private512KiB two-read-port feature store.

Use --wait-for-vivado-slot when queued behind the existing implementation
jobs. No board access, bitstream generation or production source changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "deployment/hardware/z100_2026/feature_banks_v1"
VIVADO = Path("C:/appload/2026.1/Vivado/bin/vivado.bat")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-for-vivado-slot", action="store_true")
    args = parser.parse_args()
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    if args.wait_for_vivado_slot:
        while True:
            count = subprocess.check_output(["powershell", "-NoProfile", "-Command",
                "@(Get-Process vivado -ErrorAction SilentlyContinue).Count"], text=True)
            if int(count.strip()) < 2:
                break
            time.sleep(30)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"_"+uuid.uuid4().hex[:8]
    evidence = ROOT/"validation/board_z100/feature_banks_v1"/run_id
    build = ROOT/"deployment/build/z100_feature_banks_v1"/run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    sources = (FIXTURE/"z100_feature_banks.sv", FIXTURE/"tb_z100_feature_banks.sv", Path(__file__))
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    result = {"status": "RUNNING", "run_id": run_id, "source_sha256": hashes,
        "board_access": False, "route_attempted": False, "bitstream_created": False,
        "synthesis_budget": {"bram36_equivalent": 128, "dsp": 0, "lut_max": 6000, "ff_max": 4096},
        "commands": []}
    (evidence/"launch.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")

    def run(name, command):
        completed = subprocess.run(command, cwd=build, env=env, text=True,
            encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (evidence/(name+".log")).write_text(completed.stdout, encoding="utf-8")
        result["commands"].append({"name": name, "args": list(map(str, command)), "return_code": completed.returncode})
        if completed.returncode:
            raise RuntimeError(f"{name} returned{completed.returncode}")
        return completed.stdout

    try:
        # Full scalar/halo/address tests are independent of this RAM RTL.
        run("host_layout_tests", [sys.executable, "-B", "-X", "utf8", "-m", "unittest", "discover",
            "-s", str(ROOT/"tests"), "-p", "test_z100_feature_window_layout.py", "-v"])
        bindir = VIVADO.parent
        run("xvlog", [str(bindir/"xvlog.bat"), "-sv", str(sources[0]), str(sources[1])])
        run("xelab", [str(bindir/"xelab.bat"), "-mt", "2", "tb_z100_feature_banks", "-s", "feature_banks_sim"])
        sim = run("xsim", [str(bindir/"xsim.bat"), "feature_banks_sim", "-runall"])
        marker = re.findall(r"FEATURE_BANKS_PASS words_written=(\d+) responses=(\d+) stalls=(\d+) errors=(\d+) full_capacity_bytes=(\d+)", sim)
        if len(marker) != 1 or "Fatal:" in sim:
            raise ValueError("Simulation did not produce exactly one successful coverage marker")
        words, responses, stalls, errors, capacity = map(int, marker[0])
        if (words, responses, errors, capacity) != (8200, 1057, 5, 524288) or stalls <= 0:
            raise ValueError(f"Simulation coverage differs: {marker[0]}")
        result["simulation"] = {"status": "PASS", "words_written": words, "responses": responses,
            "stalled_cycles": stalls, "errors": errors, "full_capacity_bytes": capacity,
            "ports_read": 128, "same_bank_two_independent_addresses": True,
            "continuous_result_interval_cycles": 1, "reset_cancel_recovery": True}
        # Generate Tcl with absolute brace-quoted paths (not shell expansion).
        tcl = build/"synth.tcl"
        text = '''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {%s}
synth_design -top z100_feature_banks -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none
create_clock -name feature_clk -period 10.000 [get_ports clk]
report_utilization -file {%s}
report_utilization -hierarchical -file {%s}
report_timing_summary -delay_type min_max -report_unconstrained -file {%s}
write_checkpoint -force {%s}
set lut [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]
set ff [llength [get_cells -hier -filter {REF_NAME =~ FD*}]]
set ram36 [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]
set ram18 [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]
set dsp [llength [get_cells -hier -filter {REF_NAME =~ DSP*}]]
set latch [llength [get_cells -hier -filter {REF_NAME =~ LD*}]]
set blackbox [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]
puts "FEATURE_BANKS_SYNTH lut=$lut ff=$ff ram36=$ram36 ram18=$ram18 dsp=$dsp latch=$latch blackbox=$blackbox"
exit
''' % tuple(p.as_posix() for p in (sources[0], evidence/"utilization.rpt", evidence/"hierarchical.rpt",
                                   evidence/"timing_synth.rpt", build/"post_synth.dcp"))
        tcl.write_text(text, encoding="utf-8")
        synth = run("synth", [str(VIVADO), "-mode", "batch", "-log", str(evidence/"vivado.log"),
            "-journal", str(evidence/"vivado.jou"), "-source", str(tcl)])
        matches = re.findall(r"FEATURE_BANKS_SYNTH lut=(\d+) ff=(\d+) ram36=(\d+) ram18=(\d+) dsp=(\d+) latch=(\d+) blackbox=(\d+)", synth)
        if len(matches) != 1:
            raise ValueError("Synthesis resource census missing or repeated")
        lut, ff, ram36, ram18, dsp, latch, blackbox = map(int, matches[0])
        result["synthesis"] = dict(lut=lut, ff=ff, ram36=ram36, ram18=ram18,
            bram36_equivalent=ram36+ram18/2, dsp=dsp, latch=latch, blackbox=blackbox)
        if lut > 6000 or ff > 4096 or ram36+ram18/2 != 128 or dsp or latch or blackbox:
            raise ValueError("Actual mapping failed the fixed resource screen")
        if hashes != {str(p.relative_to(ROOT)): sha(p) for p in sources}:
            raise ValueError("Source changed during validation")
        result["status"] = "PASS_PRIVATE_FEATURE_BANKS_XSIM_OOC_SYNTH_ONLY"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["source_sha256_after"] = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    result["artifact_sha256"] = {str(p.relative_to(ROOT)): sha(p)
        for folder in (evidence, build) for p in sorted(folder.glob("*"))
        if p.is_file() and p.name != "result.json"}
    (evidence/"result.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(evidence/"result.json"),
        "error": result.get("error")}), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
