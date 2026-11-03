`default_nettype none
// Private four-channel x twelve-site window reader over feature_banks_v1.
// Each request selects one ky/kx tap. A controller must reorder weights in
// exactly the same four-channel order and keep each site group in one row.
module z100_feature_window (
    input wire clk, rst_n, cancel,
    input wire cfg_begin,
    output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,
    input wire [13:0] cfg_words,
    input wire cfg_word_valid,
    output wire cfg_word_ready,
    input wire [511:0] cfg_data,
    input wire cfg_commit,
    output wire cfg_commit_ready,
    output wire store_valid, loading,
    output wire [31:0] active_epoch,
    output wire error_valid,
    output wire [2:0] error_code,

    input wire window_valid,
    output wire window_ready,
    input wire [31:0] window_epoch,
    input wire [31:0] window_tag,
    input wire [13:0] window_row_address,
    input wire signed [11:0] window_first_x,
    input wire [10:0] window_input_width,
    input wire [10:0] window_output_remaining,
    input wire [3:0] window_sites,
    input wire [3:0] window_channel_mask,
    input wire window_stride_two,
    input wire window_y_valid,

    output wire out_valid,
    input wire out_ready,
    output wire [31:0] out_tag,
    output wire [47:0] out_mask,
    output wire [383:0] out_data
);
    reg s0_valid;
    reg [31:0] s0_epoch, s0_tag;
    reg [1663:0] s0_addresses;
    reg [127:0] s0_read_mask;
    reg [239:0] s0_map;
    reg [47:0] s0_value_mask;
    reg [31:0] s1_tag;
    reg [239:0] s1_map;
    reg [47:0] s1_value_mask;
    reg window_error;
    wire ram_cfg_begin_ready, ram_req_ready, ram_error;
    wire [2:0] ram_error_code;
    wire [1023:0] ram_data;
    wire [31:0] ram_out_epoch;
    wire ram_cfg_begin = cfg_begin && cfg_begin_ready;
    assign cfg_begin_ready = ram_cfg_begin_ready && !s0_valid;
    assign window_ready = rst_n && store_valid && !loading && !cancel &&
                          !cfg_begin && (!s0_valid || ram_req_ready);
    assign error_valid = window_error || ram_error;
    assign error_code = window_error ? 3'd1 : ram_error_code;
    assign out_tag = s1_tag;
    assign out_mask = s1_value_mask;

    z100_feature_banks store (
        .clk(clk), .rst_n(rst_n), .cancel(cancel), .cfg_begin(ram_cfg_begin),
        .cfg_begin_ready(ram_cfg_begin_ready), .cfg_epoch(cfg_epoch), .cfg_words(cfg_words),
        .cfg_word_valid(cfg_word_valid), .cfg_word_ready(cfg_word_ready), .cfg_data(cfg_data),
        .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .error_valid(ram_error), .error_code(ram_error_code), .store_valid(store_valid),
        .active_epoch(active_epoch), .loading(loading), .req_valid(s0_valid),
        .req_ready(ram_req_ready), .req_epoch(s0_epoch), .req_addresses(s0_addresses),
        .req_mask(s0_read_mask), .out_valid(out_valid), .out_ready(out_ready),
        .out_epoch(ram_out_epoch), .out_data(ram_data)
    );

    reg descriptor_ok;
    reg [1663:0] addresses;
    reg [127:0] read_mask;
    reg [239:0] value_map;
    reg [47:0] value_mask;
    integer c, site, x, bank, port_index, address, value_index;
    integer first_x, last_x, sites_int, width_int, step_x;
    always @* begin
        first_x=$signed(window_first_x);
        sites_int=window_sites;
        width_int=window_input_width;
        step_x=window_stride_two ? 2 : 1;
        last_x=first_x+(sites_int-1)*step_x;
        descriptor_ok = (window_sites>=1 && window_sites<=12 &&
            window_sites<=window_output_remaining && window_input_width>=1 &&
            window_input_width<=640 && first_x>=-1 &&
            (window_channel_mask==1 || window_channel_mask==3 ||
             window_channel_mask==7 || window_channel_mask==15));
        if (last_x > width_int)
            descriptor_ok = 0;
        addresses=0;
        read_mask=0;
        value_map=0;
        value_mask=0;
        x=0; bank=0; port_index=0; address=0; value_index=0;
        for(c=0;c<4;c=c+1) begin
            for(site=0;site<12;site=site+1) begin
                x=first_x+site*step_x;
                value_index=c*12+site;
                if(site<window_sites && window_channel_mask[c] && window_y_valid &&
                   x>=0 && x<window_input_width) begin
                    bank=c*16+(x & 15);
                    // Stride2 revisits a bank after8 sites. A missing padded
                    // first occurrence leaves port0 unused, which is legal.
                    port_index=bank*2+((window_stride_two && site>=8) ? 1 : 0);
                    address=window_row_address+(x>>4);
                    if(address>=8192) descriptor_ok=0;
                    addresses[port_index*13+:13]=address;
                    read_mask[port_index]=1;
                    // A channel lane only selects its own32 byte-read slots.
                    // Keep the channel-bank prefix static through the gather.
                    value_map[value_index*5+:5]=port_index & 31;
                    value_mask[value_index]=1;
                end
            end
        end
    end

    genvar value;
    generate for(value=0;value<48;value=value+1) begin : gen_gather
        assign out_data[value*8+:8] = s1_value_mask[value] ?
            ram_data[(value/12)*256+s1_map[value*5+:5]*8+:8] : 8'd0;
    end endgenerate

    always @(posedge clk) begin
        if(!rst_n || cancel) begin
            s0_valid<=0;
            s0_epoch<=0; s0_tag<=0;
            s0_addresses<=0; s0_read_mask<=0; s0_map<=0; s0_value_mask<=0;
            s1_tag<=0; s1_map<=0; s1_value_mask<=0;
            window_error<=0;
        end else begin
            window_error<=0;
            if(s0_valid && ram_req_ready) begin
                s0_valid<=0;
                s1_tag<=s0_tag;
                s1_map<=s0_map;
                s1_value_mask<=s0_value_mask;
            end
            if(window_valid && window_ready) begin
                if(!descriptor_ok) begin
                    s0_valid<=0;
                    window_error<=1;
                end else begin
                    s0_valid<=1;
                    s0_epoch<=window_epoch;
                    s0_tag<=window_tag;
                    s0_addresses<=addresses;
                    s0_read_mask<=read_mask;
                    s0_map<=value_map;
                    s0_value_mask<=value_mask;
                end
            end
            if(ram_error) s0_valid<=0;
        end
    end
endmodule
`default_nettype wire
