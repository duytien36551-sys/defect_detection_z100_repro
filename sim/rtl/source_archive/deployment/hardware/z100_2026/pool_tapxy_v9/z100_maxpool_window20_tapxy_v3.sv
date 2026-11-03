`default_nettype none
// Private autonomous signed5x5/s1/p2 MaxPool for the actual width20 SPPF.
// External shared FeatureLayout window source; this module owns no feature RAM.
// Scale equality is a host-side model admission condition, not a rescaler.
(* use_dsp="no" *)
module z100_maxpool_window20_tapxy_v3 (
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
    reg [31:0] epoch_q,block_q;
    reg [10:0] channels_q,channel_base_q;
    reg [9:0] height_q,row_q;
    reg [3:0] subgroup_q;
    reg [4:0] tap_q;
    reg [2:0] tap_x_q,tap_y_q;
    reg [13:0] block_row_base_q,group_row_base_q;
    wire enable=rst_n&&!cancel;
    assign active=state!=IDLE;
    wire local_cancel=cancel||(state==FAULT);
    wire pool_valid,pool_ready,pool_error,pool_active;
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
    wire [10:0] lanes_left=channels_q-channel_base_q;
    wire [5:0] block_lanes=lanes_left>=32 ? 6'd32 : lanes_left[5:0];
    wire [6:0] group_count=({1'b0,block_lanes}+7'd3)>>2;
    wire [6:0] subgroup_remaining={1'b0,block_lanes}-({3'b0,subgroup_q}<<2);
    wire [2:0] subgroup_channels=subgroup_remaining>=4 ? 3'd4 : subgroup_remaining[2:0];
    wire [6:0] expected_pool_lanes=subgroup_channels*7'd20;
    wire [3:0] channel_mask=4'hf>>(4-subgroup_channels);
    wire [31:0] input_token=(block_q<<3)+subgroup_q+1;
    wire [31:0] output_token=block_q+1;
    // Coordinate recurrence removes encoded-tap division from the address path.
    wire [2:0] tap_x=tap_x_q,tap_y=tap_y_q;
    wire signed [11:0] first_x=$signed({9'd0,tap_x})-12'sd2;
    wire signed [11:0] source_y=$signed({2'd0,row_q})+$signed({9'd0,tap_y})-12'sd2;
    wire y_valid=source_y>=0&&source_y<$signed({2'd0,height_q});
    wire [13:0] valid_y_offset=y_valid ? {1'b0,source_y[11:0],1'b0} : 14'd0;
    wire [13:0] row_address=group_row_base_q+valid_y_offset;
    wire job_good=job_epoch!=0&&job_epoch==active_epoch&&job_channels!=0&&
        job_channels<=128&&job_height!=0&&job_height<=20&&job_width==20&&
        job_channels==loaded_channels&&job_height==loaded_height&&job_width==loaded_width;
    assign job_ready=enable&&state==IDLE&&store_valid&&!loading&&pack_ready&&!child_failure;
    assign out_valid=enable&&active&&state!=FAULT&&pack_valid&&!child_failure;
    assign window_valid=state==ISSUE;
    assign window_epoch=epoch_q;
    assign window_request_tag={27'd0,tap_q};
    assign window_row_address=row_address[13:0];
    assign window_first_x=first_x;
    assign window_channel_mask=channel_mask;
    assign window_y_valid=y_valid;
    assign window_cancel=local_cancel;

    z100_maxpool_vector pool(
        .clk(clk),.rst_n(rst_n),.cancel(local_cancel),.in_valid(window_out_valid),.in_ready(window_out_ready),
        .in_epoch(epoch_q),.in_token(input_token),.in_lanes(expected_pool_lanes),
        .in_first(window_tag==0),.in_last(window_tag==24),.in_mask(window_mask),.in_data(window_data),
        .out_valid(pool_valid),.out_ready(pool_ready),.out_epoch(pool_epoch),.out_token(pool_token),
        .out_lanes(pool_lanes),.out_data(pool_data),.error_valid(pool_error),.active(pool_active));
    z100_maxpool_collect32 collector(
        .clk(clk),.rst_n(rst_n),.cancel(local_cancel),.cfg_valid(state==COLLECT_CFG),.cfg_ready(collect_ready),
        .cfg_epoch(epoch_q),.cfg_input_token_base((block_q<<3)+1),.cfg_output_token(output_token),.cfg_lanes(block_lanes),
        .in_valid(pool_valid),.in_ready(pool_ready),.in_epoch(pool_epoch),.in_token(pool_token),
        .in_lanes(pool_lanes),.in_data(pool_data),.out_valid(post_valid),.out_ready(post_ready),
        .out_epoch(post_epoch),.out_token(post_token),.out_site(post_site),.out_lanes(post_lanes),
        .out_last(post_last),.out_data(post_data),.done(collect_done),.error_valid(collect_error),.active(collect_active));
    z100_native_output_packer #(.SITES(20)) packer(
        .clk(clk),.rst_n(rst_n),.cancel(local_cancel),.cfg_valid(state==PACK_CFG),.cfg_ready(pack_ready),
        .cfg_epoch(epoch_q),.cfg_channels(channels_q),.cfg_height(height_q),.cfg_width(10'd20),.cfg_token_base(32'd1),
        .in_valid(post_valid),.in_ready(post_ready),.in_epoch(post_epoch),.in_token(post_token),
        .in_site(post_site),.in_lanes(post_lanes),.in_last(post_last),.in_data(post_data),
        .out_valid(pack_valid),.out_ready(out_ready&&state!=FAULT&&!child_failure),
        .out_epoch(out_epoch),.out_address(out_address),.out_data(out_data),.out_last(out_last),
        .done(pack_done),.error_valid(pack_error),.error_code(pack_error_code),.active(pack_active));
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            state<=IDLE;done<=0;error_valid<=0;error_code<=0;
            epoch_q<=0;block_q<=0;channels_q<=0;channel_base_q<=0;height_q<=0;row_q<=0;subgroup_q<=0;tap_q<=0;tap_x_q<=0;tap_y_q<=0;block_row_base_q<=0;group_row_base_q<=0;
        end else begin
            done<=0;error_valid<=0;error_code<=0;
            if(child_failure)begin
                error_valid<=1;error_code<=fw_error ? 4'd2 : pool_error ? 4'd3 : collect_error ? 4'd4 : 4'd5;
                state<=FAULT;
            end else case(state)
                IDLE:if(job_valid&&job_ready)begin
                    if(!job_good)begin error_valid<=1;error_code<=1;end
                    else begin
                        state<=PACK_CFG;epoch_q<=job_epoch;channels_q<=job_channels;height_q<=job_height;
                        row_q<=0;channel_base_q<=0;block_q<=0;subgroup_q<=0;tap_q<=0;tap_x_q<=0;tap_y_q<=0;block_row_base_q<=0;group_row_base_q<=0;
                    end
                end
                PACK_CFG:if(pack_ready)state<=COLLECT_CFG;
                COLLECT_CFG:if(collect_ready)begin state<=ISSUE;subgroup_q<=0;tap_q<=0;tap_x_q<=0;tap_y_q<=0;group_row_base_q<=block_row_base_q;end
                ISSUE:if(window_ready)begin
                    if(tap_q==24)state<=WAIT_VECTOR;
                    else begin
                        tap_q<=tap_q+1'b1;
                        if(tap_x_q==4)begin tap_x_q<=0;tap_y_q<=tap_y_q+1'b1;end
                        else tap_x_q<=tap_x_q+1'b1;
                    end
                end
                WAIT_VECTOR:if(pool_valid&&pool_ready)begin
                    if(subgroup_q+1==group_count)state<=WAIT_COLLECT;
                    else begin subgroup_q<=subgroup_q+1'b1;tap_q<=0;tap_x_q<=0;tap_y_q<=0;group_row_base_q<=group_row_base_q+{3'd0,height_q,1'b0};state<=ISSUE;end
                end
                WAIT_COLLECT:if(collect_done)begin
                    if(row_q+1==height_q&&channel_base_q+32>=channels_q)state<=DRAIN;
                    else begin
                        block_q<=block_q+1;
                        if(row_q+1==height_q)begin row_q<=0;channel_base_q<=channel_base_q+32;block_row_base_q<=block_row_base_q+{height_q,4'd0};end
                        else row_q<=row_q+1;
                        state<=COLLECT_CFG;
                    end
                end
                DRAIN:if(pack_done)begin state<=IDLE;done<=1;end
                FAULT:state<=FAULT;
                default:begin state<=FAULT;error_valid<=1;error_code<=6;end
            endcase
        end
    end
endmodule
`default_nettype wire
