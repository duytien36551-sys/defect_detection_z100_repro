`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_output_packer;
    `include "native_output_counts.svh"

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;
    reg cancel = 1'b0;

    reg cfg_valid = 1'b0;
    wire cfg_ready4, cfg_ready8, cfg_ready12;
    reg [31:0] cfg_epoch = 0;
    reg [10:0] cfg_channels = 0;
    reg [9:0] cfg_height = 0;
    reg [9:0] cfg_width = 0;
    reg [31:0] cfg_token_base = 0;

    reg in_valid = 1'b0;
    wire in_ready4, in_ready8, in_ready12;
    reg [31:0] in_epoch = 0;
    reg [31:0] in_token4 = 0, in_token8 = 0, in_token12 = 0;
    reg [3:0] in_site4 = 0, in_site8 = 0, in_site12 = 0;
    reg [5:0] in_lanes = 0;
    reg in_last4 = 0, in_last8 = 0, in_last12 = 0;
    reg [255:0] in_data = 0;

    wire out_valid4, out_valid8, out_valid12;
    reg out_ready = 1'b0;
    wire [31:0] out_epoch4, out_epoch8, out_epoch12;
    wire [12:0] out_address4, out_address8, out_address12;
    wire [511:0] out_data4, out_data8, out_data12;
    wire out_last4, out_last8, out_last12;
    wire done4, done8, done12;
    wire error4, error8, error12;
    wire [2:0] error_code4, error_code8, error_code12;
    wire active4, active8, active12;

    z100_native_output_packer #(.SITES(4)) dut4 (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_valid(cfg_valid), .cfg_ready(cfg_ready4), .cfg_epoch(cfg_epoch),
        .cfg_channels(cfg_channels), .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_token_base(cfg_token_base), .in_valid(in_valid), .in_ready(in_ready4),
        .in_epoch(in_epoch), .in_token(in_token4), .in_site(in_site4),
        .in_lanes(in_lanes), .in_last(in_last4), .in_data(in_data),
        .out_valid(out_valid4), .out_ready(out_ready), .out_epoch(out_epoch4),
        .out_address(out_address4), .out_data(out_data4), .out_last(out_last4),
        .done(done4), .error_valid(error4), .error_code(error_code4), .active(active4)
    );
    z100_native_output_packer #(.SITES(8)) dut8 (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_valid(cfg_valid), .cfg_ready(cfg_ready8), .cfg_epoch(cfg_epoch),
        .cfg_channels(cfg_channels), .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_token_base(cfg_token_base), .in_valid(in_valid), .in_ready(in_ready8),
        .in_epoch(in_epoch), .in_token(in_token8), .in_site(in_site8),
        .in_lanes(in_lanes), .in_last(in_last8), .in_data(in_data),
        .out_valid(out_valid8), .out_ready(out_ready), .out_epoch(out_epoch8),
        .out_address(out_address8), .out_data(out_data8), .out_last(out_last8),
        .done(done8), .error_valid(error8), .error_code(error_code8), .active(active8)
    );
    z100_native_output_packer #(.SITES(12)) dut12 (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .cfg_valid(cfg_valid), .cfg_ready(cfg_ready12), .cfg_epoch(cfg_epoch),
        .cfg_channels(cfg_channels), .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_token_base(cfg_token_base), .in_valid(in_valid), .in_ready(in_ready12),
        .in_epoch(in_epoch), .in_token(in_token12), .in_site(in_site12),
        .in_lanes(in_lanes), .in_last(in_last12), .in_data(in_data),
        .out_valid(out_valid12), .out_ready(out_ready), .out_epoch(out_epoch12),
        .out_address(out_address12), .out_data(out_data12), .out_last(out_last12),
        .done(done12), .error_valid(error12), .error_code(error_code12), .active(active12)
    );

    reg [127:0] case_cfg_mem [0:CASE_COUNT-1];
    reg [63:0] case_offset_mem [0:CASE_COUNT-1];
    reg [255:0] input_word_mem [0:INPUT_WORD_COUNT-1];
    reg [527:0] expected_word_mem [0:EXPECTED_WORD_COUNT-1];

    integer total_input_handshakes = 0;
    integer total_output_handshakes = 0;
    integer total_done = 0;
    reg [31:0] expected_output_epoch = 0;
    integer config_error_count = 0;
    integer input_error_count = 0;
    integer input_bubble_cycles = 0;
    integer input_stall_cycles = 0;
    integer input_stability_checks = 0;
    integer output_stall_cycles = 0;
    integer output_stability_checks = 0;
    integer two_buffer_full_checks = 0;
    integer full_buffer_reload_checks = 0;
    integer max_input_burst = 0;
    integer current_input_burst = 0;
    integer max_output_burst = 0;
    integer current_output_burst = 0;
    integer reset_abort_count = 0;
    integer cancel_abort_count = 0;
    integer timeout_cycles = 0;
    integer case_index;
    integer cfg_case;
    integer current_case;
    integer case_c;
    integer case_h;
    integer case_w;
    integer case_epoch;
    integer case_token_base;
    integer case_input_count;
    integer case_output_count;
    integer case_input_start;
    integer case_output_start;
    integer case_group;
    integer case_row;
    integer case_x;
    integer case_seq;
    integer run_sites4;
    integer run_sites8;
    integer run_sites12;
    integer token_offset4;
    integer token_offset8;
    integer token_offset12;
    integer expected_lanes_int;
    integer data_index;
    integer accepted;
    integer i;
    integer j;
    integer local_count;
    integer done_target;
    integer output_target;
    integer prefix_index;
    integer start_done_count;
    integer bad_mode;
    integer special_full;
    integer full_pause_done = 0;
    reg input_prev_stall = 1'b0;
    reg [255:0] held_input_data = 0;
    reg [31:0] held_input_epoch = 0;
    reg [31:0] held_input_token4 = 0, held_input_token8 = 0, held_input_token12 = 0;
    reg [3:0] held_input_site4 = 0, held_input_site8 = 0, held_input_site12 = 0;
    reg [5:0] held_input_lanes = 0;
    reg held_input_last4 = 0, held_input_last8 = 0, held_input_last12 = 0;
    reg prev_out_stall4 = 1'b0, prev_out_stall8 = 1'b0, prev_out_stall12 = 1'b0;
    reg [31:0] held_out_epoch4 = 0, held_out_epoch8 = 0, held_out_epoch12 = 0;
    reg [12:0] held_out_address4 = 0, held_out_address8 = 0, held_out_address12 = 0;
    reg [511:0] held_out_data4 = 0, held_out_data8 = 0, held_out_data12 = 0;
    reg held_out_last4 = 0, held_out_last8 = 0, held_out_last12 = 0;
    reg previous_last_handshake = 1'b0;

    wire cfg_ready_all = cfg_ready4 && cfg_ready8 && cfg_ready12;
    wire in_ready_all = in_ready4 && in_ready8 && in_ready12;

    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            input_prev_stall = 1'b0;
            prev_out_stall4 = 1'b0;
            prev_out_stall8 = 1'b0;
            prev_out_stall12 = 1'b0;
            current_input_burst = 0;
            current_output_burst = 0;
            previous_last_handshake = 1'b0;
        end else begin
            timeout_cycles = timeout_cycles + 1;
            if (timeout_cycles > 2000000)
                $fatal(1, "native output packer test timed out");

            if (cfg_ready4 !== cfg_ready8 || cfg_ready4 !== cfg_ready12 ||
                in_ready4 !== in_ready8 || in_ready4 !== in_ready12 ||
                out_valid4 !== out_valid8 || out_valid4 !== out_valid12 ||
                active4 !== active8 || active4 !== active12)
                $fatal(1, "parameterized packer instances diverged in control state");

            if (input_prev_stall) begin
                if (!in_valid || in_data !== held_input_data || in_epoch !== held_input_epoch ||
                    in_token4 !== held_input_token4 || in_token8 !== held_input_token8 ||
                    in_token12 !== held_input_token12 || in_site4 !== held_input_site4 ||
                    in_site8 !== held_input_site8 || in_site12 !== held_input_site12 ||
                    in_lanes !== held_input_lanes || in_last4 !== held_input_last4 ||
                    in_last8 !== held_input_last8 || in_last12 !== held_input_last12)
                    $fatal(1, "input payload or metadata changed while both transpose buffers were full");
                input_stability_checks = input_stability_checks + 1;
            end
            input_prev_stall = in_valid && !in_ready_all;
            if (input_prev_stall) begin
                input_stall_cycles = input_stall_cycles + 1;
                held_input_data = in_data;
                held_input_epoch = in_epoch;
                held_input_token4 = in_token4;
                held_input_token8 = in_token8;
                held_input_token12 = in_token12;
                held_input_site4 = in_site4;
                held_input_site8 = in_site8;
                held_input_site12 = in_site12;
                held_input_lanes = in_lanes;
                held_input_last4 = in_last4;
                held_input_last8 = in_last8;
                held_input_last12 = in_last12;
            end

            if (in_valid && in_ready_all) begin
                total_input_handshakes = total_input_handshakes + 1;
                current_input_burst = current_input_burst + 1;
                if (current_input_burst > max_input_burst)
                    max_input_burst = current_input_burst;
            end else begin
                current_input_burst = 0;
            end

            if (prev_out_stall4) begin
                if (!out_valid4 || out_epoch4 !== held_out_epoch4 ||
                    out_address4 !== held_out_address4 || out_data4 !== held_out_data4 ||
                    out_last4 !== held_out_last4)
                    $fatal(1, "SITES=4 output changed while stalled");
                if (!out_valid8 || out_epoch8 !== held_out_epoch8 ||
                    out_address8 !== held_out_address8 || out_data8 !== held_out_data8 ||
                    out_last8 !== held_out_last8)
                    $fatal(1, "SITES=8 output changed while stalled");
                if (!out_valid12 || out_epoch12 !== held_out_epoch12 ||
                    out_address12 !== held_out_address12 || out_data12 !== held_out_data12 ||
                    out_last12 !== held_out_last12)
                    $fatal(1, "SITES=12 output changed while stalled");
                output_stability_checks = output_stability_checks + 1;
            end
            prev_out_stall4 = out_valid4 && !out_ready;
            prev_out_stall8 = out_valid8 && !out_ready;
            prev_out_stall12 = out_valid12 && !out_ready;
            if (out_valid4 && !out_ready) begin
                output_stall_cycles = output_stall_cycles + 1;
                held_out_epoch4 = out_epoch4;
                held_out_address4 = out_address4;
                held_out_data4 = out_data4;
                held_out_last4 = out_last4;
                held_out_epoch8 = out_epoch8;
                held_out_address8 = out_address8;
                held_out_data8 = out_data8;
                held_out_last8 = out_last8;
                held_out_epoch12 = out_epoch12;
                held_out_address12 = out_address12;
                held_out_data12 = out_data12;
                held_out_last12 = out_last12;
            end

            if (out_valid4 && out_ready) begin
                if (out_epoch4 !== expected_output_epoch ||
                    out_epoch8 !== expected_output_epoch ||
                    out_epoch12 !== expected_output_epoch || out_address4 !== out_address8 ||
                    out_address4 !== out_address12 || out_data4 !== out_data8 ||
                    out_data4 !== out_data12 || out_last4 !== out_last8 ||
                    out_last4 !== out_last12)
                    $fatal(1, "parameterized output words differ");
                if (total_output_handshakes >= EXPECTED_WORD_COUNT)
                    $fatal(1, "extra output word beyond expected scatter list");
                if (out_address4 !== expected_word_mem[total_output_handshakes][524:512] ||
                    out_data4 !== expected_word_mem[total_output_handshakes][511:0] ||
                    out_last4 !== expected_word_mem[total_output_handshakes][525])
                    $fatal(1, "packed output mismatch word=%0d address=%0d expected_address=%0d",
                           total_output_handshakes, out_address4,
                           expected_word_mem[total_output_handshakes][524:512]);
                total_output_handshakes = total_output_handshakes + 1;
                current_output_burst = current_output_burst + 1;
                if (current_output_burst > max_output_burst)
                    max_output_burst = current_output_burst;
            end else begin
                current_output_burst = 0;
            end

            if (done4 !== done8 || done4 !== done12 ||
                error4 !== error8 || error4 !== error12 ||
                error_code4 !== error_code8 || error_code4 !== error_code12)
                $fatal(1, "parameterized completion or error pulses diverged");
            if (done4) begin
                if (!previous_last_handshake)
                    $fatal(1, "done asserted without the preceding last output handshake");
                total_done = total_done + 1;
            end
            if (error4) begin
                if (error_code4 == 3'd1)
                    config_error_count = config_error_count + 1;
                else if (error_code4 == 3'd2)
                    input_error_count = input_error_count + 1;
                else
                    $fatal(1, "unexpected error code %0d", error_code4);
            end
            previous_last_handshake = out_valid4 && out_ready && out_last4;
        end
    end

    task automatic drive_config(input integer c, input integer h, input integer w,
                                input integer epoch, input integer token_base);
        integer accepted_cfg;
        begin
            @(negedge clk);
            cfg_channels = c;
            cfg_height = h;
            cfg_width = w;
            cfg_epoch = epoch;
            cfg_token_base = token_base;
            expected_output_epoch = epoch;
            cfg_valid = 1'b1;
            accepted_cfg = 0;
            while (!accepted_cfg) begin
                @(posedge clk);
                if (cfg_ready_all)
                    accepted_cfg = 1;
            end
            @(negedge clk);
            cfg_valid = 1'b0;
        end
    endtask

    task automatic prepare_input(input integer ci, input integer gb,
                                 input integer y, input integer x,
                                 input integer memory_index, input integer mode);
        reg [127:0] cfg;
        integer c;
        integer h;
        integer w;
        integer epoch_value;
        integer token_base_value;
        integer lanes_value;
        integer sites4;
        integer sites8;
        integer sites12;
        integer run4;
        integer run8;
        integer run12;
        integer last4;
        integer last8;
        integer last12;
        integer chunk4;
        integer chunk8;
        integer chunk12;
        begin
            cfg = case_cfg_mem[ci];
            c = cfg[10:0];
            h = cfg[20:11];
            w = cfg[30:21];
            epoch_value = cfg[62:31];
            token_base_value = cfg[94:63];
            lanes_value = ((c-gb) >= 32) ? 32 : (c-gb);

            chunk4 = w-(x/4)*4;
            if (chunk4 > 4) chunk4=4;
            chunk8 = w-(x/8)*8;
            if (chunk8 > 8) chunk8=8;
            chunk12 = w-(x/12)*12;
            if (chunk12 > 12) chunk12=12;
            sites4 = (w+3)/4;
            sites8 = (w+7)/8;
            sites12 = (w+11)/12;
            run4 = ((gb/32)*h+y)*sites4+(x/4);
            run8 = ((gb/32)*h+y)*sites8+(x/8);
            run12 = ((gb/32)*h+y)*sites12+(x/12);
            last4 = (x == (x/4)*4+chunk4-1);
            last8 = (x == (x/8)*8+chunk8-1);
            last12 = (x == (x/12)*12+chunk12-1);

            in_valid = 1'b1;
            in_epoch = (mode == 1) ? (epoch_value ^ 32'd1) : epoch_value;
            in_token4 = (mode == 2) ? token_base_value+run4+1 : token_base_value+run4;
            in_token8 = (mode == 2) ? token_base_value+run8+1 : token_base_value+run8;
            in_token12 = (mode == 2) ? token_base_value+run12+1 : token_base_value+run12;
            in_site4 = (mode == 3) ? (x%4)+1 : (x%4);
            in_site8 = (mode == 3) ? (x%8)+1 : (x%8);
            in_site12 = (mode == 3) ? (x%12)+1 : (x%12);
            in_lanes = (mode == 4) ? lanes_value-1 : lanes_value;
            in_last4 = (mode == 5) ? !last4 : last4;
            in_last8 = (mode == 5) ? !last8 : last8;
            in_last12 = (mode == 5) ? !last12 : last12;
            in_data = input_word_mem[memory_index];
        end
    endtask

    task automatic wait_input_accept(input integer special_case, input integer x_value);
        integer check_index;
        reg [255:0] pause_data;
        reg [31:0] pause_epoch;
        reg [31:0] pause_token4;
        begin
            accepted = 0;
            while (!accepted) begin
                @(posedge clk);
                if (in_ready_all) begin
                    accepted = 1;
                end else if (special_case && x_value == 32 && !full_pause_done) begin
                    if (dut4.buffer_full !== 2'b11 || dut8.buffer_full !== 2'b11 ||
                        dut12.buffer_full !== 2'b11)
                        $fatal(1, "input stalled without both transpose buffers being full");
                    if (cfg_ready4 || cfg_ready8 || cfg_ready12)
                        $fatal(1, "configuration became ready before full tile drain");
                    pause_data = in_data;
                    pause_epoch = in_epoch;
                    pause_token4 = in_token4;
                    cfg_channels = 11'd1;
                    cfg_height = 10'd1;
                    cfg_width = 10'd1;
                    cfg_epoch = 32'd999;
                    cfg_token_base = 32'd999;
                    cfg_valid = 1'b1;
                    for (check_index = 0; check_index < 3; check_index = check_index + 1) begin
                        @(posedge clk);
                        if (in_ready_all || dut4.buffer_full !== 2'b11 ||
                            in_data !== pause_data || in_epoch !== pause_epoch ||
                            in_token4 !== pause_token4 || cfg_ready_all)
                            $fatal(1, "two-buffer full backpressure or held input failed");
                        two_buffer_full_checks = two_buffer_full_checks + 1;
                        full_buffer_reload_checks = full_buffer_reload_checks + 1;
                    end
                    @(negedge clk);
                    cfg_valid = 1'b0;
                    out_ready = 1'b1;
                    full_pause_done = 1;
                end
            end
        end
    endtask

    task automatic send_prefix(input integer ci, input integer count);
        integer k;
        reg [63:0] offsets;
        begin
            offsets = case_offset_mem[ci];
            for (k = 0; k < count; k = k + 1) begin
                @(negedge clk);
                prepare_input(ci, 0, 0, k, offsets[31:0]+k, 0);
                wait_input_accept(0, k);
            end
            @(negedge clk);
            in_valid = 1'b0;
        end
    endtask

    task automatic pulse_cancel_abort;
        begin
            @(negedge clk);
            cancel = 1'b1;
            @(posedge clk);
            #1;
            if (active4 || active8 || active12 || out_valid4 || out_valid8 || out_valid12)
                $fatal(1, "cancel did not flush packer-valid state");
            @(negedge clk);
            cancel = 1'b0;
            out_ready = 1'b1;
            cancel_abort_count = cancel_abort_count + 1;
        end
    endtask

    task automatic pulse_reset_abort;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            in_valid = 1'b0;
            @(posedge clk);
            #1;
            if (active4 || active8 || active12 || out_valid4 || out_valid8 || out_valid12)
                $fatal(1, "reset did not flush packer-valid state");
            repeat (2) @(negedge clk);
            rst_n = 1'b1;
            reset_abort_count = reset_abort_count + 1;
        end
    endtask

    task automatic run_valid_case(input integer ci, input integer special_case);
        reg [127:0] cfg;
        reg [63:0] offsets;
        integer c;
        integer h;
        integer w;
        integer epoch_value;
        integer token_base_value;
        integer inputs_here;
        integer outputs_here;
        integer input_base;
        integer output_base;
        integer seq;
        integer gb;
        integer y;
        integer x;
        integer bubble_here;
        begin
            cfg = case_cfg_mem[ci];
            offsets = case_offset_mem[ci];
            c = cfg[10:0];
            h = cfg[20:11];
            w = cfg[30:21];
            epoch_value = cfg[62:31];
            token_base_value = cfg[94:63];
            inputs_here = cfg[110:95];
            outputs_here = cfg[124:111];
            input_base = offsets[31:0];
            output_base = offsets[63:32];
            if (total_output_handshakes != output_base)
                $fatal(1, "expected output offset mismatch before case %0d", ci);
            start_done_count = total_done;
            drive_config(c, h, w, epoch_value, token_base_value);
            out_ready = special_case ? 1'b0 : 1'b1;
            full_pause_done = 0;
            seq = 0;
            for (gb = 0; gb < c; gb = gb + 32) begin
                for (y = 0; y < h; y = y + 1) begin
                    for (x = 0; x < w; x = x + 1) begin
                        @(negedge clk);
                        bubble_here = (!special_case && ((seq % 251) == 97));
                        if (bubble_here) begin
                            in_valid = 1'b0;
                            input_bubble_cycles = input_bubble_cycles + 1;
                            @(posedge clk);
                            @(negedge clk);
                        end
                        prepare_input(ci, gb, y, x, input_base+seq, 0);
                        wait_input_accept(special_case, x);
                        seq = seq + 1;
                    end
                end
            end
            if (seq != inputs_here)
                $fatal(1, "producer input beat count differs for case %0d", ci);
            @(negedge clk);
            in_valid = 1'b0;
            out_ready = 1'b1;
            output_target = output_base + outputs_here;
            done_target = start_done_count + 1;
            while (total_output_handshakes < output_target)
                @(negedge clk);
            while (total_done < done_target)
                @(negedge clk);
            if (total_output_handshakes != output_target || active4 || active8 || active12 ||
                !cfg_ready4 || !cfg_ready8 || !cfg_ready12)
                $fatal(1, "case %0d did not complete and drain exactly", ci);
        end
    endtask

    task automatic send_bad_input(input integer ci, input integer mode);
        reg [127:0] cfg;
        reg [63:0] offsets;
        integer c;
        integer h;
        integer w;
        integer epoch_value;
        integer token_base_value;
        begin
            cfg = case_cfg_mem[ci];
            offsets = case_offset_mem[ci];
            c = cfg[10:0];
            h = cfg[20:11];
            w = cfg[30:21];
            epoch_value = cfg[62:31];
            token_base_value = cfg[94:63];
            drive_config(c, h, w, epoch_value, token_base_value);
            @(negedge clk);
            prepare_input(ci, 0, 0, 0, offsets[31:0], mode);
            @(posedge clk);
            if (!in_ready_all)
                $fatal(1, "malformed beat was not accepted for fail-closed rejection");
            #1;
            if (!error4 || error_code4 != 3'd2 || active4 || out_valid4 ||
                !error8 || !error12)
                $fatal(1, "malformed input metadata did not invalidate active tile mode=%0d", mode);
            @(negedge clk);
            in_valid = 1'b0;
            if (!cfg_ready_all)
                $fatal(1, "input-error invalidation did not return packer to idle");
        end
    endtask

    task automatic send_bad_config(input integer c, input integer h, input integer w,
                                   input integer epoch, input integer token_base);
        begin
            drive_config(c, h, w, epoch, token_base);
            if (!error4 || error_code4 != 3'd1 || active4 ||
                !error8 || !error12 || !cfg_ready_all)
                $fatal(1, "malformed configuration was not rejected c=%0d h=%0d w=%0d", c, h, w);
            @(negedge clk);
        end
    endtask

    initial begin
        $readmemh("native_output_cases.hex", case_cfg_mem);
        $readmemh("native_output_offsets.hex", case_offset_mem);
        $readmemh("native_output_input.hex", input_word_mem);
        $readmemh("native_output_expected.hex", expected_word_mem);

        repeat (4) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        out_ready = 1'b1;

        // Four configuration failures cover zero dimensions, capacity,
        // encoded width range, and token-counter overflow.
        send_bad_config(0, 1, 1, 10, 10);
        send_bad_config(1024, 640, 640, 11, 11);
        send_bad_config(1, 1, 641, 12, 12);
        send_bad_config(1, 2, 1, 13, 32'hffffffff);

        // Each malformed input field must fail closed independently.
        send_bad_input(58, 1);
        send_bad_input(58, 2);
        send_bad_input(58, 3);
        send_bad_input(58, 4);
        send_bad_input(58, 5);

        // Reset and cancel clear a partially filled 512-byte block without
        // clearing its payload; later complete runs must overwrite it.
        drive_config(case_cfg_mem[51][10:0], case_cfg_mem[51][20:11],
                     case_cfg_mem[51][30:21], case_cfg_mem[51][62:31],
                     case_cfg_mem[51][94:63]);
        send_prefix(51, 3);
        pulse_reset_abort();

        drive_config(case_cfg_mem[51][10:0], case_cfg_mem[51][20:11],
                     case_cfg_mem[51][30:21], case_cfg_mem[51][62:31],
                     case_cfg_mem[51][94:63]);
        send_prefix(51, 3);
        pulse_cancel_abort();

        // Cancel a full block while its first word is held under output stall.
        drive_config(case_cfg_mem[58][10:0], case_cfg_mem[58][20:11],
                     case_cfg_mem[58][30:21], case_cfg_mem[58][62:31],
                     case_cfg_mem[58][94:63]);
        out_ready = 1'b0;
        send_prefix(58, 16);
        #1;
        if (!out_valid4 || !out_valid8 || !out_valid12)
            $fatal(1, "completed block missing before stalled cancel: inputs=%0d outputs=%0d S4(full=%b drain=%b x=%0d site=%0d/%0d err=%b code=%0d) S8(full=%b drain=%b x=%0d site=%0d/%0d err=%b code=%0d) S12(full=%b drain=%b x=%0d site=%0d/%0d err=%b code=%0d)",
                   total_input_handshakes, total_output_handshakes,
                   dut4.buffer_full, dut4.drain_buffer, dut4.x_q,
                   dut4.site_index_q, dut4.sites_this_run_q, error4, error_code4,
                   dut8.buffer_full, dut8.drain_buffer, dut8.x_q,
                   dut8.site_index_q, dut8.sites_this_run_q, error8, error_code8,
                   dut12.buffer_full, dut12.drain_buffer, dut12.x_q,
                   dut12.site_index_q, dut12.sites_this_run_q, error12, error_code12);
        repeat (3) @(posedge clk);
        pulse_cancel_abort();

        for (case_index = 0; case_index < CASE_COUNT; case_index = case_index + 1) begin
            cfg_case = case_cfg_mem[case_index][127:125];
            run_valid_case(case_index, cfg_case == 1);
        end

        if (total_output_handshakes != EXPECTED_WORD_COUNT || total_done != CASE_COUNT ||
            total_input_handshakes < INPUT_WORD_COUNT || config_error_count != 4 ||
            input_error_count != 5 || reset_abort_count != 1 || cancel_abort_count != 2 ||
            input_bubble_cycles <= 0 || two_buffer_full_checks < 3 ||
            full_buffer_reload_checks < 3 || input_stall_cycles < 3 ||
            input_stability_checks < 2 || output_stall_cycles < 3 ||
            output_stability_checks < 2 || max_input_burst < 32 || max_output_burst < 8)
            $fatal(1, "coverage missing: outputs=%0d/%0d done=%0d/%0d input=%0d bubbles=%0d input_stalls=%0d input_stability=%0d output_stalls=%0d output_stability=%0d full_checks=%0d reload_checks=%0d max_in=%0d max_out=%0d cfg_errors=%0d in_errors=%0d resets=%0d cancels=%0d",
                   total_output_handshakes, EXPECTED_WORD_COUNT, total_done, CASE_COUNT,
                   total_input_handshakes, input_bubble_cycles, input_stall_cycles,
                   input_stability_checks, output_stall_cycles, output_stability_checks,
                   two_buffer_full_checks, full_buffer_reload_checks, max_input_burst,
                   max_output_burst, config_error_count, input_error_count,
                   reset_abort_count, cancel_abort_count);

        $display("NATIVE_OUTPUT_PACKER_PASS cases=%0d inputs=%0d outputs=%0d done=%0d input_bubbles=%0d input_stalls=%0d input_stability=%0d output_stalls=%0d output_stability=%0d full_buffer_checks=%0d busy_reload_checks=%0d max_input_burst=%0d max_output_burst=%0d config_errors=%0d input_errors=%0d resets=%0d cancels=%0d sites4=1 sites8=1 sites12=1",
                 CASE_COUNT, INPUT_WORD_COUNT, EXPECTED_WORD_COUNT, total_done,
                 input_bubble_cycles, input_stall_cycles, input_stability_checks,
                 output_stall_cycles, output_stability_checks, two_buffer_full_checks,
                 full_buffer_reload_checks, max_input_burst, max_output_burst,
                 config_error_count, input_error_count, reset_abort_count, cancel_abort_count);
        $finish;
    end
endmodule
`default_nettype wire
