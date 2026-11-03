`timescale 1ns/1ps

// Differential stress test: the frozen asynchronous implementation is the
// cycle/byte oracle for normal traffic. Abort/reset windows are checked against
// the new synchronous-reset contract and recovery requirements.
module tb_z100_sync_reset_stress;
    reg clk = 0;
    always #5 clk = ~clk;

    reg rst_n = 0;
    reg cfg_start = 0;
    reg cfg_abort = 0;
    reg [2:0] cfg_opcode = 0;
    reg [31:0] cfg_r1 = 0, cfg_sequence = 0, cfg_filter_id = 0;
    reg [31:0] s_axis_tdata = 0;
    reg [3:0] s_axis_tkeep = 4'hf;
    reg s_axis_tvalid = 0, s_axis_tlast = 0;
    reg m_axis_tready = 0;
    reg compare_enable = 0;

    wire old_cfg_ready, new_cfg_ready;
    wire old_cfg_error, new_cfg_error;
    wire old_s_ready, new_s_ready;
    wire [31:0] old_m_data, new_m_data;
    wire old_m_valid, new_m_valid;
    wire old_m_last, new_m_last;
    integer compared_cycles = 0;
    integer successful_responses = 0;
    integer aborted_scenarios = 0;
    integer reset_scenarios = 0;

    v8_tile64_axis_legacy legacy_dut (
        .clk(clk), .rst_n(rst_n), .cfg_start(cfg_start),
        .cfg_abort(cfg_abort), .cfg_opcode(cfg_opcode), .cfg_r1(cfg_r1),
        .cfg_sequence(cfg_sequence), .cfg_filter_id(cfg_filter_id),
        .cfg_ready(old_cfg_ready), .cfg_error(old_cfg_error),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(old_s_ready),
        .s_axis_tlast(s_axis_tlast), .m_axis_tdata(old_m_data),
        .m_axis_tvalid(old_m_valid), .m_axis_tready(m_axis_tready),
        .m_axis_tlast(old_m_last)
    );

    v8_tile64_axis candidate_dut (
        .clk(clk), .rst_n(rst_n), .cfg_start(cfg_start),
        .cfg_abort(cfg_abort), .cfg_opcode(cfg_opcode), .cfg_r1(cfg_r1),
        .cfg_sequence(cfg_sequence), .cfg_filter_id(cfg_filter_id),
        .cfg_ready(new_cfg_ready), .cfg_error(new_cfg_error),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(new_s_ready),
        .s_axis_tlast(s_axis_tlast), .m_axis_tdata(new_m_data),
        .m_axis_tvalid(new_m_valid), .m_axis_tready(m_axis_tready),
        .m_axis_tlast(new_m_last)
    );

    always @(posedge clk) begin
        #1;
        if (compare_enable) begin
            compared_cycles = compared_cycles + 1;
            if ({old_cfg_ready, old_cfg_error, old_s_ready, old_m_data,
                 old_m_valid, old_m_last} !==
                {new_cfg_ready, new_cfg_error, new_s_ready, new_m_data,
                 new_m_valid, new_m_last}) begin
                $display("legacy state=%0d candidate state=%0d", legacy_dut.state,
                         candidate_dut.state);
                $fatal(1, "legacy/candidate interface cycle mismatch");
            end
        end
    end

    function [31:0] make_r1;
        input integer taps, lanes, sites;
        begin make_r1 = (sites << 24) | (lanes << 16) | taps; end
    endfunction

    function integer bias_for;
        input integer lane;
        begin bias_for = lane - 8; end
    endfunction

    function integer weight_for;
        input integer lane;
        begin weight_for = (lane % 5) - 2; end
    endfunction

    task fail;
        input [8*120-1:0] message;
        begin $display("FAIL %0s at %0t", message, $time); $fatal(1); end
    endtask

    task wait_state;
        input [3:0] wanted;
        integer timeout;
        begin
            timeout = 0;
            while (candidate_dut.state !== wanted && timeout < 20000) begin
                @(posedge clk); #1; timeout = timeout + 1;
            end
            if (candidate_dut.state !== wanted || legacy_dut.state !== wanted)
                fail("timed out waiting for shared protocol state");
        end
    endtask

    task start_command;
        input [2:0] opcode;
        input [31:0] r1, seq, fid;
        begin
            @(negedge clk);
            while (!new_cfg_ready || !old_cfg_ready) @(negedge clk);
            cfg_opcode = opcode; cfg_r1 = r1;
            cfg_sequence = seq; cfg_filter_id = fid; cfg_start = 1;
            @(negedge clk); cfg_start = 0;
        end
    endtask

    task send_word;
        input [31:0] data;
        input last;
        input integer gap_cycles;
        integer g;
        begin
            @(negedge clk);
            for (g = 0; g < gap_cycles; g = g + 1) @(negedge clk);
            s_axis_tdata = data; s_axis_tlast = last; s_axis_tvalid = 1;
            while (!new_s_ready || !old_s_ready) @(negedge clk);
            @(posedge clk);
            @(negedge clk); s_axis_tvalid = 0; s_axis_tlast = 0;
        end
    endtask

    task recv_word;
        input [31:0] expected;
        input last;
        input integer stalls;
        integer n;
        reg [31:0] held;
        begin
            m_axis_tready = 0;
            while (!new_m_valid || !old_m_valid) @(negedge clk);
            #1;
            if (new_m_data !== expected || new_m_last !== last)
                fail("candidate response word differs from expected");
            held = new_m_data;
            for (n = 0; n < stalls; n = n + 1) begin
                @(negedge clk); #1;
                if (!new_m_valid || new_m_data !== held || new_m_last !== last)
                    fail("response changed while backpressured");
            end
            @(negedge clk); m_axis_tready = 1;
            @(posedge clk); #1; m_axis_tready = 0;
            successful_responses = successful_responses + 1;
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

    task load_model17;
        input [31:0] seq, fid;
        integer i, lane;
        reg [31:0] packed_weights;
        begin
            start_command(1, make_r1(1, 17, 0), seq, fid);
            for (i = 0; i < 64; i = i + 1)
                send_word(i < 17 ? bias_for(i) : 0, 0, i % 3);
            for (i = 0; i < 16; i = i + 1) begin
                packed_weights = 0;
                for (lane = 0; lane < 4; lane = lane + 1)
                    packed_weights[lane*8 +: 8] =
                        (i*4 + lane < 17) ? weight_for(i*4 + lane) : 0;
                send_word(packed_weights, i == 15, i % 2);
            end
            recv_header(make_r1(1, 17, 0), seq, fid);
            recv_word(0, 1, 1);
            if (new_cfg_error || old_cfg_error)
                fail("fresh model LOAD raised cfg_error");
        end
    endtask

    task run_model17;
        input [31:0] seq, fid;
        input integer sites;
        integer s, lane;
        reg [31:0] r1;
        begin
            r1 = make_r1(1, 17, sites);
            start_command(2, r1, seq, fid);
            for (s = 0; s < sites; s = s + 1)
                send_word((s == 0) ? 32'h0000007f : 32'h00000080,
                          s == sites - 1, s % 2);
            recv_header(r1, seq, fid);
            for (s = 0; s < sites; s = s + 1)
                for (lane = 0; lane < 17; lane = lane + 1)
                    recv_word(bias_for(lane) +
                              ((s == 0) ? 127 : -128) * weight_for(lane),
                              0, lane % 4 == 0 ? 2 : 0);
            recv_word(0, 1, 1);
            if (new_cfg_error || old_cfg_error)
                fail("normal differential RUN raised cfg_error");
        end
    endtask

    task stale_run_rejected;
        input [31:0] seq, fid;
        reg [31:0] r1;
        begin
            r1 = make_r1(1, 1, 1);
            // Issue the retry on the first edge after abort/reset release.
            @(negedge clk);
            cfg_abort = 0; rst_n = 1; cfg_start = 1;
            cfg_opcode = 2; cfg_r1 = r1; cfg_sequence = seq;
            cfg_filter_id = fid; m_axis_tready = 0;
            @(posedge clk); #1; cfg_start = 0;
            compare_enable = 1;
            wait_state(4'd10); // DRAIN: stale RUN rejected because loaded=0.
            send_word(32'h00000001, 1, 0);
            recv_header(r1, seq, fid);
            recv_word(0, 0, 0);
            recv_word(32'h00000012, 1, 1);
            if (!new_cfg_error || !old_cfg_error)
                fail("stale RUN was not rejected after invalidation");
        end
    endtask

    task recover_after_interruption;
        input [31:0] seq;
        begin
            stale_run_rejected(seq, 32'h00001000 + seq);
            load_model17(seq + 1, 32'h00001000 + seq);
            run_model17(seq + 2, 32'h00001000 + seq, 1);
            compare_enable = 1;
            $display("PASS recovery sequence=%0d stale-RUN rejected, full reload, fresh RUN",
                     seq);
        end
    endtask

    task interrupt_stage;
        input [3:0] stage;
        input integer use_reset;
        input integer phase;
        input integer scenario_id;
        integer edge_i;
        begin
            compare_enable = 1;
            cfg_abort = 0; rst_n = 1; m_axis_tready = 0;
            if (stage == 4'd1) begin
                start_command(1, make_r1(1, 17, 0), scenario_id, 32'h77);
                wait_state(4'd1); // LOAD_BIAS
                send_word(32'h00000003, 0, 0);
                wait_state(4'd1);
            end else if (stage == 4'd4) begin
                start_command(1, make_r1(1, 17, 0), scenario_id, 32'h77);
                for (edge_i = 0; edge_i < 64; edge_i = edge_i + 1)
                    send_word(edge_i, 0, edge_i % 2);
                for (edge_i = 0; edge_i < 16; edge_i = edge_i + 1)
                    send_word(32'h01010101, edge_i == 15, edge_i % 2);
                wait_state(4'd4); // WEIGHT_COMMIT, final tap may commit here.
            end else begin
                load_model17(scenario_id, 32'h77);
                start_command(2, make_r1(1, 17, 1), scenario_id + 1, 32'h77);
                send_word(32'h00000007, 1, 0);
                if (stage == 4'd7) wait_state(4'd7); // activation feed
                else if (stage == 4'd8) wait_state(4'd8); // pipeline drain
                else if (stage == 4'd9) wait_state(4'd9); // result storage
                else if (stage == 4'd11) wait_state(4'd11); // backpressured response
                else fail("invalid stage in stress scenario");
            end

            // Exercise three assertion phases while preserving at least one
            // active clock edge under reset: after rising edge, at falling edge,
            // and two nanoseconds after falling edge.
            if (phase == 0) begin
                #1;
            end else if (phase == 1) begin
                // If we are already in the low half-cycle, do not wait for a
                // falling edge that would cross another active edge.
                if (clk) @(negedge clk);
                else #1;
            end else begin
                #2;
            end

            compare_enable = 0;
            if (use_reset) begin
                rst_n = 0;
                #1;
                if (candidate_dut.state !== stage)
                    fail("synchronous candidate reset changed state before active edge");
                if (legacy_dut.state !== 4'd0)
                    fail("legacy asynchronous reset did not clear immediately");
                repeat (2) begin @(posedge clk); #1; end
                if (candidate_dut.state !== 4'd0 || !new_cfg_ready)
                    fail("candidate synchronous reset did not clear on clock");
                @(negedge clk);
                reset_scenarios = reset_scenarios + 1;
                $display("PASS synchronous reset stage=%0d phase=%0d spans active edge",
                         stage, phase);
            end else begin
                cfg_abort = 1;
                #1;
                if (candidate_dut.state !== stage || legacy_dut.state !== stage)
                    fail("cfg_abort changed state away from active edge");
                @(posedge clk); #1;
                if (candidate_dut.state !== 4'd0 || !new_cfg_error)
                    fail("cfg_abort did not synchronously return candidate to idle");
                repeat (1) @(posedge clk);
                @(negedge clk);
                aborted_scenarios = aborted_scenarios + 1;
                $display("PASS cfg_abort stage=%0d phase=%0d invalidates transaction",
                         stage, phase);
            end
            recover_after_interruption(32'h00002000 + scenario_id * 16);
        end
    endtask

    initial begin
        // Hold reset through two rising edges, then compare normal traffic.
        repeat (2) @(posedge clk);
        @(negedge clk); rst_n = 1; compare_enable = 1;
        repeat (2) @(posedge clk);

        // Normal load/run: signed extreme activations, input bubbles, output
        // stalls, multiple sites and a non-aligned 17-lane tail.
        load_model17(100, 32'habc);
        run_model17(101, 32'habc, 2);
        $display("PASS differential normal transactions byte/cycle exact (%0d cycles)",
                 compared_cycles);

        interrupt_stage(4'd1, 0, 0, 1);
        interrupt_stage(4'd4, 0, 1, 2);
        interrupt_stage(4'd7, 0, 2, 3);
        interrupt_stage(4'd8, 0, 0, 4);
        interrupt_stage(4'd9, 0, 1, 5);
        interrupt_stage(4'd11, 0, 2, 6);

        interrupt_stage(4'd1, 1, 0, 11);
        interrupt_stage(4'd4, 1, 1, 12);
        interrupt_stage(4'd7, 1, 2, 13);
        interrupt_stage(4'd8, 1, 0, 14);
        interrupt_stage(4'd9, 1, 1, 15);
        interrupt_stage(4'd11, 1, 2, 16);

        if (compared_cycles < 1000 || successful_responses < 100 ||
            aborted_scenarios != 6 || reset_scenarios != 6)
            fail("stress coverage counters below required minimum");
        $display("PASS z100_sync_reset_stress compared_cycles=%0d responses=%0d aborts=%0d resets=%0d",
                 compared_cycles, successful_responses, aborted_scenarios,
                 reset_scenarios);
        $finish;
    end

    initial begin
        #20000000; $fatal(1, "sync reset stress test timeout");
    end
endmodule
