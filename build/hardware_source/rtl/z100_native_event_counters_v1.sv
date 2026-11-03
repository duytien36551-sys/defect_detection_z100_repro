`default_nettype none

module z100_native_event_counters_v1 (
    input wire clk,
    input wire rst_n,
    input wire event_start,
    input wire [31:0] event_epoch,
    input wire [7:0] event_id,
    input wire success_terminal,
    input wire fault,
    input wire all_io_quiet,
    input wire [3:0] fault_code,
    input wire cancel,

    input wire [1:0] read_kind,
    input wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire m_axi_rvalid,
    input wire m_axi_rready,
    input wire m_axi_rlast,
    input wire m_axi_awvalid,
    input wire m_axi_awready,
    input wire m_axi_wvalid,
    input wire m_axi_wready,
    input wire [7:0] m_axi_wstrb,
    input wire m_axi_wlast,
    input wire m_axi_bvalid,
    input wire m_axi_bready,

    input wire phase_enable,
    input wire load_active,
    input wire compute_active,
    input wire write_active,
    input wire mac_good_group,
    input wire [10:0] mac_good_slots,
    input wire mac_starve,
    input wire mac_output_stall,
    input wire residency_hit,
    input wire residency_miss,

    input wire [5:0] read_index,
    output reg [31:0] read_data,
    output reg snapshot_valid,
    output reg [1:0] snapshot_outcome,
    output reg snapshot_overflow,
    output reg [31:0] snapshot_epoch,
    output reg [7:0] snapshot_event,
    output reg [3:0] snapshot_fault_code
);
    localparam [1:0] READ_NONE=2'd0, READ_FEATURE=2'd1,
                     READ_PARAMETER=2'd2, READ_DIRECTORY=2'd3;
    localparam [1:0] OUTCOME_NONE=2'd0, OUTCOME_SUCCESS=2'd1,
                     OUTCOME_CANCEL=2'd2, OUTCOME_FAULT=2'd3;

    localparam integer C_EVENT_CYCLES=0;
    localparam integer C_FEATURE_AR=1;
    localparam integer C_FEATURE_R_BEATS=2;
    localparam integer C_FEATURE_R_BYTES=3;
    localparam integer C_PARAMETER_AR=4;
    localparam integer C_PARAMETER_R_BEATS=5;
    localparam integer C_PARAMETER_R_BYTES=6;
    localparam integer C_DIRECTORY_AR=7;
    localparam integer C_DIRECTORY_R_BEATS=8;
    localparam integer C_DIRECTORY_R_BYTES=9;
    localparam integer C_AR_WAIT=10;
    localparam integer C_R_GAP=11;
    localparam integer C_AW=12;
    localparam integer C_W_BEATS=13;
    localparam integer C_W_BYTES=14;
    localparam integer C_B=15;
    localparam integer C_AW_WAIT=16;
    localparam integer C_W_STALL=17;
    localparam integer C_B_WAIT=18;
    localparam integer C_MAC_GROUPS=19;
    localparam integer C_MAC_USEFUL_SLOTS=20;
    localparam integer C_MAC_ACTIVE=21;
    localparam integer C_MAC_STARVE=22;
    localparam integer C_MAC_OUTPUT_STALL=23;
    localparam integer C_LOAD_ACTIVE=24;
    localparam integer C_WRITE_ACTIVE=25;
    localparam integer C_LOAD_COMPUTE=26;
    localparam integer C_LOAD_WRITE=27;
    localparam integer C_COMPUTE_WRITE=28;
    localparam integer C_LOAD_COMPUTE_WRITE=29;
    localparam integer C_RESIDENCY_HIT=30;
    localparam integer C_RESIDENCY_MISS=31;
    localparam integer COUNTER_COUNT=32;

    reg event_open_q;
    reg fault_publish_pending_q;
    reg cancel_seen_q;
    reg [31:0] event_epoch_q;
    reg [7:0] event_id_q;
    reg overflow_q;
    reg read_open_q;
    reg [1:0] read_kind_q;
    reg b_pending_q;
    reg [31:0] counters_q [0:COUNTER_COUNT-1];
    reg [31:0] snapshot_q [0:COUNTER_COUNT-1];
    reg [31:0] increment [0:COUNTER_COUNT-1];
    reg [32:0] sum [0:COUNTER_COUNT-1];
    reg [31:0] counter_next [0:COUNTER_COUNT-1];
    reg overflow_now;

    wire ar_fire=m_axi_arvalid && m_axi_arready;
    wire r_fire=m_axi_rvalid && m_axi_rready;
    wire aw_fire=m_axi_awvalid && m_axi_awready;
    wire w_fire=m_axi_wvalid && m_axi_wready;
    wire b_fire=m_axi_bvalid && m_axi_bready;
    wire terminal=success_terminal || (fault && all_io_quiet);
    wire sample_phase=phase_enable && !fault && !cancel;
    wire [3:0] wstrb_count={3'd0,m_axi_wstrb[0]}+{3'd0,m_axi_wstrb[1]}+
                 {3'd0,m_axi_wstrb[2]}+{3'd0,m_axi_wstrb[3]}+
                 {3'd0,m_axi_wstrb[4]}+{3'd0,m_axi_wstrb[5]}+
                 {3'd0,m_axi_wstrb[6]}+{3'd0,m_axi_wstrb[7]};
    wire [1:0] accepted_read_kind=read_open_q ? read_kind_q :
                                      (ar_fire ? read_kind : READ_NONE);

    integer i;
    always @* begin
        for (i=0;i<COUNTER_COUNT;i=i+1)
            increment[i]=32'd0;

        if (event_open_q) begin
            increment[C_EVENT_CYCLES]=32'd1;
            if (ar_fire) begin
                case (read_kind)
                    READ_FEATURE: increment[C_FEATURE_AR]=32'd1;
                    READ_PARAMETER: increment[C_PARAMETER_AR]=32'd1;
                    READ_DIRECTORY: increment[C_DIRECTORY_AR]=32'd1;
                    default: begin end
                endcase
            end
            if (r_fire) begin
                case (accepted_read_kind)
                    READ_FEATURE: begin
                        increment[C_FEATURE_R_BEATS]=32'd1;
                        increment[C_FEATURE_R_BYTES]=32'd8;
                    end
                    READ_PARAMETER: begin
                        increment[C_PARAMETER_R_BEATS]=32'd1;
                        increment[C_PARAMETER_R_BYTES]=32'd8;
                    end
                    READ_DIRECTORY: begin
                        increment[C_DIRECTORY_R_BEATS]=32'd1;
                        increment[C_DIRECTORY_R_BYTES]=32'd8;
                    end
                    default: begin end
                endcase
            end
            if (m_axi_arvalid && !m_axi_arready)
                increment[C_AR_WAIT]=32'd1;
            if (read_open_q && !m_axi_rvalid)
                increment[C_R_GAP]=32'd1;
            if (aw_fire) increment[C_AW]=32'd1;
            if (w_fire) begin
                increment[C_W_BEATS]=32'd1;
                increment[C_W_BYTES]={28'd0,wstrb_count};
            end
            if (b_fire) increment[C_B]=32'd1;
            if (m_axi_awvalid && !m_axi_awready)
                increment[C_AW_WAIT]=32'd1;
            if (m_axi_wvalid && !m_axi_wready)
                increment[C_W_STALL]=32'd1;
            if (b_pending_q && !m_axi_bvalid)
                increment[C_B_WAIT]=32'd1;

            if (sample_phase) begin
                if (mac_good_group) begin
                    increment[C_MAC_GROUPS]=32'd1;
                    increment[C_MAC_USEFUL_SLOTS]={21'd0,mac_good_slots};
                end
                if (compute_active) increment[C_MAC_ACTIVE]=32'd1;
                if (mac_starve) increment[C_MAC_STARVE]=32'd1;
                if (mac_output_stall) increment[C_MAC_OUTPUT_STALL]=32'd1;
                if (load_active) increment[C_LOAD_ACTIVE]=32'd1;
                if (write_active) increment[C_WRITE_ACTIVE]=32'd1;
                if (load_active && compute_active)
                    increment[C_LOAD_COMPUTE]=32'd1;
                if (load_active && write_active)
                    increment[C_LOAD_WRITE]=32'd1;
                if (compute_active && write_active)
                    increment[C_COMPUTE_WRITE]=32'd1;
                if (load_active && compute_active && write_active)
                    increment[C_LOAD_COMPUTE_WRITE]=32'd1;
                if (residency_hit) increment[C_RESIDENCY_HIT]=32'd1;
                if (residency_miss) increment[C_RESIDENCY_MISS]=32'd1;
            end
        end
    end

    integer j;
    always @* begin
        overflow_now=1'b0;
        for (j=0;j<COUNTER_COUNT;j=j+1) begin
            sum[j]={1'b0,counters_q[j]}+{1'b0,increment[j]};
            if (sum[j][32]) begin
                counter_next[j]=32'hffffffff;
                if (increment[j]!=0) overflow_now=1'b1;
            end else begin
                counter_next[j]=sum[j][31:0];
            end
        end
    end

    always @* begin
        if (read_index<COUNTER_COUNT)
            read_data=snapshot_q[read_index];
        else
            read_data=32'd0;
    end

    integer k;
    always @(posedge clk) begin
        if (!rst_n) begin
            event_open_q<=1'b0;
            fault_publish_pending_q<=1'b0;
            cancel_seen_q<=1'b0;
            event_epoch_q<=32'd0;
            event_id_q<=8'd0;
            overflow_q<=1'b0;
            read_open_q<=1'b0;
            read_kind_q<=READ_NONE;
            b_pending_q<=1'b0;
            snapshot_valid<=1'b0;
            snapshot_outcome<=OUTCOME_NONE;
            snapshot_overflow<=1'b0;
            snapshot_epoch<=32'd0;
            snapshot_event<=8'd0;
            snapshot_fault_code<=4'd0;
            for (k=0;k<COUNTER_COUNT;k=k+1) begin
                counters_q[k]<=32'd0;
                snapshot_q[k]<=32'd0;
            end
        end else if (event_start) begin
            event_open_q<=1'b1;
            fault_publish_pending_q<=1'b0;
            cancel_seen_q<=cancel;
            event_epoch_q<=event_epoch;
            event_id_q<=event_id;
            overflow_q<=1'b0;
            read_open_q<=1'b0;
            read_kind_q<=READ_NONE;
            b_pending_q<=1'b0;
            snapshot_valid<=1'b0;
            snapshot_outcome<=OUTCOME_NONE;
            snapshot_overflow<=1'b0;
            snapshot_epoch<=32'd0;
            snapshot_event<=8'd0;
            snapshot_fault_code<=4'd0;
            for (k=0;k<COUNTER_COUNT;k=k+1) begin
                counters_q[k]<=32'd0;
                snapshot_q[k]<=32'd0;
            end
        end else if (fault_publish_pending_q) begin
            // Counters and identity froze on the original terminal edge T.
            // Sample only the backend code at T+1; never count this extra edge.
            snapshot_fault_code<=fault_code;
            snapshot_valid<=1'b1;
            fault_publish_pending_q<=1'b0;
        end else if (event_open_q) begin
            if (cancel) cancel_seen_q<=1'b1;
            if (ar_fire) begin
                read_open_q<=1'b1;
                read_kind_q<=read_kind;
            end
            if (r_fire && m_axi_rlast)
                read_open_q<=1'b0;
            if (w_fire && m_axi_wlast)
                b_pending_q<=1'b1;
            if (b_fire)
                b_pending_q<=1'b0;

            overflow_q<=overflow_q || overflow_now;
            for (k=0;k<COUNTER_COUNT;k=k+1)
                counters_q[k]<=counter_next[k];

            if (terminal) begin
                event_open_q<=1'b0;
                snapshot_valid<=success_terminal;
                fault_publish_pending_q<=!success_terminal;
                snapshot_outcome<=success_terminal ? OUTCOME_SUCCESS :
                    ((cancel_seen_q || cancel) ? OUTCOME_CANCEL : OUTCOME_FAULT);
                snapshot_overflow<=overflow_q || overflow_now;
                snapshot_epoch<=event_epoch_q;
                snapshot_event<=event_id_q;
                snapshot_fault_code<=4'd0;
                for (k=0;k<COUNTER_COUNT;k=k+1)
                    snapshot_q[k]<=counter_next[k];
            end
        end
    end
endmodule

`default_nettype wire
