`default_nettype none
// Private, epoch-tagged sixteen-lane lookup unit for one active pointwise table.
// Eight replicated 64Kx8 true-dual-port arrays provide two independent lanes
// each. Port A explicitly shares its write/read address to preserve BRAM count.
module z100_pointwise_lookup (
    input wire clk,
    input wire rst_n,
    input wire cancel,

    input wire cfg_begin,
    output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,
    input wire [1:0] cfg_mode,
    input wire cfg_word_valid,
    output wire cfg_word_ready,
    input wire [7:0] cfg_data,
    input wire cfg_commit,
    output wire cfg_commit_ready,
    output reg error_valid,
    output reg [2:0] error_code,
    output reg store_valid,
    output reg [31:0] active_epoch,
    output reg [1:0] active_mode,
    output wire loading,

    input wire in_valid,
    output wire in_ready,
    input wire [31:0] in_epoch,
    input wire [31:0] in_token,
    input wire [1:0] in_mode,
    input wire [4:0] in_lanes,
    input wire in_last,
    input wire [127:0] in_a,
    input wire [127:0] in_b,

    output reg out_valid,
    input wire out_ready,
    output reg [31:0] out_epoch,
    output reg [31:0] out_token,
    output reg [4:0] out_lanes,
    output reg out_last,
    output reg [127:0] out_data
);
    localparam [1:0] MODE_UNARY = 2'b00;
    localparam [1:0] MODE_ADD = 2'b01;

    reg load_active;
    reg [31:0] pending_epoch;
    reg [1:0] pending_mode;
    reg [16:0] expected_bytes;
    reg [16:0] written_bytes;

    reg rd_valid;
    reg [31:0] rd_epoch;
    reg [31:0] rd_token;
    reg [4:0] rd_lanes;
    reg rd_last;
    wire out_slot = !out_valid || out_ready;
    wire rd_slot = !rd_valid || out_slot;
    wire pipeline_empty = !rd_valid && !out_valid;

    assign loading = load_active;
    assign cfg_begin_ready = rst_n && !cancel && !load_active && pipeline_empty;
    assign cfg_word_ready = rst_n && !cancel && load_active &&
                            !cfg_begin && !cfg_commit;
    assign cfg_commit_ready = rst_n && !cancel && load_active && !cfg_begin;

    wire [15:0] cfg_address = written_bytes[15:0];
    wire write_fire = cfg_word_valid && cfg_word_ready &&
                      (written_bytes < expected_bytes);
    wire in_fire = in_valid && in_ready;
    wire request_valid = (in_mode == MODE_UNARY || in_mode == MODE_ADD) &&
                         (in_mode == active_mode) &&
                         (in_epoch == active_epoch) &&
                         (in_lanes != 0) && (in_lanes <= 16);
    wire read_fire = in_fire && request_valid;

    assign in_ready = rst_n && !cancel && store_valid && !load_active &&
                      !cfg_begin && !cfg_commit && rd_slot;

    // 16 lane addresses, each byte is independently addressed. Unary uses
    // signed-int8 + 128; ADD uses {signed_a + 128, signed_b + 128}.
    wire [16*16-1:0] lane_address;
    genvar lane;
    generate for (lane = 0; lane < 16; lane = lane + 1) begin : gen_addresses
        wire [7:0] a_byte = in_a[lane*8 +: 8];
        wire [7:0] b_byte = in_b[lane*8 +: 8];
        wire [7:0] a_index = a_byte ^ 8'h80;
        wire [7:0] b_index = b_byte ^ 8'h80;
        assign lane_address[lane*16 +: 16] =
            (in_mode == MODE_ADD) ? {a_index, b_index} : {8'd0, a_index};
    end endgenerate

    wire [127:0] ram_result;
    genvar copy_index;
    generate for (copy_index = 0; copy_index < 8; copy_index = copy_index + 1) begin : gen_table
        localparam integer LANE_A = copy_index * 2;
        localparam integer LANE_B = copy_index * 2 + 1;
        (* ram_style = "block" *) reg [7:0] table_mem [0:65535];
        reg [7:0] read_a;
        reg [7:0] read_b;
        wire [15:0] port_a_read_address = lane_address[LANE_A*16 +: 16];
        wire [15:0] port_b_read_address = lane_address[LANE_B*16 +: 16];
        // Keep the loader and port-A read on one address expression. The
        // arrays are initialized by strict sequential writes, never cleared.
        wire [15:0] port_a_address = write_fire ? cfg_address : port_a_read_address;

        always @(posedge clk) begin
            if (write_fire)
                table_mem[port_a_address] <= cfg_data;
            else if (read_fire && in_lanes > LANE_A)
                read_a <= table_mem[port_a_address];
        end
        always @(posedge clk) begin
            if (read_fire && in_lanes > LANE_B)
                read_b <= table_mem[port_b_read_address];
        end

        assign ram_result[LANE_A*8 +: 8] = (rd_lanes > LANE_A) ? read_a : 8'd0;
        assign ram_result[LANE_B*8 +: 8] = (rd_lanes > LANE_B) ? read_b : 8'd0;
    end endgenerate

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            load_active <= 1'b0;
            pending_epoch <= 32'd0;
            pending_mode <= 2'b00;
            expected_bytes <= 17'd0;
            written_bytes <= 17'd0;
            store_valid <= 1'b0;
            active_epoch <= 32'd0;
            active_mode <= 2'b00;
            error_valid <= 1'b0;
            error_code <= 3'd0;
            rd_valid <= 1'b0;
            rd_epoch <= 32'd0;
            rd_token <= 32'd0;
            rd_lanes <= 5'd0;
            rd_last <= 1'b0;
            out_valid <= 1'b0;
            out_epoch <= 32'd0;
            out_token <= 32'd0;
            out_lanes <= 5'd0;
            out_last <= 1'b0;
            out_data <= 128'd0;
        end else begin
            error_valid <= 1'b0;
            error_code <= 3'd0;

            if (out_slot) begin
                out_valid <= rd_valid;
                if (rd_valid) begin
                    out_epoch <= rd_epoch;
                    out_token <= rd_token;
                    out_lanes <= rd_lanes;
                    out_last <= rd_last;
                    out_data <= ram_result;
                end else begin
                    out_data <= 128'd0;
                end
            end

            if (rd_slot) begin
                rd_valid <= read_fire;
                if (read_fire) begin
                    rd_epoch <= in_epoch;
                    rd_token <= in_token;
                    rd_lanes <= in_lanes;
                    rd_last <= in_last;
                end
            end

            if (cfg_begin && cfg_begin_ready) begin
                store_valid <= 1'b0;
                active_epoch <= 32'd0;
                active_mode <= 2'b00;
                pending_epoch <= cfg_epoch;
                pending_mode <= cfg_mode;
                written_bytes <= 17'd0;
                if (cfg_epoch == 0 ||
                    (cfg_mode != MODE_UNARY && cfg_mode != MODE_ADD) ||
                    cfg_word_valid || cfg_commit) begin
                    load_active <= 1'b0;
                    expected_bytes <= 17'd0;
                    error_valid <= 1'b1;
                    error_code <= 3'd1;
                end else begin
                    load_active <= 1'b1;
                    expected_bytes <= (cfg_mode == MODE_UNARY) ? 17'd256 : 17'd65536;
                end
            end else if (load_active) begin
                if (cfg_commit && cfg_commit_ready) begin
                    load_active <= 1'b0;
                    if (written_bytes != expected_bytes || cfg_word_valid) begin
                        store_valid <= 1'b0;
                        active_epoch <= 32'd0;
                        active_mode <= 2'b00;
                        error_valid <= 1'b1;
                        error_code <= 3'd2;
                    end else begin
                        store_valid <= 1'b1;
                        active_epoch <= pending_epoch;
                        active_mode <= pending_mode;
                    end
                end else if (cfg_word_valid && cfg_word_ready) begin
                    if (written_bytes >= expected_bytes) begin
                        load_active <= 1'b0;
                        expected_bytes <= 17'd0;
                        store_valid <= 1'b0;
                        active_epoch <= 32'd0;
                        active_mode <= 2'b00;
                        error_valid <= 1'b1;
                        error_code <= 3'd3;
                    end else begin
                        written_bytes <= written_bytes + 1'b1;
                    end
                end
            end

            if (in_fire && !request_valid) begin
                error_valid <= 1'b1;
                error_code <= 3'd4;
                if (rd_slot)
                    rd_valid <= 1'b0;
            end
        end
    end
endmodule
`default_nettype wire
