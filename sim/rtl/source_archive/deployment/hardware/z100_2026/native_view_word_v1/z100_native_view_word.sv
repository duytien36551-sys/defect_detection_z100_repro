`default_nettype none
// Private one-word view transform:4channels x16pixels, exact unary LUT,
// in-word nearest1/2/4, strict channel/x tails. No tensor payload copy RAM.
//64 independent asynchronous LUT reads use replicated distributed memory;
// the active256-byte table loads in32 contiguous64-bit handshakes.
(* use_dsp="no" *)
module z100_native_view_word (
    input wire clk,rst_n,cancel,
    input wire cfg_begin,output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,input wire [5:0] cfg_lut_id,
    input wire cfg_word_valid,output wire cfg_word_ready,input wire [63:0] cfg_data,
    input wire cfg_commit,output wire cfg_commit_ready,
    output reg store_valid,output reg loading,output reg error_valid,output reg [2:0] error_code,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,in_token,in_table_epoch,input wire [5:0] in_lut_id,
    input wire [3:0] in_source_first_x,input wire [1:0] in_nearest_shift,
    input wire [2:0] in_channels,input wire [4:0] in_x_count,
    input wire in_last,input wire [511:0] in_data,
    output wire out_valid,input wire out_ready,
    output reg [31:0] out_epoch,out_token,output reg out_last,output reg [511:0] out_data
);
    reg [31:0] epoch_q;
    reg [5:0] lut_id_q,count;
    reg result_valid;
    wire enabled=rst_n&&!cancel;
    wire slot=!result_valid||out_ready;
    wire control_busy=cfg_begin||cfg_word_valid||cfg_commit;
    assign cfg_begin_ready=enabled&&!loading&&slot&&!cfg_word_valid&&!cfg_commit;
    assign cfg_word_ready=enabled&&loading&&!cfg_begin&&!cfg_commit;
    assign cfg_commit_ready=enabled&&loading&&!cfg_begin&&!cfg_word_valid;
    assign in_ready=enabled&&store_valid&&!loading&&!control_busy&&slot;
    assign out_valid=enabled&&result_valid;
    wire [5:0] last_source_x={2'd0,in_source_first_x}+(({1'b0,in_x_count}-1)>>in_nearest_shift);
    wire metadata_good=in_epoch!=0&&in_token!=0&&in_table_epoch==epoch_q&&in_lut_id==lut_id_q&&
        in_channels>0&&in_channels<=4&&in_x_count>0&&in_x_count<=16&&in_nearest_shift<=2&&last_source_x<16;
    wire write_fire=cfg_word_valid&&cfg_word_ready&&count<32;
    wire [511:0] lookup;
    genvar lane,bank;
    generate for(lane=0;lane<64;lane=lane+1)begin:gen_lane
        wire [4:0] source_x={1'b0,in_source_first_x}+((lane%16)>>in_nearest_shift);
        wire [7:0] source_value=in_data[(lane/16)*128+source_x*8+:8];
        wire [7:0] address=source_value^8'h80;
        wire [63:0] bank_values;
        for(bank=0;bank<8;bank=bank+1)begin:gen_bank
            (* ram_style="distributed" *)reg [7:0] table_mem[0:31];
            always @(posedge clk)if(write_fire)table_mem[count[4:0]]<=cfg_data[bank*8+:8];
            assign bank_values[bank*8+:8]=table_mem[address[7:3]];
        end
        assign lookup[lane*8+:8]=((lane/16)<in_channels&&(lane%16)<in_x_count) ? bank_values[address[2:0]*8+:8] : 8'd0;
    end endgenerate
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            epoch_q<=0;lut_id_q<=0;count<=0;store_valid<=0;loading<=0;error_valid<=0;error_code<=0;
            result_valid<=0;out_epoch<=0;out_token<=0;out_last<=0;out_data<=0;
        end else begin
            error_valid<=0;error_code<=0;
            if(slot)begin
                result_valid<=in_valid&&in_ready&&metadata_good;
                if(in_valid&&in_ready&&metadata_good)begin out_epoch<=in_epoch;out_token<=in_token;out_last<=in_last;out_data<=lookup;end
            end
            if(in_valid&&in_ready&&!metadata_good)begin error_valid<=1;error_code<=4;end
            if(cfg_begin&&cfg_begin_ready)begin
                store_valid<=0;count<=0;
                if(cfg_epoch==0)begin loading<=0;error_valid<=1;error_code<=1;end
                else begin epoch_q<=cfg_epoch;lut_id_q<=cfg_lut_id;loading<=1;end
            end else if(cfg_word_valid&&cfg_word_ready)begin
                if(count>=32)begin loading<=0;store_valid<=0;error_valid<=1;error_code<=3;end
                else count<=count+1;
            end else if(cfg_commit&&cfg_commit_ready)begin
                loading<=0;
                if(count!=32)begin store_valid<=0;error_valid<=1;error_code<=2;end
                else store_valid<=1;
            end
        end
    end
endmodule
`default_nettype wire
