`timescale 1ns/1ps
module tb;
  reg clk=0; always #5 clk=~clk;
  reg rst_n=0,cancel=0,cfg_valid=0,mode=0,in_valid=0,out_ready=0,in_last=0;
  reg [31:0] ep,in_ep; reg[10:0] ch; reg[9:0] h,w; reg[12:0] in_idx,in_addr; reg[511:0] in_data;
  wire o_cr,n_cr,o_ir,n_ir,o_ov,n_ov,o_ol,n_ol,o_act,n_act,o_done,n_done,o_err,n_err; wire[1:0] o_ec,n_ec;
  wire [12:0] o_oi,n_oi,o_oa,n_oa; wire[31:0] o_oe,n_oe;
`define P(cv,r,i,v,l,a,x,act,dn,er,ec,oe,oi) .clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_valid(cv),.cfg_ready(r),.cfg_epoch(ep),.cfg_write_order(mode), \
 .cfg_channels(ch),.cfg_height(h),.cfg_width(w),.in_valid(in_valid),.in_ready(i),.in_epoch(in_ep),.in_index(in_idx),.in_address(in_addr), \
 .in_last(in_last),.in_data(in_data),.out_valid(v),.out_ready(out_ready),.out_epoch(oe),.out_index(oi),.out_address(a),.out_last(l),.out_data(), \
 .active(act),.done(dn),.error_valid(er),.error_code(ec)
  wire o_cv = cfg_valid && n_cr;
  so_old O(`P(o_cv,o_cr,o_ir,o_ov,o_ol,o_oa,,o_act,o_done,o_err,o_ec,o_oe,o_oi));
  z100_native_stream_order N(`P(cfg_valid,n_cr,n_ir,n_ov,n_ol,n_oa,,n_act,n_done,n_err,n_ec,n_oe,n_oi));
  integer cyc=0,err=0,jobs=0,beats=0,seed,k; reg ocfg_seen;
  // Reference expectation for in_address in write mode from old internal regs
  function [31:0] oaddr; input dummy; oaddr = O.address_calc; endfunction
  initial begin
    if(!$value$plusargs("seed=%d",seed)) seed=1; $urandom(seed);
    repeat(3)@(posedge clk); rst_n=1;
    for(k=0;k<3000;k=k+1) begin
      @(negedge clk);
      mode=$urandom%2; ep=($urandom%20==0)?0:$urandom; ch=($urandom%10==0)?$urandom:1+$urandom%100; h=($urandom%10==0)?$urandom:1+$urandom%12; w=($urandom%10==0)?$urandom:1+$urandom%60;
      if ($urandom%5==0) begin ch=1+$urandom%1024; h=1+$urandom%640; w=1+$urandom%640; end
      cfg_valid=1;
      // old accepts immediately when idle; new waits until stable. Hold cfg until new accepts.
      while(!n_cr) begin @(negedge clk); end
      if(!o_cr) begin err=err+1; $display("OLD not ready"); end
      @(posedge clk); #1 cfg_valid=0; jobs=jobs+1;
      // drive beats until done/error, with random stalls and occasional bad metadata/cancel
      while(N.active) begin
        @(negedge clk);
        in_valid=($urandom%4!=0); out_ready=($urandom%3!=0); in_ep=($urandom%400==0)?32'hdead:N.epoch_q;
        in_idx=($urandom%400==0)?13'h1fff:N.sequence_q[12:0]; in_addr=($urandom%400==0)?13'h1fff:N.address_calc[12:0];
        in_last=N.sequence_q+1==N.total_words_q; if($urandom%500==0) in_last=!in_last; in_data=$urandom;
        cancel=($urandom%3000==0);
        #1;
        if (O.active!==N.active || (O.active && (o_ir!==n_ir || o_ov!==n_ov || o_oa!==n_oa || o_ol!==n_ol || o_oi!==n_oi || O.address_calc!==N.address_calc))) begin
          err=err+1; if(err<10) $display("MISMATCH job=%0d seq=%0d oa=%0d na=%0d ir %b/%b ov %b/%b",jobs,O.sequence_q,O.address_calc,N.address_calc,o_ir,n_ir,o_ov,n_ov);
        end
        @(posedge clk); #1; beats=beats+(in_valid&&o_ir);
        if (o_done!==n_done || o_err!==n_err || o_ec!==n_ec) begin err=err+1; if(err<10)$display("STATUS mismatch"); end
        cancel=0;
      end
      // after accept-cycle both must agree (check old accepted the same cfg verdict)
    end
    $display("SO_EQ jobs=%0d beats=%0d errors=%0d",jobs,beats,err); $finish;
  end
  // Old module must see the cfg at the same cycle the new accepts: align by forcing old to accept only when new accepts.
endmodule
