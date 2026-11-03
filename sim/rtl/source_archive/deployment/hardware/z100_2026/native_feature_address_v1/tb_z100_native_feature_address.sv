`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_feature_address;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,clear_fault=0,begin_valid=0,in_valid=0,in_last=1,out_ready=0;
    reg [31:0] begin_epoch=200,in_epoch=200;
    reg [9:0] channels=8,height=1,width=16;
    reg [11:0] in_native_word=0;
    reg [511:0] in_data=512'h817265;
    wire begin_ready,in_ready,out_valid,out_last,active,fault,done;
    wire [31:0] out_epoch;wire [12:0] out_address;wire [511:0] out_data;wire [3:0] fault_code;
    z100_native_feature_address dut(.*);
    integer rejected=0,holds=0,k,j;
    task automatic begin_tile;
        begin @(negedge clk);begin_valid=1;if(!begin_ready)$fatal(1,"Begin blocked");@(negedge clk);begin_valid=0;end
    endtask
    task automatic clear;
        begin
            if(!fault||active||out_valid)$fatal(1,"Expected closed fault");rejected=rejected+1;
            in_valid=0;clear_fault=1;@(negedge clk);clear_fault=0;if(fault||active)$fatal(1,"Recovery failed");
        end
    endtask
    initial begin
        repeat(4)@(negedge clk);rst_n=1;
        for(j=0;j<6;j=j+1)begin
            channels=8;height=1;width=16;begin_epoch=200;
            case(j)0:channels=12;1:channels=0;2:height=0;3:width=641;4:begin_epoch=0;
                5:begin channels=512;height=640;width=640;end endcase
            begin_tile();clear();
        end
        for(j=0;j<3;j=j+1)begin
            channels=8;height=1;width=16;begin_epoch=200;begin_tile();
            in_epoch=200;in_native_word=0;in_last=0;
            case(j)0:in_epoch=201;1:in_native_word=1;2:in_last=1;endcase
            in_valid=1;#1;if(out_valid||!in_ready)$fatal(1,"Bad metadata forwarded");@(negedge clk);clear();
        end
        begin_tile();in_epoch=200;in_native_word=0;in_last=0;in_valid=1;
        for(k=0;k<20;k=k+1)begin #1;
            if(!out_valid||in_ready||out_address!=0||out_epoch!=200||out_last||out_data!==in_data)$fatal(1,"Held payload/address");
            holds=holds+1;@(negedge clk);end
        cancel=1;#1;if(out_valid||in_ready)$fatal(1,"Cancelled word forwarded");@(negedge clk);cancel=0;clear();
        begin_tile();in_valid=1;out_ready=1;in_epoch=200;in_native_word=0;in_last=0;
        @(negedge clk);in_native_word=1;in_last=1;
        #1;if(out_address!=1||!out_last)$fatal(1,"Second word map");@(negedge clk);in_valid=0;
        if(!done||active||fault)$fatal(1,"Completion failed");
        if(rejected!=10||holds!=20)$fatal(1,"Coverage");
        $display("FEATURE_ADDRESS_GUARD_PASS rejected=10 held_cycles=20 recovery_completion=1");$finish;
    end
    initial begin #100000;$fatal(1,"Guard watchdog");end
endmodule
`default_nettype wire
