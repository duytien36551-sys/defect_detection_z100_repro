`default_nettype none
// 2026-10-31 (routing fix): four-tap INT8 weight-pair dot product in one
// DSP48E1 PCOUT->PCIN cascade (WP486-style signed pair packing).
//   packed_t = wh_t*2^17 + wl_t          (25-bit signed A operand)
//   P        = sum_t a_t * packed_t      (accumulated in the cascade)
//   low  = sext(P[16:0])                 = sum_t a_t*wl_t
//   high = P[33:17] + P[16]              = sum_t a_t*wh_t
// Exact for a in [-128,127] and wl/wh in [-127,127]: |low|,|high| <= 65024 < 2^16
// and packed_t fits 25 bits. Weight byte 0x80 (-128) is rejected at MAC
// configuration (z100_window_mac_timing_v13 commit error 2).
// Tap t operands must arrive t cycles after tap 0 (caller skews them).
// Each DSP: AREG=BREG=1, MREG=1, PREG=1 -> P3 valid 3+3 = 6 edges after the
// tap-0 operands. Free-running, no CE/reset: validity is tracked by the caller.
(* use_dsp="no" *)
module z100_int8_pair_cascade4 (
    input wire clk,
    input wire signed [24:0] packed0, packed1, packed2, packed3,
    input wire signed [7:0] act0, act1, act2, act3,
    output wire signed [16:0] out_low, out_high
);
    wire [47:0] p [0:3];
    wire [47:0] pc [0:3];
    wire signed [24:0] pk [0:3];
    wire signed [7:0] ac [0:3];
    assign pk[0]=packed0; assign pk[1]=packed1; assign pk[2]=packed2; assign pk[3]=packed3;
    assign ac[0]=act0; assign ac[1]=act1; assign ac[2]=act2; assign ac[3]=act3;
    genvar t;
    generate for(t=0;t<4;t=t+1) begin : gen_tap
        DSP48E1 #(.USE_MULT("MULTIPLY"),.USE_DPORT("FALSE"),.USE_SIMD("ONE48"),
            .AREG(1),.ACASCREG(1),.BREG(1),.BCASCREG(1),.CREG(0),.DREG(0),.ADREG(0),
            .MREG(1),.PREG(1),.OPMODEREG(0),.ALUMODEREG(0),.INMODEREG(0),
            .CARRYINREG(0),.CARRYINSELREG(0)) dsp (
            .CLK(clk),
            .A({{5{pk[t][24]}},pk[t]}), .B({{10{ac[t][7]}},ac[t]}),
            .C(48'd0), .D(25'd0),
            .ACIN(30'd0), .BCIN(18'd0), .PCIN(t==0 ? 48'd0 : pc[t==0 ? 0 : t-1]),
            .CARRYCASCIN(1'b0), .MULTSIGNIN(1'b0),
            // X=M, Y=M (product); Z = 0 for tap 0, PCIN for taps 1..3.
            .OPMODE(t==0 ? 7'b0000101 : 7'b0010101), .ALUMODE(4'b0000), .INMODE(5'b00000),
            .CARRYIN(1'b0), .CARRYINSEL(3'b000),
            .P(p[t]), .PCOUT(pc[t]),
            .CEP(1'b1),.CEA1(1'b1),.CEA2(1'b1),.CEB1(1'b1),.CEB2(1'b1),
            .CEAD(1'b1),.CEALUMODE(1'b1),.CEC(1'b1),.CECARRYIN(1'b1),.CECTRL(1'b1),
            .CED(1'b1),.CEINMODE(1'b1),.CEM(1'b1),
            .RSTA(1'b0),.RSTB(1'b0),.RSTC(1'b0),.RSTD(1'b0),
            .RSTM(1'b0),.RSTP(1'b0),.RSTCTRL(1'b0),.RSTALUMODE(1'b0),
            .RSTALLCARRYIN(1'b0),.RSTINMODE(1'b0)
        );
    end endgenerate
    wire [47:0] last = p[3];
    assign out_low  = $signed(last[16:0]);
    assign out_high = $signed(last[33:17]) + $signed({16'd0, last[16]});
endmodule
`default_nettype wire
