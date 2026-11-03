"""Replay all graph-root lifetimes through seven real RTL commit contexts."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import hashlib,json,os,re,subprocess

ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PLAN=ROOT/'validation/board_z100/native_tensor_lifetimes/20261025T052917.142448Z/result.json'
GRAPH=ROOT/'deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline/model/graph.json'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check(ok,msg):
    if not ok:raise ValueError(msg)


def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/native_tensor_slots'/stamp;build=ROOT/'build'/('nts_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True);report=out/'result.json';before={}
    result=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False,production_integrated=False)
    try:
        plan=json.loads(PLAN.read_text());graph=json.loads(GRAPH.read_text())
        check(plan['status'].startswith('PASS_HOST_ALL163') and len(plan['events'])==73,'Closed complete lifetime plan')
        for n,h in plan['source_sha256'].items():check(sha(ROOT/n)==h,'Lifetime source drift '+n)
        nodes={n['id']:n for n in graph['nodes']}
        slots=[dict(active=False,pub=False,fault=False,refs=0,epoch=0,gen=0,address=0,id=0,c=0,h=0,w=0,rows=set(),pending=None,last=(0,0)) for _ in range(7)]
        commands=[];expected=[];codes=Counter();operations=Counter()
        def fields(s):return dict(e=s['epoch'],g=s['gen'],tensor=s['id'])
        def command(op,slot,e=200,g=0,tensor=0,address=0,c=0,h=0,w=0,first=0,th=0,success=True,quiet=127,want=None):
            valid=slot<7;code=0;s=slots[slot] if valid else None
            key=valid and (e,g,tensor)==(s['epoch'],s['gen'],s['id'])
            idle=bool(quiet&(1<<slot)) if valid else False
            if not valid:code=1
            elif op==0:
                if s['active'] or not idle:code=3
                else:
                    words=((c+3)//4)*h*((w+15)//16)
                    good=e!=0 and g!=0 and (e,g)>s['last'] and address%64==0 and 0<c<=1024 and 0<h<=640 and 0<w<=640 and address+words*64<=2**32
                    if not good:s.update(active=True,fault=True,pub=False);code=4
                    else:s.update(active=True,fault=False,pub=False,epoch=e,gen=g,address=address,id=tensor,c=c,h=h,w=w,rows=set(),pending=None,last=(e,g))
            elif op==1:
                if not s['active'] or s['pub'] or s['fault'] or s['pending'] is not None or not idle:code=3
                elif not key or th==0 or first+th>s['h'] or set(range(first,first+th))&s['rows']:s.update(fault=True,pub=False);code=4
                else:s['pending']=(first,th)
            elif op==2:
                if not s['active'] or s['pub'] or s['fault'] or not idle:code=3
                elif not key or not success or s['pending']!=(first,th):s.update(fault=True,pub=False);code=4
                else:
                    s['rows'].update(range(first,first+th));s['pending']=None;s['pub']=len(s['rows'])==s['h']
            elif op==3:
                if not key:code=2
                elif not s['pub']:code=7
                elif s['refs']==255:code=5
                else:s['refs']+=1
            elif op==4:
                if not key:code=2
                elif s['refs']==0:code=6
                elif not idle:code=3
                else:s['refs']-=1
            elif op==5:
                if not key:code=2
                elif not s['pub'] or s['refs'] or not idle:code=3
                else:s.update(active=False,pub=False,rows=set(),pending=None)
            elif op==6:
                if not key:code=2
                elif not s['active']:code=7
                else:s.update(fault=True,pub=False)
            elif op==7:
                if not key:code=2
                elif not s['fault']:code=7
                elif not idle or s['refs']:code=3
                else:s.update(active=False,fault=False,pub=False,rows=set(),pending=None)
            if want is not None:check(code==want,'Independent test model expected code')
            tag=len(commands)+1
            commands.append(op|slot<<3|tag<<6|e<<38|g<<70|address<<102|tensor<<134|c<<150|h<<161|w<<171|first<<181|th<<191|int(success)<<201|quiet<<202)
            active=sum(int(x['active'])<<i for i,x in enumerate(slots));pub=sum(int(x['pub'])<<i for i,x in enumerate(slots));fault=sum(int(x['fault'])<<i for i,x in enumerate(slots))
            snapshot=code
            if valid:
                size=((s['c']+3)//4)*s['h']*((s['w']+15)//16)*64
                snapshot|=int(s['active'])<<4|int(s['pub'])<<5|int(s['fault'])<<6|s['refs']<<7|s['epoch']<<15|s['gen']<<47|s['address']<<79|size<<111|s['id']<<143|s['c']<<159|s['h']<<170|s['w']<<180|len(s['rows'])<<190
            snapshot|=active<<201|pub<<208|fault<<215;expected.append(snapshot);codes[code]+=1;operations[op]+=1
        def allocate(slot,node,generation):
            _,c,h,w=graph['input_shape'] if node==-1 else nodes[node]['shape'];addr=0x10000000+slot*0x400000
            command(0,slot,g=generation,tensor=node&65535,address=addr,c=c,h=h,w=w,want=0)
        def finish_tiles(slot):
            s=slots[slot];chunks=[(first,min(31,s['h']-first)) for first in range(0,s['h'],31)]
            for first,height in reversed(chunks):
                command(1,slot,**fields(s),first=first,th=height,want=0)
                command(2,slot,**fields(s),first=first,th=height,quiet=127^(1<<slot),want=3)
                command(2,slot,**fields(s),first=first,th=height,want=0)
        allocate(0,-1,1);finish_tiles(0)
        for event in plan['events']:
            for read in event['reads']:
                s=slots[read['slot']];check(s['id']==read['node']&65535 and s['gen']==read['generation'] and s['pub'],'Read source from actual topological lifetime')
                command(3,read['slot'],**fields(s),want=0)
                command(5,read['slot'],**fields(s),want=3)
            if event['materialized_node'] is not None:
                dest=event['reserve_destination'];allocate(dest['slot'],event['materialized_node'],dest['generation']);finish_tiles(dest['slot'])
            for read in event['reads']:command(4,read['slot'],**fields(slots[read['slot']]),want=0)
            for released in event['release_after_job_and_io_readers_quiescent']:command(5,released['slot'],**fields(slots[released['slot']]),want=0)
        check(not any(s['active'] or s['refs'] for s in slots),'All graph metadata destinations retired')
        graph_commands=len(commands)
        # Independent adverse reference/state cases beyond normal graph replay.
        command(0,0,e=201,g=1000,tensor=42,address=0x10000000,c=4,h=1,w=16,want=0)
        command(3,0,**fields(slots[0]),want=7)
        command(1,0,**fields(slots[0]),first=0,th=1,want=0);command(2,0,**fields(slots[0]),first=0,th=1,want=0)
        command(1,0,**fields(slots[0]),first=0,th=1,want=3)
        command(2,0,**fields(slots[0]),first=0,th=1,want=3)
        command(3,7,e=201,g=1000,tensor=42,want=1)
        command(3,0,e=200,g=1000,tensor=42,want=2);command(3,0,e=201,g=999,tensor=42,want=2);command(3,0,e=201,g=1000,tensor=43,want=2)
        for _ in range(255):command(3,0,**fields(slots[0]),want=0)
        command(3,0,**fields(slots[0]),want=5);command(5,0,**fields(slots[0]),want=3)
        command(4,0,**fields(slots[0]),quiet=126,want=3);command(6,0,**fields(slots[0]),want=0)
        command(7,0,**fields(slots[0]),want=3)
        for _ in range(255):command(4,0,**fields(slots[0]),want=0)
        command(4,0,**fields(slots[0]),want=6);command(7,0,**fields(slots[0]),quiet=126,want=3);command(7,0,**fields(slots[0]),want=0)
        command(0,0,e=201,g=1000,tensor=42,address=0x10000000,c=4,h=1,w=16,want=4);command(7,0,**fields(slots[0]),want=0)
        command(0,0,e=201,g=1001,tensor=42,address=0x10000000,c=4,h=2,w=16,want=0)
        command(1,0,**fields(slots[0]),first=0,th=1,want=0)
        command(2,0,e=201,g=1002,tensor=42,first=0,th=1,want=4);command(7,0,**fields(slots[0]),want=0)
        command(0,0,e=201,g=1002,tensor=42,address=0x10000000,c=4,h=2,w=16,want=0)
        command(1,0,**fields(slots[0]),first=0,th=1,want=0);command(2,0,**fields(slots[0]),first=0,th=1,want=0)
        command(1,0,**fields(slots[0]),first=0,th=1,want=4);command(7,0,**fields(slots[0]),want=0)
        (build/'commands.hex').write_text(''.join(f'{x:064x}\n' for x in commands));(build/'expected.hex').write_text(''.join(f'{x:064x}\n' for x in expected))
        (build/'slot_defs.vh').write_text(f'`define SLOT_COMMANDS {len(commands)}\n')
        rtl=[HW/n for n in ('native_tensor_commit_v1/z100_native_tensor_commit.sv','native_tensor_slots_v1/z100_native_tensor_slots.sv','native_tensor_slots_v1/tb_z100_native_tensor_slots.sv')]
        before={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),PLAN,GRAPH,*rtl)}
        result.update(source_sha256_before=before,source_package_sha256=plan['source_package_sha256'],fixture=dict(commands=len(commands),graph_commands=graph_commands,response_codes=dict(codes),opcodes=dict(operations),scope='Metadata only. Source-upload and B-complete events are test stimulus here; physical IO binding separately verified in actual compute publication test.4MiB-spaced slot addresses are fixture regions, not a DDR allocator.'))
        report.write_text(json.dumps(result,indent=2)+'\n')
        def run(label,args):
            argv=list(map(str,args));env=dict(os.environ,XILINX_LOCAL_USER_DATA='no')
            proc=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);result['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Actual strict diagnostic '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_tensor_slots','-s','slots_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','slots_sim','-runall']);rows=re.findall(r'^TENSOR_SLOTS_PASS (.+)$',logs,re.M);check(len(rows)==1,'Complete seven-slot replay')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',rows[0])}
        check(sim==dict(commands=len(commands),replies=len(commands),response_hold_cycles=len(commands)*5,peak_live_slots=7,graph_events=73,materialized_results=72),'Every queued response, held identity and complete lifecycle replay')
        result.update(status='PASS_PRIVATE_SEVEN_TENSOR_SLOTS_ALL163_NODE_ROOT_LIFETIMES_READ_LEASES_ERROR_REPLIES_XSIM_ONLY',simulation=sim,
            scope='Seven real row-coverage/version ledgers, queued command/reply plane and saturating read references. All73 graph-root events plus invalid slot/state/key, overflow/underflow, failed/old completion, overlap, abort, busy release/recovery and response backpressure. Synthetic metadata events; no actual fullgraph MAC/DDR allocator/read producer or physical FPS acceptance.')
    except Exception as exc:result.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    result['source_sha256_before']=before;result['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=result['source_sha256_after']:result.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    result['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(status=result['status'],report=str(report),error=result.get('error'))));return int(result['status'].startswith('FAILED'))


if __name__=='__main__':raise SystemExit(main())
