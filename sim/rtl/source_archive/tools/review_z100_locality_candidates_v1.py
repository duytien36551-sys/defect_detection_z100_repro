"""Review candidate diffs and actual logs; does not promote measured timing."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import re

from validate_z100_raw_buffer_local_v2 import expected_candidate
from validate_z100_mac_local_weight_v2 import expected_weight_candidate, expected_weight_testbench, parse_marker

ROOT=Path(__file__).resolve().parents[1]


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def resolve(n):
    n=n.replace('\\','/')
    return Path(n[9:10]+':/'+n[11:]) if n.startswith('external/') else ROOT/n


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--weight-proof',type=Path,action='append',required=True)
    ap.add_argument('--raw-proof',type=Path,required=True)
    a=ap.parse_args()
    out=ROOT/'validation/board_z100/locality_candidates_root_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True)
    r=dict(status='FAILED_CLOSED',board_access=False,vendor_flow_run=False,
           mapped_resources_accepted=False,routed_timing_accepted=False,full_pipeline_30fps_accepted=False)
    pins={str(Path(__file__).relative_to(ROOT)):sha(Path(__file__))}
    try:
        hw=ROOT/'deployment/hardware/z100_2026'
        raw=hw/'native_raw_buffer_local_v2/z100_native_raw_buffer_local_v2.sv'
        weight=hw/'mac_local_weight_v2/z100_window_mac_local_weight_v2.sv'
        assert raw.read_text()==expected_candidate((hw/'native_raw_buffer_v1/z100_native_raw_buffer.sv').read_text())
        assert weight.read_text()==expected_weight_candidate((hw/'mac_local_control_v1/z100_window_mac_local_control_v1.sv').read_text())
        assert (hw/'mac_local_weight_v2/tb_z100_mac_local_weight_v2.sv').read_text()==expected_weight_testbench((hw/'mac_local_control_v3_validation/tb_z100_mac_local_control_v3.sv').read_text())
        weights={}
        for proof in [a.raw_proof,*a.weight_proof]:
            proof=proof.resolve()
            p=json.loads(proof.read_text())
            assert p['source_sha256_before'] and p['source_sha256_before']==p['source_sha256_after']
            for name,digest in {**p['source_sha256_after'],**p['artifact_sha256']}.items():
                assert sha(resolve(name))==digest,name
                pins[name]=digest
            pins[str(proof.relative_to(ROOT))]=sha(proof)
            if proof==a.raw_proof.resolve():
                assert p['status']=='PASS_LOCAL_FIFO_PUBLIC_CYCLE_AND_QUEUE_MODEL'
                assert p['compile_command']['return_code']==p['simulation_command']['return_code']==0
                log=resolve(p['simulation_command']['log']).read_text()
                lines=re.findall(r'^RAW_BUFFER_LOCAL_V2_PASS (.+)$',log,re.M)
                assert len(lines)==1 and log.count('$finish called at')==1
                counts={n:int(v) for n,v in re.findall(r'(\w+)=(\d+)',lines[0])}
                for name,minimum in dict(cycles=600,pushes=100,pops=100,simultaneous=40,full_stalls=2,output_stalls=40,resets=2,cancels=2,pointer_checks=21000).items():
                    assert counts[name]>=minimum,name
                r['raw_buffer']=dict(candidate_sha256=sha(raw),counters=counts,additional_logical_pointer_FF=34)
            else:
                assert p['status']=='PASS_LOCAL_VENDOR_SOURCE_CYCLE_EQUIVALENCE_SIMULATION_ONLY'
                for sites,counts in p['simulation']['sites'].items():
                    commands=[c for c in p['commands'] if c['name'].startswith(f'sites{sites}_')]
                    assert len(commands)==2 and all(c['return_code']==0 for c in commands)
                    args=commands[0]['argv']
                    for model in ('DSP48E1.v','MULT_MACRO.v','glbl.v'):
                        assert any(Path(x).name==model for x in args)
                    assert not any('FAST_SIM' in x for x in args)
                    log=resolve(commands[1]['log']).read_text()
                    actual=parse_marker(log,int(sites))
                    assert actual==counts and log.count('$finish called at')==1
                    weights[sites]=actual
        assert {'1','2'}.issubset(weights)
        for dep in ('tools/validate_z100_raw_buffer_local_v2.py','tools/validate_z100_mac_local_weight_v2.py'):
            pins[dep]=sha(ROOT/dep)
        r.update(status='REVIEWED_LOCALITY_CANDIDATES_SIMULATION_ONLY_NOT_INTEGRATED',
            weight_operand=dict(candidate_sha256=sha(weight),sites=weights,additional_logical_weight_FF_at_sites20=19456),
            scope='Separate candidate simulations and exact source transformations only. Combined integration and routed timing require fresh evidence.')
    except Exception as exc:
        r['error']=f'{type(exc).__name__}: {exc}'
    r['source_sha256_before']=pins
    r['source_sha256_after']={n:sha(resolve(n)) for n in pins}
    assert r['source_sha256_before']==r['source_sha256_after']
    (out/'result.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(out/'result.json'),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))


if __name__=='__main__':
    raise SystemExit(main())
