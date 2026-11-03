`timescale 1ns/1ps
`default_nettype none

module tb_z100_native_axi64_writer;
    localparam integer DDR_BASE = 32'h1000_0000;
    localparam integer MEM_BYTES = 1_048_576;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;

    reg cmd_valid = 1'b0;
    wire cmd_ready;
    reg [31:0] cmd_epoch = 0;
    reg [31:0] cmd_address = 0;
    reg [13:0] cmd_word_count = 0;
    reg in_valid = 1'b0;
    wire in_ready;
    reg [31:0] in_epoch = 0;
    reg [12:0] in_index = 0;
    reg [511:0] in_data = 0;
    reg in_last = 0;
    reg cancel = 1'b0;
    reg timeout = 1'b0;
    reg clear_fault = 1'b0;
    wire busy, done, fault;
    wire [3:0] fault_code;

    wire [5:0] m_axi_awid;
    wire [31:0] m_axi_awaddr;
    wire [3:0] m_axi_awlen;
    wire [2:0] m_axi_awsize;
    wire [1:0] m_axi_awburst;
    wire m_axi_awvalid;
    reg m_axi_awready = 0;
    wire [5:0] m_axi_wid;
    wire [63:0] m_axi_wdata;
    wire [7:0] m_axi_wstrb;
    wire m_axi_wlast, m_axi_wvalid;
    reg m_axi_wready = 0;
    reg [5:0] m_axi_bid = 0;
    reg [1:0] m_axi_bresp = 0;
    reg m_axi_bvalid = 0;
    wire m_axi_bready;

    z100_native_axi64_writer dut (.*);

    reg aw_allow = 1'b1;
    reg w_allow = 1'b1;
    reg b_allow = 1'b1;
    reg force_aw_ready = 1'b0;
    reg force_w_run = 1'b0;
    reg [31:0] lfsr = 32'h5a17_c3e9;
    reg slave_active = 1'b0;
    reg b_pending = 1'b0;
    integer b_delay_count = 0;
    integer b_delay_setting = 3;
    reg [31:0] next_bid = 0;
    reg [1:0] next_bresp = 0;
    integer slave_awaddr = 0;
    integer slave_awbeats = 0;
    integer slave_wbeat = 0;

    reg score_enable = 1'b0;
    reg [31:0] score_base = 0;
    reg [13:0] score_words = 0;
    reg [31:0] score_epoch = 0;
    integer score_input_words = 0;
    integer score_aw_words = 0;
    integer score_written_words = 0;
    reg [7:0] expected_mem [0:MEM_BYTES-1];
    reg [7:0] actual_mem [0:MEM_BYTES-1];

    integer aw_count = 0;
    integer w_count = 0;
    integer b_count = 0;
    integer done_count = 0;
    integer invalid_count = 0;
    integer stream_fault_count = 0;
    integer cancel_count = 0;
    integer timeout_count = 0;
    integer bid_fault_count = 0;
    integer bresp_fault_count = 0;
    integer blocked_poll_count = 0;
    integer aw_hold_count = 0;
    integer w_hold_count = 0;
    integer max_w_streak = 0;
    integer current_w_streak = 0;
    integer cycle_count = 0;
    reg held_aw = 1'b0;
    reg [31:0] held_awaddr = 0;
    reg [3:0] held_awlen = 0;
    reg held_w = 1'b0;
    reg [63:0] held_wdata = 0;
    reg [7:0] held_wstrb = 0;
    reg held_wlast = 0;
    integer i, j, byte_addr, word_no, expected_burst_words, page_words;
    reg [511:0] check_word;

    function [7:0] input_byte;
        input [12:0] word_index;
        input [31:0] epoch;
        input integer byte_index;
        integer value;
        begin
            value = word_index * 13 + byte_index * 29 + epoch * 7 + (word_index >> 4);
            input_byte = value[7:0];
        end
    endfunction

    function [7:0] golden_byte;
        input [12:0] word_index;
        input [31:0] epoch;
        input integer byte_index;
        integer value;
        begin
            value = word_index * 13 + byte_index * 29 + epoch * 7 +
                    ((word_index & 13'h1ff0) >> 4);
            golden_byte = value[7:0];
        end
    endfunction

    function [511:0] make_input_word;
        input [12:0] word_index;
        input [31:0] epoch;
        integer b;
        begin
            for (b = 0; b < 64; b = b + 1)
                make_input_word[b*8 +: 8] = input_byte(word_index, epoch, b);
        end
    endfunction

    always @(negedge clk) begin
        lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
        m_axi_awready = aw_allow && !slave_active &&
                        (force_aw_ready || (lfsr[1:0] != 0));
        m_axi_wready = w_allow && slave_active && !b_pending &&
                       (force_w_run || (lfsr[5:2] != 0));
        if (!m_axi_bvalid && b_pending && b_allow) begin
            if (b_delay_count > 0)
                b_delay_count = b_delay_count - 1;
            else if (lfsr[9:6] != 0) begin
                m_axi_bvalid = 1'b1;
                m_axi_bid = next_bid[5:0];
                m_axi_bresp = next_bresp;
            end
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            slave_active = 1'b0;
            b_pending = 1'b0;
            m_axi_bvalid <= 1'b0;
            held_aw = 1'b0;
            held_w = 1'b0;
            current_w_streak = 0;
        end else begin
            cycle_count = cycle_count + 1;
            if (cycle_count > 2_000_000)
                $fatal(1, "global watchdog expired busy=%0d fault=%0d code=%0d", busy, fault, fault_code);

            if (held_aw) begin
                if (!m_axi_awvalid || m_axi_awaddr !== held_awaddr || m_axi_awlen !== held_awlen)
                    $fatal(1, "AW changed while stalled");
                aw_hold_count = aw_hold_count + 1;
            end
            held_aw = m_axi_awvalid && !m_axi_awready;
            if (held_aw) begin
                held_awaddr = m_axi_awaddr;
                held_awlen = m_axi_awlen;
            end

            if (held_w) begin
                if (!m_axi_wvalid || m_axi_wdata !== held_wdata || m_axi_wstrb !== held_wstrb ||
                    m_axi_wlast !== held_wlast || m_axi_wid !== 0)
                    $fatal(1, "W payload changed while stalled");
                w_hold_count = w_hold_count + 1;
            end
            held_w = m_axi_wvalid && !m_axi_wready;
            if (held_w) begin
                held_wdata = m_axi_wdata;
                held_wstrb = m_axi_wstrb;
                held_wlast = m_axi_wlast;
            end

            if (in_valid && in_ready)
                score_input_words = score_input_words + 1;

            if (m_axi_awvalid && m_axi_awready) begin
                if (slave_active || m_axi_awid !== 0 || m_axi_awsize !== 3 || m_axi_awburst !== 2'b01)
                    $fatal(1, "AW identity/ordering/geometry failure");
                if (m_axi_awaddr[5:0] != 0 || (m_axi_awlen != 7 && m_axi_awlen != 15))
                    $fatal(1, "AW alignment or burst length failure addr=%08x len=%0d", m_axi_awaddr, m_axi_awlen);
                if (({1'b0,m_axi_awaddr[11:0]} + ((m_axi_awlen + 1) * 8)) > 4096)
                    $fatal(1, "AW crosses 4KiB boundary");
                expected_burst_words = (m_axi_awlen + 1) / 8;
                if (score_enable) begin
                    if (m_axi_awaddr !== score_base + score_aw_words * 64)
                        $fatal(1, "AW order/address expected=%08x actual=%08x", score_base + score_aw_words*64, m_axi_awaddr);
                    page_words = (4096 - (m_axi_awaddr & 4095)) / 64;
                    if (score_words - score_aw_words < expected_burst_words)
                        $fatal(1, "Unexpected AW beyond command count");
                    if (expected_burst_words > 2 || expected_burst_words > page_words ||
                        expected_burst_words != ((score_words-score_aw_words < 2) ?
                            score_words-score_aw_words : 2) && page_words >= 2)
                        $fatal(1, "AW burst split differs from expected 2-word/page policy");
                    if (score_input_words < score_aw_words + expected_burst_words)
                        $fatal(1, "AW advertised before its complete input burst was buffered");
                    score_aw_words = score_aw_words + expected_burst_words;
                end
                slave_active = 1'b1;
                slave_awaddr = m_axi_awaddr;
                slave_awbeats = m_axi_awlen + 1;
                slave_wbeat = 0;
                aw_count = aw_count + 1;
            end

            if (m_axi_wvalid && m_axi_wready) begin
                if (!slave_active || m_axi_wid !== 0 || m_axi_wstrb !== 8'hff)
                    $fatal(1, "W before AW, wrong ID, or wrong WSTRB");
                if (m_axi_wlast !== (slave_wbeat == slave_awbeats - 1))
                    $fatal(1, "WLAST mismatch beat=%0d total=%0d", slave_wbeat, slave_awbeats);
                if (((slave_awaddr & 4095) + (slave_awbeats * 8)) > 4096)
                    $fatal(1, "Accepted W burst crosses 4KiB");
                if (score_enable) begin
                    word_no = (slave_awaddr - score_base) / 64 + slave_wbeat / 8;
                    if (word_no < 0 || word_no >= score_words)
                        $fatal(1, "W outside configured input sequence");
                    check_word = make_input_word(word_no[12:0], score_epoch);
                    if (m_axi_wdata !== check_word[(slave_wbeat % 8)*64 +: 64])
                        $fatal(1, "W data/order mismatch word=%0d beat=%0d", word_no, slave_wbeat);
                    byte_addr = slave_awaddr - DDR_BASE + slave_wbeat * 8;
                    if (byte_addr < 0 || byte_addr + 7 >= MEM_BYTES)
                        $fatal(1, "Scoreboard address outside modeled DDR");
                    for (j = 0; j < 8; j = j + 1)
                        actual_mem[byte_addr+j] = m_axi_wdata[j*8 +: 8];
                end
                w_count = w_count + 1;
                current_w_streak = current_w_streak + 1;
                if (current_w_streak > max_w_streak)
                    max_w_streak = current_w_streak;
                if (m_axi_wlast) begin
                    if (score_enable)
                        score_written_words = score_written_words + expected_burst_words;
                    b_pending = 1'b1;
                    b_delay_count = b_delay_setting;
                    slave_wbeat = 0;
                end else begin
                    slave_wbeat = slave_wbeat + 1;
                end
            end else begin
                current_w_streak = 0;
            end

            if (m_axi_bvalid && m_axi_bready) begin
                b_count = b_count + 1;
                m_axi_bvalid <= 1'b0;
                b_pending = 1'b0;
                slave_active = 1'b0;
                next_bid = 0;
                next_bresp = 0;
            end
            if (done)
                done_count = done_count + 1;
        end
    end

    task prepare_score;
        input [31:0] base;
        input integer words;
        input [31:0] epoch;
        input enable_score;
        integer k;
        integer address_index;
        begin
            score_enable = enable_score;
            score_base = base;
            score_words = words;
            score_epoch = epoch;
            score_input_words = 0;
            score_aw_words = 0;
            score_written_words = 0;
            if (enable_score) begin
                if (base < DDR_BASE || base + words*64 > DDR_BASE + MEM_BYTES)
                    $fatal(1, "Test scoreboard range invalid");
                for (k = 0; k < words*64; k = k + 1) begin
                    address_index = base - DDR_BASE + k;
                    expected_mem[address_index] = golden_byte((k/64), epoch, k%64);
                    actual_mem[address_index] = 8'h00;
                end
            end
        end
    endtask

    task verify_score;
        input integer words;
        integer k;
        integer address_index;
        begin
            if (score_enable) begin
                if (score_written_words != words)
                    $fatal(1, "Scoreboard words written expected=%0d actual=%0d", words, score_written_words);
                for (k = 0; k < words*64; k = k + 1) begin
                    address_index = score_base - DDR_BASE + k;
                    if (actual_mem[address_index] !== expected_mem[address_index])
                        $fatal(1, "Byte scoreboard mismatch offset=%0d got=%02x expected=%02x",
                               k, actual_mem[address_index], expected_mem[address_index]);
                end
            end
        end
    endtask

    task issue;
        input [31:0] base;
        input [13:0] words;
        input [31:0] epoch;
        integer waits;
        reg accepted;
        begin
            @(negedge clk);
            cmd_address = base;
            cmd_word_count = words;
            cmd_epoch = epoch;
            cmd_valid = 1'b1;
            waits = 0;
            accepted = 1'b0;
            while (!accepted) begin
                @(posedge clk);
                if (cmd_ready) accepted = 1'b1;
                waits = waits + 1;
                if (waits > 2000)
                    $fatal(1, "Command was not accepted base=%08x count=%0d fault=%0d", base, words, fault);
            end
            @(negedge clk);
            cmd_valid = 1'b0;
            // The accepted command is a snapshot; hostile live pins must be ignored.
            cmd_address = 32'hdead_c0c0;
            cmd_word_count = 14'd8193;
            cmd_epoch = 0;
        end
    endtask

    task push_meta;
        input [12:0] index;
        input [31:0] epoch;
        input last_value;
        integer waits;
        reg accepted;
        begin
            @(negedge clk);
            in_index = index;
            in_epoch = epoch;
            in_last = last_value;
            in_data = make_input_word(index, epoch);
            in_valid = 1'b1;
            waits = 0;
            accepted = 1'b0;
            while (!accepted) begin
                @(posedge clk);
                if (in_ready) accepted = 1'b1;
                waits = waits + 1;
                if (waits > 100000)
                    $fatal(1, "Input word stalled indefinitely index=%0d busy=%0d fault=%0d", index, busy, fault);
            end
            @(negedge clk);
            in_valid = 1'b0;
        end
    endtask

    task wait_done;
        input integer previous_done;
        integer waits;
        begin
            waits = 0;
            while (done_count == previous_done) begin
                @(posedge clk);
                waits = waits + 1;
                if (waits > 1_000_000)
                    $fatal(1, "Done watchdog busy=%0d fault=%0d code=%0d", busy, fault, fault_code);
            end
        end
    endtask

    task wait_idle;
        integer waits;
        begin
            waits = 0;
            while (busy) begin
                @(posedge clk);
                waits = waits + 1;
                if (waits > 100000)
                    $fatal(1, "Busy did not clear fault=%0d code=%0d", fault, fault_code);
            end
        end
    endtask

    task clear_fault_now;
        begin
            if (busy)
                $fatal(1, "Attempted to clear fault while AXI transaction is outstanding");
            @(negedge clk); clear_fault = 1'b1;
            @(posedge clk);
            @(negedge clk); clear_fault = 1'b0;
            @(posedge clk);
            if (fault || !cmd_ready)
                $fatal(1, "Fault did not clear in idle");
        end
    endtask

    task probe_blocked_clear_and_reload;
        integer k;
        begin
            @(negedge clk); clear_fault = 1'b1;
            cmd_valid = 1'b1;
            cmd_epoch = 32'd77;
            cmd_address = 32'h1008_0000;
            cmd_word_count = 14'd1;
            for (k = 0; k < 200; k = k + 1) begin
                @(posedge clk);
                if (cmd_ready || !busy || !fault)
                    $fatal(1, "Clear/reload unexpectedly accepted with outstanding AXI transaction");
                blocked_poll_count = blocked_poll_count + 1;
            end
            @(negedge clk);
            cmd_valid = 1'b0;
            clear_fault = 1'b0;
        end
    endtask

    task wait_fault_idle;
        input [3:0] code;
        integer waits;
        begin
            waits = 0;
            while (busy) begin
                @(posedge clk);
                waits = waits + 1;
                if (waits > 100000)
                    $fatal(1, "Faulted transfer did not drain code=%0d current=%0d", code, fault_code);
            end
            if (!fault || fault_code !== code)
                $fatal(1, "Expected sticky fault code %0d got fault=%0d code=%0d", code, fault, fault_code);
        end
    endtask

    task pulse_cancel;
        begin
            @(negedge clk); cancel = 1'b1;
            @(posedge clk);
            @(negedge clk); cancel = 1'b0;
        end
    endtask

    task pulse_timeout;
        begin
            @(negedge clk); timeout = 1'b1;
            @(posedge clk);
            @(negedge clk); timeout = 1'b0;
        end
    endtask

    task invalid_command;
        input [31:0] base;
        input [13:0] words;
        input [31:0] epoch;
        integer before_aw;
        integer waits;
        reg accepted;
        begin
            prepare_score(base, 0, epoch, 1'b0);
            before_aw = aw_count;
            @(negedge clk);
            cmd_address = base; cmd_word_count = words; cmd_epoch = epoch; cmd_valid = 1'b1;
            waits = 0;
            accepted = 1'b0;
            while (!accepted) begin
                @(posedge clk);
                if (cmd_ready) accepted = 1'b1;
                waits = waits + 1;
                if (waits > 1000) $fatal(1, "Invalid descriptor handshake blocked unexpectedly");
            end
            @(negedge clk); cmd_valid = 1'b0;
            waits = 0;
            while (!fault) begin
                @(posedge clk); waits = waits + 1;
                if (waits > 10) $fatal(1, "Invalid command did not fault");
            end
            if (fault_code !== 4'd1 || busy || aw_count != before_aw || m_axi_awvalid)
                $fatal(1, "Invalid descriptor caused bus activity or wrong error");
            invalid_count = invalid_count + 1;
            clear_fault_now();
        end
    endtask

    task stream_error;
        input integer kind;
        input [3:0] expected_code;
        integer before_aw;
        begin
            prepare_score(32'h1008_0000, 2, 32'd31, 1'b0);
            issue(32'h1008_0000, 14'd2, 32'd31);
            before_aw = aw_count;
            case (kind)
                0: push_meta(13'd0, 32'd32, 1'b0);
                1: push_meta(13'd1, 32'd31, 1'b0);
                default: push_meta(13'd0, 32'd31, 1'b1);
            endcase
            if (!fault || fault_code !== expected_code || busy || aw_count != before_aw || m_axi_awvalid)
                $fatal(1, "Malformed input was not rejected before AW kind=%0d", kind);
            stream_fault_count = stream_fault_count + 1;
            clear_fault_now();
        end
    endtask

    task late_stream_error_after_committed_burst;
        integer before_aw;
        integer before_b;
        integer k;
        integer address_index;
        begin
            prepare_score(32'h1008_0380, 3, 32'd48, 1'b1);
            before_aw = aw_count;
            before_b = b_count;
            issue(32'h1008_0380, 14'd3, 32'd48);
            push_meta(13'd0, 32'd48, 1'b0);
            push_meta(13'd1, 32'd48, 1'b0);
            // This word is rejected after the first complete 2-word burst was written.
            push_meta(13'd2, 32'd49, 1'b1);
            wait_fault_idle(4'd2);
            if (aw_count != before_aw+1 || b_count != before_b+1 ||
                score_written_words != 2 || m_axi_awvalid)
                $fatal(1, "Late malformed word did not leave exactly one prior burst written");
            verify_score(2);
            for (k = 0; k < 64; k = k + 1) begin
                address_index = score_base - DDR_BASE + 128 + k;
                if (actual_mem[address_index] !== 8'h00)
                    $fatal(1, "Rejected third word was written at byte %0d", k);
            end
            stream_fault_count = stream_fault_count + 1;
            clear_fault_now();
        end
    endtask

    integer baseline_aw, baseline_w, baseline_b, baseline_done;
    integer k, start_w, before_aw, before_b;
    integer full_aw, full_w, full_b;
    integer actual_addr;

    initial begin
        for (i = 0; i < MEM_BYTES; i = i + 1) begin
            expected_mem[i] = 0;
            actual_mem[i] = 0;
        end
        repeat (5) @(posedge clk);
        if (cmd_ready || in_ready || m_axi_awvalid || m_axi_wvalid || m_axi_bready)
            $fatal(1, "Private ready/valid signals were not suppressed during platform reset");
        @(negedge clk); rst_n = 1'b1;
        repeat (3) @(posedge clk);

        // Full 8192-word, 4KiB-page-safe, byte-addressed write/readback.
        prepare_score(32'h1000_0000, 8192, 32'h1234_5678, 1'b1);
        baseline_done = done_count;
        issue(32'h1000_0000, 14'd8192, 32'h1234_5678);
        push_meta(13'd0, 32'h1234_5678, 1'b0);
        push_meta(13'd1, 32'h1234_5678, 1'b0);
        force_w_run = 1'b1;
        start_w = w_count;
        while (w_count < start_w + 16) @(posedge clk);
        force_w_run = 1'b0;
        for (k = 2; k < 8192; k = k + 1)
            push_meta(k[12:0], 32'h1234_5678, (k == 8191));
        wait_done(baseline_done);
        wait_idle();
        if (fault || aw_count != 4096 || w_count != 65536 || b_count != 4096)
            $fatal(1, "Full-capacity totals mismatch aw=%0d w=%0d b=%0d", aw_count, w_count, b_count);
        if (score_written_words != 8192 || max_w_streak < 16)
            $fatal(1, "Full capacity or W burst coverage missing");
        verify_score(8192);
        full_aw = aw_count; full_w = w_count; full_b = b_count;

        // Exact 32-bit exclusive-end boundary is valid and one beat group safe.
        prepare_score(32'hffff_ffc0, 1, 32'h31, 1'b0);
        baseline_done = done_count;
        issue(32'hffff_ffc0, 14'd1, 32'h31);
        push_meta(13'd0, 32'h31, 1'b1);
        wait_done(baseline_done);
        wait_idle();
        if (fault) $fatal(1, "Exact address-end boundary command failed");

        // A two-word command beginning in the last word of a page must split into
        // two independently acknowledged single-word bursts.
        prepare_score(32'h1000_0fc0, 2, 32'h32, 1'b1);
        baseline_done = done_count;
        issue(32'h1000_0fc0, 14'd2, 32'h32);
        push_meta(13'd0, 32'h32, 1'b0);
        push_meta(13'd1, 32'h32, 1'b1);
        wait_done(baseline_done);
        wait_idle();
        if (fault) $fatal(1, "Page-split command failed");
        verify_score(2);

        invalid_command(32'h1000_0000, 14'd1, 32'd0);
        invalid_command(32'h1000_0001, 14'd1, 32'd1);
        invalid_command(32'h1000_0000, 14'd0, 32'd1);
        invalid_command(32'h1000_0000, 14'd8193, 32'd1);
        invalid_command(32'hffff_ffc0, 14'd2, 32'd1);

        stream_error(0, 4'd2); // wrong epoch
        stream_error(1, 4'd3); // wrong index
        stream_error(2, 4'd4); // wrong last
        late_stream_error_after_committed_burst();

        // Cancel while only part of the next burst is privately buffered.
        prepare_score(32'h1008_0000, 2, 32'd41, 1'b0);
        before_aw = aw_count;
        issue(32'h1008_0000, 14'd2, 32'd41);
        push_meta(13'd0, 32'd41, 1'b0);
        pulse_cancel();
        wait_fault_idle(4'd8);
        if (aw_count != before_aw || m_axi_awvalid)
            $fatal(1, "Cancel during prebuffer advertised an AW");
        cancel_count = cancel_count + 1;
        clear_fault_now();

        // Cancel after AWVALID: address/length cannot be withdrawn; buffered W drains.
        prepare_score(32'h1008_0040, 2, 32'd42, 1'b1);
        aw_allow = 1'b0;
        before_aw = aw_count; before_b = b_count;
        issue(32'h1008_0040, 14'd2, 32'd42);
        push_meta(13'd0, 32'd42, 1'b0);
        push_meta(13'd1, 32'd42, 1'b1);
        repeat (4) @(posedge clk);
        if (!m_axi_awvalid) $fatal(1, "Expected pending AW before cancellation");
        pulse_cancel();
        probe_blocked_clear_and_reload();
        if (!m_axi_awvalid || !busy || !fault)
            $fatal(1, "AW cancellation did not remain pending safely");
        if (aw_count != before_aw || b_count != before_b)
            $fatal(1, "AW stall accepted unexpectedly");
        aw_allow = 1'b1;
        wait_fault_idle(4'd8);
        if (aw_count != before_aw+1 || b_count != before_b+1)
            $fatal(1, "Advertised AW was not fully drained");
        verify_score(2);
        cancel_count = cancel_count + 1;
        clear_fault_now();

        // Cancel mid-W with a permanently held beat, then release and finish it.
        prepare_score(32'h1008_0100, 2, 32'd43, 1'b1);
        aw_allow = 1'b1; force_aw_ready = 1'b1; w_allow = 1'b0;
        start_w = w_count; before_b = b_count;
        issue(32'h1008_0100, 14'd2, 32'd43);
        push_meta(13'd0, 32'd43, 1'b0);
        push_meta(13'd1, 32'd43, 1'b1);
        repeat (5) @(posedge clk);
        force_aw_ready = 1'b0;
        w_allow = 1'b1;
        while (w_count < start_w+3) @(posedge clk);
        w_allow = 1'b0;
        repeat (3) @(posedge clk);
        if (!m_axi_wvalid || m_axi_wready) $fatal(1, "Expected held W beat before cancel");
        pulse_cancel();
        probe_blocked_clear_and_reload();
        if (!m_axi_wvalid || m_axi_wready || !busy || !fault)
            $fatal(1, "W cancellation did not hold outstanding beat");
        w_allow = 1'b1;
        wait_fault_idle(4'd8);
        if (b_count != before_b+1) $fatal(1, "W cancellation failed to consume B");
        verify_score(2);
        cancel_count = cancel_count + 1;
        clear_fault_now();

        // Timeout after AW has been advertised; permanently blocked AW cannot be abandoned.
        prepare_score(32'h1008_0180, 2, 32'd44, 1'b1);
        aw_allow = 1'b0; before_aw = aw_count; before_b = b_count;
        issue(32'h1008_0180, 14'd2, 32'd44);
        push_meta(13'd0, 32'd44, 1'b0);
        push_meta(13'd1, 32'd44, 1'b1);
        repeat (4) @(posedge clk);
        pulse_timeout();
        probe_blocked_clear_and_reload();
        if (!m_axi_awvalid || !busy || !fault || fault_code != 7)
            $fatal(1, "Timeout abandoned or cleared a pending AW");
        aw_allow = 1'b1;
        wait_fault_idle(4'd7);
        if (aw_count != before_aw+1 || b_count != before_b+1)
            $fatal(1, "Timed-out AW/W/B transaction did not drain");
        verify_score(2);
        timeout_count = timeout_count + 1;
        clear_fault_now();

        // A missing B response keeps busy/faulted and rejects clear/reload for 200 polls.
        prepare_score(32'h1008_0200, 2, 32'd45, 1'b1);
        b_allow = 1'b0; before_b = b_count;
        issue(32'h1008_0200, 14'd2, 32'd45);
        push_meta(13'd0, 32'd45, 1'b0);
        push_meta(13'd1, 32'd45, 1'b1);
        while (!b_pending) @(posedge clk);
        pulse_cancel();
        probe_blocked_clear_and_reload();
        if (b_count != before_b || !busy || !fault)
            $fatal(1, "Missing B did not keep write outstanding");
        b_allow = 1'b1;
        wait_fault_idle(4'd8);
        if (b_count != before_b+1) $fatal(1, "B response was not consumed after release");
        verify_score(2);
        cancel_count = cancel_count + 1;
        clear_fault_now();

        // Validate strict BID and BRESP handling after the response is consumed.
        prepare_score(32'h1008_0280, 2, 32'd46, 1'b1);
        next_bid = 6'd1;
        issue(32'h1008_0280, 14'd2, 32'd46);
        push_meta(13'd0, 32'd46, 1'b0);
        push_meta(13'd1, 32'd46, 1'b1);
        wait_fault_idle(4'd5);
        verify_score(2);
        bid_fault_count = bid_fault_count + 1;
        clear_fault_now();

        prepare_score(32'h1008_0300, 2, 32'd47, 1'b1);
        next_bresp = 2'b10;
        issue(32'h1008_0300, 14'd2, 32'd47);
        push_meta(13'd0, 32'd47, 1'b0);
        push_meta(13'd1, 32'd47, 1'b1);
        wait_fault_idle(4'd6);
        verify_score(2);
        bresp_fault_count = bresp_fault_count + 1;
        clear_fault_now();

        if (done_count != 3 || full_aw != 4096 || full_w != 65536 || full_b != 4096 ||
            invalid_count != 5 || stream_fault_count != 4 || cancel_count != 4 ||
            timeout_count != 1 || bid_fault_count != 1 || bresp_fault_count != 1 ||
            blocked_poll_count < 800 || max_w_streak < 16 || aw_hold_count == 0 || w_hold_count == 0)
            $fatal(1, "Coverage counters incomplete done=%0d invalid=%0d stream=%0d cancel=%0d timeout=%0d blocked=%0d",
                   done_count, invalid_count, stream_fault_count, cancel_count, timeout_count, blocked_poll_count);

        $display("NATIVE_AXI64_WRITER_PASS bytes=524288 words=8192 aw=%0d w=%0d b=%0d invalid=%0d stream_faults=%0d cancel=%0d timeout=%0d bid=%0d bresp=%0d blocked=%0d max_w_streak=%0d aw_hold=%0d w_hold=%0d done=%0d capacity_words=8192",
                 aw_count, w_count, b_count, invalid_count, stream_fault_count, cancel_count,
                 timeout_count, bid_fault_count, bresp_fault_count, blocked_poll_count,
                 max_w_streak, aw_hold_count, w_hold_count, done_count);
        $finish;
    end
endmodule
`default_nettype wire
