`default_nettype none
// Private native-window engine. Four taps x32 channels xSITES products.
// A group contains four adjacent input channels at one ky/kx, rather than
// tile64's flattened tap order. Matching reordered weights are mandatory.
// One buffer: no next-job compute until the previous result has drained.
module z100_window_mac_accum_v2 #(
    parameter integer SITES=4
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
    input wire [3:0] run_sites,
    input wire act_valid,
    output wire act_ready,
    input wire [31:0] act_token,
    input wire act_last,
    input wire [4*SITES*8-1:0] act_data,
    output wire out_valid,
    input wire out_ready,
    output wire [31:0] out_token,
    output wire [3:0] out_site,
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
    reg [3:0] sites, drain_site;
    reg p0_valid,p1_valid,p2_valid,p3_valid;
    reg p0_last,p1_last,p2_last,p3_last;
    reg [4*SITES*8-1:0] activation_q;
    wire [255:0] weight_read_q[0:3];
    (* keep="true" *) reg [255:0] weight_operand_q[0:3];
    // Replicas are local to each8-output group, limiting activation fanout.
    (* dont_touch="true" *) reg signed [7:0] activation_operand_q[0:SITES-1][0:3][0:3];
    (* use_dsp="yes" *) reg signed [15:0] product_q[0:SITES-1][0:31][0:3];
    // Keep the exact 19-bit sum boundary, but prevent the sum tree from
    // consuming the 128 non-multiplier DSP48 cells.
    (* use_dsp = "no" *) reg signed [18:0] sum_q[0:SITES-1][0:31];
    // One 48-bit DSP feedback accumulator per site/lane. Only bits [32:0]
    // participate in the existing 33-bit wrap, clamp, and overflow behavior.
    (* use_dsp = "yes" *) reg signed [47:0] accum_dsp[0:SITES-1][0:31];
    (* use_dsp = "yes" *) wire signed [47:0] accum_plus_sum[0:SITES-1][0:31];
    reg signed [31:0] bias[0:31];
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
    wire weight_write=cfg_weight_valid && cfg_weight_ready && written_groups<expected_groups;
    genvar tap, site, lane;
    generate for(tap=0;tap<4;tap=tap+1) begin : gen_weights
        (* ram_style="block" *) reg [255:0] memory[0:1023];
        reg [255:0] read_q;
        always @(posedge clk) begin
            if(weight_write) memory[written_groups[9:0]]<=cfg_weights[tap*256+:256];
            if(input_good) read_q<=memory[accepted_groups[9:0]];
        end
        assign weight_read_q[tap]=read_q;
    end endgenerate
    generate for(site=0;site<SITES;site=site+1) begin : gen_site
        for(lane=0;lane<32;lane=lane+1) begin : gen_lane
            (* use_dsp = "no" *) wire signed [16:0] pair0=$signed({product_q[site][lane][0][15],product_q[site][lane][0]})+
                                            $signed({product_q[site][lane][1][15],product_q[site][lane][1]});
            (* use_dsp = "no" *) wire signed [16:0] pair1=$signed({product_q[site][lane][2][15],product_q[site][lane][2]})+
                                            $signed({product_q[site][lane][3][15],product_q[site][lane][3]});
            (* use_dsp = "no" *) wire signed [18:0] total=$signed({{2{pair0[16]}},pair0})+$signed({{2{pair1[16]}},pair1});
            assign accum_plus_sum[site][lane]=
                accum_dsp[site][lane]+$signed({{29{sum_q[site][lane][18]}},sum_q[site][lane]});
            always @(posedge clk) begin
                // Free-running data registers have no reset/CE fanout.
                product_q[site][lane][0]<=activation_operand_q[site][lane/8][0]*$signed(weight_operand_q[0][lane*8+:8]);
                product_q[site][lane][1]<=activation_operand_q[site][lane/8][1]*$signed(weight_operand_q[1][lane*8+:8]);
                product_q[site][lane][2]<=activation_operand_q[site][lane/8][2]*$signed(weight_operand_q[2][lane*8+:8]);
                product_q[site][lane][3]<=activation_operand_q[site][lane/8][3]*$signed(weight_operand_q[3][lane*8+:8]);
                sum_q[site][lane]<=total;
            end
        end
    end endgenerate
    integer s,l,t,g;
    always @(posedge clk) begin
        for(t=0;t<4;t=t+1) begin
            weight_operand_q[t]<=weight_read_q[t];
            for(s=0;s<SITES;s=s+1)
                for(g=0;g<4;g=g+1)
                    activation_operand_q[s][g][t]<=activation_q[(t*SITES+s)*8+:8];
        end
        if(input_good) activation_q<=act_data;
    end
    function automatic [31:0] clamp33(input signed [32:0] value);
        if(value[32]!=value[31]) clamp33=value[32] ? 32'h80000000 : 32'h7fffffff;
        else clamp33=value[31:0];
    endfunction
    generate for(lane=0;lane<32;lane=lane+1) begin : gen_output
        wire signed [32:0] value=accum_dsp[drain_site][lane][32:0];
        assign out_data[lane*32+:32]=(lane<lanes) ? clamp33(value) : 32'd0;
        assign out_overflow[lane]=(lane<lanes) && (value[32]!=value[31]);
    end endgenerate

    always @(posedge clk) begin
        if(!rst_n || cancel) begin
            state<=IDLE; loading<=0; bias_loaded<=0;
            expected_groups<=0; written_groups<=0; accepted_groups<=0;
            weights_valid<=0; weights_epoch<=0; pending_epoch<=0;
            token<=0; lanes<=0; sites<=0; drain_site<=0;
            p0_valid<=0;p1_valid<=0;p2_valid<=0;p3_valid<=0;
            p0_last<=0;p1_last<=0;p2_last<=0;p3_last<=0;
            error_valid<=0;error_code<=0;
        end else begin
            error_valid<=0;error_code<=0;
            p0_valid<=input_good; p1_valid<=p0_valid; p2_valid<=p1_valid; p3_valid<=p2_valid;
            p0_last<=input_good && expected_last;
            p1_last<=p0_last; p2_last<=p1_last; p3_last<=p2_last;
            if(cfg_begin && cfg_begin_ready) begin
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
                    if(written_groups!=expected_groups || !bias_loaded || cfg_weight_valid || cfg_bias_valid) begin
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
                        else begin
                            for(l=0;l<32;l=l+1) bias[l]<=cfg_bias[l*32+:32];
                            bias_loaded<=1;
                        end
                    end
                end
            end else if(run_valid && run_ready) begin
                if(run_epoch!=weights_epoch || run_token==0 || run_lanes==0 || run_lanes>32 || run_sites==0 || run_sites>SITES) begin
                    error_valid<=1;error_code<=4;
                end else begin
                    state<=INPUTS;accepted_groups<=0;
                    token<=run_token;lanes<=run_lanes;sites<=run_sites;drain_site<=0;
                    for(s=0;s<SITES;s=s+1)
                        for(l=0;l<32;l=l+1)
                            accum_dsp[s][l]<= (s<run_sites && l<run_lanes) ?
                                $signed({{16{bias[l][31]}},bias[l]}) : 48'sd0;
                end
            end
            if(input_fire) begin
                if(!input_good) begin
                    state<=IDLE;weights_valid<=0;weights_epoch<=0;
                    p0_valid<=0;p1_valid<=0;p2_valid<=0;p3_valid<=0;
                    error_valid<=1;error_code<=5;
                end else begin
                    accepted_groups<=accepted_groups+1'b1;
                    if(expected_last) state<=FLUSH;
                end
            end
            if(p3_valid && (state==INPUTS || state==FLUSH)) begin
                for(s=0;s<SITES;s=s+1)
                    for(l=0;l<32;l=l+1)
                        if(s<sites && l<lanes)
                            accum_dsp[s][l]<=accum_plus_sum[s][l];
                if(p3_last) begin state<=OUTPUTS;drain_site<=0;end
            end
            if(out_valid && out_ready) begin
                if(out_last) state<=IDLE;
                else drain_site<=drain_site+1'b1;
            end
        end
    end
endmodule
`default_nettype wire
