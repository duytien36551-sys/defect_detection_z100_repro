`timescale 1ns/1ps
`default_nettype none
module tb_z100_accum33_dsp;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,cancel=0,load_bias=0,enable=0;
    reg signed [31:0] bias=0;
    reg signed [18:0] delta=0;
    wire value_valid,overflow;
    wire signed [32:0] value;
    wire signed [31:0] clamped;
    z100_accum33_dsp dut(.*);
    reg expected_valid=0;
    reg signed [63:0] expected=0;
    reg signed [31:0] expected_clamp;
    integer checks=0,loads=0,updates=0,holds=0,flushes=0,saturations=0;
    integer streak=0,max_streak=0;
    reg [31:0] rng=32'h351bc9e7;
    reg signed [31:0] biases[0:7];
    integer run_id,g,groups;

    task automatic step(input bit ld,en,can,reset_high,
                        input signed[31:0] b,input signed[18:0] d);
        begin
            @(negedge clk);
            load_bias=ld;enable=en;cancel=can;rst_n=reset_high;bias=b;delta=d;
            #1;
            if((can || !reset_high) && (value_valid || value!==0 || clamped!==0 || overflow))
                $fatal(1,"private canceled/invalid arithmetic exposed stale payload");
            if(!reset_high || can) begin
                expected_valid=0; expected=0;flushes=flushes+1;streak=0;
            end else if(ld) begin
                expected_valid=1; expected=$signed(b);loads=loads+1;streak=0;
            end else if(en && expected_valid) begin
                expected=expected+$signed(d);updates=updates+1;streak=streak+1;
                if(streak>max_streak)max_streak=streak;
            end else begin holds=holds+1;streak=0;end
            if(expected>64'sd4294967295 || expected< -64'sd4294967296)
                $fatal(1,"test exceeded exact signed33 admissible bounds");
            if(expected>64'sd2147483647)expected_clamp=32'sh7fffffff;
            else if(expected< -64'sd2147483648)expected_clamp=32'sh80000000;
            else expected_clamp=expected[31:0];
            @(posedge clk);#1;
            if(value_valid!==expected_valid || value!==(expected_valid ? expected[32:0] : 33'd0) ||
               clamped!==(expected_valid ? expected_clamp : 32'd0) ||
               overflow!==(expected_valid && (expected>64'sd2147483647 || expected< -64'sd2147483648)))
                $fatal(1,"feedback mismatch check=%0d got=%h expected=%h valid=%b/%b",checks,value,expected[32:0],value_valid,expected_valid);
            if(overflow)saturations=saturations+1;
            checks=checks+1;
        end
    endtask

    initial begin
        biases[0]=32'sh80000000;biases[1]=32'sh7fffffff;
        biases[2]=-1;biases[3]=0;biases[4]=1;
        biases[5]=-32'sd2147483600;biases[6]=32'sd2147483600;biases[7]=32'sd1234567;
        repeat(25)@(negedge clk);
        step(0,1,0,0,0,0);
        step(0,1,0,1,0,19'sd123); // No update before a legal bias load.
        for(run_id=0;run_id<64;run_id=run_id+1) begin
            case(run_id%6)0:groups=1;1:groups=2;2:groups=9;3:groups=36;4:groups=576;5:groups=1024;endcase
            step(1,1,0,1,biases[run_id%8],19'sh3ffff); // Load wins over update.
            for(g=0;g<groups;g=g+1) begin
                rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
                case(run_id%4)
                  0:step(0,1,0,1,0,19'sh3ffff);
                  1:step(0,1,0,1,0,19'sh40000);
                  default:step(0,1,0,1,0,rng[18:0]);
                endcase
            end
            step(0,0,0,1,32'sh80000000,19'sh40000);
            step(0,0,0,1,32'sh7fffffff,19'sh3ffff);
            if(run_id%8==0)begin
                step(1,1,1,1,32'sh7fffffff,19'sh3ffff);
                step(0,1,0,1,0,19'sh3ffff);
            end
            if(run_id%8==4)begin
                step(0,1,0,0,0,19'sh40000);
                step(0,1,0,1,0,19'sh40000);
            end
        end
        if(loads!=64 || updates<16000 || holds<128 || flushes!=17 || saturations==0 || max_streak!=1024)
            $fatal(1,"feedback coverage insufficient %0d %0d %0d %0d %0d %0d",loads,updates,holds,flushes,saturations,max_streak);
        $display("ACCUM33_DSP_PASS checks=%0d loads=%0d updates=%0d holds=%0d flushes=%0d saturations=%0d ii1_streak=%0d",checks,loads,updates,holds,flushes,saturations,max_streak);
        $finish;
    end
    initial begin #10000000;$fatal(1,"accum33 watchdog");end
endmodule
`default_nettype wire
