// Standalone synchronous implementation fixture for resident-v3.
// The default profile exercises 27/144/2304/4091 taps with varying lane/site
// shapes, then reloads activations twice under the final persistent weight
// epoch. FAST_SMOKE keeps the same protocol and shape variation for XSim.
// Numeric acceptance remains in the independent all-output comparison bench.
module z100_tile_reuse_resident_v3_timing_top #(
    parameter integer FAST_SMOKE = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    output wire        monitor_valid,
    output wire [31:0] monitor_data,
    output wire        monitor_overflow,
    output wire [1:0]  monitor_site,
    output wire [4:0]  monitor_lane,
    output wire        monitor_last,
    output wire        monitor_ready,
    output wire [31:0] monitor_status
);
    localparam [31:0] SCHEMA = 32'h5a523301;
    localparam [3:0] ST_WEIGHT_BEGIN = 4'd0;
    localparam [3:0] ST_WEIGHT_DATA = 4'd1;
    localparam [3:0] ST_BIAS_DATA = 4'd2;
    localparam [3:0] ST_WEIGHT_COMMIT = 4'd3;
    localparam [3:0] ST_ACT_BEGIN = 4'd4;
    localparam [3:0] ST_ACT_DATA = 4'd5;
    localparam [3:0] ST_ACT_COMMIT = 4'd6;
    localparam [3:0] ST_RUN = 4'd7;
    localparam [3:0] ST_WAIT = 4'd8;
    localparam [3:0] ST_DONE = 4'd9;
    localparam [3:0] ST_FAILED = 4'd10;

    wire core_clk;
    BUFG clock_buffer (.I(clk), .O(core_clk));
    // The external reset is sampled twice before synchronous distribution.
    // Hold reset low for at least two core clocks. Arithmetic is unchanged.
    (* ASYNC_REG = "TRUE" *) reg reset_meta = 1'b0;
    (* ASYNC_REG = "TRUE" *) reg reset_local = 1'b0;
    always @(posedge core_clk) begin
        reset_meta <= rst_n;
        reset_local <= reset_meta;
    end

    reg [3:0] state = ST_WEIGHT_BEGIN;
    reg [1:0] shape_index = 2'd0;
    reg [11:0] tap_index = 12'd0;
    reg [31:0] activation_epoch = 32'd0;
    reg [7:0] run_target = 8'd0;
    reg last_shape_replay = 1'b0;
    reg [31:0] payload_lfsr = 32'h91e10da5;
    reg [31:0] ready_lfsr = 32'h6d2b79f5;
    reg [17:0] watchdog_cycles = 18'd0;
    reg [15:0] accepted_commands = 16'd0;
    reg [7:0] completed_runs = 8'd0;
    reg protocol_fault = 1'b0;
    reg scan_active = 1'b0;
    reg [4:0] scan_lane = 5'd0;

    reg cmd_valid;
    reg [3:0] cmd_opcode;
    reg [31:0] cmd_weight_epoch;
    reg [31:0] cmd_activation_epoch;
    reg [11:0] cmd_addr;
    reg [12:0] cmd_tap_count;
    reg [5:0] cmd_lane_count;
    reg [2:0] cmd_site_count;
    reg [3:0] cmd_site_mask;
    reg [1023:0] cmd_payload;

    wire cmd_ready;
    wire [31:0] schema_id;
    wire error_valid;
    wire [3:0] error_code;
    wire weight_valid;
    wire activation_valid;
    wire [31:0] active_weight_epoch;
    wire [31:0] active_activation_epoch;
    wire busy;
    wire core_out_valid;
    wire core_out_ready;
    wire [1:0] core_out_site;
    wire core_out_last;
    wire [5:0] core_out_lane_count;
    wire [1023:0] core_out_data;
    wire [31:0] core_out_overflow;

    function automatic [12:0] taps_for_shape(input [1:0] shape);
        begin
            if (FAST_SMOKE != 0) begin
                case (shape)
                    2'd0: taps_for_shape = 13'd7;
                    2'd1: taps_for_shape = 13'd12;
                    2'd2: taps_for_shape = 13'd19;
                    default: taps_for_shape = 13'd27;
                endcase
            end else begin
                case (shape)
                    2'd0: taps_for_shape = 13'd27;
                    2'd1: taps_for_shape = 13'd144;
                    2'd2: taps_for_shape = 13'd2304;
                    default: taps_for_shape = 13'd4091;
                endcase
            end
        end
    endfunction

    function automatic [5:0] lanes_for_shape(input [1:0] shape);
        begin
            case (shape)
                2'd0: lanes_for_shape = 6'd9;
                2'd1: lanes_for_shape = 6'd17;
                default: lanes_for_shape = 6'd32;
            endcase
        end
    endfunction

    function automatic [2:0] sites_for_shape(input [1:0] shape);
        begin
            case (shape)
                2'd0: sites_for_shape = 3'd1;
                2'd1: sites_for_shape = 3'd3;
                2'd2: sites_for_shape = 3'd2;
                default: sites_for_shape = 3'd4;
            endcase
        end
    endfunction

    function automatic [31:0] advance_lfsr(input [31:0] value);
        begin
            advance_lfsr = {value[30:0], value[31] ^ value[21] ^ value[1] ^ value[0]};
        end
    endfunction

    function automatic [255:0] make_weight_payload(
        input [31:0] seed,
        input [11:0] address
    );
        integer lane;
        begin
            for (lane = 0; lane < 32; lane = lane + 1)
                make_weight_payload[(lane * 8) +: 8] =
                    seed[((lane % 4) * 8) +: 8] ^ address[7:0] ^
                    (lane * 8'h13) ^ {4'd0, address[11:8]};
        end
    endfunction

    function automatic [31:0] make_activation_payload(
        input [31:0] seed,
        input [11:0] address
    );
        integer site;
        begin
            for (site = 0; site < 4; site = site + 1)
                make_activation_payload[(site * 8) +: 8] =
                    seed[(site * 8) +: 8] ^ address[7:0] ^
                    (site * 8'h2d) ^ {4'd0, address[11:8]};
        end
    endfunction

    function automatic [1023:0] make_bias_payload(input [31:0] seed);
        integer lane;
        begin
            for (lane = 0; lane < 32; lane = lane + 1)
                make_bias_payload[(lane * 32) +: 32] =
                    seed ^ (32'h9e3779b9 * (lane + 1)) ^ (lane << 19);
        end
    endfunction

    wire [31:0] weight_epoch_for_shape = {30'd0, shape_index} + 32'd1;
    wire [12:0] current_taps = taps_for_shape(shape_index);
    wire [5:0] current_lanes = lanes_for_shape(shape_index);
    wire [2:0] current_sites = sites_for_shape(shape_index);
    wire [3:0] current_site_mask = (4'b0001 << current_sites) - 1'b1;
    wire final_output_lane = ({1'b0, scan_lane} + 6'd1) == core_out_lane_count;

    always @* begin
        cmd_valid = 1'b0;
        cmd_opcode = 4'd0;
        cmd_weight_epoch = weight_epoch_for_shape;
        cmd_activation_epoch = 32'd0;
        cmd_addr = tap_index;
        cmd_tap_count = current_taps;
        cmd_lane_count = current_lanes;
        cmd_site_count = current_sites;
        cmd_site_mask = 4'd0;
        cmd_payload = 1024'd0;

        case (state)
            ST_WEIGHT_BEGIN: begin
                cmd_valid = 1'b1;
                cmd_opcode = 4'd1;
                cmd_addr = 12'd0;
            end
            ST_WEIGHT_DATA: begin
                cmd_valid = 1'b1;
                cmd_opcode = 4'd2;
                cmd_payload[255:0] = make_weight_payload(payload_lfsr, tap_index);
            end
            ST_BIAS_DATA: begin
                cmd_valid = 1'b1;
                cmd_opcode = 4'd3;
                cmd_addr = 12'd0;
                cmd_payload = make_bias_payload(payload_lfsr);
            end
            ST_WEIGHT_COMMIT: begin
                cmd_valid = 1'b1;
                cmd_opcode = 4'd4;
                cmd_addr = 12'd0;
            end
            ST_ACT_BEGIN: begin
                cmd_valid = 1'b1;
                cmd_opcode = 4'd5;
                cmd_activation_epoch = activation_epoch + 32'd1;
                cmd_addr = 12'd0;
            end
            ST_ACT_DATA: begin
                cmd_valid = 1'b1;
                cmd_opcode = 4'd6;
                cmd_activation_epoch = activation_epoch;
                cmd_site_mask = current_site_mask;
                cmd_payload[31:0] = make_activation_payload(payload_lfsr, tap_index);
            end
            ST_ACT_COMMIT: begin
                cmd_valid = 1'b1;
                cmd_opcode = 4'd7;
                cmd_activation_epoch = activation_epoch;
                cmd_addr = 12'd0;
            end
            ST_RUN: begin
                cmd_valid = 1'b1;
                cmd_opcode = 4'd8;
                cmd_activation_epoch = activation_epoch;
                cmd_addr = 12'd0;
            end
            default: begin end
        endcase
    end

    reg serial_valid = 1'b0;
    reg [31:0] serial_data;
    reg serial_overflow;
    reg [1:0] serial_site;
    reg [4:0] serial_lane;
    reg serial_last;
    wire serial_ready = ready_lfsr[2:0] != 3'b000;
    wire serial_can_accept = !serial_valid || serial_ready;
    wire raw_valid = scan_active && core_out_valid;
    wire raw_fire = raw_valid && serial_can_accept;
    reg [31:0] registered_status = 32'd0;
    assign monitor_valid = serial_valid;
    assign monitor_data = serial_data;
    assign monitor_overflow = serial_overflow;
    assign monitor_site = serial_site;
    assign monitor_lane = serial_lane;
    assign monitor_last = serial_last;
    assign monitor_ready = serial_valid && serial_ready;
    assign core_out_ready = raw_fire && final_output_lane;
    assign monitor_status = registered_status;

    always @(posedge core_clk) begin
        if (!reset_local) begin
            serial_valid <= 1'b0;
            registered_status <= 32'd0;
        end else begin
            registered_status <= {
                (state == ST_DONE), protocol_fault, weight_valid, activation_valid,
                busy, core_out_valid, monitor_valid, monitor_ready,
                completed_runs, accepted_commands
            };
            if (serial_can_accept) begin
                serial_valid <= raw_valid;
                if (raw_valid) begin
                    serial_data <= core_out_data[(scan_lane * 32) +: 32];
                    serial_overflow <= core_out_overflow[scan_lane];
                    serial_site <= core_out_site;
                    serial_lane <= scan_lane;
                    serial_last <= core_out_last && final_output_lane;
                end
            end
        end
    end

    always @(posedge core_clk) begin
        if (!reset_local) begin
            state <= ST_WEIGHT_BEGIN;
            shape_index <= 2'd0;
            tap_index <= 12'd0;
            activation_epoch <= 32'd0;
            run_target <= 8'd0;
            last_shape_replay <= 1'b0;
            payload_lfsr <= 32'h91e10da5;
            ready_lfsr <= 32'h6d2b79f5;
            watchdog_cycles <= 18'd0;
            accepted_commands <= 16'd0;
            completed_runs <= 8'd0;
            protocol_fault <= 1'b0;
            scan_active <= 1'b0;
            scan_lane <= 5'd0;
        end else begin
            if (ready_lfsr == 32'd0)
                ready_lfsr <= 32'h6d2b79f5;
            else
                ready_lfsr <= advance_lfsr(ready_lfsr);

            if (watchdog_cycles != 18'h3ffff)
                watchdog_cycles <= watchdog_cycles + 1'b1;
            if ((watchdog_cycles == 18'd200000) && (state != ST_DONE)) begin
                state <= ST_FAILED;
                protocol_fault <= 1'b1;
            end

            if ((schema_id != SCHEMA) || error_valid || (error_code != 4'd0))
                protocol_fault <= 1'b1;

            if (cmd_valid && cmd_ready) begin
                accepted_commands <= accepted_commands + 1'b1;
                payload_lfsr <= advance_lfsr(payload_lfsr);
                case (state)
                    ST_WEIGHT_BEGIN: begin tap_index <= 12'd0; state <= ST_WEIGHT_DATA; end
                    ST_WEIGHT_DATA: begin
                        if ({1'b0, tap_index} + 13'd1 == current_taps)
                            state <= ST_BIAS_DATA;
                        else
                            tap_index <= tap_index + 1'b1;
                    end
                    ST_BIAS_DATA: state <= ST_WEIGHT_COMMIT;
                    ST_WEIGHT_COMMIT: state <= ST_ACT_BEGIN;
                    ST_ACT_BEGIN: begin
                        tap_index <= 12'd0;
                        activation_epoch <= activation_epoch + 1'b1;
                        state <= ST_ACT_DATA;
                    end
                    ST_ACT_DATA: begin
                        if ({1'b0, tap_index} + 13'd1 == current_taps)
                            state <= ST_ACT_COMMIT;
                        else
                            tap_index <= tap_index + 1'b1;
                    end
                    ST_ACT_COMMIT: state <= ST_RUN;
                    ST_RUN: begin
                        run_target <= completed_runs + 1'b1;
                        state <= ST_WAIT;
                    end
                    default: begin end
                endcase
            end

            if (!scan_active && core_out_valid) begin
                scan_active <= 1'b1;
                scan_lane <= 5'd0;
            end else if (raw_fire) begin
                if (final_output_lane) begin
                    scan_active <= 1'b0;
                    scan_lane <= 5'd0;
                    if (core_out_last)
                        completed_runs <= completed_runs + 1'b1;
                end else begin
                    scan_lane <= scan_lane + 1'b1;
                end
            end

            if ((state == ST_WAIT) && (completed_runs >= run_target) &&
                !busy && !core_out_valid && !serial_valid) begin
                if (!weight_valid || (active_weight_epoch != weight_epoch_for_shape) ||
                    !activation_valid || (active_activation_epoch != activation_epoch)) begin
                    state <= ST_FAILED;
                    protocol_fault <= 1'b1;
                end else if (shape_index != 2'd3) begin
                    shape_index <= shape_index + 1'b1;
                    last_shape_replay <= 1'b0;
                    state <= ST_WEIGHT_BEGIN;
                end else if (!last_shape_replay) begin
                    last_shape_replay <= 1'b1;
                    state <= ST_ACT_BEGIN;
                end else begin
                    state <= ST_DONE;
                end
            end
        end
    end

    // No DONT_TOUCH or hierarchy preservation: generated commands, complete
    // arithmetic/RAM state, and every serialized output word stay live by use.
    z100_tile_reuse_resident_v3 #(.MAX_TAPS(4091)) core (
        .clk(core_clk), .rst_n(reset_local),
        .cmd_valid(cmd_valid), .cmd_ready(cmd_ready),
        .cmd_schema(SCHEMA), .cmd_opcode(cmd_opcode),
        .cmd_weight_epoch(cmd_weight_epoch), .cmd_activation_epoch(cmd_activation_epoch),
        .cmd_addr(cmd_addr), .cmd_tap_count(cmd_tap_count),
        .cmd_lane_count(cmd_lane_count), .cmd_site_count(cmd_site_count),
        .cmd_site_mask(cmd_site_mask), .cmd_payload(cmd_payload),
        .schema_id(schema_id), .error_valid(error_valid), .error_code(error_code),
        .weight_valid(weight_valid), .activation_valid(activation_valid),
        .active_weight_epoch(active_weight_epoch),
        .active_activation_epoch(active_activation_epoch), .busy(busy),
        .out_valid(core_out_valid), .out_ready(core_out_ready),
        .out_site(core_out_site), .out_last(core_out_last),
        .out_lane_count(core_out_lane_count), .out_data(core_out_data),
        .out_overflow(core_out_overflow)
    );
endmodule
