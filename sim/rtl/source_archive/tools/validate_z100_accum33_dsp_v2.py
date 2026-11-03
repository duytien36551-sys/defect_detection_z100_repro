"""Exact signed33 feedback using explicit DSP48E1 controls; v1 macro first-load failure preserved."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess

for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'deployment/hardware/z100_2026/accum33_dsp_v2'
RTL=DIR/'z100_accum33_dsp.sv'
TB=DIR/'tb_z100_accum33_dsp.sv'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def bounds_proof():
    upper=(1<<31)-1+1024*((1<<18)-1)
    lower=-(1<<31)-1024*(1<<18)
    require(-(1<<32)<=lower<=upper<(1<<32),'Signed33 native group bound')
    return dict(status='PASS_SIGNED33_BOUND_ONLY_NOT_RTL',max_groups=1024,
                signed19_delta_min=-(1<<18),signed19_delta_max=(1<<18)-1,
                extreme_sum_min=lower,extreme_sum_max=upper)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence=ROOT/'validation/board_z100/accum33_dsp_v2'/stamp
    build=ROOT/'deployment/build/z100_accum33_dsp_v2'/stamp
    evidence.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    paths=(RTL,TB,Path(__file__).resolve(),Path('C:/appload/2026.1/Vivado/data/verilog/src/unimacro/ADDSUB_MACRO.v'),Path('C:/appload/2026.1/Vivado/data/verilog/src/unisims/DSP48E1.v'),Path('C:/appload/2026.1/Vivado/data/verilog/src/glbl.v'));before={str(p):sha(p) for p in paths}
    result=dict(status='RUNNING',source_sha256_before=before,commands=[],board_access=False,
        production_integrated=False,full_pipeline_30fps_accepted=False,
        design='Explicit DSP48E1 PREG1 constant control registers bypassed, exact signed33 feedback; CE-safe first bias load',
        external_references=[
            'https://docs.amd.com/v/u/en-US/ug479_7Series_DSP48E1'],
        external_code_imported=False)
    report=evidence/'result.json'
    try:
        (evidence/'src').mkdir()
        for p in paths:
            dest=evidence/'src'/p.name;shutil.copyfile(p,dest)
        result['host']=bounds_proof();result['status']='PASS_HOST_BOUNDS_RTL_VENDOR_PENDING'
        if args.execute:
            env=dict(os.environ)
            def run(name,argv):
                p=subprocess.run(list(map(str,argv)),cwd=build,env=env,text=True,encoding='utf-8',
                    errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                (evidence/f'{name}.log').write_text(p.stdout)
                result['commands'].append(dict(name=name,argv=list(map(str,argv)),return_code=p.returncode))
                require(p.returncode==0,f'{name} failed')
                require(not re.search(r'^\s*(?:Fatal:|ERROR:)',p.stdout,re.M),f'{name} fatal')
                return p.stdout
            run('xvlog',[VENDOR/'xvlog.bat','-sv',RTL,TB,Path('C:/appload/2026.1/Vivado/data/verilog/src/glbl.v')])
            run('xelab',[VENDOR/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_accum33_dsp','glbl','-s','accum33_dsp_sim'])
            sim=run('xsim',[VENDOR/'xsim.bat','accum33_dsp_sim','-runall'])
            rows=re.findall(r'^ACCUM33_DSP_PASS checks=(\d+) loads=(\d+) updates=(\d+) holds=(\d+) flushes=(\d+) saturations=(\d+) ii1_streak=(\d+)\s*$',sim,re.M)
            require(len(rows)==1,'Accumulator pass marker missing')
            checks,loads,updates,holds,flushes,saturations,streak=map(int,rows[0])
            require(loads==64 and updates>=16000 and holds>=128 and flushes==17 and
                saturations>0 and streak==1024,'Accumulator feedback/load/CE/recovery coverage')
            result['simulation']=dict(status='PASS',checks=checks,loads=loads,updates=updates,
                holds=holds,flushes=flushes,saturations=saturations,consecutive_ii1=streak,latency=1)
            tcl=evidence/'synth.tcl'
            tcl.write_text('''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {%s}
synth_design -top z100_accum33_dsp -part xc7z100ffg900-2 -mode out_of_context
create_clock -period 10 [get_ports clk]
report_utilization -file {%s}
set leaf [get_cells -hier -filter {IS_PRIMITIVE == 1}]
foreach {kind pattern} {LUT LUT* FF FD* RAM36 RAMB36* RAM18 RAMB18* DSP DSP* LATCH LD*} {
    puts "ACCUM33_CENSUS $kind [llength [filter $leaf REF_NAME=~$pattern]]"
}
puts "ACCUM33_CENSUS BLACKBOX [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]"
foreach cell [get_cells -hier -filter {REF_NAME == DSP48E1}] {
    puts "ACCUM33_DSP_MODE [get_property NAME $cell] [get_property USE_MULT $cell]"
}
write_checkpoint -force {%s}
''' % (RTL.as_posix(),(evidence/'utilization.rpt').as_posix(),(build/'post_synth.dcp').as_posix()))
            synth=run('vivado_ooc',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,
                '-log',evidence/'vivado.log','-journal',evidence/'vivado.jou'])
            counts={k:int(v) for k,v in re.findall(r'^ACCUM33_CENSUS (\w+) (\d+)\s*$',synth,re.M)}
            require(set(counts)=={'LUT','FF','RAM36','RAM18','DSP','LATCH','BLACKBOX'},'Missing packing census')
            modes=re.findall(r'^ACCUM33_DSP_MODE (\S+) (\S+)\s*$',synth,re.M)
            require(counts['DSP']==1 and modes and len(modes)==1 and modes[0][1]=='NONE' and
                counts['LUT']<=200 and counts['FF']<=100 and all(counts[k]==0 for k in
                ('RAM36','RAM18','LATCH','BLACKBOX')),'Exact single-adder DSP feedback mapping gate')
            result['synthesis']=dict(status='PASS_PRIVATE_ONE_DSP_SIGNED33_FEEDBACK_OOC_ONLY',
                primitive_counts=counts,dsp_modes=modes,routed_frequency_or_system_throughput_accepted=False)
            result['status']='PASS_PRIVATE_SIGNED33_FEEDBACK_XSIM_ONE_DSP_OOC_ONLY'
    except Exception as exc:result.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        result['source_sha256_after']={str(p):sha(p) for p in paths}
        if result['source_sha256_after']!=before:result.update(status='FAILED_SOURCE_INTEGRITY',error='Sources changed')
        result['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for base in (evidence,build)
            for p in base.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],report=str(report),error=result.get('error')),indent=2))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__=='__main__':raise SystemExit(main())
