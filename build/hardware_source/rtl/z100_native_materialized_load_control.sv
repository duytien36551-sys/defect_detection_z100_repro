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
    localparam IDLE=0,CONFIG=1,ISSUE=2,READ_WAIT=3,NEXT_BLOCK=4,ORDER_WAIT=5,COMMIT=6,COMPLETE=7,FAILED=8,CLEAR=9,RECOVER_WAIT=10,CHECK=11;
    reg [3:0] state;
    reg [31:0] epoch_q,generation_q,address_q,timeout_q,elapsed_q;
    reg [10:0] channels_q,channel_base_q;
    reg [9:0] full_height_q,width_q,first_row_q,height_q;
    reg [5:0] xwords_q;reg [13:0] total_words_q,word_base_q;
    reg feature_configured,order_configured,order_finished;
    wire running=state>=CONFIG&&state<=COMPLETE;
    // periph_flat_v3: (1) the accepted command is latched (L_*) and
    // command_good is evaluated over a 5-stage register pipeline in CHECK;
    // the old accept/fail(1) decision is then taken from the verdict.
    // (2) block words/offset/address are computed by a 3-stage register
    // pipeline from the *_q registers; ISSUE acts only after issue_cnt==3
    // (inputs change only on accept and NEXT_BLOCK). (3) timed_out is
    // registered (timeout detected one cycle later). All widths are exact
    // for every port bit pattern (no wrap in the old 32/33-bit forms).
    wire live=running||state==CHECK;
    reg [31:0] L_epoch,L_gen,L_addr,L_timeout;
    reg [10:0] L_ch;reg [9:0] L_fh,L_w,L_fr,L_h;reg L_committed;
    reg [2:0] ck_cnt;
    reg [8:0] k1_g4;reg [6:0] k1_xw;reg k1_ok;
    reg [18:0] k2_gh,k2_gf;reg k2_ok;
    reg [25:0] k3_total,k3_full;reg k3_ok;
    reg [32:0] k4_fend;reg k4_ok;
    reg k5_good;
    always @(posedge clk)begin
        k1_g4<=({1'b0,L_ch}+12'd3)>>2;
        k1_xw<=({1'b0,L_w}+11'd15)>>4;
        k1_ok<=L_epoch!=0&&L_gen!=0&&L_addr[5:0]==0&&L_timeout!=0&&
            L_ch>0&&L_ch<=1024&&L_w>0&&L_w<=640&&L_fh>0&&L_fh<=640&&
            L_h>0&&L_h<=640&&({1'b0,L_fr}+{1'b0,L_h})<={1'b0,L_fh}&&L_committed;
        k2_gh<=k1_g4*L_h;k2_gf<=k1_g4*L_fh;k2_ok<=k1_ok;
        k3_total<=k2_gh*k1_xw;k3_full<=k2_gf*k1_xw;k3_ok<=k2_ok;
        k4_fend<={1'b0,L_addr}+{1'b0,k3_full,6'd0};
        k4_ok<=k3_ok&&k3_total>0&&k3_total<=8192;
        k5_good<=k4_ok&&k4_fend<=33'h100000000;
    end
    wire [11:0] remaining_channels={1'b0,channels_q}-{1'b0,channel_base_q};
    wire [3:0] subgroups=remaining_channels>=32 ? 4'd8 : ((remaining_channels+3)>>2);
    reg [3:0] b1_sub;reg [15:0] b1_hx,b1_fx;reg [18:0] b1_cf;
    reg [18:0] b2_bw;reg [25:0] b2_off;
    reg [18:0] b3_bw;reg [32:0] b3_addr;
    reg [1:0] issue_cnt;
    always @(posedge clk)begin
        b1_sub<=subgroups;b1_hx<=height_q*xwords_q;b1_fx<=first_row_q*xwords_q;
        b1_cf<=(channel_base_q>>2)*full_height_q;
        b2_bw<=b1_sub*b1_hx;b2_off<=b1_cf*xwords_q+b1_fx*b1_sub;
        b3_bw<=b2_bw;b3_addr<={1'b0,address_q}+{1'b0,b2_off,6'd0};
    end
    wire issue_ready=state==ISSUE&&issue_cnt==2'd3;
    wire [31:0] current_block_words={13'd0,b3_bw};
    wire [32:0] block_address=b3_addr;
    reg timed_out_q;
    wire timed_out=timed_out_q;
    wire stop_work=abort||timed_out||reader_fault||pipeline_error;
    // periph_flat_v3 (census 20261030T100207Z): feature_begin/feature_commit
    // no longer include `abort`. abort is the backend-wide cancel (any fault
    // -> prefetch child_cancel), and abort -> begin -> feature store
    // arbitration -> begin_ready -> this FSM was a 29-31 level loop. Both
    // users (Conv backend: abort=datapath_cancel; Pool backend:
    // abort=abort_work=aux_cancel) feed the same signal into the compute core
    // cancel, and every core register touched by begin/commit is reset by
    // that cancel; the store's command_admission/fire_ready contain !cancel.
    // In this FSM abort has priority over the CONFIG/COMMIT case, so the
    // begin/commit handshake result is ignored in an abort cycle.
    wire stop_local=timed_out||reader_fault||pipeline_error;
    assign active=state!=IDLE;
    assign fault=state==FAILED||state==CLEAR||state==RECOVER_WAIT;
    assign cmd_ready=rst_n&&state==IDLE&&!abort&&!reader_busy&&!reader_fault&&!pipeline_error;
    assign epoch=epoch_q;assign source_generation=generation_q;assign channels=channels_q;assign height=height_q;assign width=width_q;
    assign total_words=total_words_q;assign block_words=current_block_words[13:0];assign block_word_base=word_base_q;
    assign reader_address=block_address[31:0];
    assign feature_begin=rst_n&&state==CONFIG&&!feature_configured&&!stop_local;
    assign order_config=rst_n&&state==CONFIG&&!order_configured&&!stop_work;
    assign reader_command=rst_n&&issue_ready&&!stop_work;
    assign feature_commit=rst_n&&state==COMMIT&&!stop_local;
    assign semantic_cancel=rst_n&&(fault||live&&stop_work);
    assign reader_cancel=rst_n&&(state==FAILED||live&&stop_work);
    assign reader_clear_fault=rst_n&&state==CLEAR&&!abort;
    always @(posedge clk)begin
        if(!rst_n)begin timed_out_q<=0;issue_cnt<=0;end  // ck_cnt is owned by the FSM block (single driver)
        else begin
            timed_out_q<=running&&elapsed_q>=timeout_q;
            issue_cnt<=(state!=ISSUE)?2'd0:(issue_cnt==2'd3)?2'd3:issue_cnt+2'd1;
        end
    end
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;fault_code<=0;done<=0;result_committed<=0;
            epoch_q<=0;generation_q<=0;address_q<=0;timeout_q<=0;elapsed_q<=0;channels_q<=0;channel_base_q<=0;
            full_height_q<=0;width_q<=0;first_row_q<=0;height_q<=0;xwords_q<=0;total_words_q<=0;word_base_q<=0;
            feature_configured<=0;order_configured<=0;order_finished<=0;
        end else begin
            done<=0;
            if(running)begin elapsed_q<=elapsed_q+1;if(order_done)order_finished<=1;end
            if(live&&stop_work)begin
                state<=FAILED;result_committed<=0;fault_code<=abort ? 2 : timed_out ? 3 : reader_fault ? 4 : 5;
            end else case(state)
                IDLE:if(reader_fault)begin state<=FAILED;fault_code<=4;result_committed<=0;end
                    else if(cmd_valid&&cmd_ready)begin
                        result_committed<=0;elapsed_q<=0;fault_code<=0;
                        L_epoch<=cmd_epoch;L_gen<=cmd_source_generation;L_addr<=cmd_source_address;L_timeout<=cmd_timeout_cycles;
                        L_ch<=cmd_channels;L_fh<=cmd_full_height;L_w<=cmd_width;L_fr<=cmd_first_row;L_h<=cmd_height;
                        L_committed<=cmd_source_committed&&cmd_source_is_materialized;
                        ck_cnt<=0;state<=CHECK;
                    end
                CHECK:begin
                    ck_cnt<=ck_cnt+3'd1;
                    if(ck_cnt==3'd5)begin
                        if(!k5_good)begin state<=FAILED;fault_code<=1;end
                        else begin
                            epoch_q<=L_epoch;generation_q<=L_gen;address_q<=L_addr;timeout_q<=L_timeout;
                            channels_q<=L_ch;full_height_q<=L_fh;width_q<=L_w;first_row_q<=L_fr;height_q<=L_h;
                            xwords_q<=k1_xw[5:0];total_words_q<=k3_total[13:0];word_base_q<=0;channel_base_q<=0;
                            feature_configured<=0;order_configured<=0;order_finished<=0;elapsed_q<=0;state<=CONFIG;
                        end
                    end
                end
                CONFIG:begin
                    if(feature_begin&&feature_begin_ready)feature_configured<=1;
                    if(order_config&&order_config_ready)order_configured<=1;
                    if((feature_configured||feature_begin_ready)&&(order_configured||order_config_ready))state<=ISSUE;
                end
                ISSUE:if(!issue_ready);
                    else if(block_address>33'h0ffffffff||current_block_words==0||current_block_words>8192||word_base_q+current_block_words>total_words_q)begin state<=FAILED;fault_code<=6;end
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
