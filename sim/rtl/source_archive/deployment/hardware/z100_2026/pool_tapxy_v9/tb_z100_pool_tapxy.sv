`timescale 1ns/1ps
`default_nettype none
module tb_z100_pool_tapxy;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,cancel=0,fw_error=0,job_valid=0;
 reg[10:0] job_channels=5;reg[9:0] job_height=3;wire[9:0] job_width=20;
 reg[31:0] job_epoch=200;wire[31:0] active_epoch=200;
 wire store_valid=1,loading=0;wire[10:0] loaded_channels=job_channels;
 wire[9:0] loaded_height=job_height,loaded_width=20;
 wire window_valid,window_ready,window_y_valid,window_cancel,window_out_ready,job_ready,out_valid,out_ready,out_last,done,error_valid,active;
 wire[31:0] window_epoch,window_request_tag,out_epoch;wire[13:0] window_row_address;wire signed[11:0] window_first_x;
 wire[3:0] window_channel_mask,error_code;wire[12:0] out_address;wire[511:0] out_data;
 reg window_out_valid=0;reg[31:0] window_tag=0;reg[79:0] window_mask=0;reg[639:0] window_data=0;
 integer cycle=0;reg block_window=0,block_output=0,checking=0;
 assign window_ready=!block_window&&cycle%5!=0&&(!window_out_valid||window_out_ready);
 assign out_ready=!block_output&&cycle%23>8;
 z100_maxpool_window20_tapxy_v3 dut(.*);
 function automatic signed[7:0] value(input integer c,input integer y,input integer x);
  value=((c*37+y*19+x*11)%256)-128;
 endfunction
 function automatic[7:0] golden(input integer c,input integer y,input integer x);
  integer ky,kx,yy,xx;reg signed[7:0] largest,v;
  begin largest=-128;
   for(ky=0;ky<5;ky=ky+1)for(kx=0;kx<5;kx=kx+1)begin
    yy=y+ky-2;xx=x+kx-2;
    if(yy>=0&&yy<job_height&&xx>=0&&xx<20)begin v=value(c,yy,xx);if(v>largest)largest=v;end
   end
   golden=largest;
  end
 endfunction
 integer c,p,source_group,source_row,source_x;
 always @(posedge clk)begin
  cycle<=cycle+1;
  if(!rst_n||cancel||window_cancel)window_out_valid<=0;
  else begin
   if(window_out_valid&&window_out_ready)window_out_valid<=0;
   if(window_valid&&window_ready)begin
    window_out_valid<=1;window_tag<=window_request_tag;
    source_group=window_row_address/(job_height*2);
    source_row=(window_row_address%(job_height*2))/2;
    for(c=0;c<4;c=c+1)for(p=0;p<20;p=p+1)begin
     source_x=$signed(window_first_x)+p;
     window_mask[c*20+p]<=window_channel_mask[c]&&window_y_valid&&source_x>=0&&source_x<20;
     window_data[(c*20+p)*8+:8]<=source_x>=0&&source_x<20?value(source_group*4+c,source_row,source_x):8'd0;
    end
   end
  end
 end
 integer words=0,total_words=0,total_bytes=0,completed_jobs=0,window_holds=0,output_holds=0;
 integer bank,co,oy,ox;reg[8191:0] seen=0;reg[7:0] expected;
 always @(posedge clk)if(rst_n)begin
  if(window_valid&&!window_ready)window_holds=window_holds+1;
  if(out_valid&&!out_ready)output_holds=output_holds+1;
  if(checking&&error_valid)$fatal(1,"Valid TapXY job error=%d",error_code);
  if(checking&&out_valid&&out_ready)begin
   if(out_epoch!=200||out_address>=((job_channels+3)/4)*job_height*2||seen[out_address]||out_last!==(words+1==((job_channels+3)/4)*job_height*2))$fatal(1,"TapXY signed pool output identity/order");
   co=(out_address/(job_height*2))*4;oy=(out_address%(job_height*2))/2;
   for(bank=0;bank<64;bank=bank+1)begin
    ox=(out_address%2)*16+bank%16;
    expected=(co+bank/16<job_channels&&ox<20)?golden(co+bank/16,oy,ox):8'd0;
    if(out_data[bank*8+:8]!==expected)$fatal(1,"TapXY independent signed max mismatch address=%d bank=%d got=%h want=%h",out_address,bank,out_data[bank*8+:8],expected);
    total_bytes=total_bytes+1;
   end
   seen[out_address]=1;words=words+1;total_words=total_words+1;
  end
 end
 task tick;begin @(posedge clk);#1;end endtask
 task submit(input integer channels,input integer height,input integer verify_data);begin
  @(negedge clk);job_channels=channels;job_height=height;job_epoch=200;checking=verify_data;words=0;seen=0;job_valid=1;
  #1;if(!job_ready)$fatal(1,"TapXY job not ready");tick();@(negedge clk);job_valid=0;
 end endtask
 task complete;begin
  while(!done)tick();@(negedge clk);
  if(words!=((job_channels+3)/4)*job_height*2||active||out_valid)$fatal(1,"TapXY job not fully drained words=%d",words);
  completed_jobs=completed_jobs+1;checking=0;
 end endtask
 task cancel_job;begin
  @(negedge clk);cancel=1;tick();
  if(active||out_valid||done||dut.tap_q!=0||dut.tap_x_q!=0||dut.tap_y_q!=0)$fatal(1,"TapXY cancel did not clear private job/counters");
  @(negedge clk);cancel=0;tick();
 end endtask
 initial begin
  repeat(5)tick();@(negedge clk);rst_n=1;
  submit(5,3,1);complete();submit(128,20,1);complete();
  // Invalid epoch leaves the consumer idle and emits the original error.
  @(negedge clk);job_epoch=199;job_valid=1;tick();
  if(!error_valid||error_code!=1||active)$fatal(1,"TapXY invalid epoch admission");
  @(negedge clk);job_valid=0;job_epoch=200;tick();
  block_window=1;submit(5,3,0);while(!window_valid)tick();repeat(5)tick();cancel_job();block_window=0;
  submit(5,3,0);while(dut.tap_q<10)tick();cancel_job();
  block_output=1;submit(5,3,0);while(!out_valid)tick();repeat(5)tick();cancel_job();block_output=0;
  submit(5,3,0);while(!window_valid)tick();@(negedge clk);fw_error=1;tick();
  if(!error_valid||error_code!=2||!active||!window_cancel||out_valid)$fatal(1,"TapXY source fault not latched");
  @(negedge clk);fw_error=0;repeat(4)tick();if(!active||!window_cancel||job_ready)$fatal(1,"TapXY fault disappeared before cancel");cancel_job();
  submit(5,3,1);complete();repeat(3)tick();
  if(completed_jobs!=3||total_words!=1304||total_bytes!=83456||window_holds<10||output_holds<10||dut.tapxy_monitor.window_checks<16000||dut.tapxy_monitor.output_checks<1304)$fatal(1,"TapXY numeric/miter/stall coverage incomplete");
  $display("POOL_TAPXY_PASS complete_jobs=3 signed_packed_words=1304 independent_bytes=83456 cancel_cases=3 fault_recovery=1 bad_epoch=1 window_holds=%0d output_holds=%0d miter_controls=%0d miter_windows=%0d miter_outputs=%0d coordinate_checks=%0d",window_holds,output_holds,dut.tapxy_monitor.control_checks,dut.tapxy_monitor.window_checks,dut.tapxy_monitor.output_checks,dut.tapxy_monitor.coordinate_checks);
  $finish;
 end
 initial begin #20000000;$fatal(1,"TapXY unit watchdog state=%d words=%d",dut.state,words);end
endmodule
`default_nettype wire
