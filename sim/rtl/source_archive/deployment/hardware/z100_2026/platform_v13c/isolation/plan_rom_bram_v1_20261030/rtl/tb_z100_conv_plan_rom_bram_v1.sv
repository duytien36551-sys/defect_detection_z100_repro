`timescale 1ns/1ps
`default_nettype none
module tb_z100_conv_plan_rom_bram_v1;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,cancel=0,request_valid=0,result_ready=0;
 wire request_ready_ref,request_ready_cand,result_valid_ref,result_valid_cand;
 reg[31:0] request_epoch=1,request_tag=1,request_model_crc=2213989717;
 reg[7:0] request_event=1,request_tile=0;
 wire[31:0] result_epoch_ref,result_tag_ref,result_runs_ref,result_windows_ref;
 wire[7:0] result_event_ref,result_tile_ref,result_tile_count_ref;
 wire[15:0] result_parameter_first_ref;wire[207:0] result_geometry_ref;
 wire result_error_ref;
 wire[31:0] result_epoch_cand,result_tag_cand,result_runs_cand,result_windows_cand;
 wire[7:0] result_event_cand,result_tile_cand,result_tile_count_cand;
 wire[15:0] result_parameter_first_cand;wire[207:0] result_geometry_cand;
 wire result_error_cand;

 z100_conv_plan_rom #(.MAP_FILE("conv_event_map.hex"),.TILE_FILE("conv_tiles.hex")) u_ref (
  .clk(clk),.rst_n(rst_n),.cancel(cancel),.request_valid(request_valid),.request_ready(request_ready_ref),
  .request_epoch(request_epoch),.request_tag(request_tag),.request_model_crc(request_model_crc),
  .request_event(request_event),.request_tile(request_tile),.result_valid(result_valid_ref),
  .result_ready(result_ready),.result_epoch(result_epoch_ref),.result_tag(result_tag_ref),
  .result_event(result_event_ref),.result_tile(result_tile_ref),.result_error(result_error_ref),
  .result_geometry(result_geometry_ref),.result_parameter_first(result_parameter_first_ref),
  .result_tile_count(result_tile_count_ref),.result_runs(result_runs_ref),.result_windows(result_windows_ref));
 z100_conv_plan_rom_bram_v1 #(.MAP_FILE("conv_event_map.hex"),.TILE_FILE("conv_tiles.hex")) u_cand (
  .clk(clk),.rst_n(rst_n),.cancel(cancel),.request_valid(request_valid),.request_ready(request_ready_cand),
  .request_epoch(request_epoch),.request_tag(request_tag),.request_model_crc(request_model_crc),
  .request_event(request_event),.request_tile(request_tile),.result_valid(result_valid_cand),
  .result_ready(result_ready),.result_epoch(result_epoch_cand),.result_tag(result_tag_cand),
  .result_event(result_event_cand),.result_tile(result_tile_cand),.result_error(result_error_cand),
  .result_geometry(result_geometry_cand),.result_parameter_first(result_parameter_first_cand),
  .result_tile_count(result_tile_count_cand),.result_runs(result_runs_cand),.result_windows(result_windows_cand));

 reg[31:0] expected[0:3212];
 wire[378:0] snapshot_ref={request_ready_ref,result_valid_ref,result_epoch_ref,result_tag_ref,
  result_event_ref,result_tile_ref,result_error_ref,result_geometry_ref,result_parameter_first_ref,
  result_tile_count_ref,result_runs_ref,result_windows_ref};
 wire[378:0] snapshot_cand={request_ready_cand,result_valid_cand,result_epoch_cand,result_tag_cand,
  result_event_cand,result_tile_cand,result_error_cand,result_geometry_cand,result_parameter_first_cand,
  result_tile_count_cand,result_runs_cand,result_windows_cand};
 reg[378:0] held_snapshot;
 reg[319:0] saved_record;
 integer i,j,held=0,negative_cases=0,cancel_cases=0,back_to_back_replacements=0;
 integer reset_request_collisions=0,cancel_request_collisions=0;
 integer expected_runs,expected_windows;

 task compare_outputs;
  begin if(snapshot_ref!==snapshot_cand)$fatal(1,"baseline/candidate cycle mismatch ref=%h cand=%h",snapshot_ref,snapshot_cand);end
 endtask
 task step;
  begin @(posedge clk);#1;compare_outputs;@(negedge clk);end
 endtask
 task submit;
  begin
   request_valid=1;#1;if(!request_ready_ref||!request_ready_cand)$fatal(1,"ROM admission unavailable");step;request_valid=0;
   if(!result_valid_ref||!result_valid_cand||result_epoch_ref!=request_epoch||result_tag_ref!=request_tag||
      result_event_ref!=request_event||result_tile_ref!=request_tile)$fatal(1,"ROM result identity/latency");
   held_snapshot=snapshot_ref;
   repeat(3)begin
    request_valid=1;request_tag=request_tag+1;#1;
    if(request_ready_ref||request_ready_cand)$fatal(1,"Accepted over held ROM result");
    step;if(!result_valid_ref||snapshot_ref!==held_snapshot)$fatal(1,"Held ROM payload changed");held=held+1;
   end
   request_valid=0;
  end
 endtask
 task consume;
  begin result_ready=1;step;result_ready=0;#1;if(result_valid_ref||result_valid_cand)$fatal(1,"ROM result did not retire");end
 endtask
 task invalid;
  begin
   submit;
   if(!result_error_ref||result_geometry_ref!=0||result_parameter_first_ref!=0||result_tile_count_ref!=0||
      result_runs_ref!=0||result_windows_ref!=0)$fatal(1,"Invalid plan leaked usable metadata");
   negative_cases=negative_cases+1;consume;
  end
 endtask
 task issue_tile;
  input integer idx;
  input[31:0] tag_value;
  input integer replace_current;
  begin
   request_valid=1;result_ready=(replace_current!=0);request_epoch=1;request_tag=tag_value;
   request_event=expected[idx*17+13][7:0];request_tile=expected[idx*17+14][7:0];#1;
   if(!request_ready_ref||!request_ready_cand)$fatal(1,"Back-to-back request was not admitted idx=%0d",idx);
   step;request_valid=0;result_ready=0;#1;
   if(!result_valid_ref||result_epoch_ref!=request_epoch||result_tag_ref!=tag_value||
      result_event_ref!=request_event||result_tile_ref!=request_tile||result_error_ref)
    $fatal(1,"Back-to-back request response mismatch idx=%0d",idx);
   if(result_tile_count_ref!=expected[idx*17+15]||result_parameter_first_ref!=expected[idx*17+16])
    $fatal(1,"Back-to-back binding mismatch idx=%0d",idx);
   for(j=0;j<13;j=j+1)if(result_geometry_ref[j*16+:16]!==expected[idx*17+j][15:0])
    $fatal(1,"Back-to-back geometry mismatch idx=%0d field=%0d",idx,j);
   expected_runs=((expected[idx*17+9]+31)/32)*expected[idx*17+6]*((expected[idx*17+8]+19)/20);
   expected_windows=expected_runs*((expected[idx*17]+3)/4)*expected[idx*17+10]*expected[idx*17+10];
   if(result_runs_ref!=expected_runs||result_windows_ref!=expected_windows)$fatal(1,"Back-to-back budget mismatch idx=%0d",idx);
  end
 endtask

 initial begin
  $readmemh("expected_plan.hex",expected);
  repeat(3)step;rst_n=1;step;
  for(i=0;i<189;i=i+1)begin
   request_epoch=1;request_tag=1000+i;request_event=expected[i*17+13][7:0];request_tile=expected[i*17+14][7:0];submit;
   if(result_error_ref||result_tile_count_ref!=expected[i*17+15]||result_parameter_first_ref!=expected[i*17+16])
    $fatal(1,"ROM C binding tile=%0d",i);
   for(j=0;j<13;j=j+1)if(result_geometry_ref[j*16+:16]!==expected[i*17+j][15:0])
    $fatal(1,"ROM C geometry tile=%0d field=%0d",i,j);
   expected_runs=((expected[i*17+9]+31)/32)*expected[i*17+6]*((expected[i*17+8]+19)/20);
   expected_windows=expected_runs*((expected[i*17]+3)/4)*expected[i*17+10]*expected[i*17+10];
   if(result_runs_ref!=expected_runs||result_windows_ref!=expected_windows)$fatal(1,"ROM budget tile=%0d",i);
   consume;
  end
  // Replace a live response on every edge while changing event, tile and tag.
  issue_tile(0,32'd7001,0);
  issue_tile(16,32'd7002,1);
  issue_tile(17,32'd7003,1);back_to_back_replacements=2;consume;
  request_event=1;request_tile=0;request_epoch=0;invalid;request_epoch=1;
  request_tag=0;invalid;request_tag=1;
  request_model_crc=0;invalid;request_model_crc=2213989717;
  request_event=0;invalid;request_event=255;invalid;request_event=200;invalid;request_event=1;
  request_tile=16;invalid;request_tile=255;invalid;request_tile=0;
  saved_record=u_ref.tile_rom[0];
  u_ref.tile_rom[0]=saved_record^(320'd1<<312);u_cand.tile_rom[0]=saved_record^(320'd1<<312);invalid;
  u_ref.tile_rom[0]=saved_record^(320'd1<<304);u_cand.tile_rom[0]=saved_record^(320'd1<<304);invalid;
  u_ref.tile_rom[0]=saved_record^(320'd1<<296);u_cand.tile_rom[0]=saved_record^(320'd1<<296);invalid;
  u_ref.tile_rom[0]=saved_record^(320'd1<<288);u_cand.tile_rom[0]=saved_record^(320'd1<<288);invalid;
  u_ref.tile_rom[0]=saved_record;u_cand.tile_rom[0]=saved_record;
  // A synchronous reset wins over a simultaneous new request and clears all
  // public state while the candidate's unreset memory output stays masked.
  issue_tile(16,32'd7100,0);request_valid=1;result_ready=1;rst_n=0;step;
  request_valid=0;result_ready=0;rst_n=1;step;
  if(result_valid_ref||result_error_ref||result_geometry_ref!=0||result_parameter_first_ref!=0||
     result_tile_count_ref!=0||result_runs_ref!=0||result_windows_ref!=0)
   $fatal(1,"Reset/request collision did not clear observable state");
  reset_request_collisions=1;
  submit;
  // Cancel likewise wins over a simultaneous request/retire attempt.
  request_valid=1;result_ready=1;cancel=1;step;request_valid=0;result_ready=0;cancel=0;
  if(result_valid_ref||result_error_ref||result_geometry_ref!=0||result_parameter_first_ref!=0||
     result_tile_count_ref!=0||result_runs_ref!=0||result_windows_ref!=0)
   $fatal(1,"Cancel/request collision did not clear observable state");
  cancel_cases=cancel_cases+1;cancel_request_collisions=1;
  submit;if(result_error_ref)$fatal(1,"ROM failed after cancel");consume;
  if(negative_cases!=12||held!=203*3||cancel_cases!=1||back_to_back_replacements!=2||
     reset_request_collisions!=1||cancel_request_collisions!=1)
   $fatal(1,"ROM coverage held=%0d negative=%0d",held,negative_cases);
  $display("PLAN_ROM_BRAM_MITER_PASS tiles=189 negative_cases=%0d held_cycles=%0d cancel_cases=%0d latency_cycles=1 back_to_back_replacements=%0d reset_request_collisions=%0d cancel_request_collisions=%0d",
    negative_cases,held,cancel_cases,back_to_back_replacements,reset_request_collisions,cancel_request_collisions);$finish;
 end
 initial begin #1000000;$fatal(1,"ROM watchdog");end
endmodule
`default_nettype wire
