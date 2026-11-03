`default_nettype none
// Private partitioned-tree v2. Identical search/control/8-cycle ABI to v1.
// Each level stores only the complete binary tree nodes it can address.
// Stages0..6 use distributed RAM; stage7 uses block RAM. No payload reset.
// A model job owns 255 sorted signed33 keys per channel, including +2^31.
// All lanes use one shared elastic-valid chain; no cross-lane progress skew.
module z100_requant_vector (
    input wire clk, input wire rst_n, input wire cancel,
    input wire cfg_begin, output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch, input wire [5:0] cfg_lanes,
    input wire cfg_word_valid, output wire cfg_word_ready,
    input wire [1055:0] cfg_keys,
    input wire cfg_commit, output wire cfg_commit_ready,
    output reg cfg_error, output reg input_error,
    input wire in_valid, output wire in_ready,
    input wire [31:0] in_epoch, input wire [31:0] in_token,
    input wire [4:0] in_site, input wire in_last,
    input wire [1023:0] in_data,
    output wire out_valid, input wire out_ready,
    output wire [31:0] out_epoch, output wire [31:0] out_token,
    output wire [4:0] out_site, output wire [5:0] out_lanes,
    output wire out_last, output wire [255:0] out_data
);
    localparam signed [32:0] KEY_MIN = -33'sd2147483648;
    localparam signed [32:0] KEY_MAX = 33'sd2147483648;
    reg loading, loaded;
    reg [31:0] epoch;
    reg [5:0] lanes;
    reg [8:0] cfg_count;
    reg signed [32:0] previous [0:31];
    wire [31:0] key_good;
    wire control_busy = cfg_begin || cfg_word_valid || cfg_commit;
    reg [7:0] valid_q;
    wire [7:0] ready;
    reg [31:0] epoch_q [0:7], token_q [0:7];
    reg [4:0] site_q [0:7];
    reg last_q [0:7];
    wire empty = ~(|valid_q);
    wire enabled = loaded && !loading && !control_busy && rst_n && !cancel;
    wire bad_input = enabled && in_valid && (in_epoch != epoch || in_token == 0 || in_site >= 20);
    wire cfg_fire = cfg_word_valid && cfg_word_ready;
    wire valid_keys = (&key_good) && cfg_count < 255;
    assign cfg_begin_ready = empty && !loading && !cfg_word_valid && !cfg_commit && rst_n && !cancel;
    assign cfg_word_ready = empty && loading && !cfg_begin && !cfg_commit && rst_n && !cancel;
    assign cfg_commit_ready = empty && loading && !cfg_begin && !cfg_word_valid && rst_n && !cancel;
    assign ready[7] = !valid_q[7] || out_ready;
    assign in_ready = enabled && ready[0] && !bad_input;
    assign out_valid = valid_q[7] && rst_n && !cancel && !bad_input;
    assign out_epoch = epoch_q[7];
    assign out_token = token_q[7];
    assign out_site = site_q[7];
    assign out_last = last_q[7];
    assign out_lanes = lanes;

    genvar s, c;
    generate for (s=0;s<7;s=s+1) begin : gen_ready
        assign ready[s] = !valid_q[s] || ready[s+1];
    end endgenerate
    generate for (c=0;c<32;c=c+1) begin : gen_lane
        wire signed [32:0] config_key = cfg_keys[c*33 +: 33];
        assign key_good[c] = config_key >= KEY_MIN && config_key <= KEY_MAX &&
                             (cfg_count == 0 || config_key >= previous[c]) &&
                             (cfg_count != 254 || config_key == KEY_MAX);
        reg signed [31:0] raw_q [0:7];
        reg [8:0] low_q [0:7], high_q [0:7];
        wire [8:0] next_low [0:7], next_high [0:7], middle [0:7];
        wire [7:0] key_index [0:7];
        wire signed [32:0] key_q [0:7];
        for (s=0;s<8;s=s+1) begin : gen_search
            wire rd_enable;
            wire [7:0] rd_address;
            if (s == 0) begin : first
                assign rd_enable = in_valid && in_ready;
                assign rd_address = 8'd127;
            end else begin : later
                assign rd_enable = ready[s] && valid_q[s-1];
                assign rd_address = key_index[s-1];
            end
            z100_requant_partition_table #(.LEVEL(s)) table_inst(
                .clk(clk), .wr_en(cfg_fire && valid_keys),
                .wr_addr(cfg_count[7:0]), .wr_data(config_key),
                .rd_en(rd_enable), .rd_addr(rd_address), .rd_data(key_q[s]));
            wire signed [32:0] raw_extended = {raw_q[s][31],raw_q[s]};
            wire below = raw_extended < key_q[s];
            assign middle[s] = (low_q[s] + high_q[s]) >> 1;
            assign next_low[s] = below ? low_q[s] : middle[s] + 9'd1;
            assign next_high[s] = below ? middle[s] : high_q[s];
            assign key_index[s] = (next_low[s] + next_high[s]) >> 1;
        end
        wire signed [9:0] result_wide = $signed({1'b0,next_low[7]}) - 10'sd127;
        assign out_data[c*8 +: 8] = c < lanes ? result_wide[7:0] : 8'd0;
        integer p;
        always @(posedge clk) begin
            // Payload state is meaningful only under the shared valid chain.
            if (ready[0] && in_valid && in_ready) begin
                low_q[0] <= 0; high_q[0] <= 255;
                raw_q[0] <= in_data[c*32 +: 32];
            end
            for (p=1;p<8;p=p+1) begin
                if (ready[p] && valid_q[p-1]) begin
                    low_q[p] <= next_low[p-1]; high_q[p] <= next_high[p-1];
                    raw_q[p] <= raw_q[p-1];
                end
            end
        end
    end endgenerate

    integer i;
    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            loading<=0; loaded<=0; epoch<=0; lanes<=0; cfg_count<=0;
            cfg_error<=0; input_error<=0; valid_q<=0;
        end else begin
            cfg_error<=0; input_error<=0;
            if (cfg_begin && cfg_begin_ready) begin
                loaded<=0; cfg_count<=0;
                if (cfg_epoch == 0 || cfg_lanes == 0 || cfg_lanes > 32) begin
                    loading<=0; cfg_error<=1;
                end else begin
                    loading<=1; epoch<=cfg_epoch; lanes<=cfg_lanes;
                end
            end else if (cfg_fire) begin
                if (!valid_keys) begin
                    loading<=0; loaded<=0; cfg_error<=1; cfg_count<=0;
                end else begin
                    cfg_count<=cfg_count+9'd1;
                    for (i=0;i<32;i=i+1) previous[i]<=cfg_keys[i*33 +: 33];
                end
            end else if (cfg_commit && cfg_commit_ready) begin
                loading<=0;
                if (cfg_count == 255) loaded<=1;
                else begin loaded<=0; cfg_error<=1; end
            end
            if (bad_input) begin
                loaded<=0; loading<=0; input_error<=1; valid_q<=0;
            end else begin
                if (ready[0]) begin
                    valid_q[0]<=in_valid && in_ready;
                    if (in_valid && in_ready) begin
                        epoch_q[0]<=in_epoch; token_q[0]<=in_token;
                        site_q[0]<=in_site; last_q[0]<=in_last;
                    end
                end
                for (i=1;i<8;i=i+1) begin
                    if (ready[i]) begin
                        valid_q[i]<=valid_q[i-1];
                        if (valid_q[i-1]) begin
                            epoch_q[i]<=epoch_q[i-1]; token_q[i]<=token_q[i-1];
                            site_q[i]<=site_q[i-1]; last_q[i]<=last_q[i-1];
                        end
                    end
                end
            end
        end
    end
endmodule

module z100_requant_partition_table #(
    parameter integer LEVEL = 0
) (
    input wire clk, input wire wr_en, input wire [7:0] wr_addr,
    input wire signed [32:0] wr_data,
    input wire rd_en, input wire [7:0] rd_addr,
    output reg signed [32:0] rd_data
);
    // Level d addresses exactly (2*p+1)*2**(7-d)-1, p=0..2**d-1.
    // This partitions all255 ordered keys, including the +2**31 sentinel.
    // Mapping is constant per generated stage; no data-dependent division.
    localparam integer SHIFT = 8 - LEVEL;
    localparam integer MASK = (1 << SHIFT) - 1;
    localparam integer RESIDUE = (1 << (7-LEVEL)) - 1;
    localparam integer DEPTH = 1 << LEVEL;
    localparam integer ADDRESS_BITS = LEVEL > 0 ? LEVEL : 1;
    wire selected_write = wr_en && ((wr_addr & MASK) == RESIDUE);
    wire [ADDRESS_BITS-1:0] local_wr = wr_addr >> SHIFT;
    wire [ADDRESS_BITS-1:0] local_rd = rd_addr >> SHIFT;
    generate if (LEVEL < 7) begin : gen_distributed
        (* ram_style="distributed" *) reg signed [32:0] mem [0:DEPTH-1];
        always @(posedge clk) begin
            if (selected_write) mem[local_wr] <= wr_data;
            if (rd_en) rd_data <= mem[local_rd];
        end
    end else begin : gen_block
        (* ram_style="block" *) reg signed [32:0] mem [0:DEPTH-1];
        always @(posedge clk) begin
            if (selected_write) mem[local_wr] <= wr_data;
            if (rd_en) rd_data <= mem[local_rd];
        end
    end endgenerate
endmodule
`default_nettype wire
