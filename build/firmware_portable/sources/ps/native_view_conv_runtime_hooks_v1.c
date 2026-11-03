#include "native_view_conv_runtime_hooks_v1.h"

#include "native_runtime_maps_v1.h"
#include "native_view_bindings_v1.h"

#include <limits.h>
#include <string.h>

#define ZN_NVRV1_ADDRESS_LIMIT UINT64_C(0x100000000)

typedef struct ZnNvrv1Range {
    uint64_t begin;
    uint64_t end;
} ZnNvrv1Range;

typedef struct ZnNvrv1CpuRange {
    uintptr_t begin;
    uintptr_t end;
} ZnNvrv1CpuRange;

static int
zn_nvrv1_ref_equal(ZnRef a, ZnRef b)
{
    return a.slot == b.slot && a.tensor == b.tensor &&
           a.generation == b.generation;
}

static int
zn_nvrv1_request_equal(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index &&
           a->operation == b->operation && zn_nvrv1_ref_equal(a->ref, b->ref) &&
           a->job == b->job;
}

static int
zn_nvrv1_event_equal(const ZnEvent *a, const ZnEvent *b)
{
    uint8_t index;

    if (!a || !b || a->event != b->event ||
        a->tile_first != b->tile_first || a->tile_count != b->tile_count ||
        a->compute_node != b->compute_node || a->operation != b->operation ||
        a->read_count != b->read_count || a->retire_count != b->retire_count ||
        a->has_destination != b->has_destination)
        return 0;
    if (a->has_destination &&
        (a->destination.address != b->destination.address ||
         a->destination.bytes != b->destination.bytes ||
         a->destination.channels != b->destination.channels ||
         a->destination.height != b->destination.height ||
         a->destination.width != b->destination.width ||
         !zn_nvrv1_ref_equal(a->destination.ref, b->destination.ref)))
        return 0;
    for (index = 0; index < a->read_count; ++index)
        if (!zn_nvrv1_ref_equal(a->reads[index], b->reads[index]))
            return 0;
    for (index = 0; index < a->retire_count; ++index)
        if (!zn_nvrv1_ref_equal(a->retired[index], b->retired[index]))
            return 0;
    return 1;
}

static int
zn_nvrv1_cpu_range(const void *base, size_t bytes, ZnNvrv1CpuRange *out)
{
    uintptr_t begin;

    if (!base || bytes == 0 || !out)
        return 0;
    begin = (uintptr_t)base;
    if ((uintmax_t)bytes > (uintmax_t)(UINTPTR_MAX - begin))
        return 0;
    out->begin = begin;
    out->end = begin + (uintptr_t)bytes;
    return 1;
}

static int
zn_nvrv1_cpu_overlap(ZnNvrv1CpuRange a, ZnNvrv1CpuRange b)
{
    return a.begin < b.end && b.begin < a.end;
}

static int
zn_nvrv1_physical_range(const ZnNativePlatformMappedSpanV1 *mapping,
                         ZnNvrv1Range *out)
{
    if (!mapping || !out || !mapping->cpu_base || mapping->bytes == 0 ||
        mapping->cpu_bytes < mapping->bytes ||
        mapping->physical_base >= ZN_NVRV1_ADDRESS_LIMIT ||
        mapping->bytes > ZN_NVRV1_ADDRESS_LIMIT - mapping->physical_base ||
        (mapping->physical_base & UINT64_C(63)) != 0 ||
        (mapping->bytes & UINT64_C(63)) != 0 ||
        ((uintptr_t)mapping->cpu_base & (uintptr_t)63u) != 0)
        return 0;
    out->begin = mapping->physical_base;
    out->end = mapping->physical_base + mapping->bytes;
    return 1;
}

static int
zn_nvrv1_make_source_mapping(
    const ZnNativeViewConvRuntimeV1 *runtime,
    const ZnNativeGraphConvBindingV2 *binding,
    ZnNativePlatformMappedSpanV1 *source_mapping)
{
    const ZnNativePlatformMappedSpanV1 *pool;
    uint64_t offset64;
    size_t offset;

    if (!runtime || !binding || !source_mapping)
        return 0;
    pool = &runtime->scratch_mapping;
    if (!pool->cpu_base || binding->scratch.bytes == 0 ||
        binding->source_span.bytes == 0 ||
        binding->source_span.base != binding->scratch.base ||
        binding->source_span.bytes > binding->scratch.bytes ||
        binding->scratch.base < pool->physical_base)
        return 0;
    offset64 = (uint64_t)binding->scratch.base - pool->physical_base;
    if (offset64 > pool->bytes || binding->scratch.bytes > pool->bytes - offset64 ||
        offset64 > pool->cpu_bytes ||
        binding->source_span.bytes > pool->cpu_bytes - (size_t)offset64 ||
        offset64 > (uint64_t)SIZE_MAX)
        return 0;
    offset = (size_t)offset64;
    if (((uintptr_t)(pool->cpu_base + offset) & (uintptr_t)63u) != 0)
        return 0;

    source_mapping->physical_base = binding->source_span.base;
    source_mapping->bytes = binding->source_span.bytes;
    source_mapping->cpu_base = pool->cpu_base + offset;
    source_mapping->cpu_bytes = binding->source_span.bytes;
    return 1;
}

static int
zn_nvrv1_view_equal(const ZnNativeViewSourceV1 *a,
                    const ZnNativeViewSourceV1 *b)
{
    return a && b && a->data == b->data && a->bytes == b->bytes &&
           a->epoch == b->epoch && zn_nvrv1_ref_equal(a->ref, b->ref) &&
           a->channels == b->channels && a->height == b->height &&
           a->width == b->width;
}

static int
zn_nvrv1_source_range_is_metadata_free(
    ZnNvrv1CpuRange range, const ZnNativeViewConvRuntimeV1 *runtime,
    const ZnRequest *request, const ZnNativeGraphConvBindingV2 *binding)
{
    const void *objects[] = {
        runtime, runtime->lifecycle, runtime->lifecycle->owner,
        runtime->cache, &runtime->lifecycle->active_dispatch_snapshot,
        request, binding, &runtime->arena_mapping, &runtime->scratch_mapping,
        runtime->sources, &runtime->cache->destination_mapping
    };
    const size_t sizes[] = {
        sizeof *runtime, sizeof *runtime->lifecycle,
        sizeof *runtime->lifecycle->owner, sizeof *runtime->cache,
        sizeof runtime->lifecycle->active_dispatch_snapshot,
        sizeof *request, sizeof *binding, sizeof runtime->arena_mapping,
        sizeof runtime->scratch_mapping, sizeof runtime->sources,
        sizeof runtime->cache->destination_mapping
    };
    size_t index;

    for (index = 0; index < sizeof objects / sizeof objects[0]; ++index) {
        ZnNvrv1CpuRange metadata;
        if (!zn_nvrv1_cpu_range(objects[index], sizes[index], &metadata) ||
            zn_nvrv1_cpu_overlap(range, metadata))
            return 0;
    }
    return 1;
}

static int
zn_nvrv1_invalidate_sources(
    ZnNativeViewConvRuntimeV1 *runtime, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNvrv1CpuRange source_ranges[ZN_NATIVE_VIEW_CONV_MAX_READS_V1];
    ZnNvrv1CpuRange destination_range;
    ZnNvrv1CpuRange scratch_range;
    uint8_t index;
    uintptr_t arena_cpu;
    uint64_t arena_offset;
    uint32_t line = ZN_NATIVE_FEATURE_CACHE_LINE_BYTES_V1;
    const ZnNativeArenaOwnerV1 *owner;
    const ZnNativePlatformMemoryOpsV1 *memory;

    if (!runtime || !runtime->lifecycle || !runtime->cache || !request ||
        !binding || !runtime->lifecycle->owner ||
        runtime->source_count != binding->graph_read_count ||
        !runtime->arena_mapping.cpu_base ||
        !zn_nvrv1_cpu_range(runtime->cache->destination_mapping.cpu_address,
                            runtime->cache->destination_mapping.view.bytes,
                            &destination_range) ||
        !zn_nvrv1_cpu_range(runtime->cache->source_mapping.cpu_base,
                            runtime->cache->source_mapping.cpu_bytes,
                            &scratch_range))
        return 0;

    owner = runtime->lifecycle->owner;
    memory = &runtime->cache->ops.memory;
    arena_cpu = (uintptr_t)runtime->arena_mapping.cpu_base;
    memset(source_ranges, 0, sizeof source_ranges);
    for (index = 0; index < binding->graph_read_count; ++index) {
        ZnNativeRuntimeTensorMapV1 mapped;
        ZnNativeViewSourceV1 *retained = &runtime->sources[index];
        ZnRef ref = request->job->reads[index];
        const ZnNativeArenaSlotV1 *slot;
        ZnNvrv1CpuRange source_range;
        uint8_t bit = (uint8_t)(UINT32_C(1) << index);
        uintptr_t source_cpu;
        int duplicate = 0;
        uint8_t prior;

        if (ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1 ||
            !zn_nvrv1_ref_equal(ref, binding->graph_read_refs[index]) ||
            zn_native_runtime_map_read_v1(
                owner, &runtime->lifecycle->active_dispatch_snapshot,
                request, index, &runtime->arena_mapping, &mapped) != 0 ||
            !zn_nvrv1_view_equal(retained, &mapped.view))
            return 0;
        slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_nvrv1_ref_equal(slot->ref, ref) || slot->reader_count == 0 ||
            slot->io_count != 0 || slot->bytes != mapped.view.bytes ||
            slot->region.capacity_bytes < slot->bytes ||
            mapped.view.bytes == 0 || (mapped.view.bytes % line) != 0 ||
            (slot->region.address % line) != 0 ||
            (slot->region.capacity_bytes % line) != 0 ||
            (owner->event_state[request->event_index].acquired_mask & bit) == 0 ||
            (owner->event_state[request->event_index].returned_mask & bit) != 0 ||
            slot->region.address < runtime->arena_mapping.physical_base)
            return 0;

        arena_offset = (uint64_t)slot->region.address -
                       runtime->arena_mapping.physical_base;
        if (arena_offset > runtime->arena_mapping.bytes ||
            slot->region.capacity_bytes >
                runtime->arena_mapping.bytes - arena_offset ||
            arena_offset > runtime->arena_mapping.cpu_bytes ||
            slot->region.capacity_bytes >
                runtime->arena_mapping.cpu_bytes - (size_t)arena_offset ||
            arena_offset > (uint64_t)SIZE_MAX)
            return 0;
        source_cpu = arena_cpu + (uintptr_t)arena_offset;
        if ((source_cpu & (uintptr_t)(line - 1u)) != 0 ||
            (uintptr_t)mapped.cpu_address != source_cpu ||
            !zn_nvrv1_cpu_range((const void *)source_cpu,
                                slot->region.capacity_bytes, &source_range) ||
            zn_nvrv1_cpu_overlap(source_range, destination_range) ||
            zn_nvrv1_cpu_overlap(source_range, scratch_range) ||
            !zn_nvrv1_source_range_is_metadata_free(
                source_range, runtime, request, binding))
            return 0;

        for (prior = 0; prior < index; ++prior) {
            if (zn_nvrv1_cpu_overlap(source_range, source_ranges[prior])) {
                if (!zn_nvrv1_ref_equal(ref, request->job->reads[prior]) ||
                    source_range.begin != source_ranges[prior].begin ||
                    source_range.end != source_ranges[prior].end)
                    return 0;
                duplicate = 1;
                break;
            }
        }
        source_ranges[index] = source_range;
        if (!duplicate && memory->invalidate_readback(
                runtime->cache->ops.memory_context,
                (void *)source_cpu, mapped.view.bytes) != 0)
            return 0;
    }

    return memory->barrier(runtime->cache->ops.memory_context) == 0;
}

static int
zn_nvrv1_callback_code(ZnNativeFeatureCacheCodeV1 code)
{
    if (code == ZN_NATIVE_FEATURE_CACHE_V1_READY)
        return 0;
    if (code == ZN_NATIVE_FEATURE_CACHE_V1_BUSY)
        return 1;
    return -1;
}

static int
zn_nvrv1_check_binding(ZnNativeViewConvRuntimeV1 *runtime,
                       const ZnRequest *request,
                       const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeFeatureCacheCodeV1 code;

    if (!runtime || !runtime->active || !runtime->lifecycle || !runtime->cache ||
        !runtime->lifecycle->active || !request || !binding)
        return -1;
    code = zn_native_feature_cache_check_binding_v1(
        runtime->cache, runtime->lifecycle, request, binding);
    return zn_nvrv1_callback_code(code);
}

static int
zn_nvrv1_check_leases(void *context, const ZnRequest *request,
                      const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeViewConvRuntimeV1 *runtime =
        (ZnNativeViewConvRuntimeV1 *)context;
    ZnNativePlatformMappedSpanV1 source_mapping;
    ZnNativeRuntimeTensorMapV1 mapped;
    uint8_t index;
    ZnNativeFeatureCacheCodeV1 code;

    if (!runtime || !runtime->lifecycle || !runtime->cache || !request ||
        !binding || !runtime->lifecycle->active ||
        !zn_nvrv1_request_equal(request, &runtime->lifecycle->active_request))
        return -1;
    if (runtime->active)
        return zn_nvrv1_check_binding(runtime, request, binding);
    if (request->operation != ZN_RUN ||
        (runtime->cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY &&
         runtime->cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED) ||
        !runtime->lifecycle->owner || !request->job ||
        !zn_nvrv1_event_equal(request->job,
                              zn_native_view_event_v1(request->event_index)) ||
        binding->graph_read_count != request->job->read_count ||
        binding->graph_read_count == 0 ||
        binding->graph_read_count > ZN_NATIVE_VIEW_CONV_MAX_READS_V1)
        return -1;

    /* A view event with missing sources returns INVALID before any write;
     * generated direct/non-view events return 1 and must fail closed here. */
    if (zn_native_view_input_v1(request, NULL, 0, NULL, 0) != -1)
        return -1;
    if (!zn_nvrv1_make_source_mapping(runtime, binding, &source_mapping))
        return -1;

    memset(runtime->sources, 0, sizeof runtime->sources);
    for (index = 0; index < binding->graph_read_count; ++index) {
        if (zn_native_runtime_map_read_v1(
                runtime->lifecycle->owner,
                &runtime->lifecycle->active_dispatch_snapshot, request, index,
                &runtime->arena_mapping, &mapped) != 0 ||
            !zn_nvrv1_ref_equal(mapped.view.ref,
                                 binding->graph_read_refs[index]))
            return -1;
        runtime->sources[index] = mapped.view;
    }
    runtime->source_count = binding->graph_read_count;
    code = zn_native_feature_cache_bind_v1(
        runtime->cache, runtime->lifecycle,
        &runtime->lifecycle->active_dispatch_snapshot, request, binding,
        &source_mapping, &runtime->arena_mapping);
    if (code != ZN_NATIVE_FEATURE_CACHE_V1_READY) {
        memset(runtime->sources, 0, sizeof runtime->sources);
        runtime->source_count = 0;
        return -1;
    }
    runtime->run_request = *request;
    runtime->converted = 0;
    runtime->active = 1;
    return 0;
}

static int
zn_nvrv1_convert_views(void *context, const ZnRequest *request,
                       const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeViewConvRuntimeV1 *runtime =
        (ZnNativeViewConvRuntimeV1 *)context;
    ZnNativeFeatureCacheCodeV1 cache_code;
    int code;

    if (!runtime || !runtime->lifecycle || !runtime->cache || !request ||
        !binding || request->operation != ZN_RUN)
        return -1;
    cache_code = zn_native_feature_cache_check_binding_v1(
        runtime->cache, runtime->lifecycle, request, binding);
    if (cache_code != ZN_NATIVE_FEATURE_CACHE_V1_READY)
        return zn_nvrv1_callback_code(cache_code);
    if (runtime->converted)
        return 0;
    if (runtime->source_invalidation_started)
        return -1;
    if (runtime->source_count != binding->graph_read_count ||
        !zn_nvrv1_request_equal(request, &runtime->run_request))
        return -1;

    runtime->source_invalidation_started = 1;
    if (!zn_nvrv1_invalidate_sources(runtime, request, binding))
        return -1;

    code = zn_native_view_input_v1(
        request, runtime->sources, runtime->source_count,
        runtime->cache->source_mapping.cpu_base,
        (size_t)runtime->cache->source_mapping.bytes);
    if (code != 0)
        return -1;
    runtime->converted = 1;
    return 0;
}

static int
zn_nvrv1_clean_source(void *context,
                      const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeViewConvRuntimeV1 *runtime =
        (ZnNativeViewConvRuntimeV1 *)context;
    if (!runtime || !runtime->lifecycle || !runtime->cache ||
        !runtime->lifecycle->active ||
        !runtime->converted ||
        zn_nvrv1_check_binding(runtime, &runtime->lifecycle->active_request,
                                binding) != 0)
        return -1;
    return zn_nvrv1_callback_code(
        zn_native_feature_cache_prepare_v1(runtime->cache, binding));
}

static int
zn_nvrv1_check_source_ready(void *context, const ZnRequest *request,
                            const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeViewConvRuntimeV1 *runtime =
        (ZnNativeViewConvRuntimeV1 *)context;
    if (!runtime || !runtime->lifecycle || !runtime->cache ||
        !runtime->converted)
        return -1;
    return zn_nvrv1_callback_code(
        zn_native_feature_cache_check_source_ready_v1(
            runtime->cache, runtime->lifecycle, request, binding));
}

static int
zn_nvrv1_invalidate_output(void *context,
                           const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeViewConvRuntimeV1 *runtime =
        (ZnNativeViewConvRuntimeV1 *)context;
    if (!runtime || !runtime->lifecycle || !runtime->cache ||
        !runtime->lifecycle->active)
        return -1;
    return zn_nvrv1_callback_code(
        zn_native_feature_cache_make_output_visible_v1(
            runtime->cache, runtime->lifecycle, binding));
}

static int
zn_nvrv1_validate_and_publish(void *context,
                              const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeViewConvRuntimeV1 *runtime =
        (ZnNativeViewConvRuntimeV1 *)context;
    if (!runtime || !runtime->lifecycle || !runtime->cache ||
        !runtime->lifecycle->active || !binding ||
        runtime->cache->stage !=
            ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE)
        return -1;
    return zn_nvrv1_check_binding(runtime, &runtime->lifecycle->active_request,
                                   binding);
}

static int
zn_nvrv1_drain_ready(void *context, const ZnRequest *request,
                     const ZnNativeGraphConvBindingV2 *binding)
{
    return zn_nvrv1_check_binding(
        (ZnNativeViewConvRuntimeV1 *)context, request, binding);
}

static int
zn_nvrv1_return_graph_read(void *context, const ZnRequest *request,
                           const ZnNativeGraphConvBindingV2 *binding,
                           uint8_t read_index)
{
    if (!request || !request->job || read_index >= request->job->read_count ||
        !zn_nvrv1_ref_equal(request->ref, request->job->reads[read_index]))
        return -1;
    return zn_nvrv1_check_binding(
        (ZnNativeViewConvRuntimeV1 *)context, request, binding);
}

static int
zn_nvrv1_release_scratch(void *context,
                         const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeViewConvRuntimeV1 *runtime =
        (ZnNativeViewConvRuntimeV1 *)context;
    ZnNativeFeatureCacheCodeV1 code;

    if (!runtime || !runtime->active || !runtime->lifecycle || !runtime->cache ||
        !runtime->lifecycle->finishing || !binding)
        return -1;
    code = zn_native_feature_cache_release_scratch_v1(
        runtime->cache, runtime->lifecycle, binding);
    if (code != ZN_NATIVE_FEATURE_CACHE_V1_READY)
        return zn_nvrv1_callback_code(code);
    memset(&runtime->run_request, 0, sizeof runtime->run_request);
    memset(runtime->sources, 0, sizeof runtime->sources);
    runtime->source_count = 0;
    runtime->source_invalidation_started = 0;
    runtime->converted = 0;
    runtime->active = 0;
    return 0;
}

ZnNativeViewConvRuntimeCodeV1
zn_native_view_conv_runtime_hooks_init_v1(
    ZnNativeViewConvRuntimeV1 *runtime,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativePlatformMappedSpanV1 *arena_mapping,
    const ZnNativePlatformMappedSpanV1 *scratch_mapping,
    ZnNativeGraphConvHooksV2 *hooks)
{
    ZnNvrv1Range arena_physical;
    ZnNvrv1Range scratch_physical;
    ZnNvrv1CpuRange arena_cpu;
    ZnNvrv1CpuRange scratch_cpu;
    ZnNvrv1CpuRange runtime_cpu;
    ZnNvrv1CpuRange lifecycle_cpu;
    ZnNvrv1CpuRange cache_cpu;
    ZnNvrv1CpuRange hooks_cpu;

    if (!runtime || !lifecycle || !cache || !arena_mapping ||
        !scratch_mapping || !hooks)
        return ZN_NATIVE_VIEW_CONV_RUNTIME_V1_ARGUMENT;
    if (!zn_nvrv1_physical_range(arena_mapping, &arena_physical) ||
        !zn_nvrv1_physical_range(scratch_mapping, &scratch_physical) ||
        !zn_nvrv1_cpu_range(arena_mapping->cpu_base,
                            arena_mapping->cpu_bytes, &arena_cpu) ||
        !zn_nvrv1_cpu_range(scratch_mapping->cpu_base,
                            scratch_mapping->cpu_bytes, &scratch_cpu) ||
        !zn_nvrv1_cpu_range(runtime, sizeof *runtime, &runtime_cpu) ||
        !zn_nvrv1_cpu_range(lifecycle, sizeof *lifecycle, &lifecycle_cpu) ||
        !zn_nvrv1_cpu_range(cache, sizeof *cache, &cache_cpu) ||
        !zn_nvrv1_cpu_range(hooks, sizeof *hooks, &hooks_cpu) ||
        arena_mapping->cpu_bytes != arena_mapping->bytes ||
        zn_nvrv1_cpu_overlap(arena_cpu, scratch_cpu) ||
        !(arena_physical.end <= scratch_physical.begin ||
          scratch_physical.end <= arena_physical.begin) ||
        zn_nvrv1_cpu_overlap(runtime_cpu, arena_cpu) ||
        zn_nvrv1_cpu_overlap(runtime_cpu, scratch_cpu) ||
        zn_nvrv1_cpu_overlap(lifecycle_cpu, arena_cpu) ||
        zn_nvrv1_cpu_overlap(lifecycle_cpu, scratch_cpu) ||
        zn_nvrv1_cpu_overlap(cache_cpu, arena_cpu) ||
        zn_nvrv1_cpu_overlap(cache_cpu, scratch_cpu) ||
        zn_nvrv1_cpu_overlap(hooks_cpu, arena_cpu) ||
        zn_nvrv1_cpu_overlap(hooks_cpu, scratch_cpu) ||
        zn_nvrv1_cpu_overlap(runtime_cpu, lifecycle_cpu) ||
        zn_nvrv1_cpu_overlap(runtime_cpu, cache_cpu) ||
        zn_nvrv1_cpu_overlap(runtime_cpu, hooks_cpu) ||
        zn_nvrv1_cpu_overlap(cache_cpu, lifecycle_cpu) ||
        zn_nvrv1_cpu_overlap(cache_cpu, hooks_cpu) ||
        zn_nvrv1_cpu_overlap(lifecycle_cpu, hooks_cpu) ||
        cache->ops.memory.cache_clean == NULL ||
        cache->ops.memory.barrier == NULL ||
        cache->ops.memory.invalidate_readback == NULL ||
        cache->ops.release_scratch == NULL ||
        (cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY &&
         cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED))
        return ZN_NATIVE_VIEW_CONV_RUNTIME_V1_INVALID;

    memset(runtime, 0, sizeof *runtime);
    runtime->lifecycle = lifecycle;
    runtime->cache = cache;
    runtime->arena_mapping = *arena_mapping;
    runtime->scratch_mapping = *scratch_mapping;

    memset(hooks, 0, sizeof *hooks);
    hooks->context = runtime;
    hooks->check_leases = zn_nvrv1_check_leases;
    hooks->convert_views = zn_nvrv1_convert_views;
    hooks->clean_source = zn_nvrv1_clean_source;
    hooks->check_source_ready = zn_nvrv1_check_source_ready;
    hooks->invalidate_output = zn_nvrv1_invalidate_output;
    hooks->validate_and_publish = zn_nvrv1_validate_and_publish;
    hooks->drain_ready = zn_nvrv1_drain_ready;
    hooks->return_graph_read = zn_nvrv1_return_graph_read;
    hooks->release_scratch = zn_nvrv1_release_scratch;
    return ZN_NATIVE_VIEW_CONV_RUNTIME_V1_READY;
}

