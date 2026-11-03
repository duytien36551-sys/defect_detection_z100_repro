`default_nettype none

// Integrated AXI-Lite control frontend and native materialized-Conv V3 backend.
// AXI-Lite addresses are relative byte offsets. A platform bridge must provide
// the assigned base address externally and preserve all 12 address bits.
module z100_native_conv_mmio_backend_resident_guard_v3 #(

    parameter integer SITES = 20,
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
    z100_native_conv_mmio_v2 u_mmio_frontend (
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
        .irq(irq)
    );

    z100_native_conv_backend_v3_resident_guard_v3 #(
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
        .m_axi_arid(m_axi_arid),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready),
        .m_axi_awid(m_axi_awid),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_wid(m_axi_wid),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready)
    );
endmodule

`default_nettype wire


