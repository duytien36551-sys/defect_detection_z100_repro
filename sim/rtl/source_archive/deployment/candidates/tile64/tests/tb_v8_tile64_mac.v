`timescale 1ns/1ps

module tb_v8_tile64_mac;
    localparam integer MAX_TAPS = 4091;
    reg clk = 0;
    reg rst_n = 0;
    reg cfg_weight_we = 0;
    reg [11:0] cfg_weight_addr = 0;
    reg [511:0] cfg_weights = 0;
    reg cfg_bias_we = 0;
    reg [2047:0] cfg_biases = 0;
    wire cfg_ready;
    reg run = 0;
    reg [12:0] tap_count = 0;
    reg [6:0] lane_count = 0;
    reg act_valid = 0;
    reg signed [7:0] act_data = 0;
    wire act_ready;
    wire out_valid;
    wire [6:0] out_lane_count;
    wire [2047:0] out_raw;
    wire [63:0] out_overflow;
    wire error;
    wire busy;
    wire ref_cfg_ready, ref_act_ready, ref_out_valid;
    wire [6:0] ref_out_lane_count;
    wire [2047:0] ref_out_raw;
    wire [63:0] ref_out_overflow;
    wire ref_error, ref_busy;

    integer lane_i, tap_i, wait_i, act_v, weight_v;
    reg signed [31:0] bias_ref [0:63];
    reg signed [63:0] sum_ref;
    reg [31:0] raw_ref;
    reg signed [7:0] activation_ref;

    always #5 clk = ~clk;

    v8_tile64_mac #(.MAX_TAPS(MAX_TAPS)) dut (
        .clk(clk), .rst_n(rst_n),
        .cfg_weight_we(cfg_weight_we), .cfg_weight_addr(cfg_weight_addr),
        .cfg_weights(cfg_weights), .cfg_bias_we(cfg_bias_we),
        .cfg_biases(cfg_biases), .cfg_ready(cfg_ready),
        .run(run), .tap_count(tap_count), .lane_count(lane_count),
        .act_valid(act_valid), .act_data(act_data), .act_ready(act_ready),
        .out_valid(out_valid), .out_lane_count(out_lane_count),
        .out_raw(out_raw), .out_overflow(out_overflow),
        .error(error), .busy(busy)
    );

    v8_tile64_mac_reference #(.MAX_TAPS(MAX_TAPS)) reference_dut (
        .clk(clk), .rst_n(rst_n),
        .cfg_weight_we(cfg_weight_we), .cfg_weight_addr(cfg_weight_addr),
        .cfg_weights(cfg_weights), .cfg_bias_we(cfg_bias_we),
        .cfg_biases(cfg_biases), .cfg_ready(ref_cfg_ready),
        .run(run), .tap_count(tap_count), .lane_count(lane_count),
        .act_valid(act_valid), .act_data(act_data), .act_ready(ref_act_ready),
        .out_valid(ref_out_valid), .out_lane_count(ref_out_lane_count),
        .out_raw(ref_out_raw), .out_overflow(ref_out_overflow),
        .error(ref_error), .busy(ref_busy)
    );

    // This reference is a module-name-renamed copy of the frozen MAC from the
    // failed post-route snapshot. Compare every visible signal every cycle.
    always @(posedge clk) begin
        #1;
        if (rst_n &&
            {cfg_ready, act_ready, out_valid, out_lane_count, out_raw,
             out_overflow, error, busy} !==
            {ref_cfg_ready, ref_act_ready, ref_out_valid, ref_out_lane_count,
             ref_out_raw, ref_out_overflow, ref_error, ref_busy}) begin
            $display("cycle mismatch optimized valid=%b busy=%b vs ref valid=%b busy=%b",
                out_valid, busy, ref_out_valid, ref_busy);
            $fatal(1, "optimized MAC behavior or out_valid latency differs from reference");
        end
    end

    function integer weight_for;
        input integer tap;
        input integer lane;
        begin weight_for = ((tap * 7 + lane * 3) % 11) - 5; end
    endfunction

    function integer activation_for;
        input integer tap;
        input integer mode;
        begin activation_for = ((tap + mode) % 3) + 1; end
    endfunction

    task fail;
        input [8*120-1:0] message;
        begin $display("FAIL %0s at %0t", message, $time); $fatal(1); end
    endtask

    task load_biases;
        integer k;
        begin
            for (k = 0; k < 64; k = k + 1) begin
                bias_ref[k] = (k % 5) - 2;
                cfg_biases[k*32 +: 32] = bias_ref[k];
            end
            @(negedge clk);
            if (!cfg_ready || !ref_cfg_ready) fail("MAC not ready for bias load");
            cfg_bias_we = 1;
            @(negedge clk); cfg_bias_we = 0;
        end
    endtask

    task load_weights;
        integer t, l;
        begin
            for (t = 0; t < MAX_TAPS; t = t + 1) begin
                @(negedge clk);
                cfg_weight_addr = t[11:0];
            for (l = 0; l < 64; l = l + 1)
                    cfg_weights[l*8 +: 8] = weight_for(t, l);
                cfg_weight_we = 1;
            end
            @(negedge clk); cfg_weight_we = 0;
        end
    endtask

    task run_and_check;
        input integer taps;
        input integer lanes;
        input integer mode;
        integer t, l;
        begin
            @(negedge clk);
            if (!cfg_ready || !ref_cfg_ready)
                fail("back-to-back MAC run was not ready on first eligible cycle");
            tap_count = taps;
            lane_count = lanes;
            run = 1;
            @(negedge clk); run = 0;
            if (!busy) fail("valid MAC run did not start");

            for (t = 0; t < taps; t = t + 1) begin
                @(negedge clk);
                act_data = activation_for(t, mode);
                act_valid = 1;
                while (!act_ready) @(negedge clk);
                @(negedge clk); act_valid = 0;
            end

            wait_i = 0;
            while (!out_valid && wait_i < 10) begin
                @(posedge clk); #1; wait_i = wait_i + 1;
            end
            if (!out_valid) fail("MAC result timed out");
            if (out_lane_count !== lanes) fail("reported active lane count differs");
            if (busy) fail("MAC busy remained set after result");

            for (l = 0; l < 64; l = l + 1) begin
                sum_ref = bias_ref[l];
                if (l < lanes)
                    for (t = 0; t < taps; t = t + 1)
                        sum_ref = sum_ref +
                            (activation_for(t, mode) * weight_for(t, l));
                if (l >= lanes) begin
                    raw_ref = 0;
                    if (out_overflow[l] !== 1'b0)
                        fail("inactive lane overflow was nonzero");
                end else if (sum_ref > 64'sh000000007fffffff) begin
                    raw_ref = 32'h7fffffff;
                    if (out_overflow[l] !== 1'b1)
                        fail("positive overflow flag missing");
                end else if (sum_ref < -64'sh0000000080000000) begin
                    raw_ref = 32'h80000000;
                    if (out_overflow[l] !== 1'b1)
                        fail("negative overflow flag missing");
                end else begin
                    raw_ref = sum_ref[31:0];
                    if (out_overflow[l] !== 1'b0)
                        fail("unexpected overflow flag");
                end
                if (out_raw[l*32 +: 32] !== raw_ref) begin
                    $display("lane %0d got %08x expected %08x", l,
                        out_raw[l*32 +: 32], raw_ref);
                    fail("raw output mismatch");
                end
            end
            $display("PASS MAC taps=%0d lanes=%0d", taps, lanes);
        end
    endtask

    task run_contiguous_check;
        input integer taps;
        input integer lanes;
        integer t, l;
        begin
            @(negedge clk);
            if (!cfg_ready || !ref_cfg_ready)
                fail("consecutive MAC run did not become ready");
            tap_count = taps; lane_count = lanes; run = 1;
            @(negedge clk); run = 0;
            for (t = 0; t < taps; t = t + 1) begin
                @(negedge clk);
                act_data = activation_for(t, 4); act_valid = 1;
                while (!act_ready) @(negedge clk);
                @(posedge clk); #1;
            end
            @(negedge clk); act_valid = 0;
            wait_i = 0;
            while (!out_valid && wait_i < 10) begin
                @(posedge clk); #1; wait_i = wait_i + 1;
            end
            if (!out_valid || out_lane_count !== lanes)
                fail("contiguous MAC activation stream did not complete");
            for (l = 0; l < lanes; l = l + 1) begin
                sum_ref = bias_ref[l];
                for (t = 0; t < taps; t = t + 1)
                    sum_ref = sum_ref + activation_for(t, 4) * weight_for(t, l);
                if (out_raw[l*32 +: 32] !== sum_ref[31:0] || out_overflow[l])
                    fail("contiguous activation stream output mismatch");
            end
            $display("PASS MAC contiguous taps=%0d lanes=%0d", taps, lanes);
        end
    endtask

    task reset_midrun_recovery;
        begin
            @(negedge clk); tap_count = 3; lane_count = 64; run = 1;
            @(negedge clk); run = 0;
            @(negedge clk); act_data = 1; act_valid = 1;
            while (!act_ready) @(negedge clk);
            @(posedge clk); #1;
            @(negedge clk); act_valid = 0; rst_n = 0;
            repeat (2) @(negedge clk);
            if (out_valid || busy || ref_out_valid || ref_busy)
                fail("async reset did not clear MAC pipeline state");
            rst_n = 1;
            load_biases;
            run_and_check(1, 17, 1);
            $display("PASS MAC async reset during product pipeline and fresh RUN");
        end
    endtask

    task run_saturation_check;
        input [31:0] bias_bits;
        input [7:0] weight_bits;
        input [31:0] expected_raw;
        integer k;
        begin
            for (k = 0; k < 64; k = k + 1) begin
                bias_ref[k] = bias_bits;
                cfg_biases[k*32 +: 32] = bias_bits;
            end
            @(negedge clk); cfg_bias_we = 1;
            @(negedge clk); cfg_bias_we = 0;
            cfg_weight_addr = 0;
            for (k = 0; k < 64; k = k + 1)
                cfg_weights[k*8 +: 8] = weight_bits;
            @(negedge clk); cfg_weight_we = 1;
            @(negedge clk); cfg_weight_we = 0;

            @(negedge clk); tap_count = 1; lane_count = 64; run = 1;
            @(negedge clk); run = 0;
            @(negedge clk); act_data = 1; act_valid = 1;
            while (!act_ready) @(negedge clk);
            @(negedge clk); act_valid = 0;
            wait_i = 0;
            while (!out_valid && wait_i < 10) begin
                @(posedge clk); #1; wait_i = wait_i + 1;
            end
            if (!out_valid || out_lane_count !== 64)
                fail("saturating MAC run did not complete");
            for (k = 0; k < 64; k = k + 1) begin
                if (out_raw[k*32 +: 32] !== expected_raw ||
                    out_overflow[k] !== 1'b1)
                    fail("INT33-to-INT32 saturation or overflow flag mismatch");
            end
            @(negedge clk);
        end
    endtask

    initial begin
        repeat (4) @(negedge clk);
        rst_n = 1;
        load_biases;
        load_weights;

        // The two partial lane counts exercise distinct, non-byte-aligned tails.
        run_and_check(1, 17, 0);
        run_and_check(1, 33, 1);
        run_and_check(1, 63, 2);
        // The preceding commands are launched on the first eligible cycle;
        // this run keeps act_valid high across every accepted tap.
        run_contiguous_check(9, 64);
        // Read every tap in the maximum-depth weight banks with all 64 lanes.
        run_and_check(MAX_TAPS, 64, 3);

        reset_midrun_recovery;

        run_saturation_check(32'h7fffffff, 8'd1, 32'h7fffffff);
        run_saturation_check(32'h80000000, 8'hff, 32'h80000000);

        @(negedge clk); tap_count = 1; lane_count = 65; run = 1;
        @(negedge clk); run = 0;
        if (busy || !error) fail("lane count 65 was not rejected");
        $display("PASS v8_tile64_mac full depth, 17/33/63 tails, saturation, and invalid lane check");
        $finish;
    end

    initial begin
        #20000000; $fatal(1, "MAC test timeout");
    end
endmodule
