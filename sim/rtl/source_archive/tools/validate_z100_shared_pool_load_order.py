"""Native Conv -> canonical-loaded Pool -> native Conv on one mirrored cache."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026'
PROOF=ROOT/'validation/board_z100/native_row20_shared_switch/20261024T135257.810595Z/result.json'
LOAD_PROOF=ROOT/'validation/board_z100/native_view_cache_load_v1/20261024T143613.999445Z/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
REPLACEMENTS={
 'z100_feature_banks_addressed.sv':HW/'feature_banks_load_order_v1/z100_feature_banks_load_order.sv',
 'z100_feature_banks_4read.sv':HW/'feature_banks_4read_load_order_v1/z100_feature_banks_4read_load_order.sv',
 'z100_feature_window20_pool5.sv':HW/'feature_window20_load_order_v1/z100_feature_window20_load_order.sv',
 'z100_native_row20_shared_pool.sv':HW/'shared_window_pool_load_order_v1/z100_native_row20_shared_pool_load_order.sv'}
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_shared_pool_load_order'/stamp;build=ROOT/'build'/('sload_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True);report=out/'result.json'
    sources=[Path(__file__),PROOF,LOAD_PROOF,*REPLACEMENTS.values()];before={}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False,production_integrated=False)
    try:
        p=read(PROOF);load=read(LOAD_PROOF)
        check(p['status']=='PASS_QUALITY200_SHARED_CACHE_CONV_POOL_CONV_NUMERIC_XSIM_ONLY','Original Conv/Pool/Conv proof')
        check(load['status']=='PASS_PRIVATE_REAL_AXI_CACHED_GATHER_CANONICAL_FEATURE_LOAD_READBACK_BOTH_ORDERS_XSIM_OOC','Actual cached gather consumer RAM seam')
        for proof in (p,load):
            check(proof['source_sha256_before']==proof['source_sha256_after'],'Stable prerequisite source')
            for n,h in {**proof['source_sha256_after'],**proof['artifact_sha256']}.items():check(sha(resolve(n))==h,'Prerequisite source/artifact drift '+n)
        original_files=[resolve(n) for n in p['commands'][0]['args'][2:]]
        original_tb=next(f for f in original_files if f.name=='tb_z100_native_row20_shared_switch.sv')
        rtl=[REPLACEMENTS.get(f.name,f) for f in original_files if f!=original_tb]
        check(len(rtl)==16 and sum(f.suffix=='.sv' for f in rtl)==15,'Original15RTL plus frozen vendor glbl')
        sources += [original_tb,*rtl]
        for name in p['artifact_sha256']:
            f=ROOT/name
            if name.startswith('build/') and f.suffix=='.hex':sources.append(f);shutil.copy2(f,build/f.name)
        before={str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f):sha(f) for f in sources}
        pool=[int(x,16) for x in (build/'pool_input.hex').read_text().split()]
        addresses=[int(x,16) for x in (build/'pool_addresses.hex').read_text().split()]
        check(len(pool)==len(addresses)==1280 and sorted(addresses)==list(range(1280)),'Exact1280word checked pool source')
        canonical=[0]*1280
        for a,v in zip(addresses,pool):canonical[a]=v
        (build/'pool_input_canonical.hex').write_text(''.join(f'{v:0128x}\n' for v in canonical))
        text=original_tb.read_text()
        def edit(a,b):
            nonlocal text
            check(text.count(a)==1,'Bounded shared load-order TB adapter '+a[:80]);text=text.replace(a,b)
        edit('module tb_z100_native_row20_shared_switch;','module tb_z100_shared_pool_load_order;')
        edit('reg score_reset=0;','reg score_reset=0;reg feature_cfg_canonical_order=0;')
        edit('z100_native_row20_shared_pool #(','z100_native_row20_shared_pool_load_order #(')
        edit('feature_cfg_epoch = EPOCH; feature_cfg_word_epoch = EPOCH;', 'feature_cfg_canonical_order=0;feature_cfg_epoch = EPOCH; feature_cfg_word_epoch = EPOCH;')
        edit('$readmemh("pool_input.hex",pool_input_words);','$readmemh("pool_input_canonical.hex",pool_input_words);')
        edit('feature_cfg_epoch=EPOCH+1;feature_cfg_channels=128;', 'feature_cfg_canonical_order=1;feature_cfg_epoch=EPOCH+1;feature_cfg_channels=128;')
        edit('for(k=0;k<1280;k=k+1)begin', '''if(!dut.feature_window.store.copy_a.canonical_q||!dut.feature_window.store.copy_b.canonical_q)$fatal(1,"mirrored canonical admission not latched");
        feature_cfg_canonical_order=0;
        for(k=0;k<1280;k=k+1)begin''')
        edit('feature_cfg_word_address=pool_addresses[k];','feature_cfg_word_address=k;')
        edit('SHARED_COMPUTE_POOL_SWITCH_PASS','SHARED_DUAL_LOAD_ORDER_COMPUTE_POOL_SWITCH_PASS')
        tb=build/'tb_z100_shared_pool_load_order.sv';tb.write_text(text)
        r['fixture']=dict(source_package_sha256=load['fixture']['source_package_sha256'],native_conv_runs=32,canonical_pool_source_words=1280,
            pool_source_reorder='Host reorders the closed source fixture by its explicit canonical bank addresses; pool output golden/native addresses unchanged.',
            no_reset_or_parameter_reload_between_modes=True)
        report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual tool diagnostic '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_shared_pool_load_order','glbl','-s','sharedload_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','sharedload_sim','-runall'])
        matches=re.findall(r'^SHARED_DUAL_LOAD_ORDER_COMPUTE_POOL_SWITCH_PASS (.+)$',text,re.M);check(len(matches)==1,'Complete shared two-mode marker')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',matches[0])}
        check(all(sim[k]==v for k,v in dict(conv_runs=32,conv_raw_lanes=20480,conv_words=160,pool_words=1280,exclusion_probes=8,parameter_reloads_after_pool=0,DUT_reset_between_modes=0).items()) and sim['pool_stalls']>0,'Actual dual-mode compute/ownership coverage')
        r.update(status='PASS_PRIVATE_SHARED_NATIVE_CONV_CANONICAL_POOL_NATIVE_CONV_XSIM_ONLY',simulation=sim,
            scope='Both copies of the existing four-read source store support checked canonical and native load modes. Actual compute path switches without reset/reloading parameters. Fullrow OOC/resource/route, actual gather-to-four-read cycle coupling, large-tensor tile/halo scheduling, fullgraph/HP and physical FPS remain unaccepted.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(resolve(n)) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
