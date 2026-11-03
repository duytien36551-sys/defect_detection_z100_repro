#ifndef Z100_NATIVE_POOL_ASYNC_V1_H
#define Z100_NATIVE_POOL_ASYNC_V1_H
#include "native_pool_command_v1.h"
#include <stddef.h>

typedef struct {
    void *context;
    int (*clean)(void *, void *, size_t);
    int (*invalidate)(void *, void *, size_t);
    int (*barrier)(void *);
} ZnPoolCacheOpsV1;

typedef struct {
    uint32_t physical_address;
    void *cpu_address;
    size_t bytes;
} ZnPoolMappingV1;

enum { ZN_POOL_ASYNC_BUSY = 1, ZN_POOL_ASYNC_DONE = 0,
       ZN_POOL_ASYNC_ERROR = -1 };
enum { ZN_POOL_ASYNC_IDLE = 0, ZN_POOL_ASYNC_RUNNING = 1,
       ZN_POOL_ASYNC_COMPLETE = 2, ZN_POOL_ASYNC_FAILED = 3 };

typedef struct {
    ZnNativeConvDriverV2 *driver;
    ZnPoolCacheOpsV1 cache;
    ZnPoolMappingV1 source, destination;
    unsigned state;
    unsigned cancelled;
} ZnPoolAsyncV1;

/* Zero-initialize once. Serialized application context only. The caller retains
 * graph references, reservations and both mappings from begin until DONE.
 * ERROR never authorizes graph release, reset or retry. After ERROR inspect the
 * transport drain state and use coordinated platform recovery. No CPU fallback.
 * The shared driver must also be the Conv driver's single hardware owner. */
int zn_pool_async_begin_v1(ZnPoolAsyncV1 *, ZnNativeConvDriverV2 *,
    const ZnNativeConvCommand *, const ZnPoolMappingV1 *,
    const ZnPoolMappingV1 *, const ZnPoolCacheOpsV1 *);
/* A bounded poll; DONE requires checked result, destination invalidation,
 * barrier and successful ACK/readback. No destination clean after PL writes. */
int zn_pool_async_poll_v1(ZnPoolAsyncV1 *);
/* Issue ABORT/CANCEL using transport race handling, then continue polling.
 * Cancellation can never produce DONE, including a same-edge success race. */
int zn_pool_async_cancel_v1(ZnPoolAsyncV1 *);
/* Failure-service step, callable even after a graph/cache failure. Marks the
 * operation failed, issues race-safe ABORT/CANCEL if still pending/active, and
 * continues physical status polling. Returns 2 only for a checked drained
 * terminal record; 1 while draining; -1 if observation cannot prove quiescence.
 * It never ACKs, publishes, releases graph refs or resets hardware. */
int zn_pool_async_abort_drain_v1(ZnPoolAsyncV1 *);
#endif
