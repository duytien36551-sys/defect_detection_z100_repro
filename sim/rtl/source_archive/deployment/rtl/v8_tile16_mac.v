// 16-output-lane INT8 dot-product tile for quantized YOLO convolutions.
//
// Configuration contract:
//   * cfg_weight_we writes one tap address in all 16 independent weight banks.
//     cfg_weights[8*lane +: 8] is the signed weight for that lane.
//   * cfg_bias_we writes all 16 signed biases. Configuration is accepted only
//     while cfg_ready is high; every tap used by a run must be preloaded.
//   * run starts one spatial site with tap_count in 1..MAX_TAPS and
//     lane_count in 1..16. The first lane_count outputs are active.
//   * While act_ready is high, each act_valid/act_data handshake consumes one
//     signed activation tap and advances the tap index by exactly one. A
//     missing act_valid stalls the tap index without disturbing the pipeline.
//   * out_raw is packed as signed 32-bit lane words, lane 0 in bits [31:0].
//     out_valid pulses only after all tap products have reached the accumulators;
//     inactive tail lanes are zero. out_overflow has one bit per lane.
//
// The weight memories are generated as 16 separate synchronous-read banks.
// No activation or weight is saturated during accumulation. Each lane sums in
// signed 33 bits, then clamps to signed 32 bits using v8_conv_mac semantics.
module v8_tile16_mac #(
    parameter MAX_TAPS = 4091
) (
    input wire clk,
    input wire rst_n,

    input wire cfg_weight_we,
    input wire [11:0] cfg_weight_addr,
    input wire [127:0] cfg_weights,
    input wire cfg_bias_we,
    input wire [511:0] cfg_biases,
    output wire cfg_ready,

    input wire run,
    input wire [12:0] tap_count,
    input wire [4:0] lane_count,
    input wire act_valid,
    input wire signed [7:0] act_data,
    output wire act_ready,

    output reg out_valid,
    output reg [4:0] out_lane_count,
    output reg [511:0] out_raw,
    output reg [15:0] out_overflow,
    output reg error,
    output reg busy
);
    reg [12:0] taps_remaining;
    reg [11:0] tap_index;
    reg [4:0] active_lanes;
    reg signed [31:0] bias_bank [0:15];
    reg signed [32:0] accumulator [0:15];
    reg signed [7:0] activation_q;
    reg signed [7:0] activation_stage;
    reg stage0_valid;
    reg stage0_last;
    reg stage1_valid;
    reg stage1_last;
    reg stage2_valid;
    reg stage2_last;
    reg signed [15:0] product_q [0:15];

    wire signed [7:0] weight_read [0:15];
    wire signed [15:0] product_value [0:15];
    wire signed [32:0] accumulated_value [0:15];
    wire accept_tap;
    integer i;

    assign cfg_ready = !busy && !run;
    assign act_ready = busy && (taps_remaining != 0);
    assign accept_tap = act_valid && act_ready;

    function [31:0] clamp_signed33;
        input signed [32:0] value;
        begin
            if (value[32] != value[31])
                clamp_signed33 = value[32] ? 32'h80000000 : 32'h7fffffff;
            else
                clamp_signed33 = value[31:0];
        end
    endfunction

    genvar lane;
    generate
        for (lane = 0; lane < 16; lane = lane + 1) begin : gen_weight_lane
            // One independent 8-bit, MAX_TAPS-deep synchronous-read bank per
            // output lane. Tap weights are loaded in parallel across lanes.
            reg signed [7:0] weight_bank [0:MAX_TAPS-1];
            reg signed [7:0] weight_q;
            reg signed [7:0] weight_stage;
            (* use_dsp = "yes" *) wire signed [15:0] product_direct;

            assign weight_read[lane] = weight_q;
            assign product_direct = activation_stage * weight_stage;
            assign product_value[lane] = product_direct;
            assign accumulated_value[lane] = accumulator[lane] +
                {{17{product_q[lane][15]}}, product_q[lane]};

            always @(posedge clk) begin
                if (cfg_weight_we && cfg_ready && (cfg_weight_addr < MAX_TAPS))
                    weight_bank[cfg_weight_addr] <= cfg_weights[(lane * 8) +: 8];
                if (accept_tap)
                    weight_q <= weight_bank[tap_index];
                if (stage0_valid)
                    weight_stage <= weight_q;
            end
        end
    endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            taps_remaining <= 0;
            tap_index <= 0;
            active_lanes <= 0;
            activation_q <= 0;
            activation_stage <= 0;
            stage0_valid <= 0;
            stage0_last <= 0;
            stage1_valid <= 0;
            stage1_last <= 0;
            stage2_valid <= 0;
            stage2_last <= 0;
            out_valid <= 0;
            out_lane_count <= 0;
            out_raw <= 0;
            out_overflow <= 0;
            error <= 0;
            busy <= 0;
            for (i = 0; i < 16; i = i + 1) begin
                bias_bank[i] <= 0;
                accumulator[i] <= 0;
                product_q[i] <= 0;
            end
        end else begin
            out_valid <= 0;
            error <= 0;

            if (cfg_bias_we && cfg_ready) begin
                for (i = 0; i < 16; i = i + 1)
                    bias_bank[i] <= cfg_biases[(i * 32) +: 32];
            end

            if (cfg_weight_we && cfg_ready && (cfg_weight_addr >= MAX_TAPS))
                error <= 1;

            if (run && !busy) begin
                stage0_valid <= 0;
                stage0_last <= 0;
                stage1_valid <= 0;
                stage1_last <= 0;
                stage2_valid <= 0;
                stage2_last <= 0;
                if ((tap_count == 0) || (tap_count > MAX_TAPS) ||
                    (lane_count == 0) || (lane_count > 16)) begin
                    error <= 1;
                    busy <= 0;
                end else begin
                    taps_remaining <= tap_count;
                    tap_index <= 0;
                    active_lanes <= lane_count;
                    out_lane_count <= 0;
                    out_raw <= 0;
                    out_overflow <= 0;
                    for (i = 0; i < 16; i = i + 1) begin
                        accumulator[i] <= {{1{bias_bank[i][31]}}, bias_bank[i]};
                        product_q[i] <= 0;
                    end
                    busy <= 1;
                end
            end else begin
                // Stage 0 captures one activation while each lane's synchronous
                // weight bank reads the same tap address.
                stage0_valid <= accept_tap;
                if (accept_tap) begin
                    activation_q <= act_data;
                    stage0_last <= (taps_remaining == 1);
                    taps_remaining <= taps_remaining - 1'b1;
                    tap_index <= tap_index + 1'b1;
                end

                // Stage 1 separates BRAM read timing from the DSP multiplier.
                stage1_valid <= stage0_valid;
                if (stage0_valid) begin
                    stage1_last <= stage0_last;
                    activation_stage <= activation_q;
                end

                // Stage 2 registers all signed products. Gaps in act_valid
                // naturally bubble through without advancing the tap index.
                stage2_valid <= stage1_valid;
                if (stage1_valid) begin
                    stage2_last <= stage1_last;
                    for (i = 0; i < 16; i = i + 1)
                        product_q[i] <= product_value[i];
                end

                // Accumulate only active lanes. On the final product, publish
                // every lane together after including that product in the sum.
                if (stage2_valid) begin
                    for (i = 0; i < 16; i = i + 1) begin
                        if (i < active_lanes)
                            accumulator[i] <= accumulated_value[i];
                        if (stage2_last) begin
                            if (i < active_lanes) begin
                                out_raw[(i * 32) +: 32] <= clamp_signed33(accumulated_value[i]);
                                out_overflow[i] <= accumulated_value[i][32] ^ accumulated_value[i][31];
                            end else begin
                                out_raw[(i * 32) +: 32] <= 0;
                                out_overflow[i] <= 0;
                            end
                        end
                    end
                    if (stage2_last) begin
                        out_valid <= 1;
                        out_lane_count <= active_lanes;
                        busy <= 0;
                    end
                end
            end
        end
    end
endmodule
