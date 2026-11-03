"""Direct CHW oracle for20site gather on the validated four-read store."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import argparse,hashlib,json,os,re,shutil,subprocess
from z100_feature_window_layout import FeatureLayout

ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026'
RTL=HW/'feature_window20_v1/z100_feature_window20.sv'
TB=HW/'feature_window20_v1/tb_z100_feature_window20.sv'
BANK=HW/'feature_banks_addressed_v1/z100_feature_banks_addressed.sv'
FOUR=HW/'feature_banks_4read_v4/z100_feature_banks_4read.sv'
PREREQ=ROOT/'validation/board_z100/feature_banks_4read_v4/20261024T095451.504289Z_f1d680b0/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(ok,msg):
    if not ok:raise ValueError(msg)


def fixture(build):
    c,h,w=7,8,640
    chw=bytes((ch*43+y*17+x*29+(x>>4)*7)&255 for ch in range(c) for y in range(h) for x in range(w))
    layout=FeatureLayout(c,h,w);packed=layout.pack(chw)
    addresses=[((sg*h+y)*40+xw) for y in range(h) for xw in range(40) for sg in range(2)]
    require(len(addresses)==640 and sorted(addresses)==list(range(640)),'Scatter geometry')
    (build/'load_addresses.hex').write_text(''.join(f'{a:04x}\n' for a in addresses))
    (build/'load_data.hex').write_text(''.join(f'{int.from_bytes(packed[a*64:(a+1)*64],"little"):0128x}\n' for a in addresses))
    desc=[];gold=[];maxread=0;active=0
    for stride in (1,2):
        ow=640//stride
        for oy in (0,1,3):
            for ky in range(3):
                iy=oy*stride+ky-1
                for kx in range(3):
                    for group in (0,1):
                        for ox,n in [(x,min(20,ow-x)) for x in range(0,ow,20)]+[(ow-3,3),(17,19),(0,1),(7,7),(13,16)]:
                            tag=0x42000000+len(desc);fx=ox*stride+kx-1
                            row=((group*h+(iy if 0<=iy<h else 0))*40)
                            mask=15 if group==0 else 7
                            fields=((77,32),(tag,32),(row,14),(fx&4095,12),(w,11),(ow-ox,11),
                                    (n,5),(mask,4),(stride==2,1),(0<=iy<h,1))
                            d=0
                            for value,bits in fields:d=(d<<bits)|int(value)
                            desc.append(d);data=0;vm=0;ports=Counter()
                            for lane in range(4):
                                ch=group*4+lane
                                for site in range(20):
                                    x=fx+site*stride;valid=site<n and ch<c and 0<=iy<h and 0<=x<w
                                    if valid:
                                        byte=chw[(ch*h+iy)*w+x];active+=1;vm|=1<<(lane*20+site)
                                        ports[(lane,x%16)]+=1
                                    else:byte=0
                                    data|=byte<<((lane*20+site)*8)
                            require(max(ports.values(),default=0)<=3,'20site needsmorethanthreeports')
                            maxread=max(maxread,max(ports.values(),default=0));gold.append((vm<<640)|data)
    require(maxread==3,'Third physical readport never needed')
    (build/'fixture_defs.vh').write_text(f'`define WINDOWS {len(desc)}\n')
    (build/'descriptors.hex').write_text(''.join(f'{d:031x}\n' for d in desc))
    (build/'golden.hex').write_text(''.join(f'{d:0180x}\n' for d in gold))
    return dict(windows=len(desc),bytes=len(desc)*80,active_bytes=active,max_reads_per_bank=maxread,
        CHW_sha256=hashlib.sha256(chw).hexdigest(),shape=[c,h,w],load_words=640,
        oracle='Direct CHW coordinates; no RTL slot mapping used as golden',
        fixture_sha256={p.name:sha(p) for p in build.iterdir() if p.is_file()})


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/fw20_bankv4'/stamp;build=ROOT/'build'/('fw20v4_'+stamp)
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    paths=(RTL,TB,BANK,FOUR,PREREQ,Path(__file__),ROOT/'tools/z100_feature_window_layout.py')
    before={str(p.relative_to(ROOT)):sha(p) for p in paths}
    d=dict(status='RUNNING',source_sha256_before=before,commands=[],board_access=False,
        production_integrated=False,full_pipeline_30fps_accepted=False)
    report=out/'result.json'
    try:
        pr=json.loads(PREREQ.read_text())
        require(pr['status']=='PASS_PRIVATE_FOUR_READ_FEATURE_BANK_XSIM_OOC_ONLY' and all(pr['mirror_cancel_seam'].values()),'4read registered cancel prerequisite')
        for name,value in pr['source_sha256_after'].items():
            require(sha(ROOT/name)==value,'4read prerequisite source drift')
        (out/'src').mkdir()
        for i,p in enumerate(paths):shutil.copyfile(p,out/'src'/f'{i:02d}{p.suffix}')
        d['fixture']=fixture(build);d['status']='PASS_PRIVATE_HOST_20SITE_FIXTURE_ONLY'
        if args.execute:
            env=dict(os.environ)
            for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[key]='1'
            def run(name,argv):
                argv=list(map(str,argv));p=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',
                    errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                (out/(name+'.log')).write_text(p.stdout)
                d['commands'].append(dict(name=name,argv=argv,return_code=p.returncode))
                require(p.returncode==0 and not re.search(r'^\s*(?:Fatal:|ERROR:)',p.stdout,re.M),name+' failed')
                return p.stdout
            run('xvlog',[VENDOR/'xvlog.bat','-sv','-i',build,BANK,FOUR,RTL,TB])
            run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_feature_window20','-s','fw20_sim'])
            text=run('xsim',[VENDOR/'xsim.bat','fw20_sim','-runall'])
            rows=re.findall(r'^FEATURE_WINDOW20_PASS windows=(\d+) bytes=(\d+) holds=(\d+) third_port_reads=(\d+) ii1_streak=(\d+) invalid=(\d+) cancels=(\d+) reset_reload=1$',text,re.M)
            require(len(rows)==1,'20site unique PASS marker')
            windows,bytecount,holds,third,streak,invalid,cancels=map(int,rows[0])
            require(windows==d['fixture']['windows'] and bytecount==windows*80 and holds>0 and third>0
                and streak>=2 and invalid==1 and cancels==2,'20site exact coverage')
            d['simulation']=dict(windows=windows,bytes=bytecount,holds=holds,third_port_reads=third,
                max_consecutive_results=streak,invalid_descriptors=invalid,cancels=cancels,reset_reload=True)
            d['status']='PASS_PRIVATE_20SITE_WINDOW_BANKV3_XSIM_ONLY'
    except Exception as exc:d.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        d['source_sha256_after']={str(p.relative_to(ROOT)):sha(p) for p in paths}
        if before!=d['source_sha256_after']:d.update(status='FAILED_SOURCE_INTEGRITY',error='Source mutation')
        d['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for base in (out,build) for p in base.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(d,indent=2)+'\n')
    print(json.dumps(dict(status=d['status'],report=str(report),error=d.get('error'))))
    return 0 if d['status'].startswith('PASS_') else 1


if __name__=='__main__':raise SystemExit(main())
