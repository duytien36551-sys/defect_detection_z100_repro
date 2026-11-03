`timescale 1ns/1ps
`default_nettype none
module tb_z100_conv_event_control;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,cancel=0,recover=0,recovery_drained=0,cmd_valid=0;
 reg[31:0] cmd_epoch=1,cmd_job_base=1,cmd_token_base=100,cmd_tag_base=200;
 reg[7:0] cmd_tiles=1;reg[9:0] cmd_output_height=20;
 reg source_leased=1,destination_reserved=1,descriptor_valid=0;
 reg[31:0] descriptor_epoch=1,descriptor_runs=16,descriptor_windows=144;
 reg[7:0] descriptor_index=0;
 reg[9:0] descriptor_input_y=0,descriptor_input_rows=40,descriptor_output_y=0,descriptor_output_rows=20;
 reg load_ready=0,load_done=0,load_committed=1,load_fault=0;
 reg[31:0] load_epoch=1;
 reg tile_ready=0,tile_done=0,tile_fault=0;
 reg[31:0] tile_done_epoch=1,tile_done_job=1;
 reg io_quiet=0;
 wire cmd_ready,descriptor_ready,load_valid,tile_valid,child_cancel,active,needs_drain,done,fault;
 wire[31:0] epoch,job_tag,token_base,tag_base;
 wire[9:0] input_y,input_rows,output_y,output_rows;
 wire[7:0] next_descriptor,committed_tiles;wire[3:0] fault_code;
 z100_conv_event_control dut(.*);
 reg[31:0] plan[0:3023];
 integer first,last,ti,j,k,events=0,tiles=0,negative_cases=0,held_cycles=0,drain_cycles=0;
 reg[31:0] expected_token=100,expected_tag=200;
 task step;begin @(posedge clk);#1;@(negedge clk);end endtask
 task reset_case;begin
  rst_n=0;cancel=0;recover=0;recovery_drained=0;cmd_valid=0;descriptor_valid=0;
  source_leased=1;destination_reserved=1;load_ready=0;load_done=0;load_committed=1;load_fault=0;
  tile_ready=0;tile_done=0;tile_fault=0;io_quiet=0;
  cmd_epoch=1;cmd_job_base=1;cmd_token_base=100;cmd_tag_base=200;cmd_tiles=1;cmd_output_height=20;
  descriptor_epoch=1;descriptor_index=0;descriptor_input_y=0;descriptor_input_rows=40;
  descriptor_output_y=0;descriptor_output_rows=20;descriptor_runs=16;descriptor_windows=144;
  load_epoch=1;tile_done_epoch=1;tile_done_job=1;
  step;rst_n=1;step;
 end endtask
 task start;begin if(!cmd_ready)$fatal(1,"admission unavailable");cmd_valid=1;step;cmd_valid=0;end endtask
 task desc;begin if(!descriptor_ready)$fatal(1,"descriptor unavailable");descriptor_valid=1;step;descriptor_valid=0;end endtask
 task failed(input integer code);begin
  if(!fault||fault_code!=code||!child_cancel||!needs_drain||done||cmd_ready||descriptor_ready||load_valid||tile_valid)$fatal(1,"fault contract code=%0d actual=%0d",code,fault_code);
  negative_cases=negative_cases+1;
 end endtask
 initial begin
  $readmemh("event_plan.hex",plan);
  reset_case;first=0;
  while(first<189)begin
   last=first;
   while(last+1<189&&plan[(last+1)*16+15]==plan[first*16+15])last=last+1;
   cmd_tiles=last-first+1;cmd_job_base=100+first;cmd_output_height=plan[first*16+7];
   cmd_token_base=expected_token;cmd_tag_base=expected_tag;start;
   for(ti=first;ti<=last;ti=ti+1)begin
    if(!descriptor_ready||next_descriptor!=ti-first)$fatal(1,"plan request order");
    repeat(2)begin step;if(!descriptor_ready||load_valid||tile_valid)$fatal(1,"advance without descriptor");end
    descriptor_index=ti-first;descriptor_input_y=plan[ti*16+3];descriptor_input_rows=plan[ti*16+4];
    descriptor_output_y=plan[ti*16+5];descriptor_output_rows=plan[ti*16+6];
    descriptor_runs=plan[ti*16+13];descriptor_windows=plan[ti*16+14];desc;
    repeat(3)begin
     if(!load_valid||epoch!=1||job_tag!=100+ti||token_base!=expected_token||tag_base!=expected_tag||
        input_y!=plan[ti*16+3]||input_rows!=plan[ti*16+4]||output_y!=plan[ti*16+5]||output_rows!=plan[ti*16+6])$fatal(1,"held plan payload tile=%0d",ti);
     step;held_cycles=held_cycles+1;
    end
    load_ready=1;step;load_ready=0;step;if(tile_valid)$fatal(1,"compute before load");
    load_done=1;step;load_done=0;
    repeat(3)begin if(!tile_valid)$fatal(1,"lost held tile");step;held_cycles=held_cycles+1;end
    tile_ready=1;step;tile_ready=0;tile_done_job=100+ti;tile_done=1;step;tile_done=0;
    repeat(4)begin step;drain_cycles=drain_cycles+1;if(done||load_valid||tile_valid||descriptor_ready)$fatal(1,"advance before write drain");end
    io_quiet=1;step;io_quiet=0;
    if(ti==last&&(!done||committed_tiles!=last-first+1))$fatal(1,"missing whole producer completion");
    if(ti!=last&&done)$fatal(1,"early whole producer completion");
    expected_token=expected_token+descriptor_runs;expected_tag=expected_tag+descriptor_windows;tiles=tiles+1;
   end
   step;if(done)$fatal(1,"done not pulse");events=events+1;first=last+1;
  end
  start;failed(4);
  recover=1;repeat(3)begin step;if(!fault)$fatal(1,"recovered without drain");end
  recovery_drained=1;repeat(3)begin step;if(!fault)$fatal(1,"recovered without quiet");end
  io_quiet=1;step;recover=0;start;failed(4);
  reset_case;source_leased=0;start;failed(4);
  reset_case;cmd_job_base=32'hffffffff;cmd_tiles=2;start;failed(4);
  reset_case;start;cancel=1;step;failed(1);
  reset_case;start;destination_reserved=0;step;failed(2);
  reset_case;start;load_fault=1;step;failed(2);
  reset_case;start;tile_done=1;step;failed(3);
  reset_case;start;desc;load_ready=1;step;load_ready=0;load_epoch=2;load_done=1;step;failed(5);
  reset_case;start;desc;load_ready=1;step;load_ready=0;load_committed=0;load_done=1;step;failed(5);
  reset_case;start;desc;load_ready=1;step;load_ready=0;load_done=1;step;load_done=0;
  tile_ready=1;step;tile_ready=0;tile_done_job=2;tile_done=1;step;failed(6);
  reset_case;start;descriptor_epoch=2;desc;failed(8);
  reset_case;start;descriptor_index=1;desc;failed(8);
  reset_case;start;descriptor_output_y=1;desc;failed(8);
  reset_case;start;descriptor_output_rows=19;desc;failed(8);
  reset_case;start;descriptor_input_y=639;desc;failed(8);
  reset_case;start;descriptor_runs=0;desc;failed(8);
  reset_case;start;descriptor_windows=15;desc;failed(8);
  reset_case;cmd_token_base=32'hfffffff1;start;desc;failed(8);
  reset_case;cmd_tag_base=32'hffffff80;start;desc;failed(8);
  // A final allocation may end exactly at 2^32; a nonfinal one may not.
  reset_case;cmd_token_base=32'hfffffff0;start;desc;if(!load_valid||fault)$fatal(1,"exact final token boundary");
  reset_case;cmd_token_base=32'hfffffff0;cmd_tiles=2;cmd_output_height=40;start;desc;failed(8);
  if(events!=63||tiles!=189||negative_cases!=21||held_cycles!=1134||drain_cycles!=756)$fatal(1,"coverage mismatch events=%0d tiles=%0d negative=%0d",events,tiles,negative_cases);
  $display("CONV_EVENT_CONTROL_PASS events=63 tiles=189 negative_cases=21 held_cycles=1134 drain_cycles=756");$finish;
 end
 initial begin #1000000;$fatal(1,"watchdog");end
endmodule
`default_nettype wire
