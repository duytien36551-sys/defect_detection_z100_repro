`default_nettype none
// Exact signed INT8 pair sharing one activation. A25={high,9'b0,low_u8};
// the low unsigned-weight product is signed16, so its sign corrects the high
// extraction. A second correction restores the low weight's signed meaning.
// One arithmetic pipeline stage, free-running like the frozen native MAC.
(* use_dsp="no" *)
module z100_int8_pair_packing (
    input wire clk, rst_n, cancel, in_valid,
    input wire signed [7:0] in_activation, in_weight_low, in_weight_high,
    output wire out_valid,
    output wire signed [15:0] out_product_low, out_product_high
);
    wire signed [24:0] packed_weights=$signed({in_weight_high,9'b0,in_weight_low});
    (* use_dsp="yes" *) reg signed [32:0] packed_product;
    reg signed [7:0] activation_q;
    reg low_negative_q, valid_q;
    always @(posedge clk) begin
        packed_product<=packed_weights*in_activation;
        activation_q<=in_activation;
        low_negative_q<=in_weight_low[7];
        if(!rst_n || cancel) valid_q<=0;
        else valid_q<=in_valid;
    end
    wire signed [15:0] low_unsigned_product=packed_product[15:0];
    wire signed [15:0] high_floor=packed_product[32:17];
    wire signed [15:0] activation_times256=$signed({activation_q,8'b0});
    assign out_product_low=low_unsigned_product-(low_negative_q ? activation_times256 : 16'sd0);
    assign out_product_high=high_floor+(low_unsigned_product[15] ? 16'sd1 : 16'sd0);
    assign out_valid=rst_n && !cancel && valid_q;
endmodule
`default_nettype wire
