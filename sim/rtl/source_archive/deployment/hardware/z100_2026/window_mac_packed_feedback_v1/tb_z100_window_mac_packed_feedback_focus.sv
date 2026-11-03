`timescale 1ns/1ps
`default_nettype none
module tb_z100_window_mac_packed_feedback_focus;
    reg clk=0;
    always #5 clk=~clk;
    wire done12;
    z100_window_mac_scale_case #(.SITES(12)) case12(.clk(clk), .done(done12));
    initial begin
        wait(done12);
        #1;
        $display("WINDOW_MAC_FEEDBACK_FOCUS_PASS sites12_jobs=%0d sites12_words=%0d sites12_metadata=%0d sites12_stalls=%0d sites12_bubbles=%0d sites12_stream_errors=%0d sites12_config_errors=%0d sites12_run_errors=%0d sites12_cross=%0d sites12_saturation=%0d sites12_cancel_offsets=%0d sites12_reset_offsets=%0d sites12_real_windows=%0d sites12_site_tail_mask=%0d sites12_lane_tail_mask=%0d sites12_group_mask=%0d max_groups=%0d replays=%0d",
                 case12.jobs,case12.word_checks,case12.metadata_checks,case12.stalls,
                 case12.bubbles,case12.stream_errors,case12.config_errors,case12.run_errors,
                 case12.cross_checks,case12.saturation_checks,case12.cancel_offsets,
                 case12.reset_offsets,case12.real_window_checks,case12.site_tail_mask,
                 case12.lane_tail_mask,case12.group_mask,case12.max_groups_seen,case12.replay_pairs);
        $finish;
    end
    initial begin #100000000; $fatal(1,"Focused SITES12 watchdog"); end
endmodule

module z100_window_mac_scale_case #(parameter integer SITES = 8) (
    input wire clk,
    output reg done = 0
);
    localparam signed [63:0] I32_MAX = 64'sd2147483647;
    localparam signed [63:0] I32_MIN = -64'sd2147483648;
    localparam integer TAIL_COUNT = (SITES == 8) ? 5 : 7;
    integer site_tails [0:6];
    integer lane_tails [0:3];
    integer group_sizes [0:4];

    reg rst_n = 0;
    reg cancel = 0;
    reg cfg_begin = 0;
    wire cfg_begin_ready;
    reg [31:0] cfg_epoch = 0;
    reg [10:0] cfg_groups = 0;
    reg cfg_weight_valid = 0;
    wire cfg_weight_ready;
    reg [1023:0] cfg_weights = 0;
    reg cfg_bias_valid = 0;
    wire cfg_bias_ready;
    reg [1023:0] cfg_bias = 0;
    reg cfg_commit = 0;
    wire cfg_commit_ready;
    wire weights_valid;
    wire [31:0] weights_epoch;
    wire error_valid;
    wire [2:0] error_code;
    reg run_valid = 0;
    wire run_ready;
    reg [31:0] run_epoch = 0;
    reg [31:0] run_token = 0;
    reg [5:0] run_lanes = 0;
    reg [3:0] run_sites = 0;
    reg act_valid = 0;
    wire act_ready;
    reg [31:0] act_token = 0;
    reg act_last = 0;
    reg [4*SITES*8-1:0] act_data = 0;
    wire out_valid;
    reg out_ready = 0;
    wire [31:0] out_token;
    wire [3:0] out_site;
    wire out_last;
    wire [5:0] out_lanes;
    wire [1023:0] out_data;
    wire [31:0] out_overflow;

    reg signed [7:0] weight [0:1023][0:3][0:31];
    reg signed [7:0] activation [0:1023][0:3][0:SITES-1];
    reg signed [31:0] bias [0:31];
    longint signed expected_sum [0:SITES-1][0:31];

    reg [7:0] real_weight_bytes [0:1151];
    reg [31:0] real_bias_words [0:31];
    reg [7:0] real_activation_bytes [0:431];
    reg [31:0] real_expected_words [0:383];

    integer jobs = 0;
    integer word_checks = 0;
    integer metadata_checks = 0;
    integer overflow_checks = 0;
    integer stalls = 0;
    integer bubbles = 0;
    integer stream_errors = 0;
    integer config_errors = 0;
    integer run_errors = 0;
    integer cross_checks = 0;
    integer saturation_checks = 0;
    integer cancel_offsets = 0;
    integer reset_offsets = 0;
    integer real_window_checks = 0;
    integer replay_pairs = 0;
    integer max_groups_seen = 0;
    integer site_tail_mask = 0;
    integer lane_tail_mask = 0;
    integer group_mask = 0;

    reg [1023:0] held_data;
    reg [31:0] held_overflow;
    reg [31:0] held_token;
    reg [3:0] held_site;
    reg [5:0] held_lanes;
    reg held_last;

    z100_window_mac #(.SITES(SITES)) dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(cfg_begin_ready),
        .cfg_epoch(cfg_epoch), .cfg_groups(cfg_groups),
        .cfg_weight_valid(cfg_weight_valid), .cfg_weight_ready(cfg_weight_ready),
        .cfg_weights(cfg_weights), .cfg_bias_valid(cfg_bias_valid),
        .cfg_bias_ready(cfg_bias_ready), .cfg_bias(cfg_bias),
        .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .weights_valid(weights_valid), .weights_epoch(weights_epoch),
        .error_valid(error_valid), .error_code(error_code),
        .run_valid(run_valid), .run_ready(run_ready), .run_epoch(run_epoch),
        .run_token(run_token), .run_lanes(run_lanes), .run_sites(run_sites),
        .act_valid(act_valid), .act_ready(act_ready), .act_token(act_token),
        .act_last(act_last), .act_data(act_data),
        .out_valid(out_valid), .out_ready(out_ready), .out_token(out_token),
        .out_site(out_site), .out_last(out_last), .out_lanes(out_lanes),
        .out_data(out_data), .out_overflow(out_overflow)
    );

    task automatic tick;
        begin @(posedge clk); #1; end
    endtask

    task automatic at_negedge;
        begin @(negedge clk); #1; end
    endtask

    task automatic expect_error(input integer code);
        begin
            if (!error_valid || error_code != code)
                $fatal(1, "SITES=%0d expected error %0d got valid=%0d code=%0d",
                       SITES, code, error_valid, error_code);
        end
    endtask

    task automatic make_random_weights(input integer count, input integer seed);
        integer g, t, lane;
        begin
            for (lane = 0; lane < 32; lane = lane + 1)
                bias[lane] = (lane % 2 == 0) ? (lane * 731 - 15000) : (9000 - lane * 541);
            for (g = 0; g < count; g = g + 1)
                for (t = 0; t < 4; t = t + 1)
                    for (lane = 0; lane < 32; lane = lane + 1)
                        weight[g][t][lane] = ((seed * 13 + g * 17 + t * 91 + lane * 23) % 256) - 128;
        end
    endtask

    task automatic make_random_activations(input integer count, input integer seed);
        integer g, t, s;
        begin
            for (g = 0; g < count; g = g + 1)
                for (t = 0; t < 4; t = t + 1)
                    for (s = 0; s < SITES; s = s + 1)
                        activation[g][t][s] = ((seed * 29 + g * 71 + t * 11 + s * 47) % 256) - 128;
        end
    endtask

    task automatic load_configuration(input integer epoch, input integer count);
        integer g, t, lane;
        begin
            at_negedge();
            if (!cfg_begin_ready) $fatal(1, "SITES=%0d configuration did not start", SITES);
            cfg_epoch = epoch;
            cfg_groups = count;
            cfg_begin = 1;
            tick();
            if (weights_valid || error_valid) $fatal(1, "SITES=%0d old weights/error at load start", SITES);
            at_negedge(); cfg_begin = 0; #1;
            for (g = 0; g < count; g = g + 1) begin
                if (!cfg_weight_ready) $fatal(1, "SITES=%0d weight slot blocked at group %0d", SITES, g);
                for (t = 0; t < 4; t = t + 1)
                    for (lane = 0; lane < 32; lane = lane + 1)
                        cfg_weights[(t * 32 + lane) * 8 +: 8] = weight[g][t][lane];
                cfg_weight_valid = 1;
                tick();
                if (error_valid) $fatal(1, "SITES=%0d valid weight rejected", SITES);
                at_negedge(); cfg_weight_valid = 0;
            end
            for (lane = 0; lane < 32; lane = lane + 1)
                cfg_bias[lane * 32 +: 32] = bias[lane];
            cfg_bias_valid = 1;
            tick();
            if (error_valid) $fatal(1, "SITES=%0d valid bias rejected", SITES);
            at_negedge(); cfg_bias_valid = 0; cfg_commit = 1;
            tick();
            if (!weights_valid || weights_epoch != epoch || error_valid)
                $fatal(1, "SITES=%0d configuration commit failed", SITES);
            if (count > max_groups_seen) max_groups_seen = count;
            at_negedge(); cfg_commit = 0;
        end
    endtask

    task automatic invalid_configuration_tests;
        integer t, lane;
        begin
            at_negedge();
            cfg_epoch = 0; cfg_groups = 1; cfg_begin = 1; tick(); expect_error(1); config_errors = config_errors + 1;
            at_negedge(); cfg_begin = 0;
            cfg_epoch = 71; cfg_groups = 0; cfg_begin = 1; tick(); expect_error(1); config_errors = config_errors + 1;
            at_negedge(); cfg_begin = 0;
            cfg_epoch = 71; cfg_groups = 1025; cfg_begin = 1; tick(); expect_error(1); config_errors = config_errors + 1;
            at_negedge(); cfg_begin = 0;
            cfg_epoch = 71; cfg_groups = 2; cfg_begin = 1; tick();
            at_negedge(); cfg_begin = 0; cfg_commit = 1; tick(); expect_error(2); config_errors = config_errors + 1;
            at_negedge(); cfg_commit = 0;
            cfg_epoch = 71; cfg_groups = 1; cfg_begin = 1; tick();
            at_negedge(); cfg_begin = 0;
            for (t = 0; t < 4; t = t + 1)
                for (lane = 0; lane < 32; lane = lane + 1)
                    cfg_weights[(t * 32 + lane) * 8 +: 8] = 0;
            cfg_weight_valid = 1; tick(); at_negedge();
            cfg_weight_valid = 1; tick(); expect_error(3); config_errors = config_errors + 1;
            at_negedge(); cfg_weight_valid = 0;
            cfg_epoch = 71; cfg_groups = 1; cfg_begin = 1; tick();
            at_negedge(); cfg_begin = 0; cfg_bias = 0; cfg_bias_valid = 1; tick();
            at_negedge(); cfg_bias_valid = 1; tick(); expect_error(3); config_errors = config_errors + 1;
            at_negedge(); cfg_bias_valid = 0;
            if (!cfg_begin_ready || weights_valid) $fatal(1, "SITES=%0d invalid configuration recovery failed", SITES);
        end
    endtask

    task automatic start_run(input integer epoch, input integer id,
                             input integer lanes, input integer sites);
        begin
            #1;
            if (!run_ready) $fatal(1, "SITES=%0d run not ready", SITES);
            run_epoch = epoch; run_token = id; run_lanes = lanes; run_sites = sites;
            run_valid = 1; tick();
            if (error_valid || !act_ready) $fatal(1, "SITES=%0d run was rejected", SITES);
            run_valid = 0;
        end
    endtask

    task automatic probe_inflight_reload_block;
        begin
            at_negedge();
            cfg_epoch = weights_epoch + 1; cfg_groups = 1; cfg_begin = 1;
            #1;
            if (cfg_begin_ready || run_ready || !act_ready)
                $fatal(1, "SITES=%0d in-flight configuration/run admission was not blocked", SITES);
            tick();
            at_negedge(); cfg_begin = 0;
            if (error_valid) $fatal(1, "SITES=%0d blocked reload changed error state", SITES);
        end
    endtask

    task automatic send_group(input integer g, input integer count,
                              input integer id, input integer bubble_count,
                              input integer token_override, input integer last_override,
                              input integer expected_error);
        integer t, s, token_value, last_value, b;
        begin
            act_valid = 0;
            for (b = 0; b < bubble_count; b = b + 1) begin
                at_negedge();
                if (!act_ready) $fatal(1, "SITES=%0d unexpected activation backpressure in bubble", SITES);
                tick(); bubbles = bubbles + 1;
            end
            at_negedge();
            if (!act_ready) $fatal(1, "SITES=%0d activation not ready at group %0d", SITES, g);
            for (t = 0; t < 4; t = t + 1)
                for (s = 0; s < SITES; s = s + 1)
                    act_data[(t * SITES + s) * 8 +: 8] = activation[g][t][s];
            token_value = (token_override < 0) ? id : token_override;
            last_value = (last_override < 0) ? ((g + 1) == count) : last_override;
            act_token = token_value; act_last = last_value; act_valid = 1;
            tick();
            if (expected_error == 0 && error_valid)
                $fatal(1, "SITES=%0d valid activation rejected", SITES);
            if (expected_error != 0) expect_error(expected_error);
            act_valid = 0;
        end
    endtask

    task automatic send_all(input integer count, input integer id, input integer seed);
        integer g, bubble_count;
        begin
            for (g = 0; g < count; g = g + 1) begin
                bubble_count = (((g + seed) % 9) == 0) ? 1 : 0;
                send_group(g, count, id, bubble_count, -1, -1, 0);
            end
        end
    endtask

    task automatic check_results(input integer count, input integer lanes,
                                 input integer sites, input integer id,
                                 input integer kind, input integer real_mode,
                                 input integer replay);
        integer s, lane, g, t, waits, hold_cycles, h;
        longint signed sum, wide_weight, wide_activation, partial;
        reg [31:0] expected;
        reg expected_overflow;
        begin
            for (s = 0; s < sites; s = s + 1)
                for (lane = 0; lane < 32; lane = lane + 1) begin
                    if (lane >= lanes) begin
                        sum = 0;
                    end else if (real_mode != 0) begin
                        sum = $signed(real_expected_words[s * 32 + lane]);
                    end else begin
                        sum = bias[lane];
                        for (g = 0; g < count; g = g + 1) begin
                            partial = 0;
                            for (t = 0; t < 4; t = t + 1) begin
                                wide_weight = weight[g][t][lane];
                                wide_activation = activation[g][t][s];
                                partial = partial + wide_weight * wide_activation;
                            end
                            sum = sum + partial;
                            if (kind == 1 && g == 0 && sum <= I32_MAX)
                                $fatal(1, "SITES=%0d positive transient case did not cross INT32_MAX", SITES);
                            if (kind == 1 && g == count - 1 && (sum > I32_MAX || sum < I32_MIN))
                                $fatal(1, "SITES=%0d positive transient case did not return inside INT32", SITES);
                            if (kind == 2 && g == 0 && sum >= I32_MIN)
                                $fatal(1, "SITES=%0d negative transient case did not cross INT32_MIN", SITES);
                            if (kind == 2 && g == count - 1 && (sum > I32_MAX || sum < I32_MIN))
                                $fatal(1, "SITES=%0d negative transient case did not return inside INT32", SITES);
                        end
                    end
                    expected_sum[s][lane] = sum;
                    if (kind == 1 || kind == 2) cross_checks = cross_checks + 1;
                    if (kind == 3 && sum <= I32_MAX)
                        $fatal(1, "SITES=%0d positive saturation case did not overflow", SITES);
                    if (kind == 4 && sum >= I32_MIN)
                        $fatal(1, "SITES=%0d negative saturation case did not overflow", SITES);
                    if (kind == 3 || kind == 4) saturation_checks = saturation_checks + 1;
                end

            for (s = 0; s < sites; s = s + 1) begin
                waits = 0;
                while (!out_valid) begin
                    tick();
                    waits = waits + 1;
                    if (waits > 16) $fatal(1, "SITES=%0d output timeout", SITES);
                end
                #1;
                if (out_token != id || out_site != s || out_lanes != lanes || out_last != ((s + 1) == sites))
                    $fatal(1, "SITES=%0d output metadata mismatch token=%0d site=%0d lanes=%0d last=%0d",
                           SITES, out_token, out_site, out_lanes, out_last);
                metadata_checks = metadata_checks + 1;
                if (real_mode != 0) real_window_checks = real_window_checks + 1;
                for (lane = 0; lane < 32; lane = lane + 1) begin
                    sum = expected_sum[s][lane];
                    expected_overflow = (sum > I32_MAX || sum < I32_MIN);
                    if (sum > I32_MAX) expected = 32'h7fffffff;
                    else if (sum < I32_MIN) expected = 32'h80000000;
                    else expected = sum[31:0];
                    if (out_data[lane * 32 +: 32] !== expected || out_overflow[lane] !== expected_overflow)
                        $fatal(1, "SITES=%0d numerical mismatch job=%0d site=%0d lane=%0d got=%h expected=%h sum=%0d overflow=%b/%b",
                               SITES, jobs, s, lane, out_data[lane * 32 +: 32], expected, sum,
                               out_overflow[lane], expected_overflow);
                    word_checks = word_checks + 1;
                    overflow_checks = overflow_checks + 1;
                end
                held_data = out_data; held_overflow = out_overflow; held_token = out_token;
                held_site = out_site; held_lanes = out_lanes; held_last = out_last;
                hold_cycles = ((id + s) % 3) + 1;
                for (h = 0; h < hold_cycles; h = h + 1) begin
                    tick();
                    if (!out_valid || out_data !== held_data || out_overflow !== held_overflow ||
                        out_token !== held_token || out_site !== held_site || out_lanes !== held_lanes || out_last !== held_last ||
                        act_ready || run_ready || cfg_begin_ready)
                        $fatal(1, "SITES=%0d stalled output changed or accepted overlapping work", SITES);
                    stalls = stalls + 1;
                end
                at_negedge(); out_ready = 1; tick();
                at_negedge(); out_ready = 0;
            end
            jobs = jobs + 1;
            if (replay != 0) replay_pairs = replay_pairs + 1;
            if (out_valid || !run_ready || !weights_valid || weights_epoch != run_epoch)
                $fatal(1, "SITES=%0d job did not retire with resident weights", SITES);
        end
    endtask

    task automatic reject_run(input integer epoch, input integer id,
                              input integer lanes, input integer sites);
        integer resident_epoch_before;
        begin
            resident_epoch_before = weights_epoch;
            at_negedge();
            if (!run_ready) $fatal(1, "SITES=%0d invalid-run test could not start", SITES);
            run_epoch = epoch; run_token = id; run_lanes = lanes; run_sites = sites; run_valid = 1;
            tick(); expect_error(4); run_errors = run_errors + 1;
            if (!run_ready || !weights_valid || weights_epoch != resident_epoch_before || act_ready)
                $fatal(1, "SITES=%0d invalid run changed resident state: run_ready=%0d weights_valid=%0d weights_epoch=%0d expected_resident_epoch=%0d act_ready=%0d rejected_run_epoch=%0d",
                       SITES, run_ready, weights_valid, weights_epoch,
                       resident_epoch_before, act_ready, epoch);
            at_negedge(); run_valid = 0;
        end
    endtask

    task automatic check_invalid_runs;
        integer epoch;
        begin
            epoch = weights_epoch;
            reject_run(epoch - 1, 1, 1, 1);
            reject_run(epoch, 0, 1, 1);
            reject_run(epoch, 2, 0, 1);
            reject_run(epoch, 3, 33, 1);
            reject_run(epoch, 4, 1, 0);
            reject_run(epoch, 5, 1, SITES + 1);
        end
    endtask

    task automatic check_bad_stream(input integer trial);
        integer id, epoch;
        begin
            epoch = 700 + trial;
            id = 710 + trial;
            make_random_weights(2, 811 + trial);
            make_random_activations(2, 911 + trial);
            load_configuration(epoch, 2);
            start_run(epoch, id, 9, 1);
            if (trial == 0) begin
                send_group(0, 2, id, 0, id + 1, 0, 5);
            end else if (trial == 1) begin
                send_group(0, 2, id, 0, -1, 1, 5);
            end else begin
                send_group(0, 2, id, 0, -1, 0, 0);
                send_group(1, 2, id, 0, -1, 0, 5);
            end
            stream_errors = stream_errors + 1;
            if (weights_valid || act_ready) $fatal(1, "SITES=%0d bad stream retained valid weights", SITES);
            repeat (8) begin
                tick();
                if (out_valid) $fatal(1, "SITES=%0d malformed stream leaked output", SITES);
            end
        end
    endtask

    task automatic check_flush_offset(input integer offset, input integer use_reset);
        integer epoch, id, k;
        begin
            epoch = 800 + offset + use_reset * 10;
            id = 900 + offset + use_reset * 10;
            make_random_weights(1, epoch);
            make_random_activations(1, epoch + 7);
            load_configuration(epoch, 1);
            start_run(epoch, id, 32, 4);
            send_group(0, 1, id, 0, -1, -1, 0);
            for (k = 0; k < offset; k = k + 1) begin
                tick(); at_negedge();
            end
            if (use_reset != 0) rst_n = 0;
            else cancel = 1;
            tick();
            at_negedge(); rst_n = 1; cancel = 0;
            repeat (8) begin
                tick();
                if (out_valid || weights_valid || run_ready || act_ready)
                    $fatal(1, "SITES=%0d stale output/weights after flush offset=%0d reset=%0d", SITES, offset, use_reset);
            end
            if (!cfg_begin_ready) $fatal(1, "SITES=%0d flush did not return to configuration state", SITES);
            if (use_reset != 0) reset_offsets = reset_offsets + 1;
            else cancel_offsets = cancel_offsets + 1;

            // Prove that each cancellation/reset boundary recovers for a new job.
            make_random_weights(1, epoch + 33);
            make_random_activations(1, epoch + 77);
            load_configuration(epoch + 1, 1);
            start_run(epoch + 1, id + 1, 1, 1);
            send_group(0, 1, id + 1, 0, -1, -1, 0);
            check_results(1, 1, 1, id + 1, 0, 0, 0);
        end
    endtask

    task automatic install_real_firstconv;
        integer g, t, lane, s;
        begin
            for (g = 0; g < 9; g = g + 1)
                for (t = 0; t < 4; t = t + 1)
                    for (lane = 0; lane < 32; lane = lane + 1)
                        weight[g][t][lane] = real_weight_bytes[(g * 4 + t) * 32 + lane];
            for (lane = 0; lane < 32; lane = lane + 1)
                bias[lane] = $signed(real_bias_words[lane]);
            for (g = 0; g < 9; g = g + 1)
                for (t = 0; t < 4; t = t + 1)
                    for (s = 0; s < SITES; s = s + 1)
                        activation[g][t][s] = real_activation_bytes[(g * 4 + t) * 12 + s];
        end
    endtask

    task automatic check_directed_arithmetic;
        integer lane, s, g, t, id, epoch;
        begin
            // Positive and negative intermediate excursions must recover before output.
            for (g = 1; g <= 2; g = g + 1) begin
                make_random_weights(2, 1);
                for (lane = 0; lane < 32; lane = lane + 1) begin
                    bias[lane] = (g == 1) ? 32'h7fff3caf : 32'h8000c350;
                    for (t = 0; t < 4; t = t + 1) begin
                        weight[0][t][lane] = (g == 1) ? 127 : -128;
                        weight[1][t][lane] = (g == 1) ? 127 : -128;
                    end
                end
                for (s = 0; s < SITES; s = s + 1)
                    for (t = 0; t < 4; t = t + 1) begin
                        activation[0][t][s] = (g == 1) ? 127 : 127;
                        activation[1][t][s] = 0;
                    end
                for (s = 0; s < SITES; s = s + 1) begin
                    activation[1][0][s] = (g == 1) ? -128 : -127;
                end
                epoch = 950 + g; id = 960 + g;
                load_configuration(epoch, 2); start_run(epoch, id, 32, SITES);
                send_all(2, id, 11);
                check_results(2, 32, SITES, id, g, 0, 0);
            end

            // The final unbounded accumulation saturates to signed INT32 on output.
            for (g = 3; g <= 4; g = g + 1) begin
                for (lane = 0; lane < 32; lane = lane + 1) begin
                    bias[lane] = (g == 3) ? 32'h7fffffff : 32'h80000000;
                    for (t = 0; t < 4; t = t + 1)
                        weight[0][t][lane] = (g == 3) ? 127 : -128;
                end
                for (s = 0; s < SITES; s = s + 1)
                    for (t = 0; t < 4; t = t + 1)
                        activation[0][t][s] = 127;
                epoch = 970 + g; id = 980 + g;
                load_configuration(epoch, 1); start_run(epoch, id, 32, SITES);
                send_all(1, id, 13);
                check_results(1, 32, SITES, id, g, 0, 0);
            end
        end
    endtask

    integer group_index, site_index, replay, lanes_value, sites_value, lane_index;
    integer count, epoch, id, tail_index;
    initial begin
        // Hold the vendor global model through startup before releasing local reset.
        #250;
        $readmemh("fixture/firstconv_weights.hex", real_weight_bytes);
        $readmemh("fixture/firstconv_bias.hex", real_bias_words);
        $readmemh("fixture/firstconv_activations.hex", real_activation_bytes);
        $readmemh("fixture/firstconv_expected.hex", real_expected_words);
        site_tails[0]=1; site_tails[1]=3; site_tails[2]=4; site_tails[3]=7;
        site_tails[4]=8; site_tails[5]=11; site_tails[6]=12;
        lane_tails[0]=1; lane_tails[1]=16; lane_tails[2]=31; lane_tails[3]=32;
        group_sizes[0]=1; group_sizes[1]=9; group_sizes[2]=36;
        group_sizes[3]=576; group_sizes[4]=1024;

        repeat (3) tick();
        at_negedge(); rst_n = 1;
        invalid_configuration_tests();
        make_random_weights(1, 73); load_configuration(73, 1); check_invalid_runs();

        // Five geometry points exercise group-depth boundaries and output tails.
        // The 1024-group configuration is replayed without reloading weights.
        for (group_index = 0; group_index < 5; group_index = group_index + 1) begin
            count = group_sizes[group_index];
            group_mask = group_mask | (1 << group_index);
            epoch = 100 + group_index;
            make_random_weights(count, 1700 + group_index);
            load_configuration(epoch, count);
            case (group_index)
                0: begin sites_value=1;  lanes_value=1;  site_tail_mask=site_tail_mask | 1;  lane_tail_mask=lane_tail_mask | 1; end
                1: begin sites_value=7;  lanes_value=16; site_tail_mask=site_tail_mask | 8;  lane_tail_mask=lane_tail_mask | 2; end
                2: begin sites_value=12; lanes_value=31; site_tail_mask=site_tail_mask | 64; lane_tail_mask=lane_tail_mask | 4; end
                3: begin sites_value=4;  lanes_value=32; site_tail_mask=site_tail_mask | 4;  lane_tail_mask=lane_tail_mask | 8; end
                default: begin sites_value=12; lanes_value=32; site_tail_mask=site_tail_mask | 64; lane_tail_mask=lane_tail_mask | 8; end
            endcase
            for (replay = 0; replay < ((group_index == 4) ? 2 : 1); replay = replay + 1) begin
                id = 2000 + group_index * 10 + replay;
                make_random_activations(count, id + 19);
                start_run(epoch, id, lanes_value, sites_value);
                if (group_index == 0 && replay == 0) probe_inflight_reload_block();
                send_all(count, id, id + 3);
                check_results(count, lanes_value, sites_value, id, 0, 0, replay);
            end
        end

        check_directed_arithmetic();

        // Two traces use independently sourced OIHW, biases, and accepted NCHW input.
        install_real_firstconv();
        load_configuration(990, 9);
        for (replay = 0; replay < 2; replay = replay + 1) begin
            id = 991 + replay;
            start_run(990, id, 16, SITES);
            send_all(9, id, 41);
            check_results(9, 16, SITES, id, 0, 1, replay);
        end

        for (tail_index = 0; tail_index < 3; tail_index = tail_index + 1)
            check_bad_stream(tail_index);
        for (tail_index = 0; tail_index < 5; tail_index = tail_index + 1) begin
            check_flush_offset(tail_index, 0);
            check_flush_offset(tail_index, 1);
        end

        if (jobs != 22 || word_checks != 4160 || word_checks != metadata_checks * 32 ||
            overflow_checks != word_checks || config_errors != 6 || run_errors != 6 ||
            stream_errors != 3 || cross_checks != 2 * SITES * 32 ||
            saturation_checks != 2 * SITES * 32 || cancel_offsets != 5 || reset_offsets != 5 ||
            real_window_checks != 2 * SITES || max_groups_seen != 1024 || bubbles == 0 ||
            stalls == 0 || replay_pairs < 2 || site_tail_mask != 77 || lane_tail_mask != 15 ||
            group_mask != 31)
            $fatal(1, "FOCUS coverage mismatch jobs=%0d words=%0d metadata=%0d cfg=%0d run=%0d stream=%0d cross=%0d sat=%0d cancel=%0d reset=%0d real=%0d replay=%0d groups=%0d",
                   jobs, word_checks, metadata_checks, config_errors, run_errors,
                   stream_errors, cross_checks, saturation_checks, cancel_offsets,
                   reset_offsets, real_window_checks, replay_pairs, max_groups_seen);
        done = 1;
    end
endmodule
`default_nettype wire
