`default_nettype none
// Private exact native feedback experiment. No reset on arithmetic payload:
// each accepted load writes the new signed32 bias before updates are legal.
(* use_dsp="no" *)
module z100_accum33_dsp (
    input wire clk, rst_n, cancel, load_bias, enable,
    input wire signed [31:0] bias,
    input wire signed [18:0] delta,
    output wire value_valid,
    output wire signed [32:0] value,
    output wire signed [31:0] clamped,
    output wire overflow
);
    reg initialized;
    wire signed [32:0] feedback;
    wire signed [32:0] operand_a=load_bias ? $signed({bias[31],bias}) : feedback;
    wire signed [32:0] operand_b=load_bias ? 33'sd0 : $signed({{14{delta[18]}},delta});
    wire update=rst_n && !cancel && (load_bias || (enable && initialized));
    wire unused_carry;
    ADDSUB_MACRO #(.DEVICE("7SERIES"),.LATENCY(1),.STYLE("DSP"),.WIDTH(33)) feedback_adder (
        .RESULT(feedback),.CARRYOUT(unused_carry),.A(operand_a),.B(operand_b),
        .ADD_SUB(1'b1),.CARRYIN(1'b0),.CE(update),.CLK(clk),.RST(1'b0)
    );
    always @(posedge clk) begin
        if(!rst_n || cancel) initialized<=0;
        else if(load_bias) initialized<=1;
    end
    assign value_valid=rst_n && !cancel && initialized;
    assign value=value_valid ? feedback : 33'sd0;
    assign overflow=value_valid && (feedback[32]!=feedback[31]);
    assign clamped=!value_valid ? 32'sd0 : overflow ?
        (feedback[32] ? 32'sh80000000 : 32'sh7fffffff) : feedback[31:0];
endmodule
`default_nettype wire
