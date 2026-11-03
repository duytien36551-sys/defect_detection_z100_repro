`default_nettype none
// Private first-convolution bridge for the frozen feature-window and native
// MAC components. One accepted window response is one four-channel MAC group.
// Bounded fixture contract: run_token is externally owned and must stay fixed
// from the first queued window through the final drained output. A production
// scheduler still needs a captured job descriptor and error/cancel admission.
module z100_window_mac_bridge #(
    parameter integer GROUPS_PER_RUN = 9
) (
    input wire clk,
    input wire rst_n,
    input wire cancel,

    input wire feature_cfg_begin,
    output wire feature_cfg_begin_ready,
    input wire [31:0] feature_cfg_epoch,
    input wire [13:0] feature_cfg_words,
    input wire feature_cfg_word_valid,
    output wire feature_cfg_word_ready,
    input wire [511:0] feature_cfg_data,
    input wire feature_cfg_commit,
    output wire feature_cfg_commit_ready,
    output wire feature_store_valid,
    output wire feature_loading,
    output wire [31:0] feature_active_epoch,
    output wire feature_error_valid,
    output wire [2:0] feature_error_code,

    input wire window_valid,
    output wire window_ready,
    input wire [31:0] window_epoch,
    input wire [31:0] window_tag,
    input wire [13:0] window_row_address,
    input wire signed [11:0] window_first_x,
    input wire [10:0] window_input_width,
    input wire [10:0] window_output_remaining,
    input wire [3:0] window_sites,
    input wire [3:0] window_channel_mask,
    input wire window_stride_two,
    input wire window_y_valid,

    input wire mac_cfg_begin,
    output wire mac_cfg_begin_ready,
    input wire [31:0] mac_cfg_epoch,
    input wire [10:0] mac_cfg_groups,
    input wire mac_cfg_weight_valid,
    output wire mac_cfg_weight_ready,
    input wire [1023:0] mac_cfg_weights,
    input wire mac_cfg_bias_valid,
    output wire mac_cfg_bias_ready,
    input wire [1023:0] mac_cfg_bias,
    input wire mac_cfg_commit,
    output wire mac_cfg_commit_ready,
    output wire mac_weights_valid,
    output wire [31:0] mac_weights_epoch,
    output wire mac_error_valid,
    output wire [2:0] mac_error_code,

    input wire run_valid,
    output wire run_ready,
    input wire [31:0] run_epoch,
    input wire [31:0] run_token,
    input wire [5:0] run_lanes,
    input wire [3:0] run_sites,

    output wire stream_valid,
    output wire stream_ready,
    output wire [31:0] stream_token,
    output wire stream_last,
    output wire [127:0] stream_data,
    output wire [31:0] response_tag,
    output wire [47:0] response_mask,

    output wire out_valid,
    input wire out_ready,
    output wire [31:0] out_token,
    output wire [3:0] out_site,
    output wire out_last,
    output wire [5:0] out_lanes,
    output wire [1023:0] out_data,
    output wire [31:0] out_overflow
);
    localparam integer SITES = 4;

    wire window_out_valid;
    wire window_out_ready;
    wire [383:0] window_out_data;
    reg [10:0] accepted_responses;
    genvar channel, site;

    z100_feature_window feature_window (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(feature_cfg_begin), .cfg_begin_ready(feature_cfg_begin_ready),
        .cfg_epoch(feature_cfg_epoch), .cfg_words(feature_cfg_words),
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
        .out_ready(window_out_ready), .out_tag(response_tag), .out_mask(response_mask),
        .out_data(window_out_data)
    );

    wire [127:0] activation_data;
    generate
        for (channel = 0; channel < 4; channel = channel + 1) begin : gen_channel
            for (site = 0; site < SITES; site = site + 1) begin : gen_site
                assign activation_data[(channel*SITES+site)*8 +: 8] =
                    window_out_data[(channel*12+site)*8 +: 8];
            end
        end
    endgenerate

    assign stream_valid = window_out_valid;
    assign stream_data = activation_data;
    assign stream_token = run_token;
    assign stream_last = (accepted_responses == GROUPS_PER_RUN-1);
    assign stream_ready = window_out_ready;

    wire mac_act_ready;
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
        .act_last(stream_last), .act_data(stream_data), .out_valid(out_valid),
        .out_ready(out_ready), .out_token(out_token), .out_site(out_site),
        .out_last(out_last), .out_lanes(out_lanes), .out_data(out_data),
        .out_overflow(out_overflow)
    );

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            accepted_responses <= 0;
        end else begin
            if (run_valid && run_ready)
                accepted_responses <= 0;
            else if (stream_valid && stream_ready)
                accepted_responses <= accepted_responses + 1'b1;
        end
    end
endmodule
`default_nettype wire
