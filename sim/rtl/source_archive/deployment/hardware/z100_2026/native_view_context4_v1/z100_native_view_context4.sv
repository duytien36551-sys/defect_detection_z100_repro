`default_nettype none
// Up to four exact LUT contexts for one compiled virtual node, all resident.
//32 true-dual-port1024x8 arrays supply64 synchronous reads. Configuration is
// byte-sequential while quiescent; payload is never cleared by reset/cancel.
(* use_dsp="no" *)
module z100_native_view_context4 (
    input wire clk,rst_n,cancel,
    input wire cfg_begin,output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,input wire [2:0] cfg_contexts,
    input wire cfg_word_valid,output wire cfg_word_ready,input wire [7:0] cfg_data,
    input wire cfg_commit,output wire cfg_commit_ready,
    output reg store_valid,output reg loading,output reg error_valid,output reg [2:0] error_code,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,in_token,in_table_epoch,input wire [1:0] in_context,
    input wire [3:0] in_source_first_x,input wire [1:0] in_nearest_shift,
    input wire [2:0] in_channels,input wire [4:0] in_x_count,
    input wire in_last,input wire [511:0] in_data,
    output wire out_valid,input wire out_ready,
    output reg [31:0] out_epoch,out_token,output reg out_last,output reg [511:0] out_data
);
    reg [31:0] epoch_q,rd_epoch,rd_token;
    reg [2:0] contexts_q;
    reg [10:0] count,expected_bytes;
    reg rd_valid,result_valid,rd_last;
    reg [63:0] rd_mask;
    wire enabled=rst_n&&!cancel;
    wire out_slot=!result_valid||out_ready;
    wire rd_slot=!rd_valid||out_slot;
    wire empty=!rd_valid&&!result_valid;
    wire control_busy=cfg_begin||cfg_word_valid||cfg_commit;
    assign cfg_begin_ready=enabled&&!loading&&empty&&!cfg_word_valid&&!cfg_commit;
    assign cfg_word_ready=enabled&&loading&&!cfg_begin&&!cfg_commit;
    assign cfg_commit_ready=enabled&&loading&&!cfg_begin&&!cfg_word_valid;
    assign in_ready=enabled&&store_valid&&!loading&&!control_busy&&rd_slot;
    assign out_valid=enabled&&result_valid;
    wire [5:0] last_source_x={2'd0,in_source_first_x}+(({1'b0,in_x_count}-1)>>in_nearest_shift);
    wire metadata_good=in_epoch!=0&&in_token!=0&&in_table_epoch==epoch_q&&in_context<contexts_q&&
        in_channels>0&&in_channels<=4&&in_x_count>0&&in_x_count<=16&&in_nearest_shift<=2&&last_source_x<16;
    wire write_fire=cfg_word_valid&&cfg_word_ready&&count<expected_bytes;
    wire read_fire=in_valid&&in_ready&&metadata_good;
    wire [639:0] addresses;
    wire [63:0] request_mask;
    wire [511:0] ram_result;
    genvar lane,copy;
    generate for(lane=0;lane<64;lane=lane+1)begin:gen_address
        wire [4:0] source_x={1'b0,in_source_first_x}+((lane%16)>>in_nearest_shift);
        wire [7:0] value=in_data[(lane/16)*128+source_x*8+:8];
        assign addresses[lane*10+:10]={in_context,value^8'h80};
        assign request_mask[lane]=(lane/16)<in_channels&&(lane%16)<in_x_count;
    end endgenerate
    generate for(copy=0;copy<32;copy=copy+1)begin:gen_copy
        localparam integer A=copy*2,B=copy*2+1;
        (* ram_style="block" *)reg [7:0] table_mem[0:1023];
        reg [7:0] result_a,result_b;
        wire [9:0] address_a=write_fire ? count[9:0] : addresses[A*10+:10];
        always @(posedge clk)begin
            if(write_fire)table_mem[address_a]<=cfg_data;
            else if(read_fire&&request_mask[A])result_a<=table_mem[address_a];
        end
        always @(posedge clk)if(read_fire&&request_mask[B])result_b<=table_mem[addresses[B*10+:10]];
        assign ram_result[A*8+:8]=rd_mask[A] ? result_a : 8'd0;
        assign ram_result[B*8+:8]=rd_mask[B] ? result_b : 8'd0;
    end endgenerate
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            epoch_q<=0;contexts_q<=0;count<=0;expected_bytes<=0;store_valid<=0;loading<=0;error_valid<=0;error_code<=0;
            rd_valid<=0;rd_epoch<=0;rd_token<=0;rd_last<=0;rd_mask<=0;
            result_valid<=0;out_epoch<=0;out_token<=0;out_last<=0;out_data<=0;
        end else begin
            error_valid<=0;error_code<=0;
            if(out_slot)begin
                result_valid<=rd_valid;
                if(rd_valid)begin out_epoch<=rd_epoch;out_token<=rd_token;out_last<=rd_last;out_data<=ram_result;end
            end
            if(rd_slot)begin
                rd_valid<=read_fire;
                if(read_fire)begin rd_epoch<=in_epoch;rd_token<=in_token;rd_last<=in_last;rd_mask<=request_mask;end
            end
            if(in_valid&&in_ready&&!metadata_good)begin error_valid<=1;error_code<=4;end
            if(cfg_begin&&cfg_begin_ready)begin
                store_valid<=0;count<=0;
                if(cfg_epoch==0||cfg_contexts==0||cfg_contexts>4)begin loading<=0;error_valid<=1;error_code<=1;end
                else begin epoch_q<=cfg_epoch;contexts_q<=cfg_contexts;expected_bytes<={cfg_contexts,8'd0};loading<=1;end
            end else if(cfg_word_valid&&cfg_word_ready)begin
                if(count>=expected_bytes)begin loading<=0;store_valid<=0;error_valid<=1;error_code<=3;end
                else count<=count+1;
            end else if(cfg_commit&&cfg_commit_ready)begin
                loading<=0;
                if(count!=expected_bytes)begin store_valid<=0;error_valid<=1;error_code<=2;end
                else store_valid<=1;
            end
        end
    end
endmodule
`default_nettype wire
