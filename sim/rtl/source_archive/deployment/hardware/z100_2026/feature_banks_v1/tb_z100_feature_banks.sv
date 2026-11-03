`timescale 1ns/1ps
module tb_z100_feature_banks;
    localparam integer AW=13;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, cancel=0;
    reg cfg_begin=0, cfg_word_valid=0, cfg_commit=0;
    wire cfg_begin_ready, cfg_word_ready, cfg_commit_ready;
    reg [31:0] cfg_epoch=0;
    reg [AW:0] cfg_words=0;
    reg [511:0] cfg_data=0;
    wire error_valid, store_valid, loading;
    wire [2:0] error_code;
    wire [31:0] active_epoch;
    reg req_valid=0;
    wire req_ready;
    reg [31:0] req_epoch=0;
    reg [128*AW-1:0] req_addresses=0;
    reg [127:0] req_mask=0;
    wire out_valid;
    reg out_ready=0;
    wire [31:0] out_epoch;
    wire [1023:0] out_data;
    z100_feature_banks dut(.*);
    integer words_written=0, responses=0, stalls=0, errors_checked=0;
    integer n, p, b, address;
    reg [31:0] rng=32'h7100640;
    reg [1023:0] expected;
    reg [1023:0] held;

    function automatic [7:0] pattern(input integer addr, bank, epoch);
        pattern=(addr*17) ^ (addr>>5) ^ (bank*29) ^ (epoch*37);
    endfunction

    task automatic step;
        begin @(posedge clk); #1; end
    endtask
    task automatic begin_load(input integer epoch, words);
        begin
            @(negedge clk);
            if(!cfg_begin_ready) $fatal(1,"begin not ready");
            cfg_epoch=epoch; cfg_words=words; cfg_begin=1;
            step();
            if(store_valid || !loading || req_ready) $fatal(1,"load ownership");
            @(negedge clk); cfg_begin=0;
        end
    endtask
    task automatic send_word(input integer addr, epoch);
        integer bank;
        begin
            #1;
            if(!cfg_word_ready) $fatal(1,"word not ready");
            for(bank=0;bank<64;bank=bank+1)
                cfg_data[bank*8+:8]=pattern(addr,bank,epoch);
            cfg_word_valid=1;
            step();
            words_written=words_written+1;
            @(negedge clk); cfg_word_valid=0;
        end
    endtask
    task automatic commit_load(input integer epoch);
        begin
            if(!cfg_commit_ready) $fatal(1,"commit not ready");
            cfg_commit=1; step();
            if(error_valid || loading || !store_valid || active_epoch!=epoch)
                $fatal(1,"full commit failed");
            @(negedge clk); cfg_commit=0;
        end
    endtask
    task automatic expect_error(input integer code);
        begin
            if(!error_valid || error_code!=code || store_valid || out_valid)
                $fatal(1,"error mismatch expected=%0d actual=%0d valid=%0d",code,error_code,error_valid);
            errors_checked=errors_checked+1;
        end
    endtask

    initial begin
        repeat(3) step();
        @(negedge clk); rst_n=1;
        // Empty/invalid configuration cannot make stale RAM readable.
        cfg_epoch=1; cfg_words=0; cfg_begin=1; step(); expect_error(1);
        @(negedge clk); cfg_begin=0;
        begin_load(1,4);
        send_word(0,1);
        cfg_commit=1; step(); expect_error(2);
        @(negedge clk); cfg_commit=0;
        begin_load(2,1);
        send_word(0,2);
        send_word(1,2); expect_error(3);
        // The full physical address range, including the final word, is used.
        begin_load(3,8192);
        for(n=0;n<8192;n=n+1) send_word(n,3);
        commit_load(3);
        for(n=0;n<1024;n=n+1) begin
            #1;
            if(!req_ready) $fatal(1,"read not ready");
            expected=0;
            for(p=0;p<128;p=p+1) begin
                rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
                address=(n==0) ? 8191 : rng[12:0];
                req_addresses[p*AW+:AW]=address;
                req_mask[p]=(n<2) || rng[16];
                if(req_mask[p]) expected[p*8+:8]=pattern(address,p/2,3);
            end
            req_epoch=3; req_valid=1; out_ready=0;
            step();
            if(!out_valid || out_epoch!=3 || out_data!==expected) $fatal(1,"read mismatch n=%0d",n);
            @(negedge clk); req_valid=0;
            held=out_data;
            repeat(n%5) begin
                // Perturb all unaccepted inputs during output backpressure.
                req_addresses=~req_addresses; req_mask=~req_mask;
                step(); stalls=stalls+1;
                if(req_ready || cfg_begin_ready || !out_valid || out_data!==held)
                    $fatal(1,"stalled output changed");
                @(negedge clk);
            end
            out_ready=1; step();
            if(out_valid) $fatal(1,"response did not drain");
            responses=responses+1;
            @(negedge clk); out_ready=0;
        end
        // One request per cycle with alternating valid masks.
        for(n=0;n<32;n=n+1) begin
            req_valid=1; req_epoch=3; out_ready=1; expected=0;
            for(p=0;p<128;p=p+1) begin
                req_addresses[p*AW+:AW]=n;
                req_mask[p]=(p+n)%2;
                if(req_mask[p]) expected[p*8+:8]=pattern(n,p/2,3);
            end
            #1;
            if(!req_ready) $fatal(1,"throughput ready missing");
            step();
            if(!out_valid || out_data!==expected) $fatal(1,"stream read mismatch");
            responses=responses+1;
            @(negedge clk);
        end
        req_valid=0; step();
        @(negedge clk); out_ready=0;
        // Old epoch is consumed as an error and invalidates the store.
        req_epoch=2; req_valid=1; step(); expect_error(4);
        @(negedge clk); req_valid=0;
        begin_load(4,1); send_word(0,4); commit_load(4);
        req_epoch=4; req_addresses=0; req_addresses[AW-1:0]=1;
        req_mask=1; req_valid=1; step(); expect_error(4);
        @(negedge clk); req_valid=0;
        // Cancel during a load and while a result is stalled clears ownership.
        begin_load(5,2); send_word(0,5);
        cancel=1; step();
        if(store_valid || loading || out_valid || req_ready) $fatal(1,"load cancel failed");
        @(negedge clk); cancel=0;
        begin_load(6,1); send_word(0,6); commit_load(6);
        req_epoch=6; req_addresses=0; req_mask=~128'd0; req_valid=1; step();
        if(!out_valid) $fatal(1,"cancel setup missing");
        @(negedge clk); req_valid=0; cancel=1; step();
        if(out_valid || store_valid || loading) $fatal(1,"output cancel failed");
        @(negedge clk); cancel=0;
        // Reset during a load, then reload the same RAM with a new epoch.
        begin_load(7,2); send_word(0,7); rst_n=0; step();
        if(store_valid || loading || out_valid) $fatal(1,"reset invalidation failed");
        @(negedge clk); rst_n=1;
        begin_load(8,1); send_word(0,8); commit_load(8);
        req_epoch=8; req_addresses=0; req_mask=~128'd0; req_valid=1; step();
        for(p=0;p<128;p=p+1)
            if(out_data[p*8+:8]!==pattern(0,p/2,8)) $fatal(1,"post-reset stale read");
        if(!out_valid || out_epoch!=8) $fatal(1,"post-reset validity");
        responses=responses+1;
        $display("FEATURE_BANKS_PASS words_written=%0d responses=%0d stalls=%0d errors=%0d full_capacity_bytes=524288",words_written,responses,stalls,errors_checked);
        $finish;
    end
    initial begin #2000000; $fatal(1,"watchdog"); end
endmodule
