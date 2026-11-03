`timescale 1ns/1ps
`default_nettype none
module tb_z100_window_mac_accum_v3;
    localparam integer TOTAL_GROUPS = 1657;
    localparam integer CASE_COUNT = 8;
    localparam integer EXPECTED_OUTPUTS = 16;
    localparam integer BUNDLE_WIDTH = 1099;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg cancel = 1'b0;
    reg cfg_begin = 1'b0;
    reg [31:0] cfg_epoch = 32'd0;
    reg [10:0] cfg_groups = 11'd0;
    reg cfg_weight_valid = 1'b0;
    reg [1023:0] cfg_weights = 1024'd0;
    reg cfg_bias_valid = 1'b0;
    reg [1023:0] cfg_bias = 1024'd0;
    reg cfg_commit = 1'b0;
    wire cfg_begin_ready;
    wire cfg_weight_ready;
    wire cfg_bias_ready;
    wire cfg_commit_ready;
    wire weights_valid;
    wire [31:0] weights_epoch;
    wire error_valid;
    wire [2:0] error_code;
    reg run_valid = 1'b0;
    reg [31:0] run_epoch = 32'd0;
    reg [31:0] run_token = 32'd0;
    reg [5:0] run_lanes = 6'd0;
    reg [3:0] run_sites = 4'd0;
    wire run_ready;
    reg act_valid = 1'b0;
    reg [31:0] act_token = 32'd0;
    reg act_last = 1'b0;
    reg [127:0] act_data = 128'd0;
    wire act_ready;
    wire out_valid;
    reg out_ready = 1'b0;
    wire [31:0] out_token;
    wire [3:0] out_site;
    wire out_last;
    wire [5:0] out_lanes;
    wire [1023:0] out_data;
    wire [31:0] out_overflow;

    reg [1023:0] weight_words [0:TOTAL_GROUPS-1];
    reg [127:0] activation_words [0:TOTAL_GROUPS-1];
    reg [1023:0] bias_words [0:CASE_COUNT-1];
    reg [95:0] case_words [0:CASE_COUNT-1];
    // One padding zero makes the 275-digit hex memory words exactly 1100 bits.
    reg [BUNDLE_WIDTH:0] expected_words [0:EXPECTED_OUTPUTS-1];

    integer expected_index = 0;
    integer output_count = 0;
    integer stall_count = 0;
    integer bubble_count = 0;
    integer weight_handshakes = 0;
    integer bias_handshakes = 0;
    integer act_handshakes = 0;
    integer run_handshakes = 0;
    integer error1_count = 0;
    integer error2_count = 0;
    integer error4_count = 0;
    integer error5_count = 0;
    integer cycles = 0;
    reg was_stalled = 1'b0;
    reg stall_enable = 1'b0;
    reg [15:0] ready_lfsr = 16'hace1;
    reg [BUNDLE_WIDTH-1:0] stalled_bundle;
    wire [BUNDLE_WIDTH-1:0] actual_bundle = {
        out_token, out_site, out_last, out_lanes, out_overflow, out_data
    };

    always #5 clk = ~clk;

    z100_window_mac_accum_v3 #(.SITES(4)) dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(cfg_begin_ready),
        .cfg_epoch(cfg_epoch), .cfg_groups(cfg_groups),
        .cfg_weight_valid(cfg_weight_valid), .cfg_weight_ready(cfg_weight_ready),
        .cfg_weights(cfg_weights), .cfg_bias_valid(cfg_bias_valid),
        .cfg_bias_ready(cfg_bias_ready), .cfg_bias(cfg_bias),
        .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .weights_valid(weights_valid), .weights_epoch(weights_epoch),
        .error_valid(error_valid), .error_code(error_code),
        .run_valid(run_valid), .run_ready(run_ready), .run_epoch(run_epoch),
        .run_token(run_token), .run_lanes(run_lanes), .run_sites(run_sites),
        .act_valid(act_valid), .act_ready(act_ready), .act_token(act_token),
        .act_last(act_last), .act_data(act_data),
        .out_valid(out_valid), .out_ready(out_ready), .out_token(out_token),
        .out_site(out_site), .out_last(out_last), .out_lanes(out_lanes),
        .out_data(out_data), .out_overflow(out_overflow)
    );

    always @(negedge clk) begin
        if (!rst_n || cancel) begin
            out_ready <= 1'b0;
        end else if (stall_enable) begin
            out_ready <= 1'b0;
        end else begin
            ready_lfsr <= {ready_lfsr[14:0], ready_lfsr[15] ^ ready_lfsr[13] ^ ready_lfsr[12] ^ ready_lfsr[10]};
            out_ready <= ready_lfsr[0] | ready_lfsr[3];
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            was_stalled = 1'b0;
        end else begin
            cycles = cycles + 1;
            if (cycles > 100000)
                $fatal(1, "FAIL: accumulator v2 watchdog expired");

            if (cfg_weight_valid && cfg_weight_ready)
                weight_handshakes = weight_handshakes + 1;
            if (cfg_bias_valid && cfg_bias_ready)
                bias_handshakes = bias_handshakes + 1;
            if (act_valid && act_ready)
                act_handshakes = act_handshakes + 1;
            if (run_valid && run_ready)
                run_handshakes = run_handshakes + 1;

            if (was_stalled && (!out_valid || actual_bundle !== stalled_bundle))
                $fatal(1, "FAIL: output bundle changed during backpressure expected=%0275x got=%0275x",
                       stalled_bundle, actual_bundle);
            if (out_valid && !out_ready) begin
                stall_count = stall_count + 1;
                was_stalled = 1'b1;
                stalled_bundle = actual_bundle;
            end else begin
                was_stalled = 1'b0;
            end

            if (out_valid && out_ready) begin
                if (expected_index >= EXPECTED_OUTPUTS)
                    $fatal(1, "FAIL: unexpected output index=%0d", expected_index);
                if (actual_bundle !== expected_words[expected_index][BUNDLE_WIDTH-1:0])
                    $fatal(1, "FAIL: output mismatch index=%0d got=%0275x expected=%0275x",
                           expected_index, actual_bundle, expected_words[expected_index][BUNDLE_WIDTH-1:0]);
                expected_index = expected_index + 1;
                output_count = output_count + 1;
            end

            if (error_valid) begin
                case (error_code)
                    3'd1: error1_count = error1_count + 1;
                    3'd2: error2_count = error2_count + 1;
                    3'd4: error4_count = error4_count + 1;
                    3'd5: error5_count = error5_count + 1;
                    default: $fatal(1, "FAIL: unexpected core error code=%0d", error_code);
                endcase
            end
        end
    end

    task automatic wait_error(input [2:0] wanted);
        integer timeout;
        begin
            // Catch a new one-cycle error that asserted on the just-accepted
            // transaction; only wait for a later pulse when the wanted code
            // is not already visible.
            if (!(error_valid && error_code === wanted)) begin
                timeout = 0;
                while (error_valid && timeout < 16) begin
                    @(negedge clk);
                    timeout = timeout + 1;
                end
                timeout = 0;
                while (!error_valid && timeout < 64) begin
                    @(negedge clk);
                    timeout = timeout + 1;
                end
            end
            if (!error_valid || error_code !== wanted)
                $fatal(1, "FAIL: expected error code=%0d got valid=%b code=%0d", wanted, error_valid, error_code);
            @(negedge clk);
        end
    endtask

    task automatic send_bad_begin;
        integer accepted;
        begin
            @(negedge clk);
            cfg_epoch = 32'd0;
            cfg_groups = 11'd1;
            cfg_begin = 1'b1;
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (cfg_begin_ready)
                    accepted = 1;
            end
            @(negedge clk);
            cfg_begin = 1'b0;
            wait_error(3'd1);
        end
    endtask

    task automatic send_incomplete_commit;
        integer accepted;
        begin
            @(negedge clk);
            cfg_epoch = 32'd99;
            cfg_groups = 11'd1;
            cfg_begin = 1'b1;
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (cfg_begin_ready)
                    accepted = 1;
            end
            @(negedge clk);
            cfg_begin = 1'b0;
            cfg_commit = 1'b1;
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (cfg_commit_ready)
                    accepted = 1;
            end
            @(negedge clk);
            cfg_commit = 1'b0;
            wait_error(3'd2);
        end
    endtask

    task automatic send_weight(input integer index);
        integer accepted;
        begin
            @(negedge clk);
            cfg_weights = weight_words[index];
            cfg_weight_valid = 1'b1;
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (cfg_weight_ready)
                    accepted = 1;
            end
            @(negedge clk);
            cfg_weight_valid = 1'b0;
        end
    endtask

    task automatic send_bias(input integer index);
        integer accepted;
        begin
            @(negedge clk);
            cfg_bias = bias_words[index];
            cfg_bias_valid = 1'b1;
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (cfg_bias_ready)
                    accepted = 1;
            end
            @(negedge clk);
            cfg_bias_valid = 1'b0;
        end
    endtask

    task automatic send_commit(input [31:0] wanted_epoch);
        integer accepted;
        integer timeout;
        begin
            @(negedge clk);
            cfg_commit = 1'b1;
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (cfg_commit_ready)
                    accepted = 1;
            end
            @(negedge clk);
            cfg_commit = 1'b0;
            timeout = 0;
            while ((!weights_valid || weights_epoch !== wanted_epoch) && timeout < 64) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!weights_valid || weights_epoch !== wanted_epoch)
                $fatal(1, "FAIL: configuration did not commit epoch=%08x", wanted_epoch);
        end
    endtask

    task automatic configure_case(input integer case_index);
        reg [95:0] desc;
        integer count;
        integer first_word;
        integer group_index;
        reg [31:0] epoch_value;
        begin
            desc = case_words[case_index];
            count = desc[95:85];
            epoch_value = desc[74:43];
            first_word = desc[10:0];
            @(negedge clk);
            cfg_epoch = epoch_value;
            cfg_groups = count;
            cfg_begin = 1'b1;
            group_index = 0;
            while (group_index == 0) begin
                @(posedge clk);
                if (cfg_begin_ready)
                    group_index = 1;
            end
            @(negedge clk);
            cfg_begin = 1'b0;
            for (group_index = 0; group_index < count; group_index = group_index + 1)
                send_weight(first_word + group_index);
            send_bias(case_index);
            send_commit(epoch_value);
        end
    endtask

    task automatic send_run(input integer case_index, input [31:0] override_epoch);
        reg [95:0] desc;
        integer accepted;
        begin
            desc = case_words[case_index];
            @(negedge clk);
            run_epoch = override_epoch;
            run_token = desc[42:11];
            run_lanes = desc[84:79];
            run_sites = desc[78:75];
            run_valid = 1'b1;
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (run_ready)
                    accepted = 1;
            end
            @(negedge clk);
            run_valid = 1'b0;
        end
    endtask

    task automatic send_case_acts(input integer case_index, input integer limit_groups,
                                  input reg use_bad_token, input reg insert_bubbles);
        reg [95:0] desc;
        integer count;
        integer configured_groups;
        integer first_word;
        integer group_index;
        integer accepted;
        integer gap;
        reg [31:0] token_value;
        begin
            desc = case_words[case_index];
            configured_groups = desc[95:85];
            count = configured_groups;
            first_word = desc[10:0];
            token_value = desc[42:11];
            if (limit_groups < count)
                count = limit_groups;
            for (group_index = 0; group_index < count; group_index = group_index + 1) begin
                gap = insert_bubbles && group_index != 0 && ((group_index % 127) == 63);
                if (group_index == 0 || gap) begin
                    @(negedge clk);
                    act_valid = 1'b0;
                    if (gap) begin
                        bubble_count = bubble_count + 1;
                        @(posedge clk);
                        @(negedge clk);
                    end
                    act_valid = 1'b1;
                end else begin
                    @(negedge clk);
                end
                act_data = activation_words[first_word + group_index];
                act_token = use_bad_token ? (token_value ^ 32'h1) : token_value;
                act_last = (group_index + 1 == configured_groups);
                accepted = 0;
                while (!accepted) begin
                    @(posedge clk);
                    if (act_ready)
                        accepted = 1;
                end
            end
            @(negedge clk);
            act_valid = 1'b0;
        end
    endtask

    task automatic wait_outputs(input integer wanted);
        integer timeout;
        begin
            timeout = 0;
            while (output_count < wanted && timeout < 100000) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (output_count < wanted)
                $fatal(1, "FAIL: output timeout wanted=%0d observed=%0d", wanted, output_count);
        end
    endtask

    task automatic check_first_four_valid_stages;
        begin
            if ({dut.p3_valid, dut.p2_valid, dut.p1_valid, dut.p0_valid} !== 4'b0001)
                $fatal(1, "FAIL: accepted activation did not start at p0: %b%b%b%b",
                       dut.p3_valid, dut.p2_valid, dut.p1_valid, dut.p0_valid);
            @(negedge clk);
            if ({dut.p3_valid, dut.p2_valid, dut.p1_valid, dut.p0_valid} !== 4'b0010)
                $fatal(1, "FAIL: valid stage p1 misaligned: %b%b%b%b",
                       dut.p3_valid, dut.p2_valid, dut.p1_valid, dut.p0_valid);
            @(negedge clk);
            if ({dut.p3_valid, dut.p2_valid, dut.p1_valid, dut.p0_valid} !== 4'b0100)
                $fatal(1, "FAIL: valid stage p2 misaligned: %b%b%b%b",
                       dut.p3_valid, dut.p2_valid, dut.p1_valid, dut.p0_valid);
            @(negedge clk);
            if ({dut.p3_valid, dut.p2_valid, dut.p1_valid, dut.p0_valid} !== 4'b1000)
                $fatal(1, "FAIL: valid stage p3 misaligned: %b%b%b%b",
                       dut.p3_valid, dut.p2_valid, dut.p1_valid, dut.p0_valid);
        end
    endtask

    task automatic expect_no_output_after_cancel;
        integer i;
        begin
            @(negedge clk);
            cancel = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cancel = 1'b0;
            for (i = 0; i < 6; i = i + 1)
                @(posedge clk);
            if (out_valid || weights_valid || dut.p0_valid || dut.p1_valid || dut.p2_valid || dut.p3_valid)
                $fatal(1, "FAIL: cancel left valid state or loaded weights active");
        end
    endtask

    integer c;
    integer g;
    integer base;
    reg [95:0] desc;
    reg [31:0] epoch_value;
    integer count;
    integer wanted_outputs;
    initial begin
        $readmemh("weights.hex", weight_words);
        $readmemh("activations.hex", activation_words);
        $readmemh("biases.hex", bias_words);
        $readmemh("cases.hex", case_words);
        $readmemh("expected_outputs.hex", expected_words);

        repeat (5) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        send_bad_begin();
        send_incomplete_commit();

        for (c = 0; c < 5; c = c + 1) begin
            desc = case_words[c];
            count = desc[95:85];
            epoch_value = desc[74:43];
            base = desc[10:0];
            configure_case(c);
            if (c == 0) begin
                @(posedge clk);
                stall_enable = 1'b1;
            end
            send_run(c, epoch_value);
            send_case_acts(c, count, 1'b0, 1'b1);
            if (c == 0) begin
                check_first_four_valid_stages();
                wait (out_valid === 1'b1);
                repeat (4) @(posedge clk);
                if (out_ready !== 1'b0)
                    $fatal(1, "FAIL: directed first-output pause was not held");
                @(posedge clk);
                stall_enable = 1'b0;
            end
            wanted_outputs = expected_index + desc[78:75];
            wait_outputs(wanted_outputs);
        end

        // Invalid run geometry/epoch must raise code 4 without mutating the
        // committed weights. A bad activation token must raise code 5 and
        // invalidate the weights exactly as in the frozen controller.
        desc = case_words[4];
        epoch_value = desc[74:43];
        send_run(4, epoch_value ^ 32'h1);
        wait_error(3'd4);
        if (!weights_valid)
            $fatal(1, "FAIL: invalid run changed committed weights");
        send_run(4, epoch_value);
        send_case_acts(4, 1, 1'b1, 1'b0);
        wait_error(3'd5);
        if (weights_valid || out_valid)
            $fatal(1, "FAIL: bad activation did not fail closed");

        // Cancel with work in p0..p2, before the final input group. Then prove
        // a fresh configuration overwrites the DSP accumulator from bias.
        configure_case(5);
        desc = case_words[5];
        epoch_value = desc[74:43];
        send_run(5, epoch_value);
        send_case_acts(5, 2, 1'b0, 1'b0);
        expect_no_output_after_cancel();

        // Reset a held output, prove it is discarded, and recover with a new
        // configuration/run. The held reset-run outputs are intentionally not
        // part of the expected stream.
        configure_case(6);
        desc = case_words[6];
        epoch_value = desc[74:43];
        @(posedge clk);
        stall_enable = 1'b1;
        send_run(6, epoch_value);
        send_case_acts(6, 1, 1'b0, 1'b0);
        wait (out_valid === 1'b1);
        repeat (2) @(posedge clk);
        if (!out_valid || out_ready)
            $fatal(1, "FAIL: reset case was not holding an output");
        @(negedge clk);
        rst_n = 1'b0;
        repeat (3) @(posedge clk);
        if (out_valid || weights_valid)
            $fatal(1, "FAIL: reset did not flush active output and weights");
        @(negedge clk);
        rst_n = 1'b1;
        stall_enable = 1'b0;
        repeat (2) @(negedge clk);

        configure_case(7);
        desc = case_words[7];
        epoch_value = desc[74:43];
        send_run(7, epoch_value);
        send_case_acts(7, 1, 1'b0, 1'b0);
        wait_outputs(EXPECTED_OUTPUTS);

        if (expected_index != EXPECTED_OUTPUTS || output_count != EXPECTED_OUTPUTS)
            $fatal(1, "FAIL: output totals index=%0d count=%0d", expected_index, output_count);
        if (weight_handshakes != TOTAL_GROUPS || bias_handshakes != CASE_COUNT ||
            act_handshakes != 1651 || run_handshakes != 10)
            $fatal(1, "FAIL: traffic counts weight=%0d bias=%0d act=%0d run=%0d",
                   weight_handshakes, bias_handshakes, act_handshakes, run_handshakes);
        if (error1_count != 1 || error2_count != 1 || error4_count != 1 || error5_count != 1)
            $fatal(1, "FAIL: error coverage c1=%0d c2=%0d c4=%0d c5=%0d",
                   error1_count, error2_count, error4_count, error5_count);
        if (stall_count == 0 || bubble_count == 0)
            $fatal(1, "FAIL: missing input-bubble/output-stall coverage bubbles=%0d stalls=%0d",
                   bubble_count, stall_count);

        $display("WINDOW_MAC_ACCUM_V3_PASS outputs=%0d numeric_cases=5 groups=1,9,36,576,1024 weight_words=%0d bias_words=%0d activation_handshakes=%0d run_handshakes=%0d input_bubbles=%0d output_stalls=%0d error1=%0d error2=%0d error4=%0d error5=%0d valid_stages=4 cancel_recovery=1 reset_recovery=1",
                 output_count, weight_handshakes, bias_handshakes, act_handshakes,
                 run_handshakes, bubble_count, stall_count, error1_count,
                 error2_count, error4_count, error5_count);
        $finish;
    end
endmodule
`default_nettype wire
