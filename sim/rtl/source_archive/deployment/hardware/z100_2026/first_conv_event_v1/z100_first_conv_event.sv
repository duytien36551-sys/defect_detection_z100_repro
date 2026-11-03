`default_nettype none
// Serial materialized producer for epoch200's first3->16,640->320 Conv+SiLU.
// Sixteen real halo loads and full20-row tile computations. No child completion
// is fabricated. done means all output writes drained, not graph-slot publication.
// External owner retains source lease/destination reservation until done/recovery.
(* use_dsp="no" *)
module z100_first_conv_event(
 input wire clk,rst_n,cancel,recover,recovery_drained,
 input wire cmd_valid,output wire cmd_ready,
 input wire[31:0] cmd_epoch,cmd_job_base,cmd_token_base,cmd_tag_base,
 input wire source_leased,destination_reserved,
 output wire load_valid,input wire load_ready,
 input wire load_done,load_committed,load_fault,input wire[31:0] load_epoch,
 output wire tile_valid,input wire tile_ready,
 input wire tile_done,tile_fault,input wire[31:0] tile_done_epoch,tile_done_job,
 input wire io_quiet,
 output wire[31:0] epoch,job_tag,token_base,tag_base,
 output wire[9:0] input_y,input_rows,output_y,
 output wire child_cancel,active,needs_drain,
 output reg done,fault,output reg[3:0] fault_code,
 output reg[4:0] committed_tiles
);
 localparam IDLE=0,LOAD=1,LOAD_WAIT=2,TILE=3,TILE_WAIT=4,DRAIN=5,FAILED=6;
 reg[2:0] state;
 reg[31:0] epoch_q,job_q,token_q,tag_q,ledger_epoch,ledger_job;
 reg[3:0] index_q;
 wire good=cmd_epoch!=0 && cmd_job_base!=0 && cmd_token_base!=0 &&
  (cmd_epoch>ledger_epoch || (cmd_epoch==ledger_epoch && cmd_job_base>ledger_job)) &&
  {1'b0,cmd_job_base}+33'd15<=33'hffffffff &&
  {1'b0,cmd_token_base}+33'd5119<=33'hffffffff &&
  {1'b0,cmd_tag_base}+33'd46079<=33'hffffffff && source_leased && destination_reserved;
 assign cmd_ready=rst_n&&state==IDLE&&!cancel&&!fault;
 assign load_valid=rst_n&&state==LOAD&&!cancel&&!fault;
 assign tile_valid=rst_n&&state==TILE&&!cancel&&!fault;
 assign epoch=epoch_q;assign job_tag=job_q;assign token_base=token_q;assign tag_base=tag_q;
 assign output_y=index_q*10'd20;
 assign input_y=index_q==0?10'd0:index_q*10'd40-10'd1;
 assign input_rows=index_q==0?10'd40:10'd41;
 assign active=state!=IDLE&&state!=FAILED;
 assign needs_drain=state==FAILED;
 assign child_cancel=cancel||fault;
 always @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;epoch_q<=0;job_q<=0;token_q<=0;tag_q<=0;index_q<=0;
   ledger_epoch<=0;ledger_job<=0;done<=0;fault<=0;fault_code<=0;committed_tiles<=0;
  end else begin
   done<=0;
   if(state==FAILED)begin
    if(recover&&recovery_drained&&io_quiet&&!cancel&&!load_fault&&!tile_fault&&!load_done&&!tile_done)begin
     state<=IDLE;fault<=0;fault_code<=0;
    end
   end else if(cancel&&state!=IDLE)begin state<=FAILED;fault<=1;fault_code<=1;end
   else if(state!=IDLE && (!source_leased||!destination_reserved||load_fault||tile_fault))begin
    state<=FAILED;fault<=1;fault_code<=2;
   end else if(load_done&&state!=LOAD_WAIT || tile_done&&state!=TILE_WAIT)begin
    state<=FAILED;fault<=1;fault_code<=3;
   end else case(state)
    IDLE:if(cmd_valid&&cmd_ready)begin
     if(!good)begin state<=FAILED;fault<=1;fault_code<=4;end
     else begin
      epoch_q<=cmd_epoch;job_q<=cmd_job_base;token_q<=cmd_token_base;tag_q<=cmd_tag_base;
      ledger_epoch<=cmd_epoch;ledger_job<=cmd_job_base+15;index_q<=0;committed_tiles<=0;state<=LOAD;
     end
    end
    LOAD:if(load_valid&&load_ready)state<=LOAD_WAIT;
    LOAD_WAIT:if(load_done)begin
     if(!load_committed||load_epoch!=epoch_q)begin state<=FAILED;fault<=1;fault_code<=5;end
     else state<=TILE;
    end
    TILE:if(tile_valid&&tile_ready)state<=TILE_WAIT;
    TILE_WAIT:if(tile_done)begin
     if(tile_done_epoch!=epoch_q||tile_done_job!=job_q)begin state<=FAILED;fault<=1;fault_code<=6;end
     else begin committed_tiles<=committed_tiles+1'b1;state<=DRAIN;end
    end
    DRAIN:if(io_quiet)begin
     if(index_q==15)begin done<=1;state<=IDLE;end
     else begin index_q<=index_q+1'b1;job_q<=job_q+1;token_q<=token_q+320;tag_q<=tag_q+2880;state<=LOAD;end
    end
    default:begin state<=FAILED;fault<=1;fault_code<=7;end
   endcase
  end
 end
endmodule
`default_nettype wire
