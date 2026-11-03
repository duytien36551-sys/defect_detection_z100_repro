`timescale 1ns/1ps
`default_nettype none

module tb_z100_window_refill_slot;
    localparam integer DATA_WIDTH = 32;
    localparam integer DEPTH = 16;
    localparam integer ADDR_WIDTH = 4;
    localparam integer GEN_WIDTH = 8;
    localparam integer ROW_WIDTH = 32;
    localparam integer COUNT_WIDTH = 5;
    localparam [1:0] SLOT_INVALID = 2'd0;
    localparam [1:0] SLOT_FILLING = 2'd1;
    localparam [1:0] SLOT_READY = 2'd2;
    localparam [1:0] SLOT_IN_USE = 2'd3;

    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n, cancel;
    reg begin_valid;
    wire begin_ready;
    reg [ROW_WIDTH-1:0] begin_absolute_row;
    reg [GEN_WIDTH-1:0] begin_generation;
    reg [COUNT_WIDTH-1:0] begin_word_count;
    wire begin_reject;
    reg write_valid;
    wire write_ready;
    reg [ROW_WIDTH-1:0] write_absolute_row;
    reg [GEN_WIDTH-1:0] write_generation;
    reg [ADDR_WIDTH-1:0] write_address;
    reg [DATA_WIDTH-1:0] write_data;
    wire write_reject;
    reg commit_valid;
    wire commit_ready;
    reg [ROW_WIDTH-1:0] commit_absolute_row;
    reg [GEN_WIDTH-1:0] commit_generation;
    wire commit_reject;
    reg acquire_valid;
    wire acquire_ready;
    reg [ROW_WIDTH-1:0] acquire_absolute_row;
    reg [GEN_WIDTH-1:0] acquire_generation;
    wire acquire_reject;
    reg [1:0] read_valid;
    wire [1:0] read_ready;
    reg [2*ROW_WIDTH-1:0] read_absolute_row;
    reg [2*GEN_WIDTH-1:0] read_generation;
    reg [2*ADDR_WIDTH-1:0] read_address;
    wire [1:0] read_reject;
    wire [1:0] result_valid;
    reg [1:0] result_ready;
    wire [2*DATA_WIDTH-1:0] result_data;
    wire [2*ROW_WIDTH-1:0] result_absolute_row;
    wire [2*GEN_WIDTH-1:0] result_generation;
    wire [2*ADDR_WIDTH-1:0] result_address;
    reg release_valid;
    wire release_ready;
    wire release_reject;
    wire [1:0] slot_state;
    wire [ROW_WIDTH-1:0] slot_absolute_row;
    wire [GEN_WIDTH-1:0] slot_generation;
    wire [COUNT_WIDTH-1:0] fill_count;
    wire [COUNT_WIDTH-1:0] slot_word_count;

    integer accepted_read_count;
    integer consumed_read_count;
    integer randomized_stall_cycles;
    integer cancel_filling_count;
    integer cancel_ready_count;
    integer cancel_in_use_count;
    integer reset_filling_count;
    integer reset_ready_count;
    integer reset_in_use_count;
    integer generation_wrap_count;
    integer wrong_order_reject_count;
    integer ownership_reject_count;
    integer same_address_dual_count;
    integer observed_accepted = 0;
    integer observed_consumed = 0;
    integer observed_aborted = 0;
    integer failure_count = 0;
    reg [1:0] expected_valid = 0;
    reg [31:0] expected_data [0:1];
    reg [31:0] expected_row [0:1];
    reg [7:0] expected_generation [0:1];
    reg [3:0] expected_address [0:1];
    integer monitor_port;
    reg [31:0] lfsr;
    integer i;
    integer p;

    z100_window_refill_slot #(
        .DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH),
        .GEN_WIDTH(GEN_WIDTH), .ROW_WIDTH(ROW_WIDTH), .COUNT_WIDTH(COUNT_WIDTH)
    ) dut (
        .clk(clk), .rst_n(rst_n), .cancel(cancel),
        .begin_valid(begin_valid), .begin_ready(begin_ready),
        .begin_absolute_row(begin_absolute_row), .begin_generation(begin_generation),
        .begin_word_count(begin_word_count), .begin_reject(begin_reject),
        .write_valid(write_valid), .write_ready(write_ready),
        .write_absolute_row(write_absolute_row), .write_generation(write_generation),
        .write_address(write_address), .write_data(write_data), .write_reject(write_reject),
        .commit_valid(commit_valid), .commit_ready(commit_ready),
        .commit_absolute_row(commit_absolute_row), .commit_generation(commit_generation),
        .commit_reject(commit_reject),
        .acquire_valid(acquire_valid), .acquire_ready(acquire_ready),
        .acquire_absolute_row(acquire_absolute_row), .acquire_generation(acquire_generation),
        .acquire_reject(acquire_reject),
        .read_valid(read_valid), .read_ready(read_ready),
        .read_absolute_row(read_absolute_row), .read_generation(read_generation),
        .read_address(read_address), .read_reject(read_reject),
        .result_valid(result_valid), .result_ready(result_ready), .result_data(result_data),
        .result_absolute_row(result_absolute_row), .result_generation(result_generation),
        .result_address(result_address),
        .release_valid(release_valid), .release_ready(release_ready),
        .release_reject(release_reject), .slot_state(slot_state),
        .slot_absolute_row(slot_absolute_row), .slot_generation(slot_generation),
        .fill_count(fill_count), .slot_word_count(slot_word_count)
    );

    function [31:0] make_word;
        input [31:0] row_id;
        input [7:0] gen_id;
        input [3:0] address;
        begin
            make_word = (row_id * 32'h45d9f3b) ^ ({24'b0, gen_id} * 32'h01010101) ^
                        ({28'b0, address} * 32'h9e3779b9);
        end
    endfunction

    // Count every actual edge handshake, including directed aborted reads.
    // An output consumed and replaced on the same edge uses the old expected
    // entry for the consume and then records the new read. No marker-only score.
    always @(posedge clk) begin
        if (!rst_n || cancel) begin
            if (result_valid != 0) begin
                failure_count=failure_count+1;
                $display("FAIL: abort edge exposed output handshake");
                $fatal(1);
            end
            for (monitor_port=0; monitor_port<2; monitor_port=monitor_port+1)
                if (expected_valid[monitor_port]) observed_aborted=observed_aborted+1;
            expected_valid=0;
        end else begin
            for (monitor_port=0; monitor_port<2; monitor_port=monitor_port+1) begin
                if (result_valid[monitor_port] && result_ready[monitor_port]) begin
                    if (!expected_valid[monitor_port] ||
                        result_data[monitor_port*32 +: 32] !== expected_data[monitor_port] ||
                        result_absolute_row[monitor_port*32 +: 32] !== expected_row[monitor_port] ||
                        result_generation[monitor_port*8 +: 8] !== expected_generation[monitor_port] ||
                        result_address[monitor_port*4 +: 4] !== expected_address[monitor_port]) begin
                        failure_count=failure_count+1;
                        $display("FAIL: edge scoreboard output mismatch");
                        $fatal(1);
                    end
                    observed_consumed=observed_consumed+1;
                    expected_valid[monitor_port]=0;
                end
                if (read_valid[monitor_port] && read_ready[monitor_port]) begin
                    if (expected_valid[monitor_port]) begin
                        failure_count=failure_count+1;
                        $display("FAIL: read overwrote unconsumed scoreboard entry");
                        $fatal(1);
                    end
                    expected_valid[monitor_port]=1;
                    expected_row[monitor_port]=read_absolute_row[monitor_port*32 +: 32];
                    expected_generation[monitor_port]=read_generation[monitor_port*8 +: 8];
                    expected_address[monitor_port]=read_address[monitor_port*4 +: 4];
                    expected_data[monitor_port]=make_word(expected_row[monitor_port],
                        expected_generation[monitor_port],expected_address[monitor_port]);
                    observed_accepted=observed_accepted+1;
                end
            end
        end
    end

    task step;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    task require;
        input condition;
        input [8*96-1:0] message;
        begin
            if (condition !== 1'b1) begin
                failure_count=failure_count+1;
                $display("FAIL: %0s", message);
                $fatal(1);
            end
        end
    endtask

    task reset_now;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            cancel = 1'b0;
            result_ready=2'b11;
            read_valid=2'b11; write_valid=1; commit_valid=1;
            #1;
            require(read_ready==0 && !write_ready && !commit_ready && result_valid==0,
                    "reset suppresses pending output and simultaneous read/write/commit");
            step();
            require(slot_state == SLOT_INVALID, "reset invalidates slot state");
            require(result_valid == 2'b00, "reset clears read results");
            @(negedge clk);
            rst_n = 1'b1;
            read_valid=0; write_valid=0; commit_valid=0; result_ready=0;
        end
    endtask

    task cancel_now;
        begin
            @(negedge clk);
            cancel = 1'b1;
            result_ready=2'b11;
            read_valid=2'b11; write_valid=1; commit_valid=1;
            #1;
            require(read_ready==0 && !write_ready && !commit_ready && result_valid==0,
                    "cancel suppresses pending output and simultaneous read/write/commit");
            step();
            require(slot_state == SLOT_INVALID, "cancel invalidates slot state");
            require(result_valid == 2'b00, "cancel clears read results");
            @(negedge clk);
            cancel = 1'b0;
            read_valid=0; write_valid=0; commit_valid=0; result_ready=0;
        end
    endtask

    task begin_row;
        input [31:0] row_id;
        input [7:0] gen_id;
        input [4:0] word_count;
        begin
            @(negedge clk);
            begin_absolute_row = row_id;
            begin_generation = gen_id;
            begin_word_count = word_count;
            begin_valid = 1'b1;
            #1;
            require(begin_ready, "begin accepted only for idle valid geometry");
            step();
            require(slot_state == SLOT_FILLING, "begin enters FILLING");
            require(slot_absolute_row == row_id && slot_generation == gen_id,
                    "begin records absolute row and wrapping generation");
            require(fill_count == 0 && slot_word_count == word_count,
                    "begin clears count and stores expected word count");
            @(negedge clk);
            begin_valid = 1'b0;
        end
    endtask

    task write_word;
        input [31:0] row_id;
        input [7:0] gen_id;
        input [3:0] address;
        input [31:0] value;
        input expected_accept;
        begin
            @(negedge clk);
            write_absolute_row = row_id;
            write_generation = gen_id;
            write_address = address;
            write_data = value;
            write_valid = 1'b1;
            #1;
            if (expected_accept) begin
                require(write_ready, "sequential refill write ready");
                step();
                require(fill_count == address + 1, "accepted write advances fill count once");
            end else begin
                require(!write_ready, "invalid or owned refill write is not accepted");
                step();
                require(write_reject, "invalid or owned refill write has explicit rejection");
            end
            @(negedge clk);
            write_valid = 1'b0;
        end
    endtask

    task fill_complete_row;
        input [31:0] row_id;
        input [7:0] gen_id;
        input [4:0] word_count;
        integer address;
        begin
            begin_row(row_id, gen_id, word_count);
            for (address = 0; address < word_count; address = address + 1)
                write_word(row_id, gen_id, address[3:0], make_word(row_id, gen_id, address[3:0]), 1'b1);
            @(negedge clk);
            commit_absolute_row = row_id;
            commit_generation = gen_id;
            commit_valid = 1'b1;
            #1;
            require(commit_ready, "commit requires a complete matching fill");
            step();
            require(slot_state == SLOT_READY, "complete commit enters READY");
            @(negedge clk);
            commit_valid = 1'b0;
        end
    endtask

    task acquire_row;
        input [31:0] row_id;
        input [7:0] gen_id;
        begin
            @(negedge clk);
            acquire_absolute_row = row_id;
            acquire_generation = gen_id;
            acquire_valid = 1'b1;
            #1;
            require(acquire_ready, "matching READY row can be acquired");
            step();
            require(slot_state == SLOT_IN_USE, "acquire establishes read ownership");
            @(negedge clk);
            acquire_valid = 1'b0;
        end
    endtask

    task issue_one_read;
        input integer port_id;
        input [31:0] row_id;
        input [7:0] gen_id;
        input [3:0] address;
        input integer stall_count;
        integer k;
        begin
            @(negedge clk);
            read_valid = 2'b00;
            read_valid[port_id] = 1'b1;
            read_absolute_row[port_id*ROW_WIDTH +: ROW_WIDTH] = row_id;
            read_generation[port_id*GEN_WIDTH +: GEN_WIDTH] = gen_id;
            read_address[port_id*ADDR_WIDTH +: ADDR_WIDTH] = address;
            result_ready = 2'b00;
            #1;
            require(read_ready[port_id], "valid owned in-range read is accepted");
            step();

            require(result_valid[port_id], "accepted read produces a result");
            require(result_data[port_id*DATA_WIDTH +: DATA_WIDTH] == make_word(row_id, gen_id, address),
                    "read scoreboard matches current row data");
            require(result_absolute_row[port_id*ROW_WIDTH +: ROW_WIDTH] == row_id &&
                    result_generation[port_id*GEN_WIDTH +: GEN_WIDTH] == gen_id &&
                    result_address[port_id*ADDR_WIDTH +: ADDR_WIDTH] == address,
                    "result retains row generation and address tag");
            @(negedge clk);
            read_valid[port_id] = 1'b0;
            for (k = 0; k < stall_count; k = k + 1) begin
                step();
                require(result_valid[port_id], "stalled result remains valid");
                require(result_data[port_id*DATA_WIDTH +: DATA_WIDTH] == make_word(row_id, gen_id, address),
                        "stalled result data remains stable");
                require(result_generation[port_id*GEN_WIDTH +: GEN_WIDTH] == gen_id,
                        "stalled result generation remains stable");
                randomized_stall_cycles = randomized_stall_cycles + 1;
                @(negedge clk);
            end
            result_ready[port_id] = 1'b1;
            step();

            require(!result_valid[port_id], "consumed result releases its output slot");
            result_ready[port_id] = 1'b0;
        end
    endtask

    task random_read_stream;
        input [31:0] row_id;
        input [7:0] gen_id;
        input integer requests_per_port;
        integer sent0;
        integer sent1;
        integer cycles;
        reg [1:0] accepted;
        reg [1:0] old_valid;
        reg [1:0] old_ready;
        reg [2*DATA_WIDTH-1:0] old_data;
        reg [2*GEN_WIDTH-1:0] old_generation;
        reg [2*ROW_WIDTH-1:0] old_row;
        reg [2*ADDR_WIDTH-1:0] old_address;
        reg [3:0] addr0;
        reg [3:0] addr1;
        begin
            sent0 = 0;
            sent1 = 0;
            cycles = 0;
            while ((sent0 < requests_per_port || sent1 < requests_per_port || result_valid != 0) && cycles < 400) begin
                @(negedge clk);
                lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
                result_ready = {lfsr[5], lfsr[0]};
                read_valid[0] = (sent0 < requests_per_port);
                read_valid[1] = (sent1 < requests_per_port);
                addr0 = sent0[3:0] % slot_word_count;
                addr1 = (sent1[3:0] * 3 + 1) % slot_word_count;
                read_absolute_row[0 +: ROW_WIDTH] = row_id;
                read_absolute_row[ROW_WIDTH +: ROW_WIDTH] = row_id;
                read_generation[0 +: GEN_WIDTH] = gen_id;
                read_generation[GEN_WIDTH +: GEN_WIDTH] = gen_id;
                read_address[0 +: ADDR_WIDTH] = addr0;
                read_address[ADDR_WIDTH +: ADDR_WIDTH] = addr1;
                #1;
                accepted = read_valid & read_ready;
                old_valid = result_valid;
                old_ready = result_ready;
                old_data = result_data;
                old_generation = result_generation;
                old_row = result_absolute_row;
                old_address = result_address;
                if (old_valid != 0 && (old_valid & ~old_ready) != 0)
                    randomized_stall_cycles = randomized_stall_cycles + 1;
                @(posedge clk);
                #1;
                for (p = 0; p < 2; p = p + 1) begin
                    if (accepted[p]) begin
                        if (p == 0) begin
                            require(result_valid[0], "random stream port0 response valid");
                            require(result_data[0 +: DATA_WIDTH] == make_word(row_id, gen_id, addr0),
                                    "random stream port0 scoreboard data");
                            require(result_address[0 +: ADDR_WIDTH] == addr0,
                                    "random stream port0 address tag");
                            sent0 = sent0 + 1;
                        end else begin
                            require(result_valid[1], "random stream port1 response valid");
                            require(result_data[DATA_WIDTH +: DATA_WIDTH] == make_word(row_id, gen_id, addr1),
                                    "random stream port1 scoreboard data");
                            require(result_address[ADDR_WIDTH +: ADDR_WIDTH] == addr1,
                                    "random stream port1 address tag");
                            sent1 = sent1 + 1;
                        end
                        require(result_generation[p*GEN_WIDTH +: GEN_WIDTH] == gen_id &&
                                result_absolute_row[p*ROW_WIDTH +: ROW_WIDTH] == row_id,
                                "random stream result keeps generation and absolute row");

                    end else if (old_valid[p] && old_ready[p]) begin
                        require(!result_valid[p], "consumed random response clears valid");
                    end else if (old_valid[p]) begin
                        require(result_valid[p], "random backpressured response retains valid");
                        require(result_data[p*DATA_WIDTH +: DATA_WIDTH] == old_data[p*DATA_WIDTH +: DATA_WIDTH] &&
                                result_generation[p*GEN_WIDTH +: GEN_WIDTH] == old_generation[p*GEN_WIDTH +: GEN_WIDTH] &&
                                result_absolute_row[p*ROW_WIDTH +: ROW_WIDTH] == old_row[p*ROW_WIDTH +: ROW_WIDTH] &&
                                result_address[p*ADDR_WIDTH +: ADDR_WIDTH] == old_address[p*ADDR_WIDTH +: ADDR_WIDTH],
                                "random backpressured response remains stable");
                    end
                end
                cycles = cycles + 1;
            end
            require(cycles < 400, "random dual-port stream drains under bounded backpressure");
            require(sent0 == requests_per_port && sent1 == requests_per_port,
                    "both random read ports complete requested transactions");
            require(result_valid == 2'b00, "random read stream leaves no outstanding results");
            read_valid = 2'b00;
            result_ready = 2'b00;
        end
    endtask

    initial begin
        rst_n = 1'b0;
        cancel = 1'b0;
        begin_valid = 1'b0;
        begin_absolute_row = 0;
        begin_generation = 0;
        begin_word_count = 0;
        write_valid = 1'b0;
        write_absolute_row = 0;
        write_generation = 0;
        write_address = 0;
        write_data = 0;
        commit_valid = 1'b0;
        commit_absolute_row = 0;
        commit_generation = 0;
        acquire_valid = 1'b0;
        acquire_absolute_row = 0;
        acquire_generation = 0;
        read_valid = 0;
        read_absolute_row = 0;
        read_generation = 0;
        read_address = 0;
        result_ready = 0;
        release_valid = 0;
        accepted_read_count = 0;
        consumed_read_count = 0;
        randomized_stall_cycles = 0;
        cancel_filling_count = 0;
        cancel_ready_count = 0;
        cancel_in_use_count = 0;
        reset_filling_count = 0;
        reset_ready_count = 0;
        reset_in_use_count = 0;
        generation_wrap_count = 0;
        wrong_order_reject_count = 0;
        ownership_reject_count = 0;
        same_address_dual_count = 0;
        lfsr = 32'hc001d00d;

        reset_now();
        require(slot_state == SLOT_INVALID, "initial reset starts INVALID");

        // Invalid geometry and malformed ordered writes receive explicit rejects.
        @(negedge clk);
        begin_word_count = 0;
        begin_valid = 1'b1;
        step();
        require(begin_reject && slot_state == SLOT_INVALID, "zero length begin is rejected");
        @(negedge clk);
        begin_word_count = 17;
        begin_valid = 1'b1;
        step();
        require(begin_reject && slot_state == SLOT_INVALID, "depth overflow begin is rejected");
        @(negedge clk);
        begin_valid = 1'b0;

        begin_row(32'h100, 8'hfe, 5'd8);
        @(negedge clk);
        commit_absolute_row = 32'h100;
        commit_generation = 8'hfe;
        commit_valid = 1'b1;
        step();
        require(commit_reject && slot_state == SLOT_FILLING, "early commit is rejected");
        @(negedge clk);
        commit_valid = 1'b0;
        write_word(32'h100, 8'hfe, 4'd1, make_word(32'h100, 8'hfe, 4'd1), 1'b0);
        wrong_order_reject_count = wrong_order_reject_count + 1;
        write_word(32'h100, 8'hfe, 4'd0, make_word(32'h100, 8'hfe, 4'd0), 1'b1);
        write_word(32'h100, 8'hfe, 4'd0, make_word(32'h100, 8'hfe, 4'd0), 1'b0);
        wrong_order_reject_count = wrong_order_reject_count + 1;
        for (i = 1; i < 8; i = i + 1)
            write_word(32'h100, 8'hfe, i[3:0], make_word(32'h100, 8'hfe, i[3:0]), 1'b1);
        @(negedge clk);
        commit_absolute_row = 32'h101;
        commit_generation = 8'hfe;
        commit_valid = 1'b1;
        step();
        require(commit_reject && slot_state == SLOT_FILLING, "wrong row commit is rejected");
        @(negedge clk);
        commit_absolute_row = 32'h100;
        commit_generation = 8'hfe;
        #1;
        require(commit_ready, "complete matching row can commit");
        step();
        require(slot_state == SLOT_READY, "commit creates READY ownership");
        @(negedge clk);
        commit_valid = 1'b0;

        @(negedge clk);
        acquire_absolute_row = 32'h101;
        acquire_generation = 8'hfe;
        acquire_valid = 1'b1;
        step();
        require(acquire_reject && slot_state == SLOT_READY, "wrong row acquire is rejected");
        @(negedge clk);
        acquire_absolute_row = 32'h100;
        acquire_generation = 8'hfe;
        #1;
        require(acquire_ready, "right row acquire accepted");
        step();
        require(slot_state == SLOT_IN_USE, "acquire enters IN_USE");
        @(negedge clk);
        acquire_valid = 1'b0;

        read_absolute_row[0 +: ROW_WIDTH] = 32'h100;
        read_generation[0 +: GEN_WIDTH] = 8'hfe;
        read_address[0 +: ADDR_WIDTH] = 4'd8;
        read_valid = 2'b01;
        step();
        require(read_reject[0] && !read_ready[0] && result_valid == 2'b00,
                "out-of-range read is explicitly rejected");
        read_valid = 2'b00;

        // Same-address reads are legal on both ports and produce independent
        // tagged results. A blocked result prevents release/refill and holds data.
        read_absolute_row[0 +: ROW_WIDTH] = 32'h100;
        read_absolute_row[ROW_WIDTH +: ROW_WIDTH] = 32'h100;
        read_generation[0 +: GEN_WIDTH] = 8'hfe;
        read_generation[GEN_WIDTH +: GEN_WIDTH] = 8'hfe;
        read_address[0 +: ADDR_WIDTH] = 4'd3;
        read_address[ADDR_WIDTH +: ADDR_WIDTH] = 4'd3;
        read_valid = 2'b11;
        result_ready = 2'b00;
        #1;
        require(read_ready == 2'b11, "both read ports accept same-address access");
        step();

        same_address_dual_count = 1;
        require(result_valid == 2'b11, "same-address dual read returns both ports");
        require(result_data[0 +: DATA_WIDTH] == make_word(32'h100, 8'hfe, 4'd3) &&
                result_data[DATA_WIDTH +: DATA_WIDTH] == make_word(32'h100, 8'hfe, 4'd3),
                "same-address dual read scoreboard agrees");
        @(negedge clk);
        read_valid = 2'b00;
        begin_absolute_row = 32'h101;
        begin_generation = 8'hff;
        begin_word_count = 8;
        begin_valid = 1'b1;
        write_absolute_row = 32'h100;
        write_generation = 8'hfe;
        write_address = 0;
        write_data = 32'hbad0bad0;
        write_valid = 1'b1;
        release_valid = 1'b1;
        #1;
        require(!begin_ready && !write_ready && !release_ready,
                "stalled results and active owner block begin, write, and release");
        step();
        require(begin_reject && write_reject && release_reject,
                "blocked ownership operations are explicitly rejected");
        ownership_reject_count = ownership_reject_count + 3;
        require(result_valid == 2'b11 &&
                result_data[0 +: DATA_WIDTH] == make_word(32'h100, 8'hfe, 4'd3) &&
                result_data[DATA_WIDTH +: DATA_WIDTH] == make_word(32'h100, 8'hfe, 4'd3),
                "both stalled same-generation results remain stable");
        randomized_stall_cycles = randomized_stall_cycles + 1;
        @(negedge clk);
        begin_valid = 1'b0;
        write_valid = 1'b0;
        release_valid = 1'b0;
        result_ready = 2'b11;
        step();

        require(result_valid == 2'b00, "both dual-read results drain");
        @(negedge clk);
        result_ready = 2'b00;

        random_read_stream(32'h100, 8'hfe, 16);
        require(randomized_stall_cycles >= 3, "random read stream exercised backpressure");

        @(negedge clk);
        release_valid = 1'b1;
        #1;
        require(release_ready, "empty output queues allow release");
        step();
        require(slot_state == SLOT_READY, "release returns row to READY");
        @(negedge clk);
        release_valid = 1'b0;

        // release+begin on the same edge has a deterministic policy: release
        // may complete, while begin is rejected and must be retried next cycle.
        acquire_row(32'h100, 8'hfe);
        @(negedge clk);
        release_valid = 1'b1;
        begin_valid = 1'b1;
        begin_absolute_row = 32'h101;
        begin_generation = 8'hff;
        begin_word_count = 8;
        #1;
        require(release_ready && !begin_ready, "simultaneous release/begin rejects begin");
        step();
        require(release_reject == 1'b0 && begin_reject && slot_state == SLOT_READY,
                "release succeeds and concurrent begin is explicitly rejected");
        @(negedge clk);
        release_valid = 1'b0;
        begin_valid = 1'b0;

        fill_complete_row(32'h101, 8'hff, 5'd8);
        acquire_row(32'h101, 8'hff);
        issue_one_read(0, 32'h101, 8'hff, 4'd6, 2);
        @(negedge clk);
        release_valid = 1'b1;
        #1;
        require(release_ready, "generation FF release handshake sampled before edge");
        step();
        require(slot_state == SLOT_READY, "generation FF row releases cleanly");
        @(negedge clk);
        release_valid = 1'b0;

        // Eight-bit generation wraps while absolute row identity advances.
        fill_complete_row(32'h102, 8'h00, 5'd8);
        generation_wrap_count = 1;
        acquire_row(32'h102, 8'h00);
        issue_one_read(1, 32'h102, 8'h00, 4'd2, 1);
        @(negedge clk);
        release_valid = 1'b1;
        step();
        require(slot_state == SLOT_READY, "wrapped generation row releases");
        @(negedge clk);
        release_valid = 1'b0;

        // Cancel and reset each live ownership state. A canceled/stalled row
        // must be completely refilled before a later generation is observable.
        cancel_now();
        cancel_ready_count = 1;

        begin_row(32'h200, 8'h01, 5'd4);
        write_word(32'h200, 8'h01, 4'd0, make_word(32'h200, 8'h01, 4'd0), 1'b1);
        cancel_now();
        cancel_filling_count = 1;

        begin_row(32'h201, 8'h02, 5'd4);
        write_word(32'h201, 8'h02, 4'd0, make_word(32'h201, 8'h02, 4'd0), 1'b1);
        reset_now();
        reset_filling_count = 1;

        fill_complete_row(32'h202, 8'h03, 5'd4);
        cancel_now();
        cancel_ready_count = cancel_ready_count + 1;

        fill_complete_row(32'h203, 8'h04, 5'd4);
        acquire_row(32'h203, 8'h04);
        issue_one_read(0, 32'h203, 8'h04, 4'd1, 1);
        // Recreate an outstanding result to verify cancellation clears it.
        @(negedge clk);
        read_absolute_row[0 +: ROW_WIDTH] = 32'h203;
        read_generation[0 +: GEN_WIDTH] = 8'h04;
        read_address[0 +: ADDR_WIDTH] = 1;
        read_valid = 2'b01;
        result_ready = 2'b00;
        #1;
        require(read_ready[0], "in-use row accepts cancel-stall read");
        step();
        @(negedge clk);
        read_valid = 2'b00;
        require(result_valid[0], "in-use read is held before cancel");
        cancel_now();
        cancel_in_use_count = 1;

        fill_complete_row(32'h204, 8'h05, 5'd4);
        reset_ready_count = 1;
        reset_now();

        fill_complete_row(32'h205, 8'h06, 5'd4);
        acquire_row(32'h205, 8'h06);
        @(negedge clk);
        read_absolute_row[0 +: ROW_WIDTH] = 32'h205;
        read_generation[0 +: GEN_WIDTH] = 8'h06;
        read_address[0 +: ADDR_WIDTH] = 1;
        read_valid = 2'b01;
        result_ready = 2'b00;
        #1;
        require(read_ready[0], "reset-stall row accepts read");
        step();
        @(negedge clk);
        read_valid = 2'b00;
        require(result_valid[0], "reset-stall response is outstanding");
        reset_now();
        reset_in_use_count = 1;

        accepted_read_count=observed_accepted;
        consumed_read_count=observed_consumed;
        require(accepted_read_count >= 32, "read acceptance coverage is meaningful");
        require(consumed_read_count >= 32, "read consumption coverage is meaningful");
        require(randomized_stall_cycles >= 3, "backpressure coverage is nonzero");
        require(cancel_filling_count == 1 && cancel_ready_count >= 2 && cancel_in_use_count == 1,
                "cancel coverage includes FILLING, READY, and IN_USE");
        require(reset_filling_count == 1 && reset_ready_count == 1 && reset_in_use_count == 1,
                "reset coverage includes FILLING, READY, and IN_USE");
        require(generation_wrap_count == 1 && same_address_dual_count == 1,
                "generation wrap and legal dual same-address reads covered");
        require(wrong_order_reject_count >= 2 && ownership_reject_count >= 3,
                "wrong order and ownership rejection coverage is nonzero");
        require(observed_accepted == observed_consumed + observed_aborted && expected_valid == 0,
                "every accepted read must be consumed or explicitly aborted");
        require(observed_aborted == 2 && observed_consumed >= 32,
                "two pending ready-high results aborted with meaningful read coverage");

        if (failure_count != 0) begin
            $display("FAIL: final assertion failures=%0d",failure_count);
            $finish;
        end else
        $display("WINDOW_REFILL_SIM_PASS accepted_reads=%0d consumed_reads=%0d randomized_stall_cycles=%0d cancel_filling=%0d cancel_ready=%0d cancel_in_use=%0d reset_filling=%0d reset_ready=%0d reset_in_use=%0d generation_wrap=%0d wrong_order_rejects=%0d ownership_rejects=%0d same_address_dual=%0d", accepted_read_count, consumed_read_count, randomized_stall_cycles, cancel_filling_count, cancel_ready_count, cancel_in_use_count, reset_filling_count, reset_ready_count, reset_in_use_count, generation_wrap_count, wrong_order_reject_count, ownership_reject_count, same_address_dual_count);
        $display("WINDOW_REFILL_EDGE_SCORE accepted=%0d consumed=%0d aborted=%0d pending=%0d", observed_accepted,observed_consumed,observed_aborted,expected_valid);
        $finish;
    end
endmodule

`default_nettype wire
