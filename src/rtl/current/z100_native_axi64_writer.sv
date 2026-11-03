`timescale 1ns/1ps
`default_nettype none

// Private single-outstanding AXI3-compatible 64-bit write adapter.
//
// rst_n is owned by the platform reset coordinator. Assert it only after the
// AXI fabric guarantees no AW/W/B transaction remains outstanding (or during
// coordinated fabric reset). A local reset must not abandon an accepted write.
// The caller must reserve an uncommitted DDR region until done is observed.
// This fixture is not the production DMA reset/abort or commit contract.
//
// A complete 1- or 2-word burst is buffered before AWVALID. Therefore cancel
// after AW is advertised never needs more private input to finish W and drain B.
// Input/output words use little-endian lanes: W beat 0 is bits [63:0].
module z100_native_axi64_writer (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         cmd_valid,
    output wire         cmd_ready,
    input  wire [31:0]  cmd_epoch,
    input  wire [31:0]  cmd_address,
    input  wire [13:0]  cmd_word_count,

    input  wire         in_valid,
    output wire         in_ready,
    input  wire [31:0]  in_epoch,
    input  wire [12:0]  in_index,
    input  wire [511:0] in_data,
    input  wire         in_last,

    input  wire         cancel,
    input  wire         timeout,
    input  wire         clear_fault,

    output reg          busy,
    output reg          done,
    output reg          fault,
    output reg  [3:0]   fault_code,

    output wire [5:0]   m_axi_awid,
    output reg  [31:0]  m_axi_awaddr,
    output reg  [3:0]   m_axi_awlen,
    output wire [2:0]   m_axi_awsize,
    output wire [1:0]   m_axi_awburst,
    output wire         m_axi_awvalid,
    input  wire         m_axi_awready,

    output wire [5:0]   m_axi_wid,
    output wire [63:0]  m_axi_wdata,
    output wire [7:0]   m_axi_wstrb,
    output wire         m_axi_wlast,
    output wire         m_axi_wvalid,
    input  wire         m_axi_wready,

    input  wire [5:0]   m_axi_bid,
    input  wire [1:0]   m_axi_bresp,
    input  wire         m_axi_bvalid,
    output wire         m_axi_bready
);
    localparam [3:0] FAULT_NONE          = 4'd0;
    localparam [3:0] FAULT_BAD_COMMAND   = 4'd1;
    localparam [3:0] FAULT_BAD_EPOCH     = 4'd2;
    localparam [3:0] FAULT_BAD_INDEX     = 4'd3;
    localparam [3:0] FAULT_BAD_LAST      = 4'd4;
    localparam [3:0] FAULT_BAD_BID       = 4'd5;
    localparam [3:0] FAULT_BAD_BRESP     = 4'd6;
    localparam [3:0] FAULT_TIMEOUT       = 4'd7;
    localparam [3:0] FAULT_CANCELLED     = 4'd8;

    localparam [2:0] ST_IDLE = 3'd0;
    localparam [2:0] ST_FILL = 3'd1;
    localparam [2:0] ST_AW   = 3'd2;
    localparam [2:0] ST_W    = 3'd3;
    localparam [2:0] ST_B    = 3'd4;

    reg [2:0] state;
    reg [31:0] command_epoch;
    reg [13:0] command_word_count;
    reg [13:0] remaining_words;
    reg [13:0] input_words_seen;
    reg [31:0] next_address;
    reg [1:0] burst_target_words;
    reg [1:0] burst_fill_words;
    reg abort_pending;
    reg [1:0] write_word_select;
    reg [2:0] write_beat_select;

    reg [511:0] burst_buffer [0:1];

    wire [32:0] command_bytes = {13'd0, cmd_word_count, 6'd0};
    wire [32:0] command_end = {1'b0, cmd_address} + command_bytes;
    wire command_invalid = (cmd_epoch == 0) || (cmd_address[5:0] != 0) ||
                           (cmd_word_count == 0) ||
                           (cmd_word_count > 14'd8192) ||
                           (command_end > 33'h1_0000_0000);

    function [1:0] choose_burst_words;
        input [31:0] address;
        input [13:0] words;
        reg [12:0] page_bytes;
        reg [6:0] page_words;
        reg [1:0] result_words;
        begin
            page_bytes = 13'd4096 - {1'b0, address[11:0]};
            page_words = page_bytes[12:6];
            result_words = 2'd2;
            if (words < {12'd0, result_words})
                result_words = words[1:0];
            if (page_words < {5'd0, result_words})
                result_words = page_words[1:0];
            choose_burst_words = result_words;
        end
    endfunction

    wire [1:0] initial_burst_words = choose_burst_words(cmd_address, cmd_word_count);
    wire [31:0] after_burst_address = next_address + {26'd0, burst_target_words, 6'd0};
    wire [13:0] after_burst_remaining = remaining_words - {12'd0, burst_target_words};
    wire [1:0] after_burst_words = choose_burst_words(after_burst_address,
                                                       after_burst_remaining);
    wire in_fire = in_valid && in_ready;
    wire aw_fire = m_axi_awvalid && m_axi_awready;
    wire w_fire = m_axi_wvalid && m_axi_wready;
    wire b_fire = m_axi_bvalid && m_axi_bready;

    assign cmd_ready = rst_n && (state == ST_IDLE) && !fault && !cancel && !timeout;
    assign in_ready = rst_n && (state == ST_FILL) && !fault && !abort_pending &&
                      !cancel && !timeout;

    assign m_axi_awid = 6'd0;
    assign m_axi_awsize = 3'd3;
    assign m_axi_awburst = 2'b01;
    assign m_axi_awvalid = rst_n && (state == ST_AW);

    assign m_axi_wid = 6'd0;
    assign m_axi_wdata = burst_buffer[write_word_select[0]]
                                      [write_beat_select * 64 +: 64];
    assign m_axi_wstrb = 8'hff;
    assign m_axi_wlast = (write_beat_select == 3'd7) &&
                         (write_word_select == (burst_target_words - 1'b1));
    assign m_axi_wvalid = rst_n && (state == ST_W);
    assign m_axi_bready = rst_n && (state == ST_B);

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            fault <= 1'b0;
            fault_code <= FAULT_NONE;
            command_epoch <= 0;
            command_word_count <= 0;
            remaining_words <= 0;
            input_words_seen <= 0;
            next_address <= 0;
            m_axi_awaddr <= 0;
            m_axi_awlen <= 0;
            burst_target_words <= 0;
            burst_fill_words <= 0;
            abort_pending <= 1'b0;
            write_word_select <= 0;
            write_beat_select <= 0;
        end else begin
            done <= 1'b0;

            if (clear_fault && (state == ST_IDLE)) begin
                fault <= 1'b0;
                fault_code <= FAULT_NONE;
                abort_pending <= 1'b0;
            end

            if (timeout && busy && !fault) begin
                fault <= 1'b1;
                fault_code <= FAULT_TIMEOUT;
                abort_pending <= 1'b1;
            end else if (cancel && busy) begin
                if (!fault) begin
                    fault <= 1'b1;
                    fault_code <= FAULT_CANCELLED;
                end
                abort_pending <= 1'b1;
            end

            case (state)
                ST_IDLE: begin
                    if (cmd_valid && cmd_ready) begin
                        if (command_invalid) begin
                            fault <= 1'b1;
                            fault_code <= FAULT_BAD_COMMAND;
                        end else begin
                            busy <= 1'b1;
                            command_epoch <= cmd_epoch;
                            command_word_count <= cmd_word_count;
                            remaining_words <= cmd_word_count;
                            input_words_seen <= 0;
                            next_address <= cmd_address;
                            burst_target_words <= initial_burst_words;
                            burst_fill_words <= 0;
                            abort_pending <= 1'b0;
                            m_axi_awaddr <= cmd_address;
                            m_axi_awlen <= {initial_burst_words, 3'b000} - 1'b1;
                            state <= ST_FILL;
                        end
                    end
                end

                ST_FILL: begin
                    if (cancel) begin
                        busy <= 1'b0;
                        fault <= 1'b1;
                        if (!fault)
                            fault_code <= FAULT_CANCELLED;
                        abort_pending <= 1'b0;
                        burst_fill_words <= 0;
                        state <= ST_IDLE;
                    end else if (timeout) begin
                        busy <= 1'b0;
                        abort_pending <= 1'b0;
                        burst_fill_words <= 0;
                        state <= ST_IDLE;
                    end else if (in_fire) begin
                        if (in_epoch != command_epoch) begin
                            fault <= 1'b1;
                            fault_code <= FAULT_BAD_EPOCH;
                            busy <= 1'b0;
                            burst_fill_words <= 0;
                            state <= ST_IDLE;
                        end else if (in_index != input_words_seen[12:0]) begin
                            fault <= 1'b1;
                            fault_code <= FAULT_BAD_INDEX;
                            busy <= 1'b0;
                            burst_fill_words <= 0;
                            state <= ST_IDLE;
                        end else if (in_last != (input_words_seen ==
                                                   (command_word_count - 14'd1))) begin
                            fault <= 1'b1;
                            fault_code <= FAULT_BAD_LAST;
                            busy <= 1'b0;
                            burst_fill_words <= 0;
                            state <= ST_IDLE;
                        end else begin
                            burst_buffer[burst_fill_words[0]] <= in_data;
                            input_words_seen <= input_words_seen + 1'b1;
                            burst_fill_words <= burst_fill_words + 1'b1;
                            if ((burst_fill_words + 1'b1) == burst_target_words)
                                state <= ST_AW;
                        end
                    end
                end

                ST_AW: begin
                    if (aw_fire) begin
                        write_word_select <= 0;
                        write_beat_select <= 0;
                        state <= ST_W;
                    end
                end

                ST_W: begin
                    if (w_fire) begin
                        if (write_beat_select == 3'd7) begin
                            write_beat_select <= 0;
                            if (write_word_select == (burst_target_words - 1'b1)) begin
                                state <= ST_B;
                            end else begin
                                write_word_select <= write_word_select + 1'b1;
                            end
                        end else begin
                            write_beat_select <= write_beat_select + 1'b1;
                        end
                    end
                end

                ST_B: begin
                    if (b_fire) begin
                        if ((m_axi_bid != 0) || (m_axi_bresp != 2'b00)) begin
                            if (!fault) begin
                                fault <= 1'b1;
                                fault_code <= (m_axi_bid != 0) ? FAULT_BAD_BID :
                                                                   FAULT_BAD_BRESP;
                            end
                            busy <= 1'b0;
                            abort_pending <= 1'b0;
                            burst_fill_words <= 0;
                            state <= ST_IDLE;
                        end else if (cancel || timeout || abort_pending || fault) begin
                            busy <= 1'b0;
                            abort_pending <= 1'b0;
                            burst_fill_words <= 0;
                            state <= ST_IDLE;
                        end else if (remaining_words == {12'd0, burst_target_words}) begin
                            busy <= 1'b0;
                            done <= 1'b1;
                            burst_fill_words <= 0;
                            state <= ST_IDLE;
                        end else begin
                            next_address <= after_burst_address;
                            remaining_words <= after_burst_remaining;
                            burst_target_words <= after_burst_words;
                            burst_fill_words <= 0;
                            m_axi_awaddr <= after_burst_address;
                            m_axi_awlen <= {after_burst_words, 3'b000} - 1'b1;
                            state <= ST_FILL;
                        end
                    end
                end

                default: begin
                    state <= ST_IDLE;
                    busy <= 1'b0;
                    burst_fill_words <= 0;
                end
            endcase
        end
    end
endmodule
`default_nettype wire
