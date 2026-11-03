`default_nettype none
// Private Conv tile RUN sequencer. Parameter-group -> all output rows -> next
// group matches the existing packer order. Completion requires an external
// successful write/publication acknowledgement, not merely row submission.
// Cancel invalidates private work; external AXI owners must still drain. This
// module never resets DMA/AXI or releases a graph source lease on its own.
(* use_dsp="no" *)
module z100_native_conv_tile_control_v2 #(parameter integer SITES=20)(
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
    localparam IDLE=0,PACK=1,PARAM=2,PARAM_WAIT=3,ROW=4,ROW_WAIT=5,PUBLISH=6,FAILED=7,CHECK=8;
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
    reg row_arm_q;
    // periph_flat_v3: the accepted command is latched (L_*) and command_ok is
    // evaluated over a 5-stage register pipeline (CHECK state, ck_cnt), then
    // the old accept/fail(1) decision is taken from the registered verdict.
    // Arithmetic widths cover every port bit pattern (see
    // docs/z100_tile_control_arithmetic_bounds_20261030.md); terms that wrap in
    // the old 64-bit form only do so when another ANDed term is already false.
    reg[31:0] L_epoch,L_token,L_tag,L_job;
    reg[15:0] L_pf;
    reg[10:0] L_cin,L_cout;
    reg[9:0] L_ih,L_iw,L_iy,L_ir,L_oh,L_ow,L_oy,L_or;
    reg[1:0] L_k,L_s,L_p;
    reg[2:0] ck_cnt;
    // stage A
    reg[6:0] a_xw,a_og32,a_ox16;
    reg[9:0] a_cg,a_og4;
    reg[3:0] a_kk;
    reg[5:0] a_seg;
    reg signed[13:0] a_nx,a_ny;
    reg signed[15:0] a_ft,a_lt;
    reg a_ok;
    // stage B
    reg[16:0] b_plane,b_runs_p;
    reg[13:0] b_groups;
    reg[19:0] b_words_p;
    reg b_ok;
    // stage C
    reg[26:0] c_bank,c_words;
    reg[22:0] c_runs;
    reg[19:0] c_tag_step;
    reg c_ok;
    // stage D
    reg[36:0] d_rg;
    reg d_ok;
    // stage E
    reg e_ok;
    wire ledger_ok=(L_epoch>ledger_epoch||(L_epoch==ledger_epoch&&L_job>ledger_tag));
    wire signed[15:0] nf=a_ft<0?16'sd0:a_ft;
    wire signed[15:0] nl=a_lt>=$signed({6'd0,L_ih})?$signed({6'd0,L_ih})-16'sd1:a_lt;
    wire[10:0] iy_end={1'b0,L_iy}+{1'b0,L_ir};
    always @(posedge clk)begin
        a_xw<=({1'b0,L_iw}+11'd15)>>4;
        a_cg<=({1'b0,L_cin}+12'd3)>>2;
        a_kk<=L_k*L_k;
        a_seg<=({1'b0,L_ow}+SITES-1)/SITES;
        a_og32<=({1'b0,L_cout}+12'd31)>>5;
        a_og4<=({1'b0,L_cout}+12'd3)>>2;
        a_ox16<=({1'b0,L_ow}+11'd15)>>4;
        a_nx<=$signed({4'd0,L_iw})+$signed({11'd0,L_p,1'b0})-$signed({12'd0,L_k});
        a_ny<=$signed({4'd0,L_ih})+$signed({11'd0,L_p,1'b0})-$signed({12'd0,L_k});
        a_ft<=$signed({6'd0,L_oy})*$signed({14'd0,L_s})-$signed({14'd0,L_p});
        a_lt<=($signed({6'd0,L_oy})+$signed({6'd0,L_or})-16'sd1)*$signed({14'd0,L_s})-$signed({14'd0,L_p})+$signed({14'd0,L_k})-16'sd1;
        a_ok<=L_epoch!=0&&L_token!=0&&L_job!=0&&ledger_ok&&
            L_cin>=1&&L_cin<=1024&&L_cout>=1&&L_cout<=1024&&
            L_ih>=1&&L_ih<=640&&L_iw>=1&&L_iw<=640&&
            L_oh>=1&&L_oh<=640&&L_ow>=1&&L_ow<=640&&
            L_ir>=1&&L_or>=1&&
            iy_end<={1'b0,L_ih}&&
            {1'b0,L_oy}+{1'b0,L_or}<={1'b0,L_oh}&&
            (L_k==1||L_k==3)&&(L_s==1||L_s==2)&&L_p<=1;
        b_plane<=L_ir*a_xw;
        b_groups<=a_cg*a_kk;
        b_runs_p<=a_og32*L_or;
        b_words_p<=a_og4*L_or;
        b_ok<=a_ok&&a_nx>=0&&a_ny>=0&&
            (L_s==2?(a_nx>>>1)+14'sd1:a_nx+14'sd1)==$signed({4'd0,L_ow})&&
            (L_s==2?(a_ny>>>1)+14'sd1:a_ny+14'sd1)==$signed({4'd0,L_oh})&&
            $signed({6'd0,L_iy})<=nf&&nl>=0&&$signed({5'd0,iy_end})>nl&&
            {1'b0,L_pf}+{10'd0,a_og32}-17'd1<=17'd65535;
        c_bank<=a_cg*b_plane;
        c_runs<=b_runs_p*a_seg;
        c_words<=b_words_p*a_ox16;
        c_tag_step<=a_seg*b_groups;
        c_ok<=b_ok&&b_groups>=1&&b_groups<=1024;
        d_rg<=c_runs*b_groups;
        d_ok<=c_ok&&c_bank>=1&&c_bank<=4096&&c_words>=1&&c_words<=8192&&
            {1'b0,L_token}+{10'd0,c_runs}-33'd1<=33'h0ffffffff;
        e_ok<=d_ok&&{5'd0,L_tag}+d_rg-37'd1<=37'h00ffffffff;
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
    assign row_valid=rst_n&&state==ROW&&row_arm_q&&!cancel&&!fault;
    assign row_token_base=token_q;assign row_tag_base=tag_q;
    assign row_channels=cin_q;assign row_input_width=iw_q;assign row_output_width=ow_q;
    assign row_kernel=k_q;assign row_stride=s_q;assign row_padding=p_q;
    assign row_lanes=({1'b0,cout_q}-{1'b0,group_q,5'd0}>=32)?6'd32:cout_q-group_q*32;
    assign row_bank_words=bank_words_q;assign row_plane_stride=plane_q;
    assign row_done_ready=rst_n&&state==ROW_WAIT&&!cancel&&!fault;
    assign publish_ready=rst_n&&state==PUBLISH&&!cancel&&!fault;
    // periph_flat_v3: row_ky_bases/row_y_valid are registered (same function
    // of the same *_q registers). row_valid waits one cycle after entering
    // ROW (row_arm_q) so the registered values always match row_q.
    integer ky;reg signed[31:0] sy,local_y;
    reg[41:0] ky_bases_next;reg[2:0] y_valid_next;
    always @*begin
        ky_bases_next=0;y_valid_next=0;sy=0;local_y=0;
        for(ky=0;ky<3;ky=ky+1)if(ky<k_q)begin
            sy=($signed({22'd0,oy_q})+$signed({22'd0,row_q}))*$signed({30'd0,s_q})-$signed({30'd0,p_q})+ky;
            local_y=sy-$signed({22'd0,iy_q});
            if(sy>=0&&sy<$signed({22'd0,ih_q}))begin
                y_valid_next[ky]=1;ky_bases_next[ky*14+:14]=local_y*xwords_q;
            end
        end
    end
    always @(posedge clk)begin
        row_ky_bases<=ky_bases_next;row_y_valid<=y_valid_next;
        row_arm_q<=rst_n&&state==ROW;
    end
    task fail(input[3:0] code);begin state<=FAILED;fault<=1;fault_code<=code;end endtask
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;done<=0;fault<=0;fault_code<=0;job_tag_q<=0;ledger_epoch<=0;ledger_tag<=0;epoch_q<=0;token_q<=0;tag_q<=0;
            tile_token_q<=0;tile_tag_q<=0;tag_step_q<=0;parameter_first_q<=0;cin_q<=0;cout_q<=0;
            ih_q<=0;iw_q<=0;iy_q<=0;ir_q<=0;ow_q<=0;oy_q<=0;rows_q<=0;row_q<=0;
            k_q<=0;s_q<=0;p_q<=0;group_q<=0;group_count_q<=0;segments_q<=0;bank_words_q<=0;plane_q<=0;xwords_q<=0;
            ck_cnt<=0;
        end else begin
            done<=0;
            if(state==FAILED)begin
                if(recover&&recovery_drained&&!cancel)begin state<=IDLE;fault<=0;fault_code<=0;end
            end else if(cancel)fail(4'd2);
            else if((parameter_done_valid&&state!=PARAM_WAIT)||(row_done_valid&&state!=ROW_WAIT)||(publish_valid&&state!=PUBLISH))fail(4'd3);
            else case(state)
                IDLE:if(cmd_valid&&cmd_ready)begin
                    L_epoch<=cmd_epoch;L_token<=cmd_token_base;L_tag<=cmd_tag_base;L_job<=cmd_job_tag;
                    L_pf<=cmd_parameter_first;L_cin<=cmd_input_channels;L_cout<=cmd_output_channels;
                    L_ih<=cmd_input_height;L_iw<=cmd_input_width;L_iy<=cmd_input_y;L_ir<=cmd_input_rows;
                    L_oh<=cmd_output_height;L_ow<=cmd_output_width;L_oy<=cmd_output_y;L_or<=cmd_output_rows;
                    L_k<=cmd_kernel;L_s<=cmd_stride;L_p<=cmd_padding;
                    ck_cnt<=0;state<=CHECK;
                end
                CHECK:begin
                    ck_cnt<=ck_cnt+3'd1;
                    if(ck_cnt==3'd5)begin
                        if(!e_ok)fail(4'd1);
                        else begin
                            epoch_q<=L_epoch;token_q<=L_token;tag_q<=L_tag;
                            job_tag_q<=L_job;ledger_epoch<=L_epoch;ledger_tag<=L_job;
                            tile_token_q<=L_token;tile_tag_q<=L_tag;tag_step_q<={12'd0,c_tag_step};
                            parameter_first_q<=L_pf;cin_q<=L_cin;cout_q<=L_cout;
                            ih_q<=L_ih;iw_q<=L_iw;iy_q<=L_iy;ir_q<=L_ir;
                            ow_q<=L_ow;oy_q<=L_oy;rows_q<=L_or;
                            k_q<=L_k;s_q<=L_s;p_q<=L_p;
                            group_q<=0;row_q<=0;group_count_q<=a_og32[5:0];segments_q<=a_seg;
                            bank_words_q<=c_bank[13:0];plane_q<=b_plane[13:0];xwords_q<=a_xw[5:0];state<=PACK;
                        end
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
