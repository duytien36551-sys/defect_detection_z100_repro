#ifndef Z100_POOL_GRAPH_ADAPTER_V1_H
#define Z100_POOL_GRAPH_ADAPTER_V1_H
#include "native_pool_async_v1.h"
#include "native_arena_nonconv_lifecycle_v1.h"

typedef struct {
    ZnNativeArenaOwnerV1 *owner;
    ZnDispatch *dispatch;
    ZnNativeConvDriverV2 *driver;
    ZnPoolCacheOpsV1 cache;
    ZnNativeConvCommand command;
    ZnRequest request;
    ZnPoolAsyncV1 async;
    unsigned bound;
    unsigned fault;
} ZnPoolGraphAdapterV1;

/* Zero-init once. Bind the CURRENT pending Pool RUN after graph ACQUIRE.
 * Command IDs come from the same allocator used by Conv; this API never
 * invents/reuses them. Driver must be the single shared Conv/Pool owner.
 * Binding performs no cache/MMIO. No rebind before exact graph RETURN/drain. */
int zn_pool_graph_bind_v1(ZnPoolGraphAdapterV1 *, ZnNativeArenaOwnerV1 *,
    ZnDispatch *, const ZnRequest *, const ZnNativeConvCommand *,
    ZnNativeConvDriverV2 *, const ZnPoolCacheOpsV1 *);
int zn_pool_graph_step_v1(void *, const ZnRequest *,
    const ZnNativeArenaNonConvSourceV1 *, const ZnNativeArenaNonConvOutputV1 *, uint32_t);
/* Called by PL-specific output visibility hook. Performs no cache clean. */
int zn_pool_graph_visible_v1(const ZnPoolGraphAdapterV1 *, const ZnRequest *,
    const ZnNativeArenaNonConvOutputV1 *, uint32_t);
int zn_pool_graph_drained_v1(const ZnPoolGraphAdapterV1 *, const ZnRequest *);
int zn_pool_graph_release_v1(ZnPoolGraphAdapterV1 *);
/* A failed graph retains all references. Recovery code continues physical
 * transport draining directly; it must not reset/reinitialize the driver. */
int zn_pool_graph_cancel_v1(ZnPoolGraphAdapterV1 *);
/* Fault-service continuation. 2 means observed physical terminal only;
 * graph leases remain retained and release remains forbidden. */
int zn_pool_graph_abort_drain_v1(ZnPoolGraphAdapterV1 *);
#endif
