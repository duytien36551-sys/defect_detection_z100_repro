`timescale 1ns/1ps
module tb_z100_maxpool_collect32;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cfg_valid=0,in_valid=0,out_ready=0;
    wire cfg_ready,in_ready,out_valid,out_last,done,error_valid,active;
    reg [31:0] cfg_epoch=200,cfg_input_token_base=1,cfg_output_token=1;
    reg [5:0] cfg_lanes=32;
    reg [31:0] in_epoch=200,in_token=1;reg [6:0] in_lanes=80;reg [639:0] in_data=0;
    wire [31:0] out_epoch,out_token;wire [4:0] out_site;wire [5:0] out_lanes;wire [255:0] out_data;
    z100_maxpool_collect32 dut(.*);
    integer cases=0,errors=0,beats=0,holds=0,n,g,s,l,required,pattern;
    reg [255:0] expected;
    task tick;begin @(posedge clk);#1;end endtask
    task clear;
        begin @(negedge clk);cancel=1;in_valid=0;cfg_valid=0;tick();
            if(active||out_valid||done||error_valid)$fatal(1,"cancel");
            @(negedge clk);cancel=0;out_ready=0;
        end
    endtask
    task configure(input integer lanes);
        begin
            clear();cfg_epoch=200;cfg_input_token_base=1000+lanes*8;cfg_output_token=100+lanes;cfg_lanes=lanes;
            cfg_valid=1;#1;if(!cfg_ready)$fatal(1,"config not ready");tick();@(negedge clk);cfg_valid=0;
        end
    endtask
    task send(input integer group_num,lanes);
        integer ch,x;
        begin
            @(negedge clk);in_epoch=200;in_token=1000+lanes*8+group_num;
            in_lanes=((lanes-group_num*4)>=4)?80:(lanes-group_num*4)*20;
            for(ch=0;ch<4;ch=ch+1)for(x=0;x<20;x=x+1)
                in_data[(ch*20+x)*8+:8]=(group_num*4+ch)*37+x*17+lanes;
            in_valid=1;#1;if(!in_ready)$fatal(1,"input not ready");tick();@(negedge clk);in_valid=0;
        end
    endtask
    task check_case(input integer lanes);
        integer group_num,site,lane;
        reg [255:0] gold,held;
        begin
            configure(lanes);
            for(group_num=0;group_num<(lanes+3)/4;group_num=group_num+1)send(group_num,lanes);
            // Mutating inactive cfg ports must not affect the accepted block.
            cfg_epoch=999;cfg_input_token_base=0;cfg_output_token=0;cfg_lanes=0;cfg_valid=1;
            for(site=0;site<20;site=site+1)begin
                gold=0;for(lane=0;lane<lanes;lane=lane+1)gold[lane*8+:8]=lane*37+site*17+lanes;
                if(!out_valid||out_epoch!=200||out_token!=100+lanes||out_lanes!=lanes||out_site!=site||out_last!==(site==19)||out_data!==gold||cfg_ready)
                    $fatal(1,"collector case mismatch lanes=%0d site=%0d",lanes,site);
                held=out_data;
                repeat(2)begin tick();if(!out_valid||out_data!==held||out_site!=site)$fatal(1,"held result");holds=holds+1;end
                @(negedge clk);out_ready=1;tick();@(negedge clk);out_ready=0;beats=beats+1;
                if(site==19)cfg_valid=0;
            end
            if(active||out_valid||!done||error_valid)$fatal(1,"collector done");
            cases=cases+1;
        end
    endtask
    task expect_error;
        begin if(!error_valid||active||out_valid)$fatal(1,"error did not invalidate");errors=errors+1;
            tick();if(error_valid)$fatal(1,"error not a pulse");end
    endtask
    initial begin
        repeat(5)tick();@(negedge clk);rst_n=1;
        check_case(1);check_case(3);check_case(4);check_case(5);check_case(9);
        check_case(16);check_case(17);check_case(31);check_case(32);
        for(pattern=0;pattern<6;pattern=pattern+1)begin
            clear();cfg_epoch=200;cfg_input_token_base=1;cfg_output_token=1;cfg_lanes=32;
            case(pattern)
                0:cfg_lanes=0;1:cfg_lanes=33;2:cfg_epoch=0;3:cfg_input_token_base=0;
                4:cfg_output_token=0;5:cfg_input_token_base=32'hffffffff;
            endcase
            cfg_valid=1;tick();@(negedge clk);cfg_valid=0;expect_error();check_case(1);
        end
        for(pattern=0;pattern<3;pattern=pattern+1)begin
            configure(9);send(0,9);
            @(negedge clk);in_epoch=200;in_token=1073;in_lanes=80;
            if(pattern==0)in_epoch=201;
            if(pattern==1)in_token=1072;
            if(pattern==2)in_lanes=60;
            in_valid=1;tick();@(negedge clk);in_valid=0;expect_error();check_case(1);
        end
        // Cancel/reset both a partially collected block and a held output.
        configure(32);send(0,32);clear();check_case(1);
        configure(1);send(0,1);clear();check_case(1);
        configure(32);send(0,32);@(negedge clk);rst_n=0;tick();if(active||out_valid)$fatal(1,"reset collect");
        @(negedge clk);rst_n=1;check_case(1);
        configure(1);send(0,1);@(negedge clk);rst_n=0;tick();if(active||out_valid)$fatal(1,"reset output");
        @(negedge clk);rst_n=1;check_case(1);
        if(cases!=22||errors!=9||beats!=440||holds!=880)$fatal(1,"coverage cases=%0d errors=%0d",cases,errors);
        $display("MAXPOOL_COLLECT_PASS cases=22 errors=9 output_beats=440 hold_cycles=880 tail_lanes=1,3,4,5,9,16,17,31,32 cancel_reset_phases=4 cfg_mutation=1");
        $finish;
    end
endmodule
