`default_nettype none
// timing_v13: z100_accum33_dsp with internal P feedback.
// Original: P -> fabric 33-bit mux -> C pin -> ALU (a full fabric round trip
// every accumulate, plus a load mux in front of C and A:B).
// Here: load   : OPMODE Z=C, X=0     -> P = sext(bias)
//       update : OPMODE Z=P, X=A:B   -> P = P + sext(delta)
// P[32:0] equals the original 33-bit wrap result because the low 33 bits of
// a 48-bit two's-complement sum depend only on the low 33 bits of operands.
// A:B carries delta unmuxed, C carries bias unmuxed; only OPMODE[5:4],[1:0]
// depend on load_bias.
(* use_dsp="no" *)
module z100_accum33_dsp_pfb (
    input wire clk, rst_n, cancel, load_bias, enable,
    input wire signed [31:0] bias,
    input wire signed [18:0] delta,
    output wire value_valid,
    output wire signed [32:0] value,
    output wire signed [31:0] clamped,
    output wire overflow
);
    reg initialized;
    wire update=rst_n && !cancel && (load_bias || (enable && initialized));
    wire signed [47:0] c48={{16{bias[31]}},bias};
    wire signed [47:0] ab48={{29{delta[18]}},delta};
    wire [6:0] opmode=load_bias ? 7'b0110000 : 7'b0100011;
    wire [47:0] p48;
    wire signed [32:0] feedback=p48[32:0];
    DSP48E1 #(.USE_MULT("NONE"),.AREG(0),.ACASCREG(0),.BREG(0),.BCASCREG(0),
        .CREG(0),.DREG(0),.ADREG(0),.MREG(0),.PREG(1),.OPMODEREG(0),
        .ALUMODEREG(0),.INMODEREG(0),.CARRYINREG(0),.CARRYINSELREG(0)) feedback_adder (
        .CLK(clk),.A(ab48[47:18]),.B(ab48[17:0]),.C(c48),.D(25'd0),
        .ACIN(30'd0),.BCIN(18'd0),.PCIN(48'd0),.CARRYCASCIN(1'b0),.MULTSIGNIN(1'b0),
        .OPMODE(opmode),.ALUMODE(4'b0000),.INMODE(5'b00000),
        .CARRYIN(1'b0),.CARRYINSEL(3'b000),.P(p48),
        .CEP(update),.CEA1(1'b1),.CEA2(1'b1),.CEB1(1'b1),.CEB2(1'b1),
        .CEAD(1'b1),.CEALUMODE(1'b1),.CEC(1'b1),.CECARRYIN(1'b1),.CECTRL(1'b1),
        .CED(1'b1),.CEINMODE(1'b1),.CEM(1'b1),
        .RSTA(1'b0),.RSTB(1'b0),.RSTC(1'b0),.RSTD(1'b0),
        .RSTM(1'b0),.RSTP(1'b0),.RSTCTRL(1'b0),.RSTALUMODE(1'b0),
        .RSTALLCARRYIN(1'b0),.RSTINMODE(1'b0)
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
