#ifndef Z100_NATIVE_VIEW_CONV_RUNTIME_HOOKS_V1_H
#define Z100_NATIVE_VIEW_CONV_RUNTIME_HOOKS_V1_H

#include "native_feature_cache_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_VIEW_CONV_MAX_READS_V1 7u

typedef enum ZnNativeViewConvRuntimeCodeV1 {
    ZN_NATIVE_VIEW_CONV_RUNTIME_V1_READY = 0,
    ZN_NATIVE_VIEW_CONV_RUNTIME_V1_ARGUMENT = -1,
    ZN_NATIVE_VIEW_CONV_RUNTIME_V1_INVALID = -2
} ZnNativeViewConvRuntimeCodeV1;

/* This adapter holds borrowed maps and input descriptors only. The caller
 * owns the arena and scratch mappings and must keep them live until release. */
typedef struct ZnNativeViewConvRuntimeV1 {
    ZnNativeArenaConvLifecycleV1 *lifecycle;
    ZnNativeFeatureCacheV1 *cache;
    ZnNativePlatformMappedSpanV1 arena_mapping;
    ZnNativePlatformMappedSpanV1 scratch_mapping;
    ZnRequest run_request;
    ZnNativeViewSourceV1 sources[ZN_NATIVE_VIEW_CONV_MAX_READS_V1];
    uint8_t source_count;
    uint8_t active;
    uint8_t source_invalidation_started;
    uint8_t converted;
} ZnNativeViewConvRuntimeV1;

/* Initialize feature_cache first, then build these hooks, then initialize the
 * lifecycle at the same lifecycle address. The supplied scratch span is the
 * caller's complete mapped scratch reservation; generated bindings select a
 * subrange for each event. All state and mappings must be disjoint. */
ZnNativeViewConvRuntimeCodeV1 zn_native_view_conv_runtime_hooks_init_v1(
    ZnNativeViewConvRuntimeV1 *runtime,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativePlatformMappedSpanV1 *arena_mapping,
    const ZnNativePlatformMappedSpanV1 *scratch_mapping,
    ZnNativeGraphConvHooksV2 *hooks);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_VIEW_CONV_RUNTIME_HOOKS_V1_H */
