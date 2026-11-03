"""Summarize explicitly supplied offline evidence; does not run or deploy it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-report',type=Path,required=True)
    parser.add_argument('--reuse-report',type=Path,required=True)
    args=parser.parse_args()
    paths=[args.host_report,args.reuse_report,
        Path('validation/board_z100/offline_acceptance/20261021T055404Z_60502aca/result.json'),
        Path('validation/board_z100/model_readiness_completion/manifest_adapter_completion.json'),
        Path('validation/board_z100/architecture_options/options.json'),
        Path('validation/board_z100/architecture_options/decision_record.json'),
        Path('validation/board_z100/vendor_support_bundle/20261021T062857Z_69f07437/result.json'),
        Path('validation/board_z100/reuse_core_v0/20261021T063447Z_a67a4e39/manifest.json')]
    identities=[];documents=[]
    for value in paths:
        path=(ROOT/value).resolve()
        if ROOT not in path.parents:raise ValueError('evidence escapes project')
        raw=path.read_bytes();documents.append(json.loads(raw))
        identities.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(raw).hexdigest()))
    host,reuse,dma,model,options,decision,vendor,sim=documents
    if host['status']!='PASS_NONBOARD_REGRESSION_GATES_REMAIN':raise ValueError('host regression did not pass')
    if dma['status']!='PASS_FRESH_FULL_SUITE' or len(dma['fresh'])!=14:raise ValueError('full DMA suite missing')
    if not model['independent_verifier_passed'] or model['records']!=8000:raise ValueError('candidate manifest verification missing')
    if sim['status']!='SIM_PASS' or sim['sim']['summary']['jobs']!=40:raise ValueError('core simulation missing')
    for name in ('z100_tile_reuse_core.v','tb_z100_tile_reuse_core.sv'):
        key='deployment\\hardware\\z100_2026\\tile_reuse_core_v0\\'+name
        if sha(ROOT/key)!=sim['source_sha256'][key]:raise ValueError('simulated RTL/testbench changed')
        if reuse['source_sha256'].get(key)!=sim['source_sha256'][key]:raise ValueError('OOC and simulated RTL/testbench differ')
    for row in host['checks']:
        if sha(ROOT/row['log'])!=row['log_sha256']:raise ValueError('host result log changed')
    for row in dma['fresh']:
        if sha(Path(row['result_path']))!=row['result_sha256']:raise ValueError('fresh DMA result changed')
    tests={row['name']:row['unittest_count'] for row in host['checks'] if row.get('unittest_count')}
    report=dict(schema_version=1,status='OFFLINE_PREPARATION_DELIVERED_MODEL_AND_ARCHITECTURE_GATES_OPEN',
        created_at_utc=datetime.now(timezone.utc).isoformat(),generator_sha256=sha(Path(__file__)),
        evidence=identities,host_tests=tests,host_test_total=sum(tests.values()),
        fresh_dma_cases=14,pinned_dma_files=dma['pinned_file_count'],production_integrity=host['production_integrity'],
        primary_training_route='pin-paperstyle-resplit-20261021',primary_route_user_confirmed=True,
        deployment_input_size=640,deployment_resolution_user_confirmed=True,
        deployment_candidate='deployment/candidates/pin640',protocol='pin9-v8/2-input640',
        historical_pcb_pin_retained=True,final_model_selected=False,
        candidate_manifest=dict(records=8000,boxes=model['boxes'],clipped_boxes=model['clipped_boxes'],
            split_counts=model['split_counts'],integrity_verified=True,source_labels_modified=False,
            test_labels_read_for_integrity=True,model_evaluated=False),
        core=dict(simulation_jobs=40,simulated_rtl_matches=True,ooc_status=reuse.get('status'),
            ooc_runs=(reuse.get('ooc') or {}).get('runs',[]),integrated_into_dma=False,
            wrapper='Input-registered OOC timing fixture only; not a handshake-qualified bridge'),
        vendor_support_bundle_sent=vendor['sent'],
        findings_open=['REQP-181','LUTAR-1','RTSTAT-10','PDCN-1569','DSP methodology advisories'],
        remaining_dependencies=[
            dict(item='Primary300-epoch training and best checkpoint freeze',kind='training_not_board',status='PENDING'),
            dict(item='User-selected PIN640 chain: see dedicated migration acceptance evidence',kind='isolated_interface_migration_not_board',status='SEE_PIN640_REPORT'),
            dict(item='Final float/INT8 validation and package; normal-image false positives when data exists',kind='final_model_and_dataset_not_board',status='PENDING'),
            dict(item='Whole-graph activation/weight reuse, window/schedule/protocol/requant integration',kind='architecture_work_not_board',status='NOT_IMPLEMENTED_DEPENDS_ON_MODEL_INTERFACE_AND_OOC'),
            dict(item='Vendor supported disposition or further proof for open findings',kind='vendor_evidence_not_board',status='OPEN'),
            dict(item='Exact revisions/fullDDR/PHY identity and physical startup/coherency/throughput',kind='physical_board',status='NOT_RUN')],
        production_hardware_changed=False,production_firmware_changed=False,training_modified=False,
        physical_board_tested=False,bitstream_generated=False,boot_image_generated=False,
        fps_measured=False,release_eligible=False,all_nonboard_work_complete=False,goal4=None)
    out=ROOT/'validation/board_z100/nonboard_completion'
    out.mkdir(parents=True,exist_ok=True)
    target=out/'phase_report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# Z100 无板工程阶段报告','',f"状态：`{report['status']}`",'',
        f"主路线：新光电 PIN paper-style300e；用户已确认，保留 PCB/PIN 历史。正式权重未选择。",
        f"主机回归：{report['host_test_total']} 项通过；实际 DMA/BRAM 14 项完整重跑通过；341 项冻结文件保持一致。",
        '候选数据：8000 条、24563 个框、6400/800/800 划分，17 个十进制舍入边界修正有审计，原始标签不变。',
        f"隔离复用核：40 个仿真任务通过；OOC 状态 `{reuse.get('status')}`；未接入活动 DMA/固件。",'',
        '## OOC 记录','']
    for row in report['core']['ooc_runs']:
        lines.append(f"- {row['frequency_mhz']} MHz：流程退出码 {row['return_code']}，timing `{row.get('timing_closure')}`，route `{row.get('route_validation',{}).get('status')}`，resources `{row.get('routed_resources')}`。")
    lines+=['','## 未完成的依赖','']
    lines += [f"- {row['item']}：{row['status']}（{row['kind']}）。" for row in report['remaining_dependencies']]
    lines+=['','## 证据身份','']
    lines += [f"- `{row['path']}` — `{row['sha256']}`" for row in identities]
    lines+=['','完整说明见 [无板交付与剩余依赖](../../../docs/z100_nonboard_completion.md)。未测试实板、未测FPS、未验收最终模型；第四目标保持空值。']
    (out/'phase_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=report['status'],report=target.relative_to(ROOT).as_posix(),host_test_total=report['host_test_total'])))


if __name__=='__main__':main()
