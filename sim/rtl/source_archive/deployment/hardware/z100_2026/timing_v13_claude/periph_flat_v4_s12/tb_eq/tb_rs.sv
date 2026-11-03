`timescale 1ns/1ps
module tb;
  reg clk=0; always #5 clk=~clk;
  reg rst_n=0, cmd_valid=0;
  reg [31:0] ep,tk,tg; reg[10:0] ch; reg[9:0] iw,ow; reg[1:0] k,s,p; reg[5:0] ln; reg[13:0] bw,ps; reg[41:0] kyb; reg[2:0] yv;
  wire o_ready,n_ready,o_fv,n_fv; wire [2:0] o_fc,n_fc;
`define P .clk(clk),.rst_n(rst_n),.cancel(1'b0),.cmd_valid(cmd_valid),.cmd_epoch(ep),.cmd_token_base(tk),.cmd_tag_base(tg), \
  .cmd_channels(ch),.cmd_input_width(iw),.cmd_output_width(ow),.cmd_kernel(k),.cmd_stride(s),.cmd_padding(p),.cmd_lanes(ln), \
  .cmd_bank_words(bw),.cmd_channel_plane_stride(ps),.cmd_ky_row_bases(kyb),.cmd_y_valid(yv),.run_ready(1'b0),.window_ready(1'b0), \
  .post_done_valid(1'b0),.post_done_epoch(32'd0),.post_done_token(32'd0)
  rs_old O(`P,.cmd_ready(o_ready),.fault_valid(o_fv),.fault_code(o_fc));
  z100_native_row_scheduler20 N(`P,.cmd_ready(n_ready),.fault_valid(n_fv),.fault_code(n_fc));
  integer i,err=0,nacc=0,seed,mode,d; reg o_ok; reg o_fault_seen;
  function [31:0] rr(input integer lo, input integer hi); rr = lo + ($urandom % (hi-lo+1)); endfunction
  task gen; begin
    mode=$urandom%6;
    ep=$urandom; tk=($urandom%10==0)?0:$urandom; tg=$urandom;
    k=($urandom%2)?3:(($urandom%4==0)?$urandom:1); s=($urandom%2)?2:(($urandom%4==0)?$urandom:1); p=($urandom%2)?1:(($urandom%6==0)?$urandom:0);
    ch=(mode==0)?$urandom:rr(1,1030); iw=(mode==1)?$urandom:rr(1,645);
    ow=(s==2)?((iw+2*p-k)>>1)+1:(iw+2*p-k)+1; if($urandom%6==0) ow=$urandom;
    ln=($urandom%8==0)?$urandom:rr(1,32); bw=($urandom%8==0)?$urandom:rr(1,8192); ps=($urandom%10==0)?0:rr(1,300);
    kyb={14'($urandom),14'($urandom),14'($urandom)}; yv=$urandom;
    if (mode>=3) begin // mostly legal, small addresses
      k=($urandom%2)?3:1; s=($urandom%2)?2:1; p=(k==3)?$urandom%2:0; ch=rr(1,64); iw=rr(k,200);
      ow=(s==2)?((iw+2*p-k)>>1)+1:(iw+2*p-k)+1; ln=rr(1,32); bw=rr(1,8192); ps=rr(1,200);
      kyb={14'(rr(0,3000)),14'(rr(0,3000)),14'(rr(0,3000))}; tk=rr(1,1000); tg=rr(1,1000);
      #1;
      if (mode==4) begin d=$urandom%3; bw = O.checked_row_end + d; end
      if (mode==5) begin tg = 33'h1_0000_0000 - (((ow+19)/20)*O.checked_groups) + ($urandom%3)-1; tk = 33'h1_0000_0000 - ((ow+19)/20) + ($urandom%3)-1; if(tk==0) tk=1; end
    end
  end endtask
  initial begin
    if(!$value$plusargs("seed=%d",seed)) seed=1; $urandom(seed);
    repeat(3) @(posedge clk); rst_n=1; @(posedge clk);
    for(i=0;i<20000;i=i+1) begin
      gen;
      @(negedge clk); if(!(o_ready&&n_ready)) begin err=err+1; if(err<10)$display("NOTREADY %0d",i); end
      o_ok=O.cmd_ok; cmd_valid=1; @(posedge clk); #1 cmd_valid=0;
      o_fault_seen=o_fv;
      if (o_ok !== (O.state==1) || o_fault_seen !== !o_ok) begin err=err+1; $display("OLDSELF %0d",i); end
      repeat(6) @(posedge clk); #1;
      if ((N.state==1)!==o_ok || (o_ok && (N.group_count_q!==O.group_count_q || N.channel_groups_q!==O.channel_groups_q || N.current_sites_q!==O.current_sites_q || N.ky_bases_q!==O.ky_bases_q || N.token_q!==O.token_q || N.tag_q!==O.tag_q || N.lanes_q!==O.lanes_q))) begin
        err=err+1; if(err<20) $display("MISMATCH %0d old_ok=%0d nstate=%0d ch=%0d iw=%0d ow=%0d k=%0d s=%0d p=%0d bw=%0d ps=%0d", i,o_ok,N.state,ch,iw,ow,k,s,p,bw,ps);
      end
      if (!o_ok && N.state!=0) begin err=err+1; end
      if (o_ok) nacc=nacc+1;
      force O.state=0; force N.state=0; @(posedge clk); #1 release O.state; release N.state; @(posedge clk);
    end
    $display("RS_EQ accepted=%0d errors=%0d",nacc,err); $finish;
  end
  // new-side fault pulse must appear exactly when rejecting
  integer nf=0; always @(posedge clk) if (n_fv && n_fc==1) nf=nf+1;
  final $display("new_fault_pulses=%0d", nf);
endmodule
