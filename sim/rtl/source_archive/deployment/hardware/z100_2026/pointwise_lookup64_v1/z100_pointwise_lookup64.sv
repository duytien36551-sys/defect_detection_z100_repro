`default_nettype none
// Private, epoch-tagged sixteen-lane lookup unit for one active pointwise table.
// Eight copies of eight8Kx8 banks retain16 independent read lanes while
// accepting eight contiguous configuration bytes per handshake.
module z100_pointwise_lookup64 (
    input wire clk,
    input wire rst_n,
    input wire cancel,

    input wire cfg_begin,
    output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,
    input wire [1:0] cfg_mode,
    input wire cfg_word_valid,
    output wire cfg_word_ready,
    input wire [63:0] cfg_data,
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

    wire [12:0] cfg_address = written_bytes[15:3];
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

    // Eight byte-interleaved banks per copy accept a contiguous64-bit word.
    // Every lane retains an independent read port; bank-selection metadata is
    // captured with its synchronous RAM read and held under downstream stalls.
    wire [127:0] ram_result;
    genvar copy_index,byte_bank;
    generate for(copy_index=0;copy_index<8;copy_index=copy_index+1)begin:gen_table
        localparam integer LANE_A=copy_index*2;
        localparam integer LANE_B=copy_index*2+1;
        wire [15:0] address_a=lane_address[LANE_A*16+:16];
        wire [15:0] address_b=lane_address[LANE_B*16+:16];
        reg [2:0] select_a,select_b;
        wire [63:0] bank_result_a,bank_result_b;
        always @(posedge clk)begin
            if(read_fire&&in_lanes>LANE_A)select_a<=address_a[2:0];
            if(read_fire&&in_lanes>LANE_B)select_b<=address_b[2:0];
        end
        for(byte_bank=0;byte_bank<8;byte_bank=byte_bank+1)begin:gen_byte_bank
            (* ram_style="block" *)reg[7:0] table_mem[0:8191];
            reg [7:0] read_a,read_b;
            wire [12:0] port_a_address=write_fire ? cfg_address : address_a[15:3];
            always @(posedge clk)begin
                if(write_fire)table_mem[port_a_address]<=cfg_data[byte_bank*8+:8];
                else if(read_fire&&in_lanes>LANE_A&&address_a[2:0]==byte_bank)
                    read_a<=table_mem[port_a_address];
            end
            always @(posedge clk)begin
                if(read_fire&&in_lanes>LANE_B&&address_b[2:0]==byte_bank)
                    read_b<=table_mem[address_b[15:3]];
            end
            assign bank_result_a[byte_bank*8+:8]=read_a;
            assign bank_result_b[byte_bank*8+:8]=read_b;
        end
        assign ram_result[LANE_A*8+:8]=rd_lanes>LANE_A ? bank_result_a[select_a*8+:8] : 8'd0;
        assign ram_result[LANE_B*8+:8]=rd_lanes>LANE_B ? bank_result_b[select_b*8+:8] : 8'd0;
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
                        written_bytes <= written_bytes + 17'd8;
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
