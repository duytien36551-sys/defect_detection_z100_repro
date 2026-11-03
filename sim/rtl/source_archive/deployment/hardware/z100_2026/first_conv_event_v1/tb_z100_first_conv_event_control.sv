`timescale 1ns/1ps
`default_nettype none
module tb_z100_first_conv_event_control;
 reg clk=0; always #5 clk=~clk;
 reg rst_n=0,cancel=0,recover=0,recovery_drained=0,cmd_valid=0;
 reg[31:0] cmd_epoch=1,cmd_job_base=1,cmd_token_base=100,cmd_tag_base=200;
 reg source_leased=1,destination_reserved=1,load_ready=0,load_done=0,load_committed=1,load_fault=0;
 reg[31:0] load_epoch=1;
 reg tile_ready=0,tile_done=0,tile_fault=0;
 reg[31:0] tile_done_epoch=1,tile_done_job=1;
 reg io_quiet=0;
 wire cmd_ready,load_valid,tile_valid,child_cancel,active,needs_drain,done,fault;
 wire[31:0] epoch,job_tag,token_base,tag_base;
 wire[9:0] input_y,input_rows,output_y;
 wire[3:0] fault_code;wire[4:0] committed_tiles;
 z100_first_conv_event dut(.*);
 integer n,k,negative_cases=0,held_cycles=0,drain_cycles=0;
 task step;begin @(posedge clk);#1;@(negedge clk);end endtask
 task reset_case;begin
  rst_n=0;cancel=0;recover=0;recovery_drained=0;cmd_valid=0;
  source_leased=1;destination_reserved=1;load_ready=0;load_done=0;load_committed=1;load_fault=0;
  tile_ready=0;tile_done=0;tile_fault=0;io_quiet=0;
  cmd_epoch=1;cmd_job_base=1;cmd_token_base=100;cmd_tag_base=200;
  load_epoch=1;tile_done_epoch=1;tile_done_job=1;
  step;rst_n=1;step;
 end endtask
 task start;begin if(!cmd_ready)$fatal(1,"admission unavailable");cmd_valid=1;step;cmd_valid=0;end endtask
 task failed(input integer code);begin
  if(!fault||fault_code!=code||!child_cancel||!needs_drain||done||cmd_ready||load_valid||tile_valid)$fatal(1,"fault contract code=%0d actual=%0d",code,fault_code);
  negative_cases=negative_cases+1;
 end endtask
 initial begin
  reset_case;start;
  for(n=0;n<16;n=n+1)begin
   for(k=0;k<3;k=k+1)begin
    if(!load_valid||output_y!=n*20||input_y!=(n==0?0:n*40-1)||input_rows!=(n==0?40:41)||job_tag!=n+1||token_base!=100+n*320||tag_base!=200+n*2880)$fatal(1,"held command geometry");
    step;held_cycles=held_cycles+1;
   end
   load_ready=1;step;load_ready=0;step;
   if(tile_valid)$fatal(1,"compute before load completion");
   load_done=1;step;load_done=0;
   if(!tile_valid)$fatal(1,"missing compute command");
   repeat(3)begin step;held_cycles=held_cycles+1;if(!tile_valid)$fatal(1,"lost held tile");end
   tile_ready=1;step;tile_ready=0;tile_done_job=n+1;
   tile_done=1;step;tile_done=0;
   repeat(4)begin step;drain_cycles=drain_cycles+1;if(done||load_valid||tile_valid)$fatal(1,"advance before write drain");end
   io_quiet=1;step;io_quiet=0;
   if(n==15&&(!done||committed_tiles!=16))$fatal(1,"missing final completion");
  end
  step;if(done)$fatal(1,"done not pulse");
  start;failed(4); // Same job range is never accepted twice.
  recover=1;repeat(3)begin step;if(!fault)$fatal(1,"early recovery without drain");end
  recovery_drained=1;repeat(3)begin step;if(!fault)$fatal(1,"early recovery without quiet");end
  io_quiet=1;step;recover=0;if(!cmd_ready)$fatal(1,"drained recovery failed");
  start;failed(4); // Recovery must preserve identity ledger.
  reset_case;source_leased=0;start;failed(4);
  reset_case;cmd_token_base=32'hfffffff0;start;failed(4);
  reset_case;start;cancel=1;step;failed(1);
  reset_case;start;destination_reserved=0;step;failed(2);
  reset_case;start;load_fault=1;step;failed(2);
  reset_case;start;tile_done=1;step;failed(3);
  reset_case;start;load_ready=1;step;load_ready=0;load_epoch=2;load_done=1;step;failed(5);
  reset_case;start;load_ready=1;step;load_ready=0;load_committed=0;load_done=1;step;failed(5);
  reset_case;start;load_ready=1;step;load_ready=0;load_done=1;step;load_done=0;
  tile_ready=1;step;tile_ready=0;tile_done_job=2;tile_done=1;step;failed(6);
  if(negative_cases!=11||held_cycles!=96||drain_cycles!=64)$fatal(1,"coverage mismatch");
  $display("FIRST_CONV_CONTROL_PASS tiles=16 negative_cases=%0d held_cycles=%0d drain_cycles=%0d",negative_cases,held_cycles,drain_cycles);$finish;
 end
 initial begin #100000;$fatal(1,"watchdog");end
endmodule
`default_nettype wire
