"""Replay independently proved view bytes with four interleaved resident LUTs."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
OWN=ROOT/'deployment/hardware/z100_2026/native_view_context4_v1'
PROOF=ROOT/'validation/board_z100/native_view_word_v1/20261024T135528.864553Z/result.json'
MANIFEST=ROOT/'deployment/build/z100_quality200_virtual_views/20261024T134242.002345Z/views_manifest.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_view_context4_v1'/stamp;build=ROOT/'build'/('vctx_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True)
    rtl,tb=OWN/'z100_native_view_context4.sv',OWN/'tb_z100_native_view_context4.sv'
    sources=[Path(__file__),rtl,tb,PROOF,MANIFEST];before={}
    r=dict(status='RUNNING',board_access=False,full_pipeline_30fps_accepted=False,commands=[],process_environment_overrides={'XILINX_LOCAL_USER_DATA':'no'})
    report=out/'result.json'
    try:
        p=read(PROOF);check(p['status']=='PASS_PRIVATE_EXACT34_VIRTUAL_TENSORS_512BIT_VIEW_WORD_XSIM_OOC','Accepted exact prior payload fixture')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Prior proof source/artifact drift '+n)
        def artifact(name):
            paths=[ROOT/n for n in p['artifact_sha256'] if (ROOT/n).name==name]
            check(len(paths)==1,'Unique prior fixture '+name);return paths[0]
        vpath,cpath=artifact('vectors.hex'),artifact('counts.hex');tables=MANIFEST.parent/'composed_unary256.bin'
        sources += [vpath,cpath,tables];before={str(f.relative_to(ROOT)):sha(f) for f in sources}
        counts=[int(x,16) for x in cpath.read_text().split()];check(len(counts)==36,'All36 original LUTs')
        vectors=[int(x,16) for x in vpath.read_text().split()];check(len(vectors)==sum(counts)==203408,'Unchanged exact payload count')
        groups=[];cursor=0
        for count in counts:groups.append(vectors[cursor:cursor+count]);cursor+=count
        palette_counts=[]
        with (build/'vectors.hex').open('w') as f:
            for start in range(0,36,4):
                group=groups[start:start+4];n=0
                for i in range(max(map(len,group))):
                    for context,items in enumerate(group):
                        if i<len(items):f.write(f'{items[i]|(context<<1039):0261x}\n');n+=1
                palette_counts.append(n)
        raw=tables.read_bytes();check(len(raw)==9216,'All composed LUT bytes')
        (build/'tables.hex').write_text(''.join(f'{x:02x}\n' for x in raw))
        (build/'counts.hex').write_text(''.join(f'{n:08x}\n' for n in palette_counts))
        (build/'fixture_defs.vh').write_text('`define PALETTES 9\n`define WORDS 203408\n')
        node_palettes=[]
        for node in read(MANIFEST)['virtual_nodes']:
            ids=sorted({s['mapping']['lut_id'] for s in node['segments']})
            check(1<=len(ids)<=4,'Current virtual node fits resident contexts')
            node_palettes.append(dict(node=node['node'],context_to_lut=ids))
        check(len(node_palettes)==34,'Every current virtual node bound')
        (out/'node_palettes.json').write_text(json.dumps(node_palettes,indent=2)+'\n')
        r['fixture']=dict(prior_exact_vectors=203408,palettes=9,node_palettes=node_palettes,
            actual_virtual_words=p['fixture']['actual_virtual_words'],actual_group4_descriptors=p['fixture']['actual_group4_descriptors'],
            source_package_sha256=p['fixture']['source_package_sha256'],interleaved_contexts=True)
        for f in (rtl,tb,Path(__file__)):shutil.copy2(f,out/f.name)
        report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict vendor diagnostic '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',rtl,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_view_context4','-s','viewcontext_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','viewcontext_sim','-runall'])
        markers=re.findall(r'^NATIVE_VIEW_CONTEXT4_PASS (.+)$',text,re.M);check(len(markers)==1,'Complete resident context marker')
        observed={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(all(observed.get(k)==v for k,v in dict(palettes=9,vectors=203408,output_bytes=13018112,cfg_beats=9216,errors=15,aborts=2).items()) and observed['stalls']>0 and observed['max_ii1']>=20,'Full byte/stall/error coverage')
        r['simulation']=observed
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+rtl.as_posix()+'}\nsynth_design -top z100_native_view_context4 -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nset fh [open {'+(out/'primitive_counts.txt').as_posix()+'} w]\nforeach pattern {RAMB18E1 RAMB36E1 DSP48E1 LDCE LDPE} {puts $fh "$pattern [llength [get_cells -hier -filter REF_NAME==$pattern]]"}\nputs $fh "BLACKBOX [llength [get_cells -hier -filter IS_BLACKBOX==1]]"\nclose $fh\nwrite_checkpoint -force {'+(build/'viewcontext.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        util=(out/'utilization.rpt').read_text()
        def metric(n):return int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        primitives={k:int(v) for k,v in re.findall(r'(\w+) (\d+)',(out/'primitive_counts.txt').read_text())}
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),BRAM36eq=primitives['RAMB36E1']+primitives['RAMB18E1']/2,**primitives)
        check(resources['BRAM36eq']==16 and primitives['DSP48E1']==primitives['LDCE']==primitives['LDPE']==primitives['BLACKBOX']==0,'Actual32 dual-port RAM18 copies, no DSP/latches/blackboxes')
        r.update(status='PASS_PRIVATE_EXACT34_VIEWS_FOUR_RESIDENT_CONTEXTS_XSIM_16BRAM_OOC',resources=resources,
            scope='All prior exact current200 payload vectors with context switching under backpressure; one virtual-node palette at a time. Automatic DDR gather/load assembly, complete graph/platform timing and board FPS remain unaccepted.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={str(f.relative_to(ROOT)):sha(f) for f in sources} if before else {}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
