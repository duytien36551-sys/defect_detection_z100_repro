`timescale 1ns/1ps
module tb_mm2s_response_slice;
  reg clk=0, reset=1, sv=0, mr=0, active=0;
  reg [35:0] sd=0;
  wire sr, mv;
  wire [35:0] md;
  reg [35:0] expected[0:8191];
  integer head=0, tail=0, sent=0, received=0, cycle=0, resets=0;
  reg consumed=0, stalled=0;
  reg [35:0] held;
  always #5 clk=~clk;
  // The same supported full R-channel implementation selected by public
  // axi_register_slice IP REG_R=1. Production flow instantiates that public IP.
  axi_register_slice_v2_1_37_axic_register_slice #(
    .C_FAMILY("zynq"), .C_DATA_WIDTH(36), .C_REG_CONFIG(1)
  ) dut(.ACLK(clk),.ARESET(reset),.S_PAYLOAD_DATA(sd),.S_VALID(sv),
        .S_READY(sr),.M_PAYLOAD_DATA(md),.M_VALID(mv),.M_READY(mr));
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
      active=0;sv=0;mr=0;
      @(negedge clk); #(phase); reset=1;
      repeat(6) @(negedge clk);
      head=0;tail=0;
      reset=0;
      repeat(5) @(negedge clk);
      if(mv) $fatal(1,"Stale valid after reset flush");
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
          sd={sent[0],sent[2:0],sent[31:0]};
        end
        mr=((i%11)>3);
      end
      @(negedge clk);mr=1;
      while(sv && !consumed) @(negedge clk);
      sv=0;
      repeat(10) @(negedge clk);
      if(head!=tail) $fatal(1,"Not all accepted responses drained");
    end
  endtask
  reg old_valid;
  reg [35:0] old_data;
  initial begin
    apply_reset(1);traffic(1200);
    // An asynchronous upstream transition must not reach the downstream
    // RAM-control side between clock edges.
    @(negedge clk);sv=0;mr=0;
    #1;old_valid=mv;old_data=md;sv=1;sd=36'hABCDE1234;
    #1;sv=0;sd=0;
    #1;if(mv!==old_valid || md!==old_data) $fatal(1,"Async response propagated through full slice");
    apply_reset(3);traffic(1200);
    // Reset with a full/backpressured pipeline, then retry fresh traffic.
    @(negedge clk);sv=1;sd=36'h123456789;mr=0;
    repeat(5) @(negedge clk);
    apply_reset(4);traffic(1200);
    if(received<1000 || resets!=3) $fatal(1,"Insufficient exercised traffic");
    $display("PASS MM2S_RESPONSE_SLICE received=%0d resets=%0d",received,resets);
    $finish;
  end
  initial begin #2000000;$fatal(1,"Timeout");end
endmodule
