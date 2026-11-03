#include "native_nonconv_runtime_hooks_v1.h"

#include <stdint.h>
#include <string.h>

#define ZN_NRH_ARENA_BASE_V1 UINT64_C(0x10000000)
#define ZN_NRH_ARENA_BYTES_V1 UINT64_C(5201920)
#define ZN_NRH_PHYSICAL_LIMIT_V1 UINT64_C(0x100000000)

static int
zn_nrh_ref_equal_v1(ZnRef left, ZnRef right)
{
    return left.generation == right.generation &&
           left.tensor == right.tensor && left.slot == right.slot;
}

static int
zn_nrh_request_equal_v1(const ZnRequest *left, const ZnRequest *right)
{
    return left && right && left->epoch == right->epoch &&
           left->tag == right->tag &&
           left->event_index == right->event_index &&
           left->operation == right->operation &&
           zn_nrh_ref_equal_v1(left->ref, right->ref) &&
           left->job == right->job;
}

static int
zn_nrh_same_event_v1(const ZnRequest *left, const ZnRequest *right)
{
    return left && right && left->epoch == right->epoch &&
           left->event_index == right->event_index && left->job == right->job;
}

static int
zn_nrh_cpu_span_valid_v1(const void *address, size_t bytes)
{
    uintptr_t begin = (uintptr_t)address;
    return address && bytes != 0 && bytes <= UINTPTR_MAX - begin;
}

static int
zn_nrh_physical_span_valid_v1(uint64_t address, uint64_t bytes)
{
    return address != 0 && bytes != 0 && address < ZN_NRH_PHYSICAL_LIMIT_V1 &&
           bytes <= ZN_NRH_PHYSICAL_LIMIT_V1 - address;
}

static int
zn_nrh_physical_overlap_v1(uint64_t left, uint64_t left_bytes,
                           uint64_t right, uint64_t right_bytes)
{
    return left < right + right_bytes && right < left + left_bytes;
}

static int
zn_nrh_cpu_overlap_v1(const void *left, size_t left_bytes,
                      const void *right, size_t right_bytes)
{
    uintptr_t left_start = (uintptr_t)left;
    uintptr_t right_start = (uintptr_t)right;
    return left_start < right_start + right_bytes &&
           right_start < left_start + left_bytes;
}

static int
zn_nrh_arena_valid_v1(const ZnNativePlatformMappedSpanV1 *arena)
{
    return arena && arena->physical_base == ZN_NRH_ARENA_BASE_V1 &&
           arena->bytes == ZN_NRH_ARENA_BYTES_V1 &&
           arena->cpu_bytes == ZN_NRH_ARENA_BYTES_V1 && arena->cpu_base &&
           (((uintptr_t)arena->cpu_base & 63u) == 0) &&
           zn_nrh_physical_span_valid_v1(arena->physical_base, arena->bytes) &&
           zn_nrh_cpu_span_valid_v1(arena->cpu_base, arena->cpu_bytes);
}

static int
zn_nrh_heads_valid_v1(const ZnNativePlatformMappedSpanV1 *arena,
                      const ZnNativePlatformMappedSpanV1 *heads,
                      uint8_t exclusive)
{
    if (!arena || !heads || exclusive != 1 || !heads->cpu_base ||
        heads->bytes < ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1 ||
        heads->cpu_bytes < heads->bytes ||
        (heads->physical_base & 63u) != 0 ||
        ((uintptr_t)heads->cpu_base & 63u) != 0 ||
        (ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1 & 63u) != 0 ||
        !zn_nrh_physical_span_valid_v1(heads->physical_base, heads->bytes) ||
        !zn_nrh_cpu_span_valid_v1(heads->cpu_base, heads->cpu_bytes))
        return 0;
    if (zn_nrh_physical_overlap_v1(heads->physical_base, heads->bytes,
                                   arena->physical_base, arena->bytes) ||
        zn_nrh_cpu_overlap_v1(heads->cpu_base, heads->cpu_bytes,
                              arena->cpu_base, arena->cpu_bytes))
        return 0;
    return 1;
}

static int
zn_nrh_map_range_v1(const ZnNativePlatformMappedSpanV1 *mapping,
                    uint32_t physical_address, uint32_t bytes,
                    uint8_t **cpu_address)
{
    uint64_t offset;
    uintptr_t cpu_base;

    if (!mapping || !cpu_address || !mapping->cpu_base || bytes == 0 ||
        (physical_address & 63u) != 0 || (bytes & 63u) != 0 ||
        (mapping->physical_base & 63u) != 0 ||
        ((uintptr_t)mapping->cpu_base & 63u) != 0 ||
        !zn_nrh_physical_span_valid_v1(mapping->physical_base,
                                       mapping->bytes) ||
        !zn_nrh_cpu_span_valid_v1(mapping->cpu_base, mapping->cpu_bytes))
        return 0;
    if ((uint64_t)physical_address < mapping->physical_base)
        return 0;
    offset = (uint64_t)physical_address - mapping->physical_base;
    cpu_base = (uintptr_t)mapping->cpu_base;
    if (offset > mapping->bytes || bytes > mapping->bytes - offset ||
        offset > mapping->cpu_bytes || bytes > mapping->cpu_bytes - offset ||
        offset > UINTPTR_MAX - cpu_base ||
        bytes > UINTPTR_MAX - (cpu_base + (uintptr_t)offset))
        return 0;
    *cpu_address = (uint8_t *)(cpu_base + (uintptr_t)offset);
    return 1;
}

static int
zn_nrh_dispatch_request_valid_v1(
    const ZnNativeNonConvRuntimeHooksV1 *runtime,
    const ZnRequest *request, uint8_t operation)
{
    const ZnNativeArenaOwnerV1 *owner;
    const ZnDispatch *dispatch;

    if (!runtime || !request || !runtime->owner || !runtime->dispatch)
        return 0;
    owner = runtime->owner;
    dispatch = runtime->dispatch;
    return owner->initialized && !owner->fault && !owner->complete &&
           dispatch->events && dispatch->pending && !dispatch->fault &&
           !dispatch->done && dispatch->events == owner->events &&
           dispatch->epoch == owner->epoch && dispatch->count == owner->event_count &&
           request->epoch == owner->epoch && request->operation == operation &&
           request->event_index < dispatch->count &&
           dispatch->cursor == request->event_index &&
           dispatch->phase == operation &&
           request->job == &dispatch->events[request->event_index] &&
           zn_nrh_request_equal_v1(request, &dispatch->request);
}

static uint8_t
zn_nrh_count_mask_v1(uint8_t count)
{
    return count == 0 ? 0 : (uint8_t)((UINT32_C(1) << count) - 1u);
}

static int
zn_nrh_previous_run_complete_v1(
    const ZnNativeNonConvRuntimeHooksV1 *runtime)
{
    const ZnRequest *run;
    const ZnNativeArenaEventStateV1 *state;
    const ZnEvent *event;

    if (!runtime || !runtime->run_active || !runtime->owner)
        return 0;
    run = &runtime->run_request;
    if (!run->job || run->event_index >= runtime->owner->event_count)
        return 0;
    event = run->job;
    state = &runtime->owner->event_state[run->event_index];
    return state->run_acked && state->drained &&
           state->returned_mask == zn_nrh_count_mask_v1(event->read_count) &&
           state->retired_mask == zn_nrh_count_mask_v1(event->retire_count);
}

static int
zn_nrh_lifecycle_run_matches_v1(
    const ZnNativeNonConvRuntimeHooksV1 *runtime,
    const ZnRequest *request)
{
    return runtime && request && runtime->lifecycle &&
           runtime->lifecycle->owner == runtime->owner &&
           runtime->lifecycle->active &&
           runtime->lifecycle->run_request.operation == ZN_RUN &&
           zn_nrh_request_equal_v1(&runtime->lifecycle->run_request, request);
}

static int
zn_nrh_begin_run_v1(ZnNativeNonConvRuntimeHooksV1 *runtime,
                    const ZnRequest *request)
{
    if (!runtime || !zn_nrh_dispatch_request_valid_v1(runtime, request, ZN_RUN) ||
        !zn_nrh_lifecycle_run_matches_v1(runtime, request))
        return 0;
    if (runtime->run_active) {
        if (zn_nrh_request_equal_v1(&runtime->run_request, request))
            return 1;
        if (runtime->run_request.event_index == request->event_index ||
            !zn_nrh_previous_run_complete_v1(runtime))
            return 0;
        runtime->run_active = 0;
        runtime->output_cache_visible = 0;
        runtime->output_publish_ready = 0;
        runtime->heads_cache_visible = 0;
        memset(&runtime->run_request, 0, sizeof runtime->run_request);
    }
    runtime->run_request = *request;
    runtime->operator_call_baseline = runtime->lifecycle->operator_call_count;
    runtime->run_active = 1;
    runtime->output_cache_visible = 0;
    runtime->output_publish_ready = 0;
    runtime->heads_cache_visible = 0;
    return 1;
}

static int
zn_nrh_run_matches_v1(const ZnNativeNonConvRuntimeHooksV1 *runtime,
                      const ZnRequest *request)
{
    return runtime && runtime->run_active && request &&
           zn_nrh_dispatch_request_valid_v1(runtime, request, ZN_RUN) &&
           zn_nrh_lifecycle_run_matches_v1(runtime, request) &&
           zn_nrh_request_equal_v1(&runtime->run_request, request);
}

static int
zn_nrh_operator_delta_v1(const ZnNativeNonConvRuntimeHooksV1 *runtime,
                         uint32_t delta)
{
    return runtime && runtime->lifecycle &&
           runtime->operator_call_baseline <= UINT32_MAX - delta &&
           runtime->lifecycle->operator_call_count ==
               runtime->operator_call_baseline + delta;
}

static int
zn_nrh_map_source_exact_v1(ZnNativeNonConvRuntimeHooksV1 *runtime,
                           const ZnRequest *request, uint8_t read_index,
                           uint32_t expected_address, uint32_t expected_bytes,
                           ZnNativeArenaNonConvSourceV1 *source)
{
    ZnNativeRuntimeTensorMapV1 mapped;
    const ZnNativeArenaSlotV1 *slot;
    ZnRef expected_ref;
    uint8_t *capacity_address;

    if (!runtime || !request || !request->job || !source ||
        read_index >= request->job->read_count ||
        !zn_nrh_run_matches_v1(runtime, request))
        return 0;
    expected_ref = request->job->reads[read_index];
    if (expected_ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return 0;
    slot = &runtime->owner->slots[expected_ref.slot];
    memset(&mapped, 0, sizeof mapped);
    if (zn_native_runtime_map_read_v1(runtime->owner, runtime->dispatch,
                                      request, read_index, &runtime->arena,
                                      &mapped) != 0 ||
        mapped.physical_address != expected_address ||
        mapped.view.bytes != expected_bytes ||
        mapped.view.epoch != request->epoch ||
        !zn_nrh_ref_equal_v1(mapped.view.ref, expected_ref) ||
        mapped.view.data != mapped.cpu_address ||
        !zn_nrh_map_range_v1(&runtime->arena, slot->region.address,
                             slot->region.capacity_bytes,
                             &capacity_address) ||
        capacity_address != mapped.cpu_address ||
        slot->region.address != expected_address ||
        slot->bytes != expected_bytes ||
        slot->region.capacity_bytes == 0 ||
        slot->bytes > slot->region.capacity_bytes)
        return 0;
    memset(source, 0, sizeof *source);
    source->physical_address = mapped.physical_address;
    source->view = mapped.view;
    return 1;
}

static int
zn_nrh_output_exact_v1(ZnNativeNonConvRuntimeHooksV1 *runtime,
                       const ZnRequest *request,
                       const ZnNativeArenaNonConvOutputV1 *output,
                       uint32_t output_bytes)
{
    const ZnEvent *event;

    if (!runtime || !request || !request->job || !output ||
        !zn_nrh_run_matches_v1(runtime, request))
        return 0;
    event = request->job;
    if (event->has_destination) {
        const ZnNativeArenaSlotV1 *slot;
        const ZnNativeArenaEventStateV1 *state;
        uint8_t *mapped_data;

        if (event->destination.ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1 ||
            event->destination.bytes != output_bytes)
            return 0;
        slot = &runtime->owner->slots[event->destination.ref.slot];
        state = &runtime->owner->event_state[request->event_index];
        /* The runtime destination mapper is pre-RUN only: RUN owns the slot's
         * I/O lease. Revalidate that in-flight lease and the original mapping. */
        if (!state->allocated || !state->run_started ||
            slot->state != ZN_NATIVE_ARENA_SLOT_RESERVED_V1 ||
            !zn_nrh_ref_equal_v1(slot->ref, event->destination.ref) ||
            slot->reader_count != 0 || slot->io_count == 0 ||
            slot->region.address != event->destination.address ||
            slot->bytes != output_bytes ||
            slot->region.capacity_bytes == 0 ||
            slot->bytes > slot->region.capacity_bytes ||
            !zn_nrh_map_range_v1(&runtime->arena, event->destination.address,
                                 slot->region.capacity_bytes, &mapped_data) ||
            output->physical_address != event->destination.address ||
            output->data != mapped_data ||
            output->capacity_bytes != slot->region.capacity_bytes)
            return 0;
        return 1;
    }

    if (event->operation != ZN_HEADS || request->event_index != 72 ||
        event->event != 163 || output_bytes != ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1 ||
        output->physical_address != 0 || output->data != runtime->heads.cpu_base ||
        output->capacity_bytes != ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1 ||
        runtime->heads.bytes < ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1 ||
        runtime->heads.cpu_bytes < ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1)
        return 0;
    return 1;
}

static int
zn_nrh_map_source_v1(void *opaque, const ZnRequest *request,
                     uint8_t read_index, uint32_t expected_address,
                     uint32_t expected_bytes,
                     ZnNativeArenaNonConvSourceV1 *source)
{
    ZnNativeNonConvRuntimeHooksV1 *runtime = opaque;

    if (!runtime || !source || !zn_nrh_begin_run_v1(runtime, request) ||
        !zn_nrh_operator_delta_v1(runtime, 0) ||
        !zn_nrh_map_source_exact_v1(runtime, request, read_index,
                                    expected_address, expected_bytes, source))
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
zn_nrh_source_visible_v1(void *opaque, const ZnRequest *request,
                         uint8_t read_index,
                         const ZnNativeArenaNonConvSourceV1 *source)
{
    ZnNativeNonConvRuntimeHooksV1 *runtime = opaque;
    ZnNativeArenaNonConvSourceV1 current;
    const ZnNativeArenaSlotV1 *slot;
    uint8_t *cpu_address;

    if (!runtime || !source || read_index >= 7 ||
        !zn_nrh_run_matches_v1(runtime, request) ||
        !zn_nrh_operator_delta_v1(runtime, 0) ||
        !zn_nrh_map_source_exact_v1(runtime, request, read_index,
                                    source->physical_address,
                                    (uint32_t)source->view.bytes, &current) ||
        source->physical_address != current.physical_address ||
        source->view.data != current.view.data ||
        source->view.bytes != current.view.bytes ||
        source->view.epoch != current.view.epoch ||
        !zn_nrh_ref_equal_v1(source->view.ref, current.view.ref) ||
        source->view.channels != current.view.channels ||
        source->view.height != current.view.height ||
        source->view.width != current.view.width)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;

    slot = &runtime->owner->slots[source->view.ref.slot];
    if (!zn_nrh_map_range_v1(&runtime->arena, slot->region.address,
                             slot->region.capacity_bytes, &cpu_address) ||
        cpu_address != source->view.data ||
        runtime->cache_ops.invalidate_readback(
            runtime->cache_context, cpu_address,
            slot->region.capacity_bytes) != 0 ||
        runtime->cache_ops.barrier(runtime->cache_context) != 0)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;

    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
zn_nrh_map_output_v1(void *opaque, const ZnRequest *request,
                     uint32_t expected_address, uint32_t output_bytes,
                     ZnNativeArenaNonConvOutputV1 *output)
{
    ZnNativeNonConvRuntimeHooksV1 *runtime = opaque;

    if (!runtime || !output || !zn_nrh_begin_run_v1(runtime, request) ||
        !zn_nrh_operator_delta_v1(runtime, 0))
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    memset(output, 0, sizeof *output);
    if (request->job->has_destination) {
        ZnNativeRuntimeTensorMapV1 mapped;
        const ZnNativeArenaSlotV1 *slot;

        if (expected_address != request->job->destination.address ||
            output_bytes != request->job->destination.bytes ||
            request->job->destination.ref.slot >=
                ZN_NATIVE_ARENA_SLOT_COUNT_V1)
            return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
        memset(&mapped, 0, sizeof mapped);
        if (zn_native_runtime_map_destination_v1(
                runtime->owner, runtime->dispatch, request, &runtime->arena,
                &mapped) != 0)
            return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
        slot = &runtime->owner->slots[request->job->destination.ref.slot];
        output->physical_address = mapped.physical_address;
        output->data = mapped.cpu_address;
        output->capacity_bytes = slot->region.capacity_bytes;
    } else {
        if (request->job->operation != ZN_HEADS ||
            request->event_index != 72 || request->job->event != 163 ||
            expected_address != 0 ||
            output_bytes != ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1 ||
            !zn_nrh_heads_valid_v1(&runtime->arena, &runtime->heads,
                                   runtime->heads_exclusive))
            return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
        output->physical_address = 0;
        output->data = runtime->heads.cpu_base;
        output->capacity_bytes = ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1;
    }
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
zn_nrh_clean_output_v1(void *opaque, const ZnRequest *request,
                       const ZnNativeArenaNonConvOutputV1 *output,
                       uint32_t output_bytes)
{
    ZnNativeNonConvRuntimeHooksV1 *runtime = opaque;
    uint8_t *cpu_address;
    const ZnNativeArenaSlotV1 *slot;

    if (!runtime || !request || !request->job || !request->job->has_destination ||
        !zn_nrh_run_matches_v1(runtime, request) ||
        !runtime->lifecycle->run_started || !runtime->lifecycle->computed ||
        !zn_nrh_operator_delta_v1(runtime, 1) ||
        !zn_nrh_output_exact_v1(runtime, request, output, output_bytes) ||
        runtime->output_cache_visible ||
        request->job->destination.ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;

    slot = &runtime->owner->slots[request->job->destination.ref.slot];
    if (!zn_nrh_map_range_v1(&runtime->arena, slot->region.address,
                             slot->region.capacity_bytes, &cpu_address) ||
        cpu_address != output->data ||
        runtime->cache_ops.cache_clean(runtime->cache_context, cpu_address,
                                       slot->region.capacity_bytes) != 0 ||
        runtime->cache_ops.barrier(runtime->cache_context) != 0)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    runtime->output_cache_visible = 1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
zn_nrh_publish_output_v1(void *opaque, const ZnRequest *request,
                         const ZnNativeArenaNonConvOutputV1 *output,
                         uint32_t output_bytes)
{
    ZnNativeNonConvRuntimeHooksV1 *runtime = opaque;
    const ZnNativeArenaEventStateV1 *state;

    if (!runtime || !request || !request->job || !request->job->has_destination ||
        !zn_nrh_run_matches_v1(runtime, request) ||
        !runtime->lifecycle->run_started || !runtime->lifecycle->computed ||
        !runtime->lifecycle->output_cleaned ||
        !zn_nrh_operator_delta_v1(runtime, 1) ||
        !runtime->output_cache_visible || runtime->output_publish_ready ||
        !zn_nrh_output_exact_v1(runtime, request, output, output_bytes))
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    state = &runtime->owner->event_state[request->event_index];
    if (state->run_completed || state->output_published || state->run_acked)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    runtime->output_publish_ready = 1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
zn_nrh_drain_ready_v1(void *opaque, const ZnRequest *request,
                      ZnNativeArenaQuiescenceEvidenceV1 *evidence)
{
    ZnNativeNonConvRuntimeHooksV1 *runtime = opaque;
    const ZnNativeArenaEventStateV1 *state;
    const ZnEvent *event;

    if (!runtime || !request || !evidence ||
        !zn_nrh_dispatch_request_valid_v1(runtime, request, ZN_DRAIN) ||
        !runtime->run_active ||
        !zn_nrh_same_event_v1(&runtime->run_request, request) ||
        !runtime->lifecycle || !runtime->lifecycle->active ||
        !runtime->lifecycle->run_acked || !runtime->lifecycle->computed ||
        !runtime->lifecycle->completion_recorded ||
        !zn_nrh_operator_delta_v1(runtime, 1))
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;

    event = request->job;
    state = &runtime->owner->event_state[request->event_index];
    if (state->run_tag != runtime->run_request.tag || !state->run_started ||
        !state->run_completed || !state->run_acked || state->io_quiescent ||
        state->drained ||
        (event->has_destination &&
         (!state->output_published || !runtime->output_publish_ready ||
          !runtime->output_cache_visible || !runtime->lifecycle->output_cleaned)) ||
        (!event->has_destination &&
         (event->operation != ZN_HEADS || state->output_published ||
          runtime->lifecycle->output_cleaned || runtime->heads_cache_visible ||
          runtime->lifecycle->output.physical_address != 0 ||
          runtime->lifecycle->output.data != runtime->heads.cpu_base ||
          runtime->lifecycle->output.capacity_bytes !=
              ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1 ||
          !zn_nrh_heads_valid_v1(&runtime->arena, &runtime->heads,
                                 runtime->heads_exclusive) ||
          runtime->cache_ops.cache_clean(
              runtime->cache_context, runtime->heads.cpu_base,
              ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1) != 0 ||
          runtime->cache_ops.barrier(runtime->cache_context) != 0)))
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;

    if (!event->has_destination)
        runtime->heads_cache_visible = 1;
    memset(evidence, 0, sizeof *evidence);
    evidence->epoch = request->epoch;
    evidence->run_tag = runtime->run_request.tag;
    evidence->event_index = request->event_index;
    evidence->all_read_io_quiet = 1;
    evidence->all_write_io_quiet = 1;
    evidence->driver_terminal = 1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
zn_nrh_return_graph_read_v1(void *opaque, const ZnRequest *request,
                            uint8_t read_index, uint32_t physical_address,
                            ZnRef ref)
{
    ZnNativeNonConvRuntimeHooksV1 *runtime = opaque;
    const ZnNativeArenaEventStateV1 *state;
    const ZnNativeArenaSlotV1 *slot;
    const ZnEvent *event;
    uint8_t bit;

    if (!runtime || !request || !request->job ||
        !zn_nrh_dispatch_request_valid_v1(runtime, request, ZN_RETURN) ||
        !runtime->run_active ||
        !zn_nrh_same_event_v1(&runtime->run_request, request) ||
        !runtime->lifecycle || !runtime->lifecycle->active ||
        !runtime->lifecycle->quiescence_recorded ||
        read_index != runtime->dispatch->index ||
        read_index >= request->job->read_count)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;

    event = request->job;
    if (!zn_nrh_ref_equal_v1(ref, event->reads[read_index]) ||
        !zn_nrh_ref_equal_v1(request->ref, event->reads[read_index]) ||
        ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    state = &runtime->owner->event_state[request->event_index];
    slot = &runtime->owner->slots[ref.slot];
    bit = (uint8_t)(UINT32_C(1) << read_index);
    if (!state->drained || !state->io_quiescent || !state->run_acked ||
        (state->acquired_mask & bit) == 0 || (state->returned_mask & bit) != 0 ||
        slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
        !zn_nrh_ref_equal_v1(slot->ref, ref) || slot->reader_count == 0 ||
        slot->io_count != 0 || slot->region.address != physical_address)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

int
zn_native_nonconv_runtime_hooks_init_v1(
    ZnNativeNonConvRuntimeHooksV1 *runtime,
    ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
    ZnNativeArenaNonConvLifecycleV1 *lifecycle,
    const ZnNativePlatformMappedSpanV1 *arena,
    const ZnNativePlatformMappedSpanV1 *heads,
    uint8_t heads_exclusive,
    const ZnNativePlatformMemoryOpsV1 *cache_ops, void *cache_context,
    ZnNativeArenaNonConvHooksV1 *hooks)
{
    ZnNativeNonConvRuntimeHooksV1 candidate;
    ZnNativeArenaNonConvHooksV1 candidate_hooks;

    if (!runtime || !owner || !dispatch || !lifecycle || !arena || !heads ||
        !cache_ops || !hooks || !owner->initialized || owner->fault ||
        owner->complete || !dispatch->events || dispatch->fault || dispatch->done ||
        dispatch->events != owner->events ||
        dispatch->epoch != owner->epoch || dispatch->count != owner->event_count ||
        !zn_nrh_arena_valid_v1(arena) ||
        !zn_nrh_heads_valid_v1(arena, heads, heads_exclusive) ||
        !cache_ops->invalidate_readback || !cache_ops->cache_clean ||
        !cache_ops->barrier)
        return -1;

    memset(&candidate, 0, sizeof candidate);
    candidate.owner = owner;
    candidate.dispatch = dispatch;
    candidate.lifecycle = lifecycle;
    candidate.arena = *arena;
    candidate.heads = *heads;
    candidate.heads_exclusive = 1;
    candidate.cache_ops = *cache_ops;
    candidate.cache_context = cache_context;

    memset(&candidate_hooks, 0, sizeof candidate_hooks);
    candidate_hooks.map_source = zn_nrh_map_source_v1;
    candidate_hooks.source_visible = zn_nrh_source_visible_v1;
    candidate_hooks.map_output = zn_nrh_map_output_v1;
    candidate_hooks.clean_output = zn_nrh_clean_output_v1;
    candidate_hooks.publish_output = zn_nrh_publish_output_v1;
    candidate_hooks.drain_ready = zn_nrh_drain_ready_v1;
    candidate_hooks.return_graph_read = zn_nrh_return_graph_read_v1;

    *runtime = candidate;
    candidate_hooks.context = runtime;
    *hooks = candidate_hooks;
    return 0;
}

static int
zn_nrh_result_outputs_disjoint_v1(
    const ZnNativeNonConvRuntimeHooksV1 *runtime,
    const uint8_t **data, size_t *bytes)
{
    if (!zn_nrh_cpu_span_valid_v1(data, sizeof *data) ||
        !zn_nrh_cpu_span_valid_v1(bytes, sizeof *bytes) ||
        zn_nrh_cpu_overlap_v1(data, sizeof *data, bytes, sizeof *bytes) ||
        zn_nrh_cpu_overlap_v1(data, sizeof *data, runtime, sizeof *runtime) ||
        zn_nrh_cpu_overlap_v1(bytes, sizeof *bytes, runtime, sizeof *runtime) ||
        zn_nrh_cpu_overlap_v1(data, sizeof *data, runtime->owner,
                              sizeof *runtime->owner) ||
        zn_nrh_cpu_overlap_v1(bytes, sizeof *bytes, runtime->owner,
                              sizeof *runtime->owner) ||
        zn_nrh_cpu_overlap_v1(data, sizeof *data, runtime->dispatch,
                              sizeof *runtime->dispatch) ||
        zn_nrh_cpu_overlap_v1(bytes, sizeof *bytes, runtime->dispatch,
                              sizeof *runtime->dispatch) ||
        zn_nrh_cpu_overlap_v1(data, sizeof *data, runtime->lifecycle,
                              sizeof *runtime->lifecycle) ||
        zn_nrh_cpu_overlap_v1(bytes, sizeof *bytes, runtime->lifecycle,
                              sizeof *runtime->lifecycle) ||
        zn_nrh_cpu_overlap_v1(data, sizeof *data, runtime->arena.cpu_base,
                              runtime->arena.cpu_bytes) ||
        zn_nrh_cpu_overlap_v1(bytes, sizeof *bytes, runtime->arena.cpu_base,
                              runtime->arena.cpu_bytes) ||
        zn_nrh_cpu_overlap_v1(data, sizeof *data, runtime->heads.cpu_base,
                              ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1) ||
        zn_nrh_cpu_overlap_v1(bytes, sizeof *bytes, runtime->heads.cpu_base,
                              ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1))
        return 0;
    return 1;
}

int
zn_native_nonconv_runtime_heads_result_v1(
    const ZnNativeNonConvRuntimeHooksV1 *runtime,
    const uint8_t **data, size_t *bytes)
{
    const ZnNativeArenaEventStateV1 *state;
    const ZnEvent *event;
    const uint8_t *candidate_data;
    size_t candidate_bytes;

    if (!runtime || !data || !bytes || !runtime->owner || !runtime->dispatch ||
        !runtime->lifecycle || runtime->owner->fault || runtime->dispatch->fault ||
        !runtime->owner->initialized || !runtime->owner->complete ||
        !runtime->dispatch->done ||
        runtime->dispatch->pending ||
        !runtime->dispatch->events ||
        runtime->dispatch->events != runtime->owner->events ||
        runtime->dispatch->epoch != runtime->owner->epoch ||
        runtime->dispatch->count != runtime->owner->event_count ||
        runtime->owner->event_count != ZN_NATIVE_ARENA_EVENT_COUNT_V1 ||
        runtime->dispatch->cursor != runtime->dispatch->count ||
        runtime->owner->events != runtime->dispatch->events ||
        runtime->lifecycle->owner != runtime->owner ||
        !runtime->lifecycle->active || !runtime->lifecycle->run_acked ||
        !runtime->lifecycle->quiescence_recorded ||
        !runtime->lifecycle->computed ||
        !runtime->lifecycle->completion_recorded ||
        !runtime->run_active || !runtime->heads_cache_visible ||
        !zn_nrh_operator_delta_v1(runtime, 1) ||
        !zn_nrh_heads_valid_v1(&runtime->arena, &runtime->heads,
                               runtime->heads_exclusive) ||
        !zn_nrh_result_outputs_disjoint_v1(runtime, data, bytes) ||
        runtime->run_request.operation != ZN_RUN ||
        runtime->run_request.epoch != runtime->owner->epoch ||
        runtime->run_request.event_index != 72 ||
        runtime->run_request.job != &runtime->owner->events[72])
        return -1;

    event = runtime->run_request.job;
    state = &runtime->owner->event_state[72];
    if (event->operation != ZN_HEADS || event->event != 163 ||
        event->has_destination || state->run_tag != runtime->run_request.tag ||
        !state->run_started || !state->run_completed || !state->run_acked ||
        !state->io_quiescent || !state->drained || state->output_published ||
        state->returned_mask != zn_nrh_count_mask_v1(event->read_count) ||
        state->retired_mask != zn_nrh_count_mask_v1(event->retire_count) ||
        runtime->lifecycle->output.physical_address != 0 ||
        runtime->lifecycle->output.data != runtime->heads.cpu_base ||
        runtime->lifecycle->output.capacity_bytes !=
            ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1)
        return -1;

    candidate_data = runtime->heads.cpu_base;
    candidate_bytes = ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1;
    *data = candidate_data;
    *bytes = candidate_bytes;
    return 0;
}
