`default_nettype none
// Guarded one-entry parameter residency filter.
//
// V2 closes two protocol gaps in the V1 candidate: a rejected context must
// never launch the downstream command, and a foreign completion must be
// consumed as a fault without being published to the upstream owner.  It also
// captures the native parameter loader's one-cycle done pulse when the tile
// consumer is stalled, then holds the completion until done_ready.
module z100_parameter_residency_guard_v2 (
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
    localparam [2:0] ST_IDLE    = 3'd0;
    localparam [2:0] ST_WAIT    = 3'd1;
    localparam [2:0] ST_HIT     = 3'd2;
    localparam [2:0] ST_FAULT   = 3'd3;
    localparam [2:0] ST_PENDING = 3'd4;

    reg [2:0] state;
    reg cache_valid;
    reg [31:0] cache_epoch, cache_event, cache_generation;
    reg [15:0] cache_job;
    reg [31:0] request_epoch, request_event, request_generation;
    reg [15:0] request_job;
    reg pending_error;

    wire context_matches = context_valid &&
        context_epoch == cmd_epoch && context_event == cmd_event &&
        context_generation == cmd_generation;
    wire cache_hit = cache_valid && context_matches &&
        cache_epoch == cmd_epoch && cache_event == cmd_event &&
        cache_generation == cmd_generation && cache_job == cmd_job;
    wire completion_identity_matches =
        downstream_done_epoch == request_epoch &&
        downstream_done_event == request_event &&
        downstream_done_generation == request_generation &&
        downstream_done_job == request_job;
    // An unsolicited completion owns the cycle and prevents a new command
    // from being accepted or exposed downstream.
    wire idle = state == ST_IDLE && rst_n && !cancel && !fault &&
        !downstream_done_valid;

    assign cmd_ready = idle && context_matches &&
        (cache_hit || downstream_cmd_ready);
    assign downstream_cmd_valid = idle && cmd_valid && context_matches &&
        !cache_hit;
    assign downstream_cmd_epoch = cmd_epoch;
    assign downstream_cmd_event = cmd_event;
    assign downstream_cmd_generation = cmd_generation;
    assign downstream_cmd_job = cmd_job;

    // The native_parameter_reader has no done_ready port and emits a one-cycle
    // done pulse.  Accept it whenever a miss is outstanding; ST_PENDING holds
    // the completion for the tile controller if it is applying backpressure.
    // A mismatched completion is drained immediately, then faulted without
    // exposing it to the caller.
    assign downstream_done_ready = state == ST_WAIT && rst_n && !cancel && !fault;
    assign done_valid = rst_n && !cancel && !fault &&
        ((state == ST_HIT && !downstream_done_valid) ||
         (state == ST_WAIT && downstream_done_valid && completion_identity_matches) ||
         state == ST_PENDING);
    assign done_epoch = request_epoch;
    assign done_event = request_event;
    assign done_generation = request_generation;
    assign done_job = request_job;
    assign done_error = state == ST_HIT ? 1'b0 :
        state == ST_PENDING ? pending_error : downstream_done_error;
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
            pending_error <= 1'b0;
            fault <= 1'b0;
            fault_code <= 0;
        end else if (cancel) begin
            // The native backend keeps accepted AXI work owned by its readers
            // and reports all_io_quiet only after those readers drain.  This
            // clears the logical parameter request and cache after cancel.
            state <= ST_IDLE;
            cache_valid <= 1'b0;
            pending_error <= 1'b0;
            fault <= 1'b0;
            fault_code <= 0;
        end else if (state == ST_FAULT) begin
            state <= ST_IDLE;
            fault <= 1'b0;
            fault_code <= 0;
        end else if (fault) begin
            state <= ST_FAULT;
        end else begin
            if ((state == ST_IDLE || state == ST_HIT) && downstream_done_valid) begin
                state <= ST_FAULT;
                fault <= 1'b1;
                fault_code <= 3'd1;
                cache_valid <= 1'b0;
                pending_error <= 1'b0;
            end else if (state == ST_IDLE) begin
                if (cmd_valid && !context_matches) begin
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
                    if (!completion_identity_matches) begin
                        state <= ST_FAULT;
                        fault <= 1'b1;
                        fault_code <= 3'd2;
                        cache_valid <= 1'b0;
                        pending_error <= 1'b0;
                    end else begin
                        if (downstream_done_error) begin
                            cache_valid <= 1'b0;
                        end else begin
                            cache_valid <= 1'b1;
                            cache_epoch <= request_epoch;
                            cache_event <= request_event;
                            cache_generation <= request_generation;
                            cache_job <= request_job;
                        end
                        if (done_ready) begin
                            state <= ST_IDLE;
                            pending_error <= 1'b0;
                        end else begin
                            pending_error <= downstream_done_error;
                            state <= ST_PENDING;
                        end
                    end
                end
            end else if (state == ST_PENDING) begin
                if (done_valid && done_ready) begin
                    state <= ST_IDLE;
                    pending_error <= 1'b0;
                end
            end
        end
    end
endmodule
`default_nettype wire
