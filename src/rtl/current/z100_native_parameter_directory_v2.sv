`default_nettype none
// One immutable32-byte parameter descriptor, two records per64-byte DDR word.
// Forwarding this record is NOT parameter configuration completion. Parent
// still waits for the real parameter loader's configured/drained event.
// rst_n is coordinated reset. Abort/error retains reader drain ownership;
// recover never clears an in-flight physical transfer.
(* use_dsp="no" *)
module z100_native_parameter_directory_v2(
 input wire clk,rst_n,abort,recover,consumer_idle,
 input wire cmd_valid,output wire cmd_ready,
 input wire[31:0] cmd_epoch,cmd_tag,cmd_table_base,cmd_model_crc,cmd_payload_begin,
 input wire[32:0] cmd_payload_end,input wire[15:0] cmd_job,cmd_count,
 input wire[31:0] cmd_timeout,
 output wire reader_command,input wire reader_command_ready,
 output wire[31:0] reader_epoch,reader_address,output wire[13:0] reader_words,
 input wire reader_busy,reader_fault,output wire reader_cancel,reader_clear,
 input wire reader_valid,output wire reader_ready,input wire[31:0] reader_result_epoch,
 input wire[12:0] reader_index,input wire reader_last,input wire[511:0] reader_data,
 output wire descriptor_valid,input wire descriptor_ready,
 output wire[31:0] descriptor_epoch,descriptor_tag,
 output wire[15:0] descriptor_job,output reg[10:0] descriptor_groups,output reg[5:0] descriptor_lanes,
 output reg[31:0] descriptor_weights,descriptor_bias,descriptor_factors,descriptor_unary,
 output wire active,needs_drain,output reg done,fault,output reg[3:0] fault_code
);
 localparam IDLE=0,ISSUE=1,READ=2,DRAIN=3,FORWARD=4,FAILED=5,CLEAR=6;
 reg[2:0] state;reg[31:0] epoch_q,tag_q,address_q,crc_q,begin_q,limit_q,timer;
 reg[32:0] end_q;reg[15:0] job_q;
 wire[32:0] table_end={1'b0,cmd_table_base}+((({17'd0,cmd_count}+1)>>1)<<6);
 wire invalid_command=cmd_epoch==0||cmd_tag==0||cmd_table_base==0||cmd_table_base[5:0]!=0||
     cmd_model_crc==0||cmd_count==0||cmd_count>173||cmd_job>=cmd_count||cmd_timeout==0||
     table_end>33'h100000000||cmd_payload_begin[5:0]!=0||cmd_payload_end<={1'b0,cmd_payload_begin}||cmd_payload_end>33'h100000000;
 wire[255:0] record=job_q[0]?reader_data[511:256]:reader_data[255:0];
 wire[31:0] w=record[31:0],b=record[63:32],f=record[95:64],u=record[127:96];
 wire[10:0] groups=record[138:128];wire[5:0] lanes=record[144:139];
 wire record_ok=record[159:145]==0&&record[175:160]==job_q&&record[191:176]==16'h5a50&&
     record[223:192]==crc_q&&record[255:224]==0&&groups>=1&&groups<=1024&&lanes>=1&&lanes<=32&&
     w[5:0]==0&&b[5:0]==0&&f[5:0]==0&&u[5:0]==0&&w>=begin_q&&b>=begin_q&&f>=begin_q&&u>=begin_q&&
     {1'b0,w}+{15'd0,groups,7'd0}<=end_q&&{1'b0,b}+128<=end_q&&{1'b0,f}+256<=end_q&&{1'b0,u}+256<=end_q;
 assign cmd_ready=rst_n&&state==IDLE&&!fault&&!abort&&!reader_busy&&!reader_fault&&consumer_idle;
 assign active=state!=IDLE&&state!=FAILED&&state!=CLEAR;assign needs_drain=state==FAILED||state==CLEAR;
 assign reader_command=rst_n&&state==ISSUE&&!fault&&!abort;
 assign reader_epoch=epoch_q;assign reader_address=address_q;assign reader_words=1;
 assign reader_ready=rst_n&&state==READ&&!fault&&!abort;
 assign reader_cancel=abort||state==FAILED;
 // Frozen reader requires clear_fault with cancel deasserted.
 assign reader_clear=state==CLEAR&&!reader_busy&&consumer_idle&&!abort;
 assign descriptor_valid=rst_n&&state==FORWARD&&!fault&&!abort;
 assign descriptor_epoch=epoch_q;assign descriptor_tag=tag_q;assign descriptor_job=job_q;
 task fail(input[3:0] code);begin state<=FAILED;fault<=1;fault_code<=code;end endtask
 always @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;done<=0;fault<=0;fault_code<=0;epoch_q<=0;tag_q<=0;address_q<=0;crc_q<=0;begin_q<=0;end_q<=0;
   limit_q<=0;timer<=0;job_q<=0;descriptor_groups<=0;descriptor_lanes<=0;
   descriptor_weights<=0;descriptor_bias<=0;descriptor_factors<=0;descriptor_unary<=0;
  end else begin
   done<=0;
   if(state==FAILED)begin if(recover&&!reader_busy&&consumer_idle&&!abort)state<=CLEAR;end
   else if(state==CLEAR)begin
    if(abort||!consumer_idle)state<=FAILED;
    else if(!reader_busy&&!reader_fault)begin state<=IDLE;fault<=0;fault_code<=0;end
   end
   else if(abort)fail(4'd2);
   else if(state!=IDLE&&timer>=limit_q-1)fail(4'd3);
   else if(state!=IDLE&&reader_fault)fail(4'd4);
   else begin
    if(state!=IDLE)timer<=timer+1;
    case(state)
     IDLE:if(cmd_valid&&cmd_ready)begin
      if(invalid_command)fail(4'd1);
      else begin epoch_q<=cmd_epoch;tag_q<=cmd_tag;job_q<=cmd_job;
       address_q<=cmd_table_base+{11'd0,cmd_job[15:1],6'd0};crc_q<=cmd_model_crc;begin_q<=cmd_payload_begin;end_q<=cmd_payload_end;
       limit_q<=cmd_timeout;timer<=0;state<=ISSUE;end
     end
     ISSUE:if(reader_command&&reader_command_ready)state<=READ;
     READ:if(reader_valid&&reader_ready)begin
      if(reader_result_epoch!=epoch_q||reader_index!=0||!reader_last)fail(4'd5);
      else if(!record_ok)fail(4'd6);
      else begin descriptor_groups<=groups;descriptor_lanes<=lanes;
       descriptor_weights<=w;descriptor_bias<=b;descriptor_factors<=f;descriptor_unary<=u;state<=DRAIN;end
     end
     DRAIN:if(!reader_busy)state<=FORWARD;
     FORWARD:if(descriptor_valid&&descriptor_ready)begin state<=IDLE;done<=1;end
     default:if(state!=IDLE)fail(4'd7);
    endcase
   end
  end
 end
endmodule
`default_nettype wire
