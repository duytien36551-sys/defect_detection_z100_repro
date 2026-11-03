"""Bind actual DDR/config end-to-end proof and standalone mover mapping."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
REPORTS={
 'rtl':'validation/board_z100/native_parameter_reader_v2/20261025T074249.656472Z/result.json',
 'ooc':'validation/board_z100/native_parameter_reader_ooc/20261025T074445.127384Z/result.json',
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def main():
    out=ROOT/'validation/board_z100/native_parameter_reader_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    r=dict(status='RUNNING',board_access=False,physical_deployed=False,full_pipeline_30fps_accepted=False,route_or_frequency_accepted=False,fullgraph_execution_accepted=False)
    try:
        proofs={};checked={}
        for label,n in REPORTS.items():
            p=json.loads((ROOT/n).read_text());check(p['status'].startswith('PASS_PRIVATE_'),'Closed actual proof '+label)
            check(p['source_sha256_before']==p['source_sha256_after'],'Stable actual source '+label)
            for name,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(resolve(name))==h,'Bound source/artifact '+name);checked[name]=h
            commands=p.get('commands',[p['command']] if 'command' in p else []);check(commands and all(c['return_code']==0 for c in commands),'Actual tool completion '+label)
            for log in (ROOT/n).parent.glob('*.log'):check(not re.search(r'^\s*(?:ERROR:|Fatal:)',log.read_text(errors='replace'),re.M),'Strict actual log '+str(log))
            proofs[label]=p
        sim=proofs['rtl']['simulation'];check(sim==dict(jobs=173,configs=74447,weight_bytes=3011712,bias_values=5536,factors=5419,unary_replica_bytes=708608,AXI_AR=24397,AXI_R=390352,recoveries=3,early_recovery_blocks=24),'All real DDR parameter and physical drain coverage')
        check(proofs['rtl']['source_package_sha256']=='65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c' and proofs['rtl']['memory_fixture_bytes']==3122432,'Exact current model assets')
        c=proofs['ooc']['observed_primitive_counts'];check(c['DSP']==c['RAM36']==c['RAM18']==c['LATCH']==c['BLACKBOX']==0 and c['LUT']<=4000 and c['FF']<=3500 and proofs['ooc']['LUTLP1_count']==0,'Actual mover-only resource budget')
        key='deployment\\hardware\\z100_2026\\native_parameter_reader_v1\\z100_native_parameter_reader.sv'
        check(proofs['rtl']['source_sha256_after'][key]==proofs['ooc']['source_sha256_after'][key],'Same DUT test and mapping')
        tb=ROOT/'deployment/hardware/z100_2026/native_parameter_reader_v1/tb_z100_native_parameter_reader_v2.sv';text=tb.read_text()
        check('expected_payload[beat_probe*64+:64]=memory[' in text and 'cmd_data!==expected_payload' in text and 'stored_weight!==cmd_data' in text and 'factor.multipliers[cmd_index]' in text and 'stored_unary!=={16{cmd_data[7:0]}}' in text,'Independent immutable DDR-address oracle and actual child config probes')
        protected=json.loads((ROOT/'validation/board_z100/acceleration_resource_review/20261023/protected_before.json').read_text())['files']
        for n,h in protected.items():check(sha(ROOT/n)==h,'Protected source '+n)
        r.update(status='ROOT_REVIEWED_ALL173_DDR_AXI_PARAMETER_TO_REAL_CONFIG_DRAIN_RECOVERY_AND_MOVER_OOC_NOT_INFERENCE',
            report_bindings={k:dict(path=v,sha256=sha(ROOT/v)) for k,v in REPORTS.items()},unique_source_artifact_hashes_checked=len(checked),protected_sources_checked=len(protected),simulation=sim,mover_resources=c,
            scope='Immutable parameter DDR fixture -> frozen AXI64 reader -> parameter mover -> strict config bridge -> actual MAC SITES1 configuration RAM/bias, factor32 and unary16 replicas. No MAC computation, input feature pipeline or result generation. Timeout/metadata error branches exist but this integration only exercises held AR/absent R abort and RRESP fault. Platform asset identity/reservation/cache maintenance/HP sharing remain caller responsibilities. No routed clock, ARM download, board FPS or30FPS acceptance.',
            next_gate='Integrate parameter commands with actual20site row scheduler/input/writeback RUN backend and shared platform IO. Verify timeout/metadata/config faults and source version ownership at system scope; close final platform route and board parity before sustained FPS measurement.')
    except Exception as exc:r.update(status='FAILED_ROOT_REVIEW_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['reviewer_sha256']=sha(Path(__file__));p=out/'result.json';p.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(p),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
