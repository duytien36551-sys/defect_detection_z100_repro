"""Validate same-cycle raw FIFO read-pointer replicas against baseline and queue model."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'deployment/hardware/z100_2026/native_raw_buffer_v1/z100_native_raw_buffer.sv'
CANDIDATE = ROOT/'deployment/hardware/z100_2026/native_raw_buffer_local_v2/z100_native_raw_buffer_local_v2.sv'
TB = ROOT/'deployment/hardware/z100_2026/native_raw_buffer_local_v2/tb_z100_native_raw_buffer_local_v2.sv'
LOCAL_ROOT = ROOT/'deployment/build/local_tools/iverilog13_msys2'
PASS = re.compile(r'^RAW_BUFFER_LOCAL_V2_PASS (.+)$', re.M)
ERROR = re.compile(r'(?:\berror:|syntax error|unknown module|unable to bind|port .* expects)', re.I)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def key(path):
    p=Path(path).resolve()
    try: return p.relative_to(ROOT).as_posix()
    except ValueError: return 'external/'+p.as_posix().replace(':','')


def require(ok,msg):
    if not ok: raise ValueError(msg)


def expected_candidate(base_text):
    old_module='module z100_native_raw_buffer ('
    require(base_text.count(old_module)==1,'Unique baseline module')
    text=base_text.replace(old_module,'module z100_native_raw_buffer_local_v2 (',1)
    old='''    reg [1:0] count;
    reg read_pointer,write_pointer;
    reg [1093:0] payload0,payload1;
    wire enable=rst_n&&!cancel;
    assign in_ready=enable&&count<2;
    assign out_valid=enable&&count!=0;
    assign {out_epoch,out_token,out_site,out_last,out_data}=read_pointer ? payload1 : payload0;
    wire push=in_valid&&in_ready;
    wire pop=out_valid&&out_ready;
'''
    new='''    reg [1:0] count;
    reg write_pointer;
    reg [1093:0] payload0,payload1;
    wire enable=rst_n&&!cancel;
    assign in_ready=enable&&count<2;
    assign out_valid=enable&&count!=0;
    wire push=in_valid&&in_ready;
    wire pop=out_valid&&out_ready;

    wire [1093:0] selected_payload;
    genvar group_index;
    generate for(group_index=0;group_index<35;group_index=group_index+1) begin : gen_local_read_pointer
        localparam integer LOW=group_index*32;
        localparam integer WIDTH=(LOW+32<=1094) ? 32 : (1094-LOW);
        (* dont_touch="true", keep="true" *) reg local_read_pointer;
        always @(posedge clk) begin
            if(!rst_n||cancel) local_read_pointer<=1'b0;
            else if(pop) local_read_pointer<=!local_read_pointer;
        end
        assign selected_payload[LOW+:WIDTH]=local_read_pointer ? payload1[LOW+:WIDTH] : payload0[LOW+:WIDTH];
    end endgenerate
    assign {out_epoch,out_token,out_site,out_last,out_data}=selected_payload;
'''
    require(text.count(old)==1,'Exact public FIFO read-select seam')
    text=text.replace(old,new,1)
    require(text.count('if(!rst_n||cancel)begin count<=0;read_pointer<=0;write_pointer<=0;end')==1,
            'Exact baseline reset seam')
    text=text.replace('if(!rst_n||cancel)begin count<=0;read_pointer<=0;write_pointer<=0;end',
                      'if(!rst_n||cancel)begin count<=0;write_pointer<=0;end',1)
    require(text.count('            if(pop)read_pointer<=!read_pointer;\n')==1,'Exact baseline read-pointer update')
    text=text.replace('            if(pop)read_pointer<=!read_pointer;\n','',1)
    return text


def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_raw_buffer_local_v2'/stamp
    build=ROOT/'deployment/build/native_raw_buffer_local_v2'/stamp
    out.mkdir(parents=True);build.mkdir(parents=True)
    result_path=out/'result.json'
    result=dict(schema='z100-raw-buffer-local-v2-validation/1',status='PREFLIGHT',
        board_access=False,synthesis_or_route_run=False,routed_timing_accepted=False,
        full_pipeline_30fps_accepted=False,
        scope='Local RTL behavioral equivalence and queue-order test only; physical timing and mapped cost unmeasured.')
    sources=[];before={}
    try:
        manifest_path=LOCAL_ROOT/'manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        require(manifest.get('schema')=='project-local-iverilog/1' and
                manifest.get('versions',{}).get('iverilog','').startswith('Icarus Verilog version 13.0'),
                'Pinned project-local Icarus 13 required')
        runtime=[manifest_path]
        for relative,digest in manifest['files'].items():
            path=LOCAL_ROOT/Path(relative.replace('\\','/'))
            require(path.is_file() and sha(path)==digest,'Pinned Icarus component hash mismatch: '+relative)
            runtime.append(path)
        compiler=LOCAL_ROOT/'ucrt64/bin/iverilog.exe'
        runner=LOCAL_ROOT/'ucrt64/bin/vvp.exe'
        backend=LOCAL_ROOT/'ucrt64/lib/ivl'
        require(compiler.is_file() and runner.is_file() and backend.is_dir(),'Pinned compiler/runtime backend missing')
        sources=[Path(__file__),BASE,CANDIDATE,TB,*runtime,compiler,runner]
        require(all(p.is_file() for p in sources),'A source/runtime file is missing')
        require(CANDIDATE.read_text(encoding='utf-8')==expected_candidate(BASE.read_text(encoding='utf-8')),
                'Candidate differs from the bounded same-cycle replica transformation')
        before=dict(sorted((key(p),sha(p)) for p in sources))
        result.update(source_sha256_before=before,
            source_closure={key(p):sha(p) for p in (BASE,CANDIDATE,TB,manifest_path,compiler,runner)},
            candidate_change=dict(public_interface=False,slot_count=2,slot_payload_bits=1094,
                selector_groups=35,group_bits=32,final_group_bits=6,extra_pointer_flops=34,
                read_pointer_extra_pipeline_cycles=0,write_or_occupancy_logic_changed=False,
                mapped_ff_count='NOT_MEASURED'))
        result_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        env=dict(os.environ);env['PATH']=str(LOCAL_ROOT/'ucrt64/bin')+os.pathsep+env.get('PATH','')
        env['OMP_NUM_THREADS']='1'
        compile_argv=[str(compiler),'-B',str(backend),'-g2012','-Wall','-s','tb_z100_native_raw_buffer_local_v2','-o',
            str(build/'raw_buffer_local_v2.vvp'),str(BASE),str(CANDIDATE),str(TB)]
        start=time.monotonic()
        comp=subprocess.run(compile_argv,cwd=build,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        comp_log=comp.stdout+('\n' if comp.stdout and comp.stderr else '')+comp.stderr
        comp_path=out/'iverilog.log';comp_path.write_text(comp_log,encoding='utf-8')
        result['compile_command']=dict(argv=compile_argv,cwd=str(build),return_code=comp.returncode,
            elapsed_seconds=round(time.monotonic()-start,3),log=key(comp_path),log_sha256=sha(comp_path))
        require(comp.returncode==0 and not ERROR.search(comp_log),'Icarus compile failed; see '+str(comp_path))
        executable=build/'raw_buffer_local_v2.vvp';require(executable.is_file(),'Compiled simulation image missing')
        run_argv=[str(runner),'-M',str(backend),str(executable)]
        start=time.monotonic()
        sim=subprocess.run(run_argv,cwd=build,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        sim_log=sim.stdout+('\n' if sim.stdout and sim.stderr else '')+sim.stderr
        sim_path=out/'vvp.log';sim_path.write_text(sim_log,encoding='utf-8')
        result['simulation_command']=dict(argv=run_argv,cwd=str(build),return_code=sim.returncode,
            elapsed_seconds=round(time.monotonic()-start,3),log=key(sim_path),log_sha256=sha(sim_path))
        require(sim.returncode==0 and not ERROR.search(sim_log),'VVP simulation failed; see '+str(sim_path))
        matches=PASS.findall(sim_log);require(len(matches)==1,'Exactly one FIFO equivalence/coverage PASS marker required')
        counts={name:int(value) for name,value in re.findall(r'(\w+)=(\d+)',matches[0])}
        gates=dict(cycles=600,pushes=100,pops=100,simultaneous=40,full_stalls=2,output_stalls=40,
                   bubbles=30,resets=2,cancels=2,pointer_checks=21000,head_checks=100,extra_pointer_flops=34)
        require(all(counts.get(name,-1)>=minimum for name,minimum in gates.items()),'Incomplete queue/pointer coverage: '+str(counts))
        require(sim_log.count('$finish called at')==1,'Simulation did not reach one normal finish')
        after=dict(sorted((key(p),sha(p)) for p in sources))
        require(before==after,'A pinned source/runtime changed during simulation')
        result.update(status='PASS_LOCAL_FIFO_PUBLIC_CYCLE_AND_QUEUE_MODEL',source_sha256_after=after,
            coverage=counts,simulation_scope='Baseline public-cycle match plus independent two-entry model of accepted pushes/pops/payload order; 35 replicas checked every sample.')
    except Exception as exc:
        result.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
        if before:
            result['source_sha256_before']=before
            result['source_sha256_after']={key(p):sha(p) for p in sources}
    result['artifact_sha256']={str(path.relative_to(ROOT)).replace('\\','/'):sha(path)
        for folder in (out,build) for path in folder.rglob('*') if path.is_file() and path!=result_path}
    result_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],report=key(result_path),error=result.get('error'))))
    raise SystemExit(0 if result['status'].startswith('PASS_') else 1)


if __name__=='__main__': main()
