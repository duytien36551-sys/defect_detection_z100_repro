#ifndef Z100_NATIVE_GRAPH_SESSION_V1_H
#define Z100_NATIVE_GRAPH_SESSION_V1_H

#include "native_graph_frame_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

enum {
    ZN_NATIVE_SESSION_V1_READY = 0,
    ZN_NATIVE_SESSION_V1_ARGUMENT = -1,
    ZN_NATIVE_SESSION_V1_STATE = -2,
    ZN_NATIVE_SESSION_V1_FAILED = -3
};

/* Bit order for reservation diagnostics; attempted includes a failed callback,
 * whose ownership is conservatively unknown. There is no implicit release. */
#define ZN_NATIVE_SESSION_ARENA_V1 UINT32_C(1)
#define ZN_NATIVE_SESSION_HEADS_V1 UINT32_C(2)
#define ZN_NATIVE_SESSION_PARAMETERS_V1 UINT32_C(4)
#define ZN_NATIVE_SESSION_DIRECTORY_V1 UINT32_C(8)
#define ZN_NATIVE_SESSION_SCRATCH_V1 UINT32_C(16)

typedef struct ZnNativeGraphSessionConfigV1 {
    ZnNativeGraphFrameConfigV1 frame;
    ZnNativePlatformMemoryRequestV1 model;
} ZnNativeGraphSessionConfigV1;

/* Static, serialized, one-time model preparation followed by many frames.
 * Exact frozen mappings only. Caller establishes physical/MMU/platform identity
 * and supplies a real exclusive reservation service. Callbacks must not mutate
 * session/config/source metadata; contexts must remain stable and outside all
 * writable buffers. Session and source image/string storage remain alive.
 * Fields are diagnostic: do not modify them or call frame APIs directly.
 * No heap, hardware probing, reset, abort, release, or automatic recovery. */
typedef struct ZnNativeGraphSessionV1 {
    uint32_t magic;
    int32_t state, prepare_code, callback_status;
    uint32_t attempted_reservations, reserved;
    ZnNativePlatformMemoryStateV1 model_state;
    ZnNativePlatformMemoryRequestV1 model;
    ZnNativeGraphFrameV1 frame;
} ZnNativeGraphSessionV1;

/* Zero once before first use. Session preflight rejection has no side effects.
 * Then constructs frame metadata (no IO), reserves arena, HEADS, parameters,
 * directory, scratch, and invokes real copy/cache/readback SHA verification.
 * All five reservations precede any copy. Any later failure latches FAILED;
 * bytes/ownership may have changed. Never retry or memset after that failure
 * until external recovery establishes quiescence and resolves reservations.
 * Successful prepare is the only transition permitting frame start. */
int zn_native_graph_session_prepare_v1(ZnNativeGraphSessionV1 *, const ZnNativeGraphSessionConfigV1 *);
int zn_native_graph_session_start_v1(ZnNativeGraphSessionV1 *, const uint8_t *, size_t);
int zn_native_graph_session_poll_v1(ZnNativeGraphSessionV1 *, uint32_t);
int zn_native_graph_session_heads_v1(const ZnNativeGraphSessionV1 *, const uint8_t **, size_t *);
/* Metadata-only rearm after verified success; never recopies model images. */
int zn_native_graph_session_rearm_v1(ZnNativeGraphSessionV1 *, uint32_t);

#ifdef __cplusplus
}
#endif
#endif
