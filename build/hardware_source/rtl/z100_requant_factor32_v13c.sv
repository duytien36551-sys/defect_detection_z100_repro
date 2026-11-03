`default_nettype none
// timing_v13c 32-lane exact-factor requant. Same config ABI and same output
// transactions as z100_requant_factor32 for well-formed streams.
// Structural changes (raw_buffer -> requant was the #3 block in the census):
//  * no global stall: the 32x3 DSPs and all pipeline FFs run with CE=1;
//  * input slice s0 (free-running payload) - DSP A/B come from local FFs;
//  * a 16-deep LUTRAM output FIFO absorbs back-pressure; in_ready depends
//    only on a registered credit flag (outstanding <= 15), not on any lane;
//  * bad epoch/token/site is detected on the registered s0 beat (one cycle
//    later than the original, the bad beat is consumed instead of refused);
//    effect is identical: input_error pulse, pipeline flushed, fault until
//    the next cfg_begin.
// Latency 9 cycles (was 5): s0, DSP P, cross, partial, product, |p|, round, result(v7), FIFO; throughput 1 beat/cycle.
(* use_dsp="no" *)
module z100_requant_factor32_v13c (
    input wire clk,rst_n,cancel,
    input wire cfg_begin,output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,input wire [5:0] cfg_lanes,
    input wire cfg_word_valid,output wire cfg_word_ready,
    input wire [30:0] cfg_multiplier,input wire [5:0] cfg_shift,
    input wire cfg_commit,output wire cfg_commit_ready,
    output reg cfg_error,output reg input_error,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,in_token,input wire [4:0] in_site,input wire in_last,
    input wire [1023:0] in_data,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,out_token,
    output wire [4:0] out_site,output wire [5:0] out_lanes,
    output wire out_last,output wire [255:0] out_data
);
    localparam integer CAP=16, MW=70;
    reg loading,loaded,fault_q;
    reg [31:0] epoch;
    reg [5:0] lanes,cfg_count;
    reg [31:0] lane_mask_q;
    reg [30:0] multipliers[0:31];reg [5:0] shifts[0:31];
    reg [62:0] frac_mask[0:31],half_bit[0:31]; // derived from shifts at cfg time
    reg [4:0] outstanding;
    reg room_q;
    reg [4:0] count;
    reg [3:0] wp,rp;
    reg [7:1] v;
    reg [MW-1:0] meta[1:7];
    reg s0_valid;
    reg [MW-1:0] s0_meta;
    reg [1023:0] s0_data;
    (* ram_style="distributed" *) reg [MW+256-1:0] fifo[0:CAP-1];
    wire control_busy=cfg_begin||cfg_word_valid||cfg_commit;
    wire enable=rst_n&&!cancel;
    wire empty=outstanding==0;
    wire enabled=loaded&&!loading&&!control_busy&&enable&&!fault_q;
    assign cfg_begin_ready=enable&&empty&&!loading&&!cfg_word_valid&&!cfg_commit;
    assign cfg_word_ready=enable&&empty&&loading&&!cfg_begin&&!cfg_commit;
    assign cfg_commit_ready=enable&&empty&&loading&&!cfg_begin&&!cfg_word_valid;
    assign in_ready=enabled&&room_q;
    wire fire=in_valid&&in_ready;
    wire [31:0] s0_epoch=s0_meta[69:38];
    wire [31:0] s0_token=s0_meta[37:6];
    wire [4:0] s0_site=s0_meta[5:1];
    wire bad_s0=s0_valid&&(s0_epoch!=epoch||s0_token==0||s0_site>=20);
    wire [MW+256-1:0] head=fifo[rp];
    assign out_valid=enable&&count!=0&&!fault_q;
    wire pop=out_valid&&out_ready;
    assign {out_epoch,out_token,out_site,out_last}=head[MW+256-1:256];
    assign out_data=head[255:0];
    assign out_lanes=lanes;
    wire [4:0] outstanding_next=outstanding+fire-pop;


    wire [255:0] lane_result;
    genvar lane;
    generate for(lane=0;lane<32;lane=lane+1)begin:gen_lane
        wire signed [31:0] in_value=s0_data[lane*32+:32];
        wire [30:0] in_multiplier=multipliers[lane];
        wire signed [17:0] a_sum=$signed({2'b0,in_value[15:0]})+$signed({{2{in_value[31]}},in_value[31:16]});
        wire signed [17:0] b_sum=$signed({2'b0,in_multiplier[15:0]})+$signed({3'b0,in_multiplier[30:16]});
        wire signed [24:0] a_low=$signed({9'd0,in_value[15:0]});
        wire signed [24:0] a_high=$signed({{9{in_value[31]}},in_value[31:16]});
        wire signed [24:0] a_both=$signed({{7{a_sum[17]}},a_sum});
        wire signed [17:0] b_low=$signed({2'b0,in_multiplier[15:0]});
        wire signed [17:0] b_high=$signed({3'b0,in_multiplier[30:16]});
        wire signed [42:0] low_product,high_product,sum_product;
        MULT_MACRO #(.DEVICE("7SERIES"),.LATENCY(1),.STYLE("DSP"),.WIDTH_A(25),.WIDTH_B(18)) p_low(
            .P(low_product),.A(a_low),.B(b_low),.CE(1'b1),.CLK(clk),.RST(1'b0));
        MULT_MACRO #(.DEVICE("7SERIES"),.LATENCY(1),.STYLE("DSP"),.WIDTH_A(25),.WIDTH_B(18)) p_high(
            .P(high_product),.A(a_high),.B(b_high),.CE(1'b1),.CLK(clk),.RST(1'b0));
        MULT_MACRO #(.DEVICE("7SERIES"),.LATENCY(1),.STYLE("DSP"),.WIDTH_A(25),.WIDTH_B(18)) p_sum(
            .P(sum_product),.A(a_both),.B(b_sum),.CE(1'b1),.CLK(clk),.RST(1'b0));
        reg signed [42:0] cross_q,low_q,high_q,high_delay_q;
        reg signed [62:0] partial_q,product_q;
        reg signed [7:0] result_q;
        // Rounding split in three registered steps (was one 38-level cone):
        //  A: |product| and sign;  B: whole=mag>>shift, saturation flag and
        //  round-up decision (masks precomputed per lane);  C: add + saturate.
        reg [62:0] mag_q; reg neg_a,neg_b;
        reg [6:0] whole_q; reg big_q,up_q;
        wire [5:0] sh=shifts[lane];
        wire [62:0] fm=frac_mask[lane];
        wire [62:0] whole_full=mag_q>>sh;
        wire [62:0] frac=mag_q&fm;
        wire [62:0] half=half_bit[lane];
        wire up=sh!=0&&((frac>half)||((frac==half)&&whole_full[0]));
        wire [7:0] answer={1'b0,whole_q}+up_q;
        wire [62:0] product_neg=~product_q+63'd1;
        wire [62:0] product_abs=product_q[62] ? product_neg : product_q;
        // Free-running, no reset/CE. shifts[] is static while outstanding!=0.
        always @(posedge clk)begin
            cross_q<=sum_product-low_product-high_product;
            low_q<=low_product;high_q<=high_product;
            partial_q<=$signed({{20{low_q[42]}},low_q})+($signed({{20{cross_q[42]}},cross_q})<<<16);
            high_delay_q<=high_q;
            product_q<=partial_q+($signed({{20{high_delay_q[42]}},high_delay_q})<<<32);
            mag_q<=product_abs;
            neg_a<=product_q[62];
            whole_q<=whole_full[6:0]; big_q<=|whole_full[62:7]; up_q<=up; neg_b<=neg_a;
            if(big_q||answer>=8'd127) result_q<=neg_b ? -8'sd127 : 8'sd127;
            else result_q<=neg_b ? -$signed({1'b0,answer[6:0]}) : $signed({1'b0,answer[6:0]});
        end
        assign lane_result[lane*8+:8]=lane_mask_q[lane] ? result_q : 8'd0;
    end endgenerate
    // Payload paths: no reset, no CE cone.
    integer i;
    always @(posedge clk)begin
        s0_data<=in_data;
        s0_meta<={in_epoch,in_token,in_site,in_last};
        meta[1]<=s0_meta;
        for(i=2;i<=7;i=i+1)meta[i]<=meta[i-1];
        if(v[7])fifo[wp]<={meta[7],lane_result};
    end
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            loading<=0;loaded<=0;fault_q<=0;epoch<=0;lanes<=0;cfg_count<=0;lane_mask_q<=0;
            cfg_error<=0;input_error<=0;s0_valid<=0;v<=0;
            outstanding<=0;room_q<=0;count<=0;wp<=0;rp<=0;
        end else begin
            cfg_error<=0;input_error<=0;
            if(cfg_begin&&cfg_begin_ready)begin
                loaded<=0;fault_q<=0;cfg_count<=0;
                if(cfg_epoch==0||cfg_lanes==0||cfg_lanes>32)begin loading<=0;cfg_error<=1;end
                else begin
                    loading<=1;epoch<=cfg_epoch;lanes<=cfg_lanes;
                    for(i=0;i<32;i=i+1)lane_mask_q[i]<=i<cfg_lanes;
                end
            end else if(cfg_word_valid&&cfg_word_ready)begin
                if(cfg_count>=lanes||cfg_multiplier==0)begin
                    loading<=0;loaded<=0;cfg_count<=0;cfg_error<=1;
                end else begin
                    multipliers[cfg_count]<=cfg_multiplier;shifts[cfg_count]<=cfg_shift;cfg_count<=cfg_count+1;
                    frac_mask[cfg_count]<=(63'd1<<cfg_shift)-63'd1;
                    half_bit[cfg_count]<=cfg_shift==0 ? 63'd0 : (63'd1<<(cfg_shift-6'd1));
                end
            end else if(cfg_commit&&cfg_commit_ready)begin
                loading<=0;
                if(cfg_count==lanes)loaded<=1;
                else begin loaded<=0;cfg_error<=1;end
            end
            if(bad_s0)begin
                loaded<=0;loading<=0;input_error<=1;fault_q<=1;
                s0_valid<=0;v<=0;outstanding<=0;room_q<=0;count<=0;wp<=0;rp<=0;
            end else begin
                s0_valid<=fire;
                v<={v[6:1],s0_valid};
                outstanding<=outstanding_next;
                room_q<=outstanding_next<CAP;
                if(v[7])wp<=wp+1'b1;
                if(pop)rp<=rp+1'b1;
                count<=count+v[7]-pop;
            end
        end
    end
endmodule
`default_nettype wire
