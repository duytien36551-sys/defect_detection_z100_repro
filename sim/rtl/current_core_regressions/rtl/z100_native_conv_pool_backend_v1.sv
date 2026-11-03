`timescale 1ns/1ps
`default_nettype none
module z100_native_conv_pool_backend_v1 #(
    parameter integer SITES = 12,
    parameter integer SITE_FIFO_DEPTH = 4,
    parameter MAP_FILE = "conv_event_map.hex",
    parameter TILE_FILE = "conv_tiles.hex",
    parameter [31:0] MODEL_CRC = 32'd2213989717
) (
    input wire  clk,
    input wire  rst_n,
    input wire  cmd_valid,
    output wire  cmd_ready,
    input wire [31:0] cmd_epoch,
    input wire [7:0] cmd_event,
    input wire [31:0] cmd_model_crc,
    input wire [31:0] cmd_job_base,
    input wire [31:0] cmd_token_base,
    input wire [31:0] cmd_tag_base,
    input wire  cmd_first_bank,
    input wire [31:0] cmd_source_base,
    input wire [31:0] cmd_source_generation,
    input wire  source_lease_valid,
    input wire [31:0] source_lease_generation,
    input wire [31:0] source_lease_region_begin,
    input wire [32:0] source_lease_region_end,
    input wire [31:0] cmd_destination_base,
    input wire [31:0] cmd_destination_generation,
    input wire  destination_reservation_valid,
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
    input wire  cancel,
    output wire  active,
    output wire  fault,
    output wire [3:0] fault_code,
    output wire  needs_drain,
    output wire  drain_complete,
    output wire  all_io_quiet,
    output wire  producer_context_valid,
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
    output wire  producer_complete,
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
    output wire  m_axi_arvalid,
    input wire  m_axi_arready,
    input wire [5:0] m_axi_rid,
    input wire [63:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire  m_axi_rlast,
    input wire  m_axi_rvalid,
    output wire  m_axi_rready,
    output wire [5:0] m_axi_awid,
    output wire [31:0] m_axi_awaddr,
    output wire [3:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output wire  m_axi_awvalid,
    input wire  m_axi_awready,
    output wire [5:0] m_axi_wid,
    output wire [63:0] m_axi_wdata,
    output wire [7:0] m_axi_wstrb,
    output wire  m_axi_wlast,
    output wire  m_axi_wvalid,
    input wire  m_axi_wready,
    input wire [5:0] m_axi_bid,
    input wire [1:0] m_axi_bresp,
    input wire  m_axi_bvalid,
    output wire  m_axi_bready
);
    reg owner_valid, owner_pool;
    // periph_flat_v3: aux_owner_q == owner_valid && owner_pool at every edge
    // (same next-state updates). A register instead of a LUT, with fanout
    // replication: the AND output drove 661 loads (feature cfg muxes).
    (* max_fanout = 64 *) reg aux_owner_q;
    wire select_pool=cmd_event==8'd70 || cmd_event==8'd71 || cmd_event==8'd72;
    wire  conv_cmd_ready;
    wire  conv_active;
    wire  conv_fault;
    wire [3:0] conv_fault_code;
    wire  conv_needs_drain;
    wire  conv_drain_complete;
    wire  conv_all_io_quiet;
    wire  conv_producer_context_valid;
    wire [15:0] conv_producer_cin;
    wire [15:0] conv_producer_input_height;
    wire [15:0] conv_producer_input_width;
    wire [15:0] conv_producer_cout;
    wire [15:0] conv_producer_output_height;
    wire [15:0] conv_producer_output_width;
    wire [15:0] conv_producer_kernel;
    wire [15:0] conv_producer_stride;
    wire [15:0] conv_producer_padding;
    wire [15:0] conv_producer_parameter_first;
    wire [7:0] conv_producer_event;
    wire  conv_producer_complete;
    wire [31:0] conv_producer_complete_epoch;
    wire [7:0] conv_producer_complete_event;
    wire [31:0] conv_producer_complete_model_crc;
    wire [31:0] conv_producer_complete_job_base;
    wire [31:0] conv_producer_complete_token_base;
    wire [31:0] conv_producer_complete_tag_base;
    wire [31:0] conv_producer_complete_destination_generation;
    wire [7:0] conv_producer_complete_tiles;
    wire [1:0] conv_diagnostic_read_kind;
    wire conv_diagnostic_load_active,conv_diagnostic_compute_active;
    wire conv_diagnostic_write_active,conv_diagnostic_mac_good_group;
    wire [10:0] conv_diagnostic_mac_good_slots;
    wire conv_diagnostic_mac_starve,conv_diagnostic_mac_output_stall;
    wire conv_diagnostic_residency_hit,conv_diagnostic_residency_miss;
    wire [5:0] conv_m_axi_arid;
    wire [31:0] conv_m_axi_araddr;
    wire [3:0] conv_m_axi_arlen;
    wire [2:0] conv_m_axi_arsize;
    wire [1:0] conv_m_axi_arburst;
    wire  conv_m_axi_arvalid;
    wire  conv_m_axi_rready;
    wire [5:0] conv_m_axi_awid;
    wire [31:0] conv_m_axi_awaddr;
    wire [3:0] conv_m_axi_awlen;
    wire [2:0] conv_m_axi_awsize;
    wire [1:0] conv_m_axi_awburst;
    wire  conv_m_axi_awvalid;
    wire [5:0] conv_m_axi_wid;
    wire [63:0] conv_m_axi_wdata;
    wire [7:0] conv_m_axi_wstrb;
    wire  conv_m_axi_wlast;
    wire  conv_m_axi_wvalid;
    wire  conv_m_axi_bready;
    wire  pool_cmd_ready;
    wire  pool_active;
    wire  pool_fault;
    wire [3:0] pool_fault_code;
    wire  pool_needs_drain;
    wire  pool_drain_complete;
    wire  pool_all_io_quiet;
    wire  pool_producer_context_valid;
    wire [15:0] pool_producer_cin;
    wire [15:0] pool_producer_input_height;
    wire [15:0] pool_producer_input_width;
    wire [15:0] pool_producer_cout;
    wire [15:0] pool_producer_output_height;
    wire [15:0] pool_producer_output_width;
    wire [15:0] pool_producer_kernel;
    wire [15:0] pool_producer_stride;
    wire [15:0] pool_producer_padding;
    wire [15:0] pool_producer_parameter_first;
    wire [7:0] pool_producer_event;
    wire  pool_producer_complete;
    wire [31:0] pool_producer_complete_epoch;
    wire [7:0] pool_producer_complete_event;
    wire [31:0] pool_producer_complete_model_crc;
    wire [31:0] pool_producer_complete_job_base;
    wire [31:0] pool_producer_complete_token_base;
    wire [31:0] pool_producer_complete_tag_base;
    wire [31:0] pool_producer_complete_destination_generation;
    wire [7:0] pool_producer_complete_tiles;
    wire pool_diagnostic_load_active,pool_diagnostic_write_active;
    wire [5:0] pool_m_axi_arid;
    wire [31:0] pool_m_axi_araddr;
    wire [3:0] pool_m_axi_arlen;
    wire [2:0] pool_m_axi_arsize;
    wire [1:0] pool_m_axi_arburst;
    wire  pool_m_axi_arvalid;
    wire  pool_m_axi_rready;
    wire [5:0] pool_m_axi_awid;
    wire [31:0] pool_m_axi_awaddr;
    wire [3:0] pool_m_axi_awlen;
    wire [2:0] pool_m_axi_awsize;
    wire [1:0] pool_m_axi_awburst;
    wire  pool_m_axi_awvalid;
    wire [5:0] pool_m_axi_wid;
    wire [63:0] pool_m_axi_wdata;
    wire [7:0] pool_m_axi_wstrb;
    wire  pool_m_axi_wlast;
    wire  pool_m_axi_wvalid;
    wire  pool_m_axi_bready;
    wire  aux_cancel;
    wire  aux_pool_job_valid;
    wire  aux_pool_job_ready;
    wire [31:0] aux_pool_job_epoch;
    wire [10:0] aux_pool_job_channels;
    wire [9:0] aux_pool_job_height;
    wire [9:0] aux_pool_job_width;
    wire  aux_pool_packed_valid;
    wire  aux_pool_packed_ready;
    wire [31:0] aux_pool_packed_epoch;
    wire [12:0] aux_pool_packed_address;
    wire [511:0] aux_pool_packed_data;
    wire  aux_pool_packed_last;
    wire  aux_pool_done;
    wire  aux_pool_error;
    wire [3:0] aux_pool_error_code;
    wire  aux_pool_active;
    wire  aux_feature_cfg_begin;
    wire  aux_feature_cfg_begin_ready;
    wire  aux_feature_cfg_canonical_order;
    wire  aux_feature_load_bank;
    wire  aux_compute_source_bank;
    wire  aux_feature_load_store_valid;
    wire  aux_feature_load_loading;
    wire [31:0] aux_feature_load_active_epoch;
    wire [31:0] aux_feature_cfg_epoch;
    wire [10:0] aux_feature_cfg_channels;
    wire [9:0] aux_feature_cfg_height;
    wire [9:0] aux_feature_cfg_width;
    wire [31:0] aux_feature_cfg_word_epoch;
    wire [12:0] aux_feature_cfg_word_address;
    wire  aux_feature_cfg_word_last;
    wire  aux_feature_cfg_word_valid;
    wire  aux_feature_cfg_word_ready;
    wire [511:0] aux_feature_cfg_data;
    wire  aux_feature_cfg_commit;
    wire  aux_feature_cfg_commit_ready;
    wire  aux_feature_store_valid;
    wire  aux_feature_loading;
    wire [31:0] aux_feature_active_epoch;
    wire  aux_feature_error_valid;
    wire [3:0] aux_feature_error_code;
    wire permit=!owner_valid && !conv_active && !pool_active && !conv_fault && !pool_fault && conv_all_io_quiet && pool_all_io_quiet;
    assign cmd_ready=rst_n && permit && (select_pool ? pool_cmd_ready : conv_cmd_ready);
    wire accepted=cmd_valid && cmd_ready;
    assign all_io_quiet=conv_all_io_quiet && pool_all_io_quiet;
    assign drain_complete=all_io_quiet;
    assign active=owner_valid || conv_active || pool_active;
    assign fault=owner_valid ? (owner_pool ? pool_fault : conv_fault) : (conv_fault || pool_fault);
    assign fault_code=owner_pool ? pool_fault_code : conv_fault_code;
    assign needs_drain=fault && !all_io_quiet;
    assign producer_complete=owner_valid && all_io_quiet && !fault && (owner_pool ? pool_producer_complete : conv_producer_complete);
    assign diagnostic_read_kind=!owner_valid ? 2'd0 :
        owner_pool ? 2'd1 : conv_diagnostic_read_kind;
    assign diagnostic_load_active=owner_valid &&
        (owner_pool ? pool_diagnostic_load_active : conv_diagnostic_load_active);
    assign diagnostic_compute_active=owner_valid && !owner_pool &&
        conv_diagnostic_compute_active;
    assign diagnostic_write_active=owner_valid &&
        (owner_pool ? pool_diagnostic_write_active : conv_diagnostic_write_active);
    assign diagnostic_mac_good_group=!owner_pool && conv_diagnostic_mac_good_group;
    assign diagnostic_mac_good_slots=owner_pool ? 11'd0 : conv_diagnostic_mac_good_slots;
    assign diagnostic_mac_starve=!owner_pool && conv_diagnostic_mac_starve;
    assign diagnostic_mac_output_stall=!owner_pool && conv_diagnostic_mac_output_stall;
    assign diagnostic_residency_hit=!owner_pool && conv_diagnostic_residency_hit;
    assign diagnostic_residency_miss=!owner_pool && conv_diagnostic_residency_miss;
    always @(posedge clk) begin
        if(!rst_n) begin owner_valid<=0;owner_pool<=0;aux_owner_q<=0;end
        else begin
            if(accepted) begin owner_valid<=1;owner_pool<=select_pool;aux_owner_q<=select_pool;end
            if(producer_complete) begin owner_valid<=0;aux_owner_q<=0;end
            // No fault/cancel release. Owner is retained until coordinated reset.
        end
    end
    assign producer_context_valid=owner_pool ? pool_producer_context_valid : conv_producer_context_valid;
    assign producer_cin=owner_pool ? pool_producer_cin : conv_producer_cin;
    assign producer_input_height=owner_pool ? pool_producer_input_height : conv_producer_input_height;
    assign producer_input_width=owner_pool ? pool_producer_input_width : conv_producer_input_width;
    assign producer_cout=owner_pool ? pool_producer_cout : conv_producer_cout;
    assign producer_output_height=owner_pool ? pool_producer_output_height : conv_producer_output_height;
    assign producer_output_width=owner_pool ? pool_producer_output_width : conv_producer_output_width;
    assign producer_kernel=owner_pool ? pool_producer_kernel : conv_producer_kernel;
    assign producer_stride=owner_pool ? pool_producer_stride : conv_producer_stride;
    assign producer_padding=owner_pool ? pool_producer_padding : conv_producer_padding;
    assign producer_parameter_first=owner_pool ? pool_producer_parameter_first : conv_producer_parameter_first;
    assign producer_event=owner_pool ? pool_producer_event : conv_producer_event;
    assign producer_complete_epoch=owner_pool ? pool_producer_complete_epoch : conv_producer_complete_epoch;
    assign producer_complete_event=owner_pool ? pool_producer_complete_event : conv_producer_complete_event;
    assign producer_complete_model_crc=owner_pool ? pool_producer_complete_model_crc : conv_producer_complete_model_crc;
    assign producer_complete_job_base=owner_pool ? pool_producer_complete_job_base : conv_producer_complete_job_base;
    assign producer_complete_token_base=owner_pool ? pool_producer_complete_token_base : conv_producer_complete_token_base;
    assign producer_complete_tag_base=owner_pool ? pool_producer_complete_tag_base : conv_producer_complete_tag_base;
    assign producer_complete_destination_generation=owner_pool ? pool_producer_complete_destination_generation : conv_producer_complete_destination_generation;
    assign producer_complete_tiles=owner_pool ? pool_producer_complete_tiles : conv_producer_complete_tiles;
    assign m_axi_arid=owner_pool ? pool_m_axi_arid : conv_m_axi_arid;
    assign m_axi_araddr=owner_pool ? pool_m_axi_araddr : conv_m_axi_araddr;
    assign m_axi_arlen=owner_pool ? pool_m_axi_arlen : conv_m_axi_arlen;
    assign m_axi_arsize=owner_pool ? pool_m_axi_arsize : conv_m_axi_arsize;
    assign m_axi_arburst=owner_pool ? pool_m_axi_arburst : conv_m_axi_arburst;
    assign m_axi_arvalid=owner_pool ? pool_m_axi_arvalid : conv_m_axi_arvalid;
    assign m_axi_rready=owner_pool ? pool_m_axi_rready : conv_m_axi_rready;
    assign m_axi_awid=owner_pool ? pool_m_axi_awid : conv_m_axi_awid;
    assign m_axi_awaddr=owner_pool ? pool_m_axi_awaddr : conv_m_axi_awaddr;
    assign m_axi_awlen=owner_pool ? pool_m_axi_awlen : conv_m_axi_awlen;
    assign m_axi_awsize=owner_pool ? pool_m_axi_awsize : conv_m_axi_awsize;
    assign m_axi_awburst=owner_pool ? pool_m_axi_awburst : conv_m_axi_awburst;
    assign m_axi_awvalid=owner_pool ? pool_m_axi_awvalid : conv_m_axi_awvalid;
    assign m_axi_wid=owner_pool ? pool_m_axi_wid : conv_m_axi_wid;
    assign m_axi_wdata=owner_pool ? pool_m_axi_wdata : conv_m_axi_wdata;
    assign m_axi_wstrb=owner_pool ? pool_m_axi_wstrb : conv_m_axi_wstrb;
    assign m_axi_wlast=owner_pool ? pool_m_axi_wlast : conv_m_axi_wlast;
    assign m_axi_wvalid=owner_pool ? pool_m_axi_wvalid : conv_m_axi_wvalid;
    assign m_axi_bready=owner_pool ? pool_m_axi_bready : conv_m_axi_bready;
    z100_native_conv_backend_v13c_shared #(.SITES(SITES),.SITE_FIFO_DEPTH(SITE_FIFO_DEPTH),.MAP_FILE(MAP_FILE),.TILE_FILE(TILE_FILE),.MODEL_CRC(MODEL_CRC)) conv_backend (
        .clk(clk),
        .rst_n(rst_n),
        .aux_owner(aux_owner_q),
        .aux_cancel(aux_cancel),
        .aux_pool_job_valid(aux_pool_job_valid),
        .aux_pool_job_ready(aux_pool_job_ready),
        .aux_pool_job_epoch(aux_pool_job_epoch),
        .aux_pool_job_channels(aux_pool_job_channels),
        .aux_pool_job_height(aux_pool_job_height),
        .aux_pool_job_width(aux_pool_job_width),
        .aux_pool_packed_valid(aux_pool_packed_valid),
        .aux_pool_packed_ready(aux_pool_packed_ready),
        .aux_pool_packed_epoch(aux_pool_packed_epoch),
        .aux_pool_packed_address(aux_pool_packed_address),
        .aux_pool_packed_data(aux_pool_packed_data),
        .aux_pool_packed_last(aux_pool_packed_last),
        .aux_pool_done(aux_pool_done),
        .aux_pool_error(aux_pool_error),
        .aux_pool_error_code(aux_pool_error_code),
        .aux_pool_active(aux_pool_active),
        .aux_feature_cfg_begin(aux_feature_cfg_begin),
        .aux_feature_cfg_begin_ready(aux_feature_cfg_begin_ready),
        .aux_feature_cfg_canonical_order(aux_feature_cfg_canonical_order),
        .aux_feature_load_bank(aux_feature_load_bank),
        .aux_compute_source_bank(aux_compute_source_bank),
        .aux_feature_load_store_valid(aux_feature_load_store_valid),
        .aux_feature_load_loading(aux_feature_load_loading),
        .aux_feature_load_active_epoch(aux_feature_load_active_epoch),
        .aux_feature_cfg_epoch(aux_feature_cfg_epoch),
        .aux_feature_cfg_channels(aux_feature_cfg_channels),
        .aux_feature_cfg_height(aux_feature_cfg_height),
        .aux_feature_cfg_width(aux_feature_cfg_width),
        .aux_feature_cfg_word_epoch(aux_feature_cfg_word_epoch),
        .aux_feature_cfg_word_address(aux_feature_cfg_word_address),
        .aux_feature_cfg_word_last(aux_feature_cfg_word_last),
        .aux_feature_cfg_word_valid(aux_feature_cfg_word_valid),
        .aux_feature_cfg_word_ready(aux_feature_cfg_word_ready),
        .aux_feature_cfg_data(aux_feature_cfg_data),
        .aux_feature_cfg_commit(aux_feature_cfg_commit),
        .aux_feature_cfg_commit_ready(aux_feature_cfg_commit_ready),
        .aux_feature_store_valid(aux_feature_store_valid),
        .aux_feature_loading(aux_feature_loading),
        .aux_feature_active_epoch(aux_feature_active_epoch),
        .aux_feature_error_valid(aux_feature_error_valid),
        .aux_feature_error_code(aux_feature_error_code),
        .cmd_valid(cmd_valid && permit && !select_pool),
        .cmd_ready(conv_cmd_ready),
        .cmd_epoch(cmd_epoch),
        .cmd_event(cmd_event),
        .cmd_model_crc(cmd_model_crc),
        .cmd_job_base(cmd_job_base),
        .cmd_token_base(cmd_token_base),
        .cmd_tag_base(cmd_tag_base),
        .cmd_first_bank(cmd_first_bank),
        .cmd_source_base(cmd_source_base),
        .cmd_source_generation(cmd_source_generation),
        .source_lease_valid(source_lease_valid),
        .source_lease_generation(source_lease_generation),
        .source_lease_region_begin(source_lease_region_begin),
        .source_lease_region_end(source_lease_region_end),
        .cmd_destination_base(cmd_destination_base),
        .cmd_destination_generation(cmd_destination_generation),
        .destination_reservation_valid(destination_reservation_valid),
        .destination_reservation_generation(destination_reservation_generation),
        .destination_reservation_region_begin(destination_reservation_region_begin),
        .destination_reservation_region_end(destination_reservation_region_end),
        .cmd_parameter_directory_base(cmd_parameter_directory_base),
        .cmd_parameter_count(cmd_parameter_count),
        .cmd_parameter_payload_begin(cmd_parameter_payload_begin),
        .cmd_parameter_payload_end(cmd_parameter_payload_end),
        .cmd_load_timeout_cycles(cmd_load_timeout_cycles),
        .cmd_parameter_timeout_cycles(cmd_parameter_timeout_cycles),
        .cmd_write_timeout_cycles(cmd_write_timeout_cycles),
        .cancel(cancel),
        .active(conv_active),
        .fault(conv_fault),
        .fault_code(conv_fault_code),
        .needs_drain(conv_needs_drain),
        .drain_complete(conv_drain_complete),
        .all_io_quiet(conv_all_io_quiet),
        .producer_context_valid(conv_producer_context_valid),
        .producer_cin(conv_producer_cin),
        .producer_input_height(conv_producer_input_height),
        .producer_input_width(conv_producer_input_width),
        .producer_cout(conv_producer_cout),
        .producer_output_height(conv_producer_output_height),
        .producer_output_width(conv_producer_output_width),
        .producer_kernel(conv_producer_kernel),
        .producer_stride(conv_producer_stride),
        .producer_padding(conv_producer_padding),
        .producer_parameter_first(conv_producer_parameter_first),
        .producer_event(conv_producer_event),
        .producer_complete(conv_producer_complete),
        .producer_complete_epoch(conv_producer_complete_epoch),
        .producer_complete_event(conv_producer_complete_event),
        .producer_complete_model_crc(conv_producer_complete_model_crc),
        .producer_complete_job_base(conv_producer_complete_job_base),
        .producer_complete_token_base(conv_producer_complete_token_base),
        .producer_complete_tag_base(conv_producer_complete_tag_base),
        .producer_complete_destination_generation(conv_producer_complete_destination_generation),
        .producer_complete_tiles(conv_producer_complete_tiles),
        .diagnostic_read_kind(conv_diagnostic_read_kind),
        .diagnostic_load_active(conv_diagnostic_load_active),
        .diagnostic_compute_active(conv_diagnostic_compute_active),
        .diagnostic_write_active(conv_diagnostic_write_active),
        .diagnostic_mac_good_group(conv_diagnostic_mac_good_group),
        .diagnostic_mac_good_slots(conv_diagnostic_mac_good_slots),
        .diagnostic_mac_starve(conv_diagnostic_mac_starve),
        .diagnostic_mac_output_stall(conv_diagnostic_mac_output_stall),
        .diagnostic_residency_hit(conv_diagnostic_residency_hit),
        .diagnostic_residency_miss(conv_diagnostic_residency_miss),
        .m_axi_arid(conv_m_axi_arid),
        .m_axi_araddr(conv_m_axi_araddr),
        .m_axi_arlen(conv_m_axi_arlen),
        .m_axi_arsize(conv_m_axi_arsize),
        .m_axi_arburst(conv_m_axi_arburst),
        .m_axi_arvalid(conv_m_axi_arvalid),
        .m_axi_arready((!owner_pool) ? m_axi_arready : '0),
        .m_axi_rid((!owner_pool) ? m_axi_rid : '0),
        .m_axi_rdata((!owner_pool) ? m_axi_rdata : '0),
        .m_axi_rresp((!owner_pool) ? m_axi_rresp : '0),
        .m_axi_rlast((!owner_pool) ? m_axi_rlast : '0),
        .m_axi_rvalid((!owner_pool) ? m_axi_rvalid : '0),
        .m_axi_rready(conv_m_axi_rready),
        .m_axi_awid(conv_m_axi_awid),
        .m_axi_awaddr(conv_m_axi_awaddr),
        .m_axi_awlen(conv_m_axi_awlen),
        .m_axi_awsize(conv_m_axi_awsize),
        .m_axi_awburst(conv_m_axi_awburst),
        .m_axi_awvalid(conv_m_axi_awvalid),
        .m_axi_awready((!owner_pool) ? m_axi_awready : '0),
        .m_axi_wid(conv_m_axi_wid),
        .m_axi_wdata(conv_m_axi_wdata),
        .m_axi_wstrb(conv_m_axi_wstrb),
        .m_axi_wlast(conv_m_axi_wlast),
        .m_axi_wvalid(conv_m_axi_wvalid),
        .m_axi_wready((!owner_pool) ? m_axi_wready : '0),
        .m_axi_bid((!owner_pool) ? m_axi_bid : '0),
        .m_axi_bresp((!owner_pool) ? m_axi_bresp : '0),
        .m_axi_bvalid((!owner_pool) ? m_axi_bvalid : '0),
        .m_axi_bready(conv_m_axi_bready)
    );
    z100_native_pool_backend_v1 #(.MODEL_CRC(MODEL_CRC)) pool_backend (
        .clk(clk),
        .rst_n(rst_n),
        .cmd_valid(cmd_valid && permit && select_pool),
        .cmd_ready(pool_cmd_ready),
        .cmd_epoch(cmd_epoch),
        .cmd_event(cmd_event),
        .cmd_model_crc(cmd_model_crc),
        .cmd_job_base(cmd_job_base),
        .cmd_token_base(cmd_token_base),
        .cmd_tag_base(cmd_tag_base),
        .cmd_first_bank(cmd_first_bank),
        .cmd_source_base(cmd_source_base),
        .cmd_source_generation(cmd_source_generation),
        .source_lease_valid(source_lease_valid),
        .source_lease_generation(source_lease_generation),
        .source_lease_region_begin(source_lease_region_begin),
        .source_lease_region_end(source_lease_region_end),
        .cmd_destination_base(cmd_destination_base),
        .cmd_destination_generation(cmd_destination_generation),
        .destination_reservation_valid(destination_reservation_valid),
        .destination_reservation_generation(destination_reservation_generation),
        .destination_reservation_region_begin(destination_reservation_region_begin),
        .destination_reservation_region_end(destination_reservation_region_end),
        .cmd_parameter_directory_base(cmd_parameter_directory_base),
        .cmd_parameter_count(cmd_parameter_count),
        .cmd_parameter_payload_begin(cmd_parameter_payload_begin),
        .cmd_parameter_payload_end(cmd_parameter_payload_end),
        .cmd_load_timeout_cycles(cmd_load_timeout_cycles),
        .cmd_parameter_timeout_cycles(cmd_parameter_timeout_cycles),
        .cmd_write_timeout_cycles(cmd_write_timeout_cycles),
        .cancel(cancel),
        .active(pool_active),
        .fault(pool_fault),
        .fault_code(pool_fault_code),
        .needs_drain(pool_needs_drain),
        .drain_complete(pool_drain_complete),
        .all_io_quiet(pool_all_io_quiet),
        .producer_context_valid(pool_producer_context_valid),
        .producer_cin(pool_producer_cin),
        .producer_input_height(pool_producer_input_height),
        .producer_input_width(pool_producer_input_width),
        .producer_cout(pool_producer_cout),
        .producer_output_height(pool_producer_output_height),
        .producer_output_width(pool_producer_output_width),
        .producer_kernel(pool_producer_kernel),
        .producer_stride(pool_producer_stride),
        .producer_padding(pool_producer_padding),
        .producer_parameter_first(pool_producer_parameter_first),
        .producer_event(pool_producer_event),
        .producer_complete(pool_producer_complete),
        .producer_complete_epoch(pool_producer_complete_epoch),
        .producer_complete_event(pool_producer_complete_event),
        .producer_complete_model_crc(pool_producer_complete_model_crc),
        .producer_complete_job_base(pool_producer_complete_job_base),
        .producer_complete_token_base(pool_producer_complete_token_base),
        .producer_complete_tag_base(pool_producer_complete_tag_base),
        .producer_complete_destination_generation(pool_producer_complete_destination_generation),
        .producer_complete_tiles(pool_producer_complete_tiles),
        .diagnostic_load_active(pool_diagnostic_load_active),
        .diagnostic_write_active(pool_diagnostic_write_active),
        .m_axi_arid(pool_m_axi_arid),
        .m_axi_araddr(pool_m_axi_araddr),
        .m_axi_arlen(pool_m_axi_arlen),
        .m_axi_arsize(pool_m_axi_arsize),
        .m_axi_arburst(pool_m_axi_arburst),
        .m_axi_arvalid(pool_m_axi_arvalid),
        .m_axi_arready((owner_pool) ? m_axi_arready : '0),
        .m_axi_rid((owner_pool) ? m_axi_rid : '0),
        .m_axi_rdata((owner_pool) ? m_axi_rdata : '0),
        .m_axi_rresp((owner_pool) ? m_axi_rresp : '0),
        .m_axi_rlast((owner_pool) ? m_axi_rlast : '0),
        .m_axi_rvalid((owner_pool) ? m_axi_rvalid : '0),
        .m_axi_rready(pool_m_axi_rready),
        .m_axi_awid(pool_m_axi_awid),
        .m_axi_awaddr(pool_m_axi_awaddr),
        .m_axi_awlen(pool_m_axi_awlen),
        .m_axi_awsize(pool_m_axi_awsize),
        .m_axi_awburst(pool_m_axi_awburst),
        .m_axi_awvalid(pool_m_axi_awvalid),
        .m_axi_awready((owner_pool) ? m_axi_awready : '0),
        .m_axi_wid(pool_m_axi_wid),
        .m_axi_wdata(pool_m_axi_wdata),
        .m_axi_wstrb(pool_m_axi_wstrb),
        .m_axi_wlast(pool_m_axi_wlast),
        .m_axi_wvalid(pool_m_axi_wvalid),
        .m_axi_wready((owner_pool) ? m_axi_wready : '0),
        .m_axi_bid((owner_pool) ? m_axi_bid : '0),
        .m_axi_bresp((owner_pool) ? m_axi_bresp : '0),
        .m_axi_bvalid((owner_pool) ? m_axi_bvalid : '0),
        .m_axi_bready(pool_m_axi_bready),
        .aux_owner(),
        .aux_cancel(aux_cancel),
        .aux_pool_job_valid(aux_pool_job_valid),
        .aux_pool_job_ready(aux_pool_job_ready),
        .aux_pool_job_epoch(aux_pool_job_epoch),
        .aux_pool_job_channels(aux_pool_job_channels),
        .aux_pool_job_height(aux_pool_job_height),
        .aux_pool_job_width(aux_pool_job_width),
        .aux_pool_packed_valid(aux_pool_packed_valid),
        .aux_pool_packed_ready(aux_pool_packed_ready),
        .aux_pool_packed_epoch(aux_pool_packed_epoch),
        .aux_pool_packed_address(aux_pool_packed_address),
        .aux_pool_packed_data(aux_pool_packed_data),
        .aux_pool_packed_last(aux_pool_packed_last),
        .aux_pool_done(aux_pool_done),
        .aux_pool_error(aux_pool_error),
        .aux_pool_error_code(aux_pool_error_code),
        .aux_pool_active(aux_pool_active),
        .aux_feature_cfg_begin(aux_feature_cfg_begin),
        .aux_feature_cfg_begin_ready(aux_feature_cfg_begin_ready),
        .aux_feature_cfg_canonical_order(aux_feature_cfg_canonical_order),
        .aux_feature_load_bank(aux_feature_load_bank),
        .aux_compute_source_bank(aux_compute_source_bank),
        .aux_feature_load_store_valid(aux_feature_load_store_valid),
        .aux_feature_load_loading(aux_feature_load_loading),
        .aux_feature_load_active_epoch(aux_feature_load_active_epoch),
        .aux_feature_cfg_epoch(aux_feature_cfg_epoch),
        .aux_feature_cfg_channels(aux_feature_cfg_channels),
        .aux_feature_cfg_height(aux_feature_cfg_height),
        .aux_feature_cfg_width(aux_feature_cfg_width),
        .aux_feature_cfg_word_epoch(aux_feature_cfg_word_epoch),
        .aux_feature_cfg_word_address(aux_feature_cfg_word_address),
        .aux_feature_cfg_word_last(aux_feature_cfg_word_last),
        .aux_feature_cfg_word_valid(aux_feature_cfg_word_valid),
        .aux_feature_cfg_word_ready(aux_feature_cfg_word_ready),
        .aux_feature_cfg_data(aux_feature_cfg_data),
        .aux_feature_cfg_commit(aux_feature_cfg_commit),
        .aux_feature_cfg_commit_ready(aux_feature_cfg_commit_ready),
        .aux_feature_store_valid(aux_feature_store_valid),
        .aux_feature_loading(aux_feature_loading),
        .aux_feature_active_epoch(aux_feature_active_epoch),
        .aux_feature_error_valid(aux_feature_error_valid),
        .aux_feature_error_code(aux_feature_error_code)
    );
endmodule
`default_nettype wire
