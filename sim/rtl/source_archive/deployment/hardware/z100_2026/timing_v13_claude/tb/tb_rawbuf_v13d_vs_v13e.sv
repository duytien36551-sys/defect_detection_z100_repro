`timescale 1ns/1ps
// Cycle-exact lockstep miter: z100_native_raw_buffer_v13d vs _v13e.
// Same random stimulus (valid/ready/data, cancel and reset pulses); every
// output is compared every cycle once the first reset has been applied.
module tb_rawbuf_v13d_vs_v13e;
    parameter integer SEED=1, CYCLES=200000;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0, cancel=0, in_valid=0, in_last=0, out_ready=0;
    reg [31:0] in_epoch=0, in_token=0; reg [4:0] in_site=0; reg [1023:0] in_data=0;
    wire c_ir,c_ov,c_ol,d_ir,d_ov,d_ol;
    wire [31:0] c_oe,c_ot,d_oe,d_ot; wire [4:0] c_os,d_os; wire [1023:0] c_od,d_od;
    z100_native_raw_buffer_v13d c(.clk(clk),.rst_n(rst_n),.cancel(cancel),.in_valid(in_valid),.in_ready(c_ir),
        .in_epoch(in_epoch),.in_token(in_token),.in_site(in_site),.in_last(in_last),.in_data(in_data),
        .out_valid(c_ov),.out_ready(out_ready),.out_epoch(c_oe),.out_token(c_ot),.out_site(c_os),.out_last(c_ol),.out_data(c_od));
    z100_native_raw_buffer_v13e d(.clk(clk),.rst_n(rst_n),.cancel(cancel),.in_valid(in_valid),.in_ready(d_ir),
        .in_epoch(in_epoch),.in_token(in_token),.in_site(in_site),.in_last(in_last),.in_data(in_data),
        .out_valid(d_ov),.out_ready(out_ready),.out_epoch(d_oe),.out_token(d_ot),.out_site(d_os),.out_last(d_ol),.out_data(d_od));
    integer s, cyc=0, errs=0, pushes=0, pops=0, fulls=0, k, mode=0;
    reg armed=0;
    always @(negedge clk) begin
        cyc=cyc+1;
        if(cyc%5000==0) mode={$random(s)}%4;  // vary pressure: 0 balanced 1 producer-heavy 2 consumer-heavy 3 bursty
        rst_n <= !(cyc<4 || ({$random(s)}%20000)==0);
        cancel <= ({$random(s)}%700)==0;
        case(mode)
            0: begin in_valid<=({$random(s)}%2); out_ready<=({$random(s)}%2); end
            1: begin in_valid<=({$random(s)}%8)!=0; out_ready<=({$random(s)}%4)==0; end
            2: begin in_valid<=({$random(s)}%4)==0; out_ready<=({$random(s)}%8)!=0; end
            default: begin in_valid<=((cyc/7)%2); out_ready<=((cyc/11)%2); end
        endcase
        in_epoch<=$random(s); in_token<=$random(s); in_site<=$random(s); in_last<=$random(s);
        for(k=0;k<32;k=k+1) in_data[k*32+:32]<=$random(s);
    end
    always @(posedge clk) begin
        if(!rst_n) armed<=1;
        #1;
        if(armed) begin
            if({c_ir,c_ov}!=={d_ir,d_ov} ||
               (c_ov && {c_oe,c_ot,c_os,c_ol,c_od}!=={d_oe,d_ot,d_os,d_ol,d_od})) begin
                errs=errs+1;
                if(errs<5) $display("MISMATCH cyc=%0d ir %b/%b ov %b/%b", cyc, c_ir, d_ir, c_ov, d_ov);
            end
            if(in_valid && c_ir) pushes=pushes+1;
            if(c_ov && out_ready) pops=pops+1;
            if(!c_ir && rst_n && !cancel) fulls=fulls+1;
        end
    end
    initial begin
        s=SEED;
        repeat(CYCLES) @(posedge clk);
        $display("RAWBUF seed=%0d cycles=%0d pushes=%0d pops=%0d full_cycles=%0d mismatches=%0d %s",
                 SEED, CYCLES, pushes, pops, fulls, errs, errs==0 ? "IDENTICAL" : "FAIL");
        $finish;
    end
endmodule
