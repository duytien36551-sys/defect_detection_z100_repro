`timescale 1ns/1ps
// Sequential-equivalence check: z100_feature_banks_4read_writepipe_4k_v13
// (reference) vs ..._v13p (geometry precompute; begin accept may slip 1-2 cycles).
//
// One shared driver feeds both DUTs identical inputs every cycle. The only
// intended difference is *when* cfg_begin_ready rises, so cfg_begin is held
// until BOTH have taken it; after that the two stores run in lockstep and every
// word/commit/read/error/output transaction must match one for one.
//
// The verdict is a transaction log, not a per-cycle vector compare: inside the
// delayed-accept window the DUTs legitimately differ. cmp_fbank_logs.py does
// the comparison.
module tb_fbank_v13_vs_v13p;
    parameter integer SEED = 1, CYCLES = 200000, PULSE_MODE = 0;
    reg clk = 0; always #5 clk = ~clk;
    reg rst_n, cancel, cfg_begin, cfg_canon, cfg_word_valid, cfg_word_last, cfg_commit, req_valid, out_ready;
    reg [31:0] cfg_epoch, cfg_word_epoch, req_epoch;
    reg [10:0] cfg_channels; reg [9:0] cfg_height, cfg_width;
    reg [511:0] cfg_word_data; reg [12:0] cfg_word_address;
    reg [64*4*13-1:0] req_addresses; reg [255:0] req_mask;

    wire [12:0] o0, o1; wire [3:0] ec0, ec1; wire [31:0] ae0, ae1, oe0, oe1; wire [2047:0] od0, od1;
    wire br0,wr0,cr0,ev0,sv0,ld0,rr0,ov0, br1,wr1,cr1,ev1,sv1,ld1,rr1,ov1;
`define FB_PORTS(br,wr,cr,ev,ec,sv,ae,ld,rr,ov,oe,od) .clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_begin(cfg_begin),.cfg_begin_ready(br), \
    .cfg_epoch(cfg_epoch),.cfg_canonical_order(cfg_canon),.cfg_channels(cfg_channels),.cfg_height(cfg_height),.cfg_width(cfg_width), \
    .cfg_word_valid(cfg_word_valid),.cfg_word_ready(wr),.cfg_word_data(cfg_word_data),.cfg_word_epoch(cfg_word_epoch), \
    .cfg_word_address(cfg_word_address),.cfg_word_last(cfg_word_last),.cfg_commit(cfg_commit),.cfg_commit_ready(cr), \
    .error_valid(ev),.error_code(ec),.store_valid(sv),.active_epoch(ae),.loading(ld),.req_valid(req_valid),.req_ready(rr), \
    .req_epoch(req_epoch),.req_addresses(req_addresses),.req_mask(req_mask),.out_valid(ov),.out_ready(out_ready),.out_epoch(oe),.out_data(od)

    z100_feature_banks_4read_writepipe_4k_v13  ref_dut(`FB_PORTS(br0,wr0,cr0,ev0,ec0,sv0,ae0,ld0,rr0,ov0,oe0,od0));
    z100_feature_banks_4read_writepipe_4k_v13p p_dut  (`FB_PORTS(br1,wr1,cr1,ev1,ec1,sv1,ae1,ld1,rr1,ov1,oe1,od1));

    integer fr, fp, s, cyc, k, words, wi, phase, wait_begin;
    reg [31:0] ep;
    integer n_beg, n_word, n_commit, n_read, n_err, n_out;
    reg b0, b1, w0, w1, c0, c1, rq0, rq1;
    // "this side has accepted the begin currently presented" - v13p may accept
    // one or two cycles after v13, so a same-cycle AND never fires.
    reg sb0, sb1, begin_presented;
    // One BEGIN transaction per presented cfg_begin: both stores may keep
    // accepting a held begin (an illegal config leaves load_active low, so
    // ready comes back immediately), and those extra accepts are not separate
    // transactions.
    reg logged0, logged1;
    // ERR c=1 (BAD_CONFIG) can fire more than once for one held cfg_begin
    // (retries without a new rising edge). v13 raises it on the ready edge,
    // v13p one cycle after its own ready edge - different counts, same fault.
    // Collapse consecutive identical BAD_CONFIG lines into one transaction.
    reg err_prev0, err_prev1; integer errc0, errc1;

    always @(posedge clk) begin
        b0  <= cfg_begin && br0;      b1  <= cfg_begin && br1;
        w0  <= cfg_word_valid && wr0; w1  <= cfg_word_valid && wr1;
        c0  <= cfg_commit && cr0;     c1  <= cfg_commit && cr1;
        rq0 <= req_valid && rr0;      rq1 <= req_valid && rr1;
        if (!rst_n) begin
            sb0 <= 1'b0; sb1 <= 1'b0; begin_presented <= 1'b0; logged0 = 1'b0; logged1 = 1'b0;
        end else begin
            // clear the flags on the rising edge of a new cfg_begin
            if (cfg_begin && !begin_presented) begin
                sb0 <= cfg_begin && br0;
                sb1 <= cfg_begin && br1;
            end else begin
                if (cfg_begin && br0) sb0 <= 1'b1;
                if (cfg_begin && br1) sb1 <= 1'b1;
            end
            begin_presented <= cfg_begin;
            if (cfg_begin && !begin_presented) begin logged0 = 1'b0; logged1 = 1'b0; end
        end
    end

    always @(posedge clk) if (rst_n) begin
        if (b0 && !logged0) begin logged0 = 1'b1; $fdisplay(fr, "BEGIN e=%0d c=%0d ch=%0d h=%0d w=%0d", cfg_epoch, cfg_canon, cfg_channels, cfg_height, cfg_width); n_beg = n_beg + 1; end
        if (b1 && !logged1) begin logged1 = 1'b1; $fdisplay(fp, "BEGIN e=%0d c=%0d ch=%0d h=%0d w=%0d", cfg_epoch, cfg_canon, cfg_channels, cfg_height, cfg_width); end
        if (w0) begin $fdisplay(fr, "WORD a=%0d e=%0d l=%0d d=%h", cfg_word_address, cfg_word_epoch, cfg_word_last, cfg_word_data); n_word = n_word + 1; end
        if (w1)   $fdisplay(fp, "WORD a=%0d e=%0d l=%0d d=%h", cfg_word_address, cfg_word_epoch, cfg_word_last, cfg_word_data);
        if (c0) begin $fdisplay(fr, "COMMIT sv=%0d ae=%0d ld=%0d", sv0, ae0, ld0); n_commit = n_commit + 1; end
        if (c1)   $fdisplay(fp, "COMMIT sv=%0d ae=%0d ld=%0d", sv1, ae1, ld1);
        if (rq0) begin $fdisplay(fr, "READ m=%h e=%0d", req_mask, req_epoch); n_read = n_read + 1; end
        if (rq1)  $fdisplay(fp, "READ m=%h e=%0d", req_mask, req_epoch);
        if (ev0) begin
            if (ec0 == 3'd1 && err_prev0) errc0 = errc0 + 1;
            else begin $fdisplay(fr, "ERR c=%0d ae=%0d sv=%0d", ec0, ae0, sv0); n_err = n_err + 1; end
            err_prev0 = (ec0 == 3'd1);
        end else err_prev0 = 1'b0;
        if (ev1) begin
            if (ec1 == 3'd1 && err_prev1) errc1 = errc1 + 1;
            else $fdisplay(fp, "ERR c=%0d ae=%0d sv=%0d", ec1, ae1, sv1);
            err_prev1 = (ec1 == 3'd1);
        end else err_prev1 = 1'b0;
        if (ov0 && out_ready) begin $fdisplay(fr, "OUT e=%h d=%h", oe0, od0[127:0]); n_out = n_out + 1; end
        if (ov1 && out_ready) $fdisplay(fp, "OUT e=%h d=%h", oe1, od1[127:0]);
    end

    task rand_req; integer p; begin
        for (p = 0; p < 256; p = p + 1) begin
            req_mask[p] = ({$random(s)} % 4) != 0;
            req_addresses[p*13 +: 13] = {$random(s)} % (words > 0 ? words : 1);
        end
        if (({$random(s)} % 40) == 0) begin
            p = {$random(s)} % 256;
            req_addresses[p*13 +: 13] = words + ({$random(s)} % 3);
        end
        req_epoch = (({$random(s)} % 60) == 0) ? ep + 1 : ep;
    end endtask

    initial begin
        fr = $fopen("ref.log", "w");
        fp = $fopen("new.log", "w");
        n_beg = 0; n_word = 0; n_commit = 0; n_read = 0; n_err = 0; n_out = 0;
        err_prev0 = 0; err_prev1 = 0; errc0 = 0; errc1 = 0;
        s = SEED; phase = 0; wi = 0; words = 0; ep = 1; wait_begin = 0;
        rst_n = 0; cancel = 0; cfg_begin = 0; cfg_canon = 1; cfg_word_valid = 0;
        cfg_word_last = 0; cfg_commit = 0; req_valid = 0; out_ready = 1;
        cfg_epoch = 0; cfg_word_epoch = 0; req_epoch = 0;
        cfg_channels = 8; cfg_height = 2; cfg_width = 32;
        cfg_word_data = 0; cfg_word_address = 0; req_addresses = 0; req_mask = 0;
        repeat (6) @(negedge clk); rst_n = 1;
        for (cyc = 0; cyc < CYCLES; cyc = cyc + 1) begin
            @(negedge clk);
            out_ready = ({$random(s)} % 3) != 0;
            cancel    = (({$random(s)} % 4000) == 0);
            if (cancel) begin phase = 0; cfg_begin = 0; cfg_word_valid = 0; cfg_commit = 0; req_valid = 0; end
            case (phase)
            0: begin
                req_valid = 0; cfg_word_valid = 0; cfg_commit = 0;
                ep = ep + 1;
                cfg_epoch = (({$random(s)} % 40) == 0) ? 0 : ep;
                // Cover both subgroup regimes (>=32 channels takes the 8-subgroup
                // path), the legal maxima, zero fields and the word-count limit.
                case ({$random(s)} % 8)
                  0,1,2: cfg_channels = 4 * (1 + {$random(s)} % 3);   // 4..12, <32
                  3,4:   cfg_channels = 32 + 4 * ({$random(s)} % 9);  // 32..64
                  5:     cfg_channels = 4 * (8 + {$random(s)} % 56);  // 32..252
                  6:     cfg_channels = 1024;                        // legal max
                  7:     cfg_channels = 4 * (1 + {$random(s)} % 3);
                  default: cfg_channels = 8;
                endcase
                cfg_height = 1 + {$random(s)} % 3;
                cfg_width = 16 * (1 + {$random(s)} % 3);
                if (({$random(s)} % 30) == 0) cfg_height = 640;      // forces > 8192 words
                if (({$random(s)} % 60) == 0) cfg_channels = 0;      // illegal: zero channels
                if (({$random(s)} % 60) == 0) cfg_height = 0;        // illegal: zero height
                if (({$random(s)} % 60) == 0) cfg_width = 0;         // illegal: zero width
                words = (cfg_channels / 4) * cfg_height * (cfg_width / 16);
                if (words <= 0) words = 1;
                wi = 0; wait_begin = 0;
                cfg_begin = 1; phase = 1;
            end
            // hold cfg_begin until BOTH stores took it (v13p may need two more)
            1: begin
                wait_begin = wait_begin + 1;
                // PULSE_MODE=1 drops cfg_begin after exactly one cycle, which is
                // how the real initiator drives it: a one-cycle begin must not
                // be lost just because the store wanted an extra cycle.
                if ((sb0 && sb1) || (PULSE_MODE == 1 && wait_begin >= 1)) begin
                    cfg_begin = 0; phase = 2;
                end else if (wait_begin > 12) begin cfg_begin = 0; phase = 0; end
            end
            2: begin
                cfg_word_valid = 1; cfg_word_address = wi; cfg_word_epoch = ep;
                cfg_word_last = (wi == words - 1);
                for (k = 0; k < 16; k = k + 1) cfg_word_data[k*32 +: 32] = $random(s);
                if (({$random(s)} % 150) == 0) cfg_word_address = wi + 1;
                phase = 3;
            end
            3: if (w0 && w1) begin
                   cfg_word_valid = 0; wi = wi + 1;
                   if (({$random(s)} % 100) == 0) begin cfg_commit = 1; phase = 4; end
                   else if (wi >= words) begin cfg_commit = 1; phase = 4; end
                   else phase = 2;
               end else if (!ld0 && !ld1) begin cfg_word_valid = 0; phase = 0; end
            4: if (c0 && c1) begin cfg_commit = 0; phase = 5; end
               else if (!ld0 && !ld1) begin cfg_commit = 0; phase = 0; end
            5: begin
                cfg_commit = 0; cfg_word_valid = 0;
                if (!sv0 && !sv1) begin req_valid = 0; phase = 0; end
                else if (!req_valid || (rq0 && rq1)) begin
                    if (({$random(s)} % 2000) == 0) begin req_valid = 0; phase = 0; end
                    else begin req_valid = ({$random(s)} % 4) != 0; rand_req; end
                    cfg_word_valid = (({$random(s)} % 500) == 0);
                end
            end
            endcase
        end
        $fclose(fr); $fclose(fp);
        $display("FBANK_V13P_MITER seed=%0d cycles=%0d begin=%0d word=%0d commit=%0d read=%0d err=%0d out=%0d",
                 SEED, CYCLES, n_beg, n_word, n_commit, n_read, n_err, n_out);
        $finish;
    end
endmodule
