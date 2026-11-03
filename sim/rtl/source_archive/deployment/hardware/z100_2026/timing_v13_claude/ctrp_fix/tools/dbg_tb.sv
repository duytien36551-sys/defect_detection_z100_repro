`timescale 1ns/1ps
module dbg_tb;
  reg clk=0; always #5 clk=~clk;
  wire [63:0] st0, st1;
  fb_driver #(.V13P(0),.DATA_SEED(1),.TIME_SEED(1),.CYCLES(200)) d0(.clk(clk),.dbg(st0));
  fb_driver #(.V13P(1),.DATA_SEED(1),.TIME_SEED(102),.CYCLES(200)) d1(.clk(clk),.dbg(st1));
  integer n=0;
  always @(negedge clk) begin
     n=n+1;
     if (n<60) $display("cyc %0d A: ph=%0d br=%b ld=%b sv=%b ov=%b cb=%b cw=%b cc=%b cancel=%b | B: ph=%0d br=%b ld=%b cb=%b", n, st0[3:0], st0[4], st0[5], st0[6], st0[7], st0[8], st0[9], st0[10], st0[11], st1[3:0], st1[4], st1[5], st1[8]);
     if (n==60) $finish;
  end
endmodule
