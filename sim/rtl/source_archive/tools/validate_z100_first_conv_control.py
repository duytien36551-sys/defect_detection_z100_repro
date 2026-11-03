"""Focused first-producer ownership/ordering test; synthetic children, no pixels."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, os, re, subprocess
ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026/first_conv_event_v1'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prepare-only',action='store_true');a=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/first_conv_control'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('fcc_'+stamp[-14:]);build.mkdir(parents=True)
    rtl=[HW/'z100_first_conv_event.sv',HW/'tb_z100_first_conv_event_control.sv']
    sources=[Path(__file__),*rtl];before={str(p.relative_to(ROOT)):sha(p) for p in sources}
    r=dict(status='RUNNING',commands=[],source_sha256_before=before,board_access=False,full_pipeline_30fps_accepted=False,
           scope='Controller only with synthetic child completions. Sixteen halo/tile jobs, held commands, drain gate, eleven negative cases and identity ledger retained across recovery. Not numerical, physical or full graph acceptance.')
    report=out/'result.json';report.write_text(json.dumps(r,indent=2))
    try:
        if a.prepare_only:r['status']='PREPARED_NOT_EXECUTED'
        else:
            for label,argv in [('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]),('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_first_conv_event_control','-s','control_sim']),('xsim',[VENDOR/'xsim.bat','control_sim','-runall'])]:
                p=subprocess.run(list(map(str,argv)),cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(args=list(map(str,argv)),return_code=p.returncode))
                if p.returncode or re.search(r'^\s*(ERROR:|Fatal:)',p.stdout,re.M):raise ValueError('Actual '+label+' failed')
            if 'FIRST_CONV_CONTROL_PASS tiles=16 negative_cases=11 held_cycles=96 drain_cycles=64' not in p.stdout:raise ValueError('Missing complete coverage marker')
            r['status']='PASS_CONTROLLER_ONLY_SYNTHETIC_CHILDREN_11_FAILURE_CASES'
    except Exception as e:r.update(status='FAILED_CLOSED',error=str(e))
    r['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in sources}
    if r['source_sha256_after']!=before:r['status']='FAILED_SOURCE_INTEGRITY'
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report))))
    return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
