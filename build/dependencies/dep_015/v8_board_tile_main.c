#include "v8_lwip.h"
#include "v8_pipeline.h"
#include "v8_tile_executor.h"
#include "v8_tile_board_dma.h"
#include "v8_startup_diagnostics.h"
#include "v8_sha256.h"
#include "v8_generated_model.h"
#include "v8_tile64_dma_config.h"
#include "v8_class_thresholds.h"
#ifdef V8_TILE_VFP_REQUANT
#include "v8_vfp_requant.h"
#endif
#ifdef V8_TILE_PROFILE
#include "v8_tile_profile.h"
#endif
#include "ff.h"
#include "xaxidma.h"
#include "xparameters.h"
#include "xil_printf.h"
#include "xil_io.h"
#include "xil_cache.h"
#include "v8_sdt_compat.h"
#include <stdint.h>
#include <string.h>

#if defined(SDT)
#if !defined(XPAR_XAXIDMA_0_BASEADDR) || !defined(XPAR_AXI4_LITE_V1_0_0_BASEADDR)
#error V8 firmware requires the AXI DMA and V8 accelerator register base
#endif
#elif !defined(XPAR_AXIDMA_0_DEVICE_ID) || !defined(XPAR_AXI4_LITE_V1_0_0_BASEADDR)
#error V8 firmware requires the AXI DMA and V8 accelerator register base
#endif
#ifndef V8_EMBED_MODEL
static FATFS fs;
#endif
static XAxiDma dma;
static V8TileBoardDma dma_context;
static V8TileExecutor tile_executor;
static V8Runtime runtime;
static V8Pipeline pipeline;
static V8Service service;
static V8PipelineDiagnostics v8_pipeline_diagnostics __attribute__((aligned(64)));
uint64_t v8_ticks_per_second = COUNTS_PER_SECOND;
/* Exported for JTAG diagnosis; stages: model, DMA init/reset, PL probe, network. */
volatile uint32_t v8_startup_stage __attribute__((aligned(64)));
volatile uint32_t v8_startup_error __attribute__((aligned(64)));
/* JTAG writes 1 to trigger; result is INT32_MIN while inference is running. */
volatile uint32_t v8_jtag_trigger __attribute__((aligned(64)));
volatile int32_t v8_jtag_result __attribute__((aligned(64)));
volatile uint32_t v8_jtag_count __attribute__((aligned(64)));
volatile uint32_t v8_jtag_completed __attribute__((aligned(64)));
#ifdef V8_EMBED_MODEL
extern const uint8_t v8_embedded_model_start[];
extern const uint8_t v8_embedded_model_end[];
#else
static uint8_t model_blob[V8_PACKAGE_BYTES] __attribute__((aligned(64)));
#endif
static uint8_t rgb[V8_INPUT_SIZE*V8_INPUT_SIZE*3u] __attribute__((aligned(64)));
static int8_t input_nchw[V8_INPUT_SIZE*V8_INPUT_SIZE*3u] __attribute__((aligned(64)));
static int8_t arena[V8_ARENA_BYTES] __attribute__((aligned(64)));
static int32_t scratch[V8_SCRATCH_COUNT] __attribute__((aligned(64)));
static float heads[V8_HEAD_ELEMENTS] __attribute__((aligned(64)));
V8Detection v8_jtag_detections[300] __attribute__((aligned(64)));
static char response[65536];
static uint8_t dma_taps[V8_TILE_TX_CAPACITY_BYTES] __attribute__((aligned(64)));
#ifdef V8_TILE_OVERLAP
static uint8_t dma_taps_next[V8_TILE_TX_CAPACITY_BYTES] __attribute__((aligned(64)));
#endif
#if V8_TILE_RUN_CACHE
#define V8_TILE_RUN_CACHE_CAPACITY_BYTES (2u * 1024u * 1024u)
static uint8_t tile_run_cache[V8_TILE_RUN_CACHE_CAPACITY_BYTES]
    __attribute__((aligned(64)));
_Static_assert(sizeof(tile_run_cache) == V8_TILE_RUN_CACHE_CAPACITY_BYTES,
               "run cache must reserve exactly 2 MiB");
#endif
static uint8_t dma_result[V8_TILE_RX_CAPACITY_BYTES] __attribute__((aligned(64)));
static volatile uint32_t jtag_inference_active;
#define V8_TILE64_RESPONSE_MAX_BYTES V8_TILE_MAX_RESPONSE_BYTES
_Static_assert(V8_TILE64_RESPONSE_MAX_BYTES == V8_TILE64_DMA_REQUIRED_RX_BYTES,
               "generated DMA response limit does not match tile64 ABI");
_Static_assert(V8_TILE_TX_CAPACITY_BYTES >= V8_TILE64_DMA_REQUIRED_TX_BYTES,
               "tile64 TX buffer cannot hold the maximum DMA transfer");
_Static_assert(V8_TILE_RX_CAPACITY_BYTES >= V8_TILE64_DMA_REQUIRED_RX_BYTES,
               "tile64 RX buffer cannot hold the maximum response");
#ifndef SDT
void _init(void){}
void _fini(void){}
#endif
static int infer(void *ctx,const uint8_t *tensor,size_t bytes,V8Detection *boxes,
                 size_t capacity,size_t *count){
    if (!count || !v8_tile_board_ready(&dma_context)) {
        if (count) *count = 0u;
        return -1;
    }
    *count = 0u;
    return v8_pipeline_infer((V8Pipeline*)ctx,tensor,bytes,boxes,capacity,count);
}
static void network_progress(void *opaque){
    (void)opaque;
    if(!jtag_inference_active)v8_network_pump();
}
static void cache_flush_aligned(const void *address,size_t bytes){
    uintptr_t begin=(uintptr_t)address;
    uintptr_t end;
    uintptr_t aligned_begin,aligned_end;
    if(!address||!bytes||begin>UINTPTR_MAX-bytes)return;
    end=begin+bytes;
    aligned_begin=begin&~(uintptr_t)63u;
    if(end>UINTPTR_MAX-63u)return;
    aligned_end=(end+63u)&~(uintptr_t)63u;
    Xil_DCacheFlushRange((INTPTR)aligned_begin,(u32)(aligned_end-aligned_begin));
}
static void startup_status_set(uint32_t stage,uint32_t error){
    v8_startup_stage=stage;
    v8_startup_error=error;
    cache_flush_aligned((const void*)&v8_startup_stage,64u);
    cache_flush_aligned((const void*)&v8_startup_error,64u);
}
static void jtag_inference_if_requested(void){
    size_t count=0;
    int rc;
    Xil_DCacheInvalidateRange((INTPTR)&v8_jtag_trigger,64u);
    if(v8_jtag_trigger!=1u)return;
    v8_jtag_trigger=0u;
    cache_flush_aligned((const void*)&v8_jtag_trigger,64u);
    v8_jtag_result=INT32_MIN;
    v8_jtag_count=0u;
    cache_flush_aligned((const void*)&v8_jtag_result,64u);
    cache_flush_aligned((const void*)&v8_jtag_count,64u);
    jtag_inference_active=1u;
    /* rgb is 64-byte aligned and its 1228800-byte span is cache-line aligned. */
    Xil_DCacheInvalidateRange((INTPTR)rgb,(u32)sizeof(rgb));
    rc=infer(&pipeline,rgb,sizeof(rgb),v8_jtag_detections,
             sizeof(v8_jtag_detections)/sizeof(v8_jtag_detections[0]),
             &count);
    v8_jtag_count=(uint32_t)count;
    v8_jtag_result=(int32_t)rc;
#ifdef V8_TILE_PROFILE
    cache_flush_aligned((const void*)&v8_tile_profile,sizeof(v8_tile_profile));
#endif
    cache_flush_aligned((const void*)heads,sizeof(heads));
    cache_flush_aligned((const void*)&v8_pipeline_diagnostics,
                        sizeof(v8_pipeline_diagnostics));
    cache_flush_aligned((const void*)v8_jtag_detections,
                        sizeof(v8_jtag_detections));
    cache_flush_aligned((const void*)&v8_jtag_count,64u);
    cache_flush_aligned((const void*)&v8_jtag_result,64u);
    jtag_inference_active=0u;
    v8_jtag_completed++;
    cache_flush_aligned((const void*)&v8_jtag_completed,64u);
}
static void startup_diagnostic(void *opaque,uint32_t stage,uint32_t error){
    (void)opaque;startup_status_set(stage,error);
}
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
static int model_load(void){
    const uint8_t *blob=0,*params=0;
    size_t blob_size=0;
#ifndef V8_EMBED_MODEL
    FIL f;UINT got=0;
    if(f_mount(&fs,"0:/",1)!=FR_OK)return -1;
    if(f_open(&f,"0:/MODEL.V8P",FA_READ)!=FR_OK)return -2;
    if(f_size(&f)!=sizeof(model_blob)){f_close(&f);return -3;}
    if(f_read(&f,model_blob,sizeof(model_blob),&got)!=FR_OK||got!=sizeof(model_blob)){
        f_close(&f);return -4;}
    f_close(&f);
    blob=model_blob;blob_size=sizeof(model_blob);
#else
    uintptr_t begin=(uintptr_t)v8_embedded_model_start;
    uintptr_t end=(uintptr_t)v8_embedded_model_end;
    if(end<begin)return -3;
    blob=(const uint8_t*)begin;blob_size=(size_t)(end-begin);
    if(blob_size!=(size_t)V8_PACKAGE_BYTES)return -3;
#endif
    if(V8_CLASS_COUNT!=9u||V8_REG_MAX!=16u||V8_INPUT_SIZE!=640u||
       v8_graph.classes!=V8_CLASS_COUNT||v8_graph.reg_max!=V8_REG_MAX||
       v8_graph.input_size!=V8_INPUT_SIZE||
       strcmp(V8_CLASS_DOMAIN,"pin"))return -5;
    /* Both SD and embedded builds use identical package length, CRC and graph checks. */
    if(v8_package_open(blob,blob_size,&v8_graph,&params))return -5;
    runtime.graph=&v8_graph;runtime.params=params;runtime.param_size=v8_graph.param_bytes;
    runtime.arena=arena;runtime.arena_size=sizeof(arena);
    runtime.scratch=scratch;runtime.scratch_count=sizeof(scratch)/sizeof(scratch[0]);
    runtime.conv=v8_tile_execute_conv;runtime.opaque=&tile_executor;
    runtime.clock=board_clock;runtime.trace=board_trace;
    runtime.trace_opaque=&v8_pipeline_diagnostics;
    v8_sha256_hex(blob,blob_size,service.model_sha256);
    memcpy(service.classes_sha256,V8_CLASSES_SHA256,65);
    service.class_count=v8_graph.classes;service.class_domain=V8_CLASS_DOMAIN;
    service.verified_identity=1;
    return 0;
}
int main(void){XAxiDma_Config *cfg;XAxiDma_Config local_cfg;int rc;
    if(v8_timer_startup_init()!=0){
        xil_printf("V8 timer startup failed\r\n");return 6;}
    memset(&service,0,sizeof(service));
    v8_jtag_trigger=0u;
    v8_jtag_result=INT32_MIN;
    v8_jtag_count=0u;
    v8_jtag_completed=0u;
    cache_flush_aligned((const void*)&v8_jtag_trigger,64u);
    cache_flush_aligned((const void*)&v8_jtag_result,64u);
    cache_flush_aligned((const void*)&v8_jtag_count,64u);
    cache_flush_aligned((const void*)&v8_jtag_completed,64u);
    startup_status_set(V8_STARTUP_MODEL_LOAD,V8_STARTUP_ERROR_NONE);
    rc=model_load();
    if(rc){startup_status_set(V8_STARTUP_MODEL_LOAD,(uint32_t)(-rc));
        xil_printf("V8 model load failed\r\n");return 1;}
#ifdef V8_TILE_VFP_REQUANT
    rc=v8_vfp_requant_selftest(runtime.graph,runtime.params,runtime.param_size);
    __asm__ volatile("mrc p15, 0, %0, c12, c0, 0" : "=r"(v8_vfp_selftest_status[13]));
    __asm__ volatile("mrc p15, 0, %0, c1, c0, 0" : "=r"(v8_vfp_selftest_status[14]));
    __asm__ volatile("mrs %0, cpsr" : "=r"(v8_vfp_selftest_status[15]));
    cache_flush_aligned((const void*)v8_vfp_selftest_status,64u);
    if(rc){startup_status_set(V8_STARTUP_MODEL_LOAD,100u+(uint32_t)(-rc));
        xil_printf("V8 VFP rounding self-check failed\r\n");return 4;}
#endif
    startup_status_set(V8_STARTUP_MODEL_READY,V8_STARTUP_ERROR_NONE);
    startup_status_set(V8_STARTUP_DMA_INIT,V8_STARTUP_ERROR_NONE);
    /* Keep the PL quiet before the driver's startup reset, including when a
     * prior application left a stream incomplete. V8 control holds ABORT. */
    Xil_Out32(XPAR_AXI4_LITE_V1_0_0_BASEADDR,V8_TILE_R0_ABORT);
    if((Xil_In32(XPAR_AXI4_LITE_V1_0_0_BASEADDR)&V8_TILE_R0_ABORT)==0u){
        startup_status_set(V8_STARTUP_DMA_INIT,
                           V8_STARTUP_ERROR_CONTROL_ABORT_WRITE);
        xil_printf("V8 control does not hold ABORT\r\n");return 4;}
    cfg=XAxiDma_LookupConfig(V8_DMA_CONFIG_LOOKUP_KEY);
    if(!cfg){startup_status_set(V8_STARTUP_DMA_INIT,1u);
        xil_printf("V8 DMA init failed\r\n");return 2;}
    /* Never patch the shared BSP lookup table: specialize only this instance. */
    local_cfg=*cfg;
    local_cfg.SgLengthWidth=(int)V8_TILE64_DMA_EFFECTIVE_LENGTH_WIDTH_BITS;
    xil_printf("V8 DMA length width hw=%d BSP=%d effective=%d\r\n",
               (int)V8_TILE64_DMA_HARDWARE_LENGTH_WIDTH_BITS,
               (int)V8_TILE64_DMA_BSP_LENGTH_WIDTH_BITS,
               (int)V8_TILE64_DMA_EFFECTIVE_LENGTH_WIDTH_BITS);
    if(XAxiDma_CfgInitialize(&dma,&local_cfg)!=XST_SUCCESS){
        startup_status_set(V8_STARTUP_DMA_INIT,2u);
        xil_printf("V8 DMA init failed\r\n");return 2;}
    if(XAxiDma_HasSg(&dma)){startup_status_set(V8_STARTUP_DMA_INIT,3u);
        xil_printf("V8 DMA init failed\r\n");return 2;}
    if(dma.TxBdRing.MaxTransferLen<V8_TILE_DMA_MAX_BYTES){
        startup_status_set(V8_STARTUP_DMA_INIT,5u);
        xil_printf("V8 DMA TX max transfer is below tile64 requirement\r\n");
        return 2;}
    if(dma.RxBdRing[0].MaxTransferLen<V8_TILE64_RESPONSE_MAX_BYTES){
        startup_status_set(V8_STARTUP_DMA_INIT,6u);
        xil_printf("V8 DMA RX max transfer is below tile64 response requirement\r\n");
        return 2;}
    startup_status_set(V8_STARTUP_DMA_INIT_DONE,V8_STARTUP_ERROR_NONE);
    memset(&dma_context,0,sizeof(dma_context));
    dma_context.dma=&dma;dma_context.control_base=XPAR_AXI4_LITE_V1_0_0_BASEADDR;
    dma_context.tx_capacity=sizeof(dma_taps);
    dma_context.rx_capacity=sizeof(dma_result);
    dma_context.timeout_polls=10000000u;
    dma_context.progress=network_progress;
    dma_context.startup_diagnostic=startup_diagnostic;
    memset(&tile_executor,0,sizeof(tile_executor));
    tile_executor.transfer=v8_tile_board_transfer;
    tile_executor.opaque=&dma_context;
    tile_executor.tx=(uint8_t*)dma_taps;
    tile_executor.tx_capacity=sizeof(dma_taps);
    tile_executor.rx=(uint8_t*)dma_result;
    tile_executor.rx_capacity=sizeof(dma_result);
    tile_executor.ready=v8_tile_board_ready;
#if V8_TILE_RUN_CACHE
    tile_executor.run_cache=tile_run_cache;
    tile_executor.run_cache_capacity=sizeof(tile_run_cache);
#endif
#ifdef V8_TILE_OVERLAP
    tile_executor.begin=v8_tile_board_begin;
    tile_executor.finish=v8_tile_board_finish;
    tile_executor.cancel=v8_tile_board_cancel;
    tile_executor.tx_next=dma_taps_next;
    tile_executor.tx_next_capacity=sizeof(dma_taps_next);
#endif
    startup_status_set(V8_STARTUP_DMA_RESET,V8_STARTUP_ERROR_NONE);
    if(v8_tile_board_probe(&dma_context)){
        if(v8_startup_error==V8_STARTUP_ERROR_NONE)
            startup_status_set(V8_STARTUP_PL_PROBE,
                               V8_STARTUP_ERROR_PL_PROBE);
        xil_printf("V8 tile64 PL identity mismatch\r\n");return 3;}
    startup_status_set(V8_STARTUP_PL_READY,V8_STARTUP_ERROR_NONE);
    pipeline.runtime=&runtime;pipeline.input_nchw=input_nchw;pipeline.input_capacity=sizeof(input_nchw);
    pipeline.heads_float=heads;pipeline.heads_capacity=V8_HEAD_ELEMENTS;
    pipeline.decode=(V8DecodeConfig){V8_INPUT_SIZE,V8_INPUT_SIZE,V8_CLASS_COUNT,V8_REG_MAX,0.25f,0.45f,1,NULL,0};
#if V8_CLASS_THRESHOLDS_ENABLED
    pipeline.decode.class_confidence=v8_class_thresholds;
    pipeline.decode.class_confidence_count=V8_CLASS_THRESHOLDS_COUNT;
    xil_printf("V8 class thresholds: %s\r\n",V8_CLASS_THRESHOLDS_SHA256);
#endif
    pipeline.diagnostics=&v8_pipeline_diagnostics;
    service.infer=infer;service.inference=&pipeline;
    service.tensor=rgb;service.tensor_capacity=sizeof(rgb);
    service.detections=v8_jtag_detections;
    service.detection_capacity=
        sizeof(v8_jtag_detections)/sizeof(v8_jtag_detections[0]);
    service.response=response;service.response_capacity=sizeof(response);
    startup_status_set(V8_STARTUP_NETWORK_START,V8_STARTUP_ERROR_NONE);
    rc=v8_network_start(&service);
    if(rc){startup_status_set(V8_STARTUP_NETWORK_START,(uint32_t)(-rc));
        xil_printf("V8 network init failed\r\n");return 3;}
    startup_status_set(V8_STARTUP_READY,V8_STARTUP_ERROR_NONE);
    xil_printf("V8 service ready on 192.168.10.2:5001\r\n");
    for(;;){jtag_inference_if_requested();v8_network_pump();}
}
