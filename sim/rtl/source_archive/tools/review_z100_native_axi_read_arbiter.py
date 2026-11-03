"""Bind actual DDR/config end-to-end proof and standalone mover mapping."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
REPORTS={
 'rtl':'validation/board_z100/native_axi_read_arbiter_v2/20261025T114011.006195Z/result.json',
 'ooc':'validation/board_z100/native_axi_read_arbiter_ooc/20261025T114043.476591Z/result.json',
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def main():
    out=ROOT/'validation/board_z100/native_axi_read_arbiter_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
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
        sim=proofs['rtl']['simulation']
        check(sim['paired_rounds']==24 and sim['successful_jobs']==48 and sim['AXI_R']==2272 and sim['owner0_R']+sim['owner1_R']==2272 and sim['held_AR_cycles']>=8 and sim['held_R_cycles']>=100 and sim['recovered_rounds']==2 and sim['protocol_quarantine']==1,'Actual dual-reader data/backpressure/cancel/error/quarantine coverage')
        c=proofs['ooc']['observed_primitive_counts'];check(c['DSP']==c['RAM36']==c['RAM18']==c['LATCH']==c['BLACKBOX']==0 and c['LUT']<=500 and c['FF']<=400 and proofs['ooc']['LUTLP1_count']==0,'Arbiter-only mapped resources')
        key='deployment/hardware/z100_2026/native_axi_read_arbiter_v1/z100_native_axi_read_arbiter.sv'
        check(proofs['rtl']['source_sha256_after'][str(Path(key))]==proofs['ooc']['source_sha256_after'][str(Path(key))],'Same actual DUT in sim and OOC')
        tb=ROOT/'deployment/hardware/z100_2026/native_axi_read_arbiter_v1/tb_z100_native_axi_read_arbiter_v2.sv';text=tb.read_text()
        check('datum(expected_base[k]+expected_index[k]*64+b*8)' in text and 'held_r<100' in text and 'if(ar_held&&' in text and 'if(r_held&&' in text,'Independent physical address payload oracle, held AR/R stability and coverage enforced')
        protected=json.loads((ROOT/'validation/board_z100/acceleration_resource_review/20261023/protected_before.json').read_text())['files']
        for n,h in protected.items():check(sha(ROOT/n)==h,'Protected source '+n)
        r.update(status='ROOT_REVIEWED_TWO_REAL_READERS_SHARED_AXI_ARBITRATION_BACKPRESSURE_DRAIN_QUARANTINE_OOC_NOT_PLATFORM',
            report_bindings={k:dict(path=v,sha256=sha(ROOT/v)) for k,v in REPORTS.items()},unique_source_artifact_hashes_checked=len(checked),protected_sources_checked=len(protected),simulation=sim,arbiter_resources=c,
            scope='Two frozen identical-RID0 AXI readers on one physical TB responder. Exact owner data and metadata on48 jobs, enforced5467 physical R hold cycles, cancellation while physical AR held, RRESP recovery and sticky malformed-RID quarantine. Last unadmitted peer AR remains pending until coordinated system recovery. Not feature/parameter compute integration, physical HP timing or board FPS.',
            next_gate='Integrate actual parameter and feature readers before full20site compute through this arbiter and one physical responder, then wholegraph and native PS/HP platform.')
    except Exception as exc:r.update(status='FAILED_ROOT_REVIEW_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['reviewer_sha256']=sha(Path(__file__));p=out/'result.json';p.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(p),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
