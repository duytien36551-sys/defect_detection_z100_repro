`timescale 1ns/1ps
`default_nettype none

// Diagnostic-only replay of the unchanged production writer. mode=0 matches
// the full-prefetch helper's posedge/blocking READY counter update; mode=1
// advances the same periodic READY phase at negedge. Inputs are driven only
// at negedge. This is not a writer repair or production acceptance test.
module tb_z100_writer_ready_edge;
    localparam [31:0] EPOCH = 32'd77;
    localparam [31:0] BASE = 32'h10000fc0;
    localparam integer WORDS = 64;
    localparam [2:0] ST_AW = 3'd2;
    localparam [2:0] ST_W = 3'd3;
    localparam [2:0] ST_B = 3'd4;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;
    integer mode = 0;
    integer phase = 0;
    integer wb_cycle = 0;
    integer posedge_count = 0;

    reg cmd_valid = 0;
    wire cmd_ready;
    reg [31:0] cmd_epoch = 0;
    reg [31:0] cmd_address = 0;
    reg [13:0] cmd_word_count = 0;
    reg in_valid = 0;
    wire in_ready;
    reg [31:0] in_epoch = 0;
    reg [12:0] in_index = 0;
    reg [511:0] in_data = 0;
    reg in_last = 0;
    reg cancel = 0;
    reg timeout = 0;
    reg clear_fault = 0;
    wire busy, done, fault;
    wire [3:0] fault_code;

    wire [5:0] m_axi_awid;
    wire [31:0] m_axi_awaddr;
    wire [3:0] m_axi_awlen;
    wire [2:0] m_axi_awsize;
    wire [1:0] m_axi_awburst;
    wire m_axi_awvalid;
    wire m_axi_awready = (wb_cycle % 7) != 0;
    wire [5:0] m_axi_wid;
    wire [63:0] m_axi_wdata;
    wire [7:0] m_axi_wstrb;
    wire m_axi_wlast, m_axi_wvalid;
    wire m_axi_wready = (wb_cycle % 5) != 0;
    reg [5:0] m_axi_bid = 0;
    reg [1:0] m_axi_bresp = 0;
    reg m_axi_bvalid = 0;
    wire m_axi_bready;

    z100_native_axi64_writer dut (.*);

    reg b_pending = 0;
    reg b_clear = 0;
    integer b_delay = 0;
    reg [2:0] edge_pre_state = 0;
    reg edge_pre_awvalid = 0, edge_pre_awready = 0;
    reg [31:0] edge_pre_awaddr = 0;
    reg [3:0] edge_pre_awlen = 0;
    reg edge_pre_wvalid = 0, edge_pre_wready = 0, edge_pre_wlast = 0;
    reg [5:0] edge_pre_wid = 0;
    reg [63:0] edge_pre_wdata = 0;
    reg [7:0] edge_pre_wstrb = 0;
    reg [2:0] edge_pre_wbeat = 0;
    reg [1:0] edge_pre_wword = 0;
    reg edge_pre_bvalid = 0, edge_pre_bready = 0;
    integer edge_pre_cycle = 0;

    reg held_aw = 0;
    reg [31:0] held_awaddr = 0;
    reg [3:0] held_awlen = 0;
    integer held_aw_cycle = 0;
    reg held_aw_pre_ready = 0, held_aw_post_ready = 0;
    reg [2:0] held_aw_pre_state = 0, held_aw_post_state = 0;
    reg held_w = 0;
    reg [78:0] held_w_payload = 0;
    integer aw_hold_count = 0, w_hold_count = 0;
    integer input_words = 0, accepted_aw = 0, accepted_w = 0, accepted_b = 0;
    integer aw_edge_races = 0, w_edge_races = 0, done_count = 0;

    reg slave_active = 0;
    integer burst_words = 0, burst_beats = 0, burst_beat = 0;
    integer burst_word_base = 0, aw_words_total = 0, written_words_total = 0;
    integer expected_word = 0, byte_index = 0;
    reg [511:0] expected_word_data;

    function [7:0] payload_byte;
        input integer word_index;
        input integer byte_number;
        integer value;
        begin
            value = word_index * 13 + byte_number * 29 + EPOCH * 7 + (word_index >> 4);
            payload_byte = value[7:0];
        end
    endfunction

    function [511:0] make_word;
        input integer word_index;
        integer b;
        begin
            for (b = 0; b < 64; b = b + 1)
                make_word[b*8 +: 8] = payload_byte(word_index, b);
        end
    endfunction

    // Stable mode updates READY one half-cycle before the writer samples it.
    // Unstable mode deliberately retains the original blocking posedge update.
    always @(negedge clk) begin
        if (rst_n && mode == 1)
            wb_cycle = wb_cycle + 1;
        if (b_clear) begin
            m_axi_bvalid = 0;
            b_pending = 0;
            b_clear = 0;
        end else if (rst_n && b_pending && !m_axi_bvalid) begin
            if (b_delay > 0)
                b_delay = b_delay - 1;
            else begin
                m_axi_bvalid = 1;
                m_axi_bid = 0;
                m_axi_bresp = 0;
            end
        end
        #1;
        if (rst_n) begin
            edge_pre_state = dut.state;
            edge_pre_awvalid = m_axi_awvalid;
            edge_pre_awready = m_axi_awready;
            edge_pre_awaddr = m_axi_awaddr;
            edge_pre_awlen = m_axi_awlen;
            edge_pre_wvalid = m_axi_wvalid;
            edge_pre_wready = m_axi_wready;
            edge_pre_wdata = m_axi_wdata;
            edge_pre_wstrb = m_axi_wstrb;
            edge_pre_wlast = m_axi_wlast;
            edge_pre_wid = m_axi_wid;
            edge_pre_wbeat = dut.write_beat_select;
            edge_pre_wword = dut.write_word_select;
            edge_pre_bvalid = m_axi_bvalid;
            edge_pre_bready = m_axi_bready;
            edge_pre_cycle = wb_cycle;
        end
    end

    always @(posedge clk) begin
        if (rst_n && mode == 0)
            wb_cycle = wb_cycle + 1;
        if (!rst_n) begin
            held_aw = 0;
            held_w = 0;
        end else begin
            posedge_count = posedge_count + 1;
            if (posedge_count > 100000)
                $fatal(1, "writer-ready diagnostic watchdog expired state=%0d", dut.state);

            // Keep the original strict hold assertions from compute_write_support.vh.
            if (held_aw && (!m_axi_awvalid || {m_axi_awlen,m_axi_awaddr} !== {held_awlen,held_awaddr})) begin
                $display("AW_HOLD_FAIL mode=%0d phase=%0d held_cycle=%0d held_pre_ready=%0d held_post_ready=%0d held_pre_state=%0d held_post_state=%0d current_cycle=%0d current_pre_ready=%0d current_pre_state=%0d current_state=%0d current_awvalid=%0d current_awready=%0d held_addr=%08x current_addr=%08x",
                         mode,phase,held_aw_cycle,held_aw_pre_ready,held_aw_post_ready,held_aw_pre_state,
                         held_aw_post_state,wb_cycle,edge_pre_awready,edge_pre_state,dut.state,
                         m_axi_awvalid,m_axi_awready,held_awaddr,m_axi_awaddr);
                $fatal(1, "Actual output AW hold");
            end
            held_aw = m_axi_awvalid && !m_axi_awready;
            if (held_aw) begin
                held_awaddr = m_axi_awaddr;
                held_awlen = m_axi_awlen;
                held_aw_cycle = wb_cycle;
                held_aw_pre_ready = edge_pre_awready;
                held_aw_pre_state = edge_pre_state;
            end

            if (held_w && (!m_axi_wvalid || {m_axi_wid,m_axi_wdata,m_axi_wstrb,m_axi_wlast} !== held_w_payload))
                $fatal(1, "W payload changed while stalled");
            held_w = m_axi_wvalid && !m_axi_wready;
            if (held_w)
                held_w_payload = {m_axi_wid,m_axi_wdata,m_axi_wstrb,m_axi_wlast};

            if (in_valid && in_ready)
                input_words = input_words + 1;
            if (done)
                done_count = done_count + 1;
        end

        #1;
        if (rst_n) begin
            if (held_aw && held_aw_pre_state == ST_AW) begin
                held_aw_post_ready = m_axi_awready;
                held_aw_post_state = dut.state;
            end

            if (edge_pre_state == ST_AW && edge_pre_awvalid && dut.state == ST_W) begin
                if (slave_active || edge_pre_awid !== 6'd0 || edge_pre_awsize !== 3'd3 ||
                    edge_pre_awburst !== 2'b01 || edge_pre_awaddr[5:0] != 0 ||
                    (edge_pre_awlen != 4'd7 && edge_pre_awlen != 4'd15))
                    $fatal(1, "AW identity/geometry/ownership failure");
                burst_words = (edge_pre_awlen + 1) / 8;
                burst_beats = edge_pre_awlen + 1;
                if (edge_pre_awaddr !== BASE + aw_words_total * 64 ||
                    aw_words_total + burst_words > WORDS ||
                    ((edge_pre_awaddr[11:0]) + (burst_beats * 8)) > 4096 ||
                    (burst_words != ((WORDS-aw_words_total < 2) ? WORDS-aw_words_total :
                                      ((4096-edge_pre_awaddr[11:0])/64 < 2 ?
                                       (4096-edge_pre_awaddr[11:0])/64 : 2))))
                    $fatal(1, "AW order, byte count, burst split or 4KiB boundary failure");
                burst_word_base = aw_words_total;
                aw_words_total = aw_words_total + burst_words;
                burst_beat = 0;
                slave_active = 1;
                accepted_aw = accepted_aw + 1;
                if (!edge_pre_awready && m_axi_awready && dut.state == ST_W) begin
                    aw_edge_races = aw_edge_races + 1;
                    $display("AW_EDGE_RACE phase=%0d pre_cycle=%0d post_cycle=%0d pre_ready=0 post_ready=1 state=%0d->%0d addr=%08x len=%0d",
                             phase,edge_pre_cycle,wb_cycle,edge_pre_state,dut.state,edge_pre_awaddr,edge_pre_awlen);
                end
                $display("EDGE_TRACE mode=%0d phase=%0d cycle_pre=%0d cycle_post=%0d state_pre=%0d state_post=%0d awvalid_pre=%0d awready_pre=%0d awready_post=%0d addr=%08x len=%0d",
                         mode,phase,edge_pre_cycle,wb_cycle,edge_pre_state,dut.state,
                         edge_pre_awvalid,edge_pre_awready,m_axi_awready,edge_pre_awaddr,edge_pre_awlen);
            end

            if (edge_pre_state == ST_W && edge_pre_wvalid &&
                (dut.state != ST_W || dut.write_beat_select != edge_pre_wbeat ||
                 dut.write_word_select != edge_pre_wword)) begin
                if (!slave_active || edge_pre_wid !== 6'd0 || edge_pre_wstrb !== 8'hff ||
                    edge_pre_wlast !== (burst_beat == burst_beats - 1))
                    $fatal(1, "W before AW, wrong ID/strobe, or WLAST mismatch");
                expected_word = burst_word_base + (burst_beat / 8);
                if (expected_word < 0 || expected_word >= WORDS)
                    $fatal(1, "W payload outside configured word sequence");
                expected_word_data = make_word(expected_word);
                if (edge_pre_wdata !== expected_word_data[(burst_beat % 8)*64 +: 64])
                    $fatal(1, "W payload mismatch word=%0d beat=%0d",expected_word,burst_beat);
                accepted_w = accepted_w + 1;
                if (!edge_pre_wready) begin
                    w_edge_races = w_edge_races + 1;
                    $display("W_EDGE_RACE phase=%0d pre_cycle=%0d post_cycle=%0d state=%0d->%0d beat=%0d",
                             phase,edge_pre_cycle,wb_cycle,edge_pre_state,dut.state,burst_beat);
                end
                if (edge_pre_wlast) begin
                    if (burst_beat != burst_beats - 1)
                        $fatal(1, "WLAST arrived at wrong beat");
                    written_words_total = written_words_total + burst_words;
                    slave_active = 0;
                    b_pending = 1;
                    b_delay = 3;
                end
                burst_beat = burst_beat + 1;
            end

            if (edge_pre_state == ST_B && edge_pre_bvalid && edge_pre_bready && dut.state != ST_B) begin
                accepted_b = accepted_b + 1;
                b_clear = 1;
            end

            if (edge_pre_state == ST_AW || edge_pre_state == ST_W || edge_pre_state == ST_B)
                $display("EDGE_STATE phase=%0d cycle=%0d state_pre=%0d state_post=%0d awready_pre=%0d awready_post=%0d wready_pre=%0d wready_post=%0d",
                         phase,edge_pre_cycle,edge_pre_state,dut.state,edge_pre_awready,m_axi_awready,
                         edge_pre_wready,m_axi_wready);
        end
    end

    integer i;
    reg [8*16-1:0] mode_name;
    initial begin
        if (!$value$plusargs("mode=%d", mode) || (mode != 0 && mode != 1))
            $fatal(1, "Use +mode=0 (posedge READY update) or +mode=1 (negedge READY update)");
        if (!$value$plusargs("phase=%d", phase) || phase < 0 || phase > 6)
            $fatal(1, "Use +phase=0..6");
        mode_name = mode == 0 ? "unstable" : "stable";
        #12;
        rst_n = 1;
        repeat (phase) @(negedge clk);
        @(negedge clk);
        cmd_epoch = EPOCH;
        cmd_address = BASE;
        cmd_word_count = WORDS;
        cmd_valid = 1;
        do @(posedge clk); while (!cmd_ready);
        @(negedge clk);
        cmd_valid = 0;

        for (i = 0; i < WORDS; i = i + 1) begin
            @(negedge clk);
            in_epoch = EPOCH;
            in_index = i[12:0];
            in_data = make_word(i);
            in_last = (i == WORDS - 1);
            in_valid = 1;
            do @(posedge clk); while (!in_ready);
        end
        @(negedge clk);
        in_valid = 0;
        in_last = 0;

        wait(done_count == 1);
        repeat (3) @(negedge clk);
        if (fault || busy || fault_code != 0 || input_words != WORDS ||
            accepted_aw != 33 || aw_words_total != WORDS || accepted_w != 520 ||
            written_words_total != WORDS || accepted_b != 33 || done_count != 1 ||
            aw_hold_count == 0 || w_hold_count == 0 || slave_active || b_pending || m_axi_bvalid)
            $fatal(1, "writer READY-edge replay coverage failure mode=%0d phase=%0d input=%0d aw=%0d words=%0d w=%0d b=%0d done=%0d awhold=%0d whold=%0d",
                   mode,phase,input_words,accepted_aw,aw_words_total,accepted_w,accepted_b,done_count,
                   aw_hold_count,w_hold_count);
        $display("WRITER_READY_EDGE_PASS mode=%0d mode_name=%0s phase=%0d words=%0d aw=%0d w=%0d b=%0d done=%0d aw_hold=%0d w_hold=%0d aw_edge_races=%0d w_edge_races=%0d",
                 mode,mode_name,phase,input_words,accepted_aw,accepted_w,accepted_b,done_count,
                 aw_hold_count,w_hold_count,aw_edge_races,w_edge_races);
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1, "writer READY-edge testbench watchdog expired");
    end
endmodule
`default_nettype wire
