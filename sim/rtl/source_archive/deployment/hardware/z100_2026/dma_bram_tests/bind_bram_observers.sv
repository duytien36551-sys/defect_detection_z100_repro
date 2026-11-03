// Bind only the two independently inventoried data-FIFO configurations.
// Acceptance additionally requires the exact MM2S/S2MM I_DATA_FIFO paths.
bind xpm_memory_base bram_collision_observer #(
    .SELECTED(MEMORY_TYPE==1 && MEMORY_PRIMITIVE==2 && CLOCKING_MODE==0 &&
              ADDR_WIDTH_A==7 && ADDR_WIDTH_B==7 && WRITE_DATA_WIDTH_A==READ_DATA_WIDTH_B &&
              WAKEUP_TIME==0 && ECC_MODE==0 && BYTE_WRITE_WIDTH_A==WRITE_DATA_WIDTH_A &&
              WRITE_MODE_A==2 && WRITE_MODE_B==2 && READ_LATENCY_B==2 &&
              ((WRITE_DATA_WIDTH_A==39 && MEMORY_SIZE==4992) ||
               (WRITE_DATA_WIDTH_A==38 && MEMORY_SIZE==4864))),
    .WIDTH(WRITE_DATA_WIDTH_A), .AW(ADDR_WIDTH_A), .INIT_SKIP(64)
) collision_observer (
    .clk(clka), .ena(ena), .wea(wea[0]), .enb(enb),
    .rsta(rsta), .rstb(rstb), .addra(addra), .addrb(addrb)
);
