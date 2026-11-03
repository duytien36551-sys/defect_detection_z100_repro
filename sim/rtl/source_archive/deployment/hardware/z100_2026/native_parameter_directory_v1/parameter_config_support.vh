// Directory and parameter payload readers share one actual physical AXI port.
reg d_command=0;reg[15:0] d_job=0;reg[31:0] d_tag=1;
wire d_command_ready,d_active,d_fault,d_done;wire[3:0] d_code;
wire[15:0] d_descriptor_job;wire[31:0] d_descriptor_tag;
wire dc,dc_ready,dbusy,dfault,dcancel,dclear,dv,dr,dl;
wire[31:0] de,da,doe;wire[13:0] dw;wire[12:0] di;wire[511:0] dd;
wire[5:0] p_arid,d_arid,p_rid,d_rid;wire[31:0] p_araddr,d_araddr;
wire[3:0] p_arlen,d_arlen;wire[2:0] p_arsize,d_arsize;wire[1:0] p_arburst,d_arburst,p_rresp,d_rresp;
wire p_arvalid,p_arready,p_rvalid,p_rready,p_rlast,d_arvalid,d_arready,d_rvalid,d_rready,d_rlast;
wire[63:0] p_rdata,d_rdata;
wire[1:0] arb_arready,arb_rvalid,arb_rlast;wire[11:0] arb_rid;wire[127:0] arb_rdata;wire[3:0] arb_rresp;
wire arb_active,arb_owner,arb_fault;
assign {d_arready,p_arready}=arb_arready;
assign {d_rid,p_rid}=arb_rid;assign {d_rdata,p_rdata}=arb_rdata;assign {d_rresp,p_rresp}=arb_rresp;
assign {d_rvalid,p_rvalid}=arb_rvalid;assign {d_rlast,p_rlast}=arb_rlast;
z100_native_axi_read_arbiter parameter_bus(.clk(clk),.rst_n(rst_n),
 .s_arid({d_arid,p_arid}),.s_araddr({d_araddr,p_araddr}),.s_arlen({d_arlen,p_arlen}),.s_arsize({d_arsize,p_arsize}),.s_arburst({d_arburst,p_arburst}),.s_arvalid({d_arvalid,p_arvalid}),
 .s_arready(arb_arready),.s_rid(arb_rid),.s_rdata(arb_rdata),.s_rresp(arb_rresp),.s_rlast(arb_rlast),.s_rvalid(arb_rvalid),.s_rready({d_rready,p_rready}),
 .m_arid(arid),.m_araddr(araddr),.m_arlen(arlen),.m_arsize(arsize),.m_arburst(arburst),.m_arvalid(arvalid),.m_arready(arready),
 .m_rid(6'd0),.m_rdata(rdata),.m_rresp(rresp),.m_rlast(rlast),.m_rvalid(rvalid),.m_rready(rready),.active(arb_active),.active_owner(arb_owner),.protocol_fault(arb_fault));
z100_native_parameter_directory_v2 directory(.clk(clk),.rst_n(rst_n),.abort(abort),.recover(recover),.consumer_idle(!active&&job_ready&&!load_fault),
 .cmd_valid(d_command),.cmd_ready(d_command_ready),.cmd_epoch(32'd200),.cmd_tag(d_tag),.cmd_table_base(32'h21000000),.cmd_model_crc(`MODEL_CRC),
 .cmd_payload_begin(32'h20000000),.cmd_payload_end(33'h20000000+`PAYLOAD_BYTES),.cmd_job(d_job),.cmd_count(16'd173),.cmd_timeout(32'd500000),
 .reader_command(dc),.reader_command_ready(dc_ready),.reader_epoch(de),.reader_address(da),.reader_words(dw),.reader_busy(dbusy),.reader_fault(dfault),.reader_cancel(dcancel),.reader_clear(dclear),
 .reader_valid(dv),.reader_ready(dr),.reader_result_epoch(doe),.reader_index(di),.reader_last(dl),.reader_data(dd),
 .descriptor_valid(job_valid),.descriptor_ready(job_ready),.descriptor_epoch(job_epoch),.descriptor_tag(d_descriptor_tag),.descriptor_job(d_descriptor_job),
 .descriptor_groups(job_groups),.descriptor_lanes(job_lanes),.descriptor_weights(job_weights),.descriptor_bias(job_bias),.descriptor_factors(job_factors),.descriptor_unary(job_unary),
 .active(d_active),.needs_drain(),.done(d_done),.fault(d_fault),.fault_code(d_code));
z100_native_axi64_reader directory_reader(.clk(clk),.rst_n(rst_n),.cmd_valid(dc),.cmd_ready(dc_ready),.cmd_epoch(de),.cmd_address(da),.cmd_word_count(dw),.cancel(dcancel),.timeout(1'b0),.clear_fault(dclear),
 .busy(dbusy),.done(),.fault(dfault),.fault_code(),.out_valid(dv),.out_ready(dr),.out_epoch(doe),.out_index(di),.out_last(dl),.out_data(dd),
 .m_axi_arid(d_arid),.m_axi_araddr(d_araddr),.m_axi_arlen(d_arlen),.m_axi_arsize(d_arsize),.m_axi_arburst(d_arburst),.m_axi_arvalid(d_arvalid),.m_axi_arready(d_arready),
 .m_axi_rid(d_rid),.m_axi_rdata(d_rdata),.m_axi_rresp(d_rresp),.m_axi_rlast(d_rlast),.m_axi_rvalid(d_rvalid),.m_axi_rready(d_rready));
reg[63:0] directory_memory[0:`DIRECTORY_BEATS-1];
integer directory_forwards=0,parameter_completions=0;
initial begin $readmemh("directory.hex",directory_memory);end
always @(posedge clk)if(rst_n)begin
 if(d_fault||dfault||arb_fault)$fatal(1,"Actual directory/physical bus error %d",d_code);
 if(d_done)directory_forwards<=directory_forwards+1;
 if(job_valid&&job_ready)begin
  if(d_descriptor_job!=d_job||d_descriptor_tag!=d_tag||dbusy||job_epoch!=200)$fatal(1,"Directory forwarded wrong job or undrained reader");
 end
 if(load_done)begin
  if(d_active||dbusy||!configured||load_fault)$fatal(1,"Parameter completed before real directory/configuration drain");
  parameter_completions<=parameter_completions+1;
 end
end
