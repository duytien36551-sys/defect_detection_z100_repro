`timescale 1ns/1ps
`default_nettype none
// Authored only. Compile the original Pool wrapper under the _baseline alias,
// the candidate under its original name, and the real vector/collector/packer.
module tb_pool_group_metadata_miter_v1;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,cancel=0,fw_error=0,job_valid=0;
    reg [31:0] job_epoch=1;
    reg [10:0] channels=1;
    reg [9:0] height=1;
    reg out_ready=0;
    wire old_job_ready,new_job_ready;
    wire old_window_valid,new_window_valid;
    wire old_window_out_ready,new_window_out_ready;
    wire [31:0] old_window_epoch,new_window_epoch,old_request_tag,new_request_tag;
    wire [13:0] old_row,new_row;
    wire signed [11:0] old_x,new_x;
    wire [3:0] old_channels,new_channels;
    wire old_y,new_y,old_cancel,new_cancel;
    wire old_out_valid,new_out_valid,old_last,new_last;
    wire [31:0] old_out_epoch,new_out_epoch;
    wire [12:0] old_address,new_address;
    wire [511:0] old_data,new_data;
    wire old_done,new_done,old_error,new_error,old_active,new_active;
    wire [3:0] old_error_code,new_error_code;
    reg response_valid=0;
    reg [31:0] response_tag=0;
    reg [79:0] response_mask=0;
    reg [639:0] response_data=0;
    reg [31:0] rng=32'h19bd30a7;
    wire window_ready=rng[0] && (!response_valid || old_window_out_ready);
    integer cycles=0,requests=0,responses=0,outputs=0,valid_jobs=0;
    integer stalled_outputs=0,aborts=0,faults=0,resets=0,tail_mask_seen=0;
    reg held_valid=0;
    reg [511:0] held_data;
    reg [12:0] held_address;
    reg held_last;
    integer byte_index,wait_count,n;

    z100_maxpool_window20_tapxy_v3_baseline original (
        .clk(clk),.rst_n(rst_n),.cancel(cancel),.store_valid(1'b1),.loading(1'b0),
        .active_epoch(job_epoch),.loaded_channels(channels),.loaded_height(height),.loaded_width(10'd20),
        .fw_error(fw_error),.window_valid(old_window_valid),.window_ready(window_ready),
        .window_epoch(old_window_epoch),.window_request_tag(old_request_tag),
        .window_row_address(old_row),.window_first_x(old_x),.window_channel_mask(old_channels),
        .window_y_valid(old_y),.window_cancel(old_cancel),.window_out_valid(response_valid),
        .window_out_ready(old_window_out_ready),.window_tag(response_tag),.window_mask(response_mask),
        .window_data(response_data),.job_valid(job_valid),.job_ready(old_job_ready),
        .job_epoch(job_epoch),.job_channels(channels),.job_height(height),.job_width(10'd20),
        .out_valid(old_out_valid),.out_ready(out_ready),.out_epoch(old_out_epoch),
        .out_address(old_address),.out_data(old_data),.out_last(old_last),
        .done(old_done),.error_valid(old_error),.error_code(old_error_code),.active(old_active));

    z100_maxpool_window20_tapxy_v3 candidate (
        .clk(clk),.rst_n(rst_n),.cancel(cancel),.store_valid(1'b1),.loading(1'b0),
        .active_epoch(job_epoch),.loaded_channels(channels),.loaded_height(height),.loaded_width(10'd20),
        .fw_error(fw_error),.window_valid(new_window_valid),.window_ready(window_ready),
        .window_epoch(new_window_epoch),.window_request_tag(new_request_tag),
        .window_row_address(new_row),.window_first_x(new_x),.window_channel_mask(new_channels),
        .window_y_valid(new_y),.window_cancel(new_cancel),.window_out_valid(response_valid),
        .window_out_ready(new_window_out_ready),.window_tag(response_tag),.window_mask(response_mask),
        .window_data(response_data),.job_valid(job_valid),.job_ready(new_job_ready),
        .job_epoch(job_epoch),.job_channels(channels),.job_height(height),.job_width(10'd20),
        .out_valid(new_out_valid),.out_ready(out_ready),.out_epoch(new_out_epoch),
        .out_address(new_address),.out_data(new_data),.out_last(new_last),
        .done(new_done),.error_valid(new_error),.error_code(new_error_code),.active(new_active));

    // One response slot, held stable until the real Pool consumer accepts it.
    always @(posedge clk) begin
        cycles=cycles+1;
        if (!rst_n || cancel || old_cancel) begin
            response_valid<=0;
        end else begin
            if (response_valid && old_window_out_ready) begin
                response_valid<=0;
                responses=responses+1;
            end
            if (old_window_valid && window_ready) begin
                requests=requests+1;
                response_valid<=1;
                response_tag<=old_request_tag;
                for(byte_index=0;byte_index<80;byte_index=byte_index+1) begin
                    response_data[byte_index*8+:8] <=
                        (requests*13+byte_index*7+old_request_tag*3) & 255;
                    response_mask[byte_index] <= old_channels[byte_index/20] && old_y;
                end
            end
        end
        if (rst_n && !cancel) begin
            if ({old_job_ready,old_window_valid,old_window_out_ready,old_out_valid,old_cancel,
                 old_done,old_error,old_error_code,old_active} !==
                {new_job_ready,new_window_valid,new_window_out_ready,new_out_valid,new_cancel,
                 new_done,new_error,new_error_code,new_active})
                $fatal(1,"Public control mismatch cycle %0d",cycles);
            if (old_window_valid &&
                {old_window_epoch,old_request_tag,old_row,old_x,old_channels,old_y} !==
                {new_window_epoch,new_request_tag,new_row,new_x,new_channels,new_y})
                $fatal(1,"Valid window metadata mismatch cycle %0d",cycles);
            if (old_window_valid) begin
                case(old_channels)
                    4'h1:tail_mask_seen=tail_mask_seen|1;
                    4'h3:tail_mask_seen=tail_mask_seen|2;
                    4'h7:tail_mask_seen=tail_mask_seen|4;
                    4'hf:tail_mask_seen=tail_mask_seen|8;
                    default:$fatal(1,"Invalid mask on valid request");
                endcase
            end
            if (old_out_valid && {old_out_epoch,old_address,old_data,old_last} !==
                                  {new_out_epoch,new_address,new_data,new_last})
                $fatal(1,"Valid packed output mismatch cycle %0d",cycles);
            if (held_valid && !fw_error) begin
                if (!old_out_valid || {old_data,old_address,old_last} !==
                                     {held_data,held_address,held_last})
                    $fatal(1,"Output changed while stalled");
                stalled_outputs=stalled_outputs+1;
            end
            if(old_out_valid && out_ready) outputs=outputs+1;
            if(old_done) valid_jobs=valid_jobs+1;
            held_valid=old_out_valid && !out_ready && !fw_error;
            held_data=old_data;held_address=old_address;held_last=old_last;
        end else held_valid=0;
    end

    always @(negedge clk) begin
        rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
        out_ready<=rng[2] || rng[7];
    end

    task automatic launch(input integer count,input integer rows);
        begin
            @(negedge clk);channels=count;height=rows;job_epoch=job_epoch+1;job_valid=1;
            wait_count=0;
            @(posedge clk);
            while(!old_job_ready && wait_count<100) begin
                wait_count=wait_count+1;@(posedge clk);
            end
            if(!old_job_ready) $fatal(1,"Job admission timeout");
            @(negedge clk);job_valid=0;
        end
    endtask

    task automatic finish_job;
        begin
            wait_count=0;
            @(negedge clk);
            while(!old_done && wait_count<100000) begin
                wait_count=wait_count+1;@(negedge clk);
            end
            if(!old_done || old_error) $fatal(1,"Job completion timeout/error");
            @(negedge clk);
        end
    endtask

    initial begin
        repeat(4) @(negedge clk);
        rst_n=1;
        for(n=1;n<=128;n=n+1) begin launch(n,1);finish_job();end
        launch(33,2);finish_job();
        launch(127,20);finish_job();
        // Cancel with real outstanding work, followed by a new epoch/job.
        launch(31,2);
        repeat(12) @(negedge clk);
        cancel=1;aborts=aborts+1;repeat(2) @(negedge clk);cancel=0;
        launch(7,1);finish_job();
        // Fault must hold ownership until explicit cancel/reset recovery.
        launch(65,2);repeat(12) @(negedge clk);fw_error=1;
        repeat(2) @(negedge clk);fw_error=0;faults=faults+1;
        repeat(3) @(negedge clk);
        if(old_job_ready || new_job_ready) $fatal(1,"Fault released ownership without cancel");
        cancel=1;repeat(2) @(negedge clk);cancel=0;
        launch(9,1);finish_job();
        launch(66,2);repeat(12) @(negedge clk);rst_n=0;resets=resets+1;
        repeat(2) @(negedge clk);rst_n=1;
        launch(11,1);finish_job();
        repeat(3) @(negedge clk);
        if(valid_jobs!=133 || tail_mask_seen!=15 || stalled_outputs==0 || requests==0 || responses==0)
            $fatal(1,"Insufficient miter coverage jobs=%0d masks=%0d stalls=%0d",valid_jobs,tail_mask_seen,stalled_outputs);
        $display("POOL_GROUP_METADATA_MITER_PASS jobs=%0d requests=%0d responses=%0d packed_words=%0d stalled_outputs=%0d tail_masks=%0d cancel_cases=%0d fault_cases=%0d reset_cases=%0d",
                 valid_jobs,requests,responses,outputs,stalled_outputs,tail_mask_seen,aborts,faults,resets);
        $finish;
    end
    initial begin #50000000; $fatal(1,"Miter watchdog"); end
endmodule
`default_nettype wire
