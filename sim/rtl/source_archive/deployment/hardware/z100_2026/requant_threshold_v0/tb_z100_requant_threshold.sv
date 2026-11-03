module tb_z100_requant_threshold;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,cancel=0,cfg_begin=0,cfg_valid=0,in_valid=0,out_ready=0;
 reg [7:0] cfg_address=0;
 reg signed [32:0] cfg_threshold=0;
 reg signed [31:0] in_data=0;
 wire cfg_ready,in_ready,out_valid,error;wire signed [7:0] out_data;
 z100_requant_threshold dut(.*);
 reg [32:0] tables[0:2031];
 reg [31:0] inputs[0:8191];reg [7:0] expected[0:8191];
 integer cases=0,errors=0,table_id,index,k,latency,stalls,phase;
 always @(posedge clk)if(rst_n&&error)errors<=errors+1;
 task load_table;
  input integer which;
  begin
   @(negedge clk);cfg_begin=1;@(negedge clk);cfg_begin=0;
   for(k=0;k<254;k=k+1)begin
    if(!cfg_ready)$fatal(1,"configuration not ready");
    cfg_valid=1;cfg_address=k;cfg_threshold=tables[which*254+k];@(negedge clk);
   end
   cfg_valid=0;#1;
   if(!in_ready)$fatal(1,"complete table not enabled");
  end
 endtask
 task run_one;
  input integer number;
  reg signed [7:0] held;
  begin
   @(negedge clk);in_valid=1;in_data=inputs[number];
   if(!in_ready)$fatal(1,"input not ready");
   @(negedge clk);in_valid=0;latency=0;
   while(!out_valid&&latency<17)begin @(negedge clk);latency=latency+1;end
   if(!out_valid||latency>16)$fatal(1,"search latency");
   if(out_data!==expected[number])$fatal(1,"threshold mismatch case%0d raw%0d got%0d expected%0d",number,in_data,out_data,$signed(expected[number]));
   held=out_data;
   for(stalls=0;stalls<3;stalls=stalls+1)begin
    @(negedge clk);
    if(!out_valid||out_data!==held||in_ready||cfg_ready)$fatal(1,"backpressure violated");
   end
   out_ready=1;@(negedge clk);out_ready=0;cases=cases+1;
  end
 endtask
 initial begin
  $readmemh("tables.hex",tables);$readmemh("inputs.hex",inputs);$readmemh("expected.hex",expected);
  repeat(3)@(negedge clk);rst_n=1;
  if(in_ready)$fatal(1,"unconfigured input accepted");
  for(table_id=0;table_id<8;table_id=table_id+1)begin
   load_table(table_id);
   for(index=0;index<1024;index=index+1)run_one(table_id*1024+index);
  end
  // Reject an incomplete/misordered reload and require a fresh full table.
  @(negedge clk);cfg_begin=1;@(negedge clk);cfg_begin=0;
  cfg_valid=1;cfg_address=3;cfg_threshold=0;@(negedge clk);cfg_valid=0;
  repeat(2)@(negedge clk);if(errors!=1||in_ready)$fatal(1,"bad reload accepted");
  for(phase=0;phase<16;phase=phase+1)begin
   load_table(0);@(negedge clk);in_valid=1;in_data=17;
   @(negedge clk);in_valid=0;repeat(phase)@(negedge clk);cancel=1;
   @(negedge clk);cancel=0;
   repeat(18)begin @(negedge clk);if(out_valid||in_ready)$fatal(1,"cancelled output or table survived");end
  end
  load_table(0);run_one(0);
  @(negedge clk);rst_n=0;@(negedge clk);rst_n=1;
  if(in_ready||out_valid)$fatal(1,"reset retained ownership");
  $display("REQUANT_PASS cases=%0d cancels=16 errors=%0d reset=1 max_search_cycles=16",cases,errors);$finish;
 end
 initial begin #3000000;$fatal(1,"requant timeout");end
endmodule
