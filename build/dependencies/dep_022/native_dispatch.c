#include "native_dispatch.h"
#include <string.h>

int zn_dispatch_init(ZnDispatch *s,const ZnEvent *events,uint16_t count,uint32_t epoch) {
    uint16_t i;
    if (!s) return -1;
    memset(s,0,sizeof(*s));
    if (!events || !count || !epoch) { s->fault=1; return -1; }
    for(i=0;i<count;i++) {
        const ZnEvent *e=&events[i];
        if(e->operation<ZN_CONV || e->operation>ZN_HEADS || e->read_count>7 ||
           e->retire_count>7 || e->has_destination>1) {s->fault=1;return -1;}
    }
    s->events=events;s->count=count;s->epoch=epoch;s->next_tag=1;s->phase=ZN_ALLOCATE;
    return 0;
}

int zn_dispatch_next(ZnDispatch *s,ZnRequest *out) {
    const ZnEvent *e;
    if(!s || !out || s->fault) return -1;
    if(s->done) return 0;
    if(s->pending) {*out=s->request;return 1;}
    for(;;) {
        if(s->cursor==s->count) {s->done=1;return 0;}
        e=&s->events[s->cursor];
        if(s->phase==ZN_ALLOCATE && !e->has_destination) {s->phase=ZN_ACQUIRE;continue;}
        if(s->phase==ZN_ACQUIRE && s->index==e->read_count) {s->phase=ZN_RUN;s->index=0;continue;}
        if(s->phase==ZN_RETURN && s->index==e->read_count) {s->phase=ZN_RETIRE;s->index=0;continue;}
        if(s->phase==ZN_RETIRE && s->index==e->retire_count) {
            s->cursor++;s->phase=ZN_ALLOCATE;s->index=0;continue;
        }
        if(!s->next_tag) {s->fault=1;return -1;}
        memset(&s->request,0,sizeof(s->request));
        s->request.epoch=s->epoch;s->request.tag=s->next_tag++;
        s->request.event_index=s->cursor;s->request.operation=s->phase;s->request.job=e;
        if(s->phase==ZN_ALLOCATE) s->request.ref=e->destination.ref;
        if(s->phase==ZN_ACQUIRE || s->phase==ZN_RETURN) s->request.ref=e->reads[s->index];
        if(s->phase==ZN_RETIRE) s->request.ref=e->retired[s->index];
        s->pending=1;*out=s->request;return 1;
    }
}

int zn_dispatch_ack(ZnDispatch *s,uint32_t tag,uint8_t operation,int status) {
    if(!s || s->fault || s->done) return -1;
    if(!s->pending || s->request.tag!=tag || s->request.operation!=operation ||
       (status!=ZN_ACK_OK && status!=ZN_ACK_BUSY)) {s->fault=1;return -1;}
    if(status==ZN_ACK_BUSY) return 0;
    s->pending=0;
    switch(s->phase) {
        case ZN_ALLOCATE:s->phase=ZN_ACQUIRE;break;
        case ZN_ACQUIRE:case ZN_RETURN:case ZN_RETIRE:s->index++;break;
        case ZN_RUN:s->phase=ZN_DRAIN;break;
        case ZN_DRAIN:s->phase=ZN_RETURN;break;
        default:s->fault=1;return -1;
    }
    return 0;
}
