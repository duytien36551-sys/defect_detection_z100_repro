`default_nettype none
// Whole-channel clipped row tile from a committed materialized native tensor.
// One reader command per32-channel source block, not one per512-bit word.
// The stream codec receives block_word_base+reader_index and whole-tile LAST.
// Cache ownership transfers only after codec retirement and feature commit.
(* use_dsp="no" *)
module z100_native_materialized_load_control (
    input wire clk,rst_n,
    input wire cmd_valid,output wire cmd_ready,
    input wire [31:0] cmd_epoch,cmd_source_generation,cmd_source_address,cmd_timeout_cycles,
    input wire [10:0] cmd_channels,
    input wire [9:0] cmd_full_height,cmd_width,cmd_first_row,cmd_height,
    input wire cmd_source_committed,cmd_source_is_materialized,
    input wire abort,recover,
    output wire active,fault,output reg [3:0] fault_code,output reg done,result_committed,
    output wire [31:0] epoch,source_generation,
    output wire [10:0] channels,output wire [9:0] height,width,
    output wire [13:0] total_words,block_words,block_word_base,
    output wire feature_begin,input wire feature_begin_ready,
    output wire order_config,input wire order_config_ready,input wire order_done,
    output wire feature_commit,input wire feature_commit_ready,
    output wire reader_command,input wire reader_command_ready,
    output wire [31:0] reader_address,
    input wire reader_done,reader_busy,reader_fault,pipeline_error,
    output wire semantic_cancel,reader_cancel,reader_clear_fault
);
    localparam IDLE=0,CONFIG=1,ISSUE=2,READ_WAIT=3,NEXT_BLOCK=4,ORDER_WAIT=5,COMMIT=6,COMPLETE=7,FAILED=8,CLEAR=9,RECOVER_WAIT=10;
    reg [3:0] state;
    reg [31:0] epoch_q,generation_q,address_q,timeout_q,elapsed_q;
    reg [10:0] channels_q,channel_base_q;
    reg [9:0] full_height_q,width_q,first_row_q,height_q;
    reg [5:0] xwords_q;reg [13:0] total_words_q,word_base_q;
    reg feature_configured,order_configured,order_finished;
    wire running=state>=CONFIG&&state<=COMPLETE;
    wire [5:0] command_xwords=({1'b0,cmd_width}+15)>>4;
    wire [31:0] command_groups4=({21'd0,cmd_channels}+3)>>2;
    wire [31:0] command_total=command_groups4*cmd_height*command_xwords;
    wire [31:0] command_full_words=command_groups4*cmd_full_height*command_xwords;
    wire [32:0] command_full_end={1'b0,cmd_source_address}+({1'b0,command_full_words}<<6);
    wire command_good=cmd_epoch!=0&&cmd_source_generation!=0&&cmd_source_address[5:0]==0&&cmd_timeout_cycles!=0&&
        cmd_channels>0&&cmd_channels<=1024&&cmd_width>0&&cmd_width<=640&&cmd_full_height>0&&cmd_full_height<=640&&
        cmd_height>0&&cmd_height<=640&&({1'b0,cmd_first_row}+{1'b0,cmd_height})<={1'b0,cmd_full_height}&&
        command_total>0&&command_total<=8192&&command_full_end<=33'h100000000&&cmd_source_committed&&cmd_source_is_materialized;
    wire [11:0] remaining_channels={1'b0,channels_q}-{1'b0,channel_base_q};
    wire [3:0] subgroups=remaining_channels>=32 ? 4'd8 : ((remaining_channels+3)>>2);
    wire [31:0] current_block_words=subgroups*height_q*xwords_q;
    wire [31:0] source_word_offset=(channel_base_q>>2)*full_height_q*xwords_q+first_row_q*xwords_q*subgroups;
    wire [32:0] block_address={1'b0,address_q}+({1'b0,source_word_offset}<<6);
    wire timed_out=running&&elapsed_q>=timeout_q;
    wire stop_work=abort||timed_out||reader_fault||pipeline_error;
    assign active=state!=IDLE;
    assign fault=state>=FAILED;
    assign cmd_ready=rst_n&&state==IDLE&&!abort&&!reader_busy&&!reader_fault&&!pipeline_error;
    assign epoch=epoch_q;assign source_generation=generation_q;assign channels=channels_q;assign height=height_q;assign width=width_q;
    assign total_words=total_words_q;assign block_words=current_block_words[13:0];assign block_word_base=word_base_q;
    assign reader_address=block_address[31:0];
    assign feature_begin=rst_n&&state==CONFIG&&!feature_configured&&!stop_work;
    assign order_config=rst_n&&state==CONFIG&&!order_configured&&!stop_work;
    assign reader_command=rst_n&&state==ISSUE&&!stop_work;
    assign feature_commit=rst_n&&state==COMMIT&&!stop_work;
    assign semantic_cancel=rst_n&&(fault||running&&stop_work);
    assign reader_cancel=rst_n&&(state==FAILED||running&&stop_work);
    assign reader_clear_fault=rst_n&&state==CLEAR&&!abort;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;fault_code<=0;done<=0;result_committed<=0;
            epoch_q<=0;generation_q<=0;address_q<=0;timeout_q<=0;elapsed_q<=0;channels_q<=0;channel_base_q<=0;
            full_height_q<=0;width_q<=0;first_row_q<=0;height_q<=0;xwords_q<=0;total_words_q<=0;word_base_q<=0;
            feature_configured<=0;order_configured<=0;order_finished<=0;
        end else begin
            done<=0;
            if(running)begin elapsed_q<=elapsed_q+1;if(order_done)order_finished<=1;end
            if(running&&stop_work)begin
                state<=FAILED;result_committed<=0;fault_code<=abort ? 2 : timed_out ? 3 : reader_fault ? 4 : 5;
            end else case(state)
                IDLE:if(reader_fault)begin state<=FAILED;fault_code<=4;result_committed<=0;end
                    else if(cmd_valid&&cmd_ready)begin
                        result_committed<=0;elapsed_q<=0;fault_code<=0;
                        if(!command_good)begin state<=FAILED;fault_code<=1;end
                        else begin
                            epoch_q<=cmd_epoch;generation_q<=cmd_source_generation;address_q<=cmd_source_address;timeout_q<=cmd_timeout_cycles;
                            channels_q<=cmd_channels;full_height_q<=cmd_full_height;width_q<=cmd_width;first_row_q<=cmd_first_row;height_q<=cmd_height;
                            xwords_q<=command_xwords;total_words_q<=command_total[13:0];word_base_q<=0;channel_base_q<=0;
                            feature_configured<=0;order_configured<=0;order_finished<=0;state<=CONFIG;
                        end
                    end
                CONFIG:begin
                    if(feature_begin&&feature_begin_ready)feature_configured<=1;
                    if(order_config&&order_config_ready)order_configured<=1;
                    if((feature_configured||feature_begin_ready)&&(order_configured||order_config_ready))state<=ISSUE;
                end
                ISSUE:if(block_address>33'h0ffffffff||current_block_words==0||current_block_words>8192||word_base_q+current_block_words>total_words_q)begin state<=FAILED;fault_code<=6;end
                    else if(reader_command&&reader_command_ready)state<=READ_WAIT;
                READ_WAIT:if(reader_done)state<=NEXT_BLOCK;
                NEXT_BLOCK:if(word_base_q+current_block_words==total_words_q)state<=ORDER_WAIT;
                    else begin word_base_q<=word_base_q+current_block_words;channel_base_q<=channel_base_q+32;state<=ISSUE;end
                ORDER_WAIT:if((order_finished||order_done)&&!reader_busy)state<=COMMIT;
                COMMIT:if(feature_commit&&feature_commit_ready)state<=COMPLETE;
                COMPLETE:begin done<=1;result_committed<=1;state<=IDLE;end
                FAILED:if(recover&&!abort&&!reader_busy)state<=CLEAR;
                CLEAR:if(!abort)state<=RECOVER_WAIT;else state<=FAILED;
                RECOVER_WAIT:if(abort)state<=FAILED;
                    else if(!reader_busy&&!reader_fault&&!pipeline_error)begin state<=IDLE;fault_code<=0;end
                default:begin state<=FAILED;fault_code<=7;result_committed<=0;end
            endcase
        end
    end
endmodule
`default_nettype wire
