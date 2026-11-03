`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_mac_timing_v2;
    localparam integer EXPECTED_WORDS = 960;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    wire monitor_valid;
    wire monitor_ready;
    wire [31:0] monitor_token;
    wire [31:0] monitor_data;
    wire monitor_overflow;
    wire [1:0] monitor_site;
    wire [4:0] monitor_lane;
    wire [5:0] monitor_lanes;
    wire monitor_last;
    wire [31:0] monitor_status;

    reg [78:0] expected_serial [0:EXPECTED_WORDS-1];
    integer expected_read = 0;
    integer output_words = 0;
    integer overflow_words = 0;
    integer nonzero_words = 0;
    integer completed_runs = 0;
    integer stalls = 0;
    integer cycle_count = 0;
    integer first_phase_words = 0;
    integer midrun_flush_passed = 0;
    integer reset_zero_cycles = 0;
    integer i;
    reg was_stalled = 1'b0;
    reg [78:0] stalled_word;

    always #5 clk = ~clk;

    z100_native_mac_timing_top_v2 #(.FAST_SMOKE(1)) dut (
        .clk(clk), .rst_n(rst_n),
        .monitor_valid(monitor_valid), .monitor_ready(monitor_ready),
        .monitor_token(monitor_token), .monitor_data(monitor_data),
        .monitor_overflow(monitor_overflow), .monitor_site(monitor_site),
        .monitor_lane(monitor_lane), .monitor_lanes(monitor_lanes),
        .monitor_last(monitor_last), .monitor_status(monitor_status)
    );

    always @(posedge clk) begin
        if (!dut.reset_local) begin
            #1;
            if ({monitor_valid, monitor_ready, monitor_token, monitor_data,
                 monitor_overflow, monitor_site, monitor_lane, monitor_lanes,
                 monitor_last, monitor_status} !== 113'd0)
                $fatal(1, "FAIL: registered monitor outputs were not flushed by reset");
            reset_zero_cycles = reset_zero_cycles + 1;
            expected_read = 0;
            output_words = 0;
            overflow_words = 0;
            nonzero_words = 0;
            completed_runs = 0;
            stalls = 0;
            cycle_count = 0;
            was_stalled = 1'b0;
        end else begin
            cycle_count = cycle_count + 1;
            if (cycle_count > 1000000)
                $fatal(1, "FAIL: native-MAC timing fixture watchdog expired");
            if (monitor_status[30])
                $fatal(1, "FAIL: fixture protocol fault status=%08x", monitor_status);

            if (was_stalled) begin
                if (!monitor_valid ||
                    {monitor_token, monitor_data, monitor_overflow, monitor_site,
                     monitor_lane, monitor_lanes, monitor_last} !== stalled_word)
                    $fatal(1, "FAIL: serialized MAC output changed during backpressure");
            end

            if (monitor_valid && !monitor_ready) begin
                stalls = stalls + 1;
                was_stalled = 1'b1;
                stalled_word = {monitor_token, monitor_data, monitor_overflow,
                                monitor_site, monitor_lane, monitor_lanes, monitor_last};
            end else begin
                was_stalled = 1'b0;
            end

            if (monitor_valid && monitor_ready) begin
                if (expected_read >= EXPECTED_WORDS)
                    $fatal(1, "FAIL: extra serialized output index=%0d", expected_read);
                if ({monitor_token, monitor_data, monitor_overflow, monitor_site,
                     monitor_lane, monitor_lanes, monitor_last} !== expected_serial[expected_read])
                    $fatal(1, "FAIL: output differs from signed-64 host reference index=%0d got=%020x expected=%020x",
                           expected_read,
                           {monitor_token, monitor_data, monitor_overflow, monitor_site,
                            monitor_lane, monitor_lanes, monitor_last},
                           expected_serial[expected_read]);
                expected_read = expected_read + 1;
                output_words = output_words + 1;
                if (monitor_overflow)
                    overflow_words = overflow_words + 1;
                if (monitor_data != 32'd0)
                    nonzero_words = nonzero_words + 1;
                if (monitor_last)
                    completed_runs = completed_runs + 1;
            end
        end
    end

    initial begin
        $readmemh("expected_serial.hex", expected_serial);
        repeat (6) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;

        // Interrupt the first run after valid traffic, then require the
        // complete observation bundle to flush before the fixture restarts.
        wait (output_words >= 64);
        first_phase_words = output_words;
        @(negedge clk);
        rst_n = 1'b0;
        wait (dut.reset_local === 1'b0);
        repeat (2) @(posedge clk);
        #2;
        if ({monitor_valid, monitor_ready, monitor_token, monitor_data,
             monitor_overflow, monitor_site, monitor_lane, monitor_lanes,
             monitor_last, monitor_status} !== 113'd0)
            $fatal(1, "FAIL: monitor observation stage retained stale outputs across reset");
        midrun_flush_passed = 1;
        repeat (4) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;

        wait (monitor_status[31] === 1'b1);
        #1;
        if (monitor_status[30] !== 1'b0 || monitor_status[29] !== 1'b1 ||
            monitor_status[28] !== 1'b0 || monitor_status[27] !== 1'b0 ||
            monitor_status[26] !== 1'b0 || monitor_status[25] !== 1'b0)
            $fatal(1, "FAIL: final status invalid: %08x", monitor_status);
        if (expected_read != EXPECTED_WORDS || output_words != EXPECTED_WORDS ||
            completed_runs != 8)
            $fatal(1, "FAIL: observed words=%0d read=%0d runs=%0d",
                   output_words, expected_read, completed_runs);
        if (dut.weight_load_count != 22 || dut.bias_load_count != 4 ||
            dut.activation_accept_count != 44 || dut.completed_runs != 8)
            $fatal(1, "FAIL: traffic counts weight=%0d bias=%0d activations=%0d runs=%0d",
                   dut.weight_load_count, dut.bias_load_count,
                   dut.activation_accept_count, dut.completed_runs);
        if (first_phase_words < 64 || midrun_flush_passed != 1 || reset_zero_cycles < 4 ||
            dut.input_bubble_count == 0 || stalls == 0 ||
            overflow_words == 0 || nonzero_words == 0)
            $fatal(1, "FAIL: fixture lacks reset/bubble/stall/arithmetic coverage first_phase=%0d reset_zero_cycles=%0d bubbles=%0d stalls=%0d overflow=%0d nonzero=%0d",
                   first_phase_words, reset_zero_cycles, dut.input_bubble_count,
                   stalls, overflow_words, nonzero_words);

        $display("NATIVE_MAC_TIMING_V2_RESET_FLUSH_PASS partial_words=%0d reset_zero_cycles=%0d",
                 first_phase_words, reset_zero_cycles);
        $display("NATIVE_MAC_TIMING_V2_SMOKE_PASS words=%0d runs=%0d weight_groups=%0d bias_words=%0d activation_groups=%0d input_bubbles=%0d output_stalls=%0d overflow_words=%0d nonzero_words=%0d",
                 output_words, completed_runs, dut.weight_load_count,
                 dut.bias_load_count, dut.activation_accept_count,
                 dut.input_bubble_count, stalls, overflow_words, nonzero_words);
        $finish;
    end
endmodule
`default_nettype wire
