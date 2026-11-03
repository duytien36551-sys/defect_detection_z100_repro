"""Generic producer control against the executed C row plan; no pixel claim."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, os, re, subprocess
ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026/conv_event_v1'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/native_row_commands_v2/20261025T062641.961558Z/result.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prepare-only',action='store_true');a=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/conv_event_control'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('cec_'+stamp[-14:]);build.mkdir(parents=True)
    report=out/'result.json';before={}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False,
      scope='All189 tiles grouped into63 actual Conv producers from the executed C plan. Synthetic load/tile acknowledgements test ordering, descriptor identity, hold, drain, recovery and overflow only; not numerical or graph slot publication, PS/HP or physical FPS.')
    try:
        proof=json.loads(PROOF.read_text())
        require(proof['rows']==7220 and proof['tiles']==189 and proof['execution_return_code']==0,'Executed C plan')
        require(proof['source_sha256_before']==proof['source_sha256_after'],'Stable oracle')
        for n,h in {**proof['source_sha256_after'],**proof['artifact_sha256']}.items():require(sha(ROOT/n)==h,'Oracle artifact '+n)
        header=ROOT/proof['generated_plan'];bindings=header.parent/'row_bindings.json'
        geometry=[[int(v) for v in row.split(',')] for row in re.findall(r'\{([\d,]+)\}',header.read_text().split('z100_halos[189]={')[1].split('};')[0])]
        jobs=json.loads(bindings.read_text())['tiles'];require(len(geometry)==len(jobs)==189,'Complete tiles')
        records=[];events=[]
        for i,(g,j) in enumerate(zip(geometry,jobs)):
            require(len(g)==13 and j['tile']==i and j['first_output_row']==g[5] and j['output_rows']==g[6],'C geometry binding')
            runs=((g[9]+31)//32)*g[6]*((g[8]+19)//20);windows=runs*((g[0]+3)//4)*g[10]*g[10]
            records.append(g+[runs,windows,j['event']])
            if not events or events[-1]!=j['event']:events.append(j['event'])
        require(len(events)==len(set(events))==63,'Contiguous unique Conv event groups')
        (build/'event_plan.hex').write_text(''.join(f'{v:08x}\n' for row in records for v in row))
        rtl=[HW/'z100_conv_event_control.sv',HW/'tb_z100_conv_event_control.sv']
        sources=[Path(__file__),PROOF,header,bindings,*rtl]
        before={str(p.relative_to(ROOT)):sha(p) for p in sources};r['source_sha256_before']=before
        r.update(tiles=189,events=63,runs=sum(v[13] for v in records),windows=sum(v[14] for v in records))
        report.write_text(json.dumps(r,indent=2))
        if a.prepare_only:r['status']='PREPARED_C_PLAN_BOUND_NOT_RTL_EXECUTED'
        else:
            for label,argv in [('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]),('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_conv_event_control','-s','control_sim']),('xsim',[VENDOR/'xsim.bat','control_sim','-runall'])]:
                p=subprocess.run(list(map(str,argv)),cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(args=list(map(str,argv)),return_code=p.returncode))
                require(p.returncode==0 and not re.search(r'^\s*(ERROR:|Fatal:)',p.stdout,re.M),'Actual '+label)
            require('CONV_EVENT_CONTROL_PASS events=63 tiles=189 negative_cases=21 held_cycles=1134 drain_cycles=756' in p.stdout,'Complete actual coverage')
            r['status']='PASS_CONTROLLER_ONLY63_CONV189_TILES21_FAILURE_CASES_SYNTHETIC_CHILDREN'
    except Exception as e:r.update(status='FAILED_CLOSED',error=str(e))
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if r['source_sha256_after']!=before:r['status']='FAILED_SOURCE_INTEGRITY'
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
