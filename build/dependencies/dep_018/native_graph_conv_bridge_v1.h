#ifndef Z100_NATIVE_GRAPH_CONV_BRIDGE_V1_H
#define Z100_NATIVE_GRAPH_CONV_BRIDGE_V1_H

#include "native_conv_driver_v2.h"
#include "native_dispatch.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_GRAPH_CONV_PACKAGE_SHA256_V1 \
    "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c"
#define ZN_NATIVE_GRAPH_CONV_MODEL_SHA256_V1 \
    "2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6"
#define ZN_NATIVE_GRAPH_CONV_GRAPH_SHA256_V1 \
    "9d6064e37e92e61c687608d2c5e216cccb31e0b1fc9603de0c8b21eb3acbae9f"

typedef struct ZnNativeGraphConvBindingV1 {
    uint32_t dispatch_epoch;
    uint32_t dispatch_tag;
    uint16_t event_index;
    ZnRef source_ref;
    ZnRef destination_ref;
    uint32_t source_base;
    uint32_t source_bytes;
    uint32_t expected_cookie;
    uint32_t expected_job_base;
    uint32_t expected_token_base;
    uint32_t expected_tag_base;
    uint32_t expected_tiles;
    char package_sha256[65];
    char checkpoint_sha256[65];
    char graph_sha256[65];
    ZnNativeConvCommand command;
} ZnNativeGraphConvBindingV1;

/* Callbacks return READY (0), BUSY (1), or a negative failure. */
typedef int (*ZnNativeGraphConvCheckOwnershipV1)(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV1 *binding);
typedef int (*ZnNativeGraphConvPrepareDeviceV1)(
    void *context, const ZnNativeGraphConvBindingV1 *binding);
typedef int (*ZnNativeGraphConvInvalidateOutputV1)(
    void *context, const ZnNativeGraphConvBindingV1 *binding);
typedef int (*ZnNativeGraphConvValidatePublishV1)(
    void *context, const ZnNativeGraphConvBindingV1 *binding);
typedef int (*ZnNativeGraphConvDrainReadyV1)(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV1 *binding);

typedef struct ZnNativeGraphConvHooksV1 {
    void *context;
    ZnNativeGraphConvCheckOwnershipV1 check_ownership;
    ZnNativeGraphConvPrepareDeviceV1 prepare_device;
    ZnNativeGraphConvInvalidateOutputV1 invalidate_output;
    ZnNativeGraphConvValidatePublishV1 validate_and_publish;
    ZnNativeGraphConvDrainReadyV1 drain_ready;
} ZnNativeGraphConvHooksV1;

typedef enum ZnNativeGraphConvBridgeCodeV1 {
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED = 0,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY = 1,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_UNSUPPORTED_OPERATION = 2,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_UNBOUND = 3,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ARGUMENT = -1,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST = -2,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_INVALID_BINDING = -3,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED = -4,
    ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_DRIVER = -5
} ZnNativeGraphConvBridgeCodeV1;

typedef enum ZnNativeGraphConvBridgeStageV1 {
    ZN_NATIVE_GRAPH_CONV_STAGE_V1_IDLE = 0,
    ZN_NATIVE_GRAPH_CONV_STAGE_V1_PREPARED = 1,
    ZN_NATIVE_GRAPH_CONV_STAGE_V1_SUBMITTED = 2,
    ZN_NATIVE_GRAPH_CONV_STAGE_V1_INVALIDATE = 3,
    ZN_NATIVE_GRAPH_CONV_STAGE_V1_PUBLISH = 4,
    ZN_NATIVE_GRAPH_CONV_STAGE_V1_RUN_ACKED = 5,
    ZN_NATIVE_GRAPH_CONV_STAGE_V1_DRAIN_ACKED = 6,
    ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED = 7
} ZnNativeGraphConvBridgeStageV1;

typedef struct ZnNativeGraphConvBridgeV1 {
    ZnNativeConvDriverV2 driver;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBindingV1 binding;
    ZnRequest run_request;
    ZnNativeGraphConvBridgeStageV1 stage;
    uint8_t dispatch_failure_latched;
    uint8_t ownership_check_busy;
} ZnNativeGraphConvBridgeV1;

ZnNativeGraphConvBridgeCodeV1
zn_native_graph_conv_bridge_init_v1(
    ZnNativeGraphConvBridgeV1 *bridge,
    const ZnNativeConvMmioOpsV2 *mmio,
    const ZnNativeGraphConvHooksV1 *hooks);

/* RUN requires the caller's validated command binding. DRAIN uses the immutable
 * RUN binding retained by this bridge; its binding argument may be NULL. */
ZnNativeGraphConvBridgeCodeV1
zn_native_graph_conv_bridge_step_v1(
    ZnNativeGraphConvBridgeV1 *bridge, ZnDispatch *dispatch,
    const ZnRequest *request, const ZnNativeGraphConvBindingV1 *binding);

/* Applies the real driver's preaccept ABORT / accepted CANCEL protocol. */
ZnNativeGraphConvBridgeCodeV1
zn_native_graph_conv_bridge_timeout_v1(
    ZnNativeGraphConvBridgeV1 *bridge, ZnDispatch *dispatch,
    const ZnRequest *request);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_GRAPH_CONV_BRIDGE_V1_H */
