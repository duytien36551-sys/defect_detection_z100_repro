`default_nettype none
// One-entry parameter residency filter for a Conv event.
//
// The downstream path represents the existing directory + parameter loader.
// A hit completes the tile parameter handshake without issuing a new DDR
// command. The cache key includes the graph epoch, event identity, resource
// generation and parameter job. Any cancel, downstream error, or successful
// command for a different key replaces or invalidates the entry.
module z100_parameter_residency_v1 (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        cancel,
    input  wire        context_valid,
    input  wire [31:0] context_epoch,
    input  wire [31:0] context_event,
    input  wire [31:0] context_generation,

    input  wire        cmd_valid,
    output wire        cmd_ready,
    input  wire [31:0] cmd_epoch,
    input  wire [31:0] cmd_event,
    input  wire [31:0] cmd_generation,
    input  wire [15:0] cmd_job,

    output wire        downstream_cmd_valid,
    input  wire        downstream_cmd_ready,
    output wire [31:0] downstream_cmd_epoch,
    output wire [31:0] downstream_cmd_event,
    output wire [31:0] downstream_cmd_generation,
    output wire [15:0] downstream_cmd_job,

    input  wire        downstream_done_valid,
    output wire        downstream_done_ready,
    input  wire [31:0] downstream_done_epoch,
    input  wire [31:0] downstream_done_event,
    input  wire [31:0] downstream_done_generation,
    input  wire [15:0] downstream_done_job,
    input  wire        downstream_done_error,

    output wire        done_valid,
    input  wire        done_ready,
    output wire [31:0] done_epoch,
    output wire [31:0] done_event,
    output wire [31:0] done_generation,
    output wire [15:0] done_job,
    output wire        done_error,
    output wire        active,
    output reg         fault,
    output reg  [2:0]  fault_code
);
    localparam ST_IDLE = 2'd0;
    localparam ST_WAIT = 2'd1;
    localparam ST_HIT  = 2'd2;
    localparam ST_FAULT = 2'd3;

    reg [1:0] state;
    reg       cache_valid;
    reg [31:0] cache_epoch, cache_event, cache_generation;
    reg [15:0] cache_job;
    reg [31:0] request_epoch, request_event, request_generation;
    reg [15:0] request_job;

    wire context_matches = context_valid &&
        context_epoch == cmd_epoch && context_event == cmd_event &&
        context_generation == cmd_generation;
    wire cache_hit = cache_valid && context_matches &&
        cache_epoch == cmd_epoch && cache_event == cmd_event &&
        cache_generation == cmd_generation && cache_job == cmd_job;
    wire idle = state == ST_IDLE && rst_n && !cancel && !fault;

    assign cmd_ready = idle && context_matches &&
        (cache_hit || downstream_cmd_ready);
    assign downstream_cmd_valid = idle && cmd_valid && !cache_hit;
    assign downstream_cmd_epoch = cmd_epoch;
    assign downstream_cmd_event = cmd_event;
    assign downstream_cmd_generation = cmd_generation;
    assign downstream_cmd_job = cmd_job;

    assign downstream_done_ready = state == ST_WAIT && !cancel && !fault &&
        done_ready;
    assign done_valid = (state == ST_HIT) ||
        (state == ST_WAIT && downstream_done_valid);
    assign done_epoch = state == ST_HIT ? request_epoch : downstream_done_epoch;
    assign done_event = state == ST_HIT ? request_event : downstream_done_event;
    assign done_generation = state == ST_HIT ? request_generation :
        downstream_done_generation;
    assign done_job = state == ST_HIT ? request_job : downstream_done_job;
    assign done_error = state == ST_HIT ? 1'b0 : downstream_done_error;
    assign active = state != ST_IDLE;

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            cache_valid <= 1'b0;
            cache_epoch <= 0;
            cache_event <= 0;
            cache_generation <= 0;
            cache_job <= 0;
            request_epoch <= 0;
            request_event <= 0;
            request_generation <= 0;
            request_job <= 0;
            fault <= 1'b0;
            fault_code <= 0;
        end else if (cancel) begin
            state <= ST_IDLE;
            cache_valid <= 1'b0;
            fault <= 1'b0;
            fault_code <= 0;
        end else if (state == ST_FAULT) begin
            if (!cancel) begin
                state <= ST_IDLE;
                fault <= 1'b0;
                fault_code <= 0;
            end
        end else if (fault) begin
            state <= ST_FAULT;
        end else begin
            if (state == ST_IDLE) begin
                if (downstream_done_valid) begin
                    state <= ST_FAULT;
                    fault <= 1'b1;
                    fault_code <= 3'd1;
                    cache_valid <= 1'b0;
                end else if (cmd_valid && !context_matches) begin
                    state <= ST_FAULT;
                    fault <= 1'b1;
                    fault_code <= 3'd3;
                    cache_valid <= 1'b0;
                end else if (cmd_valid && cmd_ready) begin
                    request_epoch <= cmd_epoch;
                    request_event <= cmd_event;
                    request_generation <= cmd_generation;
                    request_job <= cmd_job;
                    state <= cache_hit ? ST_HIT : ST_WAIT;
                end
            end else if (state == ST_HIT) begin
                if (done_valid && done_ready)
                    state <= ST_IDLE;
            end else if (state == ST_WAIT) begin
                if (downstream_done_valid && downstream_done_ready) begin
                    if (downstream_done_epoch != request_epoch ||
                        downstream_done_event != request_event ||
                        downstream_done_generation != request_generation ||
                        downstream_done_job != request_job) begin
                        state <= ST_FAULT;
                        fault <= 1'b1;
                        fault_code <= 3'd2;
                        cache_valid <= 1'b0;
                    end else if (downstream_done_error) begin
                        state <= ST_IDLE;
                        cache_valid <= 1'b0;
                    end else begin
                        cache_valid <= 1'b1;
                        cache_epoch <= request_epoch;
                        cache_event <= request_event;
                        cache_generation <= request_generation;
                        cache_job <= request_job;
                        state <= ST_IDLE;
                    end
                end
            end
        end
    end
endmodule
`default_nettype wire
