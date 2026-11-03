`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_axi_read_arbiter_v2;
    reg clk=0;always #5 clk=~clk;reg rst_n=0;
    reg[1:0] cmd_valid=0,cancel=0,clear_fault=0,out_ready=0;
    reg[31:0] epochs[0:1],addresses[0:1];reg[13:0] words[0:1];
    wire[1:0] cmd_ready,busy,done,fault,ov,ol;wire[31:0] oe[0:1];wire[12:0] oi[0:1];wire[511:0] od[0:1];
    wire[11:0] s_arid,s_rid;wire[63:0] s_araddr;wire[7:0] s_arlen;wire[5:0] s_arsize;wire[3:0] s_arburst,s_rresp;
    wire[1:0] s_arvalid,s_arready,s_rvalid,s_rready,s_rlast;wire[127:0] s_rdata;
    genvar g;generate for(g=0;g<2;g=g+1)begin:master
        z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid[g]),.cmd_ready(cmd_ready[g]),.cmd_epoch(epochs[g]),.cmd_address(addresses[g]),.cmd_word_count(words[g]),
            .cancel(cancel[g]),.timeout(1'b0),.clear_fault(clear_fault[g]),.busy(busy[g]),.done(done[g]),.fault(fault[g]),.fault_code(),
            .out_valid(ov[g]),.out_ready(out_ready[g]),.out_epoch(oe[g]),.out_index(oi[g]),.out_data(od[g]),.out_last(ol[g]),
            .m_axi_arid(s_arid[g*6+:6]),.m_axi_araddr(s_araddr[g*32+:32]),.m_axi_arlen(s_arlen[g*4+:4]),.m_axi_arsize(s_arsize[g*3+:3]),.m_axi_arburst(s_arburst[g*2+:2]),
            .m_axi_arvalid(s_arvalid[g]),.m_axi_arready(s_arready[g]),.m_axi_rid(s_rid[g*6+:6]),.m_axi_rdata(s_rdata[g*64+:64]),.m_axi_rresp(s_rresp[g*2+:2]),.m_axi_rlast(s_rlast[g]),.m_axi_rvalid(s_rvalid[g]),.m_axi_rready(s_rready[g]));
    end endgenerate
    wire[5:0] m_arid;wire[31:0] m_araddr;wire[3:0] m_arlen;wire[2:0] m_arsize;wire[1:0] m_arburst;
    wire m_arvalid,m_rready,active,active_owner,protocol_fault;
    reg m_rvalid=0,m_rlast=0;reg[5:0] m_rid=0;reg[63:0] m_rdata=0;reg[1:0] m_rresp=0;
    reg block_ar=0,block_r=0,inject_resp=0,inject_id=0;integer cycle=0;wire m_arready=!block_ar&&cycle%7!=0;
    z100_native_axi_read_arbiter dut(.*);
    reg mem_active=0;reg[31:0] mem_address=0;reg mem_owner=0;integer mem_beat=0,mem_beats=0;
    integer ar_count=0,r_count=0,owner_beats[0:1],output_words=0,held_ar=0,held_r=0,completed=0,recovered=0;
    integer expected_index[0:1];reg[31:0] expected_epoch[0:1],expected_base[0:1];reg[13:0] expected_words[0:1];reg[1:0] check_data=3;
    reg ar_held=0,r_held=0;reg[46:0] saved_ar;reg[72:0] saved_r;
    function automatic[63:0] datum(input[31:0] a);datum={a^32'h93ca0157,a^32'h65b2f891};endfunction
    integer k,b;always @(posedge clk)begin
        cycle<=cycle+1;
        if(rst_n)begin
            if(ar_held&&(!m_arvalid||{m_arid,m_araddr,m_arlen,m_arsize,m_arburst}!==saved_ar))$fatal(1,"Physical AR changed while held/cancelled");
            ar_held<=m_arvalid&&!m_arready;saved_ar<={m_arid,m_araddr,m_arlen,m_arsize,m_arburst};
            if(r_held&&(!m_rvalid||{m_rid,m_rdata,m_rresp,m_rlast}!==saved_r))$fatal(1,"TB physical R held data changed");
            r_held<=m_rvalid&&!m_rready;saved_r<={m_rid,m_rdata,m_rresp,m_rlast};
            if(ar_held)held_ar<=held_ar+1;if(r_held)held_r<=held_r+1;
            if(s_rvalid!=0&&(s_rvalid&(s_rvalid-1))!=0)$fatal(1,"Read response routed to multiple masters");
            if(m_rvalid&&m_rready)begin
                if(!active||active_owner!=mem_owner||!s_rvalid[mem_owner])$fatal(1,"Read owner changed before RLAST");
                r_count<=r_count+1;owner_beats[mem_owner]<=owner_beats[mem_owner]+1;m_rvalid<=0;
                if(m_rlast)mem_active<=0;else mem_beat<=mem_beat+1;
            end
            if(m_arvalid&&m_arready)begin
                if(mem_active||m_arid!=0||m_arsize!=3||m_arburst!=1||m_araddr[11:0]+(m_arlen+1)*8>4096)$fatal(1,"Shared reader physical AXI transaction");
                mem_active<=1;mem_address<=m_araddr;mem_owner<=active_owner;mem_beat<=0;mem_beats<=m_arlen+1;ar_count<=ar_count+1;
            end
            if(mem_active&&!m_rvalid&&!block_r&&cycle%3!=0)begin
                m_rvalid<=1;m_rdata<=datum(mem_address+mem_beat*8);m_rid<=inject_id?1:0;
                m_rresp<=inject_resp&&mem_beat==2?2:0;m_rlast<=mem_beat+1==mem_beats;
            end
            for(k=0;k<2;k=k+1)begin
                if(ov[k]&&out_ready[k]&&check_data[k])begin
                    if(oe[k]!=expected_epoch[k]||oi[k]!=expected_index[k]||ol[k]!=(expected_index[k]+1==expected_words[k]))$fatal(1,"Shared owner result metadata");
                    for(b=0;b<8;b=b+1)if(od[k][b*64+:64]!==datum(expected_base[k]+expected_index[k]*64+b*8))$fatal(1,"Shared owner result data");
                    expected_index[k]=expected_index[k]+1;output_words=output_words+1;
                end
                if(done[k])completed=completed+1;
            end
        end
    end
    always @(negedge clk)if(rst_n)begin out_ready[0]=cycle%257>=160;out_ready[1]=cycle%293>=180;end
    task issue_pair(input integer round_id);integer n;begin
        @(negedge clk);
        for(n=0;n<2;n=n+1)begin
            epochs[n]=200+round_id*2+n;addresses[n]=32'h30000f80+n*32'h10000+round_id*32'h20000;
            case(round_id%4)0:words[n]=1;1:words[n]=2;2:words[n]=3;3:words[n]=17;endcase
            expected_epoch[n]=epochs[n];expected_base[n]=addresses[n];expected_words[n]=words[n];expected_index[n]=0;
        end
        cmd_valid=3;
        while(cmd_valid!=0)begin @(posedge clk);if(cmd_ready[0])cmd_valid[0]<=0;if(cmd_ready[1])cmd_valid[1]<=0;end
        @(negedge clk);epochs[0]=99;epochs[1]=99;addresses[0]=0;addresses[1]=0;
    end endtask
    task recover_faults;begin
        @(negedge clk);clear_fault=3;
        do @(negedge clk);while(fault!=0||busy!=0||active);clear_fault=0;cancel=0;recovered=recovered+1;
    end endtask
    integer round_id,start_ars,old_completed;
    initial begin
        owner_beats[0]=0;owner_beats[1]=0;expected_index[0]=0;expected_index[1]=0;
        repeat(5)@(negedge clk);rst_n=1;
        for(round_id=0;round_id<24;round_id=round_id+1)begin
            issue_pair(round_id);do @(negedge clk);while(busy!=0||active||cmd_valid!=0);
            if(fault!=0||protocol_fault||expected_index[0]!=expected_words[0]||expected_index[1]!=expected_words[1])$fatal(1,"Paired reader completion/parity");
        end
        old_completed=completed;start_ars=ar_count;check_data=0;block_ar=1;issue_pair(24);
        do @(negedge clk);while(!m_arvalid);cancel[active_owner]=1;
        repeat(8)begin @(negedge clk);if(!m_arvalid||!active||ar_count!=start_ars)$fatal(1,"Held AR abandoned or another owner admitted");end
        block_ar=0;do @(negedge clk);while(busy!=0||active);cancel=0;
        if(protocol_fault||fault==0)$fatal(1,"Cancelled reader did not fail/drain in isolation");recover_faults();
        inject_resp=1;issue_pair(25);do @(negedge clk);while(busy!=0||active);inject_resp=0;
        if(protocol_fault||fault!=3)$fatal(1,"Legal AXI RRESP must reach original readers without poisoning arbiter");recover_faults();
        // ID violation quarantines future ARs, retaining selected burst until
        // physical RLAST. This is not cleared with a client-local recovery.
        inject_id=1;issue_pair(26);do @(negedge clk);while(!protocol_fault);
        inject_id=0;do @(negedge clk);while(active);repeat(8)@(negedge clk);
        if(s_arready!=0||m_arvalid)$fatal(1,"Protocol quarantine admitted new physical transaction");
        if(owner_beats[0]<100||owner_beats[1]<100||held_ar<8||held_r<100||completed<48||recovered!=2)$fatal(1,"Shared read coverage incomplete");
        $display("AXI_READ_ARBITER_PASS paired_rounds=24 successful_jobs=48 AXI_AR=%0d AXI_R=%0d owner0_R=%0d owner1_R=%0d held_AR_cycles=%0d held_R_cycles=%0d recovered_rounds=%0d protocol_quarantine=1",ar_count,r_count,owner_beats[0],owner_beats[1],held_ar,held_r,recovered);
        $finish;
    end
    initial begin #10000000;$fatal(1,"Shared read watchdog");end
endmodule
`default_nettype wire
