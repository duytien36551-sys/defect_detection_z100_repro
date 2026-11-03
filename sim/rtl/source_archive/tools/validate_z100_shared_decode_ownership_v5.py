"""Actual4K mirrored full capacity, both load orders and high-bit rejection."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/shared_decode_ownership_v5'/stamp;build=ROOT/'build'/('irg_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True);report=out/'result.json'
    rtl=[HW/n for n in ('feature_banks_load_order_4k_v4/z100_feature_banks_load_order_4k_v4.sv','feature_banks_4read_load_order_4k_v4/z100_feature_banks_4read_load_order_4k_v4.sv','feature_banks_pingpong_shared_v5/z100_feature_banks_pingpong_shared_v5.sv','feature_window20_shared_decode_4k_v5/z100_feature_window20_shared_decode_4k_v5.sv','feature_window20_shared_decode_4k_v5/tb_z100_shared_decode_ownership.sv')]
    sources=[Path(__file__),*rtl];before={str(f.relative_to(ROOT)):sha(f) for f in sources}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    try:
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual tool diagnostic '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_shared_decode_ownership','-s','guard_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','guard_sim','-runall']);markers=re.findall(r'^SHARED_DECODE_OWNERSHIP_PASS (.+)$',logs,re.M)
        check(len(markers)==1,'Complete full-capacity4K mirrored store marker');sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(sim==dict(writes=12,value_mask_checks=240,held_cycles=14,overwrite_blocks=8,simultaneous_begin_window=1,cancel_flushes=2),'Both orders, every byte/read port, held response and capacity guards')
        r.update(status='PASS_PRIVATE_SHARED_DECODE_TWO_BANKS_S0_RESPONSE_OWNERSHIP_CONCURRENT_LOAD_CANCEL_XSIM',simulation=sim,
            decision='One shared decoder/gather, RAM bank follows S0 and retained response; config/read overlap only on different banks.',
            scope='Two distinct source payloads, simultaneous B begin/A descriptor, bank-pin mutation with held A and queued B, overwrite rejection, masks/padding/stride2 and two in-flight/held cancel flushes. No whole-core resource/routing/board acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
