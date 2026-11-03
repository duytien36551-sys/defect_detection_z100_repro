"""Actual AXI reader + autonomous gather + resident LUTs for all34 views."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from z100_native_stream_layout import NativeStreamLayout
OWN=ROOT/'deployment/hardware/z100_2026/native_view_gather_v1'
WORD_PROOF=ROOT/'validation/board_z100/native_view_word_v1/20261024T135528.864553Z/result.json'
CONTEXT_PROOF=ROOT/'validation/board_z100/native_view_context4_v1/20261024T141033.398278Z/result.json'
MANIFEST=ROOT/'deployment/build/z100_quality200_virtual_views/20261024T134242.002345Z/views_manifest.json'
GRAPH=ROOT/'deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline/model/graph.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin');BASE=0x10000000
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_view_gather_v1'/stamp;build=ROOT/'build'/('vg_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True)
    rtl=OWN/'z100_native_view_gather.sv';tb=OWN/'tb_z100_native_view_gather.sv'
    context=ROOT/'deployment/hardware/z100_2026/native_view_context4_v1/z100_native_view_context4.sv'
    reader=ROOT/'deployment/hardware/z100_2026/native_axi64_reader_v1/z100_native_axi64_reader.sv'
    sources=[Path(__file__),rtl,tb,context,reader,WORD_PROOF,CONTEXT_PROOF,MANIFEST,GRAPH,ROOT/'tools/z100_native_stream_layout.py',ROOT/'tools/z100_feature_window_layout.py']
    before={};r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False,process_environment_overrides={'XILINX_LOCAL_USER_DATA':'no'})
    report=out/'result.json'
    try:
        proof=read(WORD_PROOF);cp=read(CONTEXT_PROOF)
        check(proof['status']=='PASS_PRIVATE_EXACT34_VIRTUAL_TENSORS_512BIT_VIEW_WORD_XSIM_OOC' and cp['status']=='PASS_PRIVATE_EXACT34_VIEWS_FOUR_RESIDENT_CONTEXTS_XSIM_16BRAM_OOC','Both exact payload prerequisites')
        for p in (proof,cp):
            check(p['source_sha256_before']==p['source_sha256_after'],'Prerequisite source stability')
            for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Prior source/artifact drift '+n)
        def artifact(name):
            paths=[ROOT/n for n in proof['artifact_sha256'] if (ROOT/n).name==name];check(len(paths)==1,'Unique prior fixture '+name);return paths[0]
        vp,counts_path=artifact('vectors.hex'),artifact('counts.hex');table_path=MANIFEST.parent/'composed_unary256.bin'
        sources += [vp,counts_path,table_path];before={str(p.relative_to(ROOT)):sha(p) for p in sources}
        counts=[int(x,16) for x in counts_path.read_text().split()];values=[int(x,16) for x in vp.read_text().split()]
        groups=[];cursor=0
        for count in counts:groups.append(values[cursor:cursor+count]);cursor+=count
        # The saved independently checked fixture emits448 generic records per
        # LUT, then all actual node words in canonical channel4,row,xword order.
        heads=[448]*36;manifest=read(MANIFEST);nodes={n['id']:n for n in read(GRAPH)['nodes']}
        table=table_path.read_bytes();regions={};arena_words=0;source_assignments={};inverse={}
        def region(node):
            nonlocal arena_words
            if node not in regions:
                c,h,w=nodes[node]['shape'][1:];layout=NativeStreamLayout(c,h,w)
                arena_words=(arena_words+63)//64*64
                regions[node]=dict(start=arena_words,end=arena_words+layout.words,channels=c,height=h,width=w)
                inverse[node]={address:i for i,address in enumerate(layout.addresses())};arena_words+=layout.words
            return regions[node]
        descriptors=[];words=[];node_counts=[];bindings=[];raw_tables=bytearray()
        for ordinal,view in enumerate(manifest['virtual_nodes']):
            node=view['node'];_,c,h,w=view['shape'];xwords=(w+15)//16
            palette=sorted({s['mapping']['lut_id'] for s in view['segments']});check(len(palette)<=4,'Current palette fits4 contexts')
            for context_id in range(4):raw_tables+=table[(palette[context_id] if context_id<len(palette) else 0)*256:((palette[context_id] if context_id<len(palette) else 0)+1)*256]
            entries=[]
            for segment in view['segments']:
                entries += [segment['mapping']|dict(source_channel=segment['mapping']['source_channel']+i) for i in range(segment['channels'])]
            before_desc=len(descriptors)
            for c4 in range(0,c,4):
                e=entries[c4];nc=min(4,c-c4);div=e['nearest_divisor_w'];shift=div.bit_length()-1
                check(div==e['nearest_divisor_h'] and div in (1,2,4) and e['source_channel']%4==0,'Source group admission')
                for i,other in enumerate(entries[c4:c4+nc]):check(other==e|dict(source_channel=e['source_channel']+i),'Contiguous source channels, identical LUT/spatial view')
                sr=region(e['source_node']);source_xwords=(sr['width']+15)//16;source_group=e['source_channel']//4
                source_subgroups=min(8,(sr['channels']+3)//4-(source_group//8)*8)
                native_base=(source_group//8)*8*sr['height']*source_xwords+(source_group%8)
                source_address=BASE+(sr['start']+native_base)*64
                rowstride=source_xwords*source_subgroups*64;xstride=source_subgroups*64
                output_base=(c4//4)*h*xwords;ctx=palette.index(e['lut_id']);nwords=h*xwords
                descriptor=(source_address|((BASE+sr['start']*64)<<32)|((BASE+sr['end']*64)<<64)|(rowstride<<96)|(xstride<<128)|
                    (output_base<<160)|(h<<192)|(w<<202)|(nc<<212)|(shift<<215)|(ctx<<217)|((ordinal+1)<<219)|(nwords<<251)|(ordinal<<267))
                descriptors.append(descriptor)
                for y in range(h):
                    for xword in range(xwords):
                        event=groups[e['lut_id']][heads[e['lut_id']]];heads[e['lut_id']]+=1
                        source=event&((1<<512)-1);gold=(event>>512)&((1<<512)-1)
                        sy=y//div;sx=(xword*16)//div
                        canonical=(source_group*sr['height']+sy)*source_xwords+sx//16
                        independent_ordinal=inverse[e['source_node']][canonical]
                        calculated=source_address+(y>>shift)*rowstride+(xword>>shift)*xstride
                        expected_address=BASE+(sr['start']+independent_ordinal)*64
                        check(calculated==expected_address,'Stride traversal equals independent NativeStreamLayout enumeration')
                        check(((event>>1024)&15)==sx%16 and ((event>>1028)&3)==shift and ((event>>1030)&7)==nc and ((event>>1033)&31)==min(16,w-xword*16),'Prior fixture metadata identity')
                        memory_index=sr['start']+independent_ordinal
                        check(memory_index not in source_assignments or source_assignments[memory_index]==source,'Overlapping retained source bytes identical')
                        source_assignments[memory_index]=source
                        words.append(gold|(expected_address<<512)|((output_base+y*xwords+xword)<<544)|(int(y==h-1 and xword==xwords-1)<<576))
            node_counts.append(len(descriptors)-before_desc);bindings.append(dict(node=node,palette=palette,group4_descriptors=node_counts[-1]))
        check(heads==counts,'Every actual saved fixture word consumed exactly once')
        check(len(descriptors)==1253 and len(words)==187280,'All34 current virtual tensors')
        (build/'source.hex').write_text(''.join(f'{source_assignments.get(i,0):0128x}\n' for i in range(arena_words)))
        (build/'words.hex').write_text(''.join(f'{v:0145x}\n' for v in words))
        (build/'descriptors.hex').write_text(''.join(f'{v:069x}\n' for v in descriptors))
        (build/'tables.hex').write_text(''.join(f'{v:02x}\n' for v in raw_tables))
        (build/'counts.hex').write_text(''.join(f'{v:08x}\n' for v in node_counts))
        (build/'fixture_defs.vh').write_text(f'`define MEMWORDS {arena_words}\n`define WORDS {len(words)}\n`define DESCRIPTORS {len(descriptors)}\n')
        (out/'source_regions.json').write_text(json.dumps(regions,indent=2)+'\n');(out/'node_bindings.json').write_text(json.dumps(bindings,indent=2)+'\n')
        r['fixture']=dict(source_package_sha256=manifest['source_package_sha256'],nodes=34,descriptors=1253,words=187280,
            memory_arena_words=arena_words,initialized_source_words=len(source_assignments),output_valid_bytes=10802000,
            source_layout='z100-native-stream/1',sink_layout='canonical feature bank word address, channel4,row,xword',
            address_oracle='Independent NativeStreamLayout.addresses enumeration; byte oracle is closed actual34-node integer fixture')
        for f in (Path(__file__),rtl,tb,context,reader):shutil.copy2(f,out/f.name)
        report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):env[k]='1'
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict tool diagnostic '+label);return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',rtl,context,reader,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_view_gather','-s','viewgather_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','viewgather_sim','-runall'])
        markers=re.findall(r'^NATIVE_VIEW_GATHER_PASS (.+)$',text,re.M);check(len(markers)==1,'Complete actual gather marker')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(all(sim.get(k)==v for k,v in dict(nodes=34,descriptors=1253,words=187280,AXI_AR=187280,AXI_R=1498240,recoveries=14).items()) and sim['stalls']>0 and sim['drain_probes']>=30,'All payload/address/drain coverage')
        r['simulation']=sim
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+rtl.as_posix()+'} {'+context.as_posix()+'}\nsynth_design -top z100_native_view_gather -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nset f [open {'+(out/'primitives.txt').as_posix()+'} w]\nforeach kind {RAMB18E1 RAMB36E1 DSP48E1 LDCE LDPE} {puts $f "$kind [llength [get_cells -hier -filter REF_NAME==$kind]]"}\nputs $f "BLACKBOX [llength [get_cells -hier -filter IS_BLACKBOX==1]]"\nclose $f\nwrite_checkpoint -force {'+(build/'gather.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        primitives={k:int(v) for k,v in re.findall(r'(\w+) (\d+)',(out/'primitives.txt').read_text())};util=(out/'utilization.rpt').read_text()
        metric=lambda n:int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),BRAM36eq=primitives['RAMB36E1']+primitives['RAMB18E1']/2,**primitives)
        check(resources['BRAM36eq']==16 and primitives['DSP48E1']==primitives['LDCE']==primitives['LDPE']==primitives['BLACKBOX']==0,'Bounded actual gather resource screen')
        r.update(status='PASS_PRIVATE_ALL34_VIEWS_AUTONOMOUS_AXI_GATHER_1253_DESCRIPTORS_XSIM_16BRAM_OOC',resources=resources,
            scope='Real frozen AXI reader feeds source-addressed independent retained memory, gather, exact4-context transform and checked canonical bank-loader stream. No intermediate virtual writes. Per-word single-outstanding reads; physical DDR/coherency, consumer cache admission, tiled halo scheduling, fullgraph controller, routed platform and FPS remain unaccepted.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={str(f.relative_to(ROOT)):sha(f) for f in sources} if before else {}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
