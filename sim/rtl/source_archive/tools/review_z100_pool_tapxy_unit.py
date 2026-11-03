"""Root review of limited coordinate-only change and original cycle observer."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re,difflib
ROOT=Path(__file__).resolve().parents[1]
PROOF=ROOT/'validation/board_z100/pool_tapxy_v9_unit/20261025T135409.174249Z/result.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def main():
    out=ROOT/'validation/board_z100/pool_tapxy_v9_unit_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    r=dict(status='RUNNING',board_access=False,current_model_core_integration_accepted=False,route_or_frequency_accepted=False,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(PROOF.read_text());check(p['status']=='PASS_PRIVATE_POOL_TAPXY_V9_SIGNED_NUMERIC_ORIGINAL_CYCLE_MITER_CANCEL_STALL_XSIM_ONLY','Actual numeric/miter completion')
        check(p['source_sha256_before']==p['source_sha256_after'],'Stable source');checked={}
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(resolve(n))==h,'Source/artifact '+n);checked[n]=h
        check(len(p['commands'])==3 and all(c['return_code']==0 for c in p['commands']),'Actual tools complete')
        for log in PROOF.parent.glob('*.log'):check(not re.search(r'^\s*(?:ERROR:|Fatal:)',log.read_text(errors='replace'),re.M),'Strict diagnostics')
        check(p['simulation']==dict(complete_jobs=3,signed_packed_words=1304,independent_bytes=83456,cancel_cases=3,fault_recovery=1,bad_epoch=1,window_holds=4122,output_holds=953,miter_controls=23770,miter_windows=20483,miter_outputs=2258,coordinate_checks=23770),'Exact original-cycle/numeric/stall coverage')
        old=ROOT/'deployment/hardware/z100_2026/shared_window_pool_rowbase_v6/z100_maxpool_window20_rowbase_v2.sv'
        new=ROOT/'deployment/hardware/z100_2026/pool_tapxy_v9/z100_maxpool_window20_tapxy_v3.sv'
        a=old.read_text();b=new.read_text()
        expected=a.replace('module z100_maxpool_window20_rowbase_v2','module z100_maxpool_window20_tapxy_v3').replace('reg [4:0] tap_q;', 'reg [4:0] tap_q;\n    reg [2:0] tap_x_q,tap_y_q;')
        expected=expected.replace('wire [2:0] tap_x=tap_q%5,tap_y=tap_q/5;', '// Coordinate recurrence removes encoded-tap division from the address path.\n    wire [2:0] tap_x=tap_x_q,tap_y=tap_y_q;')
        check(expected.count('tap_q<=0;')==4,'Exactly four original reset/restart sites')
        expected=expected.replace('tap_q<=0;', 'tap_q<=0;tap_x_q<=0;tap_y_q<=0;')
        expected=expected.replace("else tap_q<=tap_q+1'b1;", "else begin\n                        tap_q<=tap_q+1'b1;\n                        if(tap_x_q==4)begin tap_x_q<=0;tap_y_q<=tap_y_q+1'b1;end\n                        else tap_x_q<=tap_x_q+1'b1;\n                    end")
        check(expected==b,'Only four synchronized resets and accepted-tap coordinate recurrence change')
        (out/'pool_source.diff').write_text(''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile=str(old),tofile=str(new))))
        m=(new.parent/'z100_pool_tapxy_miter.sv').read_text();tb=(new.parent/'tb_z100_pool_tapxy.sv').read_text()
        check('bind z100_maxpool_window20_tapxy_v3' in m and 'z100_maxpool_window20_rowbase_v2 reference_pool' in m and 'tap_x_q+tap_y_q*5!=tap_q' in m,'Original RTL is a passive bound observer, invariant checked each cycle')
        check('golden(co+bank/16,oy,ox)' in tb and 'largest=-128' in tb and 'if(v>largest)' in tb,'Independent signed scalar max oracle, including negative-only padding semantics')
        top=ROOT/'deployment/hardware/z100_2026/feature_payload_v8/z100_native_row20_shared_pool_payload_v8.sv'
        newtop=new.parent/'z100_native_row20_shared_pool_tapxy_v9.sv'
        check(top.read_text().replace('module z100_native_row20_shared_pool_payload_v8','module z100_native_row20_shared_pool_tapxy_v9').replace('z100_maxpool_window20_rowbase_v2 pool_consumer','z100_maxpool_window20_tapxy_v3 pool_consumer')==newtop.read_text(),'Top name/Pool type only, unchanged compute and bank arithmetic')
        protected=json.loads((ROOT/'validation/board_z100/acceleration_resource_review/20261023/protected_before.json').read_text())['files']
        for n,h in protected.items():check(sha(ROOT/n)==h,'Protected source '+n)
        r.update(status='ROOT_REVIEWED_POOL_TAPXY_V9_COORDINATE_ONLY_CYCLE_MITER_SIGNED_NUMERIC_CANCEL_NOT_CORE_OR_TIMING',simulation=p['simulation'],source_artifact_hashes_checked=len(checked),protected_sources_checked=len(protected),report_binding=dict(path=str(PROOF.relative_to(ROOT)),sha256=sha(PROOF)),
            scope='Coordinate recurrence only; no request-cycle or original Pool control change. Passive original RTL miter covers23770 cycles,20483 valid-window cycles and2258 valid output cycles, including stalls/cancel/fault.Independent signed5x5 oracle verifies1304 packed words with128-channel full20-row and5-channel3-row tail shapes. Current-model full compute integration, OOC resources, placed/routed timing and physical FPS remain unaccepted.')
    except Exception as exc:r.update(status='FAILED_ROOT_REVIEW_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['reviewer_sha256']=sha(Path(__file__));path=out/'result.json';path.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(path),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
