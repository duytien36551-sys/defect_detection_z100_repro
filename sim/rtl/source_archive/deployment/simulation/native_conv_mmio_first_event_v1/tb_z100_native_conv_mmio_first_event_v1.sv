`timescale 1ns/1ps
`default_nettype none

// First materialized-Conv event driven through the real AXI-Lite frontend and
// native backend wrapper. The DUT receives DDR only through its AXI64 ports;
// expected arrays remain assertion-only and never feed the DUT.
module tb_z100_native_conv_mmio_first_event_v1;
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

    reg [11:0] s_axi_awaddr = 12'd0;
    reg s_axi_awvalid = 1'b0;
    wire s_axi_awready;
    reg [31:0] s_axi_wdata = 32'd0;
    reg [3:0] s_axi_wstrb = 4'd0;
    reg s_axi_wvalid = 1'b0;
    wire s_axi_wready;
    wire [1:0] s_axi_bresp;
    wire s_axi_bvalid;
    reg s_axi_bready = 1'b0;
    reg [11:0] s_axi_araddr = 12'd0;
    reg s_axi_arvalid = 1'b0;
    wire s_axi_arready;
    wire [31:0] s_axi_rdata;
    wire [1:0] s_axi_rresp;
    wire s_axi_rvalid;
    reg s_axi_rready = 1'b0;
    wire mmio_irq;

    localparam [31:0] CMD_EPOCH = 32'd200;
    localparam [7:0] CMD_EVENT = 8'd1;
    localparam [31:0] CMD_MODEL_CRC = 32'd2213989717;
    localparam [31:0] CMD_JOB_BASE = 32'd1;
    localparam [31:0] CMD_TOKEN_BASE = 32'd4100;
    localparam [31:0] CMD_TAG_BASE = 32'h53000000;
    localparam CMD_FIRST_BANK = 1'b0;
    localparam [31:0] CMD_COOKIE = 32'hc0decafe;
    localparam [31:0] CMD_PREACCEPT_TIMEOUT = 32'd5000000;

    // Values are sent through AXI-Lite; the grants below are real frontend outputs.
    localparam [31:0] cmd_source_base = 32'h10000000;
    localparam [31:0] cmd_source_generation = 32'd6901;
    localparam [32:0] CMD_SOURCE_REGION_END = 33'h010190000;
    localparam [31:0] cmd_destination_base = 32'h30000000;
    localparam [31:0] cmd_destination_generation = 32'd8201;
    localparam [32:0] CMD_DESTINATION_REGION_END = 33'h030200000;
    localparam [31:0] cmd_parameter_directory_base = 32'h21000000;
    localparam [15:0] CMD_PARAMETER_COUNT = 16'd173;
    localparam [31:0] cmd_parameter_payload_begin = 32'h20000000;
    localparam [32:0] cmd_parameter_payload_end = 33'h0202fa500;
    localparam [31:0] CMD_LOAD_TIMEOUT = 32'd5000000;
    localparam [31:0] CMD_PARAMETER_TIMEOUT = 32'd5000000;
    localparam [31:0] CMD_WRITE_TIMEOUT = 32'd1000000;

    wire active = dut.u_conv_backend.active;
    wire fault = dut.u_conv_backend.fault;
    wire [3:0] fault_code = dut.u_conv_backend.fault_code;
    wire needs_drain = dut.u_conv_backend.needs_drain;
    wire drain_complete = dut.u_conv_backend.drain_complete;
    wire all_io_quiet = dut.u_conv_backend.all_io_quiet;
    wire producer_context_valid = dut.u_conv_backend.producer_context_valid;
    wire [15:0] producer_cin = dut.u_conv_backend.producer_cin;
    wire [15:0] producer_input_height = dut.u_conv_backend.producer_input_height;
    wire [15:0] producer_input_width = dut.u_conv_backend.producer_input_width;
    wire [15:0] producer_cout = dut.u_conv_backend.producer_cout;
    wire [15:0] producer_output_height = dut.u_conv_backend.producer_output_height;
    wire [15:0] producer_output_width = dut.u_conv_backend.producer_output_width;
    wire [15:0] producer_kernel = dut.u_conv_backend.producer_kernel;
    wire [15:0] producer_stride = dut.u_conv_backend.producer_stride;
    wire [15:0] producer_padding = dut.u_conv_backend.producer_padding;
    wire [15:0] producer_parameter_first = dut.u_conv_backend.producer_parameter_first;
    wire [7:0] producer_event = dut.u_conv_backend.producer_event;
    wire producer_complete = dut.u_conv_backend.producer_complete;
    wire [31:0] producer_complete_epoch = dut.u_conv_backend.producer_complete_epoch;
    wire [7:0] producer_complete_event = dut.u_conv_backend.producer_complete_event;
    wire [31:0] producer_complete_model_crc = dut.u_conv_backend.producer_complete_model_crc;
    wire [31:0] producer_complete_job_base = dut.u_conv_backend.producer_complete_job_base;
    wire [31:0] producer_complete_token_base = dut.u_conv_backend.producer_complete_token_base;
    wire [31:0] producer_complete_tag_base = dut.u_conv_backend.producer_complete_tag_base;
    wire [31:0] producer_complete_destination_generation = dut.u_conv_backend.producer_complete_destination_generation;
    wire [7:0] producer_complete_tiles = dut.u_conv_backend.producer_complete_tiles;

    wire backend_cmd_valid = dut.u_mmio_frontend.backend_cmd_valid;
    wire backend_cmd_ready = dut.u_conv_backend.cmd_ready;
    wire raw_valid = dut.u_conv_backend.raw_valid;
    wire raw_ready = dut.u_conv_backend.raw_ready;
    wire [1023:0] raw_data = dut.u_conv_backend.raw_data;
    wire [31:0] raw_overflow = dut.u_conv_backend.raw_overflow;
    wire post_valid = dut.u_conv_backend.post_valid;
    wire post_ready = dut.u_conv_backend.post_ready;
    wire [255:0] post_data = dut.u_conv_backend.post_data;
    wire packed_valid = dut.u_conv_backend.packed_valid;
    wire packed_ready = dut.u_conv_backend.packed_ready;
    wire [12:0] packed_address = dut.u_conv_backend.packed_address;
    wire [511:0] packed_data = dut.u_conv_backend.packed_data;
    wire [9:0] tile_output_y = dut.u_conv_backend.tile_output_y;

    wire mmio_source_lease_valid = dut.source_lease_valid;
    wire mmio_destination_reservation_valid = dut.destination_reservation_valid;
    wire [31:0] source_lease_generation = dut.source_lease_generation;
    wire [31:0] source_lease_region_begin = dut.source_lease_region_begin;
    wire [32:0] source_lease_region_end = dut.source_lease_region_end;
    wire [31:0] destination_reservation_generation = dut.destination_reservation_generation;
    wire [31:0] destination_reservation_region_begin = dut.destination_reservation_region_begin;
    wire [32:0] destination_reservation_region_end = dut.destination_reservation_region_end;
    wire source_lease_valid = mmio_source_lease_valid;
    wire destination_reservation_valid = mmio_destination_reservation_valid;

    localparam [11:0] MMIO_REG_ID = 12'h000;
    localparam [11:0] MMIO_REG_ABI_VERSION = 12'h004;
    localparam [11:0] MMIO_REG_CAPABILITIES = 12'h008;
    localparam [11:0] MMIO_REG_CONTROL = 12'h00c;
    localparam [11:0] MMIO_REG_STATUS = 12'h010;
    localparam [11:0] MMIO_REG_BACKEND_FAULT_CODE = 12'h014;
    localparam [11:0] MMIO_REG_BRIDGE_ERROR = 12'h018;
    localparam [11:0] MMIO_REG_COMMITTED_TILES = 12'h01c;
    localparam [11:0] MMIO_REG_SHADOW_FIRST = 12'h040;
    localparam [11:0] MMIO_REG_RESULT_FIRST = 12'h100;
    localparam [31:0] MMIO_ID_VALUE = 32'h5a4e4331;
    localparam [31:0] MMIO_ABI_VERSION_VALUE = 32'h00010000;
    localparam [31:0] MMIO_CAPABILITIES_VALUE = 32'h0000003f;
    localparam [31:0] MMIO_CONTROL_START = 32'd1;
    localparam [31:0] MMIO_CONTROL_ACK = 32'd8;

    reg [31:0] mmio_command_words [0:26];
    reg [31:0] mmio_expected_results [0:9];
    reg [11:0] mmio_last_write_address = 12'd0;
    reg [31:0] mmio_last_write_data = 32'd0;
    integer mmio_aw_count = 0, mmio_w_count = 0, mmio_b_count = 0;
    integer mmio_ar_count = 0, mmio_r_count = 0;
    integer mmio_shadow_write_count = 0;
    integer mmio_start_count = 0, mmio_ack_count = 0;
    integer mmio_aw_first_calls = 0, mmio_w_first_calls = 0;
    integer mmio_held_b = 0, mmio_held_r = 0;
    reg mmio_aw_stalled = 1'b0, mmio_w_stalled = 1'b0;
    reg mmio_b_stalled = 1'b0, mmio_ar_stalled = 1'b0;
    reg mmio_r_stalled = 1'b0;
    reg [12:0] mmio_aw_held_payload = 13'd0;
    reg [35:0] mmio_w_held_payload = 36'd0;
    reg [1:0] mmio_b_held_payload = 2'd0;
    reg [12:0] mmio_ar_held_payload = 13'd0;
    reg [33:0] mmio_r_held_payload = 34'd0;
    integer mmio_timeout;
    reg [31:0] mmio_read_value;
    reg [31:0] mmio_status_value;
    reg [31:0] mmio_fault_value;
    reg [31:0] mmio_bridge_error_value;
    integer mmio_result_index;
    integer mmio_result_read_count = 0;
    integer mmio_write_ordinal = 0;
    reg mmio_handshake_done;

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

    z100_native_conv_mmio_backend_v1 #(
        .SITES(20), .SITE_FIFO_DEPTH(4),
        .MAP_FILE("conv_event_map.hex"), .TILE_FILE("conv_tiles.hex")
    ) dut (
        .clk(clk), .platform_rst_n(rst_n),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready),
        .irq(mmio_irq),
        .m_axi_arid(m_axi_arid), .m_axi_araddr(m_axi_araddr), .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize), .m_axi_arburst(m_axi_arburst), .m_axi_arvalid(m_axi_arvalid), .m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid), .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast), .m_axi_rvalid(m_axi_rvalid), .m_axi_rready(m_axi_rready),
        .m_axi_awid(m_axi_awid), .m_axi_awaddr(m_axi_awaddr), .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize), .m_axi_awburst(m_axi_awburst), .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_wid(m_axi_wid), .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast), .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid), .m_axi_bresp(m_axi_bresp), .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(m_axi_bready)
    );

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

    task mmio_send_aw;
        input [11:0] address;
        integer watchdog;
        begin
            @(negedge clk);
            s_axi_awaddr = address;
            s_axi_awvalid = 1'b1;
            watchdog = 0;
            mmio_handshake_done = 1'b0;
            while (!mmio_handshake_done) begin
                @(posedge clk);
                if (s_axi_awready === 1'b1) begin
                    mmio_aw_count = mmio_aw_count + 1;
                    mmio_handshake_done = 1'b1;
                end else begin
                    watchdog = watchdog + 1;
                    if (watchdog > 256) $fatal(1,"AXI-Lite AW timeout addr=%03x",address);
                end
            end
            @(negedge clk);
            s_axi_awvalid = 1'b0;
        end
    endtask

    task mmio_send_w;
        input [31:0] data;
        input [3:0] strb;
        integer watchdog;
        begin
            @(negedge clk);
            s_axi_wdata = data;
            s_axi_wstrb = strb;
            s_axi_wvalid = 1'b1;
            watchdog = 0;
            mmio_handshake_done = 1'b0;
            while (!mmio_handshake_done) begin
                @(posedge clk);
                if (s_axi_wready === 1'b1) begin
                    mmio_w_count = mmio_w_count + 1;
                    mmio_handshake_done = 1'b1;
                end else begin
                    watchdog = watchdog + 1;
                    if (watchdog > 256) $fatal(1,"AXI-Lite W timeout");
                end
            end
            @(negedge clk);
            s_axi_wvalid = 1'b0;
        end
    endtask

    task mmio_write_reg;
        input [11:0] address;
        input [31:0] data;
        input [3:0] strb;
        integer watchdog;
        begin
            mmio_last_write_address = address;
            mmio_last_write_data = data;
            if ((mmio_write_ordinal & 1) == 0) begin
                mmio_aw_first_calls = mmio_aw_first_calls + 1;
                mmio_send_aw(address);
                mmio_send_w(data,strb);
            end else begin
                mmio_w_first_calls = mmio_w_first_calls + 1;
                mmio_send_w(data,strb);
                mmio_send_aw(address);
            end
            watchdog = 0;
            while (s_axi_bvalid !== 1'b1) begin
                @(posedge clk);
                watchdog = watchdog + 1;
                if (watchdog > 256) $fatal(1,"AXI-Lite B timeout addr=%03x",address);
            end
            if (s_axi_bresp !== 2'b00) $fatal(1,"AXI-Lite BRESP error addr=%03x resp=%b",address,s_axi_bresp);
            repeat (2) @(negedge clk);
            s_axi_bready = 1'b1;
            @(posedge clk);
            if (s_axi_bvalid !== 1'b1) $fatal(1,"AXI-Lite BVALID withdrawn before handshake");
            mmio_b_count = mmio_b_count + 1;
            @(negedge clk);
            s_axi_bready = 1'b0;
            mmio_write_ordinal = mmio_write_ordinal + 1;
            if (address >= MMIO_REG_SHADOW_FIRST && address < MMIO_REG_SHADOW_FIRST+12'd108)
                mmio_shadow_write_count = mmio_shadow_write_count + 1;
            if (address == MMIO_REG_CONTROL && data == MMIO_CONTROL_START)
                mmio_start_count = mmio_start_count + 1;
            if (address == MMIO_REG_CONTROL && data == MMIO_CONTROL_ACK)
                mmio_ack_count = mmio_ack_count + 1;
        end
    endtask

    task mmio_read_reg;
        input [11:0] address;
        output [31:0] value;
        integer watchdog;
        begin
            @(negedge clk);
            s_axi_araddr = address;
            s_axi_arvalid = 1'b1;
            watchdog = 0;
            mmio_handshake_done = 1'b0;
            while (!mmio_handshake_done) begin
                @(posedge clk);
                if (s_axi_arready === 1'b1) begin
                    mmio_ar_count = mmio_ar_count + 1;
                    mmio_handshake_done = 1'b1;
                end else begin
                    watchdog = watchdog + 1;
                    if (watchdog > 256) $fatal(1,"AXI-Lite AR timeout addr=%03x",address);
                end
            end
            @(negedge clk);
            s_axi_arvalid = 1'b0;
            watchdog = 0;
            while (s_axi_rvalid !== 1'b1) begin
                @(posedge clk);
                watchdog = watchdog + 1;
                if (watchdog > 256) $fatal(1,"AXI-Lite R timeout addr=%03x",address);
            end
            if (s_axi_rresp !== 2'b00) $fatal(1,"AXI-Lite RRESP error addr=%03x resp=%b",address,s_axi_rresp);
            repeat (2) @(negedge clk);
            s_axi_rready = 1'b1;
            @(posedge clk);
            if (s_axi_rvalid !== 1'b1) $fatal(1,"AXI-Lite RVALID withdrawn before handshake");
            value = s_axi_rdata;
            mmio_r_count = mmio_r_count + 1;
            if (address >= MMIO_REG_RESULT_FIRST && address < MMIO_REG_RESULT_FIRST+12'd40)
                mmio_result_read_count = mmio_result_read_count + 1;
            @(negedge clk);
            s_axi_rready = 1'b0;
        end
    endtask

    task build_mmio_command;
        begin
            mmio_command_words[0] = CMD_COOKIE;
            mmio_command_words[1] = CMD_EPOCH;
            mmio_command_words[2] = {24'd0,CMD_EVENT};
            mmio_command_words[3] = CMD_MODEL_CRC;
            mmio_command_words[4] = CMD_JOB_BASE;
            mmio_command_words[5] = CMD_TOKEN_BASE;
            mmio_command_words[6] = CMD_TAG_BASE;
            mmio_command_words[7] = {29'd0,1'b1,1'b1,CMD_FIRST_BANK};
            mmio_command_words[8] = cmd_source_base;
            mmio_command_words[9] = cmd_source_generation;
            mmio_command_words[10] = cmd_source_base;
            mmio_command_words[11] = CMD_SOURCE_REGION_END[31:0];
            mmio_command_words[12] = {31'd0,CMD_SOURCE_REGION_END[32]};
            mmio_command_words[13] = cmd_destination_base;
            mmio_command_words[14] = cmd_destination_generation;
            mmio_command_words[15] = cmd_destination_base;
            mmio_command_words[16] = CMD_DESTINATION_REGION_END[31:0];
            mmio_command_words[17] = {31'd0,CMD_DESTINATION_REGION_END[32]};
            mmio_command_words[18] = cmd_parameter_directory_base;
            mmio_command_words[19] = {16'd0,CMD_PARAMETER_COUNT};
            mmio_command_words[20] = cmd_parameter_payload_begin;
            mmio_command_words[21] = cmd_parameter_payload_end[31:0];
            mmio_command_words[22] = {31'd0,cmd_parameter_payload_end[32]};
            mmio_command_words[23] = CMD_LOAD_TIMEOUT;
            mmio_command_words[24] = CMD_PARAMETER_TIMEOUT;
            mmio_command_words[25] = CMD_WRITE_TIMEOUT;
            mmio_command_words[26] = CMD_PREACCEPT_TIMEOUT;

            mmio_expected_results[0] = CMD_COOKIE;
            mmio_expected_results[1] = CMD_EPOCH;
            mmio_expected_results[2] = {24'd0,CMD_EVENT};
            mmio_expected_results[3] = CMD_MODEL_CRC;
            mmio_expected_results[4] = CMD_JOB_BASE;
            mmio_expected_results[5] = CMD_TOKEN_BASE;
            mmio_expected_results[6] = CMD_TAG_BASE;
            mmio_expected_results[7] = cmd_destination_generation;
            mmio_expected_results[8] = 32'd16;
            mmio_expected_results[9] = cmd_source_generation;
        end
    endtask

    // AXI-Lite payloads and responses are monitored independently of the
    // blocking driver tasks. B/R are intentionally held with READY low.
    always @(posedge clk) begin
        if (!rst_n) begin
            mmio_aw_stalled = 1'b0; mmio_w_stalled = 1'b0;
            mmio_b_stalled = 1'b0; mmio_ar_stalled = 1'b0; mmio_r_stalled = 1'b0;
            mmio_aw_held_payload = 13'd0; mmio_w_held_payload = 36'd0;
            mmio_b_held_payload = 2'd0; mmio_ar_held_payload = 13'd0;
            mmio_r_held_payload = 34'd0;
            mmio_held_b = 0; mmio_held_r = 0;
        end else begin
            if (mmio_aw_stalled && (!s_axi_awvalid || {s_axi_awaddr} !== mmio_aw_held_payload))
                $fatal(1,"AXI-Lite AW payload changed while stalled");
            if (mmio_w_stalled && (!s_axi_wvalid || {s_axi_wdata,s_axi_wstrb} !== mmio_w_held_payload))
                $fatal(1,"AXI-Lite W payload changed while stalled");
            if (mmio_b_stalled && (!s_axi_bvalid || s_axi_bresp !== mmio_b_held_payload))
                $fatal(1,"AXI-Lite B payload changed while stalled");
            if (mmio_ar_stalled && (!s_axi_arvalid || {s_axi_araddr} !== mmio_ar_held_payload))
                $fatal(1,"AXI-Lite AR payload changed while stalled");
            if (mmio_r_stalled && (!s_axi_rvalid || {s_axi_rdata,s_axi_rresp} !== mmio_r_held_payload))
                $fatal(1,"AXI-Lite R payload changed while stalled");
            mmio_aw_stalled = s_axi_awvalid && !s_axi_awready;
            mmio_w_stalled = s_axi_wvalid && !s_axi_wready;
            mmio_b_stalled = s_axi_bvalid && !s_axi_bready;
            mmio_ar_stalled = s_axi_arvalid && !s_axi_arready;
            mmio_r_stalled = s_axi_rvalid && !s_axi_rready;
            mmio_aw_held_payload = {s_axi_awaddr};
            mmio_w_held_payload = {s_axi_wdata,s_axi_wstrb};
            mmio_b_held_payload = s_axi_bresp;
            mmio_ar_held_payload = {s_axi_araddr};
            mmio_r_held_payload = {s_axi_rdata,s_axi_rresp};
            if (mmio_b_stalled) mmio_held_b = mmio_held_b + 1;
            if (mmio_r_stalled) mmio_held_r = mmio_held_r + 1;
        end
    end

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
            if (backend_cmd_valid && backend_cmd_ready) command_count = command_count + 1;

            if (producer_context_valid) begin
                context_seen = 1;
                if (producer_cin!=16'd3 || producer_input_height!=16'd640 ||
                    producer_input_width!=16'd640 || producer_cout!=16'd16 ||
                    producer_output_height!=16'd320 || producer_output_width!=16'd320 ||
                    producer_kernel!=16'd3 || producer_stride!=16'd2 ||
                    producer_padding!=16'd1 || producer_parameter_first!=16'd0 ||
                    producer_event!=CMD_EVENT)
                    $fatal(1,"ROM producer context mismatch");
            end
            if (producer_complete) begin
                completion_count = completion_count + 1;
                if (producer_complete_epoch!=CMD_EPOCH || producer_complete_event!=CMD_EVENT ||
                    producer_complete_model_crc!=CMD_MODEL_CRC ||
                    producer_complete_job_base!=CMD_JOB_BASE ||
                    producer_complete_token_base!=CMD_TOKEN_BASE ||
                    producer_complete_tag_base!=CMD_TAG_BASE ||
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

            if (raw_valid && raw_ready) begin
                if (raw_count>=RAW_RECORDS || {raw_data,raw_overflow}!==expected_raw[raw_count])
                    $fatal(1,"Complete raw stream mismatch record=%0d",raw_count);
                raw_count = raw_count + 1;
            end
            if (post_valid && post_ready) begin
                if (post_count>=POST_RECORDS || post_data!==expected_post[post_count])
                    $fatal(1,"Complete post stream mismatch record=%0d",post_count);
                post_count = post_count + 1;
            end
            if (packed_valid && packed_ready) begin
                if (packed_address>=13'd1600 || packed_count>=PACKED_WORDS)
                    $fatal(1,"Packed address/count invalid");
                packed_global_index = (packed_address/400)*6400 +
                    (tile_output_y+(packed_address%400)/20)*20 +
                    (packed_address%20);
                if (packed_global_index<0 || packed_global_index>=PACKED_WORDS ||
                    packed_data!==expected_packed[packed_global_index])
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
        build_mmio_command();
        for (i=0;i<OUTPUT_REGION_BEATS;i=i+1) output_memory[i]=GUARD;

        repeat (8) @(negedge clk);
        rst_n = 1'b1;
        mmio_read_reg(MMIO_REG_ID,mmio_read_value);
        if (mmio_read_value!==MMIO_ID_VALUE) $fatal(1,"MMIO ID mismatch got=%08x",mmio_read_value);
        mmio_read_reg(MMIO_REG_ABI_VERSION,mmio_read_value);
        if (mmio_read_value!==MMIO_ABI_VERSION_VALUE) $fatal(1,"MMIO ABI version mismatch");
        mmio_read_reg(MMIO_REG_CAPABILITIES,mmio_read_value);
        if (mmio_read_value!==MMIO_CAPABILITIES_VALUE) $fatal(1,"MMIO capabilities mismatch");
        mmio_read_reg(MMIO_REG_STATUS,mmio_status_value);
        if ((mmio_status_value & 32'h00000001)==0 || (mmio_status_value & 32'h0000033c)!=0)
            $fatal(1,"MMIO frontend/backend not READY before START status=%08x",mmio_status_value);
        mmio_read_reg(MMIO_REG_BACKEND_FAULT_CODE,mmio_fault_value);
        mmio_read_reg(MMIO_REG_BRIDGE_ERROR,mmio_bridge_error_value);
        if (mmio_fault_value!=0 || mmio_bridge_error_value!=0)
            $fatal(1,"Unexpected MMIO fault/bridge error before START");

        for (i=0;i<27;i=i+1)
            mmio_write_reg(MMIO_REG_SHADOW_FIRST + (i*4),mmio_command_words[i],4'hf);
        for (i=0;i<27;i=i+1) begin
            mmio_read_reg(MMIO_REG_SHADOW_FIRST + (i*4),mmio_read_value);
            if (mmio_read_value!==mmio_command_words[i])
                $fatal(1,"MMIO shadow readback mismatch word=%0d got=%08x expected=%08x",
                       i,mmio_read_value,mmio_command_words[i]);
        end
        mmio_read_reg(MMIO_REG_STATUS,mmio_status_value);
        mmio_read_reg(MMIO_REG_BRIDGE_ERROR,mmio_bridge_error_value);
        if ((mmio_status_value & 32'h00000001)==0 || mmio_bridge_error_value!=0)
            $fatal(1,"MMIO frontend lost READY before START status=%08x",mmio_status_value);
        mmio_write_reg(MMIO_REG_CONTROL,MMIO_CONTROL_START,4'hf);

        wait (command_count==1);
        wait (completion_count==1);
        mmio_status_value = 32'd0;
        mmio_timeout = 0;
        while ((mmio_status_value & 32'h00000110)!=32'h00000110) begin
            mmio_read_reg(MMIO_REG_STATUS,mmio_status_value);
            mmio_timeout = mmio_timeout + 1;
            if (mmio_timeout>4096) $fatal(1,"MMIO DONE/RESULT_VALID timeout status=%08x",mmio_status_value);
        end
        mmio_read_reg(MMIO_REG_BACKEND_FAULT_CODE,mmio_fault_value);
        mmio_read_reg(MMIO_REG_BRIDGE_ERROR,mmio_bridge_error_value);
        mmio_read_reg(MMIO_REG_COMMITTED_TILES,mmio_read_value);
        if (mmio_fault_value!=0 || mmio_bridge_error_value!=0 || mmio_read_value!=32'd16)
            $fatal(1,"MMIO terminal status fault=%08x bridge=%08x tiles=%0d",
                   mmio_fault_value,mmio_bridge_error_value,mmio_read_value);
        repeat (4) @(negedge clk);
        if (command_count!=1 || !context_seen || fault || active || needs_drain ||
            !all_io_quiet || !drain_complete || completion_count!=1 ||
            producer_complete_epoch!=CMD_EPOCH || producer_complete_event!=CMD_EVENT ||
            producer_complete_model_crc!=CMD_MODEL_CRC || producer_complete_job_base!=CMD_JOB_BASE ||
            producer_complete_token_base!=CMD_TOKEN_BASE || producer_complete_tag_base!=CMD_TAG_BASE ||
            producer_complete_destination_generation!=cmd_destination_generation ||
            producer_complete_tiles!=8'd16 ||
            !mmio_source_lease_valid || !mmio_destination_reservation_valid ||
            source_lease_generation!=cmd_source_generation ||
            destination_reservation_generation!=cmd_destination_generation ||
            source_lease_region_begin!=cmd_source_base || source_lease_region_end!=CMD_SOURCE_REGION_END ||
            destination_reservation_region_begin!=cmd_destination_base ||
            destination_reservation_region_end!=CMD_DESTINATION_REGION_END ||
            source_ar_count!=209600 || source_r_count!=209600 ||
            directory_ar_count!=directory_r_count || payload_ar_count!=payload_r_count ||
            directory_r_count+payload_r_count!=3712 ||
            r_count!=source_r_count+directory_r_count+payload_r_count ||
            raw_count!=RAW_RECORDS || post_count!=POST_RECORDS || packed_count!=PACKED_WORDS ||
            aw_count!=12800 || w_count!=OUTPUT_W_BEATS || b_count!=12800)
            $fatal(1,"Incomplete physical raw-complete/AXI/stream coverage");
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

        for (mmio_result_index=0;mmio_result_index<10;mmio_result_index=mmio_result_index+1) begin
            mmio_read_reg(MMIO_REG_RESULT_FIRST + (mmio_result_index*4),mmio_read_value);
            if (mmio_read_value!==mmio_expected_results[mmio_result_index])
                $fatal(1,"MMIO result identity mismatch word=%0d got=%08x expected=%08x",
                       mmio_result_index,mmio_read_value,mmio_expected_results[mmio_result_index]);
        end
        mmio_write_reg(MMIO_REG_CONTROL,MMIO_CONTROL_ACK,4'hf);
        repeat (2) @(negedge clk);
        mmio_read_reg(MMIO_REG_STATUS,mmio_status_value);
        mmio_read_reg(MMIO_REG_BACKEND_FAULT_CODE,mmio_fault_value);
        mmio_read_reg(MMIO_REG_BRIDGE_ERROR,mmio_bridge_error_value);
        if (mmio_status_value[0]!==1'b1 || (mmio_status_value & 32'h0000033c)!=0 ||
            mmio_fault_value!=0 || mmio_bridge_error_value!=0 ||
            mmio_source_lease_valid || mmio_destination_reservation_valid ||
            active || fault || !all_io_quiet || !drain_complete)
            $fatal(1,"MMIO ACK did not clear terminal state/grants status=%08x",mmio_status_value);
        if (mmio_shadow_write_count!=27 || mmio_start_count!=1 || mmio_ack_count!=1 ||
            mmio_aw_count!=29 || mmio_w_count!=29 || mmio_b_count!=29 ||
            mmio_aw_first_calls!=15 || mmio_w_first_calls!=14 ||
            mmio_ar_count!=mmio_r_count || mmio_result_read_count!=10 ||
            mmio_held_b==0 || mmio_held_r==0)
            $fatal(1,"MMIO AXI-Lite transaction/control/stall coverage incomplete");

        $display("MMIO_FIRST_EVENT_PASS tiles=16 raw=102400 post=102400 packed=25600 source_R=209600 parameter_R=3712 output_W=204800 output_AW_B=12800 guards=57344 held_AR=%0d held_AW=%0d held_W=%0d held_R=%0d held_B=%0d mmio_shadow=27 mmio_start=1 mmio_ack=1 mmio_results=10 mmio_AW=%0d mmio_W=%0d mmio_B=%0d mmio_AR=%0d mmio_R=%0d mmio_aw_first=%0d mmio_w_first=%0d mmio_held_B=%0d mmio_held_R=%0d producer_complete=PHYSICAL_TILES_ONLY ledger_publication=NOT_CLAIMED",
                 held_ar,held_aw,held_w,held_r,held_b,
                 mmio_aw_count,mmio_w_count,mmio_b_count,mmio_ar_count,mmio_r_count,
                 mmio_aw_first_calls,mmio_w_first_calls,mmio_held_b,mmio_held_r);
        $finish;
    end

    initial begin
        #400000000;
        $fatal(1,"Native Conv first-event watchdog");
    end
endmodule

`default_nettype wire
