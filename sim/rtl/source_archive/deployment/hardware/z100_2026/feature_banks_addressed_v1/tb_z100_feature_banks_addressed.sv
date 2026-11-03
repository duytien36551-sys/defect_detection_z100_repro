`timescale 1ns/1ps
`default_nettype none

module tb_z100_feature_banks_addressed;
    localparam integer AW = 13;
    localparam integer MATRIX_CASES = 90;
    localparam integer CASE_COUNT = 91;
    localparam integer MAX_INPUT_WORDS = 160000;
    localparam integer MAX_OUTPUT_WORDS = 16000;
    localparam integer SITES = 4;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;
    reg cancel = 1'b0;

    reg cfg_begin = 1'b0;
    wire cfg_begin_ready;
    reg [31:0] cfg_epoch = 0;
    reg [10:0] cfg_channels = 0;
    reg [9:0] cfg_height = 0;
    reg [9:0] cfg_width = 0;
    wire cfg_word_valid;
    wire cfg_word_ready;
    wire [511:0] cfg_word_data;
    wire [31:0] cfg_word_epoch;
    wire [12:0] cfg_word_address;
    wire cfg_word_last;
    reg cfg_commit = 1'b0;
    wire cfg_commit_ready;
    wire error_valid;
    wire [2:0] error_code;
    wire store_valid;
    wire [31:0] active_epoch;
    wire loading;

    reg req_valid = 1'b0;
    wire req_ready;
    reg [31:0] req_epoch = 0;
    reg [128*AW-1:0] req_addresses = 0;
    reg [127:0] req_mask = 0;
    wire out_valid;
    reg out_ready = 1'b0;
    wire [31:0] out_epoch;
    wire [1023:0] out_data;

    reg pack_cfg_valid = 1'b0;
    wire pack_cfg_ready;
    reg [31:0] pack_cfg_epoch = 0;
    reg [10:0] pack_cfg_channels = 0;
    reg [9:0] pack_cfg_height = 0;
    reg [9:0] pack_cfg_width = 0;
    reg [31:0] pack_cfg_token_base = 0;
    reg in_valid = 1'b0;
    wire in_ready;
    reg [31:0] in_epoch = 0;
    reg [31:0] in_token = 0;
    reg [3:0] in_site = 0;
    reg [5:0] in_lanes = 0;
    reg in_last = 0;
    reg [255:0] in_data = 0;
    wire pack_out_valid;
    wire pack_out_ready;
    wire [31:0] pack_out_epoch;
    wire [12:0] pack_out_address;
    wire [511:0] pack_out_data;
    wire pack_out_last;
    wire pack_done;
    wire pack_error_valid;
    wire [2:0] pack_error_code;
    wire pack_active;
    reg consumer_pause = 1'b0;
    reg manual_word_mode = 1'b0;
    reg manual_word_valid = 1'b0;
    reg [511:0] manual_word_data = 0;
    reg [31:0] manual_word_epoch = 0;
    reg [12:0] manual_word_address = 0;
    reg manual_word_last = 1'b0;

    reg [255:0] case_table [0:CASE_COUNT-1];
    reg [255:0] input_words [0:MAX_INPUT_WORDS-1];
    reg [511:0] expected_words [0:MAX_OUTPUT_WORDS-1];
    reg [1023:0] held_output;

    integer active_case = -1;
    integer current_expected_start = 0;
    integer current_word_count = 0;
    integer stream_seen = 0;
    integer packer_words_seen = 0;
    integer bank_word_accepts = 0;
    integer input_accepts = 0;
    integer feeder_case = -1;
    integer feeder_beat = 0;
    integer input_bubbles = 0;
    integer input_stall_cycles = 0;
    integer input_stability_checks = 0;
    integer output_stall_cycles = 0;
    integer output_stability_checks = 0;
    integer forced_full_cycles = 0;
    integer forced_pause_cycles = 0;
    integer full_buffer_seen = 0;
    integer request_responses = 0;
    integer request_count = 0;
    integer bytes_checked = 0;
    integer error_checks = 0;
    integer errors_by_code [1:7];
    integer recovery_checks = 0;
    integer cfg_cases_completed = 0;
    integer case_number;
    integer lane_number;
    integer address_a;
    integer address_b;
    integer expected_byte;
    integer source_index;
    integer group_index;
    integer row_index;
    integer x_index;
    integer lanes_count;
    integer runs_per_row;
    integer in_token_offset;
    integer input_start;
    integer input_count;
    integer expected_start;
    integer word_count;
    integer epoch_value;
    integer token_value;
    integer channels_value;
    integer height_value;
    integer width_value;
    integer pause_flag;
    integer i;
    integer n;
    integer k;
    integer b;
    integer base_address;
    integer active_lanes;
    integer accepted;
    integer bubble_wait;
    reg [255:0] held_input;
    reg [31:0] held_in_epoch;
    reg [31:0] held_in_token;
    reg [3:0] held_in_site;
    reg [5:0] held_in_lanes;
    reg held_in_last;
    reg input_was_stalled = 1'b0;
    reg monitor_stream = 1'b0;
    reg pause_controller_done = 1'b0;
    reg [511:0] negative_word;

    task automatic phase_note(input [8*40-1:0] phase, input integer case_arg);
        begin
            $display("FEATURE_BANKS_PHASE phase=%0s case=%0d stream=%0d/%0d inputs=%0d words=%0d requests=%0d bank_error=%b/%0d pack_error=%b/%0d",
                     phase, case_arg, stream_seen, current_word_count, input_accepts,
                     packer_words_seen, request_count, error_valid, error_code,
                     pack_error_valid, pack_error_code);
        end
    endtask

    task automatic diagnostic_stall(input [8*48-1:0] phase,
                                    input integer progress_arg,
                                    input integer limit_arg);
        begin
            $display("FEATURE_BANKS_DIAG_STALL phase=%0s progress=%0d limit=%0d case=%0d feeder_case=%0d feeder_beat=%0d inputs=%0d stream=%0d/%0d p_active=%b p_cfg_ready=%b in=%b/%b p_out=%b/%b p_addr=%0d p_last=%b p_err=%b/%0d buffers=%b bank_begin=%b/%b bank_word=%b/%b word_addr=%0d word_epoch=%0d word_last=%b bank_error=%b/%0d loading=%b written=%0d expected=%0d store=%b epoch=%0d commit=%b/%b req=%b/%b req_epoch=%0d req_addr0=%0d req_mask0=%b out=%b/%b out_epoch=%0d pause=%b",
                     phase, progress_arg, limit_arg, active_case, feeder_case,
                     feeder_beat, input_accepts, stream_seen,
                     current_word_count, pack_active, pack_cfg_ready, in_valid, in_ready,
                     pack_out_valid, pack_out_ready, pack_out_address, pack_out_last,
                     pack_error_valid, pack_error_code, dut_packer.buffer_full,
                     cfg_begin, cfg_begin_ready, cfg_word_valid, cfg_word_ready,
                     cfg_word_address, cfg_word_epoch, cfg_word_last, error_valid,
                     error_code, loading, dut_bank.written_words,
                     dut_bank.expected_words, store_valid, active_epoch, cfg_commit,
                     cfg_commit_ready, req_valid, req_ready, req_epoch,
                     req_addresses[0 +: AW], req_mask[0], out_valid, out_ready,
                     out_epoch, consumer_pause);
            $fatal(1, "bounded wait timeout phase=%0s", phase);
        end
    endtask

    z100_feature_banks_addressed dut_bank (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(cfg_begin_ready),
        .cfg_epoch(cfg_epoch), .cfg_channels(cfg_channels),
        .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_word_valid(cfg_word_valid), .cfg_word_ready(cfg_word_ready),
        .cfg_word_data(cfg_word_data), .cfg_word_epoch(cfg_word_epoch),
        .cfg_word_address(cfg_word_address), .cfg_word_last(cfg_word_last),
        .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .error_valid(error_valid), .error_code(error_code),
        .store_valid(store_valid), .active_epoch(active_epoch), .loading(loading),
        .req_valid(req_valid), .req_ready(req_ready), .req_epoch(req_epoch),
        .req_addresses(req_addresses), .req_mask(req_mask),
        .out_valid(out_valid), .out_ready(out_ready), .out_epoch(out_epoch),
        .out_data(out_data)
    );

    wire bank_word_valid = pack_out_valid && !consumer_pause;
    assign pack_out_ready = cfg_word_ready && !consumer_pause;
    assign cfg_word_valid = manual_word_mode ? manual_word_valid : bank_word_valid;
    assign cfg_word_data = manual_word_mode ? manual_word_data : pack_out_data;
    assign cfg_word_epoch = manual_word_mode ? manual_word_epoch : pack_out_epoch;
    assign cfg_word_address = manual_word_mode ? manual_word_address : pack_out_address;
    assign cfg_word_last = manual_word_mode ? manual_word_last : pack_out_last;

    z100_native_output_packer #(.SITES(SITES)) dut_packer (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_valid(pack_cfg_valid), .cfg_ready(pack_cfg_ready),
        .cfg_epoch(pack_cfg_epoch), .cfg_channels(pack_cfg_channels),
        .cfg_height(pack_cfg_height), .cfg_width(pack_cfg_width),
        .cfg_token_base(pack_cfg_token_base),
        .in_valid(in_valid), .in_ready(in_ready), .in_epoch(in_epoch),
        .in_token(in_token), .in_site(in_site), .in_lanes(in_lanes),
        .in_last(in_last), .in_data(in_data),
        .out_valid(pack_out_valid), .out_ready(pack_out_ready),
        .out_epoch(pack_out_epoch), .out_address(pack_out_address),
        .out_data(pack_out_data), .out_last(pack_out_last), .done(pack_done),
        .error_valid(pack_error_valid), .error_code(pack_error_code),
        .active(pack_active)
    );

    task automatic tick;
        begin @(posedge clk); #1; end
    endtask

    task automatic begin_load(input integer epoch_arg, channels_arg,
                              input integer height_arg, width_arg);
        integer waited;
        begin
            @(negedge clk);
            waited = 0;
            while (!cfg_begin_ready) begin
                if (waited >= 1000) diagnostic_stall("manual_cfg_begin_ready", waited, 1000);
                @(negedge clk); waited = waited + 1;
            end
            cfg_epoch = epoch_arg;
            cfg_channels = channels_arg;
            cfg_height = height_arg;
            cfg_width = width_arg;
            cfg_begin = 1'b1;
            tick();
            @(negedge clk);
            cfg_begin = 1'b0;
        end
    endtask

    task automatic send_cfg_word(input integer epoch_arg, address_arg,
                                 input reg [511:0] data_arg, input integer last_arg);
        integer waited;
        begin
            @(negedge clk);
            waited = 0;
            while (!cfg_word_ready) begin
                if (waited >= 1000) diagnostic_stall("manual_cfg_word_ready", waited, 1000);
                @(negedge clk); waited = waited + 1;
            end
            manual_word_epoch = epoch_arg;
            manual_word_address = address_arg;
            manual_word_data = data_arg;
            manual_word_last = last_arg;
            manual_word_valid = 1'b1;
            tick();
            @(negedge clk);
            manual_word_valid = 1'b0;
        end
    endtask

    task automatic expect_error(input integer code_arg);
        begin
            if (!error_valid || error_code != code_arg || store_valid || loading || out_valid)
                $fatal(1, "error mismatch expected=%0d valid=%0d code=%0d store=%0d loading=%0d out=%0d",
                       code_arg, error_valid, error_code, store_valid, loading, out_valid);
            errors_by_code[code_arg] = errors_by_code[code_arg] + 1;
            error_checks = error_checks + 1;
        end
    endtask

    task automatic commit_and_check(input integer epoch_arg);
        integer waited;
        begin
            @(negedge clk);
            waited = 0;
            while (!cfg_commit_ready) begin
                if (waited >= 1000) diagnostic_stall("manual_commit_ready", waited, 1000);
                @(negedge clk); waited = waited + 1;
            end
            cfg_commit = 1'b1;
            tick();
            if (error_valid || !store_valid || active_epoch != epoch_arg || loading)
                $fatal(1, "valid commit failed epoch=%0d error=%0d store=%0d active=%0d",
                       epoch_arg, error_valid, store_valid, active_epoch);
            @(negedge clk);
            cfg_commit = 1'b0;
        end
    endtask

    task automatic issue_one_read(input integer epoch_arg, address_arg,
                                  input integer mask_arg);
        integer waited;
        begin
            @(negedge clk);
            waited = 0;
            while (!req_ready) begin
                if (waited >= 1000) diagnostic_stall("manual_req_ready", waited, 1000);
                @(negedge clk); waited = waited + 1;
            end
            req_epoch = epoch_arg;
            req_addresses = 0;
            req_mask = 0;
            req_addresses[0 +: AW] = address_arg;
            req_mask[0] = mask_arg[0];
            req_valid = 1'b1;
            out_ready = 1'b0;
            tick();
            @(negedge clk);
            req_valid = 1'b0;
        end
    endtask

    task automatic run_error_tests;
        begin
            phase_note("error_tests_begin", -1);
            // Invalid geometry is rejected before creating a load epoch.
            manual_word_mode = 1'b1;
            phase_note("error_bad_config", -1);
            @(negedge clk); cfg_channels = 1025; cfg_height = 1; cfg_width = 1;
            cfg_epoch = 900; cfg_begin = 1'b1; tick(); expect_error(1);
            @(negedge clk); cfg_begin = 1'b0;

            // Early commit, wrong address/duplicate, wrong stream epoch, last,
            // channel tail, and horizontal tail all reject before that write.
            phase_note("error_early_commit", -1);
            begin_load(901, 1, 1, 1);
            @(negedge clk); cfg_commit = 1'b1; tick(); expect_error(5);
            @(negedge clk); cfg_commit = 1'b0;

            phase_note("error_wrong_address", -1);
            begin_load(902, 1, 1, 1);
            negative_word = 0; negative_word[7:0] = 8'h53;
            send_cfg_word(902, 1, negative_word, 1); expect_error(2);

            phase_note("error_wrong_epoch", -1);
            begin_load(903, 1, 1, 1);
            send_cfg_word(904, 0, 0, 1); expect_error(2);

            phase_note("error_bad_last", -1);
            begin_load(905, 1, 1, 1);
            send_cfg_word(905, 0, 0, 0); expect_error(3);

            phase_note("error_channel_padding", -1);
            begin_load(906, 3, 1, 16);
            negative_word = 0; negative_word[48*8 +: 8] = 8'hA7;
            send_cfg_word(906, 0, negative_word, 1); expect_error(4);

            phase_note("error_x_padding", -1);
            begin_load(907, 1, 1, 1);
            negative_word = 0; negative_word[1*8 +: 8] = 8'h19;
            send_cfg_word(907, 0, negative_word, 1); expect_error(4);

            phase_note("error_duplicate_address", -1);
            begin_load(908, 1, 1, 17);
            send_cfg_word(908, 0, 0, 0);
            send_cfg_word(908, 0, 0, 1); expect_error(2);

            phase_note("error_extra_word", -1);
            begin_load(909, 1, 1, 1);
            send_cfg_word(909, 0, 0, 1);
            send_cfg_word(909, 0, 0, 1); expect_error(6);

            // A partial load is invalidated by cancel and reset without RAM
            // clearing; a complete subsequent epoch must overwrite metadata.
            phase_note("error_cancel_recovery", -1);
            begin_load(910, 4, 1, 32);
            send_cfg_word(910, 0, 0, 0);
            @(negedge clk); cancel = 1'b1; tick();
            if (store_valid || loading || out_valid) $fatal(1, "cancel during load retained ownership");
            recovery_checks = recovery_checks + 1;
            @(negedge clk); cancel = 1'b0;

            phase_note("error_reset_recovery", -1);
            begin_load(911, 4, 1, 32);
            send_cfg_word(911, 0, 0, 0);
            @(negedge clk); rst_n = 1'b0; tick();
            if (store_valid || loading || out_valid) $fatal(1, "reset during load retained ownership");
            recovery_checks = recovery_checks + 1;
            @(negedge clk); rst_n = 1'b1;

            phase_note("error_bad_read_epoch", -1);
            begin_load(912, 1, 1, 1);
            send_cfg_word(912, 0, 0, 1);
            commit_and_check(912);
            issue_one_read(911, 0, 1);
            expect_error(7);
            @(negedge clk); out_ready = 1'b0;

            phase_note("error_bad_read_address", -1);
            begin_load(913, 1, 1, 1);
            send_cfg_word(913, 0, 0, 1);
            commit_and_check(913);
            issue_one_read(913, 1, 1);
            expect_error(7);
            @(negedge clk); out_ready = 1'b0;

            // Good recovery epoch plus read-stall ownership blocks reload.
            phase_note("error_stalled_output_recovery", -1);
            begin_load(914, 1, 1, 1);
            send_cfg_word(914, 0, 0, 1);
            commit_and_check(914);
            issue_one_read(914, 0, 1);
            if (!out_valid || out_epoch != 914 || out_data[7:0] !== 8'd0)
                $fatal(1, "valid recovery read mismatch");
            if (cfg_begin_ready) $fatal(1, "reload allowed while response stalled");
            @(negedge clk); out_ready = 1'b1; tick();
            if (out_valid) $fatal(1, "stalled recovery response did not drain");
            @(negedge clk); out_ready = 1'b0;
            recovery_checks = recovery_checks + 1;
        end
    endtask

    task automatic configure_case(input integer case_arg);
        integer waited;
        begin
            @(negedge clk);
            waited = 0;
            while (!pack_cfg_ready || !cfg_begin_ready) begin
                if (waited >= 1000) diagnostic_stall("case_config_ready", waited, 1000);
                @(negedge clk); waited = waited + 1;
            end
            channels_value = case_table[case_arg][10:0];
            height_value = case_table[case_arg][20:11];
            width_value = case_table[case_arg][30:21];
            epoch_value = case_table[case_arg][62:31];
            token_value = case_table[case_arg][94:63];
            input_start = case_table[case_arg][126:95];
            input_count = case_table[case_arg][146:127];
            expected_start = case_table[case_arg][178:147];
            word_count = case_table[case_arg][192:179];
            pause_flag = case_table[case_arg][193];
            active_case = case_arg;
            current_expected_start = expected_start;
            current_word_count = word_count;
            stream_seen = 0;
            pack_cfg_epoch = epoch_value;
            pack_cfg_channels = channels_value;
            pack_cfg_height = height_value;
            pack_cfg_width = width_value;
            pack_cfg_token_base = token_value;
            cfg_epoch = epoch_value;
            cfg_channels = channels_value;
            cfg_height = height_value;
            cfg_width = width_value;
            pack_cfg_valid = 1'b1;
            cfg_begin = 1'b1;
            tick();
            if (!loading || store_valid || !pack_active)
                $fatal(1, "producer/store config ownership failed case=%0d", case_arg);
            @(negedge clk);
            pack_cfg_valid = 1'b0;
            cfg_begin = 1'b0;
        end
    endtask

    task automatic feed_case(input integer case_arg);
        integer beat;
        integer case_input_start;
        integer case_input_count;
        integer case_channels;
        integer case_height;
        integer case_width;
        integer case_epoch;
        integer case_token_base;
        integer group_pixels;
        integer groups32;
        integer xwords_per_row;
        integer site_count;
        integer waited;
        begin
            case_input_start = case_table[case_arg][126:95];
            case_input_count = case_table[case_arg][146:127];
            case_channels = case_table[case_arg][10:0];
            case_height = case_table[case_arg][20:11];
            case_width = case_table[case_arg][30:21];
            case_epoch = case_table[case_arg][62:31];
            case_token_base = case_table[case_arg][94:63];
            group_pixels = case_height * case_width;
            groups32 = (case_channels + 31) / 32;
            xwords_per_row = (case_width + SITES - 1) / SITES;
            feeder_case = case_arg;
            feeder_beat = 0;
            for (beat = 0; beat < case_input_count; beat = beat + 1) begin
                feeder_beat = beat;
                if ((beat % 37) == 19) begin
                    @(negedge clk);
                    in_valid = 1'b0;
                    in_data = 0;
                    @(posedge clk); #1;
                    input_bubbles = input_bubbles + 1;
                end
                group_index = beat / group_pixels;
                source_index = beat % group_pixels;
                row_index = source_index / case_width;
                x_index = source_index % case_width;
                active_lanes = case_channels - group_index * 32;
                if (active_lanes > 32) active_lanes = 32;
                in_token_offset = group_index * case_height * xwords_per_row +
                                  row_index * xwords_per_row + (x_index / SITES);
                site_count = case_width - ((x_index / SITES) * SITES);
                if (site_count > SITES) site_count = SITES;
                @(negedge clk);
                in_epoch = case_epoch;
                in_token = case_token_base + in_token_offset;
                in_site = x_index % SITES;
                in_lanes = active_lanes;
                in_last = ((x_index % SITES) == site_count - 1);
                in_data = input_words[case_input_start + beat];
                in_valid = 1'b1;
                accepted = 0;
                waited = 0;
                while (!accepted) begin
                    @(posedge clk);
                    if (in_ready) begin
                        accepted = 1;
                        input_accepts = input_accepts + 1;
                    end else begin
                        if (waited >= 4000)
                            diagnostic_stall("feed_case_in_ready", beat, case_input_count);
                        waited = waited + 1;
                    end
                end
                @(negedge clk);
                in_valid = 1'b0;
            end
            feeder_beat = case_input_count;
            feeder_case = -1;
        end
    endtask

    task automatic pause_for_two_full_buffers;
        integer held_cycles;
        integer waited;
        reg out_valid_before_settle;
        reg out_valid_after_settle;
        reg input_valid_before_settle;
        reg input_valid_after_settle;
        begin
            held_cycles = 0;
            @(negedge clk);
            waited = 0;
            out_valid_before_settle = pack_out_valid;
            input_valid_before_settle = in_valid;
            #1;
            out_valid_after_settle = pack_out_valid;
            input_valid_after_settle = in_valid;
            $display("FEATURE_BANKS_PAUSE_SAMPLE case=%0d wait=%0d feeder_case=%0d feeder_beat=%0d inputs=%0d out_before=%b out_after=%b in_before=%b in_after=%b token=%0d site=%0d buffers=%b",
                     active_case, waited, feeder_case, feeder_beat, input_accepts,
                     out_valid_before_settle, out_valid_after_settle,
                     input_valid_before_settle, input_valid_after_settle,
                     in_token, in_site, dut_packer.buffer_full);
            while (out_valid_after_settle !== 1'b1) begin
                if (waited >= 2000)
                    diagnostic_stall("pause_wait_pack_out_valid", waited, 2000);
                @(negedge clk); waited = waited + 1;
                out_valid_before_settle = pack_out_valid;
                input_valid_before_settle = in_valid;
                #1;
                out_valid_after_settle = pack_out_valid;
                input_valid_after_settle = in_valid;
                if (out_valid_before_settle !== out_valid_after_settle ||
                    input_valid_before_settle !== input_valid_after_settle)
                    $display("FEATURE_BANKS_PAUSE_SAMPLE case=%0d wait=%0d feeder_case=%0d feeder_beat=%0d inputs=%0d out_before=%b out_after=%b in_before=%b in_after=%b token=%0d site=%0d buffers=%b",
                             active_case, waited, feeder_case, feeder_beat, input_accepts,
                             out_valid_before_settle, out_valid_after_settle,
                             input_valid_before_settle, input_valid_after_settle,
                             in_token, in_site, dut_packer.buffer_full);
            end
            consumer_pause = 1'b1;
            pause_controller_done = 1'b0;
            waited = 0;
            while (dut_packer.buffer_full !== 2'b11) begin
                if (waited >= 2000)
                    diagnostic_stall("pause_wait_both_buffers_full", waited, 2000);
                @(negedge clk); waited = waited + 1;
            end
            full_buffer_seen = full_buffer_seen + 1;
            repeat (8) begin
                @(posedge clk); #1;
                if (dut_packer.buffer_full !== 2'b11 || in_ready)
                    $fatal(1, "forced pause did not hold two full buffers and stall input");
                held_cycles = held_cycles + 1;
            end
            forced_pause_cycles = forced_pause_cycles + held_cycles;
            @(negedge clk);
            consumer_pause = 1'b0;
            pause_controller_done = 1'b1;
        end
    endtask

    task automatic read_all_case(input integer case_arg);
        integer count_arg;
        integer start_arg;
        integer epoch_arg;
        integer pair_addr;
        integer lane;
        integer bank_index;
        integer addr_arg;
        integer active_count;
        integer r;
        integer waited;
        begin
            count_arg = case_table[case_arg][192:179];
            start_arg = case_table[case_arg][178:147];
            epoch_arg = case_table[case_arg][62:31];
            for (pair_addr = 0; pair_addr < count_arg; pair_addr = pair_addr + 2) begin
                @(negedge clk);
                waited = 0;
                while (!req_ready) begin
                    if (waited >= 1000)
                        diagnostic_stall("readback_req_ready", pair_addr, count_arg);
                    @(negedge clk); waited = waited + 1;
                end
                req_epoch = epoch_arg;
                req_addresses = 0;
                req_mask = 0;
                for (bank_index = 0; bank_index < 64; bank_index = bank_index + 1) begin
                    address_a = pair_addr;
                    address_b = pair_addr + 1;
                    req_addresses[(bank_index*2)*AW +: AW] = address_a;
                    req_addresses[(bank_index*2+1)*AW +: AW] = address_b;
                    req_mask[bank_index*2] = (address_a < count_arg);
                    req_mask[bank_index*2+1] = (address_b < count_arg);
                end
                req_valid = 1'b1;
                out_ready = 1'b0;
                tick();
                if (!out_valid || out_epoch != epoch_arg)
                    $fatal(1, "read response metadata mismatch case=%0d addr=%0d", case_arg, pair_addr);
                for (lane = 0; lane < 128; lane = lane + 1) begin
                    bank_index = lane / 2;
                    addr_arg = pair_addr + (lane % 2);
                    if (addr_arg < count_arg)
                        expected_byte = expected_words[start_arg + addr_arg][bank_index*8 +: 8];
                    else
                        expected_byte = 0;
                    if (out_data[lane*8 +: 8] !== expected_byte[7:0])
                        $fatal(1, "readback byte mismatch case=%0d addr=%0d bank=%0d port=%0d got=%02x expected=%02x",
                               case_arg, addr_arg, bank_index, lane%2,
                               out_data[lane*8 +: 8], expected_byte[7:0]);
                end
                request_responses = request_responses + 1;
                request_count = request_count + 1;
                active_count = ((pair_addr + 1) < count_arg) ? 2 : 1;
                bytes_checked = bytes_checked + active_count * 64;
                @(negedge clk);
                req_valid = 1'b0;
                if ((case_arg == 0) && (pair_addr == 0)) begin
                    held_output = out_data;
                    req_addresses = ~req_addresses;
                    req_mask = ~req_mask;
                    repeat (3) begin
                        tick();
                        if (!out_valid || out_epoch != epoch_arg || out_data !== held_output ||
                            req_ready || cfg_begin_ready)
                            $fatal(1, "stalled read output changed or admitted a reload");
                        output_stall_cycles = output_stall_cycles + 1;
                        output_stability_checks = output_stability_checks + 1;
                    end
                    @(negedge clk); out_ready = 1'b1;
                    tick();
                    if (out_valid) $fatal(1, "stalled read response did not drain");
                    @(negedge clk); out_ready = 1'b0;
                end else begin
                    out_ready = 1'b1;
                    tick();
                    if (out_valid) $fatal(1, "read response did not drain");
                    @(negedge clk); out_ready = 1'b0;
                end
            end
        end
    endtask

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            input_was_stalled = 1'b0;
        end else begin
            if (in_valid && in_ready) begin
                input_was_stalled = 1'b0;
            end else if (in_valid && !in_ready) begin
                input_stall_cycles = input_stall_cycles + 1;
                if (input_was_stalled) begin
                    if (in_data !== held_input || in_epoch !== held_in_epoch ||
                        in_token !== held_in_token || in_site !== held_in_site ||
                        in_lanes !== held_in_lanes || in_last !== held_in_last)
                        $fatal(1, "input changed while stalled");
                    input_stability_checks = input_stability_checks + 1;
                end else begin
                    held_input = in_data;
                    held_in_epoch = in_epoch;
                    held_in_token = in_token;
                    held_in_site = in_site;
                    held_in_lanes = in_lanes;
                    held_in_last = in_last;
                    input_was_stalled = 1'b1;
                end
            end else begin
                input_was_stalled = 1'b0;
            end
            if (consumer_pause && pack_out_valid && !pack_out_ready)
                output_stall_cycles = output_stall_cycles + 1;
            if (consumer_pause && (dut_packer.buffer_full == 2'b11))
                forced_full_cycles = forced_full_cycles + 1;
            if (monitor_stream && pack_out_valid && pack_out_ready) begin
                if (pack_out_epoch !== epoch_value[31:0] ||
                    pack_out_address >= current_word_count ||
                    pack_out_data !== expected_words[current_expected_start + pack_out_address] ||
                    pack_out_last !== (pack_out_address == current_word_count - 1))
                    $fatal(1, "packer stream differs from direct-CHW golden case=%0d seen=%0d addr=%0d",
                           active_case, stream_seen, pack_out_address);
                stream_seen = stream_seen + 1;
                packer_words_seen = packer_words_seen + 1;
                bank_word_accepts = bank_word_accepts + 1;
            end
        end
    end

    initial begin
        for (i = 1; i <= 7; i = i + 1) errors_by_code[i] = 0;
        $readmemh("feature_banks_cases.hex", case_table);
        $readmemh("feature_banks_input.hex", input_words);
        $readmemh("feature_banks_expected.hex", expected_words);
        repeat (3) tick();
        @(negedge clk); rst_n = 1'b1;
        monitor_stream = 1'b1;

        for (case_number = 0; case_number < CASE_COUNT; case_number = case_number + 1) begin
            active_case = case_number;
            phase_note("case_begin", case_number);
            configure_case(case_number);
            phase_note("case_configured", case_number);
            phase_note("feed_begin", case_number);
            if (case_table[case_number][193]) begin
                fork
                    feed_case(case_number);
                    pause_for_two_full_buffers();
                join
                if (!pause_controller_done || full_buffer_seen != 1)
                    $fatal(1, "artificial two-buffer pause coverage missing");
            end else begin
                feed_case(case_number);
            end
            phase_note("feed_done", case_number);
            phase_note("drain_begin", case_number);
            n = 0;
            while (!pack_done) begin
                if (n >= current_word_count * 8 + 1000)
                    diagnostic_stall("case_wait_pack_done", n,
                                     current_word_count * 8 + 1000);
                tick(); n = n + 1;
            end
            phase_note("drain_done", case_number);
            if (stream_seen != current_word_count || loading != 1'b1 || store_valid)
                $fatal(1, "stream count or load ownership mismatch case=%0d seen=%0d expected=%0d",
                       case_number, stream_seen, current_word_count);
            phase_note("commit_begin", case_number);
            commit_and_check(case_table[case_number][62:31]);
            cfg_cases_completed = cfg_cases_completed + 1;
            phase_note("commit_done", case_number);
            phase_note("readback_begin", case_number);
            read_all_case(case_number);
            if (!store_valid || active_epoch != case_table[case_number][62:31])
                $fatal(1, "store validity changed during readback case=%0d", case_number);
            phase_note("readback_done", case_number);
        end

        monitor_stream = 1'b0;
        run_error_tests();
        if (!store_valid || active_epoch != 914)
            $fatal(1, "final successful recovery epoch was not resident before terminal invalidation");
        @(negedge clk); rst_n = 1'b0; tick();
        if (store_valid || loading || out_valid || active_epoch != 0)
            $fatal(1, "terminal reset did not invalidate successful recovery epoch");
        @(negedge clk); rst_n = 1'b1; tick();
        if (pack_error_valid || pack_active || error_valid || store_valid || loading || out_valid)
            $fatal(1, "unexpected terminal ownership/error state");
        if (packer_words_seen <= 8192 || bank_word_accepts != packer_words_seen ||
            request_count <= 4096 || request_responses != request_count ||
            bytes_checked < 524288 || full_buffer_seen != 1 || forced_full_cycles < 8 ||
            forced_pause_cycles != 8 || input_bubbles <= 0 || input_stall_cycles <= 0 ||
            input_stability_checks <= 0 || output_stall_cycles < 8 ||
            output_stability_checks < 3 || cfg_cases_completed != CASE_COUNT ||
            recovery_checks != 3 || error_checks != 11 ||
            errors_by_code[1] != 1 || errors_by_code[2] != 3 ||
            errors_by_code[3] != 1 || errors_by_code[4] != 2 ||
            errors_by_code[5] != 1 || errors_by_code[6] != 1 ||
            errors_by_code[7] != 2)
            $fatal(1, "coverage counts failed words=%0d requests=%0d bytes=%0d errors=%0d",
                   packer_words_seen, request_count, bytes_checked, error_checks);
        $display("FEATURE_BANKS_ADDRESSED_PASS cases=%0d matrix_cases=%0d inputs=%0d words=%0d requests=%0d responses=%0d bytes=%0d bubbles=%0d input_stalls=%0d input_stability=%0d output_stalls=%0d output_stability=%0d full_buffer_checks=%0d pause_cycles=%0d errors=%0d e1=%0d e2=%0d e3=%0d e4=%0d e5=%0d e6=%0d e7=%0d recovery=%0d capacity_words=8192 capacity_bytes=524288",
                 cfg_cases_completed, MATRIX_CASES, input_accepts, packer_words_seen,
                 request_count, request_responses, bytes_checked, input_bubbles,
                 input_stall_cycles, input_stability_checks, output_stall_cycles,
                 output_stability_checks, forced_full_cycles, forced_pause_cycles,
                 error_checks, errors_by_code[1], errors_by_code[2], errors_by_code[3],
                 errors_by_code[4], errors_by_code[5], errors_by_code[6],
                 errors_by_code[7], recovery_checks);
        $finish;
    end

    initial begin
        #30000000;
        $display("FEATURE_BANKS_DIAG_WATCHDOG time=%0t case=%0d stream=%0d/%0d inputs=%0d words=%0d requests=%0d p_active=%b p_cfg_ready=%b in=%b/%b p_out=%b/%b p_addr=%0d p_err=%b/%0d buffers=%b bank_begin=%b/%b bank_word=%b/%b bank_error=%b/%0d loading=%b written=%0d expected=%0d store=%b epoch=%0d commit=%b/%b req=%b/%b req_addr0=%0d req_mask0=%b out=%b/%b out_epoch=%0d pause=%b",
                 $time, active_case, stream_seen, current_word_count, input_accepts,
                 packer_words_seen, request_count, pack_active, pack_cfg_ready,
                 in_valid, in_ready, pack_out_valid, pack_out_ready, pack_out_address,
                 pack_error_valid, pack_error_code, dut_packer.buffer_full,
                 cfg_begin, cfg_begin_ready, cfg_word_valid, cfg_word_ready,
                 error_valid, error_code, loading, dut_bank.written_words,
                 dut_bank.expected_words, store_valid, active_epoch, cfg_commit,
                 cfg_commit_ready, req_valid, req_ready, req_addresses[0 +: AW],
                 req_mask[0], out_valid, out_ready, out_epoch, consumer_pause);
        $fatal(1, "watchdog");
    end
endmodule

`default_nettype wire
