reg row_cmd_valid=0;
wire row_cmd_ready,row_sched_done,row_sched_abort,row_sched_fault,row_sched_active;
wire[2:0] row_sched_code;
wire row_post_ready;
integer row_commands=0,row_completions=0,row_posts=0;
z100_native_row_scheduler20 row_scheduler(.clk(clk),.rst_n(rst_n),.cancel(cancel),
    .cmd_valid(row_cmd_valid),.cmd_ready(row_cmd_ready),.cmd_epoch(EPOCH),
    .cmd_token_base(TOKEN_BASE),.cmd_tag_base(32'h53000000),.cmd_channels(11'd3),
    .cmd_input_width(10'd640),.cmd_output_width(10'd320),.cmd_kernel(2'd3),.cmd_stride(2'd2),
    .cmd_padding(2'd1),.cmd_lanes(6'd16),.cmd_bank_words(14'd80),.cmd_channel_plane_stride(14'd80),
    .cmd_ky_row_bases({14'd40,14'd0,14'd0}),.cmd_y_valid(3'b110),
    .run_valid(run_valid),.run_ready(run_ready),.run_epoch(run_epoch),.run_token(run_token),
    .run_lanes(run_lanes),.run_sites(run_sites),
    .window_valid(window_valid),.window_ready(window_ready),.window_epoch(window_epoch),.window_tag(window_tag),
    .window_row_address(window_row_address),.window_first_x(window_first_x),.window_input_width(window_input_width),
    .window_output_remaining(window_output_remaining),.window_sites(window_sites),.window_channel_mask(window_channel_mask),
    .window_stride_two(window_stride_two),.window_y_valid(window_y_valid),
    .post_done_valid(post_valid&&post_ready&&post_last),.post_done_ready(row_post_ready),
    .post_done_epoch(post_epoch),.post_done_token(post_token),.done(row_sched_done),
    .abort_pulse(row_sched_abort),.fault_valid(row_sched_fault),.fault_code(row_sched_code),.active(row_sched_active));
always @(posedge clk)if(rst_n)begin
    if(row_sched_fault||row_sched_abort)$fatal(1,"Actual row scheduler fault/abort code=%d",row_sched_code);
    if(row_cmd_valid&&row_cmd_ready)row_commands<=row_commands+1;
    if(row_sched_done)row_completions<=row_completions+1;
    if(post_valid&&post_ready&&post_last)begin
        if(!row_post_ready||!row_sched_active)$fatal(1,"Unowned row postprocess completion");
        row_posts<=row_posts+1;
    end
    if(run_valid&&run_ready&&(!pp_configured||pp_active||!feature_store_valid||feature_active_epoch!=EPOCH||
       !mac_weights_valid||mac_weights_epoch!=EPOCH||!unary_store_valid||unary_active_epoch!=EPOCH))
        $fatal(1,"Scheduler started before resident feature/parameter publication");
end
task submit_scheduled_row;begin
    @(negedge clk);
    if(row_sched_active||!row_cmd_ready||!pp_configured||pp_active)$fatal(1,"Row command not ready");
    row_cmd_valid=1;do @(posedge clk);while(!row_cmd_ready);
    @(negedge clk);row_cmd_valid=0;
    do @(negedge clk);while(!row_sched_done);
    if(row_sched_active||row_sched_fault)$fatal(1,"Row command failed to retire");
end endtask
task check_scheduled_rows;begin
    if(row_commands!=2||row_completions!=2||row_posts!=32||row_sched_active||row_sched_fault||row_cmd_valid)
        $fatal(1,"Actual two-row scheduler coverage commands=%d done=%d post=%d",row_commands,row_completions,row_posts);
    $display("SCHEDULED_SHARED_COMPUTE_PASS row_commands=2 scheduler_done=2 post_done=32 run_commands=32 descriptors=288 direct_TB_run_descriptors=0");
end endtask
