`timescale 1ns/1ps
module tb_platform_v13c_control;
reg  clk;
reg  platform_rst_n;
reg [11:0] s_axi_awaddr;
reg  s_axi_awvalid;
wire  s_axi_awready;
reg [31:0] s_axi_wdata;
reg [3:0] s_axi_wstrb;
reg  s_axi_wvalid;
wire  s_axi_wready;
wire [1:0] s_axi_bresp;
wire  s_axi_bvalid;
reg  s_axi_bready;
reg [11:0] s_axi_araddr;
reg  s_axi_arvalid;
wire  s_axi_arready;
wire [31:0] s_axi_rdata;
wire [1:0] s_axi_rresp;
wire  s_axi_rvalid;
reg  s_axi_rready;
wire  irq;
wire [3:0] m_axi_arcache,m_axi_awcache;
wire [2:0] m_axi_arprot,m_axi_awprot;
wire [1:0] m_axi_arlock,m_axi_awlock;
wire [4:0] m_axi_aruser,m_axi_awuser;
wire [2:0] m_axi_arid;
wire [31:0] m_axi_araddr;
wire [3:0] m_axi_arlen;
wire [2:0] m_axi_arsize;
wire [1:0] m_axi_arburst;
wire  m_axi_arvalid;
reg  m_axi_arready;
reg [2:0] m_axi_rid;
reg [63:0] m_axi_rdata;
reg [1:0] m_axi_rresp;
reg  m_axi_rlast;
reg  m_axi_rvalid;
wire  m_axi_rready;
wire [2:0] m_axi_awid;
wire [31:0] m_axi_awaddr;
wire [3:0] m_axi_awlen;
wire [2:0] m_axi_awsize;
wire [1:0] m_axi_awburst;
wire  m_axi_awvalid;
reg  m_axi_awready;
wire [2:0] m_axi_wid;
wire [63:0] m_axi_wdata;
wire [7:0] m_axi_wstrb;
wire  m_axi_wlast;
wire  m_axi_wvalid;
reg  m_axi_wready;
reg [2:0] m_axi_bid;
reg [1:0] m_axi_bresp;
reg  m_axi_bvalid;
wire  m_axi_bready;
z100_native_conv_pool_acp_v1 dut (.clk(clk),
.platform_rst_n(platform_rst_n),
.s_axi_awaddr(s_axi_awaddr),
.s_axi_awvalid(s_axi_awvalid),
.s_axi_awready(s_axi_awready),
.s_axi_wdata(s_axi_wdata),
.s_axi_wstrb(s_axi_wstrb),
.s_axi_wvalid(s_axi_wvalid),
.s_axi_wready(s_axi_wready),
.s_axi_bresp(s_axi_bresp),
.s_axi_bvalid(s_axi_bvalid),
.s_axi_bready(s_axi_bready),
.s_axi_araddr(s_axi_araddr),
.s_axi_arvalid(s_axi_arvalid),
.s_axi_arready(s_axi_arready),
.s_axi_rdata(s_axi_rdata),
.s_axi_rresp(s_axi_rresp),
.s_axi_rvalid(s_axi_rvalid),
.s_axi_rready(s_axi_rready),
.irq(irq),
.m_axi_arcache(m_axi_arcache),
.m_axi_awcache(m_axi_awcache),
.m_axi_arprot(m_axi_arprot),
.m_axi_awprot(m_axi_awprot),
.m_axi_arlock(m_axi_arlock),
.m_axi_awlock(m_axi_awlock),
.m_axi_aruser(m_axi_aruser),
.m_axi_awuser(m_axi_awuser),
.m_axi_arid(m_axi_arid),
.m_axi_araddr(m_axi_araddr),
.m_axi_arlen(m_axi_arlen),
.m_axi_arsize(m_axi_arsize),
.m_axi_arburst(m_axi_arburst),
.m_axi_arvalid(m_axi_arvalid),
.m_axi_arready(m_axi_arready),
.m_axi_rid(m_axi_rid),
.m_axi_rdata(m_axi_rdata),
.m_axi_rresp(m_axi_rresp),
.m_axi_rlast(m_axi_rlast),
.m_axi_rvalid(m_axi_rvalid),
.m_axi_rready(m_axi_rready),
.m_axi_awid(m_axi_awid),
.m_axi_awaddr(m_axi_awaddr),
.m_axi_awlen(m_axi_awlen),
.m_axi_awsize(m_axi_awsize),
.m_axi_awburst(m_axi_awburst),
.m_axi_awvalid(m_axi_awvalid),
.m_axi_awready(m_axi_awready),
.m_axi_wid(m_axi_wid),
.m_axi_wdata(m_axi_wdata),
.m_axi_wstrb(m_axi_wstrb),
.m_axi_wlast(m_axi_wlast),
.m_axi_wvalid(m_axi_wvalid),
.m_axi_wready(m_axi_wready),
.m_axi_bid(m_axi_bid),
.m_axi_bresp(m_axi_bresp),
.m_axi_bvalid(m_axi_bvalid),
.m_axi_bready(m_axi_bready));



integer acp_checked_cycles=0, acp_ar_stalls=0, acp_aw_stalls=0, acp_w_stalls=0;
reg acp_ar_stall_q=0, acp_aw_stall_q=0, acp_w_stall_q=0;
reg [43:0] acp_ar_hold_q;
reg [43:0] acp_aw_hold_q;
reg [75:0] acp_w_hold_q;
always @(posedge clk) if(!platform_rst_n) begin
    acp_ar_stall_q<=0; acp_aw_stall_q<=0; acp_w_stall_q<=0;
end else begin
    acp_checked_cycles<=acp_checked_cycles+1;
    if(m_axi_arcache!==4'hf || m_axi_awcache!==4'hf || m_axi_arprot!==0 || m_axi_awprot!==0 ||
       m_axi_arlock!==0 || m_axi_awlock!==0 || m_axi_aruser!==5'd31 || m_axi_awuser!==5'd31)
        $fatal(1,"ACP_STATIC_ATTRIBUTES");
    if(m_axi_arvalid && m_axi_arid!==0) $fatal(1,"ACP_ARID_NOT_ZERO");
    if(m_axi_awvalid && m_axi_awid!==0) $fatal(1,"ACP_AWID_NOT_ZERO");
    if(m_axi_wvalid && m_axi_wid!==0) $fatal(1,"ACP_WID_NOT_ZERO");
    if(acp_ar_stall_q && (!m_axi_arvalid || {m_axi_arid,m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst}!==acp_ar_hold_q))
        $fatal(1,"ACP_AR_CHANGED_WHILE_STALLED");
    if(acp_aw_stall_q && (!m_axi_awvalid || {m_axi_awid,m_axi_awaddr,m_axi_awlen,m_axi_awsize,m_axi_awburst}!==acp_aw_hold_q))
        $fatal(1,"ACP_AW_CHANGED_WHILE_STALLED");
    if(acp_w_stall_q && (!m_axi_wvalid || {m_axi_wid,m_axi_wdata,m_axi_wstrb,m_axi_wlast}!==acp_w_hold_q))
        $fatal(1,"ACP_W_CHANGED_WHILE_STALLED");
    acp_ar_stall_q<=m_axi_arvalid&&!m_axi_arready;
    acp_aw_stall_q<=m_axi_awvalid&&!m_axi_awready;
    acp_w_stall_q<=m_axi_wvalid&&!m_axi_wready;
    if(m_axi_arvalid&&!m_axi_arready) begin acp_ar_hold_q<={m_axi_arid,m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst};acp_ar_stalls<=acp_ar_stalls+1;end
    if(m_axi_awvalid&&!m_axi_awready) begin acp_aw_hold_q<={m_axi_awid,m_axi_awaddr,m_axi_awlen,m_axi_awsize,m_axi_awburst};acp_aw_stalls<=acp_aw_stalls+1;end
    if(m_axi_wvalid&&!m_axi_wready) begin acp_w_hold_q<={m_axi_wid,m_axi_wdata,m_axi_wstrb,m_axi_wlast};acp_w_stalls<=acp_w_stalls+1;end
end

always #5 clk = ~clk;
initial begin #10000000; $fatal(1,"MMIO/core watchdog"); end
integer reads=0, writes=0, stalls=0, drains=0, resets=0;
reg [31:0] value;
reg [5:0] saved_id;
integer saved_beats, i, j;
reg [31:0] words[0:26];
task reset_platform;
begin
 @(negedge clk); platform_rst_n=0;
 repeat(8) @(negedge clk);
 platform_rst_n=1;
 repeat(8) @(negedge clk);
 resets=resets+1;
end endtask
task read_reg(input [11:0] address, input [1:0] expected_resp, output [31:0] data);
reg [31:0] held; reg [1:0] resp;
begin
 @(negedge clk); s_axi_araddr=address; s_axi_arvalid=1;
 do @(posedge clk); while(!s_axi_arready);
 @(negedge clk); s_axi_arvalid=0;
 while(!s_axi_rvalid) @(negedge clk);
 held=s_axi_rdata; resp=s_axi_rresp;
 repeat(3) begin
  @(negedge clk);
  if(!s_axi_rvalid || s_axi_rdata!==held || s_axi_rresp!==resp) $fatal(1,"R hold");
  stalls=stalls+1;
 end
 if(resp!==expected_resp) $fatal(1,"Unexpected read response %h at %h",resp,address);
 data=held; s_axi_rready=1;
 @(negedge clk); s_axi_rready=0; reads=reads+1;
end endtask
task write_reg(input [11:0] address, input [31:0] data, input [1:0] expected_resp);
begin
 @(negedge clk); s_axi_awaddr=address; s_axi_awvalid=1;
 do @(posedge clk); while(!s_axi_awready);
 @(negedge clk); s_axi_awvalid=0;
 // Address-first transfer deliberately splits AW and W.
 repeat(2) @(negedge clk);
 s_axi_wdata=data; s_axi_wstrb=15; s_axi_wvalid=1;
 do @(posedge clk); while(!s_axi_wready);
 @(negedge clk); s_axi_wvalid=0;
 while(!s_axi_bvalid) @(negedge clk);
 repeat(3) begin
  @(negedge clk);
  if(!s_axi_bvalid || s_axi_bresp!==expected_resp) $fatal(1,"B hold/response at %h",address);
  stalls=stalls+1;
 end
 s_axi_bready=1; @(negedge clk); s_axi_bready=0; writes=writes+1;
end endtask
reg mode_pool=0,stats_reset=0;reg signed [7:0] sample;reg [255:0] descriptor;integer selected_event,pool_index;
function automatic [63:0] numeric_memory_read(input [31:0] address);
integer k, offset_byte, x_pixel; reg [63:0] v; reg [255:0] second_descriptor;
begin
 v=0;
 second_descriptor=descriptor;
 second_descriptor[144:139]=1; second_descriptor[175:160]=1;
 if(address>=32'h900000 && address<32'h900020) v=descriptor[(address-32'h900000)*8+:64];
 else if(address>=32'h900020 && address<32'h900040) v=second_descriptor[(address-32'h900020)*8+:64];
 else if(address>=32'h100000 && address<32'h100080) begin
  for(k=0;k<8;k=k+1) begin
   offset_byte=address-32'h100000+k; x_pixel=(offset_byte/64)*16+(offset_byte%16);
   if((offset_byte%64)<16 && x_pixel<21) v[k*8+:8]=sample;
  end
 end
 else if(address>=32'ha00000 && address<32'ha00020) v=64'h0202020202020202;
 else if(address>=32'ha00100 && address<32'ha00180) v=64'h0000000100000001;
 else if(address>=32'ha00200 && address<32'ha00300) v=64'h0001010000000001;
 else if(address>=32'ha00300 && address<32'ha00400)
  for(k=0;k<8;k=k+1) v[k*8+:8]=((address-32'ha00300+k)^128)&255;
 numeric_memory_read=v;
end endfunction

reg [63:0] source_words[0:10239], expected_words[0:10239];
integer cycle=0,ar_count=0,aw_count=0,w_count=0,b_count=0,r_count=0,bubbles=0,case_id;
reg rb=0,wb=0,bp=0,r_hold=0;
reg [31:0] ra,wa;
reg [5:0] rid_q,wid_q;
integer ri=0,rn=0,wi=0,wn=0,b_delay=0;
always @* begin
 m_axi_arready=platform_rst_n && !rb && cycle%5!=0;
 m_axi_rvalid=platform_rst_n && rb && (r_hold || cycle%7!=0);
 m_axi_rid=rid_q;
 m_axi_rdata=rb ? (mode_pool ? source_words[((ra-32'h100000)>>3)+ri] : numeric_memory_read(ra+ri*8)) : 64'd0;
 m_axi_rlast=rb && ri==rn-1;
 m_axi_rresp=0;
 m_axi_awready=platform_rst_n && !wb && !bp && cycle%3!=0;
 m_axi_wready=platform_rst_n && wb && cycle%4!=0;
 m_axi_bvalid=platform_rst_n && bp && b_delay==0;
 m_axi_bid=wid_q; m_axi_bresp=0;
end
always @(posedge clk) begin
 if(!platform_rst_n || stats_reset) begin
  cycle<=0;rb<=0;wb<=0;bp<=0;r_hold<=0;ri<=0;wi<=0;b_delay<=0;
  ar_count<=0;aw_count<=0;w_count<=0;b_count<=0;r_count<=0;bubbles<=0;
 end else begin
  cycle<=cycle+1;
  if(rb && !m_axi_rvalid || wb && !m_axi_wready || bp && !m_axi_bvalid) bubbles<=bubbles+1;
  if(m_axi_arvalid && m_axi_arready) begin
   if(m_axi_arsize!==3 || m_axi_arburst!==1) $fatal(1,"Mixed HP AR metadata");
   if(mode_pool && (m_axi_araddr!==(32'h100000+ar_count*128) || m_axi_arlen!==15))$fatal(1,"Mixed Pool AR order");
   if(!mode_pool && !((m_axi_araddr>=32'h100000 && m_axi_araddr<32'h100080) ||
       (m_axi_araddr>=32'h900000 && m_axi_araddr<32'h900040) ||
       (m_axi_araddr>=32'ha00000 && m_axi_araddr<32'ha00400)))$fatal(1,"Mixed Conv AR outside fixtures");
   rb<=1;ra<=m_axi_araddr;rid_q<=m_axi_arid;rn<=m_axi_arlen+1;ri<=0;ar_count<=ar_count+1;
  end
  r_hold<=m_axi_rvalid && !m_axi_rready;
  if(m_axi_rvalid && m_axi_rready) begin
   r_count<=r_count+1;
   if(ri==rn-1) rb<=0; else ri<=ri+1;
  end
  if(m_axi_awvalid && m_axi_awready) begin
   if(m_axi_awaddr!==(32'h400000+aw_count*128) || m_axi_awlen!==15 ||
      m_axi_awsize!==3 || m_axi_awburst!==1) $fatal(1,"Pool HP AW shape/order addr=%h n=%0d",m_axi_awaddr,aw_count);
   wb<=1;wa<=m_axi_awaddr;wid_q<=m_axi_awid;wn<=m_axi_awlen+1;wi<=0;aw_count<=aw_count+1;
  end
  if(m_axi_wvalid && m_axi_wready) begin
   if(m_axi_wid!==wid_q || m_axi_wstrb!==8'hff || m_axi_wlast!==(wi==wn-1)) $fatal(1,"Pool W metadata");
   if(m_axi_wdata!==expected_words[((wa-32'h400000)>>3)+wi])
    $fatal(1,"Pool byte parity case=%0d word64=%0d expected=%h actual=%h",case_id,((wa-32'h400000)>>3)+wi,
           expected_words[((wa-32'h400000)>>3)+wi],m_axi_wdata);
   w_count<=w_count+1;
   if(wi==wn-1)begin wb<=0;bp<=1;b_delay<=5;end else wi<=wi+1;
  end
  if(bp && b_delay>0) b_delay<=b_delay-1;
  if(m_axi_bvalid && m_axi_bready) begin bp<=0;b_count<=b_count+1;end
  if(dut.accepted_core.backend_producer_complete && (rb || wb || bp)) $fatal(1,"Pool completion before physical drain");
  if(dut.accepted_core.u_conv_backend.owner_valid && dut.accepted_core.u_conv_backend.owner_pool && dut.accepted_core.u_conv_backend.conv_backend.cmd_valid)
   $fatal(1,"Pool owner admitted a Conv command");
 end
end


// Independent address-based observer at the physical ACP boundary.
integer dx,dk; reg diag_open=0,diag_read_open=0,diag_b_pending=0;
reg [1:0] diag_kind=0; reg [31:0] diag_expected[0:18];
reg [31:0] diag_read_words[0:31]; integer diag_checks=0;
function integer classify_address(input [31:0] address);
begin
 if(address>=32'h100000 && address<32'h300000) classify_address=1;
 else if(address>=32'ha00000 && address<32'hc00000) classify_address=2;
 else if(address>=32'h900000 && address<32'h900040) classify_address=3;
 else classify_address=0;
end endfunction
always @(posedge clk) begin
 if(!platform_rst_n) begin
  diag_open<=0;diag_read_open<=0;diag_b_pending<=0;diag_kind<=0;
  for(dx=0;dx<19;dx=dx+1)diag_expected[dx]<=0;
 end else if(dut.accepted_core.frontend_cmd_valid && dut.accepted_core.backend_cmd_ready) begin
  if(diag_open || diag_read_open || diag_b_pending)$fatal(1,"New event with previous traffic open");
  if(m_axi_arvalid || m_axi_awvalid || m_axi_wvalid || m_axi_rvalid || m_axi_bvalid)$fatal(1,"Traffic on command acceptance edge");
  diag_open<=1;diag_read_open<=0;diag_b_pending<=0;diag_kind<=0;
  for(dx=0;dx<19;dx=dx+1)diag_expected[dx]<=0;
 end else if(diag_open) begin
  diag_expected[0]<=diag_expected[0]+1;
  if(diag_read_open && dut.accepted_core.backend_diagnostic_read_kind!==diag_kind)$fatal(1,"Read kind changed before physical RLAST");
  if(dut.accepted_core.backend_diagnostic_residency_hit && dut.accepted_core.backend_diagnostic_residency_miss)$fatal(1,"Residency hit and miss overlap");
  if(m_axi_arvalid && m_axi_arready) begin
   dk=classify_address(m_axi_araddr);
   if(diag_read_open || dk==0)$fatal(1,"Observer unknown or multiple outstanding AR");
   if(dut.accepted_core.backend_diagnostic_read_kind!==dk[1:0])
    $fatal(1,"Physical AR kind mismatch addr=%h want=%0d got=%0d",m_axi_araddr,dk,dut.accepted_core.backend_diagnostic_read_kind);
   diag_expected[1+(dk-1)*3]<=diag_expected[1+(dk-1)*3]+1;
   diag_read_open<=1;diag_kind<=dk[1:0];
  end
  if(m_axi_rvalid && m_axi_rready) begin
   if(!diag_read_open)$fatal(1,"R before recorded AR");
   diag_expected[2+(diag_kind-1)*3]<=diag_expected[2+(diag_kind-1)*3]+1;
   diag_expected[3+(diag_kind-1)*3]<=diag_expected[3+(diag_kind-1)*3]+8;
   if(m_axi_rlast)diag_read_open<=0;
  end
  if(m_axi_arvalid && !m_axi_arready)diag_expected[10]<=diag_expected[10]+1;
  if(diag_read_open && !m_axi_rvalid)diag_expected[11]<=diag_expected[11]+1;
  if(m_axi_awvalid && m_axi_awready)diag_expected[12]<=diag_expected[12]+1;
  if(m_axi_wvalid && m_axi_wready)begin
   diag_expected[13]<=diag_expected[13]+1;
   // This fixture asserts every physical WSTRB is ff independently.
   diag_expected[14]<=diag_expected[14]+8;
   if(m_axi_wlast)begin
    if(diag_b_pending)$fatal(1,"Multiple pending write responses");
    diag_b_pending<=1;
   end
  end
  if(m_axi_bvalid && m_axi_bready)begin diag_expected[15]<=diag_expected[15]+1;diag_b_pending<=0;end
  if(m_axi_awvalid && !m_axi_awready)diag_expected[16]<=diag_expected[16]+1;
  if(m_axi_wvalid && !m_axi_wready)diag_expected[17]<=diag_expected[17]+1;
  if(diag_b_pending && !m_axi_bvalid)diag_expected[18]<=diag_expected[18]+1;
  if(dut.accepted_core.backend_producer_complete || (dut.accepted_core.backend_fault && dut.accepted_core.backend_all_io_quiet))begin
   if(diag_read_open || diag_b_pending || m_axi_arvalid || m_axi_awvalid || m_axi_wvalid)
    $fatal(1,"Snapshot published with physical traffic outstanding");
   if(dut.accepted_core.hp0_ar_slice.out_valid || dut.accepted_core.hp0_ar_slice.skid_valid || dut.accepted_core.hp0_r_slice.out_valid || dut.accepted_core.hp0_r_slice.skid_valid || dut.accepted_core.hp0_aw_slice.out_valid || dut.accepted_core.hp0_aw_slice.skid_valid || dut.accepted_core.hp0_w_slice.out_valid || dut.accepted_core.hp0_w_slice.skid_valid || dut.accepted_core.hp0_b_slice.out_valid || dut.accepted_core.hp0_b_slice.skid_valid)$fatal(1,"Terminal with register slice occupancy");
   diag_open<=0;
  end
 end
end

task check_diag;
 integer k; reg [31:0] x;
 begin
  if(diag_open)$fatal(1,"RESULT precedes snapshot");
  read_reg(12'h128,0,x);if(x!==32'h5a504331)$fatal(1,"Diagnostic magic");
  read_reg(12'h12c,0,x);if(x!==1)$fatal(1,"Diagnostic version");
  read_reg(12'h130,0,x);if(x!==3)$fatal(1,"Diagnostic success valid status %h",x);
  read_reg(12'h134,0,x);if(x!==200)$fatal(1,"Diagnostic epoch");
  read_reg(12'h138,0,x);if(x!==selected_event)$fatal(1,"Diagnostic event");
  for(k=0;k<32;k=k+1)begin
   read_reg(12'h13c+4*k,0,x);diag_read_words[k]=x;
   if(k<19 && x!==diag_expected[k])$fatal(1,"Physical counter %0d mismatch expect=%0d actual=%0d case=%0d",k,diag_expected[k],x,case_id);
  end
  if(diag_read_words[1]+diag_read_words[4]+diag_read_words[7]!=ar_count ||
     diag_read_words[2]+diag_read_words[5]+diag_read_words[8]!=r_count ||
     diag_read_words[12]!=aw_count || diag_read_words[13]!=w_count || diag_read_words[15]!=b_count)
   $fatal(1,"Diagnostic totals disagree with numeric bus model");
  if(mode_pool && (diag_read_words[19] || diag_read_words[20] || diag_read_words[21] || diag_read_words[30] || diag_read_words[31]))
   $fatal(1,"Pool inherited stale Conv counters");
  if(!mode_pool && (!diag_read_words[19] || !diag_read_words[20] || !diag_read_words[21] || !diag_read_words[31]))
   $fatal(1,"Conv diagnostic activity missing");
  if(diag_read_words[26]>diag_read_words[24] || diag_read_words[26]>diag_read_words[21] ||
     diag_read_words[27]>diag_read_words[24] || diag_read_words[27]>diag_read_words[25] ||
     diag_read_words[28]>diag_read_words[21] || diag_read_words[28]>diag_read_words[25] ||
     diag_read_words[29]>diag_read_words[26] || diag_read_words[29]>diag_read_words[27] || diag_read_words[29]>diag_read_words[28])
   $fatal(1,"Overlap counters violate intersections");
  repeat(5)@(negedge clk);
  for(k=0;k<32;k=k+1)begin read_reg(12'h13c+4*k,0,x);if(x!==diag_read_words[k])$fatal(1,"Snapshot changed while idle");end
  diag_checks=diag_checks+1;
  $display("COUNTER_PHYSICAL_CASE_PASS case=%0d cycles=%0d feature=%0d parameter=%0d directory=%0d mac_groups=%0d slots=%0d",case_id,diag_read_words[0],diag_read_words[3],diag_read_words[6],diag_read_words[9],diag_read_words[19],diag_read_words[20]);
 end
endtask

initial begin
 clk=0;
platform_rst_n=0;
s_axi_awaddr=0;
s_axi_awvalid=0;
s_axi_wdata=0;
s_axi_wstrb=0;
s_axi_wvalid=0;
s_axi_bready=0;
s_axi_araddr=0;
s_axi_arvalid=0;
s_axi_rready=0;
 descriptor=0;descriptor[31:0]=32'ha00000;descriptor[63:32]=32'ha00100;
 descriptor[95:64]=32'ha00200;descriptor[127:96]=32'ha00300;
 descriptor[138:128]=1;descriptor[144:139]=32;descriptor[191:176]=16'h5a50;descriptor[223:192]=32'h83f6cd55;
 reset_platform;
 for(case_id=0;case_id<5;case_id=case_id+1)begin
  mode_pool=(case_id==1 || case_id==3 || case_id==4);
  if(mode_pool)begin
   pool_index=case_id==1 ? 0 : case_id==3 ? 1 : 2;
   selected_event=70+pool_index;
   $readmemh($sformatf("pool_source_%0d.hex",pool_index),source_words);
   $readmemh($sformatf("pool_expected_%0d.hex",pool_index),expected_words);
  end else begin
   selected_event=1;sample=case_id==0 ? 3 : -4;
   $readmemh(case_id==0 ? "mixed_conv_expected_0.hex" : "mixed_conv_expected_1.hex",expected_words,0,143);
  end
  if(!dut.accepted_core.backend_all_io_quiet || dut.accepted_core.backend_active)$fatal(1,"Mixed stats reset while owned");
  stats_reset=1;repeat(3)@(negedge clk);stats_reset=0;
  for(i=0;i<27;i=i+1)words[i]=0;
  words[0]=32'h60000+case_id;words[1]=200;words[2]=selected_event;words[3]=32'h83f6cd55;
  words[4]=4096+case_id*16;words[5]=8192+case_id*4096;words[6]=12288+case_id*4096;words[7]=7;
  words[8]=32'h100000;words[9]=3+case_id;words[10]=32'h100000;words[11]=32'h300000;
  words[13]=32'h400000;words[14]=4+case_id;words[15]=32'h400000;words[16]=32'h800000;
  words[18]=32'h900000;words[19]=2;words[20]=32'ha00000;words[21]=32'hc00000;
  words[23]=2000000;words[24]=2000000;words[25]=4000000;words[26]=100000;
  for(i=0;i<27;i=i+1)write_reg(12'h040+4*i,words[i],0);
  write_reg(12'h00c,1,0);
  j=0;while(!irq && j<100000)begin @(negedge clk);j=j+1;end
  if(!irq)$fatal(1,"Mixed job timeout");
  read_reg(12'h010,0,value);
  if(!(value&16) || (value&32))$fatal(1,"Mixed job fault stage=%0d status=%h code=%h",case_id,value,dut.accepted_core.backend_fault_code);
  if(ar_count!=(mode_pool ? 640 : 15) || aw_count!=(mode_pool ? 640 : 9) ||
     b_count!=aw_count || w_count!=(mode_pool ? 10240 : 144))$fatal(1,"Mixed traffic incomplete");
  read_reg(12'h108,0,value);if(value!==selected_event)$fatal(1,"Mixed result event");
  read_reg(12'h110,0,value);if(value!==(4096+case_id*16))$fatal(1,"Mixed result job");
  read_reg(12'h11c,0,value);if(value!==(4+case_id))$fatal(1,"Mixed destination generation");
  read_reg(12'h124,0,value);if(value!==(3+case_id))$fatal(1,"Mixed source generation");
  check_diag;
  write_reg(12'h00c,8,0);
  read_reg(12'h010,0,value);if(value!==32'h81)$fatal(1,"Mixed not ready after ACK");
  $display("PLATFORM_V13C_MIXED_CASE_PASS stage=%0d event=%0d ar=%0d w=%0d",case_id,selected_event,ar_count,w_count);
 end
 if(resets!=1)$fatal(1,"Mixed suite reset between jobs");
 if(diag_checks!=5)$fatal(1,"Expected five telemetry comparisons");
 $display("COUNTER_PHYSICAL_MIXED_PASS jobs=5 switches=3 pool=3 conv=2 one_reset=1");
 $finish;
end
endmodule
