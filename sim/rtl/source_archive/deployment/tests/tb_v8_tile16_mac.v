`timescale 1ns/1ps

module tb_v8_tile16_mac;
    localparam MAX_TAPS = 4091;
    localparam signed [63:0] MAX_SIGNED32 = 64'sh000000007fffffff;
    localparam signed [63:0] MIN_SIGNED32 = -64'sh0000000080000000;

    reg clk = 0;
    reg rst_n = 0;
    reg cfg_weight_we = 0;
    reg [11:0] cfg_weight_addr = 0;
    reg [127:0] cfg_weights = 0;
    reg cfg_bias_we = 0;
    reg [511:0] cfg_biases = 0;
    wire cfg_ready;

    reg run = 0;
    reg [12:0] tap_count = 0;
    reg [4:0] lane_count = 0;
    reg act_valid = 0;
    reg signed [7:0] act_data = 0;
    wire act_ready;

    wire out_valid;
    wire [4:0] out_lane_count;
    wire [511:0] out_raw;
    wire [15:0] out_overflow;
    wire error;
    wire busy;

    reg signed [31:0] bias_ref [0:15];
    integer lane_i;
    integer tap_i;
    integer timeout_i;

    always #5 clk = ~clk;

    v8_tile16_mac #(.MAX_TAPS(MAX_TAPS)) dut (
        .clk(clk),
        .rst_n(rst_n),
        .cfg_weight_we(cfg_weight_we),
        .cfg_weight_addr(cfg_weight_addr),
        .cfg_weights(cfg_weights),
        .cfg_bias_we(cfg_bias_we),
        .cfg_biases(cfg_biases),
        .cfg_ready(cfg_ready),
        .run(run),
        .tap_count(tap_count),
        .lane_count(lane_count),
        .act_valid(act_valid),
        .act_data(act_data),
        .act_ready(act_ready),
        .out_valid(out_valid),
        .out_lane_count(out_lane_count),
        .out_raw(out_raw),
        .out_overflow(out_overflow),
        .error(error),
        .busy(busy)
    );

    function integer weight_for;
        input integer tap;
        input integer lane;
        begin
            if (lane == 2)
                weight_for = 127;
            else if (lane == 3)
                weight_for = -127;
            else
                weight_for = ((tap * 3 + lane * 5) % 7) - 3;
        end
    endfunction

    function integer activation_for;
        input integer tap;
        input integer mode;
        begin
            case (mode)
                0: begin
                    case (tap % 4)
                        0: activation_for = 3;
                        1: activation_for = -2;
                        2: activation_for = 4;
                        default: activation_for = 5;
                    endcase
                end
                1: begin
                    case (tap % 3)
                        0: activation_for = -4;
                        1: activation_for = 2;
                        default: activation_for = 5;
                    endcase
                end
                2: activation_for = 2;
                default: activation_for = 127;
            endcase
        end
    endfunction

    task fail;
        input [8*120-1:0] message;
        begin
            $display("FAIL: %0s at time %0t", message, $time);
            $fatal(1);
        end
    endtask

    task load_biases;
        integer k;
        begin
            cfg_biases = 0;
            for (k = 0; k < 16; k = k + 1)
                cfg_biases[(k * 32) +: 32] = bias_ref[k];
            @(negedge clk);
            if (!cfg_ready)
                fail("configuration unexpectedly not ready for biases");
            cfg_bias_we = 1;
            @(negedge clk);
            cfg_bias_we = 0;
        end
    endtask

    task load_all_weights;
        integer t;
        integer k;
        reg [127:0] weight_word;
        begin
            for (t = 0; t < MAX_TAPS; t = t + 1) begin
                weight_word = 0;
                for (k = 0; k < 16; k = k + 1)
                    weight_word[(k * 8) +: 8] = weight_for(t, k);
                @(negedge clk);
                cfg_weight_addr = t;
                cfg_weights = weight_word;
                cfg_weight_we = 1;
            end
            @(negedge clk);
            cfg_weight_we = 0;
        end
    endtask

    task reject_invalid_run;
        begin
            @(negedge clk);
            tap_count = MAX_TAPS + 1;
            lane_count = 16;
            run = 1;
            @(negedge clk);
            run = 0;
            if (busy)
                fail("invalid tap count started the MAC");
            if (!error)
                fail("invalid tap count did not raise error");
            @(posedge clk);
            #1;
            if (error)
                fail("error was not a one-cycle pulse");

            @(negedge clk);
            tap_count = 1;
            lane_count = 0;
            run = 1;
            @(negedge clk);
            run = 0;
            if (busy)
                fail("zero lane count started the MAC");
            if (!error)
                fail("zero lane count did not raise error");
            @(posedge clk);
            #1;
            if (error)
                fail("lane-count error was not a one-cycle pulse");
        end
    endtask

    task begin_site;
        input integer taps;
        input integer lanes;
        begin
            @(negedge clk);
            tap_count = taps;
            lane_count = lanes;
            run = 1;
            @(negedge clk);
            run = 0;
            if (!busy)
                fail("valid site run did not enter busy state");
            if (out_valid)
                fail("result became valid before activation input");
        end
    endtask

    task send_activation;
        input integer tap;
        input integer value;
        integer prior_index;
        integer prior_remaining;
        integer accepted;
        begin
            if ((tap % 3) == 1) begin
                @(negedge clk);
                act_valid = 0;
                prior_index = dut.tap_index;
                prior_remaining = dut.taps_remaining;
                repeat (2) begin
                    @(posedge clk);
                    #1;
                    if (dut.tap_index !== prior_index)
                        fail("tap index advanced while activation input was stalled");
                    if (dut.taps_remaining !== prior_remaining)
                        fail("remaining tap count changed while input was stalled");
                    if (out_valid)
                        fail("result became valid while activation input was stalled");
                end
            end

            @(negedge clk);
            act_data = value;
            act_valid = 1;
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (act_ready === 1'b1)
                    accepted = 1;
            end
            @(negedge clk);
            act_valid = 0;
        end
    endtask

    task check_site;
        input integer taps;
        input integer lanes;
        input integer act_mode;
        integer l;
        integer t;
        integer act_value;
        integer weight_value;
        integer wait_cycles;
        reg signed [63:0] total;
        reg [31:0] expected_raw;
        reg expected_overflow;
        begin
            begin_site(taps, lanes);
            for (t = 0; t < taps; t = t + 1) begin
                send_activation(t, activation_for(t, act_mode));
                if (t < (taps - 1)) begin
                    @(posedge clk);
                    #1;
                    if (out_valid)
                        fail("result became valid before all taps were consumed");
                end
            end
            if (act_ready)
                fail("tile accepted more than tap_count activations");

            wait_cycles = 0;
            while ((out_valid !== 1'b1) && (wait_cycles < 8)) begin
                @(posedge clk);
                #1;
                wait_cycles = wait_cycles + 1;
            end
            if (out_valid !== 1'b1)
                fail("result did not become valid after the final tap");
            if (busy)
                fail("busy remained set after result publication");
            if (out_lane_count !== lanes)
                fail("reported output lane count is incorrect");

            for (l = 0; l < 16; l = l + 1) begin
                total = bias_ref[l];
                if (l < lanes) begin
                    for (t = 0; t < taps; t = t + 1) begin
                        act_value = activation_for(t, act_mode);
                        weight_value = weight_for(t, l);
                        total = total + (act_value * weight_value);
                    end
                    if (total > MAX_SIGNED32) begin
                        expected_raw = 32'h7fffffff;
                        expected_overflow = 1;
                    end else if (total < MIN_SIGNED32) begin
                        expected_raw = 32'h80000000;
                        expected_overflow = 1;
                    end else begin
                        expected_raw = total[31:0];
                        expected_overflow = 0;
                    end
                end else begin
                    expected_raw = 0;
                    expected_overflow = 0;
                end

                if (out_raw[(l * 32) +: 32] !== expected_raw) begin
                    $display("lane %0d raw mismatch: got %08x expected %08x", l,
                        out_raw[(l * 32) +: 32], expected_raw);
                    fail("raw accumulator value mismatch");
                end
                if (out_overflow[l] !== expected_overflow) begin
                    $display("lane %0d overflow mismatch: got %b expected %b", l,
                        out_overflow[l], expected_overflow);
                    fail("overflow flag mismatch");
                end
            end
            $display("PASS site: taps=%0d lanes=%0d mode=%0d", taps, lanes, act_mode);
        end
    endtask

    initial begin
        for (lane_i = 0; lane_i < 16; lane_i = lane_i + 1)
            bias_ref[lane_i] = (lane_i * 17) - 50;
        bias_ref[2] = 32'sh7fffff00;
        bias_ref[3] = 32'sh80000100;

        repeat (4) @(negedge clk);
        rst_n = 1;
        load_biases;
        reject_invalid_run;
        load_all_weights;

        // Checks mixed-sign products, lane-tail masking, both signed32 clamps,
        // input backpressure, and consecutive spatial sites without reload.
        check_site(4, 3, 0);
        check_site(3, 4, 1);
        check_site(1, 1, 2);

        // Exercise the full 4091-tap bank depth and all 16 active lanes.
        check_site(MAX_TAPS, 16, 3);

        $display("PASS: v8_tile16_mac all checks completed");
        $finish;
    end
endmodule
