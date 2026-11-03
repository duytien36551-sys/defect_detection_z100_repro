`timescale 1ns/1ps

module tb_actual_filter17;
    localparam integer LOAD_WORDS = 2112;
    localparam integer RUN_WORDS = 2048;
    localparam integer RESULT_WORDS = 4096;
    localparam [31:0] LOAD_R1 = 32'h00400080;
    localparam [31:0] RUN_R1 = 32'h40400080;
    localparam [31:0] FILTER_ID = 32'd17;
    localparam [31:0] LOAD_SEQUENCE = 32'd1872;
    localparam [31:0] RUN_SEQUENCE = 32'd1873;

    reg clk = 0;
    always #3 clk = ~clk;
    reg rst_n = 0;
    reg cfg_start = 0, cfg_abort = 0;
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

    reg [31:0] load_words [0:LOAD_WORDS-1];
    reg [31:0] run_words [0:RUN_WORDS-1];
    reg [31:0] expected_words [0:RESULT_WORDS-1];
    string load_path, run_path, expected_path, vector_label;
    integer i;

    v8_tile64_axis dut (
        .clk(clk), .rst_n(rst_n), .cfg_start(cfg_start),
        .cfg_abort(cfg_abort), .cfg_opcode(cfg_opcode),
        .cfg_r1(cfg_r1), .cfg_sequence(cfg_sequence),
        .cfg_filter_id(cfg_filter_id), .cfg_ready(cfg_ready),
        .cfg_error(cfg_error), .s_axis_tdata(s_axis_tdata),
        .s_axis_tkeep(s_axis_tkeep), .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready), .s_axis_tlast(s_axis_tlast),
        .m_axis_tdata(m_axis_tdata), .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready), .m_axis_tlast(m_axis_tlast)
    );

    task fail;
        input [8*160-1:0] message;
        begin
            $display("FAIL %0s at %0t", message, $time);
            $fatal(1);
        end
    endtask

    task verify_word_count;
        input string path;
        input integer expected_count;
        integer fd, scan_result, count;
        reg [8*256-1:0] token;
        begin
            fd = $fopen(path, "r");
            if (fd == 0) fail("could not open vector file for length check");
            count = 0;
            scan_result = 1;
            while (scan_result == 1) begin
                scan_result = $fscanf(fd, "%s", token);
                if (scan_result == 1) count = count + 1;
            end
            $fclose(fd);
            if (count != expected_count) begin
                $display("vector count mismatch: %0s has %0d words, expected %0d",
                    path, count, expected_count);
                fail("vector file has an incorrect word count");
            end
        end
    endtask

    task command;
        input [2:0] op;
        input [31:0] r1, seq, fid;
        begin
            @(negedge clk);
            while (!cfg_ready) @(negedge clk);
            cfg_opcode = op;
            cfg_r1 = r1;
            cfg_sequence = seq;
            cfg_filter_id = fid;
            cfg_start = 1;
            @(negedge clk);
            cfg_start = 0;
        end
    endtask

    task send_word;
        input [31:0] data;
        input last;
        begin
            @(negedge clk);
            s_axis_tdata = data;
            s_axis_tlast = last;
            s_axis_tvalid = 1;
            while (!s_axis_tready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            s_axis_tvalid = 0;
            s_axis_tlast = 0;
        end
    endtask

    task recv_word;
        input [31:0] expected;
        input last;
        input integer stall_cycles;
        input integer result_index;
        integer k;
        begin
            @(negedge clk);
            while (!m_axis_tvalid) @(negedge clk);
            #1;
            if (m_axis_tdata !== expected || m_axis_tlast !== last) begin
                $display("response index=%0d got=%08x last=%b expected=%08x last=%b",
                    result_index, m_axis_tdata, m_axis_tlast, expected, last);
                fail("response word mismatch");
            end
            for (k = 0; k < stall_cycles; k = k + 1) begin
                @(posedge clk);
                #1;
                if (!m_axis_tvalid || m_axis_tdata !== expected ||
                    m_axis_tlast !== last)
                    fail("response changed while backpressured");
            end
            @(negedge clk);
            m_axis_tready = 1;
            @(posedge clk);
            @(negedge clk);
            m_axis_tready = 0;
        end
    endtask

    task recv_header;
        input [31:0] r1, seq, fid;
        begin
            recv_word(32'h564c0001, 0, 2, -4);
            recv_word(seq, 0, 0, -3);
            recv_word(fid, 0, 0, -2);
            recv_word(r1, 0, 0, -1);
        end
    endtask

    task recv_success_status;
        begin
            recv_word(32'h00000000, 1, 0, -5);
            if (cfg_error) fail("successful LOAD/RUN set cfg_error");
        end
    endtask

    initial begin
        if (!$value$plusargs("LOAD=%s", load_path))
            fail("missing +LOAD=<hex-file>");
        if (!$value$plusargs("RUN=%s", run_path))
            fail("missing +RUN=<hex-file>");
        if (!$value$plusargs("EXPECTED=%s", expected_path))
            fail("missing +EXPECTED=<hex-file>");
        if (!$value$plusargs("LABEL=%s", vector_label))
            vector_label = "UNLABELLED";

        verify_word_count(load_path, LOAD_WORDS);
        verify_word_count(run_path, RUN_WORDS);
        verify_word_count(expected_path, RESULT_WORDS);
        for (i = 0; i < LOAD_WORDS; i = i + 1)
            load_words[i] = 32'hxxxxxxxx;
        for (i = 0; i < RUN_WORDS; i = i + 1)
            run_words[i] = 32'hxxxxxxxx;
        for (i = 0; i < RESULT_WORDS; i = i + 1)
            expected_words[i] = 32'hxxxxxxxx;
        $readmemh(load_path, load_words);
        $readmemh(run_path, run_words);
        $readmemh(expected_path, expected_words);
        for (i = 0; i < LOAD_WORDS; i = i + 1)
            if ((^load_words[i]) === 1'bx) fail("LOAD vector contains an unknown word");
        for (i = 0; i < RUN_WORDS; i = i + 1)
            if ((^run_words[i]) === 1'bx) fail("RUN vector contains an unknown word");
        for (i = 0; i < RESULT_WORDS; i = i + 1)
            if ((^expected_words[i]) === 1'bx)
                fail("expected output contains an unknown word");

        $display("Vector label=%0s; LOAD=%0s (%0d words), RUN=%0s (%0d words), EXPECTED=%0s (%0d words)",
            vector_label, load_path, LOAD_WORDS, run_path, RUN_WORDS, expected_path, RESULT_WORDS);
        #18;
        rst_n = 1;

        command(3'd1, LOAD_R1, LOAD_SEQUENCE, FILTER_ID);
        for (i = 0; i < LOAD_WORDS; i = i + 1)
            send_word(load_words[i], i == LOAD_WORDS - 1);
        recv_header(LOAD_R1, LOAD_SEQUENCE, FILTER_ID);
        recv_success_status;
        $display("PASS filter17 LOAD [%0s] sequence=%0d, taps=128, lanes=64",
            vector_label, LOAD_SEQUENCE);

        command(3'd2, RUN_R1, RUN_SEQUENCE, FILTER_ID);
        for (i = 0; i < RUN_WORDS; i = i + 1)
            send_word(run_words[i], i == RUN_WORDS - 1);
        recv_header(RUN_R1, RUN_SEQUENCE, FILTER_ID);
        for (i = 0; i < RESULT_WORDS; i = i + 1)
            recv_word(expected_words[i], 0, i == 0 ? 2 : 0, i);
        recv_success_status;
        $display("PASS filter17 RUN [%0s] sequence=%0d, checked %0d site-major INT32 results",
            vector_label, RUN_SEQUENCE, RESULT_WORDS);
        $display("PASS filter17 LOAD+RUN replay [%0s]", vector_label);
        $finish;
    end

    initial begin
        #30000000;
        $fatal(1, "filter17 replay timeout");
    end
endmodule
