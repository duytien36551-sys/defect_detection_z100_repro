`default_nettype none
// Private64-bank feature store. One512-bit configuration word writes all
// banks at the same address. During compute every bank has two independent
// synchronous byte reads. Loading and reads never overlap in this version.
// Bank/read mapping is specified by tools/z100_feature_window_layout.py.
module z100_feature_banks #(
    parameter integer ADDR_BITS = 13,
    parameter integer DEPTH = 8192
) (
    input wire clk,
    input wire rst_n,
    input wire cancel,
    input wire cfg_begin,
    output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,
    input wire [ADDR_BITS:0] cfg_words,
    input wire cfg_word_valid,
    output wire cfg_word_ready,
    input wire [511:0] cfg_data,
    input wire cfg_commit,
    output wire cfg_commit_ready,
    output reg error_valid,
    output reg [2:0] error_code,
    output reg store_valid,
    output reg [31:0] active_epoch,
    output wire loading,
    input wire req_valid,
    output wire req_ready,
    input wire [31:0] req_epoch,
    input wire [128*ADDR_BITS-1:0] req_addresses,
    input wire [127:0] req_mask,
    output reg out_valid,
    input wire out_ready,
    output reg [31:0] out_epoch,
    output wire [1023:0] out_data
);
    reg load_active;
    reg [31:0] pending_epoch;
    reg [ADDR_BITS:0] expected_words;
    reg [ADDR_BITS:0] written_words;
    reg [ADDR_BITS:0] active_words;
    reg [127:0] out_mask;
    reg addresses_ok;
    integer check_port;

    assign loading = load_active;
    assign cfg_begin_ready = rst_n && !load_active && !out_valid && !cancel;
    assign cfg_word_ready = rst_n && load_active && !cfg_begin && !cfg_commit && !cancel;
    assign cfg_commit_ready = rst_n && load_active && !cfg_begin && !cancel;
    assign req_ready = rst_n && store_valid && !load_active && !cfg_begin &&
                       !cfg_commit && !cancel && (!out_valid || out_ready);
    wire req_fire = req_valid && req_ready;
    wire read_fire = req_fire && addresses_ok && (req_epoch == active_epoch);
    wire write_fire = cfg_word_valid && cfg_word_ready &&
                      (written_words < expected_words);

    always @* begin
        addresses_ok = 1'b1;
        for (check_port=0; check_port<128; check_port=check_port+1)
            if (req_mask[check_port] &&
                ({1'b0, req_addresses[check_port*ADDR_BITS +: ADDR_BITS]} >= active_words))
                addresses_ok = 1'b0;
    end

    genvar bank;
    generate for (bank=0; bank<64; bank=bank+1) begin : gen_bank
        (* ram_style = "block" *) reg [7:0] memory [0:DEPTH-1];
        reg [7:0] read_a;
        reg [7:0] read_b;
        // The first version used distinct syntactic write/read addresses;
        // Vivado replicated the RAM despite mutually exclusive enables.
        // Express portA ownership explicitly so write/read share one address.
        wire [ADDR_BITS-1:0] port_a_address = write_fire ?
            written_words[ADDR_BITS-1:0] : req_addresses[(bank*2)*ADDR_BITS +: ADDR_BITS];
        // Local ownership and no reset on read data preserve a true dual-port
        // RAM template. Validity/masks, rather than clearing RAM, own stale data.
        always @(posedge clk) begin
            if (write_fire)
                memory[port_a_address] <= cfg_data[bank*8 +: 8];
            else if (read_fire && req_mask[bank*2])
                read_a <= memory[port_a_address];
        end
        always @(posedge clk) begin
            if (read_fire && req_mask[bank*2+1])
                read_b <= memory[req_addresses[(bank*2+1)*ADDR_BITS +: ADDR_BITS]];
        end
        assign out_data[(bank*2)*8 +: 8] = out_mask[bank*2] ? read_a : 8'd0;
        assign out_data[(bank*2+1)*8 +: 8] = out_mask[bank*2+1] ? read_b : 8'd0;
    end endgenerate

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            load_active <= 0;
            pending_epoch <= 0;
            expected_words <= 0;
            written_words <= 0;
            active_words <= 0;
            active_epoch <= 0;
            store_valid <= 0;
            error_valid <= 0;
            error_code <= 0;
            out_valid <= 0;
            out_epoch <= 0;
            out_mask <= 0;
        end else begin
            error_valid <= 0;
            error_code <= 0;
            if (out_valid && out_ready)
                out_valid <= 0;
            if (cfg_begin && cfg_begin_ready) begin
                store_valid <= 0;
                active_epoch <= 0;
                active_words <= 0;
                written_words <= 0;
                if (cfg_epoch == 0 || cfg_words == 0 || cfg_words > DEPTH ||
                    cfg_word_valid || cfg_commit) begin
                    load_active <= 0;
                    error_valid <= 1;
                    error_code <= 1;
                end else begin
                    load_active <= 1;
                    pending_epoch <= cfg_epoch;
                    expected_words <= cfg_words;
                end
            end else if (load_active) begin
                if (cfg_commit && cfg_commit_ready) begin
                    load_active <= 0;
                    if (written_words != expected_words || cfg_word_valid) begin
                        error_valid <= 1;
                        error_code <= 2;
                    end else begin
                        store_valid <= 1;
                        active_epoch <= pending_epoch;
                        active_words <= expected_words;
                    end
                end else if (cfg_word_valid && cfg_word_ready) begin
                    if (written_words >= expected_words) begin
                        load_active <= 0;
                        store_valid <= 0;
                        error_valid <= 1;
                        error_code <= 3;
                    end else begin
                        written_words <= written_words+1'b1;
                    end
                end
            end else if (req_fire) begin
                if (!addresses_ok || req_epoch != active_epoch) begin
                    store_valid <= 0;
                    active_epoch <= 0;
                    active_words <= 0;
                    error_valid <= 1;
                    error_code <= 4;
                end else begin
                    out_valid <= 1;
                    out_epoch <= active_epoch;
                    out_mask <= req_mask;
                end
            end
        end
    end
endmodule
`default_nettype wire
