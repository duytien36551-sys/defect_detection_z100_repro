"""Epoch200 SPPF signed-MaxPool80 reducer: host oracle, XSim and bounded OOC."""
from pathlib import Path
from datetime import datetime, timezone
import os, sys, json, hashlib, subprocess, re, shutil
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'): os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
PIPE=ROOT/'deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline'
HW=ROOT/'deployment/hardware/z100_2026/maxpool_vector_v1'
RGB=ROOT/'validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_rgb.bin'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def read(p):return json.loads(p.read_text())
def main():
    import numpy as np
    import torch
    from deployment.candidates.pin640.quantize import run_integer
    torch.set_num_threads(1)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/maxpool_vector_v1'/stamp;build=ROOT/'build'/('mp_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),*HW.glob('*.sv'),PIPE/'model/graph.json',PIPE/'quantization/quantization.json',
           PIPE/'quantization/weights_int8.npz',ROOT/'deployment/candidates/pin640/quantize.py',
           ROOT/'deployment/candidates/pin640/export_graph.py',RGB]
    before={str(p.relative_to(ROOT)):sha(p) for p in files}
    for p in files[:3]:shutil.copy2(p,out/p.name)
    r=dict(status='RUNNING',commands=[],board_access=False,production_integrated=False,
           routed_clock_accepted=False,full_pipeline_30fps_accepted=False)
    try:
        graph=read(PIPE/'model/graph.json');q=read(PIPE/'quantization/quantization.json')
        check(graph['checkpoint_sha256']==q['model_sha256']=='2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6','Selected200 source')
        check(sha(RGB)=='f82d6ce4ad170ec4859a49f405d6a0b7ca2cdbd93b5e57142a556a92ccd750e0','Fixed validation RGB')
        check(len({q['scales'][str(i)] for i in (69,70,71,72)})==1,'These three SPPF nodes require equal scale for reducer-only integration')
        with np.load(PIPE/'quantization/weights_int8.npz') as z:params={k:torch.from_numpy(z[k].copy()) for k in z.files}
        image=torch.from_numpy(np.frombuffer(RGB.read_bytes(),dtype=np.uint8).reshape(640,640,3).transpose(2,0,1).copy()).float()[None]/255
        observed={}
        run_integer(graph,params,q,image,observe=lambda i,y:observed.update({i:y.numpy().copy()}) if i in (69,70,71,72) else None)
        vectors=validbytes=negative_boundary_vectors=0
        with (build/'taps.hex').open('w') as taps,(build/'golden.hex').open('w') as gold,(build/'lanes.hex').open('w') as lanes:
            sources=[(f'node{i}',observed[i][0],observed[i+1][0]) for i in (69,70,71)]
            # Strictly negative boundaries expose accidental zero padding.
            neg=-(np.arange(3*3*7).reshape(3,3,7)%120+1).astype(np.int8)
            sources.append(('negative',neg,None))
            source_summaries=[]
            for name,a,expected in sources:
                c,h,w=a.shape;flat=np.arange(c*h*w);count=0
                pad=np.pad(a.astype(np.int16),((0,0),(2,2),(2,2)),constant_values=-128)
                direct=np.stack([pad[:,dy:dy+h,dx:dx+w] for dy in range(5) for dx in range(5)]).max(axis=0).astype(np.int8)
                if expected is not None:check(np.array_equal(direct,expected),'Independent signed MaxPool vs integer graph '+name)
                for start in range(0,len(flat),80):
                    ix=flat[start:start+80];n=len(ix);ch=ix//(h*w);oy=(ix//w)%h;ox=ix%w
                    golden=np.zeros(80,dtype=np.int8);golden[:n]=direct.reshape(-1)[ix]
                    gold.write(f'{int.from_bytes(golden.tobytes(),"little"):0160x}\n');lanes.write(f'{n:02x}\n')
                    edge=False
                    for dy in range(-2,3):
                        for dx in range(-2,3):
                            yy=oy+dy;xx=ox+dx;valid=(yy>=0)&(yy<h)&(xx>=0)&(xx<w)
                            values=np.full(80,127,dtype=np.int8)
                            values[:n][valid]=a[ch[valid],yy[valid],xx[valid]]
                            mask=sum(1<<int(i) for i in np.flatnonzero(valid))
                            taps.write(f'{mask:020x}{int.from_bytes(values.tobytes(),"little"):0160x}\n')
                            edge |= not bool(valid.all())
                    if name=='negative' and edge:negative_boundary_vectors+=1
                    vectors+=1;count+=1;validbytes+=n
                source_summaries.append(dict(source=name,shape=list(a.shape),vectors=count,raw_input_sha256=hashlib.sha256(a.tobytes()).hexdigest()))
        (build/'fixture_defs.vh').write_text(f'`define VECTORS {vectors}\n`define VALID_BYTES {validbytes}\n')
        r['fixture']=dict(vectors=vectors,taps=vectors*25,valid_bytes=validbytes,sources=source_summaries,
                          negative_boundary_vectors=negative_boundary_vectors,invalid_tap_poison=127,
                          oracle='Direct signed CHW 5x5 maximum; compared with all three actual epoch200 SPPF nodes')
        def run(label,args):
            p=subprocess.run(list(map(str,args)),cwd=build,env=os.environ.copy(),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=list(map(str,args)),return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),label+' vendor diagnostic')
            return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',HW/'z100_maxpool_vector.sv',HW/'tb_z100_maxpool_vector.sv'])
        run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_maxpool_vector','-s','mp_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','mp_sim','-runall'])
        match=re.findall(r'^MAXPOOL_VECTOR_PASS vectors=(\d+) taps=(\d+) bytes=(\d+) held_cycles=(\d+) errors=(\d+) recoveries=(\d+)$',text,re.M)
        check(len(match)==1,'One anchored complete numeric marker')
        v,t,b,holds,errors,recoveries=map(int,match[0])
        check((v,t,b,errors,recoveries)==(vectors,vectors*25,validbytes,8,12) and holds>=vectors,'Exact numeric and recovery counts')
        r['simulation']=dict(vectors=v,taps=t,bytes=b,held_cycles=holds,errors=errors,recoveries=recoveries)
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+(HW/'z100_maxpool_vector.sv').as_posix()+'}\nsynth_design -top z100_maxpool_vector -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nreport_timing_summary -file {'+(out/'timing_unplaced.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'post_synth.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        util=(out/'utilization.rpt').read_text()
        def metric(name):return int(re.search(r'^\|\s*'+name+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        r['resources']=dict(Slice_LUT=metric('Slice LUTs'),Slice_Registers=metric('Slice Registers'),DSP=metric('DSPs'),BRAM=metric('Block RAM Tile'))
        check(r['resources']['DSP']==r['resources']['BRAM']==0 and r['resources']['Slice_LUT']<6000,'Bounded resource screen')
        r.update(status='PASS_PRIVATE_EPOCH200_MAXPOOL80_XSIM_OOC_ONLY',model_sha256=graph['checkpoint_sha256'],
                 scope='Tap reducer only; no feature-address generator, Add path, fullgraph controller, route or board execution')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        r['source_sha256_before']=before;r['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in files}
        if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
        report=out/'result.json';r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for base in (out,build) for p in base.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
