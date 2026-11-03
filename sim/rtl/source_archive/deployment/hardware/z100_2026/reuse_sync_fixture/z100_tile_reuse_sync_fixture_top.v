// Closed synchronous timing fixture for the unchanged tile reuse core.
// Only the clock crosses the fixture boundary. Inputs to the core are
// registered internally and its result is consumed by a registered signature.
// This is a timing experiment, not a production handshake bridge.
module z100_tile_reuse_sync_fixture_top (
    input wire clk,
    output reg [31:0] signature = 32'h00000000
);
    wire core_clk;
    BUFG clock_buffer (.I(clk), .O(core_clk));

    localparam [2:0] ST_RESET = 3'd0;
    localparam [2:0] ST_BEGIN = 3'd1;
    localparam [2:0] ST_LOAD = 3'd2;
    localparam [2:0] ST_RUN = 3'd3;
    localparam [2:0] ST_WAIT = 3'd4;
    localparam [2:0] ST_DRAIN = 3'd5;

    reg [2:0] controller_state = ST_RESET;
    reg [2:0] reset_cycles = 0;
    reg [31:0] lfsr = 32'h6d2b79f5;
    reg [1:0] ready_phase = 0;

    reg rst_n_q = 1'b0;
    reg load_begin_q = 1'b0;
    reg cfg_weight_we_q = 1'b0;
    reg [11:0] cfg_weight_addr_q = 12'd0;
    reg [255:0] cfg_weights_q = 256'd0;
    reg cfg_bias_we_q = 1'b0;
    reg [1023:0] cfg_biases_q = 1024'd0;
    reg act_cfg_we_q = 1'b0;
    reg [11:0] act_cfg_addr_q = 12'd0;
    reg [3:0] act_cfg_site_mask_q = 4'd0;
    reg [31:0] act_cfg_data_q = 32'd0;
    reg run_valid_q = 1'b0;
    reg [12:0] run_tap_count_q = 13'd1;
    reg [5:0] run_lane_count_q = 6'd32;
    reg [2:0] run_site_count_q = 3'd4;
    reg cancel_q = 1'b0;
    reg out_ready_q = 1'b0;

    wire cfg_weight_ready;
    wire cfg_bias_ready;
    wire act_cfg_ready;
    wire run_ready;
    wire out_valid;
    wire [1:0] out_site;
    wire out_last;
    wire [5:0] out_lane_count;
    wire [1023:0] out_data;
    wire [31:0] out_overflow;
    wire busy;
    wire error;

    integer lane;
    integer site;

    // One valid tap per job is enough to exercise the complete arithmetic,
    // BRAM read, accumulation, and output capture paths. Pseudorandom data
    // changes on every preload so the signature remains observable.
    always @(posedge core_clk) begin
        lfsr <= {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};

        load_begin_q <= 1'b0;
        cfg_weight_we_q <= 1'b0;
        cfg_bias_we_q <= 1'b0;
        act_cfg_we_q <= 1'b0;
        run_valid_q <= 1'b0;
        cancel_q <= 1'b0;
        out_ready_q <= 1'b0;

        if (reset_cycles < 3) begin
            reset_cycles <= reset_cycles + 1'b1;
            rst_n_q <= 1'b0;
            controller_state <= ST_RESET;
        end else begin
            rst_n_q <= 1'b1;
            case (controller_state)
                ST_RESET: begin
                    controller_state <= ST_BEGIN;
                end
                ST_BEGIN: begin
                    load_begin_q <= 1'b1;
                    controller_state <= ST_LOAD;
                end
                ST_LOAD: begin
                    cfg_weight_we_q <= 1'b1;
                    cfg_weight_addr_q <= 12'd0;
                    cfg_bias_we_q <= 1'b1;
                    act_cfg_we_q <= 1'b1;
                    act_cfg_addr_q <= 12'd0;
                    act_cfg_site_mask_q <= 4'b1111;
                    for (lane = 0; lane < 32; lane = lane + 1) begin
                        cfg_weights_q[(lane * 8) +: 8] <=
                            lfsr[(lane % 4) * 8 +: 8] ^ (lane * 8'h13);
                        cfg_biases_q[(lane * 32) +: 32] <=
                            lfsr ^ (32'h9e3779b9 * (lane + 1));
                    end
                    for (site = 0; site < 4; site = site + 1)
                        act_cfg_data_q[(site * 8) +: 8] <=
                            lfsr[(site % 4) * 8 +: 8] ^ (site * 8'h2d);
                    controller_state <= ST_RUN;
                end
                ST_RUN: begin
                    run_valid_q <= 1'b1;
                    controller_state <= ST_WAIT;
                end
                ST_WAIT: begin
                    if (run_ready)
                        controller_state <= ST_DRAIN;
                end
                ST_DRAIN: begin
                    // Exercise a changing ready signal while preserving the
                    // core's held-output contract under backpressure.
                    ready_phase <= ready_phase + 1'b1;
                    out_ready_q <= ready_phase[1];
                    if (out_valid && out_ready_q) begin
                        signature <= {signature[26:0], signature[31:27]} ^
                                     out_data[31:0] ^ out_data[1023:992] ^
                                     out_overflow ^ {26'd0, out_site, out_last,
                                                     out_lane_count[2:0]};
                        if (out_last) begin
                            controller_state <= ST_BEGIN;
                        end
                    end
                end
                default: controller_state <= ST_RESET;
            endcase
        end
    end

    (* DONT_TOUCH = "yes" *) z100_tile_reuse_core #(.MAX_TAPS(4091)) core (
        .clk(core_clk), .rst_n(rst_n_q),
        .load_begin(load_begin_q),
        .cfg_weight_ready(cfg_weight_ready),
        .cfg_weight_we(cfg_weight_we_q), .cfg_weight_addr(cfg_weight_addr_q),
        .cfg_weights(cfg_weights_q),
        .cfg_bias_ready(cfg_bias_ready), .cfg_bias_we(cfg_bias_we_q),
        .cfg_biases(cfg_biases_q),
        .act_cfg_ready(act_cfg_ready), .act_cfg_we(act_cfg_we_q),
        .act_cfg_addr(act_cfg_addr_q), .act_cfg_site_mask(act_cfg_site_mask_q),
        .act_cfg_data(act_cfg_data_q),
        .run_valid(run_valid_q), .run_ready(run_ready),
        .run_tap_count(run_tap_count_q), .run_lane_count(run_lane_count_q),
        .run_site_count(run_site_count_q), .cancel(cancel_q),
        .out_valid(out_valid), .out_ready(out_ready_q), .out_site(out_site),
        .out_last(out_last), .out_lane_count(out_lane_count),
        .out_data(out_data), .out_overflow(out_overflow),
        .busy(busy), .error(error)
    );
endmodule
