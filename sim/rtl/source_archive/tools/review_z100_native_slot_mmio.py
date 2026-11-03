"""Review actual AXI-Lite/IRQ manager path, C driver and strobe counterexample."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
REPORTS={
 'rtl':'validation/board_z100/native_slot_mmio_v3/20261025T065539.360469Z/result.json',
 'driver':'validation/board_z100/native_slot_mmio_driver_v2/20261025T065256.400291Z/result.json',
 'ooc':'validation/board_z100/native_slot_mmio_v2_ooc/20261025T065631.413241Z/result.json',
}
NEG='validation/board_z100/native_slot_mmio_strobe_counterexample/20261025T065617.609819Z/result.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    out=ROOT/'validation/board_z100/native_slot_mmio_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    r=dict(status='RUNNING',board_access=False,physical_deployed=False,fullgraph_execution_accepted=False,physical_interrupt_accepted=False,full_pipeline_30fps_accepted=False,route_or_frequency_accepted=False)
    try:
        proofs={};checked={}
        for label,n in REPORTS.items():
            p=json.loads((ROOT/n).read_text());check(p['status'].startswith('PASS_'),'Closed actual proof '+label)
            check(p['source_sha256_before']==p['source_sha256_after'],'Stable sources '+label)
            for name,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/name)==h,'Bound artifact '+name);checked[name]=h
            if label=='driver':check(p['compiler_return_codes']==[0,0] and p['execution_return_code']==0,'Actual host/ARM driver tools')
            else:
                commands=p.get('commands',[p['command']] if 'command' in p else []);check(commands and all(x['return_code']==0 for x in commands),'Actual vendor completion '+label)
            for log in (ROOT/n).parent.glob('*.log'):check(not re.search(r'^\s*(?:ERROR:|Fatal:)',log.read_text(errors='replace'),re.M),'Strict actual log '+str(log))
            proofs[label]=p
        sim=proofs['rtl']['simulation'];check(sim==dict(commands=1587,manager_accepts=1588,writes=20655,reads=7946,write_hold_cycles=61965,read_hold_cycles=31784,response_irqs=1587,peak_slots=7,foreign_reply_quarantined=1),'Actual full AXIL control coverage')
        check(proofs['driver']['encoded']==1586 and proofs['driver']['rejected']==1 and proofs['driver']['transport_cases']==42,'Actual C codec/mock IO coverage')
        resource=proofs['ooc']['observed_primitive_counts'];check(resource==dict(LUT=316,FF=559,RAM36=0,RAM18=0,DSP=0,LATCH=0,BLACKBOX=0) and proofs['ooc']['LUTLP1_count']==0,'Actual selected RTL mapping')
        neg=json.loads((ROOT/NEG).read_text());check(neg['status']=='FAILED_CLOSED' and neg['error']=='ValueError: Strict actual tool completion xsim','Expected original V1 counterexample preserved')
        log=(ROOT/NEG).parent/'xsim.log';text=log.read_text();check('Fatal: Unstrobed route byte changed' in text and 'Time: 750 ns' in text,'Actual original route-byte strobe counterexample')
        for n,h in {**neg['source_sha256_after'],**neg['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Counterexample source binding '+n)
        # Stimulus differs only in DUT and TB module type; all bus transactions,
        # expected snapshots and assertions retained in the passing test.
        hw=ROOT/'deployment/hardware/z100_2026/native_slot_mmio_v1'
        bad=(hw/'tb_z100_native_slot_mmio_strobe_negative.sv').read_text().replace('module tb_z100_native_slot_mmio_strobe_negative;','module tb_z100_native_slot_mmio_v3;').replace('z100_native_slot_mmio frontend(','z100_native_slot_mmio_v2 frontend(')
        check(bad==(hw/'tb_z100_native_slot_mmio_v3.sv').read_text(),'Exact V1/V2 A/B bus stimulus')
        old=(hw/'z100_native_slot_mmio.sv').read_text().replace('module z100_native_slot_mmio (','module z100_native_slot_mmio_v2 (').replace('else route_shadow<=masked_write[1:0];','else if(wstrb_q[0])route_shadow<=masked_write[1:0];')
        check(old==(hw/'z100_native_slot_mmio_v2.sv').read_text(),'Only route-byte write-enable semantics changed')
        protected=json.loads((ROOT/'validation/board_z100/acceleration_resource_review/20261023/protected_before.json').read_text())['files']
        for n,h in protected.items():check(sha(ROOT/n)==h,'Protected source '+n)
        r.update(status='ROOT_REVIEWED_NATIVE_AXIL_MMIO_V2_REAL1587_MANAGER_EVENTS_IRQ_C_DRIVER42_CASES316LUT559FF_NOT_BOARD_IO',
            report_bindings={k:dict(path=v,sha256=sha(ROOT/v)) for k,v in REPORTS.items()},
            source_artifact_hashes_checked=len(checked),protected_sources_checked=len(protected),simulation=sim,mmio_resources=resource,
            original_strobe_counterexample=dict(path=NEG,sha256=sha(ROOT/NEG),log_sha256=sha(log),reason='V1 changed the low route byte on an upper-byte-only zero write. Selected RTL V2 qualifies route update with WSTRB[0]. Exact same A/B stimulus fails V1 and passes V2.'),
            scope='AXI-Lite frontend->real arbiter->bounded manager and stored-response level IRQ in XSim. C driver uses mock callbacks, plus ARM object compile;1586 structural packets encoded exactly/one invalid slot rejected. No PS device mapping, cache/barrier implementation, GIC IRQ execution, fullgraph pixel engine, HP platform or physical FPS.',
            next_gate='Map frontend into native PS/PL platform and implement ordered device callbacks; connect graph RUN/DRAIN backend and writer/source ownership. Preserve stored replies and in-flight leases on timeout/IO ambiguity. Close whole-platform timing and validate board parity/continuous throughput.')
    except Exception as exc:r.update(status='FAILED_ROOT_REVIEW_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['reviewer_sha256']=sha(Path(__file__));p=out/'result.json';p.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(p),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
