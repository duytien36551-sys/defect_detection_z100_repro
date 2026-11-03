`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_axi64_reader;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0, cmd_valid=0, cancel=0, timeout=0, clear_fault=0;
    wire cmd_ready, busy, done, fault;
    reg [31:0] cmd_epoch=1,cmd_address=0;
    reg [13:0] cmd_word_count=0;
    wire [3:0] fault_code;
    wire out_valid; reg out_ready=0;
    wire [31:0] out_epoch;
    wire [12:0] out_index;
    wire [511:0] out_data;
    wire out_last;
    wire [5:0] m_axi_arid;
    wire [31:0] m_axi_araddr;
    wire [3:0] m_axi_arlen;
    wire [2:0] m_axi_arsize;
    wire [1:0] m_axi_arburst;
    wire m_axi_arvalid; reg m_axi_arready=0;
    reg [5:0] m_axi_rid=0;
    reg [63:0] m_axi_rdata=0;
    reg [1:0] m_axi_rresp=0;
    reg m_axi_rlast=0,m_axi_rvalid=0;
    wire m_axi_rready;
    z100_native_axi64_reader dut(.*);

    reg allow_ar=1,allow_r=1,allow_out=1,random_stalls=0,release_missing=0;
    reg pending=0, score=0;
    integer mode=0, response_beat=0, response_length=0;
    reg [31:0] response_base=0;
    reg [31:0] rng=32'h5a710064;
    reg [31:0] expected_base=0,expected_epoch=0;
    integer expected_words=0,seen=0;
    integer frame_checks=0,byte_checks=0,ar_count=0,r_count=0,done_count=0;
    integer invalid_checks=0,fault_checks=0,blocked_checks=0;
    integer ar_hold_checks=0,out_hold_checks=0,r_hold_checks=0,streak=0,max_streak=0;
    reg held_ar=0,held_out=0,held_r=0;
    reg [47:0] old_ar;
    reg [557:0] old_out;
    reg [72:0] old_r;
    integer lane;

    function automatic [7:0] memory_byte(input [31:0] address);
        memory_byte=(address*32'd37)^(address>>8)^(address>>17)^32'h5a;
    endfunction
    function automatic [63:0] memory_beat(input [31:0] address);
        integer b;
        begin
            for(b=0;b<8;b=b+1) memory_beat[b*8+:8]=memory_byte(address+b);
        end
    endfunction
    task automatic tick; begin @(posedge clk); #1; end endtask
    task automatic wait_idle;
        integer polls;
        begin
            polls=0;
            while(!cmd_ready) begin
                tick(); polls=polls+1;
                if(polls>500000) $fatal(1,"idle timeout state=%0d fault=%0d pending=%0d",dut.state,fault_code,pending);
            end
        end
    endtask
    task automatic issue(input [31:0] address, input integer count, input [31:0] ep);
        begin
            wait_idle(); @(negedge clk); #1;
            cmd_address=address;cmd_word_count=count;cmd_epoch=ep;cmd_valid=1;
            tick(); @(negedge clk); #1;cmd_valid=0;
        end
    endtask
    task automatic clear_and_recover;
        begin
            if(busy || pending || m_axi_arvalid) $fatal(1,"attempted clear before AXI drain");
            @(negedge clk); #1;clear_fault=1;tick();
            if(fault || !cmd_ready) $fatal(1,"fault did not clear after drain");
            @(negedge clk); #1;clear_fault=0;
        end
    endtask
    task automatic normal_frame(input [31:0] address, input integer count, input integer stalls);
        integer old_done,polls;
        begin
            mode=0;random_stalls=stalls;allow_ar=1;allow_r=1;allow_out=1;
            expected_base=address;expected_words=count;expected_epoch=32'h17000000+frame_checks;
            seen=0;score=1;old_done=done_count;
            issue(address,count,expected_epoch);
            polls=0;
            while(busy || seen!=count) begin
                tick(); polls=polls+1;
                if(polls>500000) $fatal(1,"normal frame timeout words=%0d seen=%0d state=%0d",count,seen,dut.state);
                if(fault) $fatal(1,"normal frame fault=%0d",fault_code);
            end
            tick();
            if(done_count!=old_done+1 || pending) $fatal(1,"completion without exact final output/AXI drain");
            score=0;frame_checks=frame_checks+1;
        end
    endtask
    task automatic invalid_command(input [31:0] address,input integer count,input [31:0] ep);
        integer before_ar;
        begin
            before_ar=ar_count;issue(address,count,ep);tick();
            if(!fault || fault_code!=1 || busy || ar_count!=before_ar || m_axi_arvalid)
                $fatal(1,"invalid command issued AXI or failed to reject");
            invalid_checks=invalid_checks+1;clear_and_recover();
        end
    endtask
    task automatic check_blocked(input integer polls);
        integer p;
        begin
            @(negedge clk); #1;clear_fault=1;cmd_valid=1;
            for(p=0;p<polls;p=p+1) begin
                tick();
                if(!busy || cmd_ready || done || out_valid || !fault)
                    $fatal(1,"pending AXI abandoned on clear/reload state=%0d",dut.state);
                blocked_checks=blocked_checks+1;
            end
            @(negedge clk); #1;clear_fault=0;cmd_valid=0;
        end
    endtask
    task automatic wait_fault_drain(input integer code);
        integer polls;
        begin
            polls=0;
            while(!fault || busy) begin
                tick();polls=polls+1;
                if(polls>1000) $fatal(1,"fault drain timeout code=%0d state=%0d",code,dut.state);
            end
            if(fault_code!=code || pending || m_axi_arvalid || out_valid)
                $fatal(1,"fault/drain mismatch wanted=%0d got=%0d",code,fault_code);
            fault_checks=fault_checks+1;clear_and_recover();
        end
    endtask

    // Slave/consumer controls update away from the active edge. A held R beat
    // is never changed, even if the random source enable changes meanwhile.
    always @(negedge clk) begin
        rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
        m_axi_arready=allow_ar && (!random_stalls || rng[3:2]!=0);
        out_ready=allow_out && (!random_stalls || rng[5:4]!=0);
        if(!held_r) begin
            m_axi_rvalid=pending && allow_r && (!random_stalls || rng[7:6]!=0) &&
                         !(mode==4 && response_beat>=response_length && !release_missing);
            m_axi_rdata=memory_beat(response_base+response_beat*8);
            m_axi_rid=(mode==1 && response_beat==0) ? 1 : 0;
            m_axi_rresp=(mode==2 && response_beat==0) ? 2 : 0;
            if(mode==3) m_axi_rlast=response_beat==3;
            else if(mode==4) m_axi_rlast=response_beat>=response_length && release_missing;
            else m_axi_rlast=response_beat==response_length-1;
        end
    end
    always @(posedge clk) if(rst_n) begin
        if(held_ar && (!m_axi_arvalid || {m_axi_arid,m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst}!==old_ar))
            $fatal(1,"AR changed while stalled/aborting");
        if(held_ar) ar_hold_checks=ar_hold_checks+1;
        held_ar=m_axi_arvalid && !m_axi_arready;
        old_ar={m_axi_arid,m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst};
        if(held_out && !cancel && !timeout && !fault && !dut.incoming_fault &&
           (!out_valid || {out_epoch,out_index,out_data,out_last}!==old_out))
            $fatal(1,"private output changed under normal backpressure");
        if(held_out && !cancel && !timeout && !fault) out_hold_checks=out_hold_checks+1;
        held_out=out_valid && !out_ready;
        old_out={out_epoch,out_index,out_data,out_last};
        if(held_r && (!m_axi_rvalid || {m_axi_rid,m_axi_rdata,m_axi_rresp,m_axi_rlast}!==old_r))
            $fatal(1,"slave R driver changed while stalled");
        if(held_r) r_hold_checks=r_hold_checks+1;
        held_r=m_axi_rvalid && !m_axi_rready;
        old_r={m_axi_rid,m_axi_rdata,m_axi_rresp,m_axi_rlast};
        if(m_axi_arvalid && m_axi_arready) begin
            if(pending || m_axi_arid!=0 || m_axi_arsize!=3 || m_axi_arburst!=1 ||
                m_axi_arlen>15 || m_axi_araddr[5:0]!=0 ||
                ({1'b0,m_axi_araddr[11:0]}+(m_axi_arlen+1)*8)>4096)
                $fatal(1,"AR geometry/multiple-outstanding violation");
            pending=1;response_base=m_axi_araddr;response_length=m_axi_arlen+1;
            response_beat=0;ar_count=ar_count+1;
        end
        if(m_axi_rvalid && m_axi_rready) begin
            r_count=r_count+1;streak=streak+1;if(streak>max_streak)max_streak=streak;
            if(m_axi_rlast) pending=0;
            else response_beat=response_beat+1;
        end else streak=0;
        if(out_valid && out_ready && score) begin
            if(out_epoch!==expected_epoch || out_index!==seen || out_last!==(seen==expected_words-1))
                $fatal(1,"output metadata mismatch seen=%0d index=%0d last=%0d",seen,out_index,out_last);
            for(lane=0;lane<64;lane=lane+1) begin
                if(out_data[lane*8+:8]!==memory_byte(expected_base+seen*64+lane))
                    $fatal(1,"byte mismatch word=%0d byte=%0d",seen,lane);
                byte_checks=byte_checks+1;
            end
            seen=seen+1;
        end
        if(done) done_count=done_count+1;
    end

    integer f,polls;
    initial begin
        repeat(4) tick();@(negedge clk);#1;rst_n=1;
        normal_frame(32'h10000000,1,0);
        normal_frame(32'h10000fc0,2,0);
        normal_frame(32'h10000f80,63,1);
        normal_frame(32'h10000fc0,64,0);
        normal_frame(32'h10000fc0,65,1);
        normal_frame(32'hfffffc00,16,0);
        normal_frame(32'h10000fc0,8192,1);
        invalid_command(32'h10000000,1,0);
        invalid_command(32'h10000001,1,1);
        invalid_command(32'h10000000,0,1);
        invalid_command(32'h10000000,8193,1);
        invalid_command(32'hffffffc0,2,1);
        random_stalls=0;
        for(f=1;f<=3;f=f+1) begin
            mode=f;issue(32'h10000000,4,1);wait_fault_drain(f+1);
        end
        // Missing RLAST cannot be cleared merely because the declared length
        // was consumed. Hold the real terminator absent for200 polls.
        mode=4;release_missing=0;issue(32'h10000000,4,1);
        polls=0;while(!fault)begin tick();polls=polls+1;if(polls>100)$fatal(1,"missing-last fault absent");end
        check_blocked(200);release_missing=1;wait_fault_drain(5);
        mode=0;release_missing=0;
        // Cancel a stalled AR: the advertised request must still be accepted
        // before its R response can be drained. clear_fault cannot retract it.
        allow_ar=0;issue(32'h10000000,4,1);
        @(negedge clk);#1;cancel=1;tick();@(negedge clk);#1;cancel=0;
        check_blocked(200);allow_ar=1;wait_fault_drain(7);
        // Timeout after AR acceptance while the slave refuses R data.
        allow_r=0;issue(32'h10000000,4,1);
        while(!pending)tick();@(negedge clk);#1;timeout=1;tick();@(negedge clk);#1;timeout=0;
        check_blocked(200);allow_r=1;wait_fault_drain(6);
        // Hold completed output and a partially assembled next word; then
        // cancel and prove all private payload is discarded while AXI drains.
        allow_out=0;issue(32'h10000000,4,1);
        polls=0;while(!out_valid)begin tick();polls=polls+1;if(polls>100)$fatal(1,"held output absent");end
        repeat(20)tick();@(negedge clk);#1;cancel=1;tick();@(negedge clk);#1;cancel=0;
        wait_fault_drain(7);allow_out=1;
        normal_frame(32'h10000fc0,65,1);
        if(frame_checks!=8 || invalid_checks!=5 || fault_checks!=7 || blocked_checks!=600 ||
           max_streak<16 || ar_hold_checks<200 || out_hold_checks==0 || r_hold_checks==0)
            $fatal(1,"coverage frames=%0d invalid=%0d faults=%0d block=%0d streak=%0d ARhold=%0d Ohold=%0d Rhold=%0d",
                frame_checks,invalid_checks,fault_checks,blocked_checks,max_streak,ar_hold_checks,out_hold_checks,r_hold_checks);
        $display("NATIVE_AXI64_READER_PASS frames=%0d bytes=%0d ar=%0d r=%0d invalid=%0d faults=%0d blocked=%0d max_r_streak=%0d ar_hold=%0d out_hold=%0d r_hold=%0d done=%0d capacity_words=8192",
            frame_checks,byte_checks,ar_count,r_count,invalid_checks,fault_checks,blocked_checks,max_streak,
            ar_hold_checks,out_hold_checks,r_hold_checks,done_count);
        $finish;
    end
    initial begin #10000000;$fatal(1,"AXI64 watchdog state=%0d",dut.state);end
endmodule
`default_nettype wire
