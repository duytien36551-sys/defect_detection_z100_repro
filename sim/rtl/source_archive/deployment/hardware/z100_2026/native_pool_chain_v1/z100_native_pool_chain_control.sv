`default_nettype none
// Private autonomous1..3 pass width20 pool controller. The source must already
// be committed by its owner. Two disjoint DDR ranges alternate; ownership is
// transferred only after both the pool packer and AXI writer finish.
// Error recovery never resets AXI: cancel is held until adapters drain, then
// clear_fault is issued in a separate cycle before accepting another command.
(* use_dsp="no" *)
module z100_native_pool_chain_control (
    input wire clk,rst_n,
    input wire cmd_valid,output wire cmd_ready,
    input wire [31:0] cmd_epoch,cmd_source_address,cmd_destination_address,
    input wire [10:0] cmd_channels,input wire [9:0] cmd_height,
    input wire [1:0] cmd_passes,input wire cmd_source_committed,
    input wire [31:0] cmd_timeout_cycles,
    input wire abort,recover,
    output wire active,output reg done,output wire fault,
    output reg [3:0] fault_code,output reg [1:0] completed_passes,
    output wire [31:0] epoch,source_address,destination_address,
    output wire [10:0] channels,output wire [9:0] height,output wire [13:0] word_count,
    output reg [31:0] result_address,output reg result_committed,
    output wire feature_begin,input wire feature_begin_ready,
    output wire read_order_config,input wire read_order_config_ready,
    output wire reader_command,input wire reader_command_ready,
    input wire reader_done,reader_busy,reader_fault,
    output wire feature_commit,input wire feature_commit_ready,
    output wire write_order_config,input wire write_order_config_ready,
    output wire writer_command,input wire writer_command_ready,
    input wire writer_done,writer_busy,writer_fault,
    output wire pool_job,input wire pool_job_ready,input wire pool_done,
    input wire pipeline_error,
    output wire semantic_cancel,output wire axi_cancel,output wire axi_clear_fault
);
    localparam IDLE=0,LOAD_CONFIG=1,READ_COMMAND=2,READ_WAIT=3,FEATURE_COMMIT=4,
               WRITE_CONFIG=5,POOL_COMMAND=6,WRITE_WAIT=7,NEXT_PASS=8,
               FAILED=9,RECOVER_CLEAR=10,RECOVER_WAIT=11;
    reg [3:0] state;
    reg [31:0] epoch_q,source_q,destination_q,timeout_q,elapsed_q;
    reg [10:0] channels_q;reg [9:0] height_q;reg [13:0] words_q;
    reg [1:0] passes_q;
    reg feature_configured,read_configured,write_configured,writer_started;
    reg read_finished,write_finished,pool_finished;
    wire running=state>=LOAD_CONFIG&&state<=NEXT_PASS;
    wire [31:0] command_words=(({21'd0,cmd_channels}+3)>>2)*cmd_height*2;
    wire [32:0] source_end={1'b0,cmd_source_address}+({1'b0,command_words}<<6);
    wire [32:0] destination_end={1'b0,cmd_destination_address}+({1'b0,command_words}<<6);
    wire disjoint=source_end<={1'b0,cmd_destination_address}||destination_end<={1'b0,cmd_source_address};
    wire command_good=cmd_epoch!=0&&cmd_channels!=0&&cmd_channels<=128&&cmd_height!=0&&cmd_height<=20&&
        cmd_passes!=0&&cmd_source_committed&&cmd_timeout_cycles!=0&&
        cmd_source_address[5:0]==0&&cmd_destination_address[5:0]==0&&
        source_end<=33'h100000000&&destination_end<=33'h100000000&&disjoint&&command_words<=8192;
    wire timed_out=running&&elapsed_q>=timeout_q;
    wire child_fault=reader_fault||writer_fault||pipeline_error;
    wire stop_work=abort||timed_out||child_fault;
    assign active=state!=IDLE;
    assign fault=state==FAILED||state==RECOVER_CLEAR||state==RECOVER_WAIT;
    assign cmd_ready=rst_n&&state==IDLE&&!abort&&!reader_busy&&!writer_busy&&!reader_fault&&!writer_fault&&!pipeline_error;
    assign epoch=epoch_q;assign source_address=source_q;assign destination_address=destination_q;
    assign channels=channels_q;assign height=height_q;assign word_count=words_q;
    assign feature_begin=rst_n&&state==LOAD_CONFIG&&!feature_configured&&!stop_work;
    assign read_order_config=rst_n&&state==LOAD_CONFIG&&!read_configured&&!stop_work;
    assign reader_command=rst_n&&state==READ_COMMAND&&!stop_work;
    assign feature_commit=rst_n&&state==FEATURE_COMMIT&&!stop_work;
    assign write_order_config=rst_n&&state==WRITE_CONFIG&&!write_configured&&!stop_work;
    assign writer_command=rst_n&&state==WRITE_CONFIG&&!writer_started&&!stop_work;
    assign pool_job=rst_n&&state==POOL_COMMAND&&!stop_work;
    assign semantic_cancel=rst_n&&(fault||running&&stop_work);
    assign axi_cancel=rst_n&&(state==FAILED||running&&stop_work);
    assign axi_clear_fault=rst_n&&state==RECOVER_CLEAR&&!abort;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;done<=0;fault_code<=0;completed_passes<=0;result_address<=0;result_committed<=0;
            epoch_q<=0;source_q<=0;destination_q<=0;timeout_q<=0;elapsed_q<=0;channels_q<=0;height_q<=0;words_q<=0;passes_q<=0;
            feature_configured<=0;read_configured<=0;write_configured<=0;writer_started<=0;
            read_finished<=0;write_finished<=0;pool_finished<=0;
        end else begin
            done<=0;
            if(running)elapsed_q<=elapsed_q+1;
            if(running&&stop_work)begin
                state<=FAILED;result_committed<=0;
                fault_code<=abort ? 4'd2 : timed_out ? 4'd3 : reader_fault ? 4'd4 : writer_fault ? 4'd5 : 4'd6;
            end else case(state)
                IDLE:if(cmd_valid&&cmd_ready)begin
                    result_committed<=0;completed_passes<=0;result_address<=0;fault_code<=0;elapsed_q<=0;
                    if(!command_good)begin state<=FAILED;fault_code<=1;end
                    else begin
                        epoch_q<=cmd_epoch;source_q<=cmd_source_address;destination_q<=cmd_destination_address;
                        channels_q<=cmd_channels;height_q<=cmd_height;words_q<=command_words[13:0];
                        passes_q<=cmd_passes;timeout_q<=cmd_timeout_cycles;
                        feature_configured<=0;read_configured<=0;write_configured<=0;writer_started<=0;
                        read_finished<=0;write_finished<=0;pool_finished<=0;state<=LOAD_CONFIG;
                    end
                end
                LOAD_CONFIG:begin
                    if(feature_begin&&feature_begin_ready)feature_configured<=1;
                    if(read_order_config&&read_order_config_ready)read_configured<=1;
                    if((feature_configured||feature_begin_ready)&&(read_configured||read_order_config_ready))state<=READ_COMMAND;
                end
                READ_COMMAND:if(reader_command_ready)state<=READ_WAIT;
                READ_WAIT:if(reader_done)begin read_finished<=1;state<=FEATURE_COMMIT;end
                FEATURE_COMMIT:if(feature_commit_ready)state<=WRITE_CONFIG;
                WRITE_CONFIG:begin
                    if(write_order_config&&write_order_config_ready)write_configured<=1;
                    if(writer_command&&writer_command_ready)writer_started<=1;
                    if((write_configured||write_order_config_ready)&&(writer_started||writer_command_ready))state<=POOL_COMMAND;
                end
                POOL_COMMAND:if(pool_job_ready)state<=WRITE_WAIT;
                WRITE_WAIT:begin
                    if(writer_done)write_finished<=1;
                    if(pool_done)pool_finished<=1;
                    if((write_finished||writer_done)&&(pool_finished||pool_done)&&!writer_busy)state<=NEXT_PASS;
                end
                NEXT_PASS:begin
                    completed_passes<=completed_passes+1;
                    if(completed_passes+1==passes_q)begin
                        result_address<=destination_q;result_committed<=1;done<=1;state<=IDLE;
                    end else begin
                        source_q<=destination_q;destination_q<=source_q;
                        feature_configured<=0;read_configured<=0;write_configured<=0;writer_started<=0;
                        read_finished<=0;write_finished<=0;pool_finished<=0;state<=LOAD_CONFIG;
                    end
                end
                FAILED:if(recover&&!abort&&!reader_busy&&!writer_busy)state<=RECOVER_CLEAR;
                RECOVER_CLEAR:if(!abort)state<=RECOVER_WAIT;else state<=FAILED;
                RECOVER_WAIT:if(abort)state<=FAILED;
                    else if(!reader_busy&&!writer_busy&&!reader_fault&&!writer_fault&&!pipeline_error)begin state<=IDLE;fault_code<=0;end
                default:begin state<=FAILED;result_committed<=0;fault_code<=7;end
            endcase
        end
    end
endmodule
`default_nettype wire
