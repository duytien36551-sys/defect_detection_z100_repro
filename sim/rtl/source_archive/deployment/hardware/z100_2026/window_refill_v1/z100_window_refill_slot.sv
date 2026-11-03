`default_nettype none

// One-row refill/read-ownership experiment. This is intentionally a single
// multiword slot with two synchronous read ports; it is not the 32-bank window
// scheduler and has no AXI or DDR interface.
module z100_window_refill_slot #(
    parameter integer DATA_WIDTH = 32,
    parameter integer DEPTH = 16,
    parameter integer ADDR_WIDTH = 4,
    parameter integer GEN_WIDTH = 8,
    parameter integer ROW_WIDTH = 32,
    parameter integer COUNT_WIDTH = ADDR_WIDTH + 1
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         cancel,

    input  wire                         begin_valid,
    output wire                         begin_ready,
    input  wire [ROW_WIDTH-1:0]         begin_absolute_row,
    input  wire [GEN_WIDTH-1:0]         begin_generation,
    input  wire [COUNT_WIDTH-1:0]       begin_word_count,
    output reg                          begin_reject,

    input  wire                         write_valid,
    output wire                         write_ready,
    input  wire [ROW_WIDTH-1:0]         write_absolute_row,
    input  wire [GEN_WIDTH-1:0]         write_generation,
    input  wire [ADDR_WIDTH-1:0]        write_address,
    input  wire [DATA_WIDTH-1:0]        write_data,
    output reg                          write_reject,

    input  wire                         commit_valid,
    output wire                         commit_ready,
    input  wire [ROW_WIDTH-1:0]         commit_absolute_row,
    input  wire [GEN_WIDTH-1:0]         commit_generation,
    output reg                          commit_reject,

    input  wire                         acquire_valid,
    output wire                         acquire_ready,
    input  wire [ROW_WIDTH-1:0]         acquire_absolute_row,
    input  wire [GEN_WIDTH-1:0]         acquire_generation,
    output reg                          acquire_reject,

    input  wire [1:0]                   read_valid,
    output reg  [1:0]                   read_ready,
    input  wire [2*ROW_WIDTH-1:0]       read_absolute_row,
    input  wire [2*GEN_WIDTH-1:0]       read_generation,
    input  wire [2*ADDR_WIDTH-1:0]      read_address,
    output reg  [1:0]                   read_reject,
    output wire [1:0]                   result_valid,
    input  wire [1:0]                   result_ready,
    output reg  [2*DATA_WIDTH-1:0]      result_data,
    output reg  [2*ROW_WIDTH-1:0]       result_absolute_row,
    output reg  [2*GEN_WIDTH-1:0]       result_generation,
    output reg  [2*ADDR_WIDTH-1:0]      result_address,

    input  wire                         release_valid,
    output wire                         release_ready,
    output reg                          release_reject,

    output reg  [1:0]                   slot_state,
    output reg  [ROW_WIDTH-1:0]         slot_absolute_row,
    output reg  [GEN_WIDTH-1:0]         slot_generation,
    output reg  [COUNT_WIDTH-1:0]       fill_count,
    output reg  [COUNT_WIDTH-1:0]       slot_word_count
);
    localparam [1:0] SLOT_INVALID = 2'd0;
    localparam [1:0] SLOT_FILLING = 2'd1;
    localparam [1:0] SLOT_READY   = 2'd2;
    localparam [1:0] SLOT_IN_USE  = 2'd3;

    reg [DATA_WIDTH-1:0] row_mem [0:DEPTH-1];
    wire command_enable = rst_n && !cancel;
    reg [1:0] result_valid_q;
    assign result_valid = result_valid_q & {2{command_enable}};

    wire begin_state_ok = (slot_state == SLOT_INVALID) || (slot_state == SLOT_READY);
    wire begin_count_ok = (begin_word_count != 0) && (begin_word_count <= DEPTH);
    wire begin_context_idle = (result_valid == 2'b00) && !release_valid && !acquire_valid;
    assign begin_ready = command_enable && begin_state_ok && begin_count_ok && begin_context_idle;

    wire write_identity_ok = (write_absolute_row == slot_absolute_row) &&
                             (write_generation == slot_generation);
    assign write_ready = command_enable && (slot_state == SLOT_FILLING) &&
                         write_identity_ok && (fill_count < slot_word_count) &&
                         (write_address == fill_count[ADDR_WIDTH-1:0]);

    wire commit_identity_ok = (commit_absolute_row == slot_absolute_row) &&
                              (commit_generation == slot_generation);
    assign commit_ready = command_enable && (slot_state == SLOT_FILLING) &&
                          commit_identity_ok && (fill_count == slot_word_count);

    wire acquire_identity_ok = (acquire_absolute_row == slot_absolute_row) &&
                               (acquire_generation == slot_generation);
    assign acquire_ready = command_enable && (slot_state == SLOT_READY) && acquire_identity_ok;

    wire release_idle = (result_valid == 2'b00) && (read_valid == 2'b00);
    assign release_ready = command_enable && (slot_state == SLOT_IN_USE) && release_idle;

    integer port_index;
    reg [ROW_WIDTH-1:0] selected_read_row;
    reg [GEN_WIDTH-1:0] selected_read_generation;
    reg [ADDR_WIDTH-1:0] selected_read_address;
    reg selected_read_identity_ok;
    always @* begin
        read_ready = 2'b00;
        for (port_index = 0; port_index < 2; port_index = port_index + 1) begin
            selected_read_row = read_absolute_row[port_index*ROW_WIDTH +: ROW_WIDTH];
            selected_read_generation = read_generation[port_index*GEN_WIDTH +: GEN_WIDTH];
            selected_read_address = read_address[port_index*ADDR_WIDTH +: ADDR_WIDTH];
            selected_read_identity_ok = (selected_read_row == slot_absolute_row) &&
                                        (selected_read_generation == slot_generation);
            if (command_enable && (slot_state == SLOT_IN_USE) && selected_read_identity_ok &&
                ({1'b0, selected_read_address} < slot_word_count) &&
                (!result_valid[port_index] || result_ready[port_index])) begin
                read_ready[port_index] = 1'b1;
            end
        end
    end

    initial begin
        if (DEPTH < 1 || ADDR_WIDTH < 1 || (DEPTH > (1 << ADDR_WIDTH)))
            $error("DEPTH/ADDR_WIDTH parameter mismatch");
        if (COUNT_WIDTH < ADDR_WIDTH + 1)
            $error("COUNT_WIDTH must represent DEPTH");
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            slot_state <= SLOT_INVALID;
            slot_absolute_row <= {ROW_WIDTH{1'b0}};
            slot_generation <= {GEN_WIDTH{1'b0}};
            fill_count <= {COUNT_WIDTH{1'b0}};
            slot_word_count <= {COUNT_WIDTH{1'b0}};
            begin_reject <= 1'b0;
            write_reject <= 1'b0;
            commit_reject <= 1'b0;
            acquire_reject <= 1'b0;
            read_reject <= 2'b00;
            release_reject <= 1'b0;
        end else if (cancel) begin
            // RAM contents are intentionally not reset. Invalidating all
            // ownership forces a complete refill before any result is visible.
            slot_state <= SLOT_INVALID;
            slot_absolute_row <= {ROW_WIDTH{1'b0}};
            slot_generation <= {GEN_WIDTH{1'b0}};
            fill_count <= {COUNT_WIDTH{1'b0}};
            slot_word_count <= {COUNT_WIDTH{1'b0}};
            begin_reject <= 1'b0;
            write_reject <= 1'b0;
            commit_reject <= 1'b0;
            acquire_reject <= 1'b0;
            read_reject <= 2'b00;
            release_reject <= 1'b0;
        end else begin
            begin_reject <= begin_valid && !begin_ready;
            write_reject <= write_valid && !write_ready;
            commit_reject <= commit_valid && !commit_ready;
            acquire_reject <= acquire_valid && !acquire_ready;
            release_reject <= release_valid && !release_ready;
            read_reject[0] <= read_valid[0] &&
                ((slot_state != SLOT_IN_USE) ||
                 (read_absolute_row[0 +: ROW_WIDTH] != slot_absolute_row) ||
                 (read_generation[0 +: GEN_WIDTH] != slot_generation) ||
                 ({1'b0, read_address[0 +: ADDR_WIDTH]} >= slot_word_count));
            read_reject[1] <= read_valid[1] &&
                ((slot_state != SLOT_IN_USE) ||
                 (read_absolute_row[ROW_WIDTH +: ROW_WIDTH] != slot_absolute_row) ||
                 (read_generation[GEN_WIDTH +: GEN_WIDTH] != slot_generation) ||
                 ({1'b0, read_address[ADDR_WIDTH +: ADDR_WIDTH]} >= slot_word_count));

            if (begin_valid && begin_ready) begin
                slot_state <= SLOT_FILLING;
                slot_absolute_row <= begin_absolute_row;
                slot_generation <= begin_generation;
                fill_count <= {COUNT_WIDTH{1'b0}};
                slot_word_count <= begin_word_count;
            end

            if (write_valid && write_ready) begin
                row_mem[write_address] <= write_data;
                fill_count <= fill_count + 1'b1;
            end

            if (commit_valid && commit_ready)
                slot_state <= SLOT_READY;

            if (acquire_valid && acquire_ready)
                slot_state <= SLOT_IN_USE;

            if (release_valid && release_ready)
                slot_state <= SLOT_READY;
        end
    end

    integer read_port;
    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            result_valid_q <= 2'b00;
            result_data <= {(2*DATA_WIDTH){1'b0}};
            result_absolute_row <= {(2*ROW_WIDTH){1'b0}};
            result_generation <= {(2*GEN_WIDTH){1'b0}};
            result_address <= {(2*ADDR_WIDTH){1'b0}};
        end else begin
            for (read_port = 0; read_port < 2; read_port = read_port + 1) begin
                if (read_valid[read_port] && read_ready[read_port]) begin
                    result_valid_q[read_port] <= 1'b1;
                    result_data[read_port*DATA_WIDTH +: DATA_WIDTH] <=
                        row_mem[read_address[read_port*ADDR_WIDTH +: ADDR_WIDTH]];
                    result_absolute_row[read_port*ROW_WIDTH +: ROW_WIDTH] <= slot_absolute_row;
                    result_generation[read_port*GEN_WIDTH +: GEN_WIDTH] <= slot_generation;
                    result_address[read_port*ADDR_WIDTH +: ADDR_WIDTH] <=
                        read_address[read_port*ADDR_WIDTH +: ADDR_WIDTH];
                end else if (result_valid[read_port] && result_ready[read_port]) begin
                    result_valid_q[read_port] <= 1'b0;
                end
            end
        end
    end
endmodule

`default_nettype wire
