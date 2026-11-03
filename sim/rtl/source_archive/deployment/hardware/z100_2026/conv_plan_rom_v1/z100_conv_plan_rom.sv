`default_nettype none
// Read-only, model-bound C halo plan. Geometry is thirteen little-field-order
// uint16 values in ZnHaloGeometry order. No tensor ownership changes here.
module z100_conv_plan_rom #(
 parameter MAP_FILE="conv_event_map.hex",
 parameter TILE_FILE="conv_tiles.hex",
 parameter [31:0] MODEL_CRC=32'd2213989717
)(
 input wire clk,rst_n,cancel,
 input wire request_valid,output wire request_ready,
 input wire[31:0] request_epoch,request_tag,request_model_crc,
 input wire[7:0] request_event,request_tile,
 output reg result_valid,input wire result_ready,
 output reg[31:0] result_epoch,result_tag,
 output reg[7:0] result_event,result_tile,
 output wire result_error,
 output wire[207:0] result_geometry,
 output wire[15:0] result_parameter_first,
 output wire[7:0] result_tile_count,
 output wire[31:0] result_runs,result_windows
);
 (* rom_style="distributed" *) reg[15:0] event_map[0:255];
 (* rom_style="block" *) reg[319:0] tile_rom[0:255];
 initial begin $readmemh(MAP_FILE,event_map);$readmemh(TILE_FILE,tile_rom);end
 reg[319:0] record_q;
 reg request_bad_q;reg[7:0] count_q;
 wire[15:0] entry=event_map[request_event];
 wire[8:0] address={1'b0,entry[7:0]}+{1'b0,request_tile};
 wire good=request_epoch!=0&&request_tag!=0&&request_model_crc==MODEL_CRC&&
   entry[15:8]!=0&&request_tile<entry[15:8]&&address<189;
 assign request_ready=rst_n&&!cancel&&(!result_valid||result_ready);
 assign result_error=request_bad_q||record_q[319:312]!=0||record_q[311:304]!=result_event||
   record_q[303:296]!=result_tile||record_q[295:288]!=count_q;
 assign result_geometry=result_error?208'd0:record_q[287:80];
 assign result_parameter_first=result_error?16'd0:record_q[79:64];
 assign result_tile_count=result_error?8'd0:record_q[295:288];
 assign result_runs=result_error?32'd0:record_q[63:32];
 assign result_windows=result_error?32'd0:record_q[31:0];
 always @(posedge clk)begin
  if(!rst_n||cancel)begin
   result_valid<=0;result_epoch<=0;result_tag<=0;result_event<=0;result_tile<=0;
   request_bad_q<=0;count_q<=0;record_q<=0;
  end else if(request_ready)begin
   result_valid<=request_valid;
   if(request_valid)begin
    result_epoch<=request_epoch;result_tag<=request_tag;result_event<=request_event;result_tile<=request_tile;
    request_bad_q<=!good;count_q<=entry[15:8];record_q<=tile_rom[good?address[7:0]:8'd0];
   end
  end
 end
endmodule
`default_nettype wire
