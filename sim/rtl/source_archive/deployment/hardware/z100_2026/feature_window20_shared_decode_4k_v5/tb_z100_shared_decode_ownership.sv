`timescale 1ns/1ps
module tb_z100_shared_decode_ownership;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cfg_bank=0,read_bank=0,cb=0,wv=0,cc=0,window_valid=0,out_ready=0;
    reg [12:0] wa=0;reg wl=0;reg [511:0] data=0;
    reg [31:0] tag=1;reg signed [11:0] x=1;reg [3:0] channel_mask=15;reg stride2=0;
    wire read_idle,lov,lob,lsv,ll,cbr,wr,cr,sv,loading,error,ready,ov;wire [31:0] lae,ae,ot;wire [3:0] ec;wire [79:0] mask;wire [639:0] od;
    z100_feature_window20_shared_decode_4k_v5 dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_bank(cfg_bank),.read_bank(read_bank),.read_idle(read_idle),
        .load_owner_valid(lov),.load_owner_bank(lob),.load_store_valid(lsv),.load_loading(ll),.load_active_epoch(lae),
        .cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(32'd200),.cfg_canonical_order(1'b1),.cfg_channels(11'd4),.cfg_height(10'd1),.cfg_width(10'd64),
        .cfg_word_epoch(32'd200),.cfg_word_address(wa),.cfg_word_last(wl),.cfg_word_valid(wv),.cfg_word_ready(wr),.cfg_data(data),.cfg_commit(cc),.cfg_commit_ready(cr),
        .store_valid(sv),.loading(loading),.active_epoch(ae),.error_valid(error),.error_code(ec),
        .window_valid(window_valid),.window_ready(ready),.window_epoch(32'd200),.window_tag(tag),.window_row_address(14'd0),.window_first_x(x),
        .window_input_width(11'd64),.window_output_remaining(11'd20),.window_sites(5'd20),.window_channel_mask(channel_mask),.window_stride_two(stride2),.window_y_valid(1'b1),
        .out_valid(ov),.out_ready(out_ready),.out_tag(ot),.out_mask(mask),.out_data(od));
    function automatic [7:0] value(input integer bank,input integer channel,input integer xpos);
        value=(bank*97+channel*43+xpos*7)^8'ha5;
    endfunction
    task tick;begin @(posedge clk);#1;end endtask
    task begin_bank(input integer bank);begin
        @(negedge clk);cfg_bank=bank;cb=1;#1;while(!cbr)begin tick();@(negedge clk);#1;end
        tick();@(negedge clk);cb=0;cfg_bank=!bank;
        if(!lov||lob!=bank)$fatal(1,"shared decode load bank not latched");
    end endtask
    integer writes=0,checks=0,held=0,blocked=0,concurrent=0,flushes=0;
    task fill_bank(input integer bank);integer word_i,c,p;begin
        for(word_i=0;word_i<4;word_i=word_i+1)begin
            @(negedge clk);wv=1;wa=word_i;wl=word_i==3;
            for(c=0;c<4;c=c+1)for(p=0;p<16;p=p+1)data[(c*16+p)*8+:8]=value(bank,c,word_i*16+p);
            #1;if(!wr||lob!=bank)$fatal(1,"shared decode mirrored write ownership");tick();writes=writes+1;
        end
        @(negedge clk);wv=0;cc=1;#1;if(!cr)$fatal(1,"shared decode bank commit");tick();@(negedge clk);cc=0;
        if(lov||!lsv||lae!=200||error)$fatal(1,"shared decode published bank invalid");
    end endtask
    task verify_window(input integer bank,input integer first_x,input integer step_x,input integer channels,input [31:0] token);integer c,p,ix;reg valid_pixel;begin
        if(!ov||ot!=token||error)$fatal(1,"shared decoder response/token ownership");
        for(c=0;c<4;c=c+1)for(p=0;p<20;p=p+1)begin
            ix=first_x+p*step_x;valid_pixel=c<channels&&ix>=0&&ix<64;
            if(mask[c*20+p]!==valid_pixel||od[(c*20+p)*8+:8] !== (valid_pixel?value(bank,c,ix):8'd0))$fatal(1,"shared decoder returned wrong bank/value bank=%0d channel=%0d site=%0d",bank,c,p);
            checks=checks+1;
        end
    end endtask
    reg [639:0] held_data;reg [79:0] held_mask;reg [31:0] held_tag;
    task hold_check;begin
        if(!ov||od!==held_data||mask!==held_mask||ot!==held_tag||read_idle||error)$fatal(1,"shared decoder held response changed with bank pins/config");held=held+1;
    end endtask
    task wait_response;integer n;begin n=0;while(!ov)begin tick();n=n+1;if(n>20)$fatal(1,"shared decoder response timeout");end end endtask
    task send_window(input integer bank,input [31:0] token,input integer first,input integer two,input integer channels);begin
        @(negedge clk);read_bank=bank;tag=token;x=first;stride2=two;channel_mask=channels==4?15:7;window_valid=1;
        #1;while(!ready)begin tick();@(negedge clk);#1;end tick();@(negedge clk);window_valid=0;read_bank=!bank;
    end endtask
    initial begin
        repeat(5)tick();@(negedge clk);rst_n=1;begin_bank(0);fill_bank(0);
        // One descriptor decode accepts A while B begins loading on the same edge.
        @(negedge clk);cfg_bank=1;cb=1;read_bank=0;window_valid=1;tag=32'ha1;x=1;stride2=0;channel_mask=15;
        #1;if(!cbr||!ready)$fatal(1,"shared decoder prevented other-bank begin/read overlap");concurrent=concurrent+1;
        tick();@(negedge clk);cb=0;window_valid=0;cfg_bank=0;read_bank=1;
        if(!lov||!lob)$fatal(1,"shared decoder begin/read load owner");
        fill_bank(1);wait_response();verify_window(0,1,1,4,32'ha1);
        held_data=od;held_mask=mask;held_tag=ot;
        repeat(3)begin tick();hold_check();end
        // Queue B in S0 while A is held; changing the pin back to A must not
        // change the queued bank or overwrite A's S1 map/tag.
        send_window(1,32'hb2,-2,1,3);if(!dut.s0_valid||!dut.s0_bank)$fatal(1,"shared S0 bank not latched");
        repeat(3)begin tick();hold_check();end
        @(negedge clk);cfg_bank=0;cb=1;
        repeat(4)begin #1;if(cbr||ready||lov)$fatal(1,"held A/queued B accepted overwrite");blocked=blocked+1;tick();hold_check();@(negedge clk);end
        cb=0;out_ready=1;tick();@(negedge clk);out_ready=0;wait_response();verify_window(1,-2,2,3,32'hb2);
        held_data=od;held_mask=mask;held_tag=ot;cfg_bank=1;cb=1;
        repeat(4)begin #1;if(cbr||lov)$fatal(1,"pending B accepted overwrite");blocked=blocked+1;tick();hold_check();@(negedge clk);end
        cb=0;out_ready=1;tick();@(negedge clk);out_ready=0;tick();
        if(!read_idle||dut.sv!==2'b11)$fatal(1,"shared decoder banks did not survive switching");
        // Cancel after an accepted descriptor, then load/reuse without any RAM
        // payload reset; both S0 and response metadata must be invalidated.
        send_window(0,32'hc3,0,0,4);@(negedge clk);cancel=1;tick();
        if(ov||lov||dut.s0_valid||dut.sv!=0)$fatal(1,"shared decoder in-flight cancel leaked response/bank");flushes=flushes+1;
        @(negedge clk);cancel=0;tick();begin_bank(0);fill_bank(0);send_window(0,32'hd4,0,0,4);wait_response();verify_window(0,0,1,4,32'hd4);
        @(negedge clk);cancel=1;tick();if(ov||lov||dut.sv!=0)$fatal(1,"shared decoder held-response cancel");flushes=flushes+1;
        if(writes!=12||checks!=240||held!=14||blocked!=8||concurrent!=1||flushes!=2)$fatal(1,"shared decoder ownership coverage");
        $display("SHARED_DECODE_OWNERSHIP_PASS writes=%0d value_mask_checks=%0d held_cycles=%0d overwrite_blocks=%0d simultaneous_begin_window=%0d cancel_flushes=%0d",writes,checks,held,blocked,concurrent,flushes);
        $finish;
    end
    initial begin #1000000;$fatal(1,"shared decoder ownership watchdog");end
endmodule
