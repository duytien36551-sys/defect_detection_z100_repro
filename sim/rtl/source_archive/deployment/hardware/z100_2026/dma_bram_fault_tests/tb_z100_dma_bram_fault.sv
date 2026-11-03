`timescale 1ns/1ps

// Offline integration harness for the pinned Z100 simulation sources.
// system_axi_dma_0_0, both generated auto_pc wrappers, system_mem_xbar_0,
// system_mm2s_response_slice_0, and system_yolo_accel_top_0_0 are the actual
// exported Vivado simulation models. The AXI-Lite masters and HP0 AXI3 DDR
// endpoint below are behavioral testbench models; they are not PS7 or DDR.
module tb_z100_dma_bram_fault;
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
    integer dma_s2mm_w_stall_cycles = 0;
    integer s2mm_core_axis_beats = 0;
    integer s2mm_core_axis_tlasts = 0;
    integer s2mm_dma_axis_beats = 0;
    integer s2mm_dma_axis_tlasts = 0;
    integer s2mm_axis_stall_cycles = 0;
    integer axis_abort_cancel_count = 0;
    // Test-only MM2S interposers. Both ends see exactly the same handshakes.
    reg mm_axis_hold = 0, mm_axis_arm = 0, read_return_hold = 0;
    integer mm_axis_target = 0, mm_core_beats = 0, mm_core_lasts = 0;
    integer mm_slice_stalls = 0, mm_axis_stalls = 0;
    integer hp_read_errors = 0, dma_read_errors = 0;
    reg [1:0] read_error_code = 0, hp_read_error_last = 0, dma_read_error_last = 0;
    integer hp_pause_after = -1;
    reg keep_read_error_across_reset = 0;
    reg retained_enable [0:1];
    reg [31:0] retained_rx [0:9];
    reg [31:0] retained_tx [0:159];
    reg prev_mm_stall = 0, prev_slice_stall = 0;
    reg [31:0] prev_mm_data = 0, prev_slice_data = 0;
    reg [3:0] prev_mm_keep = 0;
    reg prev_mm_last = 0, prev_slice_last = 0;
    reg [1:0] prev_slice_resp = 0;
    integer s2mm_axis_hold_target = 0;
    integer hp_bresp_error_responses = 0;
    integer dma_bresp_error_responses = 0;
    integer base_s2mm_core_axis_beats, base_s2mm_core_axis_tlasts;
    integer base_s2mm_dma_axis_beats, base_s2mm_dma_axis_tlasts;
    integer base_hp_bresp_error_responses, base_dma_bresp_error_responses;
    reg [1:0] hp_bresp_error_last = 0;
    reg [1:0] dma_bresp_error_last = 0;
    reg reset_status_clean = 0;
    reg reset_fence_clean = 0;
    reg reset_abort_released = 0;
    reg axis_stream_hold = 0;
    reg axis_hold_armed = 0;
    reg hp_bresp_error = 0;
    reg prev_s2mm_axis_stall = 0;
    reg [31:0] prev_s2mm_axis_data = 0;
    reg [3:0] prev_s2mm_axis_keep = 0;
    reg prev_s2mm_axis_last = 0;
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
    integer t;
    integer old_rx_base = 0;
    reg [31:0] readback;
    reg [31:0] r1_load, r1_run;
    reg [31:0] seq_probe, seq_load, seq_run, fid;

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
    wire core_mm_valid = mm_axis_tvalid && !mm_axis_hold;
    wire core_mm_ready;
    assign mm_axis_tready = core_mm_ready && !mm_axis_hold;
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
    wire [31:0] dma_s2mm_tdata;
    wire [3:0] dma_s2mm_tkeep;
    wire dma_s2mm_tvalid;
    wire dma_s2mm_tready;
    wire dma_s2mm_tlast;
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
        .s_axis_s2mm_tdata(dma_s2mm_tdata),
        .s_axis_s2mm_tkeep(dma_s2mm_tkeep),
        .s_axis_s2mm_tvalid(dma_s2mm_tvalid),
        .s_axis_s2mm_tready(dma_s2mm_tready),
        .s_axis_s2mm_tlast(dma_s2mm_tlast),
        .mm2s_introut(mm2s_introut), .s2mm_introut(s2mm_introut),
        .axi_dma_tstvec(dma_tstvec)
    );

    // A test-only interposer models an AXIS sink that withholds acceptance.
    // It gates both source TVALID into the DMA and returned TREADY to the core.
    assign dma_s2mm_tdata = accel_s2mm_tdata;
    assign dma_s2mm_tkeep = accel_s2mm_tkeep;
    assign dma_s2mm_tlast = accel_s2mm_tlast;
    assign dma_s2mm_tvalid = accel_s2mm_tvalid && !axis_stream_hold;
    assign accel_s2mm_tready = dma_s2mm_tready && !axis_stream_hold;

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
        .s_axis_mm2s_tkeep(mm_axis_tkeep), .s_axis_mm2s_tvalid(core_mm_valid),
        .s_axis_mm2s_tready(core_mm_ready), .s_axis_mm2s_tlast(mm_axis_tlast),
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
    assign mm_rvalid = slice_s_rvalid && !read_return_hold;
    assign slice_s_rready = mm_rready && !read_return_hold;

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
    reg old_rx_sentinel_enable = 0;
    reg old_rx_sentinel_violation = 0;
    reg old_tx_poison_enable = 0;
    reg old_tx_poison_violation = 0;
    reg [31:0] old_rx_sentinel [0:4];
    reg [31:0] old_tx_poison [0:79];
    reg hp_read_hold = 0;
    reg hp_write_data_hold = 0;
    integer hp_write_hold_after = -1;
    reg hp_bresp_hold = 0;
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
    reg prev_aw_stall = 0, prev_w_stall = 0, prev_r_stall = 0, prev_b_stall = 0;
    reg [31:0] prev_awaddr = 0, prev_wdata = 0, prev_rdata = 0;
    reg [3:0] prev_awlen = 0, prev_wstrb = 0;
    reg [0:0] prev_awid = 0, prev_wid = 0;
    reg [5:0] prev_rid = 0, prev_bid = 0;
    reg [2:0] prev_awsize = 0;
    reg [1:0] prev_awburst = 0, prev_rresp = 0, prev_bresp = 0;
    reg prev_wlast = 0, prev_rlast = 0;
    reg prev_dma_s2mm_w_stall = 0;
    reg [31:0] prev_dma_s2mm_wdata = 0;
    reg [3:0] prev_dma_s2mm_wstrb = 0;
    reg prev_dma_s2mm_wlast = 0;

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
    assign M00_AXI_wready = wr_active && !M00_AXI_bvalid_r && (cycle_mod != 0) &&
        !hp_write_data_hold && (hp_write_hold_after < 0 || hp_w < hp_write_hold_after);

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
                if (rd_active || M00_AXI_rvalid_r)
                    begin failure_count = failure_count + 1; $display("FAIL HP0 accepted AR while read slot occupied"); end
                M00_AXI_arready_r <= 0;
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

            if (rd_active && (!hp_read_hold || M00_AXI_rvalid_r)) begin
                if (!M00_AXI_rvalid_r) begin
                    if (rd_wait_q > 0)
                        rd_wait_q <= rd_wait_q - 1;
                    else if (hp_pause_after < 0 || hp_r < hp_pause_after) begin
                        M00_AXI_rdata_r <= ddr_model[(rd_addr_q >> 2) + rd_index_q];
                        M00_AXI_rid_r <= {5'b0, rd_id_q};
                        M00_AXI_rlast_r <= rd_index_q == rd_len_q;
                        M00_AXI_rresp_r <= read_error_code;
                        M00_AXI_rvalid_r <= 1;
                    end
                end else if (M00_AXI_rready) begin
                    if (M00_AXI_rresp_r != 0) begin
                        hp_read_errors <= hp_read_errors + 1;
                        hp_read_error_last <= M00_AXI_rresp_r;
                    end
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
                if (wr_active || wr_b_pending || M00_AXI_bvalid_r)
                    begin failure_count = failure_count + 1; $display("FAIL HP0 accepted AW while write slot occupied"); end
                M00_AXI_awready_r <= 0;
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
            else if (b_wait_q == 0 && wr_b_pending && !M00_AXI_bvalid_r && !hp_bresp_hold) begin
                M00_AXI_bid_r <= {5'b0, wr_id_q};
                M00_AXI_bresp_r <= hp_bresp_error ? 2'b10 : 2'b00;
                M00_AXI_bvalid_r <= 1;
            end
            if (M00_AXI_bvalid_r && M00_AXI_bready) begin
                if (M00_AXI_bresp_r != 2'b00) begin
                    hp_bresp_error_responses <= hp_bresp_error_responses + 1;
                    hp_bresp_error_last <= M00_AXI_bresp_r;
                end
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
        if (rst_n && old_rx_sentinel_enable && !old_rx_sentinel_violation) begin
            for (integer k = 0; k < 5; k = k + 1) begin
                if (ddr_model[old_rx_base+k] !== old_rx_sentinel[k]) begin
                    old_rx_sentinel_violation = 1;
                    failure_count = failure_count + 1;
                    $display("FAIL late HP0 write changed released RX word=%0d data=%08h expected=%08h",
                        old_rx_base+k, ddr_model[old_rx_base+k], old_rx_sentinel[k]);
                end
            end
        end
        if (rst_n && old_tx_poison_enable && !old_tx_poison_violation) begin
            for (integer k = 0; k < 80; k = k + 1) begin
                if (ddr_model[1024+k] !== old_tx_poison[k]) begin
                    old_tx_poison_violation = 1;
                    failure_count = failure_count + 1;
                    $display("FAIL old TX source changed after reset word=%0d data=%08h expected=%08h",
                        1024+k, ddr_model[1024+k], old_tx_poison[k]);
                end
            end
            if (M00_AXI_arvalid && M00_AXI_arready &&
                M00_AXI_araddr >= 32'h00001000 && M00_AXI_araddr < 32'h00001140) begin
                old_tx_poison_violation = 1;
                failure_count = failure_count + 1;
                $display("FAIL late HP0 read reused poisoned TX address=%08h", M00_AXI_araddr);
            end
        end
    end

    // AXI VALID and payload must remain stable until the receiver accepts them.
    always @(posedge clk) begin
        if (!rst_n) begin
            prev_aw_stall <= 0; prev_w_stall <= 0;
            prev_r_stall <= 0; prev_b_stall <= 0;
            prev_dma_s2mm_w_stall <= 0;
            prev_s2mm_axis_stall <= 0;
        end else begin
            if (prev_aw_stall && (!M00_AXI_awvalid || M00_AXI_awaddr !== prev_awaddr ||
                M00_AXI_awlen !== prev_awlen || M00_AXI_awid !== prev_awid ||
                M00_AXI_awsize !== prev_awsize || M00_AXI_awburst !== prev_awburst)) begin
                failure_count = failure_count + 1;
                $display("FAIL HP0 AWVALID/payload changed before AWREADY");
            end
            if (prev_w_stall && (!M00_AXI_wvalid || M00_AXI_wdata !== prev_wdata ||
                M00_AXI_wstrb !== prev_wstrb || M00_AXI_wlast !== prev_wlast || M00_AXI_wid !== prev_wid)) begin
                failure_count = failure_count + 1;
                $display("FAIL HP0 WVALID/payload changed before WREADY");
            end
            if (prev_r_stall && (!M00_AXI_rvalid_r || M00_AXI_rdata_r !== prev_rdata ||
                M00_AXI_rid_r !== prev_rid || M00_AXI_rlast_r !== prev_rlast || M00_AXI_rresp_r !== prev_rresp)) begin
                failure_count = failure_count + 1;
                $display("FAIL HP0 RVALID/payload changed before RREADY");
            end
            if (prev_b_stall && (!M00_AXI_bvalid_r || M00_AXI_bid_r !== prev_bid ||
                M00_AXI_bresp_r !== prev_bresp)) begin
                failure_count = failure_count + 1;
                $display("FAIL HP0 BVALID/payload changed before BREADY");
            end
            if (prev_dma_s2mm_w_stall && (!sm_wvalid || sm_wdata !== prev_dma_s2mm_wdata ||
                sm_wstrb !== prev_dma_s2mm_wstrb || sm_wlast !== prev_dma_s2mm_wlast)) begin
                failure_count = failure_count + 1;
                $display("FAIL DMA S2MM WVALID/payload changed before WREADY");
            end
            if (prev_s2mm_axis_stall && (!accel_s2mm_tvalid ||
                accel_s2mm_tdata !== prev_s2mm_axis_data ||
                accel_s2mm_tkeep !== prev_s2mm_axis_keep ||
                accel_s2mm_tlast !== prev_s2mm_axis_last)) begin
                if (acc_reg0[1] === 1'b1) begin
                    axis_abort_cancel_count <= axis_abort_cancel_count + 1;
                    $display("COVERAGE axis_abort_cancel time=%0t acc_reg0=%08h old_data=%08h old_keep=%h old_last=%0d new_valid=%0d new_data=%08h new_keep=%h new_last=%0d count=%0d",
                        $time, acc_reg0, prev_s2mm_axis_data, prev_s2mm_axis_keep,
                        prev_s2mm_axis_last, accel_s2mm_tvalid, accel_s2mm_tdata,
                        accel_s2mm_tkeep, accel_s2mm_tlast, axis_abort_cancel_count+1);
                end else begin
                    failure_count = failure_count + 1;
                    $display("FAIL accelerator S2MM TVALID/payload changed before core-side TREADY and before confirmed ABORT");
                end
            end
            prev_aw_stall <= M00_AXI_awvalid && !M00_AXI_awready;
            prev_w_stall <= M00_AXI_wvalid && !M00_AXI_wready;
            prev_r_stall <= M00_AXI_rvalid_r && !M00_AXI_rready;
            prev_b_stall <= M00_AXI_bvalid_r && !M00_AXI_bready;
            prev_dma_s2mm_w_stall <= sm_wvalid && !sm_wready;
            prev_s2mm_axis_stall <= accel_s2mm_tvalid && !accel_s2mm_tready;
            if (sm_wvalid && !sm_wready) dma_s2mm_w_stall_cycles <= dma_s2mm_w_stall_cycles + 1;
            if (accel_s2mm_tvalid && !accel_s2mm_tready) s2mm_axis_stall_cycles <= s2mm_axis_stall_cycles + 1;
            if (M00_AXI_awvalid && !M00_AXI_awready) begin
                prev_awaddr <= M00_AXI_awaddr; prev_awlen <= M00_AXI_awlen;
                prev_awid <= M00_AXI_awid; prev_awsize <= M00_AXI_awsize;
                prev_awburst <= M00_AXI_awburst;
            end
            if (M00_AXI_wvalid && !M00_AXI_wready) begin
                prev_wdata <= M00_AXI_wdata; prev_wstrb <= M00_AXI_wstrb;
                prev_wlast <= M00_AXI_wlast; prev_wid <= M00_AXI_wid;
            end
            if (M00_AXI_rvalid_r && !M00_AXI_rready) begin
                prev_rdata <= M00_AXI_rdata_r; prev_rid <= M00_AXI_rid_r;
                prev_rlast <= M00_AXI_rlast_r; prev_rresp <= M00_AXI_rresp_r;
            end
            if (M00_AXI_bvalid_r && !M00_AXI_bready) begin
                prev_bid <= M00_AXI_bid_r; prev_bresp <= M00_AXI_bresp_r;
            end
            if (sm_wvalid && !sm_wready) begin
                prev_dma_s2mm_wdata <= sm_wdata;
                prev_dma_s2mm_wstrb <= sm_wstrb;
                prev_dma_s2mm_wlast <= sm_wlast;
            end
            if (accel_s2mm_tvalid && !accel_s2mm_tready) begin
                prev_s2mm_axis_data <= accel_s2mm_tdata;
                prev_s2mm_axis_keep <= accel_s2mm_tkeep;
                prev_s2mm_axis_last <= accel_s2mm_tlast;
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
            if (sm_bvalid && sm_bready) begin
                dma_b_responses <= dma_b_responses + 1;
                if (sm_bresp != 2'b00) begin
                    dma_bresp_error_responses <= dma_bresp_error_responses + 1;
                    dma_bresp_error_last <= sm_bresp;
                end
            end
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
                s2mm_core_axis_beats <= s2mm_core_axis_beats + 1;
                if (accel_s2mm_tlast)
                    s2mm_core_axis_tlasts <= s2mm_core_axis_tlasts + 1;
            end
            if (dma_s2mm_tvalid && dma_s2mm_tready) begin
                s2mm_dma_axis_beats <= s2mm_dma_axis_beats + 1;
                if (dma_s2mm_tlast)
                    s2mm_dma_axis_tlasts <= s2mm_dma_axis_tlasts + 1;
                if (axis_hold_armed &&
                    s2mm_dma_axis_beats + 1 == s2mm_axis_hold_target) begin
                    axis_stream_hold <= 1;
                    axis_hold_armed <= 0;
                    $display("COVERAGE axis_hold_engaged time=%0t target_dma_beats=%0d core_beats=%0d dma_beats=%0d core_tlast=%0d dma_tlast=%0d",
                        $time, s2mm_axis_hold_target,
                        s2mm_core_axis_beats + 1, s2mm_dma_axis_beats + 1,
                        s2mm_core_axis_tlasts, s2mm_dma_axis_tlasts);
                end
            end
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            prev_mm_stall <= 0; prev_slice_stall <= 0;
        end else begin
            if ((mm_axis_tvalid && mm_axis_tready) !== (core_mm_valid && core_mm_ready))
                fail("MM2S interposer handshake disagreement");
            if (core_mm_valid && core_mm_ready) begin
                mm_core_beats <= mm_core_beats + 1;
                if (mm_axis_tlast) mm_core_lasts <= mm_core_lasts + 1;
                if (mm_axis_arm && mm_core_beats + 1 == mm_axis_target) begin
                    mm_axis_hold <= 1; mm_axis_arm <= 0;
                end
            end
            // The DMA may terminate AXIS during its own reset. ABORT alone
            // does not exempt DMA VALID/payload stability from this assertion.
            if (prev_mm_stall && mm2s_reset_out_n &&
                (!mm_axis_tvalid || mm_axis_tdata !== prev_mm_data ||
                 mm_axis_tkeep !== prev_mm_keep || mm_axis_tlast !== prev_mm_last))
                fail("MM2S AXIS changed while stalled outside DMA reset");
            prev_mm_stall <= mm_axis_tvalid && !mm_axis_tready && mm2s_reset_out_n;
            if (mm_axis_tvalid && !mm_axis_tready) begin
                mm_axis_stalls <= mm_axis_stalls + 1;
                prev_mm_data <= mm_axis_tdata; prev_mm_keep <= mm_axis_tkeep;
                prev_mm_last <= mm_axis_tlast;
            end
            // The real response slice is never reset during these cases.
            if (prev_slice_stall && (!slice_s_rvalid || slice_s_rdata !== prev_slice_data ||
                slice_s_rresp !== prev_slice_resp || slice_s_rlast !== prev_slice_last))
                fail("Actual read slice RVALID/payload changed while stalled");
            prev_slice_stall <= slice_s_rvalid && !slice_s_rready;
            if (slice_s_rvalid && !slice_s_rready) begin
                mm_slice_stalls <= mm_slice_stalls + 1;
                prev_slice_data <= slice_s_rdata; prev_slice_resp <= slice_s_rresp;
                prev_slice_last <= slice_s_rlast;
            end
            if (mm_rvalid && mm_rready && mm_rresp != 0) begin
                dma_read_errors <= dma_read_errors + 1;
                dma_read_error_last <= mm_rresp;
            end
        end
    end

    always @(posedge clk) begin
        if (rst_n) begin
            for (integer slot = 0; slot < 2; slot = slot + 1) begin
                if (retained_enable[slot]) begin
                    for (integer k = 0; k < 5; k = k + 1)
                        if (ddr_model[6144+slot*64+k] !== retained_rx[slot*5+k])
                            fail("Repeated recovery late write changed released RX");
                    for (integer k = 0; k < 80; k = k + 1)
                        if (ddr_model[1024+slot*128+k] !== retained_tx[slot*80+k])
                            fail("Repeated recovery changed poisoned TX");
                    if (M00_AXI_arvalid && M00_AXI_arready &&
                        M00_AXI_araddr >= 32'h1000+slot*512 &&
                        M00_AXI_araddr < 32'h1140+slot*512)
                        fail("Repeated recovery read from released old TX");
                end
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

    task acc_read;
        input [3:0] addr;
        output [31:0] data;
        integer t;
        begin
            @(negedge clk); acc_araddr = addr; acc_arvalid = 1; acc_rready = 0;
            t = 0;
            while (!acc_arready && t < 100) begin @(posedge clk); t = t + 1; end
            if (!acc_arready) fail("accelerator AXI-Lite read address timeout");
            @(negedge clk); acc_arvalid = 0; acc_rready = 1;
            t = 0;
            while (!acc_rvalid && t < 100) begin @(posedge clk); t = t + 1; end
            if (!acc_rvalid || acc_rresp != 0) fail("accelerator AXI-Lite read data timeout/error");
            data = acc_rdata;
            @(negedge clk); acc_rready = 0;
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

    task start_output_only;
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

    task arm_old_rx_sentinel;
        integer k;
        begin
            old_rx_sentinel_violation = 0;
            for (k = 0; k < 5; k = k + 1) begin
                old_rx_sentinel[k] = 32'hdeca0000 + k;
                ddr_model[old_rx_base+k] = old_rx_sentinel[k];
            end
            old_rx_sentinel_enable = 1;
            $display("COVERAGE old_rx_sentinel base=%0d words=5 armed=1", old_rx_base);
        end
    endtask

    task check_old_rx_sentinel;
        integer k;
        begin
            for (k = 0; k < 5; k = k + 1)
                if (ddr_model[old_rx_base+k] !== old_rx_sentinel[k])
                    fail("late write modified released RX buffer");
        end
    endtask

    task poison_old_tx;
        integer k;
        begin
            old_tx_poison_violation = 0;
            for (k = 0; k < 80; k = k + 1) begin
                old_tx_poison[k] = 32'hf00d1000 + k;
                ddr_model[1024+k] = old_tx_poison[k];
            end
            old_tx_poison_enable = 1;
            $display("COVERAGE old_tx_poison base=4096 bytes=320 words=80 armed=1");
        end
    endtask

    task fresh_reload;
        input [31:0] load_input_addr;
        input [31:0] probe_output_addr;
        input [31:0] load_output_addr;
        input [31:0] run_output_addr;
        input [31:0] probe_sequence;
        input [31:0] load_sequence;
        input [31:0] run_sequence;
        input [31:0] filter_id;
        integer probe_word, load_word, run_word;
        begin
            probe_word = probe_output_addr >> 2;
            load_word = load_output_addr >> 2;
            run_word = run_output_addr >> 2;

            set_rx_guard(probe_word, 5, 32'hc02d0101);
            run_output_only(probe_output_addr, 20, 0, 0, probe_sequence, filter_id);
            check_header(probe_output_addr, probe_sequence, filter_id, 0);
            check_rx_guard(probe_word, 5, 32'hc02d0101);
            if (ddr_model[probe_word+4] !== 0) fail("post-reset PROBE trailer mismatch");
            check_old_rx_sentinel();

            set_rx_guard(load_word, 5, 32'hc02d0102);
            run_input_output(load_input_addr, load_output_addr, 320, 20, 1,
                             r1_load, load_sequence, filter_id);
            check_header(load_output_addr, load_sequence, filter_id, r1_load);
            check_rx_guard(load_word, 5, 32'hc02d0102);
            if (ddr_model[load_word+4] !== 0) fail("post-reset LOAD trailer mismatch");
            check_old_rx_sentinel();

            set_rx_guard(run_word, 9, 32'hc02d0103);
            run_input_output(32'h00002000, run_output_addr, 16, 36, 2,
                             r1_run, run_sequence, filter_id);
            check_header(run_output_addr, run_sequence, filter_id, r1_run);
            check_rx_guard(run_word, 9, 32'hc02d0103);
            if (ddr_model[run_word+4] !== 22 || ddr_model[run_word+5] !== -2 ||
                ddr_model[run_word+6] !== 28 || ddr_model[run_word+7] !== 13 ||
                ddr_model[run_word+8] !== 0)
                fail("post-reset RUN reference/status mismatch");
            check_old_rx_sentinel();
            if (old_rx_sentinel_violation) fail("released RX buffer saw a late write after reload");
            if (old_tx_poison_violation) fail("old TX source was reused or modified after reset");
            $display("COVERAGE dma_s2mm_w_stall cycles=%0d stability_assertion=enabled triggered=%0d",
                dma_s2mm_w_stall_cycles, dma_s2mm_w_stall_cycles != 0);
        end
    endtask

    task snapshot_reset_counters;
        begin
            base_ar = hp_ar; base_r = hp_r; base_w = hp_w;
            base_dma_ar_bursts = dma_ar_bursts; base_dma_ar_beats = dma_ar_beats;
            base_dma_r_beats = dma_r_beats; base_dma_r_lasts = dma_r_lasts;
            base_dma_aw_bursts = dma_aw_bursts; base_dma_aw_beats = dma_aw_beats;
            base_dma_w_beats = dma_w_beats; base_dma_b_responses = dma_b_responses;
            base_hp_ar_beats = hp_ar_beats; base_hp_r_lasts = hp_r_lasts;
            base_hp_aw = hp_aw; base_hp_aw_beats = hp_aw_beats;
            base_hp_w = hp_w; base_hp_b = hp_b;
            base_s2mm_core_axis_beats = s2mm_core_axis_beats;
            base_s2mm_core_axis_tlasts = s2mm_core_axis_tlasts;
            base_s2mm_dma_axis_beats = s2mm_dma_axis_beats;
            base_s2mm_dma_axis_tlasts = s2mm_dma_axis_tlasts;
            base_hp_bresp_error_responses = hp_bresp_error_responses;
            base_dma_bresp_error_responses = dma_bresp_error_responses;
        end
    endtask

    task reset_dma_only;
        reg [31:0] st_tx, st_rx, st_tx_error, st_rx_error, cr_tx, cr_rx, abort_readback;
        reg reset_poll_done;
        reg reset_status_ok;
        reg reset_fence_ok;
        integer poll_count;
        integer wait_count;
        integer failures_at_fence;
        begin
            reset_status_clean = 0;
            reset_fence_clean = 0;
            reset_abort_released = 0;
            // Match production recover(): hold/read back ABORT, issue one TX CR
            // soft reset, poll TX/RX CR, then error and HALTED status pairs.
            acc_write(4'h0, 32'h2);
            acc_read(4'h0, abort_readback);
            if (abort_readback !== 32'h2) fail("ABORT readback did not confirm held ABORT");
            $display("COVERAGE abort_asserted time=%0t acc_reg0=%08h axis_pre_abort_stall_cycles=%0d axis_abort_cancel_count=%0d axis_core=%0d/%0d axis_dma=%0d/%0d core_valid=%0d core_ready=%0d dma_valid=%0d dma_ready=%0d hp0_aw=%0d hp0_w=%0d hp0_b=%0d dma_aw=%0d dma_w=%0d dma_b=%0d",
                $time, abort_readback,
                s2mm_axis_stall_cycles, axis_abort_cancel_count,
                s2mm_core_axis_beats-base_s2mm_core_axis_beats,
                s2mm_core_axis_tlasts-base_s2mm_core_axis_tlasts,
                s2mm_dma_axis_beats-base_s2mm_dma_axis_beats,
                s2mm_dma_axis_tlasts-base_s2mm_dma_axis_tlasts,
                accel_s2mm_tvalid, accel_s2mm_tready, dma_s2mm_tvalid, dma_s2mm_tready,
                hp_aw-base_hp_aw, hp_w-base_hp_w, hp_b-base_hp_b,
                dma_aw_beats-base_dma_aw_beats, dma_w_beats-base_dma_w_beats,
                dma_b_responses-base_dma_b_responses);
            dma_write(10'h000, 32'h4);
            poll_count = 0; wait_count = 0;
            st_tx = 0; st_rx = 0; cr_tx = 32'h4; cr_rx = 32'h4;
            reset_poll_done = 0; reset_status_ok = 0; reset_fence_ok = 0;
            fork
                begin
                    // The bounded model release runs concurrently with the
                    // driver's register polling; no external reset or post-fence drain.
                    repeat (40) @(posedge clk);
                    hp_read_hold = 0;
                    hp_write_data_hold = 0;
                    hp_write_hold_after = -1;
                    hp_bresp_hold = 0;
                    hp_bresp_error = 0;
                    mm_axis_hold = 0; mm_axis_arm = 0;
                    read_return_hold = 0; hp_pause_after = -1;
                    if (!keep_read_error_across_reset) read_error_code = 0;
                    $display("COVERAGE read_hold_release time=%0t axis_hold=0 return_hold=0 pause_after=-1 error_code=%b keep_error=%0d", $time, read_error_code, keep_read_error_across_reset);
                    if (axis_stream_hold)
                        $display("COVERAGE axis_hold_release time=%0t core_beats=%0d dma_beats=%0d core_tlast=%0d dma_tlast=%0d",
                            $time, s2mm_core_axis_beats, s2mm_dma_axis_beats,
                            s2mm_core_axis_tlasts, s2mm_dma_axis_tlasts);
                    axis_stream_hold = 0;
                    axis_hold_armed = 0;
                    $display("COVERAGE stall_release time=%0t hold_cycles=40 read=0 write_data=0 write_hold_after=-1 bresp=0", $time);
                end
                begin
                    while (poll_count < 3000 && ((cr_tx & 32'h4) || (cr_rx & 32'h4))) begin
                        dma_read(10'h000, cr_tx);
                        dma_read(10'h030, cr_rx);
                        poll_count = poll_count + 1;
                    end
                    if ((cr_tx & 32'h4) || (cr_rx & 32'h4)) begin
                        fail("DMA ResetIsDone polling did not clear TX/RX reset bits");
                    end else begin
                        dma_read(10'h004, st_tx_error);
                        dma_read(10'h034, st_rx_error);
                        if ((st_tx_error & 32'h770) || (st_rx_error & 32'h770)) begin
                            fail("DMA status error check failed after soft reset");
                        end else begin
                            dma_read(10'h004, st_tx);
                            dma_read(10'h034, st_rx);
                            if (!(st_tx & 32'h1) || !(st_rx & 32'h1) ||
                                (st_tx & 32'h770) || (st_rx & 32'h770)) begin
                                fail("DMA HALTED polling failed after soft reset");
                            end else begin
                                reset_status_ok = 1;
                                failures_at_fence = failure_count;
                                $display("COVERAGE reset_status tx_cr=%08h rx_cr=%08h tx_sr_errorcheck=%08h rx_sr_errorcheck=%08h tx_sr_halted=%08h rx_sr_halted=%08h",
                                    cr_tx, cr_rx, st_tx_error, st_rx_error, st_tx, st_rx);
                                $display("COVERAGE reset_fence time=%0t dma_ar_beats=%0d dma_r_beats=%0d dma_r_last=%0d hp0_ar_beats=%0d hp0_r_beats=%0d hp0_r_last=%0d dma_aw=%0d/%0d dma_w=%0d dma_b=%0d hp0_aw=%0d/%0d hp0_w=%0d hp0_b=%0d rd_active=%0d rvalid=%0d wr_active=%0d b_pending=%0d wvalid=%0d bvalid=%0d",
                                    $time, dma_ar_beats-base_dma_ar_beats, dma_r_beats-base_dma_r_beats,
                                    dma_r_lasts-base_dma_r_lasts, hp_ar_beats-base_hp_ar_beats,
                                    hp_r-base_r, hp_r_lasts-base_hp_r_lasts,
                                    dma_aw_bursts-base_dma_aw_bursts, dma_aw_beats-base_dma_aw_beats,
                                    dma_w_beats-base_dma_w_beats, dma_b_responses-base_dma_b_responses,
                                    hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats,
                                    hp_w-base_hp_w, hp_b-base_hp_b, rd_active, M00_AXI_rvalid_r,
                                    wr_active, wr_b_pending, M00_AXI_wvalid, M00_AXI_bvalid_r);
                                if (dma_ar_beats-base_dma_ar_beats != dma_r_beats-base_dma_r_beats)
                                    fail("ResetIsDone fence has unmatched DMA-side MM2S AR/R beats");
                                if (dma_ar_bursts-base_dma_ar_bursts != dma_r_lasts-base_dma_r_lasts)
                                    fail("ResetIsDone fence has unmatched DMA-side MM2S AR/RLAST bursts");
                                if (hp_ar_beats-base_hp_ar_beats != hp_r-base_r ||
                                    hp_ar-base_ar != hp_r_lasts-base_hp_r_lasts)
                                    fail("ResetIsDone fence has unmatched HP0 AR/R beats or RLASTs");
                                if (dma_ar_beats-base_dma_ar_beats != hp_ar_beats-base_hp_ar_beats ||
                                    dma_r_beats-base_dma_r_beats != hp_r-base_r)
                                    fail("ResetIsDone fence has MM2S traffic buffered between DMA and HP0");
                                if (rd_active || M00_AXI_rvalid_r)
                                    fail("ResetIsDone fence reached with HP0 read response outstanding");
                                if (slice_s_rvalid || slice_m_rvalid || mm_rvalid || mm_axis_tvalid || core_mm_valid)
                                    fail("ResetIsDone fence has old MM2S slice/AXIS response pending");
                                $display("COVERAGE read_fence time=%0t slice_valid=%0d return_valid=%0d dma_rvalid=%0d axis_valid=%0d core_valid=%0d core_beats=%0d core_lasts=%0d axis_stalls=%0d slice_stalls=%0d hp0_r_stalls=%0d",
                                    $time, slice_s_rvalid, slice_m_rvalid, mm_rvalid, mm_axis_tvalid,
                                    core_mm_valid, mm_core_beats, mm_core_lasts, mm_axis_stalls, mm_slice_stalls, hp_r_stall_cycles);
                                if (dma_aw_beats-base_dma_aw_beats != dma_w_beats-base_dma_w_beats ||
                                    dma_aw_bursts-base_dma_aw_bursts != dma_b_responses-base_dma_b_responses)
                                    fail("ResetIsDone fence has unmatched DMA-side S2MM AW/W/B");
                                if (hp_aw_beats-base_hp_aw_beats != hp_w-base_hp_w ||
                                    hp_aw-base_hp_aw != hp_b-base_hp_b)
                                    fail("ResetIsDone fence has unmatched HP0 AW/W/B");
                                if (dma_aw_beats-base_dma_aw_beats != hp_aw_beats-base_hp_aw_beats ||
                                    dma_w_beats-base_dma_w_beats != hp_w-base_hp_w ||
                                    dma_b_responses-base_dma_b_responses != hp_b-base_hp_b)
                                    fail("ResetIsDone fence has S2MM traffic buffered between DMA and HP0");
                                if (wr_active || wr_b_pending || M00_AXI_bvalid_r || M00_AXI_wvalid ||
                                    sm_awvalid || sm_wvalid || sm_bvalid ||
                                    accel_s2mm_tvalid || dma_s2mm_tvalid)
                                    fail("ResetIsDone fence reached with HP0/DMA S2MM state outstanding");
                                $display("COVERAGE reset_axis_fence time=%0t core_beats=%0d dma_beats=%0d core_tlast=%0d dma_tlast=%0d source_valid=%0d source_ready=%0d dma_valid=%0d dma_ready=%0d hold=%0d",
                                    $time, s2mm_core_axis_beats-base_s2mm_core_axis_beats,
                                    s2mm_dma_axis_beats-base_s2mm_dma_axis_beats,
                                    s2mm_core_axis_tlasts-base_s2mm_core_axis_tlasts,
                                    s2mm_dma_axis_tlasts-base_s2mm_dma_axis_tlasts,
                                    accel_s2mm_tvalid, accel_s2mm_tready,
                                    dma_s2mm_tvalid, dma_s2mm_tready, axis_stream_hold);
                                reset_fence_ok = (failure_count == failures_at_fence);
                            end
                        end
                    end
                    reset_poll_done = 1;
                end
            join_none
            wait_count = 0;
            while (!reset_poll_done && wait_count < 4000) begin
                @(posedge clk); wait_count = wait_count + 1;
            end
            if (!reset_poll_done) fail("DMA reset poll/fence synchronization timeout");
            reset_status_clean = reset_status_ok;
            reset_fence_clean = reset_status_ok && reset_fence_ok;
            // Verification-only fail-closed stop: production firmware's status
            // fence does not inspect these modeled AXI/AXIS counters. This gate
            // is a TB acceptance guard, not production recovery logic.
            if (reset_status_ok && reset_fence_ok) begin
                // This AXI-Lite write is the actual firmware buffer-release point.
                // Do not insert a drain delay between ResetIsDone and this write.
                acc_write(4'h0, 32'h0);
                reset_abort_released = 1;
                $display("COVERAGE abort_release time=%0t acc_reg0=%08h dma_ar=%0d/%0d/%0d hp0_ar=%0d/%0d/%0d dma_aw=%0d/%0d dma_w=%0d dma_b=%0d hp0_aw=%0d/%0d hp0_w=%0d hp0_b=%0d rd_active=%0d rvalid=%0d wr_active=%0d b_pending=%0d wvalid=%0d bvalid=%0d",
                    $time, acc_reg0, dma_ar_beats-base_dma_ar_beats, dma_r_beats-base_dma_r_beats,
                    dma_r_lasts-base_dma_r_lasts, hp_ar_beats-base_hp_ar_beats, hp_r-base_r,
                    hp_r_lasts-base_hp_r_lasts, dma_aw_bursts-base_dma_aw_bursts,
                    dma_aw_beats-base_dma_aw_beats, dma_w_beats-base_dma_w_beats,
                    dma_b_responses-base_dma_b_responses, hp_aw-base_hp_aw,
                    hp_aw_beats-base_hp_aw_beats, hp_w-base_hp_w, hp_b-base_hp_b,
                    rd_active, M00_AXI_rvalid_r, wr_active, wr_b_pending, M00_AXI_wvalid, M00_AXI_bvalid_r);
                if (acc_reg0[1] !== 1'b0) fail("ABORT clear write did not complete before release coverage");
                if (dma_ar_beats-base_dma_ar_beats != dma_r_beats-base_dma_r_beats ||
                    dma_ar_bursts-base_dma_ar_bursts != dma_r_lasts-base_dma_r_lasts ||
                    hp_ar_beats-base_hp_ar_beats != hp_r-base_r ||
                    hp_ar-base_ar != hp_r_lasts-base_hp_r_lasts || rd_active || M00_AXI_rvalid_r)
                    fail("ABORT release point has unmatched MM2S traffic");
                if (dma_aw_beats-base_dma_aw_beats != dma_w_beats-base_dma_w_beats ||
                    dma_aw_bursts-base_dma_aw_bursts != dma_b_responses-base_dma_b_responses ||
                    hp_aw_beats-base_hp_aw_beats != hp_w-base_hp_w ||
                    hp_aw-base_hp_aw != hp_b-base_hp_b ||
                    dma_aw_beats-base_dma_aw_beats != hp_aw_beats-base_hp_aw_beats ||
                    dma_w_beats-base_dma_w_beats != hp_w-base_hp_w ||
                    dma_b_responses-base_dma_b_responses != hp_b-base_hp_b ||
                    wr_active || wr_b_pending || M00_AXI_wvalid || M00_AXI_bvalid_r ||
                    sm_awvalid || sm_wvalid || sm_bvalid)
                    fail("ABORT release point has unmatched S2MM traffic");
                if (accel_s2mm_tvalid || dma_s2mm_tvalid)
                    fail("ABORT release point has pending old S2MM AXIS beat");
                if (slice_s_rvalid || slice_m_rvalid || mm_rvalid || mm_axis_tvalid || core_mm_valid)
                    fail("ABORT release point has pending old MM2S response");
                $display("COVERAGE abort_axis_release time=%0t core_beats=%0d dma_beats=%0d core_tlast=%0d dma_tlast=%0d source_valid=%0d source_ready=%0d dma_valid=%0d dma_ready=%0d hold=%0d",
                    $time, s2mm_core_axis_beats-base_s2mm_core_axis_beats,
                    s2mm_dma_axis_beats-base_s2mm_dma_axis_beats,
                    s2mm_core_axis_tlasts-base_s2mm_core_axis_tlasts,
                    s2mm_dma_axis_tlasts-base_s2mm_dma_axis_tlasts,
                    accel_s2mm_tvalid, accel_s2mm_tready,
                    dma_s2mm_tvalid, dma_s2mm_tready, axis_stream_hold);
            end else begin
                $display("COVERAGE abort_held time=%0t acc_reg0=%08h reset_status_clean=%0d reset_fence_clean=%0d hp0_ar=%0d hp0_r=%0d hp0_aw=%0d hp0_w=%0d hp0_b=%0d rd_active=%0d wr_active=%0d b_pending=%0d",
                    $time, acc_reg0, reset_status_clean, reset_fence_clean,
                    hp_ar-base_ar, hp_r-base_r, hp_aw-base_hp_aw, hp_w-base_hp_w,
                    hp_b-base_hp_b, rd_active, wr_active, wr_b_pending);
            end
        end
    endtask

    task reset_and_reload_aw_case;
        integer t;
        begin
            old_rx_base = 4416;
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc01d0101);
            hp_write_data_hold = 1;
            start_output_only(32'h00004500, 20, 0, 0, 32'h60102030, fid);
            t = 0;
            while (hp_aw == base_hp_aw && t < 1000) begin @(posedge clk); t = t + 1; end
            if (hp_aw == base_hp_aw || !wr_active)
                fail("AW_ONLY precondition: HP0 AW was not accepted");
            t = 0;
            while (!(M00_AXI_wvalid && !M00_AXI_wready) && t < 1000) begin @(posedge clk); t = t + 1; end
            if (!(M00_AXI_wvalid && !M00_AXI_wready) || hp_w != base_hp_w ||
                hp_aw_beats == base_hp_aw_beats)
                fail("AW_ONLY precondition: expected accepted AW and stalled unaccepted W");
            $display("COVERAGE write_precondition scenario=AW_ACCEPTED_W_STALLED hp0_aw=%0d aw_beats=%0d w_beats=%0d wvalid=%0d wready=%0d",
                hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats, hp_w-base_hp_w,
                M00_AXI_wvalid, M00_AXI_wready);

            reset_dma_only();
            if (acc_reg0[1] !== 1'b0) begin
                $display("FAIL stage write_reset_aw ABORT was not released; recovery programming withheld");
                $finish;
            end
            if (ddr_model[4415] !== 32'hc01d0101 || ddr_model[4421] !== ~32'hc01d0101)
                fail("AW_ONLY reset transaction overwrote adjacent DDR guard");
            if (hp_write_data_hold || hp_bresp_hold || wr_active || wr_b_pending || M00_AXI_bvalid_r || M00_AXI_wvalid)
                fail("AW_ONLY release boundary left held/active HP0 write state");
            arm_old_rx_sentinel();
            fresh_reload(32'h00001000, 32'h00004600, 32'h00004700, 32'h00004800,
                         32'h70102030, 32'h80102030, 32'h90102030, fid);
            if (failure_count != 0) begin
                $display("FAIL stage write_reset_aw failure_count=%0d", failure_count);
                $finish;
            end
            $display("COVERAGE write_reset_aw reload=PROBE_LOAD_RUN hp0_aw=%0d hp0_w=%0d hp0_b=%0d", hp_aw, hp_w, hp_b);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr");
            $display("PASS z100 DMA write reset AW_ONLY");
            $finish;
        end
    endtask

    task reset_and_reload_b_case;
        integer t;
        begin
            old_rx_base = 4672; // 0x4900, five response words.
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc01d0201);
            hp_bresp_hold = 1;
            start_output_only(32'h00004900, 20, 0, 0, 32'h61102030, fid);
            t = 0;
            while (!wr_b_pending && t < 1000) begin @(posedge clk); t = t + 1; end
            if (!wr_b_pending || wr_active || M00_AXI_bvalid_r || hp_aw == base_hp_aw ||
                hp_aw_beats-base_hp_aw_beats != 5 || hp_w-base_hp_w != 5 ||
                hp_b != base_hp_b || M00_AXI_wvalid)
                fail("B_DELAY precondition: expected all W accepted and B response held");
            $display("COVERAGE write_precondition scenario=W_COMPLETE_B_HELD hp0_aw=%0d aw_beats=%0d w_beats=%0d b_responses=%0d b_pending=%0d bvalid=%0d hold=%0d",
                hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats, hp_w-base_hp_w,
                hp_b-base_hp_b, wr_b_pending, M00_AXI_bvalid_r, hp_bresp_hold);

            reset_dma_only();
            if (acc_reg0[1] !== 1'b0) begin
                $display("FAIL stage write_reset_b ABORT was not released; recovery programming withheld");
                $finish;
            end
            if (ddr_model[old_rx_base-1] !== 32'hc01d0201 ||
                ddr_model[old_rx_base+5] !== ~32'hc01d0201)
                fail("B_DELAY reset transaction overwrote adjacent DDR guard");
            if (hp_bresp_hold || wr_active || wr_b_pending || M00_AXI_bvalid_r || M00_AXI_wvalid)
                fail("B_DELAY release boundary left held/active HP0 write state");
            arm_old_rx_sentinel();
            fresh_reload(32'h00001000, 32'h00004a00, 32'h00004b00, 32'h00004c00,
                         32'h71102030, 32'h81102030, 32'h91102030, fid);
            if (failure_count != 0) begin
                $display("FAIL stage write_reset_b failure_count=%0d", failure_count);
                $finish;
            end
            $display("COVERAGE write_reset_b reload=PROBE_LOAD_RUN hp0_aw=%0d hp0_w=%0d hp0_b=%0d", hp_aw, hp_w, hp_b);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr");
            $display("PASS z100 DMA write reset B_DELAY_ONLY");
            $finish;
        end
    endtask

    task reset_and_reload_both_case;
        integer t;
        begin
            old_rx_base = 4928; // 0x4d00, five response words.
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc01d0301);
            hp_read_hold = 1;
            hp_write_data_hold = 1;
            start_output_only(32'h00004d00, 20, 0, 0, 32'h62102030, fid);
            t = 0;
            while (!(hp_aw > base_hp_aw && M00_AXI_wvalid && !M00_AXI_wready) && t < 1000) begin
                @(posedge clk); t = t + 1;
            end
            if (!(hp_aw > base_hp_aw && M00_AXI_wvalid && !M00_AXI_wready) ||
                hp_w != base_hp_w || hp_aw_beats == base_hp_aw_beats)
                fail("BIDIR precondition: S2MM AW must be accepted with W stalled");

            // Launch a real MM2S transfer while the S2MM write remains held.
            dma_write(10'h004, 32'h7000);
            dma_write(10'h000, 32'h1);
            dma_write(10'h018, 32'h00001000);
            dma_write(10'h028, 320);
            t = 0;
            while (!(rd_active && hp_ar > base_ar && dma_ar_beats > base_dma_ar_beats) && t < 1000) begin
                @(posedge clk); t = t + 1;
            end
            if (!(rd_active && hp_ar > base_ar && dma_ar_beats > base_dma_ar_beats) ||
                M00_AXI_rvalid_r || hp_r != base_r || dma_r_beats != base_dma_r_beats ||
                hp_w != base_hp_w || !wr_active || !M00_AXI_wvalid || M00_AXI_wready)
                fail("BIDIR precondition: expected simultaneous pending HP0 MM2S read and S2MM write");
            $display("COVERAGE bidir_precondition scenario=MM2S_R_DELAY_PLUS_S2MM_AW_W_STALL dma_ar_beats=%0d hp0_ar_beats=%0d hp0_r_beats=%0d hp0_aw=%0d aw_beats=%0d hp0_w=%0d wvalid=%0d wready=%0d",
                dma_ar_beats-base_dma_ar_beats, hp_ar_beats-base_hp_ar_beats,
                hp_r-base_r, hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats,
                hp_w-base_hp_w, M00_AXI_wvalid, M00_AXI_wready);

            reset_dma_only();
            if (acc_reg0[1] !== 1'b0) begin
                $display("FAIL stage write_reset_both ABORT was not released; recovery programming withheld");
                $finish;
            end
            if (ddr_model[old_rx_base-1] !== 32'hc01d0301 ||
                ddr_model[old_rx_base+5] !== ~32'hc01d0301)
                fail("BIDIR reset transaction overwrote adjacent DDR guard");
            if (hp_read_hold || hp_write_data_hold || rd_active || M00_AXI_rvalid_r ||
                wr_active || wr_b_pending || M00_AXI_bvalid_r || M00_AXI_wvalid)
                fail("BIDIR release boundary left held/active HP0 transaction state");
            arm_old_rx_sentinel();
            poison_old_tx();
            fresh_reload(32'h00001200, 32'h00004e00, 32'h00004f00, 32'h00005000,
                         32'h72102030, 32'h82102030, 32'h92102030, fid);
            if (failure_count != 0) begin
                $display("FAIL stage write_reset_both failure_count=%0d", failure_count);
                $finish;
            end
            $display("COVERAGE write_reset_both reload=PROBE_LOAD_RUN hp0_ar=%0d hp0_r=%0d hp0_aw=%0d hp0_w=%0d hp0_b=%0d",
                hp_ar, hp_r, hp_aw, hp_w, hp_b);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr");
            $display("PASS z100 DMA write reset BIDIR_ONLY");
            $finish;
        end
    endtask

    task reset_and_reload_partial_w_case;
        integer t;
        begin
            old_rx_base = 5184; // 0x5100, five response words.
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc01d0401);
            hp_write_hold_after = base_hp_w + 2;
            start_output_only(32'h00005100, 20, 0, 0, 32'h63102030, fid);
            t = 0;
            while (hp_aw == base_hp_aw && t < 1000) begin @(posedge clk); t = t + 1; end
            if (hp_aw == base_hp_aw || !wr_active)
                fail("PARTIAL_W precondition: HP0 AW was not accepted");
            t = 0;
            while (hp_w-base_hp_w < 2 && t < 1000) begin @(posedge clk); t = t + 1; end
            if (hp_w-base_hp_w != 2 || !M00_AXI_wvalid || M00_AXI_wready || M00_AXI_wlast ||
                hp_aw_beats-base_hp_aw_beats != 5 || hp_b != base_hp_b ||
                wr_b_pending || M00_AXI_bvalid_r || !wr_active)
                fail("PARTIAL_W precondition: expected HP0 AW plus exactly two of five W beats");
            $display("COVERAGE write_precondition scenario=HP0_AW_PLUS_TWO_OF_FIVE_W hp0_aw=%0d aw_beats=%0d w_beats=%0d next_wlast=%0d b_responses=%0d wvalid=%0d wready=%0d",
                hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats, hp_w-base_hp_w,
                M00_AXI_wlast, hp_b-base_hp_b, M00_AXI_wvalid, M00_AXI_wready);

            reset_dma_only();
            if (!reset_abort_released || !reset_status_clean || !reset_fence_clean || acc_reg0[1] !== 1'b0) begin
                $display("FAIL stage fault_partial_w reset did not reach a closed software fence; ABORT release withheld");
                $finish;
            end
            if (ddr_model[old_rx_base-1] !== 32'hc01d0401 ||
                ddr_model[old_rx_base+5] !== ~32'hc01d0401)
                fail("PARTIAL_W reset transaction overwrote adjacent DDR guard");
            if (hp_write_hold_after >= 0 || wr_active || wr_b_pending || M00_AXI_bvalid_r || M00_AXI_wvalid)
                fail("PARTIAL_W release boundary left held/active HP0 write state");
            arm_old_rx_sentinel();
            fresh_reload(32'h00001000, 32'h00005200, 32'h00005300, 32'h00005400,
                         32'h73102030, 32'h83102030, 32'h93102030, fid);
            if (failure_count != 0) begin
                $display("FAIL stage fault_partial_w failure_count=%0d", failure_count);
                $finish;
            end
            $display("COVERAGE fault_partial_w reload=PROBE_LOAD_RUN hp0_aw=%0d hp0_w=%0d hp0_b=%0d",
                hp_aw, hp_w, hp_b);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr");
            $display("PASS z100 DMA fault PARTIAL_W");
            $finish;
        end
    endtask

    task reset_and_reload_tlast_abort_case;
        integer t;
        begin
            old_rx_base = 5248; // 0x5200, five response words.
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc01d0501);
            s2mm_axis_hold_target = s2mm_dma_axis_beats + 2;
            axis_hold_armed = 1;
            start_output_only(32'h00005200, 20, 0, 0, 32'h64102030, fid);

            t = 0;
            while (!axis_stream_hold && t < 1000) begin @(posedge clk); t = t + 1; end
            if (!axis_stream_hold)
                begin fail("TLAST_ABORT precondition timed out before S2MM AXIS beat two"); $finish; end
            t = 0;
            while (!accel_s2mm_tvalid && t < 100) begin @(posedge clk); t = t + 1; end
            if (s2mm_core_axis_beats-base_s2mm_core_axis_beats != 2 ||
                s2mm_dma_axis_beats-base_s2mm_dma_axis_beats != 2 ||
                s2mm_core_axis_tlasts != base_s2mm_core_axis_tlasts ||
                s2mm_dma_axis_tlasts != base_s2mm_dma_axis_tlasts ||
                !accel_s2mm_tvalid || accel_s2mm_tready || dma_s2mm_tvalid ||
                accel_s2mm_tlast || dma_s2mm_tlast || accel_task_finish !== 1'b0)
                begin fail("TLAST_ABORT precondition was not exact core/DMA S2MM 2-of-5 without TLAST"); $finish; end
            $display("COVERAGE axis_precondition scenario=CORE_S2MM_2_OF_5_NO_TLAST time=%0t core_beats=%0d core_tlasts=%0d dma_beats=%0d dma_tlasts=%0d source_valid=%0d source_ready=%0d source_last=%0d dma_valid=%0d dma_ready=%0d dma_last=%0d task_finish=%0d dma_aw=%0d/%0d dma_w=%0d dma_b=%0d hp0_aw=%0d/%0d hp0_w=%0d hp0_b=%0d",
                $time, s2mm_core_axis_beats-base_s2mm_core_axis_beats,
                s2mm_core_axis_tlasts-base_s2mm_core_axis_tlasts,
                s2mm_dma_axis_beats-base_s2mm_dma_axis_beats,
                s2mm_dma_axis_tlasts-base_s2mm_dma_axis_tlasts,
                accel_s2mm_tvalid, accel_s2mm_tready, accel_s2mm_tlast,
                dma_s2mm_tvalid, dma_s2mm_tready, dma_s2mm_tlast, accel_task_finish,
                dma_aw_bursts-base_dma_aw_bursts, dma_aw_beats-base_dma_aw_beats,
                dma_w_beats-base_dma_w_beats, dma_b_responses-base_dma_b_responses,
                hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats,
                hp_w-base_hp_w, hp_b-base_hp_b);

            reset_dma_only();
            if (!reset_abort_released || !reset_status_clean || !reset_fence_clean || acc_reg0[1] !== 1'b0) begin
                $display("FAIL stage fault_tlast_abort reset did not reach the closed ResetIsDone/ABORT-release fence; ABORT release withheld");
                $finish;
            end
            if (failure_count != 0) begin
                $display("FAIL stage fault_tlast_abort failure_count=%0d; reload withheld", failure_count);
                $finish;
            end
            if (ddr_model[old_rx_base-1] !== 32'hc01d0501 ||
                ddr_model[old_rx_base+5] !== ~32'hc01d0501)
                fail("TLAST_ABORT transaction overwrote adjacent DDR guard");
            arm_old_rx_sentinel();
            fresh_reload(32'h00001000, 32'h00005800, 32'h00005900, 32'h00005a00,
                         32'h74102030, 32'h84102030, 32'h94102030, fid);
            if (failure_count != 0) begin
                $display("FAIL stage fault_tlast_abort failure_count=%0d", failure_count);
                $finish;
            end
            $display("COVERAGE fault_tlast_abort reload=PROBE_LOAD_RUN axis_core=%0d/%0d axis_dma=%0d/%0d hp0_aw=%0d hp0_w=%0d hp0_b=%0d",
                s2mm_core_axis_beats-base_s2mm_core_axis_beats,
                s2mm_core_axis_tlasts-base_s2mm_core_axis_tlasts,
                s2mm_dma_axis_beats-base_s2mm_dma_axis_beats,
                s2mm_dma_axis_tlasts-base_s2mm_dma_axis_tlasts,
                hp_aw-base_hp_aw, hp_w-base_hp_w, hp_b-base_hp_b);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr+axis_gate");
            $display("PASS z100 DMA fault TLAST_ABORT");
            $finish;
        end
    endtask

    task run_bresp_error_and_reload_case;
        reg [31:0] status_rx;
        integer t;
        begin
            old_rx_base = 5376; // 0x5400, five response words.
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc01d0601);
            hp_bresp_error = 1;
            start_output_only(32'h00005400, 20, 0, 0, 32'h65102030, fid);
            status_rx = 0;
            t = 0;
            while ((status_rx & 32'h770) == 0 && t < 3000) begin
                dma_read(10'h034, status_rx);
                t = t + 1;
            end
            if ((status_rx & 32'h770) == 0) begin
                fail("BRESP error did not set a DMA S2MM error status within bounded polling");
                $display("FAIL stage fault_bresp status_rx=%08h hp_bresp_error=%0d dma_bresp_error=%0d",
                    status_rx, hp_bresp_error_responses-base_hp_bresp_error_responses,
                    dma_bresp_error_responses-base_dma_bresp_error_responses);
                $finish;
            end
            if (hp_bresp_error_responses-base_hp_bresp_error_responses != 1 ||
                hp_bresp_error_last !== 2'b10 ||
                dma_bresp_error_responses-base_dma_bresp_error_responses != 1 ||
                dma_bresp_error_last !== 2'b10 ||
                hp_b-base_hp_b != 1 || dma_b_responses-base_dma_b_responses != 1) begin
                fail("BRESP error was not observed at both HP0 and DMA B handshakes");
                $display("FAIL stage fault_bresp hp_bresp_count=%0d hp_last=%b dma_bresp_count=%0d dma_last=%b hp_b=%0d dma_b=%0d status_rx=%08h",
                    hp_bresp_error_responses-base_hp_bresp_error_responses,
                    hp_bresp_error_last,
                    dma_bresp_error_responses-base_dma_bresp_error_responses,
                    dma_bresp_error_last, hp_b-base_hp_b,
                    dma_b_responses-base_dma_b_responses, status_rx);
                $finish;
            end
            $display("COVERAGE bresp_error pre_reset time=%0t hp0_b_handshakes=%0d hp0_bresp=%b dma_b_handshakes=%0d dma_bresp=%b rx_sr=%08h aw=%0d/%0d w=%0d b=%0d hp0_aw=%0d/%0d hp0_w=%0d hp0_b=%0d",
                $time, hp_bresp_error_responses-base_hp_bresp_error_responses,
                hp_bresp_error_last,
                dma_bresp_error_responses-base_dma_bresp_error_responses,
                dma_bresp_error_last, status_rx,
                dma_aw_bursts-base_dma_aw_bursts, dma_aw_beats-base_dma_aw_beats,
                dma_w_beats-base_dma_w_beats, dma_b_responses-base_dma_b_responses,
                hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats,
                hp_w-base_hp_w, hp_b-base_hp_b);
            if ((status_rx & 32'h770) == 0) fail("BRESP pre-reset S2MM error mask missing");

            // The one injected response has completed; do not contaminate reload traffic.
            hp_bresp_error = 0;
            reset_dma_only();
            if (!reset_abort_released || !reset_status_clean || !reset_fence_clean || acc_reg0[1] !== 1'b0) begin
                $display("FAIL stage fault_bresp reset did not clear DMA error and close the software/AXI fence; ABORT release withheld");
                $finish;
            end
            if (failure_count != 0) begin
                $display("FAIL stage fault_bresp failure_count=%0d; reload withheld", failure_count);
                $finish;
            end
            if (ddr_model[old_rx_base-1] !== 32'hc01d0601 ||
                ddr_model[old_rx_base+5] !== ~32'hc01d0601)
                fail("BRESP error transaction overwrote adjacent DDR guard");
            arm_old_rx_sentinel();
            fresh_reload(32'h00001000, 32'h00005800, 32'h00005900, 32'h00005a00,
                         32'h75102030, 32'h85102030, 32'h95102030, fid);
            if (failure_count != 0) begin
                $display("FAIL stage fault_bresp failure_count=%0d", failure_count);
                $finish;
            end
            $display("COVERAGE fault_bresp reload=PROBE_LOAD_RUN prior_error_status=%08h hp0_bresp=%b dma_bresp=%b reset_error_clear=%0d",
                status_rx, hp_bresp_error_last, dma_bresp_error_last, reset_status_clean);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr+bresp_slverr_injection");
            $display("PASS z100 DMA fault BRESP_ERROR_RECOVERED");
            $finish;
        end
    endtask

    task run_persistent_hp0_stall_case;
        reg [31:0] abort_readback, cr_tx, cr_rx, sr_tx, sr_rx;
        integer t, poll_count;
        reg external_write_pending;
        reg sr_sampled;
        begin
            old_rx_base = 5312; // 0x5300, five response words.
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc01d0701);
            hp_write_data_hold = 1;
            start_output_only(32'h00005300, 20, 0, 0, 32'h66102030, fid);
            t = 0;
            while ((hp_aw == base_hp_aw || !M00_AXI_wvalid) && t < 1000) begin
                @(posedge clk); t = t + 1;
            end
            if (hp_aw == base_hp_aw || !wr_active || !M00_AXI_wvalid || M00_AXI_wready ||
                hp_w != base_hp_w || hp_b != base_hp_b) begin
                fail("PERSISTENT precondition lacked accepted HP0 AW plus WVALID&&!WREADY");
                $display("FAIL stage fault_persistent hp0_aw=%0d wvalid=%0d wready=%0d w=%0d b=%0d",
                    hp_aw-base_hp_aw, M00_AXI_wvalid, M00_AXI_wready,
                    hp_w-base_hp_w, hp_b-base_hp_b);
                $finish;
            end
            $display("COVERAGE persistent_precondition time=%0t hp0_aw=%0d/%0d hp0_w=%0d hp0_b=%0d wvalid=%0d wready=%0d dma_aw=%0d/%0d dma_w=%0d dma_b=%0d axis_core=%0d/%0d axis_dma=%0d/%0d task_finish=%0d hold=permanent",
                $time, hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats,
                hp_w-base_hp_w, hp_b-base_hp_b, M00_AXI_wvalid, M00_AXI_wready,
                dma_aw_bursts-base_dma_aw_bursts, dma_aw_beats-base_dma_aw_beats,
                dma_w_beats-base_dma_w_beats, dma_b_responses-base_dma_b_responses,
                s2mm_core_axis_beats-base_s2mm_core_axis_beats,
                s2mm_core_axis_tlasts-base_s2mm_core_axis_tlasts,
                s2mm_dma_axis_beats-base_s2mm_dma_axis_beats,
                s2mm_dma_axis_tlasts-base_s2mm_dma_axis_tlasts, accel_task_finish);

            acc_write(4'h0, 32'h2);
            acc_read(4'h0, abort_readback);
            if (abort_readback !== 32'h2) begin
                fail("PERSISTENT case ABORT write/readback did not hold");
                $finish;
            end
            $display("COVERAGE persistent_abort_asserted time=%0t acc_reg0=%08h hp0_aw=%0d hp0_w=%0d hp0_b=%0d wvalid=%0d wready=%0d",
                $time, abort_readback, hp_aw-base_hp_aw, hp_w-base_hp_w,
                hp_b-base_hp_b, M00_AXI_wvalid, M00_AXI_wready);
            dma_write(10'h000, 32'h4); // Match firmware: one TX CR reset write.
            cr_tx = 32'h4; cr_rx = 32'h4; sr_tx = 0; sr_rx = 0; sr_sampled = 0;
            poll_count = 0;
            while (poll_count < 200 && ((cr_tx & 32'h4) || (cr_rx & 32'h4))) begin
                dma_read(10'h000, cr_tx);
                dma_read(10'h030, cr_rx);
                poll_count = poll_count + 1;
            end
            external_write_pending = wr_active || wr_b_pending || M00_AXI_wvalid ||
                M00_AXI_bvalid_r || sm_awvalid || sm_wvalid || sm_bvalid;
            dma_read(10'h000, cr_tx);
            dma_read(10'h030, cr_rx);
            if (!((cr_tx & 32'h4) || (cr_rx & 32'h4))) begin
                dma_read(10'h004, sr_tx);
                dma_read(10'h034, sr_rx);
                sr_sampled = 1;
            end
            acc_read(4'h0, abort_readback);
            $display("COVERAGE persistent_bounded_poll time=%0t poll_limit=200 poll_count=%0d testbench_window_not_firmware_timeout=1 resetdone=%0d sr_sampled=%0d tx_cr=%08h rx_cr=%08h tx_sr=%08h rx_sr=%08h abort=%08h hp0_aw=%0d/%0d hp0_w=%0d hp0_b=%0d wvalid=%0d wready=%0d wr_active=%0d b_pending=%0d bvalid=%0d dma_aw=%0d/%0d dma_w=%0d dma_b=%0d external_write_pending=%0d production_C_executed=0",
                $time, poll_count,
                !((cr_tx & 32'h4) || (cr_rx & 32'h4)), sr_sampled,
                cr_tx, cr_rx, sr_tx, sr_rx, abort_readback,
                hp_aw-base_hp_aw, hp_aw_beats-base_hp_aw_beats,
                hp_w-base_hp_w, hp_b-base_hp_b,
                M00_AXI_wvalid, M00_AXI_wready, wr_active, wr_b_pending,
                M00_AXI_bvalid_r, dma_aw_bursts-base_dma_aw_bursts,
                dma_aw_beats-base_dma_aw_beats, dma_w_beats-base_dma_w_beats,
                dma_b_responses-base_dma_b_responses, external_write_pending);
            if (external_write_pending &&
                !((cr_tx & 32'h4) || (cr_rx & 32'h4))) begin
                fail("ResetIsDone bits cleared while the permanent HP0 write remained pending; stopping before ABORT clear or buffer reuse");
                $display("ESCALATE production C has not been run in this TB; if its later error/HALTED predicates pass, its current code would clear ABORT without HP0 outstanding checks");
                $finish;
            end
            if (!external_write_pending ||
                !((cr_tx & 32'h4) || (cr_rx & 32'h4)) || abort_readback !== 32'h2 ||
                M00_AXI_wready !== 1'b0 || failure_count != 0) begin
                fail("PERSISTENT bounded negative did not retain reset-pending, HP0 W stall, and ABORT");
                $display("FAIL stage fault_persistent external_pending=%0d tx_cr=%08h rx_cr=%08h abort=%08h failure_count=%0d",
                    external_write_pending, cr_tx, cr_rx, abort_readback, failure_count);
                $finish;
            end
            $display("COVERAGE persistent_pending_expected reset_bits_still_set=1 abort_held=1 no_release=1 no_reload=1");
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr+permanent_wready_hold");
            $display("PASS z100 DMA fault PERSISTENT_PENDING");
            $finish;
        end
    endtask

    task retain_episode_buffers;
        input integer episode;
        integer k;
        begin
            for (k = 0; k < 5; k = k + 1) begin
                retained_rx[episode*5+k] = 32'hdeca0000+k;
                ddr_model[6144+episode*64+k] = retained_rx[episode*5+k];
            end
            for (k = 0; k < 80; k = k + 1) begin
                retained_tx[episode*80+k] = 32'hf00d1000+episode*256+k;
                ddr_model[1024+episode*128+k] = retained_tx[episode*80+k];
            end
            retained_enable[episode] = 1;
            $display("COVERAGE retained_buffers episode=%0d tx_addr=%08h tx_words=80 rx_addr=%08h rx_words=5 armed=1", episode,
                32'h1000+episode*512, 32'h6000+episode*256);
        end
    endtask

    task early_error_retry_case;
        input integer episode_count;
        integer episode, t, hp_errors_before, dma_errors_before, core_before;
        reg [31:0] status_tx;
        begin
            keep_read_error_across_reset = 1;
            read_error_code = 2'b10;
            for (episode = 0; episode < episode_count; episode = episode + 1) begin
                old_rx_base = 6144+episode*64;
                snapshot_reset_counters();
                hp_errors_before = hp_read_errors; dma_errors_before = dma_read_errors;
                core_before = mm_core_beats;
                set_rx_guard(old_rx_base, 5, 32'hc04d0001+episode);
                hp_pause_after = hp_r+4;
                start_output_only(32'h6000+episode*256, 20, 1, r1_load, 32'h67102030+episode, fid);
                dma_write(10'h000, 32'h1);
                dma_write(10'h018, 32'h1000+episode*512);
                dma_write(10'h028, 320);
                t = 0;
                while ((hp_read_errors-hp_errors_before < 4 || dma_read_errors-dma_errors_before < 4) && t < 2000) begin
                    @(negedge clk); t = t + 1;
                end
                if (t == 2000 || hp_r-base_r != 4 || dma_r_beats-base_dma_r_beats != 4 ||
                    hp_r_lasts-base_hp_r_lasts != 0 || !rd_active ||
                    hp_read_error_last !== 2'b10 || dma_read_error_last !== 2'b10)
                    fail("Early error fixture lacked exactly four accepted SLVERR beats in a live burst");
                status_tx = 0; t = 0;
                while (!(status_tx & 32'h770) && t < 64) begin
                    dma_read(10'h004, status_tx); t = t + 1;
                end
                if (hp_r-base_r != 4 || dma_r_beats-base_dma_r_beats != 4 ||
                    !rd_active || hp_ar_beats-base_hp_ar_beats <= hp_r-base_r ||
                    mm_core_lasts != 0 || accel_task_finish)
                    fail("Early error status observation lost the in-flight pre-TLAST condition");
                $display("COVERAGE early_error episode=%0d time=%0t hp0_error_beats=%0d dma_error_beats=%0d code=10 hp0_ar_beats=%0d hp0_r=%0d dma_ar_beats=%0d dma_r=%0d hp0_rlast=%0d core_beats=%0d core_tlast=%0d tx_sr=%08h status_error_visible=%0d polls=%0d poll_limit=64 bounded_timeout_trigger=%0d rd_active=%0d production_C_executed=0",
                    episode, $time, hp_read_errors-hp_errors_before, dma_read_errors-dma_errors_before,
                    hp_ar_beats-base_hp_ar_beats, hp_r-base_r, dma_ar_beats-base_dma_ar_beats,
                    dma_r_beats-base_dma_r_beats, hp_r_lasts-base_hp_r_lasts,
                    mm_core_beats-core_before, mm_core_lasts, status_tx,
                    (status_tx & 32'h770) != 0, t, (status_tx & 32'h770) == 0, rd_active);
                if (failure_count != 0) begin $display("FAIL early error precondition"); $finish; end
                reset_dma_only();
                if (!reset_status_clean || !reset_fence_clean || !reset_abort_released || failure_count != 0) begin
                    $display("FAIL early error reset episode=%0d", episode); $finish;
                end
                if (read_error_code !== 2'b10)
                    fail("Repeated error injection did not persist across DMA-only reset");
                check_rx_guard(old_rx_base, 5, 32'hc04d0001+episode);
                retain_episode_buffers(episode);
                // Re-probe between faults, as the active C contract requires.
                set_rx_guard(6272, 5, 32'hc04d0101);
                run_output_only(32'h6200, 20, 0, 0, 32'h77102030+episode, fid);
                check_header(32'h6200, 32'h77102030+episode, fid, 0);
                check_rx_guard(6272, 5, 32'hc04d0101);
                if (ddr_model[6276] !== 0) fail("Repeated recovery PROBE trailer mismatch");
                $display("COVERAGE retry_probe episode=%0d sequence=%08h error_code_still=10 complete=1", episode, 32'h77102030+episode);
            end
            // Only now repair the modeled memory fault. Reset alone did not remove it.
            read_error_code = 0; keep_read_error_across_reset = 0;
            $display("COVERAGE fault_removed time=%0t episodes=%0d after_all_reset_fences=1", $time, episode_count);
            arm_old_rx_sentinel();
            fresh_reload(32'h1400, 32'h6200, 32'h6300, 32'h6400,
                         32'h78102030, 32'h88102030, 32'h98102030, fid);
            if (failure_count != 0) begin $display("FAIL repeated error reload"); $finish; end
            $display("COVERAGE retry_recovery episodes=%0d reload=PROBE_LOAD_RUN retained_slots=%0d hp0_errors=%0d dma_errors=%0d fault_cleared=1",
                episode_count, episode_count, hp_read_errors, dma_read_errors);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr+finite_read_pause+retained_error_injection");
            if (episode_count == 1) $display("PASS z100 DMA retry EARLY_ERROR");
            else $display("PASS z100 DMA retry REPEATED_ERROR");
            $finish;
        end
    endtask

    task permanent_read_case;
        integer t, polls;
        reg [31:0] cr_tx, cr_rx, sr_tx, sr_rx, abort_readback;
        reg external_pending, sr_sampled;
        begin
            old_rx_base = 6144;
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc04d0201);
            read_return_hold = 1;
            start_output_only(32'h6000, 20, 1, r1_load, 32'h69102030, fid);
            dma_write(10'h000, 32'h1); dma_write(10'h018, 32'h1000); dma_write(10'h028, 320);
            t = 0;
            while (!(slice_s_rvalid && !slice_s_rready && M00_AXI_rvalid_r && !M00_AXI_rready) && t < 2000) begin
                @(negedge clk); t = t + 1;
            end
            if (t == 2000 || !rd_active || dma_r_beats != base_dma_r_beats)
                fail("Permanent read fixture lacks stalled HP0 and actual slice responses");
            $display("COVERAGE permanent_read_pre time=%0t hp0_ar_beats=%0d hp0_r=%0d dma_ar_beats=%0d dma_r=%0d slice_valid=%0d slice_ready=%0d hp0_valid=%0d hp0_ready=%0d rd_active=%0d",
                $time, hp_ar_beats-base_hp_ar_beats, hp_r-base_r, dma_ar_beats-base_dma_ar_beats,
                dma_r_beats-base_dma_r_beats, slice_s_rvalid, slice_s_rready, M00_AXI_rvalid_r, M00_AXI_rready, rd_active);
            acc_write(4'h0, 32'h2); acc_read(4'h0, abort_readback);
            if (abort_readback !== 32'h2) fail("Permanent read ABORT did not latch");
            dma_write(10'h000, 32'h4);
            cr_tx = 4; cr_rx = 4; polls = 0; sr_tx = 0; sr_rx = 0; sr_sampled = 0;
            while (polls < 200 && ((cr_tx & 4) || (cr_rx & 4))) begin
                dma_read(10'h000, cr_tx); dma_read(10'h030, cr_rx); polls = polls+1;
            end
            external_pending = rd_active || M00_AXI_rvalid_r || slice_s_rvalid || slice_m_rvalid ||
                (dma_ar_beats-base_dma_ar_beats != dma_r_beats-base_dma_r_beats);
            if (!((cr_tx & 4) || (cr_rx & 4))) begin
                dma_read(10'h004, sr_tx); dma_read(10'h034, sr_rx); sr_sampled = 1;
            end
            acc_read(4'h0, abort_readback);
            $display("COVERAGE permanent_read_poll time=%0t polls=%0d poll_limit=200 tx_cr=%08h rx_cr=%08h sr_sampled=%0d tx_sr=%08h rx_sr=%08h abort=%08h external_pending=%0d hp0_ar_beats=%0d hp0_r=%0d dma_ar_beats=%0d dma_r=%0d slice_stalls=%0d hp0_stalls=%0d return_hold=%0d production_C_executed=0",
                $time, polls, cr_tx, cr_rx, sr_sampled, sr_tx, sr_rx, abort_readback, external_pending,
                hp_ar_beats-base_hp_ar_beats, hp_r-base_r, dma_ar_beats-base_dma_ar_beats,
                dma_r_beats-base_dma_r_beats, mm_slice_stalls, hp_r_stall_cycles, read_return_hold);
            if (external_pending && !((cr_tx & 4) || (cr_rx & 4))) begin
                fail("Read ResetIsDone cleared with external response still pending; escalation required");
                $display("ESCALATE production C may release ownership if remaining status predicates pass; ABORT held by TB, no reuse");
                $finish;
            end
            if (!external_pending || !((cr_tx & 4) || (cr_rx & 4)) || polls != 200 ||
                abort_readback !== 2 || !read_return_hold || failure_count != 0) begin
                $display("FAIL permanent read negative acceptance"); $finish;
            end
            check_rx_guard(old_rx_base, 5, 32'hc04d0201);
            if (failure_count != 0) begin $display("FAIL permanent read buffer guard"); $finish; end
            $display("COVERAGE permanent_read_expected abort_held=1 no_release=1 no_reload=1 reset_pending=1 bounded_TB_window_only=1");
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr+permanent_read_return_gate");
            $display("PASS z100 DMA retry PERMANENT_READ_PENDING");
            $finish;
        end
    endtask

    task read_fault_case;
        input integer kind; // 0 AXIS cut; 1 return backpressure; 2 SLVERR; 3 DECERR
        integer t, initial_core, initial_last;
        reg [31:0] status_tx, expected_error;
        begin
            old_rx_base = 5632; // 0x5800, distinct from every reload buffer.
            snapshot_reset_counters();
            set_rx_guard(old_rx_base, 5, 32'hc03d0001);
            initial_core = mm_core_beats; initial_last = mm_core_lasts;
            if (kind == 0) begin
                mm_axis_target = mm_core_beats + 2; mm_axis_arm = 1;
            end
            if (kind == 1) read_return_hold = 1;
            if (kind >= 2) read_error_code = kind == 2 ? 2'b10 : 2'b11;
            start_output_only(32'h00005800, 20, 1, r1_load, 32'h66102030+kind, fid);
            dma_write(10'h000, 32'h1);
            dma_write(10'h018, 32'h00001000);
            dma_write(10'h028, 320);
            t = 0; status_tx = 0;
            if (kind == 0) begin
                while (!(mm_axis_hold && mm_axis_tvalid && !mm_axis_tready) && t < 2000) begin
                    @(negedge clk); t = t + 1;
                end
                if (t == 2000 || mm_core_beats-initial_core != 2 ||
                    mm2s_beats != 2 || mm_core_lasts != initial_last || mm2s_tlasts != 0 ||
                    mm_axis_tlast || core_mm_valid || accel_task_finish)
                    fail("MM2S cut lacked exactly two real input handshakes before TLAST");
                repeat (5) @(negedge clk);
                if (mm_core_beats-initial_core != 2 || mm_core_lasts != initial_last)
                    fail("MM2S cut gate admitted extra core data");
                $display("COVERAGE read_precondition kind=AXIS_CUT time=%0t dma_axis=%0d core_axis=%0d dma_tlast=%0d core_tlast=%0d axis_valid=%0d axis_ready=%0d core_valid=%0d core_ready=%0d task_finish=%0d expected_beats=80 hp0_ar=%0d hp0_r=%0d",
                    $time, mm2s_beats, mm_core_beats-initial_core, mm2s_tlasts,
                    mm_core_lasts-initial_last, mm_axis_tvalid, mm_axis_tready,
                    core_mm_valid, core_mm_ready, accel_task_finish, hp_ar-base_ar, hp_r-base_r);
            end else if (kind == 1) begin
                while (!(slice_s_rvalid && !slice_s_rready && M00_AXI_rvalid_r && !M00_AXI_rready) && t < 2000) begin
                    @(negedge clk); t = t + 1;
                end
                if (t == 2000 || mm_core_beats != initial_core || !read_return_hold)
                    fail("Read backpressure did not reach both actual slice and HP0 RVALID stall");
                repeat (10) @(negedge clk);
                if (!slice_s_rvalid || slice_s_rready || !M00_AXI_rvalid_r || M00_AXI_rready ||
                    mm_slice_stalls < 10 || hp_r_stall_cycles < 10)
                    fail("Read backpressure did not maintain actual RVALID/payload stability window");
                $display("COVERAGE read_precondition kind=R_BACKPRESSURE time=%0t slice_valid=%0d slice_ready=%0d hp0_valid=%0d hp0_ready=%0d slice_stalls=%0d hp0_stalls=%0d hp0_ar_beats=%0d hp0_r=%0d dma_r=%0d core_axis=%0d",
                    $time, slice_s_rvalid, slice_s_rready, M00_AXI_rvalid_r, M00_AXI_rready,
                    mm_slice_stalls, hp_r_stall_cycles, hp_ar_beats-base_hp_ar_beats,
                    hp_r-base_r, dma_r_beats-base_dma_r_beats, mm_core_beats-initial_core);
            end else begin
                expected_error = kind == 2 ? 32'h20 : 32'h40;
                while (!(status_tx & expected_error) && t < 3000) begin
                    dma_read(10'h004, status_tx); t = t + 1;
                end
                if (t == 3000 || !hp_read_errors || !dma_read_errors ||
                    hp_read_error_last !== read_error_code || dma_read_error_last !== read_error_code)
                    fail("RRESP error did not reach both HP0/DMA handshakes and exact TX SR bit");
                $display("COVERAGE read_precondition kind=RRESP_ERROR time=%0t code=%b hp0_error_beats=%0d dma_error_beats=%0d hp0_resp=%b dma_resp=%b tx_sr=%08h expected_mask=%08h hp0_ar_beats=%0d hp0_r=%0d dma_ar_beats=%0d dma_r=%0d",
                    $time, read_error_code, hp_read_errors, dma_read_errors,
                    hp_read_error_last, dma_read_error_last, status_tx, expected_error,
                    hp_ar_beats-base_hp_ar_beats, hp_r-base_r,
                    dma_ar_beats-base_dma_ar_beats, dma_r_beats-base_dma_r_beats);
            end
            if (failure_count != 0) begin $display("FAIL read precondition kind=%0d",kind); $finish; end
            reset_dma_only();
            if (!reset_status_clean || !reset_fence_clean || !reset_abort_released || failure_count != 0) begin
                $display("FAIL read reset kind=%0d status=%0d fence=%0d released=%0d", kind,
                    reset_status_clean, reset_fence_clean, reset_abort_released);
                $finish;
            end
            check_rx_guard(old_rx_base, 5, 32'hc03d0001);
            arm_old_rx_sentinel(); poison_old_tx();
            fresh_reload(32'h00001200, 32'h00005c00, 32'h00005d00, 32'h00005e00,
                         32'h76102030+kind, 32'h86102030+kind, 32'h96102030+kind, fid);
            if (failure_count != 0) begin $display("FAIL read reload kind=%0d",kind); $finish; end
            $display("COVERAGE read_recovery kind=%0d reload=PROBE_LOAD_RUN old_tx_poison=1 old_rx_sentinel=1 axis_stalls=%0d slice_stalls=%0d hp0_stalls=%0d hp0_error_beats=%0d dma_error_beats=%0d",
                kind, mm_axis_stalls, mm_slice_stalls, hp_r_stall_cycles, hp_read_errors, dma_read_errors);
            $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0+system_mem_xbar_0(actual_auto_pc_0_1)+system_yolo_accel_top_0_0 models=cpu_axi_lite+hp0_axi3_ddr+read_test_interposers");
            case (kind)
                0: $display("PASS z100 DMA read MM2S_ABORT");
                1: $display("PASS z100 DMA read R_BACKPRESSURE");
                2: $display("PASS z100 DMA read RRESP_SLVERR");
                3: $display("PASS z100 DMA read RRESP_DECERR");
            endcase
            $finish;
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

    initial begin
        // Initial source vectors: tile64 T=1, L=1; 64 bias words then 16
        // packed weight words. Reference output is bias[0] + signed(act)*w[0].
        for (i = 0; i < 8192; i = i + 1) ddr_model[i] = 0;
        for (i = 0; i < 64; i = i + 1) ddr_model[1024 + i] = (i == 0) ? 7 : 0;
        for (i = 0; i < 16; i = i + 1) ddr_model[1088 + i] = (i == 0) ? 32'h00000003 : 0;
        for (i = 0; i < 80; i = i + 1) ddr_model[1152 + i] = ddr_model[1024 + i];
        for (i = 0; i < 80; i = i + 1) ddr_model[1280 + i] = ddr_model[1024 + i];
        retained_enable[0] = 0; retained_enable[1] = 0;
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

        if ($test$plusargs("RETRY_EARLY_ERROR")) early_error_retry_case(1);
        if ($test$plusargs("RETRY_REPEATED_ERROR")) early_error_retry_case(2);
        if ($test$plusargs("RETRY_PERMANENT_READ")) permanent_read_case();

        if ($test$plusargs("READ_MM2S_ABORT")) read_fault_case(0);
        if ($test$plusargs("READ_R_BACKPRESSURE")) read_fault_case(1);
        if ($test$plusargs("READ_RRESP_SLVERR")) read_fault_case(2);
        if ($test$plusargs("READ_RRESP_DECERR")) read_fault_case(3);

        if ($test$plusargs("WRITE_RESET_AW_ONLY")) begin
            reset_and_reload_aw_case();
        end
        if ($test$plusargs("WRITE_RESET_B_ONLY")) begin
            reset_and_reload_b_case();
        end
        if ($test$plusargs("WRITE_RESET_BOTH_ONLY")) begin
            reset_and_reload_both_case();
        end
        if ($test$plusargs("FAULT_PARTIAL_W")) begin
            reset_and_reload_partial_w_case();
        end
        if ($test$plusargs("FAULT_TLAST_ABORT")) begin
            reset_and_reload_tlast_abort_case();
        end
        if ($test$plusargs("FAULT_PERSISTENT")) begin
            run_persistent_hp0_stall_case();
        end
        if ($test$plusargs("FAULT_BRESP")) begin
            run_bresp_error_and_reload_case();
        end

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
