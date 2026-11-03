// Serialized AXI-stream front end for v8_tile16_mac. This is a new tile ABI;
// it is intentionally separate from the deployed scalar v8_conv_axis design.
// A command starts only when cfg_ready is high. R1 packs T[12:0], L[20:16],
// S[30:24]. LOAD consumes 16 bias words and T groups of four weight words.
// RUN consumes S groups of ceil(T/4) activation words. Every response is
// MAGIC, sequence, filter_id, R1, optional S*L raw words, status (TLAST).
module v8_tile16_axis (
    input wire clk,
    input wire rst_n,
    input wire cfg_start,
    input wire cfg_abort,
    input wire [2:0] cfg_opcode,
    input wire [31:0] cfg_r1,
    input wire [31:0] cfg_sequence,
    input wire [31:0] cfg_filter_id,
    output wire cfg_ready,
    output reg cfg_error,
    input wire [31:0] s_axis_tdata,
    input wire [3:0] s_axis_tkeep,
    input wire s_axis_tvalid,
    output wire s_axis_tready,
    input wire s_axis_tlast,
    output reg [31:0] m_axis_tdata,
    output wire m_axis_tvalid,
    input wire m_axis_tready,
    output wire m_axis_tlast
);
    localparam [31:0] MAGIC = 32'h563b0001;
    localparam [3:0] IDLE = 0, LOAD_BIAS = 1, BIAS_COMMIT = 2,
        LOAD_WEIGHT = 3, WEIGHT_COMMIT = 4, RUN_START = 5,
        RUN_WORD = 6, RUN_FEED = 7, RUN_WAIT = 8,
        RUN_STORE = 9, DRAIN = 10, RESPONSE = 11,
        RESPONSE_PREP = 12, CONFIG = 13;
    reg [3:0] state;
    reg [31:0] r1_q, sequence_q, filter_q;
    reg [2:0] opcode_q;
    reg [12:0] taps_q, taps_left;
    reg [4:0] lanes_q;
    reg [6:0] sites_q, site_index;
    reg [11:0] tap_index;
    reg [3:0] bias_index;
    reg [1:0] weight_word_index, byte_index;
    reg [12:0] word_index, words_per_site;
    reg [2:0] feed_bytes;
    reg [31:0] word_buffer;
    reg [511:0] biases_q, result_q;
    reg [127:0] weights_q;
    reg [4:0] store_lane;
    reg [31:0] status_q;
    reg [12:0] response_index, response_words;
    reg [11:0] response_payload_q;
    reg [6:0] response_site;
    reg [4:0] response_lane;
    reg loaded;
    reg [31:0] loaded_filter;
    reg [12:0] loaded_taps;
    reg [4:0] loaded_lanes;
    (* ram_style = "block" *) reg [31:0] result_mem [0:1023];
    reg [31:0] result_read_q;
    wire mac_cfg_ready, mac_act_ready, mac_valid, mac_error, mac_busy;
    wire [4:0] mac_lane_count;
    wire [511:0] mac_raw;
    wire [15:0] mac_overflow;
    wire take_input = s_axis_tvalid && s_axis_tready;
    wire take_output = m_axis_tvalid && m_axis_tready;
    wire final_word = (site_index + 1'b1 == sites_q) &&
                      (word_index + 1'b1 == words_per_site);
    wire final_weight = (tap_index + 1'b1 == taps_q) &&
                        (weight_word_index == 2'd3);
    wire valid_taps = r1_q[15:0] >= 1 && r1_q[15:0] <= 4091;
    wire valid_lanes = r1_q[20:16] >= 1 && r1_q[20:16] <= 16;
    wire valid_sites = r1_q[30:24] >= 1 && r1_q[30:24] <= 64;
    wire [31:0] word_count = (r1_q[15:0] + 3) >> 2;
    wire mac_reset_n = rst_n && !cfg_abort &&
                       !(state == DRAIN || (state == RESPONSE && status_q != 0));
    integer i;

    assign cfg_ready = (state == IDLE) && !cfg_abort;
    assign s_axis_tready = !cfg_abort &&
        (state == LOAD_BIAS || state == LOAD_WEIGHT ||
         state == RUN_WORD || state == DRAIN);
    assign m_axis_tvalid = (state == RESPONSE) && !cfg_abort;
    assign m_axis_tlast = m_axis_tvalid &&
        (response_index + 1'b1 == response_words);

    always @* begin
        m_axis_tdata = 0;
        if (state == RESPONSE) begin
            case (response_index)
                0: m_axis_tdata = MAGIC;
                1: m_axis_tdata = sequence_q;
                2: m_axis_tdata = filter_q;
                3: m_axis_tdata = r1_q;
                default: begin
                    if (response_index + 1'b1 == response_words)
                        m_axis_tdata = status_q;
                    else if (opcode_q == 2 && status_q == 0)
                        m_axis_tdata = result_read_q;
                end
            endcase
        end
    end

    v8_tile16_mac core (
        .clk(clk), .rst_n(mac_reset_n),
        .cfg_weight_we(state == WEIGHT_COMMIT),
        .cfg_weight_addr(tap_index), .cfg_weights(weights_q),
        .cfg_bias_we(state == BIAS_COMMIT), .cfg_biases(biases_q),
        .cfg_ready(mac_cfg_ready), .run(state == RUN_START),
        .tap_count(taps_q), .lane_count(lanes_q),
        .act_valid(state == RUN_FEED),
        .act_data(word_buffer[(byte_index * 8) +: 8]),
        .act_ready(mac_act_ready), .out_valid(mac_valid),
        .out_lane_count(mac_lane_count), .out_raw(mac_raw),
        .out_overflow(mac_overflow), .error(mac_error), .busy(mac_busy)
    );

    // Keep storage in a reset-free clocked process so Vivado can infer one
    // true dual-port BRAM instead of expanding 1024 words into flip-flops.
    always @(posedge clk) begin
        if (state == RUN_STORE)
            result_mem[{site_index, 4'b0000} + store_lane] <=
                result_q[(store_lane * 32) +: 32];
        if (state == RESPONSE_PREP && response_index >= 4 &&
            response_index + 1'b1 < response_words &&
            opcode_q == 2 && status_q == 0)
            result_read_q <= result_mem[
                {response_site, 4'b0000} + response_lane];
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            r1_q <= 0; sequence_q <= 0; filter_q <= 0; opcode_q <= 0;
            taps_q <= 0; taps_left <= 0; lanes_q <= 0;
            sites_q <= 0; site_index <= 0; tap_index <= 0;
            bias_index <= 0; weight_word_index <= 0; byte_index <= 0;
            word_index <= 0; words_per_site <= 0; feed_bytes <= 0;
            word_buffer <= 0; biases_q <= 0; result_q <= 0;
            weights_q <= 0; store_lane <= 0; status_q <= 0;
            response_index <= 0; response_words <= 5;
            response_payload_q <= 0;
            response_site <= 0; response_lane <= 0;
            loaded <= 0; loaded_filter <= 0;
            loaded_taps <= 0; loaded_lanes <= 0; cfg_error <= 0;
        end else if (cfg_abort) begin
            state <= IDLE;
            loaded <= 0;
            cfg_error <= 1;
            status_q <= 1;
        end else begin
            case (state)
                IDLE: if (cfg_start) begin
                    r1_q <= cfg_r1;
                    sequence_q <= cfg_sequence;
                    filter_q <= cfg_filter_id;
                    opcode_q <= cfg_opcode;
                    response_index <= 0;
                    response_site <= 0;
                    response_lane <= 0;
                    status_q <= 0;
                    cfg_error <= 0;
                    state <= CONFIG;
                end
                CONFIG: begin
                    taps_q <= r1_q[12:0];
                    lanes_q <= r1_q[20:16];
                    sites_q <= r1_q[30:24];
                    words_per_site <= word_count[12:0];
                    if (opcode_q == 0) begin
                        response_words <= 5;
                        if (r1_q != 0) begin
                            status_q <= 1;
                            cfg_error <= 1;
                            loaded <= 0;
                        end
                        state <= RESPONSE_PREP;
                    end else if (opcode_q == 1) begin
                        response_words <= 5;
                        loaded <= 0;
                        if (valid_taps && valid_lanes &&
                            r1_q[30:24] == 0 &&
                            r1_q[31] == 0 && r1_q[23:21] == 0) begin
                            bias_index <= 0;
                            tap_index <= 0;
                            weight_word_index <= 0;
                            state <= LOAD_BIAS;
                        end else begin
                            status_q <= 1;
                            cfg_error <= 1;
                            state <= DRAIN;
                        end
                    end else if (opcode_q == 2) begin
                        response_payload_q <= r1_q[30:24] * r1_q[20:16];
                        response_words <= 5;
                        if (valid_taps && valid_lanes && valid_sites &&
                            r1_q[31] == 0 && r1_q[23:21] == 0 &&
                            loaded && loaded_filter == filter_q &&
                            loaded_taps == r1_q[12:0] &&
                            loaded_lanes == r1_q[20:16]) begin
                            site_index <= 0;
                            word_index <= 0;
                            taps_left <= r1_q[12:0];
                            state <= RUN_START;
                        end else begin
                            status_q <= 1;
                            cfg_error <= 1;
                            loaded <= 0;
                            state <= DRAIN;
                        end
                    end else begin
                        response_words <= 5;
                        status_q <= 1;
                        cfg_error <= 1;
                        state <= RESPONSE_PREP;
                    end
                end
                LOAD_BIAS: if (take_input) begin
                    biases_q[(bias_index * 32) +: 32] <= s_axis_tdata;
                    if (s_axis_tlast || s_axis_tkeep != 4'hf) begin
                        status_q <= 1;
                        cfg_error <= 1;
                        state <= s_axis_tlast ? RESPONSE_PREP : DRAIN;
                    end else if (bias_index == 15) begin
                        state <= BIAS_COMMIT;
                    end else bias_index <= bias_index + 1'b1;
                end
                BIAS_COMMIT: state <= LOAD_WEIGHT;
                LOAD_WEIGHT: if (take_input) begin
                    weights_q[(weight_word_index * 32) +: 32] <= s_axis_tdata;
                    if (s_axis_tlast != final_weight || s_axis_tkeep != 4'hf) begin
                        status_q <= 1;
                        cfg_error <= 1;
                        state <= s_axis_tlast ? RESPONSE_PREP : DRAIN;
                    end else if (weight_word_index == 3) begin
                        state <= WEIGHT_COMMIT;
                    end else weight_word_index <= weight_word_index + 1'b1;
                end
                WEIGHT_COMMIT: begin
                    if (tap_index + 1'b1 == taps_q) begin
                        loaded <= 1;
                        loaded_filter <= filter_q;
                        loaded_taps <= taps_q;
                        loaded_lanes <= lanes_q;
                        state <= RESPONSE_PREP;
                    end else begin
                        tap_index <= tap_index + 1'b1;
                        weight_word_index <= 0;
                        state <= LOAD_WEIGHT;
                    end
                end
                RUN_START: begin
                    response_words <= 13'd5 + response_payload_q;
                    state <= RUN_WORD;
                end
                RUN_WORD: if (take_input) begin
                    if (s_axis_tlast != final_word || s_axis_tkeep != 4'hf) begin
                        status_q <= 1;
                        cfg_error <= 1;
                        loaded <= 0;
                        state <= s_axis_tlast ? RESPONSE_PREP : DRAIN;
                    end else begin
                        word_buffer <= s_axis_tdata;
                        byte_index <= 0;
                        feed_bytes <= (taps_left >= 4) ? 4 : taps_left[2:0];
                        word_index <= word_index + 1'b1;
                        state <= RUN_FEED;
                    end
                end
                RUN_FEED: if (mac_act_ready) begin
                    taps_left <= taps_left - 1'b1;
                    if (byte_index + 1'b1 == feed_bytes) begin
                        if (taps_left == 1)
                            state <= RUN_WAIT;
                        else state <= RUN_WORD;
                    end else byte_index <= byte_index + 1'b1;
                end
                RUN_WAIT: if (mac_valid) begin
                    result_q <= mac_raw;
                    store_lane <= 0;
                    if (mac_error || (mac_overflow & ((16'h1 << lanes_q) - 1'b1)) != 0) begin
                        status_q <= 1;
                        cfg_error <= 1;
                        loaded <= 0;
                    end
                    state <= RUN_STORE;
                end
                RUN_STORE: begin
                    if (store_lane + 1'b1 == lanes_q) begin
                        if (site_index + 1'b1 == sites_q)
                            state <= RESPONSE_PREP;
                        else begin
                            site_index <= site_index + 1'b1;
                            taps_left <= taps_q;
                            word_index <= 0;
                            state <= RUN_START;
                        end
                    end else store_lane <= store_lane + 1'b1;
                end
                DRAIN: begin
                    if (opcode_q == 2)
                        response_words <= 13'd5 + response_payload_q;
                    if (take_input && s_axis_tlast) state <= RESPONSE_PREP;
                end
                RESPONSE_PREP: begin
                    state <= RESPONSE;
                end
                RESPONSE: if (take_output) begin
                    if (response_index + 1'b1 == response_words)
                        state <= IDLE;
                    else begin
                        response_index <= response_index + 1'b1;
                        state <= RESPONSE_PREP;
                        if (response_index >= 4 && opcode_q == 2) begin
                            if (response_lane + 1'b1 == lanes_q) begin
                                response_lane <= 0;
                                response_site <= response_site + 1'b1;
                            end else response_lane <= response_lane + 1'b1;
                        end
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
