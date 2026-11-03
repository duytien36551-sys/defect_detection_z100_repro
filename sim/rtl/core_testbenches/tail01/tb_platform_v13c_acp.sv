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
initial begin #2000000; $fatal(1,"MMIO/core watchdog"); end
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

integer cycle=0, ar_count=0, aw_count=0, w_count=0, b_count=0, case_id;
reg rb=0, wb=0, bp=0;
reg [31:0] ra, wa;
reg [5:0] rid_q, wid_q;
integer rn, wn, ri, wi;
reg signed [7:0] sample;
integer expected_value;
reg [9215:0] captured;
integer byte_index, x_check, channel_check, byte_expected;
reg [255:0] descriptor;
reg [63:0] held_r, held_w;
reg r_stalled=0, w_stalled=0;
reg r_hold_q=0;
function automatic [63:0] memory_read(input [31:0] address);
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
 memory_read=v;
end endfunction
always @* begin
 m_axi_arready=platform_rst_n&&!rb&&(cycle%5!=0);
 m_axi_rvalid=platform_rst_n&&rb&&(r_hold_q || cycle%7!=0);
 // Hold valid once raised until consumed; the bubble schedule is handled below.
 m_axi_rid=rid_q; m_axi_rdata=memory_read(ra+ri*8); m_axi_rresp=0;
 m_axi_rlast=rb&&(ri==rn-1);
 m_axi_awready=platform_rst_n&&!wb&&!bp&&(cycle%3!=0);
 m_axi_wready=platform_rst_n&&wb&&(cycle%4!=0);
 m_axi_bid=wid_q; m_axi_bresp=0; m_axi_bvalid=platform_rst_n&&bp;
end
// Gate R bubbles only between beats, never while an asserted RVALID is held.
always @(posedge clk) begin
 if(!platform_rst_n) begin
  rb<=0; wb<=0; bp<=0; ri<=0; wi<=0; cycle<=0; r_hold_q<=0;
  ar_count<=0; aw_count<=0; w_count<=0; b_count<=0; captured<=0;
 end else begin
  cycle<=cycle+1;
  if(m_axi_arvalid&&m_axi_arready) begin
   if(m_axi_arsize!=3 || m_axi_arburst!=1) $fatal(1,"Bad HP read shape");
   rb<=1; ra<=m_axi_araddr; rid_q<=m_axi_arid; rn<=m_axi_arlen+1; ri<=0; ar_count<=ar_count+1;
  end
  r_hold_q<=m_axi_rvalid&&!m_axi_rready;
  if(m_axi_rvalid&&m_axi_rready) begin
   if(ri==rn-1) rb<=0; else ri<=ri+1;
  end
  if(m_axi_awvalid&&m_axi_awready) begin
   if(m_axi_awaddr!==(32'h400000+aw_count*128) || m_axi_awlen!==15 || m_axi_awsize!==3 || m_axi_awburst!==1)
    $fatal(1,"Unexpected output HP address/burst");
   wb<=1; wa<=m_axi_awaddr; wid_q<=m_axi_awid; wn<=m_axi_awlen+1; wi<=0; aw_count<=aw_count+1;
  end
  if(m_axi_wvalid&&m_axi_wready) begin
   if(m_axi_wid!==wid_q || m_axi_wstrb!==8'hff || m_axi_wlast!==(wi==wn-1)) $fatal(1,"Bad W metadata");
   captured[(wa-32'h400000+wi*8)*8+:64]<=m_axi_wdata; w_count<=w_count+1;
   if(wi==wn-1) begin wb<=0;bp<=1;end else wi<=wi+1;
  end
  if(m_axi_bvalid&&m_axi_bready) begin bp<=0;b_count<=b_count+1;end
  if(dut.accepted_core.backend_producer_complete && (wb||bp)) $fatal(1,"Completion before B drain");
  if(dut.accepted_core.u_conv_backend.conv_backend.pack_cfg_valid && !dut.accepted_core.u_conv_backend.conv_backend.pack_cfg_ready) begin
   if(dut.accepted_core.u_conv_backend.conv_backend.pack_cfg_channels!==33 || dut.accepted_core.u_conv_backend.conv_backend.pack_cfg_width!==21 ||
      dut.accepted_core.u_conv_backend.conv_backend.pack_cfg_height!==1) $fatal(1,"Config geometry unstable");
  end
 end
end
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
 descriptor=0;
 descriptor[31:0]=32'ha00000; descriptor[63:32]=32'ha00100;
 descriptor[95:64]=32'ha00200; descriptor[127:96]=32'ha00300;
 descriptor[138:128]=1; descriptor[144:139]=32; descriptor[191:176]=16'h5a50;
 descriptor[223:192]=32'h83f6cd55;
 for(case_id=0;case_id<3;case_id=case_id+1) begin
  case(case_id)
   0:begin sample=3;expected_value=7;end
   1:begin sample=-4;expected_value=-7;end
   2:begin sample=100;expected_value=127;end
  endcase
  reset_platform;
  for(i=0;i<27;i=i+1) words[i]=0;
  words[0]=32'h1234; words[1]=200; words[2]=1; words[3]=32'h83f6cd55;
  words[4]=4096; words[5]=8192; words[6]=12288; words[7]=7;
  words[8]=32'h100000; words[9]=3; words[10]=32'h100000; words[11]=32'h300000;
  words[13]=32'h400000; words[14]=4; words[15]=32'h400000; words[16]=32'h800000;
  words[18]=32'h900000; words[19]=2; words[20]=32'ha00000; words[21]=32'hc00000;
  words[23]=100000;words[24]=100000;words[25]=100000;words[26]=100000;
  for(i=0;i<27;i=i+1) write_reg(12'h040+4*i,words[i],0);
  write_reg(12'h00c,1,0);
  j=0;
  while(!irq && j<90000) begin @(negedge clk); j=j+1; end
  if(!irq) $fatal(1,"No success IRQ");
  read_reg(12'h010,0,value);
  if(!(value&16) || (value&32)) $fatal(1,"Compute did not succeed status=%h fault=%h",value,dut.accepted_core.backend_fault_code);
  if(aw_count!=9 || w_count!=144 || b_count!=9 || ar_count<6) $fatal(1,"Missing actual DDR traffic");
  for(byte_index=0;byte_index<1152;byte_index=byte_index+1) begin
   // Materialized DDR stream: block32 -> row -> xword -> subgroup4.
   // Packer addresses are canonical group4-major, but stream_order serializes this native order.
   if(byte_index/64<16) begin
    x_check=((byte_index/64)/8)*16+(byte_index%16);
    channel_check=((byte_index/64)%8)*4+((byte_index%64)/16);
   end else begin
    x_check=((byte_index/64)-16)*16+(byte_index%16);
    channel_check=32+((byte_index%64)/16);
   end
   byte_expected=(x_check<21 && channel_check<33)?expected_value:0;
   if(captured[byte_index*8+:8]!==byte_expected[7:0])
    $fatal(1,"Numeric/padding mismatch case=%0d byte=%0d x=%0d c=%0d expected=%0d actual=%h",case_id,byte_index,x_check,channel_check,byte_expected,captured[byte_index*8+:8]);
  end
  read_reg(12'h120,0,value); if(value!==1) $fatal(1,"Wrong committed tile result");
  $display("PLATFORM_V13C_NUMERIC_CASE_PASS case=%0d sample=%0d result=%0d ar=%0d w=%0d",case_id,sample,expected_value,ar_count,w_count);
 end
 $display("PLATFORM_V13C_NUMERIC_PASS cases=3 logical_bytes=2079 padded_bytes=3456");
 $finish;
end
endmodule
