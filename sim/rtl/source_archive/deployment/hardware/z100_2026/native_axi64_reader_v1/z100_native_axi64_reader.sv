`timescale 1ns/1ps
`default_nettype none
// Private single-outstanding AXI3 read adapter. rst_n requires coordinated
// platform/fabric reset: never assert local reset to abandon an AR/R transfer.
// Explicit cancel/fault invalidates the private output epoch. It may withdraw
// private output-valid, but ARVALID/address/length remain stable until accepted.
// Fault clearing/reload cannot succeed until the accepted burst reaches RLAST.
module z100_native_axi64_reader (
    input wire clk, rst_n,
    input wire cmd_valid, output wire cmd_ready,
    input wire [31:0] cmd_epoch, cmd_address,
    input wire [13:0] cmd_word_count,
    input wire cancel, timeout, clear_fault,
    output wire busy, output reg done, output wire fault,
    output reg [3:0] fault_code,
    output wire out_valid, input wire out_ready,
    output wire [31:0] out_epoch,
    output reg [12:0] out_index,
    output reg [511:0] out_data,
    output reg out_last,
    output wire [5:0] m_axi_arid,
    output reg [31:0] m_axi_araddr,
    output wire [3:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arvalid, input wire m_axi_arready,
    input wire [5:0] m_axi_rid,
    input wire [63:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast, m_axi_rvalid,
    output wire m_axi_rready
);
    localparam [2:0] IDLE=0, ISSUE=1, RECEIVE=2, DRAIN=3, FINISH=4, FAILED=5;
    localparam [3:0] BAD_COMMAND=1, BAD_RID=2, BAD_RESP=3,
                     EARLY_LAST=4, MISSING_LAST=5, TIMED_OUT=6, CANCELLED=7;
    reg [2:0] state;
    reg fault_pending, output_valid;
    reg [31:0] epoch;
    reg [13:0] total_words, completed_words;
    reg [4:0] burst_beats, response_index;
    reg [2:0] assembly_index;
    // Two independent64-byte slots; payload intentionally has no reset.
    reg [511:0] assembly;
    wire [32:0] command_end = {1'b0,cmd_address}+{13'd0,cmd_word_count,6'd0};
    wire invalid_command = cmd_epoch==0 || cmd_address[5:0]!=0 ||
        cmd_word_count==0 || cmd_word_count>8192 || command_end>33'h100000000;

    function automatic [4:0] choose_beats(input [31:0] address, input [13:0] words);
        reg [16:0] remaining;
        reg [12:0] page_bytes;
        reg [9:0] page_beats;
        begin
            remaining={words,3'b0};
            page_bytes=13'd4096-{1'b0,address[11:0]};
            page_beats=page_bytes[12:3];
            if(remaining<16) choose_beats=remaining[4:0];
            else choose_beats=16;
            if(page_beats<choose_beats) choose_beats=page_beats[4:0];
        end
    endfunction

    wire expected_last=response_index==burst_beats-1'b1;
    wire bad_response=m_axi_rid!=0 || m_axi_rresp!=0 || m_axi_rlast!=expected_last;
    wire output_room=!output_valid || out_ready;
    assign m_axi_rready=rst_n && ((state==DRAIN) || (state==RECEIVE &&
        (fault_pending || cancel || timeout || bad_response || assembly_index!=7 || output_room)));
    wire r_fire=m_axi_rvalid && m_axi_rready;
    wire incoming_fault=state==RECEIVE && r_fire && bad_response;
    assign out_valid=rst_n && output_valid && !fault_pending && !cancel && !timeout && !incoming_fault;
    wire output_pop=out_valid && out_ready;
    assign out_epoch=epoch;
    assign busy=(state!=IDLE && state!=FAILED);
    assign fault=fault_pending;
    assign cmd_ready=rst_n && state==IDLE && !cancel && !timeout;
    assign m_axi_arid=0;
    assign m_axi_arlen=burst_beats[3:0]-1'b1;
    assign m_axi_arsize=3;
    assign m_axi_arburst=1;
    assign m_axi_arvalid=rst_n && state==ISSUE;

    always @(posedge clk) begin
        if(!rst_n) begin
            state<=IDLE; fault_pending<=0; fault_code<=0; output_valid<=0;
            done<=0; epoch<=0; total_words<=0; completed_words<=0;
            burst_beats<=0; response_index<=0; assembly_index<=0;
            m_axi_araddr<=0; out_index<=0; out_last<=0;
        end else begin
            done<=0;
            if(output_pop) output_valid<=0;
            case(state)
                IDLE: if(cmd_valid && cmd_ready) begin
                    output_valid<=0;
                    if(invalid_command) begin
                        fault_pending<=1; fault_code<=BAD_COMMAND; state<=FAILED;
                    end else begin
                        epoch<=cmd_epoch; total_words<=cmd_word_count; completed_words<=0;
                        assembly_index<=0; response_index<=0;
                        m_axi_araddr<=cmd_address; burst_beats<=choose_beats(cmd_address,cmd_word_count);
                        state<=ISSUE;
                    end
                end
                ISSUE: begin
                    if(cancel || timeout) begin
                        fault_pending<=1; output_valid<=0;
                        if(!fault_pending) fault_code<=timeout ? TIMED_OUT : CANCELLED;
                    end
                    // Hold ARVALID, ARADDR and ARLEN even after abort until
                    // the fabric accepts the request, then drain its response.
                    if(m_axi_arready) begin
                        response_index<=0;
                        state<=(fault_pending || cancel || timeout) ? DRAIN : RECEIVE;
                    end
                end
                RECEIVE: begin
                    if(cancel || timeout || incoming_fault) begin
                        output_valid<=0; fault_pending<=1;
                        if(!fault_pending) begin
                            if(timeout) fault_code<=TIMED_OUT;
                            else if(cancel) fault_code<=CANCELLED;
                            else if(m_axi_rid!=0) fault_code<=BAD_RID;
                            else if(m_axi_rresp!=0) fault_code<=BAD_RESP;
                            else fault_code<=m_axi_rlast ? EARLY_LAST : MISSING_LAST;
                        end
                        state<=(r_fire && m_axi_rlast) ? FAILED : DRAIN;
                    end else if(r_fire) begin
                        assembly[assembly_index*64+:64]<=m_axi_rdata;
                        response_index<=response_index+1'b1;
                        if(assembly_index==7) begin
                            out_data<={m_axi_rdata,assembly[447:0]};
                            out_index<=completed_words[12:0];
                            out_last<=completed_words+1'b1==total_words;
                            output_valid<=1; completed_words<=completed_words+1'b1;
                            assembly_index<=0;
                        end else assembly_index<=assembly_index+1'b1;
                        if(m_axi_rlast) begin
                            if(completed_words+1'b1==total_words) state<=FINISH;
                            else begin
                                m_axi_araddr<=m_axi_araddr+{24'd0,burst_beats,3'b0};
                                burst_beats<=choose_beats(m_axi_araddr+{24'd0,burst_beats,3'b0},
                                                         total_words-completed_words-1'b1);
                                state<=ISSUE;
                            end
                        end
                    end
                end
                DRAIN: begin
                    output_valid<=0;
                    if(r_fire && m_axi_rlast) state<=FAILED;
                end
                FINISH: begin
                    if(cancel || timeout) begin
                        fault_pending<=1; fault_code<=timeout ? TIMED_OUT : CANCELLED;
                        output_valid<=0; state<=FAILED;
                    end else if(output_pop && out_last) begin
                        done<=1; state<=IDLE;
                    end
                end
                FAILED: begin
                    output_valid<=0;
                    if(clear_fault && !cancel && !timeout) begin
                        fault_pending<=0; fault_code<=0; state<=IDLE;
                    end
                end
                default: begin state<=FAILED; fault_pending<=1; fault_code<=BAD_COMMAND; end
            endcase
        end
    end
endmodule
`default_nettype wire
