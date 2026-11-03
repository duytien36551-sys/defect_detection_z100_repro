`timescale 1ns/1ps
module envw #(parameter NEW=0) (input clk, input rst_n, input go, input [31:0] ep,gen,addr,rbeg,to, input [32:0] rend,
  input [10:0] ch, input [9:0] fh,w,fr,h, input resv, input [31:0] seed_bad,
  output reg finished, output reg [3:0] fcode, output reg [2047:0] log, output reg [7:0] nlog, output reg [15:0] nbeats);
  wire cmd_ready; reg cmd_valid; wire active,fault,done,tc; wire [3:0] fc;
  wire oc,wcmd,wvalid,wlast,pready; wire [31:0] waddr,wep; wire [13:0] wwords; wire [12:0] widx; wire sc,wcan,wclr;
  reg odone, pvalid, wready, wdone, wbusy; reg [31:0] pep; reg [12:0] pidx; reg plast; reg [13:0] sent, blk_left;
  wire [31:0] D_epoch; integer tot;
`define WPORTS .clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.cmd_epoch(ep),.cmd_destination_generation(gen), \
  .cmd_destination_address(addr),.cmd_region_begin(rbeg),.cmd_timeout_cycles(to),.cmd_region_end(rend),.cmd_channels(ch),.cmd_full_height(fh), \
  .cmd_width(w),.cmd_first_row(fr),.cmd_height(h),.cmd_destination_reserved(resv),.abort(1'b0),.recover(1'b0),.active(active),.fault(fault), \
  .fault_code(fc),.done(done),.tile_committed(tc),.epoch(D_epoch),.destination_generation(),.channels(),.height(),.width(),.order_config(oc), \
  .order_config_ready(1'b1),.order_done(odone),.packed_valid(pvalid),.packed_ready(pready),.packed_epoch(pep),.packed_index(pidx),.packed_last(plast), \
  .packed_data(512'd0),.writer_command(wcmd),.writer_command_ready(!wbusy),.writer_address(waddr),.writer_words(wwords),.writer_valid(wvalid), \
  .writer_ready(wready),.writer_epoch(wep),.writer_index(widx),.writer_last(wlast),.writer_data(),.writer_done(wdone),.writer_busy(wbusy), \
  .writer_fault(1'b0),.pipeline_error(1'b0),.semantic_cancel(sc),.writer_cancel(wcan),.writer_clear_fault(wclr)
  wire [13:0] TW;
  generate if(NEW) begin : n z100_native_materialized_write_control D(`WPORTS); assign TW=D.total_words; end
  else begin : o mw_old D(`WPORTS); assign TW=D.total_words; end endgenerate
  reg [31:0] rng; reg configured;
  always @(posedge clk) begin
    if(!rst_n) begin cmd_valid<=0;finished<=0;fcode<=0;log<=0;nlog<=0;nbeats<=0;odone<=0;pvalid<=0;wready<=0;wdone<=0;wbusy<=0;sent<=0;blk_left<=0;rng<=seed_bad;configured<=0; end
    else begin
      rng <= rng*1103515245+12345;
      wdone<=0; odone<=0;
      if(go && !finished && cmd_ready && !cmd_valid && nlog==0 && !active) cmd_valid<=1; else cmd_valid<=0;
      if(oc) configured<=1;
      // packed source: in-order words for the whole tile, occasionally stalls
      if(configured && active && !pvalid && sent<TW && rng[7:6]!=0) begin pvalid<=1; pep<=D_epoch; pidx<=sent[12:0]; plast<=(sent+1==TW); end
      if(pvalid && pready) begin pvalid<=0; sent<=sent+1; end
      if(configured && sent==TW && active) odone<=1;
      wready <= rng[9:8]!=0;
      if(wcmd && !wbusy) begin if(nlog<32) log[nlog*64+:64]<={waddr,4'd0,wwords,14'd0}; nlog<=nlog+1; wbusy<=1; blk_left<=wwords; end
      if(wvalid && wready) begin nbeats<=nbeats+1; blk_left<=blk_left-1; end
      if(wbusy && blk_left==0 && !(wvalid&&wready)) begin wbusy<=0; wdone<=1; end
      if(fault && !finished) begin finished<=1; fcode<=fc; end
      if(done && !finished) begin finished<=1; fcode<=4'hF; end
    end
  end
endmodule
module tb;
  reg clk=0; always #5 clk=~clk; reg rst_n=0, go=0;
  reg [31:0] ep,gen,addr,rbeg,to; reg [32:0] rend; reg [10:0] ch; reg [9:0] fh,w,fr,h; reg resv; reg [31:0] sb;
  wire fo,fn; wire [3:0] co,cn; wire [2047:0] lo,ln; wire [7:0] no,nn; wire [15:0] bo,bn;
  envw #(0) EO(clk,rst_n,go,ep,gen,addr,rbeg,to,rend,ch,fh,w,fr,h,resv,sb,fo,co,lo,no,bo);
  envw #(1) EN(clk,rst_n,go,ep,gen,addr,rbeg,to,rend,ch,fh,w,fr,h,resv,sb,fn,cn,ln,nn,bn);
  integer i,err=0,acc=0,seed,n; reg [31:0] full;
  function [31:0] rr(input integer lo, input integer hi); rr = lo + ($urandom % (hi-lo+1)); endfunction
  initial begin
    if(!$value$plusargs("seed=%d",seed)) seed=1; $urandom(seed);
    for(i=0;i<1500;i=i+1) begin
      sb=$urandom; rst_n=0; go=0; repeat(2) @(posedge clk); #1;
      ep=($urandom%20==0)?0:$urandom; gen=($urandom%20==0)?0:$urandom; to=($urandom%20==0)?0:1000000; resv=($urandom%20!=0);
      ch=($urandom%8==0)?$urandom:rr(1,1024); w=($urandom%8==0)?$urandom:rr(1,640); fh=($urandom%8==0)?$urandom:rr(1,640);
      if ($urandom%2) begin ch=rr(1,100); w=rr(1,48); fh=rr(1,24); end
      fr=rr(0,fh); h=rr(1,fh); if($urandom%6==0) h=$urandom; if($urandom%6==0) fr=$urandom;
      if ($urandom%5==0) begin : exact
        integer g,x; g=1<<($urandom%9); x=1<<($urandom%6); if (8192/(g*x) > 640) x = x*((8192/(g*x)+639)/640);
        ch=4*g-($urandom%4); w=16*x-($urandom%16); h=8192/(g*x)+($urandom%3)-1; if(h<1) h=1; fh=h+($urandom%3); fr=fh-h; if (w>640) w=640; if(fh>640) begin fh=640; h=640; fr=0; end
      end
      full = (({1'b0,ch}+3)/4)*fh*((w+15)/16)*64;
      rbeg = {26'($urandom%32'h2000000),6'd0}; addr = rbeg + (($urandom%4==0)? 0 : {16'($urandom%1024),6'd0});
      rend = {1'b0,addr} + full + (($urandom%3)-1)*64; if ($urandom%10==0) rend=$urandom; if ($urandom%10==0) rbeg=addr+64;
      if ($urandom%10==0) begin addr=32'hffffffc0-full+64*($urandom%3); rbeg=addr; rend=33'h100000000; end
      @(negedge clk); rst_n=1; go=1;
      n=0; while(!(fo&&fn) && n<300000) begin @(posedge clk); n=n+1; end
      #1;
      if(!(fo&&fn) || co!==cn || no!==nn || lo!==ln || bo!==bn) begin
        err=err+1; if(err<10) $display("MISMATCH i=%0d fin %b/%b code %h/%h n %0d/%0d beats %0d/%0d ch=%0d w=%0d fh=%0d fr=%0d h=%0d",i,fo,fn,co,cn,no,nn,bo,bn,ch,w,fh,fr,h);
      end
      if(co==4'hF) acc=acc+1;
    end
    $display("MW_EQ completed=%0d errors=%0d",acc,err); $finish;
  end
endmodule
