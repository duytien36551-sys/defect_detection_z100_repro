// Directory selects the real parameter-loader fields. A nested arbiter shares
// its reader and the parameter reader before the existing feature/parameter bus.
wire pd_request,pd_ready;wire[15:0] pd_job;
wire[10:0] pd_groups;wire[5:0] pd_lanes;wire[31:0] pd_weights,pd_bias,pd_factors,pd_unary;
wire pd_active,pd_fault,pd_done;wire[3:0] pd_code;
wire pd_cmd,pd_cmdready,pd_busy,pd_rfault,pd_cancel,pd_clear,pd_valid,pd_dataready,pd_last;
wire[31:0] pd_epoch,pd_address,pd_result_epoch;wire[13:0] pd_words;wire[12:0] pd_index;wire[511:0] pd_data;
wire[31:0] pd_descriptor_epoch,pd_descriptor_tag;wire[15:0] pd_descriptor_job;
wire[5:0] pl_arid,pl_rid,pd_arid,pd_rid;wire[31:0] pl_araddr,pd_araddr;
wire[3:0] pl_arlen,pd_arlen;wire[2:0] pl_arsize,pd_arsize;wire[1:0] pl_arburst,pd_arburst,pl_rresp,pd_rresp;
wire pl_arvalid,pl_arready,pl_rvalid,pl_rlast,pl_rready,pd_arvalid,pd_arready,pd_rvalid,pd_rlast,pd_rready;
wire[63:0] pl_rdata,pd_rdata;
wire[1:0] dp_arready,dp_rvalid,dp_rlast;wire[11:0] dp_rid;wire[127:0] dp_rdata;wire[3:0] dp_rresp;
wire dp_active,dp_owner,dp_fault;
assign {pd_arready,pl_arready}=dp_arready;
assign {pd_rid,pl_rid}=dp_rid;assign {pd_rdata,pl_rdata}=dp_rdata;assign {pd_rresp,pl_rresp}=dp_rresp;
assign {pd_rvalid,pl_rvalid}=dp_rvalid;assign {pd_rlast,pl_rlast}=dp_rlast;
z100_native_axi_read_arbiter directory_parameter_bus(.clk(clk),.rst_n(rst_n),
 .s_arid({pd_arid,pl_arid}),.s_araddr({pd_araddr,pl_araddr}),.s_arlen({pd_arlen,pl_arlen}),.s_arsize({pd_arsize,pl_arsize}),.s_arburst({pd_arburst,pl_arburst}),.s_arvalid({pd_arvalid,pl_arvalid}),
 .s_arready(dp_arready),.s_rid(dp_rid),.s_rdata(dp_rdata),.s_rresp(dp_rresp),.s_rlast(dp_rlast),.s_rvalid(dp_rvalid),.s_rready({pd_rready,pl_rready}),
 .m_arid(pp_arid),.m_araddr(pp_araddr),.m_arlen(pp_arlen),.m_arsize(pp_arsize),.m_arburst(pp_arburst),.m_arvalid(pp_arvalid),.m_arready(pp_arready),
 .m_rid(pp_axi_rid),.m_rdata(pp_axi_rdata),.m_rresp(pp_axi_rresp),.m_rlast(pp_axi_rlast),.m_rvalid(pp_axi_rvalid),.m_rready(pp_axi_rready),.active(dp_active),.active_owner(dp_owner),.protocol_fault(dp_fault));
z100_native_parameter_directory_v2 parameter_directory(.clk(clk),.rst_n(rst_n),.abort(cancel),.recover(1'b0),.consumer_idle(!pp_active&&pp_job_ready&&!pp_fault),
 .cmd_valid(pd_request),.cmd_ready(pd_ready),.cmd_epoch(EPOCH),.cmd_tag(32'd1),.cmd_table_base(32'h21000000),.cmd_model_crc(`MODEL_CRC),
 .cmd_payload_begin(32'h20000000),.cmd_payload_end(33'h20000000+`PAYLOAD_BYTES),.cmd_job(pd_job),.cmd_count(16'd173),.cmd_timeout(32'd100000),
 .reader_command(pd_cmd),.reader_command_ready(pd_cmdready),.reader_epoch(pd_epoch),.reader_address(pd_address),.reader_words(pd_words),.reader_busy(pd_busy),.reader_fault(pd_rfault),.reader_cancel(pd_cancel),.reader_clear(pd_clear),
 .reader_valid(pd_valid),.reader_ready(pd_dataready),.reader_result_epoch(pd_result_epoch),.reader_index(pd_index),.reader_last(pd_last),.reader_data(pd_data),
 .descriptor_valid(pp_job_valid),.descriptor_ready(pp_job_ready),.descriptor_epoch(pd_descriptor_epoch),.descriptor_tag(pd_descriptor_tag),.descriptor_job(pd_descriptor_job),
 .descriptor_groups(pd_groups),.descriptor_lanes(pd_lanes),.descriptor_weights(pd_weights),.descriptor_bias(pd_bias),.descriptor_factors(pd_factors),.descriptor_unary(pd_unary),
 .active(pd_active),.needs_drain(),.done(pd_done),.fault(pd_fault),.fault_code(pd_code));
z100_native_axi64_reader directory_reader(.clk(clk),.rst_n(rst_n),.cmd_valid(pd_cmd),.cmd_ready(pd_cmdready),.cmd_epoch(pd_epoch),.cmd_address(pd_address),.cmd_word_count(pd_words),.cancel(pd_cancel),.timeout(1'b0),.clear_fault(pd_clear),
 .busy(pd_busy),.done(),.fault(pd_rfault),.fault_code(),.out_valid(pd_valid),.out_ready(pd_dataready),.out_epoch(pd_result_epoch),.out_index(pd_index),.out_last(pd_last),.out_data(pd_data),
 .m_axi_arid(pd_arid),.m_axi_araddr(pd_araddr),.m_axi_arlen(pd_arlen),.m_axi_arsize(pd_arsize),.m_axi_arburst(pd_arburst),.m_axi_arvalid(pd_arvalid),.m_axi_arready(pd_arready),
 .m_axi_rid(pd_rid),.m_axi_rdata(pd_rdata),.m_axi_rresp(pd_rresp),.m_axi_rlast(pd_rlast),.m_axi_rvalid(pd_rvalid),.m_axi_rready(pd_rready));
reg[63:0] pd_memory[0:`DIRECTORY_BEATS-1];
integer pd_requests=0,pd_forwards=0;
initial begin $readmemh("directory.hex",pd_memory);end
always @(posedge clk)if(rst_n)begin
 if(pd_fault||pd_rfault||dp_fault)$fatal(1,"Full-tile directory/reader/arbiter fault code=%d",pd_code);
 if(pd_request&&pd_ready)pd_requests<=pd_requests+1;
 if(pp_job_valid&&pp_job_ready)begin
  if(pd_descriptor_epoch!=EPOCH||pd_descriptor_tag!=1||pd_descriptor_job!=pd_job||pd_busy)$fatal(1,"Full-tile parameter job identity/physical drain");
  pd_forwards<=pd_forwards+1;
 end
 if(pp_done&&(pd_active||pd_busy))$fatal(1,"Configuration done while directory still owns transaction");
end
