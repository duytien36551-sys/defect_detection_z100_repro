#ifndef Z100_NATIVE_GRAPH_CONV_RUNTIME_V1_H
#define Z100_NATIVE_GRAPH_CONV_RUNTIME_V1_H

#include "native_direct_conv_runtime_hooks_v1.h"
#include "native_view_conv_runtime_hooks_v1.h"
#include "native_direct_bindings_v2.h"
#include "native_graph_executor_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Serial graph composition: direct arena reads and materialized view reads
 * share one lifecycle. Caller exclusively reserves/maps arena and scratch.
 * No physical reservation or hardware IO is performed by init/resolve.
 * Initialize once from zero, then initialize lifecycle with the returned hooks,
 * then executor with zn_native_graph_conv_runtime_resolve_v1 and this context.
 * A failed graph retains all source/scratch ownership; init is not recovery. */
typedef struct ZnNativeGraphConvRuntimeV1 {
    uint32_t magic;
    ZnNativeArenaOwnerV1 *owner;
    ZnDispatch *dispatch;
    ZnNativeArenaConvLifecycleV1 *lifecycle;
    ZnNativeDirectConvRuntimeV1 direct;
    ZnNativeViewConvRuntimeV1 view;
    ZnNativeFeatureCacheV1 view_cache;
    ZnNativeGraphConvHooksV2 direct_hooks;
    ZnNativeGraphConvHooksV2 view_hooks;
    ZnNativePlatformMappedSpanV1 arena;
    ZnNativePlatformMappedSpanV1 scratch;
    ZnNativeDirectIdsV2 ids;
    ZnNativeGraphConvBindingV2 resolved_binding;
    ZnRequest resolved_run;
    uint32_t next_scratch_generation;
    uint32_t released_view_transactions;
    uint8_t mode; /* 0 idle, 1 direct, 2 view; retained on failure */
    uint8_t scratch_in_use;
} ZnNativeGraphConvRuntimeV1;

int zn_native_graph_conv_runtime_init_v1(
    ZnNativeGraphConvRuntimeV1 *, ZnNativeArenaOwnerV1 *, ZnDispatch *,
    ZnNativeArenaConvLifecycleV1 *, const ZnNativePlatformMappedSpanV1 *arena,
    const ZnNativePlatformMappedSpanV1 *scratch, const ZnNativeDirectIdsV2 *,
    const ZnNativePlatformMemoryOpsV1 *, void *memory_context,
    ZnNativeGraphConvHooksV2 *hooks);

int zn_native_graph_conv_runtime_resolve_v1(
    void *, const ZnRequest *, ZnNativeGraphConvBindingV2 *);

#ifdef __cplusplus
}
#endif

#endif
