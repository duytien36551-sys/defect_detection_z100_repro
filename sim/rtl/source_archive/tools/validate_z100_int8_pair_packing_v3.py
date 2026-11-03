"""Exact full-range signed INT8 pair packing proof; no approximate overpacking."""
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
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'deployment/hardware/z100_2026/int8_pair_packing_v3'
RTL=DIR/'z100_int8_pair_packing.sv'
TB=DIR/'tb_z100_int8_pair_packing.sv'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def exhaustive():
    # All2^24 triples, including -128 on every signed operand. The reference
    # computes two separate signed products; it does not use the packed path.
    low_u=np.tile(np.arange(256,dtype=np.int64),256)
    high=np.repeat(np.arange(-128,128,dtype=np.int64),256)
    low_signed=low_u-(low_u>=128)*256
    packed=(high<<17)+low_u
    require(packed.min()>=-(1<<24) and packed.max()<(1<<24),'Packed weight exceeds signed25')
    digest=hashlib.sha256();cases=0;low_sign_corrections=0;high_sign_corrections=0
    min_product=0;max_product=0
    for activation in range(-128,128):
        product=packed*activation
        min_product=min(min_product,int(product.min()));max_product=max(max_product,int(product.max()))
        low_unsigned_product=product&65535
        low_unsigned_product=low_unsigned_product-(low_unsigned_product>=32768)*65536
        decoded_high=(product>>17)+(low_unsigned_product<0)
        decoded_low=low_unsigned_product-(low_u>=128)*(activation<<8)
        require(np.array_equal(decoded_high,high*activation),'High signed product error')
        require(np.array_equal(decoded_low,low_signed*activation),'Low signed product error')
        require(np.all((decoded_high>=-32768)&(decoded_high<=32767)) and
                np.all((decoded_low>=-32768)&(decoded_low<=32767)),'Signed16 output overflow')
        cases+=len(packed)
        low_sign_corrections+=int(np.count_nonzero(low_u>=128))
        high_sign_corrections+=int(np.count_nonzero(low_unsigned_product<0))
        digest.update(np.stack((decoded_low,decoded_high),axis=1).astype('<i2').tobytes())
    require(cases==16777216 and min_product>=-(1<<32) and max_product<(1<<32),
            'Full signed range proof missing')
    return dict(status='PASS_EXHAUSTIVE_SIGNED_INT8_HOST_PROOF',triples=cases,
        separately_verified_products=cases*2,packed_weight_bits=25,packed_product_bits=33,
        packed_product_min=min_product,packed_product_max=max_product,
        low_sign_corrections=low_sign_corrections,high_sign_corrections=high_sign_corrections,
        output_order='activation -128..127, high -128..127, low_unsigned0..255, pairedlow/high littleendianINT16',
        output_sha256=digest.hexdigest(),arithmetic_approximation=False,
        host_proof_not_DSP_mapping_or_frequency=True)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence=ROOT/'validation/board_z100/int8_pair_packing_v3'/stamp
    build=ROOT/'deployment/build/z100_int8_pair_packing_v3'/stamp
    evidence.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    paths=(RTL,TB,Path(__file__).resolve(),Path('C:/appload/2026.1/Vivado/data/verilog/src/unimacro/MULT_MACRO.v'),Path('C:/appload/2026.1/Vivado/data/verilog/src/unisims/DSP48E1.v'),Path('C:/appload/2026.1/Vivado/data/verilog/src/glbl.v'));before={str(p):sha(p) for p in paths}
    result=dict(status='RUNNING',source_sha256_before=before,commands=[],board_access=False,
        production_integrated=False,full_pipeline_30fps_accepted=False,
        design='Explicit vendor MULT_MACRO LATENCY1, exact signed corrections; no inferred duplicate multiply',
        external_references=[
            'https://docs.amd.com/v/u/en-US/ug479_7Series_DSP48E1',
            'https://arxiv.org/abs/2203.11028'],
        external_code_imported=False)
    report=evidence/'result.json'
    try:
        (evidence/'src').mkdir()
        for p in paths:
            dest=evidence/'src'/p.name;shutil.copyfile(p,dest)
        result['host']=exhaustive();result['status']='PASS_EXHAUSTIVE_HOST_RTL_VENDOR_PENDING'
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
            run('xelab',[VENDOR/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_int8_pair_packing','glbl','-s','int8_pair_packing_sim'])
            sim=run('xsim',[VENDOR/'xsim.bat','int8_pair_packing_sim','-runall'])
            rows=re.findall(r'^INT8_PAIR_PACKING_PASS inputs=(\d+) outputs=(\d+) ii1_streak=(\d+) bubbles=(\d+) flushes=(\d+) latency=1 signed_edge=-128\s*$',sim,re.M)
            require(len(rows)==1,'Packing unique pass marker missing')
            inputs,outputs,streak,bubbles,flushes=map(int,rows[0])
            require(inputs-outputs==2 and outputs>1100000 and streak>=65536 and bubbles>=3800 and
                flushes==2,'Packing RTL/flush/II coverage')
            result['simulation']=dict(status='PASS',inputs=inputs,output_pairs=outputs,
                consecutive_ii1=streak,bubbles=bubbles,reset_cancel_flushes=flushes,latency=1)
            tcl=evidence/'synth.tcl'
            tcl.write_text('''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {%s}
synth_design -top z100_int8_pair_packing -part xc7z100ffg900-2 -mode out_of_context
create_clock -period 10 [get_ports clk]
report_utilization -file {%s}
set leaf [get_cells -hier -filter {IS_PRIMITIVE == 1}]
foreach {kind pattern} {LUT LUT* FF FD* RAM36 RAMB36* RAM18 RAMB18* DSP DSP* LATCH LD*} {
    puts "INT8_PAIR_CENSUS $kind [llength [filter $leaf REF_NAME=~$pattern]]"
}
puts "INT8_PAIR_CENSUS BLACKBOX [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]"
foreach cell [get_cells -hier -filter {REF_NAME == DSP48E1}] {
    puts "INT8_PAIR_DSP_MODE [get_property NAME $cell] [get_property USE_MULT $cell]"
}
write_checkpoint -force {%s}
''' % (RTL.as_posix(),(evidence/'utilization.rpt').as_posix(),(build/'post_synth.dcp').as_posix()))
            synth=run('vivado_ooc',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,
                '-log',evidence/'vivado.log','-journal',evidence/'vivado.jou'])
            counts={k:int(v) for k,v in re.findall(r'^INT8_PAIR_CENSUS (\w+) (\d+)\s*$',synth,re.M)}
            require(set(counts)=={'LUT','FF','RAM36','RAM18','DSP','LATCH','BLACKBOX'},'Missing packing census')
            modes=re.findall(r'^INT8_PAIR_DSP_MODE (\S+) (\S+)\s*$',synth,re.M)
            require(counts['DSP']==1 and modes and len(modes)==1 and modes[0][1]=='MULTIPLY' and
                counts['LUT']<=200 and counts['FF']<=100 and all(counts[k]==0 for k in
                ('RAM36','RAM18','LATCH','BLACKBOX')),'Exact single-multiplier DSP mapping gate')
            result['synthesis']=dict(status='PASS_PRIVATE_ONE_DSP_TWO_SIGNED_PRODUCTS_OOC_ONLY',
                primitive_counts=counts,dsp_modes=modes,routed_frequency_or_system_throughput_accepted=False)
            result['status']='PASS_PRIVATE_EXACT_SIGNED_PAIR_HOST_XSIM_ONE_DSP_OOC_ONLY'
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
