// Isolated v3 arithmetic datapath: free-running operands; reset/cancel qualify validity.
//
// This is a private architecture prototype. It has no tile64 wire-ABI
// compatibility claim and is not connected to the production accelerator.
// Four tap banks provide the four concurrent tap operands; every tap weight
// is reused across four independently buffered spatial sites. One bank set is
// used at a time (there is no second/preload buffer).
module z100_tile_reuse_datapath_v3 #(
    parameter integer MAX_TAPS = 4091,
    parameter integer BANK_DEPTH = (MAX_TAPS + 3) / 4
) (
    input wire clk,
    input wire rst_n,

    // Start a fresh, single-buffer preload epoch while idle. This invalidates
    // all load counts without clearing the RAM contents; unloaded RAM words
    // therefore cannot be consumed by a later job.
    input wire weight_begin,
    input wire activation_begin,
    output wire cfg_weight_ready,
    input wire cfg_weight_we,
    input wire [11:0] cfg_weight_addr,
    input wire [1023:0] cfg_weight_banked,
    output wire cfg_bias_ready,
    input wire cfg_bias_we,
    input wire [1023:0] cfg_biases,
    output wire act_cfg_ready,
    input wire act_cfg_we,
    input wire [11:0] act_cfg_addr,
    input wire [3:0] act_cfg_site_mask,
    input wire [127:0] act_cfg_banked,

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
    reg p3_valid, p3_last;
    (* keep = "true" *) reg [255:0] weight_operand_q [0:3];
    (* keep = "true" *) reg [31:0] activation_operand_q [0:3];
    reg [3:0] p0_tap_mask;
    reg [3:0] p1_tap_mask;
    reg [2:0] p0_sites, p1_sites;
    reg [5:0] p0_lanes, p1_lanes;

    (* use_dsp = "yes" *) reg signed [15:0] product_q [0:3][0:31][0:3];
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
    assign run_ready = (state == ST_IDLE) && !weight_begin &&
                       !activation_begin && !cancel;
    assign cfg_weight_ready = (state == ST_IDLE) && !weight_begin &&
                              !activation_begin && !cancel;
    assign cfg_bias_ready = (state == ST_IDLE) && !weight_begin &&
                            !activation_begin && !cancel;
    assign act_cfg_ready = (state == ST_IDLE) && !weight_begin &&
                           !activation_begin && !cancel;
    assign out_valid = (state == ST_DRAIN);
    assign out_last = (drain_site + 1'b1) == active_sites;

    genvar gs, gl, gb;
    generate
        for (gs = 0; gs < 4; gs = gs + 1) begin : gen_site
            for (gl = 0; gl < 32; gl = gl + 1) begin : gen_lane
                for (gb = 0; gb < 4; gb = gb + 1) begin : gen_tap
                    assign product_value[gs][gl][gb] =
                        $signed(activation_operand_q[gb][(gs * 8) +: 8]) *
                        $signed(weight_operand_q[gb][(gl * 8) +: 8]);
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
                .din(cfg_weight_banked[(bank * 256) +: 256]), .re(rd_en),
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
                    .din(act_cfg_banked[((bank * 4 + site) * 8) +: 8]), .re(rd_en),
                    .raddr(group_index[BANK_RAM_ADDR_WIDTH-1:0]),
                    .dout(activation_read_site[(bank * 4) + site])
                );
            end
        end
    endgenerate

    // Data can update while invalid. This removes an unnecessary reset/CE
    // path from1152 operand bits; validity still cancels every pipeline stage.
    integer operand_bank;
    always @(posedge clk) begin
        for (operand_bank=0;operand_bank<4;operand_bank=operand_bank+1) begin
            weight_operand_q[operand_bank] <= weight_read_q[operand_bank];
            activation_operand_q[operand_bank] <= activation_read_q[operand_bank];
        end
    end

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
                p3_valid <= 0;
            p2_last <= 0;
                p3_last <= 0;
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
            p3_valid <= p2_valid;
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
            if (p2_valid) p3_last <= p2_last;

            if (p1_valid) begin
                for (i = 0; i < 4; i = i + 1) begin
                    for (j = 0; j < 32; j = j + 1) begin
                        for (k = 0; k < 4; k = k + 1) begin
                            if ((i < p1_sites) && (j < p1_lanes) && p1_tap_mask[k])
                                product_q[i][j][k] <= product_value[i][j][k];
                            else
                                product_q[i][j][k] <= 0;
                        end
                    end
                end
            end

            if (p2_valid) begin
                for (i = 0; i < 4; i = i + 1)
                    for (j = 0; j < 32; j = j + 1)
                        group_sum_q[i][j] <= group_sum_value[i][j];
            end

            if (p3_valid) begin
                for (i = 0; i < 4; i = i + 1) begin
                    for (j = 0; j < 32; j = j + 1) begin
                        if ((i < active_sites) && (j < active_lanes)) begin
                            accumulator[i][j] <= final_acc_value[i][j];
                            if (p3_last) begin
                                result_mem[i][j] <= clamp_signed33(final_acc_value[i][j]);
                                result_overflow_mem[i][j] <=
                                    final_acc_value[i][j][32] ^ final_acc_value[i][j][31];
                            end
                        end else if (p3_last) begin
                            result_mem[i][j] <= 0;
                            result_overflow_mem[i][j] <= 0;
                        end
                    end
                end
            end

            if (cancel) begin
                state <= ST_IDLE;
                groups_remaining <= 0;
                group_index <= 0;
                p0_valid <= 0;
                p0_last <= 0;
                p1_valid <= 0;
                p1_last <= 0;
                p2_valid <= 0;
                p3_valid <= 0;
                p2_last <= 0;
                p3_last <= 0;
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
            end else if ((weight_begin || activation_begin) && (state == ST_IDLE)) begin
                if (weight_begin) begin
                    weight_loaded_count <= 0;
                    bias_loaded <= 0;
                end
                p0_valid <= 0;
                p1_valid <= 0;
                p2_valid <= 0;
                p3_valid <= 0;
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
                p3_valid <= 0;
                            p0_last <= 0;
                            p1_last <= 0;
                            p2_last <= 0;
                p3_last <= 0;
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

                if ((state == ST_FLUSH) && p3_valid && p3_last) begin
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
// Private command schema. Payload interpretation is opcode-specific:
// WEIGHT_DATA uses payload[255:0], BIAS_DATA uses payload[1023:0], and
// ACTIVATION_DATA uses payload[31:0] as four signed activation bytes.
module z100_tile_reuse_resident_v3 #(
    parameter integer MAX_TAPS = 4091
) (
    input wire clk,
    input wire rst_n,

    input wire cmd_valid,
    output wire cmd_ready,
    input wire [31:0] cmd_schema,
    input wire [3:0] cmd_opcode,
    input wire [31:0] cmd_weight_epoch,
    input wire [31:0] cmd_activation_epoch,
    input wire [11:0] cmd_addr,
    input wire [12:0] cmd_tap_count,
    input wire [5:0] cmd_lane_count,
    input wire [2:0] cmd_site_count,
    input wire [3:0] cmd_site_mask,
    input wire [1023:0] cmd_payload,

    output wire [31:0] schema_id,
    output reg error_valid,
    output reg [3:0] error_code,
    output reg weight_valid,
    output reg activation_valid,
    output reg [31:0] active_weight_epoch,
    output reg [31:0] active_activation_epoch,
    output wire busy,

    output wire out_valid,
    input wire out_ready,
    output wire [1:0] out_site,
    output wire out_last,
    output wire [5:0] out_lane_count,
    output wire [1023:0] out_data,
    output wire [31:0] out_overflow
);
    localparam [31:0] PRIVATE_SCHEMA = 32'h5a523301; // "ZR3", schema 1
    localparam [3:0] OP_WEIGHT_BEGIN  = 4'd1;
    localparam [3:0] OP_WEIGHT_DATA   = 4'd2;
    localparam [3:0] OP_BIAS_DATA     = 4'd3;
    localparam [3:0] OP_WEIGHT_COMMIT = 4'd4;
    localparam [3:0] OP_ACT_BEGIN     = 4'd5;
    localparam [3:0] OP_ACT_DATA      = 4'd6;
    localparam [3:0] OP_ACT_COMMIT    = 4'd7;
    localparam [3:0] OP_RUN           = 4'd8;
    localparam [3:0] OP_CANCEL        = 4'd9;

    localparam [1:0] LOAD_IDLE = 2'd0;
    localparam [1:0] LOAD_WEIGHTS = 2'd1;
    localparam [1:0] LOAD_ACTIVATIONS = 2'd2;

    localparam [3:0] ERR_SCHEMA = 4'd1;
    localparam [3:0] ERR_OPCODE = 4'd2;
    localparam [3:0] ERR_STATE = 4'd3;
    localparam [3:0] ERR_EPOCH = 4'd4;
    localparam [3:0] ERR_ADDRESS = 4'd5;
    localparam [3:0] ERR_SHAPE = 4'd6;
    localparam [3:0] ERR_INCOMPLETE = 4'd7;
    localparam [3:0] ERR_EPOCH_ORDER = 4'd8;

    reg [1:0] load_state;
    reg [31:0] last_weight_epoch;
    reg [31:0] last_activation_epoch;
    reg [12:0] expected_weight_taps;
    reg [12:0] weight_word_count;
    reg weight_bias_seen;
    reg [12:0] expected_activation_taps;
    reg [2:0] expected_activation_sites;
    reg [12:0] activation_word_count [0:3];
    reg run_inflight;

    reg stage_valid;
    reg [3:0] stage_opcode;
    reg [31:0] stage_weight_epoch;
    reg [31:0] stage_activation_epoch;
    reg [11:0] stage_addr;
    reg [12:0] stage_tap_count;
    reg [5:0] stage_lane_count;
    reg [2:0] stage_site_count;
    reg [3:0] stage_site_mask;

    // Each write staging register belongs to one memory bank. The 256-bit
    // weight bus and each activation byte settle locally before the RAM port.
    reg [255:0] stage_weight_bank [0:3];
    reg [7:0] stage_activation_bank [0:15];
    reg [1023:0] stage_bias_payload;

    wire [1023:0] dp_weight_banked = {
        stage_weight_bank[3], stage_weight_bank[2],
        stage_weight_bank[1], stage_weight_bank[0]
    };
    wire [127:0] dp_activation_banked = {
        stage_activation_bank[15], stage_activation_bank[14],
        stage_activation_bank[13], stage_activation_bank[12],
        stage_activation_bank[11], stage_activation_bank[10],
        stage_activation_bank[9], stage_activation_bank[8],
        stage_activation_bank[7], stage_activation_bank[6],
        stage_activation_bank[5], stage_activation_bank[4],
        stage_activation_bank[3], stage_activation_bank[2],
        stage_activation_bank[1], stage_activation_bank[0]
    };

    wire dp_weight_begin = stage_valid && (stage_opcode == OP_WEIGHT_BEGIN);
    wire dp_activation_begin = stage_valid && (stage_opcode == OP_ACT_BEGIN);
    wire dp_weight_we = stage_valid && (stage_opcode == OP_WEIGHT_DATA);
    wire dp_bias_we = stage_valid && (stage_opcode == OP_BIAS_DATA);
    wire dp_activation_we = stage_valid && (stage_opcode == OP_ACT_DATA);
    wire dp_run_valid = stage_valid && (stage_opcode == OP_RUN);
    wire dp_cancel = stage_valid && (stage_opcode == OP_CANCEL);

    wire dp_weight_ready;
    wire dp_bias_ready;
    wire dp_activation_ready;
    wire dp_run_ready;
    wire dp_out_valid;
    wire [1:0] dp_out_site;
    wire dp_out_last;
    wire [5:0] dp_out_lane_count;
    wire [1023:0] dp_out_data;
    wire [31:0] dp_out_overflow;
    wire dp_busy;
    wire dp_error;

    wire stage_can_advance = !stage_valid ||
        ((stage_opcode == OP_WEIGHT_BEGIN) && !dp_busy) ||
        ((stage_opcode == OP_ACT_BEGIN) && !dp_busy) ||
        ((stage_opcode == OP_WEIGHT_DATA) && dp_weight_ready) ||
        ((stage_opcode == OP_BIAS_DATA) && dp_bias_ready) ||
        ((stage_opcode == OP_ACT_DATA) && dp_activation_ready) ||
        ((stage_opcode == OP_RUN) && dp_run_ready) ||
        (stage_opcode == OP_CANCEL);
    assign cmd_ready = rst_n && (!stage_valid ||
        (stage_can_advance && (stage_opcode != OP_CANCEL)));
    assign schema_id = PRIVATE_SCHEMA;
    assign out_valid = dp_out_valid && !dp_cancel;
    assign out_site = dp_out_site;
    assign out_last = dp_out_last;
    assign out_lane_count = dp_out_lane_count;
    assign out_data = dp_out_data;
    assign out_overflow = dp_out_overflow;
    assign busy = dp_busy || run_inflight || stage_valid ||
                  (load_state != LOAD_IDLE);

    z100_tile_reuse_datapath_v3 #(.MAX_TAPS(MAX_TAPS)) datapath (
        .clk(clk), .rst_n(rst_n),
        .weight_begin(dp_weight_begin), .activation_begin(dp_activation_begin),
        .cfg_weight_ready(dp_weight_ready), .cfg_weight_we(dp_weight_we),
        .cfg_weight_addr(stage_addr), .cfg_weight_banked(dp_weight_banked),
        .cfg_bias_ready(dp_bias_ready), .cfg_bias_we(dp_bias_we),
        .cfg_biases(stage_bias_payload),
        .act_cfg_ready(dp_activation_ready), .act_cfg_we(dp_activation_we),
        .act_cfg_addr(stage_addr), .act_cfg_site_mask(stage_site_mask),
        .act_cfg_banked(dp_activation_banked),
        .run_valid(dp_run_valid), .run_ready(dp_run_ready),
        .run_tap_count(stage_tap_count), .run_lane_count(stage_lane_count),
        .run_site_count(stage_site_count), .cancel(dp_cancel),
        .out_valid(dp_out_valid), .out_ready(out_ready && !dp_cancel),
        .out_site(dp_out_site), .out_last(dp_out_last),
        .out_lane_count(dp_out_lane_count), .out_data(dp_out_data),
        .out_overflow(dp_out_overflow), .busy(dp_busy), .error(dp_error)
    );

    reg act_addr_order_ok;
    reg act_commit_complete;
    reg [3:0] activation_site_mask;
    integer index;
    always @* begin
        act_addr_order_ok = 1'b1;
        act_commit_complete = 1'b1;
        activation_site_mask = (1 << expected_activation_sites) - 1'b1;
        for (index = 0; index < 4; index = index + 1) begin
            if (cmd_site_mask[index] && (cmd_addr != activation_word_count[index]))
                act_addr_order_ok = 1'b0;
            if ((index < expected_activation_sites) &&
                (activation_word_count[index] != expected_activation_taps))
                act_commit_complete = 1'b0;
        end
    end

    integer bank_index;
    integer site_index;
    integer selected_bank;
    always @(posedge clk) begin
        if (!rst_n) begin
            load_state <= LOAD_IDLE;
            last_weight_epoch <= 0;
            last_activation_epoch <= 0;
            expected_weight_taps <= 0;
            weight_word_count <= 0;
            weight_bias_seen <= 0;
            expected_activation_taps <= 0;
            expected_activation_sites <= 0;
            weight_valid <= 0;
            activation_valid <= 0;
            active_weight_epoch <= 0;
            active_activation_epoch <= 0;
            run_inflight <= 0;
            stage_valid <= 0;
            stage_opcode <= 0;
            stage_weight_epoch <= 0;
            stage_activation_epoch <= 0;
            stage_addr <= 0;
            stage_tap_count <= 0;
            stage_lane_count <= 0;
            stage_site_count <= 0;
            stage_site_mask <= 0;
            stage_bias_payload <= 0;
            error_valid <= 0;
            error_code <= 0;
            for (bank_index = 0; bank_index < 4; bank_index = bank_index + 1)
                activation_word_count[bank_index] <= 0;
        end else begin
            error_valid <= 0;

            if (stage_valid && stage_can_advance)
                stage_valid <= 0;

            if (stage_valid && (stage_opcode == OP_CANCEL)) begin
                stage_valid <= 0;
                stage_opcode <= 0;
            end

            if (cmd_valid && cmd_ready) begin
                if (cmd_schema != PRIVATE_SCHEMA) begin
                    error_valid <= 1;
                    error_code <= ERR_SCHEMA;
                end else begin
                    case (cmd_opcode)
                        OP_WEIGHT_BEGIN: begin
                            if ((load_state != LOAD_IDLE) || run_inflight || dp_busy) begin
                                error_valid <= 1; error_code <= ERR_STATE;
                            end else if ((cmd_tap_count == 0) ||
                                         (cmd_tap_count > MAX_TAPS)) begin
                                error_valid <= 1; error_code <= ERR_SHAPE;
                            end else if ((cmd_weight_epoch == 0) ||
                                         (cmd_weight_epoch <= last_weight_epoch)) begin
                                error_valid <= 1; error_code <= ERR_EPOCH_ORDER;
                            end else begin
                                load_state <= LOAD_WEIGHTS;
                                last_weight_epoch <= cmd_weight_epoch;
                                active_weight_epoch <= cmd_weight_epoch;
                                expected_weight_taps <= cmd_tap_count;
                                weight_word_count <= 0;
                                weight_bias_seen <= 0;
                                weight_valid <= 0;
                                activation_valid <= 0;
                                stage_valid <= 1;
                                stage_opcode <= OP_WEIGHT_BEGIN;
                                stage_weight_epoch <= cmd_weight_epoch;
                            end
                        end
                        OP_WEIGHT_DATA: begin
                            if (load_state != LOAD_WEIGHTS) begin
                                error_valid <= 1; error_code <= ERR_STATE;
                            end else if (cmd_weight_epoch != active_weight_epoch) begin
                                error_valid <= 1; error_code <= ERR_EPOCH;
                            end else if ((cmd_addr >= expected_weight_taps) ||
                                         (cmd_addr != weight_word_count)) begin
                                error_valid <= 1; error_code <= ERR_ADDRESS;
                            end else begin
                                weight_word_count <= weight_word_count + 1'b1;
                                stage_valid <= 1;
                                stage_opcode <= OP_WEIGHT_DATA;
                                stage_weight_epoch <= cmd_weight_epoch;
                                stage_addr <= cmd_addr;
                                selected_bank = cmd_addr[1:0];
                                stage_weight_bank[selected_bank] <= cmd_payload[255:0];
                            end
                        end
                        OP_BIAS_DATA: begin
                            if (load_state != LOAD_WEIGHTS) begin
                                error_valid <= 1; error_code <= ERR_STATE;
                            end else if (cmd_weight_epoch != active_weight_epoch) begin
                                error_valid <= 1; error_code <= ERR_EPOCH;
                            end else if (weight_bias_seen) begin
                                error_valid <= 1; error_code <= ERR_ADDRESS;
                            end else begin
                                weight_bias_seen <= 1;
                                stage_valid <= 1;
                                stage_opcode <= OP_BIAS_DATA;
                                stage_weight_epoch <= cmd_weight_epoch;
                                stage_bias_payload <= cmd_payload;
                            end
                        end
                        OP_WEIGHT_COMMIT: begin
                            if (load_state != LOAD_WEIGHTS) begin
                                error_valid <= 1; error_code <= ERR_STATE;
                            end else if (cmd_weight_epoch != active_weight_epoch) begin
                                error_valid <= 1; error_code <= ERR_EPOCH;
                            end else if ((weight_word_count != expected_weight_taps) ||
                                         !weight_bias_seen) begin
                                error_valid <= 1; error_code <= ERR_INCOMPLETE;
                            end else begin
                                load_state <= LOAD_IDLE;
                                weight_valid <= 1;
                            end
                        end
                        OP_ACT_BEGIN: begin
                            if ((load_state != LOAD_IDLE) || run_inflight || dp_busy) begin
                                error_valid <= 1; error_code <= ERR_STATE;
                            end else if (!weight_valid) begin
                                error_valid <= 1; error_code <= ERR_INCOMPLETE;
                            end else if (cmd_weight_epoch != active_weight_epoch) begin
                                error_valid <= 1; error_code <= ERR_EPOCH;
                            end else if ((cmd_activation_epoch == 0) ||
                                         (cmd_activation_epoch <= last_activation_epoch)) begin
                                error_valid <= 1; error_code <= ERR_EPOCH_ORDER;
                            end else if ((cmd_tap_count != expected_weight_taps) ||
                                         (cmd_site_count == 0) ||
                                         (cmd_site_count > 4)) begin
                                error_valid <= 1; error_code <= ERR_SHAPE;
                            end else begin
                                load_state <= LOAD_ACTIVATIONS;
                                last_activation_epoch <= cmd_activation_epoch;
                                active_activation_epoch <= cmd_activation_epoch;
                                expected_activation_taps <= cmd_tap_count;
                                expected_activation_sites <= cmd_site_count;
                                activation_valid <= 0;
                                for (bank_index = 0; bank_index < 4; bank_index = bank_index + 1)
                                    activation_word_count[bank_index] <= 0;
                                stage_valid <= 1;
                                stage_opcode <= OP_ACT_BEGIN;
                                stage_weight_epoch <= cmd_weight_epoch;
                                stage_activation_epoch <= cmd_activation_epoch;
                            end
                        end
                        OP_ACT_DATA: begin
                            if (load_state != LOAD_ACTIVATIONS) begin
                                error_valid <= 1; error_code <= ERR_STATE;
                            end else if ((cmd_activation_epoch != active_activation_epoch) ||
                                         (cmd_weight_epoch != active_weight_epoch)) begin
                                error_valid <= 1; error_code <= ERR_EPOCH;
                            end else if ((cmd_addr >= expected_activation_taps) ||
                                         (cmd_site_mask == 0) ||
                                         ((cmd_site_mask & ~activation_site_mask) != 0) ||
                                         !act_addr_order_ok) begin
                                error_valid <= 1; error_code <= ERR_ADDRESS;
                            end else begin
                                for (bank_index = 0; bank_index < 4; bank_index = bank_index + 1)
                                    if (cmd_site_mask[bank_index])
                                        activation_word_count[bank_index] <=
                                            activation_word_count[bank_index] + 1'b1;
                                stage_valid <= 1;
                                stage_opcode <= OP_ACT_DATA;
                                stage_weight_epoch <= cmd_weight_epoch;
                                stage_activation_epoch <= cmd_activation_epoch;
                                stage_addr <= cmd_addr;
                                stage_site_mask <= cmd_site_mask;
                                for (bank_index = 0; bank_index < 4; bank_index = bank_index + 1)
                                    for (site_index = 0; site_index < 4; site_index = site_index + 1)
                                        if (cmd_site_mask[site_index] &&
                                            (cmd_addr[1:0] == bank_index))
                                            stage_activation_bank[(bank_index * 4) + site_index] <=
                                                cmd_payload[(site_index * 8) +: 8];
                            end
                        end
                        OP_ACT_COMMIT: begin
                            if (load_state != LOAD_ACTIVATIONS) begin
                                error_valid <= 1; error_code <= ERR_STATE;
                            end else if ((cmd_weight_epoch != active_weight_epoch) ||
                                         (cmd_activation_epoch != active_activation_epoch)) begin
                                error_valid <= 1; error_code <= ERR_EPOCH;
                            end else if (!act_commit_complete) begin
                                error_valid <= 1; error_code <= ERR_INCOMPLETE;
                            end else begin
                                load_state <= LOAD_IDLE;
                                activation_valid <= 1;
                            end
                        end
                        OP_RUN: begin
                            if ((load_state != LOAD_IDLE) || run_inflight || dp_busy) begin
                                error_valid <= 1; error_code <= ERR_STATE;
                            end else if (!weight_valid || !activation_valid) begin
                                error_valid <= 1; error_code <= ERR_INCOMPLETE;
                            end else if ((cmd_weight_epoch != active_weight_epoch) ||
                                         (cmd_activation_epoch != active_activation_epoch)) begin
                                error_valid <= 1; error_code <= ERR_EPOCH;
                            end else if ((cmd_tap_count != expected_weight_taps) ||
                                         (cmd_tap_count != expected_activation_taps) ||
                                         (cmd_lane_count == 0) ||
                                         (cmd_lane_count > 32) ||
                                         (cmd_site_count != expected_activation_sites)) begin
                                error_valid <= 1; error_code <= ERR_SHAPE;
                            end else begin
                                run_inflight <= 1;
                                stage_valid <= 1;
                                stage_opcode <= OP_RUN;
                                stage_weight_epoch <= cmd_weight_epoch;
                                stage_activation_epoch <= cmd_activation_epoch;
                                stage_tap_count <= cmd_tap_count;
                                stage_lane_count <= cmd_lane_count;
                                stage_site_count <= cmd_site_count;
                            end
                        end
                        OP_CANCEL: begin
                            if (load_state == LOAD_WEIGHTS) begin
                                weight_valid <= 0;
                                activation_valid <= 0;
                            end else begin
                                activation_valid <= 0;
                            end
                            load_state <= LOAD_IDLE;
                            run_inflight <= 0;
                            stage_valid <= 1;
                            stage_opcode <= OP_CANCEL;
                        end
                        default: begin
                            error_valid <= 1; error_code <= ERR_OPCODE;
                        end
                    endcase
                end
            end

            if (out_valid && out_ready && out_last)
                run_inflight <= 0;
        end
    end
endmodule

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
