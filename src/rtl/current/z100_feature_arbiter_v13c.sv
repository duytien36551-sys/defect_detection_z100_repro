`default_nettype none
// timing_v13c feature-bank arbitration between feature loading (cfg) and the
// conv / pool consumers. Replaces three combinational top-level equations in
// which source_config_permitted contained "a consumer is admitted this
// cycle" (= store_valid / active_epoch compare / pool job_ready), so the
// store's state reached its own cfg_begin_ready and pending_feature_* CE
// through ~22 levels.
// Rule set:
//  * po_q (registered) = last cycle a consumer's admission pre-condition held
//    on the read bank. cfg on that bank is refused while po_q=1, exactly as
//    the original refused it while admission was possible -> consumers that
//    were already waiting keep priority over a new load.
//  * a consumer whose pre-condition only became true this cycle (po_q=0)
//    yields to cfg presented this cycle on the same bank.
//  * so cfg-fire and admission are mutually exclusive on the read bank in
//    every cycle, and neither side can block the other forever.
module z100_feature_arbiter_v13c (
    input wire clk, input wire rst_n, input wire cancel,
    input wire conv_owned, input wire pool_owned,
    input wire pack_cfg_valid, input wire [31:0] pack_cfg_epoch,
    input wire pool_job_valid, input wire inner_pool_ready,
    input wire bank_read_idle, input wire feature_store_valid, input wire feature_loading,
    input wire [31:0] feature_active_epoch,
    input wire ingress_bank, input wire read_source_bank,
    input wire cfg_begin, input wire cfg_word_valid, input wire cfg_commit,
    output wire conv_admission, output wire pool_admission,
    output wire source_config_permitted
);
    reg po_q;
    wire conv_pre = !pool_owned && !pool_job_valid && bank_read_idle && feature_store_valid &&
                    !feature_loading && pack_cfg_epoch == feature_active_epoch;
    wire pool_pre = !conv_owned && !pack_cfg_valid && bank_read_idle;
    wire po_now = (pack_cfg_valid && conv_pre) || (pool_job_valid && inner_pool_ready && pool_pre);
    wire same_bank = ingress_bank == read_source_bank;
    wire cfg_present = cfg_begin || cfg_word_valid || cfg_commit;
    // A newly-arriving consumer yields to cfg already presented on its bank.
    wire yield = cfg_present && same_bank && !po_q;
    assign conv_admission = conv_pre && !yield;
    assign pool_admission = pool_pre && !yield;
    assign source_config_permitted = (!conv_owned && !pool_owned && !po_q) || !same_bank;
    always @(posedge clk) begin
        if (!rst_n || cancel) po_q <= 1'b0;
        else po_q <= po_now;
    end
endmodule
`default_nettype wire
