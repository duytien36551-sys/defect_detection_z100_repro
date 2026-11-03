`default_nettype none
// Private generic materialized Conv producer. Descriptor order is supplied by
// the frozen C halo plan; the existing tile controller validates full geometry.
// Completion means all tiles and write responses drained, not slot publication.
(* use_dsp="no" *)
module z100_conv_event_control(
 input wire clk,rst_n,cancel,recover,recovery_drained,
 input wire cmd_valid,output wire cmd_ready,
 input wire[31:0] cmd_epoch,cmd_job_base,cmd_token_base,cmd_tag_base,
 input wire[7:0] cmd_tiles,
 input wire[9:0] cmd_output_height,
 input wire source_leased,destination_reserved,
 input wire descriptor_valid,output wire descriptor_ready,
 input wire[31:0] descriptor_epoch,
 input wire[7:0] descriptor_index,
 input wire[9:0] descriptor_input_y,descriptor_input_rows,
 input wire[9:0] descriptor_output_y,descriptor_output_rows,
 input wire[31:0] descriptor_runs,descriptor_windows,
 output wire load_valid,input wire load_ready,
 input wire load_done,load_committed,load_fault,input wire[31:0] load_epoch,
 output wire tile_valid,input wire tile_ready,
 input wire tile_done,tile_fault,input wire[31:0] tile_done_epoch,tile_done_job,
 input wire io_quiet,
 output wire[31:0] epoch,job_tag,token_base,tag_base,
 output wire[9:0] input_y,input_rows,output_y,output_rows,
 output wire[7:0] next_descriptor,
 output wire child_cancel,active,needs_drain,
 output reg done,fault,output reg[3:0] fault_code,
 output reg[7:0] committed_tiles
);
 localparam IDLE=0,DESC=1,LOAD=2,LOAD_WAIT=3,TILE=4,TILE_WAIT=5,DRAIN=6,FAILED=7;
 reg[2:0] state;
 reg[31:0] epoch_q,job_q,token_q,tag_q,runs_q,windows_q,ledger_epoch,ledger_job;
 reg[7:0] count_q,index_q;
 reg[9:0] height_q,iy_q,ir_q,oy_q,rows_q;
 reg[10:0] expected_y;
 wire last_tile=index_q+9'd1=={1'b0,count_q};
 wire[32:0] token_end={1'b0,token_q}+{1'b0,descriptor_runs};
 wire[32:0] tag_end={1'b0,tag_q}+{1'b0,descriptor_windows};
 wire command_ok=cmd_epoch!=0&&cmd_job_base!=0&&cmd_token_base!=0&&cmd_tiles!=0&&cmd_tiles<=189&&
  cmd_output_height!=0&&cmd_output_height<=640&&source_leased&&destination_reserved&&
  (cmd_epoch>ledger_epoch||(cmd_epoch==ledger_epoch&&cmd_job_base>ledger_job))&&
  {1'b0,cmd_job_base}+{25'd0,cmd_tiles}-33'd1<=33'hffffffff;
 // Nonfinal descriptors must leave representable bases for the next tile.
 wire descriptor_ok=descriptor_epoch==epoch_q&&descriptor_index==index_q&&
  descriptor_input_rows!=0&&{1'b0,descriptor_input_y}+{1'b0,descriptor_input_rows}<=640&&
  descriptor_output_rows!=0&&{1'b0,descriptor_output_y}==expected_y&&
  expected_y+{1'b0,descriptor_output_rows}<={1'b0,height_q}&&
  (last_tile?(expected_y+{1'b0,descriptor_output_rows}=={1'b0,height_q}):
             (expected_y+{1'b0,descriptor_output_rows}<{1'b0,height_q}))&&
  descriptor_runs!=0&&descriptor_windows>=descriptor_runs&&
  token_end<=(last_tile?33'h100000000:33'hffffffff)&&
  tag_end<=(last_tile?33'h100000000:33'hffffffff);
 assign cmd_ready=rst_n&&state==IDLE&&!cancel&&!fault;
 assign descriptor_ready=rst_n&&state==DESC&&!cancel&&!fault;
 assign load_valid=rst_n&&state==LOAD&&!cancel&&!fault;
 assign tile_valid=rst_n&&state==TILE&&!cancel&&!fault;
 assign epoch=epoch_q;assign job_tag=job_q;assign token_base=token_q;assign tag_base=tag_q;
 assign input_y=iy_q;assign input_rows=ir_q;assign output_y=oy_q;assign output_rows=rows_q;
 assign next_descriptor=index_q;
 assign active=state!=IDLE&&state!=FAILED;assign needs_drain=state==FAILED;
 assign child_cancel=cancel||fault;
 task fail(input[3:0] code);begin state<=FAILED;fault<=1;fault_code<=code;end endtask
 always @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;epoch_q<=0;job_q<=0;token_q<=0;tag_q<=0;runs_q<=0;windows_q<=0;
   ledger_epoch<=0;ledger_job<=0;count_q<=0;index_q<=0;height_q<=0;expected_y<=0;
   iy_q<=0;ir_q<=0;oy_q<=0;rows_q<=0;done<=0;fault<=0;fault_code<=0;committed_tiles<=0;
  end else begin
   done<=0;
   if(state==FAILED)begin
    if(recover&&recovery_drained&&io_quiet&&!cancel&&!load_fault&&!tile_fault&&!load_done&&!tile_done)begin
     state<=IDLE;fault<=0;fault_code<=0;
    end
   end else if(cancel&&state!=IDLE)fail(1);
   else if(state!=IDLE&&(!source_leased||!destination_reserved||load_fault||tile_fault))fail(2);
   else if((load_done&&state!=LOAD_WAIT)||(tile_done&&state!=TILE_WAIT))fail(3);
   else case(state)
    IDLE:if(cmd_valid&&cmd_ready)begin
     if(!command_ok)fail(4);
     else begin
      epoch_q<=cmd_epoch;job_q<=cmd_job_base;token_q<=cmd_token_base;tag_q<=cmd_tag_base;
      count_q<=cmd_tiles;height_q<=cmd_output_height;index_q<=0;expected_y<=0;committed_tiles<=0;
      ledger_epoch<=cmd_epoch;ledger_job<=cmd_job_base+cmd_tiles-1'b1;state<=DESC;
     end
    end
    DESC:if(descriptor_valid&&descriptor_ready)begin
     if(!descriptor_ok)fail(8);
     else begin
      iy_q<=descriptor_input_y;ir_q<=descriptor_input_rows;oy_q<=descriptor_output_y;rows_q<=descriptor_output_rows;
      runs_q<=descriptor_runs;windows_q<=descriptor_windows;state<=LOAD;
     end
    end
    LOAD:if(load_valid&&load_ready)state<=LOAD_WAIT;
    LOAD_WAIT:if(load_done)begin
     if(!load_committed||load_epoch!=epoch_q)fail(5);else state<=TILE;
    end
    TILE:if(tile_valid&&tile_ready)state<=TILE_WAIT;
    TILE_WAIT:if(tile_done)begin
     if(tile_done_epoch!=epoch_q||tile_done_job!=job_q)fail(6);
     else begin committed_tiles<=committed_tiles+1'b1;state<=DRAIN;end
    end
    DRAIN:if(io_quiet)begin
     if(last_tile)begin done<=1;state<=IDLE;end
     else begin
      index_q<=index_q+1'b1;job_q<=job_q+1'b1;token_q<=token_q+runs_q;tag_q<=tag_q+windows_q;
      expected_y<={1'b0,oy_q}+{1'b0,rows_q};state<=DESC;
     end
    end
    default:fail(7);
   endcase
  end
 end
endmodule
`default_nettype wire
