`timescale 1ns/1ps

// Offline integration harness for the pinned Z100 simulation sources.
// system_axi_dma_0_0, both generated auto_pc wrappers, system_mem_xbar_0,
// system_mm2s_response_slice_0, and system_yolo_accel_top_0_0 are the actual
// exported Vivado simulation models. The AXI-Lite masters and HP0 AXI3 DDR
// endpoint below are behavioral testbench models; they are not PS7 or DDR.
module tb_z100_dma_integration;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;

    integer timeout_count = 0;
    integer failure_count = 0;
    integer cpu_writes = 0;
    integer dma_writes = 0;
    integer dma_reads = 0;
    integer mm2s_beats = 0;
    integer mm2s_tlasts = 0;
    integer s2mm_beats = 0;
    integer s2mm_tlasts = 0;
    integer hp_ar = 0;
    integer hp_r = 0;
    integer hp_aw = 0;
    integer hp_w = 0;
    integer hp_b = 0;
    integer hp_r_stall_cycles = 0;
    integer hp_w_stall_cycles = 0;
    integer base_ar, base_r, base_w;
    integer base_dma_ar_bursts, base_dma_ar_beats, base_dma_r_beats, base_dma_r_lasts;
    integer base_dma_aw_bursts, base_dma_aw_beats, base_dma_w_beats, base_dma_b_responses;
    integer base_hp_ar_beats, base_hp_r_lasts, base_hp_aw, base_hp_aw_beats, base_hp_w, base_hp_b;
    integer hp_ar_beats = 0;
    integer hp_r_lasts = 0;
    integer hp_aw_beats = 0;
    integer dma_ar_bursts = 0;
    integer dma_ar_beats = 0;
    integer dma_r_beats = 0;
    integer dma_r_lasts = 0;
    integer dma_aw_bursts = 0;
    integer dma_aw_beats = 0;
    integer dma_w_beats = 0;
    integer dma_b_responses = 0;
    integer memory_model_cycles = 0;
    integer i;

    // AMD AXI DMA AXI4-Lite control/status port (behavioral CPU master).
    reg [9:0] dma_awaddr = 0;
    reg dma_awvalid = 0;
    wire dma_awready;
    reg [31:0] dma_wdata = 0;
    reg dma_wvalid = 0;
    wire dma_wready;
    wire [1:0] dma_bresp;
    wire dma_bvalid;
    reg dma_bready = 0;
    reg [9:0] dma_araddr = 0;
    reg dma_arvalid = 0;
    wire dma_arready;
    wire [31:0] dma_rdata;
    wire [1:0] dma_rresp;
    wire dma_rvalid;
    reg dma_rready = 0;

    // Accelerator AXI4-Lite control port (behavioral CPU master).
    reg [3:0] acc_awaddr = 0;
    reg [2:0] acc_awprot = 0;
    reg acc_awvalid = 0;
    wire acc_awready;
    reg [31:0] acc_wdata = 0;
    reg [3:0] acc_wstrb = 4'hf;
    reg acc_wvalid = 0;
    wire acc_wready;
    wire [1:0] acc_bresp;
    wire acc_bvalid;
    reg acc_bready = 0;
    reg [3:0] acc_araddr = 0;
    reg [2:0] acc_arprot = 0;
    reg acc_arvalid = 0;
    wire acc_arready;
    wire [31:0] acc_rdata;
    wire [1:0] acc_rresp;
    wire acc_rvalid;
    reg acc_rready = 0;
    wire [31:0] acc_reg0, acc_reg1, acc_reg2, acc_reg3;

    // AXI DMA simple-mode stream and memory interfaces.
    wire [31:0] mm_araddr;
    wire [7:0] mm_arlen;
    wire [2:0] mm_arsize;
    wire [1:0] mm_arburst;
    wire [2:0] mm_arprot;
    wire [3:0] mm_arcache;
    wire mm_arvalid;
    wire mm_arready;
    wire [31:0] mm_rdata;
    wire [1:0] mm_rresp;
    wire mm_rlast;
    wire mm_rvalid;
    wire mm_rready;
    wire [31:0] mm_axis_tdata;
    wire [3:0] mm_axis_tkeep;
    wire mm_axis_tvalid;
    wire mm_axis_tready;
    wire mm_axis_tlast;
    wire [31:0] sm_awaddr;
    wire [7:0] sm_awlen;
    wire [2:0] sm_awsize;
    wire [1:0] sm_awburst;
    wire [2:0] sm_awprot;
    wire [3:0] sm_awcache;
    wire sm_awvalid;
    wire sm_awready;
    wire [31:0] sm_wdata;
    wire [3:0] sm_wstrb;
    wire sm_wlast;
    wire sm_wvalid;
    wire sm_wready;
    wire [1:0] sm_bresp;
    wire sm_bvalid;
    wire sm_bready;
    wire [31:0] accel_s2mm_tdata;
    wire [3:0] accel_s2mm_tkeep;
    wire accel_s2mm_tvalid;
    wire accel_s2mm_tready;
    wire accel_s2mm_tlast;
    wire accel_task_finish;
    wire mm2s_reset_out_n, s2mm_reset_out_n;
    wire mm2s_introut, s2mm_introut;
    wire [31:0] dma_tstvec;

    system_axi_dma_0_0 dma (
        .s_axi_lite_aclk(clk), .m_axi_mm2s_aclk(clk),
        .m_axi_s2mm_aclk(clk), .axi_resetn(rst_n),
        .s_axi_lite_awvalid(dma_awvalid), .s_axi_lite_awready(dma_awready),
        .s_axi_lite_awaddr(dma_awaddr), .s_axi_lite_wvalid(dma_wvalid),
        .s_axi_lite_wready(dma_wready), .s_axi_lite_wdata(dma_wdata),
        .s_axi_lite_bresp(dma_bresp), .s_axi_lite_bvalid(dma_bvalid),
        .s_axi_lite_bready(dma_bready), .s_axi_lite_arvalid(dma_arvalid),
        .s_axi_lite_arready(dma_arready), .s_axi_lite_araddr(dma_araddr),
        .s_axi_lite_rvalid(dma_rvalid), .s_axi_lite_rready(dma_rready),
        .s_axi_lite_rdata(dma_rdata), .s_axi_lite_rresp(dma_rresp),
        .m_axi_mm2s_araddr(mm_araddr), .m_axi_mm2s_arlen(mm_arlen),
        .m_axi_mm2s_arsize(mm_arsize), .m_axi_mm2s_arburst(mm_arburst),
        .m_axi_mm2s_arprot(mm_arprot), .m_axi_mm2s_arcache(mm_arcache),
        .m_axi_mm2s_arvalid(mm_arvalid), .m_axi_mm2s_arready(mm_arready),
        .m_axi_mm2s_rdata(mm_rdata), .m_axi_mm2s_rresp(mm_rresp),
        .m_axi_mm2s_rlast(mm_rlast), .m_axi_mm2s_rvalid(mm_rvalid),
        .m_axi_mm2s_rready(mm_rready), .mm2s_prmry_reset_out_n(mm2s_reset_out_n),
        .m_axis_mm2s_tdata(mm_axis_tdata), .m_axis_mm2s_tkeep(mm_axis_tkeep),
        .m_axis_mm2s_tvalid(mm_axis_tvalid), .m_axis_mm2s_tready(mm_axis_tready),
        .m_axis_mm2s_tlast(mm_axis_tlast), .m_axi_s2mm_awaddr(sm_awaddr),
        .m_axi_s2mm_awlen(sm_awlen), .m_axi_s2mm_awsize(sm_awsize),
        .m_axi_s2mm_awburst(sm_awburst), .m_axi_s2mm_awprot(sm_awprot),
        .m_axi_s2mm_awcache(sm_awcache), .m_axi_s2mm_awvalid(sm_awvalid),
        .m_axi_s2mm_awready(sm_awready), .m_axi_s2mm_wdata(sm_wdata),
        .m_axi_s2mm_wstrb(sm_wstrb), .m_axi_s2mm_wlast(sm_wlast),
        .m_axi_s2mm_wvalid(sm_wvalid), .m_axi_s2mm_wready(sm_wready),
        .m_axi_s2mm_bresp(sm_bresp), .m_axi_s2mm_bvalid(sm_bvalid),
        .m_axi_s2mm_bready(sm_bready), .s2mm_prmry_reset_out_n(s2mm_reset_out_n),
        .s_axis_s2mm_tdata(accel_s2mm_tdata),
        .s_axis_s2mm_tkeep(accel_s2mm_tkeep),
        .s_axis_s2mm_tvalid(accel_s2mm_tvalid),
        .s_axis_s2mm_tready(accel_s2mm_tready),
        .s_axis_s2mm_tlast(accel_s2mm_tlast),
        .mm2s_introut(mm2s_introut), .s2mm_introut(s2mm_introut),
        .axi_dma_tstvec(dma_tstvec)
    );

    system_axi4_lite_v1_0_0_0 accel_regs (
        .slave_reg0(acc_reg0), .slave_reg1(acc_reg1),
        .slave_reg2(acc_reg2), .slave_reg3(acc_reg3),
        .s00_axi_aclk(clk), .s00_axi_aresetn(rst_n),
        .s00_axi_awaddr(acc_awaddr), .s00_axi_awprot(acc_awprot),
        .s00_axi_awvalid(acc_awvalid), .s00_axi_awready(acc_awready),
        .s00_axi_wdata(acc_wdata), .s00_axi_wstrb(acc_wstrb),
        .s00_axi_wvalid(acc_wvalid), .s00_axi_wready(acc_wready),
        .s00_axi_bresp(acc_bresp), .s00_axi_bvalid(acc_bvalid),
        .s00_axi_bready(acc_bready), .s00_axi_araddr(acc_araddr),
        .s00_axi_arprot(acc_arprot), .s00_axi_arvalid(acc_arvalid),
        .s00_axi_arready(acc_arready), .s00_axi_rdata(acc_rdata),
        .s00_axi_rresp(acc_rresp), .s00_axi_rvalid(acc_rvalid),
        .s00_axi_rready(acc_rready)
    );

    system_yolo_accel_top_0_0 accel (
        .sclk(clk), .s_rst_n(rst_n), .slave_lite_reg0(acc_reg0),
        .slave_lite_reg1(acc_reg1), .slave_lite_reg2(acc_reg2),
        .slave_lite_reg3(acc_reg3), .s_axis_mm2s_tdata(mm_axis_tdata),
        .s_axis_mm2s_tkeep(mm_axis_tkeep), .s_axis_mm2s_tvalid(mm_axis_tvalid),
        .s_axis_mm2s_tready(mm_axis_tready), .s_axis_mm2s_tlast(mm_axis_tlast),
        .s_axis_s2mm_tdata(accel_s2mm_tdata), .s_axis_s2mm_tkeep(accel_s2mm_tkeep),
        .s_axis_s2mm_tvalid(accel_s2mm_tvalid),
        .s_axis_s2mm_tready(accel_s2mm_tready),
        .s_axis_s2mm_tlast(accel_s2mm_tlast), .task_finish(accel_task_finish)
    );

    wire [31:0] slice_s_araddr, slice_m_araddr;
    wire [7:0] slice_s_arlen, slice_m_arlen;
    wire [2:0] slice_s_arsize, slice_m_arsize;
    wire [1:0] slice_s_arburst, slice_m_arburst;
    wire slice_s_arlock, slice_m_arlock;
    wire [3:0] slice_s_arcache, slice_m_arcache;
    wire [2:0] slice_s_arprot, slice_m_arprot;
    wire [3:0] slice_s_arregion, slice_m_arregion;
    wire [3:0] slice_s_arqos, slice_m_arqos;
    wire slice_s_arvalid, slice_s_arready, slice_m_arvalid, slice_m_arready;
    wire [31:0] slice_s_rdata, slice_m_rdata;
    wire [1:0] slice_s_rresp, slice_m_rresp;
    wire slice_s_rlast, slice_s_rvalid, slice_s_rready;
    wire slice_m_rlast, slice_m_rvalid, slice_m_rready;

    assign slice_s_araddr = mm_araddr;
    assign slice_s_arlen = mm_arlen;
    assign slice_s_arsize = mm_arsize;
    assign slice_s_arburst = mm_arburst;
    assign slice_s_arlock = 1'b0;
    assign slice_s_arcache = mm_arcache;
    assign slice_s_arprot = mm_arprot;
    assign slice_s_arregion = 4'b0;
    assign slice_s_arqos = 4'b0;
    assign slice_s_arvalid = mm_arvalid;
    assign mm_arready = slice_s_arready;
    assign mm_rdata = slice_s_rdata;
    assign mm_rresp = slice_s_rresp;
    assign mm_rlast = slice_s_rlast;
    assign mm_rvalid = slice_s_rvalid;
    assign slice_s_rready = mm_rready;

    system_mm2s_response_slice_0 response_slice (
        .aclk(clk), .aresetn(rst_n),
        .s_axi_araddr(slice_s_araddr), .s_axi_arlen(slice_s_arlen),
        .s_axi_arsize(slice_s_arsize), .s_axi_arburst(slice_s_arburst),
        .s_axi_arlock(slice_s_arlock), .s_axi_arcache(slice_s_arcache),
        .s_axi_arprot(slice_s_arprot), .s_axi_arregion(slice_s_arregion),
        .s_axi_arqos(slice_s_arqos), .s_axi_arvalid(slice_s_arvalid),
        .s_axi_arready(slice_s_arready), .s_axi_rdata(slice_s_rdata),
        .s_axi_rresp(slice_s_rresp), .s_axi_rlast(slice_s_rlast),
        .s_axi_rvalid(slice_s_rvalid), .s_axi_rready(slice_s_rready),
        .m_axi_araddr(slice_m_araddr), .m_axi_arlen(slice_m_arlen),
        .m_axi_arsize(slice_m_arsize), .m_axi_arburst(slice_m_arburst),
        .m_axi_arlock(slice_m_arlock), .m_axi_arcache(slice_m_arcache),
        .m_axi_arprot(slice_m_arprot), .m_axi_arregion(slice_m_arregion),
        .m_axi_arqos(slice_m_arqos), .m_axi_arvalid(slice_m_arvalid),
        .m_axi_arready(slice_m_arready), .m_axi_rdata(slice_m_rdata),
        .m_axi_rresp(slice_m_rresp), .m_axi_rlast(slice_m_rlast),
        .m_axi_rvalid(slice_m_rvalid), .m_axi_rready(slice_m_rready)
    );

    // Actual generated mem_xbar top: both exported auto_pc converters and
    // the crossbar remain in this hierarchy. Names match its flat port list.
    wire ACLK = clk;
    wire ARESETN = rst_n;
    wire M00_ACLK = clk;
    wire M00_ARESETN = rst_n;
    wire S00_ACLK = clk;
    wire S00_ARESETN = rst_n;
    wire S01_ACLK = clk;
    wire S01_ARESETN = rst_n;

    wire [31:0] M00_AXI_araddr, M00_AXI_awaddr, M00_AXI_rdata, M00_AXI_wdata;
    wire [1:0] M00_AXI_arburst, M00_AXI_awburst, M00_AXI_rresp, M00_AXI_bresp;
    wire [3:0] M00_AXI_arcache, M00_AXI_arlen, M00_AXI_awcache, M00_AXI_awlen;
    wire [0:0] M00_AXI_arid, M00_AXI_awid, M00_AXI_wid;
    wire [1:0] M00_AXI_arlock, M00_AXI_awlock;
    wire [2:0] M00_AXI_arprot, M00_AXI_arsize, M00_AXI_awprot, M00_AXI_awsize;
    wire [3:0] M00_AXI_arqos, M00_AXI_awqos, M00_AXI_wstrb;
    wire [0:0] M00_AXI_arready, M00_AXI_arvalid, M00_AXI_awready, M00_AXI_awvalid;
    wire [5:0] M00_AXI_bid, M00_AXI_rid;
    wire [0:0] M00_AXI_bready, M00_AXI_bvalid, M00_AXI_rlast;
    wire [0:0] M00_AXI_rready, M00_AXI_rvalid, M00_AXI_wlast;
    wire [0:0] M00_AXI_wready, M00_AXI_wvalid;

    wire [31:0] S00_AXI_araddr;
    wire [1:0] S00_AXI_arburst;
    wire [3:0] S00_AXI_arcache;
    wire [7:0] S00_AXI_arlen;
    wire [0:0] S00_AXI_arlock;
    wire [2:0] S00_AXI_arprot;
    wire [3:0] S00_AXI_arqos;
    wire S00_AXI_arready;
    wire [3:0] S00_AXI_arregion;
    wire [2:0] S00_AXI_arsize;
    wire S00_AXI_arvalid;
    wire [31:0] S00_AXI_rdata;
    wire S00_AXI_rlast;
    wire S00_AXI_rready;
    wire [1:0] S00_AXI_rresp;
    wire S00_AXI_rvalid;

    wire [31:0] S01_AXI_awaddr, S01_AXI_wdata;
    wire [1:0] S01_AXI_awburst, S01_AXI_bresp;
    wire [3:0] S01_AXI_awcache, S01_AXI_wstrb;
    wire [7:0] S01_AXI_awlen;
    wire [2:0] S01_AXI_awprot, S01_AXI_awsize;
    wire S01_AXI_awready, S01_AXI_awvalid;
    wire S01_AXI_bready, S01_AXI_bvalid;
    wire S01_AXI_wlast, S01_AXI_wready, S01_AXI_wvalid;

    assign S00_AXI_araddr = slice_m_araddr;
    assign S00_AXI_arburst = slice_m_arburst;
    assign S00_AXI_arcache = slice_m_arcache;
    assign S00_AXI_arlen = slice_m_arlen;
    assign S00_AXI_arlock = slice_m_arlock;
    assign S00_AXI_arprot = slice_m_arprot;
    assign S00_AXI_arqos = slice_m_arqos;
    assign S00_AXI_arregion = slice_m_arregion;
    assign S00_AXI_arsize = slice_m_arsize;
    assign S00_AXI_arvalid = slice_m_arvalid;
    assign slice_m_arready = S00_AXI_arready;
    assign slice_m_rdata = S00_AXI_rdata;
    assign slice_m_rresp = S00_AXI_rresp;
    assign slice_m_rlast = S00_AXI_rlast;
    assign slice_m_rvalid = S00_AXI_rvalid;
    assign S00_AXI_rready = slice_m_rready;

    assign S01_AXI_awaddr = sm_awaddr;
    assign S01_AXI_awburst = sm_awburst;
    assign S01_AXI_awcache = sm_awcache;
    assign S01_AXI_awlen = sm_awlen;
    assign S01_AXI_awprot = sm_awprot;
    assign S01_AXI_awsize = sm_awsize;
    assign S01_AXI_awvalid = sm_awvalid;
    assign sm_awready = S01_AXI_awready;
    assign S01_AXI_wdata = sm_wdata;
    assign S01_AXI_wlast = sm_wlast;
    assign S01_AXI_wstrb = sm_wstrb;
    assign S01_AXI_wvalid = sm_wvalid;
    assign sm_wready = S01_AXI_wready;
    assign sm_bresp = S01_AXI_bresp;
    assign sm_bvalid = S01_AXI_bvalid;
    assign S01_AXI_bready = sm_bready;

    system_mem_xbar_0 mem_xbar (.*);

    // HP0 AXI3 DDR behavioral endpoint. One read and one write burst may be
    // outstanding; independent AR/AW/W/B stalls are deterministic and finite.
    reg [31:0] ddr_model [0:8191];
    reg hp_read_hold = 0;
    reg M00_AXI_arready_r = 0;
    reg M00_AXI_awready_r = 0;
    reg [31:0] M00_AXI_rdata_r = 0;
    reg [5:0] M00_AXI_rid_r = 0;
    reg M00_AXI_rlast_r = 0;
    reg [1:0] M00_AXI_rresp_r = 0;
    reg M00_AXI_rvalid_r = 0;
    reg [5:0] M00_AXI_bid_r = 0;
    reg [1:0] M00_AXI_bresp_r = 0;
    reg M00_AXI_bvalid_r = 0;
    reg [31:0] rd_addr_q = 0;
    reg [3:0] rd_len_q = 0;
    reg [3:0] rd_index_q = 0;
    reg [0:0] rd_id_q = 0;
    reg rd_active = 0;
    integer rd_wait_q = 0;
    reg rd_seen = 0;
    reg [31:0] wr_addr_q = 0;
    reg [3:0] wr_len_q = 0;
    reg [3:0] wr_index_q = 0;
    reg [0:0] wr_id_q = 0;
    reg wr_active = 0;
    integer wr_wait_q = 0;
    integer b_wait_q = 0;
    reg aw_seen = 0;
    reg wr_b_pending = 0;
    integer cycle_mod = 0;
    reg mismatch = 0;

    assign M00_AXI_arready = M00_AXI_arready_r;
    assign M00_AXI_awready = M00_AXI_awready_r;
    assign M00_AXI_rdata = M00_AXI_rdata_r;
    assign M00_AXI_rid = M00_AXI_rid_r;
    assign M00_AXI_rlast = M00_AXI_rlast_r;
    assign M00_AXI_rresp = M00_AXI_rresp_r;
    assign M00_AXI_rvalid = M00_AXI_rvalid_r;
    assign M00_AXI_bid = M00_AXI_bid_r;
    assign M00_AXI_bresp = M00_AXI_bresp_r;
    assign M00_AXI_bvalid = M00_AXI_bvalid_r;
    assign M00_AXI_wready = wr_active && !M00_AXI_bvalid_r && (cycle_mod != 0);

    always @(posedge clk) begin
        if (!rst_n) begin
            M00_AXI_arready_r <= 0;
            M00_AXI_awready_r <= 0;
            M00_AXI_rdata_r <= 0;
            M00_AXI_rid_r <= 0;
            M00_AXI_rlast_r <= 0;
            M00_AXI_rresp_r <= 0;
            M00_AXI_rvalid_r <= 0;
            M00_AXI_bid_r <= 0;
            M00_AXI_bresp_r <= 0;
            M00_AXI_bvalid_r <= 0;
            rd_active <= 0;
            rd_wait_q <= 0;
            rd_seen <= 0;
            wr_active <= 0;
            wr_wait_q <= 0;
            b_wait_q <= 0;
            aw_seen <= 0;
            wr_b_pending <= 0;
            cycle_mod <= 0;
        end else begin
            memory_model_cycles <= memory_model_cycles + 1;
            cycle_mod <= (cycle_mod == 4) ? 0 : cycle_mod + 1;

            M00_AXI_arready_r <= 0;
            if (!M00_AXI_arvalid) begin
                rd_seen <= 0;
                rd_wait_q <= 0;
            end else if (!rd_active && !rd_seen) begin
                rd_seen <= 1;
                rd_wait_q <= 2;
            end else if (!rd_active) begin
                if (rd_wait_q > 0)
                    rd_wait_q <= rd_wait_q - 1;
                else
                    M00_AXI_arready_r <= 1;
            end
            if (M00_AXI_arvalid && M00_AXI_arready_r) begin
                if (M00_AXI_araddr[1:0] != 0 || M00_AXI_arsize != 3'd2 ||
                    M00_AXI_arburst != 2'b01 || M00_AXI_arlen > 4'd15 ||
                    ((M00_AXI_araddr >> 2) + M00_AXI_arlen + 1) > 8192)
                    begin failure_count = failure_count + 1; $display("FAIL HP0 AR alignment/size/burst/range invalid addr=%08h len=%0d size=%0d burst=%0d", M00_AXI_araddr, M00_AXI_arlen, M00_AXI_arsize, M00_AXI_arburst); end
                rd_addr_q <= M00_AXI_araddr;
                rd_len_q <= M00_AXI_arlen;
                rd_index_q <= 0;
                rd_id_q <= M00_AXI_arid;
                rd_active <= 1;
                rd_wait_q <= 2;
                rd_seen <= 0;
                hp_ar <= hp_ar + 1;
                hp_ar_beats <= hp_ar_beats + M00_AXI_arlen + 1;
            end

            if (rd_active && !hp_read_hold) begin
                if (!M00_AXI_rvalid_r) begin
                    if (rd_wait_q > 0)
                        rd_wait_q <= rd_wait_q - 1;
                    else begin
                        M00_AXI_rdata_r <= ddr_model[(rd_addr_q >> 2) + rd_index_q];
                        M00_AXI_rid_r <= {5'b0, rd_id_q};
                        M00_AXI_rlast_r <= rd_index_q == rd_len_q;
                        M00_AXI_rresp_r <= 0;
                        M00_AXI_rvalid_r <= 1;
                    end
                end else if (M00_AXI_rready) begin
                    hp_r <= hp_r + 1;
                    if (M00_AXI_rlast_r) hp_r_lasts <= hp_r_lasts + 1;
                    M00_AXI_rvalid_r <= 0;
                    if (rd_index_q == rd_len_q) begin
                        rd_active <= 0;
                        rd_index_q <= 0;
                    end else begin
                        rd_index_q <= rd_index_q + 1;
                        rd_wait_q <= 1;
                    end
                end else begin
                    hp_r_stall_cycles <= hp_r_stall_cycles + 1;
                end
            end

            M00_AXI_awready_r <= 0;
            if (!M00_AXI_awvalid) begin
                aw_seen <= 0;
                wr_wait_q <= 0;
            end else if (!wr_active && !wr_b_pending && !aw_seen) begin
                aw_seen <= 1;
                wr_wait_q <= 2;
            end else if (!wr_active && !wr_b_pending) begin
                if (wr_wait_q > 0)
                    wr_wait_q <= wr_wait_q - 1;
                else
                    M00_AXI_awready_r <= 1;
            end
            if (M00_AXI_awvalid && M00_AXI_awready_r) begin
                if (M00_AXI_awaddr[1:0] != 0 || M00_AXI_awsize != 3'd2 ||
                    M00_AXI_awburst != 2'b01 || M00_AXI_awlen > 4'd15 ||
                    ((M00_AXI_awaddr >> 2) + M00_AXI_awlen + 1) > 8192)
                    begin failure_count = failure_count + 1; $display("FAIL HP0 AW alignment/size/burst/range invalid addr=%08h len=%0d size=%0d burst=%0d", M00_AXI_awaddr, M00_AXI_awlen, M00_AXI_awsize, M00_AXI_awburst); end
                wr_addr_q <= M00_AXI_awaddr;
                wr_len_q <= M00_AXI_awlen;
                wr_index_q <= 0;
                wr_id_q <= M00_AXI_awid;
                wr_active <= 1;
                aw_seen <= 0;
                hp_aw <= hp_aw + 1;
                hp_aw_beats <= hp_aw_beats + M00_AXI_awlen + 1;
            end

            if (M00_AXI_wvalid && M00_AXI_wready) begin
                for (integer b = 0; b < 4; b = b + 1)
                    if (M00_AXI_wstrb[b])
                        ddr_model[(wr_addr_q >> 2) + wr_index_q][b*8 +: 8]
                            <= M00_AXI_wdata[b*8 +: 8];
                hp_w <= hp_w + 1;
                if (M00_AXI_wlast != (wr_index_q == wr_len_q)) begin
                    mismatch <= 1;
                    begin failure_count = failure_count + 1; $display("FAIL HP0 WLAST mismatch beat=%0d len=%0d", wr_index_q, wr_len_q); end
                end
                if (M00_AXI_wlast) begin
                    wr_active <= 0;
                    b_wait_q <= 3;
                    wr_b_pending <= 1;
                end else begin
                    wr_index_q <= wr_index_q + 1;
                end
            end else if (M00_AXI_wvalid && !M00_AXI_wready) begin
                hp_w_stall_cycles <= hp_w_stall_cycles + 1;
            end

            if (b_wait_q > 0 && !M00_AXI_bvalid_r)
                b_wait_q <= b_wait_q - 1;
            else if (b_wait_q == 0 && wr_b_pending && !M00_AXI_bvalid_r) begin
                M00_AXI_bid_r <= {5'b0, wr_id_q};
                M00_AXI_bresp_r <= 0;
                M00_AXI_bvalid_r <= 1;
            end
            if (M00_AXI_bvalid_r && M00_AXI_bready) begin
                hp_b <= hp_b + 1;
                M00_AXI_bvalid_r <= 0;
                wr_index_q <= 0;
                wr_len_q <= 0;
                wr_addr_q <= 0;
                wr_b_pending <= 0;
                b_wait_q <= 0;
            end
        end
    end

    always @(posedge clk) begin
        if (rst_n) begin
            if (mm_arvalid && mm_arready) begin
                dma_ar_bursts <= dma_ar_bursts + 1;
                dma_ar_beats <= dma_ar_beats + mm_arlen + 1;
            end
            if (mm_rvalid && mm_rready) begin
                dma_r_beats <= dma_r_beats + 1;
                if (mm_rlast) dma_r_lasts <= dma_r_lasts + 1;
            end
            if (sm_awvalid && sm_awready) begin
                dma_aw_bursts <= dma_aw_bursts + 1;
                dma_aw_beats <= dma_aw_beats + sm_awlen + 1;
            end
            if (sm_wvalid && sm_wready) dma_w_beats <= dma_w_beats + 1;
            if (sm_bvalid && sm_bready) dma_b_responses <= dma_b_responses + 1;
            if (mm_axis_tvalid && mm_axis_tready) begin
                mm2s_beats <= mm2s_beats + 1;
                if (mm_axis_tkeep != 4'hf)
                    begin failure_count = failure_count + 1; $display("FAIL MM2S TKEEP=%h", mm_axis_tkeep); end
                if (mm_axis_tlast)
                    mm2s_tlasts <= mm2s_tlasts + 1;
            end
            if (accel_s2mm_tvalid && accel_s2mm_tready) begin
                s2mm_beats <= s2mm_beats + 1;
                if (accel_s2mm_tkeep != 4'hf)
                    begin failure_count = failure_count + 1; $display("FAIL S2MM TKEEP=%h", accel_s2mm_tkeep); end
                if (accel_s2mm_tlast)
                    s2mm_tlasts <= s2mm_tlasts + 1;
            end
        end
    end

    task fail;
        input [8*160-1:0] msg;
        begin
            failure_count = failure_count + 1;
            $display("FAIL %0s time=%0t", msg, $time);
        end
    endtask

    task dma_write;
        input [9:0] addr;
        input [31:0] data;
        reg aw_done, w_done;
        integer t;
        begin
            @(negedge clk);
            dma_awaddr = addr; dma_wdata = data;
            dma_awvalid = 1; dma_wvalid = 1; dma_bready = 0;
            aw_done = 0; w_done = 0; t = 0;
            while (!(aw_done && w_done) && t < 100) begin
                @(posedge clk);
                if (dma_awvalid && dma_awready) aw_done = 1;
                if (dma_wvalid && dma_wready) w_done = 1;
                @(negedge clk);
                if (aw_done) dma_awvalid = 0;
                if (w_done) dma_wvalid = 0;
                t = t + 1;
            end
            if (!(aw_done && w_done)) fail("DMA AXI-Lite write address/data timeout");
            dma_bready = 1;
            t = 0;
            while (!dma_bvalid && t < 100) begin @(posedge clk); t = t + 1; end
            if (!dma_bvalid || dma_bresp != 0) fail("DMA AXI-Lite write response timeout/error");
            @(negedge clk); dma_bready = 0; dma_writes = dma_writes + 1;
        end
    endtask

    task dma_read;
        input [9:0] addr;
        output [31:0] data;
        integer t;
        begin
            @(negedge clk); dma_araddr = addr; dma_arvalid = 1; dma_rready = 0;
            t = 0;
            while (!dma_arready && t < 100) begin @(posedge clk); t = t + 1; end
            if (!dma_arready) fail("DMA AXI-Lite read address timeout");
            @(negedge clk); dma_arvalid = 0; dma_rready = 1;
            t = 0;
            while (!dma_rvalid && t < 100) begin @(posedge clk); t = t + 1; end
            if (!dma_rvalid || dma_rresp != 0) fail("DMA AXI-Lite read data timeout/error");
            data = dma_rdata;
            @(negedge clk); dma_rready = 0; dma_reads = dma_reads + 1;
        end
    endtask

    task acc_write;
        input [3:0] addr;
        input [31:0] data;
        integer t;
        begin
            @(negedge clk);
            acc_awaddr = addr; acc_wdata = data; acc_wstrb = 4'hf;
            acc_awvalid = 1; acc_wvalid = 1; acc_bready = 1;
            t = 0;
            while (!acc_bvalid && t < 100) begin @(posedge clk); t = t + 1; end
            if (!acc_bvalid || acc_bresp != 0) fail("accelerator AXI-Lite write timeout/error");
            @(negedge clk); acc_awvalid = 0; acc_wvalid = 0; acc_bready = 0;
            cpu_writes = cpu_writes + 1;
        end
    endtask

    task set_core_command;
        input [2:0] opcode;
        input [31:0] r1, seq, fid;
        begin
            acc_write(4'h0, 32'h0); // clear START to guarantee a rising edge for this command.
            acc_write(4'h4, r1);
            acc_write(4'h8, seq);
            acc_write(4'hc, fid);
            acc_write(4'h0, {25'b0, opcode, 4'b0001});
        end
    endtask

    task wait_channel_done;
        input [9:0] status_addr;
        reg [31:0] status;
        integer t;
        begin
            t = 0; status = 0;
            while ((status & 32'h00001002) != 32'h00001002 && t < 3000) begin
                dma_read(status_addr, status); t = t + 1;
            end
            if ((status & 32'h00001002) != 32'h00001002)
                fail("DMA channel completion/idle timeout");
            if (status & 32'h00000770) begin
                $display("DMA status @%03h = %08h", status_addr, status);
                fail("DMA status error bits set");
            end
        end
    endtask

    task run_output_only;
        input [31:0] output_addr;
        input integer bytes;
        input [2:0] opcode;
        input [31:0] r1, seq, fid;
        begin
            dma_write(10'h004, 32'h7000);
            dma_write(10'h034, 32'h7000);
            dma_write(10'h030, 32'h1);
            dma_write(10'h048, output_addr);
            dma_write(10'h058, bytes);
            set_core_command(opcode, r1, seq, fid);
            wait_channel_done(10'h034);
        end
    endtask

    task run_input_output;
        input [31:0] input_addr, output_addr;
        input integer input_bytes, output_bytes;
        input [2:0] opcode;
        input [31:0] r1, seq, fid;
        begin
            dma_write(10'h004, 32'h7000);
            dma_write(10'h034, 32'h7000);
            dma_write(10'h030, 32'h1);
            dma_write(10'h048, output_addr);
            dma_write(10'h058, output_bytes);
            set_core_command(opcode, r1, seq, fid);
            dma_write(10'h000, 32'h1);
            dma_write(10'h018, input_addr);
            dma_write(10'h028, input_bytes);
            wait_channel_done(10'h004);
            wait_channel_done(10'h034);
        end
    endtask

    task set_rx_guard;
        input integer base_word;
        input integer words;
        input [31:0] tag;
        begin
            ddr_model[base_word - 1] = tag;
            ddr_model[base_word + words] = ~tag;
        end
    endtask

    task check_rx_guard;
        input integer base_word;
        input integer words;
        input [31:0] tag;
        begin
            if (ddr_model[base_word - 1] !== tag || ddr_model[base_word + words] !== ~tag)
                fail("S2MM DDR guard overwritten");
        end
    endtask

    task check_header;
        input [31:0] base, seq, fid, r1;
        begin
            if (ddr_model[(base >> 2) + 0] !== 32'h564c0001) fail("response MAGIC mismatch");
            if (ddr_model[(base >> 2) + 1] !== seq) fail("response sequence mismatch");
            if (ddr_model[(base >> 2) + 2] !== fid) fail("response filter mismatch");
            if (ddr_model[(base >> 2) + 3] !== r1) fail("response R1 mismatch");
        end
    endtask

    task reset_dma_only;
        reg [31:0] st_tx, st_rx, cr_tx, cr_rx;
        reg reset_poll_done;
        integer poll_count;
        integer wait_count;
        begin
            // Match XAxiDma_Reset: one TX CR reset write resets the engine;
            // ResetIsDone then observes both channel CR self-clear bits.
            acc_write(4'h0, 32'h2);
            if (acc_reg0[1] !== 1'b1) fail("ABORT did not remain asserted");
            dma_write(10'h000, 32'h4);
            poll_count = 0; wait_count = 0; st_tx = 0; st_rx = 0; cr_tx = 32'h4; cr_rx = 32'h4;
            reset_poll_done = 0;
            fork
                begin
                    // Bounded R release runs concurrently with firmware-style
                    // register polling. The fence is checked at poll success.
                    repeat (40) @(posedge clk);
                    hp_read_hold = 0;
                end
                begin
                    while (poll_count < 3000) begin
                        dma_read(10'h004, st_tx);
                        dma_read(10'h034, st_rx);
                        dma_read(10'h000, cr_tx);
                        dma_read(10'h030, cr_rx);
                        if ((st_tx & 1) && (st_rx & 1) &&
                            !(st_tx & 32'h770) && !(st_rx & 32'h770) &&
                            !(cr_tx & 32'h4) && !(cr_rx & 32'h4))
                            poll_count = 3000;
                        else
                            poll_count = poll_count + 1;
                    end
                    if (!(st_tx & 1) || !(st_rx & 1) ||
                        (st_tx & 32'h770) || (st_rx & 32'h770) ||
                        (cr_tx & 32'h4) || (cr_rx & 32'h4)) begin
                        fail("DMA-only soft reset did not clear both reset bits and reach HALTED/error-free state");
                    end else begin
                        $display("COVERAGE reset_fence dma_ar_beats=%0d dma_r_beats=%0d dma_r_last=%0d hp0_ar_beats=%0d hp0_r_beats=%0d hp0_r_last=%0d dma_aw=%0d/%0d dma_w=%0d dma_b=%0d hp0_aw=%0d/%0d hp0_w=%0d hp0_b=%0d rd_active=%0d rvalid=%0d",
                            dma_ar_beats-base_dma_ar_beats, dma_r_beats-base_dma_r_beats,
                            dma_r_lasts-base_dma_r_lasts, hp_ar_beats-base_hp_ar_beats,
                            hp_r-base_r, hp_r_lasts-base_hp_r_lasts,
                            dma_aw_bursts-base_dma_aw_bursts, dma_aw_beats-base_dma_aw_beats,
                            dma_w_beats-base_dma_w_beats, dma_b_responses-base_dma_b_responses,
                            hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats,
                            hp_w-base_hp_w, hp_b-base_hp_b, rd_active, M00_AXI_rvalid_r);
                        if (dma_ar_beats-base_dma_ar_beats != dma_r_beats-base_dma_r_beats)
                            fail("software fence has unmatched DMA-side MM2S AR/R beats");
                        if (dma_ar_bursts-base_dma_ar_bursts != dma_r_lasts-base_dma_r_lasts)
                            fail("software fence has unmatched DMA-side MM2S AR/RLAST bursts");
                        if (hp_ar_beats-base_hp_ar_beats != hp_r-base_r ||
                            hp_ar-base_ar != hp_r_lasts-base_hp_r_lasts)
                            fail("software fence has unmatched HP0 AR/R beats or RLASTs");
                        if (dma_ar_beats-base_dma_ar_beats != hp_ar_beats-base_hp_ar_beats ||
                            dma_r_beats-base_dma_r_beats != hp_r-base_r)
                            fail("software fence has MM2S traffic buffered between DMA and HP0");
                        if (rd_active || M00_AXI_rvalid_r)
                            fail("software fence reached with HP0 read response outstanding");
                        if (dma_aw_beats-base_dma_aw_beats != dma_w_beats-base_dma_w_beats ||
                            dma_aw_bursts-base_dma_aw_bursts != dma_b_responses-base_dma_b_responses)
                            fail("software fence has unmatched DMA-side S2MM AW/W/B");
                        if (hp_aw_beats-base_hp_aw_beats != hp_w-base_hp_w ||
                            hp_aw-base_hp_aw != hp_b-base_hp_b)
                            fail("software fence has unmatched HP0 AW/W/B");
                        if (dma_aw_beats-base_dma_aw_beats != hp_aw_beats-base_hp_aw_beats ||
                            dma_w_beats-base_dma_w_beats != hp_w-base_hp_w ||
                            dma_b_responses-base_dma_b_responses != hp_b-base_hp_b)
                            fail("software fence has S2MM traffic buffered between DMA and HP0");
                        if (wr_active || wr_b_pending || M00_AXI_bvalid_r)
                            fail("software fence reached with HP0 write response outstanding");
                    end
                    reset_poll_done = 1;
                end
            join_none
            wait_count = 0;
            while (!reset_poll_done && wait_count < 4000) begin
                @(posedge clk); wait_count = wait_count + 1;
            end
            if (!reset_poll_done) fail("DMA reset poll/fence synchronization timeout");
            if (failure_count == 0) acc_write(4'h0, 32'h0);
        end
    endtask

    task wait_read_outstanding;
        integer t;
        begin
            t = 0;
            while (!rd_active && t < 1000) begin @(posedge clk); t = t + 1; end
            if (!rd_active) fail("HP0 read request was not accepted");
        end
    endtask

    reg [31:0] readback;
    integer t;
    reg [31:0] r1_load, r1_run;
    reg [31:0] seq_probe, seq_load, seq_run, fid;
    initial begin
        // Initial source vectors: tile64 T=1, L=1; 64 bias words then 16
        // packed weight words. Reference output is bias[0] + signed(act)*w[0].
        for (i = 0; i < 8192; i = i + 1) ddr_model[i] = 0;
        for (i = 0; i < 64; i = i + 1) ddr_model[1024 + i] = (i == 0) ? 7 : 0;
        for (i = 0; i < 16; i = i + 1) ddr_model[1088 + i] = (i == 0) ? 32'h00000003 : 0;
        ddr_model[2048 + 0] = 32'h00000005;
        ddr_model[2048 + 1] = 32'h000000fd;
        ddr_model[2048 + 2] = 32'h00000007;
        ddr_model[2048 + 3] = 32'h00000002;
        set_rx_guard(4096, 5, 32'hc01d0001);
        set_rx_guard(4160, 5, 32'hc01d0002);
        set_rx_guard(4224, 9, 32'hc01d0003);
        set_rx_guard(4288, 5, 32'hc01d0004);
        set_rx_guard(4352, 9, 32'hc01d0005);
        r1_load = 32'h00010001;
        r1_run = 32'h04010001;
        seq_probe = 32'h10203040;
        seq_load = 32'h55667788;
        seq_run = 32'ha0b0c0d0;
        fid = 32'h00c0ffee;

        repeat (32) @(posedge clk); // All external reset domains low for 32 edges.
        rst_n = 1;
        repeat (20) @(posedge clk); // >=16 active clock edges for global release.

        // PROBE response: no MM2S transfer, 5 words/20 bytes to DDR.
        run_output_only(32'h00004000, 20, 0, 0, seq_probe, fid);
        check_header(32'h00004000, seq_probe, fid, 0);
        check_rx_guard(4096, 5, 32'hc01d0001);
        if (ddr_model[4100] !== 0) fail("PROBE status trailer not zero");
        if (s2mm_tlasts != 1) fail("PROBE response TLAST count mismatch");
        if ($test$plusargs("PROBE_ONLY")) begin
            if (failure_count != 0) begin $display("FAIL stage probe failure_count=%0d", failure_count); $finish; end
            $display("COVERAGE probe cpu_writes=%0d dma_lite_writes=%0d dma_lite_reads=%0d", cpu_writes, dma_writes, dma_reads);
            $display("COVERAGE probe s2mm_beats=%0d s2mm_tlast=%0d hp_aw=%0d hp_w=%0d hp_b=%0d w_stalls=%0d", s2mm_beats, s2mm_tlasts, hp_aw, hp_w, hp_b, hp_w_stall_cycles);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr");
            $display("PASS z100 DMA integration PROBE_ONLY");
            $finish;
        end

        // LOAD consumes 64 bias plus 16 weight words through real MM2S/xbar.
        run_input_output(32'h00001000, 32'h00004100, 320, 20, 1,
                         r1_load, seq_load, fid);
        check_header(32'h00004100, seq_load, fid, r1_load);
        check_rx_guard(4160, 5, 32'hc01d0002);
        if (ddr_model[4164] !== 0) fail("LOAD status trailer not zero");
        if (mm2s_tlasts != 1) fail("LOAD input TLAST count mismatch");
        if (s2mm_tlasts != 2) fail("LOAD response TLAST count mismatch");

        // RUN uses the loaded filter: four signed activations produce exact
        // outputs from the legacy tile64 reference equation in stress test.
        run_input_output(32'h00002000, 32'h00004200, 16, 36, 2,
                         r1_run, seq_run, fid);
        check_header(32'h00004200, seq_run, fid, r1_run);
        check_rx_guard(4224, 9, 32'hc01d0003);
        if (ddr_model[4228] !== 22) fail("RUN site0 reference mismatch");
        if (ddr_model[4229] !== -2) fail("RUN site1 reference mismatch");
        if (ddr_model[4230] !== 28) fail("RUN site2 reference mismatch");
        if (ddr_model[4231] !== 13) fail("RUN site3 reference mismatch");
        if (ddr_model[4232] !== 0) fail("RUN status trailer not zero");
        if (mm2s_tlasts != 2) fail("RUN input TLAST count mismatch");
        if (s2mm_tlasts != 3) fail("RUN response TLAST count mismatch");

        if ($test$plusargs("NORMAL_ONLY")) begin
            if (failure_count != 0) begin $display("FAIL stage normal failure_count=%0d", failure_count); $finish; end
            $display("COVERAGE normal cpu_writes=%0d dma_lite_writes=%0d dma_lite_reads=%0d", cpu_writes, dma_writes, dma_reads);
            $display("COVERAGE normal mm2s_beats=%0d mm2s_tlast=%0d s2mm_beats=%0d s2mm_tlast=%0d", mm2s_beats, mm2s_tlasts, s2mm_beats, s2mm_tlasts);
            $display("COVERAGE normal hp_ar=%0d hp_r=%0d hp_aw=%0d hp_w=%0d hp_b=%0d r_stalls=%0d w_stalls=%0d", hp_ar, hp_r, hp_aw, hp_w, hp_b, hp_r_stall_cycles, hp_w_stall_cycles);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr");
            $display("PASS z100 DMA integration NORMAL_ONLY");
            $finish;
        end
        // Recovery probe: leave an accepted MM2S request's R response delayed,
        // ABORT the core, reset DMA channels only, return the old external
        // burst while xbar/slice/DDR remain live, then prove full LOAD/RUN reload.
        base_ar = hp_ar; base_r = hp_r; base_w = hp_w;
        base_dma_ar_bursts = dma_ar_bursts; base_dma_ar_beats = dma_ar_beats;
        base_dma_r_beats = dma_r_beats; base_dma_r_lasts = dma_r_lasts;
        base_dma_aw_bursts = dma_aw_bursts; base_dma_aw_beats = dma_aw_beats;
        base_dma_w_beats = dma_w_beats; base_dma_b_responses = dma_b_responses;
        base_hp_ar_beats = hp_ar_beats; base_hp_r_lasts = hp_r_lasts;
        base_hp_aw = hp_aw; base_hp_aw_beats = hp_aw_beats;
        base_hp_w = hp_w; base_hp_b = hp_b;
        hp_read_hold = 1;
        acc_write(4'h0, 32'h2); // held core ABORT before DMA starts.
        dma_write(10'h004, 32'h7000);
        dma_write(10'h034, 32'h7000);
        dma_write(10'h000, 32'h1);
        dma_write(10'h018, 32'h00001000);
        dma_write(10'h028, 320);
        wait_read_outstanding();
        repeat (5) @(posedge clk);
        if (!rd_active || hp_r != base_r) fail("R delay/outstanding precondition lost");
        reset_dma_only();
        if (!rst_n) fail("DMA-only recovery unexpectedly changed external reset");
        if (failure_count != 0) begin
            $display("FAIL stage dma_reset_fence failure_count=%0d; reload withheld", failure_count);
            $finish;
        end
        if (hp_read_hold || rd_active || M00_AXI_rvalid_r)
            fail("DMA-only software fence completed before bounded external return closed");

        // Reprogram and fully reload after clearing accelerator and DMA state.
        // For this cleanup phase, global core reset is deliberately avoided;
        // actual firmware's DMA-only reset above is the recovery under test.
        run_input_output(32'h00001000, 32'h00004300, 320, 20, 1,
                         r1_load, 32'h89abcdef, fid);
        check_header(32'h00004300, 32'h89abcdef, fid, r1_load);
        check_rx_guard(4288, 5, 32'hc01d0004);
        if (ddr_model[4292] !== 0) fail("reloaded LOAD status trailer not zero");
        run_input_output(32'h00002000, 32'h00004400, 16, 36, 2,
                         r1_run, 32'h76543210, fid);
        check_header(32'h00004400, 32'h76543210, fid, r1_run);
        check_rx_guard(4352, 9, 32'hc01d0005);
        if (ddr_model[4356] !== 22 || ddr_model[4357] !== -2 ||
            ddr_model[4358] !== 28 || ddr_model[4359] !== 13 || ddr_model[4360] !== 0)
            fail("reloaded RUN reference/status mismatch");

        // Final normal DMA status and modeled protocol accounting.
        dma_read(10'h004, readback);
        if (!(readback & 32'h1002) || (readback & 32'h770)) fail("MM2S completion register mismatch");
        dma_read(10'h034, readback);
        if (!(readback & 32'h1002) || (readback & 32'h770)) fail("S2MM completion register mismatch");
        if (mismatch) fail("HP0 model observed protocol mismatch");
        if (hp_ar < 10 || hp_r < hp_ar || hp_aw < 5 || hp_w < hp_aw || hp_b < hp_aw)
            fail("HP0 address/data/response coverage incomplete");
        if (hp_w_stall_cycles == 0)
            fail("deterministic W backpressure coverage missing");
        // RVALID&&!RREADY is not modeled as a stall here; the reset scenario
        // separately proves held R delay and exact closure at the software fence.
        if (accel_task_finish !== 1'b1 && s2mm_tlasts < 5)
            fail("accelerator finish/TLAST coverage incomplete");

        if (failure_count != 0) begin $display("FAIL stage full failure_count=%0d", failure_count); $finish; end
        $display("COVERAGE cpu_writes=%0d dma_lite_writes=%0d dma_lite_reads=%0d", cpu_writes, dma_writes, dma_reads);
        $display("COVERAGE mm2s_beats=%0d mm2s_tlast=%0d s2mm_beats=%0d s2mm_tlast=%0d", mm2s_beats, mm2s_tlasts, s2mm_beats, s2mm_tlasts);
        $display("COVERAGE hp_ar=%0d hp_r=%0d hp_aw=%0d hp_w=%0d hp_b=%0d r_stalls=%0d w_stalls=%0d", hp_ar, hp_r, hp_aw, hp_w, hp_b, hp_r_stall_cycles, hp_w_stall_cycles);
        $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr");
        $display("PASS z100 DMA integration and DMA-only recovery");
        $finish;
    end

    initial begin
        repeat (2000000) @(posedge clk);
        failure_count = failure_count + 1;
        $display("FAIL global simulation timeout cycles=2000000");
        $finish;
    end
endmodule
