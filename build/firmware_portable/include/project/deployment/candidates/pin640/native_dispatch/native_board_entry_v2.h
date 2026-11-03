#ifndef Z100_NATIVE_BOARD_ENTRY_V2_H
#define Z100_NATIVE_BOARD_ENTRY_V2_H
#include "native_graph_network_bootstrap_v2.h"

enum {
    ZN_NATIVE_BOARD_V2_UNINITIALIZED=0,
    ZN_NATIVE_BOARD_V2_LISTENING=1,
    ZN_NATIVE_BOARD_V2_DELIVERED=2,
    ZN_NATIVE_BOARD_V2_STARTING=3,
    ZN_NATIVE_BOARD_V2_ARGUMENT=-1,
    ZN_NATIVE_BOARD_V2_STATE=-2,
    ZN_NATIVE_BOARD_V2_FAILED=-3
};
enum {
    ZN_NATIVE_BOARD_V2_CLOCK=1,
    ZN_NATIVE_BOARD_V2_LAYOUT,
    ZN_NATIVE_BOARD_V2_ADAPTERS,
    ZN_NATIVE_BOARD_V2_SESSION,
    ZN_NATIVE_BOARD_V2_BIND,
    ZN_NATIVE_BOARD_V2_SERVICE,
    ZN_NATIVE_BOARD_V2_NETWORK,
    ZN_NATIVE_BOARD_V2_PUMP,
    ZN_NATIVE_BOARD_V2_REARM
};

typedef struct ZnNativeBoardConfigV2 {
    ZnNativeGraphNetworkConfigV2 network;
    ZnNativeDirectIdsV2 ids;
    uint32_t initial_epoch, poll_steps;
    /* Safety deadlines, NOT a 30FPS target. Explicit nonzero microseconds;
     * rounded up using the SDK configured frequency (not measured Hz). */
    uint64_t graph_timeout_us, connection_timeout_us;
    /* Required raw-network service gap bound, 1..60000 ms. Not measured FPS. */
    uint32_t network_max_sample_gap_ms;
} ZnNativeBoardConfigV2;

typedef struct ZnNativeBoardDiagnosticsV2 {
    int32_t state, stage, last_code, session_code, network_stage, timebase_code;
    uint32_t epoch, reserved_mask, attempted_mask;
    uint64_t ticks_per_second, graph_budget_ticks, connection_budget_ticks;
    uint64_t delivered_requests;
    ZnNativeGraphServiceTimingV2 last_timing;
} ZnNativeBoardDiagnosticsV2;

/* One cold standalone boot, static buffers, fixed identity mappings. Requires
 * a qualified matching HP64 guard_v3 bit/XSA/BSP, DDR, MMU Device mapping and
 * exclusive linker layout BEFORE use. No runtime field claims to prove them.
 * The front-end ABI is shared with old cores and cannot establish that identity.
 * start primes the timer before deadlines, acquires five reservations, copies
 * and verifies embedded images, then binds service and starts the SDK network.
 * SDT startup can block in PHY init. Never retry a started/failed instance.
 * Rejects static bad config without IO. No implicit reset/release/recovery.
 * Calls are serialized on the application context, never from an IRQ. */
int zn_native_board_start_v2(const ZnNativeBoardConfigV2 *);
/* A finite application iteration, but an accepted service request is handled
 * synchronously through existing bounded callbacks. SDK/MMIO blocking is not
 * preemptible. DELIVERED is queued COPY/close, not sender receipt or TCP ACK.
 * Does not accept another request until the application explicitly rearms. */
int zn_native_board_step_v2(void);
int zn_native_board_rearm_v2(uint32_t next_epoch);
/* Read-only diagnostic view; never modify/cast away const. No IO. */
const ZnNativeBoardDiagnosticsV2 *zn_native_board_diagnostics_v2(void);

/* Supplied by the deployment owner in an independently generated .c file.
 * No default address, MAC, deadline, epoch or hardware timeout is provided. */
extern const ZnNativeBoardConfigV2 zn_native_board_configuration_v2;
#endif
