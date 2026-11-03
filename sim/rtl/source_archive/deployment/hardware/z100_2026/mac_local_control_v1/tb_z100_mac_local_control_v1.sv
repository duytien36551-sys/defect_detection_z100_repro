`timescale 1ns/1ps
`default_nettype none

module tb_z100_mac_local_control_v1 #(parameter integer SITES=1);
    reg clk=1'b0;
    always #5 clk=~clk;
    reg rst_n=1'b0;
    reg cancel=1'b0;
    reg cfg_begin=1'b0;
    reg [31:0] cfg_epoch=32'd0;
    reg [10:0] cfg_groups=11'd0;
    reg cfg_weight_valid=1'b0;
    reg [1023:0] cfg_weights=1024'd0;
    reg cfg_bias_valid=1'b0;
    reg [1023:0] cfg_bias=1024'd0;
    reg cfg_commit=1'b0;
    reg run_valid=1'b0;
    reg [31:0] run_epoch=32'd0;
    reg [31:0] run_token=32'd0;
    reg [5:0] run_lanes=6'd0;
    reg [4:0] run_sites=5'd0;
    reg act_valid=1'b0;
    reg [31:0] act_token=32'd0;
    reg act_last=1'b0;
    reg [4*SITES*8-1:0] act_data={(4*SITES*8){1'b0}};
    reg out_ready=1'b0;

    wire ref_cfg_begin_ready, ref_cfg_weight_ready, ref_cfg_bias_ready, ref_cfg_commit_ready;
    wire ref_weights_valid, ref_error_valid, ref_run_ready, ref_act_ready, ref_out_valid;
    wire [31:0] ref_weights_epoch, ref_out_token;
    wire [2:0] ref_error_code;
    wire [4:0] ref_out_site;
    wire ref_out_last;
    wire [5:0] ref_out_lanes;
    wire [1023:0] ref_out_data;
    wire [31:0] ref_out_overflow;

    wire cand_cfg_begin_ready, cand_cfg_weight_ready, cand_cfg_bias_ready, cand_cfg_commit_ready;
    wire cand_weights_valid, cand_error_valid, cand_run_ready, cand_act_ready, cand_out_valid;
    wire [31:0] cand_weights_epoch, cand_out_token;
    wire [2:0] cand_error_code;
    wire [4:0] cand_out_site;
    wire cand_out_last;
    wire [5:0] cand_out_lanes;
    wire [1023:0] cand_out_data;
    wire [31:0] cand_out_overflow;

    z100_window_mac #(.SITES(SITES)) reference_mac (
        .clk(clk),.rst_n(rst_n),.cancel(cancel),
        .cfg_begin(cfg_begin),.cfg_begin_ready(ref_cfg_begin_ready),
        .cfg_epoch(cfg_epoch),.cfg_groups(cfg_groups),
        .cfg_weight_valid(cfg_weight_valid),.cfg_weight_ready(ref_cfg_weight_ready),
        .cfg_weights(cfg_weights),.cfg_bias_valid(cfg_bias_valid),
        .cfg_bias_ready(ref_cfg_bias_ready),.cfg_bias(cfg_bias),
        .cfg_commit(cfg_commit),.cfg_commit_ready(ref_cfg_commit_ready),
        .weights_valid(ref_weights_valid),.weights_epoch(ref_weights_epoch),
        .error_valid(ref_error_valid),.error_code(ref_error_code),
        .run_valid(run_valid),.run_ready(ref_run_ready),.run_epoch(run_epoch),
        .run_token(run_token),.run_lanes(run_lanes),.run_sites(run_sites),
        .act_valid(act_valid),.act_ready(ref_act_ready),.act_token(act_token),
        .act_last(act_last),.act_data(act_data),
        .out_valid(ref_out_valid),.out_ready(out_ready),.out_token(ref_out_token),
        .out_site(ref_out_site),.out_last(ref_out_last),.out_lanes(ref_out_lanes),
        .out_data(ref_out_data),.out_overflow(ref_out_overflow)
    );

    z100_window_mac_local_control_v1 #(.SITES(SITES)) candidate_mac (
        .clk(clk),.rst_n(rst_n),.cancel(cancel),
        .cfg_begin(cfg_begin),.cfg_begin_ready(cand_cfg_begin_ready),
        .cfg_epoch(cfg_epoch),.cfg_groups(cfg_groups),
        .cfg_weight_valid(cfg_weight_valid),.cfg_weight_ready(cand_cfg_weight_ready),
        .cfg_weights(cfg_weights),.cfg_bias_valid(cfg_bias_valid),
        .cfg_bias_ready(cand_cfg_bias_ready),.cfg_bias(cfg_bias),
        .cfg_commit(cfg_commit),.cfg_commit_ready(cand_cfg_commit_ready),
        .weights_valid(cand_weights_valid),.weights_epoch(cand_weights_epoch),
        .error_valid(cand_error_valid),.error_code(cand_error_code),
        .run_valid(run_valid),.run_ready(cand_run_ready),.run_epoch(run_epoch),
        .run_token(run_token),.run_lanes(run_lanes),.run_sites(run_sites),
        .act_valid(act_valid),.act_ready(cand_act_ready),.act_token(act_token),
        .act_last(act_last),.act_data(act_data),
        .out_valid(cand_out_valid),.out_ready(out_ready),.out_token(cand_out_token),
        .out_site(cand_out_site),.out_last(cand_out_last),.out_lanes(cand_out_lanes),
        .out_data(cand_out_data),.out_overflow(cand_out_overflow)
    );

    wire [1143:0] reference_public={ref_cfg_begin_ready,ref_cfg_weight_ready,
        ref_cfg_bias_ready,ref_cfg_commit_ready,ref_weights_valid,ref_weights_epoch,
        ref_error_valid,ref_error_code,ref_run_ready,ref_act_ready,ref_out_valid,
        ref_out_token,ref_out_site,ref_out_last,ref_out_lanes,ref_out_data,ref_out_overflow};
    wire [1143:0] candidate_public={cand_cfg_begin_ready,cand_cfg_weight_ready,
        cand_cfg_bias_ready,cand_cfg_commit_ready,cand_weights_valid,cand_weights_epoch,
        cand_error_valid,cand_error_code,cand_run_ready,cand_act_ready,cand_out_valid,
        cand_out_token,cand_out_site,cand_out_last,cand_out_lanes,cand_out_data,cand_out_overflow};

    integer accepted_runs=0;
    integer accepted_inputs=0;
    integer output_transfers=0;
    integer output_stall_cycles=0;
    integer error4_checks=0;
    integer error5_checks=0;
    integer saturation_checks=0;
    integer lane_tail_checks=0;
    integer site_tail_checks=0;
    integer cycle_checks=0;
    integer expected_site=0;
    integer expected_sites=0;
    integer expected_lanes=0;
    integer expected_mode=0; // 0=arithmetic miter only, 1=positive, 2=negative saturation
    reg [31:0] expected_token=32'd0;
    reg output_stalled=1'b0;
    reg [1099:0] held_output=1100'd0;
    integer lane_check;

    always @(posedge clk) begin
        if (!rst_n) begin
            output_stalled=1'b0;
        end else begin
            cycle_checks=cycle_checks+1;
            if (run_valid && ref_run_ready) accepted_runs=accepted_runs+1;
            if (act_valid && ref_act_ready) accepted_inputs=accepted_inputs+1;
            if (ref_error_valid && ref_error_code==3'd4) error4_checks=error4_checks+1;
            if (ref_error_valid && ref_error_code==3'd5) error5_checks=error5_checks+1;

            if (output_stalled && !cancel &&
                (!ref_out_valid || {ref_out_token,ref_out_site,ref_out_last,ref_out_lanes,
                                    ref_out_data,ref_out_overflow}!==held_output))
                $fatal(1,"SITES=%0d reference output changed while stalled",SITES);
            output_stalled=ref_out_valid && !out_ready;
            if (output_stalled) begin
                output_stall_cycles=output_stall_cycles+1;
                held_output={ref_out_token,ref_out_site,ref_out_last,ref_out_lanes,
                             ref_out_data,ref_out_overflow};
            end

            if (ref_out_valid && out_ready) begin
                if (ref_out_token!==expected_token || ref_out_site!==expected_site[4:0] ||
                    ref_out_last!==(expected_site+1==expected_sites) ||
                    ref_out_lanes!==expected_lanes[5:0])
                    $fatal(1,"SITES=%0d output metadata/token/last mismatch",SITES);
                if (expected_sites<SITES) site_tail_checks=site_tail_checks+1;
                for (lane_check=0;lane_check<32;lane_check=lane_check+1) begin
                    if (lane_check>=expected_lanes) begin
                        if (ref_out_data[lane_check*32+:32]!==32'd0 || ref_out_overflow[lane_check]!==1'b0)
                            $fatal(1,"SITES=%0d inactive lane tail not zero lane=%0d",SITES,lane_check);
                        lane_tail_checks=lane_tail_checks+1;
                    end else if (expected_mode==1) begin
                        if (ref_out_data[lane_check*32+:32]!==32'h7fffffff ||
                            ref_out_overflow[lane_check]!==1'b1)
                            $fatal(1,"SITES=%0d positive accumulator saturation lane=%0d",SITES,lane_check);
                        saturation_checks=saturation_checks+1;
                    end else if (expected_mode==2) begin
                        if (ref_out_data[lane_check*32+:32]!==32'h80000000 ||
                            ref_out_overflow[lane_check]!==1'b1)
                            $fatal(1,"SITES=%0d negative accumulator saturation lane=%0d",SITES,lane_check);
                        saturation_checks=saturation_checks+1;
                    end
                end
                output_transfers=output_transfers+1;
                expected_site=expected_site+1;
            end
            #1;
            if (reference_public!==candidate_public)
                $fatal(1,"SITES=%0d public-cycle mismatch cycle=%0d",SITES,cycle_checks);
        end
    end

    task automatic configure(input [31:0] epoch, input integer groups,
                             input [31:0] bias_word, input [7:0] weight_byte);
        integer group_index, lane_index;
        begin
            @(negedge clk); cfg_epoch=epoch; cfg_groups=groups; cfg_begin=1'b1;
            if (!ref_cfg_begin_ready) $fatal(1,"SITES=%0d config begin blocked",SITES);
            @(posedge clk); #1;
            if (ref_error_valid) $fatal(1,"SITES=%0d config begin error=%0d",SITES,ref_error_code);
            @(negedge clk); cfg_begin=1'b0; cfg_weights={128{weight_byte}};
            #1;
            for (group_index=0;group_index<groups;group_index=group_index+1) begin
                if (!ref_cfg_weight_ready) $fatal(1,"SITES=%0d weight write blocked",SITES);
                cfg_weight_valid=1'b1; @(posedge clk); #1;
                if (ref_error_valid) $fatal(1,"SITES=%0d valid weight rejected",SITES);
                @(negedge clk); cfg_weight_valid=1'b0;
            end
            cfg_bias=1024'd0;
            for (lane_index=0;lane_index<32;lane_index=lane_index+1)
                cfg_bias[lane_index*32+:32]=bias_word;
            cfg_bias_valid=1'b1; @(posedge clk); #1;
            if (ref_error_valid) $fatal(1,"SITES=%0d valid bias rejected",SITES);
            @(negedge clk); cfg_bias_valid=1'b0; cfg_commit=1'b1;
            @(posedge clk); #1;
            if (!ref_weights_valid || ref_weights_epoch!==epoch || ref_error_valid)
                $fatal(1,"SITES=%0d config commit failed",SITES);
            @(negedge clk); cfg_commit=1'b0;
        end
    endtask

    task automatic reject_run(input [31:0] epoch, input [31:0] token,
                              input [5:0] lanes, input [4:0] sites);
        begin
            @(negedge clk); run_epoch=epoch; run_token=token; run_lanes=lanes;
            run_sites=sites; run_valid=1'b1;
            if (!ref_run_ready) $fatal(1,"SITES=%0d invalid run was not admitted for checking",SITES);
            @(posedge clk); #1;
            if (!ref_error_valid || ref_error_code!=3'd4)
                $fatal(1,"SITES=%0d expected run error 4 got valid=%0d code=%0d",SITES,ref_error_valid,ref_error_code);
            @(negedge clk); run_valid=1'b0;
            @(posedge clk); #1;
        end
    endtask

    task automatic start_run(input [31:0] token, input [5:0] lanes,
                             input [4:0] sites, input integer mode);
        begin
            @(negedge clk); expected_token=token; expected_lanes=lanes;
            expected_sites=sites; expected_site=0; expected_mode=mode;
            run_epoch=ref_weights_epoch; run_token=token; run_lanes=lanes;
            run_sites=sites; run_valid=1'b1;
            if (!ref_run_ready) $fatal(1,"SITES=%0d valid run not ready",SITES);
            @(posedge clk); #1;
            if (ref_error_valid || !ref_act_ready)
                $fatal(1,"SITES=%0d valid run rejected",SITES);
            @(negedge clk); run_valid=1'b0;
        end
    endtask

    task automatic send_group(input [7:0] activation_byte, input bit last_value,
                              input [31:0] token_value, input integer expect_error);
        integer byte_index;
        begin
            @(negedge clk); act_token=token_value; act_last=last_value;
            for (byte_index=0;byte_index<4*SITES;byte_index=byte_index+1)
                act_data[byte_index*8+:8]=activation_byte;
            act_valid=1'b1;
            if (!ref_act_ready) $fatal(1,"SITES=%0d activation not ready",SITES);
            @(posedge clk); #1;
            if (expect_error!=0) begin
                if (!ref_error_valid || ref_error_code!=3'd5)
                    $fatal(1,"SITES=%0d malformed activation error=%0d",SITES,ref_error_code);
                error5_checks=error5_checks+1;
            end else if (ref_error_valid) $fatal(1,"SITES=%0d valid activation rejected",SITES);
            @(negedge clk); act_valid=1'b0;
            if (expect_error!=0) begin
                @(posedge clk); #1;
            end
        end
    endtask

    task automatic drain_with_stall(input integer hold_cycles);
        integer stall_index;
        begin
            @(negedge clk); out_ready=1'b0;
            wait(ref_out_valid===1'b1);
            for (stall_index=0;stall_index<hold_cycles;stall_index=stall_index+1) @(posedge clk);
            @(negedge clk); out_ready=1'b1;
            wait(ref_out_valid===1'b1 && ref_out_last===1'b1);
            @(posedge clk); #2;
            @(negedge clk); out_ready=1'b0;
            if (expected_site!=expected_sites)
                $fatal(1,"SITES=%0d output site count %0d != %0d",SITES,expected_site,expected_sites);
            @(posedge clk); #1;
        end
    endtask

    task automatic cancel_stalled_output;
        integer k;
        begin
            @(negedge clk); out_ready=1'b0;
            wait(ref_out_valid===1'b1);
            repeat (3) @(posedge clk);
            @(negedge clk); cancel=1'b1;
            @(posedge clk); #1;
            @(negedge clk); cancel=1'b0;
            repeat (2) @(posedge clk);
            @(negedge clk); out_ready=1'b0;
        end
    endtask

    task automatic reset_mid_run;
        begin
            @(negedge clk); rst_n=1'b0;
            repeat (3) @(posedge clk);
            @(negedge clk); rst_n=1'b1;
            repeat (2) @(posedge clk);
        end
    endtask

    initial begin
        repeat (5) @(negedge clk);
        rst_n=1'b1;
        repeat (2) @(posedge clk);

        // Positive overflow, partial site count, lane tail and output stalls.
        configure(32'd101,1,32'h7fffffff,8'h7f);
        reject_run(32'd100,32'd11,6'd5,SITES[4:0]);
        reject_run(32'd101,32'd0,6'd5,SITES[4:0]);
        reject_run(32'd101,32'd11,6'd0,SITES[4:0]);
        reject_run(32'd101,32'd11,6'd5,SITES+1);
        start_run(32'd1001,6'd5,5'd1,1);
        send_group(8'h7f,1'b1,32'd1001,0);
        drain_with_stall(4);

        // Negative overflow and a 31-lane tail.
        configure(32'd102,1,32'h80000000,8'h81);
        start_run(32'd1002,6'd31,SITES[4:0],2);
        send_group(8'h7f,1'b1,32'd1002,0);
        drain_with_stall(3);

        // Consecutive multi-group activation, all sites, and a later drain.
        configure(32'd103,2,32'd0,8'h03);
        start_run(32'd1003,6'd17,SITES[4:0],0);
        send_group(8'hfd,1'b0,32'd1003,0);
        send_group(8'h02,1'b1,32'd1003,0);
        drain_with_stall(5);

        // Malformed accepted input aborts, invalidating the loaded run.
        configure(32'd104,1,32'd0,8'h01);
        start_run(32'd1004,6'd5,5'd1,0);
        send_group(8'h11,1'b0,32'd1004,1);

        // Cancel while a computed output is held under backpressure.
        configure(32'd105,1,32'd0,8'h05);
        start_run(32'd1005,6'd9,5'd1,0);
        send_group(8'h21,1'b1,32'd1005,0);
        cancel_stalled_output();

        // Cancel after the first group of a multi-group run.
        configure(32'd106,2,32'd0,8'h07);
        start_run(32'd1006,6'd13,SITES[4:0],0);
        send_group(8'h31,1'b0,32'd1006,0);
        @(negedge clk); cancel=1'b1;
        @(posedge clk); #1;
        @(negedge clk); cancel=1'b0;
        repeat (2) @(posedge clk);

        // Platform reset also clears the local control state mid-run.
        configure(32'd107,2,32'd0,8'h09);
        start_run(32'd1007,6'd15,SITES[4:0],0);
        send_group(8'h41,1'b0,32'd1007,0);
        reset_mid_run();

        // Wrong last marker reaches the same malformed-input recovery path.
        configure(32'd108,1,32'd0,8'h0b);
        start_run(32'd1008,6'd7,5'd1,0);
        send_group(8'h51,1'b0,32'd1008,1);

        // The second overflow run exercises drain-time mask clearing again.
        configure(32'd109,1,32'h7fffffff,8'h7f);
        start_run(32'd1009,6'd3,SITES[4:0],1);
        send_group(8'h7f,1'b1,32'd1009,0);
        drain_with_stall(2);

        if (accepted_runs<12 || accepted_inputs<11 || output_transfers<1 ||
            output_stall_cycles<10 || error4_checks<4 || error5_checks<2 ||
            saturation_checks<8 || lane_tail_checks==0 ||
            ((SITES>1) && site_tail_checks==0) || cycle_checks<100)
            $fatal(1,"SITES=%0d required miter scenario coverage missing",SITES);
        $display("MAC_LOCAL_CONTROL_MITER_PASS sites=%0d accepted_runs=%0d accepted_inputs=%0d output_transfers=%0d stalls=%0d error4=%0d error5=%0d saturation_lane_checks=%0d lane_tail_checks=%0d site_tail_checks=%0d public_cycles=%0d",
                 SITES,accepted_runs,accepted_inputs,output_transfers,output_stall_cycles,
                 error4_checks,error5_checks,saturation_checks,lane_tail_checks,site_tail_checks,cycle_checks);
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1,"SITES=%0d local-control equivalence watchdog",SITES);
    end
endmodule

`default_nettype wire
