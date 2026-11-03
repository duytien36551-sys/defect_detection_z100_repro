`default_nettype none
// Narrow queued control plane for reusable published tensor contexts.
// Opcodes: allocate, tile reserve, B-complete tile, read acquire, read release,
// tensor release, abort, recover. BUSY is an explicit response; caller retries.
// Read leases must be acquired before AR and released after real IO drain.
// This module does not reset AXI or infer hardware quiescence from intent.
module z100_native_tensor_slots_bounded_v2 #(parameter integer SLOTS=7)(
    input wire clk,rst_n,input wire [SLOTS-1:0] io_quiescent,
    input wire cmd_valid,output wire cmd_ready,input wire [2:0] cmd_opcode,cmd_slot,
    input wire [31:0] cmd_tag,cmd_epoch,cmd_generation,cmd_address,
    input wire [15:0] cmd_tensor_id,input wire [10:0] cmd_channels,
    input wire [9:0] cmd_height,cmd_width,cmd_first_row,cmd_tile_height,input wire cmd_success,
    output wire response_valid,input wire response_ready,output reg [31:0] response_tag,
    output reg [2:0] response_slot,output reg [3:0] response_code,
    output wire [SLOTS-1:0] committed_slots,fault_slots,active_slots,
    input wire [2:0] query_slot,output reg query_committed,query_active,query_fault,
    output reg [7:0] query_readers,output reg [31:0] query_epoch,query_generation,query_address,query_bytes,
    output reg [15:0] query_tensor_id,output reg [10:0] query_channels,query_covered_rows,
    output reg [9:0] query_height,query_width
);
    localparam IDLE=0,EXECUTE=1,CHECK=2,RESPONSE=3;
    localparam OK=0,BAD_SLOT=1,BAD_IDENTITY=2,BUSY=3,LEDGER_FAULT=4,REF_OVERFLOW=5,REF_UNDERFLOW=6,BAD_STATE=7;
    reg [1:0] state;
    reg [2:0] opcode_q,slot_q;
    reg [31:0] tag_q,epoch_q,generation_q,address_q;
    reg [15:0] tensor_q;reg [10:0] channels_q;
    reg [9:0] height_q,width_q,first_q,tile_height_q;
    reg success_q;
    reg [7:0] references[0:SLOTS-1];
    wire [SLOTS-1:0] ar,tr,cr,rr;
    wire [31:0] epochs[0:SLOTS-1],generations[0:SLOTS-1],addresses[0:SLOTS-1],sizes[0:SLOTS-1];
    wire [15:0] tensors[0:SLOTS-1];
    wire [10:0] channels[0:SLOTS-1],covered[0:SLOTS-1];
    wire [9:0] heights[0:SLOTS-1],widths[0:SLOTS-1];
    wire selected_valid=slot_q<SLOTS;
    wire selected_identity=selected_valid&&epoch_q==epochs[slot_q]&&generation_q==generations[slot_q]&&tensor_q==tensors[slot_q];
    assign cmd_ready=rst_n&&state==IDLE;
    assign response_valid=rst_n&&state==RESPONSE;
    initial if(SLOTS<1||SLOTS>7)$fatal(1,"Tensor slot count contract");
    genvar g;
    generate for(g=0;g<SLOTS;g=g+1)begin:gen_slot
        wire issue=state==EXECUTE&&slot_q==g;
        localparam integer MAX_ROWS=g==0 ? 640 : g==1 ? 320 : g==2 ? 160 : g==3 ? 80 : g==4 ? 80 : g==5 ? 40 : 20;
        z100_native_tensor_commit_bounded_v2 #(.MAX_ROWS(MAX_ROWS)) ledger(.clk(clk),.rst_n(rst_n),
            .abort(issue&&opcode_q==6&&selected_identity),
            .recover(issue&&opcode_q==7&&selected_identity),
            .io_quiescent(io_quiescent[g]),.source_readers_quiescent(references[g]==0),
            .allocate_valid(issue&&opcode_q==0),.allocate_ready(ar[g]),
            .allocate_epoch(epoch_q),.allocate_generation(generation_q),.allocate_address(address_q),.allocate_tensor_id(tensor_q),
            .allocate_channels(channels_q),.allocate_height(height_q),.allocate_width(width_q),
            .tile_valid(issue&&opcode_q==1&&active_slots[g]&&!committed_slots[g]&&!fault_slots[g]),.tile_ready(tr[g]),
            .tile_epoch(epoch_q),.tile_generation(generation_q),.tile_tensor_id(tensor_q),.tile_first_row(first_q),.tile_height(tile_height_q),
            .completion_valid(issue&&opcode_q==2&&active_slots[g]&&!committed_slots[g]&&!fault_slots[g]),.completion_ready(cr[g]),
            .completion_epoch(epoch_q),.completion_generation(generation_q),.completion_tensor_id(tensor_q),
            .completion_first_row(first_q),.completion_height(tile_height_q),.completion_success(success_q),
            .release_valid(issue&&opcode_q==5&&selected_identity),.release_ready(rr[g]),
            .active(active_slots[g]),.fault(fault_slots[g]),.fault_code(),.source_committed(committed_slots[g]),.tile_pending(),
            .source_epoch(epochs[g]),.source_generation(generations[g]),.source_address(addresses[g]),.source_bytes(sizes[g]),
            .source_tensor_id(tensors[g]),.source_channels(channels[g]),.covered_rows(covered[g]),
            .source_height(heights[g]),.source_width(widths[g]),.publication_pulse());
    end endgenerate
    always @*begin
        query_active=0;query_committed=0;query_fault=0;query_readers=0;query_epoch=0;query_generation=0;query_address=0;
        query_bytes=0;query_tensor_id=0;query_channels=0;query_covered_rows=0;query_height=0;query_width=0;
        if(query_slot<SLOTS)begin
            query_active=active_slots[query_slot];query_committed=committed_slots[query_slot];query_fault=fault_slots[query_slot];
            query_readers=references[query_slot];query_epoch=epochs[query_slot];query_generation=generations[query_slot];
            query_address=addresses[query_slot];query_bytes=sizes[query_slot];query_tensor_id=tensors[query_slot];
            query_channels=channels[query_slot];query_covered_rows=covered[query_slot];query_height=heights[query_slot];query_width=widths[query_slot];
        end
    end
    integer n;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;opcode_q<=0;slot_q<=0;tag_q<=0;epoch_q<=0;generation_q<=0;address_q<=0;tensor_q<=0;channels_q<=0;
            height_q<=0;width_q<=0;first_q<=0;tile_height_q<=0;success_q<=0;response_tag<=0;response_slot<=0;response_code<=0;
            for(n=0;n<SLOTS;n=n+1)references[n]<=0;
        end else case(state)
            IDLE:if(cmd_valid&&cmd_ready)begin
                opcode_q<=cmd_opcode;slot_q<=cmd_slot;tag_q<=cmd_tag;epoch_q<=cmd_epoch;generation_q<=cmd_generation;
                address_q<=cmd_address;tensor_q<=cmd_tensor_id;channels_q<=cmd_channels;height_q<=cmd_height;width_q<=cmd_width;
                first_q<=cmd_first_row;tile_height_q<=cmd_tile_height;success_q<=cmd_success;state<=EXECUTE;
            end
            EXECUTE:begin
                response_tag<=tag_q;response_slot<=slot_q;response_code<=OK;state<=CHECK;
                if(!selected_valid)response_code<=BAD_SLOT;
                else case(opcode_q)
                    0:if(!ar[slot_q])response_code<=BUSY;
                    1:if(!tr[slot_q])response_code<=BUSY;
                    2:if(!cr[slot_q])response_code<=BUSY;
                    3:if(!selected_identity)response_code<=BAD_IDENTITY;
                        else if(!committed_slots[slot_q])response_code<=BAD_STATE;
                        else if(references[slot_q]==255)response_code<=REF_OVERFLOW;
                        else references[slot_q]<=references[slot_q]+1;
                    4:if(!selected_identity)response_code<=BAD_IDENTITY;
                        else if(references[slot_q]==0)response_code<=REF_UNDERFLOW;
                        else if(!io_quiescent[slot_q])response_code<=BUSY;
                        else references[slot_q]<=references[slot_q]-1;
                    5:if(!selected_identity)response_code<=BAD_IDENTITY;
                        else if(!rr[slot_q])response_code<=BUSY;
                    6:if(!selected_identity)response_code<=BAD_IDENTITY;
                        else if(!active_slots[slot_q])response_code<=BAD_STATE;
                    7:if(!selected_identity)response_code<=BAD_IDENTITY;
                        else if(!fault_slots[slot_q])response_code<=BAD_STATE;
                        else if(!io_quiescent[slot_q]||references[slot_q]!=0)response_code<=BUSY;
                endcase
            end
            CHECK:begin
                if(selected_valid&&response_code==OK&&opcode_q<=2&&fault_slots[slot_q])response_code<=LEDGER_FAULT;
                state<=RESPONSE;
            end
            RESPONSE:if(response_ready)state<=IDLE;
        endcase
    end
endmodule
`default_nettype wire
