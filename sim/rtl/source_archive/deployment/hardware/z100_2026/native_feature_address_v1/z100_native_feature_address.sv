`default_nettype none
// Checked native stream index -> canonical channel4,row,xword RAM address.
// Payload passes through without storage; state advances only on accepted word.
(* use_dsp="no" *)
module z100_native_feature_address (
    input wire clk,rst_n,cancel,clear_fault,
    input wire begin_valid,output wire begin_ready,input wire [31:0] begin_epoch,
    input wire [9:0] channels,height,width,
    input wire in_valid,output wire in_ready,input wire [31:0] in_epoch,
    input wire [11:0] in_native_word,input wire in_last,input wire [511:0] in_data,
    output wire out_valid,input wire out_ready,output wire [31:0] out_epoch,
    output wire [12:0] out_address,output wire out_last,output wire [511:0] out_data,
    output reg active,fault,output reg [3:0] fault_code,output reg done
);
    reg [31:0] epoch_q;
    reg [12:0] count,total,stride,spatial,group_base,address_q;
    reg [7:0] cgroups,group_q;
    reg [3:0] subgroup,subgroups;
    wire [31:0] xwords=({22'd0,width}+15)>>4;
    wire [31:0] plane=height*xwords;
    wire [31:0] words=(channels>>2)*plane;
    wire bad_config=begin_epoch==0||channels==0||channels>512||channels[2:0]!=0||height==0||height>640||
        width==0||width>640||words==0||words>4096;
    wire last_expected=count+1==total;
    wire metadata_good=in_epoch==epoch_q&&{1'b0,in_native_word}==count&&in_last==last_expected;
    assign begin_ready=rst_n&&!active&&!fault&&!cancel;
    assign in_ready=rst_n&&active&&!fault&&!cancel&&(metadata_good ? out_ready : 1'b1);
    assign out_valid=rst_n&&active&&!fault&&!cancel&&in_valid&&metadata_good;
    assign out_epoch=epoch_q;assign out_address=address_q;assign out_last=last_expected;assign out_data=in_data;
    always @(posedge clk)begin
        if(!rst_n)begin
            active<=0;fault<=0;fault_code<=0;done<=0;epoch_q<=0;count<=0;total<=0;stride<=0;spatial<=0;
            group_base<=0;address_q<=0;cgroups<=0;group_q<=0;subgroup<=0;subgroups<=0;
        end else begin
            done<=0;
            if(cancel)begin active<=0;fault<=1;fault_code<=2;end
            else if(fault)begin if(clear_fault)begin fault<=0;fault_code<=0;end end
            else if(begin_valid&&begin_ready)begin
                if(bad_config)begin fault<=1;fault_code<=1;end
                else begin active<=1;epoch_q<=begin_epoch;count<=0;total<=words[12:0];stride<=plane[12:0];
                    spatial<=0;group_base<=0;address_q<=0;cgroups<=channels>>2;group_q<=0;subgroup<=0;
                    subgroups<=channels>=32 ? 8 : channels>>2;end
            end else if(in_valid&&in_ready)begin
                if(!metadata_good)begin active<=0;fault<=1;fault_code<=3;end
                else if(last_expected)begin active<=0;done<=1;end
                else begin
                    count<=count+1;
                    if(subgroup+1<subgroups)begin subgroup<=subgroup+1;address_q<=address_q+stride;end
                    else if(spatial+1<stride)begin subgroup<=0;spatial<=spatial+1;address_q<=group_base+spatial+1;end
                    else begin subgroup<=0;spatial<=0;group_q<=group_q+8;group_base<=address_q+1;address_q<=address_q+1;
                        subgroups<=cgroups-(group_q+8)>=8 ? 8 : cgroups-(group_q+8);end
                end
            end
        end
    end
endmodule
`default_nettype wire
