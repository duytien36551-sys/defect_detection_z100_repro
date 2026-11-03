`default_nettype none
// Private20-site resident-row command scheduler. It serializes one resident
// 32-lane output group across a row, then waits for the matching postprocess
// drain acknowledgement before advancing the externally visible run token.
(* use_dsp = "no" *)
module z100_native_row_scheduler20 (
    input wire clk,
    input wire rst_n,
    input wire cancel,

    input wire cmd_valid,
    output wire cmd_ready,
    input wire [31:0] cmd_epoch,
    input wire [31:0] cmd_token_base,
    input wire [31:0] cmd_tag_base,
    input wire [10:0] cmd_channels,
    input wire [9:0] cmd_input_width,
    input wire [9:0] cmd_output_width,
    input wire [1:0] cmd_kernel,
    input wire [1:0] cmd_stride,
    input wire [1:0] cmd_padding,
    input wire [5:0] cmd_lanes,
    input wire [13:0] cmd_bank_words,
    input wire [13:0] cmd_channel_plane_stride,
    input wire [41:0] cmd_ky_row_bases,
    input wire [2:0] cmd_y_valid,

    output wire run_valid,
    input wire run_ready,
    output wire [31:0] run_epoch,
    output wire [31:0] run_token,
    output wire [5:0] run_lanes,
    output wire [4:0] run_sites,

    output wire window_valid,
    input wire window_ready,
    output wire [31:0] window_epoch,
    output wire [31:0] window_tag,
    output wire [13:0] window_row_address,
    output wire signed [11:0] window_first_x,
    output wire [10:0] window_input_width,
    output wire [10:0] window_output_remaining,
    output wire [4:0] window_sites,
    output wire [3:0] window_channel_mask,
    output wire window_stride_two,
    output wire window_y_valid,

    input wire post_done_valid,
    output wire post_done_ready,
    input wire [31:0] post_done_epoch,
    input wire [31:0] post_done_token,
    output reg done,
    output reg abort_pulse,
    output reg fault_valid,
    output reg [2:0] fault_code,
    output wire active
);
    localparam [2:0] ST_IDLE = 3'd0;
    localparam [2:0] ST_RUN = 3'd1;
    localparam [2:0] ST_WINDOWS = 3'd2;
    localparam [2:0] ST_POST = 3'd3;

    reg [2:0] state;
    reg [31:0] epoch_q, token_q, tag_q;
    reg [10:0] channels_q;
    reg [9:0] input_width_q, output_width_q;
    reg [1:0] kernel_q, stride_q, padding_q;
    reg [5:0] lanes_q;
    reg [13:0] bank_words_q, plane_stride_q;
    reg [41:0] ky_bases_q;
    reg [2:0] y_valid_q;
    reg [8:0] channel_groups_q;
    reg [10:0] group_count_q;
    reg [9:0] output_x_q;
    reg [4:0] current_sites_q;
    reg [7:0] group4_q;
    reg [1:0] ky_q, kx_q;
    reg [10:0] descriptor_index_q;
    reg [14:0] group_offset_q;

    wire idle = state == ST_IDLE;
    wire post_done_fire = post_done_valid && post_done_ready;
    assign active = !idle;
    assign cmd_ready = rst_n && !cancel && idle && !post_done_valid;
    // Completion is a one-beat event. Always consuming it makes unsolicited
    // and stale events observable as faults instead of leaving them queued.
    assign post_done_ready = rst_n && !cancel;

    assign run_valid = rst_n && !cancel && (state == ST_RUN);
    assign run_epoch = epoch_q;
    assign run_token = token_q;
    assign run_lanes = lanes_q;
    assign run_sites = current_sites_q;

    assign window_valid = rst_n && !cancel && (state == ST_WINDOWS);
    assign window_epoch = epoch_q;
    assign window_tag = tag_q;
    assign window_input_width = {1'b0, input_width_q};
    assign window_output_remaining = output_width_q - output_x_q;
    assign window_sites = current_sites_q;
    assign window_stride_two = stride_q == 2;
    assign window_y_valid = y_valid_q[ky_q];

    wire [13:0] selected_ky_base =
        (ky_q == 0) ? ky_bases_q[13:0] :
        (ky_q == 1) ? ky_bases_q[27:14] : ky_bases_q[41:28];
    wire [14:0] descriptor_address_wide = {1'b0, selected_ky_base} + group_offset_q;
    assign window_row_address = descriptor_address_wide[13:0];

    wire [10:0] output_x_scaled = (stride_q == 2) ? {output_x_q, 1'b0} : {1'b0, output_x_q};
    wire signed [12:0] descriptor_first_x_wide =
        $signed({2'b00, output_x_scaled}) + $signed({11'b0, kx_q}) -
        $signed({11'b0, padding_q});
    assign window_first_x = descriptor_first_x_wide[11:0];

    wire [2:0] ci_tail = channels_q[1:0];
    assign window_channel_mask =
        ((group4_q == channel_groups_q - 1'b1) && (ci_tail != 0)) ?
            ((4'b0001 << ci_tail) - 1'b1) : 4'b1111;

    // All command products and wide address checks are explicitly unsigned
    // and widened before comparison. The module-level use_dsp attribute keeps
    // these control arithmetic expressions out of DSP48 resources.
    reg cmd_ok;
    reg [11:0] checked_groups;
    reg [8:0] checked_channel_groups;
    reg [31:0] checked_output_width;
    reg [31:0] checked_x_words;
    reg [31:0] checked_last_group_offset;
    reg [31:0] checked_last_xword;
    reg [31:0] checked_last_address;
    reg [31:0] checked_row_end;
    reg [63:0] checked_token_end;
    reg [63:0] checked_tag_end;
    reg [31:0] kernel_area;
    reg [31:0] numerator;
    reg [31:0] expected_output_width;
    reg [31:0] ky_base_work;
    integer check_ky;

    always @* begin
        checked_groups = 0;
        checked_channel_groups = 0;
        checked_output_width = 0;
        checked_x_words = 0;
        checked_last_group_offset = 0;
        checked_last_xword = 0;
        checked_last_address = 0;
        checked_row_end = 0;
        checked_token_end = 0;
        checked_tag_end = 0;
        kernel_area = 0;
        numerator = 0;
        expected_output_width = 0;
        ky_base_work = 0;
        cmd_ok = 1'b1;

        if (cmd_token_base == 0 ||
            cmd_channels < 1 || cmd_channels > 1024 ||
            cmd_input_width < 1 || cmd_input_width > 640 ||
            cmd_output_width < 1 || cmd_output_width > 640 ||
            (cmd_kernel != 1 && cmd_kernel != 3) ||
            (cmd_stride != 1 && cmd_stride != 2) || cmd_padding > 1 ||
            cmd_lanes < 1 || cmd_lanes > 32 ||
            cmd_bank_words < 1 || cmd_bank_words > 8192 ||
            cmd_channel_plane_stride == 0)
            cmd_ok = 1'b0;

        checked_channel_groups = (cmd_channels + 11'd3) >> 2;
        kernel_area = (cmd_kernel == 3) ? 32'd9 : 32'd1;
        checked_groups = checked_channel_groups * kernel_area;
        if (checked_groups == 0 || checked_groups > 1024)
            cmd_ok = 1'b0;

        if (cmd_input_width + (cmd_padding << 1) < cmd_kernel) begin
            cmd_ok = 1'b0;
        end else begin
            numerator = cmd_input_width + (cmd_padding << 1) - cmd_kernel;
            expected_output_width = (cmd_stride == 2) ? (numerator >> 1) + 1 : numerator + 1;
            if (expected_output_width != cmd_output_width)
                cmd_ok = 1'b0;
        end

        checked_x_words = (cmd_input_width + 15) >> 4;
        checked_last_group_offset =
            (checked_channel_groups == 0) ? 0 :
            (checked_channel_groups - 1) * cmd_channel_plane_stride;
        checked_last_xword = checked_x_words - 1;
        checked_token_end = {32'd0, cmd_token_base} +
            ((expected_output_width + 19) / 20) - 1;
        checked_tag_end = {32'd0, cmd_tag_base} +
            (((expected_output_width + 19) / 20) * checked_groups) - 1;
        if (checked_token_end > 32'hffff_ffff || checked_tag_end > 64'hffff_ffff)
            cmd_ok = 1'b0;

        for (check_ky=0; check_ky<3; check_ky=check_ky+1) begin
            if (check_ky < cmd_kernel) begin
                ky_base_work = cmd_ky_row_bases[check_ky*14 +: 14];
                checked_row_end = ky_base_work + checked_last_group_offset + checked_last_xword;
                // The descriptor still carries a row address on a masked
                // padding row, so it must fit14 bits. Only a y-valid row is
                // required to lie inside the readable bank and 13-bit RAM.
                if (checked_row_end > 32'd16383)
                    cmd_ok = 1'b0;
                if (cmd_y_valid[check_ky] &&
                    (checked_row_end >= cmd_bank_words || checked_row_end >= 8192))
                    cmd_ok = 1'b0;
            end
        end
    end

    integer reset_index;
    always @(posedge clk) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            epoch_q <= 0; token_q <= 0; tag_q <= 0;
            channels_q <= 0; input_width_q <= 0; output_width_q <= 0;
            kernel_q <= 0; stride_q <= 0; padding_q <= 0; lanes_q <= 0;
            bank_words_q <= 0; plane_stride_q <= 0; ky_bases_q <= 0; y_valid_q <= 0;
            channel_groups_q <= 0; group_count_q <= 0; output_x_q <= 0;
            current_sites_q <= 0; group4_q <= 0; ky_q <= 0; kx_q <= 0;
            descriptor_index_q <= 0; group_offset_q <= 0;
            done <= 0; abort_pulse <= 0; fault_valid <= 0; fault_code <= 0;
        end else begin
            done <= 0;
            abort_pulse <= 0;
            fault_valid <= 0;
            fault_code <= 0;
            if (cancel) begin
                state <= ST_IDLE;
                epoch_q <= 0; token_q <= 0; tag_q <= 0;
                channels_q <= 0; input_width_q <= 0; output_width_q <= 0;
                kernel_q <= 0; stride_q <= 0; padding_q <= 0; lanes_q <= 0;
                bank_words_q <= 0; plane_stride_q <= 0; ky_bases_q <= 0; y_valid_q <= 0;
                channel_groups_q <= 0; group_count_q <= 0; output_x_q <= 0;
                current_sites_q <= 0; group4_q <= 0; ky_q <= 0; kx_q <= 0;
                descriptor_index_q <= 0; group_offset_q <= 0;
            end else if (post_done_fire) begin
                if (state != ST_POST || post_done_epoch != epoch_q || post_done_token != token_q) begin
                    fault_valid <= 1'b1;
                    fault_code <= 3'd2;
                    abort_pulse <= 1'b1;
                    state <= ST_IDLE;
                    epoch_q <= 0; token_q <= 0; tag_q <= 0;
                    channels_q <= 0; input_width_q <= 0; output_width_q <= 0;
                    kernel_q <= 0; stride_q <= 0; padding_q <= 0; lanes_q <= 0;
                    bank_words_q <= 0; plane_stride_q <= 0; ky_bases_q <= 0; y_valid_q <= 0;
                    channel_groups_q <= 0; group_count_q <= 0; output_x_q <= 0;
                    current_sites_q <= 0; group4_q <= 0; ky_q <= 0; kx_q <= 0;
                    descriptor_index_q <= 0; group_offset_q <= 0;
                end else if ({1'b0, output_x_q} + current_sites_q >= output_width_q) begin
                    done <= 1'b1;
                    state <= ST_IDLE;
                end else begin
                    output_x_q <= output_x_q + current_sites_q;
                    token_q <= token_q + 1'b1;
                    current_sites_q <= ((output_width_q - output_x_q - current_sites_q) >= 20) ? 5'd20 :
                                      (output_width_q - output_x_q - current_sites_q);
                    tag_q <= tag_q;
                    group4_q <= 0; ky_q <= 0; kx_q <= 0;
                    descriptor_index_q <= 0; group_offset_q <= 0;
                    state <= ST_RUN;
                end
            end else begin
                case (state)
                    ST_IDLE: begin
                        if (cmd_valid && cmd_ready) begin
                            if (!cmd_ok) begin
                                fault_valid <= 1'b1;
                                fault_code <= 3'd1;
                            end else begin
                                epoch_q <= cmd_epoch;
                                token_q <= cmd_token_base;
                                tag_q <= cmd_tag_base;
                                channels_q <= cmd_channels;
                                input_width_q <= cmd_input_width;
                                output_width_q <= cmd_output_width;
                                kernel_q <= cmd_kernel;
                                stride_q <= cmd_stride;
                                padding_q <= cmd_padding;
                                lanes_q <= cmd_lanes;
                                bank_words_q <= cmd_bank_words;
                                plane_stride_q <= cmd_channel_plane_stride;
                                ky_bases_q <= cmd_ky_row_bases;
                                y_valid_q <= cmd_y_valid;
                                channel_groups_q <= checked_channel_groups;
                                group_count_q <= checked_groups;
                                output_x_q <= 0;
                                current_sites_q <= (cmd_output_width >= 20) ? 5'd20 : cmd_output_width[4:0];
                                group4_q <= 0; ky_q <= 0; kx_q <= 0;
                                descriptor_index_q <= 0; group_offset_q <= 0;
                                state <= ST_RUN;
                            end
                        end
                    end
                    ST_RUN: begin
                        if (run_valid && run_ready) begin
                            group4_q <= 0; ky_q <= 0; kx_q <= 0;
                            descriptor_index_q <= 0; group_offset_q <= 0;
                            state <= ST_WINDOWS;
                        end
                    end
                    ST_WINDOWS: begin
                        if (window_valid && window_ready) begin
                            tag_q <= tag_q + 1'b1;
                            descriptor_index_q <= descriptor_index_q + 1'b1;
                            if (kx_q + 1'b1 >= kernel_q) begin
                                kx_q <= 0;
                                if (ky_q + 1'b1 >= kernel_q) begin
                                    ky_q <= 0;
                                    if ({1'b0, group4_q} + 9'd1 >= channel_groups_q) begin
                                        state <= ST_POST;
                                    end else begin
                                        group4_q <= group4_q + 1'b1;
                                        group_offset_q <= group_offset_q + plane_stride_q;
                                    end
                                end else begin
                                    ky_q <= ky_q + 1'b1;
                                end
                            end else begin
                                kx_q <= kx_q + 1'b1;
                            end
                        end
                    end
                    ST_POST: begin
                        // post_done_valid is handled above; wait without
                        // changing the resident run metadata.
                    end
                    default: begin
                        state <= ST_IDLE;
                        fault_valid <= 1'b1;
                        fault_code <= 3'd3;
                        abort_pulse <= 1'b1;
                    end
                endcase
            end
        end
    end
endmodule
`default_nettype wire
