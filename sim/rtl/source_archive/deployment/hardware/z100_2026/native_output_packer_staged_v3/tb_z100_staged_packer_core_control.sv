`timescale 1ns/1ps
`default_nettype none

// Directed integration control test for the actual V12 shared20site core.
// The runner substitutes the staged candidate for the packer only. Feature
// data and runtime traffic enter through the public feature/MAC/config ports;
// no internal valid, data, or ownership state is forced.
module tb_z100_staged_packer_core_control;
    localparam [31:0] EPOCH = 32'd200;
    localparam [31:0] TOKEN_BASE = 32'd700;

    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n = 1'b0;
    reg cancel = 1'b0;

    reg pool_job_valid = 1'b0;
    wire pool_job_ready;
    reg [31:0] pool_job_epoch = EPOCH;
    reg [10:0] pool_job_channels = 11'd1;
    reg [9:0] pool_job_height = 10'd1, pool_job_width = 10'd20;
    wire pool_packed_valid;
    reg pool_packed_ready = 1'b1;
    wire [31:0] pool_packed_epoch;
    wire [12:0] pool_packed_address;
    wire [511:0] pool_packed_data;
    wire pool_packed_last, pool_done, pool_error, pool_active;
    wire [3:0] pool_error_code;

    reg feature_cfg_begin = 1'b0;
    wire feature_cfg_begin_ready;
    reg feature_cfg_canonical_order = 1'b1;
    reg feature_load_bank = 1'b0, compute_source_bank = 1'b0;
    wire feature_load_store_valid, feature_load_loading;
    wire [31:0] feature_load_active_epoch;
    reg [31:0] feature_cfg_epoch = EPOCH;
    reg [10:0] feature_cfg_channels = 11'd1;
    reg [9:0] feature_cfg_height = 10'd1, feature_cfg_width = 10'd60;
    reg [31:0] feature_cfg_word_epoch = EPOCH;
    reg [12:0] feature_cfg_word_address = 13'd0;
    reg feature_cfg_word_last = 1'b0;
    reg feature_cfg_word_valid = 1'b0;
    wire feature_cfg_word_ready;
    reg [511:0] feature_cfg_data = 512'd0;
    reg feature_cfg_commit = 1'b0;
    wire feature_cfg_commit_ready;
    wire feature_store_valid, feature_loading;
    wire [31:0] feature_active_epoch;
    wire feature_error_valid;
    wire [3:0] feature_error_code;

    reg window_valid = 1'b0;
    wire window_ready;
    reg [31:0] window_epoch = EPOCH, window_tag = 32'd0;
    reg [13:0] window_row_address = 14'd0;
    reg signed [11:0] window_first_x = 12'sd0;
    reg [10:0] window_input_width = 11'd60;
    reg [10:0] window_output_remaining = 11'd60;
    reg [4:0] window_sites = 5'd20;
    reg [3:0] window_channel_mask = 4'b0001;
    reg window_stride_two = 1'b0, window_y_valid = 1'b1;

    reg mac_cfg_begin = 1'b0;
    wire mac_cfg_begin_ready;
    reg [31:0] mac_cfg_epoch = EPOCH;
    reg [10:0] mac_cfg_groups = 11'd1;
    reg mac_cfg_weight_valid = 1'b0;
    wire mac_cfg_weight_ready;
    reg [1023:0] mac_cfg_weights = 1024'd0;
    reg mac_cfg_bias_valid = 1'b0;
    wire mac_cfg_bias_ready;
    reg [1023:0] mac_cfg_bias = 1024'd0;
    reg mac_cfg_commit = 1'b0;
    wire mac_cfg_commit_ready;
    wire mac_weights_valid;
    wire [31:0] mac_weights_epoch;
    wire mac_error_valid;
    wire [2:0] mac_error_code;

    reg run_valid = 1'b0;
    wire run_ready;
    reg [31:0] run_epoch = EPOCH, run_token = TOKEN_BASE;
    reg [5:0] run_lanes = 6'd16;
    reg [4:0] run_sites = 5'd20;
    wire stream_valid, stream_ready;
    wire [31:0] stream_token;
    wire stream_last;
    wire [639:0] stream_data;
    wire [31:0] response_tag;
    wire [79:0] response_mask;

    reg req_cfg_begin = 1'b0;
    wire req_cfg_begin_ready;
    reg [31:0] req_cfg_epoch = EPOCH;
    reg [5:0] req_cfg_lanes = 6'd16;
    reg req_cfg_word_valid = 1'b0;
    wire req_cfg_word_ready;
    reg [30:0] req_cfg_multiplier = 31'd1;
    reg [5:0] req_cfg_shift = 6'd0;
    reg req_cfg_commit = 1'b0;
    wire req_cfg_commit_ready, req_cfg_error, req_input_error;

    reg unary_cfg_begin = 1'b0;
    wire unary_cfg_begin_ready;
    reg [31:0] unary_cfg_epoch = EPOCH;
    reg unary_cfg_word_valid = 1'b0;
    wire unary_cfg_word_ready;
    reg [7:0] unary_cfg_data = 8'd0;
    reg unary_cfg_commit = 1'b0;
    wire unary_cfg_commit_ready;
    wire unary_error_valid;
    wire [2:0] unary_error_code;
    wire unary_store_valid;
    wire [31:0] unary_active_epoch;
    wire unary_loading;

    wire raw_valid, raw_ready;
    wire [31:0] raw_token;
    wire [4:0] raw_site;
    wire raw_last;
    wire [5:0] raw_lanes;
    wire [1023:0] raw_data;
    wire [31:0] raw_overflow;

    wire post_valid, post_ready;
    wire [31:0] post_epoch, post_token;
    wire [4:0] post_site;
    wire [5:0] post_lanes;
    wire post_last;
    wire [255:0] post_data;
    wire metadata_error;

    reg pack_cfg_valid = 1'b0;
    wire pack_cfg_ready;
    reg [31:0] pack_cfg_epoch = EPOCH;
    reg [10:0] pack_cfg_channels = 11'd16;
    reg [9:0] pack_cfg_height = 10'd1, pack_cfg_width = 10'd60;
    reg [31:0] pack_cfg_token_base = TOKEN_BASE;
    wire packed_valid;
    reg packed_ready = 1'b0;
    wire [31:0] packed_epoch;
    wire [12:0] packed_address;
    wire [511:0] packed_data;
    wire packed_last, pack_done, pack_error_valid;
    wire [2:0] pack_error_code;
    wire pack_active;

    z100_native_row20_shared_pool_address_shared_local_control_v12 #(
        .SITES(20), .SITE_FIFO_DEPTH(4)
    ) dut (.*);

    integer feature_loads = 0;
    integer feature_words = 0;
    integer pending_cancel_count = 0;
    integer pending_reset_count = 0;
    integer pending_stage_checks = 0;
    integer inactive_bank_begin_count = 0;
    integer bad_geometry_e4_count = 0;
    integer mutated_valid_commit_count = 0;
    integer post_beats = 0;
    integer post_stall_cycles = 0;
    integer post_stall_stability_checks = 0;
    integer packed_beats = 0;
    integer packed_stall_cycles = 0;
    integer packed_stall_stability_checks = 0;
    integer pack_error_count = 0;
    integer early_run_count = 0;
    integer pack_done_count = 0;
    integer cycle_count = 0;

    reg previous_post_stall = 1'b0;
    reg [331:0] held_post;
    reg previous_packed_stall = 1'b0;
    reg [557:0] held_packed;

    function automatic [511:0] expected_packed_word(input integer output_index);
        integer expected_address;
        integer expected_group4;
        integer expected_xword;
        integer output_byte;
        integer output_lane;
        integer output_x;
        reg [511:0] result;
        begin
            // Four xwords, four channel subgroups, subgroup-major drain order.
            expected_address = ((output_index % 4) * 4) + (output_index / 4);
            expected_group4 = expected_address / 4;
            expected_xword = expected_address % 4;
            result = 512'd0;
            for (output_byte = 0; output_byte < 64; output_byte = output_byte + 1) begin
                output_lane = output_byte / 16;
                output_x = output_byte % 16;
                if (expected_group4 == 0 && output_lane == 0 &&
                    (expected_xword * 16 + output_x) < 60)
                    result[output_byte*8 +: 8] = 8'd8;
            end
            expected_packed_word = result;
        end
    endfunction

    task automatic tick;
        begin @(posedge clk); #1; end
    endtask

    task automatic load_feature_store;
        integer word_index;
        integer byte_index;
        integer global_x;
        begin
            feature_load_bank = 1'b0;
            feature_cfg_canonical_order = 1'b1;
            feature_cfg_epoch = EPOCH;
            feature_cfg_channels = 11'd1;
            feature_cfg_height = 10'd1;
            feature_cfg_width = 10'd60;
            feature_cfg_word_epoch = EPOCH;
            @(negedge clk);
            feature_cfg_begin = 1'b1;
            #1;
            if (!feature_cfg_begin_ready)
                $fatal(1, "STAGED_CORE_CONTROL feature begin not ready");
            @(posedge clk); #1;
            @(negedge clk); feature_cfg_begin = 1'b0; feature_cfg_word_valid = 1'b1;
            for (word_index = 0; word_index < 4; word_index = word_index + 1) begin
                feature_cfg_word_address = word_index[12:0];
                feature_cfg_word_last = (word_index == 3);
                feature_cfg_data = 512'd0;
                for (byte_index = 0; byte_index < 16; byte_index = byte_index + 1) begin
                    global_x = word_index * 16 + byte_index;
                    if (global_x < 60)
                        feature_cfg_data[byte_index*8 +: 8] = 8'd1;
                end
                #1;
                if (!feature_cfg_word_ready)
                    $fatal(1, "STAGED_CORE_CONTROL feature word %0d not ready", word_index);
                @(posedge clk); #1;
                if (feature_error_valid)
                    $fatal(1, "STAGED_CORE_CONTROL feature load error code=%0d", feature_error_code);
                feature_words = feature_words + 1;
                @(negedge clk);
            end
            feature_cfg_word_valid = 1'b0;
            feature_cfg_commit = 1'b1;
            #1;
            if (!feature_cfg_commit_ready)
                $fatal(1, "STAGED_CORE_CONTROL feature commit not ready");
            @(posedge clk); #1;
            if (!feature_store_valid || feature_active_epoch != EPOCH || feature_loading)
                $fatal(1, "STAGED_CORE_CONTROL feature store did not commit");
            @(negedge clk); feature_cfg_commit = 1'b0;
            feature_loads = feature_loads + 1;
        end
    endtask

    task automatic start_pending_valid_cfg;
        begin
            pack_cfg_epoch = EPOCH;
            pack_cfg_channels = 11'd16;
            pack_cfg_height = 10'd1;
            pack_cfg_width = 10'd60;
            pack_cfg_token_base = TOKEN_BASE;
            pack_cfg_valid = 1'b1;
            #1;
            if (!pack_cfg_ready)
                $fatal(1, "STAGED_CORE_CONTROL pending cfg E0 not admitted");
            @(posedge clk); #1;
            if (!dut.conv_owned || !dut.output_packer.cfg_pending || pack_active || pack_error_valid)
                $fatal(1, "STAGED_CORE_CONTROL E0 did not latch actual owner/pending state");
            @(negedge clk);
            pack_cfg_valid = 1'b0;
            // Deliberately poison live values; the staged transaction owns E0.
            pack_cfg_epoch = 32'd0;
            pack_cfg_channels = 11'd0;
            pack_cfg_height = 10'd0;
            pack_cfg_width = 10'd0;
            pack_cfg_token_base = 32'd0;
        end
    endtask

    task automatic check_pending_stage(input integer target_stage);
        begin
            if (!dut.conv_owned || !dut.output_packer.cfg_pending ||
                dut.output_packer.cfg_stage !== target_stage[2:0] ||
                pack_active || pack_error_valid || pack_done ||
                dut.output_packer.in_ready || pack_cfg_ready)
                $fatal(1, "STAGED_CORE_CONTROL pending stage mismatch target=%0d stage=%0d owner=%0b pending=%0b active=%0b in_ready=%0b",
                       target_stage, dut.output_packer.cfg_stage, dut.conv_owned,
                       dut.output_packer.cfg_pending, pack_active, dut.output_packer.in_ready);
            pending_stage_checks = pending_stage_checks + 1;
        end
    endtask

    task automatic probe_owner_exclusions(input integer allow_inactive_begin);
        begin
            pool_job_valid = 1'b1;
            #1;
            if (pool_job_ready)
                $fatal(1, "STAGED_CORE_CONTROL pool stole pending Conv ownership");
            pool_job_valid = 1'b0;

            feature_load_bank = 1'b0;
            feature_cfg_epoch = EPOCH + 1;
            feature_cfg_channels = 11'd1;
            feature_cfg_height = 10'd1;
            feature_cfg_width = 10'd20;
            feature_cfg_begin = 1'b1;
            #1;
            if (feature_cfg_begin_ready)
                $fatal(1, "STAGED_CORE_CONTROL active source bank reconfigured while owned");
            feature_cfg_begin = 1'b0;

            if (allow_inactive_begin != 0) begin
                feature_load_bank = 1'b1;
                feature_cfg_begin = 1'b1;
                #1;
                if (!feature_cfg_begin_ready)
                    $fatal(1, "STAGED_CORE_CONTROL inactive bank begin unexpectedly blocked");
                @(posedge clk); #1;
                if (!feature_load_loading)
                    $fatal(1, "STAGED_CORE_CONTROL inactive bank load did not acquire real load owner");
                @(negedge clk); feature_cfg_begin = 1'b0;
                inactive_bank_begin_count = inactive_bank_begin_count + 1;
            end
            feature_load_bank = 1'b0;
        end
    endtask

    task automatic abort_pending_at_stage(input integer target_stage, input integer use_reset);
        begin
            load_feature_store();
            @(negedge clk);
            start_pending_valid_cfg();
            check_pending_stage(1);
            probe_owner_exclusions(target_stage == 2);

            while (dut.output_packer.cfg_stage != target_stage[2:0]) begin
                @(posedge clk); #1;
                @(negedge clk);
            end
            check_pending_stage(target_stage);

            if (use_reset != 0) begin
                rst_n = 1'b0;
                repeat (2) begin @(posedge clk); #1; end
                if (dut.conv_owned || dut.output_packer.cfg_pending || pack_active ||
                    feature_store_valid || pack_error_valid || pack_done)
                    $fatal(1, "STAGED_CORE_CONTROL reset failed to clear stage %0d", target_stage);
                @(negedge clk); rst_n = 1'b1;
                pending_reset_count = pending_reset_count + 1;
            end else begin
                cancel = 1'b1;
                @(posedge clk); #1;
                if (dut.conv_owned || dut.output_packer.cfg_pending || pack_active ||
                    feature_store_valid || pack_error_valid || pack_done)
                    $fatal(1, "STAGED_CORE_CONTROL cancel failed to clear stage %0d", target_stage);
                @(negedge clk); cancel = 1'b0;
                pending_cancel_count = pending_cancel_count + 1;
            end
        end
    endtask

    task automatic test_bad_geometry_e4_owner_hold;
        integer stage_index;
        begin
            load_feature_store();
            @(negedge clk);
            pack_cfg_epoch = EPOCH;
            pack_cfg_channels = 11'd0;
            pack_cfg_height = 10'd1;
            pack_cfg_width = 10'd60;
            pack_cfg_token_base = TOKEN_BASE;
            pack_cfg_valid = 1'b1;
            #1;
            if (!pack_cfg_ready)
                $fatal(1, "STAGED_CORE_CONTROL bad geometry E0 not admitted by wrapper");
            @(posedge clk); #1;
            if (!dut.conv_owned || !dut.output_packer.cfg_pending || pack_error_valid || pack_done)
                $fatal(1, "STAGED_CORE_CONTROL bad geometry did not enter pending state");
            @(negedge clk);
            pack_cfg_valid = 1'b0;
            // A valid live geometry after E0 must not repair the captured C=0.
            pack_cfg_channels = 11'd16;
            pack_cfg_height = 10'd1;
            pack_cfg_width = 10'd60;
            pack_cfg_token_base = TOKEN_BASE + 32'd99;
            for (stage_index = 1; stage_index <= 3; stage_index = stage_index + 1) begin
                if (dut.output_packer.cfg_stage !== stage_index[2:0])
                    $fatal(1, "STAGED_CORE_CONTROL expected pending stage %0d", stage_index);
                if (pack_error_valid || pack_done || pack_active || !dut.conv_owned)
                    $fatal(1, "STAGED_CORE_CONTROL early error/retirement before E4");
                @(posedge clk); #1;
                @(negedge clk);
            end
            if (dut.output_packer.cfg_stage !== 3'd4 || pack_error_valid || pack_active)
                $fatal(1, "STAGED_CORE_CONTROL missing E4 pre-edge state");
            @(posedge clk); #1;
            if (!pack_error_valid || pack_error_code != 3'd1 || pack_done || pack_active ||
                !dut.conv_owned || dut.output_packer.cfg_pending)
                $fatal(1, "STAGED_CORE_CONTROL E4 geometry error/owner contract mismatch");
            bad_geometry_e4_count = bad_geometry_e4_count + 1;

            @(negedge clk);
            pool_job_valid = 1'b1;
            #1;
            if (pool_job_ready)
                $fatal(1, "STAGED_CORE_CONTROL pool stole owner after E4 error");
            pool_job_valid = 1'b0;
            feature_load_bank = 1'b0;
            feature_cfg_begin = 1'b1;
            #1;
            if (feature_cfg_begin_ready)
                $fatal(1, "STAGED_CORE_CONTROL source bank unlocked after E4 error");
            feature_cfg_begin = 1'b0;
            if (!dut.conv_owned || pack_done)
                $fatal(1, "STAGED_CORE_CONTROL owner released without done/cancel");
            // Let the registered E4 error pulse retire while checking that
            // ownership remains held for a normal non-cancel cycle.
            @(posedge clk); #1;
            if (pack_error_valid || !dut.conv_owned || pack_done)
                $fatal(1, "STAGED_CORE_CONTROL E4 error pulse/owner retirement mismatch");
            @(negedge clk);
            cancel = 1'b1;
            @(posedge clk); #1;
            if (dut.conv_owned || pack_error_valid || pack_done || feature_store_valid)
                $fatal(1, "STAGED_CORE_CONTROL explicit cancel did not retire bad-config owner");
            @(negedge clk); cancel = 1'b0;
        end
    endtask

    task automatic configure_mac;
        begin
            mac_cfg_epoch = EPOCH;
            mac_cfg_groups = 11'd1;
            @(negedge clk); mac_cfg_begin = 1'b1; #1;
            if (!mac_cfg_begin_ready)
                $fatal(1, "STAGED_CORE_CONTROL MAC begin not ready");
            @(posedge clk); #1;
            @(negedge clk);
            mac_cfg_begin = 1'b0;
            mac_cfg_weights = 1024'd0;
            mac_cfg_weights[7:0] = 8'd1;
            mac_cfg_bias = 1024'd0;
            mac_cfg_bias[31:0] = 32'd7;
            mac_cfg_weight_valid = 1'b1;
            mac_cfg_bias_valid = 1'b1;
            #1;
            if (!mac_cfg_weight_ready || !mac_cfg_bias_ready)
                $fatal(1, "STAGED_CORE_CONTROL MAC data not ready");
            @(posedge clk); #1;
            @(negedge clk);
            mac_cfg_weight_valid = 1'b0;
            mac_cfg_bias_valid = 1'b0;
            mac_cfg_commit = 1'b1;
            #1;
            if (!mac_cfg_commit_ready)
                $fatal(1, "STAGED_CORE_CONTROL MAC commit not ready");
            @(posedge clk); #1;
            @(negedge clk); mac_cfg_commit = 1'b0;
            if (!mac_weights_valid || mac_weights_epoch != EPOCH || mac_error_valid)
                $fatal(1, "STAGED_CORE_CONTROL MAC parameters did not commit");
        end
    endtask

    task automatic configure_requant;
        integer lane;
        begin
            req_cfg_epoch = EPOCH;
            req_cfg_lanes = 6'd16;
            @(negedge clk); req_cfg_begin = 1'b1; #1;
            if (!req_cfg_begin_ready)
                $fatal(1, "STAGED_CORE_CONTROL requant begin not ready");
            @(posedge clk); #1;
            @(negedge clk);
            req_cfg_begin = 1'b0;
            req_cfg_word_valid = 1'b1;
            req_cfg_multiplier = 31'd1;
            req_cfg_shift = 6'd0;
            for (lane = 0; lane < 16; lane = lane + 1) begin
                #1;
                if (!req_cfg_word_ready)
                    $fatal(1, "STAGED_CORE_CONTROL requant factor %0d not ready", lane);
                @(posedge clk); #1;
                if (req_cfg_error)
                    $fatal(1, "STAGED_CORE_CONTROL requant config error while loading");
                @(negedge clk);
            end
            req_cfg_word_valid = 1'b0;
            req_cfg_commit = 1'b1;
            #1;
            if (!req_cfg_commit_ready)
                $fatal(1, "STAGED_CORE_CONTROL requant commit not ready");
            @(posedge clk); #1;
            @(negedge clk); req_cfg_commit = 1'b0;
            if (req_cfg_error || req_input_error)
                $fatal(1, "STAGED_CORE_CONTROL requant config did not commit cleanly");
        end
    endtask

    task automatic configure_unary;
        integer byte_index;
        begin
            unary_cfg_epoch = EPOCH;
            @(negedge clk); unary_cfg_begin = 1'b1; #1;
            if (!unary_cfg_begin_ready)
                $fatal(1, "STAGED_CORE_CONTROL unary begin not ready");
            @(posedge clk); #1;
            @(negedge clk);
            unary_cfg_begin = 1'b0;
            unary_cfg_word_valid = 1'b1;
            for (byte_index = 0; byte_index < 256; byte_index = byte_index + 1) begin
                unary_cfg_data = byte_index[7:0] ^ 8'h80;
                #1;
                if (!unary_cfg_word_ready)
                    $fatal(1, "STAGED_CORE_CONTROL unary byte %0d not ready", byte_index);
                @(posedge clk); #1;
                if (unary_error_valid)
                    $fatal(1, "STAGED_CORE_CONTROL unary config error while loading");
                @(negedge clk);
            end
            unary_cfg_word_valid = 1'b0;
            unary_cfg_commit = 1'b1;
            #1;
            if (!unary_cfg_commit_ready)
                $fatal(1, "STAGED_CORE_CONTROL unary commit not ready");
            @(posedge clk); #1;
            @(negedge clk); unary_cfg_commit = 1'b0;
            if (!unary_store_valid || unary_active_epoch != EPOCH || unary_error_valid)
                $fatal(1, "STAGED_CORE_CONTROL unary table did not commit");
        end
    endtask

    task automatic commit_mutated_valid_pack_cfg;
        integer stage_index;
        begin
            pack_cfg_epoch = EPOCH;
            pack_cfg_channels = 11'd16;
            pack_cfg_height = 10'd1;
            pack_cfg_width = 10'd60;
            pack_cfg_token_base = TOKEN_BASE;
            pack_cfg_valid = 1'b1;
            #1;
            if (!pack_cfg_ready)
                $fatal(1, "STAGED_CORE_CONTROL valid pack cfg E0 not admitted");
            @(posedge clk); #1;
            if (!dut.conv_owned || !dut.output_packer.cfg_pending || pack_active)
                $fatal(1, "STAGED_CORE_CONTROL valid pack cfg did not enter pending state");
            @(negedge clk);
            pack_cfg_valid = 1'b0;
            pack_cfg_epoch = 32'd0;
            pack_cfg_channels = 11'd0;
            pack_cfg_height = 10'd0;
            pack_cfg_width = 10'd0;
            pack_cfg_token_base = 32'd0;
            if (dut.output_packer.cfg_stage !== 3'd1)
                $fatal(1, "STAGED_CORE_CONTROL valid cfg did not start at E1");
            for (stage_index = 1; stage_index <= 3; stage_index = stage_index + 1) begin
                if (dut.output_packer.cfg_stage !== stage_index[2:0] ||
                    !dut.output_packer.cfg_pending || pack_active ||
                    dut.output_packer.in_ready || packed_valid || pack_done || pack_error_valid)
                    $fatal(1, "STAGED_CORE_CONTROL unexpected pre-E4 behavior at E%0d", stage_index);
                if (stage_index == 1) begin
                    // The real wrapper admits a MAC run after ownership E0,
                    // even while the output packer is still validating cfg.
                    run_epoch = EPOCH;
                    run_token = TOKEN_BASE;
                    run_lanes = 6'd16;
                    run_sites = 5'd20;
                    run_valid = 1'b1;
                    #1;
                    if (!run_ready || pack_active || post_ready)
                        $fatal(1, "STAGED_CORE_CONTROL early run not admitted under pending backpressure");
                end
                @(posedge clk); #1;
                if (stage_index == 1) early_run_count = early_run_count + 1;
                @(negedge clk);
                if (stage_index == 1) run_valid = 1'b0;
            end
            if (dut.output_packer.cfg_stage !== 3'd4 || !dut.output_packer.cfg_pending ||
                pack_active || dut.output_packer.in_ready || pack_error_valid)
                $fatal(1, "STAGED_CORE_CONTROL valid cfg missing E4 pre-edge stage");
            @(posedge clk); #1;
            if (pack_error_valid || !pack_active || dut.output_packer.cfg_pending ||
                !dut.output_packer.in_ready || !dut.conv_owned || pack_done ||
                dut.output_packer.epoch_q !== EPOCH ||
                dut.output_packer.token_q !== TOKEN_BASE ||
                dut.output_packer.channels_q !== 11'd16 ||
                dut.output_packer.height_q !== 10'd1 ||
                dut.output_packer.width_q !== 10'd60)
                $fatal(1, "STAGED_CORE_CONTROL captured valid E0 fields failed at E4/E5");
            mutated_valid_commit_count = mutated_valid_commit_count + 1;
        end
    endtask

    task automatic send_one_run(input integer run_index);
        integer guard;
        reg stream_handshake_seen;
        begin
            @(negedge clk);
            run_epoch = EPOCH;
            run_token = TOKEN_BASE + run_index;
            run_lanes = 6'd16;
            run_sites = 5'd20;
            run_valid = !((run_index == 0) && (early_run_count == 1));
            guard = 0;
            #1;
            while (run_valid && !run_ready) begin
                @(posedge clk); #1; guard = guard + 1;
                if (guard > 20000)
                    $fatal(1, "STAGED_CORE_CONTROL run %0d admission timeout", run_index);
                @(negedge clk); #1;
            end
            if (run_valid) begin
                @(posedge clk); #1;
                @(negedge clk); run_valid = 1'b0;
            end

            window_epoch = EPOCH;
            window_tag = 32'h77000000 + run_index;
            window_row_address = 14'd0;
            window_first_x = run_index * 20;
            window_input_width = 11'd60;
            window_output_remaining = 60 - (run_index * 20);
            window_sites = 5'd20;
            window_channel_mask = 4'b0001;
            window_stride_two = 1'b0;
            window_y_valid = 1'b1;
            window_valid = 1'b1;
            guard = 0;
            #1;
            while (!window_ready) begin
                @(posedge clk); #1; guard = guard + 1;
                if (guard > 20000)
                    $fatal(1, "STAGED_CORE_CONTROL run %0d window admission timeout", run_index);
                @(negedge clk); #1;
            end
            @(posedge clk); #1;
            @(negedge clk); window_valid = 1'b0;

            guard = 0;
            stream_handshake_seen = 1'b0;
            while (!stream_handshake_seen) begin
                @(posedge clk);
                if (stream_valid && stream_ready) begin
                    if (stream_token != TOKEN_BASE + run_index || !stream_last)
                        $fatal(1, "STAGED_CORE_CONTROL actual feature/MAC handshake metadata run=%0d", run_index);
                    stream_handshake_seen = 1'b1;
                end
                #1; guard = guard + 1;
                if (guard > 20000)
                    $fatal(1, "STAGED_CORE_CONTROL run %0d feature response timeout", run_index);
            end
            // Keep the public run token stable through this run's final post
            // handshake, matching the existing full-pipeline transaction rule.
            guard = 0;
            while (post_beats < ((run_index + 1) * 20)) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 20000)
                    $fatal(1, "STAGED_CORE_CONTROL run %0d post retirement timeout", run_index);
            end
            @(negedge clk);
        end
    endtask

    task automatic hold_until_natural_packer_backpressure;
        integer guard;
        begin
            guard = 0;
            while (post_stall_cycles < 4) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 20000)
                    $fatal(1, "STAGED_CORE_CONTROL did not reach real post backpressure");
            end
            #1;
            if (!packed_valid || packed_ready || !post_valid || post_ready ||
                dut.output_packer.buffer_full !== 2'b11 || dut.side_count == 0)
                $fatal(1, "STAGED_CORE_CONTROL backpressure did not retain actual data/side metadata");
            repeat (4) @(posedge clk);
            #1;
            @(negedge clk); packed_ready = 1'b1;
        end
    endtask

    integer final_wait;
    integer run_number;
    initial begin
        repeat (5) tick();
        @(negedge clk); rst_n = 1'b1;

        // Cover cancellation/reset at each staged edge. Each abort invalidates
        // the actual feature store, so every case begins with a fresh load.
        abort_pending_at_stage(1, 0);
        abort_pending_at_stage(2, 1);
        abort_pending_at_stage(3, 0);
        abort_pending_at_stage(4, 1);

        // A bad E0 snapshot must fail at E4, emit no done, and retain the real
        // wrapper owner until explicit cancellation.
        test_bad_geometry_e4_owner_hold();

        // Recover with a fresh legal bank and legal parameters, then drive a
        // nonzero transaction through the real MAC->requant->unary->packer path.
        load_feature_store();
        configure_mac();
        configure_requant();
        configure_unary();
        if (!feature_store_valid || !mac_weights_valid || !unary_store_valid ||
            feature_active_epoch != EPOCH || mac_weights_epoch != EPOCH ||
            unary_active_epoch != EPOCH)
            $fatal(1, "STAGED_CORE_CONTROL runtime fixture not resident");

        packed_ready = 1'b0;
        commit_mutated_valid_pack_cfg();
        fork
            begin
                for (run_number = 0; run_number < 3; run_number = run_number + 1)
                    send_one_run(run_number);
            end
            begin
                hold_until_natural_packer_backpressure();
            end
        join

        final_wait = 0;
        while (pack_done_count == 0) begin
            tick(); final_wait = final_wait + 1;
            if (final_wait > 20000)
                $fatal(1, "STAGED_CORE_CONTROL pack completion timeout");
        end
        tick();
        if (post_beats != 60 || post_stall_cycles < 4 ||
            post_stall_stability_checks < 3 || packed_beats != 16 ||
            packed_stall_cycles < 4 || packed_stall_stability_checks < 3 ||
            pack_done_count != 1 || pack_error_count != 1 ||
            pack_active || packed_valid || dut.conv_owned || metadata_error ||
            feature_error_valid || mac_error_valid || req_cfg_error || req_input_error ||
            unary_error_valid)
            $fatal(1, "STAGED_CORE_CONTROL non-vacuous coverage incomplete post=%0d post_stall=%0d post_hold=%0d packed=%0d packed_stall=%0d packed_hold=%0d done=%0d errors=%0d owner=%0b",
                   post_beats, post_stall_cycles, post_stall_stability_checks,
                   packed_beats, packed_stall_cycles, packed_stall_stability_checks,
                   pack_done_count, pack_error_count, dut.conv_owned);
        if (pending_cancel_count != 2 || pending_reset_count != 2 ||
            pending_stage_checks != 8 || inactive_bank_begin_count != 1 ||
            bad_geometry_e4_count != 1 || mutated_valid_commit_count != 1 || early_run_count != 1 ||
            feature_words != feature_loads * 4)
            $fatal(1, "STAGED_CORE_CONTROL control coverage incomplete cancel=%0d reset=%0d stage_checks=%0d inactive=%0d bad_e4=%0d mutated_commit=%0d loads=%0d words=%0d",
                   pending_cancel_count, pending_reset_count, pending_stage_checks,
                   inactive_bank_begin_count, bad_geometry_e4_count,
                   mutated_valid_commit_count, feature_loads, feature_words);

        $display("STAGED_CORE_CONTROL_COUNTS feature_loads=%0d feature_words=%0d pending_cancel=%0d pending_reset=%0d pending_stage_checks=%0d inactive_bank_begin=%0d bad_geometry_e4=%0d mutated_valid_commit=%0d post_beats=%0d post_stall=%0d post_hold_checks=%0d packed_beats=%0d packed_stall=%0d packed_hold_checks=%0d pack_errors=%0d pack_done=%0d",
                 feature_loads, feature_words, pending_cancel_count, pending_reset_count,
                 pending_stage_checks, inactive_bank_begin_count, bad_geometry_e4_count,
                 mutated_valid_commit_count, post_beats, post_stall_cycles,
                 post_stall_stability_checks, packed_beats, packed_stall_cycles,
                 packed_stall_stability_checks, pack_error_count, pack_done_count);
        $display("STAGED_CORE_CONTROL_PASS real_v12_wrapper=1 forced_internal_signals=0 early_run=1");
        $finish;
    end

    always @(posedge clk) begin
        if (rst_n && !cancel) begin
            cycle_count = cycle_count + 1;
            if (cycle_count > 200000)
                $fatal(1, "STAGED_CORE_CONTROL watchdog");

            if (feature_error_valid || mac_error_valid || req_cfg_error || req_input_error ||
                unary_error_valid || metadata_error)
                $fatal(1, "STAGED_CORE_CONTROL unexpected core error feature=%0b mac=%0b req_cfg=%0b req_input=%0b unary=%0b metadata=%0b",
                       feature_error_valid, mac_error_valid, req_cfg_error,
                       req_input_error, unary_error_valid, metadata_error);
            if (pack_error_valid) pack_error_count = pack_error_count + 1;
            if (pack_done) pack_done_count = pack_done_count + 1;

            if (previous_post_stall) begin
                if (!post_valid ||
                    {post_epoch,post_token,post_site,post_lanes,post_last,post_data} !== held_post)
                    $fatal(1, "STAGED_CORE_CONTROL post data/side metadata changed under packer backpressure");
                post_stall_stability_checks = post_stall_stability_checks + 1;
            end
            previous_post_stall = post_valid && !post_ready;
            if (previous_post_stall) begin
                held_post = {post_epoch,post_token,post_site,post_lanes,post_last,post_data};
                post_stall_cycles = post_stall_cycles + 1;
            end

            if (post_valid && post_ready) begin
                reg [255:0] expected_post;
                integer byte_lane;
                expected_post = 256'd0;
                expected_post[7:0] = 8'd8;
                if (post_beats >= 60 || post_epoch !== EPOCH ||
                    post_token !== TOKEN_BASE + (post_beats / 20) ||
                    post_site !== (post_beats % 20) || post_lanes !== 6'd16 ||
                    post_last !== ((post_beats % 20) == 19) || post_data !== expected_post)
                    $fatal(1, "STAGED_CORE_CONTROL post metadata/data mismatch beat=%0d token=%0d site=%0d lanes=%0d last=%0b",
                           post_beats, post_token, post_site, post_lanes, post_last);
                for (byte_lane = 0; byte_lane < 32; byte_lane = byte_lane + 1)
                    if (post_data[byte_lane*8 +: 8] !== (byte_lane == 0 ? 8'd8 : 8'd0))
                        $fatal(1, "STAGED_CORE_CONTROL post lane %0d mismatch", byte_lane);
                post_beats = post_beats + 1;
            end

            if (previous_packed_stall) begin
                if (!packed_valid ||
                    {packed_epoch,packed_address,packed_data,packed_last} !== held_packed)
                    $fatal(1, "STAGED_CORE_CONTROL packed output changed while consumer stalled");
                packed_stall_stability_checks = packed_stall_stability_checks + 1;
            end
            previous_packed_stall = packed_valid && !packed_ready;
            if (previous_packed_stall) begin
                held_packed = {packed_epoch,packed_address,packed_data,packed_last};
                packed_stall_cycles = packed_stall_cycles + 1;
            end

            if (packed_valid && packed_ready) begin
                if (packed_beats >= 16 || packed_epoch !== EPOCH ||
                    packed_address !== (((packed_beats % 4) * 4) + (packed_beats / 4)) ||
                    packed_data !== expected_packed_word(packed_beats) ||
                    packed_last !== (packed_beats == 15))
                    $fatal(1, "STAGED_CORE_CONTROL packed result mismatch beat=%0d address=%0d last=%0b",
                           packed_beats, packed_address, packed_last);
                packed_beats = packed_beats + 1;
            end
        end else begin
            previous_post_stall = 1'b0;
            previous_packed_stall = 1'b0;
        end
    end

    initial begin
        #10000000;
        $fatal(1, "STAGED_CORE_CONTROL top watchdog");
    end
endmodule

`default_nettype wire
