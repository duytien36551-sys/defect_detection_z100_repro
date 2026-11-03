// Private single-lane exact upper-bound requantizer.
// Eight synchronous replicated memories feed an eight-stage elastic search.
module z100_requant_pipeline_ram_wrapper (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    cancel,

    input  wire                    cfg_begin,
    output wire                    cfg_begin_ready,
    input  wire                    cfg_word_valid,
    output wire                    cfg_word_ready,
    input  wire signed [32:0]      cfg_key,
    input  wire                    cfg_commit,
    output wire                    cfg_commit_ready,
    output reg                     cfg_error,

    input  wire                    in_valid,
    output wire                    in_ready,
    input  wire signed [31:0]      in_data,
    output wire                    out_valid,
    input  wire                    out_ready,
    output wire signed [7:0]       out_data
);
    localparam signed [32:0] KEY_MIN = -33'sd2147483648;
    localparam signed [32:0] KEY_MAX =  33'sd2147483648;

    reg loading;
    reg loaded;
    reg [8:0] cfg_count;
    reg signed [32:0] previous_key;

    reg [8:0] low_q [0:7];
    reg [8:0] high_q [0:7];
    reg signed [31:0] raw_q [0:7];
    reg valid_q [0:7];
    wire signed [32:0] key_q [0:7];

    wire [8:0] next_low [0:7];
    wire [8:0] next_high [0:7];
    wire [8:0] midpoint [0:7];
    wire [7:0] stage_ready;
    wire pipe_empty;
    wire control_busy = cfg_begin || cfg_word_valid || cfg_commit;
    wire run_enabled = loaded && !loading && !control_busy && rst_n && !cancel;
    wire signed [32:0] raw_ext [0:7];
    wire [7:0] key_index [0:7];
    wire raw_below_key [0:7];

    assign pipe_empty = !(valid_q[0] | valid_q[1] | valid_q[2] | valid_q[3] |
                          valid_q[4] | valid_q[5] | valid_q[6] | valid_q[7]);

    assign cfg_begin_ready = pipe_empty && !loading && !cfg_word_valid && !cfg_commit && rst_n && !cancel;
    assign cfg_word_ready = pipe_empty && loading && !cfg_begin && !cfg_commit &&
                            (cfg_count < 9'd255) && rst_n && !cancel;
    assign cfg_commit_ready = pipe_empty && loading && !cfg_begin && !cfg_word_valid && rst_n && !cancel;

    assign stage_ready[7] = !valid_q[7] || out_ready;
    genvar s;
    generate
        for (s = 0; s < 7; s = s + 1) begin : gen_ready
            assign stage_ready[s] = !valid_q[s] || stage_ready[s+1];
        end
    endgenerate
    assign in_ready = run_enabled && stage_ready[0];
    assign out_valid = valid_q[7] && rst_n && !cancel;
    wire signed [9:0] result_wide = $signed({1'b0, next_low[7]}) - 10'sd127;
    assign out_data = result_wide[7:0];

    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : gen_search
            wire table_read_enable;
            wire [7:0] table_read_address;

            if (i == 0) begin : gen_first_address
                assign table_read_enable = in_valid && in_ready;
                assign table_read_address = 8'd127;
            end else begin : gen_next_address
                assign table_read_enable = stage_ready[i] && valid_q[i-1];
                assign table_read_address = key_index[i-1];
            end

            z100_requant_table_scalar u_table (
                .clk(clk), .rst_n(rst_n), .cancel(cancel),
                .cfg_we(cfg_word_valid && cfg_word_ready),
                .cfg_addr(cfg_count[7:0]), .cfg_data(cfg_key),
                .rd_en(table_read_enable), .rd_addr(table_read_address),
                .rd_data(key_q[i])
            );
        end
    endgenerate

    generate
        for (i = 0; i < 8; i = i + 1) begin : gen_decision
            assign midpoint[i] = (low_q[i] + high_q[i]) >> 1;
            assign raw_ext[i] = {raw_q[i][31], raw_q[i]};
            assign raw_below_key[i] = $signed(raw_ext[i]) < $signed(key_q[i]);
            assign next_low[i] = raw_below_key[i] ? low_q[i] : midpoint[i] + 9'd1;
            assign next_high[i] = raw_below_key[i] ? midpoint[i] : high_q[i];
            assign key_index[i] = (next_low[i] + next_high[i]) >> 1;
        end
    endgenerate

    integer p;
    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            loading <= 1'b0;
            loaded <= 1'b0;
            cfg_count <= 9'd0;
            previous_key <= KEY_MIN;
            cfg_error <= 1'b0;
            for (p = 0; p < 8; p = p + 1) begin
                low_q[p] <= 9'd0;
                high_q[p] <= 9'd0;
                raw_q[p] <= 32'sd0;
                valid_q[p] <= 1'b0;
            end
        end else begin
            cfg_error <= 1'b0;

            if (cfg_begin && cfg_begin_ready) begin
                loaded <= 1'b0;
                loading <= 1'b1;
                cfg_count <= 9'd0;
                previous_key <= KEY_MIN;
            end else if (cfg_word_valid && cfg_word_ready) begin
                if (cfg_key < KEY_MIN || cfg_key > KEY_MAX ||
                    (cfg_count != 0 && cfg_key < previous_key) ||
                    (cfg_count == 9'd254 && cfg_key != KEY_MAX)) begin
                    loaded <= 1'b0;
                    loading <= 1'b0;
                    cfg_count <= 9'd0;
                    cfg_error <= 1'b1;
                end else begin
                    previous_key <= cfg_key;
                    cfg_count <= cfg_count + 9'd1;
                end
            end else if (cfg_commit && cfg_commit_ready) begin
                if (cfg_count == 9'd255) begin
                    loaded <= 1'b1;
                    loading <= 1'b0;
                end else begin
                    loaded <= 1'b0;
                    loading <= 1'b0;
                    cfg_count <= 9'd0;
                    cfg_error <= 1'b1;
                end
            end

            if (stage_ready[0]) begin
                valid_q[0] <= in_valid && run_enabled;
                if (in_valid && run_enabled) begin
                    low_q[0] <= 9'd0;
                    high_q[0] <= 9'd255;
                    raw_q[0] <= in_data;
                end
            end
            for (p = 1; p < 8; p = p + 1) begin
                if (stage_ready[p]) begin
                    valid_q[p] <= valid_q[p-1];
                    if (valid_q[p-1]) begin
                        low_q[p] <= next_low[p-1];
                        high_q[p] <= next_high[p-1];
                        raw_q[p] <= raw_q[p-1];
                    end
                end
            end
        end
    end
endmodule


// A single independently owned synchronous table.  This wrapper is an
// isolated mapping experiment; its protocol and read timing match pipeline v1.
module z100_requant_table_scalar (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    cancel,
    input  wire                    cfg_we,
    input  wire [7:0]              cfg_addr,
    input  wire signed [32:0]      cfg_data,
    input  wire                    rd_en,
    input  wire [7:0]              rd_addr,
    output wire signed [32:0]      rd_data
);
    (* ram_style = "block" *) reg signed [32:0] tree_mem [0:254];
    reg signed [32:0] read_q;

    always @(posedge clk) begin
        if (!rst_n || cancel)
            read_q <= 33'sd0;
        else if (rd_en)
            read_q <= tree_mem[rd_addr];
    end

    always @(posedge clk) begin
        if (cfg_we)
            tree_mem[cfg_addr] <= cfg_data;
    end

    assign rd_data = read_q;
endmodule
