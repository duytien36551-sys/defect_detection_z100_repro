`timescale 1ns/1ps
`default_nettype none
// Autonomous standalone timing fixture for the frozen native-window MAC.
// FAST_SMOKE shortens each tap-group count for XSim; implementation uses the
// default full 9/36/576/1024-group profiles. External reset must stay low for
// at least two core clocks; release is sampled through two reset flops.
// The monitor outputs have a one-cycle observation delay through one aligned stage.
module z100_native_mac_timing_top_v2 #(
    parameter integer FAST_SMOKE = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    output reg         monitor_valid,
    output reg         monitor_ready,
    output reg  [31:0] monitor_token,
    output reg  [31:0] monitor_data,
    output reg         monitor_overflow,
    output reg  [1:0]  monitor_site,
    output reg  [4:0]  monitor_lane,
    output reg  [5:0]  monitor_lanes,
    output reg         monitor_last,
    output reg  [31:0] monitor_status
);
    localparam [3:0] ST_WEIGHT_BEGIN  = 4'd0;
    localparam [3:0] ST_WEIGHT_DATA   = 4'd1;
    localparam [3:0] ST_BIAS_DATA     = 4'd2;
    localparam [3:0] ST_WEIGHT_COMMIT = 4'd3;
    localparam [3:0] ST_RUN           = 4'd4;
    localparam [3:0] ST_ACT_DATA      = 4'd5;
    localparam [3:0] ST_WAIT          = 4'd6;
    localparam [3:0] ST_DONE          = 4'd7;
    localparam [3:0] ST_FAILED        = 4'd8;

    wire core_clk;
    BUFG clock_buffer (.I(clk), .O(core_clk));

    // Reset is sampled, then synchronously distributed. No timing exception
    // is applied to either reset stage or to its path from rst_n.
    (* ASYNC_REG = "TRUE" *) reg reset_meta = 1'b0;
    (* ASYNC_REG = "TRUE" *) reg reset_local = 1'b0;
    always @(posedge core_clk) begin
        reset_meta  <= rst_n;
        reset_local <= reset_meta;
    end

    reg [3:0] state = ST_WEIGHT_BEGIN;
    reg [1:0] shape_index = 2'd0;
    reg replay_index = 1'b0;
    reg [10:0] weight_group = 11'd0;
    reg [10:0] activation_group = 11'd0;
    reg bubble_pending = 1'b0;
    reg [2:0] groups_since_bubble = 3'd0;
    reg [7:0] run_target = 8'd0;
    reg [20:0] watchdog_cycles = 21'd0;
    reg protocol_fault = 1'b0;
    reg [15:0] weight_load_count = 16'd0;
    reg [7:0] bias_load_count = 8'd0;
    reg [15:0] activation_accept_count = 16'd0;
    reg [15:0] input_bubble_count = 16'd0;

    function automatic [10:0] groups_for_shape(input [1:0] shape);
        begin
            if (FAST_SMOKE != 0) begin
                case (shape)
                    2'd0: groups_for_shape = 11'd3;
                    2'd1: groups_for_shape = 11'd4;
                    2'd2: groups_for_shape = 11'd6;
                    default: groups_for_shape = 11'd9;
                endcase
            end else begin
                case (shape)
                    2'd0: groups_for_shape = 11'd9;
                    2'd1: groups_for_shape = 11'd36;
                    2'd2: groups_for_shape = 11'd576;
                    default: groups_for_shape = 11'd1024;
                endcase
            end
        end
    endfunction

    function automatic [5:0] lanes_for_shape(input [1:0] shape);
        begin
            lanes_for_shape = (shape == 2'd0) ? 6'd16 : 6'd32;
        end
    endfunction

    function automatic [3:0] sites_for_shape(input [1:0] shape);
        begin
            sites_for_shape = (shape == 2'd1) ? 4'd3 : 4'd4;
        end
    endfunction

    function automatic signed [7:0] make_weight_byte(
        input [1:0] shape,
        input [10:0] group_index,
        input integer tap_index,
        input integer lane_index
    );
        integer value;
        reg [7:0] group_mix;
        reg [7:0] lane_mix;
        begin
            if (lane_index == 0)
                value = 1 + group_index[2:0] + tap_index * 2 + shape;
            else if (lane_index == 1)
                value = -1 - group_index[2:0] - tap_index * 2 - shape;
            else begin
                group_mix = group_index[7:0] ^ {5'd0, group_index[10:8]};
                lane_mix = lane_index[7:0] ^ {4'd0, tap_index[3:0]} ^ {6'd0, shape};
                value = group_mix ^ lane_mix;
            end
            make_weight_byte = value;
        end
    endfunction

    function automatic [7:0] make_activation_byte(
        input [1:0] shape,
        input replay,
        input [10:0] group_index,
        input integer tap_index,
        input integer site_index
    );
        reg [5:0] group_mix;
        reg [5:0] tap_mix;
        reg [5:0] site_mix;
        reg [5:0] run_mix;
        begin
            group_mix = group_index[5:0] ^ {group_index[8:6], group_index[10:8]};
            tap_mix = {tap_index[2:0], tap_index[2:0]};
            site_mix = {site_index[1:0], site_index[3:0]};
            run_mix = {replay, shape, 3'b101};
            make_activation_byte = 8'd1 + {2'd0, (group_mix ^ tap_mix ^ site_mix ^ run_mix)};
        end
    endfunction

    function automatic [31:0] make_bias_word(
        input [1:0] shape,
        input integer lane_index
    );
        integer value;
        begin
            if (lane_index == 0)
                make_bias_word = 32'h7fffffdf;
            else if (lane_index == 1)
                make_bias_word = 32'h80000020;
            else begin
                value = ((lane_index * 37 + shape * 101) & 2047) - 1024;
                make_bias_word = value;
            end
        end
    endfunction

    function automatic [31:0] token_for(input [1:0] shape, input replay);
        begin
            token_for = 32'h4e4d0001 + shape * 2 + replay;
        end
    endfunction

    wire [10:0] current_groups = groups_for_shape(shape_index);
    wire [5:0] current_lanes = lanes_for_shape(shape_index);
    wire [3:0] current_sites = sites_for_shape(shape_index);
    wire [31:0] current_epoch = {30'd0, shape_index} + 32'd1;

    reg cfg_begin = 1'b0;
    reg [31:0] cfg_epoch = 32'd0;
    reg [10:0] cfg_groups = 11'd0;
    reg cfg_weight_valid = 1'b0;
    reg [1023:0] cfg_weights = 1024'd0;
    reg cfg_bias_valid = 1'b0;
    reg [1023:0] cfg_bias = 1024'd0;
    reg cfg_commit = 1'b0;
    wire cfg_begin_ready;
    wire cfg_weight_ready;
    wire cfg_bias_ready;
    wire cfg_commit_ready;
    wire weights_valid;
    wire [31:0] weights_epoch;
    wire error_valid;
    wire [2:0] error_code;

    reg run_valid = 1'b0;
    reg [31:0] run_epoch = 32'd0;
    reg [31:0] run_token = 32'd0;
    reg [5:0] run_lanes = 6'd0;
    reg [3:0] run_sites = 4'd0;
    wire run_ready;

    reg act_valid = 1'b0;
    reg [31:0] act_token = 32'd0;
    reg act_last = 1'b0;
    reg [127:0] act_data = 128'd0;
    wire act_ready;
    wire out_valid;
    wire out_ready;
    wire [31:0] out_token;
    wire [3:0] out_site;
    wire out_last;
    wire [5:0] out_lanes;
    wire [1023:0] out_data;
    wire [31:0] out_overflow;
    wire busy = weights_valid && !run_ready;
    reg [7:0] completed_runs = 8'd0;
    reg serial_valid = 1'b0;

    z100_window_mac #(.SITES(4)) core (
        .clk(core_clk), .rst_n(reset_local), .cancel(1'b0),
        .cfg_begin(cfg_begin), .cfg_begin_ready(cfg_begin_ready),
        .cfg_epoch(cfg_epoch), .cfg_groups(cfg_groups),
        .cfg_weight_valid(cfg_weight_valid), .cfg_weight_ready(cfg_weight_ready),
        .cfg_weights(cfg_weights), .cfg_bias_valid(cfg_bias_valid),
        .cfg_bias_ready(cfg_bias_ready), .cfg_bias(cfg_bias),
        .cfg_commit(cfg_commit), .cfg_commit_ready(cfg_commit_ready),
        .weights_valid(weights_valid), .weights_epoch(weights_epoch),
        .error_valid(error_valid), .error_code(error_code),
        .run_valid(run_valid), .run_ready(run_ready), .run_epoch(run_epoch),
        .run_token(run_token), .run_lanes(run_lanes), .run_sites(run_sites),
        .act_valid(act_valid), .act_ready(act_ready), .act_token(act_token),
        .act_last(act_last), .act_data(act_data),
        .out_valid(out_valid), .out_ready(out_ready), .out_token(out_token),
        .out_site(out_site), .out_last(out_last), .out_lanes(out_lanes),
        .out_data(out_data), .out_overflow(out_overflow)
    );

    always @(posedge core_clk) begin : controller
        integer tap;
        integer lane;
        integer site;
        if (!reset_local) begin
            state <= ST_WEIGHT_BEGIN;
            shape_index <= 2'd0;
            replay_index <= 1'b0;
            weight_group <= 11'd0;
            activation_group <= 11'd0;
            bubble_pending <= 1'b0;
            groups_since_bubble <= 3'd0;
            run_target <= 8'd0;
            watchdog_cycles <= 21'd0;
            protocol_fault <= 1'b0;
            weight_load_count <= 16'd0;
            bias_load_count <= 8'd0;
            activation_accept_count <= 16'd0;
            input_bubble_count <= 16'd0;
            cfg_begin <= 1'b0;
            cfg_epoch <= 32'd0;
            cfg_groups <= 11'd0;
            cfg_weight_valid <= 1'b0;
            cfg_weights <= 1024'd0;
            cfg_bias_valid <= 1'b0;
            cfg_bias <= 1024'd0;
            cfg_commit <= 1'b0;
            run_valid <= 1'b0;
            run_epoch <= 32'd0;
            run_token <= 32'd0;
            run_lanes <= 6'd0;
            run_sites <= 4'd0;
            act_valid <= 1'b0;
            act_token <= 32'd0;
            act_last <= 1'b0;
            act_data <= 128'd0;
        end else begin
            if (watchdog_cycles != 21'h1fffff)
                watchdog_cycles <= watchdog_cycles + 1'b1;
            if ((watchdog_cycles == 21'd1000000) && state != ST_DONE) begin
                state <= ST_FAILED;
                protocol_fault <= 1'b1;
            end
            if (error_valid || error_code != 3'd0)
                protocol_fault <= 1'b1;

            case (state)
                ST_WEIGHT_BEGIN: begin
                    if (!cfg_begin) begin
                        cfg_epoch <= current_epoch;
                        cfg_groups <= current_groups;
                        cfg_begin <= 1'b1;
                    end else if (cfg_begin_ready) begin
                        cfg_begin <= 1'b0;
                        weight_group <= 11'd0;
                        cfg_weight_valid <= 1'b0;
                        state <= ST_WEIGHT_DATA;
                    end
                end
                ST_WEIGHT_DATA: begin
                    if (cfg_weight_valid) begin
                        if (cfg_weight_ready) begin
                            cfg_weight_valid <= 1'b0;
                            weight_load_count <= weight_load_count + 1'b1;
                            if (weight_group + 11'd1 == current_groups) begin
                                cfg_bias_valid <= 1'b0;
                                state <= ST_BIAS_DATA;
                            end else begin
                                weight_group <= weight_group + 1'b1;
                            end
                        end
                    end else begin
                        for (tap = 0; tap < 4; tap = tap + 1)
                            for (lane = 0; lane < 32; lane = lane + 1)
                                cfg_weights[tap*256 + lane*8 +: 8] <=
                                    make_weight_byte(shape_index, weight_group, tap, lane);
                        cfg_weight_valid <= 1'b1;
                    end
                end
                ST_BIAS_DATA: begin
                    if (cfg_bias_valid) begin
                        if (cfg_bias_ready) begin
                            cfg_bias_valid <= 1'b0;
                            bias_load_count <= bias_load_count + 1'b1;
                            state <= ST_WEIGHT_COMMIT;
                        end
                    end else begin
                        for (lane = 0; lane < 32; lane = lane + 1)
                            cfg_bias[lane*32 +: 32] <= make_bias_word(shape_index, lane);
                        cfg_bias_valid <= 1'b1;
                    end
                end
                ST_WEIGHT_COMMIT: begin
                    if (!cfg_commit)
                        cfg_commit <= 1'b1;
                    else if (cfg_commit_ready) begin
                        cfg_commit <= 1'b0;
                        state <= ST_RUN;
                    end
                end
                ST_RUN: begin
                    if (!run_valid) begin
                        run_epoch <= current_epoch;
                        run_token <= token_for(shape_index, replay_index);
                        run_lanes <= current_lanes;
                        run_sites <= current_sites;
                        run_valid <= 1'b1;
                    end else if (run_ready) begin
                        run_valid <= 1'b0;
                        run_target <= completed_runs + 1'b1;
                        activation_group <= 11'd0;
                        act_valid <= 1'b0;
                        bubble_pending <= 1'b0;
                        groups_since_bubble <= 3'd0;
                        state <= ST_ACT_DATA;
                    end
                end
                ST_ACT_DATA: begin
                    if (act_valid) begin
                        if (act_ready) begin
                            act_valid <= 1'b0;
                            activation_accept_count <= activation_accept_count + 1'b1;
                            if (activation_group + 11'd1 == current_groups) begin
                                state <= ST_WAIT;
                            end else begin
                                activation_group <= activation_group + 1'b1;
                                if (groups_since_bubble == 3'd6) begin
                                    bubble_pending <= 1'b1;
                                    groups_since_bubble <= 3'd0;
                                end else begin
                                    groups_since_bubble <= groups_since_bubble + 1'b1;
                                end
                            end
                        end
                    end else if (bubble_pending) begin
                        bubble_pending <= 1'b0;
                        input_bubble_count <= input_bubble_count + 1'b1;
                    end else begin
                        for (tap = 0; tap < 4; tap = tap + 1)
                            for (site = 0; site < 4; site = site + 1)
                                act_data[(tap*4 + site)*8 +: 8] <=
                                    make_activation_byte(shape_index, replay_index,
                                                        activation_group, tap, site);
                        act_token <= run_token;
                        act_last <= (activation_group + 11'd1 == current_groups);
                        act_valid <= 1'b1;
                    end
                end
                ST_WAIT: begin
                    if (completed_runs >= run_target && !busy && !out_valid && !serial_valid) begin
                        if (!replay_index) begin
                            replay_index <= 1'b1;
                            state <= ST_RUN;
                        end else if (shape_index != 2'd3) begin
                            shape_index <= shape_index + 1'b1;
                            replay_index <= 1'b0;
                            state <= ST_WEIGHT_BEGIN;
                        end else begin
                            state <= ST_DONE;
                        end
                    end
                end
                ST_DONE: begin end
                default: begin
                    state <= ST_FAILED;
                    protocol_fault <= 1'b1;
                end
            endcase
        end
    end

    reg [31:0] ready_lfsr = 32'h6d2b79f5;
    reg [31:0] serial_token = 32'd0;
    reg [31:0] serial_data = 32'd0;
    reg serial_overflow = 1'b0;
    reg [1:0] serial_site = 2'd0;
    reg [4:0] serial_lane = 5'd0;
    reg [5:0] serial_lanes = 6'd0;
    reg serial_last = 1'b0;
    reg [4:0] scan_lane = 5'd0;
    reg scan_active = 1'b0;
    wire serial_ready = ready_lfsr[2:0] != 3'b000;
    wire serial_can_accept = !serial_valid || serial_ready;
    wire serial_handshake = serial_valid && serial_ready;
    wire raw_valid = scan_active && out_valid;
    wire raw_fire = raw_valid && serial_can_accept;
    wire final_output_lane = scan_lane == 5'd31;
    wire core_out_ready = raw_fire && final_output_lane;
    reg [31:0] registered_status = 32'd0;

    assign out_ready = core_out_ready;
    always @(posedge core_clk) begin : monitor_observation_stage
        if (!reset_local) begin
            monitor_valid <= 1'b0;
            monitor_ready <= 1'b0;
            monitor_token <= 32'd0;
            monitor_data <= 32'd0;
            monitor_overflow <= 1'b0;
            monitor_site <= 2'd0;
            monitor_lane <= 5'd0;
            monitor_lanes <= 6'd0;
            monitor_last <= 1'b0;
            monitor_status <= 32'd0;
        end else begin
            monitor_valid <= serial_valid;
            monitor_ready <= serial_handshake;
            monitor_token <= serial_token;
            monitor_data <= serial_data;
            monitor_overflow <= serial_overflow;
            monitor_site <= serial_site;
            monitor_lane <= serial_lane;
            monitor_lanes <= serial_lanes;
            monitor_last <= serial_last;
            monitor_status <= registered_status;
        end
    end

    always @(posedge core_clk) begin : output_serializer
        if (!reset_local) begin
            ready_lfsr <= 32'h6d2b79f5;
            serial_valid <= 1'b0;
            serial_token <= 32'd0;
            serial_data <= 32'd0;
            serial_overflow <= 1'b0;
            serial_site <= 2'd0;
            serial_lane <= 5'd0;
            serial_lanes <= 6'd0;
            serial_last <= 1'b0;
            scan_lane <= 5'd0;
            scan_active <= 1'b0;
            completed_runs <= 8'd0;
            registered_status <= 32'd0;
        end else begin
            ready_lfsr <= {ready_lfsr[30:0],
                ready_lfsr[31] ^ ready_lfsr[21] ^ ready_lfsr[1] ^ ready_lfsr[0]};
            if (ready_lfsr == 32'd0)
                ready_lfsr <= 32'h6d2b79f5;

            registered_status <= {
                (state == ST_DONE), protocol_fault, weights_valid, busy,
                out_valid, serial_valid, serial_handshake, 1'b0,
                completed_runs, activation_accept_count
            };

            if (serial_can_accept) begin
                serial_valid <= raw_valid;
                if (raw_valid) begin
                    serial_token <= out_token;
                    serial_data <= out_data[(scan_lane * 32) +: 32];
                    serial_overflow <= out_overflow[scan_lane];
                    serial_site <= out_site[1:0];
                    serial_lane <= scan_lane;
                    serial_lanes <= out_lanes;
                    serial_last <= out_last && final_output_lane;
                end
            end

            if (!scan_active && out_valid) begin
                scan_active <= 1'b1;
                scan_lane <= 5'd0;
            end else if (raw_fire) begin
                if (final_output_lane) begin
                    scan_active <= 1'b0;
                    scan_lane <= 5'd0;
                    if (out_last)
                        completed_runs <= completed_runs + 1'b1;
                end else begin
                    scan_lane <= scan_lane + 1'b1;
                end
            end
        end
    end
endmodule
`default_nettype wire
