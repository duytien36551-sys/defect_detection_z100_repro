"""Root inventory and bounded acceptance for three private stream components."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
REPORTS={
    'pointwise':'pointwise_lookup_v1/20261023T170247.984305Z_e9bd94e5',
    'requant':'requant_vector_v1/20261023T170603.603537Z_1260c0c7',
    'native_integration':'window_mac_integration_v1/20261023T170656.575146Z_6a293ada',
}


def require(test,message):
    if not test: raise ValueError(message)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    reviewed={}
    for name,folder in REPORTS.items():
        path=ROOT/'validation/board_z100'/folder/'result.json'
        data=json.loads(path.read_text())
        require(data['status'].startswith('PASS_'),f'Failure:{name}')
        before=data.get('source_sha256_before',data.get('source_sha256'))
        require(before==data['source_sha256_after'],f'Source moved:{name}')
        aliases={'rtl':'deployment/hardware/z100_2026/pointwise_lookup_v1/z100_pointwise_lookup.sv',
            'testbench':'deployment/hardware/z100_2026/pointwise_lookup_v1/tb_z100_pointwise_lookup.sv',
            'validator':'tools/validate_z100_pointwise_lookup.py'} if name=='pointwise' else {}
        for f,h in before.items():
            actual=ROOT/aliases.get(f,f)
            if isinstance(h,dict):
                require(actual.stat().st_size==h['bytes'],f'Source length drift:{f}')
                h=h['sha256']
            require(sha(actual)==h,f'Source drift:{f}')
        inventory=data.get('artifact_sha256',data.get('artifact_inventory'))
        for f,h in inventory.items():
            actual=ROOT/f
            if isinstance(h,dict):
                require(actual.stat().st_size==h['bytes'],f'Length drift:{f}')
                h=h['sha256']
            require(sha(actual)==h,f'Artifact drift:{f}')
        reviewed[name]={'report':str(path.relative_to(ROOT)),'sha256':sha(path),
            'source_count':len(before),'artifact_count':len(inventory),'simulation':data['simulation']}
        if name=='pointwise':
            s=data['simulation'];hw=data['synthesis']
            require(s['tables']==128 and s['exhaustive_values']==424448 and
                s['max_consecutive_accepts_ii1']>=4096 and s['output_stall_cycles']>0 and
                s['reload_rejected_while_inflight'] and s['tail_lanes_zero'],'Pointwise coverage')
            require(hw['ram36']==128 and hw['ram18']==0 and hw['dsp']==0 and
                hw['latch']==0 and hw['blackbox']==0 and hw['lut']<=12000 and hw['ff']<=6000,
                'Pointwise fixed OOC screen')
            reviewed[name]['synthesis']=hw
        elif name=='requant':
            s=data['simulation'];cov=data['coverage']
            require(cov['channels']==5419 and cov['native_jobs']==173 and
                cov['c_verified_boundary_records_checked_against_python']==4156373 and
                cov['python_oracle_and_upper_bound_matches']==4156373,'Requant host identity/coverage')
            require(s['main_vector_beats']==132691 and s['main_outputs']==132691 and
                s['accept_ii_failures']==0 and s['output_ii_failures']==0 and
                s['first_job_accept_to_output_cycles']==8 and s['inactive_tail_zero_checks']==90059 and
                s['cancel_stage_flushes']==8 and s['reset_stage_flushes']==8 and
                s['invalid_configuration_cases']==9 and s['invalid_input_cases']==3,'Requant RTL coverage')
        else:
            s=data['simulation']
            expected={'jobs':6,'requests':54,'responses':54,'outputs':22,'raw_words':704,
                'flags':704,'load_words':8160,'weight_groups':9,'bias_loads':1,'residency':6}
            require(all(s[k]==v for k,v in expected.items()),'Real native operand/residency coverage')
            require(s['response_stalls']>0 and s['output_stalls']>0 and s['input_bubbles']>0,'Native flow coverage')
    result={
        'status':'ROOT_REVIEW_PRIVATE_STREAM_COMPONENTS_PASS_NOT_FULL_PIPELINE',
        'utc':datetime.now(timezone.utc).isoformat(),'reviewed':reviewed,
        'native_bridge_limit':'Externally owned run_token must remain fixed from first queued descriptor through final output; this is bounded real-operand arithmetic integration, not production scheduler/abort/admission acceptance.',
        'corrections_preserved':'Earlier source-key/preflight/CLI/TB delta-cycle and token-stability failures remain immutable. Root read core/TB and corrected test job-token ownership before queuing; no frozen feature/window/MAC core changed.',
        'worker_execution_limit_deviation':'Pointwise worker continued past its two-failure packet stop threshold. Root reviewed actual passed source/coverage/inventory and prohibited further runs; passing evidence is accepted only on its technical scope, not as compliance with that execution rule.',
        'board_access':False,'timing_accepted':False,'production_integrated':False,
        'full_pipeline_30fps_accepted':False,'reviewer_sha256':sha(Path(__file__)),
    }
    dest=ROOT/'validation/board_z100/acceleration_resource_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    dest.mkdir(parents=True,exist_ok=False);path=dest/'stream_components_review.json'
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'report':str(path)}))


if __name__=='__main__':main()
