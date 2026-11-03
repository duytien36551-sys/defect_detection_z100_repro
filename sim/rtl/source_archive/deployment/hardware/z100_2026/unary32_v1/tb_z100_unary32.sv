`timescale 1ns/1ps
`default_nettype none
module tb_z100_unary32;
    localparam integer TABLES = 57;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg cancel = 1'b0;
    always #5 clk = ~clk;

    reg cfg_begin = 1'b0;
    wire cfg_begin_ready;
    reg [31:0] cfg_epoch = 32'd0;
    reg cfg_word_valid = 1'b0;
    wire cfg_word_ready;
    reg [7:0] cfg_data = 8'd0;
    reg cfg_commit = 1'b0;
    wire cfg_commit_ready;
    wire error_valid;
    wire [2:0] error_code;
    wire store_valid;
    wire [31:0] active_epoch;
    wire loading;

    reg in_valid = 1'b0;
    wire in_ready;
    reg [31:0] in_epoch = 32'd0;
    reg [31:0] in_token = 32'd0;
    reg [5:0] in_lanes = 6'd0;
    reg in_last = 1'b0;
    reg [255:0] in_data = 256'd0;

    wire out_valid;
    reg out_ready = 1'b1;
    wire [31:0] out_epoch;
    wire [31:0] out_token;
    wire [5:0] out_lanes;
    wire out_last;
    wire [255:0] out_data;

    z100_unary32 dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(cfg_begin_ready),
        .cfg_epoch(cfg_epoch), .cfg_word_valid(cfg_word_valid),
        .cfg_word_ready(cfg_word_ready), .cfg_data(cfg_data),
        .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .error_valid(error_valid), .error_code(error_code),
        .store_valid(store_valid), .active_epoch(active_epoch), .loading(loading),
        .in_valid(in_valid), .in_ready(in_ready), .in_epoch(in_epoch),
        .in_token(in_token), .in_lanes(in_lanes), .in_last(in_last),
        .in_data(in_data), .out_valid(out_valid), .out_ready(out_ready),
        .out_epoch(out_epoch), .out_token(out_token), .out_lanes(out_lanes),
        .out_last(out_last), .out_data(out_data)
    );

    reg [7:0] all_tables [0:TABLES*256-1];
    reg [255:0] seen_codes [0:TABLES*32-1];
    reg [255:0] expected_data_q [0:65535];
    reg [31:0] expected_epoch_q [0:65535];
    reg [31:0] expected_token_q [0:65535];
    reg [5:0] expected_lanes_q [0:65535];
    reg expected_last_q [0:65535];
    reg expected_exhaustive_q [0:65535];

    integer queue_head = 0;
    integer queue_tail = 0;
    integer current_table = 0;
    integer stimulus_exhaustive = 0;
    integer cycles = 0;
    integer accepted_requests = 0;
    integer refused_requests = 0;
    integer responses = 0;
    integer active_byte_comparisons = 0;
    integer exhaustive_beats = 0;
    integer exhaustive_comparisons = 0;
    integer cfg_writes = 0;
    integer overlong_words = 0;
    integer error_events = 0;
    integer error_counts [0:7];
    integer output_stall_cycles = 0;
    integer current_ii1 = 0;
    integer max_ii1 = 0;
    integer last_accept_cycle = -10;
    integer lane_i;
    integer index_i;
    integer t_i;
    reg [255:0] monitor_data;
    reg stalled_previous = 1'b0;
    reg [31:0] stalled_epoch;
    reg [31:0] stalled_token;
    reg [5:0] stalled_lanes;
    reg stalled_last;
    reg [255:0] stalled_data;

    always @(posedge clk) begin
        cycles = cycles + 1;
        if (!rst_n || cancel) begin
            if (queue_tail > queue_head)
                queue_head = queue_tail;
            queue_tail = queue_head;
            current_ii1 = 0;
            last_accept_cycle = -10;
            stalled_previous = 1'b0;
        end else begin
            if (error_valid) begin
                error_events = error_events + 1;
                error_counts[error_code] = error_counts[error_code] + 1;
            end

            if (cfg_word_valid && cfg_word_ready) begin
                if (dut.written_bytes >= 9'd256)
                    overlong_words = overlong_words + 1;
                else
                    cfg_writes = cfg_writes + 1;
            end

            if (out_valid && !out_ready) begin
                output_stall_cycles = output_stall_cycles + 1;
                if (stalled_previous &&
                    {out_epoch, out_token, out_lanes, out_last, out_data} !==
                    {stalled_epoch, stalled_token, stalled_lanes, stalled_last, stalled_data})
                    $fatal(1, "FAIL: output changed under backpressure");
                stalled_epoch = out_epoch;
                stalled_token = out_token;
                stalled_lanes = out_lanes;
                stalled_last = out_last;
                stalled_data = out_data;
                stalled_previous = 1'b1;
            end else begin
                stalled_previous = 1'b0;
            end

            if (out_valid && out_ready) begin
                if (queue_head >= queue_tail)
                    $fatal(1, "FAIL: response without an expected request");
                if ({out_epoch, out_token, out_lanes, out_last} !==
                    {expected_epoch_q[queue_head], expected_token_q[queue_head],
                     expected_lanes_q[queue_head], expected_last_q[queue_head]})
                    $fatal(1, "FAIL: metadata mismatch at response %0d", responses);
                if (out_data !== expected_data_q[queue_head])
                    $fatal(1, "FAIL: byte vector mismatch response=%0d got=%064x expected=%064x",
                           responses, out_data, expected_data_q[queue_head]);
                for (lane_i = 0; lane_i < 32; lane_i = lane_i + 1)
                    if (lane_i < expected_lanes_q[queue_head]) begin
                        active_byte_comparisons = active_byte_comparisons + 1;
                        if (expected_exhaustive_q[queue_head])
                            exhaustive_comparisons = exhaustive_comparisons + 1;
                    end
                if (expected_exhaustive_q[queue_head])
                    exhaustive_beats = exhaustive_beats + 1;
                queue_head = queue_head + 1;
                responses = responses + 1;
            end

            if (in_valid && in_ready) begin
                accepted_requests = accepted_requests + 1;
                if (in_epoch == active_epoch && in_lanes > 0 && in_lanes <= 32) begin
                    if (cycles == last_accept_cycle + 1)
                        current_ii1 = current_ii1 + 1;
                    else
                        current_ii1 = 1;
                    if (current_ii1 > max_ii1)
                        max_ii1 = current_ii1;
                    last_accept_cycle = cycles;

                    monitor_data = 256'd0;
                    for (lane_i = 0; lane_i < 32; lane_i = lane_i + 1) begin
                        if (lane_i < in_lanes) begin
                            index_i = in_data[lane_i*8 +: 8] ^ 8'h80;
                            monitor_data[lane_i*8 +: 8] = all_tables[current_table*256 + index_i];
                            if (stimulus_exhaustive)
                                seen_codes[current_table*32 + lane_i][index_i] = 1'b1;
                        end
                    end
                    expected_data_q[queue_tail] = monitor_data;
                    expected_epoch_q[queue_tail] = in_epoch;
                    expected_token_q[queue_tail] = in_token;
                    expected_lanes_q[queue_tail] = in_lanes;
                    expected_last_q[queue_tail] = in_last;
                    expected_exhaustive_q[queue_tail] = (stimulus_exhaustive != 0);
                    queue_tail = queue_tail + 1;
                end else begin
                    refused_requests = refused_requests + 1;
                    current_ii1 = 0;
                end
            end else begin
                current_ii1 = 0;
            end
        end
    end

    task automatic fail(input [8*128-1:0] message);
        begin
            $display("FAIL: %0s", message);
            $fatal(1, "%0s", message);
        end
    endtask

    task automatic wait_empty;
        integer timeout_count;
        begin
            timeout_count = 0;
            while ((queue_head != queue_tail || out_valid || dut.s0_valid || dut.s1_valid) &&
                   timeout_count < 100) begin
                @(negedge clk);
                timeout_count = timeout_count + 1;
            end
            if (queue_head != queue_tail || out_valid || dut.s0_valid || dut.s1_valid)
                fail("stream pipeline did not drain");
        end
    endtask

    task automatic make_input(
        input integer table_id,
        input integer beat,
        input integer lane_count,
        input integer offset,
        output reg [255:0] result
    );
        integer lane;
        integer value_index;
        begin
            result = 256'd0;
            for (lane = 0; lane < 32; lane = lane + 1) begin
                value_index = (beat + lane*7 + table_id*13 + offset) & 255;
                result[lane*8 +: 8] = value_index ^ 8'h80;
                if (lane >= lane_count)
                    result[lane*8 +: 8] = 8'hd3;
            end
        end
    endtask

    task automatic start_load(input [31:0] epoch_value);
        begin
            @(negedge clk);
            cfg_epoch = epoch_value;
            cfg_begin = 1'b1;
            #1;
            if (!cfg_begin_ready)
                fail("configuration begin was not ready while pipeline empty");
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            #1;
            if (!loading || store_valid || active_epoch != 0)
                fail("configuration begin did not invalidate prior store");
        end
    endtask

    task automatic write_table(input integer table_id);
        integer byte_index;
        begin
            for (byte_index = 0; byte_index < 256; byte_index = byte_index + 1) begin
                @(negedge clk);
                cfg_data = all_tables[table_id*256 + byte_index];
                cfg_word_valid = 1'b1;
                #1;
                if (!cfg_word_ready)
                    fail("configuration word was not ready during load");
                @(posedge clk);
            end
            @(negedge clk);
            cfg_word_valid = 1'b0;
            cfg_commit = 1'b1;
            #1;
            if (!cfg_commit_ready)
                fail("commit was not ready after 256 words");
            @(posedge clk);
            @(negedge clk);
            cfg_commit = 1'b0;
            #1;
            if (loading || !store_valid || active_epoch != cfg_epoch)
                fail("exact 256-byte commit did not activate the requested epoch");
        end
    endtask

    task automatic load_table(input integer table_id, input [31:0] epoch_value);
        begin
            start_load(epoch_value);
            write_table(table_id);
        end
    endtask

    task automatic set_beat(
        input integer table_id,
        input integer beat,
        input integer lane_count,
        input integer offset,
        input [31:0] token_value,
        input bit last_value,
        input bit exhaustive_value
    );
        reg [255:0] generated_data;
        begin
            make_input(table_id, beat, lane_count, offset, generated_data);
            in_epoch = active_epoch;
            in_token = token_value;
            in_lanes = lane_count;
            in_last = last_value;
            in_data = generated_data;
            stimulus_exhaustive = exhaustive_value;
        end
    endtask

    task automatic send_single(
        input integer table_id,
        input integer beat,
        input integer lane_count,
        input integer offset,
        input [31:0] token_value,
        input bit last_value
    );
        begin
            current_table = table_id;
            @(negedge clk);
            set_beat(table_id, beat, lane_count, offset, token_value, last_value, 1'b0);
            in_valid = 1'b1;
            #1;
            if (!in_ready)
                fail("valid input request was not ready");
            @(posedge clk);
            @(negedge clk);
            in_valid = 1'b0;
            stimulus_exhaustive = 0;
        end
    endtask

    task automatic send_invalid(input [31:0] epoch_value, input [5:0] lanes_value);
        begin
            wait_empty();
            @(negedge clk);
            in_epoch = epoch_value;
            in_token = 32'hdeadcafe;
            in_lanes = lanes_value;
            in_last = 1'b1;
            in_data = {32{8'h91}};
            in_valid = 1'b1;
            #1;
            if (!in_ready)
                fail("invalid request was not accepted for explicit refusal");
            @(posedge clk);
            @(negedge clk);
            in_valid = 1'b0;
            #1;
            if (!error_valid || error_code != 3'd4)
                fail("stale epoch or invalid lane request was not refused");
            wait_empty();
        end
    endtask

    task automatic exhaustive_table(input integer table_id);
        integer beat;
        integer lane;
        begin
            current_table = table_id;
            for (beat = 0; beat < 256; beat = beat + 1) begin
                @(negedge clk);
                set_beat(table_id, beat, 32, 0, 32'h80000000 + table_id*512 + beat,
                         (beat == 255), 1'b1);
                in_valid = 1'b1;
                #1;
                if (!in_ready)
                    fail("continuous 32-lane test unexpectedly stalled");
                @(posedge clk);
            end
            @(negedge clk);
            in_valid = 1'b0;
            stimulus_exhaustive = 0;
            wait_empty();
            for (lane = 0; lane < 32; lane = lane + 1)
                if (seen_codes[table_id*32 + lane] !== {256{1'b1}})
                    fail("exhaustive source pattern missed a table index on one lane");
        end
    endtask

    task automatic test_bad_begin;
        begin
            @(negedge clk);
            cfg_epoch = 0;
            cfg_begin = 1'b1;
            #1;
            if (!cfg_begin_ready)
                fail("invalid begin test could not start from idle");
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            #1;
            if (!error_valid || error_code != 3'd1 || store_valid || loading)
                fail("zero-epoch configuration begin was not rejected");
        end
    endtask

    task automatic test_early_commit;
        integer i;
        begin
            start_load(32'h0000e101);
            for (i = 0; i < 7; i = i + 1) begin
                @(negedge clk);
                cfg_word_valid = 1'b1;
                cfg_data = i[7:0];
                @(posedge clk);
            end
            @(negedge clk);
            cfg_word_valid = 1'b0;
            cfg_commit = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cfg_commit = 1'b0;
            #1;
            if (!error_valid || error_code != 3'd2 || store_valid || loading)
                fail("early configuration commit was not rejected");
        end
    endtask

    task automatic test_overlong_config;
        integer i;
        begin
            start_load(32'h0000e102);
            for (i = 0; i < 256; i = i + 1) begin
                @(negedge clk);
                cfg_word_valid = 1'b1;
                cfg_data = i[7:0];
                @(posedge clk);
            end
            @(negedge clk);
            cfg_word_valid = 1'b1;
            cfg_data = 8'hfe;
            @(posedge clk);
            @(negedge clk);
            cfg_word_valid = 1'b0;
            #1;
            if (!error_valid || error_code != 3'd3 || store_valid || loading)
                fail("257th configuration byte was not rejected fail-closed");
        end
    endtask

    task automatic test_partial_lanes;
        integer counts [0:4];
        integer i;
        begin
            counts[0] = 1;
            counts[1] = 15;
            counts[2] = 16;
            counts[3] = 17;
            counts[4] = 31;
            current_table = 0;
            for (i = 0; i < 5; i = i + 1) begin
                send_single(0, i*19, counts[i], 93, 32'habc00000 + i, (i[0] != 0));
                wait_empty();
            end
            // Explicit input bubbles between active requests.
            repeat (4) @(negedge clk);
            if (in_valid)
                fail("input bubble test left valid asserted");
        end
    endtask

    task automatic test_stall_and_reload_refusal;
        begin
            wait_empty();
            out_ready = 1'b0;
            send_single(0, 77, 32, 41, 32'hbacc0001, 1'b1);
            repeat (4) @(negedge clk);
            if (!out_valid)
                fail("expected response did not reach stalled output");
            cfg_epoch = 32'h99990001;
            cfg_begin = 1'b1;
            #1;
            if (cfg_begin_ready)
                fail("reload was allowed while an output was in flight");
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            if (!store_valid)
                fail("rejected reload invalidated active table");
            repeat (5) @(negedge clk);
            out_ready = 1'b1;
            wait_empty();
        end
    endtask

    task automatic test_loading_input_disabled;
        begin
            start_load(32'h0000e200);
            @(negedge clk);
            in_valid = 1'b1;
            in_epoch = 32'h0000e200;
            in_lanes = 6'd32;
            in_data = {32{8'h80}};
            #1;
            if (in_ready)
                fail("input remained enabled during table load");
            @(posedge clk);
            @(negedge clk);
            in_valid = 1'b0;
            for (t_i = 0; t_i < 256; t_i = t_i + 1) begin
                cfg_word_valid = 1'b1;
                cfg_data = all_tables[t_i];
                @(posedge clk);
                @(negedge clk);
            end
            cfg_word_valid = 1'b0;
            cfg_commit = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cfg_commit = 1'b0;
            #1;
            if (!store_valid || loading || active_epoch != 32'h0000e200)
                fail("recovery after disabled-load input did not commit");
        end
    endtask

    task automatic test_reset_pending;
        begin
            out_ready = 1'b0;
            send_single(0, 117, 32, 3, 32'h0bad0001, 1'b0);
            repeat (4) @(negedge clk);
            if (!out_valid)
                fail("reset-pending setup did not reach output");
            rst_n = 1'b0;
            @(posedge clk);
            @(negedge clk);
            if (out_valid || store_valid || loading)
                fail("reset did not invalidate pending data and table epoch");
            rst_n = 1'b1;
            out_ready = 1'b1;
            load_table(0, 32'h0000e201);
            send_single(0, 51, 32, 19, 32'h0bad0002, 1'b1);
            wait_empty();
        end
    endtask

    task automatic test_cancel_pending;
        begin
            out_ready = 1'b0;
            send_single(0, 42, 32, 99, 32'h0bad1001, 1'b0);
            repeat (4) @(negedge clk);
            if (!out_valid)
                fail("cancel-pending setup did not reach output");
            cancel = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cancel = 1'b0;
            if (out_valid || store_valid || loading)
                fail("cancel did not invalidate pending data and table epoch");
            out_ready = 1'b1;
            load_table(0, 32'h0000e202);
            send_single(0, 211, 32, 7, 32'h0bad1002, 1'b1);
            wait_empty();
        end
    endtask

    initial begin
        $readmemh("unary32_tables.hex", all_tables);
        for (t_i = 0; t_i < TABLES*32; t_i = t_i + 1)
            seen_codes[t_i] = 256'd0;
        for (t_i = 0; t_i < 8; t_i = t_i + 1)
            error_counts[t_i] = 0;

        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        test_bad_begin();
        test_early_commit();
        test_overlong_config();

        load_table(0, 32'h0000e000);
        current_table = 0;
        send_invalid(32'h0000e001, 32'd32);
        send_invalid(active_epoch, 6'd0);
        send_invalid(active_epoch, 6'd33);

        test_loading_input_disabled();
        // Loading-input test uses the same exact first table.
        test_partial_lanes();
        test_stall_and_reload_refusal();
        wait_empty();

        for (t_i = 0; t_i < TABLES; t_i = t_i + 1) begin
            load_table(t_i, 32'h00010000 + t_i);
            exhaustive_table(t_i);
        end

        load_table(0, 32'h0000e300);
        test_reset_pending();
        test_cancel_pending();
        wait_empty();

        if (exhaustive_beats != TABLES*256 || exhaustive_comparisons != TABLES*256*32)
            fail("all-table exhaustive comparison total mismatch");
        if (max_ii1 < 256)
            fail("continuous input throughput did not sustain a 256-beat II=1 burst");
        if (output_stall_cycles < 10)
            fail("output backpressure stability was not exercised enough");
        if (cfg_writes < TABLES*256 || overlong_words != 1)
            fail("configuration write or overlong-attempt coverage mismatch");
        if (refused_requests != 3 || error_events < 6 ||
            error_counts[1] != 1 || error_counts[2] != 1 || error_counts[3] != 1 || error_counts[4] != 3)
            fail("configuration/input rejection coverage mismatch");
        $display("UNARY32_PASS tables=%0d exhaustive_beats=%0d exhaustive_values=%0d responses=%0d active_byte_comparisons=%0d max_ii1=%0d stalls=%0d cfg_writes=%0d overlong=%0d refused=%0d errors=%0d partial=1,15,16,17,31 reset=1 cancel=1 reload_busy=1 load_input_disabled=1", TABLES, exhaustive_beats, exhaustive_comparisons, responses, active_byte_comparisons, max_ii1, output_stall_cycles, cfg_writes, overlong_words, refused_requests, error_events);
        $finish;
    end
endmodule
`default_nettype wire
