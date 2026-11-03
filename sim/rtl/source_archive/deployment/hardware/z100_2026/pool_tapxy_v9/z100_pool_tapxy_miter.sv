`timescale 1ns/1ps
`default_nettype none
// Simulation-only observer: original consumer receives exactly the same
// external inputs. It never drives any input or output of the candidate.
module z100_pool_tapxy_miter(
 input wire clk,rst_n,cancel,store_valid,loading,fw_error,window_ready,window_out_valid,job_valid,out_ready,
 input wire[31:0] active_epoch,window_tag,job_epoch,
 input wire[10:0] loaded_channels,job_channels,
 input wire[9:0] loaded_height,loaded_width,job_height,job_width,
 input wire[79:0] window_mask,input wire[639:0] window_data,
 input wire window_valid,window_y_valid,window_cancel,window_out_ready,job_ready,out_valid,out_last,done,error_valid,active,
 input wire[31:0] window_epoch,window_request_tag,out_epoch,
 input wire[13:0] window_row_address,input wire signed[11:0] window_first_x,
 input wire[3:0] window_channel_mask,error_code,input wire[12:0] out_address,input wire[511:0] out_data,
 input wire[4:0] tap_q,input wire[2:0] tap_x_q,tap_y_q
);
 wire o_wvalid,o_yvalid,o_cancel,o_reply_ready,o_job_ready,o_valid,o_last,o_done,o_error,o_active;
 wire[31:0] o_wepoch,o_tag,o_epoch;wire[13:0] o_row;wire signed[11:0] o_x;
 wire[3:0] o_cmask,o_error_code;wire[12:0] o_address;wire[511:0] o_data;
 z100_maxpool_window20_rowbase_v2 reference_pool(.clk(clk),.rst_n(rst_n),.cancel(cancel),
  .store_valid(store_valid),.loading(loading),.active_epoch(active_epoch),.loaded_channels(loaded_channels),.loaded_height(loaded_height),.loaded_width(loaded_width),.fw_error(fw_error),
  .window_valid(o_wvalid),.window_ready(window_ready),.window_epoch(o_wepoch),.window_request_tag(o_tag),.window_row_address(o_row),.window_first_x(o_x),.window_channel_mask(o_cmask),.window_y_valid(o_yvalid),.window_cancel(o_cancel),
  .window_out_valid(window_out_valid),.window_out_ready(o_reply_ready),.window_tag(window_tag),.window_mask(window_mask),.window_data(window_data),
  .job_valid(job_valid),.job_ready(o_job_ready),.job_epoch(job_epoch),.job_channels(job_channels),.job_height(job_height),.job_width(job_width),
  .out_valid(o_valid),.out_ready(out_ready),.out_epoch(o_epoch),.out_address(o_address),.out_data(o_data),.out_last(o_last),.done(o_done),.error_valid(o_error),.error_code(o_error_code),.active(o_active));
 integer control_checks=0,window_checks=0,output_checks=0,coordinate_checks=0;
 always @(posedge clk)if(rst_n)begin
  #1;
  if({window_valid,window_cancel,window_out_ready,job_ready,out_valid,done,error_valid,error_code,active}!==
     {o_wvalid,o_cancel,o_reply_ready,o_job_ready,o_valid,o_done,o_error,o_error_code,o_active})$fatal(1,"TapXY changed original cycle/control behavior");
  control_checks=control_checks+1;
  if(window_valid)begin
   if({window_epoch,window_request_tag,window_row_address,window_first_x,window_channel_mask,window_y_valid}!=={o_wepoch,o_tag,o_row,o_x,o_cmask,o_yvalid})$fatal(1,"TapXY descriptor/cycle differs from original division");
   window_checks=window_checks+1;
  end
  if(out_valid)begin
   if({out_epoch,out_address,out_data,out_last}!=={o_epoch,o_address,o_data,o_last})$fatal(1,"TapXY packed output differs from original consumer");output_checks=output_checks+1;
  end
  if(tap_x_q>4||tap_y_q>4||tap_x_q+tap_y_q*5!=tap_q)$fatal(1,"TapXY coordinate recurrence lost tag synchronization");
  coordinate_checks=coordinate_checks+1;
 end
endmodule
bind z100_maxpool_window20_tapxy_v3 z100_pool_tapxy_miter tapxy_monitor(.*);
`default_nettype wire
