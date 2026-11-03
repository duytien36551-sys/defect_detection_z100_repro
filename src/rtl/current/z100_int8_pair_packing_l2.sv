`default_nettype none
// timing_v13: same exact signed INT8 pair packing as z100_int8_pair_packing,
// but MULT_MACRO LATENCY=2 (DSP48E1 AREG=BREG=1, MREG=1). The fabric->DSP
// A/B pin setup no longer includes the multiplier array. Correction metadata
// is delayed two free-running stages to stay aligned with the product.
(* use_dsp="no" *)
module z100_int8_pair_packing_l2 (
    input wire clk, rst_n, cancel, in_valid,
    input wire signed [7:0] in_activation, in_weight_low, in_weight_high,
    output wire out_valid,
    output wire signed [15:0] out_product_low, out_product_high
);
    wire signed [24:0] packed_weights=$signed({in_weight_high,9'b0,in_weight_low});
    wire signed [32:0] packed_product;
    MULT_MACRO #(.DEVICE("7SERIES"), .LATENCY(2), .STYLE("DSP"),
        .WIDTH_A(25), .WIDTH_B(8)) packed_multiplier (
        .P(packed_product), .A(packed_weights), .B(in_activation),
        .CE(1'b1), .CLK(clk), .RST(1'b0)
    );
    reg signed [7:0] activation_d1, activation_q;
    reg low_negative_d1, low_negative_q, valid_d1, valid_q;
    always @(posedge clk) begin
        activation_d1<=in_activation;   activation_q<=activation_d1;
        low_negative_d1<=in_weight_low[7]; low_negative_q<=low_negative_d1;
        if(!rst_n || cancel) begin valid_d1<=0; valid_q<=0; end
        else begin valid_d1<=in_valid; valid_q<=valid_d1; end
    end
    wire signed [15:0] low_unsigned_product=packed_product[15:0];
    wire signed [15:0] high_floor=packed_product[32:17];
    wire signed [15:0] activation_times256=$signed({activation_q,8'b0});
    assign out_product_low=low_unsigned_product-(low_negative_q ? activation_times256 : 16'sd0);
    assign out_product_high=high_floor+(low_unsigned_product[15] ? 16'sd1 : 16'sd0);
    assign out_valid=rst_n && !cancel && valid_q;
endmodule
`default_nettype wire
