`default_nettype none
// Two non-bypass slots decouple native MAC result mux from factor pre-add.
// Upstream ready depends only on registered occupancy. Full->pop introduces
// one upstream bubble; steady occupancy1 supports simultaneous push/pop II1.
(* use_dsp="no" *)
module z100_native_raw_buffer_local_v2 (
    input wire clk,rst_n,cancel,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,in_token,input wire [4:0] in_site,
    input wire in_last,input wire [1023:0] in_data,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,out_token,output wire [4:0] out_site,
    output wire out_last,output wire [1023:0] out_data
);
    reg [1:0] count;
    reg write_pointer;
    reg [1093:0] payload0,payload1;
    wire enable=rst_n&&!cancel;
    assign in_ready=enable&&count<2;
    assign out_valid=enable&&count!=0;
    wire push=in_valid&&in_ready;
    wire pop=out_valid&&out_ready;

    wire [1093:0] selected_payload;
    genvar group_index;
    generate for(group_index=0;group_index<35;group_index=group_index+1) begin : gen_local_read_pointer
        localparam integer LOW=group_index*32;
        localparam integer WIDTH=(LOW+32<=1094) ? 32 : (1094-LOW);
        (* dont_touch="true", keep="true" *) reg local_read_pointer;
        always @(posedge clk) begin
            if(!rst_n||cancel) local_read_pointer<=1'b0;
            else if(pop) local_read_pointer<=!local_read_pointer;
        end
        assign selected_payload[LOW+:WIDTH]=local_read_pointer ? payload1[LOW+:WIDTH] : payload0[LOW+:WIDTH];
    end endgenerate
    assign {out_epoch,out_token,out_site,out_last,out_data}=selected_payload;
    always @(posedge clk)begin
        if(!rst_n||cancel)begin count<=0;write_pointer<=0;end
        else begin
            if(push)begin
                if(write_pointer)payload1<={in_epoch,in_token,in_site,in_last,in_data};
                else payload0<={in_epoch,in_token,in_site,in_last,in_data};
                write_pointer<=!write_pointer;
            end
            case({push,pop})
                2'b10:count<=count+1;
                2'b01:count<=count-1;
                default:count<=count;
            endcase
        end
    end
endmodule
`default_nettype wire
