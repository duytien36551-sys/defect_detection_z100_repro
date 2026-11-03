`default_nettype none
// timing_v13c collector: same transaction behaviour as z100_maxpool_collect32
// for well-formed streams; only cycle timing differs.
// Structural rules (from the latent-path census):
//  * the 20x256 matrix has no reset and its CE is a registered per-group
//    strobe (wen_q, replicated by MAX_FANOUT) - no control cone reaches it;
//  * the write data is a free-running register (no CE) of the pool's held
//    result_data, written one cycle after the accept;
//  * cfg verdict, expected token and expected lane count are registered;
//    validity checks only drive narrow control FFs;
//  * out_valid is a pure state decode (the downstream packer resets on the
//    same cancel edge, so dropping enable from out_valid is safe).
// Cost: +1 cycle at cfg (CHECK), +1 cycle before output (FLUSH) per block.
(* use_dsp="no" *)
module z100_maxpool_collect32_v13c (
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
    localparam S_IDLE=3'd0,S_CHECK=3'd1,S_IN=3'd2,S_FLUSH=3'd3,S_OUT=3'd4;
    reg [2:0] state;
    reg [31:0] epoch_q,input_token_q,output_token_q,expect_token_q;
    reg [5:0] lanes_q;
    reg [3:0] group_q;
    reg [6:0] remaining_q,required_lanes_q;
    reg last_group_q,last_site_q;
    reg [4:0] site_q;
    reg [31:0] lane_mask_q;
    (* max_fanout = 40 *) reg [7:0] wen_q;
    reg [3:0] wgroup_q;
    reg [639:0] data_q;
    reg [255:0] matrix[0:19];
    integer s,c,lane;
    wire enable=rst_n&&!cancel;
    assign active=state!=S_IDLE;
    assign cfg_ready=enable&&state==S_IDLE;
    assign in_ready=enable&&state==S_IN;
    assign out_valid=state==S_OUT;
    assign out_epoch=epoch_q;
    assign out_token=output_token_q;
    assign out_lanes=lanes_q;
    assign out_site=site_q;
    assign out_last=last_site_q;
    // Verdict evaluated in CHECK from registered copies only.
    wire [32:0] last_input_token={1'b0,input_token_q}+(({27'b0,lanes_q}+3)>>2)-1;
    wire config_good=epoch_q!=0&&input_token_q!=0&&output_token_q!=0&&
        lanes_q!=0&&lanes_q<=32&&!last_input_token[32];
    wire in_fire=in_valid&&in_ready;
    wire input_good=in_epoch==epoch_q&&in_token==expect_token_q&&in_lanes==required_lanes_q;
    wire [6:0] remaining_next=remaining_q-7'd4;
    function [6:0] lanes_for(input [6:0] rem);
        lanes_for=(rem>=7'd4 ? 3'd4 : rem[2:0])*7'd20;
    endfunction
    always @* begin
        out_data=0;
        for(lane=0;lane<32;lane=lane+1)
            if(lane_mask_q[lane]) out_data[lane*8+:8]=matrix[site_q][lane*8+:8];
    end
    // Payload path: no reset, no control cone.
    always @(posedge clk) begin
        data_q<=in_data;
        for(integer g=0;g<8;g=g+1)
            if(wen_q[g])
                for(s=0;s<20;s=s+1)
                    for(c=0;c<4;c=c+1)
                        matrix[s][(g*4+c)*8+:8]<=data_q[(c*20+s)*8+:8];
    end
    always @(posedge clk) begin
        wen_q<=0;
        if(in_fire&&input_good) wen_q[group_q[2:0]]<=1'b1;
    end
    always @(posedge clk) begin
        if(!rst_n||cancel)begin
            state<=S_IDLE;epoch_q<=0;input_token_q<=0;output_token_q<=0;expect_token_q<=0;
            lanes_q<=0;group_q<=0;remaining_q<=0;required_lanes_q<=0;last_group_q<=0;
            site_q<=0;last_site_q<=0;lane_mask_q<=0;done<=0;error_valid<=0;
        end else begin
            done<=0;error_valid<=0;
            case(state)
                S_IDLE:if(cfg_valid&&cfg_ready)begin
                    state<=S_CHECK;epoch_q<=cfg_epoch;input_token_q<=cfg_input_token_base;
                    output_token_q<=cfg_output_token;lanes_q<=cfg_lanes;
                end
                S_CHECK:if(!config_good)begin state<=S_IDLE;error_valid<=1;end
                else begin
                    state<=S_IN;group_q<=0;site_q<=0;last_site_q<=0;
                    expect_token_q<=input_token_q;remaining_q<={1'b0,lanes_q};
                    required_lanes_q<=lanes_for({1'b0,lanes_q});last_group_q<=lanes_q<=6'd4;
                    for(lane=0;lane<32;lane=lane+1) lane_mask_q[lane]<=lane<lanes_q;
                end
                S_IN:if(in_fire)begin
                    if(!input_good)begin state<=S_IDLE;error_valid<=1;end
                    else if(last_group_q) state<=S_FLUSH;
                    else begin
                        group_q<=group_q+1'b1;expect_token_q<=expect_token_q+1;
                        remaining_q<=remaining_next;required_lanes_q<=lanes_for(remaining_next);
                        last_group_q<=remaining_next<=7'd4;
                    end
                end
                S_FLUSH:begin state<=S_OUT;site_q<=0;last_site_q<=0;end
                S_OUT:if(out_ready)begin
                    if(last_site_q)begin state<=S_IDLE;site_q<=0;last_site_q<=0;done<=1;end
                    else begin site_q<=site_q+1'b1;last_site_q<=site_q==5'd18;end
                end
                default:begin state<=S_IDLE;error_valid<=1;end
            endcase
        end
    end
endmodule
`default_nettype wire
