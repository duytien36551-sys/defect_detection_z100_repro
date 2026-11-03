`timescale 1ns/1ps
`default_nettype none
`include "parameter_reader_defs.vh"
module tb_z100_native_parameter_reader_v2;
    reg clk=0;always #5 clk=~clk;reg rst_n=0;
    wire cancel,cmd_valid,response_ready;
    wire[3:0] cmd_operation;wire[31:0] cmd_epoch,cmd_tag,cmd_index;
    wire[10:0] cmd_groups;wire[5:0] cmd_lanes;wire[1023:0] cmd_data;
    wire cmd_ready,response_valid,response_error,configured,child_cancel,fault;wire[31:0] response_tag;
    wire[31:0] cfg_epoch;wire[10:0] cfg_groups;wire[5:0] cfg_lanes;
    wire mac_begin,mac_begin_ready,mac_weight,mac_weight_ready,mac_bias,mac_bias_ready,mac_commit,mac_commit_ready,mac_error,mac_loaded;
    wire[31:0] mac_epoch;wire[1023:0] mac_data;
    wire factor_begin,factor_begin_ready,factor_word,factor_word_ready,factor_commit,factor_commit_ready,factor_error;
    wire[30:0] factor_multiplier;wire[5:0] factor_shift;
    wire unary_begin,unary_begin_ready,unary_word,unary_word_ready,unary_commit,unary_commit_ready,unary_error,unary_loaded;
    wire[7:0] unary_data;wire[31:0] unary_epoch;
    reg block_child=0,inject_child_error=0;
    wire mbready,mwready,mbiasready,mcready,fbready,fwready,fcready,ubready,uwready,ucready;
    wire real_mac_error,factor_cfg_error,factor_input_error;
    assign mac_begin_ready=mbready&&!block_child;assign mac_weight_ready=mwready&&!block_child;
    assign mac_bias_ready=mbiasready&&!block_child;assign mac_commit_ready=mcready&&!block_child;
    assign factor_begin_ready=fbready&&!block_child;assign factor_word_ready=fwready&&!block_child;assign factor_commit_ready=fcready&&!block_child;
    assign unary_begin_ready=ubready&&!block_child;assign unary_word_ready=uwready&&!block_child;assign unary_commit_ready=ucready&&!block_child;
    assign mac_error=real_mac_error||inject_child_error;assign factor_error=factor_cfg_error||factor_input_error;
    z100_native_parameter_bridge dut(.*);
    // SITES1 only reduces idle arithmetic replication. Config RAM/ports/groups,
    // bias32 and exact-factor/unary32 modules are the same production sources.
    z100_window_mac #(.SITES(1)) mac(.clk(clk),.rst_n(rst_n),.cancel(child_cancel),
        .cfg_begin(mac_begin&&!block_child),.cfg_begin_ready(mbready),.cfg_epoch(cfg_epoch),.cfg_groups(cfg_groups),
        .cfg_weight_valid(mac_weight&&!block_child),.cfg_weight_ready(mwready),.cfg_weights(mac_data),
        .cfg_bias_valid(mac_bias&&!block_child),.cfg_bias_ready(mbiasready),.cfg_bias(mac_data),
        .cfg_commit(mac_commit&&!block_child),.cfg_commit_ready(mcready),.weights_valid(mac_loaded),.weights_epoch(mac_epoch),.error_valid(real_mac_error),.error_code(),
        .run_valid(1'b0),.run_ready(),.run_epoch(32'd0),.run_token(32'd0),.run_lanes(6'd0),.run_sites(5'd0),
        .act_valid(1'b0),.act_ready(),.act_token(32'd0),.act_last(1'b0),.act_data(32'd0),
        .out_valid(),.out_ready(1'b1),.out_token(),.out_site(),.out_last(),.out_lanes(),.out_data(),.out_overflow());
    z100_requant_factor32 factor(.clk(clk),.rst_n(rst_n),.cancel(child_cancel),
        .cfg_begin(factor_begin&&!block_child),.cfg_begin_ready(fbready),.cfg_epoch(cfg_epoch),.cfg_lanes(cfg_lanes),
        .cfg_word_valid(factor_word&&!block_child),.cfg_word_ready(fwready),.cfg_multiplier(factor_multiplier),.cfg_shift(factor_shift),
        .cfg_commit(factor_commit&&!block_child),.cfg_commit_ready(fcready),.cfg_error(factor_cfg_error),.input_error(factor_input_error),
        .in_valid(1'b0),.in_ready(),.in_epoch(32'd0),.in_token(32'd0),.in_site(5'd0),.in_last(1'b0),.in_data(1024'd0),
        .out_valid(),.out_ready(1'b1),.out_epoch(),.out_token(),.out_site(),.out_lanes(),.out_last(),.out_data());
    z100_unary32 unary(.clk(clk),.rst_n(rst_n),.cancel(child_cancel),
        .cfg_begin(unary_begin&&!block_child),.cfg_begin_ready(ubready),.cfg_epoch(cfg_epoch),
        .cfg_word_valid(unary_word&&!block_child),.cfg_word_ready(uwready),.cfg_data(unary_data),
        .cfg_commit(unary_commit&&!block_child),.cfg_commit_ready(ucready),.error_valid(unary_error),.error_code(),
        .store_valid(unary_loaded),.active_epoch(unary_epoch),.loading(),
        .in_valid(1'b0),.in_ready(),.in_epoch(32'd0),.in_token(32'd0),.in_lanes(6'd0),.in_last(1'b0),.in_data(256'd0),
        .out_valid(),.out_ready(1'b1),.out_epoch(),.out_token(),.out_lanes(),.out_last(),.out_data());
    wire[31:0] probe_index=cmd_index;wire[1023:0] stored_weight;wire[127:0] stored_unary;
    genvar tap,replica;generate for(tap=0;tap<4;tap=tap+1)begin:weight_probe
        assign stored_weight[tap*256+:256]=mac.gen_weights[tap].memory[probe_index[9:0]];
    end
    for(replica=0;replica<16;replica=replica+1)begin:unary_probe
        assign stored_unary[replica*8+:8]=unary.gen_table[replica].table_mem[probe_index[7:0]];
    end endgenerate
    reg abort=0,recover=0,job_valid=0;reg[31:0] job_epoch=200,job_timeout=5000000;
    reg[10:0] job_groups=0;reg[5:0] job_lanes=0;
    reg[31:0] job_weights=0,job_bias=0,job_factors=0,job_unary=0;
    wire job_ready,active,load_fault,load_done;wire[3:0] load_fault_code;
    wire reader_command,reader_command_ready,reader_busy,reader_fault,reader_cancel,reader_clear,reader_valid,reader_ready,reader_last;
    wire[31:0] reader_epoch,reader_address,reader_result_epoch;wire[13:0] reader_words;wire[12:0] reader_index;wire[511:0] reader_data;
    z100_native_parameter_reader loader(.clk(clk),.rst_n(rst_n),.abort(abort),.recover(recover),
        .job_valid(job_valid),.job_ready(job_ready),.job_epoch(job_epoch),.job_timeout(job_timeout),.job_groups(job_groups),.job_lanes(job_lanes),
        .job_weights(job_weights),.job_bias(job_bias),.job_factors(job_factors),.job_unary(job_unary),
        .reader_command(reader_command),.reader_command_ready(reader_command_ready),.reader_epoch(reader_epoch),.reader_address(reader_address),.reader_words(reader_words),
        .reader_busy(reader_busy),.reader_fault(reader_fault),.reader_cancel(reader_cancel),.reader_clear(reader_clear),
        .reader_valid(reader_valid),.reader_ready(reader_ready),.reader_result_epoch(reader_result_epoch),.reader_index(reader_index),.reader_last(reader_last),.reader_data(reader_data),
        .cfg_valid(cmd_valid),.cfg_ready(cmd_ready),.cfg_operation(cmd_operation),.cfg_epoch(cmd_epoch),.cfg_tag(cmd_tag),.cfg_index(cmd_index),
        .cfg_groups(cmd_groups),.cfg_lanes(cmd_lanes),.cfg_data(cmd_data),.cfg_response_valid(response_valid),.cfg_response_ready(response_ready),
        .cfg_response_tag(response_tag),.cfg_response_error(response_error),.cfg_fault(fault),.cfg_configured(configured),.cfg_cancel(cancel),
        .active(active),.fault(load_fault),.fault_code(load_fault_code),.done(load_done));
    wire[5:0] arid;wire[31:0] araddr;wire[3:0] arlen;wire[2:0] arsize;wire[1:0] arburst;wire arvalid,rready;
    reg block_ar=0,block_r=0,inject_resp=0;reg rvalid=0,rlast=0;reg[63:0] rdata=0;reg[1:0] rresp=0;
    integer cycle=0,ars=0,rbeats=0;wire arready=!block_ar&&cycle%5!=0;
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),.cmd_valid(reader_command),.cmd_ready(reader_command_ready),
        .cmd_epoch(reader_epoch),.cmd_address(reader_address),.cmd_word_count(reader_words),.cancel(reader_cancel),.timeout(1'b0),.clear_fault(reader_clear),
        .busy(reader_busy),.done(),.fault(reader_fault),.fault_code(),.out_valid(reader_valid),.out_ready(reader_ready),
        .out_epoch(reader_result_epoch),.out_index(reader_index),.out_data(reader_data),.out_last(reader_last),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
        .m_axi_rid(6'd0),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
    reg[63:0] memory[0:`PARAMETER_MEMORY_BEATS-1];reg[191:0] jobs[0:172];
    reg memory_active=0;reg[31:0] memory_address=0;integer memory_beat=0,memory_beats=0;
    reg arheld=0,rheld=0;reg[35:0] saved_ar;reg[66:0] saved_r;
    integer configs=0,weight_checks=0,bias_checks=0,factor_checks=0,unary_checks=0,completed=0,recoveries=0,early_recovery_blocks=0;
    integer lane,beat_probe;reg[31:0] expected_address;reg[1023:0] expected_payload;
    always @(posedge clk)begin
        cycle<=cycle+1;
        if(rst_n)begin
            if(arheld&&(!arvalid||{arlen,araddr}!==saved_ar))$fatal(1,"Parameter cancelled AR changed");
            arheld<=arvalid&&!arready;saved_ar<={arlen,araddr};
            if(rheld&&(!rvalid||{rdata,rresp,rlast}!==saved_r))$fatal(1,"Parameter TB R hold violated");
            rheld<=rvalid&&!rready;saved_r<={rdata,rresp,rlast};
            if(arvalid&&arready)begin
                if(memory_active||arid!=0||arsize!=3||arburst!=1||araddr<32'h20000000||
                   (araddr-32'h20000000)/8+arlen>=`PARAMETER_MEMORY_BEATS||araddr[11:0]+(arlen+1)*8>4096)$fatal(1,"Parameter AXI range/page transaction");
                memory_active<=1;memory_address<=araddr;memory_beat<=0;memory_beats<=arlen+1;ars<=ars+1;
            end
            if(rvalid&&rready)begin rvalid<=0;rbeats<=rbeats+1;if(rlast)memory_active<=0;else memory_beat<=memory_beat+1;end
            if(memory_active&&!rvalid&&!block_r&&cycle%3!=0)begin
                rvalid<=1;rdata<=memory[(memory_address-32'h20000000)/8+memory_beat];rlast<=memory_beat+1==memory_beats;
                rresp<=inject_resp&&memory_beat==2?2:0;
            end
            if(response_valid&&response_ready&&!response_error&&!load_fault)begin
                if(completed<173)begin
                    expected_payload=0;expected_address=0;
                    case(cmd_operation)
                        4:expected_address=jobs[completed][31:0]+cmd_index*128;
                        5:expected_address=jobs[completed][63:32];
                        6:expected_address=jobs[completed][95:64]+cmd_index*8;
                        7:expected_address=jobs[completed][127:96]+cmd_index;
                    endcase
                    if(cmd_operation==4||cmd_operation==5)begin
                        for(beat_probe=0;beat_probe<16;beat_probe=beat_probe+1)
                            expected_payload[beat_probe*64+:64]=memory[(expected_address-32'h20000000)/8+beat_probe];
                    end else if(cmd_operation==6)expected_payload[63:0]=memory[(expected_address-32'h20000000)/8];
                    else if(cmd_operation==7)expected_payload[7:0]=memory[(expected_address-32'h20000000)/8]>>((expected_address%8)*8);
                    if(cmd_data!==expected_payload||cmd_epoch!=200||cmd_groups!==jobs[completed][138:128]||cmd_lanes!==jobs[completed][144:139])
                        $fatal(1,"Config payload/order differs from immutable DDR oracle job=%d operation=%d index=%d",completed,cmd_operation,cmd_index);
                end
                configs<=configs+1;
                if(cmd_operation==4)begin if(stored_weight!==cmd_data)$fatal(1,"DDR weight physical config differs");weight_checks<=weight_checks+128;end
                if(cmd_operation==5)begin
                    for(lane=0;lane<32;lane=lane+1)if(mac.bias[lane]!==cmd_data[lane*32+:32])$fatal(1,"DDR bias physical config differs");bias_checks<=bias_checks+32;
                end
                if(cmd_operation==6)begin
                    if(factor.multipliers[cmd_index]!==cmd_data[30:0]||factor.shifts[cmd_index]!==cmd_data[37:32])$fatal(1,"DDR factor physical config differs");factor_checks<=factor_checks+1;
                end
                if(cmd_operation==7)begin if(stored_unary!=={16{cmd_data[7:0]}})$fatal(1,"DDR unary replicas differ");unary_checks<=unary_checks+16;end
            end
            if(load_done&&(!configured||reader_busy||load_fault||!mac_loaded||!unary_loaded||!factor.loaded))$fatal(1,"Parameter job published before actual config/IO done");
        end
    end
    task issue(input integer j);
        begin @(negedge clk);job_epoch=200;job_timeout=5000000;
            job_groups=jobs[j][138:128];job_lanes=jobs[j][144:139];
            job_weights=jobs[j][31:0];job_bias=jobs[j][63:32];job_factors=jobs[j][95:64];job_unary=jobs[j][127:96];job_valid=1;
            do @(posedge clk);while(!job_ready);
            @(negedge clk);job_valid=0;job_groups=0;job_lanes=0;job_epoch=99;job_weights=32'hffffffff;
        end
    endtask
    task recovery;begin
        recover=1;repeat(8)begin @(negedge clk);if(reader_busy)begin if(job_ready)$fatal(1,"Reconfigured before IO drain");early_recovery_blocks=early_recovery_blocks+1;end end
        abort=0;block_ar=0;block_r=0;inject_resp=0;
        do @(negedge clk);while(!job_ready);recover=0;recoveries=recoveries+1;
        if(reader_fault||fault||load_fault||configured)$fatal(1,"Parameter recovery retained stale state");
    end endtask
    integer j;initial begin
        $readmemh("parameter_memory.hex",memory);$readmemh("parameter_jobs.hex",jobs);
        repeat(5)@(negedge clk);rst_n=1;
        for(j=0;j<173;j=j+1)begin
            issue(j);do @(negedge clk);while(!load_done&&!load_fault);
            if(load_fault||!configured)$fatal(1,"DDR parameter job failed index=%d code=%d",j,load_fault_code);completed=completed+1;
        end
        if(configs!=74447||weight_checks!=3011712||bias_checks!=5536||factor_checks!=5419||unary_checks!=708608)$fatal(1,"Full DDR parameter coverage config=%d",configs);
        // Abort held advertised AR; early recover must wait for acceptance/drain.
        block_ar=1;issue(0);do @(negedge clk);while(!arvalid);abort=1;recovery();
        // Accepted AR with withheld R; no reset or clearing can bypass RLAST.
        block_r=1;issue(0);do @(negedge clk);while(!reader_busy||!memory_active);abort=1;recovery();
        inject_resp=1;issue(0);do @(negedge clk);while(!load_fault);recovery();
        if(recoveries!=3||early_recovery_blocks<16||reader_busy||memory_active)$fatal(1,"Parameter recovery coverage incomplete");
        $display("PARAMETER_READER_PASS jobs=%0d configs=%0d weight_bytes=%0d bias_values=%0d factors=%0d unary_replica_bytes=%0d AXI_AR=%0d AXI_R=%0d recoveries=%0d early_recovery_blocks=%0d",completed,74447,3011712,5536,5419,708608,ars,rbeats,recoveries,early_recovery_blocks);
        $finish;
    end
    initial begin #100000000;$fatal(1,"Parameter DDR loader watchdog");end
endmodule
`default_nettype wire
