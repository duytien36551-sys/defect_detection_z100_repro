`timescale 1ns/1ps
// Transaction-level equivalence: z100_native_output_packer vs _v13.
// Independent drivers with identical seeds; every output beat, error and done
// is logged and the logs must be identical (v13 may accept cfg later).
`define PK_PORTS .clk(clk),.rst_n(rst_n),.cancel(cancel),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready), \
    .cfg_epoch(cfg_epoch),.cfg_channels(cfg_channels),.cfg_height(cfg_height),.cfg_width(cfg_width),.cfg_token_base(cfg_token_base), \
    .in_valid(in_valid),.in_ready(in_ready),.in_epoch(in_epoch),.in_token(in_token),.in_site(in_site),.in_lanes(in_lanes), \
    .in_last(in_last),.in_data(in_data),.out_valid(out_valid),.out_ready(out_ready),.out_epoch(out_epoch),.out_address(out_address), \
    .out_data(out_data),.out_last(out_last),.done(done),.error_valid(error_valid),.error_code(error_code),.active(active)
module pk_driver #(parameter integer V13=0, SEED=1, NJOB=150) (input wire clk, output reg fin, output integer nout);
    reg rst_n, cancel, cfg_valid, in_valid, in_last, out_ready;
    reg [31:0] cfg_epoch, cfg_token_base, in_epoch, in_token; reg [10:0] cfg_channels; reg [9:0] cfg_height, cfg_width;
    reg [4:0] in_site; reg [5:0] in_lanes; reg [255:0] in_data;
    wire cfg_ready, in_ready, out_valid, out_last, done, error_valid, active;
    wire [31:0] out_epoch; wire [12:0] out_address; wire [511:0] out_data; wire [2:0] error_code;
    generate if(V13) begin : g13 z100_native_output_packer_v13 #(.SITES(20)) dut(`PK_PORTS);
             end else begin : g12 z100_native_output_packer #(.SITES(20)) dut(`PK_PORTS); end endgenerate
    integer fd, s, rs, j, g, r, x, k, run, kind, bad_at, beat, ndone, nerr, base;
    reg failed; integer C,H,W,grp,row,xx,site,ns; reg [31:0] ep, base_tok, tok;
    initial begin if(V13) fd=$fopen("pk_v13.txt","w"); else fd=$fopen("pk_v12.txt","w"); nout=0; ndone=0; nerr=0; rs=SEED*13+5; end
    always @(posedge clk) begin
        if(out_valid && out_ready) begin $fdisplay(fd,"OUT %h %h %0d %h",out_epoch,out_address,out_last,out_data); nout=nout+1; end
        if(error_valid) begin $fdisplay(fd,"ERR %0d",error_code); nerr=nerr+1; end
        if(done) begin $fdisplay(fd,"DONE"); ndone=ndone+1; end
    end
    always @(negedge clk) out_ready <= ({$random(rs)}%3)!=0;
    task idle(input integer n); integer q; begin for(q=0;q<n;q=q+1) @(negedge clk); end endtask
    initial begin
        s=SEED; fin=0; rst_n=0; cancel=0; cfg_valid=0; in_valid=0; in_last=0;
        cfg_epoch=0; cfg_token_base=0; in_epoch=0; in_token=0; cfg_channels=0; cfg_height=0; cfg_width=0;
        in_site=0; in_lanes=0; in_data=0;
        idle(4); rst_n=1; idle(2);
        for(j=0;j<NJOB;j=j+1) begin
            kind={$random(s)}%10;   // 0: bad geometry  1: bad input beat  2: cancel mid-job
            cfg_epoch=1+{$random(s)}%999; cfg_token_base=1+{$random(s)}%5000; ep=cfg_epoch; base_tok=cfg_token_base;
            cfg_channels=(kind==0) ? 0 : 1+{$random(s)}%128;
            cfg_height=1+{$random(s)}%3;
            case({$random(s)}%5) 0: cfg_width=20; 1: cfg_width=40; 2: cfg_width=7; 3: cfg_width=13; default: cfg_width=33; endcase
            idle({$random(s)}%3);
            C=cfg_channels; H=cfg_height; W=cfg_width;
            $fdisplay(fd,"JOB %0d %0d",j,kind);
            cfg_valid=1; @(posedge clk); while(!cfg_ready) @(posedge clk); @(negedge clk); cfg_valid=0;
            cfg_channels=$random(s); cfg_height=$random(s); cfg_token_base=$random(s); // may change after handshake
            if(kind==0) idle(3);
            else begin
                bad_at={$random(s)}%60; beat=0; failed=0; tok=base_tok;
                for(grp=0; grp<C && !failed; grp=grp+32)
                  for(row=0; row<H && !failed; row=row+1)
                    for(xx=0; xx<W && !failed; xx=xx+ns) begin
                        ns=(W-xx>=20)?20:(W-xx);
                        for(site=0; site<ns && !failed; site=site+1) begin
                            in_epoch=ep; in_token=tok; in_site=site; in_lanes=(C-grp>=32)?32:(C-grp);
                            in_last=(site==ns-1);
                            for(k=0;k<8;k=k+1) in_data[k*32+:32]=$random(s);
                            if(kind==2 && beat==bad_at) begin cancel=1; idle(1); cancel=0; failed=1; end
                            else begin
                                if(kind==1 && beat==bad_at) in_token=tok+1;
                                in_valid=1; @(posedge clk); while(!in_ready) @(posedge clk); @(negedge clk); in_valid=0;
                                if(kind==1 && beat==bad_at) failed=1;
                                beat=beat+1; idle(({$random(s)}%4==0)?1:0);
                            end
                        end
                        tok=tok+1;
                    end
                if(!failed) begin base=ndone; while(ndone==base) @(negedge clk); end
            end
            idle(2);
        end
        idle(30); $fclose(fd); fin=1;
    end
endmodule

module tb_packer_v12_vs_v13;
    parameter integer SEED=1, NJOB=150;
    reg clk=0; always #5 clk=~clk;
    wire f12,f13; integer n12,n13;
    pk_driver #(.V13(0),.SEED(SEED),.NJOB(NJOB)) a(.clk(clk),.fin(f12),.nout(n12));
    pk_driver #(.V13(1),.SEED(SEED),.NJOB(NJOB)) b(.clk(clk),.fin(f13),.nout(n13));
    initial begin wait(f12&&f13); $display("PACKER_SUMMARY seed=%0d out v12=%0d v13=%0d",SEED,n12,n13); $finish; end
    initial begin #50000000; $display("TIMEOUT"); $finish; end
endmodule
