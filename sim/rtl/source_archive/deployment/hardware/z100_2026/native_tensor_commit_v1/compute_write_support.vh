// Source-bound testbench seam: actual Conv/Pool packer -> codec -> reserved
// write control -> frozen AXI writer -> independently checked DDR model.
localparam [31:0] WB_BASE=32'h20000000;
reg wb_pending=0,wb_mode=0;
wire wb_tile_ready_selected;
wire [2:0] wb_tensor_committed,wb_tensor_fault;
reg [2:0] wb_allocated=0;
reg [31:0] wb_epoch_q=0,wb_address_q=0;
reg [10:0] wb_channels_q=0;reg [9:0] wb_height_q=0,wb_width_q=0;
integer wb_scheduled=0,wb_completed=0,wb_cycle=0,wb_aws=0,wb_ws=0,wb_bs=0,wb_packed=0;
wire wb_command_ready,wb_active,wb_fault,wb_done,wb_committed,wb_oc,wb_ocr,wb_order_done;
wire [3:0] wb_code;
wire [31:0] wb_epoch,wb_generation;
wire [10:0] wb_channels;wire [9:0] wb_height,wb_width;
wire wb_pv,wb_pr,wb_pl;wire [31:0] wb_pe;wire [12:0] wb_pi;wire [511:0] wb_pd;
wire wb_wc,wb_wcr,wb_wv,wb_wr,wb_wl,wb_wdone,wb_wbusy,wb_wfault,wb_codec_error,wb_cancel,wb_clear,wb_semantic;
wire [31:0] wb_wa,wb_we;wire[13:0] wb_ww;wire[12:0] wb_wi;wire[511:0] wb_wd;
wire wb_source_ready;
assign packed_ready=conv_allow&&!wb_mode&&wb_source_ready;
assign pool_packed_ready=pool_allow&&wb_mode&&wb_source_ready;
wire wb_source_valid=wb_mode ? pool_packed_valid&&pool_allow : packed_valid&&conv_allow;
z100_native_materialized_write_control write_control(.clk(clk),.rst_n(rst_n),
    .cmd_valid(wb_pending&&wb_tile_ready_selected),.cmd_ready(wb_command_ready),.cmd_epoch(wb_epoch_q),.cmd_destination_generation(32'd801+wb_scheduled),
    .cmd_destination_address(wb_address_q),.cmd_region_begin(WB_BASE),.cmd_region_end({1'b0,WB_BASE}+33'h80000),.cmd_timeout_cycles(32'd1000000),
    .cmd_channels(wb_channels_q),.cmd_full_height(wb_height_q),.cmd_width(wb_width_q),.cmd_first_row(10'd0),.cmd_height(wb_height_q),.cmd_destination_reserved(1'b1),
    .abort(cancel),.recover(1'b0),.active(wb_active),.fault(wb_fault),.fault_code(wb_code),.done(wb_done),.tile_committed(wb_committed),
    .epoch(wb_epoch),.destination_generation(wb_generation),.channels(wb_channels),.height(wb_height),.width(wb_width),
    .order_config(wb_oc),.order_config_ready(wb_ocr),.order_done(wb_order_done),
    .packed_valid(wb_pv),.packed_ready(wb_pr),.packed_epoch(wb_pe),.packed_index(wb_pi),.packed_last(wb_pl),.packed_data(wb_pd),
    .writer_command(wb_wc),.writer_command_ready(wb_wcr),.writer_address(wb_wa),.writer_words(wb_ww),
    .writer_valid(wb_wv),.writer_ready(wb_wr),.writer_epoch(wb_we),.writer_index(wb_wi),.writer_last(wb_wl),.writer_data(wb_wd),
    .writer_done(wb_wdone),.writer_busy(wb_wbusy),.writer_fault(wb_wfault),.pipeline_error(wb_codec_error),
    .semantic_cancel(wb_semantic),.writer_cancel(wb_cancel),.writer_clear_fault(wb_clear));
z100_native_stream_order write_order(.clk(clk),.rst_n(rst_n),.cancel(wb_semantic),
    .cfg_valid(wb_oc),.cfg_ready(wb_ocr),.cfg_epoch(wb_epoch),.cfg_write_order(1'b1),
    .cfg_channels(wb_channels),.cfg_height(wb_height),.cfg_width(wb_width),
    .in_valid(wb_source_valid),.in_ready(wb_source_ready),.in_epoch(wb_mode ? pool_packed_epoch : packed_epoch),.in_index(13'd0),
    .in_address(wb_mode ? pool_packed_address : packed_address),.in_last(wb_mode ? pool_packed_last : packed_last),.in_data(wb_mode ? pool_packed_data : packed_data),
    .out_valid(wb_pv),.out_ready(wb_pr),.out_epoch(wb_pe),.out_index(wb_pi),.out_address(),.out_last(wb_pl),.out_data(wb_pd),
    .active(),.done(wb_order_done),.error_valid(wb_codec_error),.error_code());
wire [5:0] wb_awid,wb_wid;wire[31:0] wb_awaddr;wire[3:0] wb_awlen;wire[2:0] wb_awsize;wire[1:0] wb_awburst;
wire wb_awvalid,wb_wvalid,wb_wlast,wb_bready;wire[63:0] wb_wdata;wire[7:0] wb_wstrb;
reg wb_bvalid=0;
wire wb_awready=wb_cycle%7!=0,wb_wready=wb_cycle%5!=0;
z100_native_axi64_writer output_writer(.clk(clk),.rst_n(rst_n),.cmd_valid(wb_wc),.cmd_ready(wb_wcr),
    .cmd_epoch(wb_epoch),.cmd_address(wb_wa),.cmd_word_count(wb_ww),
    .in_valid(wb_wv),.in_ready(wb_wr),.in_epoch(wb_we),.in_index(wb_wi),.in_data(wb_wd),.in_last(wb_wl),
    .cancel(wb_cancel),.timeout(1'b0),.clear_fault(wb_clear),.busy(wb_wbusy),.done(wb_wdone),.fault(wb_wfault),.fault_code(),
    .m_axi_awid(wb_awid),.m_axi_awaddr(wb_awaddr),.m_axi_awlen(wb_awlen),.m_axi_awsize(wb_awsize),.m_axi_awburst(wb_awburst),.m_axi_awvalid(wb_awvalid),.m_axi_awready(wb_awready),
    .m_axi_wid(wb_wid),.m_axi_wdata(wb_wdata),.m_axi_wstrb(wb_wstrb),.m_axi_wlast(wb_wlast),.m_axi_wvalid(wb_wvalid),.m_axi_wready(wb_wready),
    .m_axi_bid(6'd0),.m_axi_bresp(2'd0),.m_axi_bvalid(wb_bvalid),.m_axi_bready(wb_bready));
reg[63:0] wb_memory[0:65535];reg wb_awowned=0;reg[31:0] wb_address=0;
integer wb_beat=0,wb_beats=0,wb_bdelay=0;
reg wb_awheld=0,wb_wheld=0;reg[35:0] wb_aw_saved;reg[78:0] wb_w_saved;
always @(posedge clk)begin
    wb_cycle=wb_cycle+1;
    if(rst_n)begin
        if(wb_fault||wb_codec_error||wb_wfault)$fatal(1,"Actual compute writeback fault %d",wb_code);
        if(wb_pending&&wb_command_ready&&wb_tile_ready_selected)wb_pending<=0;
        if(pack_cfg_valid&&pack_cfg_ready||pool_job_valid&&pool_job_ready)begin
            if(wb_pending||wb_active||wb_wbusy)$fatal(1,"New output job before old destination commit");
            wb_pending<=1;wb_mode<=pool_job_valid&&pool_job_ready;
            wb_epoch_q<=pool_job_valid&&pool_job_ready ? pool_job_epoch : pack_cfg_epoch;
            wb_channels_q<=pool_job_valid&&pool_job_ready ? pool_job_channels : pack_cfg_channels;
            wb_height_q<=pool_job_valid&&pool_job_ready ? pool_job_height : pack_cfg_height;
            wb_width_q<=pool_job_valid&&pool_job_ready ? pool_job_width : pack_cfg_width;
            wb_address_q<=WB_BASE+wb_scheduled*131072;wb_scheduled=wb_scheduled+1;
        end
        if(wb_done)begin
            if(!wb_committed||wb_wbusy||wb_awowned||wb_bvalid||wb_bdelay!=0)$fatal(1,"Output published before B response");
            wb_completed=wb_completed+1;
        end
        if(wb_source_valid&&wb_source_ready)wb_packed=wb_packed+1;
        if(wb_awheld&&(!wb_awvalid||{wb_awlen,wb_awaddr}!==wb_aw_saved))$fatal(1,"Actual output AW hold");
        wb_awheld=wb_awvalid&&!wb_awready;wb_aw_saved={wb_awlen,wb_awaddr};
        if(wb_wheld&&(!wb_wvalid||{wb_wid,wb_wdata,wb_wstrb,wb_wlast}!==wb_w_saved))$fatal(1,"Actual output W hold");
        wb_wheld=wb_wvalid&&!wb_wready;wb_w_saved={wb_wid,wb_wdata,wb_wstrb,wb_wlast};
        if(wb_awvalid&&wb_awready)begin
            if(wb_awowned||wb_bvalid||wb_bdelay!=0||wb_awid!=0||wb_awsize!=3||wb_awburst!=1||wb_awlen!=15||
                wb_awaddr<WB_BASE||wb_awaddr>=WB_BASE+524288||wb_awaddr[6:0]!=0)$fatal(1,"Actual output burst geometry");
            wb_awowned<=1;wb_address<=wb_awaddr;wb_beat<=0;wb_beats<=wb_awlen+1;wb_aws=wb_aws+1;
        end
        if(wb_wvalid&&wb_wready)begin
            if(!wb_awowned||wb_wid!=0||wb_wstrb!=255||wb_wlast!=(wb_beat+1==wb_beats))$fatal(1,"Actual output W ownership");
            wb_memory[((wb_address-WB_BASE)>>3)+wb_beat]<=wb_wdata;wb_beat<=wb_beat+1;wb_ws=wb_ws+1;
            if(wb_wlast)begin wb_awowned<=0;wb_bdelay<=9;end
        end
        if(wb_bdelay>0)begin wb_bdelay<=wb_bdelay-1;if(wb_bdelay==1)wb_bvalid<=1;end
        if(wb_bvalid&&wb_bready)begin wb_bvalid<=0;wb_bs=wb_bs+1;end
        if((wb_awowned||wb_bvalid||wb_bdelay!=0)&&wb_committed)$fatal(1,"Actual destination committed early");
    end
end

wire [2:0] wb_alloc_ready,wb_tile_ready,wb_complete_ready;
wire wb_io_quiescent=!wb_active&&!wb_wbusy&&!wb_awowned&&!wb_bvalid&&wb_bdelay==0;
assign wb_tile_ready_selected=(wb_scheduled==1&&wb_tile_ready[0]||wb_scheduled==2&&wb_tile_ready[1]||wb_scheduled==3&&wb_tile_ready[2]);
genvar wb_slot;
generate for(wb_slot=0;wb_slot<3;wb_slot=wb_slot+1)begin:gen_tensor_ledger
    wire selected=wb_scheduled==wb_slot+1;
    wire [31:0] tensor_epoch,tensor_generation,tensor_address,tensor_bytes;
    wire [15:0] tensor_id;
    wire [10:0] covered,tensor_channels;
    wire [9:0] tensor_height,tensor_width;
    z100_native_tensor_commit ledger(.clk(clk),.rst_n(rst_n),.abort(cancel),.recover(1'b0),
        .io_quiescent(wb_io_quiescent),.source_readers_quiescent(1'b1),
        .allocate_valid(wb_pending&&selected&&!wb_allocated[wb_slot]),.allocate_ready(wb_alloc_ready[wb_slot]),
        .allocate_epoch(wb_epoch_q),.allocate_generation(32'd802+wb_slot),.allocate_address(wb_address_q),.allocate_tensor_id(wb_slot),
        .allocate_channels(wb_channels_q),.allocate_height(wb_height_q),.allocate_width(wb_width_q),
        .tile_valid(wb_pending&&wb_command_ready&&selected&&wb_allocated[wb_slot]),.tile_ready(wb_tile_ready[wb_slot]),
        .tile_epoch(wb_epoch_q),.tile_generation(32'd802+wb_slot),.tile_tensor_id(wb_slot),.tile_first_row(10'd0),.tile_height(wb_height_q),
        .completion_valid(wb_done&&selected),.completion_ready(wb_complete_ready[wb_slot]),
        .completion_epoch(wb_epoch),.completion_generation(wb_generation),.completion_tensor_id(wb_slot),
        .completion_first_row(10'd0),.completion_height(wb_height_q),.completion_success(wb_committed),
        .release_valid(1'b0),.release_ready(),.active(),.fault(wb_tensor_fault[wb_slot]),.fault_code(),
        .source_committed(wb_tensor_committed[wb_slot]),.tile_pending(),.source_epoch(tensor_epoch),.source_generation(tensor_generation),
        .source_address(tensor_address),.source_bytes(tensor_bytes),.source_tensor_id(tensor_id),
        .source_channels(tensor_channels),.covered_rows(covered),.source_height(tensor_height),.source_width(tensor_width),.publication_pulse());
    always @(posedge clk)if(rst_n)begin
        if(wb_pending&&selected&&!wb_allocated[wb_slot]&&wb_alloc_ready[wb_slot])wb_allocated[wb_slot]<=1;
        if(wb_tensor_fault[wb_slot])$fatal(1,"Actual destination ledger fault");
        if(wb_done&&selected&&!wb_complete_ready[wb_slot])$fatal(1,"Actual B-complete tile lost publication event");
        if(wb_tensor_committed[wb_slot])begin
            if(covered!=tensor_height||tensor_generation!=802+wb_slot||tensor_address!=WB_BASE+wb_slot*131072||
                tensor_bytes!=(wb_slot==1 ? 81920 : 5120)||tensor_id!=wb_slot)
                $fatal(1,"Published compute tensor identity/shape mismatch");
            if(selected&&(wb_awowned||wb_bvalid||wb_bdelay!=0||wb_active||wb_wbusy))$fatal(1,"Full tensor published before final B");
        end
    end
end endgenerate
