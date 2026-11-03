#include "native_graph_conv_runtime_v1.h"
#include "native_scratch_bindings_v2.h"

#include <limits.h>
#include <string.h>

#define GRAPH_RUNTIME_MAGIC UINT32_C(0x4e475231)

static int disjoint(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t ab = (uintptr_t)a, bb = (uintptr_t)b;
    if (!a || !b || !an || !bn || an > UINTPTR_MAX-ab || bn > UINTPTR_MAX-bb) return 0;
    return ab+an <= bb || bb+bn <= ab;
}

static int valid_mapping(const ZnNativePlatformMappedSpanV1 *m)
{
    uintptr_t cpu;
    if (!m || !m->cpu_base || !m->bytes || m->bytes != m->cpu_bytes ||
        m->physical_base >= UINT64_C(0x40000000) ||
        m->bytes > UINT64_C(0x40000000) - m->physical_base ||
        (m->physical_base & UINT64_C(63)) || (m->bytes & UINT64_C(63))) return 0;
    cpu = (uintptr_t)m->cpu_base;
    return !(cpu & (uintptr_t)63u) && m->cpu_bytes <= UINTPTR_MAX - cpu;
}

static int same_request(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag && a->event_index == b->event_index &&
        a->operation == b->operation && a->job == b->job && a->ref.slot == b->ref.slot &&
        a->ref.tensor == b->ref.tensor && a->ref.generation == b->ref.generation;
}

static ZnNativeGraphConvHooksV2 *selected(ZnNativeGraphConvRuntimeV1 *r)
{
    if (!r || r->magic != GRAPH_RUNTIME_MAGIC) return NULL;
    return r->mode == 1 ? &r->direct_hooks : r->mode == 2 ? &r->view_hooks : NULL;
}

static int release_view(void *context, const ZnNativeGraphScratchLeaseV2 *lease)
{
    ZnNativeGraphConvRuntimeV1 *r = context;
    const ZnNativeGraphScratchLeaseV2 *expected;
    if (!r || !lease || r->mode != 2 || !r->scratch_in_use || r->released_view_transactions == UINT32_MAX) return -1;
    expected = &r->resolved_binding.scratch;
    if (lease->epoch != expected->epoch || lease->generation != expected->generation ||
        lease->base != expected->base || lease->bytes != expected->bytes) return -1;
    /* The common cache has verified driver quiet and every graph RETURN.
     * Return the caller's fixed exclusive scratch pool for the next view. */
    r->scratch_in_use = 0;
    ++r->released_view_transactions;
    return 0;
}

static int route_check(void *context, const ZnRequest *q, const ZnNativeGraphConvBindingV2 *b)
{
    ZnNativeGraphConvRuntimeV1 *r = context;
    ZnNativeGraphConvHooksV2 *h = selected(r);
    if (!h || !q || !b || q->epoch != r->resolved_run.epoch || q->event_index != r->resolved_run.event_index ||
        q->job != r->resolved_run.job || b->dispatch_tag != r->resolved_run.tag) return -1;
    return h->check_leases(h->context, q, b);
}

static int route_convert(void *context, const ZnRequest *q, const ZnNativeGraphConvBindingV2 *b)
{
    ZnNativeGraphConvHooksV2 *h = selected(context);
    return h ? h->convert_views(h->context, q, b) : -1;
}

static int route_clean(void *context, const ZnNativeGraphConvBindingV2 *b)
{
    ZnNativeGraphConvHooksV2 *h = selected(context);
    return h ? h->clean_source(h->context, b) : -1;
}

static int route_ready(void *context, const ZnRequest *q, const ZnNativeGraphConvBindingV2 *b)
{
    ZnNativeGraphConvHooksV2 *h = selected(context);
    return h ? h->check_source_ready(h->context, q, b) : -1;
}

static int route_invalidate(void *context, const ZnNativeGraphConvBindingV2 *b)
{
    ZnNativeGraphConvHooksV2 *h = selected(context);
    return h ? h->invalidate_output(h->context, b) : -1;
}

static int route_publish(void *context, const ZnNativeGraphConvBindingV2 *b)
{
    ZnNativeGraphConvHooksV2 *h = selected(context);
    return h ? h->validate_and_publish(h->context, b) : -1;
}

static int route_drain(void *context, const ZnRequest *q, const ZnNativeGraphConvBindingV2 *b)
{
    ZnNativeGraphConvHooksV2 *h = selected(context);
    return h ? h->drain_ready(h->context, q, b) : -1;
}

static int route_return(void *context, const ZnRequest *q, const ZnNativeGraphConvBindingV2 *b, uint8_t i)
{
    ZnNativeGraphConvHooksV2 *h = selected(context);
    return h ? h->return_graph_read(h->context, q, b, i) : -1;
}

static int route_finish(void *context, const ZnNativeGraphConvBindingV2 *b)
{
    ZnNativeGraphConvRuntimeV1 *r = context;
    ZnNativeGraphConvHooksV2 *h = selected(r);
    int code;
    if (!h) return -1;
    code = h->release_scratch(h->context, b);
    if (code != 0) return code;
    if (r->scratch_in_use) return -1;
    r->mode = 0;
    memset(&r->resolved_binding, 0, sizeof r->resolved_binding);
    memset(&r->resolved_run, 0, sizeof r->resolved_run);
    return 0;
}

int zn_native_graph_conv_runtime_resolve_v1(void *context, const ZnRequest *q, ZnNativeGraphConvBindingV2 *out)
{
    ZnNativeGraphConvRuntimeV1 *r = context;
    ZnNativeGraphConvBindingV2 b;
    ZnNativeGraphScratchLeaseV2 lease;
    ZnNativeRuntimeTensorMapV1 source;
    ZnNativeScratchIdsV2 ids;
    ZnNativeDirectIdsV2 event_ids;
    int code;
    if (!r || r->magic != GRAPH_RUNTIME_MAGIC || !q || !out || !q->job || q->operation != ZN_RUN ||
        q->job->operation != ZN_CONV || !r->dispatch->pending || r->dispatch->fault || r->owner->fault ||
        !same_request(q, &r->dispatch->request) || q->epoch != r->owner->epoch ||
        q->event_index >= r->owner->event_count || q->job != &r->owner->events[q->event_index])
        return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
    if (r->mode) {
        if (!same_request(q, &r->resolved_run)) return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
        *out = r->resolved_binding;
        return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_READY_V1;
    }
    if (r->scratch_in_use ||
        (r->direct.cache.stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY && r->direct.cache.stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED) ||
        (r->view_cache.stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY && r->view_cache.stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED) ||
        zn_native_runtime_map_read_v1(r->owner, r->dispatch, q, 0, &r->arena, &source) != 0 ||
        source.view.bytes > UINT32_MAX)
        return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
    lease.epoch = q->epoch;
    lease.generation = source.view.ref.generation;
    lease.base = source.physical_address;
    lease.bytes = (uint32_t)source.view.bytes;
    /* The PL retains the last accepted job range across event ACKs. Frozen
     * tile ranges are disjoint and ordered, including direct/view transitions.
     * Retrying the same resolved request still returns its cached binding. */
    if (!q->job->tile_count ||
        (uint64_t)r->ids.job_base + q->job->tile_first + q->job->tile_count >
        (uint64_t)UINT32_MAX + 1u)
        return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
    event_ids = r->ids;
    event_ids.job_base += q->job->tile_first;
    code = zn_native_direct_binding_v2(q, &event_ids, &lease, &b);
    if (code == 0) {
        r->mode = 1;
    } else if (code == 1) {
        if (!r->next_scratch_generation || r->next_scratch_generation == UINT32_MAX)
            return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
        memset(&ids, 0, sizeof ids);
        ids.job_base = event_ids.job_base; ids.token_base = event_ids.token_base; ids.tag_base = event_ids.tag_base;
        ids.load_timeout_cycles = r->ids.load_timeout_cycles; ids.parameter_timeout_cycles = r->ids.parameter_timeout_cycles;
        ids.write_timeout_cycles = r->ids.write_timeout_cycles; ids.preaccept_timeout_cycles = r->ids.preaccept_timeout_cycles;
        ids.first_bank = r->ids.first_bank;
        lease.generation = r->next_scratch_generation;
        lease.base = (uint32_t)r->scratch.physical_base;
        lease.bytes = (uint32_t)r->scratch.bytes;
        if (zn_native_scratch_binding_v2(q, &ids, &lease, &b) != 0)
            return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
        ++r->next_scratch_generation;
        r->scratch_in_use = 1;
        r->mode = 2;
    } else return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
    r->resolved_binding = b;
    r->resolved_run = *q;
    *out = b;
    return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_READY_V1;
}

int zn_native_graph_conv_runtime_init_v1(
    ZnNativeGraphConvRuntimeV1 *r, ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
    ZnNativeArenaConvLifecycleV1 *lifecycle, const ZnNativePlatformMappedSpanV1 *arena,
    const ZnNativePlatformMappedSpanV1 *scratch, const ZnNativeDirectIdsV2 *ids,
    const ZnNativePlatformMemoryOpsV1 *memory, void *memory_context, ZnNativeGraphConvHooksV2 *hooks)
{
    ZnNativePlatformMappedSpanV1 a, s;
    ZnNativeDirectIdsV2 id_copy;
    ZnNativePlatformMemoryOpsV1 ops;
    const void *objects[] = {r, owner, dispatch, lifecycle, hooks};
    const size_t sizes[] = {sizeof *r, sizeof *owner, sizeof *dispatch, sizeof *lifecycle, sizeof *hooks};
    size_t i, j;
    if (!r || r->magic || !owner || !dispatch || !lifecycle || !arena || !scratch || !ids || !memory || !hooks ||
        !owner->initialized || owner->fault || dispatch->fault || dispatch->epoch != owner->epoch ||
        dispatch->events != owner->events || !valid_mapping(arena) || !valid_mapping(scratch) ||
        !disjoint(arena->cpu_base, arena->cpu_bytes, scratch->cpu_base, scratch->cpu_bytes) ||
        !(arena->physical_base + arena->bytes <= scratch->physical_base ||
          scratch->physical_base + scratch->bytes <= arena->physical_base) ||
        !memory->cache_clean || !memory->barrier || !memory->invalidate_readback ||
        !ids->job_base || !ids->token_base || !ids->tag_base || !ids->load_timeout_cycles ||
        !ids->parameter_timeout_cycles || !ids->write_timeout_cycles || !ids->preaccept_timeout_cycles || ids->first_bank > 1)
        return -1;
    for (i = 0; i < sizeof objects/sizeof objects[0]; ++i) {
        if (!disjoint(objects[i], sizes[i], arena->cpu_base, arena->cpu_bytes) ||
            !disjoint(objects[i], sizes[i], scratch->cpu_base, scratch->cpu_bytes)) return -1;
        for (j = i+1; j < sizeof objects/sizeof objects[0]; ++j)
            if (!disjoint(objects[i], sizes[i], objects[j], sizes[j])) return -1;
    }
    a = *arena; s = *scratch; id_copy = *ids; ops = *memory;
    memset(r, 0, sizeof *r);
    r->arena = a; r->scratch = s; r->ids = id_copy;
    r->owner = owner; r->dispatch = dispatch; r->lifecycle = lifecycle;
    if (zn_native_direct_conv_runtime_hooks_init_v1(&r->direct, lifecycle, &a, &ops, memory_context, &r->direct_hooks) != 0 ||
        zn_native_feature_cache_init_v1(&r->view_cache, &ops, memory_context, release_view, r) != ZN_NATIVE_FEATURE_CACHE_V1_READY ||
        zn_native_view_conv_runtime_hooks_init_v1(&r->view, lifecycle, &r->view_cache, &a, &s, &r->view_hooks) != ZN_NATIVE_VIEW_CONV_RUNTIME_V1_READY)
        return -1;
    r->next_scratch_generation = 1;
    r->magic = GRAPH_RUNTIME_MAGIC;
    memset(hooks, 0, sizeof *hooks);
    hooks->context = r; hooks->check_leases = route_check; hooks->convert_views = route_convert;
    hooks->clean_source = route_clean; hooks->check_source_ready = route_ready; hooks->invalidate_output = route_invalidate;
    hooks->validate_and_publish = route_publish; hooks->drain_ready = route_drain;
    hooks->return_graph_read = route_return; hooks->release_scratch = route_finish;
    return 0;
}
