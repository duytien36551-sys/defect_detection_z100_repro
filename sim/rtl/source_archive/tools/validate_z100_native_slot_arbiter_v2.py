"""Prepare then run real three-client arbitration plus all1587 manager events.

Default preparation starts no vendor process. Execute a preserved preparation
with --execute-prepared RELATIVE_REPORT when fewer than two Vivado flows live.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/native_tensor_slots_bounded_v2/20261025T054420.119171Z/result.json'
SUPPORT=HW/'native_slot_arbiter_v1/slot_arbiter_support_v2.vh'
ARBITER=HW/'native_slot_arbiter_v1/z100_native_slot_arbiter.sv'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def stamp():return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
def prepare():
    runid=stamp();out=ROOT/'validation/board_z100/native_slot_arbiter_prepared_v2'/runid;out.mkdir(parents=True)
    build=ROOT/'build'/('nsa_'+runid[-14:]);build.mkdir(parents=True);before={}
    r=dict(status='PREPARING',board_access=False,vendor_tools_started=False,full_pipeline_30fps_accepted=False,production_integrated=False)
    try:
        p=json.loads(PROOF.read_text());check(p['status'].startswith('PASS_PRIVATE_MODEL_BOUNDED'),'Closed real model bounded manager prerequisite')
        check(p['simulation']['commands']==1587,'Complete frozen graph metadata and faults')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Frozen manager binding '+n)
        oldtb=HW/'native_tensor_slots_bounded_v2/tb_z100_native_tensor_slots_bounded_v2.sv'
        fixture=[]
        for basename in ('commands.hex','expected.hex','slot_defs.vh'):
            src=next(ROOT/n for n in p['artifact_sha256'] if Path(n).name==basename);fixture.append(src);shutil.copyfile(src,build/basename)
        shutil.copyfile(SUPPORT,build/SUPPORT.name)
        text=oldtb.read_text()
        def edit(a,b):
            nonlocal text
            check(text.count(a)==1,'Unique arbiter integration seam '+a[:50]);text=text.replace(a,b)
        edit('module tb_z100_native_tensor_slots_bounded_v2;','module tb_z100_native_slot_arbiter;')
        edit('    z100_native_tensor_slots_bounded_v2 dut(.*);','    `include "slot_arbiter_support_v2.vh"')
        edit('repeat(5)@(negedge clk);rst_n=1;','repeat(5)@(negedge clk);rst_n=1;@(negedge clk);concurrent_round(0);concurrent_round(1);concurrent_round(2);')
        edit('cmd_success=commands[i][201];','client_id=(cmd_opcode==3||cmd_opcode==4)?1:(cmd_opcode==1||cmd_opcode==2)?2:0;cmd_success=commands[i][201];')
        edit('            do @(negedge clk);while(!response_valid);', '''            if(i==50)begin
                do @(negedge clk);while(!mrv);fault_shim=1;
                repeat(4)@(negedge clk);fault_shim=0;
            end
            do @(negedge clk);while(!response_valid);''')
        edit('        $finish;', '''        if(!arb_fault||mismatch_checks<3||concurrent_replies!=9||manager_accepts!=`SLOT_COMMANDS+9||manager_stalls<100||arb_active)
            $fatal(1,"Incomplete arbitration/foreign reply coverage");
        $display("SLOT_ARBITER_PASS commands=%0d concurrent_replies=%0d manager_accepts=%0d manager_stalls=%0d mismatch_checks=%0d final_refs=0",`SLOT_COMMANDS,concurrent_replies,manager_accepts,manager_stalls,mismatch_checks);
        $finish;''')
        tb=build/'tb_z100_native_slot_arbiter.sv';tb.write_text(text)
        rtl=[HW/'native_tensor_slots_bounded_v2/z100_native_tensor_commit_bounded_v2.sv',HW/'native_tensor_slots_bounded_v2/z100_native_tensor_slots_bounded_v2.sv',ARBITER,tb]
        before={str(s.relative_to(ROOT)):sha(s) for s in [Path(__file__),PROOF,SUPPORT,oldtb,*fixture,*rtl[:-1]]}
        r.update(status='PREPARED_UNEXECUTED_WAITING_FOR_VENDOR_SLOT',build=str(build.relative_to(ROOT)),rtl=[str(s.relative_to(ROOT)) for s in rtl],
                 commands=1587,concurrent_rounds=3,source_sha256_before=before,
                 scope='Prepared real RTL three-client arbiter plus seven-slot manager metadata replay. No compile, simulation, resource or functional acceptance yet; no actual source-reader/compute writeback connections or board inference.')
    except Exception as exc:r.update(status='FAILED_PREPARATION_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for p in build.iterdir() if p.is_file()}
    report=out/'result.json';report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
def execute(report):
    prep_path=ROOT/report;prep=json.loads(prep_path.read_text());check(prep['status']=='PREPARED_UNEXECUTED_WAITING_FOR_VENDOR_SLOT','Explicit preserved preparation')
    # Read actual live handles; a stale status.json alone is not a slot.
    census=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-Process vivado -ErrorAction SilentlyContinue).Count"],capture_output=True,text=True)
    check(census.returncode==0,'Authoritative vendor process census')
    if int(census.stdout.strip())>=2:
        print(json.dumps(dict(status='DEFERRED_TWO_LIVE_VENDOR_FLOWS',prepared_report=str(prep_path),vendor_tools_started=False)));return 0
    for n,h in {**prep['source_sha256_after'],**prep['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Prepared source/artifact drift '+n)
    out=ROOT/'validation/board_z100/native_slot_arbiter_v2'/stamp();out.mkdir(parents=True)
    build=ROOT/prep['build'];r=dict(status='RUNNING',commands=[],board_access=False,production_integrated=False,full_pipeline_30fps_accepted=False,
        prepared_report=str(prep_path.relative_to(ROOT)),prepared_report_sha256=sha(prep_path),source_sha256_before=prep['source_sha256_after'])
    rp=out/'result.json';rp.write_text(json.dumps(r,indent=2)+'\n')
    try:
        def run(label,args):
            argv=list(map(str,args));proc=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode));check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual vendor completion '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*[ROOT/n for n in prep['rtl']]])
        run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_slot_arbiter','-s','arb_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','arb_sim','-runall'])
        rows=re.findall(r'^SLOT_ARBITER_PASS (.+)$',logs,re.M);check(len(rows)==1,'Complete arbitration simulation marker')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',rows[0])}
        check(sim['commands']==1587 and sim['concurrent_replies']==9 and sim['manager_accepts']==1596 and sim['manager_stalls']>100 and sim['mismatch_checks']>=3,'Actual full arbitration coverage')
        r.update(status='PASS_PRIVATE_THREE_CLIENT_ARBITER_REAL_SEVEN_SLOT_MANAGER1587_EVENTS_BACKPRESSURE_FOREIGN_REPLY_XSIM_ONLY',simulation=sim,
                 scope='Actual control arbitration/real bounded manager. Three simultaneous client rounds use identical tags and invalid slot7 with independent payloads; complete1587 graph metadata/adverse requests follow. Full packet stability, exclusive reply owner, downstream/upstream backpressure and foreign reply rejection verified. No physical source-reader/compute producer, fullgraph pixel, OOC, routed clock or board FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_after']={n:sha(ROOT/n) for n in prep['source_sha256_after']}
    if r['source_sha256_before']!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=rp}
    rp.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(rp),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute-prepared');args=parser.parse_args()
    raise SystemExit(execute(args.execute_prepared) if args.execute_prepared else prepare())
