`timescale 1ns/1ps
`default_nettype none

module tb_z100_feature_banks_4read;
    localparam integer AW = 13;
    localparam integer CASE_COUNT = 91;
    localparam integer MAX_WORDS = 9920;
    localparam integer LOGICAL_PORTS = 256;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;
    reg cancel = 1'b0;

    reg cfg_begin = 1'b0;
    wire cfg_begin_ready;
    reg [31:0] cfg_epoch = 0;
    reg [10:0] cfg_channels = 0;
    reg [9:0] cfg_height = 0;
    reg [9:0] cfg_width = 0;
    reg cfg_word_valid = 1'b0;
    wire cfg_word_ready;
    reg [511:0] cfg_word_data = 0;
    reg [31:0] cfg_word_epoch = 0;
    reg [12:0] cfg_word_address = 0;
    reg cfg_word_last = 1'b0;
    reg cfg_commit = 1'b0;
    wire cfg_commit_ready;
    wire error_valid;
    wire [3:0] error_code;
    wire store_valid;
    wire [31:0] active_epoch;
    wire loading;

    reg req_valid = 1'b0;
    wire req_ready;
    reg [31:0] req_epoch = 0;
    reg [64*4*AW-1:0] req_addresses = 0;
    reg [255:0] req_mask = 0;
    wire out_valid;
    reg out_ready = 1'b0;
    wire [31:0] out_epoch;
    wire [2047:0] out_data;

    reg [255:0] case_table [0:CASE_COUNT-1];
    reg [511:0] loader_words [0:MAX_WORDS-1];
    reg [12:0] loader_addresses [0:MAX_WORDS-1];
    reg [511:0] expected_words [0:MAX_WORDS-1];
    reg [12:0] score_addresses [0:LOGICAL_PORTS-1];

    integer total_cfg_words = 0;
    integer config_read_rejects = 0;
    integer input_conflict_rejections = 0;
    integer cfg_bubble_cycles = 0;
    integer request_count = 0;
    integer response_count = 0;
    integer checked_bytes = 0;
    integer request_stall_cycles = 0;
    integer request_stability_checks = 0;
    integer output_stall_cycles = 0;
    integer output_stability_checks = 0;
    integer max_ii1_response_burst = 0;
    integer current_ii1_response_burst = 0;
    integer simulation_cycle = 0;
    integer previous_response_cycle = -2;
    integer error_checks = 0;
    integer errors_by_code [0:7];
    integer recovery_checks = 0;
    integer global_bad_read_checks = 0;
    integer child_read_suppressions = 0;
    integer child_store_flush_checks = 0;
    integer masked_bad_address_accepts = 0;
    integer cases_completed = 0;
    integer scoreboard_enabled = 0;
    integer scoreboard_base = 0;
    reg [31:0] scoreboard_epoch = 0;
    integer pending_read = 0;
    integer previous_request_stalled = 0;
    reg [31:0] held_req_epoch = 0;
    reg [64*4*AW-1:0] held_req_addresses = 0;
    reg [255:0] held_req_mask = 0;
    integer previous_output_stalled = 0;
    reg [2047:0] held_output_data = 0;
    reg [31:0] held_output_epoch = 0;
    integer monitor_q;
    integer monitor_bank;
    integer expected_byte_value;
    integer response_contiguous;
    integer req_cycle_fire;

    z100_feature_banks_4read #(.ADDR_BITS(AW), .DEPTH(8192)) dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(cfg_begin_ready),
        .cfg_epoch(cfg_epoch), .cfg_channels(cfg_channels),
        .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_word_valid(cfg_word_valid), .cfg_word_ready(cfg_word_ready),
        .cfg_word_data(cfg_word_data), .cfg_word_epoch(cfg_word_epoch),
        .cfg_word_address(cfg_word_address), .cfg_word_last(cfg_word_last),
        .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .error_valid(error_valid), .error_code(error_code),
        .store_valid(store_valid), .active_epoch(active_epoch), .loading(loading),
        .req_valid(req_valid), .req_ready(req_ready), .req_epoch(req_epoch),
        .req_addresses(req_addresses), .req_mask(req_mask),
        .out_valid(out_valid), .out_ready(out_ready), .out_epoch(out_epoch),
        .out_data(out_data)
    );

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            pending_read = 0;
            previous_request_stalled = 0;
            previous_output_stalled = 0;
            current_ii1_response_burst = 0;
            previous_response_cycle = -2;
        end else begin
            if (previous_request_stalled) begin
                if (!req_valid || req_epoch !== held_req_epoch ||
                    req_addresses !== held_req_addresses || req_mask !== held_req_mask)
                    $fatal(1, "request payload changed while backpressured");
                request_stability_checks = request_stability_checks + 1;
            end
            previous_request_stalled = req_valid && !req_ready;
            if (previous_request_stalled) begin
                request_stall_cycles = request_stall_cycles + 1;
                held_req_epoch = req_epoch;
                held_req_addresses = req_addresses;
                held_req_mask = req_mask;
            end

            if (previous_output_stalled) begin
                if (!out_valid || out_data !== held_output_data ||
                    out_epoch !== held_output_epoch)
                    $fatal(1, "output payload changed while backpressured");
                output_stability_checks = output_stability_checks + 1;
            end
            previous_output_stalled = out_valid && !out_ready;
            if (previous_output_stalled) begin
                output_stall_cycles = output_stall_cycles + 1;
                held_output_data = out_data;
                held_output_epoch = out_epoch;
            end

            if (scoreboard_enabled && out_valid && out_ready) begin
                if (!pending_read)
                    $fatal(1, "response arrived with no accepted read request");
                if (out_epoch !== scoreboard_epoch)
                    $fatal(1, "response epoch mismatch got=%0d expected=%0d",
                           out_epoch, scoreboard_epoch);
                for (monitor_q = 0; monitor_q < LOGICAL_PORTS; monitor_q = monitor_q + 1) begin
                    monitor_bank = monitor_q / 4;
                    expected_byte_value = expected_words[
                        scoreboard_base + score_addresses[monitor_q]][monitor_bank*8 +: 8];
                    if (out_data[monitor_q*8 +: 8] !== expected_byte_value[7:0])
                        $fatal(1, "data mismatch q=%0d bank=%0d address=%0d got=%02x expected=%02x",
                               monitor_q, monitor_bank, score_addresses[monitor_q],
                               out_data[monitor_q*8 +: 8], expected_byte_value[7:0]);
                    checked_bytes = checked_bytes + 1;
                end
                response_count = response_count + 1;
                pending_read = 0;
                if (previous_response_cycle == simulation_cycle - 1)
                    current_ii1_response_burst = current_ii1_response_burst + 1;
                else
                    current_ii1_response_burst = 1;
                if (current_ii1_response_burst > max_ii1_response_burst)
                    max_ii1_response_burst = current_ii1_response_burst;
                previous_response_cycle = simulation_cycle;
            end

            if (scoreboard_enabled && req_valid && req_ready) begin
                if (pending_read && !(out_valid && out_ready))
                    $fatal(1, "more than one outstanding request in one-deep response fixture");
                for (monitor_q = 0; monitor_q < LOGICAL_PORTS; monitor_q = monitor_q + 1)
                    score_addresses[monitor_q] =
                        req_addresses[monitor_q*AW +: AW];
                pending_read = 1;
                request_count = request_count + 1;
            end
        end
        simulation_cycle = simulation_cycle + 1;
    end

    task automatic tick;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    task automatic build_request(input integer request_index,
                                 input integer word_count);
        integer bank_index;
        integer port_index;
        integer address_value;
        begin
            req_addresses = 0;
            req_mask = {256{1'b1}};
            for (bank_index = 0; bank_index < 64; bank_index = bank_index + 1) begin
                for (port_index = 0; port_index < 4; port_index = port_index + 1) begin
                    address_value = (request_index + port_index + bank_index * 11) % word_count;
                    req_addresses[(bank_index*4+port_index)*AW +: AW] = address_value[AW-1:0];
                end
            end
        end
    endtask

    task automatic begin_load(input integer epoch_arg, channels_arg,
                              input integer height_arg, width_arg);
        integer waited;
        begin
            @(negedge clk);
            waited = 0;
            while (!cfg_begin_ready) begin
                if (waited >= 1000) $fatal(1, "timeout waiting cfg_begin_ready");
                @(negedge clk);
                waited = waited + 1;
            end
            cfg_epoch = epoch_arg;
            cfg_channels = channels_arg;
            cfg_height = height_arg;
            cfg_width = width_arg;
            cfg_begin = 1'b1;
            tick();
            if (!loading || store_valid)
                $fatal(1, "begin_load failed to enter loading state");
            @(negedge clk);
            cfg_begin = 1'b0;
        end
    endtask

    task automatic send_manual_word(input integer epoch_arg, address_arg,
                                    input reg [511:0] data_arg,
                                    input integer last_arg);
        integer waited;
        begin
            @(negedge clk);
            waited = 0;
            while (!cfg_word_ready) begin
                if (waited >= 1000) $fatal(1, "timeout waiting cfg_word_ready");
                @(negedge clk);
                waited = waited + 1;
            end
            cfg_word_epoch = epoch_arg;
            cfg_word_address = address_arg;
            cfg_word_data = data_arg;
            cfg_word_last = last_arg;
            cfg_word_valid = 1'b1;
            tick();
            @(negedge clk);
            cfg_word_valid = 1'b0;
        end
    endtask

    task automatic commit_valid(input integer epoch_arg);
        begin
            @(negedge clk);
            if (!cfg_commit_ready) $fatal(1, "commit unexpectedly not ready");
            cfg_commit = 1'b1;
            tick();
            if (error_valid || !store_valid || loading || active_epoch != epoch_arg)
                $fatal(1, "commit failed epoch=%0d error=%b/%0d store=%b active=%0d",
                       epoch_arg, error_valid, error_code, store_valid, active_epoch);
            @(negedge clk);
            cfg_commit = 1'b0;
        end
    endtask

    task automatic expect_error(input integer code_arg);
        begin
            if (!error_valid || error_code != code_arg || store_valid || loading || out_valid)
                $fatal(1, "error mismatch expected=%0d got=%b/%0d store=%b loading=%b out=%b",
                       code_arg, error_valid, error_code, store_valid, loading, out_valid);
            error_checks = error_checks + 1;
            errors_by_code[code_arg] = errors_by_code[code_arg] + 1;
        end
    endtask

    task automatic expect_global_bad_read_and_flush(input integer request_epoch_arg,
                                                     input integer logical_port_arg,
                                                     input integer address_arg);
        begin
            @(negedge clk);
            req_epoch = request_epoch_arg;
            req_addresses = 0;
            req_addresses[logical_port_arg*AW +: AW] = address_arg[AW-1:0];
            req_mask = 0;
            req_mask[logical_port_arg] = 1'b1;
            req_valid = 1'b1;
            out_ready = 1'b1;
            #1;
            if (!req_ready)
                $fatal(1, "global bad-read request was not accepted port=%0d address=%0d",
                       logical_port_arg, address_arg);
            if (dut.req_valid_i !== 1'b0)
                $fatal(1, "globally rejected request reached child copies port=%0d address=%0d",
                       logical_port_arg, address_arg);
            child_read_suppressions = child_read_suppressions + 1;
            tick();
            expect_error(7);
            if (!dut.local_badread_pulse || store_valid || out_valid || req_ready ||
                cfg_begin_ready || dut.active_words_q != 0)
                $fatal(1, "global bad-read pulse did not immediately invalidate public state");
            @(negedge clk); req_valid = 1'b0;
            tick();
            if (dut.store_valid_a || dut.store_valid_b ||
                dut.active_epoch_a != 0 || dut.active_epoch_b != 0 ||
                dut.out_valid_a || dut.out_valid_b || error_valid || loading ||
                store_valid || out_valid)
                $fatal(1, "global bad-read pulse failed to flush both child stores");
            child_store_flush_checks = child_store_flush_checks + 1;
            global_bad_read_checks = global_bad_read_checks + 1;
        end
    endtask

    task automatic run_case(input integer case_index);
        reg [255:0] descriptor;
        integer channels_value;
        integer height_value;
        integer width_value;
        integer epoch_value;
        integer words_value;
        integer load_start;
        integer expected_start;
        integer word_index;
        integer accepted_requests;
        integer cycles;
        integer wait_cycles;
        integer start_requests;
        integer start_responses;
        integer was_accepted;
        begin
            descriptor = case_table[case_index];
            channels_value = descriptor[10:0];
            height_value = descriptor[20:11];
            width_value = descriptor[30:21];
            epoch_value = descriptor[62:31];
            words_value = descriptor[76:63];
            load_start = descriptor[90:77];
            expected_start = descriptor[104:91];

            begin_load(epoch_value, channels_value, height_value, width_value);

            // The read channel must remain not-ready while configuration owns the store.
            @(negedge clk);
            req_epoch = epoch_value;
            req_mask = {256{1'b1}};
            build_request(0, words_value);
            if (req_ready) $fatal(1, "read accepted while configuration loading");
            tick();
            if (req_ready) $fatal(1, "read became ready during configuration load");
            config_read_rejects = config_read_rejects + 1;

            for (word_index = 0; word_index < words_value; word_index = word_index + 1) begin
                if ((word_index % 17) == 0) begin
                    @(negedge clk);
                    cfg_word_valid = 1'b0;
                    tick();
                    cfg_bubble_cycles = cfg_bubble_cycles + 1;
                end
                @(negedge clk);
                cfg_word_epoch = epoch_value;
                cfg_word_address = loader_addresses[load_start + word_index];
                cfg_word_data = loader_words[load_start + word_index];
                cfg_word_last = (word_index == words_value - 1);
                cfg_word_valid = 1'b1;
                if (!cfg_word_ready) $fatal(1, "child write ready dropped during load");
                tick();
                total_cfg_words = total_cfg_words + 1;
                @(negedge clk);
                cfg_word_valid = 1'b0;
            end
            commit_valid(epoch_value);

            scoreboard_base = expected_start;
            scoreboard_epoch = epoch_value;
            scoreboard_enabled = 1;
            start_requests = request_count;
            start_responses = response_count;
            accepted_requests = 0;
            cycles = 0;
            @(negedge clk);
            req_epoch = epoch_value;
            out_ready = 1'b0;
            req_valid = 1'b1;
            build_request(accepted_requests, words_value);
            while (accepted_requests < words_value) begin
                @(posedge clk);
                was_accepted = req_valid && req_ready;
                #1;
                if (was_accepted) accepted_requests = accepted_requests + 1;
                cycles = cycles + 1;
                if (cycles > words_value + 1000)
                    $fatal(1, "bounded request acceptance wait case=%0d accepted=%0d/%0d",
                           case_index, accepted_requests, words_value);
                @(negedge clk);
                if (accepted_requests < words_value) begin
                    req_valid = 1'b1;
                    build_request(accepted_requests, words_value);
                end else begin
                    req_valid = 1'b0;
                end
                if (cycles <= 5)
                    out_ready = 1'b0;
                else if (cycles <= 40)
                    out_ready = 1'b1;
                else
                    out_ready = ((cycles % 37) != 11) && ((cycles % 37) != 12) &&
                                ((cycles % 37) != 13);
            end

            @(negedge clk);
            req_valid = 1'b0;
            out_ready = 1'b1;
            wait_cycles = 0;
            while (response_count < start_responses + words_value) begin
                tick();
                wait_cycles = wait_cycles + 1;
                if (wait_cycles > 1000)
                    $fatal(1, "bounded response drain case=%0d responses=%0d/%0d",
                           case_index, response_count - start_responses, words_value);
                @(negedge clk);
                out_ready = 1'b1;
            end
            if (request_count != start_requests + words_value ||
                response_count != start_responses + words_value || pending_read != 0)
                $fatal(1, "request/response count mismatch case=%0d", case_index);
            scoreboard_enabled = 0;
            out_ready = 1'b0;
            if (case_index == 0) begin
                // Conflicting command classes remain held atomically; external
                // cancel aborts the deliberately malformed overlapping probe.
                @(negedge clk);
                cfg_epoch = epoch_value + 32'd1;
                cfg_channels = channels_value;
                cfg_height = height_value;
                cfg_width = width_value;
                cfg_begin = 1'b1;
                req_epoch = epoch_value;
                build_request(0, words_value);
                req_valid = 1'b1;
                #1;
                repeat (2) begin
                    if (cfg_begin_ready || req_ready)
                        $fatal(1, "conflicting command classes were not held");
                    tick();
                    if (!store_valid || active_epoch != epoch_value || loading || error_valid)
                        $fatal(1, "conflicting command classes changed mirrored state");
                    @(negedge clk);
                end
                cancel = 1'b1;
                tick();
                if (store_valid || loading || out_valid)
                    $fatal(1, "cancel did not abort conflicting command probe");
                @(negedge clk);
                cfg_begin = 1'b0;
                req_valid = 1'b0;
                cancel = 1'b0;
                input_conflict_rejections = input_conflict_rejections + 1;
            end
            cases_completed = cases_completed + 1;
        end
    endtask

    task automatic run_error_tests;
        reg [511:0] bad_word;
        integer small_epoch;
        begin
            // Invalid geometry: rejected before either mirror begins loading.
            @(negedge clk);
            cfg_epoch = 7001; cfg_channels = 1025; cfg_height = 1; cfg_width = 1;
            cfg_begin = 1'b1;
            tick(); expect_error(1);
            @(negedge clk); cfg_begin = 1'b0;

            // Early commit.
            begin_load(7002, 1, 1, 1);
            @(negedge clk); cfg_commit = 1'b1;
            tick(); expect_error(5);
            @(negedge clk); cfg_commit = 1'b0;

            // Wrong physical address/order.
            begin_load(7003, 1, 1, 1);
            bad_word = 0; bad_word[7:0] = 8'h53;
            send_manual_word(7003, 1, bad_word, 1); expect_error(2);

            // Wrong input epoch.
            begin_load(7004, 1, 1, 1);
            send_manual_word(7005, 0, 0, 1); expect_error(2);

            // Incorrect last marker.
            begin_load(7006, 1, 1, 1);
            send_manual_word(7006, 0, 0, 0); expect_error(3);

            // Nonzero padded bank byte.
            begin_load(7007, 1, 1, 1);
            bad_word = 0; bad_word[8 +: 8] = 8'hA7;
            send_manual_word(7007, 0, bad_word, 1); expect_error(4);

            // Extra word after the exact count.
            begin_load(7008, 1, 1, 1);
            send_manual_word(7008, 0, 0, 1);
            send_manual_word(7008, 0, 0, 1); expect_error(6);

            // Cancel and reset each invalidate a partial load; a later epoch reloads.
            begin_load(7009, 4, 1, 32);
            send_manual_word(7009, 0, 0, 0);
            @(negedge clk); cancel = 1'b1; tick();
            if (store_valid || loading || out_valid) $fatal(1, "cancel kept partial load valid");
            recovery_checks = recovery_checks + 1;
            @(negedge clk); cancel = 1'b0;

            begin_load(7010, 4, 1, 32);
            send_manual_word(7010, 0, 0, 0);
            @(negedge clk); rst_n = 1'b0; tick();
            if (store_valid || loading || out_valid) $fatal(1, "reset kept partial load valid");
            recovery_checks = recovery_checks + 1;
            @(negedge clk); rst_n = 1'b1; tick();

            // Bad epoch and address reads fail closed and do not return a response.
            begin_load(7011, 1, 1, 1);
            send_manual_word(7011, 0, 0, 1);
            commit_valid(7011);
            expect_global_bad_read_and_flush(7012, 0, 0);

            begin_load(7013, 1, 1, 1);
            send_manual_word(7013, 0, 0, 1);
            commit_valid(7013);
            expect_global_bad_read_and_flush(7013, 2, 1);

            // Cancel while a valid response is pending, then prove a fresh load works.
            small_epoch = 7014;
            begin_load(small_epoch, 1, 1, 1);
            send_manual_word(small_epoch, 0, 0, 1);
            commit_valid(small_epoch);
            @(negedge clk); req_epoch = small_epoch; req_addresses = 0;
            req_addresses[0 +: AW] = 1;
            req_addresses[3*AW +: AW] = 0;
            req_mask = 0; req_mask[3] = 1'b1;
            req_valid = 1; out_ready = 1;
            #1;
            if (!req_ready || dut.req_valid_i !== 1'b1)
                $fatal(1, "masked out-of-range address incorrectly rejected request");
            tick();
            if (!out_valid || out_epoch != small_epoch || error_valid || !store_valid)
                $fatal(1, "masked out-of-range address did not preserve valid request");
            for (monitor_q = 0; monitor_q < LOGICAL_PORTS; monitor_q = monitor_q + 1)
                if (out_data[monitor_q*8 +: 8] !== 8'h00)
                    $fatal(1, "masked address control returned nonzero data q=%0d", monitor_q);
            @(negedge clk); req_valid = 0;
            tick();
            if (out_valid || error_valid || !store_valid)
                $fatal(1, "masked address control did not drain cleanly");
            masked_bad_address_accepts = masked_bad_address_accepts + 1;

            @(negedge clk); req_epoch = small_epoch; req_addresses = 0;
            req_mask = 1; req_valid = 1; out_ready = 0;
            tick();
            @(negedge clk); req_valid = 0;
            if (!out_valid) $fatal(1, "expected stalled response before cancel");
            cancel = 1'b1; tick();
            if (out_valid || store_valid || loading) $fatal(1, "cancel did not flush pending response");
            recovery_checks = recovery_checks + 1;
            @(negedge clk); cancel = 1'b0; out_ready = 0;

            // Force one internal mirrored epoch disagreement to verify the wrapper's
            // fail-closed latch; external cancel is the sole documented clear path.
            small_epoch = 7015;
            begin_load(small_epoch, 1, 1, 1);
            send_manual_word(small_epoch, 0, 0, 1);
            commit_valid(small_epoch);
            force dut.active_epoch_b = active_epoch ^ 32'h00000001;
            #1;
            if (!error_valid || error_code != 8 || store_valid || req_ready || cfg_begin_ready)
                $fatal(1, "mirror disagreement was not fail-closed");
            if (dut.child_cancel)
                $fatal(1, "mirror compare still drives child cancel combinationally");
            req_epoch = small_epoch; req_mask = 1; req_addresses = 0; req_valid = 1;
            #1;
            if (req_ready || dut.req_valid_i || out_valid || cfg_word_ready || cfg_commit_ready)
                $fatal(1, "unregistered mirror fault admitted an external transaction");
            tick();
            if (!dut.mirror_fault_latched || !dut.child_cancel || req_ready || out_valid)
                $fatal(1, "mirror fault was not captured before child flush");
            release dut.active_epoch_b;
            tick();
            if (dut.store_valid_a || dut.store_valid_b || dut.loading_a || dut.loading_b ||
                !error_valid || error_code != 8 || req_ready || out_valid)
                $fatal(1, "registered mirror cancel did not flush both child stores");
            $display("MIRROR_CANCEL_SEAM_PASS immediate_public_block=1 suppressed_child_requests=1 registered_flush=1 sticky_until_cancel=1");
            @(negedge clk); req_valid = 0; cancel = 1'b1; tick();
            if (error_valid || store_valid || loading || out_valid)
                $fatal(1, "external cancel did not clear mirrored fault state");
            @(negedge clk); cancel = 1'b0; out_ready = 0;
            recovery_checks = recovery_checks + 1;

            small_epoch = 7016;
            begin_load(small_epoch, 1, 1, 1);
            send_manual_word(small_epoch, 0, 0, 1);
            commit_valid(small_epoch);
            @(negedge clk); req_epoch = small_epoch; req_addresses = 0;
            req_mask = {256{1'b0}}; req_mask[0] = 1'b1; req_mask[255] = 1'b1;
            req_valid = 1'b1; out_ready = 1'b1;
            if (!req_ready) $fatal(1, "recovery read was not ready");
            tick();
            if (!out_valid || out_epoch != small_epoch)
                $fatal(1, "post-cancel reload did not produce a response");
            for (monitor_q = 0; monitor_q < LOGICAL_PORTS; monitor_q = monitor_q + 1) begin
                if ((monitor_q == 0 || monitor_q == 255) && out_data[monitor_q*8 +: 8] !== 8'h00)
                    $fatal(1, "recovery masked read data mismatch");
                if ((monitor_q != 0 && monitor_q != 255) && out_data[monitor_q*8 +: 8] !== 8'h00)
                    $fatal(1, "masked output tail was not forced to zero");
            end
            @(negedge clk); req_valid = 0;
            tick();
            if (out_valid) $fatal(1, "recovery response did not drain");
            recovery_checks = recovery_checks + 1;
        end
    endtask

    integer case_index;
    task automatic admission_depth_tests;
        integer phase, pattern, bits_set, repeats, conflict_checks, blocked_begins;
        reg [13:0] saved_pending;
        begin
            conflict_checks = 0; blocked_begins = 0;
            // All 11 conflicting subsets in both idle and loading states.
            for (phase=0; phase<2; phase=phase+1) begin
                for (pattern=1; pattern<16; pattern=pattern+1) begin
                    bits_set = ((pattern>>0)&1)+((pattern>>1)&1)+
                               ((pattern>>2)&1)+((pattern>>3)&1);
                    if (bits_set>1) begin
                        @(negedge clk); cancel=1; tick();
                        @(negedge clk); cancel=0;
                        if (phase==1) begin_load(8001,4,2,16);
                        saved_pending = dut.pending_words;
                        @(negedge clk);
                        cfg_begin=pattern[0]; cfg_word_valid=pattern[1];
                        cfg_commit=pattern[2]; req_valid=pattern[3];
                        for (repeats=0; repeats<3; repeats=repeats+1) begin
                            #1;
                            if (cfg_begin_ready || cfg_word_ready || cfg_commit_ready || req_ready ||
                                dut.cfg_begin_i || dut.cfg_word_valid_i || dut.cfg_commit_i || dut.req_valid_i)
                                $fatal(1,"conflicting command escaped admission mask");
                            tick();
                            if (error_valid || dut.pending_words!==saved_pending ||
                                dut.copy_a.written_words!==0 || dut.copy_b.written_words!==0 ||
                                loading!==(phase==1))
                                $fatal(1,"conflicting commands changed mirrored state");
                        end
                        conflict_checks=conflict_checks+1;
                        @(negedge clk); cancel=1; tick();
                        @(negedge clk); cfg_begin=0; cfg_word_valid=0; cfg_commit=0; req_valid=0; cancel=0;
                    end
                end
            end
            begin_load(8002,4,2,16);
            saved_pending=dut.pending_words;
            @(negedge clk); cfg_begin=1; cfg_epoch=8003; cfg_channels=16;cfg_height=3;cfg_width=40;
            repeat(4) begin
                #1;
                if (cfg_begin_ready || !dut.cfg_begin_i) $fatal(1,"selected valid must not depend on ready");
                tick();
                if (dut.pending_words!==saved_pending || dut.copy_a.pending_epoch!==8002 ||
                    dut.copy_b.pending_epoch!==8002) $fatal(1,"unaccepted begin modified pending geometry");
                blocked_begins=blocked_begins+1;
            end
            @(negedge clk);cancel=1;tick();
            @(negedge clk);cfg_begin=0;cancel=0;tick();
            if(conflict_checks!=22 || blocked_begins!=4) $fatal(1,"admission depth coverage");
            $display("COMMAND_ADMISSION_V4_PASS conflict_subsets=22 held_cycles=66 unaccepted_begin_cycles=4");
        end
    endtask

    integer init_index;
    integer total_words;
    integer total_cases;
    integer capacity_words;
    integer capacity_bytes;

    initial begin
        for (init_index = 0; init_index < 8; init_index = init_index + 1)
            errors_by_code[init_index] = 0;
        $readmemh("feature_banks_4read_cases.hex", case_table);
        $readmemh("feature_banks_4read_load_words.hex", loader_words);
        $readmemh("feature_banks_4read_load_addresses.hex", loader_addresses);
        $readmemh("feature_banks_4read_expected_words.hex", expected_words);

        repeat (3) tick();
        @(negedge clk); rst_n = 1'b1; tick();
        admission_depth_tests();
        total_words = 0;
        total_cases = CASE_COUNT;
        capacity_words = case_table[CASE_COUNT-1][76:63];
        capacity_bytes = capacity_words * 64;
        for (case_index = 0; case_index < CASE_COUNT; case_index = case_index + 1) begin
            run_case(case_index);
            total_words = total_words + case_table[case_index][76:63];
        end
        run_error_tests();

        if (cases_completed != 91 || total_cfg_words != 9920 ||
            request_count != 9920 || response_count != 9920 ||
            checked_bytes != 9920*256 || config_read_rejects != CASE_COUNT ||
            input_conflict_rejections != 1 ||
            cfg_bubble_cycles <= 0 || request_stall_cycles <= 0 ||
            request_stability_checks <= 0 || output_stall_cycles <= 0 ||
            output_stability_checks <= 0 || max_ii1_response_burst < 32 ||
            error_checks != 9 || errors_by_code[1] != 1 || errors_by_code[2] != 2 ||
            errors_by_code[3] != 1 || errors_by_code[4] != 1 || errors_by_code[5] != 1 ||
            errors_by_code[6] != 1 || errors_by_code[7] != 2 || recovery_checks != 5 ||
            global_bad_read_checks != 2 || child_read_suppressions != 2 ||
            child_store_flush_checks != 2 || masked_bad_address_accepts != 1 ||
            total_words != 9920 || capacity_words != 8192 || capacity_bytes != 524288)
            $fatal(1, "coverage gate failed cases=%0d writes=%0d reads=%0d/%0d bytes=%0d reject=%0d conflicts=%0d bubbles=%0d reqstall=%0d/%0d outstall=%0d/%0d II1=%0d errors=%0d recoveries=%0d words=%0d cap=%0d/%0d",
                   cases_completed, total_cfg_words, request_count, response_count,
                   checked_bytes, config_read_rejects, input_conflict_rejections, cfg_bubble_cycles,
                   request_stall_cycles, request_stability_checks,
                   output_stall_cycles, output_stability_checks, max_ii1_response_burst,
                   error_checks, recovery_checks, total_words, capacity_words, capacity_bytes);

        $display("FEATURE_BANKS_4READ_V4_PASS cases=%0d writes=%0d requests=%0d responses=%0d bytes=%0d cfg_read_rejects=%0d conflicts=%0d cfg_bubbles=%0d req_stalls=%0d req_stability=%0d out_stalls=%0d out_stability=%0d ii1_burst=%0d errors=%0d e1=%0d e2=%0d e3=%0d e4=%0d e5=%0d e6=%0d e7=%0d recoveries=%0d capacity_words=%0d capacity_bytes=%0d global_bad_reads=%0d child_suppressed=%0d flushed_copies=%0d masked_bad_accepted=%0d",
                 cases_completed, total_cfg_words, request_count, response_count,
                 checked_bytes, config_read_rejects, input_conflict_rejections, cfg_bubble_cycles,
                 request_stall_cycles, request_stability_checks,
                 output_stall_cycles, output_stability_checks, max_ii1_response_burst,
                 error_checks, errors_by_code[1], errors_by_code[2], errors_by_code[3],
                 errors_by_code[4], errors_by_code[5], errors_by_code[6],
                  errors_by_code[7], recovery_checks, capacity_words, capacity_bytes,
                  global_bad_read_checks, child_read_suppressions,
                  child_store_flush_checks, masked_bad_address_accepts);
        $finish;
    end
endmodule

`default_nettype wire
