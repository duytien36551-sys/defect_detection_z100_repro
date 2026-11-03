`timescale 1ns/1ps
module tb_z100_parameter_residency_v1;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, cancel = 0, context_valid = 1;
    reg [31:0] context_epoch = 32'd7, context_event = 32'd11,
               context_generation = 32'd3;
    reg cmd_valid = 0;
    wire cmd_ready;
    reg [31:0] cmd_epoch = 32'd7, cmd_event = 32'd11,
               cmd_generation = 32'd3;
    reg [15:0] cmd_job = 16'd4;
    wire downstream_cmd_valid;
    reg downstream_cmd_ready = 1;
    wire [31:0] downstream_cmd_epoch, downstream_cmd_event,
                downstream_cmd_generation;
    wire [15:0] downstream_cmd_job;
    reg downstream_done_valid = 0, downstream_done_error = 0;
    wire downstream_done_ready;
    reg [31:0] downstream_done_epoch = 0, downstream_done_event = 0,
               downstream_done_generation = 0;
    reg [15:0] downstream_done_job = 0;
    wire done_valid;
    reg done_ready = 1;
    wire [31:0] done_epoch, done_event, done_generation;
    wire [15:0] done_job;
    wire done_error, active, fault;
    wire [2:0] fault_code;
    integer checks = 0;
    integer failures = 0;

    z100_parameter_residency_v1 dut (.*);

    task check(input condition, input [1023:0] name);
        begin
            checks = checks + 1;
            if (!condition) begin
                $display("FAIL %0s", name);
                failures = failures + 1;
            end
        end
    endtask

    task reset_case;
        begin
            @(negedge clk);
            rst_n = 0;
            cancel = 0;
            cmd_valid = 0;
            downstream_done_valid = 0;
            downstream_done_error = 0;
            downstream_cmd_ready = 1;
            done_ready = 1;
            context_valid = 1;
            context_epoch = 7; cmd_epoch = 7;
            context_event = 11; cmd_event = 11;
            context_generation = 3; cmd_generation = 3;
            @(negedge clk);
            rst_n = 1;
        end
    endtask

    task present_completion(input [15:0] job, input error);
        begin
            downstream_done_epoch = 7;
            downstream_done_event = 11;
            downstream_done_generation = 3;
            downstream_done_job = job;
            downstream_done_error = error;
            downstream_done_valid = 1;
            #1;
        end
    endtask

    task issue(input [15:0] job, input expect_downstream);
        begin
            cmd_job = job;
            cmd_valid = 1;
            #1;
            check(cmd_ready, "command accepted");
            check(downstream_cmd_valid == expect_downstream,
                  expect_downstream ? "miss forwards downstream" : "hit suppresses downstream");
            @(posedge clk);
            #1;
            cmd_valid = 0;
        end
    endtask

    task complete_downstream(input [15:0] job, input error);
        begin
            downstream_done_epoch = cmd_epoch;
            downstream_done_event = cmd_event;
            downstream_done_generation = cmd_generation;
            downstream_done_job = job;
            downstream_done_error = error;
            downstream_done_valid = 1;
            check(downstream_done_ready, "downstream completion accepted");
            @(posedge clk);
            #1;
            downstream_done_valid = 0;
            downstream_done_error = 0;
            @(posedge clk);
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        rst_n = 1;
        issue(16'd4, 1);
        complete_downstream(16'd4, 0);
        check(!fault && !done_valid, "miss completion stores resident entry");

        issue(16'd4, 0);
        #1 check(done_valid && done_job == 16'd4 && !done_error,
                 "resident hit completes without downstream");
        @(posedge clk);
        #1 check(!done_valid, "hit completion is one cycle");

        issue(16'd5, 1);
        complete_downstream(16'd5, 0);
        issue(16'd4, 1);
        complete_downstream(16'd4, 0);

        context_generation = 32'd4;
        cmd_generation = 32'd4;
        issue(16'd4, 1);
        complete_downstream(16'd4, 0);

        cancel = 1;
        @(posedge clk);
        cancel = 0;
        context_generation = 32'd3;
        cmd_generation = 32'd3;
        issue(16'd4, 1);
        complete_downstream(16'd4, 1);
        check(!fault, "downstream error clears entry without poisoning");

        cmd_generation = 32'd9;
        context_generation = 32'd8;
        cmd_valid = 1;
        #1 check(!cmd_ready, "context mismatch is not accepted");
        @(posedge clk);
        #1 check(fault && fault_code == 3'd3, "context mismatch faults closed");
        cmd_valid = 0;

        // Rejected context must never be accepted by the downstream loader,
        // including while its ready input is stalled.
        reset_case();
        cmd_valid = 1;
        context_valid = 0;
        downstream_cmd_ready = 0;
        #1 check(!cmd_ready && !downstream_cmd_valid,
                 "invalid context suppresses both handshake sides under stall");
        downstream_cmd_ready = 1;
        #1 check(!cmd_ready && !downstream_cmd_valid,
                 "invalid context cannot launch downstream");
        @(posedge clk);
        #1;
        check(fault && fault_code == 3'd3, "invalid context records context fault");

        reset_case();
        cmd_valid = 1;
        cmd_event = 12;
        #1 check(!cmd_ready && !downstream_cmd_valid,
                 "mismatched event cannot launch downstream");

        // An unowned completion takes priority over a concurrent command.
        reset_case();
        cmd_valid = 1;
        present_completion(4, 0);
        check(!cmd_ready && !downstream_cmd_valid && !done_valid,
              "idle unexpected completion prevents new command acceptance");
        @(posedge clk);
        #1;
        check(fault && fault_code == 1, "idle unexpected completion faults");

        // A bad completion is consumed and faults even if upstream stalls;
        // its foreign identity must never be published to the tile owner.
        reset_case();
        issue(4, 1);
        done_ready = 0;
        present_completion(5, 0);
        check(!done_valid && downstream_done_ready,
              "mismatched completion is drained without upstream publication");
        check(done_epoch == 7 && done_event == 11 &&
              done_generation == 3 && done_job == 4,
              "completion metadata retains accepted request identity");
        @(posedge clk);
        #1;
        check(fault && fault_code == 2, "mismatched completion faults despite upstream stall");

        // Correct completions retain the accepted identity while caller bus
        // inputs change and the consumer applies backpressure.
        reset_case();
        issue(4, 1);
        cmd_epoch = 91; cmd_event = 92; cmd_generation = 93; cmd_job = 94;
        done_ready = 0;
        present_completion(4, 1);
        check(done_valid && done_error && !downstream_done_ready,
              "error completion respects consumer backpressure");
        repeat (3) begin
            @(posedge clk);
        #1;
            check(done_valid && done_error && done_epoch == 7 &&
                  done_event == 11 && done_generation == 3 && done_job == 4 &&
                  !cmd_ready && !downstream_cmd_valid,
                  "stalled completion retains ownership and accepted metadata");
        end
        done_ready = 1;
        @(posedge clk);
        #1;
        downstream_done_valid = 0;
        downstream_done_error = 0;
        cmd_epoch = 7; cmd_event = 11; cmd_generation = 3;
        issue(4, 1);
        complete_downstream(4, 0);

        // Cancellation suppresses a resident-hit completion immediately.
        done_ready = 0;
        issue(4, 0);
        check(done_valid, "hit completion can be stalled");
        cancel = 1;
        #1 check(!done_valid && !downstream_done_ready && !cmd_ready &&
                 !downstream_cmd_valid, "cancel suppresses pending hit publication");
        @(posedge clk);
        #1;
        cancel = 0;
        check(!done_valid && !active, "cancel clears logical hit owner");

        reset_case();
        issue(4, 1);
        present_completion(4, 0);
        cancel = 1;
        #1 check(!done_valid && !downstream_done_ready,
                 "cancel suppresses simultaneous miss completion");
        @(posedge clk);
        #1;
        cancel = 0;
        cmd_valid = 1;
        #1 check(!cmd_ready && !downstream_cmd_valid,
                 "post-cancel stale completion cannot admit replacement command");
        @(posedge clk);
        #1;
        check(fault && fault_code == 1, "post-cancel stale completion faults closed");

        reset_case();
        issue(4, 1);
        present_completion(4, 0);
        rst_n = 0;
        #1 check(!done_valid && !downstream_done_ready && !cmd_ready &&
                 !downstream_cmd_valid, "reset suppresses all transaction handshakes");

        // A downstream completion during a cache hit has no downstream owner.
        reset_case();
        issue(4, 1);
        complete_downstream(4, 0);
        done_ready = 0;
        issue(4, 0);
        present_completion(4, 0);
        check(!done_valid && !downstream_done_ready,
              "unowned downstream completion cannot alias a cache hit");
        @(posedge clk);
        #1;
        check(fault && fault_code == 1, "unexpected hit-time completion faults closed");

        if (failures != 0)
            $fatal(1, "Z100_PARAMETER_RESIDENCY_V1_FAIL checks=%0d failures=%0d", checks, failures);
        $display("Z100_PARAMETER_RESIDENCY_V1_PASS checks=%0d baseline_checks=23 ownership_regressions=1", checks);
        $finish(0);
    end
endmodule
