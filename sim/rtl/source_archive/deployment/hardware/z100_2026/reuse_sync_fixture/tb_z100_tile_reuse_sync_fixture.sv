module tb_z100_tile_reuse_sync_fixture;
    reg clk = 1'b0;
    wire [31:0] signature;
    integer cycles = 0;
    integer signature_changes = 0;
    reg [31:0] previous_signature = 32'd0;

    always #5 clk = ~clk;

    z100_tile_reuse_sync_fixture_top dut (
        .clk(clk),
        .signature(signature)
    );

    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (signature != previous_signature) begin
            previous_signature <= signature;
            signature_changes <= signature_changes + 1;
        end
        if (cycles == 800) begin
            if (signature_changes < 8 || signature == 0) begin
                $display("SYNC_FIXTURE_SIM_FAIL changes=%0d signature=%08x",
                         signature_changes, signature);
                $finish(1);
            end
            $display("SYNC_FIXTURE_SIM_PASS cycles=%0d changes=%0d signature=%08x",
                     cycles, signature_changes, signature);
            $finish;
        end
    end
endmodule
