`timescale 1ns/1ps

module tb_v8_tile64_axis;
    localparam integer MAX_TAPS = 4091;
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
    integer i, lane_i, site_i, tap_i, word_i, byte_i;
    integer expected_value, activation_value, weight_value;
    reg [31:0] r1_local, data_local, weight_word;

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

    function [31:0] make_r1;
        input integer taps, lanes, sites;
        begin make_r1 = (sites << 24) | (lanes << 16) | taps; end
    endfunction

    function integer bias_for;
        input integer lane;
        begin bias_for = lane - 32; end
    endfunction

    function integer simple_weight_for;
        input integer lane;
        begin simple_weight_for = (lane % 7) - 3; end
    endfunction

    function integer max_weight_for;
        input integer tap, lane;
        begin max_weight_for = ((tap * 3 + lane * 5) % 7) - 3; end
    endfunction

    function integer activation_for;
        input integer site;
        begin activation_for = ((site % 3) + 1); end
    endfunction

    task fail;
        input [8*120-1:0] message;
        begin $display("FAIL %0s at %0t", message, $time); $fatal(1); end
    endtask

    task command;
        input [2:0] op;
        input [31:0] r1, seq, fid;
        begin
            @(negedge clk);
            while (!cfg_ready) @(negedge clk);
            cfg_opcode = op; cfg_r1 = r1;
            cfg_sequence = seq; cfg_filter_id = fid; cfg_start = 1;
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
            @(posedge clk);
            @(negedge clk); s_axis_tvalid = 0; s_axis_tlast = 0;
        end
    endtask

    task recv_word;
        input [31:0] expected;
        input last;
        input integer stall_cycles;
        integer k;
        begin
            @(negedge clk);
            while (!m_axis_tvalid) @(negedge clk);
            #1;
            if (m_axis_tdata !== expected || m_axis_tlast !== last) begin
                $display("got data=%08x last=%b expected=%08x last=%b",
                    m_axis_tdata, m_axis_tlast, expected, last);
                fail("response word mismatch");
            end
            for (k = 0; k < stall_cycles; k = k + 1) begin
                @(posedge clk); #1;
                if (!m_axis_tvalid || m_axis_tdata !== expected ||
                    m_axis_tlast !== last)
                    fail("response changed while backpressured");
            end
            @(negedge clk); m_axis_tready = 1;
            @(posedge clk);
            @(negedge clk); m_axis_tready = 0;
        end
    endtask

    task recv_header;
        input [31:0] r1, seq, fid;
        begin
            recv_word(32'h564c0001, 0, 2);
            recv_word(seq, 0, 0);
            recv_word(fid, 0, 0);
            recv_word(r1, 0, 0);
        end
    endtask

    task load_simple_model;
        input integer lanes;
        input [31:0] seq, fid;
        integer bias_lane, wi, bi, lane;
        reg [31:0] load_r1, current_word;
        begin
            load_r1 = make_r1(1, lanes, 0);
            command(1, load_r1, seq, fid);
            for (bias_lane = 0; bias_lane < 64; bias_lane = bias_lane + 1)
                send_word(bias_for(bias_lane), 0);
            for (wi = 0; wi < 16; wi = wi + 1) begin
                current_word = 0;
                for (bi = 0; bi < 4; bi = bi + 1) begin
                    lane = wi * 4 + bi;
                    current_word[bi*8 +: 8] = simple_weight_for(lane);
                end
                send_word(current_word, wi == 15);
            end
            recv_header(load_r1, seq, fid);
            recv_word(0, 1, 0);
            if (cfg_error) fail("valid simple LOAD raised cfg_error");
        end
    endtask

    task run_simple_model;
        input integer lanes, sites;
        input [31:0] seq, fid;
        integer s, l;
        reg [31:0] run_r1, activation_word;
        begin
            run_r1 = make_r1(1, lanes, sites);
            command(2, run_r1, seq, fid);
            for (s = 0; s < sites; s = s + 1) begin
                activation_word = activation_for(s);
                send_word(activation_word, s == sites - 1);
            end
            recv_header(run_r1, seq, fid);
            for (s = 0; s < sites; s = s + 1) begin
                activation_value = activation_for(s);
                for (l = 0; l < lanes; l = l + 1) begin
                    expected_value = bias_for(l) +
                        activation_value * simple_weight_for(l);
                    recv_word(expected_value, 0, (s == 0 && l == 0) ? 2 : 0);
                end
            end
            recv_word(0, 1, 0);
            if (cfg_error) fail("valid simple RUN raised cfg_error");
            $display("PASS AXIS simple LOAD/RUN lanes=%0d sites=%0d", lanes, sites);
        end
    endtask

    task load_max_tap_model;
        input [31:0] seq, fid;
        integer lane, tap, wi, bi;
        reg [31:0] load_r1, current_word;
        begin
            load_r1 = make_r1(MAX_TAPS, 64, 0);
            command(1, load_r1, seq, fid);
            for (lane = 0; lane < 64; lane = lane + 1)
                send_word(bias_for(lane), 0);
            for (tap = 0; tap < MAX_TAPS; tap = tap + 1) begin
                for (wi = 0; wi < 16; wi = wi + 1) begin
                    current_word = 0;
                    for (bi = 0; bi < 4; bi = bi + 1) begin
                        lane = wi * 4 + bi;
                        current_word[bi*8 +: 8] = max_weight_for(tap, lane);
                    end
                    send_word(current_word,
                        tap == MAX_TAPS - 1 && wi == 15);
                end
            end
            recv_header(load_r1, seq, fid);
            recv_word(0, 1, 0);
            if (cfg_error) fail("4091-tap 64-lane LOAD raised cfg_error");
            $display("PASS AXIS LOAD transported all 4091 taps x 64 weights");
        end
    endtask

    task run_max_tap_model;
        input [31:0] seq, fid;
        integer wi, bi, lane, tap, expected_sum;
        reg [31:0] run_r1;
        begin
            run_r1 = make_r1(MAX_TAPS, 64, 1);
            command(2, run_r1, seq, fid);
            for (wi = 0; wi < 1023; wi = wi + 1)
                send_word(32'h01010101, wi == 1022);
            recv_header(run_r1, seq, fid);
            for (lane = 0; lane < 64; lane = lane + 1) begin
                expected_sum = bias_for(lane);
                for (tap = 0; tap < MAX_TAPS; tap = tap + 1)
                    expected_sum = expected_sum + max_weight_for(tap, lane);
                recv_word(expected_sum, 0, lane == 0 ? 2 : 0);
            end
            recv_word(0, 1, 0);
            if (cfg_error) fail("4091-tap RUN raised cfg_error");
            $display("PASS AXIS RUN consumed all 4091 taps for 64 lanes");
        end
    endtask

    task test_bad_load_recovery;
        reg [31:0] bad_r1;
        begin
            bad_r1 = make_r1(1, 64, 0);
            command(1, bad_r1, 100, 7);
            send_word(32'h12345678, 1);
            recv_header(bad_r1, 100, 7);
            recv_word(32'h00000021, 1, 0);
            if (!cfg_error) fail("early-TLAST LOAD did not report cfg_error");
            load_simple_model(64, 101, 7);
            run_simple_model(64, 2, 102, 7);
            $display("PASS AXIS malformed LOAD response and recovery");
        end
    endtask

    task test_invalid_header_recovery;
        reg [31:0] bad_r1;
        begin
            bad_r1 = make_r1(1, 65, 0);
            command(1, bad_r1, 105, 8);
            send_word(32'h0, 1);
            recv_header(bad_r1, 105, 8);
            recv_word(32'h00000011, 1, 0);
            if (!cfg_error) fail("lane count 65 was not rejected");

            bad_r1 = make_r1(1, 64, 0) | 32'h00800000;
            command(1, bad_r1, 106, 8);
            send_word(32'h0, 1);
            recv_header(bad_r1, 106, 8);
            recv_word(32'h00000011, 1, 0);
            if (!cfg_error) fail("reserved R1 bit 23 was not rejected");

            load_simple_model(64, 107, 8);
            run_simple_model(64, 2, 108, 8);
            $display("PASS AXIS 7-bit lane limit, reserved-bit rejection, and recovery");
        end
    endtask

    task test_overflow_lane63;
        integer b, wi, bi, lane;
        reg [31:0] load_r1, run_r1, current_word;
        begin
            load_r1 = make_r1(1, 64, 0);
            command(1, load_r1, 110, 12);
            for (b = 0; b < 64; b = b + 1)
                send_word(b == 63 ? 32'h7fffffff : bias_for(b), 0);
            for (wi = 0; wi < 16; wi = wi + 1) begin
                current_word = 0;
                for (bi = 0; bi < 4; bi = bi + 1) begin
                    lane = wi * 4 + bi;
                    current_word[bi*8 +: 8] = (lane == 63) ? 1 : 0;
                end
                send_word(current_word, wi == 15);
            end
            recv_header(load_r1, 110, 12);
            recv_word(0, 1, 0);

            run_r1 = make_r1(1, 64, 1);
            command(2, run_r1, 111, 12);
            send_word(32'd1, 1);
            recv_header(run_r1, 111, 12);
            for (lane = 0; lane < 64; lane = lane + 1)
                recv_word(0, 0, lane == 0 ? 2 : 0);
            recv_word(32'h00010041, 1, 0);
            if (!cfg_error) fail("lane 63 overflow was not reported");
            $display("PASS AXIS lane 63 overflow diagnostics and zeroed error payload");
        end
    endtask

    task test_abort_recovery;
        reg [31:0] pending_r1;
        begin
            pending_r1 = make_r1(1, 64, 0);
            command(1, pending_r1, 120, 13);
            repeat (3) @(negedge clk);
            cfg_abort = 1;
            @(negedge clk); cfg_abort = 0;
            @(negedge clk);
            if (!cfg_ready || !cfg_error || m_axis_tvalid)
                fail("abort did not return AXIS to idle with error");
            load_simple_model(17, 121, 13);
            run_simple_model(17, 2, 122, 13);
            $display("PASS AXIS abort and fresh command recovery");
        end
    endtask

    task test_reset_recovery;
        reg [31:0] run_r1;
        begin
            load_simple_model(17, 130, 14);
            run_r1 = make_r1(1, 17, 64);
            command(2, run_r1, 131, 14);
            send_word(activation_for(0), 0);
            repeat (3) @(negedge clk);

            // Reset while the RUN is incomplete and the MAC pipeline is active.
            rst_n = 0;
            repeat (2) @(negedge clk);
            #1;
            if (m_axis_tvalid || cfg_error)
                fail("reset did not clear active response/error state");
            rst_n = 1;
            repeat (3) @(negedge clk);

            // Reset also invalidates loaded weights; a fresh LOAD must be required.
            load_simple_model(17, 132, 14);
            run_simple_model(17, 2, 133, 14);
            $display("PASS AXIS reset during active RUN and fresh LOAD/RUN recovery");
        end
    endtask

    initial begin
        #18; rst_n = 1;

        command(0, 0, 11, 7);
        recv_header(0, 11, 7);
        recv_word(0, 1, 0);

        // Exercise nonaligned lane tails and all 4096 result-memory entries.
        load_simple_model(17, 12, 8);
        run_simple_model(17, 2, 13, 8);
        load_simple_model(33, 14, 9);
        run_simple_model(33, 2, 15, 9);
        load_simple_model(63, 16, 10);
        run_simple_model(63, 2, 17, 10);
        load_simple_model(64, 18, 11);
        run_simple_model(64, 64, 19, 11);

        load_max_tap_model(20, 12);
        run_max_tap_model(21, 12);

        test_invalid_header_recovery;
        test_bad_load_recovery;
        test_overflow_lane63;
        test_abort_recovery;
        test_reset_recovery;

        $display("PASS v8_tile64_axis ABI, 4096 results, max taps, tails, error/abort recovery, and backpressure");
        $finish;
    end

    initial begin
        #30000000; $fatal(1, "AXIS test timeout");
    end
endmodule
