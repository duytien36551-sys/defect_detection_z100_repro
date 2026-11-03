"""Pool coordinate recurrence versus original cycle miter and signed5x5 oracle."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/feature_payload_v8_compute/20261025T115808.296464Z/result.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/pool_tapxy_v9_unit'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('ptxy_'+stamp[-14:]);build.mkdir(parents=True);report=out/'result.json';before={}
    r=dict(status='RUNNING',commands=[],board_access=False,route_or_frequency_accepted=False,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(PROOF.read_text());check(p['status'].startswith('PASS_PRIVATE_FEATURE_PAYLOAD_V8_SHARED_AXI'),'Actual reference core proof')
        check(p['source_sha256_before']==p['source_sha256_after'],'Stable reference source')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(resolve(n))==h,'Reference source/artifact '+n)
        original=[Path(n) for n in p['commands'][0]['args'][2:]]
        names=['z100_maxpool_vector.sv','z100_maxpool_collect32.sv','z100_native_output_packer.sv','z100_maxpool_window20_rowbase_v2.sv']
        rtl=[]
        for name in names:
            files=[s for s in original if s.name==name];check(len(files)==1,'Unique frozen dependency '+name);rtl+=files
        rtl+=[HW/'pool_tapxy_v9'/n for n in ('z100_maxpool_window20_tapxy_v3.sv','z100_pool_tapxy_miter.sv','tb_z100_pool_tapxy.sv')]
        before={str(s.relative_to(ROOT)):sha(s) for s in [Path(__file__),PROOF,*rtl]};r['source_sha256_before']=before;report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,argv):
            argv=list(map(str,argv));proc=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode));check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_pool_tapxy','-s','tapxy_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','tapxy_sim','-runall']);markers=re.findall(r'^POOL_TAPXY_PASS (.+)$',logs,re.M);check(len(markers)==1,'Complete signed numeric/miter marker')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(sim['complete_jobs']==3 and sim['signed_packed_words']==1304 and sim['independent_bytes']==83456 and sim['cancel_cases']==3 and sim['fault_recovery']==1 and sim['bad_epoch']==1 and sim['window_holds']>=10 and sim['output_holds']>=10 and sim['miter_windows']>=16000 and sim['miter_outputs']>=1304 and sim['coordinate_checks']==sim['miter_controls'],'Actual signed full128x20 SPPF shape, tail5x3, cycle equivalence and cancel/fault cases')
        r.update(status='PASS_PRIVATE_POOL_TAPXY_V9_SIGNED_NUMERIC_ORIGINAL_CYCLE_MITER_CANCEL_STALL_XSIM_ONLY',simulation=sim,
            scope='Synchronous x/y counters replace tap%5 and tap/5 while original tap/tag retained. Unmodified original consumer receives identical external inputs through a simulation-only bind observer; every control cycle, valid descriptor and valid packed output compared. Independent signed5x5 scalar oracle checks1304 packed words for5x3,128x20 and reuse5x3 cases, with input/output stalls, invalid epoch, three cancel points and source-fault recovery. No added request cycle permitted by miter. Not actual current-model input tensor/core integration, mapped/routed timing or board FPS.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
