#ifndef Z100_NATIVE_GRAPH_ABORT_V1_H
#define Z100_NATIVE_GRAPH_ABORT_V1_H

#include "native_graph_executor_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum ZnNativeGraphAbortCodeV1 {
    ZN_NATIVE_GRAPH_ABORT_V1_READY = 0,
    ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS = 1,
    ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED = 2,
    ZN_NATIVE_GRAPH_ABORT_V1_ARGUMENT = -1,
    ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY = -2,
    ZN_NATIVE_GRAPH_ABORT_V1_DRIVER = -3,
    ZN_NATIVE_GRAPH_ABORT_V1_OWNERSHIP = -4
} ZnNativeGraphAbortCodeV1;

typedef enum ZnNativeGraphAbortStateV1 {
    ZN_NATIVE_GRAPH_ABORT_STATE_V1_UNINITIALIZED = 0,
    ZN_NATIVE_GRAPH_ABORT_STATE_V1_ARMED = 1,
    ZN_NATIVE_GRAPH_ABORT_STATE_V1_QUIESCENT = 2,
    ZN_NATIVE_GRAPH_ABORT_STATE_V1_FAILED = 3
} ZnNativeGraphAbortStateV1;

/* This adapter consumes only the already-resolved Conv RUN terminal. Its
 * snapshots bind it to that exact failed graph and allow every call to reject
 * intervening owner, dispatcher, executor, bridge, or command changes. */
typedef struct ZnNativeGraphAbortV1 {
    ZnNativeGraphExecutorV1 *executor;
    ZnNativeArenaOwnerV1 *owner;
    ZnDispatch *dispatch;
    ZnNativeArenaConvLifecycleV1 *conv_lifecycle;
    ZnNativeArenaNonConvLifecycleV1 *nonconv_lifecycle;
    ZnNativeGraphConvBridgeV2 *bridge;
    ZnNativeConvDriverV2 *driver;
    ZnNativeGraphExecutorV1 executor_snapshot;
    ZnNativeArenaOwnerV1 owner_snapshot;
    ZnDispatch dispatch_snapshot;
    ZnNativeArenaConvLifecycleV1 conv_snapshot;
    ZnNativeArenaNonConvLifecycleV1 nonconv_snapshot;
    ZnNativeGraphConvBindingV2 binding_snapshot;
    ZnNativeConvCommand command_snapshot;
    ZnNativeConvMmioOpsV2 mmio_snapshot;
    uint32_t command_words_snapshot[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t expected_tiles_snapshot;
    int32_t terminal_code_snapshot;
    int32_t last_driver_code;
    int32_t failure_code;
    uint8_t state;
} ZnNativeGraphAbortV1;

/* Bind only after the executor has latched a terminal fault for this RUN.
 * This records identities and performs no MMIO or ownership transition. */
ZnNativeGraphAbortCodeV1
zn_native_graph_abort_v1_init(ZnNativeGraphAbortV1 *adapter,
                              ZnNativeGraphExecutorV1 *executor);

/* Performs one bounded driver timeout, poll, or checked ACK action. The caller
 * owns the overall deadline and may stop calling at any time. */
ZnNativeGraphAbortCodeV1
zn_native_graph_abort_v1_step(ZnNativeGraphAbortV1 *adapter);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_GRAPH_ABORT_V1_H */
