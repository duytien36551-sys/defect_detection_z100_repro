`timescale 1ns/1ps
// Structural ownership counterexample, not an AXI abort/reset workaround.
// The deliberately invalid epoch issues no AR, allowing a coordinated test
// reset of the old design after it loses ownership of a faulted command.
module tb_z100_ingress_release_guard;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,av=0,am=0,rv=0,rm=0,bc=0,vc=0,clear=0;
    wire old_ar,new_ar,old_rr,new_rr,old_ov,new_ov,old_om,new_om,old_br,new_br,old_vr,new_vr;
    wire old_bf,new_bf,old_vf,new_vf;
    z100_native_ingress_reader old_dut(.clk(clk),.rst_n(rst_n),.acquire_valid(av),.acquire_mode(am),.acquire_ready(old_ar),
        .release_valid(rv),.release_mode(rm),.release_ready(old_rr),.b_quiet(1'b1),.v_quiet(1'b1),.owner_valid(old_ov),.owner_mode(old_om),
        .b_command(bc),.b_command_ready(old_br),.b_epoch(32'd0),.b_address(32'h10000000),.b_words(14'd1),.b_cancel(1'b0),.b_clear_fault(clear),.b_busy(),.b_done(),.b_fault(old_bf),.b_fault_code(),
        .b_valid(),.b_ready(1'b1),.b_result_epoch(),.b_index(),.b_data(),.b_last(),
        .v_command(vc),.v_command_ready(old_vr),.v_epoch(32'd0),.v_address(32'h10000000),.v_cancel(1'b0),.v_clear_fault(clear),.v_busy(),.v_done(),.v_fault(old_vf),.v_fault_code(),
        .v_valid(),.v_ready(1'b1),.v_result_epoch(),.v_index(),.v_data(),.v_last(),
        .m_axi_arid(),.m_axi_araddr(),.m_axi_arlen(),.m_axi_arsize(),.m_axi_arburst(),.m_axi_arvalid(),.m_axi_arready(1'b0),
        .m_axi_rid(6'd0),.m_axi_rdata(64'd0),.m_axi_rresp(2'd0),.m_axi_rlast(1'b0),.m_axi_rvalid(1'b0),.m_axi_rready());
    z100_native_ingress_reader_v2 new_dut(.clk(clk),.rst_n(rst_n),.acquire_valid(av),.acquire_mode(am),.acquire_ready(new_ar),
        .release_valid(rv),.release_mode(rm),.release_ready(new_rr),.b_quiet(1'b1),.v_quiet(1'b1),.owner_valid(new_ov),.owner_mode(new_om),
        .b_command(bc),.b_command_ready(new_br),.b_epoch(32'd0),.b_address(32'h10000000),.b_words(14'd1),.b_cancel(1'b0),.b_clear_fault(clear),.b_busy(),.b_done(),.b_fault(new_bf),.b_fault_code(),
        .b_valid(),.b_ready(1'b1),.b_result_epoch(),.b_index(),.b_data(),.b_last(),
        .v_command(vc),.v_command_ready(new_vr),.v_epoch(32'd0),.v_address(32'h10000000),.v_cancel(1'b0),.v_clear_fault(clear),.v_busy(),.v_done(),.v_fault(new_vf),.v_fault_code(),
        .v_valid(),.v_ready(1'b1),.v_result_epoch(),.v_index(),.v_data(),.v_last(),
        .m_axi_arid(),.m_axi_araddr(),.m_axi_arlen(),.m_axi_arsize(),.m_axi_arburst(),.m_axi_arvalid(),.m_axi_arready(1'b0),
        .m_axi_rid(6'd0),.m_axi_rdata(64'd0),.m_axi_rresp(2'd0),.m_axi_rlast(1'b0),.m_axi_rvalid(1'b0),.m_axi_rready());
    task tick;begin @(posedge clk);#1;end endtask
    integer mode,retained=0,recovered=0,lost=0;
    initial begin
        for(mode=0;mode<2;mode=mode+1)begin
            @(negedge clk);rst_n=0;repeat(3)tick();@(negedge clk);rst_n=1;am=mode;rm=mode;av=1;
            #1;if(!old_ar||!new_ar)$fatal(1,"release guard acquire");tick();@(negedge clk);av=0;
            bc=!mode;vc=mode;rv=1;
            #1;if(!old_rr||new_rr||!(mode?old_vr&&new_vr:old_br&&new_br))$fatal(1,"same-edge collision was not discriminated");
            tick();
            if(old_ov||!new_ov||new_om!=mode||!old_dut.reader_fault||!new_dut.reader_fault)$fatal(1,"old loss/new retained fault counterexample missing");
            lost=lost+1;retained=retained+1;
            @(negedge clk);bc=0;vc=0;rv=0;
            repeat(3)begin if(!new_ov||new_rr||!(mode?new_vf:new_bf))$fatal(1,"fault lease released");tick();end
            @(negedge clk);clear=1;tick();@(negedge clk);clear=0;tick();
            if(new_dut.reader_fault||!old_dut.reader_fault||!new_ov)$fatal(1,"owned recovery vs orphaned old fault");
            @(negedge clk);rv=1;#1;if(!new_rr)$fatal(1,"fixed quiescent release");tick();@(negedge clk);rv=0;
            if(new_ov||new_dut.reader_busy||new_dut.reader_fault)$fatal(1,"fixed release not quiescent");recovered=recovered+1;
        end
        if(lost!=2||retained!=2||recovered!=2)$fatal(1,"release guard coverage");
        $display("INGRESS_RELEASE_GUARD_PASS old_lost_owners=%0d fixed_retained_owners=%0d fixed_owned_recoveries=%0d modes=2 AXI_AR=0",lost,retained,recovered);
        $finish;
    end
    initial begin #100000;$fatal(1,"release guard watchdog");end
endmodule
