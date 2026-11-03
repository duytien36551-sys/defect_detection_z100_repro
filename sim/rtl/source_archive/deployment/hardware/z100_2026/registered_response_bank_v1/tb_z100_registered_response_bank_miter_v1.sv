`timescale 1ns/1ps
`default_nettype none

module tb_z100_registered_response_bank_miter_v1;
    reg clk=0;
    always #5 clk=~clk;

    reg rst_n=0, cancel=0;
    reg cfg_bank=0, read_bank=0, req_bank=0;
    reg cfg_begin=0, cfg_canonical_order=1;
    reg [31:0] cfg_epoch=200, cfg_word_epoch=200;
    reg [10:0] cfg_channels=4;
    reg [9:0] cfg_height=1, cfg_width=64;
    reg [12:0] cfg_word_address=0;
    reg cfg_word_last=0, cfg_word_valid=0, cfg_commit=0;
    reg [511:0] cfg_data=0;
    reg req_valid=0;
    reg [31:0] req_epoch=200;
    reg [3327:0] req_addresses=0;
    reg [255:0] req_mask=0;
    reg out_ready=0;

    wire [1:0] old_bank_store_valid, new_bank_store_valid;
    wire old_read_idle, new_read_idle;
    wire old_load_owner_valid, new_load_owner_valid;
    wire old_load_owner_bank, new_load_owner_bank;
    wire old_load_store_valid, new_load_store_valid;
    wire old_load_loading, new_load_loading;
    wire [31:0] old_load_active_epoch, new_load_active_epoch;
    wire old_cfg_begin_ready, new_cfg_begin_ready;
    wire old_cfg_word_ready, new_cfg_word_ready;
    wire old_cfg_commit_ready, new_cfg_commit_ready;
    wire old_store_valid, new_store_valid;
    wire old_loading, new_loading;
    wire [31:0] old_active_epoch, new_active_epoch;
    wire old_error_valid, new_error_valid;
    wire [3:0] old_error_code, new_error_code;
    wire old_req_ready, new_req_ready;
    wire old_out_valid, new_out_valid;
    wire [31:0] old_out_epoch, new_out_epoch;
    wire [2047:0] old_out_data, new_out_data;

    z100_feature_banks_pingpong_writepipe_v7_baseline old_dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_bank(cfg_bank), .read_bank(read_bank), .req_bank(req_bank),
        .read_idle(old_read_idle), .load_owner_valid(old_load_owner_valid),
        .load_owner_bank(old_load_owner_bank), .load_store_valid(old_load_store_valid),
        .load_loading(old_load_loading), .load_active_epoch(old_load_active_epoch),
        .bank_store_valid(old_bank_store_valid), .cfg_begin(cfg_begin),
        .cfg_begin_ready(old_cfg_begin_ready), .cfg_epoch(cfg_epoch),
        .cfg_canonical_order(cfg_canonical_order), .cfg_channels(cfg_channels),
        .cfg_height(cfg_height), .cfg_width(cfg_width), .cfg_word_epoch(cfg_word_epoch),
        .cfg_word_address(cfg_word_address), .cfg_word_last(cfg_word_last),
        .cfg_word_valid(cfg_word_valid), .cfg_word_ready(old_cfg_word_ready),
        .cfg_data(cfg_data), .cfg_commit(cfg_commit),
        .cfg_commit_ready(old_cfg_commit_ready), .store_valid(old_store_valid),
        .loading(old_loading), .active_epoch(old_active_epoch),
        .error_valid(old_error_valid), .error_code(old_error_code),
        .req_valid(req_valid), .req_ready(old_req_ready), .req_epoch(req_epoch),
        .req_addresses(req_addresses), .req_mask(req_mask), .out_valid(old_out_valid),
        .out_ready(out_ready), .out_epoch(old_out_epoch), .out_data(old_out_data)
    );

    z100_feature_banks_pingpong_writepipe_v7 new_dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_bank(cfg_bank), .read_bank(read_bank), .req_bank(req_bank),
        .read_idle(new_read_idle), .load_owner_valid(new_load_owner_valid),
        .load_owner_bank(new_load_owner_bank), .load_store_valid(new_load_store_valid),
        .load_loading(new_load_loading), .load_active_epoch(new_load_active_epoch),
        .bank_store_valid(new_bank_store_valid), .cfg_begin(cfg_begin),
        .cfg_begin_ready(new_cfg_begin_ready), .cfg_epoch(cfg_epoch),
        .cfg_canonical_order(cfg_canonical_order), .cfg_channels(cfg_channels),
        .cfg_height(cfg_height), .cfg_width(cfg_width), .cfg_word_epoch(cfg_word_epoch),
        .cfg_word_address(cfg_word_address), .cfg_word_last(cfg_word_last),
        .cfg_word_valid(cfg_word_valid), .cfg_word_ready(new_cfg_word_ready),
        .cfg_data(cfg_data), .cfg_commit(cfg_commit),
        .cfg_commit_ready(new_cfg_commit_ready), .store_valid(new_store_valid),
        .loading(new_loading), .active_epoch(new_active_epoch),
        .error_valid(new_error_valid), .error_code(new_error_code),
        .req_valid(req_valid), .req_ready(new_req_ready), .req_epoch(req_epoch),
        .req_addresses(req_addresses), .req_mask(req_mask), .out_valid(new_out_valid),
        .out_ready(out_ready), .out_epoch(new_out_epoch), .out_data(new_out_data)
    );

    integer checks=0, accepted_reads=0, retired_reads=0;
    integer held_valid_cycles=0, invalid_payload_difference_cycles=0;
    integer cycles;
    reg [31:0] held_epoch;
    reg [2047:0] held_data;
    reg held_response=0;

    function automatic [7:0] byte_value(input integer bank, input integer channel,
                                         input integer xpos);
        byte_value=(bank*97+channel*43+xpos*7)^8'ha5;
    endfunction

    task automatic check_equal;
    begin
        checks=checks+1;
        if (old_read_idle!==new_read_idle ||
            old_load_owner_valid!==new_load_owner_valid ||
            old_load_owner_bank!==new_load_owner_bank ||
            old_load_store_valid!==new_load_store_valid ||
            old_load_loading!==new_load_loading ||
            old_load_active_epoch!==new_load_active_epoch ||
            old_bank_store_valid!==new_bank_store_valid ||
            old_cfg_begin_ready!==new_cfg_begin_ready ||
            old_cfg_word_ready!==new_cfg_word_ready ||
            old_cfg_commit_ready!==new_cfg_commit_ready ||
            old_store_valid!==new_store_valid || old_loading!==new_loading ||
            old_active_epoch!==new_active_epoch || old_error_valid!==new_error_valid ||
            old_error_code!==new_error_code || old_req_ready!==new_req_ready ||
            old_out_valid!==new_out_valid)
            $fatal(1,"response-bank valid/control mismatch at check %0d",checks);
        if (old_out_valid) begin
            if (old_out_epoch!==new_out_epoch || old_out_data!==new_out_data)
                $fatal(1,"valid response payload mismatch at check %0d",checks);
            if (held_response && (!out_ready) &&
                (old_out_epoch!==held_epoch || old_out_data!==held_data))
                $fatal(1,"valid stalled response changed at check %0d",checks);
            if (!out_ready) begin
                held_response=1;
                held_epoch=old_out_epoch;
                held_data=old_out_data;
                held_valid_cycles=held_valid_cycles+1;
            end else begin
                held_response=0;
            end
        end else begin
            held_response=0;
            if (old_out_data!==new_out_data)
                invalid_payload_difference_cycles=invalid_payload_difference_cycles+1;
        end
    end
    endtask

    task automatic tick;
    begin
        @(posedge clk); #1; check_equal();
    end
    endtask

    task automatic begin_bank(input integer bank);
    begin
        @(negedge clk); cfg_bank=bank; cfg_begin=1; #1; check_equal();
        cycles=0;
        while (!old_cfg_begin_ready) begin
            tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
            if(cycles>12) $fatal(1,"cfg_begin timeout for bank %0d",bank);
        end
        tick(); @(negedge clk); cfg_begin=0; cfg_bank=!bank; #1; check_equal();
        if (!old_load_owner_valid || old_load_owner_bank!==bank)
            $fatal(1,"load owner did not latch bank %0d",bank);
    end
    endtask

    task automatic fill_bank(input integer bank);
        integer word_i, channel_i, byte_i, xpos;
    begin
        begin_bank(bank);
        for(word_i=0;word_i<4;word_i=word_i+1) begin
            @(negedge clk); cfg_word_valid=1; cfg_word_address=word_i;
            cfg_word_last=(word_i==3); cfg_word_epoch=200;
            for(channel_i=0;channel_i<4;channel_i=channel_i+1)
                for(byte_i=0;byte_i<16;byte_i=byte_i+1) begin
                    xpos=word_i*16+byte_i;
                    cfg_data[(channel_i*16+byte_i)*8 +: 8]=
                        byte_value(bank,channel_i,xpos);
                end
            #1; check_equal(); cycles=0;
            while(!old_cfg_word_ready) begin
                tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
                if(cycles>12) $fatal(1,"cfg_word timeout for bank %0d",bank);
            end
            tick();
        end
        @(negedge clk); cfg_word_valid=0; cfg_word_last=0; cfg_commit=1; #1;
        check_equal(); cycles=0;
        while(!old_cfg_commit_ready) begin
            tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
            if(cycles>12) $fatal(1,"cfg_commit timeout for bank %0d",bank);
        end
        tick(); @(negedge clk); cfg_commit=0; #1; check_equal();
        cycles=0;
        while(!old_bank_store_valid[bank]) begin
            tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
            if(cycles>12) $fatal(1,"bank %0d failed to publish",bank);
        end
        if(old_error_valid) $fatal(1,"bank %0d load error %0d",bank,old_error_code);
    end
    endtask

    task automatic issue_read(input integer bank);
    begin
        @(negedge clk); read_bank=bank; req_bank=bank; req_epoch=200;
        req_addresses=0; req_mask=0; req_mask[0]=1; req_mask[1]=1;
        req_valid=1; #1; check_equal(); cycles=0;
        while(!old_req_ready) begin
            tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
            if(cycles>12) $fatal(1,"read request timeout for bank %0d",bank);
        end
        tick(); accepted_reads=accepted_reads+1;
        @(negedge clk); req_valid=0; #1; check_equal(); cycles=0;
        while(!old_out_valid) begin
            tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
            if(cycles>12) $fatal(1,"read response timeout for bank %0d",bank);
        end
        if(old_out_epoch!==32'd200 ||
           old_out_data[7:0]!==byte_value(bank,0,0) ||
           old_out_data[15:8]!==byte_value(bank,0,0))
            $fatal(1,"bank %0d response byte oracle failed epoch=%0d lane0=%h lane1=%h",
                   bank,old_out_epoch,old_out_data[7:0],old_out_data[15:8]);
        for(integer lane=2;lane<256;lane=lane+1)
            if(old_out_data[lane*8 +: 8]!==8'd0)
                $fatal(1,"unexpected unmasked byte at lane %0d",lane);
    end
    endtask

    task automatic retire_read;
    begin
        @(negedge clk); out_ready=1; #1; check_equal(); tick();
        retired_reads=retired_reads+1;
        @(negedge clk); out_ready=0; #1; check_equal();
        if(old_out_valid) $fatal(1,"response remained valid after retirement");
    end
    endtask

    task automatic simultaneous_same_bank_retire_and_request(input integer bank);
    begin
        if(!old_out_valid || !new_out_valid)
            $fatal(1,"same-bank overlap requires a pending response");
        @(negedge clk); req_bank=bank; req_epoch=200; req_valid=1; out_ready=1;
        req_addresses=0; req_mask=0; req_mask[0]=1; req_mask[1]=1; #1; check_equal();
        if(!old_req_ready || !old_out_valid)
            $fatal(1,"baseline did not admit same-bank full-throughput overlap");
        tick(); accepted_reads=accepted_reads+1; retired_reads=retired_reads+1;
        @(negedge clk); req_valid=0; out_ready=0; #1; check_equal();
        cycles=0;
        while(!old_out_valid) begin
            tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
            if(cycles>12) $fatal(1,"overlapped response did not arrive");
        end
        if(old_out_epoch!==32'd200 ||
           old_out_data[7:0]!==byte_value(bank,0,0) ||
           old_out_data[15:8]!==byte_value(bank,0,0))
            $fatal(1,"same-bank overlapped response byte oracle failed");
    end
    endtask

    task automatic reset_pending_response;
    begin
        if(!old_out_valid) $fatal(1,"reset test needs a pending response");
        @(negedge clk); rst_n=0; #1; check_equal();
        if(old_out_valid) $fatal(1,"reset did not suppress pending valid");
        tick();
        @(negedge clk); rst_n=1; cancel=0; req_valid=0; out_ready=0; #1; check_equal();
        if(old_out_valid || !old_read_idle || old_bank_store_valid!==2'b00)
            $fatal(1,"reset did not clear pending and both bank-valid states");
    end
    endtask

    task automatic issue_bad_epoch;
    begin
        @(negedge clk); req_bank=0; read_bank=0; req_epoch=201;
        req_addresses=0; req_mask=0; req_mask[0]=1; req_valid=1; #1; check_equal();
        cycles=0;
        while(!old_req_ready) begin
            tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
            if(cycles>12) $fatal(1,"bad-epoch request timeout");
        end
        tick(); accepted_reads=accepted_reads+1;
        @(negedge clk); req_valid=0; #1; check_equal(); cycles=0;
        while(!old_error_valid) begin
            tick(); @(negedge clk); #1; check_equal(); cycles=cycles+1;
            if(cycles>12) $fatal(1,"bad-epoch error was not reported");
        end
        if(old_error_code!==4'd7 || old_out_valid)
            $fatal(1,"bad epoch did not fail closed with error 7");
        @(negedge clk); cancel=1; #1; check_equal(); tick();
        @(negedge clk); cancel=0; #1; check_equal();
        if(old_error_valid || old_out_valid || !old_read_idle || old_bank_store_valid!==2'b00)
            $fatal(1,"cancel did not clear bad-epoch state and invalidate both stores");
    end
    endtask

    initial begin
        repeat(4) tick();
        @(negedge clk); rst_n=1; #1; check_equal();
        fill_bank(0);
        fill_bank(1);

        issue_read(0);
        // The pending response is owned by bank 0. Changing the unrelated
        // request selector while READY is low must not change valid payload.
        repeat(3) begin
            @(negedge clk); req_bank=1; read_bank=1; #1; check_equal(); tick();
        end
        // The inactive bank may be reloaded while bank 0 is pending. Its
        // configuration and writes must not steal the response-bank mux.
        fill_bank(1);
        if(old_out_data[7:0]!==byte_value(0,0,0) || old_out_epoch!==32'd200)
            $fatal(1,"inactive-bank reload disturbed pending bank-0 response");
        // The active response bank cannot be configured before it retires.
        @(negedge clk); cfg_bank=0; cfg_begin=1; #1; check_equal();
        if(old_cfg_begin_ready) $fatal(1,"active response bank was not excluded");
        cfg_begin=0;
        retire_read();

        issue_read(1);
        simultaneous_same_bank_retire_and_request(1);
        retire_read();

        issue_read(0);
        reset_pending_response();
        fill_bank(0);
        fill_bank(1);
        issue_read(0);
        retire_read();

        issue_bad_epoch();
        fill_bank(0);
        fill_bank(1);
        issue_read(1);
        retire_read();
        if(accepted_reads<=retired_reads)
            $fatal(1,"cancelled/error transactions were not covered");
        $display("REGISTERED_RESPONSE_BANK_MITER_PASS checks=%0d accepted_reads=%0d retired_reads=%0d held_valid_cycles=%0d invalid_payload_difference_cycles=%0d",checks,accepted_reads,retired_reads,held_valid_cycles,invalid_payload_difference_cycles);
        $finish;
    end

    initial begin
        #200000;
        $fatal(1,"registered response-bank miter watchdog");
    end
endmodule

`default_nettype wire
