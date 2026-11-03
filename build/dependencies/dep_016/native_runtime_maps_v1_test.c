#include "native_runtime_maps_v1.h"
#include "graph_plan.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL line=%d\n", __LINE__); return 1; } } while (0)

static ZnNativeArenaConfigV1 config(void)
{
    const ZnNativeArenaRegionV1 regions[7] = {
        {268435456u,1638400u}, {270073856u,1638400u}, {271712256u,819200u},
        {272531456u,409600u}, {272941056u,409600u}, {273350656u,122880u},
        {273473536u,163840u}
    };
    ZnNativeArenaConfigV1 c = {0};
    c.arena_base=268435456u; c.arena_end=273637376u;
    c.arena_bytes=5201920u; c.alignment=4096u;
    memcpy(c.slots,regions,sizeof regions);
    memcpy(c.package_sha256,ZN_NATIVE_ARENA_PACKAGE_SHA256_V1,sizeof c.package_sha256);
    memcpy(c.graph_sha256,ZN_NATIVE_ARENA_GRAPH_SHA256_V1,sizeof c.graph_sha256);
    memcpy(c.plan_sha256,ZN_NATIVE_ARENA_PLAN_SHA256_V1,sizeof c.plan_sha256);
    memcpy(c.manifest_sha256,ZN_NATIVE_ARENA_MANIFEST_SHA256_V1,sizeof c.manifest_sha256);
    return c;
}

static int rejection_checks(ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
                            ZnRequest *request, ZnNativePlatformMappedSpanV1 *arena)
{
    ZnNativeRuntimeTensorMapV1 out, before;
    ZnNativeArenaSlotV1 *slot=&owner->slots[request->job->reads[0].slot];
    ZnNativeArenaSlotV1 saved=*slot;
    ZnNativePlatformMappedSpanV1 bad=*arena;
    uint8_t acquired=owner->event_state[request->event_index].acquired_mask;
    memset(&out,0xa5,sizeof out); before=out;
    ++request->tag;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,arena,&out)==-1);
    --request->tag;
    ++slot->ref.generation;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,arena,&out)==-1);
    *slot=saved; slot->reader_count=0;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,arena,&out)==-1);
    *slot=saved; slot->region.address+=64;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,arena,&out)==-1);
    *slot=saved; slot->bytes-=64;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,arena,&out)==-1);
    *slot=saved;
    owner->event_state[request->event_index].acquired_mask=0;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,arena,&out)==-1);
    owner->event_state[request->event_index].acquired_mask=acquired;
    --bad.cpu_bytes;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,&bad,&out)==-1);
    bad=*arena; ++bad.cpu_base;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,&bad,&out)==-1);
    bad=*arena; bad.physical_base+=64;
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,&bad,&out)==-1);
    bad=*arena; bad.cpu_base=(uint8_t *)(UINTPTR_MAX & ~(uintptr_t)63u);
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,0,&bad,&out)==-1);
    CHECK(zn_native_runtime_map_read_v1(owner,dispatch,request,
        request->job->read_count,arena,&out)==-1);
    CHECK(memcmp(&out,&before,sizeof out)==0);
    return 0;
}

int main(void)
{
    ZnNativeArenaOwnerV1 owner={0};
    ZnNativeArenaConfigV1 c=config();
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativePlatformMappedSpanV1 arena={0};
    ZnNativeRuntimeTensorMapV1 mapped;
    uint8_t *allocation=malloc(5201920u+63u);
    unsigned reads=0, destinations=0, runs=0, rejects=0, steps=0;
    int next;
    size_t i;
    CHECK(allocation!=NULL);
    arena.physical_base=c.arena_base; arena.bytes=c.arena_bytes;
    arena.cpu_bytes=c.arena_bytes;
    arena.cpu_base=(uint8_t *)(((uintptr_t)allocation+63u)&~(uintptr_t)63u);
    memset(arena.cpu_base,0xa5,arena.cpu_bytes);
    CHECK(zn_dispatch_init(&dispatch,z100_graph_events,73,200)==0);
    CHECK(zn_native_arena_owner_init_v1(&owner,&c,&dispatch,200)==0);
    while ((next=zn_dispatch_next(&dispatch,&request))==1 && steps++<700u) {
        if (request.operation==ZN_RUN) {
            ZnNativeArenaCompletionEvidenceV1 evidence={0};
            uint8_t r;
            CHECK(rejection_checks(&owner,&dispatch,&request,&arena)==0);
            rejects+=11;
            for (r=0;r<request.job->read_count;++r) {
                const ZnNativeArenaSlotV1 *slot=&owner.slots[request.job->reads[r].slot];
                CHECK(zn_native_runtime_map_read_v1(&owner,&dispatch,&request,r,&arena,&mapped)==0);
                CHECK(mapped.physical_address==slot->region.address &&
                      mapped.cpu_address==arena.cpu_base+(slot->region.address-c.arena_base) &&
                      mapped.view.data==mapped.cpu_address && mapped.view.bytes==slot->bytes &&
                      mapped.view.epoch==200 && mapped.view.ref.generation==slot->ref.generation);
                if (mapped.view.ref.tensor==-1)
                    CHECK(mapped.view.channels==3 && mapped.view.height==640 && mapped.view.width==640);
                ++reads;
            }
            if (request.job->has_destination) {
                ZnNativeArenaSlotV1 *slot=&owner.slots[request.job->destination.ref.slot];
                ZnNativeArenaSlotV1 saved=*slot;
                ZnNativeRuntimeTensorMapV1 before;
                CHECK(zn_native_runtime_map_destination_v1(&owner,&dispatch,&request,&arena,&mapped)==0);
                CHECK(mapped.physical_address==request.job->destination.address &&
                      mapped.cpu_address==arena.cpu_base+(request.job->destination.address-c.arena_base) &&
                      mapped.view.bytes==request.job->destination.bytes &&
                      mapped.view.channels==request.job->destination.channels);
                before=mapped;
                ++slot->ref.generation;
                CHECK(zn_native_runtime_map_destination_v1(&owner,&dispatch,&request,&arena,&mapped)==-1);
                *slot=saved; slot->bytes+=64;
                CHECK(zn_native_runtime_map_destination_v1(&owner,&dispatch,&request,&arena,&mapped)==-1);
                *slot=saved;
                CHECK(memcmp(&mapped,&before,sizeof mapped)==0);
                rejects+=2; ++destinations;
            } else {
                ZnNativeRuntimeTensorMapV1 before=mapped;
                CHECK(request.event_index==72);
                CHECK(zn_native_runtime_map_destination_v1(&owner,&dispatch,&request,&arena,&mapped)==-1);
                CHECK(memcmp(&mapped,&before,sizeof mapped)==0); ++rejects;
            }
            CHECK(zn_native_arena_owner_run_started_v1(&owner,&dispatch,&request)==0);
            evidence.epoch=request.epoch; evidence.run_tag=request.tag;
            evidence.event_index=request.event_index; evidence.result_identity_verified=1;
            evidence.driver_terminal_success=1;
            if (request.job->has_destination) {
                evidence.output_cache_visible=1;
                evidence.destination_ref=request.job->destination.ref;
                evidence.destination_bytes=request.job->destination.bytes;
                CHECK(zn_native_arena_owner_publish_v1(&owner,&dispatch,&request,&evidence)==0);
            } else
                CHECK(zn_native_arena_owner_complete_without_output_v1(&owner,&dispatch,&request,&evidence)==0);
            ++runs;
        } else if (request.operation==ZN_DRAIN) {
            ZnNativeArenaQuiescenceEvidenceV1 quiet={0};
            quiet.epoch=request.epoch; quiet.run_tag=owner.event_state[request.event_index].run_tag;
            quiet.event_index=request.event_index;
            quiet.all_read_io_quiet=1; quiet.all_write_io_quiet=1; quiet.driver_terminal=1;
            CHECK(zn_native_arena_owner_notify_quiescent_v1(&owner,&dispatch,&request,&quiet)==0);
        }
        CHECK(zn_native_arena_owner_step_v1(&owner,&dispatch,&request)==0);
    }
    CHECK(next==0 && runs==73 && destinations==72);
    CHECK(zn_native_arena_owner_verify_complete_v1(&owner,&dispatch)==0);
    for (i=0;i<arena.cpu_bytes;++i) CHECK(arena.cpu_base[i]==0xa5);
    printf("NATIVE_RUNTIME_MAPS_PASS events=%u reads=%u destinations=%u rejections=%u arena_unchanged=1 synthetic_completions=1\n",
           runs,reads,destinations,rejects);
    free(allocation);
    return 0;
}
