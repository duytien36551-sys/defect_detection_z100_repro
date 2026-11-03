`timescale 1ns/1ps
// Transaction-level equivalence: z100_feature_banks_4read_writepipe_4k_v13
// (reference) vs ..._v13p (geometry precompute, begin accept may slip 1-2 cycles).
//
// Same structure as tb_requant32_vs_v13c.sv: each DUT has its OWN driver.
// The data seed is shared, so both drivers present the same sequence of
// configurations, words and read requests; the timing seed differs, so the
// two DUTs see different ready/valid back-pressure and therefore take their
// handshakes on different cycles. Each driver logs its own accepted
// transactions; the log comparison is the verdict.
//
// Not a cycle-exact miter: v13p may delay cfg_begin_ready, so per-cycle
// vectors are expected to differ. What must not differ is the transaction
// stream and the resulting store state.
`define FB_PORTS .clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_begin(cfg_begin),.cfg_begin_ready(br), \
    .cfg_epoch(cfg_epoch),.cfg_canonical_order(cfg_canon),.cfg_channels(cfg_channels),.cfg_height(cfg_height),.cfg_width(cfg_width), \
    .cfg_word_valid(cfg_word_valid),.cfg_word_ready(wr),.cfg_word_data(cfg_word_data),.cfg_word_epoch(cfg_word_epoch), \
    .cfg_word_address(cfg_word_address),.cfg_word_last(cfg_word_last),.cfg_commit(cfg_commit),.cfg_commit_ready(cr), \
    .error_valid(ev),.error_code(ec),.store_valid(sv),.active_epoch(ae),.loading(ld),.req_valid(req_valid),.req_ready(rr), \
    .req_epoch(req_epoch),.req_addresses(req_addresses),.req_mask(req_mask),.out_valid(ov),.out_ready(out_ready),.out_epoch(oe),.out_data(od)

module fb_driver #(parameter integer V13P = 0, DATA_SEED = 1, TIME_SEED = 1, CYCLES = 200000)
                   (input wire clk, output wire [63:0] dbg, output wire [63:0] dbgx);
    reg rst_n, cancel, cfg_begin, cfg_canon, cfg_word_valid, cfg_word_last, cfg_commit, req_valid, out_ready;
    reg [31:0] cfg_epoch, cfg_word_epoch, req_epoch;
    reg [10:0] cfg_channels; reg [9:0] cfg_height, cfg_width;
    reg [511:0] cfg_word_data; reg [12:0] cfg_word_address;
    reg [64*4*13-1:0] req_addresses; reg [255:0] req_mask;
    wire [12:0] o_dummy;
    wire [3:0] ec; wire [31:0] ae, oe; wire [2047:0] od;
    wire br, wr, cr, ev, sv, ld, rr, ov;
    generate if (V13P) begin : gp
        z100_feature_banks_4read_writepipe_4k_v13p dut(`FB_PORTS);
    end else begin : gr
        z100_feature_banks_4read_writepipe_4k_v13  dut(`FB_PORTS);
    end endgenerate

    integer fd, ds, ts, cyc, k, words, wi, phase, nbeg, nword, ncommit, nread, nerr, nout;
    integer idle_beat = 0, last_phase = -1;
    reg [31:0] ep;

    initial begin
        fd = V13P ? $fopen("new.log", "w") : $fopen("ref.log", "w");
        ds = DATA_SEED * 7919 + 13;
        ts = TIME_SEED * 104729 + 7;
        nbeg = 0; nword = 0; ncommit = 0; nread = 0; nerr = 0; nout = 0;
        phase = 0; wi = 0; words = 0; ep = 1;
        rst_n = 0; cancel = 0; cfg_begin = 0; cfg_canon = 1; cfg_word_valid = 0;
        cfg_word_last = 0; cfg_commit = 0; req_valid = 0; out_ready = 1;
        cfg_epoch = 0; cfg_word_epoch = 0; req_epoch = 0;
        cfg_channels = 8; cfg_height = 2; cfg_width = 32;
        cfg_word_data = 0; cfg_word_address = 0; req_addresses = 0; req_mask = 0;
        repeat (4) @(negedge clk); rst_n = 1;
        for (cyc = 0; cyc < CYCLES; cyc = cyc + 1) begin
            @(negedge clk);
            if (phase == last_phase) idle_beat = idle_beat + 1; else idle_beat = 0;
            last_phase = phase;
            out_ready = ({$random(ts)} % 3) != 0;
            cancel    = (({$random(ts)} % 3000) == 0);
            if (cancel) phase = 0;
            case (phase)
            0: begin
                req_valid = 0; cfg_word_valid = 0; cfg_commit = 0;
                ep = ep + 1;
                cfg_epoch = (({$random(ds)} % 40) == 0) ? 0 : ep;
                cfg_channels = 4 * (1 + {$random(ds)} % 3);
                cfg_height = 1 + {$random(ds)} % 3;
                cfg_width = 16 * (1 + {$random(ds)} % 2);
                // occasional illegal geometry: too many channels, zero epoch
                if (({$random(ds)} % 25) == 0) cfg_channels = 1024;
                if (({$random(ds)} % 25) == 0) cfg_height = 640;
                words = (cfg_channels / 4) * cfg_height * (cfg_width / 16);
                wi = 0;
                cfg_begin = 1; phase = 1;
            end
            // hold cfg_begin for a few cycles: exercises the presented-early path
            1: if (br && cfg_begin) begin
                   $fdisplay(fd, "BEGIN e=%0d c=%0d ch=%0d h=%0d w=%0d",
                             cfg_epoch, cfg_canon, cfg_channels, cfg_height, cfg_width);
                   nbeg = nbeg + 1; cfg_begin = 0; phase = 2;
               end else if (({$random(ts)} % 50) == 0) begin cfg_begin = 0; phase = 0; end
            2: begin
                cfg_word_valid = 1; cfg_word_address = wi; cfg_word_epoch = ep;
                cfg_word_last = (wi == words - 1);
                for (k = 0; k < 16; k = k + 1) cfg_word_data[k*32 +: 32] = $random(ds);
                if (({$random(ds)} % 150) == 0) cfg_word_address = wi + 1;
                phase = 3;
            end
            3: if (wr && cfg_word_valid) begin
                   $fdisplay(fd, "WORD a=%0d e=%0d l=%0d d=%h", cfg_word_address, cfg_word_epoch, cfg_word_last, cfg_word_data);
                   nword = nword + 1;
                   cfg_word_valid = 0; wi = wi + 1;
                   if (({$random(ds)} % 100) == 0) begin cfg_commit = 1; phase = 4; end
                   else if (wi >= words) begin cfg_commit = 1; phase = 4; end
                   else phase = 2;
               end else if ((!ld && cfg_word_valid) || idle_beat > 64) begin
                   cfg_word_valid = 0; phase = 0; end
            4: if (cr && cfg_commit) begin
                   $fdisplay(fd, "COMMIT sv=%0d ae=%0d", sv, ae);
                   ncommit = ncommit + 1; cfg_commit = 0; phase = 5;
               end else if ((!ld && cfg_commit) || idle_beat > 64) begin
                   cfg_commit = 0; phase = 0; end
            5: begin
                cfg_commit = 0; cfg_word_valid = 0;
                if (!sv) begin req_valid = 0; phase = 0; end
                else if (!req_valid || rr || idle_beat > 64) begin
                    if (({$random(ts)} % 2000) == 0) begin req_valid = 0; phase = 0; end
                    else begin
                        req_valid = ({$random(ts)} % 4) != 0;
                        for (k = 0; k < 256; k = k + 1) begin
                            req_mask[k] = ({$random(ds)} % 4) != 0;
                            req_addresses[k*13 +: 13] = {$random(ds)} % (words > 0 ? words : 1);
                        end
                        if (({$random(ds)} % 40) == 0) begin
                            k = {$random(ds)} % 256;
                            req_addresses[k*13 +: 13] = words + ({$random(ds)} % 3);
                        end
                        req_epoch = (({$random(ds)} % 60) == 0) ? ep + 1 : ep;
                        if (rr && req_valid)
                            $fdisplay(fd, "READ m=%h e=%0d", req_mask, req_epoch);
                        nread = nread + 1;
                    end
                end
            end
            endcase
            if (ev) begin $fdisplay(fd, "ERR c=%0d", ec); nerr = nerr + 1; end
            if (ov && out_ready) begin $fdisplay(fd, "OUT e=%h d=%h", oe, od[63:0]); nout = nout + 1; end
        end
        $fflush(fd); $fclose(fd);
        $display("FB_DRIVER v13p=%0d data_seed=%0d time_seed=%0d begin=%0d word=%0d commit=%0d read=%0d err=%0d out=%0d",
                 V13P, DATA_SEED, TIME_SEED, nbeg, nword, ncommit, nread, nerr, nout);
    end

    wire [12:0] unused_out = o_dummy;
    assign dbg = {rst_n, cancel, cfg_word_valid, cfg_commit, cfg_begin, ov, sv, ld, br, phase[3:0]};
    assign dbgx = {24'b0, cfg_epoch[7:0], 5'b0, cfg_channels, 1'b0, cfg_height, 1'b0, cfg_width,
                   br, wr, cr, rr};
endmodule

module tb_fbank_v13_vs_v13p;
    parameter integer SEED = 1, CYCLES = 200000;
    reg clk = 0; always #5 clk = ~clk;
    // Different timing seeds so the two DUTs are NOT in lockstep: a miter that
    // shares one driver cannot exercise v13p's delayed accept at all.
    fb_driver #(.V13P(0), .DATA_SEED(SEED), .TIME_SEED(SEED),      .CYCLES(CYCLES)) d0(.clk(clk));
    fb_driver #(.V13P(1), .DATA_SEED(SEED), .TIME_SEED(SEED + 101), .CYCLES(CYCLES)) d1(.clk(clk));
    initial begin
        repeat (CYCLES + 200) @(negedge clk);
        $display("FBANK_V13P_MITER seed=%0d cycles=%0d written", SEED, CYCLES);
        $finish;
    end
endmodule
