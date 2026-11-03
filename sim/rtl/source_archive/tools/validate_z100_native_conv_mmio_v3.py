"""Actual local frontend control simulation; backend status is an explicit mock."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import uuid

from validate_z100_mac_local_control_v3 import local_runtime, source_key

ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026'
RTL=HW/'native_conv_mmio_v2/z100_native_conv_mmio_v2.sv'
TB=HW/'native_conv_mmio_v3_validation/tb_z100_native_conv_mmio_v3.sv'
ORIGINAL=HW/'native_conv_mmio_v1/z100_native_conv_mmio_v1.sv'
OLDTB=HW/'native_conv_mmio_v1/tb_z100_native_conv_mmio_v1.sv'
CONTRACT=ROOT/'validation/board_z100/native_conv_mmio_contract_v1/20261026T181445Z/result.json'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check(ok,message):
    if not ok:
        raise ValueError(message)


def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:6]
    out=ROOT/'validation/board_z100/native_conv_mmio_v3_validation'/stamp
    build=ROOT/'build'/('ncmmio3_'+stamp[9:])
    out.mkdir(parents=True);build.mkdir(parents=True)
    result_path=out/'result.json'
    result=dict(status='PREFLIGHT',board_access=False,backend_mock=True,
        actual_backend_arithmetic_executed=False,fullgraph_execution_accepted=False,
        full_pipeline_30fps_accepted=False,scope='Frontend AXI-Lite control only. Backend command readiness/status/completion are explicitly mocked; no DMA or actual arithmetic execution.')
    sources=[]; before={}
    try:
        check(sha(ORIGINAL)=='d9b9c19b60386a3c5f6a9c87b0c7f90a656953a47361c5d5ca46ad7950f3283a','Frozen draft RTL provenance')
        check(sha(OLDTB)=='e0d942a7e27735d457008e9fa73eb37814f9f27ad782aab004799f97528ea2d8','Frozen draft TB provenance')
        expected=ORIGINAL.read_text().replace('module z100_native_conv_mmio_v1 (',
            '(* use_dsp = "no" *)\nmodule z100_native_conv_mmio_v2 (',1).replace(
            '(state_q != ST_IDLE) || accepted_q || result_valid_q;',
            '(state_q != ST_IDLE) || accepted_q || result_valid_q ||\n                         backend_fault || fault_seen_q || backend_active || !backend_all_io_quiet;',1)
        check(RTL.read_text()==expected,'Exact bounded RTL change: gate shadow writes by READY health plus synthesis DSP prohibition')
        contract=json.loads(CONTRACT.read_text())
        check(contract['validation']['exit_code']==0 and contract['reviewed_sources_unchanged'],'Actual declaration-check prerequisite')
        for name,digest in {**contract['source_hashes_after'],**contract['deliverable_sha256']}.items():
            check(sha(ROOT/name)==digest.lower(),'Frozen ABI/source contract drift: '+name)
        compiler,runner,backend,runtime_paths,_=local_runtime()
        sources=[Path(__file__),ROOT/'tools/validate_z100_mac_local_control_v3.py',RTL,TB,ORIGINAL,OLDTB,CONTRACT,
            *[ROOT/n for n in contract['deliverable_sha256']],*runtime_paths]
        before={source_key(p):sha(p) for p in sources}
        result['source_sha256_before']=before
        result['commands']=[]
        result['draft_failure_disposition']='Draft lacked source-bound logs; preserved source/vvp. Test mock had stayed quiet after backend acceptance, allowing legal cancel deassertion before sampling. V2 mock creates outstanding work at acceptance; source/destination generation expectations corrected. RTL additionally rejects shadow writes while backend unhealthy after fault ACK.'
        env=dict(os.environ,OMP_NUM_THREADS='1')
        env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
        exe=build/'test.vvp'
        steps=[('iverilog',[str(compiler),'-B',str(backend),'-g2012','-Wall','-s','tb_z100_native_conv_mmio_v3','-o',str(exe),str(RTL),str(TB)]),
            ('vvp',[str(runner),'-M',str(backend),str(exe)])]
        for label,argv in steps:
            proc=subprocess.run(argv,cwd=build,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
            log=proc.stdout+proc.stderr
            log_path=out/(label+'.log');log_path.write_text(log)
            result['commands'].append(dict(label=label,argv=argv,return_code=proc.returncode,log=source_key(log_path)))
            check(proc.returncode==0 and not re.search(r'(?im)^\s*(error:|fatal:|FAIL_NATIVE_CONV_MMIO)',log),'Strict actual '+label+' diagnostics')
        markers=re.findall(r'^PASS_NATIVE_CONV_MMIO_FRONTEND (.+)$',log,re.M)
        check(len(markers)==1 and log.count('$finish called at')==1,'Complete normal frontend test termination')
        counts={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        minimum=dict(awfirst=1,wfirst=1,bhold=3,rhold=6,partial=1,ro=1,unaligned=1,unmapped=2,
            zero_strobe=4,invalid=1,abort=1,timeout=1,abortrace=1,timeoutrace=1,earlyack=1,
            shadowlock=2,fault_active_quiet=1,success=1,raw_identity=2,grants=3,irq=2,coordinated_reset=2)
        check(all(counts.get(k,-1)>=v for k,v in minimum.items()),'Required executed control/ownership coverage')
        result.update(status='PASS_LOCAL_FRONTEND_CONTROL_WITH_MOCK_BACKEND_NOT_INTEGRATION',simulation=counts,
            synthesized_or_routed=False,backend_wrapper_mapping_validated=False)
    except Exception as exc:
        result.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    result['source_sha256_before']=before
    result['source_sha256_after']={source_key(p):sha(p) for p in sources}
    if before!=result['source_sha256_after']:
        result.update(status='FAILED_SOURCE_INTEGRITY')
    result['artifact_sha256']={source_key(p):sha(p) for d in (out,build) for p in d.rglob('*') if p.is_file() and p!=result_path}
    result_path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],report=str(result_path),error=result.get('error'))))
    return int(result['status'].startswith('FAILED'))


if __name__=='__main__':
    raise SystemExit(main())
