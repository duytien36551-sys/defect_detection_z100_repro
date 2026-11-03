`timescale 1ns/1ps

// Isolated multiple-outstanding read-order experiment using the generated
// system_axi_dma_0_0 and system_mm2s_response_slice_0 simulation models.
// The memory endpoint is a finite behavioral FIFO; there is deliberately no
// response until at least two bursts have been accepted.
module tb_z100_axi_order;
    localparam integer TRANSFER_BYTES = 1024;
    localparam integer TRANSFER_WORDS = TRANSFER_BYTES / 4;
    localparam integer QDEPTH = 16;
    localparam [31:0] BASE_ADDR = 32'h00001000;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;

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

    wire [31:0] dma_mm_araddr;
    wire [7:0] dma_mm_arlen;
    wire [2:0] dma_mm_arsize;
    wire [1:0] dma_mm_arburst;
    wire [2:0] dma_mm_arprot;
    wire [3:0] dma_mm_arcache;
    wire dma_mm_arvalid;
    wire dma_mm_arready;
    wire [31:0] dma_mm_rdata;
    wire [1:0] dma_mm_rresp;
    wire dma_mm_rlast;
    wire dma_mm_rvalid;
    wire dma_mm_rready;
    wire dma_reset_out_n;
    wire [31:0] axis_tdata;
    wire [3:0] axis_tkeep;
    wire axis_tvalid;
    wire axis_tlast;
    wire mm2s_introut;
    wire s2mm_introut;
    wire [31:0] dma_tstvec;

    wire [31:0] dma_sm_awaddr;
    wire [7:0] dma_sm_awlen;
    wire [2:0] dma_sm_awsize;
    wire [1:0] dma_sm_awburst;
    wire [2:0] dma_sm_awprot;
    wire [3:0] dma_sm_awcache;
    wire dma_sm_awvalid;
    wire dma_sm_wlast;
    wire [31:0] dma_sm_wdata;
    wire [3:0] dma_sm_wstrb;
    wire dma_sm_wvalid;
    wire dma_sm_bready;
    wire s2mm_reset_out_n;
    wire s2mm_tready;

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
        .m_axi_mm2s_araddr(dma_mm_araddr), .m_axi_mm2s_arlen(dma_mm_arlen),
        .m_axi_mm2s_arsize(dma_mm_arsize), .m_axi_mm2s_arburst(dma_mm_arburst),
        .m_axi_mm2s_arprot(dma_mm_arprot), .m_axi_mm2s_arcache(dma_mm_arcache),
        .m_axi_mm2s_arvalid(dma_mm_arvalid), .m_axi_mm2s_arready(dma_mm_arready),
        .m_axi_mm2s_rdata(dma_mm_rdata), .m_axi_mm2s_rresp(dma_mm_rresp),
        .m_axi_mm2s_rlast(dma_mm_rlast), .m_axi_mm2s_rvalid(dma_mm_rvalid),
        .m_axi_mm2s_rready(dma_mm_rready), .mm2s_prmry_reset_out_n(dma_reset_out_n),
        .m_axis_mm2s_tdata(axis_tdata), .m_axis_mm2s_tkeep(axis_tkeep),
        .m_axis_mm2s_tvalid(axis_tvalid), .m_axis_mm2s_tready(1'b1),
        .m_axis_mm2s_tlast(axis_tlast), .m_axi_s2mm_awaddr(dma_sm_awaddr),
        .m_axi_s2mm_awlen(dma_sm_awlen), .m_axi_s2mm_awsize(dma_sm_awsize),
        .m_axi_s2mm_awburst(dma_sm_awburst), .m_axi_s2mm_awprot(dma_sm_awprot),
        .m_axi_s2mm_awcache(dma_sm_awcache), .m_axi_s2mm_awvalid(dma_sm_awvalid),
        .m_axi_s2mm_awready(1'b0), .m_axi_s2mm_wdata(dma_sm_wdata),
        .m_axi_s2mm_wstrb(dma_sm_wstrb), .m_axi_s2mm_wlast(dma_sm_wlast),
        .m_axi_s2mm_wvalid(dma_sm_wvalid), .m_axi_s2mm_wready(1'b0),
        .m_axi_s2mm_bresp(2'b00), .m_axi_s2mm_bvalid(1'b0),
        .m_axi_s2mm_bready(dma_sm_bready), .s2mm_prmry_reset_out_n(s2mm_reset_out_n),
        .s_axis_s2mm_tdata(32'b0), .s_axis_s2mm_tkeep(4'b0),
        .s_axis_s2mm_tvalid(1'b0), .s_axis_s2mm_tready(s2mm_tready),
        .s_axis_s2mm_tlast(1'b0), .mm2s_introut(mm2s_introut),
        .s2mm_introut(s2mm_introut), .axi_dma_tstvec(dma_tstvec)
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

    assign slice_s_araddr = dma_mm_araddr;
    assign slice_s_arlen = dma_mm_arlen;
    assign slice_s_arsize = dma_mm_arsize;
    assign slice_s_arburst = dma_mm_arburst;
    assign slice_s_arlock = 1'b0;
    assign slice_s_arcache = dma_mm_arcache;
    assign slice_s_arprot = dma_mm_arprot;
    assign slice_s_arregion = 4'b0;
    assign slice_s_arqos = 4'b0;
    assign slice_s_arvalid = dma_mm_arvalid;
    assign dma_mm_arready = slice_s_arready;
    assign dma_mm_rdata = slice_s_rdata;
    assign dma_mm_rresp = slice_s_rresp;
    assign dma_mm_rlast = slice_s_rlast;
    assign dma_mm_rvalid = slice_s_rvalid;
    assign slice_s_rready = dma_mm_rready;

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

    reg [31:0] q_addr [0:QDEPTH-1];
    reg [7:0] q_len [0:QDEPTH-1];
    integer q_wr = 0;
    integer q_rd = 0;
    integer outstanding = 0;
    integer peak_outstanding = 0;
    integer accepted_bursts = 0;
    integer completed_bursts = 0;
    integer returned_beats = 0;
    integer stream_beats = 0;
    integer response_beat = 0;
    integer failures = 0;
    reg response_gate_open = 0;
    reg m_rvalid_r = 0;
    reg [31:0] m_rdata_r = 0;
    reg m_rlast_r = 0;

    assign slice_m_arready = rst_n && outstanding < QDEPTH;
    assign slice_m_rdata = m_rdata_r;
    assign slice_m_rresp = 2'b00;
    assign slice_m_rlast = m_rlast_r;
    assign slice_m_rvalid = m_rvalid_r;

    always @(posedge clk) begin : memory_fifo
        integer slot;
        integer addr_expected;
        reg ar_fire;
        reg r_fire;
        reg rlast_fire;
        if (!rst_n) begin
            q_wr <= 0;
            q_rd <= 0;
            outstanding <= 0;
            peak_outstanding <= 0;
            accepted_bursts <= 0;
            completed_bursts <= 0;
            returned_beats <= 0;
            response_beat <= 0;
            response_gate_open <= 0;
            m_rvalid_r <= 0;
            m_rdata_r <= 0;
            m_rlast_r <= 0;
        end else begin
            ar_fire = slice_m_arvalid && slice_m_arready;
            r_fire = m_rvalid_r && slice_m_rready;
            rlast_fire = r_fire && m_rlast_r;

            if (outstanding >= 2) response_gate_open <= 1;

            if (ar_fire) begin
                slot = q_wr % QDEPTH;
                addr_expected = BASE_ADDR + accepted_bursts * 64;
                if (slice_m_araddr !== addr_expected[31:0]) begin
                    failures = failures + 1;
                    $display("FAIL ORDER_AR_ADDRESS seq=%0d expected=%08x actual=%08x", accepted_bursts, addr_expected, slice_m_araddr);
                end
                if (slice_m_arsize !== 3'd2 || slice_m_arburst !== 2'b01 ||
                    slice_m_arlen !== 8'd15) begin
                    failures = failures + 1;
                    $display("FAIL ORDER_AR_SHAPE seq=%0d len=%0d size=%0d burst=%0d", accepted_bursts, slice_m_arlen, slice_m_arsize, slice_m_arburst);
                end
                q_addr[slot] <= slice_m_araddr;
                q_len[slot] <= slice_m_arlen;
                q_wr <= q_wr + 1;
                accepted_bursts <= accepted_bursts + 1;
                $display("AXI_ORDER_AR seq=%0d addr=%08x beats=%0d id=none", accepted_bursts, slice_m_araddr, slice_m_arlen + 1);
            end

            if (r_fire) begin
                if (m_rdata_r !== q_addr[q_rd % QDEPTH] + response_beat * 4) begin
                    failures = failures + 1;
                    $display("FAIL ORDER_R_DATA seq=%0d beat=%0d expected=%08x actual=%08x", q_rd, response_beat, q_addr[q_rd % QDEPTH] + response_beat * 4, m_rdata_r);
                end
                if (m_rlast_r !== (response_beat == q_len[q_rd % QDEPTH])) begin
                    failures = failures + 1;
                    $display("FAIL ORDER_R_LAST seq=%0d beat=%0d last=%0d", q_rd, response_beat, m_rlast_r);
                end
                $display("AXI_ORDER_R seq=%0d beat=%0d data=%08x last=%0d id=none", q_rd, response_beat, m_rdata_r, m_rlast_r);
                returned_beats <= returned_beats + 1;
                m_rvalid_r <= 0;
                if (rlast_fire) begin
                    q_rd <= q_rd + 1;
                    outstanding <= outstanding + (ar_fire ? 0 : -1);
                    response_beat <= 0;
                    completed_bursts <= completed_bursts + 1;
                end else begin
                    if (ar_fire) outstanding <= outstanding + 1;
                    response_beat <= response_beat + 1;
                end
            end else if (ar_fire) begin
                outstanding <= outstanding + 1;
            end

            if (!m_rvalid_r && outstanding > 0 && response_gate_open) begin
                m_rvalid_r <= 1;
                m_rdata_r <= q_addr[q_rd % QDEPTH] + response_beat * 4;
                m_rlast_r <= response_beat == q_len[q_rd % QDEPTH];
            end

            if (ar_fire && outstanding + (rlast_fire ? 0 : 1) > peak_outstanding)
                peak_outstanding <= outstanding + (rlast_fire ? 0 : 1);
        end
    end

    always @(posedge clk) begin
        if (rst_n && axis_tvalid) begin
            if (axis_tkeep !== 4'hf) begin
                failures = failures + 1;
                $display("FAIL ORDER_AXIS_KEEP beat=%0d keep=%h", stream_beats, axis_tkeep);
            end
            if (axis_tdata !== BASE_ADDR + stream_beats * 4) begin
                failures = failures + 1;
                $display("FAIL ORDER_AXIS_DATA beat=%0d expected=%08x actual=%08x", stream_beats, BASE_ADDR + stream_beats * 4, axis_tdata);
            end
            if (axis_tlast !== (stream_beats == TRANSFER_WORDS-1)) begin
                failures = failures + 1;
                $display("FAIL ORDER_AXIS_LAST beat=%0d last=%0d", stream_beats, axis_tlast);
            end
            $display("AXI_ORDER_AXIS beat=%0d data=%08x last=%0d", stream_beats, axis_tdata, axis_tlast);
            stream_beats <= stream_beats + 1;
        end
    end

    task fail;
        input [8*120-1:0] message;
        begin
            failures = failures + 1;
            $display("FAIL %0s", message);
        end
    endtask

    task dma_write;
        input [9:0] addr;
        input [31:0] data;
        reg aw_done;
        reg w_done;
        integer t;
        begin
            @(negedge clk);
            dma_awaddr = addr; dma_wdata = data;
            dma_awvalid = 1; dma_wvalid = 1; dma_bready = 0;
            aw_done = 0; w_done = 0; t = 0;
            while (!(aw_done && w_done) && t < 200) begin
                @(posedge clk);
                if (dma_awvalid && dma_awready) aw_done = 1;
                if (dma_wvalid && dma_wready) w_done = 1;
                @(negedge clk);
                if (aw_done) dma_awvalid = 0;
                if (w_done) dma_wvalid = 0;
                t = t + 1;
            end
            if (!(aw_done && w_done)) fail("AXI-Lite write address/data timeout");
            dma_bready = 1;
            t = 0;
            while (!dma_bvalid && t < 200) begin @(posedge clk); t = t + 1; end
            if (!dma_bvalid || dma_bresp != 0) fail("AXI-Lite write response timeout/error");
            @(negedge clk); dma_bready = 0;
        end
    endtask

    task dma_read;
        input [9:0] addr;
        output [31:0] data;
        integer t;
        begin
            @(negedge clk); dma_araddr = addr; dma_arvalid = 1; dma_rready = 0;
            t = 0;
            while (!dma_arready && t < 200) begin @(posedge clk); t = t + 1; end
            if (!dma_arready) fail("AXI-Lite read address timeout");
            @(negedge clk); dma_arvalid = 0; dma_rready = 1;
            t = 0;
            while (!dma_rvalid && t < 200) begin @(posedge clk); t = t + 1; end
            if (!dma_rvalid || dma_rresp != 0) fail("AXI-Lite read response timeout/error");
            data = dma_rdata;
            @(negedge clk); dma_rready = 0;
        end
    endtask

    integer t;
    reg [31:0] status;
    initial begin
        repeat (32) @(posedge clk);
        rst_n = 1;
        repeat (20) @(posedge clk);

        dma_write(10'h000, 32'h00000001);
        dma_write(10'h018, BASE_ADDR);
        dma_write(10'h028, TRANSFER_BYTES);

        t = 0;
        while (stream_beats < TRANSFER_WORDS && t < 10000) begin
            @(posedge clk);
            t = t + 1;
        end
        if (stream_beats != TRANSFER_WORDS) fail("stream did not complete after ordered responses");
        if (peak_outstanding < 2) fail("actual DMA/slice did not accept multiple reads before first response");

        t = 0; status = 0;
        while ((status & 32'h00001002) != 32'h00001002 && t < 500) begin
            dma_read(10'h004, status);
            t = t + 1;
        end
        if ((status & 32'h00001002) != 32'h00001002) fail("MM2S completion/idle not observed");
        if (status & 32'h00000770) fail("MM2S status reports error");
        if (accepted_bursts != completed_bursts || outstanding != 0)
            fail("read queue did not drain to a closed fence");
        if (returned_beats != TRANSFER_WORDS || stream_beats != TRANSFER_WORDS)
            fail("read/stream beat totals do not match transfer length");

        if (failures != 0) begin
            $display("FAIL AXI_ORDER_TEST failures=%0d accepted=%0d completed=%0d peak=%0d", failures, accepted_bursts, completed_bursts, peak_outstanding);
            $finish;
        end
        $display("COVERAGE AXI_ORDER accepted=%0d completed=%0d returned_beats=%0d stream_beats=%0d peak_outstanding=%0d id_width=0", accepted_bursts, completed_bursts, returned_beats, stream_beats, peak_outstanding);
        $display("SOURCE_CHAIN actual=system_axi_dma_0_0+system_mm2s_response_slice_0 models=ordered_fifo_memory+axil_master+axis_sink");
        $display("PASS z100 actual DMA/slice multiple-outstanding ordered read");
        $finish;
    end

    initial begin
        #200000;
        $display("FAIL AXI_ORDER_TEST global timeout accepted=%0d completed=%0d peak=%0d", accepted_bursts, completed_bursts, peak_outstanding);
        $finish;
    end
endmodule
