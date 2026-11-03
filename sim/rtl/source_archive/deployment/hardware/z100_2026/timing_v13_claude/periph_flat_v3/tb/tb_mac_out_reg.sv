`timescale 1ns/1ps
// 2026-10-31: MAC old (live drain_site mux) vs new (registered output).
// The new version presents each result ONE cycle earlier than the old one,
// which is a legal, purely latency-side change as long as the ORDERED stream
// of accepted output beats is identical. So this miter compares the event
// stream (token, site, last, lanes, data, overflow) plus the error and
// weights_valid sequences, ignoring the cycle stamp column.
`define MAC_PORTS .clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_begin(cfg_begin),.cfg_begin_ready(cfg_begin_ready), \
    .cfg_epoch(cfg_epoch),.cfg_groups(cfg_groups),.cfg_weight_valid(cfg_weight_valid),.cfg_weight_ready(cfg_weight_ready), \
    .cfg_weights(cfg_weights),.cfg_bias_valid(cfg_bias_valid),.cfg_bias_ready(cfg_bias_ready),.cfg_bias(cfg_bias), \
    .cfg_commit(cfg_commit),.cfg_commit_ready(cfg_commit_ready),.weights_valid(weights_valid),.weights_epoch(weights_epoch), \
    .error_valid(error_valid),.error_code(error_code),.run_valid(run_valid),.run_ready(run_ready),.run_epoch(run_epoch), \
    .run_token(run_token),.run_lanes(run_lanes),.run_sites(run_sites),.act_valid(act_valid),.act_ready(act_ready), \
    .act_token(act_token),.act_last(act_last),.act_data(act_data),.out_valid(out_valid),.out_ready(out_ready), \
    .out_token(out_token),.out_site(out_site),.out_last(out_last),.out_lanes(out_lanes),.out_data(out_data),.out_overflow(out_overflow)

module mac_driver #(parameter integer SITES=4, parameter integer NEW=0,
                    parameter integer SEED=1, parameter integer NSCEN=150, parameter integer TIGHT=0) (
    input wire clk, output reg done, output integer nout, output integer nerr, output integer cycles);
    reg rst_n, cancel, cfg_begin, cfg_weight_valid, cfg_bias_valid, cfg_commit;
    reg run_valid, act_valid, act_last, out_ready;
    reg [31:0] cfg_epoch, run_epoch, run_token, act_token;
    reg [10:0] cfg_groups; reg [1023:0] cfg_weights, cfg_bias;
    reg [5:0] run_lanes; reg [4:0] run_sites; reg [4*SITES*8-1:0] act_data;
    wire cfg_begin_ready,cfg_weight_ready,cfg_bias_ready,cfg_commit_ready,weights_valid;
    wire error_valid,run_ready,act_ready,out_valid,out_last;
    wire [31:0] weights_epoch,out_token,out_overflow; wire [2:0] error_code;
    wire [4:0] out_site; wire [5:0] out_lanes; wire [1023:0] out_data;
    generate if(NEW) begin : gnew
        z100_window_mac_timing_v13 #(.SITES(SITES)) dut(`MAC_PORTS);
    end else begin : gold
        z100_mac_ref_old #(.SITES(SITES)) dut(`MAC_PORTS);
    end endgenerate

    integer fd, nlast, s, rs, sc, i, r, a, g, nr, kind, rk, bpos, m, base, gap, rk_det, cw;
    reg wv_q; reg [6:0] rdy_q; reg [31:0] ep, tok; reg abort;
    initial begin
        fd = $fopen(NEW ? "log_new.txt" : "log_old.txt", "w");
        nout=0; nerr=0; nlast=0; wv_q=0; cycles=0; rs=SEED*7+3;
    end
    always @(posedge clk) begin
        cycles = cycles+1;
        if(out_valid && out_ready) begin
            $fdisplay(fd,"OUT %h %0d %0d %0d %h %h",out_token,out_site,out_last,out_lanes,out_data,out_overflow);
            nout=nout+1; if(out_last) nlast=nlast+1;
        end
        if(error_valid) begin $fdisplay(fd,"ERR %0d",error_code); nerr=nerr+1; end
        if(weights_valid!==wv_q) $fdisplay(fd,"WV %0d %h",weights_valid,weights_epoch);
        wv_q <= weights_valid;
        // 2026-10-31 coverage fix: the event log only records `out_valid &&
        // out_ready` beats, so a design that presents a beat DURING cancel was
        // only caught when the random out_ready happened to be high on that
        // exact cycle (1 of 5 seeds against the mutant that drops the
        // combinational cancel mask). Record the contract directly: neither the
        // old (state==OUTPUTS && !cancel) nor the new (out_valid_q && ... &&
        // !cancel) form may assert out_valid while cancel is high.
        if(cancel && out_valid) $fdisplay(fd,"VC %h",out_site);
    end
    always @(negedge clk) out_ready <= ({$random(rs)}%4)!=0;

    function [1023:0] rand1024(input integer dummy);
        integer k; begin for(k=0;k<32;k=k+1) rand1024[k*32+:32]=$random(s); end
    endfunction
    task idle(input integer n); integer k; begin for(k=0;k<n;k=k+1) @(negedge clk); end endtask
    task w_beat(input [1023:0] w, input with_bias); begin
        cfg_weights=w; cfg_weight_valid=1; cfg_bias_valid=with_bias;
        @(posedge clk); while(!cfg_weight_ready) @(posedge clk);
        @(negedge clk); cfg_weight_valid=0; cfg_bias_valid=0; end endtask
    task b_beat; begin
        cfg_bias_valid=1; @(posedge clk); while(!cfg_bias_ready) @(posedge clk);
        @(negedge clk); cfg_bias_valid=0; end endtask
    task begin_beat; begin
        cfg_begin=1; @(posedge clk); while(!cfg_begin_ready) @(posedge clk);
        @(negedge clk); cfg_begin=0; end endtask
    task commit_beat; begin
        cfg_commit=1; @(posedge clk); while(!cfg_commit_ready) @(posedge clk);
        @(negedge clk); cfg_commit=0; end endtask
    task run_beat; begin
        run_valid=1; @(posedge clk); while(!run_ready) @(posedge clk);
        @(negedge clk); run_valid=0; end endtask
    task act_beat; begin
        act_valid=1; @(posedge clk); while(!act_ready) @(posedge clk);
        @(negedge clk); act_valid=0; end endtask
    task make_bias; integer k, mode; begin
        mode={$random(s)}%4;
        for(k=0;k<32;k=k+1)
            case(mode)
                0: cfg_bias[k*32+:32]=32'h7ffff000+({$random(s)}%8192);
                1: cfg_bias[k*32+:32]=32'h80001000-({$random(s)}%8192);
                default: cfg_bias[k*32+:32]=$random(s);
            endcase
    end endtask
    initial begin
        s=SEED; done=0;
        rst_n=0; cancel=0; cfg_begin=0; cfg_weight_valid=0; cfg_bias_valid=0; cfg_commit=0;
        run_valid=0; act_valid=0; act_last=0; cfg_epoch=0; cfg_groups=0;
        cfg_weights=0; cfg_bias=0; run_epoch=0; run_token=0; act_token=0;
        run_lanes=0; run_sites=0; act_data=0;
        idle(5); rst_n=1; idle(2);
        for(sc=0;sc<NSCEN;sc=sc+1) begin
            g = 1+{$random(s)}%6; ep = 1+{$random(s)}%1000;
            kind = {$random(s)}%12;
            cfg_epoch = (kind==0) ? 0 : ep; cfg_groups = g;
            begin_beat;
            if(kind!=0) begin
                make_bias; bpos={$random(s)}%g;
                for(i=0;i<g-((kind==4)?1:0);i=i+1) begin
                    if(i==bpos && kind!=1 && ({$random(s)}%3)==0) w_beat(rand1024(0),1);
                    else begin
                        if(i==bpos && kind!=1) begin idle({$random(s)}%2); b_beat; end
                        w_beat(rand1024(0),0);
                    end
                    if(!TIGHT) idle({$random(s)}%2);
                end
                if(kind==2) w_beat(rand1024(0),0);
                if(kind==3) b_beat;
                if(!TIGHT) idle({$random(s)}%3);
                if(kind!=2 && kind!=3) commit_beat;
            end
            if(!TIGHT) idle(1+{$random(s)}%2);
            if(weights_valid) begin
                nr = 1+{$random(s)}%4; abort=0;
                for(r=0;r<nr && !abort;r=r+1) begin
                    rk = {$random(s)}%16;
                    rk_det = (rk==4);
                    tok = 1+{$random(s)}%60000;
                    run_epoch = (rk==0) ? ep+1 : ep; run_token = tok;
                    run_lanes = (rk==1) ? 33 : 1+{$random(s)}%32;
                    run_sites = 1+{$random(s)}%SITES;
                    run_beat;
                    if(rk<=1) begin idle(2); end
                    else begin
                        for(a=0;a<g && !abort;a=a+1) begin
                            for(i=0;i<4*SITES;i=i+1) act_data[i*8+:8]=$random(s);
                            act_token = (rk==2 && a==g-1) ? tok+1 : tok;
                            act_last = (rk==3) ? ((g>1) ? (a==0) : 1'b0) : (a==g-1);
                            if(rk==5 && a==g/2) begin cancel=1; idle(1); cancel=0; abort=1; end
                            else begin
                                act_beat;
                                if(act_token!=tok || act_last!=(a==g-1)) abort=1;
                                gap={$random(s)}%4; if(gap<2) gap=0; idle(gap);
                            end
                        end
                        act_last=0;
                        if(!abort) begin
                            if(rk==4) begin
                                m={$random(s)}%(run_sites+1); base=nout;
                                while(nout<base+m) @(negedge clk);
                                // rk==6: deterministic cancel-in-flight. Wait
                                // until the output stream is actually presenting
                                // a beat (out_valid high, out_ready may still be
                                // low) and only then cancel, so the cancel mask
                                // is exercised on a live beat EVERY time rather
                                // than depending on a random out_ready. This is
                                // the case that caught the missing !cancel term.
                                if(rk_det) begin
                                    // Bounded: if the stream already drained
                                    // (last beat consumed) out_valid stays low,
                                    // so give up after 64 cycles rather than
                                    // hanging the whole miter.
                                    cw = 0;
                                    while(!out_valid && cw<64) begin @(negedge clk); cw=cw+1; end
                                end
                                cancel=1; idle(1); cancel=0; abort=1;
                            end else begin
                                base=nlast; while(nlast==base) @(negedge clk);
                            end
                        end
                    end
                    idle({$random(s)}%3);
                end
            end
            idle(3);
        end
        idle(20); $fclose(fd); done=1;
    end
endmodule

module tb_mac_out_reg;
    parameter integer SITES=4, SEED=1, NSCEN=150, TIGHT=0;
    reg clk=0; always #5 clk=~clk;
    wire da,db; integer oa,ob,ea,eb,ca,cb;
    mac_driver #(.SITES(SITES),.NEW(0),.SEED(SEED),.NSCEN(NSCEN),.TIGHT(TIGHT)) a(.clk(clk),.done(da),.nout(oa),.nerr(ea),.cycles(ca));
    mac_driver #(.SITES(SITES),.NEW(1),.SEED(SEED),.NSCEN(NSCEN),.TIGHT(TIGHT)) b(.clk(clk),.done(db),.nout(ob),.nerr(eb),.cycles(cb));
    initial begin
        wait(da && db);
        $display("SUMMARY tight=%0d sites=%0d seed=%0d out old=%0d new=%0d err old=%0d new=%0d",
                 TIGHT, SITES, SEED, oa,ob,ea,eb);
        $finish;
    end
    initial begin #400000000; $display("TIMEOUT"); $finish; end
endmodule
