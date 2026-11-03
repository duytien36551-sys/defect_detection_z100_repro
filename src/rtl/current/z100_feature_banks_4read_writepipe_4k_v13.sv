`default_nettype none

// Private four-read-port view of the frozen two-port addressed feature store.
// Two identical physical stores receive atomic writes; reads 0/1 come from
// copy_a and reads 2/3 come from copy_b. Payload RAM is never reset or cleared.
(* use_dsp = "no" *)
// timing_v13: combinational admission/ready/child-out-ready gates use only the
// registered mirror_fault_latched (one edge later than the raw compare); the
// raw mirror_mismatch still drives error_valid/error_code, store_valid and
// out_valid immediately. Children get read_hint (no global_read_bad / epoch /
// address compare) as their BRAM read strobe. Fault-free behavior is cycle-exact.
module z100_feature_banks_4read_writepipe_4k_v13 #(
    parameter integer ADDR_BITS = 13,
    parameter integer DEPTH = 4096
) (
    input  wire                       clk,
    input  wire                       rst_n,
    input  wire                       cancel,

    input  wire                       cfg_begin,
    output wire                       cfg_begin_ready,
    input  wire [31:0]                cfg_epoch,
    input wire cfg_canonical_order,
    input  wire [10:0]                cfg_channels,
    input  wire [9:0]                 cfg_height,
    input  wire [9:0]                 cfg_width,

    input  wire                       cfg_word_valid,
    output wire                       cfg_word_ready,
    input  wire [511:0]               cfg_word_data,
    input  wire [31:0]                cfg_word_epoch,
    input  wire [12:0]                cfg_word_address,
    input  wire                       cfg_word_last,
    input  wire                       cfg_commit,
    output wire                       cfg_commit_ready,

    output wire                       error_valid,
    output wire [3:0]                 error_code,
    output wire                       store_valid,
    output wire [31:0]                active_epoch,
    output wire                       loading,

    input  wire                       req_valid,
    output wire                       req_ready,
    input  wire [31:0]                req_epoch,
    input  wire [64*4*ADDR_BITS-1:0]  req_addresses,
    input  wire [255:0]               req_mask,
    output wire                       out_valid,
    input  wire                       out_ready,
    output wire [31:0]                out_epoch,
    output wire [2047:0]              out_data
);
    localparam [3:0] ERR_MIRROR_MISMATCH = 4'd8;
    localparam [3:0] ERR_BAD_READ = 4'd7;

    reg [13:0] pending_words;
    reg [13:0] active_words_q;
    reg local_badread_pulse;
    reg [31:0] cfg_group4_calc;
    reg [31:0] cfg_xwords_calc;
    reg [31:0] cfg_words_calc;
    reg cfg_geometry_ok;
    reg global_read_bad;
    integer read_check_port;

    wire cfg_begin_ready_a, cfg_begin_ready_b;
    wire cfg_word_ready_a, cfg_word_ready_b;
    wire cfg_commit_ready_a, cfg_commit_ready_b;
    wire req_ready_a, req_ready_b;
    // The addressed child suppresses each ready while another command class
    // is active. Keep those child gates acyclic if a caller presents two
    // command classes together: hold all of them until the inputs are exclusive.
    wire input_classes_exclusive = !(
        (cfg_begin && (cfg_word_valid || cfg_commit || req_valid)) ||
        (cfg_word_valid && (cfg_commit || req_valid)) ||
        (cfg_commit && req_valid));
    wire cfg_begin_fire_ready;
    wire cfg_word_fire_ready;
    wire cfg_commit_fire_ready;
    wire req_fire_ready;
    // Forward exclusive valid independently of ready. The frozen children
    // perform their own handshakes; mirror equality guarantees equal readiness
    // for the selected class. This removes cross-class ready->valid chains.
    wire command_admission;
    wire cfg_begin_i = cfg_begin && command_admission;
    wire cfg_word_valid_i = cfg_word_valid && command_admission;
    wire cfg_commit_i = cfg_commit && command_admission;
    wire req_valid_i = req_valid && command_admission && !global_read_bad;
    wire read_hint_i = req_valid && command_admission;
    wire bad_read_fire = req_valid && req_ready && global_read_bad;

    wire error_valid_a, error_valid_b;
    wire [2:0] error_code_a, error_code_b;
    wire store_valid_a, store_valid_b;
    wire [31:0] active_epoch_a, active_epoch_b;
    wire loading_a, loading_b;
    wire out_valid_a, out_valid_b;
    wire [31:0] out_epoch_a, out_epoch_b;
    wire [1023:0] out_data_a, out_data_b;
    wire [128*ADDR_BITS-1:0] req_addresses_a, req_addresses_b;
    wire [127:0] req_mask_a, req_mask_b;
    wire child_cancel;
    wire child_out_ready_a, child_out_ready_b;
    reg mirror_fault_latched;
    reg mirror_mismatch;
    assign command_admission = input_classes_exclusive && rst_n && !cancel &&
        !local_badread_pulse && !mirror_fault_latched;

    always @* begin
        cfg_group4_calc = ({21'b0, cfg_channels} + 32'd3) >> 2;
        cfg_xwords_calc = ({22'b0, cfg_width} + 32'd15) >> 4;
        cfg_words_calc = cfg_group4_calc * {22'b0, cfg_height} * cfg_xwords_calc;
        cfg_geometry_ok = (cfg_epoch != 0) && (cfg_channels != 0) &&
                          (cfg_channels <= 11'd1024) && (cfg_height != 0) &&
                          (cfg_height <= 10'd640) && (cfg_width != 0) &&
                          (cfg_width <= 10'd640) && (cfg_words_calc != 0) &&
                          (cfg_words_calc <= DEPTH) && (cfg_words_calc <= 32'd8192);
    end

    always @* begin
        global_read_bad = (req_epoch != active_epoch_a);
        for (read_check_port = 0; read_check_port < 256; read_check_port = read_check_port + 1) begin
            if (req_mask[read_check_port] &&
                ({1'b0, req_addresses[read_check_port*ADDR_BITS +: ADDR_BITS]} >= active_words_q))
                global_read_bad = 1'b1;
        end
    end

    assign cfg_begin_fire_ready = input_classes_exclusive && rst_n && !cancel && !local_badread_pulse &&
                                  !mirror_fault_latched &&
                                  cfg_begin_ready_a && cfg_begin_ready_b;
    assign cfg_word_fire_ready = input_classes_exclusive && rst_n && !cancel && !local_badread_pulse &&
                                 !mirror_fault_latched &&
                                 cfg_word_ready_a && cfg_word_ready_b;
    assign cfg_commit_fire_ready = input_classes_exclusive && rst_n && !cancel && !local_badread_pulse &&
                                   !mirror_fault_latched &&
                                   cfg_commit_ready_a && cfg_commit_ready_b;
    assign req_fire_ready = input_classes_exclusive && rst_n && !cancel && !local_badread_pulse &&
                            !mirror_fault_latched &&
                            req_ready_a && req_ready_b;
    assign cfg_begin_ready = cfg_begin_fire_ready;
    assign cfg_word_ready = cfg_word_fire_ready;
    assign cfg_commit_ready = cfg_commit_fire_ready;
    assign req_ready = req_fire_ready;

    // v13: admission/ready gates react to the latched fault (next edge);
    // public valid/error outputs still react to mirror_mismatch immediately.
    // Flush children from the registered sticky fault on the following edge;
    // this removes the epoch-compare -> cancel -> child-ready -> command-reset cone.
    assign child_cancel = cancel || local_badread_pulse || mirror_fault_latched;
    assign child_out_ready_a = out_ready && out_valid_b && rst_n && !cancel &&
                               !mirror_fault_latched;
    assign child_out_ready_b = out_ready && out_valid_a && rst_n && !cancel &&
                               !mirror_fault_latched;

    always @* begin
        mirror_mismatch = 1'b0;
        if (rst_n && !cancel &&
            ((loading_a != loading_b) || (store_valid_a != store_valid_b) ||
             (active_epoch_a != active_epoch_b) || (out_valid_a != out_valid_b) ||
             (error_valid_a != error_valid_b) ||
             (error_valid_a && (error_code_a != error_code_b)) ||
             (out_valid_a && out_valid_b && (out_epoch_a != out_epoch_b)))
        )
            mirror_mismatch = 1'b1;
    end

    always @(posedge clk) begin
        if (!rst_n || cancel)
            mirror_fault_latched <= 1'b0;
        else if (mirror_mismatch)
            mirror_fault_latched <= 1'b1;
    end

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            pending_words <= 14'b0;
            active_words_q <= 14'b0;
            local_badread_pulse <= 1'b0;
        end else begin
            local_badread_pulse <= 1'b0;
            if (cfg_begin_i && cfg_begin_ready) begin
                pending_words <= cfg_geometry_ok ? cfg_words_calc[13:0] : 14'b0;
                active_words_q <= 14'b0;
            end else if (cfg_commit_i && cfg_commit_ready) begin
                active_words_q <= pending_words;
            end else if (bad_read_fire) begin
                active_words_q <= 14'b0;
                local_badread_pulse <= 1'b1;
            end
        end
    end

    assign loading = loading_a || loading_b;
    // (b) store_valid drops the same-cycle mirror compare; a mirror fault
    // still raises error_valid immediately and clears store_valid next edge.
    assign store_valid = rst_n && !cancel && !local_badread_pulse && !mirror_fault_latched &&
                         store_valid_a && store_valid_b;
    assign active_epoch = store_valid ? active_epoch_a : 32'b0;
    assign out_valid = rst_n && !cancel && !local_badread_pulse && !mirror_fault_latched &&
                       !mirror_mismatch && out_valid_a && out_valid_b &&
                       (out_epoch_a == out_epoch_b);
    assign out_epoch = out_valid ? out_epoch_a : 32'b0;
    // (c) error_valid/error_code use only the latched mirror fault: a mirror
    // mismatch (hardware self-check, never true in fault-free operation) is
    // reported one edge later. out_valid still masks the mismatch cycle.
    // Removes out_epoch compare -> error_valid -> pool job_ready -> top
    // cfg_begin -> store cfg_begin_ready -> pending_feature_* CE (26 levels).
    assign error_valid = mirror_fault_latched || local_badread_pulse ||
                         error_valid_a || error_valid_b;
    assign error_code = mirror_fault_latched ? ERR_MIRROR_MISMATCH :
                        local_badread_pulse ? ERR_BAD_READ :
                        error_valid_a ? {1'b0, error_code_a} :
                        error_valid_b ? {1'b0, error_code_b} : 4'b0;

    genvar bank;
    generate for (bank = 0; bank < 64; bank = bank + 1) begin : gen_port_map
        assign req_addresses_a[(bank*2)*ADDR_BITS +: ADDR_BITS] =
            req_addresses[(bank*4)*ADDR_BITS +: ADDR_BITS];
        assign req_addresses_a[(bank*2+1)*ADDR_BITS +: ADDR_BITS] =
            req_addresses[(bank*4+1)*ADDR_BITS +: ADDR_BITS];
        assign req_addresses_b[(bank*2)*ADDR_BITS +: ADDR_BITS] =
            req_addresses[(bank*4+2)*ADDR_BITS +: ADDR_BITS];
        assign req_addresses_b[(bank*2+1)*ADDR_BITS +: ADDR_BITS] =
            req_addresses[(bank*4+3)*ADDR_BITS +: ADDR_BITS];
        assign req_mask_a[bank*2] = req_mask[bank*4];
        assign req_mask_a[bank*2+1] = req_mask[bank*4+1];
        assign req_mask_b[bank*2] = req_mask[bank*4+2];
        assign req_mask_b[bank*2+1] = req_mask[bank*4+3];

        assign out_data[(bank*4)*8 +: 8] = out_data_a[(bank*2)*8 +: 8];
        assign out_data[(bank*4+1)*8 +: 8] = out_data_a[(bank*2+1)*8 +: 8];
        assign out_data[(bank*4+2)*8 +: 8] = out_data_b[(bank*2)*8 +: 8];
        assign out_data[(bank*4+3)*8 +: 8] = out_data_b[(bank*2+1)*8 +: 8];
    end endgenerate

    z100_feature_banks_writepipe_4k_v13 #(.ADDR_BITS(ADDR_BITS), .DEPTH(DEPTH)) copy_a (
        .clk(clk), .rst_n(rst_n), .cancel(child_cancel),
        .cfg_begin(cfg_begin_i), .cfg_begin_ready(cfg_begin_ready_a),
        .cfg_canonical_order(cfg_canonical_order), .cfg_epoch(cfg_epoch), .cfg_channels(cfg_channels),
        .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_word_valid(cfg_word_valid_i), .cfg_word_ready(cfg_word_ready_a),
        .cfg_word_data(cfg_word_data), .cfg_word_epoch(cfg_word_epoch),
        .cfg_word_address(cfg_word_address), .cfg_word_last(cfg_word_last),
        .cfg_commit(cfg_commit_i), .cfg_commit_ready(cfg_commit_ready_a),
        .error_valid(error_valid_a), .error_code(error_code_a),
        .store_valid(store_valid_a), .active_epoch(active_epoch_a),
        .loading(loading_a), .req_valid(req_valid_i), .read_hint(read_hint_i), .req_ready(req_ready_a),
        .req_epoch(req_epoch), .req_addresses(req_addresses_a),
        .req_mask(req_mask_a), .out_valid(out_valid_a),
        .out_ready(child_out_ready_a), .out_epoch(out_epoch_a), .out_data(out_data_a)
    );

    z100_feature_banks_writepipe_4k_v13 #(.ADDR_BITS(ADDR_BITS), .DEPTH(DEPTH)) copy_b (
        .clk(clk), .rst_n(rst_n), .cancel(child_cancel),
        .cfg_begin(cfg_begin_i), .cfg_begin_ready(cfg_begin_ready_b),
        .cfg_canonical_order(cfg_canonical_order), .cfg_epoch(cfg_epoch), .cfg_channels(cfg_channels),
        .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_word_valid(cfg_word_valid_i), .cfg_word_ready(cfg_word_ready_b),
        .cfg_word_data(cfg_word_data), .cfg_word_epoch(cfg_word_epoch),
        .cfg_word_address(cfg_word_address), .cfg_word_last(cfg_word_last),
        .cfg_commit(cfg_commit_i), .cfg_commit_ready(cfg_commit_ready_b),
        .error_valid(error_valid_b), .error_code(error_code_b),
        .store_valid(store_valid_b), .active_epoch(active_epoch_b),
        .loading(loading_b), .req_valid(req_valid_i), .read_hint(read_hint_i), .req_ready(req_ready_b),
        .req_epoch(req_epoch), .req_addresses(req_addresses_b),
        .req_mask(req_mask_b), .out_valid(out_valid_b),
        .out_ready(child_out_ready_b), .out_epoch(out_epoch_b), .out_data(out_data_b)
    );

    initial begin
        if ((ADDR_BITS != 13) || (DEPTH != 4096))
            $error("z100_feature_banks_4read requires ADDR_BITS=13 and DEPTH=4096");
    end
endmodule

`default_nettype wire
