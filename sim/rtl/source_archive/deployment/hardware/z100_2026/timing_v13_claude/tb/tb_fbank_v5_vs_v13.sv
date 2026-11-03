`timescale 1ns/1ps
// Cycle-exact miter: z100_feature_banks_4read_writepipe_4k_v5 vs _v13 driven by
// identical inputs. Every output is compared every cycle; out_data only when
// out_valid (the documented contract). Stimulus loads small stores, then issues
// good/bad-address/bad-epoch reads with random backpressure, cancels, illegal
// multi-class inputs and protocol errors.
module tb_fbank_v5_vs_v13;
    parameter integer SEED=1, CYCLES=40000;
    reg clk=0; always #5 clk=~clk;
    reg rst_n, cancel, cfg_begin, cfg_canon, cfg_word_valid, cfg_word_last, cfg_commit, req_valid, out_ready;
    reg [31:0] cfg_epoch, cfg_word_epoch, req_epoch; reg [10:0] cfg_channels; reg [9:0] cfg_height, cfg_width;
    reg [511:0] cfg_word_data; reg [12:0] cfg_word_address; reg [64*4*13-1:0] req_addresses; reg [255:0] req_mask;
    wire [12:0] o0, o1;
    wire [3:0] ec0, ec1; wire [31:0] ae0, ae1, oe0, oe1; wire [2047:0] od0, od1;
    wire br0,wr0,cr0,ev0,sv0,ld0,rr0,ov0, br1,wr1,cr1,ev1,sv1,ld1,rr1,ov1;
`define FB_PORTS(br,wr,cr,ev,ec,sv,ae,ld,rr,ov,oe,od) .clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_begin(cfg_begin),.cfg_begin_ready(br), \
    .cfg_epoch(cfg_epoch),.cfg_canonical_order(cfg_canon),.cfg_channels(cfg_channels),.cfg_height(cfg_height),.cfg_width(cfg_width), \
    .cfg_word_valid(cfg_word_valid),.cfg_word_ready(wr),.cfg_word_data(cfg_word_data),.cfg_word_epoch(cfg_word_epoch), \
    .cfg_word_address(cfg_word_address),.cfg_word_last(cfg_word_last),.cfg_commit(cfg_commit),.cfg_commit_ready(cr), \
    .error_valid(ev),.error_code(ec),.store_valid(sv),.active_epoch(ae),.loading(ld),.req_valid(req_valid),.req_ready(rr), \
    .req_epoch(req_epoch),.req_addresses(req_addresses),.req_mask(req_mask),.out_valid(ov),.out_ready(out_ready),.out_epoch(oe),.out_data(od)
    z100_feature_banks_4read_writepipe_4k_v5  ref_dut(`FB_PORTS(br0,wr0,cr0,ev0,ec0,sv0,ae0,ld0,rr0,ov0,oe0,od0));
    z100_feature_banks_4read_writepipe_4k_v13 new_dut(`FB_PORTS(br1,wr1,cr1,ev1,ec1,sv1,ae1,ld1,rr1,ov1,oe1,od1));

    wire [9:0] sig0={br0,wr0,cr0,ev0,sv0,ld0,rr0,ov0,2'b0};
    wire [9:0] sig1={br1,wr1,cr1,ev1,sv1,ld1,rr1,ov1,2'b0};
    integer s, cyc, fails, n_out, n_err, n_badread, words, wi, k, phase, hold;
    reg [31:0] ep;
    integer errhist[0:15]; initial for(k=0;k<16;k=k+1) errhist[k]=0;
    reg f_begin, f_word, f_commit, f_req;
    always @(posedge clk) begin
        f_begin<=cfg_begin&&br0; f_word<=cfg_word_valid&&wr0; f_commit<=cfg_commit&&cr0; f_req<=req_valid&&rr0;
    end
    always @(posedge clk) begin
        if(sig0!==sig1 || (ev0 && ec0!==ec1) || ae0!==ae1 || (ov0 && (oe0!==oe1 || od0!==od1))) begin
            fails=fails+1;
            if(fails<10) $display("MISMATCH t=%0t sig %b/%b ec %0d/%0d ae %h/%h", $time, sig0, sig1, ec0, ec1, ae0, ae1);
        end
        if(ov0 && out_ready) n_out=n_out+1;
        if(ev0) begin n_err=n_err+1; errhist[ec0]=errhist[ec0]+1;  if(ec0==7) n_badread=n_badread+1; end
    end
    task rand_req; integer p; begin
        for(p=0;p<256;p=p+1) begin
            req_mask[p] = ({$random(s)}%4)!=0;
            req_addresses[p*13+:13] = {$random(s)}%(words>0?words:1);
        end
        if(({$random(s)}%40)==0) begin p={$random(s)}%256; req_addresses[p*13+:13]=words+({$random(s)}%3); end
        req_epoch = (({$random(s)}%60)==0) ? ep+1 : ep;
    end endtask
    initial begin
        s=SEED; fails=0; n_out=0; n_err=0; n_badread=0; phase=0; hold=0; wi=0; words=0; ep=1;
        rst_n=0; cancel=0; cfg_begin=0; cfg_canon=1; cfg_word_valid=0; cfg_word_last=0; cfg_commit=0; req_valid=0; out_ready=1;
        cfg_epoch=0; cfg_word_epoch=0; req_epoch=0; cfg_channels=8; cfg_height=2; cfg_width=32;
        cfg_word_data=0; cfg_word_address=0; req_addresses=0; req_mask=0;
        repeat(4) @(negedge clk); rst_n=1;
        for(cyc=0;cyc<CYCLES;cyc=cyc+1) begin
            @(negedge clk);
            out_ready = ({$random(s)}%3)!=0;
            cancel = (({$random(s)}%3000)==0);
            if(cancel) phase=0;
            case(phase)
            0: begin // begin a new store
                req_valid=0; cfg_word_valid=0; cfg_commit=0;
                ep=ep+1; cfg_epoch=(({$random(s)}%40)==0) ? 0 : ep;
                cfg_channels=4*(1+{$random(s)}%3); cfg_height=1+{$random(s)}%3; cfg_width=16*(1+{$random(s)}%2);
                words=(cfg_channels/4)*cfg_height*(cfg_width/16); wi=0;
                cfg_begin=1; phase=1;
            end
            1: if(f_begin) begin cfg_begin=0; phase=2; end else if(({$random(s)}%50)==0) begin cfg_begin=0; phase=0; end
            2: begin // stream words
                cfg_word_valid=1; cfg_word_address=wi; cfg_word_epoch=ep;
                cfg_word_last=(wi==words-1);
                for(k=0;k<16;k=k+1) cfg_word_data[k*32+:32]=$random(s);
                if(({$random(s)}%150)==0) cfg_word_address=wi+1;  // order error
                phase=3;
            end
            3: if(f_word) begin
                cfg_word_valid=0; wi=wi+1;
                if(({$random(s)}%100)==0) begin cfg_commit=1; phase=4; end // early commit
                else if(wi>=words) begin cfg_commit=1; phase=4; end
                else phase=2;
               end else if(!ld0) begin cfg_word_valid=0; phase=0; end
            4: if(f_commit) begin cfg_commit=0; phase=5; end else if(!ld0) begin cfg_commit=0; phase=0; end
            5: begin // reads
                cfg_commit=0; cfg_word_valid=0;
                if(!sv0 && !req_valid) phase=0;
                else if(!req_valid || f_req) begin
                    if(({$random(s)}%2000)==0) begin req_valid=0; phase=0; end
                    else begin req_valid=({$random(s)}%4)!=0; rand_req; end
                    // occasionally present an illegal second command class
                    cfg_word_valid=(({$random(s)}%500)==0);
                end
            end
            endcase
        end
        for(k=1;k<9;k=k+1) $display("  error code %0d: %0d", k, errhist[k]);
        $display("FBANK_MITER seed=%0d cycles=%0d outputs=%0d errors=%0d badread=%0d mismatches=%0d", SEED, CYCLES, n_out, n_err, n_badread, fails);
        $finish;
    end
endmodule
