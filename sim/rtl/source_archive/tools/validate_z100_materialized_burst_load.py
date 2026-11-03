"""Real AXI bursts + codec + feature RAM for42 materialized-input Conv layers."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/quality200_halo_load_fixture/20261024T145530.965329Z/result.json'
ACTUAL=ROOT/'validation/board_z100/quality200_halo_load_xsim/20261024T145923.181549Z/result.json'
VIEWS=ROOT/'deployment/build/z100_quality200_virtual_views/20261024T134242.002345Z/views_manifest.json';BASE=0x10000000
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/materialized_burst_load_v1'/stamp;build=ROOT/'build'/('mload_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True);report=out/'result.json'
    rtl=HW/'native_materialized_load_v1/z100_native_materialized_load_control.sv';tb=HW/'native_materialized_load_v1/tb_z100_native_materialized_load.sv'
    reader=HW/'native_axi64_reader_v1/z100_native_axi64_reader.sv';codec=HW/'native_stream_order_v1/z100_native_stream_order.sv';bank=HW/'feature_banks_load_order_v1/z100_feature_banks_load_order.sv'
    sources=[Path(__file__),rtl,tb,reader,codec,bank,PROOF,ACTUAL,VIEWS];before={}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    try:
        proof=read(PROOF);actual=read(ACTUAL)
        check(proof['status'].startswith('PASS_HOST_CURRENT200_ALL63') and actual['status'].startswith('PASS_PRIVATE_ALL63_CONV_HALO'),'Closed current integer-capture and real halo inputs')
        for p in (proof,actual):
            check(p['source_sha256_before']==p['source_sha256_after'],'Prerequisite source stability')
            for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Prior source/artifact drift '+n)
        prepared=ROOT/proof['build'];tile_path=PROOF.parent/'halo_tiles.json';region_path=PROOF.parent/'source_regions.json'
        sources += [tile_path,region_path,prepared/'source.hex',prepared/'words.hex'];before={str(f.relative_to(ROOT)):sha(f) for f in sources}
        virtual={v['node'] for v in read(VIEWS)['virtual_nodes']};regions=read(region_path);all_words=[int(x,16) for x in (prepared/'words.hex').read_text().split()]
        selected=[t for t in read(tile_path) if t['input_node'] not in virtual];check(len(selected)==128 and len({t['conv'] for t in selected})==42,'Exactly42 materialized-input operators')
        cases=[];gold=[];ar=[];commands=[]
        for tile in selected:
            sr=regions[str(tile['input_node'])];c=tile['input_channels'];h=tile['input_rows'];w=tile['input_width'];full_h=sr['height'];first_y=tile['input_y'];count=tile['words']
            check(sr['channels']==c and sr['width']==w and first_y+h<=full_h,'Committed source full shape')
            address=BASE+sr['start']*64;offset=len(gold)
            cases.append(address|(c<<32)|(full_h<<43)|(w<<53)|(first_y<<63)|(h<<73)|(count<<83)|(offset<<97))
            gold += [v&((1<<512)-1) for v in all_words[tile['word_offset']:tile['word_offset']+count]]
            xwords=(w+15)//16
            # Independently enumerate native source layout group32,row,xword,
            # subgroup4. The selected row range within each group is contiguous.
            group_base=sr['start']
            for c32 in range(0,c,32):
                subgroups=(min(32,c-c32)+3)//4
                a=BASE+(group_base+first_y*xwords*subgroups)*64;n=h*xwords*subgroups
                commands.append(dict(conv=tile['conv'],source_address=a,words=n,tile_output_word_base=sum(x['words'] for x in commands[-((c32+31)//32):]) if c32 else 0))
                remaining=n*8
                while remaining:
                    beats=min(16,remaining,(4096-(a&4095))//8);check(beats>0,'Positive page-bounded burst')
                    ar.append(a|((beats-1)<<32));a+=beats*8;remaining-=beats
                group_base+=subgroups*full_h*xwords
        check(len(commands)==240 and len(gold)==211496,'Exact materialized halo word/command scope')
        shutil.copy2(prepared/'source.hex',build/'source.hex')
        for name,values,width in [('gold.hex',gold,128),('cases.hex',cases,33),('expected_ar.hex',ar,9)]:
            (build/name).write_text(''.join(f'{v:0{width}x}\n' for v in values))
        memory_words=sum(1 for _ in (build/'source.hex').open())
        (build/'fixture_defs.vh').write_text(f'`define MEMWORDS {memory_words}\n`define TILES {len(selected)}\n`define WORDS {len(gold)}\n`define COMMANDS {len(commands)}\n`define ARS {len(ar)}\n')
        (out/'tile_sources.json').write_text(json.dumps(selected,indent=2)+'\n');(out/'reader_commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        r['fixture']=dict(source_package_sha256=proof['source_package_sha256'],conv_layers=42,tiles=128,words=211496,reader_commands=240,expected_AXI_AR=len(ar),expected_AXI_R=211496*8,
            scope='Only real materialized inputs;21 virtual-input operators still require exact gather/LUT. Golden is preserved independently captured integer-parent halo crop, no new model predictions.')
        report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):env[k]='1'
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict actual tool diagnostic '+label);return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',rtl,reader,codec,bank,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_materialized_load','-s','materialized_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','materialized_sim','-runall']);matches=re.findall(r'^MATERIALIZED_LOAD_PASS (.+)$',text,re.M)
        check(len(matches)==1,'Complete native-burst halo load marker');sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',matches[0])}
        check(all(sim[k]==v for k,v in dict(tiles=128,words=211496,readback=211496,commands=240,AXI_AR=len(ar),AXI_R=211496*8,recoveries=15).items()) and sim['drain_probes']>=30 and sim['stalls']>0,'All source bursts, actual cache bytes and fault/drain coverage')
        r['simulation']=sim
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+rtl.as_posix()+'}\nsynth_design -top z100_native_materialized_load_control -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nset f [open {'+(out/'primitives.txt').as_posix()+'} w]\nforeach kind {RAMB18E1 RAMB36E1 DSP48E1 LDCE LDPE} {puts $f "$kind [llength [get_cells -hier -filter REF_NAME==$kind]]"}\nputs $f "BLACKBOX [llength [get_cells -hier -filter IS_BLACKBOX==1]]"\nclose $f\nwrite_checkpoint -force {'+(build/'control.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        primitives={k:int(v) for k,v in re.findall(r'(\w+) (\d+)',(out/'primitives.txt').read_text())};util=(out/'utilization.rpt').read_text()
        metric=lambda n:int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        check(all(primitives[k]==0 for k in primitives),'Control-only no DSP/RAM/latch/blackbox')
        r.update(status='PASS_PRIVATE42_CONV_MATERIALIZED_NATIVE_BURST_HALO_LOAD_REAL_AXI_RAM_XSIM_CONTROL_OOC',control_resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),**primitives),
            scope='Actual page-bounded frozen AXI reader, native codec and checked source RAM;240 group32 reader commands load128 actual integer halo tiles and all211496 words read back. Control-only OOC excludes reader/codec/RAM. No fullgraph ownership, MAC execution, overlap, routed frequency, physical DDR or FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={str(f.relative_to(ROOT)):sha(f) for f in sources} if before else {}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
