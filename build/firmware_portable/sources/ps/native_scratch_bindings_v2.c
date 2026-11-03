
#include "native_scratch_bindings_v2.h"
#include "graph_plan.h"
#include <string.h>
typedef struct {uint32_t bytes,runs,windows;uint8_t supported;} ViewInput;
static const ViewInput views[73]={
    {0},
    {0},
    {0},
    {409600u,1280u,46080u,1},
    {0},
    {0},
    {1228800u,1280u,15360u,1},
    {0},
    {0},
    {204800u,320u,23040u,1},
    {0},
    {0},
    {0},
    {0},
    {0},
    {819200u,640u,20480u,1},
    {0},
    {0},
    {122880u,160u,23040u,1},
    {0},
    {0},
    {0},
    {0},
    {0},
    {491520u,320u,20480u,1},
    {0},
    {0},
    {81920u,80u,23040u,1},
    {0},
    {0},
    {245760u,160u,15360u,1},
    {0},
    {0},
    {0},
    {0},
    {327680u,160u,20480u,1},
    {737280u,320u,30720u,1},
    {122880u,160u,23040u,1},
    {0},
    {368640u,320u,15360u,1},
    {1228800u,640u,30720u,1},
    {204800u,320u,23040u,1},
    {0},
    {614400u,640u,15360u,1},
    {0},
    {368640u,320u,15360u,1},
    {122880u,160u,23040u,1},
    {0},
    {368640u,320u,15360u,1},
    {0},
    {245760u,160u,15360u,1},
    {81920u,80u,23040u,1},
    {0},
    {245760u,160u,15360u,1},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
    {0},
};
static int ref_eq(ZnRef a,ZnRef b) {
    return a.slot==b.slot && a.tensor==b.tensor && a.generation==b.generation;
}
static int event_eq(const ZnEvent *a,const ZnEvent *b) {
    unsigned i;
    if(a->event!=b->event || a->tile_first!=b->tile_first ||
       a->tile_count!=b->tile_count || a->compute_node!=b->compute_node ||
       a->operation!=b->operation || a->read_count!=b->read_count ||
       a->retire_count!=b->retire_count || a->has_destination!=b->has_destination)
        return 0;
    if(a->has_destination &&
       (a->destination.address!=b->destination.address ||
        a->destination.bytes!=b->destination.bytes ||
        a->destination.channels!=b->destination.channels ||
        a->destination.height!=b->destination.height ||
        a->destination.width!=b->destination.width ||
        !ref_eq(a->destination.ref,b->destination.ref))) return 0;
    for(i=0;i<a->read_count;i++) if(!ref_eq(a->reads[i],b->reads[i])) return 0;
    for(i=0;i<a->retire_count;i++) if(!ref_eq(a->retired[i],b->retired[i])) return 0;
    return 1;
}

static int overlap(uint64_t a,uint64_t n,uint64_t b,uint64_t m) {
    return a<b+m && b<a+n;
}
int zn_native_scratch_binding_v2(const ZnRequest *r,const ZnNativeScratchIdsV2 *ids,
    const ZnNativeGraphScratchLeaseV2 *scratch,ZnNativeGraphConvBindingV2 *out) {
    const ZnEvent *e;const ViewInput *v;ZnNativeGraphConvBindingV2 b;
    ZnNativeConvCommand *c=&b.command;uint64_t end;unsigned i;
    if(!r || !ids || !scratch || !out || !r->job || !r->epoch || !r->tag ||
       r->operation!=ZN_RUN || r->event_index>=73) return -1;
    e=&z100_graph_events[r->event_index];v=&views[r->event_index];
    if(!event_eq(e,r->job)) return -1;
    if(!v->supported) return 1;
    end=(uint64_t)scratch->base+scratch->bytes;
    if(scratch->epoch!=r->epoch || !scratch->generation || !scratch->base ||
       scratch->base%64u || scratch->bytes%64u || scratch->bytes<v->bytes ||
       end>UINT64_C(0x40000000) ||
       overlap(scratch->base,scratch->bytes,268435456u,5201920u) ||
       overlap(scratch->base,scratch->bytes,536870912u,3122432u) ||
       overlap(scratch->base,scratch->bytes,553648128u,5568u) ||
       ids->first_bank>1 || !ids->job_base || !ids->token_base || !ids->tag_base ||
       (uint64_t)ids->job_base+e->tile_count-1>UINT32_MAX ||
       (uint64_t)ids->token_base+v->runs-1>UINT32_MAX ||
       (uint64_t)ids->tag_base+v->windows-1>UINT32_MAX) return -1;
    memset(&b,0,sizeof b);b.dispatch_epoch=r->epoch;b.dispatch_tag=r->tag;
    b.event_index=r->event_index;b.graph_read_count=e->read_count;
    for(i=0;i<e->read_count;i++) b.graph_read_refs[i]=e->reads[i];
    b.destination_ref=e->destination.ref;b.scratch=*scratch;
    b.source_span.base=scratch->base;b.source_span.bytes=v->bytes;
    b.expected_cookie=r->tag;b.expected_job_base=ids->job_base;
    b.expected_token_base=ids->token_base;b.expected_tag_base=ids->tag_base;
    b.expected_tiles=e->tile_count;
    memcpy(b.package_sha256,"65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c",65);memcpy(b.checkpoint_sha256,"2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6",65);
    memcpy(b.graph_sha256,"9d6064e37e92e61c687608d2c5e216cccb31e0b1fc9603de0c8b21eb3acbae9f",65);
    c->request_cookie=r->tag;c->epoch=r->epoch;c->event=e->event;
    c->model_crc32=ZN_NATIVE_CONV_MMIO_MODEL_CRC32;c->job_base=ids->job_base;
    c->token_base=ids->token_base;c->tag_base=ids->tag_base;
    c->flags=ZN_NC_SHADOW_SOURCE_LEASE_VALID|ZN_NC_SHADOW_DEST_RESERVATION_VALID|
        (ids->first_bank?ZN_NC_SHADOW_FIRST_BANK:0);
    c->source_base=scratch->base;c->source_generation=scratch->generation;
    c->source_lease_region_begin=scratch->base;c->source_lease_region_end.low=(uint32_t)end;
    c->destination_base=e->destination.address;c->destination_generation=e->destination.ref.generation;
    c->destination_reservation_region_begin=e->destination.address;
    c->destination_reservation_region_end.low=e->destination.address+e->destination.bytes;
    c->parameter_directory_base=553648128u;c->parameter_count=173;
    c->parameter_payload_begin=536870912u;c->parameter_payload_end.low=539993344u;
    c->load_timeout_cycles=ids->load_timeout_cycles;c->parameter_timeout_cycles=ids->parameter_timeout_cycles;
    c->write_timeout_cycles=ids->write_timeout_cycles;c->preaccept_timeout_cycles=ids->preaccept_timeout_cycles;
    if(zn_native_conv_command_validate_v1(c)!=ZN_NATIVE_CONV_COMMAND_OK) return -1;
    *out=b;return 0;
}
