"""Actual buffer ordering/stability/II1 and no-memory-reset implementation."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re,subprocess,shutil
ROOT=Path(__file__).resolve().parents[1]
OWN=ROOT/'deployment/hardware/z100_2026/native_raw_buffer_v1'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_raw_buffer_v1'/stamp;build=ROOT/'build'/('rawbuf_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl,tb=OWN/'z100_native_raw_buffer.sv',OWN/'tb_z100_native_raw_buffer.sv'
    sources=[Path(__file__),rtl,tb];before={str(p.relative_to(ROOT)):sha(p) for p in sources}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False);report=out/'result.json'
    try:
        for p in sources:shutil.copy2(p,out/p.name)
        def run(label,args):
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict diagnostic '+label);return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',rtl,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_raw_buffer','-s','rawbuf_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','rawbuf_sim','-runall']);m=re.findall(r'^RAW_BUFFER_PASS (.+)$',text,re.M);check(len(m)==1,'Complete raw buffer proof')
        values={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[0])}
        check(values['accepted']==2052 and values['received']==2048 and values['aborts']==2 and values['simultaneous']>=900 and values['stalls']>0 and values['full_cycles']>0,'Full/reset/cancel/II1 coverage')
        r['simulation']=values
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+rtl.as_posix()+'}\nsynth_design -top z100_native_raw_buffer -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'rawbuf.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        text=(out/'utilization.rpt').read_text()
        def metric(n):return int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',text,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=metric('DSPs'),BRAM=metric('Block RAM Tile'))
        check(resources['DSP']==resources['BRAM']==0,'No arithmetic/block RAM')
        r.update(status='PASS_PRIVATE_RAW_BUFFER_FULL_RESET_CANCEL_II1_XSIM_OOC',resources=resources,
            scope='Two raw output slots; registered upstream ready. No route/board result; cancellation invalidates queued data metadata only.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in sources}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
