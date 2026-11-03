// TB responder: two real readers share one physical AXI read channel.
wire[5:0] shared_arid;wire[31:0] shared_araddr;wire[3:0] shared_arlen;
wire[2:0] shared_arsize;wire[1:0] shared_arburst;
wire shared_arvalid,shared_rready,shared_active,shared_owner,shared_fault;
wire shared_arready=rst_n&&!shared_mem_active&&(pf_cycles%7)!=0;
reg shared_rvalid=0,shared_rlast=0;reg[63:0] shared_rdata=0;
wire[11:0] shared_s_rid;wire[127:0] shared_s_rdata;wire[3:0] shared_s_rresp;
wire[1:0] shared_s_arready,shared_s_rvalid,shared_s_rlast;
assign {pp_arready,pf_arready}=shared_s_arready;
assign {pp_axi_rid,pf_axi_rid}=shared_s_rid;
assign {pp_axi_rdata,pf_axi_rdata}=shared_s_rdata;
assign {pp_axi_rresp,pf_axi_rresp}=shared_s_rresp;
assign {pp_axi_rvalid,pf_rvalid}=shared_s_rvalid;
assign {pp_axi_rlast,pf_axi_rlast}=shared_s_rlast;
z100_native_axi_read_arbiter shared_read_bus(.clk(clk),.rst_n(rst_n),
    .s_arid({pp_arid,pf_arid}),.s_araddr({pp_araddr,pf_araddr}),.s_arlen({pp_arlen,pf_arlen}),
    .s_arsize({pp_arsize,pf_arsize}),.s_arburst({pp_arburst,pf_arburst}),.s_arvalid({pp_arvalid,pf_arvalid}),
    .s_arready(shared_s_arready),.s_rid(shared_s_rid),.s_rdata(shared_s_rdata),.s_rresp(shared_s_rresp),
    .s_rlast(shared_s_rlast),.s_rvalid(shared_s_rvalid),.s_rready({pp_axi_rready,pf_rready}),
    .m_arid(shared_arid),.m_araddr(shared_araddr),.m_arlen(shared_arlen),.m_arsize(shared_arsize),
    .m_arburst(shared_arburst),.m_arvalid(shared_arvalid),.m_arready(shared_arready),
    .m_rid(6'd0),.m_rdata(shared_rdata),.m_rresp(2'd0),.m_rlast(shared_rlast),.m_rvalid(shared_rvalid),
    .m_rready(shared_rready),.active(shared_active),.active_owner(shared_owner),.protocol_fault(shared_fault));
reg shared_mem_active=0,shared_mem_owner=0;
reg[31:0] shared_mem_address=0;integer shared_beat=0,shared_beats=0;
integer shared_ars=0,shared_rs=0,shared_owner0=0,shared_owner1=0,shared_contention=0;
reg shared_hold=0;reg[64:0] shared_held_data;
wire shared_pop=shared_rvalid&&shared_rready;
wire[31:0] shared_address=shared_mem_address+shared_beat*8;
always @(posedge clk)if(rst_n)begin
    if(shared_fault)$fatal(1,"Shared physical read protocol fault");
    if(pp_arvalid&&pf_arvalid)shared_contention<=shared_contention+1;
    if(shared_hold&&(!shared_rvalid||{shared_rlast,shared_rdata}!==shared_held_data))$fatal(1,"Physical shared R changed while held");
    shared_hold<=shared_rvalid&&!shared_rready;shared_held_data<={shared_rlast,shared_rdata};
    if(shared_arvalid&&shared_arready)begin
        if(shared_mem_active||shared_arid!=0||shared_arsize!=3||shared_arburst!=1||
           shared_araddr[11:0]+(shared_arlen+1)*8>4096)$fatal(1,"Shared physical read transaction");
        if(shared_owner)begin
            if(shared_araddr<32'h20000000||shared_araddr+(shared_arlen+1)*8>32'h20000700)$fatal(1,"Physical parameter region");
        end else if(!((shared_araddr>=GA_BASE&&shared_araddr+(shared_arlen+1)*8<=GA_BASE+5120)||
                     (shared_araddr>=PF_BASE&&shared_araddr+(shared_arlen+1)*8<=PF_BASE+81920)))$fatal(1,"Physical feature region");
        shared_mem_active<=1;shared_mem_owner<=shared_owner;shared_mem_address<=shared_araddr;
        shared_beat<=0;shared_beats<=shared_arlen+1;shared_ars<=shared_ars+1;
    end
    if(shared_pop)begin
        if(!shared_active||shared_owner!=shared_mem_owner)$fatal(1,"Physical response owner changed");
        shared_rvalid<=0;shared_rs<=shared_rs+1;
        if(shared_mem_owner)shared_owner1<=shared_owner1+1;else shared_owner0<=shared_owner0+1;
        if(shared_rlast)shared_mem_active<=0;else shared_beat<=shared_beat+1;
    end
    if(shared_mem_active&&!shared_rvalid&&(pf_cycles%11)>1)begin
        shared_rvalid<=1;shared_rlast<=shared_beat+1==shared_beats;
        if(shared_mem_owner)shared_rdata<=pp_memory[(shared_address-32'h20000000)/8];
        else if(shared_address>=GA_BASE&&shared_address<GA_BASE+5120)
            shared_rdata<=ga_memory[(shared_address-GA_BASE)>>6][shared_address[5:3]*64+:64];
        else shared_rdata<=pf_memory[(shared_address-PF_BASE)>>6][shared_address[5:3]*64+:64];
    end
end
task check_shared_read;begin
    if(shared_active||shared_mem_active||shared_rvalid||shared_fault||shared_contention==0||
       shared_owner0!=10880||shared_owner1!=224||shared_rs!=11104||shared_ars!=734)
        $fatal(1,"Shared read coverage/retirement AR=%d R=%d owner0=%d owner1=%d contend=%d",shared_ars,shared_rs,shared_owner0,shared_owner1,shared_contention);
    $display("SHARED_PHYSICAL_READ_PASS AXI_AR=%0d AXI_R=%0d owner0_beats=%0d owner1_beats=%0d contended_cycles=%0d",shared_ars,shared_rs,shared_owner0,shared_owner1,shared_contention);
end endtask
