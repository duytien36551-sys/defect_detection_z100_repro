`default_nettype none
// Private 32-lane unary byte-table stream for exact packaged SiLU maps.
// Sixteen replicated 256x8 distributed memories each provide two independent
// asynchronous reads. Configuration bytes are broadcast to every replica.
module z100_unary32 (
    input wire clk,
    input wire rst_n,
    input wire cancel,

    input wire cfg_begin,
    output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,
    input wire cfg_word_valid,
    output wire cfg_word_ready,
    input wire [7:0] cfg_data,
    input wire cfg_commit,
    output wire cfg_commit_ready,
    output reg error_valid,
    output reg [2:0] error_code,
    output reg store_valid,
    output reg [31:0] active_epoch,
    output wire loading,

    input wire in_valid,
    output wire in_ready,
    input wire [31:0] in_epoch,
    input wire [31:0] in_token,
    input wire [5:0] in_lanes,
    input wire in_last,
    input wire [255:0] in_data,

    output wire out_valid,
    input wire out_ready,
    output wire [31:0] out_epoch,
    output wire [31:0] out_token,
    output wire [5:0] out_lanes,
    output wire out_last,
    output wire [255:0] out_data
);
    reg load_active;
    reg [31:0] pending_epoch;
    reg [8:0] written_bytes;

    reg s0_valid;
    reg [31:0] s0_epoch;
    reg [31:0] s0_token;
    reg [5:0] s0_lanes;
    reg s0_last;
    reg [255:0] s0_data;

    reg s1_valid;
    reg [31:0] s1_epoch;
    reg [31:0] s1_token;
    reg [5:0] s1_lanes;
    reg s1_last;
    reg [255:0] s1_data;

    wire s1_ready = !s1_valid || out_ready;
    wire s0_ready = !s0_valid || s1_ready;
    wire pipeline_empty = !s0_valid && !s1_valid;
    wire request_valid = (in_epoch == active_epoch) &&
                         (in_lanes != 0) && (in_lanes <= 32);
    wire in_fire = in_valid && in_ready;
    wire lookup_fire = in_fire && request_valid;

    assign loading = load_active;
    assign cfg_begin_ready = rst_n && !cancel && !load_active && pipeline_empty;
    assign cfg_word_ready = rst_n && !cancel && load_active &&
                            !cfg_begin && !cfg_commit;
    assign cfg_commit_ready = rst_n && !cancel && load_active && !cfg_begin;
    assign in_ready = rst_n && !cancel && store_valid && !load_active &&
                      !cfg_begin && !cfg_commit && s0_ready;

    wire [7:0] cfg_address = written_bytes[7:0];
    wire cfg_write_fire = cfg_word_valid && cfg_word_ready &&
                          (written_bytes < 9'd256);

    wire [255:0] read_data;
    wire [255:0] lane_data = in_data;
    genvar copy_index;
    generate for (copy_index = 0; copy_index < 16; copy_index = copy_index + 1) begin : gen_table
        localparam integer LANE_A = copy_index * 2;
        localparam integer LANE_B = copy_index * 2 + 1;
        (* ram_style = "distributed" *) reg [7:0] table_mem [0:255];
        wire [7:0] address_a = lane_data[LANE_A*8 +: 8] ^ 8'h80;
        wire [7:0] address_b = lane_data[LANE_B*8 +: 8] ^ 8'h80;
        wire [7:0] value_a = table_mem[address_a];
        wire [7:0] value_b = table_mem[address_b];

        // The table is never reset. Every accepted configuration write is
        // broadcast to all sixteen replicas, then a strict 256-byte commit
        // makes the new epoch visible.
        always @(posedge clk) begin
            if (cfg_write_fire)
                table_mem[cfg_address] <= cfg_data;
        end

        assign read_data[LANE_A*8 +: 8] = value_a;
        assign read_data[LANE_B*8 +: 8] = value_b;
    end endgenerate

    wire [255:0] masked_read_data;
    genvar lane;
    generate for (lane = 0; lane < 32; lane = lane + 1) begin : gen_tail_mask
        assign masked_read_data[lane*8 +: 8] =
            (in_lanes > lane) ? read_data[lane*8 +: 8] : 8'd0;
    end endgenerate

    assign out_valid = s1_valid;
    assign out_epoch = s1_epoch;
    assign out_token = s1_token;
    assign out_lanes = s1_lanes;
    assign out_last = s1_last;
    assign out_data = s1_data;

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            load_active <= 1'b0;
            pending_epoch <= 32'd0;
            written_bytes <= 9'd0;
            store_valid <= 1'b0;
            active_epoch <= 32'd0;
            error_valid <= 1'b0;
            error_code <= 3'd0;
            s0_valid <= 1'b0;
            s0_epoch <= 32'd0;
            s0_token <= 32'd0;
            s0_lanes <= 6'd0;
            s0_last <= 1'b0;
            s0_data <= 256'd0;
            s1_valid <= 1'b0;
            s1_epoch <= 32'd0;
            s1_token <= 32'd0;
            s1_lanes <= 6'd0;
            s1_last <= 1'b0;
            s1_data <= 256'd0;
        end else begin
            error_valid <= 1'b0;
            error_code <= 3'd0;

            if (s1_ready) begin
                s1_valid <= s0_valid;
                if (s0_valid) begin
                    s1_epoch <= s0_epoch;
                    s1_token <= s0_token;
                    s1_lanes <= s0_lanes;
                    s1_last <= s0_last;
                    s1_data <= s0_data;
                end else begin
                    s1_data <= 256'd0;
                end
            end

            if (s0_ready) begin
                s0_valid <= lookup_fire;
                if (lookup_fire) begin
                    s0_epoch <= in_epoch;
                    s0_token <= in_token;
                    s0_lanes <= in_lanes;
                    s0_last <= in_last;
                    s0_data <= masked_read_data;
                end else begin
                    s0_data <= 256'd0;
                end
            end

            if (cfg_begin && cfg_begin_ready) begin
                store_valid <= 1'b0;
                active_epoch <= 32'd0;
                pending_epoch <= cfg_epoch;
                written_bytes <= 9'd0;
                if (cfg_epoch == 0 || cfg_word_valid || cfg_commit) begin
                    load_active <= 1'b0;
                    error_valid <= 1'b1;
                    error_code <= 3'd1;
                end else begin
                    load_active <= 1'b1;
                end
            end else if (load_active) begin
                if (cfg_commit && cfg_commit_ready) begin
                    load_active <= 1'b0;
                    if (written_bytes != 9'd256 || cfg_word_valid) begin
                        store_valid <= 1'b0;
                        active_epoch <= 32'd0;
                        error_valid <= 1'b1;
                        error_code <= 3'd2;
                    end else begin
                        store_valid <= 1'b1;
                        active_epoch <= pending_epoch;
                    end
                end else if (cfg_word_valid && cfg_word_ready) begin
                    if (written_bytes >= 9'd256) begin
                        load_active <= 1'b0;
                        store_valid <= 1'b0;
                        active_epoch <= 32'd0;
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
                if (s0_ready)
                    s0_valid <= 1'b0;
            end
        end
    end
endmodule
`default_nettype wire
