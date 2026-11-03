// One output-channel dot product for a quantized YOLOv8 convolution.
// Activations and weights are signed int8. Padding taps are zero.
// The product register keeps the multiplier off the 33-bit accumulator path.
module v8_conv_mac (
    input wire clk,
    input wire rst_n,
    input wire start,
    input wire [31:0] tap_count,
    input wire signed [31:0] bias,
    input wire tap_valid,
    input wire signed [7:0] activation,
    input wire signed [7:0] weight,
    output wire tap_ready,
    output reg out_valid,
    output reg out_overflow,
    output reg signed [31:0] raw_acc,
    output reg busy
);
    reg [31:0] remaining;
    // Firmware caps a dot product at 16,383 taps. With |int8*int8| <= 16,384,
    // INT32 bias plus all taps fits in signed 33 bits, including cancellation.
    reg signed [32:0] accumulator;
    wire signed [15:0] product = activation * weight;
    reg signed [15:0] product_reg;
    reg product_valid;
    reg product_last;
    reg final_pending;
    wire signed [32:0] product_ext = {{17{product_reg[15]}}, product_reg};
    wire signed [32:0] accumulated_product = accumulator + product_ext;
    wire accumulator_overflow = accumulator[32] ^ accumulator[31];
    assign tap_ready = busy && (remaining != 0);

    function signed [31:0] clamp32;
        input signed [32:0] x;
        begin
            if (x[32] != x[31])
                clamp32 = x[32] ? 32'sh80000000 : 32'sh7fffffff;
            else
                clamp32 = x[31:0];
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            remaining <= 0;
            accumulator <= 0;
            product_reg <= 0;
            product_valid <= 0;
            product_last <= 0;
            final_pending <= 0;
            raw_acc <= 0;
            out_valid <= 0;
            out_overflow <= 0;
            busy <= 0;
        end else begin
            out_valid <= 0;
            if (start && !busy) begin
                accumulator <= {{1{bias[31]}}, bias};
                remaining <= tap_count;
                product_reg <= 0;
                product_valid <= 0;
                product_last <= 0;
                final_pending <= 0;
                out_overflow <= 0;
                if (tap_count == 0 || tap_count > 32'd16383) begin
                    raw_acc <= bias;
                    out_valid <= 1;
                    out_overflow <= tap_count > 32'd16383;
                    busy <= 0;
                end else busy <= 1;
            end else begin
                // Accept one tap per cycle while a previous product is accumulated.
                if (tap_valid && tap_ready) begin
                    product_reg <= product;
                    product_valid <= 1;
                    product_last <= remaining == 1;
                    remaining <= remaining - 1'b1;
                end else begin
                    product_valid <= 0;
                end

                // Accumulate the prior cycle's registered product.
                if (product_valid) begin
                    accumulator <= accumulated_product;
                    if (product_last) begin
                        product_valid <= 0;
                        final_pending <= 1;
                    end
                end

                // Saturate only after the final product has reached the accumulator.
                if (final_pending) begin
                    raw_acc <= clamp32(accumulator);
                    out_overflow <= accumulator_overflow;
                    out_valid <= 1;
                    busy <= 0;
                    final_pending <= 0;
                end
            end
        end
    end
endmodule
