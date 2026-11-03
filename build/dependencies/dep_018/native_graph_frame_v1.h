#ifndef Z100_NATIVE_GRAPH_FRAME_V1_H
#define Z100_NATIVE_GRAPH_FRAME_V1_H

#include "native_graph_conv_runtime_v1.h"
#include "native_graph_poller_v1.h"
#include "native_nonconv_runtime_hooks_v1.h"
#include "native_pool_scheduler_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_FRAME_INPUT_BYTES_V1 1228800u
#define ZN_NATIVE_FRAME_NATIVE_INPUT_BYTES_V1 1638400u

enum {
    ZN_NATIVE_FRAME_V1_READY = 0,
    ZN_NATIVE_FRAME_V1_YIELDED = 1,
    ZN_NATIVE_FRAME_V1_COMPLETE = 2,
    ZN_NATIVE_FRAME_V1_COMPLETE_LATE = 3,
    ZN_NATIVE_FRAME_V1_ARGUMENT = -1,
    ZN_NATIVE_FRAME_V1_STATE = -2,
    ZN_NATIVE_FRAME_V1_FAILED = -3
};

typedef struct ZnNativeGraphFrameConfigV1 {
    uint32_t epoch;
    ZnNativeArenaConfigV1 arena_config;
    ZnNativePlatformMappedSpanV1 arena, scratch, heads;
    ZnNativeDirectIdsV2 ids;
    ZnPoolScheduleConfigV1 pool_ids;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativePlatformMemoryOpsV1 memory;
    void *memory_context;
    ZnNativeGraphPollerTicksV1 read_ticks;
    void *clock_context;
    uint64_t ticks_per_second, budget_ticks;
} ZnNativeGraphFrameConfigV1;

/* One serialized frame, no heap, IO policy or hidden hardware reset. The
 * caller has already reserved exclusive arena/scratch/HEADS, prepared and
 * verified frozen parameters/directory with native_platform_memory_v1, and
 * established the matching platform/MMU/cache configuration. Init only
 * constructs software state; it cannot establish these physical prerequisites.
 * Keep this object, mappings, callbacks and callback contexts stable. Do not
 * overwrite/reinitialize a started or failed frame. External recovery owns
 * physical quiescence; native_graph_abort_v1 may consume frame.executor.
 * Fields are exposed for static storage/diagnostics, not caller mutation. */
typedef struct ZnNativeGraphFrameV1 {
    uint32_t magic;
    int32_t state, last_poller_code;
    ZnNativeGraphFrameConfigV1 config;
    ZnDispatch dispatch;
    ZnNativeArenaOwnerV1 owner;
    ZnNativeArenaConvLifecycleV1 conv;
    ZnNativeArenaNonConvLifecycleV1 nonconv;
    ZnNativeGraphConvRuntimeV1 conv_runtime;
    ZnNativeNonConvRuntimeHooksV1 nonconv_runtime;
    ZnPoolSchedulerV1 pool_scheduler;
    ZnNativeGraphConvHooksV2 conv_hooks;
    ZnNativeArenaNonConvHooksV1 nonconv_hooks;
    ZnNativeGraphExecutorV1 executor;
    ZnNativeGraphPollerV1 poller;
} ZnNativeGraphFrameV1;

/* Initialize a zeroed frame once. No MMIO, cache callbacks or clock sampling.
 * Static argument/plan rejection leaves the frame and all buffers unchanged.
 * A later construction failure leaves a terminal frame, never a usable one. */
int zn_native_graph_frame_init_v1(ZnNativeGraphFrameV1 *, const ZnNativeGraphFrameConfigV1 *);

/* Input is already preprocessed signed INT8 NCHW 1x3x640x640, not RGB uint8.
 * Starts the frame deadline BEFORE packing. Packs only input slot0 into the
 * native stream, with zero fourth-channel padding. First Conv lifecycle owns
 * cache clean/barriers before hardware submission. No MMIO is issued here.
 * Input must be disjoint from all retained state and all three mapped buffers. */
int zn_native_graph_frame_start_v1(ZnNativeGraphFrameV1 *, const uint8_t *, size_t);

/* Up to 64 executor calls; gaps between calls count in the same deadline.
 * Failures retain leases and reservations. No reset, abort or restart occurs. */
int zn_native_graph_frame_poll_v1(ZnNativeGraphFrameV1 *, uint32_t max_steps);

/* Available only at verified completion, including COMPLETE_LATE. Returns
 * 613200 bytes of NCHW INT8 heads; padded mapping is 613248 bytes. Output
 * variables must lie outside frame and its mappings. No decoder is invoked. */
int zn_native_graph_frame_heads_v1(const ZnNativeGraphFrameV1 *, const uint8_t **, size_t *);

/* Fault-service Pool drain only, one bounded step; return 2 is checked
 * physical terminal with graph ownership retained. Never reset/rearm on this.
 * If the current failure belongs to Conv, use the existing Conv abort adapter. */
int zn_native_graph_frame_pool_abort_v1(ZnNativeGraphFrameV1 *);

/* After the caller has consumed HEADS, reuse the same reserved buffers and
 * metadata for a strictly increasing epoch. Requires verified graph completion,
 * all arena slots retired/quiet, both cache transactions released and the
 * driver idle without ownership. Performs no IO or buffer clearing. Invalidates
 * prior HEADS access through this API. A failed/active frame cannot be rearmed. */
int zn_native_graph_frame_rearm_v1(ZnNativeGraphFrameV1 *, uint32_t next_epoch);

#ifdef __cplusplus
}
#endif
#endif
