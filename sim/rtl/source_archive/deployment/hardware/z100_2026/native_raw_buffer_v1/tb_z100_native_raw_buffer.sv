`timescale 1ns/1ps
module tb_z100_native_raw_buffer;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,iv=0,ordy=0;
    reg [31:0] ie=0,it=0;reg [4:0] site=0;reg last=0;reg [1023:0] data=0;
    wire ir,ov,olast;wire [31:0] oe,ot;wire [4:0] os;wire [1023:0] od;
    z100_native_raw_buffer dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),.in_valid(iv),.in_ready(ir),
        .in_epoch(ie),.in_token(it),.in_site(site),.in_last(last),.in_data(data),
        .out_valid(ov),.out_ready(ordy),.out_epoch(oe),.out_token(ot),.out_site(os),.out_last(olast),.out_data(od));
    reg [1093:0] queue[0:4095];integer head=0,tail=0,cycle=0,sent=0,received=0,stalls=0,simultaneous=0,full=0,aborts=0;
    reg held=0;reg [1093:0] helddata;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(!rst_n||cancel)begin head=0;tail=0;held=0;end
        else begin
            if(held&&(!ov||{oe,ot,os,olast,od}!==helddata))$fatal(1,"raw payload held corruption");
            held=ov&&!ordy;
            if(held)begin stalls=stalls+1;helddata={oe,ot,os,olast,od};end
            if(ov&&ordy)begin
                if(head>=tail||{oe,ot,os,olast,od}!==queue[head])$fatal(1,"raw FIFO order/data corruption");
                head=head+1;received=received+1;
            end
            if(iv&&ir)begin queue[tail]={ie,it,site,last,data};tail=tail+1;sent=sent+1;end
            if(iv&&ir&&ov&&ordy)simultaneous=simultaneous+1;
            if(!ir&&ov)full=full+1;
        end
        if(cycle>20000)$fatal(1,"buffer timeout");
    end
    task tick;begin @(posedge clk);#1;end endtask
    task packet(input integer n);integer j;begin
        ie=n^32'h59f2;it=n+1;site=n%20;last=n%20==19;
        for(j=0;j<32;j=j+1)data[j*32+:32]=(n*104729)^(j*65537)^32'hdeadbeef;
    end endtask
    integer i,n;
    initial begin
        repeat(5)tick();@(negedge clk);rst_n=1;
        // Explicit full-buffer cancel/reset, no RAM clearing is required.
        for(n=0;n<2;n=n+1)begin
            for(i=0;i<2;i=i+1)begin @(negedge clk);iv=1;packet(n*2+i);tick();end
            @(negedge clk);iv=0;#1;if(ir||!ov)$fatal(1,"full state missing");
            repeat(4)tick();@(negedge clk);if(n==0)cancel=1;else rst_n=0;
            tick();@(negedge clk);cancel=0;rst_n=1;aborts=aborts+1;#1;
            if(ov||!ir)$fatal(1,"abort visibility");
        end
        for(i=0;i<2048;i=i+1)begin
            @(negedge clk);iv=1;packet(i);ordy=(i<1000)||((cycle%13)>4);#1;
            while(!ir)begin tick();@(negedge clk);ordy=(cycle%13)>4;#1;end
            tick();
            if(i%23==0)begin @(negedge clk);iv=0;ordy=1;tick();end
        end
        @(negedge clk);iv=0;ordy=1;while(ov)tick();
        if(received!=2048||sent!=2052||stalls==0||full==0||simultaneous<900||aborts!=2)$fatal(1,"raw buffer coverage %0d/%0d",received,sent);
        $display("RAW_BUFFER_PASS accepted=%0d received=%0d stalls=%0d simultaneous=%0d full_cycles=%0d aborts=%0d",sent,received,stalls,simultaneous,full,aborts);
        $finish;
    end
endmodule
