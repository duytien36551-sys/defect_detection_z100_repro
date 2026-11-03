`default_nettype none
// Isolated exact signed 33-bit feedback accumulator using one fabric adder.
// State payload is intentionally not reset; initialized masks it after reset/cancel.
module z100_accum33_fabric32_v1 (
    input wire clk, rst_n, cancel, load_bias, enable,
    input wire signed [31:0] bias,
    input wire signed [18:0] delta,
    output wire value_valid,
    output wire signed [32:0] value,
    output wire signed [31:0] clamped,
    output wire overflow
);
    reg initialized;
    reg signed [32:0] feedback_q;

    wire signed [32:0] feedback = feedback_q;
    wire signed [32:0] operand_a =
        load_bias ? $signed({bias[31], bias}) : feedback;
    wire signed [32:0] operand_b =
        load_bias ? 33'sd0 : $signed({{14{delta[18]}}, delta});
    wire update = rst_n && !cancel &&
        (load_bias || (enable && initialized));

    // The mapping directive is scoped only to this target 33-bit adder.
    (* use_dsp = "no" *) wire signed [32:0] feedback_sum = operand_a + operand_b;

    always @(posedge clk) begin
        if (update)
            feedback_q <= feedback_sum;

        if (!rst_n || cancel)
            initialized <= 1'b0;
        else if (load_bias)
            initialized <= 1'b1;
    end

    assign value_valid = rst_n && !cancel && initialized;
    assign value = value_valid ? feedback : 33'sd0;
    assign overflow = value_valid && (feedback[32] != feedback[31]);
    assign clamped = !value_valid ? 32'sd0 :
        overflow ? (feedback[32] ? 32'sh80000000 : 32'sh7fffffff) :
                   feedback[31:0];
endmodule
`default_nettype wire
