`default_nettype none
// One tile: <=64 resident channel8 templates, native group32/y/x/pair order.
// Address increments replace spatial multipliers. Dispatch completion does NOT
// mean cache/transform/store completion. Owning ingress must drain on cancel;
// this component has no AXI pins and cannot reset or clear the external reader.
(* use_dsp="no" *)
module z100_native_pair_sequencer (
    input wire clk,rst_n,
    input wire cfg_begin,output wire cfg_begin_ready,
    input wire [9:0] cfg_channels,cfg_height,cfg_width,
    input wire [31:0] cfg_table_epoch,
    input wire cfg_valid,output wire cfg_ready,
    input wire [31:0] cfg_source_address,cfg_region_begin,cfg_source_generation,cfg_row_stride,cfg_x_stride,
    input wire [32:0] cfg_region_end,
    input wire [1:0] cfg_context,cfg_shift,
    input wire cfg_commit,output wire cfg_commit_ready,output wire store_valid,
    input wire start,output wire start_ready,input wire [31:0] frame_epoch,timeout_cycles,
    input wire cancel,clear_fault,downstream_quiescent,
    output wire active,output wire fault,output reg [3:0] fault_code,output reg dispatch_done,
    output wire req_valid,input wire req_ready,
    output wire [31:0] req_epoch,req_address,req_source_generation,req_table_epoch,
    output wire [1:0] req_context,req_shift,
    output wire [3:0] req_source_first_x,output wire [4:0] req_valid_x,
    output wire [11:0] req_native_word,output wire req_last
);
    localparam EMPTY=0,CONFIG=1,READY=2,FETCH=3,ISSUE=4,FAILED=5;
    reg [2:0] state;
    reg [6:0] pair_count,loaded;
    reg [9:0] height_q,width_q,y_q;
    reg [5:0] xwords_q,x_q,group_q,slot_q;
    reg [12:0] words_q;
    reg [11:0] output_q;
    reg [31:0] table_epoch_q,epoch_q,timeout_q,elapsed;
    // Template RAM is unreset. CONFIG initializes every admitted entry, and
    // commit cannot expose a partially populated tile. Mutable addresses are
    // scoped to this single dispatch; another run requires a fresh config.
    reg [32:0] addresses[0:63],row_addresses[0:63];
    reg [31:0] regions_begin[0:63],generations[0:63],row_strides[0:63],x_strides[0:63];
    reg [32:0] regions_end[0:63];
    reg [1:0] contexts[0:63],shifts[0:63];
    reg [32:0] addr_q,row_q,end_q;
    reg [31:0] begin_q,generation_q,row_stride_q,x_stride_q;
    reg [1:0] context_q,shift_q;
    wire running=state==FETCH||state==ISSUE;
    wire expired=running&&elapsed>=timeout_q;
    wire stop_work=cancel||expired;
    wire [10:0] cfg_xwords=({1'b0,cfg_width}+11'd15)>>4;
    wire [31:0] cfg_words=(cfg_channels>>2)*cfg_height*cfg_xwords;
    wire bad_geometry=cfg_channels==0||cfg_channels>512||cfg_channels[2:0]!=0||
        cfg_height==0||cfg_height>640||cfg_width==0||cfg_width>640||cfg_table_epoch==0||cfg_words>4096;
    wire bad_template=cfg_source_address[6:0]!=0||cfg_region_begin[6:0]!=0||cfg_region_end[6:0]!=0||
        cfg_region_end>33'h100000000||{1'b0,cfg_region_begin}>=cfg_region_end||
        {1'b0,cfg_source_address}<{1'b0,cfg_region_begin}||{1'b0,cfg_source_address}+128>cfg_region_end||
        cfg_source_generation==0||cfg_row_stride==0||cfg_x_stride==0||cfg_row_stride[6:0]!=0||
        cfg_x_stride[6:0]!=0||cfg_shift>2;
    wire range_good=addr_q>={1'b0,begin_q}&&addr_q+33'd128<=end_q&&addr_q<33'h100000000;
    wire row_end=x_q+1==xwords_q;
    wire repeat_x_end=shift_q==0||shift_q==1&&x_q[0]||shift_q==2&&x_q[1:0]==3;
    wire repeat_y_end=shift_q==0||shift_q==1&&y_q[0]||shift_q==2&&y_q[1:0]==3;
    wire final_slot=({1'b0,slot_q}+1==pair_count)||slot_q[1:0]==3;
    wire [10:0] remaining_x={1'b0,width_q}-({5'd0,x_q}<<4);
    assign cfg_begin_ready=rst_n&&(state==EMPTY||state==READY)&&downstream_quiescent&&!cancel&&!start;
    assign cfg_ready=rst_n&&state==CONFIG&&loaded<pair_count&&!cancel&&!cfg_commit;
    assign cfg_commit_ready=rst_n&&state==CONFIG&&loaded==pair_count&&!cancel&&!cfg_valid;
    assign store_valid=state==READY;
    assign start_ready=rst_n&&state==READY&&downstream_quiescent&&!cancel&&!cfg_begin;
    assign active=running;
    assign fault=state==FAILED;
    assign req_valid=rst_n&&state==ISSUE&&!stop_work&&range_good;
    assign req_epoch=epoch_q;assign req_address=addr_q[31:0];assign req_source_generation=generation_q;
    assign req_table_epoch=table_epoch_q;assign req_context=context_q;assign req_shift=shift_q;
    assign req_source_first_x=shift_q==0 ? 4'd0 : shift_q==1 ? {x_q[0],3'd0} : {x_q[1:0],2'd0};
    assign req_valid_x=remaining_x>=16 ? 5'd16 : remaining_x[4:0];
    assign req_native_word=output_q;assign req_last={1'b0,output_q}+13'd2==words_q;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=EMPTY;pair_count<=0;loaded<=0;height_q<=0;width_q<=0;y_q<=0;
            xwords_q<=0;x_q<=0;group_q<=0;slot_q<=0;words_q<=0;output_q<=0;
            table_epoch_q<=0;epoch_q<=0;timeout_q<=0;elapsed<=0;fault_code<=0;dispatch_done<=0;
            addr_q<=0;row_q<=0;end_q<=0;begin_q<=0;generation_q<=0;row_stride_q<=0;x_stride_q<=0;context_q<=0;shift_q<=0;
        end else begin
            dispatch_done<=0;
            if(running&&elapsed!=32'hffffffff)elapsed<=elapsed+1;
            if(cancel&&state!=EMPTY&&state!=FAILED)begin state<=FAILED;fault_code<=2;end
            else if(expired)begin state<=FAILED;fault_code<=3;end
            else case(state)
                EMPTY,READY:begin
                    if(cfg_begin&&cfg_begin_ready)begin
                        if(bad_geometry)begin state<=FAILED;fault_code<=1;end
                        else begin state<=CONFIG;loaded<=0;pair_count<=cfg_channels>>3;height_q<=cfg_height;
                            width_q<=cfg_width;xwords_q<=cfg_xwords[5:0];words_q<=cfg_words[12:0];table_epoch_q<=cfg_table_epoch;end
                    end else if(start&&start_ready)begin
                        if(frame_epoch==0||timeout_cycles==0)begin state<=FAILED;fault_code<=1;end
                        else begin state<=FETCH;epoch_q<=frame_epoch;timeout_q<=timeout_cycles;elapsed<=0;
                            y_q<=0;x_q<=0;group_q<=0;slot_q<=0;output_q<=0;end
                    end
                end
                CONFIG:begin
                    if(cfg_valid&&cfg_ready)begin
                        if(bad_template)begin state<=FAILED;fault_code<=4;end
                        else begin
                            addresses[loaded[5:0]]<={1'b0,cfg_source_address};row_addresses[loaded[5:0]]<={1'b0,cfg_source_address};
                            regions_begin[loaded[5:0]]<=cfg_region_begin;regions_end[loaded[5:0]]<=cfg_region_end;
                            generations[loaded[5:0]]<=cfg_source_generation;row_strides[loaded[5:0]]<=cfg_row_stride;
                            x_strides[loaded[5:0]]<=cfg_x_stride;contexts[loaded[5:0]]<=cfg_context;shifts[loaded[5:0]]<=cfg_shift;
                            loaded<=loaded+1;
                        end
                    end
                    if(cfg_commit&&cfg_commit_ready)state<=READY;
                end
                FETCH:begin
                    addr_q<=addresses[slot_q];row_q<=row_addresses[slot_q];begin_q<=regions_begin[slot_q];end_q<=regions_end[slot_q];
                    generation_q<=generations[slot_q];row_stride_q<=row_strides[slot_q];x_stride_q<=x_strides[slot_q];
                    context_q<=contexts[slot_q];shift_q<=shifts[slot_q];state<=ISSUE;
                end
                ISSUE:if(!range_good)begin state<=FAILED;fault_code<=5;end
                    else if(req_valid&&req_ready)begin
                        if(req_last)begin dispatch_done<=1;state<=EMPTY;end
                        else begin
                            output_q<=output_q+2;state<=FETCH;
                            if(row_end)begin
                                addresses[slot_q]<=row_q+(repeat_y_end ? {1'b0,row_stride_q} : 33'd0);
                                if(repeat_y_end)row_addresses[slot_q]<=row_q+{1'b0,row_stride_q};
                            end else if(repeat_x_end)addresses[slot_q]<=addr_q+{1'b0,x_stride_q};
                            if(final_slot)begin
                                if(row_end)begin
                                    x_q<=0;
                                    if(y_q+1==height_q)begin y_q<=0;group_q<=group_q+4;slot_q<=group_q+4;end
                                    else begin y_q<=y_q+1;slot_q<=group_q;end
                                end else begin x_q<=x_q+1;slot_q<=group_q;end
                            end else slot_q<=slot_q+1;
                        end
                    end
                FAILED:if(clear_fault&&!cancel&&downstream_quiescent)begin state<=EMPTY;fault_code<=0;end
                default:begin state<=FAILED;fault_code<=6;end
            endcase
        end
    end
endmodule
`default_nettype wire
