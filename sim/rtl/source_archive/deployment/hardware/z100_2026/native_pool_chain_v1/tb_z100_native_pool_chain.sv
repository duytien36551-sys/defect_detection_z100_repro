`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_native_pool_chain;
    localparam [31:0] BASE=32'h10000000,REGION1=32'h10020000;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0;
    wire [31:0] epoch,source_address,destination_address;
    wire [10:0] channels;wire [9:0] height;wire [13:0] word_count;
    wire r_cmd_valid,r_cmd_ready,r_core_ready,r_busy,r_done,r_fault;
    wire [3:0] r_fault_code;wire r_out_valid,r_out_ready,r_out_last;
    wire [31:0] r_out_epoch;wire [12:0] r_out_index;wire [511:0] r_out_data;
    assign r_cmd_ready=r_core_ready;
    wire [5:0] arid,rid;wire [31:0] araddr;wire [3:0] arlen;wire [2:0] arsize;
    wire [1:0] arburst,rresp;wire arvalid,arready,rvalid,rready,rlast;wire [63:0] rdata;
    wire semantic_cancel,axi_cancel,axi_clear_fault;
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(r_cmd_valid),.cmd_ready(r_core_ready),
        .cmd_epoch(epoch),.cmd_address(source_address),.cmd_word_count(word_count),.cancel(axi_cancel),.timeout(1'b0),.clear_fault(axi_clear_fault),
        .busy(r_busy),.done(r_done),.fault(r_fault),.fault_code(r_fault_code),.out_valid(r_out_valid),.out_ready(r_out_ready),
        .out_epoch(r_out_epoch),.out_index(r_out_index),.out_data(r_out_data),.out_last(r_out_last),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_rid(rid),.m_axi_rdata(rdata),.m_axi_rresp(rresp),
        .m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    wire rd_cfg,wr_cfg;wire rd_cfg_ready,wr_cfg_ready;
    wire rd_valid,rd_ready,rd_last,rd_active,rd_done,rd_error;
    wire [1:0] rd_code;wire [31:0] rd_epoch;wire [12:0] rd_address,rd_index;wire [511:0] rd_data;
    z100_native_stream_order read_order(.clk(clk),.rst_n(rst_n),.cancel(semantic_cancel),.cfg_valid(rd_cfg),.cfg_ready(rd_cfg_ready),
        .cfg_epoch(epoch),.cfg_write_order(1'b0),.cfg_channels(channels),.cfg_height(height),.cfg_width(10'd20),
        .in_valid(r_out_valid),.in_ready(r_out_ready),.in_epoch(r_out_epoch),.in_index(r_out_index),.in_address(13'd0),
        .in_last(r_out_last),.in_data(r_out_data),.out_valid(rd_valid),.out_ready(rd_ready),.out_epoch(rd_epoch),
        .out_index(rd_index),.out_address(rd_address),.out_last(rd_last),.out_data(rd_data),
        .active(rd_active),.done(rd_done),.error_valid(rd_error),.error_code(rd_code));
    wire cb,cc,jv;wire cbr,ccr,jr,sv,loading,pv,pr,plast,pdone,perr,pactive;
    wire [31:0] ae,pe;wire [12:0] pa;wire [511:0] pd;wire [3:0] pec;
    z100_maxpool_store20 pool(.clk(clk),.rst_n(rst_n),.cancel(semantic_cancel),.cfg_begin(cb),.cfg_begin_ready(cbr),
        .cfg_epoch(epoch),.cfg_channels(channels),.cfg_height(height),.cfg_width(10'd20),.cfg_word_valid(rd_valid),.cfg_word_ready(rd_ready),
        .cfg_word_epoch(rd_epoch),.cfg_word_address(rd_address),.cfg_word_last(rd_last),.cfg_data(rd_data),
        .cfg_commit(cc),.cfg_commit_ready(ccr),.store_valid(sv),.loading(loading),.active_epoch(ae),
        .job_valid(jv),.job_ready(jr),.job_epoch(epoch),.job_channels(channels),.job_height(height),.job_width(10'd20),
        .out_valid(pv),.out_ready(pr),.out_epoch(pe),.out_address(pa),.out_data(pd),.out_last(plast),
        .done(pdone),.error_valid(perr),.error_code(pec),.active(pactive));
    wire wi_valid,wi_ready,wi_last,wr_active,wr_done,wr_error;
    wire [31:0] wi_epoch;wire [12:0] wi_index,wi_address;wire [511:0] wi_data;wire [1:0] wr_code;
    z100_native_stream_order write_order(.clk(clk),.rst_n(rst_n),.cancel(semantic_cancel),.cfg_valid(wr_cfg),.cfg_ready(wr_cfg_ready),
        .cfg_epoch(epoch),.cfg_write_order(1'b1),.cfg_channels(channels),.cfg_height(height),.cfg_width(10'd20),
        .in_valid(pv),.in_ready(pr),.in_epoch(pe),.in_index(13'd0),.in_address(pa),.in_last(plast),.in_data(pd),
        .out_valid(wi_valid),.out_ready(wi_ready),.out_epoch(wi_epoch),.out_index(wi_index),.out_address(wi_address),
        .out_last(wi_last),.out_data(wi_data),.active(wr_active),.done(wr_done),.error_valid(wr_error),.error_code(wr_code));
    wire w_cmd_valid;wire w_cmd_ready,w_busy,w_done,w_fault;wire [3:0] w_fault_code;
    wire [5:0] awid,wid,bid;wire [31:0] awaddr;wire [3:0] awlen;wire [2:0] awsize;
    wire [1:0] awburst,bresp;wire awvalid,awready,wvalid,wready,wlast,bvalid,bready;
    wire [63:0] wdata;wire [7:0] wstrb;
    z100_native_axi64_writer writer(.clk(clk),.rst_n(rst_n),.cmd_valid(w_cmd_valid),.cmd_ready(w_cmd_ready),
        .cmd_epoch(epoch),.cmd_address(destination_address),.cmd_word_count(word_count),.in_valid(wi_valid),.in_ready(wi_ready),
        .in_epoch(wi_epoch),.in_index(wi_index),.in_data(wi_data),.in_last(wi_last),.cancel(axi_cancel),.timeout(1'b0),.clear_fault(axi_clear_fault),
        .busy(w_busy),.done(w_done),.fault(w_fault),.fault_code(w_fault_code),.m_axi_awid(awid),.m_axi_awaddr(awaddr),
        .m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),.m_axi_awvalid(awvalid),.m_axi_awready(awready),
        .m_axi_wid(wid),.m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
        .m_axi_bid(bid),.m_axi_bresp(bresp),.m_axi_bvalid(bvalid),.m_axi_bready(bready));
    axi3_byte_memory memory(.clk(clk),.rst_n(rst_n),.awid(awid),.awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),
        .awvalid(awvalid),.awready(awready),.wid(wid),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.wvalid(wvalid),.wready(wready),
        .bid(bid),.bresp(bresp),.bvalid(bvalid),.bready(bready),.arid(arid),.araddr(araddr),.arlen(arlen),.arsize(arsize),
        .arburst(arburst),.arvalid(arvalid),.arready(arready),.rid(rid),.rdata(rdata),.rresp(rresp),.rlast(rlast),.rvalid(rvalid),.rready(rready));
    reg cmd_valid=0,abort=0,recover=0,source_committed=1;
    reg [31:0] cmd_epoch=200,cmd_source=BASE,cmd_destination=REGION1,limit=1000000;
    reg [10:0] cmd_channels=128;reg [9:0] cmd_height=20;reg [1:0] passes=3;
    wire cmd_ready,done,fault,active;wire [3:0] fault_code;wire [1:0] completed;
    wire [31:0] result_address;wire result_committed;
    z100_native_pool_chain_control control(.clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),
        .cmd_epoch(cmd_epoch),.cmd_source_address(cmd_source),.cmd_destination_address(cmd_destination),
        .cmd_channels(cmd_channels),.cmd_height(cmd_height),.cmd_passes(passes),.cmd_source_committed(source_committed),
        .cmd_timeout_cycles(limit),.abort(abort),.recover(recover),.active(active),.done(done),.fault(fault),.fault_code(fault_code),
        .completed_passes(completed),.epoch(epoch),.source_address(source_address),.destination_address(destination_address),
        .channels(channels),.height(height),.word_count(word_count),.result_address(result_address),.result_committed(result_committed),
        .feature_begin(cb),.feature_begin_ready(cbr),.read_order_config(rd_cfg),.read_order_config_ready(rd_cfg_ready),
        .reader_command(r_cmd_valid),.reader_command_ready(r_cmd_ready),.reader_done(r_done),.reader_busy(r_busy),.reader_fault(r_fault),
        .feature_commit(cc),.feature_commit_ready(ccr),.write_order_config(wr_cfg),.write_order_config_ready(wr_cfg_ready),
        .writer_command(w_cmd_valid),.writer_command_ready(w_cmd_ready),.writer_done(w_done),.writer_busy(w_busy),.writer_fault(w_fault),
        .pool_job(jv),.pool_job_ready(jr),.pool_done(pdone),.pipeline_error(perr||rd_error||wr_error),
        .semantic_cancel(semantic_cancel),.axi_cancel(axi_cancel),.axi_clear_fault(axi_clear_fault));
    reg [511:0] inputs[0:`INPUT_WORDS-1],gold[0:`WORDS-1];reg [35:0] cases[0:`CASES-1];
    integer cycle=0,commands=0,completions=0,read_done_count=0,write_done_count=0,pool_done_count=0;
    integer output_words=0,gold_cursor=0,packet_words=0,done_words=0;
    reg [511:0] read_word;
    reg monitor=0,expect_fault=0;
    integer w_done_snapshot=0,blocked_write_cycles=0;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n&&monitor)begin
            if(fault&&!expect_fault)$fatal(1,"autonomous controller fault=%0d state=%0d",fault_code,control.state);
            if(cmd_valid&&cmd_ready)commands=commands+1;
            if(r_done)read_done_count=read_done_count+1;
            if(pdone)pool_done_count=pool_done_count+1;
            if(w_done)write_done_count=write_done_count+1;
            if(wi_valid&&wi_ready)begin
                if(wi_data!==gold[output_words]||wi_index!=packet_words||wi_epoch!=200+commands-1||wi_last!==(packet_words==word_count-1))
                    $fatal(1,"autonomous output mismatch word=%0d idx=%0d epoch=%0d expected_epoch=%0d",output_words,wi_index,wi_epoch,200+commands-1);
                packet_words=packet_words+1;output_words=output_words+1;
            end
            if(w_done)begin
                if(packet_words!=word_count)$fatal(1,"writer done before entire stream accepted");
                packet_words=0;
            end
            if(control.state==7&&writer.busy)begin
                blocked_write_cycles=blocked_write_cycles+1;
                if(arvalid||r_cmd_valid||result_committed)$fatal(1,"read/commit before pending destination write completion");
            end
            if(cb&&cbr&&control.completed_passes!=0&&write_done_count<read_done_count)
                $fatal(1,"next pass configured before prior AXI writer committed");
            if(done)begin
                completions=completions+1;
                if(!result_committed||active||r_busy||w_busy)$fatal(1,"autonomous final commit incomplete");
            end
        end
        if(cycle>2000000)$fatal(1,"autonomous timeout state=%0d output=%0d",control.state,output_words);
    end
    task tick;begin @(posedge clk);#1;end endtask
    task send_command;begin
        while(!cmd_ready)tick();@(negedge clk);cmd_valid=1;tick();@(negedge clk);cmd_valid=0;
    end endtask
    integer n,i,b,offset,seed_cursor=0,case_index;
    initial begin
        $readmemh("input.hex",inputs);$readmemh("golden.hex",gold);$readmemh("cases.hex",cases);
        repeat(5)tick();@(negedge clk);rst_n=1;monitor=1;
        for(n=0;n<3;n=n+1)begin
            case_index=n==0 ? 0 : n+2;
            cmd_channels=cases[case_index][10:0];cmd_height=cases[case_index][20:11];
            done_words=cases[case_index][34:21];cmd_epoch=200+n;passes=n==0 ? 3 : 1;
            cmd_source=BASE;cmd_destination=REGION1;limit=1000000;source_committed=1;
            for(i=0;i<done_words;i=i+1)for(b=0;b<64;b=b+1)memory.bytes[i*64+b]=inputs[seed_cursor+i][b*8+:8];
            seed_cursor=seed_cursor+done_words;send_command();
            // Configuration is latched for the complete three-pass sequence.
            cmd_epoch=0;cmd_source=0;cmd_destination=0;cmd_channels=0;cmd_height=0;passes=0;source_committed=0;
            while(completions<n+1)tick();
            if(completed!==(n==0 ? 2'd3 : 2'd1)||result_address!=REGION1)$fatal(1,"autonomous pass/result identity");
            offset=result_address-BASE;
            for(i=0;i<done_words;i=i+1)begin
                for(b=0;b<64;b=b+1)read_word[b*8+:8]=memory.bytes[offset+i*64+b];
                if(read_word!==gold[output_words-done_words+i])$fatal(1,"autonomous committed memory mismatch");
            end
        end
        if(output_words!=`WORDS||commands!=3||completions!=3||read_done_count!=5||write_done_count!=5||pool_done_count!=5||
            memory.aw_count!=`BURSTS||memory.ar_count!=`BURSTS||memory.b_count!=`BURSTS||memory.w_count!=`WORDS*8||memory.r_count!=`WORDS*8||blocked_write_cycles==0)
            $fatal(1,"autonomous coverage output=%0d cmd=%0d done=%0d",output_words,commands,completions);
        $display("NATIVE_POOL_CHAIN_PASS commands=%0d completed=%0d passes=5 chained_sppf=3 words=%0d AW=%0d W=%0d B=%0d AR=%0d R=%0d blocked_write_cycles=%0d",
            commands,completions,output_words,memory.aw_count,memory.w_count,memory.b_count,memory.ar_count,memory.r_count,blocked_write_cycles);
        $finish;
    end
endmodule
