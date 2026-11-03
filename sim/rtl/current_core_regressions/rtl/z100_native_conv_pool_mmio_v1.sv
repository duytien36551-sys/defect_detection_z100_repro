`default_nettype none

// Integrated AXI-Lite control frontend and native materialized-Conv V3 backend.
// AXI-Lite addresses are relative byte offsets. A platform bridge must provide
// the assigned base address externally and preserve all 12 address bits.
module z100_native_conv_pool_mmio_v1 #(
    parameter integer SITES = 12,
    parameter integer SITE_FIFO_DEPTH = 4,
    parameter MAP_FILE = "conv_event_map.hex",
    parameter TILE_FILE = "conv_tiles.hex"
) (
    input wire clk,
    input wire platform_rst_n,

    input wire [11:0] s_axi_awaddr,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid,
    output wire s_axi_wready,
    output wire [1:0] s_axi_bresp,
    output wire s_axi_bvalid,
    input wire s_axi_bready,

    input wire [11:0] s_axi_araddr,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output wire [31:0] s_axi_rdata,
    output wire [1:0] s_axi_rresp,
    output wire s_axi_rvalid,
    input wire s_axi_rready,
    output wire irq,

    output wire [5:0] m_axi_arid,
    output wire [31:0] m_axi_araddr,
    output wire [3:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [5:0] m_axi_rid,
    input wire [63:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast,
    input wire m_axi_rvalid,
    output wire m_axi_rready,

    output wire [5:0] m_axi_awid,
    output wire [31:0] m_axi_awaddr,
    output wire [3:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output wire m_axi_awvalid,
    input wire m_axi_awready,
    output wire [5:0] m_axi_wid,
    output wire [63:0] m_axi_wdata,
    output wire [7:0] m_axi_wstrb,
    output wire m_axi_wlast,
    output wire m_axi_wvalid,
    input wire m_axi_wready,
    input wire [5:0] m_axi_bid,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready
);
    // Preserve the full relative address. The frontend returns SLVERR for
    // 0x200..0xfff; narrowing to nine bits here would alias those accesses.
    wire [31:0] s_axi_awaddr_rel32 = {20'd0, s_axi_awaddr};
    wire [31:0] s_axi_araddr_rel32 = {20'd0, s_axi_araddr};

    wire [863:0] frontend_cmd_words;
    wire frontend_cmd_valid;
    wire backend_cmd_ready;
    wire frontend_cancel;
    wire source_lease_valid;
    wire [31:0] source_lease_generation;
    wire [31:0] source_lease_region_begin;
    wire [32:0] source_lease_region_end;
    wire destination_reservation_valid;
    wire [31:0] destination_reservation_generation;
    wire [31:0] destination_reservation_region_begin;
    wire [32:0] destination_reservation_region_end;

    wire backend_active;
    wire backend_fault;
    wire [3:0] backend_fault_code;
    wire backend_needs_drain;
    wire backend_drain_complete;
    wire backend_all_io_quiet;
    wire [7:0] backend_committed_tiles;
    wire backend_producer_complete;
    wire [31:0] backend_complete_epoch;
    wire [7:0] backend_complete_event;
    wire [31:0] backend_complete_model_crc;
    wire [31:0] backend_complete_job_base;
    wire [31:0] backend_complete_token_base;
    wire [31:0] backend_complete_tag_base;
    wire [31:0] backend_complete_destination_generation;
    wire [7:0] backend_complete_tiles;
    wire [1:0] backend_diagnostic_read_kind;
    wire backend_diagnostic_load_active,backend_diagnostic_compute_active;
    wire backend_diagnostic_write_active,backend_diagnostic_mac_good_group;
    wire [10:0] backend_diagnostic_mac_good_slots;
    wire backend_diagnostic_mac_starve,backend_diagnostic_mac_output_stall;
    wire backend_diagnostic_residency_hit,backend_diagnostic_residency_miss;

    wire [5:0] diagnostic_counter_index;
    wire [31:0] diagnostic_counter_data;
    wire diagnostic_snapshot_valid,diagnostic_overflow;
    wire [1:0] diagnostic_outcome;
    wire [31:0] diagnostic_epoch;
    wire [7:0] diagnostic_event;
    wire [3:0] diagnostic_fault_code;

    // Producer context is kept connected to real backend outputs for the
    // integration boundary; MMIO reports only the frozen frontend result ABI.
    wire backend_producer_context_valid;
    wire [15:0] backend_producer_cin;
    wire [15:0] backend_producer_input_height;
    wire [15:0] backend_producer_input_width;
    wire [15:0] backend_producer_cout;
    wire [15:0] backend_producer_output_height;
    wire [15:0] backend_producer_output_width;
    wire [15:0] backend_producer_kernel;
    wire [15:0] backend_producer_stride;
    wire [15:0] backend_producer_padding;
    wire [15:0] backend_producer_parameter_first;
    wire [7:0] backend_producer_event;

    // The snapshot is little-word-first: [31:0] is ABI word 0. Word 0
    // (request cookie) and word 26 (frontend preaccept timeout) are frontend
    // control only; all other backend command fields are wired below.
    z100_native_conv_pool_mmio_frontend_v1 u_mmio_frontend (
        .clk(clk),
        .platform_rst_n(platform_rst_n),
        .s_axi_awaddr(s_axi_awaddr_rel32),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata),
        .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr_rel32),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready),
        .backend_cmd_words(frontend_cmd_words),
        .backend_cmd_valid(frontend_cmd_valid),
        .backend_cmd_ready(backend_cmd_ready),
        .backend_cancel(frontend_cancel),
        .backend_source_lease_valid(source_lease_valid),
        .backend_source_lease_generation(source_lease_generation),
        .backend_source_lease_region_begin(source_lease_region_begin),
        .backend_source_lease_region_end(source_lease_region_end),
        .backend_destination_reservation_valid(destination_reservation_valid),
        .backend_destination_reservation_generation(destination_reservation_generation),
        .backend_destination_reservation_region_begin(destination_reservation_region_begin),
        .backend_destination_reservation_region_end(destination_reservation_region_end),
        .backend_active(backend_active),
        .backend_fault(backend_fault),
        .backend_fault_code(backend_fault_code),
        .backend_needs_drain(backend_needs_drain),
        .backend_drain_complete(backend_drain_complete),
        .backend_all_io_quiet(backend_all_io_quiet),
        .backend_committed_tiles(backend_committed_tiles),
        .backend_producer_complete(backend_producer_complete),
        .backend_complete_epoch(backend_complete_epoch),
        .backend_complete_event(backend_complete_event),
        .backend_complete_model_crc(backend_complete_model_crc),
        .backend_complete_job_base(backend_complete_job_base),
        .backend_complete_token_base(backend_complete_token_base),
        .backend_complete_tag_base(backend_complete_tag_base),
        .backend_complete_destination_generation(backend_complete_destination_generation),
        .backend_complete_tiles(backend_complete_tiles),
        .backend_diagnostic_counter_index(diagnostic_counter_index),
        .backend_diagnostic_counter_data(diagnostic_counter_data),
        .backend_diagnostic_snapshot_valid(diagnostic_snapshot_valid),
        .backend_diagnostic_outcome(diagnostic_outcome),
        .backend_diagnostic_overflow(diagnostic_overflow),
        .backend_diagnostic_epoch(diagnostic_epoch),
        .backend_diagnostic_event(diagnostic_event),
        .backend_diagnostic_fault_code(diagnostic_fault_code),
        .irq(irq)
    );

    // periph_flat_v3: two-entry register slices on all five HP0 channels.
    // Every PS7 S_AXI_HP0 input lands in a flip-flop and every output is
    // driven by a flip-flop, so no backend cone reaches a PS7 pin. Slices use
    // platform_rst_n only (never cancel), so no accepted beat is ever dropped.
    wire [5:0] i_arid, i_rid, i_awid, i_wid, i_bid;
    wire [31:0] i_araddr, i_awaddr;
    wire [3:0] i_arlen, i_awlen;
    wire [2:0] i_arsize, i_awsize;
    wire [1:0] i_arburst, i_awburst, i_rresp, i_bresp;
    wire i_arvalid, i_arready, i_rlast, i_rvalid, i_rready;
    wire i_awvalid, i_awready, i_wlast, i_wvalid, i_wready, i_bvalid, i_bready;
    wire [63:0] i_rdata, i_wdata;
    wire [7:0] i_wstrb;
    z100_skid_v13c #(.W(47)) hp0_ar_slice (.clk(clk), .rst_n(platform_rst_n), .flush(1'b0),
        .in_valid(i_arvalid), .in_ready(i_arready), .in_data({i_arid,i_araddr,i_arlen,i_arsize,i_arburst}),
        .out_valid(m_axi_arvalid), .out_ready(m_axi_arready),
        .out_data({m_axi_arid,m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst}));
    z100_skid_v13c #(.W(73)) hp0_r_slice (.clk(clk), .rst_n(platform_rst_n), .flush(1'b0),
        .in_valid(m_axi_rvalid), .in_ready(m_axi_rready), .in_data({m_axi_rid,m_axi_rdata,m_axi_rresp,m_axi_rlast}),
        .out_valid(i_rvalid), .out_ready(i_rready), .out_data({i_rid,i_rdata,i_rresp,i_rlast}));
    z100_skid_v13c #(.W(47)) hp0_aw_slice (.clk(clk), .rst_n(platform_rst_n), .flush(1'b0),
        .in_valid(i_awvalid), .in_ready(i_awready), .in_data({i_awid,i_awaddr,i_awlen,i_awsize,i_awburst}),
        .out_valid(m_axi_awvalid), .out_ready(m_axi_awready),
        .out_data({m_axi_awid,m_axi_awaddr,m_axi_awlen,m_axi_awsize,m_axi_awburst}));
    z100_skid_v13c #(.W(79)) hp0_w_slice (.clk(clk), .rst_n(platform_rst_n), .flush(1'b0),
        .in_valid(i_wvalid), .in_ready(i_wready), .in_data({i_wid,i_wdata,i_wstrb,i_wlast}),
        .out_valid(m_axi_wvalid), .out_ready(m_axi_wready), .out_data({m_axi_wid,m_axi_wdata,m_axi_wstrb,m_axi_wlast}));
    z100_skid_v13c #(.W(8)) hp0_b_slice (.clk(clk), .rst_n(platform_rst_n), .flush(1'b0),
        .in_valid(m_axi_bvalid), .in_ready(m_axi_bready), .in_data({m_axi_bid,m_axi_bresp}),
        .out_valid(i_bvalid), .out_ready(i_bready), .out_data({i_bid,i_bresp}));

    z100_native_conv_pool_backend_v1 #(
        .SITES(SITES),
        .SITE_FIFO_DEPTH(SITE_FIFO_DEPTH),
        .MAP_FILE(MAP_FILE),
        .TILE_FILE(TILE_FILE)
    ) u_conv_backend (
        .clk(clk),
        .rst_n(platform_rst_n),
        .cmd_valid(frontend_cmd_valid),
        .cmd_ready(backend_cmd_ready),
        .cmd_epoch(frontend_cmd_words[1*32 +: 32]),
        .cmd_event(frontend_cmd_words[2*32 +: 8]),
        .cmd_model_crc(frontend_cmd_words[3*32 +: 32]),
        .cmd_job_base(frontend_cmd_words[4*32 +: 32]),
        .cmd_token_base(frontend_cmd_words[5*32 +: 32]),
        .cmd_tag_base(frontend_cmd_words[6*32 +: 32]),
        .cmd_first_bank(frontend_cmd_words[7*32]),
        .cmd_source_base(frontend_cmd_words[8*32 +: 32]),
        .cmd_source_generation(frontend_cmd_words[9*32 +: 32]),
        .source_lease_valid(source_lease_valid),
        .source_lease_generation(source_lease_generation),
        .source_lease_region_begin(source_lease_region_begin),
        .source_lease_region_end(source_lease_region_end),
        .cmd_destination_base(frontend_cmd_words[13*32 +: 32]),
        .cmd_destination_generation(frontend_cmd_words[14*32 +: 32]),
        .destination_reservation_valid(destination_reservation_valid),
        .destination_reservation_generation(destination_reservation_generation),
        .destination_reservation_region_begin(destination_reservation_region_begin),
        .destination_reservation_region_end(destination_reservation_region_end),
        .cmd_parameter_directory_base(frontend_cmd_words[18*32 +: 32]),
        .cmd_parameter_count(frontend_cmd_words[19*32 +: 16]),
        .cmd_parameter_payload_begin(frontend_cmd_words[20*32 +: 32]),
        .cmd_parameter_payload_end({frontend_cmd_words[22*32], frontend_cmd_words[21*32 +: 32]}),
        .cmd_load_timeout_cycles(frontend_cmd_words[23*32 +: 32]),
        .cmd_parameter_timeout_cycles(frontend_cmd_words[24*32 +: 32]),
        .cmd_write_timeout_cycles(frontend_cmd_words[25*32 +: 32]),
        .cancel(frontend_cancel),
        .active(backend_active),
        .fault(backend_fault),
        .fault_code(backend_fault_code),
        .needs_drain(backend_needs_drain),
        .drain_complete(backend_drain_complete),
        .all_io_quiet(backend_all_io_quiet),
        .producer_context_valid(backend_producer_context_valid),
        .producer_cin(backend_producer_cin),
        .producer_input_height(backend_producer_input_height),
        .producer_input_width(backend_producer_input_width),
        .producer_cout(backend_producer_cout),
        .producer_output_height(backend_producer_output_height),
        .producer_output_width(backend_producer_output_width),
        .producer_kernel(backend_producer_kernel),
        .producer_stride(backend_producer_stride),
        .producer_padding(backend_producer_padding),
        .producer_parameter_first(backend_producer_parameter_first),
        .producer_event(backend_producer_event),
        .producer_complete(backend_producer_complete),
        .producer_complete_epoch(backend_complete_epoch),
        .producer_complete_event(backend_complete_event),
        .producer_complete_model_crc(backend_complete_model_crc),
        .producer_complete_job_base(backend_complete_job_base),
        .producer_complete_token_base(backend_complete_token_base),
        .producer_complete_tag_base(backend_complete_tag_base),
        .producer_complete_destination_generation(backend_complete_destination_generation),
        .producer_complete_tiles(backend_complete_tiles),
        .diagnostic_read_kind(backend_diagnostic_read_kind),
        .diagnostic_load_active(backend_diagnostic_load_active),
        .diagnostic_compute_active(backend_diagnostic_compute_active),
        .diagnostic_write_active(backend_diagnostic_write_active),
        .diagnostic_mac_good_group(backend_diagnostic_mac_good_group),
        .diagnostic_mac_good_slots(backend_diagnostic_mac_good_slots),
        .diagnostic_mac_starve(backend_diagnostic_mac_starve),
        .diagnostic_mac_output_stall(backend_diagnostic_mac_output_stall),
        .diagnostic_residency_hit(backend_diagnostic_residency_hit),
        .diagnostic_residency_miss(backend_diagnostic_residency_miss),
        .m_axi_arid(i_arid),
        .m_axi_araddr(i_araddr),
        .m_axi_arlen(i_arlen),
        .m_axi_arsize(i_arsize),
        .m_axi_arburst(i_arburst),
        .m_axi_arvalid(i_arvalid),
        .m_axi_arready(i_arready),
        .m_axi_rid(i_rid),
        .m_axi_rdata(i_rdata),
        .m_axi_rresp(i_rresp),
        .m_axi_rlast(i_rlast),
        .m_axi_rvalid(i_rvalid),
        .m_axi_rready(i_rready),
        .m_axi_awid(i_awid),
        .m_axi_awaddr(i_awaddr),
        .m_axi_awlen(i_awlen),
        .m_axi_awsize(i_awsize),
        .m_axi_awburst(i_awburst),
        .m_axi_awvalid(i_awvalid),
        .m_axi_awready(i_awready),
        .m_axi_wid(i_wid),
        .m_axi_wdata(i_wdata),
        .m_axi_wstrb(i_wstrb),
        .m_axi_wlast(i_wlast),
        .m_axi_wvalid(i_wvalid),
        .m_axi_wready(i_wready),
        .m_axi_bid(i_bid),
        .m_axi_bresp(i_bresp),
        .m_axi_bvalid(i_bvalid),
        .m_axi_bready(i_bready)
    );

    z100_native_event_counters_v1 u_event_counters (
        .clk(clk), .rst_n(platform_rst_n),
        .event_start(frontend_cmd_valid && backend_cmd_ready),
        .event_epoch(frontend_cmd_words[1*32 +: 32]),
        .event_id(frontend_cmd_words[2*32 +: 8]),
        .success_terminal(backend_producer_complete),
        .fault(backend_fault), .all_io_quiet(backend_all_io_quiet),
        .fault_code(backend_fault_code), .cancel(frontend_cancel),
        .read_kind(backend_diagnostic_read_kind),
        .m_axi_arvalid(m_axi_arvalid), .m_axi_arready(m_axi_arready),
        .m_axi_rvalid(m_axi_rvalid), .m_axi_rready(m_axi_rready),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_wstrb(m_axi_wstrb), .m_axi_wlast(m_axi_wlast),
        .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(m_axi_bready),
        .phase_enable(!backend_fault),
        .load_active(backend_diagnostic_load_active),
        .compute_active(backend_diagnostic_compute_active),
        .write_active(backend_diagnostic_write_active),
        .mac_good_group(backend_diagnostic_mac_good_group),
        .mac_good_slots(backend_diagnostic_mac_good_slots),
        .mac_starve(backend_diagnostic_mac_starve),
        .mac_output_stall(backend_diagnostic_mac_output_stall),
        .residency_hit(backend_diagnostic_residency_hit),
        .residency_miss(backend_diagnostic_residency_miss),
        .read_index(diagnostic_counter_index), .read_data(diagnostic_counter_data),
        .snapshot_valid(diagnostic_snapshot_valid),
        .snapshot_outcome(diagnostic_outcome),
        .snapshot_overflow(diagnostic_overflow),
        .snapshot_epoch(diagnostic_epoch), .snapshot_event(diagnostic_event),
        .snapshot_fault_code(diagnostic_fault_code)
    );
endmodule

`default_nettype wire


