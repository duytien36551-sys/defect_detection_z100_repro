`timescale 1ns/1ps
// Cycle-exact miter: z100_feature_window20_address_shared_v12 (rtl_full_b) vs
// _v13c (rtl_full_c, double-buffered s1). Identical inputs; every output is
// compared every cycle, out_tag/out_mask/out_data only while out_valid.
module tb_fwin_v12_vs_v13c;
    parameter integer SEED=1, CYCLES=20000;
    reg clk=0; always #5 clk=~clk;
    reg rst_n,cancel,cfg_bank,read_bank,cfg_begin,cfg_word_valid,cfg_word_last,cfg_commit,window_valid,window_stride_two,window_y_valid,out_ready;
    reg [31:0] cfg_epoch,cfg_word_epoch,window_epoch,window_tag; reg [10:0] cfg_channels,window_input_width,window_output_remaining;
    reg [9:0] cfg_height,cfg_width; reg [12:0] cfg_word_address; reg [511:0] cfg_data;
    reg [13:0] window_row_address; reg signed [11:0] window_first_x; reg [4:0] window_sites; reg [3:0] window_channel_mask;
`define FW_PORTS(P) .clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_bank(cfg_bank),.read_bank(read_bank),.read_idle(P``ri), \
    .load_owner_valid(P``lov),.load_owner_bank(P``lob),.load_store_valid(P``lsv),.load_loading(P``lld),.load_active_epoch(P``lae), \
    .cfg_begin(cfg_begin),.cfg_begin_ready(P``br),.cfg_epoch(cfg_epoch),.cfg_canonical_order(1'b1),.cfg_channels(cfg_channels), \
    .cfg_height(cfg_height),.cfg_width(cfg_width),.cfg_word_epoch(cfg_word_epoch),.cfg_word_address(cfg_word_address), \
    .cfg_word_last(cfg_word_last),.cfg_word_valid(cfg_word_valid),.cfg_word_ready(P``wr),.cfg_data(cfg_data), \
    .cfg_commit(cfg_commit),.cfg_commit_ready(P``cr),.store_valid(P``sv),.loading(P``ld),.active_epoch(P``ae), \
    .error_valid(P``ev),.error_code(P``ec),.window_valid(window_valid),.window_ready(P``wnr),.window_epoch(window_epoch), \
    .window_tag(window_tag),.window_row_address(window_row_address),.window_first_x(window_first_x), \
    .window_input_width(window_input_width),.window_output_remaining(window_output_remaining),.window_sites(window_sites), \
    .window_channel_mask(window_channel_mask),.window_stride_two(window_stride_two),.window_y_valid(window_y_valid), \
    .out_valid(P``ov),.out_ready(out_ready),.out_tag(P``ot),.out_mask(P``om),.out_data(P``od)
    wire a_ri,a_lov,a_lob,a_lsv,a_lld,a_br,a_wr,a_cr,a_sv,a_ld,a_ev,a_wnr,a_ov; wire [31:0] a_lae,a_ae,a_ot; wire [3:0] a_ec; wire [79:0] a_om; wire [639:0] a_od;
    wire b_ri,b_lov,b_lob,b_lsv,b_lld,b_br,b_wr,b_cr,b_sv,b_ld,b_ev,b_wnr,b_ov; wire [31:0] b_lae,b_ae,b_ot; wire [3:0] b_ec; wire [79:0] b_om; wire [639:0] b_od;
    z100_feature_window20_address_shared_v12  ref_dut(`FW_PORTS(a_));
    z100_feature_window20_address_shared_v13c new_dut(`FW_PORTS(b_));
    wire [12:0] sa={a_ri,a_lov,a_lob,a_lsv,a_lld,a_br,a_wr,a_cr,a_sv,a_ld,a_ev,a_wnr,a_ov};
    wire [12:0] sb={b_ri,b_lov,b_lob,b_lsv,b_lld,b_br,b_wr,b_cr,b_sv,b_ld,b_ev,b_wnr,b_ov};
    integer s,cyc,fails,n_out,n_err,n_win,k,phase,wi,words,bank_loaded;
    reg f_begin,f_word,f_commit,f_win,f_err; reg [31:0] ep;
    always @(posedge clk) begin
        f_begin<=cfg_begin&&a_br; f_word<=cfg_word_valid&&a_wr; f_commit<=cfg_commit&&a_cr; f_win<=window_valid&&a_wnr; f_err<=a_ev;
        if(sa!==sb || a_lae!==b_lae || a_ae!==b_ae || (a_ev && a_ec!==b_ec) || (a_ov && (a_ot!==b_ot || a_om!==b_om || a_od!==b_od))) begin
            fails=fails+1; if(fails<10) $display("MISMATCH t=%0t sig %b/%b ec %0d/%0d", $time, sa, sb, a_ec, b_ec);
        end
        if(a_ov&&out_ready) n_out=n_out+1;
        if(a_ev) begin n_err=n_err+1; end
        if(window_valid&&a_wnr) n_win=n_win+1;
    end
    task rand_window; begin
        window_epoch=(({$random(s)}%80)==0) ? ep+7 : ep; window_tag={$random(s)}%25;
        window_row_address=(({$random(s)}%50)==0) ? words+1 : {$random(s)}%(words>1 ? words-1 : 1); window_first_x=$signed({$random(s)}%8)-2;
        window_input_width=cfg_width; window_sites=1+{$random(s)}%20; window_output_remaining=window_sites+{$random(s)}%3;
        case({$random(s)}%4) 0: window_channel_mask=1; 1: window_channel_mask=3; 2: window_channel_mask=7; default: window_channel_mask=15; endcase
        if(({$random(s)}%100)==0) window_channel_mask=4'b0101; // illegal descriptor
        window_stride_two=({$random(s)}%4)==0; window_y_valid=({$random(s)}%6)!=0;
    end endtask
    initial begin
        s=SEED; fails=0; n_out=0; n_err=0; n_win=0; phase=0; ep=1; wi=0; words=1; bank_loaded=0;
        rst_n=0; cancel=0; cfg_bank=0; read_bank=0; cfg_begin=0; cfg_word_valid=0; cfg_word_last=0; cfg_commit=0; window_valid=0; out_ready=1;
        cfg_epoch=0; cfg_word_epoch=0; cfg_channels=4; cfg_height=1; cfg_width=16; cfg_word_address=0; cfg_data=0;
        window_epoch=0; window_tag=0; window_row_address=0; window_first_x=0; window_input_width=16; window_output_remaining=1;
        window_sites=1; window_channel_mask=1; window_stride_two=0; window_y_valid=1;
        repeat(4) @(negedge clk); rst_n=1;
        for(cyc=0;cyc<CYCLES;cyc=cyc+1) begin
            @(negedge clk);
            out_ready=({$random(s)}%3)!=0;
            cancel=f_err || (({$random(s)}%4000)==0); if(cancel) begin phase=0; window_valid=0; end
            case(phase)
            0: begin window_valid=0; cfg_word_valid=0; cfg_commit=0; ep=ep+1;
                cfg_bank={$random(s)}%2; cfg_epoch=ep; cfg_channels=4*(1+{$random(s)}%2); cfg_height=1+{$random(s)}%3;
                cfg_width=16*(1+{$random(s)}%2); words=(cfg_channels/4)*cfg_height*(cfg_width/16); wi=0; cfg_begin=1; phase=1; end
            1: if(f_begin) begin cfg_begin=0; phase=2; end else if(({$random(s)}%60)==0) begin cfg_begin=0; phase=0; end
            2: begin cfg_word_valid=1; cfg_word_address=wi; cfg_word_epoch=ep; cfg_word_last=(wi==words-1);
                for(k=0;k<16;k=k+1) cfg_data[k*32+:32]=$random(s); phase=3; end
            3: if(f_word) begin cfg_word_valid=0; wi=wi+1; if(wi>=words) begin cfg_commit=1; phase=4; end else phase=2; end
               else if(!a_lld && !a_lov) begin cfg_word_valid=0; phase=0; end
            4: if(f_commit) begin cfg_commit=0; read_bank=cfg_bank; phase=5; end else if(!a_lov) begin cfg_commit=0; phase=0; end
            5: begin
                if(!a_sv && !window_valid) phase=0;
                else if(!window_valid || f_win) begin
                    if(({$random(s)}%1500)==0) begin window_valid=0; phase=0; end
                    else begin window_valid=({$random(s)}%5)!=0; rand_window; end
                end
            end
            endcase
        end
        $display("FWIN_MITER seed=%0d cycles=%0d windows=%0d outputs=%0d errors=%0d mismatches=%0d", SEED, CYCLES, n_win, n_out, n_err, fails);
        $finish;
    end
endmodule
