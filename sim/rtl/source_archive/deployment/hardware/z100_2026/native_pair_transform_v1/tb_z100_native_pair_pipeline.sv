`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_pair_pipeline;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cfg_begin=0,cfg_valid=0,cfg_commit=0,start=0,cancel=0,clear_fault=0,downstream_quiescent=1;
    reg [9:0] cfg_channels=0,cfg_height=0,cfg_width=0;
    reg [31:0] cfg_table_epoch=0,cfg_source_address=0,cfg_region_begin=0,cfg_source_generation=0,cfg_row_stride=0,cfg_x_stride=0;
    reg [32:0] cfg_region_end=0;
    reg [1:0] cfg_context=0,cfg_shift=0;
    reg [31:0] frame_epoch=200,timeout_cycles=2000000;
    wire cfg_begin_ready,cfg_ready,cfg_commit_ready,store_valid,start_ready,active,fault,dispatch_done,req_valid,req_last;
    wire [3:0] fault_code,req_source_first_x;
    wire [4:0] req_valid_x;
    wire [31:0] req_epoch,req_address,req_source_generation,req_table_epoch;
    wire [1:0] req_context,req_shift;
    wire [11:0] req_native_word;
    integer cycles=0;
    reg block_sink=0,score=0;
    wire req_ready;
    z100_native_pair_sequencer dut(.cancel(cancel||afault),.*);
    reg [63:0] geometry[0:60];reg [255:0] templates[0:1031];
    wire [153:0] observed={req_epoch,req_table_epoch,req_last,req_native_word,req_valid_x,req_source_first_x,req_shift,req_context,req_source_generation,req_address};

    reg cb=0,cwv=0,cc=0,arecover=0;
    reg [31:0] ce=0,pair_timeout=100000;
    reg [7:0] cd=0;
    wire cbr,cwr,ccr,sv,aactive,afault,pdone,tdone;
    wire [3:0] afc;
    wire cache_command,cache_command_ready,cache_busy,cache_fault,cache_cancel,cache_clear,cache_valid,cache_ready;
    wire [31:0] cache_epoch,cache_address,cache_generation,cache_result_epoch,cache_result_address;
    wire [1023:0] cache_data;
    wire ov,ol;wire [31:0] oe;wire [11:0] ow;wire [511:0] od;
    wire ordy=!block_sink&&cycles%37>8;
    z100_native_pair_transform adapter(.clk(clk),.rst_n(rst_n),.cancel(cancel),.recover(arecover),.timeout_cycles(pair_timeout),
        .cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(ce),.cfg_contexts(3'd4),.cfg_word_valid(cwv),.cfg_word_ready(cwr),
        .cfg_data(cd),.cfg_commit(cc),.cfg_commit_ready(ccr),.store_valid(sv),
        .req_valid(req_valid),.req_ready(req_ready),.req_epoch(req_epoch),.req_address(req_address),.req_source_generation(req_source_generation),
        .req_table_epoch(req_table_epoch),.req_context(req_context),.req_shift(req_shift),.req_source_first_x(req_source_first_x),
        .req_valid_x(req_valid_x),.req_native_word(req_native_word),.req_last(req_last),
        .cache_command(cache_command),.cache_command_ready(cache_command_ready),.cache_epoch(cache_epoch),.cache_address(cache_address),.cache_generation(cache_generation),
        .cache_busy(cache_busy),.cache_fault(cache_fault),.cache_cancel(cache_cancel),.cache_clear(cache_clear),
        .cache_valid(cache_valid),.cache_ready(cache_ready),.cache_result_epoch(cache_result_epoch),.cache_result_address(cache_result_address),.cache_data(cache_data),
        .out_valid(ov),.out_ready(ordy),.out_epoch(oe),.out_word(ow),.out_data(od),.out_last(ol),
        .active(aactive),.fault(afault),.fault_code(afc),.pair_done(pdone),.tile_done(tdone));
    wire mc,mcr,mb,mf,mcan,mclear,mv,mready,mlast;
    wire [31:0] me,ma,re,hits,misses;
    wire [13:0] mw;wire [12:0] ri;wire [511:0] md;
    z100_native_pair_cache cache(.clk(clk),.rst_n(rst_n),.cmd_valid(cache_command),.cmd_ready(cache_command_ready),
        .cmd_epoch(cache_epoch),.cmd_address(cache_address),.cmd_source_generation(cache_generation),
        .cancel(cache_cancel),.clear_fault(cache_clear),.busy(cache_busy),.fault(cache_fault),.fault_code(),.done(),
        .out_valid(cache_valid),.out_ready(cache_ready),.out_epoch(cache_result_epoch),.out_address(cache_result_address),.out_data(cache_data),
        .memory_command(mc),.memory_command_ready(mcr),.memory_epoch(me),.memory_address(ma),.memory_word_count(mw),
        .memory_busy(mb),.memory_fault(mf),.memory_cancel(mcan),.memory_clear_fault(mclear),.memory_valid(mv),.memory_ready(mready),
        .memory_result_epoch(re),.memory_result_index(ri),.memory_last(mlast),.memory_data(md),.hit_count(hits),.miss_count(misses));
    wire [5:0] arid;wire [31:0] araddr;wire [3:0] arlen;wire [2:0] arsize;wire [1:0] arburst;
    wire arvalid,rready;
    reg [63:0] rdata=0;reg rvalid=0,rlast=0;reg [1:0] rresp=0;
    reg block_ar=0,inject_resp=0,mem_active=0;
    wire arready=!block_ar&&!mem_active&&cycles%7!=0;
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(mc),.cmd_ready(mcr),.cmd_epoch(me),.cmd_address(ma),.cmd_word_count(mw),
        .cancel(mcan),.timeout(1'b0),.clear_fault(mclear),.busy(mb),.done(),.fault(mf),.fault_code(),.out_valid(mv),.out_ready(mready),
        .out_epoch(re),.out_index(ri),.out_data(md),.out_last(mlast),.m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),
        .m_axi_arsize(arsize),.m_axi_arburst(arburst),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
        .m_axi_rid(6'd0),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    `include "fixture_defs.vh"
    localparam [31:0] BASE=32'h10000000;
    reg [511:0] memory[0:`MEMWORDS-1];reg [556:0] expected_words[0:136367];reg [7:0] tables[0:61*1024-1];
    reg [31:0] response_addr=0;integer beat=0;
    integer received=0,logical_reads=0,ars=0,rs=0,completed=0,hold_cycles=0,active_cycles=0,drain_checks=0,recoveries=0;
    reg held=0,arheld=0,rheld=0,tile_running=0;
    reg [556:0] held_output;reg [31:0] held_address;reg [66:0] held_r;
    always @(posedge clk)begin
        cycles<=cycles+1;
        if(rst_n)begin
            if(arheld&&(!arvalid||araddr!==held_address))$fatal(1,"Held AR changed");
            arheld<=arvalid&&!arready;held_address<=araddr;
            if(rheld&&(!rvalid||{rdata,rresp,rlast}!==held_r))$fatal(1,"R source violated hold");
            rheld<=rvalid&&!rready;held_r<={rdata,rresp,rlast};
            if(arvalid&&arready)begin
                if(mem_active||arlen!=15||arid!=0||arsize!=3||arburst!=1||araddr[6:0]!=0||araddr<BASE||((araddr-BASE)>>6)+1>=`MEMWORDS)
                    $fatal(1,"Invalid physical pair request");
                mem_active<=1;response_addr<=araddr;beat<=0;if(score)ars<=ars+1;
            end
            if(rvalid&&rready)begin rvalid<=0;if(score)rs<=rs+1;if(rlast)mem_active<=0;else beat<=beat+1;end
            if(mem_active&&!rvalid&&cycles%11!=0&&cycles%11!=1)begin
                rvalid<=1;rdata<=memory[((response_addr-BASE)>>6)+(beat>>3)][(beat%8)*64+:64];
                rlast<=beat==15;rresp<=inject_resp&&beat==10 ? 2'd2 : 2'd0;
            end
            if(score)begin
                if(fault||afault||cache_fault)$fatal(1,"Pipeline fault seq=%d adapter=%d",fault_code,afc);
                if(held&&(!ov||{oe,ol,ow,od}!==held_output))$fatal(1,"Held transformed output changed");
                held<=ov&&!ordy;held_output<={oe,ol,ow,od};if(ov&&!ordy)hold_cycles<=hold_cycles+1;
                if(req_valid&&req_ready)logical_reads<=logical_reads+1;
                if(ov&&ordy)begin
                    if(received>=136368||{oe,ol,ow,od}!==expected_words[received])$fatal(1,"Pair output bytes/order mismatch word=%d",received);
                    received<=received+1;
                end
                if(start&&start_ready)tile_running<=1;
                if(tile_running)active_cycles<=active_cycles+1;
                if(tdone)begin completed<=completed+1;tile_running<=0;end
            end else held<=0;
        end
    end
    task automatic begin_config;
        begin @(negedge clk);cfg_begin=1;do @(posedge clk);while(!cfg_begin_ready);@(negedge clk);cfg_begin=0;end
    endtask
    task automatic load_template(input [255:0] t);
        begin
            @(negedge clk);cfg_source_address=t[31:0];cfg_region_begin=t[63:32];cfg_region_end=t[96:64];
            cfg_source_generation=t[128:97];cfg_row_stride=t[160:129];cfg_x_stride=t[192:161];
            cfg_context=t[194:193];cfg_shift=t[196:195];cfg_valid=1;
            do @(posedge clk);while(!cfg_ready);@(negedge clk);cfg_valid=0;
        end
    endtask
    task automatic commit_config;
        begin @(negedge clk);cfg_commit=1;do @(posedge clk);while(!cfg_commit_ready);@(negedge clk);cfg_commit=0;
            if(!store_valid)$fatal(1,"Commit not atomic");end
    endtask
    task automatic launch;
        begin @(negedge clk);start=1;do @(posedge clk);while(!start_ready);@(negedge clk);start=0;
            cfg_channels=0;cfg_height=0;cfg_width=0;cfg_table_epoch=0;frame_epoch=99;end
    endtask

    task automatic palette(input integer tile);
        integer k;begin
            @(negedge clk);cb=1;ce=geometry[tile][61:30];do @(posedge clk);while(!cbr);@(negedge clk);cb=0;
            for(k=0;k<1024;k=k+1)begin cwv=1;cd=tables[tile*1024+k];do @(posedge clk);while(!cwr);@(negedge clk);end
            cwv=0;cc=1;do @(posedge clk);while(!ccr);@(negedge clk);cc=0;if(!sv)$fatal(1,"Palette commit");
        end
    endtask
    task automatic prepare_tile(input integer tile,input integer first_template);
        integer k,n;begin
            palette(tile);cfg_channels=geometry[tile][9:0];cfg_height=geometry[tile][19:10];cfg_width=geometry[tile][29:20];cfg_table_epoch=geometry[tile][61:30];
            n=cfg_channels>>3;begin_config();for(k=0;k<n;k=k+1)load_template(templates[first_template+k]);commit_config();
        end
    endtask
    task automatic recover_pipeline;
        integer k;begin
            cancel=0;block_ar=0;
            do @(negedge clk);while(cache_busy);
            arecover=1;
            k=0;while(aactive&&k<40)begin @(negedge clk);k=k+1;end
            arecover=0;if(aactive||afault||cache_fault||ov||sv)$fatal(1,"Adapter recovery stale ownership");
            clear_fault=1;@(negedge clk);clear_fault=0;
            if(fault||store_valid)$fatal(1,"Sequencer recovery stale template");recoveries=recoveries+1;
        end
    endtask
    integer i,j,tc=0,real_cycles,real_holds,real_ars,real_rs;
    initial begin
        $readmemh("geometry.hex",geometry);$readmemh("templates.hex",templates);$readmemh("source.hex",memory);
        $readmemh("expected_words.hex",expected_words);$readmemh("tables.hex",tables);
        repeat(5)@(negedge clk);rst_n=1;score=1;
        for(i=0;i<61;i=i+1)begin
            prepare_tile(i,tc);tc=tc+(geometry[i][9:0]>>3);frame_epoch=200;launch();
            do @(negedge clk);while(!tdone);@(negedge clk);
            if(active||aactive||cache_busy)$fatal(1,"Tile completed before drain");
        end
        if(received!=136368||logical_reads!=68184||ars!=60624||rs!=969984||hits!=7560||misses!=60624||completed!=61||hold_cycles==0)
            $fatal(1,"Pair full trace coverage words=%d reads=%d AR=%d R=%d hit=%d miss=%d tiles=%d",received,logical_reads,ars,rs,hits,misses,completed);
        real_cycles=active_cycles;real_holds=hold_cycles;real_ars=ars;real_rs=rs;score=0;
        // Held AR abort and watchdog, with attempted early recovery blocked.
        for(i=0;i<2;i=i+1)begin
            prepare_tile(0,0);frame_epoch=201+i;block_ar=1;pair_timeout=i==1 ? 20 : 100000;launch();
            do @(negedge clk);while(!arvalid);
            if(i==0)begin cancel=1;@(negedge clk);cancel=0;end
            do @(negedge clk);while(!afault);
            arecover=1;
            for(j=0;j<40;j=j+1)begin @(negedge clk);
                if(!arvalid||!cache_busy||!afault||ov||cache_clear)$fatal(1,"Abandoned accepted reader work");drain_checks=drain_checks+1;end
            arecover=0;recover_pipeline();pair_timeout=100000;
        end
        // Physical response error propagates through reader/cache/adapter.
        prepare_tile(0,0);frame_epoch=203;inject_resp=1;launch();do @(negedge clk);while(!afault);recover_pipeline();inject_resp=0;
        // Held transformed output cancellation flushes both pair halves.
        prepare_tile(0,0);frame_epoch=204;block_sink=1;launch();do @(negedge clk);while(!ov);
        cancel=1;@(negedge clk);cancel=0;if(ov)$fatal(1,"Cancelled output exposed");recover_pipeline();block_sink=0;
        if(recoveries!=4||drain_checks!=80)$fatal(1,"Pipeline fault coverage");
        $display("PAIR_PIPELINE_PASS tiles=%0d words=%0d pair_requests=%0d AXI_AR=%0d AXI_R=%0d hits=7560 misses=60624 active_cycles=%0d output_hold_cycles=%0d recoveries=%0d drain_checks=%0d",
            completed,received,logical_reads,real_ars,real_rs,real_cycles,real_holds,recoveries,drain_checks);
        $finish;
    end
    initial begin #100000000;$fatal(1,"Pipeline watchdog");end
endmodule
`default_nettype wire
