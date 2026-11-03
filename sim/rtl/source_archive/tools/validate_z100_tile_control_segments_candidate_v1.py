"""Execute tile control against all current-model rows from the actual C oracle."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026/platform_v13c/isolation/arith_segments_narrow_v1_20261030'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/native_row_commands_v2/20261025T062641.961558Z/result.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/tile_control_segments_candidate_v1'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('segct_'+stamp[-14:]);build.mkdir(parents=True);report=out/'result.json';before={}
    result=dict(status='RUNNING',commands=[],board_access=False,pixel_compute_executed=False,
        production_integrated=False,arithmetic_candidate=True,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(PROOF.read_text());check(p['rows']==7220 and p['tiles']==189 and p['execution_return_code']==0,'Actual current-model C row oracle')
        check(p['source_sha256_before']==p['source_sha256_after'],'Stable C proof sources')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'C proof bound artifact '+n)
        header=ROOT/p['generated_plan'];bindings=header.parent/'row_bindings.json';execution=PROOF.parent/'execution.log'
        body=header.read_text().split('z100_halos[189]={')[1].split('};')[0]
        geometry=[[int(v) for v in row.split(',')] for row in re.findall(r'\{([\d,]+)\}',body)]
        rows=[[int(v) for v in line.split()[1:]] for line in execution.read_text().splitlines() if line.startswith('ROW ')]
        jobs=json.loads(bindings.read_text())['tiles']
        check(len(geometry)==len(jobs)==189 and len(rows)==7220 and all(len(g)==13 for g in geometry) and all(len(v)==12 for v in rows),'Complete C vectors')
        first=[]
        for g,j in zip(geometry,jobs):
            ids=j['parameter_jobs'];check(ids==list(range(ids[0],ids[0]+len(ids))) and len(ids)==(g[9]+31)//32,'Contiguous real parameter group IDs')
            first.append(ids[0]);check((g[9]+3)//4*g[6]*((g[8]+15)//16)<=8192,'Real output tile admitted by packer')
        for name,values in [('geometry.hex',[v for g in geometry for v in g]),('expected_rows.hex',[v for row in rows for v in row]),('parameter_first.hex',first)]:
            (build/name).write_text(''.join(f'{v:016x}\n' for v in values))
        rtl=[HW/'z100_native_conv_tile_control_v2.sv',HW/'tb_z100_native_conv_tile_control_v2.sv']
        sources=[Path(__file__),PROOF,header,bindings,execution,*rtl]
        before={str(v.relative_to(ROOT)):sha(v) for v in sources};result['source_sha256_before']=before;report.write_text(json.dumps(result,indent=2)+'\n')
        def run(label,args):
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);result['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual '+label);return proc.stdout
        if args.prepare_only:
            result.update(status='PREPARED_C_ORACLE_METADATA_FIXTURES_ONLY_NOT_RTL_EXECUTION',tiles=len(geometry),rows=len(rows),parameter_groups=sum(len(t['parameter_jobs']) for t in jobs))
        else:
            run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_conv_tile_control_v2','-s','tile_sim'])
            logs=run('xsim',[VENDOR/'xsim.bat','tile_sim','-runall']);markers=re.findall(r'^CONV_TILE_CONTROL_PASS (.+)$',logs,re.M)
            check(len(markers)==1,'Complete actual tile control marker');sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
            check(sim['graph_tiles']==189 and sim['graph_rows']==7220 and sim['graph_publications']==189 and sim['negative_cases']==12 and sim['recovery_blocks']==48 and sim['held_cycles']>=23000 and sim['publication_wait_cycles']==1330,'Actual metadata and failure/ownership gates')
            result.update(status='PASS_PRIVATE_CONV_TILE_CONTROL_V2_189_TILES7220_C_ORACLE_ROWS_GROUP_ORDER_PUBLICATION_AND_RECOVERY_XSIM_ONLY',
                simulation=sim,source_package_sha256=p['source_package_sha256'],scope='All189 current-model Conv halo tile geometries and7220 exact row commands compared to executed C oracle. Parameter group reload/order, pack config, stable stall payload, row-token ownership, delayed successful publication and twelve failure/recovery cases, monotonic epoch/job-tag admission and job-bound completion identities. Child parameter/row/publication acknowledgements are TB synthetic; no MAC pixels, actual tile DDR publication, graph source leases, synthesized mapping, platform or physical FPS.')
    except Exception as exc:result.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    result['source_sha256_before']=before;result['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=result['source_sha256_after']:result.update(status='FAILED_SOURCE_INTEGRITY')
    result['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(status=result['status'],report=str(report),error=result.get('error'))))
    return int(result['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
