#include "native_parameter_load.h"
#include <string.h>
static uint32_t le32(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
int zn_parameter_init(ZnParameterLoad *s,const ZnParameterAssets *a) {
    unsigned lane;
    if(!s)return -1;
    memset(s,0,sizeof(*s));
    if(!a||!a->weights||!a->bias||!a->factors||!a->unary||!a->epoch||
       !a->groups||a->groups>1024||!a->lanes||a->lanes>32||
       a->weight_bytes!=(uint32_t)a->groups*128||a->bias_bytes!=128||
       a->factor_bytes!=256||a->unary_bytes!=256){s->fault=1;return -1;}
    for(lane=0;lane<32;lane++){
        const uint8_t *p=a->factors+lane*8;uint32_t m=le32(p);
        if(lane<a->lanes){if(!m||m>0x7fffffffu||p[4]>63||p[5]<1||p[5]>31||p[6]!=1||p[7]!=0){s->fault=1;return -1;}}
        else if(m||p[4]||p[5]||p[6]||p[7]){s->fault=1;return -1;}
    }
    s->assets=*a;s->phase=ZP_MAC_BEGIN;s->next_tag=1;return 0;
}
int zn_parameter_next(ZnParameterLoad *s,ZnParameterRequest *r){
    if(!s||!r||s->fault)return -1;
    if(s->done)return 0;
    if(!s->pending){
        if(!s->next_tag){s->fault=1;return -1;}
        memset(&s->request,0,sizeof(s->request));
        s->request.epoch=s->assets.epoch;s->request.tag=s->next_tag++;
        s->request.operation=s->phase;s->request.index=s->index;
        s->request.groups=s->assets.groups;s->request.lanes=s->assets.lanes;
        switch(s->phase){
            case ZP_WEIGHT:s->request.data=s->assets.weights+s->index*128;s->request.bytes=128;break;
            case ZP_BIAS:s->request.data=s->assets.bias;s->request.bytes=128;break;
            case ZP_FACTOR:s->request.data=s->assets.factors+s->index*8;s->request.bytes=8;break;
            case ZP_UNARY:s->request.data=s->assets.unary+s->index;s->request.bytes=1;break;
            default:break;
        }
        s->pending=1;
    }
    *r=s->request;return 1;
}
int zn_parameter_ack(ZnParameterLoad *s,uint32_t tag,uint8_t op,int status){
    if(!s||s->fault||s->done)return -1;
    if(!s->pending||tag!=s->request.tag||op!=s->phase||(status!=0&&status!=1)){s->fault=1;return -1;}
    if(status==1)return 0;
    s->pending=0;
    if(s->phase==ZP_WEIGHT&&s->index+1<s->assets.groups){s->index++;return 0;}
    if(s->phase==ZP_FACTOR&&s->index+1<s->assets.lanes){s->index++;return 0;}
    if(s->phase==ZP_UNARY&&s->index+1<256){s->index++;return 0;}
    s->index=0;
    if(s->phase==ZP_UNARY_COMMIT)s->done=1;
    else s->phase++;
    return 0;
}
