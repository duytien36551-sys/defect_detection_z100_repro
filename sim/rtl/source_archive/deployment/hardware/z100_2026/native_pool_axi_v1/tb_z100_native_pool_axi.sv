`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_native_pool_axi;
    localparam [31:0] BASE=32'h10000000,REGION1=32'h10020000;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0;
    reg [31:0] epoch=200,source_address=BASE,destination_address=REGION1;
    reg [10:0] channels=128;reg [9:0] height=20;reg [13:0] word_count=1280;
    reg source_valid[0:1];reg [31:0] source_epoch[0:1];reg [13:0] source_words[0:1];
    reg source_select=0,destination_select=1;
    reg r_cmd_valid=0;wire r_cmd_ready,r_core_ready,r_busy,r_done,r_fault;
    wire [3:0] r_fault_code;wire r_out_valid,r_out_ready,r_out_last;
    wire [31:0] r_out_epoch;wire [12:0] r_out_index;wire [511:0] r_out_data;
    wire committed=source_valid[source_select]&&source_epoch[source_select]==epoch&&source_words[source_select]==word_count;
    assign r_cmd_ready=r_core_ready&&committed;
    wire [5:0] arid,rid;wire [31:0] araddr;wire [3:0] arlen;wire [2:0] arsize;
    wire [1:0] arburst,rresp;wire arvalid,arready,rvalid,rready,rlast;wire [63:0] rdata;
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(r_cmd_valid&&committed),.cmd_ready(r_core_ready),
        .cmd_epoch(epoch),.cmd_address(source_address),.cmd_word_count(word_count),.cancel(1'b0),.timeout(1'b0),.clear_fault(1'b0),
        .busy(r_busy),.done(r_done),.fault(r_fault),.fault_code(r_fault_code),.out_valid(r_out_valid),.out_ready(r_out_ready),
        .out_epoch(r_out_epoch),.out_index(r_out_index),.out_data(r_out_data),.out_last(r_out_last),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_rid(rid),.m_axi_rdata(rdata),.m_axi_rresp(rresp),
        .m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    reg rd_cfg=0,wr_cfg=0;wire rd_cfg_ready,wr_cfg_ready;
    wire rd_valid,rd_ready,rd_last,rd_active,rd_done,rd_error;
    wire [1:0] rd_code;wire [31:0] rd_epoch;wire [12:0] rd_address,rd_index;wire [511:0] rd_data;
    z100_native_stream_order read_order(.clk(clk),.rst_n(rst_n),.cancel(1'b0),.cfg_valid(rd_cfg),.cfg_ready(rd_cfg_ready),
        .cfg_epoch(epoch),.cfg_write_order(1'b0),.cfg_channels(channels),.cfg_height(height),.cfg_width(10'd20),
        .in_valid(r_out_valid),.in_ready(r_out_ready),.in_epoch(r_out_epoch),.in_index(r_out_index),.in_address(13'd0),
        .in_last(r_out_last),.in_data(r_out_data),.out_valid(rd_valid),.out_ready(rd_ready),.out_epoch(rd_epoch),
        .out_index(rd_index),.out_address(rd_address),.out_last(rd_last),.out_data(rd_data),
        .active(rd_active),.done(rd_done),.error_valid(rd_error),.error_code(rd_code));
    reg cb=0,cc=0,jv=0;wire cbr,ccr,jr,sv,loading,pv,pr,plast,pdone,perr,pactive;
    wire [31:0] ae,pe;wire [12:0] pa;wire [511:0] pd;wire [3:0] pec;
    z100_maxpool_store20 pool(.clk(clk),.rst_n(rst_n),.cancel(1'b0),.cfg_begin(cb),.cfg_begin_ready(cbr),
        .cfg_epoch(epoch),.cfg_channels(channels),.cfg_height(height),.cfg_width(10'd20),.cfg_word_valid(rd_valid),.cfg_word_ready(rd_ready),
        .cfg_word_epoch(rd_epoch),.cfg_word_address(rd_address),.cfg_word_last(rd_last),.cfg_data(rd_data),
        .cfg_commit(cc),.cfg_commit_ready(ccr),.store_valid(sv),.loading(loading),.active_epoch(ae),
        .job_valid(jv),.job_ready(jr),.job_epoch(epoch),.job_channels(channels),.job_height(height),.job_width(10'd20),
        .out_valid(pv),.out_ready(pr),.out_epoch(pe),.out_address(pa),.out_data(pd),.out_last(plast),
        .done(pdone),.error_valid(perr),.error_code(pec),.active(pactive));
    wire wi_valid,wi_ready,wi_last,wr_active,wr_done,wr_error;
    wire [31:0] wi_epoch;wire [12:0] wi_index,wi_address;wire [511:0] wi_data;wire [1:0] wr_code;
    z100_native_stream_order write_order(.clk(clk),.rst_n(rst_n),.cancel(1'b0),.cfg_valid(wr_cfg),.cfg_ready(wr_cfg_ready),
        .cfg_epoch(epoch),.cfg_write_order(1'b1),.cfg_channels(channels),.cfg_height(height),.cfg_width(10'd20),
        .in_valid(pv),.in_ready(pr),.in_epoch(pe),.in_index(13'd0),.in_address(pa),.in_last(plast),.in_data(pd),
        .out_valid(wi_valid),.out_ready(wi_ready),.out_epoch(wi_epoch),.out_index(wi_index),.out_address(wi_address),
        .out_last(wi_last),.out_data(wi_data),.active(wr_active),.done(wr_done),.error_valid(wr_error),.error_code(wr_code));
    reg w_cmd_valid=0;wire w_cmd_ready,w_busy,w_done,w_fault;wire [3:0] w_fault_code;
    wire [5:0] awid,wid,bid;wire [31:0] awaddr;wire [3:0] awlen;wire [2:0] awsize;
    wire [1:0] awburst,bresp;wire awvalid,awready,wvalid,wready,wlast,bvalid,bready;
    wire [63:0] wdata;wire [7:0] wstrb;
    z100_native_axi64_writer writer(.clk(clk),.rst_n(rst_n),.cmd_valid(w_cmd_valid),.cmd_ready(w_cmd_ready),
        .cmd_epoch(epoch),.cmd_address(destination_address),.cmd_word_count(word_count),.in_valid(wi_valid),.in_ready(wi_ready),
        .in_epoch(wi_epoch),.in_index(wi_index),.in_data(wi_data),.in_last(wi_last),.cancel(1'b0),.timeout(1'b0),.clear_fault(1'b0),
        .busy(w_busy),.done(w_done),.fault(w_fault),.fault_code(w_fault_code),.m_axi_awid(awid),.m_axi_awaddr(awaddr),
        .m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),.m_axi_awvalid(awvalid),.m_axi_awready(awready),
        .m_axi_wid(wid),.m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
        .m_axi_bid(bid),.m_axi_bresp(bresp),.m_axi_bvalid(bvalid),.m_axi_bready(bready));
    axi3_byte_memory memory(.clk(clk),.rst_n(rst_n),.awid(awid),.awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),
        .awvalid(awvalid),.awready(awready),.wid(wid),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.wvalid(wvalid),.wready(wready),
        .bid(bid),.bresp(bresp),.bvalid(bvalid),.bready(bready),.arid(arid),.araddr(araddr),.arlen(arlen),.arsize(arsize),
        .arburst(arburst),.arvalid(arvalid),.arready(arready),.rid(rid),.rdata(rdata),.rresp(rresp),.rlast(rlast),.rvalid(rvalid),.rready(rready));
    reg [511:0] inputs[0:`INPUT_WORDS-1],gold[0:`WORDS-1];
    reg [35:0] cases[0:`CASES-1];
    integer cycle=0,read_done_count=0,write_done_count=0,pool_done_count=0;
    integer output_words=0,gold_cursor=0,packet_words=0,blocked_probes=0,partial_probes=0,forbidden_ar=0;
    reg probing=0;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n)begin
            if(r_fault||w_fault||perr||rd_error||wr_error)$fatal(1,"coupled fault r=%0d/%0d w=%0d/%0d pool=%0d/%0d codec=%0d/%0d",r_fault,r_fault_code,w_fault,w_fault_code,perr,pec,rd_error,wr_error);
            if(r_done)read_done_count=read_done_count+1;
            if(pdone)pool_done_count=pool_done_count+1;
            if(w_done)begin
                write_done_count=write_done_count+1;source_valid[destination_select]=1;
                source_epoch[destination_select]=epoch;source_words[destination_select]=word_count;
            end
            if(wi_valid&&wi_ready)begin
                if(wi_data!==gold[gold_cursor+packet_words]||wi_index!=packet_words||wi_epoch!=epoch||wi_last!==(packet_words==word_count-1))
                    $fatal(1,"coupled packed output mismatch global=%0d index=%0d",gold_cursor+packet_words,wi_index);
                packet_words=packet_words+1;output_words=output_words+1;
            end
            if(probing)begin
                blocked_probes=blocked_probes+1;
                if(r_cmd_ready||arvalid)begin forbidden_ar=forbidden_ar+1;$fatal(1,"uncommitted destination read admitted");end
                if(memory.w_count>0&&write_done_count<read_done_count)partial_probes=partial_probes+1;
            end
        end
        if(cycle>2000000)$fatal(1,"coupled timeout outputs=%0d",output_words);
    end
    task tick;begin @(posedge clk);#1;end endtask
    integer c,i,b,offset,input_cursor=0,aw_before,w_before,goal,seed_new;
    reg [511:0] memory_word;
    reg previous_destination;
    initial begin
        $readmemh("input.hex",inputs);$readmemh("golden.hex",gold);$readmemh("cases.hex",cases);
        source_valid[0]=0;source_valid[1]=0;source_epoch[0]=0;source_epoch[1]=0;source_words[0]=0;source_words[1]=0;
        repeat(5)tick();@(negedge clk);rst_n=1;
        for(c=0;c<`CASES;c=c+1)begin
            channels=cases[c][10:0];height=cases[c][20:11];word_count=cases[c][34:21];seed_new=cases[c][35];
            epoch=c<3 ? 200 : 198+c;packet_words=0;
            if(seed_new)begin
                source_select=0;destination_select=1;source_address=BASE;destination_address=REGION1;
                for(i=0;i<word_count;i=i+1)for(b=0;b<64;b=b+1)memory.bytes[i*64+b]=inputs[input_cursor+i][b*8+:8];
                input_cursor=input_cursor+word_count;source_valid[0]=1;source_epoch[0]=epoch;source_words[0]=word_count;
            end else begin
                previous_destination=destination_select;source_select=previous_destination;destination_select=!previous_destination;
                source_address=source_select ? REGION1 : BASE;destination_address=destination_select ? REGION1 : BASE;
                if(!source_valid[source_select])$fatal(1,"chain source not committed");
            end
            source_valid[destination_select]=0;
            while(!cbr||!rd_cfg_ready)tick();@(negedge clk);cb=1;rd_cfg=1;tick();@(negedge clk);cb=0;rd_cfg=0;
            while(!r_cmd_ready)tick();@(negedge clk);r_cmd_valid=1;tick();@(negedge clk);r_cmd_valid=0;
            while(read_done_count<c+1)tick();
            while(!ccr)tick();@(negedge clk);cc=1;tick();@(negedge clk);cc=0;
            tick();if(!sv||ae!=epoch)$fatal(1,"AXI-loaded source did not commit");
            while(!wr_cfg_ready||!w_cmd_ready||!jr)tick();
            aw_before=memory.aw_count;w_before=memory.w_count;
            @(negedge clk);wr_cfg=1;w_cmd_valid=1;tick();@(negedge clk);wr_cfg=0;w_cmd_valid=0;
            jv=1;tick();@(negedge clk);jv=0;
            // Probe after real partial W activity, before the final B response.
            while(memory.w_count==w_before)tick();
            if(write_done_count>=c+1)$fatal(1,"partial-write probe too late");
            @(negedge clk);source_select=destination_select;source_address=destination_address;r_cmd_valid=1;probing=1;
            repeat(20)tick();@(negedge clk);r_cmd_valid=0;probing=0;
            while(write_done_count<c+1||pool_done_count<c+1)tick();
            if(packet_words!=word_count||w_busy||r_busy||!source_valid[destination_select])$fatal(1,"incomplete semantic/AXI completion");
            offset=destination_address-BASE;
            for(i=0;i<word_count;i=i+1)begin
                for(b=0;b<64;b=b+1)memory_word[b*8+:8]=memory.bytes[offset+i*64+b];
                if(memory_word!==gold[gold_cursor+i])$fatal(1,"committed byte-memory mismatch case=%0d word=%0d",c,i);
            end
            gold_cursor=gold_cursor+word_count;
        end
        if(output_words!=`WORDS||memory.w_count!=`WORDS*8||memory.r_count!=`WORDS*8||memory.aw_count!=`BURSTS||memory.ar_count!=`BURSTS||
           memory.b_count!=`BURSTS||blocked_probes!=100||partial_probes!=100||forbidden_ar!=0||memory.w_holds==0||memory.ar_holds==0)
            $fatal(1,"coupled coverage out=%0d W=%0d R=%0d AW=%0d AR=%0d B=%0d probes=%0d/%0d",output_words,memory.w_count,memory.r_count,memory.aw_count,memory.ar_count,memory.b_count,blocked_probes,partial_probes);
        $display("NATIVE_POOL_AXI_PASS passes=%0d chained_sppf=3 words=%0d bytes=%0d AW=%0d W=%0d B=%0d AR=%0d R=%0d blocked_partial_probes=%0d forbidden_AR=%0d read_done=%0d write_done=%0d pool_done=%0d",
            `CASES,output_words,output_words*64,memory.aw_count,memory.w_count,memory.b_count,memory.ar_count,memory.r_count,partial_probes,forbidden_ar,read_done_count,write_done_count,pool_done_count);
        $finish;
    end
endmodule
