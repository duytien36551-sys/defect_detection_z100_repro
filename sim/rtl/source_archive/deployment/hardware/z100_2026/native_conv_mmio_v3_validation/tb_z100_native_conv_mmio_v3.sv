`timescale 1ns/1ps
`default_nettype none

module tb_z100_native_conv_mmio_v3;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg platform_rst_n = 1'b0;
    reg [31:0] s_axi_awaddr = 0;
    reg s_axi_awvalid = 0;
    wire s_axi_awready;
    reg [31:0] s_axi_wdata = 0;
    reg [3:0] s_axi_wstrb = 0;
    reg s_axi_wvalid = 0;
    wire s_axi_wready;
    wire [1:0] s_axi_bresp;
    wire s_axi_bvalid;
    reg s_axi_bready = 0;
    reg [31:0] s_axi_araddr = 0;
    reg s_axi_arvalid = 0;
    wire s_axi_arready;
    wire [31:0] s_axi_rdata;
    wire [1:0] s_axi_rresp;
    wire s_axi_rvalid;
    reg s_axi_rready = 0;

    wire [863:0] backend_cmd_words;
    wire backend_cmd_valid;
    reg backend_cmd_ready = 0;
    wire backend_cancel;
    wire backend_source_lease_valid;
    wire [31:0] backend_source_lease_generation;
    wire [31:0] backend_source_lease_region_begin;
    wire [32:0] backend_source_lease_region_end;
    wire backend_destination_reservation_valid;
    wire [31:0] backend_destination_reservation_generation;
    wire [31:0] backend_destination_reservation_region_begin;
    wire [32:0] backend_destination_reservation_region_end;

    reg backend_active = 0;
    reg backend_fault = 0;
    reg [3:0] backend_fault_code = 0;
    reg backend_needs_drain = 0;
    reg backend_drain_complete = 1;
    reg backend_all_io_quiet = 1;
    reg [7:0] backend_committed_tiles = 0;
    reg backend_producer_complete = 0;
    reg [31:0] backend_complete_epoch = 0;
    reg [7:0] backend_complete_event = 0;
    reg [31:0] backend_complete_model_crc = 0;
    reg [31:0] backend_complete_job_base = 0;
    reg [31:0] backend_complete_token_base = 0;
    reg [31:0] backend_complete_tag_base = 0;
    reg [31:0] backend_complete_destination_generation = 0;
    reg [7:0] backend_complete_tiles = 0;
    wire irq;

    z100_native_conv_mmio_v2 dut (
        .clk(clk), .platform_rst_n(platform_rst_n),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready),
        .backend_cmd_words(backend_cmd_words), .backend_cmd_valid(backend_cmd_valid),
        .backend_cmd_ready(backend_cmd_ready), .backend_cancel(backend_cancel),
        .backend_source_lease_valid(backend_source_lease_valid),
        .backend_source_lease_generation(backend_source_lease_generation),
        .backend_source_lease_region_begin(backend_source_lease_region_begin),
        .backend_source_lease_region_end(backend_source_lease_region_end),
        .backend_destination_reservation_valid(backend_destination_reservation_valid),
        .backend_destination_reservation_generation(backend_destination_reservation_generation),
        .backend_destination_reservation_region_begin(backend_destination_reservation_region_begin),
        .backend_destination_reservation_region_end(backend_destination_reservation_region_end),
        .backend_active(backend_active), .backend_fault(backend_fault),
        .backend_fault_code(backend_fault_code), .backend_needs_drain(backend_needs_drain),
        .backend_drain_complete(backend_drain_complete), .backend_all_io_quiet(backend_all_io_quiet),
        .backend_committed_tiles(backend_committed_tiles), .backend_producer_complete(backend_producer_complete),
        .backend_complete_epoch(backend_complete_epoch), .backend_complete_event(backend_complete_event),
        .backend_complete_model_crc(backend_complete_model_crc), .backend_complete_job_base(backend_complete_job_base),
        .backend_complete_token_base(backend_complete_token_base), .backend_complete_tag_base(backend_complete_tag_base),
        .backend_complete_destination_generation(backend_complete_destination_generation),
        .backend_complete_tiles(backend_complete_tiles), .irq(irq)
    );

    localparam [31:0] REG_ID       = 32'h000;
    localparam [31:0] REG_VERSION  = 32'h004;
    localparam [31:0] REG_CAPS     = 32'h008;
    localparam [31:0] REG_CONTROL  = 32'h00c;
    localparam [31:0] REG_STATUS   = 32'h010;
    localparam [31:0] REG_FAULT    = 32'h014;
    localparam [31:0] REG_ERROR    = 32'h018;
    localparam [31:0] REG_TILES    = 32'h01c;
    localparam [31:0] REG_SHADOW   = 32'h040;
    localparam [31:0] REG_RESULT   = 32'h100;
    localparam [1:0] OKAY          = 2'b00;
    localparam [1:0] SLVERR        = 2'b10;

    integer aw_first_writes = 0;
    integer w_first_writes = 0;
    integer b_hold_cycles = 0;
    integer r_hold_cycles = 0;
    integer partial_strobes = 0;
    integer readonly_rejects = 0;
    integer unaligned_rejects = 0;
    integer unmapped_rejects = 0;
    integer zero_strobe_noops = 0;
    integer invalid_shadow_rejects = 0;
    integer preaccept_aborts = 0;
    integer preaccept_timeouts = 0;
    integer accept_abort_races = 0;
    integer accept_timeout_races = 0;
    integer early_ack_rejects = 0;
    integer shadow_lock_rejects = 0;
    integer fault_active_quiet_results = 0;
    integer success_results = 0;
    integer raw_identity_checks = 0;
    integer grant_hold_checks = 0;
    integer irq_checks = 0;
    integer zero_reset_checks = 0;

    // Frontend-only backend model: acceptance creates outstanding work.
    // The old model incorrectly stayed quiet through a multi-cycle AXI response,
    // so the DUT correctly released its cancel pulse before the test sampled it.
    always @(posedge clk) begin
        if (platform_rst_n && backend_cmd_valid && backend_cmd_ready) begin
            #1;
            backend_active = 1'b1;
            backend_all_io_quiet = 1'b0;
            backend_drain_complete = 1'b0;
        end
    end
    initial begin #200000; $fatal(1,"Frontend MMIO watchdog"); end

    task fail(input [8*120-1:0] message);
        begin
            $display("FAIL_NATIVE_CONV_MMIO %0s", message);
            $fatal(1);
        end
    endtask

    task wait_cycles(input integer count);
        integer i;
        begin
            for (i = 0; i < count; i = i + 1) begin
                @(posedge clk);
                #1;
            end
        end
    endtask

    task drive_aw(input [31:0] address);
        integer done;
        begin
            done = 0;
            @(negedge clk);
            s_axi_awaddr = address;
            s_axi_awvalid = 1'b1;
            while (!done) begin
                @(posedge clk);
                if (s_axi_awready) begin
                    done = 1;
                    @(negedge clk);
                    s_axi_awvalid = 1'b0;
                end
            end
        end
    endtask

    task drive_w(input [31:0] value, input [3:0] strobe);
        integer done;
        begin
            done = 0;
            @(negedge clk);
            s_axi_wdata = value;
            s_axi_wstrb = strobe;
            s_axi_wvalid = 1'b1;
            while (!done) begin
                @(posedge clk);
                if (s_axi_wready) begin
                    done = 1;
                    @(negedge clk);
                    s_axi_wvalid = 1'b0;
                end
            end
        end
    endtask

    task finish_write(input integer hold_b, output [1:0] response);
        integer i;
        reg [1:0] held_bresp;
        begin
            while (s_axi_bvalid !== 1'b1)
                @(negedge clk);
            held_bresp = s_axi_bresp;
            if (hold_b != 0) begin
                for (i = 0; i < hold_b; i = i + 1) begin
                    @(posedge clk);
                    #1;
                    if (s_axi_bvalid !== 1'b1)
                        fail("BVALID dropped while BREADY was low");
                    if ((^s_axi_bresp) === 1'bx || s_axi_bresp !== held_bresp)
                        fail("BRESP changed or unknown while held");
                    b_hold_cycles = b_hold_cycles + 1;
                end
            end
            @(negedge clk);
            s_axi_bready = 1'b1;
            @(posedge clk);
            response = s_axi_bresp;
            @(negedge clk);
            s_axi_bready = 1'b0;
        end
    endtask

    task axi_write(input [31:0] address, input [31:0] value, input [3:0] strobe,
                   input integer order, input integer hold_b, output [1:0] response);
        integer aw_done;
        integer w_done;
        begin
            if (order == 1) begin
                drive_aw(address);
                aw_first_writes = aw_first_writes + 1;
                drive_w(value, strobe);
            end else if (order == 2) begin
                drive_w(value, strobe);
                w_first_writes = w_first_writes + 1;
                drive_aw(address);
            end else begin
                aw_done = 0;
                w_done = 0;
                @(negedge clk);
                s_axi_awaddr = address;
                s_axi_wdata = value;
                s_axi_wstrb = strobe;
                s_axi_awvalid = 1'b1;
                s_axi_wvalid = 1'b1;
                while (!aw_done || !w_done) begin
                    @(posedge clk);
                    if (s_axi_awready) aw_done = 1;
                    if (s_axi_wready) w_done = 1;
                end
                @(negedge clk);
                s_axi_awvalid = 1'b0;
                s_axi_wvalid = 1'b0;
            end
            finish_write(hold_b, response);
        end
    endtask

    task axi_read(input [31:0] address, input integer hold_r,
                  output [31:0] value, output [1:0] response);
        integer i;
        integer done;
        reg [31:0] held_data;
        reg [1:0] held_resp;
        begin
            done = 0;
            @(negedge clk);
            s_axi_araddr = address;
            s_axi_arvalid = 1'b1;
            while (!done) begin
                @(posedge clk);
                if (s_axi_arready) begin
                    done = 1;
                    @(negedge clk);
                    s_axi_arvalid = 1'b0;
                end
            end
            while (s_axi_rvalid !== 1'b1)
                @(negedge clk);
            held_data = s_axi_rdata;
            held_resp = s_axi_rresp;
            for (i = 0; i < hold_r; i = i + 1) begin
                @(posedge clk);
                #1;
                if (s_axi_rvalid !== 1'b1 || s_axi_rdata !== held_data || s_axi_rresp !== held_resp)
                    fail("RVALID/RDATA/RRESP changed while RREADY was low");
                r_hold_cycles = r_hold_cycles + 1;
            end
            @(negedge clk);
            s_axi_rready = 1'b1;
            @(posedge clk);
            value = s_axi_rdata;
            response = s_axi_rresp;
            @(negedge clk);
            s_axi_rready = 1'b0;
        end
    endtask

    task expect_read(input [31:0] address, input [31:0] expected, input [1:0] expected_resp);
        reg [31:0] value;
        reg [1:0] response;
        begin
            axi_read(address, 0, value, response);
            if (value !== expected || response !== expected_resp) begin
                $display("READ mismatch addr=%h value=%h expected=%h resp=%b expected_resp=%b",
                         address, value, expected, response, expected_resp);
                fail("MMIO read value/response mismatch");
            end
        end
    endtask

    task expect_write(input [31:0] address, input [31:0] value, input [3:0] strobe,
                      input integer order, input [1:0] expected_resp);
        reg [1:0] response;
        begin
            axi_write(address, value, strobe, order, 0, response);
            if (response !== expected_resp) begin
                $display("WRITE mismatch addr=%h data=%h strb=%b resp=%b expected=%b",
                         address, value, strobe, response, expected_resp);
                fail("MMIO write response mismatch");
            end
        end
    endtask

    task write_control(input [31:0] value, input [3:0] strobe, input [1:0] expected_resp);
        begin
            expect_write(REG_CONTROL, value, strobe, 0, expected_resp);
        end
    endtask

    task read_status(output [31:0] status);
        reg [1:0] response;
        begin
            axi_read(REG_STATUS, 0, status, response);
            if (response !== OKAY)
                fail("STATUS read failed");
        end
    endtask

    task configure_backend_quiet;
        begin
            backend_cmd_ready = 1'b0;
            backend_active = 1'b0;
            backend_fault = 1'b0;
            backend_fault_code = 4'd0;
            backend_needs_drain = 1'b0;
            backend_drain_complete = 1'b1;
            backend_all_io_quiet = 1'b1;
            backend_committed_tiles = 8'd0;
            backend_producer_complete = 1'b0;
            backend_complete_epoch = 0;
            backend_complete_event = 0;
            backend_complete_model_crc = 0;
            backend_complete_job_base = 0;
            backend_complete_token_base = 0;
            backend_complete_tag_base = 0;
            backend_complete_destination_generation = 0;
            backend_complete_tiles = 0;
        end
    endtask

    task platform_reset_when_quiet;
        begin
            // The TB mock models a coordinated platform+AXI reset. No test
            // asserts reset while an accepted transaction is outstanding.
            if (!backend_all_io_quiet)
                fail("test attempted platform reset before backend IO was quiet");
            platform_rst_n = 1'b0;
            repeat (2) begin @(posedge clk); #1; end
            @(negedge clk);
            platform_rst_n = 1'b1;
            repeat (2) begin @(posedge clk); #1; end
            zero_reset_checks = zero_reset_checks + 1;
        end
    endtask

    task set_shadow_word(input integer index, input [31:0] value);
        reg [1:0] response;
        begin
            axi_write(REG_SHADOW + index*4, value, 4'hf, index % 3, 0, response);
            if (response !== OKAY) begin
                $display("shadow write failed word=%0d data=%h response=%b", index, value, response);
                fail("shadow preparation write failed");
            end
        end
    endtask

    task prepare_valid_command(input [31:0] accept_timeout, input [31:0] cookie);
        reg [31:0] words [0:26];
        integer i;
        begin
            for (i = 0; i < 27; i = i + 1) words[i] = 0;
            words[0] = cookie;
            words[1] = 200;
            words[2] = 1;
            words[3] = 32'h83f6cd55;
            words[4] = 32'h00001000;
            words[5] = 32'h00002000;
            words[6] = 32'h00003000;
            words[7] = 32'h00000007;
            words[8] = 32'h00100000;
            words[9] = 3;
            words[10] = 32'h00100000;
            words[11] = 32'h00110000;
            words[12] = 0;
            words[13] = 32'h00200000;
            words[14] = 4;
            words[15] = 32'h00200000;
            words[16] = 32'h00220000;
            words[17] = 0;
            words[18] = 32'h00300000;
            words[19] = 173;
            words[20] = 32'h00310000;
            words[21] = 32'h00320000;
            words[22] = 0;
            words[23] = 100;
            words[24] = 200;
            words[25] = 300;
            words[26] = accept_timeout;
            for (i = 0; i < 27; i = i + 1)
                set_shadow_word(i, words[i]);
        end
    endtask

    task start_pending(input [31:0] accept_timeout, input [31:0] cookie);
        reg [1:0] response;
        begin
            backend_cmd_ready = 1'b0;
            prepare_valid_command(accept_timeout, cookie);
            axi_write(REG_CONTROL, 1, 4'hf, 1, 0, response);
            if (response !== OKAY || backend_cmd_valid !== 1'b1 ||
                backend_source_lease_valid !== 1'b1 ||
                backend_destination_reservation_valid !== 1'b1)
                fail("START did not produce a stable pending command/grants");
        end
    endtask

    task write_abort_with_backend_accept;
        reg [1:0] response;
        begin
            @(negedge clk);
            backend_cmd_ready = 1'b1;
            s_axi_awaddr = REG_CONTROL;
            s_axi_wdata = 32'h2;
            s_axi_wstrb = 4'hf;
            s_axi_awvalid = 1'b1;
            s_axi_wvalid = 1'b1;
            @(posedge clk);
            #1;
            if (backend_cmd_valid !== 1'b0 || backend_cancel !== 1'b1)
                fail("same-edge abort/accept did not accept then cancel");
            @(negedge clk);
            s_axi_awvalid = 1'b0;
            s_axi_wvalid = 1'b0;
            finish_write(0, response);
            if (response !== OKAY)
                fail("same-edge abort/accept control write was not acknowledged");
            accept_abort_races = accept_abort_races + 1;
        end
    endtask

    task assert_no_accept_and_ack_local(input [31:0] expected_error);
        reg [31:0] status;
        begin
            read_status(status);
            if (status[2] !== 1'b0 || status[1] !== 1'b0 ||
                backend_cmd_valid !== 1'b0 || backend_cancel !== 1'b0)
                fail("preaccept rejection unexpectedly accepted/cancelled");
            expect_read(REG_ERROR, expected_error, OKAY);
            if (irq !== 1'b1)
                fail("local bridge error did not assert IRQ");
            write_control(32'h8, 4'hf, OKAY);
            if (backend_source_lease_valid !== 1'b0 ||
                backend_destination_reservation_valid !== 1'b0)
                fail("local error ACK did not release unaccepted grants");
        end
    endtask

    reg [31:0] rd;
    reg [31:0] status;
    reg [1:0] resp;
    integer guard;
    integer k;
    initial begin
        configure_backend_quiet();
        repeat (2) begin @(posedge clk); #1; end
        @(negedge clk);
        platform_rst_n = 1'b1;
        repeat (2) begin @(posedge clk); #1; end

        axi_read(REG_ID, 3, rd, resp);
        if (rd !== 32'h5a4e4331 || resp !== OKAY)
            fail("ID readback or R-channel hold failed");
        expect_read(REG_VERSION, 32'h00010000, OKAY);
        expect_read(REG_CAPS, 32'h0000003f, OKAY);
        expect_read(REG_STATUS, 32'h00000081, OKAY);

        expect_write(REG_ID, 32'h0, 4'hf, 0, SLVERR);
        readonly_rejects = readonly_rejects + 1;
        expect_write(REG_SHADOW + 1, 32'h0, 4'hf, 0, SLVERR);
        unaligned_rejects = unaligned_rejects + 1;
        expect_write(32'h200, 32'h0, 4'hf, 0, SLVERR);
        unmapped_rejects = unmapped_rejects + 1;
        axi_read(32'h200, 0, rd, resp);
        if (rd !== 0 || resp !== SLVERR)
            fail("unmapped read did not return zero/SLVERR");
        unmapped_rejects = unmapped_rejects + 1;

        axi_write(REG_SHADOW, 32'h11223344, 4'hf, 1, 3, resp);
        if (resp !== OKAY) fail("held-B shadow write failed");
        expect_write(REG_SHADOW, 32'haabbccdd, 4'b0101, 2, OKAY);
        partial_strobes = partial_strobes + 1;
        expect_read(REG_SHADOW, 32'h11bb33dd, OKAY);
        expect_write(REG_CONTROL, 32'h1, 4'b0000, 0, OKAY);
        zero_strobe_noops = zero_strobe_noops + 1;
        read_status(status);
        if (status[1] || status[2] || backend_cmd_valid)
            fail("zero WSTRB unexpectedly modified CONTROL");

        // Invalid CRC is rejected locally; no backend handshake or result.
        prepare_valid_command(20, 32'h01234567);
        set_shadow_word(3, 0);
        expect_write(REG_CONTROL, 32'h1, 4'hf, 0, SLVERR);
        invalid_shadow_rejects = invalid_shadow_rejects + 1;
        assert_no_accept_and_ack_local(1);

        // Preaccept ABORT withdraws VALID, but retains grants until local ACK.
        start_pending(100, 32'h11112222);
        expect_write(REG_CONTROL, 32'h2, 4'b0000, 0, OKAY);
        zero_strobe_noops = zero_strobe_noops + 1;
        if (backend_cmd_valid !== 1'b1 || backend_cancel !== 1'b0)
            fail("zero WSTRB ABORT modified pending command");
        expect_write(REG_CONTROL, 32'h2, 4'hf, 2, OKAY);
        preaccept_aborts = preaccept_aborts + 1;
        assert_no_accept_and_ack_local(2);

        // Bounded preaccept timeout must not claim backend acceptance.
        start_pending(4, 32'h33334444);
        guard = 0;
        while (backend_cmd_valid && guard < 12) begin
            @(posedge clk); #1; guard = guard + 1;
        end
        if (guard >= 12)
            fail("preaccept timeout did not expire");
        read_status(status);
        if (!status[9] || status[2] || backend_cmd_valid)
            fail("preaccept timeout status/acceptance mismatch");
        preaccept_timeouts = preaccept_timeouts + 1;
        assert_no_accept_and_ack_local(3);

        // Abort written on the same edge as cmd_valid&&cmd_ready: handshake
        // wins, cancel is asserted afterward, and accepted grants remain held.
        start_pending(100, 32'h55556666);
        write_abort_with_backend_accept();
        if (!backend_source_lease_valid || !backend_destination_reservation_valid || !backend_cancel)
            fail("accepted cancel did not retain grants/assert cancel");
        repeat (3) begin
            @(posedge clk); #1;
            if (backend_cancel !== 1'b1 || !backend_source_lease_valid || !backend_destination_reservation_valid)
                fail("cancel/grants changed before IO drained");
            grant_hold_checks = grant_hold_checks + 1;
        end
        backend_active = 1'b1;
        backend_fault = 1'b1;
        backend_fault_code = 4'd0;
        backend_needs_drain = 1'b1;
        backend_drain_complete = 1'b0;
        backend_all_io_quiet = 1'b0;
        backend_committed_tiles = 8'd3;
        #1;
        if (!irq)
            fail("accepted fault/needs-drain did not assert IRQ");
        irq_checks = irq_checks + 1;
        repeat (2) begin
            @(posedge clk); #1;
            if (backend_cancel !== 1'b1 || s_axi_rvalid && s_axi_rdata[8])
                fail("fault drain released cancel or exposed result early");
        end
        backend_all_io_quiet = 1'b1;
        backend_drain_complete = 1'b1;
        backend_needs_drain = 1'b0;
        // Faulted writer status may remain ACTIVE after all IO is quiet.
        backend_active = 1'b1;
        @(posedge clk); #1;
        if (backend_cancel !== 1'b0)
            fail("cancel did not deassert after all_io_quiet");
        read_status(status);
        if (!status[5] || !status[7] || !status[8] || status[4] || !status[3])
            fail("drained fault snapshot status mismatch");
        expect_read(REG_FAULT, 32'd0, OKAY);
        expect_read(REG_RESULT + 0, 32'h55556666, OKAY);
        expect_read(REG_RESULT + 4, 32'd200, OKAY);
        expect_read(REG_RESULT + 8, 32'd1, OKAY);
        expect_read(REG_RESULT + 16, 32'h00001000, OKAY);
        expect_read(REG_RESULT + 28, 32'd4, OKAY);
        expect_read(REG_RESULT + 36, 32'd3, OKAY);
        expect_read(REG_RESULT + 32, 32'd3, OKAY);
        fault_active_quiet_results = fault_active_quiet_results + 1;
        // Fault branch ACK is legal at all_io_quiet even if backend_active is
        // still high. It never clears the backend's sticky fault input.
        write_control(32'h8, 4'hf, OKAY);
        if (backend_source_lease_valid || backend_destination_reservation_valid ||
            backend_cmd_valid || backend_cancel)
            fail("terminal fault ACK retained frontend grants/command");
        if (irq !== 1'b0)
            fail("fault ACK did not clear bridge IRQ after ownership release");
        if (backend_fault !== 1'b1)
            fail("frontend ACK incorrectly cleared backend fault");
        // READY remains low under the sticky backend fault after owner ACK.
        // Shadow updates must remain rejected until a coordinated reset.
        expect_write(REG_SHADOW, 32'hffffffff, 4'hf, 0, SLVERR);
        shadow_lock_rejects = shadow_lock_rejects + 1;

        // Coordinated reset only after the mock AXI fabric reports quiet.
        backend_active = 1'b0;
        backend_fault = 1'b0;
        backend_fault_code = 4'd0;
        backend_needs_drain = 1'b0;
        backend_all_io_quiet = 1'b1;
        backend_drain_complete = 1'b1;
        platform_reset_when_quiet();

        // A timeout at the same edge as the first ready handshake is accepted
        // and routed through cancel/drain, never reported as preaccept timeout.
        backend_cmd_ready = 1'b1;
        prepare_valid_command(1, 32'h77778888);
        axi_write(REG_CONTROL, 32'h1, 4'hf, 0, 0, resp);
        if (resp !== OKAY)
            fail("same-edge timeout START response");
        read_status(status);
        if (!status[2] || status[9] || backend_cmd_valid || !backend_cancel)
            fail("same-edge timeout handshake did not win and cancel");
        accept_timeout_races = accept_timeout_races + 1;
        backend_cmd_ready = 1'b0;
        backend_active = 1'b1;
        backend_all_io_quiet = 1'b0;
        backend_drain_complete = 1'b0;
        backend_fault = 1'b1;
        backend_fault_code = 4'd5;
        backend_needs_drain = 1'b1;
        backend_committed_tiles = 8'd1;
        repeat (2) begin @(posedge clk); #1; end
        backend_all_io_quiet = 1'b1;
        backend_drain_complete = 1'b1;
        backend_needs_drain = 1'b0;
        backend_active = 1'b0;
        @(posedge clk); #1;
        read_status(status);
        if (!status[8] || !status[5] || status[9])
            fail("accepted-timeout cancellation did not drain to fault result");
        write_control(32'h8, 4'hf, OKAY);

        // Normal completion captures raw backend identity, then publishes the
        // stable result only after all IO is quiet and backend_active is low.
        backend_fault = 1'b0;
        backend_fault_code = 0;
        backend_needs_drain = 0;
        backend_drain_complete = 1;
        backend_all_io_quiet = 1;
        backend_active = 0;
        platform_reset_when_quiet();
        backend_cmd_ready = 1'b1;
        prepare_valid_command(100, 32'h1234abcd);
        axi_write(REG_CONTROL, 1, 4'hf, 2, 0, resp);
        if (resp !== OKAY)
            fail("success START was not accepted");
        if (backend_cmd_valid !== 1'b0 || !backend_source_lease_valid ||
            !backend_destination_reservation_valid)
            fail("accepted command did not retain snapshotted grants");
        backend_cmd_ready = 0;
        backend_active = 1;
        backend_all_io_quiet = 0;
        backend_drain_complete = 0;
        // A zero-strobe cancel must be a successful no-op after acceptance.
        expect_write(REG_CONTROL, 32'h4, 4'b0000, 0, OKAY);
        zero_strobe_noops = zero_strobe_noops + 1;
        if (backend_cancel !== 1'b0)
            fail("zero-strobe CANCEL affected accepted request");
        // ACK while accepted/nonterminal is rejected even though a local error
        // becomes sticky; it cannot release the accepted leases.
        expect_write(REG_CONTROL, 32'h8, 4'hf, 0, SLVERR);
        early_ack_rejects = early_ack_rejects + 1;
        read_status(status);
        if (!status[2] || status[8] || !backend_source_lease_valid || !backend_destination_reservation_valid)
            fail("early ACK changed accepted request ownership");
        if (!irq)
            fail("early ACK local error did not assert IRQ");
        irq_checks = irq_checks + 1;
        // Shadow is locked from START through terminal ACK.
        expect_write(REG_SHADOW, 32'hffffffff, 4'hf, 0, SLVERR);
        shadow_lock_rejects = shadow_lock_rejects + 1;
        if (backend_cmd_words[0 +: 32] !== 32'h1234abcd ||
            backend_source_lease_generation !== 32'd3)
            fail("accepted command/grant snapshot changed");
        backend_producer_complete = 1;
        backend_complete_epoch = 201;
        backend_complete_event = 8'd9;
        backend_complete_model_crc = 32'hdeadbeef;
        backend_complete_job_base = 32'h00009000;
        backend_complete_token_base = 32'h0000a000;
        backend_complete_tag_base = 32'h0000b000;
        backend_complete_destination_generation = 32'd44;
        backend_complete_tiles = 8'd7;
        backend_committed_tiles = 8'd7;
        @(posedge clk); #1;
        backend_producer_complete = 0;
        repeat (2) begin
            @(posedge clk); #1;
            if (s_axi_rvalid && s_axi_rdata[8])
                fail("successful result exposed before drain/active-low gate");
        end
        backend_active = 0;
        backend_all_io_quiet = 1;
        backend_drain_complete = 1;
        @(posedge clk); #1;
        read_status(status);
        if (!status[2] || !status[4] || !status[8] || status[5] || !irq)
            fail("normal terminal result status mismatch");
        expect_read(REG_RESULT + 0, 32'h1234abcd, OKAY);
        expect_read(REG_RESULT + 4, 32'd201, OKAY);
        expect_read(REG_RESULT + 8, 32'd9, OKAY);
        expect_read(REG_RESULT + 12, 32'hdeadbeef, OKAY);
        expect_read(REG_RESULT + 16, 32'h00009000, OKAY);
        expect_read(REG_RESULT + 20, 32'h0000a000, OKAY);
        expect_read(REG_RESULT + 24, 32'h0000b000, OKAY);
        expect_read(REG_RESULT + 28, 32'd44, OKAY);
        expect_read(REG_RESULT + 32, 32'd7, OKAY);
        expect_read(REG_RESULT + 36, 32'd3, OKAY);
        success_results = success_results + 1;
        raw_identity_checks = raw_identity_checks + 1;
        // Result remains stable under R backpressure and zero-strobe ACK.
        axi_read(REG_RESULT + 12, 3, rd, resp);
        if (rd !== 32'hdeadbeef || resp !== OKAY)
            fail("result R backpressure/read data mismatch");
        expect_write(REG_CONTROL, 32'h8, 4'b0000, 0, OKAY);
        zero_strobe_noops = zero_strobe_noops + 1;
        read_status(status);
        if (!status[8] || !status[4] || !backend_source_lease_valid)
            fail("zero-strobe ACK released held result/grants");
        // Completion identity is retained exactly as supplied by the backend,
        // including mismatches that a future PS caller must reject.
        expect_read(REG_RESULT + 4, 32'd201, OKAY);
        expect_read(REG_RESULT + 12, 32'hdeadbeef, OKAY);
        raw_identity_checks = raw_identity_checks + 1;
        write_control(32'h8, 4'hf, OKAY);
        if (backend_source_lease_valid || backend_destination_reservation_valid ||
            backend_cmd_valid)
            fail("successful terminal ACK retained command ownership");
        read_status(status);
        if (status[2] || status[4] || status[8] || !status[0] || irq)
            fail("successful terminal ACK failed to release frontend state");

        if (aw_first_writes == 0 || w_first_writes == 0 || b_hold_cycles < 3 || r_hold_cycles < 6 ||
            partial_strobes == 0 || readonly_rejects == 0 || unaligned_rejects == 0 || unmapped_rejects < 2 ||
            zero_strobe_noops < 4 || invalid_shadow_rejects == 0 || preaccept_aborts == 0 ||
            preaccept_timeouts == 0 || accept_abort_races == 0 || accept_timeout_races == 0 ||
            early_ack_rejects == 0 || shadow_lock_rejects == 0 || fault_active_quiet_results == 0 ||
            success_results == 0 || raw_identity_checks < 2 || grant_hold_checks < 3 || irq_checks < 2 ||
            zero_reset_checks < 2)
            fail("coverage gate failed");

        $display("PASS_NATIVE_CONV_MMIO_FRONTEND awfirst=%0d wfirst=%0d bhold=%0d rhold=%0d partial=%0d ro=%0d unaligned=%0d unmapped=%0d zero_strobe=%0d invalid=%0d abort=%0d timeout=%0d abortrace=%0d timeoutrace=%0d earlyack=%0d shadowlock=%0d fault_active_quiet=%0d success=%0d raw_identity=%0d grants=%0d irq=%0d coordinated_reset=%0d",
                 aw_first_writes, w_first_writes, b_hold_cycles, r_hold_cycles, partial_strobes,
                 readonly_rejects, unaligned_rejects, unmapped_rejects, zero_strobe_noops,
                 invalid_shadow_rejects, preaccept_aborts, preaccept_timeouts, accept_abort_races,
                 accept_timeout_races, early_ack_rejects, shadow_lock_rejects,
                 fault_active_quiet_results, success_results, raw_identity_checks,
                 grant_hold_checks, irq_checks, zero_reset_checks);
        $finish;
    end

endmodule

`default_nettype wire
