`timescale 1ns/1ps

module tb_z100_tile_reuse_resident_v3_timing_top;
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    wire monitor_valid;
    wire [31:0] monitor_data;
    wire monitor_overflow;
    wire [1:0] monitor_site;
    wire [4:0] monitor_lane;
    wire monitor_last;
    wire monitor_ready;
    wire [31:0] monitor_status;

    reg [40:0] expected_serial [0:511];
    integer expected_write = 0;
    integer expected_read = 0;
    integer run_index = 0;
    integer words_in_run = 0;
    integer output_words = 0;
    integer nonzero_words = 0;
    integer stalls = 0;
    integer command_counts [1:8];
    integer cycle_count = 0;
    integer i;
    integer expected_lanes;
    integer expected_sites;
    integer expected_lane;
    integer expected_site;
    integer expected_last;
    reg was_stalled = 1'b0;
    reg [31:0] stalled_data;
    reg stalled_overflow;
    reg [1:0] stalled_site;
    reg [4:0] stalled_lane;
    reg stalled_last;

    always #5 clk = ~clk;

    z100_tile_reuse_resident_v3_timing_top #(.FAST_SMOKE(1)) dut (
        .clk(clk), .rst_n(rst_n),
        .monitor_valid(monitor_valid), .monitor_data(monitor_data),
        .monitor_overflow(monitor_overflow), .monitor_site(monitor_site),
        .monitor_lane(monitor_lane), .monitor_last(monitor_last),
        .monitor_ready(monitor_ready), .monitor_status(monitor_status)
    );

    function integer lanes_for_run(input integer run_number);
        begin
            case (run_number)
                0: lanes_for_run = 9;
                1: lanes_for_run = 17;
                default: lanes_for_run = 32;
            endcase
        end
    endfunction

    function integer sites_for_run(input integer run_number);
        begin
            case (run_number)
                0: sites_for_run = 1;
                1: sites_for_run = 3;
                2: sites_for_run = 2;
                default: sites_for_run = 4;
            endcase
        end
    endfunction

    always @(posedge clk) begin
        if (!dut.reset_local) begin
            expected_write = 0;
            expected_read = 0;
            cycle_count = 0;
            run_index = 0;
            words_in_run = 0;
            output_words = 0;
            nonzero_words = 0;
            stalls = 0;
            was_stalled = 1'b0;
            for (i = 1; i <= 8; i = i + 1)
                command_counts[i] = 0;
        end else begin
            cycle_count = cycle_count + 1;
            if (cycle_count > 1000000)
                $fatal(1, "FAIL: timing fixture smoke watchdog expired");

            if (monitor_status[30])
                $fatal(1, "FAIL: timing fixture asserted protocol fault, status=%08x", monitor_status);

            if (dut.cmd_valid && dut.cmd_ready) begin
                if ((dut.cmd_opcode < 1) || (dut.cmd_opcode > 8))
                    $fatal(1, "FAIL: unexpected accepted opcode %0d", dut.cmd_opcode);
                command_counts[dut.cmd_opcode] = command_counts[dut.cmd_opcode] + 1;
            end

            if (was_stalled) begin
                if (!monitor_valid || (monitor_data !== stalled_data) ||
                    (monitor_overflow !== stalled_overflow) ||
                    (monitor_site !== stalled_site) || (monitor_lane !== stalled_lane) ||
                    (monitor_last !== stalled_last))
                    $fatal(1, "FAIL: output changed or valid dropped during backpressure");
            end

            if (monitor_valid && !monitor_ready) begin
                stalls = stalls + 1;
                was_stalled = 1'b1;
                stalled_data = monitor_data;
                stalled_overflow = monitor_overflow;
                stalled_site = monitor_site;
                stalled_lane = monitor_lane;
                stalled_last = monitor_last;
            end else begin
                was_stalled = 1'b0;
            end

            // Independent elastic-boundary scoreboard. Record every word
            // accepted from the frozen arithmetic core before its output
            // changes, then compare all bits when the registered word drains.
            if (dut.raw_fire) begin
                if (expected_write >= 512)
                    $fatal(1, "FAIL: serial scoreboard overflow");
                expected_serial[expected_write] = {
                    (dut.core_out_last && dut.final_output_lane), dut.scan_lane,
                    dut.core_out_site, dut.core_out_overflow[dut.scan_lane],
                    dut.core_out_data[(dut.scan_lane * 32) +: 32]
                };
                expected_write = expected_write + 1;
            end
            if (monitor_valid && monitor_ready) begin
                if (expected_read >= expected_write ||
                    {monitor_last, monitor_lane, monitor_site, monitor_overflow, monitor_data}
                    !== expected_serial[expected_read])
                    $fatal(1, "FAIL: registered output differs from accepted arithmetic word index=%0d", expected_read);
                expected_read = expected_read + 1;
                if (run_index >= 5)
                    $fatal(1, "FAIL: unexpected output after the fifth run");
                expected_lanes = lanes_for_run(run_index);
                expected_sites = sites_for_run(run_index);
                expected_lane = words_in_run % expected_lanes;
                expected_site = words_in_run / expected_lanes;
                expected_last = (words_in_run == (expected_lanes * expected_sites - 1));
                if ((monitor_lane !== expected_lane[4:0]) ||
                    (monitor_site !== expected_site[1:0]) ||
                    (monitor_last !== expected_last[0]))
                    $fatal(1, "FAIL: output sequence run=%0d word=%0d got site=%0d lane=%0d last=%0b expected site=%0d lane=%0d last=%0b",
                           run_index, words_in_run, monitor_site, monitor_lane, monitor_last,
                           expected_site, expected_lane, expected_last);
                output_words = output_words + 1;
                if (monitor_data !== 32'd0)
                    nonzero_words = nonzero_words + 1;
                words_in_run = words_in_run + 1;
                if (words_in_run == expected_lanes * expected_sites) begin
                    words_in_run = 0;
                    run_index = run_index + 1;
                end
            end
        end
    end

    initial begin
        for (i = 1; i <= 8; i = i + 1)
            command_counts[i] = 0;
        repeat (6) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;

        wait (monitor_status[31] === 1'b1);
        #1;
        if (monitor_status[30] !== 1'b0 || monitor_status[29] !== 1'b1 ||
            monitor_status[28] !== 1'b1 || monitor_status[27] !== 1'b0)
            $fatal(1, "FAIL: final status flags invalid: %08x", monitor_status);
        if (run_index != 5 || words_in_run != 0 || output_words != 380)
            $fatal(1, "FAIL: output totals runs=%0d words_in_run=%0d outputs=%0d", run_index, words_in_run, output_words);
        if (expected_read != 380 || expected_write != 380)
            $fatal(1, "FAIL: serial scoreboard did not compare all380 words");
        if (monitor_status[23:16] != 5 || monitor_status[15:0] != 184)
            $fatal(1, "FAIL: status counters completed=%0d accepted=%0d", monitor_status[23:16], monitor_status[15:0]);
        if (command_counts[1] != 4 || command_counts[2] != 65 ||
            command_counts[3] != 4 || command_counts[4] != 4 ||
            command_counts[5] != 5 || command_counts[6] != 92 ||
            command_counts[7] != 5 || command_counts[8] != 5)
            $fatal(1, "FAIL: command census %0d %0d %0d %0d %0d %0d %0d %0d",
                   command_counts[1], command_counts[2], command_counts[3], command_counts[4],
                   command_counts[5], command_counts[6], command_counts[7], command_counts[8]);
        if (stalls == 0 || nonzero_words == 0)
            $fatal(1, "FAIL: fixture did not exercise backpressure/arithmetic outputs stalls=%0d nonzero=%0d", stalls, nonzero_words);

        $display("TIMING_FIXTURE_SMOKE_PASS outputs=%0d runs=%0d accepted=%0d w_begin=%0d w_data=%0d bias=%0d w_commit=%0d act_begin=%0d act_data=%0d act_commit=%0d run=%0d stalls=%0d nonzero_words=%0d protocol_fault=%0d done=%0d",
                 output_words, run_index, monitor_status[15:0], command_counts[1], command_counts[2],
                 command_counts[3], command_counts[4], command_counts[5], command_counts[6],
                 command_counts[7], command_counts[8], stalls, nonzero_words,
                 monitor_status[30], monitor_status[31]);
        $finish;
    end
endmodule
