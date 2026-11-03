`timescale 1ns/1ps
`default_nettype none
module tb_z100_accum33_fabric32_miter;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n = 1'b0;
    reg cancel = 1'b0;
    reg load_bias = 1'b0;
    reg enable = 1'b0;
    reg signed [31:0] bias = 32'sd0;
    reg signed [18:0] delta = 19'sd0;

    wire valid_dsp, overflow_dsp;
    wire signed [32:0] value_dsp;
    wire signed [31:0] clamp_dsp;
    wire valid_fabric, overflow_fabric;
    wire signed [32:0] value_fabric;
    wire signed [31:0] clamp_fabric;

    z100_accum33_dsp dsp_reference (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .load_bias(load_bias), .enable(enable), .bias(bias), .delta(delta),
        .value_valid(valid_dsp), .value(value_dsp), .clamped(clamp_dsp),
        .overflow(overflow_dsp)
    );
    z100_accum33_fabric32_v1 fabric_candidate (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .load_bias(load_bias), .enable(enable), .bias(bias), .delta(delta),
        .value_valid(valid_fabric), .value(value_fabric), .clamped(clamp_fabric),
        .overflow(overflow_fabric)
    );

    reg model_valid = 1'b0;
    reg [32:0] model_state = 33'd0;
    integer checks = 0;
    integer loads = 0;
    integer updates = 0;
    integer holds = 0;
    integer flushes = 0;
    integer streak = 0;
    integer max_streak = 0;
    integer run_id, groups, g;
    reg [31:0] rng;
    reg signed [31:0] old_biases [0:7];
    reg [32:0] expected_value;
    reg [31:0] expected_clamp;
    reg expected_overflow;

    task automatic compare_outputs;
        reg [32:0] compare_value;
        reg [31:0] compare_clamp;
        reg compare_overflow;
        begin
            compare_value = model_valid ? model_state : 33'd0;
            compare_overflow = model_valid && (model_state[32] != model_state[31]);
            if (!model_valid)
                compare_clamp = 32'd0;
            else if (compare_overflow)
                compare_clamp = model_state[32] ? 32'h80000000 : 32'h7fffffff;
            else
                compare_clamp = model_state[31:0];

            if (valid_dsp !== model_valid || value_dsp !== compare_value ||
                clamp_dsp !== compare_clamp || overflow_dsp !== compare_overflow)
                $fatal(1, "DSP/reference mismatch checks=%0d got valid=%b value=%h clamp=%h ov=%b expected valid=%b value=%h clamp=%h ov=%b",
                    checks, valid_dsp, value_dsp, clamp_dsp, overflow_dsp,
                    model_valid, compare_value, compare_clamp, compare_overflow);
            if (valid_fabric !== model_valid || value_fabric !== compare_value ||
                clamp_fabric !== compare_clamp || overflow_fabric !== compare_overflow)
                $fatal(1, "fabric/golden mismatch checks=%0d got valid=%b value=%h clamp=%h ov=%b expected valid=%b value=%h clamp=%h ov=%b",
                    checks, valid_fabric, value_fabric, clamp_fabric, overflow_fabric,
                    model_valid, compare_value, compare_clamp, compare_overflow);
            if (valid_dsp !== valid_fabric || value_dsp !== value_fabric ||
                clamp_dsp !== clamp_fabric || overflow_dsp !== overflow_fabric)
                $fatal(1, "DSP/fabric miter mismatch checks=%0d", checks);
        end
    endtask

    task automatic step(
        input bit ld, input bit en, input bit can, input bit reset_high,
        input signed [31:0] b, input signed [18:0] d
    );
        begin
            @(negedge clk);
            load_bias = ld;
            enable = en;
            cancel = can;
            rst_n = reset_high;
            bias = b;
            delta = d;
            #1;
            if ((!reset_high || can) &&
                (valid_dsp !== 1'b0 || value_dsp !== 33'd0 ||
                 clamp_dsp !== 32'd0 || overflow_dsp !== 1'b0 ||
                 valid_fabric !== 1'b0 || value_fabric !== 33'd0 ||
                 clamp_fabric !== 32'd0 || overflow_fabric !== 1'b0))
                $fatal(1, "reset/cancel did not mask the visible payload immediately");

            @(posedge clk);
            if (!reset_high || can) begin
                model_valid = 1'b0;
                model_state = 33'd0;
                flushes = flushes + 1;
                streak = 0;
            end else if (ld) begin
                // load_bias has priority over enable and ignores delta.
                model_state = {b[31], b};
                model_valid = 1'b1;
                loads = loads + 1;
                streak = 0;
            end else if (en && model_valid) begin
                // Assignment to 33 bits is the independent modulo-2^33 model.
                model_state = model_state + {{14{d[18]}}, d};
                updates = updates + 1;
                streak = streak + 1;
                if (streak > max_streak)
                    max_streak = streak;
            end else begin
                holds = holds + 1;
                streak = 0;
            end
            #1;
            compare_outputs();
            checks = checks + 1;
        end
    endtask

    initial begin
        old_biases[0] = 32'sh80000000;
        old_biases[1] = 32'sh7fffffff;
        old_biases[2] = -32'sd1;
        old_biases[3] = 32'sd0;
        old_biases[4] = 32'sd1;
        old_biases[5] = -32'sd2147483600;
        old_biases[6] = 32'sd2147483600;
        old_biases[7] = 32'sd1234567;
        rng = 32'h351bc9e7;

        // Establish initialized=0 in both DUTs before testing visible invalid state.
        repeat (3) @(posedge clk);
        #1;
        compare_outputs();

        // Uninitialized enable must not update; a simultaneous bias load wins.
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sh3ffff);
        step(1'b1, 1'b1, 1'b0, 1'b1, 32'sh7fffffff, 19'sh3ffff);
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sd1);
        if (model_state !== 33'h080000000)
            $fatal(1, "positive signed32 saturation boundary vector mismatch");

        // Reuse the accepted legacy bias/group/delta vector schedule.
        for (run_id = 0; run_id < 64; run_id = run_id + 1) begin
            case (run_id % 6)
                0: groups = 1;
                1: groups = 2;
                2: groups = 9;
                3: groups = 36;
                4: groups = 576;
                default: groups = 1024;
            endcase
            step(1'b1, 1'b1, 1'b0, 1'b1, old_biases[run_id % 8], 19'sh3ffff);
            for (g = 0; g < groups; g = g + 1) begin
                rng = {rng[30:0], rng[31] ^ rng[21] ^ rng[1] ^ rng[0]};
                case (run_id % 4)
                    0: step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sh3ffff);
                    1: step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sh40000);
                    default: step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, rng[18:0]);
                endcase
            end
            step(1'b0, 1'b0, 1'b0, 1'b1, 32'sh80000000, 19'sh40000);
            step(1'b0, 1'b0, 1'b0, 1'b1, 32'sh7fffffff, 19'sh3ffff);
            if ((run_id % 8) == 0) begin
                step(1'b1, 1'b1, 1'b1, 1'b1, 32'sh7fffffff, 19'sh3ffff);
                step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sh3ffff);
            end
            if ((run_id % 8) == 4) begin
                step(1'b0, 1'b1, 1'b0, 1'b0, 32'sd0, 19'sh40000);
                step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sh40000);
            end
        end

        // Hold with changing operands; no state update while enable is low.
        step(1'b1, 1'b0, 1'b0, 1'b1, 32'sh13579bdf, 19'sd0);
        for (g = 0; g < 1024; g = g + 1)
            step(1'b0, 1'b0, 1'b0, 1'b1, 32'sh2468ace0, 19'sh3ffff);

        // Consecutive updates prove one accepted update per cycle (II=1).
        step(1'b1, 1'b0, 1'b0, 1'b1, 32'sd0, 19'sd0);
        for (g = 0; g < 1024; g = g + 1)
            step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sd123);
        if (max_streak < 1024)
            $fatal(1, "continuous-update coverage did not reach 1024 cycles");

        // Positive 33-bit wrap: max signed32 bias, then 8192 positive signed19 deltas.
        step(1'b1, 1'b0, 1'b0, 1'b1, 32'sh7fffffff, 19'sd0);
        for (g = 0; g < 8192; g = g + 1)
            step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sh3ffff);
        if (model_state !== 33'h0ffffdfff)
            $fatal(1, "positive pre-wrap vector mismatch got=%h", model_state);
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sd8192);
        if (model_state !== 33'h0ffffffff)
            $fatal(1, "positive signed33 maximum vector mismatch got=%h", model_state);
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sd1);
        if (model_state !== 33'h100000000)
            $fatal(1, "positive 33-bit wrap vector mismatch got=%h", model_state);
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, -19'sd1);
        if (model_state !== 33'h0ffffffff)
            $fatal(1, "post-wrap decrement vector mismatch got=%h", model_state);

        // Negative 33-bit wrap: minimum signed32 bias then 8192 minimum deltas.
        step(1'b1, 1'b0, 1'b0, 1'b1, 32'sh80000000, 19'sd0);
        for (g = 0; g < 8192; g = g + 1)
            step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sh40000);
        if (model_state !== 33'h100000000)
            $fatal(1, "negative signed33 minimum vector mismatch got=%h", model_state);
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, -19'sd1);
        if (model_state !== 33'h0ffffffff)
            $fatal(1, "negative 33-bit wrap vector mismatch got=%h", model_state);

        // Reset, cancel, and fresh load after nonzero state.
        step(1'b1, 1'b0, 1'b0, 1'b1, 32'sd777, 19'sd0);
        step(1'b0, 1'b1, 1'b0, 1'b0, 32'sd0, 19'sd9);
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sd9);
        step(1'b1, 1'b0, 1'b0, 1'b1, -32'sd1234, 19'sd0);
        step(1'b0, 1'b1, 1'b1, 1'b1, 32'sd0, 19'sd99);
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sd99);
        step(1'b1, 1'b0, 1'b0, 1'b1, 32'sd42, 19'sd999);
        step(1'b0, 1'b1, 1'b0, 1'b1, 32'sd0, 19'sd1);

        if (loads < 64 || updates < 17000 || holds < 1024 ||
            flushes < 10 || max_streak < 8192)
            $fatal(1, "miter coverage insufficient checks=%0d loads=%0d updates=%0d holds=%0d flushes=%0d max_streak=%0d",
                checks, loads, updates, holds, flushes, max_streak);
        $display("ACCUM33_FABRIC32_MITER_PASS checks=%0d loads=%0d updates=%0d holds=%0d flushes=%0d max_streak=%0d",
            checks, loads, updates, holds, flushes, max_streak);
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "accum33 fabric32 miter watchdog");
    end
endmodule
`default_nettype wire
