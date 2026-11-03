`timescale 1ns/1ps

module s12_phase_counters_tb;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n = 1'b0;
    reg event_start = 1'b0;
    reg [31:0] event_epoch = 32'd0;
    reg [7:0] event_id = 8'd0;
    reg success_terminal = 1'b0;
    reg fault = 1'b0;
    reg all_io_quiet = 1'b1;
    reg [3:0] fault_code = 4'd0;
    reg cancel = 1'b0;
    reg [1:0] read_kind = 2'd0;
    reg m_axi_arvalid = 1'b0;
    reg m_axi_arready = 1'b0;
    reg m_axi_rvalid = 1'b0;
    reg m_axi_rready = 1'b0;
    reg m_axi_rlast = 1'b0;
    reg m_axi_awvalid = 1'b0;
    reg m_axi_awready = 1'b0;
    reg m_axi_wvalid = 1'b0;
    reg m_axi_wready = 1'b0;
    reg [7:0] m_axi_wstrb = 8'd0;
    reg m_axi_wlast = 1'b0;
    reg m_axi_bvalid = 1'b0;
    reg m_axi_bready = 1'b0;
    reg phase_enable = 1'b1;
    reg load_active = 1'b0;
    reg compute_active = 1'b0;
    reg write_active = 1'b0;
    reg mac_good_group = 1'b0;
    reg [10:0] mac_good_slots = 11'd0;
    reg mac_starve = 1'b0;
    reg mac_output_stall = 1'b0;
    reg residency_hit = 1'b0;
    reg residency_miss = 1'b0;
    reg [5:0] read_index = 6'd0;
    wire [31:0] read_data;
    wire snapshot_valid;
    wire [1:0] snapshot_outcome;
    wire snapshot_overflow;
    wire [31:0] snapshot_epoch;
    wire [7:0] snapshot_event;
    wire [3:0] snapshot_fault_code;
    reg [31:0] frozen_counters [0:31];

    z100_native_event_counters_v1 u_counters (
        .clk(clk), .rst_n(rst_n), .event_start(event_start),
        .event_epoch(event_epoch), .event_id(event_id),
        .success_terminal(success_terminal), .fault(fault),
        .all_io_quiet(all_io_quiet), .fault_code(fault_code), .cancel(cancel),
        .read_kind(read_kind), .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready), .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready), .m_axi_rlast(m_axi_rlast),
        .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_wstrb(m_axi_wstrb), .m_axi_wlast(m_axi_wlast),
        .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(m_axi_bready),
        .phase_enable(phase_enable), .load_active(load_active),
        .compute_active(compute_active), .write_active(write_active),
        .mac_good_group(mac_good_group), .mac_good_slots(mac_good_slots),
        .mac_starve(mac_starve), .mac_output_stall(mac_output_stall),
        .residency_hit(residency_hit), .residency_miss(residency_miss),
        .read_index(read_index), .read_data(read_data),
        .snapshot_valid(snapshot_valid), .snapshot_outcome(snapshot_outcome),
        .snapshot_overflow(snapshot_overflow), .snapshot_epoch(snapshot_epoch),
        .snapshot_event(snapshot_event), .snapshot_fault_code(snapshot_fault_code)
    );

    reg [31:0] s_axi_awaddr = 32'd0;
    reg s_axi_awvalid = 1'b0;
    wire s_axi_awready;
    reg [31:0] s_axi_wdata = 32'd0;
    reg [3:0] s_axi_wstrb = 4'd0;
    reg s_axi_wvalid = 1'b0;
    wire s_axi_wready;
    wire [1:0] s_axi_bresp;
    wire s_axi_bvalid;
    reg s_axi_bready = 1'b0;
    reg [31:0] s_axi_araddr = 32'd0;
    reg s_axi_arvalid = 1'b0;
    wire s_axi_arready;
    wire [31:0] s_axi_rdata;
    wire [1:0] s_axi_rresp;
    wire s_axi_rvalid;
    reg s_axi_rready = 1'b0;
    wire [5:0] frontend_counter_index;
    wire [31:0] frontend_counter_data = 32'hcafe0000 + frontend_counter_index;
    wire [863:0] unused_cmd_words;
    wire unused_cmd_valid;
    wire unused_cancel;
    wire unused_source_lease_valid;
    wire [31:0] unused_source_lease_generation;
    wire [31:0] unused_source_lease_begin;
    wire [32:0] unused_source_lease_end;
    wire unused_destination_reservation_valid;
    wire [31:0] unused_destination_reservation_generation;
    wire [31:0] unused_destination_reservation_begin;
    wire [32:0] unused_destination_reservation_end;
    wire unused_irq;
    reg frontend_diag_valid = 1'b1;
    reg [1:0] frontend_diag_outcome = 2'd2;
    reg frontend_diag_overflow = 1'b1;
    reg [31:0] frontend_diag_epoch = 32'h11223344;
    reg [7:0] frontend_diag_event = 8'h5a;
    reg [3:0] frontend_diag_fault_code = 4'h6;

    z100_native_conv_pool_mmio_frontend_v1 u_frontend (
        .clk(clk), .platform_rst_n(rst_n),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready), .s_axi_wdata(s_axi_wdata),
        .s_axi_wstrb(s_axi_wstrb), .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready), .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready), .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready), .backend_cmd_words(unused_cmd_words),
        .backend_cmd_valid(unused_cmd_valid), .backend_cmd_ready(1'b0),
        .backend_cancel(unused_cancel), .backend_source_lease_valid(unused_source_lease_valid),
        .backend_source_lease_generation(unused_source_lease_generation),
        .backend_source_lease_region_begin(unused_source_lease_begin),
        .backend_source_lease_region_end(unused_source_lease_end),
        .backend_destination_reservation_valid(unused_destination_reservation_valid),
        .backend_destination_reservation_generation(unused_destination_reservation_generation),
        .backend_destination_reservation_region_begin(unused_destination_reservation_begin),
        .backend_destination_reservation_region_end(unused_destination_reservation_end),
        .backend_active(1'b0), .backend_fault(1'b0), .backend_fault_code(4'd0),
        .backend_needs_drain(1'b0), .backend_drain_complete(1'b1),
        .backend_all_io_quiet(1'b1), .backend_committed_tiles(8'd0),
        .backend_producer_complete(1'b0), .backend_complete_epoch(32'd0),
        .backend_complete_event(8'd0), .backend_complete_model_crc(32'd0),
        .backend_complete_job_base(32'd0), .backend_complete_token_base(32'd0),
        .backend_complete_tag_base(32'd0),
        .backend_complete_destination_generation(32'd0),
        .backend_complete_tiles(8'd0),
        .backend_diagnostic_counter_index(frontend_counter_index),
        .backend_diagnostic_counter_data(frontend_counter_data),
        .backend_diagnostic_snapshot_valid(frontend_diag_valid),
        .backend_diagnostic_outcome(frontend_diag_outcome),
        .backend_diagnostic_overflow(frontend_diag_overflow),
        .backend_diagnostic_epoch(frontend_diag_epoch),
        .backend_diagnostic_event(frontend_diag_event),
        .backend_diagnostic_fault_code(frontend_diag_fault_code), .irq(unused_irq)
    );

    task tick;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    task counter_idle;
        begin
            success_terminal = 1'b0;
            fault = 1'b0;
            all_io_quiet = 1'b1;
            fault_code = 4'd0;
            cancel = 1'b0;
            read_kind = 2'd0;
            m_axi_arvalid = 1'b0;
            m_axi_arready = 1'b0;
            m_axi_rvalid = 1'b0;
            m_axi_rready = 1'b0;
            m_axi_rlast = 1'b0;
            m_axi_awvalid = 1'b0;
            m_axi_awready = 1'b0;
            m_axi_wvalid = 1'b0;
            m_axi_wready = 1'b0;
            m_axi_wstrb = 8'd0;
            m_axi_wlast = 1'b0;
            m_axi_bvalid = 1'b0;
            m_axi_bready = 1'b0;
            phase_enable = 1'b1;
            load_active = 1'b0;
            compute_active = 1'b0;
            write_active = 1'b0;
            mac_good_group = 1'b0;
            mac_good_slots = 11'd0;
            mac_starve = 1'b0;
            mac_output_stall = 1'b0;
            residency_hit = 1'b0;
            residency_miss = 1'b0;
        end
    endtask

    task start_event;
        input [31:0] epoch;
        input [7:0] event_value;
        begin
            @(negedge clk);
            counter_idle();
            event_epoch = epoch;
            event_id = event_value;
            event_start = 1'b1;
            tick();
            @(negedge clk);
            event_start = 1'b0;
        end
    endtask

    task expect_counter;
        input [5:0] index;
        input [31:0] expected;
        begin
            read_index = index;
            #1;
            if (read_data !== expected)
                $fatal(1, "counter[%0d] expected %08x, got %08x", index, expected, read_data);
        end
    endtask

    task expect_zero_counter_range;
        input [5:0] first_index;
        input [5:0] last_index;
        integer index;
        begin
            for (index=first_index;index<=last_index;index=index+1)
                expect_counter(index,32'd0);
        end
    endtask

    task capture_snapshot_counters;
        integer index;
        begin
            for (index=0;index<32;index=index+1) begin
                read_index = index;
                #1;
                frozen_counters[index] = read_data;
            end
        end
    endtask

    task expect_snapshot_held;
        input [31:0] expected_epoch;
        input [7:0] expected_event;
        integer index;
        begin
            if (!snapshot_valid || snapshot_epoch !== expected_epoch ||
                snapshot_event !== expected_event)
                $fatal(1, "terminal snapshot identity changed after freeze");
            for (index=0;index<32;index=index+1) begin
                read_index = index;
                #1;
                if (read_data !== frozen_counters[index])
                    $fatal(1, "frozen counter[%0d] changed: expected %08x got %08x",
                           index, frozen_counters[index], read_data);
            end
        end
    endtask

    task expect_mmio_read;
        input [31:0] address;
        input [31:0] expected;
        begin
            @(negedge clk);
            s_axi_araddr = address;
            s_axi_arvalid = 1'b1;
            s_axi_rready = 1'b0;
            if (!s_axi_arready)
                $fatal(1, "MMIO AR not ready at %08x", address);
            @(posedge clk);
            #1;
            s_axi_arvalid = 1'b0;
            if (!s_axi_rvalid || s_axi_rresp !== 2'b00 || s_axi_rdata !== expected)
                $fatal(1, "MMIO read %08x expected %08x/OK, got %08x/%b valid=%b",
                       address, expected, s_axi_rdata, s_axi_rresp, s_axi_rvalid);
            @(negedge clk);
            s_axi_rready = 1'b1;
            tick();
            s_axi_rready = 1'b0;
        end
    endtask

    task expect_mmio_write_resp;
        input [31:0] address;
        input [1:0] expected_resp;
        begin
            @(negedge clk);
            s_axi_awaddr = address;
            s_axi_awvalid = 1'b1;
            s_axi_wdata = 32'hffffffff;
            s_axi_wstrb = 4'hf;
            s_axi_wvalid = 1'b1;
            s_axi_bready = 1'b0;
            if (!s_axi_awready || !s_axi_wready)
                $fatal(1, "MMIO write channels not ready at %08x", address);
            @(posedge clk);
            #1;
            s_axi_awvalid = 1'b0;
            s_axi_wvalid = 1'b0;
            if (!s_axi_bvalid || s_axi_bresp !== expected_resp)
                $fatal(1, "MMIO write %08x expected BRESP %b, got %b valid=%b",
                       address, expected_resp, s_axi_bresp, s_axi_bvalid);
            @(negedge clk);
            s_axi_bready = 1'b1;
            tick();
            s_axi_bready = 1'b0;
        end
    endtask

    initial begin
        repeat (3) tick();
        @(negedge clk);
        rst_n = 1'b1;
        tick();

        expect_mmio_read(32'h000, 32'h5a4e4331);
        expect_mmio_read(32'h004, 32'h00010001);
        expect_mmio_read(32'h008, 32'h0000007f);
        expect_mmio_read(32'h100, 32'd0);
        expect_mmio_read(32'h124, 32'd0);
        expect_mmio_read(32'h128, 32'h5a504331);
        expect_mmio_read(32'h12c, 32'd1);
        expect_mmio_read(32'h130, 32'h0000006d);
        expect_mmio_read(32'h134, 32'h11223344);
        expect_mmio_read(32'h138, 32'h0000005a);
        expect_mmio_read(32'h13c, 32'hcafe0000);
        expect_mmio_read(32'h1b8, 32'hcafe001f);
        expect_mmio_read(32'h1bc, 32'd0);
        expect_mmio_read(32'h1fc, 32'd0);
        expect_mmio_write_resp(32'h128, 2'b10);
        expect_mmio_write_resp(32'h13c, 2'b10);
        expect_mmio_write_resp(32'h1fc, 2'b10);
        expect_mmio_read(32'h128, 32'h5a504331);

        start_event(32'h11223344, 8'h5a);
        load_active = 1'b1; compute_active = 1'b1; write_active = 1'b1;
        mac_good_group = 1'b1; mac_good_slots = 11'd15;
        mac_starve = 1'b1; mac_output_stall = 1'b1; residency_miss = 1'b1;
        m_axi_arvalid = 1'b1; m_axi_arready = 1'b0; read_kind = 2'd1;
        tick();
        load_active = 1'b1; compute_active = 1'b1; write_active = 1'b0;
        mac_good_group = 1'b0; mac_starve = 1'b0; mac_output_stall = 1'b0;
        residency_miss = 1'b0; residency_hit = 1'b1;
        m_axi_arvalid = 1'b1; m_axi_arready = 1'b1; read_kind = 2'd1;
        tick();
        read_kind = 2'd2;
        load_active = 1'b0; compute_active = 1'b1; write_active = 1'b1;
        residency_hit = 1'b0;
        m_axi_arvalid = 1'b0; m_axi_arready = 1'b0;
        m_axi_rvalid = 1'b1; m_axi_rready = 1'b1; m_axi_rlast = 1'b0;
        tick();
        read_kind = 2'd3;
        load_active = 1'b1; compute_active = 1'b0; write_active = 1'b1;
        residency_miss = 1'b1;
        m_axi_rvalid = 1'b0; m_axi_rready = 1'b0;
        tick();
        residency_miss = 1'b0;
        load_active = 1'b1; compute_active = 1'b1; write_active = 1'b1;
        mac_good_group = 1'b1; mac_good_slots = 11'd12;
        m_axi_rvalid = 1'b1; m_axi_rready = 1'b1; m_axi_rlast = 1'b1;
        tick();
        load_active = 1'b0; compute_active = 1'b0; write_active = 1'b0;
        mac_good_group = 1'b0; mac_good_slots = 11'd0;
        m_axi_rvalid = 1'b0; m_axi_rready = 1'b0; m_axi_rlast = 1'b0;
        m_axi_awvalid = 1'b1; m_axi_awready = 1'b1;
        tick();
        m_axi_awvalid = 1'b0; m_axi_awready = 1'b0;
        m_axi_wvalid = 1'b1; m_axi_wready = 1'b0;
        tick();
        m_axi_wready = 1'b1; m_axi_wstrb = 8'b10000101; m_axi_wlast = 1'b1;
        tick();
        m_axi_wvalid = 1'b0; m_axi_wready = 1'b0; m_axi_wstrb = 8'd0; m_axi_wlast = 1'b0;
        tick();
        m_axi_bvalid = 1'b1; m_axi_bready = 1'b1; success_terminal = 1'b1;
        tick();
        if (!snapshot_valid || snapshot_outcome !== 2'd1 || snapshot_overflow ||
            snapshot_epoch !== 32'h11223344 || snapshot_event !== 8'h5a ||
            snapshot_fault_code !== 4'd0)
            $fatal(1, "successful event metadata mismatch");
        expect_counter(6'd0, 32'd10);
        expect_counter(6'd1, 32'd1);
        expect_counter(6'd2, 32'd2);
        expect_counter(6'd3, 32'd16);
        expect_counter(6'd4, 32'd0);
        expect_counter(6'd5, 32'd0);
        expect_counter(6'd6, 32'd0);
        expect_counter(6'd7, 32'd0);
        expect_counter(6'd8, 32'd0);
        expect_counter(6'd9, 32'd0);
        expect_counter(6'd10, 32'd1);
        expect_counter(6'd11, 32'd1);
        expect_counter(6'd12, 32'd1);
        expect_counter(6'd13, 32'd1);
        expect_counter(6'd14, 32'd3);
        expect_counter(6'd15, 32'd1);
        expect_counter(6'd16, 32'd0);
        expect_counter(6'd17, 32'd1);
        expect_counter(6'd18, 32'd1);
        expect_counter(6'd19, 32'd2);
        expect_counter(6'd20, 32'd27);
        expect_counter(6'd21, 32'd4);
        expect_counter(6'd22, 32'd1);
        expect_counter(6'd23, 32'd1);
        expect_counter(6'd24, 32'd4);
        expect_counter(6'd25, 32'd4);
        expect_counter(6'd26, 32'd3);
        expect_counter(6'd27, 32'd3);
        expect_counter(6'd28, 32'd3);
        expect_counter(6'd29, 32'd2);
        expect_counter(6'd30, 32'd1);
        expect_counter(6'd31, 32'd2);

        capture_snapshot_counters();
        @(negedge clk);
        event_epoch = 32'hffffffff; event_id = 8'hff;
        success_terminal = 1'b0; fault = 1'b0; cancel = 1'b0;
        m_axi_arvalid = 1'b1; m_axi_arready = 1'b1; read_kind = 2'd3;
        m_axi_rvalid = 1'b1; m_axi_rready = 1'b1; m_axi_rlast = 1'b1;
        m_axi_awvalid = 1'b1; m_axi_awready = 1'b1;
        m_axi_wvalid = 1'b1; m_axi_wready = 1'b1; m_axi_wstrb = 8'hff;
        m_axi_wlast = 1'b1; m_axi_bvalid = 1'b1; m_axi_bready = 1'b1;
        load_active = 1'b1; compute_active = 1'b1; write_active = 1'b1;
        mac_good_group = 1'b1; mac_good_slots = 11'd1023;
        mac_starve = 1'b1; mac_output_stall = 1'b1;
        residency_hit = 1'b1; residency_miss = 1'b1;
        repeat (3) begin
            tick();
            expect_snapshot_held(32'h11223344,8'h5a);
        end

        start_event(32'h55667788, 8'ha5);
        if (snapshot_valid || snapshot_epoch !== 32'd0 || snapshot_event !== 8'd0)
            $fatal(1, "new event did not invalidate prior snapshot identity");
        success_terminal = 1'b1;
        tick();
        if (!snapshot_valid || snapshot_outcome !== 2'd1 ||
            snapshot_epoch !== 32'h55667788 || snapshot_event !== 8'ha5)
            $fatal(1, "successive event identity mismatch");
        expect_counter(6'd0, 32'd1);
        expect_zero_counter_range(6'd1,6'd31);

        start_event(32'h10203040, 8'h61);
        m_axi_arvalid = 1'b1; m_axi_arready = 1'b1; read_kind = 2'd2;
        tick();
        m_axi_arvalid = 1'b0; m_axi_arready = 1'b0; read_kind = 2'd3;
        m_axi_rvalid = 1'b1; m_axi_rready = 1'b1; m_axi_rlast = 1'b0;
        tick();
        read_kind = 2'd1; m_axi_rlast = 1'b1;
        tick();
        m_axi_rvalid = 1'b0; m_axi_rready = 1'b0; m_axi_rlast = 1'b0;
        m_axi_arvalid = 1'b1; m_axi_arready = 1'b1; read_kind = 2'd3;
        tick();
        m_axi_arvalid = 1'b0; m_axi_arready = 1'b0; read_kind = 2'd1;
        m_axi_rvalid = 1'b1; m_axi_rready = 1'b1; m_axi_rlast = 1'b1;
        tick();
        m_axi_rvalid = 1'b0; m_axi_rready = 1'b0; m_axi_rlast = 1'b0;
        success_terminal = 1'b1;
        tick();
        if (!snapshot_valid || snapshot_outcome !== 2'd1 || snapshot_overflow ||
            snapshot_epoch !== 32'h10203040 || snapshot_event !== 8'h61)
            $fatal(1, "parameter/directory read event metadata mismatch");
        expect_counter(6'd0, 32'd6);
        expect_counter(6'd1, 32'd0);
        expect_counter(6'd2, 32'd0);
        expect_counter(6'd3, 32'd0);
        expect_counter(6'd4, 32'd1);
        expect_counter(6'd5, 32'd2);
        expect_counter(6'd6, 32'd16);
        expect_counter(6'd7, 32'd1);
        expect_counter(6'd8, 32'd1);
        expect_counter(6'd9, 32'd8);
        expect_counter(6'd10, 32'd0);
        expect_counter(6'd11, 32'd0);
        expect_zero_counter_range(6'd12,6'd31);

        start_event(32'h50607080, 8'h62);
        m_axi_awvalid = 1'b1; m_axi_awready = 1'b0;
        tick();
        tick();
        m_axi_awready = 1'b1;
        tick();
        m_axi_awvalid = 1'b0; m_axi_awready = 1'b0;
        m_axi_wvalid = 1'b1; m_axi_wready = 1'b0;
        m_axi_wstrb = 8'hff; m_axi_wlast = 1'b0;
        tick();
        tick();
        m_axi_wready = 1'b1; m_axi_wstrb = 8'h00;
        tick();
        m_axi_wstrb = 8'hff; m_axi_wlast = 1'b1;
        tick();
        m_axi_wvalid = 1'b0; m_axi_wready = 1'b0;
        m_axi_wstrb = 8'd0; m_axi_wlast = 1'b0;
        tick();
        tick();
        m_axi_bvalid = 1'b1; m_axi_bready = 1'b1; success_terminal = 1'b1;
        tick();
        if (!snapshot_valid || snapshot_outcome !== 2'd1 || snapshot_overflow ||
            snapshot_epoch !== 32'h50607080 || snapshot_event !== 8'h62)
            $fatal(1, "backpressure/WSTRB event metadata mismatch");
        expect_counter(6'd0, 32'd10);
        expect_counter(6'd12, 32'd1);
        expect_counter(6'd13, 32'd2);
        expect_counter(6'd14, 32'd8);
        expect_counter(6'd15, 32'd1);
        expect_counter(6'd16, 32'd2);
        expect_counter(6'd17, 32'd2);
        expect_counter(6'd18, 32'd2);
        expect_zero_counter_range(6'd1,6'd11);
        expect_zero_counter_range(6'd19,6'd31);

        start_event(32'h99aabbcc, 8'h33);
        @(negedge clk);
        u_counters.counters_q[0] = 32'hffffffff;
        success_terminal = 1'b1;
        tick();
        if (!snapshot_valid || !snapshot_overflow || snapshot_outcome !== 2'd1)
            $fatal(1, "saturating overflow metadata mismatch");
        expect_counter(6'd0, 32'hffffffff);
        expect_zero_counter_range(6'd1,6'd31);

        start_event(32'h99aabbcd, 8'h34);
        u_counters.counters_q[31] = 32'hffffffff;
        residency_miss = 1'b1;
        tick();
        if (!u_counters.overflow_q || u_counters.counters_q[31] !== 32'hffffffff)
            $fatal(1, "counter overflow did not saturate and set sticky state");
        @(negedge clk);
        residency_miss = 1'b0;
        u_counters.counters_q[31] = 32'd0;
        success_terminal = 1'b1;
        tick();
        if (!snapshot_valid || !snapshot_overflow || snapshot_outcome !== 2'd1 ||
            snapshot_epoch !== 32'h99aabbcd || snapshot_event !== 8'h34)
            $fatal(1, "overflow status did not remain sticky through a clean terminal edge");
        expect_counter(6'd0, 32'd2);
        expect_counter(6'd31, 32'd0);
        expect_zero_counter_range(6'd1,6'd30);

        start_event(32'hdeadbeef, 8'h42);
        if (snapshot_valid || snapshot_overflow || snapshot_outcome !== 2'd0 ||
            snapshot_epoch !== 32'd0 || snapshot_event !== 8'd0)
            $fatal(1, "event start did not reset frozen status and identity");
        expect_counter(6'd0, 32'd0);
        expect_counter(6'd31, 32'd0);
        cancel = 1'b1; fault = 1'b1; fault_code = 4'd2; all_io_quiet = 1'b0;
        tick();
        if (snapshot_valid)
            $fatal(1, "cancel snapshot published before drain completed");
        cancel = 1'b0; all_io_quiet = 1'b1;
        tick();
        if (snapshot_valid) $fatal(1, "Fault publication was not delayed");
        tick();
        if (!snapshot_valid || snapshot_outcome !== 2'd2 ||
            snapshot_epoch !== 32'hdeadbeef || snapshot_event !== 8'h42 ||
            snapshot_fault_code !== 4'd2)
            $fatal(1, "cancel-after-drain metadata mismatch");
        expect_counter(6'd0, 32'd2);
        expect_zero_counter_range(6'd1,6'd31);

        start_event(32'hdeadbef0, 8'h43);
        fault = 1'b1; fault_code = 4'd5; all_io_quiet = 1'b0;
        tick();
        if (snapshot_valid)
            $fatal(1, "non-cancel fault snapshot published before I/O quiet");
        all_io_quiet = 1'b1;
        tick();
        if (snapshot_valid) $fatal(1, "Fault publication was not delayed");
        tick();
        if (!snapshot_valid || snapshot_outcome !== 2'd3 || snapshot_overflow ||
            snapshot_epoch !== 32'hdeadbef0 || snapshot_event !== 8'h43 ||
            snapshot_fault_code !== 4'd5)
            $fatal(1, "non-cancel fault terminal metadata mismatch");
        expect_counter(6'd0, 32'd2);
        expect_zero_counter_range(6'd1,6'd31);

        // First terminal edge code0, registered backend code4 at T+1.
        start_event(32'habcd0001, 8'h51);
        fault=1;fault_code=0;all_io_quiet=1;
        m_axi_bvalid=1;m_axi_bready=1;
        u_counters.counters_q[15]=32'hffffffff;
        tick();
        if(snapshot_valid || !u_counters.fault_publish_pending_q || !snapshot_overflow)
            $fatal(1,"Fault pending/terminal overflow");
        if(u_counters.snapshot_q[0]!==1 || u_counters.snapshot_q[15]!==32'hffffffff)
            $fatal(1,"Original terminal edge was not counted exactly");
        @(negedge clk);fault_code=4;
        tick();
        if(!snapshot_valid || snapshot_fault_code!==4 || snapshot_outcome!==3 ||
           snapshot_epoch!==32'habcd0001 || snapshot_event!==8'h51)
            $fatal(1,"T+1 fault metadata publication");
        expect_counter(0,1);expect_counter(15,32'hffffffff);
        capture_snapshot_counters();
        @(negedge clk);fault_code=7;cancel=1;
        tick();
        if(snapshot_fault_code!==4 || snapshot_outcome!==3)
            $fatal(1,"Published fault metadata changed");
        expect_snapshot_held(32'habcd0001,8'h51);

        // Reset wins over a pending fault publication, with no stale reappearance.
        start_event(32'habcd0002,8'h52);
        fault=1;fault_code=0;all_io_quiet=1;tick();
        if(snapshot_valid || !u_counters.fault_publish_pending_q)$fatal(1,"Pending reset setup");
        @(negedge clk);rst_n=0;tick();
        if(snapshot_valid || u_counters.fault_publish_pending_q)$fatal(1,"Reset failed to discard pending");
        @(negedge clk);counter_idle();rst_n=1;tick();tick();
        if(snapshot_valid)$fatal(1,"Stale publication after reset");

        // Artificial simultaneous new event also has priority over old pending.
        start_event(32'habcd0003,8'h53);
        fault=1;fault_code=0;all_io_quiet=1;tick();
        if(snapshot_valid)$fatal(1,"Pending event setup");
        @(negedge clk);counter_idle();event_start=1;event_epoch=32'habcd0004;event_id=8'h54;
        tick();
        if(snapshot_valid || u_counters.fault_publish_pending_q || !u_counters.event_open_q)
            $fatal(1,"New event did not discard stale pending snapshot");
        @(negedge clk);event_start=0;success_terminal=1;tick();
        if(!snapshot_valid || snapshot_outcome!==1 || snapshot_fault_code!==0 ||
           snapshot_epoch!==32'habcd0004 || snapshot_event!==8'h54)
            $fatal(1,"Success priority/identity after pending discard");
        expect_counter(0,1);
        $display("FAULT_PUBLICATION_T_PLUS_ONE_PASS terminal_counts_unchanged=1 reset_priority=1 event_priority=1");
        $display("PASS: S12 counter and MMIO checks");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "TIMEOUT: S12 counter and MMIO checks did not complete");
    end
endmodule
