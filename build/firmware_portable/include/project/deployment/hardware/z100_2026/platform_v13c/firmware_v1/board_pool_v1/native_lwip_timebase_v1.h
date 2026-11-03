#ifndef Z100_NATIVE_LWIP_TIMEBASE_V1_H
#define Z100_NATIVE_LWIP_TIMEBASE_V1_H

#include <stddef.h>
#include <stdint.h>

enum {
    ZN_NATIVE_LWIP_TIMEBASE_V1_READY = 1,
    ZN_NATIVE_LWIP_TIMEBASE_V1_ARGUMENT = -1,
    ZN_NATIVE_LWIP_TIMEBASE_V1_STATE = -2,
    ZN_NATIVE_LWIP_TIMEBASE_V1_FAILED = -3
};

typedef struct ZnNativeLwipTimebaseConfigV1 {
    int (*read_ticks)(void *, uint64_t *);
    void *clock_context;
    size_t clock_context_bytes;
    uint64_t ticks_per_second;
    uint32_t max_sample_gap_ms;
} ZnNativeLwipTimebaseConfigV1;

/* One raw NO_SYS=1, LWIP_TIMERS=1, LWIP_TIMERS_CUSTOM=0 owner per cold boot.
 * Start the platform clock FIRST, bind BEFORE lwip_init. Pass the already
 * started Xilinx clock's read callback/context/Hz. This module neither starts
 * nor resets that clock. No init/reset/release/retry after the first callback.
 * Copy configuration once; callback context must stay alive, at a stable
 * address, separate from config, all IO/model/graph buffers and this module.
 * Serial caller only: no IRQ, thread, other CPU, reentrant clock callback or
 * second sys_now provider. Context exclusivity is the caller's responsibility.
 * Configured Hz must be 1000..UINT32_MAX; max gap 1..60000 ms is a service
 * safety limit, NOT a measured board timing or performance assertion.
 * Invalid preflight arguments perform no clock IO and do not take ownership.
 */
int zn_native_lwip_timebase_bind_v1(const ZnNativeLwipTimebaseConfigV1 *);
/* Sampling check: caller must propagate failure before/after lwIP input and
 * sys_check_timeouts. status() only reads sticky health, without clock IO.
 * sys_now is supplied using the SDK's exact prototype in lwip/sys.h; it returns
 * floor(elapsed_ticks*1000/Hz) modulo 2^32, preserving fractional ticks. On any
 * failure it freezes the last good ms and latches FAILED. sys_now before bind
 * also latches FAILED. No error can be conveyed by sys_now's numeric result.
 * Regression, excessive sample gap, callback error or callback reentry fail.
 * Equal reads are allowed: the platform clock must detect a stopped counter.
 */
int zn_native_lwip_timebase_check_v1(void);
int zn_native_lwip_timebase_status_v1(void);
/* Standard scheduler service, with timebase checks before/after and sticky
 * recursive-service rejection. Call only after lwip_init, from serialized raw
 * progress. It does NOT init the stack, run GEM input, or manually tick TCP.
 * A fault inside a timeout handler is observable after sys_check_timeouts
 * returns; this wrapper cannot preempt SDK handlers or a blocked MMIO access.
 * Startup order and maximum progress interval still need board qualification.
 */
int zn_native_lwip_timeouts_poll_v1(void);

#endif
