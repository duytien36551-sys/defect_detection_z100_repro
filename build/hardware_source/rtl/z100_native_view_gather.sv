`default_nettype none
// One channel4 descriptor autonomously gathers a virtual tensor into a bank
// loader. Source strides are compiler-bound native-stream byte strides, not
// canonical bank addresses. AXI ownership stays with the frozen reader: abort
// holds cancel until it drains; recovery never locally resets the AXI adapter.
(* use_dsp="no" *)
module z100_native_view_gather (
    input wire clk,rst_n,
    input wire cfg_begin,output wire cfg_begin_ready,input wire [31:0] cfg_epoch,input wire [2:0] cfg_contexts,
    input wire cfg_word_valid,output wire cfg_word_ready,input wire [7:0] cfg_data,
    input wire cfg_commit,output wire cfg_commit_ready,output wire store_valid,loading,
    output wire cfg_error,output wire [2:0] cfg_error_code,
    input wire cmd_valid,output wire cmd_ready,
    input wire [31:0] cmd_epoch,cmd_table_epoch,cmd_source_address,cmd_region_begin,
    input wire [32:0] cmd_region_end,
    input wire [31:0] cmd_source_row_stride,cmd_source_x_stride,cmd_output_word_base,cmd_timeout_cycles,
    input wire [9:0] cmd_height,cmd_width,input wire [2:0] cmd_channels,
    input wire [1:0] cmd_nearest_shift,cmd_context,input wire cmd_source_committed,
    input wire abort,recover,output wire active,output wire fault,output reg [3:0] fault_code,output reg done,
    output wire read_command,input wire read_command_ready,
    output wire [31:0] read_epoch,read_address,
    input wire reader_busy,reader_fault,output wire read_cancel,read_clear_fault,
    input wire read_valid,output wire read_ready,input wire [31:0] read_result_epoch,
    input wire [12:0] read_result_index,input wire read_last,input wire [511:0] read_data,
    output wire out_valid,input wire out_ready,output wire [31:0] out_epoch,out_word_address,
    output wire [511:0] out_data,output wire out_last
);
    localparam IDLE=0,ISSUE=1,REPLY=2,OUTPUT_WAIT=3,FINISH=4,FAILED=5,CLEAR=6,RECOVER_WAIT=7;
    reg [2:0] state;
    reg [31:0] epoch_q,table_epoch_q,row_stride_q,x_stride_q,output_base_q,timeout_q,elapsed_q;
    reg [32:0] address_q,row_address_q,region_begin_q,region_end_q;
    reg [9:0] height_q,width_q,y_q;reg [5:0] xwords_q,xword_q;
    reg [2:0] channels_q;reg [1:0] shift_q,context_q;
    reg [15:0] word_index_q,total_words_q;
    wire running=state>=ISSUE&&state<=FINISH;
    wire [5:0] command_xwords=({1'b0,cmd_width}+15)>>4;
    wire [15:0] command_words=cmd_height*command_xwords;
    wire [32:0] command_output_end={1'b0,cmd_output_word_base}+command_words;
    wire command_good=cmd_epoch!=0&&cmd_table_epoch!=0&&cmd_height>0&&cmd_height<=640&&cmd_width>0&&cmd_width<=640&&
        cmd_channels>0&&cmd_channels<=4&&cmd_nearest_shift<=2&&cmd_source_committed&&cmd_timeout_cycles!=0&&
        cmd_source_address[5:0]==0&&cmd_region_begin[5:0]==0&&cmd_region_end[5:0]==0&&
        cmd_region_end<=33'h100000000&&{1'b0,cmd_region_begin}<cmd_region_end&&
        cmd_source_row_stride!=0&&cmd_source_row_stride[5:0]==0&&cmd_source_x_stride!=0&&cmd_source_x_stride[5:0]==0&&
        command_output_end<=33'h100000000;
    wire range_good=address_q>=region_begin_q&&address_q+33'd64<=region_end_q;
    wire timed_out=running&&elapsed_q>=timeout_q;
    wire stop_work=abort||timed_out||reader_fault||cfg_error;
    assign active=state!=IDLE;
    assign fault=state>=FAILED;
    assign cmd_ready=rst_n&&state==IDLE&&store_valid&&!loading&&!cfg_begin&&!cfg_word_valid&&!cfg_commit&&!reader_busy&&!reader_fault&&!abort;
    assign read_epoch=epoch_q;assign read_address=address_q[31:0];
    assign read_command=rst_n&&state==ISSUE&&!stop_work&&range_good;
    assign read_cancel=rst_n&&(state==FAILED||running&&stop_work);
    assign read_clear_fault=rst_n&&state==CLEAR&&!abort;
    wire cfg_idle=state==IDLE&&!cmd_valid;
    wire cbr,cwr,ccr;
    assign cfg_begin_ready=cfg_idle&&cbr;assign cfg_word_ready=cfg_idle&&cwr;assign cfg_commit_ready=cfg_idle&&ccr;
    wire view_valid,view_ready;wire [31:0] view_epoch,view_token;wire view_last;
    wire bad_response=read_result_epoch!=epoch_q||read_result_index!=0||!read_last;
    wire [3:0] first_x=shift_q==0 ? 4'd0 : shift_q==1 ? {xword_q[0],3'd0} : {xword_q[1:0],2'd0};
    wire [10:0] remaining_x={1'b0,width_q}-({5'd0,xword_q}<<4);
    wire [4:0] valid_x=remaining_x>=16 ? 5'd16 : remaining_x[4:0];
    wire final_word=word_index_q+1==total_words_q;
    assign read_ready=rst_n&&state==REPLY&&!stop_work&&(bad_response||view_ready);
    assign out_valid=rst_n&&state==OUTPUT_WAIT&&!stop_work&&view_valid;
    assign out_epoch=view_epoch;assign out_word_address=output_base_q+word_index_q;assign out_last=view_last;
    z100_native_view_context4 transform(.clk(clk),.rst_n(rst_n),.cancel(state==FAILED||running&&stop_work),
        .cfg_begin(cfg_begin&&cfg_idle),.cfg_begin_ready(cbr),.cfg_epoch(cfg_epoch),.cfg_contexts(cfg_contexts),
        .cfg_word_valid(cfg_word_valid&&cfg_idle),.cfg_word_ready(cwr),.cfg_data(cfg_data),
        .cfg_commit(cfg_commit&&cfg_idle),.cfg_commit_ready(ccr),.store_valid(store_valid),.loading(loading),.error_valid(cfg_error),.error_code(cfg_error_code),
        .in_valid(read_valid&&state==REPLY&&!stop_work&&!bad_response),.in_ready(view_ready),
        .in_epoch(epoch_q),.in_token({16'd0,word_index_q}+1),.in_table_epoch(table_epoch_q),.in_context(context_q),
        .in_source_first_x(first_x),.in_nearest_shift(shift_q),.in_channels(channels_q),.in_x_count(valid_x),
        .in_last(final_word),.in_data(read_data),.out_valid(view_valid),.out_ready(out_ready&&state==OUTPUT_WAIT&&!stop_work),
        .out_epoch(view_epoch),.out_token(view_token),.out_last(view_last),.out_data(out_data));
    wire repeat_x_end=shift_q==0||shift_q==1&&xword_q[0]||shift_q==2&&xword_q[1:0]==3;
    wire repeat_y_end=shift_q==0||shift_q==1&&y_q[0]||shift_q==2&&y_q[1:0]==3;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;fault_code<=0;done<=0;epoch_q<=0;table_epoch_q<=0;row_stride_q<=0;x_stride_q<=0;output_base_q<=0;
            timeout_q<=0;elapsed_q<=0;address_q<=0;row_address_q<=0;region_begin_q<=0;region_end_q<=0;
            height_q<=0;width_q<=0;y_q<=0;xwords_q<=0;xword_q<=0;channels_q<=0;shift_q<=0;context_q<=0;word_index_q<=0;total_words_q<=0;
        end else begin
            done<=0;if(running)elapsed_q<=elapsed_q+1;
            if(running&&stop_work)begin state<=FAILED;fault_code<=abort ? 2 : timed_out ? 3 : reader_fault ? 4 : 5;end
            else case(state)
                IDLE:if(cmd_valid&&cmd_ready)begin
                    elapsed_q<=0;fault_code<=0;
                    if(!command_good)begin state<=FAILED;fault_code<=1;end
                    else begin
                        epoch_q<=cmd_epoch;table_epoch_q<=cmd_table_epoch;row_stride_q<=cmd_source_row_stride;x_stride_q<=cmd_source_x_stride;
                        output_base_q<=cmd_output_word_base;timeout_q<=cmd_timeout_cycles;address_q<={1'b0,cmd_source_address};
                        row_address_q<={1'b0,cmd_source_address};region_begin_q<={1'b0,cmd_region_begin};region_end_q<=cmd_region_end;
                        height_q<=cmd_height;width_q<=cmd_width;xwords_q<=command_xwords;channels_q<=cmd_channels;shift_q<=cmd_nearest_shift;
                        context_q<=cmd_context;y_q<=0;xword_q<=0;word_index_q<=0;total_words_q<=command_words;state<=ISSUE;
                    end
                end
                ISSUE:if(!range_good)begin state<=FAILED;fault_code<=6;end
                    else if(read_command&&read_command_ready)state<=REPLY;
                REPLY:if(read_valid&&read_ready)begin
                    if(bad_response)begin state<=FAILED;fault_code<=7;end else state<=OUTPUT_WAIT;
                end
                OUTPUT_WAIT:if(out_valid&&out_ready)begin
                    if(view_epoch!=epoch_q||view_token!=word_index_q+1||view_last!=final_word)begin state<=FAILED;fault_code<=8;end
                    else if(final_word)state<=FINISH;
                    else begin
                        word_index_q<=word_index_q+1;state<=ISSUE;
                        if(xword_q+1==xwords_q)begin
                            xword_q<=0;y_q<=y_q+1;
                            if(repeat_y_end)begin row_address_q<=row_address_q+row_stride_q;address_q<=row_address_q+row_stride_q;end
                            else address_q<=row_address_q;
                        end else begin xword_q<=xword_q+1;if(repeat_x_end)address_q<=address_q+x_stride_q;end
                    end
                end
                FINISH:if(!reader_busy)begin done<=1;state<=IDLE;end
                FAILED:if(recover&&!abort&&!reader_busy)state<=CLEAR;
                CLEAR:if(!abort)state<=RECOVER_WAIT;else state<=FAILED;
                RECOVER_WAIT:if(abort)state<=FAILED;else if(!reader_busy&&!reader_fault&&!cfg_error)begin state<=IDLE;fault_code<=0;end
                default:begin state<=FAILED;fault_code<=9;end
            endcase
        end
    end
endmodule
`default_nettype wire
