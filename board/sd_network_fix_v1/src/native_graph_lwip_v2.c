#include "native_graph_lwip_v2.h"
#include "native_lwip_timebase_v1.h"
#include "lwip/tcp.h"
#include "netif/xadapter.h"

#include <limits.h>
#include <string.h>

#define NET_MAGIC UINT32_C(0x4e474c32)
static ZnNativeGraphLwipV2 *binding;

static int apart(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t av=(uintptr_t)a,bv=(uintptr_t)b;
    return a && b && an && bn && an <= UINTPTR_MAX-av && bn <= UINTPTR_MAX-bv &&
        (av+an <= bv || bv+bn <= av);
}

static int outside(const ZnNativeGraphSessionV1 *s,const void *p,size_t bytes)
{
    const ZnNativePlatformMappedSpanV1 *maps[5]={&s->frame.config.arena,&s->frame.config.scratch,
        &s->frame.config.heads,&s->model.parameter_mapping,&s->model.directory_mapping};
    unsigned i;
    if (!apart(p,bytes,s,sizeof *s) || !apart(p,bytes,s->model.parameter_payload.data,(size_t)ZN_NPMV1_PARAMETER_BYTES) ||
        !apart(p,bytes,s->model.directory.data,(size_t)ZN_NPMV1_DIRECTORY_BYTES) ||
        !apart(p,bytes,s->model.package_sha256,65) || !apart(p,bytes,s->model.checkpoint_sha256,65) ||
        !apart(p,bytes,s->model.graph_sha256,65) || !apart(p,bytes,s->model.parameter_payload.sha256,65) ||
        !apart(p,bytes,s->model.directory.sha256,65)) return 0;
    for (i=0;i<5;++i) if (!apart(p,bytes,maps[i]->cpu_base,maps[i]->cpu_bytes)) return 0;
    return 1;
}

static int outside_service(const ZnNativeGraphLwipV2 *n,const void *p,size_t bytes)
{
    return outside(n->session,p,bytes) && apart(p,bytes,n,sizeof *n) &&
        apart(p,bytes,n->app,sizeof *n->app) && apart(p,bytes,n->wire,sizeof *n->wire) &&
        apart(p,bytes,n->app->input_nchw,n->app->input_bytes) &&
        apart(p,bytes,n->wire->tensor,n->wire->tensor_capacity) &&
        apart(p,bytes,n->wire->detections,n->wire->detection_capacity*sizeof *n->wire->detections) &&
        apart(p,bytes,n->wire->response,n->wire->response_capacity) && apart(p,bytes,n->wire->class_domain,4);
}

static int fail(ZnNativeGraphLwipV2 *n)
{
    n->transport_error=1; n->state=ZN_NATIVE_LWIP_V2_FAILED;
    return ZN_NATIVE_LWIP_V2_FAILED;
}

static int current(const ZnNativeGraphLwipV2 *n,struct tcp_pcb *pcb,uintptr_t generation)
{
    return n && n == binding && pcb && n->peer == pcb && generation && n->generation == generation;
}

static int sample(ZnNativeGraphLwipV2 *n,uint64_t *now)
{
    if (zn_native_lwip_timebase_check_v1()!=ZN_NATIVE_LWIP_TIMEBASE_V1_READY ||
        n->session->frame.config.read_ticks(n->session->frame.config.clock_context,now) || *now < n->last_ticks)
        return fail(n);
    n->last_ticks=*now;
    if (n->peer && *now-n->connection_start >= n->budget_ticks) return fail(n);
    return 0;
}

static void forget_peer(ZnNativeGraphLwipV2 *n)
{
    n->peer=NULL; n->generation=0; n->peer_eof=0; n->incoming_head=n->incoming_len=0;
}

static void abort_peer(ZnNativeGraphLwipV2 *n)
{
    struct tcp_pcb *pcb=n->peer;
    if (!pcb) return;
    tcp_recv(pcb,NULL); tcp_err(pcb,NULL);
    forget_peer(n);
    tcp_abort(pcb); /* TCP connection only; never a PL/DMA reset or abort. */
}

static void dropped(void *arg,err_t error)
{
    ZnNativeGraphLwipV2 *n=binding;
    uintptr_t generation=(uintptr_t)arg;
    (void)error;
    if (n && n->peer && generation && n->generation == generation) {
        forget_peer(n); (void)fail(n);
    }
}

static err_t received(void *arg,struct tcp_pcb *pcb,struct pbuf *packet,err_t error)
{
    ZnNativeGraphLwipV2 *n=binding;
    const struct pbuf *part;
    size_t total=0;
    if (!current(n,pcb,(uintptr_t)arg)) { if (packet) pbuf_free(packet); return ERR_OK; }
    if (!packet) { n->peer_eof=1; return ERR_OK; }
    if (error != ERR_OK) {
        pbuf_free(packet); (void)fail(n); abort_peer(n); return ERR_ABRT;
    }
    if (packet->tot_len > sizeof n->incoming-n->incoming_len) return ERR_MEM;
    for (part=packet;part;part=part->next) {
        if ((part->len && !part->payload) || part->len > sizeof n->incoming-total) {
            pbuf_free(packet); (void)fail(n); abort_peer(n); return ERR_ABRT;
        }
        total+=part->len;
    }
    if (total != packet->tot_len) {
        pbuf_free(packet); (void)fail(n); abort_peer(n); return ERR_ABRT;
    }
    /* Append with contiguous memcpy runs instead of one modulo per byte.
     * The ring wraps, so each run is bounded by the space before the wrap; the
     * byte sequence, head and length are identical to the byte-at-a-time form,
     * which performs a ring index update per byte (the power-of-two modulo
     * compiles to bit operations). */
    for (part=packet;part;part=part->next) {
        const uint8_t *data=part->payload; size_t remain=part->len;
        while (remain) {
            size_t at=(n->incoming_head+n->incoming_len)%sizeof n->incoming;
            size_t run=sizeof n->incoming-at;
            if (run>remain) run=remain;
            memcpy(n->incoming+at,data,run);
            n->incoming_len+=run; data+=run; remain-=run;
        }
    }
    tcp_recved(pcb,packet->tot_len); pbuf_free(packet);
    return ERR_OK;
}

static err_t accepted(void *arg,struct tcp_pcb *pcb,err_t error)
{
    ZnNativeGraphLwipV2 *n=arg;
    uint64_t now;
    if (error != ERR_OK) return error;
    if (!n || n != binding || !pcb) return ERR_ARG;
    if (n->state != ZN_NATIVE_LWIP_V2_LISTENING || n->peer || n->dispatching ||
        n->app->state != ZN_NATIVE_SERVICE_V2_READY || n->next_generation == UINTPTR_MAX) {
        if (n->next_generation == UINTPTR_MAX) (void)fail(n);
        tcp_abort(pcb); return ERR_ABRT;
    }
    if (sample(n,&now)) { tcp_abort(pcb); return ERR_ABRT; }
    n->generation=++n->next_generation; n->peer=pcb; n->peer_eof=0;
    n->incoming_head=n->incoming_len=0; n->connection_start=now;
    /* Small protocol replies must not wait for delayed ACK of their prefix. */
    tcp_nagle_disable(pcb);
    tcp_arg(pcb,(void *)n->generation); tcp_recv(pcb,received); tcp_err(pcb,dropped);
    return ERR_OK;
}

int zn_native_graph_lwip_progress_v2(void *context)
{
    ZnNativeGraphLwipV2 *n=context;
    uint64_t now;
    if (!n || n != binding || n->magic != NET_MAGIC) return ZN_NATIVE_LWIP_V2_ARGUMENT;
    if (n->state == ZN_NATIVE_LWIP_V2_FAILED) return ZN_NATIVE_LWIP_V2_FAILED;
    if (n->state == ZN_NATIVE_LWIP_V2_BOUND) return ZN_NATIVE_LWIP_V2_STATE;
    if (n->pumping) return 0;
    if (sample(n,&now)) return ZN_NATIVE_LWIP_V2_FAILED;
    n->pumping=1; ++n->progress_calls;
    /* The standard scheduler owns all protocol timers. Its callbacks may
     * invalidate the peer, so recheck health/deadline before GEM input. */
    if (zn_native_lwip_timeouts_poll_v1()!=ZN_NATIVE_LWIP_TIMEBASE_V1_READY) (void)fail(n);
    if (n->state!=ZN_NATIVE_LWIP_V2_FAILED && !sample(n,&now)) xemacif_input(n->interface);
    n->pumping=0;
    if (n->state == ZN_NATIVE_LWIP_V2_FAILED || sample(n,&now)) return ZN_NATIVE_LWIP_V2_FAILED;
    return 0;
}

static int net_read(void *context,uint8_t *to,size_t capacity)
{
    ZnNativeGraphLwipV2 *n=context;
    size_t count=0;
    if (!n || n != binding || n->state != ZN_NATIVE_LWIP_V2_SERVING || !to || !capacity) return -1;
    while (n->peer && !n->incoming_len && !n->peer_eof)
        if (zn_native_graph_lwip_progress_v2(n)) return -1;
    if (zn_native_graph_lwip_progress_v2(n) || !n->peer) return -1;
    if (!n->incoming_len) return n->peer_eof ? 0 : -1;
    while (count<capacity && n->incoming_len && count<INT_MAX) {
        size_t at=n->incoming_head;
        size_t run=sizeof n->incoming-at;
        size_t want=capacity-count;
        if (run>n->incoming_len) run=n->incoming_len;
        if (run>want) run=want;
        memcpy(to+count,n->incoming+at,run);
        count+=run;
        n->incoming_head=(at+run)%sizeof n->incoming; n->incoming_len-=run;
    }
    n->rx_bytes+=count;
    return (int)count;
}

static int net_write(void *context,const uint8_t *from,size_t bytes)
{
    ZnNativeGraphLwipV2 *n=context;
    size_t count=0;
    if (!n || n != binding || n->state != ZN_NATIVE_LWIP_V2_SERVING || !from || !bytes || bytes>INT_MAX) return -1;
    while (count<bytes) {
        struct tcp_pcb *pcb; u16_t chunk; err_t code;
        if (zn_native_graph_lwip_progress_v2(n) || !n->peer) return -1;
        pcb=n->peer; chunk=tcp_sndbuf(pcb);
        if (chunk>4096u) chunk=4096u;
        if (chunk>bytes-count) chunk=(u16_t)(bytes-count);
        if (!chunk) continue;
        code=tcp_write(pcb,from+count,chunk,TCP_WRITE_FLAG_COPY);
        if (code == ERR_MEM) continue;
        if (code != ERR_OK) { (void)fail(n); return -1; }
        count+=chunk; n->tx_copy_bytes+=chunk;
        code=tcp_output(pcb);
        if (code != ERR_OK && code != ERR_MEM) { (void)fail(n); return -1; }
    }
    if (zn_native_graph_lwip_progress_v2(n)) return -1;
    return (int)count;
}

int zn_native_graph_lwip_bind_v2(ZnNativeGraphLwipV2 *n,ZnNativeGraphSessionV1 *s,
    ZnNativeGraphServiceV2 *a,V8Service *w,uint64_t budget)
{
    const void *regions[5]; size_t sizes[5]; unsigned i,j;
    if (!n || !s || !a || !w || binding || n->magic || a->magic || !budget ||
        s->state != ZN_NATIVE_SESSION_V1_READY || !s->model_state.ready || s->reserved != 31 ||
        s->frame.state != ZN_NATIVE_FRAME_V1_READY || !s->frame.config.read_ticks ||
        s->frame.config.ticks_per_second < 1000 || s->frame.config.ticks_per_second > UINT32_MAX ||
        w->read || w->write || w->transport || w->infer || w->inference ||
        !w->class_domain || w->detection_capacity != 300 || !outside(s,n,sizeof *n) ||
        !apart(n,sizeof *n,w->class_domain,4)) return ZN_NATIVE_LWIP_V2_ARGUMENT;
    regions[0]=a; sizes[0]=sizeof *a; regions[1]=w; sizes[1]=sizeof *w;
    regions[2]=w->tensor; sizes[2]=w->tensor_capacity;
    regions[3]=w->detections; sizes[3]=w->detection_capacity*sizeof *w->detections;
    regions[4]=w->response; sizes[4]=w->response_capacity;
    for (i=0;i<5;++i) {
        if (!outside(s,regions[i],sizes[i]) || !apart(n,sizeof *n,regions[i],sizes[i]) ||
            !apart(regions[i],sizes[i],w->class_domain,4)) return ZN_NATIVE_LWIP_V2_ARGUMENT;
        for (j=i+1;j<5;++j) if (!apart(regions[i],sizes[i],regions[j],sizes[j])) return ZN_NATIVE_LWIP_V2_ARGUMENT;
    }
    memset(n,0,sizeof *n);
    n->magic=NET_MAGIC; n->session=s; n->app=a; n->wire=w; n->budget_ticks=budget;
    binding=n; w->read=net_read; w->write=net_write; w->transport=n;
    return ZN_NATIVE_LWIP_V2_BOUND;
}

int zn_native_graph_lwip_attach_v2(ZnNativeGraphLwipV2 *n,struct netif *interface,struct tcp_pcb *listener)
{
    uint64_t now;
    if (!n || n != binding || n->magic != NET_MAGIC || !interface || !listener) return ZN_NATIVE_LWIP_V2_ARGUMENT;
    if (n->state != ZN_NATIVE_LWIP_V2_BOUND || n->app->state != ZN_NATIVE_SERVICE_V2_READY ||
        n->app->wire != n->wire || n->app->session != n->session || n->app->transport != n ||
        n->wire->transport != n || n->wire->read != net_read || n->wire->write != net_write ||
        n->app->progress.progress != zn_native_graph_lwip_progress_v2 || n->app->progress.context != n ||
        n->app->progress.context_bytes != sizeof *n) return ZN_NATIVE_LWIP_V2_STATE;
    if (!outside_service(n,interface,sizeof *interface) || !outside_service(n,listener,sizeof *listener) ||
        !apart(interface,sizeof *interface,listener,sizeof *listener)) return ZN_NATIVE_LWIP_V2_ARGUMENT;
    if (sample(n,&now)) return ZN_NATIVE_LWIP_V2_FAILED;
    n->interface=interface; n->listener=listener;
    tcp_arg(listener,n); tcp_accept(listener,accepted); n->state=ZN_NATIVE_LWIP_V2_LISTENING;
    return ZN_NATIVE_LWIP_V2_LISTENING;
}

static int close_peer(ZnNativeGraphLwipV2 *n)
{
    while (n->peer) {
        struct tcp_pcb *pcb=n->peer; err_t code;
        if (zn_native_graph_lwip_progress_v2(n)) return -1;
        if (n->peer != pcb) return -1;
        tcp_recv(pcb,NULL); tcp_err(pcb,NULL);
        code=tcp_close(pcb);
        if (code == ERR_OK) { forget_peer(n); return 0; }
        tcp_recv(pcb,received); tcp_err(pcb,dropped);
        if (code != ERR_MEM) return -1;
    }
    return -1;
}

int zn_native_graph_lwip_pump_v2(ZnNativeGraphLwipV2 *n)
{
    int code;
    if (!n || n != binding || n->magic != NET_MAGIC) return ZN_NATIVE_LWIP_V2_ARGUMENT;
    if (n->pumping || n->dispatching) return n->state;
    if (zn_native_graph_lwip_progress_v2(n)) {
        if (n->state == ZN_NATIVE_LWIP_V2_FAILED) abort_peer(n);
        return n->state;
    }
    if (n->state != ZN_NATIVE_LWIP_V2_LISTENING || !n->peer) return n->state;
    if (!n->incoming_len) {
        /* TCP-only connection checks may close before sending a HELLO. */
        if (n->peer_eof && close_peer(n)) { (void)fail(n); abort_peer(n); }
        return n->state;
    }
    n->dispatching=1; n->state=ZN_NATIVE_LWIP_V2_SERVING; ++n->requests;
    code=zn_native_graph_service_one_v2(n->app);
    n->last_service_code=code; n->last_timing=n->app->timing;
    /* A validated HELLO followed by clean EOF has not started the graph.
     * Keep the same READY epoch; do not rearm or touch accelerator buffers. */
    if (code == ZN_NATIVE_SERVICE_V2_READY && n->app->state == ZN_NATIVE_SERVICE_V2_READY &&
        n->peer_eof && !n->incoming_len && !n->transport_error) {
        if (close_peer(n)) { (void)fail(n); abort_peer(n); }
        else n->state=ZN_NATIVE_LWIP_V2_LISTENING;
    } else if (code != ZN_NATIVE_SERVICE_V2_DELIVERED || n->transport_error || n->incoming_len || close_peer(n)) {
        (void)fail(n); abort_peer(n);
    } else n->state=ZN_NATIVE_LWIP_V2_DELIVERED;
    n->dispatching=0;
    return n->state;
}

int zn_native_graph_lwip_rearm_v2(ZnNativeGraphLwipV2 *n,uint32_t epoch)
{
    if (!n || n != binding || n->magic != NET_MAGIC) return ZN_NATIVE_LWIP_V2_ARGUMENT;
    if (n->state != ZN_NATIVE_LWIP_V2_DELIVERED || n->peer || n->dispatching || n->pumping || n->transport_error)
        return ZN_NATIVE_LWIP_V2_STATE;
    if (zn_native_lwip_timebase_status_v1()!=ZN_NATIVE_LWIP_TIMEBASE_V1_READY) return fail(n);
    if (zn_native_graph_service_rearm_v2(n->app,epoch) != ZN_NATIVE_SERVICE_V2_READY) return ZN_NATIVE_LWIP_V2_STATE;
    n->state=ZN_NATIVE_LWIP_V2_LISTENING;
    return n->state;
}
