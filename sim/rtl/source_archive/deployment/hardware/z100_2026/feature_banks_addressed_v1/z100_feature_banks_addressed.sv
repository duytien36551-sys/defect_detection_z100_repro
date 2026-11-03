`default_nettype none

// Private 64-bank feature store for the addressed native output-packer stream.
// Words are accepted in group32,row,xword,subgroup4 order and checked against
// a small counter state machine before any bank is written. Reset/cancel and
// rejected transactions invalidate metadata only; RAM payload is untouched.
(* use_dsp = "no" *)
module z100_feature_banks_addressed #(
    parameter integer ADDR_BITS = 13,
    parameter integer DEPTH = 8192
) (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    cancel,

    input  wire                    cfg_begin,
    output wire                    cfg_begin_ready,
    input  wire [31:0]             cfg_epoch,
    input  wire [10:0]             cfg_channels,
    input  wire [9:0]              cfg_height,
    input  wire [9:0]              cfg_width,

    input  wire                    cfg_word_valid,
    output wire                    cfg_word_ready,
    input  wire [511:0]            cfg_word_data,
    input  wire [31:0]             cfg_word_epoch,
    input  wire [12:0]             cfg_word_address,
    input  wire                    cfg_word_last,
    input  wire                    cfg_commit,
    output wire                    cfg_commit_ready,

    output reg                     error_valid,
    output reg [2:0]               error_code,
    output reg                     store_valid,
    output reg [31:0]              active_epoch,
    output wire                    loading,

    input  wire                    req_valid,
    output wire                    req_ready,
    input  wire [31:0]             req_epoch,
    input  wire [128*ADDR_BITS-1:0] req_addresses,
    input  wire [127:0]            req_mask,
    output reg                     out_valid,
    input  wire                    out_ready,
    output reg [31:0]              out_epoch,
    output wire [1023:0]           out_data
);
    localparam [2:0] ERR_BAD_CONFIG = 3'd1;
    localparam [2:0] ERR_BAD_ORDER  = 3'd2;
    localparam [2:0] ERR_BAD_LAST   = 3'd3;
    localparam [2:0] ERR_BAD_PAD    = 3'd4;
    localparam [2:0] ERR_EARLY_COMMIT = 3'd5;
    localparam [2:0] ERR_EXTRA_WORD = 3'd6;
    localparam [2:0] ERR_BAD_READ   = 3'd7;

    reg load_active;
    reg [31:0] pending_epoch;
    reg [10:0] channels_q;
    reg [9:0] height_q;
    reg [9:0] width_q;
    reg [6:0] x_words_q;
    reg [13:0] expected_words;
    reg [13:0] written_words;
    reg [13:0] active_words;

    reg [10:0] group32_base;
    reg [9:0] row_index;
    reg [5:0] xword_index;
    reg [3:0] subgroup_index;
    reg [3:0] subgroups_in_group;
    reg [13:0] address_stride;
    reg [13:0] subgroup0_address;
    reg [12:0] next_address;

    reg [127:0] out_mask;
    reg addresses_ok;
    reg word_padding_ok;
    reg word_order_ok;
    reg word_last_ok;
    reg word_epoch_ok;
    reg [31:0] cfg_group4_calc;
    reg [31:0] cfg_xwords_calc;
    reg [31:0] cfg_words_calc;
    reg [31:0] cfg_stride_calc;
    reg cfg_geometry_ok;
    integer check_port;
    integer check_byte;
    integer byte_channel;
    integer byte_x;

    assign loading = load_active;

    always @* begin
        cfg_group4_calc = ({21'b0, cfg_channels} + 32'd3) >> 2;
        cfg_xwords_calc = ({22'b0, cfg_width} + 32'd15) >> 4;
        cfg_stride_calc = {22'b0, cfg_height} * cfg_xwords_calc;
        cfg_words_calc = cfg_group4_calc * {22'b0, cfg_height} * cfg_xwords_calc;
        cfg_geometry_ok = (cfg_epoch != 0) && (cfg_channels != 0) &&
                          (cfg_channels <= 11'd1024) && (cfg_height != 0) &&
                          (cfg_height <= 10'd640) && (cfg_width != 0) &&
                          (cfg_width <= 10'd640) && (cfg_words_calc != 0) &&
                          (cfg_words_calc <= DEPTH) && (cfg_words_calc <= 32'd8192);
    end

    assign cfg_begin_ready = rst_n && !cancel && !load_active &&
                             (!out_valid || out_ready) && !cfg_word_valid &&
                             !cfg_commit && !req_valid;
    assign cfg_word_ready = rst_n && !cancel && load_active &&
                            !cfg_begin && !cfg_commit;
    assign cfg_commit_ready = rst_n && !cancel && load_active &&
                              !cfg_begin && !cfg_word_valid;
    assign req_ready = rst_n && !cancel && store_valid && !load_active &&
                       !cfg_begin && !cfg_commit && !cfg_word_valid &&
                       (!out_valid || out_ready);

    wire cfg_begin_fire = cfg_begin && cfg_begin_ready;
    wire cfg_word_fire = cfg_word_valid && cfg_word_ready;
    wire cfg_commit_fire = cfg_commit && cfg_commit_ready;
    wire req_fire = req_valid && req_ready;
    wire write_fire = cfg_word_fire && word_order_ok && word_epoch_ok &&
                      word_last_ok && word_padding_ok &&
                      (written_words < expected_words);
    wire read_fire = req_fire && addresses_ok && (req_epoch == active_epoch);

    always @* begin
        word_order_ok = (written_words < expected_words) &&
                        (cfg_word_address == next_address);
        word_epoch_ok = (cfg_word_epoch == pending_epoch);
        word_last_ok = (cfg_word_last == (written_words == expected_words - 1'b1));
        word_padding_ok = 1'b1;
        for (check_byte = 0; check_byte < 64; check_byte = check_byte + 1) begin
            byte_channel = (subgroup_index * 4) + (check_byte / 16);
            byte_x = (xword_index * 16) + (check_byte % 16);
            if (((group32_base + byte_channel) >= channels_q) ||
                (byte_x >= width_q)) begin
                if (cfg_word_data[check_byte*8 +: 8] != 8'd0)
                    word_padding_ok = 1'b0;
            end
        end
    end

    always @* begin
        addresses_ok = 1'b1;
        for (check_port = 0; check_port < 128; check_port = check_port + 1) begin
            if (req_mask[check_port] &&
                ({1'b0, req_addresses[check_port*ADDR_BITS +: ADDR_BITS]} >= active_words))
                addresses_ok = 1'b0;
        end
    end

    genvar bank;
    generate for (bank = 0; bank < 64; bank = bank + 1) begin : gen_bank
        (* ram_style = "block" *) reg [7:0] memory [0:DEPTH-1];
        reg [7:0] read_a;
        reg [7:0] read_b;
        // Keep write and read ownership on one explicit port-A address mux;
        // this prevents a tool from cloning each byte RAM for the write path.
        wire [ADDR_BITS-1:0] port_a_address = write_fire ?
            cfg_word_address[ADDR_BITS-1:0] :
            req_addresses[(bank*2)*ADDR_BITS +: ADDR_BITS];
        always @(posedge clk) begin
            if (write_fire)
                memory[port_a_address] <= cfg_word_data[bank*8 +: 8];
            else if (read_fire && req_mask[bank*2])
                read_a <= memory[port_a_address];
        end
        always @(posedge clk) begin
            if (read_fire && req_mask[bank*2+1])
                read_b <= memory[req_addresses[(bank*2+1)*ADDR_BITS +: ADDR_BITS]];
        end
        assign out_data[(bank*2)*8 +: 8] = out_mask[bank*2] ? read_a : 8'd0;
        assign out_data[(bank*2+1)*8 +: 8] = out_mask[bank*2+1] ? read_b : 8'd0;
    end endgenerate

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            load_active <= 1'b0;
            pending_epoch <= 32'b0;
            channels_q <= 11'b0;
            height_q <= 10'b0;
            width_q <= 10'b0;
            x_words_q <= 7'b0;
            expected_words <= 14'b0;
            written_words <= 14'b0;
            active_words <= 14'b0;
            group32_base <= 11'b0;
            row_index <= 10'b0;
            xword_index <= 6'b0;
            subgroup_index <= 4'b0;
            subgroups_in_group <= 4'b0;
            address_stride <= 14'b0;
            subgroup0_address <= 14'b0;
            next_address <= 13'b0;
            active_epoch <= 32'b0;
            store_valid <= 1'b0;
            error_valid <= 1'b0;
            error_code <= 3'b0;
            out_valid <= 1'b0;
            out_epoch <= 32'b0;
            out_mask <= 128'b0;
        end else begin
            error_valid <= 1'b0;
            error_code <= 3'b0;
            if (out_valid && out_ready)
                out_valid <= 1'b0;

            if (cfg_begin_fire) begin
                load_active <= 1'b0;
                store_valid <= 1'b0;
                active_epoch <= 32'b0;
                active_words <= 14'b0;
                written_words <= 14'b0;
                if (!cfg_geometry_ok) begin
                    expected_words <= 14'b0;
                    pending_epoch <= 32'b0;
                    channels_q <= 11'b0;
                    height_q <= 10'b0;
                    width_q <= 10'b0;
                    x_words_q <= 7'b0;
                    error_valid <= 1'b1;
                    error_code <= ERR_BAD_CONFIG;
                end else begin
                    load_active <= 1'b1;
                    pending_epoch <= cfg_epoch;
                    channels_q <= cfg_channels;
                    height_q <= cfg_height;
                    width_q <= cfg_width;
                    x_words_q <= cfg_xwords_calc[6:0];
                    expected_words <= cfg_words_calc[13:0];
                    group32_base <= 11'b0;
                    row_index <= 10'b0;
                    xword_index <= 6'b0;
                    subgroup_index <= 4'b0;
                    subgroups_in_group <=
                        (cfg_channels >= 32) ? 4'd8 : ((cfg_channels + 11'd3) >> 2);
                    address_stride <= cfg_stride_calc[13:0];
                    subgroup0_address <= 14'b0;
                    next_address <= 13'b0;
                end
            end else if (load_active && cfg_word_fire) begin
                if (written_words >= expected_words) begin
                    load_active <= 1'b0;
                    store_valid <= 1'b0;
                    active_epoch <= 32'b0;
                    active_words <= 14'b0;
                    error_valid <= 1'b1;
                    error_code <= ERR_EXTRA_WORD;
                end else if (!word_order_ok || !word_epoch_ok) begin
                    load_active <= 1'b0;
                    store_valid <= 1'b0;
                    active_epoch <= 32'b0;
                    active_words <= 14'b0;
                    error_valid <= 1'b1;
                    error_code <= ERR_BAD_ORDER;
                end else if (!word_last_ok) begin
                    load_active <= 1'b0;
                    store_valid <= 1'b0;
                    active_epoch <= 32'b0;
                    active_words <= 14'b0;
                    error_valid <= 1'b1;
                    error_code <= ERR_BAD_LAST;
                end else if (!word_padding_ok) begin
                    load_active <= 1'b0;
                    store_valid <= 1'b0;
                    active_epoch <= 32'b0;
                    active_words <= 14'b0;
                    error_valid <= 1'b1;
                    error_code <= ERR_BAD_PAD;
                end else begin
                    written_words <= written_words + 1'b1;
                    if ((subgroup_index + 1'b1) < subgroups_in_group) begin
                        subgroup_index <= subgroup_index + 1'b1;
                        next_address <= next_address + address_stride[12:0];
                    end else if ((xword_index + 1'b1) < x_words_q) begin
                        subgroup_index <= 4'b0;
                        xword_index <= xword_index + 1'b1;
                        subgroup0_address <= subgroup0_address + 1'b1;
                        next_address <= subgroup0_address[12:0] + 1'b1;
                    end else if ((row_index + 1'b1) < height_q) begin
                        subgroup_index <= 4'b0;
                        xword_index <= 6'b0;
                        row_index <= row_index + 1'b1;
                        subgroup0_address <= subgroup0_address + 1'b1;
                        next_address <= subgroup0_address[12:0] + 1'b1;
                    end else if ((group32_base + 11'd32) < channels_q) begin
                        subgroup_index <= 4'b0;
                        xword_index <= 6'b0;
                        row_index <= 10'b0;
                        group32_base <= group32_base + 11'd32;
                        subgroup0_address <= subgroup0_address +
                                             (address_stride * 7) + 1'b1;
                        next_address <= subgroup0_address[12:0] +
                                        (address_stride[12:0] * 7) + 1'b1;
                        subgroups_in_group <=
                            ((channels_q - (group32_base + 11'd32)) >= 32) ? 4'd8 :
                            ((channels_q - (group32_base + 11'd32) + 11'd3) >> 2);
                    end
                end
            end else if (cfg_commit_fire) begin
                load_active <= 1'b0;
                if ((written_words == expected_words) &&
                    (expected_words != 0)) begin
                    store_valid <= 1'b1;
                    active_epoch <= pending_epoch;
                    active_words <= expected_words;
                end else begin
                    store_valid <= 1'b0;
                    active_epoch <= 32'b0;
                    active_words <= 14'b0;
                    error_valid <= 1'b1;
                    error_code <= ERR_EARLY_COMMIT;
                end
            end else if (req_fire) begin
                if (!addresses_ok || (req_epoch != active_epoch)) begin
                    store_valid <= 1'b0;
                    active_epoch <= 32'b0;
                    active_words <= 14'b0;
                    out_valid <= 1'b0;
                    error_valid <= 1'b1;
                    error_code <= ERR_BAD_READ;
                end else begin
                    out_valid <= 1'b1;
                    out_epoch <= active_epoch;
                    out_mask <= req_mask;
                end
            end
        end
    end

    initial begin
        if ((ADDR_BITS != 13) || (DEPTH != 8192))
            $error("z100_feature_banks_addressed requires ADDR_BITS=13 and DEPTH=8192");
    end
endmodule

`default_nettype wire
