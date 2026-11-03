`timescale 1ns/1ps
`default_nettype none
// v13c copy of build/pmcore/20261028_pool_metadata_core_golden_v1/
// tb_z100_feature_input_capture_v12_numeric.sv. Only change: the v3-only
// cycle-exact Pool bind monitor (tapxy_monitor) is replaced by the existing
// word-by-word pool_gold check (1280 words) plus a simulated-time print.
module tb_z100_core_golden_v13c;
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
    reg score_reset=0;

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

    wire mac_cfg_begin;
    wire mac_cfg_begin_ready;
    wire [31:0] mac_cfg_epoch;
    wire [10:0] mac_cfg_groups;
    wire mac_cfg_weight_valid;
    wire mac_cfg_weight_ready;
    wire [1023:0] mac_cfg_weights;
    wire mac_cfg_bias_valid;
    wire mac_cfg_bias_ready;
    wire [1023:0] mac_cfg_bias;
    wire mac_cfg_commit;
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

    wire req_cfg_begin;
    wire req_cfg_begin_ready;
    wire [31:0] req_cfg_epoch;
    wire [5:0] req_cfg_lanes;
    wire req_cfg_word_valid;
    wire req_cfg_word_ready;
    wire [30:0] req_cfg_multiplier;
    wire [5:0] req_cfg_shift;
    wire req_cfg_commit;
    wire req_cfg_commit_ready;
    wire req_cfg_error;
    wire req_input_error;

    wire unary_cfg_begin;
    wire unary_cfg_begin_ready;
    wire [31:0] unary_cfg_epoch;
    wire unary_cfg_word_valid;
    wire unary_cfg_word_ready;
    wire [7:0] unary_cfg_data;
    wire unary_cfg_commit;
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
    reg conv_allow = 0;wire packed_ready;
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

    reg pool_job_valid=1'b0,pool_allow=1'b1;wire pool_packed_ready;
    reg [31:0] pool_job_epoch=EPOCH+1;
    reg [10:0] pool_job_channels=128;
    reg [9:0] pool_job_height=20,pool_job_width=20;
    wire pool_job_ready,pool_packed_valid,pool_packed_last,pool_done,pool_error,pool_active;
    wire [31:0] pool_packed_epoch;wire [12:0] pool_packed_address;wire [511:0] pool_packed_data;wire [3:0] pool_error_code;
    `include "hybrid_prefetch_support.vh"
    `include "compute_write_support.vh"
    `include "compute_parameter_support_v2.vh"
    `include "compute_shared_read_support_v4.vh"
    z100_native_row20_shared_pool_address_shared_local_control_v12 #(.SITES(SITES),
                               .SITE_FIFO_DEPTH(4)) dut (
        .cancel(cancel||pf_semantic_cancel||ga_fault||ga_cfg_error||pp_core_cancel),.feature_cfg_canonical_order(ga_input),.feature_load_bank(ga_input?1'b0:pf_active?pf_bank_pin:old_load_bank),.compute_source_bank(compute_source_bank),
         .feature_cfg_begin(ga_input?ga_begin:pf_active?pf_cb:feature_cfg_begin),.feature_cfg_epoch(ga_input?EPOCH:pf_active?pf_epoch:feature_cfg_epoch),.feature_cfg_channels(ga_input?11'd3:pf_active?pf_channels:feature_cfg_channels),
        .feature_cfg_height(ga_input?10'd2:pf_active?pf_height:feature_cfg_height),.feature_cfg_width(ga_input?10'd640:pf_active?pf_width:feature_cfg_width),
        .feature_cfg_word_valid(ga_input?(ga_v&&pf_sink_allow):pf_active?(pf_v&&pf_sink_allow):feature_cfg_word_valid),.feature_cfg_word_epoch(ga_input?ga_oe:pf_active?pf_ep:feature_cfg_word_epoch),
        .feature_cfg_word_address(ga_input?ga_oa[12:0]:pf_active?pf_word_address:feature_cfg_word_address),.feature_cfg_word_last(ga_input?ga_last:pf_active?pf_last:feature_cfg_word_last),
        .feature_cfg_data(ga_input?ga_od:pf_active?pf_data:feature_cfg_data),.feature_cfg_commit(ga_input?ga_commit:pf_active?pf_commit:feature_cfg_commit),.*);

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
            if(!pp_configured||pp_active)$fatal(1,"Parameter load not complete before run");
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
        if (!rst_n||score_reset) begin
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

            if ((feature_cfg_word_valid || (ga_input&&ga_v&&pf_sink_allow)) && feature_cfg_word_ready) feature_load_count = feature_load_count + 1;
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
        @(negedge clk); conv_allow = 1; consumer_released = 1;
    end

    reg [511:0] pool_input_words[0:1279],pool_gold_words[0:1279];
    reg [12:0] pool_addresses[0:1279];
    integer pool_words=0,pool_cycles=0,pool_holds=0,exclusive_probes=0;
    reg pool_held=0;reg [511:0] pool_held_data;reg [12:0] pool_held_address;
    always @(negedge clk)begin
        pool_cycles=pool_cycles+1;
        pool_allow=(pool_cycles%41)>10;
    end
    always @(posedge clk)begin
        if(rst_n)begin
            if(pool_error)$fatal(1,"shared pool error=%0d",pool_error_code);
            if(pool_held&&(!pool_packed_valid||pool_packed_data!==pool_held_data||pool_packed_address!==pool_held_address))$fatal(1,"shared pool held result corruption");
            pool_held=pool_packed_valid&&!pool_packed_ready;
            if(pool_held)begin pool_holds=pool_holds+1;pool_held_data=pool_packed_data;pool_held_address=pool_packed_address;end
            if(pool_packed_valid&&pool_packed_ready)begin
                if(pool_words>=1280||pool_packed_data!==pool_gold_words[pool_words]||pool_packed_address!==pool_addresses[pool_words]||
                   pool_packed_epoch!=EPOCH+1||pool_packed_last!==(pool_words==1279))$fatal(1,"shared mode pool numeric mismatch word=%0d",pool_words);
                pool_words=pool_words+1;
            end
        end
    end
    task shared_pool_pass;integer k;begin
        $readmemh("pool_input.hex",pool_input_words);$readmemh("pool_gold.hex",pool_gold_words);$readmemh("pool_addresses.hex",pool_addresses);
        wait(pf_completed);@(negedge clk);old_load_bank=1;compute_source_bank=1;
        if(!feature_store_valid||feature_active_epoch!=EPOCH+1)$fatal(1,"prefetched B bank not ready for Pool");
        pool_job_valid=1;#1;if(!pool_job_ready)$fatal(1,"shared pool job not admitted");
        @(posedge clk);#1;@(negedge clk);pool_job_valid=0;
        repeat(10)@(negedge clk);
        // Conflicting producer/control requests may not take the pool's store.
        window_valid=1;run_valid=1;pack_cfg_valid=1;feature_cfg_begin=1;feature_cfg_word_valid=1;feature_cfg_commit=1;
        repeat(8)begin
            #1;if(window_ready||run_ready||pack_cfg_ready||feature_cfg_begin_ready||feature_cfg_word_ready||feature_cfg_commit_ready)
                $fatal(1,"shared cache owner violated");
            exclusive_probes=exclusive_probes+1;@(negedge clk);
        end
        window_valid=0;run_valid=0;pack_cfg_valid=0;feature_cfg_begin=0;feature_cfg_word_valid=0;feature_cfg_commit=0;
        wait(pool_done);@(posedge clk);#1;
        if(pool_words!=1280||pool_holds==0||pool_active||dut.pool_owned||dut.conv_owned)$fatal(1,"shared pool retirement/ownership");
    end endtask

    integer wb_check_job,wb_check_word,wb_check_beat,wb_canonical,wb_verified=0,wb_guard;
    reg [511:0] wb_expected;
    task check_output_DDR;begin
        wait(wb_completed==3);@(negedge clk);
        if(wb_scheduled!=3||wb_packed!=1440||wb_aws!=720||wb_bs!=720||wb_ws!=11520||wb_active||wb_wbusy)
            $fatal(1,"Actual output writeback coverage jobs=%d packed=%d AW=%d W=%d B=%d",wb_completed,wb_packed,wb_aws,wb_ws,wb_bs);
        for(wb_check_job=0;wb_check_job<3;wb_check_job=wb_check_job+1)
            for(wb_check_word=0;wb_check_word<(wb_check_job==1 ? 1280 : 80);wb_check_word=wb_check_word+1)begin
                wb_canonical=(wb_check_word%4)*20+wb_check_word/4;
                wb_expected=wb_check_job==1 ? pool_gold_words[wb_check_word] : expected_packed_words[wb_canonical];
                for(wb_check_beat=0;wb_check_beat<8;wb_check_beat=wb_check_beat+1)begin
                    if(wb_memory[wb_check_job*16384+wb_check_word*8+wb_check_beat]!==wb_expected[wb_check_beat*64+:64])
                        $fatal(1,"Actual compute DDR value mismatch job=%d word=%d beat=%d",wb_check_job,wb_check_word,wb_check_beat);
                    wb_verified=wb_verified+1;
                end
            end
        for(wb_guard=0;wb_guard<65536;wb_guard=wb_guard+1)
            if(!((wb_guard<640)||(wb_guard>=16384&&wb_guard<26624)||(wb_guard>=32768&&wb_guard<33408)))
                if(wb_memory[wb_guard]!==64'h5a1bc43df609728e)$fatal(1,"Writeback clobbered unreserved output bytes");
        $display("SHARED_COMPUTE_WRITEBACK_PASS jobs=%0d packed_words=%0d DDR_beats_verified=%0d AXI_AW=%0d AXI_W=%0d AXI_B=%0d guards_checked=54016 publication_after_B=3",wb_completed,wb_packed,wb_verified,wb_aws,wb_ws,wb_bs);
    end endtask
    initial begin for(wb_guard=0;wb_guard<65536;wb_guard=wb_guard+1)wb_memory[wb_guard]=64'h5a1bc43df609728e;end
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
        fork
            load_gather_A();
            load_parameters_DDR();
        join
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

        $display("NATIVE_ROW20_SHARED_CONV_PASS runs=%0d requests=%0d responses=%0d window_bytes=%0d masks=%0d raw_beats=%0d raw_lanes=%0d raw_flags=%0d post_beats=%0d active_bytes=%0d tail_bytes=%0d packed_words=%0d packed_bytes=%0d feature_loads=%0d weight_groups=%0d bias_loads=%0d req_words=%0d unary_bytes=%0d packed_stall=%0d req_stall=%0d unary_stall=%0d raw_stall=%0d raw_stall_stability=%0d response_stalls=%0d response_stall_stability=%0d bubbles=%0d site_fifo_full=%0d full_buffers=%0d packed_hold_checks=%0d done=%0d raw_backpressure_note=%0d max_runsites=%0d tail_sites=%0d",
                 run_count, window_request_count, window_response_count, window_byte_checks,
                 response_mask_checks, raw_beats, raw_lane_checks, raw_flag_checks,
                 post_beats, post_active_byte_checks, post_tail_byte_checks, packed_beats,
                 packed_byte_checks, feature_load_count, weight_group_load_count, bias_load_count,
                 req_load_count, unary_load_count, packed_stall_cycles, requant_stall_cycles,
                 unary_stall_cycles, raw_stall_cycles, raw_stall_hold_checks,
                 response_stall_cycles, response_stall_hold_checks, stream_bubble_cycles, site_fifo_full_cycles,
                 buffer_full_seen, packed_stall_hold_checks, pack_done_count,
                 (raw_stall_cycles == 0), SITES, ROW_WIDTH-(RUNS-1)*SITES);
        wait(wb_completed==1);shared_pool_pass();wait(wb_completed==2);
        // Only the TB scoreboard is reset: no DUT reset/cancel between modes.
        @(negedge clk);score_reset=1;@(posedge clk);#1;@(negedge clk);score_reset=0;
        compute_source_bank=0;old_load_bank=0;feature_cfg_channels=3;feature_cfg_height=2;feature_cfg_width=640;
        #1;if(!feature_store_valid||feature_active_epoch!=EPOCH)$fatal(1,"retained A cache lost after B load/Pool");
        if(!mac_weights_valid||mac_weights_epoch!=EPOCH||!unary_store_valid||unary_active_epoch!=EPOCH)$fatal(1,"pool disturbed resident Conv parameters");
        configure_packer();
        for(job=0;job<RUNS;job=job+1)begin
            start_run(job);
            for(group_id=0;group_id<GROUPS;group_id=group_id+1)send_descriptor(job,group_id);
            target_post=final_post_count(job);while(post_beats<target_post)@(negedge clk);
        end
        while(packed_beats<80)@(negedge clk);wait(pack_done);@(posedge clk);#1;
        if(run_count!=16||raw_lane_checks!=10240||post_active_byte_checks!=5120||packed_beats!=80||pack_done_count!=1||
           weight_group_load_count!=0||req_load_count!=0||unary_load_count!=0||exclusive_probes!=8||pool_words!=1280||pool_error)
            $fatal(1,"shared mode switching proof incomplete");
        $display("SHARED_PINGPONG_PREFETCH_PASS conv_runs=32 conv_raw_lanes=20480 conv_words=160 pool_words=%0d pool_stalls=%0d exclusion_probes=%0d parameter_reloads_after_pool=0 DUT_reset_between_modes=0",pool_words,pool_holds,exclusive_probes);
        if(feature_load_count!=0||pf_loaded!=1280||pf_overlap_loads==0||pf_simultaneous==0||!dut.feature_window.sv[0]||!dut.feature_window.sv[1])$fatal(1,"retained/prefetched source bank proof incomplete");
        $display("PINGPONG_AXI_PREFETCH_PASS words=%0d commands=%0d AXI_AR=%0d AXI_R=%0d overlap_cycles=%0d overlap_loads=%0d simultaneous_window_load=%0d latched_bank_probes=%0d active_bank_rejections=%0d retained_A_reloads=0",pf_loaded,pf_commands,pf_ars,pf_rbeats,pf_overlap_cycles,pf_overlap_loads,pf_simultaneous,pf_bank_latch_probes,pf_active_bank_probes);
        if(ga_loaded!=80||ga_ars!=80||ga_rbeats!=640||lease_acquires!=2||lease_releases!=2||lease_valid)$fatal(1,"hybrid gather/compute/burst reader ownership incomplete");
        $display("SHARED_HYBRID_COUPLING_PASS inputA_words=%0d inputA_AXI_AR=%0d inputA_AXI_R=%0d lease_acquires=%0d lease_releases=%0d",ga_loaded,ga_ars,ga_rbeats,lease_acquires,lease_releases);
        // v13c: the Pool is not cycle-identical to v3, so the v3 bind miter
        // cannot apply. Numeric equality of all 1280 words vs pool_gold is
        // enforced in the always block above; re-check the count here.
        if(pool_words!=1280||pool_error)$fatal(1,"Integrated v13c Pool golden coverage");
        $display("V13C_POOL_GOLDEN_PASS pool_words=%0d pool_holds=%0d",pool_words,pool_holds);
        check_shared_read();
        check_output_DDR();
        if(pp_jobs!=1||pp_configs!=288||pp_commands!=4||pp_ars!=14||pp_beats!=224||pp_fault||pp_rbusy||!pp_configured)$fatal(1,"Parameter computation integration coverage");
        $display("PARAMETER_COMPUTE20_PASS parameter_jobs=1 config_commands=288 reader_commands=4 AXI_AR=14 AXI_R=224 compute_jobs=3 retained_parameter_reloads=0");
        $display("V13C_SIM_END_NS %0t", $time);$finish;
    end

    initial begin
        #10000000;
        $fatal(1, "native row pipeline watchdog timeout");
    end
endmodule
`default_nettype wire
