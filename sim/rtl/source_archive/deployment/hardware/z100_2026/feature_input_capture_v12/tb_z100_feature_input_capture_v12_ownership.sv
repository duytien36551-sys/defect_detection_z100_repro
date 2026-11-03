`timescale 1ns/1ps
module tb_z100_feature_input_capture_v12_ownership;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cfg_bank=0,read_bank=0,cb=0,wv=0,cc=0,window_valid=0,out_ready=0;
    reg [12:0] wa=0;reg wl=0;reg [511:0] data=0;
    reg [31:0] tag=1;reg signed [11:0] x=1;reg [3:0] channel_mask=15;reg stride2=0;
    reg [4:0] sites=20;reg [10:0] remaining=20,input_width=64;
    wire read_idle,lov,lob,lsv,ll,cbr,wr,cr,sv,loading,error,ready,ov;
    wire [31:0] lae,ae,ot;wire [3:0] ec;wire [79:0] mask;wire [639:0] od;

    z100_feature_window20_address_shared_v12 dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_bank(cfg_bank),.read_bank(read_bank),.read_idle(read_idle),
        .load_owner_valid(lov),.load_owner_bank(lob),.load_store_valid(lsv),.load_loading(ll),.load_active_epoch(lae),
        .cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(32'd200),.cfg_canonical_order(1'b1),.cfg_channels(11'd4),.cfg_height(10'd1),.cfg_width(10'd64),
        .cfg_word_epoch(32'd200),.cfg_word_address(wa),.cfg_word_last(wl),.cfg_word_valid(wv),.cfg_word_ready(wr),.cfg_data(data),.cfg_commit(cc),.cfg_commit_ready(cr),
        .store_valid(sv),.loading(loading),.active_epoch(ae),.error_valid(error),.error_code(ec),
        .window_valid(window_valid),.window_ready(ready),.window_epoch(32'd200),.window_tag(tag),.window_row_address(14'd0),.window_first_x(x),
        .window_input_width(input_width),.window_output_remaining(remaining),.window_sites(sites),.window_channel_mask(channel_mask),.window_stride_two(stride2),.window_y_valid(1'b1),
        .out_valid(ov),.out_ready(out_ready),.out_tag(ot),.out_mask(mask),.out_data(od));

    function automatic [7:0] value(input integer bank,input integer channel,input integer xpos);
        value=(bank*97+channel*43+xpos*7)^8'ha5;
    endfunction
    task tick;begin @(posedge clk);#1;end endtask
    task begin_bank(input integer bank);begin
        @(negedge clk);cfg_bank=bank;cb=1;#1;while(!cbr)begin tick();@(negedge clk);#1;end
        tick();@(negedge clk);cb=0;cfg_bank=!bank;
        if(!lov||lob!=bank)$fatal(1,"V12 bank load owner not latched");
    end endtask
    integer writes=0,checks=0,held=0,bank_exclusion_hold_cycles=0,verified_windows=0,bank1_verified_windows=0;
    integer full_blocks=0,bubble_checks=0,simultaneous=0;
    integer invalid_descriptors=0,cancel_empty=0,cancel_one=0,cancel_two=0;
    integer both_bank_pending=0,overwrite_blocks=0,reuse_after_cancel=0,cancel_attempted_pop=0;
    integer accepted_cfg_words=0,accepted_window_handshakes=0,accepted_descriptors=0;
    integer invalid_handshakes=0,enqueued_descriptors=0,popped_descriptors=0;
    integer cancel_cycles=0,cancelled_descriptors=0,simultaneous_handshakes=0,max_fifo_occupancy=0;
    always @(posedge clk) begin
        if (rst_n) begin
            if (wv && wr) accepted_cfg_words <= accepted_cfg_words+1;
            if (window_valid && ready) begin
                accepted_window_handshakes <= accepted_window_handshakes+1;
                if (dut.descriptor_ok) accepted_descriptors <= accepted_descriptors+1;
                else invalid_handshakes <= invalid_handshakes+1;
            end
            if (dut.fifo_enqueue) enqueued_descriptors <= enqueued_descriptors+1;
            if (dut.fifo_pop) popped_descriptors <= popped_descriptors+1;
            if (dut.fifo_enqueue && dut.fifo_pop) simultaneous_handshakes <= simultaneous_handshakes+1;
            if (dut.fifo_count > max_fifo_occupancy) max_fifo_occupancy <= dut.fifo_count;
            if (cancel) begin
                cancel_cycles <= cancel_cycles+1;
                cancelled_descriptors <= cancelled_descriptors+dut.fifo_count;
                if (dut.fifo_enqueue || dut.fifo_pop) $fatal(1,"V12 cancel allowed a queue transfer");
            end
        end
    end
    task fill_bank(input integer bank);integer word_i,c,p;begin
        for(word_i=0;word_i<4;word_i=word_i+1)begin
            @(negedge clk);wv=1;wa=word_i;wl=word_i==3;
            for(c=0;c<4;c=c+1)for(p=0;p<16;p=p+1)data[(c*16+p)*8+:8]=value(bank,c,word_i*16+p);
            #1;if(!wr||lob!=bank)$fatal(1,"V12 mirrored write ownership");tick();writes=writes+1;
        end
        @(negedge clk);wv=0;cc=1;#1;if(!cr)$fatal(1,"V12 bank commit");tick();@(negedge clk);cc=0;
        if(lov||!lsv||lae!=200||error)$fatal(1,"V12 published bank invalid");
    end endtask
    task verify_window(input integer bank,input integer first_x,input integer step_x,input integer channels,input [31:0] token);integer c,p,ix;reg valid_pixel;begin
        if(!ov||ot!=token||error)$fatal(1,"V12 response/token ownership tag=%h expected=%h",ot,token);
        for(c=0;c<4;c=c+1)for(p=0;p<20;p=p+1)begin
            ix=first_x+p*step_x;valid_pixel=c<channels&&ix>=0&&ix<64;
            if(mask[c*20+p]!==valid_pixel||od[(c*20+p)*8+:8] !== (valid_pixel?value(bank,c,ix):8'd0))
                $fatal(1,"V12 wrong bank/value bank=%0d channel=%0d site=%0d",bank,c,p);
            checks=checks+1;
        end
        verified_windows=verified_windows+1;
        if(bank==1)bank1_verified_windows=bank1_verified_windows+1;
    end endtask
    reg [639:0] held_data;reg [79:0] held_mask;reg [31:0] held_tag;
    task hold_check(input integer bank_exclusion);begin
        if(!ov||od!==held_data||mask!==held_mask||ot!==held_tag||read_idle||error)$fatal(1,"V12 held response changed");
        if(bank_exclusion)bank_exclusion_hold_cycles=bank_exclusion_hold_cycles+1;else held=held+1;
    end endtask
    task wait_response;integer n;begin n=0;while(!ov)begin tick();n=n+1;if(n>20)$fatal(1,"V12 response timeout");end end endtask
    task send_window(input integer bank,input [31:0] token,input integer first,input integer two,input integer channels);begin
        @(negedge clk);read_bank=bank;tag=token;x=first;stride2=two;channel_mask=channels==4?15:7;sites=20;remaining=20;window_valid=1;
        #1;while(!ready)begin tick();@(negedge clk);#1;end tick();@(negedge clk);window_valid=0;read_bank=!bank;
    end endtask
    task check_quiet;integer n;begin
        for(n=0;n<3;n=n+1)begin tick();if(ov||dut.fifo_count!=0||dut.q0_valid||dut.q1_valid)$fatal(1,"V12 canceled descriptor reappeared");end
    end endtask

    initial begin
        repeat(5)tick();@(negedge clk);rst_n=1;begin_bank(0);fill_bank(0);

        // Empty cancel blocks the new VALID handshake and leaves no request.
        @(negedge clk);read_bank=0;tag=32'he001;window_valid=1;#1;
        if(!ready||dut.fifo_count!=0)$fatal(1,"V12 empty cancel precondition");
        cancel=1;#1;if(ready)$fatal(1,"V12 accepted input during empty cancel");tick();
        if(dut.fifo_count!=0||dut.q0_valid||dut.q1_valid||ov||dut.sv!=0)$fatal(1,"V12 empty cancel failed");cancel_empty=cancel_empty+1;
        @(negedge clk);window_valid=0;cancel=0;tick();begin_bank(0);fill_bank(0);

        // Occupancy one: one request leaves while the next enters each cycle.
        send_window(0,32'h5101,0,0,4);
        if(dut.fifo_count!=1||read_idle)$fatal(1,"V12 queued request missing from read_idle");
        tag=32'h5102;x=1;read_bank=0;window_valid=1;#1;
        if(!ready||!dut.fifo_pop||!dut.fifo_enqueue)$fatal(1,"V12 occupancy-one overlap precondition");
        tick();
        if(dut.fifo_count!=1||!dut.fifo_head_valid||dut.fifo_head_tag!=32'h5102||dut.fifo_head_bank!=0)
            $fatal(1,"V12 occupancy-one simultaneous enqueue/dequeue");
        simultaneous=simultaneous+1;
        // Cancel wins over the next attempted input; the compact FIFO and store flush together.
        tag=32'h51ff;window_valid=1;#1;if(!ready)$fatal(1,"V12 occupancy-one cancel precondition");
        cancel=1;#1;if(ready||dut.ram_req_ready||ov)$fatal(1,"V12 cancel did not suppress push/pop/publication");tick();
        if(dut.fifo_count!=0||dut.q0_valid||dut.q1_valid||ov||dut.sv!=0)$fatal(1,"V12 occupancy-one cancel failed");cancel_one=cancel_one+1;
        @(negedge clk);window_valid=0;cancel=0;tick();begin_bank(0);fill_bank(0);begin_bank(1);fill_bank(1);

        // Malformed descriptors handshake once, pulse the legacy error, and never enter the queue.
        @(negedge clk);read_bank=0;sites=0;tag=32'hbad0;window_valid=1;#1;
        if(!ready)$fatal(1,"V12 malformed descriptor admission precondition");tick();
        if(!error||ec!=1||dut.fifo_count!=0||dut.q0_valid||dut.q1_valid||ov)$fatal(1,"V12 malformed descriptor escaped");
        invalid_descriptors=invalid_descriptors+1;
        @(negedge clk);window_valid=0;sites=20;tick();if(error)$fatal(1,"V12 malformed descriptor error did not clear");

        // Hold response A, then queue B and C from both banks behind it.
        send_window(0,32'ha001,1,0,4);wait_response();verify_window(0,1,1,4,32'ha001);
        held_data=od;held_mask=mask;held_tag=ot;
        repeat(3)begin tick();hold_check(0);end
        send_window(0,32'hb002,-2,1,3);
        if(dut.fifo_count!=1||dut.fifo_head_bank!=0||dut.fifo_pop)$fatal(1,"V12 first queued descriptor ownership");
        send_window(1,32'hc003,3,0,4);
        if(dut.fifo_count!=2||!dut.q0_valid||!dut.q1_valid||dut.q0_bank==dut.q1_bank||read_idle)
            $fatal(1,"V12 two-bank pending queue/read_idle proof");
        both_bank_pending=both_bank_pending+1;
        // Bank 1 is not writable while its read descriptor is still queued.
        @(negedge clk);cfg_bank=1;cb=1;#1;
        if(cbr||lov||ready)$fatal(1,"V12 queued bank overwrite exclusion");overwrite_blocks=overwrite_blocks+1;
        repeat(2)begin tick();hold_check(1);@(negedge clk);#1;if(cbr||lov)$fatal(1,"V12 queued bank overwrite accepted");end
        cb=0;

        // A full FIFO rejects a same-cycle replacement even as B leaves: one recovery bubble.
        window_valid=1;read_bank=0;tag=32'hd004;x=4;out_ready=1;#1;
        if(ready||!dut.fifo_pop||dut.fifo_count!=2)$fatal(1,"V12 full recovery bubble precondition");
        full_blocks=full_blocks+1;
        tick();out_ready=0;
        if(dut.fifo_count!=1||!ready)$fatal(1,"V12 full recovery bubble missing");bubble_checks=bubble_checks+1;
        tick();
        if(dut.fifo_count!=2||!dut.q0_valid||!dut.q1_valid)$fatal(1,"V12 held replacement was not accepted after bubble");
        @(negedge clk);window_valid=0;
        wait_response();verify_window(0,-2,2,3,32'hb002);

        // Cancel at occupancy two discards the accepted response and both queued banks.
        @(negedge clk);window_valid=1;tag=32'he005;out_ready=1;#1;
        if(dut.fifo_count!=2||ready||!ov)$fatal(1,"V12 two-entry cancel precondition");
        cancel=1;#1;if(ready||ov||dut.ram_req_ready)$fatal(1,"V12 two-entry cancel did not suppress transfer/publication");tick();
        if(dut.fifo_count!=0||dut.q0_valid||dut.q1_valid||ov||dut.sv!=0)$fatal(1,"V12 two-entry cancel failed");cancel_two=cancel_two+1;
        @(negedge clk);window_valid=0;out_ready=0;cancel=0;tick();check_quiet();

        // Reuse after cancel, then prove cancel blocks a simultaneous pop/push attempt at full occupancy.
        begin_bank(0);fill_bank(0);
        send_window(0,32'hf006,2,0,4);wait_response();verify_window(0,2,1,4,32'hf006);
        send_window(0,32'hf007,4,0,4);
        send_window(0,32'hf008,6,0,4);
        if(dut.fifo_count!=2||!dut.q0_valid||!dut.q1_valid)$fatal(1,"V12 same-bank cancel queue precondition");
        @(negedge clk);window_valid=1;tag=32'hf009;read_bank=0;out_ready=1;#1;
        if(ready||!dut.fifo_pop||!ov)$fatal(1,"V12 cancel attempted pop precondition");
        full_blocks=full_blocks+1;
        cancel=1;#1;if(ready||dut.ram_req_ready||ov)$fatal(1,"V12 cancel failed to suppress attempted pop");tick();
        if(dut.fifo_count!=0||dut.q0_valid||dut.q1_valid||ov||dut.sv!=0)$fatal(1,"V12 cancel/pop did not flush");
        cancel_two=cancel_two+1;cancel_attempted_pop=cancel_attempted_pop+1;
        @(negedge clk);window_valid=0;out_ready=0;cancel=0;tick();check_quiet();

        begin_bank(0);fill_bank(0);send_window(0,32'hfa10,0,0,4);wait_response();verify_window(0,0,1,4,32'hfa10);
        @(negedge clk);out_ready=1;read_bank=0;tick();@(negedge clk);out_ready=0;
        begin_bank(1);fill_bank(1);send_window(1,32'hfb11,0,0,4);wait_response();verify_window(1,0,1,4,32'hfb11);
        @(negedge clk);out_ready=1;tick();@(negedge clk);out_ready=0;
        if(ov||dut.fifo_count!=0||dut.q0_valid||dut.q1_valid)$fatal(1,"V12 final bank1 response did not drain");
        reuse_after_cancel=1;
        $display("FEATURE_INPUT_CAPTURE_V12_OWNERSHIP_COUNTS writes=%0d value_mask_checks=%0d verified_windows=%0d bank1_verified_windows=%0d held_cycles=%0d bank_exclusion_hold_cycles=%0d full_blocks=%0d bubbles=%0d simultaneous=%0d invalid=%0d cancel_empty=%0d cancel_one=%0d cancel_two=%0d both_bank_pending=%0d overwrite_blocks=%0d reuse_after_cancel=%0d cancel_attempted_pop=%0d accepted_cfg_words=%0d accepted_window_handshakes=%0d accepted_descriptors=%0d invalid_handshakes=%0d enqueued_descriptors=%0d popped_descriptors=%0d cancel_cycles=%0d cancelled_descriptors=%0d simultaneous_handshakes=%0d max_fifo_occupancy=%0d",
            writes,checks,verified_windows,bank1_verified_windows,held,bank_exclusion_hold_cycles,full_blocks,bubble_checks,simultaneous,
            invalid_descriptors,cancel_empty,cancel_one,cancel_two,both_bank_pending,overwrite_blocks,reuse_after_cancel,
            cancel_attempted_pop,accepted_cfg_words,accepted_window_handshakes,accepted_descriptors,invalid_handshakes,
            enqueued_descriptors,popped_descriptors,cancel_cycles,cancelled_descriptors,simultaneous_handshakes,max_fifo_occupancy);
        if(writes!=28||accepted_cfg_words!=28||checks!=400||verified_windows!=5||bank1_verified_windows!=1||
           held!=3||bank_exclusion_hold_cycles!=2||full_blocks!=2||bubble_checks!=1||simultaneous!=1||
           invalid_descriptors!=1||cancel_empty!=1||cancel_one!=1||cancel_two!=2||both_bank_pending!=1||
           overwrite_blocks!=1||reuse_after_cancel!=1||cancel_attempted_pop!=1||
           accepted_window_handshakes!=12||accepted_descriptors!=11||invalid_handshakes!=1||
           enqueued_descriptors!=11||popped_descriptors!=6||cancel_cycles!=4||cancelled_descriptors!=5||
           simultaneous_handshakes!=1||max_fifo_occupancy!=2)
            $fatal(1,"V12 ownership coverage incomplete");
        $display("FEATURE_INPUT_CAPTURE_V12_OWNERSHIP_PASS writes=%0d value_mask_checks=%0d verified_windows=%0d bank1_verified_windows=%0d held_cycles=%0d bank_exclusion_hold_cycles=%0d full_blocks=%0d bubbles=%0d simultaneous=%0d invalid=%0d cancel_empty=%0d cancel_one=%0d cancel_two=%0d both_bank_pending=%0d overwrite_blocks=%0d reuse_after_cancel=%0d cancel_attempted_pop=%0d accepted_cfg_words=%0d accepted_window_handshakes=%0d accepted_descriptors=%0d invalid_handshakes=%0d enqueued_descriptors=%0d popped_descriptors=%0d cancel_cycles=%0d cancelled_descriptors=%0d simultaneous_handshakes=%0d max_fifo_occupancy=%0d",
            writes,checks,verified_windows,bank1_verified_windows,held,bank_exclusion_hold_cycles,full_blocks,bubble_checks,simultaneous,
            invalid_descriptors,cancel_empty,cancel_one,cancel_two,both_bank_pending,overwrite_blocks,reuse_after_cancel,
            cancel_attempted_pop,accepted_cfg_words,accepted_window_handshakes,accepted_descriptors,invalid_handshakes,
            enqueued_descriptors,popped_descriptors,cancel_cycles,cancelled_descriptors,simultaneous_handshakes,max_fifo_occupancy);
        $finish;
    end
    initial begin #1000000;$fatal(1,"V12 ownership watchdog");end
endmodule
