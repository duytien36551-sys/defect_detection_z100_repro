`default_nettype none
// Private32-lane exact-factor replacement, sequential factor configuration.
// Runtime metadata is compatible with native20; latency is five stages.
// Production threshold/configuration ABI is intentionally not modified.
(* use_dsp="no" *)
module z100_requant_factor32 (
    input wire clk,rst_n,cancel,
    input wire cfg_begin,output wire cfg_begin_ready,
    input wire [31:0] cfg_epoch,input wire [5:0] cfg_lanes,
    input wire cfg_word_valid,output wire cfg_word_ready,
    input wire [30:0] cfg_multiplier,input wire [5:0] cfg_shift,
    input wire cfg_commit,output wire cfg_commit_ready,
    output reg cfg_error,output reg input_error,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_epoch,in_token,input wire [4:0] in_site,input wire in_last,
    input wire [1023:0] in_data,
    output wire out_valid,input wire out_ready,
    output wire [31:0] out_epoch,out_token,
    output wire [4:0] out_site,output wire [5:0] out_lanes,
    output wire out_last,output wire [255:0] out_data
);
    reg loading,loaded,fault_q;
    reg [31:0] epoch;
    reg [5:0] lanes,cfg_count;
    reg [30:0] multipliers[0:31];reg [5:0] shifts[0:31];
    reg [4:0] valid_q;
    reg [31:0] epoch_q[0:4],token_q[0:4];
    reg [4:0] site_q[0:4];reg last_q[0:4];
    wire control_busy=cfg_begin||cfg_word_valid||cfg_commit;
    wire enable=rst_n&&!cancel;
    wire empty=~(|valid_q);
    wire enabled=loaded&&!loading&&!control_busy&&enable&&!fault_q;
    wire bad_input=enabled&&in_valid&&(in_epoch!=epoch||in_token==0||in_site>=20);
    wire local_cancel=cancel||bad_input||fault_q;
    wire [31:0] lane_ready,lane_valid,lane_error;
    wire [31:0] lane_mask=32'hffffffff>>(32-lanes);
    wire all_ready=(lane_ready&lane_mask)==lane_mask;
    wire all_valid=(lane_valid&lane_mask)==lane_mask;
    wire any_valid=|(lane_valid&lane_mask);
    wire skew=loaded&&!loading&&!bad_input&&enable&&!fault_q&&
                    ((any_valid!=valid_q[4])||(any_valid&&!all_valid));
    assign cfg_begin_ready=enable&&empty&&!loading&&!cfg_word_valid&&!cfg_commit;
    assign cfg_word_ready=enable&&empty&&loading&&!cfg_begin&&!cfg_commit;
    assign cfg_commit_ready=enable&&empty&&loading&&!cfg_begin&&!cfg_word_valid;
    assign in_ready=enabled&&all_ready&&!bad_input&&!skew;
    assign out_valid=enable&&valid_q[4]&&all_valid&&!bad_input&&!fault_q&&!skew;
    assign out_epoch=epoch_q[4];assign out_token=token_q[4];
    assign out_site=site_q[4];assign out_lanes=lanes;assign out_last=last_q[4];
    wire input_fire=in_valid&&in_ready;
    genvar lane;
    generate for(lane=0;lane<32;lane=lane+1)begin:gen_lane
        wire signed [7:0] value;
        z100_requant_factor unit(.clk(clk),.rst_n(rst_n),.cancel(local_cancel),
            .in_valid(input_fire&&(lane<lanes)),.in_ready(lane_ready[lane]),
            .in_value(in_data[lane*32+:32]),.in_multiplier(multipliers[lane]),.in_shift(shifts[lane]),.in_token(32'd0),
            .out_valid(lane_valid[lane]),.out_ready(out_ready&&valid_q[4]&&all_valid&&!skew),
            .out_token(),.out_data(value),.out_product(),.error_valid(lane_error[lane]));
        assign out_data[lane*8+:8]=lane<lanes ? value : 8'd0;
    end endgenerate
    integer i;
    always @(posedge clk)begin
        if(!rst_n||cancel)begin
            loading<=0;loaded<=0;fault_q<=0;epoch<=0;lanes<=0;cfg_count<=0;
            cfg_error<=0;input_error<=0;valid_q<=0;
        end else begin
            cfg_error<=0;input_error<=0;
            if(cfg_begin&&cfg_begin_ready)begin
                loaded<=0;fault_q<=0;cfg_count<=0;
                if(cfg_epoch==0||cfg_lanes==0||cfg_lanes>32)begin loading<=0;cfg_error<=1;end
                else begin loading<=1;epoch<=cfg_epoch;lanes<=cfg_lanes;end
            end else if(cfg_word_valid&&cfg_word_ready)begin
                if(cfg_count>=lanes||cfg_multiplier==0)begin
                    loading<=0;loaded<=0;cfg_count<=0;cfg_error<=1;
                end else begin
                    multipliers[cfg_count]<=cfg_multiplier;shifts[cfg_count]<=cfg_shift;cfg_count<=cfg_count+1;
                end
            end else if(cfg_commit&&cfg_commit_ready)begin
                loading<=0;
                if(cfg_count==lanes)loaded<=1;
                else begin loaded<=0;cfg_error<=1;end
            end
            if(bad_input||skew||(|(lane_error&lane_mask)))begin
                loaded<=0;loading<=0;input_error<=1;valid_q<=0;fault_q<=1;
            end else if(all_ready)begin
                valid_q<={valid_q[3:0],input_fire};
                if(input_fire)begin epoch_q[0]<=in_epoch;token_q[0]<=in_token;site_q[0]<=in_site;last_q[0]<=in_last;end
                for(i=1;i<5;i=i+1)if(valid_q[i-1])begin
                    epoch_q[i]<=epoch_q[i-1];token_q[i]<=token_q[i-1];site_q[i]<=site_q[i-1];last_q[i]<=last_q[i-1];
                end
            end
        end
    end
endmodule
`default_nettype wire
