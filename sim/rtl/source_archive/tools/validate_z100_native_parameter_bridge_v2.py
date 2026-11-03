"""Replay all current parameter requests into actual MAC/factor/unary RTL."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
C=ROOT/'validation/board_z100/native_parameter_load_v2/20261025T073235.855733Z/result.json'
W=ROOT/'deployment/build/z100_native_window_weights/20261024T105738.276927Z_d0abdde2'
F=ROOT/'deployment/build/z100_exact_requant_factors/20261024T121414.659603Z'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/native_parameter_bridge_v2'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('npb_'+stamp[-14:]);build.mkdir(parents=True);report=out/'result.json';before={}
    r=dict(status='RUNNING',commands=[],board_access=False,production_integrated=False,physical_deployed=False,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(C.read_text());check(p['status'].startswith('PASS_HOST_C_ALL173'),'Closed real C parameter trace')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Current asset/loader binding '+n)
        wm=json.loads((W/'manifest.json').read_text());fm=json.loads((F/'manifest.json').read_text());weights=(W/'weights_group4x32.bin').read_bytes();bias=(W/'biases_int32x32.bin').read_bytes();factors=(F/'factors_job32.bin').read_bytes();unary=(C.parent/'unary_jobs.bin').read_bytes()
        packets=[];payload_bytes=0;weight_bytes=0
        for j,(w,f) in enumerate(zip(wm['jobs'],fm['jobs'])):
            groups,lanes=w['groups'],w['output_lanes'];wo,bo,fo=w['weight_start_byte'],w['bias_start_byte'],f['factor_start_byte'];lut=unary[j*256:(j+1)*256]
            actions=[(1,0,b''),(2,0,b''),(3,0,b'')]+[(4,i,weights[wo+i*128:wo+(i+1)*128]) for i in range(groups)]+[(5,0,bias[bo:bo+128])]+[(6,i,factors[fo+i*8:fo+(i+1)*8]) for i in range(lanes)]+[(7,i,lut[i:i+1]) for i in range(256)]+[(8,0,b''),(9,0,b''),(10,0,b'')]
            for tag,(op,index,data) in enumerate(actions,1):
                packets.append(op|(200<<4)|(tag<<36)|(index<<68)|(groups<<100)|(lanes<<111)|(int.from_bytes(data,'little')<<117));payload_bytes+=len(data)
                if op==4:weight_bytes+=len(data)
        check(len(packets)==p['commands']==74447 and payload_bytes==p['payload_bytes'],'Exact all173 C-bound request scope')
        (build/'parameter_packets.hex').write_text(''.join(f'{v:0286x}\n' for v in packets));(build/'parameter_defs.vh').write_text(f'`define PARAMETER_COMMANDS {len(packets)}\n')
        rtl=[HW/n for n in ('native_parameter_bridge_v1/z100_native_parameter_bridge.sv','int8_pair_packing_v3/z100_int8_pair_packing.sv','accum33_dsp_v2/z100_accum33_dsp.sv','window_mac20_v1/z100_window_mac.sv','requant_factor_v1/z100_requant_factor.sv','requant_factor32_v1/z100_requant_factor32.sv','unary32_v1/z100_unary32.sv','native_parameter_bridge_v1/tb_z100_native_parameter_bridge_v2.sv')]
        glbl=Path('C:/appload/2026.1/Vivado/data/verilog/src/glbl.v');rtl.append(glbl)
        sources=[Path(__file__),C,W/'manifest.json',F/'manifest.json',W/'weights_group4x32.bin',W/'biases_int32x32.bin',F/'factors_job32.bin',C.parent/'unary_jobs.bin',*rtl]
        before={str(s.relative_to(ROOT)) if s.is_relative_to(ROOT) else 'external/'+s.as_posix().replace(':',''):sha(s) for s in sources};r['source_sha256_before']=before;report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode));check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual tool completion '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_native_parameter_bridge_v2','glbl','-s','parameter_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','parameter_sim','-runall']);markers=re.findall(r'^PARAMETER_BRIDGE_PASS (.+)$',logs,re.M);check(len(markers)==1,'Complete real configuration proof');sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(sim['jobs']==173 and sim['commands']==74447 and sim['weight_bytes']==weight_bytes and sim['bias_values']==5536 and sim['factors']==5419 and sim['unary_replica_bytes']==173*256*16 and sim['held_response_cycles']==74447*2 and sim['protocol_rejects']==5 and sim['child_error_rejects']==1 and sim['captured_cancel']==1 and sim['child_stall_cycles']>100,'Actual all parameter configuration and guards')
        r.update(status='PASS_PRIVATE_PARAMETER_BRIDGE_ALL173_REAL_MAC_FACTOR_UNARY_CONFIG_MEMORIES_BACKPRESSURE_CANCEL_XSIM_ONLY',simulation=sim,
            scope='Real native weight RAM/bias32, exact-factor32 registers and all16 unary replicas configured/read-probed for all173 current jobs. MAC SITES1 reduces idle arithmetic only, no pixel compute. Bridge sequence/identity, stored responses, held child handshakes,3 malformed commands and captured-begin cancel tested. No AXI parameter mover, host MMIO bridge, full20-site integration, OOC/timing or board FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    def resolve(n):
        s=Path(n);return Path(s.parts[1]+':/',*s.parts[2:]) if s.parts[0]=='external' else ROOT/s
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(resolve(n)) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(s.relative_to(ROOT)):sha(s) for folder in (out,build) for s in folder.rglob('*') if s.is_file() and s!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
