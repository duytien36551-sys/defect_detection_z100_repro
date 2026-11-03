    reg pp_job_valid=0;
    wire pp_job_ready,pp_active,pp_fault,pp_done,pp_cancel,pp_configured,pp_bridge_fault,pp_core_cancel;
    wire [3:0] pp_fault_code;
    wire pp_rcmd,pp_rcmdready,pp_rbusy,pp_rfault,pp_rcancel,pp_rclear,pp_rvalid,pp_rready,pp_rlast;
    wire[31:0] pp_repoch,pp_raddress,pp_roepoch;wire[13:0] pp_rwords;wire[12:0] pp_rindex;wire[511:0] pp_rdata;
    wire pp_cv,pp_cr,pp_rv,pp_rr,pp_re;wire[3:0] pp_op;
    wire[31:0] pp_epoch,pp_tag,pp_index,pp_rtag;wire[10:0] pp_groups;wire[5:0] pp_lanes;wire[1023:0] pp_data;
    wire[31:0] pp_cfg_epoch;wire[5:0] pp_cfg_lanes;wire[10:0] pp_cfg_groups;wire[1023:0] pp_cfg_data;
    z100_native_parameter_reader pp_loader(.clk(clk),.rst_n(rst_n),.abort(cancel),.recover(1'b0),
        .job_valid(pp_job_valid),.job_ready(pp_job_ready),.job_epoch(EPOCH),.job_timeout(32'd100000),
        .job_groups(11'd9),.job_lanes(6'd16),.job_weights(32'h20000000),.job_bias(32'h20000480),.job_factors(32'h20000500),.job_unary(32'h20000600),
        .reader_command(pp_rcmd),.reader_command_ready(pp_rcmdready),.reader_epoch(pp_repoch),.reader_address(pp_raddress),.reader_words(pp_rwords),
        .reader_busy(pp_rbusy),.reader_fault(pp_rfault),.reader_cancel(pp_rcancel),.reader_clear(pp_rclear),
        .reader_valid(pp_rvalid),.reader_ready(pp_rready),.reader_result_epoch(pp_roepoch),.reader_index(pp_rindex),.reader_last(pp_rlast),.reader_data(pp_rdata),
        .cfg_valid(pp_cv),.cfg_ready(pp_cr),.cfg_operation(pp_op),.cfg_epoch(pp_epoch),.cfg_tag(pp_tag),.cfg_index(pp_index),
        .cfg_groups(pp_groups),.cfg_lanes(pp_lanes),.cfg_data(pp_data),.cfg_response_valid(pp_rv),.cfg_response_ready(pp_rr),
        .cfg_response_tag(pp_rtag),.cfg_response_error(pp_re),.cfg_fault(pp_bridge_fault),.cfg_configured(pp_configured),.cfg_cancel(pp_cancel),
        .active(pp_active),.fault(pp_fault),.fault_code(pp_fault_code),.done(pp_done));
    z100_native_parameter_bridge pp_bridge(.clk(clk),.rst_n(rst_n),.cancel(pp_cancel),
        .cmd_valid(pp_cv),.cmd_ready(pp_cr),.cmd_operation(pp_op),.cmd_epoch(pp_epoch),.cmd_tag(pp_tag),.cmd_index(pp_index),
        .cmd_groups(pp_groups),.cmd_lanes(pp_lanes),.cmd_data(pp_data),.response_valid(pp_rv),.response_ready(pp_rr),.response_tag(pp_rtag),
        .response_error(pp_re),.configured(pp_configured),.child_cancel(pp_core_cancel),.fault(pp_bridge_fault),
        .cfg_epoch(pp_cfg_epoch),.cfg_groups(pp_cfg_groups),.cfg_lanes(pp_cfg_lanes),
        .mac_begin(mac_cfg_begin),.mac_begin_ready(mac_cfg_begin_ready),.mac_weight(mac_cfg_weight_valid),.mac_weight_ready(mac_cfg_weight_ready),
        .mac_bias(mac_cfg_bias_valid),.mac_bias_ready(mac_cfg_bias_ready),.mac_commit(mac_cfg_commit),.mac_commit_ready(mac_cfg_commit_ready),
        .mac_data(pp_cfg_data),.mac_error(mac_error_valid),.mac_loaded(mac_weights_valid),.mac_epoch(mac_weights_epoch),
        .factor_begin(req_cfg_begin),.factor_begin_ready(req_cfg_begin_ready),.factor_word(req_cfg_word_valid),.factor_word_ready(req_cfg_word_ready),
        .factor_commit(req_cfg_commit),.factor_commit_ready(req_cfg_commit_ready),.factor_multiplier(req_cfg_multiplier),.factor_shift(req_cfg_shift),
        .factor_error(req_cfg_error||req_input_error),
        .unary_begin(unary_cfg_begin),.unary_begin_ready(unary_cfg_begin_ready),.unary_word(unary_cfg_word_valid),.unary_word_ready(unary_cfg_word_ready),
        .unary_commit(unary_cfg_commit),.unary_commit_ready(unary_cfg_commit_ready),.unary_data(unary_cfg_data),
        .unary_error(unary_error_valid),.unary_loaded(unary_store_valid),.unary_epoch(unary_active_epoch));
    assign mac_cfg_epoch=pp_cfg_epoch;assign req_cfg_epoch=pp_cfg_epoch;assign unary_cfg_epoch=pp_cfg_epoch;
    assign mac_cfg_groups=pp_cfg_groups;assign req_cfg_lanes=pp_cfg_lanes;assign mac_cfg_weights=pp_cfg_data;assign mac_cfg_bias=pp_cfg_data;
    wire[5:0] pp_arid;wire[31:0] pp_araddr;wire[3:0] pp_arlen;wire[2:0] pp_arsize;wire[1:0] pp_arburst;
    wire pp_arvalid,pp_axi_rready;wire pp_arready=pp_cycle%5!=0;
    reg pp_axi_rvalid=0,pp_axi_rlast=0;reg[63:0] pp_axi_rdata=0;
    z100_native_axi64_reader pp_reader(.clk(clk),.rst_n(rst_n),.cmd_valid(pp_rcmd),.cmd_ready(pp_rcmdready),
        .cmd_epoch(pp_repoch),.cmd_address(pp_raddress),.cmd_word_count(pp_rwords),.cancel(pp_rcancel),.timeout(1'b0),.clear_fault(pp_rclear),
        .busy(pp_rbusy),.done(),.fault(pp_rfault),.fault_code(),.out_valid(pp_rvalid),.out_ready(pp_rready),
        .out_epoch(pp_roepoch),.out_index(pp_rindex),.out_data(pp_rdata),.out_last(pp_rlast),
        .m_axi_arid(pp_arid),.m_axi_araddr(pp_araddr),.m_axi_arlen(pp_arlen),.m_axi_arsize(pp_arsize),.m_axi_arburst(pp_arburst),.m_axi_arvalid(pp_arvalid),.m_axi_arready(pp_arready),
        .m_axi_rid(6'd0),.m_axi_rdata(pp_axi_rdata),.m_axi_rresp(2'd0),.m_axi_rlast(pp_axi_rlast),.m_axi_rvalid(pp_axi_rvalid),.m_axi_rready(pp_axi_rready));
    reg[63:0] pp_memory[0:223];reg pp_mem_active=0;reg[31:0] pp_mem_address=0;
    integer pp_mem_beat=0,pp_mem_beats=0,pp_cycle=0,pp_ars=0,pp_beats=0,pp_commands=0,pp_configs=0,pp_jobs=0;
    always @(posedge clk)begin
        pp_cycle<=pp_cycle+1;
        if(rst_n)begin
            if(pp_rcmd&&pp_rcmdready)pp_commands<=pp_commands+1;
            if(pp_rv&&pp_rr)begin if(pp_re)$fatal(1,"20site parameter config reply error");pp_configs<=pp_configs+1;end
            if(pp_arvalid&&pp_arready)begin
                if(pp_mem_active||pp_arid!=0||pp_arsize!=3||pp_arburst!=1||pp_araddr<32'h20000000||
                   (pp_araddr-32'h20000000)/8+pp_arlen>=224)$fatal(1,"20site parameter read bounds");
                pp_mem_active<=1;pp_mem_address<=pp_araddr;pp_mem_beat<=0;pp_mem_beats<=pp_arlen+1;pp_ars<=pp_ars+1;
            end
            if(pp_axi_rvalid&&pp_axi_rready)begin pp_axi_rvalid<=0;pp_beats<=pp_beats+1;if(pp_axi_rlast)pp_mem_active<=0;else pp_mem_beat<=pp_mem_beat+1;end
            if(pp_mem_active&&!pp_axi_rvalid&&pp_cycle%3!=0)begin
                pp_axi_rvalid<=1;pp_axi_rdata<=pp_memory[(pp_mem_address-32'h20000000)/8+pp_mem_beat];pp_axi_rlast<=pp_mem_beat+1==pp_mem_beats;
            end
            if(pp_fault||pp_bridge_fault)$fatal(1,"20site parameter loader fault code=%d",pp_fault_code);
        end
    end
    initial begin $readmemh("compute_parameters.hex",pp_memory);end
    task load_parameters_DDR;begin
        @(negedge clk);pp_job_valid=1;do @(posedge clk);while(!pp_job_ready);@(negedge clk);pp_job_valid=0;
        do @(negedge clk);while(!pp_done);
        if(!pp_configured||pp_rbusy||pp_mem_active||pp_commands!=4||pp_beats!=224||pp_ars!=14||pp_configs!=288)
            $fatal(1,"20site DDR parameter transaction coverage commands=%d R=%d AR=%d config=%d",pp_commands,pp_beats,pp_ars,pp_configs);
        pp_jobs=pp_jobs+1;
    end endtask
