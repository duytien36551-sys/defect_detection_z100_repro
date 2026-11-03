`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_source_read;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,abort=0,recover=0,cmd_valid=0,out_ready=0;
    reg[2:0] cmd_slot=0;reg[31:0] cmd_epoch=200,cmd_generation=7,cmd_address=32'h10000080,cmd_timeout_cycles=100000,cmd_tag=100;
    reg[15:0] cmd_tensor_id=42;reg[13:0] cmd_words=4;
    wire cmd_ready,active,fault,lease_held,done;wire[3:0] fault_code;
    wire[2:0] query_slot,manager_opcode,manager_slot;
    wire query_committed,query_fault;wire[31:0] query_epoch,query_generation,query_address,query_bytes;wire[15:0] query_tensor_id;
    wire manager_valid,manager_ready,manager_response_valid,manager_response_ready;
    wire[31:0] manager_tag,manager_epoch,manager_generation,manager_response_tag;wire[15:0] manager_tensor_id;
    wire[2:0] manager_response_slot;wire[3:0] manager_response_code;
    wire reader_command,reader_command_ready,reader_busy,reader_done,reader_fault,reader_cancel,reader_clear,reader_valid,reader_ready,reader_last;
    wire[31:0] reader_epoch,reader_address,reader_result_epoch;wire[13:0] reader_words;wire[12:0] reader_index;wire[511:0] reader_data;
    wire out_valid,out_last;wire[31:0] out_epoch;wire[12:0] out_index;wire[511:0] out_data;
    z100_native_source_read control(.*);
    reg hv=0;wire hr,rv;reg rr=0;
    reg[2:0] hop=0;reg[31:0] htag=32'h80000000,he=200,hg=7;reg[15:0] hid=42;
    wire[31:0] rt;wire[2:0] rs;wire[3:0] rc;
    reg block_manager=0,block_response=0,spoof_manager_tag=0,spoof_reader_epoch=0;
    wire selected_host=hv;
    wire mv=hv||manager_valid&&!block_manager;
    wire mr;
    assign hr=mr&&hv;
    assign manager_ready=mr&&!hv&&!block_manager;
    wire host_response=rt[31];
    assign manager_response_valid=rv&&!host_response&&!block_response;
    assign manager_response_tag=rt^(spoof_manager_tag ? 32'd1 : 32'd0);assign manager_response_slot=rs;assign manager_response_code=rc;
    wire[6:0] committed_slots,fault_slots,active_slots;wire[7:0] readers;
    wire[6:0] quiet={6'b111111,!reader_busy};
    z100_native_tensor_slots_bounded_v2 slots(.clk(clk),.rst_n(rst_n),.io_quiescent(quiet),
        .cmd_valid(mv),.cmd_ready(mr),.cmd_opcode(selected_host?hop:manager_opcode),.cmd_slot(selected_host?3'd0:manager_slot),
        .cmd_tag(selected_host?htag:manager_tag),.cmd_epoch(selected_host?he:manager_epoch),.cmd_generation(selected_host?hg:manager_generation),
        .cmd_address(32'h10000000),.cmd_tensor_id(selected_host?hid:manager_tensor_id),.cmd_channels(11'd32),.cmd_height(10'd1),.cmd_width(10'd32),
        .cmd_first_row(10'd0),.cmd_tile_height(10'd1),.cmd_success(1'b1),
        .response_valid(rv),.response_ready(host_response?rr:manager_response_ready&&!block_response),.response_tag(rt),.response_slot(rs),.response_code(rc),
        .committed_slots(committed_slots),.fault_slots(fault_slots),.active_slots(active_slots),
        .query_slot(query_slot),.query_committed(query_committed),.query_active(),.query_fault(query_fault),.query_readers(readers),
        .query_epoch(query_epoch),.query_generation(query_generation),.query_address(query_address),.query_bytes(query_bytes),.query_tensor_id(query_tensor_id),
        .query_channels(),.query_covered_rows(),.query_height(),.query_width());
    wire[5:0] arid;wire[31:0] araddr;wire[3:0] arlen;wire[2:0] arsize;wire[1:0] arburst;wire arvalid,rready;
    reg block_ar=0,block_r=0,inject_resp=0;
    reg rvalid=0,rlast=0;reg[63:0] rdata=0;reg[1:0] rresp=0;
    integer cycle=0,ars=0,beats=0;
    wire arready=!block_ar&&cycle%5!=0;
    wire[31:0] physical_reader_epoch;
    assign reader_result_epoch=physical_reader_epoch^(spoof_reader_epoch ? 32'd1 : 32'd0);
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(reader_command),.cmd_ready(reader_command_ready),
        .cmd_epoch(reader_epoch),.cmd_address(reader_address),.cmd_word_count(reader_words),.cancel(reader_cancel),.timeout(1'b0),.clear_fault(reader_clear),
        .busy(reader_busy),.done(reader_done),.fault(reader_fault),.fault_code(),.out_valid(reader_valid),.out_ready(reader_ready),
        .out_epoch(physical_reader_epoch),.out_index(reader_index),.out_data(reader_data),.out_last(reader_last),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
        .m_axi_rid(6'd0),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    reg memory_active=0;reg[31:0] memory_address=0;integer memory_beat=0,memory_beats=0;
    reg rheld=0;reg[66:0] saved_r;reg arheld=0;reg[35:0] saved_ar;
    function automatic [63:0] datum(input[31:0] address);
        datum={address^32'hb528914f,address^32'h63ca109d};
    endfunction
    function automatic [511:0] golden(input[31:0] address);
        integer j;begin for(j=0;j<8;j=j+1)golden[j*64+:64]=datum(address+j*8);end
    endfunction
    integer ownership_checks=0,release_blocks=0,held_output=0,completed=0,recovered=0;
    always @(posedge clk)begin
        cycle<=cycle+1;
        if(rst_n)begin
            if(arheld&&(!arvalid||{arlen,araddr}!==saved_ar))$fatal(1,"Cancelled advertised AR changed");
            arheld<=arvalid&&!arready;saved_ar<={arlen,araddr};
            if(rheld&&(!rvalid||{rdata,rresp,rlast}!==saved_r))$fatal(1,"TB R hold");
            rheld<=rvalid&&!rready;saved_r<={rdata,rresp,rlast};
            if(reader_command&&reader_command_ready||arvalid||reader_busy||out_valid)begin
                if(!lease_held||readers!=1)$fatal(1,"Physical reader did not own exact source reference");ownership_checks<=ownership_checks+1;
            end
            if(manager_valid&&manager_opcode==4&&reader_busy)$fatal(1,"Source reference released before physical drain");
            if(arvalid&&arready)begin
                if(memory_active||arid!=0||arsize!=3||arburst!=1||arlen!=15||araddr[6:0]!=0)$fatal(1,"Physical source burst");
                memory_active<=1;memory_address<=araddr;memory_beat<=0;memory_beats<=arlen+1;ars<=ars+1;
            end
            if(rvalid&&rready)begin rvalid<=0;beats<=beats+1;if(rlast)memory_active<=0;else memory_beat<=memory_beat+1;end
            if(memory_active&&!rvalid&&!block_r&&cycle%3!=0)begin
                rvalid<=1;rdata<=datum(memory_address+memory_beat*8);rlast<=memory_beat+1==memory_beats;
                rresp<=inject_resp&&memory_beat==10?2:0;
            end
        end
    end
    task automatic host(input integer op,input integer code);
        begin @(negedge clk);hop=op;hv=1;htag=htag+1;
            do @(posedge clk);while(!hr);@(negedge clk);hv=0;
            do @(negedge clk);while(!rv||!host_response);
            if(rc!=code||rt!=htag)$fatal(1,"Manager host response op=%d code=%d expected=%d",op,rc,code);
            rr=1;@(negedge clk);rr=0;
        end
    endtask
    task automatic publish;
        begin host(0,0);host(1,0);host(2,0);if(!query_committed||readers!=0)$fatal(1,"Source not published");end
    endtask
    task automatic issue;
        begin @(negedge clk);cmd_valid=1;do @(posedge clk);while(!cmd_ready);@(negedge clk);cmd_valid=0;
            cmd_epoch=99;cmd_generation=0;cmd_address=32'hfffffff0;cmd_tensor_id=0;cmd_words=0;end
    endtask
    task automatic preset;
        begin cmd_slot=0;cmd_epoch=200;cmd_generation=hg;cmd_tensor_id=42;cmd_address=32'h10000080;cmd_words=4;cmd_timeout_cycles=100000;cmd_tag=cmd_tag+2;end
    endtask
    task automatic recovery;
        integer j;begin
            abort=0;block_ar=0;block_r=0;block_manager=0;block_response=0;
            do @(negedge clk);while(lease_held||reader_busy||!fault);
            // Recovery is accepted only after a reference-return ACK and drain.
            recover=1;j=0;while(active&&j<40)begin @(negedge clk);j=j+1;end
            recover=0;
            if(active||fault||readers!=0||reader_fault||out_valid)$fatal(1,"Source read recovery leaked reference");recovered=recovered+1;
        end
    endtask
    integer i,j,old_ar,old_beats;
    reg[511:0] held_data;
    initial begin
        repeat(5)@(negedge clk);rst_n=1;publish();preset();issue();
        do @(negedge clk);while(!out_valid);held_data=out_data;
        host(5,3);release_blocks=release_blocks+1;
        for(i=0;i<10;i=i+1)begin if(!out_valid||out_data!==held_data||readers!=1)$fatal(1,"Held read output/lease");held_output=held_output+1;@(negedge clk);end
        for(i=0;i<4;i=i+1)begin
            do @(negedge clk);while(!out_valid);
            if(out_epoch!=200||out_index!=i||out_last!=(i==3)||out_data!==golden(32'h10000080+i*64))$fatal(1,"Real leased source data");
            out_ready=1;@(negedge clk);out_ready=0;
        end
        do @(negedge clk);while(!done);if(lease_held||readers!=0||fault)$fatal(1,"Done preceded reference return");completed=completed+1;
        // Bad source version/range/private tag cannot take a reference or issue AR.
        for(i=0;i<5;i=i+1)begin preset();case(i)0:cmd_epoch=199;1:cmd_generation=hg+1;2:cmd_tensor_id=43;3:cmd_address=32'h10000400;4:cmd_tag=32'hffffffff;endcase
            old_ar=ars;issue();if(!fault||fault_code!=1||lease_held||readers!=0||ars!=old_ar)$fatal(1,"Bad source request took lease");recovery();end
        // Cancel before acquire acceptance and after acceptance but before ACK.
        for(i=0;i<2;i=i+1)begin
            preset();old_ar=ars;block_manager=i==0;block_response=i==1;issue();
            if(i==1)begin do @(negedge clk);while(!rv||host_response);if(readers!=1)$fatal(1,"Acquire did not reach manager");end
            abort=1;@(negedge clk);abort=0;
            repeat(15)begin @(negedge clk);if(out_valid||ars!=old_ar||!active||!fault)$fatal(1,"Cancelled acquisition issued physical read");end
            recovery();if(ars!=old_ar)$fatal(1,"Late acquire ACK allowed read");
        end
        // An unexpected manager reply must be held, then matched and unwound;
        // it cannot be treated as permission to access the source.
        preset();old_ar=ars;spoof_manager_tag=1;issue();do @(negedge clk);while(!fault);
        repeat(10)begin @(negedge clk);if(manager_response_ready||reader_command||ars!=old_ar)$fatal(1,"Foreign manager ACK allowed read");end
        spoof_manager_tag=0;recovery();if(ars!=old_ar)$fatal(1,"Bad ACK recovery issued read");
        // Held advertised AR and absent R cannot return the owned reference.
        for(i=0;i<2;i=i+1)begin
            preset();block_ar=i==0;block_r=i==1;issue();
            do @(negedge clk);while(i==0 ? !arvalid : !memory_active);
            abort=1;@(negedge clk);abort=0;recover=1;
            for(j=0;j<30;j=j+1)begin @(negedge clk);if(!lease_held||readers!=1||!reader_busy||reader_clear||done)$fatal(1,"In-flight read released/recovered early");ownership_checks=ownership_checks+1;end
            recover=0;recovery();
        end
        preset();inject_resp=1;issue();do @(negedge clk);while(!fault);recovery();inject_resp=0;
        preset();spoof_reader_epoch=1;issue();do @(negedge clk);while(!fault);
        if(out_valid||fault_code!=8)$fatal(1,"Bad private reader epoch forwarded");recovery();spoof_reader_epoch=0;
        preset();cmd_timeout_cycles=80;block_r=1;issue();do @(negedge clk);while(!fault);if(fault_code!=3)$fatal(1,"Read timeout");recovery();
        // Source abort while a real read is held revokes output, but keeps ref
        // until this reader drains and returns it through the manager.
        preset();issue();do @(negedge clk);while(!out_valid);host(6,0);do @(negedge clk);while(!fault);
        if(out_valid)$fatal(1,"Revoked source output visible");recovery();host(7,0);hg=8;publish();
        // Query approval alone does not reserve a source. Reallocate while the
        // acquire command is delayed; manager must reject the old generation.
        preset();old_ar=ars;block_manager=1;issue();host(5,0);hg=9;publish();block_manager=0;
        do @(negedge clk);while(!fault);recovery();if(ars!=old_ar||readers!=0)$fatal(1,"Stale pre-acquire query allowed AR");
        host(5,0);
        if(completed!=1||recovered!=15||release_blocks!=1||held_output!=10||readers!=0||active_slots!=0)$fatal(1,"Coverage leak recovered=%d",recovered);
        $display("SOURCE_READ_LEASE_PASS successful_reads=%0d recoveries=%0d ownership_checks=%0d held_output_cycles=%0d busy_release_rejections=%0d AXI_AR=%0d AXI_R=%0d final_refs=0",completed,recovered,ownership_checks,held_output,release_blocks,ars,beats);$finish;
    end
    initial begin #10000000;$fatal(1,"Read ownership watchdog");end
endmodule
`default_nettype wire
