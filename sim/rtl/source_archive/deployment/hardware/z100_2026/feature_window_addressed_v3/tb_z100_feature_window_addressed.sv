`timescale 1ns/1ps
module tb_z100_feature_window_addressed;
    `include "window_counts.svh"
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, cancel=0;
    reg cfg_begin=0, cfg_word_valid=0, cfg_commit=0;
    wire cfg_begin_ready, cfg_word_ready, cfg_commit_ready;
    reg [31:0] cfg_epoch=1;
    reg [10:0] cfg_channels=7;
    reg [9:0] cfg_height=8, cfg_width=40;
    reg [31:0] cfg_word_epoch=1;
    reg [12:0] cfg_word_address=0;
    reg cfg_word_last=0;
    reg [511:0] cfg_data=0;
    wire store_valid, loading, error_valid;
    wire [31:0] active_epoch;
    wire [2:0] error_code;
    reg window_valid=0;
    wire window_ready;
    reg [31:0] window_epoch=1, window_tag=0;
    reg [13:0] window_row_address=0;
    reg signed [11:0] window_first_x=0;
    reg [10:0] window_input_width=40, window_output_remaining=40;
    reg [3:0] window_sites=12, window_channel_mask=15;
    reg window_stride_two=0, window_y_valid=1;
    wire out_valid;
    reg out_ready=0;
    wire [31:0] out_tag;
    wire [47:0] out_mask;
    wire [383:0] out_data;
    z100_feature_window_addressed dut(.*);
    reg [511:0] load_words[0:LOAD_WORDS-1];
    reg [12:0] load_addresses[0:LOAD_WORDS-1];
    reg [575:0] vectors[0:VECTOR_COUNT-1];
    integer sent=0, received=0, stalls=0, streak=0, max_streak=0;
    integer n;
    reg streaming=0;
    reg [31:0] rng=32'h7657100;
    reg held_valid=0;
    reg [463:0] held;

    task automatic drive_vector(input integer index);
        reg [127:0] packet;
        begin
            packet=vectors[index][127:0];
            window_tag=packet[31:0];
            window_epoch=packet[63:32];
            window_row_address=packet[77:64];
            window_first_x=packet[89:78];
            window_input_width=packet[100:90];
            window_sites=packet[104:101];
            window_channel_mask=packet[108:105];
            window_stride_two=packet[109];
            window_y_valid=packet[110];
            window_output_remaining=packet[121:111];
        end
    endtask
    always @(posedge clk) if(streaming) begin
        if(error_valid) $fatal(1,"Unexpected window/store error=%0d",error_code);
        if(held_valid && (!out_valid || {out_tag,out_mask,out_data}!==held))
            $fatal(1,"Stalled window changed");
        held_valid=out_valid && !out_ready;
        if(held_valid) begin
            held={out_tag,out_mask,out_data};
            stalls=stalls+1;
        end
        if(window_valid && window_ready) sent=sent+1;
        if(out_valid && out_ready) begin
            if(received>=sent || out_tag!==vectors[received][31:0] ||
               out_mask!==vectors[received][175:128] || out_data!==vectors[received][559:176])
                $fatal(1,"Window mismatch index=%0d tag=%0d expected=%0d mask=%h expected=%h",received,out_tag,vectors[received][31:0],out_mask,vectors[received][175:128]);
            received=received+1;
            streak=streak+1;
            if(streak>max_streak) max_streak=streak;
        end else streak=0;
    end
    initial begin
        $readmemh("load_words.hex",load_words);
        $readmemh("load_addresses.hex",load_addresses);
        $readmemh("window_vectors.hex",vectors);
        repeat(3) @(posedge clk);
        @(negedge clk); rst_n=1;
        @(negedge clk); cfg_begin=1;
        @(posedge clk); #1;
        if(!loading || store_valid) $fatal(1,"Load begin failed");
        @(negedge clk); cfg_begin=0;
        for(n=0;n<LOAD_WORDS;n=n+1) begin
            #1;
            if(!cfg_word_ready) $fatal(1,"Load not ready");
            cfg_word_valid=1; cfg_data=load_words[n];
            cfg_word_address=load_addresses[n]; cfg_word_last=(n==LOAD_WORDS-1);
            @(posedge clk); #1;
            @(negedge clk);
        end
        cfg_word_valid=0; cfg_commit=1;
        @(posedge clk); #1;
        if(!store_valid || active_epoch!=1 || error_valid) $fatal(1,"Commit failed");
        @(negedge clk); cfg_commit=0; streaming=1;
        while(received<VECTOR_COUNT) begin
            window_valid=(sent<VECTOR_COUNT);
            if(window_valid) drive_vector(sent);
            rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            out_ready=rng[3:2]!=0;
            @(negedge clk);
        end
        streaming=0; window_valid=0; out_ready=0;
        if(sent!=VECTOR_COUNT || stalls==0 || max_streak<8) $fatal(1,"Coverage missing");
        // Invalid geometry is consumed without accessing RAM or publishing data.
        window_valid=1; window_first_x=-2;
        #1;
        if(!window_ready) $fatal(1,"Error probe not ready");
        @(posedge clk); #1;
        if(!error_valid || error_code!=1 || out_valid) $fatal(1,"Geometry not rejected");
        @(negedge clk); window_valid=0;
        @(posedge clk); #1;
        // A live, in-bounds site whose row plus x-word crosses bank depth is rejected.
        @(negedge clk); window_valid=1; window_row_address=14'd8191;
        window_first_x=16; window_sites=1; window_output_remaining=1;
        window_input_width=40; window_channel_mask=15; window_stride_two=0;
        window_y_valid=1;
        #1;
        if(!window_ready) $fatal(1,"Row-overflow probe not ready");
        @(posedge clk); #1;
        if(!error_valid || error_code!=1 || out_valid) $fatal(1,"Row overflow not rejected");
        @(negedge clk); window_valid=0;
        @(posedge clk); #1;
        // A padding-only request does not read RAM and ignores an inactive row address.
        @(negedge clk); window_valid=1; window_row_address=14'h3fff;
        window_first_x=0; window_sites=1; window_output_remaining=1;
        window_y_valid=0; out_ready=1;
        #1;
        if(!window_ready) $fatal(1,"Inactive-row control probe not ready");
        @(posedge clk); #1;
        if(error_valid || out_valid) $fatal(1,"Inactive row address was rejected");
        @(negedge clk); window_valid=0;
        @(posedge clk); #1;
        if(error_valid || !out_valid || out_mask!==48'd0 || out_data!==384'd0)
            $fatal(1,"Padding-only row control was not zero-filled");
        @(posedge clk); #1;
        if(out_valid) $fatal(1,"Padding-only response did not retire");
        @(negedge clk); out_ready=0;
        // Fill both pipeline slots behind a blocked output, then cancel.
        @(negedge clk); drive_vector(0); window_valid=1;
        repeat(3) @(negedge clk);
        if(!out_valid || window_ready || cfg_begin_ready) $fatal(1,"Two-slot stall not covered");
        window_valid=0; cancel=1;
        @(posedge clk); #1;
        if(out_valid || store_valid || loading) $fatal(1,"Window cancel failed");
        $display("FEATURE_WINDOW_ADDRESSED_V3_PASS vectors=%0d results=%0d stalls=%0d max_consecutive=%0d geometry_errors=1 row_overflow_errors=1 inactive_row_control=1 cancel_full=1",sent,received,stalls,max_streak);
        $finish;
    end
    initial begin #2000000; $fatal(1,"Window watchdog"); end
endmodule
`default_nettype wire
