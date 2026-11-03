"""Private AXI3 read seam: burst geometry, independent memory TB, bounded OOC."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT/'deployment/hardware/z100_2026/native_axi64_reader_v1'
RTL = DIR/'z100_native_axi64_reader.sv'
TB = DIR/'tb_z100_native_axi64_reader.sv'
VENDOR = Path('C:/appload/2026.1/Vivado/bin')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def plan(address, count, epoch=1):
    if not (0 < epoch < 2**32 and 0 <= address < 2**32 and address % 64 == 0 and
            1 <= count <= 8192 and address+count*64 <= 2**32):
        raise ValueError('Invalid command')
    end=address+count*64; bursts=[]
    while address<end:
        size=min(128, 4096-address%4096, end-address)
        bursts.append((address,size//8))
        address+=size
    return bursts


def preflight():
    cases=0;bursts=0;bytes_checked=0
    for offset in range(0,4096,64):
        for count in (1,2,63,64,65,8192):
            address=0x10000000+offset; sequence=plan(address,count)
            cursor=address
            for start,beats in sequence:
                require(start==cursor and beats in (8,16), 'Burst coverage/beat geometry')
                require(start//4096==(start+beats*8-1)//4096, '4KiB crossing')
                cursor+=beats*8;bursts+=1
            require(cursor==address+count*64, 'Missing/extra input bytes')
            cases+=1;bytes_checked+=count*64
    for count in (1,2,16,64,8192):
        address=2**32-count*64
        require(sum(beats*8 for _,beats in plan(address,count))==count*64, 'Exact 32bit endpoint')
        cases+=1
    invalid=[(0x10000000,1,0),(0x10000001,1,1),(0x10000000,0,1),
             (0x10000000,8193,1),(0xffffffc0,2,1)]
    for a,n,e in invalid:
        try:plan(a,n,e)
        except ValueError:pass
        else:raise ValueError('Invalid descriptor accepted')
    return dict(status='PASS_HOST_BURST_GEOMETRY_ONLY', descriptors=cases,
                all64byte_page_offsets=64, bursts=bursts, bytes_checked=bytes_checked,
                invalid_descriptors_rejected=len(invalid), actual_axi_or_ddr_qualified=False)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence=ROOT/'validation/board_z100/native_axi64_reader_v1'/stamp
    build=ROOT/'deployment/build/z100_native_axi64_reader_v1'/stamp
    evidence.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    paths=(RTL,TB,Path(__file__).resolve())
    before={str(p.relative_to(ROOT)):sha(p) for p in paths}
    result=dict(status='RUNNING',source_sha256_before=before,commands=[],
                board_access=False,production_integrated=False,full_pipeline_30fps_accepted=False,
                architecture_scope='single-outstandingAXI3_64bit_to512bit_private_epoch_stream',
                coordinated_platform_reset_required=True,local_reset_of_live_AXI_authorized=False)
    report=evidence/'result.json'
    try:
        for p in paths:
            destination=evidence/'source_snapshot'/p.relative_to(ROOT)
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,destination)
        result['host']=preflight();result['status']='PASS_HOST_PREFLIGHT_ONLY'
        if args.execute:
            env=dict(os.environ)
            for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
                env[key]='1'
            def run(name,argv):
                proc=subprocess.run(list(map(str,argv)),cwd=build,env=env,text=True,
                    encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                (evidence/f'{name}.log').write_text(proc.stdout)
                result['commands'].append(dict(name=name,argv=list(map(str,argv)),return_code=proc.returncode))
                require(proc.returncode==0,f'{name} failed')
                require(not re.search(r'^\s*(?:Fatal:|ERROR:)',proc.stdout,re.M),f'{name} fatal')
                return proc.stdout
            run('xvlog',[VENDOR/'xvlog.bat','-sv',RTL,TB])
            run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_axi64_reader','-s','native_axi64_reader_sim'])
            sim=run('xsim',[VENDOR/'xsim.bat','native_axi64_reader_sim','-runall'])
            pattern=r'^NATIVE_AXI64_READER_PASS frames=(\d+) bytes=(\d+) ar=(\d+) r=(\d+) invalid=(\d+) faults=(\d+) blocked=(\d+) max_r_streak=(\d+) ar_hold=(\d+) out_hold=(\d+) r_hold=(\d+) done=(\d+) capacity_words=8192\s*$'
            rows=re.findall(pattern,sim,re.M);require(len(rows)==1,'Missing unique anchored AXI seam PASS')
            values=list(map(int,rows[0]));frames,bytes_,ars,rs,invalid,faults,blocked,streak,arhold,outhold,rhold,done=values
            require(frames==done==8 and bytes_==541952 and invalid==5 and faults==7 and blocked==600 and
                streak>=16 and arhold>=200 and outhold>0 and rhold>0,'AXI transaction coverage')
            result['simulation']=dict(status='PASS',frames=frames,independent_byte_checks=bytes_,
                ar_bursts=ars,r_beats=rs,invalid_commands=invalid,fault_drain_recoveries=faults,
                permanent_stall_clear_reload_rejections=blocked,max_consecutive_r_accepts=streak,
                ar_stability_checks=arhold,output_stability_checks=outhold,slave_stability_checks=rhold,
                capacity_words=8192,actual_ddr_throughput_qualified=False)
            tcl=evidence/'synth.tcl'
            tcl.write_text('''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {%s}
synth_design -top z100_native_axi64_reader -part xc7z100ffg900-2 -mode out_of_context
create_clock -period 10 [get_ports clk]
report_utilization -file {%s}
set leaf [get_cells -hier -filter {IS_PRIMITIVE == 1}]
foreach {kind pattern} {LUT LUT* FF FD* RAM36 RAMB36* RAM18 RAMB18* DSP DSP* LATCH LD*} {
    puts "NATIVE_AXI64_CENSUS $kind [llength [filter $leaf REF_NAME=~$pattern]]"
}
puts "NATIVE_AXI64_CENSUS BLACKBOX [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]"
write_checkpoint -force {%s}
''' % (RTL.as_posix(),(evidence/'utilization.rpt').as_posix(),(build/'post_synth.dcp').as_posix()))
            synth=run('vivado_ooc',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,
                '-log',evidence/'vivado.log','-journal',evidence/'vivado.jou'])
            counts={k:int(v) for k,v in re.findall(r'^NATIVE_AXI64_CENSUS (\w+) (\d+)\s*$',synth,re.M)}
            require(set(counts)=={'LUT','FF','RAM36','RAM18','DSP','LATCH','BLACKBOX'},'Primitive census missing')
            require(counts['LUT']<=4000 and counts['FF']<=2500 and all(counts[k]==0 for k in
                ('RAM36','RAM18','DSP','LATCH','BLACKBOX')),'Fixed AXI reader resource gate')
            result['synthesis']=dict(status='PASS_PRIVATE_OOC_RESOURCE_SCREEN_ONLY',primitive_counts=counts,
                routed_frequency_or_bandwidth_qualified=False)
            result['status']='PASS_PRIVATE_AXI64_READER_XSIM_OOC_ONLY'
    except Exception as exc:result.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        result['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in paths}
        if result['source_sha256_after']!=before:result.update(status='FAILED_SOURCE_INTEGRITY',error='Source mutation')
        result['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for base in (evidence,build)
            for p in base.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],report=str(report),error=result.get('error')),indent=2))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__=='__main__':raise SystemExit(main())
