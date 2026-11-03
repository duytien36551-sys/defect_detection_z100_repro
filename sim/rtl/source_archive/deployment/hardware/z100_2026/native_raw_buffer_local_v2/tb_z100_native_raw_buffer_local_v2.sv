`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_raw_buffer_local_v2;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,cancel=0,in_valid=0,out_ready=0;
    reg [31:0] in_epoch=0,in_token=0; reg [4:0] in_site=0;
    reg in_last=0; reg [1023:0] in_data=0;
    wire ref_in_ready,ref_out_valid; wire [31:0] ref_epoch,ref_token;
    wire [4:0] ref_site; wire ref_last; wire [1023:0] ref_data;
    wire cand_in_ready,cand_out_valid; wire [31:0] cand_epoch,cand_token;
    wire [4:0] cand_site; wire cand_last; wire [1023:0] cand_data;

    z100_native_raw_buffer reference_buffer(
        .clk(clk),.rst_n(rst_n),.cancel(cancel),.in_valid(in_valid),.in_ready(ref_in_ready),
        .in_epoch(in_epoch),.in_token(in_token),.in_site(in_site),.in_last(in_last),.in_data(in_data),
        .out_valid(ref_out_valid),.out_ready(out_ready),.out_epoch(ref_epoch),.out_token(ref_token),
        .out_site(ref_site),.out_last(ref_last),.out_data(ref_data));
    z100_native_raw_buffer_local_v2 candidate_buffer(
        .clk(clk),.rst_n(rst_n),.cancel(cancel),.in_valid(in_valid),.in_ready(cand_in_ready),
        .in_epoch(in_epoch),.in_token(in_token),.in_site(in_site),.in_last(in_last),.in_data(in_data),
        .out_valid(cand_out_valid),.out_ready(out_ready),.out_epoch(cand_epoch),.out_token(cand_token),
        .out_site(cand_site),.out_last(cand_last),.out_data(cand_data));

    wire [1093:0] ref_payload={ref_epoch,ref_token,ref_site,ref_last,ref_data};
    wire [1093:0] cand_payload={cand_epoch,cand_token,cand_site,cand_last,cand_data};
    reg [1093:0] expected_q0=0,expected_q1=0,expected_input=0;
    integer qcount=0,cycles=0,pushes=0,pops=0,simultaneous=0;
    integer full_stalls=0,output_stalls=0,bubbles=0,resets=0,cancels=0;
    integer pointer_checks=0,head_checks=0,seq=0; reg [31:0] lfsr=32'hf00d71a5;
    reg push_fire,pop_fire; reg [1:0] pre_count;

    task automatic make_item(input integer serial);
        integer b;
        begin
            in_epoch=32'h41000000+serial; in_token=32'h52000000+serial;
            in_site=serial[4:0]; in_last=serial[0];
            for(b=0;b<128;b=b+1) in_data[b*8+:8]=(serial*37+b*19) & 255;
            expected_input={in_epoch,in_token,in_site,in_last,in_data};
        end
    endtask

    task automatic check_current;
        reg [1093:0] expected_head;
        begin
            #1;
            if(ref_in_ready!==cand_in_ready || ref_out_valid!==cand_out_valid || ref_payload!==cand_payload)
                $fatal(1,"public-cycle mismatch cycle=%0d",cycles);
            if(ref_in_ready!== (rst_n&&!cancel&&reference_buffer.count<2) ||
               ref_out_valid!== (rst_n&&!cancel&&reference_buffer.count!=0))
                $fatal(1,"ready/valid contract mismatch cycle=%0d",cycles);
            if(qcount!=reference_buffer.count)
                $fatal(1,"independent occupancy mismatch cycle=%0d model=%0d rtl=%0d",cycles,qcount,reference_buffer.count);
            if(qcount>0 && rst_n && !cancel) begin
                expected_head=expected_q0;
                if(ref_payload!==expected_head)
                    $fatal(1,"independent FIFO head mismatch cycle=%0d",cycles);
                head_checks=head_checks+1;
            end
        end
    endtask

    genvar monitor_group;
    generate for(monitor_group=0;monitor_group<35;monitor_group=monitor_group+1) begin : gen_pointer_monitor
        always @(negedge clk) begin
            #1;
            if(candidate_buffer.gen_local_read_pointer[monitor_group].local_read_pointer!==reference_buffer.read_pointer)
                $fatal(1,"local read-pointer replica mismatch group=%0d cycle=%0d",monitor_group,cycles);
            pointer_checks=pointer_checks+1;
        end
    end endgenerate

    task automatic step(input bit drive_valid,input bit drive_ready,input bit do_cancel,input bit do_reset);
        begin
            @(negedge clk);
            rst_n=!do_reset; cancel=do_cancel; out_ready=drive_ready; in_valid=drive_valid;
            if(drive_valid) begin seq=seq+1;make_item(seq);end
            else begin in_epoch=0;in_token=0;in_site=0;in_last=0;in_data=0;expected_input=0;end
            #1;
            check_current();
            pre_count=reference_buffer.count;
            push_fire=in_valid&&ref_in_ready; pop_fire=ref_out_valid&&out_ready;
            if(ref_out_valid&&!out_ready) output_stalls=output_stalls+1;
            if(pre_count==2 && in_valid && !ref_in_ready && pop_fire) full_stalls=full_stalls+1;
            if(!in_valid && !ref_out_valid) bubbles=bubbles+1;
            if(push_fire) begin
                if(qcount>=2) $fatal(1,"independent model overflow");
                pushes=pushes+1;
            end
            if(pop_fire) begin
                if(qcount==0) $fatal(1,"independent model underflow");
                pops=pops+1;
            end
            if(push_fire&&pop_fire) simultaneous=simultaneous+1;
            if(do_reset) resets=resets+1;
            if(do_cancel) cancels=cancels+1;
            @(posedge clk); #1;
            cycles=cycles+1;
            if(do_reset||do_cancel) begin qcount=0;expected_q0=0;expected_q1=0;end
            else if(push_fire&&pop_fire) begin
                if(qcount==1) begin expected_q0=expected_input;expected_q1=0;end
                else begin expected_q0=expected_q1;expected_q1=expected_input;end
            end else if(pop_fire) begin
                if(qcount==2) begin expected_q0=expected_q1;expected_q1=0;end
                else begin expected_q0=0;expected_q1=0;end
            end else if(push_fire) begin
                if(qcount==0) expected_q0=expected_input;
                else expected_q1=expected_input;
            end
            if(do_reset||do_cancel) qcount=0;
            else qcount=qcount+push_fire-pop_fire;
            check_current();
        end
    endtask

    integer i;
    initial begin
        repeat(3) @(negedge clk); rst_n=1;
        step(1,0,0,0); step(1,0,0,0); // fill
        step(1,1,0,0);                 // full cannot accept even with a pop
        step(0,1,0,0); step(0,0,0,0); // drain and stall
        step(1,1,0,0); step(1,1,0,0); step(0,1,0,0); // simultaneous push/pop
        step(1,0,0,0); step(0,0,0,1); step(1,0,0,0); step(0,0,1,0);
        step(1,0,0,0); step(1,0,0,0); step(1,0,0,0); step(0,1,0,0);
        for(i=0;i<600;i=i+1) begin
            lfsr={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
            step(lfsr[0],lfsr[4]|lfsr[9],(i%137)==71,(i%211)==103);
        end
        while(qcount!=0) step(0,1,0,0);
        if(qcount!=0 || pushes<100 || pops<100 || simultaneous<40 || full_stalls<2 ||
           output_stalls<40 || bubbles<30 || resets<2 || cancels<2 || pointer_checks<cycles*35 || head_checks<100)
            $fatal(1,"coverage gate q=%0d pushes=%0d pops=%0d sim=%0d fullstall=%0d outstall=%0d bubble=%0d reset=%0d cancel=%0d ptr=%0d head=%0d cycles=%0d",
                   qcount,pushes,pops,simultaneous,full_stalls,output_stalls,bubbles,resets,cancels,pointer_checks,head_checks,cycles);
        $display("RAW_BUFFER_LOCAL_V2_PASS cycles=%0d pushes=%0d pops=%0d simultaneous=%0d full_stalls=%0d output_stalls=%0d bubbles=%0d resets=%0d cancels=%0d pointer_checks=%0d head_checks=%0d extra_pointer_flops=%0d",
                 cycles,pushes,pops,simultaneous,full_stalls,output_stalls,bubbles,resets,cancels,pointer_checks,head_checks,34);
        $finish;
    end
    initial begin #200000; $fatal(1,"raw buffer local v2 watchdog"); end
endmodule
`default_nettype wire
