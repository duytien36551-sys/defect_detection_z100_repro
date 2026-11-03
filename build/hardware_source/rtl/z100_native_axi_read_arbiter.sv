`default_nettype none
// Two AXI3 read masters, one outstanding burst on a physical64-bit channel.
// Capture an upstream AR and retain its owner through accepted physical RLAST.
// Neither abort nor local recovery can drop an advertised/accepted transaction.
// rst_n requires coordinated reset after physical IO ownership is resolved.
module z100_native_axi_read_arbiter(
    input wire clk,rst_n,
    input wire[11:0] s_arid,input wire[63:0] s_araddr,input wire[7:0] s_arlen,
    input wire[5:0] s_arsize,input wire[3:0] s_arburst,input wire[1:0] s_arvalid,
    output reg[1:0] s_arready,
    output wire[11:0] s_rid,output wire[127:0] s_rdata,output wire[3:0] s_rresp,
    output reg[1:0] s_rlast,s_rvalid,input wire[1:0] s_rready,
    output wire[5:0] m_arid,output wire[31:0] m_araddr,output wire[3:0] m_arlen,
    output wire[2:0] m_arsize,output wire[1:0] m_arburst,output wire m_arvalid,input wire m_arready,
    input wire[5:0] m_rid,input wire[63:0] m_rdata,input wire[1:0] m_rresp,
    input wire m_rlast,m_rvalid,output wire m_rready,
    output wire active,output wire active_owner,output reg protocol_fault
);
    localparam IDLE=0,ADDRESS=1,DATA=2;
    reg[1:0] state;reg owner,next_owner;
    reg[5:0] id_q;reg[31:0] address_q;reg[3:0] len_q;reg[2:0] size_q;reg[1:0] burst_q;
    reg[4:0] beat;
    wire selected=s_arvalid[next_owner]?next_owner:!next_owner;
    wire any_request=|s_arvalid;
    assign active=state!=IDLE;assign active_owner=owner;
    assign m_arvalid=rst_n&&state==ADDRESS;
    assign m_arid=id_q;assign m_araddr=address_q;assign m_arlen=len_q;assign m_arsize=size_q;assign m_arburst=burst_q;
    assign s_rid={2{m_rid}};assign s_rdata={2{m_rdata}};assign s_rresp={2{m_rresp}};
    assign m_rready=rst_n&&state==DATA&&s_rready[owner];
    always @*begin
        s_arready=0;s_rvalid=0;s_rlast=0;
        if(rst_n&&state==IDLE&&!protocol_fault&&any_request)s_arready[selected]=1;
        if(rst_n&&state==DATA)begin s_rvalid[owner]=m_rvalid;s_rlast[owner]=m_rlast;end
    end
    always @(posedge clk)begin
        if(!rst_n)begin state<=IDLE;owner<=0;next_owner<=0;id_q<=0;address_q<=0;len_q<=0;size_q<=0;burst_q<=0;beat<=0;protocol_fault<=0;end
        else begin
            if(m_rvalid&&state!=DATA)protocol_fault<=1;
            case(state)
                IDLE:if(any_request&&s_arready[selected]&&s_arvalid[selected])begin
                    owner<=selected;id_q<=s_arid[selected*6+:6];address_q<=s_araddr[selected*32+:32];
                    len_q<=s_arlen[selected*4+:4];size_q<=s_arsize[selected*3+:3];burst_q<=s_arburst[selected*2+:2];beat<=0;state<=ADDRESS;
                end
                ADDRESS:if(m_arvalid&&m_arready)state<=DATA;
                DATA:if(m_rvalid&&m_rready)begin
                    if(m_rid!=id_q||m_rlast!=(beat=={1'b0,len_q}))protocol_fault<=1;
                    if(m_rlast)begin next_owner<=!owner;state<=IDLE;end
                    else if(beat!=31)beat<=beat+1;
                end
                default:protocol_fault<=1;
            endcase
        end
    end
endmodule
`default_nettype wire
