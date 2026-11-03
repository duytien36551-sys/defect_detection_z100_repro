`timescale 1ns/1ps
`default_nettype none
// The load and tile children below acknowledge metadata only.  They model
// ready stalls, completion identity and write drain; no tensor data is read.
module tb_z100_conv_rom_prefetch;
    reg clk=0;
    always #5 clk=~clk;

    reg rst_n=0, cancel=0, recover=0, recovery_drained=0;
    reg cmd_valid=0;
    wire cmd_ready;
    reg [31:0] cmd_epoch=1, cmd_model_crc=32'd2213989717;
    reg [7:0] cmd_event=1;
    reg [31:0] cmd_job_base=1, cmd_token_base=1, cmd_tag_base=1;
    reg cmd_first_bank=0;
    reg source_leased=1, destination_reserved=1;

    wire load_valid;
    reg load_ready=0;
    wire load_bank;
    wire [31:0] load_job_tag;
    wire [9:0] load_input_y, load_input_rows;
    wire load_done;
    wire load_committed=1'b1;
    reg load_fault=1'b0;
    wire [31:0] load_epoch;
    wire load_done_bank;
    reg [31:0] load_epoch_q=0;
    wire [31:0] cmd_epoch_for_load=load_epoch_q;

    wire tile_valid;
    reg tile_ready=0;
    wire tile_bank;
    wire [31:0] tile_job_tag, tile_token_base, tile_tag_base;
    wire [9:0] tile_input_y, tile_input_rows, tile_output_y, tile_output_rows;
    wire tile_done;
    reg tile_fault=1'b0;
    wire [31:0] tile_done_epoch, tile_done_job;
    wire tile_done_bank;

    wire load_quiet, tile_write_quiet, all_io_quiet;
    wire producer_context_valid;
    wire [15:0] producer_cin, producer_input_height, producer_input_width;
    wire [15:0] producer_cout, producer_output_height, producer_output_width;
    wire [15:0] producer_kernel, producer_stride, producer_padding;
    wire [15:0] producer_parameter_first;
    wire [7:0] producer_event;
    wire [31:0] active_epoch;
    wire active, done, fault, child_cancel, needs_drain;
    wire [3:0] fault_code;
    wire [7:0] committed_tiles;

    z100_conv_rom_prefetch dut(.*);

    reg [31:0] expected_plan[0:3212];
    integer expected_runs[0:188], expected_windows[0:188];
    integer run_prefix[0:188], window_prefix[0:188];
    integer event_start[0:62], event_count[0:62], event_code[0:62];
    integer cycle_count=0;
    reg load_pending_q=0, tile_pending_q=0;
    reg [3:0] load_left_q=0, tile_left_q=0, drain_left_q=0;
    reg load_bank_q=0, tile_bank_q=0;
    reg [31:0] load_job_q=0, tile_job_q=0, tile_epoch_q=0;
    integer load_y_q=0, load_rows_q=0, tile_iy_q=0, tile_ir_q=0, tile_oy_q=0, tile_or_q=0;
    reg [31:0] tile_token_q=0, tile_tag_q=0;

    wire load_done_model = load_pending_q && load_left_q==0;
    wire tile_done_model = tile_pending_q && tile_left_q==0;
    assign load_done=load_done_model;
    assign load_epoch=cmd_epoch_for_load;
    assign load_done_bank=load_bank_q;
    assign tile_done=tile_done_model;
    assign tile_done_epoch=tile_epoch_q;
    assign tile_done_job=tile_job_q;
    assign tile_done_bank=tile_bank_q;
    assign load_quiet=!load_pending_q;
    assign tile_write_quiet=!tile_pending_q && drain_left_q==0;
    assign all_io_quiet=load_quiet && tile_write_quiet;

    integer current_start=0, current_count=0, current_event=0;
    integer expected_job_base=0, expected_token_base=0, expected_tag_base=0;
    integer expected_first_bank=0;
    integer expect_enable=0;
    integer descriptor_count=0, load_accepts=0, tile_accepts=0;
    integer opposite_bank_overlap=0, aggregate_overlap=0;
    integer load_held_cycles=0, tile_held_cycles=0, descriptor_held_cycles=0;
    integer total_tiles=0, total_events=0, total_runs=0, total_windows=0;
    integer negative_cases=0, mutation_cases=0, cancel_cases=0, lease_loss_cases=0, child_fault_cases=0;
    integer next_fault_epoch=64, next_fault_job=30000, fault_sequence=0;
    integer nonconv_event=2;
    reg [255:0] event_present=256'd0;
    integer i,j,k,gidx,local_index,timeout_count,run_sum,window_sum;
    integer global_tile, event_no, count_temp;

    reg prev_load_stall=0, prev_tile_stall=0, prev_descriptor_stall=0;
    reg prev_load_bank=0, prev_tile_bank=0;
    reg [31:0] prev_load_job=0, prev_tile_job=0, prev_tile_token=0, prev_tile_tag=0;
    reg [9:0] prev_load_y=0, prev_load_rows=0;
    reg [9:0] prev_tile_iy=0, prev_tile_ir=0, prev_tile_oy=0, prev_tile_or=0;
    reg [31:0] prev_desc_epoch=0, prev_desc_runs=0, prev_desc_windows=0;
    reg [7:0] prev_desc_index=0;
    reg [9:0] prev_desc_iy=0, prev_desc_ir=0, prev_desc_oy=0, prev_desc_orows=0;
    integer bad_before_count=0;
    reg [319:0] saved_record0, saved_record1;

    always @* begin
        load_ready=(cycle_count%4!=1);
        tile_ready=(cycle_count%5!=2);
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            cycle_count=0;
            load_pending_q=0; tile_pending_q=0;
            load_left_q=0; tile_left_q=0; drain_left_q=0;
            load_epoch_q=0; load_bank_q=0; tile_bank_q=0;
            load_job_q=0; tile_job_q=0; tile_epoch_q=0;
            load_y_q=0; load_rows_q=0; tile_iy_q=0; tile_ir_q=0; tile_oy_q=0; tile_or_q=0;
            tile_token_q=0; tile_tag_q=0;
            prev_load_stall=0; prev_tile_stall=0; prev_descriptor_stall=0;
        end else begin
            cycle_count<=cycle_count+1;
            if (prev_load_stall && !child_cancel &&
                {load_valid,load_bank,load_job_tag,load_input_y,load_input_rows} !==
                {1'b1,prev_load_bank,prev_load_job,prev_load_y,prev_load_rows})
                $fatal(1,"held load command changed under backpressure");
            if (load_valid && !load_ready) load_held_cycles=load_held_cycles+1;
            if (prev_tile_stall && !child_cancel &&
                {tile_valid,tile_bank,tile_job_tag,tile_token_base,tile_tag_base,
                 tile_input_y,tile_input_rows,tile_output_y,tile_output_rows} !==
                {1'b1,prev_tile_bank,prev_tile_job,prev_tile_token,prev_tile_tag,
                 prev_tile_iy,prev_tile_ir,prev_tile_oy,prev_tile_or})
                $fatal(1,"held tile command changed under backpressure");
            if (tile_valid && !tile_ready) tile_held_cycles=tile_held_cycles+1;
            if (prev_descriptor_stall && !child_cancel &&
                {dut.descriptor_valid,dut.descriptor_epoch_q,dut.descriptor_index_q,
                 dut.descriptor_input_y_q,dut.descriptor_input_rows_q,
                 dut.descriptor_output_y_q,dut.descriptor_output_rows_q,
                 dut.descriptor_runs_q,dut.descriptor_windows_q} !==
                {1'b1,prev_desc_epoch,prev_desc_index,prev_desc_iy,prev_desc_ir,
                 prev_desc_oy,prev_desc_orows,prev_desc_runs,prev_desc_windows})
                $fatal(1,"held ROM descriptor changed under controller backpressure");
            if (dut.descriptor_valid && !dut.controller_descriptor_ready)
                descriptor_held_cycles=descriptor_held_cycles+1;
            prev_load_stall=load_valid && !load_ready;
            if (prev_load_stall) begin
                prev_load_bank=load_bank; prev_load_job=load_job_tag;
                prev_load_y=load_input_y; prev_load_rows=load_input_rows;
            end
            prev_tile_stall=tile_valid && !tile_ready;
            if (prev_tile_stall) begin
                prev_tile_bank=tile_bank; prev_tile_job=tile_job_tag;
                prev_tile_token=tile_token_base; prev_tile_tag=tile_tag_base;
                prev_tile_iy=tile_input_y; prev_tile_ir=tile_input_rows;
                prev_tile_oy=tile_output_y; prev_tile_or=tile_output_rows;
            end
            prev_descriptor_stall=dut.descriptor_valid && !dut.controller_descriptor_ready;
            if (prev_descriptor_stall) begin
                prev_desc_epoch=dut.descriptor_epoch_q; prev_desc_index=dut.descriptor_index_q;
                prev_desc_iy=dut.descriptor_input_y_q; prev_desc_ir=dut.descriptor_input_rows_q;
                prev_desc_oy=dut.descriptor_output_y_q; prev_desc_orows=dut.descriptor_output_rows_q;
                prev_desc_runs=dut.descriptor_runs_q; prev_desc_windows=dut.descriptor_windows_q;
            end

            if (load_pending_q && tile_pending_q && load_bank_q!=tile_bank_q)
                opposite_bank_overlap=opposite_bank_overlap+1;
            if (dut.load_valid && dut.tile_valid && dut.load_bank!=dut.tile_bank)
                aggregate_overlap=aggregate_overlap+1;

            if (expect_enable && producer_context_valid) begin
                gidx=current_start*17;
                if (producer_event!==current_event[7:0] ||
                    producer_cin!==expected_plan[gidx+0][15:0] ||
                    producer_input_height!==expected_plan[gidx+1][15:0] ||
                    producer_input_width!==expected_plan[gidx+2][15:0] ||
                    producer_cout!==expected_plan[gidx+9][15:0] ||
                    producer_output_height!==expected_plan[gidx+7][15:0] ||
                    producer_output_width!==expected_plan[gidx+8][15:0] ||
                    producer_kernel!==expected_plan[gidx+10][15:0] ||
                    producer_stride!==expected_plan[gidx+11][15:0] ||
                    producer_padding!==expected_plan[gidx+12][15:0] ||
                    producer_parameter_first!==expected_plan[gidx+16][15:0])
                    $fatal(1,"producer context mismatch event=%0d",current_event);
            end

            if (expect_enable && dut.descriptor_valid && dut.controller_descriptor_ready) begin
                local_index=descriptor_count;
                gidx=(current_start+local_index)*17;
                if (local_index>=current_count || dut.descriptor_index_q!==local_index[7:0] ||
                    dut.descriptor_input_y_q!==expected_plan[gidx+3][9:0] ||
                    dut.descriptor_input_rows_q!==expected_plan[gidx+4][9:0] ||
                    dut.descriptor_output_y_q!==expected_plan[gidx+5][9:0] ||
                    dut.descriptor_output_rows_q!==expected_plan[gidx+6][9:0] ||
                    dut.descriptor_runs_q!==expected_runs[current_start+local_index] ||
                    dut.descriptor_windows_q!==expected_windows[current_start+local_index])
                    $fatal(1,"ROM descriptor differs from raw C oracle event=%0d local=%0d",current_event,local_index);
                descriptor_count=descriptor_count+1;
            end

            if (expect_enable && load_valid) begin
                local_index=load_job_tag-expected_job_base;
                if (local_index<0 || local_index>=current_count)
                    $fatal(1,"load job outside active C event");
                gidx=(current_start+local_index)*17;
                if (load_bank!==(expected_first_bank^(local_index&1)) ||
                    load_input_y!==expected_plan[gidx+3][9:0] ||
                    load_input_rows!==expected_plan[gidx+4][9:0])
                    $fatal(1,"load command differs from raw C oracle event=%0d local=%0d",current_event,local_index);
            end
            if (expect_enable && tile_valid) begin
                local_index=tile_job_tag-expected_job_base;
                if (local_index<0 || local_index>=current_count)
                    $fatal(1,"tile job outside active C event");
                gidx=(current_start+local_index)*17;
                run_sum=run_prefix[current_start+local_index]-run_prefix[current_start];
                window_sum=window_prefix[current_start+local_index]-window_prefix[current_start];
                if (tile_bank!==(expected_first_bank^(local_index&1)) ||
                    tile_input_y!==expected_plan[gidx+3][9:0] ||
                    tile_input_rows!==expected_plan[gidx+4][9:0] ||
                    tile_output_y!==expected_plan[gidx+5][9:0] ||
                    tile_output_rows!==expected_plan[gidx+6][9:0] ||
                    tile_token_base!==(expected_token_base+run_sum) ||
                    tile_tag_base!==(expected_tag_base+window_sum))
                    $fatal(1,"tile command context differs from raw C oracle event=%0d local=%0d",current_event,local_index);
            end
            if (load_valid && load_ready) load_accepts=load_accepts+1;
            if (tile_valid && tile_ready) tile_accepts=tile_accepts+1;

            if (load_pending_q && !load_done_model && load_left_q!=0)
                load_left_q<=load_left_q-1'b1;
            if (load_done_model) begin
                load_pending_q<=0;
                load_left_q<=0;
            end else if (load_valid && load_ready) begin
                load_pending_q<=1;
                load_left_q<=4'd2;
                load_epoch_q<=active_epoch;
                load_bank_q<=load_bank;
                load_job_q<=load_job_tag;
                load_y_q<=load_input_y;
                load_rows_q<=load_input_rows;
            end

            if (tile_pending_q && !tile_done_model && tile_left_q!=0)
                tile_left_q<=tile_left_q-1'b1;
            if (tile_done_model) begin
                tile_pending_q<=0;
                tile_left_q<=0;
                drain_left_q<=4'd3;
            end else if (tile_valid && tile_ready) begin
                tile_pending_q<=1;
                tile_left_q<=4'd3;
                tile_epoch_q<=active_epoch;
                tile_bank_q<=tile_bank;
                tile_job_q<=tile_job_tag;
                tile_token_q<=tile_token_base;
                tile_tag_q<=tile_tag_base;
                tile_iy_q<=tile_input_y;
                tile_ir_q<=tile_input_rows;
                tile_oy_q<=tile_output_y;
                tile_or_q<=tile_output_rows;
            end
            if (!tile_done_model && drain_left_q!=0) drain_left_q<=drain_left_q-1'b1;
        end
    end

    task step;
        begin @(posedge clk); #1; end
    endtask

    task issue_command;
        integer t;
        begin
            cmd_valid=1;
            t=0;
            while (!cmd_ready && t<1000) begin step; t=t+1; end
            if (!cmd_ready) $fatal(1,"wrapper command admission timeout");
            step;
            cmd_valid=0;
        end
    endtask

    task wait_for_done;
        integer t;
        begin
            t=0;
            while (!done && !fault && t<200000) begin step; t=t+1; end
            if (!done || fault) $fatal(1,"event did not complete cleanly fault=%0d code=%0d",fault,fault_code);
        end
    endtask

    task wait_for_fault;
        integer t;
        begin
            t=0;
            while (!fault && t<10000) begin step; t=t+1; end
            if (!fault) $fatal(1,"expected fail-closed fault did not occur");
        end
    endtask

    task wait_for_quiet;
        integer t;
        begin
            t=0;
            while ((!all_io_quiet || !load_quiet || !tile_write_quiet) && t<10000) begin step; t=t+1; end
            if (!all_io_quiet || !load_quiet || !tile_write_quiet)
                $fatal(1,"synthetic child work did not drain");
        end
    endtask

    task recover_fault;
        begin
            wait_for_quiet;
            recover=1; recovery_drained=0;
            repeat (2) step;
            if (!fault || !needs_drain) $fatal(1,"recovery escaped before caller's drained indication");
            recovery_drained=1;
            repeat (2) step;
            recover=0; recovery_drained=0;
            step;
            if (fault || needs_drain || active) $fatal(1,"drained recovery did not return wrapper/controller idle");
            cancel=0; source_leased=1; destination_reserved=1;
        end
    endtask

    task setup_fault_command;
        input integer ecode;
        input integer job;
        input integer token;
        input integer tag;
        begin
            expect_enable=0;
            cmd_epoch=ecode; cmd_event=event_code[0]; cmd_model_crc=32'd2213989717;
            cmd_job_base=job; cmd_token_base=token; cmd_tag_base=tag; cmd_first_bank=0;
            cmd_valid=0; cancel=0; recover=0; recovery_drained=0;
            source_leased=1; destination_reserved=1;
            load_fault=0; tile_fault=0;
            descriptor_count=0; load_accepts=0; tile_accepts=0;
        end
    endtask

    task run_success_event;
        input integer eidx;
        integer t;
        begin
            current_start=event_start[eidx]; current_count=event_count[eidx]; current_event=event_code[eidx];
            expected_job_base=1000+eidx*256;
            expected_token_base=10000+eidx*1000000;
            expected_tag_base=20000+eidx*1000000;
            expected_first_bank=eidx&1;
            expect_enable=1;
            descriptor_count=0; load_accepts=0; tile_accepts=0;
            cmd_epoch=eidx+1; cmd_event=current_event[7:0]; cmd_model_crc=32'd2213989717;
            cmd_job_base=expected_job_base; cmd_token_base=expected_token_base;
            cmd_tag_base=expected_tag_base; cmd_first_bank=expected_first_bank;
            issue_command;
            wait_for_done;
            if (descriptor_count!=current_count || load_accepts!=current_count || tile_accepts!=current_count)
                $fatal(1,"event metadata count mismatch event=%0d desc=%0d load=%0d tile=%0d expected=%0d",
                       current_event,descriptor_count,load_accepts,tile_accepts,current_count);
            if (committed_tiles!=current_count || !all_io_quiet || !load_quiet || !tile_write_quiet)
                $fatal(1,"done preceded all tile commits and child drains event=%0d",current_event);
            total_events=total_events+1;
            total_tiles=total_tiles+descriptor_count;
            for (t=0;t<current_count;t=t+1) begin
                total_runs=total_runs+expected_runs[current_start+t];
                total_windows=total_windows+expected_windows[current_start+t];
            end
            expect_enable=0;
        end
    endtask

    task cancel_and_recover;
        begin
            cancel=1;
            step;
            cancel=0;
            wait_for_fault;
            if (!child_cancel || !needs_drain) $fatal(1,"cancel did not retain external child cancel/drain state");
            cancel_cases=cancel_cases+1;
            recover_fault;
        end
    endtask

    task prepare_fault_job;
        begin
            fault_sequence=fault_sequence+1;
            setup_fault_command(next_fault_epoch, next_fault_job, 32'h00100000+fault_sequence*100000,
                                32'h00200000+fault_sequence*100000);
            next_fault_epoch=next_fault_epoch+1;
            next_fault_job=next_fault_job+256;
        end
    endtask

    task start_fault_job;
        begin prepare_fault_job; issue_command; end
    endtask

    initial begin
        $readmemh("expected_plan.hex",expected_plan);
        global_tile=0; event_no=0; run_sum=0; window_sum=0;
        for (i=0;i<189;i=i+1) begin
            expected_runs[i]=((expected_plan[i*17+9]+31)/32)*expected_plan[i*17+6]*
                             ((expected_plan[i*17+8]+19)/20);
            expected_windows[i]=expected_runs[i]*((expected_plan[i*17+0]+3)/4)*
                                expected_plan[i*17+10]*expected_plan[i*17+10];
            run_prefix[i]=run_sum; window_prefix[i]=window_sum;
            run_sum=run_sum+expected_runs[i]; window_sum=window_sum+expected_windows[i];
        end
        while (global_tile<189) begin
            if (event_no>=63) $fatal(1,"C oracle has too many Conv groups");
            event_start[event_no]=global_tile;
            event_code[event_no]=expected_plan[global_tile*17+13];
            event_present[event_code[event_no]]=1'b1;
            event_count[event_no]=expected_plan[global_tile*17+15];
            if (event_count[event_no]<=0 || event_count[event_no]>189)
                $fatal(1,"invalid C event count");
            for (j=0;j<event_count[event_no];j=j+1) begin
                k=(global_tile+j)*17;
                if (expected_plan[k+13]!=event_code[event_no] || expected_plan[k+14]!=j ||
                    expected_plan[k+15]!=event_count[event_no])
                    $fatal(1,"C plan event grouping mismatch");
            end
            global_tile=global_tile+event_count[event_no];
            event_no=event_no+1;
        end
        if (event_no!=63 || run_sum!=26380 || window_sum!=1659840)
            $fatal(1,"independent C plan cardinality/totals mismatch events=%0d runs=%0d windows=%0d",event_no,run_sum,window_sum);
        if (event_present[2]) begin
            nonconv_event=1;
            while (nonconv_event<255 && event_present[nonconv_event]) nonconv_event=nonconv_event+1;
            if (nonconv_event>=255) $fatal(1,"no non-Conv event id available in byte range");
        end

        source_leased=1; destination_reserved=1;
        repeat (4) step;
        rst_n=1;
        step;
        for (i=0;i<63;i=i+1) run_success_event(i);
        if (total_events!=63 || total_tiles!=189 || total_runs!=26380 || total_windows!=1659840)
            $fatal(1,"full event totals mismatch events=%0d tiles=%0d runs=%0d windows=%0d",total_events,total_tiles,total_runs,total_windows);
        if (opposite_bank_overlap<=0 || aggregate_overlap<=0)
            $fatal(1,"real ROM/controller run observed no opposite-bank load/compute overlap");
        if (load_held_cycles<=0 || tile_held_cycles<=0 || descriptor_held_cycles<=0)
            $fatal(1,"held-valid backpressure was not observed load=%0d tile=%0d descriptor=%0d",
                   load_held_cycles,tile_held_cycles,descriptor_held_cycles);

        // Abort before the first ROM request can be accepted.
        start_fault_job;
        cancel_and_recover;
        // Abort after the synchronous ROM has returned its first response.
        start_fault_job;
        step;
        if (!dut.rom_result_valid) $fatal(1,"expected first ROM response for post-response cancel");
        cancel_and_recover;

        // Wrong response identity is rejected before the first descriptor or child command.
        start_fault_job;
        step;
        if (!dut.rom_result_valid) $fatal(1,"expected ROM response for identity mutation");
        force dut.rom_result_tag=32'hdeadbeef;
        step;
        release dut.rom_result_tag;
        wait_for_fault;
        if (load_accepts!=0 || tile_accepts!=0) $fatal(1,"wrong ROM identity leaked child commands");
        negative_cases=negative_cases+1; recover_fault;

        // CRC, unknown event, non-Conv event, zero epoch and derived job wrap.
        prepare_fault_job; cmd_model_crc=0; issue_command; wait_for_fault;
        if (load_accepts!=0 || tile_accepts!=0) $fatal(1,"bad CRC leaked child commands");
        negative_cases=negative_cases+1; recover_fault;
        prepare_fault_job; cmd_event=0; issue_command; wait_for_fault;
        if (load_accepts!=0 || tile_accepts!=0) $fatal(1,"unknown event leaked child commands");
        negative_cases=negative_cases+1; recover_fault;
        prepare_fault_job; cmd_event=nonconv_event; issue_command; wait_for_fault;
        if (load_accepts!=0 || tile_accepts!=0) $fatal(1,"non-Conv event leaked child commands");
        negative_cases=negative_cases+1; recover_fault;
        setup_fault_command(0,next_fault_job,32'h400000,32'h500000); issue_command; wait_for_fault;
        if (load_accepts!=0 || tile_accepts!=0) $fatal(1,"zero epoch leaked child commands");
        negative_cases=negative_cases+1; recover_fault;
        prepare_fault_job; cmd_job_base=32'hffffffff; issue_command; wait_for_fault;
        if (load_accepts!=0 || tile_accepts!=0) $fatal(1,"derived job overflow leaked child commands");
        negative_cases=negative_cases+1; recover_fault;

        // ROM reserved-bit mutation is confined to the simulation copy of the ROM array.
        prepare_fault_job;
        saved_record0=dut.u_plan_rom.tile_rom[event_start[0]];
        dut.u_plan_rom.tile_rom[event_start[0]][319]=1'b1;
        issue_command;
        wait_for_fault;
        if (load_accepts!=0 || tile_accepts!=0) $fatal(1,"malformed first ROM record leaked child commands");
        dut.u_plan_rom.tile_rom[event_start[0]]=saved_record0;
        mutation_cases=mutation_cases+1; recover_fault;

        // Producer invariant mutation on descriptor 1 is caught before any later child command.
        prepare_fault_job;
        saved_record1=dut.u_plan_rom.tile_rom[event_start[0]+1];
        dut.u_plan_rom.tile_rom[event_start[0]+1][80]=~dut.u_plan_rom.tile_rom[event_start[0]+1][80];
        issue_command;
        wait_for_fault;
        bad_before_count=load_accepts+tile_accepts;
        repeat (12) step;
        if (load_accepts+tile_accepts!=bad_before_count)
            $fatal(1,"child command launched after malformed producer context was detected");
        dut.u_plan_rom.tile_rom[event_start[0]+1]=saved_record1;
        mutation_cases=mutation_cases+1; recover_fault;

        // Cancellation while an actual synthetic load is outstanding.
        start_fault_job;
        timeout_count=0;
        while (!(load_valid && load_ready) && timeout_count<10000) begin step; timeout_count=timeout_count+1; end
        if (!(load_valid && load_ready)) $fatal(1,"load cancellation setup timed out");
        step; cancel_and_recover;

        // Cancellation while a tile command is outstanding.
        start_fault_job;
        timeout_count=0;
        while (!(tile_valid && tile_ready) && timeout_count<10000) begin step; timeout_count=timeout_count+1; end
        if (!(tile_valid && tile_ready)) $fatal(1,"compute cancellation setup timed out");
        step; cancel_and_recover;

        // Cancellation after tile completion but before the write-drain indication.
        start_fault_job;
        timeout_count=0;
        while (!tile_done && timeout_count<10000) begin step; timeout_count=timeout_count+1; end
        if (!tile_done) $fatal(1,"write-drain cancellation setup timed out");
        step;
        if (tile_write_quiet) $fatal(1,"write-drain fixture already quiet");
        cancel_and_recover;

        // Losing a held destination reservation fails closed and keeps cancellation asserted.
        start_fault_job;
        timeout_count=0;
        while (!(load_valid && load_ready) && timeout_count<10000) begin step; timeout_count=timeout_count+1; end
        if (!(load_valid && load_ready)) $fatal(1,"reservation-loss setup timed out");
        step; destination_reserved=0; step;
        if (!fault || !child_cancel) $fatal(1,"lost destination reservation did not fault/cancel children");
        destination_reserved=1; lease_loss_cases=lease_loss_cases+1; recover_fault;

        // Losing the leased input source has the same external drain contract.
        start_fault_job;
        timeout_count=0;
        while (!(load_valid && load_ready) && timeout_count<10000) begin step; timeout_count=timeout_count+1; end
        if (!(load_valid && load_ready)) $fatal(1,"source-lease loss setup timed out");
        step; source_leased=0; step;
        if (!fault || !child_cancel) $fatal(1,"lost source lease did not fault/cancel children");
        source_leased=1; lease_loss_cases=lease_loss_cases+1; recover_fault;

        // Both external child fault pins propagate through the wrapper and hold drain state.
        start_fault_job;
        timeout_count=0;
        while (!(load_valid && load_ready) && timeout_count<10000) begin step; timeout_count=timeout_count+1; end
        if (!(load_valid && load_ready)) $fatal(1,"load-fault setup timed out");
        step; load_fault=1; step;
        if (!fault || !child_cancel || fault_code!=4'd3) $fatal(1,"load child fault was not preserved");
        load_fault=0; child_fault_cases=child_fault_cases+1; recover_fault;

        start_fault_job;
        timeout_count=0;
        while (!(tile_valid && tile_ready) && timeout_count<10000) begin step; timeout_count=timeout_count+1; end
        if (!(tile_valid && tile_ready)) $fatal(1,"tile-fault setup timed out");
        step; tile_fault=1; step;
        if (!fault || !child_cancel || fault_code!=4'd3) $fatal(1,"tile child fault was not preserved");
        tile_fault=0; child_fault_cases=child_fault_cases+1; recover_fault;

        if (negative_cases<6 || mutation_cases!=2 || cancel_cases<5 || lease_loss_cases!=2 || child_fault_cases!=2)
            $fatal(1,"negative/mutation/cancel coverage undercount");
        $display("CONV_ROM_PREFETCH_PASS events=63 tiles=189 runs=26380 windows=1659840 opposite_bank_overlap=%0d descriptor_count=%0d negative_cases=%0d mutations=%0d cancel_recovery=%0d load_held=%0d tile_held=%0d descriptor_held=%0d lease_loss=%0d child_faults=%0d",
                 opposite_bank_overlap,total_tiles,negative_cases,mutation_cases,cancel_cases,
                 load_held_cycles,tile_held_cycles,descriptor_held_cycles,lease_loss_cases,child_fault_cases);
        $finish;
    end

    initial begin #500000000; $fatal(1,"ROM-prefetch integrated watchdog"); end
endmodule
`default_nettype wire
