`default_nettype none
// Private native-window engine. Four taps x32 channels xSITES products.
// A group contains four adjacent input channels at one ky/kx, rather than
// tile64's flattened tap order. Matching reordered weights are mandatory.
// One buffer: no next-job compute until the previous result has drained.
// timing_v13 (vs z100_window_mac_local_control_v1, same ports/handshakes):
//  * bias write registered once, then 4 site-cluster copies (CE fanout 1024 -> 256 x4)
//  * accumulator load_bias registered per site/8-lane group (no epoch compare at DSP)
//  * bias mask uses local_active instead of run_sites/run_lanes compare
//  * feedback DSP uses internal P feedback (z100_accum33_dsp_pfb)
//  * weight operand replicated per site cluster, pair MULT LATENCY=2 (AREG/BREG)
//    -> one extra pipeline stage p4; outputs appear 1 cycle later, same sequence.
//  * (b) weight BRAM write port registered (written_groups -> BRAM path)
//  * 2026-10-31 routing fix: the four taps of each weight pair are summed in a
//    DSP48E1 PCOUT->PCIN cascade (z100_int8_pair_cascade4) instead of four
//    separate products + fabric correction + fabric 4-input adder tree.
//    Same 1280 DSPs; ~4x fewer DSP->fabric nets. Weights are packed as
//    wh*2^17+wl (exact for weight bytes in [-127,127]; the quantizer clamps
//    to that range). Tap t operands are skewed by t cycles; pipeline is
//    4 cycles longer (p4 -> p8). Same output values and handshake sequence.
module z100_mac_ref_old #(
    parameter integer SITES=20
) (
    input wire clk, rst_n, cancel,
    input wire cfg_begin,
    output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,
    input wire [10:0] cfg_groups,
    input wire cfg_weight_valid,
    output wire cfg_weight_ready,
    input wire [1023:0] cfg_weights,
    input wire cfg_bias_valid,
    output wire cfg_bias_ready,
    input wire [1023:0] cfg_bias,
    input wire cfg_commit,
    output wire cfg_commit_ready,
    output reg weights_valid,
    output reg [31:0] weights_epoch,
    output reg error_valid,
    output reg [2:0] error_code,
    input wire run_valid,
    output wire run_ready,
    input wire [31:0] run_epoch,
    input wire [31:0] run_token,
    input wire [5:0] run_lanes,
    input wire [4:0] run_sites,
    input wire act_valid,
    output wire act_ready,
    input wire [31:0] act_token,
    input wire act_last,
    input wire [4*SITES*8-1:0] act_data,
    output wire out_valid,
    input wire out_ready,
    output wire [31:0] out_token,
    output wire [4:0] out_site,
    output wire out_last,
    output wire [5:0] out_lanes,
    output wire [1023:0] out_data,
    output wire [31:0] out_overflow
);
    localparam [1:0] IDLE=0, INPUTS=1, FLUSH=2, OUTPUTS=3;
    reg [1:0] state;
    reg loading, bias_loaded;
    reg [10:0] expected_groups, written_groups, accepted_groups;
    reg [31:0] pending_epoch, token;
    reg [5:0] lanes;
    reg [4:0] sites, drain_site;
    reg p0_valid,p1_valid,p2_valid,p3_valid,p4_valid,p5_valid,p6_valid,p7_valid,p8_valid;
    reg p0_last,p1_last,p2_last,p3_last,p4_last,p5_last,p6_last,p7_last,p8_last;
    reg [4*SITES*8-1:0] activation_q;
    wire [255:0] weight_read_q[0:3];
    // Cascade packing is exact only for weight bytes in [-127,127]. A byte of
    // 0x80 written in this configuration fails the commit (error 2).
    wire [3:0] weight_byte_bad;
    reg weight_byte_bad_q;
    wire weight_bad_any=weight_byte_bad_q || (|weight_byte_bad);
    // One weight operand copy per site cluster (4 clusters), indexed [cluster*4+tap].
    localparam integer CLUSTERS=4;
    // Cascade version: each copy holds 16 packed pairs (wh*2^17+wl, 25 bits).
    (* dont_touch="true", keep="true" *) reg [16*25-1:0] weight_operand_q[0:CLUSTERS*4-1];
    // Replicas are local to each8-output group, limiting activation fanout.
    (* dont_touch="true" *) reg signed [7:0] activation_operand_q[0:SITES-1][0:3][0:3];
    // Exact paired products are registered by one MULT_MACRO per adjacent
    // output-lane pair/tap/site; the native validity pipeline remains authoritative.
    wire signed [16:0] cascade_sum[0:SITES-1][0:31];
    (* use_dsp="no" *) reg signed [18:0] sum_q[0:SITES-1][0:31];
    wire signed [32:0] accum[0:SITES-1][0:31];
    // Bias write: one registered staging copy, then one copy per site cluster.
    // Visible two edges after the accepted bias beat; commit/run cannot use it
    // earlier than that (commit is >=1 edge later, run_ready needs !loading).
    reg [1023:0] bias_stage_q;
    // v13c: one strobe FF per (cluster, 64-bit slice): fanout 64 instead of 1024.
    (* dont_touch="true", keep="true" *) reg [CLUSTERS*16-1:0] bias_write_q;
    (* dont_touch="true", keep="true" *) reg [1023:0] bias_copy_q[0:CLUSTERS-1];
    wire idle = state==IDLE;
    assign cfg_begin_ready=rst_n && idle && !loading && !cancel;
    assign cfg_weight_ready=rst_n && loading && !cfg_begin && !cfg_commit && !cancel;
    assign cfg_bias_ready=cfg_weight_ready;
    assign cfg_commit_ready=rst_n && loading && !cfg_begin && !cancel;
    assign run_ready=rst_n && idle && weights_valid && !loading && !cfg_begin && !cancel;
    assign act_ready=rst_n && state==INPUTS && !cancel;
    assign out_valid=rst_n && state==OUTPUTS && !cancel;
    assign out_token=token;
    assign out_site=drain_site;
    assign out_lanes=lanes;
    assign out_last=(drain_site+1'b1)==sites;
    wire input_fire=act_valid && act_ready;
    wire expected_last=(accepted_groups+1'b1)==expected_groups;
    wire input_good=input_fire && act_token==token && act_last==expected_last;
    wire input_abort=input_fire && !input_good;
    // Bias capture shares the accepted-run boundary; rejected runs never touch feedback state.
    wire accumulator_load_bias=run_valid && run_ready && run_epoch==weights_epoch &&
        run_token!=0 && run_lanes!=0 && run_lanes<=32 && run_sites!=0 && run_sites<=SITES;
    wire weight_write=cfg_weight_valid && cfg_weight_ready && written_groups<expected_groups;
    // Each site/8-lane cluster retains its own p3-valid copy. The active mask
    // is captured on the exact accepted run edge that loads accumulator bias.
    // These controls replace the high-fanout state/site/lane decode on DSP CEP;
    // the data and valid pipeline remain at the original cycle boundaries.
    wire [SITES*32-1:0] local_accumulator_enable;
    wire [SITES*32-1:0] local_active_mask;
    wire [SITES*4-1:0] local_load_bias;
    genvar control_site, control_group, control_lane;
    generate for(control_site=0;control_site<SITES;control_site=control_site+1) begin : gen_feedback_local_site
        for(control_group=0;control_group<4;control_group=control_group+1) begin : gen_feedback_local_group
            // p4 replica (one stage later than v12 because of MULT LATENCY=2).
            (* dont_touch="true", keep="true" *) reg local_p4_valid;
            // Registered per-group bias load: one edge after the accepted run.
            // First legal accumulate is >=4 edges later, so ordering is kept.
            (* dont_touch="true", keep="true" *) reg local_load_q;
            always @(posedge clk) begin
                // Cascade: sum_q is valid after p8, so the replica follows p7.
                if(!rst_n || cancel || input_abort) local_p4_valid<=1'b0;
                else local_p4_valid<=p7_valid;
                if(!rst_n || cancel) local_load_q<=1'b0;
                else local_load_q<=accumulator_load_bias;
            end
            assign local_load_bias[control_site*4+control_group]=local_load_q;
            for(control_lane=0;control_lane<8;control_lane=control_lane+1) begin : gen_feedback_local_lane
                (* dont_touch="true", keep="true" *) reg local_active;
                always @(posedge clk) begin
                    if(!rst_n || cancel || input_abort || (out_valid && out_ready && out_last))
                        local_active<=1'b0;
                    else if(accumulator_load_bias)
                        local_active<=(control_site<run_sites) &&
                                      ((control_group*8+control_lane)<run_lanes);
                end
                assign local_accumulator_enable[control_site*32+control_group*8+control_lane]=
                    local_p4_valid && local_active;
                assign local_active_mask[control_site*32+control_group*8+control_lane]=local_active;
            end
        end
    end endgenerate
    genvar tap, site, lane, packed_site, packed_pair, packed_tap;
    generate for(tap=0;tap<4;tap=tap+1) begin : gen_weights
        (* ram_style="block" *) reg [255:0] memory[0:1023];
        reg [255:0] read_q;
        // Registered write port: the last weight lands >=2 edges before the
        // first read (commit, then run, then the first input beat).
        reg write_pending_q; reg [9:0] write_address_q; reg [255:0] write_data_q;
        always @(posedge clk) begin
            if(!rst_n) write_pending_q<=1'b0; else write_pending_q<=weight_write;
            if(weight_write) begin write_address_q<=written_groups[9:0]; write_data_q<=cfg_weights[tap*256+:256]; end
            if(write_pending_q) memory[write_address_q]<=write_data_q;
            if(input_good) read_q<=memory[accepted_groups[9:0]];
        end
        assign weight_read_q[tap]=read_q;
        wire [31:0] byte_is_min;
        genvar wb;
        for(wb=0;wb<32;wb=wb+1) begin : gen_wb
            assign byte_is_min[wb]=write_data_q[wb*8+:8]==8'h80;
        end
        assign weight_byte_bad[tap]=write_pending_q && (|byte_is_min);
    end endgenerate
    // Tap skew (2026-10-31): tap t operands lag tap 0 by t cycles so each
    // cascade stage adds its product to the previous stage's P. Skewing the
    // single BRAM read word and the 160-bit activation slice per tap before
    // replication keeps the extra registers small (free-running, no reset).
    wire [255:0] weight_skew[0:3];
    wire [SITES*8-1:0] act_skew[0:3];
    generate for(tap=0;tap<4;tap=tap+1) begin : gen_skew
        if(tap==0) begin : g0
            assign weight_skew[tap]=weight_read_q[tap];
            assign act_skew[tap]=activation_q[tap*SITES*8+:SITES*8];
        end else begin : gd
            reg [255:0] wd[0:tap-1];
            reg [SITES*8-1:0] ad[0:tap-1];
            integer k;
            always @(posedge clk) begin
                wd[0]<=weight_read_q[tap];
                ad[0]<=activation_q[tap*SITES*8+:SITES*8];
                for(k=1;k<tap;k=k+1) begin wd[k]<=wd[k-1]; ad[k]<=ad[k-1]; end
            end
            assign weight_skew[tap]=wd[tap-1];
            assign act_skew[tap]=ad[tap-1];
        end
    end endgenerate
    // Pack once per tap before replication (64 adders instead of 1280).
    wire [16*25-1:0] weight_packed[0:3];
    genvar pt, pp;
    generate for(pt=0;pt<4;pt=pt+1) begin : gen_pack_tap
        for(pp=0;pp<16;pp=pp+1) begin : gen_pack_pair
            wire signed [7:0] wl=weight_skew[pt][(pp*2)*8+:8];
            wire signed [7:0] wh=weight_skew[pt][(pp*2+1)*8+:8];
            assign weight_packed[pt][pp*25+:25]=$signed({wh,17'd0})+$signed({{17{wl[7]}},wl});
        end
    end endgenerate
    // One cascade (4 DSPs) per site/lane pair: low lane 2p, high lane 2p+1.
    generate for(packed_site=0;packed_site<SITES;packed_site=packed_site+1) begin : gen_packed_site
        for(packed_pair=0;packed_pair<16;packed_pair=packed_pair+1) begin : gen_packed_pair
            wire signed [24:0] pk[0:3];
            for(packed_tap=0;packed_tap<4;packed_tap=packed_tap+1) begin : gen_pack
                assign pk[packed_tap]=weight_operand_q[((packed_site*CLUSTERS)/SITES)*4+packed_tap][packed_pair*25+:25];
            end
            z100_int8_pair_cascade4 packed_products (
                .clk(clk),
                .packed0(pk[0]), .packed1(pk[1]), .packed2(pk[2]), .packed3(pk[3]),
                .act0(activation_operand_q[packed_site][packed_pair/4][0]),
                .act1(activation_operand_q[packed_site][packed_pair/4][1]),
                .act2(activation_operand_q[packed_site][packed_pair/4][2]),
                .act3(activation_operand_q[packed_site][packed_pair/4][3]),
                .out_low(cascade_sum[packed_site][packed_pair*2]),
                .out_high(cascade_sum[packed_site][packed_pair*2+1])
            );
        end
    end endgenerate
    generate for(site=0;site<SITES;site=site+1) begin : gen_site
        for(lane=0;lane<32;lane=lane+1) begin : gen_lane
            always @(posedge clk) begin
                // Free-running data register (no reset/CE fanout).
                sum_q[site][lane]<=$signed({{2{cascade_sum[site][lane][16]}},cascade_sum[site][lane]});
            end
        end
    end endgenerate
    integer s,l,t,g;
    genvar accum_site, accum_lane;
    generate for(accum_site=0;accum_site<SITES;accum_site=accum_site+1) begin : gen_feedback_site
        for(accum_lane=0;accum_lane<32;accum_lane=accum_lane+1) begin : gen_feedback_lane
            z100_accum33_dsp_pfb feedback_accumulator (
                .clk(clk), .rst_n(rst_n), .cancel(cancel),
                .load_bias(local_load_bias[accum_site*4+accum_lane/8]),
                .enable(local_accumulator_enable[accum_site*32+accum_lane]),
                .bias(local_active_mask[accum_site*32+accum_lane] ?
                      $signed(bias_copy_q[(accum_site*CLUSTERS)/SITES][accum_lane*32+:32]) : 32'sd0),
                .delta(sum_q[accum_site][accum_lane]), .value_valid(),
                .value(accum[accum_site][accum_lane]), .clamped(), .overflow()
            );
        end
    end endgenerate
    // Bias staging/copies. Strobe == original bias write condition.
    wire bias_write=cfg_bias_valid && cfg_bias_ready && !bias_loaded &&
                    rst_n && !cancel && !cfg_begin && loading && !cfg_commit;
    integer c;
    always @(posedge clk) begin
        if(!rst_n || cancel) bias_write_q<={CLUSTERS*16{1'b0}};
        else bias_write_q<={CLUSTERS*16{bias_write}};
        // v13c: free-running stage (no CE): it is sampled only on the edge
        // after bias_write, when it holds exactly the accepted cfg_bias.
        bias_stage_q<=cfg_bias;
        for(c=0;c<CLUSTERS*16;c=c+1)
            if(bias_write_q[c]) bias_copy_q[c/16][(c%16)*64+:64]<=bias_stage_q[(c%16)*64+:64];
    end
    always @(posedge clk) begin
        for(t=0;t<CLUSTERS*4;t=t+1)
            weight_operand_q[t]<=weight_packed[t%4];
        for(t=0;t<4;t=t+1) begin
            for(s=0;s<SITES;s=s+1)
                for(g=0;g<4;g=g+1)
                    activation_operand_q[s][g][t]<=act_skew[t][s*8+:8];
        end
        if(input_good) activation_q<=act_data;
    end
    function automatic [31:0] clamp33(input signed [32:0] value);
        if(value[32]!=value[31]) clamp33=value[32] ? 32'h80000000 : 32'h7fffffff;
        else clamp33=value[31:0];
    endfunction
    generate for(lane=0;lane<32;lane=lane+1) begin : gen_output
        wire signed [32:0] value=accum[drain_site][lane];
        assign out_data[lane*32+:32]=(lane<lanes) ? clamp33(value) : 32'd0;
        assign out_overflow[lane]=(lane<lanes) && (value[32]!=value[31]);
    end endgenerate

    always @(posedge clk) begin
        if(!rst_n || cancel) begin
            state<=IDLE; loading<=0; bias_loaded<=0;
            expected_groups<=0; written_groups<=0; accepted_groups<=0;
            weights_valid<=0; weights_epoch<=0; pending_epoch<=0;
            token<=0; lanes<=0; sites<=0; drain_site<=0;
            p0_valid<=0;p1_valid<=0;p2_valid<=0;p3_valid<=0;p4_valid<=0;
            p5_valid<=0;p6_valid<=0;p7_valid<=0;p8_valid<=0;
            p0_last<=0;p1_last<=0;p2_last<=0;p3_last<=0;p4_last<=0;
            p5_last<=0;p6_last<=0;p7_last<=0;p8_last<=0;
            error_valid<=0;error_code<=0; weight_byte_bad_q<=1'b0;
        end else begin
            error_valid<=0;error_code<=0;
            p0_valid<=input_good; p1_valid<=p0_valid; p2_valid<=p1_valid; p3_valid<=p2_valid;
            p4_valid<=p3_valid; p5_valid<=p4_valid; p6_valid<=p5_valid; p7_valid<=p6_valid; p8_valid<=p7_valid;
            p0_last<=input_good && expected_last;
            p1_last<=p0_last; p2_last<=p1_last; p3_last<=p2_last; p4_last<=p3_last;
            p5_last<=p4_last; p6_last<=p5_last; p7_last<=p6_last; p8_last<=p7_last;
            if(|weight_byte_bad) weight_byte_bad_q<=1'b1;
            if(cfg_begin && cfg_begin_ready) begin
                weight_byte_bad_q<=1'b0;
                weights_valid<=0; weights_epoch<=0;
                written_groups<=0; bias_loaded<=0;
                if(cfg_epoch==0 || cfg_groups==0 || cfg_groups>1024 || cfg_weight_valid || cfg_bias_valid || cfg_commit) begin
                    loading<=0;error_valid<=1;error_code<=1;
                end else begin
                    loading<=1;pending_epoch<=cfg_epoch;expected_groups<=cfg_groups;
                end
            end else if(loading) begin
                if(cfg_commit && cfg_commit_ready) begin
                    loading<=0;
                    if(written_groups!=expected_groups || !bias_loaded || cfg_weight_valid || cfg_bias_valid || weight_bad_any) begin
                        error_valid<=1;error_code<=2;
                    end else begin weights_valid<=1;weights_epoch<=pending_epoch;end
                end else begin
                    if(cfg_weight_valid && cfg_weight_ready) begin
                        if(written_groups>=expected_groups) begin
                            loading<=0;error_valid<=1;error_code<=3;
                        end else written_groups<=written_groups+1'b1;
                    end
                    if(cfg_bias_valid && cfg_bias_ready) begin
                        if(bias_loaded) begin loading<=0;error_valid<=1;error_code<=3;end
                        else bias_loaded<=1; // payload: bias_stage_q/bias_copy_q
                    end
                end
            end else if(run_valid && run_ready) begin
                if(run_epoch!=weights_epoch || run_token==0 || run_lanes==0 || run_lanes>32 || run_sites==0 || run_sites>SITES) begin
                    error_valid<=1;error_code<=4;
                end else begin
                    state<=INPUTS;accepted_groups<=0;
                    token<=run_token;lanes<=run_lanes;sites<=run_sites;drain_site<=0;
                end
            end
            if(input_fire) begin
                if(!input_good) begin
                    state<=IDLE;weights_valid<=0;weights_epoch<=0;
                    p0_valid<=0;p1_valid<=0;p2_valid<=0;p3_valid<=0;p4_valid<=0;
                    p5_valid<=0;p6_valid<=0;p7_valid<=0;p8_valid<=0;
                    error_valid<=1;error_code<=5;
                end else begin
                    accepted_groups<=accepted_groups+1'b1;
                    if(expected_last) state<=FLUSH;
                end
            end
            if(p8_valid && (state==INPUTS || state==FLUSH)) begin
                if(p8_last) begin state<=OUTPUTS;drain_site<=0;end
            end
            if(out_valid && out_ready) begin
                if(out_last) state<=IDLE;
                else drain_site<=drain_site+1'b1;
            end
        end
    end
endmodule
`default_nettype wire
