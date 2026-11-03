#include "native_board_entry_v2.h"
#include "native_model_images_v1.h"
#include "native_platform_cache_xilinx_v1.h"
#include "native_platform_mmio_xilinx_v1.h"
#include "native_platform_clock_xilinx_v1.h"
#include "native_platform_reservations_v1.h"
#include "native_postprocess_epoch200_v1.h"
#include <string.h>

#if !defined(ZN_NATIVE_BOARD_V2_HOST_MODEL) && (!defined(SDT) || !defined(__ARM_ARCH_7A__))
#error The board entry requires Cortex-A9 SDT or explicit isolated host testing
#endif
#if defined(ZN_NATIVE_BOARD_V2_HOST_MODEL)
#if defined(ZN_NPMMIO_V1_USE_XILINX_BSP) || defined(ZN_NPMV1_USE_XILINX_BSP)
#error Host board entry must not use hardware adapters
#endif
/* Host-only hooks are absent from the real BSP entry and never qualify PL. */
extern int zn_native_board_host_read_v2(void *,uint32_t,uint32_t *);
extern int zn_native_board_host_write_v2(void *,uint32_t,uint32_t);
extern int zn_native_board_host_barrier_v2(void *);
#endif

static struct {
    ZnNativeBoardDiagnosticsV2 diagnostic;
    ZnNativeBoardConfigV2 configuration;
    ZnNativePlatformClockXilinxV1 clock;
    ZnNativePlatformReservationsV1 reservations;
    ZnNativePlatformCacheXilinxContextV1 cache;
    ZnNativePlatformMmioXilinxContextV1 mmio;
    ZnNativeGraphSessionConfigV1 session_config;
    ZnNativeGraphSessionV1 session;
    ZnNativeGraphServiceV2 service;
    V8Service wire;
    ZnNativeGraphLwipV2 network;
    ZnNativeGraphNetworkBootstrapV2 boot;
    _Alignas(64) uint8_t rgb[V8_SERVICE_TENSOR_BYTES];
    _Alignas(64) int8_t nchw[V8_SERVICE_TENSOR_BYTES];
    V8Detection boxes[300];
    char response[65536];
} board;

static int apart(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t av=(uintptr_t)a,bv=(uintptr_t)b;
    return a && b && an<=UINTPTR_MAX-av && bn<=UINTPTR_MAX-bv && (av+an<=bv || bv+bn<=av);
}
static uint32_t ipv4(const uint8_t p[4])
{
    return (uint32_t)p[0]<<24 | (uint32_t)p[1]<<16 | (uint32_t)p[2]<<8 | p[3];
}
static int host_address(uint32_t ip,uint32_t mask)
{
    uint32_t host=ip & ~mask;
    return (ip>>24)>0 && (ip>>24)<224 && (ip>>24)!=127 && host && host!=~mask;
}
static int valid(const ZnNativeBoardConfigV2 *c)
{
    uint32_t ip,mask,gw,inverse;
    unsigned i,mac=0;
    if (!c || !apart(c,sizeof *c,&board,sizeof board)) return 0;
    ip=ipv4(c->network.address); mask=ipv4(c->network.netmask); gw=ipv4(c->network.gateway); inverse=~mask;
    for (i=0;i<6;++i) mac|=c->network.mac[i];
    return c->initial_epoch && c->poll_steps && c->poll_steps<=64 &&
        c->network_max_sample_gap_ms && c->network_max_sample_gap_ms<=60000 &&
        c->graph_timeout_us && c->connection_timeout_us &&
        c->graph_timeout_us<=c->connection_timeout_us &&
        c->ids.job_base && c->ids.token_base && c->ids.tag_base && c->ids.first_bank<=1 &&
        c->ids.load_timeout_cycles && c->ids.parameter_timeout_cycles &&
        c->ids.write_timeout_cycles && c->ids.preaccept_timeout_cycles &&
        c->network.port && mac && !(c->network.mac[0]&1u) && mask && inverse &&
        !(inverse & (inverse+1u)) && host_address(ip,mask) &&
        (!gw || (gw!=ip && host_address(gw,mask) && (gw&mask)==(ip&mask)));
}
static int ticks(uint64_t us,uint64_t hz,uint64_t *out)
{
    uint64_t whole=us/UINT64_C(1000000),fraction=us%UINT64_C(1000000),part;
    if (!hz || whole>UINT64_MAX/hz || fraction>(UINT64_MAX-UINT64_C(999999))/hz) return -1;
    part=(fraction*hz+UINT64_C(999999))/UINT64_C(1000000);
    if (whole*hz>UINT64_MAX-part) return -1;
    *out=whole*hz+part;
    return *out ? 0 : -1;
}
static void diagnostics(void)
{
    board.diagnostic.reserved_mask=board.session.reserved;
    board.diagnostic.attempted_mask=board.session.attempted_reservations;
    board.diagnostic.session_code=board.session.prepare_code;
    board.diagnostic.network_stage=board.boot.stage;
    board.diagnostic.timebase_code=zn_native_lwip_timebase_status_v1();
}
static int failed(int code)
{
    board.diagnostic.last_code=code;
    board.diagnostic.state=ZN_NATIVE_BOARD_V2_FAILED;
    diagnostics();
    return board.diagnostic.state;
}
static ZnNativePlatformMappedSpanV1 mapped(uintptr_t address,size_t bytes)
{
    ZnNativePlatformMappedSpanV1 m={(uint64_t)address,(uint64_t)bytes,(uint8_t *)address,bytes};
    return m;
}
static void configuration(void)
{
    static const ZnNativeArenaRegionV1 slots[7]={
        {268435456,1638400},{270073856,1638400},{271712256,819200},{272531456,409600},
        {272941056,409600},{273350656,122880},{273473536,163840}};
    ZnNativeGraphFrameConfigV1 *f=&board.session_config.frame;
    ZnNativePlatformMemoryRequestV1 *m=&board.session_config.model;
    f->epoch=board.configuration.initial_epoch; f->ids=board.configuration.ids;
    f->arena_config.arena_base=UINT32_C(0x10000000); f->arena_config.arena_end=273637376;
    f->arena_config.arena_bytes=5201920; f->arena_config.alignment=4096;
    memcpy(f->arena_config.slots,slots,sizeof slots);
    memcpy(f->arena_config.package_sha256,ZN_NATIVE_ARENA_PACKAGE_SHA256_V1,65);
    memcpy(f->arena_config.graph_sha256,ZN_NATIVE_ARENA_GRAPH_SHA256_V1,65);
    memcpy(f->arena_config.plan_sha256,ZN_NATIVE_ARENA_PLAN_SHA256_V1,65);
    memcpy(f->arena_config.manifest_sha256,ZN_NATIVE_ARENA_MANIFEST_SHA256_V1,65);
    f->arena=mapped(0x10000000,5201920); f->heads=mapped(0x24000000,613248);
    f->scratch=mapped(0x22000000,1228800); f->memory_context=&board.cache;
    f->read_ticks=zn_native_platform_clock_xilinx_read_v1; f->clock_context=&board.clock;
    f->ticks_per_second=board.clock.ticks_per_second; f->budget_ticks=board.diagnostic.graph_budget_ticks;
    m->package_sha256=ZN_NPMV1_PACKAGE_SHA256; m->checkpoint_sha256=ZN_NPMV1_CHECKPOINT_SHA256;
    m->graph_sha256=ZN_NPMV1_GRAPH_SHA256;
    m->directory_model_crc32=ZN_NPMV1_DIRECTORY_MODEL_CRC32;
    m->parameter_image_crc32=ZN_NPMV1_PARAMETER_IMAGE_CRC32;
    m->parameter_payload=(ZnNativePlatformImageV1){ZN_NPMV1_PARAMETER_ADDRESS,ZN_NPMV1_PARAMETER_BYTES,
        zn_native_embedded_parameters_v1,ZN_NPMV1_PARAMETER_SHA256};
    m->directory=(ZnNativePlatformImageV1){ZN_NPMV1_DIRECTORY_ADDRESS,ZN_NPMV1_DIRECTORY_BYTES,
        zn_native_embedded_directory_v1,ZN_NPMV1_DIRECTORY_SHA256};
    m->parameter_reservation=(ZnNativePlatformReservationV1){ZN_NPMV1_PARAMETER_ADDRESS,ZN_NPMV1_PARAMETER_BYTES};
    m->directory_reservation=(ZnNativePlatformReservationV1){ZN_NPMV1_DIRECTORY_ADDRESS,ZN_NPMV1_DIRECTORY_BYTES};
    m->view_scratch_reservation=(ZnNativePlatformReservationV1){0x22000000,1228800};
    m->parameter_mapping=mapped(0x20000000,3122432); m->directory_mapping=mapped(0x21000000,5568);
    m->view_scratch_mapping=f->scratch;
}

int zn_native_board_start_v2(const ZnNativeBoardConfigV2 *c)
{
    ZnNativeGraphServiceProgressV2 progress={zn_native_graph_lwip_progress_v2,&board.network,sizeof board.network,1};
    const V8Epoch200Identity *identity=v8_epoch200_expected_identity();
    ZnNativeLwipTimebaseConfigV1 timebase;
    int code;
    if (board.diagnostic.state) return ZN_NATIVE_BOARD_V2_STATE;
    if (!valid(c) ||
        (uintptr_t)zn_native_embedded_parameters_v1_end-(uintptr_t)zn_native_embedded_parameters_v1!=ZN_NPMV1_PARAMETER_BYTES ||
        (uintptr_t)zn_native_embedded_directory_v1_end-(uintptr_t)zn_native_embedded_directory_v1!=ZN_NPMV1_DIRECTORY_BYTES ||
        memcmp(identity->package_sha256,ZN_NPMV1_PACKAGE_SHA256,65) ||
        memcmp(identity->checkpoint_sha256,ZN_NPMV1_CHECKPOINT_SHA256,65) ||
        memcmp(identity->graph_sha256,ZN_NPMV1_GRAPH_SHA256,65) ||
        identity->classes!=9 || identity->input_width!=640 || identity->input_height!=640)
        return ZN_NATIVE_BOARD_V2_ARGUMENT;
    board.configuration=*c; c=&board.configuration;
    board.diagnostic.state=ZN_NATIVE_BOARD_V2_STARTING;
    board.diagnostic.epoch=c->initial_epoch; board.diagnostic.stage=ZN_NATIVE_BOARD_V2_CLOCK;
    code=zn_native_platform_clock_xilinx_init_v1(&board.clock);
    if (code) return failed(code);
    board.diagnostic.ticks_per_second=board.clock.ticks_per_second;
    if (ticks(c->graph_timeout_us,board.clock.ticks_per_second,&board.diagnostic.graph_budget_ticks) ||
        ticks(c->connection_timeout_us,board.clock.ticks_per_second,&board.diagnostic.connection_budget_ticks)) return failed(-1);
    board.diagnostic.stage=ZN_NATIVE_BOARD_V2_LAYOUT;
    code=zn_native_platform_reservations_from_linker_v1(&board.reservations);
    if (code) return failed(code);
    configuration();
    board.cache.reserve=zn_native_platform_reservations_reserve_v1; board.cache.reserve_context=&board.reservations;
    board.mmio.base=ZN_NPMMIO_V1_BASE; board.mmio.bytes=ZN_NPMMIO_V1_BYTES;
#if defined(ZN_NATIVE_BOARD_V2_HOST_MODEL)
    board.mmio.host_read32=zn_native_board_host_read_v2;
    board.mmio.host_write32=zn_native_board_host_write_v2;
    board.mmio.host_barrier=zn_native_board_host_barrier_v2;
#endif
    board.diagnostic.stage=ZN_NATIVE_BOARD_V2_ADAPTERS;
    code=zn_native_platform_cache_xilinx_ops_v1(&board.session_config.frame.memory,&board.cache);
    if (code) return failed(code);
    code=zn_native_platform_mmio_xilinx_ops_v1(&board.session_config.frame.mmio,&board.mmio);
    if (code) return failed(code);
    board.diagnostic.stage=ZN_NATIVE_BOARD_V2_SESSION;
    code=zn_native_graph_session_prepare_v1(&board.session,&board.session_config);
    diagnostics();
    if (code) return failed(code);
    /* This flag follows actual source/copy/cache/readback SHA verification;
     * it identifies the compiled frozen model, not the loaded bitstream. */
    memcpy(board.wire.model_sha256,identity->package_sha256,65);
    memcpy(board.wire.classes_sha256,identity->classes_sha256,65);
    board.wire.class_count=9; board.wire.class_domain="pin"; board.wire.verified_identity=1;
    board.wire.tensor=board.rgb; board.wire.tensor_capacity=sizeof board.rgb;
    board.wire.detections=board.boxes; board.wire.detection_capacity=300;
    board.wire.response=board.response; board.wire.response_capacity=sizeof board.response;
    board.diagnostic.stage=ZN_NATIVE_BOARD_V2_BIND;
    code=zn_native_graph_lwip_bind_v2(&board.network,&board.session,&board.service,&board.wire,
        board.diagnostic.connection_budget_ticks);
    if (code!=ZN_NATIVE_LWIP_V2_BOUND) return failed(code);
    board.diagnostic.stage=ZN_NATIVE_BOARD_V2_SERVICE; progress.poll_steps=c->poll_steps;
    code=zn_native_graph_service_init_v2(&board.service,&board.session,&board.wire,board.nchw,sizeof board.nchw,&progress);
    if (code) return failed(code);
    board.diagnostic.stage=ZN_NATIVE_BOARD_V2_NETWORK;
    timebase=(ZnNativeLwipTimebaseConfigV1){board.session.frame.config.read_ticks,
        board.session.frame.config.clock_context,sizeof board.clock,board.clock.ticks_per_second,
        board.configuration.network_max_sample_gap_ms};
    code=zn_native_graph_network_bootstrap_v2(&board.boot,&board.network,&board.configuration.network,&timebase);
    if (code) return failed(code);
    diagnostics(); board.diagnostic.state=ZN_NATIVE_BOARD_V2_LISTENING;
    return board.diagnostic.state;
}

int zn_native_board_step_v2(void)
{
    int code;
    if (board.diagnostic.state!=ZN_NATIVE_BOARD_V2_LISTENING) return ZN_NATIVE_BOARD_V2_STATE;
    board.diagnostic.stage=ZN_NATIVE_BOARD_V2_PUMP;
    code=zn_native_graph_lwip_pump_v2(&board.network);
    board.diagnostic.last_timing=board.network.last_timing;
    if (code==ZN_NATIVE_LWIP_V2_DELIVERED) {
        if (board.diagnostic.delivered_requests==UINT64_MAX) return failed(-1);
        ++board.diagnostic.delivered_requests;
        board.diagnostic.state=ZN_NATIVE_BOARD_V2_DELIVERED;
    } else if (code!=ZN_NATIVE_LWIP_V2_LISTENING) return failed(code);
    diagnostics();
    return board.diagnostic.state;
}

int zn_native_board_rearm_v2(uint32_t epoch)
{
    int code;
    if (board.diagnostic.state!=ZN_NATIVE_BOARD_V2_DELIVERED) return ZN_NATIVE_BOARD_V2_STATE;
    if (!epoch || epoch<=board.diagnostic.epoch) return ZN_NATIVE_BOARD_V2_ARGUMENT;
    board.diagnostic.stage=ZN_NATIVE_BOARD_V2_REARM;
    code=zn_native_graph_lwip_rearm_v2(&board.network,epoch);
    if (code!=ZN_NATIVE_LWIP_V2_LISTENING) return failed(code);
    board.diagnostic.epoch=epoch; board.diagnostic.last_code=0;
    board.diagnostic.state=ZN_NATIVE_BOARD_V2_LISTENING;
    diagnostics();
    return board.diagnostic.state;
}

const ZnNativeBoardDiagnosticsV2 *zn_native_board_diagnostics_v2(void)
{
    return &board.diagnostic;
}
