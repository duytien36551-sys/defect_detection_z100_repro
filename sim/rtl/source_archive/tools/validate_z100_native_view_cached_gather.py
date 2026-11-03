"""Repeat the closed all34-node gather trace through a versioned32KiB cache."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
PROOF=ROOT/'validation/board_z100/native_view_gather_v1/20261024T141739.247306Z/result.json'
VENDOR=Path('C:/appload/2026.1/Vivado/bin')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/native_view_cached_gather_v1'/stamp;build=ROOT/'build'/('vcg_'+stamp[-14:])
    out.mkdir(parents=True);build.mkdir(parents=True)
    hw=ROOT/'deployment/hardware/z100_2026'
    cache=hw/'native_word_cache_v1/z100_native_word_cache.sv';gather=hw/'native_view_gather_v1/z100_native_view_gather.sv'
    context=hw/'native_view_context4_v1/z100_native_view_context4.sv';reader=hw/'native_axi64_reader_v1/z100_native_axi64_reader.sv'
    original_tb=hw/'native_view_gather_v1/tb_z100_native_view_gather.sv'
    sources=[Path(__file__),cache,gather,context,reader,original_tb,PROOF];before={}
    r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False,process_environment_overrides={'XILINX_LOCAL_USER_DATA':'no'})
    report=out/'result.json'
    try:
        p=read(PROOF);check(p['status']=='PASS_PRIVATE_ALL34_VIEWS_AUTONOMOUS_AXI_GATHER_1253_DESCRIPTORS_XSIM_16BRAM_OOC','Closed real-reader gather prerequisite')
        check(p['source_sha256_before']==p['source_sha256_after'],'Prior source stability')
        for n,h in {**p['source_sha256_after'],**p['artifact_sha256']}.items():check(sha(ROOT/n)==h,'Prior source/artifact drift '+n)
        def artifact(name):
            paths=[ROOT/n for n in p['artifact_sha256'] if (ROOT/n).name==name];check(len(paths)==1,'Unique closed fixture '+name);return paths[0]
        for name in ('source.hex','words.hex','descriptors.hex','tables.hex','counts.hex','fixture_defs.vh'):
            f=artifact(name);sources.append(f);shutil.copy2(f,build/name)
        before={str(f.relative_to(ROOT)):sha(f) for f in sources}
        descriptors=[int(x,16) for x in (build/'descriptors.hex').read_text().split()]
        words=[int(x,16) for x in (build/'words.hex').read_text().split()]
        # Independent direct-map event model derives all expected read misses.
        tags={};cursor=0;hits=0;misses=0
        for d in descriptors:
            generation=(((d>>32)&0xffffffff)>>6)+1
            for word in words[cursor:cursor+((d>>251)&65535)]:
                address=(word>>512)&0xffffffff;index=(address>>6)&511;key=(200,generation,address>>15)
                if tags.get(index)==key:hits+=1
                else:misses+=1;tags[index]=key
            cursor+=(d>>251)&65535
        check(cursor==187280 and hits>0 and hits+misses==cursor,'All logical cache accesses')
        text=original_tb.read_text()
        def replace(a,b):
            nonlocal text
            check(text.count(a)==1,'Exact bounded TB adapter '+a[:90]);text=text.replace(a,b)
        replace('module tb_z100_native_view_gather;','module tb_z100_native_view_cached_gather;')
        replace('wire rdone;wire [3:0] rfc;', '''wire rdone;wire [3:0] rfc;
    reg [31:0] generation=1;wire [31:0] cache_hits,cache_misses;
    wire mc,mcr,mbusy,mfault,mcancel,mclear,mv,mready,mlast;wire [31:0] mep,ma,mvep;wire [12:0] mi;wire [511:0] md;
    wire [3:0] mfc;
    z100_native_word_cache cache(.clk(clk),.rst_n(rst_n),.cmd_valid(rc),.cmd_ready(rcr),.cmd_epoch(rep),.cmd_address(ra),.cmd_source_generation(generation),
        .cancel(rcancel),.clear_fault(rclear),.busy(rbusy),.fault(rfault),.fault_code(rfc),.done(rdone),
        .out_valid(rv),.out_ready(rr),.out_epoch(rvep),.out_index(ri),.out_last(rlast),.out_data(rd),
        .memory_command(mc),.memory_command_ready(mcr),.memory_epoch(mep),.memory_address(ma),.memory_busy(mbusy),.memory_fault(mfault),.memory_cancel(mcancel),.memory_clear_fault(mclear),
        .memory_valid(mv),.memory_ready(mready),.memory_result_epoch(mvep),.memory_result_index(mi),.memory_last(mlast),.memory_data(md),.hit_count(cache_hits),.miss_count(cache_misses));''')
        replace('z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(rc),.cmd_ready(rcr),.cmd_epoch(rep),.cmd_address(ra),.cmd_word_count(14\'d1),',
            'z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(mc),.cmd_ready(mcr),.cmd_epoch(mep),.cmd_address(ma),.cmd_word_count(14\'d1),')
        replace('.cancel(rcancel),.timeout(1\'b0),.clear_fault(rclear),.busy(rbusy),.done(rdone),.fault(rfault),.fault_code(rfc),',
            '.cancel(mcancel),.timeout(1\'b0),.clear_fault(mclear),.busy(mbusy),.done(),.fault(mfault),.fault_code(mfc),')
        replace('.out_valid(rv),.out_ready(rr),.out_epoch(rvep),.out_index(ri),.out_data(rd),.out_last(rlast),',
            '.out_valid(mv),.out_ready(mready),.out_epoch(mvep),.out_index(mi),.out_data(md),.out_last(mlast),')
        replace('integer cycle=0,read_requests=0,beats=0,received=0,completed=0,stall_count=0,recoveries=0,drain_probes=0;',
            'integer cycle=0,read_requests=0,physical_reads=0,beats=0,received=0,completed=0,stall_count=0,recoveries=0,drain_probes=0,hit_before=0,miss_before=0;')
        replace('if(score)begin if(araddr!==words[read_requests][543:512])$fatal(1,"wrong source address request=%0d got=%08x expected=%08x",read_requests,araddr,words[read_requests][543:512]);read_requests=read_requests+1;end',
            'if(score)begin if(araddr!==words[read_requests-1][543:512])$fatal(1,"cache miss source address mismatch");physical_reads=physical_reads+1;end')
        replace('if(score)begin\n                if(fault||cerr)',
            'if(score)begin\n                if(rc&&rcr)begin if(ra!==words[read_requests][543:512])$fatal(1,"logical gather source address mismatch");read_requests=read_requests+1;end\n                if(fault||cerr)')
        replace('te=descriptors[d][250:219];epoch=200;timeout_cycles=2000000;committed=1;',
            'te=descriptors[d][250:219];epoch=200;timeout_cycles=2000000;committed=1;generation=(rb>>6)+1;')
        replace('integer node,d,j,goal,word_goal,desc_cursor=0;', '''task small_query(input [7:0] expected);begin
        command();while(!ov)tick();if(od[7:0]!==expected||od[511:8]!==0||oe!=epoch||!ol)$fatal(1,"source version query mismatch");
        while(!done)tick();tick();
    end endtask
    integer node,d,j,goal,word_goal,desc_cursor=0,source_index;
    reg [511:0] saved_word;reg [7:0] expected_byte;integer version_hits,version_misses;''')
        replace('for(j=0;j<10;j=j+1)begin','for(j=0;j<11;j=j+1)begin')
        replace('9:re={1\'b0,rb};endcase','9:re={1\'b0,rb};10:generation=0;endcase')
        replace('command();while(!fault)tick();if(fc!=1)$fatal(1,"bad descriptor code");recovery();',
            'command();while(!fault)tick();if(fc!=(j==10?4:1))$fatal(1,"bad descriptor or generation code");recovery();')
        replace('score=1;', '''// Address reuse must miss when source generation OR frame epoch changes.
        load_palette(0);set_descriptor(0);height=1;width=1;channels=1;source_index=(sa-BASE)>>6;saved_word=memory[source_index];
        expected_byte=tables[context_id*256+(memory[source_index][7:0]^8'h80)];small_query(expected_byte);
        version_hits=cache_hits;small_query(expected_byte);if(cache_hits!=version_hits+1)$fatal(1,"same immutable source did not hit");
        memory[source_index][7:0]=saved_word[7:0]^8'h55;generation=generation+1;version_misses=cache_misses;
        expected_byte=tables[context_id*256+(memory[source_index][7:0]^8'h80)];small_query(expected_byte);if(cache_misses!=version_misses+1)$fatal(1,"generation reused stale bytes");
        memory[source_index][7:0]=saved_word[7:0]^8'haa;epoch=201;version_misses=cache_misses;
        expected_byte=tables[context_id*256+(memory[source_index][7:0]^8'h80)];small_query(expected_byte);if(cache_misses!=version_misses+1)$fatal(1,"new frame reused stale bytes");
        memory[source_index]=saved_word;
        hit_before=cache_hits;miss_before=cache_misses;score=1;''')
        replace('beats!=`WORDS*8','beats!=`MISSES*8||physical_reads!=`MISSES||cache_misses-miss_before!=`MISSES||cache_hits-hit_before!=`HITS')
        replace('recoveries!=14','recoveries!=15')
        replace('$display("NATIVE_VIEW_GATHER_PASS nodes=34 descriptors=%0d words=%0d AXI_AR=%0d AXI_R=%0d stalls=%0d recoveries=%0d drain_probes=%0d",completed,received,read_requests,beats,stall_count,recoveries,drain_probes);',
            '$display("NATIVE_VIEW_CACHED_GATHER_PASS nodes=34 descriptors=%0d words=%0d logical_reads=%0d AXI_AR=%0d AXI_R=%0d hits=%0d stalls=%0d recoveries=%0d drain_probes=%0d version_tests=4 cycles=%0d",completed,received,read_requests,physical_reads,beats,cache_hits-hit_before,stall_count,recoveries,drain_probes,cycle);')
        tb=build/'tb_z100_native_view_cached_gather.sv';tb.write_text(text)
        with (build/'fixture_defs.vh').open('a') as f:f.write(f'`define HITS {hits}\n`define MISSES {misses}\n')
        r['fixture']=dict(source_package_sha256=p['fixture']['source_package_sha256'],nodes=34,descriptors=1253,words=187280,
            expected_hits=hits,expected_misses=misses,expected_AXI_read_bytes=misses*64,
            previous_AXI_read_bytes=187280*64,read_bytes_avoided=(187280-misses)*64,
            source_generation='(unique immutable native-source region beginning >>6)+1; frame epoch also in key',
            limits='Trace-local read reductions; not actual tiled fullgraph traffic or physical DDR/FPS')
        report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            env=dict(os.environ);env['XILINX_LOCAL_USER_DATA']='no'
            argv=list(map(str,args));p=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(p.stdout);r['commands'].append(dict(label=label,args=argv,return_code=p.returncode))
            check(p.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',p.stdout,re.M),'Strict actual tool diagnostic '+label);return p.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',gather,context,reader,cache,tb]);run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_native_view_cached_gather','-s','cachedgather_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','cachedgather_sim','-runall'])
        markers=re.findall(r'^NATIVE_VIEW_CACHED_GATHER_PASS (.+)$',logs,re.M);check(len(markers)==1,'Complete cached gather marker')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
        check(all(sim.get(k)==v for k,v in dict(nodes=34,descriptors=1253,words=187280,logical_reads=187280,AXI_AR=misses,AXI_R=misses*8,hits=hits,recoveries=15,version_tests=4).items()) and sim['stalls']>0,'Exact cached payloads, generation changes and fault recovery')
        r['simulation']=sim
        tcl=build/'synth.tcl';tcl.write_text('set_param general.maxThreads 2\nread_verilog -sv {'+cache.as_posix()+'}\nsynth_design -top z100_native_word_cache -part xc7z100ffg900-2 -mode out_of_context\ncreate_clock -period 10 [get_ports clk]\nreport_utilization -file {'+(out/'utilization.rpt').as_posix()+'}\nset f [open {'+(out/'primitives.txt').as_posix()+'} w]\nforeach kind {RAMB18E1 RAMB36E1 DSP48E1 LDCE LDPE} {puts $f "$kind [llength [get_cells -hier -filter REF_NAME==$kind]]"}\nputs $f "BLACKBOX [llength [get_cells -hier -filter IS_BLACKBOX==1]]"\nclose $f\nwrite_checkpoint -force {'+(build/'cache.dcp').as_posix()+'}\nexit\n')
        run('synth',[VENDOR/'vivado.bat','-mode','batch','-source',tcl,'-log',out/'vivado.log','-journal',out/'vivado.jou'])
        primitives={k:int(v) for k,v in re.findall(r'(\w+) (\d+)',(out/'primitives.txt').read_text())};util=(out/'utilization.rpt').read_text()
        metric=lambda n:int(re.search(r'^\|\s*'+n+r'\*?\s*\|\s*(\d+)',util,re.M)[1])
        resources=dict(Slice_LUT=metric('Slice LUTs'),FF=metric('Slice Registers'),BRAM36eq=primitives['RAMB36E1']+primitives['RAMB18E1']/2,**primitives)
        check(8<=resources['BRAM36eq']<=10 and primitives['DSP48E1']==primitives['LDCE']==primitives['LDPE']==primitives['BLACKBOX']==0,'Actual bounded32KiB cache mapping')
        r.update(status='PASS_PRIVATE_VERSIONED32K_CACHE_ALL34_VIEW_GATHER_XSIM_OOC',cache_resources=resources,
            scope='Actual cache + immutable real gather/context + frozen AXI reader; all34-node source-addressed trace and changed-generation/frame tests. Cache resources exclude gather/reader. Fullgraph source ownership and consumer/HP integration, routed clocks, physical traffic and sustained FPS remain unaccepted.')
    except Exception as exc:r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before;r['source_sha256_after']={str(f.relative_to(ROOT)):sha(f) for f in sources} if before else {}
    if before!=r['source_sha256_after']:r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
