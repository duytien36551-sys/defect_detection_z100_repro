`timescale 1ns/1ps
`default_nettype none
`include "scheduler_defs.vh"
module tb_z100_native_row_scheduler;
    localparam integer COMMANDS = `COMMAND_COUNT;
    localparam integer RUNS = `RUN_COUNT;
    localparam integer WINDOWS = `WINDOW_COUNT;
    localparam integer CMD_W = 212;
    localparam integer RUN_W = 74;
    localparam integer WIN_W = 122;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg cancel = 0;
    reg cmd_valid = 0;
    wire cmd_ready;
    reg [31:0] cmd_epoch = 0, cmd_token_base = 0, cmd_tag_base = 0;
    reg [10:0] cmd_channels = 0;
    reg [9:0] cmd_input_width = 0, cmd_output_width = 0;
    reg [1:0] cmd_kernel = 0, cmd_stride = 0, cmd_padding = 0;
    reg [5:0] cmd_lanes = 0;
    reg [13:0] cmd_bank_words = 0, cmd_channel_plane_stride = 0;
    reg [41:0] cmd_ky_row_bases = 0;
    reg [2:0] cmd_y_valid = 0;

    wire run_valid;
    reg run_ready = 0;
    wire [31:0] run_epoch, run_token;
    wire [5:0] run_lanes;
    wire [3:0] run_sites;
    wire window_valid;
    reg window_ready = 0;
    wire [31:0] window_epoch, window_tag;
    wire [13:0] window_row_address;
    wire signed [11:0] window_first_x;
    wire [10:0] window_input_width, window_output_remaining;
    wire [3:0] window_sites, window_channel_mask;
    wire window_stride_two, window_y_valid;

    reg post_done_valid = 0;
    wire post_done_ready;
    reg [31:0] post_done_epoch = 0, post_done_token = 0;
    wire done, abort_pulse, fault_valid;
    wire [2:0] fault_code;
    wire active;

    reg [CMD_W-1:0] command_vector [0:COMMANDS-1];
    reg [17:0] command_meta [0:COMMANDS-1];
    reg [RUN_W-1:0] expected_runs [0:RUNS-1];
    reg [WIN_W-1:0] expected_windows [0:WINDOWS-1];

    z100_native_row_scheduler dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cmd_valid(cmd_valid), .cmd_ready(cmd_ready),
        .cmd_epoch(cmd_epoch), .cmd_token_base(cmd_token_base), .cmd_tag_base(cmd_tag_base),
        .cmd_channels(cmd_channels), .cmd_input_width(cmd_input_width),
        .cmd_output_width(cmd_output_width), .cmd_kernel(cmd_kernel),
        .cmd_stride(cmd_stride), .cmd_padding(cmd_padding), .cmd_lanes(cmd_lanes),
        .cmd_bank_words(cmd_bank_words), .cmd_channel_plane_stride(cmd_channel_plane_stride),
        .cmd_ky_row_bases(cmd_ky_row_bases), .cmd_y_valid(cmd_y_valid),
        .run_valid(run_valid), .run_ready(run_ready), .run_epoch(run_epoch),
        .run_token(run_token), .run_lanes(run_lanes), .run_sites(run_sites),
        .window_valid(window_valid), .window_ready(window_ready),
        .window_epoch(window_epoch), .window_tag(window_tag),
        .window_row_address(window_row_address), .window_first_x(window_first_x),
        .window_input_width(window_input_width),
        .window_output_remaining(window_output_remaining), .window_sites(window_sites),
        .window_channel_mask(window_channel_mask), .window_stride_two(window_stride_two),
        .window_y_valid(window_y_valid),
        .post_done_valid(post_done_valid), .post_done_ready(post_done_ready),
        .post_done_epoch(post_done_epoch), .post_done_token(post_done_token),
        .done(done), .abort_pulse(abort_pulse), .fault_valid(fault_valid),
        .fault_code(fault_code), .active(active)
    );

    integer cycle_count = 0;
    integer checked_run_count = 0, checked_window_count = 0;
    integer all_run_handshakes = 0, all_window_handshakes = 0;
    integer run_stall_cycles = 0, window_stall_cycles = 0;
    integer run_stability_checks = 0, window_stability_checks = 0;
    integer fault_count = 0, abort_count = 0, done_count = 0;
    integer reload_blocked_cycles = 0;
    integer traffic_mode = 0, check_enable = 0;
    integer previous_run_stall = 0, previous_window_stall = 0;
    reg [73:0] held_run;
    reg [121:0] held_window;
    reg [2:0] last_fault_code = 0;
    integer row_token_held = 0;
    reg [73:0] held_row_metadata;

    always @(posedge clk) begin
        cycle_count = cycle_count + 1;
        if (fault_valid) begin
            fault_count = fault_count + 1;
            last_fault_code = fault_code;
        end
        if (abort_pulse) abort_count = abort_count + 1;
        if (done) done_count = done_count + 1;
        if (run_valid && run_ready) all_run_handshakes = all_run_handshakes + 1;
        if (window_valid && window_ready) all_window_handshakes = all_window_handshakes + 1;

        if (!rst_n || cancel || abort_pulse) begin
            previous_run_stall = 0;
            previous_window_stall = 0;
        end else begin
            if (previous_run_stall) begin
                if (!run_valid || {run_epoch,run_token,run_lanes,run_sites} !== held_run)
                    $fatal(1, "run payload changed while ready was low");
                run_stability_checks = run_stability_checks + 1;
            end
        end

        if (check_enable && row_token_held && active &&
            !(post_done_valid && post_done_ready) &&
            {run_epoch,run_token,run_lanes,run_sites} !== held_row_metadata)
            $fatal(1, "run token/metadata changed before final post_done handshake");
        if (check_enable && run_valid && run_ready) begin
            held_row_metadata = {run_epoch,run_token,run_lanes,run_sites};
            row_token_held = 1;
        end
        if (check_enable && post_done_valid && post_done_ready)
            row_token_held = 0;
        if (rst_n && !cancel && !abort_pulse) begin
            previous_run_stall = run_valid && !run_ready;
            if (previous_run_stall) begin
                held_run = {run_epoch,run_token,run_lanes,run_sites};
                run_stall_cycles = run_stall_cycles + 1;
            end
        end

        if (rst_n && !cancel && !abort_pulse) begin
            if (previous_window_stall) begin
                if (!window_valid || {window_epoch,window_tag,window_row_address,
                    window_first_x,window_input_width,window_output_remaining,
                    window_sites,window_channel_mask,window_stride_two,window_y_valid} !== held_window)
                    $fatal(1, "window descriptor changed while ready was low");
                window_stability_checks = window_stability_checks + 1;
            end
            previous_window_stall = window_valid && !window_ready;
            if (previous_window_stall) begin
                held_window = {window_epoch,window_tag,window_row_address,
                    window_first_x,window_input_width,window_output_remaining,
                    window_sites,window_channel_mask,window_stride_two,window_y_valid};
                window_stall_cycles = window_stall_cycles + 1;
            end
        end

        if (check_enable && run_valid && run_ready) begin
            if (checked_run_count >= RUNS) $fatal(1, "extra run request");
            if ({run_epoch,run_token,run_lanes,run_sites} !== expected_runs[checked_run_count])
                $fatal(1, "run metadata mismatch index=%0d got=%h expected=%h",
                       checked_run_count, {run_epoch,run_token,run_lanes,run_sites},
                       expected_runs[checked_run_count]);
            checked_run_count = checked_run_count + 1;
        end
        if (check_enable && window_valid && window_ready) begin
            if (checked_window_count >= WINDOWS) $fatal(1, "extra window descriptor");
            if ({window_epoch,window_tag,window_row_address,window_first_x,
                 window_input_width,window_output_remaining,window_sites,
                 window_channel_mask,window_stride_two,window_y_valid} !==
                expected_windows[checked_window_count])
                $fatal(1, "window mismatch index=%0d got=%h expected=%h",
                       checked_window_count,
                       {window_epoch,window_tag,window_row_address,window_first_x,
                        window_input_width,window_output_remaining,window_sites,
                        window_channel_mask,window_stride_two,window_y_valid},
                       expected_windows[checked_window_count]);
            checked_window_count = checked_window_count + 1;
        end
    end

    always @(negedge clk) begin
        if (traffic_mode) begin
            run_ready = ((cycle_count % 7) != 1) && ((cycle_count % 11) != 4);
            window_ready = ((cycle_count % 9) != 2) && ((cycle_count % 13) != 5);
        end
    end

    task automatic drive_command(input integer index);
        begin
            @(negedge clk);
            cmd_epoch = command_vector[index][211:180];
            cmd_token_base = command_vector[index][179:148];
            cmd_tag_base = command_vector[index][147:116];
            cmd_channels = command_vector[index][115:105];
            cmd_input_width = command_vector[index][104:95];
            cmd_output_width = command_vector[index][94:85];
            cmd_kernel = command_vector[index][84:83];
            cmd_stride = command_vector[index][82:81];
            cmd_padding = command_vector[index][80:79];
            cmd_lanes = command_vector[index][78:73];
            cmd_bank_words = command_vector[index][72:59];
            cmd_channel_plane_stride = command_vector[index][58:45];
            cmd_ky_row_bases = command_vector[index][44:3];
            cmd_y_valid = command_vector[index][2:0];
            cmd_valid = 1;
            while (!cmd_ready) @(negedge clk);
            @(posedge clk);
            @(negedge clk); cmd_valid = 0;
        end
    endtask

    task automatic drive_simple_command(input integer kernel_value);
        begin
            @(negedge clk);
            cmd_epoch = 32'd108; cmd_token_base = 32'd77; cmd_tag_base = 32'd900;
            cmd_channels = (kernel_value == 3) ? 4 : 1;
            cmd_input_width = (kernel_value == 3) ? 3 : 1;
            cmd_output_width = (kernel_value == 3) ? 3 : 1;
            cmd_kernel = kernel_value;
            cmd_stride = 1; cmd_padding = (kernel_value == 3) ? 1 : 0;
            cmd_lanes = 1;
            cmd_bank_words = (kernel_value == 3) ? 9 : 1;
            cmd_channel_plane_stride = 3;
            cmd_ky_row_bases = {14'd0,14'd3,14'd0};
            cmd_y_valid = (kernel_value == 3) ? 3'b111 : 3'b001;
            cmd_valid = 1;
            while (!cmd_ready) @(negedge clk);
            @(posedge clk);
            @(negedge clk); cmd_valid = 0;
        end
    endtask

    task automatic clear_cancel;
        begin
            @(negedge clk); cancel = 1;
            @(posedge clk);
            @(negedge clk); cancel = 0;
            run_ready = 0; window_ready = 0;
            #1;
            if (active || run_valid || window_valid)
                $fatal(1, "cancel failed to flush active scheduler metadata");
        end
    endtask

    task automatic send_post_done(input [31:0] epoch_value, input [31:0] token_value);
        begin
            @(negedge clk);
            if (check_enable && (!active || run_epoch !== epoch_value || run_token !== token_value))
                $fatal(1, "run token was not held through the expected post_done event");
            post_done_epoch = epoch_value; post_done_token = token_value; post_done_valid = 1;
            if (!post_done_ready) $fatal(1, "post_done unexpectedly backpressured");
            @(posedge clk);
            @(negedge clk); post_done_valid = 0;
        end
    endtask

    task automatic recovery_reset;
        begin
            @(negedge clk); rst_n = 0;
            repeat (2) @(posedge clk);
            @(negedge clk); rst_n = 1;
            run_ready = 0; window_ready = 0;
            repeat (2) @(posedge clk);
            #1;
            if (active || run_valid || window_valid)
                $fatal(1, "reset failed to flush active scheduler metadata");
        end
    endtask

    integer i, r, groups, runs, valid_case;
    integer run_base, window_base, fault_base, done_base, abort_base;
    integer descriptors_before;
    initial begin
        $readmemh("commands.hex", command_vector);
        $readmemh("command_meta.hex", command_meta);
        $readmemh("expected_runs.hex", expected_runs);
        $readmemh("expected_windows.hex", expected_windows);
        repeat (5) @(negedge clk);
        rst_n = 1;
        repeat (2) @(negedge clk);

        // Abort/flush tests: no outputs are credited as numerical coverage.
        drive_simple_command(1);
        run_ready = 0; window_ready = 0;
        wait (run_valid === 1'b1);
        clear_cancel();

        run_ready = 1; window_ready = 0;
        drive_simple_command(1);
        wait (run_valid && run_ready);
        @(posedge clk);
        wait (window_valid === 1'b1);
        clear_cancel();

        run_ready = 1; window_ready = 1;
        drive_simple_command(3);
        wait (run_valid && run_ready); @(posedge clk);
        descriptors_before = all_window_handshakes;
        wait (all_window_handshakes >= descriptors_before + 2);
        @(negedge clk); window_ready = 0;
        wait (window_valid === 1'b1);
        clear_cancel();

        run_ready = 1; window_ready = 0;
        drive_simple_command(3);
        wait (run_valid && run_ready); @(posedge clk);
        wait (window_valid === 1'b1);
        recovery_reset();

        run_ready = 1; window_ready = 1;
        drive_simple_command(1);
        wait (run_valid && run_ready); @(posedge clk);
        wait (all_window_handshakes >= descriptors_before + 3);
        // This command has exactly one descriptor; cancel after descriptor
        // acceptance while waiting for the external postprocess drain event.
        wait (active && !run_valid && !window_valid);
        clear_cancel();

        // A matching token in an early post_done is still unexpected.
        run_ready = 1; window_ready = 0;
        drive_simple_command(1);
        wait (run_valid && run_ready); @(posedge clk);
        abort_base = abort_count; fault_base = fault_count;
        send_post_done(108,77);
        wait (fault_count > fault_base);
        if (last_fault_code != 2 || abort_count != abort_base+1 || active)
            $fatal(1, "early post_done did not fail closed");

        // Wrong epoch/token after all descriptors also aborts the current row.
        run_ready = 1; window_ready = 1;
        drive_simple_command(1);
        wait (run_valid && run_ready); @(posedge clk);
        descriptors_before = all_window_handshakes;
        wait (all_window_handshakes > descriptors_before);
        wait (active && !run_valid && !window_valid);
        abort_base = abort_count; fault_base = fault_count;
        send_post_done(109,77);
        wait (fault_count > fault_base);
        if (last_fault_code != 2 || abort_count != abort_base+1 || active)
            $fatal(1, "mismatched post_done did not fail closed");

        // An unsolicited completion while idle is also consumed and rejected.
        abort_base = abort_count; fault_base = fault_count;
        send_post_done(108,77);
        wait (fault_count > fault_base);
        if (last_fault_code != 2 || abort_count != abort_base+1 || active)
            $fatal(1, "unexpected idle post_done did not fail closed");

        // Main valid/invalid command vectors. Valid rows are serviced only
        // after each matching final-post handshake.
        traffic_mode = 1;
        run_ready = 1; window_ready = 1;
        check_enable = 1;
        for (i = 0; i < COMMANDS; i = i + 1) begin
            valid_case = command_meta[i][17];
            runs = command_meta[i][16:11];
            groups = command_meta[i][10:0];
            run_base = checked_run_count;
            window_base = checked_window_count;
            fault_base = fault_count;
            done_base = done_count;
            drive_command(i);
            if (!valid_case) begin
                wait (fault_count > fault_base);
                if (last_fault_code != 1 || active || run_valid || window_valid)
                    $fatal(1, "invalid command was not rejected before any run/window index=%0d", i);
                if (checked_run_count != run_base || checked_window_count != window_base)
                    $fatal(1, "invalid command emitted a run or descriptor index=%0d", i);
            end else begin
                for (r = 0; r < runs; r = r + 1) begin
                    while (checked_run_count < run_base + r + 1) @(negedge clk);
                    while (checked_window_count < window_base + (r+1)*groups) @(negedge clk);
                    send_post_done(command_vector[i][211:180],
                                   command_vector[i][179:148] + r);
                end
                if (done_count == done_base) begin
                    while (done_count == done_base) @(negedge clk);
                end
                if (active || done_count != done_base + 1 || checked_run_count != run_base + runs ||
                    checked_window_count != window_base + runs*groups)
                    $fatal(1, "valid row did not retire exactly once index=%0d", i);
                @(negedge clk);
            end
        end

        // Exercise a 200-cycle reload probe while the long first-conv row is
        // active. The reload request stays valid throughout all 200 polls,
        // and cmd_ready must remain low for every cycle while the row runs.
        if (checked_run_count != RUNS || checked_window_count != WINDOWS)
            $fatal(1, "coverage totals mismatch runs=%0d/%0d windows=%0d/%0d",
                   checked_run_count, RUNS, checked_window_count, WINDOWS);
        if (run_stall_cycles == 0 || window_stall_cycles == 0 ||
            run_stability_checks == 0 || window_stability_checks == 0)
            $fatal(1, "run/window backpressure stability coverage missing");
        if (reload_blocked_cycles != 200)
            $fatal(1, "reload block poll coverage missing: %0d", reload_blocked_cycles);
        if (fault_count < `EXPECTED_FAULTS || abort_count < 3 || done_count != `VALID_COMMAND_COUNT)
            $fatal(1, "fault/abort/done accounting mismatch fault=%0d abort=%0d done=%0d",
                   fault_count, abort_count, done_count);
        if (active || run_valid || window_valid || post_done_valid)
            $fatal(1, "scheduler did not return idle");
        $display("NATIVE_ROW_SCHEDULER_PASS commands=%0d valid_commands=%0d invalid_commands=%0d runs=%0d windows=%0d run_stalls=%0d run_stable=%0d window_stalls=%0d window_stable=%0d blocked_reload_polls=%0d faults=%0d aborts=%0d done=%0d",
                 COMMANDS, `VALID_COMMAND_COUNT, `INVALID_COMMAND_COUNT,
                 checked_run_count, checked_window_count, run_stall_cycles,
                 run_stability_checks, window_stall_cycles, window_stability_checks,
                 reload_blocked_cycles, fault_count, abort_count, done_count);
        $finish;
    end

    // A monitor thread probes the command port during the first long row.
    integer reload_poll;
    initial begin : reload_probe
        wait (traffic_mode && active);
        @(negedge clk); // Let the accepted command driver drop its valid first.
        @(negedge clk);
        cmd_valid = 1;
        cmd_epoch = 32'd108; cmd_token_base = 32'd99999; cmd_tag_base = 32'd99999;
        cmd_channels = 1; cmd_input_width = 1; cmd_output_width = 1;
        cmd_kernel = 1; cmd_stride = 1; cmd_padding = 0; cmd_lanes = 1;
        cmd_bank_words = 1; cmd_channel_plane_stride = 1;
        cmd_ky_row_bases = 0; cmd_y_valid = 1;
        for (reload_poll = 0; reload_poll < 200; reload_poll = reload_poll + 1) begin
            if (cmd_ready) $fatal(1, "command reload became ready while row active");
            reload_blocked_cycles = reload_blocked_cycles + 1;
            @(posedge clk);
        end
        @(negedge clk); cmd_valid = 0;
    end

    initial begin
        #100000000;
        $fatal(1, "native row scheduler watchdog");
    end
endmodule
`default_nettype wire
