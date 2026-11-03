`default_nettype none

// AXI4-Lite frontend for the proposed native Conv V3 relative-register ABI.
// This block does not instantiate the Conv backend or assign a PS address.
// platform_rst_n must be the coordinated platform reset shared with the
// backend/AXI fabric; this block has no software-visible local reset.
module z100_native_conv_mmio_v1 (
    input  wire         clk,
    input  wire         platform_rst_n,

    input  wire [31:0]  s_axi_awaddr,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire [3:0]   s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output reg  [1:0]   s_axi_bresp,
    output reg          s_axi_bvalid,
    input  wire         s_axi_bready,

    input  wire [31:0]  s_axi_araddr,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output reg  [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready,

    // Word 0 is backend_cmd_words[31:0] (cookie); word 26 is the high word.
    output wire [863:0] backend_cmd_words,
    output wire         backend_cmd_valid,
    input  wire         backend_cmd_ready,
    output wire         backend_cancel,

    // Lease and reservation grants are driven from the immutable command
    // snapshot and remain stable from START through terminal ACK.
    output wire         backend_source_lease_valid,
    output wire [31:0]  backend_source_lease_generation,
    output wire [31:0]  backend_source_lease_region_begin,
    output wire [32:0]  backend_source_lease_region_end,
    output wire         backend_destination_reservation_valid,
    output wire [31:0]  backend_destination_reservation_generation,
    output wire [31:0]  backend_destination_reservation_region_begin,
    output wire [32:0]  backend_destination_reservation_region_end,

    // Status/completion wires correspond to z100_native_conv_backend_v3.
    input  wire         backend_active,
    input  wire         backend_fault,
    input  wire [3:0]   backend_fault_code,
    input  wire         backend_needs_drain,
    input  wire         backend_drain_complete,
    input  wire         backend_all_io_quiet,
    input  wire [7:0]   backend_committed_tiles,
    input  wire         backend_producer_complete,
    input  wire [31:0]  backend_complete_epoch,
    input  wire [7:0]   backend_complete_event,
    input  wire [31:0]  backend_complete_model_crc,
    input  wire [31:0]  backend_complete_job_base,
    input  wire [31:0]  backend_complete_token_base,
    input  wire [31:0]  backend_complete_tag_base,
    input  wire [31:0]  backend_complete_destination_generation,
    input  wire [7:0]   backend_complete_tiles,

    output wire         irq
);
    localparam [31:0] REG_ID                    = 32'h000;
    localparam [31:0] REG_ABI_VERSION           = 32'h004;
    localparam [31:0] REG_CAPABILITIES          = 32'h008;
    localparam [31:0] REG_CONTROL               = 32'h00c;
    localparam [31:0] REG_STATUS                = 32'h010;
    localparam [31:0] REG_BACKEND_FAULT_CODE    = 32'h014;
    localparam [31:0] REG_BRIDGE_ERROR          = 32'h018;
    localparam [31:0] REG_COMMITTED_TILES       = 32'h01c;
    localparam [31:0] REG_SHADOW_FIRST          = 32'h040;
    localparam [31:0] REG_SHADOW_LAST           = 32'h0a8;
    localparam [31:0] REG_RESULT_FIRST          = 32'h100;
    localparam [31:0] REG_RESULT_LAST           = 32'h124;

    localparam [31:0] CONTROL_START             = 32'h00000001;
    localparam [31:0] CONTROL_ABORT             = 32'h00000002;
    localparam [31:0] CONTROL_CANCEL            = 32'h00000004;
    localparam [31:0] CONTROL_ACK               = 32'h00000008;
    localparam [31:0] CONTROL_MASK              = 32'h0000000f;

    localparam [31:0] ERROR_NONE                = 32'd0;
    localparam [31:0] ERROR_INVALID_SHADOW      = 32'd1;
    localparam [31:0] ERROR_PREACCEPT_ABORT     = 32'd2;
    localparam [31:0] ERROR_PREACCEPT_TIMEOUT   = 32'd3;
    localparam [31:0] ERROR_ILLEGAL_CONTROL     = 32'd4;

    localparam [1:0] ST_IDLE                   = 2'd0;
    localparam [1:0] ST_PENDING                = 2'd1;
    localparam [1:0] ST_ACCEPTED               = 2'd2;
    localparam [1:0] ST_TERMINAL               = 2'd3;

    localparam [1:0] AXI_OKAY                  = 2'b00;
    localparam [1:0] AXI_SLVERR                = 2'b10;

    reg [863:0] shadow_words_q;
    reg [863:0] command_words_q;
    reg [319:0] result_words_q;
    reg [319:0] success_words_q;
    reg [1:0] state_q;
    reg snapshot_valid_q;
    reg accepted_q;
    reg result_valid_q;
    reg done_q;
    reg preaccept_timeout_q;
    reg [31:0] bridge_error_q;
    reg [31:0] preaccept_count_q;
    reg success_pending_q;
    reg fault_seen_q;
    reg [3:0] fault_code_snapshot_q;
    reg backend_cancel_q;

    reg aw_hold_q;
    reg [31:0] awaddr_hold_q;
    reg w_hold_q;
    reg [31:0] wdata_hold_q;
    reg [3:0] wstrb_hold_q;

    wire aw_fire = s_axi_awvalid && s_axi_awready;
    wire w_fire = s_axi_wvalid && s_axi_wready;
    wire write_complete = (aw_hold_q || aw_fire) &&
                          (w_hold_q || w_fire) && !s_axi_bvalid;
    wire [31:0] write_addr = aw_hold_q ? awaddr_hold_q : s_axi_awaddr;
    wire [31:0] write_data = w_hold_q ? wdata_hold_q : s_axi_wdata;
    wire [3:0] write_strb = w_hold_q ? wstrb_hold_q : s_axi_wstrb;
    wire [31:0] write_byte_mask = {{8{write_strb[3]}}, {8{write_strb[2]}},
                                   {8{write_strb[1]}}, {8{write_strb[0]}}};
    wire [31:0] write_masked_data = write_data & write_byte_mask;
    wire write_zero_strobe = write_complete && (write_strb == 4'b0000);
    wire write_addr_aligned = (write_addr[1:0] == 2'b00) && (write_addr[31:9] == 0);
    wire write_is_shadow = write_addr_aligned && write_addr >= REG_SHADOW_FIRST &&
                           write_addr <= REG_SHADOW_LAST;
    wire write_is_control = write_addr_aligned && (write_addr == REG_CONTROL);
    wire shadow_locked = snapshot_valid_q || (bridge_error_q != ERROR_NONE) ||
                         (state_q != ST_IDLE) || accepted_q || result_valid_q;

    wire [31:0] sh_epoch = shadow_words_q[1*32 +: 32];
    wire [31:0] sh_event = shadow_words_q[2*32 +: 32];
    wire [31:0] sh_model_crc = shadow_words_q[3*32 +: 32];
    wire [31:0] sh_job_base = shadow_words_q[4*32 +: 32];
    wire [31:0] sh_token_base = shadow_words_q[5*32 +: 32];
    wire [31:0] sh_tag_base = shadow_words_q[6*32 +: 32];
    wire [31:0] sh_flags = shadow_words_q[7*32 +: 32];
    wire [31:0] sh_source_base = shadow_words_q[8*32 +: 32];
    wire [31:0] sh_source_generation = shadow_words_q[9*32 +: 32];
    wire [31:0] sh_source_begin = shadow_words_q[10*32 +: 32];
    wire [31:0] sh_source_end_lo = shadow_words_q[11*32 +: 32];
    wire [31:0] sh_source_end_hi = shadow_words_q[12*32 +: 32];
    wire [31:0] sh_destination_base = shadow_words_q[13*32 +: 32];
    wire [31:0] sh_destination_generation = shadow_words_q[14*32 +: 32];
    wire [31:0] sh_destination_begin = shadow_words_q[15*32 +: 32];
    wire [31:0] sh_destination_end_lo = shadow_words_q[16*32 +: 32];
    wire [31:0] sh_destination_end_hi = shadow_words_q[17*32 +: 32];
    wire [31:0] sh_parameter_directory_base = shadow_words_q[18*32 +: 32];
    wire [31:0] sh_parameter_count = shadow_words_q[19*32 +: 32];
    wire [31:0] sh_parameter_payload_begin = shadow_words_q[20*32 +: 32];
    wire [31:0] sh_parameter_payload_end_lo = shadow_words_q[21*32 +: 32];
    wire [31:0] sh_parameter_payload_end_hi = shadow_words_q[22*32 +: 32];
    wire [31:0] sh_load_timeout = shadow_words_q[23*32 +: 32];
    wire [31:0] sh_parameter_timeout = shadow_words_q[24*32 +: 32];
    wire [31:0] sh_write_timeout = shadow_words_q[25*32 +: 32];
    wire [31:0] sh_preaccept_timeout = shadow_words_q[26*32 +: 32];

    wire [32:0] sh_source_end = {sh_source_end_hi[0], sh_source_end_lo};
    wire [32:0] sh_destination_end = {sh_destination_end_hi[0], sh_destination_end_lo};
    wire [32:0] sh_parameter_payload_end = {sh_parameter_payload_end_hi[0], sh_parameter_payload_end_lo};
    (* use_dsp = "no" *) wire [32:0] sh_directory_bytes =
        (({17'd0, sh_parameter_count[15:0]} + 33'd1) >> 1) << 6;
    (* use_dsp = "no" *) wire [32:0] sh_directory_end =
        {1'b0, sh_parameter_directory_base} + sh_directory_bytes;

    wire shadow_valid =
        sh_epoch != 0 && sh_job_base != 0 && sh_token_base != 0 && sh_tag_base != 0 &&
        sh_event[31:8] == 0 && sh_model_crc == 32'h83f6cd55 &&
        sh_flags[31:3] == 0 && sh_flags[2:1] == 2'b11 &&
        sh_source_generation != 0 && sh_destination_generation != 0 &&
        sh_source_base[5:0] == 0 && sh_source_begin[5:0] == 0 &&
        sh_source_end[5:0] == 0 && sh_source_end_hi[31:1] == 0 &&
        sh_source_end <= 33'h1_0000_0000 &&
        {1'b0, sh_source_base} >= {1'b0, sh_source_begin} &&
        {1'b0, sh_source_base} < sh_source_end &&
        {1'b0, sh_source_begin} < sh_source_end &&
        sh_destination_base[5:0] == 0 && sh_destination_begin[5:0] == 0 &&
        sh_destination_end[5:0] == 0 && sh_destination_end_hi[31:1] == 0 &&
        sh_destination_end <= 33'h1_0000_0000 &&
        {1'b0, sh_destination_base} >= {1'b0, sh_destination_begin} &&
        {1'b0, sh_destination_base} < sh_destination_end &&
        {1'b0, sh_destination_begin} < sh_destination_end &&
        sh_parameter_directory_base[5:0] == 0 &&
        sh_parameter_count[31:16] == 0 && sh_parameter_count[15:0] != 0 &&
        sh_parameter_count[15:0] <= 16'd173 &&
        sh_directory_end <= 33'h1_0000_0000 &&
        sh_parameter_payload_begin[5:0] == 0 &&
        sh_parameter_payload_end_hi[31:1] == 0 &&
        sh_parameter_payload_end > {1'b0, sh_parameter_payload_begin} &&
        sh_parameter_payload_end <= 33'h1_0000_0000 &&
        sh_load_timeout != 0 && sh_parameter_timeout != 0 &&
        sh_write_timeout != 0 && sh_preaccept_timeout != 0;

    wire backend_idle_healthy = !backend_fault && !fault_seen_q &&
                                !backend_active && backend_all_io_quiet;
    wire frontend_ready = state_q == ST_IDLE && !snapshot_valid_q &&
                          !accepted_q && !result_valid_q &&
                          bridge_error_q == ERROR_NONE && backend_idle_healthy;
    wire [31:0] status_word =
        (frontend_ready            ? 32'h00000001 : 0) |
        (state_q == ST_PENDING     ? 32'h00000002 : 0) |
        (accepted_q                ? 32'h00000004 : 0) |
        (backend_active            ? 32'h00000008 : 0) |
        (done_q                    ? 32'h00000010 : 0) |
        ((backend_fault || fault_seen_q) ? 32'h00000020 : 0) |
        (backend_needs_drain       ? 32'h00000040 : 0) |
        (backend_drain_complete    ? 32'h00000080 : 0) |
        (result_valid_q            ? 32'h00000100 : 0) |
        (preaccept_timeout_q       ? 32'h00000200 : 0);

    wire [31:0] read_address = s_axi_araddr;
    reg [31:0] read_data_comb;
    reg [1:0] read_resp_comb;
    integer read_word_index;
    always @* begin
        read_data_comb = 32'd0;
        read_resp_comb = AXI_OKAY;
        read_word_index = 0;
        if (read_address[31:9] != 0 || read_address[1:0] != 0) begin
            read_resp_comb = AXI_SLVERR;
        end else begin
            case (read_address)
                REG_ID:                 read_data_comb = 32'h5a4e4331;
                REG_ABI_VERSION:        read_data_comb = 32'h00010000;
                REG_CAPABILITIES:       read_data_comb = 32'h0000003f;
                REG_CONTROL:            read_data_comb = 32'd0;
                REG_STATUS:             read_data_comb = status_word;
                REG_BACKEND_FAULT_CODE: read_data_comb = fault_seen_q ?
                                                   {28'd0, fault_code_snapshot_q} :
                                                   {28'd0, backend_fault_code};
                REG_BRIDGE_ERROR:       read_data_comb = bridge_error_q;
                REG_COMMITTED_TILES:    read_data_comb = {24'd0, backend_committed_tiles};
                default: begin
                    if (read_address >= REG_SHADOW_FIRST && read_address <= REG_SHADOW_LAST) begin
                        read_word_index = (read_address - REG_SHADOW_FIRST) >> 2;
                        read_data_comb = shadow_words_q[read_word_index*32 +: 32];
                    end else if (read_address >= REG_RESULT_FIRST && read_address <= REG_RESULT_LAST) begin
                        read_word_index = (read_address - REG_RESULT_FIRST) >> 2;
                        read_data_comb = result_words_q[read_word_index*32 +: 32];
                    end else if (read_address >= 32'h020 && read_address <= 32'h03c) begin
                        read_data_comb = 32'd0;
                    end else if (read_address >= 32'h0ac && read_address <= 32'h0fc) begin
                        read_data_comb = 32'd0;
                    end else if (read_address >= 32'h128 && read_address <= 32'h1fc) begin
                        read_data_comb = 32'd0;
                    end else begin
                        read_resp_comb = AXI_SLVERR;
                    end
                end
            endcase
        end
    end

    wire [31:0] control_value = write_masked_data;
    wire control_onehot = (control_value != 0) &&
                          ((control_value & (control_value - 1'b1)) == 0);
    wire control_bits_valid = (control_value & ~CONTROL_MASK) == 0;
    wire control_well_formed = control_onehot && control_bits_valid;
    wire ctrl_start = write_complete && write_is_control && write_strb != 0 &&
                      control_well_formed && control_value == CONTROL_START;
    wire ctrl_abort = write_complete && write_is_control && write_strb != 0 &&
                      control_well_formed && control_value == CONTROL_ABORT;
    wire ctrl_cancel = write_complete && write_is_control && write_strb != 0 &&
                       control_well_formed && control_value == CONTROL_CANCEL;
    wire ctrl_ack = write_complete && write_is_control && write_strb != 0 &&
                    control_well_formed && control_value == CONTROL_ACK;
    wire ctrl_ack_local = ctrl_ack && state_q == ST_IDLE && !accepted_q &&
                          !result_valid_q && bridge_error_q != ERROR_NONE;
    wire ctrl_ack_success = ctrl_ack && state_q == ST_TERMINAL && accepted_q &&
                            result_valid_q && done_q && backend_all_io_quiet &&
                            !backend_active && !backend_fault;
    wire ctrl_ack_fault = ctrl_ack && state_q == ST_TERMINAL && accepted_q &&
                          result_valid_q && !done_q && fault_seen_q &&
                          backend_fault && backend_all_io_quiet;
    wire ctrl_cancel_legal = ctrl_cancel && state_q == ST_ACCEPTED && accepted_q &&
                             !result_valid_q;
    wire ctrl_abort_legal = ctrl_abort && state_q == ST_PENDING && !accepted_q;
    wire ctrl_start_legal_state = ctrl_start && frontend_ready;
    wire ctrl_start_invalid_shadow = ctrl_start_legal_state && !shadow_valid;
    wire ctrl_start_accepted = ctrl_start_legal_state && shadow_valid;
    wire ctrl_ack_legal = ctrl_ack_local || ctrl_ack_success || ctrl_ack_fault;
    wire ctrl_legal = ctrl_start_accepted || ctrl_start_invalid_shadow ||
                      ctrl_abort_legal || ctrl_cancel_legal || ctrl_ack_legal;
    wire ctrl_invalid_write = write_complete && write_is_control && write_strb != 0 &&
                              (!control_well_formed || !ctrl_legal);
    (* use_dsp = "no" *) wire [31:0] preaccept_count_next = preaccept_count_q + 32'd1;
    wire preaccept_timeout_now = state_q == ST_PENDING &&
        preaccept_count_next >= command_words_q[26*32 +: 32];
    wire backend_handshake = state_q == ST_PENDING && backend_cmd_ready;

    assign s_axi_awready = platform_rst_n && !aw_hold_q && !s_axi_bvalid;
    assign s_axi_wready = platform_rst_n && !w_hold_q && !s_axi_bvalid;
    assign s_axi_arready = platform_rst_n && !s_axi_rvalid;
    assign backend_cmd_words = command_words_q;
    assign backend_cmd_valid = state_q == ST_PENDING;
    assign backend_cancel = backend_cancel_q;
    assign backend_source_lease_valid = snapshot_valid_q && command_words_q[7*32+1];
    assign backend_source_lease_generation = command_words_q[9*32 +: 32];
    assign backend_source_lease_region_begin = command_words_q[10*32 +: 32];
    assign backend_source_lease_region_end = {command_words_q[12*32], command_words_q[11*32 +: 32]};
    assign backend_destination_reservation_valid = snapshot_valid_q && command_words_q[7*32+2];
    assign backend_destination_reservation_generation = command_words_q[14*32 +: 32];
    assign backend_destination_reservation_region_begin = command_words_q[15*32 +: 32];
    assign backend_destination_reservation_region_end = {command_words_q[17*32], command_words_q[16*32 +: 32]};
    assign irq = result_valid_q || bridge_error_q != ERROR_NONE ||
                 (accepted_q && backend_fault) ||
                 (accepted_q && backend_fault && backend_needs_drain);

    integer byte_lane;
    always @(posedge clk) begin
        if (!platform_rst_n) begin
            shadow_words_q <= 864'd0;
        end else if (write_complete && write_is_shadow && write_strb != 0 &&
                     !shadow_locked) begin
            for (byte_lane = 0; byte_lane < 4; byte_lane = byte_lane + 1) begin
                if (write_strb[byte_lane])
                    shadow_words_q[((write_addr - REG_SHADOW_FIRST) >> 2)*32 + byte_lane*8 +: 8]
                        <= write_data[byte_lane*8 +: 8];
            end
        end
    end

    always @(posedge clk) begin
        if (!platform_rst_n) begin
            aw_hold_q <= 1'b0;
            awaddr_hold_q <= 32'd0;
            w_hold_q <= 1'b0;
            wdata_hold_q <= 32'd0;
            wstrb_hold_q <= 4'd0;
            s_axi_bresp <= AXI_OKAY;
            s_axi_bvalid <= 1'b0;
            s_axi_rdata <= 32'd0;
            s_axi_rresp <= AXI_OKAY;
            s_axi_rvalid <= 1'b0;
        end else begin
            if (aw_fire) begin
                aw_hold_q <= 1'b1;
                awaddr_hold_q <= s_axi_awaddr;
            end
            if (w_fire) begin
                w_hold_q <= 1'b1;
                wdata_hold_q <= s_axi_wdata;
                wstrb_hold_q <= s_axi_wstrb;
            end
            if (s_axi_bvalid && s_axi_bready)
                s_axi_bvalid <= 1'b0;
            if (write_complete) begin
                aw_hold_q <= 1'b0;
                w_hold_q <= 1'b0;
                s_axi_bvalid <= 1'b1;
                s_axi_bresp <= AXI_OKAY;
                if (!write_zero_strobe) begin
                    if (!write_addr_aligned ||
                        !(write_is_shadow || write_is_control)) begin
                        s_axi_bresp <= AXI_SLVERR;
                    end else if (write_is_shadow) begin
                        if (shadow_locked)
                            s_axi_bresp <= AXI_SLVERR;
                    end else if (write_is_control) begin
                        if (!control_well_formed || !ctrl_legal)
                            s_axi_bresp <= AXI_SLVERR;
                        else if (ctrl_start_invalid_shadow)
                            s_axi_bresp <= AXI_SLVERR;
                    end
                end
            end

            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1'b1;
                s_axi_rdata <= read_data_comb;
                s_axi_rresp <= read_resp_comb;
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (!platform_rst_n) begin
            command_words_q <= 864'd0;
            result_words_q <= 320'd0;
            success_words_q <= 320'd0;
            state_q <= ST_IDLE;
            snapshot_valid_q <= 1'b0;
            accepted_q <= 1'b0;
            result_valid_q <= 1'b0;
            done_q <= 1'b0;
            preaccept_timeout_q <= 1'b0;
            bridge_error_q <= ERROR_NONE;
            preaccept_count_q <= 32'd0;
            success_pending_q <= 1'b0;
            fault_seen_q <= 1'b0;
            fault_code_snapshot_q <= 4'd0;
            backend_cancel_q <= 1'b0;
        end else begin
            if (ctrl_invalid_write && bridge_error_q == ERROR_NONE)
                bridge_error_q <= ERROR_ILLEGAL_CONTROL;

            if (ctrl_start_invalid_shadow) begin
                command_words_q <= shadow_words_q;
                snapshot_valid_q <= 1'b1;
                if (bridge_error_q == ERROR_NONE)
                    bridge_error_q <= ERROR_INVALID_SHADOW;
            end
            if (ctrl_start_accepted) begin
                command_words_q <= shadow_words_q;
                snapshot_valid_q <= 1'b1;
                state_q <= ST_PENDING;
                accepted_q <= 1'b0;
                result_valid_q <= 1'b0;
                done_q <= 1'b0;
                success_pending_q <= 1'b0;
                preaccept_count_q <= 32'd0;
            end

            if (backend_cancel_q && backend_all_io_quiet)
                backend_cancel_q <= 1'b0;
            if (ctrl_cancel_legal)
                backend_cancel_q <= 1'b1;

            if (state_q == ST_PENDING) begin
                if (backend_handshake) begin
                    accepted_q <= 1'b1;
                    state_q <= ST_ACCEPTED;
                    preaccept_count_q <= 32'd0;
                    // A same-edge abort or accept timeout loses to handshake,
                    // but immediately enters accepted cancellation/drain.
                    if (ctrl_abort_legal || preaccept_timeout_now)
                        backend_cancel_q <= 1'b1;
                end else if (ctrl_abort_legal) begin
                    state_q <= ST_IDLE;
                    preaccept_count_q <= 32'd0;
                    if (bridge_error_q == ERROR_NONE)
                        bridge_error_q <= ERROR_PREACCEPT_ABORT;
                end else if (preaccept_timeout_now) begin
                    state_q <= ST_IDLE;
                    preaccept_count_q <= 32'd0;
                    preaccept_timeout_q <= 1'b1;
                    if (bridge_error_q == ERROR_NONE)
                        bridge_error_q <= ERROR_PREACCEPT_TIMEOUT;
                end else begin
                    preaccept_count_q <= preaccept_count_next;
                end
            end

            if (accepted_q && backend_fault) begin
                if (!fault_seen_q)
                    fault_code_snapshot_q <= backend_fault_code;
                fault_seen_q <= 1'b1;
            end

            if (accepted_q && !result_valid_q) begin
                if (backend_fault || fault_seen_q) begin
                    success_pending_q <= 1'b0;
                    if (backend_all_io_quiet) begin
                        result_words_q[0*32 +: 32] <= command_words_q[0*32 +: 32];
                        result_words_q[1*32 +: 32] <= command_words_q[1*32 +: 32];
                        result_words_q[2*32 +: 32] <= command_words_q[2*32 +: 32] & 32'hff;
                        result_words_q[3*32 +: 32] <= command_words_q[3*32 +: 32];
                        result_words_q[4*32 +: 32] <= command_words_q[4*32 +: 32];
                        result_words_q[5*32 +: 32] <= command_words_q[5*32 +: 32];
                        result_words_q[6*32 +: 32] <= command_words_q[6*32 +: 32];
                        result_words_q[7*32 +: 32] <= command_words_q[14*32 +: 32];
                        result_words_q[8*32 +: 32] <= {24'd0, backend_committed_tiles};
                        result_words_q[9*32 +: 32] <= command_words_q[9*32 +: 32];
                        result_valid_q <= 1'b1;
                        done_q <= 1'b0;
                        state_q <= ST_TERMINAL;
                    end
                end else begin
                    if (backend_producer_complete && !success_pending_q) begin
                        success_words_q[0*32 +: 32] <= command_words_q[0*32 +: 32];
                        success_words_q[1*32 +: 32] <= backend_complete_epoch;
                        success_words_q[2*32 +: 32] <= {24'd0, backend_complete_event};
                        success_words_q[3*32 +: 32] <= backend_complete_model_crc;
                        success_words_q[4*32 +: 32] <= backend_complete_job_base;
                        success_words_q[5*32 +: 32] <= backend_complete_token_base;
                        success_words_q[6*32 +: 32] <= backend_complete_tag_base;
                        success_words_q[7*32 +: 32] <= backend_complete_destination_generation;
                        success_words_q[8*32 +: 32] <= {24'd0, backend_complete_tiles};
                        success_words_q[9*32 +: 32] <= command_words_q[9*32 +: 32];
                        success_pending_q <= 1'b1;
                    end
                    if (success_pending_q && backend_all_io_quiet && !backend_active &&
                        !backend_fault) begin
                        result_words_q <= success_words_q;
                        result_valid_q <= 1'b1;
                        done_q <= 1'b1;
                        state_q <= ST_TERMINAL;
                        success_pending_q <= 1'b0;
                    end
                end
            end

            if (ctrl_ack_local) begin
                bridge_error_q <= ERROR_NONE;
                preaccept_timeout_q <= 1'b0;
                snapshot_valid_q <= 1'b0;
                command_words_q <= command_words_q;
                state_q <= ST_IDLE;
            end else if (ctrl_ack_success || ctrl_ack_fault) begin
                result_valid_q <= 1'b0;
                done_q <= 1'b0;
                accepted_q <= 1'b0;
                snapshot_valid_q <= 1'b0;
                state_q <= ST_IDLE;
                success_pending_q <= 1'b0;
                backend_cancel_q <= 1'b0;
                bridge_error_q <= ERROR_NONE;
                preaccept_timeout_q <= 1'b0;
            end
        end
    end
endmodule

`default_nettype wire
