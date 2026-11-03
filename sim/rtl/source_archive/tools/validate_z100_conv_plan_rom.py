"""Build and validate model-bound synthesizable metadata ROM from C halo proof."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,re,struct,subprocess
ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026/conv_plan_rom_v1'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/native_row_commands_v2/20261025T062641.961558Z/result.json'
PACKAGE=ROOT/'deployment/candidates/pin640/quant_candidates/epoch200_head_concat_20261024T103836.103919Z/package/MODEL.V8P'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prepare-only',action='store_true');a=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/conv_plan_rom'/stamp;build=ROOT/'build'/('cpr_'+stamp[-14:]);out.mkdir(parents=True);build.mkdir(parents=True)
    report=out/'result.json';before={};r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(PROOF.read_text());require(p['rows']==7220 and p['tiles']==189 and p['execution_return_code']==0,'Executed current C oracle')
        require(p['source_sha256_before']==p['source_sha256_after'],'Stable oracle')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():require(sha(ROOT/n)==h,'Oracle artifact '+n)
        require(sha(PACKAGE)==p['source_package_sha256']=='65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c','Frozen model binding')
        require(struct.unpack_from('<I',PACKAGE.read_bytes(),12)[0]==2213989717,'Model CRC identity')
        header=ROOT/p['generated_plan'];bindings=header.parent/'row_bindings.json';j=json.loads(bindings.read_text())['tiles']
        g=[[int(v) for v in row.split(',')] for row in re.findall(r'\{([\d,]+)\}',header.read_text().split('z100_halos[189]={')[1].split('};')[0])]
        require(len(g)==len(j)==189,'Complete C plan')
        event_map=[0]*256;records=[0]*256;expected=[];events=[];runs_total=0;windows_total=0
        for i,(geometry,tile) in enumerate(zip(g,j)):
            event=tile['event'];require(0<event<163 and tile['tile']==i and len(geometry)==13,'Valid actual Conv event')
            if not events or events[-1]!=event:require(event not in events,'Contiguous event group');events.append(event)
            indices=[k for k,v in enumerate(j) if v['event']==event];first=indices[0];count=len(indices);local=i-first
            require(indices==list(range(first,first+count)) and count<=189,'Contiguous tiles')
            ids=tile['parameter_jobs'];require(ids==list(range(ids[0],ids[0]+len(ids))) and len(ids)==(geometry[9]+31)//32,'Resident output group indices')
            require(geometry[5]==tile['first_output_row'] and geometry[6]==tile['output_rows'],'C halo binding')
            require(all(0<=x<65536 for x in geometry),'Geometry field widths')
            runs=((geometry[9]+31)//32)*geometry[6]*((geometry[8]+19)//20);windows=runs*((geometry[0]+3)//4)*geometry[10]*geometry[10]
            require(0<runs<=windows<1<<32 and ids[0]<65536,'Descriptor counts')
            packed=sum(v<<(16*k) for k,v in enumerate(geometry))
            record=windows|(runs<<32)|(ids[0]<<64)|(packed<<80)|(count<<288)|(local<<296)|(event<<304)
            require(record<1<<312,'Reserved bits remain zero');records[i]=record;event_map[event]=(count<<8)|first
            # Independent unpacked test oracle: raw C fields, not a copied ROM.
            expected+=geometry+[event,local,count,ids[0]];runs_total+=runs;windows_total+=windows
        require(len(events)==63 and runs_total==26380 and windows_total==1659840,'Complete model counts')
        (build/'conv_event_map.hex').write_text(''.join(f'{v:04x}\n' for v in event_map))
        (build/'conv_tiles.hex').write_text(''.join(f'{v:080x}\n' for v in records))
        (build/'expected_plan.hex').write_text(''.join(f'{v:08x}\n' for v in expected))
        rtl=[HW/'z100_conv_plan_rom.sv',HW/'tb_z100_conv_plan_rom.sv'];sources=[Path(__file__),PROOF,header,bindings,PACKAGE,*rtl]
        before={str(v.relative_to(ROOT)):sha(v) for v in sources};r.update(source_sha256_before=before,tiles=189,events=63,runs=runs_total,windows=windows_total,rom_payload_bits=256*320+256*16)
        r['scope']='Read-only model-bound synthesizable metadata responder. Geometry/parameter-first/count/run/window values come from executed current C halo plan. Stable valid/ready, identity, CRC/range rejection and cancellation tested independently of tensor data. Not connected to producer/tile/graph slots, mapped resources, platform or physical FPS.'
        report.write_text(json.dumps(r,indent=2)+'\n')
        if a.prepare_only:r['status']='PREPARED_MODEL_BOUND_CONV_ROM_C_PLAN_ONLY_NOT_RTL_EXECUTED'
        else:
            for label,argv in [('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]),('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_conv_plan_rom','-s','plan_sim']),('xsim',[VENDOR/'xsim.bat','plan_sim','-runall'])]:
                proc=subprocess.run(list(map(str,argv)),cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',capture_output=True);logs=proc.stdout+'\n'+proc.stderr;(out/(label+'.log')).write_text(logs);r['commands'].append(dict(args=list(map(str,argv)),return_code=proc.returncode))
                require(proc.returncode==0 and not re.search(r'^\s*(ERROR:|Fatal:)',logs,re.M),'Actual '+label)
            require('CONV_PLAN_ROM_PASS tiles=189 negative_cases=11 held_cycles=606 cancel_cases=1' in logs,'Complete ROM coverage')
            r['status']='PASS_METADATA_ROM189_TILES11_FAILURE_CASES_HOLD_CANCEL_NOT_COMPUTE'
    except Exception as e:r.update(status='FAILED_CLOSED',error=f'{type(e).__name__}: {e}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']:r['status']='FAILED_SOURCE_INTEGRITY'
    r['artifact_sha256']={str(v.relative_to(ROOT)):sha(v) for folder in (out,build) for v in folder.rglob('*') if v.is_file() and v!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
