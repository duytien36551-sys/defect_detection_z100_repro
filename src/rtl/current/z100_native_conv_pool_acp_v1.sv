`default_nettype none

// ACP transport wrapper around the unchanged accepted S12 compute platform.
// AXI-Lite addresses are relative byte offsets. A platform bridge must provide
// the assigned base address externally and preserve all 12 address bits.
module z100_native_conv_pool_acp_v1 #(
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

    output wire [3:0] m_axi_arcache,
    output wire [3:0] m_axi_awcache,
    output wire [2:0] m_axi_arprot,
    output wire [2:0] m_axi_awprot,
    output wire [1:0] m_axi_arlock,
    output wire [1:0] m_axi_awlock,
    output wire [4:0] m_axi_aruser,
    output wire [4:0] m_axi_awuser,
    output wire [2:0] m_axi_arid,
    output wire [31:0] m_axi_araddr,
    output wire [3:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [2:0] m_axi_rid,
    input wire [63:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast,
    input wire m_axi_rvalid,
    output wire m_axi_rready,

    output wire [2:0] m_axi_awid,
    output wire [31:0] m_axi_awaddr,
    output wire [3:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output wire m_axi_awvalid,
    input wire m_axi_awready,
    output wire [2:0] m_axi_wid,
    output wire [63:0] m_axi_wdata,
    output wire [7:0] m_axi_wstrb,
    output wire m_axi_wlast,
    output wire m_axi_wvalid,
    input wire m_axi_wready,
    input wire [2:0] m_axi_bid,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready
);

    // UG585 3.5: coherent iff AxUSER[0] && AxCACHE[1].
    // PS7 also inserts USER=31 internally. No exclusive or locked access.
    assign m_axi_arcache=4'hf; assign m_axi_awcache=4'hf;
    assign m_axi_arprot=3'b000; assign m_axi_awprot=3'b000;
    assign m_axi_arlock=2'b00; assign m_axi_awlock=2'b00;
    assign m_axi_aruser=5'd31; assign m_axi_awuser=5'd31;
    wire [5:0] native_arid,native_awid,native_wid;
    assign m_axi_arid=native_arid[2:0];
    assign m_axi_awid=native_awid[2:0];
    assign m_axi_wid=native_wid[2:0];
    // All accepted producers emit ID zero; arbitration does not add source tags.
    // Keep the original six-bit response checks by explicit zero extension.
    z100_native_conv_pool_mmio_v1 #(.SITES(SITES),.SITE_FIFO_DEPTH(SITE_FIFO_DEPTH),
        .MAP_FILE(MAP_FILE),.TILE_FILE(TILE_FILE)) accepted_core (
        .clk(clk),
        .platform_rst_n(platform_rst_n),
        .s_axi_awaddr(s_axi_awaddr),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata),
        .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready),
        .irq(irq),
        .m_axi_arid(native_arid),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_rid({3'b000,m_axi_rid}),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready),
        .m_axi_awid(native_awid),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_wid(native_wid),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_bid({3'b000,m_axi_bid}),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready)
    );
`ifndef SYNTHESIS
    always @(posedge clk) if (platform_rst_n) begin
        if (m_axi_arvalid && native_arid !== 6'd0) $fatal(1,"ACP_ARID_NOT_ZERO");
        if (m_axi_awvalid && native_awid !== 6'd0) $fatal(1,"ACP_AWID_NOT_ZERO");
        if (m_axi_wvalid && native_wid !== 6'd0) $fatal(1,"ACP_WID_NOT_ZERO");
    end
`endif
endmodule
`default_nettype wire
