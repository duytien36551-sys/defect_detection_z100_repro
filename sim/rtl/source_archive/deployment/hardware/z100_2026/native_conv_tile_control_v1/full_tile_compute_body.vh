// Appended to the source-bound full20site core declaration/instance seam.
reg ft_command=0;wire ft_command_ready,ft_done,ft_fault,ft_active,ft_drain;
wire[3:0] ft_fault_code;wire[31:0] ft_epoch,ft_job;
wire ft_row_valid,ft_row_ready,ft_row_done_ready,ft_param_done_ready,ft_publish_ready;
wire[31:0] ft_token,ft_tag;wire[10:0] ft_channels;wire[9:0] ft_iw,ft_ow;
wire[1:0] ft_kernel,ft_stride,ft_padding;wire[5:0] ft_lanes;
wire[13:0] ft_bank_words,ft_plane;wire[41:0] ft_bases;wire[2:0] ft_yvalid;wire[15:0] ft_parameter_job;
wire ft_scheduler_done,ft_scheduler_abort,ft_scheduler_fault,ft_scheduler_active,ft_post_ready;
wire[2:0] ft_scheduler_code;
reg[31:0] ft_last_post_epoch=0,ft_last_post_token=0;
z100_native_conv_tile_control_v2 tile_control(.clk(clk),.rst_n(rst_n),.cancel(cancel),.recover(1'b0),.recovery_drained(1'b0),
 .cmd_valid(ft_command),.cmd_ready(ft_command_ready),.cmd_epoch(EPOCH),.cmd_token_base(TOKEN_BASE),.cmd_tag_base(32'h53000000),.cmd_job_tag(32'd1),
 .cmd_parameter_first(16'd0),.cmd_input_channels(11'd3),.cmd_output_channels(11'd16),
 .cmd_input_height(10'd640),.cmd_input_width(10'd640),.cmd_input_y(10'd0),.cmd_input_rows(10'd40),
 .cmd_output_height(10'd320),.cmd_output_width(10'd320),.cmd_output_y(10'd0),.cmd_output_rows(10'd20),.cmd_kernel(2'd3),.cmd_stride(2'd2),.cmd_padding(2'd1),
 .pack_valid(pack_cfg_valid),.pack_ready(pack_cfg_ready),.epoch(ft_epoch),.job_tag(ft_job),.pack_token_base(pack_cfg_token_base),
 .pack_channels(pack_cfg_channels),.pack_height(pack_cfg_height),.pack_width(pack_cfg_width),
 .parameter_valid(pp_job_valid),.parameter_ready(pp_job_ready),.parameter_job(ft_parameter_job),
 .parameter_done_valid(pp_done),.parameter_done_ready(ft_param_done_ready),.parameter_done_epoch(EPOCH),.parameter_done_job(16'd0),
 .parameter_done_job_tag(ft_job),.parameter_done_error(pp_fault||pp_bridge_fault),
 .row_valid(ft_row_valid),.row_ready(ft_row_ready),.row_token_base(ft_token),.row_tag_base(ft_tag),.row_channels(ft_channels),
 .row_input_width(ft_iw),.row_output_width(ft_ow),.row_kernel(ft_kernel),.row_stride(ft_stride),.row_padding(ft_padding),
 .row_lanes(ft_lanes),.row_bank_words(ft_bank_words),.row_plane_stride(ft_plane),.row_ky_bases(ft_bases),.row_y_valid(ft_yvalid),
 .row_done_valid(ft_scheduler_done),.row_done_ready(ft_row_done_ready),.row_done_epoch(ft_last_post_epoch),.row_done_last_token(ft_last_post_token),
 .row_done_job_tag(ft_job),.row_done_error(ft_scheduler_fault||ft_scheduler_abort),
 .publish_valid(wb_done),.publish_ready(ft_publish_ready),.publish_epoch(wb_epoch),.publish_tag(ft_job),.publish_error(wb_fault||!wb_committed),
 .child_cancel(ft_cancel),.active(ft_active),.needs_drain(ft_drain),.done(ft_done),.fault(ft_fault),.fault_code(ft_fault_code));
assign pack_cfg_epoch=ft_epoch;
z100_native_row_scheduler20 row_scheduler(.clk(clk),.rst_n(rst_n),.cancel(cancel||ft_cancel),
 .cmd_valid(ft_row_valid),.cmd_ready(ft_row_ready),.cmd_epoch(ft_epoch),.cmd_token_base(ft_token),.cmd_tag_base(ft_tag),
 .cmd_channels(ft_channels),.cmd_input_width(ft_iw),.cmd_output_width(ft_ow),.cmd_kernel(ft_kernel),.cmd_stride(ft_stride),.cmd_padding(ft_padding),
 .cmd_lanes(ft_lanes),.cmd_bank_words(ft_bank_words),.cmd_channel_plane_stride(ft_plane),.cmd_ky_row_bases(ft_bases),.cmd_y_valid(ft_yvalid),
 .run_valid(run_valid),.run_ready(run_ready),.run_epoch(run_epoch),.run_token(run_token),.run_lanes(run_lanes),.run_sites(run_sites),
 .window_valid(window_valid),.window_ready(window_ready),.window_epoch(window_epoch),.window_tag(window_tag),.window_row_address(window_row_address),
 .window_first_x(window_first_x),.window_input_width(window_input_width),.window_output_remaining(window_output_remaining),.window_sites(window_sites),
 .window_channel_mask(window_channel_mask),.window_stride_two(window_stride_two),.window_y_valid(window_y_valid),
 .post_done_valid(post_valid&&post_ready&&post_last),.post_done_ready(ft_post_ready),.post_done_epoch(post_epoch),.post_done_token(post_token),
 .done(ft_scheduler_done),.abort_pulse(ft_scheduler_abort),.fault_valid(ft_scheduler_fault),.fault_code(ft_scheduler_code),.active(ft_scheduler_active));
integer ft_cycle=0,ft_rows=0,ft_param_completions=0,ft_pack_configs=0,ft_done_count=0,ft_guards=0,ft_checked=0;
reg[1599:0] ft_seen=0;
reg ft_rhold=0,ft_phold=0,ft_whold=0;
reg[1099:0] ft_raw_saved;reg[331:0] ft_post_saved;reg[557:0] ft_word_saved;
integer fi,fj,fy,fx,fg,fsegment,fsy;
always @(negedge clk)if(rst_n)conv_allow=(ft_cycle%23)>5;
always @(posedge clk)begin
 ft_cycle<=ft_cycle+1;
 if(rst_n)begin
  if(feature_error_valid||mac_error_valid||req_cfg_error||req_input_error||unary_error_valid||pack_error_valid||metadata_error||
     ft_fault||ft_scheduler_fault||ft_scheduler_abort||pool_error)$fatal(1,"Full tile child/control fault %d/%d",ft_fault_code,ft_scheduler_code);
  if(pack_cfg_valid&&pack_cfg_ready)ft_pack_configs<=ft_pack_configs+1;
  if(pp_done)begin if(!ft_param_done_ready||ft_parameter_job!=0)$fatal(1,"Unowned real parameter completion");ft_param_completions<=ft_param_completions+1;end
  if(ft_scheduler_done)begin if(!ft_row_done_ready)$fatal(1,"Unowned real row completion");ft_rows<=ft_rows+1;end
  if(wb_done&&!ft_publish_ready)$fatal(1,"Real writer completion not owned by tile");
  if(ft_done)begin if(!wb_committed||wb_wbusy||wb_active||wb_awowned||wb_bvalid||wb_bdelay!=0)$fatal(1,"Tile completion before physical B/publication drain");ft_done_count<=ft_done_count+1;end
  if(run_valid&&run_ready)begin
   if(run_epoch!=EPOCH||run_token!=TOKEN_BASE+run_count||run_lanes!=16||run_sites!=20||run_count>=320||!pp_configured||pp_active||!feature_store_valid||feature_active_epoch!=EPOCH)
    $fatal(1,"Full tile run identity/resident publication");run_count<=run_count+1;
  end
  if(window_valid&&window_ready)begin
   fi=window_request_count;fy=fi/144;fg=fi%9;fsegment=(fi/9)%16;fsy=fy*2-1+fg/3;
   if(fi>=2880||window_epoch!=EPOCH||window_tag!=32'h53000000+fi||window_row_address!=((fsy>=0&&fsy<40)?fsy*40:0)||
      $signed(window_first_x)!=fsegment*40+fg%3-1||window_input_width!=640||window_output_remaining!=320-fsegment*20||
      window_sites!=20||window_channel_mask!=7||!window_stride_two||window_y_valid!=(fsy>=0&&fsy<40))$fatal(1,"Full tile descriptor geometry index=%d",fi);
   window_request_count<=window_request_count+1;
  end
  if(ft_rhold&&(!raw_valid||{raw_token,raw_site,raw_last,raw_lanes,raw_data,raw_overflow}!==ft_raw_saved))$fatal(1,"Full tile raw held payload changed");
  ft_rhold<=raw_valid&&!raw_ready;ft_raw_saved<={raw_token,raw_site,raw_last,raw_lanes,raw_data,raw_overflow};
  if(raw_valid&&raw_ready)begin
   fi=raw_beats;
   if(fi>=6400||raw_token!=TOKEN_BASE+fi/20||raw_site!=fi%20||raw_lanes!=16||raw_last!=(fi%20==19)||{raw_data,raw_overflow}!==expected_raw_words[fi])$fatal(1,"Full tile original OIHW raw mismatch pixel=%d",fi);
   raw_beats<=raw_beats+1;
  end
  if(ft_phold&&(!post_valid||{post_epoch,post_token,post_site,post_lanes,post_last,post_data}!==ft_post_saved))$fatal(1,"Full tile post held payload changed");
  ft_phold<=post_valid&&!post_ready;ft_post_saved<={post_epoch,post_token,post_site,post_lanes,post_last,post_data};
  if(post_valid&&post_ready)begin
   fi=post_beats;
   if(fi>=6400||post_epoch!=EPOCH||post_token!=TOKEN_BASE+fi/20||post_site!=fi%20||post_lanes!=16||post_last!=(fi%20==19)||post_data!==expected_post_words[fi])$fatal(1,"Full tile original binary64/SiLU post mismatch pixel=%d",fi);
   if(post_last)begin if(!ft_post_ready)$fatal(1,"Real post completion stalled");ft_last_post_epoch<=post_epoch;ft_last_post_token<=post_token;end
   post_beats<=post_beats+1;
  end
  if(ft_whold&&(!packed_valid||{packed_epoch,packed_address,packed_data,packed_last}!==ft_word_saved))$fatal(1,"Full tile packed held payload changed");
  ft_whold<=packed_valid&&!packed_ready;ft_word_saved<={packed_epoch,packed_address,packed_data,packed_last};
  if(packed_valid&&packed_ready)begin
   if(packed_beats>=1600||packed_address>=1600||ft_seen[packed_address]||packed_epoch!=EPOCH||packed_last!=(packed_beats==1599)||packed_data!==expected_packed_words[packed_address])$fatal(1,"Full tile canonical packed mismatch word=%d address=%d",packed_beats,packed_address);
   ft_seen[packed_address]<=1;packed_beats<=packed_beats+1;
  end
 end
end
task load_full_tile_DDR;begin
 @(negedge clk);pf_active=1;pf_bank_pin=0;old_load_bank=0;compute_source_bank=0;
 acquire_load_lease(0);while(!pf_command_ready)@(negedge clk);
 pf_command_valid=1;@(posedge clk);#1;@(negedge clk);pf_command_valid=0;
 wait(pf_done);@(posedge clk);#1;
 if(!pf_result||!feature_load_store_valid||feature_load_active_epoch!=EPOCH||pf_reader_busy||pf_codec_active||pf_loaded!=1600||pf_commands!=1||pf_ars!=800||pf_rbeats!=12800)$fatal(1,"Full input halo DDR publication/coverage");
 release_load_lease();@(negedge clk);pf_active=0;
end endtask
reg[511:0] expected_ddr[0:1599];
initial begin
 $readmemh("expected_raw_words.hex",expected_raw_words);$readmemh("expected_post_words.hex",expected_post_words);
 $readmemh("expected_packed_words.hex",expected_packed_words);$readmemh("expected_ddr_words.hex",expected_ddr);
 for(fi=0;fi<65536;fi=fi+1)wb_memory[fi]=64'h5a1bc43df609728e;
 #250;repeat(5)@(negedge clk);rst_n=1;load_full_tile_DDR();
 @(negedge clk);ft_command=1;#1;if(!ft_command_ready)$fatal(1,"Full tile not admitted");@(posedge clk);#1;@(negedge clk);ft_command=0;
 wait(ft_done);repeat(3)@(negedge clk);
 if(ft_done_count!=1||ft_rows!=20||ft_param_completions!=1||ft_pack_configs!=1||run_count!=320||window_request_count!=2880||
    raw_beats!=6400||post_beats!=6400||packed_beats!=1600||ft_seen!=={1600{1'b1}}||ft_active||ft_fault||
    wb_completed!=1||wb_scheduled!=1||wb_packed!=1600||wb_aws!=800||wb_ws!=12800||wb_bs!=800||wb_active||wb_wbusy||
    pp_configs!=288||pp_commands!=4||pp_ars!=14||pp_beats!=224||!pp_configured||pp_rbusy||shared_active||shared_fault||
    shared_ars!=814||shared_rs!=13024||shared_owner0!=12800||shared_owner1!=224)$fatal(1,"Full tile complete-path coverage");
 for(fi=0;fi<1600;fi=fi+1)for(fj=0;fj<8;fj=fj+1)begin
  if(wb_memory[fi*8+fj]!==expected_ddr[fi][fj*64+:64])$fatal(1,"Full tile native DDR golden word=%d beat=%d",fi,fj);ft_checked=ft_checked+1;
 end
 for(fi=12800;fi<65536;fi=fi+1)begin if(wb_memory[fi]!==64'h5a1bc43df609728e)$fatal(1,"Full tile outside reserved output region modified");ft_guards=ft_guards+1;end
 $display("FULL_CONV_TILE_COMPUTE_PASS output_rows=20 row_commands=20 runs=320 descriptors=2880 raw_pixels=6400 raw_lanes=204800 post_bytes=204800 packed_words=1600 feature_DDR_beats=12800 parameter_DDR_beats=224 output_DDR_beats=12800 physical_AR=814 output_AW=800 output_B=800 publication_after_B=1 guard_beats=52736");
 $finish;
end
initial begin #20000000;$fatal(1,"Full tile compute watchdog");end
