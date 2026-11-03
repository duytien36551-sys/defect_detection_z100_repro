`timescale 1ns/1ps
`default_nettype none
`include "slot_defs.vh"
module tb_z100_native_slot_mmio_strobe_negative;
    reg clk=0;always #5 clk=~clk;reg rst_n=0;
    reg [11:0] awaddr=0,araddr=0;reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
    reg [31:0] wdata=0;reg [3:0] wstrb=0;
    wire awready,wready,bvalid,arready,rvalid,irq;wire[1:0] bresp,rresp;wire[31:0] rdata;
    wire[2:0] cv,cr,rv,rr;wire[605:0] cp;wire[116:0] rp;
    reg spoof_bridge_reply=0;
    wire[116:0] bridge_reply=rp^(spoof_bridge_reply?117'd1:117'd0);
    z100_native_slot_mmio frontend(.clk(clk),.rst_n(rst_n),
        .s_axi_awaddr(awaddr),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
        .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
        .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
        .s_axi_araddr(araddr),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
        .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
        .client_valid(cv),.client_ready(cr),.client_packet(cp),.client_response_valid(rv),
        .client_response_ready(rr),.client_response_packet(bridge_reply),.interrupt(irq));
    wire av,mready,mrv,mrr,arb_active,arb_fault;wire[201:0] mp;wire[38:0] mrp;
    z100_native_slot_arbiter arb(.clk(clk),.rst_n(rst_n),.client_valid(cv),.client_ready(cr),.client_packet(cp),
        .client_response_valid(rv),.client_response_ready(rr),.client_response_packet(rp),
        .manager_valid(av),.manager_ready(mready),.manager_packet(mp),.manager_response_valid(mrv),.manager_response_ready(mrr),
        .manager_response_packet(mrp),.active(arb_active),.protocol_fault(arb_fault));
    reg [6:0] io_quiescent=127;reg[2:0] query_slot=0;wire slot_ready;
    wire [6:0] committed_slots,fault_slots,active_slots;wire[31:0] response_tag;wire[2:0] response_slot;wire[3:0] response_code_raw;
    wire query_committed,query_active,query_fault;wire[7:0] query_readers;
    wire[31:0] query_epoch,query_generation,query_address,query_bytes;
    wire[15:0] query_tensor_id;wire[10:0] query_channels,query_covered_rows;wire[9:0] query_height,query_width;
    integer stalled=0,manager_accepts=0;wire allow_manager=stalled>=3;
    assign mready=slot_ready&&allow_manager;assign mrp={response_code_raw,response_slot,response_tag};
    always @(posedge clk)begin if(!rst_n||!av)stalled<=0;else if(!mready)stalled<=stalled+1;
        if(rst_n&&av&&mready)manager_accepts<=manager_accepts+1;end
    z100_native_tensor_slots_bounded_v2 slots(.clk(clk),.rst_n(rst_n),.io_quiescent(io_quiescent),
        .cmd_valid(av&&allow_manager),.cmd_ready(slot_ready),.cmd_opcode(mp[2:0]),.cmd_slot(mp[5:3]),.cmd_tag(mp[37:6]),
        .cmd_epoch(mp[69:38]),.cmd_generation(mp[101:70]),.cmd_address(mp[133:102]),.cmd_tensor_id(mp[149:134]),
        .cmd_channels(mp[160:150]),.cmd_height(mp[170:161]),.cmd_width(mp[180:171]),.cmd_first_row(mp[190:181]),.cmd_tile_height(mp[200:191]),.cmd_success(mp[201]),
        .response_valid(mrv),.response_ready(mrr),.response_tag(response_tag),.response_slot(response_slot),.response_code(response_code_raw),
        .committed_slots(committed_slots),.fault_slots(fault_slots),.active_slots(active_slots),.query_slot(query_slot),
        .query_committed(query_committed),.query_active(query_active),.query_fault(query_fault),.query_readers(query_readers),
        .query_epoch(query_epoch),.query_generation(query_generation),.query_address(query_address),.query_bytes(query_bytes),.query_tensor_id(query_tensor_id),
        .query_channels(query_channels),.query_covered_rows(query_covered_rows),.query_height(query_height),.query_width(query_width));
    reg[3:0] response_code=0;
    wire [221:0] snapshot={fault_slots,committed_slots,active_slots,query_covered_rows,query_width,query_height,query_channels,
        query_tensor_id,query_bytes,query_address,query_generation,query_epoch,query_readers,query_fault,query_committed,query_active,response_code};
    integer writes=0,reads=0,bholds=0,rholds=0,irqs=0,peak=0;
    task send_aw(input[11:0] address);begin @(negedge clk);awaddr=address;awvalid=1;
        do @(posedge clk);while(!awready);@(negedge clk);awvalid=0;awaddr=12'hfff;end endtask
    task send_w(input[31:0] data,input[3:0] strobes);begin @(negedge clk);wdata=data;wstrb=strobes;wvalid=1;
        do @(posedge clk);while(!wready);@(negedge clk);wvalid=0;wdata=32'hdeadbeef;wstrb=0;end endtask
    task wr(input[11:0] address,input[31:0] data,input[3:0] strobes,input integer order,input[1:0] wanted);
        integer j;begin
            if(order==0)begin send_aw(address);repeat(3)@(negedge clk);send_w(data,strobes);end
            else if(order==1)begin send_w(data,strobes);repeat(2)@(negedge clk);send_aw(address);end
            else begin fork send_aw(address);send_w(data,strobes);join end
            do @(negedge clk);while(!bvalid);
            for(j=0;j<3;j=j+1)begin if(!bvalid||bresp!==wanted)$fatal(1,"AXIL write response addr=%h got=%h wanted=%h",address,bresp,wanted);bholds=bholds+1;@(negedge clk);end
            bready=1;@(negedge clk);bready=0;writes=writes+1;
        end
    endtask
    task rd(input[11:0] address,input[1:0] wanted,output reg[31:0] value);
        integer j;begin
            @(negedge clk);araddr=address;arvalid=1;do @(posedge clk);while(!arready);
            @(negedge clk);arvalid=0;araddr=12'hfff;
            do @(negedge clk);while(!rvalid);value=rdata;
            for(j=0;j<4;j=j+1)begin if(!rvalid||rresp!==wanted||rdata!==value)$fatal(1,"AXIL read hold addr=%h",address);rholds=rholds+1;@(negedge clk);end
            rready=1;@(negedge clk);rready=0;reads=reads+1;
        end
    endtask
    task post(input[201:0] packet,input integer route);
        integer j;begin for(j=0;j<7;j=j+1)wr(12'h010+j*4,packet>>(j*32),15,j%3,0);
            wr(12'h00c,route,15,0,0);wr(12'h008,1,15,1,0);end
    endtask
    reg [255:0] commands[0:`SLOT_COMMANDS-1],expected[0:`SLOT_COMMANDS-1];
    reg[31:0] status,lo,hi,value;reg[201:0] packet;integer i,j,n,route,waits,accepted_before;
    initial begin
        $readmemh("commands.hex",commands);$readmemh("expected.hex",expected);
        repeat(5)@(negedge clk);rst_n=1;
        rd(0,0,value);if(value!==32'h5a4e5331)$fatal(1,"Frontend identity");
        wr(16,32'h12345678,15,0,0);wr(16,32'haabbccdd,5,1,0);rd(16,0,value);if(value!==32'h12bb56dd)$fatal(1,"Byte strobes");
        wr(12,2,15,0,0);wr(12,0,2,1,0);rd(12,0,value);if(value!=2)$fatal(1,"Unstrobed route byte changed");
        wr(12,0,1,2,0);rd(12,0,value);if(value!=0)$fatal(1,"Strobed route byte not changed");
        wr(16,32'hffffffff,0,2,0);rd(16,0,value);if(value!==32'h12bb56dd)$fatal(1,"Zero strobe modified shadow");
        wr(17,0,15,0,2);rd(17,2,value);rd(12'h02c,2,value);wr(12'h02c,0,15,0,2);
        wr(12'h00c,1,15,1,2);wr(8,2,15,2,2);wr(8,3,15,0,2);
        wr(40,32'hfffffc00,15,0,0);wr(8,1,15,0,2);rd(4,0,status);if(status!=0)$fatal(1,"Rejected upper packet bits submitted");
        for(i=0;i<`SLOT_COMMANDS;i=i+1)begin
            query_slot=commands[i][5:3];io_quiescent=commands[i][208:202];packet=commands[i][201:0];
            route=(packet[2:0]==1||packet[2:0]==2)?2:0;post(packet,route);
            // Commands and staging remain locked even after manager response
            // has been stored, until the host explicitly acknowledges it.
            wr(16,0,15,0,2);wr(8,1,15,1,2);wr(12,0,15,2,2);
            waits=0;status=0;while(!status[1])begin rd(4,0,status);waits=waits+1;if(waits>100)$fatal(1,"MMIO reply watchdog");end
            if(!status[0]||!irq)$fatal(1,"Response IRQ or retained ownership absent");irqs=irqs+1;
            rd(48,0,lo);rd(52,0,hi);response_code=hi[6:3];#1; // settle continuous snapshot projection before comparison
            if(lo!==packet[37:6]||hi[2:0]!==packet[5:3]||hi[31:7]!=0||snapshot!==expected[i][221:0])$fatal(1,"MMIO manager identity/snapshot command=%d",i);
            rd(56,0,value);if(value!=route)$fatal(1,"Captured client route");
            n=0;for(j=0;j<7;j=j+1)if(active_slots[j])n=n+1;if(n>peak)peak=n;
            wr(8,2,15,0,0);rd(4,0,status);if(status!=0||irq)$fatal(1,"ACK did not release bridge/IRQ");
        end
        if(active_slots!=0||fault_slots!=0||committed_slots!=0||peak!=7||arb_fault||manager_accepts!=`SLOT_COMMANDS)$fatal(1,"Full MMIO graph metadata coverage");
        // Foreign response must stay unacknowledged; correct response can drain,
        // but sticky fault prevents new normal work until coordinated reset.
        packet=0;packet[5:3]=7;packet[37:6]=32'h778899aa;spoof_bridge_reply=1;post(packet,0);
        do @(negedge clk);while(!rv[0]);repeat(5)@(negedge clk);
        if(rr[0])$fatal(1,"Foreign bridge reply consumed");rd(4,0,status);if(!status[3]||status[1]||!irq)$fatal(1,"Foreign ACK not quarantined");
        spoof_bridge_reply=0;status=0;while(!status[1])rd(4,0,status);
        rd(48,0,lo);if(lo!==32'h778899aa)$fatal(1,"Correct late reply lost");wr(8,2,15,0,0);
        accepted_before=manager_accepts;wr(8,1,15,0,2);repeat(8)@(negedge clk);if(manager_accepts!=accepted_before)$fatal(1,"Faulted bridge resumed normal work");
        $display("SLOT_MMIO_PASS commands=%0d manager_accepts=%0d writes=%0d reads=%0d write_hold_cycles=%0d read_hold_cycles=%0d response_irqs=%0d peak_slots=%0d foreign_reply_quarantined=1",`SLOT_COMMANDS,manager_accepts,writes,reads,bholds,rholds,irqs,peak);
        $finish;
    end
    initial begin #20000000;$fatal(1,"MMIO watchdog");end
endmodule
`default_nettype wire
