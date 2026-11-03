"""Bidirectional native-stream word-order codec with an actual200 SPPF tensor."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess,sys
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
OWN=ROOT/'deployment/hardware/z100_2026/native_stream_order_v1'
POOL=ROOT/'validation/board_z100/maxpool_store20_v1/20261024T114248.653929Z/result.json'
POOL_REVIEW=ROOT/'validation/board_z100/maxpool_store20_review/20261024T114811.460230Z/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)

def main():
    from z100_native_stream_layout import NativeStreamLayout
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_stream_order_v1'/stamp;build=ROOT/'build'/('nsord_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl,tb=OWN/'z100_native_stream_order.sv',OWN/'tb_z100_native_stream_order.sv'
    sources=[Path(__file__),rtl,tb,ROOT/'tools/z100_native_stream_layout.py',ROOT/'tools/z100_feature_window_layout.py',POOL,POOL_REVIEW]
    before={};r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    report=out/'result.json'
    try:
        p=json.loads(POOL.read_text());pr=json.loads(POOL_REVIEW.read_text())
        check(pr['status']=='ROOT_ACCEPT_AUTONOMOUS_POOL_XSIM_OOC128BRAM_UNUSED_PORTS_PRUNED_NOTBOARD' and pr['original_failed_report_sha256']==sha(POOL),'Actual signed MaxPool source binding')
        input_file=next(ROOT/n for n in p['artifact_sha256'] if Path(n).name=='input.hex');sources.append(input_file)
        check(sha(input_file)==p['artifact_sha256'][str(input_file.relative_to(ROOT))],'Actual200 source fixture')
        before={str(p.relative_to(ROOT)):sha(p) for p in sources}
        actual_stream=b''.join(int(line,16).to_bytes(64,'little') for line in input_file.read_text().splitlines()[:1280])
        actual_layout=NativeStreamLayout(128,20,20);actual_chw=actual_layout.unpack(actual_stream)
        check(hashlib.sha256(actual_chw).hexdigest()==p['fixture']['cases'][0]['input_sha256'],'Actual node69 CHW reconstruction')
        cases=[(1,1,1),(3,2,640),(16,64,320),(32,20,20),(33,2,17),(73,80,80),(9,1,20),(128,20,20)]
        nw=0;summary=[]
        with (build/'words.hex').open('w') as f,(build/'cases.hex').open('w') as cf:
            for c,h,w in cases:
                layout=NativeStreamLayout(c,h,w)
                chw=actual_chw if (c,h,w)==(128,20,20) else bytes((cc*47+yy*13+xx*7)&255 for cc in range(c) for yy in range(h) for xx in range(w))
                stream=layout.pack(chw);addresses=list(layout.addresses())
                check(layout.unpack(stream)==chw and sorted(addresses)==list(range(layout.words)),'Complete independent CHW/canonical/stream permutation')
                check(layout.words<=8192,'Bank-bounded codec fixture')
                for i,address in enumerate(addresses):
                    word=int.from_bytes(stream[i*64:(i+1)*64],'little');f.write(f'{word|(address<<512)|(i<<525):0135x}\n')
                cf.write(f'{c|(h<<11)|(w<<21)|(layout.words<<31):012x}\n');nw+=layout.words
                summary.append(dict(shape=[c,h,w],words=layout.words,CHW_sha256=hashlib.sha256(chw).hexdigest(),stream_sha256=hashlib.sha256(stream).hexdigest()))
        (build/'fixture_defs.vh').write_text(f'`define CASES {len(cases)}\n`define WORDS {nw}\n')
        r['fixture']=dict(cases=summary,words_per_direction=nw,model_scope='Last fixture is actual current-quality200 node69; others adversarial geometry/pattern data',layout='z100-native-stream/1')
        for f in (rtl,tb,Path(__file__)):shutil.copy2(f,out/f.name)
        def run(label,args):
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict vendor diagnostic '+label)
            return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',rtl,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_stream_order','-s','nsorder_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','nsorder_sim','-runall'])
        markers=re.findall(r'^NATIVE_STREAM_ORDER_PASS cases=(\d+) words=(\d+) stalls=(\d+) errors=(\d+) aborts=(\d+) done=(\d+)$',text,re.M)
        check(len(markers)==1,'Complete native stream codec marker')
        values=list(map(int,markers[0]));check(values[:2]==[16,2*nw] and values[2]>0 and values[3:]==[10,2,16],'Both modes full permutations, errors, stalls and semantic aborts')
        r['simulation']=dict(zip(('cases','words','stalls','errors','aborts','done'),values))
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+rtl.as_posix()+'}\nsynth_design -top z100_native_stream_order -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'stream_order.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        util=(out/'utilization.rpt').read_text()
        def metric(n):return int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=metric('DSPs'),BRAM=metric('Block RAM Tile'))
        check(resources['DSP']==resources['BRAM']==0 and resources['Slice_LUT']<5000,'Metadata-only codec resource gate')
        r.update(status='PASS_PRIVATE_BIDIRECTIONAL_NATIVE_STREAM_ORDER_XSIM_OOC',resources=resources,
            scope='Contiguous stream ordinal versus bank address metadata only; no payload reorder buffer. Not yet linked to AXI read/write or physical DDR. Multi-command/tile ROI producers must supply global tile index/last semantics; no AXI cancellation/reset guarantee.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        r['source_sha256_before']=before;r['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in sources} if before else {}
        if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
        r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))

if __name__=='__main__':raise SystemExit(main())
