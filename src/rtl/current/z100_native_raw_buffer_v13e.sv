`default_nettype none
// Two non-bypass slots decouple native MAC result mux from factor pre-add.
// Upstream ready depends only on registered occupancy. Full->pop introduces
// one upstream bubble; steady occupancy1 supports simultaneous push/pop II1.
// v13e (vs z100_native_raw_buffer_v13d, identical ports and cycle behaviour):
//  v13d registered the slot load enable into 8 replicas per slot, each
//  covering an arbitrary 137-bit slice of the 1094-bit word. Routed, one
//  replica had to reach payload bits 150+ rows apart (9.48 ns, slack 0.001).
//  Here the replicas follow the physical data lanes: one per 32-bit result
//  lane (32) + epoch + token + {site,last}  = 35 per slot, each driving <=32
//  CE pins that sit next to that lane's MAC/requant logic. The enable is the
//  same next-state function as v13d. (* keep *) instead of dont_touch so
//  phys_opt may still replicate a copy that ends up far from its sinks.
(* use_dsp="no" *)
module z100_native_raw_buffer_v13e (
    input wire clk,rst_n,cancel,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,in_token,input wire [4:0] in_site,
    input wire in_last,input wire [1023:0] in_data,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,out_token,output wire [4:0] out_site,
    output wire out_last,output wire [1023:0] out_data
);
    localparam integer LANES=32;
    localparam integer COPIES=LANES+3; // data lanes, epoch, token, {site,last}
    reg [1:0] count;
    reg read_pointer,write_pointer;
    reg [1023:0] data0,data1;
    reg [31:0] epoch0,epoch1,token0,token1;
    reg [5:0] meta0,meta1;              // {site,last}
    wire enable=rst_n&&!cancel;
    assign in_ready=enable&&count<2;
    assign out_valid=enable&&count!=0;
    assign out_epoch=read_pointer ? epoch1 : epoch0;
    assign out_token=read_pointer ? token1 : token0;
    assign {out_site,out_last}=read_pointer ? meta1 : meta0;
    assign out_data=read_pointer ? data1 : data0;
    wire push=in_valid&&in_ready;
    wire pop=out_valid&&out_ready;

    // Next-state occupancy/pointer (exactly what the sequential block loads).
    reg [1:0] count_n; reg write_pointer_n;
    always @* begin
        if(!rst_n||cancel) begin count_n=2'd0; write_pointer_n=1'b0; end
        else begin
            write_pointer_n=push ? !write_pointer : write_pointer;
            case({push,pop})
                2'b10:count_n=count+1'b1;
                2'b01:count_n=count-1'b1;
                default:count_n=count;
            endcase
        end
    end
    wire free_n=(count_n<2);
    // load*_q[k] at cycle t == (count<2 && write_pointer==slot) at cycle t.
    (* keep="true" *) reg [COPIES-1:0] load0_q;
    (* keep="true" *) reg [COPIES-1:0] load1_q;
    always @(posedge clk) begin
        load0_q<={COPIES{free_n && !write_pointer_n}};
        load1_q<={COPIES{free_n &&  write_pointer_n}};
    end

    // Free slot reloads every cycle; the slot at write_pointer is never
    // observed while free (count<2), so outputs are cycle-exact.
    genvar k;
    generate for(k=0;k<LANES;k=k+1) begin : gen_lane
        always @(posedge clk) begin
            if(load0_q[k]) data0[k*32+:32]<=in_data[k*32+:32];
            if(load1_q[k]) data1[k*32+:32]<=in_data[k*32+:32];
        end
    end endgenerate
    always @(posedge clk) begin
        if(load0_q[LANES])   epoch0<=in_epoch;
        if(load1_q[LANES])   epoch1<=in_epoch;
        if(load0_q[LANES+1]) token0<=in_token;
        if(load1_q[LANES+1]) token1<=in_token;
        if(load0_q[LANES+2]) meta0<={in_site,in_last};
        if(load1_q[LANES+2]) meta1<={in_site,in_last};
    end

    always @(posedge clk)begin
        if(!rst_n||cancel)begin count<=0;read_pointer<=0;write_pointer<=0;end
        else begin
            if(push)write_pointer<=!write_pointer;
            if(pop)read_pointer<=!read_pointer;
            count<=count_n;
        end
    end
endmodule
`default_nettype wire
