`timescale 1ns/1ps
`default_nettype none

// Isolated packer regression. The reference and candidate have independent
// ready/valid timing; each output stream is checked against the same CHW
// scatter oracle by handshake order, never by cycle alignment.
//
// The small owner registers below model only the wrapper policy
// conv_owned <= cfg_fire; clear on done/reset/cancel; hold on error. This is
// an ownership-policy harness, not an instantiation of the production pool
// wrapper. The primary thread owns full-wrapper validation.
module tb_z100_native_output_packer_staged;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    wire pass4, pass8, pass12, pass20;
    packer_staged_case #(.SITES(4), .CASE_ID(4)) c4 (.clk(clk), .finished(pass4));
    packer_staged_case #(.SITES(8), .CASE_ID(8)) c8 (.clk(clk), .finished(pass8));
    packer_staged_case #(.SITES(12), .CASE_ID(12)) c12 (.clk(clk), .finished(pass12));
    packer_staged_case #(.SITES(20), .CASE_ID(20)) c20 (.clk(clk), .finished(pass20));

    initial begin
        wait (pass4 && pass8 && pass12 && pass20);
        $display("PACKER_STAGED_PASS cases=4 owner_harness_only=1 actual_wrapper=0");
        $finish;
    end

    initial begin
        #100000000;
        $fatal(1, "PACKER_STAGED_FAIL top watchdog");
    end
endmodule

module packer_staged_case #(parameter integer SITES=20, parameter integer CASE_ID=20)
    (input wire clk, output reg finished=1'b0);
    localparam [2:0] ERR_BAD_CONFIG = 3'd1;
    localparam [2:0] ERR_BAD_INPUT = 3'd2;

    reg rst_n = 1'b0;
    reg cancel = 1'b0;

    reg cfg_valid_ref = 1'b0, cfg_valid_cand = 1'b0;
    wire cfg_ready_ref, cfg_ready_cand;
    reg [31:0] cfg_epoch = 32'b0;
    reg [10:0] cfg_channels = 11'b0;
    reg [9:0] cfg_height = 10'b0, cfg_width = 10'b0;
    reg [31:0] cfg_token_base = 32'b0;

    reg in_valid_ref = 1'b0, in_valid_cand = 1'b0;
    wire in_ready_ref, in_ready_cand;
    reg [31:0] in_epoch = 32'b0, in_token = 32'b0;
    reg [4:0] in_site = 5'b0;
    reg [5:0] in_lanes = 6'b0;
    reg in_last = 1'b0;
    reg [255:0] in_data = 256'b0;

    wire out_valid_ref, out_valid_cand;
    reg out_ready_ref = 1'b0, out_ready_cand = 1'b0;
    wire [31:0] out_epoch_ref, out_epoch_cand;
    wire [12:0] out_address_ref, out_address_cand;
    wire [511:0] out_data_ref, out_data_cand;
    wire out_last_ref, out_last_cand;
    wire done_ref, done_cand, error_ref, error_cand;
    wire [2:0] error_code_ref, error_code_cand;
    wire active_ref, active_cand;

    z100_native_output_packer_reference #(.SITES(SITES)) reference_dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_valid(cfg_valid_ref), .cfg_ready(cfg_ready_ref), .cfg_epoch(cfg_epoch),
        .cfg_channels(cfg_channels), .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_token_base(cfg_token_base), .in_valid(in_valid_ref), .in_ready(in_ready_ref),
        .in_epoch(in_epoch), .in_token(in_token), .in_site(in_site), .in_lanes(in_lanes),
        .in_last(in_last), .in_data(in_data), .out_valid(out_valid_ref),
        .out_ready(out_ready_ref), .out_epoch(out_epoch_ref), .out_address(out_address_ref),
        .out_data(out_data_ref), .out_last(out_last_ref), .done(done_ref),
        .error_valid(error_ref), .error_code(error_code_ref), .active(active_ref)
    );

    z100_native_output_packer #(.SITES(SITES)) candidate_dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_valid(cfg_valid_cand), .cfg_ready(cfg_ready_cand), .cfg_epoch(cfg_epoch),
        .cfg_channels(cfg_channels), .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_token_base(cfg_token_base), .in_valid(in_valid_cand), .in_ready(in_ready_cand),
        .in_epoch(in_epoch), .in_token(in_token), .in_site(in_site), .in_lanes(in_lanes),
        .in_last(in_last), .in_data(in_data), .out_valid(out_valid_cand),
        .out_ready(out_ready_cand), .out_epoch(out_epoch_cand), .out_address(out_address_cand),
        .out_data(out_data_cand), .out_last(out_last_cand), .done(done_cand),
        .error_valid(error_cand), .error_code(error_code_cand), .active(active_cand)
    );

    integer cycle_no = 0;
    integer cfg_fires_ref = 0, cfg_fires_cand = 0;
    integer cfg_cycle_ref = -1, cfg_cycle_cand = -1;
    integer in_fires_ref = 0, in_fires_cand = 0;
    integer first_in_cycle_ref = -1, first_in_cycle_cand = -1;
    integer done_count_ref = 0, done_count_cand = 0;
    integer error_count_ref = 0, error_count_cand = 0;
    integer cfg_error_count = 0, input_error_count = 0;
    integer expected_error_ref = 0, expected_error_cand = 0;
    integer error_cycle_ref = -1, error_cycle_cand = -1;

    integer case_c = 1, case_h = 1, case_w = 1;
    reg [31:0] case_epoch = 32'b0, case_token = 32'b0;
    integer expected_words = 0;
    integer expected_input_beats = 0;
    integer output_index_ref = 0, output_index_cand = 0;
    integer stream_index = 0, stream_total = 0;
    reg stream_tracking = 1'b0, stream_auto = 1'b0;
    reg stream_accepted_ref = 1'b0, stream_accepted_cand = 1'b0;
    reg scoreboard_enable = 1'b0;

    reg owner_ref = 1'b0, owner_cand = 1'b0;
    integer owner_checks = 0;
    integer valid_case_count = 0;
    integer cancel_abort_count = 0, reset_abort_count = 0;
    integer input_stall_ref = 0, input_stall_cand = 0;
    integer output_stall_ref = 0, output_stall_cand = 0;
    integer input_stability_checks = 0, output_stability_checks = 0;
    integer valid_output_total = 0;
    integer loop_i, loop_j, loop_k;
    integer width_table [0:11];
    integer channel_table [0:7];

    reg prev_in_stall_ref = 1'b0, prev_in_stall_cand = 1'b0;
    reg [31:0] held_in_epoch = 32'b0, held_in_token = 32'b0;
    reg [4:0] held_in_site = 5'b0;
    reg [5:0] held_in_lanes = 6'b0;
    reg held_in_last = 1'b0;
    reg [255:0] held_in_data = 256'b0;
    reg prev_out_stall_ref = 1'b0, prev_out_stall_cand = 1'b0;
    reg [31:0] held_out_epoch_ref = 32'b0, held_out_epoch_cand = 32'b0;
    reg [12:0] held_out_address_ref = 13'b0, held_out_address_cand = 13'b0;
    reg [511:0] held_out_data_ref = 512'b0, held_out_data_cand = 512'b0;
    reg held_out_last_ref = 1'b0, held_out_last_cand = 1'b0;
    reg last_fire_ref_this_edge = 1'b0, last_fire_cand_this_edge = 1'b0;

    function [7:0] sample_byte;
        input integer row_value;
        input integer x_value;
        input integer channel_value;
        input [31:0] salt;
        integer mixed;
        begin
            mixed = (row_value * 73) + (x_value * 29) + (channel_value * 17) +
                    salt[7:0] + (CASE_ID * 11);
            sample_byte = mixed & 255;
        end
    endfunction

    function [255:0] make_input_word;
        input integer row_value;
        input integer x_value;
        input integer channel_group;
        input integer channels_value;
        input [31:0] salt;
        integer lane;
        integer absolute_channel;
        begin
            make_input_word = 256'b0;
            for (lane = 0; lane < 32; lane = lane + 1) begin
                absolute_channel = (channel_group * 32) + lane;
                if (absolute_channel < channels_value)
                    make_input_word[lane*8 +: 8] =
                        sample_byte(row_value, x_value, absolute_channel, salt);
                else
                    make_input_word[lane*8 +: 8] = 8'hd3 ^ lane[7:0];
            end
        end
    endfunction

    function [12:0] expected_address;
        input integer output_number;
        input integer channels_value;
        input integer height_value;
        input integer width_value;
        integer x_words;
        integer group4;
        integer remainder;
        integer row_value;
        integer x_word;
        integer group32;
        integer subgroups;
        begin
            x_words = (width_value + 15) / 16;
            // Stream order is group32,row,xword,subgroup4. The stored
            // address order is group4,row,xword and is intentionally scattered.
            group32 = output_number / (8 * height_value * x_words);
            remainder = output_number % (8 * height_value * x_words);
            subgroups = (channels_value - group32 * 32 + 3) / 4;
            if (subgroups > 8) subgroups = 8;
            group4 = group32 * 8 + remainder % subgroups;
            row_value = remainder / (subgroups * x_words);
            x_word = (remainder / subgroups) % x_words;
            expected_address = ((group4 * height_value + row_value) * x_words) + x_word;
        end
    endfunction

    function [511:0] expected_data;
        input integer output_number;
        input integer channels_value;
        input integer height_value;
        input integer width_value;
        input [31:0] salt;
        integer x_words;
        integer group4;
        integer remainder;
        integer row_value;
        integer x_word;
        integer lane;
        integer x_offset;
        integer absolute_channel;
        integer absolute_x;
        integer address_value;
        begin
            x_words = (width_value + 15) / 16;
            address_value = expected_address(output_number, channels_value,
                                             height_value, width_value);
            group4 = address_value / (height_value * x_words);
            remainder = address_value % (height_value * x_words);
            row_value = remainder / x_words;
            x_word = remainder % x_words;
            expected_data = 512'b0;
            for (lane = 0; lane < 4; lane = lane + 1) begin
                absolute_channel = (group4 * 4) + lane;
                for (x_offset = 0; x_offset < 16; x_offset = x_offset + 1) begin
                    absolute_x = (x_word * 16) + x_offset;
                    if ((absolute_channel < channels_value) && (absolute_x < width_value))
                        expected_data[(lane*16+x_offset)*8 +: 8] =
                            sample_byte(row_value, absolute_x, absolute_channel, salt);
                end
            end
        end
    endfunction

    always @(negedge clk) begin
        if (stream_auto && rst_n && !cancel) begin
            out_ready_ref = ((cycle_no % 11) != 3) && ((cycle_no % 11) != 4);
            out_ready_cand = ((cycle_no % 13) != 2) && ((cycle_no % 13) != 3) &&
                             ((cycle_no % 13) != 4);
            if (stream_index < stream_total) begin
                in_valid_ref = !stream_accepted_ref;
                in_valid_cand = !stream_accepted_cand;
                begin : gen_beat
                    integer group_value;
                    integer row_value;
                    integer x_value;
                    integer channels_left;
                    integer this_run;
                    integer run_site;
                    group_value = stream_index / (case_h * case_w);
                    row_value = (stream_index / case_w) % case_h;
                    x_value = stream_index % case_w;
                    channels_left = case_c - (group_value * 32);
                    in_epoch = case_epoch;
                    in_token = case_token +
                        ((((group_value * case_h) + row_value) * ((case_w + SITES - 1) / SITES)) +
                         (x_value / SITES));
                    in_site = x_value % SITES;
                    in_lanes = (channels_left >= 32) ? 6'd32 : channels_left[5:0];
                    this_run = case_w - ((x_value / SITES) * SITES);
                    if (this_run > SITES) this_run = SITES;
                    run_site = x_value % SITES;
                    in_last = (run_site == (this_run - 1));
                    in_data = make_input_word(row_value, x_value, group_value,
                                              case_c, case_epoch);
                end
            end else begin
                in_valid_ref = 1'b0;
                in_valid_cand = 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        cycle_no = cycle_no + 1;
        if (cycle_no > 1000000)
            $fatal(1, "PACKER_STAGED_FAIL sites=%0d watchdog", SITES);

        last_fire_ref_this_edge = 1'b0;
        last_fire_cand_this_edge = 1'b0;

        if (!rst_n || cancel) begin
            prev_in_stall_ref = 1'b0;
            prev_in_stall_cand = 1'b0;
            prev_out_stall_ref = 1'b0;
            prev_out_stall_cand = 1'b0;
            owner_ref = 1'b0;
            owner_cand = 1'b0;
        end else begin
            if (cfg_valid_ref && cfg_ready_ref) begin
                cfg_fires_ref = cfg_fires_ref + 1;
                cfg_cycle_ref = cycle_no;
                owner_ref = 1'b1;
            end else if (done_ref) begin
                owner_ref = 1'b0;
            end
            if (cfg_valid_cand && cfg_ready_cand) begin
                cfg_fires_cand = cfg_fires_cand + 1;
                cfg_cycle_cand = cycle_no;
                owner_cand = 1'b1;
            end else if (done_cand) begin
                owner_cand = 1'b0;
            end

            if (in_valid_ref && in_ready_ref) begin
                in_fires_ref = in_fires_ref + 1;
                if (first_in_cycle_ref < 0) first_in_cycle_ref = cycle_no;
                if (stream_tracking) stream_accepted_ref = 1'b1;
            end
            if (in_valid_cand && in_ready_cand) begin
                in_fires_cand = in_fires_cand + 1;
                if (first_in_cycle_cand < 0) first_in_cycle_cand = cycle_no;
                if (stream_tracking) stream_accepted_cand = 1'b1;
            end
            if (stream_tracking && stream_accepted_ref && stream_accepted_cand) begin
                stream_index = stream_index + 1;
                stream_accepted_ref = 1'b0;
                stream_accepted_cand = 1'b0;
            end

            if (prev_in_stall_ref) begin
                if (!in_valid_ref || in_epoch !== held_in_epoch || in_token !== held_in_token ||
                    in_site !== held_in_site || in_lanes !== held_in_lanes ||
                    in_last !== held_in_last || in_data !== held_in_data)
                    $fatal(1, "SITES=%0d reference input changed while stalled", SITES);
                input_stability_checks = input_stability_checks + 1;
            end
            if (prev_in_stall_cand) begin
                if (!in_valid_cand || in_epoch !== held_in_epoch || in_token !== held_in_token ||
                    in_site !== held_in_site || in_lanes !== held_in_lanes ||
                    in_last !== held_in_last || in_data !== held_in_data)
                    $fatal(1, "SITES=%0d candidate input changed while stalled", SITES);
                input_stability_checks = input_stability_checks + 1;
            end
            prev_in_stall_ref = in_valid_ref && !in_ready_ref;
            prev_in_stall_cand = in_valid_cand && !in_ready_cand;
            if (prev_in_stall_ref) begin
                input_stall_ref = input_stall_ref + 1;
                held_in_epoch = in_epoch; held_in_token = in_token; held_in_site = in_site;
                held_in_lanes = in_lanes; held_in_last = in_last; held_in_data = in_data;
            end
            if (prev_in_stall_cand) begin
                input_stall_cand = input_stall_cand + 1;
                held_in_epoch = in_epoch; held_in_token = in_token; held_in_site = in_site;
                held_in_lanes = in_lanes; held_in_last = in_last; held_in_data = in_data;
            end

            if (prev_out_stall_ref) begin
                if (!out_valid_ref || out_epoch_ref !== held_out_epoch_ref ||
                    out_address_ref !== held_out_address_ref || out_data_ref !== held_out_data_ref ||
                    out_last_ref !== held_out_last_ref)
                    $fatal(1, "SITES=%0d reference output changed while stalled", SITES);
                output_stability_checks = output_stability_checks + 1;
            end
            if (prev_out_stall_cand) begin
                if (!out_valid_cand || out_epoch_cand !== held_out_epoch_cand ||
                    out_address_cand !== held_out_address_cand || out_data_cand !== held_out_data_cand ||
                    out_last_cand !== held_out_last_cand)
                    $fatal(1, "SITES=%0d candidate output changed while stalled", SITES);
                output_stability_checks = output_stability_checks + 1;
            end
            prev_out_stall_ref = out_valid_ref && !out_ready_ref;
            prev_out_stall_cand = out_valid_cand && !out_ready_cand;
            if (prev_out_stall_ref) begin
                output_stall_ref = output_stall_ref + 1;
                held_out_epoch_ref = out_epoch_ref; held_out_address_ref = out_address_ref;
                held_out_data_ref = out_data_ref; held_out_last_ref = out_last_ref;
            end
            if (prev_out_stall_cand) begin
                output_stall_cand = output_stall_cand + 1;
                held_out_epoch_cand = out_epoch_cand; held_out_address_cand = out_address_cand;
                held_out_data_cand = out_data_cand; held_out_last_cand = out_last_cand;
            end

            if (scoreboard_enable && out_valid_ref && out_ready_ref) begin
                if (output_index_ref >= expected_words)
                    $fatal(1, "SITES=%0d extra reference output", SITES);
                if (out_epoch_ref !== case_epoch ||
                    out_address_ref !== expected_address(output_index_ref, case_c, case_h, case_w) ||
                    out_data_ref !== expected_data(output_index_ref, case_c, case_h, case_w, case_epoch) ||
                    out_last_ref !== (output_index_ref == expected_words - 1))
                    $fatal(1, "SITES=%0d reference scatter mismatch word=%0d addr=%0d expected_addr=%0d",
                           SITES, output_index_ref, out_address_ref,
                           expected_address(output_index_ref, case_c, case_h, case_w));
                output_index_ref = output_index_ref + 1;
                valid_output_total = valid_output_total + 1;
                if (out_last_ref) last_fire_ref_this_edge = 1'b1;
            end
            if (scoreboard_enable && out_valid_cand && out_ready_cand) begin
                if (output_index_cand >= expected_words)
                    $fatal(1, "SITES=%0d extra candidate output", SITES);
                if (out_epoch_cand !== case_epoch ||
                    out_address_cand !== expected_address(output_index_cand, case_c, case_h, case_w) ||
                    out_data_cand !== expected_data(output_index_cand, case_c, case_h, case_w, case_epoch) ||
                    out_last_cand !== (output_index_cand == expected_words - 1))
                    $fatal(1, "SITES=%0d candidate scatter mismatch word=%0d addr=%0d expected_addr=%0d",
                           SITES, output_index_cand, out_address_cand,
                           expected_address(output_index_cand, case_c, case_h, case_w));
                output_index_cand = output_index_cand + 1;
                valid_output_total = valid_output_total + 1;
                if (out_last_cand) last_fire_cand_this_edge = 1'b1;
            end
        end

        #0.1;
        if (done_ref) begin
            if (!last_fire_ref_this_edge)
                $fatal(1, "SITES=%0d reference done was not paired with final output handshake", SITES);
            done_count_ref = done_count_ref + 1;
        end
        if (done_cand) begin
            if (!last_fire_cand_this_edge)
                $fatal(1, "SITES=%0d candidate done was not paired with final output handshake", SITES);
            done_count_cand = done_count_cand + 1;
        end
        if (error_ref) begin
            if (error_code_ref !== expected_error_ref[2:0])
                $fatal(1, "SITES=%0d reference error=%0d expected=%0d", SITES,
                       error_code_ref, expected_error_ref);
            error_count_ref = error_count_ref + 1;
            error_cycle_ref = cycle_no;
            if (error_code_ref == ERR_BAD_CONFIG) cfg_error_count = cfg_error_count + 1;
            if (error_code_ref == ERR_BAD_INPUT) input_error_count = input_error_count + 1;
        end
        if (error_cand) begin
            if (error_code_cand !== expected_error_cand[2:0])
                $fatal(1, "SITES=%0d candidate error=%0d expected=%0d", SITES,
                       error_code_cand, expected_error_cand);
            error_count_cand = error_count_cand + 1;
            error_cycle_cand = cycle_no;
        end
    end

    task reset_pair;
        begin
            @(negedge clk);
            rst_n = 1'b0; cancel = 1'b0;
            cfg_valid_ref = 1'b0; cfg_valid_cand = 1'b0;
            in_valid_ref = 1'b0; in_valid_cand = 1'b0;
            out_ready_ref = 1'b0; out_ready_cand = 1'b0;
            stream_auto = 1'b0; stream_tracking = 1'b0; scoreboard_enable = 1'b0;
            @(posedge clk); #1;
            if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                owner_ref || owner_cand)
                $fatal(1, "SITES=%0d reset failed to clear runtime/owner state", SITES);
            @(negedge clk); rst_n = 1'b1;
            @(posedge clk); #1;
            if (!cfg_ready_ref || !cfg_ready_cand)
                $fatal(1, "SITES=%0d packer not ready after reset", SITES);
        end
    endtask

    task issue_config;
        input [10:0] channels_value;
        input [9:0] height_value;
        input [9:0] width_value;
        input [31:0] epoch_value;
        input [31:0] token_value;
        integer start_ref;
        integer start_cand;
        integer seen_ref;
        integer seen_cand;
        integer wait_count;
        begin
            @(negedge clk);
            cfg_channels = channels_value; cfg_height = height_value; cfg_width = width_value;
            cfg_epoch = epoch_value; cfg_token_base = token_value;
            start_ref = cfg_fires_ref; start_cand = cfg_fires_cand;
            seen_ref = 0; seen_cand = 0; wait_count = 0;
            cfg_valid_ref = 1'b1; cfg_valid_cand = 1'b1;
            while (((seen_ref == 0) || (seen_cand == 0)) && (wait_count < 100)) begin
                @(posedge clk); #1;
                if (cfg_fires_ref > start_ref) seen_ref = 1;
                if (cfg_fires_cand > start_cand) seen_cand = 1;
                wait_count = wait_count + 1;
                @(negedge clk);
                if (seen_ref != 0) cfg_valid_ref = 1'b0;
                if (seen_cand != 0) cfg_valid_cand = 1'b0;
            end
            if (!seen_ref || !seen_cand)
                $fatal(1, "SITES=%0d configuration handshake watchdog", SITES);
            // Deliberately mutate live inputs after E0. The pending candidate
            // must use only its accepted snapshot; the reference must agree.
            cfg_epoch = epoch_value ^ 32'h5a5aa5a5;
            cfg_token_base = 32'hdeadbeef;
            cfg_channels = 11'd2047; cfg_height = 10'd1023; cfg_width = 10'd1023;
        end
    endtask

    task wait_active_pair;
        integer wait_count;
        begin
            wait_count = 0;
            while ((!active_ref || !active_cand) && (wait_count < 32)) begin
                @(posedge clk); #1;
                wait_count = wait_count + 1;
            end
            if (!active_ref || !active_cand)
                $fatal(1, "SITES=%0d valid config failed to become active", SITES);
        end
    endtask

    task probe_busy_config;
        integer start_ref;
        integer start_cand;
        integer probe_i;
        begin
            start_ref = cfg_fires_ref; start_cand = cfg_fires_cand;
            @(negedge clk);
            cfg_epoch = 32'h1234abcd; cfg_token_base = 32'h10203040;
            cfg_channels = 11'd32; cfg_height = 10'd2; cfg_width = 10'd33;
            cfg_valid_ref = 1'b1; cfg_valid_cand = 1'b1;
            for (probe_i = 0; probe_i < 2; probe_i = probe_i + 1) begin
                @(posedge clk); #1;
                if (cfg_ready_ref || cfg_ready_cand ||
                    cfg_fires_ref != start_ref || cfg_fires_cand != start_cand)
                    $fatal(1, "SITES=%0d second config accepted while active", SITES);
            end
            @(negedge clk); cfg_valid_ref = 1'b0; cfg_valid_cand = 1'b0;
            @(posedge clk); #1;
        end
    endtask

    task run_valid_geometry;
        input integer channels_value;
        input integer height_value;
        input integer width_value;
        input [31:0] token_value;
        input [31:0] epoch_value;
        integer start_done_ref;
        integer start_done_cand;
        integer start_errors_ref;
        integer start_errors_cand;
        integer wait_count;
        begin
            case_c = channels_value; case_h = height_value; case_w = width_value;
            case_epoch = epoch_value; case_token = token_value;
            expected_words = ((channels_value + 3) / 4) * height_value * ((width_value + 15) / 16);
            expected_input_beats = ((channels_value + 31) / 32) * height_value * width_value;
            output_index_ref = 0; output_index_cand = 0;
            expected_error_ref = 0; expected_error_cand = 0;
            start_done_ref = done_count_ref; start_done_cand = done_count_cand;
            start_errors_ref = error_count_ref; start_errors_cand = error_count_cand;
            issue_config(channels_value[10:0], height_value[9:0], width_value[9:0],
                         epoch_value, token_value);
            wait_active_pair();
            if (!owner_ref || !owner_cand)
                $fatal(1, "SITES=%0d owner was not acquired at config acceptance", SITES);
            owner_checks = owner_checks + 1;
            probe_busy_config();

            stream_index = 0; stream_total = expected_input_beats;
            stream_accepted_ref = 1'b0; stream_accepted_cand = 1'b0;
            stream_tracking = 1'b1; scoreboard_enable = 1'b1;
            stream_auto = 1'b1;
            wait_count = 0;
            while (((done_count_ref == start_done_ref) || (done_count_cand == start_done_cand)) &&
                   (wait_count < 200000)) begin
                @(posedge clk); #1;
                wait_count = wait_count + 1;
                if (error_count_ref != start_errors_ref || error_count_cand != start_errors_cand)
                    $fatal(1, "SITES=%0d unexpected error during valid geometry", SITES);
            end
            if (done_count_ref != start_done_ref + 1 || done_count_cand != start_done_cand + 1)
                $fatal(1, "SITES=%0d valid geometry completion watchdog", SITES);
            if (stream_index != stream_total || output_index_ref != expected_words ||
                output_index_cand != expected_words)
                $fatal(1, "SITES=%0d incomplete valid stream in=%0d/%0d out=%0d/%0d expected=%0d",
                       SITES, stream_index, stream_total, output_index_ref, output_index_cand, expected_words);
            stream_auto = 1'b0; stream_tracking = 1'b0; scoreboard_enable = 1'b0;
            @(negedge clk);
            in_valid_ref = 1'b0; in_valid_cand = 1'b0;
            out_ready_ref = 1'b0; out_ready_cand = 1'b0;
            @(posedge clk); #1;
            if (owner_ref || owner_cand)
                $fatal(1, "SITES=%0d owner did not release after done", SITES);
            if (error_count_ref != start_errors_ref || error_count_cand != start_errors_cand)
                $fatal(1, "SITES=%0d unexpected valid-case error", SITES);
            valid_case_count = valid_case_count + 1;
        end
    endtask

    task cancel_and_check;
        integer wait_i;
        begin
            @(negedge clk);
            stream_auto = 1'b0; stream_tracking = 1'b0; scoreboard_enable = 1'b0;
            cfg_valid_ref = 1'b0; cfg_valid_cand = 1'b0;
            in_valid_ref = 1'b0; in_valid_cand = 1'b0;
            cancel = 1'b1;
            @(posedge clk); #1;
            if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                out_valid_ref || out_valid_cand || owner_ref || owner_cand)
                $fatal(1, "SITES=%0d cancel failed to clear runtime/error/owner", SITES);
            cancel_abort_count = cancel_abort_count + 1;
            @(negedge clk); cancel = 1'b0;
            for (wait_i = 0; wait_i < 4; wait_i = wait_i + 1) begin
                @(posedge clk); #1;
                if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                    out_valid_ref || out_valid_cand)
                    $fatal(1, "SITES=%0d late event after cancel", SITES);
            end
        end
    endtask

    task reset_abort_check;
        integer wait_i;
        begin
            @(negedge clk);
            stream_auto = 1'b0; stream_tracking = 1'b0; scoreboard_enable = 1'b0;
            cfg_valid_ref = 1'b0; cfg_valid_cand = 1'b0;
            in_valid_ref = 1'b0; in_valid_cand = 1'b0;
            rst_n = 1'b0;
            @(posedge clk); #1;
            if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                out_valid_ref || out_valid_cand || owner_ref || owner_cand)
                $fatal(1, "SITES=%0d reset failed to clear pending/runtime/owner", SITES);
            reset_abort_count = reset_abort_count + 1;
            @(negedge clk); rst_n = 1'b1;
            for (wait_i = 0; wait_i < 4; wait_i = wait_i + 1) begin
                @(posedge clk); #1;
                if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                    out_valid_ref || out_valid_cand)
                    $fatal(1, "SITES=%0d late event after reset", SITES);
            end
        end
    endtask

    // These two helpers are called at the current negedge immediately after
    // E0, so their reset/cancel is sampled on the requested E1 edge.
    task cancel_pending_now;
        integer wait_i;
        begin
            cancel = 1'b1;
            @(posedge clk); #1;
            if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                out_valid_ref || out_valid_cand || owner_ref || owner_cand)
                $fatal(1, "SITES=%0d E1 cancel failed to clear pending/owner", SITES);
            cancel_abort_count = cancel_abort_count + 1;
            @(negedge clk); cancel = 1'b0;
            for (wait_i = 0; wait_i < 4; wait_i = wait_i + 1) begin
                @(posedge clk); #1;
                if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                    out_valid_ref || out_valid_cand)
                    $fatal(1, "SITES=%0d late event after E1 cancel", SITES);
            end
        end
    endtask

    task reset_pending_now;
        integer wait_i;
        begin
            rst_n = 1'b0;
            @(posedge clk); #1;
            if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                out_valid_ref || out_valid_cand || owner_ref || owner_cand)
                $fatal(1, "SITES=%0d E1 reset failed to clear pending/owner", SITES);
            reset_abort_count = reset_abort_count + 1;
            @(negedge clk); rst_n = 1'b1;
            for (wait_i = 0; wait_i < 4; wait_i = wait_i + 1) begin
                @(posedge clk); #1;
                if (active_ref || active_cand || error_ref || error_cand || done_ref || done_cand ||
                    out_valid_ref || out_valid_cand)
                    $fatal(1, "SITES=%0d late event after E1 reset", SITES);
            end
        end
    endtask

    task run_invalid_config;
        input [10:0] channels_value;
        input [9:0] height_value;
        input [9:0] width_value;
        input [31:0] token_value;
        integer start_error_ref;
        integer start_error_cand;
        integer start_done_ref;
        integer start_done_cand;
        integer pending_edge;
        begin
            expected_error_ref = ERR_BAD_CONFIG;
            expected_error_cand = ERR_BAD_CONFIG;
            start_error_ref = error_count_ref; start_error_cand = error_count_cand;
            start_done_ref = done_count_ref; start_done_cand = done_count_cand;
            issue_config(channels_value, height_value, width_value,
                         32'hc0010000 + CASE_ID + cfg_fires_cand, token_value);
            // The candidate must hold the accepted invalid snapshot through
            // E1-E3 and report once at E4. The reference reports on E0.
            for (pending_edge = 1; pending_edge <= 3; pending_edge = pending_edge + 1) begin
                @(posedge clk); #1;
                if (active_cand || cfg_ready_cand || in_ready_cand ||
                    error_count_cand != start_error_cand)
                    $fatal(1, "SITES=%0d invalid candidate left pending before E4 edge=%0d",
                           SITES, pending_edge);
            end
            @(posedge clk); #1;
            if (error_count_ref != start_error_ref + 1 || error_count_cand != start_error_cand + 1)
                $fatal(1, "SITES=%0d invalid config did not report exactly once", SITES);
            if (error_cycle_ref != cfg_cycle_ref || error_cycle_cand != cfg_cycle_cand + 4)
                $fatal(1, "SITES=%0d invalid config error timing ref=%0d/%0d cand=%0d/%0d",
                       SITES, error_cycle_ref, cfg_cycle_ref, error_cycle_cand, cfg_cycle_cand);
            if (done_count_ref != start_done_ref || done_count_cand != start_done_cand ||
                owner_ref !== 1'b1 || owner_cand !== 1'b1)
                $fatal(1, "SITES=%0d invalid config completed or incorrectly released owner", SITES);
            owner_checks = owner_checks + 1;
            cancel_and_check();
            expected_error_ref = 0; expected_error_cand = 0;
        end
    endtask

    task run_bad_input;
        input integer bad_field;
        integer start_error_ref;
        integer start_error_cand;
        integer start_done_ref;
        integer start_done_cand;
        integer start_in_ref;
        integer start_in_cand;
        integer wait_count;
        begin
            case_c = 4; case_h = 1; case_w = 1;
            case_epoch = 32'hbadd0000 + (CASE_ID * 16) + bad_field;
            case_token = 32'h13570000 + bad_field;
            expected_error_ref = 0; expected_error_cand = 0;
            issue_config(case_c[10:0], case_h[9:0], case_w[9:0], case_epoch, case_token);
            wait_active_pair();

            expected_error_ref = ERR_BAD_INPUT; expected_error_cand = ERR_BAD_INPUT;
            start_error_ref = error_count_ref; start_error_cand = error_count_cand;
            start_done_ref = done_count_ref; start_done_cand = done_count_cand;
            start_in_ref = in_fires_ref; start_in_cand = in_fires_cand;
            stream_index = 0; stream_total = 1; stream_tracking = 1'b1;
            stream_auto = 1'b0; scoreboard_enable = 1'b0;
            stream_accepted_ref = 1'b0; stream_accepted_cand = 1'b0;
            @(negedge clk);
            in_epoch = case_epoch; in_token = case_token; in_site = 5'd0;
            in_lanes = 6'd4; in_last = 1'b1;
            in_data = make_input_word(0, 0, 0, case_c, case_epoch);
            case (bad_field)
                0: in_epoch = case_epoch ^ 32'h1;
                1: in_token = case_token ^ 32'h1;
                2: in_site = 5'd1;
                3: in_lanes = 6'd3;
                4: in_last = 1'b0;
                default: $fatal(1, "bad metadata field index=%0d", bad_field);
            endcase
            in_valid_ref = 1'b1; in_valid_cand = 1'b1;
            wait_count = 0;
            while (((in_fires_ref == start_in_ref) || (in_fires_cand == start_in_cand)) &&
                   (wait_count < 100)) begin
                @(posedge clk); #1; wait_count = wait_count + 1;
                @(negedge clk);
                if (in_fires_ref > start_in_ref) in_valid_ref = 1'b0;
                if (in_fires_cand > start_in_cand) in_valid_cand = 1'b0;
            end
            if (in_fires_ref != start_in_ref + 1 || in_fires_cand != start_in_cand + 1)
                $fatal(1, "SITES=%0d malformed input did not handshake", SITES);
            wait_count = 0;
            while (((error_count_ref == start_error_ref) || (error_count_cand == start_error_cand)) &&
                   (wait_count < 20)) begin
                @(posedge clk); #1; wait_count = wait_count + 1;
            end
            if (error_count_ref != start_error_ref + 1 || error_count_cand != start_error_cand + 1 ||
                done_count_ref != start_done_ref || done_count_cand != start_done_cand)
                $fatal(1, "SITES=%0d malformed input recovery contract failed", SITES);
            if (owner_ref !== 1'b1 || owner_cand !== 1'b1)
                $fatal(1, "SITES=%0d bad input released owner before cancel", SITES);
            owner_checks = owner_checks + 1;
            cancel_and_check();
            expected_error_ref = 0; expected_error_cand = 0;
        end
    endtask

    task run_pending_abort;
        input integer target_stage;
        input integer use_reset;
        integer edge_i;
        begin
            expected_error_ref = 0; expected_error_cand = 0;
            case_c = 33; case_h = 3; case_w = 33;
            case_epoch = 32'hab000000 + CASE_ID + (target_stage * 16) + use_reset;
            case_token = 32'h77000000 + target_stage;
            issue_config(case_c[10:0], case_h[9:0], case_w[9:0], case_epoch, case_token);
            if (active_cand || cfg_ready_cand || in_ready_cand || !owner_cand)
                $fatal(1, "SITES=%0d candidate not pending after E0", SITES);
            for (edge_i = 1; edge_i < target_stage; edge_i = edge_i + 1) begin
                @(posedge clk); #1;
                if (active_cand || cfg_ready_cand || in_ready_cand || error_cand || done_cand)
                    $fatal(1, "SITES=%0d candidate not pending at E%0d", SITES, edge_i);
            end
            if (target_stage == 1) begin
                if (use_reset != 0) reset_pending_now();
                else cancel_pending_now();
            end else begin
                if (use_reset != 0) reset_abort_check();
                else cancel_and_check();
            end
            expected_error_ref = 0; expected_error_cand = 0;
        end
    endtask

    task run_earliest_input_case;
        integer edge_i_local;
        integer start_cfg_ref;
        integer start_cfg_cand;
        integer start_in_ref;
        integer start_in_cand;
        integer start_done_ref;
        integer start_done_cand;
        integer wait_count;
        begin
            case_c = 1; case_h = 1; case_w = 1;
            case_epoch = 32'hf00d0000 + CASE_ID;
            case_token = 32'hffffffff;
            expected_words = 1; expected_input_beats = 1;
            output_index_ref = 0; output_index_cand = 0;
            expected_error_ref = 0; expected_error_cand = 0;
            start_cfg_ref = cfg_fires_ref; start_cfg_cand = cfg_fires_cand;
            start_in_ref = in_fires_ref; start_in_cand = in_fires_cand;
            start_done_ref = done_count_ref; start_done_cand = done_count_cand;
            stream_index = 0; stream_total = 1; stream_tracking = 1'b1; stream_auto = 1'b0;
            stream_accepted_ref = 1'b0; stream_accepted_cand = 1'b0;
            scoreboard_enable = 1'b1;
            @(negedge clk);
            cfg_channels = 11'd1; cfg_height = 10'd1; cfg_width = 10'd1;
            cfg_epoch = case_epoch; cfg_token_base = case_token;
            cfg_valid_ref = 1'b1; cfg_valid_cand = 1'b1;
            in_epoch = case_epoch; in_token = case_token; in_site = 5'd0;
            in_lanes = 6'd1; in_last = 1'b1;
            in_data = make_input_word(0, 0, 0, case_c, case_epoch);
            in_valid_ref = 1'b1; in_valid_cand = 1'b1;
            out_ready_ref = 1'b1; out_ready_cand = 1'b1;
            @(posedge clk); #1;
            if (cfg_fires_ref != start_cfg_ref + 1 || cfg_fires_cand != start_cfg_cand + 1 ||
                active_cand || cfg_ready_cand || in_ready_cand)
                $fatal(1, "SITES=%0d E0 snapshot/pending behavior mismatch", SITES);
            @(negedge clk); cfg_valid_ref = 1'b0; cfg_valid_cand = 1'b0;
            // At E1 the baseline can consume; the staged candidate must not.
            @(posedge clk); #1;
            if (in_fires_ref != start_in_ref + 1 || in_fires_cand != start_in_cand ||
                active_cand || cfg_ready_cand || in_ready_cand)
                $fatal(1, "SITES=%0d E1 input readiness contract mismatch", SITES);
            @(negedge clk); in_valid_ref = 1'b0;
            for (edge_i_local = 2; edge_i_local <= 4; edge_i_local = edge_i_local + 1) begin
                @(posedge clk); #1;
                if (edge_i_local < 4 && (active_cand || cfg_ready_cand || in_ready_cand))
                    $fatal(1, "SITES=%0d candidate accepted before E4", SITES);
                if (edge_i_local == 4 && !active_cand)
                    $fatal(1, "SITES=%0d candidate did not commit at E4", SITES);
                if (in_fires_cand != start_in_cand)
                    $fatal(1, "SITES=%0d candidate accepted input before E5", SITES);
            end
            @(posedge clk); #1;
            if (in_fires_cand != start_in_cand + 1 ||
                (cycle_no - cfg_cycle_cand) != 5)
                $fatal(1, "SITES=%0d earliest candidate input was not E5 cycle=%0d cfg=%0d",
                       SITES, first_in_cycle_cand, cfg_cycle_cand);
            @(negedge clk); in_valid_cand = 1'b0;
            wait_count = 0;
            while (((done_count_ref == start_done_ref) || (done_count_cand == start_done_cand)) &&
                   (wait_count < 100)) begin
                @(posedge clk); #1; wait_count = wait_count + 1;
            end
            if (output_index_ref != 1 || output_index_cand != 1 ||
                done_count_ref != start_done_ref + 1 || done_count_cand != start_done_cand + 1)
                $fatal(1, "SITES=%0d E5 timing case output/completion mismatch", SITES);
            scoreboard_enable = 1'b0; stream_tracking = 1'b0;
            @(posedge clk); #1;
            if (owner_ref || owner_cand)
                $fatal(1, "SITES=%0d max-token valid case owner release failed", SITES);
            valid_case_count = valid_case_count + 1;
        end
    endtask

    integer token_for_sweep;
    integer epoch_for_sweep;
    initial begin
        width_table[0]=1; width_table[1]=15; width_table[2]=16; width_table[3]=17;
        width_table[4]=19; width_table[5]=20; width_table[6]=21; width_table[7]=31;
        width_table[8]=32; width_table[9]=33; width_table[10]=40; width_table[11]=640;
        channel_table[0]=1; channel_table[1]=3; channel_table[2]=4; channel_table[3]=9;
        channel_table[4]=31; channel_table[5]=32; channel_table[6]=33; channel_table[7]=64;
        expected_error_ref = 0; expected_error_cand = 0;
        reset_pair();

        // E0 snapshot, exact E4 commit/E5 input, token zero/max, and basic CHW scatter.
        run_earliest_input_case();
        reset_pair();

        // Exercise every requested width/channel tail at every supported SITES.
        for (loop_i = 0; loop_i < 12; loop_i = loop_i + 1) begin
            for (loop_j = 0; loop_j < 8; loop_j = loop_j + 1) begin
                if ((loop_i == 0) && (loop_j == 0)) token_for_sweep = 0;
                else token_for_sweep = 32'h01000000 + (CASE_ID * 65536) +
                                       (loop_i * 257) + (loop_j * 17);
                epoch_for_sweep = 32'ha5000000 + (CASE_ID * 4096) +
                                  (loop_i * 32) + loop_j;
                run_valid_geometry(channel_table[loop_j], 1, width_table[loop_i],
                                   token_for_sweep[31:0], epoch_for_sweep[31:0]);
            end
        end
        run_valid_geometry(33, 2, 33, 32'h02000000 + CASE_ID, 32'ha5110021 + CASE_ID);
        run_valid_geometry(64, 3, 17, 32'h02010000 + CASE_ID, 32'ha5110033 + CASE_ID);
        run_valid_geometry(1024, 1, 1, 32'h02020000 + CASE_ID, 32'ha5110401 + CASE_ID);
        run_valid_geometry(1, 640, 1, 32'h02030000 + CASE_ID, 32'ha5110640 + CASE_ID);
        run_valid_geometry(64, 512, 16, 32'h03000000 + CASE_ID, 32'ha5128192 + CASE_ID);

        // 8193 is not representable by the allowed product factors (8193=3*2731,
        // and 2731 exceeds the maxima for ceil(C/4), H, and ceil(W/16)). The
        // first simple constructible over-cap point is 8208 output words.
        run_invalid_config(11'd64, 10'd513, 10'd16, 32'h04000000 + CASE_ID);
        run_invalid_config(11'd0, 10'd1, 10'd1, 32'd0);
        run_invalid_config(11'd1, 10'd0, 10'd1, 32'd0);
        run_invalid_config(11'd1, 10'd1, 10'd0, 32'd0);
        run_invalid_config(11'd1025, 10'd1, 10'd1, 32'd0);
        run_invalid_config(11'd1, 10'd641, 10'd1, 32'd0);
        run_invalid_config(11'd1, 10'd1, 10'd641, 32'd0);
        run_invalid_config(11'd2047, 10'd1023, 10'd1023, 32'd0);
        run_invalid_config(11'd1, 10'd1, 10'd21, 32'hffffffff);

        // Invalid input checks cover all five metadata fields; errors retain
        // ownership until cancel, followed by a fresh accepted configuration.
        for (loop_k = 0; loop_k < 5; loop_k = loop_k + 1) begin
            run_bad_input(loop_k);
        end

        // Reset and cancel each pending phase E1 through E4.
        for (loop_i = 1; loop_i <= 4; loop_i = loop_i + 1) begin
            run_pending_abort(loop_i, 0);
            run_pending_abort(loop_i, 1);
        end

        // Explicit error/cancel recovery into a known valid transaction.
        run_valid_geometry(9, 2, 19, 32'h05000000 + CASE_ID, 32'ha5130009 + CASE_ID);

        if (valid_case_count < 100 || cfg_error_count < 9 || input_error_count != 5 ||
            cancel_abort_count < 13 || reset_abort_count != 4 ||
            input_stall_ref == 0 || input_stall_cand == 0 ||
            output_stall_ref == 0 || output_stall_cand == 0 ||
            input_stability_checks == 0 || output_stability_checks == 0 || owner_checks < 14)
            $fatal(1, "SITES=%0d non-vacuous coverage counters failed valid=%0d cfgerr=%0d inerr=%0d cancel=%0d reset=%0d",
                   SITES, valid_case_count, cfg_error_count, input_error_count,
                   cancel_abort_count, reset_abort_count);
        finished = 1'b1;
        $display("PACKER_STAGED_CASE_PASS sites=%0d valid=%0d cfg_error=%0d input_error=%0d cancel=%0d reset=%0d owner_harness=1 input_stalls=%0d/%0d output_stalls=%0d/%0d stability=%0d/%0d outputs=%0d",
                 SITES, valid_case_count, cfg_error_count, input_error_count,
                 cancel_abort_count, reset_abort_count, input_stall_ref, input_stall_cand,
                 output_stall_ref, output_stall_cand, input_stability_checks,
                 output_stability_checks, valid_output_total);
    end
endmodule

`default_nettype wire
