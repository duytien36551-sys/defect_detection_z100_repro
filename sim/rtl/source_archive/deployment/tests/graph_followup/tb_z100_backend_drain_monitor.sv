`timescale 1ns/1ps
module tb_z100_backend_drain_monitor;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,command_fire=0,cancel=0,all_io_quiet=0,drain_complete=0,producer_complete=0;
    reg arvalid=0,arready=0,rvalid=0,rready=0,rlast=0;
    reg awvalid=0,awready=0,wvalid=0,wready=0,wlast=0,bvalid=0,bready=0;
    wire [7:0] violations;
    integer checks=0;
    z100_backend_drain_monitor dut(.*);
    task check(input [7:0] expected);
        begin #1;checks=checks+1;if(violations!==expected)
            $fatal(1,"MONITOR_CHECK got=%h expected=%h",violations,expected);end
    endtask
    task tick;
        begin @(posedge clk);@(negedge clk);end
    endtask
    initial begin
        tick();rst_n=1;all_io_quiet=1;drain_complete=1;check(0);
        // An advertised AR remains nonquiet even before acceptance.
        arvalid=1;check(1);all_io_quiet=0;drain_complete=0;check(0);
        arready=1;tick();arvalid=0;arready=0;check(0);
        all_io_quiet=1;drain_complete=1;check(1);
        all_io_quiet=0;drain_complete=0;cancel=1;tick();cancel=0;
        rvalid=1;rready=1;rlast=0;tick();check(0);
        rlast=1;tick();rvalid=0;rready=0;rlast=0;
        all_io_quiet=1;drain_complete=1;check(0);
        producer_complete=1;check(4);producer_complete=0;
        command_fire=1;tick();command_fire=0;
        producer_complete=1;check(0);producer_complete=0;
        // AW -> WLAST -> delayed B must remain owned through the B handshake.
        all_io_quiet=0;drain_complete=0;awvalid=1;awready=1;tick();awvalid=0;awready=0;
        all_io_quiet=1;drain_complete=1;check(1);
        all_io_quiet=0;drain_complete=0;bvalid=1;bready=1;check(128);bvalid=0;bready=0;
        wvalid=1;wready=1;wlast=1;tick();wvalid=0;wready=0;wlast=0;
        all_io_quiet=1;drain_complete=1;check(1);
        all_io_quiet=0;drain_complete=0;cancel=1;tick();cancel=0;
        bvalid=1;bready=1;check(0);tick();bvalid=0;bready=0;
        all_io_quiet=1;drain_complete=1;check(0);
        producer_complete=1;check(4);producer_complete=0;
        drain_complete=0;check(2);drain_complete=1;
        all_io_quiet=0;drain_complete=0;rvalid=1;rready=1;check(16);rvalid=0;rready=0;
        wvalid=1;wready=1;check(64);wvalid=0;wready=0;
        awvalid=1;awready=1;tick();check(32);awvalid=0;awready=0;
        arvalid=1;arready=1;tick();check(8);arvalid=0;arready=0;
        $display("DRAIN_MONITOR_SELFTEST_PASS checks=%0d backend=0 numerical=0 physical=0",checks);
        $finish;
    end
    initial begin #10000;$fatal(1,"monitor watchdog");end
endmodule
