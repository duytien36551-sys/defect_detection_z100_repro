#ifndef Z100_NATIVE_GRAPH_EXECUTOR_V1_H
#define Z100_NATIVE_GRAPH_EXECUTOR_V1_H

#include "native_arena_conv_lifecycle_v1.h"
#include "native_arena_nonconv_lifecycle_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum ZnNativeGraphExecutorCodeV1 {
    ZN_NATIVE_GRAPH_EXECUTOR_V1_ACKED = 0,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY = 1,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_SCRATCH_RELEASED = 2,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_COMPLETE = 3,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_UNSUPPORTED = 4,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_ARGUMENT = -1,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST = -2,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_INVALID = -3,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_FAILED = -4,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_POISONED = -5,
    ZN_NATIVE_GRAPH_EXECUTOR_V1_TIMED_OUT = -6
} ZnNativeGraphExecutorCodeV1;

enum {
    ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_READY_V1 = 0,
    ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_BUSY_V1 = 1,
    ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_UNSUPPORTED_V1 = 2,
    ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1 = -1
};

/* The resolver chooses the exact direct or scratch/view Conv binding. BUSY is
 * retryable; it must retain any reservation and leave *binding unchanged. */
typedef int (*ZnNativeGraphExecutorResolveConvV1)(
    void *context, const ZnRequest *request,
    ZnNativeGraphConvBindingV2 *binding);

/* The caller serializes step/timeout calls and initializes the owner,
 * dispatcher, and both lifecycles before executor initialization. */
typedef struct ZnNativeGraphExecutorV1 {
    ZnNativeArenaOwnerV1 *owner;
    ZnDispatch *dispatch;
    ZnNativeArenaConvLifecycleV1 *conv_lifecycle;
    ZnNativeArenaNonConvLifecycleV1 *nonconv_lifecycle;
    ZnNativeGraphExecutorResolveConvV1 resolve_conv;
    void *resolve_context;
    ZnRequest pending_request;
    ZnRequest binding_run_request;
    ZnNativeGraphConvBindingV2 binding;
    ZnNativeGraphConvBindingV2 binding_snapshot;
    int32_t terminal_code;
    uint8_t pending_valid;
    uint8_t binding_valid;
    uint8_t finish_pending;
    uint8_t terminal;
    uint8_t complete;
} ZnNativeGraphExecutorV1;

ZnNativeGraphExecutorCodeV1
zn_native_graph_executor_v1_init(
    ZnNativeGraphExecutorV1 *executor, ZnNativeArenaOwnerV1 *owner,
    ZnDispatch *dispatch, ZnNativeArenaConvLifecycleV1 *conv_lifecycle,
    ZnNativeArenaNonConvLifecycleV1 *nonconv_lifecycle,
    ZnNativeGraphExecutorResolveConvV1 resolve_conv, void *resolve_context);

/* Polls one dispatcher request. BUSY retains the exact request and resolved
 * Conv binding. After the final Conv RETURN, BUSY retries finish only. */
ZnNativeGraphExecutorCodeV1
zn_native_graph_executor_v1_step(ZnNativeGraphExecutorV1 *executor);

/* Permanently faults owner and dispatcher while retaining all leases and
 * reservations. Recovery must independently establish physical quiescence. */
ZnNativeGraphExecutorCodeV1
zn_native_graph_executor_v1_timeout(ZnNativeGraphExecutorV1 *executor);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_GRAPH_EXECUTOR_V1_H */
