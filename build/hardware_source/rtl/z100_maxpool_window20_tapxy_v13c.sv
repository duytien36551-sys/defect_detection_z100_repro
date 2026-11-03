`default_nettype none
// timing_v13c SPPF MaxPool controller. Same external transactions as
// z100_maxpool_window20_tapxy_v3; cycle timing differs.
// Structural changes (latent-path census, pool_consumer was the #1 block):
//  * all per-block / per-subgroup geometry (block lanes, subgroup channels,
//    expected pool lanes, channel mask, tokens, last-row/last-subgroup) is
//    kept in incrementally-updated registers - no channels_q -> subtract ->
//    min -> multiply cone reaches any child;
//  * the window request leaves through a register slice, so the address
//    adder no longer chains into feature_window's q*_addresses;
//  * children use the _v13c collector/vector (registered CE strobes, no
//    reset on payload).
(* use_dsp="no" *)
module z100_maxpool_window20_tapxy_v13c (
    input wire clk,rst_n,cancel,
    input wire store_valid,loading,input wire [31:0] active_epoch,
    input wire [10:0] loaded_channels,input wire [9:0] loaded_height,loaded_width,
    input wire fw_error,
    output wire window_valid,input wire window_ready,
    output wire [31:0] window_epoch,window_request_tag,
    output wire [13:0] window_row_address,
    output wire signed [11:0] window_first_x,
    output wire [3:0] window_channel_mask,output wire window_y_valid,window_cancel,
    input wire window_out_valid,output wire window_out_ready,
    input wire [31:0] window_tag,input wire [79:0] window_mask,input wire [639:0] window_data,
    input wire job_valid,output wire job_ready,
    input wire [31:0] job_epoch,
    input wire [10:0] job_channels,input wire [9:0] job_height,job_width,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,output wire [12:0] out_address,
    output wire [511:0] out_data,output wire out_last,
    output reg done,output reg error_valid,output reg [3:0] error_code,
    output wire active
);
    localparam IDLE=0,PACK_CFG=1,COLLECT_CFG=2,ISSUE=3,WAIT_VECTOR=4,
               WAIT_COLLECT=5,DRAIN=6,FAULT=7;
    reg [2:0] state;
    reg fault_q;
    reg [31:0] epoch_q;
    reg [10:0] channels_q,lanes_left_q;
    reg [9:0] height_q,row_q;
    reg [6:0] sub_rem_q,pool_lanes_q;
    reg [3:0] mask_q;
    reg last_sub_q,last_row_q,last_block_q;
    reg [31:0] in_tok_q,blk_tok1_q,out_tok_q;
    reg [5:0] block_lanes_q;
    reg [4:0] tap_q;
    reg [2:0] tap_x_q,tap_y_q;
    reg [13:0] block_row_base_q,group_row_base_q;
    wire enable=rst_n&&!cancel;
    assign active=state!=IDLE;
    wire local_cancel=cancel||fault_q;
    wire pool_valid,pool_ready,pool_error;
    wire [31:0] pool_epoch,pool_token;
    wire [6:0] pool_lanes;
    wire [639:0] pool_data;
    wire collect_ready,collect_error,collect_done,collect_active;
    wire post_valid,post_ready,post_last;
    wire [31:0] post_epoch,post_token;
    wire [4:0] post_site;
    wire [5:0] post_lanes;
    wire [255:0] post_data;
    wire pack_ready,pack_error,pack_done,pack_active,pack_valid;
    wire [2:0] pack_error_code;
    wire child_failure=fw_error||pool_error||collect_error||pack_error;
    // Shallow helpers on registered state only.
    function [5:0] min32(input [10:0] v); min32=v>=11'd32 ? 6'd32 : v[5:0]; endfunction
    function [2:0] min4(input [6:0] v); min4=v>=7'd4 ? 3'd4 : v[2:0]; endfunction
    function [3:0] mask_of(input [2:0] n); mask_of=4'hf>>(3'd4-n); endfunction
    wire [6:0] sub_rem_next=sub_rem_q-7'd4;
    wire [10:0] lanes_left_next=lanes_left_q-11'd32;
    // Request generator -> register slice -> feature_window.
    wire [2:0] tap_x=tap_x_q,tap_y=tap_y_q;
    wire signed [11:0] first_x=$signed({9'd0,tap_x})-12'sd2;
    wire signed [11:0] source_y=$signed({2'd0,row_q})+$signed({9'd0,tap_y})-12'sd2;
    wire y_valid=source_y>=0&&source_y<$signed({2'd0,height_q});
    wire [13:0] valid_y_offset=y_valid ? {1'b0,source_y[11:0],1'b0} : 14'd0;
    wire [13:0] row_address=group_row_base_q+valid_y_offset;
    wire req_valid=state==ISSUE;
    wire req_ready;
    wire req_fire=req_valid&&req_ready;
    localparam integer RW=32+5+14+12+4+1;
    wire [RW-1:0] req_out;
    z100_skid_v13c #(.W(RW)) request_slice(.clk(clk),.rst_n(rst_n),.flush(local_cancel),
        .in_valid(req_valid),.in_ready(req_ready),.in_data({epoch_q,tap_q,row_address,first_x,mask_q,y_valid}),
        .out_valid(window_valid),.out_ready(window_ready),.out_data(req_out));
    assign window_epoch=req_out[RW-1-:32];
    assign window_request_tag={27'd0,req_out[RW-33-:5]};
    assign window_row_address=req_out[RW-38-:14];
    assign window_first_x=req_out[RW-52-:12];
    assign window_channel_mask=req_out[4:1];
    assign window_y_valid=req_out[0];
    assign window_cancel=local_cancel;
    wire job_good=job_epoch!=0&&job_epoch==active_epoch&&job_channels!=0&&
        job_channels<=128&&job_height!=0&&job_height<=20&&job_width==20&&
        job_channels==loaded_channels&&job_height==loaded_height&&job_width==loaded_width;
    assign job_ready=enable&&state==IDLE&&store_valid&&!loading&&pack_ready&&!child_failure;
    assign out_valid=enable&&active&&!fault_q&&pack_valid&&!child_failure;

    z100_maxpool_vector_v13c pool(
        .clk(clk),.rst_n(rst_n),.cancel(local_cancel),.in_valid(window_out_valid),.in_ready(window_out_ready),
        .in_epoch(epoch_q),.in_token(in_tok_q),.in_lanes(pool_lanes_q),
        .in_first(window_tag==0),.in_last(window_tag==24),.in_mask(window_mask),.in_data(window_data),
        .out_valid(pool_valid),.out_ready(pool_ready),.out_epoch(pool_epoch),.out_token(pool_token),
        .out_lanes(pool_lanes),.out_data(pool_data),.error_valid(pool_error),.active());
    z100_maxpool_collect32_v13c collector(
        .clk(clk),.rst_n(rst_n),.cancel(local_cancel),.cfg_valid(state==COLLECT_CFG),.cfg_ready(collect_ready),
        .cfg_epoch(epoch_q),.cfg_input_token_base(blk_tok1_q),.cfg_output_token(out_tok_q),.cfg_lanes(block_lanes_q),
        .in_valid(pool_valid),.in_ready(pool_ready),.in_epoch(pool_epoch),.in_token(pool_token),
        .in_lanes(pool_lanes),.in_data(pool_data),.out_valid(post_valid),.out_ready(post_ready),
        .out_epoch(post_epoch),.out_token(post_token),.out_site(post_site),.out_lanes(post_lanes),
        .out_last(post_last),.out_data(post_data),.done(collect_done),.error_valid(collect_error),.active(collect_active));
    z100_native_output_packer_v13 #(.SITES(20)) packer(
        .clk(clk),.rst_n(rst_n),.cancel(local_cancel),.cfg_valid(state==PACK_CFG),.cfg_ready(pack_ready),
        .cfg_epoch(epoch_q),.cfg_channels(channels_q),.cfg_height(height_q),.cfg_width(10'd20),.cfg_token_base(32'd1),
        .in_valid(post_valid),.in_ready(post_ready),.in_epoch(post_epoch),.in_token(post_token),
        .in_site(post_site),.in_lanes(post_lanes),.in_last(post_last),.in_data(post_data),
        .out_valid(pack_valid),.out_ready(out_ready&&!fault_q&&!child_failure),
        .out_epoch(out_epoch),.out_address(out_address),.out_data(out_data),.out_last(out_last),
        .done(pack_done),.error_valid(pack_error),.error_code(pack_error_code),.active(pack_active));
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            state<=IDLE;fault_q<=0;done<=0;error_valid<=0;error_code<=0;
            epoch_q<=0;channels_q<=0;lanes_left_q<=0;block_lanes_q<=0;height_q<=0;row_q<=0;
            sub_rem_q<=0;pool_lanes_q<=0;mask_q<=0;last_sub_q<=0;last_row_q<=0;
            in_tok_q<=0;blk_tok1_q<=0;out_tok_q<=0;
            tap_q<=0;tap_x_q<=0;tap_y_q<=0;block_row_base_q<=0;group_row_base_q<=0;
        end else begin
            done<=0;error_valid<=0;error_code<=0;
            if(child_failure)begin
                error_valid<=1;error_code<=fw_error ? 4'd2 : pool_error ? 4'd3 : collect_error ? 4'd4 : 4'd5;
                state<=FAULT;fault_q<=1;
            end else case(state)
                IDLE:if(job_valid&&job_ready)begin
                    if(!job_good)begin error_valid<=1;error_code<=1;end
                    else begin
                        state<=PACK_CFG;epoch_q<=job_epoch;channels_q<=job_channels;height_q<=job_height;
                        lanes_left_q<=job_channels;block_lanes_q<=min32(job_channels);
                        row_q<=0;last_row_q<=job_height==10'd1;
                        blk_tok1_q<=1;out_tok_q<=1;
                        tap_q<=0;tap_x_q<=0;tap_y_q<=0;block_row_base_q<=0;group_row_base_q<=0;
                    end
                end
                PACK_CFG:if(pack_ready)state<=COLLECT_CFG;
                COLLECT_CFG:if(collect_ready)begin
                    state<=ISSUE;tap_q<=0;tap_x_q<=0;tap_y_q<=0;group_row_base_q<=block_row_base_q;
                    sub_rem_q<={1'b0,block_lanes_q};
                    pool_lanes_q<=min4({1'b0,block_lanes_q})*7'd20;
                    mask_q<=mask_of(min4({1'b0,block_lanes_q}));
                    last_sub_q<=block_lanes_q<=6'd4;
                    in_tok_q<=blk_tok1_q;
                end
                ISSUE:if(req_fire)begin
                    if(tap_q==24)state<=WAIT_VECTOR;
                    else begin
                        tap_q<=tap_q+1'b1;
                        if(tap_x_q==4)begin tap_x_q<=0;tap_y_q<=tap_y_q+1'b1;end
                        else tap_x_q<=tap_x_q+1'b1;
                    end
                end
                WAIT_VECTOR:if(pool_valid&&pool_ready)begin
                    if(last_sub_q)state<=WAIT_COLLECT;
                    else begin
                        sub_rem_q<=sub_rem_next;pool_lanes_q<=min4(sub_rem_next)*7'd20;
                        mask_q<=mask_of(min4(sub_rem_next));last_sub_q<=sub_rem_next<=7'd4;
                        in_tok_q<=in_tok_q+1;
                        tap_q<=0;tap_x_q<=0;tap_y_q<=0;group_row_base_q<=group_row_base_q+{3'd0,height_q,1'b0};state<=ISSUE;
                    end
                end
                WAIT_COLLECT:if(collect_done)begin
                    if(last_row_q&&lanes_left_q<=11'd32)state<=DRAIN;
                    else begin
                        blk_tok1_q<=blk_tok1_q+32'd8;out_tok_q<=out_tok_q+1;
                        if(last_row_q)begin
                            row_q<=0;last_row_q<=height_q==10'd1;
                            lanes_left_q<=lanes_left_next;block_lanes_q<=min32(lanes_left_next);
                            block_row_base_q<=block_row_base_q+{height_q,4'd0};
                        end else begin
                            row_q<=row_q+1;last_row_q<=row_q+10'd2==height_q;
                        end
                        state<=COLLECT_CFG;
                    end
                end
                DRAIN:if(pack_done)begin state<=IDLE;done<=1;end
                FAULT:state<=FAULT;
                default:begin state<=FAULT;fault_q<=1;error_valid<=1;error_code<=6;end
            endcase
        end
    end
endmodule
`default_nettype wire
