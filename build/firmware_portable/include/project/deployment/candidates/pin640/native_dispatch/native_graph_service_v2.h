/* Independent progress-enabled candidate; accepted service v1 remains unchanged. */
#ifndef Z100_NATIVE_GRAPH_SERVICE_V2_H
#define Z100_NATIVE_GRAPH_SERVICE_V2_H

#include "native_graph_session_v1.h"
#include "v8_service.h"

#ifdef __cplusplus
extern "C" {
#endif

enum {
    ZN_NATIVE_SERVICE_V2_READY = 0,
    ZN_NATIVE_SERVICE_V2_SERVING = 1,
    ZN_NATIVE_SERVICE_V2_RESULT_PENDING = 2,
    ZN_NATIVE_SERVICE_V2_DELIVERED = 3,
    ZN_NATIVE_SERVICE_V2_ARGUMENT = -1,
    ZN_NATIVE_SERVICE_V2_STATE = -2,
    ZN_NATIVE_SERVICE_V2_FAILED = -3
};

typedef struct ZnNativeGraphServiceTimingV2 {
    uint32_t epoch;
    int32_t wire_code, frame_code, decode_code;
    uint64_t ticks_per_second;
    uint64_t connection_start, connection_end;
    uint64_t infer_start, preprocess_end, graph_end, decode_end;
    uint64_t preprocess_ticks, graph_ticks, decode_ticks, infer_ticks, connection_ticks;
    size_t detections;
    uint8_t clock_valid, inference_completed, result_delivered, graph_complete_late;
} ZnNativeGraphServiceTimingV2;

typedef struct ZnNativeGraphServiceProgressV2 {
    int (*progress)(void *); /* Serialized; zero means healthy, failure latches. */
    void *context;
    size_t context_bytes; /* Whole writable context, disjoint from retained data. */
    uint32_t poll_steps; /* 1..64 executor steps between progress callbacks. */
} ZnNativeGraphServiceProgressV2;

/* One serialized network request, no transport retry or hardware recovery.
 * Initialize only against a freshly prepared READY session. All service buffers,
 * callback contexts and objects remain caller-owned/stable. The adapter binds
 * the frozen model/classes and existing pin9-v8/2-input640 service. It supplies
 * RGB preprocessing, session polling and fixed all-class decode/NMS.
 * The caller must not invoke/modify the session or service independently.
 * Success is RESULT fully written according to the transport write contract;
 * this does not prove sender receipt. Failure retains buffers/reservations.
 * Timing uses the session's single clock, in raw ticks. Connection scope starts
 * before HELLO read and ends after final write, so it is NOT sender end-to-end
 * timing and must not be imported as a full-pipeline acceptance trace. */
typedef struct ZnNativeGraphServiceV2 {
    uint32_t magic;
    int32_t state;
    ZnNativeGraphSessionV1 *session;
    V8Service *wire;
    int8_t *input_nchw;
    size_t input_bytes;
    uint64_t last_ticks;
    V8ServiceRead read;
    V8ServiceWrite write;
    void *transport;
    ZnNativeGraphServiceProgressV2 progress;
    ZnNativeGraphServiceTimingV2 timing;
} ZnNativeGraphServiceV2;

/* app must be zero-initialized once. service has verified frozen package/classes, domain pin, nine classes,
 * read/write callbacks, disjoint RGB/detection/response storage, and NULL
 * infer/inference. detection_capacity must equal 300; response >=65536 bytes.
 * nchw is exactly 1228800 bytes, separate from all retained data. Invalid
 * configuration has no callbacks or writes to app/service/buffers. */
int zn_native_graph_service_init_v2(ZnNativeGraphServiceV2 *, ZnNativeGraphSessionV1 *,
                                   V8Service *, int8_t *nchw, size_t nchw_bytes,
                                   const ZnNativeGraphServiceProgressV2 *progress);
/* NULL progress retains v1 polling behavior. A callback may service network
 * input/timers but must not call service/session APIs or mutate their metadata.
 * It is called before each poll and once after terminal completion, including
 * the first poll before any Conv starts. Failure retains in-flight graph leases;
 * no reset/abort/ACK/recovery is implicit. */
/* Exactly one HELLO/INFER/RESULT connection; the existing service handles short
 * reads/writes. Transport callbacks must enforce their own finite deadlines;
 * a synchronous blocking callback cannot be preempted by graph polling. */
int zn_native_graph_service_one_v2(ZnNativeGraphServiceV2 *);
/* Only after confirmed full RESULT write. Metadata-only; strictly newer epoch.
 * No next request/reuse is allowed while RESULT_PENDING or after any failure. */
int zn_native_graph_service_rearm_v2(ZnNativeGraphServiceV2 *, uint32_t next_epoch);

#ifdef __cplusplus
}
#endif
#endif
