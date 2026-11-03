"""Private eight-byte loader, exhaustive current quality200 table readback."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,os,re,shutil,subprocess
for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[key]='1'
ROOT=Path(__file__).resolve().parents[1]
OWN=ROOT/'deployment/hardware/z100_2026/pointwise_lookup64_v1'
ASSET=ROOT/'validation/board_z100/pointwise_tables_v1/20261024T105738.323222Z_336c918a/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok,msg):
    if not ok:raise ValueError(msg)

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/pointwise_lookup64_v1'/stamp
    build=ROOT/'build'/('pw64_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl,tb=OWN/'z100_pointwise_lookup64.sv',OWN/'tb_z100_pointwise_lookup64.sv'
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    sources=[Path(__file__),rtl,tb,ASSET];before={};report=out/'result.json'
    try:
        asset=read(ASSET)
        check(asset['status']=='PASS_PIN640_POINTWISE_TABLES_HOST_ONLY','Exact current C-oracle table derivation')
        check(asset['source_sha256']==asset['source_sha256_after'],'Table input stability')
        for name,digest in {**asset['source_sha256_after'],**asset['artifact_sha256']}.items():
            check(sha(ROOT/name)==digest,'Bound table source/artifact '+name)
        manifest_path=ROOT/asset['manifest_file'];manifest=read(manifest_path)
        check(sha(manifest_path)==asset['manifest_sha256'],'Sealed table manifest')
        sources.append(manifest_path)
        tables=sorted(manifest['tables'],key=lambda t:t['asset_file'])
        check(len(tables)==128 and sum('add' in t['table_kind'] for t in tables)==6,'Table inventory')
        (build/'tables').mkdir()
        with (build/'pointwise_tables.index').open('w') as index:
            for i,t in enumerate(tables):
                source=manifest_path.parent/t['asset_file'];sources.append(source)
                blob=source.read_bytes();mode=int('add' in t['table_kind'])
                check(len(blob)==t['byte_length']==(65536 if mode else 256) and sha(source)==t['sha256'],'Exact unary/Add payload')
                name=f'tables/table{i:03d}.hex'
                (build/name).write_text(''.join(f'{v:02x}\n' for v in blob))
                input_index=-1 if mode else t['input_index']
                index.write(f'{i} {mode} {len(blob)} {t["node_id"]} {input_index} {name}\n')
        before={str(p.relative_to(ROOT)):sha(p) for p in sources}
        for p in (rtl,tb,Path(__file__)):shutil.copy2(p,out/p.name)
        def run(label,args):
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict vendor diagnostics '+label)
            return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',rtl,tb])
        run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_pointwise_lookup64','-s','pw64_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','pw64_sim','-runall'])
        marker=re.findall(r'^POINTWISE_LOOKUP64_PASS (.+)$',text,re.M)
        check(len(marker)==1,'Complete exhaustive wide lookup marker')
        counts={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',marker[0])}
        for k,v in dict(tables=128,unary_tables=122,add_tables=6,exhaustive_beats=26528,exhaustive_values=424448,
                        cfg_write_beats=53159,overlong=1,refused=4,errors=8,reset=1,cancel=1).items():
            check(counts.get(k)==v,'Actual coverage '+k)
        check(counts['comparisons']>=424448 and counts['max_ii1']>=4096 and counts['stalls']>=5,'Read mux/throughput/stall coverage')
        r['simulation']=counts
        tcl=build/'synth.tcl'
        tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+rtl.as_posix()+'}\nsynth_design -top z100_pointwise_lookup64 -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'lookup.dcp').as_posix()+'}\nputs "PW64_CENSUS LATCH [llength [get_cells -hier -filter {PRIMITIVE_SUBGROUP == LATCH}]]"\nputs "PW64_CENSUS BLACKBOX [llength [get_cells -hier -filter {IS_BLACKBOX}]]"\nexit\n')
        synth=run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        util=(out/'utilization.rpt').read_text()
        def metric(n):return float(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*([\d.]+)',util,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=metric('DSPs'),BRAM36eq=metric('Block RAM Tile'))
        check(resources['BRAM36eq']==128 and resources['DSP']==0 and resources['Slice_LUT']<6000,'Expected banked table resource budget')
        check('PW64_CENSUS LATCH 0' in synth and 'PW64_CENSUS BLACKBOX 0' in synth,'No latch/blackbox')
        r.update(status='PASS_PRIVATE_QUALITY200_POINTWISE64_EXHAUSTIVE_XSIM_OOC',resources=resources,
            config_bytes_per_handshake=8,nominal_all128table_load_beats=53056,nominal_six_add_load_beats=49152,
            original_six_add_load_beats=393216,model_package_sha256='65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c',
            scope='Private64-bit configuration interface;16lane lookup integer semantics/protocol timing preserved. V8PK/tile64 production ABI unchanged. Load counts exclude command/DDR/bubbles; no integrated bandwidth, routed clock, board or FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        r['source_sha256_before']=before;r['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in sources} if before else {}
        if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
        r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))

if __name__=='__main__':raise SystemExit(main())
