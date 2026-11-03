#ifndef Z100_NATIVE_PLATFORM_MMIO_XILINX_V1_H
#define Z100_NATIVE_PLATFORM_MMIO_XILINX_V1_H

#include "native_conv_driver_v2.h"

#define ZN_NPMMIO_V1_BASE UINT32_C(0x43C20000)
#define ZN_NPMMIO_V1_BYTES UINT32_C(0x1000)

/* Host hooks model absolute-address IO only. BSP mode rejects all hooks.
 * This context and its mapping must remain unchanged while a driver owns it.
 * A matching native XSA and Device-memory mapping are platform prerequisites;
 * constructing these callbacks neither programs the PL nor installs an MMU map. */
typedef struct ZnNativePlatformMmioXilinxContextV1 {
    uint32_t base;
    uint32_t bytes;
    void *host_context;
    int (*host_read32)(void *context, uint32_t address, uint32_t *value);
    int (*host_write32)(void *context, uint32_t address, uint32_t value);
    int (*host_barrier)(void *context);
} ZnNativePlatformMmioXilinxContextV1;

/* Explicit build mode: ZN_NPMMIO_V1_USE_XILINX_BSP or
 * ZN_NPMMIO_V1_HOST_MODEL. Invalid configuration leaves ops unchanged. */
int zn_native_platform_mmio_xilinx_ops_v1(
    ZnNativeConvMmioOpsV2 *ops,
    ZnNativePlatformMmioXilinxContextV1 *context);

#endif
