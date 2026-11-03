`timescale 1ns/1ps
module tb_z100_mac_bias_local_control_v1;
    localparam integer SITES=20;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, cancel=0;
    reg cfg_begin=0, cfg_weight_valid=0, cfg_bias_valid=0, cfg_commit=0;
    reg [31:0] cfg_epoch=0;
    reg [10:0] cfg_groups=0;
    reg [1023:0] cfg_weights=0, cfg_bias=0;
    reg run_valid=0;
    reg [31:0] run_epoch=0, run_token=0;
    reg [5:0] run_lanes=0;
    reg [4:0] run_sites=0;
    reg act_valid=0;
    reg [31:0] act_token=0;
    reg act_last=0;
    reg [4*SITES*8-1:0] act_data=0;
    reg out_ready=0;

    wire [3:0] old_cfg_ready, new_cfg_ready;
    wire old_weights_valid, new_weights_valid;
    wire [31:0] old_weights_epoch, new_weights_epoch;
    wire old_error_valid, new_error_valid;
    wire [2:0] old_error_code, new_error_code;
    wire old_run_ready, new_run_ready, old_act_ready, new_act_ready;
    wire old_out_valid, new_out_valid;
    wire [31:0] old_out_token, new_out_token;
    wire [4:0] old_out_site, new_out_site;
    wire old_out_last, new_out_last;
    wire [5:0] old_out_lanes, new_out_lanes;
    wire [1023:0] old_out_data, new_out_data;
    wire [31:0] old_out_overflow, new_out_overflow;
    reg [31:0] expected_bias[0:31];
    reg [1023:0] held_data;
    integer lane, wait_count, stall_count;

    z100_window_mac_local_control_v1_baseline #(.SITES(SITES)) old_mac (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(old_cfg_ready[0]),
        .cfg_epoch(cfg_epoch), .cfg_groups(cfg_groups),
        .cfg_weight_valid(cfg_weight_valid), .cfg_weight_ready(old_cfg_ready[1]),
        .cfg_weights(cfg_weights), .cfg_bias_valid(cfg_bias_valid), .cfg_bias_ready(old_cfg_ready[2]),
        .cfg_bias(cfg_bias), .cfg_commit(cfg_commit), .cfg_commit_ready(old_cfg_ready[3]),
        .weights_valid(old_weights_valid), .weights_epoch(old_weights_epoch),
        .error_valid(old_error_valid), .error_code(old_error_code),
        .run_valid(run_valid), .run_ready(old_run_ready), .run_epoch(run_epoch), .run_token(run_token),
        .run_lanes(run_lanes), .run_sites(run_sites), .act_valid(act_valid), .act_ready(old_act_ready),
        .act_token(act_token), .act_last(act_last), .act_data(act_data),
        .out_valid(old_out_valid), .out_ready(out_ready), .out_token(old_out_token),
        .out_site(old_out_site), .out_last(old_out_last), .out_lanes(old_out_lanes),
        .out_data(old_out_data), .out_overflow(old_out_overflow)
    );
    z100_window_mac_local_control_v1 #(.SITES(SITES)) new_mac (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_begin(cfg_begin), .cfg_begin_ready(new_cfg_ready[0]),
        .cfg_epoch(cfg_epoch), .cfg_groups(cfg_groups),
        .cfg_weight_valid(cfg_weight_valid), .cfg_weight_ready(new_cfg_ready[1]),
        .cfg_weights(cfg_weights), .cfg_bias_valid(cfg_bias_valid), .cfg_bias_ready(new_cfg_ready[2]),
        .cfg_bias(cfg_bias), .cfg_commit(cfg_commit), .cfg_commit_ready(new_cfg_ready[3]),
        .weights_valid(new_weights_valid), .weights_epoch(new_weights_epoch),
        .error_valid(new_error_valid), .error_code(new_error_code),
        .run_valid(run_valid), .run_ready(new_run_ready), .run_epoch(run_epoch), .run_token(run_token),
        .run_lanes(run_lanes), .run_sites(run_sites), .act_valid(act_valid), .act_ready(new_act_ready),
        .act_token(act_token), .act_last(act_last), .act_data(act_data),
        .out_valid(new_out_valid), .out_ready(out_ready), .out_token(new_out_token),
        .out_site(new_out_site), .out_last(new_out_last), .out_lanes(new_out_lanes),
        .out_data(new_out_data), .out_overflow(new_out_overflow)
    );

    task automatic check_public;
        begin
            if(new_mac.gen_bias_local_control[0].local_loading_q !== new_mac.loading ||
               new_mac.gen_bias_local_control[1].local_loading_q !== new_mac.loading ||
               new_mac.gen_bias_local_control[2].local_loading_q !== new_mac.loading ||
               new_mac.gen_bias_local_control[3].local_loading_q !== new_mac.loading ||
               new_mac.gen_bias_local_control[0].local_bias_loaded_q !== new_mac.bias_loaded ||
               new_mac.gen_bias_local_control[1].local_bias_loaded_q !== new_mac.bias_loaded ||
               new_mac.gen_bias_local_control[2].local_bias_loaded_q !== new_mac.bias_loaded ||
               new_mac.gen_bias_local_control[3].local_bias_loaded_q !== new_mac.bias_loaded ||
               new_mac.gen_bias_local_control[0].local_loading_q !== old_mac.loading ||
               new_mac.gen_bias_local_control[1].local_loading_q !== old_mac.loading ||
               new_mac.gen_bias_local_control[2].local_loading_q !== old_mac.loading ||
               new_mac.gen_bias_local_control[3].local_loading_q !== old_mac.loading ||
               new_mac.gen_bias_local_control[0].local_bias_loaded_q !== old_mac.bias_loaded ||
               new_mac.gen_bias_local_control[1].local_bias_loaded_q !== old_mac.bias_loaded ||
               new_mac.gen_bias_local_control[2].local_bias_loaded_q !== old_mac.bias_loaded ||
               new_mac.gen_bias_local_control[3].local_bias_loaded_q !== old_mac.bias_loaded)
                $fatal(1,"Local config replica state diverged from the frozen FSM");
            if(old_cfg_ready !== new_cfg_ready || old_weights_valid !== new_weights_valid ||
               old_weights_epoch !== new_weights_epoch || old_error_valid !== new_error_valid ||
               old_error_code !== new_error_code || old_run_ready !== new_run_ready ||
               old_act_ready !== new_act_ready || old_out_valid !== new_out_valid)
                $fatal(1,"Control/valid mismatch oldcfg=%b newcfg=%b olderr=%b/%0d newerr=%b/%0d oldout=%b newout=%b",
                    old_cfg_ready,new_cfg_ready,old_error_valid,old_error_code,new_error_valid,new_error_code,
                    old_out_valid,new_out_valid);
            if(old_out_valid &&
               (old_out_token !== new_out_token || old_out_site !== new_out_site ||
                old_out_last !== new_out_last || old_out_lanes !== new_out_lanes ||
                old_out_data !== new_out_data || old_out_overflow !== new_out_overflow))
                $fatal(1,"Valid output mismatch");
        end
    endtask
    task automatic tick;
        begin @(posedge clk); #1; check_public(); end
    endtask
    task automatic set_bias_pattern(input integer seed);
        integer i;
        begin
            for(i=0;i<32;i=i+1) begin
                case(i)
                    0: cfg_bias[i*32+:32]=32'h00000000;
                    1: cfg_bias[i*32+:32]=32'h7fffffff;
                    2: cfg_bias[i*32+:32]=32'h80000000;
                    default: cfg_bias[i*32+:32]=(seed*32'h01010101) ^ (i*32'h10204081);
                endcase
            end
        end
    endtask
    task automatic remember_bias;
        integer i;
        begin for(i=0;i<32;i=i+1) expected_bias[i]=cfg_bias[i*32+:32]; end
    endtask
    task automatic check_internal_bias;
        integer i;
        begin
            for(i=0;i<32;i=i+1) begin
                if(old_mac.bias[i] !== new_mac.bias[i])
                    $fatal(1,"Old/new bias mismatch lane%0d old=%h new=%h",i,old_mac.bias[i],new_mac.bias[i]);
                if(old_mac.bias[i] !== expected_bias[i])
                    $fatal(1,"Bias byte oracle mismatch lane%0d got=%h expected=%h",i,old_mac.bias[i],expected_bias[i]);
            end
        end
    endtask
    task automatic begin_config(input [31:0] epoch, input [10:0] groups);
        begin
            @(negedge clk); cfg_epoch=epoch; cfg_groups=groups; cfg_begin=1;
            tick();
            @(negedge clk); cfg_begin=0;
        end
    endtask
    task automatic write_one_weight;
        begin
            @(negedge clk); cfg_weights=0; cfg_weight_valid=1;
            tick();
            if(!old_cfg_ready[1] || !new_cfg_ready[1]) $fatal(1,"Weight handshake missing");
            @(negedge clk); cfg_weight_valid=0;
        end
    endtask
    task automatic expect_error(input [2:0] code);
        begin
            if(!old_error_valid || old_error_code!==code || !new_error_valid || new_error_code!==code)
                $fatal(1,"Expected matching error %0d old=%b/%0d new=%b/%0d",code,
                    old_error_valid,old_error_code,new_error_valid,new_error_code);
        end
    endtask

    initial begin
        repeat(3) tick();
        @(negedge clk); rst_n=1;
        tick();

        // Bad begin while bias_valid is asserted must not write any lane.
        set_bias_pattern(77);
        @(negedge clk); cfg_epoch=0; cfg_groups=1; cfg_begin=1; cfg_bias_valid=1;
        tick(); expect_error(1);
        @(negedge clk); cfg_begin=0; cfg_bias_valid=0;
        for(lane=0;lane<32;lane=lane+1) expected_bias[lane]=old_mac.bias[lane];
        check_internal_bias();

        // Repeated bias reports error 3 and does not overwrite the first accepted payload.
        begin_config(1,1);
        write_one_weight();
        @(negedge clk); set_bias_pattern(3); cfg_bias_valid=1;
        tick(); remember_bias(); check_internal_bias();
        @(negedge clk); set_bias_pattern(9); cfg_bias_valid=1;
        tick(); expect_error(3); check_internal_bias();
        @(negedge clk); cfg_bias_valid=0;

        // Commit has priority over a coincident bias; it rejects the incomplete config.
        begin_config(2,1);
        set_bias_pattern(8);
        @(negedge clk); cfg_bias_valid=1; cfg_commit=1;
        tick(); expect_error(2); check_internal_bias();
        @(negedge clk); cfg_bias_valid=0; cfg_commit=0;

        // Weight overflow and first bias on one edge preserve both original NBA effects:
        // loading closes with error 3 while bias_loaded and all 32 payload words update.
        begin_config(3,1);
        write_one_weight();
        @(negedge clk); set_bias_pattern(12); cfg_weight_valid=1; cfg_bias_valid=1;
        tick(); expect_error(3); remember_bias(); check_internal_bias();
        @(negedge clk); cfg_weight_valid=0; cfg_bias_valid=0;

        // A cfg_begin pulse while already loading is not accepted and blocks bias capture.
        begin_config(4,1);
        set_bias_pattern(41);
        @(negedge clk); cfg_begin=1; cfg_epoch=41; cfg_groups=1; cfg_bias_valid=1;
        tick();
        if(old_cfg_ready[0] || new_cfg_ready[0]) $fatal(1,"Loading unexpectedly accepted another begin");
        check_internal_bias();
        @(negedge clk); cfg_begin=0; cfg_bias_valid=0;

        // Cancel clears both global and local FSM state, then configuration can restart.
        @(negedge clk); cancel=1;
        tick();
        @(negedge clk); cancel=0;
        tick();
        if(!old_cfg_ready[0] || !new_cfg_ready[0]) $fatal(1,"Cancel did not return config FSM to idle");

        // Reset during a fresh load also clears both replicated state machines.
        begin_config(40,1);
        @(negedge clk); rst_n=0;
        tick();
        @(negedge clk); rst_n=1;
        tick();
        if(!old_cfg_ready[0] || !new_cfg_ready[0]) $fatal(1,"Reset did not return config FSM to idle");
        check_internal_bias();

        // Successful configuration with zero weights makes the output a direct bias oracle.
        begin_config(5,1);
        write_one_weight();
        @(negedge clk); set_bias_pattern(13); cfg_bias_valid=1;
        tick(); remember_bias(); check_internal_bias();
        @(negedge clk); cfg_bias_valid=0; cfg_commit=1;
        tick();
        if(!old_weights_valid || !new_weights_valid || old_weights_epoch!==5 || new_weights_epoch!==5)
            $fatal(1,"Valid config commit failed");
        @(negedge clk); cfg_commit=0;

        // One valid MAC transaction; compare its complete payload and held-stall behavior.
        @(negedge clk); run_epoch=5; run_token=32'h12345678; run_lanes=32; run_sites=1; run_valid=1;
        tick();
        if(!old_act_ready || !new_act_ready) $fatal(1,"Accepted run did not open input");
        @(negedge clk); run_valid=0; act_valid=1; act_token=32'h12345678; act_last=1; act_data=0;
        tick();
        @(negedge clk); act_valid=0;
        wait_count=0;
        while(!new_out_valid && wait_count<16) begin
            @(negedge clk); tick(); wait_count=wait_count+1;
        end
        if(!new_out_valid || !new_out_last || new_out_site!==0 || new_out_token!==32'h12345678)
            $fatal(1,"Valid transaction timed out or metadata mismatch");
        for(lane=0;lane<32;lane=lane+1) begin
            if(new_out_data[lane*32+:32]!==expected_bias[lane] || new_out_overflow[lane]!==1'b0)
                $fatal(1,"Bias result oracle lane%0d got=%h expected=%h",lane,new_out_data[lane*32+:32],expected_bias[lane]);
        end
        held_data=new_out_data;
        for(stall_count=0;stall_count<3;stall_count=stall_count+1) begin
            @(negedge clk); tick();
            if(!new_out_valid || new_out_data!==held_data || old_out_data!==held_data)
                $fatal(1,"Output changed under backpressure");
        end
        @(negedge clk); out_ready=1;
        tick();
        @(negedge clk); out_ready=0;
        if(new_out_valid) $fatal(1,"Output did not retire");

        $display("MAC_BIAS_LOCAL_CONTROL_PASS groups=4 lanes_per_group=8 bias_lanes=32 cfg_errors=3 overflow_bias_nba=1 valid_jobs=1 stall_cycles=3");
        $finish;
    end
    initial begin #200000; $fatal(1,"Miter watchdog"); end
endmodule
