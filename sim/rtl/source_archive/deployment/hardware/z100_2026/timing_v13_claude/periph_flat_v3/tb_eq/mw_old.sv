`default_nettype none
// Whole-channel row tile -> reserved native DDR tensor. One writer command per
// channel32 block. Completion follows every B response and codec retirement.
// tile_committed is NOT whole-tensor publication: an external owner must verify
// all nonoverlapping tiles before releasing the destination generation.
(* use_dsp="no" *)
module mw_old (
    input wire clk,rst_n,
    input wire cmd_valid,output wire cmd_ready,
    input wire [31:0] cmd_epoch,cmd_destination_generation,cmd_destination_address,cmd_region_begin,cmd_timeout_cycles,
    input wire [32:0] cmd_region_end,
    input wire [10:0] cmd_channels,input wire [9:0] cmd_full_height,cmd_width,cmd_first_row,cmd_height,
    input wire cmd_destination_reserved,
    input wire abort,recover,
    output wire active,fault,output reg [3:0] fault_code,output reg done,tile_committed,
    output wire [31:0] epoch,destination_generation,
    output wire [10:0] channels,output wire [9:0] height,width,
    output wire order_config,input wire order_config_ready,input wire order_done,
    input wire packed_valid,output wire packed_ready,input wire [31:0] packed_epoch,
    input wire [12:0] packed_index,input wire packed_last,input wire [511:0] packed_data,
    output wire writer_command,input wire writer_command_ready,
    output wire [31:0] writer_address,output wire [13:0] writer_words,
    output wire writer_valid,input wire writer_ready,output wire [31:0] writer_epoch,
    output wire [12:0] writer_index,output wire writer_last,output wire [511:0] writer_data,
    input wire writer_done,writer_busy,writer_fault,pipeline_error,
    output wire semantic_cancel,writer_cancel,writer_clear_fault
);
    localparam IDLE=0,CONFIG=1,ISSUE=2,WRITE_WAIT=3,NEXT_BLOCK=4,FINISH=5,FAILED=6,CLEAR=7,RECOVER_WAIT=8;
    reg [3:0] state;
    reg [31:0] epoch_q,generation_q,address_q,timeout_q,elapsed;
    reg [10:0] channels_q,channel_base;
    reg [9:0] full_height_q,width_q,first_row_q,height_q;
    reg [5:0] xwords_q;
    reg [13:0] total_words,word_base,accepted_words;
    reg order_finished;
    wire running=state>=CONFIG&&state<=FINISH;
    wire [31:0] cfg_xwords=({22'd0,cmd_width}+15)>>4;
    wire [31:0] cfg_groups=({21'd0,cmd_channels}+3)>>2;
    wire [31:0] cfg_total=cfg_groups*cmd_height*cfg_xwords;
    wire [31:0] cfg_full_words=cfg_groups*cmd_full_height*cfg_xwords;
    wire [32:0] cfg_end={1'b0,cmd_destination_address}+({1'b0,cfg_full_words}<<6);
    wire command_good=cmd_epoch!=0&&cmd_destination_generation!=0&&cmd_destination_reserved&&cmd_timeout_cycles!=0&&
        cmd_destination_address[5:0]==0&&cmd_region_begin[5:0]==0&&cmd_region_end[5:0]==0&&
        {1'b0,cmd_destination_address}>={1'b0,cmd_region_begin}&&{1'b0,cmd_region_begin}<cmd_region_end&&
        cfg_end<=cmd_region_end&&cmd_region_end<=33'h100000000&&
        cmd_channels>0&&cmd_channels<=1024&&cmd_width>0&&cmd_width<=640&&cmd_full_height>0&&cmd_full_height<=640&&
        cmd_height>0&&({1'b0,cmd_first_row}+{1'b0,cmd_height})<={1'b0,cmd_full_height}&&cfg_total>0&&cfg_total<=8192;
    wire [11:0] channels_left={1'b0,channels_q}-{1'b0,channel_base};
    wire [3:0] subgroups=channels_left>=32 ? 8 : (channels_left+3)>>2;
    wire [31:0] block_words=subgroups*height_q*xwords_q;
    wire [31:0] offset_words=(channel_base>>2)*full_height_q*xwords_q+first_row_q*xwords_q*subgroups;
    wire [32:0] block_address={1'b0,address_q}+({1'b0,offset_words}<<6);
    wire timed_out=running&&elapsed>=timeout_q;
    wire bad_packed=packed_epoch!=epoch_q||{1'b0,packed_index}!=accepted_words||
        packed_last!=(accepted_words+1==total_words);
    wire stop_work=abort||timed_out||writer_fault||pipeline_error;
    assign active=state!=IDLE;assign fault=state>=FAILED;
    assign cmd_ready=rst_n&&state==IDLE&&!abort&&!writer_busy&&!writer_fault&&!pipeline_error;
    assign epoch=epoch_q;assign destination_generation=generation_q;
    assign channels=channels_q;assign height=height_q;assign width=width_q;
    assign order_config=rst_n&&state==CONFIG&&!stop_work;
    assign writer_command=rst_n&&state==ISSUE&&!stop_work;
    assign writer_address=block_address[31:0];assign writer_words=block_words[13:0];
    wire within_block=accepted_words<word_base+block_words;
    assign writer_valid=rst_n&&state==WRITE_WAIT&&packed_valid&&within_block&&!bad_packed&&!stop_work;
    assign packed_ready=rst_n&&state==WRITE_WAIT&&within_block&&!stop_work&&(bad_packed ? 1'b1 : writer_ready);
    assign writer_epoch=epoch_q;assign writer_index=packed_index-word_base[12:0];
    assign writer_last=accepted_words+1==word_base+block_words;assign writer_data=packed_data;
    assign semantic_cancel=rst_n&&(fault||running&&stop_work);
    assign writer_cancel=rst_n&&(state==FAILED||running&&stop_work);
    assign writer_clear_fault=rst_n&&state==CLEAR&&!abort;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;epoch_q<=0;generation_q<=0;address_q<=0;timeout_q<=0;elapsed<=0;
            channels_q<=0;channel_base<=0;full_height_q<=0;width_q<=0;first_row_q<=0;height_q<=0;xwords_q<=0;
            total_words<=0;word_base<=0;accepted_words<=0;order_finished<=0;fault_code<=0;done<=0;tile_committed<=0;
        end else begin
            done<=0;
            if(running)begin if(elapsed!=32'hffffffff)elapsed<=elapsed+1;if(order_done)order_finished<=1;end
            if(running&&stop_work)begin state<=FAILED;tile_committed<=0;fault_code<=abort ? 2 : timed_out ? 3 : writer_fault ? 4 : 5;end
            else case(state)
                IDLE:if(writer_fault)begin state<=FAILED;tile_committed<=0;fault_code<=4;end
                    else if(cmd_valid&&cmd_ready)begin
                        tile_committed<=0;elapsed<=0;fault_code<=0;
                        if(!command_good)begin state<=FAILED;fault_code<=1;end
                        else begin epoch_q<=cmd_epoch;generation_q<=cmd_destination_generation;address_q<=cmd_destination_address;
                            timeout_q<=cmd_timeout_cycles;channels_q<=cmd_channels;channel_base<=0;full_height_q<=cmd_full_height;
                            width_q<=cmd_width;first_row_q<=cmd_first_row;height_q<=cmd_height;xwords_q<=cfg_xwords[5:0];
                            total_words<=cfg_total[13:0];word_base<=0;accepted_words<=0;order_finished<=0;state<=CONFIG;end
                    end
                CONFIG:if(order_config&&order_config_ready)state<=ISSUE;
                ISSUE:if(writer_command&&writer_command_ready)state<=WRITE_WAIT;
                WRITE_WAIT:begin
                    if(packed_valid&&packed_ready)begin
                        if(bad_packed)begin state<=FAILED;fault_code<=6;end
                        else accepted_words<=accepted_words+1;
                    end
                    if(writer_done)begin
                        if(accepted_words!=word_base+block_words)begin state<=FAILED;fault_code<=7;end
                        else if(word_base+block_words==total_words)state<=FINISH;
                        else state<=NEXT_BLOCK;
                    end
                end
                NEXT_BLOCK:begin word_base<=word_base+block_words;channel_base<=channel_base+32;state<=ISSUE;end
                FINISH:if(order_finished&&!writer_busy)begin done<=1;tile_committed<=1;state<=IDLE;end
                FAILED:if(recover&&!abort&&!writer_busy)state<=CLEAR;
                CLEAR:if(abort)state<=FAILED;else state<=RECOVER_WAIT;
                RECOVER_WAIT:if(abort)state<=FAILED;else if(!writer_busy&&!writer_fault&&!pipeline_error)begin state<=IDLE;fault_code<=0;end
                default:begin state<=FAILED;tile_committed<=0;fault_code<=8;end
            endcase
        end
    end
endmodule
`default_nettype wire
