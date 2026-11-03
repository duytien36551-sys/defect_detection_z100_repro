#include "native_graph_frame_v1.h"
#include "graph_plan.h"

#include <string.h>

#define FRAME_MAGIC UINT32_C(0x4e474631)
#define FRAME_RUNNING 4

static int disjoint(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t ab = (uintptr_t)a, bb = (uintptr_t)b;
    return a && b && an && bn && an <= UINTPTR_MAX-ab && bn <= UINTPTR_MAX-bb &&
           (ab+an <= bb || bb+bn <= ab);
}

static int mapped(const ZnNativePlatformMappedSpanV1 *m, uint64_t base, uint64_t bytes)
{
    return m->physical_base == base && m->bytes == bytes && m->cpu_bytes == bytes && m->cpu_base &&
           !((uintptr_t)m->cpu_base & (uintptr_t)63u) && m->cpu_bytes <= UINTPTR_MAX-(uintptr_t)m->cpu_base;
}

static int outside(const ZnNativeGraphFrameV1 *f, const ZnNativeGraphFrameConfigV1 *c,
                   const void *p, size_t n)
{
    return disjoint(p, n, f, sizeof *f) && disjoint(p, n, c->arena.cpu_base, c->arena.cpu_bytes) &&
           disjoint(p, n, c->scratch.cpu_base, c->scratch.cpu_bytes) &&
           disjoint(p, n, c->heads.cpu_base, c->heads.cpu_bytes);
}

static int fail(ZnNativeGraphFrameV1 *f)
{
    f->state = ZN_NATIVE_FRAME_V1_FAILED;
    f->owner.fault = 1;
    f->dispatch.fault = 1;
    return ZN_NATIVE_FRAME_V1_FAILED;
}

#define POOL_CONV_MAX_RUNS UINT32_C(26380)
#define POOL_CONV_MAX_WINDOWS UINT32_C(1659840)

static int pool_ids_valid(const ZnNativeGraphFrameConfigV1 *c)
{
    uint32_t max_tiles=0;
    unsigned i;
    const ZnPoolScheduleConfigV1 *p=&c->pool_ids;
    for(i=0;i<ZN_NATIVE_ARENA_EVENT_COUNT_V1;++i)
        if(z100_graph_events[i].operation==ZN_CONV && z100_graph_events[i].tile_count>max_tiles)
            max_tiles=z100_graph_events[i].tile_count;
    /* Conv consumes job_base..job_base+max_tiles-1; each Pool consumes
     * exactly one job ID. Tokens/tags also use separate reserved ranges;
     * conservative frozen-graph bounds are validated by the preparation tool. */
    return p->job_base && p->token_base && p->tag_base &&
        p->job_base<=UINT32_MAX-2 && p->token_base<=UINT32_MAX-2 && p->tag_base<=UINT32_MAX-2 &&
        (uint64_t)c->ids.job_base+max_tiles<=p->job_base &&
        (uint64_t)c->ids.token_base+POOL_CONV_MAX_RUNS<=p->token_base &&
        (uint64_t)c->ids.tag_base+POOL_CONV_MAX_WINDOWS<=p->tag_base &&
        p->load_timeout && p->compute_timeout && p->write_timeout && p->preaccept_timeout && p->first_bank<=1;
}
static int attach_pool(ZnNativeGraphFrameV1 *f)
{
    ZnPoolCacheOpsV1 cache;
    cache.context=f->config.memory_context;
    cache.clean=f->config.memory.cache_clean;
    cache.invalidate=f->config.memory.invalidate_readback;
    cache.barrier=f->config.memory.barrier;
    if(zn_pool_scheduler_init_v1(&f->pool_scheduler,&f->owner,&f->dispatch,
        &f->conv.bridge.driver,&cache,&f->config.pool_ids)!=0 ||
       zn_native_nonconv_runtime_attach_pool_v1(&f->nonconv_runtime,&f->pool_scheduler.adapter,
        &f->nonconv_hooks)!=0) return -1;
    f->nonconv_hooks.pool_context=&f->pool_scheduler;
    f->nonconv_hooks.pool_step=zn_pool_scheduler_step_v1;
    return 0;
}

int zn_native_graph_frame_init_v1(ZnNativeGraphFrameV1 *f, const ZnNativeGraphFrameConfigV1 *c)
{
    ZnDispatch checked_dispatch;
    ZnNativeArenaOwnerV1 checked_owner;
    if (!f || f->magic || !c || !c->epoch || !c->read_ticks || !c->ticks_per_second || !c->budget_ticks ||
        !c->mmio.read32 || !c->mmio.write32 || !c->mmio.write_barrier ||
        !c->memory.cache_clean || !c->memory.invalidate_readback || !c->memory.barrier ||
        !pool_ids_valid(c) ||
        !c->ids.job_base || !c->ids.token_base || !c->ids.tag_base || c->ids.first_bank > 1 ||
        !c->ids.load_timeout_cycles || !c->ids.parameter_timeout_cycles ||
        !c->ids.write_timeout_cycles || !c->ids.preaccept_timeout_cycles ||
        !mapped(&c->arena, UINT64_C(0x10000000), UINT64_C(5201920)) ||
        !mapped(&c->scratch, ZN_NPMV1_VIEW_SCRATCH_CANDIDATE_ADDRESS, ZN_NPMV1_VIEW_SCRATCH_MIN_BYTES) ||
        !mapped(&c->heads, UINT64_C(0x24000000), ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1) ||
        !outside(f, c, c, sizeof *c) ||
        !disjoint(f, sizeof *f, c->arena.cpu_base, c->arena.cpu_bytes) ||
        !disjoint(f, sizeof *f, c->scratch.cpu_base, c->scratch.cpu_bytes) ||
        !disjoint(f, sizeof *f, c->heads.cpu_base, c->heads.cpu_bytes) ||
        !disjoint(c->arena.cpu_base, c->arena.cpu_bytes, c->scratch.cpu_base, c->scratch.cpu_bytes) ||
        !disjoint(c->arena.cpu_base, c->arena.cpu_bytes, c->heads.cpu_base, c->heads.cpu_bytes) ||
        !disjoint(c->scratch.cpu_base, c->scratch.cpu_bytes, c->heads.cpu_base, c->heads.cpu_bytes))
        return ZN_NATIVE_FRAME_V1_ARGUMENT;
    memset(&checked_dispatch, 0, sizeof checked_dispatch);
    memset(&checked_owner, 0, sizeof checked_owner);
    if (zn_dispatch_init(&checked_dispatch, z100_graph_events, ZN_NATIVE_ARENA_EVENT_COUNT_V1, c->epoch) != 0 ||
        zn_native_arena_owner_init_v1(&checked_owner, &c->arena_config, &checked_dispatch, c->epoch) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED) return ZN_NATIVE_FRAME_V1_ARGUMENT;
    memset(f, 0, sizeof *f);
    f->magic = FRAME_MAGIC;
    f->config = *c;
    if (zn_dispatch_init(&f->dispatch, z100_graph_events, ZN_NATIVE_ARENA_EVENT_COUNT_V1, c->epoch) != 0 ||
        zn_native_arena_owner_init_v1(&f->owner, &c->arena_config, &f->dispatch, c->epoch) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED ||
        zn_native_graph_conv_runtime_init_v1(&f->conv_runtime, &f->owner, &f->dispatch, &f->conv,
            &f->config.arena, &f->config.scratch, &f->config.ids, &f->config.memory,
            f->config.memory_context, &f->conv_hooks) != 0 ||
        zn_native_arena_conv_lifecycle_init_v1(&f->conv, &f->owner, &f->config.mmio, &f->conv_hooks) !=
            ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED ||
        zn_native_nonconv_runtime_hooks_init_v1(&f->nonconv_runtime, &f->owner, &f->dispatch, &f->nonconv,
            &f->config.arena, &f->config.heads, 1, &f->config.memory, f->config.memory_context, &f->nonconv_hooks) != 0 ||
        attach_pool(f) != 0 ||
        zn_native_arena_nonconv_lifecycle_init_v1(&f->nonconv, &f->owner, &f->nonconv_hooks) !=
            ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED ||
        zn_native_graph_executor_v1_init(&f->executor, &f->owner, &f->dispatch, &f->conv, &f->nonconv,
            zn_native_graph_conv_runtime_resolve_v1, &f->conv_runtime) != ZN_NATIVE_GRAPH_EXECUTOR_V1_ACKED)
        return fail(f);
    f->state = ZN_NATIVE_FRAME_V1_READY;
    return ZN_NATIVE_FRAME_V1_READY;
}

int zn_native_graph_frame_start_v1(ZnNativeGraphFrameV1 *f, const uint8_t *input, size_t bytes)
{
    size_t y, word, c;
    if (!f || f->magic != FRAME_MAGIC) return ZN_NATIVE_FRAME_V1_ARGUMENT;
    if (f->state != ZN_NATIVE_FRAME_V1_READY) return ZN_NATIVE_FRAME_V1_STATE;
    if (bytes != ZN_NATIVE_FRAME_INPUT_BYTES_V1 || !outside(f, &f->config, input, bytes))
        return ZN_NATIVE_FRAME_V1_ARGUMENT;
    f->last_poller_code = zn_native_graph_poller_init_v1(&f->poller, &f->executor, f->config.read_ticks,
        f->config.clock_context, f->config.ticks_per_second, f->config.budget_ticks);
    if (f->last_poller_code != ZN_NATIVE_GRAPH_POLLER_V1_YIELDED) return fail(f);
    for (y = 0; y < 640; ++y) {
        for (word = 0; word < 40; ++word) {
            uint8_t *out = f->config.arena.cpu_base + (y*40+word)*64;
            for (c = 0; c < 3; ++c)
                memcpy(out+c*16, input+c*409600+y*640+word*16, 16);
            memset(out+48, 0, 16);
        }
    }
    f->state = FRAME_RUNNING;
    return ZN_NATIVE_FRAME_V1_YIELDED;
}

int zn_native_graph_frame_poll_v1(ZnNativeGraphFrameV1 *f, uint32_t max_steps)
{
    int code;
    if (!f || f->magic != FRAME_MAGIC || !max_steps || max_steps > ZN_NATIVE_GRAPH_POLLER_MAX_STEPS_V1)
        return ZN_NATIVE_FRAME_V1_ARGUMENT;
    if (f->state == ZN_NATIVE_FRAME_V1_COMPLETE || f->state == ZN_NATIVE_FRAME_V1_COMPLETE_LATE ||
        f->state == ZN_NATIVE_FRAME_V1_FAILED) return f->state;
    if (f->state != FRAME_RUNNING) return ZN_NATIVE_FRAME_V1_STATE;
    code = zn_native_graph_poller_poll_v1(&f->poller, max_steps);
    f->last_poller_code = code;
    if (code == ZN_NATIVE_GRAPH_POLLER_V1_YIELDED) return ZN_NATIVE_FRAME_V1_YIELDED;
    if (code == ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE || code == ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE_LATE) {
        f->state = code == ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE ? ZN_NATIVE_FRAME_V1_COMPLETE : ZN_NATIVE_FRAME_V1_COMPLETE_LATE;
        return f->state;
    }
    return fail(f);
}

int zn_native_graph_frame_heads_v1(const ZnNativeGraphFrameV1 *f, const uint8_t **data, size_t *bytes)
{
    if (!f || f->magic != FRAME_MAGIC || !data || !bytes ||
        (f->state != ZN_NATIVE_FRAME_V1_COMPLETE && f->state != ZN_NATIVE_FRAME_V1_COMPLETE_LATE) ||
        !outside(f, &f->config, data, sizeof *data) || !outside(f, &f->config, bytes, sizeof *bytes) ||
        !disjoint(data, sizeof *data, bytes, sizeof *bytes)) return ZN_NATIVE_FRAME_V1_ARGUMENT;
    return zn_native_nonconv_runtime_heads_result_v1(&f->nonconv_runtime, data, bytes) == 0 ?
        ZN_NATIVE_FRAME_V1_READY : ZN_NATIVE_FRAME_V1_FAILED;
}

int zn_native_graph_frame_rearm_v1(ZnNativeGraphFrameV1 *f, uint32_t next_epoch)
{
    ZnNativeGraphFrameConfigV1 next;
    int code;
    if (!f || f->magic != FRAME_MAGIC) return ZN_NATIVE_FRAME_V1_ARGUMENT;
    if ((f->state != ZN_NATIVE_FRAME_V1_COMPLETE && f->state != ZN_NATIVE_FRAME_V1_COMPLETE_LATE) ||
        next_epoch <= f->config.epoch || !f->executor.complete || f->executor.terminal ||
        !f->owner.complete || f->owner.epoch != f->config.epoch ||
        f->conv.active || f->conv.fault || f->nonconv.fault || f->conv_runtime.mode ||
        f->conv_runtime.scratch_in_use || f->conv_runtime.direct.active ||
        f->conv_runtime.direct.cache.stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED ||
        f->conv_runtime.view_cache.stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED ||
        f->conv.bridge.stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_IDLE ||
        f->conv.bridge.driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(&f->conv.bridge.driver) ||
        zn_native_arena_owner_verify_complete_v1(&f->owner, &f->dispatch) != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return ZN_NATIVE_FRAME_V1_STATE;
    if(f->pool_scheduler.fault ||
       (f->pool_scheduler.adapter.bound && zn_pool_graph_release_v1(&f->pool_scheduler.adapter)!=0))
        return ZN_NATIVE_FRAME_V1_STATE;
    next = f->config;
    next.epoch = next_epoch;
    f->magic = 0; /* Only this verified-success transition permits construction. */
    code = zn_native_graph_frame_init_v1(f, &next);
    if (code == ZN_NATIVE_FRAME_V1_READY) return code;
    f->magic = FRAME_MAGIC;
    return fail(f);
}

int zn_native_graph_frame_pool_abort_v1(ZnNativeGraphFrameV1 *f)
{
    if(!f || f->magic!=FRAME_MAGIC || f->state!=ZN_NATIVE_FRAME_V1_FAILED ||
       !f->pool_scheduler.adapter.bound ||
       f->pool_scheduler.adapter.async.state==ZN_POOL_ASYNC_COMPLETE)
        return ZN_NATIVE_FRAME_V1_STATE;
    return zn_pool_scheduler_abort_v1(&f->pool_scheduler);
}
