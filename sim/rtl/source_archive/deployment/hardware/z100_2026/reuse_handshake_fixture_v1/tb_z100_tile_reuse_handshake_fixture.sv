`timescale 1ns/1ps
module tb_z100_tile_reuse_handshake_fixture;
    reg clk = 1'b0;
    always #2.5 clk = ~clk;

    reg rst_n = 1'b0;
    reg [31:0] load_seed = 32'h7fff0000;
    reg request_valid = 1'b0;
    wire request_ready;
    reg [12:0] request_taps = 13'd0;
    reg [5:0] request_lanes = 6'd32;
    reg [2:0] request_sites = 3'd4;
    reg cancel = 1'b0;
    reg observe_ready = 1'b0;
    wire scan_valid;
    wire [31:0] scan_word;
    wire scan_overflow;
    wire [1:0] scan_site;
    wire [4:0] scan_lane;
    wire [5:0] scan_lane_count;
    wire scan_last;
    wire scan_job_done;
    wire protocol_error;

    integer accepted_jobs = 0;
    integer completed_jobs = 0;
    integer scanned_words = 0;
    integer blocked_request_cycles = 0;
    integer output_stall_cycles = 0;
    integer cycle_count = 0;

    reg [31:0] expected_value [0:3][0:31];
    reg expected_overflow [0:3][0:31];
    reg [31:0] model_weight_lfsr [0:31];
    reg [31:0] model_activation_lfsr [0:3];
    reg signed [63:0] model_total [0:3][0:31];
    reg request_stalled = 1'b0;
    reg [12:0] held_taps;
    reg [5:0] held_lanes;
    reg [2:0] held_sites;
    reg [31:0] held_word;
    reg held_overflow;
    reg [1:0] held_site;
    reg [4:0] held_lane;
    reg [5:0] held_lane_count;
    reg held_last;
    reg output_stalled = 1'b0;

    z100_tile_reuse_handshake_fixture_top dut (
        .clk(clk), .rst_n(rst_n), .load_seed(load_seed),
        .request_valid(request_valid), .request_ready(request_ready),
        .request_taps(request_taps), .request_lanes(request_lanes),
        .request_sites(request_sites), .cancel(cancel),
        .observe_ready(observe_ready), .scan_valid(scan_valid),
        .scan_word(scan_word), .scan_overflow(scan_overflow),
        .scan_site(scan_site), .scan_lane(scan_lane),
        .scan_lane_count(scan_lane_count), .scan_last(scan_last),
        .scan_job_done(scan_job_done), .protocol_error(protocol_error)
    );

    function automatic [31:0] advance_model_lfsr;
        input [31:0] value;
        begin
            advance_model_lfsr = {value[30:0], value[31] ^ value[21] ^ value[1] ^ value[0]};
        end
    endfunction

    function automatic [31:0] initial_weight_lfsr;
        input [31:0] seed;
        input integer lane;
        begin
            initial_weight_lfsr = (seed ^ (32'h9e3779b9 * (lane + 1))) | 32'd1;
        end
    endfunction

    function automatic [31:0] initial_activation_lfsr;
        input [31:0] seed;
        input integer site;
        begin
            initial_activation_lfsr = (seed ^ (32'h7f4a7c15 * (site + 1))) | 32'd1;
        end
    endfunction

    task fail;
        input [8*160-1:0] message;
        begin
            $display("FAIL: %0s", message);
            $fatal(1);
        end
    endtask

    task calculate_reference;
        input integer taps;
        input [31:0] seed;
        integer site;
        integer lane;
        integer tap;
        integer signed w;
        integer signed a;
        begin
            for (lane = 0; lane < 32; lane = lane + 1)
                model_weight_lfsr[lane] = initial_weight_lfsr(seed, lane);
            for (site = 0; site < 4; site = site + 1) begin
                model_activation_lfsr[site] = initial_activation_lfsr(seed, site);
                for (lane = 0; lane < 32; lane = lane + 1)
                    model_total[site][lane] = $signed(seed) + (lane * 256);
            end
            for (tap = 0; tap < taps; tap = tap + 1) begin
                for (lane = 0; lane < 32; lane = lane + 1) begin
                    w = $signed(model_weight_lfsr[lane][7:0]);
                    for (site = 0; site < 4; site = site + 1) begin
                        a = $signed(model_activation_lfsr[site][7:0]);
                        model_total[site][lane] = model_total[site][lane] + (w * a);
                    end
                    model_weight_lfsr[lane] = advance_model_lfsr(model_weight_lfsr[lane]);
                end
                for (site = 0; site < 4; site = site + 1)
                    model_activation_lfsr[site] = advance_model_lfsr(model_activation_lfsr[site]);
            end
            for (site = 0; site < 4; site = site + 1) begin
                for (lane = 0; lane < 32; lane = lane + 1) begin
                    if (model_total[site][lane] > 64'sd2147483647) begin
                        expected_value[site][lane] = 32'h7fffffff;
                        expected_overflow[site][lane] = 1'b1;
                    end else if (model_total[site][lane] < -64'sd2147483648) begin
                        expected_value[site][lane] = 32'h80000000;
                        expected_overflow[site][lane] = 1'b1;
                    end else begin
                        expected_value[site][lane] = model_total[site][lane][31:0];
                        expected_overflow[site][lane] = 1'b0;
                    end
                end
            end
        end
    endtask

    task wait_request_ready;
        integer watchdog;
        begin
            watchdog = 0;
            while (!request_ready && watchdog < 12000) begin
                @(negedge clk);
                watchdog = watchdog + 1;
            end
            if (!request_ready)
                fail("preload/reload did not reach request_ready");
        end
    endtask

    task send_request;
        input integer taps;
        integer watchdog;
        begin
            @(negedge clk);
            request_taps = taps;
            request_lanes = 32;
            request_sites = 4;
            request_valid = 1'b1;
            watchdog = 0;
            while (!request_ready && watchdog < 12000) begin
                @(negedge clk);
                watchdog = watchdog + 1;
            end
            if (!request_ready)
                fail("request did not become ready");
            @(posedge clk);
            if (!request_ready)
                fail("request_ready dropped before valid/ready handshake");
            accepted_jobs = accepted_jobs + 1;
            @(negedge clk);
            request_valid = 1'b0;
        end
    endtask

    task send_blocked_request;
        input integer taps;
        integer watchdog;
        begin
            @(negedge clk);
            request_taps = taps;
            request_lanes = 32;
            request_sites = 4;
            request_valid = 1'b1;
            watchdog = 0;
            while (1) begin
                @(posedge clk);
                if (request_ready) begin
                    accepted_jobs = accepted_jobs + 1;
                    @(negedge clk);
                    request_valid = 1'b0;
                    disable send_blocked_request;
                end
                watchdog = watchdog + 1;
                if (watchdog > 2000)
                    fail("blocked request timed out");
                @(negedge clk);
                if (!request_ready)
                    blocked_request_cycles = blocked_request_cycles + 1;
                if (!request_valid || request_taps !== taps || request_lanes !== 32 || request_sites !== 4)
                    fail("request payload changed while request_ready was low");
            end
        end
    endtask

    task collect_job;
        input integer taps;
        input [31:0] seed;
        integer lane_expected;
        integer site_expected;
        integer watchdog;
        integer ready_phase;
        integer job_stalls;
        begin
            calculate_reference(taps, seed);
            lane_expected = 0;
            site_expected = 0;
            watchdog = 0;
            ready_phase = 0;
            job_stalls = 0;
            while (site_expected < 4 && watchdog < 6000) begin
                @(negedge clk);
                // Deterministic irregular backpressure includes long stalls.
                observe_ready = ((ready_phase % 7) != 1) && ((ready_phase % 7) != 2);
                ready_phase = ready_phase + 1;
                if (scan_valid) begin
                    if (scan_site !== site_expected[1:0] || scan_lane !== lane_expected[4:0])
                        fail("scan site/lane order mismatch");
                    if (scan_word !== expected_value[site_expected][lane_expected])
                        fail("one of the 1024 output data bits did not match scalar reference");
                    if (scan_overflow !== expected_overflow[site_expected][lane_expected])
                        fail("one of the 32 overflow bits did not match scalar reference");
                    if (scan_lane_count !== 6'd32)
                        fail("scan lane_count metadata mismatch");
                    if (scan_last !== ((site_expected == 3) && (lane_expected == 31)))
                        fail("scan last metadata mismatch");
                    if (observe_ready) begin
                        @(posedge clk);
                        scanned_words = scanned_words + 1;
                        if (scan_job_done !== ((site_expected == 3) && (lane_expected == 31)))
                            fail("scan_job_done handshake mismatch");
                        if (lane_expected == 31) begin
                            lane_expected = 0;
                            site_expected = site_expected + 1;
                        end else begin
                            lane_expected = lane_expected + 1;
                        end
                    end else begin
                        output_stall_cycles = output_stall_cycles + 1;
                        job_stalls = job_stalls + 1;
                    end
                end
                watchdog = watchdog + 1;
            end
            observe_ready = 1'b1;
            if (site_expected != 4)
                fail("timed out scanning all four sites");
            if (protocol_error)
                fail("valid job raised core protocol_error");
            completed_jobs = completed_jobs + 1;
            $display("JOB_PASS taps=%0d sites=4 lanes=32 scanned_words=128 stalls=%0d scan_cycles=%0d",
                taps, job_stalls, ready_phase);
        end
    endtask

    task cancel_running_job;
        integer guard;
        begin
            send_request(4091);
            repeat (6) @(negedge clk);
            cancel = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cancel = 1'b0;
            guard = 0;
            while (!request_ready && guard < 12000) begin
                @(negedge clk);
                if (scan_valid)
                    fail("stale output escaped after cancel");
                guard = guard + 1;
            end
            if (!request_ready)
                fail("cancel did not reload to request_ready");
            repeat (8) begin
                @(posedge clk);
                if (scan_valid)
                    fail("stale result escaped after cancel reload");
            end
            $display("CANCEL_RELOAD_PASS cycles=%0d", guard);
        end
    endtask

    task reset_while_result_stalled;
        integer guard;
        begin
            send_request(129);
            observe_ready = 1'b0;
            guard = 0;
            while (!scan_valid && guard < 400) begin
                @(negedge clk);
                guard = guard + 1;
            end
            if (!scan_valid)
                fail("timed out waiting for backpressured result before reset");
            repeat (3) @(posedge clk);
            if (!scan_valid)
                fail("result valid disappeared during reset precondition stall");
            rst_n = 1'b0;
            load_seed = 32'h80001234;
            repeat (3) @(posedge clk);
            @(negedge clk);
            rst_n = 1'b1;
            observe_ready = 1'b1;
            wait_request_ready();
            repeat (8) begin
                @(posedge clk);
                if (scan_valid)
                    fail("stale result escaped after synchronous reset");
            end
            $display("RESET_STALLED_RESULT_PASS wait_cycles=%0d", guard);
        end
    endtask

    always @(posedge clk) begin
        cycle_count = cycle_count + 1;
        if (!rst_n || cancel) begin
            request_stalled <= 1'b0;
            output_stalled <= 1'b0;
        end else begin
            if (request_stalled &&
                (!request_valid || request_taps !== held_taps ||
                 request_lanes !== held_lanes || request_sites !== held_sites))
                fail("request valid/payload did not remain stable while blocked");
            request_stalled <= request_valid && !request_ready;
            if (request_valid && !request_ready) begin
                held_taps <= request_taps;
                held_lanes <= request_lanes;
                held_sites <= request_sites;
            end
            if (output_stalled &&
                (!scan_valid || scan_word !== held_word ||
                 scan_overflow !== held_overflow || scan_site !== held_site ||
                 scan_lane !== held_lane || scan_lane_count !== held_lane_count ||
                 scan_last !== held_last))
                fail("result valid/payload did not remain stable while blocked");
            output_stalled <= scan_valid && !observe_ready;
            if (scan_valid && !observe_ready) begin
                held_word <= scan_word;
                held_overflow <= scan_overflow;
                held_site <= scan_site;
                held_lane <= scan_lane;
                held_lane_count <= scan_lane_count;
                held_last <= scan_last;
            end
        end
    end

    initial begin : main
        integer guard;
        rst_n = 1'b0;
        repeat (4) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        wait_request_ready();

        // Full MAX_TAPS run covers every weight/activation address, all four
        // banks, all lanes/sites and the three-bank final group. Queue a second
        // request during the first run to verify request-side backpressure.
        send_request(4091);
        fork
            collect_job(4091, 32'h7fff0000);
            send_blocked_request(5);
        join
        collect_job(5, 32'h7fff0000);

        cancel_running_job();
        reset_while_result_stalled();
        send_request(129);
        collect_job(129, 32'h80001234);
        send_request(128);
        collect_job(128, 32'h80001234);

        if (accepted_jobs != 6 || completed_jobs != 4 || scanned_words != 512)
            fail("final job or scanned-word count mismatch");
        if (blocked_request_cycles < 10 || output_stall_cycles < 20)
            fail("insufficient observed request/result backpressure");
        if (protocol_error)
            fail("core protocol_error asserted at test completion");
        $display("HANDSHAKE_SIM_PASS accepted_jobs=%0d completed_jobs=%0d scanned_words=%0d blocked_request_cycles=%0d output_stall_cycles=%0d total_cycles=%0d",
            accepted_jobs, completed_jobs, scanned_words, blocked_request_cycles,
            output_stall_cycles, cycle_count);
        $finish;
    end

    initial begin
        #1000000;
        $display("FAIL: global simulation timeout");
        $fatal(1);
    end
endmodule
