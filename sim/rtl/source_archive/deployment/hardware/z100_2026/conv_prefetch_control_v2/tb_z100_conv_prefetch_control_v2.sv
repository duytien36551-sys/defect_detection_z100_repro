`timescale 1ns/1ps
`default_nettype none
module tb_z100_conv_prefetch_control_v2;
 reg clk=0; always #5 clk=~clk;
 reg rst_n=0,cancel=0,recover=0,recovery_drained=0;
 reg cmd_valid=0;
 wire cmd_ready;
 reg[31:0] cmd_epoch=1,cmd_job_base=1,cmd_token_base=1,cmd_tag_base=1;
 reg[7:0] cmd_tiles=1;
 reg[9:0] cmd_output_height=20;
 reg cmd_first_bank=0,source_leased=1,destination_reserved=1;
 reg descriptor_valid=0;
 wire descriptor_ready;
 reg[31:0] descriptor_epoch=1;
 reg[7:0] descriptor_index=0;
 reg[9:0] descriptor_input_y=0,descriptor_input_rows=40;
 reg[9:0] descriptor_output_y=0,descriptor_output_rows=20;
 reg[31:0] descriptor_runs=16,descriptor_windows=144;
 wire[7:0] next_descriptor;
 wire load_valid;
 reg load_ready=0;
 wire load_bank;
 wire[31:0] load_job_tag;
 wire[9:0] load_input_y,load_input_rows;
 reg load_done=0,load_committed=1,load_fault=0;
 reg[31:0] load_epoch=1;
 reg load_done_bank=0;
 wire tile_valid;
 reg tile_ready=0;
 wire tile_bank;
 wire[31:0] tile_job_tag,tile_token_base,tile_tag_base;
 wire[9:0] tile_input_y,tile_input_rows,tile_output_y,tile_output_rows;
 reg tile_done=0,tile_fault=0;
 reg[31:0] tile_done_epoch=1,tile_done_job=1;
 reg tile_done_bank=0;
 reg load_quiet=1,tile_write_quiet=1,all_io_quiet=1;
 wire[31:0] epoch;
 wire child_cancel,active,needs_drain;
 wire done,fault;
 wire[3:0] fault_code;
 wire[7:0] committed_tiles;

 z100_conv_prefetch_control dut(.*);

 // Four independent files bind raw C geometry, event grouping, run totals,
 // and window totals. The bench does not infer plan contents from DUT state.
 reg[31:0] geometry_mem[0:2456];
 reg[31:0] event_mem[0:251];
 reg[31:0] run_mem[0:188];
 reg[31:0] window_mem[0:188];

 integer events_seen=0,tiles_seen=0,negative_cases=0,recovery_blocks=0;
integer held_load_cycles=0,held_tile_cycles=0,overlap_cycles=0;
integer held_load_on_tile_done=0,held_tile_on_load_done=0;
 integer event_no,first_tile,tile_count,event_id,out_height;
 integer desc_sent,loads_accepted,loads_completed,tiles_accepted,tiles_completed,tiles_drained;
 integer model_cycles,desc_hs,load_hs,load_ack,tile_hs,tile_ack,drain_ack;
 integer local_tile,global_tile,bank_no,exp_bank,raw_base;
 integer load_hold,tile_hold,final_quiet_hold,done_seen;
 integer load_pending,load_timer,load_pending_tile,load_pending_bank;
 integer tile_pending,tile_timer,tile_pending_tile,tile_pending_bank;
 integer drain_pending,drain_timer,drain_tile,drain_bank;
 integer bank_owned[0:1],bank_loaded[0:1],bank_tile[0:1];
 integer prev_load_valid,prev_load_stalled,prev_tile_valid,prev_tile_stalled;
 integer prev_desc_valid,prev_desc_stalled;
 reg prev_load_bank,prev_tile_bank;
 reg[31:0] prev_load_job,prev_tile_job,prev_tile_token,prev_tile_tag;
 reg[9:0] prev_load_y,prev_load_rows,prev_tile_iy,prev_tile_ir,prev_tile_oy,prev_tile_orows;
 reg[31:0] prev_desc_epoch,prev_desc_runs,prev_desc_windows;
 reg[7:0] prev_desc_index;
 reg[9:0] prev_desc_iy,prev_desc_ir,prev_desc_oy,prev_desc_orows;
 reg[31:0] token_cursor,tag_cursor,job_cursor;
 integer i,j,k;
integer total_run_check,total_window_check;
integer initial_bank_mask=0;

 task step;
  begin @(posedge clk); #1; @(negedge clk); end
 endtask

 task reset_case;
  begin
   rst_n=0;cancel=0;recover=0;recovery_drained=0;cmd_valid=0;
   cmd_epoch=1;cmd_job_base=1;cmd_token_base=1;cmd_tag_base=1;cmd_tiles=1;
   cmd_output_height=20;cmd_first_bank=0;source_leased=1;destination_reserved=1;
   descriptor_valid=0;descriptor_epoch=1;descriptor_index=0;
   descriptor_input_y=0;descriptor_input_rows=40;descriptor_output_y=0;descriptor_output_rows=20;
   descriptor_runs=16;descriptor_windows=144;
   load_ready=0;load_done=0;load_committed=1;load_fault=0;load_epoch=1;load_done_bank=0;
   tile_ready=0;tile_done=0;tile_fault=0;tile_done_epoch=1;tile_done_job=1;tile_done_bank=0;
   load_quiet=1;tile_write_quiet=1;all_io_quiet=1;
   repeat(2) step;
   rst_n=1;step;
   if(!cmd_ready||fault)$fatal(1,"reset did not return idle");
  end
 endtask

 task start_command;
  integer timeout;
  begin
   cmd_valid=1;timeout=0;
   while(!cmd_ready && timeout<20) begin step;timeout=timeout+1;end
   if(!cmd_ready)$fatal(1,"command not accepted at public ready");
   step;cmd_valid=0;
  end
 endtask

 task set_one_descriptor;
  input[31:0] ep;
  input[7:0] ix;
  input[9:0] iy,ir,oy,orows;
  input[31:0] runs,windows;
  integer timeout;
  begin
   descriptor_epoch=ep;descriptor_index=ix;descriptor_input_y=iy;descriptor_input_rows=ir;
   descriptor_output_y=oy;descriptor_output_rows=orows;descriptor_runs=runs;descriptor_windows=windows;
   descriptor_valid=1;timeout=0;
   while(!descriptor_ready && timeout<100) begin step;timeout=timeout+1;end
   if(!descriptor_ready)$fatal(1,"descriptor never became ready");
   step;descriptor_valid=0;
  end
 endtask

 task accept_one_load;
  integer timeout;
  begin
   timeout=0;
   while(!load_valid && !fault && timeout<100) begin step;timeout=timeout+1;end
   if(!load_valid)$fatal(1,"load command missing");
   load_ready=1;load_quiet=0;all_io_quiet=0;step;load_ready=0;
  end
 endtask

 task complete_one_load;
  input[31:0] ep;
  input bank;
  input committed;
  begin
   repeat(2) begin step;if(tile_valid)$fatal(1,"tile visible before load commit");end
   load_epoch=ep;load_done_bank=bank;load_committed=committed;load_done=1;
   step;load_done=0;load_committed=1;load_quiet=1;
  end
 endtask

 task accept_one_tile;
  integer timeout;
  begin
   timeout=0;
   while(!tile_valid && !fault && timeout<100) begin step;timeout=timeout+1;end
   if(!tile_valid)$fatal(1,"tile command missing after committed load");
   tile_ready=1;step;tile_ready=0;
  end
 endtask

 task complete_one_tile;
  input[31:0] ep,job;
  input bank;
  begin
   repeat(2) step;
   tile_done_epoch=ep;tile_done_job=job;tile_done_bank=bank;tile_done=1;
   step;tile_done=0;
  end
 endtask

 task expect_fault;
  integer timeout;
  begin
   timeout=0;
   while(!fault && timeout<20) begin step;timeout=timeout+1;end
   if(!fault||fault_code==0||!child_cancel||!needs_drain||done||cmd_ready||descriptor_ready||load_valid||tile_valid)
    $fatal(1,"fault-closed public contract not held");
  end
 endtask

 function[31:0] runs_before;
  input integer first;
  input integer count;
  integer n;
  reg[31:0] acc;
  begin acc=0;for(n=0;n<count;n=n+1)acc=acc+run_mem[first+n];runs_before=acc;end
 endfunction

 function[31:0] windows_before;
  input integer first;
  input integer count;
  integer n;
  reg[31:0] acc;
  begin acc=0;for(n=0;n<count;n=n+1)acc=acc+window_mem[first+n];windows_before=acc;end
 endfunction

 task run_c_plan;
  integer ev,first,count,eid,height,ds,la,lc,ta,tc,td,cycles,local_ix,tile_ix,bn,raw;
  integer hdesc,hload,ackload,htile,acktile,retire,timeout,token_base_local,tag_base_local;
  integer held_load_before,held_tile_before;
  integer exp_load_bank,exp_tile_bank,seen_done;
  integer current_load_stall,current_tile_stall;
  reg[31:0] load_epoch_snap,load_job_snap;
  reg[9:0] load_y_snap,load_rows_snap;
  reg load_bank_snap;
  reg[31:0] tile_job_snap,tile_token_snap,tile_tag_snap;
  reg[9:0] tile_iy_snap,tile_ir_snap,tile_oy_snap,tile_orows_snap;
  reg tile_bank_snap;
  begin
   token_cursor=1;tag_cursor=1;job_cursor=32'h1000;initial_bank_mask=0;
   for(ev=0;ev<63;ev=ev+1) begin
    first=event_mem[ev*4];count=event_mem[ev*4+1];eid=event_mem[ev*4+2];height=event_mem[ev*4+3];
    if(count<1||count>189||first<0||first+count>189||height<1||height>640)
     $fatal(1,"bad event fixture ev=%0d",ev);
    cmd_epoch=100+ev;cmd_job_base=job_cursor;cmd_token_base=token_cursor;cmd_tag_base=tag_cursor;
    cmd_tiles=count;cmd_output_height=height;cmd_first_bank=ev[0];initial_bank_mask=initial_bank_mask|(1<<ev[0]);
    source_leased=1;destination_reserved=1;start_command;
    ds=0;la=0;lc=0;ta=0;tc=0;td=0;cycles=0;seen_done=0;
    load_pending=0;load_timer=0;load_pending_tile=-1;load_pending_bank=-1;
    tile_pending=0;tile_timer=0;tile_pending_tile=-1;tile_pending_bank=-1;
    drain_pending=0;drain_timer=0;drain_tile=-1;drain_bank=-1;
    bank_owned[0]=0;bank_owned[1]=0;bank_loaded[0]=0;bank_loaded[1]=0;bank_tile[0]=-1;bank_tile[1]=-1;
    prev_load_valid=0;prev_load_stalled=0;prev_tile_valid=0;prev_tile_stalled=0;
    prev_desc_valid=0;prev_desc_stalled=0;
    load_hold=0;tile_hold=0;final_quiet_hold=0;
    while(!seen_done) begin
     cycles=cycles+1;if(cycles>20000)$fatal(1,"plan event timeout ev=%0d",ev);
     descriptor_valid=(ds<count);
     if(descriptor_valid) begin
      tile_ix=first+ds;raw=tile_ix*13;
      descriptor_epoch=100+ev;descriptor_index=ds;
      descriptor_input_y=geometry_mem[raw+3];descriptor_input_rows=geometry_mem[raw+4];
      descriptor_output_y=geometry_mem[raw+5];descriptor_output_rows=geometry_mem[raw+6];
      descriptor_runs=run_mem[tile_ix];descriptor_windows=window_mem[tile_ix];
     end

     load_ready=0;load_done=0;load_committed=1;load_fault=0;
     tile_ready=0;tile_done=0;tile_fault=0;
     held_load_before=prev_load_valid&&prev_load_stalled;
     held_tile_before=prev_tile_valid&&prev_tile_stalled;
     if(load_pending) begin
      load_quiet=0;
      if(load_timer>0)load_timer=load_timer-1;
      else begin load_done=1;load_epoch=100+ev;load_done_bank=load_pending_bank;load_committed=1;end
     end else load_quiet=1;
     if(tile_pending) begin
      if(tile_timer>0)tile_timer=tile_timer-1;
      else begin tile_done=1;tile_done_epoch=100+ev;tile_done_job=job_cursor+tile_pending_tile;tile_done_bank=tile_pending_bank;end
     end
     if(drain_pending) begin
      if(drain_timer>0)begin drain_timer=drain_timer-1;tile_write_quiet=0;end
      else tile_write_quiet=1;
     end else tile_write_quiet=1;
     if(drain_pending&&drain_timer==0&&tile_write_quiet&&td==count-1&&final_quiet_hold==0)
      final_quiet_hold=3;

     // Completion, quiet and descriptor signals settle before observing either
     // child VALID; this catches withdrawal caused by an opposite-port response.
     #1;
     if(descriptor_valid&&descriptor_ready&&next_descriptor!=ds)
      $fatal(1,"descriptor cursor mismatch ev=%0d local=%0d actual=%0d",ev,ds,next_descriptor);
     if(prev_load_valid&&prev_load_stalled&&!load_valid)
      $fatal(1,"held load VALID was withdrawn before acceptance");
     if(load_valid) begin
      local_ix=la;tile_ix=first+local_ix;raw=tile_ix*13;exp_load_bank=(ev[0]^(local_ix&1));
      if(epoch!=100+ev||load_job_tag!=job_cursor+local_ix||load_bank!=exp_load_bank||
         load_input_y!=geometry_mem[raw+3]||load_input_rows!=geometry_mem[raw+4])
       $fatal(1,"load payload mismatch tile=%0d",tile_ix);
      if(bank_owned[exp_load_bank])$fatal(1,"bank reused before write drain tile=%0d bank=%0d",tile_ix,exp_load_bank);
      if((tile_pending||drain_pending) &&
         ((tile_pending&&exp_load_bank==tile_pending_bank)||(drain_pending&&exp_load_bank==drain_bank)))
       $fatal(1,"loader aliases active compute/drain bank tile=%0d",tile_ix);
      if(prev_load_valid&&prev_load_stalled) begin
       if(load_bank!==prev_load_bank||load_job_tag!==prev_load_job||load_input_y!==prev_load_y||load_input_rows!==prev_load_rows)
        $fatal(1,"load payload changed under backpressure tile=%0d",tile_ix);
      end else begin
       prev_load_bank=load_bank;prev_load_job=load_job_tag;prev_load_y=load_input_y;prev_load_rows=load_input_rows;
      end
      current_load_stall=(local_ix==2)?30:(2+(local_ix%4));
      if(load_hold>=current_load_stall)load_ready=1;
      else begin load_hold=load_hold+1;held_load_cycles=held_load_cycles+1;end
      prev_load_valid=1;
     end else begin load_hold=0;prev_load_valid=0;prev_load_stalled=0;end

     if(prev_tile_valid&&prev_tile_stalled&&!tile_valid)
      $fatal(1,"held tile VALID was withdrawn before acceptance");
     if(tile_valid) begin
      if(drain_pending)$fatal(1,"next tile VALID presented before prior write drain");
      local_ix=ta;tile_ix=first+local_ix;raw=tile_ix*13;exp_tile_bank=(ev[0]^(local_ix&1));
      if(epoch!=100+ev||tile_bank!=exp_tile_bank||tile_job_tag!=job_cursor+local_ix||
         tile_token_base!=token_cursor+runs_before(first,local_ix)||
         tile_tag_base!=tag_cursor+windows_before(first,local_ix)||
         tile_input_y!=geometry_mem[raw+3]||tile_input_rows!=geometry_mem[raw+4]||
         tile_output_y!=geometry_mem[raw+5]||tile_output_rows!=geometry_mem[raw+6])
       $fatal(1,"tile payload mismatch tile=%0d",tile_ix);
      if(!bank_loaded[exp_tile_bank]||bank_tile[exp_tile_bank]!=tile_ix)
       $fatal(1,"tile issued before matching committed load tile=%0d bank=%0d",tile_ix,exp_tile_bank);
      if(prev_tile_valid&&prev_tile_stalled) begin
       if(tile_bank!==prev_tile_bank||tile_job_tag!==prev_tile_job||tile_token_base!==prev_tile_token||
          tile_tag_base!==prev_tile_tag||tile_input_y!==prev_tile_iy||tile_input_rows!==prev_tile_ir||
          tile_output_y!==prev_tile_oy||tile_output_rows!==prev_tile_orows)
        $fatal(1,"tile payload changed under backpressure tile=%0d",tile_ix);
      end else begin
       prev_tile_bank=tile_bank;prev_tile_job=tile_job_tag;prev_tile_token=tile_token_base;prev_tile_tag=tile_tag_base;
       prev_tile_iy=tile_input_y;prev_tile_ir=tile_input_rows;prev_tile_oy=tile_output_y;prev_tile_orows=tile_output_rows;
      end
      current_tile_stall=(local_ix==0)?12:(2+(local_ix%3));
      if(tile_hold>=current_tile_stall)tile_ready=1;
      else begin tile_hold=tile_hold+1;held_tile_cycles=held_tile_cycles+1;end
      prev_tile_valid=1;
     end else begin tile_hold=0;prev_tile_valid=0;prev_tile_stalled=0;end
     all_io_quiet=(!load_pending&&!tile_pending&&!load_done&&!tile_done&&load_quiet&&tile_write_quiet&&
                   !load_valid&&!tile_valid&&!descriptor_valid);
     if(final_quiet_hold>0)begin all_io_quiet=0;final_quiet_hold=final_quiet_hold-1;end
     #1;
     if(load_pending&&(tile_pending||drain_pending)) begin
      if((tile_pending&&load_pending_bank==tile_pending_bank)||(drain_pending&&load_pending_bank==drain_bank))
       $fatal(1,"active loader bank aliases compute/drain bank");
      overlap_cycles=overlap_cycles+1;
     end

     hdesc=descriptor_valid&&descriptor_ready;
     hload=load_valid&&load_ready;
     ackload=load_done;
     htile=tile_valid&&tile_ready;
     acktile=tile_done;
     if(acktile&&held_load_before&&!hload)held_load_on_tile_done=held_load_on_tile_done+1;
     if(ackload&&held_tile_before&&!htile)held_tile_on_load_done=held_tile_on_load_done+1;
     retire=drain_pending&&tile_write_quiet;
     if(load_valid&&!load_ready)prev_load_stalled=1;else if(hload)prev_load_stalled=0;
     if(tile_valid&&!tile_ready)prev_tile_stalled=1;else if(htile)prev_tile_stalled=0;
     if(descriptor_valid&&!descriptor_ready)begin
      if(prev_desc_valid&&prev_desc_stalled) begin
       if(descriptor_epoch!==prev_desc_epoch||descriptor_index!==prev_desc_index||
          descriptor_input_y!==prev_desc_iy||descriptor_input_rows!==prev_desc_ir||
          descriptor_output_y!==prev_desc_oy||descriptor_output_rows!==prev_desc_orows||
          descriptor_runs!==prev_desc_runs||descriptor_windows!==prev_desc_windows)
        $fatal(1,"descriptor changed while target bank unavailable");
      end else begin
       prev_desc_epoch=descriptor_epoch;prev_desc_index=descriptor_index;prev_desc_iy=descriptor_input_y;
       prev_desc_ir=descriptor_input_rows;prev_desc_oy=descriptor_output_y;prev_desc_orows=descriptor_output_rows;
       prev_desc_runs=descriptor_runs;prev_desc_windows=descriptor_windows;
      end
      prev_desc_stalled=1;
     end else begin prev_desc_stalled=0;end
     prev_desc_valid=descriptor_valid;

     if(hload) begin
      local_ix=la;tile_ix=first+local_ix;bank_no=load_bank;
      if(bank_owned[bank_no])$fatal(1,"load acceptance reuses owned bank tile=%0d",tile_ix);
      bank_owned[bank_no]=1;bank_loaded[bank_no]=0;bank_tile[bank_no]=tile_ix;
      load_pending=1;load_pending_tile=local_ix;load_pending_bank=bank_no;load_timer=4+(local_ix%3);
      la=la+1;load_hold=0;prev_load_valid=1;
     end
     if(ackload) begin
      if(!load_pending||!load_committed||load_epoch!=100+ev||load_done_bank!=load_pending_bank)
       $fatal(1,"unexpected synthetic load response");
      bank_loaded[load_pending_bank]=1;bank_tile[load_pending_bank]=first+load_pending_tile;
      load_pending=0;load_pending_tile=-1;load_pending_bank=-1;lc=lc+1;
     end
     if(htile) begin
      local_ix=ta;bank_no=tile_bank;
      if(!bank_owned[bank_no]||!bank_loaded[bank_no]||bank_tile[bank_no]!=first+local_ix)
       $fatal(1,"tile handshake without bank residency");
      if(tile_pending||drain_pending)$fatal(1,"single tile engine accepted overlapping compute");
      tile_pending=1;tile_pending_tile=local_ix;tile_pending_bank=bank_no;tile_timer=15+(local_ix%4);
      ta=ta+1;tile_hold=0;prev_tile_valid=1;
     end
     if(acktile) begin
      if(!tile_pending||tile_done_epoch!=100+ev||tile_done_job!=job_cursor+tile_pending_tile||tile_done_bank!=tile_pending_bank)
       $fatal(1,"unexpected synthetic tile response");
      tile_pending=0;drain_pending=1;drain_timer=4+(tile_pending_tile%3);
      drain_tile=tile_pending_tile;drain_bank=tile_pending_bank;tile_pending_tile=-1;tile_pending_bank=-1;tc=tc+1;
     end
     if(retire) begin
      if(!bank_owned[drain_bank]||!bank_loaded[drain_bank]||bank_tile[drain_bank]!=first+drain_tile)
       $fatal(1,"write drain released wrong bank");
      bank_owned[drain_bank]=0;bank_loaded[drain_bank]=0;bank_tile[drain_bank]=-1;
      drain_pending=0;td=td+1;
     end
     if(hdesc)ds=ds+1;
     step;
     if(acktile&&held_load_before&&!hload&&
        (!load_valid||load_bank!==prev_load_bank||load_job_tag!==prev_load_job||
         load_input_y!==prev_load_y||load_input_rows!==prev_load_rows))
      $fatal(1,"held load VALID/payload changed on opposite tile completion");
     if(ackload&&held_tile_before&&!htile&&
        (!tile_valid||tile_bank!==prev_tile_bank||tile_job_tag!==prev_tile_job||
         tile_token_base!==prev_tile_token||tile_tag_base!==prev_tile_tag||
         tile_input_y!==prev_tile_iy||tile_input_rows!==prev_tile_ir||
         tile_output_y!==prev_tile_oy||tile_output_rows!==prev_tile_orows))
      $fatal(1,"held tile VALID/payload changed on opposite load completion");
     if(fault)$fatal(1,"C plan event fault=%0d event=%0d",fault_code,eid);
     if(done) begin
      if(ds!=count||la!=count||lc!=count||ta!=count||tc!=count||td!=count||
         committed_tiles!=count||!all_io_quiet||load_pending||tile_pending||drain_pending)
       $fatal(1,"done before all C-plan work drained event=%0d",eid);
      seen_done=1;events_seen=events_seen+1;tiles_seen=tiles_seen+count;
     end else if(td==count&&final_quiet_hold==0&&all_io_quiet)
      $fatal(1,"missing done pulse after event drain");
    end
    if(done) begin step;if(done)$fatal(1,"done was not a pulse");end
    token_cursor=token_cursor+runs_before(first,count);
    tag_cursor=tag_cursor+windows_before(first,count);
    job_cursor=job_cursor+count;
   end
   if(events_seen!=63||tiles_seen!=189||initial_bank_mask!=3||overlap_cycles==0||held_load_cycles==0||held_tile_cycles==0||
      held_load_on_tile_done==0||held_tile_on_load_done==0)
    $fatal(1,"positive plan coverage missing events=%0d tiles=%0d overlap=%0d",events_seen,tiles_seen,overlap_cycles);
  end
 endtask

 task one_good_prefix;
  input[31:0] ep,job,token,tag;
  begin
   cmd_epoch=ep;cmd_job_base=job;cmd_token_base=token;cmd_tag_base=tag;cmd_tiles=1;cmd_output_height=20;cmd_first_bank=0;
   start_command;
   set_one_descriptor(ep,0,0,40,0,20,16,144);
  end
 endtask

 task one_good_loaded;
  input[31:0] ep,job,token,tag;
  begin one_good_prefix(ep,job,token,tag);accept_one_load;complete_one_load(ep,0,1);end
 endtask

 task test_negative_cases;
  integer timeout,b;
  reg[31:0] replay_epoch,replay_job;
  begin
   // Unsolicited load and tile completions are both fatal while idle.
   reset_case;load_done=1;step;load_done=0;expect_fault;negative_cases=negative_cases+1;
   reset_case;tile_done=1;step;tile_done=0;expect_fault;negative_cases=negative_cases+1;

   // Invalid event allocations and ledger range overflow.
   reset_case;cmd_tiles=0;start_command;expect_fault;negative_cases=negative_cases+1;
   reset_case;cmd_job_base=32'hffffffff;cmd_tiles=2;cmd_output_height=40;start_command;expect_fault;negative_cases=negative_cases+1;
   reset_case;cmd_tiles=190;start_command;expect_fault;negative_cases=negative_cases+1;

   // Whole-event graph ownership remains leased/reserved until completion.
   reset_case;one_good_prefix(1,10,1,1);source_leased=0;step;expect_fault;negative_cases=negative_cases+1;
   reset_case;one_good_prefix(1,10,1,1);destination_reserved=0;step;expect_fault;negative_cases=negative_cases+1;

   // Sequential descriptor identity, contiguous output rows, halo bounds,
   // counts and token/tag allocation boundaries are checked independently.
   reset_case;cmd_epoch=1;cmd_job_base=10;cmd_tiles=1;cmd_output_height=20;start_command;
   set_one_descriptor(2,0,0,40,0,20,16,144);expect_fault;negative_cases=negative_cases+1;
   // A second tile makes descriptor index 1 the only valid next index.
   reset_case;cmd_tiles=2;cmd_output_height=40;start_command;
   set_one_descriptor(1,0,0,40,0,20,16,144);
   set_one_descriptor(1,2,39,41,20,20,16,144);expect_fault;negative_cases=negative_cases+1;
   reset_case;start_command;descriptor_valid=1;descriptor_epoch=1;descriptor_index=0;descriptor_input_y=0;descriptor_input_rows=40;
   descriptor_output_y=1;descriptor_output_rows=20;descriptor_runs=16;descriptor_windows=144;step;descriptor_valid=0;
   expect_fault;negative_cases=negative_cases+1;
   reset_case;start_command;descriptor_valid=1;descriptor_epoch=1;descriptor_index=0;descriptor_input_y=0;descriptor_input_rows=40;
   descriptor_output_y=0;descriptor_output_rows=19;descriptor_runs=16;descriptor_windows=144;step;descriptor_valid=0;
   expect_fault;negative_cases=negative_cases+1;
   reset_case;start_command;descriptor_valid=1;descriptor_epoch=1;descriptor_index=0;descriptor_input_y=639;descriptor_input_rows=2;
   descriptor_output_y=0;descriptor_output_rows=20;descriptor_runs=16;descriptor_windows=144;step;descriptor_valid=0;
   expect_fault;negative_cases=negative_cases+1;
   reset_case;start_command;descriptor_valid=1;descriptor_epoch=1;descriptor_index=0;descriptor_input_y=0;descriptor_input_rows=40;
   descriptor_output_y=0;descriptor_output_rows=20;descriptor_runs=0;descriptor_windows=144;step;descriptor_valid=0;
   expect_fault;negative_cases=negative_cases+1;
   reset_case;start_command;descriptor_valid=1;descriptor_epoch=1;descriptor_index=0;descriptor_input_y=0;descriptor_input_rows=40;
   descriptor_output_y=0;descriptor_output_rows=20;descriptor_runs=16;descriptor_windows=15;step;descriptor_valid=0;
   expect_fault;negative_cases=negative_cases+1;
   reset_case;cmd_token_base=32'hfffffff1;start_command;descriptor_valid=1;descriptor_epoch=1;descriptor_index=0;
   descriptor_input_y=0;descriptor_input_rows=40;descriptor_output_y=0;descriptor_output_rows=20;descriptor_runs=16;descriptor_windows=144;
   step;descriptor_valid=0;expect_fault;negative_cases=negative_cases+1;
   reset_case;cmd_tag_base=32'hffffff80;start_command;descriptor_valid=1;descriptor_epoch=1;descriptor_index=0;
   descriptor_input_y=0;descriptor_input_rows=40;descriptor_output_y=0;descriptor_output_rows=20;descriptor_runs=16;descriptor_windows=144;
   step;descriptor_valid=0;expect_fault;negative_cases=negative_cases+1;

   // Delayed load completion must match the accepted bank, epoch and commit.
   reset_case;one_good_prefix(1,10,1,1);accept_one_load;complete_one_load(2,0,1);expect_fault;negative_cases=negative_cases+1;
   reset_case;one_good_prefix(1,10,1,1);accept_one_load;complete_one_load(1,1,1);expect_fault;negative_cases=negative_cases+1;
   reset_case;one_good_prefix(1,10,1,1);accept_one_load;complete_one_load(1,0,0);expect_fault;negative_cases=negative_cases+1;
   reset_case;one_good_prefix(1,10,1,1);accept_one_load;load_fault=1;step;load_fault=0;expect_fault;negative_cases=negative_cases+1;

   // Tile completion is tied to the launched epoch, job and physical bank.
   reset_case;one_good_loaded(1,10,1,1);accept_one_tile;complete_one_tile(2,10,0);expect_fault;negative_cases=negative_cases+1;
   reset_case;one_good_loaded(1,10,1,1);accept_one_tile;complete_one_tile(1,11,0);expect_fault;negative_cases=negative_cases+1;
   reset_case;one_good_loaded(1,10,1,1);accept_one_tile;complete_one_tile(1,10,1);expect_fault;negative_cases=negative_cases+1;
   reset_case;one_good_loaded(1,10,1,1);accept_one_tile;tile_fault=1;step;tile_fault=0;expect_fault;negative_cases=negative_cases+1;

   // Cancellation is injected after load 1 is accepted while tile 0 computes.
   reset_case;cmd_epoch=1;cmd_job_base=100;cmd_token_base=1;cmd_tag_base=1;cmd_tiles=2;cmd_output_height=40;
   cmd_first_bank=0;start_command;
   set_one_descriptor(1,0,0,40,0,20,16,144);accept_one_load;complete_one_load(1,0,1);accept_one_tile;
   descriptor_epoch=1;descriptor_index=1;descriptor_input_y=39;descriptor_input_rows=41;
   descriptor_output_y=20;descriptor_output_rows=20;descriptor_runs=16;descriptor_windows=144;descriptor_valid=1;
   timeout=0;while(!descriptor_ready&&timeout<50)begin step;timeout=timeout+1;end
   if(!descriptor_ready)$fatal(1,"second descriptor blocked while bank 1 free");step;descriptor_valid=0;
   timeout=0;while(!load_valid&&timeout<50)begin step;timeout=timeout+1;end
   if(!load_valid||load_bank!=1)$fatal(1,"missing real load/compute overlap for cancel case");
   load_ready=1;load_quiet=0;all_io_quiet=0;step;load_ready=0;overlap_cycles=overlap_cycles+1;
   cancel=1;step;cancel=0;expect_fault;negative_cases=negative_cases+1;

   // Recover only with the complete drained-and-quiet handshake and no
   // cancel/fault/completion pulse. Then replaying the same event is rejected.
   reset_case;replay_epoch=77;replay_job=500;one_good_prefix(replay_epoch,replay_job,7,9);
   load_fault=1;step;load_fault=0;expect_fault;
   recovery_drained=0;load_quiet=1;tile_write_quiet=1;all_io_quiet=1;recover=1;step;recover=0;
   if(!fault)$fatal(1,"recovered without recovery_drained");recovery_blocks=recovery_blocks+1;
   recovery_drained=1;load_quiet=0;recover=1;step;recover=0;load_quiet=1;
   if(!fault)$fatal(1,"recovered while load path not quiet");recovery_blocks=recovery_blocks+1;
   tile_write_quiet=0;recover=1;step;recover=0;tile_write_quiet=1;
   if(!fault)$fatal(1,"recovered while tile-write path not quiet");recovery_blocks=recovery_blocks+1;
   all_io_quiet=0;recover=1;step;recover=0;all_io_quiet=1;
   if(!fault)$fatal(1,"recovered while all I/O not quiet");recovery_blocks=recovery_blocks+1;
   cancel=1;recover=1;step;recover=0;cancel=0;
   if(!fault)$fatal(1,"recovered while cancel asserted");recovery_blocks=recovery_blocks+1;
   load_fault=1;recover=1;step;recover=0;load_fault=0;
   if(!fault)$fatal(1,"recovered with load fault pulse");recovery_blocks=recovery_blocks+1;
   tile_fault=1;recover=1;step;recover=0;tile_fault=0;
   if(!fault)$fatal(1,"recovered with tile fault pulse");recovery_blocks=recovery_blocks+1;
   load_done=1;recover=1;step;recover=0;load_done=0;
   if(!fault)$fatal(1,"recovered with load completion pulse");recovery_blocks=recovery_blocks+1;
   tile_done=1;recover=1;step;recover=0;tile_done=0;
   if(!fault)$fatal(1,"recovered with tile completion pulse");recovery_blocks=recovery_blocks+1;
   recovery_drained=1;load_quiet=1;tile_write_quiet=1;all_io_quiet=1;
   recover=1;step;recover=0;
   if(fault||!cmd_ready)$fatal(1,"safe recovery did not return idle");
   cmd_epoch=replay_epoch;cmd_job_base=replay_job;cmd_token_base=7;cmd_tag_base=9;cmd_tiles=1;cmd_output_height=20;cmd_first_bank=0;
   start_command;expect_fault;negative_cases=negative_cases+1;
  end
 endtask

 initial begin
  $readmemh("prefetch_geometry.hex",geometry_mem);
  $readmemh("prefetch_events.hex",event_mem);
  $readmemh("prefetch_runs.hex",run_mem);
  $readmemh("prefetch_windows.hex",window_mem);
  total_run_check=0;total_window_check=0;
  for(i=0;i<189;i=i+1)begin total_run_check=total_run_check+run_mem[i];total_window_check=total_window_check+window_mem[i];end
  if(total_run_check!=26380||total_window_check!=1659840)$fatal(1,"C-plan run/window totals mismatch");
  reset_case;
  run_c_plan;
  reset_case;
  test_negative_cases;
  if(events_seen!=63||tiles_seen!=189||negative_cases!=26||recovery_blocks!=9||overlap_cycles==0||
     held_load_cycles==0||held_tile_cycles==0||held_load_on_tile_done==0||held_tile_on_load_done==0)
   $fatal(1,"coverage marker mismatch events=%0d tiles=%0d negative=%0d recovery=%0d overlap=%0d",
          events_seen,tiles_seen,negative_cases,recovery_blocks,overlap_cycles);
  $display("CONV_PREFETCH_CONTROL_PASS events=%0d tiles=%0d negative_cases=%0d recovery_blocks=%0d overlap_cycles=%0d held_load_cycles=%0d held_tile_cycles=%0d held_load_on_tile_done=%0d held_tile_on_load_done=%0d runs=%0d windows=%0d",
           events_seen,tiles_seen,negative_cases,recovery_blocks,overlap_cycles,held_load_cycles,held_tile_cycles,
           held_load_on_tile_done,held_tile_on_load_done,total_run_check,total_window_check);
  $finish;
 end
 initial begin #50000000;$fatal(1,"watchdog");end
endmodule
`default_nettype wire
