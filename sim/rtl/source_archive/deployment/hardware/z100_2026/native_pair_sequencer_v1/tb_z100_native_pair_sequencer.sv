`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_pair_sequencer;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cfg_begin=0,cfg_valid=0,cfg_commit=0,start=0,cancel=0,clear_fault=0,downstream_quiescent=1;
    reg [9:0] cfg_channels=0,cfg_height=0,cfg_width=0;
    reg [31:0] cfg_table_epoch=0,cfg_source_address=0,cfg_region_begin=0,cfg_source_generation=0,cfg_row_stride=0,cfg_x_stride=0;
    reg [32:0] cfg_region_end=0;
    reg [1:0] cfg_context=0,cfg_shift=0;
    reg [31:0] frame_epoch=200,timeout_cycles=100000;
    wire cfg_begin_ready,cfg_ready,cfg_commit_ready,store_valid,start_ready,active,fault,dispatch_done,req_valid,req_last;
    wire [3:0] fault_code,req_source_first_x;
    wire [4:0] req_valid_x;
    wire [31:0] req_epoch,req_address,req_source_generation,req_table_epoch;
    wire [1:0] req_context,req_shift;
    wire [11:0] req_native_word;
    integer cycles=0;
    reg block_sink=0,score=0;
    wire req_ready=!block_sink&&cycles%7!=0&&cycles%7!=1;
    z100_native_pair_sequencer dut(.*);
    reg [63:0] geometry[0:60];reg [255:0] templates[0:1031];reg [159:0] expected[0:68183];
    wire [153:0] observed={req_epoch,req_table_epoch,req_last,req_native_word,req_valid_x,req_source_first_x,req_shift,req_context,req_source_generation,req_address};
    integer cursor=0,hold_count=0,requests=0,tiles=0,negative=0,blocked_checks=0;
    reg held=0;reg[153:0] held_payload;
    always @(posedge clk)begin
        cycles<=cycles+1;
        if(rst_n&&score)begin
            if(held&&(!req_valid||observed!==held_payload))$fatal(1,"Request changed under backpressure");
            held<=req_valid&&!req_ready;held_payload<=observed;
            if(req_valid&&!req_ready)hold_count<=hold_count+1;
            if(req_valid&&req_ready)begin
                if(cursor>=68184||observed!==expected[cursor][153:0])
                    $fatal(1,"Template address/order/metadata mismatch pair=%d observed=%h expected=%h",cursor,observed,expected[cursor]);
                cursor<=cursor+1;requests<=requests+1;
            end
            if(fault)$fatal(1,"Unexpected real tile fault code=%d",fault_code);
        end else held<=0;
    end
    task automatic begin_config;
        begin @(negedge clk);cfg_begin=1;do @(posedge clk);while(!cfg_begin_ready);@(negedge clk);cfg_begin=0;end
    endtask
    task automatic load_template(input [255:0] t);
        begin
            @(negedge clk);cfg_source_address=t[31:0];cfg_region_begin=t[63:32];cfg_region_end=t[96:64];
            cfg_source_generation=t[128:97];cfg_row_stride=t[160:129];cfg_x_stride=t[192:161];
            cfg_context=t[194:193];cfg_shift=t[196:195];cfg_valid=1;
            do @(posedge clk);while(!cfg_ready);@(negedge clk);cfg_valid=0;
        end
    endtask
    task automatic commit_config;
        begin @(negedge clk);cfg_commit=1;do @(posedge clk);while(!cfg_commit_ready);@(negedge clk);cfg_commit=0;
            if(!store_valid)$fatal(1,"Commit not atomic");end
    endtask
    task automatic launch;
        begin @(negedge clk);start=1;do @(posedge clk);while(!start_ready);@(negedge clk);start=0;
            cfg_channels=0;cfg_height=0;cfg_width=0;cfg_table_epoch=0;frame_epoch=99;end
    endtask
    task automatic recover_fault;
        integer k;begin
            if(!fault)$fatal(1,"Missing expected fault");negative=negative+1;
            cancel=0;clear_fault=1;downstream_quiescent=0;
            for(k=0;k<8;k=k+1)begin @(negedge clk);
                if(!fault||start_ready||cfg_begin_ready||req_valid)$fatal(1,"Recovery escaped downstream ownership");blocked_checks=blocked_checks+1;end
            downstream_quiescent=1;@(negedge clk);clear_fault=0;
            if(fault||store_valid)$fatal(1,"Fault recovery state");
        end
    endtask
    localparam [31:0] BASE=32'h10000000;
    reg [255:0] base_template,t;
    integer i,j,tc=0,pairs,k,done_before;
    initial begin
        $readmemh("geometry.hex",geometry);$readmemh("templates.hex",templates);$readmemh("expected.hex",expected);
        base_template=0;base_template[31:0]=BASE;base_template[63:32]=BASE;base_template[96:64]={1'b0,BASE}+4096;
        base_template[128:97]=1;base_template[160:129]=256;base_template[192:161]=128;
        repeat(5)@(negedge clk);rst_n=1;score=1;
        for(i=0;i<61;i=i+1)begin
            cfg_channels=geometry[i][9:0];cfg_height=geometry[i][19:10];cfg_width=geometry[i][29:20];cfg_table_epoch=geometry[i][61:30];
            pairs=cfg_channels>>3;begin_config();
            // Early commit remains blocked until all resident templates exist.
            cfg_commit=1;repeat(3)begin @(negedge clk);if(cfg_commit_ready||store_valid)$fatal(1,"Partial template commit");end cfg_commit=0;
            for(j=0;j<pairs;j=j+1)begin load_template(templates[tc]);tc=tc+1;end
            commit_config();frame_epoch=200;launch();
            do @(negedge clk);while(!dispatch_done);
            if(active||store_valid)$fatal(1,"Mutable template tile may not replay without reload");tiles=tiles+1;
        end
        score=0;
        if(cursor!=68184||tc!=1032||tiles!=61||hold_count==0)$fatal(1,"Full model template coverage");
        // Geometry and nonpaired channels rejected.
        cfg_channels=12;cfg_height=1;cfg_width=16;cfg_table_epoch=1;begin_config();recover_fault();
        cfg_channels=512;cfg_height=640;cfg_width=640;cfg_table_epoch=1;begin_config();recover_fault();
        // Invalid alignment, immutable source identity, region, stride and phase.
        for(k=0;k<7;k=k+1)begin
            cfg_channels=8;cfg_height=1;cfg_width=16;cfg_table_epoch=1;begin_config();t=base_template;
            case(k)
                0:t[31:0]=BASE+64;
                1:t[128:97]=0;
                2:t[96:64]={1'b0,BASE};
                3:t[160:129]=64;
                4:t[192:161]=0;
                5:t[196:195]=3;
                6:t[63:32]=BASE+128;
            endcase
            load_template(t);recover_fault();
        end
        // Cancel a held request; clear is barred until external ownership ends.
        cfg_channels=8;cfg_height=1;cfg_width=16;cfg_table_epoch=1;begin_config();load_template(base_template);commit_config();
        block_sink=1;frame_epoch=200;launch();do @(negedge clk);while(!req_valid);
        cancel=1;@(negedge clk);recover_fault();block_sink=0;
        // Bounded dispatch timeout under a permanently blocked consumer.
        cfg_channels=8;cfg_height=1;cfg_width=16;cfg_table_epoch=1;begin_config();load_template(base_template);commit_config();
        block_sink=1;timeout_cycles=12;frame_epoch=200;launch();do @(negedge clk);while(!fault);
        if(fault_code!=3)$fatal(1,"Timeout code");recover_fault();block_sink=0;timeout_cycles=100000;
        // Runtime next address exceeds region; no second request can escape.
        cfg_channels=8;cfg_height=1;cfg_width=32;cfg_table_epoch=1;begin_config();t=base_template;t[96:64]={1'b0,BASE}+128;
        load_template(t);commit_config();frame_epoch=200;launch();
        do @(negedge clk);while(!fault);
        if(fault_code!=5)$fatal(1,"Runtime range guard");recover_fault();
        if(negative!=12||blocked_checks!=96)$fatal(1,"Negative coverage");
        $display("PAIR_SEQUENCER_PASS tiles=%0d templates=%0d requests=%0d held_cycles=%0d rejected_cases=%0d blocked_clear_cycles=%0d",tiles,tc,requests,hold_count,negative,blocked_checks);
        $finish;
    end
    initial begin #30000000;$fatal(1,"Watchdog timeout");end
endmodule
`default_nettype wire
