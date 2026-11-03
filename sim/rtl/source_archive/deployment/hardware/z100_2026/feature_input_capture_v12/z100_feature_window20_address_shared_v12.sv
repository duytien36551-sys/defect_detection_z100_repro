// Isolated5x5-p2 admission: only first_x minimum and last_x maximum change.
`default_nettype none
// Private20site window adapter on two replicated two-read-port feature stores.
// Each physical bank owns two statically generated request slices. Site
// coordinates are shared, then each bank selects its one legal site per port.
module z100_feature_window20_address_shared_v12 (
    input wire clk, rst_n, cancel,
    input wire cfg_bank,read_bank,output wire read_idle,
    output wire load_owner_valid,load_owner_bank,
    output wire load_store_valid,load_loading,output wire [31:0] load_active_epoch,
    input wire cfg_begin,
    output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,
    input wire cfg_canonical_order,
    input wire [10:0] cfg_channels,
    input wire [9:0] cfg_height, cfg_width,
    input wire [31:0] cfg_word_epoch,
    input wire [12:0] cfg_word_address,
    input wire cfg_word_last,
    input wire cfg_word_valid,
    output wire cfg_word_ready,
    input wire [511:0] cfg_data,
    input wire cfg_commit,
    output wire cfg_commit_ready,
    output wire store_valid, loading,
    output wire [31:0] active_epoch,
    output wire error_valid,
    output wire [3:0] error_code,

    input wire window_valid,
    output wire window_ready,
    input wire [31:0] window_epoch,
    input wire [31:0] window_tag,
    input wire [13:0] window_row_address,
    input wire signed [11:0] window_first_x,
    input wire [10:0] window_input_width,
    input wire [10:0] window_output_remaining,
    input wire [4:0] window_sites,
    input wire [3:0] window_channel_mask,
    input wire window_stride_two,
    input wire window_y_valid,

    output wire out_valid,
    input wire out_ready,
    output wire [31:0] out_tag,
    output wire [79:0] out_mask,
    output wire [639:0] out_data
);
    reg fifo_head,fifo_tail;
    reg [1:0] fifo_count;
    reg q0_valid,q0_bank,q1_valid,q1_bank;
    wire ram_read_idle;wire [1:0] sv;
    reg [31:0] q0_epoch,q1_epoch,q0_tag,q1_tag;
    reg [3327:0] q0_addresses,q1_addresses;
    reg [255:0] q0_read_mask,q1_read_mask;
    reg [479:0] q0_map,q1_map;
    reg [79:0] q0_value_mask,q1_value_mask;
    reg [31:0] s1_tag;
    reg [479:0] s1_map;
    reg [79:0] s1_value_mask;
    reg window_error;
    reg descriptor_ok;

    wire ram_cfg_begin_ready, ram_req_ready, ram_error;
    wire fifo_full = (fifo_count == 2'd2);
    wire fifo_head_valid = fifo_head ? q1_valid : q0_valid;
    wire fifo_head_bank = fifo_head ? q1_bank : q0_bank;
    wire [31:0] fifo_head_epoch = fifo_head ? q1_epoch : q0_epoch;
    wire [3327:0] fifo_head_addresses = fifo_head ? q1_addresses : q0_addresses;
    wire [255:0] fifo_head_read_mask = fifo_head ? q1_read_mask : q0_read_mask;
    wire [31:0] fifo_head_tag = fifo_head ? q1_tag : q0_tag;
    wire [479:0] fifo_head_map = fifo_head ? q1_map : q0_map;
    wire [79:0] fifo_head_value_mask = fifo_head ? q1_value_mask : q0_value_mask;
    wire fifo_pop = fifo_head_valid && ram_req_ready;
    wire fifo_enqueue = window_valid && window_ready && descriptor_ok;
    wire fifo_capture = window_valid && !fifo_full;
    wire [3:0] ram_error_code;
    wire [2047:0] ram_data;
    wire [31:0] ram_out_epoch;
    wire [3327:0] request_addresses;
    wire [255:0] request_read_mask;
    wire [479:0] request_value_map;
    wire [79:0] request_value_mask;
    // Hold begin VALID while downstream is stalled; never feed READY back
    // into VALID. The lower store owns exclusive command handshakes.
    wire cfg_fifo_admitted = !(q0_valid && cfg_bank==q0_bank) &&
                             !(q1_valid && cfg_bank==q1_bank);
    wire ram_cfg_begin = cfg_begin && cfg_fifo_admitted;

    assign cfg_begin_ready = ram_cfg_begin_ready && cfg_fifo_admitted;
    assign read_idle=ram_read_idle&&(fifo_count==0);
    assign window_ready = rst_n && store_valid && !loading && !cancel &&
                          !(cfg_begin&&cfg_bank==read_bank) && !error_valid && !fifo_full;
    assign error_valid = window_error || ram_error;
    assign error_code = window_error ? 4'd1 : ram_error_code;
    assign out_tag = s1_tag;
    assign out_mask = s1_value_mask;

    z100_feature_banks_pingpong_writepipe_v7 store (
        .cfg_bank(cfg_bank),.read_bank(read_bank),.req_bank(fifo_head_bank),.read_idle(ram_read_idle),
        .load_owner_valid(load_owner_valid),.load_owner_bank(load_owner_bank),
        .load_store_valid(load_store_valid),.load_loading(load_loading),.load_active_epoch(load_active_epoch),.bank_store_valid(sv),
        .clk(clk), .rst_n(rst_n), .cancel(cancel), .cfg_begin(ram_cfg_begin),
        .cfg_begin_ready(ram_cfg_begin_ready), .cfg_canonical_order(cfg_canonical_order), .cfg_epoch(cfg_epoch),
        .cfg_channels(cfg_channels), .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_word_valid(cfg_word_valid), .cfg_word_ready(cfg_word_ready), .cfg_data(cfg_data),
        .cfg_word_epoch(cfg_word_epoch), .cfg_word_address(cfg_word_address), .cfg_word_last(cfg_word_last),
        .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .error_valid(ram_error), .error_code(ram_error_code), .store_valid(store_valid),
        .active_epoch(active_epoch), .loading(loading), .req_valid(fifo_head_valid),
        .req_ready(ram_req_ready), .req_epoch(fifo_head_epoch), .req_addresses(fifo_head_addresses),
        .req_mask(fifo_head_read_mask), .out_valid(out_valid), .out_ready(out_ready),
        .out_epoch(ram_out_epoch), .out_data(ram_data)
    );

    wire signed [12:0] input_width_extended = $signed({2'b00, window_input_width});
    wire signed [12:0] site_x [0:19];
    wire [14:0] site_address [0:19];
    wire site_readable [0:19];
    wire site_address_overflow [0:19];
    integer first_x, last_x, sites_int, width_int, step_x, descriptor_site;

    // These twelve adders are shared by all64 physical banks and48 gather
    // entries. A site is readable only when it is requested and in bounds.
    genvar site_index;
    generate for (site_index=0; site_index<20; site_index=site_index+1) begin : gen_site
        assign site_x[site_index] = $signed(window_first_x) +
            (window_stride_two ? (site_index * 2) : site_index);
        assign site_address[site_index] = {1'b0, window_row_address} +
            {6'd0, site_x[site_index][12:4]};
        assign site_readable[site_index] = (site_index < window_sites) && window_y_valid &&
            (site_x[site_index] >= 0) && (site_x[site_index] < input_width_extended);
        assign site_address_overflow[site_index] = site_readable[site_index] &&
            (site_address[site_index] >= 15'd4096);
    end endgenerate

    always @* begin
        first_x = $signed(window_first_x);
        sites_int = window_sites;
        width_int = window_input_width;
        step_x = window_stride_two ? 2 : 1;
        last_x = first_x + (sites_int-1)*step_x;
        descriptor_ok = (window_sites>=1 && window_sites<=20 &&
            window_sites<=window_output_remaining && window_input_width>=1 &&
            window_input_width<=640 && first_x>=-2 &&
            (window_channel_mask==1 || window_channel_mask==3 ||
             window_channel_mask==7 || window_channel_mask==15));
        if (last_x > width_int+1)
            descriptor_ok = 0;
        for (descriptor_site=0; descriptor_site<20; descriptor_site=descriptor_site+1)
            if (site_address_overflow[descriptor_site])
                descriptor_ok = 0;
    end

    // The request bus is generated with fixed slices. For stride1 a bank's
    // matching residue can occur once; for stride2 the second occurrence is
    // assigned to port1 after site7. The legal request is therefore one-hot.
    // Address geometry is identical for the four channel banks. Decode it
    // once per x residue and port; channel validity gates only the read mask.
    // Unmasked addresses are private payload and never issue a RAM read.
    genvar x_residue, read_port, address_channel;
    generate for (x_residue=0; x_residue<16; x_residue=x_residue+1) begin : gen_shared_address
        for (read_port=0; read_port<4; read_port=read_port+1) begin : gen_port
            reg [12:0] selected_address;
            reg selected;
            integer candidate_site;
            always @* begin
                selected_address=13'd0; selected=1'b0;
                for (candidate_site=0; candidate_site<20; candidate_site=candidate_site+1) begin
                    if (descriptor_ok && site_readable[candidate_site] &&
                        site_x[candidate_site][3:0]==x_residue &&
                        ((!window_stride_two && read_port==(candidate_site/16)) ||
                         (window_stride_two && read_port==(candidate_site/8)))) begin
                        selected_address=selected_address | site_address[candidate_site][12:0];
                        selected=1'b1;
                    end
                end
            end
            for (address_channel=0; address_channel<4; address_channel=address_channel+1) begin : gen_channel
                assign request_addresses[((address_channel*16+x_residue)*4+read_port)*13 +: 13]=selected_address;
                assign request_read_mask[(address_channel*16+x_residue)*4+read_port]=selected && window_channel_mask[address_channel];
            end
        end
    end endgenerate

    genvar channel_index, value_site;
    generate for (channel_index=0; channel_index<4; channel_index=channel_index+1) begin : gen_value_channel
        for (value_site=0; value_site<20; value_site=value_site+1) begin : gen_value_site
            localparam integer VALUE_INDEX = channel_index*20+value_site;
            wire valid_value = descriptor_ok && site_readable[value_site] &&
                               window_channel_mask[channel_index];
            wire [1:0] local_port=window_stride_two ? (value_site/8) : (value_site/16);
            wire [5:0] local_slot={site_x[value_site][3:0],local_port};
            assign request_value_map[VALUE_INDEX*6 +: 6] = valid_value ? local_slot : 6'd0;
            assign request_value_mask[VALUE_INDEX] = valid_value;
        end
    end endgenerate

    genvar value;
    generate for (value=0; value<80; value=value+1) begin : gen_gather
        assign out_data[value*8 +: 8] = s1_value_mask[value] ?
            ram_data[(value/20)*512 + s1_map[value*6 +: 6]*8 +: 8] : 8'd0;
    end endgenerate

    // Payload capture uses only input VALID and registered local capacity.
    // Semantic admission updates the compact FIFO state below; the bank
    // store READY advances only the compact head/tail/count state.
    always @(posedge clk) begin
        if (fifo_capture) begin
            if (fifo_tail) begin
                q1_epoch<=window_epoch;q1_tag<=window_tag;
                q1_addresses<=request_addresses;q1_read_mask<=request_read_mask;
                q1_map<=request_value_map;q1_value_mask<=request_value_mask;
            end else begin
                q0_epoch<=window_epoch;q0_tag<=window_tag;
                q0_addresses<=request_addresses;q0_read_mask<=request_read_mask;
                q0_map<=request_value_map;q0_value_mask<=request_value_mask;
            end
        end
        if (fifo_pop) begin
            s1_tag<=fifo_head_tag;
            s1_map<=fifo_head_map;
            s1_value_mask<=fifo_head_value_mask;
        end
    end
    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            fifo_head<=0;fifo_tail<=0;fifo_count<=0;
            q0_valid<=0;q0_bank<=0;q1_valid<=0;q1_bank<=0;window_error<=0;
        end else begin
            window_error<=0;
            if (fifo_enqueue) begin
                if (fifo_tail) begin q1_valid<=1;q1_bank<=read_bank;end
                else begin q0_valid<=1;q0_bank<=read_bank;end
                fifo_tail<=!fifo_tail;
            end
            if (fifo_pop) begin
                if (fifo_head) q1_valid<=0;
                else q0_valid<=0;
                fifo_head<=!fifo_head;
            end
            case ({fifo_enqueue,fifo_pop})
                2'b10: fifo_count<=fifo_count+1'b1;
                2'b01: fifo_count<=fifo_count-1'b1;
                default: fifo_count<=fifo_count;
            endcase
            if (window_valid && window_ready) begin
                if (!descriptor_ok) window_error<=1;
            end
            if (ram_error) begin
                fifo_head<=0;fifo_tail<=0;fifo_count<=0;
                q0_valid<=0;q1_valid<=0;
            end
        end
    end
endmodule
`default_nettype wire
