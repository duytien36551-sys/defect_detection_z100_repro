`default_nettype none
// Private20-site resident-row command scheduler. It serializes one resident
// 32-lane output group across a row, then waits for the matching postprocess
// drain acknowledgement before advancing the externally visible run token.
(* use_dsp = "no" *)
module z100_native_row_scheduler20 #(
    // v4-s12 (2026-10-31): sites processed per run. Was hard-coded 20.
    parameter integer MAX_SITES = 20
) (
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
    localparam [2:0] ST_CHECK = 3'd4;

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

    // periph_flat_v3: the accepted command is latched (L_*) and cmd_ok is
    // evaluated over a 5-stage register pipeline in ST_CHECK (ck_cnt). The old
    // decision (fault code 1 and stay idle, or load and RUN) is then taken
    // from the registered verdict. Widths are exact whenever the simple range
    // checks (a_pre) pass; otherwise the verdict is false as before.
    reg [31:0] L_epoch, L_token, L_tag;
    reg [10:0] L_ch;
    reg [9:0] L_iw, L_ow;
    reg [1:0] L_k, L_s, L_p;
    reg [5:0] L_lanes;
    reg [13:0] L_bw, L_ps;
    reg [41:0] L_kyb;
    reg [2:0] L_yv;
    reg [2:0] ck_cnt;
    reg a_pre, a_numok;
    reg [8:0] a_cg;
    reg [3:0] a_ka;
    reg [10:0] a_num;
    reg [10:0] b_eow;
    reg b_eowok;
    reg [11:0] b_groups;
    reg [6:0] b_xw;
    reg [22:0] b_lgo;
    reg [5:0] c_segs;
    reg [24:0] c_re0, c_re1, c_re2;
    reg c_ok;
    reg d_tok_ok, d_row_ok, d_ok;
    reg [17:0] d_sg;
    reg e_ok;
    wire [10:0] iw_pad = {1'b0, L_iw} + {8'd0, L_p, 1'b0};
    always @(posedge clk) begin
        a_pre <= L_token != 0 &&
                 L_ch >= 1 && L_ch <= 1024 &&
                 L_iw >= 1 && L_iw <= 640 && L_ow >= 1 && L_ow <= 640 &&
                 (L_k == 1 || L_k == 3) && (L_s == 1 || L_s == 2) && L_p <= 1 &&
                 L_lanes >= 1 && L_lanes <= 32 &&
                 L_bw >= 1 && L_bw <= 8192 && L_ps != 0;
        a_cg <= (L_ch + 11'd3) >> 2;
        a_ka <= (L_k == 3) ? 4'd9 : 4'd1;
        a_numok <= iw_pad >= {9'd0, L_k};
        a_num <= iw_pad - {9'd0, L_k};
        b_eow <= (L_s == 2) ? (a_num >> 1) + 11'd1 : a_num + 11'd1;
        b_eowok <= a_numok && (((L_s == 2) ? (a_num >> 1) + 11'd1 : a_num + 11'd1) == {1'b0, L_ow});
        b_groups <= a_cg * a_ka;
        b_xw <= ({1'b0, L_iw} + 11'd15) >> 4;
        b_lgo <= (a_cg == 0) ? 23'd0 : (a_cg - 9'd1) * L_ps;
        c_segs <= (b_eow + (MAX_SITES[10:0] - 11'd1)) / MAX_SITES[10:0];
        c_re0 <= {11'd0, L_kyb[13:0]}  + {2'd0, b_lgo} + {18'd0, b_xw} - 25'd1;
        c_re1 <= {11'd0, L_kyb[27:14]} + {2'd0, b_lgo} + {18'd0, b_xw} - 25'd1;
        c_re2 <= {11'd0, L_kyb[41:28]} + {2'd0, b_lgo} + {18'd0, b_xw} - 25'd1;
        c_ok <= a_pre && b_eowok && b_groups != 0 && b_groups <= 1024;
        d_tok_ok <= {1'b0, L_token} + {27'd0, c_segs} - 33'd1 <= 33'h0_ffff_ffff;
        d_sg <= c_segs * b_groups;
        d_row_ok <= !(c_re0 > 16383) && !(L_yv[0] && (c_re0 >= L_bw || c_re0 >= 8192)) &&
                    (L_k < 2 || (!(c_re1 > 16383) && !(L_yv[1] && (c_re1 >= L_bw || c_re1 >= 8192)))) &&
                    (L_k < 3 || (!(c_re2 > 16383) && !(L_yv[2] && (c_re2 >= L_bw || c_re2 >= 8192))));
        d_ok <= c_ok;
        e_ok <= d_ok && d_tok_ok && d_row_ok &&
                ({1'b0, L_tag} + {15'd0, d_sg} - 33'd1 <= 33'h0_ffff_ffff);
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
            ck_cnt <= 0;
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
                    current_sites_q <= ((output_width_q - output_x_q - current_sites_q) >= MAX_SITES[9:0]) ? MAX_SITES[4:0] :
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
                            L_epoch <= cmd_epoch; L_token <= cmd_token_base; L_tag <= cmd_tag_base;
                            L_ch <= cmd_channels; L_iw <= cmd_input_width; L_ow <= cmd_output_width;
                            L_k <= cmd_kernel; L_s <= cmd_stride; L_p <= cmd_padding;
                            L_lanes <= cmd_lanes; L_bw <= cmd_bank_words; L_ps <= cmd_channel_plane_stride;
                            L_kyb <= cmd_ky_row_bases; L_yv <= cmd_y_valid;
                            ck_cnt <= 0;
                            state <= ST_CHECK;
                        end
                    end
                    ST_CHECK: begin
                        ck_cnt <= ck_cnt + 3'd1;
                        if (ck_cnt == 3'd5) begin
                            if (!e_ok) begin
                                fault_valid <= 1'b1;
                                fault_code <= 3'd1;
                                state <= ST_IDLE;
                            end else begin
                                epoch_q <= L_epoch;
                                token_q <= L_token;
                                tag_q <= L_tag;
                                channels_q <= L_ch;
                                input_width_q <= L_iw;
                                output_width_q <= L_ow;
                                kernel_q <= L_k;
                                stride_q <= L_s;
                                padding_q <= L_p;
                                lanes_q <= L_lanes;
                                bank_words_q <= L_bw;
                                plane_stride_q <= L_ps;
                                ky_bases_q <= L_kyb;
                                y_valid_q <= L_yv;
                                channel_groups_q <= a_cg;
                                group_count_q <= b_groups[10:0];
                                output_x_q <= 0;
                                current_sites_q <= (L_ow >= MAX_SITES[9:0]) ? MAX_SITES[4:0] : L_ow[4:0];
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
