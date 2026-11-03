`timescale 1ns/1ps

module tb_z100_sync_reset_wrapper;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg [31:0] r0 = 0, r1 = 0, r2 = 0, r3 = 0;
    reg [31:0] s_data = 0;
    reg [3:0] s_keep = 4'hf;
    reg s_valid = 0, s_last = 0, m_ready = 0;
    wire s_ready, m_valid, m_last, finish;
    wire [31:0] m_data;
    wire [3:0] m_keep;
    integer timeout;

    yolo_accel_top dut (
        .sclk(clk), .s_rst_n(rst_n),
        .slave_lite_reg0(r0), .slave_lite_reg1(r1),
        .slave_lite_reg2(r2), .slave_lite_reg3(r3),
        .s_axis_mm2s_tdata(s_data), .s_axis_mm2s_tkeep(s_keep),
        .s_axis_mm2s_tvalid(s_valid), .s_axis_mm2s_tready(s_ready),
        .s_axis_mm2s_tlast(s_last), .s_axis_s2mm_tdata(m_data),
        .s_axis_s2mm_tkeep(m_keep), .s_axis_s2mm_tvalid(m_valid),
        .s_axis_s2mm_tready(m_ready), .s_axis_s2mm_tlast(m_last),
        .task_finish(finish)
    );

    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk); rst_n = 1;
        // Start a LOAD command, then latch a second start while the core is
        // busy. Reset is asserted mid-cycle; pending registers must hold their
        // value until the next active clock edge, then clear synchronously.
        @(negedge clk);
        r0 = 32'h11; r1 = 32'h00110001; r2 = 32'h55; r3 = 32'h66;
        @(posedge clk); #1;
        r0 = 0;
        @(posedge clk); #1; // first pending start is accepted; core is busy.
        @(negedge clk);
        r0 = 32'h21; r1 = 32'h00010001; r2 = 32'h77; r3 = 32'h88;
        @(posedge clk); #1;
        r0 = 0;
        if (!dut.start_pending)
            $fatal(1, "wrapper failed to hold a pending start while busy");

        #2; rst_n = 0; #1;
        if (!dut.start_pending || dut.start_prev !== 1'b1)
            $fatal(1, "wrapper reset changed pending registers before clock");
        @(posedge clk); #1;
        if (dut.start_pending || dut.start_prev !== 1'b0 ||
            dut.opcode_pending !== 3'b0 ||
            dut.r1_pending !== 32'b0 || dut.sequence_pending !== 32'b0 ||
            dut.filter_pending !== 32'b0 || finish !== 1'b0)
            $fatal(1, "wrapper pending registers did not clear synchronously");
        repeat (2) @(posedge clk);
        @(negedge clk); rst_n = 1;
        #1;
        if (dut.start_pending || dut.core.state !== 4'd0)
            $fatal(1, "stale wrapper command survived reset");
        $display("PASS wrapper pending start reset clears only on active edge");
        $finish;
    end

    initial begin
        #10000; $fatal(1, "wrapper reset test timeout");
    end
endmodule
