`default_nettype none
// One source read owns one explicit manager reference before it can issue AR.
// Management request/reply interface must be exclusively arbitrated upstream.
// Cancellation while acquiring still waits for the matching acknowledgement;
// a successful late acquire is released without ever issuing the data read.
// Frozen reader retains advertised/accepted AXI requests and drains on cancel.
module z100_native_source_read (
    input wire clk,rst_n,abort,recover,
    input wire cmd_valid,output wire cmd_ready,input wire [2:0] cmd_slot,
    input wire [31:0] cmd_epoch,cmd_generation,cmd_address,cmd_timeout_cycles,cmd_tag,
    input wire [15:0] cmd_tensor_id,input wire [13:0] cmd_words,
    output wire [2:0] query_slot,input wire query_committed,query_fault,
    input wire [31:0] query_epoch,query_generation,query_address,query_bytes,input wire [15:0] query_tensor_id,
    output wire manager_valid,input wire manager_ready,output wire [2:0] manager_opcode,manager_slot,
    output wire [31:0] manager_tag,manager_epoch,manager_generation,output wire [15:0] manager_tensor_id,
    input wire manager_response_valid,output wire manager_response_ready,
    input wire [31:0] manager_response_tag,input wire [2:0] manager_response_slot,input wire [3:0] manager_response_code,
    output wire reader_command,input wire reader_command_ready,
    output wire [31:0] reader_epoch,reader_address,output wire [13:0] reader_words,
    input wire reader_busy,reader_done,reader_fault,output wire reader_cancel,reader_clear,
    input wire reader_valid,output wire reader_ready,input wire [31:0] reader_result_epoch,
    input wire [12:0] reader_index,input wire reader_last,input wire [511:0] reader_data,
    output wire out_valid,input wire out_ready,output wire [31:0] out_epoch,
    output wire [12:0] out_index,output wire out_last,output wire [511:0] out_data,
    output wire active,fault,lease_held,output reg [3:0] fault_code,output reg done
);
    localparam IDLE=0,ACQUIRE=1,ACQUIRE_REPLY=2,ISSUE=3,READ_WAIT=4,DRAIN=5,RELEASE=6,RELEASE_REPLY=7,FINISH=8,FAILED=9,CLEAR=10;
    reg [3:0] state;
    reg [2:0] slot_q;
    reg [31:0] epoch_q,generation_q,address_q,timeout_q,tag_q,elapsed;
    reg [15:0] tensor_q;
    reg [13:0] words_q,received;
    reg stopped,owns;
    wire running=state!=IDLE&&state!=FAILED&&state!=CLEAR;
    wire expired=running&&elapsed>=timeout_q;
    wire revoked=owns&&(!query_committed||query_fault||query_epoch!=epoch_q||query_generation!=generation_q||query_tensor_id!=tensor_q);
    wire stop_now=abort||expired||reader_fault||revoked;
    wire [32:0] requested_end={1'b0,cmd_address}+{13'd0,cmd_words,6'd0};
    wire [32:0] source_end={1'b0,query_address}+{1'b0,query_bytes};
    wire good_command=cmd_slot<7&&cmd_epoch!=0&&cmd_generation!=0&&cmd_timeout_cycles!=0&&cmd_tag!=32'hffffffff&&
        cmd_words>0&&cmd_words<=8192&&cmd_address[5:0]==0&&query_committed&&!query_fault&&
        cmd_epoch==query_epoch&&cmd_generation==query_generation&&cmd_tensor_id==query_tensor_id&&
        {1'b0,cmd_address}>={1'b0,query_address}&&requested_end<=source_end&&source_end<=33'h100000000;
    wire expected_response=manager_response_tag==manager_tag&&manager_response_slot==slot_q;
    wire bad_word=reader_result_epoch!=epoch_q||{1'b0,reader_index}!=received||reader_last!=(received+1==words_q);
    assign query_slot=state==IDLE ? cmd_slot : slot_q;
    assign cmd_ready=rst_n&&state==IDLE&&!reader_busy&&!reader_fault&&!abort;
    assign manager_valid=rst_n&&(state==ACQUIRE||state==RELEASE);
    assign manager_opcode=(state==RELEASE||state==RELEASE_REPLY) ? 3'd4 : 3'd3;
    assign manager_slot=slot_q;assign manager_epoch=epoch_q;assign manager_generation=generation_q;assign manager_tensor_id=tensor_q;
    assign manager_tag=(state==RELEASE||state==RELEASE_REPLY) ? tag_q+1 : tag_q;
    assign manager_response_ready=rst_n&&(state==ACQUIRE_REPLY||state==RELEASE_REPLY)&&expected_response;
    assign reader_command=rst_n&&state==ISSUE&&!stopped&&!stop_now;
    assign reader_epoch=epoch_q;assign reader_address=address_q;assign reader_words=words_q;
    assign reader_cancel=rst_n&&(stopped||stop_now)&&(state==ISSUE||state==READ_WAIT||state==DRAIN||state==RELEASE||state==RELEASE_REPLY||state==FAILED);
    assign reader_clear=rst_n&&state==CLEAR&&!abort;
    assign reader_ready=rst_n&&state==READ_WAIT&&!stopped&&!stop_now&&(bad_word ? 1'b1 : out_ready);
    assign out_valid=rst_n&&state==READ_WAIT&&!stopped&&!stop_now&&reader_valid&&!bad_word;
    assign out_epoch=reader_result_epoch;assign out_index=reader_index;assign out_last=reader_last;assign out_data=reader_data;
    assign active=state!=IDLE;assign fault=stopped||state==FAILED||state==CLEAR;assign lease_held=owns;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;slot_q<=0;epoch_q<=0;generation_q<=0;address_q<=0;timeout_q<=0;tag_q<=0;elapsed<=0;tensor_q<=0;
            words_q<=0;received<=0;stopped<=0;owns<=0;fault_code<=0;done<=0;
        end else begin
            done<=0;
            if(running&&elapsed!=32'hffffffff)elapsed<=elapsed+1;
            if(running&&stop_now&&!stopped)begin stopped<=1;fault_code<=abort ? 2 : expired ? 3 : reader_fault ? 4 : 5;end
            if((state==ACQUIRE_REPLY||state==RELEASE_REPLY)&&manager_response_valid&&!expected_response)begin stopped<=1;fault_code<=6;end
            case(state)
                IDLE:if(cmd_valid&&cmd_ready)begin
                    stopped<=0;owns<=0;elapsed<=0;received<=0;fault_code<=0;
                    if(!good_command)begin state<=FAILED;stopped<=1;fault_code<=1;end
                    else begin state<=ACQUIRE;slot_q<=cmd_slot;epoch_q<=cmd_epoch;generation_q<=cmd_generation;address_q<=cmd_address;
                        timeout_q<=cmd_timeout_cycles;tag_q<=cmd_tag;tensor_q<=cmd_tensor_id;words_q<=cmd_words;end
                end
                ACQUIRE:if(manager_valid&&manager_ready)state<=ACQUIRE_REPLY;
                ACQUIRE_REPLY:if(manager_response_valid&&manager_response_ready)begin
                    if(manager_response_code==0)begin owns<=1;state<=stopped||stop_now ? DRAIN : ISSUE;end
                    else begin state<=FAILED;stopped<=1;fault_code<=7;end
                end
                ISSUE:if(stopped||stop_now)state<=DRAIN;
                    else if(reader_command&&reader_command_ready)state<=READ_WAIT;
                READ_WAIT:begin
                    if(stopped||stop_now)state<=DRAIN;
                    else if(reader_valid&&reader_ready)begin
                        if(bad_word)begin stopped<=1;fault_code<=8;state<=DRAIN;end
                        else received<=received+1;
                    end
                    if(reader_done)begin
                        if(received!=words_q)begin stopped<=1;fault_code<=9;end
                        state<=DRAIN;
                    end
                end
                DRAIN:if(!reader_busy)state<=owns ? RELEASE : FINISH;
                RELEASE:if(manager_valid&&manager_ready)state<=RELEASE_REPLY;
                RELEASE_REPLY:if(manager_response_valid&&manager_response_ready)begin
                    if(manager_response_code==0)begin owns<=0;state<=FINISH;end
                    else if(manager_response_code==3)state<=RELEASE;
                    else begin stopped<=1;fault_code<=10;state<=RELEASE;end
                end
                FINISH:if(stopped||stop_now)state<=FAILED;else begin done<=1;state<=IDLE;end
                FAILED:if(recover&&!abort&&!reader_busy&&!owns)state<=CLEAR;
                CLEAR:if(abort)state<=FAILED;else if(!reader_busy&&!reader_fault)begin state<=IDLE;stopped<=0;fault_code<=0;end
                default:begin state<=FAILED;stopped<=1;fault_code<=11;end
            endcase
        end
    end
endmodule
`default_nettype wire
