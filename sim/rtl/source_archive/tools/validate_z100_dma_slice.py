"""Verify the installed supported R-channel slice with stalls and reset cancellation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import uuid
from project_config import load_project_config, resolve_external_path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated-ip',type=Path,help='Generated public register-slice simulation wrapper')
    args=parser.parse_args()
    _,config,local=load_project_config(ROOT)
    install=resolve_external_path(config,local,"vivado.target2026.1")
    if install is None: raise ValueError("Vivado not configured")
    source=install/'data/ip/xilinx/axi_register_slice_v2_1/hdl/axi_register_slice_v2_1_rfs.v'
    test=ROOT/'deployment/hardware/z100_2026/dma_slice_tests/tb_mm2s_response_slice.v'
    top='tb_mm2s_response_slice'
    additional=[]
    if args.generated_ip:
        generated=args.generated_ip.resolve()
        if ROOT not in generated.parents or not generated.is_file(): raise ValueError('Generated wrapper must exist inside project')
        additional=[install/'data/ip/xilinx/axi_infrastructure_v1_1/hdl/axi_infrastructure_v1_1_vl_rfs.v',generated]
        test=ROOT/'deployment/hardware/z100_2026/dma_slice_tests/tb_mm2s_public_slice.v'
        top='tb_mm2s_public_slice'
    include=install/'data/ip/xilinx/axi_infrastructure_v1_1/hdl/axi_infrastructure_v1_1_0.vh'
    identity=uuid.uuid4().hex[:8]
    output=ROOT/'deployment/build/z100_slice_sim'/identity
    output.mkdir(parents=True,exist_ok=False)
    report_dir=ROOT/'validation/board_z100/dma_slice_review'/identity
    report_dir.mkdir(parents=True,exist_ok=False)
    calls=[('compile',[str(install/'bin/xvlog.bat'),'-i',str(install/'data/ip/xilinx/axi_infrastructure_v1_1/hdl'),str(source),*[str(p) for p in additional],str(test)]),
           ('elaborate',[str(install/'bin/xelab.bat'),'--mt','2',top,'-s','slice_snapshot']),
           ('simulate',[str(install/'bin/xsim.bat'),'slice_snapshot','-runall'])]
    records=[];passed=False
    for name,command in calls:
        log=report_dir/(name+'.log')
        with log.open('w',encoding='utf-8') as handle:
            run=subprocess.run(command,cwd=output,stdout=handle,stderr=subprocess.STDOUT,timeout=300)
        records.append({'command':command,'returncode':run.returncode,'log':log.relative_to(ROOT).as_posix()})
        if run.returncode: break
        if name=='simulate': passed='PASS MM2S_RESPONSE_SLICE' in log.read_text(encoding='utf-8',errors='replace')
    report={'status':'PASS' if passed else 'FAIL','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'include':str(include),'include_sha256':hashlib.sha256(include.read_bytes()).hexdigest(),
            'test':str(test),'test_sha256':hashlib.sha256(test.read_bytes()).hexdigest(),
            'additional_sources':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in additional],
            'commands':records,'output':str(output),'scope':('generated public read-only AXI slice R=1/AR=7 response/address handshake simulation' if additional else 'installed REG_R=1 payload/handshake simulation')+', not physical DMA test',
            'physical_board_tested':False}
    path=report_dir/'result.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'report':str(path)},indent=2))
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
