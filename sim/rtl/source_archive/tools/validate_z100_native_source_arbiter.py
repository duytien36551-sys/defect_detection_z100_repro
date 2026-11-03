"""Prepare/run actual source controller and AXI reader through real arbitration."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/native_source_read/20261025T061054.707595Z/result.json'
SUPPORT=HW/'native_slot_arbiter_v1/source_arbiter_support.vh';ARBITER=HW/'native_slot_arbiter_v1/z100_native_slot_arbiter.sv'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def stamp():return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
def prepare():
    runid=stamp();out=ROOT/'validation/board_z100/native_source_arbiter_prepared'/runid;out.mkdir(parents=True)
    build=ROOT/'build'/('nsra_'+runid[-14:]);build.mkdir(parents=True);before={}
    r=dict(status='PREPARING',board_access=False,vendor_tools_started=False,full_pipeline_30fps_accepted=False,production_integrated=False)
    try:
        proof=json.loads(PROOF.read_text());check(proof['status'].startswith('PASS_PRIVATE_SOURCE_READ'),'Closed actual physical reader prerequisite')
        for n,h in {**proof['source_sha256_after'],**proof['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Source binding '+n)
        oldtb=HW/'native_source_read_v1/tb_z100_native_source_read.sv';text=oldtb.read_text()
        def edit(a,b):
            nonlocal text
            check(text.count(a)==1,'Unique actual-source arbiter seam '+a[:55]);text=text.replace(a,b)
        edit('module tb_z100_native_source_read;','module tb_z100_native_source_arbiter;')
        start=text.index('    wire selected_host=hv;');end=text.index('    wire[6:0] committed_slots',start)
        text=text[:start]+'    `include "source_arbiter_support.vh"\n'+text[end:]
        start=text.index('        .cmd_valid(mv),');end=text.index('        .committed_slots(',start)
        text=text[:start]+'''        .cmd_valid(real_manager_valid),.cmd_ready(real_manager_ready),
        .cmd_opcode(selected_packet[2:0]),.cmd_slot(selected_packet[5:3]),.cmd_tag(selected_packet[37:6]),
        .cmd_epoch(selected_packet[69:38]),.cmd_generation(selected_packet[101:70]),.cmd_address(selected_packet[133:102]),
        .cmd_tensor_id(selected_packet[149:134]),.cmd_channels(selected_packet[160:150]),.cmd_height(selected_packet[170:161]),
        .cmd_width(selected_packet[180:171]),.cmd_first_row(selected_packet[190:181]),.cmd_tile_height(selected_packet[200:191]),.cmd_success(selected_packet[201]),
        .response_valid(rv),.response_ready(real_manager_response_ready),.response_tag(rt),.response_slot(rs),.response_code(rc),
'''+text[end:]
        # Preserve all original data and fault cases; only add measured arbiter coverage.
        edit('$finish;', '''
        if(arb_graph_replies<10||arb_source_replies<10||arb_active)$fatal(1,"Missing actual reader arbitration activity");
        $display("SOURCE_ARBITER_PASS graph_replies=%0d source_replies=%0d final_refs=%0d",arb_graph_replies,arb_source_replies,readers);
        $finish;''')
        tb=build/'tb_z100_native_source_arbiter.sv';tb.write_text(text);shutil.copyfile(SUPPORT,build/SUPPORT.name)
        rtl=[HW/n for n in ('native_tensor_slots_bounded_v2/z100_native_tensor_commit_bounded_v2.sv','native_tensor_slots_bounded_v2/z100_native_tensor_slots_bounded_v2.sv','native_axi64_reader_v1/z100_native_axi64_reader.sv','native_source_read_v1/z100_native_source_read.sv')]+[ARBITER,tb]
        before={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),PROOF,SUPPORT,oldtb,*rtl[:-1]]}
        r.update(status='PREPARED_UNEXECUTED_WAITING_FOR_VENDOR_SLOT',build=str(build.relative_to(ROOT)),rtl=[str(p.relative_to(ROOT)) for p in rtl],source_sha256_before=before,
            scope='Prepared source-control/real AXI reader/bounded manager test through actual three-client arbiter. All original data/abort/recovery cases preserved; host and source occupy two clients, third idle. No compile or simulation acceptance yet.')
    except Exception as exc:r.update(status='FAILED_PREPARATION_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_after']={n:sha(ROOT/n) for n in before};r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for p in build.iterdir() if p.is_file()}
    path=out/'result.json';path.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(path),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
def execute(report):
    pp=ROOT/report;p=json.loads(pp.read_text());check(p['status']=='PREPARED_UNEXECUTED_WAITING_FOR_VENDOR_SLOT','Preserved preparation')
    live=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-Process vivado -ErrorAction SilentlyContinue).Count"],capture_output=True,text=True);check(live.returncode==0,'Actual tool census')
    if int(live.stdout.strip())>=2:
        print(json.dumps(dict(status='DEFERRED_TWO_LIVE_VENDOR_FLOWS',vendor_tools_started=False,prepared_report=str(pp))));return 0
    for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Prepared source drift '+n)
    out=ROOT/'validation/board_z100/native_source_arbiter'/stamp();out.mkdir(parents=True);build=ROOT/p['build'];rp=out/'result.json'
    r=dict(status='RUNNING',commands=[],board_access=False,production_integrated=False,full_pipeline_30fps_accepted=False,prepared_report=str(pp.relative_to(ROOT)),prepared_report_sha256=sha(pp),source_sha256_before=p['source_sha256_after']);rp.write_text(json.dumps(r,indent=2)+'\n')
    try:
        def run(label,args):
            argv=list(map(str,args));done=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(done.stdout);r['commands'].append(dict(label=label,args=argv,return_code=done.returncode));check(done.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',done.stdout,re.M),'Actual strict tool completion '+label);return done.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*[ROOT/n for n in p['rtl']]])
        run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_source_arbiter','-s','source_arb_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','source_arb_sim','-runall'])
        def marker(name):
            rows=re.findall('^'+name+r' (.+)$',logs,re.M);check(len(rows)==1,'Complete '+name);return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',rows[0])}
        old=marker('SOURCE_READ_LEASE_PASS');sim=marker('SOURCE_ARBITER_PASS')
        check(old['successful_reads']==1 and old['recoveries']==15 and old['held_output_cycles']==10 and old['busy_release_rejections']==1 and old['final_refs']==0,'Preserved numeric/physical ownership/failure coverage')
        check(sim['graph_replies']>=10 and sim['source_replies']>=10 and sim['final_refs']==0,'Actual two producers through production arbiter')
        r.update(status='PASS_PRIVATE_ACTUAL_SOURCE_READ_REAL_ARBITER_MANAGER_AXI_DRAIN15_RECOVERIES_XSIM_ONLY',simulation=sim,source_simulation=old,
            scope='Actual three-client arbiter replaces old test mux on graph/source manager requests; third client idle. Frozen numeric data, ownership-before-AR, physical drain and15 fault recoveries retained. No full input cache/gather, graph pixels, OOC, HP platform or board FPS acceptance.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_after']={n:sha(ROOT/n) for n in p['source_sha256_after']}
    if r['source_sha256_before']!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=rp}
    rp.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(rp),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute-prepared');args=parser.parse_args()
    raise SystemExit(execute(args.execute_prepared) if args.execute_prepared else prepare())
