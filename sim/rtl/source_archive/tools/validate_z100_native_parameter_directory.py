"""Read all173 immutable job descriptors through the actual frozen AXI reader."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,struct,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PROOF=ROOT/'validation/board_z100/native_parameter_reader_v2/20261025T074249.656472Z/result.json'
PACKAGE=ROOT/'deployment/candidates/pin640/quant_candidates/epoch200_head_concat_20261024T103836.103919Z/package/MODEL.V8P'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/native_parameter_directory'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('npdir_'+stamp[-14:]);build.mkdir(parents=True);report=out/'result.json';before={}
    r=dict(status='RUNNING',commands=[],board_access=False,parameter_configuration_executed=False,full_pipeline_30fps_accepted=False)
    try:
        p=json.loads(PROOF.read_text());check(p['status']=='PASS_PRIVATE_DDR_PARAMETER_READER_ALL173_REAL_AXI_BRIDGE_MAC_FACTOR_UNARY_CANCEL_DRAIN_XSIM_ONLY','Actual all173 parameter image oracle')
        check(p['source_sha256_before']==p['source_sha256_after'],'Stable original source')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(resolve(n))==h,'Original source/artifact '+n)
        jobs_file=next(ROOT/n for n in p['artifact_sha256'] if Path(n).name=='parameter_jobs.hex')
        memory_file=next(ROOT/n for n in p['artifact_sha256'] if Path(n).name=='parameter_memory.hex')
        jobs=[int(v,16) for v in jobs_file.read_text().split()];check(len(jobs)==173 and all(v>>145==0 for v in jobs),'Original192-bit immutable job identities')
        payload_bytes=len(memory_file.read_text().split())*8;check(payload_bytes==p['memory_fixture_bytes']==3122432,'Actual same payload region')
        check(sha(PACKAGE)==p['source_package_sha256']=='65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c','Current model identity')
        model_crc=struct.unpack_from('<I',PACKAGE.read_bytes(),12)[0]
        blob=b''.join((value|(j<<160)|(0x5a50<<176)|(model_crc<<192)).to_bytes(32,'little') for j,value in enumerate(jobs))
        blob+=bytes((-len(blob))%64);check(len(blob)==5568,'Two records per aligned64-byte word')
        (build/'directory.bin').write_bytes(blob)
        (build/'directory.hex').write_text(''.join(f'{int.from_bytes(blob[i:i+8],"little"):016x}\n' for i in range(0,len(blob),8)))
        (build/'parameter_jobs.hex').write_bytes(jobs_file.read_bytes())
        (build/'directory_defs.vh').write_text(f"`define MODEL_CRC 32'd{model_crc}\n`define PAYLOAD_BYTES 33'd{payload_bytes}\n`define DIRECTORY_BYTES 32'd{len(blob)}\n`define DIRECTORY_BEATS {len(blob)//8}\n")
        rtl=[HW/'native_axi64_reader_v1/z100_native_axi64_reader.sv',HW/'native_parameter_directory_v1/z100_native_parameter_directory.sv',HW/'native_parameter_directory_v1/tb_z100_native_parameter_directory.sv']
        sources=[Path(__file__),PROOF,PACKAGE,jobs_file,memory_file,*rtl]
        before={str(s.relative_to(ROOT)):sha(s) for s in sources};r['source_sha256_before']=before;report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,argv):
            argv=list(map(str,argv));proc=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout);r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode));check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M),'Strict actual '+label);return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_parameter_directory','-s','directory_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','directory_sim','-runall']);markers=re.findall(r'^PARAMETER_DIRECTORY_PASS (.+)$',logs,re.M);check(len(markers)==1,'Complete actual directory marker')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(sim['model_jobs']==173 and sim['validated_forwards']==174 and sim['rejected_records']==11 and sim['recoveries']==16 and sim['early_recovery_blocks']==12 and sim['physical_AR']==189 and sim['physical_R']==1512 and sim['held_descriptor_cycles']==696 and sim['consumer_busy_blocks']==522 and sim['held_AR_cycles']>=12,'Original job equality, actual DDR and all failures/drain/consumer gates')
        r.update(status='PASS_PRIVATE_PARAMETER_DIRECTORY173_ORIGINAL_JOBS_REAL_AXI_RECORD_GUARDS_DRAIN_RECOVERY_XSIM_ONLY',simulation=sim,directory_bytes=len(blob),source_package_sha256=sha(PACKAGE),model_crc=model_crc,
            scope='All173 original independent parameter-job records read through frozen AXI64 reader, odd/even32-byte selection and exact145-bit payload comparison. Descriptor stable under backpressure and blocked while consumer busy. Eleven malformed records, out-of-range index, wrong response epoch, actual RRESP, held-AR abort/timeout and16 drained recoveries. Forward completion is not actual parameter configuration; no loader/core pixels, combined platform, physical DDR or FPS accepted.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
