// NCHW byte address for one convolution tap. Invalid taps represent zero
// padding and must contribute signed zero to v8_conv_mac.
module v8_window_addr (
    input wire [15:0] input_width,
    input wire [15:0] input_height,
    input wire [15:0] input_channels,
    input wire [15:0] output_x,
    input wire [15:0] output_y,
    input wire [7:0] stride,
    input wire [7:0] pad_left,
    input wire [7:0] pad_top,
    input wire [7:0] kernel_x,
    input wire [7:0] kernel_y,
    input wire [15:0] input_channel,
    output wire address_valid,
    output wire [31:0] byte_address
);
    wire signed [32:0] x = $signed({1'b0, output_x}) *
                            $signed({1'b0, stride}) + $signed({1'b0, kernel_x}) -
                            $signed({1'b0, pad_left});
    wire signed [32:0] y = $signed({1'b0, output_y}) *
                            $signed({1'b0, stride}) + $signed({1'b0, kernel_y}) -
                            $signed({1'b0, pad_top});
    wire [48:0] linear = (input_channel * input_height + y) *
                         input_width + x;
    assign address_valid = input_width != 0 && input_height != 0 &&
                           input_channels != 0 && stride != 0 &&
                           input_channel < input_channels &&
                           x >= 0 && x < $signed({1'b0, input_width}) &&
                           y >= 0 && y < $signed({1'b0, input_height}) &&
                           linear <= 49'h0ffffffff;
    assign byte_address = address_valid ? linear[31:0] : 32'd0;
endmodule
