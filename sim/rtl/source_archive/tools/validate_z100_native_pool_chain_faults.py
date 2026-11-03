"""Autonomous pool controller faults with actual AXI drain/recovery semantics."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[1];OWN=ROOT/'deployment/hardware/z100_2026/native_pool_chain_v1'
PROOF=ROOT/'validation/board_z100/native_pool_chain_v1/20261024T132949.028286Z/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_pool_chain_faults'/stamp;build=ROOT/'build'/('mpfault_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    before={};r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False);report=out/'result.json'
    try:
        p=json.loads(PROOF.read_text());check(p['status']=='PASS_PRIVATE_AUTONOMOUS_CONTROLLER_REAL_AXI_THREE_SPPF_CHAIN_XSIM','Actual successful autonomous chain')
        check(p['source_sha256_before']==p['source_sha256_after'],'Stable success prerequisite')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Success proof identity '+n)
        rtl=[Path(n) for n in p['commands'][0]['args'][2:] if Path(n).name not in ('axi3_byte_memory.sv','tb_z100_native_pool_chain.sv')]
        check(len(rtl)==11,'Exact actual11 RTL module closure')
        tb=OWN/'tb_z100_native_pool_chain_faults.sv';memory=OWN/'axi3_byte_memory_faults.sv'
        sources=[Path(__file__),*rtl,tb,memory,PROOF];before={str(f.relative_to(ROOT)):sha(f) for f in sources}
        for f in [Path(__file__),*rtl,tb,memory]:shutil.copy2(f,out/f.name)
        def run(label,args):
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict vendor diagnostic '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl,memory,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_pool_chain_faults','-s','pool_fault_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','pool_fault_sim','-runall'])
        marker=re.findall(r'^NATIVE_POOL_CHAIN_FAULT_PASS (.+)$',text,re.M);check(len(marker)==1,'One complete actual fault/drain marker')
        values={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',marker[0])}
        expected=dict(invalid_commands=12,reader_cancel=1,reader_response_error=1,watchdog=1,writer_cancel=1,writer_response_error=1,recoveries=17,success_words=2,done=1,no_local_AXI_reset=1)
        check(all(values.get(k)==v for k,v in expected.items()) and values['drain_probes']>=60,'Independent abort and no-reload-before-drain coverage')
        r['simulation']=values
        control=OWN/'z100_native_pool_chain_control.sv';tcl=build/'synth.tcl'
        tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+control.as_posix()+'}\nsynth_design -top z100_native_pool_chain_control -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'control.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        util=(out/'utilization.rpt').read_text()
        def metric(n):return int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=metric('DSPs'),BRAM=metric('Block RAM Tile'))
        check(resources['DSP']==resources['BRAM']==0 and resources['Slice_LUT']<8000,'Bounded control-only resource gate')
        r.update(status='PASS_PRIVATE_AUTONOMOUS_POOL_REAL_AXI_CANCEL_FAULT_DRAIN_RECOVERY_XSIM_CONTROL_OOC',resources=resources,
            scope='Actual adapters and pool/codec with adversarial independent byte memory. Success chain and this fault proof are separate. Controller has no AXI reset output; platform rst_n still requires coordinated reset. No PS HP, fullgraph, physical DDR, timing or FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
