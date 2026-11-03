`timescale 1ns/1ps
module tb_segments_equivalence;
reg [9:0] width;
wire [5:0] narrow;
reg [63:0] original;
integer i;
z100_tile_control_segments_candidate_v1 dut(.cmd_output_width(width), .segments(narrow));
initial begin
 for(i=0;i<1024;i=i+1) begin
  width=i; #1;
  original=({54'd0,width}+19)/20;
  if (original !== {58'd0,narrow}) $fatal(1,"Mismatch width=%0d",i);
 end
 $display("SEGMENTS_EXHAUSTIVE_PASS cases=1024"); $finish;
end
endmodule
