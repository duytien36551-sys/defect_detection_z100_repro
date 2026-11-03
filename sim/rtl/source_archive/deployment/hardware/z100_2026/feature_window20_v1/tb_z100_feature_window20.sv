`timescale 1ns/1ps
`default_nettype none
`include "fixture_defs.vh"
module tb_z100_feature_window20;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cfg_begin=0,cfg_word_valid=0,cfg_commit=0;
    wire cfg_begin_ready,cfg_word_ready,cfg_commit_ready,store_valid,loading,error_valid;
    wire[3:0]error_code;
    reg[31:0]cfg_epoch=77,cfg_word_epoch=77;
    reg[10:0]cfg_channels=7;
    reg[9:0]cfg_height=8,cfg_width=640;
    reg[12:0]cfg_word_address=0;
    reg cfg_word_last=0;
    reg[511:0]cfg_data=0;
    wire[31:0]active_epoch;
    reg window_valid=0;
    wire window_ready;
    reg[31:0]window_epoch=77,window_tag=0;
    reg[13:0]window_row_address=0;
    reg signed[11:0]window_first_x=0;
    reg[10:0]window_input_width=640,window_output_remaining=0;
    reg[4:0]window_sites=20;
    reg[3:0]window_channel_mask=15;
    reg window_stride_two=0,window_y_valid=1;
    wire out_valid;
    reg out_ready=0;
    wire[31:0]out_tag;
    wire[79:0]out_mask;
    wire[639:0]out_data;
    z100_feature_window20 dut(.*);
    reg[511:0]load_data[0:639];
    reg[12:0]load_addresses[0:639];
    reg[122:0]descriptors[0:`WINDOWS-1];
    reg[719:0]golden[0:`WINDOWS-1];
    integer sent=0,received=0,cycle=0,holds=0,thirdport=0,maxstreak=0,streak=0;
    integer i,b,errors=0,cancels=0;
    reg prevhold=0;
    reg[751:0]held;
    reg scoring=0;
    always @(posedge clk) begin
        cycle=cycle+1;
        if(scoring) begin
            if(error_valid)$fatal(1,"unexpected20site window error %0d",error_code);
            if(prevhold)begin
                if(!out_valid || {out_tag,out_mask,out_data}!==held)$fatal(1,"held20site response changed");
                holds=holds+1;
            end
            prevhold=out_valid&&!out_ready;
            if(prevhold)held={out_tag,out_mask,out_data};
            if(window_valid&&window_ready)sent=sent+1;
            if(out_valid&&out_ready)begin
                if(received>=`WINDOWS || out_tag!==(32'h42000000+received) ||
                   {out_mask,out_data}!==golden[received])$fatal(1,"20site direct CHW mismatch index=%0d tag=%h expectedtag=%h mask=%h expectedmask=%h data=%h expecteddata=%h",received,out_tag,32'h42000000+received,out_mask,golden[received][719:640],out_data,golden[received][639:0]);
                received=received+1;streak=streak+1;
                if(streak>maxstreak)maxstreak=streak;
            end else streak=0;
            if(dut.s0_valid&&dut.ram_req_ready)
                for(b=0;b<64;b=b+1)if(dut.s0_read_mask[b*4+2])thirdport=thirdport+1;
        end
    end
    always @(negedge clk)if(scoring)out_ready=(cycle%17<12);
    task automatic load_feature;
        begin
            @(negedge clk);cfg_begin=1;#1;
            if(!cfg_begin_ready)$fatal(1,"config begin blocked");
            @(posedge clk);@(negedge clk);cfg_begin=0;
            for(i=0;i<640;i=i+1)begin
                cfg_word_valid=1;cfg_word_address=load_addresses[i];cfg_data=load_data[i];cfg_word_last=(i==639);
                #1;if(!cfg_word_ready)$fatal(1,"20site load blocked %0d",i);
                @(posedge clk);@(negedge clk);
            end
            cfg_word_valid=0;cfg_commit=1;#1;if(!cfg_commit_ready)$fatal(1,"commit blocked");
            @(posedge clk);#1;if(!store_valid||error_valid)$fatal(1,"commit failed");
            @(negedge clk);cfg_commit=0;
        end
    endtask
    task automatic flush;
        begin
            @(negedge clk);cancel=1;
            @(posedge clk);#1;if(out_valid||window_ready||store_valid)$fatal(1,"20site cancel leaked epoch");
            @(negedge clk);cancel=0;window_valid=0;out_ready=0;cancels=cancels+1;
        end
    endtask
    initial begin
        $readmemh("load_data.hex",load_data);$readmemh("load_addresses.hex",load_addresses);
        $readmemh("descriptors.hex",descriptors);$readmemh("golden.hex",golden);
        repeat(5)@(negedge clk);rst_n=1;
        load_feature();scoring=1;
        for(i=0;i<`WINDOWS;i=i+1)begin
            @(negedge clk);
            {window_epoch,window_tag,window_row_address,window_first_x,window_input_width,
             window_output_remaining,window_sites,window_channel_mask,window_stride_two,window_y_valid}=descriptors[i];
            window_valid=1;#1;
            do @(posedge clk); while(!window_ready);
        end
        @(negedge clk);window_valid=0;
        while(received<`WINDOWS)@(negedge clk);
        scoring=0;prevhold=0;out_ready=0;
        if(sent!=`WINDOWS||holds==0||thirdport==0||maxstreak<2)$fatal(1,"20site normal coverage absent");
        // 21site exceeds the new 5bit descriptor contract and emits no response.
        @(negedge clk);window_sites=21;window_first_x=0;window_output_remaining=320;
        window_y_valid=1;window_channel_mask=15;window_valid=1;#1;
        do @(posedge clk); while(!window_ready);#1;if(!error_valid||error_code!=1||out_valid)$fatal(1,"21site invalid descriptor accepted");
        errors=errors+1;@(negedge clk);window_valid=0;
        flush();load_feature();
        // Hold a complete20site response, then cancel synchronously.
        @(negedge clk);
        {window_epoch,window_tag,window_row_address,window_first_x,window_input_width,
         window_output_remaining,window_sites,window_channel_mask,window_stride_two,window_y_valid}=descriptors[0];
        window_valid=1;#1;do @(posedge clk); while(!window_ready);
        @(negedge clk);window_valid=0;
        while(!out_valid)@(negedge clk);
        flush();load_feature();
        @(negedge clk);rst_n=0;@(posedge clk);#1;
        if(store_valid||out_valid||window_ready)$fatal(1,"20site reset leaked epoch");
        @(negedge clk);rst_n=1;load_feature();
        if(errors!=1||cancels!=2||!store_valid)$fatal(1,"20site recovery coverage");
        $display("FEATURE_WINDOW20_PASS windows=%0d bytes=%0d holds=%0d third_port_reads=%0d ii1_streak=%0d invalid=%0d cancels=%0d reset_reload=1",received,received*80,holds,thirdport,maxstreak,errors,cancels);
        $finish;
    end
    initial begin #10000000;$fatal(1,"20site watchdog");end
endmodule
`default_nettype wire
