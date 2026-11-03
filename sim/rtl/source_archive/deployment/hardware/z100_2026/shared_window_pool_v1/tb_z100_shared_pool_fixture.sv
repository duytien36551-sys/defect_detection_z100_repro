`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_shared_pool_fixture;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cb=0,cwv=0,cwl=0,cc=0,jv=0,ordy=0;
    reg [31:0] epoch=200,cwe=200,je=200;
    reg [10:0] channels=0,jchannels=0;
    reg [9:0] height=0,width=20,jheight=0,jwidth=20;
    reg [12:0] cwa=0;
    reg [511:0] cdata=0;
    wire cbr,cwr,ccr,sv,loading,jr,ov,olast,done,err,active;
    wire [31:0] ae,oe;wire [12:0] oa;wire [511:0] od;wire [3:0] ec;
    z100_shared_pool_fixture dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),
        .cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(epoch),.cfg_channels(channels),.cfg_height(height),.cfg_width(width),
        .cfg_word_valid(cwv),.cfg_word_ready(cwr),.cfg_word_epoch(cwe),.cfg_word_address(cwa),.cfg_word_last(cwl),.cfg_data(cdata),
        .cfg_commit(cc),.cfg_commit_ready(ccr),.store_valid(sv),.loading(loading),.active_epoch(ae),
        .job_valid(jv),.job_ready(jr),.job_epoch(je),.job_channels(jchannels),.job_height(jheight),.job_width(jwidth),
        .out_valid(ov),.out_ready(ordy),.out_epoch(oe),.out_address(oa),.out_data(od),.out_last(olast),
        .done(done),.error_valid(err),.error_code(ec),.active(active));
    reg [511:0] input_words[0:`INPUT_WORDS-1],gold[0:`WORDS-1];
    reg [12:0] addresses[0:`WORDS-1],input_addresses[0:`INPUT_WORDS-1];reg [127:0] cases[0:`CASES-1];
    integer cycle=0,words=0,case_words=0,case_goal=0,case_epoch=0,done_count=0;
    integer descriptors=0,pool_results=0,holds=0,errors=0,monitor=0,aborts=0;
    reg expected_error=0,held=0;reg [511:0] helddata;reg [12:0] heldaddr;
    reg [31:0] heldepoch;reg heldlast;
    always @(negedge clk) ordy=rst_n&&(cycle%41)>10;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n&&!cancel)begin
            if(err)begin
                if(!expected_error||ec!=1)$fatal(1,"unexpected controller error code=%0d fw=%0d state=%0d config=%0d/%0d/%0d epoch=%0d word=%0d last=%0d",ec,dut.fw_code,dut.consumer.state,channels,height,width,epoch,cwa,cwl);
                errors=errors+1;
            end
            if(monitor)begin
                if(held&&(!ov||od!==helddata||oa!==heldaddr||oe!==heldepoch||olast!==heldlast))
                    $fatal(1,"held output changed");
                held=ov&&!ordy;
                if(held)begin holds=holds+1;helddata=od;heldaddr=oa;heldepoch=oe;heldlast=olast;end
                if(ov&&ordy)begin
                    if(words>=`WORDS||od!==gold[words]||oa!==addresses[words]||oe!=case_epoch||olast!==(case_words==case_goal-1))
                        $fatal(1,"gold mismatch word=%0d addr=%0d expected=%0d data=%0128x gold=%0128x",words,oa,addresses[words],od,gold[words]);
                    words=words+1;case_words=case_words+1;
                end
                if(dut.consumer.state==3&&dut.wr)descriptors=descriptors+1;
                if(dut.consumer.pool_valid&&dut.consumer.pool_ready)pool_results=pool_results+1;
                if(done)done_count=done_count+1;
            end else if(done)$fatal(1,"done from cancelled job");
        end else held=0;
        if(cycle>2000000)$fatal(1,"timeout state=%0d words=%0d",dut.consumer.state,words);
    end
    task tick;begin @(posedge clk);#1;end endtask
    task load_source(input integer count,input integer base);integer i;begin
        while(!cbr)tick();@(negedge clk);cb=1;tick();@(negedge clk);cb=0;
        for(i=0;i<count;i=i+1)begin
            cdata=input_words[base+i];cwa=input_addresses[base+i];cwl=i==count-1;cwe=epoch;cwv=1;#1;
            while(!cwr)begin tick();@(negedge clk);#1;end
            tick();@(negedge clk);cwv=0;
        end
        while(!ccr)tick();@(negedge clk);cc=1;tick();@(negedge clk);cc=0;
        tick();if(!sv||ae!=epoch)$fatal(1,"source commit failed");
    end endtask
    task start_job;begin
        while(!jr)tick();@(negedge clk);jv=1;tick();@(negedge clk);jv=0;
    end endtask
    task bad_job(input integer which);integer n;begin
        expected_error=1;n=errors;
        je=epoch;jchannels=channels;jheight=height;jwidth=20;
        case(which)
            0:je=epoch+1;
            1:jwidth=19;
            2:jchannels=0;
            3:jheight=0;
            4:jchannels=channels-1;
        endcase
        start_job();repeat(3)tick();
        if(errors!=n+1||active||!sv)$fatal(1,"invalid job not rejected independently");
        expected_error=0;
    end endtask
    integer c,i,input_cursor=0,count,goal,base_errors;
    initial begin
        $readmemh("input.hex",input_words);$readmemh("input_addresses.hex",input_addresses);$readmemh("golden.hex",gold);$readmemh("addresses.hex",addresses);$readmemh("cases.hex",cases);
        repeat(5)tick();@(negedge clk);rst_n=1;repeat(3)tick();
        if(jr)$fatal(1,"job accepted without committed source");
        // Cancel after real window activity, then reload the complete source.
        channels=cases[0][10:0];height=cases[0][20:11];count=cases[0][34:21];
        load_source(count,0);je=epoch;jchannels=channels;jheight=height;start_job();
        while(!(dut.consumer.state==3&&dut.consumer.tap_q==10))tick();
        @(negedge clk);cancel=1;tick();@(negedge clk);cancel=0;aborts=aborts+1;
        repeat(10)tick();if(active||sv||ov||jr)$fatal(1,"cancel did not invalidate source/job");
        // Reset a separate in-flight pool accumulation and reload again.
        load_source(count,0);start_job();while(!dut.consumer.pool_active)tick();
        @(negedge clk);rst_n=0;tick();@(negedge clk);rst_n=1;aborts=aborts+1;
        repeat(10)tick();if(active||sv||ov||jr)$fatal(1,"reset did not invalidate source/job");
        monitor=1;
        for(c=0;c<`CASES;c=c+1)begin
            channels=cases[c][10:0];height=cases[c][20:11];count=cases[c][34:21];goal=cases[c][48:35];
            epoch=200+c;case_epoch=epoch;case_goal=goal;case_words=0;
            load_source(count,input_cursor);input_cursor=input_cursor+count;
            if(c==0)for(i=0;i<5;i=i+1)bad_job(i);
            je=epoch;jchannels=channels;jheight=height;jwidth=20;start_job();
            // In-flight job mutations and feature-load attempts must not change latched work.
            repeat(8)tick();@(negedge clk);je=0;jchannels=0;jheight=0;jwidth=0;cb=1;cwv=1;cc=1;
            #1;if(cbr||cwr||ccr||jr)$fatal(1,"active ownership violation");
            repeat(3)tick();@(negedge clk);cb=0;cwv=0;cc=0;
            while(done_count<c+1)tick();
            if(case_words!=case_goal||active)$fatal(1,"completion count/state");
        end
        if(words!=`WORDS||descriptors!=`VECTORS*25||pool_results!=`VECTORS||holds==0||errors!=5||aborts!=2)
            $fatal(1,"coverage words=%0d descriptors=%0d vectors=%0d holds=%0d errors=%0d",words,descriptors,pool_results,holds,errors);
        $display("SHARED_POOL_FIXTURE_PASS cases=%0d words=%0d descriptors=%0d vectors=%0d stalls=%0d invalid_jobs=%0d aborts=%0d done=%0d",`CASES,words,descriptors,pool_results,holds,errors,aborts,done_count);
        $finish;
    end
endmodule
