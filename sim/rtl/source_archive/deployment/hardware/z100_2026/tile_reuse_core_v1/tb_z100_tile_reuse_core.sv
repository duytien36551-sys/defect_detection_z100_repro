`timescale 1ns/1ps

module tb_z100_tile_reuse_core;
    localparam integer MAX_TAPS = 4091;
    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;

    reg load_begin = 0;
    wire cfg_weight_ready;
    reg cfg_weight_we = 0;
    reg [11:0] cfg_weight_addr = 0;
    reg [255:0] cfg_weights = 0;
    wire cfg_bias_ready;
    reg cfg_bias_we = 0;
    reg [1023:0] cfg_biases = 0;
    wire act_cfg_ready;
    reg act_cfg_we = 0;
    reg [11:0] act_cfg_addr = 0;
    reg [3:0] act_cfg_site_mask = 0;
    reg [31:0] act_cfg_data = 0;

    reg run_valid = 0;
    wire run_ready;
    reg [12:0] run_tap_count = 0;
    reg [5:0] run_lane_count = 0;
    reg [2:0] run_site_count = 0;
    reg cancel = 0;

    wire out_valid;
    reg out_ready = 0;
    wire [1:0] out_site;
    wire out_last;
    wire [5:0] out_lane_count;
    wire [1023:0] out_data;
    wire [31:0] out_overflow;
    wire busy;
    wire error;

    z100_tile_reuse_core #(.MAX_TAPS(MAX_TAPS)) dut (
        .clk(clk), .rst_n(rst_n),
        .load_begin(load_begin),
        .cfg_weight_ready(cfg_weight_ready),
        .cfg_weight_we(cfg_weight_we), .cfg_weight_addr(cfg_weight_addr), .cfg_weights(cfg_weights),
        .cfg_bias_ready(cfg_bias_ready), .cfg_bias_we(cfg_bias_we), .cfg_biases(cfg_biases),
        .act_cfg_ready(act_cfg_ready), .act_cfg_we(act_cfg_we), .act_cfg_addr(act_cfg_addr),
        .act_cfg_site_mask(act_cfg_site_mask), .act_cfg_data(act_cfg_data),
        .run_valid(run_valid), .run_ready(run_ready), .run_tap_count(run_tap_count),
        .run_lane_count(run_lane_count), .run_site_count(run_site_count), .cancel(cancel),
        .out_valid(out_valid), .out_ready(out_ready), .out_site(out_site), .out_last(out_last),
        .out_lane_count(out_lane_count), .out_data(out_data), .out_overflow(out_overflow),
        .busy(busy), .error(error)
    );

    reg signed [7:0] activations [0:3][0:MAX_TAPS-1];
    reg signed [7:0] weights [0:63][0:MAX_TAPS-1];
    reg signed [31:0] biases [0:63];
    reg [31:0] expected_value [0:63][0:3];
    reg expected_overflow [0:63][0:3];
    reg [31:0] reconstructed [0:63][0:3];

    reg [31:0] rng_state = 32'h51f15eed;
    integer cycle_counter = 0;
    integer group_issue_counter = 0;
    integer last_issue_cycle = 0;
    integer load_cycle_total = 0;
    integer job_count = 0;
    integer failed = 0;

    always @(posedge clk) begin
        cycle_counter = cycle_counter + 1;
        if (dut.issue_group) begin
            group_issue_counter = group_issue_counter + 1;
            last_issue_cycle = cycle_counter;
        end
    end

    function [31:0] next_random;
        reg [31:0] x;
        begin
            x = rng_state;
            x = x ^ (x << 13);
            x = x ^ (x >> 17);
            x = x ^ (x << 5);
            rng_state = x;
            next_random = x;
        end
    endfunction

    function [31:0] clamp64;
        input signed [63:0] value;
        begin
            if (value > 64'sh000000007fffffff)
                clamp64 = 32'h7fffffff;
            else if (value < -64'sh0000000080000000)
                clamp64 = 32'h80000000;
            else
                clamp64 = value[31:0];
        end
    endfunction

    task fail;
        input [8*240-1:0] message;
        begin
            $display("FAIL: %0s at cycle %0d", message, cycle_counter);
            failed = failed + 1;
            $finish(1);
        end
    endtask

    task pulse_load_begin;
        begin
            @(negedge clk);
            load_begin = 1;
            @(posedge clk);
            load_cycle_total = load_cycle_total + 1;
            @(negedge clk);
            load_begin = 0;
        end
    endtask

    task prepare_case;
        input integer taps;
        input integer sites;
        input integer mode;
        integer t, s, ch;
        reg [31:0] rv;
        begin
            for (s = 0; s < 4; s = s + 1) begin
                for (t = 0; t < taps; t = t + 1) begin
                    rv = next_random();
                    if (s >= sites)
                        activations[s][t] = 0;
                    else if (mode == 1)
                        activations[s][t] = 8'sd127;
                    else if (mode == 2)
                        activations[s][t] = -8'sd128;
                    else if ((mode == 3) && (t < (taps / 2)))
                        activations[s][t] = 8'sd127;
                    else if (mode == 3)
                        activations[s][t] = -8'sd127;
                    else if ((mode == 4) && (t < (taps / 2)))
                        activations[s][t] = -8'sd128;
                    else if (mode == 4)
                        activations[s][t] = 8'sd127;
                    else
                        activations[s][t] = rv[7:0];
                end
            end

            for (ch = 0; ch < 64; ch = ch + 1) begin
                rv = next_random();
                if (mode == 1)
                    biases[ch] = 32'sh7fffff00;
                else if (mode == 2)
                    biases[ch] = -32'sh7fffff00;
                else if (mode == 3)
                    biases[ch] = 32'sh7fffff00;
                else if (mode == 4)
                    biases[ch] = -32'sh7fffff00;
                else
                    biases[ch] = rv;

                for (t = 0; t < taps; t = t + 1) begin
                    rv = next_random();
                    if ((mode == 1) || (mode == 2) || (mode == 3) || (mode == 4))
                        weights[ch][t] = 8'sd127;
                    else if ((t % 11) == 0)
                        weights[ch][t] = -8'sd128;
                    else
                        weights[ch][t] = rv[7:0];
                end
            end

            for (ch = 0; ch < 64; ch = ch + 1) begin
                for (s = 0; s < 4; s = s + 1) begin
                    if (s >= sites) begin
                        expected_value[ch][s] = 0;
                        expected_overflow[ch][s] = 0;
                    end else begin
                        begin : scalar_dot
                            reg signed [63:0] acc;
                            reg signed [15:0] product;
                            acc = biases[ch];
                            for (t = 0; t < taps; t = t + 1) begin
                                product =
                                    $signed({{8{activations[s][t][7]}}, activations[s][t]}) *
                                    $signed({{8{weights[ch][t][7]}}, weights[ch][t]});
                                acc = acc + product;
                            end
                            expected_value[ch][s] = clamp64(acc);
                            expected_overflow[ch][s] =
                                (acc > 64'sh000000007fffffff) ||
                                (acc < -64'sh0000000080000000);
                        end
                    end
                    reconstructed[ch][s] = 32'hdeadbeef;
                end
            end
        end
    endtask

    task load_block;
        input integer taps;
        input integer sites;
        input integer block_index;
        integer t, s, lane;
        reg [31:0] packed_act;
        reg [255:0] packed_weights;
        reg [1023:0] packed_biases;
        begin
            pulse_load_begin();
            packed_biases = 0;
            for (lane = 0; lane < 32; lane = lane + 1)
                packed_biases[(lane * 32) +: 32] = biases[(block_index * 32) + lane];
            for (t = 0; t < taps; t = t + 1) begin
                packed_act = 0;
                packed_weights = 0;
                for (s = 0; s < 4; s = s + 1)
                    packed_act[(s * 8) +: 8] = activations[s][t];
                for (lane = 0; lane < 32; lane = lane + 1)
                    packed_weights[(lane * 8) +: 8] = weights[(block_index * 32) + lane][t];

                @(negedge clk);
                if (!cfg_weight_ready || !act_cfg_ready || !cfg_bias_ready)
                    fail("preload ready deasserted while idle");
                cfg_weight_we = 1;
                cfg_weight_addr = t;
                cfg_weights = packed_weights;
                act_cfg_we = 1;
                act_cfg_addr = t;
                act_cfg_site_mask = (1 << sites) - 1;
                act_cfg_data = packed_act;
                cfg_bias_we = (t == 0);
                cfg_biases = packed_biases;
                @(posedge clk);
                load_cycle_total = load_cycle_total + 1;
                @(negedge clk);
                if (error)
                    fail("valid preload raised error");
                cfg_weight_we = 0;
                act_cfg_we = 0;
                cfg_bias_we = 0;
            end
        end
    endtask

    task check_current_output;
        input integer block_index;
        input integer expected_site;
        integer lane;
        integer channel;
        begin
            if (!out_valid)
                fail("output valid dropped before site readback");
            if (out_site !== expected_site[1:0])
                fail("output site order mismatch");
            if (out_lane_count !== run_lane_count)
                fail("output lane count mismatch");
            if (out_last !== (expected_site == run_site_count - 1))
                fail("output last marker mismatch");
            for (lane = 0; lane < 32; lane = lane + 1) begin
                channel = block_index * 32 + lane;
                if (out_data[(lane * 32) +: 32] !== expected_value[channel][expected_site])
                    fail("scalar-reference data mismatch");
                if (out_overflow[lane] !== expected_overflow[channel][expected_site])
                    fail("scalar-reference overflow mismatch");
                reconstructed[channel][expected_site] = out_data[(lane * 32) +: 32];
            end
        end
    endtask

    task run_block;
        input integer taps;
        input integer sites;
        input integer block_index;
        input integer lanes;
        input integer repetition;
        integer start_cycle, first_valid_cycle, last_handshake_cycle;
        integer first_issue_cycle;
        integer issue_start, issues, start_latency, pipe_cycles;
        integer handshakes, stall_left, total_stalls, watchdog;
        integer expected_site;
        reg [1023:0] held_data;
        reg [31:0] held_overflow;
        reg [1:0] held_site;
        reg [5:0] held_lane_count;
        begin
            run_tap_count = taps;
            run_lane_count = lanes;
            run_site_count = sites;
            run_valid = 0;
            out_ready = 0;
            @(negedge clk);
            if (!run_ready)
                fail("run not ready after preload");
            issue_start = group_issue_counter;
            run_valid = 1;
            @(posedge clk);
            @(negedge clk);
            start_cycle = cycle_counter;
            if (!busy)
                fail("accepted run did not enter busy state");
            run_valid = 0;

            watchdog = 0;
            while (!out_valid && watchdog < taps + 30) begin
                @(negedge clk);
                watchdog = watchdog + 1;
                if (error)
                    fail("valid run raised error");
            end
            if (!out_valid)
                fail("timeout waiting for result buffer");
            first_valid_cycle = cycle_counter;
            issues = group_issue_counter - issue_start;
            first_issue_cycle = last_issue_cycle - (issues - 1);
            start_latency = first_issue_cycle - start_cycle;
            pipe_cycles = (first_valid_cycle - start_cycle) - issues;
            expected_site = 0;
            handshakes = 0;
            total_stalls = 0;
            stall_left = 2 + (expected_site % 3);
            watchdog = 0;
            while (handshakes < sites && watchdog < (sites * 20 + 40)) begin
                if (!out_valid)
                    fail("result buffer valid lost while draining");
                check_current_output(block_index, expected_site);
                held_data = out_data;
                held_overflow = out_overflow;
                held_site = out_site;
                held_lane_count = out_lane_count;
                if (stall_left > 0) begin
                    out_ready = 0;
                    stall_left = stall_left - 1;
                    total_stalls = total_stalls + 1;
                end else begin
                    out_ready = 1;
                end
                @(posedge clk);
                if (out_ready) begin
                    handshakes = handshakes + 1;
                    last_handshake_cycle = cycle_counter;
                    expected_site = expected_site + 1;
                    stall_left = 2 + (expected_site % 3);
                end else begin
                    if ((out_data !== held_data) || (out_overflow !== held_overflow) ||
                        (out_site !== held_site) || (out_lane_count !== held_lane_count))
                        fail("backpressured result changed under stall");
                end
                @(negedge clk);
                out_ready = 0;
                watchdog = watchdog + 1;
            end
            if (handshakes != sites)
                fail("readback handshake count mismatch");
            if (out_valid || busy)
                fail("core failed to return idle after final readback");
            job_count = job_count + 1;
            $display("METRIC case=%0d block=%0d taps=%0d groups=%0d sites=%0d lanes=%0d start_to_issue=%0d issue_cycles=%0d pipeline_flush=%0d start_to_result=%0d drain_cycles=%0d readback_handshakes=%0d stall_cycles=%0d total_job_cycles=%0d",
                job_count, block_index, taps, (taps + 3) / 4, sites, lanes,
                start_latency, issues, pipe_cycles, first_valid_cycle - start_cycle,
                last_handshake_cycle - first_valid_cycle + 1, handshakes, total_stalls,
                last_handshake_cycle - start_cycle);
        end
    endtask

    task run_case;
        input integer taps;
        input integer sites;
        input integer mode;
        input integer lanes0;
        input integer lanes1;
        integer block_index;
        integer ch, s;
        begin
            prepare_case(taps, sites, mode);
            for (ch = 0; ch < 64; ch = ch + 1) begin
                if ((ch < 32) && ((ch % 32) >= lanes0)) begin
                    for (s = 0; s < 4; s = s + 1) begin
                        expected_value[ch][s] = 0;
                        expected_overflow[ch][s] = 0;
                    end
                end else if ((ch >= 32) && ((ch % 32) >= lanes1)) begin
                    for (s = 0; s < 4; s = s + 1) begin
                        expected_value[ch][s] = 0;
                        expected_overflow[ch][s] = 0;
                    end
                end
            end
            for (block_index = 0; block_index < 2; block_index = block_index + 1) begin
                load_block(taps, sites, block_index);
                if (block_index == 0)
                    run_block(taps, sites, block_index, lanes0, 0);
                else
                    run_block(taps, sites, block_index, lanes1, 0);
                // Same preload, next job: validates consecutive operation
                // without a new load epoch or a second buffer.
                if (block_index == 0)
                    run_block(taps, sites, block_index, lanes0, 1);
                else
                    run_block(taps, sites, block_index, lanes1, 1);
            end
            for (ch = 0; ch < 64; ch = ch + 1) begin
                for (s = 0; s < sites; s = s + 1) begin
                    if (reconstructed[ch][s] !== expected_value[ch][s])
                        fail("two-block adapter reconstruction mismatch");
                end
            end
            $display("CASE_PASS taps=%0d sites=%0d mode=%0d lanes0=%0d lanes1=%0d", taps, sites, mode, lanes0, lanes1);
        end
    endtask

    task expect_invalid_unloaded_run;
        begin
            @(negedge clk);
            run_tap_count = 1;
            run_lane_count = 1;
            run_site_count = 1;
            run_valid = 1;
            @(posedge clk);
            @(negedge clk);
            run_valid = 0;
            if (busy)
                fail("run consumed unloaded scratchpad data");
            if (!error)
                fail("unloaded run was not rejected");
            @(posedge clk);
            @(negedge clk);
        end
    endtask

    task abort_mid_pipeline;
        input integer use_reset;
        input integer delay_edges;
        integer before_issues;
        integer watchdog;
        begin
            prepare_case(5, 4, 0);
            load_block(5, 4, 0);
            run_tap_count = 5;
            run_lane_count = 32;
            run_site_count = 4;
            @(negedge clk);
            before_issues = group_issue_counter;
            run_valid = 1;
            @(posedge clk);
            @(negedge clk);
            run_valid = 0;
            watchdog = 0;
            while ((group_issue_counter == before_issues) && watchdog < 10) begin
                @(negedge clk);
                watchdog = watchdog + 1;
            end
            if (group_issue_counter == before_issues)
                fail("abort test did not reach compute pipeline");
            repeat (delay_edges) @(negedge clk);
            if (use_reset) begin
                rst_n = 0;
                @(posedge clk);
                @(negedge clk);
                rst_n = 1;
            end else begin
                cancel = 1;
                @(posedge clk);
                @(negedge clk);
                cancel = 0;
            end
            if (busy || out_valid)
                fail("reset/cancel left a result or busy state");
            repeat (8) begin
                @(posedge clk);
                if (out_valid)
                    fail("stale result escaped after reset/cancel");
            end
            $display("ABORT_PASS kind=%0d issue_count=%0d", use_reset, group_issue_counter - before_issues);
        end
    endtask

    initial begin : test_main
        integer t;
        rst_n = 0;
        repeat (3) @(posedge clk);
        @(negedge clk);
        rst_n = 1;
        expect_invalid_unloaded_run();

        // Random signed inputs, one/three/four/five taps, partial channels and
        // one/three/four sites exercise all residue and tail masks.
        run_case(1, 4, 0, 32, 32);
        run_case(3, 3, 0, 31, 7);
        run_case(4, 1, 0, 1, 1);
        run_case(5, 4, 3, 29, 32);
        run_case(5, 4, 4, 32, 17);

        // Positive and negative final saturation plus cancellation after a
        // prefix that would overflow signed32 if intermediate clipping existed.
        run_case(4091, 4, 1, 32, 32);
        run_case(4091, 3, 2, 30, 31);
        run_case(5, 4, 3, 32, 32);

        for(t=0;t<4;t=t+1) abort_mid_pipeline(0,t);
        run_case(5, 1, 0, 32, 32);
        for(t=0;t<4;t=t+1) abort_mid_pipeline(1,t);
        run_case(3, 4, 0, 32, 32);

        $display("SIM_PASS jobs=%0d preload_cycles=%0d sim_cycles=%0d", job_count, load_cycle_total, cycle_counter);
        $finish;
    end

    initial begin
        #30000000;
        $display("FAIL: global simulation timeout");
        $finish(1);
    end
endmodule
