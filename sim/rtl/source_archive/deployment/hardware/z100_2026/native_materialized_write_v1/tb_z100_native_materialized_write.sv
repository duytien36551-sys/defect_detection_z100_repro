`timescale 1ns/1ps
`default_nettype none
module tb_z100_native_materialized_write;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cmd_valid=0,abort=0,recover=0;
    reg [31:0] cmd_epoch=200,cmd_destination_generation=1,cmd_destination_address=32'h10000000,
        cmd_region_begin=32'h10000000,cmd_timeout_cycles=100000;
    reg [32:0] cmd_region_end=33'h100200000;
    reg [10:0] cmd_channels=4;
    reg [9:0] cmd_full_height=2,cmd_width=16,cmd_first_row=0,cmd_height=2;
    reg cmd_destination_reserved=1;
    wire cmd_ready,active,fault,done,tile_committed,order_config,order_config_ready,order_done;
    wire [3:0] fault_code;
    wire [31:0] epoch,destination_generation;wire [10:0] channels;wire [9:0] height,width;
    wire packed_valid,packed_ready,packed_last;wire [31:0] packed_epoch;wire [12:0] packed_index;wire [511:0] packed_data;
    wire writer_command,writer_command_ready,writer_valid,writer_ready,writer_last,writer_done,writer_busy,writer_fault,pipeline_error;
    wire [31:0] writer_address,writer_epoch;wire [13:0] writer_words;wire [12:0] writer_index;wire [511:0] writer_data;
    wire semantic_cancel,writer_cancel,writer_clear_fault;
    z100_native_materialized_write_control control(.*);
    reg iv=0,il=0;reg[31:0] ie=200;reg[12:0] ia=0;reg[511:0] idata=0;
    wire ir,codec_active,codec_error;wire[1:0] codec_code;
    assign pipeline_error=codec_error;
    z100_native_stream_order codec(.clk(clk),.rst_n(rst_n),.cancel(semantic_cancel),
        .cfg_valid(order_config),.cfg_ready(order_config_ready),.cfg_epoch(epoch),.cfg_write_order(1'b1),
        .cfg_channels(channels),.cfg_height(height),.cfg_width(width),
        .in_valid(iv),.in_ready(ir),.in_epoch(ie),.in_index(13'd0),.in_address(ia),.in_last(il),.in_data(idata),
        .out_valid(packed_valid),.out_ready(packed_ready),.out_epoch(packed_epoch),.out_index(packed_index),
        .out_address(),.out_last(packed_last),.out_data(packed_data),.active(codec_active),.done(order_done),.error_valid(codec_error),.error_code(codec_code));
    wire [5:0] awid,wid;wire[31:0] awaddr;wire[3:0] awlen;wire[2:0] awsize;wire[1:0] awburst;
    wire awvalid,wvalid,wlast,bready;wire[63:0] wdata;wire[7:0] wstrb;
    reg[5:0] bid=0;reg[1:0] bresp=0;reg bvalid=0;
    integer cycle=0;reg block_aw=0,block_w=0,block_b=0;
    wire awready=!block_aw&&cycle%7!=0;wire wready=!block_w&&cycle%5!=0;
    wire visible_bvalid=bvalid&&!block_b;
    z100_native_axi64_writer writer(.clk(clk),.rst_n(rst_n),.cmd_valid(writer_command),.cmd_ready(writer_command_ready),
        .cmd_epoch(epoch),.cmd_address(writer_address),.cmd_word_count(writer_words),
        .in_valid(writer_valid),.in_ready(writer_ready),.in_epoch(writer_epoch),.in_index(writer_index),.in_data(writer_data),.in_last(writer_last),
        .cancel(writer_cancel),.timeout(1'b0),.clear_fault(writer_clear_fault),.busy(writer_busy),.done(writer_done),.fault(writer_fault),.fault_code(),
        .m_axi_awid(awid),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),.m_axi_awvalid(awvalid),.m_axi_awready(awready),
        .m_axi_wid(wid),.m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
        .m_axi_bid(bid),.m_axi_bresp(bresp),.m_axi_bvalid(visible_bvalid),.m_axi_bready(bready));
    localparam [31:0] BASE=32'h10000000;
    localparam [63:0] SENTINEL=64'h5a1bc43df609728e;
    reg[63:0] memory[0:262143],expected[0:262143];
    reg aw_owned=0;integer beat=0,beats=0;reg[31:0] address_q=0;
    integer inject_response=0,aws=0,ws=0,bs=0,commands=0,early_commit_checks=0;
    reg awheld=0,wheld=0,bheld=0;reg[40:0] saved_aw;reg[78:0] saved_w;reg[7:0] saved_b;
    always @(posedge clk)begin
        cycle<=cycle+1;
        if(rst_n)begin
            if(awheld&&(!awvalid||{awaddr,awlen,awsize,awburst}!==saved_aw))$fatal(1,"AW changed while held/abort");
            awheld<=awvalid&&!awready;saved_aw<={awaddr,awlen,awsize,awburst};
            if(wheld&&(!wvalid||{wid,wdata,wstrb,wlast}!==saved_w))$fatal(1,"W changed while held/abort");
            wheld<=wvalid&&!wready;saved_w<={wid,wdata,wstrb,wlast};
            if(bheld&&(!visible_bvalid||{bid,bresp}!==saved_b))$fatal(1,"TB B violated hold");
            bheld<=visible_bvalid&&!bready;saved_b<={bid,bresp};
            if(writer_command&&writer_command_ready)commands<=commands+1;
            if(awvalid&&awready)begin
                if(aw_owned||bvalid||awid!=0||awsize!=3||awburst!=1||(awlen!=7&&awlen!=15)||awaddr[5:0]!=0||
                    {1'b0,awaddr[11:0]}+(awlen+1)*8>4096||awaddr<BASE||awaddr-BASE>=2097152)$fatal(1,"Bad write burst");
                aw_owned<=1;address_q<=awaddr;beat<=0;beats<=awlen+1;aws<=aws+1;
            end
            if(wvalid&&wready)begin
                if(!aw_owned||wid!=0||wstrb!=255||wlast!=(beat+1==beats))$fatal(1,"Bad write response ordering");
                memory[((address_q-BASE)>>3)+beat]<=wdata;beat<=beat+1;ws<=ws+1;
                if(wlast)begin aw_owned<=0;bvalid<=1;bid<=inject_response==2 ? 1 : 0;bresp<=inject_response==1 ? 2 : 0;end
            end
            if(visible_bvalid&&bready)begin bvalid<=0;bs<=bs+1;end
            if((aw_owned||bvalid)&&tile_committed)$fatal(1,"Destination published before final B");
            if(aw_owned||bvalid)early_commit_checks<=early_commit_checks+1;
        end
    end
    integer c_q,h_q,w_q,f_q,fh_q,ep_q,xwords,total,successful=0,verified_beats=0,recoveries=0,drain_checks=0;
    function automatic [511:0] payload(input integer c4,input integer y,input integer xword);
        integer ch,x;begin
            payload=0;
            for(ch=0;ch<4;ch=ch+1)for(x=0;x<16;x=x+1)
                if(c4*4+ch<c_q&&xword*16+x<w_q)
                    payload[ch*128+x*8+:8]=(c4*4+ch)*17+(f_q+y)*13+(xword*16+x)*7+ep_q;
        end
    endfunction
    task automatic set_shape(input integer c,input integer fh,input integer w,input integer first,input integer h);
        begin c_q=c;h_q=h;w_q=w;f_q=first;fh_q=fh;ep_q=200;xwords=(w+15)/16;total=((c+3)/4)*h*xwords;
            cmd_channels=c;cmd_full_height=fh;cmd_width=w;cmd_first_row=first;cmd_height=h;cmd_epoch=200;cmd_destination_generation=7;
            cmd_destination_address=BASE;cmd_region_begin=BASE;cmd_region_end={1'b0,BASE}+2097152;
            cmd_destination_reserved=1;cmd_timeout_cycles=1000000;end
    endtask
    task automatic launch;
        begin @(negedge clk);cmd_valid=1;do @(posedge clk);while(!cmd_ready);@(negedge clk);cmd_valid=0;end
    endtask
    task automatic send_word(input integer index,input integer last,input[511:0] data);
        begin @(negedge clk);iv=1;ia=index;ie=200;il=last;idata=data;
            do @(posedge clk);while(!ir&&!fault);@(negedge clk);iv=0;end
    endtask
    task automatic send_all;
        integer cb,y,x,sub,n,groups;begin n=0;
            for(cb=0;cb<c_q;cb=cb+32)begin groups=c_q-cb>=32 ? 8 : (c_q-cb+3)/4;
                for(y=0;y<h_q;y=y+1)for(x=0;x<xwords;x=x+1)for(sub=0;sub<groups;sub=sub+1)begin
                    send_word(((cb/4+sub)*h_q+y)*xwords+x,n+1==total,payload(cb/4+sub,y,x));n=n+1;
                end
            end
        end
    endtask
    task automatic success_case(input integer c,input integer fh,input integer w,input integer first,input integer h);
        integer i,cb,y,x,sub,k,groups,wordaddr,fullwords;reg[511:0] d;begin
            set_shape(c,fh,w,first,h);fullwords=((c+3)/4)*fh*xwords;
            for(i=0;i<fullwords*8;i=i+1)begin memory[i]=SENTINEL;expected[i]=SENTINEL;end
            // Independent native full-tensor scatter oracle with untouched rows.
            for(cb=0;cb<c;cb=cb+32)begin groups=c-cb>=32 ? 8 : (c-cb+3)/4;
                for(y=0;y<h;y=y+1)for(x=0;x<xwords;x=x+1)for(sub=0;sub<groups;sub=sub+1)begin
                    wordaddr=(cb/4)*fh*xwords+(first+y)*xwords*groups+x*groups+sub;d=payload(cb/4+sub,y,x);
                    for(k=0;k<8;k=k+1)expected[wordaddr*8+k]=d[k*64+:64];
                end
            end
            launch();
            // Source command mutation cannot change the accepted reservation.
            cmd_destination_address=32'hfffffff0;cmd_channels=0;cmd_height=0;cmd_destination_generation=0;cmd_region_end=0;
            send_all();do @(negedge clk);while(!done&&!fault);
            if(fault||!tile_committed||writer_busy||codec_active||aw_owned||bvalid||destination_generation!=7||epoch!=200)$fatal(1,"Successful tile failed code=%d",fault_code);
            for(i=0;i<fullwords*8;i=i+1)begin if(memory[i]!==expected[i])$fatal(1,"DDR content/untouched row mismatch shape=%d/%d/%d beat=%d",c,fh,w,i);verified_beats=verified_beats+1;end
            successful=successful+1;
        end
    endtask
    task automatic recovery;
        integer k;begin
            iv=0;abort=0;
            do @(negedge clk);while(writer_busy);
            recover=1;k=0;while(active&&k<30)begin @(negedge clk);k=k+1;end
            recover=0;if(active||fault||writer_fault||tile_committed||writer_busy||codec_active||bvalid||aw_owned)$fatal(1,"Recovery did not revoke reservation");
            recoveries=recoveries+1;
        end
    endtask
    integer j,k,old_aw,old_cmd;
    initial begin
        repeat(5)@(negedge clk);rst_n=1;
        success_case(4,1,1,0,1);success_case(3,7,17,2,2);success_case(9,9,31,3,3);success_case(36,11,33,4,3);
        success_case(128,32,20,3,20);success_case(512,64,32,16,16);success_case(1024,3,16,1,1);success_case(3,640,640,638,2);
        // Malformed reservations/geometries cannot issue AW or codec config.
        old_aw=aws;old_cmd=commands;
        for(j=0;j<10;j=j+1)begin
            set_shape(4,2,16,0,2);
            case(j)0:cmd_epoch=0;1:cmd_destination_generation=0;2:cmd_destination_reserved=0;3:cmd_destination_address=BASE+1;
                4:cmd_region_end={1'b0,BASE}+64;5:cmd_first_row=1;6:cmd_channels=0;7:cmd_width=641;8:cmd_timeout_cycles=0;
                9:begin cmd_destination_address=32'hffffffc0;cmd_region_begin=32'hffffffc0;cmd_region_end=33'h100000000;end endcase
            launch();if(!fault||tile_committed)$fatal(1,"Bad reservation accepted");recovery();
        end
        if(aws!=old_aw||commands!=old_cmd)$fatal(1,"Bad reservation issued AXI");
        // Cancel with AW, W or B indefinitely blocked; recovery cannot abandon.
        for(j=0;j<3;j=j+1)begin
            set_shape(4,2,16,0,2);block_aw=j==0;block_w=j==1;block_b=j==2;launch();send_all();
            if(j==0)begin do @(negedge clk);while(!awvalid);end
            if(j==1)begin do @(negedge clk);while(!wvalid);end
            if(j==2)begin do @(negedge clk);while(!bvalid);end
            abort=1;@(negedge clk);abort=0;recover=1;
            for(k=0;k<30;k=k+1)begin @(negedge clk);
                if(!writer_busy||cmd_ready||tile_committed||writer_clear_fault||done)$fatal(1,"Outstanding write abandoned");drain_checks=drain_checks+1;end
            recover=0;block_aw=0;block_w=0;block_b=0;recovery();
        end
        // Timer and physical BID/BRESP errors revoke partial destination.
        set_shape(4,2,16,0,2);cmd_timeout_cycles=100;block_b=1;launch();send_all();do @(negedge clk);while(!fault);
        if(fault_code!=3)$fatal(1,"Timeout classification");block_b=0;recovery();
        for(j=1;j<=2;j=j+1)begin set_shape(4,2,16,0,2);inject_response=j;launch();send_all();
            do @(negedge clk);while(!fault);if(fault_code!=4)$fatal(1,"Physical write error classification");recovery();inject_response=0;end
        // Codec rejects wrong canonical address before private writer input.
        set_shape(4,2,16,0,2);launch();send_word(7,0,0);do @(negedge clk);while(!fault);
        if(fault_code!=5)$fatal(1,"Codec failure classification");recovery();
        success_case(36,11,33,4,3);
        if(successful!=9||recoveries!=17||drain_checks!=90||early_commit_checks==0)$fatal(1,"Coverage incomplete");
        $display("MATERIALIZED_WRITE_PASS successful_tiles=%0d verified_DDR_beats=%0d recoveries=%0d drain_checks=%0d writer_commands=%0d AXI_AW=%0d AXI_W=%0d AXI_B=%0d premature_commit_checks=%0d",successful,verified_beats,recoveries,drain_checks,commands,aws,ws,bs,early_commit_checks);
        $finish;
    end
    initial begin #100000000;$fatal(1,"Writeback watchdog");end
endmodule
`default_nettype wire
