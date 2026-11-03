`timescale 1ns/1ps
`default_nettype none
module tb_z100_window_mac_post;
    `include "integration_counts.svh"
    localparam integer JOBS = 6;
    localparam integer GROUPS = 9;
    localparam integer RESULT_WORDS = 22;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg cancel = 0;

    reg feature_cfg_begin = 0;
    wire feature_cfg_begin_ready;
    reg [31:0] feature_cfg_epoch = 0;
    reg [13:0] feature_cfg_words = 0;
    reg feature_cfg_word_valid = 0;
    wire feature_cfg_word_ready;
    reg [511:0] feature_cfg_data = 0;
    reg feature_cfg_commit = 0;
    wire feature_cfg_commit_ready;
    wire feature_store_valid;
    wire feature_loading;
    wire [31:0] feature_active_epoch;
    wire feature_error_valid;
    wire [2:0] feature_error_code;

    reg window_valid = 0;
    wire window_ready;
    reg [31:0] window_epoch = 1;
    reg [31:0] window_tag = 0;
    reg [13:0] window_row_address = 0;
    reg signed [11:0] window_first_x = 0;
    reg [10:0] window_input_width = 640;
    reg [10:0] window_output_remaining = 320;
    reg [3:0] window_sites = 4;
    reg [3:0] window_channel_mask = 7;
    reg window_stride_two = 1;
    reg window_y_valid = 0;

    reg mac_cfg_begin = 0;
    wire mac_cfg_begin_ready;
    reg [31:0] mac_cfg_epoch = 0;
    reg [10:0] mac_cfg_groups = 0;
    reg mac_cfg_weight_valid = 0;
    wire mac_cfg_weight_ready;
    reg [1023:0] mac_cfg_weights = 0;
    reg mac_cfg_bias_valid = 0;
    wire mac_cfg_bias_ready;
    reg [1023:0] mac_cfg_bias = 0;
    reg mac_cfg_commit = 0;
    wire mac_cfg_commit_ready;
    wire mac_weights_valid;
    wire [31:0] mac_weights_epoch;
    wire mac_error_valid;
    wire [2:0] mac_error_code;

    reg run_valid = 0;
    wire run_ready;
    reg [31:0] run_epoch = 1;
    reg [31:0] run_token = 0;
    reg [5:0] run_lanes = 16;
    reg [3:0] run_sites = 4;

    wire stream_valid;
    wire stream_ready;
    wire [31:0] stream_token;
    wire stream_last;
    wire [127:0] stream_data;
    wire [31:0] response_tag;
    wire [47:0] response_mask;

    reg req_cfg_begin = 0;
    wire req_cfg_begin_ready;
    reg [31:0] req_cfg_epoch = 0;
    reg [5:0] req_cfg_lanes = 0;
    reg req_cfg_word_valid = 0;
    wire req_cfg_word_ready;
    reg [1055:0] req_cfg_keys = 0;
    reg req_cfg_commit = 0;
    wire req_cfg_commit_ready;
    wire req_cfg_error;
    wire req_input_error;

    reg unary_cfg_begin = 0;
    wire unary_cfg_begin_ready;
    reg [31:0] unary_cfg_epoch = 0;
    reg unary_cfg_word_valid = 0;
    wire unary_cfg_word_ready;
    reg [7:0] unary_cfg_data = 0;
    reg unary_cfg_commit = 0;
    wire unary_cfg_commit_ready;
    wire unary_error_valid;
    wire [2:0] unary_error_code;
    wire unary_store_valid;
    wire [31:0] unary_active_epoch;
    wire unary_loading;

    wire raw_valid;
    wire raw_ready;
    wire [31:0] raw_token;
    wire [3:0] raw_site;
    wire raw_last;
    wire [5:0] raw_lanes;
    wire [1023:0] raw_data;
    wire [31:0] raw_overflow;
    wire metadata_error;

    wire out_valid;
    reg out_ready = 0;
    wire [31:0] out_epoch;
    wire [31:0] out_token;
    wire [3:0] out_site;
    wire out_last;
    wire [5:0] out_lanes;
    wire [255:0] out_data;

    reg [511:0] feature_words [0:LOAD_WORDS-1];
    reg [1023:0] weight_groups [0:GROUPS-1];
    reg [1023:0] bias_word [0:0];
    reg [1055:0] expected_words [0:RESULT_WORDS-1];
    reg [255:0] expected_post_words [0:RESULT_WORDS-1];
    reg [1055:0] req_cfg_words [0:254];
    reg [7:0] unary_cfg_bytes [0:255];
    integer output_y [0:JOBS-1];
    integer output_x [0:JOBS-1];
    integer output_sites [0:JOBS-1];

    integer current_job = 0;
    integer job_request_count = 0;
    integer job_response_count = 0;
    integer job_output_count = 0;
    integer job_raw_count = 0;
    integer feature_load_count = 0;
    integer weight_load_count = 0;
    integer bias_load_count = 0;
    integer req_cfg_load_count = 0;
    integer unary_cfg_load_count = 0;
    integer total_requests = 0;
    integer total_responses = 0;
    integer total_outputs = 0;
    integer total_raw_beats = 0;
    integer raw_lane_checks = 0;
    integer raw_flag_checks = 0;
    integer active_post_byte_checks = 0;
    integer masked_post_byte_checks = 0;
    integer total_output_stalls = 0;
    integer total_raw_stalls = 0;
    integer raw_stall_stability_checks = 0;
    integer injected_pause_cycles = 0;
    integer injected_pause_stability_checks = 0;
    integer injected_pause_started = 0;
    integer injected_pause_released = 0;
    integer total_response_stalls = 0;
    integer stream_bubble_cycles = 0;
    integer output_metadata_checks = 0;
    integer timeout_cycles = 0;
    reg job_active = 0;
    reg previous_response_stall = 0;
    reg [31:0] held_response_tag = 0;
    reg [47:0] held_response_mask = 0;
    reg [127:0] held_stream_data = 0;
    reg [31:0] held_stream_token = 0;
    reg held_stream_last = 0;
    reg previous_output_stall = 0;
    reg previous_raw_stall = 0;
    reg [31:0] held_raw_token = 0;
    reg [3:0] held_raw_site = 0;
    reg held_raw_last = 0;
    reg [5:0] held_raw_lanes = 0;
    reg [1023:0] held_raw_data = 0;
    reg [31:0] held_raw_overflow = 0;
    reg [31:0] held_output_token = 0;
    reg [3:0] held_output_site = 0;
    reg held_output_last = 0;
    reg [5:0] held_output_lanes = 0;
    reg [255:0] held_output_data = 0;
    reg [31:0] held_output_epoch = 0;

    integer request_group;
    integer request_ky;
    integer request_kx;
    integer request_input_y;
    integer request_expected_x;
    integer request_expected_row;
    integer result_lane;
    integer result_index;
    integer result_expected_site;
    reg [47:0] computed_mask;

    z100_window_mac_post #(.GROUPS_PER_RUN(GROUPS)) dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .feature_cfg_begin(feature_cfg_begin),
        .feature_cfg_begin_ready(feature_cfg_begin_ready),
        .feature_cfg_epoch(feature_cfg_epoch), .feature_cfg_words(feature_cfg_words),
        .feature_cfg_word_valid(feature_cfg_word_valid),
        .feature_cfg_word_ready(feature_cfg_word_ready), .feature_cfg_data(feature_cfg_data),
        .feature_cfg_commit(feature_cfg_commit),
        .feature_cfg_commit_ready(feature_cfg_commit_ready),
        .feature_store_valid(feature_store_valid), .feature_loading(feature_loading),
        .feature_active_epoch(feature_active_epoch), .feature_error_valid(feature_error_valid),
        .feature_error_code(feature_error_code),
        .window_valid(window_valid), .window_ready(window_ready),
        .window_epoch(window_epoch), .window_tag(window_tag),
        .window_row_address(window_row_address), .window_first_x(window_first_x),
        .window_input_width(window_input_width),
        .window_output_remaining(window_output_remaining), .window_sites(window_sites),
        .window_channel_mask(window_channel_mask), .window_stride_two(window_stride_two),
        .window_y_valid(window_y_valid),
        .mac_cfg_begin(mac_cfg_begin), .mac_cfg_begin_ready(mac_cfg_begin_ready),
        .mac_cfg_epoch(mac_cfg_epoch), .mac_cfg_groups(mac_cfg_groups),
        .mac_cfg_weight_valid(mac_cfg_weight_valid),
        .mac_cfg_weight_ready(mac_cfg_weight_ready), .mac_cfg_weights(mac_cfg_weights),
        .mac_cfg_bias_valid(mac_cfg_bias_valid), .mac_cfg_bias_ready(mac_cfg_bias_ready),
        .mac_cfg_bias(mac_cfg_bias), .mac_cfg_commit(mac_cfg_commit),
        .mac_cfg_commit_ready(mac_cfg_commit_ready), .mac_weights_valid(mac_weights_valid),
        .mac_weights_epoch(mac_weights_epoch), .mac_error_valid(mac_error_valid),
        .mac_error_code(mac_error_code), .run_valid(run_valid), .run_ready(run_ready),
        .run_epoch(run_epoch), .run_token(run_token), .run_lanes(run_lanes),
        .run_sites(run_sites), .stream_valid(stream_valid), .stream_ready(stream_ready),
        .stream_token(stream_token), .stream_last(stream_last), .stream_data(stream_data),
        .response_tag(response_tag), .response_mask(response_mask), .out_valid(out_valid),
        .req_cfg_begin(req_cfg_begin), .req_cfg_begin_ready(req_cfg_begin_ready),
        .req_cfg_epoch(req_cfg_epoch), .req_cfg_lanes(req_cfg_lanes),
        .req_cfg_word_valid(req_cfg_word_valid), .req_cfg_word_ready(req_cfg_word_ready),
        .req_cfg_keys(req_cfg_keys), .req_cfg_commit(req_cfg_commit),
        .req_cfg_commit_ready(req_cfg_commit_ready), .req_cfg_error(req_cfg_error),
        .req_input_error(req_input_error), .unary_cfg_begin(unary_cfg_begin),
        .unary_cfg_begin_ready(unary_cfg_begin_ready), .unary_cfg_epoch(unary_cfg_epoch),
        .unary_cfg_word_valid(unary_cfg_word_valid), .unary_cfg_word_ready(unary_cfg_word_ready),
        .unary_cfg_data(unary_cfg_data), .unary_cfg_commit(unary_cfg_commit),
        .unary_cfg_commit_ready(unary_cfg_commit_ready), .unary_error_valid(unary_error_valid),
        .unary_error_code(unary_error_code), .unary_store_valid(unary_store_valid),
        .unary_active_epoch(unary_active_epoch), .unary_loading(unary_loading),
        .raw_valid(raw_valid), .raw_ready(raw_ready), .raw_token(raw_token), .raw_site(raw_site),
        .raw_last(raw_last), .raw_lanes(raw_lanes), .raw_data(raw_data),
        .raw_overflow(raw_overflow), .out_ready(out_ready), .out_epoch(out_epoch),
        .out_token(out_token), .out_site(out_site), .out_last(out_last),
        .out_lanes(out_lanes), .out_data(out_data), .metadata_error(metadata_error)
    );

    function automatic [31:0] tag_for(input integer job, input integer group_index);
        tag_for = 32'h5a000000 + job*256 + group_index;
    endfunction

    function automatic [31:0] token_for(input integer job);
        token_for = 32'd1001 + job;
    endfunction

    function automatic [47:0] expected_response_mask(input integer job, input integer group_index);
        integer ky;
        integer kx;
        integer iy;
        integer ix;
        integer ch;
        integer site_index;
        reg [47:0] mask_value;
        begin
            ky = group_index / 3;
            kx = group_index % 3;
            iy = output_y[job]*2 + ky - 1;
            mask_value = 0;
            for (ch = 0; ch < 3; ch = ch + 1) begin
                for (site_index = 0; site_index < 4; site_index = site_index + 1) begin
                    ix = (output_x[job] + site_index)*2 + kx - 1;
                    if (site_index < output_sites[job] && iy >= 0 && iy < 640 &&
                        ix >= 0 && ix < 640)
                        mask_value[ch*12+site_index] = 1'b1;
                end
            end
            expected_response_mask = mask_value;
        end
    endfunction

    task automatic send_descriptor(input integer job, input integer group_index);
        integer ky;
        integer kx;
        integer iy;
        begin
            ky = group_index / 3;
            kx = group_index % 3;
            iy = output_y[job]*2 + ky - 1;
            @(negedge clk);
            window_epoch = 1;
            window_tag = tag_for(job, group_index);
            window_row_address = (iy >= 0 && iy < 640) ? iy*40 : 0;
            window_first_x = output_x[job]*2 + kx - 1;
            window_input_width = 640;
            window_output_remaining = 320 - output_x[job];
            window_sites = output_sites[job];
            window_channel_mask = 7;
            window_stride_two = 1;
            window_y_valid = (iy >= 0 && iy < 640);
            window_valid = 1;
            do @(posedge clk); while (!window_ready);
            @(negedge clk);
            window_valid = 0;
            if (group_index != GROUPS-1)
                @(negedge clk);
        end
    endtask

    task automatic start_run(input integer job);
        begin
            @(negedge clk);
            if (!feature_store_valid || feature_loading || feature_active_epoch != 1 ||
                !mac_weights_valid || mac_weights_epoch != 1)
                $fatal(1, "resident feature or weight epoch lost before job %0d", job);
            run_epoch = 1;
            run_token = token_for(job);
            run_lanes = 16;
            run_sites = output_sites[job];
            run_valid = 1;
            job_active = 1;
            do @(posedge clk); while (!run_ready);
            @(negedge clk);
            run_valid = 0;
        end
    endtask

    always @(posedge clk) begin
        if (!rst_n) begin
            feature_load_count = 0;
            weight_load_count = 0;
            bias_load_count = 0;
            req_cfg_load_count = 0;
            unary_cfg_load_count = 0;
            total_requests = 0;
            total_responses = 0;
            total_outputs = 0;
            total_raw_beats = 0;
            raw_lane_checks = 0;
            raw_flag_checks = 0;
            active_post_byte_checks = 0;
            masked_post_byte_checks = 0;
            total_output_stalls = 0;
            total_raw_stalls = 0;
            total_response_stalls = 0;
            stream_bubble_cycles = 0;
            output_metadata_checks = 0;
            previous_response_stall = 0;
            previous_output_stall = 0;
            previous_raw_stall = 0;
            timeout_cycles = 0;
        end else begin
            timeout_cycles = timeout_cycles + 1;
            if (timeout_cycles > 1000000)
                $fatal(1, "integration simulation timed out");
            if (feature_error_valid)
                $fatal(1, "feature-window error code=%0d", feature_error_code);
            if (mac_error_valid)
                $fatal(1, "native-MAC error code=%0d", mac_error_code);
            if (req_cfg_error || req_input_error)
                $fatal(1, "requantizer error cfg=%0d input=%0d", req_cfg_error, req_input_error);
            if (unary_error_valid)
                $fatal(1, "unary error code=%0d", unary_error_code);
            if (metadata_error)
                $fatal(1, "requant-to-unary sideband metadata mismatch");

            if (feature_cfg_word_valid && feature_cfg_word_ready)
                feature_load_count = feature_load_count + 1;
            if (mac_cfg_weight_valid && mac_cfg_weight_ready)
                weight_load_count = weight_load_count + 1;
            if (mac_cfg_bias_valid && mac_cfg_bias_ready)
                bias_load_count = bias_load_count + 1;
            if (req_cfg_word_valid && req_cfg_word_ready)
                req_cfg_load_count = req_cfg_load_count + 1;
            if (unary_cfg_word_valid && unary_cfg_word_ready)
                unary_cfg_load_count = unary_cfg_load_count + 1;

            if (window_valid && window_ready) begin
                request_group = job_request_count;
                if (request_group >= GROUPS)
                    $fatal(1, "extra feature-window request in job %0d", current_job);
                request_ky = request_group / 3;
                request_kx = request_group % 3;
                request_input_y = output_y[current_job]*2 + request_ky - 1;
                request_expected_x = output_x[current_job]*2 + request_kx - 1;
                request_expected_row = (request_input_y >= 0 && request_input_y < 640) ?
                    request_input_y*40 : 0;
                if (window_epoch != 1 || window_tag != tag_for(current_job, request_group) ||
                    window_row_address != request_expected_row ||
                    $signed(window_first_x) != request_expected_x ||
                    window_input_width != 640 ||
                    window_output_remaining != 320-output_x[current_job] ||
                    window_sites != output_sites[current_job] || window_channel_mask != 7 ||
                    window_stride_two != 1 ||
                    window_y_valid != (request_input_y >= 0 && request_input_y < 640))
                    $fatal(1, "window request descriptor mismatch job=%0d group=%0d",
                           current_job, request_group);
                job_request_count = job_request_count + 1;
                total_requests = total_requests + 1;
            end

            if (previous_response_stall) begin
                if (!stream_valid || response_tag !== held_response_tag ||
                    response_mask !== held_response_mask || stream_data !== held_stream_data ||
                    stream_token !== held_stream_token || stream_last !== held_stream_last)
                    $fatal(1, "window response changed while backpressured");
            end
            previous_response_stall = stream_valid && !stream_ready;
            if (previous_response_stall) begin
                total_response_stalls = total_response_stalls + 1;
                held_response_tag = response_tag;
                held_response_mask = response_mask;
                held_stream_data = stream_data;
                held_stream_token = stream_token;
                held_stream_last = stream_last;
            end

            if (stream_valid && stream_ready) begin
                if (job_response_count >= GROUPS)
                    $fatal(1, "extra MAC activation response in job %0d", current_job);
                if (response_tag != tag_for(current_job, job_response_count) ||
                    response_mask !== expected_response_mask(current_job, job_response_count) ||
                    stream_token != token_for(current_job) ||
                    stream_last != (job_response_count == GROUPS-1))
                    $fatal(1, "activation response metadata mismatch job=%0d group=%0d",
                           current_job, job_response_count);
                job_response_count = job_response_count + 1;
                total_responses = total_responses + 1;
            end else if (job_active && stream_ready && job_response_count < GROUPS) begin
                stream_bubble_cycles = stream_bubble_cycles + 1;
            end

            if (previous_raw_stall) begin
                if (!raw_valid || raw_token !== held_raw_token || raw_site !== held_raw_site ||
                    raw_last !== held_raw_last || raw_lanes !== held_raw_lanes ||
                    raw_data !== held_raw_data || raw_overflow !== held_raw_overflow)
                    $fatal(1, "raw MAC output changed while requantizer backpressured");
                raw_stall_stability_checks = raw_stall_stability_checks + 1;
            end
            previous_raw_stall = raw_valid && !raw_ready;
            if (previous_raw_stall) begin
                total_raw_stalls = total_raw_stalls + 1;
                held_raw_token = raw_token;
                held_raw_site = raw_site;
                held_raw_last = raw_last;
                held_raw_lanes = raw_lanes;
                held_raw_data = raw_data;
                held_raw_overflow = raw_overflow;
            end
            if (raw_valid && raw_ready) begin
                result_index = total_raw_beats;
                if (result_index >= RESULT_WORDS || job_raw_count >= output_sites[current_job])
                    $fatal(1, "extra raw MAC site in job %0d", current_job);
                if (raw_token != token_for(current_job) || raw_site != job_raw_count ||
                    raw_lanes != 16 || raw_last != (job_raw_count == output_sites[current_job]-1))
                    $fatal(1, "raw MAC metadata mismatch job=%0d site=%0d", current_job, job_raw_count);
                for (result_lane = 0; result_lane < 32; result_lane = result_lane + 1) begin
                    if (raw_data[result_lane*32 +: 32] !==
                        expected_words[result_index][32+result_lane*32 +: 32])
                        $fatal(1, "raw MAC result mismatch job=%0d site=%0d lane=%0d got=%08x expected=%08x",
                               current_job, job_raw_count, result_lane,
                               raw_data[result_lane*32 +: 32],
                               expected_words[result_index][32+result_lane*32 +: 32]);
                    if (raw_overflow[result_lane] !== expected_words[result_index][result_lane])
                        $fatal(1, "raw overflow flag mismatch job=%0d site=%0d lane=%0d",
                               current_job, job_raw_count, result_lane);
                    raw_lane_checks = raw_lane_checks + 1;
                    raw_flag_checks = raw_flag_checks + 1;
                end
                job_raw_count = job_raw_count + 1;
                total_raw_beats = total_raw_beats + 1;
            end

            if (previous_output_stall) begin
                if (!out_valid || out_token !== held_output_token || out_site !== held_output_site ||
                    out_last !== held_output_last || out_lanes !== held_output_lanes ||
                    out_epoch !== held_output_epoch || out_data !== held_output_data)
                    $fatal(1, "postprocess output changed while stalled");
            end
            previous_output_stall = out_valid && !out_ready;
            if (previous_output_stall) begin
                total_output_stalls = total_output_stalls + 1;
                held_output_token = out_token;
                held_output_site = out_site;
                held_output_last = out_last;
                held_output_lanes = out_lanes;
                held_output_epoch = out_epoch;
                held_output_data = out_data;
            end

            if (out_valid && out_ready) begin
                result_index = total_outputs;
                result_expected_site = job_output_count;
                if (result_index >= RESULT_WORDS || job_output_count >= output_sites[current_job])
                    $fatal(1, "extra MAC output site in job %0d", current_job);
                if (out_epoch != 1 || out_token != token_for(current_job) ||
                    out_site != result_expected_site || out_lanes != 16 ||
                    out_last != (job_output_count == output_sites[current_job]-1))
                    $fatal(1, "postprocess metadata mismatch job=%0d site=%0d",
                           current_job, job_output_count);
                for (result_lane = 0; result_lane < 32; result_lane = result_lane + 1) begin
                    if (out_data[result_lane*8 +: 8] !==
                        expected_post_words[result_index][result_lane*8 +: 8])
                        $fatal(1, "postprocess byte mismatch job=%0d site=%0d lane=%0d got=%02x expected=%02x",
                               current_job, job_output_count, result_lane,
                               out_data[result_lane*8 +: 8],
                               expected_post_words[result_index][result_lane*8 +: 8]);
                    if (result_lane < 16)
                        active_post_byte_checks = active_post_byte_checks + 1;
                    else
                        masked_post_byte_checks = masked_post_byte_checks + 1;
                end
                job_output_count = job_output_count + 1;
                total_outputs = total_outputs + 1;
                output_metadata_checks = output_metadata_checks + 1;
            end
        end
    end

    // Artificially pause only the requantizer's ready input before the first
    // raw handshake. This directly verifies the MAC output holding contract;
    // it does not claim that the natural full-buffer path was reached.
    initial begin : injected_consumer_pause
        reg [31:0] pause_token;
        reg [3:0] pause_site;
        reg pause_last;
        reg [5:0] pause_lanes;
        reg [1023:0] pause_data;
        reg [31:0] pause_overflow;

        wait (rst_n === 1'b1);
        wait (raw_valid === 1'b1);
        if (total_raw_beats != 0 || raw_ready !== 1'b1)
            $fatal(1, "injected pause was not before the first raw handshake");
        pause_token = raw_token;
        pause_site = raw_site;
        pause_last = raw_last;
        pause_lanes = raw_lanes;
        pause_data = raw_data;
        pause_overflow = raw_overflow;
        force dut.req_in_ready = 1'b0;
        injected_pause_started = 1;
        repeat (3) begin
            @(posedge clk);
            #1;
            if (raw_valid !== 1'b1 || raw_ready !== 1'b0 ||
                raw_token !== pause_token || raw_site !== pause_site ||
                raw_last !== pause_last || raw_lanes !== pause_lanes ||
                raw_data !== pause_data || raw_overflow !== pause_overflow)
                $fatal(1, "raw MAC output changed during injected requantizer pause");
            injected_pause_cycles = injected_pause_cycles + 1;
            injected_pause_stability_checks = injected_pause_stability_checks + 1;
        end
        @(negedge clk);
        release dut.req_in_ready;
        injected_pause_released = 1;
    end

    integer i;
    integer job;
    initial begin
        $readmemh("feature_words.hex", feature_words);
        $readmemh("native_weight_groups.hex", weight_groups);
        $readmemh("native_bias.hex", bias_word);
        $readmemh("expected_raw_words.hex", expected_words);
        $readmemh("expected_post_words.hex", expected_post_words);
        $readmemh("req_cfg.hex", req_cfg_words);
        $readmemh("unary_cfg.hex", unary_cfg_bytes);

        output_y[0] = 0;   output_x[0] = 0;   output_sites[0] = 4;
        output_y[1] = 0;   output_x[1] = 317; output_sites[1] = 3;
        output_y[2] = 1;   output_x[2] = 11;  output_sites[2] = 4;
        output_y[3] = 100; output_x[3] = 40;  output_sites[3] = 4;
        output_y[4] = 101; output_x[4] = 0;   output_sites[4] = 4;
        output_y[5] = 101; output_x[5] = 317; output_sites[5] = 3;

        repeat (6) @(negedge clk);
        rst_n = 1;

        // Load the real feature tile once: three channels, source rows 0..203.
        @(negedge clk);
        feature_cfg_epoch = 1;
        feature_cfg_words = LOAD_WORDS;
        feature_cfg_begin = 1;
        #1;
        if (!feature_cfg_begin_ready)
            $fatal(1, "feature configuration begin was not ready");
        @(posedge clk);
        @(negedge clk);
        feature_cfg_begin = 0;
        feature_cfg_word_valid = 1;
        #1;
        for (i = 0; i < LOAD_WORDS; i = i + 1) begin
            feature_cfg_data = feature_words[i];
            if (!feature_cfg_word_ready)
                $fatal(1, "feature load backpressured at word %0d", i);
            @(posedge clk);
            if (feature_error_valid)
                $fatal(1, "feature load error during word %0d", i);
            if (i != LOAD_WORDS-1)
                @(negedge clk);
        end
        @(negedge clk);
        feature_cfg_word_valid = 0;
        feature_cfg_commit = 1;
        #1;
        if (!feature_cfg_commit_ready)
            $fatal(1, "feature configuration commit was not ready");
        @(posedge clk);
        @(negedge clk);
        feature_cfg_commit = 0;
        if (!feature_store_valid || feature_active_epoch != 1 || feature_loading)
            $fatal(1, "feature store did not commit epoch 1");

        // Load only the current model's first-convolution weights and bias.
        mac_cfg_epoch = 1;
        mac_cfg_groups = GROUPS;
        mac_cfg_begin = 1;
        #1;
        if (!mac_cfg_begin_ready)
            $fatal(1, "MAC configuration begin was not ready");
        @(posedge clk);
        @(negedge clk);
        mac_cfg_begin = 0;
        mac_cfg_weight_valid = 1;
        #1;
        for (i = 0; i < GROUPS; i = i + 1) begin
            mac_cfg_weights = weight_groups[i];
            if (!mac_cfg_weight_ready)
                $fatal(1, "MAC weight load backpressured at group %0d", i);
            @(posedge clk);
            if (mac_error_valid)
                $fatal(1, "MAC weight load error during group %0d", i);
            if (i != GROUPS-1)
                @(negedge clk);
        end
        @(negedge clk);
        mac_cfg_weight_valid = 0;
        mac_cfg_bias_valid = 1;
        mac_cfg_bias = bias_word[0];
        #1;
        if (!mac_cfg_bias_ready)
            $fatal(1, "MAC bias load was not ready");
        @(posedge clk);
        @(negedge clk);
        mac_cfg_bias_valid = 0;
        mac_cfg_commit = 1;
        #1;
        if (!mac_cfg_commit_ready)
            $fatal(1, "MAC configuration commit was not ready");
        @(posedge clk);
        @(negedge clk);
        mac_cfg_commit = 0;
        if (!mac_weights_valid || mac_weights_epoch != 1)
            $fatal(1, "MAC weights did not commit epoch 1");

        // The exact first-convolution 255-key config and node-1 SiLU LUT are
        // resident for all six jobs; no reload occurs at job boundaries.
        req_cfg_epoch = 1;
        req_cfg_lanes = 16;
        req_cfg_begin = 1;
        #1;
        if (!req_cfg_begin_ready)
            $fatal(1, "requant configuration begin was not ready");
        @(posedge clk);
        @(negedge clk);
        req_cfg_begin = 0;
        req_cfg_word_valid = 1;
        #1;
        for (i = 0; i < 255; i = i + 1) begin
            req_cfg_keys = req_cfg_words[i];
            if (!req_cfg_word_ready)
                $fatal(1, "requant key load backpressured at word %0d", i);
            @(posedge clk);
            if (req_cfg_error)
                $fatal(1, "requant key load error during word %0d", i);
            if (i != 254)
                @(negedge clk);
        end
        @(negedge clk);
        req_cfg_word_valid = 0;
        req_cfg_commit = 1;
        #1;
        if (!req_cfg_commit_ready)
            $fatal(1, "requant configuration commit was not ready");
        @(posedge clk);
        @(negedge clk);
        req_cfg_commit = 0;

        unary_cfg_epoch = 1;
        unary_cfg_begin = 1;
        #1;
        if (!unary_cfg_begin_ready)
            $fatal(1, "unary configuration begin was not ready");
        @(posedge clk);
        @(negedge clk);
        unary_cfg_begin = 0;
        unary_cfg_word_valid = 1;
        #1;
        for (i = 0; i < 256; i = i + 1) begin
            unary_cfg_data = unary_cfg_bytes[i];
            if (!unary_cfg_word_ready)
                $fatal(1, "unary LUT load backpressured at byte %0d", i);
            @(posedge clk);
            if (unary_error_valid)
                $fatal(1, "unary LUT load error during byte %0d", i);
            if (i != 255)
                @(negedge clk);
        end
        @(negedge clk);
        unary_cfg_word_valid = 0;
        unary_cfg_commit = 1;
        #1;
        if (!unary_cfg_commit_ready)
            $fatal(1, "unary configuration commit was not ready");
        @(posedge clk);
        @(negedge clk);
        unary_cfg_commit = 0;
        if (!unary_store_valid || unary_active_epoch != 1 || unary_loading)
            $fatal(1, "unary LUT did not commit epoch 1");

        for (job = 0; job < JOBS; job = job + 1) begin
            current_job = job;
            // This bounded bridge forwards the externally owned job token.
            // Own it before a descriptor can produce a stalled response, and
            // retain it through the complete run/drain interval.
            run_token = token_for(job);
            job_request_count = 0;
            job_response_count = 0;
            job_output_count = 0;
            job_raw_count = 0;
            out_ready = 0;
            job_active = 0;

            if (job == 0) begin
                // Deliberately hold the first real response while the MAC is
                // idle, then release it only after the run token is accepted.
                send_descriptor(job, 0);
                while (!stream_valid)
                    @(negedge clk);
                if (stream_ready)
                    $fatal(1, "MAC accepted a response before run start");
                repeat (3) @(posedge clk);
                start_run(job);
                for (i = 1; i < GROUPS; i = i + 1)
                    send_descriptor(job, i);
            end else begin
                start_run(job);
                for (i = 0; i < GROUPS; i = i + 1)
                    send_descriptor(job, i);
            end

            while (job_response_count < GROUPS)
                @(negedge clk);
            if (job_request_count != GROUPS)
                $fatal(1, "job %0d request count %0d != 9", job, job_request_count);
            while (!out_valid)
                @(negedge clk);
            repeat (3) @(posedge clk);
            @(negedge clk);
            if (!out_valid || out_ready || job_output_count != 0)
                $fatal(1, "first output site was not held under backpressure");
            out_ready = 1;
            while (job_output_count < output_sites[job])
                @(negedge clk);
            out_ready = 0;
            job_active = 0;
            if (job_response_count != GROUPS || job_raw_count != output_sites[job] ||
                job_output_count != output_sites[job] ||
                window_valid || stream_valid || out_valid)
                $fatal(1, "job %0d did not drain before the next run", job);
            if (!feature_store_valid || feature_loading || feature_active_epoch != 1 ||
                !mac_weights_valid || mac_weights_epoch != 1 ||
                !unary_store_valid || unary_active_epoch != 1 || unary_loading)
                $fatal(1, "resident feature or weight epoch changed after job %0d", job);
        end

        if (feature_load_count != LOAD_WORDS || weight_load_count != GROUPS || bias_load_count != 1 ||
            req_cfg_load_count != 255 || unary_cfg_load_count != 256)
            $fatal(1, "resident configuration load counts changed: feature=%0d weight=%0d bias=%0d req=%0d unary=%0d",
                   feature_load_count, weight_load_count, bias_load_count,
                   req_cfg_load_count, unary_cfg_load_count);
        if (total_requests != JOBS*GROUPS || total_responses != JOBS*GROUPS ||
            total_raw_beats != RESULT_WORDS || raw_lane_checks != RESULT_WORDS*32 ||
            raw_flag_checks != RESULT_WORDS*32 || total_outputs != RESULT_WORDS ||
            active_post_byte_checks != RESULT_WORDS*16 || masked_post_byte_checks != RESULT_WORDS*16 ||
            output_metadata_checks != RESULT_WORDS)
            $fatal(1, "post transfer counts differ requests=%0d responses=%0d raw=%0d rawlanes=%0d flags=%0d outputs=%0d active=%0d tails=%0d metadata=%0d",
                   total_requests, total_responses, total_raw_beats, raw_lane_checks,
                   raw_flag_checks, total_outputs, active_post_byte_checks,
                   masked_post_byte_checks, output_metadata_checks);
        if (stream_bubble_cycles <= 0 || total_response_stalls < 3 ||
            total_raw_stalls < 1 || total_output_stalls < 3 ||
            injected_pause_started != 1 || injected_pause_released != 1 ||
            injected_pause_cycles != 3 || injected_pause_stability_checks != 3 ||
            raw_stall_stability_checks < 2)
            $fatal(1, "stall coverage missing: bubbles=%0d response_stalls=%0d raw_stalls=%0d raw_stability=%0d post_stalls=%0d injected_started=%0d injected_released=%0d injected_cycles=%0d injected_stability=%0d",
                   stream_bubble_cycles, total_response_stalls, total_raw_stalls,
                   raw_stall_stability_checks, total_output_stalls, injected_pause_started,
                   injected_pause_released, injected_pause_cycles,
                   injected_pause_stability_checks);
        $display("WINDOW_MAC_POST_PASS jobs=%0d requests=%0d responses=%0d raw_beats=%0d raw_lanes=%0d flags=%0d post_beats=%0d active_bytes=%0d masked_tails=%0d load_words=%0d weight_groups=%0d bias_loads=%0d req_words=%0d unary_bytes=%0d input_bubbles=%0d response_stalls=%0d raw_stalls=%0d post_stalls=%0d metadata=%0d residency=%0d pause_mode=INJECTED_REQ_IN_READY_LOW injected_pause_cycles=%0d injected_pause_stability=%0d raw_stall_stability=%0d",
                 JOBS, total_requests, total_responses, total_raw_beats, raw_lane_checks,
                 raw_flag_checks, total_outputs, active_post_byte_checks, masked_post_byte_checks,
                 feature_load_count, weight_load_count, bias_load_count, req_cfg_load_count,
                 unary_cfg_load_count, stream_bubble_cycles, total_response_stalls,
                 total_raw_stalls, total_output_stalls, output_metadata_checks, JOBS,
                 injected_pause_cycles, injected_pause_stability_checks,
                 raw_stall_stability_checks);
        $finish;
    end
endmodule

`default_nettype wire
