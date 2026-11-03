`timescale 1ns/1ps
module tb_v8_tile16_axis;
    reg clk = 0;
    always #3 clk = ~clk;
    reg rst_n = 0, cfg_start = 0, cfg_abort = 0;
    reg [2:0] cfg_opcode = 0;
    reg [31:0] cfg_r1 = 0, cfg_sequence = 0, cfg_filter_id = 0;
    wire cfg_ready, cfg_error;
    reg [31:0] s_axis_tdata = 0;
    reg [3:0] s_axis_tkeep = 4'hf;
    reg s_axis_tvalid = 0, s_axis_tlast = 0;
    wire s_axis_tready;
    wire [31:0] m_axis_tdata;
    wire m_axis_tvalid, m_axis_tlast;
    reg m_axis_tready = 0;
    integer i;

    v8_tile16_axis dut(
        .clk(clk), .rst_n(rst_n), .cfg_start(cfg_start),
        .cfg_abort(cfg_abort), .cfg_opcode(cfg_opcode),
        .cfg_r1(cfg_r1), .cfg_sequence(cfg_sequence),
        .cfg_filter_id(cfg_filter_id), .cfg_ready(cfg_ready),
        .cfg_error(cfg_error), .s_axis_tdata(s_axis_tdata),
        .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
        .s_axis_tlast(s_axis_tlast), .m_axis_tdata(m_axis_tdata),
        .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
        .m_axis_tlast(m_axis_tlast)
    );

    task command;
        input [2:0] op;
        input [31:0] r1, seq, fid;
        begin
            @(negedge clk);
            if (!cfg_ready) $fatal(1, "command not ready");
            cfg_opcode = op; cfg_r1 = r1;
            cfg_sequence = seq; cfg_filter_id = fid;
            cfg_start = 1;
            @(negedge clk); cfg_start = 0;
        end
    endtask
    task send_word;
        input [31:0] data;
        input last;
        begin
            @(negedge clk);
            s_axis_tdata = data; s_axis_tlast = last; s_axis_tvalid = 1;
            while (!s_axis_tready) @(negedge clk);
            @(negedge clk); s_axis_tvalid = 0; s_axis_tlast = 0;
        end
    endtask
    task recv_word;
        input [31:0] expected;
        input last;
        begin
            @(negedge clk);
            while (!m_axis_tvalid) @(negedge clk);
            if (m_axis_tdata !== expected || m_axis_tlast !== last)
                $fatal(1, "response got=%h last=%b expected=%h last=%b",
                       m_axis_tdata, m_axis_tlast, expected, last);
            m_axis_tready = 1;
            @(negedge clk); m_axis_tready = 0;
        end
    endtask

    initial begin
        #20; rst_n = 1;
        command(0, 0, 11, 7);
        recv_word(32'h563b0001, 0);
        recv_word(11, 0);
        recv_word(7, 0);
        recv_word(0, 0);
        recv_word(0, 1);

        // T=3, L=2. Weights are (+1,+2,+3) and (-1,-2,-3).
        command(1, 32'h00020003, 12, 7);
        for (i = 0; i < 16; i = i + 1)
            send_word(0, 0);
        send_word(32'h0000ff01, 0);
        send_word(0, 0); send_word(0, 0); send_word(0, 0);
        send_word(32'h0000fe02, 0);
        send_word(0, 0); send_word(0, 0); send_word(0, 0);
        send_word(32'h0000fd03, 0);
        send_word(0, 0); send_word(0, 0); send_word(0, 1);
        recv_word(32'h563b0001, 0);
        recv_word(12, 0); recv_word(7, 0);
        recv_word(32'h00020003, 0); recv_word(0, 1);

        command(2, 32'h02020003, 13, 7);
        send_word(32'h00030201, 0);
        send_word(32'h00060504, 1);
        recv_word(32'h563b0001, 0);
        recv_word(13, 0); recv_word(7, 0);
        recv_word(32'h02020003, 0);
        recv_word(14, 0); recv_word(-14, 0);
        recv_word(32, 0); recv_word(-32, 0);
        recv_word(0, 1);
        if (cfg_error) $fatal(1, "unexpected cfg_error");

        // Wrong filter identity must be rejected, with a complete response
        // frame so the S2MM side can finish instead of waiting forever.
        command(2, 32'h01020003, 14, 8);
        send_word(32'h00030201, 1);
        recv_word(32'h563b0001, 0);
        recv_word(14, 0); recv_word(8, 0);
        recv_word(32'h01020003, 0);
        recv_word(0, 0); recv_word(0, 0);
        recv_word(1, 1);
        if (!cfg_error) $fatal(1, "mismatched filter did not error");

        command(1, 32'h00010001, 15, 9);
        s_axis_tkeep = 4'h7;
        send_word(0, 0);
        s_axis_tkeep = 4'hf;
        send_word(0, 1);
        recv_word(32'h563b0001, 0);
        recv_word(15, 0); recv_word(9, 0);
        recv_word(32'h00010001, 0); recv_word(1, 1);
        if (!cfg_error) $fatal(1, "short TKEEP did not error");
        $display("PASS v8_tile16_axis probe/load/run/backpressure/error frames");
        $finish;
    end
    initial begin
        #200000; $fatal(1, "timeout");
    end
endmodule
