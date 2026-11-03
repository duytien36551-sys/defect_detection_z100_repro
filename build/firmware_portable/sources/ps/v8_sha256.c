#include "v8_sha256.h"

#include <string.h>

#define V8_SHA256_CONTEXT_MAGIC UINT32_C(0x56385332)

static const uint32_t k[64] = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};
static uint32_t rotr(uint32_t x, unsigned n) { return (x >> n) | (x << (32u - n)); }
static uint32_t be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
#define SHA256_ROUND(A,B,C,D,E,F,G,H,K_VALUE,W_VALUE) do { \
    uint32_t sha256_round_t1 = (H)+(rotr((E),6)^rotr((E),11)^rotr((E),25))+ \
        (((E)&(F))^(~(E)&(G)))+(K_VALUE)+(W_VALUE); \
    uint32_t sha256_round_t2 = (rotr((A),2)^rotr((A),13)^rotr((A),22))+ \
        (((A)&(B))^((A)&(C))^((B)&(C))); \
    (D) += sha256_round_t1; \
    (H) = sha256_round_t1 + sha256_round_t2; \
} while(0)
static void block(uint32_t h[8], const uint8_t data[64]) {
    uint32_t w[64], a,b,c,d,e,f,g,t;
    unsigned i;
    for(i=0;i<16;i++) w[i]=be32(data+4*i);
    for(i=16;i<64;i++) w[i]=(rotr(w[i-2],17)^rotr(w[i-2],19)^(w[i-2]>>10))+
        w[i-7]+(rotr(w[i-15],7)^rotr(w[i-15],18)^(w[i-15]>>3))+w[i-16];
    a=h[0];b=h[1];c=h[2];d=h[3];e=h[4];f=h[5];g=h[6];t=h[7];
    for(i=0;i<64;i+=8){
        SHA256_ROUND(a,b,c,d,e,f,g,t,k[i],w[i]);
        SHA256_ROUND(t,a,b,c,d,e,f,g,k[i+1],w[i+1]);
        SHA256_ROUND(g,t,a,b,c,d,e,f,k[i+2],w[i+2]);
        SHA256_ROUND(f,g,t,a,b,c,d,e,k[i+3],w[i+3]);
        SHA256_ROUND(e,f,g,t,a,b,c,d,k[i+4],w[i+4]);
        SHA256_ROUND(d,e,f,g,t,a,b,c,k[i+5],w[i+5]);
        SHA256_ROUND(c,d,e,f,g,t,a,b,k[i+6],w[i+6]);
        SHA256_ROUND(b,c,d,e,f,g,t,a,k[i+7],w[i+7]);
    }
    h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=t;
}
#undef SHA256_ROUND
void v8_sha256_hex(const uint8_t *data, size_t length, char hex[65]) {
    V8Sha256Context context;
    if(!hex || (!data && length))return;
    if(v8_sha256_init(&context) || v8_sha256_update(&context,data,length))return;
    (void)v8_sha256_final_hex(&context,hex);
}

int v8_sha256_init(V8Sha256Context *context) {
    if(!context)return -1;
    memset(context,0,sizeof(*context));
    context->state[0]=0x6a09e667;context->state[1]=0xbb67ae85;
    context->state[2]=0x3c6ef372;context->state[3]=0xa54ff53a;
    context->state[4]=0x510e527f;context->state[5]=0x9b05688c;
    context->state[6]=0x1f83d9ab;context->state[7]=0x5be0cd19;
    context->magic=V8_SHA256_CONTEXT_MAGIC;
    return 0;
}

int v8_sha256_update(V8Sha256Context *context,const uint8_t *data,size_t length) {
    size_t original=length;
    if(!context || context->magic!=V8_SHA256_CONTEXT_MAGIC || context->finalized ||
       (!data && length) || (uint64_t)length>UINT64_MAX/8u-context->total_bytes)return -1;
    if(!length)return 0;
    if(context->block_bytes){
        size_t take=64u-context->block_bytes;
        if(take>length)take=length;
        memcpy(context->block+context->block_bytes,data,take);
        context->block_bytes+=take;data+=take;length-=take;
        if(context->block_bytes==64u){block(context->state,context->block);context->block_bytes=0;}
    }
    while(length>=64u){block(context->state,data);data+=64u;length-=64u;}
    if(length){memcpy(context->block,data,length);context->block_bytes=length;}
    context->total_bytes+=(uint64_t)original;
    return 0;
}

int v8_sha256_final_hex(V8Sha256Context *context,char hex[65]) {
    static const char digits[]="0123456789abcdef";
    uint64_t bit_length;
    unsigned i,j;
    size_t used;
    if(!context || context->magic!=V8_SHA256_CONTEXT_MAGIC || context->finalized || !hex)return -1;
    bit_length=context->total_bytes*8u;
    used=context->block_bytes;
    context->block[used++]=0x80u;
    if(used>56u){
        memset(context->block+used,0,64u-used);
        block(context->state,context->block);
        used=0;
    }
    memset(context->block+used,0,56u-used);
    for(i=0;i<8;i++)context->block[56u+i]=(uint8_t)(bit_length>>(56u-8u*i));
    block(context->state,context->block);
    for(i=0;i<8;i++)for(j=0;j<4;j++){
        uint8_t v=(uint8_t)(context->state[i]>>(24u-8u*j));
        hex[8u*i+2u*j]=digits[v>>4];hex[8u*i+2u*j+1u]=digits[v&15u];
    }
    hex[64]=0;
    context->finalized=1u;
    return 0;
}
