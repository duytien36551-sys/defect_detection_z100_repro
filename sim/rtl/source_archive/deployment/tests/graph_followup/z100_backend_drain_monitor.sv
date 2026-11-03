`timescale 1ns/1ps
`default_nettype none
// Simulation-only scoreboard for the backend's single-outstanding physical bus.
// This module observes signals; it never drives/reset/repairs the actual DUT.
module z100_backend_drain_monitor(
    input wire clk,rst_n,command_fire,cancel,all_io_quiet,drain_complete,producer_complete,
    input wire arvalid,arready,rvalid,rready,rlast,
    input wire awvalid,awready,wvalid,wready,wlast,bvalid,bready,
    output wire [7:0] violations
);
    reg read_pending,write_pending,write_last_seen,cancel_seen;
    wire ar_fire=arvalid&&arready, r_fire=rvalid&&rready;
    wire aw_fire=awvalid&&awready, w_fire=wvalid&&wready, b_fire=bvalid&&bready;
    wire physical_pending=read_pending||write_pending||arvalid||awvalid||wvalid;
    assign violations[0]=rst_n&&all_io_quiet&&physical_pending;
    assign violations[1]=rst_n&&(drain_complete!=all_io_quiet);
    assign violations[2]=rst_n&&producer_complete&&
        (!all_io_quiet||physical_pending||cancel||cancel_seen);
    assign violations[3]=rst_n&&ar_fire&&read_pending;
    assign violations[4]=rst_n&&r_fire&&!read_pending;
    assign violations[5]=rst_n&&aw_fire&&write_pending;
    assign violations[6]=rst_n&&w_fire&&!write_pending;
    assign violations[7]=rst_n&&b_fire&&
        (!write_pending||!(write_last_seen||(w_fire&&wlast)));
    always @(posedge clk) begin
        if(!rst_n) begin
            read_pending<=0;write_pending<=0;write_last_seen<=0;cancel_seen<=0;
        end else begin
            if(command_fire) cancel_seen<=0;
            if(cancel) cancel_seen<=1;
            if(ar_fire) read_pending<=1;
            if(r_fire&&rlast) read_pending<=0;
            if(aw_fire) begin write_pending<=1;write_last_seen<=0;end
            if(w_fire&&wlast) write_last_seen<=1;
            if(b_fire) begin write_pending<=0;write_last_seen<=0;end
        end
    end
endmodule
`default_nettype wire
