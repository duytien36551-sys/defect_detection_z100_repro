`timescale 1ns/1ps
`default_nettype none
module tb_z100_conv_plan_rom;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,cancel=0,request_valid=0,result_ready=0;
 wire request_ready,result_valid,result_error;
 reg[31:0] request_epoch=1,request_tag=1,request_model_crc=2213989717;
 reg[7:0] request_event=1,request_tile=0;
 wire[31:0] result_epoch,result_tag,result_runs,result_windows;
 wire[7:0] result_event,result_tile,result_tile_count;
 wire[15:0] result_parameter_first;wire[207:0] result_geometry;
 z100_conv_plan_rom dut(.*);
 reg[31:0] expected[0:3212]; //189*17, unpacked original C geometry/bindings.
 wire[376:0] snapshot={result_epoch,result_tag,result_event,result_tile,result_error,result_geometry,result_parameter_first,result_tile_count,result_runs,result_windows};
 reg[376:0] saved;reg[319:0] saved_record;
 integer i,j,held=0,negative_cases=0,cancel_cases=0;
 integer expected_runs,expected_windows;
 task step;begin @(posedge clk);#1;@(negedge clk);end endtask
 task submit;begin
  request_valid=1;#1;if(!request_ready)$fatal(1,"ROM admission unavailable");step;request_valid=0;
  if(!result_valid||result_epoch!=request_epoch||result_tag!=request_tag||result_event!=request_event||result_tile!=request_tile)$fatal(1,"ROM result identity/latency");
  saved=snapshot;
  repeat(3)begin
   // A different unaccepted request must not affect the held response.
   request_valid=1;request_tag=request_tag+1;
   #1;if(request_ready)$fatal(1,"Accepted over held ROM result");step;
   if(!result_valid||snapshot!==saved)$fatal(1,"Held ROM payload changed");held=held+1;
  end
  request_valid=0;
 end endtask
 task consume;begin result_ready=1;step;result_ready=0;if(result_valid)$fatal(1,"ROM result did not retire");end endtask
 task invalid;begin
  submit;if(!result_error||result_geometry!=0||result_parameter_first!=0||result_tile_count!=0||result_runs!=0||result_windows!=0)$fatal(1,"Invalid plan leaked usable metadata");
  negative_cases=negative_cases+1;consume;
 end endtask
 initial begin
  $readmemh("expected_plan.hex",expected);
  repeat(3)step;rst_n=1;step;
  for(i=0;i<189;i=i+1)begin
   request_epoch=1;request_tag=1000+i;request_event=expected[i*17+13];request_tile=expected[i*17+14];submit;
   if(result_error||result_tile_count!=expected[i*17+15]||result_parameter_first!=expected[i*17+16])$fatal(1,"ROM C binding tile=%0d",i);
   for(j=0;j<13;j=j+1)if(result_geometry[j*16+:16]!==expected[i*17+j][15:0])$fatal(1,"ROM C geometry tile=%0d field=%0d",i,j);
   expected_runs=((expected[i*17+9]+31)/32)*expected[i*17+6]*((expected[i*17+8]+19)/20);
   expected_windows=expected_runs*((expected[i*17]+3)/4)*expected[i*17+10]*expected[i*17+10];
   if(result_runs!=expected_runs||result_windows!=expected_windows)$fatal(1,"ROM run/window budget tile=%0d",i);consume;
  end
  request_event=1;request_tile=0;request_epoch=0;invalid;request_epoch=1;
  request_tag=0;invalid;request_tag=1;
  request_model_crc=0;invalid;request_model_crc=2213989717;
  request_event=0;invalid;request_event=255;invalid;request_event=1;
  request_tile=16;invalid;request_tile=255;invalid;request_tile=0;
  saved_record=dut.tile_rom[0];
  dut.tile_rom[0]=saved_record^(320'd1<<312);invalid;
  dut.tile_rom[0]=saved_record^(320'd1<<304);invalid;
  dut.tile_rom[0]=saved_record^(320'd1<<296);invalid;
  dut.tile_rom[0]=saved_record^(320'd1<<288);invalid;
  dut.tile_rom[0]=saved_record;
  submit;cancel=1;step;cancel=0;if(result_valid)$fatal(1,"Cancel retained stale ROM result");cancel_cases=cancel_cases+1;
  submit;if(result_error)$fatal(1,"ROM failed after cancel");consume;
  if(negative_cases!=11||held!=606||cancel_cases!=1)$fatal(1,"ROM coverage held=%0d",held);
  $display("CONV_PLAN_ROM_PASS tiles=189 negative_cases=11 held_cycles=606 cancel_cases=1");$finish;
 end
 initial begin #1000000;$fatal(1,"ROM watchdog");end
endmodule
`default_nettype wire
