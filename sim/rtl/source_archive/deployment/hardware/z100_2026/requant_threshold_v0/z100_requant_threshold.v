// Private exact threshold lookup. One lane, synchronous table RAM, <=16 search clocks.
// Config loads254 ordered signed33 thresholds; +2^31 is a never-crossed sentinel.
module z100_requant_threshold(
 input wire clk,input wire rst_n,input wire cancel,
 input wire cfg_begin,input wire cfg_valid,output wire cfg_ready,
 input wire [7:0] cfg_address,input wire signed [32:0] cfg_threshold,
 input wire in_valid,output wire in_ready,input wire signed [31:0] in_data,
 output wire out_valid,input wire out_ready,output reg signed [7:0] out_data,
 output reg error
);
 localparam IDLE=0,READ=1,COMPARE=2;
 reg [1:0] state;
 (* ram_style="block" *) reg signed [32:0] table_mem[0:255];
 reg signed [32:0] threshold_q,previous;
 reg signed [31:0] raw;
 reg [8:0] lo,hi,count;
 wire [8:0] midpoint=(lo+hi)>>1;
 wire crosses=$signed({raw[31],raw}) >= $signed(threshold_q);
 wire [8:0] next_lo=crosses?midpoint+9'd1:lo;
 wire [8:0] next_hi=crosses?hi:midpoint;
 reg loaded,full;
 assign cfg_ready=(state==IDLE)&&!full&&rst_n&&!cancel;
 assign in_ready=(state==IDLE)&&!full&&loaded&&!cfg_valid&&!cfg_begin&&rst_n&&!cancel;
 assign out_valid=full&&rst_n&&!cancel;
 always @(posedge clk)begin
  if(!rst_n||cancel)begin
   state<=IDLE;loaded<=0;full<=0;count<=0;error<=0;out_data<=0;
   lo<=0;hi<=254;raw<=0;previous<=-33'sd2147483648;
  end else begin
   error<=0;
   if(full&&out_ready)full<=0;
   if(cfg_begin&&cfg_ready)begin
    loaded<=0;count<=0;previous<=-33'sd2147483648;
    if(cfg_valid)error<=1;
   end else if(cfg_valid&&cfg_ready)begin
    if(count>=254||cfg_address!=count||cfg_threshold< -33'sd2147483648||
       cfg_threshold>33'sd2147483648||(count!=0&&cfg_threshold<previous))begin
     loaded<=0;count<=0;error<=1;
    end else begin
     table_mem[cfg_address]<=cfg_threshold;previous<=cfg_threshold;count<=count+1;
     if(count==253)loaded<=1;
    end
   end
   if(in_valid&&in_ready)begin raw<=in_data;lo<=0;hi<=254;state<=READ;end
   if(state==READ)begin threshold_q<=table_mem[midpoint[7:0]];state<=COMPARE;end
   if(state==COMPARE)begin
    lo<=next_lo;hi<=next_hi;
    if(next_lo==next_hi)begin out_data<=$signed({1'b0,next_lo})-10'sd127;full<=1;state<=IDLE;end
    else state<=READ;
   end
  end
 end
endmodule
