`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_row20_factor_buffer;
    localparam integer SITES = 20;
    localparam integer GROUPS = 9;
    localparam integer ROW_WIDTH = 320;
    localparam integer RUNS = 16;
    localparam integer FEATURE_WORDS = 80;
    localparam integer WINDOW_REQUESTS = RUNS * GROUPS;
    localparam integer EPOCH = 32'd77;
    localparam integer TOKEN_BASE = 32'd4100;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg cancel = 0;

    reg feature_cfg_begin = 0;
    wire feature_cfg_begin_ready;
    reg [31:0] feature_cfg_epoch = 0;
    reg [10:0] feature_cfg_channels = 3;
    reg [9:0] feature_cfg_height = 2, feature_cfg_width = 640;
    reg [31:0] feature_cfg_word_epoch = EPOCH;
    reg [12:0] feature_cfg_word_address = 0;
    reg feature_cfg_word_last = 0;
    reg feature_cfg_word_valid = 0;
    wire feature_cfg_word_ready;
    reg [511:0] feature_cfg_data = 0;
    reg feature_cfg_commit = 0;
    wire feature_cfg_commit_ready;
    wire feature_store_valid;
    wire feature_loading;
    wire [31:0] feature_active_epoch;
    wire feature_error_valid;
    wire [3:0] feature_error_code;

    reg window_valid = 0;
    wire window_ready;
    reg [31:0] window_epoch = 0;
    reg [31:0] window_tag = 0;
    reg [13:0] window_row_address = 0;
    reg signed [11:0] window_first_x = 0;
    reg [10:0] window_input_width = 640;
    reg [10:0] window_output_remaining = ROW_WIDTH;
    reg [4:0] window_sites = SITES;
    reg [3:0] window_channel_mask = 7;
    reg window_stride_two = 1;
    reg window_y_valid = 0;

    reg mac_cfg_begin = 0;
    wire mac_cfg_begin_ready;
    reg [31:0] mac_cfg_epoch = 0;
    reg [10:0] mac_cfg_groups = GROUPS;
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
    reg [31:0] run_epoch = 0;
    reg [31:0] run_token = 0;
    reg [5:0] run_lanes = 16;
    reg [4:0] run_sites = SITES;
    wire stream_valid;
    wire stream_ready;
    wire [31:0] stream_token;
    wire stream_last;
    wire [639:0] stream_data;
    wire [31:0] response_tag;
    wire [79:0] response_mask;

    reg req_cfg_begin = 0;
    wire req_cfg_begin_ready;
    reg [31:0] req_cfg_epoch = 0;
    reg [5:0] req_cfg_lanes = 16;
    reg req_cfg_word_valid = 0;
    wire req_cfg_word_ready;
    reg [30:0] req_cfg_multiplier = 0;
    reg [5:0] req_cfg_shift = 0;
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
    wire [4:0] raw_site;
    wire raw_last;
    wire [5:0] raw_lanes;
    wire [1023:0] raw_data;
    wire [31:0] raw_overflow;

    wire post_valid;
    wire post_ready;
    wire [31:0] post_epoch;
    wire [31:0] post_token;
    wire [4:0] post_site;
    wire [5:0] post_lanes;
    wire post_last;
    wire [255:0] post_data;
    wire metadata_error;

    reg pack_cfg_valid = 0;
    wire pack_cfg_ready;
    reg [31:0] pack_cfg_epoch = 0;
    reg [10:0] pack_cfg_channels = 16;
    reg [9:0] pack_cfg_height = 1;
    reg [9:0] pack_cfg_width = ROW_WIDTH;
    reg [31:0] pack_cfg_token_base = TOKEN_BASE;
    wire packed_valid;
    reg packed_ready = 0;
    wire [31:0] packed_epoch;
    wire [12:0] packed_address;
    wire [511:0] packed_data;
    wire packed_last;
    wire pack_done;
    wire pack_error_valid;
    wire [2:0] pack_error_code;
    wire pack_active;

    reg [511:0] feature_words [0:FEATURE_WORDS-1];
    reg [1023:0] weight_groups [0:GROUPS-1];
    reg [1023:0] bias_word [0:0];
    reg [36:0] req_words [0:15];
    reg [7:0] unary_bytes [0:255];
    reg [639:0] expected_window_data [0:WINDOW_REQUESTS-1];
    reg [79:0] expected_window_masks [0:WINDOW_REQUESTS-1];
    reg [1055:0] expected_raw_words [0:ROW_WIDTH-1];
    reg [255:0] expected_post_words [0:ROW_WIDTH-1];
    reg [511:0] expected_packed_words [0:79];

    integer feature_load_count = 0;
    integer weight_group_load_count = 0;
    integer bias_load_count = 0;
    integer req_load_count = 0;
    integer unary_load_count = 0;
    integer run_count = 0;
    integer window_request_count = 0;
    integer window_response_count = 0;
    integer window_byte_checks = 0;
    integer response_mask_checks = 0;
    integer raw_beats = 0;
    integer raw_lane_checks = 0;
    integer raw_flag_checks = 0;
    integer post_beats = 0;
    integer post_active_byte_checks = 0;
    integer post_tail_byte_checks = 0;
    integer packed_beats = 0;
    integer packed_byte_checks = 0;
    integer packed_stall_cycles = 0;
    integer packed_stall_hold_checks = 0;
    integer post_stall_cycles = 0;
    integer requant_stall_cycles = 0;
    integer unary_stall_cycles = 0;
    integer raw_stall_cycles = 0;
    integer raw_stall_hold_checks = 0;
    integer response_stall_cycles = 0;
    integer response_stall_hold_checks = 0;
    integer stream_bubble_cycles = 0;
    integer site_fifo_full_cycles = 0;
    integer pack_done_count = 0;
    integer timeout_cycles = 0;
    integer buffer_full_seen = 0;
    integer consumer_hold_checks = 0;
    integer consumer_released = 0;
    reg [79:0] packed_address_seen = 0;
    integer active_token_valid = 0;
    reg [31:0] active_token = 0;
    reg active_final_post_seen = 0;

    reg previous_response_stall = 0;
    reg [784:0] held_response;
    reg previous_raw_stall = 0;
    reg [1099:0] held_raw;
    reg previous_post_stall = 0;
    reg [331:0] held_post;
    reg previous_packed_stall = 0;
    reg [557:0] held_packed;
    integer idx, run_index, site_index, group_index, input_y, output_x;
    integer result_lane, result_index, expected_sites, expected_site, packed_expected_address;

    z100_native_row20_factor_buffer #(.SITES(SITES),
                               .SITE_FIFO_DEPTH(4)) dut (.*);

    function automatic [31:0] tag_for(input integer run_id, input integer group_id);
        tag_for = 32'h53000000 + run_id*16 + group_id;
    endfunction

    function automatic integer sites_for_run(input integer run_id);
        sites_for_run = (run_id == RUNS-1) ? ROW_WIDTH-run_id*SITES : SITES;
    endfunction

    function automatic integer final_post_count(input integer run_id);
        final_post_count = (run_id == RUNS-1) ? ROW_WIDTH : (run_id+1)*SITES;
    endfunction

    task automatic load_features;
        integer i;
        begin
            @(negedge clk);
            feature_cfg_epoch = EPOCH; feature_cfg_word_epoch = EPOCH;
            feature_cfg_begin = 1;
            #1;
            if (!feature_cfg_begin_ready) $fatal(1, "feature begin not ready");
            @(posedge clk); #1;
            if (!feature_loading || feature_store_valid) $fatal(1, "feature begin failed");
            @(negedge clk); feature_cfg_begin = 0; feature_cfg_word_valid = 1;
            for (i = 0; i < FEATURE_WORDS; i = i + 1) begin
                feature_cfg_data = feature_words[i]; feature_cfg_word_address = i;
                feature_cfg_word_last = (i == FEATURE_WORDS-1); #1;
                if (!feature_cfg_word_ready) $fatal(1, "feature word %0d not ready", i);
                @(posedge clk); #1;
                if (feature_error_valid) $fatal(1, "feature load error word=%0d code=%0d", i, feature_error_code);
                if (i != FEATURE_WORDS-1) @(negedge clk);
            end
            @(negedge clk); feature_cfg_word_valid = 0; feature_cfg_commit = 1; #1;
            if (!feature_cfg_commit_ready) $fatal(1, "feature commit not ready");
            @(posedge clk); #1;
            if (!feature_store_valid || feature_active_epoch != EPOCH || feature_loading)
                $fatal(1, "feature store did not commit expected epoch");
            @(negedge clk); feature_cfg_commit = 0;
        end
    endtask

    task automatic load_mac;
        integer i;
        begin
            @(negedge clk);
            mac_cfg_epoch = EPOCH; mac_cfg_groups = GROUPS; mac_cfg_begin = 1; #1;
            if (!mac_cfg_begin_ready) $fatal(1, "MAC config begin not ready");
            @(posedge clk); #1;
            @(negedge clk); mac_cfg_begin = 0; mac_cfg_weight_valid = 1;
            for (i = 0; i < GROUPS; i = i + 1) begin
                mac_cfg_weights = weight_groups[i]; #1;
                if (!mac_cfg_weight_ready) $fatal(1, "MAC weight group %0d not ready", i);
                @(posedge clk); #1;
                if (mac_error_valid) $fatal(1, "MAC weight error code=%0d", mac_error_code);
                if (i != GROUPS-1) @(negedge clk);
            end
            @(negedge clk); mac_cfg_weight_valid = 0;
            mac_cfg_bias = bias_word[0]; mac_cfg_bias_valid = 1;
            @(posedge clk); #1;
            if (mac_error_valid) $fatal(1, "MAC bias load error code=%0d", mac_error_code);
            @(negedge clk); mac_cfg_bias_valid = 0; mac_cfg_commit = 1; #1;
            if (!mac_cfg_commit_ready) $fatal(1, "MAC commit not ready");
            @(posedge clk); #1;
            if (!mac_weights_valid || mac_weights_epoch != EPOCH || mac_error_valid)
                $fatal(1, "MAC resident weights did not commit");
            @(negedge clk); mac_cfg_commit = 0;
        end
    endtask

    task automatic load_requant;
        integer i;
        begin
            @(negedge clk);
            req_cfg_epoch = EPOCH; req_cfg_lanes = 16; req_cfg_begin = 1; #1;
            if (!req_cfg_begin_ready) $fatal(1, "requant config begin not ready");
            @(posedge clk); #1;
            @(negedge clk); req_cfg_begin = 0; req_cfg_word_valid = 1;
            for (i = 0; i < 16; i = i + 1) begin
                req_cfg_multiplier = req_words[i][30:0]; req_cfg_shift = req_words[i][36:31]; #1;
                if (!req_cfg_word_ready) $fatal(1, "requant key vector %0d not ready", i);
                @(posedge clk); #1;
                if (req_cfg_error) $fatal(1, "requant config error at vector %0d", i);
                if (i != 15) @(negedge clk);
            end
            @(negedge clk); req_cfg_word_valid = 0; req_cfg_commit = 1; #1;
            if (!req_cfg_commit_ready) $fatal(1, "requant commit not ready");
            @(posedge clk); #1;
            if (req_cfg_error) $fatal(1, "requant config commit failed");
            @(negedge clk); req_cfg_commit = 0;
        end
    endtask

    task automatic load_unary;
        integer i;
        begin
            @(negedge clk);
            unary_cfg_epoch = EPOCH; unary_cfg_begin = 1; #1;
            if (!unary_cfg_begin_ready) $fatal(1, "unary config begin not ready");
            @(posedge clk); #1;
            @(negedge clk); unary_cfg_begin = 0; unary_cfg_word_valid = 1;
            for (i = 0; i < 256; i = i + 1) begin
                unary_cfg_data = unary_bytes[i]; #1;
                if (!unary_cfg_word_ready) $fatal(1, "unary LUT byte %0d not ready", i);
                @(posedge clk); #1;
                if (unary_error_valid) $fatal(1, "unary LUT error byte=%0d", i);
                if (i != 255) @(negedge clk);
            end
            @(negedge clk); unary_cfg_word_valid = 0; unary_cfg_commit = 1; #1;
            if (!unary_cfg_commit_ready) $fatal(1, "unary commit not ready");
            @(posedge clk); #1;
            if (unary_error_valid || !unary_store_valid || unary_active_epoch != EPOCH)
                $fatal(1, "unary LUT did not commit");
            @(negedge clk); unary_cfg_commit = 0;
        end
    endtask

    task automatic configure_packer;
        begin
            @(negedge clk);
            pack_cfg_epoch = EPOCH; pack_cfg_channels = 16;
            pack_cfg_height = 1; pack_cfg_width = ROW_WIDTH;
            pack_cfg_token_base = TOKEN_BASE; pack_cfg_valid = 1; #1;
            if (!pack_cfg_ready) $fatal(1, "packer config not ready");
            @(posedge clk); #1;
            if (!pack_active || pack_error_valid) $fatal(1, "packer config failed");
            @(negedge clk); pack_cfg_valid = 0;
        end
    endtask

    task automatic start_run(input integer job);
        begin
            @(negedge clk);
            if (!feature_store_valid || feature_active_epoch != EPOCH ||
                !mac_weights_valid || mac_weights_epoch != EPOCH ||
                !unary_store_valid || unary_active_epoch != EPOCH)
                $fatal(1, "resident configuration lost before run %0d", job);
            run_epoch = EPOCH; run_token = TOKEN_BASE + job;
            run_lanes = 16; run_sites = sites_for_run(job); run_valid = 1;
            do @(posedge clk); while (!run_ready);
            @(negedge clk); run_valid = 0;
        end
    endtask

    task automatic send_descriptor(input integer job, input integer group_id);
        integer ky, kx, iy, ox;
        begin
            ky = group_id / 3; kx = group_id % 3;
            iy = ky - 1; ox = job*SITES;
            @(negedge clk);
            window_epoch = EPOCH; window_tag = tag_for(job, group_id);
            window_row_address = (iy >= 0 && iy < 2) ? iy*40 : 0;
            window_first_x = ox*2 + kx - 1;
            window_input_width = 640; window_output_remaining = ROW_WIDTH-ox;
            window_sites = sites_for_run(job); window_channel_mask = 7;
            window_stride_two = 1; window_y_valid = (iy >= 0 && iy < 2);
            window_valid = 1;
            do @(posedge clk); while (!window_ready);
            @(negedge clk); window_valid = 0;
            do @(posedge clk); while (!(stream_valid && stream_ready));
            @(negedge clk);
        end
    endtask

    always @(posedge clk) begin
        if (!rst_n) begin
            feature_load_count = 0; weight_group_load_count = 0; bias_load_count = 0;
            req_load_count = 0; unary_load_count = 0; run_count = 0;
            window_request_count = 0; window_response_count = 0; window_byte_checks = 0;
            response_mask_checks = 0; raw_beats = 0; raw_lane_checks = 0; raw_flag_checks = 0;
            post_beats = 0; post_active_byte_checks = 0; post_tail_byte_checks = 0;
            packed_beats = 0; packed_byte_checks = 0; packed_stall_cycles = 0;
            packed_stall_hold_checks = 0; post_stall_cycles = 0;
            requant_stall_cycles = 0; unary_stall_cycles = 0; raw_stall_cycles = 0;
            raw_stall_hold_checks = 0; response_stall_cycles = 0;
            response_stall_hold_checks = 0; stream_bubble_cycles = 0;
            site_fifo_full_cycles = 0; pack_done_count = 0; timeout_cycles = 0;
            active_token_valid = 0; active_token = 0; active_final_post_seen = 0;
            packed_address_seen = 0;
            previous_response_stall = 0; previous_raw_stall = 0;
            previous_post_stall = 0; previous_packed_stall = 0;
        end else begin
            timeout_cycles = timeout_cycles + 1;
            if (timeout_cycles > 200000) $fatal(1, "native row pipeline watchdog");
            if (feature_error_valid) $fatal(1, "feature-window error code=%0d", feature_error_code);
            if (mac_error_valid) $fatal(1, "native-MAC error code=%0d", mac_error_code);
            if (req_cfg_error || req_input_error)
                $fatal(1, "requantizer error config=%0d input=%0d", req_cfg_error, req_input_error);
            if (unary_error_valid) $fatal(1, "unary error code=%0d", unary_error_code);
            if (pack_error_valid) $fatal(1, "packer error code=%0d", pack_error_code);
            if (metadata_error) $fatal(1, "requant-to-unary sideband metadata mismatch");

            if (feature_cfg_word_valid && feature_cfg_word_ready) feature_load_count = feature_load_count + 1;
            if (mac_cfg_weight_valid && mac_cfg_weight_ready) weight_group_load_count = weight_group_load_count + 1;
            if (mac_cfg_bias_valid && mac_cfg_bias_ready) bias_load_count = bias_load_count + 1;
            if (req_cfg_word_valid && req_cfg_word_ready) req_load_count = req_load_count + 1;
            if (unary_cfg_word_valid && unary_cfg_word_ready) unary_load_count = unary_load_count + 1;
            if (run_valid && run_ready) run_count = run_count + 1;

            if (window_valid && window_ready) begin
                idx = window_request_count;
                if (idx >= WINDOW_REQUESTS) $fatal(1, "extra feature-window descriptor");
                run_index = idx / GROUPS; group_index = idx % GROUPS;
                input_y = group_index/3 - 1; output_x = run_index*SITES;
                if (window_epoch != EPOCH || window_tag != tag_for(run_index, group_index) ||
                    window_row_address != ((input_y >= 0 && input_y < 2) ? input_y*40 : 0) ||
                    $signed(window_first_x) != output_x*2+(group_index%3)-1 ||
                    window_input_width != 640 || window_output_remaining != ROW_WIDTH-output_x ||
                    window_sites != sites_for_run(run_index) || window_channel_mask != 7 ||
                    !window_stride_two || window_y_valid != (input_y >= 0 && input_y < 2))
                    $fatal(1, "window descriptor mismatch run=%0d group=%0d", run_index, group_index);
                window_request_count = window_request_count + 1;
            end

            if (previous_response_stall) begin
                if (!stream_valid || {response_tag,response_mask,stream_token,stream_last,stream_data} !== held_response)
                    $fatal(1, "feature response changed while MAC stalled");
                response_stall_hold_checks = response_stall_hold_checks + 1;
            end
            previous_response_stall = stream_valid && !stream_ready;
            if (previous_response_stall) begin
                held_response = {response_tag,response_mask,stream_token,stream_last,stream_data};
                response_stall_cycles = response_stall_cycles + 1;
            end
            if (stream_valid && stream_ready) begin
                idx = window_response_count;
                if (idx >= WINDOW_REQUESTS) $fatal(1, "extra feature-window response");
                run_index = idx / GROUPS; group_index = idx % GROUPS;
                if (response_tag !== tag_for(run_index, group_index) ||
                    response_mask !== expected_window_masks[idx] ||
                    stream_token !== TOKEN_BASE+run_index || stream_last !== (group_index==GROUPS-1) ||
                    stream_data !== expected_window_data[idx])
                    $fatal(1, "feature response mismatch index=%0d run=%0d group=%0d tag=%08x mask=%012x",
                           idx, run_index, group_index, response_tag, response_mask);
                response_mask_checks = response_mask_checks + 1;
                window_byte_checks = window_byte_checks + 80;
                window_response_count = window_response_count + 1;
            end else if (active_token_valid && stream_ready) begin
                stream_bubble_cycles = stream_bubble_cycles + 1;
            end

            if (run_valid && run_ready) begin
                if (active_token_valid) $fatal(1, "new run token before previous final post handshake");
                active_token_valid = 1;
                active_token = run_token;
                active_final_post_seen = 0;
            end
            if (active_token_valid && run_token !== active_token)
                $fatal(1, "external run token changed before final post handshake");

            if (previous_raw_stall) begin
                if (!raw_valid || {raw_token,raw_site,raw_last,raw_lanes,raw_data,raw_overflow} !== held_raw)
                    $fatal(1, "raw MAC payload or metadata changed while requantizer stalled");
                raw_stall_hold_checks = raw_stall_hold_checks + 1;
            end
            previous_raw_stall = raw_valid && !raw_ready;
            if (previous_raw_stall) begin
                held_raw = {raw_token,raw_site,raw_last,raw_lanes,raw_data,raw_overflow};
                raw_stall_cycles = raw_stall_cycles + 1;
            end
            if (raw_valid && raw_ready) begin
                idx = raw_beats;
                if (idx >= ROW_WIDTH) $fatal(1, "extra raw MAC result");
                run_index = (idx < (RUNS-1)*SITES) ? idx/SITES : RUNS-1;
                expected_site = (idx < (RUNS-1)*SITES) ? idx%SITES : idx-(RUNS-1)*SITES;
                expected_sites = sites_for_run(run_index);
                if (raw_token !== TOKEN_BASE+run_index || raw_site !== expected_site ||
                    raw_lanes !== 16 || raw_last !== (expected_site==expected_sites-1))
                    $fatal(1, "raw metadata mismatch index=%0d token=%0d site=%0d", idx, raw_token, raw_site);
                for (result_lane = 0; result_lane < 32; result_lane = result_lane + 1) begin
                    if (raw_data[result_lane*32 +: 32] !==
                        expected_raw_words[idx][32+result_lane*32 +: 32])
                        $fatal(1, "raw lane mismatch site=%0d lane=%0d got=%08x expected=%08x",
                               idx, result_lane, raw_data[result_lane*32 +: 32],
                               expected_raw_words[idx][32+result_lane*32 +: 32]);
                    if (raw_overflow[result_lane] !== expected_raw_words[idx][result_lane])
                        $fatal(1, "raw overflow mismatch site=%0d lane=%0d", idx, result_lane);
                    raw_lane_checks = raw_lane_checks + 1;
                    raw_flag_checks = raw_flag_checks + 1;
                end
                raw_beats = raw_beats + 1;
            end

            if (previous_post_stall) begin
                if (!post_valid || {post_epoch,post_token,post_site,post_lanes,post_last,post_data} !== held_post)
                    $fatal(1, "postprocess output changed while packer stalled");
            end
            previous_post_stall = post_valid && !post_ready;
            if (previous_post_stall) begin
                held_post = {post_epoch,post_token,post_site,post_lanes,post_last,post_data};
                post_stall_cycles = post_stall_cycles + 1;
            end
            if (dut.req_out_valid && !dut.req_out_ready) requant_stall_cycles = requant_stall_cycles + 1;
            if (dut.unary_out_valid && !dut.unary_out_ready) unary_stall_cycles = unary_stall_cycles + 1;
            if (dut.side_count == 4) site_fifo_full_cycles = site_fifo_full_cycles + 1;
            if (post_valid && post_ready) begin
                idx = post_beats;
                if (idx >= ROW_WIDTH) $fatal(1, "extra postprocess result");
                run_index = (idx < (RUNS-1)*SITES) ? idx/SITES : RUNS-1;
                expected_site = (idx < (RUNS-1)*SITES) ? idx%SITES : idx-(RUNS-1)*SITES;
                expected_sites = sites_for_run(run_index);
                if (post_epoch !== EPOCH || post_token !== TOKEN_BASE+run_index ||
                    post_site !== expected_site || post_lanes !== 16 ||
                    post_last !== (expected_site==expected_sites-1))
                    $fatal(1, "post metadata mismatch site=%0d token=%0d site_field=%0d", idx, post_token, post_site);
                if (!active_token_valid || post_token !== active_token)
                    $fatal(1, "run token was not stable through final post handshake");
                for (result_lane = 0; result_lane < 32; result_lane = result_lane + 1) begin
                    if (post_data[result_lane*8 +: 8] !== expected_post_words[idx][result_lane*8 +: 8])
                        $fatal(1, "post byte mismatch site=%0d lane=%0d got=%02x expected=%02x",
                               idx, result_lane, post_data[result_lane*8 +: 8],
                               expected_post_words[idx][result_lane*8 +: 8]);
                    if (result_lane < 16) post_active_byte_checks = post_active_byte_checks + 1;
                    else post_tail_byte_checks = post_tail_byte_checks + 1;
                end
                if (post_last) begin
                    active_token_valid = 0;
                    active_final_post_seen = 1;
                end
                post_beats = post_beats + 1;
            end

            if (previous_packed_stall) begin
                if (!packed_valid || {packed_epoch,packed_address,packed_data,packed_last} !== held_packed)
                    $fatal(1, "packer output changed while stalled");
                packed_stall_hold_checks = packed_stall_hold_checks + 1;
            end
            previous_packed_stall = packed_valid && !packed_ready;
            if (previous_packed_stall) begin
                held_packed = {packed_epoch,packed_address,packed_data,packed_last};
                packed_stall_cycles = packed_stall_cycles + 1;
            end
            if (packed_valid && packed_ready) begin
                idx = packed_beats;
                if (idx >= 80) $fatal(1, "extra packed feature word");
                packed_expected_address = (idx % 4)*20 + (idx / 4);
                if (packed_epoch !== EPOCH || packed_address !== packed_expected_address ||
                    packed_last !== (idx==79))
                    $fatal(1, "packed metadata/order mismatch index=%0d address=%0d expected_address=%0d last=%0d",
                           idx, packed_address, packed_expected_address, packed_last);
                if (packed_address >= 80)
                    $fatal(1, "packed address outside first-row feature span: %0d", packed_address);
                if (packed_address_seen[packed_address])
                    $fatal(1, "duplicate packed address index=%0d address=%0d", idx, packed_address);
                if (packed_data !== expected_packed_words[packed_address])
                    $fatal(1, "packed data mismatch index=%0d address=%0d", idx, packed_address);
                packed_address_seen[packed_address] = 1'b1;
                packed_byte_checks = packed_byte_checks + 64;
                packed_beats = packed_beats + 1;
            end
            if (pack_done) begin
                pack_done_count = pack_done_count + 1;
                if (pack_done_count != 1 || packed_beats != 80 ||
                    packed_address_seen !== {80{1'b1}})
                    $fatal(1, "packer done before exactly80 unique accepted addresses");
            end
        end
    end

    initial begin : packed_consumer
        reg [557:0] held;
        wait (rst_n === 1'b1);
        wait (dut.output_packer.buffer_full === 2'b11);
        buffer_full_seen = 1;
        #1;
        if (!packed_valid || packed_ready) $fatal(1, "two full transpose buffers did not hold output");
        held = {packed_epoch,packed_address,packed_data,packed_last};
        repeat (4) begin
            @(posedge clk); #1;
            if (!packed_valid || packed_ready ||
                {packed_epoch,packed_address,packed_data,packed_last} !== held)
                $fatal(1, "held packed output changed before consumer release");
            consumer_hold_checks = consumer_hold_checks + 1;
        end
        @(negedge clk); packed_ready = 1; consumer_released = 1;
    end

    integer i, job, group_id, target_post;
    initial begin
        $readmemh("feature_words.hex", feature_words);
        $readmemh("native_weight_groups.hex", weight_groups);
        $readmemh("native_bias.hex", bias_word);
        $readmemh("req_factors.hex", req_words);
        $readmemh("unary_cfg.hex", unary_bytes);
        $readmemh("expected_windows.hex", expected_window_data);
        $readmemh("expected_window_masks.hex", expected_window_masks);
        $readmemh("expected_raw_words.hex", expected_raw_words);
        $readmemh("expected_post_words.hex", expected_post_words);
        $readmemh("expected_packed_words.hex", expected_packed_words);

        #250; // Vendor global startup for explicit DSP primitives.
        repeat (5) @(negedge clk);
        rst_n = 1;
        load_features();
        load_mac();
        load_requant();
        load_unary();
        configure_packer();

        for (job = 0; job < RUNS; job = job + 1) begin
            start_run(job);
            for (group_id = 0; group_id < GROUPS; group_id = group_id + 1)
                send_descriptor(job, group_id);
            target_post = final_post_count(job);
            while (post_beats < target_post) @(negedge clk);
        end
        while (packed_beats < 80) @(negedge clk);
        wait (pack_done === 1'b1);
        @(posedge clk); #1;

        if (feature_load_count != FEATURE_WORDS || weight_group_load_count != GROUPS ||
            bias_load_count != 1 || req_load_count != 16 || unary_load_count != 256)
            $fatal(1, "configuration was not loaded exactly once: feature=%0d weights=%0d bias=%0d req=%0d unary=%0d",
                   feature_load_count, weight_group_load_count, bias_load_count, req_load_count, unary_load_count);
        if (run_count != RUNS || window_request_count != WINDOW_REQUESTS ||
            window_response_count != WINDOW_REQUESTS || window_byte_checks != WINDOW_REQUESTS*80 ||
            response_mask_checks != WINDOW_REQUESTS)
            $fatal(1, "feature window coverage mismatch runs=%0d requests=%0d responses=%0d bytes=%0d masks=%0d",
                   run_count, window_request_count, window_response_count, window_byte_checks, response_mask_checks);
        if (raw_beats != ROW_WIDTH || raw_lane_checks != ROW_WIDTH*32 || raw_flag_checks != ROW_WIDTH*32)
            $fatal(1, "raw MAC coverage mismatch beats=%0d lanes=%0d flags=%0d", raw_beats, raw_lane_checks, raw_flag_checks);
        if (post_beats != ROW_WIDTH || post_active_byte_checks != ROW_WIDTH*16 ||
            post_tail_byte_checks != ROW_WIDTH*16)
            $fatal(1, "postprocess coverage mismatch beats=%0d active=%0d tails=%0d",
                   post_beats, post_active_byte_checks, post_tail_byte_checks);
        if (packed_beats != 80 || packed_address_seen !== {80{1'b1}} ||
            packed_byte_checks != 80*64 || pack_done_count != 1 ||
            !consumer_released || !buffer_full_seen || consumer_hold_checks != 4 ||
            packed_stall_hold_checks < 4 || post_stall_cycles == 0 ||
            requant_stall_cycles == 0 || unary_stall_cycles == 0)
            $fatal(1, "packer/backpressure coverage missing words=%0d bytes=%0d done=%0d full=%0d hold=%0d post=%0d req=%0d unary=%0d",
                   packed_beats, packed_byte_checks, pack_done_count, buffer_full_seen,
                   consumer_hold_checks, post_stall_cycles, requant_stall_cycles, unary_stall_cycles);
        if (pack_active || packed_valid || pack_error_valid || metadata_error)
            $fatal(1, "pipeline did not retire cleanly");

        $display("NATIVE_ROW20_FACTOR_BUFFER_PASS runs=%0d requests=%0d responses=%0d window_bytes=%0d masks=%0d raw_beats=%0d raw_lanes=%0d raw_flags=%0d post_beats=%0d active_bytes=%0d tail_bytes=%0d packed_words=%0d packed_bytes=%0d feature_loads=%0d weight_groups=%0d bias_loads=%0d req_words=%0d unary_bytes=%0d packed_stall=%0d req_stall=%0d unary_stall=%0d raw_stall=%0d raw_stall_stability=%0d response_stalls=%0d response_stall_stability=%0d bubbles=%0d site_fifo_full=%0d full_buffers=%0d packed_hold_checks=%0d done=%0d raw_backpressure_note=%0d max_runsites=%0d tail_sites=%0d",
                 run_count, window_request_count, window_response_count, window_byte_checks,
                 response_mask_checks, raw_beats, raw_lane_checks, raw_flag_checks,
                 post_beats, post_active_byte_checks, post_tail_byte_checks, packed_beats,
                 packed_byte_checks, feature_load_count, weight_group_load_count, bias_load_count,
                 req_load_count, unary_load_count, packed_stall_cycles, requant_stall_cycles,
                 unary_stall_cycles, raw_stall_cycles, raw_stall_hold_checks,
                 response_stall_cycles, response_stall_hold_checks, stream_bubble_cycles, site_fifo_full_cycles,
                 buffer_full_seen, packed_stall_hold_checks, pack_done_count,
                 (raw_stall_cycles == 0), SITES, ROW_WIDTH-(RUNS-1)*SITES);
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "native row pipeline watchdog timeout");
    end
endmodule
`default_nettype wire
