`default_nettype none
// Private metadata codec between contiguous native-stream DDR and addressed
// feature-bank/packer order. No payload buffer: normal source must hold while
// stalled. On semantic abort the external AXI adapter must separately drain;
// this module never resets or abandons AXI transactions.
(* use_dsp="no" *)
module z100_native_stream_order (
    input wire clk,rst_n,cancel,
    input wire cfg_valid,output wire cfg_ready,
    input wire [31:0] cfg_epoch,input wire cfg_write_order,
    input wire [10:0] cfg_channels,input wire [9:0] cfg_height,cfg_width,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,input wire [12:0] in_index,in_address,
    input wire in_last,input wire [511:0] in_data,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,output wire [12:0] out_index,out_address,
    output wire out_last,output wire [511:0] out_data,
    output reg active,output reg done,output reg error_valid,output reg [1:0] error_code
);
    reg [31:0] epoch_q;
    reg mode_q;
    reg [10:0] channels_q,channel_base_q;
    reg [9:0] height_q,row_q;
    reg [6:0] xwords_q;
    reg [5:0] xword_q;
    reg [3:0] subgroup_q;
    reg [13:0] total_words_q,sequence_q;
    // periph_flat_v3: (1) cfg geometry is computed by a 3-stage pipeline from
    // registered copies (cc_*) of the cfg inputs; cfg_ready additionally needs
    // the inputs stable for four cycles so the registered verdict matches the
    // presented cfg (same scheme as z100_native_output_packer_v13).
    // (2) address_calc is tracked incrementally in registers: lin_q is the
    // address at subgroup 0 and addr_q = lin_q + subgroup_q*H*XW. Values are
    // identical to the old product for every accepted configuration.
    reg [10:0] cc_channels;reg [9:0] cc_height,cc_width;
    reg same_p1,same_p2,same_p3;
    reg [8:0] s1_g4;reg [6:0] s1_xw;
    reg [18:0] s2_gh;reg [16:0] s2_hxw;reg [6:0] s2_xw;
    reg [25:0] s3_words;reg [16:0] s3_hxw;reg [19:0] s3_hxw7;reg [6:0] s3_xw;
    wire cfg_same_now=cfg_channels==cc_channels&&cfg_height==cc_height&&cfg_width==cc_width;
    always @(posedge clk)begin
        cc_channels<=cfg_channels;cc_height<=cfg_height;cc_width<=cfg_width;
        s1_g4<=({1'b0,cc_channels}+12'd3)>>2;s1_xw<=({1'b0,cc_width}+11'd15)>>4;
        s2_gh<=s1_g4*cc_height;s2_hxw<=cc_height*s1_xw;s2_xw<=s1_xw;
        s3_words<=s2_gh*s2_xw;s3_hxw<=s2_hxw;s3_hxw7<=s2_hxw*3'd7;s3_xw<=s2_xw;
        if(!rst_n||cancel)begin same_p1<=0;same_p2<=0;same_p3<=0;end
        else begin same_p1<=cfg_same_now;same_p2<=same_p1;same_p3<=same_p2;end
    end
    wire cfg_stable=cfg_same_now&&same_p1&&same_p2&&same_p3;
    wire [31:0] cfg_words={6'd0,s3_words};
    wire cfg_good=cfg_epoch!=0&&cc_channels!=0&&cc_channels<=1024&&cc_height!=0&&cc_height<=640&&
                  cc_width!=0&&cc_width<=640&&cfg_words!=0&&cfg_words<=8192;
    wire [10:0] channels_left=channels_q-channel_base_q;
    wire [3:0] subgroups=channels_left>=32 ? 4'd8 : (channels_left+3)>>2;
    reg [16:0] hxw_q;reg [19:0] hxw7_q;
    reg [31:0] lin_q,addr_q;
    wire [31:0] address_calc=addr_q;
    wire expected_last=sequence_q+1==total_words_q;
    wire metadata_good=in_epoch==epoch_q&&in_last==expected_last&&
                     (mode_q ? in_address==address_calc : in_index==sequence_q);
    wire enable=rst_n&&!cancel;
    assign cfg_ready=enable&&!active&&cfg_stable;
    assign in_ready=enable&&active&&(metadata_good ? out_ready : 1'b1);
    assign out_valid=enable&&active&&in_valid&&metadata_good;
    assign out_epoch=epoch_q;assign out_index=sequence_q[12:0];assign out_address=address_calc[12:0];
    assign out_last=expected_last;assign out_data=in_data;
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            epoch_q<=0;mode_q<=0;channels_q<=0;height_q<=0;xwords_q<=0;
            channel_base_q<=0;row_q<=0;xword_q<=0;subgroup_q<=0;total_words_q<=0;sequence_q<=0;
            active<=0;done<=0;error_valid<=0;error_code<=0;
            hxw_q<=0;hxw7_q<=0;lin_q<=0;addr_q<=0;
        end else begin
            done<=0;error_valid<=0;error_code<=0;
            if(cfg_valid&&cfg_ready)begin
                if(!cfg_good)begin active<=0;error_valid<=1;error_code<=1;end
                else begin
                    active<=1;epoch_q<=cfg_epoch;mode_q<=cfg_write_order;
                    channels_q<=cfg_channels;height_q<=cfg_height;xwords_q<=s3_xw;
                    total_words_q<=cfg_words[13:0];sequence_q<=0;channel_base_q<=0;row_q<=0;xword_q<=0;subgroup_q<=0;
                    hxw_q<=s3_hxw;hxw7_q<=s3_hxw7;lin_q<=0;addr_q<=0;
                end
            end else if(in_valid&&in_ready)begin
                if(!metadata_good)begin active<=0;error_valid<=1;error_code<=2;end
                else if(expected_last)begin active<=0;done<=1;end
                else begin
                    sequence_q<=sequence_q+1;
                    if(subgroup_q+1==subgroups)begin
                        subgroup_q<=0;
                        if(xword_q+1==xwords_q)begin
                            xword_q<=0;
                            if(row_q+1==height_q)begin row_q<=0;channel_base_q<=channel_base_q+32;
                                lin_q<=lin_q+32'd1+{12'd0,hxw7_q};addr_q<=lin_q+32'd1+{12'd0,hxw7_q};end
                            else begin row_q<=row_q+1;lin_q<=lin_q+32'd1;addr_q<=lin_q+32'd1;end
                        end else begin xword_q<=xword_q+1;lin_q<=lin_q+32'd1;addr_q<=lin_q+32'd1;end
                    end else begin subgroup_q<=subgroup_q+1;addr_q<=addr_q+{15'd0,hxw_q};end
                end
            end
        end
    end
endmodule
`default_nettype wire
