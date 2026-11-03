#ifndef Z100_POOL_SCHEDULER_V1_H
#define Z100_POOL_SCHEDULER_V1_H
#include "native_pool_graph_adapter_v1.h"

/* Reserve three consecutive IDs in each namespace for Pool70/71/72 before
 * construction; the owner keeps that range separate from Conv command ranges.
 * A strictly increasing frame epoch scopes reuse of the reserved ranges. */
typedef struct {
    uint32_t job_base, token_base, tag_base;
    uint32_t load_timeout, compute_timeout, write_timeout, preaccept_timeout;
    uint8_t first_bank;
} ZnPoolScheduleConfigV1;
typedef struct {
    ZnPoolGraphAdapterV1 adapter;
    ZnNativeArenaOwnerV1 *owner;
    ZnDispatch *dispatch;
    ZnNativeConvDriverV2 *driver;
    ZnPoolCacheOpsV1 cache;
    ZnPoolScheduleConfigV1 config;
    uint32_t last_epoch, last_event;
    unsigned initialized, fault;
} ZnPoolSchedulerV1;

int zn_pool_scheduler_init_v1(ZnPoolSchedulerV1 *, ZnNativeArenaOwnerV1 *,
    ZnDispatch *, ZnNativeConvDriverV2 *, const ZnPoolCacheOpsV1 *, const ZnPoolScheduleConfigV1 *);
/* Produces a command from the frozen event and CURRENT graph slot leases.
 * No IO; rejects altered plan fields, overflow and unsupported event shapes. */
int zn_pool_scheduler_command_v1(const ZnPoolSchedulerV1 *, const ZnRequest *, ZnNativeConvCommand *);
int zn_pool_scheduler_step_v1(void *, const ZnRequest *,
    const ZnNativeArenaNonConvSourceV1 *, const ZnNativeArenaNonConvOutputV1 *, uint32_t);
int zn_pool_scheduler_abort_v1(ZnPoolSchedulerV1 *);
#endif
