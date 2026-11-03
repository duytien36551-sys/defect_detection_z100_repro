module tb_z100_reuse_command_bridge;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,cancel=0,cmd_valid=0,result_ready=0;
 reg [2:0] cmd_opcode=0,cmd_sites=4;reg [11:0] cmd_address=0;
 reg [1023:0] cmd_data=0;reg [3:0] cmd_site_mask=15;
 reg [12:0] cmd_taps=5;reg [5:0] cmd_lanes=32;
 wire cmd_ready,result_valid,error;wire [1023:0] result_data;
 wire [31:0] result_overflow;wire [1:0] result_site;
 wire result_last;wire [5:0] result_lanes;
 z100_reuse_command_bridge dut(.*);
 integer accepted=0,results=0,cancels=0,errors=0,resets=0;
 always @(posedge clk)if(rst_n&&!cancel&&cmd_valid&&cmd_ready)accepted<=accepted+1;
 always @(posedge clk)if(rst_n&&!cancel&&error)errors<=errors+1;
 task send;
  input integer op,address;input [1023:0] data;
  integer timeout;
  begin
   @(negedge clk);cmd_valid=1;cmd_opcode=op;cmd_address=address;cmd_data=data;timeout=0;
   while(!cmd_ready&&timeout<100)begin @(negedge clk);timeout=timeout+1;end
   if(!cmd_ready)$fatal(1,"command timeout");
   @(posedge clk);@(negedge clk);cmd_valid=0;
  end
 endtask
 task preload;
  integer tap,lane;reg [1023:0] value;
  begin
   send(0,0,0);value=0;
   for(lane=0;lane<32;lane=lane+1)value[lane*32+:32]=lane-17;
   send(1,0,value);
   for(tap=0;tap<5;tap=tap+1)begin
    value=0;for(lane=0;lane<32;lane=lane+1)value[lane*8+:8]=lane%5-2;
    send(2,tap,value);
    value=0;for(lane=0;lane<4;lane=lane+1)value[lane*8+:8]=tap+lane-3;
    send(3,tap,value);
   end
  end
 endtask
 task drain;
  integer site,lane,expected,timeout,stall;reg [1023:0] held;reg [31:0] overflow;
  begin
   for(site=0;site<4;site=site+1)begin
    timeout=0;
    while(!result_valid&&timeout<100)begin @(negedge clk);timeout=timeout+1;end
    if(!result_valid)$fatal(1,"result timeout");
    held=result_data;overflow=result_overflow;
    for(stall=0;stall<7;stall=stall+1)begin
     @(negedge clk);
     if(!result_valid||result_data!==held||result_overflow!==overflow||result_site!==site[1:0])$fatal(1,"stalled result changed");
    end
    if(result_last!==(site==3)||result_lanes!==32||overflow!==0)$fatal(1,"result metadata");
    for(lane=0;lane<32;lane=lane+1)begin
     expected=lane-17+(lane%5-2)*(5*site-5);
     if($signed(result_data[lane*32+:32])!==expected)$fatal(1,"scalar mismatch lane%0d site%0d",lane,site);
    end
    result_ready=1;@(posedge clk);@(negedge clk);result_ready=0;results=results+1;
   end
  end
 endtask
 integer delay_stage;
 initial begin
  repeat(3)@(posedge clk);@(negedge clk);rst_n=1;
  preload();send(4,0,0);drain();
  // Cancel a queued command and each of the four pipeline offsets.
  for(delay_stage=0;delay_stage<5;delay_stage=delay_stage+1)begin
   preload();send(4,0,0);repeat(delay_stage)@(negedge clk);
   cancel=1;@(posedge clk);@(negedge clk);cancel=0;cancels=cancels+1;
   repeat(12)begin @(negedge clk);if(result_valid)$fatal(1,"stale cancelled output");end
  end
  // Cancel a result held in the elastic output register.
  preload();send(4,0,0);wait(result_valid);@(negedge clk);cancel=1;
  @(posedge clk);@(negedge clk);cancel=0;cancels=cancels+1;
  if(result_valid)$fatal(1,"stalled output survived cancel");
  preload();send(4,0,0);drain();
  send(7,0,0);repeat(2)@(negedge clk);
  if(errors!=1)$fatal(1,"reserved opcode error missing or repeated");
  preload();send(4,0,0);drain();
  // A queued command cannot execute across a stalled result boundary.
  preload();send(4,0,0);wait(result_valid);send(7,0,0);
  repeat(5)begin @(negedge clk);if(cmd_ready||errors!=1)$fatal(1,"queued command bypassed result stall");end
  drain();repeat(3)@(negedge clk);
  if(errors!=2)$fatal(1,"queued reserved opcode did not execute exactly once");
  // Reset invalidates both a held result and a queued command.
  preload();send(4,0,0);wait(result_valid);send(7,0,0);
  @(negedge clk);rst_n=0;#1;
  if(result_valid||cmd_ready)$fatal(1,"reset handshake not suppressed");
  repeat(2)@(negedge clk);rst_n=1;resets=resets+1;
  repeat(12)begin @(negedge clk);if(result_valid||errors!=2)$fatal(1,"stale reset command/result");end
  preload();send(4,0,0);drain();
  $display("BRIDGE_PASS commands=%0d results=%0d cancels=%0d errors=%0d resets=%0d",accepted,results,cancels,errors,resets);$finish;
 end
 initial begin #200000;$fatal(1,"global timeout");end
endmodule
