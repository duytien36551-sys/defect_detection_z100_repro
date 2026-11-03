"""Private V8 window payload reset split: unchanged bank ownership/cancel oracle."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';NEW=HW/'feature_writepipe_v7';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
COMPUTE=ROOT/'validation/board_z100/shared_compute_rowbase_v6/20261025T055628.412110Z/result.json'
REPLACE={
 'z100_feature_banks_load_order_4k_v4.sv':'z100_feature_banks_writepipe_4k_v5.sv',
 'z100_feature_banks_4read_load_order_4k_v4.sv':'z100_feature_banks_4read_writepipe_4k_v5.sv',
 'z100_feature_banks_pingpong_shared_v5.sv':'z100_feature_banks_pingpong_writepipe_v7.sv',
 'z100_feature_window20_shared_decode_4k_v5.sv':'z100_feature_window20_writepipe_v7.sv',
 'z100_native_row20_shared_pool_rowbase_v6.sv':'z100_native_row20_shared_pool_writepipe_v7.sv'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['ownership'],required=True);args=parser.parse_args()
    live=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-Process vivado -ErrorAction SilentlyContinue).Count"],capture_output=True,text=True);check(live.returncode==0 and int(live.stdout.strip())<2,'At most two vendor flows')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/('validation/board_z100/feature_payload_v8_'+args.suite)/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('fwp_'+args.suite+'_'+stamp[-14:]);build.mkdir(parents=True);report=out/'result.json';before={}
    r=dict(status='RUNNING',suite=args.suite,commands=[],board_access=False,production_integrated=False,full_pipeline_30fps_accepted=False,route_or_frequency_accepted=False)
    try:
        sources=[Path(__file__)];fixtures=[]
        leaf=NEW/REPLACE['z100_feature_banks_load_order_4k_v4.sv'];four=NEW/REPLACE['z100_feature_banks_4read_load_order_4k_v4.sv']
        if args.suite=='unit':rtl=[leaf,NEW/'tb_z100_feature_writepipe.sv'];top='tb_z100_feature_writepipe';marker='FEATURE_WRITEPIPE_PASS'
        elif args.suite=='boundary':rtl=[leaf,four,NEW/'tb_z100_banks_writepipe_boundary.sv'];top='tb_z100_banks_writepipe_boundary';marker='BANKS4K_BOUNDARY_PASS'
        elif args.suite=='ownership':
            original=HW/'feature_window20_shared_decode_4k_v5/tb_z100_shared_decode_ownership.sv';sources.append(original)
            text=original.read_text().replace('module tb_z100_shared_decode_ownership;','module tb_z100_shared_writepipe_ownership;').replace('z100_feature_window20_shared_decode_4k_v5 dut','z100_feature_window20_payload_v8 dut')
            tb=build/'tb_z100_shared_writepipe_ownership.sv';tb.write_text(text)
            rtl=[leaf,four,NEW/REPLACE['z100_feature_banks_pingpong_shared_v5.sv'],HW/'feature_payload_v8/z100_feature_window20_payload_v8.sv',tb]
            top='tb_z100_shared_writepipe_ownership';marker='SHARED_DECODE_OWNERSHIP_PASS'
        else:
            p=json.loads(COMPUTE.read_text());check(p['status']=='PASS_PRIVATE_ROWBASE_V6_SHARED_CONV_POOL_RETAINED_CONV_AXI_DDR_PARITY_XSIM_ONLY','Closed current actual compute/DDR proof')
            for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(resolve(n))==h,'Closed compute source/artifact '+n)
            original=[Path(n) for n in p['commands'][0]['args'][2:]];oldtb=next(s for s in original if s.name=='tb_z100_shared_compute_writeback.sv');sources.extend([COMPUTE,oldtb])
            rtl=[NEW/REPLACE[s.name] if s.name in REPLACE else s for s in original if s!=oldtb]
            for s in oldtb.parent.iterdir():
                if s.suffix in ('.hex','.vh'):fixtures.append(s);shutil.copyfile(s,build/s.name)
            text=oldtb.read_text().replace('module tb_z100_shared_compute_writeback;','module tb_z100_shared_compute_writepipe;').replace('z100_native_row20_shared_pool_rowbase_v6 #(','z100_native_row20_shared_pool_writepipe_v7 #(')
            tb=build/'tb_z100_shared_compute_writepipe.sv';tb.write_text(text);rtl.append(tb);top='tb_z100_shared_compute_writepipe';marker='SHARED_COMPUTE_WRITEBACK_PASS'
            r['source_package_sha256']=p['source_package_sha256']
        sources.extend([*rtl,*fixtures]);before={str(s.relative_to(ROOT)) if s.is_relative_to(ROOT) else 'external/'+s.as_posix().replace(':',''):sha(s) for s in sources};r['source_sha256_before']=before
        report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,argv):
            av=list(map(str,argv));proc=subprocess.run(av,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=av,return_code=proc.returncode));check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Actual strict tool completion '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2',top,'-s','writepipe_sim']);logs=run('xsim',[VENDOR/'xsim.bat','writepipe_sim','-runall'])
        rows=re.findall('^'+marker+r' (.+)$',logs,re.M);check(len(rows)==1,'Unique complete '+marker);sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',rows[0])}
        expected={
          'unit':dict(accepted=7,physical_writes=6,commit_with_pending=2,cancel_pending=1,checked_bytes=512,rejected_words=2),
          'boundary':dict(modes=2,words=8192,read_bytes=2097152,guards=6,held_cycles=468,address_bits=13,physical_depth=4096),
          'ownership':dict(writes=12,value_mask_checks=240,held_cycles=14,overwrite_blocks=8,simultaneous_begin_window=1,cancel_flushes=2),
          'compute':dict(jobs=3,packed_words=1440,DDR_beats_verified=11520,AXI_AW=720,AXI_W=11520,AXI_B=720,guards_checked=54016,publication_after_B=3)}
        check(sim==expected[args.suite],'Exact frozen '+args.suite+' coverage')
        r.update(status='PASS_PRIVATE_FEATURE_PAYLOAD_V8_'+args.suite.upper()+'_XSIM_ONLY',simulation=sim,
            scope='Only V8 window payload reset and enable split with unchanged V7 banks. Original ownership oracle checks simultaneous other-bank load/read, held A and queued B metadata stability, overwrite exclusion, cancellation with pending/held response, reload and exact pixel/mask data. Not compute, mapped resources, timing or physical FPS.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(resolve(n)) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(s.relative_to(ROOT)):sha(s) for folder in (out,build) for s in folder.rglob('*') if s.is_file() and s!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
