`timescale 1ns/1ps
module tb_platform_v13c_control;
reg  clk;
reg  rst_n;
reg  cmd_view_mode;
reg  view_sources_live;
reg  view_table_live;
reg [31:0] view_epoch;
reg [7:0] view_event;
reg [10:0] view_channels;
reg [9:0] view_height;
reg [9:0] view_width;
reg [2:0] view_context_count;
wire  view_descriptor_request;
wire [4:0] view_descriptor_index;
reg  view_descriptor_valid;
reg [31:0] view_descriptor_epoch;
reg [31:0] view_descriptor_address;
reg [31:0] view_descriptor_generation;
reg [31:0] view_descriptor_region_begin;
reg [32:0] view_descriptor_region_end;
reg [5:0] view_descriptor_channels;
reg [15:0] view_descriptor_contexts;
reg  view_lut_cfg_begin_valid;
wire  view_lut_cfg_begin_ready;
reg [31:0] view_lut_cfg_epoch;
reg [2:0] view_lut_cfg_contexts;
reg  view_lut_cfg_word_valid;
wire  view_lut_cfg_word_ready;
reg [7:0] view_lut_cfg_data;
reg  view_lut_cfg_commit_valid;
wire  view_lut_cfg_commit_ready;
wire  view_lut_cfg_valid;
wire  view_lut_error_valid;
wire [2:0] view_lut_error_code;
reg  cmd_valid;
wire  cmd_ready;
reg [31:0] cmd_epoch;
reg [7:0] cmd_event;
reg [31:0] cmd_model_crc;
reg [31:0] cmd_job_base;
reg [31:0] cmd_token_base;
reg [31:0] cmd_tag_base;
reg  cmd_first_bank;
reg [31:0] cmd_source_base;
reg [31:0] cmd_source_generation;
reg  source_lease_valid;
reg [31:0] source_lease_generation;
reg [31:0] source_lease_region_begin;
reg [32:0] source_lease_region_end;
reg [31:0] cmd_destination_base;
reg [31:0] cmd_destination_generation;
reg  destination_reservation_valid;
reg [31:0] destination_reservation_generation;
reg [31:0] destination_reservation_region_begin;
reg [32:0] destination_reservation_region_end;
reg [31:0] cmd_parameter_directory_base;
reg [15:0] cmd_parameter_count;
reg [31:0] cmd_parameter_payload_begin;
reg [32:0] cmd_parameter_payload_end;
reg [31:0] cmd_load_timeout_cycles;
reg [31:0] cmd_parameter_timeout_cycles;
reg [31:0] cmd_write_timeout_cycles;
reg  cancel;
wire  active;
wire  fault;
wire [3:0] fault_code;
wire  needs_drain;
wire  drain_complete;
wire  all_io_quiet;
wire  producer_context_valid;
wire [15:0] producer_cin;
wire [15:0] producer_input_height;
wire [15:0] producer_input_width;
wire [15:0] producer_cout;
wire [15:0] producer_output_height;
wire [15:0] producer_output_width;
wire [15:0] producer_kernel;
wire [15:0] producer_stride;
wire [15:0] producer_padding;
wire [15:0] producer_parameter_first;
wire [7:0] producer_event;
wire  producer_complete;
wire [31:0] producer_complete_epoch;
wire [7:0] producer_complete_event;
wire [31:0] producer_complete_model_crc;
wire [31:0] producer_complete_job_base;
wire [31:0] producer_complete_token_base;
wire [31:0] producer_complete_tag_base;
wire [31:0] producer_complete_destination_generation;
wire [7:0] producer_complete_tiles;
wire [5:0] m_axi_arid;
wire [31:0] m_axi_araddr;
wire [3:0] m_axi_arlen;
wire [2:0] m_axi_arsize;
wire [1:0] m_axi_arburst;
wire  m_axi_arvalid;
reg  m_axi_arready;
reg [5:0] m_axi_rid;
reg [63:0] m_axi_rdata;
reg [1:0] m_axi_rresp;
reg  m_axi_rlast;
reg  m_axi_rvalid;
wire  m_axi_rready;
wire [5:0] m_axi_awid;
wire [31:0] m_axi_awaddr;
wire [3:0] m_axi_awlen;
wire [2:0] m_axi_awsize;
wire [1:0] m_axi_awburst;
wire  m_axi_awvalid;
reg  m_axi_awready;
wire [5:0] m_axi_wid;
wire [63:0] m_axi_wdata;
wire [7:0] m_axi_wstrb;
wire  m_axi_wlast;
wire  m_axi_wvalid;
reg  m_axi_wready;
reg [5:0] m_axi_bid;
reg [1:0] m_axi_bresp;
reg  m_axi_bvalid;
wire  m_axi_bready;
z100_native_conv_pool_backend_v1 dut (.clk(clk),
.rst_n(rst_n),
.cmd_valid(cmd_valid),
.cmd_ready(cmd_ready),
.cmd_epoch(cmd_epoch),
.cmd_event(cmd_event),
.cmd_model_crc(cmd_model_crc),
.cmd_job_base(cmd_job_base),
.cmd_token_base(cmd_token_base),
.cmd_tag_base(cmd_tag_base),
.cmd_first_bank(cmd_first_bank),
.cmd_source_base(cmd_source_base),
.cmd_source_generation(cmd_source_generation),
.source_lease_valid(source_lease_valid),
.source_lease_generation(source_lease_generation),
.source_lease_region_begin(source_lease_region_begin),
.source_lease_region_end(source_lease_region_end),
.cmd_destination_base(cmd_destination_base),
.cmd_destination_generation(cmd_destination_generation),
.destination_reservation_valid(destination_reservation_valid),
.destination_reservation_generation(destination_reservation_generation),
.destination_reservation_region_begin(destination_reservation_region_begin),
.destination_reservation_region_end(destination_reservation_region_end),
.cmd_parameter_directory_base(cmd_parameter_directory_base),
.cmd_parameter_count(cmd_parameter_count),
.cmd_parameter_payload_begin(cmd_parameter_payload_begin),
.cmd_parameter_payload_end(cmd_parameter_payload_end),
.cmd_load_timeout_cycles(cmd_load_timeout_cycles),
.cmd_parameter_timeout_cycles(cmd_parameter_timeout_cycles),
.cmd_write_timeout_cycles(cmd_write_timeout_cycles),
.cancel(cancel),
.active(active),
.fault(fault),
.fault_code(fault_code),
.needs_drain(needs_drain),
.drain_complete(drain_complete),
.all_io_quiet(all_io_quiet),
.producer_context_valid(producer_context_valid),
.producer_cin(producer_cin),
.producer_input_height(producer_input_height),
.producer_input_width(producer_input_width),
.producer_cout(producer_cout),
.producer_output_height(producer_output_height),
.producer_output_width(producer_output_width),
.producer_kernel(producer_kernel),
.producer_stride(producer_stride),
.producer_padding(producer_padding),
.producer_parameter_first(producer_parameter_first),
.producer_event(producer_event),
.producer_complete(producer_complete),
.producer_complete_epoch(producer_complete_epoch),
.producer_complete_event(producer_complete_event),
.producer_complete_model_crc(producer_complete_model_crc),
.producer_complete_job_base(producer_complete_job_base),
.producer_complete_token_base(producer_complete_token_base),
.producer_complete_tag_base(producer_complete_tag_base),
.producer_complete_destination_generation(producer_complete_destination_generation),
.producer_complete_tiles(producer_complete_tiles),
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

integer success_count=0, n, held_ar_count;
reg pause_ar=0,pause_r=0,pause_aw=0,pause_b=0,inject_r=0,inject_b=0;
reg [31:0] held_address;
reg [3:0] held_length;

reg [63:0] source_words[0:10239], expected_words[0:10239];
integer cycle=0,ar_count=0,aw_count=0,w_count=0,b_count=0,r_count=0,bubbles=0,case_id;
reg rb=0,wb=0,bp=0,r_hold=0;
reg [31:0] ra,wa;
reg [5:0] rid_q,wid_q;
integer ri=0,rn=0,wi=0,wn=0,b_delay=0;
always @* begin
 m_axi_arready=rst_n && !rb && cycle%5!=0 && !pause_ar;
 m_axi_rvalid=rst_n && rb && (r_hold || cycle%7!=0) && !pause_r;
 m_axi_rid=rid_q;
 m_axi_rdata=rb ? source_words[((ra-32'h100000)>>3)+ri] : 64'd0;
 m_axi_rlast=rb && ri==rn-1;
 m_axi_rresp=(inject_r && r_count==0) ? 2'b10 : 2'b00;
 m_axi_awready=rst_n && !wb && !bp && cycle%3!=0 && !pause_aw;
 m_axi_wready=rst_n && wb && cycle%4!=0;
 m_axi_bvalid=rst_n && bp && b_delay==0 && !pause_b;
 m_axi_bid=wid_q; m_axi_bresp=(inject_b && b_count==0) ? 2'b10 : 2'b00;
end
always @(posedge clk) begin
 if(!rst_n) begin
  cycle<=0;rb<=0;wb<=0;bp<=0;r_hold<=0;ri<=0;wi<=0;b_delay<=0;
  ar_count<=0;aw_count<=0;w_count<=0;b_count<=0;r_count<=0;bubbles<=0;
 end else begin
  cycle<=cycle+1;
  if(rb && !m_axi_rvalid || wb && !m_axi_wready || bp && !m_axi_bvalid) bubbles<=bubbles+1;
  if(m_axi_arvalid && m_axi_arready) begin
   if(m_axi_araddr!==(32'h100000+(ar_count%640)*128) || m_axi_arlen!==15 ||
      m_axi_arsize!==3 || m_axi_arburst!==1) $fatal(1,"Pool HP AR shape/order addr=%h n=%0d",m_axi_araddr,ar_count);
   rb<=1;ra<=m_axi_araddr;rid_q<=m_axi_arid;rn<=m_axi_arlen+1;ri<=0;ar_count<=ar_count+1;
  end
  r_hold<=m_axi_rvalid && !m_axi_rready;
  if(m_axi_rvalid && m_axi_rready) begin
   r_count<=r_count+1;
   if(ri==rn-1) rb<=0; else ri<=ri+1;
  end
  if(m_axi_awvalid && m_axi_awready) begin
   if(m_axi_awaddr!==(32'h400000+(aw_count%640)*128) || m_axi_awlen!==15 ||
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
  if(producer_complete && (rb || wb || bp)) $fatal(1,"Pool completion before physical drain");
  if(dut.owner_valid && dut.owner_pool && dut.conv_backend.cmd_valid)
   $fatal(1,"Pool owner admitted a Conv command");
 end
end
always #5 clk=~clk;
initial begin #100000000;$fatal(1,"Pool fault suite watchdog");end
always @(posedge clk) begin
 if(!rst_n)success_count<=0;
 else if(producer_complete)success_count<=success_count+1;
end
task ticks(input integer count);begin repeat(count)@(negedge clk);end endtask
task submit;
begin
 @(negedge clk);cmd_valid=1;
 do @(posedge clk);while(!cmd_ready);
 @(negedge clk);cmd_valid=0;
end endtask
task wait_fault_and_drain;
begin
 n=0;while(!fault && n<2000000)begin ticks(1);n=n+1;end
 if(!fault)$fatal(1,"No expected fault case=%0d",case_id);
 n=0;
 while(!all_io_quiet && n<2000000)begin
  if(!dut.owner_valid || !dut.owner_pool || cmd_ready || producer_complete)$fatal(1,"Lost owned Pool IO");
  ticks(1);n=n+1;
 end
 if(!all_io_quiet || !drain_complete)$fatal(1,"Pool drain timeout case=%0d",case_id);
 cancel=0;ticks(10);
 if(!fault || cmd_ready || !dut.owner_valid || !dut.owner_pool)$fatal(1,"Pool fault/owner not sticky");
 if(success_count!==(case_id==9 || case_id==10 ? 1 : 0))$fatal(1,"False Pool success case=%0d",case_id);
 held_ar_count=ar_count;cmd_valid=1;
 repeat(10)begin ticks(1);if(cmd_ready || ar_count!=held_ar_count)$fatal(1,"Fault permitted reload");end
 cmd_valid=0;
 $display("PLATFORM_V13C_POOL_FAULT_CASE_PASS case=%0d code=%0d ar=%0d aw=%0d r=%0d w=%0d b=%0d",case_id,fault_code,ar_count,aw_count,r_count,w_count,b_count);
end endtask
initial begin
 clk=0;
rst_n=0;
cmd_view_mode=0;
view_sources_live=0;
view_table_live=0;
view_epoch=0;
view_event=0;
view_channels=0;
view_height=0;
view_width=0;
view_context_count=0;
view_descriptor_valid=0;
view_descriptor_epoch=0;
view_descriptor_address=0;
view_descriptor_generation=0;
view_descriptor_region_begin=0;
view_descriptor_region_end=0;
view_descriptor_channels=0;
view_descriptor_contexts=0;
view_lut_cfg_begin_valid=0;
view_lut_cfg_epoch=0;
view_lut_cfg_contexts=0;
view_lut_cfg_word_valid=0;
view_lut_cfg_data=0;
view_lut_cfg_commit_valid=0;
cmd_valid=0;
cmd_epoch=0;
cmd_event=0;
cmd_model_crc=0;
cmd_job_base=0;
cmd_token_base=0;
cmd_tag_base=0;
cmd_first_bank=0;
cmd_source_base=0;
cmd_source_generation=0;
source_lease_valid=0;
source_lease_generation=0;
source_lease_region_begin=0;
source_lease_region_end=0;
cmd_destination_base=0;
cmd_destination_generation=0;
destination_reservation_valid=0;
destination_reservation_generation=0;
destination_reservation_region_begin=0;
destination_reservation_region_end=0;
cmd_parameter_directory_base=0;
cmd_parameter_count=0;
cmd_parameter_payload_begin=0;
cmd_parameter_payload_end=0;
cmd_load_timeout_cycles=0;
cmd_parameter_timeout_cycles=0;
cmd_write_timeout_cycles=0;
cancel=0;
 $readmemh("pool_source_0.hex",source_words);
 $readmemh("pool_expected_0.hex",expected_words);
 for(case_id=0;case_id<15;case_id=case_id+1)begin
  if(case_id>0 && !all_io_quiet)$fatal(1,"Attempt reset before quiescence");
  @(negedge clk);rst_n=0;cancel=0;cmd_valid=0;
  pause_ar=0;pause_r=0;pause_aw=0;pause_b=0;inject_r=0;inject_b=0;
  ticks(8);rst_n=1;ticks(8);
  cmd_epoch=200;cmd_event=70;cmd_model_crc=32'h83f6cd55;
  cmd_job_base=4096;cmd_token_base=8192;cmd_tag_base=12288;cmd_first_bank=1;
  cmd_source_base=32'h100000;cmd_source_generation=3;source_lease_valid=1;source_lease_generation=3;
  source_lease_region_begin=32'h100000;source_lease_region_end=33'h300000;
  cmd_destination_base=32'h400000;cmd_destination_generation=4;destination_reservation_valid=1;
  destination_reservation_generation=4;destination_reservation_region_begin=32'h400000;destination_reservation_region_end=33'h800000;
  cmd_parameter_directory_base=32'h900000;cmd_parameter_count=173;
  cmd_parameter_payload_begin=32'ha00000;cmd_parameter_payload_end=33'hc00000;
  cmd_load_timeout_cycles=2000000;cmd_parameter_timeout_cycles=2000000;cmd_write_timeout_cycles=4000000;
  case(case_id)
   0:pause_r=1;
   2:pause_b=1;
   3:pause_ar=1;
   4:pause_aw=1;
   5:inject_r=1;
   6:inject_b=1;
   8:cmd_parameter_timeout_cycles=8;
   11:cmd_load_timeout_cycles=8;
   12:cmd_write_timeout_cycles=20;
   13:cmd_model_crc=32'hdeadbeef;
   14:begin
    cmd_destination_base=32'h100040;
    destination_reservation_region_begin=32'h100000;destination_reservation_region_end=33'h300000;
   end
  endcase
  submit;
  case(case_id)
   0:begin
    while(!rb)ticks(1);
    cancel=1;
    repeat(20)begin ticks(1);if(all_io_quiet || cmd_ready || !dut.owner_valid)$fatal(1,"Read stall lost ownership");end
    pause_r=0;
   end
   1:begin while(!dut.aux_pool_active)ticks(1);cancel=1;end
   2:begin
    while(!bp)ticks(1);cancel=1;
    repeat(20)begin ticks(1);if(all_io_quiet || cmd_ready || !dut.owner_valid)$fatal(1,"B stall lost ownership");end
    pause_b=0;
   end
   3:begin
    while(!m_axi_arvalid)ticks(1);held_address=m_axi_araddr;held_length=m_axi_arlen;cancel=1;
    repeat(20)begin ticks(1);if(!m_axi_arvalid || m_axi_araddr!==held_address || m_axi_arlen!==held_length || all_io_quiet)$fatal(1,"Cancelled AR withdrawn");end
    pause_ar=0;
   end
   4:begin
    while(!m_axi_awvalid)ticks(1);held_address=m_axi_awaddr;held_length=m_axi_awlen;cancel=1;
    repeat(20)begin ticks(1);if(!m_axi_awvalid || m_axi_awaddr!==held_address || m_axi_awlen!==held_length || all_io_quiet)$fatal(1,"Cancelled AW withdrawn");end
    pause_aw=0;
   end
   7:begin while(!rb)ticks(1);source_lease_generation=4;end
   9,10:begin
    while(!producer_complete && !fault)ticks(1);
    if(fault || !all_io_quiet)$fatal(1,"Replay prerequisite Pool failed");
    ticks(5);
    if(!cmd_ready || dut.owner_valid || success_count!=1)$fatal(1,"Healthy owner did not release");
    if(case_id==10)begin cmd_epoch=199;cmd_job_base=8192;end
    submit;
   end
  endcase
  wait_fault_and_drain;
 end
 $display("PLATFORM_V13C_POOL_FAULT_PASS cases=15 cancelled_r_hold=20 cancelled_b_hold=20 ar_hold=20 aw_hold=20 lease_loss=1 replay=2 errors=2 timeouts=3 reset_retries=14");
 $finish;
end
endmodule
