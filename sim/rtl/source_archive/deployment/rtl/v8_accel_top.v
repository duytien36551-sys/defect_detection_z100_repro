// Batch wrapper for the existing one-dot V8 convolution core.
// Register 0 bit 0 rising edge starts an operation; bit 1 held high aborts it.
// Register 1 is taps per dot, register 2 is signed bias, and register 3 is the
// number of output dots. Input words retain the existing {16'h0, weight, act}
// encoding. Each dot produces one raw INT32 word followed by one status word.
module v8_accel_top (
    input wire sclk, input wire s_rst_n,
    input wire [31:0] slave_lite_reg0, slave_lite_reg1,
    input wire [31:0] slave_lite_reg2, slave_lite_reg3,
    input wire [31:0] s_axis_mm2s_tdata,
    input wire [3:0] s_axis_mm2s_tkeep,
    input wire s_axis_mm2s_tvalid,
    output wire s_axis_mm2s_tready,
    input wire s_axis_mm2s_tlast,
    output wire [31:0] s_axis_s2mm_tdata,
    output wire [3:0] s_axis_s2mm_tkeep,
    output wire s_axis_s2mm_tvalid,
    input wire s_axis_s2mm_tready,
    output wire s_axis_s2mm_tlast,
    output reg task_finish
);
    localparam [2:0] PH_IDLE       = 3'd0;
    localparam [2:0] PH_DOT_START  = 3'd1;
    localparam [2:0] PH_INPUT      = 3'd2;
    localparam [2:0] PH_WAIT_DOT   = 3'd3;
    localparam [2:0] PH_RAW        = 3'd4;
    localparam [2:0] PH_STATUS     = 3'd5;
    localparam [2:0] PH_CONFIG_CHECK = 3'd6;
    localparam [31:0] STATUS_MAGIC = 32'h563A0000;

    reg abort_sync;
    wire core_rst_n = s_rst_n && !abort_sync;
    wire streams_enabled = !slave_lite_reg0[1] && core_rst_n;

    reg start_prev;
    reg [2:0] phase;
    reg [31:0] taps_latched;
    reg [10:0] dots_remaining;
    reg signed [31:0] bias_latched;
    reg [31:0] total_words_latched;
    reg [31:0] input_words_accepted;
    reg [31:0] input_words_in_dot;
    reg [31:0] result_latched;
    reg operation_error;
    reg config_ranges_valid;

    wire start_rise = slave_lite_reg0[0] && !start_prev;
    wire probe_config = (slave_lite_reg1 == 0) && (slave_lite_reg3 == 1);
    wire [24:0] requested_words = slave_lite_reg1[13:0] *
                                  slave_lite_reg3[10:0];
    wire valid_scalar_config =
        (slave_lite_reg3 >= 1) && (slave_lite_reg3 <= 1024) &&
        (slave_lite_reg1 >= 1) && (slave_lite_reg1 <= 16383);

    wire core_cfg_ready;
    wire core_cfg_error;
    wire core_s_ready;
    wire core_m_valid;
    wire [31:0] core_m_data;
    wire core_start = (phase == PH_DOT_START) && core_cfg_ready && streams_enabled;
    wire core_s_valid = s_axis_mm2s_tvalid && (phase == PH_INPUT) && streams_enabled;
    wire core_s_last = input_words_in_dot == (taps_latched - 1'b1);
    wire core_m_ready = (phase == PH_WAIT_DOT) && streams_enabled;
    wire input_handshake = s_axis_mm2s_tvalid && s_axis_mm2s_tready;
    wire expected_packet_last =
        (input_words_accepted + 1'b1) == total_words_latched;
    wire malformed_input = input_handshake &&
        ((s_axis_mm2s_tkeep != 4'hf) ||
         (s_axis_mm2s_tlast != expected_packet_last));
    wire final_tap_in_dot =
        (input_words_in_dot + 1'b1) == taps_latched;
    wire accept_start = start_rise && (phase == PH_IDLE) &&
                        streams_enabled && core_cfg_ready;

    assign s_axis_mm2s_tready = core_s_ready && (phase == PH_INPUT) &&
                                streams_enabled;
    assign s_axis_s2mm_tvalid =
        ((phase == PH_RAW) || (phase == PH_STATUS)) && streams_enabled;
    assign s_axis_s2mm_tdata = (phase == PH_STATUS) ?
        (STATUS_MAGIC | {31'b0, operation_error}) : result_latched;
    assign s_axis_s2mm_tkeep = 4'hf;
    assign s_axis_s2mm_tlast = (phase == PH_STATUS) &&
                               (dots_remaining == 1);

    v8_conv_axis core (
        .clk(sclk), .rst_n(core_rst_n), .cfg_start(core_start),
        .cfg_tap_count(taps_latched), .cfg_bias(bias_latched),
        .cfg_ready(core_cfg_ready), .cfg_error(core_cfg_error),
        .s_axis_tdata(s_axis_mm2s_tdata), .s_axis_tvalid(core_s_valid),
        .s_axis_tready(core_s_ready), .s_axis_tlast(core_s_last),
        .m_axis_tdata(core_m_data), .m_axis_tvalid(core_m_valid),
        .m_axis_tready(core_m_ready), .m_axis_tlast()
    );

    always @(posedge sclk or negedge s_rst_n) begin
        if (!s_rst_n)
            abort_sync <= 1'b0;
        else
            abort_sync <= slave_lite_reg0[1];
    end

    always @(posedge sclk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            start_prev <= 1'b0;
            phase <= PH_IDLE;
            taps_latched <= 0;
            dots_remaining <= 0;
            bias_latched <= 0;
            total_words_latched <= 0;
            input_words_accepted <= 0;
            input_words_in_dot <= 0;
            result_latched <= 0;
            operation_error <= 1'b0;
            config_ranges_valid <= 1'b0;
            task_finish <= 1'b0;
        end else begin
            start_prev <= slave_lite_reg0[0];
            task_finish <= 1'b0;

            if (accept_start) begin
                taps_latched <= slave_lite_reg1;
                bias_latched <= slave_lite_reg2;
                input_words_accepted <= 0;
                input_words_in_dot <= 0;
                config_ranges_valid <= valid_scalar_config;
                if (probe_config) begin
                    total_words_latched <= 0;
                    dots_remaining <= 1;
                    result_latched <= slave_lite_reg2;
                    operation_error <= 1'b0;
                    phase <= PH_RAW;
                end else begin
                    total_words_latched <= requested_words;
                    dots_remaining <= slave_lite_reg3[10:0];
                    result_latched <= 0;
                    operation_error <= 1'b0;
                    phase <= PH_CONFIG_CHECK;
                end
            end else begin
                if (phase == PH_CONFIG_CHECK) begin
                    if (!config_ranges_valid || total_words_latched > 16383) begin
                        dots_remaining <= 1;
                        operation_error <= 1;
                        phase <= PH_RAW;
                    end else phase <= PH_DOT_START;
                end
                if (core_start) begin
                    input_words_in_dot <= 0;
                    phase <= PH_INPUT;
                end

                if (input_handshake) begin
                    input_words_accepted <= input_words_accepted + 1'b1;
                    input_words_in_dot <= input_words_in_dot + 1'b1;
                    if (malformed_input)
                        operation_error <= 1'b1;
                    if (final_tap_in_dot) begin
                        input_words_in_dot <= 0;
                        phase <= PH_WAIT_DOT;
                    end
                end

                if ((phase == PH_WAIT_DOT) && core_m_valid && core_m_ready) begin
                    result_latched <= core_m_data;
                    operation_error <= operation_error || core_cfg_error;
                    phase <= PH_RAW;
                end

                if ((phase == PH_RAW) && s_axis_s2mm_tready && streams_enabled)
                    phase <= PH_STATUS;

                if ((phase == PH_STATUS) && s_axis_s2mm_tready &&
                    streams_enabled) begin
                    if (dots_remaining == 1) begin
                        phase <= PH_IDLE;
                        task_finish <= 1'b1;
                    end else begin
                        dots_remaining <= dots_remaining - 1'b1;
                        phase <= PH_DOT_START;
                    end
                end
            end
        end
    end
endmodule
