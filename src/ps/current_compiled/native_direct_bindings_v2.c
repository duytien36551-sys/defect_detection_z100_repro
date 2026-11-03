
#include "native_direct_bindings_v2.h"
#include "graph_plan.h"
#include <string.h>

typedef struct {
    uint32_t source_base, source_bytes, runs, windows;
    uint8_t supported;
} DirectEvent;

static const DirectEvent direct_events[73] = {
    {268435456u,1638400u,5120u,46080u,1},
    {270073856u,1638400u,1280u,46080u,1},
    {268435456u,819200u,1280u,10240u,1},
    {0u,0u,0u,0u,0},
    {268435456u,409600u,1280u,46080u,1},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {271712256u,819200u,640u,46080u,1},
    {268435456u,409600u,640u,10240u,1},
    {0u,0u,0u,0u,0},
    {268435456u,204800u,320u,23040u,1},
    {0u,0u,0u,0u,0},
    {268435456u,204800u,320u,23040u,1},
    {271712256u,204800u,320u,23040u,1},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {272531456u,409600u,320u,46080u,1},
    {268435456u,245760u,320u,10240u,1},
    {0u,0u,0u,0u,0},
    {268435456u,122880u,160u,23040u,1},
    {0u,0u,0u,0u,0},
    {268435456u,122880u,160u,23040u,1},
    {271712256u,122880u,160u,23040u,1},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {272941056u,245760u,160u,46080u,1},
    {268435456u,163840u,160u,10240u,1},
    {0u,0u,0u,0u,0},
    {268435456u,81920u,80u,23040u,1},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {271712256u,163840u,80u,5120u,1},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {270073856u,122880u,160u,23040u,1},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {271712256u,204800u,320u,23040u,1},
    {0u,0u,0u,0u,0},
    {271712256u,409600u,160u,23040u,1},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {268435456u,122880u,160u,23040u,1},
    {0u,0u,0u,0u,0},
    {268435456u,245760u,80u,23040u,1},
    {0u,0u,0u,0u,0},
    {0u,0u,0u,0u,0},
    {270073856u,81920u,80u,23040u,1},
    {0u,0u,0u,0u,0},
    {271712256u,409600u,640u,92160u,1},
    {272531456u,409600u,640u,92160u,1},
    {272941056u,409600u,640u,10240u,1},
    {271712256u,409600u,640u,92160u,1},
    {272941056u,409600u,640u,92160u,1},
    {271712256u,409600u,320u,5120u,1},
    {268435456u,245760u,160u,46080u,1},
    {271712256u,122880u,160u,23040u,1},
    {273350656u,122880u,160u,2560u,1},
    {268435456u,245760u,160u,46080u,1},
    {273350656u,122880u,160u,23040u,1},
    {268435456u,122880u,80u,1280u,1},
    {270073856u,163840u,40u,23040u,1},
    {268435456u,40960u,40u,5760u,1},
    {273473536u,40960u,40u,640u,1},
    {270073856u,163840u,40u,23040u,1},
    {273473536u,40960u,40u,5760u,1},
    {270073856u,40960u,20u,320u,1},
    {0u,0u,0u,0u,0},
};

static int ref_eq(ZnRef a, ZnRef b) {
    return a.slot == b.slot && a.tensor == b.tensor &&
           a.generation == b.generation;
}

static int event_eq(const ZnEvent *a, const ZnEvent *b) {
    unsigned i;
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
         !ref_eq(a->destination.ref, b->destination.ref)))
        return 0;
    for (i = 0; i < a->read_count; ++i)
        if (!ref_eq(a->reads[i], b->reads[i]))
            return 0;
    for (i = 0; i < a->retire_count; ++i)
        if (!ref_eq(a->retired[i], b->retired[i]))
            return 0;
    return 1;
}

int zn_native_direct_binding_v2(const ZnRequest *request,
    const ZnNativeDirectIdsV2 *ids,
    const ZnNativeGraphScratchLeaseV2 *source,
    ZnNativeGraphConvBindingV2 *out) {
    const ZnEvent *event;
    const DirectEvent *entry;
    ZnNativeGraphConvBindingV2 b;
    ZnNativeConvCommand *c = &b.command;
    uint64_t source_end;
    uint64_t destination_end;

    if (!request || !ids || !source || !out || !request->job ||
        request->epoch == 0 || request->tag == 0 ||
        request->operation != ZN_RUN || request->event_index >= 73)
        return -1;
    event = &z100_graph_events[request->event_index];
    entry = &direct_events[request->event_index];
    if (!event_eq(event, request->job))
        return -1;
    if (!entry->supported)
        return 1;

    source_end = (uint64_t)source->base + source->bytes;
    destination_end = (uint64_t)event->destination.address +
                      event->destination.bytes;
    if (event->operation != ZN_CONV || event->read_count != 1 ||
        !event->has_destination || event->tile_count == 0 ||
        source->epoch != request->epoch ||
        source->generation != event->reads[0].generation ||
        source->base != entry->source_base ||
        source->bytes != entry->source_bytes || (source->base & 63u) != 0 ||
        (source->bytes & 63u) != 0 || source_end > UINT64_C(0x40000000) ||
        destination_end > UINT64_C(0x40000000) ||
        ids->first_bank > 1 || ids->job_base == 0 ||
        ids->token_base == 0 || ids->tag_base == 0 ||
        ids->load_timeout_cycles == 0 ||
        ids->parameter_timeout_cycles == 0 ||
        ids->write_timeout_cycles == 0 ||
        ids->preaccept_timeout_cycles == 0 ||
        (uint64_t)ids->job_base + event->tile_count - 1u > UINT32_MAX ||
        (uint64_t)ids->token_base + entry->runs - 1u > UINT32_MAX ||
        (uint64_t)ids->tag_base + entry->windows - 1u > UINT32_MAX)
        return -1;

    memset(&b, 0, sizeof b);
    b.dispatch_epoch = request->epoch;
    b.dispatch_tag = request->tag;
    b.event_index = request->event_index;
    b.graph_read_count = event->read_count;
    b.graph_read_refs[0] = event->reads[0];
    b.destination_ref = event->destination.ref;
    b.scratch = *source;
    b.source_span.base = source->base;
    b.source_span.bytes = entry->source_bytes;
    b.expected_cookie = request->tag;
    b.expected_job_base = ids->job_base;
    b.expected_token_base = ids->token_base;
    b.expected_tag_base = ids->tag_base;
    b.expected_tiles = event->tile_count;
    memcpy(b.package_sha256, "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c", 65);
    memcpy(b.checkpoint_sha256, "2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6", 65);
    memcpy(b.graph_sha256, "9d6064e37e92e61c687608d2c5e216cccb31e0b1fc9603de0c8b21eb3acbae9f", 65);

    c->request_cookie = request->tag;
    c->epoch = request->epoch;
    c->event = event->event;
    c->model_crc32 = ZN_NATIVE_CONV_MMIO_MODEL_CRC32;
    c->job_base = ids->job_base;
    c->token_base = ids->token_base;
    c->tag_base = ids->tag_base;
    c->flags = ZN_NC_SHADOW_SOURCE_LEASE_VALID |
               ZN_NC_SHADOW_DEST_RESERVATION_VALID |
               (ids->first_bank ? ZN_NC_SHADOW_FIRST_BANK : 0u);
    c->source_base = source->base;
    c->source_generation = source->generation;
    c->source_lease_region_begin = source->base;
    c->source_lease_region_end.low = (uint32_t)source_end;
    c->source_lease_region_end.high = (uint8_t)(source_end >> 32);
    c->destination_base = event->destination.address;
    c->destination_generation = event->destination.ref.generation;
    c->destination_reservation_region_begin = event->destination.address;
    c->destination_reservation_region_end.low = (uint32_t)destination_end;
    c->destination_reservation_region_end.high =
        (uint8_t)(destination_end >> 32);
    c->parameter_directory_base = 553648128u;
    c->parameter_count = 173u;
    c->parameter_payload_begin = 536870912u;
    c->parameter_payload_end.low = 539993344u;
    c->load_timeout_cycles = ids->load_timeout_cycles;
    c->parameter_timeout_cycles = ids->parameter_timeout_cycles;
    c->write_timeout_cycles = ids->write_timeout_cycles;
    c->preaccept_timeout_cycles = ids->preaccept_timeout_cycles;
    if (zn_native_conv_command_validate_v1(c) != ZN_NATIVE_CONV_COMMAND_OK)
        return -1;
    *out = b;
    return 0;
}
