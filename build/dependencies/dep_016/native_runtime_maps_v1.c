#include "native_runtime_maps_v1.h"
#include "graph_plan.h"

#include <string.h>

#define ARENA_BASE UINT32_C(0x10000000)
#define ARENA_BYTES UINT32_C(5201920)

static int ref_equal(ZnRef a, ZnRef b)
{
    return a.slot == b.slot && a.tensor == b.tensor &&
           a.generation == b.generation;
}

static int event_equal(const ZnEvent *a, const ZnEvent *b)
{
    unsigned i;
    if (a->event != b->event || a->tile_first != b->tile_first ||
        a->tile_count != b->tile_count || a->compute_node != b->compute_node ||
        a->operation != b->operation || a->read_count != b->read_count ||
        a->retire_count != b->retire_count || a->has_destination != b->has_destination)
        return 0;
    if (a->has_destination &&
        (a->destination.address != b->destination.address ||
         a->destination.bytes != b->destination.bytes ||
         a->destination.channels != b->destination.channels ||
         a->destination.height != b->destination.height ||
         a->destination.width != b->destination.width ||
         !ref_equal(a->destination.ref, b->destination.ref)))
        return 0;
    for (i = 0; i < a->read_count; ++i)
        if (!ref_equal(a->reads[i], b->reads[i])) return 0;
    for (i = 0; i < a->retire_count; ++i)
        if (!ref_equal(a->retired[i], b->retired[i])) return 0;
    return 1;
}

static int pending_valid(const ZnNativeArenaOwnerV1 *owner,
                         const ZnDispatch *dispatch, const ZnRequest *request)
{
    if (!owner || !dispatch || !request || !owner->initialized || owner->fault ||
        owner->complete || dispatch->fault || dispatch->done || !dispatch->pending ||
        !dispatch->events || dispatch->events != owner->events ||
        dispatch->count != ZN_NATIVE_ARENA_EVENT_COUNT_V1 ||
        owner->event_count != dispatch->count || dispatch->epoch != owner->epoch ||
        request->epoch != owner->epoch || request->event_index >= dispatch->count ||
        dispatch->cursor != request->event_index || request->operation != ZN_RUN ||
        dispatch->phase != ZN_RUN || request->job != &dispatch->events[request->event_index])
        return 0;
    return dispatch->request.epoch == request->epoch &&
           dispatch->request.tag == request->tag &&
           dispatch->request.event_index == request->event_index &&
           dispatch->request.operation == request->operation &&
           ref_equal(dispatch->request.ref, request->ref) &&
           dispatch->request.job == request->job &&
           event_equal(request->job, &z100_graph_events[request->event_index]);
}

static int mapped_address(const ZnNativePlatformMappedSpanV1 *arena,
                          uint32_t physical, uint32_t bytes, uint8_t **pointer)
{
    uint64_t offset;
    uintptr_t cpu;
    if (!arena || !pointer || !arena->cpu_base ||
        arena->physical_base != ARENA_BASE || arena->bytes != ARENA_BYTES ||
        arena->cpu_bytes != ARENA_BYTES ||
        ((uintptr_t)arena->cpu_base & 63u) != 0 || physical < ARENA_BASE ||
        bytes == 0 || (physical & 63u) != 0 || (bytes & 63u) != 0)
        return 0;
    offset = (uint64_t)physical - arena->physical_base;
    cpu = (uintptr_t)arena->cpu_base;
    if (offset > arena->bytes || bytes > arena->bytes - offset ||
        arena->cpu_bytes > UINTPTR_MAX - cpu)
        return 0;
    *pointer = arena->cpu_base + (size_t)offset;
    return 1;
}

static int shape_for_ref(ZnRef ref, uint16_t before,
                         uint16_t *channels, uint16_t *height, uint16_t *width,
                         uint32_t *physical)
{
    uint16_t i;
    if (ref.slot == 0 && ref.tensor == -1 && ref.generation == 1) {
        *channels = 3; *height = 640; *width = 640;
        *physical = ARENA_BASE;
        return 1;
    }
    for (i = 0; i < before; ++i) {
        const ZnEvent *event = &z100_graph_events[i];
        if (event->has_destination && ref_equal(event->destination.ref, ref)) {
            *channels = event->destination.channels;
            *height = event->destination.height;
            *width = event->destination.width;
            *physical = event->destination.address;
            return 1;
        }
    }
    return 0;
}

static uint64_t packed_bytes(uint16_t c, uint16_t h, uint16_t w)
{
    return (((uint64_t)c + 3u) / 4u) * h * (((uint64_t)w + 15u) / 16u) * 64u;
}

int zn_native_runtime_map_read_v1(
    const ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request, uint8_t read_index,
    const ZnNativePlatformMappedSpanV1 *arena, ZnNativeRuntimeTensorMapV1 *out)
{
    ZnNativeRuntimeTensorMapV1 candidate;
    const ZnNativeArenaSlotV1 *slot;
    const ZnNativeArenaEventStateV1 *state;
    ZnRef ref;
    uint8_t *pointer;
    uint32_t expected_address;
    if (!out || !pending_valid(owner, dispatch, request) ||
        read_index >= request->job->read_count)
        return -1;
    ref = request->job->reads[read_index];
    if (ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1) return -1;
    slot = &owner->slots[ref.slot];
    state = &owner->event_state[request->event_index];
    if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
        !ref_equal(slot->ref, ref) || slot->reader_count == 0 ||
        (state->acquired_mask & (uint8_t)(1u << read_index)) == 0 ||
        slot->bytes > slot->region.capacity_bytes ||
        !mapped_address(arena, slot->region.address, slot->bytes, &pointer))
        return -1;
    memset(&candidate, 0, sizeof candidate);
    if (!shape_for_ref(ref, request->event_index, &candidate.view.channels,
                       &candidate.view.height, &candidate.view.width,
                       &expected_address) || slot->region.address != expected_address ||
        packed_bytes(candidate.view.channels, candidate.view.height,
                     candidate.view.width) != slot->bytes)
        return -1;
    candidate.physical_address = slot->region.address;
    candidate.cpu_address = pointer;
    candidate.view.epoch = request->epoch;
    candidate.view.ref = ref;
    candidate.view.data = pointer;
    candidate.view.bytes = slot->bytes;
    *out = candidate;
    return 0;
}

int zn_native_runtime_map_destination_v1(
    const ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request, const ZnNativePlatformMappedSpanV1 *arena,
    ZnNativeRuntimeTensorMapV1 *out)
{
    ZnNativeRuntimeTensorMapV1 candidate;
    const ZnDestination *destination;
    const ZnNativeArenaSlotV1 *slot;
    uint8_t *pointer;
    if (!out || !pending_valid(owner, dispatch, request) ||
        !request->job->has_destination) return -1;
    destination = &request->job->destination;
    if (destination->ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1) return -1;
    slot = &owner->slots[destination->ref.slot];
    if (!owner->event_state[request->event_index].allocated ||
        slot->state != ZN_NATIVE_ARENA_SLOT_RESERVED_V1 ||
        !ref_equal(slot->ref, destination->ref) || slot->reader_count || slot->io_count ||
        slot->region.address != destination->address || slot->bytes != destination->bytes ||
        slot->bytes > slot->region.capacity_bytes ||
        !mapped_address(arena, destination->address, destination->bytes, &pointer))
        return -1;
    memset(&candidate, 0, sizeof candidate);
    candidate.physical_address = destination->address;
    candidate.cpu_address = pointer;
    candidate.view.epoch = request->epoch;
    candidate.view.ref = destination->ref;
    candidate.view.channels = destination->channels;
    candidate.view.height = destination->height;
    candidate.view.width = destination->width;
    candidate.view.bytes = destination->bytes;
    candidate.view.data = pointer;
    *out = candidate;
    return 0;
}
