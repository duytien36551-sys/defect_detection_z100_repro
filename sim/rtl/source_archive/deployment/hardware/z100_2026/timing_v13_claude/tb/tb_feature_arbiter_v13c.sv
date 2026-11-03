`timescale 1ns/1ps
// Closed-loop property test of z100_feature_arbiter_v13c (rules only; the
// store / packer / pool are abstract random models). Checked every cycle:
//  P1 never (cfg fire on the read bank) && (conv or pool admission fire)
//  P2 a consumer whose admission pre-condition already held last cycle is
//     never overtaken by a cfg begin on its bank (original priority kept)
//  P3 liveness: every held request fires within LIMIT cycles
module tb_feature_arbiter_v13c;
    parameter integer SEED=1, CYCLES=300000, LIMIT=400;
    reg clk=0; always #5 clk=~clk;
    reg rst_n, cancel;
    reg conv_owned, pool_owned, pack_cfg_valid, pool_job_valid, inner_pool_ready;
    reg bank_read_idle, store_valid, loading, ingress_bank, cfg_begin, cfg_word, cfg_commit;
    reg conv_pack_ready, fw_begin_ready;
    reg [31:0] pack_epoch, active_epoch;
    wire conv_adm, pool_adm, permitted;
    z100_feature_arbiter_v13c dut(.clk(clk),.rst_n(rst_n),.cancel(cancel),.conv_owned(conv_owned),.pool_owned(pool_owned),
        .pack_cfg_valid(pack_cfg_valid),.pack_cfg_epoch(pack_epoch),.pool_job_valid(pool_job_valid),.inner_pool_ready(inner_pool_ready),
        .bank_read_idle(bank_read_idle),.feature_store_valid(store_valid),.feature_loading(loading),.feature_active_epoch(active_epoch),
        .ingress_bank(ingress_bank),.read_source_bank(1'b0),.cfg_begin(cfg_begin),.cfg_word_valid(cfg_word),.cfg_commit(cfg_commit),
        .conv_admission(conv_adm),.pool_admission(pool_adm),.source_config_permitted(permitted));
    wire conv_fire = pack_cfg_valid && conv_adm && conv_pack_ready;
    wire pool_fire = pool_job_valid && inner_pool_ready && pool_adm;
    wire cfg_fire  = cfg_begin && permitted && fw_begin_ready;
    wire conv_pre  = !pool_owned && !pool_job_valid && bank_read_idle && store_valid && !loading && pack_epoch==active_epoch;
    integer s, cyc, p1, p2, wc, wp, wg, maxw, own_t, load_t, nconv, npool, ncfg, nyield;
    reg conv_pre_q, conv_hold_q;
    always @(posedge clk) begin conv_pre_q <= conv_pre && pack_cfg_valid; conv_hold_q <= pack_cfg_valid; end
    always @(posedge clk) if (rst_n) begin
        if (cfg_fire && ingress_bank==0 && (conv_fire || pool_fire)) p1 = p1 + 1;
        if (cfg_fire && ingress_bank==0 && conv_pre_q && pack_cfg_valid && conv_pre) p2 = p2 + 1;
        if (cfg_begin && ingress_bank==0 && conv_pre && pack_cfg_valid && !conv_fire && !conv_pre_q) nyield = nyield + 1;
    end
    initial begin
        s=SEED; p1=0; p2=0; wc=0; wp=0; wg=0; maxw=0; own_t=0; load_t=0; nconv=0; npool=0; ncfg=0; nyield=0;
        rst_n=0; cancel=0; conv_owned=0; pool_owned=0; pack_cfg_valid=0; pool_job_valid=0; inner_pool_ready=1;
        bank_read_idle=1; store_valid=1; loading=0; ingress_bank=0; cfg_begin=0; cfg_word=0; cfg_commit=0;
        conv_pack_ready=1; fw_begin_ready=1; pack_epoch=5; active_epoch=5;
        repeat(3) @(negedge clk); rst_n=1;
        for (cyc=0; cyc<CYCLES; cyc=cyc+1) begin
            @(posedge clk); #1;
            // consequences of this edge's fires (abstract models)
            if (conv_fire) begin conv_owned=1; own_t=3+{$random(s)}%20; pack_cfg_valid=0; nconv=nconv+1; wc=0; end
            if (pool_fire) begin pool_owned=1; own_t=3+{$random(s)}%20; pool_job_valid=0; npool=npool+1; wp=0; end
            if (cfg_fire) begin cfg_begin=0; ncfg=ncfg+1; wg=0;
                if (ingress_bank==0) begin store_valid=0; loading=1; load_t=2+{$random(s)}%15; end end
            if ((conv_owned||pool_owned) && own_t>0) begin own_t=own_t-1; if (own_t==0) begin conv_owned=0; pool_owned=0; end end
            if (loading && load_t>0) begin load_t=load_t-1; if (load_t==0) begin loading=0; store_valid=1; active_epoch=active_epoch+1; end end
            // new requests (held until they fire)
            if (!pack_cfg_valid && !pool_job_valid && !conv_owned && !pool_owned && ({$random(s)}%6)==0) begin
                if ({$random(s)}%2) begin pack_cfg_valid=1; pack_epoch=({$random(s)}%4==0) ? active_epoch+1 : active_epoch; end
                else pool_job_valid=1;
            end
            if (!cfg_begin && !loading && ({$random(s)}%9)==0) begin cfg_begin=1; ingress_bank={$random(s)}%2; end
            inner_pool_ready=({$random(s)}%4)!=0; conv_pack_ready=({$random(s)}%4)!=0; fw_begin_ready=({$random(s)}%5)!=0;
            bank_read_idle=!(conv_owned||pool_owned) || ({$random(s)}%3==0);
            // a conv waiting for an epoch that is never loaded would wait forever by design: let it retarget
            if (pack_cfg_valid && wc>LIMIT/2 && pack_epoch!=active_epoch) pack_epoch=active_epoch;
            if (pack_cfg_valid) wc=wc+1; if (pool_job_valid) wp=wp+1; if (cfg_begin) wg=wg+1;
            if (wc>maxw) maxw=wc; if (wp>maxw) maxw=wp; if (wg>maxw) maxw=wg;
        end
        $display("ARB seed=%0d cycles=%0d conv=%0d pool=%0d cfg=%0d yields=%0d P1_excl_viol=%0d P2_prio_viol=%0d max_wait=%0d %s",
                 SEED, CYCLES, nconv, npool, ncfg, nyield, p1, p2, maxw, (p1==0&&p2==0&&maxw<LIMIT) ? "PASS" : "FAIL");
        $finish;
    end
endmodule
