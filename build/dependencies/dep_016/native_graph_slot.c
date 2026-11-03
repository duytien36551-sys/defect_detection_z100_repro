#include "native_graph_slot.h"
#include <string.h>
int zn_graph_slot_command(const ZnRequest *r,ZnSlotCommand *out,uint8_t *client) {
    ZnSlotCommand c;uint64_t size;
    if(!r||!out||!client||!r->job||!r->epoch||!r->tag)return -1;
    if(r->operation==ZN_RUN||r->operation==ZN_DRAIN)return 1;
    if(r->ref.slot>=7||!r->ref.generation||r->ref.tensor< -1||r->ref.tensor>65535)return -1;
    memset(&c,0,sizeof(c));c.slot=r->ref.slot;c.epoch=r->epoch;c.generation=r->ref.generation;
    c.tensor=(uint16_t)r->ref.tensor;c.tag=r->tag;c.success=1;
    switch(r->operation) {
        case ZN_ALLOCATE: {
            const ZnDestination *d=&r->job->destination;
            if(!r->job->has_destination||d->ref.slot!=r->ref.slot||d->ref.generation!=r->ref.generation||d->ref.tensor!=r->ref.tensor||
               !d->channels||d->channels>1024||!d->height||d->height>640||!d->width||d->width>640||d->address%64)return -1;
            size=(uint64_t)((d->channels+3)/4)*d->height*((d->width+15)/16)*64;
            if(size!=d->bytes||(uint64_t)d->address+size>UINT64_C(0x100000000))return -1;
            c.opcode=0;c.address=d->address;c.channels=d->channels;c.height=d->height;c.width=d->width;break;
        }
        case ZN_ACQUIRE:c.opcode=3;break;
        case ZN_RETURN:c.opcode=4;break;
        case ZN_RETIRE:c.opcode=5;break;
        default:return -1;
    }
    *out=c;*client=0;return 0;
}
int zn_graph_slot_complete(ZnDispatch *s,const ZnRequest *r,uint8_t code) {
    ZnSlotCommand c;uint8_t client;
    if(!s||!r||code>15||s->epoch!=r->epoch||!s->pending||s->request.event_index!=r->event_index||s->request.job!=r->job||
       s->request.tag!=r->tag||s->request.operation!=r->operation||s->request.ref.slot!=r->ref.slot||
       s->request.ref.generation!=r->ref.generation||s->request.ref.tensor!=r->ref.tensor||zn_graph_slot_command(r,&c,&client)!=0)return -1;
    return zn_dispatch_ack(s,r->tag,r->operation,code==0?ZN_ACK_OK:code==3?ZN_ACK_BUSY:ZN_ACK_FAILED);
}
