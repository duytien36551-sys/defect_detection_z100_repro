#include "native_graph_session_v1.h"

#include <string.h>

#define SESSION_MAGIC UINT32_C(0x4e475331)

static int separated(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t av = (uintptr_t)a, bv = (uintptr_t)b;
    return a && b && an && bn && an <= UINTPTR_MAX-av && bn <= UINTPTR_MAX-bv &&
        (av+an <= bv || bv+bn <= av);
}

static int exact(const ZnNativePlatformMappedSpanV1 *m, uint64_t base, uint64_t bytes)
{
    return m->physical_base == base && m->bytes == bytes && m->cpu_bytes == bytes && m->cpu_base &&
        !((uintptr_t)m->cpu_base & (uintptr_t)63u) && m->cpu_bytes <= UINTPTR_MAX-(uintptr_t)m->cpu_base;
}

static int reservation(const ZnNativePlatformReservationV1 *r, const ZnNativePlatformMappedSpanV1 *m)
{
    return r->address == m->physical_base && r->bytes == m->bytes;
}

static int preflight(const ZnNativeGraphSessionV1 *s, const ZnNativeGraphSessionConfigV1 *c)
{
    const ZnNativePlatformMemoryRequestV1 *m = &c->model;
    const ZnNativePlatformMappedSpanV1 *maps[5] = {&c->frame.arena, &c->frame.heads,
        &m->parameter_mapping, &m->directory_mapping, &c->frame.scratch};
    const void *metadata[9] = {s, c, m->parameter_payload.data, m->directory.data,
        m->package_sha256, m->checkpoint_sha256, m->graph_sha256,
        m->parameter_payload.sha256, m->directory.sha256};
    const size_t lengths[9] = {sizeof *s, sizeof *c, (size_t)ZN_NPMV1_PARAMETER_BYTES,
        (size_t)ZN_NPMV1_DIRECTORY_BYTES, 65, 65, 65, 65, 65};
    size_t i, j;
    if (!c->frame.memory.reserve || !c->frame.memory.copy ||
        !exact(&m->parameter_mapping, ZN_NPMV1_PARAMETER_ADDRESS, ZN_NPMV1_PARAMETER_BYTES) ||
        !exact(&m->directory_mapping, ZN_NPMV1_DIRECTORY_ADDRESS, ZN_NPMV1_DIRECTORY_BYTES) ||
        !reservation(&m->parameter_reservation, &m->parameter_mapping) ||
        !reservation(&m->directory_reservation, &m->directory_mapping) ||
        !reservation(&m->view_scratch_reservation, &c->frame.scratch) ||
        m->view_scratch_mapping.physical_base != c->frame.scratch.physical_base ||
        m->view_scratch_mapping.bytes != c->frame.scratch.bytes ||
        m->view_scratch_mapping.cpu_base != c->frame.scratch.cpu_base ||
        m->view_scratch_mapping.cpu_bytes != c->frame.scratch.cpu_bytes)
        return 0;
    /* Frame init separately checks its exact physical spans, plan and callbacks.
     * Check all CPU spans here before its first metadata write. */
    for (i = 0; i < 5; ++i) {
        for (j = 0; j < 9; ++j)
            if (!separated(maps[i]->cpu_base, maps[i]->cpu_bytes, metadata[j], lengths[j])) return 0;
        for (j = i+1; j < 5; ++j)
            if (!separated(maps[i]->cpu_base, maps[i]->cpu_bytes, maps[j]->cpu_base, maps[j]->cpu_bytes)) return 0;
    }
    for (i = 1; i < 9; ++i)
        if (!separated(s, sizeof *s, metadata[i], lengths[i])) return 0;
    return 1;
}

static int broken(ZnNativeGraphSessionV1 *s)
{
    s->state = ZN_NATIVE_SESSION_V1_FAILED;
    return s->state;
}

static int reserve_one(ZnNativeGraphSessionV1 *s, const ZnNativePlatformReservationV1 *r, uint32_t bit)
{
    s->attempted_reservations |= bit;
    s->callback_status = s->frame.config.memory.reserve(s->frame.config.memory_context, r);
    if (s->callback_status) return s->callback_status;
    s->reserved |= bit;
    return 0;
}

static int model_reserve(void *context, const ZnNativePlatformReservationV1 *r)
{
    ZnNativeGraphSessionV1 *s = context;
    uint32_t bit = r->address == ZN_NPMV1_PARAMETER_ADDRESS ? ZN_NATIVE_SESSION_PARAMETERS_V1 :
        r->address == ZN_NPMV1_DIRECTORY_ADDRESS ? ZN_NATIVE_SESSION_DIRECTORY_V1 : ZN_NATIVE_SESSION_SCRATCH_V1;
    return reserve_one(s, r, bit);
}

static int model_copy(void *context, uint8_t *to, const uint8_t *from, size_t bytes)
{
    ZnNativeGraphSessionV1 *s = context;
    return s->frame.config.memory.copy(s->frame.config.memory_context, to, from, bytes);
}

static int model_clean(void *context, void *address, size_t bytes)
{
    ZnNativeGraphSessionV1 *s = context;
    return s->frame.config.memory.cache_clean(s->frame.config.memory_context, address, bytes);
}

static int model_invalidate(void *context, void *address, size_t bytes)
{
    ZnNativeGraphSessionV1 *s = context;
    return s->frame.config.memory.invalidate_readback(s->frame.config.memory_context, address, bytes);
}

static int model_barrier(void *context)
{
    ZnNativeGraphSessionV1 *s = context;
    return s->frame.config.memory.barrier(s->frame.config.memory_context);
}

int zn_native_graph_session_prepare_v1(ZnNativeGraphSessionV1 *s, const ZnNativeGraphSessionConfigV1 *c)
{
    ZnNativePlatformReservationV1 r;
    const ZnNativePlatformMemoryOpsV1 ops = {model_reserve, model_copy, model_clean, model_barrier, model_invalidate};
    if (!s || !c) return ZN_NATIVE_SESSION_V1_ARGUMENT;
    if (s->magic) return ZN_NATIVE_SESSION_V1_STATE;
    if (!preflight(s, c)) return ZN_NATIVE_SESSION_V1_ARGUMENT;
    memset(s, 0, sizeof *s);
    s->magic = SESSION_MAGIC;
    s->state = ZN_NATIVE_SESSION_V1_FAILED;
    s->model = c->model;
    s->prepare_code = zn_native_graph_frame_init_v1(&s->frame, &c->frame);
    if (s->prepare_code != ZN_NATIVE_FRAME_V1_READY) return broken(s);
    r.address = c->frame.arena.physical_base; r.bytes = c->frame.arena.bytes;
    if (reserve_one(s, &r, ZN_NATIVE_SESSION_ARENA_V1)) return broken(s);
    r.address = c->frame.heads.physical_base; r.bytes = c->frame.heads.bytes;
    if (reserve_one(s, &r, ZN_NATIVE_SESSION_HEADS_V1)) return broken(s);
    s->prepare_code = zn_native_platform_memory_prepare_v1(&s->model, &ops, s, &s->model_state);
    if (s->prepare_code != ZN_NPMV1_OK || !s->model_state.ready || s->reserved != UINT32_C(31)) return broken(s);
    s->state = ZN_NATIVE_SESSION_V1_READY;
    return s->state;
}

static int usable(const ZnNativeGraphSessionV1 *s)
{
    return s && s->magic == SESSION_MAGIC && s->state == ZN_NATIVE_SESSION_V1_READY &&
        s->model_state.ready && s->reserved == UINT32_C(31);
}

static int outside_session(const ZnNativeGraphSessionV1 *s, const void *p, size_t bytes)
{
    return separated(p, bytes, s, sizeof *s) &&
        separated(p, bytes, s->model.parameter_mapping.cpu_base, s->model.parameter_mapping.cpu_bytes) &&
        separated(p, bytes, s->model.directory_mapping.cpu_base, s->model.directory_mapping.cpu_bytes) &&
        separated(p, bytes, s->model.parameter_payload.data, (size_t)ZN_NPMV1_PARAMETER_BYTES) &&
        separated(p, bytes, s->model.directory.data, (size_t)ZN_NPMV1_DIRECTORY_BYTES) &&
        separated(p, bytes, s->model.package_sha256, 65) &&
        separated(p, bytes, s->model.checkpoint_sha256, 65) &&
        separated(p, bytes, s->model.graph_sha256, 65) &&
        separated(p, bytes, s->model.parameter_payload.sha256, 65) &&
        separated(p, bytes, s->model.directory.sha256, 65);
}

int zn_native_graph_session_start_v1(ZnNativeGraphSessionV1 *s, const uint8_t *input, size_t bytes)
{
    int code;
    if (!usable(s)) return ZN_NATIVE_SESSION_V1_STATE;
    if (!outside_session(s, input, bytes)) return ZN_NATIVE_SESSION_V1_ARGUMENT;
    code = zn_native_graph_frame_start_v1(&s->frame, input, bytes);
    if (code == ZN_NATIVE_FRAME_V1_FAILED) return broken(s);
    return code;
}

int zn_native_graph_session_poll_v1(ZnNativeGraphSessionV1 *s, uint32_t steps)
{
    int code;
    if (!usable(s)) return ZN_NATIVE_SESSION_V1_STATE;
    code = zn_native_graph_frame_poll_v1(&s->frame, steps);
    if (code == ZN_NATIVE_FRAME_V1_FAILED) return broken(s);
    return code;
}

int zn_native_graph_session_heads_v1(const ZnNativeGraphSessionV1 *s, const uint8_t **data, size_t *bytes)
{
    if (!usable(s)) return ZN_NATIVE_SESSION_V1_STATE;
    if (!outside_session(s, data, sizeof *data) || !outside_session(s, bytes, sizeof *bytes))
        return ZN_NATIVE_SESSION_V1_ARGUMENT;
    return zn_native_graph_frame_heads_v1(&s->frame, data, bytes);
}

int zn_native_graph_session_rearm_v1(ZnNativeGraphSessionV1 *s, uint32_t epoch)
{
    int code;
    if (!usable(s)) return ZN_NATIVE_SESSION_V1_STATE;
    code = zn_native_graph_frame_rearm_v1(&s->frame, epoch);
    if (code == ZN_NATIVE_FRAME_V1_FAILED) return broken(s);
    return code;
}
