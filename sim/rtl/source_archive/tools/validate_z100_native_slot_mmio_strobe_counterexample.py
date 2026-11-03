"""Run actual AXI-Lite frontend -> arbiter -> bounded seven-slot manager."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/native_tensor_slots_bounded_v2/20261025T054420.119171Z/result.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    live=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-Process vivado -ErrorAction SilentlyContinue).Count"],capture_output=True,text=True)
    check(live.returncode==0 and int(live.stdout.strip())<2,'At most two vendor flows including this test')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/native_slot_mmio_strobe_counterexample'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('nsmm_'+stamp[-14:]);build.mkdir(parents=True);report=out/'result.json';before={}
    r=dict(status='RUNNING',commands=[],board_access=False,production_integrated=False,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(PROOF.read_text());check(p['status'].startswith('PASS_PRIVATE_MODEL_BOUNDED'),'Closed real seven-slot metadata prerequisite')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Closed prerequisite binding '+n)
        fixtures=[]
        for base in ('commands.hex','expected.hex','slot_defs.vh'):
            src=next(ROOT/n for n in p['artifact_sha256'] if Path(n).name==base);fixtures.append(src);shutil.copyfile(src,build/base)
        rtl=[HW/n for n in ('native_tensor_slots_bounded_v2/z100_native_tensor_commit_bounded_v2.sv','native_tensor_slots_bounded_v2/z100_native_tensor_slots_bounded_v2.sv','native_slot_arbiter_v1/z100_native_slot_arbiter.sv','native_slot_mmio_v1/z100_native_slot_mmio.sv','native_slot_mmio_v1/tb_z100_native_slot_mmio_strobe_negative.sv')]
        before={str(s.relative_to(ROOT)):sha(s) for s in [Path(__file__),PROOF,*fixtures,*rtl]};r['source_sha256_before']=before;report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode));check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual tool completion '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_slot_mmio_strobe_negative','-s','mmio_sim']);logs=run('xsim',[VENDOR/'xsim.bat','mmio_sim','-runall'])
        rows=re.findall(r'^SLOT_MMIO_PASS (.+)$',logs,re.M);check(len(rows)==1,'Complete actual MMIO marker');sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',rows[0])}
        check(sim['commands']==1587 and sim['manager_accepts']==1588 and sim['response_irqs']==1587 and sim['peak_slots']==7 and sim['foreign_reply_quarantined']==1,'Actual MMIO complete metadata and error isolation')
        check(sim['write_hold_cycles']==sim['writes']*3 and sim['read_hold_cycles']==sim['reads']*4,'All actual AXI B/R response holds exercised')
        r.update(status='PASS_PRIVATE_AXIL_MMIO_REAL_ARBITER_SEVEN_SLOT_ALL1587_METADATA_IRQ_BYTE_STROBES_BACKPRESSURE_XSIM_ONLY',simulation=sim,
            scope='Actual AXI-Lite frontend/arbiter/bounded manager. Independent AW/W orders, byte strobes, held B/R responses, locked staging/doorbells, all1587 metadata/adverse vectors, stored-reply IRQ/ACK and foreign ACK quarantine. Graph and writer clients driven by register writes; source client idle. No actual PS MMIO execution, PL image MAC, full HP platform, routed frequency or board FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
