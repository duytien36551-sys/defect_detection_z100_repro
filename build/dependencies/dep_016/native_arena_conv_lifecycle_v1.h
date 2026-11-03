#ifndef Z100_NATIVE_ARENA_CONV_LIFECYCLE_V1_H
#define Z100_NATIVE_ARENA_CONV_LIFECYCLE_V1_H

#include "native_arena_owner_v1.h"
#include "native_graph_conv_bridge_v2.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum ZnNativeArenaConvLifecycleCodeV1 {
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED = 0,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY = 1,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FINISH_REQUIRED = 2,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_SCRATCH_RELEASED = 3,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_UNSUPPORTED = 4,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ARGUMENT = -1,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_STALE_REQUEST = -2,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_INVALID = -3,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ORDER = -4,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED = -5,
    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_POISONED = -6
} ZnNativeArenaConvLifecycleCodeV1;

typedef struct ZnNativeArenaConvLifecycleV1 {
    ZnNativeArenaOwnerV1 *owner;
    ZnNativeGraphConvHooksV2 runtime_hooks;
    ZnNativeGraphConvBridgeV2 bridge;
    ZnDispatch active_dispatch_snapshot;
    ZnRequest active_request;
    ZnDispatch last_run_dispatch_snapshot;
    ZnRequest last_run_request;
    uint32_t bridge_dispatch_ack_count;
    uint32_t owner_shadow_commit_count;
    uint8_t active;
    uint8_t finishing;
    uint8_t fault;
    uint8_t run_started_recorded;
    uint8_t publication_recorded;
    uint8_t quiescence_recorded;
} ZnNativeArenaConvLifecycleV1;

/* Runtime hooks are wrapped by the lifecycle owner; they remain retryable on
 * BUSY. The caller serializes every operation on this one lifecycle object. */
ZnNativeArenaConvLifecycleCodeV1
zn_native_arena_conv_lifecycle_init_v1(
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    ZnNativeArenaOwnerV1 *owner,
    const ZnNativeConvMmioOpsV2 *mmio,
    const ZnNativeGraphConvHooksV2 *runtime_hooks);

/* Non-Conv slot transitions go directly through the owner. Conv RUN, DRAIN,
 * and RETURN pass through the real V2 bridge and its real dispatcher ACK. */
ZnNativeArenaConvLifecycleCodeV1
zn_native_arena_conv_lifecycle_step_v1(
    ZnNativeArenaConvLifecycleV1 *lifecycle, ZnDispatch *dispatch,
    const ZnRequest *request, const ZnNativeGraphConvBindingV2 *binding);

/* Must succeed before any later graph request is ACKed after the final Conv
 * RETURN. BUSY retries finish only; it never resubmits or re-ACKs a RETURN. */
ZnNativeArenaConvLifecycleCodeV1
zn_native_arena_conv_lifecycle_finish_v1(
    ZnNativeArenaConvLifecycleV1 *lifecycle, const ZnDispatch *dispatch);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_ARENA_CONV_LIFECYCLE_V1_H */
