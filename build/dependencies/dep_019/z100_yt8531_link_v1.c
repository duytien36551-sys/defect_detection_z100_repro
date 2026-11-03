#include "z100_yt8531_link_v1.h"

int zn_yt8531_link_speed_v1(const ZnYt8531LinkOpsV1 *ops, uint8_t phy) {
    uint16_t id1,id2,control,status,specific;
    unsigned poll;
    if(!ops || !ops->read || !ops->delay_ms || phy>31) return -1;
    if(ops->read(ops->context,phy,2,&id1) || ops->read(ops->context,phy,3,&id2) ||
       id1!=0x4f51u || id2!=0xe91bu) return -1;
    /* Reject reset/powerdown/isolate or disabled negotiation rather than
     * silently writing vendor registers or guessing a forced link speed. */
    if(ops->read(ops->context,phy,0,&control) || (control&0x8c00u) || !(control&0x1000u)) return -1;
    for(poll=0;poll<500;++poll) {
        /* BMSR link state is latched low: discard the first observation. */
        if(ops->read(ops->context,phy,1,&status) || ops->read(ops->context,phy,1,&status)) return -1;
        if((status&0x24u)==0x24u) {
            if(ops->read(ops->context,phy,0x11,&specific)) return -1;
            if((specific&0x0c00u)==0x0c00u) {
                if(!(specific&0x2000u) || (specific&0x0200u)) return -1;
                switch((specific>>14)&3u) {
                    case 0:return 10;
                    case 1:return 100;
                    case 2:return 1000;
                    default:return -1;
                }
            }
        }
        ops->delay_ms(ops->context,10);
    }
    return -1;
}
