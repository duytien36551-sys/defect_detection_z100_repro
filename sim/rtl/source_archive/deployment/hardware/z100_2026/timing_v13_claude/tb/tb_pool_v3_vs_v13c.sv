`timescale 1ns/1ps
// Transaction-level equivalence: z100_maxpool_window20_tapxy_v3 (rtl_full_b)
// vs z100_maxpool_window20_tapxy_v13c (rtl_full_c). Each DUT has its own
// behavioural feature-window responder (random ready / latency / out_ready);
// response payload is a pure hash of the request, so both DUTs see the same
// data for the same request regardless of timing. Logs must be identical.
`define POOL_PORTS .clk(clk),.rst_n(rst_n),.cancel(1'b0),.store_valid(1'b1),.loading(1'b0),.active_epoch(job_epoch), \
    .loaded_channels(job_channels),.loaded_height(job_height),.loaded_width(10'd20),.fw_error(1'b0), \
    .window_valid(wv),.window_ready(wr),.window_epoch(we),.window_request_tag(wt),.window_row_address(wa), \
    .window_first_x(wx),.window_channel_mask(wm),.window_y_valid(wy),.window_cancel(), \
    .window_out_valid(rv),.window_out_ready(rr),.window_tag(rt),.window_mask(rmask),.window_data(rdata), \
    .job_valid(job_valid),.job_ready(job_ready),.job_epoch(job_epoch),.job_channels(bad ? 11'd0 : job_channels), \
    .job_height(job_height),.job_width(10'd20),.out_valid(ov),.out_ready(or_),.out_epoch(oe),.out_address(oa), \
    .out_data(od),.out_last(ol),.done(done),.error_valid(err),.error_code(ecode),.active(act)
module pool_driver #(parameter integer V13C=0, SEED=1, NJOB=24) (input wire clk, output reg fin);
    reg rst_n, job_valid, bad, wr, rv, or_;
    reg [31:0] job_epoch; reg [10:0] job_channels; reg [9:0] job_height;
    wire wv, rr, ov, ol, done, err, act, wy;
    wire [31:0] we, wt, oe; wire [13:0] wa; wire signed [11:0] wx; wire [3:0] wm, ecode;
    wire [12:0] oa; wire [511:0] od;
    reg [31:0] rt; reg [79:0] rmask; reg [639:0] rdata;
    wire job_ready;
    generate if(V13C) begin : gc z100_maxpool_window20_tapxy_v13c dut(`POOL_PORTS);
             end else begin : gb z100_maxpool_window20_tapxy_v3 dut(`POOL_PORTS); end endgenerate
    // request FIFO of the feature-window model
    reg [63:0] fq[0:7]; reg [4:0] ftag[0:7]; reg fyv[0:7]; reg [3:0] fm[0:7];
    integer wp, rp, cnt, fd, rs, j, nout, i, lat; reg taken; reg [7:0] hm; integer js;
    function [7:0] h8(input [63:0] k, input integer lane);
        reg [31:0] x; begin x=k[31:0]^(k[63:32]*32'h9e3779b1)^(lane*32'h85ebca6b); x=x^(x>>15); x=x*32'h2c1b3c6d; x=x^(x>>12); h8=x[7:0]^x[23:16]; end
    endfunction
    initial begin if(V13C) fd=$fopen("pool_v13c.txt","w"); else fd=$fopen("pool_v3.txt","w"); rs=SEED*7+3; wp=0; rp=0; cnt=0; nout=0; lat=0; taken=0; end
    always @(posedge clk) begin
        if(ov&&or_) begin $fdisplay(fd,"OUT %h %h %0d %h",oe,oa,ol,od); nout=nout+1; end
        if(err) $fdisplay(fd,"ERR %0d",ecode);
        if(done) $fdisplay(fd,"DONE");
        if(wv&&wr) begin
            fq[wp[2:0]]<={we,{18'd0,wa}}^{32'd0,{20{wx[11]}},wx}; ftag[wp[2:0]]<=wt[4:0]; fyv[wp[2:0]]<=wy; fm[wp[2:0]]<=wm; wp=wp+1; cnt=cnt+1;
        end
        if(rv&&rr) begin rp=rp+1; cnt=cnt-1; taken=1; end
    end
    always @(negedge clk) begin
        or_ <= ({$random(rs)}%4)!=0;
        wr <= (cnt<6) && (({$random(rs)}%3)!=0);
        if(rv && !taken) ; // hold until accepted
        else if(cnt>0 && ({$random(rs)}%3)!=0) begin
            rv<=1; rt<={27'd0,ftag[rp[2:0]]};
            for(i=0;i<80;i=i+1) begin
                rdata[i*8+:8]<=h8(fq[rp[2:0]]^{59'd0,ftag[rp[2:0]]},i);
                hm=h8(fq[rp[2:0]],i+97);
                rmask[i]<=(ftag[rp[2:0]]==12) || (fyv[rp[2:0]] && fm[rp[2:0]][i/20] && hm[0]);
            end
        end else rv<=0;
        taken=0;
    end
    initial begin
        fin=0; js=SEED*31+11; rst_n=0; job_valid=0; bad=0; rv=0; wr=0; or_=0; job_epoch=0; job_channels=0; job_height=0;
        repeat(5) @(negedge clk); rst_n=1; repeat(3) @(negedge clk);
        for(j=0;j<NJOB;j=j+1) begin
            job_epoch=32'h100+j; bad=(j%9)==4;
            case(j%6)
                0: begin job_channels=1+{$random(js)}%8;  job_height=1+{$random(js)}%3; end
                1: begin job_channels=128; job_height=2; end
                2: begin job_channels=33+{$random(js)}%40; job_height=1+{$random(js)}%5; end
                3: begin job_channels=32; job_height=20; end
                4: begin job_channels=1+{$random(js)}%128; job_height=1; end
                default: begin job_channels=5+{$random(js)}%30; job_height=1+{$random(js)}%20; end
            endcase
            $fdisplay(fd,"JOB %0d C=%0d H=%0d bad=%0d", j, job_channels, job_height, bad);
            job_valid=1; @(posedge clk); while(!job_ready) @(posedge clk); @(negedge clk); job_valid=0;
            if(!bad) begin @(posedge clk); while(!done) @(posedge clk); end
            repeat(4) @(negedge clk);
        end
        $fclose(fd); fin=1; $display("POOL_DUT V13C=%0d finished_at=%0t", V13C, $time);
    end
endmodule
module tb_pool_v3_vs_v13c;
    reg clk=0; always #5 clk=~clk;
    wire f0, f1;
    pool_driver #(.V13C(0),.SEED(`SEED)) d0(.clk(clk),.fin(f0));
    pool_driver #(.V13C(1),.SEED(`SEED)) d1(.clk(clk),.fin(f1));
    integer cyc=0;
    always @(posedge clk) begin
        cyc=cyc+1;
        if(f0&&f1) begin $display("POOL_MITER_FIN cycles=%0d out_v3=%0d out_v13c=%0d", cyc, d0.nout, d1.nout); $finish; end
        if(cyc>3000000) begin $display("POOL_MITER_TIMEOUT f0=%0d f1=%0d", f0, f1); $finish; end
    end
endmodule
