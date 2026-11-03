`timescale 1ns/1ps
module tb_mm2s_public_slice;
  reg clk=0, reset=1, sv=0, mr=0, active=0;
  reg [34:0] sd=0;
  wire sr, mv;
  wire [34:0] md;
  reg [34:0] expected[0:8191];
  integer head=0, tail=0, sent=0, received=0, cycle=0, resets=0;
  reg consumed=0, stalled=0;
  reg [34:0] held;
  always #5 clk=~clk;
  reg av=0,br=0;
  reg [60:0] ad=0;
  wire ar,bv;
  wire [60:0] bd;
  reg [60:0] address_expected[0:8191];
  integer ah=0,at=0,ar_received=0;
  reg ac=0, astalled=0;
  reg [60:0] aheld;
  // Compile the actual generated public wrapper, not only its R helper.
  system_mm2s_response_slice_0 dut(.aclk(clk),
    .aresetn(~reset),
    .s_axi_rdata(md[31:0]),
    .s_axi_rresp(md[33:32]),
    .s_axi_rlast(md[34]),
    .s_axi_rvalid(mv),
    .s_axi_rready(mr),
    .m_axi_rdata(sd[31:0]),
    .m_axi_rresp(sd[33:32]),
    .m_axi_rlast(sd[34]),
    .m_axi_rvalid(sv),
    .m_axi_rready(sr),
    .s_axi_arvalid(av),
    .s_axi_arready(ar),
    .m_axi_arvalid(bv),
    .m_axi_arready(br),
    .s_axi_araddr(ad[31:0]),
    .m_axi_araddr(bd[31:0]),
    .s_axi_arlen(ad[39:32]),
    .m_axi_arlen(bd[39:32]),
    .s_axi_arsize(ad[42:40]),
    .m_axi_arsize(bd[42:40]),
    .s_axi_arburst(ad[44:43]),
    .m_axi_arburst(bd[44:43]),
    .s_axi_arlock(ad[45:45]),
    .m_axi_arlock(bd[45:45]),
    .s_axi_arcache(ad[49:46]),
    .m_axi_arcache(bd[49:46]),
    .s_axi_arprot(ad[52:50]),
    .m_axi_arprot(bd[52:50]),
    .s_axi_arregion(ad[56:53]),
    .m_axi_arregion(bd[56:53]),
    .s_axi_arqos(ad[60:57]),
    .m_axi_arqos(bd[60:57]));
  always @(posedge clk) begin
    ac=av&&ar;
    if(active && !reset) begin
      if(astalled && (!bv || bd!==aheld)) $fatal(1,"Address changed under backpressure");
      if(bv&&br) begin
        if(ah==at || bd!==address_expected[ah]) $fatal(1,"Address lost/reordered/stale");
        ah=ah+1;ar_received=ar_received+1;
      end
      if(av&&ar) begin address_expected[at]=ad;at=at+1;end
      astalled=bv&&!br;aheld=bd;
    end else astalled=0;
  end
  always @(posedge clk) begin
    consumed=sv&&sr;
    if(active && !reset) begin
      if(stalled && (!mv || md!==held)) $fatal(1,"Payload/valid changed under backpressure");
      if(mv&&mr) begin
        if(head==tail || md!==expected[head]) $fatal(1,"Lost/reordered/stale response");
        head=head+1; received=received+1;
      end
      if(sv&&sr) begin expected[tail]=sd;tail=tail+1;sent=sent+1;end
      stalled=mv&&!mr;held=md;
    end else stalled=0;
  end
  task apply_reset;
    input integer phase;
    begin
      active=0;sv=0;mr=0;av=0;br=0;
      @(negedge clk); #(phase); reset=1;
      repeat(6) @(negedge clk);
      head=0;tail=0;ah=0;at=0;
      reset=0;
      repeat(5) @(negedge clk);
      if(mv || bv) $fatal(1,"Stale valid after reset flush");
      active=1;resets=resets+1;
    end
  endtask
  task traffic;
    input integer count;
    integer i;
    begin
      for(i=0;i<count;i=i+1) begin
        @(negedge clk);
        if(!sv || consumed) begin
          sv=((i%7)!=0);
          sd={sent[2:0],sent[31:0]};
        end
        mr=((i%11)>3);
        if(!av || ac) begin
          av=((i%9)!=0);
          ad[31:0]=at<<2;
          ad[60:32]={4'h0,4'h0,3'h0,4'h3,1'b0,2'b01,3'd2,8'd15};
        end
        br=((i%13)>4);
      end
      @(negedge clk);mr=1;br=1;
      while(sv && !consumed) @(negedge clk);
      sv=0;
      while(av && !ac) @(negedge clk);
      av=0;
      repeat(10) @(negedge clk);
      if(head!=tail || ah!=at) $fatal(1,"Not all accepted responses drained");
    end
  endtask
  reg old_valid;
  reg [34:0] old_data;
  initial begin
    apply_reset(1);traffic(1200);
    // An asynchronous upstream transition must not reach the downstream
    // RAM-control side between clock edges.
    @(negedge clk);sv=0;mr=0;
    #1;old_valid=mv;old_data=md;sv=1;sd=35'h2BCDE1234;
    #1;sv=0;sd=0;
    #1;if(mv!==old_valid || md!==old_data) $fatal(1,"Async response propagated through full slice");
    apply_reset(3);traffic(1200);
    // Reset with a full/backpressured pipeline, then retry fresh traffic.
    @(negedge clk);sv=1;sd=35'h123456789;mr=0;av=1;br=0;
    repeat(5) @(negedge clk);
    apply_reset(4);traffic(1200);
    if(received<1000 || ar_received<1000 || resets!=3) $fatal(1,"Insufficient exercised traffic");
    $display("PASS MM2S_RESPONSE_SLICE received=%0d addresses=%0d resets=%0d",received,ar_received,resets);
    $finish;
  end
  initial begin #2000000;$fatal(1,"Timeout");end
endmodule
