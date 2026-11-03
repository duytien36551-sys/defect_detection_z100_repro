`timescale 1ns/1ps

module tb_z100_tile_reuse_resident_v3;
    localparam integer MAX_TAPS = 4091;
    localparam [31:0] SCHEMA = 32'h5a523301;
    localparam [3:0] OP_WEIGHT_BEGIN  = 4'd1;
    localparam [3:0] OP_WEIGHT_DATA   = 4'd2;
    localparam [3:0] OP_BIAS_DATA     = 4'd3;
    localparam [3:0] OP_WEIGHT_COMMIT = 4'd4;
    localparam [3:0] OP_ACT_BEGIN     = 4'd5;
    localparam [3:0] OP_ACT_DATA      = 4'd6;
    localparam [3:0] OP_ACT_COMMIT    = 4'd7;
    localparam [3:0] OP_RUN           = 4'd8;
    localparam [3:0] OP_CANCEL        = 4'd9;

    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;

    reg cmd_valid = 0;
    wire cmd_ready;
    reg [31:0] cmd_schema = SCHEMA;
    reg [3:0] cmd_opcode = 0;
    reg [31:0] cmd_weight_epoch = 0;
    reg [31:0] cmd_activation_epoch = 0;
    reg [11:0] cmd_addr = 0;
    reg [12:0] cmd_tap_count = 0;
    reg [5:0] cmd_lane_count = 0;
    reg [2:0] cmd_site_count = 0;
    reg [3:0] cmd_site_mask = 0;
    reg [1023:0] cmd_payload = 0;

    wire [31:0] schema_id;
    wire error_valid;
    wire [3:0] error_code;
    wire weight_valid;
    wire activation_valid;
    wire [31:0] active_weight_epoch;
    wire [31:0] active_activation_epoch;
    wire busy;
    wire out_valid;
    reg out_ready = 0;
    wire [1:0] out_site;
    wire out_last;
    wire [5:0] out_lane_count;
    wire [1023:0] out_data;
    wire [31:0] out_overflow;

    z100_tile_reuse_resident_v3 #(.MAX_TAPS(MAX_TAPS)) dut (
        .clk(clk), .rst_n(rst_n), .cmd_valid(cmd_valid), .cmd_ready(cmd_ready),
        .cmd_schema(cmd_schema), .cmd_opcode(cmd_opcode),
        .cmd_weight_epoch(cmd_weight_epoch),
        .cmd_activation_epoch(cmd_activation_epoch), .cmd_addr(cmd_addr),
        .cmd_tap_count(cmd_tap_count), .cmd_lane_count(cmd_lane_count),
        .cmd_site_count(cmd_site_count), .cmd_site_mask(cmd_site_mask),
        .cmd_payload(cmd_payload), .schema_id(schema_id), .error_valid(error_valid),
        .error_code(error_code), .weight_valid(weight_valid),
        .activation_valid(activation_valid), .active_weight_epoch(active_weight_epoch),
        .active_activation_epoch(active_activation_epoch), .busy(busy),
        .out_valid(out_valid), .out_ready(out_ready), .out_site(out_site),
        .out_last(out_last), .out_lane_count(out_lane_count),
        .out_data(out_data), .out_overflow(out_overflow)
    );

    reg signed [7:0] weight_values [0:31][0:MAX_TAPS-1];
    reg signed [7:0] activation_values [0:3][0:MAX_TAPS-1];
    reg signed [31:0] bias_values [0:31];
    reg [31:0] expected_values [0:31][0:3];
    reg expected_overflow [0:31][0:3];

    integer cycle_counter = 0;
    integer command_counter = 0;
    integer weight_data_commands = 0;
    integer group_issues = 0;
    integer failed = 0;
    reg [31:0] random_state = 32'h8e31a92d;

    always @(posedge clk) begin
        cycle_counter = cycle_counter + 1;
        if (rst_n && dut.datapath.issue_group)
            group_issues = group_issues + 1;
    end

    function [31:0] next_random;
        reg [31:0] x;
        begin
            x = random_state;
            x = x ^ (x << 13);
            x = x ^ (x >> 17);
            x = x ^ (x << 5);
            random_state = x;
            next_random = x;
        end
    endfunction

    function [31:0] clamp64;
        input signed [63:0] value;
        begin
            if (value > 64'sh000000007fffffff)
                clamp64 = 32'h7fffffff;
            else if (value < -64'sh0000000080000000)
                clamp64 = 32'h80000000;
            else
                clamp64 = value[31:0];
        end
    endfunction

    task fail;
        input [8*240-1:0] message;
        begin
            $display("FAIL: %0s cycle=%0d", message, cycle_counter);
            failed = failed + 1;
            $finish(1);
        end
    endtask

    task send_command;
        input [3:0] opcode;
        input [31:0] weight_epoch;
        input [31:0] activation_epoch;
        input [11:0] address;
        input [12:0] taps;
        input [5:0] lanes;
        input [2:0] sites;
        input [3:0] site_mask;
        input [1023:0] payload;
        input [31:0] schema;
        integer watchdog;
        reg accepted;
        begin
            @(negedge clk);
            cmd_opcode = opcode;
            cmd_weight_epoch = weight_epoch;
            cmd_activation_epoch = activation_epoch;
            cmd_addr = address;
            cmd_tap_count = taps;
            cmd_lane_count = lanes;
            cmd_site_count = sites;
            cmd_site_mask = site_mask;
            cmd_payload = payload;
            cmd_schema = schema;
            cmd_valid = 1;
            watchdog = 0;
            accepted = 0;
            while (!accepted && watchdog < 100000) begin
                @(posedge clk);
                if (cmd_ready) begin
                    accepted = 1;
                    command_counter = command_counter + 1;
                    if (opcode == OP_WEIGHT_DATA)
                        weight_data_commands = weight_data_commands + 1;
                end
                watchdog = watchdog + 1;
            end
            if (!accepted)
                fail("command ingress watchdog expired");
            @(negedge clk);
            cmd_valid = 0;
        end
    endtask

    task expect_error;
        input [3:0] opcode;
        input [31:0] weight_epoch;
        input [31:0] activation_epoch;
        input [11:0] address;
        input [12:0] taps;
        input [5:0] lanes;
        input [2:0] sites;
        input [3:0] site_mask;
        input [1023:0] payload;
        input [31:0] schema;
        input [3:0] expected_code;
        begin
            send_command(opcode, weight_epoch, activation_epoch, address,
                         taps, lanes, sites, site_mask, payload, schema);
            if (!error_valid || error_code !== expected_code) begin
                $display("ERROR_MISMATCH opcode=%0d expected_valid=1 expected_code=%0d actual_valid=%b actual_code=%0d weight_valid=%b activation_valid=%b busy=%b active_weight=%0d active_activation=%0d",
                    opcode, expected_code, error_valid, error_code, weight_valid,
                    activation_valid, busy, active_weight_epoch, active_activation_epoch);
                fail("invalid command was not rejected with expected code");
            end
        end
    endtask

    task expect_success;
        input [3:0] opcode;
        input [31:0] weight_epoch;
        input [31:0] activation_epoch;
        input [11:0] address;
        input [12:0] taps;
        input [5:0] lanes;
        input [2:0] sites;
        input [3:0] site_mask;
        input [1023:0] payload;
        begin
            send_command(opcode, weight_epoch, activation_epoch, address,
                         taps, lanes, sites, site_mask, payload, SCHEMA);
            if (error_valid)
                fail("valid command raised an error");
        end
    endtask

    task build_weight_epoch;
        input integer taps;
        input [31:0] epoch;
        input integer mode;
        input integer begin_epoch;
        integer lane;
        integer tap;
        reg [1023:0] payload;
        reg [31:0] rv;
        integer first_cycle;
        integer last_cycle;
        integer command_start;
        begin
            first_cycle = cycle_counter;
            command_start = command_counter;
            if (begin_epoch)
                expect_success(OP_WEIGHT_BEGIN, epoch, 0, 0, taps, 0, 0, 0, 0);
            payload = 0;
            for (lane = 0; lane < 32; lane = lane + 1) begin
                rv = next_random();
                if ((mode == 1) || (mode == 3))
                    bias_values[lane] = (mode == 3) ? 32'sh7fffc17f : 32'sh7fffff00;
                else if (mode == 4)
                    bias_values[lane] = 32'sd2147433647;
                else if (mode == 2)
                    bias_values[lane] = -32'sh7fffff00;
                else
                    bias_values[lane] = rv;
            end
            for (tap = 0; tap < taps; tap = tap + 1) begin
                payload = 0;
                for (lane = 0; lane < 32; lane = lane + 1) begin
                    rv = next_random();
                    if ((mode == 1) || (mode == 4))
                        weight_values[lane][tap] = 8'sd127;
                    else if ((mode == 2) || (mode == 3))
                        weight_values[lane][tap] = 8'sd127;
                    else if ((tap % 17) == 0)
                        weight_values[lane][tap] = -8'sd128;
                    else
                        weight_values[lane][tap] = rv[7:0];
                    payload[(lane * 8) +: 8] = weight_values[lane][tap];
                end
                expect_success(OP_WEIGHT_DATA, epoch, 0, tap, taps, 0, 0, 0, payload);
            end
            payload = 0;
            for (lane = 0; lane < 32; lane = lane + 1)
                payload[(lane * 32) +: 32] = bias_values[lane];
            expect_success(OP_BIAS_DATA, epoch, 0, 0, taps, 0, 0, 0, payload);
            expect_success(OP_WEIGHT_COMMIT, epoch, 0, 0, taps, 0, 0, 0, 0);
            last_cycle = cycle_counter;
            if (!weight_valid || (active_weight_epoch != epoch))
                fail("weight epoch commit did not establish valid weights");
            $display("LOAD_METRIC kind=weights epoch=%0d taps=%0d data_bytes=%0d bias_bytes=128 commands=%0d cycles=%0d",
                epoch, taps, taps * 32, command_counter - command_start,
                last_cycle - first_cycle);
        end
    endtask

    task build_activation_epoch;
        input integer taps;
        input integer sites;
        input [31:0] weight_epoch;
        input [31:0] activation_epoch;
        input integer mode;
        input integer begin_epoch;
        integer site;
        integer tap;
        integer first_cycle;
        integer last_cycle;
        integer command_start;
        reg [1023:0] payload;
        reg [31:0] rv;
        begin
            first_cycle = cycle_counter;
            command_start = command_counter;
            if (begin_epoch)
                expect_success(OP_ACT_BEGIN, weight_epoch, activation_epoch,
                               0, taps, 0, sites, 0, 0);
            for (tap = 0; tap < taps; tap = tap + 1) begin
                payload = 0;
                for (site = 0; site < 4; site = site + 1) begin
                    rv = next_random();
                    if (site >= sites)
                        activation_values[site][tap] = 0;
                    else if (mode == 1)
                        activation_values[site][tap] = 8'sd127;
                    else if (mode == 2)
                        activation_values[site][tap] = -8'sd128;
                    else if ((mode == 3) && ((tap & 1) == 0))
                        activation_values[site][tap] = 8'sd127;
                    else if (mode == 3)
                        activation_values[site][tap] = -8'sd128;
                    else if (mode == 4)
                        activation_values[site][tap] = (tap < 4) ? 8'sd127 : -8'sd128;
                    else
                        activation_values[site][tap] = rv[7:0];
                    payload[(site * 8) +: 8] = activation_values[site][tap];
                end
                expect_success(OP_ACT_DATA, weight_epoch, activation_epoch,
                               tap, taps, 0, sites, (1 << sites) - 1, payload);
            end
            expect_success(OP_ACT_COMMIT, weight_epoch, activation_epoch,
                           0, taps, 0, sites, 0, 0);
            last_cycle = cycle_counter;
            if (!activation_valid || (active_activation_epoch != activation_epoch))
                fail("activation epoch commit did not establish valid tile");
            $display("LOAD_METRIC kind=activations epoch=%0d taps=%0d sites=%0d payload_bytes=%0d valid_bytes=%0d commands=%0d cycles=%0d",
                activation_epoch, taps, sites, taps * 4, taps * sites,
                command_counter - command_start, last_cycle - first_cycle);
        end
    endtask

    task build_scalar_reference;
        input integer taps;
        input integer sites;
        input integer lanes;
        integer lane;
        integer site;
        integer tap;
        reg signed [63:0] accum;
        reg signed [15:0] product;
        begin
            for (lane = 0; lane < 32; lane = lane + 1) begin
                for (site = 0; site < 4; site = site + 1) begin
                    if ((lane >= lanes) || (site >= sites)) begin
                        expected_values[lane][site] = 0;
                        expected_overflow[lane][site] = 0;
                    end else begin
                        accum = bias_values[lane];
                        for (tap = 0; tap < taps; tap = tap + 1) begin
                            product = $signed(activation_values[site][tap]) *
                                      $signed(weight_values[lane][tap]);
                            accum = accum + product;
                        end
                        expected_values[lane][site] = clamp64(accum);
                        expected_overflow[lane][site] =
                            (accum > 64'sh000000007fffffff) ||
                            (accum < -64'sh0000000080000000);
                    end
                end
            end
        end
    endtask

    task check_site;
        input integer expected_site;
        input integer lanes;
        integer lane;
        begin
            if (!out_valid)
                fail("result valid dropped during serialized drain");
            if (out_site !== expected_site[1:0])
                fail("serialized output site order mismatch");
            if (out_last !== (expected_site == (dut.expected_activation_sites - 1)))
                fail("serialized output last marker mismatch");
            if (out_lane_count !== lanes[5:0])
                fail("serialized output lane count mismatch");
            for (lane = 0; lane < 32; lane = lane + 1) begin
                if (out_data[(lane * 32) +: 32] !== expected_values[lane][expected_site]) begin
                    $display("SCALAR_MISMATCH site=%0d lane=%0d actual=%08x expected=%08x",
                        expected_site, lane, out_data[(lane * 32) +: 32],
                        expected_values[lane][expected_site]);
                    fail("independent scalar output mismatch");
                end
                if (out_overflow[lane] !== expected_overflow[lane][expected_site])
                    fail("signed32 overflow flag mismatch");
            end
        end
    endtask

    task drain_and_compare;
        input integer sites;
        input integer lanes;
        integer site;
        integer watchdog;
        integer stall;
        reg [1023:0] held_data;
        reg [31:0] held_overflow;
        reg [1:0] held_site;
        reg [5:0] held_lane_count;
        begin
            out_ready = 0;
            for (site = 0; site < sites; site = site + 1) begin
                watchdog = 0;
                while (!out_valid && watchdog < 200000) begin
                    @(negedge clk);
                    watchdog = watchdog + 1;
                end
                if (!out_valid)
                    fail("serialized output watchdog expired");
                held_data = out_data;
                held_overflow = out_overflow;
                held_site = out_site;
                held_lane_count = out_lane_count;
                for (stall = 0; stall < (site % 3) + 2; stall = stall + 1) begin
                    @(posedge clk);
                    if (!out_valid || out_data !== held_data ||
                        out_overflow !== held_overflow || out_site !== held_site ||
                        out_lane_count !== held_lane_count)
                        fail("result changed while backpressured");
                    @(negedge clk);
                    out_ready = 0;
                end
                check_site(site, lanes);
                out_ready = 1;
                @(posedge clk);
                check_site(site, lanes);
                @(negedge clk);
                out_ready = 0;
            end
            if (out_valid || busy)
                fail("completed run did not return to idle");
        end
    endtask

    task run_and_compare;
        input integer taps;
        input integer sites;
        input integer lanes;
        input [31:0] weight_epoch;
        input [31:0] activation_epoch;
        input [8*24-1:0] label;
        integer start_cycle;
        integer before_groups;
        integer end_cycle;
        integer expected_groups;
        begin
            build_scalar_reference(taps, sites, lanes);
            start_cycle = cycle_counter;
            before_groups = group_issues;
            expect_success(OP_RUN, weight_epoch, activation_epoch,
                           0, taps, lanes, sites, 0, 0);
            drain_and_compare(sites, lanes);
            end_cycle = cycle_counter;
            expected_groups = (taps + 3) / 4;
            if ((group_issues - before_groups) != expected_groups)
                fail("compute group cycle count does not match ceil(taps/4)");
            $display("CASE_METRIC label=%0s taps=%0d groups=%0d lanes=%0d sites=%0d start_to_last_result_cycles=%0d issue_cycles=%0d result_bus_bytes=%0d useful_result_bytes=%0d status=PASS",
                label, taps, expected_groups, lanes, sites, end_cycle - start_cycle,
                group_issues - before_groups, sites * 128, sites * lanes * 4);
        end
    endtask

    task wait_for_issue_count;
        input integer target;
        integer watchdog;
        begin
            watchdog = 0;
            while ((group_issues < target) && watchdog < 100000) begin
                @(negedge clk);
                watchdog = watchdog + 1;
            end
            if (group_issues < target)
                fail("run did not reach requested pipeline issue count");
        end
    endtask

    task cancel_pipeline_stage_sweep;
        integer pipeline_edge;
        integer before_issues;
        begin
            out_ready = 0;
            build_weight_epoch(1, 3, 0, 1);
            for (pipeline_edge = 0; pipeline_edge < 5; pipeline_edge = pipeline_edge + 1) begin
                build_activation_epoch(1, 1, 3, 50 + pipeline_edge, 0, 1);
                before_issues = group_issues;
                expect_success(OP_RUN, 3, 50 + pipeline_edge, 0, 1, 1, 1, 0, 0);
                // RUN is accepted at this negedge. Delaying the command by
                // pipeline_edge edges makes CANCEL reach the datapath while
                // the one-group job is at successive issue/product/sum/accum
                // boundaries, without a second group filling the pipeline.
                repeat (pipeline_edge) @(negedge clk);
                send_cancel_now();
                repeat (8) begin
                    @(posedge clk);
                    if (out_valid)
                        fail("stage-sweep cancel leaked a stale result");
                end
                if (!weight_valid || active_weight_epoch != 3 || activation_valid || busy)
                    fail("stage-sweep cancel changed resident weights or stayed busy");
                if ((group_issues - before_issues) > 1)
                    fail("single-group cancellation issued more than one group");
            $display("CANCEL_STAGE_PASS pipeline_edge=%0d issued=%0d weight_epoch=3",
                    pipeline_edge, group_issues - before_issues);
            end
        end
    endtask

    task reset_pipeline_stage_sweep;
        integer pipeline_edge;
        integer before_issues;
        begin
            out_ready = 0;
            for (pipeline_edge = 0; pipeline_edge < 5; pipeline_edge = pipeline_edge + 1) begin
                build_weight_epoch(1, 4, 0, 1);
                build_activation_epoch(1, 1, 4, 60 + pipeline_edge, 0, 1);
                before_issues = group_issues;
                expect_success(OP_RUN, 4, 60 + pipeline_edge, 0, 1, 1, 1, 0, 0);
                repeat (pipeline_edge + 1) @(negedge clk);
                rst_n = 0;
                repeat (3) @(posedge clk);
                @(negedge clk);
                rst_n = 1;
                repeat (2) @(posedge clk);
                @(negedge clk);
                if (weight_valid || activation_valid || busy || out_valid)
                    fail("stage-sweep reset left a valid epoch or in-flight result");
                if ((group_issues - before_issues) > 1)
                    fail("single-group reset issued more than one group");
                $display("RESET_STAGE_PASS pipeline_edge=%0d issued=%0d",
                    pipeline_edge, group_issues - before_issues);
            end
        end
    endtask

    task send_cancel_now;
        integer watchdog;
        reg accepted;
        begin
            // Called on the negedge returned by expect_success(OP_RUN), so
            // this accepts CANCEL on the earliest possible following edge.
            cmd_opcode = OP_CANCEL;
            cmd_weight_epoch = 0;
            cmd_activation_epoch = 0;
            cmd_addr = 0;
            cmd_tap_count = 0;
            cmd_lane_count = 0;
            cmd_site_count = 0;
            cmd_site_mask = 0;
            cmd_payload = 0;
            cmd_schema = SCHEMA;
            cmd_valid = 1;
            watchdog = 0;
            accepted = 0;
            while (!accepted && watchdog < 100000) begin
                @(posedge clk);
                if (cmd_ready) begin
                    accepted = 1;
                    command_counter = command_counter + 1;
                end
                watchdog = watchdog + 1;
            end
            if (!accepted)
                fail("cancel command ingress watchdog expired");
            @(negedge clk);
            cmd_valid = 0;
        end
    endtask

    task replay_comparison_jobs;
        integer job;
        integer sites;
        integer lanes;
        reg [31:0] rv;
        begin
            for (job = 0; job < 40; job = job + 1) begin
                if (job == 39) begin
                    sites = 4;
                    lanes = 32;
                end else begin
                    rv = next_random();
                    sites = (rv % 4) + 1;
                    rv = next_random();
                    lanes = (rv % 32) + 1;
                end
                build_activation_epoch(27, sites, 2, 3 + job, 0, 1);
                run_and_compare(27, sites, lanes, 2, 3 + job, "random_signed_replay");
            end
            $display("REPLAY_METRIC scalar_comparison_jobs=40 weight_epoch=2 status=PASS");
        end
    endtask

    integer before_weight_commands;
    integer load_start_cycle;
    integer lane;
    reg [1023:0] payload;
    integer weight_epoch_count;
    integer activation_epoch_count;
    integer before_run_groups;
    integer workload_start_cycle;
    integer workload_end_cycle;
    integer prefix_tap;
    reg signed [15:0] prefix_product;
    reg signed [63:0] prefix_accum;
    initial begin : test_main
        repeat (3) @(posedge clk);
        @(negedge clk);
        rst_n = 1;
        if (schema_id !== SCHEMA)
            fail("private protocol schema ID mismatch");

        expect_error(OP_WEIGHT_BEGIN, 1, 0, 0, 1, 0, 0, 0, 0,
                     32'hdeadbeef, 4'd1);
        expect_error(OP_WEIGHT_BEGIN, 1, 0, 0, 4092, 0, 0, 0, 0,
                     SCHEMA, 4'd6);

        load_start_cycle = cycle_counter;
        expect_success(OP_WEIGHT_BEGIN, 2, 0, 0, 27, 0, 0, 0, 0);
        expect_error(OP_WEIGHT_COMMIT, 2, 0, 0, 27, 0, 0, 0, 0,
                     SCHEMA, 4'd7);
        expect_error(OP_ACT_BEGIN, 2, 1, 0, 27, 0, 4, 0, 0,
                     SCHEMA, 4'd3);
        expect_error(OP_WEIGHT_DATA, 99, 0, 0, 27, 0, 0, 0, 0,
                     SCHEMA, 4'd4);
        expect_error(OP_WEIGHT_DATA, 2, 0, 1, 27, 0, 0, 0, 0,
                     SCHEMA, 4'd5);
        before_weight_commands = weight_data_commands;
        build_weight_epoch(27, 2, 0, 0);
        if (weight_data_commands - before_weight_commands != 27)
            fail("weight epoch accepted wrong number of data words");

        expect_success(OP_ACT_BEGIN, 2, 1, 0, 27, 0, 4, 0, 0);
        expect_error(OP_ACT_COMMIT, 2, 1, 0, 27, 0, 4, 0, 0,
                     SCHEMA, 4'd7);
        expect_error(OP_ACT_DATA, 2, 88, 0, 27, 0, 4, 4'hf, 0,
                     SCHEMA, 4'd4);
        expect_error(OP_ACT_DATA, 2, 1, 1, 27, 0, 4, 4'hf, 0,
                     SCHEMA, 4'd5);
        build_activation_epoch(27, 4, 2, 1, 0, 0);
        expect_error(OP_RUN, 99, 1, 0, 27, 32, 4, 0, 0,
                     SCHEMA, 4'd4);
        run_and_compare(27, 4, 32, 2, 1, "taps27_full");

        before_weight_commands = weight_data_commands;
        build_activation_epoch(27, 4, 2, 2, 3, 1);
        run_and_compare(27, 4, 32, 2, 2, "resident_tile_2");
        if (weight_data_commands != before_weight_commands)
            fail("activation replacement reloaded persistent weights");
        $display("PERSISTENCE_METRIC weight_epoch=2 activation_epochs=2 weight_words=%0d weight_bytes=%0d extra_weight_words=0 invariant=PASS",
            27, 27 * 32);

        // A rejected overlapping run during compute proves that the command
        // ingress stays bounded while the arithmetic pipeline is occupied.
        replay_comparison_jobs();
        before_weight_commands = weight_data_commands;
        before_run_groups = group_issues;
        expect_success(OP_RUN, 2, 42, 0, 27, 32, 4, 0, 0);
        expect_error(OP_RUN, 2, 42, 0, 27, 32, 4, 0, 0,
                     SCHEMA, 4'd3);
        wait_for_issue_count(before_run_groups + 7);
        // Run is allowed to finish normally after the overlap rejection.
        drain_and_compare(4, 32);
        if (weight_data_commands != before_weight_commands)
            fail("run path changed persistent weight count");

        // Sweep cancel through all four registered arithmetic stages.
        cancel_pipeline_stage_sweep();
        expect_error(OP_RUN, 3, 54, 0, 1, 1, 1, 0, 0,
                     SCHEMA, 4'd7);
        build_activation_epoch(1, 1, 3, 55, 0, 1);
        run_and_compare(1, 1, 1, 3, 55, "post_cancel_reload");

        // Reset the private model and every in-flight pipeline boundary at
        // staged offsets before rebuilding a fresh model after the sweep.
        reset_pipeline_stage_sweep();
        expect_error(OP_RUN, 4, 64, 0, 1, 1, 1, 0, 0,
                     SCHEMA, 4'd7);

        // A new weight epoch invalidates the prior activation epoch.
        expect_success(OP_WEIGHT_BEGIN, 5, 0, 0, 144, 0, 0, 0, 0);
        if (weight_valid || activation_valid)
            fail("new weight epoch did not invalidate prior model data");
        expect_error(OP_RUN, 3, 55, 0, 1, 1, 1, 0, 0,
                     SCHEMA, 4'd3);
        build_weight_epoch(144, 5, 0, 0);
        expect_error(OP_RUN, 5, 100, 0, 144, 32, 4, 0, 0,
                     SCHEMA, 4'd7);
        build_activation_epoch(144, 3, 5, 100, 0, 1);
        run_and_compare(144, 3, 32, 5, 100, "taps144_sites3");

        expect_error(OP_WEIGHT_BEGIN, 2, 0, 0, 1, 0, 0, 0, 0,
                     SCHEMA, 4'd8);

        build_weight_epoch(1, 6, 1, 1);
        build_activation_epoch(1, 1, 6, 101, 1, 1);
        run_and_compare(1, 1, 1, 6, 101, "positive_saturation");
        build_weight_epoch(1, 7, 2, 1);
        build_activation_epoch(1, 1, 7, 102, 2, 1);
        run_and_compare(1, 1, 1, 7, 102, "negative_saturation");
        build_weight_epoch(5, 8, 3, 1);
        build_activation_epoch(5, 1, 8, 103, 3, 1);
        prefix_accum = bias_values[0];
        for (prefix_tap = 0; prefix_tap < 5; prefix_tap = prefix_tap + 1) begin
            prefix_product = $signed(weight_values[0][prefix_tap]) *
                             $signed(activation_values[0][prefix_tap]);
            prefix_accum = prefix_accum + prefix_product;
            if (prefix_tap == 0 && prefix_accum !== 64'sd2147483776)
                fail("prefix-overflow first prefix differs from independently expected max+129");
        end
        if (prefix_accum !== 64'sd2147483522)
            fail("prefix-overflow final sum differs from independently expected max-125");
        run_and_compare(5, 1, 1, 8, 103, "prefix_overflow_returns_in_range");

        // Cross INT32_MAX at the end of the actual four-tap accumulation
        // group, then return in range on tap five. This catches a clamp at
        // an intermediate group boundary even when the final sum is valid.
        build_weight_epoch(5, 9, 4, 1);
        build_activation_epoch(5, 1, 9, 107, 4, 1);
        prefix_accum = bias_values[0];
        for (prefix_tap = 0; prefix_tap < 5; prefix_tap = prefix_tap + 1) begin
            prefix_product = $signed(weight_values[0][prefix_tap]) *
                             $signed(activation_values[0][prefix_tap]);
            prefix_accum = prefix_accum + prefix_product;
            case (prefix_tap)
                0: if (prefix_accum !== 64'sd2147449776)
                       fail("four-tap-group overflow prefix 1 differs from scalar golden");
                1: if (prefix_accum !== 64'sd2147465905)
                       fail("four-tap-group overflow prefix 2 differs from scalar golden");
                2: if (prefix_accum !== 64'sd2147482034)
                       fail("four-tap-group overflow prefix 3 differs from scalar golden");
                3: if (prefix_accum !== 64'sd2147498163)
                       fail("four-tap-group sum must exceed INT32_MAX by 14516");
                4: if (prefix_accum !== 64'sd2147481907)
                       fail("four-tap-group overflow final sum differs from scalar golden");
            endcase
        end
        if ((prefix_accum > 64'sd2147483647) ||
            (prefix_accum < -64'sd2147483648))
            fail("directed group-boundary final sum must return inside signed32 range");
        run_and_compare(5, 1, 1, 9, 107, "group_boundary_overflow_returns_in_range");

        build_weight_epoch(2304, 10, 1, 1);
        build_activation_epoch(2304, 4, 10, 108, 1, 1);
        workload_start_cycle = cycle_counter;
        before_run_groups = group_issues;
        expect_success(OP_RUN, 10, 108, 0, 2304, 9, 4, 0, 0);
        expect_error(OP_ACT_BEGIN, 10, 109, 0, 2304, 0, 4, 0, 0,
                     SCHEMA, 4'd3);
        build_scalar_reference(2304, 4, 9);
        drain_and_compare(4, 9);
        workload_end_cycle = cycle_counter;
        if (group_issues - before_run_groups != 576)
            fail("2304-tap workload group count mismatch");
        $display("CASE_METRIC label=taps2304_tail9 taps=2304 groups=576 lanes=9 sites=4 start_to_last_result_cycles=%0d issue_cycles=%0d result_bus_bytes=512 useful_result_bytes=144 status=PASS",
            workload_end_cycle - workload_start_cycle, group_issues - before_run_groups);

        // The maximum accepted tap count is exercised at a single site/lane.
        build_weight_epoch(4091, 11, 0, 1);
        build_activation_epoch(4091, 1, 11, 110, 0, 1);
        run_and_compare(4091, 1, 1, 11, 110, "taps4091_bound");

        $display("SIM_PASS cases=50 commands=%0d weight_data_commands=%0d cycles=%0d result_stalls=verified schema=%08x",
            command_counter, weight_data_commands, cycle_counter, schema_id);
        $finish;
    end

    initial begin
        #200000000;
        $display("FAIL: global simulation timeout");
        $finish(1);
    end
endmodule
