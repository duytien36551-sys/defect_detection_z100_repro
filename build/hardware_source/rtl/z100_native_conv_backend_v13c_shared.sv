`default_nettype none
// Source-bound native materialized-Conv backend for the epoch200 PIN640 model.
//
// This is a synthesizable component top, not the full graph runtime. It accepts
// one model-ROM Conv event, reads the leased materialized source, configures
// weights from the bounded parameter directory/payload, executes the real V10
// 20-site datapath, and writes every output tile through the AXI64 writer.
// producer_complete means that every tile's physical B response has drained.
// It does not publish the full tensor or mean graph RUN success: the caller
// must commit the complete tensor through its graph ledger and await its ack.
//
// rst_n is a platform reset. It may only be asserted when the AXI fabric is
// also reset or when all_io_quiet is already true. cancel, lost leases, child
// faults, and timeouts never reset the AXI adapters; accepted transactions
// remain owned until RLAST/B is drained. Fault recovery is by coordinated
// platform reset after drain, not by locally abandoning a transaction.
module z100_native_conv_backend_v13c_shared #(
    parameter integer SITES = 12,
    parameter integer SITE_FIFO_DEPTH = 4,
    parameter MAP_FILE = "conv_event_map.hex",
    parameter TILE_FILE = "conv_tiles.hex",
    parameter [31:0] MODEL_CRC = 32'd2213989717
) (
    input wire clk,
    input wire rst_n,
    input wire aux_owner,
    input wire aux_cancel,
    input wire  aux_pool_job_valid,
    output wire  aux_pool_job_ready,
    input wire [31:0] aux_pool_job_epoch,
    input wire [10:0] aux_pool_job_channels,
    input wire [9:0] aux_pool_job_height,
    input wire [9:0] aux_pool_job_width,
    output wire  aux_pool_packed_valid,
    input wire  aux_pool_packed_ready,
    output wire [31:0] aux_pool_packed_epoch,
    output wire [12:0] aux_pool_packed_address,
    output wire [511:0] aux_pool_packed_data,
    output wire  aux_pool_packed_last,
    output wire  aux_pool_done,
    output wire  aux_pool_error,
    output wire [3:0] aux_pool_error_code,
    output wire  aux_pool_active,
    input wire  aux_feature_cfg_begin,
    output wire  aux_feature_cfg_begin_ready,
    input wire  aux_feature_cfg_canonical_order,
    input wire  aux_feature_load_bank,
    input wire  aux_compute_source_bank,
    output wire  aux_feature_load_store_valid,
    output wire  aux_feature_load_loading,
    output wire [31:0] aux_feature_load_active_epoch,
    input wire [31:0] aux_feature_cfg_epoch,
    input wire [10:0] aux_feature_cfg_channels,
    input wire [9:0] aux_feature_cfg_height,
    input wire [9:0] aux_feature_cfg_width,
    input wire [31:0] aux_feature_cfg_word_epoch,
    input wire [12:0] aux_feature_cfg_word_address,
    input wire  aux_feature_cfg_word_last,
    input wire  aux_feature_cfg_word_valid,
    output wire  aux_feature_cfg_word_ready,
    input wire [511:0] aux_feature_cfg_data,
    input wire  aux_feature_cfg_commit,
    output wire  aux_feature_cfg_commit_ready,
    output wire  aux_feature_store_valid,
    output wire  aux_feature_loading,
    output wire [31:0] aux_feature_active_epoch,
    output wire  aux_feature_error_valid,
    output wire [3:0] aux_feature_error_code,

    input wire cmd_valid,
    output wire cmd_ready,
    input wire [31:0] cmd_epoch,
    input wire [7:0] cmd_event,
    input wire [31:0] cmd_model_crc,
    input wire [31:0] cmd_job_base,
    input wire [31:0] cmd_token_base,
    input wire [31:0] cmd_tag_base,
    input wire cmd_first_bank,

    input wire [31:0] cmd_source_base,
    input wire [31:0] cmd_source_generation,
    input wire source_lease_valid,
    input wire [31:0] source_lease_generation,
    input wire [31:0] source_lease_region_begin,
    input wire [32:0] source_lease_region_end,

    input wire [31:0] cmd_destination_base,
    input wire [31:0] cmd_destination_generation,
    input wire destination_reservation_valid,
    input wire [31:0] destination_reservation_generation,
    input wire [31:0] destination_reservation_region_begin,
    input wire [32:0] destination_reservation_region_end,

    input wire [31:0] cmd_parameter_directory_base,
    input wire [15:0] cmd_parameter_count,
    input wire [31:0] cmd_parameter_payload_begin,
    input wire [32:0] cmd_parameter_payload_end,
    input wire [31:0] cmd_load_timeout_cycles,
    input wire [31:0] cmd_parameter_timeout_cycles,
    input wire [31:0] cmd_write_timeout_cycles,
    input wire cancel,

    output wire active,
    output wire fault,
    output wire [3:0] fault_code,
    output wire needs_drain,
    output wire drain_complete,
    output wire all_io_quiet,

    output wire producer_context_valid,
    output wire [15:0] producer_cin,
    output wire [15:0] producer_input_height,
    output wire [15:0] producer_input_width,
    output wire [15:0] producer_cout,
    output wire [15:0] producer_output_height,
    output wire [15:0] producer_output_width,
    output wire [15:0] producer_kernel,
    output wire [15:0] producer_stride,
    output wire [15:0] producer_padding,
    output wire [15:0] producer_parameter_first,
    output wire [7:0] producer_event,

    output wire producer_complete,
    output wire [31:0] producer_complete_epoch,
    output wire [7:0] producer_complete_event,
    output wire [31:0] producer_complete_model_crc,
    output wire [31:0] producer_complete_job_base,
    output wire [31:0] producer_complete_token_base,
    output wire [31:0] producer_complete_tag_base,
    output wire [31:0] producer_complete_destination_generation,
    output wire [7:0] producer_complete_tiles,

    output wire [1:0] diagnostic_read_kind,
    output wire diagnostic_load_active,diagnostic_compute_active,
    output wire diagnostic_write_active,
    output wire diagnostic_mac_good_group,
    output wire [10:0] diagnostic_mac_good_slots,
    output wire diagnostic_mac_starve,diagnostic_mac_output_stall,
    output wire diagnostic_residency_hit,diagnostic_residency_miss,

    output wire [5:0] m_axi_arid,
    output wire [31:0] m_axi_araddr,
    output wire [3:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [5:0] m_axi_rid,
    input wire [63:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast,
    input wire m_axi_rvalid,
    output wire m_axi_rready,

    output wire [5:0] m_axi_awid,
    output wire [31:0] m_axi_awaddr,
    output wire [3:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output wire m_axi_awvalid,
    input wire m_axi_awready,
    output wire [5:0] m_axi_wid,
    output wire [63:0] m_axi_wdata,
    output wire [7:0] m_axi_wstrb,
    output wire m_axi_wlast,
    output wire m_axi_wvalid,
    input wire m_axi_wready,
    input wire [5:0] m_axi_bid,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready
);
    // The final rounded directory read must fit in the32-bit address space.
    wire [32:0] command_directory_bytes = (({17'd0,cmd_parameter_count}+33'd1)>>1)<<6;
    wire [32:0] command_directory_end = {1'b0,cmd_parameter_directory_base}+command_directory_bytes;
    wire command_resources_valid = source_lease_valid &&
        source_lease_generation == cmd_source_generation &&
        cmd_source_generation != 0 && cmd_source_base[5:0] == 0 &&
        {1'b0,cmd_source_base} >= {1'b0,source_lease_region_begin} &&
        source_lease_region_begin[5:0] == 0 && source_lease_region_end[5:0] == 0 &&
        source_lease_region_end <= 33'h1_0000_0000 &&
        destination_reservation_valid &&
        destination_reservation_generation == cmd_destination_generation &&
        cmd_destination_generation != 0 && cmd_destination_base[5:0] == 0 &&
        {1'b0,cmd_destination_base} >= {1'b0,destination_reservation_region_begin} &&
        destination_reservation_region_begin[5:0] == 0 &&
        destination_reservation_region_end[5:0] == 0 &&
        destination_reservation_region_end <= 33'h1_0000_0000 &&
        cmd_parameter_directory_base[5:0] == 0 &&
        cmd_parameter_count != 0 && cmd_parameter_count <= 16'd173 &&
        command_directory_end <= 33'h1_0000_0000 &&
        cmd_parameter_payload_begin[5:0] == 0 &&
        cmd_parameter_payload_end > {1'b0,cmd_parameter_payload_begin} &&
        cmd_parameter_payload_end <= 33'h1_0000_0000 &&
        cmd_load_timeout_cycles != 0 && cmd_parameter_timeout_cycles != 0 &&
        cmd_write_timeout_cycles != 0;
    reg [31:0] epoch_q, model_crc_q, job_base_q, token_base_q, tag_base_q;
    reg [7:0] event_q;
    reg first_bank_q;
    reg [31:0] source_base_q, source_generation_q;
    reg [31:0] source_region_begin_q;
    reg [32:0] source_region_end_q;
    reg [31:0] destination_base_q, destination_generation_q;
    reg [31:0] destination_region_begin_q;
    reg [32:0] destination_region_end_q;
    reg [31:0] parameter_directory_base_q, parameter_payload_begin_q;
    reg [15:0] parameter_count_q;
    reg [32:0] parameter_payload_end_q;
    reg [31:0] load_timeout_q, parameter_timeout_q, write_timeout_q;
    reg command_active_q;
    wire event_cmd_ready, event_active, event_done, event_fault;
    wire [3:0] event_fault_code;
    wire event_child_cancel, event_needs_drain;
    wire [31:0] event_epoch, load_job_tag, tile_job_tag, tile_token_base, tile_tag_base;
    wire [9:0] load_input_y, load_input_rows, tile_input_y, tile_input_rows;
    wire [9:0] tile_output_y, tile_output_rows;
    wire load_valid, load_bank, tile_valid, tile_bank;
    wire [15:0] context_cin, context_ih, context_iw, context_cout;
    wire [15:0] context_oh, context_ow, context_kernel, context_stride, context_padding;
    wire [15:0] context_parameter_first;
    wire [7:0] context_event;
    wire context_valid;
    wire [7:0] committed_tiles;
    wire load_done, load_committed, load_fault;
    wire [31:0] load_done_epoch;
    wire load_done_bank;
    wire tile_done, tile_fault;
    wire [31:0] tile_done_epoch, tile_done_job;
    wire tile_done_bank;
    wire lease_matches = source_lease_valid &&
        source_lease_generation == source_generation_q &&
        source_lease_region_begin == source_region_begin_q &&
        source_lease_region_end == source_region_end_q;
    wire reservation_matches = destination_reservation_valid &&
        destination_reservation_generation == destination_generation_q &&
        destination_reservation_region_begin == destination_region_begin_q &&
        destination_reservation_region_end == destination_region_end_q;
    // periph_flat_v2: the tensor range/overlap check is a 5-stage pipeline over
    // registered inputs (context_* from the ROM scheduler, *_q command regs).
    // Consumers only see context_valid after the check finished clean; the ROM
    // scheduler's ADMIT step waits for range_ok. A bad range raises
    // context_range_bad (registered) exactly as before, only 5 cycles later and
    // before any load/tile/parameter command could have been issued.
    // Widths are bounded by the ROM scheduler's response checks
    // (cin,cout<=1024; heights,widths<=640); out-of-bound values flag bad.
    wire context_valid_raw;
    reg [2:0] range_cnt_q;
    reg [8:0] rs1_sg, rs1_og;
    reg [5:0] rs1_sx, rs1_ox;
    reg [9:0] rs1_ih, rs1_oh;
    reg rs1_oversize;
    reg [18:0] rs2_sp, rs2_op;
    reg [5:0] rs2_sx, rs2_ox;
    reg rs2_oversize;
    reg [24:0] rs3_sw, rs3_ow;
    reg rs3_oversize;
    reg [32:0] rs4_send, rs4_oend, rs4_dend;
    reg rs4_oversize;
    reg rs5_bad;
    wire range_done = command_active_q && context_valid_raw && range_cnt_q == 3'd5;
    wire range_ok = range_done && !rs5_bad;
    wire context_range_bad = range_done && rs5_bad;
    assign context_valid = context_valid_raw && range_ok;
    wire [32:0] directory_bytes_q = (({17'd0,parameter_count_q}+33'd1)>>1)<<6;
    always @(posedge clk) begin
        if (!rst_n || !command_active_q || !context_valid_raw) range_cnt_q <= 3'd0;
        else if (range_cnt_q != 3'd5) range_cnt_q <= range_cnt_q + 3'd1;
        // stage 1: group/xword counts
        rs1_sg <= (context_cin + 16'd3) >> 2;
        rs1_og <= (context_cout + 16'd3) >> 2;
        rs1_sx <= (context_iw + 16'd15) >> 4;
        rs1_ox <= (context_ow + 16'd15) >> 4;
        rs1_ih <= context_ih[9:0];
        rs1_oh <= context_oh[9:0];
        rs1_oversize <= context_cin > 16'd1024 || context_cout > 16'd1024 ||
                        context_ih > 16'd640 || context_iw > 16'd640 ||
                        context_oh > 16'd640 || context_ow > 16'd640;
        // stage 2/3: words = groups * rows * xwords
        rs2_sp <= rs1_sg * rs1_ih;  rs2_op <= rs1_og * rs1_oh;
        rs2_sx <= rs1_sx;           rs2_ox <= rs1_ox;   rs2_oversize <= rs1_oversize;
        rs3_sw <= rs2_sp * rs2_sx;  rs3_ow <= rs2_op * rs2_ox;  rs3_oversize <= rs2_oversize;
        // stage 4: half-open ends (64-byte words)
        rs4_send <= {1'b0,source_base_q} + {2'd0,rs3_sw,6'd0};
        rs4_oend <= {1'b0,destination_base_q} + {2'd0,rs3_ow,6'd0};
        rs4_dend <= {1'b0,parameter_directory_base_q} + directory_bytes_q;
        rs4_oversize <= rs3_oversize;
        // stage 5: region and overlap verdict
        rs5_bad <= rs4_oversize ||
            source_base_q < source_region_begin_q || rs4_send > source_region_end_q ||
            destination_base_q < destination_region_begin_q || rs4_oend > destination_region_end_q ||
            ({1'b0,source_base_q} < rs4_oend && {1'b0,destination_base_q} < rs4_send) ||
            ({1'b0,destination_base_q} < parameter_payload_end_q && {1'b0,parameter_payload_begin_q} < rs4_oend) ||
            ({1'b0,destination_base_q} < rs4_dend && {1'b0,parameter_directory_base_q} < rs4_oend);
    end
    // periph_flat_v3 (census 20261030T094622Z): lease/reservation matches are
    // registered. The 32/33-bit MMIO-vs-command compares fed datapath_cancel
    // and the prefetch source_leased -> child_cancel -> load abort -> feature
    // handshake loop (31 levels). lease_ok_q(t) = lease(t-1) matches the
    // command registers as they are at t: on the accept edge it is computed
    // from the command being accepted (regions are copied from the lease, so
    // only valid + generation can differ). Effect: a host lease revocation is
    // seen one cycle later; a mismatched generation still faults on the first
    // active cycle, exactly as before.
    reg lease_ok_q, reservation_ok_q;
    always @(posedge clk) begin
        if (!rst_n) begin
            lease_ok_q <= 1'b0; reservation_ok_q <= 1'b0;
        end else if (cmd_valid && cmd_ready) begin
            lease_ok_q <= source_lease_valid && source_lease_generation == cmd_source_generation;
            reservation_ok_q <= destination_reservation_valid &&
                destination_reservation_generation == cmd_destination_generation;
        end else begin
            lease_ok_q <= lease_matches; reservation_ok_q <= reservation_matches;
        end
    end
    wire resource_lost = command_active_q && (!lease_ok_q || !reservation_ok_q);
    wire datapath_cancel = command_active_q &&
        (cancel || event_child_cancel || resource_lost || context_range_bad);
    wire range_fault = command_active_q && context_range_bad;
    wire effective_source_leased = command_active_q && lease_ok_q && !range_fault;
    wire effective_destination_reserved = command_active_q && reservation_ok_q && !range_fault;
    wire load_cmd_ready, load_active, load_ctrl_fault, load_result_committed;
    wire [3:0] load_ctrl_fault_code;
    wire [31:0] load_epoch, load_generation, load_address;
    wire [10:0] load_channels;
    wire [9:0] load_height, load_width;
    wire [13:0] load_words, load_block_words, load_word_base;
    wire feature_begin, feature_begin_ready, feature_order_config, feature_order_config_ready;
    wire feature_commit, feature_commit_ready;
    wire pf_reader_command, pf_reader_command_ready, pf_reader_busy, pf_reader_done;
    wire pf_reader_fault, pf_reader_cancel, pf_reader_clear;
    wire [3:0] pf_reader_fault_code;
    wire pf_reader_valid, pf_reader_ready, pf_reader_last;
    wire [31:0] pf_reader_epoch;
    wire [12:0] pf_reader_index;
    wire [511:0] pf_reader_data;
    wire pf_order_valid, pf_order_ready, pf_order_last, pf_order_active, pf_order_done;
    wire pf_order_error;
    wire [1:0] pf_order_error_code;
    wire [31:0] pf_order_epoch;
    wire [12:0] pf_order_index, pf_order_address;
    wire [511:0] pf_order_data;
    wire feature_store_valid, feature_loading;
    wire [31:0] feature_active_epoch;
    wire feature_error_valid;
    wire [3:0] feature_error_code;
    // periph_flat_v3 (census 20261030T092323Z): the backend consumes a
    // registered copy of the feature-store error. The raw error is the end of
    // a 4-level OR tree inside the store; feeding it straight into fault ->
    // child_cancel -> load abort -> feature_begin -> store ready -> FSM made a
    // 31-level path. The store already masks all of its own readies in the
    // error cycle, so the one-edge delay only postpones the cancel of the
    // other units by one cycle. Cleared by the same cancel the core receives.
    reg feature_error_q;
    reg [3:0] feature_error_code_q;
    wire [31:0] feature_load_active_epoch;
    wire feature_load_store_valid, feature_load_loading;
    reg completed_load_bank_q;
    wire [5:0] pf_arid;
    wire [31:0] pf_araddr;
    wire [3:0] pf_arlen;
    wire [2:0] pf_arsize;
    wire [1:0] pf_arburst;
    wire pf_arvalid, pf_arready, pf_rready;
    wire pf_rvalid;
    wire [5:0] pf_rid;
    wire [63:0] pf_rdata;
    wire [1:0] pf_rresp;
    wire pf_rlast;
    wire [13:0] pf_global_index = load_word_base + {1'b0,pf_reader_index};
    wire [31:0] feature_cfg_epoch = load_epoch;
    wire [10:0] feature_cfg_channels = load_channels;
    wire [9:0] feature_cfg_height = load_height, feature_cfg_width = load_width;
    wire [31:0] feature_cfg_word_epoch = pf_order_epoch;
    wire [12:0] feature_cfg_word_address = pf_order_address;
    wire feature_cfg_word_last = pf_order_last;
    wire feature_cfg_word_valid = load_active && pf_order_valid;
    wire [511:0] feature_cfg_data = pf_order_data;
    wire feature_cfg_canonical_order = 1'b0;
    wire feature_load_bank = load_bank;
    wire [31:0] pack_cfg_epoch, pack_cfg_token_base;
    wire [10:0] pack_cfg_channels;
    wire [9:0] pack_cfg_height, pack_cfg_width;
    wire pack_cfg_valid, pack_cfg_ready;
    wire feature_cfg_begin_ready_v10, feature_cfg_word_ready, feature_cfg_commit_ready_v10;
    wire compute_source_bank = tile_bank;
    wire window_valid, core_window_ready;
    wire [31:0] window_epoch, window_tag;
    wire [13:0] window_row_address;
    wire signed [11:0] window_first_x;
    wire [10:0] window_input_width, window_output_remaining;
    wire [4:0] window_sites;
    wire [3:0] window_channel_mask;
    wire window_stride_two, window_y_valid;
    wire mac_cfg_begin, mac_cfg_begin_ready;
    wire [31:0] mac_cfg_epoch;
    wire [10:0] mac_cfg_groups;
    wire mac_cfg_weight_valid, mac_cfg_weight_ready, mac_cfg_bias_valid, mac_cfg_bias_ready, mac_cfg_commit, mac_cfg_commit_ready;
    wire [1023:0] mac_cfg_weights, mac_cfg_bias;
    wire mac_weights_valid, mac_error_valid;
    wire [31:0] mac_weights_epoch;
    wire [2:0] mac_error_code;
    wire run_valid, core_run_ready;
    wire [31:0] run_epoch, run_token;
    wire [5:0] run_lanes;
    wire [4:0] run_sites;
    wire stream_valid, stream_ready, stream_last;
    wire [31:0] stream_token;
    wire [639:0] stream_data;
    wire [31:0] response_tag;
    wire [79:0] response_mask;
    wire req_cfg_begin, req_cfg_begin_ready;
    wire [31:0] req_cfg_epoch;
    wire [5:0] req_cfg_lanes, req_cfg_shift;
    wire req_cfg_word_valid, req_cfg_word_ready, req_cfg_commit, req_cfg_commit_ready;
    wire [30:0] req_cfg_multiplier;
    wire req_cfg_error, req_input_error;
    wire unary_cfg_begin, unary_cfg_begin_ready;
    wire [31:0] unary_cfg_epoch;
    wire unary_cfg_word_valid, unary_cfg_word_ready, unary_cfg_commit, unary_cfg_commit_ready;
    wire [7:0] unary_cfg_data;
    wire unary_error_valid, unary_store_valid, unary_loading;
    wire [2:0] unary_error_code;
    wire [31:0] unary_active_epoch;
    wire raw_valid, raw_ready, raw_last;
    wire [31:0] raw_token, raw_overflow;
    wire [4:0] raw_site;
    wire [5:0] raw_lanes;
    wire [1023:0] raw_data;
    wire mac_diagnostic_active,mac_diagnostic_good_group;
    wire [10:0] mac_diagnostic_good_slots;
    wire mac_diagnostic_starve,mac_diagnostic_output_stall;
    wire post_valid, post_ready, post_last;
    wire [31:0] post_epoch, post_token;
    wire [4:0] post_site;
    wire [5:0] post_lanes;
    wire [255:0] post_data;
    wire metadata_error;
    wire packed_valid, packed_ready, packed_last, pack_done, pack_error_valid, pack_active;
    wire [31:0] packed_epoch;
    wire [12:0] packed_address;
    wire [511:0] packed_data;
    wire [2:0] pack_error_code;
    wire tile_cmd_ready, tile_active, tile_fault_internal, tile_needs_drain;
    wire [3:0] tile_fault_internal_code;
    wire pack_valid, pack_ready, parameter_valid, parameter_ready;
    // Parameter residency is a private handshake optimization.  The
    // directory/reader remain the physical-transfer owner on a miss; a hit
    // only publishes the already-configured parameter job to tile control.
    wire resident_cmd_valid, resident_cmd_ready;
    wire [31:0] resident_cmd_epoch, resident_cmd_event, resident_cmd_generation;
    wire [15:0] resident_cmd_job;
    wire resident_downstream_cmd_valid;
    wire [31:0] resident_downstream_cmd_epoch, resident_downstream_cmd_event;
    wire [31:0] resident_downstream_cmd_generation;
    wire [15:0] resident_downstream_cmd_job;
    wire resident_downstream_done_ready;
    wire resident_done_valid, resident_done_error;
    wire [31:0] resident_done_epoch, resident_done_event, resident_done_generation;
    wire [15:0] resident_done_job;
    wire resident_active, resident_fault;
    wire [2:0] resident_fault_code;
    wire [31:0] tile_epoch, pack_token_q, tile_job_q;
    wire [10:0] pack_channels;
    wire [9:0] pack_height, pack_width;
    wire [15:0] parameter_job;
    wire parameter_done_valid, parameter_done_ready, parameter_done_error;
    wire row_valid, row_ready, row_done_valid, row_done_ready;
    wire [31:0] row_token_base, row_tag_base;
    wire [10:0] row_channels;
    wire [9:0] row_input_width, row_output_width;
    wire [1:0] row_kernel, row_stride, row_padding;
    wire [5:0] row_lanes;
    wire [13:0] row_bank_words, row_plane_stride;
    wire [41:0] row_ky_bases;
    wire [2:0] row_y_valid;
    wire [31:0] row_done_epoch, row_done_last_token;
    wire row_done_error;
    wire publish_valid, publish_ready, publish_error;
    wire [31:0] publish_epoch, publish_tag;
    wire tile_child_cancel;
    wire scheduler_done, scheduler_abort, scheduler_fault, scheduler_active, scheduler_post_ready;
    wire [2:0] scheduler_fault_code;
    reg [31:0] scheduler_last_post_epoch, scheduler_last_post_token;
    wire scheduler_run_valid, scheduler_run_ready, scheduler_window_valid, scheduler_window_ready;
    wire [31:0] scheduler_run_epoch, scheduler_run_token;
    wire [5:0] scheduler_run_lanes;
    wire [4:0] scheduler_run_sites;
    wire [31:0] scheduler_window_epoch, scheduler_window_tag;
    wire [13:0] scheduler_window_row_address;
    wire signed [11:0] scheduler_window_first_x;
    wire [10:0] scheduler_window_input_width, scheduler_window_output_remaining;
    wire [4:0] scheduler_window_sites;
    wire [3:0] scheduler_window_channel_mask;
    wire scheduler_window_stride_two, scheduler_window_y_valid;
    wire [10:0] pd_groups;
    wire [5:0] pd_lanes;
    wire [31:0] pd_weights, pd_bias, pd_factors, pd_unary;
    wire parameter_job_valid, parameter_job_ready, parameter_active, parameter_fault, parameter_done;
    wire [3:0] parameter_fault_code;
    wire parameter_reader_command, parameter_reader_command_ready, parameter_reader_busy, parameter_reader_fault;
    wire parameter_reader_cancel, parameter_reader_clear, parameter_reader_valid, parameter_reader_ready;
    wire parameter_reader_last;
    wire [31:0] parameter_reader_epoch, parameter_reader_address, parameter_result_epoch;
    wire [13:0] parameter_reader_words;
    wire [12:0] parameter_reader_index;
    wire [511:0] parameter_reader_data;
    wire cfg_valid, cfg_ready, cfg_response_valid, cfg_response_ready, cfg_response_error;
    wire [3:0] cfg_operation;
    wire [31:0] cfg_epoch, cfg_tag, cfg_index, cfg_response_tag;
    wire [10:0] cfg_groups;
    wire [5:0] cfg_lanes;
    wire [1023:0] cfg_data;
    wire bridge_fault, bridge_configured, bridge_child_cancel;
    wire [1023:0] bridge_mac_data;
    wire [31:0] bridge_cfg_epoch;
    wire [10:0] bridge_cfg_groups;
    wire [5:0] bridge_cfg_lanes;
    wire directory_request, directory_ready, directory_active, directory_fault, directory_done;
    wire [3:0] directory_fault_code;
    wire directory_reader_command, directory_reader_command_ready, directory_reader_busy, directory_reader_fault;
    wire directory_reader_cancel, directory_reader_clear, directory_reader_valid, directory_reader_ready;
    wire directory_reader_last;
    wire [31:0] directory_reader_epoch, directory_reader_address, directory_result_epoch;
    wire [13:0] directory_reader_words;
    wire [12:0] directory_reader_index;
    wire [511:0] directory_reader_data;
    wire directory_descriptor_valid, directory_descriptor_ready;
    wire [31:0] directory_descriptor_epoch, directory_descriptor_tag;
    wire [15:0] directory_descriptor_job;
    wire [31:0] directory_descriptor_weights, directory_descriptor_bias;
    wire [31:0] directory_descriptor_factors, directory_descriptor_unary;
    wire parameter_identity_ok = directory_descriptor_epoch == event_epoch &&
        directory_descriptor_tag == tile_job_q && directory_descriptor_job == parameter_job;
    wire datapath_fault = feature_error_q || mac_error_valid || req_cfg_error || req_input_error ||
        unary_error_valid || metadata_error || pack_error_valid || pf_order_error;
    wire directory_consumer_idle = !parameter_active && parameter_job_ready && !parameter_fault;
    wire [5:0] directory_arid, parameter_arid, merged_arid;
    wire [31:0] directory_araddr, parameter_araddr, merged_araddr;
    wire [3:0] directory_arlen, parameter_arlen, merged_arlen;
    wire [2:0] directory_arsize, parameter_arsize, merged_arsize;
    wire [1:0] directory_arburst, parameter_arburst, merged_arburst;
    wire directory_arvalid, directory_arready, directory_rready;
    wire parameter_arvalid, parameter_arready, parameter_rready;
    wire merged_arvalid, merged_arready, merged_rready;
    wire directory_rvalid, directory_rlast, parameter_rvalid, parameter_rlast;
    wire [5:0] directory_rid, parameter_rid;
    wire [63:0] directory_rdata, parameter_rdata;
    wire [1:0] directory_rresp, parameter_rresp;
    wire [11:0] dp_s_rid;
    wire [127:0] dp_s_rdata;
    wire [3:0] dp_s_rresp;
    wire [1:0] dp_s_arready, dp_s_rvalid, dp_s_rlast;
    wire dp_active, dp_active_owner, dp_protocol_fault;
    wire [5:0] merged_rid;
    wire [63:0] merged_rdata;
    wire [1:0] merged_rresp;
    wire merged_rlast, merged_rvalid;
    wire [11:0] physical_s_rid;
    wire [127:0] physical_s_rdata;
    wire [3:0] physical_s_rresp;
    wire [1:0] physical_s_arready, physical_s_rvalid, physical_s_rlast;
    wire physical_active, physical_active_owner, physical_protocol_fault;
    wire write_command, write_command_ready, write_active, write_fault, write_done, write_committed;
    wire [3:0] write_fault_code;
    wire [31:0] write_epoch, write_generation, write_address, write_writer_epoch;
    wire [10:0] write_channels;
    wire [9:0] write_height, write_width;
    wire write_order_config, write_order_config_ready, write_order_done;
    wire write_packed_valid, write_packed_ready, write_packed_last;
    wire [31:0] write_packed_epoch;
    wire [12:0] write_packed_index;
    wire [511:0] write_packed_data;
    wire write_writer_valid, write_writer_ready, write_writer_last, write_writer_done, write_writer_busy;
    wire write_writer_fault, write_codec_error, write_semantic_cancel, write_writer_cancel, write_writer_clear;
    wire [13:0] write_words;
    wire [12:0] write_writer_index;
    wire [511:0] write_writer_data;
    wire [31:0] write_writer_address;
    wire [31:0] write_writer_input_epoch;
    wire write_writer_command, write_writer_command_ready;
    wire output_order_input_ready;
    wire [5:0] output_awid, output_wid;
    wire [31:0] output_awaddr;
    wire [3:0] output_awlen;
    wire [2:0] output_awsize;
    wire [1:0] output_awburst;
    wire output_awvalid, output_wvalid, output_wlast, output_bready;
    wire [63:0] output_wdata;
    wire [7:0] output_wstrb;
    wire output_writer_busy, output_writer_done, output_writer_fault;
    wire [3:0] output_writer_fault_code;
    wire load_io_quiet = !pf_reader_busy && !pf_order_active;
    wire write_io_quiet = !output_writer_busy;
    // The external lease/reservation metadata must match the command and remain
    // stable through completion. The containing runtime owns actual publication.


























































    assign cmd_ready = event_cmd_ready && command_resources_valid && !cancel && !fault;

    z100_conv_rom_prefetch_v2 #(
        .MAP_FILE(MAP_FILE), .TILE_FILE(TILE_FILE), .MODEL_CRC(MODEL_CRC)
    ) event_rom_prefetch (
        .clk(clk), .rst_n(rst_n), .cancel(cancel || context_range_bad),
        .recover(1'b0), .recovery_drained(1'b0),
        .cmd_valid(cmd_valid && command_resources_valid && !cancel && !fault),
        .cmd_ready(event_cmd_ready), .cmd_epoch(cmd_epoch), .cmd_event(cmd_event),
        .cmd_model_crc(cmd_model_crc), .cmd_job_base(cmd_job_base),
        .cmd_token_base(cmd_token_base), .cmd_tag_base(cmd_tag_base),
        .cmd_first_bank(cmd_first_bank),
        .source_leased(effective_source_leased),
        .destination_reserved(effective_destination_reserved),
        .load_valid(load_valid), .load_ready(load_cmd_ready), .load_bank(load_bank),
        .load_job_tag(load_job_tag), .load_input_y(load_input_y),
        .load_input_rows(load_input_rows), .load_done(load_done),
        .load_committed(load_committed), .load_fault(load_fault),
        .load_epoch(load_done_epoch), .load_done_bank(load_done_bank),
        .tile_valid(tile_valid), .tile_ready(tile_cmd_ready), .tile_bank(tile_bank),
        .tile_job_tag(tile_job_tag), .tile_token_base(tile_token_base),
        .tile_tag_base(tile_tag_base), .tile_input_y(tile_input_y),
        .tile_input_rows(tile_input_rows), .tile_output_y(tile_output_y),
        .tile_output_rows(tile_output_rows), .tile_done(tile_done),
        .tile_fault(tile_fault), .tile_done_epoch(tile_done_epoch),
        .tile_done_job(tile_done_job), .tile_done_bank(tile_done_bank),
        .load_quiet(load_io_quiet), .tile_write_quiet(write_io_quiet),
        .all_io_quiet(all_io_quiet), .producer_context_valid(context_valid_raw), .admit_ok(range_ok),
        .producer_cin(context_cin), .producer_input_height(context_ih),
        .producer_input_width(context_iw), .producer_cout(context_cout),
        .producer_output_height(context_oh), .producer_output_width(context_ow),
        .producer_kernel(context_kernel), .producer_stride(context_stride),
        .producer_padding(context_padding), .producer_parameter_first(context_parameter_first),
        .producer_event(context_event), .active_epoch(event_epoch), .active(event_active),
        .done(event_done), .fault(event_fault), .fault_code(event_fault_code),
        .child_cancel(event_child_cancel), .needs_drain(event_needs_drain),
        .committed_tiles(committed_tiles)
    );

    assign producer_context_valid = context_valid;
    assign producer_cin = context_cin;
    assign producer_input_height = context_ih;
    assign producer_input_width = context_iw;
    assign producer_cout = context_cout;
    assign producer_output_height = context_oh;
    assign producer_output_width = context_ow;
    assign producer_kernel = context_kernel;
    assign producer_stride = context_stride;
    assign producer_padding = context_padding;
    assign producer_parameter_first = context_parameter_first;
    assign producer_event = context_event;
    assign producer_complete = event_done;
    assign producer_complete_tiles = committed_tiles;





























    z100_native_materialized_load_control materialized_load (
        .clk(clk), .rst_n(rst_n), .cmd_valid(load_valid), .cmd_ready(load_cmd_ready),
        .cmd_epoch(event_epoch), .cmd_source_generation(source_generation_q),
        .cmd_source_address(source_base_q), .cmd_timeout_cycles(load_timeout_q),
        .cmd_channels(context_cin[10:0]), .cmd_full_height(context_ih[9:0]),
        .cmd_width(context_iw[9:0]), .cmd_first_row(load_input_y),
        .cmd_height(load_input_rows), .cmd_source_committed(effective_source_leased),
        .cmd_source_is_materialized(1'b1), .abort(datapath_cancel), .recover(1'b0),
        .active(load_active), .fault(load_ctrl_fault), .fault_code(load_ctrl_fault_code),
        .done(load_done), .result_committed(load_result_committed), .epoch(load_epoch),
        .source_generation(load_generation), .channels(load_channels), .height(load_height),
        .width(load_width), .total_words(load_words), .block_words(load_block_words),
        .block_word_base(load_word_base), .feature_begin(feature_begin),
        .feature_begin_ready(feature_begin_ready), .order_config(feature_order_config),
        .order_config_ready(feature_order_config_ready), .order_done(pf_order_done),
        .feature_commit(feature_commit), .feature_commit_ready(feature_commit_ready),
        .reader_command(pf_reader_command), .reader_command_ready(pf_reader_command_ready),
        .reader_address(load_address), .reader_done(pf_reader_done),
        .reader_busy(pf_reader_busy), .reader_fault(pf_reader_fault),
        .pipeline_error(pf_order_error || feature_error_q),
        .semantic_cancel(), .reader_cancel(pf_reader_cancel),
        .reader_clear_fault(pf_reader_clear)
    );
    assign load_committed = load_result_committed;
    assign load_done_epoch = load_epoch;

    always @(posedge clk) begin
        if (!rst_n) completed_load_bank_q <= 1'b0;
        else if (load_valid && load_cmd_ready) completed_load_bank_q <= load_bank;
    end
    assign load_done_bank = completed_load_bank_q;
    assign load_fault = load_ctrl_fault || pf_reader_fault || pf_order_error || feature_error_q;












    z100_native_axi64_reader source_reader (
        .clk(clk), .rst_n(rst_n), .cmd_valid(pf_reader_command),
        .cmd_ready(pf_reader_command_ready), .cmd_epoch(load_epoch),
        .cmd_address(load_address), .cmd_word_count(load_block_words),
        .cancel(pf_reader_cancel), .timeout(1'b0), .clear_fault(pf_reader_clear),
        .busy(pf_reader_busy), .done(pf_reader_done), .fault(pf_reader_fault),
        .fault_code(pf_reader_fault_code), .out_valid(pf_reader_valid),
        .out_ready(pf_reader_ready), .out_epoch(pf_reader_epoch),
        .out_index(pf_reader_index), .out_data(pf_reader_data),
        .out_last(pf_reader_last), .m_axi_arid(pf_arid), .m_axi_araddr(pf_araddr),
        .m_axi_arlen(pf_arlen), .m_axi_arsize(pf_arsize), .m_axi_arburst(pf_arburst),
        .m_axi_arvalid(pf_arvalid), .m_axi_arready(pf_arready), .m_axi_rid(pf_rid),
        .m_axi_rdata(pf_rdata), .m_axi_rresp(pf_rresp), .m_axi_rlast(pf_rlast),
        .m_axi_rvalid(pf_rvalid), .m_axi_rready(pf_rready)
    );

    z100_native_stream_order feature_order (
        .clk(clk), .rst_n(rst_n), .cancel(load_ctrl_fault || datapath_cancel),
        .cfg_valid(feature_order_config), .cfg_ready(feature_order_config_ready),
        .cfg_epoch(load_epoch), .cfg_write_order(1'b0), .cfg_channels(load_channels),
        .cfg_height(load_height), .cfg_width(load_width),
        .in_valid(pf_reader_valid), .in_ready(pf_reader_ready), .in_epoch(pf_reader_epoch),
        .in_index(pf_global_index[12:0]), .in_address(13'd0),
        .in_last(pf_global_index + 14'd1 == load_words), .in_data(pf_reader_data),
        .out_valid(pf_order_valid), .out_ready(feature_cfg_word_ready),
        .out_epoch(pf_order_epoch), .out_index(pf_order_index),
        .out_address(pf_order_address), .out_last(pf_order_last), .out_data(pf_order_data),
        .active(pf_order_active), .done(pf_order_done), .error_valid(pf_order_error),
        .error_code(pf_order_error_code)
    );










































































    // periph_flat_v3: two-entry register slice on the core's feature-word
    // input (after the Conv/Pool owner mux). It cuts the combinational
    // valid/ready loop reader -> stream order -> feature store -> ready ->
    // reader. Begin and commit are only passed to the core while the slice is
    // empty, so a commit can never overtake a buffered word. The slice is
    // flushed by the same cancel the core receives.
    wire core_feature_cfg_begin_ready, core_feature_cfg_word_ready, core_feature_cfg_commit_ready;
    wire fw_in_valid = aux_owner ? aux_feature_cfg_word_valid : feature_cfg_word_valid;
    wire [557:0] fw_in_data = aux_owner ?
        {aux_feature_cfg_word_epoch, aux_feature_cfg_word_address, aux_feature_cfg_word_last, aux_feature_cfg_data} :
        {feature_cfg_word_epoch, feature_cfg_word_address, feature_cfg_word_last, feature_cfg_data};
    wire fw_out_valid;
    wire [557:0] fw_out_bus;
    wire [31:0] fw_out_epoch = fw_out_bus[557:526];
    wire [12:0] fw_out_address = fw_out_bus[525:513];
    wire fw_out_last = fw_out_bus[512];
    wire [511:0] fw_out_data = fw_out_bus[511:0];
    wire core_cancel = datapath_cancel || (aux_owner && aux_cancel);
    // periph_flat_v3 (census 20261030T101645Z): the compute core receives a
    // registered cancel. core_cancel is the end of the backend fault OR tree
    // + prefetch child_cancel (8-9 levels) and fanned out to ~22.5k core
    // flip-flops; through the store's command admission it also closed the
    // cancel -> begin_ready -> load FSM loop (27 levels). The core is now
    // cancelled one cycle after the backend units. That cycle is harmless:
    // every producer outside the core is cancelled at the same edge as before
    // (FSM priority / valid gated by its own cancel), so whatever the core
    // accepts or emits in that cycle is discarded when its own cancel arrives.
    // cancel only occurs on faults and host cancel (both need a reset before
    // the next job), never in a successful job. The core-side slices and
    // registers below are cleared during both cycles (core_cancel_any).
    (* max_fanout = 400 *) reg core_cancel_q;
    always @(posedge clk) begin
        if (!rst_n) core_cancel_q <= 1'b0;
        else core_cancel_q <= core_cancel;
    end
    wire core_cancel_any = core_cancel || core_cancel_q;
    wire fw_flush = core_cancel_any;
    z100_skid_v13c #(.W(558)) feature_word_slice (
        .clk(clk), .rst_n(rst_n), .flush(fw_flush),
        .in_valid(fw_in_valid), .in_ready(feature_cfg_word_ready), .in_data(fw_in_data),
        .out_valid(fw_out_valid), .out_ready(core_feature_cfg_word_ready), .out_data(fw_out_bus));
    // out_valid==0 implies the skid entry is empty as well.
    wire fw_empty = !fw_out_valid;
    // periph_flat_v3: the Conv/Pool-muxed feature cfg geometry (epoch,
    // channels, height, width) reaches the store from registers. Both
    // producers are z100_native_materialized_load_control, which holds begin
    // and these fields (its *_q registers) constant from CONFIG entry until
    // the begin handshake. Begin is passed only when it was already requested
    // in the previous cycle by the same owner, so the registered copy equals
    // the live value in every cycle in which the store can see begin.
    // Removes owner -> cfg mux -> store geometry calc -> copy R/CE paths.
    // Cost: +1 cycle per feature load.
    wire fcfg_begin_req = aux_owner ? aux_feature_cfg_begin : feature_begin;
    reg [31:0] fcfg_epoch_q;
    reg [10:0] fcfg_channels_q;
    reg [9:0] fcfg_height_q, fcfg_width_q;
    reg fcfg_seen_q, fcfg_owner_q;
    always @(posedge clk) begin
        fcfg_epoch_q <= aux_owner ? aux_feature_cfg_epoch : feature_cfg_epoch;
        fcfg_channels_q <= aux_owner ? aux_feature_cfg_channels : feature_cfg_channels;
        fcfg_height_q <= aux_owner ? aux_feature_cfg_height : feature_cfg_height;
        fcfg_width_q <= aux_owner ? aux_feature_cfg_width : feature_cfg_width;
        fcfg_owner_q <= aux_owner;
        if (!rst_n || core_cancel_any) fcfg_seen_q <= 1'b0;
        else fcfg_seen_q <= fcfg_begin_req;
    end
    wire fcfg_settled = fcfg_seen_q && (fcfg_owner_q == aux_owner);
    wire fw_core_begin = fcfg_begin_req && fw_empty && fcfg_settled;
    wire fw_core_commit = (aux_owner ? aux_feature_cfg_commit : feature_commit) && fw_empty;
    assign feature_cfg_begin_ready_v10 = core_feature_cfg_begin_ready && fw_empty && fcfg_settled;
    assign feature_cfg_commit_ready_v10 = core_feature_cfg_commit_ready && fw_empty;
    always @(posedge clk) begin
        if (!rst_n || core_cancel_any) begin
            feature_error_q <= 1'b0; feature_error_code_q <= 4'd0;
        end else begin
            feature_error_q <= feature_error_valid; feature_error_code_q <= feature_error_code;
        end
    end
    // periph_flat_v3: two-entry register slice between the Conv output packer
    // and output_order. Cuts packer drain_buffer -> out_address calc ->
    // output_order metadata compare -> in_ready -> packer (and -> write
    // control -> output writer burst buffer WE), 28-31 levels. Pure FIFO
    // (beat order unchanged, full throughput, +1 cycle latency). Flushed by
    // the same cancel as the core/packer, so a buffered beat is dropped
    // exactly when the packer itself would have been reset. A write-side-only
    // cancel (write_semantic_cancel) keeps the beat, as the packer would.
    wire pk_valid, pk_last;
    wire [31:0] pk_epoch;
    wire [12:0] pk_address;
    wire [511:0] pk_data;
    z100_skid_v13c #(.W(558)) packed_slice (
        .clk(clk), .rst_n(rst_n), .flush(core_cancel_any),
        .in_valid(packed_valid), .in_ready(packed_ready),
        .in_data({packed_epoch, packed_address, packed_last, packed_data}),
        .out_valid(pk_valid), .out_ready(output_order_input_ready),
        .out_data({pk_epoch, pk_address, pk_last, pk_data}));

    // Pooling is outside this Conv backend's public work contract. V10's
    // existing shared core includes the pool consumer, held permanently idle.
    z100_native_row20_shared_pool_address_shared_local_control_v12 #(
        .SITES(SITES), .SITE_FIFO_DEPTH(SITE_FIFO_DEPTH)
    ) compute_core (
        .clk(clk), .rst_n(rst_n),
        .cancel(core_cancel_q),
        .pool_job_valid((aux_owner ? aux_pool_job_valid : 1'b0)), .pool_job_ready(aux_pool_job_ready), .pool_job_epoch((aux_owner ? aux_pool_job_epoch : 32'd0)),
        .pool_job_channels((aux_owner ? aux_pool_job_channels : 11'd0)), .pool_job_height((aux_owner ? aux_pool_job_height : 10'd0)), .pool_job_width((aux_owner ? aux_pool_job_width : 10'd0)),
        .pool_packed_valid(aux_pool_packed_valid), .pool_packed_ready((aux_owner ? aux_pool_packed_ready : 1'b0)), .pool_packed_epoch(aux_pool_packed_epoch),
        .pool_packed_address(aux_pool_packed_address), .pool_packed_data(aux_pool_packed_data), .pool_packed_last(aux_pool_packed_last),
        .pool_done(aux_pool_done), .pool_error(aux_pool_error), .pool_error_code(aux_pool_error_code), .pool_active(aux_pool_active),
        .feature_cfg_begin(fw_core_begin), .feature_cfg_begin_ready(core_feature_cfg_begin_ready),
        .feature_cfg_canonical_order((aux_owner ? aux_feature_cfg_canonical_order : feature_cfg_canonical_order)),
        .feature_load_bank((aux_owner ? aux_feature_load_bank : feature_load_bank)), .compute_source_bank((aux_owner ? aux_compute_source_bank : compute_source_bank)),
        .feature_load_store_valid(feature_load_store_valid), .feature_load_loading(feature_load_loading),
        .feature_load_active_epoch(feature_load_active_epoch),
        .feature_cfg_epoch(fcfg_epoch_q), .feature_cfg_channels(fcfg_channels_q),
        .feature_cfg_height(fcfg_height_q), .feature_cfg_width(fcfg_width_q),
        .feature_cfg_word_epoch(fw_out_epoch), .feature_cfg_word_address(fw_out_address),
        .feature_cfg_word_last(fw_out_last), .feature_cfg_word_valid(fw_out_valid),
        .feature_cfg_word_ready(core_feature_cfg_word_ready), .feature_cfg_data(fw_out_data),
        .feature_cfg_commit(fw_core_commit), .feature_cfg_commit_ready(core_feature_cfg_commit_ready),
        .feature_store_valid(feature_store_valid), .feature_loading(feature_loading),
        .feature_active_epoch(feature_active_epoch), .feature_error_valid(feature_error_valid),
        .feature_error_code(feature_error_code),
        .window_valid(window_valid), .window_ready(core_window_ready), .window_epoch(window_epoch),
        .window_tag(window_tag), .window_row_address(window_row_address), .window_first_x(window_first_x),
        .window_input_width(window_input_width), .window_output_remaining(window_output_remaining),
        .window_sites(window_sites), .window_channel_mask(window_channel_mask),
        .window_stride_two(window_stride_two), .window_y_valid(window_y_valid),
        .mac_cfg_begin(mac_cfg_begin), .mac_cfg_begin_ready(mac_cfg_begin_ready),
        .mac_cfg_epoch(mac_cfg_epoch), .mac_cfg_groups(mac_cfg_groups),
        .mac_cfg_weight_valid(mac_cfg_weight_valid), .mac_cfg_weight_ready(mac_cfg_weight_ready),
        .mac_cfg_weights(mac_cfg_weights), .mac_cfg_bias_valid(mac_cfg_bias_valid),
        .mac_cfg_bias_ready(mac_cfg_bias_ready), .mac_cfg_bias(mac_cfg_bias),
        .mac_cfg_commit(mac_cfg_commit), .mac_cfg_commit_ready(mac_cfg_commit_ready),
        .mac_weights_valid(mac_weights_valid), .mac_weights_epoch(mac_weights_epoch),
        .mac_error_valid(mac_error_valid), .mac_error_code(mac_error_code),
        .run_valid(run_valid), .run_ready(core_run_ready), .run_epoch(run_epoch), .run_token(run_token),
        .run_lanes(run_lanes), .run_sites(run_sites), .stream_valid(stream_valid),
        .stream_ready(stream_ready), .stream_token(stream_token), .stream_last(stream_last),
        .stream_data(stream_data), .response_tag(response_tag), .response_mask(response_mask),
        .diagnostic_mac_active(mac_diagnostic_active),
        .diagnostic_mac_good_group(mac_diagnostic_good_group),
        .diagnostic_mac_good_slots(mac_diagnostic_good_slots),
        .diagnostic_mac_starve(mac_diagnostic_starve),
        .diagnostic_mac_output_stall(mac_diagnostic_output_stall),
        .req_cfg_begin(req_cfg_begin), .req_cfg_begin_ready(req_cfg_begin_ready),
        .req_cfg_epoch(req_cfg_epoch), .req_cfg_lanes(req_cfg_lanes),
        .req_cfg_word_valid(req_cfg_word_valid), .req_cfg_word_ready(req_cfg_word_ready),
        .req_cfg_multiplier(req_cfg_multiplier), .req_cfg_shift(req_cfg_shift),
        .req_cfg_commit(req_cfg_commit), .req_cfg_commit_ready(req_cfg_commit_ready),
        .req_cfg_error(req_cfg_error), .req_input_error(req_input_error),
        .unary_cfg_begin(unary_cfg_begin), .unary_cfg_begin_ready(unary_cfg_begin_ready),
        .unary_cfg_epoch(unary_cfg_epoch), .unary_cfg_word_valid(unary_cfg_word_valid),
        .unary_cfg_word_ready(unary_cfg_word_ready), .unary_cfg_data(unary_cfg_data),
        .unary_cfg_commit(unary_cfg_commit), .unary_cfg_commit_ready(unary_cfg_commit_ready),
        .unary_error_valid(unary_error_valid), .unary_error_code(unary_error_code),
        .unary_store_valid(unary_store_valid), .unary_active_epoch(unary_active_epoch),
        .unary_loading(unary_loading), .raw_valid(raw_valid), .raw_ready(raw_ready),
        .raw_token(raw_token), .raw_site(raw_site), .raw_last(raw_last), .raw_lanes(raw_lanes),
        .raw_data(raw_data), .raw_overflow(raw_overflow), .post_valid(post_valid),
        .post_ready(post_ready), .post_epoch(post_epoch), .post_token(post_token),
        .post_site(post_site), .post_lanes(post_lanes), .post_last(post_last), .post_data(post_data),
        .metadata_error(metadata_error), .pack_cfg_valid(pack_cfg_valid), .pack_cfg_ready(pack_cfg_ready),
        .pack_cfg_epoch(pack_cfg_epoch), .pack_cfg_channels(pack_cfg_channels),
        .pack_cfg_height(pack_cfg_height), .pack_cfg_width(pack_cfg_width),
        .pack_cfg_token_base(pack_cfg_token_base), .packed_valid(packed_valid),
        .packed_ready(packed_ready), .packed_epoch(packed_epoch), .packed_address(packed_address),
        .packed_data(packed_data), .packed_last(packed_last), .pack_done(pack_done),
        .pack_error_valid(pack_error_valid), .pack_error_code(pack_error_code), .pack_active(pack_active)
    );
    assign feature_begin_ready = feature_cfg_begin_ready_v10;
    assign feature_commit_ready = feature_cfg_commit_ready_v10;



























    z100_native_conv_tile_control_v2 #(.SITES(SITES)) tile_control (
        .clk(clk), .rst_n(rst_n), .cancel(datapath_cancel), .recover(1'b0), .recovery_drained(1'b0),
        .cmd_valid(tile_valid), .cmd_ready(tile_cmd_ready), .cmd_epoch(event_epoch),
        .cmd_token_base(tile_token_base), .cmd_tag_base(tile_tag_base), .cmd_job_tag(tile_job_tag),
        .cmd_parameter_first(context_parameter_first), .cmd_input_channels(context_cin[10:0]),
        .cmd_output_channels(context_cout[10:0]), .cmd_input_height(context_ih[9:0]),
        .cmd_input_width(context_iw[9:0]), .cmd_input_y(tile_input_y), .cmd_input_rows(tile_input_rows),
        .cmd_output_height(context_oh[9:0]), .cmd_output_width(context_ow[9:0]),
        .cmd_output_y(tile_output_y), .cmd_output_rows(tile_output_rows),
        .cmd_kernel(context_kernel[1:0]), .cmd_stride(context_stride[1:0]),
        .cmd_padding(context_padding[1:0]), .pack_valid(pack_valid), .pack_ready(pack_ready),
        .epoch(tile_epoch), .pack_token_base(pack_token_q), .job_tag(tile_job_q),
        .pack_channels(pack_channels), .pack_height(pack_height), .pack_width(pack_width),
        .parameter_valid(parameter_valid), .parameter_ready(parameter_ready), .parameter_job(parameter_job),
        .parameter_done_valid(parameter_done_valid), .parameter_done_ready(parameter_done_ready),
        .parameter_done_epoch(event_epoch), .parameter_done_job_tag(tile_job_q),
        .parameter_done_job(parameter_job), .parameter_done_error(parameter_done_error),
        .row_valid(row_valid), .row_ready(row_ready), .row_token_base(row_token_base),
        .row_tag_base(row_tag_base), .row_channels(row_channels), .row_input_width(row_input_width),
        .row_output_width(row_output_width), .row_kernel(row_kernel), .row_stride(row_stride),
        .row_padding(row_padding), .row_lanes(row_lanes), .row_bank_words(row_bank_words),
        .row_plane_stride(row_plane_stride), .row_ky_bases(row_ky_bases), .row_y_valid(row_y_valid),
        .row_done_valid(row_done_valid), .row_done_ready(row_done_ready),
        .row_done_epoch(row_done_epoch), .row_done_last_token(row_done_last_token),
        .row_done_job_tag(tile_job_q), .row_done_error(row_done_error),
        .publish_valid(publish_valid), .publish_ready(publish_ready), .publish_epoch(publish_epoch),
        .publish_tag(publish_tag), .publish_error(publish_error), .child_cancel(tile_child_cancel),
        .active(tile_active), .needs_drain(tile_needs_drain), .done(tile_done),
        .fault(tile_fault_internal), .fault_code(tile_fault_internal_code)
    );











    z100_native_row_scheduler20 #(.MAX_SITES(SITES)) row_scheduler (
        .clk(clk), .rst_n(rst_n), .cancel(datapath_cancel || tile_child_cancel),
        .cmd_valid(row_valid), .cmd_ready(row_ready), .cmd_epoch(tile_epoch),
        .cmd_token_base(row_token_base), .cmd_tag_base(row_tag_base), .cmd_channels(row_channels),
        .cmd_input_width(row_input_width), .cmd_output_width(row_output_width),
        .cmd_kernel(row_kernel), .cmd_stride(row_stride), .cmd_padding(row_padding),
        .cmd_lanes(row_lanes), .cmd_bank_words(row_bank_words),
        .cmd_channel_plane_stride(row_plane_stride), .cmd_ky_row_bases(row_ky_bases),
        .cmd_y_valid(row_y_valid), .run_valid(scheduler_run_valid), .run_ready(core_run_ready),
        .run_epoch(scheduler_run_epoch), .run_token(scheduler_run_token),
        .run_lanes(scheduler_run_lanes), .run_sites(scheduler_run_sites),
        .window_valid(scheduler_window_valid), .window_ready(core_window_ready),
        .window_epoch(scheduler_window_epoch), .window_tag(scheduler_window_tag),
        .window_row_address(scheduler_window_row_address), .window_first_x(scheduler_window_first_x),
        .window_input_width(scheduler_window_input_width),
        .window_output_remaining(scheduler_window_output_remaining),
        .window_sites(scheduler_window_sites), .window_channel_mask(scheduler_window_channel_mask),
        .window_stride_two(scheduler_window_stride_two), .window_y_valid(scheduler_window_y_valid),
        .post_done_valid(post_valid && post_ready && post_last), .post_done_ready(scheduler_post_ready),
        .post_done_epoch(post_epoch), .post_done_token(post_token), .done(scheduler_done),
        .abort_pulse(scheduler_abort), .fault_valid(scheduler_fault),
        .fault_code(scheduler_fault_code), .active(scheduler_active)
    );
    assign run_valid = scheduler_run_valid;
    assign window_valid = scheduler_window_valid;
    assign run_epoch = scheduler_run_epoch;
    assign run_token = scheduler_run_token;
    assign run_lanes = scheduler_run_lanes;
    assign run_sites = scheduler_run_sites;
    assign window_epoch = scheduler_window_epoch;
    assign window_tag = scheduler_window_tag;
    assign window_row_address = scheduler_window_row_address;
    assign window_first_x = scheduler_window_first_x;
    assign window_input_width = scheduler_window_input_width;
    assign window_output_remaining = scheduler_window_output_remaining;
    assign window_sites = scheduler_window_sites;
    assign window_channel_mask = scheduler_window_channel_mask;
    assign window_stride_two = scheduler_window_stride_two;
    assign window_y_valid = scheduler_window_y_valid;

    always @(posedge clk) begin
        if (!rst_n || datapath_cancel) begin
            scheduler_last_post_epoch <= 0;
            scheduler_last_post_token <= 0;
        end else if (post_valid && post_ready && post_last) begin
            scheduler_last_post_epoch <= post_epoch;
            scheduler_last_post_token <= post_token;
        end
    end
    assign row_done_valid = scheduler_done;
    assign row_done_epoch = scheduler_last_post_epoch;
    assign row_done_last_token = scheduler_last_post_token;
    assign row_done_error = scheduler_fault || scheduler_abort;







































    assign directory_descriptor_ready = parameter_job_ready && parameter_identity_ok;
    assign parameter_job_valid = directory_descriptor_valid && parameter_identity_ok;
    assign parameter_ready = resident_cmd_ready;
    assign parameter_done_valid = resident_done_valid;
    assign parameter_done_error = resident_done_error || resident_fault || parameter_fault ||
        bridge_fault || directory_fault || directory_reader_fault || parameter_reader_fault;
    assign publish_valid = write_done;
    assign publish_epoch = write_epoch;
    assign publish_tag = tile_job_q;
    assign publish_error = write_fault || !write_committed;
    assign tile_fault = tile_fault_internal || scheduler_fault || scheduler_abort ||
        write_fault || output_writer_fault || directory_fault || directory_reader_fault ||
        parameter_fault || parameter_reader_fault || bridge_fault || resident_fault || datapath_fault;

    assign resident_cmd_valid = parameter_valid;
    assign resident_cmd_epoch = event_epoch;
    assign resident_cmd_event = {24'd0, context_event};
    // Match the accepted tile plan: residency is scoped to the destination
    // graph-slot generation.  A new output slot invalidates configuration even
    // when the parameter DDR region is unchanged, preventing cross-slot reuse.
    assign resident_cmd_generation = destination_generation_q;
    assign resident_cmd_job = parameter_job;



    z100_native_parameter_directory_v2 parameter_directory (
        .clk(clk), .rst_n(rst_n), .abort(datapath_cancel), .recover(1'b0),
        .consumer_idle(directory_consumer_idle), .cmd_valid(resident_downstream_cmd_valid),
        .cmd_ready(directory_ready), .cmd_epoch(resident_downstream_cmd_epoch), .cmd_tag(tile_job_q),
        .cmd_table_base(parameter_directory_base_q), .cmd_model_crc(model_crc_q),
        .cmd_payload_begin(parameter_payload_begin_q), .cmd_payload_end(parameter_payload_end_q),
        .cmd_job(resident_downstream_cmd_job), .cmd_count(parameter_count_q), .cmd_timeout(parameter_timeout_q),
        .reader_command(directory_reader_command), .reader_command_ready(directory_reader_command_ready),
        .reader_epoch(directory_reader_epoch), .reader_address(directory_reader_address),
        .reader_words(directory_reader_words), .reader_busy(directory_reader_busy),
        .reader_fault(directory_reader_fault), .reader_cancel(directory_reader_cancel),
        .reader_clear(directory_reader_clear), .reader_valid(directory_reader_valid),
        .reader_ready(directory_reader_ready), .reader_result_epoch(directory_result_epoch),
        .reader_index(directory_reader_index), .reader_last(directory_reader_last),
        .reader_data(directory_reader_data), .descriptor_valid(directory_descriptor_valid),
        .descriptor_ready(directory_descriptor_ready), .descriptor_epoch(directory_descriptor_epoch),
        .descriptor_tag(directory_descriptor_tag), .descriptor_job(directory_descriptor_job),
        .descriptor_groups(pd_groups), .descriptor_lanes(pd_lanes),
        .descriptor_weights(directory_descriptor_weights), .descriptor_bias(directory_descriptor_bias),
        .descriptor_factors(directory_descriptor_factors), .descriptor_unary(directory_descriptor_unary),
        .active(directory_active), .needs_drain(), .done(directory_done),
        .fault(directory_fault), .fault_code(directory_fault_code)
    );
    z100_native_parameter_reader parameter_loader (
        .clk(clk), .rst_n(rst_n), .abort(datapath_cancel), .recover(1'b0),
        .job_valid(parameter_job_valid), .job_ready(parameter_job_ready), .job_epoch(event_epoch),
        .job_timeout(parameter_timeout_q), .job_groups(pd_groups), .job_lanes(pd_lanes),
        .job_weights(directory_descriptor_weights), .job_bias(directory_descriptor_bias),
        .job_factors(directory_descriptor_factors), .job_unary(directory_descriptor_unary),
        .reader_command(parameter_reader_command), .reader_command_ready(parameter_reader_command_ready),
        .reader_epoch(parameter_reader_epoch), .reader_address(parameter_reader_address),
        .reader_words(parameter_reader_words), .reader_busy(parameter_reader_busy),
        .reader_fault(parameter_reader_fault), .reader_cancel(parameter_reader_cancel),
        .reader_clear(parameter_reader_clear), .reader_valid(parameter_reader_valid),
        .reader_ready(parameter_reader_ready), .reader_result_epoch(parameter_result_epoch),
        .reader_index(parameter_reader_index), .reader_last(parameter_reader_last),
        .reader_data(parameter_reader_data), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_operation(cfg_operation), .cfg_epoch(cfg_epoch), .cfg_tag(cfg_tag), .cfg_index(cfg_index),
        .cfg_groups(cfg_groups), .cfg_lanes(cfg_lanes), .cfg_data(cfg_data),
        .cfg_response_valid(cfg_response_valid), .cfg_response_ready(cfg_response_ready),
        .cfg_response_tag(cfg_response_tag), .cfg_response_error(cfg_response_error),
        .cfg_fault(bridge_fault), .cfg_configured(bridge_configured), .cfg_cancel(bridge_child_cancel),
        .active(parameter_active), .fault(parameter_fault), .fault_code(parameter_fault_code),
        .done(parameter_done)
    );
    z100_parameter_residency_guard_v3 parameter_residency (
        .clk(clk), .rst_n(rst_n), .cancel(datapath_cancel),
        .outer_command_start(cmd_valid && cmd_ready),
        .context_valid(context_valid), .context_epoch(event_epoch),
        .context_event({24'd0, context_event}),
        .context_generation(destination_generation_q),
        .cmd_valid(resident_cmd_valid), .cmd_ready(resident_cmd_ready),
        .cmd_epoch(resident_cmd_epoch), .cmd_event(resident_cmd_event),
        .cmd_generation(resident_cmd_generation), .cmd_job(resident_cmd_job),
        .downstream_cmd_valid(resident_downstream_cmd_valid),
        .downstream_cmd_ready(directory_ready),
        .downstream_cmd_epoch(resident_downstream_cmd_epoch),
        .downstream_cmd_event(resident_downstream_cmd_event),
        .downstream_cmd_generation(resident_downstream_cmd_generation),
        .downstream_cmd_job(resident_downstream_cmd_job),
        .downstream_done_valid(parameter_done),
        .downstream_done_ready(resident_downstream_done_ready),
        .downstream_done_epoch(event_epoch),
        .downstream_done_event({24'd0, context_event}),
        .downstream_done_generation(destination_generation_q),
        .downstream_done_job(parameter_job),
        .downstream_done_error(parameter_fault || bridge_fault || directory_fault ||
            directory_reader_fault || parameter_reader_fault),
        .done_valid(resident_done_valid), .done_ready(parameter_done_ready),
        .done_epoch(resident_done_epoch), .done_event(resident_done_event),
        .done_generation(resident_done_generation), .done_job(resident_done_job),
        .done_error(resident_done_error), .active(resident_active),
        .fault(resident_fault), .fault_code(resident_fault_code)
    );
    z100_native_parameter_bridge parameter_bridge (
        .clk(clk), .rst_n(rst_n), .cancel(bridge_child_cancel), .cmd_valid(cfg_valid),
        .cmd_ready(cfg_ready), .cmd_operation(cfg_operation), .cmd_epoch(cfg_epoch),
        .cmd_tag(cfg_tag), .cmd_index(cfg_index), .cmd_groups(cfg_groups), .cmd_lanes(cfg_lanes),
        .cmd_data(cfg_data), .response_valid(cfg_response_valid),
        .response_ready(cfg_response_ready), .response_tag(cfg_response_tag),
        .response_error(cfg_response_error), .configured(bridge_configured),
        .child_cancel(), .fault(bridge_fault), .cfg_epoch(bridge_cfg_epoch),
        .cfg_groups(bridge_cfg_groups), .cfg_lanes(bridge_cfg_lanes),
        .mac_begin(mac_cfg_begin), .mac_begin_ready(mac_cfg_begin_ready),
        .mac_weight(mac_cfg_weight_valid), .mac_weight_ready(mac_cfg_weight_ready),
        .mac_bias(mac_cfg_bias_valid), .mac_bias_ready(mac_cfg_bias_ready),
        .mac_commit(mac_cfg_commit), .mac_commit_ready(mac_cfg_commit_ready),
        .mac_data(bridge_mac_data), .mac_error(mac_error_valid), .mac_loaded(mac_weights_valid),
        .mac_epoch(mac_weights_epoch), .factor_begin(req_cfg_begin),
        .factor_begin_ready(req_cfg_begin_ready), .factor_word(req_cfg_word_valid),
        .factor_word_ready(req_cfg_word_ready), .factor_commit(req_cfg_commit),
        .factor_commit_ready(req_cfg_commit_ready), .factor_multiplier(req_cfg_multiplier),
        .factor_shift(req_cfg_shift), .factor_error(req_cfg_error || req_input_error),
        .unary_begin(unary_cfg_begin), .unary_begin_ready(unary_cfg_begin_ready),
        .unary_word(unary_cfg_word_valid), .unary_word_ready(unary_cfg_word_ready),
        .unary_commit(unary_cfg_commit), .unary_commit_ready(unary_cfg_commit_ready),
        .unary_data(unary_cfg_data), .unary_error(unary_error_valid),
        .unary_loaded(unary_store_valid), .unary_epoch(unary_active_epoch)
    );
    assign mac_cfg_epoch = bridge_cfg_epoch;
    assign req_cfg_epoch = bridge_cfg_epoch;
    assign unary_cfg_epoch = bridge_cfg_epoch;
    assign mac_cfg_groups = bridge_cfg_groups;
    assign req_cfg_lanes = bridge_cfg_lanes;
    assign mac_cfg_weights = bridge_mac_data;
    assign mac_cfg_bias = bridge_mac_data;


















    z100_native_axi64_reader directory_reader (
        .clk(clk), .rst_n(rst_n), .cmd_valid(directory_reader_command),
        .cmd_ready(directory_reader_command_ready), .cmd_epoch(directory_reader_epoch),
        .cmd_address(directory_reader_address), .cmd_word_count(directory_reader_words),
        .cancel(directory_reader_cancel), .timeout(1'b0), .clear_fault(directory_reader_clear),
        .busy(directory_reader_busy), .done(), .fault(directory_reader_fault), .fault_code(),
        .out_valid(directory_reader_valid), .out_ready(directory_reader_ready),
        .out_epoch(directory_result_epoch), .out_index(directory_reader_index),
        .out_data(directory_reader_data), .out_last(directory_reader_last),
        .m_axi_arid(directory_arid), .m_axi_araddr(directory_araddr),
        .m_axi_arlen(directory_arlen), .m_axi_arsize(directory_arsize),
        .m_axi_arburst(directory_arburst), .m_axi_arvalid(directory_arvalid),
        .m_axi_arready(directory_arready), .m_axi_rid(directory_rid),
        .m_axi_rdata(directory_rdata), .m_axi_rresp(directory_rresp),
        .m_axi_rlast(directory_rlast), .m_axi_rvalid(directory_rvalid),
        .m_axi_rready(directory_rready)
    );
    z100_native_axi64_reader parameter_reader (
        .clk(clk), .rst_n(rst_n), .cmd_valid(parameter_reader_command),
        .cmd_ready(parameter_reader_command_ready), .cmd_epoch(parameter_reader_epoch),
        .cmd_address(parameter_reader_address), .cmd_word_count(parameter_reader_words),
        .cancel(parameter_reader_cancel), .timeout(1'b0), .clear_fault(parameter_reader_clear),
        .busy(parameter_reader_busy), .done(), .fault(parameter_reader_fault), .fault_code(),
        .out_valid(parameter_reader_valid), .out_ready(parameter_reader_ready),
        .out_epoch(parameter_result_epoch), .out_index(parameter_reader_index),
        .out_data(parameter_reader_data), .out_last(parameter_reader_last),
        .m_axi_arid(parameter_arid), .m_axi_araddr(parameter_araddr),
        .m_axi_arlen(parameter_arlen), .m_axi_arsize(parameter_arsize),
        .m_axi_arburst(parameter_arburst), .m_axi_arvalid(parameter_arvalid),
        .m_axi_arready(parameter_arready), .m_axi_rid(parameter_rid),
        .m_axi_rdata(parameter_rdata), .m_axi_rresp(parameter_rresp),
        .m_axi_rlast(parameter_rlast), .m_axi_rvalid(parameter_rvalid),
        .m_axi_rready(parameter_rready)
    );
    z100_native_axi_read_arbiter directory_parameter_arbiter (
        .clk(clk), .rst_n(rst_n), .s_arid({directory_arid,parameter_arid}),
        .s_araddr({directory_araddr,parameter_araddr}), .s_arlen({directory_arlen,parameter_arlen}),
        .s_arsize({directory_arsize,parameter_arsize}), .s_arburst({directory_arburst,parameter_arburst}),
        .s_arvalid({directory_arvalid,parameter_arvalid}), .s_arready(dp_s_arready),
        .s_rid(dp_s_rid), .s_rdata(dp_s_rdata), .s_rresp(dp_s_rresp),
        .s_rlast(dp_s_rlast), .s_rvalid(dp_s_rvalid), .s_rready({directory_rready,parameter_rready}),
        .m_arid(merged_arid), .m_araddr(merged_araddr), .m_arlen(merged_arlen),
        .m_arsize(merged_arsize), .m_arburst(merged_arburst), .m_arvalid(merged_arvalid),
        .m_arready(merged_arready), .m_rid(merged_rid), .m_rdata(merged_rdata),
        .m_rresp(merged_rresp), .m_rlast(merged_rlast), .m_rvalid(merged_rvalid),
        .m_rready(merged_rready), .active(dp_active), .active_owner(dp_active_owner),
        .protocol_fault(dp_protocol_fault)
    );
    assign {directory_arready,parameter_arready} = dp_s_arready;
    assign directory_rid = dp_s_rid[11:6];
    assign parameter_rid = dp_s_rid[5:0];
    assign directory_rdata = dp_s_rdata[127:64];
    assign parameter_rdata = dp_s_rdata[63:0];
    assign directory_rresp = dp_s_rresp[3:2];
    assign parameter_rresp = dp_s_rresp[1:0];
    assign directory_rlast = dp_s_rlast[1];
    assign parameter_rlast = dp_s_rlast[0];
    assign directory_rvalid = dp_s_rvalid[1];
    assign parameter_rvalid = dp_s_rvalid[0];










    assign {merged_rid, pf_rid} = physical_s_rid;
    assign {merged_rdata, pf_rdata} = physical_s_rdata;
    assign {merged_rresp, pf_rresp} = physical_s_rresp;
    assign {merged_rvalid, pf_rvalid} = physical_s_rvalid;
    assign {merged_rlast, pf_rlast} = physical_s_rlast;
    assign {merged_arready, pf_arready} = physical_s_arready;
    z100_native_axi_read_arbiter physical_read_arbiter (
        .clk(clk), .rst_n(rst_n), .s_arid({merged_arid,pf_arid}),
        .s_araddr({merged_araddr,pf_araddr}), .s_arlen({merged_arlen,pf_arlen}),
        .s_arsize({merged_arsize,pf_arsize}), .s_arburst({merged_arburst,pf_arburst}),
        .s_arvalid({merged_arvalid,pf_arvalid}), .s_arready(physical_s_arready),
        .s_rid(physical_s_rid), .s_rdata(physical_s_rdata), .s_rresp(physical_s_rresp),
        .s_rlast(physical_s_rlast), .s_rvalid(physical_s_rvalid),
        .s_rready({merged_rready,pf_rready}), .m_arid(m_axi_arid), .m_araddr(m_axi_araddr),
        .m_arlen(m_axi_arlen), .m_arsize(m_axi_arsize), .m_arburst(m_axi_arburst),
        .m_arvalid(m_axi_arvalid), .m_arready(m_axi_arready), .m_rid(m_axi_rid),
        .m_rdata(m_axi_rdata), .m_rresp(m_axi_rresp), .m_rlast(m_axi_rlast),
        .m_rvalid(m_axi_rvalid), .m_rready(m_axi_rready), .active(physical_active),
        .active_owner(physical_active_owner), .protocol_fault(physical_protocol_fault)
    );






























    assign pack_ready = pack_cfg_ready && write_command_ready;
    assign pack_cfg_valid = pack_valid;
    assign pack_cfg_epoch = tile_epoch;
    assign pack_cfg_token_base = pack_token_q;
    assign pack_cfg_channels = pack_channels;
    assign pack_cfg_height = pack_height;
    assign pack_cfg_width = pack_width;
    assign write_command = pack_valid && pack_ready;
    // packed_ready is driven by packed_slice (periph_flat_v3).
    assign tile_done_epoch = tile_epoch;
    assign tile_done_job = tile_job_tag;
    assign tile_done_bank = tile_bank;

    z100_native_materialized_write_control materialized_write (
        .clk(clk), .rst_n(rst_n), .cmd_valid(write_command), .cmd_ready(write_command_ready),
        .cmd_epoch(tile_epoch), .cmd_destination_generation(destination_generation_q),
        .cmd_destination_address(destination_base_q), .cmd_region_begin(destination_region_begin_q),
        .cmd_region_end(destination_region_end_q), .cmd_timeout_cycles(write_timeout_q),
        .cmd_channels(pack_channels), .cmd_full_height(context_oh[9:0]),
        .cmd_width(context_ow[9:0]), .cmd_first_row(tile_output_y), .cmd_height(pack_height),
        .cmd_destination_reserved(effective_destination_reserved), .abort(datapath_cancel),
        .recover(1'b0), .active(write_active), .fault(write_fault), .fault_code(write_fault_code),
        .done(write_done), .tile_committed(write_committed), .epoch(write_epoch),
        .destination_generation(write_generation), .channels(write_channels),
        .height(write_height), .width(write_width), .order_config(write_order_config),
        .order_config_ready(write_order_config_ready), .order_done(write_order_done),
        .packed_valid(write_packed_valid), .packed_ready(write_packed_ready), .packed_epoch(write_packed_epoch),
        .packed_index(write_packed_index), .packed_last(write_packed_last), .packed_data(write_packed_data),
        .writer_command(write_writer_command), .writer_command_ready(write_writer_command_ready),
        .writer_address(write_writer_address), .writer_words(write_words), .writer_valid(write_writer_valid),
        .writer_ready(write_writer_ready), .writer_epoch(write_writer_input_epoch),
        .writer_index(write_writer_index), .writer_last(write_writer_last), .writer_data(write_writer_data),
        .writer_done(output_writer_done), .writer_busy(output_writer_busy),
        .writer_fault(output_writer_fault), .pipeline_error(write_codec_error),
        .semantic_cancel(write_semantic_cancel), .writer_cancel(write_writer_cancel),
        .writer_clear_fault(write_writer_clear)
    );
    z100_native_stream_order output_order (
        .clk(clk), .rst_n(rst_n), .cancel(write_semantic_cancel),
        .cfg_valid(write_order_config), .cfg_ready(write_order_config_ready),
        .cfg_epoch(write_epoch), .cfg_write_order(1'b1), .cfg_channels(write_channels),
        .cfg_height(write_height), .cfg_width(write_width), .in_valid(pk_valid),
        .in_ready(output_order_input_ready), .in_epoch(pk_epoch), .in_index(13'd0),
        .in_address(pk_address), .in_last(pk_last), .in_data(pk_data),
        .out_valid(write_packed_valid), .out_ready(write_packed_ready), .out_epoch(write_packed_epoch),
        .out_index(write_packed_index), .out_address(), .out_last(write_packed_last),
        .out_data(write_packed_data), .active(), .done(write_order_done), .error_valid(write_codec_error),
        .error_code()
    );
    z100_native_axi64_writer output_writer (
        .clk(clk), .rst_n(rst_n), .cmd_valid(write_writer_command),
        .cmd_ready(write_writer_command_ready), .cmd_epoch(write_epoch),
        .cmd_address(write_writer_address), .cmd_word_count(write_words),
        .in_valid(write_writer_valid), .in_ready(write_writer_ready),
        .in_epoch(write_writer_input_epoch), .in_index(write_writer_index),
        .in_data(write_writer_data), .in_last(write_writer_last), .cancel(write_writer_cancel),
        .timeout(1'b0), .clear_fault(write_writer_clear), .busy(output_writer_busy),
        .done(output_writer_done), .fault(output_writer_fault), .fault_code(output_writer_fault_code),
        .m_axi_awid(output_awid), .m_axi_awaddr(output_awaddr), .m_axi_awlen(output_awlen),
        .m_axi_awsize(output_awsize), .m_axi_awburst(output_awburst), .m_axi_awvalid(output_awvalid),
        .m_axi_awready(m_axi_awready), .m_axi_wid(output_wid), .m_axi_wdata(output_wdata),
        .m_axi_wstrb(output_wstrb), .m_axi_wlast(output_wlast), .m_axi_wvalid(output_wvalid),
        .m_axi_wready(m_axi_wready), .m_axi_bid(m_axi_bid), .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(output_bready)
    );
    assign m_axi_awid = output_awid;
    assign m_axi_awaddr = output_awaddr;
    assign m_axi_awlen = output_awlen;
    assign m_axi_awsize = output_awsize;
    assign m_axi_awburst = output_awburst;
    assign m_axi_awvalid = output_awvalid;
    assign m_axi_wid = output_wid;
    assign m_axi_wdata = output_wdata;
    assign m_axi_wstrb = output_wstrb;
    assign m_axi_wlast = output_wlast;
    assign m_axi_wvalid = output_wvalid;
    assign m_axi_bready = output_bready;



    assign all_io_quiet = !pf_reader_busy && !directory_reader_busy && !parameter_reader_busy &&
        !dp_active && !physical_active && !output_writer_busy;
    assign diagnostic_read_kind = !physical_active ? 2'd0 :
        !physical_active_owner ? 2'd1 : !dp_active ? 2'd0 :
        !dp_active_owner ? 2'd2 : 2'd3;
    assign diagnostic_load_active = load_active;
    assign diagnostic_compute_active = mac_diagnostic_active;
    assign diagnostic_write_active = write_active;
    assign diagnostic_mac_good_group = mac_diagnostic_good_group;
    assign diagnostic_mac_good_slots = mac_diagnostic_good_slots;
    assign diagnostic_mac_starve = mac_diagnostic_starve;
    assign diagnostic_mac_output_stall = mac_diagnostic_output_stall;
    assign diagnostic_residency_hit = resident_cmd_valid && resident_cmd_ready &&
                                      !resident_downstream_cmd_valid;
    assign diagnostic_residency_miss = resident_downstream_cmd_valid && directory_ready;
    assign drain_complete = all_io_quiet;
    assign active = command_active_q || event_active || load_active || tile_active ||
        scheduler_active || directory_active || parameter_active || write_active || pack_active || pk_valid;
    assign fault = event_fault || load_ctrl_fault || pf_reader_fault || pf_order_error ||
        directory_fault || directory_reader_fault || parameter_fault || parameter_reader_fault ||
        bridge_fault || write_fault || output_writer_fault || datapath_fault ||
        scheduler_fault || scheduler_abort || dp_protocol_fault || physical_protocol_fault;
    assign fault_code = event_fault ? event_fault_code :
        load_ctrl_fault ? load_ctrl_fault_code :
        write_fault ? write_fault_code :
        parameter_fault ? parameter_fault_code :
        directory_fault ? directory_fault_code :
        output_writer_fault ? output_writer_fault_code :
        scheduler_fault ? {1'b0,scheduler_fault_code} :
        (scheduler_abort || dp_protocol_fault || physical_protocol_fault) ? 4'd14 : 4'd0;
    assign needs_drain = fault && !all_io_quiet;

    assign producer_complete_epoch = epoch_q;
    assign producer_complete_event = event_q;
    assign producer_complete_model_crc = model_crc_q;
    assign producer_complete_job_base = job_base_q;
    assign producer_complete_token_base = token_base_q;
    assign producer_complete_tag_base = tag_base_q;
    assign producer_complete_destination_generation = destination_generation_q;

    always @(posedge clk) begin
        if (!rst_n) begin
            epoch_q <= 0; model_crc_q <= 0; job_base_q <= 0; token_base_q <= 0; tag_base_q <= 0;
            event_q <= 0; first_bank_q <= 0; source_base_q <= 0; source_generation_q <= 0;
            source_region_begin_q <= 0; source_region_end_q <= 0; destination_base_q <= 0;
            destination_generation_q <= 0; destination_region_begin_q <= 0;
            destination_region_end_q <= 0; parameter_directory_base_q <= 0;
            parameter_payload_begin_q <= 0; parameter_payload_end_q <= 0; parameter_count_q <= 0;
            load_timeout_q <= 0; parameter_timeout_q <= 0; write_timeout_q <= 0;
            command_active_q <= 0;
        end else begin
            if (cmd_valid && cmd_ready) begin
                epoch_q <= cmd_epoch; model_crc_q <= cmd_model_crc; job_base_q <= cmd_job_base;
                token_base_q <= cmd_token_base; tag_base_q <= cmd_tag_base; event_q <= cmd_event;
                first_bank_q <= cmd_first_bank; source_base_q <= cmd_source_base;
                source_generation_q <= cmd_source_generation;
                source_region_begin_q <= source_lease_region_begin;
                source_region_end_q <= source_lease_region_end;
                destination_base_q <= cmd_destination_base;
                destination_generation_q <= cmd_destination_generation;
                destination_region_begin_q <= destination_reservation_region_begin;
                destination_region_end_q <= destination_reservation_region_end;
                parameter_directory_base_q <= cmd_parameter_directory_base;
                parameter_count_q <= cmd_parameter_count;
                parameter_payload_begin_q <= cmd_parameter_payload_begin;
                parameter_payload_end_q <= cmd_parameter_payload_end;
                load_timeout_q <= cmd_load_timeout_cycles;
                parameter_timeout_q <= cmd_parameter_timeout_cycles;
                write_timeout_q <= cmd_write_timeout_cycles;
                command_active_q <= 1'b1;
            end else if (producer_complete || (fault && all_io_quiet)) begin
                command_active_q <= 1'b0;
            end
        end
    end

`ifdef FORMAL
    // Intentionally empty: this top carries no simulation-only assumptions.
`endif
    assign aux_feature_cfg_begin_ready = feature_cfg_begin_ready_v10;
    assign aux_feature_load_store_valid = feature_load_store_valid;
    assign aux_feature_load_loading = feature_load_loading;
    assign aux_feature_load_active_epoch = feature_load_active_epoch;
    assign aux_feature_cfg_word_ready = feature_cfg_word_ready;
    assign aux_feature_cfg_commit_ready = feature_cfg_commit_ready_v10;
    assign aux_feature_store_valid = feature_store_valid;
    assign aux_feature_loading = feature_loading;
    assign aux_feature_active_epoch = feature_active_epoch;
    assign aux_feature_error_valid = feature_error_q;
    assign aux_feature_error_code = feature_error_code_q;
endmodule
`default_nettype wire
