// Closed, dynamically handshaken timing fixture for the unchanged v2 core.
// The core instance has no DONT_TOUCH attribute. Every result data bit is
// selected onto scan_word over a 32-lane observation sequence while the core
// keeps the complete site result valid and stable.
module z100_tile_reuse_handshake_fixture_top (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] load_seed,
    input  wire        request_valid,
    output wire        request_ready,
    input  wire [12:0] request_taps,
    input  wire [5:0]  request_lanes,
    input  wire [2:0]  request_sites,
    input  wire        cancel,
    input  wire        observe_ready,
    output wire        scan_valid,
    output wire [31:0] scan_word,
    output wire        scan_overflow,
    output wire [1:0]  scan_site,
    output reg  [4:0]  scan_lane,
    output wire [5:0]  scan_lane_count,
    output wire        scan_last,
    output wire        scan_job_done,
    output wire        protocol_error
);
    localparam integer MAX_TAPS = 4091;
    localparam [1:0] ST_BEGIN = 2'd0;
    localparam [1:0] ST_LOAD  = 2'd1;
    localparam [1:0] ST_READY = 2'd2;
    localparam [1:0] ST_RUN   = 2'd3;

    wire core_clk;
    BUFG clock_buffer (.I(clk), .O(core_clk));

    reg [1:0] state;
    reg [11:0] weight_addr;
    reg [11:0] activation_addr;
    reg bias_sent;
    reg [31:0] seed_q;
    reg scan_active;
    reg [31:0] weight_lfsr [0:31];
    reg [31:0] activation_lfsr [0:3];

    wire load_begin = (state == ST_BEGIN);
    wire cfg_weight_ready;
    wire cfg_bias_ready;
    wire act_cfg_ready;
    wire run_ready;
    wire core_out_valid;
    wire [1:0] core_out_site;
    wire core_out_last;
    wire [5:0] core_out_lane_count;
    wire [1023:0] core_out_data;
    wire [31:0] core_out_overflow;
    wire core_busy;
    wire core_error;
    wire cfg_weight_we = (state == ST_LOAD) && (weight_addr < MAX_TAPS);
    wire cfg_bias_we = (state == ST_LOAD) && !bias_sent;
    wire act_cfg_we = (state == ST_LOAD) && (activation_addr < MAX_TAPS);
    wire run_valid = request_valid && (state == ST_READY);
    wire core_out_ready = scan_valid && observe_ready && (scan_lane == 5'd31);

    reg [255:0] cfg_weights;
    reg [1023:0] cfg_biases;
    reg [31:0] act_cfg_data;
    integer lane;
    integer site;
    integer init_lane;
    integer init_site;
    integer advance_lane;

    function automatic [31:0] advance_lfsr;
        input [31:0] value;
        begin
            advance_lfsr = {value[30:0], value[31] ^ value[21] ^ value[1] ^ value[0]};
        end
    endfunction

    // Each lane and site has an independent 32-bit stream. State advances only
    // when the corresponding configuration write is accepted, preventing a
    // short-period address/sign pattern from making banks or multipliers
    // equivalent to synthesis. The seed remains an external timing input.
    always @* begin
        cfg_weights = 256'd0;
        cfg_biases = 1024'd0;
        act_cfg_data = 32'd0;
        for (lane = 0; lane < 32; lane = lane + 1) begin
            cfg_weights[(lane * 8) +: 8] = weight_lfsr[lane][7:0];
            cfg_biases[(lane * 32) +: 32] = seed_q + (lane * 256);
        end
        for (site = 0; site < 4; site = site + 1) begin
            act_cfg_data[(site * 8) +: 8] = activation_lfsr[site][7:0];
        end
    end

    assign request_ready = (state == ST_READY) && run_ready && !cancel && rst_n;
    assign scan_valid = scan_active && core_out_valid;
    assign scan_word = core_out_data[(scan_lane * 32) +: 32];
    assign scan_overflow = core_out_overflow[scan_lane];
    assign scan_site = core_out_site;
    assign scan_lane_count = core_out_lane_count;
    assign scan_last = core_out_last && (scan_lane == 5'd31);
    assign scan_job_done = scan_valid && observe_ready && scan_last;
    assign protocol_error = core_error;

    always @(posedge core_clk) begin
        if (!rst_n) begin
            state <= ST_BEGIN;
            weight_addr <= 12'd0;
            activation_addr <= 12'd0;
            bias_sent <= 1'b0;
            seed_q <= load_seed;
            scan_active <= 1'b0;
            scan_lane <= 5'd0;
            for (init_lane = 0; init_lane < 32; init_lane = init_lane + 1)
                weight_lfsr[init_lane] <= (load_seed ^ (32'h9e3779b9 * (init_lane + 1))) | 32'd1;
            for (init_site = 0; init_site < 4; init_site = init_site + 1)
                activation_lfsr[init_site] <= (load_seed ^ (32'h7f4a7c15 * (init_site + 1))) | 32'd1;
        end else if (cancel) begin
            state <= ST_BEGIN;
            weight_addr <= 12'd0;
            activation_addr <= 12'd0;
            bias_sent <= 1'b0;
            seed_q <= load_seed;
            scan_active <= 1'b0;
            scan_lane <= 5'd0;
            for (init_lane = 0; init_lane < 32; init_lane = init_lane + 1)
                weight_lfsr[init_lane] <= (load_seed ^ (32'h9e3779b9 * (init_lane + 1))) | 32'd1;
            for (init_site = 0; init_site < 4; init_site = init_site + 1)
                activation_lfsr[init_site] <= (load_seed ^ (32'h7f4a7c15 * (init_site + 1))) | 32'd1;
        end else begin
            case (state)
                ST_BEGIN: state <= ST_LOAD;
                ST_LOAD: begin
                    if (cfg_weight_we && cfg_weight_ready) begin
                        weight_addr <= weight_addr + 1'b1;
                        for (advance_lane = 0; advance_lane < 32; advance_lane = advance_lane + 1)
                            weight_lfsr[advance_lane] <= advance_lfsr(weight_lfsr[advance_lane]);
                    end
                    if (act_cfg_we && act_cfg_ready) begin
                        activation_addr <= activation_addr + 1'b1;
                        for (init_site = 0; init_site < 4; init_site = init_site + 1)
                            activation_lfsr[init_site] <= advance_lfsr(activation_lfsr[init_site]);
                    end
                    if (cfg_bias_we && cfg_bias_ready)
                        bias_sent <= 1'b1;
                    if ((weight_addr == MAX_TAPS) &&
                        (activation_addr == MAX_TAPS) && bias_sent)
                        state <= ST_READY;
                end
                ST_READY: begin
                    if (request_valid && request_ready)
                        state <= ST_RUN;
                end
                ST_RUN: begin
                    if (!core_busy && !core_out_valid && !scan_active)
                        state <= ST_READY;
                end
                default: state <= ST_BEGIN;
            endcase

            if (!scan_active && core_out_valid) begin
                scan_active <= 1'b1;
                scan_lane <= 5'd0;
            end else if (scan_active && core_out_valid && observe_ready) begin
                if (scan_lane == 5'd31) begin
                    scan_active <= 1'b0;
                    scan_lane <= 5'd0;
                end else begin
                    scan_lane <= scan_lane + 1'b1;
                end
            end
        end
    end

    // Deliberately no DONT_TOUCH/KEEP_HIERARCHY: netlist preservation must
    // follow from live request/data paths and externally scanned results.
    z100_tile_reuse_core #(.MAX_TAPS(MAX_TAPS)) core (
        .clk(core_clk), .rst_n(rst_n),
        .load_begin(load_begin),
        .cfg_weight_ready(cfg_weight_ready),
        .cfg_weight_we(cfg_weight_we), .cfg_weight_addr(weight_addr),
        .cfg_weights(cfg_weights),
        .cfg_bias_ready(cfg_bias_ready), .cfg_bias_we(cfg_bias_we),
        .cfg_biases(cfg_biases),
        .act_cfg_ready(act_cfg_ready), .act_cfg_we(act_cfg_we),
        .act_cfg_addr(activation_addr), .act_cfg_site_mask(4'b1111),
        .act_cfg_data(act_cfg_data),
        .run_valid(run_valid), .run_ready(run_ready),
        .run_tap_count(request_taps), .run_lane_count(request_lanes),
        .run_site_count(request_sites), .cancel(cancel),
        .out_valid(core_out_valid), .out_ready(core_out_ready),
        .out_site(core_out_site), .out_last(core_out_last),
        .out_lane_count(core_out_lane_count), .out_data(core_out_data),
        .out_overflow(core_out_overflow), .busy(core_busy), .error(core_error)
    );
endmodule
