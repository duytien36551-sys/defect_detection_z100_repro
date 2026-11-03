`timescale 1ns/1ps
`default_nettype none

// Integration-only harness: the commit barrier below is caller policy, not a
// production ABI. The independent byte array is shared by two AXI3 ports.
module tb_z100_native_transport_loopback;
    localparam [31:0] DDR_BASE = 32'h1000_0000;
    localparam integer MEM_BYTES = 1_048_576;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;

    reg w_cmd_valid = 1'b0;
    wire w_cmd_ready;
    reg [31:0] w_cmd_epoch = 0, w_cmd_address = 0;
    reg [13:0] w_cmd_word_count = 0;
    reg w_in_valid = 1'b0;
    wire w_in_ready;
    reg [31:0] w_in_epoch = 0;
    reg [12:0] w_in_index = 0;
    reg [511:0] w_in_data = 0;
    reg w_in_last = 0;
    reg w_cancel = 1'b0, w_timeout = 1'b0, w_clear_fault = 1'b0;
    wire w_busy, w_done, w_fault;
    wire [3:0] w_fault_code;

    wire [5:0] w_awid;
    wire [31:0] w_awaddr;
    wire [3:0] w_awlen;
    wire [2:0] w_awsize;
    wire [1:0] w_awburst;
    wire w_awvalid;
    reg w_awready = 1'b0;
    wire [5:0] w_wid;
    wire [63:0] w_wdata;
    wire [7:0] w_wstrb;
    wire w_wlast, w_wvalid;
    reg w_wready = 1'b0;
    reg [5:0] w_bid = 0;
    reg [1:0] w_bresp = 0;
    reg w_bvalid = 1'b0;
    wire w_bready;

    reg r_host_cmd_valid = 1'b0;
    wire r_host_cmd_ready;
    reg [31:0] r_host_cmd_epoch = 0, r_host_cmd_address = 0;
    reg [13:0] r_host_cmd_word_count = 0;
    reg r_cancel = 1'b0, r_timeout = 1'b0, r_clear_fault = 1'b0;
    wire r_busy, r_done, r_fault;
    wire [3:0] r_fault_code;
    wire r_out_valid;
    reg r_out_ready = 1'b0;
    wire [31:0] r_out_epoch;
    wire [12:0] r_out_index;
    wire [511:0] r_out_data;
    wire r_out_last;
    wire [5:0] r_arid;
    wire [31:0] r_araddr;
    wire [3:0] r_arlen;
    wire [2:0] r_arsize;
    wire [1:0] r_arburst;
    wire r_arvalid;
    reg r_arready = 1'b0;
    reg [5:0] r_rid = 0;
    reg [63:0] r_rdata = 0;
    reg [1:0] r_rresp = 0;
    reg r_rlast = 0, r_rvalid = 1'b0;
    wire r_rready;

    z100_native_axi64_writer writer (
        .clk(clk), .rst_n(rst_n),
        .cmd_valid(w_cmd_valid), .cmd_ready(w_cmd_ready),
        .cmd_epoch(w_cmd_epoch), .cmd_address(w_cmd_address),
        .cmd_word_count(w_cmd_word_count),
        .in_valid(w_in_valid), .in_ready(w_in_ready), .in_epoch(w_in_epoch),
        .in_index(w_in_index), .in_data(w_in_data), .in_last(w_in_last),
        .cancel(w_cancel), .timeout(w_timeout), .clear_fault(w_clear_fault),
        .busy(w_busy), .done(w_done), .fault(w_fault), .fault_code(w_fault_code),
        .m_axi_awid(w_awid), .m_axi_awaddr(w_awaddr), .m_axi_awlen(w_awlen),
        .m_axi_awsize(w_awsize), .m_axi_awburst(w_awburst),
        .m_axi_awvalid(w_awvalid), .m_axi_awready(w_awready),
        .m_axi_wid(w_wid), .m_axi_wdata(w_wdata), .m_axi_wstrb(w_wstrb),
        .m_axi_wlast(w_wlast), .m_axi_wvalid(w_wvalid), .m_axi_wready(w_wready),
        .m_axi_bid(w_bid), .m_axi_bresp(w_bresp), .m_axi_bvalid(w_bvalid),
        .m_axi_bready(w_bready)
    );

    // A caller-side commit gate: the reader receives no command until a full,
    // successful writer completion has been observed for the requested range.
    reg a_committed = 1'b0, b_committed = 1'b0;
    reg c_committed = 1'b0, small_committed = 1'b0;
    reg [31:0] a_epoch = 0, b_epoch = 0, c_epoch = 0, small_epoch = 0;
    reg [31:0] small_base = 0;
    reg [13:0] a_words = 0, b_words = 0, c_words = 0, small_words = 0;
    wire r_commit_ok;
    wire r_core_cmd_valid = r_host_cmd_valid && r_commit_ok;
    wire r_core_cmd_ready;
    assign r_host_cmd_ready = r_commit_ok && r_core_cmd_ready;

    function committed_range;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        reg [32:0] request_end;
        reg [32:0] region_end;
        begin
            request_end = {1'b0,address} + {13'd0,words,6'd0};
            region_end = 0;
            committed_range = 1'b0;
            if (a_committed && epoch == a_epoch && address >= DDR_BASE &&
                request_end <= {1'b0,DDR_BASE} + {13'd0,a_words,6'd0}) begin
                committed_range = 1'b1;
            end
            if (b_committed && epoch == b_epoch && address >= 32'h100a_0000 &&
                request_end <= {1'b0,32'h100a_0000} + {13'd0,b_words,6'd0}) begin
                committed_range = 1'b1;
            end
            if (c_committed && epoch == c_epoch && address >= 32'h100b_0000 &&
                request_end <= {1'b0,32'h100b_0000} + {13'd0,c_words,6'd0}) begin
                committed_range = 1'b1;
            end
            if (small_committed && epoch == small_epoch && address == small_base &&
                request_end == {1'b0,small_base} + {13'd0,small_words,6'd0}) begin
                committed_range = 1'b1;
            end
        end
    endfunction
    assign r_commit_ok = committed_range(r_host_cmd_address, r_host_cmd_word_count,
                                         r_host_cmd_epoch);

    z100_native_axi64_reader reader (
        .clk(clk), .rst_n(rst_n),
        .cmd_valid(r_core_cmd_valid), .cmd_ready(r_core_cmd_ready),
        .cmd_epoch(r_host_cmd_epoch), .cmd_address(r_host_cmd_address),
        .cmd_word_count(r_host_cmd_word_count),
        .cancel(r_cancel), .timeout(r_timeout), .clear_fault(r_clear_fault),
        .busy(r_busy), .done(r_done), .fault(r_fault), .fault_code(r_fault_code),
        .out_valid(r_out_valid), .out_ready(r_out_ready), .out_epoch(r_out_epoch),
        .out_index(r_out_index), .out_data(r_out_data), .out_last(r_out_last),
        .m_axi_arid(r_arid), .m_axi_araddr(r_araddr), .m_axi_arlen(r_arlen),
        .m_axi_arsize(r_arsize), .m_axi_arburst(r_arburst),
        .m_axi_arvalid(r_arvalid), .m_axi_arready(r_arready),
        .m_axi_rid(r_rid), .m_axi_rdata(r_rdata), .m_axi_rresp(r_rresp),
        .m_axi_rlast(r_rlast), .m_axi_rvalid(r_rvalid), .m_axi_rready(r_rready)
    );

    reg [7:0] ddr_bytes [0:MEM_BYTES-1];
    reg [31:0] random_state = 32'h5a17_c3e9;
    reg allow_aw = 1'b1, allow_w = 1'b1, allow_b = 1'b1;
    reg allow_ar = 1'b1, allow_r = 1'b1, allow_out = 1'b1;
    reg force_w_run = 1'b0, force_r_run = 1'b0, force_out_run = 1'b0;
    reg next_bad_bid = 1'b0;
    reg inject_rresp_next = 1'b0;

    reg wr_active = 1'b0, wr_b_pending = 1'b0;
    integer wr_b_delay = 0;
    integer wr_addr = 0, wr_burst_beats = 0, wr_beat_index = 0;
    integer wr_burst_words = 0;
    reg [5:0] wr_bid_next = 0;
    reg [1:0] wr_bresp_next = 0;
    integer wr_score_base = 0, wr_score_count = 0, wr_score_epoch = 0;
    integer wr_input_words = 0, wr_aw_words = 0, wr_written_words = 0;
    integer total_writer_input_words = 0;

    reg rd_active = 1'b0, rd_inject_this_burst = 1'b0, rd_drain_tracking = 1'b0;
    integer rd_addr = 0, rd_burst_beats = 0, rd_beat_index = 0;
    integer rd_b_delay = 0;
    integer rd_score_base = 0, rd_score_count = 0, rd_score_epoch = 0;
    integer rd_ar_words = 0, rd_output_words = 0;
    reg rd_expect_error = 1'b0, rd_command_commit_snapshot = 1'b0;

    integer w_aw_count = 0, w_w_count = 0, w_b_count = 0;
    integer r_ar_count = 0, r_r_count = 0;
    integer w_len16_count = 0, r_len16_count = 0;
    integer w_done_count = 0, r_done_count = 0;
    integer writer_fault_count = 0, reader_fault_count = 0;
    reg last_writer_success = 1'b0;
    reg [31:0] last_writer_address = 0, last_writer_epoch = 0;
    reg [13:0] last_writer_words = 0;
    integer blocked_read_probes = 0, forbidden_ar_count = 0;
    integer concurrent_busy_cycles = 0;
    integer aw_hold_checks = 0, w_hold_checks = 0;
    integer ar_hold_checks = 0, r_hold_checks = 0, out_hold_checks = 0;
    integer input_hold_checks = 0;
    integer max_w_streak = 0, current_w_streak = 0;
    integer max_r_streak = 0, current_r_streak = 0;
    integer rresp_drain_beats = 0;
    integer memory_write_bytes = 0, golden_output_bytes = 0;
    integer cycle_count = 0;
    reg held_aw = 0, held_w = 0, held_ar = 0, held_r = 0, held_out = 0, held_in = 0;
    reg [31:0] held_awaddr = 0, held_araddr = 0;
    reg [3:0] held_awlen = 0, held_arlen = 0;
    reg [63:0] held_wdata = 0, held_rdata = 0;
    reg [7:0] held_wstrb = 0;
    reg held_wlast = 0, held_rlast = 0;
    reg [511:0] held_outdata = 0;
    reg [31:0] held_outepoch = 0;
    reg [12:0] held_outindex = 0;
    reg held_outlast = 0;
    reg [511:0] held_indata = 0;
    reg [31:0] held_in_epoch = 0;
    reg [12:0] held_in_index = 0;
    reg held_in_last = 0;

    integer expected_burst_words, page_words, word_index, byte_offset;
    integer mem_offset, lane, temp_word;
    reg [511:0] check_word;
    integer i;

    function [7:0] input_byte;
        input [12:0] word_index;
        input [31:0] epoch;
        input integer byte_index;
        integer value;
        begin
            value = word_index * 31 + byte_index * 17 + epoch * 9 + (word_index >> 4);
            input_byte = value[7:0];
        end
    endfunction

    function [7:0] golden_byte;
        input [12:0] word_index;
        input [31:0] epoch;
        input integer byte_index;
        integer value;
        begin
            value = byte_index * 17 + epoch * 9 + word_index * 31 +
                    ((word_index & 13'h1ff0) >> 4);
            golden_byte = value[7:0];
        end
    endfunction

    function [511:0] make_input_word;
        input [12:0] word_index;
        input [31:0] epoch;
        integer b;
        begin
            for (b=0; b<64; b=b+1)
                make_input_word[b*8+:8] = input_byte(word_index, epoch, b);
        end
    endfunction

    function [511:0] make_golden_word;
        input [12:0] word_index;
        input [31:0] epoch;
        integer b;
        begin
            for (b=0; b<64; b=b+1)
                make_golden_word[b*8+:8] = golden_byte(word_index, epoch, b);
        end
    endfunction

    function [63:0] memory_read64;
        input integer address;
        integer offset;
        integer b;
        begin
            offset = address - DDR_BASE;
            for (b=0; b<8; b=b+1)
                memory_read64[b*8+:8] = ddr_bytes[offset+b];
        end
    endfunction

    always @(negedge clk) begin
        random_state = {random_state[30:0], random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        w_awready = rst_n && allow_aw && !wr_active && (random_state[1:0] != 0);
        w_wready = rst_n && allow_w && wr_active && !wr_b_pending &&
                   (force_w_run || random_state[5:2] != 0);
        r_arready = rst_n && allow_ar && !rd_active && (random_state[7:6] != 0);
        r_out_ready = rst_n && allow_out && (force_out_run || random_state[10:8] != 0);
        if (rst_n && !w_bvalid && wr_b_pending && allow_b) begin
            if (wr_b_delay > 0)
                wr_b_delay = wr_b_delay - 1;
            else if (random_state[13:11] != 0) begin
                w_bvalid = 1'b1;
                w_bid = wr_bid_next;
                w_bresp = wr_bresp_next;
            end
        end
        if (rst_n && !r_rvalid && rd_active && allow_r) begin
            if (force_r_run || rd_b_delay == 0) begin
                mem_offset = rd_addr - DDR_BASE + rd_beat_index * 8;
                if (mem_offset < 0 || mem_offset + 7 >= MEM_BYTES)
                    $fatal(1, "Read slave address outside shared memory");
                r_rdata = memory_read64(rd_addr + rd_beat_index*8);
                r_rid = 0;
                r_rresp = (rd_inject_this_burst && rd_beat_index == 0) ? 2'b10 : 2'b00;
                r_rlast = (rd_beat_index == rd_burst_beats-1);
                r_rvalid = 1'b1;
            end else begin
                rd_b_delay = rd_b_delay - 1;
            end
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            wr_active = 1'b0; wr_b_pending = 1'b0; w_bvalid <= 1'b0;
            rd_active = 1'b0; r_rvalid <= 1'b0;
            held_aw = 0; held_w = 0; held_ar = 0; held_r = 0; held_out = 0; held_in = 0;
            current_w_streak = 0; current_r_streak = 0;
        end else begin
            cycle_count = cycle_count + 1;
            if (cycle_count > 5_000_000)
                $fatal(1, "Global watchdog writer busy=%0d fault=%0d reader busy=%0d fault=%0d",
                       w_busy,w_fault,r_busy,r_fault);
            if (w_busy && r_busy)
                concurrent_busy_cycles = concurrent_busy_cycles + 1;

            if (held_aw) begin
                if (!w_awvalid || w_awaddr !== held_awaddr || w_awlen !== held_awlen)
                    $fatal(1, "Writer AW changed under backpressure");
                aw_hold_checks = aw_hold_checks + 1;
            end
            held_aw = w_awvalid && !w_awready;
            if (held_aw) begin held_awaddr=w_awaddr; held_awlen=w_awlen; end

            if (held_w) begin
                if (!w_wvalid || w_wdata !== held_wdata || w_wstrb !== held_wstrb ||
                    w_wlast !== held_wlast || w_wid !== 0)
                    $fatal(1, "Writer W changed under backpressure");
                w_hold_checks = w_hold_checks + 1;
            end
            held_w = w_wvalid && !w_wready;
            if (held_w) begin held_wdata=w_wdata; held_wstrb=w_wstrb; held_wlast=w_wlast; end

            if (held_ar) begin
                if (!r_arvalid || r_araddr !== held_araddr || r_arlen !== held_arlen)
                    $fatal(1, "Reader AR changed under backpressure");
                ar_hold_checks = ar_hold_checks + 1;
            end
            held_ar = r_arvalid && !r_arready;
            if (held_ar) begin held_araddr=r_araddr; held_arlen=r_arlen; end

            if (held_r) begin
                if (!r_rvalid || r_rdata !== held_rdata || r_rlast !== held_rlast || r_rid !== 0)
                    $fatal(1, "Memory R response changed under backpressure");
                r_hold_checks = r_hold_checks + 1;
            end
            held_r = r_rvalid && !r_rready;
            if (held_r) begin held_rdata=r_rdata; held_rlast=r_rlast; end

            if (held_out) begin
                if (!r_out_valid || r_out_data !== held_outdata || r_out_epoch !== held_outepoch ||
                    r_out_index !== held_outindex || r_out_last !== held_outlast)
                    $fatal(1, "Reader output changed under backpressure");
                out_hold_checks = out_hold_checks + 1;
            end
            held_out = r_out_valid && !r_out_ready;
            if (held_out) begin
                held_outdata=r_out_data; held_outepoch=r_out_epoch;
                held_outindex=r_out_index; held_outlast=r_out_last;
            end

            if (held_in) begin
                if (!w_in_valid || w_in_data !== held_indata || w_in_epoch !== held_in_epoch ||
                    w_in_index !== held_in_index || w_in_last !== held_in_last)
                    $fatal(1, "Private writer input changed under backpressure");
                input_hold_checks = input_hold_checks + 1;
            end
            held_in = w_in_valid && !w_in_ready;
            if (held_in) begin
                held_indata=w_in_data; held_in_epoch=w_in_epoch;
                held_in_index=w_in_index; held_in_last=w_in_last;
            end

            if (w_in_valid && w_in_ready)
                begin
                    wr_input_words = wr_input_words + 1;
                    total_writer_input_words = total_writer_input_words + 1;
                end

            if (w_awvalid && w_awready) begin
                if (wr_active || w_awid !== 0 || w_awsize !== 3 || w_awburst !== 2'b01)
                    $fatal(1, "Writer AW identity/order failure");
                if (w_awaddr[5:0] != 0 || (w_awlen != 7 && w_awlen != 15))
                    $fatal(1, "Writer AW alignment/length failure");
                if ((w_awaddr[11:0] + (w_awlen+1)*8) > 4096)
                    $fatal(1, "Writer AW crosses 4KiB boundary");
                if (w_awaddr !== wr_score_base + wr_aw_words*64)
                    $fatal(1, "Writer AW order mismatch expected=%08x actual=%08x",
                           wr_score_base + wr_aw_words*64,w_awaddr);
                page_words = (4096 - (w_awaddr & 4095))/64;
                expected_burst_words = 2;
                if (wr_score_count-wr_aw_words < expected_burst_words)
                    expected_burst_words = wr_score_count-wr_aw_words;
                if (page_words < expected_burst_words)
                    expected_burst_words = page_words;
                if ((w_awlen+1) != expected_burst_words*8)
                    $fatal(1, "Writer AWLEN expected=%0d actual=%0d",expected_burst_words*8-1,w_awlen);
                if (wr_input_words < wr_aw_words + expected_burst_words)
                    $fatal(1, "Writer advertised AW before full burst prebuffer");
                wr_aw_words = wr_aw_words + expected_burst_words;
                wr_active = 1'b1;
                wr_addr = w_awaddr;
                wr_burst_beats = w_awlen + 1;
                wr_burst_words = expected_burst_words;
                wr_beat_index = 0;
                w_aw_count = w_aw_count + 1;
                if (w_awlen == 15) w_len16_count = w_len16_count + 1;
            end

            if (w_wvalid && w_wready) begin
                if (!wr_active || w_wid !== 0 || w_wstrb !== 8'hff)
                    $fatal(1, "W beat before AW or invalid WID/WSTRB");
                if (w_wlast !== (wr_beat_index == wr_burst_beats-1))
                    $fatal(1, "Writer WLAST mismatch");
                word_index = (wr_addr - wr_score_base)/64 + wr_beat_index/8;
                if (word_index < 0 || word_index >= wr_score_count)
                    $fatal(1, "Writer W beat outside canonical sequential stream");
                check_word = make_input_word(word_index[12:0],wr_score_epoch[31:0]);
                if (w_wdata !== check_word[(wr_beat_index%8)*64+:64])
                    $fatal(1, "Writer data does not match independent canonical source word=%0d beat=%0d",
                           word_index,wr_beat_index);
                byte_offset = wr_addr - DDR_BASE + wr_beat_index*8;
                if (byte_offset < 0 || byte_offset+7 >= MEM_BYTES)
                    $fatal(1, "Write address outside shared memory");
                for (lane=0; lane<8; lane=lane+1) begin
                    ddr_bytes[byte_offset+lane] = w_wdata[lane*8+:8];
                    memory_write_bytes = memory_write_bytes + 1;
                end
                w_w_count = w_w_count + 1;
                current_w_streak = current_w_streak + 1;
                if (current_w_streak > max_w_streak) max_w_streak=current_w_streak;
                if (w_wlast) begin
                    wr_written_words = wr_written_words + wr_burst_words;
                wr_bid_next = next_bad_bid ? 6'd1 : 6'd0;
                next_bad_bid = 1'b0;
                    wr_b_pending = 1'b1;
                    wr_b_delay = 2;
                    wr_beat_index = 0;
                end else wr_beat_index = wr_beat_index + 1;
            end else current_w_streak = 0;

            if (w_bvalid && w_bready) begin
                w_b_count = w_b_count + 1;
                w_bvalid <= 1'b0;
                wr_b_pending = 1'b0;
                wr_active = 1'b0;
                wr_bid_next = 0;
                wr_bresp_next = 0;
            end

            if (r_arvalid && r_arready) begin
                if (!r_commit_ok) begin
                    forbidden_ar_count = forbidden_ar_count + 1;
                    $fatal(1, "AR was issued before committed writer range");
                end
                if (rd_active || r_arid !== 0 || r_arsize !== 3 || r_arburst !== 2'b01)
                    $fatal(1, "Reader AR identity/order failure");
                if (r_araddr[5:0] != 0 || (r_arlen != 7 && r_arlen != 15))
                    $fatal(1, "Reader AR alignment/length failure");
                if ((r_araddr[11:0] + (r_arlen+1)*8) > 4096)
                    $fatal(1, "Reader AR crosses 4KiB boundary");
                if (r_araddr !== rd_score_base + rd_ar_words*64)
                    $fatal(1, "Reader AR order mismatch expected=%08x actual=%08x",
                           rd_score_base+rd_ar_words*64,r_araddr);
                page_words = (4096 - (r_araddr & 4095))/64;
                expected_burst_words = 2;
                if (rd_score_count-rd_ar_words < expected_burst_words)
                    expected_burst_words = rd_score_count-rd_ar_words;
                if (page_words < expected_burst_words)
                    expected_burst_words = page_words;
                if ((r_arlen+1) != expected_burst_words*8)
                    $fatal(1, "Reader ARLEN expected=%0d actual=%0d",expected_burst_words*8-1,r_arlen);
                rd_ar_words = rd_ar_words + expected_burst_words;
                rd_active = 1'b1;
                rd_addr = r_araddr;
                rd_burst_beats = r_arlen+1;
                rd_beat_index = 0;
                rd_b_delay = 2;
                rd_inject_this_burst = inject_rresp_next;
                inject_rresp_next = 1'b0;
                rd_drain_tracking = 1'b0;
                rd_command_commit_snapshot = r_commit_ok;
                r_ar_count = r_ar_count + 1;
                if (r_arlen == 15) r_len16_count = r_len16_count + 1;
            end

            if (r_rvalid && r_rready) begin
                if (!rd_active || r_rid !== 0 || r_rlast !== (rd_beat_index == rd_burst_beats-1))
                    $fatal(1, "Read slave R beat order/ID/RLAST error");
                if (r_rresp != 0 && !(rd_inject_this_burst && rd_beat_index == 0))
                    $fatal(1, "Unexpected read response error");
                if (rd_inject_this_burst && rd_beat_index == 0 && r_rresp != 0)
                    rd_drain_tracking = 1'b1;
                else if (rd_drain_tracking)
                    rresp_drain_beats = rresp_drain_beats + 1;
                r_r_count = r_r_count + 1;
                current_r_streak = current_r_streak + 1;
                if (current_r_streak > max_r_streak) max_r_streak=current_r_streak;
                if (r_rlast) begin
                    rd_active = 1'b0;
                    rd_inject_this_burst = 1'b0;
                    rd_drain_tracking = 1'b0;
                    r_rvalid <= 1'b0;
                end else begin
                    rd_beat_index = rd_beat_index + 1;
                    r_rvalid <= 1'b0;
                    rd_b_delay = random_state[15:14];
                end
            end else current_r_streak = 0;

            if (r_out_valid) begin
                if (!rd_command_commit_snapshot)
                    $fatal(1, "Reader exposed an epoch without successful writer commit");
                if (rd_expect_error)
                    $fatal(1, "Reader exposed data for RRESP-faulted request");
                if (r_out_epoch !== rd_score_epoch[31:0] || r_out_index !== rd_output_words[12:0] ||
                    r_out_last !== (rd_output_words == rd_score_count-1))
                    $fatal(1, "Reader output metadata mismatch output=%0d",rd_output_words);
                check_word = make_golden_word(rd_output_words[12:0],rd_score_epoch[31:0]);
                if (r_out_data !== check_word)
                    $fatal(1, "Reader byte stream mismatch output word=%0d",rd_output_words);
                if (r_out_valid && r_out_ready) begin
                    rd_output_words = rd_output_words + 1;
                    golden_output_bytes = golden_output_bytes + 64;
                end
            end

            if (w_done) w_done_count = w_done_count + 1;
            if (r_done) r_done_count = r_done_count + 1;
        end
    end

    task writer_start;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        integer wait_cycles;
        reg accepted;
        begin
            wr_score_base = address;
            wr_score_count = words;
            wr_score_epoch = epoch;
            wr_input_words = 0;
            wr_aw_words = 0;
            wr_written_words = 0;
            last_writer_success = 1'b0;
            @(negedge clk);
            w_cmd_address=address; w_cmd_word_count=words; w_cmd_epoch=epoch; w_cmd_valid=1'b1;
            wait_cycles=0; accepted=0;
            while (!accepted) begin
                @(posedge clk);
                if (w_cmd_ready) accepted=1;
                wait_cycles=wait_cycles+1;
                if (wait_cycles>1000) $fatal(1,"Writer command handshake timeout");
            end
            @(negedge clk);
            w_cmd_valid=1'b0;
            w_cmd_address=32'hdead_c0c0; w_cmd_word_count=14'd8193; w_cmd_epoch=0;
        end
    endtask

    // Drive one sequential stream without inserting a bubble after each word.
    // At a two-word prebuffer boundary the next private word remains stable
    // through AW/W/B backpressure until the adapter asks for the next fill.
    task writer_stream_from;
        input integer first_index;
        input integer total_words;
        input [31:0] epoch;
        integer k;
        integer wait_cycles;
        reg accepted;
        begin
            for (k=first_index;k<total_words;k=k+1) begin
                @(negedge clk);
                w_in_index=k[12:0]; w_in_epoch=epoch;
                w_in_data=make_input_word(k[12:0],epoch);
                w_in_last=(k==total_words-1); w_in_valid=1'b1;
                wait_cycles=0; accepted=0;
                while (!accepted) begin
                    @(posedge clk);
                    if (w_in_ready) accepted=1;
                    wait_cycles=wait_cycles+1;
                    if (wait_cycles>500000)
                        $fatal(1,"Writer stream input stall timed out idx=%0d",k);
                end
            end
            @(negedge clk); w_in_valid=1'b0;
        end
    endtask

    task writer_push;
        input integer index;
        input [31:0] epoch;
        input last_value;
        integer wait_cycles;
        reg accepted;
        begin
            @(negedge clk);
            w_in_index=index[12:0]; w_in_epoch=epoch;
            w_in_data=make_input_word(index[12:0],epoch);
            w_in_last=last_value; w_in_valid=1'b1;
            wait_cycles=0; accepted=0;
            while (!accepted) begin
                @(posedge clk);
                if (w_in_ready) accepted=1;
                wait_cycles=wait_cycles+1;
                if (wait_cycles>500000) $fatal(1,"Writer input stall timed out idx=%0d",index);
            end
            @(negedge clk); w_in_valid=1'b0;
        end
    endtask

    task wait_writer_done;
        input integer baseline;
        integer wait_cycles;
        begin
            wait_cycles=0;
            while (w_done_count==baseline) begin
                @(posedge clk); wait_cycles=wait_cycles+1;
                if (wait_cycles>1_000_000) $fatal(1,"Writer done timeout fault=%0d code=%0d",w_fault,w_fault_code);
            end
            if (w_fault || w_busy) $fatal(1,"Writer reported done with fault/busy");
        end
    endtask

    task writer_good;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        integer baseline;
        begin
            baseline=w_done_count;
            writer_start(address,words,epoch);
            writer_stream_from(0,words,epoch);
            wait_writer_done(baseline);
            if (wr_written_words != words)
                $fatal(1,"Writer accepted W data for %0d/%0d words",wr_written_words,words);
            last_writer_address=address; last_writer_words=words; last_writer_epoch=epoch;
            last_writer_success=1'b1;
        end
    endtask

    task writer_fault_done;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        input [3:0] expected_code;
        integer baseline;
        integer baseline_b;
        integer k;
        integer wait_cycles;
        begin
            baseline=w_done_count; baseline_b=w_b_count;
            writer_start(address,words,epoch);
            writer_stream_from(0,words,epoch);
            wait_cycles=0;
            while (w_busy) begin
                @(posedge clk); wait_cycles=wait_cycles+1;
                if (wait_cycles>100000) $fatal(1,"Writer fault response did not drain");
            end
            if (!w_fault || w_fault_code!==expected_code || w_done_count!=baseline || w_b_count!=baseline_b+1)
                $fatal(1,"Expected writer fault %0d after consumed B code=%0d",expected_code,w_fault_code);
            writer_fault_count=writer_fault_count+1;
        end
    endtask

    task writer_cancel_partial_b;
        input [31:0] address;
        input [31:0] epoch;
        integer baseline_b;
        integer baseline_done;
        integer wait_cycles;
        begin
            baseline_b=w_b_count; baseline_done=w_done_count;
            writer_start(address,14'd3,epoch);
            writer_push(0,epoch,1'b0);
            writer_push(1,epoch,1'b0);
            wait_cycles=0;
            while (w_b_count==baseline_b) begin
                @(posedge clk); wait_cycles=wait_cycles+1;
                if (wait_cycles>10000) $fatal(1,"First partial-region burst did not finish");
            end
            @(negedge clk); w_cancel=1'b1;
            @(posedge clk);
            @(negedge clk); w_cancel=1'b0;
            wait_cycles=0;
            while (w_busy) begin
                @(posedge clk); wait_cycles=wait_cycles+1;
                if (wait_cycles>100) $fatal(1,"Prefill cancel failed to stop writer");
            end
            if (!w_fault || w_fault_code!==4'd8 || w_done_count!=baseline_done ||
                w_b_count!=baseline_b+1 || wr_input_words!=2 || wr_written_words!=2)
                $fatal(1,"Partial write abort did not remain uncommitted");
            writer_fault_count=writer_fault_count+1;
        end
    endtask

    task writer_clear;
        begin
            if (w_busy) $fatal(1,"Cannot clear writer while transaction is outstanding");
            @(negedge clk); w_clear_fault=1'b1;
            @(posedge clk);
            @(negedge clk); w_clear_fault=1'b0;
            @(posedge clk);
            if (w_fault || !w_cmd_ready) $fatal(1,"Writer fault clear failed");
        end
    endtask

    task set_region_commit;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        begin
            if (w_busy || w_fault || !last_writer_success ||
                address!=last_writer_address || words!=last_writer_words || epoch!=last_writer_epoch)
                $fatal(1,"Commit attempted before final good B and writer done");
            if (address==DDR_BASE) begin a_committed=1; a_words=words; a_epoch=epoch; end
            else if (address==32'h100a_0000) begin b_committed=1; b_words=words; b_epoch=epoch; end
            else if (address==32'h100b_0000) begin c_committed=1; c_words=words; c_epoch=epoch; end
            else begin small_committed=1; small_base=address; small_words=words; small_epoch=epoch; end
            last_writer_success=1'b0;
        end
    endtask

    task reader_start;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        input expect_error;
        integer wait_cycles;
        reg accepted;
        begin
            rd_score_base=address; rd_score_count=words; rd_score_epoch=epoch;
            rd_output_words=0; rd_ar_words=0; rd_expect_error=expect_error;
            rd_command_commit_snapshot=0;
            @(negedge clk);
            r_host_cmd_address=address; r_host_cmd_word_count=words;
            r_host_cmd_epoch=epoch; r_host_cmd_valid=1'b1;
            wait_cycles=0; accepted=0;
            while (!accepted) begin
                @(posedge clk);
                if (r_host_cmd_ready) accepted=1;
                wait_cycles=wait_cycles+1;
                if (wait_cycles>10000) $fatal(1,"Reader command blocked despite committed range %08x",address);
            end
            rd_command_commit_snapshot=1;
            @(negedge clk);
            r_host_cmd_valid=1'b0;
        end
    endtask

    task reader_good;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        input force_first16;
        integer baseline_done;
        integer baseline_r;
        integer wait_cycles;
        begin
            baseline_done=r_done_count; baseline_r=r_r_count;
            if (force_first16) begin force_r_run=1; force_out_run=1; end
            reader_start(address,words,epoch,1'b0);
            wait_cycles=0;
            while (rd_output_words < words) begin
                @(posedge clk);
                wait_cycles=wait_cycles+1;
                if (force_first16 && r_r_count>=baseline_r+16) begin
                    force_r_run=0; force_out_run=0;
                end
                if (wait_cycles>1_000_000) $fatal(1,"Reader output timeout addr=%08x",address);
            end
            while (r_done_count==baseline_done) begin
                @(posedge clk);
                if (wait_cycles>1_000_000) $fatal(1,"Reader done timeout addr=%08x",address);
                wait_cycles=wait_cycles+1;
            end
            if (r_fault || r_busy || rd_ar_words!=words || rd_output_words!=words)
                $fatal(1,"Reader successful loopback failed words=%0d arwords=%0d",rd_output_words,rd_ar_words);
        end
    endtask

    task reader_rresp_fault;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        integer baseline_faults;
        integer baseline_ar;
        integer baseline_r;
        integer baseline_done;
        integer wait_cycles;
        begin
            baseline_faults=reader_fault_count; baseline_ar=r_ar_count;
            baseline_r=r_r_count; baseline_done=r_done_count;
            rd_expect_error=1'b1;
            inject_rresp_next=1'b1;
            reader_start(address,words,epoch,1'b1);
            wait_cycles=0;
            while (r_busy) begin
                @(posedge clk); wait_cycles=wait_cycles+1;
                if (wait_cycles>10000) $fatal(1,"RRESP error did not drain to RLAST");
            end
            if (!r_fault || r_fault_code!==4'd3 || r_done_count!=baseline_done ||
                rd_output_words!=0 || r_ar_count!=baseline_ar+1 ||
                r_r_count!=baseline_r+16 || rresp_drain_beats!=15)
                $fatal(1,"RRESP fault failed drain/output suppression code=%0d R=%0d drain=%0d",
                       r_fault_code,r_r_count-baseline_r,rresp_drain_beats);
            reader_fault_count=reader_fault_count+1;
        end
    endtask

    task reader_clear;
        begin
            if (r_busy) $fatal(1,"Cannot clear reader with R transaction outstanding");
            @(negedge clk); r_clear_fault=1'b1;
            @(posedge clk);
            @(negedge clk); r_clear_fault=1'b0;
            @(posedge clk);
            if (r_fault || !r_core_cmd_ready) $fatal(1,"Reader fault clear failed");
        end
    endtask

    task probe_uncommitted_read;
        input [31:0] address;
        input [13:0] words;
        input [31:0] epoch;
        integer baseline_ar;
        integer k;
        begin
            if (committed_range(address,words,epoch))
                $fatal(1,"Negative commit-barrier probe points at committed region");
            baseline_ar=r_ar_count;
            @(negedge clk);
            r_host_cmd_address=address; r_host_cmd_word_count=words;
            r_host_cmd_epoch=epoch; r_host_cmd_valid=1'b1;
            for (k=0;k<8;k=k+1) begin
                @(posedge clk);
                if (r_host_cmd_ready || r_busy || r_arvalid)
                    $fatal(1,"Reader accepted uncommitted range %08x",address);
                blocked_read_probes=blocked_read_probes+1;
            end
            @(negedge clk); r_host_cmd_valid=1'b0;
            if (r_ar_count!=baseline_ar)
                $fatal(1,"Uncommitted read probe emitted AR");
        end
    endtask

    integer baseline_done, baseline_b, baseline_ar, baseline_r, baseline_w;
    integer k, b, word_idx, addr_idx;
    reg [31:0] test_bases [0:4];
    reg [13:0] test_words [0:4];

    initial begin
        for (i=0;i<MEM_BYTES;i=i+1) ddr_bytes[i]=0;
        repeat (5) @(posedge clk);
        if (w_cmd_ready || w_in_ready || w_awvalid || w_wvalid || w_bready ||
            r_core_cmd_ready || r_arvalid || r_rready || r_out_valid)
            $fatal(1,"Protocol ready/valid not held low during coordinated reset");
        @(negedge clk); rst_n=1'b1;
        repeat (2) @(posedge clk);

        // Full 512KiB canonical-order write. The commit record is withheld until
        // the component's done pulse, which itself follows the final good B.
        baseline_done=w_done_count; baseline_b=w_b_count;
        writer_start(DDR_BASE,14'd8192,32'h0000_00a1);
        writer_push(0,32'h0000_00a1,1'b0);
        writer_push(1,32'h0000_00a1,1'b0);
        force_w_run=1'b1;
        baseline_w=w_w_count;
        while (w_w_count<baseline_w+16) @(posedge clk);
        force_w_run=1'b0;
        writer_stream_from(2,8192,32'h0000_00a1);
        wait_writer_done(baseline_done);
        if (w_b_count!=baseline_b+4096 || wr_written_words!=8192 || wr_aw_words!=8192)
            $fatal(1,"Full writer did not complete all words and good B responses");
        last_writer_address=DDR_BASE; last_writer_words=14'd8192;
        last_writer_epoch=32'h0000_00a1; last_writer_success=1'b1;
        set_region_commit(DDR_BASE,14'd8192,32'h0000_00a1);
        // Read committed A while independently writing disjoint region B.
        fork
            begin
                b_committed=0;
                writer_good(32'h100a_0000,14'd65,32'h0000_00b1);
                set_region_commit(32'h100a_0000,14'd65,32'h0000_00b1);
            end
            begin
                reader_good(DDR_BASE,14'd8192,32'h0000_00a1,1'b1);
            end
        join
        if (concurrent_busy_cycles==0)
            $fatal(1,"No simultaneous writer/reader busy cycles observed");
        reader_good(32'h100a_0000,14'd65,32'h0000_00b1,1'b0);

        test_bases[0]=32'h1008_0000; test_words[0]=1;
        test_bases[1]=32'h1008_0fc0; test_words[1]=2;
        test_bases[2]=32'h1008_1000; test_words[2]=63;
        test_bases[3]=32'h1008_2000; test_words[3]=64;
        test_bases[4]=32'h1008_3000; test_words[4]=65;
        for (k=0;k<5;k=k+1) begin
            small_committed=0;
            writer_good(test_bases[k],test_words[k],32'h0000_00c0+k);
            set_region_commit(test_bases[k],test_words[k],32'h0000_00c0+k);
            reader_good(test_bases[k],test_words[k],32'h0000_00c0+k,1'b0);
        end

        // A new partial update invalidates B before touching memory. It writes
        // one complete 2-word burst then cancels while waiting for the final word.
        b_committed=0;
        writer_cancel_partial_b(32'h100a_0000,32'h0000_00b2);
        for (word_idx=0;word_idx<2;word_idx=word_idx+1)
            for (b=0;b<64;b=b+1) begin
                addr_idx=32'h100a_0000-DDR_BASE+word_idx*64+b;
                if (ddr_bytes[addr_idx]!==golden_byte(word_idx,32'h0000_00b2,b))
                    $fatal(1,"Partial region B write byte mismatch");
            end
        probe_uncommitted_read(32'h100a_0000,14'd3,32'h0000_00b2);
        writer_clear();
        writer_good(32'h100a_0000,14'd3,32'h0000_00b3);
        set_region_commit(32'h100a_0000,14'd3,32'h0000_00b3);
        reader_good(32'h100a_0000,14'd3,32'h0000_00b3,1'b0);

        // An invalid BID consumes B but never commits region C. Recovery rewrites it.
        c_committed=0;
        next_bad_bid=1'b1;
        writer_fault_done(32'h100b_0000,14'd2,32'h0000_00d1,4'd5);
        if (c_committed) $fatal(1,"BID fault incorrectly committed region C");
        probe_uncommitted_read(32'h100b_0000,14'd2,32'h0000_00d1);
        writer_clear();
        writer_good(32'h100b_0000,14'd2,32'h0000_00d2);
        set_region_commit(32'h100b_0000,14'd2,32'h0000_00d2);
        reader_good(32'h100b_0000,14'd2,32'h0000_00d2,1'b0);

        // A committed read with a bad first RRESP must drain the complete burst,
        // expose no data/epoch, then recover on a clean request.
        reader_rresp_fault(DDR_BASE,14'd2,32'h0000_00a1);
        reader_clear();
        reader_good(DDR_BASE,14'd2,32'h0000_00a1,1'b0);

        if (w_aw_count!=4234 || w_w_count!=67688 || w_b_count!=4234 ||
            r_ar_count!=4234 || r_r_count!=67688 || w_done_count!=9 || r_done_count!=10 ||
            writer_fault_count!=2 || reader_fault_count!=1 || blocked_read_probes!=16 ||
            forbidden_ar_count!=0 || concurrent_busy_cycles==0 ||
            w_len16_count!=4227 || r_len16_count!=4227 ||
            max_w_streak<16 || max_r_streak<16 || aw_hold_checks==0 || w_hold_checks==0 ||
            ar_hold_checks==0 || r_hold_checks==0 || out_hold_checks==0 || input_hold_checks==0 ||
            rresp_drain_beats!=15 || golden_output_bytes!=541376)
            $fatal(1,"Loopback coverage mismatch W aw/w/b=%0d/%0d/%0d R ar/r=%0d/%0d done=%0d/%0d blocked=%0d overlap=%0d",
                   w_aw_count,w_w_count,w_b_count,r_ar_count,r_r_count,w_done_count,r_done_count,
                   blocked_read_probes,concurrent_busy_cycles);

        if (memory_write_bytes!=541504 || total_writer_input_words!=8461)
            $fatal(1,"Final canonical writer byte/input census mismatch bytes=%0d input=%0d",
                   memory_write_bytes,total_writer_input_words);
        $display("NATIVE_TRANSPORT_LOOPBACK_PASS capacity_words=8192 full_bytes=524288 input_words=%0d memory_write_bytes=%0d w_aw=%0d w_beats=%0d w_b=%0d r_ar=%0d r_beats=%0d output_words=%0d w_len16=%0d r_len16=%0d concurrent_cycles=%0d blocked_probes=%0d forbidden_ar=%0d w_done=%0d r_done=%0d writer_faults=%0d reader_faults=%0d drain_beats=%0d golden_output_bytes=%0d aw_hold=%0d w_hold=%0d ar_hold=%0d r_hold=%0d out_hold=%0d input_hold=%0d max_w_streak=%0d max_r_streak=%0d",
                 total_writer_input_words,memory_write_bytes,w_aw_count,w_w_count,w_b_count,r_ar_count,r_r_count,
                 golden_output_bytes/64,w_len16_count,r_len16_count,
                 concurrent_busy_cycles,blocked_read_probes,forbidden_ar_count,w_done_count,r_done_count,
                 writer_fault_count,reader_fault_count,rresp_drain_beats,golden_output_bytes,
                 aw_hold_checks,w_hold_checks,ar_hold_checks,r_hold_checks,out_hold_checks,input_hold_checks,
                 max_w_streak,max_r_streak);
        $finish;
    end
endmodule
`default_nettype wire
