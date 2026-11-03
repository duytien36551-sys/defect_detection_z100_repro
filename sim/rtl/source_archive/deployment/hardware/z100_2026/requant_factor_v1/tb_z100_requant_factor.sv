`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_requant_factor;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,iv=0,ordy=1;
    reg signed [31:0] value=0;
    reg [30:0] multiplier=1;reg [5:0] shift=0;reg [31:0] token=0;
    wire ir,ov,err;wire [31:0] ot;wire signed [7:0] od;wire signed [62:0] product;
    z100_requant_factor dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),.in_valid(iv),.in_ready(ir),
        .in_value(value),.in_multiplier(multiplier),.in_shift(shift),.in_token(token),
        .out_valid(ov),.out_ready(ordy),.out_token(ot),.out_data(od),.out_product(product),.error_valid(err));
    reg [148:0] vectors[0:`VECTORS-1];
    integer cycle=0,sent=0,received=0,holds=0,errors=0,aborts=0;
    reg monitor=0,held=0,expected_error=0;
    reg [31:0] holdtoken;reg signed [7:0] holddata;reg signed [62:0] holdproduct;
    always @(negedge clk)ordy=rst_n&&(cycle%37)>8;
    always @(posedge clk)begin
        cycle=cycle+1;
        if(rst_n&&!cancel)begin
            if(err)begin if(!expected_error)$fatal(1,"unexpected factor error");errors=errors+1;end
            if(monitor)begin
                if(held&&(!ov||ot!==holdtoken||od!==holddata||product!==holdproduct))$fatal(1,"stall corruption");
                held=ov&&!ordy;
                if(held)begin holds=holds+1;holdtoken=ot;holddata=od;holdproduct=product;end
                if(iv&&ir)sent=sent+1;
                if(ov&&ordy)begin
                    if(received>=`VECTORS||ot!=received+1||od!==vectors[received][85:78]||product!==vectors[received][148:86])
                        $fatal(1,"factor mismatch index=%0d token=%0d raw=%0d M=%0d shift=%0d got=%0d want=%0d product=%0d expectedProduct=%0d",received,ot,$signed(vectors[received][31:0]),vectors[received][62:32],vectors[received][68:63],od,$signed(vectors[received][85:78]),product,$signed(vectors[received][148:86]));
                    received=received+1;
                end
            end else if(ov)$fatal(1,"cancelled/reset input escaped");
        end else held=0;
        if(cycle>10000000)$fatal(1,"factor timeout");
    end
    task tick;begin @(posedge clk);#1;end endtask
    task inject_cancel(input integer reset_it);begin
        @(negedge clk);iv=1;value=-2147483648;multiplier=2147483647;shift=31;token=32'hdead;
        while(!ir)tick();tick();@(negedge clk);iv=0;
        if(reset_it)rst_n=0;else cancel=1;
        tick();@(negedge clk);rst_n=1;cancel=0;aborts=aborts+1;
        repeat(10)tick();
    end endtask
    integer i;
    initial begin
        $readmemh("vectors.hex",vectors);
        #250;repeat(4)tick();@(negedge clk);rst_n=1;
        inject_cancel(0);inject_cancel(1);
        expected_error=1;@(negedge clk);iv=1;multiplier=0;tick();@(negedge clk);iv=0;
        repeat(8)tick();expected_error=0;if(errors!=1)$fatal(1,"zero factor accepted");
        monitor=1;
        for(i=0;i<`VECTORS;i=i+1)begin
            if(i%97==0)begin @(negedge clk);iv=0;tick();end
            @(negedge clk);value=vectors[i][31:0];multiplier=vectors[i][62:32];shift=vectors[i][68:63];token=i+1;iv=1;#1;
            while(!ir)begin tick();@(negedge clk);#1;end
            tick();
        end
        @(negedge clk);iv=0;
        while(received<`VECTORS)tick();
        if(sent!=`VECTORS||holds==0||errors!=1||aborts!=2)$fatal(1,"coverage failure");
        $display("REQUANT_FACTOR_PASS vectors=%0d received=%0d stalls=%0d invalid=%0d aborts=%0d",sent,received,holds,errors,aborts);
        $finish;
    end
endmodule
