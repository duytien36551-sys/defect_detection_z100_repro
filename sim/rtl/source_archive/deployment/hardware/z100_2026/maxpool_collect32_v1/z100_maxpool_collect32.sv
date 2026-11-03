`default_nettype none
// Private width20 bridge: eight channel4/site20 vectors -> twenty native32
// site beats. Payload is never reset; inactive tail channels are masked out.
(* use_dsp="no" *)
module z100_maxpool_collect32 (
    input wire clk,input wire rst_n,input wire cancel,
    input wire cfg_valid,output wire cfg_ready,
    input wire [31:0] cfg_epoch,input wire [31:0] cfg_input_token_base,
    input wire [31:0] cfg_output_token,input wire [5:0] cfg_lanes,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,input wire [31:0] in_token,
    input wire [6:0] in_lanes,input wire [639:0] in_data,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,output wire [31:0] out_token,
    output wire [4:0] out_site,output wire [5:0] out_lanes,
    output wire out_last,output reg [255:0] out_data,
    output reg done,output reg error_valid,output wire active
);
    reg [1:0] state;
    reg [31:0] epoch_q,input_token_q,output_token_q;
    reg [5:0] lanes_q;
    reg [3:0] groups_q,group_q;
    reg [4:0] site_q;
    reg [255:0] matrix[0:19];
    integer s,c;
    wire enable=rst_n&&!cancel;
    assign active=state!=0;
    assign cfg_ready=enable&&state==0;
    assign in_ready=enable&&state==1;
    assign out_valid=enable&&state==2;
    assign out_epoch=epoch_q;
    assign out_token=output_token_q;
    assign out_lanes=lanes_q;
    assign out_site=site_q;
    assign out_last=site_q==19;
    wire [6:0] remaining={1'b0,lanes_q}-({3'b0,group_q}<<2);
    wire [2:0] channels_this_group=remaining>=4 ? 3'd4 : remaining[2:0];
    wire [6:0] required_lanes=channels_this_group*7'd20;
    wire [32:0] last_input_token={1'b0,cfg_input_token_base}+(({27'b0,cfg_lanes}+3)>>2)-1;
    wire config_good=cfg_epoch!=0&&cfg_input_token_base!=0&&cfg_output_token!=0&&
        cfg_lanes!=0&&cfg_lanes<=32&&!last_input_token[32];
    wire input_good=in_epoch==epoch_q&&in_token==input_token_q+group_q&&in_lanes==required_lanes;
    always @* begin
        out_data=0;
        for(integer lane=0;lane<32;lane=lane+1)
            if(lane<lanes_q) out_data[lane*8+:8]=matrix[site_q][lane*8+:8];
    end
    always @(posedge clk) begin
        if(!rst_n||cancel)begin
            state<=0;epoch_q<=0;input_token_q<=0;output_token_q<=0;
            lanes_q<=0;groups_q<=0;group_q<=0;site_q<=0;done<=0;error_valid<=0;
        end else begin
            done<=0;error_valid<=0;
            if(cfg_valid&&cfg_ready)begin
                if(!config_good)begin state<=0;error_valid<=1;end
                else begin
                    state<=1;epoch_q<=cfg_epoch;input_token_q<=cfg_input_token_base;
                    output_token_q<=cfg_output_token;lanes_q<=cfg_lanes;
                    groups_q<=({1'b0,cfg_lanes}+7'd3)>>2;group_q<=0;site_q<=0;
                end
            end else if(in_valid&&in_ready)begin
                if(!input_good)begin state<=0;error_valid<=1;end
                else begin
                    for(s=0;s<20;s=s+1)
                        for(c=0;c<4;c=c+1)
                            if(c<channels_this_group)
                                matrix[s][(group_q*4+c)*8+:8]<=in_data[(c*20+s)*8+:8];
                    if(group_q+1==groups_q)begin state<=2;site_q<=0;end
                    else group_q<=group_q+1;
                end
            end else if(out_valid&&out_ready)begin
                if(site_q==19)begin state<=0;site_q<=0;done<=1;end
                else site_q<=site_q+1;
            end
        end
    end
endmodule
`default_nettype wire
