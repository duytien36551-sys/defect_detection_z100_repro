`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_requant_factor32;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,cb=0,cwv=0,cc=0,iv=0;
    reg [31:0] ce=0,ie=0,it=0;reg [5:0] cl=0,cs=0;reg [30:0] cm=0;
    reg [4:0] site=0;reg last=0;reg [1023:0] data=0;
    wire cbr,cwr,ccr,cerr,ierr,ir,ov;reg ordy=0,hold_output=0;
    wire [31:0] oe,ot;wire [4:0] os;wire [5:0] ol;wire olast;wire [255:0] od;
    z100_requant_factor32 dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),
        .cfg_begin(cb),.cfg_begin_ready(cbr),.cfg_epoch(ce),.cfg_lanes(cl),
        .cfg_word_valid(cwv),.cfg_word_ready(cwr),.cfg_multiplier(cm),.cfg_shift(cs),
        .cfg_commit(cc),.cfg_commit_ready(ccr),.cfg_error(cerr),.input_error(ierr),
        .in_valid(iv),.in_ready(ir),.in_epoch(ie),.in_token(it),.in_site(site),.in_last(last),.in_data(data),
        .out_valid(ov),.out_ready(ordy),.out_epoch(oe),.out_token(ot),.out_site(os),.out_lanes(ol),.out_last(olast),.out_data(od));
    reg [1279:0] vectors[0:`VECTORS-1];reg [36:0] factors[0:`FACTORS-1];
    reg [5:0] lanes[0:`CASES-1];
    integer cycle=0,received=0,sent=0,case_index=0,holds=0,cfg_errors=0,input_errors=0;
    integer accepted_run=0,max_run=0,previous_accept=-10;
    reg monitor=0,expect_cfg_error=0,expect_input_error=0,held=0;
    reg [255:0] helddata;reg [31:0] heldtoken;
    always @(negedge clk)ordy=rst_n&&!hold_output&&(cycle%43)>10;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n&&!cancel)begin
            if(cerr)begin if(!expect_cfg_error)$fatal(1,"unexpected config error");cfg_errors=cfg_errors+1;end
            if(ierr)begin if(!expect_input_error)$fatal(1,"unexpected input error");input_errors=input_errors+1;end
            if(monitor)begin
                if(held&&(!ov||od!==helddata||ot!==heldtoken))$fatal(1,"vector changed under stall");
                held=ov&&!ordy;
                if(held)begin holds=holds+1;helddata=od;heldtoken=ot;end
                if(iv&&ir)begin
                    sent=sent+1;
                    if(previous_accept==cycle-1)accepted_run=accepted_run+1;else accepted_run=1;
                    previous_accept=cycle;if(accepted_run>max_run)max_run=accepted_run;
                end
                if(ov&&ordy)begin
                    if(received>=`VECTORS||od!==vectors[received][1279:1024]||ot!=received+1||oe!=200+case_index||
                       os!==((received%`PER_CASE)%20)||ol!==lanes[case_index]||olast!==((received%`PER_CASE)%20==19))
                        $fatal(1,"vector mismatch index=%0d token=%0d epoch=%0d lanes=%0d site=%0d",received,ot,oe,ol,os);
                    received=received+1;
                end
            end else if(ov&&!expect_input_error)$fatal(1,"unscored output escaped");
        end else held=0;
        if(cycle>100000)$fatal(1,"timeout received=%0d",received);
    end
    task tick;begin @(posedge clk);#1;end endtask
    task begin_cfg(input integer ep,input integer count);begin
        while(!cbr)tick();@(negedge clk);ce=ep;cl=count;cb=1;tick();@(negedge clk);cb=0;
    end endtask
    task word(input [30:0] mult,input [5:0] sh);begin
        @(negedge clk);cm=mult;cs=sh;cwv=1;#1;
        while(!cwr)begin tick();@(negedge clk);#1;end
        tick();@(negedge clk);cwv=0;
    end endtask
    task commit_cfg;begin
        while(!ccr)tick();@(negedge clk);cc=1;tick();@(negedge clk);cc=0;
    end endtask
    task abort_pending(input integer reset_it);begin
        begin_cfg(91,1);word(1,0);commit_cfg();
        @(negedge clk);ie=91;it=1;site=0;data=0;iv=1;#1;
        while(!ir)begin tick();@(negedge clk);#1;end
        tick();@(negedge clk);iv=0;if(reset_it)rst_n=0;else cancel=1;
        tick();@(negedge clk);rst_n=1;cancel=0;repeat(8)tick();
        if(ov||ir)$fatal(1,"abort did not invalidate pipeline/config");
    end endtask
    integer c,i,j,fcursor=0,vindex;
    initial begin
        $readmemh("vectors.hex",vectors);$readmemh("factors.hex",factors);$readmemh("lanes.hex",lanes);
        #250;repeat(5)tick();@(negedge clk);rst_n=1;
        expect_cfg_error=1;
        begin_cfg(0,1);repeat(2)tick();
        begin_cfg(1,0);repeat(2)tick();
        begin_cfg(1,33);repeat(2)tick();
        begin_cfg(1,1);word(0,30);repeat(2)tick();
        begin_cfg(1,2);word(1,30);commit_cfg();repeat(2)tick();
        begin_cfg(1,1);word(1,30);word(1,30);repeat(2)tick();
        if(cfg_errors!=6)$fatal(1,"config rejection count=%0d",cfg_errors);
        expect_cfg_error=0;
        abort_pending(0);abort_pending(1);
        // A stale producer invalidates all in-flight work, matching native ABI.
        begin_cfg(92,1);word(1,0);commit_cfg();
        expect_input_error=1;@(negedge clk);iv=1;ie=93;it=1;tick();@(negedge clk);iv=0;
        repeat(8)tick();expect_input_error=0;if(input_errors!=1||ir||ov)$fatal(1,"stale input was not rejected");
        monitor=1;
        for(c=0;c<`CASES;c=c+1)begin
            case_index=c;begin_cfg(200+c,lanes[c]);
            for(j=0;j<lanes[c];j=j+1)word(factors[fcursor+j][30:0],factors[fcursor+j][36:31]);
            fcursor=fcursor+lanes[c];commit_cfg();
            for(i=0;i<`PER_CASE;i=i+1)begin
                vindex=c*`PER_CASE+i;
                if(i%89==0)begin @(negedge clk);iv=0;tick();end
                @(negedge clk);data=vectors[vindex][1023:0];ie=200+c;it=vindex+1;site=i%20;last=i%20==19;iv=1;#1;
                while(!ir)begin tick();@(negedge clk);#1;end
                tick();
            end
            @(negedge clk);iv=0;
            while(received<(c+1)*`PER_CASE)tick();repeat(3)tick();
        end
        if(sent!=`VECTORS||received!=`VECTORS||holds==0||max_run<20)$fatal(1,"coverage counts");
        $display("REQUANT_FACTOR32_PASS cases=%0d vectors=%0d lane_values=%0d stalls=%0d max_ii1=%0d cfg_errors=%0d input_errors=%0d aborts=2",`CASES,received,`LANE_VALUES,holds,max_run,cfg_errors,input_errors);
        $finish;
    end
endmodule
