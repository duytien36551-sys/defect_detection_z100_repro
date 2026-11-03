// AXI-Stream bridge for one raw INT32 output-channel dot product.
// MM2S 32-bit words encode {16'b0, signed weight[7:0], signed activation[7:0]}.
// One cfg_start arms tap_count words. S2MM emits one 32-bit raw accumulator.
// cfg_error flags early/late TLAST or INT32 overflow; firmware must reject
// results when cfg_error is set. No command-register address is assumed here.
module v8_conv_axis (
    input wire clk, input wire rst_n,
    input wire cfg_start,
    input wire [31:0] cfg_tap_count,
    input wire signed [31:0] cfg_bias,
    output wire cfg_ready,
    output reg cfg_error,
    input wire [31:0] s_axis_tdata,
    input wire s_axis_tvalid,
    output wire s_axis_tready,
    input wire s_axis_tlast,
    output reg [31:0] m_axis_tdata,
    output reg m_axis_tvalid,
    input wire m_axis_tready,
    output wire m_axis_tlast
);
    wire mac_ready, mac_valid, mac_overflow, mac_busy;
    wire signed [31:0] mac_result;
    reg [31:0] accepted;
    reg [31:0] expected;
    reg pending_result;
    wire take = s_axis_tvalid && s_axis_tready;
    assign cfg_ready = !mac_busy && !pending_result && !m_axis_tvalid && !mac_valid;
    assign s_axis_tready = mac_ready && !m_axis_tvalid;
    assign m_axis_tlast = m_axis_tvalid;
    v8_conv_mac mac(.clk(clk), .rst_n(rst_n),
        .start(cfg_start && cfg_ready), .tap_count(cfg_tap_count),
        .bias(cfg_bias), .tap_valid(take),
        .activation(s_axis_tdata[7:0]), .weight(s_axis_tdata[15:8]),
        .tap_ready(mac_ready), .out_valid(mac_valid),
        .out_overflow(mac_overflow), .raw_acc(mac_result), .busy(mac_busy));
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            accepted <= 0; expected <= 0; pending_result <= 0;
            m_axis_tdata <= 0; m_axis_tvalid <= 0; cfg_error <= 0;
        end else begin
            if (cfg_start && cfg_ready) begin
                expected <= cfg_tap_count;
                accepted <= 0;
                pending_result <= 1;
                cfg_error <= 0;
            end
            if (take) begin
                accepted <= accepted + 1'b1;
                if (s_axis_tlast != (accepted + 1'b1 == expected))
                    cfg_error <= 1;
            end
            if (mac_valid) begin
                m_axis_tdata <= mac_result;
                m_axis_tvalid <= 1;
                if (mac_overflow) cfg_error <= 1;
            end
            if (m_axis_tvalid && m_axis_tready) begin
                m_axis_tvalid <= 0;
                pending_result <= 0;
            end
        end
    end
endmodule
