// Behavioral simulation model only. Vivado implementation uses the BUFG
// primitive supplied by the XC7Z100 device library.
module BUFG (input wire I, output wire O);
    assign O = I;
endmodule
