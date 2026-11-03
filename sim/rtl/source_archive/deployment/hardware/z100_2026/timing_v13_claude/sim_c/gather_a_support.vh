// Source-bound identity virtual gather into bankA through the same leased
// reader later used for materialized burst prefetch into bankB.
localparam [31:0] GA_BASE=32'h11000000;
reg ga_input=0,ga_begin=0,ga_commit=0,ga_cb=0,ga_wv=0,ga_cc=0,ga_cv=0;
reg [7:0] ga_cfg_data=0;
wire ga_cbr,ga_cwr,ga_ccr,ga_store_valid,ga_loading,ga_cfg_error,ga_cmd_ready,ga_active,ga_fault,ga_done;
wire [2:0] ga_cfg_code;wire [3:0] ga_code;
wire ga_rc,ga_rcr,ga_busy,ga_rfault,ga_cancel,ga_clear,ga_rv,ga_rr,ga_rlast;
wire [31:0] ga_rep,ga_addr,ga_result_epoch;wire [12:0] ga_ri;wire [511:0] ga_rd;
wire ga_v,ga_last;wire [31:0] ga_oe,ga_oa;wire [511:0] ga_od;
wire ga_ready=ga_input&&feature_cfg_word_ready&&pf_sink_allow;
z100_native_view_gather gather_A(.clk(clk),.rst_n(rst_n),.cfg_begin(ga_cb),.cfg_begin_ready(ga_cbr),.cfg_epoch(EPOCH),.cfg_contexts(3'd4),
    .cfg_word_valid(ga_wv),.cfg_word_ready(ga_cwr),.cfg_data(ga_cfg_data),.cfg_commit(ga_cc),.cfg_commit_ready(ga_ccr),
    .store_valid(ga_store_valid),.loading(ga_loading),.cfg_error(ga_cfg_error),.cfg_error_code(ga_cfg_code),
    .cmd_valid(ga_cv),.cmd_ready(ga_cmd_ready),.cmd_epoch(EPOCH),.cmd_table_epoch(EPOCH),.cmd_source_address(GA_BASE),
    .cmd_region_begin(GA_BASE),.cmd_region_end({1'b0,GA_BASE}+33'd5120),.cmd_source_row_stride(32'd2560),.cmd_source_x_stride(32'd64),
    .cmd_output_word_base(32'd0),.cmd_timeout_cycles(32'd100000),.cmd_height(10'd2),.cmd_width(10'd640),.cmd_channels(3'd3),
    .cmd_nearest_shift(2'd0),.cmd_context(2'd0),.cmd_source_committed(1'b1),.abort(cancel),.recover(1'b0),
    .active(ga_active),.fault(ga_fault),.fault_code(ga_code),.done(ga_done),
    .read_command(ga_rc),.read_command_ready(ga_rcr),.read_epoch(ga_rep),.read_address(ga_addr),.reader_busy(ga_busy),.reader_fault(ga_rfault),.read_cancel(ga_cancel),.read_clear_fault(ga_clear),
    .read_valid(ga_rv),.read_ready(ga_rr),.read_result_epoch(ga_result_epoch),.read_result_index(ga_ri),.read_last(ga_rlast),.read_data(ga_rd),
    .out_valid(ga_v),.out_ready(ga_ready),.out_epoch(ga_oe),.out_word_address(ga_oa),.out_data(ga_od),.out_last(ga_last));
wire gm_command,gm_command_ready,gm_busy,gm_fault,gm_cancel,gm_clear,gm_valid,gm_ready,gm_last,gm_done;
wire [31:0] gm_epoch,gm_address,gm_result_epoch,ga_hits,ga_misses;
wire [12:0] gm_index;wire [511:0] gm_data;wire [3:0] gm_code;
z100_native_word_cache gather_A_cache(.clk(clk),.rst_n(rst_n),.cmd_valid(ga_rc),.cmd_ready(ga_rcr),.cmd_epoch(ga_rep),.cmd_address(ga_addr),.cmd_source_generation(32'd6101),
    .cancel(ga_cancel),.clear_fault(ga_clear),.busy(ga_busy),.fault(ga_rfault),.fault_code(),.done(),
    .out_valid(ga_rv),.out_ready(ga_rr),.out_epoch(ga_result_epoch),.out_index(ga_ri),.out_last(ga_rlast),.out_data(ga_rd),
    .memory_command(gm_command),.memory_command_ready(gm_command_ready),.memory_epoch(gm_epoch),.memory_address(gm_address),
    .memory_busy(gm_busy),.memory_fault(gm_fault),.memory_cancel(gm_cancel),.memory_clear_fault(gm_clear),
    .memory_valid(gm_valid),.memory_ready(gm_ready),.memory_result_epoch(gm_result_epoch),.memory_result_index(gm_index),.memory_last(gm_last),.memory_data(gm_data),
    .hit_count(ga_hits),.miss_count(ga_misses));
reg lease_acquire=0,lease_acquire_mode=1,lease_release=0,lease_release_mode=1;
wire lease_acquire_ready,lease_release_ready,lease_valid,lease_mode;
integer lease_acquires=0,lease_releases=0,ga_loaded=0,ga_ars=0,ga_rbeats=0;
reg [511:0] ga_memory[0:79];
always @(posedge clk)if(rst_n)begin
    if(ga_fault||ga_cfg_error)$fatal(1,"coupled gatherA fault=%0d/%0d cfg=%0d",ga_fault,ga_code,ga_cfg_code);
    if(lease_acquire&&lease_acquire_ready)lease_acquires=lease_acquires+1;
    if(lease_release&&lease_release_ready)lease_releases=lease_releases+1;
    if(ga_input&&ga_v&&ga_ready)begin
        if(ga_loaded>=80||ga_oa!=ga_loaded||ga_oe!=EPOCH||ga_od!==feature_words[ga_loaded]||ga_last!=(ga_loaded==79))$fatal(1,"actual gatherA source-to-bank data mismatch address=%0d",ga_oa);
        ga_loaded=ga_loaded+1;
    end
    if(pf_arvalid&&pf_arready&&lease_mode)begin
        if(pf_arid!=0||pf_arsize!=3||pf_arburst!=1||pf_arlen!=7||pf_araddr!==GA_BASE+ga_ars*64)$fatal(1,"coupled gatherA AXI identity/order");
        ga_ars=ga_ars+1;
    end
    if(pf_pop&&lease_mode)ga_rbeats=ga_rbeats+1;
end
task acquire_load_lease(input integer selected);begin
    while(!lease_acquire_ready)@(negedge clk);
    lease_acquire=1;lease_acquire_mode=selected;@(posedge clk);#1;@(negedge clk);lease_acquire=0;lease_acquire_mode=!selected;
    if(!lease_valid||lease_mode!=selected)$fatal(1,"coupled reader did not latch lease mode");
end endtask
task release_load_lease;begin
    @(negedge clk);lease_release=1;lease_release_mode=lease_mode;
    #1;while(!lease_release_ready)begin @(negedge clk);#1;end
    @(posedge clk);#1;@(negedge clk);lease_release=0;
    if(lease_valid)$fatal(1,"coupled reader lease did not release");
end endtask
task load_gather_A;integer k;begin
    $readmemh("feature_words.hex",ga_memory);
    ga_input=1;acquire_load_lease(1);
    while(!ga_cbr)@(negedge clk);ga_cb=1;@(posedge clk);#1;@(negedge clk);ga_cb=0;
    for(k=0;k<1024;k=k+1)begin
        ga_wv=1;ga_cfg_data=(k%256)^8'h80;
        #1;if(!ga_cwr)$fatal(1,"gatherA identity palette readiness");@(posedge clk);#1;@(negedge clk);
    end
    ga_wv=0;ga_cc=1;#1;if(!ga_ccr)$fatal(1,"gatherA palette commit");@(posedge clk);#1;@(negedge clk);ga_cc=0;
    while(!feature_cfg_begin_ready)@(negedge clk);ga_begin=1;@(posedge clk);#1;@(negedge clk);ga_begin=0;
    while(!ga_cmd_ready)@(negedge clk);ga_cv=1;@(posedge clk);#1;@(negedge clk);ga_cv=0;
    wait(ga_done);@(posedge clk);#1;@(negedge clk);
    while(!feature_cfg_commit_ready)@(negedge clk);ga_commit=1;@(posedge clk);#1;@(negedge clk);ga_commit=0;
    if(ga_loaded!=80||ga_ars!=80||ga_rbeats!=640||ga_misses!=80||ga_hits!=0||!feature_load_store_valid||feature_load_active_epoch!=EPOCH)$fatal(1,"gatherA bank published before input/reader/commit retirement");
    release_load_lease();ga_input=0;
end endtask
