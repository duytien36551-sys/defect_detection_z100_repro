`include "gather_A_support.vh"
// Included inside the source-bound Conv/Pool/Conv testbench only.
localparam [31:0] PF_BASE=32'h10000000;
reg pf_active=0,pf_command_valid=0,pf_bank_pin=1,old_load_bank=0,compute_source_bank=0,pf_completed=0;
wire feature_load_store_valid,feature_load_loading;wire [31:0] feature_load_active_epoch;
wire pf_command_ready,pf_fault,pf_done,pf_result,pf_active_control;wire [3:0] pf_fault_code;
wire [31:0] pf_epoch,pf_generation,pf_address;wire [10:0] pf_channels;wire [9:0] pf_height,pf_width;
wire [13:0] pf_words,pf_block_words,pf_word_base;
wire pf_cb,pf_oc,pf_oc_ready,pf_order_done,pf_commit,pf_read_command,pf_read_command_ready;
wire pf_reader_done,pf_reader_busy,pf_reader_fault,pf_semantic_cancel,pf_reader_cancel,pf_reader_clear;
wire pf_rv,pf_rr,pf_rlast_word;wire [31:0] pf_rep;wire [12:0] pf_ri;wire [511:0] pf_rd;wire [3:0] pf_reader_code;
wire pf_v,pf_ready,pf_last,pf_codec_error,pf_codec_active;wire [1:0] pf_codec_code;wire [31:0] pf_ep;wire [12:0] pf_index,pf_word_address;wire [511:0] pf_data;
integer pf_cycles=0;wire pf_sink_allow=(pf_cycles%31)>7;
wire pf_pipeline_error=feature_error_valid||pf_codec_error;
z100_native_materialized_load_control prefetch_control(.clk(clk),.rst_n(rst_n),.cmd_valid(pf_command_valid),.cmd_ready(pf_command_ready),
    .cmd_epoch(EPOCH+1),.cmd_source_generation(32'd6901),.cmd_source_address(PF_BASE),.cmd_timeout_cycles(32'd200000),
    .cmd_channels(11'd128),.cmd_full_height(10'd20),.cmd_width(10'd20),.cmd_first_row(10'd0),.cmd_height(10'd20),
    .cmd_source_committed(1'b1),.cmd_source_is_materialized(1'b1),.abort(cancel),.recover(1'b0),.active(pf_active_control),.fault(pf_fault),.fault_code(pf_fault_code),.done(pf_done),.result_committed(pf_result),
    .epoch(pf_epoch),.source_generation(pf_generation),.channels(pf_channels),.height(pf_height),.width(pf_width),.total_words(pf_words),.block_words(pf_block_words),.block_word_base(pf_word_base),
    .feature_begin(pf_cb),.feature_begin_ready(feature_cfg_begin_ready&&pf_active),.order_config(pf_oc),.order_config_ready(pf_oc_ready),.order_done(pf_order_done),
    .feature_commit(pf_commit),.feature_commit_ready(feature_cfg_commit_ready&&pf_active),.reader_command(pf_read_command),.reader_command_ready(pf_read_command_ready),.reader_address(pf_address),
    .reader_done(pf_reader_done),.reader_busy(pf_reader_busy),.reader_fault(pf_reader_fault),.pipeline_error(pf_pipeline_error),
    .semantic_cancel(pf_semantic_cancel),.reader_cancel(pf_reader_cancel),.reader_clear_fault(pf_reader_clear));
wire [5:0] pf_arid;wire [31:0] pf_araddr;wire [3:0] pf_arlen;wire [2:0] pf_arsize;wire [1:0] pf_arburst;
wire pf_arvalid,pf_arready,pf_rready;wire pf_rvalid,pf_axi_rlast;wire [63:0] pf_axi_rdata;wire[5:0] pf_axi_rid;wire[1:0] pf_axi_rresp;
z100_native_ingress_reader_v2 shared_reader(.clk(clk),.rst_n(rst_n),
    .acquire_valid(lease_acquire),.acquire_mode(lease_acquire_mode),.acquire_ready(lease_acquire_ready),
    .release_valid(lease_release),.release_mode(lease_release_mode),.release_ready(lease_release_ready),
    .b_quiet(!pf_active_control&&!pf_codec_active),.v_quiet(!ga_active&&!ga_loading),.owner_valid(lease_valid),.owner_mode(lease_mode),
    .b_command(pf_read_command),.b_command_ready(pf_read_command_ready),.b_epoch(pf_epoch),.b_address(pf_address),.b_words(pf_block_words),
    .b_cancel(pf_reader_cancel),.b_clear_fault(pf_reader_clear),.b_busy(pf_reader_busy),.b_done(pf_reader_done),.b_fault(pf_reader_fault),.b_fault_code(pf_reader_code),
    .b_valid(pf_rv),.b_ready(pf_rr),.b_result_epoch(pf_rep),.b_index(pf_ri),.b_data(pf_rd),.b_last(pf_rlast_word),
    .v_command(gm_command),.v_command_ready(gm_command_ready),.v_epoch(gm_epoch),.v_address(gm_address),
    .v_cancel(gm_cancel),.v_clear_fault(gm_clear),.v_busy(gm_busy),.v_done(gm_done),.v_fault(gm_fault),.v_fault_code(gm_code),
    .v_valid(gm_valid),.v_ready(gm_ready),.v_result_epoch(gm_result_epoch),.v_index(gm_index),.v_data(gm_data),.v_last(gm_last),
    .m_axi_arid(pf_arid),.m_axi_araddr(pf_araddr),.m_axi_arlen(pf_arlen),.m_axi_arsize(pf_arsize),.m_axi_arburst(pf_arburst),.m_axi_arvalid(pf_arvalid),.m_axi_arready(pf_arready),
    .m_axi_rid(pf_axi_rid),.m_axi_rdata(pf_axi_rdata),.m_axi_rresp(pf_axi_rresp),.m_axi_rlast(pf_axi_rlast),.m_axi_rvalid(pf_rvalid),.m_axi_rready(pf_rready));
wire [13:0] pf_global_index=pf_word_base+pf_ri;
z100_native_stream_order prefetch_order(.clk(clk),.rst_n(rst_n),.cancel(pf_semantic_cancel),.cfg_valid(pf_oc),.cfg_ready(pf_oc_ready),.cfg_epoch(pf_epoch),.cfg_write_order(1'b0),.cfg_channels(pf_channels),.cfg_height(pf_height),.cfg_width(pf_width),
    .in_valid(pf_rv),.in_ready(pf_rr),.in_epoch(pf_rep),.in_index(pf_global_index[12:0]),.in_address(13'd0),.in_last(pf_global_index+1==pf_words),.in_data(pf_rd),
    .out_valid(pf_v),.out_ready(pf_ready),.out_epoch(pf_ep),.out_index(pf_index),.out_address(pf_word_address),.out_last(pf_last),.out_data(pf_data),.active(pf_codec_active),.done(pf_order_done),.error_valid(pf_codec_error),.error_code(pf_codec_code));
assign pf_ready=pf_active&&pf_sink_allow&&feature_cfg_word_ready;
reg [511:0] pf_memory[0:1279];wire pf_pop=pf_rvalid&&pf_rready;
integer pf_ars=0,pf_rbeats=0,pf_loaded=0,pf_commands=0,pf_overlap_cycles=0,pf_overlap_loads=0,pf_simultaneous=0,pf_bank_latch_probes=0,pf_active_bank_probes=0;
reg pf_ar_held=0,pf_r_held=0;reg [35:0] pf_held_ar;reg [64:0] pf_held_r;
always @(posedge clk)begin
    pf_cycles=pf_cycles+1;
    if(rst_n)begin
        if(pf_fault||pf_codec_error)$fatal(1,"prefetch controller/codec fault=%0d/%0d code=%0d",pf_fault,pf_codec_error,pf_fault_code);
        if(pf_ar_held&&(!pf_arvalid||{pf_arlen,pf_araddr}!==pf_held_ar))$fatal(1,"prefetch AR changed while held");
        pf_ar_held=pf_arvalid&&!pf_arready;if(pf_ar_held)pf_held_ar={pf_arlen,pf_araddr};
        if(pf_r_held&&(!pf_rvalid||{pf_axi_rlast,pf_axi_rdata}!==pf_held_r))$fatal(1,"prefetch memory R changed while held");
        pf_r_held=pf_rvalid&&!pf_rready;if(pf_r_held)pf_held_r={pf_axi_rlast,pf_axi_rdata};
        if(pf_read_command&&pf_read_command_ready)pf_commands=pf_commands+1;
        if(pf_arvalid&&pf_arready&&!lease_mode)begin
            if(pf_arid!=0||pf_arsize!=3||pf_arburst!=1||pf_arlen!=15||pf_araddr!==PF_BASE+pf_ars*128)$fatal(1,"prefetch source burst identity/order");
            pf_ars=pf_ars+1;
        end
        if(pf_pop&&!lease_mode)pf_rbeats=pf_rbeats+1;
        if(pf_active&&lease_valid&&!lease_mode&&dut.conv_owned&&pf_reader_busy)begin
            pf_overlap_cycles=pf_overlap_cycles+1;
            if(dut.source_bank_q!==0||feature_active_epoch!=EPOCH)$fatal(1,"prefetch changed live Conv source bank/epoch");
        end
        if(pf_active&&pf_v&&pf_ready)begin
            pf_loaded=pf_loaded+1;
            if(dut.feature_window.load_owner_bank!==1)$fatal(1,"prefetch overwrote computation bank");
            if(pf_bank_pin==0)pf_bank_latch_probes=pf_bank_latch_probes+1;
            if(dut.conv_owned)begin
                pf_overlap_loads=pf_overlap_loads+1;
                if(stream_valid&&stream_ready)pf_simultaneous=pf_simultaneous+1;
            end
        end
    end
end
integer pf_i;
initial begin
    $readmemh("pool_input.hex",pf_memory);
    wait(run_count>0);
    @(negedge clk);old_load_bank=0;feature_cfg_begin=1;
    for(pf_i=0;pf_i<4;pf_i=pf_i+1)begin
        #1;if(feature_cfg_begin_ready)$fatal(1,"active computation bank accepted overwrite");
        pf_active_bank_probes=pf_active_bank_probes+1;@(negedge clk);
    end
    feature_cfg_begin=0;pf_active=1;pf_bank_pin=1;
    acquire_load_lease(0);
    while(!pf_command_ready)@(negedge clk);
    pf_command_valid=1;@(posedge clk);#1;@(negedge clk);pf_command_valid=0;
    wait(pf_cb&&feature_cfg_begin_ready);@(posedge clk);#1;
    if(!dut.feature_window.load_owner_valid||!dut.feature_window.load_owner_bank)$fatal(1,"prefetch bank ownership not latched");
    @(negedge clk);pf_bank_pin=0;compute_source_bank=1;
    wait(pf_done);@(posedge clk);#1;
    if(!pf_result||!feature_load_store_valid||feature_load_active_epoch!=EPOCH+1||pf_reader_busy||pf_codec_active)$fatal(1,"prefetch source published before complete commit");
    if(pf_loaded!=1280||pf_commands!=4||pf_ars!=640||pf_rbeats!=10240||pf_overlap_cycles==0||pf_overlap_loads==0||pf_simultaneous==0||pf_bank_latch_probes==0||pf_active_bank_probes!=4)$fatal(1,"prefetch overlap/ownership coverage missing");
    release_load_lease();
    @(negedge clk);pf_active=0;pf_completed=1;
end
