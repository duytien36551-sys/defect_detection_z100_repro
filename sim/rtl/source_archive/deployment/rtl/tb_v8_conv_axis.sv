`timescale 1ns/1ps
module tb_v8_conv_axis;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,cfg_start=0,s_axis_tvalid=0,s_axis_tlast=0,m_axis_tready=0;
    reg [31:0] cfg_tap_count=0,s_axis_tdata=0;
    reg signed [31:0] cfg_bias=0;
    wire cfg_ready,cfg_error,s_axis_tready,m_axis_tvalid,m_axis_tlast;
    wire [31:0] m_axis_tdata;
    v8_conv_axis dut(.clk(clk),.rst_n(rst_n),.cfg_start(cfg_start),
        .cfg_tap_count(cfg_tap_count),.cfg_bias(cfg_bias),.cfg_ready(cfg_ready),
        .cfg_error(cfg_error),.s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),.s_axis_tready(s_axis_tready),
        .s_axis_tlast(s_axis_tlast),.m_axis_tdata(m_axis_tdata),
        .m_axis_tvalid(m_axis_tvalid),.m_axis_tready(m_axis_tready),
        .m_axis_tlast(m_axis_tlast));
    initial begin #2000; $fatal(1,"bridge watchdog cfg_ready=%b tap_ready=%b valid=%b busy=%b pending=%b accepted=%0d expected=%0d",
        cfg_ready,s_axis_tready,m_axis_tvalid,dut.mac_busy,dut.pending_result,dut.accepted,dut.expected); end
    task configure;
        input [31:0] n;
        input signed [31:0] b;
        begin
            @(negedge clk); if(!cfg_ready)$fatal(1,"bridge not idle");
            cfg_tap_count=n;cfg_bias=b;cfg_start=1;
            @(negedge clk);cfg_start=0;
        end
    endtask
    task tap;
        input signed [7:0] a,w;
        input last;
        begin
            @(negedge clk);s_axis_tdata={16'b0,w,a};s_axis_tlast=last;
            s_axis_tvalid=1;
            while(!s_axis_tready) @(negedge clk);
            @(negedge clk);s_axis_tvalid=0;
        end
    endtask
    initial begin
        @(negedge clk);rst_n=1;
        configure(2,10);
        tap(-4,3,0);
        repeat(3) @(negedge clk); // input stall must not complete early
        if(m_axis_tvalid)$fatal(1,"completed during input stall");
        tap(7,-2,1);
        wait(m_axis_tvalid); @(negedge clk);
        if(!m_axis_tvalid||$signed(m_axis_tdata)!=-16||cfg_error||!m_axis_tlast)
            $fatal(1,"AXIS result/error %0d/%b",$signed(m_axis_tdata),cfg_error);
        repeat(3) @(negedge clk); // output backpressure preserves result
        if(!m_axis_tvalid||$signed(m_axis_tdata)!=-16||cfg_ready)
            $fatal(1,"output stall lost result");
        m_axis_tready=1;
        @(negedge clk);m_axis_tready=0;
        @(negedge clk);if(!cfg_ready)$fatal(1,"bridge did not rearm");
        configure(1,0);tap(2,3,0); // missing TLAST is an error
        wait(m_axis_tvalid); @(negedge clk);
        if(!m_axis_tvalid||!cfg_error)$fatal(1,"missing TLAST not flagged");
        $display("PASS V8 AXIS stalls, result and malformed packet");$finish;
    end
endmodule
