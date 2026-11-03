#ifndef Z100_NATIVE_GRAPH_POLLER_V1_H
#define Z100_NATIVE_GRAPH_POLLER_V1_H

#include "native_graph_executor_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_GRAPH_POLLER_MAX_STEPS_V1 64u

typedef enum ZnNativeGraphPollerCodeV1 {
    ZN_NATIVE_GRAPH_POLLER_V1_YIELDED = 0,
    ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE = 1,
    ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE_LATE = 2,
    ZN_NATIVE_GRAPH_POLLER_V1_TIMED_OUT = -1,
    ZN_NATIVE_GRAPH_POLLER_V1_EXECUTOR_FAILED = -2,
    ZN_NATIVE_GRAPH_POLLER_V1_CLOCK_FAILED = -3,
    ZN_NATIVE_GRAPH_POLLER_V1_IDENTITY = -4,
    ZN_NATIVE_GRAPH_POLLER_V1_ARGUMENT = -5
} ZnNativeGraphPollerCodeV1;

/* Return 0 and a monotonic, nonwrapping 64-bit counter. The clock callback
 * must not call the executor, alter graph state, or perform hardware work. */
typedef int (*ZnNativeGraphPollerTicksV1)(void *context, uint64_t *ticks);

/* Exposed for static storage only. After init all fields are API-owned; the
 * caller may read statistics but must not modify this object, its pointers,
 * counters or terminal state. Identity checks compare the separately owned
 * executor/frame relationships against these retained, unmodified anchors;
 * they are not a memory-corruption or arbitrary-struct-tampering defense. */
typedef struct ZnNativeGraphPollerV1 {
    uint32_t magic;
    ZnNativeGraphExecutorV1 *executor;
    ZnNativeArenaOwnerV1 *owner;
    ZnDispatch *dispatch;
    ZnNativeArenaConvLifecycleV1 *conv;
    ZnNativeArenaNonConvLifecycleV1 *nonconv;
    ZnNativeGraphExecutorResolveConvV1 resolver;
    void *resolver_context;
    const ZnEvent *events;
    uint32_t epoch;
    uint16_t event_count;
    ZnNativeGraphPollerTicksV1 read_ticks;
    void *clock_context;
    uint64_t ticks_per_second;
    uint64_t budget_ticks;
    uint64_t start_ticks;
    uint64_t last_ticks;
    uint64_t elapsed_ticks;
    uint64_t executor_calls;
    uint64_t busy_calls;
    uint64_t acked_calls;
    uint64_t scratch_releases;
    int32_t last_executor_code;
    int32_t terminal_code;
    uint8_t terminal;
} ZnNativeGraphPollerV1;

/* Zero-initialize once; reinitialization is rejected. The caller has already
 * initialized the executor and retains all objects/callbacks for this frame.
 * No time-unit conversion is implicit. The budget starts at this call, so
 * gaps between subsequent poll calls count against the same frame deadline. */
ZnNativeGraphPollerCodeV1 zn_native_graph_poller_init_v1(
    ZnNativeGraphPollerV1 *poller, ZnNativeGraphExecutorV1 *executor,
    ZnNativeGraphPollerTicksV1 read_ticks, void *clock_context,
    uint64_t ticks_per_second, uint64_t budget_ticks);

/* Calls the real executor at most max_steps times (1..64). No sleep, reset,
 * automatic frame restart, bridge timeout, or hardware abort is performed.
 * The caller serializes all graph/driver operations. Callbacks themselves
 * must be bounded: polling cannot preempt synchronous conversion/MMIO calls.
 * COMPLETE_LATE means graph completion was already verified when the final
 * clock sample exceeded the budget; it does not claim rollback or throughput.
 * A detected deadline before completion faults via executor timeout, retaining
 * current ownership. A separate abort adapter must establish quiescence. */
ZnNativeGraphPollerCodeV1 zn_native_graph_poller_poll_v1(
    ZnNativeGraphPollerV1 *poller, uint32_t max_steps);

#ifdef __cplusplus
}
#endif
#endif
