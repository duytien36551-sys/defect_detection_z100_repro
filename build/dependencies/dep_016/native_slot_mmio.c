#include "native_slot_mmio.h"
#include <string.h>
static void put(uint32_t w[7],unsigned bit,unsigned width,uint32_t value) {
    uint64_t v=(uint64_t)value<<(bit%32);unsigned at=bit/32;
    w[at]|=(uint32_t)v;
    if(bit%32+width>32)w[at+1]|=(uint32_t)(v>>32);
}
int zn_slot_encode(const ZnSlotCommand *c,uint32_t w[7]) {
    if(!c||!w||c->opcode>7||c->slot>6||c->success>1||!c->epoch||!c->generation||
       c->channels>2047||c->height>1023||c->width>1023||c->first_row>1023||c->tile_height>1023)return ZN_MMIO_ARGUMENT;
    memset(w,0,7*sizeof(*w));
    put(w,0,3,c->opcode);put(w,3,3,c->slot);put(w,6,32,c->tag);put(w,38,32,c->epoch);
    put(w,70,32,c->generation);put(w,102,32,c->address);put(w,134,16,c->tensor);put(w,150,11,c->channels);
    put(w,161,10,c->height);put(w,171,10,c->width);put(w,181,10,c->first_row);put(w,191,10,c->tile_height);put(w,201,1,c->success);
    return ZN_MMIO_OK;
}
static int valid(const ZnSlotMmio *io,uint8_t client) {return io&&io->read32&&io->write32&&(client==0||client==2);}
int zn_slot_mmio_submit(const ZnSlotMmio *io,uint8_t client,const ZnSlotCommand *c) {
    uint32_t w[7],id,status;unsigned i;
    if(!valid(io,client)||zn_slot_encode(c,w))return ZN_MMIO_ARGUMENT;
    if(io->read32(io->context,0,&id))return ZN_MMIO_IO;
    if(id!=0x5a4e5331u)return ZN_MMIO_IDENTITY;
    if(io->read32(io->context,4,&status))return ZN_MMIO_IO;
    if(status&8)return ZN_MMIO_PROTOCOL;
    if(status&7)return ZN_MMIO_BUSY;
    for(i=0;i<7;i++)if(io->write32(io->context,16+i*4,w[i]))return ZN_MMIO_IO;
    if(io->write32(io->context,12,client)||io->write32(io->context,8,1))return ZN_MMIO_IO;
    return ZN_MMIO_OK;
}
int zn_slot_mmio_collect(const ZnSlotMmio *io,uint8_t client,const ZnSlotCommand *c,uint32_t budget,uint8_t *code) {
    uint32_t status,lo,hi,route,id,w[7];
    if(!valid(io,client)||!code||!budget||zn_slot_encode(c,w))return ZN_MMIO_ARGUMENT;
    if(io->read32(io->context,0,&id))return ZN_MMIO_IO;
    if(id!=0x5a4e5331u)return ZN_MMIO_IDENTITY;
    while(budget--) {
        if(io->read32(io->context,4,&status))return ZN_MMIO_IO;
        if(status&8)return ZN_MMIO_PROTOCOL;
        if(status&2) {
            if(io->read32(io->context,48,&lo)||io->read32(io->context,52,&hi)||io->read32(io->context,56,&route))return ZN_MMIO_IO;
            if(lo!=c->tag||(hi&7)!=c->slot||(hi>>7)!=0||route!=client)return ZN_MMIO_PROTOCOL;
            if(io->write32(io->context,8,2))return ZN_MMIO_IO;
            *code=(uint8_t)((hi>>3)&15);return ZN_MMIO_OK;
        }
        if(!(status&1))return ZN_MMIO_PROTOCOL;
    }
    return ZN_MMIO_TIMEOUT;
}
