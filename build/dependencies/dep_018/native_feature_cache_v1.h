#ifndef Z100_NATIVE_FEATURE_CACHE_V1_H
#define Z100_NATIVE_FEATURE_CACHE_V1_H

#include "native_arena_conv_lifecycle_v1.h"
#include "native_runtime_maps_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_FEATURE_CACHE_LINE_BYTES_V1 32u

typedef enum ZnNativeFeatureCacheCodeV1 {
    ZN_NATIVE_FEATURE_CACHE_V1_READY = 0,
    ZN_NATIVE_FEATURE_CACHE_V1_BUSY = 1,
    ZN_NATIVE_FEATURE_CACHE_V1_ARGUMENT = -1,
    ZN_NATIVE_FEATURE_CACHE_V1_STALE = -2,
    ZN_NATIVE_FEATURE_CACHE_V1_INVALID = -3,
    ZN_NATIVE_FEATURE_CACHE_V1_CACHE_FAILED = -4,
    ZN_NATIVE_FEATURE_CACHE_V1_ORDER = -5,
    ZN_NATIVE_FEATURE_CACHE_V1_POISONED = -6
} ZnNativeFeatureCacheCodeV1;

typedef enum ZnNativeFeatureCacheStageV1 {
    ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY = 0,
    ZN_NATIVE_FEATURE_CACHE_STAGE_V1_BOUND,
    ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARING,
    ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED,
    ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE,
    ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED,
    ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED
} ZnNativeFeatureCacheStageV1;

/* BUSY means the scratch allocator did not release any part of the lease. */
typedef int (*ZnNativeFeatureCacheReleaseScratchV1)(
    void *context, const ZnNativeGraphScratchLeaseV2 *lease);

typedef struct ZnNativeFeatureCacheOpsV1 {
    ZnNativePlatformMemoryOpsV1 memory;
    void *memory_context;
    ZnNativeFeatureCacheReleaseScratchV1 release_scratch;
    void *release_context;
} ZnNativeFeatureCacheOpsV1;

/* Caller zero-initializes once. Reinitialize is rejected, including after a
 * failed transaction; a later event can bind only after explicit release. */
typedef struct ZnNativeFeatureCacheV1 {
    uint32_t magic;
    uint32_t transaction_count;
    uint8_t stage;
    uint8_t step;
    int32_t callback_status;
    ZnNativeFeatureCacheOpsV1 ops;
    ZnNativeArenaOwnerV1 *owner;
    ZnNativeArenaConvLifecycleV1 *lifecycle;
    ZnRequest run_request;
    ZnNativeGraphConvBindingV2 binding;
    ZnNativePlatformMappedSpanV1 source_mapping;
    ZnNativePlatformMappedSpanV1 arena_mapping;
    ZnNativeRuntimeTensorMapV1 destination_mapping;
} ZnNativeFeatureCacheV1;

int zn_native_feature_cache_init_v1(
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativePlatformMemoryOpsV1 *memory,
    void *memory_context,
    ZnNativeFeatureCacheReleaseScratchV1 release_scratch,
    void *release_context);

/* Bind during the first RUN check_leases callback, before conversion and
 * run_started. The mapper output is retained through verified completion. */
ZnNativeFeatureCacheCodeV1 zn_native_feature_cache_bind_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnDispatch *dispatch,
    const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding,
    const ZnNativePlatformMappedSpanV1 *source_mapping,
    const ZnNativePlatformMappedSpanV1 *arena_mapping);

/* Use from runtime check_leases on RUN/DRAIN/RETURN retries. It performs no
 * cache operation and never remaps the destination after run_started. */
ZnNativeFeatureCacheCodeV1 zn_native_feature_cache_check_binding_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding);

/* Use from clean_source after the CPU view converter has finished. */
ZnNativeFeatureCacheCodeV1 zn_native_feature_cache_prepare_v1(
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativeGraphConvBindingV2 *binding);

/* Candidate-only entry for the direct Conv clean_source hook, after that hook
 * has verified the frozen generated binding. It skips source clean step 0
 * only when the owner ledger proves a completed, published, quiescent Conv
 * producer and exact current read lease. Other valid sources keep full
 * prepare; contradictory Conv identities fail closed. */
ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_prepare_direct_source_candidate_v1(
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativeGraphConvBindingV2 *binding);

/* Use from check_source_ready immediately before V2 submit. */
ZnNativeFeatureCacheCodeV1 zn_native_feature_cache_check_source_ready_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding);

/* Use from invalidate_output. The V2 success tuple and DRAIN_COMPLETE status
 * are checked before invalidation; the bridge ACKs the driver afterward. */
ZnNativeFeatureCacheCodeV1 zn_native_feature_cache_make_output_visible_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnNativeGraphConvBindingV2 *binding);

/* Use from release_scratch. Physical scratch release is gated by actual
 * lifecycle quiescence and every original graph-read RETURN. */
ZnNativeFeatureCacheCodeV1 zn_native_feature_cache_release_scratch_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnNativeGraphConvBindingV2 *binding);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_FEATURE_CACHE_V1_H */
