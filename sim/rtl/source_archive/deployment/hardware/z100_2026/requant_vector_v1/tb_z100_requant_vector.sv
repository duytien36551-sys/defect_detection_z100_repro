`timescale 1ns/1ps
`default_nettype none

module tb_z100_requant_vector;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n = 1'b0;
    reg cancel = 1'b0;
    reg cfg_begin = 1'b0;
    wire cfg_begin_ready;
    reg [31:0] cfg_epoch = 0;
    reg [5:0] cfg_lanes = 0;
    reg cfg_word_valid = 1'b0;
    wire cfg_word_ready;
    reg [1055:0] cfg_keys = 0;
    reg cfg_commit = 1'b0;
    wire cfg_commit_ready;
    wire cfg_error;
    wire input_error;
    reg in_valid = 1'b0;
    wire in_ready;
    reg [31:0] in_epoch = 0;
    reg [31:0] in_token = 0;
    reg [3:0] in_site = 0;
    reg in_last = 0;
    reg [1023:0] in_data = 0;
    reg [255:0] expected_input_data = 0;
    wire out_valid;
    reg out_ready = 1'b1;
    wire [31:0] out_epoch;
    wire [31:0] out_token;
    wire [3:0] out_site;
    wire [5:0] out_lanes;
    wire out_last;
    wire [255:0] out_data;

    z100_requant_vector dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(cfg_begin_ready),
        .cfg_epoch(cfg_epoch), .cfg_lanes(cfg_lanes),
        .cfg_word_valid(cfg_word_valid), .cfg_word_ready(cfg_word_ready),
        .cfg_keys(cfg_keys), .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .cfg_error(cfg_error), .input_error(input_error),
        .in_valid(in_valid), .in_ready(in_ready), .in_epoch(in_epoch),
        .in_token(in_token), .in_site(in_site), .in_last(in_last), .in_data(in_data),
        .out_valid(out_valid), .out_ready(out_ready), .out_epoch(out_epoch),
        .out_token(out_token), .out_site(out_site), .out_lanes(out_lanes),
        .out_last(out_last), .out_data(out_data)
    );

    reg [1055:0] recovery_cfg [0:254];
    reg [1055:0] synthetic_cfg [0:254];
    reg [1279:0] extra_records [0:31];
    reg [1055:0] cfg_record;
    reg [1279:0] data_record;

    reg [255:0] expected_data_q [0:15];
    reg [31:0] expected_epoch_q [0:15];
    reg [31:0] expected_token_q [0:15];
    reg [3:0] expected_site_q [0:15];
    reg [5:0] expected_lanes_q [0:15];
    reg expected_last_q [0:15];
    integer expected_head = 0;
    integer expected_tail = 0;
    integer expected_count = 0;
    integer cycle_count = 0;
    integer accepted_total = 0;
    integer output_total = 0;
    integer flushed_total = 0;
    integer main_accepted = 0;
    integer main_outputs = 0;
    integer active_lane_checks = 0;
    integer tail_lane_checks = 0;
    integer stall_stability_checks = 0;
    integer bubble_cycles = 0;
    integer cancellation_flushes = 0;
    integer reset_flushes = 0;
    integer recovery_checks = 0;
    integer invalid_cfg_cases = 0;
    integer invalid_input_cases = 0;
    integer reload_blocked_checks = 0;
    integer measured_accept_ii_checks = 0;
    integer measured_output_ii_checks = 0;
    integer measured_accept_ii_failures = 0;
    integer measured_output_ii_failures = 0;
    integer current_job = -1;
    integer current_beat = 0;
    integer current_lanes = 0;
    integer current_vector_count = 0;
    integer current_node = 0;
    integer current_first_channel = 0;
    integer active_epoch = 0;
    integer last_accept_cycle = -1;
    integer last_output_cycle = -1;
    integer first_accept_cycle = -1;
    integer first_output_cycle = -1;
    integer first_job_latency = -1;
    integer main_ii_enable = 0;
    integer jobs_done = 0;
    integer channels_done = 0;
    integer main_beats_done = 0;
    integer job_fd;
    integer cfg_fd;
    integer data_fd;
    integer scan_status;
    integer job_index;
    integer word_index;
    integer beat_index;
    integer epoch_value;
    integer lane_value;
    integer vector_count_value;
    integer node_value;
    integer first_channel_value;
    integer stage_index;
    integer mode_index;
    integer found_valid;
    integer i;
    integer synthetic_index;
    reg was_stalled = 1'b0;
    reg [255:0] held_data;
    reg [31:0] held_epoch;
    reg [31:0] held_token;
    reg [3:0] held_site;
    reg [5:0] held_lanes;
    reg held_last;
    reg [31:0] current_token;
    reg [3:0] current_site;
    reg current_last;
    reg malformed_input_expected;

    always @* begin
        malformed_input_expected = in_valid &&
            ((in_epoch != active_epoch) || (in_token == 0) || (in_site >= 12));
    end

    always @(posedge clk) begin
        cycle_count = cycle_count + 1;
        if (!rst_n || cancel) begin
            flushed_total = flushed_total + expected_count;
            expected_head = 0;
            expected_tail = 0;
            expected_count = 0;
            was_stalled = 1'b0;
        end else begin
            if (was_stalled) begin
                if (!out_valid || out_data !== held_data || out_epoch !== held_epoch ||
                    out_token !== held_token || out_site !== held_site ||
                    out_lanes !== held_lanes || out_last !== held_last) begin
                    $fatal(1, "OUTPUT_STALL_UNSTABLE cycle=%0d", cycle_count);
                end
                stall_stability_checks = stall_stability_checks + 1;
            end
            if (out_valid && !out_ready) begin
                was_stalled = 1'b1;
                held_data = out_data;
                held_epoch = out_epoch;
                held_token = out_token;
                held_site = out_site;
                held_lanes = out_lanes;
                held_last = out_last;
            end else begin
                was_stalled = 1'b0;
            end

            if (malformed_input_expected) begin
                if (in_ready) $fatal(1, "MALFORMED_INPUT_WAS_ACCEPTED");
                flushed_total = flushed_total + expected_count;
                expected_head = 0;
                expected_tail = 0;
                expected_count = 0;
            end else begin
                if (out_valid && out_ready) begin
                    if (expected_count <= 0) $fatal(1, "UNEXPECTED_OUTPUT cycle=%0d", cycle_count);
                    if (out_data !== expected_data_q[expected_head] ||
                        out_epoch !== expected_epoch_q[expected_head] ||
                        out_token !== expected_token_q[expected_head] ||
                        out_site !== expected_site_q[expected_head] ||
                        out_lanes !== expected_lanes_q[expected_head] ||
                        out_last !== expected_last_q[expected_head]) begin
                        $display("OUTPUT_MISMATCH cycle=%0d head=%0d epoch=%h/%h token=%h/%h site=%h/%h lanes=%0d/%0d last=%b/%b data=%h expected=%h",
                                 cycle_count, expected_head, out_epoch, expected_epoch_q[expected_head],
                                 out_token, expected_token_q[expected_head], out_site,
                                 expected_site_q[expected_head], out_lanes,
                                 expected_lanes_q[expected_head], out_last,
                                 expected_last_q[expected_head], out_data,
                                 expected_data_q[expected_head]);
                        $fatal(1, "OUTPUT_MISMATCH");
                    end
                    expected_head = (expected_head + 1) & 15;
                    expected_count = expected_count - 1;
                    output_total = output_total + 1;
                    active_lane_checks = active_lane_checks + out_lanes;
                    tail_lane_checks = tail_lane_checks + (32 - out_lanes);
                    if (main_ii_enable) begin
                        main_outputs = main_outputs + 1;
                        if (last_output_cycle >= 0) begin
                            if (cycle_count - last_output_cycle != 1)
                                measured_output_ii_failures = measured_output_ii_failures + 1;
                            measured_output_ii_checks = measured_output_ii_checks + 1;
                        end else begin
                            first_output_cycle = cycle_count;
                        end
                        last_output_cycle = cycle_count;
                    end
                end

                if (in_valid && in_ready) begin
                    if (expected_count >= 15) $fatal(1, "TESTBENCH_SCOREBOARD_OVERFLOW");
                    expected_data_q[expected_tail] = expected_input_data;
                    expected_epoch_q[expected_tail] = in_epoch;
                    expected_token_q[expected_tail] = in_token;
                    expected_site_q[expected_tail] = in_site;
                    expected_lanes_q[expected_tail] = current_lanes;
                    expected_last_q[expected_tail] = in_last;
                    expected_tail = (expected_tail + 1) & 15;
                    expected_count = expected_count + 1;
                    accepted_total = accepted_total + 1;
                    if (main_ii_enable) begin
                        main_accepted = main_accepted + 1;
                        if (last_accept_cycle >= 0) begin
                            if (cycle_count - last_accept_cycle != 1)
                                measured_accept_ii_failures = measured_accept_ii_failures + 1;
                            measured_accept_ii_checks = measured_accept_ii_checks + 1;
                        end else begin
                            first_accept_cycle = cycle_count;
                        end
                        last_accept_cycle = cycle_count;
                    end
                end else if (!in_valid && main_ii_enable) begin
                    bubble_cycles = bubble_cycles + 1;
                end
            end
        end
    end

    task automatic drive_begin(input [31:0] epoch_arg, input [5:0] lanes_arg,
                               input integer expect_error);
        begin
            @(negedge clk);
            cfg_epoch = epoch_arg;
            cfg_lanes = lanes_arg;
            cfg_begin = 1'b1;
            #1;
            if (!cfg_begin_ready) $fatal(1, "CFG_BEGIN_NOT_READY epoch=%0d lanes=%0d", epoch_arg, lanes_arg);
            @(posedge clk); #1;
            cfg_begin = 1'b0;
            if (expect_error && !cfg_error) $fatal(1, "CFG_BEGIN_ERROR_NOT_REPORTED");
            if (!expect_error && cfg_error) $fatal(1, "UNEXPECTED_CFG_BEGIN_ERROR");
        end
    endtask

    task automatic drive_word(input [1055:0] word_arg, input integer expect_error);
        begin
            @(negedge clk);
            cfg_keys = word_arg;
            cfg_word_valid = 1'b1;
            #1;
            if (!cfg_word_ready) $fatal(1, "CFG_WORD_NOT_READY count_word=%0d", word_index);
            @(posedge clk); #1;
            cfg_word_valid = 1'b0;
            if (expect_error && !cfg_error) $fatal(1, "CFG_WORD_ERROR_NOT_REPORTED word=%0d", word_index);
            if (!expect_error && cfg_error) $fatal(1, "UNEXPECTED_CFG_WORD_ERROR word=%0d", word_index);
        end
    endtask

    task automatic drive_commit(input integer expect_error);
        begin
            @(negedge clk);
            cfg_commit = 1'b1;
            #1;
            if (!cfg_commit_ready) $fatal(1, "CFG_COMMIT_NOT_READY");
            @(posedge clk); #1;
            cfg_commit = 1'b0;
            if (expect_error && !cfg_error) $fatal(1, "CFG_COMMIT_ERROR_NOT_REPORTED");
            if (!expect_error && cfg_error) $fatal(1, "UNEXPECTED_CFG_COMMIT_ERROR");
        end
    endtask

    task automatic configure_recovery(input [31:0] epoch_arg, input [5:0] lanes_arg);
        begin
            drive_begin(epoch_arg, lanes_arg, 0);
            for (word_index = 0; word_index < 255; word_index = word_index + 1)
                drive_word(recovery_cfg[word_index], 0);
            drive_commit(0);
            active_epoch = epoch_arg;
            current_lanes = lanes_arg;
        end
    endtask

    task automatic configure_synthetic(input [31:0] epoch_arg);
        begin
            drive_begin(epoch_arg, 32, 0);
            for (word_index = 0; word_index < 255; word_index = word_index + 1)
                drive_word(synthetic_cfg[word_index], 0);
            drive_commit(0);
            active_epoch = epoch_arg;
            current_lanes = 32;
        end
    endtask

    task automatic send_extra(input integer record_index, input [31:0] epoch_arg,
                              input [31:0] token_arg, input [3:0] site_arg,
                              input last_arg);
        begin
            @(negedge clk);
            in_valid = 1'b1;
            in_epoch = epoch_arg;
            in_token = token_arg;
            in_site = site_arg;
            in_last = last_arg;
            in_data = extra_records[record_index][1023:0];
            expected_input_data = extra_records[record_index][1279:1024];
            #1;
            if (!in_ready) $fatal(1, "EXTRA_INPUT_NOT_READY record=%0d", record_index);
            @(posedge clk); #1;
            if (!in_ready) $fatal(1, "EXTRA_INPUT_NOT_ACCEPTED record=%0d", record_index);
            in_valid = 1'b0;
        end
    endtask

    task automatic wait_for_drain;
        integer guard;
        begin
            guard = 0;
            while (expected_count != 0 && guard < 32) begin
                @(posedge clk); #1;
                guard = guard + 1;
            end
            if (expected_count != 0) $fatal(1, "DRAIN_TIMEOUT expected=%0d", expected_count);
        end
    endtask

    task automatic expect_unloaded;
        begin
            @(negedge clk);
            in_valid = 1'b1;
            in_epoch = active_epoch;
            in_token = 32'h0000a5a5;
            in_site = 4'd0;
            in_last = 1'b1;
            in_data = 0;
            expected_input_data = 0;
            #1;
            if (in_ready) $fatal(1, "INVALID_CONFIG_RETAINED_OLD_TABLE");
            @(posedge clk); #1;
            in_valid = 1'b0;
            if (out_valid) $fatal(1, "INVALID_CONFIG_EMITTED_OUTPUT");
            if (!cfg_error && !input_error && in_ready) $fatal(1, "FAILED_CLOSED_STATE_NOT_HELD");
            invalid_cfg_cases = invalid_cfg_cases + 1;
        end
    endtask

    task automatic send_bad_word_case(input integer case_id, input [31:0] epoch_arg);
        reg [1055:0] mutated;
        integer bad_index;
        integer j;
        begin
            configure_synthetic(epoch_arg);
            // A new configuration first removes the currently valid synthetic table.
            drive_begin(epoch_arg + 1, 32, 0);
            bad_index = 0;
            if (case_id == 2) bad_index = 1;
            if (case_id == 3) bad_index = 254;
            for (j = 0; j <= bad_index; j = j + 1) begin
                mutated = synthetic_cfg[j];
                if (j == 0 && case_id == 0) mutated[7*33 +: 33] = (-33'sd2147483648 - 33'sd1);
                if (j == 0 && case_id == 1) mutated[7*33 +: 33] = (33'sd2147483648 + 33'sd1);
                if (j == 0 && case_id == 2) mutated[7*33 +: 33] = 33'sd1;
                if (j == 1 && case_id == 2) mutated[7*33 +: 33] = 33'sd0;
                if (j == 254 && case_id == 3) mutated[7*33 +: 33] = 33'sd0;
                drive_word(mutated, j == bad_index);
            end
            expect_unloaded();
        end
    endtask

    task automatic send_bad_input_case(input integer case_id, input [31:0] epoch_arg);
        reg [31:0] bad_epoch;
        reg [31:0] bad_token;
        reg [3:0] bad_site;
        begin
            configure_recovery(epoch_arg, 16);
            out_ready = 1'b0;
            @(negedge clk);
            in_valid = 1'b1;
            in_epoch = epoch_arg;
            in_token = 32'h12340001;
            in_site = 4'd3;
            in_last = 1'b0;
            in_data = extra_records[0][1023:0];
            expected_input_data = extra_records[0][1279:1024];
            @(posedge clk); #1;
            if (expected_count != 1) $fatal(1, "PREFLIGHT_TOKEN_NOT_ACCEPTED");
            bad_epoch = epoch_arg;
            bad_token = 32'h12340002;
            bad_site = 4'd4;
            if (case_id == 0) bad_epoch = epoch_arg + 1;
            if (case_id == 1) bad_token = 0;
            if (case_id == 2) bad_site = 4'd12;
            in_epoch = bad_epoch;
            in_token = bad_token;
            in_site = bad_site;
            in_last = 1'b1;
            in_data = extra_records[1][1023:0];
            expected_input_data = extra_records[1][1279:1024];
            @(posedge clk); #1;
            if (!input_error) $fatal(1, "MALFORMED_INPUT_ERROR_NOT_REPORTED case=%0d", case_id);
            if (in_ready || out_valid) $fatal(1, "MALFORMED_INPUT_DID_NOT_FLUSH case=%0d", case_id);
            in_valid = 1'b0;
            out_ready = 1'b1;
            invalid_input_cases = invalid_input_cases + 1;
        end
    endtask

    task automatic abort_at_stage(input integer stage_arg, input integer use_reset,
                                  input [31:0] epoch_arg);
        integer wait_index;
        begin
            configure_recovery(epoch_arg, 16);
            out_ready = 1'b0;
            @(negedge clk);
            in_valid = 1'b1;
            in_epoch = epoch_arg;
            in_token = 32'h70000000 + stage_arg + (use_reset ? 32'h100 : 0);
            in_site = stage_arg[3:0];
            in_last = stage_arg == 7;
            in_data = extra_records[stage_arg][1023:0];
            expected_input_data = extra_records[stage_arg][1279:1024];
            @(posedge clk); #1;
            if (expected_count != 1) $fatal(1, "ABORT_PREFLIGHT_NOT_ACCEPTED stage=%0d", stage_arg);
            in_valid = 1'b0;
            for (wait_index = 0; wait_index < stage_arg; wait_index = wait_index + 1) begin
                @(posedge clk); #1;
            end
            if (dut.valid_q !== (8'b1 << stage_arg)) begin
                $fatal(1, "ABORT_STAGE_MISMATCH requested=%0d valid_q=%b", stage_arg, dut.valid_q);
            end
            if (use_reset) begin
                rst_n = 1'b0;
                @(posedge clk); #1;
                rst_n = 1'b1;
                reset_flushes = reset_flushes + 1;
            end else begin
                cancel = 1'b1;
                @(posedge clk); #1;
                cancel = 1'b0;
                cancellation_flushes = cancellation_flushes + 1;
            end
            in_valid = 1'b0;
            if (out_valid) $fatal(1, "ABORT_LEFT_OUTPUT_VALID stage=%0d", stage_arg);
            out_ready = 1'b1;
            @(posedge clk); #1;
            if (expected_count != 0) $fatal(1, "ABORT_SCOREBOARD_NOT_FLUSHED");
            configure_recovery(epoch_arg + 32'd1000, 16);
            send_extra(stage_arg, epoch_arg + 32'd1000, 32'h71000000 + stage_arg,
                       stage_arg[3:0], 1'b1);
            wait_for_drain();
            recovery_checks = recovery_checks + 1;
        end
    endtask

    task automatic test_reload_blocked_and_stall(input [31:0] epoch_arg);
        integer wait_index;
        begin
            configure_recovery(epoch_arg, 16);
            out_ready = 1'b0;
            send_extra(8, epoch_arg, 32'h60000001, 4'd8, 1'b0);
            found_valid = 0;
            for (wait_index = 0; wait_index < 12; wait_index = wait_index + 1) begin
                @(posedge clk); #1;
                if (out_valid) begin
                    found_valid = 1;
                    wait_index = 12;
                end
            end
            if (!found_valid) $fatal(1, "STALLED_OUTPUT_NOT_REACHED");
            repeat (4) begin @(posedge clk); #1; end
            @(negedge clk);
            cfg_epoch = epoch_arg + 1;
            cfg_lanes = 16;
            cfg_begin = 1'b1;
            #1;
            if (cfg_begin_ready) $fatal(1, "RELOAD_ALLOWED_WITH_OUTPUT_INFLIGHT");
            @(posedge clk); #1;
            cfg_begin = 1'b0;
            if (!out_valid) $fatal(1, "OUTPUT_DROPPED_DURING_BLOCKED_RELOAD");
            reload_blocked_checks = reload_blocked_checks + 1;
            @(negedge clk); out_ready = 1'b1;
            @(posedge clk); #1;
            wait_for_drain();
            configure_recovery(epoch_arg + 2, 16);
            send_extra(9, epoch_arg + 2, 32'h60000002, 4'd9, 1'b1);
            wait_for_drain();
            recovery_checks = recovery_checks + 1;
        end
    endtask

    integer expected_jobs;
    integer expected_main_beats;
    integer expected_channels;
    integer contract_fd;
    initial begin
        contract_fd = $fopen("coverage.txt", "r");
        if (contract_fd == 0) $fatal(1, "COVERAGE_CONTRACT_OPEN_FAILED");
        scan_status = $fscanf(contract_fd, "%d %d %d\n", expected_jobs,
                              expected_main_beats, expected_channels);
        $fclose(contract_fd);
        if (scan_status != 3) $fatal(1, "COVERAGE_CONTRACT_READ_FAILED");
        $readmemh("recovery_cfg.mem", recovery_cfg);
        $readmemh("synthetic_cfg.mem", synthetic_cfg);
        $readmemh("extra_records.mem", extra_records);

        repeat (3) @(posedge clk);
        @(negedge clk); rst_n = 1'b1;
        repeat (2) @(posedge clk);

        job_fd = $fopen("jobs.txt", "r");
        cfg_fd = $fopen("cfg.mem", "r");
        data_fd = $fopen("vectors.mem", "r");
        if (job_fd == 0 || cfg_fd == 0 || data_fd == 0) $fatal(1, "MAIN_FIXTURE_OPEN_FAILED");
        out_ready = 1'b1;
        for (job_index = 0; job_index < expected_jobs; job_index = job_index + 1) begin
            scan_status = $fscanf(job_fd, "%d %d %d %d %d\n", epoch_value, lane_value,
                                  vector_count_value, node_value, first_channel_value);
            if (scan_status != 5) $fatal(1, "JOB_DESCRIPTOR_READ_FAILED job=%0d status=%0d", job_index, scan_status);
            current_job = job_index;
            current_lanes = lane_value;
            current_vector_count = vector_count_value;
            current_node = node_value;
            current_first_channel = first_channel_value;
            drive_begin(epoch_value, lane_value[5:0], 0);
            for (word_index = 0; word_index < 255; word_index = word_index + 1) begin
                scan_status = $fscanf(cfg_fd, "%h\n", cfg_record);
                if (scan_status != 1) $fatal(1, "CONFIG_WORD_READ_FAILED job=%0d word=%0d", job_index, word_index);
                drive_word(cfg_record, 0);
            end
            drive_commit(0);
            active_epoch = epoch_value;
            last_accept_cycle = -1;
            last_output_cycle = -1;
            first_accept_cycle = -1;
            first_output_cycle = -1;
            main_ii_enable = 1;
            for (beat_index = 0; beat_index < vector_count_value; beat_index = beat_index + 1) begin
                scan_status = $fscanf(data_fd, "%h\n", data_record);
                if (scan_status != 1) $fatal(1, "DATA_VECTOR_READ_FAILED job=%0d beat=%0d", job_index, beat_index);
                @(negedge clk);
                in_valid = 1'b1;
                in_epoch = epoch_value;
                in_token = (job_index + 1) * 1000000 + beat_index + 1;
                in_site = beat_index % 12;
                in_last = (beat_index == vector_count_value - 1);
                in_data = data_record[1023:0];
                expected_input_data = data_record[1279:1024];
                #1;
                if (!in_ready) $fatal(1, "MAIN_INPUT_NOT_READY job=%0d beat=%0d", job_index, beat_index);
                @(posedge clk); #1;
                if (!in_ready) $fatal(1, "MAIN_INPUT_NOT_ACCEPTED job=%0d beat=%0d", job_index, beat_index);
                main_beats_done = main_beats_done + 1;
            end
            @(negedge clk); in_valid = 1'b0;
            main_ii_enable = 1'b1;
            wait_for_drain();
            main_ii_enable = 1'b0;
            if (first_accept_cycle < 0 || first_output_cycle < 0)
                $fatal(1, "MAIN_JOB_MISSING_ACTIVITY job=%0d", job_index);
            if (job_index == 0) first_job_latency = first_output_cycle - first_accept_cycle;
            jobs_done = jobs_done + 1;
            channels_done = channels_done + lane_value;
        end
        $fclose(job_fd); $fclose(cfg_fd); $fclose(data_fd);
        if (main_beats_done != expected_main_beats) $fatal(1, "MAIN_BEAT_COVERAGE_MISMATCH got=%0d expected=%0d", main_beats_done, expected_main_beats);
        if (jobs_done != expected_jobs || channels_done != expected_channels)
            $fatal(1, "MAIN_JOB_COVERAGE_MISMATCH jobs=%0d channels=%0d", jobs_done, channels_done);
        if (expected_count != 0) $fatal(1, "MAIN_STREAM_DID_NOT_DRAIN");
        if (measured_accept_ii_failures != 0 || measured_output_ii_failures != 0)
            $fatal(1, "MAIN_STEADY_II_FAILURE accept=%0d output=%0d", measured_accept_ii_failures, measured_output_ii_failures);

        // Bubble handling and a deliberately blocked output/reload exercise.
        test_reload_blocked_and_stall(32'd50000);
        configure_recovery(32'd51000, 16);
        send_extra(10, 32'd51000, 32'h51000001, 4'd1, 1'b0);
        repeat (2) begin @(posedge clk); #1; end
        bubble_cycles = bubble_cycles + 2;
        send_extra(11, 32'd51000, 32'h51000002, 4'd2, 1'b1);
        wait_for_drain();

        // Reset and cancel at each of the eight valid stages, with a recovery transfer after each.
        for (stage_index = 0; stage_index < 8; stage_index = stage_index + 1) begin
            abort_at_stage(stage_index, 0, 32'd52000 + stage_index * 10);
            abort_at_stage(stage_index, 1, 32'd53000 + stage_index * 10);
        end

        // A one-lane malformed table must invalidate the whole pending configuration.
        drive_begin(0, 16, 1);
        expect_unloaded();
        drive_begin(32'd60000, 0, 1);
        expect_unloaded();
        drive_begin(32'd60001, 33, 1);
        expect_unloaded();

        drive_begin(32'd61000, 32, 0);
        for (word_index = 0; word_index < 8; word_index = word_index + 1)
            drive_word(synthetic_cfg[word_index], 0);
        drive_commit(1);
        expect_unloaded();

        drive_begin(32'd62000, 32, 0);
        for (word_index = 0; word_index < 255; word_index = word_index + 1)
            drive_word(synthetic_cfg[word_index], 0);
        drive_word(synthetic_cfg[254], 1);
        expect_unloaded();

        send_bad_word_case(0, 32'd63000); // KEY_MIN - 1 in lane 7.
        send_bad_word_case(1, 32'd63100); // KEY_MAX + 1 in lane 7.
        send_bad_word_case(2, 32'd63200); // Descending keys in lane 7.
        send_bad_word_case(3, 32'd63300); // Missing final +2^31 key in lane 7.

        send_bad_input_case(0, 32'd64000); // Stale epoch.
        send_bad_input_case(1, 32'd64100); // Zero token.
        send_bad_input_case(2, 32'd64200); // Site 12.

        if (invalid_cfg_cases < 8) $fatal(1, "CONFIG_ERROR_COVERAGE_SHORT got=%0d", invalid_cfg_cases);
        if (invalid_input_cases != 3) $fatal(1, "INPUT_ERROR_COVERAGE_SHORT got=%0d", invalid_input_cases);
        if (cancellation_flushes != 8 || reset_flushes != 8 || recovery_checks < 17)
            $fatal(1, "RESET_CANCEL_RECOVERY_COVERAGE cancel=%0d reset=%0d recovery=%0d",
                   cancellation_flushes, reset_flushes, recovery_checks);
        if (reload_blocked_checks != 1 || stall_stability_checks < 4 || bubble_cycles < 2)
            $fatal(1, "FLOW_CONTROL_COVERAGE reload=%0d stall=%0d bubbles=%0d",
                   reload_blocked_checks, stall_stability_checks, bubble_cycles);
        if (output_total + flushed_total != accepted_total)
            $fatal(1, "HANDSHAKE_COUNT_MISMATCH accepted=%0d outputs=%0d flushed=%0d",
                   accepted_total, output_total, flushed_total);
        if (expected_count != 0) $fatal(1, "FINAL_SCOREBOARD_NOT_EMPTY");

        $display("REQUANT_VECTOR_PASS jobs=%0d channels=%0d main_beats=%0d main_outputs=%0d all_outputs=%0d first_job_latency=%0d active_lane_checks=%0d tail_lane_checks=%0d accept_ii_checks=%0d output_ii_checks=%0d accept_ii_failures=%0d output_ii_failures=%0d stall_checks=%0d bubble_cycles=%0d reload_blocked=%0d cancel_stages=%0d reset_stages=%0d recovery_checks=%0d invalid_configs=%0d invalid_inputs=%0d",
                 jobs_done, channels_done, main_beats_done, main_outputs, output_total,
                 first_job_latency, active_lane_checks, tail_lane_checks,
                 measured_accept_ii_checks, measured_output_ii_checks,
                 measured_accept_ii_failures, measured_output_ii_failures,
                 stall_stability_checks, bubble_cycles, reload_blocked_checks,
                 cancellation_flushes, reset_flushes, recovery_checks,
                 invalid_cfg_cases, invalid_input_cases);
        $finish;
    end
endmodule

`default_nettype wire
