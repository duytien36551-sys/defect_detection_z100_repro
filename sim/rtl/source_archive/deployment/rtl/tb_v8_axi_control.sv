`timescale 1ns/1ps
module tb_v8_axi_control;
reg clk=0, rst=0;
always #3 clk=~clk;
reg [3:0] awaddr=0;
reg [31:0] wdata=0;
reg awvalid=0,wvalid=0;
wire awready,wready,bvalid;
wire [1:0] bresp;
wire [31:0] r0,r1,r2,r3;
wire [31:0] data;
wire valid,last,ready,finish;
reg input_valid=0,input_last=0;
reg batch_mode=0;
axi4_lite_v1_0_S00_AXI bus(.slave_reg0(r0),.slave_reg1(r1),.slave_reg2(r2),.slave_reg3(r3),
 .S_AXI_ACLK(clk),.S_AXI_ARESETN(rst),.S_AXI_AWADDR(awaddr),.S_AXI_AWPROT(3'b0),
 .S_AXI_AWVALID(awvalid),.S_AXI_AWREADY(awready),.S_AXI_WDATA(wdata),.S_AXI_WSTRB(4'hf),
 .S_AXI_WVALID(wvalid),.S_AXI_WREADY(wready),.S_AXI_BRESP(bresp),.S_AXI_BVALID(bvalid),.S_AXI_BREADY(1'b1),
 .S_AXI_ARADDR(4'b0),.S_AXI_ARPROT(3'b0),.S_AXI_ARVALID(1'b0),.S_AXI_RREADY(1'b1));
v8_accel_top dut(.sclk(clk),.s_rst_n(rst),.slave_lite_reg0(r0),.slave_lite_reg1(r1),
 .slave_lite_reg2(r2),.slave_lite_reg3(r3),.s_axis_mm2s_tdata(32'b0),.s_axis_mm2s_tkeep(4'hf),
 .s_axis_mm2s_tvalid(input_valid),.s_axis_mm2s_tready(ready),.s_axis_mm2s_tlast(input_last),
 .s_axis_s2mm_tdata(data),.s_axis_s2mm_tvalid(valid),.s_axis_s2mm_tlast(last),
 .s_axis_s2mm_tready(1'b1),.task_finish(finish));
task wr(input [3:0] addr,input [31:0] value);
 begin
 @(negedge clk);awaddr=addr;wdata=value;awvalid=1;wvalid=1;
 do @(posedge clk);while(!(awready&&wready));
 @(negedge clk);awvalid=0;wvalid=0;
 do @(posedge clk);while(!bvalid);
 @(negedge clk);
 end
endtask
integer outputs=0;
always @(posedge clk) if(valid) begin
 if(!batch_mode) begin
  if(outputs==0 && (data!==32'h18c047a5 || last!==0)) $fatal(1,"probe raw");
  if(outputs==1 && (data!==32'h563a0000 || last!==1)) $fatal(1,"probe status");
 end else begin
  if(data !== ((outputs%2==0)?32'd7:32'h563a0000)) $fatal(1,"continuous batch result");
  if(last !== (outputs==1211)) $fatal(1,"continuous batch last");
 end
 outputs=outputs+1;
end
integer i;
initial begin
 repeat(4) @(negedge clk);rst=1;
 wr(0,2);
 repeat(20) begin @(negedge clk);if(r0!==2||valid) $fatal(1,"ABORT did not hold");end
 wr(0,0);repeat(3) @(negedge clk);
 wr(4,0);wr(8,32'h18c047a5);wr(12,1);wr(0,1);
 repeat(10) @(negedge clk);
 if(r0!==0||outputs!=2) $fatal(1,"START pulse/probe contract");
 batch_mode=1;outputs=0;
 wr(4,27);wr(8,7);wr(12,606);wr(0,1);
 @(negedge clk);input_valid=1;
 for(i=0;i<16362;i=i+1) begin
  input_last=(i==16361);
  do @(posedge clk);while(!ready);
  @(negedge clk);
 end
 input_valid=0;input_last=0;
 repeat(15) @(negedge clk);
 if(outputs!=1212) $fatal(1,"continuous full batch count %d",outputs);
 $display("PASS AXI-Lite held ABORT, pulse START, probe and concurrent 606-dot batch");$finish;
end
initial begin #1000000;$fatal(1,"watchdog");end
endmodule
