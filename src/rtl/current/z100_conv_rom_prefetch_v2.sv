`default_nettype none
// Model-bound Conv plan ROM scheduler.  This module owns metadata only: the
// source lease, destination reservation, child I/O and drained recovery remain
// owned by its caller.
(* use_dsp = "no" *)
module z100_conv_rom_prefetch_v2 #(
    parameter MAP_FILE = "conv_event_map.hex",
    parameter TILE_FILE = "conv_tiles.hex",
    parameter [31:0] MODEL_CRC = 32'd2213989717
)(
    input wire clk,
    input wire rst_n,
    input wire cancel,
    input wire recover,
    input wire recovery_drained,

    input wire cmd_valid,
    output wire cmd_ready,
    input wire [31:0] cmd_epoch,
    input wire [7:0] cmd_event,
    input wire [31:0] cmd_model_crc,
    input wire [31:0] cmd_job_base,
    input wire [31:0] cmd_token_base,
    input wire [31:0] cmd_tag_base,
    input wire cmd_first_bank,

    input wire source_leased,
    input wire destination_reserved,

    output wire load_valid,
    input wire load_ready,
    output wire load_bank,
    output wire [31:0] load_job_tag,
    output wire [9:0] load_input_y,
    output wire [9:0] load_input_rows,
    input wire load_done,
    input wire load_committed,
    input wire load_fault,
    input wire [31:0] load_epoch,
    input wire load_done_bank,

    output wire tile_valid,
    input wire tile_ready,
    output wire tile_bank,
    output wire [31:0] tile_job_tag,
    output wire [31:0] tile_token_base,
    output wire [31:0] tile_tag_base,
    output wire [9:0] tile_input_y,
    output wire [9:0] tile_input_rows,
    output wire [9:0] tile_output_y,
    output wire [9:0] tile_output_rows,
    input wire tile_done,
    input wire tile_fault,
    input wire [31:0] tile_done_epoch,
    input wire [31:0] tile_done_job,
    input wire tile_done_bank,

    input wire load_quiet,
    input wire tile_write_quiet,
    input wire all_io_quiet,
    input wire admit_ok,

    output reg producer_context_valid,
    output reg [15:0] producer_cin,
    output reg [15:0] producer_input_height,
    output reg [15:0] producer_input_width,
    output reg [15:0] producer_cout,
    output reg [15:0] producer_output_height,
    output reg [15:0] producer_output_width,
    output reg [15:0] producer_kernel,
    output reg [15:0] producer_stride,
    output reg [15:0] producer_padding,
    output reg [15:0] producer_parameter_first,
    output reg [7:0] producer_event,

    output wire [31:0] active_epoch,
    output wire active,
    output reg done,
    output wire fault,
    output wire [3:0] fault_code,
    output wire child_cancel,
    output wire needs_drain,
    output wire [7:0] committed_tiles
);
    localparam [3:0] ST_IDLE       = 4'd0;
    localparam [3:0] ST_REQ_FIRST  = 4'd1;
    localparam [3:0] ST_WAIT_FIRST = 4'd2;
    localparam [3:0] ST_ADMIT      = 4'd3;
    localparam [3:0] ST_DESCRIPTOR = 4'd4;
    localparam [3:0] ST_REQ_NEXT   = 4'd5;
    localparam [3:0] ST_WAIT_NEXT  = 4'd6;
    localparam [3:0] ST_DRAIN      = 4'd7;
    localparam [3:0] ST_FAILED     = 4'd8;
    // periph_flat_v3: WAIT captures the ROM result into r_* registers, CHK
    // evaluates the checks from those registers into f_* flags, VRF acts on
    // the flags. A bad response raises fault_q plus a one-cycle bad_pulse_q,
    // which replaces the old same-cycle response_bad_now in every cancel term.
    // Cost: two extra cycles per ROM descriptor (<=189 per event).
    localparam [3:0] ST_CHK_FIRST  = 4'd9;
    localparam [3:0] ST_VRF_FIRST  = 4'd10;
    localparam [3:0] ST_CHK_NEXT   = 4'd11;
    localparam [3:0] ST_VRF_NEXT   = 4'd12;

    reg [3:0] state_q;
    reg fault_q;
    reg [3:0] fault_code_q;
    reg [31:0] cmd_epoch_q, cmd_job_base_q, cmd_token_base_q, cmd_tag_base_q;
    reg [31:0] cmd_model_crc_q;
    reg [7:0] cmd_event_q, tile_count_q;
    reg cmd_first_bank_q;
    reg [9:0] expected_output_y_q;

    reg [31:0] descriptor_epoch_q, descriptor_runs_q, descriptor_windows_q;
    reg [7:0] descriptor_index_q;
    reg [9:0] descriptor_input_y_q, descriptor_input_rows_q;
    reg [9:0] descriptor_output_y_q, descriptor_output_rows_q;

    wire rom_request_valid;
    wire rom_request_ready;
    wire rom_result_valid;
    wire rom_result_ready;
    wire rom_result_error;
    wire [31:0] rom_result_epoch, rom_result_tag;
    wire [7:0] rom_result_event, rom_result_tile, rom_result_tile_count;
    wire [207:0] rom_result_geometry;
    wire [15:0] rom_result_parameter_first;
    wire [31:0] rom_result_runs, rom_result_windows;
    wire [7:0] rom_request_tile;
    wire [7:0] controller_next_descriptor;

    wire controller_cmd_ready;
    wire controller_descriptor_ready;
    wire controller_load_valid, controller_tile_valid;
    wire controller_child_cancel, controller_active, controller_needs_drain;
    wire controller_done, controller_fault;
    wire [3:0] controller_fault_code;
    wire [31:0] controller_epoch;
    wire [7:0] controller_committed_tiles;

    reg [31:0] r_epoch, r_tag, r_runs, r_windows;
    reg [7:0] r_event, r_tile, r_tile_count;
    reg r_error;
    reg [207:0] r_geometry;
    reg [15:0] r_parameter_first;
    reg bad_pulse_q;
    wire [15:0] response_cin          = r_geometry[15:0];
    wire [15:0] response_input_height = r_geometry[31:16];
    wire [15:0] response_input_width  = r_geometry[47:32];
    wire [15:0] response_input_y      = r_geometry[63:48];
    wire [15:0] response_input_rows   = r_geometry[79:64];
    wire [15:0] response_output_y     = r_geometry[95:80];
    wire [15:0] response_output_rows  = r_geometry[111:96];
    wire [15:0] response_output_height= r_geometry[127:112];
    wire [15:0] response_output_width = r_geometry[143:128];
    wire [15:0] response_cout         = r_geometry[159:144];
    wire [15:0] response_kernel       = r_geometry[175:160];
    wire [15:0] response_stride       = r_geometry[191:176];
    wire [15:0] response_padding      = r_geometry[207:192];
    // The downstream producer/consumer contract uses bounded channel and
    // shape encodings. Widen before adding so parameter range wrap is rejected.
    wire [16:0] response_parameter_groups = ({1'b0,response_cout}+17'd31)>>5;
    wire [16:0] response_parameter_end = {1'b0,r_parameter_first}+
                                         response_parameter_groups;
    wire response_consumer_contract_bad = response_cin>16'd1024 ||
                                          response_cout>16'd1024 ||
                                          (response_kernel!=16'd1 && response_kernel!=16'd3) ||
                                          (response_stride!=16'd1 && response_stride!=16'd2) ||
                                          response_padding>16'd1 ||
                                          response_parameter_end>17'd173;
    wire [16:0] response_input_end = {1'b0,response_input_y}+{1'b0,response_input_rows};
    wire [16:0] response_output_end = {1'b0,response_output_y}+{1'b0,response_output_rows};
    wire [32:0] response_job_end = {1'b0,cmd_job_base_q}+{25'd0,r_tile_count}-33'd1;
    wire response_identity_bad = r_epoch!=cmd_epoch_q ||
                                 r_tag!=cmd_job_base_q ||
                                 r_event!=cmd_event_q ||
                                 r_tile!=(state_q==ST_CHK_FIRST ? 8'd0 : controller_next_descriptor);
    wire response_payload_bad = r_error || response_identity_bad ||
                                response_consumer_contract_bad ||
                                r_tile_count==0 || r_tile_count>8'd189 ||
                                r_runs==0 || r_windows<r_runs ||
                                response_cin==0 || response_input_height==0 || response_input_height>640 ||
                                response_input_width==0 || response_input_width>640 ||
                                response_input_rows==0 || response_input_end>response_input_height ||
                                response_output_rows==0 || response_output_height==0 || response_output_height>640 ||
                                response_output_width==0 || response_output_width>640 ||
                                response_cout==0 || response_kernel==0 || response_stride==0 ||
                                response_padding>response_kernel || response_output_end>response_output_height;
    // CHK registers three flag groups from the captured r_* record; VRF ORs
    // them. response_bad_now is a registered one-cycle pulse after VRF.
    reg f_payload_q, f_first_q, f_ctx_q;
    wire response_first_extra = response_output_y!=0 ||
                              (r_tile_count==1 ? response_output_end!=response_output_height :
                                                 response_output_end>=response_output_height) ||
                              response_job_end>33'h0ffffffff;
    wire response_ctx_extra = r_tile_count!=tile_count_q ||
                                r_parameter_first!=producer_parameter_first ||
                                response_cin!=producer_cin ||
                                response_input_height!=producer_input_height ||
                                response_input_width!=producer_input_width ||
                                response_cout!=producer_cout ||
                                response_output_height!=producer_output_height ||
                                response_output_width!=producer_output_width ||
                                response_kernel!=producer_kernel ||
                                response_stride!=producer_stride ||
                                response_padding!=producer_padding ||
                                response_output_y!=expected_output_y_q ||
                                (r_tile+8'd1==tile_count_q ? response_output_end!=producer_output_height :
                                                             response_output_end>=producer_output_height);
    wire vrf_first_bad = f_payload_q || f_first_q;
    wire vrf_next_bad  = f_payload_q || f_ctx_q;
    wire response_bad_now = bad_pulse_q;
    wire controller_cancel = (cancel && state_q!=ST_IDLE && state_q!=ST_FAILED) ||
                             response_bad_now ||
                             ((!source_leased || !destination_reserved) &&
                              state_q!=ST_IDLE && state_q!=ST_FAILED);
    wire rom_cancel = cancel || fault_q || response_bad_now ||
                      ((!source_leased || !destination_reserved) &&
                       state_q!=ST_IDLE && state_q!=ST_FAILED);
    wire descriptor_valid = state_q==ST_DESCRIPTOR && !fault_q && !cancel &&
                            source_leased && destination_reserved;
    wire descriptor_handshake = descriptor_valid && controller_descriptor_ready;
    wire rom_response_state = state_q==ST_WAIT_FIRST || state_q==ST_WAIT_NEXT;
    wire quiet_drained = recovery_drained && all_io_quiet && load_quiet && tile_write_quiet;

    assign rom_request_valid = state_q==ST_REQ_FIRST || state_q==ST_REQ_NEXT;
    assign rom_request_tile = state_q==ST_REQ_FIRST ? 8'd0 : controller_next_descriptor;
    assign rom_result_ready = rom_response_state;

    z100_conv_plan_rom #(
        .MAP_FILE(MAP_FILE),
        .TILE_FILE(TILE_FILE),
        .MODEL_CRC(MODEL_CRC)
    ) u_plan_rom (
        .clk(clk), .rst_n(rst_n), .cancel(rom_cancel),
        .request_valid(rom_request_valid), .request_ready(rom_request_ready),
        .request_epoch(cmd_epoch_q), .request_tag(cmd_job_base_q),
        .request_model_crc(cmd_model_crc_q), .request_event(cmd_event_q),
        .request_tile(rom_request_tile),
        .result_valid(rom_result_valid), .result_ready(rom_result_ready),
        .result_epoch(rom_result_epoch), .result_tag(rom_result_tag),
        .result_event(rom_result_event), .result_tile(rom_result_tile),
        .result_error(rom_result_error), .result_geometry(rom_result_geometry),
        .result_parameter_first(rom_result_parameter_first),
        .result_tile_count(rom_result_tile_count), .result_runs(rom_result_runs),
        .result_windows(rom_result_windows)
    );

    wire controller_cmd_valid = state_q==ST_ADMIT && admit_ok && !fault_q && !cancel &&
                                source_leased && destination_reserved;
    wire controller_descriptor_valid = descriptor_valid;
    z100_conv_prefetch_control_v2 u_prefetch (
        .clk(clk), .rst_n(rst_n), .cancel(controller_cancel),
        .recover(recover && quiet_drained && controller_needs_drain),
        .recovery_drained(recovery_drained),
        .cmd_valid(controller_cmd_valid), .cmd_ready(controller_cmd_ready),
        .cmd_epoch(cmd_epoch_q), .cmd_job_base(cmd_job_base_q),
        .cmd_token_base(cmd_token_base_q), .cmd_tag_base(cmd_tag_base_q),
        .cmd_tiles(tile_count_q), .cmd_output_height(producer_output_height[9:0]),
        .cmd_first_bank(cmd_first_bank_q), .source_leased(source_leased),
        .destination_reserved(destination_reserved),
        .descriptor_valid(controller_descriptor_valid),
        .descriptor_ready(controller_descriptor_ready),
        .descriptor_epoch(descriptor_epoch_q), .descriptor_index(descriptor_index_q),
        .descriptor_input_y(descriptor_input_y_q), .descriptor_input_rows(descriptor_input_rows_q),
        .descriptor_output_y(descriptor_output_y_q), .descriptor_output_rows(descriptor_output_rows_q),
        .descriptor_runs(descriptor_runs_q), .descriptor_windows(descriptor_windows_q),
        .next_descriptor(controller_next_descriptor),
        .load_valid(controller_load_valid), .load_ready(load_ready), .load_bank(load_bank),
        .load_job_tag(load_job_tag), .load_input_y(load_input_y), .load_input_rows(load_input_rows),
        .load_done(load_done), .load_committed(load_committed), .load_fault(load_fault),
        .load_epoch(load_epoch), .load_done_bank(load_done_bank),
        .tile_valid(controller_tile_valid), .tile_ready(tile_ready), .tile_bank(tile_bank),
        .tile_job_tag(tile_job_tag), .tile_token_base(tile_token_base), .tile_tag_base(tile_tag_base),
        .tile_input_y(tile_input_y), .tile_input_rows(tile_input_rows),
        .tile_output_y(tile_output_y), .tile_output_rows(tile_output_rows),
        .tile_done(tile_done), .tile_fault(tile_fault), .tile_done_epoch(tile_done_epoch),
        .tile_done_job(tile_done_job), .tile_done_bank(tile_done_bank),
        .load_quiet(load_quiet), .tile_write_quiet(tile_write_quiet), .all_io_quiet(all_io_quiet),
        .epoch(controller_epoch), .child_cancel(controller_child_cancel), .active(controller_active),
        .needs_drain(controller_needs_drain), .done(controller_done), .fault(controller_fault),
        .fault_code(controller_fault_code), .committed_tiles(controller_committed_tiles)
    );

    assign cmd_ready = rst_n && state_q==ST_IDLE && !fault_q && !cancel &&
                       controller_cmd_ready;
    assign load_valid = controller_load_valid && !fault_q && state_q!=ST_FAILED;
    assign tile_valid = controller_tile_valid && !fault_q && state_q!=ST_FAILED;
    // Pair producer context with the newly accepted outer command even before
    // the inner controller admits it and updates its own epoch register.
    assign active_epoch = cmd_epoch_q;
    assign active = (state_q!=ST_IDLE && state_q!=ST_FAILED) || controller_active;
    assign fault = fault_q || controller_fault;
    assign fault_code = fault_q ? fault_code_q : controller_fault_code;
    assign child_cancel = cancel || fault_q || controller_child_cancel || response_bad_now ||
                          ((state_q!=ST_IDLE) && (!source_leased || !destination_reserved));
    assign needs_drain = fault_q || controller_needs_drain;
    assign committed_tiles = controller_committed_tiles;

    always @(posedge clk) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            fault_q <= 1'b0;
            fault_code_q <= 4'd0;
            cmd_epoch_q <= 32'd0;
            cmd_event_q <= 8'd0;
            cmd_model_crc_q <= MODEL_CRC;
            cmd_job_base_q <= 32'd0;
            cmd_token_base_q <= 32'd0;
            cmd_tag_base_q <= 32'd0;
            cmd_first_bank_q <= 1'b0;
            tile_count_q <= 8'd0;
            expected_output_y_q <= 10'd0;
            descriptor_epoch_q <= 32'd0;
            descriptor_index_q <= 8'd0;
            descriptor_input_y_q <= 10'd0;
            descriptor_input_rows_q <= 10'd0;
            descriptor_output_y_q <= 10'd0;
            descriptor_output_rows_q <= 10'd0;
            descriptor_runs_q <= 32'd0;
            descriptor_windows_q <= 32'd0;
            producer_context_valid <= 1'b0;
            producer_cin <= 16'd0;
            producer_input_height <= 16'd0;
            producer_input_width <= 16'd0;
            producer_cout <= 16'd0;
            producer_output_height <= 16'd0;
            producer_output_width <= 16'd0;
            producer_kernel <= 16'd0;
            producer_stride <= 16'd0;
            producer_padding <= 16'd0;
            producer_parameter_first <= 16'd0;
            producer_event <= 8'd0;
            done <= 1'b0;
            bad_pulse_q <= 1'b0;
            f_payload_q <= 1'b0; f_first_q <= 1'b0; f_ctx_q <= 1'b0;
        end else begin
            done <= 1'b0;
            bad_pulse_q <= 1'b0;
            if (state_q==ST_IDLE) begin
                if (cmd_valid && cmd_ready) begin
                    if (cmd_epoch==0 || cmd_job_base==0 || cmd_token_base==0 || cmd_tag_base==0) begin
                        state_q <= ST_FAILED;
                        fault_q <= 1'b1;
                        fault_code_q <= 4'd1;
                    end else begin
                        cmd_epoch_q <= cmd_epoch;
                        cmd_event_q <= cmd_event;
                        cmd_model_crc_q <= cmd_model_crc;
                        cmd_job_base_q <= cmd_job_base;
                        cmd_token_base_q <= cmd_token_base;
                        cmd_tag_base_q <= cmd_tag_base;
                        cmd_first_bank_q <= cmd_first_bank;
                        producer_context_valid <= 1'b0;
                        expected_output_y_q <= 10'd0;
                        state_q <= ST_REQ_FIRST;
                    end
                end
            end else if (state_q!=ST_FAILED && cancel) begin
                state_q <= ST_FAILED;
                fault_q <= 1'b1;
                fault_code_q <= 4'd2;
            end else if (state_q!=ST_IDLE && state_q!=ST_FAILED &&
                         (!source_leased || !destination_reserved)) begin
                state_q <= ST_FAILED;
                fault_q <= 1'b1;
                fault_code_q <= 4'd3;
            end else if ((state_q==ST_WAIT_FIRST || state_q==ST_WAIT_NEXT) && rom_result_valid) begin
                r_epoch <= rom_result_epoch; r_tag <= rom_result_tag;
                r_event <= rom_result_event; r_tile <= rom_result_tile;
                r_error <= rom_result_error; r_geometry <= rom_result_geometry;
                r_parameter_first <= rom_result_parameter_first;
                r_tile_count <= rom_result_tile_count;
                r_runs <= rom_result_runs; r_windows <= rom_result_windows;
                state_q <= (state_q==ST_WAIT_FIRST) ? ST_CHK_FIRST : ST_CHK_NEXT;
            end else if (state_q==ST_CHK_FIRST || state_q==ST_CHK_NEXT) begin
                f_payload_q <= response_payload_bad;
                f_first_q <= response_first_extra;
                f_ctx_q <= response_ctx_extra;
                state_q <= (state_q==ST_CHK_FIRST) ? ST_VRF_FIRST : ST_VRF_NEXT;
            end else if (state_q==ST_VRF_FIRST) begin
                if (vrf_first_bad) begin
                    state_q <= ST_FAILED;
                    fault_q <= 1'b1;
                    fault_code_q <= 4'd4;
                    bad_pulse_q <= 1'b1;
                end else begin
                    tile_count_q <= r_tile_count;
                    producer_context_valid <= 1'b1;
                    producer_cin <= response_cin;
                    producer_input_height <= response_input_height;
                    producer_input_width <= response_input_width;
                    producer_cout <= response_cout;
                    producer_output_height <= response_output_height;
                    producer_output_width <= response_output_width;
                    producer_kernel <= response_kernel;
                    producer_stride <= response_stride;
                    producer_padding <= response_padding;
                    producer_parameter_first <= r_parameter_first;
                    producer_event <= cmd_event_q;
                    descriptor_epoch_q <= cmd_epoch_q;
                    descriptor_index_q <= r_tile;
                    descriptor_input_y_q <= response_input_y[9:0];
                    descriptor_input_rows_q <= response_input_rows[9:0];
                    descriptor_output_y_q <= response_output_y[9:0];
                    descriptor_output_rows_q <= response_output_rows[9:0];
                    descriptor_runs_q <= r_runs;
                    descriptor_windows_q <= r_windows;
                    state_q <= ST_ADMIT;
                end
            end else if (state_q==ST_VRF_NEXT) begin
                if (vrf_next_bad) begin
                    state_q <= ST_FAILED;
                    fault_q <= 1'b1;
                    fault_code_q <= 4'd5;
                    bad_pulse_q <= 1'b1;
                end else begin
                    descriptor_epoch_q <= cmd_epoch_q;
                    descriptor_index_q <= r_tile;
                    descriptor_input_y_q <= response_input_y[9:0];
                    descriptor_input_rows_q <= response_input_rows[9:0];
                    descriptor_output_y_q <= response_output_y[9:0];
                    descriptor_output_rows_q <= response_output_rows[9:0];
                    descriptor_runs_q <= r_runs;
                    descriptor_windows_q <= r_windows;
                    state_q <= ST_DESCRIPTOR;
                end
            end else if (state_q==ST_ADMIT && controller_cmd_valid && controller_cmd_ready) begin
                state_q <= ST_DESCRIPTOR;
            end else if (state_q==ST_DESCRIPTOR && descriptor_handshake) begin
                expected_output_y_q <= descriptor_output_y_q + descriptor_output_rows_q;
                if (descriptor_index_q+8'd1==tile_count_q)
                    state_q <= ST_DRAIN;
                else
                    state_q <= ST_REQ_NEXT;
            end else if (state_q==ST_REQ_FIRST && rom_request_valid && rom_request_ready) begin
                state_q <= ST_WAIT_FIRST;
            end else if (state_q==ST_REQ_NEXT && rom_request_valid && rom_request_ready) begin
                state_q <= ST_WAIT_NEXT;
            end else if (state_q==ST_DRAIN && controller_done) begin
                if (all_io_quiet && load_quiet && tile_write_quiet) begin
                    done <= 1'b1;
                    state_q <= ST_IDLE;
                    producer_context_valid <= 1'b0;
                end else begin
                    state_q <= ST_FAILED;
                    fault_q <= 1'b1;
                    fault_code_q <= 4'd6;
                end
            end else if (state_q==ST_FAILED && recover && quiet_drained && !cancel &&
                         !load_fault && !tile_fault) begin
                state_q <= ST_IDLE;
                fault_q <= 1'b0;
                fault_code_q <= 4'd0;
                producer_context_valid <= 1'b0;
                tile_count_q <= 8'd0;
                expected_output_y_q <= 10'd0;
                descriptor_epoch_q <= 32'd0;
                descriptor_index_q <= 8'd0;
            end else if (controller_fault || load_fault || tile_fault) begin
                state_q <= ST_FAILED;
                fault_q <= 1'b1;
                fault_code_q <= controller_fault ? controller_fault_code : 4'd3;
            end
        end
    end
endmodule
`default_nettype wire
