#ifndef Z100_NATIVE_PLATFORM_CACHE_XILINX_V1_H
#define Z100_NATIVE_PLATFORM_CACHE_XILINX_V1_H

#include "native_platform_memory_v1.h"

/*
 * The reservation policy belongs to the platform owner (Linux CMA, a
 * bare-metal linker reservation, or a test fixture).  This adapter keeps that
 * policy outside the cache implementation while supplying the copy/order
 * operations required by native_platform_memory_v1.
 */
typedef int (*ZnNativePlatformCacheReserveV1)(
    void *context,
    const ZnNativePlatformReservationV1 *range);

typedef struct {
    ZnNativePlatformCacheReserveV1 reserve;
    void *reserve_context;
} ZnNativePlatformCacheXilinxContextV1;

/*
 * Define ZN_NPMV1_USE_XILINX_BSP for the standalone Cortex-A9 build, or
 * ZN_NPMV1_CACHE_HOST_MODEL for explicit host-only testing. Omitting a mode,
 * selecting both, or using BSP mode on a non-ARMv7-A target fails compilation.
 * Cache callbacks require nonzero 32-byte-aligned addresses and lengths,
 * without 32-bit end overflow. Caller owns every cache line in the range.
 * Host mode performs no device cache operations and cannot qualify a board.
 */
int zn_native_platform_cache_xilinx_ops_v1(
    ZnNativePlatformMemoryOpsV1 *ops,
    ZnNativePlatformCacheXilinxContextV1 *context);

#endif
