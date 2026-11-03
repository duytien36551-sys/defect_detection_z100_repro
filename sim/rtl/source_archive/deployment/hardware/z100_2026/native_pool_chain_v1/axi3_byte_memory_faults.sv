`timescale 1ns/1ps
// Test-only independent byte memory. Separate AXI3 read/write ports, one
// outstanding burst per port, deterministic stalls, full handshake checking.
module axi3_byte_memory_faults #(
    parameter integer MEM_BYTES=262144,
    parameter [31:0] BASE=32'h10000000
)(
    input wire clk,rst_n,
    input wire allow_aw,allow_w,allow_b,allow_ar,allow_r,
    input wire [1:0] injected_bresp,injected_rresp,
    input wire [5:0] awid,input wire [31:0] awaddr,input wire [3:0] awlen,
    input wire [2:0] awsize,input wire [1:0] awburst,input wire awvalid,output wire awready,
    input wire [5:0] wid,input wire [63:0] wdata,input wire [7:0] wstrb,input wire wlast,wvalid,output wire wready,
    output reg [5:0] bid,output reg [1:0] bresp,output reg bvalid,input wire bready,
    input wire [5:0] arid,input wire [31:0] araddr,input wire [3:0] arlen,
    input wire [2:0] arsize,input wire [1:0] arburst,input wire arvalid,output wire arready,
    output reg [5:0] rid,output reg [63:0] rdata,output reg [1:0] rresp,
    output reg rlast,rvalid,input wire rready
);
    reg [7:0] bytes[0:MEM_BYTES-1];
    integer cycle=0,aw_count=0,w_count=0,b_count=0,ar_count=0,r_count=0;
    integer aw_holds=0,w_holds=0,ar_holds=0,r_holds=0,b_holds=0;
    reg wr_active=0,rd_active=0,b_pending=0;
    integer wr_address=0,wr_beats=0,wr_index=0,rd_address=0,rd_beats=0,rd_index=0,b_delay=0;
    reg held_aw=0,held_w=0,held_ar=0,held_r=0,held_b=0;
    reg [31:0] hawaddr,haraddr;reg [3:0] hawlen,harlen;
    reg [63:0] hwdata,hrdata;reg hwlast,hrlast;reg [5:0] hbid;
    assign awready=rst_n&&allow_aw&&!wr_active&&!b_pending&&!bvalid&&(cycle%17)>3;
    assign wready=rst_n&&allow_w&&wr_active&&(cycle%7)>1;
    assign arready=rst_n&&allow_ar&&!rd_active&&!rvalid&&(cycle%19)>4;
    integer lane;
    always @(posedge clk)begin
        cycle<=cycle+1;
        if(!rst_n)begin
            wr_active<=0;rd_active<=0;b_pending<=0;bvalid<=0;rvalid<=0;
            bid<=0;bresp<=0;rid<=0;rresp<=injected_rresp;rlast<=0;rdata<=0;
            held_aw<=0;held_w<=0;held_ar<=0;held_r<=0;held_b<=0;
        end else begin
            if(held_aw&&(!awvalid||awaddr!==hawaddr||awlen!==hawlen))$fatal(1,"AXI AW changed under stall");
            if(held_w&&(!wvalid||wdata!==hwdata||wlast!==hwlast))$fatal(1,"AXI W changed under stall");
            if(held_ar&&(!arvalid||araddr!==haraddr||arlen!==harlen))$fatal(1,"AXI AR changed under stall");
            if(held_r&&(!rvalid||rdata!==hrdata||rlast!==hrlast))$fatal(1,"AXI R model changed under stall");
            if(held_b&&(!bvalid||bid!==hbid))$fatal(1,"AXI B model changed under stall");
            held_aw<=awvalid&&!awready;held_w<=wvalid&&!wready;held_ar<=arvalid&&!arready;held_r<=rvalid&&!rready;held_b<=bvalid&&!bready;
            if(awvalid&&!awready)begin aw_holds=aw_holds+1;hawaddr=awaddr;hawlen=awlen;end
            if(wvalid&&!wready)begin w_holds=w_holds+1;hwdata=wdata;hwlast=wlast;end
            if(arvalid&&!arready)begin ar_holds=ar_holds+1;haraddr=araddr;harlen=arlen;end
            if(rvalid&&!rready)begin r_holds=r_holds+1;hrdata=rdata;hrlast=rlast;end
            if(bvalid&&!bready)begin b_holds=b_holds+1;hbid=bid;end
            if(awvalid&&awready)begin
                if(awid!=0||awsize!=3||awburst!=1||awaddr<BASE||awaddr+(awlen+1)*8>BASE+MEM_BYTES||
                   awaddr[2:0]!=0||({1'b0,awaddr[11:0]}+(awlen+1)*8)>4096)$fatal(1,"AXI AW contract");
                wr_active<=1;wr_address=awaddr-BASE;wr_beats=awlen+1;wr_index=0;aw_count=aw_count+1;
            end
            if(wvalid&&wready)begin
                if(wid!=0||wstrb!=8'hff||wlast!==(wr_index==wr_beats-1))$fatal(1,"AXI W contract");
                for(lane=0;lane<8;lane=lane+1)bytes[wr_address+wr_index*8+lane]<=wdata[lane*8+:8];
                wr_index=wr_index+1;w_count=w_count+1;
                if(wlast)begin wr_active<=0;b_pending<=1;b_delay=3;end
            end
            if(bvalid&&bready)begin bvalid<=0;b_count=b_count+1;end
            if(b_pending&&allow_b)begin
                if(b_delay==0)begin bid<=0;bresp<=injected_bresp;bvalid<=1;b_pending<=0;end
                else b_delay=b_delay-1;
            end
            if(arvalid&&arready)begin
                if(arid!=0||arsize!=3||arburst!=1||araddr<BASE||araddr+(arlen+1)*8>BASE+MEM_BYTES||
                   araddr[2:0]!=0||({1'b0,araddr[11:0]}+(arlen+1)*8)>4096)$fatal(1,"AXI AR contract");
                rd_active<=1;rd_address=araddr-BASE;rd_beats=arlen+1;rd_index=0;ar_count=ar_count+1;
            end
            if(rvalid&&rready)begin rvalid<=0;r_count=r_count+1;end
            if((!rvalid||rready)&&rd_active&&allow_r&&(cycle%5)!=0)begin
                for(lane=0;lane<8;lane=lane+1)rdata[lane*8+:8]<=bytes[rd_address+rd_index*8+lane];
                rid<=0;rresp<=injected_rresp;rlast<=rd_index==rd_beats-1;rvalid<=1;rd_index=rd_index+1;
                if(rd_index==rd_beats)rd_active<=0;
            end
        end
    end
endmodule
