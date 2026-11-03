"""Run private reuse-v1 elastic command bridge RTL simulation with Vivado XSim."""
import json
import re
from pathlib import Path
from datetime import datetime, timezone
import uuid
from validate_z100_reuse_sync import ROOT, sha256, VIVADO_DEFAULT, run_command


def parse_result(text):
    if re.search(r'Fatal:|FAIL|ERROR:',text): raise ValueError('Simulator failure')
    matches=re.findall(r'BRIDGE_PASS commands=(\d+) results=(\d+) cancels=(\d+) errors=(\d+) resets=(\d+)',text)
    if len(matches)!=1: raise ValueError('Expected one bridge completion marker')
    values=dict(zip(('commands','results','cancels','errors','resets'),map(int,matches[0])))
    if values['commands']<100 or any(values[k]!=v for k,v in (('results',20),('cancels',6),('errors',2),('resets',1))):
        raise ValueError('Bridge activity coverage changed')
    return values


def main():
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    evidence=ROOT/'validation/board_z100/reuse_core_v1'/run_id
    build=ROOT/'deployment/build/z100_reuse_core_v1'/run_id/'bridge'
    evidence.mkdir(parents=True);build.mkdir(parents=True)
    core=ROOT/'deployment/hardware/z100_2026/tile_reuse_core_v1'
    sources=[core/name for name in ('z100_tile_reuse_core.v','z100_reuse_command_bridge.v','tb_z100_reuse_command_bridge.sv')]
    identities={str(p.relative_to(ROOT)):sha256(p) for p in [*sources,Path(__file__)]}
    bindir=VIVADO_DEFAULT.parent
    commands=[('xvlog',[str(bindir/'xvlog.bat'),'-sv',*map(str,sources)]),
              ('xelab',[str(bindir/'xelab.bat'),'-mt','2','tb_z100_reuse_command_bridge','-s','bridge_sim']),
              ('xsim',[str(bindir/'xsim.bat'),'bridge_sim','-runall'])]
    report=dict(status='FAIL',run_id=run_id,source_sha256=identities,commands=[],
                physical_board_tested=False,production_protocol_compatible=False,release_eligible=False)
    for name,command in commands:
        result=run_command(command,build,evidence/(name+'.log'))
        report['commands'].append({k:v for k,v in result.items() if k!='output'})
        if result['return_code']!=0:break
        if name=='xsim':
            try:
                report['coverage']=parse_result(result['output'])
                if identities!={str(p.relative_to(ROOT)):sha256(p) for p in [*sources,Path(__file__)]}:raise ValueError('Sources changed')
                report['status']='PASS_PRIVATE_ELASTIC_COMMAND_BRIDGE'
            except ValueError as exc:report['error']=str(exc)
    report['log_sha256']={str(p.relative_to(ROOT)):sha256(p) for p in evidence.glob('*.log')}
    (evidence/'bridge_result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],report=str(evidence/'bridge_result.json'),error=report.get('error'))))
    return 0 if report['status'].startswith('PASS_') else 1


if __name__=='__main__':raise SystemExit(main())
