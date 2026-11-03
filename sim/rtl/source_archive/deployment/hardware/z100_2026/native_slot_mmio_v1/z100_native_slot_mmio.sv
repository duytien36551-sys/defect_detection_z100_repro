`default_nettype none
// Private AXI4-Lite packet frontend for graph(client0)/writer(client2).
// Source client1 remains autonomous. One command is retained until host ACKs
// the stored response. No local reset/timeout discards an accepted transaction.
module z100_native_slot_mmio (
    input wire clk,rst_n,
    input wire [11:0] s_axi_awaddr,input wire s_axi_awvalid,output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,input wire [3:0] s_axi_wstrb,input wire s_axi_wvalid,output wire s_axi_wready,
    output reg [1:0] s_axi_bresp,output reg s_axi_bvalid,input wire s_axi_bready,
    input wire [11:0] s_axi_araddr,input wire s_axi_arvalid,output wire s_axi_arready,
    output reg [31:0] s_axi_rdata,output reg [1:0] s_axi_rresp,output reg s_axi_rvalid,input wire s_axi_rready,
    output wire [2:0] client_valid,input wire [2:0] client_ready,output wire [605:0] client_packet,
    input wire [2:0] client_response_valid,output reg [2:0] client_response_ready,
    input wire [116:0] client_response_packet,output wire interrupt
);
    reg aw_held,w_held;reg [11:0] awaddr_q;reg [31:0] wdata_q;reg [3:0] wstrb_q;
    reg [31:0] shadow[0:6];reg [1:0] route_shadow,route_q;
    reg inflight,send_pending,reply_valid,protocol_fault;
    reg [201:0] packet_q;reg [38:0] reply_q;
    wire [38:0] incoming_reply=client_response_packet[route_q*39+:39];
    wire reply_identity=incoming_reply[31:0]==packet_q[37:6]&&incoming_reply[34:32]==packet_q[5:3];
    wire collecting=inflight&&!send_pending&&!reply_valid;
    assign s_axi_awready=rst_n&&!aw_held&&!s_axi_bvalid;
    assign s_axi_wready=rst_n&&!w_held&&!s_axi_bvalid;
    assign s_axi_arready=rst_n&&!s_axi_rvalid;
    assign client_valid=rst_n&&send_pending?(3'b001<<route_q):3'b000;
    assign client_packet={3{packet_q}};
    assign interrupt=rst_n&&(reply_valid||protocol_fault);
    reg [31:0] masked_write;integer byte_index;
    always @*begin
        masked_write=0;
        for(byte_index=0;byte_index<4;byte_index=byte_index+1)
            if(wstrb_q[byte_index])masked_write[byte_index*8+:8]=wdata_q[byte_index*8+:8];
        client_response_ready=0;
        if(rst_n&&collecting&&reply_identity)client_response_ready[route_q]=1;
    end
    integer i,j;
    always @(posedge clk)begin
        if(!rst_n)begin
            aw_held<=0;w_held<=0;awaddr_q<=0;wdata_q<=0;wstrb_q<=0;
            s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rresp<=0;s_axi_rdata<=0;
            route_shadow<=0;route_q<=0;inflight<=0;send_pending<=0;reply_valid<=0;protocol_fault<=0;packet_q<=0;reply_q<=0;
            for(i=0;i<7;i=i+1)shadow[i]<=0;
        end else begin
            if(s_axi_bvalid&&s_axi_bready)s_axi_bvalid<=0;
            if(s_axi_rvalid&&s_axi_rready)s_axi_rvalid<=0;
            if(s_axi_awvalid&&s_axi_awready)begin aw_held<=1;awaddr_q<=s_axi_awaddr;end
            if(s_axi_wvalid&&s_axi_wready)begin w_held<=1;wdata_q<=s_axi_wdata;wstrb_q<=s_axi_wstrb;end
            if(send_pending&&client_ready[route_q])send_pending<=0;
            if(collecting&&client_response_valid[route_q])begin
                if(!reply_identity)protocol_fault<=1;
                else if(client_response_ready[route_q])begin reply_q<=incoming_reply;reply_valid<=1;end
            end
            if(aw_held&&w_held&&!s_axi_bvalid)begin
                aw_held<=0;w_held<=0;s_axi_bvalid<=1;s_axi_bresp<=0;
                if(awaddr_q[1:0]!=0)s_axi_bresp<=2;
                else if(wstrb_q==0)begin end
                else if(awaddr_q>=12'h010&&awaddr_q<=12'h028)begin
                    if(inflight)s_axi_bresp<=2;
                    else for(j=0;j<4;j=j+1)if(wstrb_q[j])shadow[(awaddr_q-16)>>2][j*8+:8]<=wdata_q[j*8+:8];
                end else case(awaddr_q)
                    12'h00c:if(inflight||(masked_write!=0&&masked_write!=2))s_axi_bresp<=2;
                        else route_shadow<=masked_write[1:0];
                    12'h008:begin
                        if(masked_write==1)begin
                            if(inflight||reply_valid||protocol_fault||shadow[6][31:10]!=0)s_axi_bresp<=2;
                            else begin
                                packet_q<={shadow[6][9:0],shadow[5],shadow[4],shadow[3],shadow[2],shadow[1],shadow[0]};
                                route_q<=route_shadow;inflight<=1;send_pending<=1;
                            end
                        end else if(masked_write==2)begin
                            if(!reply_valid)s_axi_bresp<=2;
                            else begin reply_valid<=0;inflight<=0;end
                        end else s_axi_bresp<=2;
                    end
                    default:s_axi_bresp<=2;
                endcase
            end
            if(s_axi_arvalid&&s_axi_arready)begin
                s_axi_rvalid<=1;s_axi_rresp<=0;s_axi_rdata<=0;
                if(s_axi_araddr[1:0]!=0)s_axi_rresp<=2;
                else if(s_axi_araddr>=12'h010&&s_axi_araddr<=12'h028)s_axi_rdata<=shadow[(s_axi_araddr-16)>>2];
                else case(s_axi_araddr)
                    12'h000:s_axi_rdata<=32'h5a4e5331;
                    12'h004:s_axi_rdata<={28'd0,protocol_fault,send_pending,reply_valid,inflight};
                    12'h00c:s_axi_rdata<={30'd0,route_shadow};
                    12'h030:s_axi_rdata<=reply_q[31:0];
                    12'h034:s_axi_rdata<={25'd0,reply_q[38:32]};
                    12'h038:s_axi_rdata<={30'd0,route_q};
                    default:s_axi_rresp<=2;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
