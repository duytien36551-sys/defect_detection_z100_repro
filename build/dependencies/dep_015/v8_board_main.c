#include "v8_lwip.h"
#include "v8_pipeline.h"
#include "v8_dma.h"
#include "v8_sha256.h"
#include "v8_generated_model.h"
#include "ff.h"
#include "xaxidma.h"
#include "xparameters.h"
#include "xil_printf.h"
#include "xil_io.h"
#include "v8_sdt_compat.h"
#include <string.h>

#if defined(SDT)
#if !defined(XPAR_XAXIDMA_0_BASEADDR) || !defined(XPAR_AXI4_LITE_V1_0_0_BASEADDR)
#error V8 firmware requires the AXI DMA and V8 accelerator register base
#endif
#elif !defined(XPAR_AXIDMA_0_DEVICE_ID) || !defined(XPAR_AXI4_LITE_V1_0_0_BASEADDR)
#error V8 firmware requires the AXI DMA and V8 accelerator register base
#endif
static FATFS fs;
static XAxiDma dma;
static V8DmaContext dma_context;
static V8Runtime runtime;
static V8Pipeline pipeline;
static V8Service service;
static V8PipelineDiagnostics v8_pipeline_diagnostics;
uint64_t v8_ticks_per_second = COUNTS_PER_SECOND;
static uint8_t model_blob[V8_PACKAGE_BYTES] __attribute__((aligned(64)));
static uint8_t rgb[V8_INPUT_SIZE*V8_INPUT_SIZE*3u] __attribute__((aligned(64)));
static int8_t input_nchw[V8_INPUT_SIZE*V8_INPUT_SIZE*3u] __attribute__((aligned(64)));
static int8_t arena[V8_ARENA_BYTES] __attribute__((aligned(64)));
static int32_t scratch[V8_SCRATCH_COUNT] __attribute__((aligned(64)));
static float heads[V8_HEAD_ELEMENTS] __attribute__((aligned(64)));
static V8Detection detections[300];
static char response[65536];
static uint32_t dma_taps[2][16384] __attribute__((aligned(64)));
static uint32_t dma_result[2048] __attribute__((aligned(64)));
#ifdef V8_DMA_INJECT_ONCE
static int v8_fault_pending=1;
volatile uint32_t v8_injected_failure[10];
#endif
#ifndef SDT
void _init(void){}
void _fini(void){}
#endif
static int infer(void *ctx,const uint8_t *tensor,size_t bytes,V8Detection *boxes,
                 size_t capacity,size_t *count){
#ifdef V8_DMA_INJECT_ONCE
    if(v8_fault_pending){
        V8Node n={0},s={0};
        const int8_t a=1,w=1;
        const uint8_t bias[4]={255,255,255,127};
        int32_t raw=0x55555555;
        int rc;
        v8_fault_pending=0;
        n.c=n.h=n.w=n.kernel=n.stride=n.groups=1;s.c=s.h=s.w=1;
        rc=v8_dma_conv(&dma_context,&n,&s,&a,&w,bias,&raw);
        v8_injected_failure[0]=1;
        v8_injected_failure[1]=(uint32_t)rc;
        v8_injected_failure[2]=(uint32_t)dma_context.last_transfer_error;
        v8_injected_failure[3]=dma_context.probed;
        v8_injected_failure[4]=dma_context.needs_probe;
        v8_injected_failure[5]=dma_context.faulted;
        v8_injected_failure[6]=(uint32_t)raw;
        v8_injected_failure[7]=(rc==-12 && dma_context.last_transfer_error==-7 &&
            !dma_context.probed && dma_context.needs_probe && !dma_context.faulted && raw==0x55555555);
        *count=0;
        return rc?rc:-1; /* Diagnostic request always fails; publish no result. */
    }
    {int rc=v8_pipeline_infer((V8Pipeline*)ctx,tensor,bytes,boxes,capacity,count);
     v8_injected_failure[0]=2;v8_injected_failure[8]=(uint32_t)rc;
     v8_injected_failure[9]++;return rc;}
#else
    return v8_pipeline_infer((V8Pipeline*)ctx,tensor,bytes,boxes,capacity,count);
#endif
}
static void network_progress(void *opaque){(void)opaque;v8_network_pump();}
static uint64_t board_clock(void *opaque){XTime ticks;(void)opaque;XTime_GetTime(&ticks);return (uint64_t)ticks;}
static void board_trace(void *opaque,uint32_t node,uint32_t op,uint64_t ticks,
                        const int8_t *output,size_t output_bytes){
    V8PipelineDiagnostics *d=(V8PipelineDiagnostics*)opaque;
    (void)output;(void)output_bytes;
    if(!d)return;
    if(node>=V8_PIPELINE_DIAGNOSTIC_NODES){d->trace_dropped++;return;}
    d->node_op[node]=op;d->node_ticks[node]=ticks;
    if(d->node_count<node+1u)d->node_count=node+1u;
}
static int model_load(void){FIL f;UINT got=0;const uint8_t *params=0;
    if(f_mount(&fs,"0:/",1)!=FR_OK)return -1;
    if(f_open(&f,"0:/MODEL.V8P",FA_READ)!=FR_OK)return -2;
    if(f_size(&f)!=sizeof(model_blob)){f_close(&f);return -3;}
    if(f_read(&f,model_blob,sizeof(model_blob),&got)!=FR_OK||got!=sizeof(model_blob)){
        f_close(&f);return -4;}
    f_close(&f);
    if(V8_CLASS_COUNT!=9u||V8_REG_MAX!=16u||V8_INPUT_SIZE!=640u||
       v8_graph.classes!=V8_CLASS_COUNT||v8_graph.reg_max!=V8_REG_MAX||
       v8_graph.input_size!=V8_INPUT_SIZE||
       strcmp(V8_CLASS_DOMAIN,"pin"))return -5;
    if(v8_package_open(model_blob,sizeof(model_blob),&v8_graph,&params))return -5;
    runtime.graph=&v8_graph;runtime.params=params;runtime.param_size=v8_graph.param_bytes;
    runtime.arena=arena;runtime.arena_size=sizeof(arena);
    runtime.scratch=scratch;runtime.scratch_count=sizeof(scratch)/sizeof(scratch[0]);
    runtime.conv=v8_dma_conv;runtime.opaque=&dma_context;
    runtime.clock=board_clock;runtime.trace=board_trace;
    runtime.trace_opaque=&v8_pipeline_diagnostics;
    v8_sha256_hex(model_blob,sizeof(model_blob),service.model_sha256);
    memcpy(service.classes_sha256,V8_CLASSES_SHA256,65);
    service.class_count=v8_graph.classes;service.class_domain=V8_CLASS_DOMAIN;
    service.verified_identity=1;
    return 0;
}
int main(void){XAxiDma_Config *cfg;
    if(v8_timer_startup_init()!=0){
        xil_printf("V8 timer startup failed\r\n");return 6;}
    memset(&service,0,sizeof(service));
    if(model_load()){xil_printf("V8 model load failed\r\n");return 1;}
    /* Keep the PL quiet before the driver's startup reset, including when a
     * prior application left a stream incomplete. V8 control holds ABORT. */
    Xil_Out32(XPAR_AXI4_LITE_V1_0_0_BASEADDR,V8_DMA_CTRL_ABORT);
    if((Xil_In32(XPAR_AXI4_LITE_V1_0_0_BASEADDR)&V8_DMA_CTRL_ABORT)==0u){
        xil_printf("V8 control does not hold ABORT\r\n");return 4;}
    cfg=XAxiDma_LookupConfig(V8_DMA_CONFIG_LOOKUP_KEY);
    if(!cfg||XAxiDma_CfgInitialize(&dma,cfg)!=XST_SUCCESS||XAxiDma_HasSg(&dma)){
        xil_printf("V8 DMA init failed\r\n");return 2;}
    memset(&dma_context,0,sizeof(dma_context));
    dma_context.dma=&dma;dma_context.ctrl_base=XPAR_AXI4_LITE_V1_0_0_BASEADDR;
    dma_context.taps=dma_taps[0];dma_context.taps_alt=dma_taps[1];
    dma_context.result=dma_result;
    dma_context.input_capacity_words=sizeof(dma_taps[0])/sizeof(dma_taps[0][0]);
    dma_context.result_capacity_words=sizeof(dma_result)/sizeof(dma_result[0]);
    dma_context.timeout_polls=10000000u;
    dma_context.progress=network_progress;
    if(v8_dma_probe(&dma_context)){xil_printf("V8 PL identity mismatch\r\n");return 3;}
#ifdef V8_DMA_SELFTEST
    {extern int v8_dma_selftest(V8DmaContext*);
     int selftest_rc=v8_dma_selftest(&dma_context);
     xil_printf("V8 DMA selftest rc=%d\r\n",selftest_rc);return selftest_rc?5:0;}
#endif
    pipeline.runtime=&runtime;pipeline.input_nchw=input_nchw;pipeline.input_capacity=sizeof(input_nchw);
    pipeline.heads_float=heads;pipeline.heads_capacity=V8_HEAD_ELEMENTS;
    pipeline.decode=(V8DecodeConfig){V8_INPUT_SIZE,V8_INPUT_SIZE,V8_CLASS_COUNT,V8_REG_MAX,0.25f,0.45f,1,NULL,0};
    pipeline.diagnostics=&v8_pipeline_diagnostics;
    service.infer=infer;service.inference=&pipeline;
    service.tensor=rgb;service.tensor_capacity=sizeof(rgb);
    service.detections=detections;service.detection_capacity=300;
    service.response=response;service.response_capacity=sizeof(response);
    if(v8_network_start(&service)){xil_printf("V8 network init failed\r\n");return 3;}
    xil_printf("V8 service ready on 192.168.10.2:5001\r\n");
    for(;;)v8_network_pump();
}
