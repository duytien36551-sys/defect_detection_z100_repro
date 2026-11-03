`timescale 1ns/1ps
// Transaction-level equivalence: z100_requant_factor32 vs _v13c. Each DUT has
// its own driver (same seed for content, own seed for valid/ready timing).
// Good jobs: every output beat logged and compared. Faulty jobs (one beat with
// a wrong epoch): outputs not logged, the ERR line is.
`define RQ_PORTS .clk(clk),.rst_n(rst_n),.cancel(1'b0),.cfg_begin(cfg_begin),.cfg_begin_ready(cbr),.cfg_epoch(cfg_epoch), \
    .cfg_lanes(cfg_lanes),.cfg_word_valid(cfg_word_valid),.cfg_word_ready(cwr),.cfg_multiplier(cfg_mult),.cfg_shift(cfg_shift), \
    .cfg_commit(cfg_commit),.cfg_commit_ready(ccr),.cfg_error(cfg_error),.input_error(input_error),.in_valid(in_valid), \
    .in_ready(in_ready),.in_epoch(in_epoch),.in_token(in_token),.in_site(in_site),.in_last(in_last),.in_data(in_data), \
    .out_valid(out_valid),.out_ready(out_ready),.out_epoch(out_epoch),.out_token(out_token),.out_site(out_site), \
    .out_lanes(out_lanes),.out_last(out_last),.out_data(out_data)
module rq_driver #(parameter integer V13C=0, SEED=1, NJOB=30) (input wire clk, output reg fin);
    reg rst_n,cfg_begin,cfg_word_valid,cfg_commit,in_valid,in_last,out_ready,bad_job;
    reg [31:0] cfg_epoch,in_epoch,in_token; reg [5:0] cfg_lanes,cfg_shift; reg [30:0] cfg_mult;
    reg [4:0] in_site; reg [1023:0] in_data;
    wire cbr,cwr,ccr,cfg_error,input_error,in_ready,out_valid,out_last;
    wire [31:0] out_epoch,out_token; wire [4:0] out_site; wire [5:0] out_lanes; wire [255:0] out_data;
    generate if(V13C) begin : gc z100_requant_factor32_v13c dut(`RQ_PORTS);
             end else begin : gb z100_requant_factor32 dut(`RQ_PORTS); end endgenerate
    integer fd,cs,ts,j,b,l,nbeat,badb,nout,got_err;
    initial begin
        if(V13C) fd=$fopen("rq_v13c.txt","w"); else fd=$fopen("rq_v12.txt","w");
        cs=SEED*101+7; ts=SEED*13+(V13C?977:3); nout=0; bad_job=0; got_err=0;
    end
    always @(posedge clk) begin
        if(out_valid&&out_ready) begin nout=nout+1; if(!bad_job) $fdisplay(fd,"OUT %h %h %0d %0d %0d %h",out_epoch,out_token,out_site,out_lanes,out_last,out_data); end
        if(input_error) begin if(!got_err) $fdisplay(fd,"IERR job=%0d",j); got_err=1; end
        if(cfg_error) $fdisplay(fd,"CERR job=%0d",j);
    end
    always @(negedge clk) out_ready <= ({$random(ts)}%4)!=0;
    task idle(input integer n); integer q; begin for(q=0;q<n;q=q+1) @(negedge clk); end endtask
    initial begin
        fin=0; rst_n=0; cfg_begin=0; cfg_word_valid=0; cfg_commit=0; in_valid=0; in_last=0;
        cfg_epoch=0; cfg_lanes=0; cfg_mult=0; cfg_shift=0; in_epoch=0; in_token=0; in_site=0; in_data=0;
        idle(5); rst_n=1; idle(2);
        for(j=0;j<NJOB;j=j+1) begin
            // wait for the pipeline to drain (cfg_begin_ready requires empty)
            cs=SEED*7919+j*104729+1; // per-job content seed: independent of beats consumed by an earlier faulty job
            cfg_epoch=32'h40+j; cfg_lanes=1+{$random(cs)}%32; if(j%7==3) cfg_lanes=32;
            cfg_begin=1; @(posedge clk); while(!cbr) @(posedge clk); @(negedge clk); cfg_begin=0;
            for(l=0;l<cfg_lanes;l=l+1) begin
                cfg_mult=1+{$random(cs)}%31'h7fffffff; cfg_shift=(j%4==0) ? {$random(cs)}%64 : 36+{$random(cs)}%26;
                cfg_word_valid=1; @(posedge clk); while(!cwr) @(posedge clk); @(negedge clk); cfg_word_valid=0;
            end
            cfg_commit=1; @(posedge clk); while(!ccr) @(posedge clk); @(negedge clk); cfg_commit=0;
            nbeat=1+{$random(cs)}%60; badb=(j%5==2) ? {$random(cs)}%nbeat : -1; bad_job=badb>=0; got_err=0;
            $fdisplay(fd,"JOB %0d lanes=%0d beats=%0d bad=%0d",j,cfg_lanes,nbeat,badb);
            for(b=0;b<nbeat && !got_err;b=b+1) begin
                while(({$random(ts)}%3)==0) @(negedge clk);
                in_epoch=(b==badb) ? cfg_epoch+1 : cfg_epoch; in_token=1+b; in_site=b%20; in_last=(b==nbeat-1);
                for(l=0;l<32;l=l+1) in_data[l*32+:32]=$random(cs);
                in_valid=1; @(posedge clk); while(!in_ready && !got_err) @(posedge clk); @(negedge clk); in_valid=0;
            end
            // drain: generous idle so every good beat leaves both designs
            idle(80); bad_job=0;
        end
        $fdisplay(fd,"END"); $fclose(fd); fin=1;
    end
endmodule
module tb_requant32_vs_v13c;
    reg clk=0; always #5 clk=~clk;
    wire f0,f1;
    rq_driver #(.V13C(0),.SEED(`SEED)) d0(.clk(clk),.fin(f0));
    rq_driver #(.V13C(1),.SEED(`SEED)) d1(.clk(clk),.fin(f1));
    integer cyc=0;
    always @(posedge clk) begin cyc=cyc+1;
        if(f0&&f1) begin $display("RQ_MITER_FIN cycles=%0d out_v12=%0d out_v13c=%0d",cyc,d0.nout,d1.nout); $finish; end
        if(cyc>400000) begin $display("RQ_MITER_TIMEOUT"); $finish; end
    end
endmodule
