`timescale 1ns/1ps
`default_nettype none
`include "parameter_defs.vh"
module tb_z100_native_parameter_bridge;
    reg clk=0;always #5 clk=~clk;reg rst_n=0,cancel=0,cmd_valid=0,response_ready=0;
    reg[3:0] cmd_operation=0;reg[31:0] cmd_epoch=200,cmd_tag=0,cmd_index=0;
    reg[10:0] cmd_groups=0;reg[5:0] cmd_lanes=0;reg[1023:0] cmd_data=0;
    wire cmd_ready,response_valid,response_error,configured,child_cancel,fault;wire[31:0] response_tag;
    wire[31:0] cfg_epoch;wire[10:0] cfg_groups;wire[5:0] cfg_lanes;
    wire mac_begin,mac_begin_ready,mac_weight,mac_weight_ready,mac_bias,mac_bias_ready,mac_commit,mac_commit_ready,mac_error,mac_loaded;
    wire[31:0] mac_epoch;wire[1023:0] mac_data;
    wire factor_begin,factor_begin_ready,factor_word,factor_word_ready,factor_commit,factor_commit_ready,factor_error;
    wire[30:0] factor_multiplier;wire[5:0] factor_shift;
    wire unary_begin,unary_begin_ready,unary_word,unary_word_ready,unary_commit,unary_commit_ready,unary_error,unary_loaded;
    wire[7:0] unary_data;wire[31:0] unary_epoch;
    reg block_child=0,inject_child_error=0;
    wire mbready,mwready,mbiasready,mcready,fbready,fwready,fcready,ubready,uwready,ucready;
    wire real_mac_error,factor_cfg_error,factor_input_error;
    assign mac_begin_ready=mbready&&!block_child;assign mac_weight_ready=mwready&&!block_child;
    assign mac_bias_ready=mbiasready&&!block_child;assign mac_commit_ready=mcready&&!block_child;
    assign factor_begin_ready=fbready&&!block_child;assign factor_word_ready=fwready&&!block_child;assign factor_commit_ready=fcready&&!block_child;
    assign unary_begin_ready=ubready&&!block_child;assign unary_word_ready=uwready&&!block_child;assign unary_commit_ready=ucready&&!block_child;
    assign mac_error=real_mac_error||inject_child_error;assign factor_error=factor_cfg_error||factor_input_error;
    z100_native_parameter_bridge dut(.*);
    // SITES1 only reduces idle arithmetic replication. Config RAM/ports/groups,
    // bias32 and exact-factor/unary32 modules are the same production sources.
    z100_window_mac #(.SITES(1)) mac(.clk(clk),.rst_n(rst_n),.cancel(child_cancel),
        .cfg_begin(mac_begin&&!block_child),.cfg_begin_ready(mbready),.cfg_epoch(cfg_epoch),.cfg_groups(cfg_groups),
        .cfg_weight_valid(mac_weight&&!block_child),.cfg_weight_ready(mwready),.cfg_weights(mac_data),
        .cfg_bias_valid(mac_bias&&!block_child),.cfg_bias_ready(mbiasready),.cfg_bias(mac_data),
        .cfg_commit(mac_commit&&!block_child),.cfg_commit_ready(mcready),.weights_valid(mac_loaded),.weights_epoch(mac_epoch),.error_valid(real_mac_error),.error_code(),
        .run_valid(1'b0),.run_ready(),.run_epoch(32'd0),.run_token(32'd0),.run_lanes(6'd0),.run_sites(5'd0),
        .act_valid(1'b0),.act_ready(),.act_token(32'd0),.act_last(1'b0),.act_data(32'd0),
        .out_valid(),.out_ready(1'b1),.out_token(),.out_site(),.out_last(),.out_lanes(),.out_data(),.out_overflow());
    z100_requant_factor32 factor(.clk(clk),.rst_n(rst_n),.cancel(child_cancel),
        .cfg_begin(factor_begin&&!block_child),.cfg_begin_ready(fbready),.cfg_epoch(cfg_epoch),.cfg_lanes(cfg_lanes),
        .cfg_word_valid(factor_word&&!block_child),.cfg_word_ready(fwready),.cfg_multiplier(factor_multiplier),.cfg_shift(factor_shift),
        .cfg_commit(factor_commit&&!block_child),.cfg_commit_ready(fcready),.cfg_error(factor_cfg_error),.input_error(factor_input_error),
        .in_valid(1'b0),.in_ready(),.in_epoch(32'd0),.in_token(32'd0),.in_site(5'd0),.in_last(1'b0),.in_data(1024'd0),
        .out_valid(),.out_ready(1'b1),.out_epoch(),.out_token(),.out_site(),.out_lanes(),.out_last(),.out_data());
    z100_unary32 unary(.clk(clk),.rst_n(rst_n),.cancel(child_cancel),
        .cfg_begin(unary_begin&&!block_child),.cfg_begin_ready(ubready),.cfg_epoch(cfg_epoch),
        .cfg_word_valid(unary_word&&!block_child),.cfg_word_ready(uwready),.cfg_data(unary_data),
        .cfg_commit(unary_commit&&!block_child),.cfg_commit_ready(ucready),.error_valid(unary_error),.error_code(),
        .store_valid(unary_loaded),.active_epoch(unary_epoch),.loading(),
        .in_valid(1'b0),.in_ready(),.in_epoch(32'd0),.in_token(32'd0),.in_lanes(6'd0),.in_last(1'b0),.in_data(256'd0),
        .out_valid(),.out_ready(1'b1),.out_epoch(),.out_token(),.out_lanes(),.out_last(),.out_data());
    reg[1140:0] packets[0:`PARAMETER_COMMANDS-1];reg[1140:0] packet;
    reg[31:0] probe_index=0;wire[1023:0] stored_weight;wire[127:0] stored_unary;
    genvar tap,replica;generate for(tap=0;tap<4;tap=tap+1)begin:weight_probe
        assign stored_weight[tap*256+:256]=mac.gen_weights[tap].memory[probe_index[9:0]];
    end
    for(replica=0;replica<16;replica=replica+1)begin:unary_probe
        assign stored_unary[replica*8+:8]=unary.gen_table[replica].table_mem[probe_index[7:0]];
    end endgenerate
    integer i,j,commands=0,jobs=0,checked_weight_bytes=0,checked_unary_bytes=0,checked_biases=0,checked_factors=0,held_cycles=0,child_stalls=0;
    reg[3:0] wanted_op;reg[31:0] wanted_tag;reg[1023:0] payload;
    task pulse_cancel;begin @(negedge clk);cancel=1;@(negedge clk);cancel=0;repeat(2)@(negedge clk);
        if(configured||fault||mac_loaded||unary_loaded||factor.loaded)$fatal(1,"Cancel retained partial configuration");end endtask
    task submit(input[1140:0] p,input integer stall_child);
        begin
            @(negedge clk);{cmd_data,cmd_lanes,cmd_groups,cmd_index,cmd_tag,cmd_epoch,cmd_operation}=p;cmd_valid=1;block_child=stall_child;
            wanted_op=cmd_operation;wanted_tag=cmd_tag;payload=cmd_data;probe_index=cmd_index;
            do @(posedge clk);while(!cmd_ready);
            @(negedge clk);cmd_valid=0;cmd_data=~payload;cmd_epoch=99;cmd_index=32'hffffffff;cmd_operation=0;
            if(stall_child)begin
                repeat(3)begin @(negedge clk);if(response_valid||configured)$fatal(1,"Configuration advanced before child handshake");child_stalls=child_stalls+1;end
                block_child=0;
            end
            do @(negedge clk);while(!response_valid);
        end
    endtask
    initial begin
        $readmemh("parameter_packets.hex",packets);repeat(5)@(negedge clk);rst_n=1;
        for(i=0;i<`PARAMETER_COMMANDS;i=i+1)begin
            packet=packets[i];submit(packet,i%97==0);
            if(response_error||fault||response_tag!==wanted_tag)$fatal(1,"Real parameter config rejected command=%d op=%d",i,wanted_op);
            case(wanted_op)
                4:begin if(stored_weight!==payload)$fatal(1,"Physical weight RAM differs");checked_weight_bytes=checked_weight_bytes+128;end
                5:for(j=0;j<32;j=j+1)begin if(mac.bias[j]!==payload[j*32+:32])$fatal(1,"Physical bias differs");checked_biases=checked_biases+1;end
                6:begin if(factor.multipliers[probe_index]!==payload[30:0]||factor.shifts[probe_index]!==payload[37:32])$fatal(1,"Actual factor config differs");checked_factors=checked_factors+1;end
                7:begin if(stored_unary!=={16{payload[7:0]}})$fatal(1,"Actual unary replica config differs");checked_unary_bytes=checked_unary_bytes+16;end
                10:begin
                    if(!configured||!mac_loaded||mac_epoch!=200||!factor.loaded||factor.epoch!=200||!unary_loaded||unary_epoch!=200)$fatal(1,"Configured before all actual children committed");jobs=jobs+1;
                end
            endcase
            if(wanted_op!=10&&configured)$fatal(1,"Early configuration publication");
            repeat(2)begin @(negedge clk);if(!response_valid||response_error||response_tag!==wanted_tag)$fatal(1,"Config response changed under hold");held_cycles=held_cycles+1;end
            response_ready=1;@(negedge clk);response_ready=0;commands=commands+1;
        end
        pulse_cancel();packet=packets[0];packet[3:0]=2;submit(packet,0);
        if(!fault||!response_error||configured)$fatal(1,"Wrong operation accepted");pulse_cancel();
        packet=packets[0];submit(packet,0);response_ready=1;@(negedge clk);response_ready=0;
        packet=packets[1];packet[67:36]=0; // wrong tag (zero)
        submit(packet,0);if(!fault||!response_error)$fatal(1,"Zero tag accepted");pulse_cancel();
        packet=packets[0];submit(packet,0);response_ready=1;@(negedge clk);response_ready=0;
        packet=packets[1];packet[35:4]=201;submit(packet,0);if(!fault||!response_error)$fatal(1,"Foreign epoch accepted");pulse_cancel();
        // Cancel a captured begin before it can reach its child.
        @(negedge clk);packet=packets[0];{cmd_data,cmd_lanes,cmd_groups,cmd_index,cmd_tag,cmd_epoch,cmd_operation}=packet;cmd_valid=1;block_child=1;
        do @(posedge clk);while(!cmd_ready);@(negedge clk);cmd_valid=0;cancel=1;
        @(negedge clk);cancel=0;block_child=0;repeat(2)@(negedge clk);
        if(mac_loaded||unary_loaded||configured||fault||response_valid)$fatal(1,"Cancelled begin survived");
        if(commands!=`PARAMETER_COMMANDS||jobs!=173||checked_factors!=5419||checked_biases!=5536)$fatal(1,"Incomplete current model config");
        $display("PARAMETER_BRIDGE_PASS jobs=%0d commands=%0d weight_bytes=%0d bias_values=%0d factors=%0d unary_replica_bytes=%0d held_response_cycles=%0d child_stall_cycles=%0d protocol_rejects=3 captured_cancel=1",jobs,commands,checked_weight_bytes,checked_biases,checked_factors,checked_unary_bytes,held_cycles,child_stalls);
        $finish;
    end
    initial begin #50000000;$fatal(1,"Parameter bridge watchdog");end
endmodule
`default_nettype wire
