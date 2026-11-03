"""Source-store to addressed MaxPool output, actual selected200 quality package."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, shutil, subprocess, sys
for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):
    os.environ[key]='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
HW=ROOT/'deployment/hardware/z100_2026'
OWN=HW/'shared_window_pool_v1'
BASE=ROOT/'deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline'
CANDIDATE=ROOT/'deployment/candidates/pin640/quant_candidates/epoch200_head_concat_20261024T103836.103919Z'
QUALITY=ROOT/'validation/board_z100/epoch200_head_concat_review/20261024T105726.857325Z/result.json'
RGB=ROOT/'validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_rgb.bin'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def main():
    import numpy as np
    import torch
    from deployment.candidates.pin640.quantize import run_integer
    from z100_feature_window_layout import FeatureLayout
    torch.set_num_threads(1)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/shared_pool_fixture_v1'/stamp
    build=ROOT/'build'/('mpstore_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl=[HW/'feature_banks_addressed_v1/z100_feature_banks_addressed.sv',
         HW/'feature_banks_4read_v4/z100_feature_banks_4read.sv',
         HW/'maxpool_store20_v1/z100_feature_window20_pool5.sv',HW/'maxpool_vector_v1/z100_maxpool_vector.sv',
         HW/'maxpool_collect32_v1/z100_maxpool_collect32.sv',HW/'native_row20_v1/z100_native_output_packer.sv',
         OWN/'z100_maxpool_window20.sv', OWN/'z100_shared_pool_fixture.sv']
    tb=OWN/'tb_z100_shared_pool_fixture.sv'
    sources=[Path(__file__),*rtl,tb,HW/'feature_window20_v1/z100_feature_window20.sv',
             BASE/'model/graph.json',CANDIDATE/'package/MODEL.V8P',CANDIDATE/'quantization/quantization.json',
             CANDIDATE/'quantization/weights_int8.npz',QUALITY,RGB,
             ROOT/'deployment/candidates/pin640/quantize.py',ROOT/'deployment/candidates/pin640/export_graph.py',
             ROOT/'tools/z100_feature_window_layout.py']
    before={str(p.relative_to(ROOT)):sha(p) for p in sources}
    r=dict(status='RUNNING',board_access=False,fullgraph_accepted=False,routed_clock_accepted=False,
           full_pipeline_30fps_accepted=False,commands=[],source_sha256_before=before)
    report=out/'result.json'
    try:
        qreview=read(QUALITY)
        check(qreview['accuracy_accepted'] and qreview['package_sha256']==sha(CANDIDATE/'package/MODEL.V8P'), 'Reviewed selected200 quality package')
        original=(HW/'feature_window20_v1/z100_feature_window20.sv').read_text()
        expected='// Isolated5x5-p2 admission: only first_x minimum and last_x maximum change.\n'+original.replace('module z100_feature_window20 (','module z100_feature_window20_pool5 (').replace('first_x>=-1','first_x>=-2').replace('last_x > width_int','last_x > width_int+1')
        check(expected==(HW/'maxpool_store20_v1/z100_feature_window20_pool5.sv').read_text(),'Only private signed-padding2 bounds widened; original unchanged')
        for p in [*rtl,tb,Path(__file__)]:shutil.copy2(p,out/p.name)
        graph,q=read(BASE/'model/graph.json'),read(CANDIDATE/'quantization/quantization.json')
        check(graph['checkpoint_sha256']==q['model_sha256']==qreview['checkpoint_sha256'],'Selected checkpoint identity')
        check(len({q['scales'][str(i)] for i in (69,70,71,72)})==1,'Model-specific SPPF scale equality')
        check(sha(RGB)=='f82d6ce4ad170ec4859a49f405d6a0b7ca2cdbd93b5e57142a556a92ccd750e0','Fixed validation RGB')
        with np.load(CANDIDATE/'quantization/weights_int8.npz') as z:params={k:torch.from_numpy(z[k].copy()) for k in z.files}
        image=torch.from_numpy(np.frombuffer(RGB.read_bytes(),dtype=np.uint8).reshape(640,640,3).transpose(2,0,1).copy()).float()[None]/255
        captured={}
        run_integer(graph,params,q,image,observe=lambda i,y:captured.update({i:y.numpy()[0].copy()}) if i in (69,70,71,72) else None)
        cases=[(f'node{i}',captured[i],captured[i+1]) for i in (69,70,71)]
        cases += [('negative_tail9',-(np.arange(180).reshape(9,1,20)%100+1).astype(np.int8),None),
                  ('channel_tail33',((np.arange(1320).reshape(33,2,20)*17+27)%255-127).astype(np.int8),None)]
        inputs=words=vectors=0;summary=[]
        with (build/'input.hex').open('w') as fi,(build/'input_addresses.hex').open('w') as fia,(build/'golden.hex').open('w') as fg,(build/'addresses.hex').open('w') as fa,(build/'cases.hex').open('w') as fc:
            for name,a,graph_expected in cases:
                c,h,w=a.shape;check(w==20 and c<=128 and h<=20,'Bounded actual SPPF geometry')
                pad=np.pad(a.astype(np.int16),((0,0),(2,2),(2,2)),constant_values=-128)
                gold=np.stack([pad[:,ky:ky+h,kx:kx+w] for ky in range(5) for kx in range(5)]).max(axis=0).astype(np.int8)
                if graph_expected is not None:check(np.array_equal(gold,graph_expected),'Independent signed5x5 equals graph '+name)
                layout=FeatureLayout(c,h,w);inp=layout.pack(a.tobytes());packed=layout.pack(gold.tobytes())
                for c32 in range(0,c,32):
                    for y in range(h):
                        for xw in range(2):
                            for sg in range((min(32,c-c32)+3)//4):
                                addr=(((c32//4+sg)*h+y)*2+xw)
                                fi.write(f'{int.from_bytes(inp[addr*64:(addr+1)*64],"little"):0128x}\n');fia.write(f'{addr:04x}\n')
                                fg.write(f'{int.from_bytes(packed[addr*64:(addr+1)*64],"little"):0128x}\n');fa.write(f'{addr:04x}\n')
                fc.write(f'{c|(h<<11)|(layout.words<<21)|(layout.words<<35):032x}\n')
                inputs+=layout.words;words+=layout.words;vectors+=((c+3)//4)*h
                summary.append(dict(source=name,shape=list(a.shape),input_words=layout.words,output_words=layout.words,
                    input_sha256=hashlib.sha256(a.tobytes()).hexdigest(),packed_output_sha256=hashlib.sha256(packed).hexdigest()))
        (build/'fixture_defs.vh').write_text(f'`define CASES {len(cases)}\n`define INPUT_WORDS {inputs}\n`define WORDS {words}\n`define VECTORS {vectors}\n')
        r['fixture']=dict(cases=summary,input_words=inputs,output_words=words,vectors=vectors,descriptors=vectors*25,
            package_sha256=sha(CANDIDATE/'package/MODEL.V8P'),source_checkpoint_sha256=graph['checkpoint_sha256'])
        def run(label,argv):
            p=subprocess.run(list(map(str,argv)),cwd=build,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=list(map(str,argv)),return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict vendor diagnostic '+label)
            return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl,tb])
        run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_shared_pool_fixture','-s','mpstore_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','mpstore_sim','-runall'])
        markers=re.findall(r'^SHARED_POOL_FIXTURE_PASS cases=(\d+) words=(\d+) descriptors=(\d+) vectors=(\d+) stalls=(\d+) invalid_jobs=(\d+) aborts=(\d+) done=(\d+)$',text,re.M)
        check(len(markers)==1,'Complete autonomous MaxPool PASS marker')
        values=list(map(int,markers[0]));check(values[:4]==[len(cases),words,vectors*25,vectors] and values[4]>0 and values[5:]==[5,2,len(cases)],'Data, real window activity, stalls and recovery coverage')
        r['simulation']=dict(zip(('cases','words','descriptors','vectors','stalls','invalid_jobs','aborts','done'),values))
        tcl=build/'synth.tcl'
        tcl.write_text('set_param general.maxThreads 2\n'+''.join('read_verilog -sv {'+p.as_posix()+'}\n' for p in rtl)+
            'synth_design -top z100_shared_pool_fixture -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'pool.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        util=(out/'utilization.rpt').read_text()
        def metric(n):return float(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*([\d.]+)',util,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=metric('DSPs'),BRAM36eq=metric('Block RAM Tile'))
        check(resources['DSP']==0 and resources['BRAM36eq']==128 and resources['Slice_LUT']<65000,'Stride1-only static port pruning leaves one128BRAM payload copy; numeric/protocol contract unchanged')
        r.update(status='PASS_PRIVATE_SHARED_WINDOW_SOURCE_AND_CACHEFREE_POOL_XSIM_OOC',resources=resources,
            scope='Extracted no-feature-RAM pool consumer with external shared window source. Actual5case source-store regression, no shared conv/pool switching proof in this harness; combined wrapper verified separately. No fullgraph/board/FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        r['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in sources}
        if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
        r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))

if __name__=='__main__':raise SystemExit(main())
