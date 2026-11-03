`timescale 1ns/1ps
module tb;
  reg clk=0; always #5 clk=~clk;
  reg rst_n=0, recover=0;
  reg cmd_valid=0;
  reg [31:0] ep,tk,tg,jt; reg[15:0] pf; reg[10:0] ci,co; reg[9:0] ih,iw,iy,ir,oh,ow,oy,orr; reg[1:0] k,s,p;
  wire o_ready,n_ready;
  wire [3:0] o_fc,n_fc; wire o_fault,n_fault;
  wire o_pack_valid,n_pack_valid;
`define PORTS(pre) .clk(clk),.rst_n(rst_n),.cancel(1'b0),.recover(recover),.recovery_drained(1'b1), \
   .cmd_valid(cmd_valid),.cmd_epoch(ep),.cmd_token_base(tk),.cmd_tag_base(tg),.cmd_job_tag(jt),.cmd_parameter_first(pf), \
   .cmd_input_channels(ci),.cmd_output_channels(co),.cmd_input_height(ih),.cmd_input_width(iw),.cmd_input_y(iy),.cmd_input_rows(ir), \
   .cmd_output_height(oh),.cmd_output_width(ow),.cmd_output_y(oy),.cmd_output_rows(orr),.cmd_kernel(k),.cmd_stride(s),.cmd_padding(p), \
   .pack_ready(1'b0),.parameter_ready(1'b0),.parameter_done_valid(1'b0),.parameter_done_epoch(32'd0),.parameter_done_job_tag(32'd0), \
   .parameter_done_job(16'd0),.parameter_done_error(1'b0),.row_ready(1'b0),.row_done_valid(1'b0),.row_done_epoch(32'd0), \
   .row_done_last_token(32'd0),.row_done_job_tag(32'd0),.row_done_error(1'b0),.publish_valid(1'b0),.publish_epoch(32'd0), \
   .publish_tag(32'd0),.publish_error(1'b0)
  tc_old O(`PORTS(o) ,.cmd_ready(o_ready),.fault(o_fault),.fault_code(o_fc),.pack_valid(o_pack_valid));
  z100_native_conv_tile_control_v2 N(`PORTS(n) ,.cmd_ready(n_ready),.fault(n_fault),.fault_code(n_fc),.pack_valid(n_pack_valid));
  integer i, nacc=0, nrej=0, err=0, seed, mode;
  function [31:0] rr(input integer lo, input integer hi); rr = lo + ($urandom % (hi-lo+1)); endfunction
  task gen;
    begin
      mode=$urandom%8;
      ep = O.ledger_epoch + rr(0,2); jt = O.ledger_tag + rr(0,3) - 1;
      if ($urandom%16==0) ep=$urandom; if ($urandom%16==0) jt=$urandom;
      tk = ($urandom%8==0)? 0 : (($urandom%4==0)? 32'hffffffff - rr(0,4000000) : $urandom);
      tg = ($urandom%4==0)? 32'hffffffff - rr(0,20000000) : $urandom; if ($urandom%32==0) tg=0;
      pf = ($urandom%4==0)? 16'hffff - rr(0,64) : rr(0,200);
      k = ($urandom%2)? 3 : (($urandom%4==0)? $urandom : 1);
      s = ($urandom%2)? 2 : (($urandom%4==0)? $urandom : 1);
      p = ($urandom%2)? 1 : (($urandom%6==0)? $urandom : 0);
      ci = (mode==0)? $urandom : rr(1,1030); co = (mode==1)? $urandom : rr(1,1030);
      ih = (mode==2)? $urandom : rr(1,645); iw = (mode==3)? $urandom : rr(1,645);
      if (mode>=4) begin ci=rr(1,64); co=rr(1,128); ih=rr(k,40); iw=rr(k,80); end
      // consistent output dims most of the time
      oh = (s==2)? ((ih+2*p-k)>>1)+1 : (ih+2*p-k)+1; ow = (s==2)? ((iw+2*p-k)>>1)+1 : (iw+2*p-k)+1;
      if ($urandom%6==0) oh=$urandom; if ($urandom%6==0) ow=$urandom;
      oy = rr(0, oh>0?oh-1:0); orr = rr(1, (oh>oy)? oh-oy : 1); if ($urandom%10==0) orr=$urandom;
      iy = ($urandom%3==0)? $urandom%ih : ((oy*s>p)? oy*s-p : 0); ir = ($urandom%5==0)? $urandom : (ih>iy? rr(1,ih-iy):1);
      if ($urandom%10==0) iy=$urandom;
      if (mode>=5) begin : valid_cmd
        integer g,x,d;
        ep = O.ledger_epoch + 1; jt = 1; k = ($urandom%2)?3:1; s = ($urandom%2)?2:1; p = (k==3)? ($urandom%2) : 0;
        ih = rr(k+2,640); iw = rr(k+2,640);
        oh = (s==2)? ((ih+2*p-k)>>1)+1 : (ih+2*p-k)+1; ow = (s==2)? ((iw+2*p-k)>>1)+1 : (iw+2*p-k)+1;
        ci = rr(1,1024); co = rr(1,1024); oy=0; orr=oh; iy=0; ir=ih; pf=rr(0,100);
        tk = rr(1,1000); tg = rr(1,1000);
        d = $urandom%3; d = d-1;
        if (mode==5) begin // words boundary 8192
          g = 1<<($urandom%9); x = 1<<($urandom%6);
          co = 4*g; orr = 8192/(g*x) + d; if (orr<1) orr=1;
          ow = 16*x - ($urandom%16); iw = (s==2)? 2*ow - 2 + k - 2*p : ow - 1 + k - 2*p;
          if (iw<1 || iw>640) iw = 16; oh = orr; ih = (s==2)? 2*oh-2+k-2*p : oh-1+k-2*p; ir=ih;
          ow = (s==2)? ((iw+2*p-k)>>1)+1 : (iw+2*p-k)+1; oh = (s==2)? ((ih+2*p-k)>>1)+1 : (ih+2*p-k)+1; orr=oh;
        end
        if (mode==6) begin // bank_words boundary 4096
          g = 1<<($urandom%9); x = 1<<($urandom%6);
          ci = 4*g - ($urandom%4); iw = 16*x - ($urandom%16); ir = 4096/(g*x) + d; if (ir<1) ir=1; ih = ir;
          if (ih < k) ih = k;
          oh = (s==2)? ((ih+2*p-k)>>1)+1 : (ih+2*p-k)+1; ow = (s==2)? ((iw+2*p-k)>>1)+1 : (iw+2*p-k)+1; orr=oh; ir=ih;
        end
        #0;
        if (mode==7 || $urandom%2) begin // tag / token / param boundary
          #1; tg = 33'h1_0000_0000 - O.runs*O.groups + ($urandom%3) - 1;
          tk = 33'h1_0000_0000 - O.runs + ($urandom%3) - 1; if (tk==0) tk=1;
          if ($urandom%2) pf = 16'hffff - O.outgroups + 1 + ($urandom%3) - 1;
          if (tg==0) tg=1;
        end
      end
    end
  endtask
  reg o_ok; reg [31:0] o_step; reg [5:0] o_gc,o_seg,o_xw; reg [13:0] o_bw,o_pl;
  initial begin
    if(!$value$plusargs("seed=%d",seed)) seed=1; $urandom(seed);
    repeat(3) @(posedge clk); rst_n=1; @(posedge clk);
    for(i=0;i<20000;i=i+1) begin
      gen;
      @(negedge clk); if(!(o_ready&&n_ready)) begin $display("NOT_READY i=%0d %b %b",i,o_ready,n_ready); err=err+1; end
      o_ok=O.command_ok; cmd_valid=1;
      @(posedge clk); #1 cmd_valid=0;
      // old decided at that edge; capture old results
      o_step=O.tag_step_q; o_gc=O.group_count_q; o_seg=O.segments_q; o_bw=O.bank_words_q; o_pl=O.plane_q; o_xw=O.xwords_q;
      if (o_ok !== (O.state==1)) begin $display("OLDSELF i=%0d",i); err=err+1; end
      // new: wait for decision
      repeat(7) @(posedge clk); #1;
      if ((N.state==1) !== o_ok || (N.state==7) !== !o_ok || (n_fault&&n_fc!=1)) begin
        err=err+1; if(err<20) $display("MISMATCH i=%0d old_ok=%0d new_state=%0d ci=%0d co=%0d ih=%0d iw=%0d iy=%0d ir=%0d oh=%0d ow=%0d oy=%0d or=%0d k=%0d s=%0d p=%0d tk=%h tg=%h pf=%h",
          i,o_ok,N.state,ci,co,ih,iw,iy,ir,oh,ow,oy,orr,k,s,p,tk,tg,pf);
      end else if (o_ok && (N.tag_step_q!==o_step || N.group_count_q!==o_gc || N.segments_q!==o_seg || N.bank_words_q!==o_bw || N.plane_q!==o_pl || N.xwords_q!==o_xw
                 || N.ledger_epoch!==O.ledger_epoch || N.ledger_tag!==O.ledger_tag || N.cin_q!==O.cin_q || N.rows_q!==O.rows_q)) begin
        err=err+1; if(err<20) $display("REGMISMATCH i=%0d step %h/%h gc %0d/%0d seg %0d/%0d bw %0d/%0d pl %0d/%0d xw %0d/%0d",i,N.tag_step_q,o_step,N.group_count_q,o_gc,N.segments_q,o_seg,N.bank_words_q,o_bw,N.plane_q,o_pl,N.xwords_q,o_xw);
      end
      if (o_ok) nacc=nacc+1; else nrej=nrej+1;
      // return both to IDLE: accepted -> reset (keeps ledger? no) ; use recover from FAILED, else force via rst-free path
      if (o_ok) begin force O.state=0; force N.state=0; @(posedge clk); #1 release O.state; release N.state; end
      else begin recover=1; @(posedge clk); #1 recover=0; end
      @(posedge clk);
    end
    $display("TC_EQ seed=%0d accepted=%0d rejected=%0d errors=%0d",seed,nacc,nrej,err);
    $finish;
  end
endmodule
