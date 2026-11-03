`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_native_view_gather;
    localparam [31:0] BASE=32'h10000000;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cb=0,cwv=0,cc=0,cv=0,abort=0,recover=0,ordy=1,allow_ar=1,inject_resp=0;
    reg [31:0] ce=1,epoch=200,te=1,sa=0,rb=0,rowstride=0,xstride=0,ob=0,timeout_cycles=2000000;
    reg [32:0] re=0;reg [9:0] height=1,width=1;reg [2:0] channels=4;reg [1:0] shift=0,context_id=0;reg committed=1;
    reg [7:0] cd=0;wire cbr,cwr,ccr,sv,loading,cerr,cr,active,fault,done;wire [2:0] cec;wire [3:0] fc;
    wire rc,rcr,rbusy,rfault,rcancel,rclear,rv,rr,rlast;wire [31:0] rep,ra,rvep;wire [12:0] ri;wire [511:0] rd;
    wire ov,ol;wire [31:0] oe,oa;wire [511:0] od;
    z100_native_view_gather dut(.clk(clk),.rst_n(rst_n),.cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(ce),.cfg_contexts(3'd4),
        .cfg_word_valid(cwv),.cfg_word_ready(cwr),.cfg_data(cd),.cfg_commit(cc),.cfg_commit_ready(ccr),.store_valid(sv),.loading(loading),.cfg_error(cerr),.cfg_error_code(cec),
        .cmd_valid(cv),.cmd_ready(cr),.cmd_epoch(epoch),.cmd_table_epoch(te),.cmd_source_address(sa),.cmd_region_begin(rb),.cmd_region_end(re),
        .cmd_source_row_stride(rowstride),.cmd_source_x_stride(xstride),.cmd_output_word_base(ob),.cmd_timeout_cycles(timeout_cycles),
        .cmd_height(height),.cmd_width(width),.cmd_channels(channels),.cmd_nearest_shift(shift),.cmd_context(context_id),.cmd_source_committed(committed),
        .abort(abort),.recover(recover),.active(active),.fault(fault),.fault_code(fc),.done(done),
        .read_command(rc),.read_command_ready(rcr),.read_epoch(rep),.read_address(ra),.reader_busy(rbusy),.reader_fault(rfault),.read_cancel(rcancel),.read_clear_fault(rclear),
        .read_valid(rv),.read_ready(rr),.read_result_epoch(rvep),.read_result_index(ri),.read_last(rlast),.read_data(rd),
        .out_valid(ov),.out_ready(ordy),.out_epoch(oe),.out_word_address(oa),.out_data(od),.out_last(ol));
    wire [5:0] arid,rid;wire [31:0] araddr;wire [3:0] arlen;wire [2:0] arsize;wire [1:0] arburst,rresp;
    wire arvalid,arready,rvalid,rready,axi_rlast;wire [63:0] rdata;wire rdone;wire [3:0] rfc;
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(rc),.cmd_ready(rcr),.cmd_epoch(rep),.cmd_address(ra),.cmd_word_count(14'd1),
        .cancel(rcancel),.timeout(1'b0),.clear_fault(rclear),.busy(rbusy),.done(rdone),.fault(rfault),.fault_code(rfc),
        .out_valid(rv),.out_ready(rr),.out_epoch(rvep),.out_index(ri),.out_data(rd),.out_last(rlast),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
        .m_axi_rid(rid),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(axi_rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    reg [511:0] memory[0:`MEMWORDS-1];reg [576:0] words[0:`WORDS-1];reg [272:0] descriptors[0:`DESCRIPTORS-1];
    reg [7:0] tables[0:34*1024-1];reg [31:0] node_desc_count[0:33];
    integer cycle=0,read_requests=0,beats=0,received=0,completed=0,stall_count=0,recoveries=0,drain_probes=0;
    reg score=0,mem_busy=0,held=0,arheld=0;reg [2:0] beat=0;reg [31:0] mem_addr=0,held_araddr;reg [576:0] held_output;
    assign arready=rst_n&&allow_ar&&!mem_busy&&cycle%7!=0;
    assign rvalid=rst_n&&mem_busy&&cycle%11!=0&&cycle%11!=1;
    assign rdata=memory[(mem_addr-BASE)>>6][beat*64+:64];
    assign rid=0;assign rresp=inject_resp?2'b10:2'b00;assign axi_rlast=beat==7;
    always @(negedge clk)ordy=rst_n&&(cycle%37)>8;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n)begin
            if(arheld&&(!arvalid||araddr!==held_araddr))$fatal(1,"AR changed while held including cancel");
            arheld=arvalid&&!arready;if(arheld)held_araddr=araddr;
            if(arvalid&&arready)begin
                if(arid!=0||arlen!=7||arsize!=3||arburst!=1||araddr[5:0]!=0||araddr<BASE||((araddr-BASE)>>6)>=`MEMWORDS)$fatal(1,"invalid gather AXI request");
                if(score)begin if(araddr!==words[read_requests][543:512])$fatal(1,"wrong source address request=%0d got=%08x expected=%08x",read_requests,araddr,words[read_requests][543:512]);read_requests=read_requests+1;end
                mem_busy<=1;mem_addr<=araddr;beat<=0;
            end
            if(rvalid&&rready)begin if(score)beats=beats+1;if(beat==7)mem_busy<=0;else beat<=beat+1;end
            if(score)begin
                if(fault||cerr)$fatal(1,"gather runtime fault=%0d/%0d context=%0d",fault,fc,cec);
                if(held&&(!ov||{oe,ol,oa,od}!==held_output))$fatal(1,"gather output changed while held");
                held=ov&&!ordy;if(held)begin stall_count=stall_count+1;held_output={oe,ol,oa,od};end
                if(ov&&ordy)begin
                    if(oe!=200||oa!==words[received][575:544]||ol!==words[received][576]||od!==words[received][511:0])$fatal(1,"gather output mismatch word=%0d address=%0d",received,oa);
                    received=received+1;
                end
                if(done)completed=completed+1;
            end else held=0;
        end
        if(cycle>12000000)$fatal(1,"gather timeout received=%0d",received);
    end
    task tick;begin @(posedge clk);#1;end endtask
    task load_palette(input integer node);integer i;begin
        while(!cbr)tick();@(negedge clk);cb=1;ce=node+1;tick();@(negedge clk);cb=0;
        for(i=0;i<1024;i=i+1)begin @(negedge clk);cwv=1;cd=tables[node*1024+i];#1;if(!cwr)$fatal(1,"palette loader ready");tick();end
        @(negedge clk);cwv=0;cc=1;#1;if(!ccr)$fatal(1,"palette commit ready");tick();@(negedge clk);cc=0;
        if(!sv||loading||cerr)$fatal(1,"palette commit");
    end endtask
    task set_descriptor(input integer d);begin
        sa=descriptors[d][31:0];rb=descriptors[d][63:32];re={1'b0,descriptors[d][95:64]};rowstride=descriptors[d][127:96];xstride=descriptors[d][159:128];
        ob=descriptors[d][191:160];height=descriptors[d][201:192];width=descriptors[d][211:202];channels=descriptors[d][214:212];
        shift=descriptors[d][216:215];context_id=descriptors[d][218:217];te=descriptors[d][250:219];epoch=200;timeout_cycles=2000000;committed=1;
    end endtask
    task command;begin while(!cr)tick();@(negedge clk);cv=1;tick();@(negedge clk);cv=0;end endtask
    task recovery;integer wait_count;begin
        wait_count=0;
        while(rbusy)begin if(cr||done||ov||!rcancel)$fatal(1,"unsafe gather drain");drain_probes=drain_probes+1;tick();wait_count=wait_count+1;if(wait_count>1000)$fatal(1,"drain timeout");end
        @(negedge clk);recover=1;tick();@(negedge clk);recover=0;wait_count=0;
        while(active)begin tick();wait_count=wait_count+1;if(wait_count>100)$fatal(1,"recovery timeout");end
        if(fault||rfault||ov||done||sv)$fatal(1,"recovery stale ownership");recoveries=recoveries+1;
    end endtask
    integer node,d,j,goal,word_goal,desc_cursor=0;
    initial begin
        $readmemh("source.hex",memory);$readmemh("words.hex",words);$readmemh("descriptors.hex",descriptors);$readmemh("tables.hex",tables);$readmemh("counts.hex",node_desc_count);
        repeat(5)tick();@(negedge clk);rst_n=1;
        for(j=0;j<10;j=j+1)begin
            load_palette(0);set_descriptor(0);
            case(j)0:epoch=0;1:height=0;2:width=641;3:channels=0;4:shift=3;5:committed=0;6:sa=sa+1;7:rowstride=0;8:timeout_cycles=0;9:re={1'b0,rb};endcase
            command();while(!fault)tick();if(fc!=1)$fatal(1,"bad descriptor code");recovery();
        end
        load_palette(0);set_descriptor(0);allow_ar=0;command();while(!arvalid)tick();@(negedge clk);abort=1;tick();@(negedge clk);abort=0;
        repeat(20)begin if(!arvalid||cr||done||ov||!fault||!rcancel)$fatal(1,"held-AR abort ownership");drain_probes=drain_probes+1;tick();end
        allow_ar=1;recovery();
        load_palette(0);set_descriptor(0);allow_ar=0;timeout_cycles=20;command();while(!fault)tick();if(fc!=3)$fatal(1,"watchdog code");
        repeat(10)begin if(!arvalid||cr||done||ov)$fatal(1,"held-AR watchdog ownership");tick();end allow_ar=1;recovery();
        load_palette(0);set_descriptor(0);inject_resp=1;command();while(!fault)tick();if(fc!=4)$fatal(1,"reader error code");recovery();inject_resp=0;
        load_palette(0);set_descriptor(0);sa=re[31:0];command();while(!fault)tick();if(fc!=6||arvalid)$fatal(1,"range guard before AR");recovery();
        score=1;
        for(node=0;node<34;node=node+1)begin
            load_palette(node);goal=desc_cursor+node_desc_count[node];
            for(d=desc_cursor;d<goal;d=d+1)begin
                set_descriptor(d);word_goal=received+descriptors[d][266:251];command();
                // Mutating source command pins during active work must not affect latched ownership.
                sa=32'hfffffff0;rb=0;re=0;height=0;width=0;shift=3;context_id=3;te=0;committed=0;
                while(!done)tick();if(received!=word_goal||!ol)$fatal(1,"descriptor boundary/count");tick();
            end
            desc_cursor=goal;
        end
        if(received!=`WORDS||read_requests!=`WORDS||beats!=`WORDS*8||completed!=`DESCRIPTORS||stall_count==0||recoveries!=14||drain_probes<30)$fatal(1,"gather coverage");
        $display("NATIVE_VIEW_GATHER_PASS nodes=34 descriptors=%0d words=%0d AXI_AR=%0d AXI_R=%0d stalls=%0d recoveries=%0d drain_probes=%0d",completed,received,read_requests,beats,stall_count,recoveries,drain_probes);
        $finish;
    end
endmodule
