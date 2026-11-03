`default_nettype none

// Private exact INT32 -> INT8 search tree with eight independently loaded contexts.
// Each synchronous block RAM stores only the midpoint nodes reachable at its depth.
module z100_requant_context (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    cancel,

    input  wire                    cfg_begin,
    input  wire [2:0]              cfg_context,
    output wire                    cfg_begin_ready,
    input  wire                    cfg_word_valid,
    output wire                    cfg_word_ready,
    input  wire signed [32:0]      cfg_key,
    input  wire                    cfg_commit,
    output wire                    cfg_commit_ready,
    output reg                     cfg_error,

    input  wire                    in_valid,
    output wire                    in_ready,
    input  wire [2:0]              in_context,
    input  wire signed [31:0]      in_data,
    output wire                    out_valid,
    input  wire                    out_ready,
    output wire [2:0]              out_context,
    output wire signed [7:0]       out_data
);
    localparam signed [32:0] KEY_MIN = -33'sd2147483648;
    localparam signed [32:0] KEY_MAX =  33'sd2147483648;

    reg [7:0] context_valid;
    reg loading;
    reg [2:0] target_context;
    reg [8:0] cfg_count;
    reg signed [32:0] previous_key;

    reg [7:0] valid_q;
    reg [2:0] context_q [0:7];
    reg [6:0] node_q [0:7];
    reg signed [31:0] raw_q [0:7];
    wire signed [32:0] key_q [0:7];
    wire [7:0] next_node [0:7];
    wire [7:0] branch;
    wire [7:0] stage_ready;
    wire [9:0] read_address [0:7];

    reg [2:0] cfg_bank;
    reg [7:0] cfg_node;
    reg [8:0] cfg_index_plus_one;
    reg [8:0] cfg_odd;
    reg found_zero;
    integer bit_index;

    wire [9:0] cfg_address = ({7'b0, target_context} << cfg_bank) | {2'b0, cfg_node};
    wire pipe_empty = ~(|valid_q);
    wire control_busy = cfg_begin || cfg_word_valid || cfg_commit;
    wire run_enabled = !loading && !control_busy && rst_n && !cancel;
    wire cfg_accept_word = cfg_word_valid && cfg_word_ready;
    wire cfg_word_good = (cfg_count < 9'd255) &&
                         (cfg_key >= KEY_MIN) && (cfg_key <= KEY_MAX) &&
                         ((cfg_count == 0) || (cfg_key >= previous_key)) &&
                         ((cfg_count != 9'd254) || (cfg_key == KEY_MAX));

    always @* begin
        // Index 127 has seven trailing ones and therefore selects stage 0.
        cfg_bank = 3'd0;
        found_zero = 1'b0;
        for (bit_index = 0; bit_index < 7; bit_index = bit_index + 1) begin
            if (!found_zero && !cfg_count[bit_index]) begin
                cfg_bank = 3'd7 - bit_index;
                found_zero = 1'b1;
            end
        end
        cfg_index_plus_one = {1'b0, cfg_count[7:0]} + 9'd1;
        cfg_odd = cfg_index_plus_one >> (3'd7 - cfg_bank);
        cfg_node = (cfg_odd - 9'd1) >> 1;
    end

    assign cfg_begin_ready = pipe_empty && !loading && !cfg_word_valid && !cfg_commit && rst_n && !cancel;
    assign cfg_word_ready = pipe_empty && loading && !cfg_begin && !cfg_commit && rst_n && !cancel;
    assign cfg_commit_ready = pipe_empty && loading && !cfg_begin && !cfg_word_valid && rst_n && !cancel;

    assign stage_ready[7] = !valid_q[7] || out_ready;
    genvar s;
    generate
        for (s = 0; s < 7; s = s + 1) begin : gen_ready
            assign stage_ready[s] = !valid_q[s] || stage_ready[s+1];
        end
    endgenerate

    assign read_address[0] = {7'b0, in_context};
    generate
        for (s = 1; s < 8; s = s + 1) begin : gen_read_address
            assign read_address[s] = ({7'b0, context_q[s-1]} << s) | next_node[s-1];
        end
    endgenerate

    assign in_ready = run_enabled && stage_ready[0] && context_valid[in_context];
    assign out_valid = valid_q[7] && rst_n && !cancel;
    assign out_context = context_q[7];
    wire [7:0] final_rank = {node_q[7], branch[7]};
    wire signed [8:0] result_wide = $signed({1'b0, final_rank}) - 9'sd127;
    assign out_data = result_wide[7:0];

    generate
        for (s = 0; s < 8; s = s + 1) begin : gen_stage_memory
            localparam integer NODE_COUNT = (1 << s);
            localparam integer DEPTH = (8 << s);
            (* ram_style = "block" *) reg signed [32:0] tree_mem [0:DEPTH-1];
            reg signed [32:0] read_q;

            if (s == 0) begin : gen_stage0_read
                always @(posedge clk) begin
                    if (!rst_n || cancel)
                        read_q <= 33'sd0;
                    else if (in_valid && in_ready)
                        read_q <= tree_mem[read_address[s][s+2:0]];
                end
            end else begin : gen_later_stage_read
                always @(posedge clk) begin
                    if (!rst_n || cancel)
                        read_q <= 33'sd0;
                    else if (stage_ready[s] && valid_q[s-1])
                        read_q <= tree_mem[read_address[s][s+2:0]];
                end
            end

            always @(posedge clk) begin
                if (cfg_accept_word && cfg_word_good && cfg_bank == s)
                    tree_mem[cfg_address[s+2:0]] <= cfg_key;
            end

            assign key_q[s] = read_q;
            assign branch[s] = $signed({raw_q[s][31], raw_q[s]}) >= $signed(key_q[s]);
            assign next_node[s] = {node_q[s], branch[s]};
        end
    endgenerate

    integer p;
    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            context_valid <= 8'b0;
            loading <= 1'b0;
            target_context <= 3'b0;
            cfg_count <= 9'd0;
            previous_key <= KEY_MIN;
            cfg_error <= 1'b0;
            valid_q <= 8'b0;
            for (p = 0; p < 8; p = p + 1) begin
                context_q[p] <= 3'b0;
                node_q[p] <= 7'b0;
                raw_q[p] <= 32'sd0;
            end
        end else begin
            cfg_error <= 1'b0;

            if (cfg_begin && cfg_begin_ready) begin
                context_valid[cfg_context] <= 1'b0;
                target_context <= cfg_context;
                loading <= 1'b1;
                cfg_count <= 9'd0;
                previous_key <= KEY_MIN;
            end else if (cfg_accept_word) begin
                if (cfg_word_good) begin
                    previous_key <= cfg_key;
                    cfg_count <= cfg_count + 9'd1;
                end else begin
                    context_valid[target_context] <= 1'b0;
                    loading <= 1'b0;
                    cfg_count <= 9'd0;
                    previous_key <= KEY_MIN;
                    cfg_error <= 1'b1;
                end
            end else if (cfg_commit && cfg_commit_ready) begin
                if (cfg_count == 9'd255) begin
                    context_valid[target_context] <= 1'b1;
                    loading <= 1'b0;
                end else begin
                    context_valid[target_context] <= 1'b0;
                    loading <= 1'b0;
                    cfg_count <= 9'd0;
                    previous_key <= KEY_MIN;
                    cfg_error <= 1'b1;
                end
            end

            if (stage_ready[0]) begin
                valid_q[0] <= in_valid && in_ready;
                if (in_valid && in_ready) begin
                    context_q[0] <= in_context;
                    node_q[0] <= 7'd0;
                    raw_q[0] <= in_data;
                end
            end
            for (p = 1; p < 8; p = p + 1) begin
                if (stage_ready[p]) begin
                    valid_q[p] <= valid_q[p-1];
                    if (valid_q[p-1]) begin
                        context_q[p] <= context_q[p-1];
                        // The 8-bit child index always fits the next stage's
                        // low p bits; assignment truncates only leading zeroes.
                        node_q[p] <= next_node[p-1];
                        raw_q[p] <= raw_q[p-1];
                    end
                end
            end
        end
    end
endmodule

`default_nettype wire
