`default_nettype none
// Private config transaction adapter; never owns an AXI transaction. cancel
// invalidates all child configuration, so callers cannot reuse partial state.
module z100_native_parameter_bridge(
    input wire clk,rst_n,cancel,
    input wire cmd_valid,output wire cmd_ready,input wire [3:0] cmd_operation,
    input wire [31:0] cmd_epoch,cmd_tag,cmd_index,input wire [10:0] cmd_groups,
    input wire [5:0] cmd_lanes,input wire [1023:0] cmd_data,
    output wire response_valid,input wire response_ready,output reg [31:0] response_tag,
    output reg response_error,output wire configured,output wire child_cancel,
    output wire [31:0] cfg_epoch,output wire [10:0] cfg_groups,output wire [5:0] cfg_lanes,
    output wire mac_begin,input wire mac_begin_ready,output wire mac_weight,input wire mac_weight_ready,
    output wire mac_bias,input wire mac_bias_ready,output wire mac_commit,input wire mac_commit_ready,
    output wire [1023:0] mac_data,input wire mac_error,mac_loaded,input wire [31:0] mac_epoch,
    output wire factor_begin,input wire factor_begin_ready,output wire factor_word,input wire factor_word_ready,
    output wire factor_commit,input wire factor_commit_ready,output wire [30:0] factor_multiplier,
    output wire [5:0] factor_shift,input wire factor_error,
    output wire unary_begin,input wire unary_begin_ready,output wire unary_word,input wire unary_word_ready,
    output wire unary_commit,input wire unary_commit_ready,output wire [7:0] unary_data,
    input wire unary_error,unary_loaded,input wire [31:0] unary_epoch,
    output wire fault
);
    localparam IDLE=0,ISSUE=1,CHECK=2,RESPONSE=3;
    reg [1:0] state;reg [3:0] expected,operation_q;reg [31:0] index_q,epoch_q;
    reg [10:0] groups_q;reg [5:0] lanes_q;reg [1023:0] data_q;
    reg fault_q,configured_q;
    wire enabled=rst_n&&!cancel&&!fault_q;
    wire factor_good=cmd_data[31:0]!=0&&!cmd_data[31]&&cmd_data[39:32]<=63&&
        cmd_data[47:40]>=1&&cmd_data[47:40]<=31&&cmd_data[63:48]==1;
    wire command_good=cmd_epoch!=0&&cmd_groups>0&&cmd_groups<=1024&&cmd_lanes>0&&cmd_lanes<=32&&
        cmd_tag!=0&&cmd_operation==expected&&cmd_index==index_q&&
        (expected==1||(cmd_epoch==epoch_q&&cmd_groups==groups_q&&cmd_lanes==lanes_q))&&
        (expected!=6||factor_good);
    wire child_error=mac_error||factor_error||unary_error;
    wire issued=enabled&&state==ISSUE;
    reg target_ready;
    always @*case(operation_q)
        1:target_ready=mac_begin_ready;2:target_ready=factor_begin_ready;3:target_ready=unary_begin_ready;
        4:target_ready=mac_weight_ready;5:target_ready=mac_bias_ready;6:target_ready=factor_word_ready;
        7:target_ready=unary_word_ready;8:target_ready=mac_commit_ready;
        9:target_ready=factor_commit_ready;10:target_ready=unary_commit_ready;
        default:target_ready=0;
    endcase
    assign cmd_ready=enabled&&state==IDLE;
    assign response_valid=rst_n&&!cancel&&state==RESPONSE;
    assign configured=enabled&&configured_q;
    assign child_cancel=cancel||fault_q;
    assign fault=fault_q;
    assign cfg_epoch=epoch_q;assign cfg_groups=groups_q;assign cfg_lanes=lanes_q;
    assign mac_data=data_q;assign factor_multiplier=data_q[30:0];assign factor_shift=data_q[37:32];assign unary_data=data_q[7:0];
    assign mac_begin=issued&&operation_q==1;assign factor_begin=issued&&operation_q==2;assign unary_begin=issued&&operation_q==3;
    assign mac_weight=issued&&operation_q==4;assign mac_bias=issued&&operation_q==5;assign factor_word=issued&&operation_q==6;
    assign unary_word=issued&&operation_q==7;assign mac_commit=issued&&operation_q==8;
    assign factor_commit=issued&&operation_q==9;assign unary_commit=issued&&operation_q==10;
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            state<=IDLE;expected<=1;operation_q<=0;index_q<=0;epoch_q<=0;groups_q<=0;lanes_q<=0;
            fault_q<=0;configured_q<=0;response_error<=0;response_tag<=0;
        end else begin
            if(child_error)begin fault_q<=1;configured_q<=0;end
            case(state)
                IDLE:if(cmd_valid&&cmd_ready)begin
                    response_tag<=cmd_tag;response_error<=0;configured_q<=0;
                    if(!command_good||child_error)begin fault_q<=1;response_error<=1;state<=RESPONSE;end
                    else begin
                        operation_q<=cmd_operation;data_q<=cmd_data;
                        if(expected==1)begin epoch_q<=cmd_epoch;groups_q<=cmd_groups;lanes_q<=cmd_lanes;end
                        state<=ISSUE;
                    end
                end
                ISSUE:if(child_error||fault_q)begin response_error<=1;state<=RESPONSE;end
                    else if(issued&&target_ready)state<=CHECK;
                CHECK:begin
                    state<=RESPONSE;
                    if(child_error||fault_q||
                       (operation_q==8&&(!mac_loaded||mac_epoch!=epoch_q))||
                       (operation_q==10&&(!unary_loaded||unary_epoch!=epoch_q)))begin
                        fault_q<=1;configured_q<=0;response_error<=1;
                    end else begin
                        if((operation_q==4&&index_q+1<groups_q)||(operation_q==6&&index_q+1<lanes_q)||(operation_q==7&&index_q<255))index_q<=index_q+1;
                        else begin index_q<=0;expected<=operation_q==10?1:operation_q+1'b1;end
                        if(operation_q==10)configured_q<=1;
                    end
                end
                RESPONSE:if(response_valid&&response_ready)state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
