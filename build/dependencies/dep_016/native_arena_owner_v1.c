#include "native_arena_owner_v1.h"

#include "graph_plan.h"

#include <string.h>

enum {
    ZN_NATIVE_ARENA_BASE_V1 = UINT32_C(0x10000000),
    ZN_NATIVE_ARENA_END_V1 = UINT32_C(273637376),
    ZN_NATIVE_ARENA_BYTES_V1 = UINT32_C(5201920),
    ZN_NATIVE_ARENA_ALIGNMENT_V1 = 4096
};

static const ZnNativeArenaRegionV1 zn_native_arena_regions_v1[
    ZN_NATIVE_ARENA_SLOT_COUNT_V1] = {
    { UINT32_C(268435456), UINT32_C(1638400) },
    { UINT32_C(270073856), UINT32_C(1638400) },
    { UINT32_C(271712256), UINT32_C(819200) },
    { UINT32_C(272531456), UINT32_C(409600) },
    { UINT32_C(272941056), UINT32_C(409600) },
    { UINT32_C(273350656), UINT32_C(122880) },
    { UINT32_C(273473536), UINT32_C(163840) }
};

static int
zn_native_arena_ref_equal_v1(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
zn_native_arena_request_equal_v1(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index &&
           a->operation == b->operation &&
           zn_native_arena_ref_equal_v1(a->ref, b->ref) && a->job == b->job;
}

static int
zn_native_arena_event_equal_v1(const ZnEvent *a, const ZnEvent *b)
{
    uint8_t index;

    if (!a || !b || a->event != b->event || a->tile_first != b->tile_first ||
        a->tile_count != b->tile_count || a->compute_node != b->compute_node ||
        a->operation != b->operation || a->read_count != b->read_count ||
        a->retire_count != b->retire_count ||
        a->has_destination != b->has_destination)
        return 0;
    if (a->has_destination &&
        (a->destination.address != b->destination.address ||
         a->destination.bytes != b->destination.bytes ||
         a->destination.channels != b->destination.channels ||
         a->destination.height != b->destination.height ||
         a->destination.width != b->destination.width ||
         !zn_native_arena_ref_equal_v1(a->destination.ref,
                                       b->destination.ref)))
        return 0;
    for (index = 0; index < a->read_count; ++index) {
        if (!zn_native_arena_ref_equal_v1(a->reads[index], b->reads[index]))
            return 0;
    }
    for (index = 0; index < a->retire_count; ++index) {
        if (!zn_native_arena_ref_equal_v1(a->retired[index], b->retired[index]))
            return 0;
    }
    return 1;
}

static int
zn_native_arena_ref_valid_v1(ZnRef ref)
{
    return ref.generation != 0 && ref.slot < ZN_NATIVE_ARENA_SLOT_COUNT_V1 &&
           ref.tensor >= -1 && ref.tensor <= 65535;
}

static uint64_t
zn_native_arena_tensor_bytes_v1(const ZnDestination *destination)
{
    uint64_t channels = destination->channels;
    uint64_t height = destination->height;
    uint64_t width = destination->width;

    return ((channels + 3u) / 4u) * height * ((width + 15u) / 16u) * 64u;
}

static int
zn_native_arena_reference_precedes_v1(ZnRef ref, uint16_t event_index)
{
    uint16_t index;

    if (ref.generation == 1 && ref.tensor == -1 && ref.slot == 0)
        return 1;
    for (index = 0; index < event_index; ++index) {
        const ZnEvent *event = &z100_graph_events[index];
        if (event->has_destination &&
            zn_native_arena_ref_equal_v1(ref, event->destination.ref))
            return 1;
    }
    return 0;
}

static ZnNativeArenaOwnerCodeV1
zn_native_arena_config_valid_v1(const ZnNativeArenaConfigV1 *config)
{
    uint8_t index;
    uint8_t other;
    uint64_t end;

    if (!config)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    if (config->arena_base != ZN_NATIVE_ARENA_BASE_V1 ||
        config->arena_end != ZN_NATIVE_ARENA_END_V1 ||
        config->arena_bytes != ZN_NATIVE_ARENA_BYTES_V1 ||
        config->alignment != ZN_NATIVE_ARENA_ALIGNMENT_V1 ||
        memcmp(config->package_sha256, ZN_NATIVE_ARENA_PACKAGE_SHA256_V1,
               sizeof config->package_sha256) != 0 ||
        memcmp(config->graph_sha256, ZN_NATIVE_ARENA_GRAPH_SHA256_V1,
               sizeof config->graph_sha256) != 0 ||
        memcmp(config->plan_sha256, ZN_NATIVE_ARENA_PLAN_SHA256_V1,
               sizeof config->plan_sha256) != 0 ||
        memcmp(config->manifest_sha256, ZN_NATIVE_ARENA_MANIFEST_SHA256_V1,
               sizeof config->manifest_sha256) != 0)
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;

    if ((uint64_t)config->arena_base + config->arena_bytes != config->arena_end ||
        config->arena_base % config->alignment != 0)
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;

    for (index = 0; index < ZN_NATIVE_ARENA_SLOT_COUNT_V1; ++index) {
        const ZnNativeArenaRegionV1 *slot = &config->slots[index];
        uint64_t slot_end = (uint64_t)slot->address + slot->capacity_bytes;
        if (slot->address != zn_native_arena_regions_v1[index].address ||
            slot->capacity_bytes !=
                zn_native_arena_regions_v1[index].capacity_bytes ||
            slot->capacity_bytes == 0 || slot->address % config->alignment != 0 ||
            slot->address < config->arena_base || slot_end > config->arena_end ||
            slot_end > UINT64_C(0x100000000))
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        end = slot_end;
        for (other = 0; other < index; ++other) {
            uint64_t other_begin = config->slots[other].address;
            uint64_t other_end = other_begin + config->slots[other].capacity_bytes;
            if ((uint64_t)slot->address < other_end && other_begin < end)
                return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        }
    }
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

static ZnNativeArenaOwnerCodeV1
zn_native_arena_plan_valid_v1(const ZnNativeArenaConfigV1 *config,
                              const ZnEvent *events, uint16_t count)
{
    uint32_t generation_high_water[ZN_NATIVE_ARENA_SLOT_COUNT_V1] = { 1, 0, 0, 0, 0, 0, 0 };
    uint16_t index;

    if (!events || count != ZN_NATIVE_ARENA_EVENT_COUNT_V1)
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
    if (memcmp(Z100_GRAPH_PACKAGE_SHA256, ZN_NATIVE_ARENA_PACKAGE_SHA256_V1,
               sizeof ZN_NATIVE_ARENA_PACKAGE_SHA256_V1) != 0)
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;

    for (index = 0; index < count; ++index) {
        const ZnEvent *event = &events[index];
        const ZnEvent *frozen = &z100_graph_events[index];
        uint8_t read_index;
        uint8_t retire_index;

        if (!zn_native_arena_event_equal_v1(event, frozen) ||
            event->operation < ZN_CONV || event->operation > ZN_HEADS ||
            event->read_count > 7 || event->retire_count > 7 ||
            event->has_destination > 1)
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;

        for (read_index = 0; read_index < event->read_count; ++read_index) {
            if (!zn_native_arena_ref_valid_v1(event->reads[read_index]) ||
                !zn_native_arena_reference_precedes_v1(event->reads[read_index],
                                                       index))
                return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        }
        for (retire_index = 0; retire_index < event->retire_count;
             ++retire_index) {
            if (!zn_native_arena_ref_valid_v1(event->retired[retire_index]) ||
                !zn_native_arena_reference_precedes_v1(event->retired[retire_index],
                                                       index))
                return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        }

        if (event->has_destination) {
            const ZnDestination *destination = &event->destination;
            uint8_t slot;
            uint64_t bytes;
            uint64_t dest_end;

            if (!zn_native_arena_ref_valid_v1(destination->ref) ||
                destination->ref.tensor < 0 || !destination->channels ||
                destination->channels > 1024 || !destination->height ||
                destination->height > 640 || !destination->width ||
                destination->width > 640)
                return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
            slot = destination->ref.slot;
            bytes = zn_native_arena_tensor_bytes_v1(destination);
            dest_end = (uint64_t)destination->address + destination->bytes;
            if (destination->address != config->slots[slot].address ||
                (destination->address & 63u) != 0 ||
                destination->bytes != bytes ||
                destination->bytes > config->slots[slot].capacity_bytes ||
                dest_end > (uint64_t)config->slots[slot].address +
                               config->slots[slot].capacity_bytes ||
                destination->ref.generation <= generation_high_water[slot])
                return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
            generation_high_water[slot] = destination->ref.generation;

            for (read_index = 0; read_index < event->read_count; ++read_index) {
                if (event->reads[read_index].slot == slot)
                    return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
            }
        }
    }
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

static ZnNativeArenaOwnerCodeV1
zn_native_arena_pending_valid_v1(const ZnNativeArenaOwnerV1 *owner,
                                 const ZnDispatch *dispatch,
                                 const ZnRequest *request)
{
    if (!owner || !dispatch || !request)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    if (!owner->initialized)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    if (owner->fault || dispatch->fault)
        return ZN_NATIVE_ARENA_OWNER_V1_POISONED;
    if (dispatch->events != owner->events || dispatch->count != owner->event_count ||
        dispatch->epoch != owner->epoch || !dispatch->pending ||
        request->epoch != owner->epoch || request->event_index >= owner->event_count ||
        dispatch->cursor != request->event_index ||
        dispatch->phase != request->operation ||
        request->job != &owner->events[request->event_index] ||
        !zn_native_arena_event_equal_v1(request->job,
            &z100_graph_events[request->event_index]) ||
        !zn_native_arena_request_equal_v1(request, &dispatch->request))
        return ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST;
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

static uint8_t
zn_native_arena_read_mask_v1(uint8_t count)
{
    return count == 0 ? 0 : (uint8_t)((UINT32_C(1) << count) - 1u);
}

static ZnNativeArenaOwnerCodeV1
zn_native_arena_current_run_valid_v1(const ZnNativeArenaOwnerV1 *owner,
                                     const ZnDispatch *dispatch,
                                     const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 code =
        zn_native_arena_pending_valid_v1(owner, dispatch, request);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;
    if (request->operation != ZN_RUN)
        return ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST;
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

static int
zn_native_arena_event_resources_ready_v1(const ZnNativeArenaOwnerV1 *owner,
                                         const ZnEvent *event,
                                         int require_zero_io)
{
    uint8_t index;

    for (index = 0; index < event->read_count; ++index) {
        const ZnRef ref = event->reads[index];
        const ZnNativeArenaSlotV1 *slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_native_arena_ref_equal_v1(slot->ref, ref) ||
            (require_zero_io && slot->io_count != 0))
            return 0;
    }
    if (event->has_destination) {
        const ZnRef ref = event->destination.ref;
        const ZnNativeArenaSlotV1 *slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_native_arena_ref_equal_v1(slot->ref, ref) ||
            (require_zero_io && (slot->io_count != 0 || slot->reader_count != 0)))
            return 0;
    }
    return 1;
}

ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_init_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnNativeArenaConfigV1 *config,
    const ZnDispatch *dispatch, uint32_t epoch)
{
    ZnNativeArenaOwnerCodeV1 code;
    uint8_t slot;

    if (!owner || !config || !dispatch || !epoch)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    if (owner->initialized)
        return ZN_NATIVE_ARENA_OWNER_V1_ORDER;
    code = zn_native_arena_config_valid_v1(config);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;
    if (!dispatch->events || dispatch->count != ZN_NATIVE_ARENA_EVENT_COUNT_V1 ||
        dispatch->epoch != epoch || dispatch->pending || dispatch->fault ||
        dispatch->done || dispatch->cursor != 0 || dispatch->phase != ZN_ALLOCATE ||
        dispatch->index != 0 || dispatch->next_tag != 1)
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
    code = zn_native_arena_plan_valid_v1(config, dispatch->events,
                                         dispatch->count);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;

    memset(owner, 0, sizeof *owner);
    owner->events = dispatch->events;
    owner->epoch = epoch;
    owner->event_count = dispatch->count;
    for (slot = 0; slot < ZN_NATIVE_ARENA_SLOT_COUNT_V1; ++slot)
        owner->slots[slot].region = config->slots[slot];

    owner->slots[0].ref.generation = 1;
    owner->slots[0].ref.tensor = -1;
    owner->slots[0].ref.slot = 0;
    owner->slots[0].bytes = config->slots[0].capacity_bytes;
    owner->slots[0].generation_high_water = 1;
    owner->slots[0].state = ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1;
    owner->initialized = 1;
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_step_v1(
    ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
    const ZnRequest *request)
{
    const ZnEvent *event;
    ZnNativeArenaEventStateV1 *event_state;
    ZnNativeArenaOwnerCodeV1 code;
    uint8_t index;
    uint8_t bit;
    ZnNativeArenaSlotV1 *slot;

    code = zn_native_arena_pending_valid_v1(owner, dispatch, request);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;
    event = request->job;
    event_state = &owner->event_state[request->event_index];

    switch (request->operation) {
    case ZN_ALLOCATE:
        if (!event->has_destination || request->ref.slot != event->destination.ref.slot ||
            !zn_native_arena_ref_equal_v1(request->ref, event->destination.ref))
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        slot = &owner->slots[request->ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_EMPTY_V1 || event_state->allocated ||
            request->ref.generation <= slot->generation_high_water ||
            event->destination.address != slot->region.address ||
            event->destination.bytes == 0 ||
            event->destination.bytes > slot->region.capacity_bytes)
            return ZN_NATIVE_ARENA_OWNER_V1_ORDER;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0) {
            owner->fault = 1;
            return ZN_NATIVE_ARENA_OWNER_V1_FAILED;
        }
        slot->ref = request->ref;
        slot->bytes = event->destination.bytes;
        slot->generation_high_water = request->ref.generation;
        slot->state = ZN_NATIVE_ARENA_SLOT_RESERVED_V1;
        event_state->allocated = 1;
        return ZN_NATIVE_ARENA_OWNER_V1_ACKED;

    case ZN_ACQUIRE:
        index = dispatch->index;
        if (index >= event->read_count ||
            !zn_native_arena_ref_equal_v1(request->ref, event->reads[index]))
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        bit = (uint8_t)(UINT32_C(1) << index);
        if (event_state->run_started || (event_state->acquired_mask & bit) != 0)
            return ZN_NATIVE_ARENA_OWNER_V1_ORDER;
        slot = &owner->slots[request->ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_native_arena_ref_equal_v1(slot->ref, request->ref))
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        if (slot->reader_count == UINT16_MAX)
            return ZN_NATIVE_ARENA_OWNER_V1_OVERFLOW;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0) {
            owner->fault = 1;
            return ZN_NATIVE_ARENA_OWNER_V1_FAILED;
        }
        ++slot->reader_count;
        event_state->acquired_mask |= bit;
        return ZN_NATIVE_ARENA_OWNER_V1_ACKED;

    case ZN_RUN:
        if (event_state->acquired_mask !=
                zn_native_arena_read_mask_v1(event->read_count) ||
            (event->has_destination &&
             (!event_state->allocated ||
              !zn_native_arena_ref_equal_v1(
                  owner->slots[event->destination.ref.slot].ref,
                  event->destination.ref) ||
              (!event_state->output_published &&
               owner->slots[event->destination.ref.slot].state !=
                   ZN_NATIVE_ARENA_SLOT_RESERVED_V1) ||
              (event_state->output_published &&
               owner->slots[event->destination.ref.slot].state !=
                   ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1))))
            return ZN_NATIVE_ARENA_OWNER_V1_ORDER;
        if (!event_state->run_started)
            return ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND;
        if (!event_state->run_completed ||
            (event->has_destination && !event_state->output_published))
            return ZN_NATIVE_ARENA_OWNER_V1_BUSY;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0) {
            owner->fault = 1;
            return ZN_NATIVE_ARENA_OWNER_V1_FAILED;
        }
        event_state->run_acked = 1;
        return ZN_NATIVE_ARENA_OWNER_V1_ACKED;

    case ZN_DRAIN:
        if (!event_state->run_acked || !event_state->run_completed ||
            !event_state->io_quiescent ||
            !zn_native_arena_event_resources_ready_v1(owner, event, 1))
            return ZN_NATIVE_ARENA_OWNER_V1_BUSY;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0) {
            owner->fault = 1;
            return ZN_NATIVE_ARENA_OWNER_V1_FAILED;
        }
        event_state->drained = 1;
        return ZN_NATIVE_ARENA_OWNER_V1_ACKED;

    case ZN_RETURN:
        index = dispatch->index;
        if (index >= event->read_count ||
            !zn_native_arena_ref_equal_v1(request->ref, event->reads[index]))
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        bit = (uint8_t)(UINT32_C(1) << index);
        if (!event_state->drained || (event_state->acquired_mask & bit) == 0 ||
            (event_state->returned_mask & bit) != 0)
            return ZN_NATIVE_ARENA_OWNER_V1_ORDER;
        slot = &owner->slots[request->ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_native_arena_ref_equal_v1(slot->ref, request->ref) ||
            slot->reader_count == 0 || slot->io_count != 0)
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0) {
            owner->fault = 1;
            return ZN_NATIVE_ARENA_OWNER_V1_FAILED;
        }
        --slot->reader_count;
        event_state->returned_mask |= bit;
        return ZN_NATIVE_ARENA_OWNER_V1_ACKED;

    case ZN_RETIRE:
        index = dispatch->index;
        if (index >= event->retire_count ||
            !zn_native_arena_ref_equal_v1(request->ref, event->retired[index]))
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        bit = (uint8_t)(UINT32_C(1) << index);
        if ((event_state->retired_mask & bit) != 0)
            return ZN_NATIVE_ARENA_OWNER_V1_ORDER;
        slot = &owner->slots[request->ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_native_arena_ref_equal_v1(slot->ref, request->ref) ||
            slot->reader_count != 0 || slot->io_count != 0)
            return ZN_NATIVE_ARENA_OWNER_V1_BUSY;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0) {
            owner->fault = 1;
            return ZN_NATIVE_ARENA_OWNER_V1_FAILED;
        }
        slot->state = ZN_NATIVE_ARENA_SLOT_EMPTY_V1;
        slot->bytes = 0;
        memset(&slot->ref, 0, sizeof slot->ref);
        event_state->retired_mask |= bit;
        return ZN_NATIVE_ARENA_OWNER_V1_ACKED;

    default:
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
    }
}

ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_run_started_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request)
{
    const ZnEvent *event;
    ZnNativeArenaEventStateV1 *event_state;
    ZnNativeArenaOwnerCodeV1 code;
    uint8_t index;
    uint8_t mask;

    code = zn_native_arena_current_run_valid_v1(owner, dispatch, request);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;
    event = request->job;
    event_state = &owner->event_state[request->event_index];
    mask = zn_native_arena_read_mask_v1(event->read_count);
    if (event_state->run_started || event_state->run_completed ||
        event_state->acquired_mask != mask)
        return ZN_NATIVE_ARENA_OWNER_V1_ORDER;

    for (index = 0; index < event->read_count; ++index) {
        const ZnRef ref = event->reads[index];
        const ZnNativeArenaSlotV1 *slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_native_arena_ref_equal_v1(slot->ref, ref))
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        if (slot->io_count == UINT16_MAX)
            return ZN_NATIVE_ARENA_OWNER_V1_OVERFLOW;
    }
    if (event->has_destination) {
        const ZnRef ref = event->destination.ref;
        const ZnNativeArenaSlotV1 *slot = &owner->slots[ref.slot];
        if (!event_state->allocated ||
            slot->state != ZN_NATIVE_ARENA_SLOT_RESERVED_V1 ||
            !zn_native_arena_ref_equal_v1(slot->ref, ref))
            return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
        if (slot->io_count == UINT16_MAX)
            return ZN_NATIVE_ARENA_OWNER_V1_OVERFLOW;
    }

    for (index = 0; index < event->read_count; ++index)
        ++owner->slots[event->reads[index].slot].io_count;
    if (event->has_destination)
        ++owner->slots[event->destination.ref.slot].io_count;
    event_state->run_tag = request->tag;
    event_state->run_started = 1;
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_publish_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request,
    const ZnNativeArenaCompletionEvidenceV1 *evidence)
{
    const ZnEvent *event;
    ZnNativeArenaEventStateV1 *event_state;
    ZnNativeArenaOwnerCodeV1 code;
    ZnNativeArenaSlotV1 *slot;

    if (!evidence)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    code = zn_native_arena_current_run_valid_v1(owner, dispatch, request);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;
    event = request->job;
    event_state = &owner->event_state[request->event_index];
    if (!event->has_destination || !event_state->run_started ||
        event_state->run_completed || evidence->epoch != owner->epoch ||
        evidence->event_index != request->event_index ||
        evidence->run_tag != event_state->run_tag ||
        !evidence->result_identity_verified ||
        !evidence->driver_terminal_success || !evidence->output_cache_visible ||
        !zn_native_arena_ref_equal_v1(evidence->destination_ref,
                                      event->destination.ref) ||
        evidence->destination_bytes != event->destination.bytes)
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;

    slot = &owner->slots[event->destination.ref.slot];
    if (slot->state != ZN_NATIVE_ARENA_SLOT_RESERVED_V1 ||
        !zn_native_arena_ref_equal_v1(slot->ref, event->destination.ref) ||
        slot->bytes != event->destination.bytes)
        return ZN_NATIVE_ARENA_OWNER_V1_ORDER;

    slot->state = ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1;
    event_state->output_published = 1;
    event_state->run_completed = 1;
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_complete_without_output_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request,
    const ZnNativeArenaCompletionEvidenceV1 *evidence)
{
    const ZnEvent *event;
    ZnNativeArenaEventStateV1 *event_state;
    ZnNativeArenaOwnerCodeV1 code;

    if (!evidence)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    code = zn_native_arena_current_run_valid_v1(owner, dispatch, request);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;
    event = request->job;
    event_state = &owner->event_state[request->event_index];
    if (event->has_destination || !event_state->run_started ||
        event_state->run_completed || evidence->epoch != owner->epoch ||
        evidence->event_index != request->event_index ||
        evidence->run_tag != event_state->run_tag ||
        !evidence->result_identity_verified ||
        !evidence->driver_terminal_success || evidence->output_cache_visible ||
        evidence->destination_ref.generation != 0 ||
        evidence->destination_ref.tensor != 0 ||
        evidence->destination_ref.slot != 0 || evidence->destination_bytes != 0)
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
    event_state->run_completed = 1;
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_notify_quiescent_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request,
    const ZnNativeArenaQuiescenceEvidenceV1 *evidence)
{
    const ZnEvent *event;
    ZnNativeArenaEventStateV1 *event_state;
    ZnNativeArenaOwnerCodeV1 code;
    uint16_t required[ZN_NATIVE_ARENA_SLOT_COUNT_V1] = { 0, 0, 0, 0, 0, 0, 0 };
    uint8_t index;

    if (!evidence)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    code = zn_native_arena_pending_valid_v1(owner, dispatch, request);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;
    if (request->operation != ZN_RUN && request->operation != ZN_DRAIN)
        return ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST;
    event = request->job;
    event_state = &owner->event_state[request->event_index];
    if (!event_state->run_started || !event_state->run_completed ||
        event_state->io_quiescent || evidence->epoch != owner->epoch ||
        evidence->event_index != request->event_index ||
        evidence->run_tag != event_state->run_tag ||
        !evidence->all_read_io_quiet || !evidence->all_write_io_quiet ||
        !evidence->driver_terminal)
        return ZN_NATIVE_ARENA_OWNER_V1_INVALID;
    if (request->operation == ZN_DRAIN && !event_state->run_acked)
        return ZN_NATIVE_ARENA_OWNER_V1_ORDER;

    for (index = 0; index < event->read_count; ++index)
        ++required[event->reads[index].slot];
    if (event->has_destination)
        ++required[event->destination.ref.slot];
    for (index = 0; index < ZN_NATIVE_ARENA_SLOT_COUNT_V1; ++index) {
        if (owner->slots[index].io_count < required[index])
            return ZN_NATIVE_ARENA_OWNER_V1_ORDER;
    }
    for (index = 0; index < event->read_count; ++index)
        --owner->slots[event->reads[index].slot].io_count;
    if (event->has_destination)
        --owner->slots[event->destination.ref.slot].io_count;
    event_state->io_quiescent = 1;
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}

ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_fail_v1(
    ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
    const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 code;

    code = zn_native_arena_pending_valid_v1(owner, dispatch, request);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return code;
    owner->fault = 1;
    (void)zn_dispatch_ack(dispatch, request->tag, request->operation,
                         ZN_ACK_FAILED);
    return ZN_NATIVE_ARENA_OWNER_V1_FAILED;
}

ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_verify_complete_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch)
{
    uint8_t index;

    if (!owner || !dispatch)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    if (!owner->initialized)
        return ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT;
    if (owner->fault || dispatch->fault)
        return ZN_NATIVE_ARENA_OWNER_V1_POISONED;
    if (dispatch->events != owner->events || dispatch->count != owner->event_count ||
        dispatch->epoch != owner->epoch || !dispatch->done || dispatch->pending ||
        dispatch->cursor != owner->event_count)
        return ZN_NATIVE_ARENA_OWNER_V1_BUSY;
    for (index = 0; index < ZN_NATIVE_ARENA_SLOT_COUNT_V1; ++index) {
        const ZnNativeArenaSlotV1 *slot = &owner->slots[index];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_EMPTY_V1 ||
            slot->reader_count != 0 || slot->io_count != 0)
            return ZN_NATIVE_ARENA_OWNER_V1_BUSY;
    }
    owner->complete = 1;
    return ZN_NATIVE_ARENA_OWNER_V1_ACKED;
}
