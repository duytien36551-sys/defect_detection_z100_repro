`timescale 1ns/1ps
module tb_z100_banks_writepipe_boundary;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cb=0,wv=0,cc=0,rv=0,ordy=1,canonical=0;
    reg [10:0] channels=32;reg [9:0] height=16,width=512;
    reg [12:0] wa=0;reg last=0;reg [511:0] wd=0;
    reg [3327:0] qa=0;reg [255:0] qm=0;
    wire cbr,wr,cr,rr,ov,sv,loading,error;wire [3:0] ec;wire [31:0] ep,oe;wire [2047:0] od;
    z100_feature_banks_4read_writepipe_4k_v5 dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),
        .cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(32'd200),.cfg_canonical_order(canonical),.cfg_channels(channels),.cfg_height(height),.cfg_width(width),
        .cfg_word_valid(wv),.cfg_word_ready(wr),.cfg_word_data(wd),.cfg_word_epoch(32'd200),.cfg_word_address(wa),.cfg_word_last(last),
        .cfg_commit(cc),.cfg_commit_ready(cr),.error_valid(error),.error_code(ec),.store_valid(sv),.active_epoch(ep),.loading(loading),
        .req_valid(rv),.req_ready(rr),.req_epoch(32'd200),.req_addresses(qa),.req_mask(qm),.out_valid(ov),.out_ready(ordy),.out_epoch(oe),.out_data(od));
    function automatic [7:0] pattern(input integer address,input integer bank);
        pattern=(address*37+bank*13+(address>>8)*7)^8'hb3;
    endfunction
    task tick;begin @(posedge clk);#1;end endtask
    task begin_load(input integer mode);begin
        while(!cbr)tick();@(negedge clk);cb=1;canonical=mode;tick();@(negedge clk);cb=0;canonical=!mode;
    end endtask
    task clear_pulse;begin @(negedge clk);cancel=1;tick();@(negedge clk);cancel=0;tick();end endtask
    integer mode,i,b,p,address,expected_address,loaded=0,checked=0,guards=0,holds=0;
    reg [2047:0] held;
    initial begin
        repeat(5)tick();@(negedge clk);rst_n=1;
        for(mode=0;mode<2;mode=mode+1)begin
            // Reject a valid13-bit address-space geometry beyond physical4K.
            channels=33;begin_load(mode);
            if(!error||ec!=1||sv||loading)$fatal(1,"4K oversized geometry was admitted");guards=guards+1;clear_pulse();
            channels=32;begin_load(mode);@(negedge clk);wv=1;wa=4096;last=0;wd=0;
            #1;if(!wr)$fatal(1,"4K high write probe not accepted for checking");tick();
            if(!error||ec!=2||sv||loading)$fatal(1,"4K bit12 write silently aliased");guards=guards+1;
            @(negedge clk);wv=0;clear_pulse();begin_load(mode);
            for(i=0;i<4096;i=i+1)begin
                // Native order interleaves8 channel4 subgroups per row/xword;
                // canonical order enumerates all rows of one subgroup first.
                address=mode ? i : ((i%8)*16+(i/8)/32)*32+(i/8)%32;
                @(negedge clk);wv=1;wa=address;last=i==4095;
                for(b=0;b<64;b=b+1)wd[b*8+:8]=pattern(address,b);
                #1;if(!wr)$fatal(1,"4K full-capacity write not ready");tick();
                if(error||sv)$fatal(1,"4K full-capacity word rejected/published early mode=%0d index=%0d error=%0d",mode,i,ec);loaded=loaded+1;
            end
            @(negedge clk);wv=0;cc=1;#1;if(!cr)$fatal(1,"4K commit readiness");tick();@(negedge clk);cc=0;
            if(!sv||loading||error||ep!=200)$fatal(1,"4K full-capacity commit");
            for(i=0;i<4096;i=i+1)begin
                @(negedge clk);rv=1;ordy=!(i%53==0);qm={256{1'b1}};
                for(b=0;b<64;b=b+1)for(p=0;p<4;p=p+1)begin
                    expected_address=(i*(p*2+1)+p*7)%4096;qa[(b*4+p)*13+:13]=expected_address;
                    if(p==2&&i%17==0)qm[b*4+p]=0;
                end
                #1;if(!rr)$fatal(1,"4K read admission");tick();
                if(!ov||oe!=200||error)$fatal(1,"4K full read response");
                for(b=0;b<64;b=b+1)for(p=0;p<4;p=p+1)begin
                    expected_address=(i*(p*2+1)+p*7)%4096;
                    if(od[(b*4+p)*8+:8] !== (qm[b*4+p]?pattern(expected_address,b):8'd0))$fatal(1,"4K four-read data mismatch mode=%0d address=%0d bank=%0d port=%0d",mode,i,b,p);
                    checked=checked+1;
                end
                held=od;@(negedge clk);rv=0;
                if(!ordy)begin
                    repeat(3)begin tick();if(!ov||od!==held||rr)$fatal(1,"4K held response changed");holds=holds+1;end
                    @(negedge clk);ordy=1;
                end
                tick();
            end
            @(negedge clk);rv=1;qm=1;qa=0;qa[12:0]=4096;
            #1;if(!rr)$fatal(1,"4K high read probe not admitted for checking");tick();
            if(!error||ec!=7||sv||ov)$fatal(1,"4K bit12 read silently aliased");guards=guards+1;
            @(negedge clk);rv=0;tick();
            if(dut.store_valid_a||dut.store_valid_b||dut.active_epoch_a||dut.active_epoch_b)$fatal(1,"4K bad-read atomic mirror flush");clear_pulse();
        end
        if(loaded!=8192||checked!=2097152||guards!=6||holds==0)$fatal(1,"4K boundary coverage");
        $display("BANKS4K_BOUNDARY_PASS modes=2 words=%0d read_bytes=%0d guards=%0d held_cycles=%0d address_bits=13 physical_depth=4096",loaded,checked,guards,holds);
        $finish;
    end
    initial begin #2000000;$fatal(1,"4K boundary watchdog");end
endmodule
