`default_nettype none
// Model-bound Conv plan ROM scheduler.  This module owns metadata only: the
// source lease, destination reservation, child I/O and drained recovery remain
// owned by its caller.
module z100_conv_rom_prefetch #(
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

    wire [15:0] response_cin          = rom_result_geometry[15:0];
    wire [15:0] response_input_height = rom_result_geometry[31:16];
    wire [15:0] response_input_width  = rom_result_geometry[47:32];
    wire [15:0] response_input_y      = rom_result_geometry[63:48];
    wire [15:0] response_input_rows   = rom_result_geometry[79:64];
    wire [15:0] response_output_y     = rom_result_geometry[95:80];
    wire [15:0] response_output_rows  = rom_result_geometry[111:96];
    wire [15:0] response_output_height= rom_result_geometry[127:112];
    wire [15:0] response_output_width = rom_result_geometry[143:128];
    wire [15:0] response_cout         = rom_result_geometry[159:144];
    wire [15:0] response_kernel       = rom_result_geometry[175:160];
    wire [15:0] response_stride       = rom_result_geometry[191:176];
    wire [15:0] response_padding      = rom_result_geometry[207:192];
    wire [16:0] response_input_end = {1'b0,response_input_y}+{1'b0,response_input_rows};
    wire [16:0] response_output_end = {1'b0,response_output_y}+{1'b0,response_output_rows};
    wire [32:0] response_job_end = {1'b0,cmd_job_base_q}+{25'd0,rom_result_tile_count}-33'd1;
    wire response_identity_bad = rom_result_epoch!=cmd_epoch_q ||
                                 rom_result_tag!=cmd_job_base_q ||
                                 rom_result_event!=cmd_event_q ||
                                 rom_result_tile!=(state_q==ST_WAIT_FIRST ? 8'd0 : controller_next_descriptor);
    wire response_payload_bad = rom_result_error || response_identity_bad ||
                                rom_result_tile_count==0 || rom_result_tile_count>8'd189 ||
                                rom_result_runs==0 || rom_result_windows<rom_result_runs ||
                                response_cin==0 || response_input_height==0 || response_input_height>640 ||
                                response_input_width==0 || response_input_width>640 ||
                                response_input_rows==0 || response_input_end>response_input_height ||
                                response_output_rows==0 || response_output_height==0 || response_output_height>640 ||
                                response_output_width==0 || response_output_width>640 ||
                                response_cout==0 || response_kernel==0 || response_stride==0 ||
                                response_padding>response_kernel || response_output_end>response_output_height;
    wire response_first_bad = response_payload_bad || response_output_y!=0 ||
                              (rom_result_tile_count==1 ? response_output_end!=response_output_height :
                                                          response_output_end>=response_output_height) ||
                              response_job_end>33'h0ffffffff;
    wire response_context_bad = response_payload_bad ||
                                rom_result_tile_count!=tile_count_q ||
                                rom_result_parameter_first!=producer_parameter_first ||
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
                                (rom_result_tile+8'd1==tile_count_q ? response_output_end!=producer_output_height :
                                                                       response_output_end>=producer_output_height);
    wire response_bad_now = rom_result_valid &&
                            ((state_q==ST_WAIT_FIRST && response_first_bad) ||
                             (state_q==ST_WAIT_NEXT && response_context_bad));
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

    wire controller_cmd_valid = state_q==ST_ADMIT && !fault_q && !cancel &&
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
    assign active_epoch = controller_epoch;
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
        end else begin
            done <= 1'b0;
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
            end else if (state_q==ST_WAIT_FIRST && rom_result_valid) begin
                if (response_first_bad) begin
                    state_q <= ST_FAILED;
                    fault_q <= 1'b1;
                    fault_code_q <= 4'd4;
                end else begin
                    tile_count_q <= rom_result_tile_count;
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
                    producer_parameter_first <= rom_result_parameter_first;
                    producer_event <= cmd_event_q;
                    descriptor_epoch_q <= cmd_epoch_q;
                    descriptor_index_q <= rom_result_tile;
                    descriptor_input_y_q <= response_input_y[9:0];
                    descriptor_input_rows_q <= response_input_rows[9:0];
                    descriptor_output_y_q <= response_output_y[9:0];
                    descriptor_output_rows_q <= response_output_rows[9:0];
                    descriptor_runs_q <= rom_result_runs;
                    descriptor_windows_q <= rom_result_windows;
                    state_q <= ST_ADMIT;
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
            end else if (state_q==ST_WAIT_NEXT && rom_result_valid) begin
                if (response_context_bad) begin
                    state_q <= ST_FAILED;
                    fault_q <= 1'b1;
                    fault_code_q <= 4'd5;
                end else begin
                    descriptor_epoch_q <= cmd_epoch_q;
                    descriptor_index_q <= rom_result_tile;
                    descriptor_input_y_q <= response_input_y[9:0];
                    descriptor_input_rows_q <= response_input_rows[9:0];
                    descriptor_output_y_q <= response_output_y[9:0];
                    descriptor_output_rows_q <= response_output_rows[9:0];
                    descriptor_runs_q <= rom_result_runs;
                    descriptor_windows_q <= rom_result_windows;
                    state_q <= ST_DESCRIPTOR;
                end
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
