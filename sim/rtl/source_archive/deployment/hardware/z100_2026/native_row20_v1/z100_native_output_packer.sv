`default_nettype none

// Private ordered native32 output stream -> feature-bank word packer.
// One in-flight 32x16-byte transpose block per buffer; buffer payload is never
// reset, and each byte is masked before it can appear on the output interface.
(* use_dsp="no" *)
module z100_native_output_packer #(
    parameter integer SITES = 20
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          cancel,

    input  wire          cfg_valid,
    output wire          cfg_ready,
    input  wire [31:0]   cfg_epoch,
    input  wire [10:0]   cfg_channels,
    input  wire [9:0]    cfg_height,
    input  wire [9:0]    cfg_width,
    input  wire [31:0]   cfg_token_base,

    input  wire          in_valid,
    output wire          in_ready,
    input  wire [31:0]   in_epoch,
    input  wire [31:0]   in_token,
    input  wire [4:0]    in_site,
    input  wire [5:0]    in_lanes,
    input  wire          in_last,
    input  wire [255:0]  in_data,

    output wire          out_valid,
    input  wire          out_ready,
    output wire [31:0]   out_epoch,
    output wire [12:0]   out_address,
    output reg  [511:0]  out_data,
    output wire          out_last,

    output reg           done,
    output reg           error_valid,
    output reg  [2:0]    error_code,
    output reg           active
);
    localparam integer SAFE_SITES = (SITES >= 1) ? SITES : 4;
    localparam [2:0] ERR_BAD_CONFIG = 3'd1;
    localparam [2:0] ERR_BAD_INPUT  = 3'd2;

    // The two memories together hold exactly 2*16*256 bits (1 KiB).
    // Their payload is intentionally left unchanged by reset and cancel.
    reg [255:0] transpose0 [0:15];
    reg [255:0] transpose1 [0:15];

    reg [1:0] buffer_full;
    reg fill_buffer;
    reg drain_buffer;
    reg fill_active;
    reg producer_done;
    reg [3:0] drain_subgroup;

    reg [31:0] epoch_q;
    reg [31:0] token_q;
    reg [10:0] channels_q;
    reg [9:0] height_q;
    reg [9:0] width_q;
    reg [6:0] x_words_q;

    reg [10:0] group_base_q;
    reg [9:0] row_q;
    reg [9:0] x_q;
    reg [4:0] site_index_q;
    reg [4:0] sites_this_run_q;

    reg [10:0] buffer_group [0:1];
    reg [9:0]  buffer_row [0:1];
    reg [5:0]  buffer_xword [0:1];
    reg [5:0]  buffer_lanes [0:1];
    reg        buffer_final [0:1];

    reg [63:0] cfg_group4_calc;
    reg [63:0] cfg_xwords_calc;
    (* use_dsp = "no" *) reg [63:0] cfg_words_calc;
    reg [63:0] cfg_group32_calc;
    reg [63:0] cfg_sites_calc;
    (* use_dsp = "no" *) reg [63:0] cfg_runs_calc;
    reg [63:0] cfg_last_token_calc;
    reg        cfg_geometry_ok;

    always @* begin
        cfg_group4_calc = ({53'b0, cfg_channels} + 64'd3) / 64'd4;
        cfg_xwords_calc = ({54'b0, cfg_width} + 64'd15) / 64'd16;
        cfg_words_calc = cfg_group4_calc * {54'b0, cfg_height} * cfg_xwords_calc;
        cfg_group32_calc = ({53'b0, cfg_channels} + 64'd31) / 64'd32;
        cfg_sites_calc = ({54'b0, cfg_width} + SAFE_SITES - 1) / SAFE_SITES;
        cfg_runs_calc = cfg_group32_calc * {54'b0, cfg_height} * cfg_sites_calc;
        cfg_last_token_calc = {32'b0, cfg_token_base} + cfg_runs_calc - 64'd1;
        cfg_geometry_ok = (cfg_channels != 0) && (cfg_channels <= 1024) &&
                          (cfg_height != 0) && (cfg_height <= 640) &&
                          (cfg_width != 0) && (cfg_width <= 640) &&
                          (cfg_words_calc != 0) && (cfg_words_calc <= 8192) &&
                          (cfg_runs_calc != 0) &&
                          (cfg_last_token_calc <= 64'h00000000ffffffff);
    end

    wire command_enable = rst_n && !cancel;
    wire buffers_empty = (buffer_full == 2'b00);
    assign cfg_ready = command_enable && !active && !fill_active && buffers_empty;
    assign in_ready = command_enable && active && !producer_done && !buffer_full[fill_buffer];

    wire [10:0] channels_left = channels_q - group_base_q;
    wire [5:0] expected_lanes = (channels_left >= 32) ? 6'd32 : channels_left[5:0];
    wire expected_last = (sites_this_run_q != 0) &&
                         (site_index_q == sites_this_run_q - 1'b1);
    wire input_metadata_good = (in_epoch === epoch_q) && (in_token === token_q) &&
                               (in_site === site_index_q) && (in_lanes === expected_lanes) &&
                               (in_last === expected_last);

    // A malformed accepted beat invalidates the block before any same-edge
    // downstream handshake can consume output from the invalidated tile.
    assign out_valid = command_enable && active && buffer_full[drain_buffer] &&
                       !(in_valid && in_ready && !input_metadata_good);
    assign out_epoch = epoch_q;
    wire [5:0] drain_lanes = buffer_lanes[drain_buffer];
    wire [3:0] drain_subgroups = (drain_lanes + 6'd3) >> 2;
    (* use_dsp = "no" *) wire [31:0] out_address_calc =
        ((((({21'b0, buffer_group[drain_buffer]} >> 2) + {28'b0, drain_subgroup}) *
            {22'b0, height_q}) +
           {22'b0, buffer_row[drain_buffer]}) * {25'b0, x_words_q}) +
        {26'b0, buffer_xword[drain_buffer]};
    assign out_address = out_address_calc[12:0];
    assign out_last = out_valid && buffer_final[drain_buffer] &&
                      (drain_subgroup == drain_subgroups - 1'b1);

    integer output_byte;
    integer output_lane;
    integer output_x;
    integer output_absolute_x;
    always @* begin
        out_data = 512'b0;
        for (output_byte = 0; output_byte < 64; output_byte = output_byte + 1) begin
            output_lane = drain_subgroup * 4 + (output_byte / 16);
            output_x = output_byte % 16;
            output_absolute_x = buffer_xword[drain_buffer] * 16 + output_x;
            if ((output_lane < drain_lanes) && (output_absolute_x < width_q)) begin
                if (drain_buffer == 1'b0)
                    out_data[output_byte*8 +: 8] =
                        transpose0[output_x][output_lane*8 +: 8];
                else
                    out_data[output_byte*8 +: 8] =
                        transpose1[output_x][output_lane*8 +: 8];
            end
        end
    end

    integer reset_index;
    always @(posedge clk) begin
        if (!rst_n) begin
            active <= 1'b0;
            buffer_full <= 2'b00;
            fill_buffer <= 1'b0;
            drain_buffer <= 1'b0;
            fill_active <= 1'b0;
            producer_done <= 1'b0;
            drain_subgroup <= 4'b0;
            epoch_q <= 32'b0;
            token_q <= 32'b0;
            channels_q <= 11'b0;
            height_q <= 10'b0;
            width_q <= 10'b0;
            x_words_q <= 7'b0;
            group_base_q <= 11'b0;
            row_q <= 10'b0;
            x_q <= 10'b0;
            site_index_q <= 5'b0;
            sites_this_run_q <= 5'b0;
            done <= 1'b0;
            error_valid <= 1'b0;
            error_code <= 3'b0;
            for (reset_index = 0; reset_index < 2; reset_index = reset_index + 1) begin
                buffer_group[reset_index] <= 11'b0;
                buffer_row[reset_index] <= 10'b0;
                buffer_xword[reset_index] <= 6'b0;
                buffer_lanes[reset_index] <= 6'b0;
                buffer_final[reset_index] <= 1'b0;
            end
        end else if (cancel) begin
            active <= 1'b0;
            buffer_full <= 2'b00;
            fill_buffer <= 1'b0;
            drain_buffer <= 1'b0;
            fill_active <= 1'b0;
            producer_done <= 1'b0;
            drain_subgroup <= 4'b0;
            epoch_q <= 32'b0;
            token_q <= 32'b0;
            channels_q <= 11'b0;
            height_q <= 10'b0;
            width_q <= 10'b0;
            x_words_q <= 7'b0;
            group_base_q <= 11'b0;
            row_q <= 10'b0;
            x_q <= 10'b0;
            site_index_q <= 5'b0;
            sites_this_run_q <= 5'b0;
            done <= 1'b0;
            error_valid <= 1'b0;
            error_code <= 3'b0;
            for (reset_index = 0; reset_index < 2; reset_index = reset_index + 1) begin
                buffer_group[reset_index] <= 11'b0;
                buffer_row[reset_index] <= 10'b0;
                buffer_xword[reset_index] <= 6'b0;
                buffer_lanes[reset_index] <= 6'b0;
                buffer_final[reset_index] <= 1'b0;
            end
        end else begin
            done <= 1'b0;
            error_valid <= 1'b0;
            error_code <= 3'b0;

            if (cfg_valid && cfg_ready) begin
                if (!cfg_geometry_ok) begin
                    error_valid <= 1'b1;
                    error_code <= ERR_BAD_CONFIG;
                    active <= 1'b0;
                    producer_done <= 1'b0;
                    fill_active <= 1'b0;
                    buffer_full <= 2'b00;
                    fill_buffer <= 1'b0;
                    drain_buffer <= 1'b0;
                    drain_subgroup <= 4'b0;
                    epoch_q <= 32'b0;
                    token_q <= 32'b0;
                    channels_q <= 11'b0;
                    height_q <= 10'b0;
                    width_q <= 10'b0;
                    x_words_q <= 7'b0;
                    group_base_q <= 11'b0;
                    row_q <= 10'b0;
                    x_q <= 10'b0;
                    site_index_q <= 5'b0;
                    sites_this_run_q <= 5'b0;
                    buffer_group[0] <= 11'b0;
                    buffer_group[1] <= 11'b0;
                    buffer_row[0] <= 10'b0;
                    buffer_row[1] <= 10'b0;
                    buffer_xword[0] <= 6'b0;
                    buffer_xword[1] <= 6'b0;
                    buffer_lanes[0] <= 6'b0;
                    buffer_lanes[1] <= 6'b0;
                    buffer_final[0] <= 1'b0;
                    buffer_final[1] <= 1'b0;
                end else begin
                    active <= 1'b1;
                    producer_done <= 1'b0;
                    fill_active <= 1'b0;
                    buffer_full <= 2'b00;
                    fill_buffer <= 1'b0;
                    drain_buffer <= 1'b0;
                    drain_subgroup <= 4'b0;
                    epoch_q <= cfg_epoch;
                    token_q <= cfg_token_base;
                    channels_q <= cfg_channels;
                    height_q <= cfg_height;
                    width_q <= cfg_width;
                    x_words_q <= cfg_xwords_calc[6:0];
                    group_base_q <= 11'b0;
                    row_q <= 10'b0;
                    x_q <= 10'b0;
                    site_index_q <= 5'b0;
                    sites_this_run_q <= (cfg_width >= SAFE_SITES) ? SAFE_SITES : cfg_width[4:0];
                end
            end

            if (in_valid && in_ready) begin
                if (!input_metadata_good) begin
                    error_valid <= 1'b1;
                    error_code <= ERR_BAD_INPUT;
                    active <= 1'b0;
                    producer_done <= 1'b0;
                    fill_active <= 1'b0;
                    buffer_full <= 2'b00;
                    fill_buffer <= 1'b0;
                    drain_buffer <= 1'b0;
                    drain_subgroup <= 4'b0;
                    epoch_q <= 32'b0;
                    token_q <= 32'b0;
                    channels_q <= 11'b0;
                    height_q <= 10'b0;
                    width_q <= 10'b0;
                    x_words_q <= 7'b0;
                    group_base_q <= 11'b0;
                    row_q <= 10'b0;
                    x_q <= 10'b0;
                    site_index_q <= 5'b0;
                    sites_this_run_q <= 5'b0;
                    buffer_group[0] <= 11'b0;
                    buffer_group[1] <= 11'b0;
                    buffer_row[0] <= 10'b0;
                    buffer_row[1] <= 10'b0;
                    buffer_xword[0] <= 6'b0;
                    buffer_xword[1] <= 6'b0;
                    buffer_lanes[0] <= 6'b0;
                    buffer_lanes[1] <= 6'b0;
                    buffer_final[0] <= 1'b0;
                    buffer_final[1] <= 1'b0;
                end else begin
                    if (fill_buffer == 1'b0)
                        transpose0[x_q[3:0]] <= in_data;
                    else
                        transpose1[x_q[3:0]] <= in_data;

                    buffer_group[fill_buffer] <= group_base_q;
                    buffer_row[fill_buffer] <= row_q;
                    buffer_xword[fill_buffer] <= x_q[9:4];
                    buffer_lanes[fill_buffer] <= expected_lanes;
                    buffer_final[fill_buffer] <=
                        (group_base_q + 11'd32 >= channels_q) &&
                        (row_q == height_q - 1'b1) && (x_q == width_q - 1'b1);

                    if ((x_q[3:0] == 4'd15) || (x_q == width_q - 1'b1)) begin
                        buffer_full[fill_buffer] <= 1'b1;
                        fill_active <= 1'b0;
                        fill_buffer <= !fill_buffer;
                    end else begin
                        fill_active <= 1'b1;
                    end

                    if (expected_last) begin
                        token_q <= token_q + 1'b1;
                        site_index_q <= 5'b0;
                        if (x_q != width_q - 1'b1)
                            sites_this_run_q <= ((width_q - (x_q + 1'b1)) >= SAFE_SITES) ?
                                                SAFE_SITES : (width_q - (x_q + 1'b1));
                    end else begin
                        site_index_q <= site_index_q + 1'b1;
                    end

                    if (x_q == width_q - 1'b1) begin
                        x_q <= 10'b0;
                        site_index_q <= 5'b0;
                        if (row_q == height_q - 1'b1) begin
                            row_q <= 10'b0;
                            if (group_base_q + 11'd32 >= channels_q) begin
                                producer_done <= 1'b1;
                            end else begin
                                group_base_q <= group_base_q + 11'd32;
                                sites_this_run_q <= (width_q >= SAFE_SITES) ?
                                                    SAFE_SITES : width_q[4:0];
                            end
                        end else begin
                            row_q <= row_q + 1'b1;
                            sites_this_run_q <= (width_q >= SAFE_SITES) ?
                                                SAFE_SITES : width_q[4:0];
                        end
                    end else begin
                        x_q <= x_q + 1'b1;
                    end
                end
            end

            if (out_valid && out_ready) begin
                if ((drain_subgroup + 1'b1) >= drain_subgroups) begin
                    buffer_full[drain_buffer] <= 1'b0;
                    drain_buffer <= !drain_buffer;
                    drain_subgroup <= 4'b0;
                    if (out_last) begin
                        done <= 1'b1;
                        active <= 1'b0;
                    end
                end else begin
                    drain_subgroup <= drain_subgroup + 1'b1;
                end
            end
        end
    end

    initial begin
        if ((SITES != 4) && (SITES != 8) && (SITES != 12) && (SITES != 20))
            $error("SITES must be 4, 8, 12, or 20");
    end
endmodule

`default_nettype wire
