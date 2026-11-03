`default_nettype none
module z100_shared_pool_fixture (
    input wire clk,rst_n,cancel,
    input wire cfg_begin,output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,
    input wire [10:0] cfg_channels,input wire [9:0] cfg_height,cfg_width,
    input wire cfg_word_valid,output wire cfg_word_ready,
    input wire [31:0] cfg_word_epoch,input wire [12:0] cfg_word_address,
    input wire cfg_word_last,input wire [511:0] cfg_data,
    input wire cfg_commit,output wire cfg_commit_ready,
    output wire store_valid,loading,output wire [31:0] active_epoch,
    input wire job_valid,output wire job_ready,
    input wire [31:0] job_epoch,
    input wire [10:0] job_channels,input wire [9:0] job_height,job_width,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,output wire [12:0] out_address,
    output wire [511:0] out_data,output wire out_last,
    output reg done,output reg error_valid,output reg [3:0] error_code,
    output wire active
);
    reg [10:0] pending_c,loaded_c;
    reg [9:0] pending_h,pending_w,loaded_h,loaded_w;
    wire wv,wr,wov,window_reply_ready,wcancel,fw_error;
    wire [31:0] we,wt,ot;wire [13:0] wa;wire signed [11:0] wx;
    wire [3:0] wc,fw_code;wire wy;wire [79:0] mask;wire [639:0] data;
    wire fbr,fwr,fcr;wire admission=!active&&!job_valid;
    assign cfg_begin_ready=fbr&&admission;assign cfg_word_ready=fwr&&admission;assign cfg_commit_ready=fcr&&admission;
    always @(posedge clk)begin
        if(!rst_n||cancel)begin pending_c<=0;pending_h<=0;pending_w<=0;loaded_c<=0;loaded_h<=0;loaded_w<=0;end
        else begin
            if(cfg_begin&&cfg_begin_ready)begin pending_c<=cfg_channels;pending_h<=cfg_height;pending_w<=cfg_width;end
            if(cfg_commit&&cfg_commit_ready)begin loaded_c<=pending_c;loaded_h<=pending_h;loaded_w<=pending_w;end
        end
    end
    z100_feature_window20_pool5 feature_window(.clk(clk),.rst_n(rst_n),.cancel(wcancel),
        .cfg_begin(cfg_begin&&admission),.cfg_begin_ready(fbr),.cfg_epoch(cfg_epoch),.cfg_channels(cfg_channels),.cfg_height(cfg_height),.cfg_width(cfg_width),
        .cfg_word_valid(cfg_word_valid&&admission),.cfg_word_ready(fwr),.cfg_word_epoch(cfg_word_epoch),.cfg_word_address(cfg_word_address),.cfg_word_last(cfg_word_last),
        .cfg_data(cfg_data),.cfg_commit(cfg_commit&&admission),.cfg_commit_ready(fcr),.store_valid(store_valid),.loading(loading),.active_epoch(active_epoch),.error_valid(fw_error),.error_code(fw_code),
        .window_valid(wv),.window_ready(wr),.window_epoch(we),.window_tag(wt),.window_row_address(wa),.window_first_x(wx),.window_input_width(11'd20),
        .window_output_remaining(11'd20),.window_sites(5'd20),.window_channel_mask(wc),.window_stride_two(1'b0),.window_y_valid(wy),
        .out_valid(wov),.out_ready(window_reply_ready),.out_tag(ot),.out_mask(mask),.out_data(data));
    z100_maxpool_window20 consumer(.clk(clk),.rst_n(rst_n),.cancel(cancel),.store_valid(store_valid),.loading(loading),.active_epoch(active_epoch),
        .loaded_channels(loaded_c),.loaded_height(loaded_h),.loaded_width(loaded_w),.fw_error(fw_error),
        .window_valid(wv),.window_ready(wr),.window_epoch(we),.window_request_tag(wt),.window_row_address(wa),.window_first_x(wx),.window_channel_mask(wc),.window_y_valid(wy),.window_cancel(wcancel),
        .window_out_valid(wov),.window_out_ready(window_reply_ready),.window_tag(ot),.window_mask(mask),.window_data(data),
        .job_valid(job_valid),.job_ready(job_ready),.job_epoch(job_epoch),.job_channels(job_channels),.job_height(job_height),.job_width(job_width),
        .out_valid(out_valid),.out_ready(out_ready),.out_epoch(out_epoch),.out_address(out_address),.out_data(out_data),.out_last(out_last),.done(done),.error_valid(error_valid),.error_code(error_code),.active(active));
endmodule
`default_nettype wire
