`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_native_view_word;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cb=0,cwv=0,cc=0,iv=0,ordy=1,force_hold=0;
    reg [31:0] ce=1,ie=200,it=0,te=1;reg [5:0] cid=0,iid=0;
    reg [63:0] cd=0;reg [3:0] sx=0;reg [1:0] shift=0;reg [2:0] channels=4;reg [4:0] xcount=16;
    reg ilast=0;reg [511:0] data=0;wire cbr,cwr,ccr,sv,loading,err,ir,ov,olast;wire [2:0] ec;
    wire [31:0] oe,ot;wire [511:0] od;
    z100_native_view_word dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(ce),.cfg_lut_id(cid),
        .cfg_word_valid(cwv),.cfg_word_ready(cwr),.cfg_data(cd),.cfg_commit(cc),.cfg_commit_ready(ccr),.store_valid(sv),.loading(loading),.error_valid(err),.error_code(ec),
        .in_valid(iv),.in_ready(ir),.in_epoch(ie),.in_token(it),.in_table_epoch(te),.in_lut_id(iid),.in_source_first_x(sx),.in_nearest_shift(shift),
        .in_channels(channels),.in_x_count(xcount),.in_last(ilast),.in_data(data),.out_valid(ov),.out_ready(ordy),.out_epoch(oe),.out_token(ot),.out_last(olast),.out_data(od));
    reg [1038:0] vectors[0:`WORDS-1];reg [63:0] table_words[0:`TABLES*32-1];reg [31:0] counts[0:`TABLES-1];
    integer cycle=0,sent=0,received=0,holds=0,errors=0,aborts=0,cfg_beats=0,streak=0,max_streak=0,last_accept=-10;
    reg score=0,expect_error=0,held=0;
    reg [576:0] held_output;
    always @(negedge clk)ordy=rst_n&&!force_hold&&(cycle%43)>10;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n&&!cancel)begin
            if(err)begin if(!expect_error)$fatal(1,"unexpected view error=%0d",ec);errors=errors+1;end
            if(score)begin
                if(held&&(!ov||{oe,ot,olast,od}!==held_output))$fatal(1,"view word output changed while held");
                held=ov&&!ordy;
                if(held)begin holds=holds+1;held_output={oe,ot,olast,od};end
                if(cwv&&cwr)cfg_beats=cfg_beats+1;
                if(iv&&ir)begin
                    sent=sent+1;if(last_accept==cycle-1)streak=streak+1;else streak=1;
                    last_accept=cycle;if(streak>max_streak)max_streak=streak;
                end
                if(ov&&ordy)begin
                    if(received>=`WORDS||od!==vectors[received][1023:512]||oe!=200||ot!=received+1||olast!==vectors[received][1038])
                        $fatal(1,"view word mismatch index=%0d token=%0d got=%0128x expected=%0128x",received,ot,od,vectors[received][1023:512]);
                    received=received+1;
                end
            end
        end else held=0;
        if(cycle>5000000)$fatal(1,"view word timeout received=%0d",received);
    end
    task tick;begin @(posedge clk);#1;end endtask
    task begin_table(input integer ep,input integer id);begin
        while(!cbr)tick();@(negedge clk);ce=ep;cid=id;cb=1;tick();@(negedge clk);cb=0;
    end endtask
    task write_table(input integer n,input integer tableid);integer i;begin
        for(i=0;i<n;i=i+1)begin
            @(negedge clk);cwv=1;cd=table_words[tableid*32+(i%32)];#1;
            if(!cwr)$fatal(1,"view table loader not ready");tick();@(negedge clk);cwv=0;
        end
    end endtask
    task commit_table;begin
        while(!ccr)tick();@(negedge clk);cc=1;tick();@(negedge clk);cc=0;
    end endtask
    task load_table(input integer tableid);begin
        begin_table(tableid+1,tableid);write_table(32,tableid);commit_table();if(!sv||loading)$fatal(1,"view table commit");
    end endtask
    integer i,t,j,cursor=0,goal;
    initial begin
        $readmemh("vectors.hex",vectors);$readmemh("tables.hex",table_words);$readmemh("counts.hex",counts);
        repeat(5)tick();@(negedge clk);rst_n=1;
        expect_error=1;begin_table(0,0);repeat(2)tick();
        begin_table(1,0);write_table(31,0);commit_table();repeat(2)tick();
        begin_table(1,0);write_table(33,0);repeat(2)tick();
        if(errors!=3)$fatal(1,"view configuration rejection count");expect_error=0;
        load_table(0);
        expect_error=1;
        for(i=0;i<10;i=i+1)begin
            ie=200;it=1;te=1;iid=0;sx=0;shift=0;channels=4;xcount=16;
            case(i)0:ie=0;1:it=0;2:te=2;3:iid=1;4:channels=0;5:channels=5;6:xcount=0;7:xcount=17;8:shift=3;9:sx=15;endcase
            @(negedge clk);iv=1;#1;while(!ir)begin tick();@(negedge clk);#1;end
            tick();@(negedge clk);iv=0;repeat(2)tick();if(!sv||ov)$fatal(1,"bad view metadata disturbed table or exposed result");
        end
        expect_error=0;if(errors!=13)$fatal(1,"view metadata rejection count");
        for(i=0;i<2;i=i+1)begin
            load_table(0);force_hold=1;repeat(2)tick();
            @(negedge clk);ie=200;it=1;te=1;iid=0;sx=0;shift=0;channels=4;xcount=16;iv=1;
            tick();@(negedge clk);iv=0;#1;if(!ov)$fatal(1,"view abort fixture not held");
            cb=1;#1;if(cbr)$fatal(1,"view reload while result held");tick();@(negedge clk);cb=0;
            if(i==0)cancel=1;else rst_n=0;tick();@(negedge clk);cancel=0;rst_n=1;force_hold=0;
            if(ov||sv||loading)$fatal(1,"view abort not invalidated");aborts=aborts+1;
        end
        score=1;
        for(t=0;t<`TABLES;t=t+1)begin
            load_table(t);goal=cursor+counts[t];
            for(j=cursor;j<goal;j=j+1)begin
                if(j%97==0)begin @(negedge clk);iv=0;tick();end
                @(negedge clk);ie=200;it=j+1;te=t+1;iid=t;data=vectors[j][511:0];sx=vectors[j][1027:1024];shift=vectors[j][1029:1028];
                channels=vectors[j][1032:1030];xcount=vectors[j][1037:1033];ilast=vectors[j][1038];iv=1;#1;
                while(!ir)begin tick();@(negedge clk);#1;end
                tick();
            end
            @(negedge clk);iv=0;while(received<goal)tick();cursor=goal;
        end
        if(sent!=`WORDS||received!=`WORDS||cfg_beats!=`TABLES*32||holds==0||max_streak<20||aborts!=2)$fatal(1,"view word coverage");
        $display("NATIVE_VIEW_WORD_PASS tables=%0d vectors=%0d output_bytes=%0d cfg_beats=%0d stalls=%0d max_ii1=%0d errors=%0d aborts=%0d",`TABLES,received,received*64,cfg_beats,holds,max_streak,errors,aborts);
        $finish;
    end
endmodule
