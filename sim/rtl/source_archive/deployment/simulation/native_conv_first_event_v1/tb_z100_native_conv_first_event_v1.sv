`timescale 1ns/1ps
`default_nettype none

`ifndef NATIVE_CONV_BACKEND_TOP
`define NATIVE_CONV_BACKEND_TOP z100_native_conv_backend_v2
`endif

// Numerical event regression for the immutable, source-bound V2 backend.
// The DUT receives only real AXI64 source, parameter and destination traffic.
// Golden arrays are used solely by assertion monitors and never feed the DUT.
module tb_z100_native_conv_first_event_v1;
    localparam integer SOURCE_WORDS = 25600;       // 512-bit native DDR words
    localparam integer DIRECTORY_BEATS = 696;      // 64-bit words
    localparam integer PARAMETER_BEATS = 390304;   // 3,122,432 byte payload
    localparam integer RAW_RECORDS = 102400;
    localparam integer POST_RECORDS = 102400;
    localparam integer PACKED_WORDS = 25600;
    localparam integer OUTPUT_W_BEATS = 204800;
    localparam integer OUTPUT_REGION_BEATS = 262144; // separate 2 MiB region
    localparam integer OUTPUT_GUARD_BEATS = 57344;
    localparam [63:0] GUARD = 64'h5a1bc43df609728e;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;

    reg cmd_valid = 1'b0;
    wire cmd_ready;
    reg [31:0] cmd_epoch = 32'd200;
    reg [7:0] cmd_event = 8'd1;
    reg [31:0] cmd_model_crc = 32'd2213989717;
    reg [31:0] cmd_job_base = 32'd1;
    reg [31:0] cmd_token_base = 32'd4100;
    reg [31:0] cmd_tag_base = 32'h53000000;
    reg cmd_first_bank = 1'b0;

    // Test fixture metadata is driven through the full public command and
    // lease/reservation ports; no geometry or descriptors are injected.
    reg [31:0] cmd_source_base = 32'h10000000;
    reg [31:0] cmd_source_generation = 32'd6901;
    reg source_lease_valid = 1'b1;
    reg [31:0] source_lease_generation = 32'd6901;
    reg [31:0] source_lease_region_begin = 32'h10000000;
    reg [32:0] source_lease_region_end = 33'h010190000;

    reg [31:0] cmd_destination_base = 32'h30000000;
    reg [31:0] cmd_destination_generation = 32'd8201;
    reg destination_reservation_valid = 1'b1;
    reg [31:0] destination_reservation_generation = 32'd8201;
    reg [31:0] destination_reservation_region_begin = 32'h30000000;
    reg [32:0] destination_reservation_region_end = 33'h030200000;

    reg [31:0] cmd_parameter_directory_base = 32'h21000000;
    reg [15:0] cmd_parameter_count = 16'd173;
    reg [31:0] cmd_parameter_payload_begin = 32'h20000000;
    reg [32:0] cmd_parameter_payload_end = 33'h0202fa500;
    reg [31:0] cmd_load_timeout_cycles = 32'd5000000;
    reg [31:0] cmd_parameter_timeout_cycles = 32'd5000000;
    reg [31:0] cmd_write_timeout_cycles = 32'd1000000;
    reg cancel = 1'b0;

    wire active, fault;
    wire [3:0] fault_code;
    wire needs_drain, drain_complete, all_io_quiet;
    wire producer_context_valid;
    wire [15:0] producer_cin, producer_input_height, producer_input_width;
    wire [15:0] producer_cout, producer_output_height, producer_output_width;
    wire [15:0] producer_kernel, producer_stride, producer_padding;
    wire [15:0] producer_parameter_first;
    wire [7:0] producer_event;
    wire producer_complete;
    wire [31:0] producer_complete_epoch;
    wire [7:0] producer_complete_event;
    wire [31:0] producer_complete_model_crc, producer_complete_job_base;
    wire [31:0] producer_complete_token_base, producer_complete_tag_base;
    wire [31:0] producer_complete_destination_generation;
    wire [7:0] producer_complete_tiles;

    wire [5:0] m_axi_arid;
    wire [31:0] m_axi_araddr;
    wire [3:0] m_axi_arlen;
    wire [2:0] m_axi_arsize;
    wire [1:0] m_axi_arburst;
    wire m_axi_arvalid;
    reg m_axi_arready = 1'b0;
    reg [5:0] m_axi_rid = 6'd0;
    reg [63:0] m_axi_rdata = 64'd0;
    reg [1:0] m_axi_rresp = 2'b00;
    reg m_axi_rlast = 1'b0;
    reg m_axi_rvalid = 1'b0;
    wire m_axi_rready;

    wire [5:0] m_axi_awid;
    wire [31:0] m_axi_awaddr;
    wire [3:0] m_axi_awlen;
    wire [2:0] m_axi_awsize;
    wire [1:0] m_axi_awburst;
    wire m_axi_awvalid;
    reg m_axi_awready = 1'b0;
    wire [5:0] m_axi_wid;
    wire [63:0] m_axi_wdata;
    wire [7:0] m_axi_wstrb;
    wire m_axi_wlast, m_axi_wvalid;
    reg m_axi_wready = 1'b0;
    reg [5:0] m_axi_bid = 6'd0;
    reg [1:0] m_axi_bresp = 2'b00;
    reg m_axi_bvalid = 1'b0;
    wire m_axi_bready;

    `NATIVE_CONV_BACKEND_TOP dut (.*);

    reg [511:0] source_memory [0:SOURCE_WORDS-1];
    reg [63:0] directory_memory [0:DIRECTORY_BEATS-1];
    reg [63:0] parameter_memory [0:PARAMETER_BEATS-1];
    reg [1055:0] expected_raw [0:RAW_RECORDS-1];
    reg [255:0] expected_post [0:POST_RECORDS-1];
    reg [511:0] expected_packed [0:PACKED_WORDS-1];
    reg [511:0] expected_native_ddr [0:PACKED_WORDS-1];
    reg [63:0] output_memory [0:OUTPUT_REGION_BEATS-1];

    function [63:0] memory_read64;
        input [31:0] address;
        reg [511:0] source_line;
        begin
            if (address >= cmd_source_base &&
                {1'b0,address} < source_lease_region_end) begin
                source_line = source_memory[(address-cmd_source_base) >> 6];
                memory_read64 = source_line[address[5:3]*64 +: 64];
            end else if (address >= cmd_parameter_directory_base &&
                         {1'b0,address} < ({1'b0,cmd_parameter_directory_base}+33'd5568)) begin
                memory_read64 = directory_memory[(address-cmd_parameter_directory_base) >> 3];
            end else if (address >= cmd_parameter_payload_begin &&
                         {1'b0,address} < cmd_parameter_payload_end) begin
                memory_read64 = parameter_memory[(address-cmd_parameter_payload_begin) >> 3];
            end else begin
                memory_read64 = 64'hxxxxxxxxxxxxxxxx;
            end
        end
    endfunction

    wire [32:0] ar_end = {1'b0,m_axi_araddr} + ({29'd0,m_axi_arlen}+33'd1)*33'd8;
    wire [32:0] aw_end = {1'b0,m_axi_awaddr} + ({29'd0,m_axi_awlen}+33'd1)*33'd8;
    wire [46:0] ar_payload = {m_axi_arid,m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst};
    wire [46:0] aw_payload = {m_axi_awid,m_axi_awaddr,m_axi_awlen,m_axi_awsize,m_axi_awburst};
    wire [78:0] w_payload = {m_axi_wid,m_axi_wdata,m_axi_wstrb,m_axi_wlast};
    wire [72:0] r_payload = {m_axi_rid,m_axi_rdata,m_axi_rresp,m_axi_rlast};
    wire [7:0] b_payload = {m_axi_bid,m_axi_bresp};

    integer cycle_count = 0;
    reg rd_active = 1'b0;
    integer rd_beats = 0;
    integer rd_beat_index = 0;
    reg [31:0] rd_address = 32'd0;
    reg [5:0] rd_id = 6'd0;
    reg wr_active = 1'b0;
    integer wr_beats = 0;
    integer wr_beat_index = 0;
    reg [31:0] wr_address = 32'd0;
    reg [5:0] wr_id = 6'd0;
    reg b_pending = 1'b0;
    integer b_delay = 0;

    // All READY controls change on the falling edge and stay stable through
    // the next transfer edge, avoiding the previous writer-ready race.
    always @(negedge clk) begin
        if (!rst_n) begin
            m_axi_arready = 1'b0;
            m_axi_awready = 1'b0;
            m_axi_wready = 1'b0;
        end else begin
            m_axi_arready = !rd_active && ((cycle_count % 7) != 0);
            m_axi_awready = !wr_active && ((cycle_count % 11) != 3);
            m_axi_wready = ((cycle_count % 9) != 2) && ((cycle_count % 13) != 5);
        end
    end

    // One outstanding read response stream, with the accepted AXI ID and
    // stable R payload held until RREADY. Data always comes from frozen files.
    always @(posedge clk) begin
        if (!rst_n) begin
            rd_active <= 1'b0;
            rd_beats <= 0;
            rd_beat_index <= 0;
            rd_address <= 32'd0;
            rd_id <= 6'd0;
            m_axi_rid <= 6'd0;
            m_axi_rdata <= 64'd0;
            m_axi_rresp <= 2'b00;
            m_axi_rlast <= 1'b0;
            m_axi_rvalid <= 1'b0;
        end else begin
            if (m_axi_arvalid && m_axi_arready) begin
                rd_active <= 1'b1;
                rd_beats <= m_axi_arlen + 1;
                rd_beat_index <= 0;
                rd_address <= m_axi_araddr;
                rd_id <= m_axi_arid;
            end
            if (m_axi_rvalid && m_axi_rready) begin
                m_axi_rvalid <= 1'b0;
                if (m_axi_rlast) begin
                    rd_active <= 1'b0;
                    rd_beat_index <= 0;
                end else begin
                    rd_beat_index <= rd_beat_index + 1;
                    rd_address <= rd_address + 32'd8;
                end
            end else if (rd_active && !m_axi_rvalid && ((cycle_count % 11) != 2)) begin
                m_axi_rid <= rd_id;
                m_axi_rdata <= memory_read64(rd_address);
                m_axi_rresp <= 2'b00;
                m_axi_rlast <= (rd_beat_index == rd_beats-1);
                m_axi_rvalid <= 1'b1;
            end
        end
    end

    // Real AXI write capture with delayed B responses. The capture area is a
    // separate 2 MiB region; its tail remains a checked guard.
    always @(posedge clk) begin
        if (!rst_n) begin
            wr_active <= 1'b0;
            wr_beats <= 0;
            wr_beat_index <= 0;
            wr_address <= 32'd0;
            wr_id <= 6'd0;
            b_pending <= 1'b0;
            b_delay <= 0;
            m_axi_bid <= 6'd0;
            m_axi_bresp <= 2'b00;
            m_axi_bvalid <= 1'b0;
        end else begin
            if (m_axi_awvalid && m_axi_awready) begin
                wr_active <= 1'b1;
                wr_beats <= m_axi_awlen + 1;
                wr_beat_index <= 0;
                wr_address <= m_axi_awaddr;
                wr_id <= m_axi_awid;
            end
            if (m_axi_wvalid && m_axi_wready) begin
                output_memory[(wr_address-cmd_destination_base)/8 + wr_beat_index] <= m_axi_wdata;
                if (m_axi_wlast) begin
                    b_pending <= 1'b1;
                    b_delay <= 3;
                end else begin
                    wr_beat_index <= wr_beat_index + 1;
                end
            end
            if (m_axi_bvalid && m_axi_bready) begin
                m_axi_bvalid <= 1'b0;
                b_pending <= 1'b0;
                wr_active <= 1'b0;
                wr_beat_index <= 0;
            end else if (b_pending && !m_axi_bvalid) begin
                if (b_delay != 0) b_delay <= b_delay - 1;
                else begin
                    m_axi_bid <= wr_id;
                    m_axi_bresp <= 2'b00;
                    m_axi_bvalid <= 1'b1;
                end
            end
        end
    end

    integer command_count = 0;
    integer context_seen = 0;
    integer completion_count = 0;
    integer source_ar_count = 0, source_r_count = 0;
    integer directory_ar_count = 0, payload_ar_count = 0;
    integer directory_r_count = 0, payload_r_count = 0;
    integer ar_count = 0, r_count = 0;
    integer aw_count = 0, w_count = 0, b_count = 0;
    integer raw_count = 0, post_count = 0, packed_count = 0;
    integer held_ar = 0, held_aw = 0, held_w = 0, held_r = 0, held_b = 0;
    reg ar_stalled = 1'b0, aw_stalled = 1'b0, w_stalled = 1'b0;
    reg r_stalled = 1'b0, b_stalled = 1'b0;
    reg [46:0] ar_held_payload = 47'd0, aw_held_payload = 47'd0;
    reg [78:0] w_held_payload = 79'd0;
    reg [72:0] r_held_payload = 73'd0;
    reg [7:0] b_held_payload = 8'd0;
    integer packed_global_index;
    integer i,j;

    always @(posedge clk) begin
        if (!rst_n) begin
            cycle_count = 0;
            command_count = 0;
            context_seen = 0;
            completion_count = 0;
            source_ar_count = 0;
            source_r_count = 0;
            directory_ar_count = 0;
            payload_ar_count = 0;
            directory_r_count = 0;
            payload_r_count = 0;
            ar_count = 0; r_count = 0;
            aw_count = 0; w_count = 0; b_count = 0;
            raw_count = 0; post_count = 0; packed_count = 0;
            held_ar = 0; held_aw = 0; held_w = 0; held_r = 0; held_b = 0;
            ar_stalled = 1'b0; aw_stalled = 1'b0; w_stalled = 1'b0;
            r_stalled = 1'b0; b_stalled = 1'b0;
        end else begin
            cycle_count = cycle_count + 1;
            if (fault) $fatal(1,"V2 backend fault code=%0d",fault_code);
            if (needs_drain && !fault) $fatal(1,"Drain requested without backend fault");
            if (cmd_valid && cmd_ready) command_count = command_count + 1;

            if (producer_context_valid) begin
                context_seen = 1;
                if (producer_cin!=16'd3 || producer_input_height!=16'd640 ||
                    producer_input_width!=16'd640 || producer_cout!=16'd16 ||
                    producer_output_height!=16'd320 || producer_output_width!=16'd320 ||
                    producer_kernel!=16'd3 || producer_stride!=16'd2 ||
                    producer_padding!=16'd1 || producer_parameter_first!=16'd0 ||
                    producer_event!=8'd1)
                    $fatal(1,"ROM producer context mismatch");
            end
            if (producer_complete) begin
                completion_count = completion_count + 1;
                if (producer_complete_epoch!=cmd_epoch || producer_complete_event!=cmd_event ||
                    producer_complete_model_crc!=cmd_model_crc ||
                    producer_complete_job_base!=cmd_job_base ||
                    producer_complete_token_base!=cmd_token_base ||
                    producer_complete_tag_base!=cmd_tag_base ||
                    producer_complete_destination_generation!=cmd_destination_generation ||
                    producer_complete_tiles!=8'd16)
                    $fatal(1,"Raw complete identity/tiles mismatch");
            end

            if (ar_stalled && (!m_axi_arvalid || ar_payload!==ar_held_payload))
                $fatal(1,"AR payload/valid changed while stalled");
            if (aw_stalled && (!m_axi_awvalid || aw_payload!==aw_held_payload))
                $fatal(1,"AW payload/valid changed while stalled");
            if (w_stalled && (!m_axi_wvalid || w_payload!==w_held_payload))
                $fatal(1,"W payload/valid changed while stalled");
            if (r_stalled && (!m_axi_rvalid || r_payload!==r_held_payload))
                $fatal(1,"R payload/valid changed while stalled");
            if (b_stalled && (!m_axi_bvalid || b_payload!==b_held_payload))
                $fatal(1,"B payload/valid changed while stalled");
            ar_stalled = m_axi_arvalid && !m_axi_arready;
            aw_stalled = m_axi_awvalid && !m_axi_awready;
            w_stalled = m_axi_wvalid && !m_axi_wready;
            r_stalled = m_axi_rvalid && !m_axi_rready;
            b_stalled = m_axi_bvalid && !m_axi_bready;
            ar_held_payload = ar_payload;
            aw_held_payload = aw_payload;
            w_held_payload = w_payload;
            r_held_payload = r_payload;
            b_held_payload = b_payload;
            if (ar_stalled) held_ar = held_ar + 1;
            if (aw_stalled) held_aw = held_aw + 1;
            if (w_stalled) held_w = held_w + 1;
            if (r_stalled) held_r = held_r + 1;
            if (b_stalled) held_b = held_b + 1;

            if (m_axi_arvalid && m_axi_arready) begin
                ar_count = ar_count + 1;
                if (m_axi_arsize!=3'd3 || m_axi_arburst!=2'b01 ||
                    m_axi_araddr[2:0]!=0 || ar_end[32] ||
                    m_axi_araddr[11:0]+(m_axi_arlen+1)*8>4096 || rd_active)
                    $fatal(1,"Illegal or overlapping AXI read request");
                if (m_axi_araddr>=cmd_source_base && ar_end<={1'b0,source_lease_region_end})
                    source_ar_count = source_ar_count + m_axi_arlen + 1;
                else if (m_axi_araddr>=cmd_parameter_directory_base &&
                         ar_end<=({1'b0,cmd_parameter_directory_base}+33'd5568))
                    directory_ar_count = directory_ar_count + m_axi_arlen + 1;
                else if (m_axi_araddr>=cmd_parameter_payload_begin && ar_end<=cmd_parameter_payload_end)
                    payload_ar_count = payload_ar_count + m_axi_arlen + 1;
                else $fatal(1,"AXI read escaped source, directory or parameter bounds: %08x",m_axi_araddr);
            end
            if (m_axi_rvalid && m_axi_rready) begin
                r_count = r_count + 1;
                if (!rd_active || m_axi_rid!=rd_id || m_axi_rresp!=2'b00 ||
                    m_axi_rlast!=(rd_beat_index==rd_beats-1))
                    $fatal(1,"AXI read response ID/RESP/LAST mismatch");
                if (rd_address>=cmd_source_base && {1'b0,rd_address}<source_lease_region_end)
                    source_r_count = source_r_count + 1;
                else if (rd_address>=cmd_parameter_directory_base &&
                         {1'b0,rd_address}<({1'b0,cmd_parameter_directory_base}+33'd5568))
                    directory_r_count = directory_r_count + 1;
                else if (rd_address>=cmd_parameter_payload_begin &&
                         {1'b0,rd_address}<cmd_parameter_payload_end)
                    payload_r_count = payload_r_count + 1;
                else $fatal(1,"AXI read response address out of range");
            end
            if (m_axi_awvalid && m_axi_awready) begin
                aw_count = aw_count + 1;
                if (m_axi_awsize!=3'd3 || m_axi_awburst!=2'b01 ||
                    m_axi_awaddr[6:0]!=0 || aw_end[32] ||
                    m_axi_awaddr[11:0]+(m_axi_awlen+1)*8>4096 ||
                    m_axi_awaddr<cmd_destination_base ||
                    aw_end>{1'b0,destination_reservation_region_end} || wr_active ||
                    m_axi_awlen!=4'd15)
                    $fatal(1,"Illegal AXI output burst/bounds");
            end
            if (m_axi_wvalid && m_axi_wready) begin
                w_count = w_count + 1;
                if (!wr_active || m_axi_wid!=wr_id || m_axi_wstrb!=8'hff ||
                    wr_beat_index>=wr_beats || m_axi_wlast!=(wr_beat_index==wr_beats-1))
                    $fatal(1,"AXI W beat ID/STRB/LAST mismatch");
            end
            if (m_axi_bvalid && m_axi_bready) begin
                b_count = b_count + 1;
                if (!wr_active || !b_pending || m_axi_bid!=wr_id || m_axi_bresp!=2'b00)
                    $fatal(1,"AXI B response identity/status mismatch");
            end

            if (dut.raw_valid && dut.raw_ready) begin
                if (raw_count>=RAW_RECORDS || {dut.raw_data,dut.raw_overflow}!==expected_raw[raw_count])
                    $fatal(1,"Complete raw stream mismatch record=%0d",raw_count);
                raw_count = raw_count + 1;
            end
            if (dut.post_valid && dut.post_ready) begin
                if (post_count>=POST_RECORDS || dut.post_data!==expected_post[post_count])
                    $fatal(1,"Complete post stream mismatch record=%0d",post_count);
                post_count = post_count + 1;
            end
            if (dut.packed_valid && dut.packed_ready) begin
                if (dut.packed_address>=13'd1600 || packed_count>=PACKED_WORDS)
                    $fatal(1,"Packed address/count invalid");
                packed_global_index = (dut.packed_address/400)*6400 +
                    (dut.tile_output_y+(dut.packed_address%400)/20)*20 +
                    (dut.packed_address%20);
                if (packed_global_index<0 || packed_global_index>=PACKED_WORDS ||
                    dut.packed_data!==expected_packed[packed_global_index])
                    $fatal(1,"Complete packed stream mismatch record=%0d global=%0d",
                           packed_count,packed_global_index);
                packed_count = packed_count + 1;
            end
        end
    end

    initial begin
        $readmemh("input_native_DDR.hex",source_memory);
        $readmemh("directory.hex",directory_memory);
        $readmemh("parameter_memory.hex",parameter_memory);
        $readmemh("expected_raw_words.hex",expected_raw);
        $readmemh("expected_post_words.hex",expected_post);
        $readmemh("expected_packed_words.hex",expected_packed);
        $readmemh("expected_native_DDR.hex",expected_native_ddr);
        for (i=0;i<OUTPUT_REGION_BEATS;i=i+1) output_memory[i]=GUARD;

        repeat (8) @(negedge clk);
        rst_n = 1'b1;
        wait (cmd_ready===1'b1);
        @(negedge clk); cmd_valid = 1'b1;
        @(posedge clk);
        if (!cmd_ready) $fatal(1,"Backend did not admit the complete command");
        @(negedge clk); cmd_valid = 1'b0;

        wait (completion_count==1);
        repeat (4) @(negedge clk);
        if (command_count!=1 || !context_seen || fault || active || needs_drain ||
            !all_io_quiet || !drain_complete || completion_count!=1 ||
            source_ar_count!=209600 || source_r_count!=209600 ||
            directory_ar_count!=directory_r_count || payload_ar_count!=payload_r_count ||
            directory_r_count+payload_r_count!=3712 ||
            r_count!=source_r_count+directory_r_count+payload_r_count ||
            raw_count!=RAW_RECORDS || post_count!=POST_RECORDS || packed_count!=PACKED_WORDS ||
            aw_count!=12800 || w_count!=OUTPUT_W_BEATS || b_count!=12800)
            $fatal(1,"Incomplete raw-complete/AXI/stream coverage");
        if (OUTPUT_REGION_BEATS-OUTPUT_W_BEATS!=OUTPUT_GUARD_BEATS)
            $fatal(1,"Fixture output guard geometry");
        for (i=0;i<PACKED_WORDS;i=i+1) begin
            for (j=0;j<8;j=j+1) begin
                if (output_memory[i*8+j]!==expected_native_ddr[i][j*64 +: 64])
                    $fatal(1,"Native DDR golden mismatch word=%0d beat=%0d",i,j);
            end
        end
        for (i=OUTPUT_W_BEATS;i<OUTPUT_REGION_BEATS;i=i+1) begin
            if (output_memory[i]!==GUARD) $fatal(1,"Output guard modified word=%0d",i);
        end
        if (held_ar==0 || held_aw==0 || held_w==0)
            $fatal(1,"AXI AR/AW/W stall coverage missing");

        $display("NATIVE_CONV_FIRST_EVENT_PASS raw=102400 post=102400 packed=25600 source_R=209600 parameter_R=3712 output_W=204800 output_AW_B=12800 guards=57344 held_AR=%0d held_AW=%0d held_W=%0d held_R=%0d held_B=%0d producer_complete=PHYSICAL_TILES_ONLY ledger_publication=NOT_CLAIMED",
                 held_ar,held_aw,held_w,held_r,held_b);
        $finish;
    end

    initial begin
        #400000000;
        $fatal(1,"Native Conv first-event watchdog");
    end
endmodule

`default_nettype wire
