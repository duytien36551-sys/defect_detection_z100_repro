`default_nettype none
// A whole-load lease multiplexes the materialized burst path (0) and the
// virtual gather/cache path (1) onto one frozen AXI reader. A descriptor's
// reader completion is not a lease release: the caller must retain ownership
// through codec retirement and feature-store commit, including fault drain.
// Release also excludes a same-edge owned command even if a caller wrongly
// asserts quiet. Otherwise a new reader transaction could lose its owner.
// rst_n is the coordinated fabric reset, never a local recovery mechanism.
module z100_native_ingress_reader_v2 (
    input wire clk,rst_n,
    input wire acquire_valid,acquire_mode,output wire acquire_ready,
    input wire release_valid,release_mode,output wire release_ready,
    input wire b_quiet,v_quiet,output reg owner_valid,owner_mode,
    input wire b_command,output wire b_command_ready,
    input wire [31:0] b_epoch,b_address,input wire [13:0] b_words,
    input wire b_cancel,b_clear_fault,output wire b_busy,b_done,b_fault,
    output wire [3:0] b_fault_code,
    output wire b_valid,input wire b_ready,output wire [31:0] b_result_epoch,
    output wire [12:0] b_index,output wire [511:0] b_data,output wire b_last,
    input wire v_command,output wire v_command_ready,
    input wire [31:0] v_epoch,v_address,
    input wire v_cancel,v_clear_fault,output wire v_busy,v_done,v_fault,
    output wire [3:0] v_fault_code,
    output wire v_valid,input wire v_ready,output wire [31:0] v_result_epoch,
    output wire [12:0] v_index,output wire [511:0] v_data,output wire v_last,
    output wire [5:0] m_axi_arid,output wire [31:0] m_axi_araddr,
    output wire [3:0] m_axi_arlen,output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,output wire m_axi_arvalid,input wire m_axi_arready,
    input wire [5:0] m_axi_rid,input wire [63:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,input wire m_axi_rlast,m_axi_rvalid,output wire m_axi_rready
);
    wire b_owned=rst_n&&owner_valid&&!owner_mode;
    wire v_owned=rst_n&&owner_valid&&owner_mode;
    wire reader_command_ready,reader_busy,reader_done,reader_fault,reader_valid,reader_last;
    wire [3:0] reader_fault_code;wire [31:0] reader_epoch;
    wire [12:0] reader_index;wire [511:0] reader_data;
    wire reader_quiet=!reader_busy&&!reader_fault&&!reader_valid;
    assign acquire_ready=rst_n&&!owner_valid&&reader_quiet&&b_quiet&&v_quiet;
    assign release_ready=rst_n&&owner_valid&&release_mode==owner_mode&&reader_quiet&&
        (owner_mode ? v_quiet : b_quiet)&&!(owner_mode ? v_command : b_command);
    always @(posedge clk)begin
        if(!rst_n)begin owner_valid<=0;owner_mode<=0;end
        else begin
            if(acquire_valid&&acquire_ready)begin owner_valid<=1;owner_mode<=acquire_mode;end
            if(release_valid&&release_ready)owner_valid<=0;
        end
    end
    assign b_command_ready=b_owned&&reader_command_ready;
    assign v_command_ready=v_owned&&reader_command_ready;
    assign b_busy=!b_owned||reader_busy;assign v_busy=!v_owned||reader_busy;
    assign b_fault=b_owned&&reader_fault;assign v_fault=v_owned&&reader_fault;
    assign b_fault_code=b_owned ? reader_fault_code : 4'd0;
    assign v_fault_code=v_owned ? reader_fault_code : 4'd0;
    assign b_done=b_owned&&reader_done;assign v_done=v_owned&&reader_done;
    assign b_valid=b_owned&&reader_valid;assign v_valid=v_owned&&reader_valid;
    assign b_result_epoch=reader_epoch;assign v_result_epoch=reader_epoch;
    assign b_index=reader_index;assign v_index=reader_index;
    assign b_data=reader_data;assign v_data=reader_data;
    assign b_last=reader_last;assign v_last=reader_last;
    z100_native_axi64_reader reader(.clk(clk),.rst_n(rst_n),
        .cmd_valid(b_owned&&b_command||v_owned&&v_command),.cmd_ready(reader_command_ready),
        .cmd_epoch(owner_mode ? v_epoch : b_epoch),.cmd_address(owner_mode ? v_address : b_address),
        .cmd_word_count(owner_mode ? 14'd1 : b_words),
        .cancel(b_owned&&b_cancel||v_owned&&v_cancel),.timeout(1'b0),
        .clear_fault(b_owned&&b_clear_fault||v_owned&&v_clear_fault),
        .busy(reader_busy),.done(reader_done),.fault(reader_fault),.fault_code(reader_fault_code),
        .out_valid(reader_valid),.out_ready(b_owned&&b_ready||v_owned&&v_ready),
        .out_epoch(reader_epoch),.out_index(reader_index),.out_data(reader_data),.out_last(reader_last),
        .m_axi_arid(m_axi_arid),.m_axi_araddr(m_axi_araddr),.m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),.m_axi_arburst(m_axi_arburst),.m_axi_arvalid(m_axi_arvalid),.m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid),.m_axi_rdata(m_axi_rdata),.m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),.m_axi_rvalid(m_axi_rvalid),.m_axi_rready(m_axi_rready));
endmodule
`default_nettype wire
