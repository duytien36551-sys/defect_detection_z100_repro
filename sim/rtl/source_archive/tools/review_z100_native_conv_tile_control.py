"""Review tile sequencer metadata proof; synthetic child ACK scope stays explicit."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
ACTUAL=ROOT/'validation/board_z100/native_conv_tile_control_v2/20261025T122519.447891Z/result.json'
ORACLE=ROOT/'validation/board_z100/native_row_commands_v2/20261025T062641.961558Z/result.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    out=ROOT/'validation/board_z100/native_conv_tile_control_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    result=dict(status='RUNNING',board_access=False,pixel_compute_executed=False,actual_DDR_publication_accepted=False,
        physical_deployed=False,route_or_frequency_accepted=False,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(ACTUAL.read_text());c=json.loads(ORACLE.read_text());checked={}
        check(p['status']=='PASS_PRIVATE_CONV_TILE_CONTROL_V2_189_TILES7220_C_ORACLE_ROWS_GROUP_ORDER_PUBLICATION_AND_RECOVERY_XSIM_ONLY','Closed actual tile simulation')
        check(c['status']=='PASS_HOST_C_V2_ALL189_HALO_ROW_COMMANDS173_BOUND_PARAMETER_JOBS_ZERO_TOKEN_REJECTED_NOT_INFERENCE','Actual C metadata oracle')
        for proof in (p,c):
            check(proof['source_sha256_before']==proof['source_sha256_after'],'Stable proof source')
            for n,h in {**proof['source_sha256_after'],**proof['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Bound source/artifact '+n);checked[n]=h
        check(len(p['commands'])==3 and all(x['return_code']==0 for x in p['commands']),'Actual compile/elaborate/sim complete')
        for log in ACTUAL.parent.glob('*.log'):check(not re.search(r'^\s*(?:ERROR:|Fatal:)',log.read_text(errors='replace'),re.M),'Strict actual diagnostics')
        check(p['simulation']==dict(graph_tiles=189,graph_rows=7220,graph_publications=189,graph_pack_configs=189,negative_cases=12,recovery_blocks=48,held_cycles=23427,publication_wait_cycles=1330,parameter_requests=377),'Complete exact graph metadata and negative coverage')
        header=ROOT/c['generated_plan'];bindings=header.parent/'row_bindings.json';jobs=json.loads(bindings.read_text())['tiles']
        check(sum(len(t['parameter_jobs']) for t in jobs)==375,'All graph parameter requests plus two successful negative-test preparations explain377')
        tb=(ROOT/'deployment/hardware/z100_2026/native_conv_tile_control_v1/tb_z100_native_conv_tile_control_v2.sv').read_text()
        check('row_ky_bases!=expected[n+9]' in tb and 'row_token_base!=expected[n+3]' in tb and 'row_tag_base!=expected[n+4]' in tb,'Hardware outputs compared directly with executed C output')
        check('if(done||cmd_ready||!active||!publish_ready)' in tb and 'if(!fault||!child_cancel||cmd_ready)' in tb,'No completion before publication and no recovery before drained ACK')
        rtl=(ROOT/'deployment/hardware/z100_2026/native_conv_tile_control_v1/z100_native_conv_tile_control_v2.sv').read_text()
        check('cmd_epoch>ledger_epoch||(cmd_epoch==ledger_epoch&&cmd_job_tag>ledger_tag)' in rtl and 'parameter_done_job_tag!=job_tag_q' in rtl and 'row_done_job_tag!=job_tag_q' in rtl and 'publish_tag!=job_tag_q' in rtl,'Job-bound completion and monotonic admission code audited')
        protected=json.loads((ROOT/'validation/board_z100/acceleration_resource_review/20261023/protected_before.json').read_text())['files']
        for n,h in protected.items():check(sha(ROOT/n)==h,'Protected source '+n)
        result.update(status='ROOT_REVIEWED_CONV_TILE189_7220_C_ORACLE_ROWS_GROUP_ORDER_AND_SYNTHETIC_PUBLICATION_NOT_PIXEL_EXECUTION',
            source_artifact_hashes_checked=len(checked),protected_sources_checked=len(protected),simulation=p['simulation'],
            report_bindings={str(q.relative_to(ROOT)):sha(q) for q in (ACTUAL,ORACLE)},
            scope='All189 Conv tile metadata sequences and all7220 C-oracle row fields.375 normal parameter-group requests; two extra successful preparations inside negative tests. Twelve exercised faults, same-frame job-tag replay rejection and drained recovery; epoch monotonic code audited but epoch rollback/wrap transitions not independently exercised. Parameter/row/publication ACKs are synthetic TB events, not executed Conv pixels, real DDR publication, graph source leases, timing or FPS.',
            next_gate='Use this controller to drive real parameter loader, row scheduler/compute, packer and writer for a full output tile, comparing original OIHW integer convolution and canonical output layout. Then all materialized graph nodes and native PS/HP/MMIO/firmware.')
    except Exception as exc:result.update(status='FAILED_ROOT_REVIEW_CLOSED',error=f'{type(exc).__name__}: {exc}')
    result['reviewer_sha256']=sha(Path(__file__));path=out/'result.json';path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],report=str(path),error=result.get('error'))));return int(result['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
