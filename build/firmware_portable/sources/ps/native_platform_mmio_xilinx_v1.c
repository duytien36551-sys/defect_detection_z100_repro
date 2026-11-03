#include "native_platform_mmio_xilinx_v1.h"

#if defined(ZN_NPMMIO_V1_USE_XILINX_BSP) && defined(ZN_NPMMIO_V1_HOST_MODEL)
#error "Select exactly one MMIO implementation"
#elif !defined(ZN_NPMMIO_V1_USE_XILINX_BSP) && !defined(ZN_NPMMIO_V1_HOST_MODEL)
#error "Explicit Xilinx BSP or host-only MMIO model selection is required"
#endif

#if defined(ZN_NPMMIO_V1_USE_XILINX_BSP)
#if !defined(__ARM_ARCH_7A__)
#error "The Xilinx MMIO adapter requires a Cortex-A9 ARMv7-A target"
#endif
#include "xil_io.h"
#endif

static int context_valid(const ZnNativePlatformMmioXilinxContextV1 *context)
{
    if (!context || context->base != ZN_NPMMIO_V1_BASE ||
        context->bytes != ZN_NPMMIO_V1_BYTES)
        return 0;
#if defined(ZN_NPMMIO_V1_USE_XILINX_BSP)
    return !context->host_context && !context->host_read32 &&
           !context->host_write32 && !context->host_barrier;
#else
    return context->host_read32 && context->host_write32 &&
           context->host_barrier;
#endif
}

static int readable(uint32_t offset)
{
    return (offset & 3u) == 0u &&
           (offset <= ZN_NC_REG_CAPABILITIES ||
            (offset >= ZN_NC_REG_STATUS && offset <= ZN_NC_REG_COMMITTED_TILES) ||
            (offset >= ZN_NC_REG_RESULT_COOKIE && offset <= ZN_NC_REG_RESULT_SOURCE_GEN));
}

static int writable(uint32_t offset, uint32_t value)
{
    if ((offset & 3u) != 0u)
        return 0;
    if (offset == ZN_NC_REG_CONTROL)
        return value != 0u && (value & ~ZN_NC_CONTROL_VALID_MASK) == 0u &&
               (value & (value - 1u)) == 0u;
    return offset >= ZN_NC_REG_SHADOW_COOKIE &&
           offset <= ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT;
}

static int read32(void *opaque, uint32_t offset, uint32_t *value)
{
    ZnNativePlatformMmioXilinxContextV1 *context =
        (ZnNativePlatformMmioXilinxContextV1 *)opaque;
    uint32_t observed;
    if (!value || !context_valid(context) || !readable(offset))
        return -1;
#if defined(ZN_NPMMIO_V1_USE_XILINX_BSP)
    __asm__ volatile("dsb sy" ::: "memory");
    observed = Xil_In32((UINTPTR)(context->base + offset));
    __asm__ volatile("dsb sy" ::: "memory");
#else
    if (context->host_read32(context->host_context, context->base + offset,
                             &observed) != 0)
        return -1;
#endif
    *value = observed;
    return 0;
}

static int write32(void *opaque, uint32_t offset, uint32_t value)
{
    ZnNativePlatformMmioXilinxContextV1 *context =
        (ZnNativePlatformMmioXilinxContextV1 *)opaque;
    if (!context_valid(context) || !writable(offset, value))
        return -1;
#if defined(ZN_NPMMIO_V1_USE_XILINX_BSP)
    Xil_Out32((UINTPTR)(context->base + offset), value);
    /* Device writes are completed even for START/ACK, which the driver may
     * follow immediately with a status read. Shadow batching still uses the
     * driver's separate barrier before START. */
    __asm__ volatile("dsb sy" ::: "memory");
    return 0;
#else
    return context->host_write32(context->host_context, context->base + offset,
                                  value);
#endif
}

static int write_barrier(void *opaque)
{
    ZnNativePlatformMmioXilinxContextV1 *context =
        (ZnNativePlatformMmioXilinxContextV1 *)opaque;
    if (!context_valid(context))
        return -1;
#if defined(ZN_NPMMIO_V1_USE_XILINX_BSP)
    __asm__ volatile("dsb sy" ::: "memory");
    return 0;
#else
    return context->host_barrier(context->host_context);
#endif
}

int zn_native_platform_mmio_xilinx_ops_v1(
    ZnNativeConvMmioOpsV2 *ops,
    ZnNativePlatformMmioXilinxContextV1 *context)
{
    if (!ops || !context_valid(context))
        return -1;
    ops->context = context;
    ops->read32 = read32;
    ops->write32 = write32;
    ops->write_barrier = write_barrier;
    return 0;
}
