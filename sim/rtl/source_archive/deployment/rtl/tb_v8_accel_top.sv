`timescale 1ns/1ps

module tb_v8_accel_top;
    reg clk = 0;
    reg rst_n = 0;
    reg [31:0] reg0 = 0;
    reg [31:0] reg1 = 0;
    reg [31:0] reg2 = 0;
    reg [31:0] reg3 = 0;
    reg [31:0] mm2s_data = 0;
    reg [3:0] mm2s_keep = 4'hf;
    reg mm2s_valid = 0;
    wire mm2s_ready;
    reg mm2s_last = 0;
    wire [31:0] s2mm_data;
    wire [3:0] s2mm_keep;
    wire s2mm_valid;
    reg s2mm_ready = 0;
    wire s2mm_last;
    wire task_finish;
    integer checks = 0;
    integer stage = 0;
    reg [31:0] prng = 32'h1bad_f00d;

    always #5 clk = ~clk;

    v8_accel_top dut (
        .sclk(clk), .s_rst_n(rst_n),
        .slave_lite_reg0(reg0), .slave_lite_reg1(reg1),
        .slave_lite_reg2(reg2), .slave_lite_reg3(reg3),
        .s_axis_mm2s_tdata(mm2s_data), .s_axis_mm2s_tkeep(mm2s_keep),
        .s_axis_mm2s_tvalid(mm2s_valid), .s_axis_mm2s_tready(mm2s_ready),
        .s_axis_mm2s_tlast(mm2s_last), .s_axis_s2mm_tdata(s2mm_data),
        .s_axis_s2mm_tkeep(s2mm_keep), .s_axis_s2mm_tvalid(s2mm_valid),
        .s_axis_s2mm_tready(s2mm_ready), .s_axis_s2mm_tlast(s2mm_last),
        .task_finish(task_finish)
    );

    task automatic check(input condition, input [8*96-1:0] message);
        begin
            checks = checks + 1;
            if (!condition) begin
                $display("FAIL: %0s at time %0t", message, $time);
                $fatal(1);
            end
        end
    endtask

    task automatic launch(input [31:0] taps, input [31:0] dots,
                          input [31:0] bias);
        begin
            @(negedge clk);
            reg0[0] = 1'b0;
            reg1 = taps;
            reg2 = bias;
            reg3 = dots;
            @(negedge clk);
            reg0[0] = 1'b1;
            @(negedge clk);
            reg0[0] = 1'b0;
        end
    endtask

    task automatic send_word(input [31:0] value, input [3:0] keep,
                             input last);
        begin
            @(negedge clk);
            mm2s_data = value;
            mm2s_keep = keep;
            mm2s_last = last;
            mm2s_valid = 1'b1;
            do begin
                @(posedge clk);
            end while (!mm2s_ready);
            @(negedge clk);
            mm2s_valid = 1'b0;
            mm2s_last = 1'b0;
            mm2s_keep = 4'hf;
        end
    endtask

    task automatic send_zero_taps(input integer count);
        integer i;
        begin
            for (i = 0; i < count; i = i + 1)
                send_word(32'b0, 4'hf, i == count-1);
        end
    endtask

    function automatic [31:0] xorshift32(input [31:0] state);
        reg [31:0] value;
        begin
            value = state;
            value = value ^ (value << 13);
            value = value ^ (value >> 17);
            value = value ^ (value << 5);
            xorshift32 = value;
        end
    endfunction

    task automatic send_random_gap_word(input [31:0] value,
                                        input [3:0] keep,
                                        input last);
        integer gap_cycles;
        begin
            prng = xorshift32(prng);
            gap_cycles = prng[1:0];
            @(negedge clk);
            mm2s_valid = 1'b0;
            repeat (gap_cycles) @(negedge clk);
            mm2s_data = value;
            mm2s_keep = keep;
            mm2s_last = last;
            mm2s_valid = 1'b1;
            do begin
                @(posedge clk);
            end while (!mm2s_ready);
            @(negedge clk);
            mm2s_valid = 1'b0;
            mm2s_last = 1'b0;
            mm2s_keep = 4'hf;
        end
    endtask

    task automatic take_word(input [31:0] expected_data,
                             input expected_last,
                             input expected_finish,
                             input integer stall_cycles);
        integer i;
        begin
            while (!s2mm_valid) begin
                @(posedge clk);
                #1;
            end
            check(s2mm_data === expected_data, "output data before ready");
            check(s2mm_keep === 4'hf, "output keep is full word");
            check(s2mm_last === expected_last, "output TLAST placement");
            check(task_finish === 1'b0, "task_finish waits for final status handshake");
            for (i = 0; i < stall_cycles; i = i + 1) begin
                @(posedge clk);
                #1;
                check(s2mm_valid === 1'b1, "output valid held under backpressure");
                check(s2mm_data === expected_data, "output data stable under backpressure");
                check(s2mm_keep === 4'hf, "output keep stable under backpressure");
                check(s2mm_last === expected_last, "output TLAST stable under backpressure");
                check(task_finish === 1'b0, "finish remains low under backpressure");
            end
            @(negedge clk);
            s2mm_ready = 1'b1;
            @(posedge clk);
            check(s2mm_valid === 1'b1, "valid is asserted on output handshake");
            check(s2mm_data === expected_data, "data matches on output handshake");
            check(s2mm_last === expected_last, "TLAST matches on output handshake");
            #1;
            s2mm_ready = 1'b0;
            check(task_finish === expected_finish,
                  "task_finish only pulses on final status transfer");
            if (expected_finish) begin
                @(posedge clk);
                #1;
                check(task_finish === 1'b0, "task_finish is a one-cycle pulse");
                check(s2mm_valid === 1'b0, "completed operation has no extra output");
            end
        end
    endtask

    task automatic expect_pair(input [31:0] raw, input error,
                               input final_dot, input integer raw_stall,
                               input integer status_stall);
        begin
            take_word(raw, 1'b0, 1'b0, raw_stall);
            take_word(32'h563A0000 | {31'b0, error}, final_dot,
                      final_dot, status_stall);
        end
    endtask

    task automatic check_no_output(input integer cycles);
        integer i;
        begin
            for (i = 0; i < cycles; i = i + 1) begin
                @(posedge clk);
                #1;
                check(s2mm_valid === 1'b0, "no unexpected extra output");
                check(task_finish === 1'b0, "no repeated finish pulse");
            end
        end
    endtask

    task automatic abort_and_check;
        begin
            @(negedge clk);
            reg0[1] = 1'b1;
            repeat (2) @(posedge clk);
            @(negedge clk);
            reg0[1] = 1'b0;
            repeat (2) @(posedge clk);
            #1;
            check(s2mm_valid === 1'b0, "abort clears output valid");
            check(mm2s_ready === 1'b0, "abort clears input ready");
            check(task_finish === 1'b0, "abort clears finish state");
        end
    endtask

    task automatic check_no_output_while_truncated(input integer cycles);
        integer i;
        begin
            for (i = 0; i < cycles; i = i + 1) begin
                @(posedge clk);
                #1;
                check(s2mm_valid === 1'b0,
                      "truncated dot emits no partial result");
                check(task_finish === 1'b0,
                      "truncated dot does not finish before abort");
            end
        end
    endtask

    function automatic [31:0] encoded(input integer activation,
                                      input integer weight);
        reg signed [7:0] a;
        reg signed [7:0] w;
        begin
            a = activation;
            w = weight;
            encoded = {16'b0, w, a};
        end
    endfunction

    integer i;
    integer raw_stall;
    integer status_stall;
    initial begin
        repeat (4) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;

        // T=0, B=1 is the successful no-input bias probe.
        stage = 1;
        launch(0, 1, 32'h18C047A5);
        expect_pair(32'h18C047A5, 1'b0, 1'b1, 2, 2);

        // Every invalid shape returns one error pair and accepts no input.
        stage = 2;
        launch(1, 0, 32'd9);
        check(mm2s_ready === 1'b0, "B=0 invalid config refuses input");
        expect_pair(0, 1'b1, 1'b1, 0, 0);
        check_no_output(2);

        launch(16384, 1, 32'd0);
        expect_pair(0, 1'b1, 1'b1, 0, 0);
        check_no_output(2);

        launch(16383, 2, 32'd0);
        expect_pair(0, 1'b1, 1'b1, 0, 0);
        check_no_output(2);

        launch(0, 2, 32'd0);
        expect_pair(0, 1'b1, 1'b1, 0, 0);
        check_no_output(2);

        launch(1, 1025, 32'd0);
        expect_pair(0, 1'b1, 1'b1, 0, 0);
        check_no_output(2);
        launch(1, 2048, 0);
        expect_pair(0, 1'b1, 1'b1, 0, 0);
        launch(65536, 1, 0);
        expect_pair(0, 1'b1, 1'b1, 0, 0);
        launch(16, 1024, 0);
        expect_pair(0, 1'b1, 1'b1, 0, 0);

        // Signed products and bias: 10 + (-4*3) + (7*-2) = -16.
        stage = 3;
        launch(2, 1, 32'd10);
        send_word(encoded(-4, 3), 4'hf, 1'b0);
        send_word(encoded(7, -2), 4'hf, 1'b1);
        expect_pair(32'hfffffff0, 1'b0, 1'b1, 3, 4);

        // B=2, T=2: dot-major packets; physical TLAST occurs only at word 4.
        // Attempt register edits and a busy START pulse after dot zero begins.
        stage = 4;
        launch(2, 2, 32'd5);
        send_word(encoded(1, 3), 4'hf, 1'b0);
        @(negedge clk);
        reg1 = 1;
        reg2 = 32'd999;
        reg3 = 1;
        reg0[0] = 1'b1;
        @(negedge clk);
        reg0[0] = 1'b0;
        send_word(encoded(2, -1), 4'hf, 1'b0);
        expect_pair(32'd6, 1'b0, 1'b0, 2, 2);
        send_word(encoded(-4, -2), 4'hf, 1'b0);
        send_word(encoded(3, 1), 4'hf, 1'b1);
        expect_pair(32'd16, 1'b0, 1'b1, 1, 3);

        // External early and missing packet TLAST are sticky errors.
        stage = 5;
        launch(1, 2, 32'd0);
        send_word(encoded(2, 3), 4'hf, 1'b1);
        expect_pair(32'd6, 1'b1, 1'b0, 0, 0);
        send_word(encoded(4, 5), 4'hf, 1'b1);
        expect_pair(32'd20, 1'b1, 1'b1, 0, 0);

        launch(1, 1, 32'd0);
        send_word(encoded(2, 3), 4'hf, 1'b0);
        expect_pair(32'd6, 1'b1, 1'b1, 0, 0);

        launch(1, 1, 32'd0);
        send_word(encoded(2, 3), 4'h7, 1'b1);
        expect_pair(32'd6, 1'b1, 1'b1, 0, 0);

        // MAC overflow is returned as a saturated raw result plus error status.
        stage = 6;
        launch(1, 1, 32'h7fffffff);
        send_word(encoded(1, 1), 4'hf, 1'b1);
        expect_pair(32'h7fffffff, 1'b1, 1'b1, 1, 2);
        launch(1, 1, 32'h80000000);
        send_word(encoded(1, -1), 4'hf, 1'b1);
        expect_pair(32'h80000000, 1'b1, 1'b1, 0, 0);

        // Abort while accepting taps, while RAW is stalled, and while STATUS is stalled.
        stage = 7;
        launch(2, 1, 32'd4);
        send_word(encoded(2, 2), 4'hf, 1'b0);
        abort_and_check();
        launch(1, 1, 32'd7);
        send_word(encoded(2, 3), 4'hf, 1'b1);
        while (!s2mm_valid) begin @(posedge clk); #1; end
        abort_and_check();
        launch(1, 1, 32'd8);
        send_word(encoded(2, 3), 4'hf, 1'b1);
        while (!s2mm_valid) begin @(posedge clk); #1; end
        take_word(32'd14, 1'b0, 1'b0, 0);
        check(s2mm_valid === 1'b1, "status pending before status-phase abort");
        abort_and_check();

        // Clean relaunch after all abort points.
        stage = 8;
        launch(1, 1, 32'd11);
        send_word(encoded(2, 3), 4'hf, 1'b1);
        expect_pair(32'd17, 1'b0, 1'b1, 0, 0);

        // Pseudo-random VALID gaps and output stalls across a three-dot tail batch.
        stage = 9;
        launch(3, 3, 32'hfffffffe);
        send_random_gap_word(encoded(2, 3), 4'hf, 1'b0);
        send_random_gap_word(encoded(-1, 4), 4'hf, 1'b0);
        send_random_gap_word(encoded(3, -2), 4'hf, 1'b0);
        prng = xorshift32(prng);
        raw_stall = prng[2:1];
        prng = xorshift32(prng);
        status_stall = prng[2:1];
        expect_pair(32'hfffffffa, 1'b0, 1'b0, raw_stall, status_stall);

        send_random_gap_word(encoded(-3, 5), 4'hf, 1'b0);
        send_random_gap_word(encoded(7, 2), 4'hf, 1'b0);
        send_random_gap_word(encoded(4, 1), 4'hf, 1'b0);
        prng = xorshift32(prng);
        raw_stall = prng[2:1];
        prng = xorshift32(prng);
        status_stall = prng[2:1];
        expect_pair(32'd1, 1'b0, 1'b0, raw_stall, status_stall);

        send_random_gap_word(encoded(10, 2), 4'hf, 1'b0);
        send_random_gap_word(encoded(0, 7), 4'hf, 1'b0);
        send_random_gap_word(encoded(-2, 3), 4'hf, 1'b1);
        prng = xorshift32(prng);
        raw_stall = prng[2:1];
        prng = xorshift32(prng);
        status_stall = prng[2:1];
        expect_pair(32'd12, 1'b0, 1'b1, raw_stall, status_stall);

        // An early physical TLAST followed by too few taps never emits a result.
        stage = 10;
        launch(3, 1, 32'd0);
        send_word(encoded(2, 3), 4'hf, 1'b1);
        send_word(encoded(4, 5), 4'hf, 1'b0);
        check_no_output_while_truncated(8);
        abort_and_check();

        // A beat presented after the exact packet end is never accepted.
        stage = 11;
        launch(1, 1, 32'd2);
        send_word(encoded(3, 4), 4'hf, 1'b1);
        @(negedge clk);
        mm2s_data = encoded(99, 99);
        mm2s_keep = 4'hf;
        mm2s_last = 1'b1;
        mm2s_valid = 1'b1;
        repeat (6) begin
            @(posedge clk);
            #1;
            check(mm2s_ready === 1'b0,
                  "extra beat after packet end is backpressured");
            check(dut.input_words_accepted === 1,
                  "extra beat is not counted as accepted input");
        end
        expect_pair(32'd14, 1'b0, 1'b1, 0, 0);
        check(dut.input_words_accepted === 1,
              "completed packet count excludes the extra beat");
        @(negedge clk);
        mm2s_valid = 1'b0;
        mm2s_last = 1'b0;

        // Abort immediately after the last tap, during core result generation.
        stage = 12;
        launch(2, 1, 32'd0);
        send_word(encoded(1, 1), 4'hf, 1'b0);
        @(negedge clk);
        mm2s_data = encoded(2, 2);
        mm2s_keep = 4'hf;
        mm2s_last = 1'b1;
        mm2s_valid = 1'b1;
        do begin
            @(posedge clk);
        end while (!mm2s_ready);
        @(negedge clk);
        mm2s_valid = 1'b0;
        mm2s_last = 1'b0;
        reg0[1] = 1'b1;
        check(s2mm_valid === 1'b0,
              "abort is asserted before the result becomes valid");
        repeat (2) @(posedge clk);
        #1;
        check(s2mm_valid === 1'b0,
              "pipeline abort discards the in-flight result");
        @(negedge clk);
        reg0[1] = 1'b0;
        repeat (2) @(posedge clk);
        #1;
        check(s2mm_valid === 1'b0,
              "pipeline abort leaves no pending result");
        launch(1, 1, 32'd6);
        send_word(encoded(2, 4), 4'hf, 1'b1);
        expect_pair(32'd14, 1'b0, 1'b1, 0, 0);

        // Largest legal T and largest B independently exercise counter bounds.
        stage = 13;
        @(negedge clk);reg0=0;reg1=1;reg2=3;reg3=2;
        @(negedge clk);reg0=1;
        @(posedge clk);#1;
        check(dut.phase==6 && !mm2s_ready && !s2mm_valid,
              "configuration check launches no core or stream work");
        @(negedge clk);reg0=0;reg1=0;reg2=999;reg3=1;
        send_word(encoded(2,3),4'hf,0);
        expect_pair(9,0,0,0,0);
        send_word(encoded(4,-1),4'hf,1);
        expect_pair(32'hffffffff,0,1,0,0);

        @(negedge clk);reg0=0;reg1=2;reg2=7;reg3=2;
        @(negedge clk);reg0=1;
        @(posedge clk);#1;check(dut.phase==6,"abort target is configuration stage");
        @(negedge clk);reg0=2;
        repeat(3) @(negedge clk);
        check(!mm2s_ready && !s2mm_valid,"configuration abort discards pending work");
        reg0=0;repeat(3) @(negedge clk);
        launch(0,1,32'h18c047a5);
        expect_pair(32'h18c047a5,0,1,0,0);

        launch(16383, 1, 32'hfffffff9);
        send_zero_taps(16383);
        expect_pair(32'hfffffff9, 1'b0, 1'b1, 0, 0);

        launch(1, 1024, 32'd0);
        for (i = 0; i < 1024; i = i + 1) begin
            send_word(32'b0, 4'hf, i == 1023);
            expect_pair(0, 1'b0, i == 1023, 0, 0);
        end

        check_no_output(3);
        $display("PASS: tb_v8_accel_top completed %0d checks", checks);
        $finish;
    end

    initial begin
        #10000000;
        $display("FAIL: watchdog expired at stage %0d phase %0d dots_remaining %0d accepted %0d in_dot %0d valid %b ready %b output %h finish %b",
                 stage, dut.phase, dut.dots_remaining, dut.input_words_accepted,
                 dut.input_words_in_dot, mm2s_valid, mm2s_ready,
                 s2mm_data, task_finish);
        $fatal(1);
    end
endmodule
