`timescale 1ns/1ps
`default_nettype none
module tb_z100_bank_overlap_followup;
    reg clk = 0;
    always #5 clk = ~clk;

    reg rst_n=0, cancel=0, recover=0, recovery_drained=0;
    reg cmd_valid=0;
    wire cmd_ready;
    reg [31:0] cmd_epoch=0, cmd_job_base=0, cmd_token_base=0, cmd_tag_base=0;
    reg [7:0] cmd_tiles=0;
    reg [9:0] cmd_output_height=0;
    reg cmd_first_bank=0;
    reg source_leased=0, destination_reserved=0;

    reg descriptor_valid=0;
    wire descriptor_ready;
    reg [31:0] descriptor_epoch=0;
    reg [7:0] descriptor_index=0;
    reg [9:0] descriptor_input_y=0, descriptor_input_rows=0;
    reg [9:0] descriptor_output_y=0, descriptor_output_rows=0;
    reg [31:0] descriptor_runs=0, descriptor_windows=0;
    wire [7:0] next_descriptor;

    wire load_valid;
    reg load_ready=0;
    wire load_bank;
    wire [31:0] load_job_tag;
    wire [9:0] load_input_y, load_input_rows;
    reg load_done=0, load_committed=0, load_fault=0;
    reg [31:0] load_epoch=0;
    reg load_done_bank=0;

    wire tile_valid;
    reg tile_ready=0;
    wire tile_bank;
    wire [31:0] tile_job_tag, tile_token_base, tile_tag_base;
    wire [9:0] tile_input_y, tile_input_rows, tile_output_y, tile_output_rows;
    reg tile_done=0, tile_fault=0;
    reg [31:0] tile_done_epoch=0, tile_done_job=0;
    reg tile_done_bank=0;

    reg load_quiet=1, tile_write_quiet=1, all_io_quiet=1;
    wire [31:0] epoch;
    wire child_cancel, active, needs_drain;
    wire done, fault;
    wire [3:0] fault_code;
    wire [7:0] committed_tiles;

    z100_conv_prefetch_control_v2 dut(.*);

    // Independent child/DDR ownership model. The DUT itself only owns the
    // metadata FSM; these flags stand in for the external loader, compute
    // engine and output writer and never claim pixel/DDR numerical behavior.
    reg model_owned[0:1];
    reg model_loaded[0:1];
    reg model_load_pending=0, model_compute_pending=0, model_writer_pending=0;
    reg model_load_bank=0, model_compute_bank=0, model_writer_bank=0;
    reg [31:0] model_load_job=0, model_compute_job=0;
    integer same_bank_block_cycles=0, load_compute_overlap_cycles=0;
    integer recovery_gate_checks=0, drain_phase_checks=0;

    task tick;
        begin @(posedge clk); #1; end
    endtask

    task reset_case;
        integer b;
        begin
            rst_n=0; cancel=0; recover=0; recovery_drained=0; cmd_valid=0;
            cmd_epoch=0; cmd_job_base=0; cmd_token_base=0; cmd_tag_base=0;
            cmd_tiles=0; cmd_output_height=0; cmd_first_bank=0;
            source_leased=1; destination_reserved=1;
            descriptor_valid=0; descriptor_epoch=0; descriptor_index=0;
            descriptor_input_y=0; descriptor_input_rows=0;
            descriptor_output_y=0; descriptor_output_rows=0;
            descriptor_runs=0; descriptor_windows=0;
            load_ready=0; load_done=0; load_committed=0; load_fault=0;
            load_epoch=0; load_done_bank=0;
            tile_ready=0; tile_done=0; tile_fault=0;
            tile_done_epoch=0; tile_done_job=0; tile_done_bank=0;
            load_quiet=1; tile_write_quiet=1; all_io_quiet=1;
            model_load_pending=0; model_compute_pending=0; model_writer_pending=0;
            model_load_bank=0; model_compute_bank=0; model_writer_bank=0;
            model_load_job=0; model_compute_job=0;
            for (b=0;b<2;b=b+1) begin model_owned[b]=0; model_loaded[b]=0; end
            tick(); tick(); rst_n=1; tick();
            if (!cmd_ready || active || fault) $fatal(1,"reset did not return DUT to idle");
        end
    endtask

    task start_command;
        begin
            cmd_epoch=77; cmd_job_base=500; cmd_token_base=1000; cmd_tag_base=2000;
            cmd_tiles=3; cmd_output_height=60; cmd_first_bank=0; cmd_valid=1;
            #1;
            if (!cmd_ready) $fatal(1,"command blocked from quiet idle");
            tick(); cmd_valid=0; all_io_quiet=0;
            if (!active || epoch!=cmd_epoch) $fatal(1,"command did not activate expected epoch");
        end
    endtask

    task drive_descriptor;
        input integer idx;
        begin
            descriptor_epoch=cmd_epoch; descriptor_index=idx[7:0];
            descriptor_input_y=idx*20; descriptor_input_rows=40;
            descriptor_output_y=idx*20; descriptor_output_rows=20;
            descriptor_runs=16; descriptor_windows=144;
            descriptor_valid=1;
        end
    endtask

    task send_descriptor;
        input integer idx;
        integer expected_bank;
        begin
            expected_bank=cmd_first_bank ^ (idx & 1);
            drive_descriptor(idx); #1;
            if (!descriptor_ready) $fatal(1,"descriptor %0d unexpectedly blocked",idx);
            if (model_owned[expected_bank]) $fatal(1,"descriptor reused owned bank %0d",expected_bank);
            tick(); descriptor_valid=0;
            if (next_descriptor!=idx+1) $fatal(1,"descriptor cursor did not advance at %0d",idx);
        end
    endtask

    task accept_load;
        input integer expected_bank;
        input integer expected_job;
        begin
            #1;
            if (!load_valid || load_bank!==expected_bank[0])
                $fatal(1,"expected load bank %0d valid=%0b actual_bank=%0d",expected_bank,load_valid,load_bank);
            if (load_job_tag!=expected_job) $fatal(1,"load job tag mismatch expected=%0d actual=%0d",expected_job,load_job_tag);
            if (model_owned[expected_bank]) $fatal(1,"loader attempted to acquire owned bank %0d",expected_bank);
            model_owned[expected_bank]=1; model_loaded[expected_bank]=0;
            model_load_pending=1; model_load_bank=expected_bank[0]; model_load_job=load_job_tag;
            load_quiet=0; load_ready=1; tick(); load_ready=0;
        end
    endtask

    task complete_load;
        begin
            if (!model_load_pending) $fatal(1,"test model completed a nonexistent load");
            load_epoch=cmd_epoch; load_done_bank=model_load_bank;
            load_done=1; load_committed=1; tick();
            load_done=0; load_committed=0; load_quiet=1;
            model_loaded[model_load_bank]=1; model_load_pending=0;
        end
    endtask

    task accept_tile;
        input integer expected_bank;
        input integer expected_job;
        begin
            #1;
            if (!tile_valid || tile_bank!==expected_bank[0])
                $fatal(1,"expected tile bank %0d valid=%0b actual_bank=%0d",expected_bank,tile_valid,tile_bank);
            if (tile_job_tag!=expected_job) $fatal(1,"tile job tag mismatch expected=%0d actual=%0d",expected_job,tile_job_tag);
            if (!model_owned[expected_bank] || !model_loaded[expected_bank])
                $fatal(1,"compute attempted to use unowned/unloaded bank %0d",expected_bank);
            if (model_compute_pending || model_writer_pending)
                $fatal(1,"single compute/write path accepted overlapping tile");
            model_compute_pending=1; model_compute_bank=expected_bank[0]; model_compute_job=tile_job_tag;
            tile_ready=1; tick(); tile_ready=0;
        end
    endtask

    task complete_tile;
        begin
            if (!model_compute_pending) $fatal(1,"test model completed nonexistent compute");
            tile_done_epoch=cmd_epoch; tile_done_job=model_compute_job;
            tile_done_bank=model_compute_bank; tile_done=1;
            tile_write_quiet=0; tick(); tile_done=0;
            model_compute_pending=0; model_writer_pending=1; model_writer_bank=model_compute_bank;
        end
    endtask

    task drain_writer;
        begin
            if (!model_writer_pending) $fatal(1,"test model drained nonexistent writer");
            tile_write_quiet=1; tick();
            model_owned[model_writer_bank]=0; model_loaded[model_writer_bank]=0;
            model_writer_pending=0;
        end
    endtask

    initial begin
        reset_case();
        start_command();

        send_descriptor(0);
        send_descriptor(1);
        accept_load(0,500);
        complete_load();
        accept_tile(0,500);

        // Hold descriptor 2, which maps back to bank 0, while tile 0 owns it.
        drive_descriptor(2); #1;
        if (descriptor_ready) $fatal(1,"same-bank descriptor was not blocked during compute");
        same_bank_block_cycles=same_bank_block_cycles+1;

        // The independent loader owns bank 1 while compute owns bank 0.
        accept_load(1,501);
        if (!model_load_pending || !model_compute_pending ||
            model_load_bank==model_compute_bank)
            $fatal(1,"load/compute overlap ownership was not independent");
        load_compute_overlap_cycles=load_compute_overlap_cycles+1;
        #1;
        if (descriptor_ready || load_valid)
            $fatal(1,"same-bank descriptor/load invariants changed under overlap");
        complete_load();

        complete_tile();
        #1;
        if (descriptor_ready || tile_valid)
            $fatal(1,"DRAIN ownership did not block same-bank reuse and next tile");
        same_bank_block_cycles=same_bank_block_cycles+1;
        repeat (2) begin tick(); if (descriptor_ready) $fatal(1,"same bank reused before write drain"); same_bank_block_cycles=same_bank_block_cycles+1; end
        drain_writer();
        #1;
        if (!descriptor_ready) $fatal(1,"same bank did not become available after write drain");
        tick(); descriptor_valid=0;
        if (next_descriptor!=3 || model_owned[0])
            $fatal(1,"descriptor 2 failed to acquire the drained bank");

        // Bank 0 can now load tile 2 on the same cycle bank 1 starts tile 1.
        #1;
        if (!load_valid || !tile_valid || load_bank==tile_bank)
            $fatal(1,"opposite-bank simultaneous load/compute opportunity missing");
        if (model_owned[load_bank] || !model_owned[tile_bank] || !model_loaded[tile_bank])
            $fatal(1,"simultaneous dispatch violated model ownership");
        model_owned[load_bank]=1; model_loaded[load_bank]=0;
        model_load_pending=1; model_load_bank=load_bank; model_load_job=load_job_tag;
        model_compute_pending=1; model_compute_bank=tile_bank; model_compute_job=tile_job_tag;
        load_quiet=0; tile_write_quiet=0; load_ready=1; tile_ready=1;
        tick(); load_ready=0; tile_ready=0;
        load_compute_overlap_cycles=load_compute_overlap_cycles+1;
        if (!model_load_pending || !model_compute_pending ||
            model_load_bank==model_compute_bank)
            $fatal(1,"simultaneous handshakes aliased bank ownership");

        cancel=1; tick(); cancel=0;
        if (!fault || fault_code!=1 || !needs_drain || !child_cancel ||
            load_valid || tile_valid || cmd_ready)
            $fatal(1,"cancel did not enter fail-closed drain state");
        if (!model_load_pending || !model_compute_pending ||
            model_load_bank==model_compute_bank)
            $fatal(1,"cancel lost accepted child ownership");

        // Recovery is gated until each accepted child/writer has drained.
        recovery_drained=1; recover=1;
        if (load_quiet || tile_write_quiet || all_io_quiet) $fatal(1,"drain test started with false quiet flags");
        tick();
        if (!fault || !needs_drain || cmd_ready) $fatal(1,"recovery escaped before external drain");
        recovery_gate_checks=recovery_gate_checks+1;

        // A canceled loader may complete late. That pulse still blocks recovery.
        complete_load();
        if (!model_owned[0] || !model_loaded[0])
            $fatal(1,"drained loader bank ownership was released before recovery");
        all_io_quiet=0; tile_write_quiet=0;
        if (!fault || !needs_drain) $fatal(1,"load drain cleared controller fault");
        drain_phase_checks=drain_phase_checks+1;

        // The active compute then completes; its output writer remains pending.
        complete_tile();
        if (!model_writer_pending || model_writer_bank!=1 || tile_write_quiet)
            $fatal(1,"compute completion did not retain writer ownership");
        if (!fault || !needs_drain) $fatal(1,"compute drain cleared controller fault");
        drain_phase_checks=drain_phase_checks+1;

        // A delayed write drain releases only the modeled physical owner. The
        // controller still waits for the explicit recovery_drained handshake.
        drain_writer();
        all_io_quiet=1; load_quiet=1; tile_write_quiet=1;
        recovery_drained=0; recover=1; tick();
        if (!fault || !needs_drain || cmd_ready)
            $fatal(1,"recovery accepted without recovery_drained");
        recovery_gate_checks=recovery_gate_checks+1;

        recovery_drained=1; all_io_quiet=0; recover=1; tick();
        if (!fault || !needs_drain || cmd_ready)
            $fatal(1,"recovery accepted while all I/O was not quiet");
        recovery_gate_checks=recovery_gate_checks+1;

        all_io_quiet=1; recover=1; tick(); recover=0;
        if (fault || needs_drain || active || !cmd_ready)
            $fatal(1,"fully drained recovery did not return idle");
        model_owned[0]=0; model_loaded[0]=0;
        if (model_load_pending || model_compute_pending || model_writer_pending)
            $fatal(1,"external child model was not fully drained at recovery");

        // Failed commands advance the replay ledger at acceptance; retrying
        // the same epoch/job after recovery must remain rejected.
        cmd_epoch=77; cmd_job_base=500; cmd_token_base=1000; cmd_tag_base=2000;
        cmd_tiles=3; cmd_output_height=60; cmd_first_bank=0; cmd_valid=1;
        #1; if (!cmd_ready) $fatal(1,"recovery did not reopen command port");
        tick(); cmd_valid=0;
        if (!fault || !needs_drain || fault_code!=7)
            $fatal(1,"same epoch/job replay was not rejected after cancellation");
        if (same_bank_block_cycles<3 || load_compute_overlap_cycles<2 ||
            recovery_gate_checks<3 || drain_phase_checks<2)
            $fatal(1,"directed coverage counters are incomplete");

        $display("BANK_OVERLAP_FOLLOWUP_PASS same_bank_block_cycles=%0d load_compute_overlap_cycles=%0d recovery_gate_checks=%0d drain_phase_checks=%0d replay_rejected=1",
                 same_bank_block_cycles,load_compute_overlap_cycles,recovery_gate_checks,drain_phase_checks);
        $finish;
    end

    initial begin #100000; $fatal(1,"watchdog timeout"); end
endmodule
`default_nettype wire




