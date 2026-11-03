`default_nettype none
// Private four-channel x twelve-site window reader over feature_banks_v1.
// Each physical bank owns two statically generated request slices. Site
// coordinates are shared, then each bank selects its one legal site per port.
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
    wire [1663:0] request_addresses;
    wire [127:0] request_read_mask;
    wire [239:0] request_value_map;
    wire [47:0] request_value_mask;
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

    wire signed [12:0] input_width_extended = $signed({2'b00, window_input_width});
    wire signed [12:0] site_x [0:11];
    wire [14:0] site_address [0:11];
    wire site_readable [0:11];
    wire site_address_overflow [0:11];
    reg descriptor_ok;
    integer first_x, last_x, sites_int, width_int, step_x, descriptor_site;

    // These twelve adders are shared by all64 physical banks and48 gather
    // entries. A site is readable only when it is requested and in bounds.
    genvar site_index;
    generate for (site_index=0; site_index<12; site_index=site_index+1) begin : gen_site
        assign site_x[site_index] = $signed(window_first_x) +
            (window_stride_two ? (site_index * 2) : site_index);
        assign site_address[site_index] = {1'b0, window_row_address} +
            {6'd0, site_x[site_index][12:4]};
        assign site_readable[site_index] = (site_index < window_sites) && window_y_valid &&
            (site_x[site_index] >= 0) && (site_x[site_index] < input_width_extended);
        assign site_address_overflow[site_index] = site_readable[site_index] &&
            (site_address[site_index] >= 15'd8192);
    end endgenerate

    always @* begin
        first_x = $signed(window_first_x);
        sites_int = window_sites;
        width_int = window_input_width;
        step_x = window_stride_two ? 2 : 1;
        last_x = first_x + (sites_int-1)*step_x;
        descriptor_ok = (window_sites>=1 && window_sites<=12 &&
            window_sites<=window_output_remaining && window_input_width>=1 &&
            window_input_width<=640 && first_x>=-1 &&
            (window_channel_mask==1 || window_channel_mask==3 ||
             window_channel_mask==7 || window_channel_mask==15));
        if (last_x > width_int)
            descriptor_ok = 0;
        for (descriptor_site=0; descriptor_site<12; descriptor_site=descriptor_site+1)
            if (site_address_overflow[descriptor_site])
                descriptor_ok = 0;
    end

    // The request bus is generated with fixed slices. For stride1 a bank's
    // matching residue can occur once; for stride2 the second occurrence is
    // assigned to port1 after site7. The legal request is therefore one-hot.
    genvar physical_bank, read_port;
    generate for (physical_bank=0; physical_bank<64; physical_bank=physical_bank+1) begin : gen_bank
        localparam integer CHANNEL = physical_bank / 16;
        localparam integer X_RESIDUE = physical_bank % 16;
        for (read_port=0; read_port<2; read_port=read_port+1) begin : gen_port
            reg [12:0] selected_address;
            reg selected;
            integer candidate_site;
            always @* begin
                selected_address = 13'd0;
                selected = 1'b0;
                for (candidate_site=0; candidate_site<12; candidate_site=candidate_site+1) begin
                    if (descriptor_ok && site_readable[candidate_site] &&
                        window_channel_mask[CHANNEL] &&
                        site_x[candidate_site][3:0] == X_RESIDUE &&
                        ((!window_stride_two && read_port==0) ||
                         (window_stride_two && ((candidate_site>=8) == (read_port==1))))) begin
                        selected_address = selected_address | site_address[candidate_site][12:0];
                        selected = 1'b1;
                    end
                end
            end
            assign request_addresses[(physical_bank*2+read_port)*13 +: 13] = selected_address;
            assign request_read_mask[physical_bank*2+read_port] = selected;
        end
    end endgenerate

    genvar channel_index, value_site;
    generate for (channel_index=0; channel_index<4; channel_index=channel_index+1) begin : gen_value_channel
        for (value_site=0; value_site<12; value_site=value_site+1) begin : gen_value_site
            localparam integer VALUE_INDEX = channel_index*12+value_site;
            wire valid_value = descriptor_ok && site_readable[value_site] &&
                               window_channel_mask[channel_index];
            wire [4:0] local_slot = {site_x[value_site][3:0],
                                      (window_stride_two && value_site>=8)};
            assign request_value_map[VALUE_INDEX*5 +: 5] = valid_value ? local_slot : 5'd0;
            assign request_value_mask[VALUE_INDEX] = valid_value;
        end
    end endgenerate

    genvar value;
    generate for (value=0; value<48; value=value+1) begin : gen_gather
        assign out_data[value*8 +: 8] = s1_value_mask[value] ?
            ram_data[(value/12)*256 + s1_map[value*5 +: 5]*8 +: 8] : 8'd0;
    end endgenerate

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            s0_valid<=0;
            s0_epoch<=0; s0_tag<=0;
            s0_addresses<=0; s0_read_mask<=0; s0_map<=0; s0_value_mask<=0;
            s1_tag<=0; s1_map<=0; s1_value_mask<=0;
            window_error<=0;
        end else begin
            window_error<=0;
            if (s0_valid && ram_req_ready) begin
                s0_valid<=0;
                s1_tag<=s0_tag;
                s1_map<=s0_map;
                s1_value_mask<=s0_value_mask;
            end
            if (window_valid && window_ready) begin
                if (!descriptor_ok) begin
                    s0_valid<=0;
                    window_error<=1;
                end else begin
                    s0_valid<=1;
                    s0_epoch<=window_epoch;
                    s0_tag<=window_tag;
                    s0_addresses<=request_addresses;
                    s0_read_mask<=request_read_mask;
                    s0_map<=request_value_map;
                    s0_value_mask<=request_value_mask;
                end
            end
            if (ram_error) s0_valid<=0;
        end
    end
endmodule
`default_nettype wire
