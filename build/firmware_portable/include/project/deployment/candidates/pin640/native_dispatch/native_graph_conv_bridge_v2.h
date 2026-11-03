#ifndef Z100_NATIVE_GRAPH_CONV_BRIDGE_V2_H
#define Z100_NATIVE_GRAPH_CONV_BRIDGE_V2_H

#include "native_conv_driver_v2.h"
#include "native_dispatch.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_GRAPH_CONV_PACKAGE_SHA256_V2 \
    "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c"
#define ZN_NATIVE_GRAPH_CONV_MODEL_SHA256_V2 \
    "2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6"
#define ZN_NATIVE_GRAPH_CONV_GRAPH_SHA256_V2 \
    "9d6064e37e92e61c687608d2c5e216cccb31e0b1fc9603de0c8b21eb3acbae9f"

enum { ZN_NATIVE_GRAPH_CONV_MAX_READS_V2 = 7 };

typedef struct ZnNativeGraphScratchLeaseV2 {
    uint32_t epoch;
    uint32_t generation;
    uint32_t base;
    uint32_t bytes;
} ZnNativeGraphScratchLeaseV2;

typedef struct ZnNativeGraphDmaSpanV2 {
    uint32_t base;
    uint32_t bytes;
} ZnNativeGraphDmaSpanV2;

typedef struct ZnNativeGraphConvBindingV2 {
    uint32_t dispatch_epoch;
    uint32_t dispatch_tag;
    uint16_t event_index;
    uint8_t graph_read_count;
    ZnRef graph_read_refs[ZN_NATIVE_GRAPH_CONV_MAX_READS_V2];
    ZnRef destination_ref;
    ZnNativeGraphScratchLeaseV2 scratch;
    ZnNativeGraphDmaSpanV2 source_span;
    uint32_t expected_cookie;
    uint32_t expected_job_base;
    uint32_t expected_token_base;
    uint32_t expected_tag_base;
    uint32_t expected_tiles;
    char package_sha256[65];
    char checkpoint_sha256[65];
    char graph_sha256[65];
    ZnNativeConvCommand command;
} ZnNativeGraphConvBindingV2;

/* Callbacks return READY (0), BUSY (1), or a negative failure. A callback
 * returning BUSY/failure must preserve leases and reservations it owns. */
typedef int (*ZnNativeGraphConvCheckLeasesV2)(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding);
typedef int (*ZnNativeGraphConvConvertViewsV2)(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding);
typedef int (*ZnNativeGraphConvCleanSourceV2)(
    void *context, const ZnNativeGraphConvBindingV2 *binding);
typedef int (*ZnNativeGraphConvCheckSourceReadyV2)(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding);
typedef int (*ZnNativeGraphConvInvalidateOutputV2)(
    void *context, const ZnNativeGraphConvBindingV2 *binding);
typedef int (*ZnNativeGraphConvPublishV2)(
    void *context, const ZnNativeGraphConvBindingV2 *binding);
typedef int (*ZnNativeGraphConvDrainReadyV2)(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding);
typedef int (*ZnNativeGraphConvReturnReadV2)(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding, uint8_t read_index);
typedef int (*ZnNativeGraphConvReleaseScratchV2)(
    void *context, const ZnNativeGraphConvBindingV2 *binding);

typedef struct ZnNativeGraphConvHooksV2 {
    void *context;
    ZnNativeGraphConvCheckLeasesV2 check_leases;
    /* Must run the selected view converter into source_span; READY means its
     * full materialization succeeded. It must be resumable/idempotent on BUSY. */
    ZnNativeGraphConvConvertViewsV2 convert_views;
    /* Must clean source_span and complete the platform cache/order barrier. */
    ZnNativeGraphConvCleanSourceV2 clean_source;
    /* Verifies materialization, cache visibility, and lease identity. */
    ZnNativeGraphConvCheckSourceReadyV2 check_source_ready;
    ZnNativeGraphConvInvalidateOutputV2 invalidate_output;
    ZnNativeGraphConvPublishV2 validate_and_publish;
    ZnNativeGraphConvDrainReadyV2 drain_ready;
    /* Performs the matching graph-ledger RETURN for one exact original read. */
    ZnNativeGraphConvReturnReadV2 return_graph_read;
    /* Called only after every RETURN ACK and verified driver quiescence. */
    ZnNativeGraphConvReleaseScratchV2 release_scratch;
} ZnNativeGraphConvHooksV2;

typedef enum ZnNativeGraphConvBridgeCodeV2 {
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED = 0,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY = 1,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_SCRATCH_RELEASED = 2,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_UNSUPPORTED_OPERATION = 3,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_UNBOUND = 4,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ARGUMENT = -1,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST = -2,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_INVALID_BINDING = -3,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED = -4,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_DRIVER = -5
} ZnNativeGraphConvBridgeCodeV2;

typedef enum ZnNativeGraphConvBridgeStageV2 {
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_IDLE = 0,
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING = 1,
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED = 2,
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_PUBLISH = 3,
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_RUN_ACKED = 4,
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_DRAIN_ACKED = 5,
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED = 6,
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_SCRATCH_RELEASED = 7,
    ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED = 8
} ZnNativeGraphConvBridgeStageV2;

typedef struct ZnNativeGraphConvBridgeV2 {
    ZnNativeConvDriverV2 driver;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativeGraphConvBindingV2 binding;
    ZnRequest run_request;
    ZnRequest return_request;
    ZnNativeGraphConvBridgeStageV2 stage;
    uint8_t dispatch_failure_latched;
    uint8_t converted;
    uint8_t source_clean;
    uint8_t return_cursor;
} ZnNativeGraphConvBridgeV2;

ZnNativeGraphConvBridgeCodeV2
zn_native_graph_conv_bridge_init_v2(
    ZnNativeGraphConvBridgeV2 *bridge,
    const ZnNativeConvMmioOpsV2 *mmio,
    const ZnNativeGraphConvHooksV2 *hooks);

/* V2 owns Conv RUN/DRAIN and exact graph read RETURNs. */
ZnNativeGraphConvBridgeCodeV2
zn_native_graph_conv_bridge_step_v2(
    ZnNativeGraphConvBridgeV2 *bridge, ZnDispatch *dispatch,
    const ZnRequest *request, const ZnNativeGraphConvBindingV2 *binding);

/* Call after the final graph read RETURN has been ACKed and before dispatching
 * or ACKing later graph work. BUSY retries this function, not the RETURN. */
ZnNativeGraphConvBridgeCodeV2
zn_native_graph_conv_bridge_finish_v2(
    ZnNativeGraphConvBridgeV2 *bridge, const ZnDispatch *dispatch);

ZnNativeGraphConvBridgeCodeV2
zn_native_graph_conv_bridge_timeout_v2(
    ZnNativeGraphConvBridgeV2 *bridge, ZnDispatch *dispatch,
    const ZnRequest *request);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_GRAPH_CONV_BRIDGE_V2_H */
