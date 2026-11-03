`default_nettype none
// Private metadata codec between contiguous native-stream DDR and addressed
// feature-bank/packer order. No payload buffer: normal source must hold while
// stalled. On semantic abort the external AXI adapter must separately drain;
// this module never resets or abandons AXI transactions.
(* use_dsp="no" *)
module so_old (
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
    wire [31:0] cfg_words=((({21'd0,cfg_channels}+3)>>2)*cfg_height)*(({22'd0,cfg_width}+15)>>4);
    wire cfg_good=cfg_epoch!=0&&cfg_channels!=0&&cfg_channels<=1024&&cfg_height!=0&&cfg_height<=640&&
                  cfg_width!=0&&cfg_width<=640&&cfg_words!=0&&cfg_words<=8192;
    wire [10:0] channels_left=channels_q-channel_base_q;
    wire [3:0] subgroups=channels_left>=32 ? 4'd8 : (channels_left+3)>>2;
    wire [31:0] address_calc=(((channel_base_q>>2)+subgroup_q)*height_q+row_q)*xwords_q+xword_q;
    wire expected_last=sequence_q+1==total_words_q;
    wire metadata_good=in_epoch==epoch_q&&in_last==expected_last&&
                     (mode_q ? in_address==address_calc : in_index==sequence_q);
    wire enable=rst_n&&!cancel;
    assign cfg_ready=enable&&!active;
    assign in_ready=enable&&active&&(metadata_good ? out_ready : 1'b1);
    assign out_valid=enable&&active&&in_valid&&metadata_good;
    assign out_epoch=epoch_q;assign out_index=sequence_q[12:0];assign out_address=address_calc[12:0];
    assign out_last=expected_last;assign out_data=in_data;
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            epoch_q<=0;mode_q<=0;channels_q<=0;height_q<=0;xwords_q<=0;
            channel_base_q<=0;row_q<=0;xword_q<=0;subgroup_q<=0;total_words_q<=0;sequence_q<=0;
            active<=0;done<=0;error_valid<=0;error_code<=0;
        end else begin
            done<=0;error_valid<=0;error_code<=0;
            if(cfg_valid&&cfg_ready)begin
                if(!cfg_good)begin active<=0;error_valid<=1;error_code<=1;end
                else begin
                    active<=1;epoch_q<=cfg_epoch;mode_q<=cfg_write_order;
                    channels_q<=cfg_channels;height_q<=cfg_height;xwords_q<=({1'b0,cfg_width}+15)>>4;
                    total_words_q<=cfg_words[13:0];sequence_q<=0;channel_base_q<=0;row_q<=0;xword_q<=0;subgroup_q<=0;
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
                            if(row_q+1==height_q)begin row_q<=0;channel_base_q<=channel_base_q+32;end
                            else row_q<=row_q+1;
                        end else xword_q<=xword_q+1;
                    end else subgroup_q<=subgroup_q+1;
                end
            end
        end
    end
endmodule
`default_nettype wire
