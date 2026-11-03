#ifndef Z100_NATIVE_GRAPH_LWIP_V1_H
#define Z100_NATIVE_GRAPH_LWIP_V1_H

#include "native_graph_service_v2.h"

struct netif;
struct tcp_pcb;

enum {
    ZN_NATIVE_LWIP_V1_BOUND = 0,
    ZN_NATIVE_LWIP_V1_LISTENING = 1,
    ZN_NATIVE_LWIP_V1_SERVING = 2,
    ZN_NATIVE_LWIP_V1_DELIVERED = 3,
    ZN_NATIVE_LWIP_V1_ARGUMENT = -1,
    ZN_NATIVE_LWIP_V1_STATE = -2,
    ZN_NATIVE_LWIP_V1_FAILED = -3
};

/* One raw-lwIP singleton, serialized on the caller's execution context. No
 * lwIP/GEM/PHY/GIC/IP/listener initialization is performed here. Initialize the
 * matching platform separately, then attach its live netif/listening PCB.
 * Transport pointer always remains this object; callbacks carry immutable
 * integer generations, so an old PCB/error cannot refer to a new connection.
 * Objects, callbacks and contexts must remain alive. No implicit retry/reset,
 * graph abort/ACK, parameter copy, reservation release or failure recovery. */
typedef struct ZnNativeGraphLwipV1 {
    uint32_t magic;
    int32_t state, transport_error, last_service_code;
    ZnNativeGraphSessionV1 *session;
    ZnNativeGraphServiceV2 *app;
    V8Service *wire;
    struct netif *interface;
    struct tcp_pcb *listener, *peer;
    uintptr_t generation, next_generation;
    uint64_t budget_ticks, connection_start, last_ticks, fast_tick, slow_tick;
    uint64_t requests, rx_bytes, tx_copy_bytes, progress_calls;
    size_t incoming_head, incoming_len;
    uint8_t peer_eof, pumping, dispatching;
    uint8_t incoming[32768];
    ZnNativeGraphServiceTimingV2 last_timing;
} ZnNativeGraphLwipV1;

/* Phase1: zero n/app once; prepare session; wire has frozen identity/buffers and
 * NULL read/write/transport/infer/inference. bind installs only transport
 * callbacks; no clock, lwIP or hardware IO. Only one successful bind per boot.
 * Rejection leaves state/buffers unchanged. Session/app/wire/input mappings and
 * n storage must be separate. The entire-connection deadline is measured from
 * accept, including all short IO, graph execution and close backpressure. */
int zn_native_graph_lwip_bind_v1(ZnNativeGraphLwipV1 *, ZnNativeGraphSessionV1 *,
    ZnNativeGraphServiceV2 *, V8Service *, uint64_t connection_budget_ticks);
/* Phase2: service_init_v2 with progress={progress_v1,n,sizeof *n,1..64}; then
 * attach the caller's already initialized interface/listening PCB. Interface/
 * PCB storage must lie outside graph/service/transport storage. No ownership
 * transfer of the listener/netif; they remain stable for the object's lifetime. */
int zn_native_graph_lwip_attach_v1(ZnNativeGraphLwipV1 *, struct netif *, struct tcp_pcb *);
/* Progress services raw input and TCP timers only; it never dispatches a second
 * request. pump additionally dispatches exactly one native service connection.
 * The service's graph-progress callback must be progress_v1. */
int zn_native_graph_lwip_progress_v1(void *);
int zn_native_graph_lwip_pump_v1(ZnNativeGraphLwipV1 *);
/* Explicit metadata-only rearm, after full tcp_write COPY and successful
 * tcp_close queueing. These do NOT prove ACK or sender receipt. Only the sender
 * trace proves complete receipt; FAILED never permits another connection. */
int zn_native_graph_lwip_rearm_v1(ZnNativeGraphLwipV1 *, uint32_t next_epoch);

#endif
