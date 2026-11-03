`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_tensor_commit;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,abort=0,recover=0,io_quiescent=1,source_readers_quiescent=1;
    reg allocate_valid=0,tile_valid=0,completion_valid=0,completion_success=1,release_valid=0;
    reg[31:0] allocate_epoch=200,allocate_generation=1,allocate_address=32'h10000000,
        tile_epoch=200,tile_generation=1,completion_epoch=200,completion_generation=1;
    reg[15:0] allocate_tensor_id=42,tile_tensor_id=42,completion_tensor_id=42;
    reg[10:0] allocate_channels=36;
    reg[9:0] allocate_height=5,allocate_width=17,tile_first_row=0,tile_height=1,completion_first_row=0,completion_height=1;
    wire allocate_ready,tile_ready,completion_ready,release_ready,active,fault,source_committed,tile_pending,publication_pulse;
    wire[3:0] fault_code;wire[31:0] source_epoch,source_generation,source_address,source_bytes;
    wire[15:0] source_tensor_id;wire[10:0] source_channels,covered_rows;wire[9:0] source_height,source_width;
    z100_native_tensor_commit dut(.*);
    integer next_generation=1,publications=0,accepted_tiles=0,completed_tiles=0,rejections=0,blocked_checks=0,releases=0;
    integer expected_rows=0,configured_height=0;
    always @(posedge clk)if(rst_n)begin
        if(publication_pulse)publications<=publications+1;
        if(source_committed&&(tile_pending||covered_rows!=source_height||fault))$fatal(1,"Partial/stale source publication");
    end
    task automatic preset(input integer h);
        begin allocate_epoch=200;allocate_generation=next_generation;next_generation=next_generation+1;
            allocate_address=32'h10000000;allocate_tensor_id=42;allocate_channels=36;allocate_height=h;allocate_width=17;
            expected_rows=0;configured_height=h;
        end
    endtask
    task automatic allocate;
        begin @(negedge clk);allocate_valid=1;if(!allocate_ready)$fatal(1,"Allocation unexpectedly blocked");
            @(negedge clk);allocate_valid=0;
        end
    endtask
    task automatic reserve_tile(input integer first,input integer h);
        begin @(negedge clk);tile_epoch=source_epoch;tile_generation=source_generation;tile_tensor_id=source_tensor_id;
            tile_first_row=first;tile_height=h;tile_valid=1;if(!tile_ready)$fatal(1,"Tile reserve blocked");
            @(negedge clk);tile_valid=0;if(!tile_pending||fault||source_committed)$fatal(1,"Tile reserve not retained");
            accepted_tiles=accepted_tiles+1;tile_first_row=639;tile_height=0;tile_epoch=99;tile_generation=0;tile_tensor_id=13;
        end
    endtask
    task automatic complete_tile(input integer first,input integer h);
        integer k;begin
            @(negedge clk);completion_epoch=source_epoch;completion_generation=source_generation;completion_tensor_id=source_tensor_id;
            completion_first_row=first;completion_height=h;completion_success=1;completion_valid=1;io_quiescent=0;
            for(k=0;k<3;k=k+1)begin #1;
                if(completion_ready||source_committed||!tile_pending||allocate_ready||tile_ready)$fatal(1,"Completion accepted before B quiescence");
                blocked_checks=blocked_checks+1;@(negedge clk);
            end
            io_quiescent=1;#1;if(!completion_ready)$fatal(1,"Completion did not become available");
            @(negedge clk);completion_valid=0;expected_rows=expected_rows+h;
            if(fault||tile_pending||covered_rows!=expected_rows||source_committed!=(expected_rows==configured_height))$fatal(1,"Coverage/publication mismatch");
            completed_tiles=completed_tiles+1;
        end
    endtask
    task automatic release_tensor;
        integer k;begin
            if(!source_committed)$fatal(1,"Incomplete source released");
            release_valid=1;source_readers_quiescent=0;
            for(k=0;k<10;k=k+1)begin @(negedge clk);if(release_ready||!source_committed||allocate_ready)$fatal(1,"Live reader lost source");blocked_checks=blocked_checks+1;end
            source_readers_quiescent=1;io_quiescent=0;
            for(k=0;k<10;k=k+1)begin @(negedge clk);if(release_ready||!source_committed)$fatal(1,"Busy IO lost source");blocked_checks=blocked_checks+1;end
            io_quiescent=1;@(negedge clk);release_valid=0;
            if(active||source_committed||tile_pending)$fatal(1,"Release did not invalidate source");releases=releases+1;
        end
    endtask
    task automatic fault_recovery;
        integer k;begin
            if(!fault||source_committed)$fatal(1,"Expected revoked source");rejections=rejections+1;
            tile_valid=0;completion_valid=0;abort=0;recover=1;io_quiescent=0;
            for(k=0;k<5;k=k+1)begin @(negedge clk);if(!fault||allocate_ready||source_committed)$fatal(1,"Cleared busy writer reservation");blocked_checks=blocked_checks+1;end
            io_quiescent=1;source_readers_quiescent=0;
            for(k=0;k<5;k=k+1)begin @(negedge clk);if(!fault||allocate_ready)$fatal(1,"Cleared live source reader reservation");blocked_checks=blocked_checks+1;end
            source_readers_quiescent=1;@(negedge clk);recover=0;
            if(active||fault||source_committed||tile_pending)$fatal(1,"Fault recovery did not revoke identity");
        end
    endtask
    integer j,k;
    initial begin
        repeat(5)@(negedge clk);rst_n=1;
        preset(640);allocate();reserve_tile(639,1);complete_tile(639,1);reserve_tile(0,320);complete_tile(0,320);
        reserve_tile(320,319);complete_tile(320,319);release_tensor();
        preset(63);allocate();
        for(j=1;j<63;j=j+2)begin reserve_tile(j,1);complete_tile(j,1);end
        for(j=0;j<63;j=j+2)begin reserve_tile(j,1);complete_tile(j,1);end
        release_tensor();preset(1);allocate();reserve_tile(0,1);complete_tile(0,1);release_tensor();
        // Incorrect allocation shape/address or stale frame identity.
        for(j=0;j<7;j=j+1)begin
            preset(5);
            case(j)0:allocate_epoch=0;1:allocate_generation=0;2:allocate_channels=0;3:allocate_height=0;4:allocate_width=641;
                5:allocate_address=32'hffffffc0;6:allocate_epoch=199;endcase
            allocate();fault_recovery();
        end
        // Covered-row overlap/duplicate, range and source identity errors.
        for(j=0;j<7;j=j+1)begin
            preset(5);allocate();reserve_tile(0,2);complete_tile(0,2);
            tile_epoch=source_epoch;tile_generation=source_generation;tile_tensor_id=source_tensor_id;tile_first_row=2;tile_height=1;
            case(j)0:tile_first_row=1;1:begin tile_first_row=0;tile_height=2;end
                2:tile_first_row=5;3:tile_height=0;4:tile_epoch=199;5:tile_generation=source_generation+1;6:tile_tensor_id=43;endcase
            tile_valid=1;@(negedge clk);fault_recovery();
        end
        // Failed/mismatched/stale or unsolicited result must revoke the tensor.
        for(j=0;j<7;j=j+1)begin
            preset(5);allocate();if(j!=6)reserve_tile(0,2);
            completion_epoch=source_epoch;completion_generation=source_generation;completion_tensor_id=source_tensor_id;
            completion_first_row=0;completion_height=2;completion_success=1;
            case(j)0:completion_success=0;1:completion_epoch=199;2:completion_generation=source_generation+1;
                3:completion_tensor_id=43;4:completion_first_row=1;5:completion_height=1;endcase
            completion_valid=1;@(negedge clk);fault_recovery();
        end
        // Duplicate completion or tile command after publication invalidates it.
        for(j=0;j<2;j=j+1)begin
            preset(1);allocate();reserve_tile(0,1);complete_tile(0,1);
            if(j==0)completion_valid=1;else tile_valid=1;
            @(negedge clk);fault_recovery();
        end
        // Busy physical IO prevents both reserve and premature recovery.
        preset(5);allocate();io_quiescent=0;tile_valid=1;
        repeat(10)begin @(negedge clk);if(tile_ready||tile_pending||source_committed)$fatal(1,"Reserved while old writer active");blocked_checks=blocked_checks+1;end
        tile_valid=0;io_quiescent=1;reserve_tile(0,5);abort=1;#1;if(source_committed)$fatal(1,"Abort publication");@(negedge clk);fault_recovery();
        // New reservation must not reuse the previous frame/generation key.
        preset(1);allocate();reserve_tile(0,1);complete_tile(0,1);release_tensor();
        allocate_generation=source_generation;allocate();fault_recovery();
        preset(1);allocate();reserve_tile(0,1);complete_tile(0,1);release_tensor();
        if(rejections!=25||publications!=7||releases!=5||completed_tiles!=78||accepted_tiles!=85)
            $fatal(1,"Commit ledger coverage reject=%d publications=%d release=%d complete=%d reserve=%d",rejections,publications,releases,completed_tiles,accepted_tiles);
        $display("TENSOR_COMMIT_PASS publications=%0d releases=%0d accepted_tiles=%0d completed_tiles=%0d rejected_cases=%0d quiescence_checks=%0d max_height=640",publications,releases,accepted_tiles,completed_tiles,rejections,blocked_checks);
        $finish;
    end
    initial begin #1000000;$fatal(1,"Tensor commit watchdog");end
endmodule
`default_nettype wire
