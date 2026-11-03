`timescale 1ns/1ps
`default_nettype none
`include "directory_defs.vh"
module tb_z100_native_parameter_directory_v2;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,abort=0,recover=0,consumer_idle=1;
 reg cmd_valid=0;wire cmd_ready;reg[31:0] cmd_epoch=200,cmd_tag=1,cmd_table_base=32'h21000000,cmd_model_crc=`MODEL_CRC,cmd_payload_begin=32'h20000000;
 reg[32:0] cmd_payload_end=33'h20000000+`PAYLOAD_BYTES;reg[15:0] cmd_job=0,cmd_count=173;reg[31:0] cmd_timeout=50000;
 wire reader_command,reader_command_ready,reader_busy,reader_fault,reader_cancel,reader_clear,reader_valid,reader_ready,reader_last;
 wire[31:0] reader_epoch,reader_address,reader_result_epoch;wire[13:0] reader_words;wire[12:0] reader_index;wire[511:0] reader_data;
 wire descriptor_valid;reg descriptor_ready=0;wire[31:0] descriptor_epoch,descriptor_tag;
 wire[15:0] descriptor_job;wire[10:0] descriptor_groups;wire[5:0] descriptor_lanes;
 wire[31:0] descriptor_weights,descriptor_bias,descriptor_factors,descriptor_unary;
 wire active,needs_drain,done,fault;wire[3:0] fault_code;
 reg inject_meta=0;
 wire[31:0] rd_epoch;wire[12:0] rd_index;wire rd_last;
 z100_native_parameter_directory_v2 dut(.reader_result_epoch(inject_meta?32'd1:rd_epoch),.*);
 wire[5:0] arid;wire[31:0] araddr;wire[3:0] arlen;wire[2:0] arsize;wire[1:0] arburst;wire arvalid,rready;
 reg block_ar=0,block_r=0,inject_resp=0;integer cycle=0;wire arready=!block_ar&&cycle%7!=0;
 reg rvalid=0,rlast=0;reg[63:0] rdata=0;reg[1:0] rresp=0;
 z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(reader_command),.cmd_ready(reader_command_ready),
  .cmd_epoch(reader_epoch),.cmd_address(reader_address),.cmd_word_count(reader_words),.cancel(reader_cancel),.timeout(1'b0),.clear_fault(reader_clear),
  .busy(reader_busy),.done(),.fault(reader_fault),.fault_code(),.out_valid(reader_valid),.out_ready(reader_ready),.out_epoch(rd_epoch),.out_index(reader_index),.out_last(reader_last),.out_data(reader_data),
  .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
  .m_axi_rid(6'd0),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
 reg[63:0] memory[0:`DIRECTORY_BEATS-1];reg[191:0] expected_jobs[0:172];
 reg mem_active=0;reg[31:0] mem_address=0;integer beat=0,beats=0,ars=0,rbeats=0,held_ar=0;
 reg ar_hold=0;reg[46:0] ar_saved;
 always @(posedge clk)begin
  cycle<=cycle+1;
  if(rst_n)begin
   if(ar_hold&&(!arvalid||{arid,araddr,arlen,arsize,arburst}!==ar_saved))$fatal(1,"Directory physical AR changed under hold/cancel");
   ar_hold<=arvalid&&!arready;ar_saved<={arid,araddr,arlen,arsize,arburst};if(ar_hold)held_ar<=held_ar+1;
   if(arvalid&&arready)begin
    if(mem_active||arid!=0||arsize!=3||arburst!=1||arlen!=7||araddr[5:0]!=0||araddr<32'h21000000||araddr+64>32'h21000000+`DIRECTORY_BYTES)$fatal(1,"Directory physical read bounds/identity");
    mem_active<=1;mem_address<=araddr;beat<=0;beats<=arlen+1;ars<=ars+1;
   end
   if(rvalid&&rready)begin rvalid<=0;rbeats<=rbeats+1;if(rlast)mem_active<=0;else beat<=beat+1;end
   if(mem_active&&!rvalid&&!block_r&&cycle%3!=0)begin
    rvalid<=1;rdata<=memory[(mem_address-32'h21000000)/8+beat];rlast<=beat+1==beats;rresp<=inject_resp&&beat==2?2:0;
   end
  end
 end
 integer requests=0,forwarded=0,holds=0,failures=0,early_blocks=0,consumer_blocks=0;
 reg[224:0] saved_descriptor;
 task tick;begin @(posedge clk);#1;end endtask
 task issue(input integer job);begin
  @(negedge clk);cmd_job=job;cmd_tag=requests+1;cmd_valid=1;
  #1;if(!cmd_ready)$fatal(1,"Directory command not ready");tick();@(negedge clk);cmd_valid=0;requests=requests+1;
 end endtask
 task recover_fault;begin
  if(!fault||!needs_drain||cmd_ready||descriptor_valid||done)$fatal(1,"Directory error not isolated");
  @(negedge clk);recover=1;
  do begin tick();@(negedge clk);end while(fault||reader_fault||reader_busy||!cmd_ready);
  recover=0;failures=failures+1;
 end endtask
 task valid_job(input integer job);integer expected_tag;begin
  expected_tag=requests+1;issue(job);
  // Latched command pins may change while the request is owned.
  cmd_job=173;cmd_tag=0;cmd_table_base=0;
  while(!descriptor_valid)begin tick();if(fault)$fatal(1,"Valid immutable descriptor rejected job=%d code=%d",job,fault_code);end
  if(reader_busy||mem_active||descriptor_job!=job||descriptor_epoch!=200||descriptor_tag!=expected_tag||
     {descriptor_lanes,descriptor_groups,descriptor_unary,descriptor_factors,descriptor_bias,descriptor_weights}!==expected_jobs[job][144:0])$fatal(1,"Directory differs from original independently bound parameter job %d",job);
  saved_descriptor={descriptor_epoch,descriptor_tag,descriptor_job,descriptor_lanes,descriptor_groups,descriptor_unary,descriptor_factors,descriptor_bias,descriptor_weights};
  repeat(4)begin tick();if(!descriptor_valid||reader_busy||done||{descriptor_epoch,descriptor_tag,descriptor_job,descriptor_lanes,descriptor_groups,descriptor_unary,descriptor_factors,descriptor_bias,descriptor_weights}!==saved_descriptor)$fatal(1,"Directory held descriptor changed or forwarded before consumer");holds=holds+1;end
  @(negedge clk);descriptor_ready=1;tick();@(negedge clk);descriptor_ready=0;consumer_idle=0;
  if(!done||active||fault)$fatal(1,"Descriptor forward completion missing");forwarded=forwarded+1;
  repeat(3)begin tick();if(cmd_ready)$fatal(1,"Directory admitted while real consumer not idle");consumer_blocks=consumer_blocks+1;end
  @(negedge clk);consumer_idle=1;cmd_table_base=32'h21000000;
 end endtask
 reg[255:0] original;integer j,c,old_ars;
 initial begin
  $readmemh("directory.hex",memory);$readmemh("parameter_jobs.hex",expected_jobs);
  repeat(5)tick();@(negedge clk);rst_n=1;
  for(j=0;j<173;j=j+1)valid_job(j);
  if(forwarded!=173||ars!=173||rbeats!=1384||holds!=692||consumer_blocks!=519)$fatal(1,"All173 directory coverage");
  original={memory[3],memory[2],memory[1],memory[0]};
  for(c=0;c<11;c=c+1)begin
   {memory[3],memory[2],memory[1],memory[0]}=original;
   case(c)
    0:memory[2][48]=!memory[2][48]; //magic bit176
    1:memory[3][0]=!memory[3][0]; //model CRC bit192
    2:memory[2][32]=!memory[2][32]; //job index bit160
    3:memory[2][10:0]=0;
    4:memory[2][16:11]=0;
    5:memory[0][0]=!memory[0][0];
    6:memory[0][31:0]=32'hffffffc0;
    7:memory[3][32]=1; //reserved bit224
    8:memory[0][32]=!memory[0][32]; //bias alignment
    9:memory[1][31:0]=0; //factor outside region
    10:memory[1][63:32]=32'h21000000; //unary outside region
   endcase
   issue(0);while(!fault)tick();if(fault_code!=6)$fatal(1,"Bad descriptor fault classification %d",fault_code);recover_fault();
  end
  {memory[3],memory[2],memory[1],memory[0]}=original;
  old_ars=ars;issue(173);if(!fault||fault_code!=1||ars!=old_ars)$fatal(1,"Bad index issued DDR");recover_fault();
  inject_meta=1;issue(0);while(!fault)tick();inject_meta=0;if(fault_code!=5)$fatal(1,"Metadata epoch mismatch accepted");recover_fault();
  inject_resp=1;issue(0);while(!fault)tick();inject_resp=0;if(fault_code!=4)$fatal(1,"Physical reader error not isolated");recover_fault();
  // Both explicit abort and timeout must preserve an advertised physical AR.
  for(c=0;c<2;c=c+1)begin
   block_ar=1;cmd_timeout=c==0?50000:12;issue(0);while(!arvalid)tick();
   if(c==0)begin @(negedge clk);abort=1;tick();@(negedge clk);abort=0;end
   while(!fault)tick();if(fault_code!=(c==0?2:3))$fatal(1,"Abort/timeout classification");
   @(negedge clk);recover=1;
   repeat(6)begin tick();if(!fault||!reader_busy||!arvalid||cmd_ready||reader_clear)$fatal(1,"Directory discarded held physical read");early_blocks=early_blocks+1;end
   @(negedge clk);recover=0;block_ar=0;recover_fault();
  end
  cmd_timeout=50000;valid_job(172);
  if(failures!=16||early_blocks!=12||forwarded!=174||held_ar<12)$fatal(1,"Directory error/recovery/consumer coverage");
  $display("PARAMETER_DIRECTORY_PASS model_jobs=173 validated_forwards=174 rejected_records=11 bad_index=1 metadata_error=1 reader_error=1 abort_timeout=2 recoveries=16 early_recovery_blocks=12 held_descriptor_cycles=%0d consumer_busy_blocks=%0d physical_AR=%0d physical_R=%0d held_AR_cycles=%0d",holds,consumer_blocks,ars,rbeats,held_ar);
  $finish;
 end
 initial begin #10000000;$fatal(1,"Parameter directory watchdog forwards=%d failures=%d AR=%d R=%d state=%d reader_fault=%b busy=%b",forwarded,failures,ars,rbeats,dut.state,reader_fault,reader_busy);end
endmodule
`default_nettype wire
