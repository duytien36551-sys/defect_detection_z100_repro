// Isolated 32-output x 4-tap x 4-site INT8 reuse core.
//
// This is a private architecture prototype. It has no tile64 wire-ABI
// compatibility claim and is not connected to the production accelerator.
// Four tap banks provide the four concurrent tap operands; every tap weight
// is reused across four independently buffered spatial sites. One bank set is
// used at a time (there is no second/preload buffer).
module z100_tile_reuse_core #(
    parameter integer MAX_TAPS = 4091,
    parameter integer BANK_DEPTH = (MAX_TAPS + 3) / 4
) (
    input wire clk,
    input wire rst_n,

    // Start a fresh, single-buffer preload epoch while idle. This invalidates
    // all load counts without clearing the RAM contents; unloaded RAM words
    // therefore cannot be consumed by a later job.
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
    output reg [1:0] out_site,
    output wire out_last,
    output reg [5:0] out_lane_count,
    output reg [1023:0] out_data,
    output reg [31:0] out_overflow,
    output wire busy,
    output reg error
);
    localparam [1:0] ST_IDLE = 2'd0;
    localparam [1:0] ST_COMPUTE = 2'd1;
    localparam [1:0] ST_FLUSH = 2'd2;
    localparam [1:0] ST_DRAIN = 2'd3;

    reg [1:0] state;
    reg [12:0] weight_loaded_count;
    reg [12:0] activation_loaded_count [0:3];
    reg bias_loaded;
    reg [12:0] active_taps;
    reg [5:0] active_lanes;
    reg [2:0] active_sites;
    reg [10:0] groups_remaining;
    reg [10:0] group_index;
    reg [1:0] drain_site;

    // Each tap residue is a private simple-dual-port RAM. The activation
    // bytes are split by site so each RAM has one fixed-width write port; the
    // packer below presents the four registered site reads to the multiplier
    // array. RAM contents are intentionally not reset or cleared.
    // The validated MAX_TAPS=4091 contract uses at most 1023 groups, so every
    // accepted group index fits in this 10-bit RAM address.
    localparam integer BANK_RAM_DEPTH =
        (1 << $clog2((BANK_DEPTH < 2) ? 2 : BANK_DEPTH));
    localparam integer BANK_RAM_ADDR_WIDTH = $clog2(BANK_RAM_DEPTH);
    wire [255:0] weight_read_q [0:3];
    wire [7:0] activation_read_site [0:15];
    wire [31:0] activation_read_q [0:3];

    reg signed [31:0] bias_bank [0:31];
    reg signed [32:0] accumulator [0:3][0:31];
    reg [31:0] result_mem [0:3][0:31];
    reg result_overflow_mem [0:3][0:31];

    reg p0_valid, p0_last;
    reg p1_valid, p1_last;
    reg p2_valid, p2_last;
    reg [3:0] p0_tap_mask;
    reg [3:0] p1_tap_mask;
    reg [2:0] p0_sites, p1_sites;
    reg [5:0] p0_lanes, p1_lanes;

    reg signed [15:0] product_q [0:3][0:31][0:3];
    reg signed [18:0] group_sum_q [0:3][0:31];
    wire signed [15:0] product_value [0:3][0:31][0:3];
    wire signed [18:0] group_sum_value [0:3][0:31];
    wire signed [32:0] final_acc_value [0:3][0:31];

    integer i;
    integer j;
    integer k;
    integer mem_site;
    integer output_lane;

    function [31:0] clamp_signed33;
        input signed [32:0] value;
        begin
            if (value[32] != value[31])
                clamp_signed33 = value[32] ? 32'h80000000 : 32'h7fffffff;
            else
                clamp_signed33 = value[31:0];
        end
    endfunction

    assign busy = (state != ST_IDLE);
    assign run_ready = (state == ST_IDLE) && !load_begin && !cancel;
    assign cfg_weight_ready = (state == ST_IDLE) && !load_begin && !cancel;
    assign cfg_bias_ready = (state == ST_IDLE) && !load_begin && !cancel;
    assign act_cfg_ready = (state == ST_IDLE) && !load_begin && !cancel;
    assign out_valid = (state == ST_DRAIN);
    assign out_last = (drain_site + 1'b1) == active_sites;

    genvar gs, gl, gb;
    generate
        for (gs = 0; gs < 4; gs = gs + 1) begin : gen_site
            for (gl = 0; gl < 32; gl = gl + 1) begin : gen_lane
                for (gb = 0; gb < 4; gb = gb + 1) begin : gen_tap
                    assign product_value[gs][gl][gb] =
                        $signed(activation_read_q[gb][(gs * 8) +: 8]) *
                        $signed(weight_read_q[gb][(gl * 8) +: 8]);
                end
                assign group_sum_value[gs][gl] =
                    {{3{product_q[gs][gl][0][15]}}, product_q[gs][gl][0]} +
                    {{3{product_q[gs][gl][1][15]}}, product_q[gs][gl][1]} +
                    {{3{product_q[gs][gl][2][15]}}, product_q[gs][gl][2]} +
                    {{3{product_q[gs][gl][3][15]}}, product_q[gs][gl][3]};
                assign final_acc_value[gs][gl] = accumulator[gs][gl] +
                    {{14{group_sum_q[gs][gl][18]}}, group_sum_q[gs][gl]};
            end
        end
    endgenerate

    assign activation_read_q[0] = {
        activation_read_site[3], activation_read_site[2],
        activation_read_site[1], activation_read_site[0]};
    assign activation_read_q[1] = {
        activation_read_site[7], activation_read_site[6],
        activation_read_site[5], activation_read_site[4]};
    assign activation_read_q[2] = {
        activation_read_site[11], activation_read_site[10],
        activation_read_site[9], activation_read_site[8]};
    assign activation_read_q[3] = {
        activation_read_site[15], activation_read_site[14],
        activation_read_site[13], activation_read_site[12]};

    always @* begin
        for (output_lane = 0; output_lane < 32; output_lane = output_lane + 1) begin
            out_data[(output_lane * 32) +: 32] = result_mem[drain_site][output_lane];
            out_overflow[output_lane] = result_overflow_mem[drain_site][output_lane];
        end
    end

    wire issue_group = (state == ST_COMPUTE);
    wire [12:0] issue_base = {group_index, 2'b00};
    wire act_cfg_order_ok =
        (!act_cfg_site_mask[0] || (act_cfg_addr == activation_loaded_count[0])) &&
        (!act_cfg_site_mask[1] || (act_cfg_addr == activation_loaded_count[1])) &&
        (!act_cfg_site_mask[2] || (act_cfg_addr == activation_loaded_count[2])) &&
        (!act_cfg_site_mask[3] || (act_cfg_addr == activation_loaded_count[3]));

    genvar bank, site;
    generate
        for (bank = 0; bank < 4; bank = bank + 1) begin : gen_weight_bank
            wire wr_en = cfg_weight_we && cfg_weight_ready &&
                (cfg_weight_addr < MAX_TAPS) &&
                (cfg_weight_addr == weight_loaded_count) &&
                (cfg_weight_addr[1:0] == bank);
            wire rd_en = issue_group &&
                ((issue_base + bank) < active_taps);
            z100_sync_sdp_ram #(
                .DATA_WIDTH(256), .ADDR_WIDTH(BANK_RAM_ADDR_WIDTH),
                .DEPTH(BANK_RAM_DEPTH)
            ) ram (
                .clk(clk), .we(wr_en), .waddr(cfg_weight_addr[11:2]),
                .din(cfg_weights), .re(rd_en),
                .raddr(group_index[BANK_RAM_ADDR_WIDTH-1:0]),
                .dout(weight_read_q[bank])
            );
        end
        for (bank = 0; bank < 4; bank = bank + 1) begin : gen_activation_bank
            for (site = 0; site < 4; site = site + 1) begin : gen_activation_site
                wire wr_en = act_cfg_we && act_cfg_ready &&
                    (act_cfg_addr < MAX_TAPS) && act_cfg_order_ok &&
                    act_cfg_site_mask[site] &&
                    (act_cfg_addr == activation_loaded_count[site]) &&
                    (act_cfg_addr[1:0] == bank);
                wire rd_en = issue_group && (site < active_sites) &&
                    ((issue_base + bank) < active_taps);
                z100_sync_sdp_ram #(
                    .DATA_WIDTH(8), .ADDR_WIDTH(BANK_RAM_ADDR_WIDTH),
                    .DEPTH(BANK_RAM_DEPTH)
                ) ram (
                    .clk(clk), .we(wr_en), .waddr(act_cfg_addr[11:2]),
                    .din(act_cfg_data[(site * 8) +: 8]), .re(rd_en),
                    .raddr(group_index[BANK_RAM_ADDR_WIDTH-1:0]),
                    .dout(activation_read_site[(bank * 4) + site])
                );
            end
        end
    endgenerate

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            weight_loaded_count <= 0;
            bias_loaded <= 0;
            active_taps <= 0;
            active_lanes <= 0;
            active_sites <= 0;
            groups_remaining <= 0;
            group_index <= 0;
            drain_site <= 0;
            out_site <= 0;
            out_lane_count <= 0;
            p0_valid <= 0;
            p0_last <= 0;
            p1_valid <= 0;
            p1_last <= 0;
            p2_valid <= 0;
            p2_last <= 0;
            p0_tap_mask <= 0;
            p1_tap_mask <= 0;
            p0_sites <= 0;
            p1_sites <= 0;
            p0_lanes <= 0;
            p1_lanes <= 0;
            error <= 0;
            for (i = 0; i < 4; i = i + 1) begin
                activation_loaded_count[i] <= 0;
                for (j = 0; j < 32; j = j + 1) begin
                    accumulator[i][j] <= 0;
                    result_mem[i][j] <= 0;
                    result_overflow_mem[i][j] <= 0;
                    group_sum_q[i][j] <= 0;
                    for (k = 0; k < 4; k = k + 1)
                        product_q[i][j][k] <= 0;
                end
            end
            for (i = 0; i < 32; i = i + 1)
                bias_bank[i] <= 0;
        end else begin
            error <= 0;

            // Valid bits always advance, including bubbles during pipeline
            // drain, so cancel/reset can discard every in-flight operation.
            p0_valid <= issue_group;
            p1_valid <= p0_valid;
            p2_valid <= p1_valid;
            if (issue_group) begin
                p0_last <= (groups_remaining == 1);
                p0_tap_mask[0] <= (issue_base + 0) < active_taps;
                p0_tap_mask[1] <= (issue_base + 1) < active_taps;
                p0_tap_mask[2] <= (issue_base + 2) < active_taps;
                p0_tap_mask[3] <= (issue_base + 3) < active_taps;
                p0_sites <= active_sites;
                p0_lanes <= active_lanes;
            end
            if (p0_valid) begin
                p1_last <= p0_last;
                p1_tap_mask <= p0_tap_mask;
                p1_sites <= p0_sites;
                p1_lanes <= p0_lanes;
            end
            if (p1_valid)
                p2_last <= p1_last;

            if (p0_valid) begin
                for (i = 0; i < 4; i = i + 1) begin
                    for (j = 0; j < 32; j = j + 1) begin
                        for (k = 0; k < 4; k = k + 1) begin
                            if ((i < p0_sites) && (j < p0_lanes) && p0_tap_mask[k])
                                product_q[i][j][k] <= product_value[i][j][k];
                            else
                                product_q[i][j][k] <= 0;
                        end
                    end
                end
            end

            if (p1_valid) begin
                for (i = 0; i < 4; i = i + 1)
                    for (j = 0; j < 32; j = j + 1)
                        group_sum_q[i][j] <= group_sum_value[i][j];
            end

            if (p2_valid) begin
                for (i = 0; i < 4; i = i + 1) begin
                    for (j = 0; j < 32; j = j + 1) begin
                        if ((i < active_sites) && (j < active_lanes)) begin
                            accumulator[i][j] <= final_acc_value[i][j];
                            if (p2_last) begin
                                result_mem[i][j] <= clamp_signed33(final_acc_value[i][j]);
                                result_overflow_mem[i][j] <=
                                    final_acc_value[i][j][32] ^ final_acc_value[i][j][31];
                            end
                        end else if (p2_last) begin
                            result_mem[i][j] <= 0;
                            result_overflow_mem[i][j] <= 0;
                        end
                    end
                end
            end

            if (cancel) begin
                state <= ST_IDLE;
                weight_loaded_count <= 0;
                bias_loaded <= 0;
                groups_remaining <= 0;
                group_index <= 0;
                p0_valid <= 0;
                p0_last <= 0;
                p1_valid <= 0;
                p1_last <= 0;
                p2_valid <= 0;
                p2_last <= 0;
                p0_tap_mask <= 0;
                p1_tap_mask <= 0;
                for (i = 0; i < 4; i = i + 1) begin
                    activation_loaded_count[i] <= 0;
                    for (j = 0; j < 32; j = j + 1) begin
                        accumulator[i][j] <= 0;
                        result_mem[i][j] <= 0;
                        result_overflow_mem[i][j] <= 0;
                        for (k = 0; k < 4; k = k + 1)
                            product_q[i][j][k] <= 0;
                    end
                end
            end else if (load_begin && (state == ST_IDLE)) begin
                weight_loaded_count <= 0;
                bias_loaded <= 0;
                p0_valid <= 0;
                p1_valid <= 0;
                p2_valid <= 0;
                for (i = 0; i < 4; i = i + 1) begin
                    activation_loaded_count[i] <= 0;
                    for (j = 0; j < 32; j = j + 1) begin
                        result_mem[i][j] <= 0;
                        result_overflow_mem[i][j] <= 0;
                    end
                end
            end else begin
                if (cfg_weight_we && cfg_weight_ready) begin
                    if ((cfg_weight_addr >= MAX_TAPS) ||
                        (cfg_weight_addr != weight_loaded_count)) begin
                        error <= 1;
                    end else begin
                        weight_loaded_count <= weight_loaded_count + 1'b1;
                    end
                end

                if (cfg_bias_we && cfg_bias_ready)
                    for (i = 0; i < 32; i = i + 1)
                        bias_bank[i] <= cfg_biases[(i * 32) +: 32];
                if (cfg_bias_we && cfg_bias_ready)
                    bias_loaded <= 1;

                if (act_cfg_we && act_cfg_ready) begin
                    if ((act_cfg_addr >= MAX_TAPS) ||
                        (act_cfg_site_mask == 0) || !act_cfg_order_ok) begin
                        error <= 1;
                    end else begin
                        for (i = 0; i < 4; i = i + 1) begin
                            if (act_cfg_site_mask[i]) begin
                                activation_loaded_count[i] <= activation_loaded_count[i] + 1'b1;
                            end
                        end
                    end
                end

                if (run_valid && run_ready) begin
                    if ((run_tap_count == 0) || (run_tap_count > MAX_TAPS) ||
                        (run_lane_count == 0) || (run_lane_count > 32) ||
                        (run_site_count == 0) || (run_site_count > 4) ||
                        !bias_loaded || (weight_loaded_count < run_tap_count)) begin
                        error <= 1;
                    end else begin
                        for (i = 0; i < 4; i = i + 1) begin
                            if ((i < run_site_count) &&
                                (activation_loaded_count[i] < run_tap_count))
                                error <= 1;
                        end
                        if ((activation_loaded_count[0] >= run_tap_count) &&
                            ((run_site_count < 2) || (activation_loaded_count[1] >= run_tap_count)) &&
                            ((run_site_count < 3) || (activation_loaded_count[2] >= run_tap_count)) &&
                            ((run_site_count < 4) || (activation_loaded_count[3] >= run_tap_count)) &&
                            bias_loaded && (weight_loaded_count >= run_tap_count) &&
                            (run_tap_count != 0) && (run_tap_count <= MAX_TAPS) &&
                            (run_lane_count != 0) && (run_lane_count <= 32) &&
                            (run_site_count != 0) && (run_site_count <= 4)) begin
                            active_taps <= run_tap_count;
                            active_lanes <= run_lane_count;
                            active_sites <= run_site_count;
                            groups_remaining <= (run_tap_count + 3) >> 2;
                            group_index <= 0;
                            drain_site <= 0;
                            out_site <= 0;
                            out_lane_count <= run_lane_count;
                            p0_valid <= 0;
                            p1_valid <= 0;
                            p2_valid <= 0;
                            p0_last <= 0;
                            p1_last <= 0;
                            p2_last <= 0;
                            for (i = 0; i < 4; i = i + 1) begin
                                for (j = 0; j < 32; j = j + 1) begin
                                    if ((i < run_site_count) && (j < run_lane_count))
                                        accumulator[i][j] <= {{1{bias_bank[j][31]}}, bias_bank[j]};
                                    else
                                        accumulator[i][j] <= 0;
                                end
                            end
                            state <= ST_COMPUTE;
                        end else begin
                            error <= 1;
                        end
                    end
                end

                if (issue_group) begin
                    group_index <= group_index + 1'b1;
                    groups_remaining <= groups_remaining - 1'b1;
                    if (groups_remaining == 1)
                        state <= ST_FLUSH;
                end

                if ((state == ST_FLUSH) && p2_valid && p2_last) begin
                    state <= ST_DRAIN;
                    drain_site <= 0;
                    out_site <= 0;
                end

                if ((state == ST_DRAIN) && out_ready) begin
                    if (drain_site + 1'b1 >= active_sites) begin
                        state <= ST_IDLE;
                    end else begin
                        drain_site <= drain_site + 1'b1;
                        out_site <= drain_site + 1'b1;
                    end
                end
            end
        end
    end

    // Keep explicit readback outputs combinationally tied to the stable result
    // buffer. A stalled site therefore cannot be overwritten by another job.
endmodule

// Fixed-width single-write/synchronous-read template used by each private
// bank. The wrapper/core state guarantees that writes only happen during
// preload and reads only happen for valid compute taps; unloaded entries are
// never read. This is a genuine simple-dual-port template, not a forced
// register-array substitute.
module z100_sync_sdp_ram #(
    parameter integer DATA_WIDTH = 8,
    parameter integer ADDR_WIDTH = 10,
    parameter integer DEPTH = 1024
) (
    input wire clk,
    input wire we,
    input wire [ADDR_WIDTH-1:0] waddr,
    input wire [DATA_WIDTH-1:0] din,
    input wire re,
    input wire [ADDR_WIDTH-1:0] raddr,
    output reg [DATA_WIDTH-1:0] dout
);
    (* ram_style = "block" *) reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    always @(posedge clk) begin
        if (we)
            mem[waddr] <= din;
        if (re)
            dout <= mem[raddr];
    end
endmodule
