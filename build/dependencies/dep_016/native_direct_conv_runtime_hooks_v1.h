#ifndef Z100_NATIVE_DIRECT_CONV_RUNTIME_HOOKS_V1_H
#define Z100_NATIVE_DIRECT_CONV_RUNTIME_HOOKS_V1_H

#include "native_feature_cache_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Candidate adapter: direct bindings borrow one native arena tensor.
 * No scratch allocator owns that tensor. The bridge's finish hook closes the
 * cache transaction after graph RETURN; it never frees/retires the arena slot.
 * Initialize this zeroed object once, build its hooks, then initialize the
 * lifecycle at the supplied address. Keep all metadata/maps stable and outside
 * the mapped arena. No MMIO/DDR reservation is performed by initialization. */
typedef struct ZnNativeDirectConvRuntimeV1 {
    ZnNativeFeatureCacheV1 cache;
    ZnNativeArenaConvLifecycleV1 *lifecycle;
    ZnNativePlatformMappedSpanV1 arena;
    uint32_t closed_transactions;
    uint8_t active;
    uint8_t source_checked;
} ZnNativeDirectConvRuntimeV1;

int zn_native_direct_conv_runtime_hooks_init_v1(
    ZnNativeDirectConvRuntimeV1 *runtime,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnNativePlatformMappedSpanV1 *arena,
    const ZnNativePlatformMemoryOpsV1 *memory, void *memory_context,
    ZnNativeGraphConvHooksV2 *hooks);

#ifdef __cplusplus
}
#endif

#endif
