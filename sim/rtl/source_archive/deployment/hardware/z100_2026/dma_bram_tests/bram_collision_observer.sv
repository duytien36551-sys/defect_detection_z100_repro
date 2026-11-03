`timescale 1ns/1ps
// Passive checker. Read/write addresses are XPM word addresses, not AXIS beats.
module bram_collision_observer #(
    parameter integer SELECTED=1, WIDTH=39, AW=7, INIT_SKIP=64,
    parameter integer EXPECT_DIAGNOSTICS=0
) (
    input wire clk, ena, wea, enb, rsta, rstb,
    input wire [AW-1:0] addra, addrb
);
    integer edges=0, cycles=0, writes=0, reads=0, concurrent=0;
    integer collisions=0, unknowns=0, reset_cycles=0, reset_writes=0, reset_reads=0;
    integer write_wraps=0, read_wraps=0, skipped_writes=0;
    reg [(1<<AW)-1:0] write_seen=0, read_seen=0;
    reg [AW-1:0] prev_write=0, prev_read=0;
    reg prev_write_valid=0, prev_read_valid=0;
    reg wr, rd;
    // Active-region sampling sees the same pre-NBA inputs as synchronous RAM.
    // Reset does not disable checking: it only separates pointer-wrap epochs.
    always @(posedge clk) if (SELECTED) begin
        edges=edges+1;
        wr=(ena===1'b1 && wea===1'b1); rd=(enb===1'b1);
        if (edges<=INIT_SKIP) begin
            if (wr) skipped_writes=skipped_writes+1;
        end else begin
            cycles=cycles+1;
            if ((ena!==1'b0 && ena!==1'b1) || (enb!==1'b0 && enb!==1'b1) ||
                (ena===1'b1 && wea!==1'b0 && wea!==1'b1) ||
                (rsta!==1'b0 && rsta!==1'b1) || (rstb!==1'b0 && rstb!==1'b1) ||
                (wr && $isunknown(addra)) || (rd && $isunknown(addrb))) begin
                unknowns=unknowns+1;
                if (!EXPECT_DIAGNOSTICS) $display("FAIL BRAM_OBS unknown path=%m time=%0t",$time);
            end
            if (rsta===1'b1 || rstb===1'b1) begin
                reset_cycles=reset_cycles+1;
                prev_write_valid=0; prev_read_valid=0;
                if(wr) reset_writes=reset_writes+1;
                if(rd) reset_reads=reset_reads+1;
            end
            if(wr && !$isunknown(addra)) begin
                writes=writes+1; write_seen[addra]=1;
                if(prev_write_valid && prev_write=={AW{1'b1}} && addra==0) write_wraps=write_wraps+1;
                if(rsta===1'b0 && rstb===1'b0) begin prev_write=addra; prev_write_valid=1; end
            end
            if(rd && !$isunknown(addrb)) begin
                reads=reads+1; read_seen[addrb]=1;
                if(prev_read_valid && prev_read=={AW{1'b1}} && addrb==0) read_wraps=read_wraps+1;
                if(rsta===1'b0 && rstb===1'b0) begin prev_read=addrb; prev_read_valid=1; end
            end
            if(wr && rd) begin
                concurrent=concurrent+1;
                if(!$isunknown({addra,addrb}) && addra==addrb) begin
                    collisions=collisions+1;
                    if(!EXPECT_DIAGNOSTICS) $display("FAIL BRAM_OBS collision path=%m time=%0t address=%0d reset=%b%b",$time,addra,rsta,rstb);
                end
            end
        end
    end
    final if(SELECTED) begin
        $display("BRAM_OBS path=%m width=%0d cycles=%0d init_skip=%0d writes=%0d reads=%0d concurrent=%0d collisions=%0d unknowns=%0d reset_cycles=%0d reset_writes=%0d reset_reads=%0d write_wraps=%0d read_wraps=%0d write_addresses=%0d read_addresses=%0d skipped_writes=%0d",
            WIDTH,cycles,INIT_SKIP,writes,reads,concurrent,collisions,unknowns,reset_cycles,reset_writes,reset_reads,
            write_wraps,read_wraps,$countones(write_seen),$countones(read_seen),skipped_writes);
    end
endmodule
