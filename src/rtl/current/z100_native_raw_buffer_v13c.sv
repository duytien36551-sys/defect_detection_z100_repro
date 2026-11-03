`default_nettype none
// Two non-bypass slots decouple native MAC result mux from factor pre-add.
// Upstream ready depends only on registered occupancy. Full->pop introduces
// one upstream bubble; steady occupancy1 supports simultaneous push/pop II1.
(* use_dsp="no" *)
module z100_native_raw_buffer_v13c (
    input wire clk,rst_n,cancel,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,in_token,input wire [4:0] in_site,
    input wire in_last,input wire [1023:0] in_data,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,out_token,output wire [4:0] out_site,
    output wire out_last,output wire [1023:0] out_data
);
    reg [1:0] count;
    reg read_pointer,write_pointer;
    reg [1093:0] payload0,payload1;
    wire enable=rst_n&&!cancel;
    assign in_ready=enable&&count<2;
    assign out_valid=enable&&count!=0;
    assign {out_epoch,out_token,out_site,out_last,out_data}=read_pointer ? payload1 : payload0;
    wire push=in_valid&&in_ready;
    wire pop=out_valid&&out_ready;
    // v13c: the free write slot reloads every cycle (CE = registered
    // occupancy/pointer only); push merely advances write_pointer. The slot at
    // write_pointer is never observed while free (count<2), so outputs are
    // cycle-exact with the original. Removes native_mac valid cone -> 2x1094 CE.
    wire slot_free=count<2;
    always @(posedge clk)begin
        if(slot_free&&write_pointer)payload1<={in_epoch,in_token,in_site,in_last,in_data};
        if(slot_free&&!write_pointer)payload0<={in_epoch,in_token,in_site,in_last,in_data};
    end
    always @(posedge clk)begin
        if(!rst_n||cancel)begin count<=0;read_pointer<=0;write_pointer<=0;end
        else begin
            if(push)write_pointer<=!write_pointer;
            if(pop)read_pointer<=!read_pointer;
            case({push,pop})
                2'b10:count<=count+1;
                2'b01:count<=count-1;
                default:count<=count;
            endcase
        end
    end
endmodule
`default_nettype wire
