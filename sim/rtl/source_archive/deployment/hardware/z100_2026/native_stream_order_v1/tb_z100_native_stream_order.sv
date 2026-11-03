`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_native_stream_order;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cv=0,mode=0,iv=0,ilast=0,ordy=0,force_hold=0;
    reg [31:0] epoch=200,ie=200;
    reg [10:0] channels=1;reg [9:0] height=1,width=1;
    reg [12:0] idx=0,addr=0;reg [511:0] data=0;
    wire cr,ir,ov,olast,active,done,err;wire [1:0] ec;
    wire [31:0] oe;wire [12:0] oi,oa;wire [511:0] od;
    z100_native_stream_order dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),
        .cfg_valid(cv),.cfg_ready(cr),.cfg_epoch(epoch),.cfg_write_order(mode),.cfg_channels(channels),.cfg_height(height),.cfg_width(width),
        .in_valid(iv),.in_ready(ir),.in_epoch(ie),.in_index(idx),.in_address(addr),.in_last(ilast),.in_data(data),
        .out_valid(ov),.out_ready(ordy),.out_epoch(oe),.out_index(oi),.out_address(oa),.out_last(olast),.out_data(od),
        .active(active),.done(done),.error_valid(err),.error_code(ec));
    reg [537:0] words[0:`WORDS-1];reg [44:0] cases[0:`CASES-1];
    integer cycle=0,received=0,packet_words=0,packet_goal=0,packet_epoch=0,done_count=0,holds=0,errors=0;
    reg monitor=0,expected_error=0,held=0;
    reg [511:0] hd;reg [31:0] he;reg [12:0] hi,ha;reg hl;
    always @(negedge clk)ordy=rst_n&&!force_hold&&(cycle%31)>7;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n&&!cancel)begin
            if(err)begin if(!expected_error)$fatal(1,"unexpected stream error=%0d",ec);errors=errors+1;end
            if(monitor)begin
                if(held&&(!ov||{od,oe,oi,oa,olast}!=={hd,he,hi,ha,hl}))$fatal(1,"stream output changed while held");
                held=ov&&!ordy;
                if(held)begin holds=holds+1;hd=od;he=oe;hi=oi;ha=oa;hl=olast;end
                if(ov&&ordy)begin
                    if(od!==words[received%`WORDS][511:0]||oa!==words[received%`WORDS][524:512]||oi!=packet_words||
                       oe!=packet_epoch||olast!==(packet_words==packet_goal-1))
                        $fatal(1,"order mismatch word=%0d index=%0d address=%0d expected=%0d",received,oi,oa,words[received%`WORDS][524:512]);
                    received=received+1;packet_words=packet_words+1;
                end
                if(done)done_count=done_count+1;
            end
        end else held=0;
        if(cycle>200000)$fatal(1,"timeout");
    end
    task tick;begin @(posedge clk);#1;end endtask
    task config_job;begin
        while(!cr)tick();@(negedge clk);cv=1;tick();@(negedge clk);cv=0;
    end endtask
    integer n,c,m,i,j,base,goal,before_error;
    initial begin
        $readmemh("words.hex",words);$readmemh("cases.hex",cases);
        repeat(5)tick();@(negedge clk);rst_n=1;
        expected_error=1;
        for(n=0;n<5;n=n+1)begin
            epoch=200;channels=1;height=1;width=1;
            case(n)0:epoch=0;1:channels=0;2:height=0;3:width=0;4:begin channels=1024;height=640;width=640;end endcase
            config_job();repeat(2)tick();if(active)$fatal(1,"bad geometry admitted");
        end
        for(n=0;n<5;n=n+1)begin
            epoch=200;channels=1;height=(n==3 ? 2 : 1);width=1;mode=n==2;config_job();
            ie=(n==0 ? 201 : 200);idx=(n==1 ? 1 : 0);addr=(n==2 ? 1 : 0);ilast=n!=4;iv=1;
            #1;if(ov)$fatal(1,"malformed stream word exposed downstream");
            while(!ir)tick();tick();@(negedge clk);iv=0;repeat(2)tick();if(active)$fatal(1,"bad word did not invalidate job");
        end
        if(errors!=10)$fatal(1,"error count=%0d",errors);expected_error=0;
        for(n=0;n<2;n=n+1)begin
            force_hold=1;epoch=200;channels=1;height=1;width=1;mode=0;config_job();
            @(negedge clk);force_hold=1;ie=200;idx=0;addr=0;ilast=1;iv=1;
            repeat(2)tick();if(!ov)$fatal(1,"abort fixture not held");
            @(negedge clk);if(n==0)cancel=1;else rst_n=0;tick();
            @(negedge clk);cancel=0;rst_n=1;iv=0;force_hold=0;repeat(2)tick();
            if(active||ov)$fatal(1,"abort retained semantic transaction");
        end
        monitor=1;
        for(m=0;m<2;m=m+1)begin
            base=0;
            for(c=0;c<`CASES;c=c+1)begin
                channels=cases[c][10:0];height=cases[c][20:11];width=cases[c][30:21];goal=cases[c][44:31];
                epoch=200+m*`CASES+c;mode=m;packet_epoch=epoch;packet_words=0;packet_goal=goal;config_job();
                for(i=0;i<goal;i=i+1)begin
                    @(negedge clk);ie=packet_epoch;idx=m ? 13'h1fff : i;
                    addr=m ? words[base+i][524:512] : 13'h1fff;data=words[base+i][511:0];ilast=i==goal-1;iv=1;#1;
                    while(!ir)begin tick();@(negedge clk);#1;end
                    tick();@(negedge clk);iv=0;
                    if(i==0)begin epoch=0;channels=0;height=0;width=0;mode=!m;end
                end
                repeat(2)tick();if(packet_words!=goal||active)$fatal(1,"stream completion");base=base+goal;
            end
        end
        if(received!=2*`WORDS||done_count!=2*`CASES||holds==0)$fatal(1,"coverage counts");
        $display("NATIVE_STREAM_ORDER_PASS cases=%0d words=%0d stalls=%0d errors=%0d aborts=2 done=%0d",2*`CASES,received,holds,errors,done_count);
        $finish;
    end
endmodule
