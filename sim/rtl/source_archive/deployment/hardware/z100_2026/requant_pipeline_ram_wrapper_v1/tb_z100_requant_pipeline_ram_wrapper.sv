module tb_z100_requant_pipeline_ram_wrapper;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n = 1'b0;
    reg cancel = 1'b0;
    reg cfg_begin = 1'b0;
    wire cfg_begin_ready;
    reg cfg_word_valid = 1'b0;
    wire cfg_word_ready;
    reg signed [32:0] cfg_key = 33'sd0;
    reg cfg_commit = 1'b0;
    wire cfg_commit_ready;
    wire cfg_error;
    reg in_valid = 1'b0;
    wire in_ready;
    reg signed [31:0] in_data = 32'sd0;
    wire out_valid;
    reg out_ready = 1'b0;
    wire signed [7:0] out_data;

    z100_requant_pipeline_ram_wrapper dut (.*);

    reg [32:0] tree [0:254];
    reg [31:0] stimulus [0:1023];
    reg [7:0] expected [0:1023];
    integer accept_cycle [0:1023];

    integer cycle_count = 0;
    integer accepted = 0;
    integer returned = 0;
    integer first_latency = -1;
    integer min_latency = 1000000;
    integer max_latency = 0;
    integer continuous_accept_ii_max = 0;
    integer continuous_result_ii_max = 0;
    integer blocked_output_cycles = 0;
    integer monitor_enable = 0;
    integer continuous_check = 0;
    integer previous_accept_cycle = -1;
    integer previous_result_cycle = -1;
    reg previous_stalled = 1'b0;
    reg signed [7:0] held_output = 8'sd0;

    always @(posedge clk) begin
        if (rst_n && monitor_enable) begin
            cycle_count = cycle_count + 1;
            if (previous_stalled && (!out_valid || out_data !== held_output))
                $fatal(1, "stalled output changed or disappeared");
            previous_stalled = out_valid && !out_ready;
            if (previous_stalled) begin
                held_output = out_data;
                blocked_output_cycles = blocked_output_cycles + 1;
            end

            if (in_valid && in_ready) begin
                if (accepted >= 1024) $fatal(1, "too many inputs accepted");
                accept_cycle[accepted] = cycle_count;
                if (continuous_check && accepted > 0 && accepted < 256) begin
                    if (cycle_count - previous_accept_cycle != 1)
                        $fatal(1, "continuous input interval was not one cycle");
                    continuous_accept_ii_max = 1;
                end
                previous_accept_cycle = cycle_count;
                accepted = accepted + 1;
            end

            if (out_valid && out_ready) begin
                integer this_latency;
                if (returned >= accepted) $fatal(1, "result without accepted input");
                if (out_data !== expected[returned])
                    $fatal(1, "result mismatch idx=%0d raw=%0d got=%0d expected=%0d",
                           returned, $signed(stimulus[returned]), $signed(out_data), $signed(expected[returned]));
                this_latency = cycle_count - accept_cycle[returned];
                if (first_latency < 0) first_latency = this_latency;
                if (this_latency < min_latency) min_latency = this_latency;
                if (this_latency > max_latency) max_latency = this_latency;
                if (continuous_check && returned > 0 && returned < 128) begin
                    if (cycle_count - previous_result_cycle != 1)
                        $fatal(1, "continuous result interval was not one cycle");
                    continuous_result_ii_max = 1;
                end
                previous_result_cycle = cycle_count;
                returned = returned + 1;
            end
        end
    end

    task begin_configuration;
        begin
            @(negedge clk);
            cfg_begin = 1'b1;
            @(posedge clk);
            if (!cfg_begin_ready) $fatal(1, "configuration begin was not ready");
            @(negedge clk);
            cfg_begin = 1'b0;
        end
    endtask

    task send_configuration_word;
        input signed [32:0] value;
        begin
            @(negedge clk);
            cfg_word_valid = 1'b1;
            cfg_key = value;
            @(posedge clk);
            if (!cfg_word_ready) $fatal(1, "configuration word was not ready");
            @(negedge clk);
            cfg_word_valid = 1'b0;
        end
    endtask

    task commit_configuration;
        begin
            @(negedge clk);
            cfg_commit = 1'b1;
            @(posedge clk);
            if (!cfg_commit_ready) $fatal(1, "configuration commit was not ready");
            @(negedge clk);
            cfg_commit = 1'b0;
            #1;
            if (cfg_error || !in_ready) $fatal(1, "complete table did not become runnable");
        end
    endtask

    task load_case;
        input integer which;
        reg [8*32-1:0] filename;
        integer k;
        begin
            $sformat(filename, "tree_%02d.hex", which);
            $readmemh(filename, tree);
            begin_configuration();
            for (k = 0; k < 255; k = k + 1)
                send_configuration_word(tree[k]);
            commit_configuration();
        end
    endtask

    task reset_case_counters;
        begin
            cycle_count = 0;
            accepted = 0;
            returned = 0;
            first_latency = -1;
            min_latency = 1000000;
            max_latency = 0;
            continuous_accept_ii_max = 0;
            continuous_result_ii_max = 0;
            blocked_output_cycles = 0;
            previous_accept_cycle = -1;
            previous_result_cycle = -1;
            previous_stalled = 1'b0;
        end
    endtask

    task run_case;
        input integer which;
        reg [8*32-1:0] filename;
        reg [31:0] lfsr;
        integer index;
        integer watchdog;
        begin
            $sformat(filename, "input_%02d.hex", which);
            $readmemh(filename, stimulus);
            $sformat(filename, "expected_%02d.hex", which);
            $readmemh(filename, expected);
            @(negedge clk);
            reset_case_counters();
            continuous_check = 1;
            monitor_enable = 1;
            lfsr = 32'h9e3779b9 ^ which;
            in_valid = 1'b1;
            in_data = stimulus[0];
            out_ready = 1'b1;
            index = 0;
            watchdog = 0;
            while (index < 1024 && watchdog < 10000) begin
                @(posedge clk);
                watchdog = watchdog + 1;
                if (in_ready) index = index + 1;
                if (index < 1024) begin
                    @(negedge clk);
                    in_data = stimulus[index];
                    if (index < 256) begin
                        out_ready = 1'b1;
                    end else begin
                        lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
                        out_ready = (lfsr[2:0] != 3'b000);
                    end
                end
            end
            if (index != 1024) $fatal(1, "input stream timeout");
            @(negedge clk);
            in_valid = 1'b0;
            continuous_check = 0;
            watchdog = 0;
            while (returned < 1024 && watchdog < 20000) begin
                lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
                out_ready = (lfsr[2:0] != 3'b000);
                @(posedge clk);
                watchdog = watchdog + 1;
                @(negedge clk);
            end
            if (accepted != 1024 || returned != 1024) $fatal(1, "stream coverage incomplete");
            if (!continuous_accept_ii_max || !continuous_result_ii_max)
                $fatal(1, "steady-state II=1 coverage missing");
            if (blocked_output_cycles == 0) $fatal(1, "random output stalls not exercised");
            out_ready = 1'b0;
            monitor_enable = 0;
            repeat (2) begin
                @(posedge clk);
                #1;
                if (out_valid) $fatal(1, "unexpected result after drain");
            end
            $display("PIPE_CASE id=%0d vectors=%0d no_stall_latency=%0d observed_latency_min=%0d observed_latency_max=%0d accept_ii=1 result_ii=1 blocked_cycles=%0d",
                     which, returned, first_latency, min_latency, max_latency, blocked_output_cycles);
        end
    endtask

    task fill_pipeline_without_output;
        integer sent;
        integer guard;
        begin
            @(negedge clk);
            in_valid = 1'b1;
            in_data = -32'sd500;
            out_ready = 1'b0;
            sent = 0;
            guard = 0;
            while (sent < 8 && guard < 100) begin
                @(posedge clk);
                guard = guard + 1;
                if (in_ready) sent = sent + 1;
                if (sent < 8) begin
                    @(negedge clk);
                    in_data = in_data + 32'sd1;
                end
            end
            @(negedge clk);
            in_valid = 1'b0;
            #1;
            if (sent != 8 || !out_valid || out_ready)
                $fatal(1, "failed to create a held pipeline result");
        end
    endtask

    integer stage_cancel_cases = 0;
    integer stage_reset_cases = 0;
    integer idle_abort_cases = 0;
    integer config_abort_cases = 0;
    integer context_swap_cases = 0;

    task send_and_check_one;
        input signed [31:0] raw_value;
        input signed [7:0] expected_value;
        integer watchdog;
        begin
            @(negedge clk);
            in_data = raw_value;
            in_valid = 1'b1;
            out_ready = 1'b1;
            @(posedge clk);
            if (!in_ready) $fatal(1, "directed transaction was not accepted");
            @(negedge clk);
            in_valid = 1'b0;
            watchdog = 0;
            while (!out_valid && watchdog < 20) begin
                @(posedge clk);
                watchdog = watchdog + 1;
                @(negedge clk);
            end
            if (!out_valid) $fatal(1, "directed transaction timed out");
            if (out_data !== expected_value)
                $fatal(1, "directed result mismatch raw=%0d got=%0d expected=%0d",
                       $signed(raw_value), $signed(out_data), $signed(expected_value));
            @(posedge clk);
            @(negedge clk);
            if (out_valid) $fatal(1, "directed transaction did not drain");
        end
    endtask

    task abort_one_stage;
        input integer target_stage;
        input integer use_reset;
        integer watchdog;
        begin
            if (!dut.pipe_empty) $fatal(1, "stage-abort precondition: pipeline not empty");
            @(negedge clk);
            out_ready = 1'b0;
            in_valid = 1'b1;
            in_data = -32'sd700 + target_stage;
            @(posedge clk);
            if (!in_ready) $fatal(1, "stage-abort input was not accepted");
            @(negedge clk);
            in_valid = 1'b0;
            watchdog = 0;
            while (!dut.valid_q[target_stage] && watchdog < 20) begin
                @(negedge clk);
                watchdog = watchdog + 1;
            end
            if (!dut.valid_q[target_stage]) $fatal(1, "did not reach target stage %0d", target_stage);
            if (use_reset) rst_n = 1'b0;
            else cancel = 1'b1;
            #1;
            if (out_valid || in_ready) $fatal(1, "abort did not suppress ownership at stage %0d", target_stage);
            @(posedge clk);
            #1;
            if (dut.valid_q[0] || dut.valid_q[1] || dut.valid_q[2] || dut.valid_q[3] ||
                dut.valid_q[4] || dut.valid_q[5] || dut.valid_q[6] || dut.valid_q[7])
                $fatal(1, "old context survived abort at stage %0d", target_stage);
            @(negedge clk);
            rst_n = 1'b1;
            cancel = 1'b0;
            out_ready = 1'b0;
            #1;
            if (out_valid || in_ready || !cfg_begin_ready)
                $fatal(1, "abort at stage %0d did not clear pipeline/table ownership", target_stage);
            if (use_reset) stage_reset_cases = stage_reset_cases + 1;
            else stage_cancel_cases = stage_cancel_cases + 1;
        end
    endtask

    task abort_idle;
        input integer use_reset;
        begin
            if (!dut.pipe_empty) $fatal(1, "idle-abort precondition: pipeline not empty");
            @(negedge clk);
            if (use_reset) rst_n = 1'b0;
            else cancel = 1'b1;
            #1;
            if (in_ready || out_valid) $fatal(1, "idle abort did not suppress ownership");
            @(posedge clk);
            @(negedge clk);
            rst_n = 1'b1;
            cancel = 1'b0;
            #1;
            if (in_ready || out_valid || !cfg_begin_ready)
                $fatal(1, "idle abort did not invalidate table ownership");
            idle_abort_cases = idle_abort_cases + 1;
        end
    endtask

    task abort_configuration;
        input integer use_reset;
        begin
            begin_configuration();
            send_configuration_word(-33'sd2147483648);
            send_configuration_word(-33'sd2147483648);
            if (!dut.loading || dut.loaded) $fatal(1, "configuration-abort precondition failed");
            @(negedge clk);
            if (use_reset) rst_n = 1'b0;
            else cancel = 1'b1;
            #1;
            if (cfg_word_ready || cfg_commit_ready || in_ready)
                $fatal(1, "configuration abort did not block interfaces");
            @(posedge clk);
            @(negedge clk);
            rst_n = 1'b1;
            cancel = 1'b0;
            #1;
            if (cfg_word_ready || cfg_commit_ready || in_ready || !cfg_begin_ready)
                $fatal(1, "configuration abort retained a partial table");
            config_abort_cases = config_abort_cases + 1;
        end
    endtask

    task test_context_swap;
        begin
            load_case(8); // every signed32 input maps to +127
            @(negedge clk);
            in_data = -32'sd2147483648;
            in_valid = 1'b1;
            out_ready = 1'b0;
            @(posedge clk);
            if (!in_ready) $fatal(1, "old-table context was not accepted");
            @(negedge clk);
            in_valid = 1'b0;
            while (!out_valid) @(negedge clk);
            if (out_data !== 8'sd127) $fatal(1, "old table context result mismatch");
            cfg_begin = 1'b1;
            #1;
            if (cfg_begin_ready) $fatal(1, "configuration began before old context drained");
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            out_ready = 1'b1;
            @(posedge clk);
            @(negedge clk);
            out_ready = 1'b0;
            if (!dut.pipe_empty || out_valid) $fatal(1, "old context did not drain");
            load_case(9); // every signed32 input maps to -127
            send_and_check_one(-32'sd2147483648, -8'sd127);
            context_swap_cases = context_swap_cases + 1;
        end
    endtask

    integer case_id;
    integer k;
    reg [8*32-1:0] filename;
    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        if (in_ready) $fatal(1, "unconfigured table accepted input");

        // A decreasing valid-range key invalidates an in-progress load.
        begin_configuration();
        send_configuration_word(-33'sd2147483648);
        send_configuration_word(-33'sd2147483647);
        send_configuration_word(-33'sd2147483648);
        #1;
        if (!cfg_error || in_ready || cfg_commit_ready) $fatal(1, "nonmonotone table was not rejected");

        // A premature commit is accepted as a control request but rejected.
        begin_configuration();
        @(negedge clk);
        cfg_commit = 1'b1;
        @(posedge clk);
        if (!cfg_commit_ready) $fatal(1, "early commit control was not observed");
        @(negedge clk);
        cfg_commit = 1'b0;
        #1;
        if (!cfg_error || in_ready) $fatal(1, "incomplete table commit was not rejected");

        for (case_id = 0; case_id < 11; case_id = case_id + 1) begin
            load_case(case_id);
            run_case(case_id);
        end

        // Cancel a full pipeline while its oldest result is held at the output.
        load_case(0);
        monitor_enable = 0;
        fill_pipeline_without_output();
        cancel = 1'b1;
        #1;
        if (out_valid || in_ready) $fatal(1, "cancel did not immediately suppress ownership");
        @(posedge clk);
        @(negedge clk);
        cancel = 1'b0;
        #1;
        if (out_valid || in_ready || !cfg_begin_ready) $fatal(1, "cancel retained a result or table");
        repeat (12) begin
            @(posedge clk);
            #1;
            if (out_valid) $fatal(1, "cancelled result leaked after cancellation");
        end

        load_case(0);
        fill_pipeline_without_output();
        rst_n = 1'b0;
        #1;
        if (out_valid || in_ready) $fatal(1, "reset did not immediately suppress ownership");
        @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        #1;
        if (out_valid || in_ready || !cfg_begin_ready) $fatal(1, "reset retained a result or table");
        repeat (12) begin
            @(posedge clk);
            #1;
            if (out_valid) $fatal(1, "reset result leaked after reset");
        end

        // Abort a single live token at every registered search stage, once by
        // cancel and once by reset. Each abort invalidates table ownership.
        for (k = 0; k < 8; k = k + 1) begin
            load_case(8);
            abort_one_stage(k, 0);
            load_case(8);
            abort_one_stage(k, 1);
        end

        load_case(8);
        abort_idle(0);
        load_case(8);
        abort_idle(1);
        abort_configuration(0);
        abort_configuration(1);
        test_context_swap();

        $display("REQUANT_PIPELINE_RAM_WRAPPER_PASS cases=11264 actual_tables=8 synthetic_tables=3 config_errors=2 premature_commit=1 cancel=1 reset=1 stage_cancel=%0d stage_reset=%0d idle_abort=%0d config_abort=%0d context_swap=%0d latency_no_stall=8 steady_accept_ii=1 steady_result_ii=1",
                 stage_cancel_cases, stage_reset_cases, idle_abort_cases, config_abort_cases, context_swap_cases);
        $finish;
    end

    initial begin
        #5000000;
        $fatal(1, "requant pipeline timeout");
    end
endmodule
