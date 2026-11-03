`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_hybrid_ingress4k_v4;
    localparam [31:0] BASE=32'h10000000;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,acquire_valid=0,acquire_mode=0,release_valid=0,release_mode=0;
    wire acquire_ready,release_ready,owner_valid,owner_mode;
    reg score=0,rogue=0,allow_ar=1,abort=0,recover=0,sink_allow=1;
    integer cycle=0,node=0,offset=0,count=0;
    wire mode=owner_mode;
    // Materialized whole-tile controller and native stream decoder.
    reg bcmd=0;reg [31:0] bca=BASE,bce=200,bcgen=1;reg [10:0] bcc=3;
    reg [9:0] bcfh=640,bcw=640,bcy=0,bch=39;
    wire bcr,bactive,bfault,bdone,bresult;wire [3:0] bfc;
    wire [31:0] be,bgen,ba;wire [10:0] bchannels;wire [9:0] bh,bw;
    wire [13:0] bn,bblock,bbase;wire bbegin,bbready,boc,bocr,bodone,bcommit,bcommitready;
    wire brc,brcr,brdone,brbusy,brfault,bsemantic,brcancel,brclear;
    wire brv,brr,brlast;wire [31:0] brep;wire [12:0] bri;wire [511:0] brd;wire [3:0] brfc;
    wire bov,bor,bol,bcodec_error,bcodec_active;wire [1:0] bcodec_code;
    wire [31:0] boe;wire [12:0] boa,boi;wire [511:0] bod;
    wire ferr;wire [2:0] fec;
    z100_native_materialized_load_control burst(.clk(clk),.rst_n(rst_n),.cmd_valid(bcmd),.cmd_ready(bcr),
        .cmd_epoch(bce),.cmd_source_generation(bcgen),.cmd_source_address(bca),.cmd_timeout_cycles(32'd2000000),
        .cmd_channels(bcc),.cmd_full_height(bcfh),.cmd_width(bcw),.cmd_first_row(bcy),.cmd_height(bch),
        .cmd_source_committed(1'b1),.cmd_source_is_materialized(1'b1),.abort(abort),.recover(recover),
        .active(bactive),.fault(bfault),.fault_code(bfc),.done(bdone),.result_committed(bresult),
        .epoch(be),.source_generation(bgen),.channels(bchannels),.height(bh),.width(bw),.total_words(bn),.block_words(bblock),.block_word_base(bbase),
        .feature_begin(bbegin),.feature_begin_ready(bbready),.order_config(boc),.order_config_ready(bocr),.order_done(bodone),
        .feature_commit(bcommit),.feature_commit_ready(bcommitready),.reader_command(brc),.reader_command_ready(brcr),.reader_address(ba),
        .reader_done(brdone),.reader_busy(brbusy),.reader_fault(brfault),.pipeline_error(bcodec_error||(!mode&&ferr)),
        .semantic_cancel(bsemantic),.reader_cancel(brcancel),.reader_clear_fault(brclear));
    wire [13:0] bglobal=bbase+bri;
    z100_native_stream_order codec(.clk(clk),.rst_n(rst_n),.cancel(bsemantic),.cfg_valid(boc),.cfg_ready(bocr),
        .cfg_epoch(be),.cfg_write_order(1'b0),.cfg_channels(bchannels),.cfg_height(bh),.cfg_width(bw),
        .in_valid(brv),.in_ready(brr),.in_epoch(brep),.in_index(bglobal[12:0]),.in_address(13'd0),.in_last(bglobal+1==bn),.in_data(brd),
        .out_valid(bov),.out_ready(bor),.out_epoch(boe),.out_index(boi),.out_address(boa),.out_last(bol),.out_data(bod),
        .active(bcodec_active),.done(bodone),.error_valid(bcodec_error),.error_code(bcodec_code));
    // Virtual descriptors retain their exact LUT/nearest mapping and versioned cache.
    reg vcb=0,vcwv=0,vcc=0,vcmd=0;reg [31:0] vce=1,ve=200,vte=1,vsa=BASE,vrb=BASE,vrow=64,vx=64,vob=0,vgen=1;
    reg [32:0] vre=33'h100000040;reg [9:0] vh=1,vw=1;reg [2:0] vc=4;reg [1:0] vshift=0,vctx=0;reg [7:0] vcd=0;
    wire vcbr,vcwr,vccr,vsv,vloading,vcerr,vcr,vactive,vfault,vdone;wire [2:0] vcec;wire [3:0] vfc;
    wire vrc,vrcr,vrbusy,vrfault,vrcancel,vrclear,vrv,vrr,vrlast;wire [31:0] vrep,vra,vrvep;wire [12:0] vri;wire [511:0] vrd;
    wire vov,vor,vol;wire [31:0] voe,voa;wire [511:0] vod;
    z100_native_view_gather gather(.clk(clk),.rst_n(rst_n),.cfg_begin(vcb),.cfg_begin_ready(vcbr),.cfg_epoch(vce),.cfg_contexts(3'd4),
        .cfg_word_valid(vcwv),.cfg_word_ready(vcwr),.cfg_data(vcd),.cfg_commit(vcc),.cfg_commit_ready(vccr),.store_valid(vsv),.loading(vloading),.cfg_error(vcerr),.cfg_error_code(vcec),
        .cmd_valid(vcmd),.cmd_ready(vcr),.cmd_epoch(ve),.cmd_table_epoch(vte),.cmd_source_address(vsa),.cmd_region_begin(vrb),.cmd_region_end(vre),
        .cmd_source_row_stride(vrow),.cmd_source_x_stride(vx),.cmd_output_word_base(vob),.cmd_timeout_cycles(32'd2000000),
        .cmd_height(vh),.cmd_width(vw),.cmd_channels(vc),.cmd_nearest_shift(vshift),.cmd_context(vctx),.cmd_source_committed(1'b1),
        .abort(abort&&mode),.recover(recover&&mode),.active(vactive),.fault(vfault),.fault_code(vfc),.done(vdone),
        .read_command(vrc),.read_command_ready(vrcr),.read_epoch(vrep),.read_address(vra),.reader_busy(vrbusy),.reader_fault(vrfault),.read_cancel(vrcancel),.read_clear_fault(vrclear),
        .read_valid(vrv),.read_ready(vrr),.read_result_epoch(vrvep),.read_result_index(vri),.read_last(vrlast),.read_data(vrd),
        .out_valid(vov),.out_ready(vor),.out_epoch(voe),.out_word_address(voa),.out_data(vod),.out_last(vol));
    wire mc,mcr,mbusy,mfault,mcancel,mclear,mv,mready,mlast,mdone;wire [31:0] mep,ma,mvep,cache_hits,cache_misses;
    wire [12:0] mi;wire [511:0] md;wire [3:0] mfc;
    z100_native_word_cache cache(.clk(clk),.rst_n(rst_n),.cmd_valid(vrc),.cmd_ready(vrcr),.cmd_epoch(vrep),.cmd_address(vra),.cmd_source_generation(vgen),
        .cancel(vrcancel),.clear_fault(vrclear),.busy(vrbusy),.fault(vrfault),.fault_code(),.done(),
        .out_valid(vrv),.out_ready(vrr),.out_epoch(vrvep),.out_index(vri),.out_last(vrlast),.out_data(vrd),
        .memory_command(mc),.memory_command_ready(mcr),.memory_epoch(mep),.memory_address(ma),.memory_busy(mbusy),.memory_fault(mfault),.memory_cancel(mcancel),.memory_clear_fault(mclear),
        .memory_valid(mv),.memory_ready(mready),.memory_result_epoch(mvep),.memory_result_index(mi),.memory_last(mlast),.memory_data(md),.hit_count(cache_hits),.miss_count(cache_misses));
    wire [5:0] arid;wire [31:0] araddr;wire [3:0] arlen;wire [2:0] arsize;wire [1:0] arburst;
    wire arvalid,arready,rready;reg rvalid=0,rlast=0;reg [63:0] rdata=0;
    z100_native_ingress_reader_v2 ingress(.clk(clk),.rst_n(rst_n),.acquire_valid(acquire_valid),.acquire_mode(acquire_mode),.acquire_ready(acquire_ready),
        .release_valid(release_valid),.release_mode(release_mode),.release_ready(release_ready),.b_quiet(!bactive&&!bcodec_active),.v_quiet(!vactive&&!vloading),.owner_valid(owner_valid),.owner_mode(owner_mode),
        .b_command(brc||(rogue&&mode)),.b_command_ready(brcr),.b_epoch(be),.b_address(ba),.b_words(bblock),
        .b_cancel(brcancel||(rogue&&mode)),.b_clear_fault(brclear||(rogue&&mode)),.b_busy(brbusy),.b_done(brdone),.b_fault(brfault),.b_fault_code(brfc),
        .b_valid(brv),.b_ready(brr),.b_result_epoch(brep),.b_index(bri),.b_data(brd),.b_last(brlast),
        .v_command(mc||(rogue&&!mode)),.v_command_ready(mcr),.v_epoch(mep),.v_address(ma),
        .v_cancel(mcancel||(rogue&&!mode)),.v_clear_fault(mclear||(rogue&&!mode)),.v_busy(mbusy),.v_done(mdone),.v_fault(mfault),.v_fault_code(mfc),
        .v_valid(mv),.v_ready(mready),.v_result_epoch(mvep),.v_index(mi),.v_data(md),.v_last(mlast),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
        .m_axi_rid(6'd0),.m_axi_rdata(rdata),.m_axi_rresp(2'd0),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    // Both ingress paths publish to the same checked source store.
    reg fbegin=0,fcommit=0,fquery=0;reg [10:0] fchannels=1;reg [9:0] fh=1,fw=1;
    wire fbr,fwr,fcr,fsv,fl;wire [31:0] fae;reg [1663:0] fqa=0;reg [127:0] fqm=0;
    wire fqr,fov;wire [31:0] foe;wire [1023:0] fod;
    wire loadv=mode ? vov : bov;wire [31:0] loade=mode ? voe : boe;
    wire [31:0] loada=mode ? voa : {19'd0,boa};wire [511:0] loadd=mode ? vod : bod;
    wire loadlast=mode ? voa+1==count : bol;
    assign bor=!mode&&fwr&&sink_allow;assign vor=mode&&fwr&&sink_allow;
    assign bbready=!mode&&fbr;assign bcommitready=!mode&&fcr;
    z100_feature_banks_load_order_4k_v4 bank(.clk(clk),.rst_n(rst_n),.cancel(owner_valid&&(mode ? (abort||vfault||vcerr) : bsemantic)),
        .cfg_begin(mode?fbegin:bbegin),.cfg_begin_ready(fbr),.cfg_epoch(32'd200),.cfg_canonical_order(mode),
        .cfg_channels(mode?fchannels:bchannels),.cfg_height(mode?fh:bh),.cfg_width(mode?fw:bw),
        .cfg_word_valid(owner_valid&&loadv&&sink_allow),.cfg_word_ready(fwr),.cfg_word_data(loadd),.cfg_word_epoch(loade),.cfg_word_address(loada[12:0]),.cfg_word_last(loadlast),
        .cfg_commit(mode?fcommit:bcommit),.cfg_commit_ready(fcr),.error_valid(ferr),.error_code(fec),.store_valid(fsv),.active_epoch(fae),.loading(fl),
        .req_valid(fquery),.req_ready(fqr),.req_epoch(32'd200),.req_addresses(fqa),.req_mask(fqm),.out_valid(fov),.out_ready(1'b1),.out_epoch(foe),.out_data(fod));
    reg [511:0] memory[0:`MEMWORDS-1];reg [576:0] words[0:`WORDS-1];reg [272:0] descriptors[0:`DESCRIPTORS-1];
    reg [7:0] tables[0:189*1024-1];reg [31:0] counts[0:188];reg [45:0] geometry[0:188];
    reg [129:0] cases[0:188];reg [35:0] expected_ar[0:`HYBRID_ARS-1];
    reg mem_busy=0;reg [31:0] mem_addr=0;reg [4:0] beat=0,beats_in_burst=0;
    wire pop=rvalid&&rready;wire [4:0] next_beat=pop?beat+1'b1:beat;
    wire [31:0] next_address=mem_addr+{24'd0,next_beat,3'd0};
    assign arready=rst_n&&allow_ar&&!mem_busy&&cycle%7!=0;
    always @(negedge clk)sink_allow=rst_n&&cycle%37>8;
    always @(posedge clk)begin
        if(!rst_n)begin mem_busy<=0;rvalid<=0;rlast<=0;rdata<=0;beat<=0;beats_in_burst<=0;end
        else begin
            if(arvalid&&arready)begin mem_busy<=1;mem_addr<=araddr;beat<=0;beats_in_burst<={1'b0,arlen}+1;end
            if(pop)begin rvalid<=0;if(rlast)mem_busy<=0;else beat<=beat+1;end
            if(mem_busy&&(!rvalid||rready)&&!(pop&&rlast)&&cycle%11>1)begin
                rvalid<=1;rdata<=memory[(next_address-BASE)>>6][next_address[5:3]*64+:64];rlast<=next_beat+1==beats_in_burst;
            end
        end
    end
    integer ars=0,rbeats=0,loaded=0,readback=0,burst_commands=0,virtual_commands=0,logical_reads=0;
    integer leases=0,release_blocked=0,wrong_owner_probes=0,recoveries=0,drain_probes=0,stalls=0;
    reg arheld=0,rheld=0,loadheld=0;reg [35:0] held_ar;reg [64:0] held_r;reg [557:0] held_load;
    integer virtual_word_cursor=0;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n)begin
            if(arheld&&(!arvalid||{arlen,araddr}!==held_ar))$fatal(1,"hybrid AR unstable");
            arheld=arvalid&&!arready;if(arheld)held_ar={arlen,araddr};
            if(rheld&&(!rvalid||{rlast,rdata}!==held_r))$fatal(1,"hybrid legal memory R unstable");
            rheld=rvalid&&!rready;if(rheld)held_r={rlast,rdata};
            if(acquire_valid&&acquire_ready)leases=leases+1;
            if(owner_valid)begin
                if((mode&&(brcr||brv||brdone||brfault))||(!mode&&(mcr||mv||mdone||mfault)))$fatal(1,"non-owner saw reader completion/admission");
                if(rogue)wrong_owner_probes=wrong_owner_probes+1;
            end
            if(score)begin
                if(bfault||vfault||vcerr||bcodec_error||ferr)$fatal(1,"hybrid runtime fault node=%0d b=%0d v=%0d f=%0d",node,bfc,vfc,fec);
                if(arvalid&&arready)begin
                    if(ars>=`HYBRID_ARS||{arlen,araddr}!==expected_ar[ars])$fatal(1,"hybrid source AR mismatch request=%0d got=%08x/%0d",ars,araddr,arlen);
                    ars=ars+1;
                end
                if(pop)rbeats=rbeats+1;
                if(brc&&brcr)burst_commands=burst_commands+1;
                if(vcmd&&vcr)begin virtual_commands=virtual_commands+1;virtual_word_cursor=offset+vob;end
                if(vrc&&vrcr)begin
                    if(vra!==words[virtual_word_cursor][543:512])$fatal(1,"hybrid logical source mapping");
                    virtual_word_cursor=virtual_word_cursor+1;logical_reads=logical_reads+1;
                end
                if(loadheld&&(!loadv||{loade,loada[12:0],loadlast,loadd}!==held_load))$fatal(1,"hybrid output unstable");
                loadheld=loadv&&!(fwr&&sink_allow);if(loadheld)begin held_load={loade,loada[12:0],loadlast,loadd};stalls=stalls+1;end
                if(loadv&&fwr&&sink_allow)begin
                    if(loade!=200||loada>=count||loadd!==words[offset+loada][511:0])$fatal(1,"hybrid decoded halo data node=%0d address=%0d",node,loada);
                    loaded=loaded+1;
                end
            end else loadheld=0;
        end
        if(cycle>16000000)$fatal(1,"hybrid watchdog node=%0d loaded=%0d",node,loaded);
    end
    task tick;begin @(posedge clk);#1;end endtask
    task acquire(input integer selected);begin
        while(!acquire_ready)tick();@(negedge clk);acquire_mode=selected;acquire_valid=1;tick();@(negedge clk);acquire_valid=0;acquire_mode=!selected;
        if(!owner_valid||owner_mode!=selected)$fatal(1,"lease did not latch mode");
        release_mode=!selected;release_valid=1;#1;if(release_ready)$fatal(1,"wrong owner released lease");tick();@(negedge clk);release_valid=0;
    end endtask
    task release_lease;begin
        @(negedge clk);release_mode=mode;release_valid=1;#1;while(!release_ready)begin tick();@(negedge clk);#1;end
        tick();@(negedge clk);release_valid=0;if(owner_valid)$fatal(1,"quiescent lease not released");
    end endtask
    task set_case(input integer i);begin
        bca=cases[i][31:0];bcc=cases[i][42:32];bcfh=cases[i][52:43];bcw=cases[i][62:53];bcy=cases[i][72:63];bch=cases[i][82:73];bce=200;bcgen=(bca>>6)+1;
        fchannels=geometry[i][10:0];fh=geometry[i][20:11];fw=geometry[i][30:21];count=geometry[i][44:31];offset=cases[i][128:97];
    end endtask
    task burst_command;begin while(!bcr)tick();@(negedge clk);bcmd=1;tick();@(negedge clk);bcmd=0;bca=32'hffffffc0;bcc=0;bce=0;bcgen=0;end endtask
    task palette(input integer n);integer k;begin
        while(!vcbr)tick();@(negedge clk);vcb=1;vce=n+1;tick();@(negedge clk);vcb=0;
        for(k=0;k<1024;k=k+1)begin @(negedge clk);vcwv=1;vcd=tables[n*1024+k];#1;if(!vcwr)$fatal(1,"hybrid palette ready");tick();end
        @(negedge clk);vcwv=0;vcc=1;#1;if(!vccr)$fatal(1,"hybrid palette commit");tick();@(negedge clk);vcc=0;
    end endtask
    task descriptor(input integer d);begin
        vsa=descriptors[d][31:0];vrb=descriptors[d][63:32];vre={1'b0,descriptors[d][95:64]};vrow=descriptors[d][127:96];vx=descriptors[d][159:128];
        vob=descriptors[d][191:160];vh=descriptors[d][201:192];vw=descriptors[d][211:202];vc=descriptors[d][214:212];
        vshift=descriptors[d][216:215];vctx=descriptors[d][218:217];vte=descriptors[d][250:219];ve=200;vgen=(vrb>>6)+1;
    end endtask
    task virtual_command;begin while(!vcr)tick();@(negedge clk);vcmd=1;tick();@(negedge clk);vcmd=0;vsa=32'hffffffc0;vre=0;vrow=0;vx=0;ve=0;vte=0;end endtask
    task feature_begin;begin while(!fbr)tick();@(negedge clk);fbegin=1;tick();@(negedge clk);fbegin=0;end endtask
    task feature_commit;begin while(!fcr)tick();@(negedge clk);fcommit=1;tick();@(negedge clk);fcommit=0;end endtask
    task verify_ram;integer k,b;begin
        if(!fsv||fl||fae!=200)$fatal(1,"hybrid source not atomically committed");
        for(k=0;k<count;k=k+1)begin
            @(negedge clk);fquery=1;fqm=128'h55555555555555555555555555555555;
            for(b=0;b<64;b=b+1)begin fqa[(b*2)*13+:13]=k;fqa[(b*2+1)*13+:13]=k;end
            #1;while(!fqr)begin tick();@(negedge clk);#1;end tick();
            if(!fov||foe!=200)$fatal(1,"hybrid RAM read epoch");
            for(b=0;b<64;b=b+1)if(fod[b*16+:8]!==words[offset+k][b*8+:8]||fod[b*16+8+:8]!==0)$fatal(1,"hybrid actual RAM mismatch tile=%0d address=%0d bank=%0d",node,k,b);
            readback=readback+1;@(negedge clk);fquery=0;tick();
        end
    end endtask
    // Both modes must retain their lease while an unaccepted AR drains after
    // abort. Opposite commands/cancel/clear cannot seize or clear that reader.
    task abort_probe(input integer selected,input integer tile,input integer d);integer n;begin
        acquire(selected);set_case(tile);allow_ar=0;
        if(selected)begin palette(tile);feature_begin();descriptor(d);virtual_command();end else burst_command();
        while(!arvalid)tick();@(negedge clk);abort=1;release_mode=selected;release_valid=1;rogue=1;tick();@(negedge clk);abort=0;
        repeat(12)begin
            if(!owner_valid||owner_mode!=selected||release_ready||acquire_ready||!arvalid)$fatal(1,"hybrid abort lost outstanding lease");
            release_blocked=release_blocked+1;drain_probes=drain_probes+1;tick();
        end
        allow_ar=1;n=0;while(mem_busy||arvalid||ingress.reader_busy)begin
            if(release_ready||!owner_valid)$fatal(1,"lease released before AXI drain");drain_probes=drain_probes+1;tick();n=n+1;if(n>1000)$fatal(1,"hybrid drain timeout");
        end
        if(release_ready||fsv)$fatal(1,"faulted reader/store released or published");
        @(negedge clk);release_valid=0;recover=1;tick();@(negedge clk);recover=0;n=0;
        while(selected?vactive:bactive)begin tick();n=n+1;if(n>100)$fatal(1,"hybrid recovery timeout b=%0d v=%0d",bfc,vfc);end
        if(ingress.reader_fault||fsv)$fatal(1,"hybrid stale fault/store");rogue=0;recoveries=recoveries+1;release_lease();
    end endtask
    integer d,goal,cursor=0,first_virtual=-1,first_virtual_desc=0,hit_before=0,miss_before=0,lease_before=0;
    initial begin
        $readmemh("source.hex",memory);$readmemh("words.hex",words);$readmemh("descriptors.hex",descriptors);$readmemh("tables.hex",tables);
        $readmemh("counts.hex",counts);$readmemh("node_geometry.hex",geometry);$readmemh("hybrid_cases.hex",cases);$readmemh("hybrid_ar.hex",expected_ar);
        for(d=0;d<189;d=d+1)begin if(first_virtual<0&&cases[d][129])begin first_virtual=d;first_virtual_desc=cursor;end cursor=cursor+counts[d];end
        if(first_virtual<0)$fatal(1,"missing virtual fixture");cursor=0;
        repeat(5)tick();@(negedge clk);rst_n=1;
        abort_probe(0,0,0);abort_probe(1,first_virtual,first_virtual_desc);
        hit_before=cache_hits;miss_before=cache_misses;lease_before=leases;score=1;
        for(node=0;node<189;node=node+1)begin
            acquire(cases[node][129]);set_case(node);rogue=1;goal=cursor+counts[node];
            if(mode)begin
                palette(node);feature_begin();
                for(d=cursor;d<goal;d=d+1)begin descriptor(d);virtual_command();while(!vdone)tick();tick();end
                feature_commit();
            end else begin burst_command();while(!bdone)tick();if(!bresult||bcodec_active||brbusy)$fatal(1,"burst published prematurely");tick();end
            verify_ram();rogue=0;release_lease();cursor=goal;
        end
        if(loaded!=`WORDS||readback!=`WORDS||ars!=`HYBRID_ARS||rbeats!=`HYBRID_R||burst_commands!=240||virtual_commands!=`VIRTUAL_DESCRIPTORS||logical_reads!=136368||cache_hits-hit_before!=`HYBRID_HITS||cache_misses-miss_before!=`HYBRID_MISSES||leases-lease_before!=189||recoveries!=2||release_blocked!=24||wrong_owner_probes==0||stalls==0)$fatal(1,"hybrid ingress coverage loaded=%0d read=%0d AR=%0d R=%0d b=%0d v=%0d hits=%0d misses=%0d",loaded,readback,ars,rbeats,burst_commands,virtual_commands,cache_hits-hit_before,cache_misses-miss_before);
        $display("HYBRID_INGRESS_PASS layers=63 tiles=189 words=%0d readback=%0d burst_commands=%0d virtual_descriptors=%0d logical_virtual_reads=%0d AXI_AR=%0d AXI_R=%0d hits=%0d misses=%0d leases=%0d recoveries=%0d release_blocked=%0d drain_probes=%0d wrong_owner_probes=%0d stalls=%0d cycles=%0d",loaded,readback,burst_commands,virtual_commands,logical_reads,ars,rbeats,cache_hits-hit_before,cache_misses-miss_before,leases-lease_before,recoveries,release_blocked,drain_probes,wrong_owner_probes,stalls,cycle);
        $finish;
    end
endmodule
