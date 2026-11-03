#include "native_platform_cache_xilinx_v1.h"

#include <stdio.h>
#include <string.h>

static int reserve_ok(void *context,
                      const ZnNativePlatformReservationV1 *range)
{
    unsigned *calls = (unsigned *)context;
    if (!range || range->bytes == 0u)
        return -1;
    ++*calls;
    return 0;
}

static int reserve_busy(void *context,
                        const ZnNativePlatformReservationV1 *range)
{
    (void)context;
    (void)range;
    return 1;
}

int main(void)
{
    ZnNativePlatformMemoryOpsV1 ops;
    ZnNativePlatformCacheXilinxContextV1 context;
    ZnNativePlatformReservationV1 range = { UINT64_C(0x20000000), 64u };
    unsigned calls = 0u;
    uint8_t source[64];
    uint8_t destination[64];
    unsigned i;

    for (i = 0u; i < sizeof source; ++i)
        source[i] = (uint8_t)(i ^ 0x5au);
    (void)memset(destination, 0, sizeof destination);
    context.reserve = reserve_ok;
    context.reserve_context = &calls;
    if (zn_native_platform_cache_xilinx_ops_v1(&ops, &context) != 0)
        return 1;
    if (ops.reserve(&context, &range) != 0 || calls != 1u)
        return 2;
    if (ops.copy(&context, destination, source, sizeof source) != 0 ||
        memcmp(source, destination, sizeof source) != 0)
        return 3;
    if (ops.cache_clean(&context, (void *)(uintptr_t)0x20000000u, 64u) != 0 ||
        ops.barrier(&context) != 0 ||
        ops.invalidate_readback(&context, (void *)(uintptr_t)0x21000000u, 64u) != 0)
        return 4;
    if (ops.cache_clean(&context, NULL, sizeof destination) == 0 ||
        ops.invalidate_readback(&context, destination, 0u) == 0)
        return 5;
    if (zn_native_platform_cache_xilinx_ops_v1(NULL, &context) == 0 ||
        zn_native_platform_cache_xilinx_ops_v1(&ops, NULL) == 0)
        return 6;
    if (ops.cache_clean(&context, (void *)(uintptr_t)0x20000001u, 64u) == 0 ||
        ops.invalidate_readback(&context, (void *)(uintptr_t)0x21000000u, 63u) == 0 ||
        ops.cache_clean(&context, (void *)(uintptr_t)0xffffffe0u, 32u) == 0 ||
        ops.invalidate_readback(&context, (void *)(uintptr_t)0x20000000u, (size_t)UINT32_MAX) == 0)
        return 7;
    if (ops.copy(&context, NULL, source, 1u) == 0 ||
        ops.copy(&context, destination, NULL, 1u) == 0 ||
        ops.copy(&context, NULL, NULL, 0u) != 0)
        return 8;
    context.reserve = reserve_busy;
    if (ops.reserve(&context, &range) != 1)
        return 9;
    context.reserve = NULL;
    if (ops.reserve(&context, &range) == 0 ||
        zn_native_platform_cache_xilinx_ops_v1(&ops, &context) == 0)
        return 10;
    (void)puts("NATIVE_PLATFORM_CACHE_XILINX_V1_PASS host_model=1 board_access=0");
    return 0;
}
