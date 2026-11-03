
#include "native_scratch_bindings_v2.h"
#include "graph_plan.h"
#include <stdio.h>
#include <string.h>
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL %d\n",__LINE__);return 1;}}while(0)
int main(void) {
    ZnNativeScratchIdsV2 ids={1000,100000,10000000,1000000,1000000,1000000,1000000,0};
    ZnNativeGraphScratchLeaseV2 scratch={200,800,0x22000000,1228800};
    ZnNativeGraphConvBindingV2 b,before;ZnRequest r;ZnEvent bad;
    unsigned i,j,good=0,deferred=0,rejected=0;uint32_t words[27];
    memset(&r,0,sizeof r);r.epoch=200;r.operation=ZN_RUN;
    for(i=0;i<73;i++) {
        int rc;r.event_index=(uint16_t)i;r.tag=100+i;r.job=&z100_graph_events[i];
        memset(&b,0xa5,sizeof b);before=b;
        rc=zn_native_scratch_binding_v2(&r,&ids,&scratch,&b);
        if(rc==1) {CHECK(memcmp(&b,&before,sizeof b)==0);deferred++;continue;}
        CHECK(rc==0);good++;CHECK(b.graph_read_count==r.job->read_count);
        for(j=0;j<b.graph_read_count;j++) CHECK(b.graph_read_refs[j].generation==r.job->reads[j].generation &&
            b.graph_read_refs[j].tensor==r.job->reads[j].tensor && b.graph_read_refs[j].slot==r.job->reads[j].slot);
        CHECK(zn_native_conv_command_encode_v1(&b.command,words)==ZN_NATIVE_CONV_COMMAND_OK);
        printf("WORDS %u",i);for(j=0;j<27;j++)printf(" %08x",words[j]);puts("");
        memset(&b,0xa5,sizeof b);before=b;
        #define REJECT() do {CHECK(zn_native_scratch_binding_v2(&r,&ids,&scratch,&b)==-1);CHECK(memcmp(&b,&before,sizeof b)==0);rejected++;} while(0)
        scratch.epoch=199;REJECT();scratch.epoch=200;
        scratch.generation=0;REJECT();scratch.generation=800;
        scratch.bytes=64;REJECT();scratch.bytes=1228800;
        scratch.base=0x10000000;REJECT();scratch.base=0x20000000;REJECT();
        scratch.base=0x21000000;REJECT();scratch.base=0x3fffffc0;REJECT();scratch.base=0x22000000;
        ids.tag_base=UINT32_MAX;REJECT();ids.tag_base=10000000;
        bad=*r.job;bad.reads[0].generation++;r.job=&bad;REJECT();r.job=&z100_graph_events[i];
        ids.load_timeout_cycles=0;REJECT();ids.load_timeout_cycles=1000000;
        #undef REJECT
    }
    CHECK(good==21 && deferred==52 && rejected==210);
    puts("SCRATCH_BINDINGS_V2_PASS views=21 deferred=52 command_words=567 adversarial_rejections=210");return 0;
}
