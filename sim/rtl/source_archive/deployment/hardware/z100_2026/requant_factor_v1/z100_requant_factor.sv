`default_nettype none
// Exact signed32 * unsigned31 via three DSP48E1 products (Karatsuba).
// Fixed five-stage latency when advancing; global stall holds every stage.
// Factors are accepted only after host proof of all254 output transitions.
(* use_dsp="no" *)
module z100_requant_factor (
    input wire clk,rst_n,cancel,
    input wire in_valid,output wire in_ready,
    input wire signed [31:0] in_value,
    input wire [30:0] in_multiplier,input wire [5:0] in_shift,
    input wire [31:0] in_token,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_token,output wire signed [7:0] out_data,
    output wire signed [62:0] out_product,
    output reg error_valid
);
    reg [4:0] valid_q;
    reg [31:0] token_q[0:4];
    reg [5:0] shift_q[0:3];
    reg signed [42:0] cross_q,low_q,high_q,high_delay_q;
    reg signed [62:0] partial_q,product_q,debug_product_q;
    reg signed [7:0] result_q;
    wire enable=rst_n&&!cancel;
    wire advance=!valid_q[4]||out_ready;
    assign in_ready=enable&&advance;
    assign out_valid=enable&&valid_q[4];
    assign out_data=result_q;
    assign out_product=debug_product_q;
    assign out_token=token_q[4];
    wire signed [17:0] a_sum=$signed({2'b0,in_value[15:0]})+
                                      $signed({{2{in_value[31]}},in_value[31:16]});
    wire signed [17:0] b_sum=$signed({2'b0,in_multiplier[15:0]})+
                                      $signed({3'b0,in_multiplier[30:16]});
    wire signed [24:0] a_low=$signed({9'd0,in_value[15:0]});
    wire signed [24:0] a_high=$signed({{9{in_value[31]}},in_value[31:16]});
    wire signed [24:0] a_both=$signed({{7{a_sum[17]}},a_sum});
    wire signed [17:0] b_low=$signed({2'b0,in_multiplier[15:0]});
    wire signed [17:0] b_high=$signed({3'b0,in_multiplier[30:16]});
    wire signed [42:0] low_product,high_product,sum_product;
    wire ce=enable&&advance;
    MULT_MACRO #(.DEVICE("7SERIES"),.LATENCY(1),.STYLE("DSP"),.WIDTH_A(25),.WIDTH_B(18)) p_low(
        .P(low_product),.A(a_low),.B(b_low),.CE(ce),.CLK(clk),.RST(1'b0));
    MULT_MACRO #(.DEVICE("7SERIES"),.LATENCY(1),.STYLE("DSP"),.WIDTH_A(25),.WIDTH_B(18)) p_high(
        .P(high_product),.A(a_high),.B(b_high),.CE(ce),.CLK(clk),.RST(1'b0));
    MULT_MACRO #(.DEVICE("7SERIES"),.LATENCY(1),.STYLE("DSP"),.WIDTH_A(25),.WIDTH_B(18)) p_sum(
        .P(sum_product),.A(a_both),.B(b_sum),.CE(ce),.CLK(clk),.RST(1'b0));

    function automatic signed [7:0] rounded(input signed [62:0] value,input [5:0] shift);
        reg [63:0] magnitude,whole,fraction,half,mask,answer;
        begin
            magnitude=value[62] ? $unsigned(-$signed({value[62],value})) : {1'b0,value};
            whole=magnitude>>shift;
            if(shift==0)answer=whole;
            else begin
                mask=(64'd1<<shift)-1;
                fraction=magnitude&mask;
                half=64'd1<<(shift-1);
                answer=whole+((fraction>half)||((fraction==half)&&whole[0]));
            end
            if(answer>=127)rounded=value[62] ? -8'sd127 : 8'sd127;
            else rounded=value[62] ? -$signed({1'b0,answer[6:0]}) : $signed({1'b0,answer[6:0]});
        end
    endfunction
    integer i;
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            valid_q<=0;error_valid<=0;
            for(i=0;i<5;i=i+1)token_q[i]<=0;
            for(i=0;i<4;i=i+1)shift_q[i]<=0;
        end else begin
            error_valid<=0;
            if(advance)begin
                valid_q<={valid_q[3:0],in_valid&&(in_multiplier!=0)};
                token_q[0]<=in_token;shift_q[0]<=in_shift;
                for(i=1;i<5;i=i+1)token_q[i]<=token_q[i-1];
                for(i=1;i<4;i=i+1)shift_q[i]<=shift_q[i-1];
                cross_q<=sum_product-low_product-high_product;
                low_q<=low_product;high_q<=high_product;
                partial_q<=$signed({{20{low_q[42]}},low_q})+
                           ($signed({{20{cross_q[42]}},cross_q})<<<16);
                high_delay_q<=high_q;
                product_q<=partial_q+($signed({{20{high_delay_q[42]}},high_delay_q})<<<32);
                result_q<=rounded(product_q,shift_q[3]);
                debug_product_q<=product_q;
                if(in_valid&&in_multiplier==0)error_valid<=1;
            end
        end
    end
endmodule
`default_nettype wire
