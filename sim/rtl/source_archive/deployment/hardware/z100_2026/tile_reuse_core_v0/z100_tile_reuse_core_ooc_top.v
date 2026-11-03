// Registered boundary used only for honest standalone OOC timing closure.
// Each host-side field is sampled before it reaches the core. The board/DMA
// integration may add further registers and is intentionally not represented.
module z100_tile_reuse_core_ooc_top (
    input wire clk,
    input wire rst_n,
    input wire load_begin,
    output wire cfg_weight_ready,
    input wire cfg_weight_we,
    input wire [11:0] cfg_weight_addr,
    input wire [255:0] cfg_weights,
    output wire cfg_bias_ready,
    input wire cfg_bias_we,
    input wire [1023:0] cfg_biases,
    output wire act_cfg_ready,
    input wire act_cfg_we,
    input wire [11:0] act_cfg_addr,
    input wire [3:0] act_cfg_site_mask,
    input wire [31:0] act_cfg_data,
    input wire run_valid,
    output wire run_ready,
    input wire [12:0] run_tap_count,
    input wire [5:0] run_lane_count,
    input wire [2:0] run_site_count,
    input wire cancel,
    output wire out_valid,
    input wire out_ready,
    output wire [1:0] out_site,
    output wire out_last,
    output wire [5:0] out_lane_count,
    output wire [1023:0] out_data,
    output wire [31:0] out_overflow,
    output wire busy,
    output wire error
);
    reg rst_n_q = 1'b0;
    reg load_begin_q = 0;
    reg cfg_weight_we_q = 0;
    reg [11:0] cfg_weight_addr_q = 0;
    reg [255:0] cfg_weights_q = 0;
    reg cfg_bias_we_q = 0;
    reg [1023:0] cfg_biases_q = 0;
    reg act_cfg_we_q = 0;
    reg [11:0] act_cfg_addr_q = 0;
    reg [3:0] act_cfg_site_mask_q = 0;
    reg [31:0] act_cfg_data_q = 0;
    reg run_valid_q = 0;
    reg [12:0] run_tap_count_q = 0;
    reg [5:0] run_lane_count_q = 0;
    reg [2:0] run_site_count_q = 0;
    reg cancel_q = 0;
    reg out_ready_q = 0;

    always @(posedge clk) begin
        rst_n_q <= rst_n;
        load_begin_q <= load_begin;
        cfg_weight_we_q <= cfg_weight_we;
        cfg_weight_addr_q <= cfg_weight_addr;
        cfg_weights_q <= cfg_weights;
        cfg_bias_we_q <= cfg_bias_we;
        cfg_biases_q <= cfg_biases;
        act_cfg_we_q <= act_cfg_we;
        act_cfg_addr_q <= act_cfg_addr;
        act_cfg_site_mask_q <= act_cfg_site_mask;
        act_cfg_data_q <= act_cfg_data;
        run_valid_q <= run_valid;
        run_tap_count_q <= run_tap_count;
        run_lane_count_q <= run_lane_count;
        run_site_count_q <= run_site_count;
        cancel_q <= cancel;
        out_ready_q <= out_ready;
    end

    z100_tile_reuse_core #(.MAX_TAPS(4091)) core (
        .clk(clk), .rst_n(rst_n_q),
        .load_begin(load_begin_q),
        .cfg_weight_ready(cfg_weight_ready),
        .cfg_weight_we(cfg_weight_we_q), .cfg_weight_addr(cfg_weight_addr_q), .cfg_weights(cfg_weights_q),
        .cfg_bias_ready(cfg_bias_ready), .cfg_bias_we(cfg_bias_we_q), .cfg_biases(cfg_biases_q),
        .act_cfg_ready(act_cfg_ready), .act_cfg_we(act_cfg_we_q), .act_cfg_addr(act_cfg_addr_q),
        .act_cfg_site_mask(act_cfg_site_mask_q), .act_cfg_data(act_cfg_data_q),
        .run_valid(run_valid_q), .run_ready(run_ready), .run_tap_count(run_tap_count_q),
        .run_lane_count(run_lane_count_q), .run_site_count(run_site_count_q), .cancel(cancel_q),
        .out_valid(out_valid), .out_ready(out_ready_q), .out_site(out_site), .out_last(out_last),
        .out_lane_count(out_lane_count), .out_data(out_data), .out_overflow(out_overflow),
        .busy(busy), .error(error)
    );
endmodule
