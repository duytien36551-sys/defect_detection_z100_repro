#ifndef Z100_NATIVE_NONCONV_RUNTIME_HOOKS_V1_H
#define Z100_NATIVE_NONCONV_RUNTIME_HOOKS_V1_H

#include "native_arena_nonconv_lifecycle_v1.h"
#include "native_pool_graph_adapter_v1.h"
#include "native_platform_memory_v1.h"
#include "native_runtime_maps_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1 613248u

typedef struct ZnNativeNonConvRuntimeHooksV1 {
    ZnPoolGraphAdapterV1 *pool_adapter;
    ZnNativeArenaOwnerV1 *owner;
    ZnDispatch *dispatch;
    ZnNativeArenaNonConvLifecycleV1 *lifecycle;
    ZnNativePlatformMappedSpanV1 arena;
    ZnNativePlatformMappedSpanV1 heads;
    ZnNativePlatformMemoryOpsV1 cache_ops;
    void *cache_context;
    ZnRequest run_request;
    uint32_t operator_call_baseline;
    uint8_t heads_exclusive;
    uint8_t run_active;
    uint8_t output_cache_visible;
    uint8_t output_publish_ready;
    uint8_t heads_cache_visible;
} ZnNativeNonConvRuntimeHooksV1;

/* The caller owns and keeps the mappings, reservations, owner, dispatcher,
 * lifecycle, and platform callbacks stable for the hook lifetime. HEADS must
 * be a separate exclusive mapping with a 64-byte-aligned cache span of at
 * least 613248 bytes. This function does not reserve or publish memory. */
int zn_native_nonconv_runtime_hooks_init_v1(
    ZnNativeNonConvRuntimeHooksV1 *runtime,
    ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
    ZnNativeArenaNonConvLifecycleV1 *lifecycle,
    const ZnNativePlatformMappedSpanV1 *arena,
    const ZnNativePlatformMappedSpanV1 *heads,
    uint8_t heads_exclusive,
    const ZnNativePlatformMemoryOpsV1 *cache_ops, void *cache_context,
    ZnNativeArenaNonConvHooksV1 *hooks);

/* Install before lifecycle init / any graph RUN. Each Pool command still
 * requires exact current-request binding with zn_pool_graph_bind_v1. */
int zn_native_nonconv_runtime_attach_pool_v1(
    ZnNativeNonConvRuntimeHooksV1 *, ZnPoolGraphAdapterV1 *, ZnNativeArenaNonConvHooksV1 *);

/* Return HEADS only after the caller completes final dispatcher and owner
 * verification. On rejection, leave both output objects unchanged. */
int zn_native_nonconv_runtime_heads_result_v1(
    const ZnNativeNonConvRuntimeHooksV1 *runtime,
    const uint8_t **data, size_t *bytes);

#ifdef __cplusplus
}
#endif

#endif
