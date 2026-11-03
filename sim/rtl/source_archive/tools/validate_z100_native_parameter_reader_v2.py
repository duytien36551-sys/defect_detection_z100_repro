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
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/native_parameter_reader_v2'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('npr_'+stamp[-14:]);build.mkdir(parents=True);report=out/'result.json';before={}
    r=dict(status='RUNNING',commands=[],board_access=False,production_integrated=False,physical_deployed=False,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(C.read_text());check(p['status'].startswith('PASS_HOST_C_ALL173'),'Closed real C parameter trace')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Current asset/loader binding '+n)
        wm=json.loads((W/'manifest.json').read_text());fm=json.loads((F/'manifest.json').read_text());weights=(W/'weights_group4x32.bin').read_bytes();bias=(W/'biases_int32x32.bin').read_bytes();factors=(F/'factors_job32.bin').read_bytes();unary=(C.parent/'unary_jobs.bin').read_bytes()
        base=0x20000000
        assets=weights+bias+factors+unary
        assert len(assets)%64==0
        bias_base=base+len(weights);factor_base=bias_base+len(bias);unary_base=factor_base+len(factors)
        jobs=[]
        for j,(w,f) in enumerate(zip(wm['jobs'],fm['jobs'])):
            assert all(w[k]==f[k] for k in ('node','output_channel_first','output_lanes','weight_start_byte','bias_start_byte'))
            jobs.append((base+w['weight_start_byte'])|((bias_base+w['bias_start_byte'])<<32)|((factor_base+f['factor_start_byte'])<<64)|((unary_base+j*256)<<96)|(w['groups']<<128)|(w['output_lanes']<<139))
        check(len(jobs)==173,'Complete current parameter jobs')
        (build/'parameter_memory.hex').write_text(''.join(f'{int.from_bytes(assets[i:i+8],"little"):016x}\n' for i in range(0,len(assets),8)))
        (build/'parameter_jobs.hex').write_text(''.join(f'{v:048x}\n' for v in jobs))
        (build/'parameter_reader_defs.vh').write_text(f'`define PARAMETER_MEMORY_BEATS {len(assets)//8}\n')
        rtl=[HW/n for n in ('native_parameter_bridge_v1/z100_native_parameter_bridge.sv','int8_pair_packing_v3/z100_int8_pair_packing.sv','accum33_dsp_v2/z100_accum33_dsp.sv','window_mac20_v1/z100_window_mac.sv','requant_factor_v1/z100_requant_factor.sv','requant_factor32_v1/z100_requant_factor32.sv','unary32_v1/z100_unary32.sv','native_parameter_reader_v1/z100_native_parameter_reader.sv','native_axi64_reader_v1/z100_native_axi64_reader.sv','native_parameter_reader_v1/tb_z100_native_parameter_reader_v2.sv')]
        glbl=Path('C:/appload/2026.1/Vivado/data/verilog/src/glbl.v');rtl.append(glbl)
        sources=[Path(__file__),C,W/'manifest.json',F/'manifest.json',W/'weights_group4x32.bin',W/'biases_int32x32.bin',F/'factors_job32.bin',C.parent/'unary_jobs.bin',*rtl]
        before={str(s.relative_to(ROOT)) if s.is_relative_to(ROOT) else 'external/'+s.as_posix().replace(':',''):sha(s) for s in sources};r['source_sha256_before']=before;report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode));check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual tool completion '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_native_parameter_reader_v2','glbl','-s','parameter_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','parameter_sim','-runall']);markers=re.findall(r'^PARAMETER_READER_PASS (.+)$',logs,re.M);check(len(markers)==1,'Complete real configuration proof');sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(sim['jobs']==173 and sim['configs']==74447 and sim['weight_bytes']==3011712 and sim['bias_values']==5536 and sim['factors']==5419 and sim['unary_replica_bytes']==708608 and sim['recoveries']==3 and sim['early_recovery_blocks']>=16 and sim['AXI_AR']>1000 and sim['AXI_R']>10000,'Actual all173 DDR configuration and physical drain/recovery coverage')
        r.update(status='PASS_PRIVATE_DDR_PARAMETER_READER_ALL173_REAL_AXI_BRIDGE_MAC_FACTOR_UNARY_CANCEL_DRAIN_XSIM_ONLY',simulation=sim,
            source_package_sha256=wm['source_package_sha256'],memory_fixture_bytes=len(assets),
            scope='Actual frozen AXI64 reader -> new parameter mover -> strict config bridge -> MAC SITES1 config RAM/bias32, factor32 and unary16 replicas. All173 current jobs, exact DDR-address independent payload oracle and physical config probes; held AR/withheld R abort, physical RRESP fault and3 recoveries retaining IO until drain. No MAC output computation, full20site platform, shared HP arbitration/cache coherency, asset physical reservation or board FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    def resolve(n):
        s=Path(n);return Path(s.parts[1]+':/',*s.parts[2:]) if s.parts[0]=='external' else ROOT/s
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(resolve(n)) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(s.relative_to(ROOT)):sha(s) for folder in (out,build) for s in folder.rglob('*') if s.is_file() and s!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
