`timescale 1ns/1ps
module tb_bram_observer_selftest;
    reg clk=0; always #5 clk=~clk;
    reg ena=0,wea=0,enb=0,rsta=0,rstb=0;
    reg [6:0] addra=0,addrb=0;
    bram_collision_observer #(.INIT_SKIP(0),.EXPECT_DIAGNOSTICS(1)) dut(.*);
    task step(input bit a,input bit w,input bit b,input [6:0] wa,input [6:0] ra,input bit reset_b);
        @(negedge clk); ena=a;wea=w;enb=b;addra=wa;addrb=ra;rstb=reset_b;
        @(posedge clk); #1;
    endtask
    initial begin
        // No access; equal but unknown addresses must not be mistaken for traffic.
        step(0,0,0,7'bx,7'bx,0);
        step(0,1,1,10,10,0); // ENA off must suppress write even when WEA is on
        step(1,0,1,11,11,0); // WEA off must suppress write even when ENA is on
        step(1,1,1,4,5,0); // simultaneous different-address control
        step(1,1,1,6,6,0); // positive collision, ordinary operation
        step(1,1,1,7,7,1); // reset must not hide a collision
        step(1,1,0,127,0,0); step(1,1,0,0,0,0);
        step(0,0,1,0,127,0); step(0,0,1,0,0,0);
        step(1,1,0,7'bx,0,0); // active unknown address must be reported
        if(dut.collisions!=2 || dut.concurrent!=3 || dut.unknowns!=1 ||
           dut.write_wraps!=1 || dut.read_wraps!=1 || dut.reset_cycles!=1 ||
           dut.reset_writes!=1 || dut.reset_reads!=1 || dut.writes!=5 || dut.reads!=7) begin
            $display("FAIL BRAM observer selftest counters"); $finish;
        end
        $display("PASS BRAM observer selftest collision=2 unknown=1 distinct_control=1 disabled_control=1 reset_collision=1 write_wrap=1 read_wrap=1");
        $finish;
    end
endmodule
