#include "native_pool_scheduler_v1.h"
#include <string.h>

static int config_valid(const ZnPoolScheduleConfigV1 *c) {
    return c && c->job_base && c->token_base && c->tag_base &&
        c->job_base<=UINT32_MAX-2 && c->token_base<=UINT32_MAX-2 && c->tag_base<=UINT32_MAX-2 &&
        c->load_timeout && c->compute_timeout && c->write_timeout && c->preaccept_timeout && c->first_bank<=1;
}
int zn_pool_scheduler_init_v1(ZnPoolSchedulerV1 *p, ZnNativeArenaOwnerV1 *o,
    ZnDispatch *d, ZnNativeConvDriverV2 *driver, const ZnPoolCacheOpsV1 *cache,
    const ZnPoolScheduleConfigV1 *config) {
    if (!p || p->initialized || !o || !d || !o->initialized || o->fault || d->fault ||
        o->events!=d->events || o->epoch!=d->epoch || !driver ||
        driver->state!=ZN_NATIVE_CONV_STATE_V2_IDLE || driver->ownership_held ||
        !cache || !cache->clean || !cache->invalidate || !cache->barrier || !config_valid(config)) return -1;
    memset(p,0,sizeof *p);p->owner=o;p->dispatch=d;p->driver=driver;
    p->cache=*cache;p->config=*config;p->initialized=1;
    return 0;
}
int zn_pool_scheduler_command_v1(const ZnPoolSchedulerV1 *p, const ZnRequest *r, ZnNativeConvCommand *out) {
    static const uint8_t src_slots[3]={0,1,2}, dst_slots[3]={1,2,5};
    static const uint32_t addresses[3]={270073856u,271712256u,273350656u};
    const ZnEvent *e;
    const ZnNativeArenaSlotV1 *s,*d;
    ZnNativeConvCommand c;
    uint32_t i;
    uint64_t se,de;
    if (!p || !p->initialized || p->fault || !r || !out || !r->job || !config_valid(&p->config) ||
        r->operation!=ZN_RUN || r->event_index<32 || r->event_index>34 ||
        r->epoch!=p->owner->epoch || !r->epoch || !r->tag || p->owner->fault || p->dispatch->fault ||
        !p->dispatch->pending || p->dispatch->cursor!=r->event_index ||
        r->job!=&p->owner->events[r->event_index] || p->dispatch->events!=p->owner->events ||
        p->dispatch->request.tag!=r->tag || p->dispatch->request.job!=r->job ||
        p->dispatch->request.operation!=ZN_RUN) return -1;
    i=r->event_index-32;e=r->job;
    if (e->event!=70+i || e->compute_node!=(int16_t)(70+i) || e->tile_first!=104 || e->tile_count ||
        e->operation!=ZN_POOL || e->read_count!=1 || e->retire_count || !e->has_destination ||
        e->reads[0].slot!=src_slots[i] || e->reads[0].generation!=33+i || e->reads[0].tensor!=(int32_t)(69+i) ||
        e->destination.ref.slot!=dst_slots[i] || e->destination.ref.generation!=34+i ||
        e->destination.ref.tensor!=(int32_t)(70+i) || e->destination.address!=addresses[i] ||
        e->destination.bytes!=81920 || e->destination.channels!=128 ||
        e->destination.height!=20 || e->destination.width!=20) return -1;
    s=&p->owner->slots[src_slots[i]];d=&p->owner->slots[dst_slots[i]];
    se=(uint64_t)s->region.address+s->region.capacity_bytes;
    de=(uint64_t)d->region.address+d->region.capacity_bytes;
    if (se>UINT32_MAX || de>UINT32_MAX) return -1;
    memset(&c,0,sizeof c);
    c.request_cookie=r->tag;c.epoch=r->epoch;c.event=e->event;
    c.model_crc32=ZN_NATIVE_CONV_MMIO_MODEL_CRC32;
    c.job_base=p->config.job_base+i;c.token_base=p->config.token_base+i;c.tag_base=p->config.tag_base+i;
    c.flags=ZN_NC_SHADOW_SOURCE_LEASE_VALID|ZN_NC_SHADOW_DEST_RESERVATION_VALID|
        (p->config.first_bank?ZN_NC_SHADOW_FIRST_BANK:0);
    c.source_base=s->region.address;c.source_generation=e->reads[0].generation;
    c.source_lease_region_begin=s->region.address;c.source_lease_region_end.low=(uint32_t)se;
    c.destination_base=d->region.address;c.destination_generation=e->destination.ref.generation;
    c.destination_reservation_region_begin=d->region.address;c.destination_reservation_region_end.low=(uint32_t)de;
    c.parameter_directory_base=0x21000000u;c.parameter_count=173;
    c.parameter_payload_begin=0x20000000u;c.parameter_payload_end.low=0x202fa500u;
    c.load_timeout_cycles=p->config.load_timeout;c.parameter_timeout_cycles=p->config.compute_timeout;
    c.write_timeout_cycles=p->config.write_timeout;c.preaccept_timeout_cycles=p->config.preaccept_timeout;
    if (!zn_native_pool_command_valid_v1(&c)) return -1;
    *out=c;return 0;
}
int zn_pool_scheduler_step_v1(void *opaque, const ZnRequest *r,
    const ZnNativeArenaNonConvSourceV1 *s,const ZnNativeArenaNonConvOutputV1 *d,uint32_t bytes) {
    ZnPoolSchedulerV1 *p=opaque;
    ZnNativeConvCommand c;
    int code;
    if (!p || !p->initialized || p->fault || !r || !r->job) return -1;
    if (p->adapter.bound && (p->adapter.request.epoch!=r->epoch || p->adapter.request.tag!=r->tag ||
        p->adapter.request.event_index!=r->event_index || p->adapter.request.job!=r->job)) {
        if (zn_pool_graph_release_v1(&p->adapter)!=0) {p->fault=1;return -1;}
    }
    if (!p->adapter.bound) {
        if ((p->last_epoch && (r->epoch<p->last_epoch ||
             (r->epoch==p->last_epoch && r->job->event<=p->last_event))) ||
            zn_pool_scheduler_command_v1(p,r,&c)!=0 ||
            zn_pool_graph_bind_v1(&p->adapter,p->owner,p->dispatch,r,&c,p->driver,&p->cache)!=0) {
            p->fault=1;return -1;
        }
        p->last_epoch=r->epoch;p->last_event=r->job->event;
    }
    code=zn_pool_graph_step_v1(&p->adapter,r,s,d,bytes);
    if (code<0)p->fault=1;
    return code;
}
int zn_pool_scheduler_abort_v1(ZnPoolSchedulerV1 *p) {
    if (!p || !p->initialized || !p->adapter.bound) return -1;
    p->fault=1;return zn_pool_graph_abort_drain_v1(&p->adapter);
}
