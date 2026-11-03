`default_nettype none
// timing_v13c tap reducer: same results as z100_maxpool_vector for streams in
// which the next vector's first beat is not offered while a result is held
// (true for the window20 pool, which issues one vector at a time).
// Structural rules:
//  * input slice s0 (free-running payload, no reset/CE) breaks the
//    feature-RAM -> window mux -> compare-tree -> maximum_q path;
//  * in_ready is a shallow function of registered state only;
//  * maximum_q / result_data have no reset; their CEs are dedicated
//    registered strobes (replicated by MAX_FANOUT), not the metadata cone;
//  * metadata verdict only drives narrow control FFs.
// Cost: +1 cycle latency per vector; throughput unchanged (1 beat/cycle).
(* use_dsp="no" *)
module z100_maxpool_vector_v13c # (parameter integer LANES=80) (
    input wire clk, input wire rst_n, input wire cancel,
    input wire in_valid, output wire in_ready,
    input wire [31:0] in_epoch, input wire [31:0] in_token,
    input wire [6:0] in_lanes, input wire in_first, input wire in_last,
    input wire [LANES-1:0] in_mask,
    input wire [LANES*8-1:0] in_data,
    output wire out_valid, input wire out_ready,
    output wire [31:0] out_epoch, output wire [31:0] out_token,
    output wire [6:0] out_lanes, output wire [LANES*8-1:0] out_data,
    output reg error_valid, output reg active
);
    reg [31:0] epoch_q, token_q, result_epoch, result_token;
    reg [6:0] lanes_q, result_lanes;
    reg [LANES*8-1:0] maximum_q, result_data;
    reg [LANES-1:0] seen_q;
    reg result_valid;
    // s0 input slice
    reg s0_valid, s0_first, s0_last;
    (* max_fanout = 64 *) reg s0_ce;     // = s0_valid, CE copy for maximum_q
    (* max_fanout = 64 *) reg s0_ce_last; // = s0_valid && s0_last, CE for result_data
    reg [31:0] s0_epoch, s0_token;
    reg [6:0] s0_lanes;
    reg [LANES-1:0] s0_mask;
    reg [LANES*8-1:0] s0_data;
    reg [LANES*8-1:0] maximum_next;
    reg [LANES-1:0] seen_next;
    reg all_seen;
    integer lane;
    wire enable = rst_n && !cancel;
    // Never accept while a result is held or the closing beat is in s0.
    assign in_ready = enable && !result_valid && !(s0_valid && s0_last);
    wire fire = in_valid && in_ready;
    wire metadata_good = s0_lanes>0 && s0_lanes<=LANES && s0_epoch!=0 && s0_token!=0 &&
        ((s0_first && !active) || (!s0_first && active && s0_epoch==epoch_q &&
          s0_token==token_q && s0_lanes==lanes_q));
    always @* begin
        maximum_next = s0_first ? {LANES{8'h80}} : maximum_q;
        seen_next = s0_first ? {LANES{1'b0}} : seen_q;
        all_seen = 1'b1;
        for(lane=0;lane<LANES;lane=lane+1) begin
            if(lane<s0_lanes) begin
                if(s0_mask[lane]) begin
                    if(!seen_next[lane] || $signed(s0_data[lane*8+:8])>$signed(maximum_next[lane*8+:8]))
                        maximum_next[lane*8+:8]=s0_data[lane*8+:8];
                    seen_next[lane]=1'b1;
                end
                if(!seen_next[lane]) all_seen=1'b0;
            end else begin
                maximum_next[lane*8+:8]=8'd0;
                seen_next[lane]=1'b0;
            end
        end
    end
    wire malformed = s0_valid && (!metadata_good || (s0_last && !all_seen));
    assign out_valid = enable && result_valid;
    assign out_epoch=result_epoch;
    assign out_token=result_token;
    assign out_lanes=result_lanes;
    assign out_data=result_data;
    // Payload: no reset. A malformed beat may update maximum_q, but the error
    // path cancels the pool and the next vector starts with s0_first.
    always @(posedge clk) begin
        // Free-running slice: meaningful only when s0_valid (no CE cone from
        // the upstream valid onto 700+ payload FFs).
        s0_data<=in_data; s0_mask<=in_mask; s0_epoch<=in_epoch; s0_token<=in_token;
        s0_lanes<=in_lanes; s0_first<=in_first; s0_last<=in_last;
        if(s0_ce) maximum_q<=maximum_next;
        if(s0_ce_last) result_data<=maximum_next;
        if(s0_ce_last) begin result_epoch<=s0_epoch; result_token<=s0_token; result_lanes<=s0_lanes; end
    end
    always @(posedge clk) begin
        if(!rst_n || cancel) begin
            active<=0; result_valid<=0; error_valid<=0;
            s0_valid<=0; s0_ce<=0; s0_ce_last<=0;
            epoch_q<=0;token_q<=0;lanes_q<=0;seen_q<=0;
        end else begin
            error_valid<=0;
            s0_valid<=fire; s0_ce<=fire; s0_ce_last<=fire&&in_last;
            if(out_valid && out_ready) result_valid<=0;
            if(s0_valid) begin
                if(malformed) begin
                    active<=0; result_valid<=0; error_valid<=1; seen_q<=0;
                end else begin
                    epoch_q<=s0_epoch; token_q<=s0_token; lanes_q<=s0_lanes;
                    seen_q<=seen_next;
                    active<=!s0_last;
                    if(s0_last) result_valid<=1;
                end
            end
        end
    end
endmodule
`default_nettype wire
