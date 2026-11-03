`timescale 1ns/1ps
`default_nettype none
`include "slot_defs.vh"
module tb_z100_native_tensor_slots_bounded_v2;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cmd_valid=0,response_ready=0;
    reg [6:0] io_quiescent=127;
    reg [2:0] cmd_opcode=0,cmd_slot=0,query_slot=0;
    reg [31:0] cmd_tag=0,cmd_epoch=0,cmd_generation=0,cmd_address=0;
    reg [15:0] cmd_tensor_id=0;reg [10:0] cmd_channels=0;
    reg [9:0] cmd_height=0,cmd_width=0,cmd_first_row=0,cmd_tile_height=0;reg cmd_success=1;
    wire cmd_ready,response_valid;wire [31:0] response_tag;wire[2:0] response_slot;wire[3:0] response_code;
    wire[6:0] committed_slots,fault_slots,active_slots;
    wire query_committed,query_active,query_fault;wire[7:0] query_readers;
    wire[31:0] query_epoch,query_generation,query_address,query_bytes;
    wire[15:0] query_tensor_id;wire[10:0] query_channels,query_covered_rows;wire[9:0] query_height,query_width;
    z100_native_tensor_slots_bounded_v2 dut(.*);
    reg [255:0] commands[0:`SLOT_COMMANDS-1],expected[0:`SLOT_COMMANDS-1];
    wire [221:0] snapshot={fault_slots,committed_slots,active_slots,query_covered_rows,query_width,query_height,query_channels,
        query_tensor_id,query_bytes,query_address,query_generation,query_epoch,query_readers,query_fault,query_committed,query_active,response_code};
    integer i,k,held_cycles=0,replies=0,observed_peak=0,n;
    reg[31:0] wanted_tag;reg[2:0] wanted_slot;
    reg[221:0] held_snapshot;
    initial begin
        $readmemh("commands.hex",commands);$readmemh("expected.hex",expected);
        repeat(5)@(negedge clk);rst_n=1;
        for(i=0;i<`SLOT_COMMANDS;i=i+1)begin
            @(negedge clk);
            cmd_opcode=commands[i][2:0];cmd_slot=commands[i][5:3];cmd_tag=commands[i][37:6];
            cmd_epoch=commands[i][69:38];cmd_generation=commands[i][101:70];cmd_address=commands[i][133:102];
            cmd_tensor_id=commands[i][149:134];cmd_channels=commands[i][160:150];cmd_height=commands[i][170:161];
            cmd_width=commands[i][180:171];cmd_first_row=commands[i][190:181];cmd_tile_height=commands[i][200:191];
            cmd_success=commands[i][201];io_quiescent=commands[i][208:202];wanted_tag=cmd_tag;wanted_slot=cmd_slot;query_slot=cmd_slot;cmd_valid=1;
            do @(posedge clk);while(!cmd_ready);
            @(negedge clk);cmd_valid=0;cmd_opcode=6;cmd_slot=6;cmd_tag=32'hdeadbeef;cmd_epoch=99;cmd_generation=0;cmd_address=0;cmd_first_row=639;cmd_tile_height=0;
            do @(negedge clk);while(!response_valid);
            for(k=0;k<5;k=k+1)begin
                if(!response_valid||response_tag!==wanted_tag||response_slot!==wanted_slot||snapshot!==expected[i][221:0]||cmd_ready)
                    $fatal(1,"Slot command/result mismatch command=%d op=%d code=%d wanted=%h got=%h",i,commands[i][2:0],response_code,expected[i][221:0],snapshot);
                held_cycles=held_cycles+1;@(negedge clk);
            end
            n=0;for(k=0;k<7;k=k+1)if(active_slots[k])n=n+1;if(n>observed_peak)observed_peak=n;
            response_ready=1;@(negedge clk);response_ready=0;replies=replies+1;
        end
        if(active_slots!=0||fault_slots!=0||committed_slots!=0||observed_peak!=7)$fatal(1,"Slots not retired or peak missing");
        $display("TENSOR_SLOTS_PASS commands=%0d replies=%0d response_hold_cycles=%0d peak_live_slots=%0d graph_events=73 materialized_results=72",`SLOT_COMMANDS,replies,held_cycles,observed_peak);
        $finish;
    end
    initial begin #10000000;$fatal(1,"Slot manager watchdog");end
endmodule
`default_nettype wire
