// Behavioral simulation model only. Vivado implementation uses the vendor
// BUFG primitive instantiated in z100_tile_reuse_sync_fixture_top.v.
module BUFG(input wire I, output wire O);
    assign O = I;
endmodule
