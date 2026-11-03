`timescale 1ns/1ps
`include "fixture_defs.vh"
module tb_z100_maxpool_pack;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cancel=0;
    reg iv=0,ifirst=0,ilast=0;
    wire ir,mv,mr,ma,me;
    reg [31:0] ie=200,it=1;reg [6:0] ilanes=80;
    reg [79:0] imask=0;reg [639:0] idata=0;
    wire [31:0] m_epoch,m_token;wire [6:0] m_lanes;wire [639:0] m_data;
    z100_maxpool_vector pool(.clk(clk),.rst_n(rst_n),.cancel(cancel),.in_valid(iv),.in_ready(ir),
        .in_epoch(ie),.in_token(it),.in_lanes(ilanes),.in_first(ifirst),.in_last(ilast),
        .in_mask(imask),.in_data(idata),.out_valid(mv),.out_ready(mr),.out_epoch(m_epoch),
        .out_token(m_token),.out_lanes(m_lanes),.out_data(m_data),.error_valid(me),.active(ma));
    reg cv=0;wire cr,ca,ce,cd,pv,pr,plast;
    reg [31:0] cfg_epoch=200,cfg_input_token_base=1,cfg_output_token=1;
    reg [5:0] cfg_lanes=32;
    wire [31:0] pe,pt;wire [4:0] ps;wire [5:0] pl;wire [255:0] pd;
    z100_maxpool_collect32 collect(.clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_valid(cv),.cfg_ready(cr),
        .cfg_epoch(cfg_epoch),.cfg_input_token_base(cfg_input_token_base),.cfg_output_token(cfg_output_token),.cfg_lanes(cfg_lanes),
        .in_valid(mv),.in_ready(mr),.in_epoch(m_epoch),.in_token(m_token),.in_lanes(m_lanes),.in_data(m_data),
        .out_valid(pv),.out_ready(pr),.out_epoch(pe),.out_token(pt),.out_site(ps),.out_lanes(pl),
        .out_last(plast),.out_data(pd),.done(cd),.error_valid(ce),.active(ca));
    reg pcv=0;wire pcr,ov,olast,pdone,perr,pa;reg ordy=0;
    reg [10:0] channels=128;reg [9:0] height=20;
    wire [31:0] oe;wire [12:0] oa;wire [511:0] od;wire [2:0] pec;
    z100_native_output_packer #(.SITES(20)) pack(.clk(clk),.rst_n(rst_n),.cancel(cancel),
        .cfg_valid(pcv),.cfg_ready(pcr),.cfg_epoch(cfg_epoch),.cfg_channels(channels),.cfg_height(height),
        .cfg_width(10'd20),.cfg_token_base(32'd1),.in_valid(pv),.in_ready(pr),.in_epoch(pe),.in_token(pt),
        .in_site(ps),.in_lanes(pl),.in_last(plast),.in_data(pd),.out_valid(ov),.out_ready(ordy),
        .out_epoch(oe),.out_address(oa),.out_data(od),.out_last(olast),.done(pdone),
        .error_valid(perr),.error_code(pec),.active(pa));
    reg [719:0] taps[0:`TAPS-1];
    reg [511:0] gold[0:`WORDS-1];reg [12:0] addresses[0:`WORDS-1];
    reg [127:0] cases[0:`CASES-1];
    integer cyc=0,words=0,case_words=0,case_goal=0,case_epoch=0;
    integer done_count=0,blocks=0,postbeats=0,tapbeats=0,packholds=0,postholds=0;
    reg heldpack=0,heldpost=0;reg [511:0] packdata;reg [12:0] packaddr;
    reg [255:0] postdata;reg [31:0] posttoken;reg [4:0] postsite;
    always @(negedge clk)ordy=rst_n&&(cyc>1500)&&((cyc%41)>10);
    always @(posedge clk)begin
        cyc=cyc+1;
        if(rst_n&&!cancel)begin
            if(me||ce||perr)$fatal(1,"pipeline error pool=%0d collect=%0d pack=%0d/%0d",me,ce,perr,pec);
            if(heldpack && (!ov||od!==packdata||oa!==packaddr))$fatal(1,"packed output changed under stall");
            if(heldpost && (!pv||pd!==postdata||pt!==posttoken||ps!==postsite))$fatal(1,"collector output changed under stall");
            heldpack=ov&&!ordy;heldpost=pv&&!pr;
            if(heldpack)begin packholds=packholds+1;packdata=od;packaddr=oa;end
            if(heldpost)begin postholds=postholds+1;postdata=pd;posttoken=pt;postsite=ps;end
            if(ov&&ordy)begin
                if(words>=`WORDS||od!==gold[words]||oa!==addresses[words]||oe!=case_epoch||olast!==(case_words==case_goal-1))
                    $fatal(1,"packed mismatch index=%0d address=%0d expected=%0d",words,oa,addresses[words]);
                words=words+1;case_words=case_words+1;
            end
            if(pdone)done_count=done_count+1;
            if(cd)blocks=blocks+1;
            if(pv&&pr)postbeats=postbeats+1;
            if(iv&&ir)tapbeats=tapbeats+1;
        end
        if(cyc>1000000)$fatal(1,"timeout");
    end
    task tick;begin @(posedge clk);#1;end endtask
    integer c,b,sg,t,ng,nlanes,vector_cursor=0,block_count,vector_count;
    initial begin
        $readmemh("taps.hex",taps);$readmemh("golden.hex",gold);$readmemh("addresses.hex",addresses);$readmemh("cases.hex",cases);
        repeat(5)tick();@(negedge clk);rst_n=1;tick();
        for(c=0;c<`CASES;c=c+1)begin
            channels=cases[c][10:0];height=cases[c][20:11];block_count=cases[c][36:21];
            case_goal=cases[c][52:37];case_words=0;case_epoch=200+c;cfg_epoch=case_epoch;
            while(!pcr)tick();@(negedge clk);pcv=1;tick();@(negedge clk);pcv=0;
            for(b=0;b<block_count;b=b+1)begin
                nlanes=channels-(b/height)*32;if(nlanes>32)nlanes=32;ng=(nlanes+3)/4;
                while(!cr)tick();@(negedge clk);cfg_lanes=nlanes;cfg_input_token_base=b*8+1;cfg_output_token=b+1;cv=1;
                tick();@(negedge clk);cv=0;
                for(sg=0;sg<ng;sg=sg+1)begin
                    ilanes=((nlanes-sg*4)>=4)?80:(nlanes-sg*4)*20;it=b*8+sg+1;ie=case_epoch;
                    for(t=0;t<25;t=t+1)begin
                        if((t+b)%7==0)tick();
                        @(negedge clk);idata=taps[vector_cursor*25+t][639:0];imask=taps[vector_cursor*25+t][719:640];
                        ifirst=t==0;ilast=t==24;iv=1;#1;
                        while(!ir)begin tick();@(negedge clk);#1;end
                        tick();@(negedge clk);iv=0;
                    end
                    vector_cursor=vector_cursor+1;
                end
            end
            while(done_count<c+1)tick();
            if(case_words!=case_goal)$fatal(1,"case output word count");
        end
        if(words!=`WORDS||blocks!=`BLOCKS||postbeats!=`BLOCKS*20||tapbeats!=`TAPS||packholds==0||postholds==0)
            $fatal(1,"coverage words=%0d blocks=%0d post=%0d taps=%0d stalls=%0d/%0d",words,blocks,postbeats,tapbeats,packholds,postholds);
        $display("MAXPOOL_PACK_PASS cases=%0d vectors=%0d taps=%0d post_beats=%0d packed_words=%0d valid_bytes=%0d pack_stalls=%0d post_stalls=%0d done=%0d",`CASES,`VECTORS,tapbeats,postbeats,words,`VALID_BYTES,packholds,postholds,done_count);
        $finish;
    end
endmodule
