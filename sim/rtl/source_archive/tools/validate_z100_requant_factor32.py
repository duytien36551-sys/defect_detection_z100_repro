"""32-lane exact factor configuration/metadata/tails/fault/II1 acceptance."""
from pathlib import Path
from datetime import datetime,timezone
import bisect,hashlib,json,os,random,re,shutil,struct,subprocess
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026'
OWN=HW/'requant_factor32_v1'
SURVEY=ROOT/'validation/board_z100/exact_requant_factor_survey/20261024T115605.743100Z/result.json'
MICRO=ROOT/'validation/board_z100/requant_factor_v1/20261024T120055.400888Z/result.json'
ASSET=ROOT/'validation/board_z100/current_requant_tables/20261024T105738.290964Z_37e400a8/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok,msg):
    if not ok:raise ValueError(msg)
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/requant_factor32_v1'/stamp;build=ROOT/'build'/('rqf32_'+stamp[-14:])
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    rtl=[HW/'requant_factor_v1/z100_requant_factor.sv',OWN/'z100_requant_factor32.sv'];tb=OWN/'tb_z100_requant_factor32.sv'
    macro=VENDOR.parent/'data/verilog/src/unimacro/MULT_MACRO.v';dsp=VENDOR.parent/'data/verilog/src/unisims/DSP48E1.v';glbl=VENDOR.parent/'data/verilog/src/glbl.v'
    sources=[Path(__file__),*rtl,tb,SURVEY,MICRO,ASSET]
    before={};r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    report=out/'result.json'
    try:
        micro=read(MICRO);check(micro['status']=='PASS_PRIVATE_EXACT_FACTOR_ALL_CURRENT_C_BOUNDARIES_XSIM_THREE_DSP_OOC','Full actual micro boundary proof')
        for n,h in {**micro['source_sha256_after'],**micro['artifact_sha256']}.items():check(sha(resolve(n))==h,'Micro binding '+n)
        s,a=read(SURVEY),read(ASSET);keyfile=next(ROOT/n for n in a['artifact_sha256'] if Path(n).name=='thresholds_254_i64.bin')
        sources.append(keyfile);before={str(p.relative_to(ROOT)):sha(p) for p in sources}
        keys=[v[0] for v in struct.iter_unpack('<q',keyfile.read_bytes())]
        factors=s['factors'];rare=[p for p in factors if p['selected']['bits']==31];counts=(1,3,16,31,32);per=1000;nv=nl=0
        with (build/'vectors.hex').open('w') as vf,(build/'factors.hex').open('w') as ff,(build/'lanes.hex').open('w') as lf:
            for case,lanes in enumerate(counts):
                lf.write(f'{lanes:02x}\n');selected=[factors[(case*997+j*53)%5419] for j in range(lanes)]
                if lanes==32:selected[:len(rare)]=rare
                samples=[]
                for p in selected:
                    m=p['selected'];ff.write(f'{m["multiplier"]|(m["shift"]<<31):010x}\n')
                    table=keys[p['index']*254:(p['index']+1)*254]
                    samples.append((table,sorted({-(1<<31),(1<<31)-1,0}|{x+d for x in table for d in (-1,0,1) if -(1<<31)<=x+d<(1<<31)})))
                for v in range(per):
                    data=expected=0
                    for lane,(table,probes) in enumerate(samples):
                        raw=probes[(v+lane*17)%len(probes)]
                        data|=(raw&0xffffffff)<<(lane*32);expected|=((bisect.bisect_right(table,raw)-127)&255)<<(lane*8)
                    vf.write(f'{expected:064x}{data:0256x}\n');nv+=1;nl+=lanes
        (build/'fixture_defs.vh').write_text(f'`define CASES 5\n`define PER_CASE {per}\n`define VECTORS {nv}\n`define FACTORS {sum(counts)}\n`define LANE_VALUES {nl}\n')
        r['fixture']=dict(cases=list(counts),vectors=nv,lane_values=nl,rare31bit_channels=[p['index'] for p in rare],oracle='C-verified transition tables; inactive output lanes zero')
        for p in (*rtl,tb,Path(__file__)):shutil.copy2(p,out/p.name)
        def run(label,args):
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict diagnostic '+label)
            return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',macro,dsp,glbl,*rtl,tb])
        run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_requant_factor32','glbl','-s','rqfactor32_sim'])
        text=run('xsim',[VENDOR/'xsim.bat','rqfactor32_sim','-runall'])
        marker=re.findall(r'^REQUANT_FACTOR32_PASS (.+)$',text,re.M);check(len(marker)==1,'Complete vector marker')
        values={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',marker[0])}
        check(all(values[k]==v for k,v in dict(cases=5,vectors=nv,lane_values=nl,cfg_errors=6,input_errors=1,aborts=2).items()) and values['stalls']>0 and values['max_ii1']>=20,'Complete vector and fault coverage')
        r['simulation']=values
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\n'+''.join('read_verilog -sv {'+p.as_posix()+'}\n' for p in rtl)+'synth_design -top z100_requant_factor32 -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nwrite_checkpoint -force {'+(build/'factor32.dcp').as_posix()+'}\nforeach pat {DSP48E1 RAMB36E1 RAMB18E1 LDCE LDPE} {puts "FACTOR32_CENSUS $pat [llength [get_cells -hier -filter [format {REF_NAME == %s} $pat]]]"}\nputs "FACTOR32_CENSUS BLACKBOX [llength [get_cells -hier -filter {IS_BLACKBOX}]]"\nexit\n')
        text=run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        census={k:int(v) for k,v in re.findall(r'^FACTOR32_CENSUS (\w+) (\d+)$',text,re.M)}
        check(census==dict(DSP48E1=96,RAMB36E1=0,RAMB18E1=0,LDCE=0,LDPE=0,BLACKBOX=0),'Actual full32lane96DSP mapping')
        util=(out/'utilization.rpt').read_text()
        def metric(n):return int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        r.update(status='PASS_PRIVATE_FACTOR32_CONFIG_METADATA_TAILS_FAULTS_XSIM_96DSP_OOC',primitive_counts=census,
            resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),DSP=96,BRAM36eq=0),
            scope='Actual32lane datapath with1/3/16/31/32lane configs, exact model table outputs and protocol recovery. No fullgraph, route, DDR, physical or FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        r['source_sha256_before']=before;r['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in sources} if before else {}
        if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
        r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))

if __name__=='__main__':raise SystemExit(main())
