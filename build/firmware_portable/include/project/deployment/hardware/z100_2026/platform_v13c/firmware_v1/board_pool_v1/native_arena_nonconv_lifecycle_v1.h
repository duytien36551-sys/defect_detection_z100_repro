#ifndef Z100_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_H
#define Z100_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_H

#include "native_arena_owner_v1.h"
#include "native_view_materialize_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1 613200u

typedef enum ZnNativeArenaNonConvLifecycleCodeV1 {
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED = 0,
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY = 1,
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_UNSUPPORTED = 2,
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ARGUMENT = -1,
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_STALE_REQUEST = -2,
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_INVALID = -3,
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ORDER = -4,
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED = -5,
    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_POISONED = -6
} ZnNativeArenaNonConvLifecycleCodeV1;

enum {
    ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1 = 0,
    ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1 = 1,
    ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1 = -1
};

typedef struct ZnNativeArenaNonConvSourceV1 {
    uint32_t physical_address;
    ZnNativeViewSourceV1 view;
} ZnNativeArenaNonConvSourceV1;

typedef struct ZnNativeArenaNonConvOutputV1 {
    uint32_t physical_address;
    uint8_t *data;
    size_t capacity_bytes;
} ZnNativeArenaNonConvOutputV1;

/* Hook return values are READY, BUSY, or FAILED. READY map results retain the
 * returned mapping until the matching graph reads have been returned. BUSY
 * retries only that hook; callers serialize the lifecycle and retain leases. */
typedef struct ZnNativeArenaNonConvHooksV1 {
    void *context;
    /* Pool is always asynchronous in this candidate. READY promises checked
     * hardware completion, cache visibility and ACK/readback; BUSY retains all
     * graph mappings/leases. FAILED never permits CPU fallback or release.
     * The clean_output hook must distinguish PL-produced Pool from CPU ADD. */
    void *pool_context;
    int (*pool_step)(void *pool_context, const ZnRequest *request,
                     const ZnNativeArenaNonConvSourceV1 *source,
                     const ZnNativeArenaNonConvOutputV1 *output,
                     uint32_t output_bytes);
    int (*map_source)(void *context, const ZnRequest *request,
                      uint8_t read_index, uint32_t expected_address,
                      uint32_t expected_bytes,
                      ZnNativeArenaNonConvSourceV1 *source);
    int (*source_visible)(void *context, const ZnRequest *request,
                          uint8_t read_index,
                          const ZnNativeArenaNonConvSourceV1 *source);
    int (*map_output)(void *context, const ZnRequest *request,
                      uint32_t expected_address, uint32_t output_bytes,
                      ZnNativeArenaNonConvOutputV1 *output);
    int (*clean_output)(void *context, const ZnRequest *request,
                        const ZnNativeArenaNonConvOutputV1 *output,
                        uint32_t output_bytes);
    /* READY means the complete CPU output is visible to graph consumers. */
    int (*publish_output)(void *context, const ZnRequest *request,
                          const ZnNativeArenaNonConvOutputV1 *output,
                          uint32_t output_bytes);
    int (*drain_ready)(void *context, const ZnRequest *request,
                       ZnNativeArenaQuiescenceEvidenceV1 *evidence);
    int (*return_graph_read)(void *context, const ZnRequest *request,
                             uint8_t read_index, uint32_t physical_address,
                             ZnRef ref);
} ZnNativeArenaNonConvHooksV1;

typedef struct ZnNativeArenaNonConvLifecycleV1 {
    ZnNativeArenaOwnerV1 *owner;
    ZnNativeArenaNonConvHooksV1 hooks;
    ZnRequest run_request;
    ZnNativeArenaNonConvSourceV1 sources[7];
    ZnNativeArenaNonConvOutputV1 output;
    uint32_t operator_call_count;
    uint8_t active;
    uint8_t mapped_mask;
    uint8_t visible_mask;
    uint8_t output_mapped;
    uint8_t run_started;
    uint8_t computed;
    uint8_t pool_started;
    uint8_t output_cleaned;
    uint8_t completion_recorded;
    uint8_t run_acked;
    uint8_t quiescence_recorded;
    uint8_t fault;
} ZnNativeArenaNonConvLifecycleV1;

/* Initialize after owner/dispatch initialization. The caller serializes every
 * operation and owns physical reservation, platform visibility, and leases. */
ZnNativeArenaNonConvLifecycleCodeV1
zn_native_arena_nonconv_lifecycle_init_v1(
    ZnNativeArenaNonConvLifecycleV1 *lifecycle,
    ZnNativeArenaOwnerV1 *owner,
    const ZnNativeArenaNonConvHooksV1 *hooks);

/* ALLOCATE/ACQUIRE/RETIRE use the owner directly. ADD/POOL/HEADS RUN, DRAIN,
 * and exact ordered RETURN requests use this adapter and its runtime hooks. */
ZnNativeArenaNonConvLifecycleCodeV1
zn_native_arena_nonconv_lifecycle_step_v1(
    ZnNativeArenaNonConvLifecycleV1 *lifecycle, ZnDispatch *dispatch,
    const ZnRequest *request);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_H */
