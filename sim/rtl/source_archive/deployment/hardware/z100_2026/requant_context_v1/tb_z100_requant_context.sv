module tb_z100_requant_context;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n = 1'b0;
    reg cancel = 1'b0;
    reg cfg_begin = 1'b0;
    reg [2:0] cfg_context = 3'b0;
    wire cfg_begin_ready;
    reg cfg_word_valid = 1'b0;
    wire cfg_word_ready;
    reg signed [32:0] cfg_key = 33'sd0;
    reg cfg_commit = 1'b0;
    wire cfg_commit_ready;
    wire cfg_error;
    reg in_valid = 1'b0;
    wire in_ready;
    reg [2:0] in_context = 3'b0;
    reg signed [31:0] in_data = 32'sd0;
    wire out_valid;
    reg out_ready = 1'b0;
    wire [2:0] out_context;
    wire signed [7:0] out_data;

    z100_requant_context dut (.*);

    reg [32:0] tree [0:254];
    reg [42:0] vectors [0:8191];
    integer accept_cycle [0:8191];
    integer active_count = 0;
    integer accepted_count = 0;
    integer returned_count = 0;
    integer cycle_count = 0;
    integer previous_accept_cycle = -1;
    integer previous_result_cycle = -1;
    integer blocked_output_cycles = 0;
    integer monitor_enable = 0;
    integer first_latency = -1;
    integer min_latency = 1000000;
    integer max_latency = 0;
    reg previous_stalled = 1'b0;
    reg [7:0] held_context = 8'b0;
    reg signed [7:0] held_output = 8'sd0;
    reg [31:0] lfsr;

    always @(posedge clk) begin
        if (rst_n && monitor_enable) begin
            integer this_latency;
            cycle_count = cycle_count + 1;
            if (previous_stalled && (!out_valid || out_context !== held_context[2:0] ||
                                     out_data !== held_output))
                $fatal(1, "stalled context or output changed");
            previous_stalled = out_valid && !out_ready;
            if (previous_stalled) begin
                held_context = {5'b0, out_context};
                held_output = out_data;
                blocked_output_cycles = blocked_output_cycles + 1;
            end
            if (in_valid && in_ready) begin
                if (accepted_count >= active_count) $fatal(1, "too many inputs accepted");
                accept_cycle[accepted_count] = cycle_count;
                if (accepted_count > 0 && accepted_count < 256 &&
                    cycle_count - previous_accept_cycle != 1)
                    $fatal(1, "initial input stream was not II=1");
                previous_accept_cycle = cycle_count;
                accepted_count = accepted_count + 1;
            end
            if (out_valid && out_ready) begin
                if (returned_count >= accepted_count)
                    $fatal(1, "result without an accepted input");
                if (out_context !== vectors[returned_count][42:40])
                    $fatal(1, "context mismatch index=%0d got=%0d expected=%0d",
                           returned_count, out_context, vectors[returned_count][42:40]);
                if (out_data !== $signed(vectors[returned_count][7:0]))
                    $fatal(1, "result mismatch index=%0d raw=%0d ctx=%0d got=%0d expected=%0d",
                           returned_count, $signed(vectors[returned_count][39:8]),
                           vectors[returned_count][42:40], $signed(out_data),
                           $signed(vectors[returned_count][7:0]));
                this_latency = cycle_count - accept_cycle[returned_count];
                if (first_latency < 0) first_latency = this_latency;
                if (this_latency < min_latency) min_latency = this_latency;
                if (this_latency > max_latency) max_latency = this_latency;
                if (returned_count < 64 && this_latency != 8)
                    $fatal(1, "no-stall latency was %0d rather than 8", this_latency);
                if (returned_count > 0 && returned_count < 128 &&
                    cycle_count - previous_result_cycle != 1)
                    $fatal(1, "initial result stream was not II=1");
                previous_result_cycle = cycle_count;
                returned_count = returned_count + 1;
            end
        end
    end

    task begin_configuration;
        input [2:0] which_context;
        begin
            @(negedge clk);
            cfg_context = which_context;
            cfg_begin = 1'b1;
            @(posedge clk);
            if (!cfg_begin_ready) $fatal(1, "configuration begin was not ready");
            #1;
            if (in_ready) $fatal(1, "input remained enabled during configuration");
            @(negedge clk);
            cfg_begin = 1'b0;
        end
    endtask

    task send_word;
        input signed [32:0] value;
        input integer expect_error;
        begin
            @(negedge clk);
            cfg_word_valid = 1'b1;
            cfg_key = value;
            @(posedge clk);
            if (!cfg_word_ready) $fatal(1, "configuration word was not ready");
            #1;
            if (expect_error && !cfg_error) $fatal(1, "invalid key was not reported");
            if (!expect_error && cfg_error) $fatal(1, "valid key unexpectedly failed");
            @(negedge clk);
            cfg_word_valid = 1'b0;
        end
    endtask

    task commit_configuration;
        input integer expect_error;
        begin
            @(negedge clk);
            cfg_commit = 1'b1;
            @(posedge clk);
            if (!cfg_commit_ready) $fatal(1, "configuration commit was not ready");
            #1;
            if (expect_error && !cfg_error) $fatal(1, "invalid commit was not reported");
            if (!expect_error && cfg_error) $fatal(1, "valid commit unexpectedly failed");
            @(negedge clk);
            cfg_commit = 1'b0;
        end
    endtask

    task load_context;
        input [2:0] which_context;
        input integer tree_id;
        reg [8*32-1:0] filename;
        integer k;
        begin
            $sformat(filename, "tree_%02d.hex", tree_id);
            $readmemh(filename, tree);
            begin_configuration(which_context);
            for (k = 0; k < 255; k = k + 1)
                send_word($signed(tree[k]), 0);
            commit_configuration(0);
            #1;
            in_context = which_context;
            in_valid = 1'b0;
            #1;
            if (!in_ready) $fatal(1, "committed context did not become valid");
        end
    endtask

    task check_context_ready;
        input [2:0] which_context;
        input integer expected_ready;
        begin
            in_valid = 1'b0;
            in_context = which_context;
            #1;
            if (in_ready !== expected_ready[0])
                $fatal(1, "context %0d eligibility got=%0d expected=%0d",
                       which_context, in_ready, expected_ready);
        end
    endtask

    task run_stream;
        input integer count;
        input integer stream_id;
        reg [8*32-1:0] filename;
        integer index;
        integer watchdog;
        begin
            case (stream_id)
                0: filename = "stream_actual.hex";
                1: filename = "stream_synthetic.hex";
                2: filename = "stream_preserved.hex";
                default: $fatal(1, "invalid stream id");
            endcase
            $readmemh(filename, vectors);
            @(negedge clk);
            active_count = count;
            accepted_count = 0;
            returned_count = 0;
            cycle_count = 0;
            previous_accept_cycle = -1;
            previous_result_cycle = -1;
            blocked_output_cycles = 0;
            first_latency = -1;
            min_latency = 1000000;
            max_latency = 0;
            previous_stalled = 1'b0;
            monitor_enable = 1;
            lfsr = 32'h9e3779b9 ^ stream_id;
            in_context = vectors[0][42:40];
            in_data = $signed(vectors[0][39:8]);
            in_valid = 1'b1;
            out_ready = 1'b1;
            index = 0;
            watchdog = 0;
            while (index < count && watchdog < count * 5 + 10000) begin
                @(posedge clk);
                watchdog = watchdog + 1;
                if (in_valid && in_ready) index = index + 1;
                @(negedge clk);
                if (index < count) begin
                    in_context = vectors[index][42:40];
                    in_data = $signed(vectors[index][39:8]);
                    in_valid = 1'b1;
                end else begin
                    in_valid = 1'b0;
                end
                if (index < 256) begin
                    out_ready = 1'b1;
                end else begin
                    lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
                    out_ready = (lfsr[2:0] != 3'b000);
                end
            end
            if (index != count) $fatal(1, "input stream timed out");
            watchdog = 0;
            while (returned_count < count && watchdog < count * 5 + 10000) begin
                lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
                out_ready = (lfsr[2:0] != 3'b000);
                @(posedge clk);
                watchdog = watchdog + 1;
                @(negedge clk);
            end
            if (accepted_count != count || returned_count != count)
                $fatal(1, "stream coverage accepted=%0d returned=%0d expected=%0d",
                       accepted_count, returned_count, count);
            if (blocked_output_cycles == 0) $fatal(1, "random output backpressure was not exercised");
            if (first_latency != 8 || min_latency < 8)
                $fatal(1, "unexpected stream latency first=%0d min=%0d", first_latency, min_latency);
            if (!previous_result_cycle) $fatal(1, "result interval coverage missing");
            monitor_enable = 0;
            in_valid = 1'b0;
            out_ready = 1'b0;
            repeat (2) begin
                @(posedge clk);
                #1;
                if (out_valid) $fatal(1, "unexpected result after stream drain");
            end
            $display("CONTEXT_STREAM id=%0d vectors=%0d latency_no_stall=%0d latency_min=%0d latency_max=%0d input_ii=1 result_ii=1 blocked_cycles=%0d",
                     stream_id, returned_count, first_latency, min_latency, max_latency, blocked_output_cycles);
        end
    endtask

    task failed_sentinel_configuration;
        integer k;
        begin
            $readmemh("tree_08.hex", tree);
            begin_configuration(3'd5);
            for (k = 0; k < 254; k = k + 1)
                send_word($signed(tree[k]), 0);
            send_word(33'sd2147483647, 1);
            check_context_ready(3'd5, 0);
            check_context_ready(3'd1, 1);
        end
    endtask

    task early_commit_configuration;
        integer k;
        begin
            $readmemh("tree_00.hex", tree);
            begin_configuration(3'd6);
            for (k = 0; k < 12; k = k + 1)
                send_word($signed(tree[k]), 0);
            commit_configuration(1);
            check_context_ready(3'd6, 0);
            check_context_ready(3'd1, 1);
        end
    endtask

    task decreasing_configuration;
        begin
            begin_configuration(3'd4);
            send_word(-33'sd2147483648, 0);
            send_word(-33'sd2147483647, 0);
            send_word(-33'sd2147483648, 1);
            check_context_ready(3'd4, 0);
            check_context_ready(3'd1, 1);
        end
    endtask

    task excessive_configuration;
        integer k;
        begin
            $readmemh("tree_00.hex", tree);
            begin_configuration(3'd7);
            for (k = 0; k < 255; k = k + 1)
                send_word($signed(tree[k]), 0);
            send_word(33'sd2147483648, 1);
            check_context_ready(3'd7, 0);
            check_context_ready(3'd1, 1);
        end
    endtask

    task test_configuration_requires_empty_pipeline;
        begin
            @(negedge clk);
            in_context = 3'd0;
            in_data = -32'sd500;
            in_valid = 1'b1;
            out_ready = 1'b0;
            @(posedge clk);
            if (!in_ready) $fatal(1, "valid context did not accept guard input");
            @(negedge clk);
            in_valid = 1'b0;
            #1;
            if (cfg_begin_ready) $fatal(1, "configuration began with an in-flight token");
            if (cfg_word_ready || cfg_commit_ready)
                $fatal(1, "configuration data/commit ready while the pipeline was nonempty");
            out_ready = 1'b1;
            repeat (10) @(posedge clk);
            @(negedge clk);
            out_ready = 1'b0;
            if (!cfg_begin_ready) $fatal(1, "pipeline did not drain before configuration");
        end
    endtask

    task exercise_flush;
        input integer target_stage;
        input integer reset_mode;
        integer guard;
        begin
            load_context(3'd0, 0);
            load_context(3'd1, 1);
            @(negedge clk);
            in_context = 3'd0;
            in_data = -32'sd1234567;
            in_valid = 1'b1;
            out_ready = 1'b0;
            @(posedge clk);
            if (!in_ready) $fatal(1, "flush token was not accepted");
            @(negedge clk);
            in_valid = 1'b0;
            if (target_stage > 0) begin
                repeat (target_stage) @(posedge clk);
                @(negedge clk);
            end
            if (dut.valid_q !== (8'b1 << target_stage))
                $fatal(1,"flush must target exact stage %0d, observed=%b",target_stage,dut.valid_q);
            if (reset_mode) rst_n = 1'b0;
            else cancel = 1'b1;
            #1;
            if (out_valid || in_ready) $fatal(1, "flush did not immediately suppress outputs");
            @(posedge clk);
            @(negedge clk);
            cancel = 1'b0;
            rst_n = 1'b1;
            #1;
            check_context_ready(3'd0, 0);
            check_context_ready(3'd1, 0);
            if (!cfg_begin_ready) $fatal(1, "flush left the pipeline or configuration busy");
            guard = 0;
            while (guard < 10) begin
                @(posedge clk);
                #1;
                if (out_valid) $fatal(1, "flushed result leaked from stage %0d", target_stage);
                guard = guard + 1;
            end
            $display("CONTEXT_FLUSH_PASS stage=%0d reset=%0d",target_stage,reset_mode);
        end
    endtask

    task run_recovery_probe;
        integer watchdog;
        begin
            $readmemh("stream_actual.hex", vectors);
            @(negedge clk);
            in_context = vectors[0][42:40];
            in_data = $signed(vectors[0][39:8]);
            in_valid = 1'b1;
            out_ready = 1'b1;
            @(posedge clk);
            if (!in_ready) $fatal(1, "recovery probe was not accepted");
            @(negedge clk);
            in_valid = 1'b0;
            watchdog = 0;
            while (!out_valid && watchdog < 16) begin
                @(negedge clk);
                watchdog = watchdog + 1;
            end
            if (!out_valid) $fatal(1, "reconfigured context produced no recovery output");
            if (out_context !== vectors[0][42:40] ||
                out_data !== $signed(vectors[0][7:0]))
                $fatal(1, "reconfigured context recovery result mismatch");
            @(posedge clk);
            @(negedge clk);
            out_ready = 1'b0;
            repeat (2) begin
                @(posedge clk);
                #1;
                if (out_valid) $fatal(1, "recovery result repeated after its handshake");
            end
        end
    endtask

    task exercise_partial_configuration_flush;
        input integer reset_mode;
        integer k;
        begin
            load_context(3'd0, 0);
            load_context(3'd1, 1);
            $readmemh("tree_00.hex", tree);
            begin_configuration(3'd2);
            for (k = 0; k < 16; k = k + 1)
                send_word($signed(tree[k]), 0);
            @(negedge clk);
            if (reset_mode) rst_n = 1'b0;
            else cancel = 1'b1;
            #1;
            if (in_ready || out_valid) $fatal(1, "partial-load flush did not suppress ownership");
            @(posedge clk);
            #1;
            if (dut.loading || dut.valid_q !== 8'b0 || dut.context_valid !== 8'b0)
                $fatal(1, "partial-load flush retained configuration or context validity");
            @(negedge clk);
            cancel = 1'b0;
            rst_n = 1'b1;
            #1;
            if (!cfg_begin_ready) $fatal(1, "partial-load flush left configuration busy");
            repeat (10) begin
                @(posedge clk);
                #1;
                if (out_valid) $fatal(1, "partial-load flush leaked an old output");
            end
            check_context_ready(3'd0, 0);
            check_context_ready(3'd1, 0);
            check_context_ready(3'd2, 0);
            load_context(3'd0, 0);
            run_recovery_probe();
            $display("CONTEXT_CONFIG_FLUSH_PASS reset=%0d", reset_mode);
        end
    endtask

    task exercise_full_pipeline_flush;
        input integer reset_mode;
        integer k;
        begin
            for (k = 0; k < 8; k = k + 1)
                load_context(k[2:0], k);
            out_ready = 1'b0;
            for (k = 0; k < 8; k = k + 1) begin
                @(negedge clk);
                in_context = k[2:0];
                in_data = -32'sd1000000 + k;
                in_valid = 1'b1;
                @(posedge clk);
                if (!in_ready) $fatal(1, "full-pipeline token %0d was not accepted", k);
            end
            @(negedge clk);
            in_valid = 1'b0;
            #1;
            if (dut.valid_q !== 8'hff || !out_valid || out_ready)
                $fatal(1, "backpressured pipeline was not full before flush: valid=%b", dut.valid_q);
            if (reset_mode) rst_n = 1'b0;
            else cancel = 1'b1;
            #1;
            if (out_valid || in_ready) $fatal(1, "full-pipeline flush did not suppress ownership");
            @(posedge clk);
            #1;
            if (dut.valid_q !== 8'b0 || dut.context_valid !== 8'b0)
                $fatal(1, "full-pipeline flush retained valid stages or contexts");
            @(negedge clk);
            cancel = 1'b0;
            rst_n = 1'b1;
            #1;
            if (!cfg_begin_ready) $fatal(1, "full-pipeline flush left configuration busy");
            for (k = 0; k < 8; k = k + 1)
                check_context_ready(k[2:0], 0);
            repeat (10) begin
                @(posedge clk);
                #1;
                if (out_valid) $fatal(1, "full-pipeline flush leaked an old output");
            end
            load_context(3'd0, 0);
            run_recovery_probe();
            $display("CONTEXT_FULL_FLUSH_PASS reset=%0d", reset_mode);
        end
    endtask

    integer context_id;
    integer flush_stage;
    integer flush_mode;
    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        check_context_ready(3'd0, 0);
        for (context_id = 0; context_id < 8; context_id = context_id + 1)
            load_context(context_id[2:0], context_id);

        test_configuration_requires_empty_pipeline();
        failed_sentinel_configuration();
        load_context(3'd5, 5);
        early_commit_configuration();
        load_context(3'd6, 6);
        decreasing_configuration();
        load_context(3'd4, 4);
        excessive_configuration();
        load_context(3'd7, 7);

        run_stream(8192, 0);
        for (context_id = 0; context_id < 3; context_id = context_id + 1)
            load_context(context_id[2:0], context_id + 8);
        run_stream(1280, 2);
        run_stream(3072, 1);

        for (flush_mode = 0; flush_mode < 2; flush_mode = flush_mode + 1) begin
            exercise_partial_configuration_flush(flush_mode);
            exercise_full_pipeline_flush(flush_mode);
        end

        for (flush_mode = 0; flush_mode < 2; flush_mode = flush_mode + 1)
            for (flush_stage = 0; flush_stage < 8; flush_stage = flush_stage + 1)
                exercise_flush(flush_stage, flush_mode);

        $display("REQUANT_CONTEXT_PASS actual_results=8192 synthetic_results=3072 preserved_context_results=1280 contexts=8 mapped_indices=255 sentinel_index=254 config_errors=4 excessive_write=1 early_commit=1 invalid_sentinel=1 decreasing_key=1 cancel_stages=8 reset_stages=8 config_flush_cancel=1 config_flush_reset=1 full_flush_cancel=1 full_flush_reset=1 latency_no_stall=8 steady_accept_ii=1 steady_result_ii=1");
        $finish;
    end

    initial begin
        #12000000;
        $fatal(1, "requant context testbench timeout");
    end
endmodule
