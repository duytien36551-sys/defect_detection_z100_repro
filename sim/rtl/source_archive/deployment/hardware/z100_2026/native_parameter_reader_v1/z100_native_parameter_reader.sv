`default_nettype none
// Immutable parameter-region reader -> strict config bridge. One frozen AXI
// reader owns all four segments; never clear/cancel by abandoning AXI traffic.
// cfg_cancel invalidates only private configuration; reader_cancel drains IO.
module z100_native_parameter_reader(
    input wire clk,rst_n,abort,recover,
    input wire job_valid,output wire job_ready,input wire [31:0] job_epoch,job_timeout,
    input wire [10:0] job_groups,input wire [5:0] job_lanes,
    input wire [31:0] job_weights,job_bias,job_factors,job_unary,
    output wire reader_command,input wire reader_command_ready,
    output wire [31:0] reader_epoch,reader_address,output wire [13:0] reader_words,
    input wire reader_busy,reader_fault,output wire reader_cancel,reader_clear,
    input wire reader_valid,output wire reader_ready,input wire [31:0] reader_result_epoch,
    input wire [12:0] reader_index,input wire reader_last,input wire [511:0] reader_data,
    output wire cfg_valid,input wire cfg_ready,output wire [3:0] cfg_operation,
    output wire [31:0] cfg_epoch,cfg_tag,cfg_index,output wire [10:0] cfg_groups,
    output wire [5:0] cfg_lanes,output reg [1023:0] cfg_data,
    input wire cfg_response_valid,output wire cfg_response_ready,input wire [31:0] cfg_response_tag,
    input wire cfg_response_error,cfg_fault,cfg_configured,output wire cfg_cancel,
    output wire active,fault,output reg [3:0] fault_code,output reg done
);
    localparam IDLE=0,SEND=1,REPLY=2,READ_CMD=3,COLLECT=4,DRAIN=5,FINISH=6,FAIL_DRAIN=7,FAILED=8,CLEAR=9;
    reg [3:0] state,op_q,segment;
    reg [31:0] epoch_q,timeout_q,elapsed,tag_q,weight_q,bias_q,factor_q,unary_q;
    reg [10:0] groups_q;reg [5:0] lanes_q;
    reg [13:0] received,total_words;
    reg [2:0] chunk_words;
    reg [31:0] emit_index;
    reg [2047:0] staging;
    wire running=state!=IDLE&&state<FAIL_DRAIN;
    wire expired=running&&elapsed>=timeout_q;
    wire stop_now=abort||expired||reader_fault||cfg_fault;
    wire [32:0] weight_end={1'b0,job_weights}+({22'd0,job_groups}<<7);
    wire good=job_epoch!=0&&job_timeout!=0&&job_groups>0&&job_groups<=1024&&job_lanes>0&&job_lanes<=32&&
        job_weights[5:0]==0&&job_bias[5:0]==0&&job_factors[5:0]==0&&job_unary[5:0]==0&&
        weight_end<=33'h100000000&&{1'b0,job_bias}+33'd128<=33'h100000000&&
        {1'b0,job_factors}+33'd256<=33'h100000000&&{1'b0,job_unary}+33'd256<=33'h100000000;
    wire bad_word=reader_result_epoch!=epoch_q||{1'b0,reader_index}!=received||reader_last!=(received+1==total_words);
    wire expected_reply=cfg_response_tag==tag_q;
    assign active=state!=IDLE;
    assign fault=state>=FAIL_DRAIN;
    assign job_ready=rst_n&&state==IDLE&&!abort&&!reader_busy&&!reader_fault&&!cfg_fault;
    assign reader_command=rst_n&&state==READ_CMD&&!stop_now;
    assign reader_epoch=epoch_q;
    assign reader_address=segment==4?weight_q:segment==5?bias_q:segment==6?factor_q:unary_q;
    assign reader_words=total_words;
    assign reader_ready=rst_n&&state==COLLECT&&!stop_now;
    assign reader_cancel=rst_n&&(state==FAIL_DRAIN||state==FAILED||running&&stop_now);
    assign reader_clear=rst_n&&state==CLEAR&&!abort;
    assign cfg_cancel=rst_n&&(state==FAIL_DRAIN||state==FAILED||running&&stop_now);
    assign cfg_valid=rst_n&&state==SEND&&!stop_now;
    assign cfg_operation=op_q;assign cfg_epoch=epoch_q;assign cfg_tag=tag_q;assign cfg_index=emit_index;
    assign cfg_groups=groups_q;assign cfg_lanes=lanes_q;
    assign cfg_response_ready=rst_n&&state==REPLY&&expected_reply&&!stop_now;
    // Staging only changes after a real received beat. No reset on payload.
    always @*begin
        cfg_data=0;
        if(op_q==4||op_q==5)cfg_data=staging[1023:0];
        else if(op_q==6)cfg_data[63:0]=staging[emit_index[4:0]*64+:64];
        else if(op_q==7)cfg_data[7:0]=staging[emit_index[7:0]*8+:8];
    end
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;op_q<=1;segment<=4;epoch_q<=0;timeout_q<=0;elapsed<=0;tag_q<=1;
            weight_q<=0;bias_q<=0;factor_q<=0;unary_q<=0;groups_q<=0;lanes_q<=0;
            received<=0;total_words<=0;chunk_words<=0;emit_index<=0;fault_code<=0;done<=0;
        end else begin
            done<=0;
            if(running&&elapsed<32'hffffffff)elapsed<=elapsed+1;
            if(running&&stop_now)begin
                state<=FAIL_DRAIN;fault_code<=abort?4'd2:expired?4'd3:reader_fault?4'd4:4'd5;
            end else case(state)
                IDLE:if(job_valid&&job_ready)begin
                    if(!good)begin state<=FAILED;fault_code<=1;end
                    else begin
                        epoch_q<=job_epoch;timeout_q<=job_timeout;elapsed<=0;groups_q<=job_groups;lanes_q<=job_lanes;
                        weight_q<=job_weights;bias_q<=job_bias;factor_q<=job_factors;unary_q<=job_unary;
                        op_q<=1;segment<=4;tag_q<=1;emit_index<=0;received<=0;chunk_words<=0;fault_code<=0;state<=SEND;
                    end
                end
                SEND:if(cfg_valid&&cfg_ready)state<=REPLY;
                REPLY:if(cfg_response_valid)begin
                    if(!expected_reply)begin state<=FAIL_DRAIN;fault_code<=6;end
                    else if(cfg_response_ready)begin
                        if(cfg_response_error)begin state<=FAIL_DRAIN;fault_code<=7;end
                        else begin
                            tag_q<=tag_q+1;
                            if(op_q<3)begin op_q<=op_q+1;state<=SEND;end
                            else if(op_q==3)begin segment<=4;total_words<={3'd0,groups_q}<<1;received<=0;chunk_words<=0;emit_index<=0;state<=READ_CMD;end
                            else if(op_q==4)begin
                                if(emit_index+1<groups_q)begin emit_index<=emit_index+1;chunk_words<=0;state<=COLLECT;end
                                else state<=DRAIN;
                            end
                            else if(op_q==5)state<=DRAIN;
                            else if(op_q==6&&emit_index+1<lanes_q)begin emit_index<=emit_index+1;state<=SEND;end
                            else if(op_q==7&&emit_index<255)begin emit_index<=emit_index+1;state<=SEND;end
                            else if(op_q==6||op_q==7)state<=DRAIN;
                            else if(op_q<10)begin op_q<=op_q+1;state<=SEND;end
                            else state<=FINISH;
                        end
                    end
                end
                READ_CMD:if(reader_command&&reader_command_ready)begin state<=COLLECT;received<=0;chunk_words<=0;end
                COLLECT:if(reader_valid&&reader_ready)begin
                    if(bad_word)begin state<=FAIL_DRAIN;fault_code<=8;end
                    else begin
                        staging[chunk_words*512+:512]<=reader_data;
                        received<=received+1;chunk_words<=chunk_words+1;
                        if((segment<=5&&chunk_words==1)||(segment>=6&&chunk_words==3))begin op_q<=segment;state<=SEND;end
                    end
                end
                DRAIN:if(!reader_busy)begin
                    if(received!=total_words)begin state<=FAIL_DRAIN;fault_code<=9;end
                    else if(segment<7)begin
                        segment<=segment+1;total_words<=segment==4?14'd2:14'd4;
                        received<=0;chunk_words<=0;emit_index<=0;state<=READ_CMD;
                    end else begin op_q<=8;emit_index<=0;state<=SEND;end
                end
                FINISH:if(!reader_busy)begin
                    if(!cfg_configured)begin state<=FAIL_DRAIN;fault_code<=10;end
                    else begin done<=1;state<=IDLE;end
                end
                FAIL_DRAIN:if(!reader_busy)state<=FAILED;
                FAILED:if(recover&&!abort&&!reader_busy)state<=CLEAR;
                CLEAR:if(!reader_busy&&!reader_fault&&!cfg_fault&&!abort)begin state<=IDLE;fault_code<=0;end
            endcase
        end
    end
endmodule
`default_nettype wire
