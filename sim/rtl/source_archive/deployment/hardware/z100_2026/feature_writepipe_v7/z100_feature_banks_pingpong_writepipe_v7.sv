`default_nettype none
// Two four-read RAM banks behind ONE shared window decoder/gather. The request
// bank travels with the decoder's S0 packet; response ownership is retained
// until retirement. Configuring another bank can overlap a read transaction.
module z100_feature_banks_pingpong_writepipe_v7 (
    input wire clk,rst_n,cancel,input wire cfg_bank,read_bank,req_bank,
    output wire read_idle,output reg load_owner_valid,load_owner_bank,
    output wire load_store_valid,load_loading,output wire [31:0] load_active_epoch,
    output wire [1:0] bank_store_valid,
    input wire cfg_begin,output wire cfg_begin_ready,input wire [31:0] cfg_epoch,
    input wire cfg_canonical_order,input wire [10:0] cfg_channels,input wire [9:0] cfg_height,cfg_width,
    input wire [31:0] cfg_word_epoch,input wire [12:0] cfg_word_address,input wire cfg_word_last,
    input wire cfg_word_valid,output wire cfg_word_ready,input wire [511:0] cfg_data,
    input wire cfg_commit,output wire cfg_commit_ready,
    output wire store_valid,loading,output wire [31:0] active_epoch,
    output wire error_valid,output wire [3:0] error_code,
    input wire req_valid,output wire req_ready,input wire [31:0] req_epoch,
    input wire [3327:0] req_addresses,input wire [255:0] req_mask,
    output wire out_valid,input wire out_ready,output wire [31:0] out_epoch,output wire [2047:0] out_data
);
    wire [1:0] cb_ready,cw_ready,cc_ready,sv,ld,err,rready,ovalid;
    wire [31:0] ae[0:1],oe[0:1];wire [3:0] ec[0:1];wire [2047:0] od[0:1];
    reg read_pending,response_bank_q,bookkeeping_error;
    wire enabled=rst_n&&!cancel&&!error_valid;
    wire cfg_exclusive=!(cfg_begin&&(cfg_word_valid||cfg_commit)||cfg_word_valid&&cfg_commit);
    wire request_admitted=!read_pending||req_bank==response_bank_q;
    wire response_bank=read_pending ? response_bank_q : req_bank;
    wire begin_read_conflict=req_valid&&req_bank==cfg_bank;
    wire cfg_request_conflict=(cfg_begin&&cfg_bank==req_bank)||
        (load_owner_valid&&(cfg_word_valid||cfg_commit)&&load_owner_bank==req_bank);
    assign error_valid=err[0]||err[1]||bookkeeping_error;
    assign error_code=bookkeeping_error ? 4'd15 : err[0] ? ec[0] : ec[1];
    assign read_idle=enabled&&!read_pending;
    assign cfg_begin_ready=enabled&&cfg_exclusive&&!load_owner_valid&&!begin_read_conflict&&
        !(read_pending&&cfg_bank==response_bank_q)&&cb_ready[cfg_bank];
    assign cfg_word_ready=enabled&&cfg_exclusive&&load_owner_valid&&cw_ready[load_owner_bank];
    assign cfg_commit_ready=enabled&&cfg_exclusive&&load_owner_valid&&cc_ready[load_owner_bank];
    assign store_valid=enabled&&sv[read_bank];assign loading=ld[read_bank];assign active_epoch=ae[read_bank];
    assign load_store_valid=enabled&&sv[load_owner_bank];assign load_loading=load_owner_valid&&ld[load_owner_bank];assign load_active_epoch=ae[load_owner_bank];
    assign bank_store_valid=sv;
    assign req_ready=enabled&&request_admitted&&!cfg_request_conflict&&rready[req_bank];
    assign out_valid=enabled&&read_pending&&ovalid[response_bank];
    assign out_epoch=oe[response_bank];assign out_data=od[response_bank];
    wire begin_fire=cfg_begin&&cfg_begin_ready;
    wire commit_fire=cfg_commit&&cfg_commit_ready;
    wire request_fire=req_valid&&req_ready;
    wire output_fire=out_valid&&out_ready;
    always @(posedge clk)begin
        if(!rst_n||cancel)begin load_owner_valid<=0;load_owner_bank<=0;read_pending<=0;response_bank_q<=0;bookkeeping_error<=0;end
        else begin
            if(begin_fire)begin load_owner_valid<=1;load_owner_bank<=cfg_bank;end
            if(commit_fire)load_owner_valid<=0;
            case({request_fire,output_fire})
                2'b10:begin if(read_pending)bookkeeping_error<=1;else read_pending<=1;end
                2'b01:read_pending<=0;
                default:begin end
            endcase
            if(request_fire&&!read_pending)response_bank_q<=req_bank;
        end
    end
    genvar b;
    generate for(b=0;b<2;b=b+1)begin:gen_bank
        z100_feature_banks_4read_writepipe_4k_v5 unit(.clk(clk),.rst_n(rst_n),.cancel(cancel),
            // VALID is qualified by input classes/ownership only, never READY.
            .cfg_begin(cfg_begin&&enabled&&cfg_exclusive&&!load_owner_valid&&!begin_read_conflict&&cfg_bank==b&&!(read_pending&&cfg_bank==response_bank_q)),.cfg_begin_ready(cb_ready[b]),
            .cfg_epoch(cfg_epoch),.cfg_canonical_order(cfg_canonical_order),.cfg_channels(cfg_channels),.cfg_height(cfg_height),.cfg_width(cfg_width),
            .cfg_word_epoch(cfg_word_epoch),.cfg_word_address(cfg_word_address),.cfg_word_last(cfg_word_last),
            .cfg_word_valid(cfg_word_valid&&enabled&&cfg_exclusive&&load_owner_valid&&load_owner_bank==b),.cfg_word_ready(cw_ready[b]),.cfg_word_data(cfg_data),
            .cfg_commit(cfg_commit&&enabled&&cfg_exclusive&&load_owner_valid&&load_owner_bank==b),.cfg_commit_ready(cc_ready[b]),
            .store_valid(sv[b]),.loading(ld[b]),.active_epoch(ae[b]),.error_valid(err[b]),.error_code(ec[b]),
            .req_valid(req_valid&&enabled&&request_admitted&&!cfg_request_conflict&&req_bank==b),.req_ready(rready[b]),
            .req_epoch(req_epoch),.req_addresses(req_addresses),.req_mask(req_mask),
            .out_valid(ovalid[b]),.out_ready(out_ready&&enabled&&read_pending&&response_bank==b),.out_epoch(oe[b]),.out_data(od[b]));
    end endgenerate
endmodule
`default_nettype wire
