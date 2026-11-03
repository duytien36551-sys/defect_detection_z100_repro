`timescale 1ns/1ps
`default_nettype none
module tb_z100_int8_pair_packing;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,in_valid=0;
    reg signed [7:0] in_activation=0,in_weight_low=0,in_weight_high=0;
    wire out_valid;
    wire signed [15:0] out_product_low,out_product_high;
    z100_int8_pair_packing dut(.*);
    integer expected_lo[0:7],expected_hi[0:7];
    integer write_index=0,read_index=0,checks=0,inputs=0,bubbles=0,flushes=0,streak=0,max_streak=0;
    reg previous_valid=0;
    reg [31:0] rng=32'h7a1008ff;
    integer lo,hi,a,edge_index,n;
    function automatic integer edge_value(input integer index);
        case(index)
            0:edge_value=-128;1:edge_value=-127;2:edge_value=-1;3:edge_value=0;
            4:edge_value=1;5:edge_value=63;6:edge_value=126;default:edge_value=127;
        endcase
    endfunction
    task automatic drive(input integer act,wl,wh,valid);
        begin
            @(negedge clk);in_activation=act;in_weight_low=wl;in_weight_high=wh;in_valid=valid;
        end
    endtask
    always @(posedge clk) begin
        if(!rst_n || cancel) begin
            if(out_valid) $fatal(1,"packing reset/cancel failed to suppress output");
            write_index=0;read_index=0;previous_valid=0;streak=0;
        end else begin
            if(out_valid!==previous_valid) $fatal(1,"packing valid latency is not one arithmetic cycle");
            previous_valid=in_valid;
            if(out_valid) begin
                if(read_index==write_index || out_product_low!==expected_lo[read_index%8] ||
                    out_product_high!==expected_hi[read_index%8])
                    $fatal(1,"pair product mismatch low=%0d/%0d high=%0d/%0d",out_product_low,
                        expected_lo[read_index%8],out_product_high,expected_hi[read_index%8]);
                read_index=read_index+1;checks=checks+1;streak=streak+1;
                if(streak>max_streak) max_streak=streak;
            end else streak=0;
            if(in_valid) begin
                expected_lo[write_index%8]=$signed(in_activation)*$signed(in_weight_low);
                expected_hi[write_index%8]=$signed(in_activation)*$signed(in_weight_high);
                write_index=write_index+1;inputs=inputs+1;
            end else bubbles=bubbles+1;
        end
    end
    initial begin
        repeat(3)@(negedge clk);rst_n=1;
        // Every activation and low weight, with each high-weight edge.
        for(edge_index=0;edge_index<8;edge_index=edge_index+1)
            for(lo=-128;lo<128;lo=lo+1)
                for(a=-128;a<128;a=a+1)
                    drive(a,lo,edge_value(edge_index),1);
        // Every activation and high weight, with each low-weight edge.
        for(edge_index=0;edge_index<8;edge_index=edge_index+1)
            for(hi=-128;hi<128;hi=hi+1)
                for(a=-128;a<128;a=a+1)
                    drive(a,edge_value(edge_index),hi,1);
        for(n=0;n<65536;n=n+1) begin
            rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            drive(rng[7:0],rng[15:8],rng[23:16],n%17!=0);
        end
        drive(0,0,0,0);repeat(3)@(negedge clk);
        if(read_index!=write_index || checks!=inputs) $fatal(1,"packing outputs lost before flush");
        // Discard a live product at both cancellation and reset boundaries.
        drive(-128,-128,-128,1);@(posedge clk);#1;
        @(negedge clk);cancel=1;in_valid=0;
        @(posedge clk);#1;flushes=flushes+1;
        @(negedge clk);cancel=0;
        drive(127,-128,127,1);drive(0,0,0,0);repeat(3)@(negedge clk);
        drive(-128,127,-128,1);@(posedge clk);#1;
        @(negedge clk);rst_n=0;in_valid=0;
        @(posedge clk);#1;flushes=flushes+1;
        @(negedge clk);rst_n=1;
        drive(-128,-128,-128,1);drive(0,0,0,0);repeat(3)@(negedge clk);
        if(read_index!=write_index || inputs-checks!=2 || checks<1100000 || max_streak<65536 || bubbles<3800 || flushes!=2)
            $fatal(1,"packing coverage inputs=%0d checks=%0d streak=%0d bubbles=%0d flush=%0d",
                inputs,checks,max_streak,bubbles,flushes);
        $display("INT8_PAIR_PACKING_PASS inputs=%0d outputs=%0d ii1_streak=%0d bubbles=%0d flushes=%0d latency=1 signed_edge=-128",
            inputs,checks,max_streak,bubbles,flushes);
        $finish;
    end
    initial begin #20000000;$fatal(1,"packing watchdog");end
endmodule
`default_nettype wire
