`default_nettype none
// Private first-convolution row pipeline. The SITES-wide feature response is
// kept intact through the native MAC; no activation sites are truncated.
// run_token remains externally stable from the first descriptor until the
// final packer word for that row job is accepted.
module z100_native_row_store #(
    parameter integer SITES = 12,
    parameter integer GROUPS_PER_RUN = 9,
    parameter integer SITE_FIFO_DEPTH = 4
) (
    input wire clk, input wire rst_n, input wire cancel,

    input wire feature_cfg_begin, output wire feature_cfg_begin_ready,
    input wire [31:0] feature_cfg_epoch, input wire [13:0] feature_cfg_words,
    input wire feature_cfg_word_valid, output wire feature_cfg_word_ready,
    input wire [511:0] feature_cfg_data,
    input wire feature_cfg_commit, output wire feature_cfg_commit_ready,
    output wire feature_store_valid, output wire feature_loading,
    output wire [31:0] feature_active_epoch,
    output wire feature_error_valid, output wire [2:0] feature_error_code,

    input wire window_valid, output wire window_ready,
    input wire [31:0] window_epoch, input wire [31:0] window_tag,
    input wire [13:0] window_row_address, input wire signed [11:0] window_first_x,
    input wire [10:0] window_input_width, input wire [10:0] window_output_remaining,
    input wire [3:0] window_sites, input wire [3:0] window_channel_mask,
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
    input wire [5:0] run_lanes, input wire [3:0] run_sites,
    output wire stream_valid, output wire stream_ready,
    output wire [31:0] stream_token, output wire stream_last,
    output wire [4*SITES*8-1:0] stream_data,
    output wire [31:0] response_tag, output wire [47:0] response_mask,

    input wire req_cfg_begin, output wire req_cfg_begin_ready,
    input wire [31:0] req_cfg_epoch, input wire [5:0] req_cfg_lanes,
    input wire req_cfg_word_valid, output wire req_cfg_word_ready,
    input wire [1055:0] req_cfg_keys,
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
    output wire [31:0] raw_token, output wire [3:0] raw_site,
    output wire raw_last, output wire [5:0] raw_lanes,
    output wire [1023:0] raw_data, output wire [31:0] raw_overflow,

    output wire post_valid, output wire post_ready,
    output wire [31:0] post_epoch, output wire [31:0] post_token,
    output wire [3:0] post_site, output wire [5:0] post_lanes,
    output wire post_last, output wire [255:0] post_data,
    output reg metadata_error,

    input wire pack_cfg_valid, output wire pack_cfg_ready,
    input wire [31:0] pack_cfg_epoch, input wire [10:0] pack_cfg_channels,
    input wire [9:0] pack_cfg_height, input wire [9:0] pack_cfg_width,
    input wire [31:0] pack_cfg_token_base,
    output wire packed_valid, output wire packed_ready,
    output wire [31:0] packed_epoch, output wire [12:0] packed_address,
    output wire [511:0] packed_data, output wire packed_last,
    output wire pack_done, output wire pack_error_valid,
    output wire [2:0] pack_error_code, output wire pack_active,
    input wire sink_enable,
    output reg store_fault,
    output wire output_store_valid, output wire [31:0] output_store_epoch,
    input wire next_window_valid, output wire next_window_ready,
    input wire [31:0] next_window_epoch, next_window_tag,
    input wire [13:0] next_window_row_address,
    input wire signed [11:0] next_window_first_x,
    input wire [10:0] next_window_input_width, next_window_output_remaining,
    input wire [3:0] next_window_sites, next_window_channel_mask,
    input wire next_window_stride_two, next_window_y_valid,
    output wire next_out_valid, input wire next_out_ready,
    output wire [31:0] next_out_tag,
    output wire [47:0] next_out_mask,
    output wire [383:0] next_out_data
);
    // Packer and destination geometry are accepted atomically. No reader can
    // observe a partial feature epoch. Only a complete pack_done can commit.
    wire pipeline_cancel=cancel || store_fault;
    wire row_pack_cfg_ready, bank_begin_ready;
    wire row_pack_cfg_valid=pack_cfg_valid && bank_begin_ready && !store_fault;
    wire bank_begin=pack_cfg_valid && row_pack_cfg_ready && !store_fault;
    wire bank_word_ready, bank_commit_ready, bank_error;
    wire [2:0] bank_error_code;
    wire bank_store_valid, bank_loading;
    wire [31:0] bank_epoch;
    reg commit_pending;
    assign pack_cfg_ready=row_pack_cfg_ready && bank_begin_ready && !store_fault;
    assign packed_ready=sink_enable && bank_word_ready && !store_fault;
    assign output_store_valid=bank_store_valid && !store_fault && !cancel;
    assign output_store_epoch=output_store_valid ? bank_epoch : 32'd0;
    always @(posedge clk) begin
        if(!rst_n || cancel) begin
            store_fault<=0;
            commit_pending<=0;
        end else begin
            if(feature_error_valid || mac_error_valid || req_cfg_error || req_input_error ||
               unary_error_valid || metadata_error || pack_error_valid || bank_error) begin
                store_fault<=1;
                commit_pending<=0;
            end else if(!store_fault) begin
                if(pack_done) commit_pending<=1;
                if(commit_pending && bank_commit_ready) commit_pending<=0;
            end
        end
    end
    z100_native_row_pipeline #(.SITES(SITES), .GROUPS_PER_RUN(GROUPS_PER_RUN),
        .SITE_FIFO_DEPTH(SITE_FIFO_DEPTH)) row (
        .clk(clk),
        .rst_n(rst_n),
        .cancel(pipeline_cancel),
        .feature_cfg_begin(feature_cfg_begin),
        .feature_cfg_begin_ready(feature_cfg_begin_ready),
        .feature_cfg_epoch(feature_cfg_epoch),
        .feature_cfg_words(feature_cfg_words),
        .feature_cfg_word_valid(feature_cfg_word_valid),
        .feature_cfg_word_ready(feature_cfg_word_ready),
        .feature_cfg_data(feature_cfg_data),
        .feature_cfg_commit(feature_cfg_commit),
        .feature_cfg_commit_ready(feature_cfg_commit_ready),
        .feature_store_valid(feature_store_valid),
        .feature_loading(feature_loading),
        .feature_active_epoch(feature_active_epoch),
        .feature_error_valid(feature_error_valid),
        .feature_error_code(feature_error_code),
        .window_valid(window_valid),
        .window_ready(window_ready),
        .window_epoch(window_epoch),
        .window_tag(window_tag),
        .window_row_address(window_row_address),
        .window_first_x(window_first_x),
        .window_input_width(window_input_width),
        .window_output_remaining(window_output_remaining),
        .window_sites(window_sites),
        .window_channel_mask(window_channel_mask),
        .window_stride_two(window_stride_two),
        .window_y_valid(window_y_valid),
        .mac_cfg_begin(mac_cfg_begin),
        .mac_cfg_begin_ready(mac_cfg_begin_ready),
        .mac_cfg_epoch(mac_cfg_epoch),
        .mac_cfg_groups(mac_cfg_groups),
        .mac_cfg_weight_valid(mac_cfg_weight_valid),
        .mac_cfg_weight_ready(mac_cfg_weight_ready),
        .mac_cfg_weights(mac_cfg_weights),
        .mac_cfg_bias_valid(mac_cfg_bias_valid),
        .mac_cfg_bias_ready(mac_cfg_bias_ready),
        .mac_cfg_bias(mac_cfg_bias),
        .mac_cfg_commit(mac_cfg_commit),
        .mac_cfg_commit_ready(mac_cfg_commit_ready),
        .mac_weights_valid(mac_weights_valid),
        .mac_weights_epoch(mac_weights_epoch),
        .mac_error_valid(mac_error_valid),
        .mac_error_code(mac_error_code),
        .run_valid(run_valid),
        .run_ready(run_ready),
        .run_epoch(run_epoch),
        .run_token(run_token),
        .run_lanes(run_lanes),
        .run_sites(run_sites),
        .stream_valid(stream_valid),
        .stream_ready(stream_ready),
        .stream_token(stream_token),
        .stream_last(stream_last),
        .stream_data(stream_data),
        .response_tag(response_tag),
        .response_mask(response_mask),
        .req_cfg_begin(req_cfg_begin),
        .req_cfg_begin_ready(req_cfg_begin_ready),
        .req_cfg_epoch(req_cfg_epoch),
        .req_cfg_lanes(req_cfg_lanes),
        .req_cfg_word_valid(req_cfg_word_valid),
        .req_cfg_word_ready(req_cfg_word_ready),
        .req_cfg_keys(req_cfg_keys),
        .req_cfg_commit(req_cfg_commit),
        .req_cfg_commit_ready(req_cfg_commit_ready),
        .req_cfg_error(req_cfg_error),
        .req_input_error(req_input_error),
        .unary_cfg_begin(unary_cfg_begin),
        .unary_cfg_begin_ready(unary_cfg_begin_ready),
        .unary_cfg_epoch(unary_cfg_epoch),
        .unary_cfg_word_valid(unary_cfg_word_valid),
        .unary_cfg_word_ready(unary_cfg_word_ready),
        .unary_cfg_data(unary_cfg_data),
        .unary_cfg_commit(unary_cfg_commit),
        .unary_cfg_commit_ready(unary_cfg_commit_ready),
        .unary_error_valid(unary_error_valid),
        .unary_error_code(unary_error_code),
        .unary_store_valid(unary_store_valid),
        .unary_active_epoch(unary_active_epoch),
        .unary_loading(unary_loading),
        .raw_valid(raw_valid),
        .raw_ready(raw_ready),
        .raw_token(raw_token),
        .raw_site(raw_site),
        .raw_last(raw_last),
        .raw_lanes(raw_lanes),
        .raw_data(raw_data),
        .raw_overflow(raw_overflow),
        .post_valid(post_valid),
        .post_ready(post_ready),
        .post_epoch(post_epoch),
        .post_token(post_token),
        .post_site(post_site),
        .post_lanes(post_lanes),
        .post_last(post_last),
        .post_data(post_data),
        .metadata_error(metadata_error),
        .pack_cfg_valid(row_pack_cfg_valid),
        .pack_cfg_ready(row_pack_cfg_ready),
        .pack_cfg_epoch(pack_cfg_epoch),
        .pack_cfg_channels(pack_cfg_channels),
        .pack_cfg_height(pack_cfg_height),
        .pack_cfg_width(pack_cfg_width),
        .pack_cfg_token_base(pack_cfg_token_base),
        .packed_valid(packed_valid),
        .packed_ready(packed_ready),
        .packed_epoch(packed_epoch),
        .packed_address(packed_address),
        .packed_data(packed_data),
        .packed_last(packed_last),
        .pack_done(pack_done),
        .pack_error_valid(pack_error_valid),
        .pack_error_code(pack_error_code),
        .pack_active(pack_active)
    );
    z100_feature_window_addressed output_window (
        .clk(clk), .rst_n(rst_n), .cancel(pipeline_cancel),
        .cfg_begin(bank_begin), .cfg_begin_ready(bank_begin_ready),
        .cfg_epoch(pack_cfg_epoch), .cfg_channels(pack_cfg_channels),
        .cfg_height(pack_cfg_height), .cfg_width(pack_cfg_width),
        .cfg_word_epoch(packed_epoch), .cfg_word_address(packed_address),
        .cfg_word_last(packed_last),
        .cfg_word_valid(packed_valid && sink_enable && !store_fault),
        .cfg_word_ready(bank_word_ready), .cfg_data(packed_data),
        .cfg_commit(commit_pending && !store_fault), .cfg_commit_ready(bank_commit_ready),
        .store_valid(bank_store_valid), .loading(bank_loading), .active_epoch(bank_epoch),
        .error_valid(bank_error), .error_code(bank_error_code),
        .window_valid(next_window_valid && !store_fault), .window_ready(next_window_ready),
        .window_epoch(next_window_epoch), .window_tag(next_window_tag),
        .window_row_address(next_window_row_address), .window_first_x(next_window_first_x),
        .window_input_width(next_window_input_width),
        .window_output_remaining(next_window_output_remaining), .window_sites(next_window_sites),
        .window_channel_mask(next_window_channel_mask), .window_stride_two(next_window_stride_two),
        .window_y_valid(next_window_y_valid), .out_valid(next_out_valid), .out_ready(next_out_ready),
        .out_tag(next_out_tag), .out_mask(next_out_mask), .out_data(next_out_data)
    );
endmodule
`default_nettype wire
