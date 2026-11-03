`default_nettype none
// Direct-mapped32KiB,256 immutable128B lines. One accepted frozen-reader
// command fetches exactly TWO512-bit words. Install is atomic at checked word1;
// word0, cancelled/errored words and partial lines never modify cache payload
// or tags. Coordinated fabric reset clears validity only, not payload RAM.
module z100_native_pair_cache (
    input wire clk,rst_n,
    input wire cmd_valid,output wire cmd_ready,
    input wire [31:0] cmd_epoch,cmd_address,cmd_source_generation,
    input wire cancel,clear_fault,
    output wire busy,fault,output reg [3:0] fault_code,output reg done,
    output wire out_valid,input wire out_ready,output wire [31:0] out_epoch,out_address,
    output reg [1023:0] out_data,
    output wire memory_command,input wire memory_command_ready,
    output wire [31:0] memory_epoch,memory_address,output wire [13:0] memory_word_count,
    input wire memory_busy,memory_fault,output wire memory_cancel,memory_clear_fault,
    input wire memory_valid,output wire memory_ready,input wire [31:0] memory_result_epoch,
    input wire [12:0] memory_result_index,input wire memory_last,input wire [511:0] memory_data,
    output reg [31:0] hit_count,miss_count
);
    localparam IDLE=0,LOOKUP=1,MISS_COMMAND=2,MISS_FIRST=3,MISS_SECOND=4,OUTPUT_WAIT=5,FAILED=6,CLEAR=7;
    reg [2:0] state;
    reg [31:0] epoch_q,address_q,generation_q;
    reg [255:0] valid_bits;
    (* ram_style="block" *)reg [1023:0] data_memory[0:255];
    (* ram_style="block" *)reg [80:0] tag_memory[0:255];
    reg [1023:0] data_read;reg [80:0] tag_read;reg valid_read;
    reg [511:0] first_word;
    wire [7:0] index_q=address_q[14:7];
    wire [80:0] key_q={epoch_q,generation_q,address_q[31:15]};
    wire command_fire=cmd_valid&&cmd_ready;
    wire bad_command=cmd_epoch==0||cmd_source_generation==0||cmd_address[6:0]!=0;
    wire first_bad=memory_result_epoch!=epoch_q||memory_result_index!=0||memory_last;
    wire second_bad=memory_result_epoch!=epoch_q||memory_result_index!=1||!memory_last;
    wire install=state==MISS_SECOND&&memory_valid&&memory_ready&&!second_bad&&!memory_fault&&!cancel;
    always @(posedge clk)begin
        if(command_fire&&!bad_command)begin
            data_read<=data_memory[cmd_address[14:7]];tag_read<=tag_memory[cmd_address[14:7]];
        end
        if(install)begin data_memory[index_q]<={memory_data,first_word};tag_memory[index_q]<=key_q;end
    end
    assign fault=state==FAILED||state==CLEAR||memory_fault;
    assign busy=memory_busy||(state!=IDLE&&state!=FAILED);
    assign cmd_ready=rst_n&&state==IDLE&&!cancel&&!memory_busy&&!memory_fault;
    assign memory_epoch=epoch_q;assign memory_address=address_q;assign memory_word_count=14'd2;
    assign memory_command=rst_n&&state==MISS_COMMAND&&!cancel&&!memory_fault;
    assign memory_ready=rst_n&&(state==MISS_FIRST||state==MISS_SECOND)&&!cancel&&!memory_fault;
    assign memory_cancel=rst_n&&(cancel||state==FAILED);
    assign memory_clear_fault=rst_n&&state==CLEAR&&!cancel;
    assign out_valid=rst_n&&state==OUTPUT_WAIT&&!cancel&&!memory_fault;
    assign out_epoch=epoch_q;assign out_address=address_q;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;epoch_q<=0;address_q<=0;generation_q<=0;valid_bits<=0;valid_read<=0;
            done<=0;fault_code<=0;out_data<=0;first_word<=0;hit_count<=0;miss_count<=0;
        end else begin
            done<=0;
            if(cancel&&state!=FAILED&&state!=CLEAR)begin state<=FAILED;fault_code<=2;end
            else if(memory_fault&&state!=FAILED&&state!=CLEAR)begin state<=FAILED;fault_code<=4;end
            else case(state)
                IDLE:if(command_fire)begin
                    if(bad_command)begin state<=FAILED;fault_code<=1;end
                    else begin epoch_q<=cmd_epoch;address_q<=cmd_address;generation_q<=cmd_source_generation;
                        valid_read<=valid_bits[cmd_address[14:7]];state<=LOOKUP;end
                end
                LOOKUP:if(valid_read&&tag_read==key_q)begin out_data<=data_read;hit_count<=hit_count+1;state<=OUTPUT_WAIT;end
                    else begin miss_count<=miss_count+1;state<=MISS_COMMAND;end
                MISS_COMMAND:if(memory_command&&memory_command_ready)state<=MISS_FIRST;
                MISS_FIRST:if(memory_valid&&memory_ready)begin
                    if(first_bad)begin state<=FAILED;fault_code<=3;end
                    else begin first_word<=memory_data;state<=MISS_SECOND;end
                end
                MISS_SECOND:if(memory_valid&&memory_ready)begin
                    if(second_bad)begin state<=FAILED;fault_code<=3;end
                    else begin valid_bits[index_q]<=1;out_data<={memory_data,first_word};state<=OUTPUT_WAIT;end
                end
                OUTPUT_WAIT:if(out_valid&&out_ready)begin done<=1;state<=IDLE;end
                FAILED:if(clear_fault&&!cancel&&!memory_busy)state<=CLEAR;
                CLEAR:if(cancel)state<=FAILED;else if(!memory_busy&&!memory_fault)begin state<=IDLE;fault_code<=0;end
                default:begin state<=FAILED;fault_code<=5;end
            endcase
        end
    end
endmodule
`default_nettype wire
