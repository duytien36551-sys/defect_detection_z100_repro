"""All actual34 virtual tensors through one-word exact RTL view transforms."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess,sys
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
OWN=ROOT/'deployment/hardware/z100_2026/native_view_word_v1'
PROOF=ROOT/'validation/board_z100/quality200_virtual_views/20261024T134242.002345Z/result.json'
BASE=ROOT/'deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline'
CANDIDATE=ROOT/'deployment/candidates/pin640/quant_candidates/epoch200_head_concat_20261024T103836.103919Z'
RGB=ROOT/'validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_rgb.bin'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok,msg):
    if not ok:raise ValueError(msg)

def main():
    import numpy as np
    import torch
    from deployment.candidates.pin640.quantize import run_integer,qround
    from z100_feature_window_layout import FeatureLayout
    torch.set_num_threads(1)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_view_word_v1'/stamp;build=ROOT/'build'/('vword_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl,tb=OWN/'z100_native_view_word.sv',OWN/'tb_z100_native_view_word.sv'
    sources=[Path(__file__),rtl,tb,PROOF,BASE/'model/graph.json',CANDIDATE/'quantization/quantization.json',CANDIDATE/'quantization/weights_int8.npz',RGB,
        ROOT/'deployment/candidates/pin640/quantize.py',ROOT/'deployment/candidates/pin640/export_graph.py',ROOT/'tools/z100_feature_window_layout.py']
    before={};r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False,process_environment_overrides={'XILINX_LOCAL_USER_DATA':'no'});report=out/'result.json'
    try:
        proof=read(PROOF);check(proof['status']=='PASS_HOST_EXACT34_VIEWS57_CONV_SILU_FUSIONS_CURRENT200_ONE_IMAGE','Actual current view compilation')
        for n,h in {**proof['source_sha256_after'],**proof['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Compiled proof drift '+n)
        manifest_path=ROOT/proof['manifest'];manifest=read(manifest_path);table_path=manifest_path.parent/'composed_unary256.bin'
        sources += [manifest_path,table_path];before={str(p.relative_to(ROOT)):sha(p) for p in sources}
        tables=np.frombuffer(table_path.read_bytes(),dtype=np.int8).reshape(-1,256);check(len(tables)==36,'All composed LUTs including identity')
        graph,q=read(BASE/'model/graph.json'),read(CANDIDATE/'quantization/quantization.json')
        image=torch.from_numpy(np.frombuffer(RGB.read_bytes(),dtype=np.uint8).reshape(640,640,3).transpose(2,0,1).copy()).float()[None]/255
        captured={-1:qround(image.double()/q['scales']['-1']).numpy()[0].copy()}
        with np.load(CANDIDATE/'quantization/weights_int8.npz') as z:params={k:torch.from_numpy(z[k].copy()) for k in z.files}
        with torch.inference_mode():run_integer(graph,params,q,image,observe=lambda i,y:captured.update({i:y.numpy()[0].copy()}))
        packed={}
        def canonical(n):
            if n not in packed:
                value=captured[n];layout=FeatureLayout(*value.shape,bank_depth=1<<20);packed[n]=(layout,layout.pack(value.tobytes()))
            return packed[n]
        events=[[] for _ in tables];generic=0;actual_words=0;group4_count=0;pernode=[];descriptor_rows=[]
        def emit(lut_id,source,expected,first,shift,channels,xcount):
            # Independent byte-permutation and composed LUT check before RTL.
            check(first+((xcount-1)>>shift)<16,'Single source word covers complete output')
            values=np.frombuffer(source,dtype=np.int8).reshape(4,16);gold=np.zeros((4,16),dtype=np.int8)
            for c in range(channels):gold[c,:xcount]=tables[lut_id,values[c,first+(np.arange(xcount)>>shift)].astype(np.int16)+128]
            check(gold.tobytes()==expected,'Host single-word transform equals captured integer tensor')
            events[lut_id].append((int.from_bytes(source,'little'),int.from_bytes(expected,'little'),first,shift,channels,xcount))
        for lut_id in range(len(tables)):
            for v in range(256):
                src=((np.arange(64,dtype=np.int16)*13+v)%256-128).astype(np.int8)
                emit(lut_id,src.tobytes(),tables[lut_id,src.astype(np.int16)+128].tobytes(),0,0,4,16);generic+=1
            for shift in range(3):
                for first in range(16):
                    xcount=min(16,(16-first)*(1<<shift))
                    for channels in range(1,5):
                        src=((np.arange(64,dtype=np.int16)*17+first*11+channels*3+shift)%256-128).astype(np.int8).reshape(4,16)
                        gold=np.zeros((4,16),dtype=np.int8)
                        for c in range(channels):gold[c,:xcount]=tables[lut_id,src[c,first+(np.arange(xcount)>>shift)].astype(np.int16)+128]
                        emit(lut_id,src.tobytes(),gold.tobytes(),first,shift,channels,xcount);generic+=1
        for view in manifest['virtual_nodes']:
            nid=view['node'];_,c,h,w=view['shape'];entries=[]
            for segment in view['segments']:
                for i in range(segment['channels']):entries.append(segment['mapping']|dict(source_channel=segment['mapping']['source_channel']+i))
            check(len(entries)==c,'Complete channel manifest')
            layout,expected=canonical(nid);checked=0
            for c4 in range(0,c,4):
                e=entries[c4];nc=min(4,c-c4)
                check(e['source_channel']%4==0,'Current source channel group4 alignment')
                for i,x in enumerate(entries[c4:c4+nc]):
                    check(x['source_node']==e['source_node'] and x['source_channel']==e['source_channel']+i and all(x[k]==e[k] for k in ('lut_id','nearest_divisor_h','nearest_divisor_w')),'Current one-source-group4 view admission')
                divisor=e['nearest_divisor_w'];check(divisor==e['nearest_divisor_h'] and divisor in (1,2,4),'Nearest power-of-two view')
                shift=divisor.bit_length()-1;source_layout,source_blob=canonical(e['source_node']);group4_count+=1
                descriptor_rows.append(dict(node=nid,output_channel_base=c4,valid_channels=nc,source_node=e['source_node'],source_channel_base=e['source_channel'],nearest_shift=shift,lut_id=e['lut_id']))
                for y in range(h):
                    for xword in range(layout.x_words):
                        sy=y>>shift;sx=(xword*16)>>shift
                        source_address=((e['source_channel']//4)*source_layout.height+sy)*source_layout.x_words+sx//16
                        dest_address=((c4//4)*h+y)*layout.x_words+xword
                        a=source_blob[source_address*64:(source_address+1)*64];b=expected[dest_address*64:(dest_address+1)*64]
                        check(len(a)==len(b)==64,'Complete source/output512bit words')
                        emit(e['lut_id'],a,b,sx%16,shift,nc,min(16,w-xword*16));actual_words+=1;checked+=1
            check(checked==layout.words,'Every actual virtual output word covered exactly once')
            pernode.append(dict(node=nid,words=checked,logical_bytes=c*h*w,CHW_sha256=hashlib.sha256(captured[nid].tobytes()).hexdigest()))
        with (build/'vectors.hex').open('w') as f,(build/'counts.hex').open('w') as cf:
            cursor=0
            for group in events:
                cf.write(f'{len(group):08x}\n')
                for src,dst,first,shift,channels,xcount in group:
                    last=int(cursor%19==18);value=src|(dst<<512)|(first<<1024)|(shift<<1028)|(channels<<1030)|(xcount<<1033)|(last<<1038)
                    f.write(f'{value:0260x}\n');cursor+=1
        with (build/'tables.hex').open('w') as f:
            for table in tables:
                for i in range(0,256,8):f.write(f'{int.from_bytes(table[i:i+8].tobytes(),"little"):016x}\n')
        (build/'fixture_defs.vh').write_text(f'`define TABLES {len(tables)}\n`define WORDS {cursor}\n')
        (out/'group4_descriptors.json').write_text(json.dumps(descriptor_rows,indent=2)+'\n')
        r['fixture']=dict(tables=36,total_vectors=cursor,generic_vectors=generic,actual_virtual_words=actual_words,actual_group4_descriptors=group4_count,
            per_node=pernode,source_package_sha256=proof['source_package_sha256'],
            scope='Every output512bit word of all34 actual virtual tensors on the fixed validation image; all256 input values per64lanes for every table plus nearest/tail edge cases.')
        for f in (rtl,tb,Path(__file__)):shutil.copy2(f,out/f.name)
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict vendor diagnostic '+label);return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',rtl,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_view_word','-s','viewword_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','viewword_sim','-runall'])
        markers=re.findall(r'^NATIVE_VIEW_WORD_PASS (.+)$',text,re.M);check(len(markers)==1,'Complete one-word view RTL marker')
        counts={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(all(counts.get(k)==v for k,v in dict(tables=36,vectors=cursor,output_bytes=cursor*64,cfg_beats=1152,errors=13,aborts=2).items()) and counts['stalls']>0 and counts['max_ii1']>=20,'Exact byte/tail/stall/error coverage')
        r['simulation']=counts
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+rtl.as_posix()+'}\nsynth_design -top z100_native_view_word -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'viewword.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        util=(out/'utilization.rpt').read_text()
        def metric(n):return int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=metric('DSPs'),BRAM=metric('Block RAM Tile'))
        check(resources['DSP']==resources['BRAM']==0 and resources['Slice_LUT']<15000,'Actual distributed table transform resource screen')
        r.update(status='PASS_PRIVATE_EXACT34_VIRTUAL_TENSORS_512BIT_VIEW_WORD_XSIM_OOC',resources=resources,
            scope='One512bit view payload transform,64 exact unary lookups, nearest in-word reuse and tails. Host supplies verified source words and descriptors; automatic source DDR gather/addressing, virtual load assembly, fullgraph platform/board/FPS remain unaccepted.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={str(f.relative_to(ROOT)):sha(f) for f in sources} if before else {}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))

if __name__=='__main__':raise SystemExit(main())
