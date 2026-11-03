`timescale 1ns/1ps
`default_nettype none
module tb_z100_feature_writepipe;
    reg clk=0;always #5 clk=~clk;reg rst_n=0,cancel=0,cb=0,wv=0,cc=0,rv=0;
    reg [10:0] channels=4;reg[9:0] width=16;reg[12:0] address=0;reg last=1;reg[511:0] data=0;
    wire cbr,wr,cr,rr,ov,sv,loading,error;wire[2:0] ec;wire[31:0] ep,oe;wire[1023:0] od;
    reg [1663:0] ra=0;
    z100_feature_banks_writepipe_4k_v5 dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),
        .cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(32'd200),.cfg_canonical_order(1'b1),.cfg_channels(channels),.cfg_height(10'd1),.cfg_width(width),
        .cfg_word_valid(wv),.cfg_word_ready(wr),.cfg_word_data(data),.cfg_word_epoch(32'd200),.cfg_word_address(address),.cfg_word_last(last),
        .cfg_commit(cc),.cfg_commit_ready(cr),.error_valid(error),.error_code(ec),.store_valid(sv),.active_epoch(ep),.loading(loading),
        .req_valid(rv),.req_ready(rr),.req_epoch(32'd200),.req_addresses(ra),.req_mask({128{1'b1}}),
        .out_valid(ov),.out_ready(1'b1),.out_epoch(oe),.out_data(od));
    wire[511:0] ram_word0,ram_word1;
    genvar bank;generate for(bank=0;bank<64;bank=bank+1)begin:probe
        assign ram_word0[bank*8+:8]=dut.gen_bank[bank].memory[0];
        assign ram_word1[bank*8+:8]=dut.gen_bank[bank].memory[1];
    end endgenerate
    integer accepts=0,physical_writes=0,commit_with_pending=0,cancel_pending=0,checks=0,errors=0;
    always @(posedge clk)if(rst_n)begin
        if(dut.write_fire)accepts<=accepts+1;
        if(dut.physical_write_fire)physical_writes<=physical_writes+1;
        if(cc&&cr&&dut.write_pending)commit_with_pending<=commit_with_pending+1;
        if(cancel&&dut.write_pending)begin
            if(dut.physical_write_fire)$fatal(1,"Cancelled pending write reached physical RAM");cancel_pending<=cancel_pending+1;
        end
        if(sv&&dut.write_pending)$fatal(1,"Published store still has an undrained write");
    end
    task tick;begin @(posedge clk);#1;end endtask
    task begin_load;begin
        @(negedge clk);cb=1;#1;if(!cbr)$fatal(1,"Writepipe begin not ready");tick();@(negedge clk);cb=0;
    end endtask
    task word(input[12:0] a,input[511:0] d,input integer final_word);begin
        @(negedge clk);wv=1;address=a;data=d;last=final_word;#1;if(!wr)$fatal(1,"Writepipe inserted input bubble");tick();
    end endtask
    task commit;begin
        @(negedge clk);wv=0;cc=1;#1;if(!cr||sv||!dut.write_pending)$fatal(1,"Last-word commit boundary missing");
        tick();if(!sv||loading||error||dut.write_pending)$fatal(1,"Commit exposed undrained RAM word");@(negedge clk);cc=0;
    end endtask
    integer i,b,p;reg[511:0] saved;
    initial begin
        repeat(5)tick();@(negedge clk);rst_n=1;
        begin_load();word(0,{64{8'h11}},1);commit();
        if(ram_word0!=={64{8'h11}})$fatal(1,"Final pending data absent at publication");
        begin_load();word(0,{64{8'h99}},1);
        @(negedge clk);wv=0;cancel=1;tick();if(ram_word0!=={64{8'h11}}||sv||dut.write_pending)$fatal(1,"Cancelled data changed RAM/publication");
        @(negedge clk);cancel=0;tick();
        width=64;begin_load();
        for(i=0;i<4;i=i+1)word(i,{64{8'h20+i[7:0]}},i==3);
        commit();
        for(i=0;i<4;i=i+1)begin
            @(negedge clk);rv=1;for(b=0;b<128;b=b+1)ra[b*13+:13]=i;
            #1;if(!rr)$fatal(1,"Committed stream read not ready");tick();if(!ov||oe!=200||error)$fatal(1,"Stream read response");
            for(b=0;b<64;b=b+1)for(p=0;p<2;p=p+1)begin
                if(od[(b*2+p)*8+:8]!==8'h20+i[7:0])$fatal(1,"Pipelined RAM stream data differs");checks=checks+1;
            end
            @(negedge clk);rv=0;tick();
        end
        channels=3;width=17;begin_load();data=0;data[383:0]={48{8'h55}};word(0,data,0);
        data=0;data[7:0]=8'h66;data[135:128]=8'h66;data[263:256]=8'h66;data[15:8]=8'hff;
        word(1,data,1);if(!error||ec!=4||sv||dut.write_pending)$fatal(1,"Bad padding entered pending write");errors=errors+1;
        @(negedge clk);wv=0;tick();if(ram_word1!=={64{8'h21}})$fatal(1,"Rejected padding reached RAM");
        begin_load();saved=ram_word0;word(0,0,1);if(!error||ec!=3||dut.write_pending)$fatal(1,"Bad LAST entered write stage");errors=errors+1;
        @(negedge clk);wv=0;tick();if(ram_word0!==saved)$fatal(1,"Rejected LAST changed RAM");
        if(accepts!=7||physical_writes!=6||commit_with_pending!=2||cancel_pending!=1||checks!=512||errors!=2)$fatal(1,"Incomplete writepipe boundary coverage");
        $display("FEATURE_WRITEPIPE_PASS accepted=%0d physical_writes=%0d commit_with_pending=%0d cancel_pending=%0d checked_bytes=%0d rejected_words=%0d",accepts,physical_writes,commit_with_pending,cancel_pending,checks,errors);
        $finish;
    end
    initial begin #1000000;$fatal(1,"Writepipe watchdog");end
endmodule
`default_nettype wire
