"""Check native window reads against independent CHW samples, then OOC synth."""
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

from z100_feature_window_layout import FeatureLayout

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/"deployment/hardware/z100_2026/feature_window_v1"
BANK_RTL = ROOT/"deployment/hardware/z100_2026/feature_banks_v1/z100_feature_banks.sv"
VIVADO = Path("C:/appload/2026.1/Vivado/bin/vivado.bat")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_vectors(build):
    c, h, w = 7, 8, 40
    source = bytes(((i*17)^(i>>7)^(i//(h*w)*113)) & 255 for i in range(c*h*w))
    layout = FeatureLayout(c, h, w)
    packed = layout.pack(source)
    (build/"load_words.hex").write_text("".join(f"{int.from_bytes(packed[i:i+64], 'little'):0128x}\n"
        for i in range(0,len(packed),64)), encoding="ascii")
    vectors = []
    for kernel, stride, padding in ((3,1,1),(3,2,1),(1,1,0)):
        oh=(h+2*padding-kernel)//stride+1
        ow=(w+2*padding-kernel)//stride+1
        for oy in range(oh):
            for ox in range(0,ow,12):
                sites=min(12,ow-ox)
                for cb in range(0,c,4):
                    cmask=(1 << min(4,c-cb))-1
                    for ky in range(kernel):
                        iy=oy*stride+ky-padding
                        yvalid=0 <= iy < h
                        row=((cb//4)*h+iy)*layout.x_words if yvalid else 0
                        for kx in range(kernel):
                            firstx=ox*stride+kx-padding
                            tag=len(vectors)
                            packet=(tag | (1<<32) | (row<<64) | ((firstx&4095)<<78) |
                                (w<<90) | (sites<<101) | (cmask<<105) | ((stride==2)<<109) |
                                (yvalid<<110) | ((ow-ox)<<111))
                            data=0; mask=0
                            # Expected values use only original CHW indexing,
                            # never bank/port addresses or the RTL mapping.
                            for lane in range(4):
                                for site in range(12):
                                    channel=cb+lane
                                    ix=(ox+site)*stride+kx-padding
                                    index=lane*12+site
                                    if site<sites and channel<c and yvalid and 0<=ix<w:
                                        data |= source[(channel*h+iy)*w+ix] << (index*8)
                                        mask |= 1<<index
                            vectors.append(packet | (mask<<128) | (data<<176))
    (build/"window_vectors.hex").write_text("".join(f"{v:0144x}\n" for v in vectors), encoding="ascii")
    (build/"window_counts.svh").write_text(f"localparam integer LOAD_WORDS={layout.words};\nlocalparam integer VECTOR_COUNT={len(vectors)};\n", encoding="ascii")
    return {"vectors":len(vectors), "load_words":layout.words, "shape":[c,h,w],
            "source_sha256":hashlib.sha256(source).hexdigest(),
            "expected_values_from_direct_chw":True, "kernel_stride_pairs":[[3,1],[3,2],[1,1]]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-for-bank-pass", action="store_true")
    parser.add_argument("--bank-report", type=Path, required=True,
                        help="Exact bank result.json dependency; older failed runs are never substituted")
    args=parser.parse_args()
    dependency=args.bank_report.resolve()
    if ROOT/"validation/board_z100/feature_banks_v1" not in dependency.parents or dependency.name!="result.json":
        parser.error("Bank dependency must be an exact result.json under this project's feature-bank evidence")
    if args.wait_for_bank_pass:
        # This dependency is part of the queue: do not consume a third vendor
        # slot while the two older resident-core implementations are running.
        while True:
            if dependency.is_file():
                dep=json.loads(dependency.read_text(encoding="utf-8"))
                if dep.get("status")!="PASS_PRIVATE_FEATURE_BANKS_XSIM_OOC_SYNTH_ONLY":
                    raise RuntimeError(f"Feature-bank dependency did not pass: {dependency}")
                if dep["source_sha256"].get(str(BANK_RTL.relative_to(ROOT))) != sha(BANK_RTL):
                    raise RuntimeError("Passing bank source differs from the requested window dependency")
                break
            time.sleep(30)
    else:
        parser.error("--wait-for-bank-pass is required before hardware window validation")
    while True:
        count=subprocess.check_output(["powershell","-NoProfile","-Command",
            "@(Get-Process vivado -ErrorAction SilentlyContinue).Count"],text=True)
        if int(count.strip())<2: break
        time.sleep(30)
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"_"+uuid.uuid4().hex[:8]
    evidence=ROOT/"validation/board_z100/feature_window_v1"/run_id
    build=ROOT/"deployment/build/z100_feature_window_v1"/run_id
    evidence.mkdir(parents=True,exist_ok=False); build.mkdir(parents=True,exist_ok=False)
    sources=(BANK_RTL,FIXTURE/"z100_feature_window.sv",FIXTURE/"tb_z100_feature_window.sv",
             ROOT/"tools/z100_feature_window_layout.py",Path(__file__))
    hashes={str(p.relative_to(ROOT)):sha(p) for p in sources}
    result={"status":"RUNNING","run_id":run_id,"source_sha256":hashes,"commands":[],
            "dependency_report":str(dependency.relative_to(ROOT)),"dependency_sha256":sha(dependency),
            "board_access":False,"route_attempted":False,"bitstream_created":False}
    env=dict(os.environ)
    for key in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS","NUMEXPR_NUM_THREADS"): env[key]="1"
    def run(name,command):
        proc=subprocess.run(command,cwd=build,env=env,text=True,encoding="utf-8",errors="replace",
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (evidence/(name+".log")).write_text(proc.stdout,encoding="utf-8")
        result["commands"].append({"name":name,"args":list(map(str,command)),"return_code":proc.returncode})
        if proc.returncode: raise RuntimeError(f"{name} returned{proc.returncode}")
        return proc.stdout
    try:
        vectors=generate_vectors(build)
        result["reference"]=vectors
        (evidence/"launch.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        bindir=VIVADO.parent
        run("xvlog",[str(bindir/"xvlog.bat"),"-sv",str(BANK_RTL),str(sources[1]),str(sources[2])])
        run("xelab",[str(bindir/"xelab.bat"),"-mt","2","tb_z100_feature_window","-s","feature_window_sim"])
        sim=run("xsim",[str(bindir/"xsim.bat"),"feature_window_sim","-runall"])
        rows=re.findall(r"FEATURE_WINDOW_PASS vectors=(\d+) results=(\d+) stalls=(\d+) max_consecutive=(\d+) geometry_errors=1 cancel_full=1",sim)
        if len(rows)!=1 or "Fatal:" in sim: raise ValueError("Window simulation coverage marker missing")
        sent,received,stalls,streak=map(int,rows[0])
        if sent!=vectors["vectors"] or received!=sent or stalls<=0 or streak<8:
            raise ValueError("Window coverage mismatch")
        result["simulation"]={"status":"PASS","vectors":sent,"results":received,"stalls":stalls,
            "max_consecutive_results":streak,"geometry_error_rejected":True,"cancel_two_slots":True}
        tcl=build/"synth.tcl"
        tcl.write_text('''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {%s}
read_verilog -sv {%s}
synth_design -top z100_feature_window -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none
create_clock -name window_clk -period 10.000 [get_ports clk]
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
puts "FEATURE_WINDOW_SYNTH lut=$lut ff=$ff ram36=$ram36 ram18=$ram18 dsp=$dsp latch=$latch blackbox=$blackbox"
exit
''' % tuple(p.as_posix() for p in (BANK_RTL,sources[1],evidence/"utilization.rpt",
            evidence/"hierarchical.rpt",evidence/"timing_synth.rpt",build/"post_synth.dcp")),encoding="utf-8")
        synth=run("synth",[str(VIVADO),"-mode","batch","-log",str(evidence/"vivado.log"),
            "-journal",str(evidence/"vivado.jou"),"-source",str(tcl)])
        rows=re.findall(r"FEATURE_WINDOW_SYNTH lut=(\d+) ff=(\d+) ram36=(\d+) ram18=(\d+) dsp=(\d+) latch=(\d+) blackbox=(\d+)",synth)
        if len(rows)!=1: raise ValueError("Window synthesis resource census missing")
        lut,ff,ram36,ram18,dsp,latch,blackbox=map(int,rows[0])
        result["synthesis"]=dict(lut=lut,ff=ff,ram36=ram36,ram18=ram18,bram36_equivalent=ram36+ram18/2,
                                  dsp=dsp,latch=latch,blackbox=blackbox)
        if lut>30000 or ff>10000 or ram36+ram18/2!=128 or dsp or latch or blackbox:
            raise ValueError("Window mapping failed the fixed screen")
        if hashes!={str(p.relative_to(ROOT)):sha(p) for p in sources}: raise ValueError("Source changed")
        result["status"]="PASS_PRIVATE_BANKED_WINDOW_XSIM_OOC_SYNTH_ONLY"
    except Exception as exc:
        result["status"]="FAILED_CLOSED"; result["error"]=f"{type(exc).__name__}: {exc}"
    result["source_sha256_after"]={str(p.relative_to(ROOT)):sha(p) for p in sources}
    result["artifact_sha256"]={str(p.relative_to(ROOT)):sha(p) for folder in (build,evidence)
        for p in sorted(folder.glob("*")) if p.is_file() and p.name!="result.json"}
    (evidence/"result.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"report":str(evidence/"result.json"),"error":result.get("error")}),flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__=="__main__": raise SystemExit(main())
