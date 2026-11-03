#include "v8_runtime.h"
#include "v8_generated_model.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef V8_TEST_TILE
#include "tile_mock.h"
#endif
#ifdef V8_TEST_PIPELINE
#include "v8_pipeline.h"
#endif
int main(int argc,char**argv){
 FILE*f;long sz;uint8_t*b;const uint8_t*p;V8Runtime r={0};int8_t*input;uint8_t *ib,*ab,*sb;uint32_t i;int rc;
 if(argc!=4)return 1;
 f=fopen(argv[1],"rb");if(!f)return 2;fseek(f,0,SEEK_END);sz=ftell(f);rewind(f);if(sz<32)return 3;b=malloc((size_t)sz);if(!b)return 4;
 if(fread(b,1,(size_t)sz,f)!=(size_t)sz)return 5;
 fclose(f);
 rc=v8_package_open(b,(size_t)sz,&v8_graph,&p);if(rc)return 6;
 ib=malloc(1228800+128);ab=malloc(v8_graph.arena_bytes+128);sb=malloc(V8_SCRATCH_COUNT*sizeof(int32_t)+128);if(!ib||!ab||!sb)return 7;
 memset(ib,0xa5,1228800+128);memset(ab,0xa5,v8_graph.arena_bytes+128);memset(sb,0xa5,V8_SCRATCH_COUNT*sizeof(int32_t)+128);
 input=(int8_t*)(ib+64);r.arena=(int8_t*)(ab+64);r.scratch=(int32_t*)(sb+64);
 f=fopen(argv[2],"rb");if(!f)return 8;if(fread(input,1,1228800,f)!=1228800||fgetc(f)!=EOF)return 9;fclose(f);
 r.graph=&v8_graph;r.params=p;r.param_size=v8_graph.param_bytes;r.arena_size=v8_graph.arena_bytes;r.scratch_count=V8_SCRATCH_COUNT;
#ifdef V8_TEST_TILE
 V8TileExecutor executor={0};
 memset(&mock_tx,0xa5,sizeof(mock_tx));memset(&mock_rx,0xa5,sizeof(mock_rx));
 executor.tx=mock_tx.data;executor.tx_capacity=sizeof(mock_tx.data);executor.rx=mock_rx.data;executor.rx_capacity=sizeof(mock_rx.data);executor.transfer=mock_transfer;
 r.conv=v8_tile_execute_conv;r.opaque=&executor;
#endif
#ifdef V8_TEST_PIPELINE
 {
 V8Pipeline pipeline={0};V8Detection detections[300];size_t count=0;
 uint8_t *nchw=malloc(1228800+128),*headbuf=malloc(V8_HEAD_ELEMENTS*sizeof(float)+128);
 if(!nchw||!headbuf)return 7;
 memset(nchw,0xa5,1228800+128);memset(headbuf,0xa5,V8_HEAD_ELEMENTS*sizeof(float)+128);
 pipeline.runtime=&r;pipeline.input_nchw=(int8_t*)(nchw+64);pipeline.input_capacity=1228800;
 pipeline.heads_float=(float*)(headbuf+64);pipeline.heads_capacity=V8_HEAD_ELEMENTS;
 pipeline.decode=(V8DecodeConfig){.input_width=640,.input_height=640,.classes=9,.reg_max=16,.confidence=.25f,.iou=.45f,.multi_label=1};
 rc=v8_pipeline_infer(&pipeline,(const uint8_t*)input,1228800,detections,300,&count);
 for(i=0;i<64;i++)if(nchw[i]!=0xa5||nchw[64+1228800+i]!=0xa5||headbuf[i]!=0xa5||headbuf[64+V8_HEAD_ELEMENTS*sizeof(float)+i]!=0xa5)return 13;
 printf("pipeline_detections=%llu\n",(unsigned long long)count);free(nchw);free(headbuf);
 }
#else
 rc=v8_run(&r,input,1228800);
#endif
 if(rc){printf("runtime=%d node=%u\n",rc,r.completed);return 10;}
 for(i=0;i<64;i++)if(ib[i]!=0xa5||ib[64+1228800+i]!=0xa5||ab[i]!=0xa5||ab[64+v8_graph.arena_bytes+i]!=0xa5||sb[i]!=0xa5||sb[64+V8_SCRATCH_COUNT*sizeof(int32_t)+i]!=0xa5)return 13;
 f=fopen(argv[3],"wb");if(!f)return 11;for(i=0;i<3;i++){const V8Node*n=v8_nodes+v8_graph.outputs[i];if(fwrite(r.arena+n->offset,1,n->bytes,f)!=n->bytes)return 12;}fclose(f);
#ifdef V8_TEST_TILE
 printf("tile_loads=%llu tile_runs=%llu tx_bytes=%llu rx_bytes=%llu\n",(unsigned long long)executor.loads,(unsigned long long)executor.runs,(unsigned long long)mock_tx_bytes,(unsigned long long)mock_rx_bytes);
#endif
 printf("PASS nodes=%u callback_convolutions=%u\n",r.completed,r.callback_convolutions);free(b);free(ib);free(ab);free(sb);return 0;
}
