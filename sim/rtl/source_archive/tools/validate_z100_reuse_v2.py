"""Validate free-running operand registers, then route a separate DSP fixture."""
import json
from pathlib import Path
from datetime import datetime,timezone
import uuid
import validate_z100_reuse_v1 as sim
from validate_z100_reuse_sync import ROOT,sha256,run_command,VIVADO_DEFAULT


def main():
    run=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    core=ROOT/'deployment/hardware/z100_2026/tile_reuse_core_v2'
    evidence=ROOT/'validation/board_z100/reuse_core_v2'/run;evidence.mkdir(parents=True)
    build=ROOT/'deployment/build/z100_reuse_core_v2'/run
    sim.CORE_DIR=core;sim.BUILD_ROOT=build.parent
    sources=[core/n for n in ('z100_tile_reuse_core.v','tb_z100_tile_reuse_core.sv','dsp_impl.tcl')]
    sources += [Path(__file__).resolve(),ROOT/'tools/validate_z100_reuse_v1.py',
                ROOT/'deployment/hardware/z100_2026/reuse_sync_fixture/z100_tile_reuse_sync_fixture_top.v',
                ROOT/'deployment/hardware/z100_2026/reuse_sync_fixture/sync_constraints.xdc',
                ROOT/'deployment/hardware/z100_2026/tile_reuse_core_v1/z100_tile_reuse_core.v']
    before={str(p.relative_to(ROOT)):sha256(p) for p in sources}
    report=dict(status='RUNNING',run_id=run,core='v2',frequency_mhz=200,source_sha256=before,
                physical_board_tested=False,release_eligible=False,build_dir=str(build))
    (evidence/'launch.json').write_text(json.dumps(report,indent=2)+'\n')
    tools={n:VIVADO_DEFAULT.parent/(n+'.bat') for n in ('xvlog','xelab','xsim')}
    result=sim.run_sim(tools,run,evidence);report['simulation']=result
    if result['status']!='PASS' or result['summary']['jobs']!=40 or result['summary']['abort_checks_passed']!=8:
        report['status']='SIMULATION_FAILED'
    else:
        command=[str(VIVADO_DEFAULT),'-mode','batch','-log',str(evidence/'vivado.log'),'-journal',str(evidence/'vivado.jou'),
                 '-source',str(core/'dsp_impl.tcl'),'-tclargs','200',str(build),str(evidence),'all']
        result=run_command(command,ROOT,evidence/'stdout.log')
        report['command']={k:v for k,v in result.items() if k!='output'}
        report['status']='ROUTE_EXECUTION_COMPLETED_REQUIRES_REVIEW' if result['return_code']==0 else 'ROUTE_EXECUTION_FAILED'
    if before!={str(p.relative_to(ROOT)):sha256(p) for p in sources}:report['status']='SOURCES_CHANGED'
    report['artifact_sha256']={str(p.relative_to(ROOT)):sha256(p) for p in evidence.iterdir() if p.is_file()}
    (evidence/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],report=str(evidence/'result.json'))))
    return 0 if report['status']=='ROUTE_EXECUTION_COMPLETED_REQUIRES_REVIEW' else 1


if __name__=='__main__':raise SystemExit(main())
