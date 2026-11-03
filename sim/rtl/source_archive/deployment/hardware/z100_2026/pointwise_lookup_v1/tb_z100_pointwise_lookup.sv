`timescale 1ns/1ps
`default_nettype none
module tb_z100_pointwise_lookup;
    localparam [1:0] MODE_UNARY = 2'b00;
    localparam [1:0] MODE_ADD = 2'b01;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg cancel = 1'b0;
    always #5 clk = ~clk;

    reg cfg_begin = 1'b0;
    wire cfg_begin_ready;
    reg [31:0] cfg_epoch = 32'd0;
    reg [1:0] cfg_mode = 2'b00;
    reg cfg_word_valid = 1'b0;
    wire cfg_word_ready;
    reg [7:0] cfg_data = 8'd0;
    reg cfg_commit = 1'b0;
    wire cfg_commit_ready;
    wire error_valid;
    wire [2:0] error_code;
    wire store_valid;
    wire [31:0] active_epoch;
    wire [1:0] active_mode;
    wire loading;

    reg in_valid = 1'b0;
    wire in_ready;
    reg [31:0] in_epoch = 32'd0;
    reg [31:0] in_token = 32'd0;
    reg [1:0] in_mode = 2'b00;
    reg [4:0] in_lanes = 5'd0;
    reg in_last = 1'b0;
    reg [127:0] in_a = 128'd0;
    reg [127:0] in_b = 128'd0;

    wire out_valid;
    reg out_ready = 1'b1;
    wire [31:0] out_epoch;
    wire [31:0] out_token;
    wire [4:0] out_lanes;
    wire out_last;
    wire [127:0] out_data;

    z100_pointwise_lookup dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(cfg_begin_ready),
        .cfg_epoch(cfg_epoch), .cfg_mode(cfg_mode),
        .cfg_word_valid(cfg_word_valid), .cfg_word_ready(cfg_word_ready),
        .cfg_data(cfg_data), .cfg_commit(cfg_commit),
        .cfg_commit_ready(cfg_commit_ready), .error_valid(error_valid),
        .error_code(error_code), .store_valid(store_valid),
        .active_epoch(active_epoch), .active_mode(active_mode), .loading(loading),
        .in_valid(in_valid), .in_ready(in_ready), .in_epoch(in_epoch),
        .in_token(in_token), .in_mode(in_mode), .in_lanes(in_lanes),
        .in_last(in_last), .in_a(in_a), .in_b(in_b), .out_valid(out_valid),
        .out_ready(out_ready), .out_epoch(out_epoch), .out_token(out_token),
        .out_lanes(out_lanes), .out_last(out_last), .out_data(out_data)
    );

    reg [7:0] expected_table [0:65535];
    reg [127:0] expected_q [0:65535];
    reg [31:0] expected_epoch_q [0:65535];
    reg [31:0] expected_token_q [0:65535];
    reg [4:0] expected_lanes_q [0:65535];
    reg expected_last_q [0:65535];

    integer queue_head = 0;
    integer queue_tail = 0;
    integer cycle_count = 0;
    integer accepted_beats = 0;
    integer responses = 0;
    integer lookup_comparisons = 0;
    integer cfg_writes = 0;
    integer cfg_overlong = 0;
    integer input_refusals = 0;
    integer errors_seen = 0;
    integer last_error_code = 0;
    integer stall_cycles = 0;
    integer current_ii1 = 0;
    integer max_ii1 = 0;
    integer last_accept_cycle = -10;
    integer monitor_lane;
    integer monitor_index;
    integer monitor_valid;
    reg [127:0] monitor_expected_data;
    reg stalled_last_cycle = 1'b0;
    reg [31:0] stalled_epoch;
    reg [31:0] stalled_token;
    reg [4:0] stalled_lanes;
    reg stalled_last;
    reg [127:0] stalled_data;

    always @(posedge clk) begin
        cycle_count = cycle_count + 1;
        if (!rst_n || cancel) begin
            queue_head = 0;
            queue_tail = 0;
            current_ii1 = 0;
            last_accept_cycle = -10;
            stalled_last_cycle = 1'b0;
        end else begin
            if (error_valid) begin
                errors_seen = errors_seen + 1;
                last_error_code = error_code;
            end
            if (cfg_word_valid && cfg_word_ready) begin
                if (dut.written_bytes >= dut.expected_bytes)
                    cfg_overlong = cfg_overlong + 1;
                else
                    cfg_writes = cfg_writes + 1;
            end
            if (out_valid && out_ready) begin
                if (queue_head >= queue_tail)
                    $fatal(1, "FAIL: output without expected request");
                if ({out_epoch, out_token, out_lanes, out_last} !==
                    {expected_epoch_q[queue_head], expected_token_q[queue_head],
                     expected_lanes_q[queue_head], expected_last_q[queue_head]})
                    $fatal(1, "FAIL: metadata mismatch at response %0d", responses);
                if (out_data !== expected_q[queue_head])
                    $fatal(1, "FAIL: data mismatch at response %0d got=%032x expected=%032x",
                           responses, out_data, expected_q[queue_head]);
                for (monitor_lane = 0; monitor_lane < 16; monitor_lane = monitor_lane + 1)
                    if (monitor_lane < expected_lanes_q[queue_head])
                        lookup_comparisons = lookup_comparisons + 1;
                queue_head = queue_head + 1;
                responses = responses + 1;
            end
            if (out_valid && !out_ready) begin
                stall_cycles = stall_cycles + 1;
                if (stalled_last_cycle &&
                    {out_epoch, out_token, out_lanes, out_last, out_data} !==
                    {stalled_epoch, stalled_token, stalled_lanes, stalled_last, stalled_data})
                    $fatal(1, "FAIL: output changed under backpressure");
                stalled_epoch = out_epoch;
                stalled_token = out_token;
                stalled_lanes = out_lanes;
                stalled_last = out_last;
                stalled_data = out_data;
                stalled_last_cycle = 1'b1;
            end else begin
                stalled_last_cycle = 1'b0;
            end
            if (in_valid && in_ready) begin
                accepted_beats = accepted_beats + 1;
                if (cycle_count == last_accept_cycle + 1)
                    current_ii1 = current_ii1 + 1;
                else
                    current_ii1 = 1;
                if (current_ii1 > max_ii1)
                    max_ii1 = current_ii1;
                last_accept_cycle = cycle_count;
                monitor_valid = (in_epoch == active_epoch) && (in_mode == active_mode) &&
                                (in_mode == MODE_UNARY || in_mode == MODE_ADD) &&
                                (in_lanes > 0) && (in_lanes <= 16);
                if (monitor_valid) begin
                    monitor_expected_data = 128'd0;
                    for (monitor_lane = 0; monitor_lane < 16; monitor_lane = monitor_lane + 1) begin
                        if (monitor_lane < in_lanes) begin
                            if (in_mode == MODE_UNARY)
                                monitor_index = in_a[monitor_lane*8 +: 8] ^ 8'h80;
                            else
                                monitor_index = ((in_a[monitor_lane*8 +: 8] ^ 8'h80) << 8) |
                                                (in_b[monitor_lane*8 +: 8] ^ 8'h80);
                            monitor_expected_data[monitor_lane*8 +: 8] = expected_table[monitor_index];
                        end
                    end
                    expected_q[queue_tail] = monitor_expected_data;
                    expected_epoch_q[queue_tail] = in_epoch;
                    expected_token_q[queue_tail] = in_token;
                    expected_lanes_q[queue_tail] = in_lanes;
                    expected_last_q[queue_tail] = in_last;
                    queue_tail = queue_tail + 1;
                end else begin
                    input_refusals = input_refusals + 1;
                end
            end else begin
                current_ii1 = 0;
            end
        end
    end

    task automatic fail(input string message);
        begin
            $display("FAIL: %s", message);
            $fatal(1, "%s", message);
        end
    endtask

    task automatic wait_empty;
        integer timeout_cycles;
        begin
            timeout_cycles = 0;
            while ((queue_head != queue_tail || out_valid || dut.rd_valid) &&
                   timeout_cycles < 100) begin
                @(negedge clk);
                timeout_cycles = timeout_cycles + 1;
            end
            if (queue_head != queue_tail || out_valid || dut.rd_valid)
                fail("pipeline did not drain");
        end
    endtask

    task automatic begin_bad_config(input [1:0] mode, input [31:0] epoch);
        begin
            @(negedge clk);
            cfg_mode = mode;
            cfg_epoch = epoch;
            cfg_begin = 1'b1;
            if (!cfg_begin_ready) fail("bad config could not be presented while idle");
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            if (!error_valid || error_code != 3'd1 || store_valid || loading)
                fail("invalid config mode/epoch was not rejected fail-closed");
        end
    endtask

    task automatic test_early_commit;
        integer i;
        begin
            @(negedge clk);
            cfg_mode = MODE_UNARY;
            cfg_epoch = 32'h0000e001;
            cfg_begin = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            #1; // allow combinational ready outputs to settle after deassertion
            if (!loading || !cfg_word_ready) begin
                fail("early-commit setup did not load");
            end
            for (i = 0; i < 7; i = i + 1) begin
                cfg_word_valid = 1'b1;
                cfg_data = i[7:0];
                @(posedge clk);
                @(negedge clk);
            end
            cfg_word_valid = 1'b0;
            cfg_commit = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cfg_commit = 1'b0;
            if (!error_valid || error_code != 3'd2 || store_valid || loading)
                fail("early commit was not rejected");
        end
    endtask

    task automatic test_overlong_load;
        integer i;
        begin
            @(negedge clk);
            cfg_mode = MODE_UNARY;
            cfg_epoch = 32'h0000e002;
            cfg_begin = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            if (!loading) fail("overlong-load setup did not load");
            for (i = 0; i < 257; i = i + 1) begin
                cfg_word_valid = 1'b1;
                cfg_data = i[7:0];
                @(posedge clk);
                @(negedge clk);
                if (i < 256 && !loading) fail("unary load ended before 256 bytes");
            end
            cfg_word_valid = 1'b0;
            if (!error_valid || error_code != 3'd3 || store_valid || loading)
                fail("overlong table load was not rejected");
        end
    endtask

    task automatic load_table(input string filename, input integer mode,
                              input integer length, input [31:0] epoch,
                              input integer is_nominal);
        integer i;
        begin
            $readmemh(filename, expected_table, 0, length - 1);
            @(negedge clk);
            cfg_mode = mode[1:0];
            cfg_epoch = epoch;
            cfg_begin = 1'b1;
            if (!cfg_begin_ready) fail("table load begin was blocked while idle");
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            if (!loading || store_valid) fail("table load did not disable active data");

            // Input is explicitly disabled throughout a table transfer.
            in_valid = 1'b1;
            in_epoch = epoch;
            in_mode = mode[1:0];
            in_lanes = 5'd1;
            if (in_ready) fail("input became ready while a table was loading");
            @(posedge clk);
            @(negedge clk);
            in_valid = 1'b0;

            for (i = 0; i < length; i = i + 1) begin
                cfg_word_valid = 1'b1;
                cfg_data = expected_table[i];
                if (!cfg_word_ready) fail("table byte loader lost ready");
                @(posedge clk);
                @(negedge clk);
            end
            cfg_word_valid = 1'b0;
            cfg_commit = 1'b1;
            if (!cfg_commit_ready) fail("table commit was blocked");
            @(posedge clk);
            @(negedge clk);
            cfg_commit = 1'b0;
            if (!store_valid || loading || active_epoch != epoch || active_mode != mode[1:0])
                fail("exact table load did not commit");
        end
    endtask

    task automatic drive_beat(input integer mode, input [31:0] epoch,
                              input [31:0] token, input integer lanes,
                              input integer last, input [127:0] a_data,
                              input [127:0] b_data);
        begin
            @(negedge clk);
            in_valid = 1'b1;
            in_epoch = epoch;
            in_token = token;
            in_mode = mode[1:0];
            in_lanes = lanes[4:0];
            in_last = last[0];
            in_a = a_data;
            in_b = b_data;
            while (!in_ready) @(negedge clk);
            @(posedge clk);
        end
    endtask

    task automatic send_invalid(input integer mode, input [31:0] epoch,
                                input integer lanes, input [31:0] token);
        begin
            drive_beat(mode, epoch, token, lanes, 1, 128'd0, 128'd0);
            @(negedge clk);
            in_valid = 1'b0;
            if (!error_valid || error_code != 3'd4 || !store_valid)
                fail("invalid request was not refused while preserving the loaded table");
        end
    endtask

    task automatic exhaustive_table(input integer mode, input integer length,
                                    input [31:0] epoch, input integer table_number);
        integer batch;
        integer lane_number;
        integer permutation;
        integer address_index;
        reg [127:0] a_data;
        reg [127:0] b_data;
        begin
            a_data = 128'd0;
            b_data = 128'd0;
            in_valid = 1'b0;
            out_ready = 1'b1;
            for (batch = 0; batch < length / 16; batch = batch + 1) begin
                a_data = 128'd0;
                b_data = 128'd0;
                for (lane_number = 0; lane_number < 16; lane_number = lane_number + 1) begin
                    permutation = (lane_number * 5 + batch) % 16;
                    address_index = batch * 16 + permutation;
                    if (mode == MODE_UNARY) begin
                        a_data[lane_number*8 +: 8] = address_index ^ 8'h80;
                        b_data[lane_number*8 +: 8] = (address_index * 13 + lane_number) & 255;
                    end else begin
                        a_data[lane_number*8 +: 8] = ((address_index >> 8) & 255) ^ 8'h80;
                        b_data[lane_number*8 +: 8] = (address_index & 255) ^ 8'h80;
                    end
                end
                @(negedge clk);
                in_valid = 1'b1;
                in_epoch = epoch;
                in_token = (table_number << 16) | batch;
                in_mode = mode[1:0];
                in_lanes = 5'd16;
                in_last = (batch == (length / 16) - 1);
                in_a = a_data;
                in_b = b_data;
                if (!in_ready) fail("un-stalled exhaustive lookup lost ready");
                @(posedge clk);
                if (!in_ready) fail("un-stalled exhaustive lookup did not accept");
            end
            @(negedge clk);
            in_valid = 1'b0;
            wait_empty();
        end
    endtask

    task automatic test_partial_backpressure(input [31:0] epoch);
        reg [127:0] a_data;
        reg [127:0] b_data;
        begin
            out_ready = 1'b0;
            a_data = 128'd0;
            b_data = 128'd0;
            // First request has one active lane.
            a_data[7:0] = 8'h80;
            drive_beat(MODE_UNARY, epoch, 32'habc00001, 1, 0, a_data, b_data);
            @(negedge clk);
            in_valid = 1'b0; // real input bubble between accepted beats
            @(posedge clk);
            // Second request is partial and moves into the RAM-read slot while
            // the first result is held in the output slot.
            a_data = 128'd0;
            b_data = 128'd0;
            a_data[7:0] = 8'h00;
            a_data[15:8] = 8'h81;
            a_data[23:16] = 8'h7f;
            a_data[31:24] = 8'hfe;
            a_data[39:32] = 8'h02;
            a_data[47:40] = 8'h10;
            a_data[55:48] = 8'hff;
            drive_beat(MODE_UNARY, epoch, 32'habc00002, 7, 1, a_data, b_data);
            @(negedge clk);
            in_valid = 1'b0;
            if (!out_valid || !dut.rd_valid || in_ready)
                fail("two-slot backpressure state was not reached");

            cfg_begin = 1'b1;
            cfg_epoch = epoch + 1;
            cfg_mode = MODE_UNARY;
            if (cfg_begin_ready) fail("reload began with lookup requests inflight");
            @(posedge clk);
            @(negedge clk);
            cfg_begin = 1'b0;
            if (!store_valid || !out_valid || !dut.rd_valid)
                fail("rejected reload disturbed stalled lookup state");
            repeat (5) @(posedge clk);
            @(negedge clk);
            out_ready = 1'b1;
            wait_empty();
            // Exercise a wider partial count and a lane-15 tail mask.
            a_data = 128'd0;
            b_data = 128'd0;
            for (integer k = 0; k < 15; k = k + 1)
                a_data[k*8 +: 8] = (k * 17 + 3) & 255;
            drive_beat(MODE_UNARY, epoch, 32'habc00003, 15, 1, a_data, b_data);
            @(negedge clk);
            in_valid = 1'b0;
            wait_empty();
        end
    endtask

    task automatic test_cancel_pending(input [31:0] epoch);
        reg [127:0] a_data;
        begin
            out_ready = 1'b0;
            a_data = 128'h00112233445566778899aabbccddeeff;
            drive_beat(MODE_UNARY, epoch, 32'hcace0001, 16, 1, a_data, 128'd0);
            @(negedge clk);
            in_valid = 1'b0;
            repeat (3) @(posedge clk);
            @(negedge clk);
            if (!out_valid) fail("cancel test did not create a pending output");
            cancel = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cancel = 1'b0;
            out_ready = 1'b1;
            if (out_valid || store_valid || loading || dut.rd_valid)
                fail("cancel did not invalidate store and inflight result");
        end
    endtask

    task automatic test_reset_pending(input integer mode, input [31:0] epoch);
        reg [127:0] a_data;
        reg [127:0] b_data;
        begin
            out_ready = 1'b0;
            a_data = 128'h80fe7f00010203040506070809101112;
            b_data = 128'hffeeddbbccaa99887766554433221100;
            drive_beat(mode, epoch, 32'h5e700001, 16, 1, a_data, b_data);
            @(negedge clk);
            in_valid = 1'b0;
            repeat (3) @(posedge clk);
            @(negedge clk);
            if (!out_valid) fail("reset test did not create a pending output");
            rst_n = 1'b0;
            repeat (2) @(posedge clk);
            @(negedge clk);
            if (out_valid || store_valid || loading || dut.rd_valid)
                fail("reset did not invalidate store and inflight result");
            rst_n = 1'b1;
            out_ready = 1'b1;
            @(posedge clk);
            @(negedge clk);
        end
    endtask

    task automatic run_file_table(input integer table_number, input integer mode,
                                  input integer length, input integer node_id,
                                  input integer input_index, input string filename,
                                  input integer do_exhaustive);
        reg [31:0] epoch;
        begin
            epoch = table_number + 1;
            load_table(filename, mode, length, epoch, 1);
            if (table_number == 0) begin
                test_partial_backpressure(epoch);
                test_cancel_pending(epoch);
                // Reload after cancel, then exhaustively cover the first table.
                load_table(filename, mode, length, epoch, 0);
            end
            if (do_exhaustive)
                exhaustive_table(mode, length, epoch, table_number);
        end
    endtask

    integer table_fd;
    integer scan_rc;
    integer table_number;
    integer table_mode;
    integer table_length;
    integer table_node;
    integer table_input;
    integer tables_seen = 0;
    integer unary_tables_seen = 0;
    integer add_tables_seen = 0;
    integer exhaustive_beats = 0;
    integer exhaustive_values = 0;
    integer nominal_table_bytes = 0;
    integer final_mode = 0;
    integer final_length = 0;
    integer final_node = 0;
    integer final_input = 0;
    string table_filename;
    string final_filename;

    initial begin
        queue_head = 0;
        queue_tail = 0;
        repeat (3) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;

        begin_bad_config(2'b10, 32'd1);
        begin_bad_config(MODE_UNARY, 32'd0);
        test_early_commit();
        test_overlong_load();

        table_fd = $fopen("pointwise_tables.index", "r");
        if (table_fd == 0) fail("pointwise_tables.index could not be opened");
        while (!$feof(table_fd)) begin
            scan_rc = $fscanf(table_fd, "%d %d %d %d %d %s\n",
                              table_number, table_mode, table_length,
                              table_node, table_input, table_filename);
            if (scan_rc == 6) begin
                if ((table_mode == 0 && table_length != 256) ||
                    (table_mode == 1 && table_length != 65536))
                    fail("table index has unexpected byte length");
                run_file_table(table_number, table_mode, table_length, table_node,
                               table_input, table_filename, 1);
                tables_seen = tables_seen + 1;
                if (table_mode == 0) begin
                    unary_tables_seen = unary_tables_seen + 1;
                end else begin
                    add_tables_seen = add_tables_seen + 1;
                end
                exhaustive_beats = exhaustive_beats + (table_length / 16);
                exhaustive_values = exhaustive_values + table_length;
                nominal_table_bytes = nominal_table_bytes + table_length;
                final_mode = table_mode;
                final_length = table_length;
                final_node = table_node;
                final_input = table_input;
                final_filename = table_filename;
            end else if (!$feof(table_fd)) begin
                fail("malformed pointwise_tables.index row");
            end
        end
        $fclose(table_fd);
        if (tables_seen != 128 || unary_tables_seen != 122 || add_tables_seen != 6 ||
            exhaustive_beats != 26528 || exhaustive_values != 424448 ||
            nominal_table_bytes != 424448)
            fail("table index totals differ from the pinned package");

        // A reset while a synchronous read and an output are pending drops
        // both slots; reload the last unary table and prove recovery.
        test_reset_pending(final_mode, tables_seen);
        load_table(final_filename, final_mode, final_length, tables_seen, 0);
        send_invalid(final_mode, tables_seen + 1, 1, 32'hbad00001); // stale epoch
        send_invalid(final_mode, tables_seen, 0, 32'hbad00002);     // zero lanes
        send_invalid(final_mode, tables_seen, 17, 32'hbad00003);    // >16 lanes
        send_invalid(2, tables_seen, 1, 32'hbad00004);              // invalid mode
        if (input_refusals != 4) fail("invalid request refusal count mismatch");

        drive_beat(final_mode, tables_seen, 32'hfeed0001, 1, 1,
                   128'h00000000000000000000000000000080, 128'd0);
        @(negedge clk);
        in_valid = 1'b0;
        wait_empty();
        if (errors_seen != 8 || lookup_comparisons < 424448 ||
            max_ii1 < 4096 || stall_cycles < 5 || cfg_overlong != 1 ||
            cfg_writes != 425223)
            fail("coverage totals failed fixed acceptance counts");
        $display("POINTWISE_LOOKUP_PASS tables=%0d unary_tables=%0d add_tables=%0d exhaustive_beats=%0d exhaustive_values=%0d responses=%0d comparisons=%0d max_ii1=%0d stalls=%0d cfg_writes=%0d overlong=%0d refused=%0d errors=%0d reset=1 cancel=1",
                 tables_seen, unary_tables_seen, add_tables_seen, exhaustive_beats,
                 exhaustive_values, responses, lookup_comparisons, max_ii1,
                 stall_cycles, cfg_writes, cfg_overlong, input_refusals, errors_seen);
        $finish;
    end
endmodule
`default_nettype wire
