`default_nettype none
// One reserved materialized tensor, one in-flight whole-channel row tile.
// Publication requires exact nonoverlapping row coverage and downstream AXI
// quiescence at each successful tile completion. No payload RAM or AXI reset.
// Instantiate/bind per live destination slot; external graph owner supplies
// consumer quiescence before releasing a published tensor.
(* use_dsp="no" *)
module z100_native_tensor_commit_bounded_v2 #(parameter integer MAX_ROWS=640) (
    input wire clk,rst_n,abort,recover,io_quiescent,source_readers_quiescent,
    input wire allocate_valid,output wire allocate_ready,
    input wire [31:0] allocate_epoch,allocate_generation,allocate_address,
    input wire [15:0] allocate_tensor_id,
    input wire [10:0] allocate_channels,input wire [9:0] allocate_height,allocate_width,
    input wire tile_valid,output wire tile_ready,
    input wire [31:0] tile_epoch,tile_generation,input wire [15:0] tile_tensor_id,
    input wire [9:0] tile_first_row,tile_height,
    input wire completion_valid,output wire completion_ready,
    input wire [31:0] completion_epoch,completion_generation,input wire [15:0] completion_tensor_id,
    input wire [9:0] completion_first_row,completion_height,input wire completion_success,
    input wire release_valid,output wire release_ready,
    output wire active,fault,output reg [3:0] fault_code,
    output wire source_committed,output wire tile_pending,
    output wire [31:0] source_epoch,source_generation,source_address,source_bytes,
    output wire [15:0] source_tensor_id,
    output wire [10:0] source_channels,covered_rows,
    output wire [9:0] source_height,source_width,
    output reg publication_pulse
);
    localparam EMPTY=0,BUILDING=1,PUBLISHED=2,FAILED=3;
    reg [1:0] state;
    reg [31:0] epoch_q,generation_q,address_q,bytes_q,last_epoch,last_generation;
    reg [15:0] tensor_q;
    reg [10:0] channels_q,covered;
    reg [9:0] height_q,width_q,pending_first,pending_height;
    reg pending;
    initial if(MAX_ROWS<1||MAX_ROWS>640)$fatal(1,"Commit row capacity contract");
    reg [MAX_ROWS-1:0] completed_rows;
    wire [31:0] cfg_words=((({21'd0,allocate_channels}+3)>>2)*allocate_height)*(({22'd0,allocate_width}+15)>>4);
    wire [32:0] cfg_end={1'b0,allocate_address}+({1'b0,cfg_words}<<6);
    wire identity_fresh=allocate_epoch>last_epoch||allocate_epoch==last_epoch&&allocate_generation>last_generation;
    wire allocation_good=allocate_epoch!=0&&allocate_generation!=0&&identity_fresh&&allocate_address[5:0]==0&&
        allocate_channels>0&&allocate_channels<=1024&&allocate_height>0&&allocate_height<=MAX_ROWS&&
        allocate_width>0&&allocate_width<=640&&cfg_end<=33'h100000000;
    wire [10:0] tile_end={1'b0,tile_first_row}+{1'b0,tile_height};
    reg rows_clear;
    integer row,update_row;
    always @*begin
        rows_clear=1;
        for(row=0;row<MAX_ROWS;row=row+1)
            if(row>=tile_first_row&&row<tile_end&&completed_rows[row])rows_clear=0;
    end
    wire tile_good=tile_epoch==epoch_q&&tile_generation==generation_q&&tile_tensor_id==tensor_q&&
        tile_height!=0&&tile_end<={1'b0,height_q}&&rows_clear;
    wire completion_good=pending&&completion_success&&completion_epoch==epoch_q&&completion_generation==generation_q&&
        completion_tensor_id==tensor_q&&completion_first_row==pending_first&&completion_height==pending_height;
    assign allocate_ready=rst_n&&state==EMPTY&&io_quiescent&&!abort;
    assign tile_ready=rst_n&&state==BUILDING&&!pending&&io_quiescent&&!abort&&!completion_valid;
    assign completion_ready=rst_n&&state==BUILDING&&io_quiescent&&!abort&&!tile_valid;
    assign release_ready=rst_n&&state==PUBLISHED&&!pending&&io_quiescent&&source_readers_quiescent&&!abort&&!tile_valid&&!completion_valid;
    assign active=state!=EMPTY;assign fault=state==FAILED;
    assign source_committed=rst_n&&state==PUBLISHED&&!abort;
    assign tile_pending=pending;
    assign source_epoch=epoch_q;assign source_generation=generation_q;assign source_tensor_id=tensor_q;
    assign source_address=address_q;assign source_bytes=bytes_q;
    assign source_channels=channels_q;assign source_height=height_q;assign source_width=width_q;assign covered_rows=covered;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=EMPTY;epoch_q<=0;generation_q<=0;address_q<=0;bytes_q<=0;last_epoch<=0;last_generation<=0;tensor_q<=0;
            channels_q<=0;covered<=0;height_q<=0;width_q<=0;pending_first<=0;pending_height<=0;pending<=0;
            completed_rows<=0;fault_code<=0;publication_pulse<=0;
        end else begin
            publication_pulse<=0;
            if(abort&&state!=EMPTY)begin state<=FAILED;fault_code<=2;end
            else case(state)
                EMPTY:if(allocate_valid&&allocate_ready)begin
                    if(!allocation_good)begin state<=FAILED;fault_code<=1;end
                    else begin
                        state<=BUILDING;epoch_q<=allocate_epoch;generation_q<=allocate_generation;tensor_q<=allocate_tensor_id;
                        address_q<=allocate_address;bytes_q<=cfg_words<<6;channels_q<=allocate_channels;height_q<=allocate_height;width_q<=allocate_width;
                        last_epoch<=allocate_epoch;last_generation<=allocate_generation;covered<=0;pending<=0;completed_rows<=0;
                    end
                end
                BUILDING:begin
                    if(tile_valid&&tile_ready)begin
                        if(!tile_good)begin state<=FAILED;fault_code<=3;end
                        else begin pending<=1;pending_first<=tile_first_row;pending_height<=tile_height;end
                    end
                    if(completion_valid&&completion_ready)begin
                        if(!completion_good)begin state<=FAILED;fault_code<=4;end
                        else begin
                            pending<=0;covered<=covered+pending_height;
                            for(update_row=0;update_row<MAX_ROWS;update_row=update_row+1)
                                if(update_row>=pending_first&&update_row<({1'b0,pending_first}+{1'b0,pending_height}))completed_rows[update_row]<=1;
                            if(covered+pending_height==height_q)begin state<=PUBLISHED;publication_pulse<=1;end
                        end
                    end
                end
                PUBLISHED:if(tile_valid||completion_valid)begin state<=FAILED;fault_code<=5;end
                    else if(release_valid&&release_ready)begin state<=EMPTY;covered<=0;completed_rows<=0;pending<=0;end
                FAILED:if(recover&&io_quiescent&&source_readers_quiescent)begin
                    state<=EMPTY;covered<=0;completed_rows<=0;pending<=0;fault_code<=0;
                end
            endcase
        end
    end
endmodule
`default_nettype wire
