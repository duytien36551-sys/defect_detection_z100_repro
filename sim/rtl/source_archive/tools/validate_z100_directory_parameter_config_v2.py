"""Directory lookup -> actual all173 configuration memories on one AXI read port."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
PARAM=ROOT/'validation/board_z100/native_parameter_reader_v2/20261025T074249.656472Z/result.json'
DIRECTORY=ROOT/'validation/board_z100/native_parameter_directory_v2/20261025T131431.890309Z/result.json'
SUPPORT=HW/'native_parameter_directory_v1/parameter_config_support.vh'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/directory_parameter_config_v2'/stamp;out.mkdir(parents=True)
    build=ROOT/'build'/('dpcfg_'+stamp[-14:]);build.mkdir(parents=True);report=out/'result.json';before={}
    r=dict(status='RUNNING',commands=[],board_access=False,pixel_compute_executed=False,full_pipeline_30fps_accepted=False)
    try:
        pp,dp=[json.loads(p.read_text()) for p in (PARAM,DIRECTORY)]
        check(pp['status'].startswith('PASS_PRIVATE_DDR_PARAMETER_READER_ALL173') and dp['status'].startswith('PASS_PRIVATE_PARAMETER_DIRECTORY_V2_173'),'Closed actual source/config proofs')
        for p in (pp,dp):
            check(p['source_sha256_before']==p['source_sha256_after'],'Stable source')
            for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(resolve(n))==h,'Bound original source/artifact '+n)
        files=[Path(n) for n in pp['commands'][0]['args'][2:]];oldtb=next(p for p in files if p.name=='tb_z100_native_parameter_reader_v2.sv');rtl=[p for p in files if p!=oldtb]
        fixtures=[]
        for name in ('parameter_memory.hex','parameter_jobs.hex','parameter_reader_defs.vh'):
            p=next(ROOT/n for n in pp['artifact_sha256'] if Path(n).name==name);fixtures.append(p);shutil.copyfile(p,build/name)
        for name in ('directory.hex','directory_defs.vh'):
            p=next(ROOT/n for n in dp['artifact_sha256'] if Path(n).name==name);fixtures.append(p);shutil.copyfile(p,build/name)
        shutil.copyfile(SUPPORT,build/SUPPORT.name)
        text=oldtb.read_text()
        def edit(a,b):
            nonlocal text
            check(text.count(a)==1,'Unique integration seam '+a[:80]);text=text.replace(a,b)
        edit('module tb_z100_native_parameter_reader_v2;','module tb_z100_directory_parameter_config;\n    `include "directory_defs.vh"')
        edit('reg abort=0,recover=0,job_valid=0;reg[31:0] job_epoch=200,job_timeout=5000000;', 'reg abort=0,recover=0;wire job_valid;wire[31:0] job_epoch;reg[31:0] job_timeout=5000000;')
        edit('reg[10:0] job_groups=0;reg[5:0] job_lanes=0;', 'wire[10:0] job_groups;wire[5:0] job_lanes;')
        edit('reg[31:0] job_weights=0,job_bias=0,job_factors=0,job_unary=0;', 'wire[31:0] job_weights,job_bias,job_factors,job_unary;')
        start=text.index('    z100_native_axi64_reader reader(');end=text.index('    reg[63:0] memory',start)
        reader=text[start:end]
        names=['arid','araddr','arlen','arsize','arburst','arvalid','arready','rdata','rresp','rlast','rvalid','rready']
        for name in names:reader=reader.replace('.m_axi_'+name+'('+name+')','.m_axi_'+name+'(p_'+name+')')
        reader=reader.replace(".m_axi_rid(6'd0)",'.m_axi_rid(p_rid)')
        text=text[:start]+'    `include "parameter_config_support.vh"\n'+reader+text[end:]
        edit("araddr<32'h20000000||\n                   (araddr-32'h20000000)/8+arlen>=`PARAMETER_MEMORY_BEATS", "!((araddr>=32'h20000000&&(araddr-32'h20000000)/8+arlen<`PARAMETER_MEMORY_BEATS)||(araddr>=32'h21000000&&(araddr-32'h21000000)/8+arlen<`DIRECTORY_BEATS))")
        edit("rdata<=memory[(memory_address-32'h20000000)/8+memory_beat]", "rdata<=(memory_address>=32'h21000000) ? directory_memory[(memory_address-32'h21000000)/8+memory_beat] : memory[(memory_address-32'h20000000)/8+memory_beat]")
        a=text.index('    task issue(input integer j);');b=text.index('    task recovery;',a)
        text=text[:a]+'''    task issue(input integer j);
        begin @(negedge clk);d_job=j;d_tag=j+1;d_command=1;
            do @(posedge clk);while(!d_command_ready);
            @(negedge clk);d_command=0;
        end
    endtask
''' +text[b:]
        a=text.index('        // Abort held advertised AR;');b=text.index('        $finish;',a)
        text=text[:a]+'''        repeat(3)@(negedge clk);
        if(directory_forwards!=173||parameter_completions!=173||ars!=24567||rbeats!=391688||reader_busy||dbusy||active||d_active||memory_active||arb_active||arb_fault||load_fault||d_fault||!configured)$fatal(1,"Directory-to-real-config complete coverage");
        $display("DIRECTORY_PARAMETER_CONFIG_PASS model_jobs=%0d directory_forwards=%0d configurations=%0d weight_bytes=%0d bias_values=%0d factors=%0d unary_replica_bytes=%0d parameter_completions=%0d physical_AR=%0d physical_R=%0d",completed,directory_forwards,configs,weight_checks,bias_checks,factor_checks,unary_checks,parameter_completions,ars,rbeats);
''' +text[b:]
        tb=build/'tb_z100_directory_parameter_config.sv';tb.write_text(text);rtl.append(tb)
        for name in ('native_parameter_directory_v1/z100_native_parameter_directory_v2.sv','native_axi_read_arbiter_v1/z100_native_axi_read_arbiter.sv'):
            p=HW/name;check(p not in rtl,'Single source instance');rtl.append(p)
        before={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else 'external/'+p.as_posix().replace(':',''):sha(p) for p in [Path(__file__),PARAM,DIRECTORY,SUPPORT,oldtb,*fixtures,*rtl]}
        r['source_sha256_before']=before;report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,argv):
            argv=list(map(str,argv));p=subprocess.run(argv,cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode));check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict actual '+label);return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl]);run('xelab',[VENDOR/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_directory_parameter_config','glbl','-s','directory_config_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','directory_config_sim','-runall']);rows=re.findall(r'^DIRECTORY_PARAMETER_CONFIG_PASS (.+)$',logs,re.M);check(len(rows)==1,'Complete real configuration marker')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',rows[0])}
        check(sim==dict(model_jobs=173,directory_forwards=173,configurations=74447,weight_bytes=3011712,bias_values=5536,factors=5419,unary_replica_bytes=708608,parameter_completions=173,physical_AR=24567,physical_R=391688),'All original independent DDR/config memory probes plus directory reads')
        r.update(status='PASS_PRIVATE_DIRECTORY_TO_ALL173_REAL_PARAMETER_CONFIG_SINGLE_AXI_XSIM_ONLY',simulation=sim,source_package_sha256=pp['source_package_sha256'],
            scope='DDR directory -> descriptor -> actual parameter loader/bridge -> original MAC SITES1 config RAM/bias/factor32/unary16. Original independent DDR-address and configuration-memory probes retained; no direct TB job geometry/address assignments. Both actual frozen readers share one physical AXI arbiter/responder. Positive all173 integration; negative directory and parameter drain suites remain separately bound prerequisites. No MAC pixels, full20site runtime platform or physical FPS.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(resolve(n)) for n in before}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY')
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
