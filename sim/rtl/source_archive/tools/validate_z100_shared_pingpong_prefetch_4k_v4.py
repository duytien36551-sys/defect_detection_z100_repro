"""Actual Conv(A) + AXI prefetch(B), Pool(B), then retained Conv(A)."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/native_row20_shared_switch/20261024T135257.810595Z/result.json'
BURST=ROOT/'validation/board_z100/materialized_load_review/20261024T153556.171212Z/result.json'
REPLACEMENTS={
 'z100_feature_banks_addressed.sv':HW/'feature_banks_load_order_4k_v4/z100_feature_banks_load_order_4k_v4.sv',
 'z100_feature_banks_4read.sv':HW/'feature_banks_4read_load_order_4k_v4/z100_feature_banks_4read_load_order_4k_v4.sv',
 'z100_feature_window20_pool5.sv':HW/'feature_window20_load_order_4k_v4/z100_feature_window20_load_order_4k_v4.sv',
 'z100_native_row20_shared_pool.sv':HW/'shared_window_pool_pingpong_4k_v4/z100_native_row20_shared_pool_pingpong_4k_v4.sv'}
EXTRA=[HW/'feature_window20_pingpong_4k_v4/z100_feature_window20_pingpong_4k_v4.sv',HW/'native_materialized_load_v1/z100_native_materialized_load_control.sv',HW/'native_axi64_reader_v1/z100_native_axi64_reader.sv',HW/'native_stream_order_v1/z100_native_stream_order.sv']
SUPPORT=HW/'shared_window_pool_pingpong_v1/prefetch_support.vh'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/shared_pingpong_prefetch_4k_v4'/stamp;build=ROOT/'build'/('ppf_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True);report=out/'result.json';sources=[Path(__file__),PROOF,BURST,SUPPORT,*REPLACEMENTS.values(),*EXTRA];before={}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False,production_integrated=False)
    try:
        p=read(PROOF);review=read(BURST)
        check(p['status']=='PASS_QUALITY200_SHARED_CACHE_CONV_POOL_CONV_NUMERIC_XSIM_ONLY' and review['status'].startswith('ROOT_ACCEPT_CURRENT20042'),'Closed shared compute and burst loader prerequisites')
        for proof in (p,review):
            if 'source_sha256_before' in proof:check(proof['source_sha256_before']==proof['source_sha256_after'],'Stable prerequisite sources')
            for field in ('source_sha256_after','source_sha256','artifact_sha256'):
                for n,h in proof.get(field,{}).items():check(sha(resolve(n))==h,'Source/artifact prerequisite drift '+n)
            for binding in proof.get('report_bindings',{}).values():check(sha(ROOT/binding['path'])==binding['sha256'],'Closed report binding')
        oldfiles=[resolve(n) for n in p['commands'][0]['args'][2:]];oldtb=next(f for f in oldfiles if f.name=='tb_z100_native_row20_shared_switch.sv')
        rtl=[REPLACEMENTS.get(f.name,f) for f in oldfiles if f!=oldtb]+EXTRA
        check(len(rtl)==20 and sum(f.suffix=='.sv' for f in rtl)==19,'Exact19RTL plus frozen glbl closure')
        sources += [oldtb,*rtl]
        for n in p['artifact_sha256']:
            f=ROOT/n
            if n.startswith('build/') and f.suffix=='.hex':sources.append(f);shutil.copy2(f,build/f.name)
        sources=list(dict.fromkeys(sources));before={str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f):sha(f) for f in sources}
        shutil.copy2(SUPPORT,build/SUPPORT.name)
        text=oldtb.read_text()
        def edit(a,b):
            nonlocal text
            check(text.count(a)==1,'Bounded prefetch TB integration '+a[:80]);text=text.replace(a,b)
        edit('module tb_z100_native_row20_shared_switch;','module tb_z100_shared_pingpong_prefetch;')
        edit('z100_native_row20_shared_pool #(', '`include "prefetch_support.vh"\n    z100_native_row20_shared_pool_pingpong_4k_v4 #(')
        edit('.SITE_FIFO_DEPTH(4)) dut (.*);', '''.SITE_FIFO_DEPTH(4)) dut (
        .cancel(cancel||pf_semantic_cancel),.feature_cfg_canonical_order(1'b0),.feature_load_bank(pf_active?pf_bank_pin:old_load_bank),.compute_source_bank(compute_source_bank),
        .feature_cfg_begin(pf_active?pf_cb:feature_cfg_begin),.feature_cfg_epoch(pf_active?pf_epoch:feature_cfg_epoch),.feature_cfg_channels(pf_active?pf_channels:feature_cfg_channels),
        .feature_cfg_height(pf_active?pf_height:feature_cfg_height),.feature_cfg_width(pf_active?pf_width:feature_cfg_width),
        .feature_cfg_word_valid(pf_active?(pf_v&&pf_sink_allow):feature_cfg_word_valid),.feature_cfg_word_epoch(pf_active?pf_ep:feature_cfg_word_epoch),
        .feature_cfg_word_address(pf_active?pf_word_address:feature_cfg_word_address),.feature_cfg_word_last(pf_active?pf_last:feature_cfg_word_last),
        .feature_cfg_data(pf_active?pf_data:feature_cfg_data),.feature_cfg_commit(pf_active?pf_commit:feature_cfg_commit),.*);''')
        begin=text.index('        @(negedge clk);feature_cfg_epoch=EPOCH+1;',text.index('task shared_pool_pass'))
        end=text.index('        pool_job_valid=1;',begin)
        text=text[:begin]+'''        wait(pf_completed);@(negedge clk);old_load_bank=1;compute_source_bank=1;
        if(!feature_store_valid||feature_active_epoch!=EPOCH+1)$fatal(1,"prefetched B bank not ready for Pool");
'''+text[end:]
        edit('feature_cfg_channels=3;feature_cfg_height=2;feature_cfg_width=640;\n        load_features();', '''compute_source_bank=0;old_load_bank=0;feature_cfg_channels=3;feature_cfg_height=2;feature_cfg_width=640;
        #1;if(!feature_store_valid||feature_active_epoch!=EPOCH)$fatal(1,"retained A cache lost after B load/Pool");''')
        edit('SHARED_COMPUTE_POOL_SWITCH_PASS','SHARED_PINGPONG_PREFETCH_PASS')
        edit('        $finish;\n    end\n\n    initial begin', '''        if(feature_load_count!=0||pf_loaded!=1280||pf_overlap_loads==0||pf_simultaneous==0||!dut.feature_window.sv[0]||!dut.feature_window.sv[1])$fatal(1,"retained/prefetched source bank proof incomplete");
        $display("PINGPONG_AXI_PREFETCH_PASS words=%0d commands=%0d AXI_AR=%0d AXI_R=%0d overlap_cycles=%0d overlap_loads=%0d simultaneous_window_load=%0d latched_bank_probes=%0d active_bank_rejections=%0d retained_A_reloads=0",pf_loaded,pf_commands,pf_ars,pf_rbeats,pf_overlap_cycles,pf_overlap_loads,pf_simultaneous,pf_bank_latch_probes,pf_active_bank_probes);
        $finish;
    end

    initial begin''')
        tb=build/'tb_z100_shared_pingpong_prefetch.sv';tb.write_text(text)
        r['fixture']=dict(source_package_sha256=review['source_package_sha256'],source_A='Exact quality200 first-convolution row input,16runs/144windows',source_B='Exact quality200128x20x20 source for signed5x5 Pool',
            protocol='Load bank latched at begin; compute bank latched at Conv/Pool ownership; legal held AXI R/AR channels. No DUT reset or A feature/weight/factor/SiLU reload between modes.')
        report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):env[k]='1'
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual tool diagnostic '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_shared_pingpong_prefetch','glbl','-s','pingpong_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','pingpong_sim','-runall'])
        rows=re.findall(r'^SHARED_PINGPONG_PREFETCH_PASS (.+)$',logs,re.M);markers=re.findall(r'^PINGPONG_AXI_PREFETCH_PASS (.+)$',logs,re.M)
        check(len(rows)==len(markers)==1,'Complete shared compute and actual AXI prefetch markers')
        compute={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',rows[0])};pf={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(all(compute[k]==v for k,v in dict(conv_runs=32,conv_raw_lanes=20480,conv_words=160,pool_words=1280,exclusion_probes=8,parameter_reloads_after_pool=0,DUT_reset_between_modes=0).items()),'Both current Conv rows and Pool exact')
        check(all(pf[k]==v for k,v in dict(words=1280,commands=4,AXI_AR=640,AXI_R=10240,active_bank_rejections=4,retained_A_reloads=0).items()) and all(pf[k]>0 for k in ('overlap_cycles','overlap_loads','simultaneous_window_load','latched_bank_probes')),'Actual simultaneous load/compute, source-latch mutation and write protection coverage')
        r.update(status='PASS_PRIVATE_4K_V4_TWO_BANKS_CONV_AXI_PREFETCH_POOL_RETAINED_CONV_XSIM_ONLY',simulation=compute,prefetch=pf,
            scope='Real reader/codec/burst loader writes B while native20 computes A, then Pool reads B and Conv reuses retained A. No cached feature/weight/SiLU/factor reload for second Conv. Fullgraph lifetime/scheduler, platform HP integration, new whole-core resources/routing and physical FPS remain unaccepted.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(resolve(n)) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
