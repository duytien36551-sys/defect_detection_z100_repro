#include "native_parameter_directory.h"
#include <string.h>
static uint32_t u32(const uint8_t *p){
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
static void put32(uint8_t *p,uint32_t v){
    unsigned i;for(i=0;i<4;i++)p[i]=(uint8_t)(v>>(i*8));
}
static int region(uint32_t address,uint32_t bytes,uint32_t begin,uint64_t end){
    return !(address&63u)&&address>=begin&&(uint64_t)address+bytes<=end;
}
static int valid(const ZnParameterDirectoryRecord *r,uint32_t crc,uint32_t begin,uint64_t end){
    if(!r||!crc||(begin&63u)||end<=begin||end>UINT64_C(0x100000000)||
       r->job>=173||!r->groups||r->groups>1024||!r->lanes||r->lanes>32)return 0;
    return region(r->weights,(uint32_t)r->groups*128,begin,end)&&
        region(r->bias,128,begin,end)&&region(r->factors,256,begin,end)&&region(r->unary,256,begin,end);
}
int zn_parameter_directory_encode(uint8_t out[32],const ZnParameterDirectoryRecord *r,
    uint32_t crc,uint32_t begin,uint64_t end){
    uint8_t record[32]={0};
    if(!out||!valid(r,crc,begin,end))return -1;
    put32(record,r->weights);put32(record+4,r->bias);put32(record+8,r->factors);put32(record+12,r->unary);
    put32(record+16,(uint32_t)r->groups|((uint32_t)r->lanes<<11));
    put32(record+20,(uint32_t)r->job|UINT32_C(0x5a500000));put32(record+24,crc);
    memcpy(out,record,sizeof(record));return 0;
}
int zn_parameter_directory_decode(ZnParameterDirectoryRecord *out,const uint8_t record[32],
    uint16_t job,uint32_t crc,uint32_t begin,uint64_t end){
    ZnParameterDirectoryRecord r;uint32_t control,identity;
    if(!out||!record||job>=173)return -1;
    control=u32(record+16);identity=u32(record+20);
    if(control&UINT32_C(0xfffe0000))return -1;
    if(identity!=((uint32_t)job|UINT32_C(0x5a500000))||u32(record+24)!=crc||u32(record+28))return -1;
    memset(&r,0,sizeof(r));r.weights=u32(record);r.bias=u32(record+4);
    r.factors=u32(record+8);r.unary=u32(record+12);r.groups=(uint16_t)(control&2047u);
    r.lanes=(uint8_t)((control>>11)&63u);r.job=job;
    if(!valid(&r,crc,begin,end))return -1;
    *out=r;return 0;
}
