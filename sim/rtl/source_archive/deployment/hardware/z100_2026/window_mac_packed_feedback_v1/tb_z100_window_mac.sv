`timescale 1ns/1ps
module tb_z100_window_mac;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0,cancel=0,cfg_begin=0,cfg_weight_valid=0,cfg_bias_valid=0,cfg_commit=0;
    wire cfg_begin_ready,cfg_weight_ready,cfg_bias_ready,cfg_commit_ready;
    reg [31:0] cfg_epoch=0;
    reg [10:0] cfg_groups=0;
    reg [1023:0] cfg_weights=0,cfg_bias=0;
    wire weights_valid,error_valid;
    wire [31:0] weights_epoch;
    wire [2:0] error_code;
    reg run_valid=0;
    wire run_ready;
    reg [31:0] run_epoch=0,run_token=0;
    reg [5:0] run_lanes=0;
    reg [3:0] run_sites=0;
    reg act_valid=0;
    wire act_ready;
    reg [31:0] act_token=0;
    reg act_last=0;
    reg [127:0] act_data=0;
    wire out_valid,out_last;
    reg out_ready=0;
    wire [31:0] out_token;
    wire [3:0] out_site;
    wire [5:0] out_lanes;
    wire [1023:0] out_data;
    wire [31:0] out_overflow;
    z100_window_mac dut(.*);
    reg signed [7:0] w[0:1023][0:3][0:31];
    reg signed [7:0] a[0:1023][0:3][0:3];
    reg signed [31:0] biases[0:31];
    longint signed reference_sum[0:3][0:31];
    longint signed partial, wa, aa;
    reg [1023:0] held_data;
    reg [31:0] held_overflow;
    integer jobs=0,products_checked=0,metadata_checked=0,overflow_flags_checked=0,stalls=0,errors=0,replays=0;
    integer config_errors=0,run_errors=0,cross_checks=0,saturation_checks=0;
    integer k,t,l,s,n,groups,lanes,sites,kind,trial,offset;

    task automatic step;
        begin @(posedge clk); #1; end
    endtask
    task automatic expect_error(input integer code);
        begin
            if(!error_valid || error_code!=code || out_valid)
                $fatal(1,"Expected error%0d actual%0d valid%0d",code,error_code,error_valid);
            errors=errors+1;
        end
    endtask
    task automatic make_values(input integer seed,count,mode);
        integer group,tap,lane,site;
        begin
            for(lane=0;lane<32;lane=lane+1)
                biases[lane]=(lane%2==0) ? 32'sh7fff3caf : -32'sh7fff3cb0;
            for(group=0;group<count;group=group+1)
                for(tap=0;tap<4;tap=tap+1) begin
                    for(lane=0;lane<32;lane=lane+1)
                        w[group][tap][lane]=((seed*13+group*17+tap*91+lane*23)%256)-128;
                    for(site=0;site<4;site=site+1)
                        a[group][tap][site]=((seed*29+group*71+tap*11+site*47)%256)-128;
                end
            if(mode==1 || mode==2) begin
                for(lane=0;lane<32;lane=lane+1) begin
                    biases[lane]=(mode==1) ? 32'sd2147433647 : -32'sd2147433648;
                    for(group=0;group<count;group=group+1)
                        for(tap=0;tap<4;tap=tap+1) w[group][tap][lane]=(mode==1) ? 127 : -128;
                end
                for(site=0;site<4;site=site+1)
                    for(group=0;group<count;group=group+1)
                        for(tap=0;tap<4;tap=tap+1)
                            a[group][tap][site]=(group==0) ? 127 : ((tap==0) ? -128 : 0);
            end
            if(mode==3 || mode==4) begin
                for(lane=0;lane<32;lane=lane+1) begin
                    biases[lane]=(mode==3) ? 32'sd2147433647 : -32'sd2147433648;
                    for(group=0;group<count;group=group+1)
                        for(tap=0;tap<4;tap=tap+1)
                            w[group][tap][lane]=(mode==3) ? 127 : -128;
                end
                for(site=0;site<4;site=site+1)
                    for(group=0;group<count;group=group+1)
                        for(tap=0;tap<4;tap=tap+1)
                            a[group][tap][site]=127;
            end
        end
    endtask
    task automatic check_configuration_errors;
        integer tap,lane;
        begin
            @(negedge clk);#1;
            if(!cfg_begin_ready) $fatal(1,"Invalid epoch test could not begin");
            cfg_epoch=0;cfg_groups=1;cfg_begin=1;step();expect_error(1);config_errors=config_errors+1;
            @(negedge clk);cfg_begin=0;
            cfg_epoch=72;cfg_groups=0;cfg_begin=1;step();expect_error(1);config_errors=config_errors+1;
            @(negedge clk);cfg_begin=0;
            cfg_epoch=72;cfg_groups=1025;cfg_begin=1;step();expect_error(1);config_errors=config_errors+1;
            @(negedge clk);cfg_begin=0;
            cfg_epoch=72;cfg_groups=2;cfg_begin=1;step();
            @(negedge clk);cfg_begin=0;cfg_commit=1;step();expect_error(2);config_errors=config_errors+1;
            @(negedge clk);cfg_commit=0;
            cfg_epoch=72;cfg_groups=1;cfg_begin=1;step();
            @(negedge clk);cfg_begin=0;
            for(tap=0;tap<4;tap=tap+1)
                for(lane=0;lane<32;lane=lane+1) cfg_weights[(tap*32+lane)*8+:8]=0;
            cfg_weight_valid=1;step();@(negedge clk);cfg_weight_valid=0;
            cfg_weight_valid=1;step();expect_error(3);config_errors=config_errors+1;
            @(negedge clk);cfg_weight_valid=0;
            cfg_epoch=72;cfg_groups=1;cfg_begin=1;step();
            @(negedge clk);cfg_begin=0;
            cfg_weight_valid=1;step();@(negedge clk);cfg_weight_valid=0;
            cfg_bias=0;cfg_bias_valid=1;step();@(negedge clk);step();
            expect_error(3);config_errors=config_errors+1;
            @(negedge clk);cfg_bias_valid=0;
            cfg_epoch=72;cfg_groups=1;cfg_begin=1;step();
            @(negedge clk);cfg_begin=0;
            cfg_weight_valid=1;step();@(negedge clk);cfg_weight_valid=0;
            cfg_commit=1;step();expect_error(2);config_errors=config_errors+1;
            @(negedge clk);cfg_commit=0;
            if(!cfg_begin_ready || weights_valid) $fatal(1,"Malformed configuration did not recover cleanly");
        end
    endtask
    task automatic reject_run(input integer epoch,id,nlanes,nsites);
        begin
            @(negedge clk);#1;
            if(!run_ready) $fatal(1,"Invalid run test not ready");
            run_epoch=epoch;run_token=id;run_lanes=nlanes;run_sites=nsites;run_valid=1;
            step();expect_error(4);run_errors=run_errors+1;
            if(!run_ready || !weights_valid || weights_epoch!=73 || act_ready)
                $fatal(1,"Invalid run damaged committed weights or run state");
            @(negedge clk);run_valid=0;
        end
    endtask
    task automatic load_weights(input integer epoch,count);
        integer group,tap,lane;
        begin
            @(negedge clk); #1;
            if(!cfg_begin_ready) $fatal(1,"Loader begin not ready");
            cfg_epoch=epoch;cfg_groups=count;cfg_begin=1;step();
            if(weights_valid) $fatal(1,"Old weights remained valid");
            @(negedge clk);cfg_begin=0;
            for(group=0;group<count;group=group+1) begin
                #1;if(!cfg_weight_ready) $fatal(1,"Weight not ready");
                for(tap=0;tap<4;tap=tap+1)
                    for(lane=0;lane<32;lane=lane+1)
                        cfg_weights[(tap*32+lane)*8+:8]=w[group][tap][lane];
                cfg_weight_valid=1;step();
                @(negedge clk);
            end
            cfg_weight_valid=0;cfg_bias_valid=1;
            for(lane=0;lane<32;lane=lane+1) cfg_bias[lane*32+:32]=biases[lane];
            step();@(negedge clk);cfg_bias_valid=0;cfg_commit=1;step();
            if(!weights_valid || weights_epoch!=epoch || error_valid) $fatal(1,"Weight commit failed");
            @(negedge clk);cfg_commit=0;
        end
    endtask
    task automatic begin_run(input integer epoch,id,nlanes,nsites);
        begin
            #1;if(!run_ready) $fatal(1,"Run not ready");
            run_epoch=epoch;run_token=id;run_lanes=nlanes;run_sites=nsites;run_valid=1;
            step();if(error_valid || !act_ready) $fatal(1,"Run not accepted");
            @(negedge clk);run_valid=0;
        end
    endtask
    task automatic send_activation(input integer group,count,id,bubbles);
        integer tap,site;
        begin
            act_valid=0;
            repeat(bubbles) begin step();@(negedge clk);end
            #1;if(!act_ready) $fatal(1,"Activation not ready");
            for(tap=0;tap<4;tap=tap+1)
                for(site=0;site<4;site=site+1)
                    act_data[(tap*4+site)*8+:8]=a[group][tap][site];
            act_token=id;act_last=(group+1==count);act_valid=1;
            step();if(error_valid) $fatal(1,"Good input rejected");
            @(negedge clk);act_valid=0;
        end
    endtask
    task automatic check_results(input integer count,nlanes,nsites,id);
        integer site,lane,group,tap,waits,hold;
        reg [31:0] expected;
        reg overflow;
        longint signed sum,partial,widened_w,widened_a;
        begin
            for(site=0;site<nsites;site=site+1)
                for(lane=0;lane<nlanes;lane=lane+1) begin
                    sum=biases[lane];
                    for(group=0;group<count;group=group+1) begin
                        partial=0;
                        for(tap=0;tap<4;tap=tap+1) begin
                            widened_w=w[group][tap][lane];widened_a=a[group][tap][site];
                            partial=partial+widened_w*widened_a;
                        end
                        sum=sum+partial;
                        if(group==0 && kind==1 && sum<=64'sd2147483647)
                            $fatal(1,"Positive directed case did not cross INT32_MAX at the group boundary");
                        if(group==count-1 && kind==1 && (sum>64'sd2147483647 || sum< -64'sd2147483648))
                            $fatal(1,"Positive directed case did not return inside INT32 after the next group");
                        if(group==0 && kind==2 && sum>= -64'sd2147483648)
                            $fatal(1,"Negative directed case did not cross INT32_MIN at the group boundary");
                        if(group==count-1 && kind==2 && (sum>64'sd2147483647 || sum< -64'sd2147483648))
                            $fatal(1,"Negative directed case did not return inside INT32 after the next group");
                    end
                    if(kind==1 || kind==2) cross_checks=cross_checks+1;
                    if(kind==3 && sum<=64'sd2147483647) $fatal(1,"Positive final saturation vector did not overflow");
                    if(kind==4 && sum>= -64'sd2147483648) $fatal(1,"Negative final saturation vector did not overflow");
                    if(kind==3 || kind==4) saturation_checks=saturation_checks+1;
                    reference_sum[site][lane]=sum;
                end
            for(site=0;site<nsites;site=site+1) begin
                waits=0;
                while(!out_valid) begin
                    step();@(negedge clk);waits=waits+1;
                    if(waits>12) $fatal(1,"Result timeout");
                end
                if(out_token!=id || out_site!=site || out_lanes!=nlanes || out_last!=(site+1==nsites))
                    $fatal(1,"Result metadata mismatch");
                metadata_checked=metadata_checked+1;
                for(lane=0;lane<32;lane=lane+1) begin
                    sum=(lane<nlanes) ? reference_sum[site][lane] : 0;
                    overflow=(sum>64'sd2147483647 || sum< -64'sd2147483648);
                    expected=(sum>64'sd2147483647) ? 32'h7fffffff : ((sum< -64'sd2147483648) ? 32'h80000000 : sum[31:0]);
                    if(out_data[lane*32+:32]!==expected || out_overflow[lane]!==overflow)
                        $fatal(1,"Numeric mismatch job%0d site%0d lane%0d got%h expected%h sum%0d",jobs,site,lane,out_data[lane*32+:32],expected,sum);
                    products_checked=products_checked+1;
                    overflow_flags_checked=overflow_flags_checked+1;
                end
                held_data=out_data;held_overflow=out_overflow;
                for(hold=0;hold<(site+id)%4+1;hold=hold+1) begin
                    step();@(negedge clk);stalls=stalls+1;
                    if(!out_valid || out_data!==held_data || out_overflow!==held_overflow || act_ready || cfg_begin_ready)
                        $fatal(1,"Stalled raw result changed");
                end
                out_ready=1;step();@(negedge clk);out_ready=0;
            end
            jobs=jobs+1;
            if(out_valid || !run_ready) $fatal(1,"Job did not finish");
        end
    endtask
    initial begin
        // Give vendor global primitives their required startup interval.
        #250;
        repeat(3) step();@(negedge clk);rst_n=1;
        check_configuration_errors();
        make_values(73,1,0);load_weights(73,1);
        reject_run(72,73,1,1);
        reject_run(73,0,1,1);
        reject_run(73,73,0,1);
        reject_run(73,73,33,1);
        reject_run(73,73,1,0);
        reject_run(73,73,1,5);
        for(trial=0;trial<25;trial=trial+1) begin
            case(trial%7)
                0:groups=1;1:groups=2;2:groups=7;3:groups=36;
                4:groups=144;5:groups=576;default:groups=1024;
            endcase
            kind=(trial==1) ? 1 : ((trial==8) ? 2 : ((trial==15) ? 3 : ((trial==22) ? 4 : 0)));
            if(kind==1 || kind==2) groups=2;
            if(kind==3 || kind==4) groups=1;
            make_values(trial+1,groups,kind);
            load_weights(trial+1,groups);
            lanes=1+(trial*7)%32;sites=1+trial%4;
            begin_run(trial+1,2*trial+1,lanes,sites);
            for(k=0;k<groups;k=k+1) send_activation(k,groups,2*trial+1,(k+trial)%4==0 ? 1 : 0);
            check_results(groups,lanes,sites,2*trial+1);
            // Reuse the weight epoch with a different stream/token and shape.
            begin_run(trial+1,2*trial+2,32,4);
            for(k=0;k<groups;k=k+1) send_activation(k,groups,2*trial+2,0);
            check_results(groups,32,4,2*trial+2);replays=replays+1;
        end
        // Reset and cancel at each of the five input-to-result boundaries.
        for(trial=0;trial<2;trial=trial+1)
            for(offset=0;offset<5;offset=offset+1) begin
                make_values(91,1,0);load_weights(91,1);begin_run(91,91,32,4);
                send_activation(0,1,91,0);
                repeat(offset) begin step();@(negedge clk);end
                if(trial==0) cancel=1;else rst_n=0;
                step();@(negedge clk);cancel=0;rst_n=1;
                repeat(8) begin
                    step();@(negedge clk);
                    if(out_valid || weights_valid || run_ready) $fatal(1,"Stale result after flush");
                end
            end
        // Invalid stream token and malformed final-group flags invalidate weights.
        for(trial=0;trial<3;trial=trial+1) begin
            groups=(trial==2) ? 6 : 2;
            make_values(71,groups,0);load_weights(71,groups);begin_run(71,71,9,1);
            if(trial<2) begin
                act_valid=1;act_token=(trial==0) ? 70 : 71;act_last=(trial==1);
                step();expect_error(5);
            end else begin
                for(k=0;k<4;k=k+1) send_activation(k,groups,71,0);
                act_valid=1;act_token=70;act_last=0;step();expect_error(5);
            end
            if(weights_valid || act_ready) $fatal(1,"Bad stream did not invalidate");
            repeat(8) begin
                step();@(negedge clk);
                if(out_valid) $fatal(1,"Malformed later beat leaked a result");
            end
            act_valid=0;
        end
        if(jobs!=50 || replays!=25 || cross_checks==0 || saturation_checks==0 || config_errors!=7 || run_errors!=6)
            $fatal(1,"Coverage totals jobs=%0d replays=%0d cross=%0d saturations=%0d cfg_errors=%0d run_errors=%0d",jobs,replays,cross_checks,saturation_checks,config_errors,run_errors);
        $display("WINDOW_MAC_PASS jobs=%0d replays=%0d raw_words=%0d overflow_flags=%0d metadata_sites=%0d stalls=%0d stream_errors=%0d config_errors=%0d run_errors=%0d cross_checks=%0d saturation_checks=%0d cancel_offsets=5 reset_offsets=5 max_groups=1024",jobs,replays,products_checked,overflow_flags_checked,metadata_checked,stalls,errors-config_errors-run_errors,config_errors,run_errors,cross_checks,saturation_checks);
        $finish;
    end
    initial begin #10000000;$fatal(1,"MAC watchdog");end
endmodule
