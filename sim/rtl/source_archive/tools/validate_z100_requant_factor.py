"""Actual3-DSP exact rescaler: every selected200 C-verified transition neighbor."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,random,re,shutil,struct,subprocess,sys
for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[key]='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
OWN=ROOT/'deployment/hardware/z100_2026/requant_factor_v1'
SURVEY=ROOT/'validation/board_z100/exact_requant_factor_survey/20261024T115605.743100Z/result.json'
ASSET=ROOT/'validation/board_z100/current_requant_tables/20261024T105738.290964Z_37e400a8/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
MACRO=VENDOR.parent/'data/verilog/src/unimacro/MULT_MACRO.v'
DSP=VENDOR.parent/'data/verilog/src/unisims/DSP48E1.v'
GLBL=VENDOR.parent/'data/verilog/src/glbl.v'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok,msg):
    if not ok:raise ValueError(msg)
def rel(p):
    try:return str(Path(p).relative_to(ROOT))
    except ValueError:return 'external/'+Path(p).drive.rstrip(':')+'/'+Path(p).relative_to(Path(p).anchor).as_posix()
def rational(raw,m,shift):
    q,rem=divmod(raw*m,1<<shift)
    if shift and (rem>(1<<(shift-1)) or rem==(1<<(shift-1)) and q&1):q+=1
    return max(-127,min(127,q))

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/requant_factor_v1'/stamp
    build=ROOT/'build'/('rqf_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl,tb=OWN/'z100_requant_factor.sv',OWN/'tb_z100_requant_factor.sv'
    sources=[Path(__file__),rtl,tb,SURVEY,ASSET,MACRO,DSP,GLBL]
    before={};r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    report=out/'result.json'
    try:
        from validate_z100_requant_thresholds import probes
        s,a=read(SURVEY),read(ASSET)
        check(s['status']=='PASS_HOST_COMPLETE_MONOTONE_TRANSITION_FACTOR_SURVEY' and s['exact_factor_channels']==5419 and s['fallback_threshold_channels']==0,'All channel factors exact')
        for proof in (s,a):
            for name,h in proof.get('source_sha256_after',{}).items():check(sha(ROOT/name)==h,'Source binding '+name)
            for name,h in proof['artifact_sha256'].items():check(sha(ROOT/name)==h,'Artifact binding '+name)
        check(a['status']=='PASS_CURRENT_PACKAGE_EXACT_THRESHOLDS_HOST_ONLY','C-verified current factor source')
        index=next(ROOT/k for k in a['artifact_sha256'] if Path(k).name=='channel_index.json')
        tables=next(ROOT/k for k in a['artifact_sha256'] if Path(k).name=='thresholds_254_i64.bin')
        boundaries=next(ROOT/k for k in a['artifact_sha256'] if Path(k).name=='boundaries.bin')
        sources += [index,tables,boundaries,ROOT/'tools/validate_z100_requant_thresholds.py']
        before={rel(p):sha(p) for p in sources}
        for p in [rtl,tb,Path(__file__)]:shutil.copy2(p,out/p.name)
        rows=read(index);keys=[v[0] for v in struct.iter_unpack('<q',tables.read_bytes())]
        records=iter(struct.iter_unpack('<dib',boundaries.read_bytes()))
        factors={v['index']:v['selected'] for v in s['factors']};n=0
        with (build/'vectors.hex').open('w') as f:
            def emit(raw,m,shift,expected):
                nonlocal n
                check(rational(raw,m,shift)==expected,'Independent rational ties-even semantics')
                p=raw*m;check(-(1<<62)<=p<(1<<62),'Signed63 product bound')
                value=(raw&0xffffffff)|(m<<32)|(shift<<63)|((expected&255)<<78)|((p&((1<<63)-1))<<86)
                f.write(f'{value:038x}\n');n+=1
            for i,row in enumerate(rows):
                p=factors[i];mult=struct.unpack('<d',bytes.fromhex(row['multiplier_binary64_le_hex']))[0]
                for raw in probes(keys[i*254:(i+1)*254]):
                    cm,cr,expected=next(records)
                    check(cm==mult and cr==raw,'Exact ordered C-oracle records')
                    emit(raw,p['multiplier'],p['shift'],expected)
            check(next(records,None) is None and n==a['c_boundary_vectors'],'All C records replayed exactly once')
            boundary_vectors=n
            for raw in (-(1<<31),-(1<<31)+1,-65537,-65536,-32769,-1,0,1,32767,65535,65536,(1<<31)-1):
                for m in (1,2,65535,65536,65537,(1<<30),(1<<31)-1):
                    for sh in (0,1,15,16,30,31,32,44,62,63):emit(raw,m,sh,rational(raw,m,sh))
            rng=random.Random(640200)
            for i in range(8192):
                raw=rng.randrange(-(1<<31),1<<31);m=rng.randrange(1,1<<31);sh=rng.randrange(64)
                emit(raw,m,sh,rational(raw,m,sh))
        (build/'fixture_defs.vh').write_text(f'`define VECTORS {n}\n')
        r['fixture']=dict(channels=5419,C_boundary_vectors=boundary_vectors,additional_arithmetic_vectors=n-boundary_vectors,total_vectors=n,
            model_package_sha256=a['source_package_sha256'],expected_product='Exact signed32 times positive31 Python integer product',
            expected_INT8='Previously compiled C binary64 oracle for all model boundaries/neighbors; independent integer ties-even for generic edge/random cases')
        def run(label,args):
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict vendor diagnostics '+label)
            return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',MACRO,DSP,GLBL,rtl,tb])
        run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_requant_factor','glbl','-s','rqfactor_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','rqfactor_sim','-runall'])
        marker=re.findall(r'^REQUANT_FACTOR_PASS vectors=(\d+) received=(\d+) stalls=(\d+) invalid=(\d+) aborts=(\d+)$',text,re.M)
        check(len(marker)==1,'One full factor RTL marker')
        values=list(map(int,marker[0]));check(values[:2]==[n,n] and values[2]>0 and values[3:]==[1,2],'All numeric and protocol coverage')
        r['simulation']=dict(zip(('vectors','received','stalls','invalid','aborts'),values))
        tcl=build/'synth.tcl'
        tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+rtl.as_posix()+'}\nsynth_design -top z100_requant_factor -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nreport_timing_summary -file {'+(out/'timing_unplaced.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'factor.dcp').as_posix()+'}\nforeach pattern {DSP48E1 RAMB36E1 RAMB18E1 LDCE LDPE} {puts "FACTOR_CENSUS $pattern [llength [get_cells -hier -filter [format {REF_NAME == %s} $pattern]]]"}\nputs "FACTOR_CENSUS BLACKBOX [llength [get_cells -hier -filter {IS_BLACKBOX}]]"\nexit\n')
        text=run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        census={k:int(v) for k,v in re.findall(r'^FACTOR_CENSUS (\w+) (\d+)$',text,re.M)}
        check(census==dict(DSP48E1=3,RAMB36E1=0,RAMB18E1=0,LDCE=0,LDPE=0,BLACKBOX=0),'Exact3DSP zeroRAM/latch/blackbox census')
        util=(out/'utilization.rpt').read_text()
        def metric(n):return float(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*([\d.]+)',util,re.M)[1])
        r.update(status='PASS_PRIVATE_EXACT_FACTOR_ALL_CURRENT_C_BOUNDARIES_XSIM_THREE_DSP_OOC',primitive_counts=census,
            resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=3,BRAM36eq=0),
            factor_payload_bytes_for_all_channels=5419*8,old_threshold_payload_bytes=a['packed_bytes'],
            scope='One lane exact arithmetic/global stall tested on all current C boundary records plus edges/random. No32lane configuration/row/fullgraph/platform integration, routed timing or board performance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        r['source_sha256_before']=before;r['source_sha256_after']={rel(p):sha(p) for p in sources} if before else {}
        if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
        r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))

if __name__=='__main__':raise SystemExit(main())
