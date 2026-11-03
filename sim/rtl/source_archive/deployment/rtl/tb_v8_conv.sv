`timescale 1ns/1ps
module tb_v8_conv;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, start = 0, tap_valid = 0;
    reg [31:0] tap_count = 0;
    reg signed [31:0] bias = 0;
    reg signed [7:0] activation = 0, weight = 0;
    wire tap_ready, out_valid, out_overflow, busy;
    wire signed [31:0] raw_acc;
    v8_conv_mac dut(.clk(clk), .rst_n(rst_n), .start(start),
        .tap_count(tap_count), .bias(bias), .tap_valid(tap_valid),
        .activation(activation), .weight(weight), .tap_ready(tap_ready),
        .out_valid(out_valid), .out_overflow(out_overflow),
        .raw_acc(raw_acc), .busy(busy));

    reg [15:0] input_width = 4, input_height = 4, input_channels = 2;
    reg [15:0] output_x = 0, output_y = 0, input_channel = 0;
    reg [7:0] stride = 2, pad_left = 1, pad_top = 1;
    reg [7:0] kernel_x = 0, kernel_y = 0;
    wire address_valid;
    wire [31:0] byte_address;
    v8_window_addr addr(.input_width(input_width), .input_height(input_height),
        .input_channels(input_channels), .output_x(output_x), .output_y(output_y),
        .stride(stride), .pad_left(pad_left), .pad_top(pad_top),
        .kernel_x(kernel_x), .kernel_y(kernel_y), .input_channel(input_channel),
        .address_valid(address_valid), .byte_address(byte_address));

    task check_addr;
        input [15:0] oy, ox, ic;
        input [7:0] ky, kx;
        input expected_valid;
        input [31:0] expected_addr;
        begin
            output_y=oy; output_x=ox; input_channel=ic;
            kernel_y=ky; kernel_x=kx;
            #1;
            if (address_valid !== expected_valid ||
                (expected_valid && byte_address !== expected_addr))
                $fatal(1, "address mismatch oy=%0d ox=%0d ic=%0d ky=%0d kx=%0d got=%0d/%0d expected=%0d/%0d",
                    oy,ox,ic,ky,kx,address_valid,byte_address,expected_valid,expected_addr);
        end
    endtask

    task begin_dot;
        input [31:0] taps;
        input signed [31:0] initial_bias;
        begin
            @(negedge clk); start=1; tap_count=taps; bias=initial_bias;
            @(negedge clk); start=0;
        end
    endtask

    task send_tap;
        input signed [7:0] a, w;
        begin
            @(negedge clk); tap_valid=1; activation=a; weight=w;
            while (!tap_ready) @(negedge clk);
            @(negedge clk); tap_valid=0;
        end
    endtask

    task send_three_contiguous;
        input signed [7:0] a0, w0, a1, w1, a2, w2;
        begin
            @(negedge clk); tap_valid=1; activation=a0; weight=w0;
            if (!tap_ready) $fatal(1,"first tap not ready");
            @(negedge clk); activation=a1; weight=w1;
            if (!tap_ready) $fatal(1,"second contiguous tap not ready");
            @(negedge clk); activation=a2; weight=w2;
            if (!tap_ready) $fatal(1,"third contiguous tap not ready");
            @(negedge clk); tap_valid=0;
        end
    endtask

    task send_zero_taps;
        input integer count;
        integer i;
        begin
            for (i=0; i<count; i=i+1) begin
                @(negedge clk); tap_valid=1; activation=0; weight=0;
                if (!tap_ready) $fatal(1,"tap %0d/%0d not ready",i,count);
            end
            @(negedge clk); tap_valid=0;
        end
    endtask

    task wait_result;
        integer cycles;
        begin
            cycles=0;
            while (!out_valid && cycles<32) begin
                @(negedge clk); cycles=cycles+1;
            end
            if (!out_valid) $fatal(1,"MAC result timeout");
        end
    endtask

    initial begin
        #1;
        check_addr(0,0,0,0,0,0,0); // top-left SAME padding
        check_addr(0,0,0,1,1,1,0);
        check_addr(0,0,1,1,1,1,16); // second NCHW channel
        check_addr(1,1,1,2,2,1,31); // lower-right of second channel
        check_addr(1,1,1,0,0,1,21);
        check_addr(2,2,0,0,0,1,15); // source 3,3 at stride 2
        check_addr(2,2,0,2,2,0,0); // outside
        @(negedge clk); rst_n=1;
        begin_dot(3, -10);
        if (!tap_ready) $fatal(1,"not ready");
        send_three_contiguous(-128,127, 0,-128, 127,-128); // total -32522
        wait_result;
        if (!out_valid || out_overflow || raw_acc !== -32522 || busy)
            $fatal(1,"signed MAC result %0d valid %b busy %b",raw_acc,out_valid,busy);

        // An intermediate INT32 overflow must be allowed to cancel before final saturation.
        begin_dot(2, 32'sh7fffffff);
        send_tap(127,127);
        send_tap(-127,127);
        wait_result;
        if (!out_valid || out_overflow || raw_acc !== 32'sh7fffffff)
            $fatal(1,"overflow cancellation failed %0d",raw_acc);

        begin_dot(1, 32'sh7fffffff);
        send_tap(127,127);
        wait_result;
        if (!out_valid || !out_overflow || raw_acc !== 32'sh7fffffff)
            $fatal(1,"positive saturation failed %0d",raw_acc);

        begin_dot(1, 32'sh80000000);
        send_tap(-128,127);
        wait_result;
        if (!out_valid || !out_overflow || raw_acc !== 32'sh80000000)
            $fatal(1,"negative saturation failed %0d",raw_acc);

        begin_dot(0, -1234567);
        wait_result;
        if (!out_valid || out_overflow || raw_acc !== -1234567 || busy)
            $fatal(1,"zero-tap result failed %0d",raw_acc);

        begin_dot(16383, 0);
        send_zero_taps(16383);
        if (tap_ready) $fatal(1,"accepted more than configured tap count");
        wait_result;
        if (!out_valid || out_overflow || raw_acc !== 0 || busy)
            $fatal(1,"maximum tap count failed");

        begin_dot(16384, 17);
        wait_result;
        if (!out_valid || !out_overflow || raw_acc !== 17 || busy || tap_ready)
            $fatal(1,"over-limit tap count was not rejected");

        $display("PASS v8 conv MAC and stride/padding NCHW address vectors");
        $finish;
    end
endmodule
