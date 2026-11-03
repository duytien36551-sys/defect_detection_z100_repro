`timescale 1ns/1ps
`default_nettype none
(* use_dsp="no" *)
module z100_native_pool_backend_v1 #(parameter [31:0] MODEL_CRC=32'h83f6cd55)(
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
    output wire diagnostic_load_active,diagnostic_write_active,
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
    output wire  m_axi_bready,
    output wire  aux_owner,
    output wire  aux_cancel,
    output wire  aux_pool_job_valid,
    input wire  aux_pool_job_ready,
    output wire [31:0] aux_pool_job_epoch,
    output wire [10:0] aux_pool_job_channels,
    output wire [9:0] aux_pool_job_height,
    output wire [9:0] aux_pool_job_width,
    input wire  aux_pool_packed_valid,
    output wire  aux_pool_packed_ready,
    input wire [31:0] aux_pool_packed_epoch,
    input wire [12:0] aux_pool_packed_address,
    input wire [511:0] aux_pool_packed_data,
    input wire  aux_pool_packed_last,
    input wire  aux_pool_done,
    input wire  aux_pool_error,
    input wire [3:0] aux_pool_error_code,
    input wire  aux_pool_active,
    output wire  aux_feature_cfg_begin,
    input wire  aux_feature_cfg_begin_ready,
    output wire  aux_feature_cfg_canonical_order,
    output wire  aux_feature_load_bank,
    output wire  aux_compute_source_bank,
    input wire  aux_feature_load_store_valid,
    input wire  aux_feature_load_loading,
    input wire [31:0] aux_feature_load_active_epoch,
    output wire [31:0] aux_feature_cfg_epoch,
    output wire [10:0] aux_feature_cfg_channels,
    output wire [9:0] aux_feature_cfg_height,
    output wire [9:0] aux_feature_cfg_width,
    output wire [31:0] aux_feature_cfg_word_epoch,
    output wire [12:0] aux_feature_cfg_word_address,
    output wire  aux_feature_cfg_word_last,
    output wire  aux_feature_cfg_word_valid,
    input wire  aux_feature_cfg_word_ready,
    output wire [511:0] aux_feature_cfg_data,
    output wire  aux_feature_cfg_commit,
    input wire  aux_feature_cfg_commit_ready,
    input wire  aux_feature_store_valid,
    input wire  aux_feature_loading,
    input wire [31:0] aux_feature_active_epoch,
    input wire  aux_feature_error_valid,
    input wire [3:0] aux_feature_error_code
);
    localparam [3:0] IDLE=0, LOAD_CMD=1, LOAD_WAIT=2, WRITE_CMD=3,
                     POOL_CMD=4, RUN=5, RETIRE=6, FAILED=7;
    reg [3:0] state;
    reg [31:0] epoch_q,event_job_q,token_q,tag_q,crc_q;
    reg [31:0] ledger_epoch,ledger_job;
    reg [7:0] event_q;
    reg bank_q;
    reg [31:0] source_q,source_gen_q,source_begin_q,dest_q,dest_gen_q,dest_begin_q;
    reg [32:0] source_end_q,dest_end_q;
    reg [31:0] load_timeout_q,compute_timeout_q,write_timeout_q,compute_elapsed;
    reg pool_seen,write_seen;
    reg fault_q;
    reg [3:0] code_q;
    wire running=state!=IDLE && state!=FAILED;
    wire event_good=cmd_event==8'd70 || cmd_event==8'd71 || cmd_event==8'd72;
    wire [32:0] source_limit={1'b0,cmd_source_base}+33'd81920;
    wire [32:0] dest_limit={1'b0,cmd_destination_base}+33'd81920;
    wire overlap={1'b0,cmd_source_base}<dest_limit && {1'b0,cmd_destination_base}<source_limit;
    wire parameter_overlap={1'b0,cmd_destination_base}<cmd_parameter_payload_end &&
                           {1'b0,cmd_parameter_payload_begin}<dest_limit;
    wire [32:0] directory_limit={1'b0,cmd_parameter_directory_base}+
                                 ((({17'd0,cmd_parameter_count}+33'd1)>>1)<<6);
    wire directory_overlap={1'b0,cmd_destination_base}<directory_limit &&
                           {1'b0,cmd_parameter_directory_base}<dest_limit;
    wire command_good=event_good && cmd_epoch!=0 && cmd_job_base!=0 && cmd_token_base!=0 && cmd_tag_base!=0 &&
        cmd_model_crc==MODEL_CRC &&
        (cmd_epoch>ledger_epoch || (cmd_epoch==ledger_epoch && cmd_job_base>ledger_job)) &&
        source_lease_valid && destination_reservation_valid &&
        cmd_source_generation!=0 && cmd_source_generation==source_lease_generation &&
        cmd_destination_generation!=0 && cmd_destination_generation==destination_reservation_generation &&
        cmd_source_base[5:0]==0 && cmd_destination_base[5:0]==0 &&
        source_lease_region_begin[5:0]==0 && source_lease_region_end[5:0]==0 &&
        destination_reservation_region_begin[5:0]==0 && destination_reservation_region_end[5:0]==0 &&
        cmd_source_base>=source_lease_region_begin && source_limit<=source_lease_region_end &&
        cmd_destination_base>=destination_reservation_region_begin && dest_limit<=destination_reservation_region_end &&
        source_lease_region_end<=33'h040000000 && destination_reservation_region_end<=33'h040000000 &&
        !overlap && !parameter_overlap && !directory_overlap &&
        cmd_load_timeout_cycles!=0 && cmd_parameter_timeout_cycles!=0 && cmd_write_timeout_cycles!=0;
    wire lost=running && (!source_lease_valid || !destination_reservation_valid ||
        source_lease_generation!=source_gen_q || destination_reservation_generation!=dest_gen_q ||
        source_lease_region_begin!=source_begin_q || source_lease_region_end!=source_end_q ||
        destination_reservation_region_begin!=dest_begin_q || destination_reservation_region_end!=dest_end_q);

    wire l_ready,l_active,l_fault,l_done,l_committed,l_semantic_cancel,l_reader_cancel,l_reader_clear;
    wire [3:0] l_code;
    wire [31:0] l_epoch,l_generation,l_address;
    wire [10:0] l_channels;
    wire [9:0] l_height,l_width;
    wire [13:0] l_words,l_block_words,l_word_base;
    wire l_begin,l_order,l_order_ready,l_order_done,l_commit,l_reader_command;
    wire r_cmd_ready,r_busy,r_fault,r_valid,r_ready,r_last,r_done;
    wire [3:0] r_code;
    wire [31:0] r_epoch;
    wire [12:0] r_index;
    wire [511:0] r_data;
    wire load_order_error;
    wire [1:0] load_order_code;

    wire w_ready,w_active,w_fault,w_done,w_committed,w_semantic_cancel,w_writer_cancel,w_writer_clear;
    wire [3:0] w_code;
    wire [31:0] w_epoch,w_generation,w_address,w_stream_epoch;
    wire [10:0] w_channels;
    wire [9:0] w_height,w_width;
    wire w_order,w_order_ready,w_order_done;
    wire w_packed_valid,w_packed_ready,w_packed_last;
    wire [31:0] w_packed_epoch;
    wire [12:0] w_packed_index;
    wire [511:0] w_packed_data;
    wire w_command,w_command_ready,w_valid,w_stream_ready,w_stream_last;
    wire [13:0] w_words;
    wire [12:0] w_index;
    wire [511:0] w_data;
    wire writer_busy,writer_done,writer_fault;
    wire [3:0] writer_code;
    wire write_order_error;
    wire [1:0] write_order_code;
    wire compute_expired=(state==POOL_CMD || state==RUN) && compute_elapsed>=compute_timeout_q;
    wire child_error=l_fault || r_fault || load_order_error || w_fault || writer_fault || write_order_error ||
                     aux_pool_error || aux_feature_error_valid;
    // Semantic invalidation never resets either AXI adapter. They retain R/B drain ownership.
    wire abort_work=cancel || fault_q || lost || compute_expired || child_error;
    assign aux_owner=state!=IDLE;
    assign aux_cancel=abort_work;
    assign aux_feature_load_bank=bank_q;
    assign aux_compute_source_bank=bank_q;
    assign aux_feature_cfg_canonical_order=1'b0;
    assign aux_feature_cfg_epoch=l_epoch;
    assign aux_feature_cfg_channels=l_channels;
    assign aux_feature_cfg_height=l_height;
    assign aux_feature_cfg_width=l_width;
    assign aux_feature_cfg_begin=l_begin;
    assign aux_feature_cfg_commit=l_commit;
    assign aux_pool_job_valid=rst_n && state==POOL_CMD && !abort_work;
    assign aux_pool_job_epoch=epoch_q;
    assign aux_pool_job_channels=11'd128;
    assign aux_pool_job_height=10'd20;
    assign aux_pool_job_width=10'd20;
    assign cmd_ready=rst_n && state==IDLE && !fault_q && !cancel && !r_busy && !writer_busy && !child_error;
    assign active=state!=IDLE;
    assign fault=fault_q || child_error;
    assign fault_code=code_q;
    assign all_io_quiet=!r_busy && !writer_busy;
    assign drain_complete=all_io_quiet;
    assign needs_drain=fault && !all_io_quiet;
    assign producer_context_valid=state!=IDLE;
    assign producer_cin=16'd128;
    assign producer_cout=16'd128;
    assign producer_input_height=16'd20;
    assign producer_input_width=16'd20;
    assign producer_output_height=16'd20;
    assign producer_output_width=16'd20;
    assign producer_kernel=16'd5;
    assign producer_stride=16'd1;
    assign producer_padding=16'd2;
    // Pool consumes no parameter job. 0xffff is an explicit unused metadata sentinel.
    assign producer_parameter_first=16'hffff;
    assign producer_event=event_q;
    assign producer_complete=rst_n && state==RETIRE && !fault_q && all_io_quiet;
    assign producer_complete_epoch=epoch_q;
    assign producer_complete_event=event_q;
    assign producer_complete_model_crc=crc_q;
    assign producer_complete_job_base=event_job_q;
    assign producer_complete_token_base=token_q;
    assign producer_complete_tag_base=tag_q;
    assign producer_complete_destination_generation=dest_gen_q;
    assign producer_complete_tiles=8'd1;
    assign diagnostic_load_active=l_active;
    assign diagnostic_write_active=w_active;

    always @(posedge clk) begin
        if(!rst_n) begin
            state<=IDLE; fault_q<=0;code_q<=0;epoch_q<=0;event_q<=0;event_job_q<=0;token_q<=0;tag_q<=0;crc_q<=0;
            ledger_epoch<=0;ledger_job<=0;
            bank_q<=0;source_q<=0;source_gen_q<=0;source_begin_q<=0;source_end_q<=0;
            dest_q<=0;dest_gen_q<=0;dest_begin_q<=0;dest_end_q<=0;
            load_timeout_q<=0;compute_timeout_q<=0;write_timeout_q<=0;compute_elapsed<=0;pool_seen<=0;write_seen<=0;
        end else if(state!=FAILED) begin
            if(running && abort_work) begin
                state<=FAILED;fault_q<=1;
                code_q<=cancel?4'd2:lost?4'd7:compute_expired?4'd8:
                        aux_feature_error_valid?4'd6:aux_pool_error?4'd5:
                        (l_fault||r_fault||load_order_error)?4'd3:4'd4;
            end else case(state)
                IDLE:if(cmd_valid&&cmd_ready) begin
                    if(!command_good) begin state<=FAILED;fault_q<=1;code_q<=1;end
                    else begin
                        epoch_q<=cmd_epoch;event_q<=cmd_event;event_job_q<=cmd_job_base;token_q<=cmd_token_base;tag_q<=cmd_tag_base;
                        ledger_epoch<=cmd_epoch;ledger_job<=cmd_job_base;
                        crc_q<=cmd_model_crc;bank_q<=cmd_first_bank;
                        source_q<=cmd_source_base;source_gen_q<=cmd_source_generation;
                        source_begin_q<=source_lease_region_begin;source_end_q<=source_lease_region_end;
                        dest_q<=cmd_destination_base;dest_gen_q<=cmd_destination_generation;
                        dest_begin_q<=destination_reservation_region_begin;dest_end_q<=destination_reservation_region_end;
                        load_timeout_q<=cmd_load_timeout_cycles;compute_timeout_q<=cmd_parameter_timeout_cycles;
                        write_timeout_q<=cmd_write_timeout_cycles;compute_elapsed<=0;pool_seen<=0;write_seen<=0;state<=LOAD_CMD;
                    end
                end
                LOAD_CMD:if(l_ready) state<=LOAD_WAIT;
                LOAD_WAIT:if(l_done&&l_committed) state<=WRITE_CMD;
                WRITE_CMD:if(w_ready) state<=POOL_CMD;
                POOL_CMD:begin
                    if(compute_elapsed!=32'hffffffff)compute_elapsed<=compute_elapsed+1;
                    if(aux_pool_job_valid&&aux_pool_job_ready)state<=RUN;
                end
                RUN:begin
                    if(compute_elapsed!=32'hffffffff)compute_elapsed<=compute_elapsed+1;
                    if(aux_pool_done)pool_seen<=1;
                    if(w_committed)write_seen<=1;
                    if(pool_seen&&write_seen&&all_io_quiet&&!w_active&&!aux_pool_active)state<=RETIRE;
                end
                RETIRE:state<=IDLE;
                default:begin state<=FAILED;fault_q<=1;code_q<=15;end
            endcase
        end
    end

    z100_native_materialized_load_control load_control (
        .clk(clk),
        .rst_n(rst_n),
        .cmd_valid(state==LOAD_CMD && !abort_work),
        .cmd_ready(l_ready),
        .cmd_epoch(epoch_q),
        .cmd_source_generation(source_gen_q),
        .cmd_source_address(source_q),
        .cmd_timeout_cycles(load_timeout_q),
        .cmd_channels(11'd128),
        .cmd_full_height(10'd20),
        .cmd_width(10'd20),
        .cmd_first_row(10'd0),
        .cmd_height(10'd20),
        .cmd_source_committed(1'b1),
        .cmd_source_is_materialized(1'b1),
        .abort(abort_work),
        .recover(1'b0),
        .active(l_active),
        .fault(l_fault),
        .fault_code(l_code),
        .done(l_done),
        .result_committed(l_committed),
        .epoch(l_epoch),
        .source_generation(l_generation),
        .channels(l_channels),
        .height(l_height),
        .width(l_width),
        .total_words(l_words),
        .block_words(l_block_words),
        .block_word_base(l_word_base),
        .feature_begin(l_begin),
        .feature_begin_ready(aux_feature_cfg_begin_ready),
        .order_config(l_order),
        .order_config_ready(l_order_ready),
        .order_done(l_order_done),
        .feature_commit(l_commit),
        .feature_commit_ready(aux_feature_cfg_commit_ready),
        .reader_command(l_reader_command),
        .reader_command_ready(r_cmd_ready),
        .reader_address(l_address),
        .reader_done(r_done),
        .reader_busy(r_busy),
        .reader_fault(r_fault),
        .pipeline_error(load_order_error || aux_feature_error_valid),
        .semantic_cancel(l_semantic_cancel),
        .reader_cancel(l_reader_cancel),
        .reader_clear_fault(l_reader_clear)
    );

    z100_native_stream_order load_order (
        .clk(clk),
        .rst_n(rst_n),
        .cancel(l_semantic_cancel),
        .cfg_valid(l_order),
        .cfg_ready(l_order_ready),
        .cfg_epoch(l_epoch),
        .cfg_write_order(1'b0),
        .cfg_channels(l_channels),
        .cfg_height(l_height),
        .cfg_width(l_width),
        .in_valid(r_valid),
        .in_ready(r_ready),
        .in_epoch(r_epoch),
        .in_index(l_word_base[12:0]+r_index),
        .in_address(13'd0),
        .in_last(l_word_base+{1'b0,r_index}+14'd1==l_words),
        .in_data(r_data),
        .out_valid(aux_feature_cfg_word_valid),
        .out_ready(aux_feature_cfg_word_ready),
        .out_epoch(aux_feature_cfg_word_epoch),
        .out_index(),
        .out_address(aux_feature_cfg_word_address),
        .out_last(aux_feature_cfg_word_last),
        .out_data(aux_feature_cfg_data),
        .active(),
        .done(l_order_done),
        .error_valid(load_order_error),
        .error_code(load_order_code)
    );

    z100_native_axi64_reader source_reader (
        .clk(clk),
        .rst_n(rst_n),
        .cmd_valid(l_reader_command),
        .cmd_ready(r_cmd_ready),
        .cmd_epoch(l_epoch),
        .cmd_address(l_address),
        .cmd_word_count(l_block_words),
        .cancel(l_reader_cancel),
        .timeout(1'b0),
        .clear_fault(l_reader_clear),
        .busy(r_busy),
        .done(r_done),
        .fault(r_fault),
        .fault_code(r_code),
        .out_valid(r_valid),
        .out_ready(r_ready),
        .out_epoch(r_epoch),
        .out_index(r_index),
        .out_data(r_data),
        .out_last(r_last),
        .m_axi_arid(m_axi_arid),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready)
    );

    z100_native_materialized_write_control write_control (
        .clk(clk),
        .rst_n(rst_n),
        .cmd_valid(state==WRITE_CMD && !abort_work),
        .cmd_ready(w_ready),
        .cmd_epoch(epoch_q),
        .cmd_destination_generation(dest_gen_q),
        .cmd_destination_address(dest_q),
        .cmd_region_begin(dest_begin_q),
        .cmd_region_end(dest_end_q),
        .cmd_timeout_cycles(write_timeout_q),
        .cmd_channels(11'd128),
        .cmd_full_height(10'd20),
        .cmd_width(10'd20),
        .cmd_first_row(10'd0),
        .cmd_height(10'd20),
        .cmd_destination_reserved(1'b1),
        .abort(abort_work),
        .recover(1'b0),
        .active(w_active),
        .fault(w_fault),
        .fault_code(w_code),
        .done(w_done),
        .tile_committed(w_committed),
        .epoch(w_epoch),
        .destination_generation(w_generation),
        .channels(w_channels),
        .height(w_height),
        .width(w_width),
        .order_config(w_order),
        .order_config_ready(w_order_ready),
        .order_done(w_order_done),
        .packed_valid(w_packed_valid),
        .packed_ready(w_packed_ready),
        .packed_epoch(w_packed_epoch),
        .packed_index(w_packed_index),
        .packed_last(w_packed_last),
        .packed_data(w_packed_data),
        .writer_command(w_command),
        .writer_command_ready(w_command_ready),
        .writer_address(w_address),
        .writer_words(w_words),
        .writer_valid(w_valid),
        .writer_ready(w_stream_ready),
        .writer_epoch(w_stream_epoch),
        .writer_index(w_index),
        .writer_last(w_stream_last),
        .writer_data(w_data),
        .writer_done(writer_done),
        .writer_busy(writer_busy),
        .writer_fault(writer_fault),
        .pipeline_error(write_order_error),
        .semantic_cancel(w_semantic_cancel),
        .writer_cancel(w_writer_cancel),
        .writer_clear_fault(w_writer_clear)
    );

    z100_native_stream_order write_order (
        .clk(clk),
        .rst_n(rst_n),
        .cancel(w_semantic_cancel),
        .cfg_valid(w_order),
        .cfg_ready(w_order_ready),
        .cfg_epoch(w_epoch),
        .cfg_write_order(1'b1),
        .cfg_channels(w_channels),
        .cfg_height(w_height),
        .cfg_width(w_width),
        .in_valid(aux_pool_packed_valid),
        .in_ready(aux_pool_packed_ready),
        .in_epoch(aux_pool_packed_epoch),
        .in_index(13'd0),
        .in_address(aux_pool_packed_address),
        .in_last(aux_pool_packed_last),
        .in_data(aux_pool_packed_data),
        .out_valid(w_packed_valid),
        .out_ready(w_packed_ready),
        .out_epoch(w_packed_epoch),
        .out_index(w_packed_index),
        .out_address(),
        .out_last(w_packed_last),
        .out_data(w_packed_data),
        .active(),
        .done(w_order_done),
        .error_valid(write_order_error),
        .error_code(write_order_code)
    );

    z100_native_axi64_writer destination_writer (
        .clk(clk),
        .rst_n(rst_n),
        .cmd_valid(w_command),
        .cmd_ready(w_command_ready),
        .cmd_epoch(w_epoch),
        .cmd_address(w_address),
        .cmd_word_count(w_words),
        .in_valid(w_valid),
        .in_ready(w_stream_ready),
        .in_epoch(w_stream_epoch),
        .in_index(w_index),
        .in_data(w_data),
        .in_last(w_stream_last),
        .cancel(w_writer_cancel),
        .timeout(1'b0),
        .clear_fault(w_writer_clear),
        .busy(writer_busy),
        .done(writer_done),
        .fault(writer_fault),
        .fault_code(writer_code),
        .m_axi_awid(m_axi_awid),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_wid(m_axi_wid),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready)
    );

endmodule
`default_nettype wire
