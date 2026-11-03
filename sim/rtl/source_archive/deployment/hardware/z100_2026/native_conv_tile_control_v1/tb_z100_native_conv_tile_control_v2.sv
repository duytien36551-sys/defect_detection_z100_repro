`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_conv_tile_control_v2;
reg clk=0;always #5 clk=~clk;reg rst_n=0,cancel=0,recover=0,recovery_drained=0;
reg cmd_valid=0;wire cmd_ready;
reg[31:0] cmd_epoch=200,cmd_token_base=1000,cmd_tag_base=100000,cmd_job_tag=0;
integer job_counter=0;wire[31:0] job_tag;reg[31:0] expected_job=0,parameter_done_job_tag=0,row_done_job_tag=0;
reg[15:0] cmd_parameter_first=0;
reg[10:0] cmd_input_channels=0,cmd_output_channels=0;
reg[9:0] cmd_input_height=0,cmd_input_width=0,cmd_input_y=0,cmd_input_rows=0;
reg[9:0] cmd_output_height=0,cmd_output_width=0,cmd_output_y=0,cmd_output_rows=0;
reg[1:0] cmd_kernel=0,cmd_stride=0,cmd_padding=0;
wire pack_valid,parameter_valid,row_valid,parameter_done_ready,row_done_ready,publish_ready;
reg pack_ready=0,parameter_ready=0,row_ready=0;
wire[31:0] epoch,pack_token_base,row_token_base,row_tag_base;
wire[10:0] pack_channels,row_channels;wire[9:0] pack_height,pack_width,row_input_width,row_output_width;
wire[15:0] parameter_job;wire[1:0] row_kernel,row_stride,row_padding;
wire[5:0] row_lanes;wire[13:0] row_bank_words,row_plane_stride;wire[41:0] row_ky_bases;wire[2:0] row_y_valid;
reg parameter_done_valid=0,row_done_valid=0,publish_valid=0;
reg[31:0] parameter_done_epoch=200,row_done_epoch=200,row_done_last_token=0,publish_epoch=200,publish_tag=100000;
reg[15:0] parameter_done_job=0;reg parameter_done_error=0,row_done_error=0,publish_error=0;
wire child_cancel,active,needs_drain,done,fault;wire[3:0] fault_code;
z100_native_conv_tile_control_v2 dut(.*);
reg[63:0] geometry[0:2456]; //189*13
reg[63:0] expected[0:86639]; //7220*12, actual C execution output
reg[15:0] parameter_first[0:188];
integer tile,g,row,index=0,rows_seen=0,parameters_seen=0,packs_seen=0,published=0;
integer held=0,negative=0,recovery_blocks=0,drain_waits=0;
reg[511:0] held_row;reg[95:0] held_pack;reg[47:0] held_parameter;
wire[511:0] row_snapshot={epoch,row_token_base,row_tag_base,row_channels,row_input_width,row_output_width,row_kernel,row_stride,row_padding,row_lanes,row_bank_words,row_plane_stride,row_ky_bases,row_y_valid};
task tick;begin @(posedge clk);#1;end endtask
task set_geometry(input integer t);begin
 cmd_input_channels=geometry[t*13];cmd_input_height=geometry[t*13+1];cmd_input_width=geometry[t*13+2];
 cmd_input_y=geometry[t*13+3];cmd_input_rows=geometry[t*13+4];cmd_output_y=geometry[t*13+5];cmd_output_rows=geometry[t*13+6];
 cmd_output_height=geometry[t*13+7];cmd_output_width=geometry[t*13+8];cmd_output_channels=geometry[t*13+9];
 cmd_kernel=geometry[t*13+10];cmd_stride=geometry[t*13+11];cmd_padding=geometry[t*13+12];
 job_counter=job_counter+1;cmd_job_tag=job_counter;
 cmd_parameter_first=parameter_first[t];cmd_epoch=200;cmd_token_base=1000;cmd_tag_base=100000;
end endtask
task submit;begin
 @(negedge clk);expected_job=cmd_job_tag;publish_tag=expected_job;parameter_done_job_tag=expected_job;row_done_job_tag=expected_job;cmd_valid=1;#1;if(!cmd_ready)$fatal(1,"Tile command not ready");tick();@(negedge clk);cmd_valid=0;
end endtask
task accept_pack(input integer t);begin
 while(!pack_valid)begin tick();if(fault)$fatal(1,"Valid graph tile rejected %d code=%d",t,fault_code);end
 held_pack={epoch,pack_token_base,pack_channels,pack_height,pack_width};
 repeat(3)begin tick();if(!pack_valid||{epoch,pack_token_base,pack_channels,pack_height,pack_width}!==held_pack)$fatal(1,"Pack config changed under stall");held=held+1;end
 if(job_tag!=expected_job||epoch!=200||pack_token_base!=1000||pack_channels!=geometry[t*13+9]||pack_height!=geometry[t*13+6]||pack_width!=geometry[t*13+8])$fatal(1,"Tile pack geometry identity");
 @(negedge clk);pack_ready=1;tick();@(negedge clk);pack_ready=0;packs_seen=packs_seen+1;
end endtask
task accept_parameter(input integer t,input integer group_id);begin
 while(!parameter_valid)begin tick();if(fault)$fatal(1,"Parameter request fault");end
 held_parameter={epoch,parameter_job};
 repeat(3)begin tick();if(!parameter_valid||{epoch,parameter_job}!==held_parameter)$fatal(1,"Parameter request changed under stall");held=held+1;end
 if(parameter_job!=parameter_first[t]+group_id||epoch!=200)$fatal(1,"Parameter group identity/order");
 parameter_done_job=parameter_first[t]+group_id;
 @(negedge clk);parameter_ready=1;tick();@(negedge clk);parameter_ready=0;
 repeat(2)tick();@(negedge clk);parameter_done_valid=1;
 #1;if(!parameter_done_ready)$fatal(1,"Parameter completion not owned");tick();@(negedge clk);parameter_done_valid=0;parameters_seen=parameters_seen+1;
end endtask
task check_and_accept_row(input integer expected_index,input integer t,input integer group_id,input integer local_row);integer n;begin
 while(!row_valid)begin tick();if(fault)$fatal(1,"Row request fault");end
 held_row=row_snapshot;
 repeat(3)begin tick();if(!row_valid||row_snapshot!==held_row)$fatal(1,"Row payload changed under stall");held=held+1;end
 n=expected_index*12;
 if(expected[n]!=t||expected[n+1]!=group_id||expected[n+2]!=local_row||epoch!=200||
    row_token_base!=expected[n+3]||row_tag_base!=expected[n+4]||row_channels!=expected[n+5]||
    row_bank_words!=expected[n+6]||row_plane_stride!=expected[n+7]||row_lanes!=expected[n+8]||
    row_ky_bases!=expected[n+9]||row_y_valid!=expected[n+10]||row_output_width!=expected[n+11]||
    row_input_width!=geometry[t*13+2]||row_kernel!=geometry[t*13+10]||row_stride!=geometry[t*13+11]||row_padding!=geometry[t*13+12])
    $fatal(1,"Hardware tile row differs from executed C oracle index=%d tile=%d group=%d row=%d token=%d tag=%d bases=%h mask=%b",expected_index,t,group_id,local_row,row_token_base,row_tag_base,row_ky_bases,row_y_valid);
 row_done_last_token=expected[n+3]+(geometry[t*13+8]+19)/20-1;
 @(negedge clk);row_ready=1;tick();@(negedge clk);row_ready=0;
 repeat(2)tick();@(negedge clk);row_done_valid=1;
 #1;if(!row_done_ready)$fatal(1,"Row completion not owned");tick();@(negedge clk);row_done_valid=0;rows_seen=rows_seen+1;
end endtask
task await_publication;begin
 while(!publish_ready)begin tick();if(fault)$fatal(1,"Tile did not reach publication wait");end
 repeat(7)begin tick();if(done||cmd_ready||!active||!publish_ready)$fatal(1,"Tile completed before actual DDR publication");drain_waits=drain_waits+1;end
end endtask
task clear_owned_fault;begin
 if(!fault||!needs_drain||!child_cancel||cmd_ready||done)$fatal(1,"Fault did not retain recovery ownership");
 @(negedge clk);recover=1;recovery_drained=0;
 repeat(4)begin tick();if(!fault||!child_cancel||cmd_ready)$fatal(1,"Premature recovery without drained IO");recovery_blocks=recovery_blocks+1;end
 @(negedge clk);recovery_drained=1;tick();@(negedge clk);recover=0;recovery_drained=0;
 if(fault||!cmd_ready||child_cancel||needs_drain)$fatal(1,"Qualified recovery failed");negative=negative+1;
end endtask
integer bad;
initial begin
 $readmemh("geometry.hex",geometry);$readmemh("expected_rows.hex",expected);$readmemh("parameter_first.hex",parameter_first);
 repeat(5)tick();@(negedge clk);rst_n=1;
 for(tile=0;tile<189;tile=tile+1)begin
  set_geometry(tile);submit();
  // Change command pins after capture: no output may use an unlatched field.
  cmd_epoch=999;cmd_job_tag=0;cmd_token_base=1;cmd_input_width=1;cmd_output_rows=1;
  accept_pack(tile);
  for(g=0;g<(geometry[tile*13+9]+31)/32;g=g+1)begin
   accept_parameter(tile,g);
   for(row=0;row<geometry[tile*13+6];row=row+1)begin check_and_accept_row(index,tile,g,row);index=index+1;end
  end
  await_publication();@(negedge clk);publish_valid=1;tick();@(negedge clk);publish_valid=0;
  if(!done||fault||active||!cmd_ready)$fatal(1,"Successful publication did not complete tile");published=published+1;
 end
 if(index!=7220||rows_seen!=7220||packs_seen!=189||published!=189)$fatal(1,"Whole graph tile/row metadata coverage");
 // Admission errors must perform no pack/parameter/row work.
 for(bad=0;bad<7;bad=bad+1)begin
  set_geometry(0);
  case(bad)0:cmd_epoch=0;1:cmd_token_base=0;2:cmd_input_rows=1;3:cmd_token_base=32'hffffffff;4:cmd_tag_base=32'hffffffff;5:cmd_job_tag=0;6:cmd_job_tag=1;endcase
  submit();if(!fault||fault_code!=1||pack_valid||parameter_valid||row_valid)$fatal(1,"Bad tile admission accepted");clear_owned_fault();
 end
 // Unexpected completion, cancellation, wrong parameter identity, wrong row
 // token, and failed publication each require explicit drained recovery.
 @(negedge clk);row_done_valid=1;tick();@(negedge clk);row_done_valid=0;if(fault_code!=3)$fatal(1,"Unsolicited row completion");clear_owned_fault();
 set_geometry(0);submit();@(negedge clk);cancel=1;tick();@(negedge clk);cancel=0;if(fault_code!=2)$fatal(1,"Cancel not retained");clear_owned_fault();
 set_geometry(0);submit();accept_pack(0);
 while(!parameter_valid)tick();parameter_done_job=65535;parameter_done_job_tag=expected_job-1;
 @(negedge clk);parameter_ready=1;tick();@(negedge clk);parameter_ready=0;parameter_done_valid=1;tick();@(negedge clk);parameter_done_valid=0;
 if(fault_code!=4)$fatal(1,"Wrong parameter identity accepted");clear_owned_fault();
 set_geometry(0);submit();accept_pack(0);accept_parameter(0,0);
 while(!row_valid)tick();row_done_last_token=0;
 @(negedge clk);row_ready=1;tick();@(negedge clk);row_ready=0;row_done_valid=1;tick();@(negedge clk);row_done_valid=0;
 if(fault_code!=5)$fatal(1,"Wrong row token accepted");clear_owned_fault();
 set_geometry(0);submit();accept_pack(0);accept_parameter(0,0);
 for(row=0;row<geometry[6];row=row+1)check_and_accept_row(row,0,0,row);
 await_publication();@(negedge clk);publish_error=1;publish_valid=1;tick();@(negedge clk);publish_valid=0;publish_error=0;
 if(fault_code!=6||done)$fatal(1,"Failed write publication accepted");clear_owned_fault();
 if(negative!=12||recovery_blocks!=48||held<23000||drain_waits!=1330)$fatal(1,"Negative/hold/drain coverage");
 $display("CONV_TILE_CONTROL_PASS graph_tiles=189 graph_rows=7220 graph_publications=189 graph_pack_configs=189 negative_cases=12 recovery_blocks=48 held_cycles=%0d publication_wait_cycles=%0d parameter_requests=%0d",held,drain_waits,parameters_seen);
 $finish;
end
initial begin #20000000;$fatal(1,"Tile control watchdog");end
endmodule
`default_nettype wire
