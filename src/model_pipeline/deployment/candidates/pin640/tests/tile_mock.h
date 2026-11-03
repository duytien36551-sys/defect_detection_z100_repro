/* Host arithmetic/packet oracle only; no AXI DMA or FPGA timing simulation. */
#include "v8_tile_executor.h"
#include <limits.h>
static int8_t mock_weights[4091][64];
static int32_t mock_bias[64];
static uint32_t mock_filter, mock_taps, mock_lanes;
static uint64_t mock_tx_bytes, mock_rx_bytes;
static struct { uint8_t pre[64],data[V8_TILE_TX_CAPACITY_BYTES],post[64]; } mock_tx;
static struct { uint8_t pre[64],data[V8_TILE_RX_CAPACITY_BYTES],post[64]; } mock_rx;
static uint32_t mock_read32(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void mock_write32(uint8_t*p,uint32_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);p[2]=(uint8_t)(v>>16);p[3]=(uint8_t)(v>>24);}
static int mock_transfer(void*opaque,V8TileOpcode op,uint32_t reg,uint32_t seq,uint32_t filter,
                         const uint8_t*tx,size_t tx_size,uint8_t*rx,size_t rx_size){
 uint32_t taps=reg&65535u,lanes=(reg>>16)&127u,sites=(reg>>24)&127u,s,l,t,padded=(taps+3u)&~3u;
 (void)opaque;
 if(!taps||taps>4091||!lanes||lanes>64||tx_size>V8_TILE_DMA_MAX_BYTES||rx_size>V8_TILE_MAX_RESPONSE_BYTES)return -1;
 if(op==V8_TILE_OP_LOAD){
  if(sites||tx_size!=256u+64u*taps||rx_size!=20)return -1;
  mock_filter=filter;mock_taps=taps;mock_lanes=lanes;
  for(l=0;l<64;l++){uint32_t u=mock_read32(tx+4*l);memcpy(&mock_bias[l],&u,4);}
  for(t=0;t<taps;t++)for(l=0;l<64;l++)mock_weights[t][l]=(int8_t)tx[256+64*t+l];
 }else if(op==V8_TILE_OP_RUN){
  if(!sites||sites>64||filter!=mock_filter||taps!=mock_taps||lanes!=mock_lanes||tx_size!=(size_t)sites*padded||rx_size!=20u+4u*sites*lanes)return -1;
  for(s=0;s<sites;s++){
   for(t=taps;t<padded;t++)if(tx[s*padded+t])return -1;
   for(l=0;l<lanes;l++){
    int64_t sum=mock_bias[l];
    for(t=0;t<taps;t++)sum+=(int32_t)(int8_t)tx[s*padded+t]*mock_weights[t][l];
    if(sum>INT32_MAX)sum=INT32_MAX;
    if(sum<INT32_MIN)sum=INT32_MIN;
    mock_write32(rx+16+4*(s*lanes+l),(uint32_t)(int32_t)sum);
   }
  }
 }else return -1;
 mock_write32(rx,V8_TILE_MAGIC);mock_write32(rx+4,seq);mock_write32(rx+8,filter);mock_write32(rx+12,reg);mock_write32(rx+rx_size-4,0);
 mock_tx_bytes+=tx_size;mock_rx_bytes+=rx_size;
 for(t=0;t<64;t++)if(mock_tx.pre[t]!=0xa5||mock_tx.post[t]!=0xa5||mock_rx.pre[t]!=0xa5||mock_rx.post[t]!=0xa5)return -1;
 return 0;
}
