`default_nettype none
// Private first-convolution row pipeline. The SITES-wide feature response is
// kept intact through the native MAC; no activation sites are truncated.
// run_token remains externally stable from the first descriptor until the
// final packer word for that row job is accepted.
module z100_native_row20_factor #(
    parameter integer SITES = 20,
    parameter integer SITE_FIFO_DEPTH = 4
) (
    input wire clk, input wire rst_n, input wire cancel,

    input wire feature_cfg_begin, output wire feature_cfg_begin_ready,
    input wire [31:0] feature_cfg_epoch, input wire [10:0] feature_cfg_channels,
    input wire [9:0] feature_cfg_height, feature_cfg_width,
    input wire [31:0] feature_cfg_word_epoch,
    input wire [12:0] feature_cfg_word_address,
    input wire feature_cfg_word_last,
    input wire feature_cfg_word_valid, output wire feature_cfg_word_ready,
    input wire [511:0] feature_cfg_data,
    input wire feature_cfg_commit, output wire feature_cfg_commit_ready,
    output wire feature_store_valid, output wire feature_loading,
    output wire [31:0] feature_active_epoch,
    output wire feature_error_valid, output wire [3:0] feature_error_code,

    input wire window_valid, output wire window_ready,
    input wire [31:0] window_epoch, input wire [31:0] window_tag,
    input wire [13:0] window_row_address, input wire signed [11:0] window_first_x,
    input wire [10:0] window_input_width, input wire [10:0] window_output_remaining,
    input wire [4:0] window_sites, input wire [3:0] window_channel_mask,
    input wire window_stride_two, input wire window_y_valid,

    input wire mac_cfg_begin, output wire mac_cfg_begin_ready,
    input wire [31:0] mac_cfg_epoch, input wire [10:0] mac_cfg_groups,
    input wire mac_cfg_weight_valid, output wire mac_cfg_weight_ready,
    input wire [1023:0] mac_cfg_weights, input wire mac_cfg_bias_valid,
    output wire mac_cfg_bias_ready, input wire [1023:0] mac_cfg_bias,
    input wire mac_cfg_commit, output wire mac_cfg_commit_ready,
    output wire mac_weights_valid, output wire [31:0] mac_weights_epoch,
    output wire mac_error_valid, output wire [2:0] mac_error_code,

    input wire run_valid, output wire run_ready,
    input wire [31:0] run_epoch, input wire [31:0] run_token,
    input wire [5:0] run_lanes, input wire [4:0] run_sites,
    output wire stream_valid, output wire stream_ready,
    output wire [31:0] stream_token, output wire stream_last,
    output wire [4*SITES*8-1:0] stream_data,
    output wire [31:0] response_tag, output wire [79:0] response_mask,

    input wire req_cfg_begin, output wire req_cfg_begin_ready,
    input wire [31:0] req_cfg_epoch, input wire [5:0] req_cfg_lanes,
    input wire req_cfg_word_valid, output wire req_cfg_word_ready,
    input wire [30:0] req_cfg_multiplier, input wire [5:0] req_cfg_shift,
    input wire req_cfg_commit, output wire req_cfg_commit_ready,
    output wire req_cfg_error, output wire req_input_error,

    input wire unary_cfg_begin, output wire unary_cfg_begin_ready,
    input wire [31:0] unary_cfg_epoch,
    input wire unary_cfg_word_valid, output wire unary_cfg_word_ready,
    input wire [7:0] unary_cfg_data,
    input wire unary_cfg_commit, output wire unary_cfg_commit_ready,
    output wire unary_error_valid, output wire [2:0] unary_error_code,
    output wire unary_store_valid, output wire [31:0] unary_active_epoch,
    output wire unary_loading,

    output wire raw_valid, output wire raw_ready,
    output wire [31:0] raw_token, output wire [4:0] raw_site,
    output wire raw_last, output wire [5:0] raw_lanes,
    output wire [1023:0] raw_data, output wire [31:0] raw_overflow,

    output wire post_valid, output wire post_ready,
    output wire [31:0] post_epoch, output wire [31:0] post_token,
    output wire [4:0] post_site, output wire [5:0] post_lanes,
    output wire post_last, output wire [255:0] post_data,
    output reg metadata_error,

    input wire pack_cfg_valid, output wire pack_cfg_ready,
    input wire [31:0] pack_cfg_epoch, input wire [10:0] pack_cfg_channels,
    input wire [9:0] pack_cfg_height, input wire [9:0] pack_cfg_width,
    input wire [31:0] pack_cfg_token_base,
    output wire packed_valid, input wire packed_ready,
    output wire [31:0] packed_epoch, output wire [12:0] packed_address,
    output wire [511:0] packed_data, output wire packed_last,
    output wire pack_done, output wire pack_error_valid,
    output wire [2:0] pack_error_code, output wire pack_active
);
    reg [10:0] accepted_responses;
    reg [10:0] pending_groups;
    reg [10:0] committed_groups;
    wire window_out_valid, window_out_ready;
    wire [639:0] window_out_data;
    wire [79:0] window_out_mask;
    wire mac_act_ready;

    z100_feature_window20 feature_window (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(feature_cfg_begin), .cfg_begin_ready(feature_cfg_begin_ready),
        .cfg_epoch(feature_cfg_epoch), .cfg_channels(feature_cfg_channels),
        .cfg_height(feature_cfg_height), .cfg_width(feature_cfg_width),
        .cfg_word_epoch(feature_cfg_word_epoch), .cfg_word_address(feature_cfg_word_address),
        .cfg_word_last(feature_cfg_word_last),
        .cfg_word_valid(feature_cfg_word_valid), .cfg_word_ready(feature_cfg_word_ready),
        .cfg_data(feature_cfg_data), .cfg_commit(feature_cfg_commit),
        .cfg_commit_ready(feature_cfg_commit_ready), .store_valid(feature_store_valid),
        .loading(feature_loading), .active_epoch(feature_active_epoch),
        .error_valid(feature_error_valid), .error_code(feature_error_code),
        .window_valid(window_valid), .window_ready(window_ready),
        .window_epoch(window_epoch), .window_tag(window_tag),
        .window_row_address(window_row_address), .window_first_x(window_first_x),
        .window_input_width(window_input_width),
        .window_output_remaining(window_output_remaining), .window_sites(window_sites),
        .window_channel_mask(window_channel_mask), .window_stride_two(window_stride_two),
        .window_y_valid(window_y_valid), .out_valid(window_out_valid),
        .out_ready(window_out_ready), .out_tag(response_tag),
        .out_mask(window_out_mask), .out_data(window_out_data)
    );

    assign stream_valid = window_out_valid;
    assign stream_ready = mac_act_ready;
    assign stream_token = run_token;
    assign stream_last = mac_weights_valid && (committed_groups != 0) &&
                         (accepted_responses == committed_groups-11'd1);
    assign stream_data = window_out_data;
    assign response_mask = window_out_mask;
    assign window_out_ready = mac_act_ready;

    z100_window_mac #(.SITES(SITES)) native_mac (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(mac_cfg_begin), .cfg_begin_ready(mac_cfg_begin_ready),
        .cfg_epoch(mac_cfg_epoch), .cfg_groups(mac_cfg_groups),
        .cfg_weight_valid(mac_cfg_weight_valid), .cfg_weight_ready(mac_cfg_weight_ready),
        .cfg_weights(mac_cfg_weights), .cfg_bias_valid(mac_cfg_bias_valid),
        .cfg_bias_ready(mac_cfg_bias_ready), .cfg_bias(mac_cfg_bias),
        .cfg_commit(mac_cfg_commit), .cfg_commit_ready(mac_cfg_commit_ready),
        .weights_valid(mac_weights_valid), .weights_epoch(mac_weights_epoch),
        .error_valid(mac_error_valid), .error_code(mac_error_code),
        .run_valid(run_valid), .run_ready(run_ready), .run_epoch(run_epoch),
        .run_token(run_token), .run_lanes(run_lanes), .run_sites(run_sites),
        .act_valid(stream_valid), .act_ready(mac_act_ready), .act_token(stream_token),
        .act_last(stream_last), .act_data(stream_data), .out_valid(raw_valid),
        .out_ready(raw_ready), .out_token(raw_token), .out_site(raw_site),
        .out_last(raw_last), .out_lanes(raw_lanes), .out_data(raw_data),
        .out_overflow(raw_overflow)
    );

    always @(posedge clk) begin
        if (!rst_n || cancel)
            accepted_responses <= 0;
        else if (run_valid && run_ready)
            accepted_responses <= 0;
        else if (stream_valid && stream_ready)
            accepted_responses <= accepted_responses + 1'b1;
    end

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            pending_groups <= 0;
            committed_groups <= 0;
        end else if (mac_cfg_begin && mac_cfg_begin_ready) begin
            pending_groups <= mac_cfg_groups;
            committed_groups <= 0;
        end else if (mac_error_valid) begin
            pending_groups <= 0;
            committed_groups <= 0;
        end else if (mac_cfg_commit && mac_cfg_commit_ready) begin
            committed_groups <= pending_groups;
        end
    end

    wire req_out_valid, req_out_ready;
    wire [31:0] req_out_epoch, req_out_token;
    wire [4:0] req_out_site;
    wire [5:0] req_out_lanes;
    wire req_out_last;
    wire [255:0] req_out_data;
    wire req_in_ready;
    z100_requant_factor32 requant (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(req_cfg_begin), .cfg_begin_ready(req_cfg_begin_ready),
        .cfg_epoch(req_cfg_epoch), .cfg_lanes(req_cfg_lanes),
        .cfg_word_valid(req_cfg_word_valid), .cfg_word_ready(req_cfg_word_ready),
        .cfg_multiplier(req_cfg_multiplier), .cfg_shift(req_cfg_shift), .cfg_commit(req_cfg_commit),
        .cfg_commit_ready(req_cfg_commit_ready), .cfg_error(req_cfg_error),
        .input_error(req_input_error), .in_valid(raw_valid), .in_ready(req_in_ready),
        .in_epoch(mac_weights_epoch), .in_token(raw_token), .in_site(raw_site),
        .in_last(raw_last), .in_data(raw_data), .out_valid(req_out_valid),
        .out_ready(req_out_ready), .out_epoch(req_out_epoch), .out_token(req_out_token),
        .out_site(req_out_site), .out_lanes(req_out_lanes), .out_last(req_out_last),
        .out_data(req_out_data)
    );
    assign raw_ready = req_in_ready;

    wire unary_in_ready, unary_out_valid, unary_out_ready;
    wire [31:0] unary_out_epoch, unary_out_token;
    wire [5:0] unary_out_lanes;
    wire unary_out_last;
    wire [255:0] unary_out_data;
    reg [31:0] side_epoch [0:SITE_FIFO_DEPTH-1];
    reg [31:0] side_token [0:SITE_FIFO_DEPTH-1];
    reg [4:0] side_site [0:SITE_FIFO_DEPTH-1];
    reg [5:0] side_lanes [0:SITE_FIFO_DEPTH-1];
    reg side_last [0:SITE_FIFO_DEPTH-1];
    reg [$clog2(SITE_FIFO_DEPTH)-1:0] side_rd_ptr, side_wr_ptr;
    reg [$clog2(SITE_FIFO_DEPTH+1)-1:0] side_count;
    wire side_room = side_count < SITE_FIFO_DEPTH;
    wire unary_in_valid = req_out_valid && side_room;
    assign req_out_ready = unary_in_ready && side_room;

    z100_unary32 unary (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(unary_cfg_begin), .cfg_begin_ready(unary_cfg_begin_ready),
        .cfg_epoch(unary_cfg_epoch), .cfg_word_valid(unary_cfg_word_valid),
        .cfg_word_ready(unary_cfg_word_ready), .cfg_data(unary_cfg_data),
        .cfg_commit(unary_cfg_commit), .cfg_commit_ready(unary_cfg_commit_ready),
        .error_valid(unary_error_valid), .error_code(unary_error_code),
        .store_valid(unary_store_valid), .active_epoch(unary_active_epoch),
        .loading(unary_loading), .in_valid(unary_in_valid), .in_ready(unary_in_ready),
        .in_epoch(req_out_epoch), .in_token(req_out_token), .in_lanes(req_out_lanes),
        .in_last(req_out_last), .in_data(req_out_data), .out_valid(unary_out_valid),
        .out_ready(unary_out_ready), .out_epoch(unary_out_epoch),
        .out_token(unary_out_token), .out_lanes(unary_out_lanes),
        .out_last(unary_out_last), .out_data(unary_out_data)
    );

    wire pack_in_ready;
    wire side_pop = unary_out_valid && unary_out_ready;
    wire side_push = req_out_valid && req_out_ready;
    assign unary_out_ready = pack_in_ready && (side_count != 0);
    assign post_valid = unary_out_valid && (side_count != 0);
    assign post_epoch = unary_out_epoch;
    assign post_token = unary_out_token;
    assign post_site = side_site[side_rd_ptr];
    assign post_lanes = unary_out_lanes;
    assign post_last = unary_out_last;
    assign post_data = unary_out_data;
    assign post_ready = pack_in_ready;

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            side_rd_ptr <= 0;
            side_wr_ptr <= 0;
            side_count <= 0;
            metadata_error <= 1'b0;
        end else begin
            metadata_error <= 1'b0;
            if (side_push) begin
                side_epoch[side_wr_ptr] <= req_out_epoch;
                side_token[side_wr_ptr] <= req_out_token;
                side_site[side_wr_ptr] <= req_out_site;
                side_lanes[side_wr_ptr] <= req_out_lanes;
                side_last[side_wr_ptr] <= req_out_last;
                side_wr_ptr <= side_wr_ptr + 1'b1;
            end
            if (side_pop)
                side_rd_ptr <= side_rd_ptr + 1'b1;
            case ({side_push, side_pop})
                2'b10: side_count <= side_count + 1'b1;
                2'b01: side_count <= side_count - 1'b1;
                default: side_count <= side_count;
            endcase
            if (unary_out_valid &&
                (side_count == 0 || unary_out_epoch != side_epoch[side_rd_ptr] ||
                 unary_out_token != side_token[side_rd_ptr] ||
                 unary_out_lanes != side_lanes[side_rd_ptr] ||
                 unary_out_last != side_last[side_rd_ptr]))
                metadata_error <= 1'b1;
        end
    end

    z100_native_output_packer #(.SITES(SITES)) output_packer (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_valid(pack_cfg_valid), .cfg_ready(pack_cfg_ready),
        .cfg_epoch(pack_cfg_epoch), .cfg_channels(pack_cfg_channels),
        .cfg_height(pack_cfg_height), .cfg_width(pack_cfg_width),
        .cfg_token_base(pack_cfg_token_base),
        .in_valid(post_valid), .in_ready(pack_in_ready), .in_epoch(post_epoch),
        .in_token(post_token), .in_site(post_site), .in_lanes(post_lanes),
        .in_last(post_last), .in_data(post_data),
        .out_valid(packed_valid), .out_ready(packed_ready), .out_epoch(packed_epoch),
        .out_address(packed_address), .out_data(packed_data), .out_last(packed_last),
        .done(pack_done), .error_valid(pack_error_valid), .error_code(pack_error_code),
        .active(pack_active)
    );
endmodule
`default_nettype wire
