"""Actual AXI adapters -> native stream codec -> signed pool -> AXI commit.

Three actual200 SPPF passes feed each other exclusively through a shared byte
memory. Test-only host control/commit barrier; not synthesized graph firmware.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess,sys
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
HW=ROOT/'deployment/hardware/z100_2026';OWN=HW/'native_pool_chain_v1'
POOL=ROOT/'validation/board_z100/maxpool_store20_v1/20261024T114248.653929Z/result.json'
REVIEW=ROOT/'validation/board_z100/maxpool_store20_review/20261024T114811.460230Z/result.json'
ORDER=ROOT/'validation/board_z100/native_stream_order_v1/20261024T122258.474499Z/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok,msg):
    if not ok:raise ValueError(msg)

def main():
    import numpy as np
    from z100_native_stream_layout import NativeStreamLayout
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_pool_chain_v1'/stamp;build=ROOT/'build'/('mpaxi_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl=[HW/'native_axi64_reader_v1/z100_native_axi64_reader.sv',HW/'native_axi64_writer_v1/z100_native_axi64_writer.sv',
         HW/'native_stream_order_v1/z100_native_stream_order.sv',HW/'feature_banks_addressed_v1/z100_feature_banks_addressed.sv',
         HW/'feature_banks_4read_v4/z100_feature_banks_4read.sv',HW/'maxpool_store20_v1/z100_feature_window20_pool5.sv',
         HW/'maxpool_vector_v1/z100_maxpool_vector.sv',HW/'maxpool_collect32_v1/z100_maxpool_collect32.sv',
         HW/'native_row20_v1/z100_native_output_packer.sv',HW/'maxpool_store20_v1/z100_maxpool_store20.sv', OWN/'z100_native_pool_chain_control.sv']
    tb=OWN/'tb_z100_native_pool_chain.sv';memory=HW/'native_pool_axi_v1/axi3_byte_memory.sv'
    sources=[Path(__file__),*rtl,tb,memory,POOL,REVIEW,ORDER,ROOT/'tools/z100_native_stream_layout.py',ROOT/'tools/z100_feature_window_layout.py']
    before={};r=dict(status='RUNNING',commands=[],board_access=False,production_integrated=False,full_pipeline_30fps_accepted=False)
    report=out/'result.json'
    try:
        p,review,order=map(read,(POOL,REVIEW,ORDER))
        check(review['status']=='ROOT_ACCEPT_AUTONOMOUS_POOL_XSIM_OOC128BRAM_UNUSED_PORTS_PRUNED_NOTBOARD' and review['original_failed_report_sha256']==sha(POOL),'Reviewed autonomous pool')
        check(order['status']=='PASS_PRIVATE_BIDIRECTIONAL_NATIVE_STREAM_ORDER_XSIM_OOC','Actual codec proof')
        for proof in (p,order):
            check(proof['source_sha256_before']==proof['source_sha256_after'],'Source integrity')
            for name,h in {**proof['source_sha256_after'],**proof['artifact_sha256']}.items():check(sha(ROOT/name)==h,'Prerequisite drift '+name)
        files={Path(n).name:ROOT/n for n in p['artifact_sha256'] if Path(n).name in ('input.hex','golden.hex')}
        check(len(files)==2,'Original actual model fixture files')
        sources += list(files.values())
        before={str(f.relative_to(ROOT)):sha(f) for f in sources}
        ins=files['input.hex'].read_text().splitlines();gold=files['golden.hex'].read_text().splitlines()
        source_offset=0;expected_offset=0;total_words=seed_words=bursts=0;prev=None;summary=[]
        with (build/'input.hex').open('w') as fi,(build/'golden.hex').open('w') as fg,(build/'cases.hex').open('w') as fc:
            for i,case in enumerate(p['fixture']['cases']):
                c,h,w=case['shape'];layout=NativeStreamLayout(c,h,w);nw=layout.words
                input_blob=b''.join(int(v,16).to_bytes(64,'little') for v in ins[source_offset:source_offset+nw])
                expected_blob=b''.join(int(v,16).to_bytes(64,'little') for v in gold[expected_offset:expected_offset+nw])
                source=layout.unpack(input_blob);expected=layout.unpack(expected_blob)
                check(hashlib.sha256(source).hexdigest()==case['input_sha256'],'Input CHW identity')
                check(hashlib.sha256(layout.feature.pack(expected)).hexdigest()==case['packed_output_sha256'],'Canonical CHW output identity')
                a=np.frombuffer(source,dtype=np.int8).reshape(c,h,w).astype(np.int16)
                pad=np.pad(a,((0,0),(2,2),(2,2)),constant_values=-128)
                independent=np.stack([pad[:,ky:ky+h,kx:kx+w] for ky in range(5) for kx in range(5)]).max(axis=0).astype(np.int8).tobytes()
                check(independent==expected,'Independent signed5x5 CHW golden')
                seed=i in (0,3,4)
                if not seed:check(prev==source,'Three SPPF node outputs feed the next exact input')
                if seed:
                    fi.write(''.join(v+'\n' for v in ins[source_offset:source_offset+nw]));seed_words+=nw
                fg.write(''.join(v+'\n' for v in gold[expected_offset:expected_offset+nw]))
                fc.write(f'{c|(h<<11)|(nw<<21)|(int(seed)<<35):09x}\n')
                summary.append(dict(source=case['source'],shape=[c,h,w],words=nw,new_seed=seed,input_sha256=hashlib.sha256(source).hexdigest(),output_sha256=hashlib.sha256(expected).hexdigest()))
                prev=expected;source_offset+=nw;expected_offset+=nw;total_words+=nw;bursts+=(nw+1)//2
        check(source_offset==len(ins) and expected_offset==len(gold),'All fixture words consumed')
        (build/'fixture_defs.vh').write_text(f'`define CASES 5\n`define WORDS {total_words}\n`define INPUT_WORDS {seed_words}\n`define BURSTS {bursts}\n')
        r['fixture']=dict(cases=summary,total_words=total_words,total_read_bytes=total_words*64,total_write_bytes=total_words*64,
            seed_words=seed_words,bursts_per_direction=bursts,source_package_sha256=p['fixture']['package_sha256'],
            oracle='Independent CHW signed5x5 maximum; all committed shared memory bytes compared; no intermediate SPPF results injected by host')
        for f in [*rtl,tb,memory,Path(__file__)]:shutil.copy2(f,out/f.name)
        def run(label,args):
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict vendor diagnostic '+label)
            return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl,memory,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_pool_chain','-s','pool_axi_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','pool_axi_sim','-runall'])
        markers=re.findall(r'^NATIVE_POOL_CHAIN_PASS (.+)$',text,re.M);check(len(markers)==1,'Complete actual AXI/pool chain marker')
        values={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        wanted=dict(commands=3,completed=3,passes=5,chained_sppf=3,words=total_words,AW=bursts,W=total_words*8,B=bursts,AR=bursts,R=total_words*8)
        check(all(values.get(k)==v for k,v in wanted.items()) and values['blocked_write_cycles']>0,'Actual autonomous traffic/completion/commit coverage')
        r.update(status='PASS_PRIVATE_AUTONOMOUS_CONTROLLER_REAL_AXI_THREE_SPPF_CHAIN_XSIM',simulation=values,
            scope='Actual hardware controller owns all read/config/commit/pool/write commands and range alternation. TB submits3 commands for5passes and verifies byte memory. Current test covers successful flow; fault/drain/recovery tests separate. No fullgraph/PS HP/DDR hardware, routed platform or board performance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        r['source_sha256_before']=before;r['source_sha256_after']={str(f.relative_to(ROOT)):sha(f) for f in sources} if before else {}
        if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
        r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
        report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))

if __name__=='__main__':raise SystemExit(main())
