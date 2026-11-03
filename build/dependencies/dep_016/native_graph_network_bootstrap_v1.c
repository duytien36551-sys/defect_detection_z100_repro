#include "native_graph_network_bootstrap_v1.h"
#include "lwip/init.h"
#include "lwip/tcp.h"
#include "xparameters.h"
#include <string.h>

#if !defined(SDT) && !defined(ZN_NETBOOT_V1_HOST_MODEL)
#error This network startup requires the qualified Cortex-A9 SDT SDK path
#endif
#if !defined(ZN_NETBOOT_V1_HOST_MODEL) && !defined(__ARM_ARCH_7A__)
#error This candidate is limited to Cortex-A9 ARMv7-A
#endif
#if !defined(XPAR_XEMACPS_0_BASEADDR)
#error The generated BSP must supply its GEM0 base address
#endif

#define BOOT_MAGIC UINT32_C(0x4e474231)
static ZnNativeGraphNetworkBootstrapV1 *startup_owner;

static int separate(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t av=(uintptr_t)a,bv=(uintptr_t)b;
    return a && b && an && bn && an<=UINTPTR_MAX-av && bn<=UINTPTR_MAX-bv &&
        (av+an<=bv || bv+bn<=av);
}

static int storage_safe(const ZnNativeGraphNetworkBootstrapV1 *b,const ZnNativeGraphLwipV1 *n,
    const ZnNativeGraphNetworkConfigV1 *config)
{
    const ZnNativeGraphSessionV1 *s=n->session;
    const ZnNativeGraphServiceV2 *a=n->app;
    const V8Service *w=n->wire;
    const ZnNativePlatformMappedSpanV1 *maps[5]={&s->frame.config.arena,&s->frame.config.scratch,
        &s->frame.config.heads,&s->model.parameter_mapping,&s->model.directory_mapping};
    const void *objects[15]={n,s,a,w,config,a->input_nchw,w->tensor,w->detections,w->response,w->class_domain,
        s->model.package_sha256,s->model.checkpoint_sha256,s->model.graph_sha256,
        s->model.parameter_payload.sha256,s->model.directory.sha256};
    size_t sizes[15]={sizeof *n,sizeof *s,sizeof *a,sizeof *w,sizeof *config,a->input_bytes,
        w->tensor_capacity,w->detection_capacity*sizeof *w->detections,w->response_capacity,4,65,65,65,65,65};
    unsigned i;
    for (i=0;i<15;++i) if (!separate(b,sizeof *b,objects[i],sizes[i])) return 0;
    for (i=0;i<5;++i) if (!separate(b,sizeof *b,maps[i]->cpu_base,maps[i]->cpu_bytes)) return 0;
    return separate(b,sizeof *b,s->model.parameter_payload.data,(size_t)ZN_NPMV1_PARAMETER_BYTES) &&
        separate(b,sizeof *b,s->model.directory.data,(size_t)ZN_NPMV1_DIRECTORY_BYTES);
}

static uint32_t ipv4(const uint8_t p[4])
{
    return (uint32_t)p[0]<<24 | (uint32_t)p[1]<<16 | (uint32_t)p[2]<<8 | p[3];
}

static int host_address(uint32_t ip,uint32_t mask)
{
    uint32_t host=ip & ~mask;
    return (ip>>24)>0 && (ip>>24)<224 && (ip>>24)!=127 && host && host!=~mask;
}

static int valid_config(const ZnNativeGraphNetworkConfigV1 *c)
{
    uint32_t ip=ipv4(c->address),mask=ipv4(c->netmask),gw=ipv4(c->gateway),inverse=~mask;
    unsigned i,nonzero=0;
    for (i=0;i<6;++i) nonzero|=c->mac[i];
    return c->port && nonzero && !(c->mac[0]&1u) && mask && inverse &&
        !(inverse & (inverse+1u)) && host_address(ip,mask) &&
        (!gw || (gw!=ip && host_address(gw,mask) && (gw&mask)==(ip&mask)));
}

static int failed(ZnNativeGraphNetworkBootstrapV1 *b,int code)
{
    b->last_code=code; b->state=ZN_NATIVE_NETBOOT_V1_FAILED;
    return b->state;
}

int zn_native_graph_network_bootstrap_v1(ZnNativeGraphNetworkBootstrapV1 *b,
    ZnNativeGraphLwipV1 *n,const ZnNativeGraphNetworkConfigV1 *config)
{
    ip_addr_t ip,mask,gw;
    struct tcp_pcb *listener;
    int code;
    if (!b || !n || !config) return ZN_NATIVE_NETBOOT_V1_ARGUMENT;
    if (startup_owner || b->magic) return ZN_NATIVE_NETBOOT_V1_STATE;
    /* BOUND progress is a public no-IO state check, and also validates that n
     * is the actual singleton binding rather than a lookalike structure. */
    if (n->state!=ZN_NATIVE_LWIP_V1_BOUND ||
        zn_native_graph_lwip_progress_v1(n)!=ZN_NATIVE_LWIP_V1_STATE ||
        !n->session || !n->app || !n->wire || n->app->state!=ZN_NATIVE_SERVICE_V2_READY ||
        n->app->session!=n->session || n->app->wire!=n->wire || n->app->transport!=n ||
        n->wire->transport!=n || !n->wire->read || !n->wire->write ||
        n->wire->inference!=n->app || !n->wire->infer ||
        n->app->progress.progress!=zn_native_graph_lwip_progress_v1 || n->app->progress.context!=n ||
        n->app->progress.context_bytes!=sizeof *n || !valid_config(config) ||
        !storage_safe(b,n,config)) return ZN_NATIVE_NETBOOT_V1_ARGUMENT;
    memset(b,0,sizeof *b);
    b->magic=BOOT_MAGIC; b->network=n; b->config=*config;
    b->state=ZN_NATIVE_NETBOOT_V1_STARTING; startup_owner=b;
    b->stage=ZN_NATIVE_NETBOOT_V1_STACK; lwip_init();
    IP4_ADDR(&ip,b->config.address[0],b->config.address[1],b->config.address[2],b->config.address[3]);
    IP4_ADDR(&mask,b->config.netmask[0],b->config.netmask[1],b->config.netmask[2],b->config.netmask[3]);
    IP4_ADDR(&gw,b->config.gateway[0],b->config.gateway[1],b->config.gateway[2],b->config.gateway[3]);
    b->stage=ZN_NATIVE_NETBOOT_V1_INTERFACE;
    if (xemac_add(&b->interface,&ip,&mask,&gw,b->config.mac,XPAR_XEMACPS_0_BASEADDR)!=&b->interface)
        return failed(b,-1);
    b->stage=ZN_NATIVE_NETBOOT_V1_DEFAULT_UP;
    netif_set_default(&b->interface); netif_set_up(&b->interface);
    b->stage=ZN_NATIVE_NETBOOT_V1_ALLOCATE; b->pcb=tcp_new();
    if (!b->pcb) return failed(b,ERR_MEM);
    b->stage=ZN_NATIVE_NETBOOT_V1_BIND;
    code=tcp_bind(b->pcb,IP_ADDR_ANY,b->config.port);
    if (code!=ERR_OK) return failed(b,code);
    b->stage=ZN_NATIVE_NETBOOT_V1_LISTEN;
    listener=tcp_listen(b->pcb);
    /* On conversion failure lwIP retains the old allocation. On success it
     * frees/converts that allocation; store only the returned listener. */
    if (!listener) return failed(b,ERR_MEM);
    b->pcb=listener; b->stage=ZN_NATIVE_NETBOOT_V1_ATTACH;
    code=zn_native_graph_lwip_attach_v1(n,&b->interface,b->pcb);
    if (code!=ZN_NATIVE_LWIP_V1_LISTENING) return failed(b,code);
    b->stage=ZN_NATIVE_NETBOOT_V1_DONE; b->state=ZN_NATIVE_NETBOOT_V1_READY;
    return b->state;
}
