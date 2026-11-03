#include "native_pool_graph_adapter_v1.h"
#include <string.h>

static int ref_equal(ZnRef a, ZnRef b) {
    return a.generation==b.generation && a.tensor==b.tensor && a.slot==b.slot;
}
static int request_equal(const ZnRequest *a, const ZnRequest *b) {
    return a && b && a->epoch==b->epoch && a->tag==b->tag &&
        a->event_index==b->event_index && a->operation==b->operation &&
        a->job==b->job && ref_equal(a->ref,b->ref);
}
static uint64_t end64(ZnNativeConvEnd33 end) {
    return ((uint64_t)end.high<<32)|end.low;
}
static int live_request(const ZnPoolGraphAdapterV1 *p, const ZnRequest *r) {
    const ZnEvent *e;
    if (!p || !p->bound || p->fault || !r || !p->owner || !p->dispatch ||
        !request_equal(&p->request,r) || !p->owner->initialized ||
        p->owner->fault || p->dispatch->fault || !p->dispatch->pending ||
        !request_equal(&p->dispatch->request,r) || r->operation!=ZN_RUN ||
        r->epoch!=p->owner->epoch || p->dispatch->epoch!=r->epoch ||
        p->dispatch->events!=p->owner->events ||
        p->dispatch->cursor!=r->event_index || r->event_index>=p->owner->event_count ||
        r->job!=&p->owner->events[r->event_index]) return 0;
    e=r->job;
    return e->operation==ZN_POOL && e->read_count==1 && e->has_destination &&
        e->event>=70 && e->event<=72 && e->destination.bytes==81920 &&
        e->destination.channels==128 && e->destination.height==20 && e->destination.width==20 &&
        e->reads[0].slot<ZN_NATIVE_ARENA_SLOT_COUNT_V1 &&
        e->destination.ref.slot<ZN_NATIVE_ARENA_SLOT_COUNT_V1;
}
static int leases_valid(const ZnPoolGraphAdapterV1 *p, const ZnRequest *r) {
    const ZnEvent *e=r->job;
    const ZnNativeArenaSlotV1 *s=&p->owner->slots[e->reads[0].slot];
    const ZnNativeArenaSlotV1 *d=&p->owner->slots[e->destination.ref.slot];
    const ZnNativeConvCommand *c=&p->command;
    return ref_equal(s->ref,e->reads[0]) && ref_equal(d->ref,e->destination.ref) &&
        s->state==ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 && s->reader_count!=0 &&
        d->state==ZN_NATIVE_ARENA_SLOT_RESERVED_V1 && s->bytes==81920 &&
        c->epoch==r->epoch && c->event==e->event && c->request_cookie==r->tag &&
        c->source_base==s->region.address && c->source_generation==s->ref.generation &&
        c->source_lease_region_begin==s->region.address &&
        end64(c->source_lease_region_end)==(uint64_t)s->region.address+s->region.capacity_bytes &&
        c->destination_base==e->destination.address && c->destination_base==d->region.address &&
        c->destination_generation==d->ref.generation &&
        c->destination_reservation_region_begin==d->region.address &&
        end64(c->destination_reservation_region_end)==(uint64_t)d->region.address+d->region.capacity_bytes;
}

int zn_pool_graph_bind_v1(ZnPoolGraphAdapterV1 *p, ZnNativeArenaOwnerV1 *owner,
    ZnDispatch *dispatch, const ZnRequest *request, const ZnNativeConvCommand *cmd,
    ZnNativeConvDriverV2 *driver, const ZnPoolCacheOpsV1 *cache) {
    ZnPoolGraphAdapterV1 candidate;
    if (!p || p->bound || p->fault || !owner || !dispatch || !request || !cmd ||
        !driver || driver->state!=ZN_NATIVE_CONV_STATE_V2_IDLE || driver->ownership_held ||
        !cache || !cache->clean || !cache->invalidate || !cache->barrier ||
        !zn_native_pool_command_valid_v1(cmd)) return -1;
    memset(&candidate,0,sizeof candidate);
    candidate.owner=owner; candidate.dispatch=dispatch; candidate.driver=driver;
    candidate.request=*request; candidate.command=*cmd; candidate.cache=*cache; candidate.bound=1;
    if (!live_request(&candidate,request) || !leases_valid(&candidate,request)) return -1;
    *p=candidate;
    return 0;
}

int zn_pool_graph_step_v1(void *opaque, const ZnRequest *request,
    const ZnNativeArenaNonConvSourceV1 *source,
    const ZnNativeArenaNonConvOutputV1 *output, uint32_t bytes) {
    ZnPoolGraphAdapterV1 *p=opaque;
    ZnPoolMappingV1 src,dst;
    int code;
    if (!p) return -1;
    if (!live_request(p,request) || !leases_valid(p,request) || !source || !output ||
        source->physical_address!=p->command.source_base || source->view.epoch!=request->epoch ||
        !ref_equal(source->view.ref,request->job->reads[0]) || source->view.bytes!=81920 ||
        source->view.channels!=128 || source->view.height!=20 || source->view.width!=20 ||
        output->physical_address!=p->command.destination_base || output->capacity_bytes<81920 ||
        bytes!=81920 || !p->owner->event_state[request->event_index].run_started ||
        !p->owner->slots[request->job->destination.ref.slot].io_count) {
        p->fault=1; return -1;
    }
    if (p->async.state==ZN_POOL_ASYNC_IDLE) {
        src.physical_address=source->physical_address; src.cpu_address=(void *)source->view.data; src.bytes=81920;
        dst.physical_address=output->physical_address; dst.cpu_address=output->data; dst.bytes=81920;
        code=zn_pool_async_begin_v1(&p->async,p->driver,&p->command,&src,&dst,&p->cache);
    } else {
        if (p->async.source.cpu_address!=source->view.data || p->async.destination.cpu_address!=output->data) {
            p->fault=1; return -1;
        }
        code=zn_pool_async_poll_v1(&p->async);
    }
    if (code==ZN_POOL_ASYNC_ERROR) p->fault=1;
    return code;
}

int zn_pool_graph_drained_v1(const ZnPoolGraphAdapterV1 *p, const ZnRequest *r) {
    return p && p->bound && !p->fault && request_equal(&p->request,r) &&
        p->async.state==ZN_POOL_ASYNC_COMPLETE && p->driver &&
        p->driver->state==ZN_NATIVE_CONV_STATE_V2_IDLE && !p->driver->ownership_held;
}
int zn_pool_graph_visible_v1(const ZnPoolGraphAdapterV1 *p, const ZnRequest *r,
    const ZnNativeArenaNonConvOutputV1 *o, uint32_t bytes) {
    return zn_pool_graph_drained_v1(p,r) && o && bytes==81920 && o->capacity_bytes>=bytes &&
        o->physical_address==p->command.destination_base &&
        o->data==p->async.destination.cpu_address ? 0 : -1;
}
int zn_pool_graph_release_v1(ZnPoolGraphAdapterV1 *p) {
    const ZnNativeArenaEventStateV1 *state;
    if (!p || !zn_pool_graph_drained_v1(p,&p->request) || p->owner->fault ||
        p->dispatch->fault) return -1;
    state=&p->owner->event_state[p->request.event_index];
    if (!state->run_acked || !state->drained || !state->io_quiescent || state->returned_mask!=1)
        return -1;
    memset(p,0,sizeof *p);
    return 0;
}
int zn_pool_graph_cancel_v1(ZnPoolGraphAdapterV1 *p) {
    int code;
    if (!p || !p->bound) return -1;
    p->fault=1;
    code=zn_pool_async_cancel_v1(&p->async);
    return code;
}
int zn_pool_graph_abort_drain_v1(ZnPoolGraphAdapterV1 *p) {
    if (!p || !p->bound) return -1;
    p->fault=1;
    return zn_pool_async_abort_drain_v1(&p->async);
}
