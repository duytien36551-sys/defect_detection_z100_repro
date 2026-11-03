`timescale 1ns/1ps
`default_nettype none

module tb_z100_guard_v3_cancel_recovery;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, abort_loader = 0, cancel_guard = 0, recover_loader = 0;
    reg outer_command_start = 0;
    reg context_valid = 1;
    reg [31:0] context_epoch = 7, context_event = 11, context_generation = 3;
    reg cmd_valid = 0;
    wire cmd_ready;
    reg [31:0] cmd_epoch = 7, cmd_event = 11, cmd_generation = 3;
    reg [15:0] cmd_job = 0;
    wire downstream_cmd_valid, downstream_cmd_ready;
    wire [31:0] downstream_cmd_epoch, downstream_cmd_event, downstream_cmd_generation;
    wire [15:0] downstream_cmd_job;
    wire downstream_done_valid, downstream_done_ready, downstream_done_error;
    wire [31:0] downstream_done_epoch, downstream_done_event, downstream_done_generation;
    wire [15:0] downstream_done_job;
    wire done_valid;
    reg done_ready = 0;
    wire [31:0] done_epoch, done_event, done_generation;
    wire [15:0] done_job;
    wire done_error, guard_active, guard_fault;
    wire [2:0] guard_fault_code;

    z100_parameter_residency_guard_v3 residency_guard (
        .clk(clk), .rst_n(rst_n), .cancel(cancel_guard),
        .outer_command_start(outer_command_start),
        .context_valid(context_valid), .context_epoch(context_epoch),
        .context_event(context_event), .context_generation(context_generation),
        .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_epoch(cmd_epoch),
        .cmd_event(cmd_event), .cmd_generation(cmd_generation), .cmd_job(cmd_job),
        .downstream_cmd_valid(downstream_cmd_valid), .downstream_cmd_ready(downstream_cmd_ready),
        .downstream_cmd_epoch(downstream_cmd_epoch), .downstream_cmd_event(downstream_cmd_event),
        .downstream_cmd_generation(downstream_cmd_generation), .downstream_cmd_job(downstream_cmd_job),
        .downstream_done_valid(downstream_done_valid), .downstream_done_ready(downstream_done_ready),
        .downstream_done_epoch(downstream_done_epoch), .downstream_done_event(downstream_done_event),
        .downstream_done_generation(downstream_done_generation), .downstream_done_job(downstream_done_job),
        .downstream_done_error(downstream_done_error), .done_valid(done_valid), .done_ready(done_ready),
        .done_epoch(done_epoch), .done_event(done_event), .done_generation(done_generation),
        .done_job(done_job), .done_error(done_error), .active(guard_active),
        .fault(guard_fault), .fault_code(guard_fault_code)
    );

    wire loader_job_valid, loader_job_ready;
    wire reader_command;
    wire [31:0] reader_epoch, reader_address;
    wire [13:0] reader_words;
    reg reader_busy = 0, reader_fault = 0;
    wire reader_cancel, reader_clear, reader_valid, reader_ready;
    wire [31:0] reader_result_epoch;
    wire [12:0] reader_index;
    wire reader_last;
    wire [511:0] reader_data;
    reg cfg_ready = 0;
    wire cfg_valid;
    wire [3:0] cfg_operation;
    wire [31:0] cfg_epoch, cfg_tag, cfg_index;
    wire [10:0] cfg_groups;
    wire [5:0] cfg_lanes;
    wire [1023:0] cfg_data;
    reg cfg_response_valid = 0, hold_cfg_response = 0, pending_cfg_response = 0;
    reg [31:0] pending_cfg_tag = 0;
    wire cfg_response_ready;
    reg [31:0] cfg_response_tag = 0;
    reg cfg_response_error = 0, cfg_fault = 0, cfg_configured = 0;
    wire cfg_cancel, loader_active, loader_fault, loader_done;
    wire [3:0] loader_fault_code;
    reg model_reading = 0, hold_reader = 0, drain_mode = 0;
    reg [12:0] model_index = 0;
    reg [13:0] model_words = 0;
    wire reader_quiet;
    integer loader_job_accepts = 0, reader_command_count = 0, cfg_accept_count = 0;

    assign downstream_cmd_ready = loader_job_ready;
    assign loader_job_valid = downstream_cmd_valid;
    assign downstream_done_valid = loader_done;
    assign downstream_done_epoch = context_epoch;
    assign downstream_done_event = context_event;
    assign downstream_done_generation = context_generation;
    assign downstream_done_job = cmd_job;
    assign downstream_done_error = loader_fault || reader_fault || cfg_fault;
    assign reader_result_epoch = reader_epoch;
    assign reader_valid = model_reading && !hold_reader;
    assign reader_index = model_index;
    assign reader_last = reader_index + 1 == model_words;
    assign reader_data = {16{32'hcafebabe}};
    assign reader_quiet = !reader_busy;

    z100_native_parameter_reader actual_parameter_loader (
        .clk(clk), .rst_n(rst_n), .abort(abort_loader), .recover(recover_loader),
        .job_valid(loader_job_valid), .job_ready(loader_job_ready),
        .job_epoch(downstream_cmd_epoch), .job_timeout(32'd50000),
        .job_groups(11'd1), .job_lanes(6'd1), .job_weights(32'h1000),
        .job_bias(32'h2000), .job_factors(32'h3000), .job_unary(32'h4000),
        .reader_command(reader_command), .reader_command_ready(!reader_busy),
        .reader_epoch(reader_epoch), .reader_address(reader_address), .reader_words(reader_words),
        .reader_busy(reader_busy), .reader_fault(reader_fault), .reader_cancel(reader_cancel),
        .reader_clear(reader_clear), .reader_valid(reader_valid), .reader_ready(reader_ready),
        .reader_result_epoch(reader_result_epoch), .reader_index(reader_index),
        .reader_last(reader_last), .reader_data(reader_data),
        .cfg_valid(cfg_valid), .cfg_ready(cfg_ready), .cfg_operation(cfg_operation),
        .cfg_epoch(cfg_epoch), .cfg_tag(cfg_tag), .cfg_index(cfg_index),
        .cfg_groups(cfg_groups), .cfg_lanes(cfg_lanes), .cfg_data(cfg_data),
        .cfg_response_valid(cfg_response_valid), .cfg_response_ready(cfg_response_ready),
        .cfg_response_tag(cfg_response_tag), .cfg_response_error(cfg_response_error),
        .cfg_fault(cfg_fault), .cfg_configured(cfg_configured), .cfg_cancel(cfg_cancel),
        .active(loader_active), .fault(loader_fault), .fault_code(loader_fault_code), .done(loader_done)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            reader_busy <= 0; model_reading <= 0; model_index <= 0; model_words <= 0;
            drain_mode <= 0; cfg_response_valid <= 0; cfg_response_tag <= 0;
            cfg_configured <= 0; pending_cfg_response <= 0; pending_cfg_tag <= 0;
            loader_job_accepts <= 0; reader_command_count <= 0;
            cfg_accept_count <= 0;
        end else begin
            if (loader_job_valid && loader_job_ready)
                loader_job_accepts <= loader_job_accepts + 1;
            if (reader_command && !reader_busy) begin
                reader_busy <= 1; model_reading <= 1; model_index <= 0;
                model_words <= reader_words; drain_mode <= 0;
                reader_command_count <= reader_command_count + 1;
            end
            if (reader_cancel)
                drain_mode <= 1;
            if (model_reading && !hold_reader &&
                (reader_cancel || drain_mode || (reader_valid && reader_ready))) begin
                if (model_index + 1 >= model_words) begin
                    model_reading <= 0; reader_busy <= 0; model_index <= 0; drain_mode <= 0;
                end else begin
                    model_index <= model_index + 1;
                end
            end
            if (cfg_response_valid && cfg_response_ready) begin
                cfg_response_valid <= 0;
                if (cfg_operation == 4'd8)
                    cfg_configured <= 1;
            end else if (cfg_valid && cfg_ready) begin
                cfg_accept_count <= cfg_accept_count + 1;
                if (hold_cfg_response) begin
                    pending_cfg_response <= 1;
                    pending_cfg_tag <= cfg_tag;
                end else begin
                    cfg_response_valid <= 1;
                    cfg_response_tag <= cfg_tag;
                end
            end
            if (pending_cfg_response && !hold_cfg_response && !cfg_response_valid) begin
                cfg_response_valid <= 1;
                cfg_response_tag <= pending_cfg_tag;
                pending_cfg_response <= 0;
            end
            if (cfg_cancel) begin
                cfg_response_valid <= 0;
                pending_cfg_response <= 0;
            end
        end
    end

    integer checks = 0, failures = 0;
    task check(input condition, input [8*120-1:0] label);
        begin
            checks = checks + 1;
            if (!condition) begin $display("FAIL %0s", label); failures = failures + 1; end
        end
    endtask

    task issue_command(input [15:0] job, input expected_hit);
        begin
            @(negedge clk); cmd_job = job; cmd_valid = 1; #1;
            check(cmd_ready, "guard command ready");
            check(downstream_cmd_valid == !expected_hit,
                  expected_hit ? "cache hit suppresses loader command" : "cache miss forwards to loader");
            @(posedge clk); #1; cmd_valid = 0;
        end
    endtask

    task finish_stalled_completion;
        integer i;
        reg saw_loader_pulse, saw_buffered;
        begin
            saw_loader_pulse = 0; saw_buffered = 0; done_ready = 0;
            for (i = 0; i < 30000; i = i + 1) begin
                @(negedge clk);
                if (loader_done) saw_loader_pulse = 1;
                if (saw_loader_pulse && done_valid && !loader_done) begin
                    saw_buffered = 1;
                    check(done_epoch == context_epoch && done_event == context_event &&
                          done_generation == context_generation && done_job == cmd_job,
                          "buffered completion keeps accepted loader identity");
                    check(!done_error, "loader completion succeeds without error");
                    i = 30000;
                end
            end
            check(saw_loader_pulse, "actual loader emits one-cycle done pulse");
            check(saw_buffered, "guard holds completion after source pulse disappears");
            if (!saw_buffered) $fatal(1, "timeout waiting for guarded completion");
            repeat (2) begin
                @(negedge clk);
                check(done_valid && !loader_done, "consumer stall holds completion");
            end
            done_ready = 1; @(posedge clk); #1; done_ready = 0;
            check(!done_valid, "guard retires completion after consumer accepts");
        end
    endtask

    task wait_for_reader_busy;
        integer i;
        reg observed;
        begin
            observed = 0;
            for (i = 0; i < 2000; i = i + 1) begin
                @(negedge clk);
                if (reader_busy) begin observed = 1; i = 2000; end
            end
            check(observed, "loader starts parameter reader transaction");
            if (!observed) $fatal(1, "timeout waiting for reader transaction");
        end
    endtask

    task wait_for_loader_state(input [3:0] wanted, input integer limit, input [8*80-1:0] label);
        integer i;
        reg found;
        begin
            found = 0;
            for (i = 0; i < limit; i = i + 1) begin
                @(negedge clk);
                if (actual_parameter_loader.state == wanted) begin found = 1; i = limit; end
            end
            check(found, label);
            if (!found) $fatal(1, "timeout waiting for loader state %0d", wanted);
        end
    endtask

    task recover_loader_after_cancel(input integer needs_reader_drain, input [8*80-1:0] phase_label);
        integer i;
        reg failed_state, drained;
        begin
            @(negedge clk); abort_loader = 1; cancel_guard = 1; #1;
            check(cfg_cancel, "cancel aborts loader configuration ownership");
            check(!done_valid && !downstream_done_ready,
                  "cancel suppresses public and lower completion handshakes");
            if (needs_reader_drain) begin
                check(reader_cancel && reader_busy && !reader_quiet,
                      "cancel keeps held read transaction owned");
            end else begin
                check(reader_quiet, "config-stage cancel has no outstanding reader transaction");
            end
            @(posedge clk); #1; abort_loader = 0; cancel_guard = 0;
            if (needs_reader_drain) begin
                check(reader_busy && !reader_quiet,
                      "reader ownership persists after logical abort");
                @(negedge clk); hold_reader = 0;
                drained = 0;
                for (i = 0; i < 32; i = i + 1) begin
                    @(negedge clk);
                    if (!reader_busy) begin drained = 1; i = 32; end
                    else check(!reader_quiet, "quiet proxy remains closed until held beats drain");
                end
                check(drained && reader_quiet, "held read response drains before recovery");
                if (!drained) $fatal(1, "reader drain timeout after %0s", phase_label);
            end
            failed_state = 0;
            for (i = 0; i < 16; i = i + 1) begin
                @(negedge clk);
                if (actual_parameter_loader.state == 4'd8) begin failed_state = 1; i = 16; end
            end
            check(failed_state && loader_fault, "loader reaches FAILED after cancellation drain");
            if (!failed_state) $fatal(1, "loader failed to reach recovery state after %0s", phase_label);
            @(negedge clk); recover_loader = 1;
            @(posedge clk); #1; recover_loader = 0;
            check(actual_parameter_loader.state == 4'd9,
                  "recover request advances FAILED to CLEAR");
            @(posedge clk); #1;
            check(actual_parameter_loader.state == 4'd0 && !loader_fault && !reader_busy,
                  "recovery returns loader to idle only after drain");
            check(!guard_active && !guard_fault && !done_valid,
                  "cancelled request is not published and guard is reusable");
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        @(negedge clk); rst_n = 1;

        // SEND: hold cfg_ready low so cancellation occurs while cfg_valid is
        // asserted and the config bridge has not accepted the command.
        issue_command(16'd4, 0);
        wait_for_loader_state(4'd1, 8, "loader enters SEND");
        check(cfg_valid && !cfg_ready && !reader_busy,
              "SEND phase is held under configuration backpressure");
        recover_loader_after_cancel(0, "SEND");
        check(loader_job_accepts == 1 && reader_command_count == 0,
              "SEND cancel launches no parameter read");

        // REPLY: accept a config command but withhold its response so the
        // loader owns an outstanding bridge transaction when aborted.
        cfg_ready = 1; hold_cfg_response = 1;
        issue_command(16'd5, 0);
        wait_for_loader_state(4'd2, 8, "loader enters REPLY");
        check(!cfg_valid && pending_cfg_response && !cfg_response_valid,
              "REPLY phase waits on the withheld config response");
        recover_loader_after_cancel(0, "REPLY");
        hold_cfg_response = 0;
        check(!pending_cfg_response && reader_command_count == 0,
              "REPLY cancel discards modeled response and launches no read");
        check(loader_job_accepts == 2, "second loader job accepted after SEND recovery");

        // COLLECT: acknowledge three setup operations, accept the real loader's
        // parameter read, then withhold its response beats while cancelling.
        hold_reader = 1;
        issue_command(16'd6, 0);
        wait_for_loader_state(4'd4, 64, "loader enters COLLECT");
        check(reader_busy && reader_valid == 0 && reader_ready && !reader_quiet,
              "COLLECT phase has an owned but backpressured read response");
        recover_loader_after_cancel(1, "COLLECT");
        check(reader_command_count == 1 && loader_job_accepts == 3,
              "COLLECT cancel owns exactly one loader read command");

        // Reuse after two config-stage aborts and a drained read-stage abort.
        // A complete transaction proves recovery is repeatable, not just a
        // state-code transition.
        issue_command(16'd7, 0);
        finish_stalled_completion();
        check(!loader_fault && !guard_fault && !reader_busy && reader_quiet,
              "post-recovery parameter transaction completes cleanly");
        check(reader_command_count == 5 && loader_job_accepts == 4,
              "post-recovery transaction reads all four segments");
        check(!done_valid, "successful completion retires after recovery test");

        if (failures != 0)
            $fatal(1, "Z100_GUARD_V3_CANCEL_RECOVERY_FAIL checks=%0d failures=%0d", checks, failures);
        $display("Z100_GUARD_V3_CANCEL_RECOVERY_PASS checks=%0d loader_jobs=%0d reader_commands=%0d cfg_commands=%0d",
                 checks, loader_job_accepts, reader_command_count, cfg_accept_count);
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "testbench global timeout");
    end
endmodule

`default_nettype wire
