`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_native_materialized_load;
    localparam [31:0] BASE=32'h10000000;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cv=0,abort=0,recover=0,committed=1,materialized=1,allow_ar=1,inject_resp=0;
    reg [31:0] ce=200,cgen=1,ca=BASE,ct=1000000;reg [10:0] cc=3;reg [9:0] cfh=640,cw=640,cy=0,ch=39;
    wire cr,active,fault,done,result;wire [3:0] fc;wire [31:0] epoch,generation,address;
    wire [10:0] channels;wire [9:0] height,width;wire [13:0] words,block_words,word_base;
    wire cb,cbr,oc,ocr,odone,commit,commit_ready,rc,rcr,rbusy,rfault,rdone,semantic_cancel,rcancel,rclear;
    wire reader_v,reader_r,reader_last;wire [31:0] reader_ep;wire [12:0] reader_index;wire [511:0] reader_data;wire [3:0] reader_fc;
    wire codec_v,codec_r,codec_last,codec_error,codec_active;wire [1:0] codec_ec;wire [31:0] codec_ep;wire [12:0] codec_address,codec_index;wire [511:0] codec_data;
    wire bwr,berr,bsv,bloading;wire [2:0] bec;wire [31:0] bae;
    wire pipeline_error=codec_error||berr;
    z100_native_materialized_load_control dut(.clk(clk),.rst_n(rst_n),.cmd_valid(cv),.cmd_ready(cr),.cmd_epoch(ce),.cmd_source_generation(cgen),.cmd_source_address(ca),.cmd_timeout_cycles(ct),
        .cmd_channels(cc),.cmd_full_height(cfh),.cmd_width(cw),.cmd_first_row(cy),.cmd_height(ch),.cmd_source_committed(committed),.cmd_source_is_materialized(materialized),
        .abort(abort),.recover(recover),.active(active),.fault(fault),.fault_code(fc),.done(done),.result_committed(result),
        .epoch(epoch),.source_generation(generation),.channels(channels),.height(height),.width(width),.total_words(words),.block_words(block_words),.block_word_base(word_base),
        .feature_begin(cb),.feature_begin_ready(cbr),.order_config(oc),.order_config_ready(ocr),.order_done(odone),.feature_commit(commit),.feature_commit_ready(commit_ready),
        .reader_command(rc),.reader_command_ready(rcr),.reader_address(address),.reader_done(rdone),.reader_busy(rbusy),.reader_fault(rfault),.pipeline_error(pipeline_error),
        .semantic_cancel(semantic_cancel),.reader_cancel(rcancel),.reader_clear_fault(rclear));
    wire [5:0] arid,rid;wire [31:0] araddr;wire [3:0] arlen;wire [2:0] arsize;wire [1:0] arburst,rresp;
    wire arvalid,arready,rvalid,rready,rlast;wire [63:0] rdata;
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(rc),.cmd_ready(rcr),.cmd_epoch(epoch),.cmd_address(address),.cmd_word_count(block_words),
        .cancel(rcancel),.timeout(1'b0),.clear_fault(rclear),.busy(rbusy),.done(rdone),.fault(rfault),.fault_code(reader_fc),
        .out_valid(reader_v),.out_ready(reader_r),.out_epoch(reader_ep),.out_index(reader_index),.out_data(reader_data),.out_last(reader_last),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
        .m_axi_rid(rid),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    wire [13:0] global_index=word_base+reader_index;
    z100_native_stream_order codec(.clk(clk),.rst_n(rst_n),.cancel(semantic_cancel),.cfg_valid(oc),.cfg_ready(ocr),.cfg_epoch(epoch),.cfg_write_order(1'b0),.cfg_channels(channels),.cfg_height(height),.cfg_width(width),
        .in_valid(reader_v),.in_ready(reader_r),.in_epoch(reader_ep),.in_index(global_index[12:0]),.in_address(13'd0),.in_last(global_index+1==words),.in_data(reader_data),
        .out_valid(codec_v),.out_ready(codec_r),.out_epoch(codec_ep),.out_index(codec_index),.out_address(codec_address),.out_last(codec_last),.out_data(codec_data),.active(codec_active),.done(odone),.error_valid(codec_error),.error_code(codec_ec));
    integer cycle=0;wire sink_allow=cycle%31>7;
    assign codec_r=bwr&&sink_allow;
    reg bqv=0;reg [1663:0] bqa=0;reg [127:0] bqm=0;wire bqr,bov;wire [31:0] boe;wire [1023:0] bod;
    z100_feature_banks_load_order bank(.clk(clk),.rst_n(rst_n),.cancel(semantic_cancel),.cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(epoch),.cfg_canonical_order(1'b0),.cfg_channels(channels),.cfg_height(height),.cfg_width(width),
        .cfg_word_valid(codec_v&&sink_allow),.cfg_word_ready(bwr),.cfg_word_data(codec_data),.cfg_word_epoch(codec_ep),.cfg_word_address(codec_address),.cfg_word_last(codec_last),
        .cfg_commit(commit),.cfg_commit_ready(commit_ready),.error_valid(berr),.error_code(bec),.store_valid(bsv),.active_epoch(bae),.loading(bloading),
        .req_valid(bqv),.req_ready(bqr),.req_epoch(epoch),.req_addresses(bqa),.req_mask(bqm),.out_valid(bov),.out_ready(1'b1),.out_epoch(boe),.out_data(bod));
    reg [511:0] memory[0:`MEMWORDS-1],gold[0:`WORDS-1];reg [128:0] cases[0:`TILES-1];reg [35:0] expected_ar[0:`ARS-1];
    reg score=0,mem_busy=0,arheld=0,outputheld=0;reg [31:0] mem_addr,held_addr;reg [3:0] beat=0,last_beat=0,held_len;
    reg [557:0] held_payload;integer read_commands=0,ars=0,rbeats=0,loaded=0,readback=0,completed=0,recoveries=0,drain_probes=0,stalls=0;
    wire [31:0] read_byte_address=mem_addr+{25'd0,beat,3'd0};
    assign arready=rst_n&&allow_ar&&!mem_busy&&cycle%7!=0;
    assign rvalid=rst_n&&mem_busy&&cycle%11!=0&&cycle%11!=1;
    assign rdata=memory[(read_byte_address-BASE)>>6][read_byte_address[5:3]*64+:64];
    assign rid=0;assign rresp=inject_resp?2'b10:2'b00;assign rlast=beat==last_beat;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n)begin
            if(arheld&&(!arvalid||araddr!==held_addr||arlen!==held_len))$fatal(1,"materialized AR unstable during hold/cancel");
            arheld=arvalid&&!arready;if(arheld)begin held_addr=araddr;held_len=arlen;end
            if(arvalid&&arready)begin
                if(arid!=0||arsize!=3||arburst!=1||araddr[5:0]!=0||araddr<BASE||((araddr-BASE)>>6)>=`MEMWORDS||{1'b0,araddr[11:0]}+({9'd0,arlen}+1)*8>4096)$fatal(1,"bad burst request");
                if(score)begin if(ars>=`ARS||{arlen,araddr}!==expected_ar[ars])$fatal(1,"materialized burst address/length mismatch AR=%0d got=%08x/%0d",ars,araddr,arlen);ars=ars+1;end
                mem_busy<=1;mem_addr<=araddr;last_beat<=arlen;beat<=0;
            end
            if(rvalid&&rready)begin if(score)rbeats=rbeats+1;if(rlast)mem_busy<=0;else beat<=beat+1;end
            if(score)begin
                if(fault||pipeline_error)$fatal(1,"materialized load fault=%0d/%0d pipeline=%0d/%0d",fault,fc,codec_ec,bec);
                if(rc&&rcr)read_commands=read_commands+1;
                if(outputheld&&(!codec_v||{codec_ep,codec_address,codec_last,codec_data}!==held_payload))$fatal(1,"materialized loader output unstable");
                outputheld=codec_v&&!codec_r;if(outputheld)begin held_payload={codec_ep,codec_address,codec_last,codec_data};stalls=stalls+1;end
                if(codec_v&&codec_r)loaded=loaded+1;
                if(done)begin if(!bsv||!result||rbusy||codec_active)$fatal(1,"cache published before codec/reader/commit retirement");completed=completed+1;end
            end else outputheld=0;
        end
        if(cycle>8000000)$fatal(1,"materialized watchdog");
    end
    task tick;begin @(posedge clk);#1;end endtask
    task set_case(input integer i);begin
        ca=cases[i][31:0];cc=cases[i][42:32];cfh=cases[i][52:43];cw=cases[i][62:53];cy=cases[i][72:63];ch=cases[i][82:73];
        ce=200;cgen=(ca>>6)+1;ct=1000000;committed=1;materialized=1;
    end endtask
    task command;begin while(!cr)tick();@(negedge clk);cv=1;tick();@(negedge clk);cv=0;end endtask
    task recovery;integer n;begin
        n=0;while(rbusy)begin if(cr||done||result||!rcancel)$fatal(1,"unsafe materialized drain");drain_probes=drain_probes+1;tick();n=n+1;if(n>1000)$fatal(1,"drain timeout");end
        @(negedge clk);recover=1;tick();@(negedge clk);recover=0;n=0;while(active)begin tick();n=n+1;if(n>100)$fatal(1,"recovery timeout");end
        if(fault||rfault||bsv||result||codec_active)$fatal(1,"stale materialized cache ownership");recoveries=recoveries+1;
    end endtask
    integer i,j,b,k,offset,count,goal;
    initial begin
        $readmemh("source.hex",memory);$readmemh("gold.hex",gold);$readmemh("cases.hex",cases);$readmemh("expected_ar.hex",expected_ar);
        repeat(5)tick();@(negedge clk);rst_n=1;
        for(j=0;j<12;j=j+1)begin
            set_case(0);
            case(j)0:ce=0;1:cgen=0;2:cc=0;3:cw=641;4:cfh=0;5:ch=0;6:cy=cfh;7:ca=ca+1;8:ct=0;9:committed=0;10:materialized=0;11:begin ca=32'hffffffc0;cc=1024;cfh=640;cw=640;ch=1;end endcase
            command();while(!fault)tick();if(fc!=1||arvalid||result)$fatal(1,"bad materialized command admitted");recovery();
        end
        set_case(0);allow_ar=0;command();while(!arvalid)tick();@(negedge clk);abort=1;tick();@(negedge clk);abort=0;
        repeat(20)begin if(!arvalid||!fault||cr||result||done||!rcancel)$fatal(1,"held AR abort ownership");drain_probes=drain_probes+1;tick();end allow_ar=1;recovery();
        set_case(0);allow_ar=0;ct=20;command();while(!fault)tick();if(fc!=3)$fatal(1,"materialized timeout code");repeat(10)tick();allow_ar=1;recovery();
        set_case(0);inject_resp=1;command();while(!fault)tick();if(fc!=4)$fatal(1,"materialized read error code");recovery();inject_resp=0;
        score=1;
        for(i=0;i<`TILES;i=i+1)begin
            set_case(i);offset=cases[i][128:97];count=cases[i][96:83];goal=completed+1;command();
            ca=32'hffffffc0;cc=0;cfh=0;cw=0;cy=640;ch=0;ce=0;cgen=0;committed=0;materialized=0;
            while(!done)tick();if(!result||!bsv||bae!=200||words!=count)$fatal(1,"materialized tile not committed");tick();
            for(k=0;k<count;k=k+1)begin
                @(negedge clk);bqv=1;bqm=128'h55555555555555555555555555555555;
                for(b=0;b<64;b=b+1)begin bqa[(b*2)*13+:13]=k;bqa[(b*2+1)*13+:13]=k;end
                #1;while(!bqr)begin tick();@(negedge clk);#1;end tick();
                if(!bov||boe!=200)$fatal(1,"materialized readback epoch");
                for(b=0;b<64;b=b+1)if(bod[(b*2)*8+:8]!==gold[offset+k][b*8+:8]||bod[(b*2+1)*8+:8]!==0)$fatal(1,"materialized halo mismatch tile=%0d word=%0d bank=%0d",i,k,b);
                readback=readback+1;@(negedge clk);bqv=0;tick();
            end
        end
        if(completed!=`TILES||read_commands!=`COMMANDS||ars!=`ARS||rbeats!=`WORDS*8||loaded!=`WORDS||readback!=`WORDS||recoveries!=15||drain_probes<30||stalls==0)$fatal(1,"materialized coverage");
        $display("MATERIALIZED_LOAD_PASS tiles=%0d words=%0d readback=%0d commands=%0d AXI_AR=%0d AXI_R=%0d recoveries=%0d drain_probes=%0d stalls=%0d cycles=%0d",completed,loaded,readback,read_commands,ars,rbeats,recoveries,drain_probes,stalls,cycle);
        $finish;
    end
endmodule
