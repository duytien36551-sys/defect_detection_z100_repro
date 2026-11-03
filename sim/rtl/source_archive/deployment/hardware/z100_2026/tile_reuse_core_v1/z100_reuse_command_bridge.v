// Private same-clock command adapter. No AXI/DMA or production ABI claim.
// One queued command and one elastic result beat. CANCEL invalidates both.
module z100_reuse_command_bridge(
 input wire clk,input wire rst_n,input wire cancel,
 input wire cmd_valid,output wire cmd_ready,input wire [2:0] cmd_opcode,
 input wire [11:0] cmd_address,input wire [1023:0] cmd_data,
 input wire [3:0] cmd_site_mask,input wire [12:0] cmd_taps,
 input wire [5:0] cmd_lanes,input wire [2:0] cmd_sites,
 output wire result_valid,input wire result_ready,
 output reg [1023:0] result_data,output reg [31:0] result_overflow,
 output reg [1:0] result_site,output reg result_last,
 output reg [5:0] result_lanes,output reg error
);
 reg command_full,result_full;
 reg [2:0] opcode_q,sites_q;
 reg [11:0] address_q;reg [1023:0] data_q;
 reg [3:0] mask_q;reg [12:0] taps_q;reg [5:0] lanes_q;
 wire core_busy,core_error,core_valid,core_last,core_ready;
 wire [1:0] core_site;wire [5:0] core_lanes;
 wire [1023:0] core_data;wire [31:0] core_overflow;
 wire execute=command_full&&!core_busy&&!result_full&&!cancel&&rst_n;
 assign cmd_ready=!command_full&&!cancel&&rst_n;
 assign result_valid=result_full&&rst_n&&!cancel;
 assign core_ready=(!result_full||result_ready)&&!cancel;
 always @(posedge clk) begin
  if(!rst_n||cancel)begin
   command_full<=0;result_full<=0;error<=0;
   result_data<=0;result_overflow<=0;result_site<=0;result_last<=0;result_lanes<=0;
  end else begin
   error<=core_error;
   if(cmd_valid&&cmd_ready)begin
    command_full<=1;opcode_q<=cmd_opcode;address_q<=cmd_address;
    data_q<=cmd_data;mask_q<=cmd_site_mask;taps_q<=cmd_taps;lanes_q<=cmd_lanes;sites_q<=cmd_sites;
   end
   if(execute)begin command_full<=0;if(opcode_q>4)error<=1;end
   if(result_full&&result_ready)result_full<=0;
   if(core_valid&&core_ready)begin
    result_full<=1;result_data<=core_data;result_overflow<=core_overflow;
    result_site<=core_site;result_last<=core_last;result_lanes<=core_lanes;
   end
  end
 end
 z100_tile_reuse_core core(
  .clk(clk),.rst_n(rst_n),.cancel(cancel),
  .load_begin(execute&&opcode_q==0),.cfg_weight_ready(),
  .cfg_weight_we(execute&&opcode_q==2),.cfg_weight_addr(address_q),.cfg_weights(data_q[255:0]),
  .cfg_bias_ready(),.cfg_bias_we(execute&&opcode_q==1),.cfg_biases(data_q),
  .act_cfg_ready(),.act_cfg_we(execute&&opcode_q==3),.act_cfg_addr(address_q),.act_cfg_site_mask(mask_q),.act_cfg_data(data_q[31:0]),
  .run_valid(execute&&opcode_q==4),.run_ready(),.run_tap_count(taps_q),.run_lane_count(lanes_q),.run_site_count(sites_q),
  .out_valid(core_valid),.out_ready(core_ready),.out_site(core_site),.out_last(core_last),.out_lane_count(core_lanes),
  .out_data(core_data),.out_overflow(core_overflow),.busy(core_busy),.error(core_error)
 );
endmodule
