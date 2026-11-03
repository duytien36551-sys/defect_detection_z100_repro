`timescale 1ns/1ps
module tb_z100_native_pool_chain_faults;
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
    reg allow_aw=1,allow_w=1,allow_b=1,allow_ar=1,allow_r=1;
    reg [1:0] injected_bresp=0,injected_rresp=0;
    axi3_byte_memory_faults memory(.allow_aw(allow_aw),.allow_w(allow_w),.allow_b(allow_b),.allow_ar(allow_ar),.allow_r(allow_r),.injected_bresp(injected_bresp),.injected_rresp(injected_rresp),.clk(clk),.rst_n(rst_n),.awid(awid),.awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),
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
    integer cycle=0,invalid=0,drain_probes=0,recovered=0,done_count=0,good_words=0;
    integer reader_cancels=0,reader_errors=0,timeouts=0,writer_cancels=0,writer_errors=0;
    reg good_run=0;
    reg [511:0] expected[0:1];
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n)begin
            if(axi_clear_fault&&(r_busy||w_busy))$fatal(1,"fault cleared with outstanding AXI work");
            if(recover&&fault&&(r_busy||w_busy))begin
                drain_probes=drain_probes+1;
                if(cmd_ready||axi_clear_fault||result_committed)$fatal(1,"reload/commit during AXI drain");
            end
            if(fault&&result_committed)$fatal(1,"failed result was committed");
            if(done)begin if(!good_run||!result_committed)$fatal(1,"fault job reported done");done_count=done_count+1;end
            if(good_run&&wi_valid&&wi_ready)begin
                if(good_words>=2||wi_data!==expected[good_words]||wi_index!=good_words||wi_epoch!=200||wi_last!==(good_words==1))
                    $fatal(1,"post-fault successful output mismatch");
                good_words=good_words+1;
            end
        end
        if(cycle>500000)$fatal(1,"fault test timeout state=%0d read=%0d write=%0d",control.state,reader.state,writer.state);
    end
    task tick;begin @(posedge clk);#1;end endtask
    task defaults;begin
        cmd_epoch=200;cmd_source=BASE;cmd_destination=REGION1;cmd_channels=1;cmd_height=1;passes=1;source_committed=1;limit=1000000;
    end endtask
    task send;begin
        while(!cmd_ready)tick();@(negedge clk);cmd_valid=1;tick();@(negedge clk);cmd_valid=0;
    end endtask
    task recovery;begin
        @(negedge clk);recover=1;
        while(!cmd_ready)tick();@(negedge clk);recover=0;recovered=recovered+1;
        if(fault||r_busy||w_busy||r_fault||w_fault||result_committed)$fatal(1,"recovery not clean");
    end endtask
    task await_fault(input integer code);begin
        while(!fault)tick();
        if(fault_code!=code||result_committed||cmd_ready)$fatal(1,"fault classification %0d expected=%0d",fault_code,code);
    end endtask
    integer n,b,aw0,ar0,r0,w0;
    reg [31:0] held_address;reg [3:0] held_length;
    initial begin
        // One real signed-negative C1x1x20 tile, plus strict zero padding.
        for(n=0;n<128;n=n+1)memory.bytes[n]=0;
        expected[0]=0;expected[1]=0;
        for(n=0;n<20;n=n+1)begin
            memory.bytes[(n/16)*64+n%16]=8'h80+n;
            expected[n/16][(n%16)*8+:8]=8'h80+(n+2<20 ? n+2 : 19);
        end
        repeat(5)tick();@(negedge clk);rst_n=1;
        for(n=0;n<12;n=n+1)begin
            defaults();aw0=memory.aw_count;ar0=memory.ar_count;
            case(n)
                0:cmd_epoch=0;
                1:cmd_channels=0;
                2:cmd_channels=129;
                3:cmd_height=0;
                4:cmd_height=21;
                5:passes=0;
                6:source_committed=0;
                7:limit=0;
                8:cmd_source=BASE+1;
                9:cmd_destination=REGION1+1;
                10:cmd_destination=BASE;
                11:cmd_destination=32'hffffffc0;
            endcase
            send();await_fault(1);repeat(4)tick();
            if(memory.aw_count!=aw0||memory.ar_count!=ar0)$fatal(1,"invalid command touched AXI");
            invalid=invalid+1;recovery();
        end
        // Cancel a still-advertised AR; recovery must wait for AR acceptance
        // and the final R beat, with stable request address/length throughout.
        defaults();allow_ar=0;send();while(!arvalid)tick();held_address=araddr;held_length=arlen;
        @(negedge clk);abort=1;tick();@(negedge clk);abort=0;await_fault(2);recover=1;
        repeat(20)begin tick();if(!arvalid||araddr!==held_address||arlen!==held_length||!r_busy)$fatal(1,"cancel withdrew pending AR");end
        @(negedge clk);allow_ar=1;while(!cmd_ready)tick();@(negedge clk);recover=0;recovered=recovered+1;reader_cancels=reader_cancels+1;
        if(r_fault||w_fault||result_committed)$fatal(1,"reader-cancel recovery");
        // RRESP fault is drained by the actual reader, no local reset.
        defaults();injected_rresp=2;send();await_fault(4);injected_rresp=0;recovery();reader_errors=reader_errors+1;
        // Independent command watchdog while AR remains blocked.
        defaults();allow_ar=0;limit=10;send();await_fault(3);recover=1;
        repeat(20)tick();if(!arvalid||!r_busy||cmd_ready)$fatal(1,"watchdog abandoned AXI");
        @(negedge clk);allow_ar=1;while(!cmd_ready)tick();@(negedge clk);recover=0;recovered=recovered+1;timeouts=timeouts+1;
        // AW cancellation can complete W using the writer's prebuffered burst
        // even though semantic pool output has already been invalidated.
        defaults();allow_aw=0;send();while(!awvalid)tick();held_address=awaddr;held_length=awlen;
        @(negedge clk);abort=1;tick();@(negedge clk);abort=0;await_fault(2);recover=1;
        repeat(20)begin tick();if(!awvalid||awaddr!==held_address||awlen!==held_length||!w_busy)$fatal(1,"cancel withdrew pending AW");end
        @(negedge clk);allow_aw=1;while(!cmd_ready)tick();@(negedge clk);recover=0;recovered=recovered+1;writer_cancels=writer_cancels+1;
        if(r_fault||w_fault||result_committed)$fatal(1,"writer-cancel recovery");
        defaults();injected_bresp=2;send();await_fault(5);injected_bresp=0;recovery();writer_errors=writer_errors+1;
        // A complete recovery command uses the same real cache/AXI datapath.
        defaults();good_run=1;send();while(done_count!=1)tick();
        if(good_words!=2||completed!=1||result_address!=REGION1||r_busy||w_busy||fault)$fatal(1,"post-fault success incomplete");
        for(n=0;n<2;n=n+1)for(b=0;b<64;b=b+1)
            if(memory.bytes[131072+n*64+b]!==expected[n][b*8+:8])$fatal(1,"post-fault memory bytes differ");
        if(invalid!=12||reader_cancels!=1||reader_errors!=1||timeouts!=1||writer_cancels!=1||writer_errors!=1||recovered!=17||drain_probes<60)
            $fatal(1,"fault coverage invalid=%0d recover=%0d probes=%0d",invalid,recovered,drain_probes);
        $display("NATIVE_POOL_CHAIN_FAULT_PASS invalid_commands=%0d reader_cancel=%0d reader_response_error=%0d watchdog=%0d writer_cancel=%0d writer_response_error=%0d recoveries=%0d drain_probes=%0d success_words=%0d done=%0d no_local_AXI_reset=1",
            invalid,reader_cancels,reader_errors,timeouts,writer_cancels,writer_errors,recovered,drain_probes,good_words,done_count);
        $finish;
    end
endmodule
