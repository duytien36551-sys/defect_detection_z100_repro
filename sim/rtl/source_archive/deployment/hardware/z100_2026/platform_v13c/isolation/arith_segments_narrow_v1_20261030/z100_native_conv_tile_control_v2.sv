`default_nettype none
// Private Conv tile RUN sequencer. Parameter-group -> all output rows -> next
// group matches the existing packer order. Completion requires an external
// successful write/publication acknowledgement, not merely row submission.
// Cancel invalidates private work; external AXI owners must still drain. This
// module never resets DMA/AXI or releases a graph source lease on its own.
(* use_dsp="no" *)
module z100_native_conv_tile_control_v2(
    input wire clk,rst_n,cancel,recover,recovery_drained,
    input wire cmd_valid,output wire cmd_ready,
    input wire[31:0] cmd_epoch,cmd_token_base,cmd_tag_base,cmd_job_tag,
    input wire[15:0] cmd_parameter_first,
    input wire[10:0] cmd_input_channels,cmd_output_channels,
    input wire[9:0] cmd_input_height,cmd_input_width,cmd_input_y,cmd_input_rows,
    input wire[9:0] cmd_output_height,cmd_output_width,cmd_output_y,cmd_output_rows,
    input wire[1:0] cmd_kernel,cmd_stride,cmd_padding,
    output wire pack_valid,input wire pack_ready,
    output wire[31:0] epoch,pack_token_base,job_tag,
    output wire[10:0] pack_channels,
    output wire[9:0] pack_height,pack_width,
    output wire parameter_valid,input wire parameter_ready,
    output wire[15:0] parameter_job,
    input wire parameter_done_valid,output wire parameter_done_ready,
    input wire[31:0] parameter_done_epoch,parameter_done_job_tag,input wire[15:0] parameter_done_job,
    input wire parameter_done_error,
    output wire row_valid,input wire row_ready,
    output wire[31:0] row_token_base,row_tag_base,
    output wire[10:0] row_channels,
    output wire[9:0] row_input_width,row_output_width,
    output wire[1:0] row_kernel,row_stride,row_padding,
    output wire[5:0] row_lanes,
    output wire[13:0] row_bank_words,row_plane_stride,
    output reg[41:0] row_ky_bases,output reg[2:0] row_y_valid,
    input wire row_done_valid,output wire row_done_ready,
    input wire[31:0] row_done_epoch,row_done_last_token,row_done_job_tag,input wire row_done_error,
    input wire publish_valid,output wire publish_ready,
    input wire[31:0] publish_epoch,publish_tag,input wire publish_error,
    output wire child_cancel,active,needs_drain,
    output reg done,fault,output reg[3:0] fault_code
);
    localparam IDLE=0,PACK=1,PARAM=2,PARAM_WAIT=3,ROW=4,ROW_WAIT=5,PUBLISH=6,FAILED=7;
    reg[3:0] state;
    reg[31:0] epoch_q,token_q,tag_q,tile_token_q,tile_tag_q,tag_step_q;
    reg[31:0] job_tag_q,ledger_epoch,ledger_tag;
    reg[15:0] parameter_first_q;
    reg[10:0] cin_q,cout_q;
    reg[9:0] ih_q,iw_q,iy_q,ir_q,ow_q,oy_q,rows_q,row_q;
    reg[1:0] k_q,s_q,p_q;
    reg[5:0] group_q,group_count_q,segments_q;
    reg[13:0] bank_words_q,plane_q;
    reg[5:0] xwords_q;
    reg command_ok;
    wire [10:0] segment_numerator = {1'b0,cmd_output_width}+11'd19;
    wire [10:0] segment_quotient = segment_numerator/11'd20;
    wire [5:0] segment_count = segment_quotient[5:0];
    reg[63:0] xwords,plane,bank_words,groups,segments,outgroups,runs,words;
    reg signed[31:0] first_tap,last_tap,needed_first,needed_last,numerator_x,numerator_y;
    always @*begin
        xwords=({54'd0,cmd_input_width}+15)/16;
        plane={54'd0,cmd_input_rows}*xwords;
        bank_words=(({53'd0,cmd_input_channels}+3)/4)*plane;
        groups=(({53'd0,cmd_input_channels}+3)/4)*cmd_kernel*cmd_kernel;
        segments={58'd0,segment_count};
        outgroups=({53'd0,cmd_output_channels}+31)/32;
        runs=outgroups*cmd_output_rows*segments;
        words=(({53'd0,cmd_output_channels}+3)/4)*cmd_output_rows*(({54'd0,cmd_output_width}+15)/16);
        numerator_x=$signed({22'd0,cmd_input_width})+2*$signed({30'd0,cmd_padding})-$signed({30'd0,cmd_kernel});
        numerator_y=$signed({22'd0,cmd_input_height})+2*$signed({30'd0,cmd_padding})-$signed({30'd0,cmd_kernel});
        first_tap=$signed({22'd0,cmd_output_y})*$signed({30'd0,cmd_stride})-$signed({30'd0,cmd_padding});
        last_tap=($signed({22'd0,cmd_output_y})+$signed({22'd0,cmd_output_rows})-1)*$signed({30'd0,cmd_stride})-$signed({30'd0,cmd_padding})+$signed({30'd0,cmd_kernel})-1;
        needed_first=first_tap<0?0:first_tap;
        needed_last=last_tap>=$signed({22'd0,cmd_input_height})?$signed({22'd0,cmd_input_height})-1:last_tap;
        command_ok=cmd_epoch!=0&&cmd_token_base!=0&&cmd_job_tag!=0&&
            (cmd_epoch>ledger_epoch||(cmd_epoch==ledger_epoch&&cmd_job_tag>ledger_tag))&&
            cmd_input_channels>=1&&cmd_input_channels<=1024&&cmd_output_channels>=1&&cmd_output_channels<=1024&&
            cmd_input_height>=1&&cmd_input_height<=640&&cmd_input_width>=1&&cmd_input_width<=640&&
            cmd_output_height>=1&&cmd_output_height<=640&&cmd_output_width>=1&&cmd_output_width<=640&&
            cmd_input_rows>=1&&cmd_output_rows>=1&&
            {1'b0,cmd_input_y}+{1'b0,cmd_input_rows}<=cmd_input_height&&
            {1'b0,cmd_output_y}+{1'b0,cmd_output_rows}<=cmd_output_height&&
            (cmd_kernel==1||cmd_kernel==3)&&(cmd_stride==1||cmd_stride==2)&&cmd_padding<=1&&
            numerator_x>=0&&numerator_y>=0&&
            (cmd_stride==2?(numerator_x>>1)+1:numerator_x+1)==cmd_output_width&&
            (cmd_stride==2?(numerator_y>>1)+1:numerator_y+1)==cmd_output_height&&
            cmd_input_y<=needed_first&&cmd_input_y+cmd_input_rows>needed_last&&
            bank_words>=1&&bank_words<=4096&&groups>=1&&groups<=1024&&words>=1&&words<=8192&&
            {32'd0,cmd_token_base}+runs-1<=64'hffffffff&&
            {32'd0,cmd_tag_base}+runs*groups-1<=64'hffffffff&&
            {48'd0,cmd_parameter_first}+outgroups-1<=65535;
    end
    assign cmd_ready=rst_n&&state==IDLE&&!cancel&&!fault;
    assign active=state!=IDLE&&state!=FAILED;
    assign needs_drain=state==FAILED;
    assign child_cancel=cancel||fault;
    assign job_tag=job_tag_q;assign epoch=epoch_q;assign pack_token_base=tile_token_q;
    assign pack_channels=cout_q;assign pack_height=rows_q;assign pack_width=ow_q;
    assign pack_valid=rst_n&&state==PACK&&!cancel&&!fault;
    assign parameter_valid=rst_n&&state==PARAM&&!cancel&&!fault;
    assign parameter_job=parameter_first_q+group_q;
    assign parameter_done_ready=rst_n&&state==PARAM_WAIT&&!cancel&&!fault;
    assign row_valid=rst_n&&state==ROW&&!cancel&&!fault;
    assign row_token_base=token_q;assign row_tag_base=tag_q;
    assign row_channels=cin_q;assign row_input_width=iw_q;assign row_output_width=ow_q;
    assign row_kernel=k_q;assign row_stride=s_q;assign row_padding=p_q;
    assign row_lanes=({1'b0,cout_q}-{1'b0,group_q,5'd0}>=32)?6'd32:cout_q-group_q*32;
    assign row_bank_words=bank_words_q;assign row_plane_stride=plane_q;
    assign row_done_ready=rst_n&&state==ROW_WAIT&&!cancel&&!fault;
    assign publish_ready=rst_n&&state==PUBLISH&&!cancel&&!fault;
    integer ky;reg signed[31:0] sy,local_y;
    always @*begin
        row_ky_bases=0;row_y_valid=0;sy=0;local_y=0;
        for(ky=0;ky<3;ky=ky+1)if(ky<k_q)begin
            sy=($signed({22'd0,oy_q})+$signed({22'd0,row_q}))*$signed({30'd0,s_q})-$signed({30'd0,p_q})+ky;
            local_y=sy-$signed({22'd0,iy_q});
            if(sy>=0&&sy<$signed({22'd0,ih_q}))begin
                row_y_valid[ky]=1;row_ky_bases[ky*14+:14]=local_y*xwords_q;
            end
        end
    end
    task fail(input[3:0] code);begin state<=FAILED;fault<=1;fault_code<=code;end endtask
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;done<=0;fault<=0;fault_code<=0;job_tag_q<=0;ledger_epoch<=0;ledger_tag<=0;epoch_q<=0;token_q<=0;tag_q<=0;
            tile_token_q<=0;tile_tag_q<=0;tag_step_q<=0;parameter_first_q<=0;cin_q<=0;cout_q<=0;
            ih_q<=0;iw_q<=0;iy_q<=0;ir_q<=0;ow_q<=0;oy_q<=0;rows_q<=0;row_q<=0;
            k_q<=0;s_q<=0;p_q<=0;group_q<=0;group_count_q<=0;segments_q<=0;bank_words_q<=0;plane_q<=0;xwords_q<=0;
        end else begin
            done<=0;
            if(state==FAILED)begin
                if(recover&&recovery_drained&&!cancel)begin state<=IDLE;fault<=0;fault_code<=0;end
            end else if(cancel)fail(4'd2);
            else if((parameter_done_valid&&state!=PARAM_WAIT)||(row_done_valid&&state!=ROW_WAIT)||(publish_valid&&state!=PUBLISH))fail(4'd3);
            else case(state)
                IDLE:if(cmd_valid&&cmd_ready)begin
                    if(!command_ok)fail(4'd1);
                    else begin
                        epoch_q<=cmd_epoch;token_q<=cmd_token_base;tag_q<=cmd_tag_base;
                        job_tag_q<=cmd_job_tag;ledger_epoch<=cmd_epoch;ledger_tag<=cmd_job_tag;
                        tile_token_q<=cmd_token_base;tile_tag_q<=cmd_tag_base;tag_step_q<=segments*groups;
                        parameter_first_q<=cmd_parameter_first;cin_q<=cmd_input_channels;cout_q<=cmd_output_channels;
                        ih_q<=cmd_input_height;iw_q<=cmd_input_width;iy_q<=cmd_input_y;ir_q<=cmd_input_rows;
                        ow_q<=cmd_output_width;oy_q<=cmd_output_y;rows_q<=cmd_output_rows;
                        k_q<=cmd_kernel;s_q<=cmd_stride;p_q<=cmd_padding;
                        group_q<=0;row_q<=0;group_count_q<=outgroups;segments_q<=segments;
                        bank_words_q<=bank_words;plane_q<=plane;xwords_q<=xwords;state<=PACK;
                    end
                end
                PACK:if(pack_valid&&pack_ready)state<=PARAM;
                PARAM:if(parameter_valid&&parameter_ready)state<=PARAM_WAIT;
                PARAM_WAIT:if(parameter_done_valid&&parameter_done_ready)begin
                    if(parameter_done_error||parameter_done_epoch!=epoch_q||parameter_done_job_tag!=job_tag_q||parameter_done_job!=parameter_job)fail(4'd4);
                    else state<=ROW;
                end
                ROW:if(row_valid&&row_ready)state<=ROW_WAIT;
                ROW_WAIT:if(row_done_valid&&row_done_ready)begin
                    if(row_done_error||row_done_epoch!=epoch_q||row_done_job_tag!=job_tag_q||row_done_last_token!=token_q+segments_q-1)fail(4'd5);
                    else begin
                        token_q<=token_q+segments_q;tag_q<=tag_q+tag_step_q;
                        if(row_q+1<rows_q)begin row_q<=row_q+1;state<=ROW;end
                        else if(group_q+1<group_count_q)begin group_q<=group_q+1;row_q<=0;state<=PARAM;end
                        else state<=PUBLISH;
                    end
                end
                PUBLISH:if(publish_valid&&publish_ready)begin
                    if(publish_error||publish_epoch!=epoch_q||publish_tag!=job_tag_q)fail(4'd6);
                    else begin done<=1;state<=IDLE;end
                end
                default:fail(4'd7);
            endcase
        end
    end
endmodule
`default_nettype wire
