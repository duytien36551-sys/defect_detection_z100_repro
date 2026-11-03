`timescale 1ns/1ps
`default_nettype none
// Real frozen AXI reader, legal held AXI producer, explicit fault injection.
// Scoreboard derives all 128 bytes from source address and immutable generation.
module tb_z100_native_pair_cache_v2;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,cmd_valid=0,cancel=0,clear_fault=0,out_ready=0;
    reg [31:0] cmd_epoch=1,cmd_address=0,cmd_source_generation=1;
    wire cmd_ready,busy,fault,done,out_valid;
    wire [3:0] fault_code;
    wire [31:0] out_epoch,out_address,hits,misses;
    wire [1023:0] out_data;
    wire mc,mcr,mb,mf,mcan,mclear,mv,mready,mlast;
    wire [31:0] me,ma,re;
    wire [13:0] mw;
    wire [12:0] ri;
    wire [511:0] md;
    integer shim=0;
    wire first_corrupt=(ri==0 && shim>=1 && shim<=3);
    wire second_corrupt=(ri==1 && shim>=4 && shim<=6);
    wire [31:0] shim_epoch=re ^ ((shim==1&&first_corrupt)||(shim==4&&second_corrupt)?32'd1:32'd0);
    wire [12:0] shim_index=ri ^ ((shim==2&&first_corrupt)||(shim==5&&second_corrupt)?13'd3:13'd0);
    wire shim_last=mlast ^ ((shim==3&&first_corrupt)||(shim==6&&second_corrupt));
    z100_native_pair_cache_v2 #(.INDEX_BITS(11)) dut(.clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),
        .cmd_epoch(cmd_epoch),.cmd_address(cmd_address),.cmd_source_generation(cmd_source_generation),
        .cancel(cancel),.clear_fault(clear_fault),.busy(busy),.fault(fault),.fault_code(fault_code),.done(done),
        .out_valid(out_valid),.out_ready(out_ready),.out_epoch(out_epoch),.out_address(out_address),.out_data(out_data),
        .memory_command(mc),.memory_command_ready(mcr),.memory_epoch(me),.memory_address(ma),.memory_word_count(mw),
        .memory_busy(mb),.memory_fault(mf),.memory_cancel(mcan),.memory_clear_fault(mclear),
        .memory_valid(mv),.memory_ready(mready),.memory_result_epoch(shim_epoch),.memory_result_index(shim_index),
        .memory_last(shim_last),.memory_data(md),.hit_count(hits),.miss_count(misses));
    wire [5:0] arid;
    wire [31:0] araddr;
    wire [3:0] arlen;
    wire [2:0] arsize;
    wire [1:0] arburst;
    wire arvalid,rready;
    reg [5:0] rid=0;
    reg [63:0] rdata=0;
    reg [1:0] rresp=0;
    reg rlast=0,rvalid=0;
    reg block_ar=0,block_r=0;
    integer cycles=0,ar_count=0,r_count=0,first_count=0;
    wire arready=!block_ar && cycles%5!=0;
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(mc),.cmd_ready(mcr),
        .cmd_epoch(me),.cmd_address(ma),.cmd_word_count(mw),.cancel(mcan),.timeout(1'b0),.clear_fault(mclear),
        .busy(mb),.done(),.fault(mf),.fault_code(),.out_valid(mv),.out_ready(mready),
        .out_epoch(re),.out_index(ri),.out_data(md),.out_last(mlast),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_rid(rid),.m_axi_rdata(rdata),
        .m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    localparam [31:0] BASE=32'h10000000;
    reg [31:0] seeds[0:8191];
    function automatic [63:0] value_at(input [31:0] addr,input integer beat);
        reg [31:0] low,high;
        begin low=(addr+beat*8)^seeds[(addr-BASE)>>7]^32'h52a59c31;
            high=(addr+beat*8)^ (seeds[(addr-BASE)>>7]*32'h01010101)^32'hb6d8207f;
            value_at={high,low};end
    endfunction
    function automatic [1023:0] golden(input [31:0] addr);
        integer k;begin for(k=0;k<16;k=k+1)golden[k*64+:64]=value_at(addr,k);end
    endfunction
    reg active=0;
    reg [31:0] response_addr=0;
    integer beat=0,physical_error=0,response_error=0;
    reg held_ar=0,held_r=0;
    reg [40:0] ar_saved;
    reg [72:0] r_saved;
    always @(posedge clk)begin
        cycles<=cycles+1;
        if(rst_n)begin
            if(held_ar && (!arvalid||{araddr,arlen,arsize,arburst}!==ar_saved))$fatal(1,"AR changed under backpressure/cancel");
            if(held_r && (!rvalid||{rid,rdata,rresp,rlast}!==r_saved))$fatal(1,"Test producer violated R hold");
            held_ar<=arvalid&&!arready;ar_saved<={araddr,arlen,arsize,arburst};
            held_r<=rvalid&&!rready;r_saved<={rid,rdata,rresp,rlast};
            if(mc&&mcr&&mw!=2)$fatal(1,"Pair must issue exactly two words");
            if(mv&&mready&&ri==0)first_count<=first_count+1;
            if(arvalid&&arready)begin
                if(active||rvalid)$fatal(1,"More than one outstanding burst");
                if(arid!=0||arlen!=15||arsize!=3||arburst!=1||araddr[6:0]!=0||araddr[11:0]>3968)
                    $fatal(1,"Invalid pair AXI burst");
                active<=1;response_addr<=araddr;beat<=0;response_error<=physical_error;ar_count<=ar_count+1;
            end
            if(rvalid&&rready)begin
                r_count<=r_count+1;rvalid<=0;
                if(rlast)active<=0;else beat<=beat+1;
            end
            // A gap is introduced only when no RVALID is pending.
            if(active&&!rvalid&&!block_r&&cycles%3!=0)begin
                rvalid<=1;rdata<=value_at(response_addr,beat);rid<=0;rresp<=0;
                rlast<=response_error==4 ? beat==16 : beat==15;
                if(beat==10)begin
                    if(response_error==1)rresp<=2;
                    if(response_error==2)rid<=1;
                    if(response_error==3)rlast<=1;
                end
            end
        end
    end
    integer checks=0,holds=0,recoveries=0,atomic_preserves=0,blocked=0,errors=0;
    task automatic issue(input [31:0] addr,input [31:0] ep,input [31:0] gen);
        begin
            @(negedge clk);cmd_address=addr;cmd_epoch=ep;cmd_source_generation=gen;cmd_valid=1;
            do @(posedge clk);while(!cmd_ready);
            @(negedge clk);cmd_valid=0;cmd_address=32'hdeadbeef;cmd_epoch=99;cmd_source_generation=88;
        end
    endtask
    task automatic receive_pair(input [31:0] addr,input [31:0] ep,input [1023:0] expected,input integer wait_cycles);
        integer k;begin
            do @(negedge clk);while(!out_valid&&!fault);
            if(fault)$fatal(1,"Unexpected cache fault %d",fault_code);
            for(k=0;k<=wait_cycles;k=k+1)begin
                if(!out_valid||out_epoch!==ep||out_address!==addr||out_data!==expected)
                    $fatal(1,"Pair identity/data/backpressure mismatch addr=%h",addr);
                checks=checks+1;
                if(k<wait_cycles)begin holds=holds+1;@(negedge clk);end
            end
            out_ready=1;@(posedge clk);@(negedge clk);out_ready=0;
            if(!done)$fatal(1,"Missing completion");
        end
    endtask
    task automatic query(input [31:0] addr,input [31:0] ep,input [31:0] gen,input integer expect_miss);
        integer old_ar,old_r;reg[1023:0] expected;begin
            old_ar=ar_count;old_r=r_count;expected=golden(addr);
            issue(addr,ep,gen);receive_pair(addr,ep,expected,7);
            if(ar_count-old_ar!=expect_miss||r_count-old_r!=16*expect_miss)
                $fatal(1,"Wrong hit/miss traffic addr=%h ar=%d expected=%d",addr,ar_count-old_ar,expect_miss);
        end
    endtask
    task automatic recover;
        integer n;begin
            cancel=0;
            do @(negedge clk);while(mb);
            clear_fault=1;
            n=0;
            while(!cmd_ready&&n<30)begin @(negedge clk);n=n+1;end
            if(!cmd_ready||fault||busy)$fatal(1,"Recovery did not reach idle");
            clear_fault=0;recoveries=recoveries+1;
        end
    endtask
    task automatic await_fault;
        begin do @(negedge clk);while(!fault);if(out_valid)$fatal(1,"Invalid output exposed on fault");errors=errors+1;end
    endtask
    task automatic blocked_clear(input integer n);
        integer k;begin clear_fault=1;
            for(k=0;k<n;k=k+1)begin @(negedge clk);
                if(!busy||cmd_ready||out_valid||mclear)$fatal(1,"Cleared while AXI still owned");blocked=blocked+1;
            end
            clear_fault=0;
        end
    endtask
    integer i,old_ar,first_before;
    reg [1023:0] saved;
    initial begin
        for(i=0;i<8192;i=i+1)seeds[i]=i*19+7;
        repeat(5)@(negedge clk);rst_n=1;
        query(BASE,1,1,1);query(BASE,1,1,0);
        query(BASE+3968,1,1,1); // Final128B of4KiB page.
        seeds[0]=103;query(BASE,1,2,1);query(BASE,1,2,0);
        seeds[0]=104;query(BASE,2,2,1);query(BASE,2,2,0);
        query(BASE+262144,2,2,1);query(BASE,2,2,1);
        // More than one full direct-map capacity, then check survivors/eviction.
        for(i=0;i<2100;i=i+1)query(BASE+i*128,3,3,1);
        query(BASE+2099*128,3,3,0);query(BASE,3,3,1);
        // Preload A then cancel alias B after first word; A must remain a hit.
        query(BASE,7,7,1);saved=golden(BASE);first_before=first_count;
        issue(BASE+262144,7,7);
        do @(negedge clk);while(first_count==first_before);
        cancel=1;@(negedge clk);await_fault();recover();
        query(BASE,7,7,0);atomic_preserves=atomic_preserves+1;
        // Malformed private metadata from the actual reader via explicit shim.
        for(i=1;i<=6;i=i+1)begin
            shim=i;issue(BASE+262144,7,7);await_fault();recover();shim=0;
            query(BASE,7,7,0);atomic_preserves=atomic_preserves+1;
        end
        // Protocol faults on the AXI fabric itself, with drain to real RLAST.
        for(i=1;i<=4;i=i+1)begin
            physical_error=i;issue(BASE+262144,7,7);await_fault();recover();physical_error=0;
            query(BASE,7,7,0);atomic_preserves=atomic_preserves+1;
        end
        // Bad commands must never reach AXI.
        old_ar=ar_count;
        issue(BASE,0,1);await_fault();recover();
        issue(BASE,1,0);await_fault();recover();
        issue(BASE+1,1,1);await_fault();recover();
        issue(BASE+64,1,1);await_fault();recover();
        if(ar_count!=old_ar)$fatal(1,"Malformed command issued AR");
        // Accepted command with indefinitely blocked AR; cancel cannot withdraw AR.
        block_ar=1;issue(BASE+262144,7,7);
        do @(negedge clk);while(!arvalid);
        cancel=1;@(negedge clk);cancel=0;blocked_clear(40);block_ar=0;recover();
        query(BASE,7,7,0);atomic_preserves=atomic_preserves+1;
        // Accepted AR with no response: clearing must wait until drain completes.
        block_r=1;old_ar=ar_count;issue(BASE+262144,7,7);
        do @(negedge clk);while(ar_count==old_ar);
        cancel=1;@(negedge clk);cancel=0;blocked_clear(100);block_r=0;recover();
        query(BASE,7,7,0);atomic_preserves=atomic_preserves+1;
        // Cancel already installed, held output; cached immutable line survives.
        issue(BASE,7,7);do @(negedge clk);while(!out_valid);
        cancel=1;@(negedge clk);await_fault();recover();query(BASE,7,7,0);
        if(atomic_preserves!=13||blocked!=140||recoveries!=18||errors!=16)
            $fatal(1,"Coverage incomplete atomic=%d blocked=%d recovery=%d errors=%d",atomic_preserves,blocked,recoveries,errors);
        $display("PAIR_CACHE256K_PASS checks=%0d held_cycles=%0d atomic_preserves=%0d blocked_clear_cycles=%0d recoveries=%0d errors=%0d ar=%0d r=%0d hits=%0d misses=%0d",
            checks,holds,atomic_preserves,blocked,recoveries,errors,ar_count,r_count,hits,misses);
        $finish;
    end
    initial begin #20000000;$fatal(1,"Watchdog timeout");end
endmodule
`default_nettype wire
