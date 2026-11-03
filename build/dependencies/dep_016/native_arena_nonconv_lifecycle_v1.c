#include "native_arena_nonconv_lifecycle_v1.h"

#include "native_nonconv_v1.h"

#include <stdint.h>
#include <string.h>

static int
zn_anl_ref_equal_v1(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
zn_anl_request_equal_v1(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index &&
           a->operation == b->operation && zn_anl_ref_equal_v1(a->ref, b->ref) &&
           a->job == b->job;
}

static int
zn_anl_event_equal_v1(const ZnEvent *a, const ZnEvent *b)
{
    uint8_t index;

    if (!a || !b || a->event != b->event ||
        a->tile_first != b->tile_first || a->tile_count != b->tile_count ||
        a->compute_node != b->compute_node || a->operation != b->operation ||
        a->read_count != b->read_count || a->retire_count != b->retire_count ||
        a->has_destination != b->has_destination ||
        a->destination.address != b->destination.address ||
        a->destination.bytes != b->destination.bytes ||
        a->destination.channels != b->destination.channels ||
        a->destination.height != b->destination.height ||
        a->destination.width != b->destination.width ||
        !zn_anl_ref_equal_v1(a->destination.ref, b->destination.ref))
        return 0;
    for (index = 0; index < a->read_count; ++index) {
        if (!zn_anl_ref_equal_v1(a->reads[index], b->reads[index]))
            return 0;
    }
    for (index = 0; index < a->retire_count; ++index) {
        if (!zn_anl_ref_equal_v1(a->retired[index], b->retired[index]))
            return 0;
    }
    return 1;
}

static int
zn_anl_pending_matches_v1(const ZnDispatch *dispatch,
                          const ZnRequest *request,
                          const ZnNativeArenaOwnerV1 *owner)
{
    return dispatch && request && owner && dispatch->events &&
           dispatch->pending && !dispatch->fault && owner->initialized &&
           !owner->fault && dispatch->events == owner->events &&
           dispatch->epoch == owner->epoch && dispatch->count == owner->event_count &&
           request->event_index < dispatch->count &&
           dispatch->cursor == request->event_index &&
           dispatch->phase == request->operation &&
           request->epoch == dispatch->epoch &&
           request->job == &dispatch->events[request->event_index] &&
           zn_anl_request_equal_v1(request, &dispatch->request);
}

static uint8_t
zn_anl_read_mask_v1(uint8_t count)
{
    return count == 0 ? 0 : (uint8_t)((UINT32_C(1) << count) - 1u);
}

static uint8_t
zn_anl_retire_mask_v1(uint8_t count)
{
    return count == 0 ? 0 : (uint8_t)((UINT32_C(1) << count) - 1u);
}

static size_t
zn_anl_packed_bytes_v1(uint16_t channels, uint16_t height, uint16_t width)
{
    uint64_t channel_groups = ((uint64_t)channels + 3u) / 4u;
    uint64_t width_groups = ((uint64_t)width + 15u) / 16u;
    uint64_t bytes = channel_groups * height * width_groups * 64u;

    return bytes <= SIZE_MAX ? (size_t)bytes : 0;
}

static int
zn_anl_span_v1(const void *address, size_t bytes)
{
    return address && bytes != 0 &&
           bytes <= UINTPTR_MAX - (uintptr_t)address;
}

static int
zn_anl_overlap_v1(const void *left, size_t left_bytes,
                  const void *right, size_t right_bytes)
{
    uintptr_t left_start = (uintptr_t)left;
    uintptr_t right_start = (uintptr_t)right;

    return left_start < right_start + right_bytes &&
           right_start < left_start + left_bytes;
}

static ZnNativeArenaNonConvLifecycleCodeV1
zn_anl_owner_code_v1(ZnNativeArenaOwnerCodeV1 code)
{
    switch (code) {
    case ZN_NATIVE_ARENA_OWNER_V1_ACKED:
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED;
    case ZN_NATIVE_ARENA_OWNER_V1_BUSY:
    case ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND:
    case ZN_NATIVE_ARENA_OWNER_V1_NEEDS_QUIESCENCE:
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY;
    case ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT:
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ARGUMENT;
    case ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST:
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_STALE_REQUEST;
    case ZN_NATIVE_ARENA_OWNER_V1_ORDER:
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ORDER;
    case ZN_NATIVE_ARENA_OWNER_V1_POISONED:
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_POISONED;
    default:
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED;
    }
}

static ZnNativeArenaNonConvLifecycleCodeV1
zn_anl_fail_v1(ZnNativeArenaNonConvLifecycleV1 *lifecycle,
               ZnDispatch *dispatch, const ZnRequest *request)
{
    (void)zn_native_arena_owner_fail_v1(lifecycle->owner, dispatch, request);
    lifecycle->fault = 1;
    return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED;
}

static void
zn_anl_clear_active_v1(ZnNativeArenaNonConvLifecycleV1 *lifecycle)
{
    memset(&lifecycle->run_request, 0, sizeof lifecycle->run_request);
    memset(lifecycle->sources, 0, sizeof lifecycle->sources);
    memset(&lifecycle->output, 0, sizeof lifecycle->output);
    lifecycle->active = 0;
    lifecycle->mapped_mask = 0;
    lifecycle->visible_mask = 0;
    lifecycle->output_mapped = 0;
    lifecycle->run_started = 0;
    lifecycle->computed = 0;
    lifecycle->output_cleaned = 0;
    lifecycle->completion_recorded = 0;
    lifecycle->run_acked = 0;
    lifecycle->quiescence_recorded = 0;
}

static int
zn_anl_active_event_complete_v1(
    const ZnNativeArenaNonConvLifecycleV1 *lifecycle)
{
    const ZnEvent *event;
    const ZnNativeArenaEventStateV1 *state;

    if (!lifecycle || !lifecycle->active || !lifecycle->owner ||
        !lifecycle->run_request.job ||
        lifecycle->run_request.event_index >= lifecycle->owner->event_count)
        return 0;
    event = lifecycle->run_request.job;
    state = &lifecycle->owner->event_state[lifecycle->run_request.event_index];
    return state->run_acked && state->drained &&
           state->returned_mask == zn_anl_read_mask_v1(event->read_count) &&
           state->retired_mask == zn_anl_retire_mask_v1(event->retire_count);
}

static int
zn_anl_supported_event_v1(const ZnRequest *request)
{
    const ZnEvent *frozen;

    if (!request || !request->job)
        return 0;
    if (request->job->operation != ZN_ADD &&
        request->job->operation != ZN_POOL &&
        request->job->operation != ZN_HEADS)
        return 0;
    frozen = zn_native_nonconv_event_v1(request->event_index);
    if (!zn_anl_event_equal_v1(frozen, request->job))
        return 0;
    if (request->job->operation == ZN_HEADS)
        return request->event_index == 72 && request->job->event == 163 &&
               !request->job->has_destination &&
               request->job->read_count == 6;
    return request->job->has_destination;
}

static int
zn_anl_output_bytes_v1(const ZnRequest *request, uint32_t *bytes)
{
    if (!request || !request->job || !bytes)
        return 0;
    if (request->job->has_destination) {
        if (request->job->destination.bytes == 0)
            return 0;
        *bytes = request->job->destination.bytes;
        return 1;
    }
    if (request->job->operation != ZN_HEADS ||
        request->event_index != 72 || request->job->event != 163)
        return 0;
    *bytes = ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1;
    return 1;
}

static int
zn_anl_run_owner_valid_v1(const ZnNativeArenaNonConvLifecycleV1 *lifecycle,
                          const ZnRequest *request)
{
    const ZnNativeArenaOwnerV1 *owner;
    const ZnNativeArenaEventStateV1 *state;
    const ZnEvent *event;
    uint8_t index;

    if (!lifecycle || !lifecycle->owner || !request || !request->job ||
        request->event_index >= lifecycle->owner->event_count)
        return 0;
    owner = lifecycle->owner;
    event = request->job;
    state = &owner->event_state[request->event_index];
    if (event->read_count == 0 || event->read_count > 7 ||
        state->acquired_mask != zn_anl_read_mask_v1(event->read_count) ||
        state->run_started || state->run_completed || state->run_acked)
        return 0;

    for (index = 0; index < event->read_count; ++index) {
        ZnRef ref = event->reads[index];
        const ZnNativeArenaSlotV1 *slot;

        if (ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
            return 0;
        slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_anl_ref_equal_v1(slot->ref, ref) || slot->reader_count == 0 ||
            slot->bytes == 0 || slot->region.address == 0 ||
            slot->bytes > UINT32_MAX - slot->region.address)
            return 0;
    }

    if (event->has_destination) {
        ZnRef ref = event->destination.ref;
        const ZnNativeArenaSlotV1 *slot;

        if (!state->allocated || ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1 ||
            event->destination.bytes == 0)
            return 0;
        slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_RESERVED_V1 ||
            !zn_anl_ref_equal_v1(slot->ref, ref) ||
            slot->region.address != event->destination.address ||
            slot->bytes != event->destination.bytes ||
            slot->region.capacity_bytes < event->destination.bytes ||
            event->destination.address == 0 ||
            event->destination.bytes >
                UINT32_MAX - event->destination.address)
            return 0;
    }
    return 1;
}

static int
zn_anl_source_valid_v1(const ZnNativeArenaNonConvSourceV1 *source,
                       const ZnRequest *request, ZnRef expected_ref,
                       const ZnNativeArenaSlotV1 *slot)
{
    size_t expected_bytes;

    if (!source || !request || !slot || !source->view.data ||
        source->physical_address != slot->region.address ||
        source->view.epoch != request->epoch ||
        !zn_anl_ref_equal_v1(source->view.ref, expected_ref) ||
        source->view.bytes != slot->bytes || source->view.channels == 0 ||
        source->view.height == 0 || source->view.width == 0)
        return 0;
    expected_bytes = zn_anl_packed_bytes_v1(source->view.channels,
                                            source->view.height,
                                            source->view.width);
    return expected_bytes != 0 && expected_bytes == source->view.bytes &&
           zn_anl_span_v1(source->view.data, source->view.bytes);
}

static int
zn_anl_output_valid_v1(const ZnNativeArenaNonConvOutputV1 *output,
                       uint32_t address, uint32_t bytes)
{
    return output && output->data && output->physical_address == address &&
           output->capacity_bytes >= bytes &&
           zn_anl_span_v1(output->data, bytes);
}

static int
zn_anl_sources_disjoint_v1(
    const ZnNativeArenaNonConvLifecycleV1 *lifecycle, uint8_t count,
    uint32_t output_bytes)
{
    uint8_t index;

    if (!lifecycle || !zn_anl_span_v1(lifecycle->output.data, output_bytes))
        return 0;
    for (index = 0; index < count; ++index) {
        const ZnNativeViewSourceV1 *source = &lifecycle->sources[index].view;
        if (zn_anl_overlap_v1(lifecycle->output.data, output_bytes,
                              source->data, source->bytes))
            return 0;
    }
    return 1;
}

static int
zn_anl_prepare_run_v1(ZnNativeArenaNonConvLifecycleV1 *lifecycle,
                      ZnDispatch *dispatch, const ZnRequest *request,
                      uint32_t output_bytes)
{
    const ZnEvent *event = request->job;
    uint8_t index;
    uint8_t bit;
    uint32_t output_address = event->has_destination ?
        event->destination.address : 0;

    if (!lifecycle->run_started &&
        !zn_anl_run_owner_valid_v1(lifecycle, request))
        return -1;

    for (index = 0; index < event->read_count; ++index) {
        const ZnRef ref = event->reads[index];
        const ZnNativeArenaSlotV1 *slot =
            &lifecycle->owner->slots[ref.slot];
        int hook_status;

        bit = (uint8_t)(UINT32_C(1) << index);
        if ((lifecycle->mapped_mask & bit) == 0) {
            memset(&lifecycle->sources[index], 0,
                   sizeof lifecycle->sources[index]);
            hook_status = lifecycle->hooks.map_source(
                lifecycle->hooks.context, request, index,
                slot->region.address, slot->bytes,
                &lifecycle->sources[index]);
            if (hook_status == ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1)
                return 1;
            if (hook_status != ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1 ||
                !zn_anl_source_valid_v1(&lifecycle->sources[index], request,
                                        ref, slot))
                return -1;
            lifecycle->mapped_mask |= bit;
        }
    }

    if (!lifecycle->output_mapped) {
        memset(&lifecycle->output, 0, sizeof lifecycle->output);
        {
            int hook_status = lifecycle->hooks.map_output(
                lifecycle->hooks.context, request, output_address,
                output_bytes, &lifecycle->output);
            if (hook_status == ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1)
                return 1;
            if (hook_status != ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1 ||
                !zn_anl_output_valid_v1(&lifecycle->output, output_address,
                                        output_bytes))
                return -1;
        }
        lifecycle->output_mapped = 1;
        if (!zn_anl_sources_disjoint_v1(lifecycle, event->read_count,
                                        output_bytes))
            return -1;
    }

    for (index = 0; index < event->read_count; ++index) {
        bit = (uint8_t)(UINT32_C(1) << index);
        if ((lifecycle->visible_mask & bit) == 0) {
            int hook_status = lifecycle->hooks.source_visible(
                lifecycle->hooks.context, request, index,
                &lifecycle->sources[index]);
            if (hook_status == ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1)
                return 1;
            if (hook_status != ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1)
                return -1;
            lifecycle->visible_mask |= bit;
        }
    }

    if (!lifecycle->run_started) {
        ZnNativeArenaOwnerCodeV1 owner_code;

        owner_code = zn_native_arena_owner_run_started_v1(
            lifecycle->owner, dispatch, request);
        if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
            return -1;
        lifecycle->run_started = 1;
    }

    if (!lifecycle->computed) {
        ZnNativeViewSourceV1 views[7];
        ZnNativeArenaCompletionEvidenceV1 completion;
        int operator_code;

        for (index = 0; index < event->read_count; ++index)
            views[index] = lifecycle->sources[index].view;
        ++lifecycle->operator_call_count;
        operator_code = zn_native_nonconv_run_v1(
            request, views, event->read_count, lifecycle->output.data,
            output_bytes);
        if (operator_code != 0)
            return -1;
        lifecycle->computed = 1;

        if (!event->has_destination) {
            memset(&completion, 0, sizeof completion);
            completion.epoch = request->epoch;
            completion.run_tag = request->tag;
            completion.event_index = request->event_index;
            completion.result_identity_verified = 1;
            completion.driver_terminal_success = 1;
            if (zn_native_arena_owner_complete_without_output_v1(
                    lifecycle->owner, dispatch, request, &completion) !=
                ZN_NATIVE_ARENA_OWNER_V1_ACKED)
                return -1;
            lifecycle->completion_recorded = 1;
        }
    }

    if (event->has_destination) {
        int hook_status;
        ZnNativeArenaCompletionEvidenceV1 completion;

        if (!lifecycle->output_cleaned) {
            hook_status = lifecycle->hooks.clean_output(
                lifecycle->hooks.context, request, &lifecycle->output,
                output_bytes);
            if (hook_status == ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1)
                return 1;
            if (hook_status != ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1)
                return -1;
            lifecycle->output_cleaned = 1;
        }
        hook_status = lifecycle->hooks.publish_output(
            lifecycle->hooks.context, request, &lifecycle->output,
            output_bytes);
        if (hook_status == ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1)
            return 1;
        if (hook_status != ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1)
            return -1;

        memset(&completion, 0, sizeof completion);
        completion.epoch = request->epoch;
        completion.run_tag = request->tag;
        completion.event_index = request->event_index;
        completion.destination_ref = event->destination.ref;
        completion.destination_bytes = event->destination.bytes;
        completion.result_identity_verified = 1;
        completion.driver_terminal_success = 1;
        completion.output_cache_visible = 1;
        if (zn_native_arena_owner_publish_v1(
                lifecycle->owner, dispatch, request, &completion) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED)
            return -1;
        lifecycle->completion_recorded = 1;
    }

    if (!lifecycle->completion_recorded)
        return -1;
    {
        ZnNativeArenaOwnerCodeV1 owner_code =
            zn_native_arena_owner_step_v1(lifecycle->owner, dispatch, request);
        if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
            return -1;
    }
    lifecycle->run_acked = 1;
    return 0;
}

static int
zn_anl_active_request_matches_v1(
    const ZnNativeArenaNonConvLifecycleV1 *lifecycle,
    const ZnRequest *request)
{
    return lifecycle && lifecycle->active && request &&
           lifecycle->run_request.epoch == request->epoch &&
           lifecycle->run_request.event_index == request->event_index &&
           lifecycle->run_request.job == request->job;
}

static ZnNativeArenaNonConvLifecycleCodeV1
zn_anl_run_v1(ZnNativeArenaNonConvLifecycleV1 *lifecycle,
              ZnDispatch *dispatch, const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 owner_code;
    uint32_t output_bytes;
    int prepared;

    if (!zn_anl_supported_event_v1(request))
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_UNSUPPORTED;
    if (!zn_anl_output_bytes_v1(request, &output_bytes))
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_INVALID;

    if (!lifecycle->active) {
        owner_code = zn_native_arena_owner_step_v1(
            lifecycle->owner, dispatch, request);
        if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND)
            return zn_anl_owner_code_v1(owner_code);
        memset(&lifecycle->run_request, 0, sizeof lifecycle->run_request);
        lifecycle->run_request = *request;
        lifecycle->active = 1;
    } else if (!zn_anl_request_equal_v1(&lifecycle->run_request, request)) {
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_STALE_REQUEST;
    }

    if (!lifecycle->run_started) {
        owner_code = zn_native_arena_owner_step_v1(
            lifecycle->owner, dispatch, request);
        if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND)
            return zn_anl_owner_code_v1(owner_code);
    }

    prepared = zn_anl_prepare_run_v1(lifecycle, dispatch, request,
                                     output_bytes);
    if (prepared == 1)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY;
    if (prepared != 0)
        return zn_anl_fail_v1(lifecycle, dispatch, request);
    return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED;
}

static ZnNativeArenaNonConvLifecycleCodeV1
zn_anl_drain_v1(ZnNativeArenaNonConvLifecycleV1 *lifecycle,
                ZnDispatch *dispatch, const ZnRequest *request)
{
    const ZnNativeArenaEventStateV1 *event_state;
    ZnNativeArenaQuiescenceEvidenceV1 evidence;
    ZnNativeArenaOwnerCodeV1 owner_code;
    int hook_status;

    if (!zn_anl_active_request_matches_v1(lifecycle, request) ||
        !lifecycle->run_acked || lifecycle->quiescence_recorded)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ORDER;
    event_state = &lifecycle->owner->event_state[request->event_index];
    if (!event_state->run_acked || !event_state->run_completed ||
        event_state->io_quiescent)
        return zn_anl_fail_v1(lifecycle, dispatch, request);
    owner_code = zn_native_arena_owner_step_v1(
        lifecycle->owner, dispatch, request);
    if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_BUSY)
        return zn_anl_fail_v1(lifecycle, dispatch, request);

    memset(&evidence, 0, sizeof evidence);
    hook_status = lifecycle->hooks.drain_ready(
        lifecycle->hooks.context, request, &evidence);
    if (hook_status == ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY;
    if (hook_status != ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1 ||
        evidence.epoch != request->epoch ||
        evidence.event_index != request->event_index ||
        evidence.run_tag != lifecycle->run_request.tag ||
        !evidence.all_read_io_quiet || !evidence.all_write_io_quiet ||
        !evidence.driver_terminal)
        return zn_anl_fail_v1(lifecycle, dispatch, request);

    if (zn_native_arena_owner_notify_quiescent_v1(
            lifecycle->owner, dispatch, request, &evidence) !=
        ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return zn_anl_fail_v1(lifecycle, dispatch, request);
    owner_code = zn_native_arena_owner_step_v1(
        lifecycle->owner, dispatch, request);
    if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return zn_anl_fail_v1(lifecycle, dispatch, request);
    lifecycle->quiescence_recorded = 1;
    return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED;
}

static ZnNativeArenaNonConvLifecycleCodeV1
zn_anl_return_v1(ZnNativeArenaNonConvLifecycleV1 *lifecycle,
                 ZnDispatch *dispatch, const ZnRequest *request)
{
    const ZnEvent *event;
    const ZnNativeArenaEventStateV1 *event_state;
    const ZnNativeArenaSlotV1 *slot;
    uint8_t read_index;
    int hook_status;

    if (!zn_anl_active_request_matches_v1(lifecycle, request) ||
        !lifecycle->quiescence_recorded || !request->job)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ORDER;
    event = request->job;
    read_index = dispatch->index;
    if (read_index >= event->read_count ||
        !zn_anl_ref_equal_v1(request->ref, event->reads[read_index]))
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_STALE_REQUEST;
    event_state = &lifecycle->owner->event_state[request->event_index];
    if (!event_state->drained ||
        (event_state->returned_mask & (uint8_t)(UINT32_C(1) << read_index)) != 0 ||
        request->ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ORDER;
    slot = &lifecycle->owner->slots[request->ref.slot];
    if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
        !zn_anl_ref_equal_v1(slot->ref, request->ref) ||
        slot->reader_count == 0 || slot->io_count != 0)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_INVALID;

    hook_status = lifecycle->hooks.return_graph_read(
        lifecycle->hooks.context, request, read_index, slot->region.address,
        request->ref);
    if (hook_status == ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY;
    if (hook_status != ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1)
        return zn_anl_fail_v1(lifecycle, dispatch, request);
    if (zn_native_arena_owner_step_v1(lifecycle->owner, dispatch, request) !=
        ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return zn_anl_fail_v1(lifecycle, dispatch, request);
    return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED;
}

ZnNativeArenaNonConvLifecycleCodeV1
zn_native_arena_nonconv_lifecycle_init_v1(
    ZnNativeArenaNonConvLifecycleV1 *lifecycle,
    ZnNativeArenaOwnerV1 *owner,
    const ZnNativeArenaNonConvHooksV1 *hooks)
{
    if (!lifecycle || !owner || !hooks || !owner->initialized ||
        !hooks->map_source || !hooks->source_visible || !hooks->map_output ||
        !hooks->clean_output || !hooks->publish_output || !hooks->drain_ready ||
        !hooks->return_graph_read)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ARGUMENT;
    memset(lifecycle, 0, sizeof *lifecycle);
    lifecycle->owner = owner;
    lifecycle->hooks = *hooks;
    return owner->fault ? ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_POISONED :
           ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED;
}

ZnNativeArenaNonConvLifecycleCodeV1
zn_native_arena_nonconv_lifecycle_step_v1(
    ZnNativeArenaNonConvLifecycleV1 *lifecycle, ZnDispatch *dispatch,
    const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 owner_code;

    if (!lifecycle || !lifecycle->owner || !dispatch || !request)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ARGUMENT;
    if (lifecycle->fault || lifecycle->owner->fault || dispatch->fault)
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_POISONED;
    if (!zn_anl_pending_matches_v1(dispatch, request, lifecycle->owner))
        return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_STALE_REQUEST;

    if (lifecycle->active &&
        request->event_index != lifecycle->run_request.event_index) {
        if (!zn_anl_active_event_complete_v1(lifecycle))
            return ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ORDER;
        zn_anl_clear_active_v1(lifecycle);
    }

    if (request->operation == ZN_RUN)
        return zn_anl_run_v1(lifecycle, dispatch, request);
    if (request->operation == ZN_DRAIN)
        return zn_anl_drain_v1(lifecycle, dispatch, request);
    if (request->operation == ZN_RETURN)
        return zn_anl_return_v1(lifecycle, dispatch, request);

    owner_code = zn_native_arena_owner_step_v1(
        lifecycle->owner, dispatch, request);
    return zn_anl_owner_code_v1(owner_code);
}
