"""Actual A/B same-edge release/command ownership counterexample and fix."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/ingress_release_guard'/stamp;build=ROOT/'build'/('irg_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True);report=out/'result.json'
    old=HW/'native_ingress_reader_v1/z100_native_ingress_reader.sv';new=HW/'native_ingress_reader_v2/z100_native_ingress_reader_v2.sv'
    rtl=[HW/'native_axi64_reader_v1/z100_native_axi64_reader.sv',old,new,HW/'native_ingress_reader_v2/tb_z100_ingress_release_guard.sv']
    sources=[Path(__file__),*rtl];before={str(f.relative_to(ROOT)):sha(f) for f in sources}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    try:
        expected=old.read_text().replace('module z100_native_ingress_reader (','module z100_native_ingress_reader_v2 (')
        expected=expected.replace('(owner_mode ? v_quiet : b_quiet);','(owner_mode ? v_quiet : b_quiet)&&!(owner_mode ? v_command : b_command);')
        expected=expected.replace('// rst_n is the coordinated fabric reset, never a local recovery mechanism.',
            '// Release also excludes a same-edge owned command even if a caller wrongly\n// asserts quiet. Otherwise a new reader transaction could lose its owner.\n// rst_n is the coordinated fabric reset, never a local recovery mechanism.')
        check(new.read_text()==expected,'Only module name/comment and no-release-during-owned-command guard changed')
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual tool diagnostic '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_ingress_release_guard','-s','guard_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','guard_sim','-runall']);markers=re.findall(r'^INGRESS_RELEASE_GUARD_PASS (.+)$',logs,re.M)
        check(len(markers)==1,'Complete discriminating A/B ownership marker');sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(sim==dict(old_lost_owners=2,fixed_retained_owners=2,fixed_owned_recoveries=2,modes=2,AXI_AR=0),'Both clients discriminate lost vs retained ownership and owned fault clear')
        r.update(status='PASS_PRIVATE_RELEASE_COMMAND_COLLISION_AB_BOTH_MODES_FIXED_RETAINS_AND_RECOVERS',simulation=sim,
            decision='V1 full halo trace remains historical numeric evidence, not safe general lease admission. Use V2 guarded lease for subsequent integration.',
            scope='Deliberately inconsistent quiet+command on the same edge as release; epoch0 is rejected without AXI AR. Old releases the faulted command owner and cannot clear that fault, fixed retains ownership and clears normally. Old orphaned test instance is reset only with no outstanding AXI; no production local-reset recovery is introduced.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
