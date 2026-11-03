#include "native_feature_cache_v1.h"

#include "native_conv_command_v1.h"

#include <limits.h>
#include <string.h>

#define ZN_NFCV1_MAGIC UINT32_C(0x4E464331)
#define ZN_NFCV1_ADDRESS_LIMIT UINT64_C(0x100000000)

typedef struct ZnNfcv1Range {
    uint64_t begin;
    uint64_t end;
} ZnNfcv1Range;

typedef struct ZnNfcv1CpuRange {
    uintptr_t begin;
    uintptr_t end;
} ZnNfcv1CpuRange;

static int
zn_nfcv1_ref_equal(ZnRef a, ZnRef b)
{
    return a.slot == b.slot && a.tensor == b.tensor &&
           a.generation == b.generation;
}

static int
zn_nfcv1_request_equal(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index && a->operation == b->operation &&
           zn_nfcv1_ref_equal(a->ref, b->ref) && a->job == b->job;
}

static int
zn_nfcv1_command_equal(const ZnNativeConvCommand *a,
                       const ZnNativeConvCommand *b)
{
    uint32_t words_a[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t words_b[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t index;

    if (zn_native_conv_command_encode_v1(a, words_a) !=
            ZN_NATIVE_CONV_COMMAND_OK ||
        zn_native_conv_command_encode_v1(b, words_b) !=
            ZN_NATIVE_CONV_COMMAND_OK)
        return 0;
    for (index = 0; index < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++index)
        if (words_a[index] != words_b[index])
            return 0;
    return 1;
}

static int
zn_nfcv1_binding_equal(const ZnNativeGraphConvBindingV2 *a,
                       const ZnNativeGraphConvBindingV2 *b)
{
    uint8_t index;

    if (!a || !b || a->dispatch_epoch != b->dispatch_epoch ||
        a->dispatch_tag != b->dispatch_tag || a->event_index != b->event_index ||
        a->graph_read_count != b->graph_read_count ||
        !zn_nfcv1_ref_equal(a->destination_ref, b->destination_ref) ||
        a->scratch.epoch != b->scratch.epoch ||
        a->scratch.generation != b->scratch.generation ||
        a->scratch.base != b->scratch.base || a->scratch.bytes != b->scratch.bytes ||
        a->source_span.base != b->source_span.base ||
        a->source_span.bytes != b->source_span.bytes ||
        a->expected_cookie != b->expected_cookie ||
        a->expected_job_base != b->expected_job_base ||
        a->expected_token_base != b->expected_token_base ||
        a->expected_tag_base != b->expected_tag_base ||
        a->expected_tiles != b->expected_tiles ||
        memcmp(a->package_sha256, b->package_sha256,
               sizeof a->package_sha256) != 0 ||
        memcmp(a->checkpoint_sha256, b->checkpoint_sha256,
               sizeof a->checkpoint_sha256) != 0 ||
        memcmp(a->graph_sha256, b->graph_sha256,
               sizeof a->graph_sha256) != 0 ||
        !zn_nfcv1_command_equal(&a->command, &b->command))
        return 0;
    for (index = 0; index < a->graph_read_count; ++index)
        if (!zn_nfcv1_ref_equal(a->graph_read_refs[index],
                                b->graph_read_refs[index]))
            return 0;
    return 1;
}

static int
zn_nfcv1_mapped_span_equal(const ZnNativePlatformMappedSpanV1 *a,
                           const ZnNativePlatformMappedSpanV1 *b)
{
    return a && b && a->physical_base == b->physical_base &&
           a->bytes == b->bytes && a->cpu_base == b->cpu_base &&
           a->cpu_bytes == b->cpu_bytes;
}

static uint64_t
zn_nfcv1_end33(const ZnNativeConvEnd33 *end)
{
    return ((uint64_t)end->high << 32) | end->low;
}

static int
zn_nfcv1_physical_range(uint64_t begin, uint64_t bytes,
                        ZnNfcv1Range *out)
{
    if (!out || bytes == 0 || begin >= ZN_NFCV1_ADDRESS_LIMIT ||
        bytes > ZN_NFCV1_ADDRESS_LIMIT - begin)
        return 0;
    out->begin = begin;
    out->end = begin + bytes;
    return 1;
}

static int
zn_nfcv1_physical_overlap(ZnNfcv1Range a, ZnNfcv1Range b)
{
    return a.begin < b.end && b.begin < a.end;
}

static int
zn_nfcv1_cpu_range(const void *base, size_t bytes, ZnNfcv1CpuRange *out)
{
    uintptr_t begin;

    if (!base || !bytes || !out)
        return 0;
    begin = (uintptr_t)base;
    if ((uintmax_t)bytes > (uintmax_t)(UINTPTR_MAX - begin))
        return 0;
    out->begin = begin;
    out->end = begin + (uintptr_t)bytes;
    return 1;
}

static int
zn_nfcv1_cpu_overlap(ZnNfcv1CpuRange a, ZnNfcv1CpuRange b)
{
    return a.begin < b.end && b.begin < a.end;
}

static int
zn_nfcv1_state_outside_arena(const ZnNativeFeatureCacheV1 *cache,
                             const ZnNativePlatformMappedSpanV1 *arena)
{
    ZnNfcv1CpuRange state_range;
    ZnNfcv1CpuRange arena_range;

    return zn_nfcv1_cpu_range(cache, sizeof *cache, &state_range) &&
           arena && arena->cpu_base && arena->cpu_bytes != 0 &&
           zn_nfcv1_cpu_range(arena->cpu_base, arena->cpu_bytes, &arena_range) &&
           !zn_nfcv1_cpu_overlap(state_range, arena_range);
}

static uint8_t
zn_nfcv1_read_mask(uint8_t read_count)
{
    return read_count == 0 ? 0 :
        (uint8_t)((UINT32_C(1) << read_count) - UINT32_C(1));
}

static int
zn_nfcv1_request_is_active_run(const ZnNativeArenaConvLifecycleV1 *lifecycle,
                               const ZnRequest *request)
{
    return lifecycle && request && lifecycle->active &&
           request->operation == ZN_RUN &&
           zn_nfcv1_request_equal(request, &lifecycle->active_request) &&
           zn_nfcv1_request_equal(request, &lifecycle->last_run_request);
}

static int
zn_nfcv1_owner_prepared(const ZnNativeArenaConvLifecycleV1 *lifecycle,
                        const ZnRequest *request,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnNativeArenaOwnerV1 *owner;
    const ZnNativeArenaEventStateV1 *event_state;
    const ZnEvent *event;
    const ZnNativeArenaSlotV1 *destination_slot;
    uint8_t index;

    if (!lifecycle || !request || !binding || !lifecycle->owner ||
        !zn_nfcv1_request_is_active_run(lifecycle, request))
        return 0;
    owner = lifecycle->owner;
    if (!owner->initialized || owner->fault || !owner->events ||
        owner->epoch != request->epoch ||
        request->event_index >= owner->event_count ||
        request->job != &owner->events[request->event_index] ||
        !zn_nfcv1_binding_equal(&lifecycle->bridge.binding, binding) ||
        lifecycle->bridge.stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING ||
        lifecycle->run_started_recorded)
        return 0;

    event = request->job;
    event_state = &owner->event_state[request->event_index];
    if (event->operation != ZN_CONV || event->read_count == 0 ||
        event->read_count > ZN_NATIVE_GRAPH_CONV_MAX_READS_V2 ||
        binding->graph_read_count != event->read_count ||
        binding->dispatch_epoch != request->epoch ||
        binding->dispatch_tag != request->tag ||
        binding->event_index != request->event_index ||
        !zn_nfcv1_ref_equal(binding->destination_ref,
                            event->destination.ref) ||
        event_state->acquired_mask != zn_nfcv1_read_mask(event->read_count) ||
        event_state->returned_mask != 0 || event_state->retired_mask != 0 ||
        event_state->run_started || event_state->run_completed ||
        event_state->output_published || event_state->io_quiescent ||
        event_state->run_tag != 0 || !event_state->allocated)
        return 0;

    for (index = 0; index < event->read_count; ++index) {
        ZnRef ref = event->reads[index];
        const ZnNativeArenaSlotV1 *slot;
        if (!zn_nfcv1_ref_equal(binding->graph_read_refs[index], ref) ||
            ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
            return 0;
        slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_nfcv1_ref_equal(slot->ref, ref) || slot->reader_count == 0)
            return 0;
    }

    if (!event->has_destination || event->destination.ref.slot >=
            ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return 0;
    destination_slot = &owner->slots[event->destination.ref.slot];
    return destination_slot->state == ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
           zn_nfcv1_ref_equal(destination_slot->ref, event->destination.ref) &&
           destination_slot->region.address == event->destination.address &&
           destination_slot->bytes == event->destination.bytes &&
           destination_slot->reader_count == 0 &&
           destination_slot->io_count == 0;
}

static int
zn_nfcv1_validate_mappings(const ZnNativeFeatureCacheV1 *cache,
                           const ZnNativeGraphConvBindingV2 *binding,
                           const ZnEvent *event,
                           const ZnNativeRuntimeTensorMapV1 *destination)
{
    ZnNfcv1Range scratch_lease;
    ZnNfcv1Range destination_reservation;
    ZnNfcv1Range source_data;
    ZnNfcv1Range destination_data;
    ZnNfcv1CpuRange source_cpu;
    ZnNfcv1CpuRange destination_cpu;
    uint64_t scratch_end;
    uint64_t destination_end;
    uint64_t output_end;
    uint32_t line = ZN_NATIVE_FEATURE_CACHE_LINE_BYTES_V1;

    if (!cache || !binding || !event || !destination ||
        !cache->source_mapping.cpu_base ||
        cache->source_mapping.physical_base != binding->source_span.base ||
        cache->source_mapping.bytes != binding->source_span.bytes ||
        cache->source_mapping.bytes == 0 ||
        cache->source_mapping.bytes > cache->source_mapping.cpu_bytes ||
        cache->source_mapping.cpu_bytes != cache->source_mapping.bytes ||
        ((uintptr_t)cache->source_mapping.cpu_base % line) != 0 ||
        (cache->source_mapping.physical_base % line) != 0 ||
        (cache->source_mapping.bytes % line) != 0 ||
        destination->physical_address != event->destination.address ||
        destination->view.epoch != binding->dispatch_epoch ||
        !zn_nfcv1_ref_equal(destination->view.ref, binding->destination_ref) ||
        destination->view.data != destination->cpu_address ||
        destination->view.bytes != event->destination.bytes ||
        destination->view.channels != event->destination.channels ||
        destination->view.height != event->destination.height ||
        destination->view.width != event->destination.width ||
        !destination->cpu_address ||
        ((uintptr_t)destination->cpu_address % line) != 0 ||
        (destination->physical_address % line) != 0 ||
        (destination->view.bytes % line) != 0 ||
        !zn_nfcv1_physical_range(binding->scratch.base,
                                 binding->scratch.bytes, &scratch_lease) ||
        !zn_nfcv1_physical_range(
            binding->command.destination_reservation_region_begin,
            zn_nfcv1_end33(&binding->command.destination_reservation_region_end) -
                binding->command.destination_reservation_region_begin,
            &destination_reservation) ||
        !zn_nfcv1_physical_range(cache->source_mapping.physical_base,
                                 cache->source_mapping.bytes, &source_data) ||
        !zn_nfcv1_physical_range(destination->physical_address,
                                 destination->view.bytes, &destination_data))
        return 0;

    scratch_end = (uint64_t)binding->scratch.base + binding->scratch.bytes;
    destination_end = zn_nfcv1_end33(
        &binding->command.destination_reservation_region_end);
    output_end = (uint64_t)event->destination.address + event->destination.bytes;
    if (binding->scratch.epoch != binding->dispatch_epoch ||
        binding->scratch.generation == 0 || binding->scratch.bytes == 0 ||
        binding->source_span.base != binding->scratch.base ||
        binding->source_span.bytes == 0 ||
        binding->source_span.bytes > binding->scratch.bytes ||
        binding->command.source_base != binding->source_span.base ||
        binding->command.source_generation != binding->scratch.generation ||
        binding->command.source_lease_region_begin != binding->scratch.base ||
        zn_nfcv1_end33(&binding->command.source_lease_region_end) != scratch_end ||
        scratch_end > ZN_NFCV1_ADDRESS_LIMIT ||
        destination_reservation.begin !=
            binding->command.destination_reservation_region_begin ||
        destination_reservation.end != destination_end ||
        binding->command.destination_base != event->destination.address ||
        binding->command.destination_generation !=
            binding->destination_ref.generation ||
        destination_reservation.begin > event->destination.address ||
        destination_reservation.end < output_end ||
        output_end > ZN_NFCV1_ADDRESS_LIMIT ||
        !zn_nfcv1_cpu_range(cache->source_mapping.cpu_base,
                            cache->source_mapping.cpu_bytes, &source_cpu) ||
        !zn_nfcv1_cpu_range(destination->cpu_address,
                            destination->view.bytes, &destination_cpu) ||
        zn_nfcv1_physical_overlap(scratch_lease, destination_reservation) ||
        zn_nfcv1_physical_overlap(source_data, destination_data) ||
        zn_nfcv1_cpu_overlap(source_cpu, destination_cpu))
        return 0;

    return 1;
}

static int
zn_nfcv1_driver_result_matches(const ZnNativeConvDriverV2 *driver,
                               const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnNativeConvResultV2 *result;
    const ZnNativeConvCommand *command;
    const uint32_t required = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_DONE |
                              ZN_NC_STATUS_RESULT_VALID |
                              ZN_NC_STATUS_DRAIN_COMPLETE;
    const uint32_t forbidden = ZN_NC_STATUS_FAULT | ZN_NC_STATUS_ACTIVE |
                               ZN_NC_STATUS_NEEDS_DRAIN;

    if (!driver || !binding || !driver->result_verified ||
        driver->result_is_fault || !driver->ownership_held ||
        driver->state != ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT ||
        driver->expected_tiles != binding->expected_tiles ||
        !zn_nfcv1_command_equal(&driver->command, &binding->command) ||
        (driver->last_status & required) != required ||
        (driver->last_status & forbidden) != 0 ||
        driver->last_bridge_error != ZN_NC_BRIDGE_ERROR_NONE ||
        driver->last_backend_fault_code != 0)
        return 0;

    result = &driver->result;
    command = &binding->command;
    return result->request_cookie == command->request_cookie &&
           result->epoch == command->epoch && result->event == command->event &&
           result->model_crc32 == command->model_crc32 &&
           result->job_base == command->job_base &&
           result->token_base == command->token_base &&
           result->tag_base == command->tag_base &&
           result->destination_generation == command->destination_generation &&
           result->committed_tiles == binding->expected_tiles &&
           result->source_generation == command->source_generation;
}

static int
zn_nfcv1_driver_result_matches_after_ack(
    const ZnNativeConvDriverV2 *driver,
    const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnNativeConvResultV2 *result;
    const ZnNativeConvCommand *command;

    if (!driver || !binding || !driver->result_verified ||
        driver->result_is_fault || driver->ownership_held ||
        driver->state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        driver->expected_tiles != binding->expected_tiles ||
        !zn_nfcv1_command_equal(&driver->command, &binding->command))
        return 0;
    result = &driver->result;
    command = &binding->command;
    return result->request_cookie == command->request_cookie &&
           result->epoch == command->epoch && result->event == command->event &&
           result->model_crc32 == command->model_crc32 &&
           result->job_base == command->job_base &&
           result->token_base == command->token_base &&
           result->tag_base == command->tag_base &&
           result->destination_generation == command->destination_generation &&
           result->committed_tiles == binding->expected_tiles &&
           result->source_generation == command->source_generation;
}

static int
zn_nfcv1_owner_submitted(const ZnNativeFeatureCacheV1 *cache)
{
    const ZnNativeArenaEventStateV1 *event_state;
    const ZnNativeArenaSlotV1 *destination_slot;
    const ZnEvent *event;

    if (!cache || !cache->owner || !cache->lifecycle ||
        cache->binding.event_index >= cache->owner->event_count)
        return 0;
    event = &cache->owner->events[cache->binding.event_index];
    event_state = &cache->owner->event_state[cache->binding.event_index];
    destination_slot = &cache->owner->slots[cache->binding.destination_ref.slot];
    return cache->owner->initialized && !cache->owner->fault &&
           cache->owner->epoch == cache->binding.dispatch_epoch &&
           cache->lifecycle->owner == cache->owner &&
           cache->lifecycle->active && cache->lifecycle->run_started_recorded &&
           cache->lifecycle->active_request.operation == ZN_RUN &&
           cache->lifecycle->active_request.epoch == cache->binding.dispatch_epoch &&
           cache->lifecycle->active_request.tag == cache->binding.dispatch_tag &&
           cache->lifecycle->active_request.event_index == cache->binding.event_index &&
           cache->lifecycle->active_request.job == event &&
           cache->lifecycle->bridge.stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED &&
           event_state->run_started && !event_state->run_completed &&
           !event_state->output_published && !event_state->io_quiescent &&
           event_state->run_tag == cache->binding.dispatch_tag &&
           event_state->acquired_mask == zn_nfcv1_read_mask(event->read_count) &&
           event_state->returned_mask == 0 &&
           destination_slot->state == ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
           zn_nfcv1_ref_equal(destination_slot->ref,
                              cache->binding.destination_ref) &&
           destination_slot->io_count != 0;
}

static ZnNativeFeatureCacheCodeV1
zn_nfcv1_fail(ZnNativeFeatureCacheV1 *cache, int callback_status)
{
    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
    cache->callback_status = callback_status;
    return ZN_NATIVE_FEATURE_CACHE_V1_CACHE_FAILED;
}

static int
zn_nfcv1_metadata_disjoint(const ZnNativeFeatureCacheV1 *cache,
                           const ZnNativeArenaConvLifecycleV1 *lifecycle,
                           const ZnDispatch *dispatch,
                           const ZnRequest *request,
                           const ZnNativeGraphConvBindingV2 *binding,
                           const ZnNativePlatformMappedSpanV1 *source,
                           const ZnNativePlatformMappedSpanV1 *arena,
                           const ZnNativeRuntimeTensorMapV1 *destination)
{
    const void *items[] = {
        cache, lifecycle, dispatch, request, binding, source, arena
    };
    const size_t sizes[] = {
        sizeof *cache, sizeof *lifecycle, sizeof *dispatch, sizeof *request,
        sizeof *binding, sizeof *source, sizeof *arena
    };
    ZnNfcv1CpuRange source_data;
    ZnNfcv1CpuRange destination_data;
    size_t index;

    if (!zn_nfcv1_cpu_range(source->cpu_base, source->cpu_bytes, &source_data) ||
        !zn_nfcv1_cpu_range(destination->cpu_address,
                            destination->view.bytes, &destination_data))
        return 0;
    for (index = 0; index < sizeof items / sizeof items[0]; ++index) {
        ZnNfcv1CpuRange metadata;
        if (!zn_nfcv1_cpu_range(items[index], sizes[index], &metadata) ||
            zn_nfcv1_cpu_overlap(metadata, source_data) ||
            zn_nfcv1_cpu_overlap(metadata, destination_data))
            return 0;
    }
    return 1;
}

int
zn_native_feature_cache_init_v1(
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativePlatformMemoryOpsV1 *memory,
    void *memory_context,
    ZnNativeFeatureCacheReleaseScratchV1 release_scratch,
    void *release_context)
{
    if (!cache || cache->magic != 0 || !memory || !memory->cache_clean ||
        !memory->barrier || !memory->invalidate_readback || !release_scratch)
        return ZN_NATIVE_FEATURE_CACHE_V1_ARGUMENT;
    cache->magic = ZN_NFCV1_MAGIC;
    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY;
    cache->ops.memory = *memory;
    cache->ops.memory_context = memory_context;
    cache->ops.release_scratch = release_scratch;
    cache->ops.release_context = release_context;
    return ZN_NATIVE_FEATURE_CACHE_V1_READY;
}

ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_bind_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnDispatch *dispatch,
    const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding,
    const ZnNativePlatformMappedSpanV1 *source_mapping,
    const ZnNativePlatformMappedSpanV1 *arena_mapping)
{
    ZnNativeRuntimeTensorMapV1 destination;
    const ZnEvent *event;
    if (!cache || cache->magic != ZN_NFCV1_MAGIC || !lifecycle || !dispatch ||
        !request || !binding || !source_mapping || !arena_mapping)
        return ZN_NATIVE_FEATURE_CACHE_V1_ARGUMENT;
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED)
        return ZN_NATIVE_FEATURE_CACHE_V1_POISONED;
    if (cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY &&
        cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED) {
        if (cache->lifecycle == lifecycle &&
            zn_nfcv1_request_equal(&cache->run_request, request) &&
            zn_nfcv1_binding_equal(&cache->binding, binding) &&
            zn_nfcv1_mapped_span_equal(&cache->source_mapping, source_mapping) &&
            zn_nfcv1_mapped_span_equal(&cache->arena_mapping, arena_mapping))
            return ZN_NATIVE_FEATURE_CACHE_V1_READY;
        return ZN_NATIVE_FEATURE_CACHE_V1_STALE;
    }
    if (cache->transaction_count == UINT32_MAX ||
        !zn_nfcv1_state_outside_arena(cache, arena_mapping))
        return ZN_NATIVE_FEATURE_CACHE_V1_INVALID;

    memset(&cache->run_request, 0, sizeof cache->run_request);
    memset(&cache->binding, 0, sizeof cache->binding);
    memset(&cache->source_mapping, 0, sizeof cache->source_mapping);
    memset(&cache->arena_mapping, 0, sizeof cache->arena_mapping);
    memset(&cache->destination_mapping, 0, sizeof cache->destination_mapping);
    cache->lifecycle = lifecycle;
    cache->owner = lifecycle->owner;
    cache->run_request = *request;
    cache->binding = *binding;
    cache->source_mapping = *source_mapping;
    cache->arena_mapping = *arena_mapping;
    cache->step = 0;
    cache->callback_status = 0;
    ++cache->transaction_count;
    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_BOUND;

    if (!zn_nfcv1_owner_prepared(lifecycle, request, binding) ||
        !zn_nfcv1_mapped_span_equal(&cache->arena_mapping, arena_mapping) ||
        zn_native_conv_command_validate_v1(&binding->command) !=
            ZN_NATIVE_CONV_COMMAND_OK)
        goto invalid;
    if (zn_native_runtime_map_destination_v1(
            lifecycle->owner, dispatch, request, arena_mapping, &destination) != 0)
        goto invalid;
    cache->destination_mapping = destination;
    event = request->job;
    if (!zn_nfcv1_validate_mappings(cache, binding, event, &destination) ||
        !zn_nfcv1_metadata_disjoint(cache, lifecycle, dispatch, request, binding,
                                    source_mapping, arena_mapping, &destination))
        goto invalid;
    if (!zn_nfcv1_binding_equal(&lifecycle->bridge.binding, binding))
        goto stale;
    return ZN_NATIVE_FEATURE_CACHE_V1_READY;

invalid:
    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
    return ZN_NATIVE_FEATURE_CACHE_V1_INVALID;
stale:
    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
    return ZN_NATIVE_FEATURE_CACHE_V1_STALE;
}

ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_check_binding_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnEvent *event;
    const ZnNativeArenaEventStateV1 *event_state;

    if (!cache || cache->magic != ZN_NFCV1_MAGIC || !lifecycle || !request ||
        !binding)
        return ZN_NATIVE_FEATURE_CACHE_V1_ARGUMENT;
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED)
        return ZN_NATIVE_FEATURE_CACHE_V1_POISONED;
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY ||
        cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED ||
        lifecycle != cache->lifecycle || lifecycle->owner != cache->owner ||
        !zn_nfcv1_binding_equal(&cache->binding, binding) ||
        !zn_nfcv1_binding_equal(&lifecycle->bridge.binding, binding) ||
        !lifecycle->active ||
        !zn_nfcv1_request_equal(request, &lifecycle->active_request) ||
        request->epoch != cache->run_request.epoch ||
        request->event_index != cache->run_request.event_index ||
        request->job != cache->run_request.job ||
        cache->owner->fault || !cache->owner->initialized ||
        request->event_index >= cache->owner->event_count)
        return ZN_NATIVE_FEATURE_CACHE_V1_STALE;

    event = &cache->owner->events[request->event_index];
    event_state = &cache->owner->event_state[request->event_index];
    if (event != cache->run_request.job ||
        (event_state->run_tag != cache->binding.dispatch_tag &&
         !(request->operation == ZN_RUN &&
           lifecycle->bridge.stage ==
               ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING &&
           !lifecycle->run_started_recorded && event_state->run_tag == 0)) ||
        event_state->acquired_mask != zn_nfcv1_read_mask(event->read_count))
        return ZN_NATIVE_FEATURE_CACHE_V1_STALE;

    if (request->operation == ZN_RUN) {
        if (lifecycle->bridge.stage ==
                ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING &&
            (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_BOUND ||
             cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARING ||
             cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED))
            return zn_nfcv1_owner_prepared(lifecycle, request, binding) ?
                ZN_NATIVE_FEATURE_CACHE_V1_READY :
                ZN_NATIVE_FEATURE_CACHE_V1_ORDER;
        if (lifecycle->bridge.stage ==
                ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED &&
            (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED ||
             cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE))
            return zn_nfcv1_owner_submitted(cache) ?
                ZN_NATIVE_FEATURE_CACHE_V1_READY :
                ZN_NATIVE_FEATURE_CACHE_V1_ORDER;
        if (lifecycle->bridge.stage ==
                ZN_NATIVE_GRAPH_CONV_STAGE_V2_PUBLISH &&
            cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE &&
            zn_nfcv1_driver_result_matches_after_ack(
                &lifecycle->bridge.driver, binding))
            return ZN_NATIVE_FEATURE_CACHE_V1_READY;
        return ZN_NATIVE_FEATURE_CACHE_V1_ORDER;
    }
    if (request->operation == ZN_DRAIN) {
        return lifecycle->bridge.stage ==
                   ZN_NATIVE_GRAPH_CONV_STAGE_V2_RUN_ACKED &&
               event_state->run_acked && event_state->run_completed &&
               event_state->output_published && !event_state->io_quiescent &&
               cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE ?
            ZN_NATIVE_FEATURE_CACHE_V1_READY :
            ZN_NATIVE_FEATURE_CACHE_V1_ORDER;
    }
    if (request->operation == ZN_RETURN) {
        if (lifecycle->bridge.stage !=
                ZN_NATIVE_GRAPH_CONV_STAGE_V2_DRAIN_ACKED ||
            !event_state->drained || !event_state->io_quiescent ||
            cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE ||
            lifecycle->bridge.return_cursor >= binding->graph_read_count ||
            !zn_nfcv1_ref_equal(
                request->ref,
                binding->graph_read_refs[lifecycle->bridge.return_cursor]))
            return ZN_NATIVE_FEATURE_CACHE_V1_ORDER;
        return ZN_NATIVE_FEATURE_CACHE_V1_READY;
    }
    return ZN_NATIVE_FEATURE_CACHE_V1_STALE;
}

static int
zn_nfcv1_direct_source_clean_eligible(
    const ZnNativeFeatureCacheV1 *cache,
    const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnNativeArenaConvLifecycleV1 *lifecycle;
    const ZnNativeArenaOwnerV1 *owner;
    const ZnNativeArenaEventStateV1 *consumer_state;
    const ZnNativeArenaEventStateV1 *producer_state;
    const ZnNativeArenaSlotV1 *source_slot;
    const ZnEvent *consumer;
    const ZnEvent *producer = NULL;
    ZnRef source_ref;
    uint16_t producer_index = 0;
    uint16_t index;
    uint32_t matches = 0;
    uint64_t offset;
    uintptr_t arena_cpu;

    if (!cache || !binding || !cache->lifecycle || !cache->owner)
        return -1;
    lifecycle = cache->lifecycle;
    owner = cache->owner;
    if (lifecycle->fault || lifecycle->active_dispatch_snapshot.fault ||
        lifecycle->bridge.dispatch_failure_latched || owner->fault ||
        !owner->initialized || owner->epoch != binding->dispatch_epoch ||
        owner->epoch != cache->run_request.epoch ||
        binding->event_index >= owner->event_count ||
        binding->event_index >= ZN_NATIVE_ARENA_EVENT_COUNT_V1)
        return -1;

    consumer = &owner->events[binding->event_index];
    consumer_state = &owner->event_state[binding->event_index];
    if (consumer->operation != ZN_CONV || consumer->read_count != 1 ||
        binding->graph_read_count != 1 ||
        !zn_nfcv1_ref_equal(binding->graph_read_refs[0], consumer->reads[0]) ||
        !zn_nfcv1_owner_prepared(lifecycle, &cache->run_request, binding))
        return -1;

    source_ref = consumer->reads[0];
    if (source_ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return -1;
    source_slot = &owner->slots[source_ref.slot];
    if (source_slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
        !zn_nfcv1_ref_equal(source_slot->ref, source_ref) ||
        source_slot->reader_count == 0 || source_slot->io_count != 0 ||
        consumer_state->acquired_mask != UINT8_C(1) ||
        consumer_state->returned_mask != 0 || consumer_state->retired_mask != 0)
        return -1;

    if (source_ref.tensor == -1 && source_ref.slot == 0 &&
        source_ref.generation == 1)
        return 0;

    for (index = 0; index < binding->event_index; ++index) {
        const ZnEvent *candidate = &owner->events[index];
        if (candidate->has_destination &&
            zn_nfcv1_ref_equal(candidate->destination.ref, source_ref)) {
            producer = candidate;
            producer_index = index;
            ++matches;
        }
    }
    if (matches != 1 || !producer)
        return -1;
    if (producer->operation != ZN_CONV)
        return 0;
    if (!producer->has_destination ||
        !zn_nfcv1_ref_equal(producer->destination.ref, source_ref) ||
        producer->destination.address != source_slot->region.address ||
        producer->destination.bytes != source_slot->bytes ||
        source_slot->region.capacity_bytes < producer->destination.bytes)
        return -1;

    producer_state = &owner->event_state[producer_index];
    if (!producer_state->allocated || !producer_state->run_started ||
        !producer_state->run_acked || !producer_state->run_completed ||
        !producer_state->drained || !producer_state->io_quiescent ||
        producer_state->run_tag == 0) {
        return -1;
    }
    if (!producer_state->output_published)
        return -1;

    if (!cache->source_mapping.cpu_base ||
        cache->source_mapping.physical_base != producer->destination.address ||
        cache->source_mapping.bytes != producer->destination.bytes ||
        cache->source_mapping.cpu_bytes != producer->destination.bytes ||
        binding->source_span.base != producer->destination.address ||
        binding->source_span.bytes != producer->destination.bytes ||
        !cache->arena_mapping.cpu_base ||
        cache->arena_mapping.bytes != cache->arena_mapping.cpu_bytes ||
        cache->source_mapping.physical_base < cache->arena_mapping.physical_base)
        return -1;

    offset = cache->source_mapping.physical_base -
             cache->arena_mapping.physical_base;
    if (offset > cache->arena_mapping.bytes ||
        cache->source_mapping.bytes > cache->arena_mapping.bytes - offset)
        return -1;
    arena_cpu = (uintptr_t)cache->arena_mapping.cpu_base;
    if (offset > UINTPTR_MAX - arena_cpu ||
        (uintptr_t)cache->source_mapping.cpu_base != arena_cpu + (uintptr_t)offset)
        return -1;

    return 1;
}

static ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_prepare_impl_v1(
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativeGraphConvBindingV2 *binding,
    int direct_source_candidate)
{
    const ZnNativePlatformMemoryOpsV1 *memory;
    const ZnNativeRuntimeTensorMapV1 *destination;
    int status;

    if (!cache || cache->magic != ZN_NFCV1_MAGIC || !binding)
        return ZN_NATIVE_FEATURE_CACHE_V1_ARGUMENT;
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED)
        return ZN_NATIVE_FEATURE_CACHE_V1_POISONED;
    if (!zn_nfcv1_binding_equal(&cache->binding, binding)) {
        cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
        return ZN_NATIVE_FEATURE_CACHE_V1_STALE;
    }
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED ||
        cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE)
        return ZN_NATIVE_FEATURE_CACHE_V1_READY;
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_BOUND)
        cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARING;
    if (cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARING)
        return ZN_NATIVE_FEATURE_CACHE_V1_ORDER;
    if (!cache->lifecycle || !cache->lifecycle->active ||
        cache->lifecycle->active_request.operation != ZN_RUN ||
        !zn_nfcv1_request_equal(&cache->run_request,
                                &cache->lifecycle->active_request) ||
        !zn_nfcv1_owner_prepared(cache->lifecycle, &cache->run_request,
                                 binding)) {
        cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
        return ZN_NATIVE_FEATURE_CACHE_V1_STALE;
    }

    memory = &cache->ops.memory;
    destination = &cache->destination_mapping;
    while (cache->step < 5u) {
        switch (cache->step) {
        case 0:
            if (direct_source_candidate) {
                int eligible = zn_nfcv1_direct_source_clean_eligible(
                    cache, binding);
                if (eligible < 0) {
                    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
                    return ZN_NATIVE_FEATURE_CACHE_V1_STALE;
                }
                if (eligible > 0) {
                    ++cache->step;
                    continue;
                }
            }
            status = memory->cache_clean(cache->ops.memory_context,
                                         cache->source_mapping.cpu_base,
                                         cache->source_mapping.cpu_bytes);
            break;
        case 1:
            status = memory->cache_clean(cache->ops.memory_context,
                                         destination->cpu_address,
                                         destination->view.bytes);
            break;
        case 2:
            status = memory->barrier(cache->ops.memory_context);
            break;
        case 3:
            status = memory->invalidate_readback(cache->ops.memory_context,
                                                  destination->cpu_address,
                                                  destination->view.bytes);
            break;
        default:
            status = memory->barrier(cache->ops.memory_context);
            break;
        }
        if (status != 0)
            return zn_nfcv1_fail(cache, status);
        ++cache->step;
    }
    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED;
    return ZN_NATIVE_FEATURE_CACHE_V1_READY;
}

ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_prepare_v1(
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativeGraphConvBindingV2 *binding)
{
    return zn_native_feature_cache_prepare_impl_v1(cache, binding, 0);
}

ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_prepare_direct_source_candidate_v1(
    ZnNativeFeatureCacheV1 *cache,
    const ZnNativeGraphConvBindingV2 *binding)
{
    return zn_native_feature_cache_prepare_impl_v1(cache, binding, 1);
}

ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_check_source_ready_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeFeatureCacheCodeV1 code;

    code = zn_native_feature_cache_check_binding_v1(cache, lifecycle, request,
                                                    binding);
    if (code != ZN_NATIVE_FEATURE_CACHE_V1_READY)
        return code;
    if (request->operation != ZN_RUN ||
        lifecycle->bridge.stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING ||
        lifecycle->run_started_recorded ||
        !zn_nfcv1_owner_prepared(lifecycle, request, binding))
        return ZN_NATIVE_FEATURE_CACHE_V1_ORDER;
    return cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED ?
        ZN_NATIVE_FEATURE_CACHE_V1_READY : ZN_NATIVE_FEATURE_CACHE_V1_BUSY;
}

ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_make_output_visible_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeConvDriverV2 *driver;
    int status;

    if (!cache || cache->magic != ZN_NFCV1_MAGIC || !lifecycle || !binding)
        return ZN_NATIVE_FEATURE_CACHE_V1_ARGUMENT;
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED)
        return ZN_NATIVE_FEATURE_CACHE_V1_POISONED;
    if (!zn_nfcv1_binding_equal(&cache->binding, binding) ||
        lifecycle != cache->lifecycle || lifecycle->owner != cache->owner) {
        cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
        return ZN_NATIVE_FEATURE_CACHE_V1_STALE;
    }
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE)
        return ZN_NATIVE_FEATURE_CACHE_V1_READY;
    if (cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED ||
        !zn_nfcv1_owner_submitted(cache))
        return ZN_NATIVE_FEATURE_CACHE_V1_ORDER;
    driver = &lifecycle->bridge.driver;
    if (!zn_nfcv1_driver_result_matches(driver, binding))
        return ZN_NATIVE_FEATURE_CACHE_V1_BUSY;

    /* Exact Xilinx adapter cache_clean is FlushRange (clean+invalidate).
     * ACP can own dirty L2 output: invalidate-only loses it. Ownership,
     * result identity and drain have already passed above. */
    status = cache->ops.memory.cache_clean(
        cache->ops.memory_context, cache->destination_mapping.cpu_address,
        cache->destination_mapping.view.bytes);
    if (status != 0)
        return zn_nfcv1_fail(cache, status);
    status = cache->ops.memory.barrier(cache->ops.memory_context);
    if (status != 0)
        return zn_nfcv1_fail(cache, status);
    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE;
    cache->step = 0;
    return ZN_NATIVE_FEATURE_CACHE_V1_READY;
}

static int
zn_nfcv1_owner_released_reads(const ZnNativeFeatureCacheV1 *cache,
                              const ZnNativeArenaConvLifecycleV1 *lifecycle)
{
    const ZnNativeArenaOwnerV1 *owner;
    const ZnNativeArenaEventStateV1 *event_state;
    const ZnEvent *event;
    const ZnNativeConvDriverV2 *driver;
    const ZnNativeArenaSlotV1 *destination_slot;
    uint8_t read_mask;
    uint8_t index;

    if (!cache || !lifecycle || !cache->owner ||
        lifecycle->owner != cache->owner || !lifecycle->finishing ||
        lifecycle->fault || !lifecycle->run_started_recorded ||
        !lifecycle->publication_recorded || !lifecycle->quiescence_recorded ||
        lifecycle->bridge.stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED ||
        lifecycle->bridge.return_cursor != cache->binding.graph_read_count)
        return 0;
    owner = cache->owner;
    if (!owner->initialized || owner->fault ||
        cache->binding.event_index >= owner->event_count ||
        owner->epoch != cache->binding.dispatch_epoch)
        return 0;
    event = &owner->events[cache->binding.event_index];
    event_state = &owner->event_state[cache->binding.event_index];
    driver = &lifecycle->bridge.driver;
    read_mask = zn_nfcv1_read_mask(event->read_count);
    if (event != cache->run_request.job ||
        event_state->run_tag != cache->binding.dispatch_tag ||
        !event_state->run_started || !event_state->run_acked ||
        !event_state->run_completed || !event_state->output_published ||
        !event_state->drained || !event_state->io_quiescent ||
        event_state->acquired_mask != read_mask ||
        event_state->returned_mask != read_mask ||
        driver->state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(driver) ||
        !driver->result_verified || driver->result_is_fault ||
        !zn_nfcv1_driver_result_matches_after_ack(driver, &cache->binding))
        return 0;

    for (index = 0; index < event->read_count; ++index) {
        ZnRef ref = event->reads[index];
        const ZnNativeArenaSlotV1 *slot;
        if (!zn_nfcv1_ref_equal(ref, cache->binding.graph_read_refs[index]) ||
            ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
            return 0;
        slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_nfcv1_ref_equal(slot->ref, ref))
            return 0;
    }
    if (!event->has_destination ||
        !zn_nfcv1_ref_equal(event->destination.ref,
                            cache->binding.destination_ref) ||
        event->destination.ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return 0;
    destination_slot = &owner->slots[event->destination.ref.slot];
    return destination_slot->state == ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 &&
           zn_nfcv1_ref_equal(destination_slot->ref,
                              cache->binding.destination_ref) &&
           destination_slot->bytes == event->destination.bytes;
}

ZnNativeFeatureCacheCodeV1
zn_native_feature_cache_release_scratch_v1(
    ZnNativeFeatureCacheV1 *cache,
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnNativeGraphConvBindingV2 *binding)
{
    int status;

    if (!cache || cache->magic != ZN_NFCV1_MAGIC || !lifecycle || !binding)
        return ZN_NATIVE_FEATURE_CACHE_V1_ARGUMENT;
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED)
        return ZN_NATIVE_FEATURE_CACHE_V1_POISONED;
    if (!zn_nfcv1_binding_equal(&cache->binding, binding) ||
        lifecycle != cache->lifecycle || lifecycle->owner != cache->owner) {
        cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
        return ZN_NATIVE_FEATURE_CACHE_V1_STALE;
    }
    if (cache->stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED)
        return ZN_NATIVE_FEATURE_CACHE_V1_READY;
    if (cache->stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE ||
        !zn_nfcv1_owner_released_reads(cache, lifecycle))
        return ZN_NATIVE_FEATURE_CACHE_V1_ORDER;

    status = cache->ops.release_scratch(cache->ops.release_context,
                                        &cache->binding.scratch);
    if (status == 1)
        return ZN_NATIVE_FEATURE_CACHE_V1_BUSY;
    if (status != 0) {
        cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED;
        cache->callback_status = status;
        return ZN_NATIVE_FEATURE_CACHE_V1_CACHE_FAILED;
    }
    cache->stage = ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED;
    memset(&cache->source_mapping, 0, sizeof cache->source_mapping);
    return ZN_NATIVE_FEATURE_CACHE_V1_READY;
}

