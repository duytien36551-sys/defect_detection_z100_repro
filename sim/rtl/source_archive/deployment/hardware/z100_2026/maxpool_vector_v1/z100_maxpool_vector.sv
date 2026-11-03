`default_nettype none
// Private signed INT8 tap reducer. Address generation and graph ownership are
// external. Invalid spatial taps are excluded, never replaced with zero.
(* use_dsp="no" *)
module z100_maxpool_vector # (parameter integer LANES=80) (
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
    reg [LANES*8-1:0] maximum_next;
    reg [LANES-1:0] seen_next;
    reg all_seen;
    integer lane;
    wire enable = rst_n && !cancel;
    assign in_ready = enable && (!result_valid || out_ready);
    wire fire = in_valid && in_ready;
    wire metadata_good = in_lanes>0 && in_lanes<=LANES && in_epoch!=0 && in_token!=0 &&
        ((in_first && !active) || (!in_first && active && in_epoch==epoch_q &&
          in_token==token_q && in_lanes==lanes_q));
    always @* begin
        maximum_next = in_first ? {LANES{8'h80}} : maximum_q;
        seen_next = in_first ? {LANES{1'b0}} : seen_q;
        all_seen = 1'b1;
        for(lane=0;lane<LANES;lane=lane+1) begin
            if(lane<in_lanes) begin
                if(in_mask[lane]) begin
                    if(!seen_next[lane] || $signed(in_data[lane*8+:8])>$signed(maximum_next[lane*8+:8]))
                        maximum_next[lane*8+:8]=in_data[lane*8+:8];
                    seen_next[lane]=1'b1;
                end
                if(!seen_next[lane]) all_seen=1'b0;
            end else begin
                maximum_next[lane*8+:8]=8'd0;
                seen_next[lane]=1'b0;
            end
        end
    end
    // An accepted malformed beat suppresses an otherwise visible result on
    // that same edge. Normal held output is never modified by stalled input.
    wire malformed = fire && (!metadata_good || (in_last && !all_seen));
    assign out_valid = enable && result_valid && !malformed;
    assign out_epoch=result_epoch;
    assign out_token=result_token;
    assign out_lanes=result_lanes;
    assign out_data=result_data;
    always @(posedge clk) begin
        if(!rst_n || cancel) begin
            active<=0; result_valid<=0; error_valid<=0;
            epoch_q<=0;token_q<=0;lanes_q<=0;
            maximum_q<=0;seen_q<=0;
            result_epoch<=0;result_token<=0;result_lanes<=0;result_data<=0;
        end else begin
            error_valid<=0;
            if(out_valid && out_ready) result_valid<=0;
            if(fire) begin
                if(malformed) begin
                    active<=0; result_valid<=0;error_valid<=1;seen_q<=0;
                end else begin
                    epoch_q<=in_epoch;token_q<=in_token;lanes_q<=in_lanes;
                    maximum_q<=maximum_next;seen_q<=seen_next;
                    active<=!in_last;
                    if(in_last) begin
                        result_valid<=1;result_epoch<=in_epoch;result_token<=in_token;
                        result_lanes<=in_lanes;result_data<=maximum_next;
                    end
                end
            end
        end
    end
endmodule
`default_nettype wire
