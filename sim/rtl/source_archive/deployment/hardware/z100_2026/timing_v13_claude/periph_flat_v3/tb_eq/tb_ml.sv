`timescale 1ns/1ps
// Transaction-level equivalence: each DUT gets its own environment model.
// For every command we compare: accept/reject verdict, fault code, the ordered
// list of reader commands (address, block words, word base), total words, and
// completion. Timing may differ.
module env #(parameter NEW=0) (input clk, input rst_n, input go, input [31:0] ep,gen,addr,to,
  input [10:0] ch, input [9:0] fh,w,fr,h, input comm,
  output reg finished, output reg [3:0] fcode, output reg [1023:0] log, output reg [7:0] nlog, output [13:0] tw);
  wire cmd_ready; reg cmd_valid; wire active,fault,done,rc; wire [3:0] fc;
  wire fb,oc,fcm,rcmd; wire [31:0] raddr; wire [13:0] bw,bwb; reg rdone; reg busy;
  wire sc,rcan,rclr;
  reg odone; integer t;
  generate if(NEW) begin : n
    z100_native_materialized_load_control D(.clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.cmd_epoch(ep),.cmd_source_generation(gen),
     .cmd_source_address(addr),.cmd_timeout_cycles(to),.cmd_channels(ch),.cmd_full_height(fh),.cmd_width(w),.cmd_first_row(fr),.cmd_height(h),
     .cmd_source_committed(comm),.cmd_source_is_materialized(1'b1),.abort(1'b0),.recover(1'b0),.active(active),.fault(fault),.fault_code(fc),.done(done),
     .result_committed(rc),.epoch(),.source_generation(),.channels(),.height(),.width(),.total_words(tw),.block_words(bw),.block_word_base(bwb),
     .feature_begin(fb),.feature_begin_ready(1'b1),.order_config(oc),.order_config_ready(1'b1),.order_done(odone),.feature_commit(fcm),.feature_commit_ready(1'b1),
     .reader_command(rcmd),.reader_command_ready(1'b1),.reader_address(raddr),.reader_done(rdone),.reader_busy(busy),.reader_fault(1'b0),.pipeline_error(1'b0),
     .semantic_cancel(sc),.reader_cancel(rcan),.reader_clear_fault(rclr));
  end else begin : o
    ml_old D(.clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.cmd_epoch(ep),.cmd_source_generation(gen),
     .cmd_source_address(addr),.cmd_timeout_cycles(to),.cmd_channels(ch),.cmd_full_height(fh),.cmd_width(w),.cmd_first_row(fr),.cmd_height(h),
     .cmd_source_committed(comm),.cmd_source_is_materialized(1'b1),.abort(1'b0),.recover(1'b0),.active(active),.fault(fault),.fault_code(fc),.done(done),
     .result_committed(rc),.epoch(),.source_generation(),.channels(),.height(),.width(),.total_words(tw),.block_words(bw),.block_word_base(bwb),
     .feature_begin(fb),.feature_begin_ready(1'b1),.order_config(oc),.order_config_ready(1'b1),.order_done(odone),.feature_commit(fcm),.feature_commit_ready(1'b1),
     .reader_command(rcmd),.reader_command_ready(1'b1),.reader_address(raddr),.reader_done(rdone),.reader_busy(busy),.reader_fault(1'b0),.pipeline_error(1'b0),
     .semantic_cancel(sc),.reader_cancel(rcan),.reader_clear_fault(rclr));
  end endgenerate
  always @(posedge clk) begin
    if(!rst_n) begin cmd_valid<=0; finished<=0; fcode<=0; log<=0; nlog<=0; rdone<=0; odone<=0; busy<=0; t<=0; end
    else begin
      rdone<=0; odone<=0;
      if(go && !finished && cmd_ready && !cmd_valid && nlog==0 && !active) cmd_valid<=1; else cmd_valid<=0;
      if(rcmd) begin if(nlog<16) log[nlog*64+:64] <= {raddr, 4'd0, bw, bwb[13:0]}; nlog<=nlog+1; busy<=1; t<=3; end
      if(busy) begin if(t==0) begin busy<=0; rdone<=1; end else t<=t-1; end
      if(fault && !finished) begin finished<=1; fcode<=fc; end
      if(done && !finished) begin finished<=1; fcode<=4'hF; end
      if(fcm) odone<=1;
      if(active && !busy && !rcmd) odone<=1;
    end
  end
endmodule
module tb;
  reg clk=0; always #5 clk=~clk; reg rst_n=0, go=0;
  reg [31:0] ep,gen,addr,to; reg [10:0] ch; reg [9:0] fh,w,fr,h; reg comm;
  wire fo,fn; wire [3:0] co,cn; wire [1023:0] lo,ln; wire [7:0] no,nn; wire [13:0] two,twn;
  env #(0) EO(clk,rst_n,go,ep,gen,addr,to,ch,fh,w,fr,h,comm,fo,co,lo,no,two);
  env #(1) EN(clk,rst_n,go,ep,gen,addr,to,ch,fh,w,fr,h,comm,fn,cn,ln,nn,twn);
  integer i,err=0,acc=0,seed,n;
  function [31:0] rr(input integer lo, input integer hi); rr = lo + ($urandom % (hi-lo+1)); endfunction
  initial begin
    if(!$value$plusargs("seed=%d",seed)) seed=1; $urandom(seed);
    for(i=0;i<6000;i=i+1) begin
      rst_n=0; go=0; repeat(2) @(posedge clk); #1;
      ep=($urandom%20==0)?0:$urandom; gen=($urandom%20==0)?0:$urandom; to=($urandom%20==0)?0:1000000; comm=($urandom%20!=0);
      ch=($urandom%8==0)?$urandom:rr(1,1024); w=($urandom%8==0)?$urandom:rr(1,640); fh=($urandom%8==0)?$urandom:rr(1,640);
      if ($urandom%2) begin ch=rr(1,200); w=rr(1,64); fh=rr(1,40); end
      fr=rr(0,fh); h=rr(1,fh); if($urandom%6==0) h=$urandom; if($urandom%6==0) fr=$urandom;
      if ($urandom%5==0) begin : exact
        integer g,x; g=1<<($urandom%9); x=1<<($urandom%6); if (8192/(g*x) > 640) x = x*((8192/(g*x)+639)/640);
        ch=4*g-($urandom%4); w=16*x-($urandom%16); h=8192/(g*x)+($urandom%3)-1; if(h<1) h=1; fh=h+($urandom%3); fr=fh-h; if (w>640) w=640; if(fh>640) begin fh=640; h=640; fr=0; end
      end
      addr=($urandom%8==0)?$urandom:{$urandom%32'h4000000,6'd0};
      if ($urandom%4==0) addr = 32'hffffffc0 - (({1'b0,ch}+3)/4)*fh*((w+15)/16)*64 + (($urandom%3)-1)*64;
      @(negedge clk); rst_n=1; go=1;
      n=0; while(!(fo&&fn) && n<20000) begin @(posedge clk); n=n+1; end
      #1;
      if(!(fo&&fn) || co!==cn || no!==nn || lo!==ln || (co==4'hF && two!==twn)) begin
        err=err+1; if(err<4) $display("ST old=%0d new=%0d obusy=%b of=%b", EO.o.D.state, EN.n.D.state, EO.busy, EO.o.D.order_finished); if(err<10) $display("MISMATCH i=%0d fin %b/%b code %h/%h n %0d/%0d ch=%0d w=%0d fh=%0d fr=%0d h=%0d addr=%h",i,fo,fn,co,cn,no,nn,ch,w,fh,fr,h,addr);
      end
      if(co==4'hF) acc=acc+1;
    end
    $display("ML_EQ completed=%0d errors=%0d",acc,err); $finish;
  end
endmodule
