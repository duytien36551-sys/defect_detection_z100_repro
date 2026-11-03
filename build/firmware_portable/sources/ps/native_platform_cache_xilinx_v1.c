#include "native_platform_cache_xilinx_v1.h"
#include "acp_cache_policy_v1.h"

#include <string.h>

#if defined(ZN_NPMV1_USE_XILINX_BSP) && defined(ZN_NPMV1_CACHE_HOST_MODEL)
#error "Select exactly one cache implementation"
#elif !defined(ZN_NPMV1_USE_XILINX_BSP) && !defined(ZN_NPMV1_CACHE_HOST_MODEL)
#error "Explicit Xilinx BSP or host-only cache model selection is required"
#endif

#if defined(ZN_ACP_CACHE_POLICY_HOST_TEST_STUBS) && !defined(ZN_NPMV1_CACHE_HOST_MODEL)
#error "Cache-operation stubs are restricted to the host model"
#endif

#if defined(ZN_NPMV1_USE_XILINX_BSP)
#if !defined(__ARM_ARCH_7A__)
#error "The Xilinx adapter requires a Cortex-A9 ARMv7-A target"
#endif
#include "xil_cache.h"
#elif defined(ZN_ACP_CACHE_POLICY_HOST_TEST_STUBS)
#include <stdint.h>
extern void Xil_DCacheFlushRange(intptr_t address, uint32_t bytes);
extern void Xil_DCacheInvalidateRange(intptr_t address, uint32_t bytes);
extern void zn_acp_cache_policy_host_test_barrier_trace(void);
#endif

static int cache_range_valid(const void *address, size_t bytes)
{
    uintptr_t begin = (uintptr_t)address;
    return begin != 0u && bytes != 0u && (begin & 31u) == 0u &&
           (bytes & 31u) == 0u && begin <= UINT32_MAX &&
           (uintmax_t)bytes <= (uintmax_t)UINT32_MAX - begin;
}

static int reserve_range(void *opaque,
                         const ZnNativePlatformReservationV1 *range)
{
    ZnNativePlatformCacheXilinxContextV1 *context =
        (ZnNativePlatformCacheXilinxContextV1 *)opaque;
    if (!context || !context->reserve || !range)
        return -1;
    return context->reserve(context->reserve_context, range);
}

static int copy_range(void *opaque, uint8_t *destination,
                      const uint8_t *source, size_t bytes)
{
    (void)opaque;
    if ((!destination || !source) && bytes != 0u)
        return -1;
    if (bytes != 0u)
        (void)memmove(destination, source, bytes);
    return 0;
}

static int cache_clean(void *opaque, void *address, size_t bytes)
{
    (void)opaque;
    if (!cache_range_valid(address, bytes))
        return -1;
    if (zn_acp_cache_policy_should_skip_v1((uintptr_t)address, bytes))
        return 0;
#if defined(ZN_NPMV1_USE_XILINX_BSP)
    Xil_DCacheFlushRange((INTPTR)address, (u32)bytes);
#elif defined(ZN_ACP_CACHE_POLICY_HOST_TEST_STUBS)
    Xil_DCacheFlushRange((intptr_t)address, (uint32_t)bytes);
#else
    (void)address;
#endif
    return 0;
}

static int barrier(void *opaque)
{
    (void)opaque;
#if defined(__arm__) && defined(ZN_NPMV1_USE_XILINX_BSP)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
#endif
#if defined(ZN_ACP_CACHE_POLICY_HOST_TEST_STUBS)
    zn_acp_cache_policy_host_test_barrier_trace();
#endif
    return 0;
}

static int invalidate_readback(void *opaque, void *address, size_t bytes)
{
    (void)opaque;
    if (!cache_range_valid(address, bytes))
        return -1;
    if (zn_acp_cache_policy_should_skip_v1((uintptr_t)address, bytes))
        return 0;
#if defined(ZN_NPMV1_USE_XILINX_BSP)
    Xil_DCacheInvalidateRange((INTPTR)address, (u32)bytes);
#elif defined(ZN_ACP_CACHE_POLICY_HOST_TEST_STUBS)
    Xil_DCacheInvalidateRange((intptr_t)address, (uint32_t)bytes);
#else
    (void)address;
#endif
    return 0;
}

int zn_native_platform_cache_xilinx_ops_v1(
    ZnNativePlatformMemoryOpsV1 *ops,
    ZnNativePlatformCacheXilinxContextV1 *context)
{
    if (!ops || !context || !context->reserve)
        return -1;
    if (zn_acp_cache_policy_seal_once_v1() != ZN_ACP_POLICY_OK_V1)
        return ZN_ACP_POLICY_ERR_LIFECYCLE_V1;
    ops->reserve = reserve_range;
    ops->copy = copy_range;
    ops->cache_clean = cache_clean;
    ops->barrier = barrier;
    ops->invalidate_readback = invalidate_readback;
    return 0;
}
