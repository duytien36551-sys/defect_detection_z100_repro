`default_nettype none
// timing_v13c two-entry register slice (skid buffer). Full throughput,
// in_ready and out_valid/out_data come straight from flip-flops, so neither
// side's combinational cone crosses the module boundary. Payload has no reset.
module z100_skid_v13c #(parameter integer W=8) (
    input wire clk, input wire rst_n, input wire flush,
    input wire in_valid, output reg in_ready, input wire [W-1:0] in_data,
    output reg out_valid, input wire out_ready, output reg [W-1:0] out_data
);
    reg skid_valid;
    reg [W-1:0] skid_data;
    wire in_fire=in_valid&&in_ready;
    wire out_fire=out_valid&&out_ready;
    always @(posedge clk) begin
        if(in_fire&&out_valid&&!out_ready) skid_data<=in_data;
        if(!out_valid||out_ready) out_data<=skid_valid ? skid_data : in_data;
    end
    always @(posedge clk) begin
        if(!rst_n||flush) begin
            out_valid<=0; skid_valid<=0; in_ready<=0;
        end else begin
            if(!out_valid||out_ready) begin
                out_valid<=skid_valid||in_fire;
                skid_valid<=0;
                in_ready<=1'b1;
            end else if(in_fire) begin
                skid_valid<=1'b1;
                in_ready<=1'b0;
            end else in_ready<=!skid_valid;
        end
    end
endmodule
`default_nettype wire
