"""Checked native address metadata guards, held cancel and recovery."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_feature_address_guards'/stamp;build=ROOT/'build'/('fag_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True);report=out/'result.json'
    rtl=[HW/n for n in ('native_feature_address_v1/z100_native_feature_address.sv','native_feature_address_v1/tb_z100_native_feature_address.sv')]
    sources=[Path(__file__),*rtl];before={str(f.relative_to(ROOT)):sha(f) for f in sources}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    try:
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual tool diagnostic '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_feature_address','-s','guard_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','guard_sim','-runall']);markers=re.findall(r'^FEATURE_ADDRESS_GUARD_PASS (.+)$',logs,re.M)
        check(len(markers)==1,'Complete full-capacity4K mirrored store marker');sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(sim==dict(rejected=10,held_cycles=20,recovery_completion=1),'Both orders, every byte/read port, held response and capacity guards')
        r.update(status='PASS_PRIVATE_NATIVE_FEATURE_ADDRESS_METADATA_BACKPRESSURE_CANCEL_RECOVERY_XSIM',simulation=sim,
            decision='Native sequential index/canonical address state advances only on accepted metadata-correct words.',
            scope='Six geometry guards; epoch/index/LAST rejection before forwarding,20 held cycles, cancel invalidation and valid two-word completion after recovery. No board performance acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
