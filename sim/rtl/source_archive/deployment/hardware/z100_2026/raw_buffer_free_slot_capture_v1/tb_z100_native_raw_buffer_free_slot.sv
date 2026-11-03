`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_raw_buffer_free_slot;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0,cancel=0;
    reg in_valid=0,out_ready=0;
    reg [31:0] in_epoch=0,in_token=0;
    reg [4:0] in_site=0;
    reg in_last=0;
    reg [1023:0] in_data=0;
    wire in_ready,out_valid,out_last;
    wire [31:0] out_epoch,out_token;
    wire [4:0] out_site;
    wire [1023:0] out_data;
    wire [1093:0] out_payload={out_epoch,out_token,out_site,out_last,out_data};
    z100_native_raw_buffer dut(.*);

    reg [1093:0] expected[0:1];
    integer q_count=0,serial=0,cycles=0,pushes=0,pops=0;
    integer stall_holds=0,invalid_payload_changes=0;
    reg [1093:0] previous_invalid_payload;
    reg have_previous_invalid=0;

    task automatic cycle(input reg reset_active,input reg cancel_active,
                         input reg valid,input reg ready);
        reg was_valid,was_ready,do_push,do_pop,do_flush;
        reg [1093:0] before_payload,accepted_payload;
        begin
            @(negedge clk);
            rst_n=!reset_active; cancel=cancel_active;
            in_valid=valid; out_ready=ready;
            in_epoch=32'h51000000+serial;
            in_token=32'h27000000+(serial*17);
            in_site=serial%20; in_last=serial[0];
            in_data={32{serial[31:0] ^ 32'hA53C19E7}};
            serial=serial+1;
            #1;
            was_valid=out_valid; was_ready=out_ready;
            do_flush=reset_active||cancel_active;
            do_push=in_valid&&in_ready;
            do_pop=out_valid&&out_ready;
            before_payload=out_payload;
            accepted_payload={in_epoch,in_token,in_site,in_last,in_data};
            if(!do_flush) begin
                if(was_valid !== (q_count!=0)) $fatal(1,"pre-edge valid mismatch");
                if(q_count!=0 && out_payload!==expected[0])
                    $fatal(1,"pre-edge FIFO head mismatch cycle=%0d",cycles);
                if(in_ready !== (q_count<2)) $fatal(1,"ready/full-bubble mismatch");
                if(was_valid&&!was_ready) stall_holds=stall_holds+1;
            end
            @(posedge clk);
            if(do_flush) q_count=0;
            else begin
                if(do_pop) begin
                    pops=pops+1;
                    if(q_count==2) expected[0]=expected[1];
                    q_count=q_count-1;
                end
                if(do_push) begin
                    if(q_count>=2) $fatal(1,"scoreboard overflow");
                    expected[q_count]=accepted_payload;
                    q_count=q_count+1; pushes=pushes+1;
                end
            end
            #1;
            cycles=cycles+1;
            if(reset_active||cancel_active) begin
                if(out_valid!==1'b0||in_ready!==1'b0) $fatal(1,"reset/cancel not masking handshake");
            end else begin
                if(out_valid !== (q_count!=0)) $fatal(1,"post-edge valid mismatch");
                if(q_count!=0 && out_payload!==expected[0])
                    $fatal(1,"post-edge FIFO head mismatch cycle=%0d",cycles);
                if(was_valid&&!was_ready && out_payload!==before_payload)
                    $fatal(1,"payload changed during valid stall");
                if(was_valid&&!was_ready && !out_valid) $fatal(1,"valid dropped during stall");
                if(!out_valid) begin
                    if(have_previous_invalid && out_payload!==previous_invalid_payload)
                        invalid_payload_changes=invalid_payload_changes+1;
                    previous_invalid_payload=out_payload;
                    have_previous_invalid=1;
                end else have_previous_invalid=0;
            end
        end
    endtask

    integer i;
    initial begin
        cycle(1,0,0,0); cycle(0,0,0,0); cycle(0,0,0,0);
        // Invalid source payload may refresh only the free slot while empty.
        cycle(0,0,0,0); cycle(0,0,0,0); cycle(0,0,0,0);
        // Fill both entries; verify the original full->pop one-cycle bubble.
        cycle(0,0,1,0); cycle(0,0,1,0);
        cycle(0,0,1,1); // full: no push, pop only
        cycle(0,0,1,0); // bubble cycle starts with one entry; accepts push
        cycle(0,0,0,0); cycle(0,0,0,1);
        // Simultaneous push/pop at occupancy one, followed by a long stall.
        cycle(0,0,1,1);
        repeat(5) cycle(0,0,0,0);
        repeat(8) cycle(0,0,0,1);
        // Deterministic stress exercises varying valid/ready combinations.
        for(i=0;i<300;i=i+1)
            cycle(0,0,(i%5!=0),(i%7==0)||(i%7==1)||(i%7==4));
        cycle(0,0,0,0); cycle(0,0,0,1); cycle(0,0,0,1);
        // Fill, cancel with data pending, recover from empty.
        cycle(0,0,1,0); cycle(0,0,1,0); cycle(0,1,0,0);
        cycle(0,0,1,1); cycle(0,0,0,1);
        cycle(0,0,1,0); cycle(1,0,0,0); cycle(0,0,0,0);
        if(q_count!=0 || pushes<20 || pops<10 || stall_holds<5 || invalid_payload_changes<1)
            $fatal(1,"coverage incomplete q=%0d pushes=%0d pops=%0d stalls=%0d invalid_changes=%0d",
                   q_count,pushes,pops,stall_holds,invalid_payload_changes);
        $display("RAW_BUFFER_FREE_SLOT_PASS cycles=%0d pushes=%0d pops=%0d stall_holds=%0d invalid_payload_changes=%0d",
                 cycles,pushes,pops,stall_holds,invalid_payload_changes);
        $finish;
    end
endmodule
`default_nettype wire
