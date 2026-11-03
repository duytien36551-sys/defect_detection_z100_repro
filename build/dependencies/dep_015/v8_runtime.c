#include "v8_runtime.h"
#include "v8_tile_profile.h"
#ifdef V8_TILE_VFP_REQUANT
#include "v8_vfp_requant.h"
#endif
#include <math.h>
#include <string.h>
#include <limits.h>
static uint32_t read_u32(const uint8_t*p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static int32_t i32(const uint8_t*p){uint32_t u=read_u32(p);int32_t v;memcpy(&v,&u,4);return v;}
static double f64(const uint8_t*p){double d;memcpy(&d,p,8);return d;}
static uint32_t crc32(const uint8_t*p,size_t n){uint32_t c=~0u;size_t i;int j;for(i=0;i<n;i++){c^=p[i];for(j=0;j<8;j++)c=(c>>1)^(0xedb88320u & (0u-(c&1u)));}return ~c;}
static int graph_contract(const V8Graph*g){return g&&(g->classes==9u)&&g->reg_max==16u&&g->input_size==640u;}
static int8_t quant(double x){double lo=floor(x),f=x-lo;double v=(f>.5 || (f==.5 && fmod(lo,2)!=0))?lo+1:lo;if(v>127)v=127;if(v< -127)v=-127;return (int8_t)v;}
#if defined(V8_TILE_FAST_REQUANT) || defined(V8_TILE_VFP_REQUANT)
static int8_t conv_quant(double x){
 int32_t whole;double fraction;
 if(x>=127)return 127;
 if(x<=-127)return -127;
 if(!isfinite(x))return quant(x);
 whole=(int32_t)x;fraction=x-whole;
 if(fraction>.5 || (fraction==.5 && whole%2!=0))whole++;
 else if(fraction<-.5 || (fraction==-.5 && whole%2!=0))whole--;
 return (int8_t)whole;
}
#endif
#ifdef V8_TILE_REQUANT_STREAM
static __attribute__((noinline)) void conv_requant_stream_channel(
    const int32_t *rawsrc,int8_t *out,uint32_t plane,double multiplier){
 uint32_t k;
#ifdef V8_TILE_VFP_REQUANT
 if(v8_vfp_requant_fpscr_is_safe(v8_vfp_requant_read_fpscr())){
  for(k=0;k<plane;k++){
   double scaled=(double)*rawsrc++*multiplier;
   *out++=isfinite(scaled)?v8_vfp_requant_round_saturated_finite(scaled):conv_quant(scaled);
  }
 }else{
  for(k=0;k<plane;k++)*out++=conv_quant((double)*rawsrc++*multiplier);
 }
#elif defined(V8_TILE_FAST_REQUANT)
 for(k=0;k<plane;k++)*out++=conv_quant((double)*rawsrc++*multiplier);
#else
 for(k=0;k<plane;k++)*out++=quant((double)*rawsrc++*multiplier);
#endif
}
#endif
static void build_rescale_lut(int8_t table[256],double src,double dst){int i;for(i=0;i<256;i++)table[i]=quant((i-128)*src/dst);}
int v8_package_open(const uint8_t*b,size_t size,const V8Graph*g,const uint8_t**p){
 if(p)*p=0;
 if(!b||!graph_contract(g)||!p||size<32||memcmp(b,"V8PK",4)||read_u32(b+4)!=1||read_u32(b+8)!=g->param_bytes||read_u32(b+12)!=g->param_crc||read_u32(b+16)!=g->count||read_u32(b+20)!=g->arena_bytes||read_u32(b+24)!=g->classes||read_u32(b+28)!=g->input_size||size!=32u+(size_t)g->param_bytes)return -1;
 if(crc32(b+32,g->param_bytes)!=g->param_crc)return -2;
 *p=b+32;return 0;
}
static int bounds(size_t off,size_t len,size_t cap){return off<=cap&&len<=cap-off;}
static int mul(size_t a,size_t b,size_t *out){if(b&&a>SIZE_MAX/b)return 0;*out=a*b;return 1;}
static int interval_overlap(size_t a,size_t alen,size_t b,size_t blen){return a<b+blen&&b<a+alen;}
int v8_graph_preflight(const V8Runtime*r){
 const V8Graph*g;uint32_t id,j,k;size_t count,tmp;
 if(!r||!r->graph||!r->graph->nodes||!r->params||!r->arena||!r->scratch)return -1;
 g=r->graph;
 if(!graph_contract(g)||!g->count||g->count>INT32_MAX||!isfinite(g->input_scale)||g->input_scale<=0||
    r->arena_size<g->arena_bytes||r->param_size!=g->param_bytes)return -2;
 for(j=0;j<3;j++)if(g->outputs[j]>=g->count)return -3;
 for(id=0;id<g->count;id++){
  const V8Node*n=&g->nodes[id];const V8Node*s[8];
  if(!n->c||!n->h||!n->w||!mul(n->c,n->h,&tmp)||!mul(tmp,n->w,&count)||
     count!=n->bytes||!bounds(n->offset,count,g->arena_bytes)||
     !isfinite(n->scale)||n->scale<=0||!n->count||n->count>8)return -4;
  for(j=0;j<n->count;j++){
   int32_t q=n->inputs[j];
   if(q< -1||q>=(int32_t)id)return -5;
   s[j]=q<0?NULL:&g->nodes[q];
  }
  for(j=0;j<id;j++){
   const V8Node*old=&g->nodes[j];int live=0;
   for(k=0;k<3;k++)if(g->outputs[k]==j)live=1;
   for(k=id;k<g->count&&!live;k++){
    const V8Node*future=&g->nodes[k];uint32_t t;
    if(future->count>8)return -5;
    for(t=0;t<future->count;t++)if(future->inputs[t]==(int32_t)j){live=1;break;}
   }
   if(live&&interval_overlap(n->offset,count,old->offset,old->bytes))return -6;
  }
  if(n->op==V8_CONV){
   size_t weights,plane;uint32_t ih=s[0]?s[0]->h:g->input_size,iw=s[0]?s[0]->w:g->input_size,ic=s[0]?s[0]->c:3;
   if(n->count!=1||n->groups!=1||!n->kernel||!n->stride||n->kernel>(uint64_t)ih+2ull*n->padding||
      n->kernel>(uint64_t)iw+2ull*n->padding||
      n->h!=((uint64_t)ih+2ull*n->padding-n->kernel)/n->stride+1||
      n->w!=((uint64_t)iw+2ull*n->padding-n->kernel)/n->stride+1||
      count>r->scratch_count||!mul(n->c,ic,&weights)||
      !mul(weights,n->kernel,&weights)||!mul(weights,n->kernel,&weights)||
      !mul(n->c,4,&plane)||!bounds(n->weight,weights,r->param_size)||
      !bounds(n->bias,plane,r->param_size)||!mul(n->c,8,&plane)||
      !bounds(n->multiplier,plane,r->param_size))return -7;
  }else if(n->op==V8_SILU){
   if(n->count!=1||!bounds(n->lut,256,r->param_size)||
      count!=(s[0]?s[0]->bytes:3u*g->input_size*g->input_size))return -8;
  }else if(n->op==V8_ADD){
   if(n->count!=2||!s[0]||!s[1]||count!=s[0]->bytes||count!=s[1]->bytes||
      n->c!=s[0]->c||n->h!=s[0]->h||n->w!=s[0]->w||
      n->c!=s[1]->c||n->h!=s[1]->h||n->w!=s[1]->w)return -9;
  }else if(n->op==V8_CONCAT){
   size_t channels=0;
   for(j=0;j<n->count;j++){
    uint32_t sh=s[j]?s[j]->h:g->input_size,sw=s[j]?s[j]->w:g->input_size,sc=s[j]?s[j]->c:3;
    if(sh!=n->h||sw!=n->w||channels>SIZE_MAX-sc)return -10;
    channels+=sc;
   }
   if(channels!=n->c)return -10;
  }else if(n->op==V8_SLICE){
   uint32_t sh=s[0]?s[0]->h:g->input_size,sw=s[0]?s[0]->w:g->input_size,sc=s[0]?s[0]->c:3;
   if(n->count!=1||n->h!=sh||n->w!=sw||n->slice_start>sc||n->c>sc-n->slice_start)return -11;
  }else if(n->op==V8_UPSAMPLE){
   uint32_t sh=s[0]?s[0]->h:g->input_size,sw=s[0]?s[0]->w:g->input_size,sc=s[0]?s[0]->c:3;
   if(n->count!=1||sh>UINT32_MAX/2||sw>UINT32_MAX/2||n->h!=sh*2||n->w!=sw*2||n->c!=sc)return -12;
  }else if(n->op==V8_POOL){
   uint32_t sh=s[0]?s[0]->h:g->input_size,sw=s[0]?s[0]->w:g->input_size,sc=s[0]?s[0]->c:3;
   if(n->count!=1||!n->stride||!n->kernel||n->c!=sc||
      n->kernel>(uint64_t)sh+2ull*n->padding||n->kernel>(uint64_t)sw+2ull*n->padding||
      n->h!=((uint64_t)sh+2ull*n->padding-n->kernel)/n->stride+1||
      n->w!=((uint64_t)sw+2ull*n->padding-n->kernel)/n->stride+1)return -13;
  }else return -14;
 }
 return 0;
}
int v8_run(V8Runtime*r,const int8_t*input,size_t input_bytes){
 uint32_t id,j,k,oc,y,x;V8Node in={0};const V8Graph*g;
 if(!r||!r->graph||!input||!r->params||!r->arena||!r->scratch)return -1;
 g=r->graph;if(!graph_contract(g)||input_bytes!=3u*g->input_size*g->input_size)return -1;
 if(v8_graph_preflight(r))return -2;
 in.c=3;in.h=in.w=g->input_size;in.scale=g->input_scale;r->completed=r->callback_convolutions=0;
 for(id=0;id<g->count;id++){
 const V8Node*n=g->nodes+id;const V8Node*s[8];const int8_t*v[8];int8_t*dst;int8_t requant_lut[256];size_t count=(size_t)n->c*n->h*n->w;
 uint64_t started=r->clock?r->clock(r->trace_opaque):0;
 if(!n->count||n->count>8||!n->c||!n->h||!n->w||n->bytes!=count||!bounds(n->offset,count,r->arena_size)||!isfinite(n->scale)||n->scale<=0)return -3;
 dst=r->arena+n->offset;
 for(j=0;j<n->count;j++){int32_t q=n->inputs[j];if(q< -1||q>=(int32_t)id)return -4;s[j]=q<0?&in:g->nodes+q;v[j]=q<0?input:r->arena+s[j]->offset;}
 if(n->op==V8_CONV){
 size_t weights=(size_t)n->c*s[0]->c*n->kernel*n->kernel;
 if(n->groups!=1||!n->stride||!n->kernel||count>r->scratch_count||!bounds(n->weight,weights,r->param_size)||!bounds(n->bias,4u*(size_t)n->c,r->param_size)||!bounds(n->multiplier,8u*(size_t)n->c,r->param_size))return -5;
 if(r->conv){int rc=r->conv(r->opaque,n,s[0],v[0],(const int8_t*)r->params+n->weight,r->params+n->bias,r->scratch);if(rc)return rc;r->callback_convolutions++;}
 else for(oc=0;oc<n->c;oc++)for(y=0;y<n->h;y++)for(x=0;x<n->w;x++){
 uint32_t ic,ky,kx;int64_t acc=i32(r->params+n->bias+oc*4);
 for(ic=0;ic<s[0]->c;ic++)for(ky=0;ky<n->kernel;ky++)for(kx=0;kx<n->kernel;kx++){
 int iy=(int)(y*n->stride+ky)-(int)n->padding,ix=(int)(x*n->stride+kx)-(int)n->padding;
 if(iy>=0&&ix>=0&&iy<(int)s[0]->h&&ix<(int)s[0]->w)acc+=(int32_t)v[0][(ic*s[0]->h+(uint32_t)iy)*s[0]->w+(uint32_t)ix]*(int32_t)((const int8_t*)r->params)[n->weight+((oc*s[0]->c+ic)*n->kernel+ky)*n->kernel+kx];
 }if(acc>INT32_MAX||acc<INT32_MIN)return -21;r->scratch[(oc*n->h+y)*n->w+x]=(int32_t)acc;
 }
 V8_TILE_PROFILE_DECLARE(conv_requant_start);V8_TILE_PROFILE_START(conv_requant_start);
#ifdef V8_TILE_REQUANT_STREAM
 {
  uint32_t plane=n->h*n->w;
  const int32_t *rawsrc=r->scratch;
  int8_t *out=dst;
  for(oc=0;oc<n->c;oc++){
   double m=f64(r->params+n->multiplier+(size_t)oc*8u);
   if(!isfinite(m)||m<=0){V8_TILE_PROFILE_STOP_ADD(conv_requant_ticks,conv_requant_start);return -6;}
   conv_requant_stream_channel(rawsrc,out,plane,m);
   rawsrc+=plane;
   out+=plane;
  }
 }
#else
 for(oc=0;oc<n->c;oc++){double m=f64(r->params+n->multiplier+oc*8);if(!isfinite(m)||m<=0){V8_TILE_PROFILE_STOP_ADD(conv_requant_ticks,conv_requant_start);return -6;}
#ifdef V8_TILE_VFP_REQUANT
 if(v8_vfp_requant_fpscr_is_safe(v8_vfp_requant_read_fpscr())){
  for(k=0;k<n->h*n->w;k++){
   j=oc*n->h*n->w+k;
   {
    double scaled=r->scratch[j]*m;
    dst[j]=isfinite(scaled)?v8_vfp_requant_round_saturated_finite(scaled):conv_quant(scaled);
   }
  }
 }else{
  for(k=0;k<n->h*n->w;k++){
   j=oc*n->h*n->w+k;
   dst[j]=conv_quant(r->scratch[j]*m);
  }
 }
#elif defined(V8_TILE_FAST_REQUANT)
 for(k=0;k<n->h*n->w;k++){j=oc*n->h*n->w+k;
 dst[j]=conv_quant(r->scratch[j]*m);
 }
#else
 for(k=0;k<n->h*n->w;k++){j=oc*n->h*n->w+k;
 dst[j]=quant(r->scratch[j]*m);
 }
#endif
 }
#endif
 V8_TILE_PROFILE_STOP_ADD(conv_requant_ticks,conv_requant_start);
 }else if(n->op==V8_SILU){if(!bounds(n->lut,256,r->param_size)||count!=s[0]->bytes)return -7;for(j=0;j<count;j++)dst[j]=(int8_t)r->params[n->lut+(int)v[0][j]+128];
 }else if(n->op==V8_ADD){if(n->count!=2||count!=s[0]->bytes||count!=s[1]->bytes)return -8;for(j=0;j<count;j++)dst[j]=quant((v[0][j]*s[0]->scale+v[1][j]*s[1]->scale)/n->scale);
 }else if(n->op==V8_CONCAT){size_t at=0;for(k=0;k<n->count;k++){size_t sz=(size_t)s[k]->c*s[k]->h*s[k]->w;if(sz>count-at||s[k]->h!=n->h||s[k]->w!=n->w)return -9;build_rescale_lut(requant_lut,s[k]->scale,n->scale);for(j=0;j<sz;j++)dst[at+j]=requant_lut[(int)v[k][j]+128];at+=sz;}if(at!=count)return -9;
 }else if(n->op==V8_SLICE){if(n->slice_start+n->c>s[0]->c||n->h!=s[0]->h||n->w!=s[0]->w)return -10;build_rescale_lut(requant_lut,s[0]->scale,n->scale);for(j=0;j<count;j++)dst[j]=requant_lut[(int)v[0][n->slice_start*n->h*n->w+j]+128];
 }else if(n->op==V8_UPSAMPLE){if(n->h!=s[0]->h*2||n->w!=s[0]->w*2||n->c!=s[0]->c)return -11;build_rescale_lut(requant_lut,s[0]->scale,n->scale);for(oc=0;oc<n->c;oc++)for(y=0;y<n->h;y++)for(x=0;x<n->w;x++)dst[(oc*n->h+y)*n->w+x]=requant_lut[(int)v[0][(oc*s[0]->h+y/2)*s[0]->w+x/2]+128];
 }else if(n->op==V8_POOL){if(!n->stride||!n->kernel||n->c!=s[0]->c)return -12;build_rescale_lut(requant_lut,s[0]->scale,n->scale);for(oc=0;oc<n->c;oc++)for(y=0;y<n->h;y++)for(x=0;x<n->w;x++){int best=-128;uint32_t ky,kx;for(ky=0;ky<n->kernel;ky++)for(kx=0;kx<n->kernel;kx++){int iy=(int)(y*n->stride+ky)-(int)n->padding,ix=(int)(x*n->stride+kx)-(int)n->padding;if(iy>=0&&ix>=0&&iy<(int)s[0]->h&&ix<(int)s[0]->w){int z=v[0][(oc*s[0]->h+(uint32_t)iy)*s[0]->w+(uint32_t)ix];if(z>best)best=z;}}dst[(oc*n->h+y)*n->w+x]=requant_lut[best+128];}
 }else return -13;
 r->completed=id+1;
 if(r->trace)r->trace(r->trace_opaque,id,n->op,r->clock?r->clock(r->trace_opaque)-started:0,dst,count);
 }return 0;
}
