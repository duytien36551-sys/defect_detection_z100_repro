`default_nettype none
// Private two-bank Conv halo scheduler. Descriptor order and geometry come
// from the frozen C plan. Load and tile cursors advance independently so the
// next halo can be serviced while the prior bank is computing. This module
// owns metadata only; external logic retains graph ownership until completion
// or drained recovery.
(* use_dsp="no" *)
module z100_conv_prefetch_control_v2(
    input wire clk,rst_n,cancel,recover,recovery_drained,
    input wire cmd_valid,output wire cmd_ready,
    input wire [31:0] cmd_epoch,cmd_job_base,cmd_token_base,cmd_tag_base,
    input wire [7:0] cmd_tiles,
    input wire [9:0] cmd_output_height,
    input wire cmd_first_bank,
    input wire source_leased,destination_reserved,
    input wire descriptor_valid,output wire descriptor_ready,
    input wire [31:0] descriptor_epoch,
    input wire [7:0] descriptor_index,
    input wire [9:0] descriptor_input_y,descriptor_input_rows,
    input wire [9:0] descriptor_output_y,descriptor_output_rows,
    input wire [31:0] descriptor_runs,descriptor_windows,
    output wire [7:0] next_descriptor,
    output wire load_valid,input wire load_ready,
    output wire load_bank,
    output wire [31:0] load_job_tag,
    output wire [9:0] load_input_y,load_input_rows,
    input wire load_done,load_committed,load_fault,
    input wire [31:0] load_epoch,
    input wire load_done_bank,
    output wire tile_valid,input wire tile_ready,
    output wire tile_bank,
    output wire [31:0] tile_job_tag,tile_token_base,tile_tag_base,
    output wire [9:0] tile_input_y,tile_input_rows,
    output wire [9:0] tile_output_y,tile_output_rows,
    input wire tile_done,tile_fault,
    input wire [31:0] tile_done_epoch,tile_done_job,
    input wire tile_done_bank,
    input wire load_quiet,tile_write_quiet,all_io_quiet,
    output wire [31:0] epoch,
    output wire child_cancel,active,needs_drain,
    output reg done,fault,
    output reg [3:0] fault_code,
    output reg [7:0] committed_tiles
);
    localparam [1:0] CTRL_IDLE=2'd0,CTRL_ACTIVE=2'd1,CTRL_FAILED=2'd2;
    localparam [2:0] BANK_FREE=3'd0,BANK_DESCRIBED=3'd1,
                     BANK_LOADING=3'd2,BANK_READY=3'd3,
                     BANK_COMPUTING=3'd4,BANK_DRAIN=3'd5;

    reg [1:0] control_state_q;
    reg [2:0] bank0_state_q,bank1_state_q;
    reg [31:0] epoch_q,job_base_q,token_next_q,tag_next_q;
    reg [31:0] ledger_epoch_q,ledger_job_end_q;
    reg [7:0] count_q,descriptor_next_q,load_next_q,tile_next_q;
    reg [9:0] output_height_q;
    reg [10:0] expected_output_y_q;
    reg first_bank_q,load_wait_q,tile_wait_q;

    reg [31:0] bank0_job_q,bank0_token_q,bank0_tag_q;
    reg [9:0] bank0_input_y_q,bank0_input_rows_q;
    reg [9:0] bank0_output_y_q,bank0_output_rows_q;
    reg [31:0] bank1_job_q,bank1_token_q,bank1_tag_q;
    reg [9:0] bank1_input_y_q,bank1_input_rows_q;
    reg [9:0] bank1_output_y_q,bank1_output_rows_q;

    wire [32:0] command_job_end = {1'b0,cmd_job_base}+
                                     {25'd0,cmd_tiles}-33'd1;
    wire command_ok = cmd_epoch!=0 && cmd_job_base!=0 && cmd_token_base!=0 &&
                      cmd_tiles!=0 && cmd_tiles<=8'd189 &&
                      cmd_output_height!=0 && cmd_output_height<=10'd640 &&
                      source_leased && destination_reserved &&
                      (cmd_epoch>ledger_epoch_q ||
                       (cmd_epoch==ledger_epoch_q && cmd_job_base>ledger_job_end_q)) &&
                      command_job_end<=33'h0ffffffff;

    wire descriptor_bank_sel = first_bank_q ^ descriptor_next_q[0];
    wire descriptor_bank_free = descriptor_bank_sel ?
                                (bank1_state_q==BANK_FREE) :
                                (bank0_state_q==BANK_FREE);
    wire descriptor_is_last = descriptor_next_q+8'd1==count_q;
    wire [10:0] descriptor_input_end = {1'b0,descriptor_input_y}+
                                       {1'b0,descriptor_input_rows};
    wire [10:0] descriptor_output_end = {1'b0,descriptor_output_y}+
                                        {1'b0,descriptor_output_rows};
    wire [32:0] descriptor_token_end = {1'b0,token_next_q}+
                                       {1'b0,descriptor_runs};
    wire [32:0] descriptor_tag_end = {1'b0,tag_next_q}+
                                     {1'b0,descriptor_windows};
    wire descriptor_ok = descriptor_epoch==epoch_q &&
                         descriptor_index==descriptor_next_q &&
                         descriptor_next_q<count_q &&
                         descriptor_input_rows!=0 && descriptor_input_end<=11'd640 &&
                         descriptor_output_rows!=0 &&
                         {1'b0,descriptor_output_y}==expected_output_y_q &&
                         descriptor_output_end<={1'b0,output_height_q} &&
                         (descriptor_is_last ?
                           descriptor_output_end=={1'b0,output_height_q} :
                           descriptor_output_end<{1'b0,output_height_q}) &&
                         descriptor_runs!=0 &&
                         descriptor_windows>=descriptor_runs &&
                         (descriptor_is_last ?
                           (descriptor_token_end<=33'h100000000 &&
                            descriptor_tag_end<=33'h100000000) :
                           (descriptor_token_end<=33'h0ffffffff &&
                            descriptor_tag_end<=33'h0ffffffff));

    wire load_bank_sel = first_bank_q ^ load_next_q[0];
    wire [2:0] load_bank_state = load_bank_sel ? bank1_state_q : bank0_state_q;
    wire tile_bank_sel = first_bank_q ^ tile_next_q[0];
    wire [2:0] tile_bank_state = tile_bank_sel ? bank1_state_q : bank0_state_q;
    wire child_fault_now = load_fault || tile_fault;
    wire child_completion_now = load_done || tile_done;
    wire quiet_for_recovery = recovery_drained && all_io_quiet &&
                              load_quiet && tile_write_quiet;
    wire load_completion_bad = (load_done &&
                                (!load_wait_q || !load_committed ||
                                 load_epoch!=epoch_q ||
                                 load_done_bank!=load_bank_sel));
    wire tile_completion_bad = tile_done &&
                               (!tile_wait_q || tile_done_epoch!=epoch_q ||
                                tile_done_job!=tile_job_tag ||
                                tile_done_bank!=tile_bank_sel);
    wire descriptor_handshake = descriptor_valid && descriptor_ready;
    wire load_handshake = load_valid && load_ready;
    wire tile_handshake = tile_valid && tile_ready;
    wire bad_event_now = (descriptor_handshake && !descriptor_ok) ||
                         load_completion_bad || tile_completion_bad;
    wire retire_bank0 = control_state_q==CTRL_ACTIVE &&
                        tile_write_quiet && bank0_state_q==BANK_DRAIN;
    wire retire_bank1 = control_state_q==CTRL_ACTIVE &&
                        tile_write_quiet && bank1_state_q==BANK_DRAIN;
    wire all_tiles_finished = descriptor_next_q==count_q &&
                              load_next_q==count_q && tile_next_q==count_q &&
                              committed_tiles==count_q && !load_wait_q &&
                              !tile_wait_q && bank0_state_q==BANK_FREE &&
                              bank1_state_q==BANK_FREE;

    assign cmd_ready = rst_n && control_state_q==CTRL_IDLE && !cancel &&
                       !fault && !child_fault_now && !child_completion_now &&
                       all_io_quiet && load_quiet && tile_write_quiet;
    assign descriptor_ready = rst_n && control_state_q==CTRL_ACTIVE &&
                              descriptor_next_q<count_q && descriptor_bank_free &&
                              !cancel && !fault && !child_fault_now &&
                              !child_completion_now && source_leased &&
                              destination_reserved;
    assign next_descriptor = descriptor_next_q;

    assign load_bank = load_bank_sel;
    assign load_valid = rst_n && control_state_q==CTRL_ACTIVE &&
                        !load_wait_q && load_next_q<count_q &&
                        load_bank_state==BANK_DESCRIBED && !load_done && !cancel && !fault &&
                        !child_fault_now &&
                        source_leased && destination_reserved;
    assign load_job_tag = load_bank_sel ? bank1_job_q : bank0_job_q;
    assign load_input_y = load_bank_sel ? bank1_input_y_q : bank0_input_y_q;
    assign load_input_rows = load_bank_sel ? bank1_input_rows_q : bank0_input_rows_q;

    assign tile_bank = tile_bank_sel;
    assign tile_valid = rst_n && control_state_q==CTRL_ACTIVE &&
                        !tile_wait_q && tile_next_q<count_q &&
                        tile_bank_state==BANK_READY && !tile_done && !cancel && !fault &&
                        bank0_state_q!=BANK_DRAIN && bank1_state_q!=BANK_DRAIN &&
                        !child_fault_now &&
                        source_leased && destination_reserved;
    assign tile_job_tag = tile_bank_sel ? bank1_job_q : bank0_job_q;
    assign tile_token_base = tile_bank_sel ? bank1_token_q : bank0_token_q;
    assign tile_tag_base = tile_bank_sel ? bank1_tag_q : bank0_tag_q;
    assign tile_input_y = tile_bank_sel ? bank1_input_y_q : bank0_input_y_q;
    assign tile_input_rows = tile_bank_sel ? bank1_input_rows_q : bank0_input_rows_q;
    assign tile_output_y = tile_bank_sel ? bank1_output_y_q : bank0_output_y_q;
    assign tile_output_rows = tile_bank_sel ? bank1_output_rows_q : bank0_output_rows_q;

    assign epoch = epoch_q;
    assign active = control_state_q==CTRL_ACTIVE;
    assign needs_drain = control_state_q==CTRL_FAILED;
    assign child_cancel = cancel || fault || child_fault_now ||
                          (control_state_q==CTRL_ACTIVE &&
                           (!source_leased || !destination_reserved));

    task set_fault;
        input [3:0] code;
        begin
            control_state_q <= CTRL_FAILED;
            fault <= 1'b1;
            fault_code <= code;
        end
    endtask

    always @(posedge clk) begin
        if (!rst_n) begin
            control_state_q <= CTRL_IDLE;
            bank0_state_q <= BANK_FREE;
            bank1_state_q <= BANK_FREE;
            epoch_q <= 0;
            job_base_q <= 0;
            token_next_q <= 0;
            tag_next_q <= 0;
            ledger_epoch_q <= 0;
            ledger_job_end_q <= 0;
            count_q <= 0;
            descriptor_next_q <= 0;
            load_next_q <= 0;
            tile_next_q <= 0;
            output_height_q <= 0;
            expected_output_y_q <= 0;
            first_bank_q <= 0;
            load_wait_q <= 0;
            tile_wait_q <= 0;
            bank0_job_q <= 0;
            bank0_token_q <= 0;
            bank0_tag_q <= 0;
            bank0_input_y_q <= 0;
            bank0_input_rows_q <= 0;
            bank0_output_y_q <= 0;
            bank0_output_rows_q <= 0;
            bank1_job_q <= 0;
            bank1_token_q <= 0;
            bank1_tag_q <= 0;
            bank1_input_y_q <= 0;
            bank1_input_rows_q <= 0;
            bank1_output_y_q <= 0;
            bank1_output_rows_q <= 0;
            done <= 0;
            fault <= 0;
            fault_code <= 0;
            committed_tiles <= 0;
        end else begin
            done <= 0;
            if (control_state_q==CTRL_FAILED) begin
                if (recover && quiet_for_recovery && !cancel &&
                    !child_fault_now && !child_completion_now) begin
                    control_state_q <= CTRL_IDLE;
                    bank0_state_q <= BANK_FREE;
                    bank1_state_q <= BANK_FREE;
                    count_q <= 0;
                    descriptor_next_q <= 0;
                    load_next_q <= 0;
                    tile_next_q <= 0;
                    output_height_q <= 0;
                    expected_output_y_q <= 0;
                    first_bank_q <= 0;
                    load_wait_q <= 0;
                    tile_wait_q <= 0;
                    bank0_job_q <= 0;
                    bank0_token_q <= 0;
                    bank0_tag_q <= 0;
                    bank0_input_y_q <= 0;
                    bank0_input_rows_q <= 0;
                    bank0_output_y_q <= 0;
                    bank0_output_rows_q <= 0;
                    bank1_job_q <= 0;
                    bank1_token_q <= 0;
                    bank1_tag_q <= 0;
                    bank1_input_y_q <= 0;
                    bank1_input_rows_q <= 0;
                    bank1_output_y_q <= 0;
                    bank1_output_rows_q <= 0;
                    committed_tiles <= 0;
                    fault <= 0;
                    fault_code <= 0;
                end
            end else if (cancel && control_state_q==CTRL_ACTIVE) begin
                set_fault(4'd1);
            end else if (control_state_q==CTRL_ACTIVE &&
                         (!source_leased || !destination_reserved)) begin
                set_fault(4'd2);
            end else if (child_fault_now) begin
                set_fault(4'd3);
            end else if (descriptor_handshake && !descriptor_ok) begin
                set_fault(4'd4);
            end else if (load_completion_bad) begin
                set_fault(4'd5);
            end else if (tile_completion_bad) begin
                set_fault(4'd6);
            end else if (control_state_q==CTRL_IDLE) begin
                // Any completion observed without an outstanding child command
                // is rejected above, including stale events between requests.
                if (cmd_valid && cmd_ready) begin
                    if (!command_ok) begin
                        set_fault(4'd7);
                    end else begin
                        control_state_q <= CTRL_ACTIVE;
                        epoch_q <= cmd_epoch;
                        job_base_q <= cmd_job_base;
                        token_next_q <= cmd_token_base;
                        tag_next_q <= cmd_tag_base;
                        ledger_epoch_q <= cmd_epoch;
                        ledger_job_end_q <= command_job_end[31:0];
                        count_q <= cmd_tiles;
                        descriptor_next_q <= 0;
                        load_next_q <= 0;
                        tile_next_q <= 0;
                        output_height_q <= cmd_output_height;
                        expected_output_y_q <= 0;
                        first_bank_q <= cmd_first_bank;
                        load_wait_q <= 0;
                        tile_wait_q <= 0;
                        bank0_state_q <= BANK_FREE;
                        bank1_state_q <= BANK_FREE;
                        bank0_job_q <= 0;
                        bank0_token_q <= 0;
                        bank0_tag_q <= 0;
                        bank0_input_y_q <= 0;
                        bank0_input_rows_q <= 0;
                        bank0_output_y_q <= 0;
                        bank0_output_rows_q <= 0;
                        bank1_job_q <= 0;
                        bank1_token_q <= 0;
                        bank1_tag_q <= 0;
                        bank1_input_y_q <= 0;
                        bank1_input_rows_q <= 0;
                        bank1_output_y_q <= 0;
                        bank1_output_rows_q <= 0;
                        committed_tiles <= 0;
                        fault <= 0;
                        fault_code <= 0;
                    end
                end
            end else if (control_state_q==CTRL_ACTIVE) begin
                if (descriptor_handshake) begin
                    descriptor_next_q <= descriptor_next_q+1'b1;
                    expected_output_y_q <= descriptor_output_end;
                    token_next_q <= descriptor_token_end[31:0];
                    tag_next_q <= descriptor_tag_end[31:0];
                    if (descriptor_bank_sel) begin
                        bank1_state_q <= BANK_DESCRIBED;
                        bank1_job_q <= job_base_q+descriptor_next_q;
                        bank1_token_q <= token_next_q;
                        bank1_tag_q <= tag_next_q;
                        bank1_input_y_q <= descriptor_input_y;
                        bank1_input_rows_q <= descriptor_input_rows;
                        bank1_output_y_q <= descriptor_output_y;
                        bank1_output_rows_q <= descriptor_output_rows;
                    end else begin
                        bank0_state_q <= BANK_DESCRIBED;
                        bank0_job_q <= job_base_q+descriptor_next_q;
                        bank0_token_q <= token_next_q;
                        bank0_tag_q <= tag_next_q;
                        bank0_input_y_q <= descriptor_input_y;
                        bank0_input_rows_q <= descriptor_input_rows;
                        bank0_output_y_q <= descriptor_output_y;
                        bank0_output_rows_q <= descriptor_output_rows;
                    end
                end

                if (load_handshake) begin
                    load_wait_q <= 1;
                    if (load_bank_sel) bank1_state_q <= BANK_LOADING;
                    else bank0_state_q <= BANK_LOADING;
                end
                if (load_done) begin
                    load_wait_q <= 0;
                    load_next_q <= load_next_q+1'b1;
                    if (load_bank_sel) bank1_state_q <= BANK_READY;
                    else bank0_state_q <= BANK_READY;
                end

                if (tile_handshake) begin
                    tile_wait_q <= 1;
                    if (tile_bank_sel) bank1_state_q <= BANK_COMPUTING;
                    else bank0_state_q <= BANK_COMPUTING;
                end
                if (tile_done) begin
                    tile_wait_q <= 0;
                    tile_next_q <= tile_next_q+1'b1;
                    if (tile_bank_sel) bank1_state_q <= BANK_DRAIN;
                    else bank0_state_q <= BANK_DRAIN;
                end

                if (retire_bank0) begin
                    bank0_state_q <= BANK_FREE;
                    bank0_job_q <= 0;
                    bank0_token_q <= 0;
                    bank0_tag_q <= 0;
                    bank0_input_y_q <= 0;
                    bank0_input_rows_q <= 0;
                    bank0_output_y_q <= 0;
                    bank0_output_rows_q <= 0;
                end
                if (retire_bank1) begin
                    bank1_state_q <= BANK_FREE;
                    bank1_job_q <= 0;
                    bank1_token_q <= 0;
                    bank1_tag_q <= 0;
                    bank1_input_y_q <= 0;
                    bank1_input_rows_q <= 0;
                    bank1_output_y_q <= 0;
                    bank1_output_rows_q <= 0;
                end
                if (retire_bank0 || retire_bank1)
                    committed_tiles <= committed_tiles+
                                       {7'd0,retire_bank0}+
                                       {7'd0,retire_bank1};

                if (all_tiles_finished && load_quiet && tile_write_quiet &&
                    all_io_quiet) begin
                    done <= 1;
                    control_state_q <= CTRL_IDLE;
                end
            end
        end
    end
endmodule
`default_nettype wire
