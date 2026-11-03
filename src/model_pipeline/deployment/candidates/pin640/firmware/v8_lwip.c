#include "v8_lwip.h"
#include "lwip/init.h"
#include "lwip/tcp.h"
#include "lwip/priv/tcp_priv.h"
#include "netif/xadapter.h"
#include "xparameters.h"
#include "xscugic.h"
#include "xil_exception.h"
#include "xstatus.h"
#include "v8_sdt_compat.h"
#include <string.h>

typedef struct {
    struct tcp_pcb *pcb;
    uintptr_t generation;
} TransportSession;

static struct netif net;
static struct tcp_pcb *peer;
static TransportSession peer_session;
static TransportSession service_session;
static uintptr_t next_generation;
static V8Service *active_service;
static unsigned char incoming[32768];
static size_t incoming_head,incoming_len;
static uint64_t last_fast,last_slow,last_link;
static int peer_eof;
static int running_service;
static int net_initialized;

static uint64_t millis(void){XTime t;XTime_GetTime(&t);return t/(COUNTS_PER_SECOND/1000u);}
static int session_is_current(const TransportSession *session){
    return session&&session->pcb&&peer==session->pcb&&peer_session.pcb==session->pcb&&
        session->generation!=0&&session->generation==peer_session.generation;
}
static void reset_incoming(void){incoming_head=incoming_len=0;}
static void clear_peer(const TransportSession *session){
    if(!session_is_current(session))return;
    peer=0;peer_session.pcb=0;peer_session.generation=0;peer_eof=0;reset_incoming();
}
static void clear_peer_generation(uintptr_t generation){
    if(peer&&generation&&peer_session.generation==generation){
        peer=0;peer_session.pcb=0;peer_session.generation=0;peer_eof=0;reset_incoming();
    }
}
static void dropped(void *arg,err_t err){
    (void)err;clear_peer_generation((uintptr_t)arg);
}
static void close_peer(const TransportSession *session){
    struct tcp_pcb *p;
    if(!session_is_current(session))return;
    p=session->pcb;clear_peer(session);
    tcp_recv(p,0);tcp_err(p,0);
    if(tcp_close(p)!=ERR_OK)tcp_abort(p);
}
static err_t received(void *arg,struct tcp_pcb *pcb,struct pbuf *p,err_t err){
    uintptr_t generation=(uintptr_t)arg;
    struct pbuf *part;
    if(!p){
        if(peer==pcb&&peer_session.pcb==pcb&&generation&&peer_session.generation==generation)peer_eof=1;
        return ERR_OK;
    }
    if(!generation||peer!=pcb||peer_session.pcb!=pcb||peer_session.generation!=generation){pbuf_free(p);return ERR_OK;}
    if(err!=ERR_OK){
        pbuf_free(p);clear_peer_generation(generation);tcp_abort(pcb);return ERR_ABRT;
    }
    if(p->tot_len>sizeof(incoming)-incoming_len)return ERR_MEM;
    for(part=p;part;part=part->next){
        size_t i;const unsigned char *data=(const unsigned char*)part->payload;
        for(i=0;i<part->len;i++)incoming[(incoming_head+incoming_len++)%sizeof(incoming)]=data[i];
    }
    tcp_recved(pcb,p->tot_len);pbuf_free(p);return ERR_OK;
}
static err_t accepted(void *arg,struct tcp_pcb *pcb,err_t err){
    (void)arg;
    if(err!=ERR_OK)return err;
    if(peer||running_service){tcp_abort(pcb);return ERR_ABRT;}
    if(++next_generation==0)++next_generation;
    reset_incoming();peer_eof=0;peer=pcb;
    peer_session.pcb=pcb;peer_session.generation=next_generation;
    tcp_arg(peer,(void*)peer_session.generation);tcp_recv(peer,received);tcp_err(peer,dropped);
    return ERR_OK;
}
void v8_network_pump(void){uint64_t now;
    if(!net_initialized)return;
    now=millis();
    if(now-last_fast>=250){tcp_fasttmr();last_fast=now;}
    if(now-last_slow>=500){tcp_slowtmr();last_slow=now;}
    if(!peer&&!running_service&&now-last_link>=1000){
        last_link=now;eth_link_detect(&net);
    }
    xemacif_input(&net);
    if(peer&&!running_service&&incoming_len){
        running_service=1;service_session=peer_session;
        active_service->transport=&service_session;
        (void)v8_service_one(active_service);
        close_peer(&service_session);
        active_service->transport=0;service_session.pcb=0;service_session.generation=0;
        running_service=0;
    }else if(peer&&!running_service&&peer_eof&&!incoming_len){
        close_peer(&peer_session);
    }
}
static int net_read(void *arg,uint8_t *dst,size_t cap){
    const TransportSession *session=(const TransportSession*)arg;
    size_t n=0;uint64_t end=millis()+30000u;
    while(session_is_current(session)&&!incoming_len&&!peer_eof&&millis()<end)v8_network_pump();
    if(!session_is_current(session)||!incoming_len)return -1;
    while(n<cap&&incoming_len){dst[n++]=incoming[incoming_head];incoming_head=(incoming_head+1)%sizeof(incoming);incoming_len--;}
    return (int)n;
}
static int net_write(void *arg,const uint8_t *src,size_t bytes){
    const TransportSession *session=(const TransportSession*)arg;
    size_t done=0;uint64_t end=millis()+30000u;
    while(session_is_current(session)&&done<bytes&&millis()<end){
        struct tcp_pcb *p=session->pcb;u16_t n=tcp_sndbuf(p);err_t rc;
        if(n>4096)n=4096;
        if(n>bytes-done)n=(u16_t)(bytes-done);
        if(!n){v8_network_pump();continue;}
        rc=tcp_write(p,src+done,n,TCP_WRITE_FLAG_COPY);
        if(rc==ERR_MEM){v8_network_pump();continue;}
        if(rc!=ERR_OK)return -1;
        done+=n;tcp_output(p);v8_network_pump();
    }
    return done==bytes?(int)done:-1;
}
int v8_network_start(V8Service *s){ip_addr_t ip,mask,gw;struct tcp_pcb *listener;
    unsigned char mac[6]={0x02,0x0a,0x35,0x00,0x01,0x08};
    if(!s)return -1;
    net_initialized=0;
    active_service=s;s->read=net_read;s->write=net_write;s->transport=0;
    Xil_ExceptionInit();
    if(XScuGic_DeviceInitialize(V8_GIC_CONFIG_LOOKUP_KEY)!=XST_SUCCESS)return -6;
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_IRQ_INT,
        (Xil_ExceptionHandler)XScuGic_DeviceInterruptHandler,
        (void*)(UINTPTR)V8_GIC_CONFIG_LOOKUP_KEY);
    lwip_init();IP4_ADDR(&ip,192,168,10,2);IP4_ADDR(&mask,255,255,255,0);IP4_ADDR(&gw,0,0,0,0);
    if(!xemac_add(&net,&ip,&mask,&gw,mac,XPAR_XEMACPS_0_BASEADDR))return -2;
    netif_set_default(&net);netif_set_up(&net);
    listener=tcp_new();if(!listener)return -3;
    if(tcp_bind(listener,IP_ADDR_ANY,5001)!=ERR_OK){tcp_abort(listener);return -4;}
    listener=tcp_listen(listener);if(!listener)return -5;
    tcp_accept(listener,accepted);
    last_fast=last_slow=last_link=millis();net_initialized=1;
    Xil_ExceptionEnableMask(XIL_EXCEPTION_IRQ);
    return 0;
}
