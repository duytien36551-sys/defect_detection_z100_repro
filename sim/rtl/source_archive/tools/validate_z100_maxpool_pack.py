"""Actual200 MaxPool80 -> channel collector -> existing native FeatureLayout packer."""
from pathlib import Path
from datetime import datetime,timezone
import os,sys,json,hashlib,subprocess,re,shutil
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from z100_feature_window_layout import FeatureLayout
PIPE=ROOT/'deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline'
HW=ROOT/'deployment/hardware/z100_2026'
OWN=HW/'maxpool_collect32_v1'
RGB=ROOT/'validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_rgb.bin'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    import numpy as np
    import torch
    from deployment.candidates.pin640.quantize import run_integer
    torch.set_num_threads(1)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/maxpool_pack_v1'/stamp;build=ROOT/'build'/('mppk_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl=[HW/'maxpool_vector_v1/z100_maxpool_vector.sv',OWN/'z100_maxpool_collect32.sv',HW/'native_row20_v1/z100_native_output_packer.sv']
    tb=OWN/'tb_z100_maxpool_pack.sv'
    sources=[Path(__file__),*rtl,tb,PIPE/'model/graph.json',PIPE/'quantization/quantization.json',PIPE/'quantization/weights_int8.npz',RGB,
             ROOT/'deployment/candidates/pin640/quantize.py',ROOT/'deployment/candidates/pin640/export_graph.py',ROOT/'tools/z100_feature_window_layout.py']
    before={str(p.relative_to(ROOT)):sha(p) for p in sources};r=dict(status='RUNNING',commands=[],board_access=False,
        fullgraph_accepted=False,routed_clock_accepted=False,full_pipeline_30fps_accepted=False)
    try:
        for p in [*rtl,tb,Path(__file__)]:shutil.copy2(p,out/p.name)
        graph=json.loads((PIPE/'model/graph.json').read_text());q=json.loads((PIPE/'quantization/quantization.json').read_text())
        check(graph['checkpoint_sha256']==q['model_sha256']=='2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6','Selected200')
        check(sha(RGB)=='f82d6ce4ad170ec4859a49f405d6a0b7ca2cdbd93b5e57142a556a92ccd750e0','Fixed val RGB')
        check(len({q['scales'][str(i)] for i in (69,70,71,72)})==1,'Exact current SPPF scale identity')
        with np.load(PIPE/'quantization/weights_int8.npz') as z:params={k:torch.from_numpy(z[k].copy()) for k in z.files}
        image=torch.from_numpy(np.frombuffer(RGB.read_bytes(),dtype=np.uint8).reshape(640,640,3).transpose(2,0,1).copy()).float()[None]/255
        captured={}
        run_integer(graph,params,q,image,observe=lambda i,y:captured.update({i:y.numpy()[0].copy()}) if i in (69,70,71,72) else None)
        cases=[(f'node{i}',captured[i],captured[i+1]) for i in (69,70,71)]
        cases += [('negative_tail9',-(np.arange(180).reshape(9,1,20)%100+1).astype(np.int8),None),
                  ('channel_tail33',((np.arange(1320).reshape(33,2,20)*17+27)%255-127).astype(np.int8),None)]
        nv=nb=nw=validbytes=0;summary=[]
        with (build/'taps.hex').open('w') as tf,(build/'golden.hex').open('w') as gf,(build/'addresses.hex').open('w') as af,(build/'cases.hex').open('w') as cf:
            for name,a,graph_expected in cases:
                c,h,w=a.shape;check(w==20,'Width20 adapter');pad=np.pad(a.astype(np.int16),((0,0),(2,2),(2,2)),constant_values=-128)
                golden=np.stack([pad[:,ky:ky+h,kx:kx+w] for ky in range(5) for kx in range(5)]).max(axis=0).astype(np.int8)
                if graph_expected is not None:check(np.array_equal(golden,graph_expected),'Exact graph SPPF '+name)
                layout=FeatureLayout(c,h,w);packed=layout.pack(golden.tobytes());blocks=((c+31)//32)*h
                cf.write(f'{c|(h<<11)|(blocks<<21)|(layout.words<<37):032x}\n')
                start=nv
                for c32 in range(0,c,32):
                    nc=min(32,c-c32)
                    for y in range(h):
                        for sg in range((nc+3)//4):
                            for ky in range(-2,3):
                                for kx in range(-2,3):
                                    data=np.full(80,127,dtype=np.int8);mask=0
                                    for ch in range(4):
                                        for x in range(20):
                                            cc=c32+sg*4+ch;yy=y+ky;xx=x+kx;slot=ch*20+x
                                            if cc<c and 0<=yy<h and 0<=xx<20:
                                                data[slot]=a[cc,yy,xx];mask|=1<<slot
                                    tf.write(f'{mask:020x}{int.from_bytes(data.tobytes(),"little"):0160x}\n')
                            nv+=1
                        for xword in range(2):
                            for sg in range((nc+3)//4):
                                addr=(((c32//4+sg)*h+y)*2+xword)
                                gf.write(f'{int.from_bytes(packed[addr*64:(addr+1)*64],"little"):0128x}\n');af.write(f'{addr:04x}\n');nw+=1
                nb+=blocks;validbytes+=c*h*w
                summary.append(dict(source=name,shape=list(a.shape),vectors=nv-start,blocks=blocks,output_words=layout.words,
                                    input_sha256=hashlib.sha256(a.tobytes()).hexdigest(),expected_packed_sha256=hashlib.sha256(packed).hexdigest()))
        (build/'fixture_defs.vh').write_text(f'`define CASES {len(cases)}\n`define VECTORS {nv}\n`define TAPS {nv*25}\n`define WORDS {nw}\n`define BLOCKS {nb}\n`define VALID_BYTES {validbytes}\n')
        r['fixture']=dict(cases=summary,vectors=nv,taps=nv*25,words=nw,blocks=nb,valid_bytes=validbytes,
            order='group32,row,subgroup4 input vectors; group32,row,xword,subgroup4 output addressed words',
            oracle='Direct signed CHW5x5 maxima and independent FeatureLayout.pack, all3 actual200 SPPF tensors and negative/channel tails')
        def run(label,args):
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(ERROR:|Fatal:)',p.stdout,re.M),'Vendor diagnostic '+label)
            return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_maxpool_pack','-s','poolpack_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','poolpack_sim','-runall'])
        markers=re.findall(r'^MAXPOOL_PACK_PASS cases=(\d+) vectors=(\d+) taps=(\d+) post_beats=(\d+) packed_words=(\d+) valid_bytes=(\d+) pack_stalls=(\d+) post_stalls=(\d+) done=(\d+)$',text,re.M)
        check(len(markers)==1,'One complete coupled PASS marker');values=list(map(int,markers[0]));r['simulation']=dict(zip(('cases','vectors','taps','post_beats','packed_words','valid_bytes','pack_stalls','post_stalls','done'),values))
        check(values[:6]==[len(cases),nv,nv*25,nb*20,nw,validbytes] and values[6]>0 and values[7]>0 and values[8]==len(cases),'Exact dataflow counts and observed backpressure')
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+(OWN/'z100_maxpool_collect32.sv').as_posix()+'}\nsynth_design -top z100_maxpool_collect32 -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'collector_utilization.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'collector.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        util=(out/'collector_utilization.rpt').read_text()
        def metric(name):return int(re.search(r'^\|\s*'+name+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=metric('DSPs'),BRAM=metric('Block RAM Tile'))
        check(resources['DSP']==resources['BRAM']==0 and resources['Slice_LUT']<12000,'Collector resource screen')
        r.update(status='PASS_PRIVATE_EPOCH200_MAXPOOL_COLLECT_PACK_XSIM_COLLECTOR_OOC_ONLY',collector_resources=resources,
                 scope='Actual reducer->collector->frozen native output packer; no feature-window address generator, fullgraph controller, HP DMA, route or board proof')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        r['source_sha256_before']=before;r['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in sources}
        if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
        report=out/'result.json';r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for base in (out,build) for p in base.rglob('*') if p.is_file() and p!=report};report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
