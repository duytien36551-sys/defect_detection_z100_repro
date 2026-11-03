`default_nettype none
// Serializes one immutable128B pair through the existing exact64B context LUT.
// One request owns metadata/cache/result slots until both output words retire.
// Cache retains external AXI ownership and drains on cancel; no local reset.
module z100_native_pair_transform (
    input wire clk,rst_n,cancel,recover,input wire [31:0] timeout_cycles,
    input wire cfg_begin,output wire cfg_begin_ready,input wire [31:0] cfg_epoch,
    input wire [2:0] cfg_contexts,input wire cfg_word_valid,output wire cfg_word_ready,
    input wire [7:0] cfg_data,input wire cfg_commit,output wire cfg_commit_ready,output wire store_valid,
    input wire req_valid,output wire req_ready,input wire [31:0] req_epoch,req_address,req_source_generation,req_table_epoch,
    input wire [1:0] req_context,req_shift,input wire [3:0] req_source_first_x,input wire [4:0] req_valid_x,
    input wire [11:0] req_native_word,input wire req_last,
    output wire cache_command,input wire cache_command_ready,output wire [31:0] cache_epoch,cache_address,cache_generation,
    input wire cache_busy,cache_fault,output wire cache_cancel,cache_clear,
    input wire cache_valid,output wire cache_ready,input wire [31:0] cache_result_epoch,cache_result_address,
    input wire [1023:0] cache_data,
    output wire out_valid,input wire out_ready,output wire [31:0] out_epoch,
    output wire [11:0] out_word,output wire [511:0] out_data,output wire out_last,
    output wire active,fault,output reg [3:0] fault_code,output reg pair_done,tile_done
);
    localparam IDLE=0,WAIT_CACHE=1,VIEW=2,OUTPUT_WAIT=3,FAILED=4,CLEAR=5,RECOVER_WAIT=6;
    reg [2:0] state;
    reg [31:0] epoch_q,address_q,table_q,elapsed,timeout_q;
    reg [1:0] context_q,shift_q;
    reg [3:0] first_x_q;
    reg [4:0] valid_x_q;
    reg [11:0] word_q;
    reg last_q,half_q;
    reg [1023:0] pair_q;
    wire running=state>=WAIT_CACHE&&state<=OUTPUT_WAIT;
    wire expired=running&&elapsed>=timeout_q;
    wire context_error,context_loading,cbr,cwr,ccr,iv_ready,ov;
    wire [2:0] context_error_code;
    wire [31:0] oe,token;
    wire ol;
    wire stop_work=cancel||expired||cache_fault||context_error;
    wire cfg_idle=state==IDLE&&!req_valid&&!cache_busy&&!cache_fault;
    wire config_busy=cfg_begin||cfg_word_valid||cfg_commit;
    assign cfg_begin_ready=cfg_idle&&cbr;
    assign cfg_word_ready=cfg_idle&&cwr;
    assign cfg_commit_ready=cfg_idle&&ccr;
    assign req_ready=rst_n&&state==IDLE&&store_valid&&!context_loading&&!config_busy&&!stop_work&&cache_command_ready;
    assign cache_command=rst_n&&state==IDLE&&store_valid&&!context_loading&&!config_busy&&!stop_work&&req_valid;
    assign cache_epoch=req_epoch;assign cache_address=req_address;assign cache_generation=req_source_generation;
    assign cache_cancel=rst_n&&(cancel||state==FAILED||running&&stop_work);
    assign cache_clear=rst_n&&state==CLEAR&&!cancel;
    assign cache_ready=rst_n&&state==WAIT_CACHE&&!stop_work;
    assign active=state!=IDLE;
    assign fault=state>=FAILED;
    wire [12:0] expected_token={1'b0,word_q}+half_q+1;
    wire expected_last=last_q&&half_q;
    wire bad_output=oe!=epoch_q||token!={19'd0,expected_token}||ol!=expected_last;
    assign out_valid=rst_n&&state==OUTPUT_WAIT&&ov&&!stop_work&&!bad_output;
    assign out_epoch=oe;assign out_word=word_q+half_q;assign out_last=ol;
    z100_native_view_context4 transform(.clk(clk),.rst_n(rst_n),.cancel(cancel||state>=FAILED||running&&stop_work),
        .cfg_begin(cfg_begin&&cfg_idle),.cfg_begin_ready(cbr),.cfg_epoch(cfg_epoch),.cfg_contexts(cfg_contexts),
        .cfg_word_valid(cfg_word_valid&&cfg_idle),.cfg_word_ready(cwr),.cfg_data(cfg_data),
        .cfg_commit(cfg_commit&&cfg_idle),.cfg_commit_ready(ccr),.store_valid(store_valid),.loading(context_loading),
        .error_valid(context_error),.error_code(context_error_code),
        .in_valid(state==VIEW&&!stop_work),.in_ready(iv_ready),.in_epoch(epoch_q),.in_token({19'd0,expected_token}),
        .in_table_epoch(table_q),.in_context(context_q),.in_source_first_x(first_x_q),.in_nearest_shift(shift_q),
        .in_channels(3'd4),.in_x_count(valid_x_q),.in_last(expected_last),.in_data(half_q ? pair_q[1023:512] : pair_q[511:0]),
        .out_valid(ov),.out_ready(out_ready&&state==OUTPUT_WAIT&&!stop_work&&!bad_output),
        .out_epoch(oe),.out_token(token),.out_last(ol),.out_data(out_data));
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;epoch_q<=0;address_q<=0;table_q<=0;elapsed<=0;timeout_q<=0;
            context_q<=0;shift_q<=0;first_x_q<=0;valid_x_q<=0;word_q<=0;last_q<=0;half_q<=0;
            pair_q<=0;fault_code<=0;pair_done<=0;tile_done<=0;
        end else begin
            pair_done<=0;tile_done<=0;
            if(running&&elapsed!=32'hffffffff)elapsed<=elapsed+1;
            if(state<FAILED&&stop_work)begin state<=FAILED;fault_code<=cancel ? 1 : expired ? 2 : cache_fault ? 3 : 4;end
            else case(state)
                IDLE:if(req_valid&&req_ready)begin
                    if(timeout_cycles==0||req_native_word[0]||req_epoch==0)begin state<=FAILED;fault_code<=5;end
                    else begin state<=WAIT_CACHE;epoch_q<=req_epoch;address_q<=req_address;table_q<=req_table_epoch;
                        context_q<=req_context;shift_q<=req_shift;first_x_q<=req_source_first_x;valid_x_q<=req_valid_x;
                        word_q<=req_native_word;last_q<=req_last;half_q<=0;elapsed<=0;timeout_q<=timeout_cycles;end
                end
                WAIT_CACHE:if(cache_valid&&cache_ready)begin
                    if(cache_result_epoch!=epoch_q||cache_result_address!=address_q)begin state<=FAILED;fault_code<=6;end
                    else begin pair_q<=cache_data;state<=VIEW;end
                end
                VIEW:if(iv_ready)state<=OUTPUT_WAIT;
                OUTPUT_WAIT:if(ov&&bad_output)begin state<=FAILED;fault_code<=7;end
                    else if(out_valid&&out_ready)begin
                        if(half_q)begin pair_done<=1;tile_done<=last_q;state<=IDLE;end
                        else begin half_q<=1;state<=VIEW;end
                    end
                FAILED:if(recover&&!cancel&&!cache_busy)state<=CLEAR;
                CLEAR:if(cancel)state<=FAILED;else state<=RECOVER_WAIT;
                RECOVER_WAIT:if(cancel)state<=FAILED;else if(!cache_busy&&!cache_fault)begin state<=IDLE;fault_code<=0;end
                default:begin state<=FAILED;fault_code<=8;end
            endcase
        end
    end
endmodule
`default_nettype wire
