`timescale 1ns/1ps
module tb_z100_maxpool_signed_pairs;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0,in_valid=0,in_first=0,in_last=0,out_ready=0;
    reg [31:0] in_epoch=200,in_token=1;
    reg [6:0] in_lanes=80;
    reg [79:0] in_mask={80{1'b1}};
    reg [639:0] in_data=0;
    wire in_ready,out_valid,error_valid,active;
    wire [31:0] out_epoch,out_token;
    wire [6:0] out_lanes;
    wire [639:0] out_data;
    reg [639:0] a,b,expected;
    integer v,l,index,aa,bb,n,pairs=0,stalls=0;
    z100_maxpool_vector dut(.*);
    task tick;begin @(posedge clk);#1;end endtask
    task send(input bit first_arg,last_arg,input [639:0] data_arg);
        begin
            @(negedge clk);in_first=first_arg;in_last=last_arg;in_data=data_arg;in_valid=1;#1;
            if(!in_ready)$fatal(1,"unexpected ready in direct pair replay");
            tick();@(negedge clk);in_valid=0;
        end
    endtask
    initial begin
        repeat(5)tick();@(negedge clk);rst_n=1;
        send(1,1,{80{8'hef}});
        if(!out_valid||out_token!=1)$fatal(1,"first pending output");
        @(negedge clk);in_valid=1;in_first=1;in_last=1;in_token=2;in_data={80{8'hdf}};
        repeat(3)begin
            #1;if(in_ready||!out_valid||out_token!=1||out_data!=={80{8'hef}})$fatal(1,"input/output hold boundary");
            tick();stalls=stalls+1;
        end
        @(negedge clk);out_ready=1;tick();
        if(!out_valid||out_token!=2||out_data!=={80{8'hdf}})$fatal(1,"sameedge drain/refill");
        @(negedge clk);in_valid=0;tick();
        if(out_valid||active)$fatal(1,"refill result failed to drain");
        for(v=0;v<820;v=v+1)begin
            n=(65536-v*80>=80)?80:65536-v*80;
            a=0;b=0;expected=0;
            for(l=0;l<n;l=l+1)begin
                index=v*80+l;aa=(index%256)-128;bb=(index/256)-128;
                a[l*8+:8]=aa;b[l*8+:8]=bb;expected[l*8+:8]=(aa>bb)?aa:bb;
                pairs=pairs+1;
            end
            in_lanes=n;in_token=v+3;out_ready=0;
            send(1,0,a);send(0,1,b);
            if(!out_valid||out_token!=v+3||out_epoch!=200||out_lanes!=n||out_data!==expected||error_valid)
                $fatal(1,"signed pair mismatch vector%0d",v);
            @(negedge clk);out_ready=1;tick();
            if(out_valid)$fatal(1,"pair result did not drain");
        end
        if(pairs!=65536||stalls!=3)$fatal(1,"signed pair coverage");
        $display("MAXPOOL_SIGNED_PAIR_PASS pairs=65536 vectors=820 input_stalls=3 simultaneous_drain_refill=1 min128_covered=1");
        $finish;
    end
endmodule
