`timescale 1ns/1ps
`default_nettype none
`include "fixture_defs.vh"
module tb_z100_maxpool_vector;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,in_valid=0,in_first=0,in_last=0,out_ready=0;
    reg [31:0] in_epoch=0,in_token=0;
    reg [6:0] in_lanes=0;
    reg [79:0] in_mask=0;
    reg [639:0] in_data=0;
    wire in_ready,out_valid,error_valid,active;
    wire [31:0] out_epoch,out_token;
    wire [6:0] out_lanes;
    wire [639:0] out_data;
    z100_maxpool_vector dut(.*);
    reg [719:0] taps[0:`VECTORS*25-1];
    reg [639:0] golden[0:`VECTORS-1];
    reg [6:0] lanes[0:`VECTORS-1];
    integer v,t,checked=0,accepted=0,holds=0,errors=0,recoveries=0;
    reg [639:0] held;
    task tick;begin @(posedge clk);#1;end endtask
    task send(input bit first_arg,last_arg);
        begin
            @(negedge clk);in_first=first_arg;in_last=last_arg;in_valid=1;
            #1;
            while(!in_ready) begin tick();@(negedge clk);#1;end
            tick();accepted=accepted+1;
            @(negedge clk);in_valid=0;
        end
    endtask
    task clear_state;
        begin
            @(negedge clk);cancel=1;in_valid=0;tick();
            if(active||out_valid||error_valid) $fatal(1,"cancel did not flush");
            @(negedge clk);cancel=0;in_epoch=200;in_token=99999;in_lanes=3;
            in_data={80{8'hf7}};in_mask={80{1'b1}};out_ready=0;
        end
    endtask
    task expect_error;
        begin
            if(!error_valid||active||out_valid) $fatal(1,"malformed sequence not rejected");
            errors=errors+1;
            tick();if(error_valid)$fatal(1,"error not a pulse");
        end
    endtask
    task recover;
        begin
            clear_state();send(1,1);
            if(!out_valid || out_lanes!=3 || out_data[23:0]!==24'hf7f7f7 || out_data[639:24]!==0)
                $fatal(1,"recovery result/tail incorrect");
            @(negedge clk);out_ready=1;tick();
            if(out_valid)$fatal(1,"recovery result failed to drain");
            recoveries=recoveries+1;
        end
    endtask
    initial begin
        $readmemh("taps.hex",taps);$readmemh("golden.hex",golden);$readmemh("lanes.hex",lanes);
        repeat(5)tick();@(negedge clk);rst_n=1;tick();
        for(v=0;v<`VECTORS;v=v+1) begin
            in_epoch=200;in_token=v+1;in_lanes=lanes[v];out_ready=0;
            for(t=0;t<25;t=t+1)begin
                if((t+v)%7==0)tick();
                in_data=taps[v*25+t][639:0];in_mask=taps[v*25+t][719:640];
                send(t==0,t==24);
            end
            if(!out_valid||active||error_valid||out_epoch!=200||out_token!=v+1||
                out_lanes!=lanes[v]||out_data!==golden[v])$fatal(1,"maxpool mismatch vector%0d",v);
            held=out_data;
            repeat(v%5+1)begin
                tick();if(!out_valid||out_data!==held||out_token!=v+1)$fatal(1,"held result changed");
                holds=holds+1;
            end
            @(negedge clk);out_ready=1;tick();
            if(out_valid)$fatal(1,"result did not drain");
            checked=checked+1;
        end
        // Eight protocol errors, each followed by a valid transaction.
        clear_state();send(0,1);expect_error();recover();
        clear_state();send(1,0);send(1,1);expect_error();recover();
        clear_state();send(1,0);in_token=99998;send(0,1);expect_error();recover();
        clear_state();in_mask=0;send(1,1);expect_error();recover();
        clear_state();in_lanes=0;send(1,1);expect_error();recover();
        clear_state();in_lanes=81;send(1,1);expect_error();recover();
        clear_state();in_epoch=0;send(1,1);expect_error();recover();
        clear_state();in_token=0;send(1,1);expect_error();recover();
        clear_state();send(1,0);clear_state();recover();
        clear_state();send(1,1);clear_state();recover();
        clear_state();send(1,0);
        @(negedge clk);rst_n=0;tick();if(active||out_valid)$fatal(1,"reset active");
        @(negedge clk);rst_n=1;recover();
        clear_state();send(1,1);
        @(negedge clk);rst_n=0;tick();if(active||out_valid)$fatal(1,"reset result");
        @(negedge clk);rst_n=1;recover();
        if(checked!=`VECTORS||errors!=8||recoveries!=12||holds<`VECTORS)
            $fatal(1,"coverage gate");
        $display("MAXPOOL_VECTOR_PASS vectors=%0d taps=%0d bytes=%0d held_cycles=%0d errors=%0d recoveries=%0d",checked,`VECTORS*25,`VALID_BYTES,holds,errors,recoveries);
        $finish;
    end
endmodule
`default_nettype wire
