#ifndef Z100_NATIVE_PLATFORM_CLOCK_XILINX_V1_H
#define Z100_NATIVE_PLATFORM_CLOCK_XILINX_V1_H
#include <stdint.h>

#define ZN_NATIVE_CLOCK_V1_MAX_STAGNANT_READS 1024u
enum {
    ZN_NATIVE_CLOCK_V1_READY=0,
    ZN_NATIVE_CLOCK_V1_ARGUMENT=-1,
    ZN_NATIVE_CLOCK_V1_STATE=-2,
    ZN_NATIVE_CLOCK_V1_FAILED=-3
};
typedef struct ZnNativePlatformClockXilinxV1 {
    uint32_t magic;
    int32_t state;
    uint32_t cpu_hz, startup_reads, stagnant_reads;
    uint64_t ticks_per_second, last_ticks;
} ZnNativePlatformClockXilinxV1;

/* Cold SDK default global-timer startup, before any deadline timestamps.
 * Requires Cortex-A9 SDT, static configured CPU frequency and SDK constructors.
 * usleep(0) primes the SDK's one-shot start without waiting for elapsed ticks;
 * the SDK may zero a previously unstarted global timer. Bounded reads then
 * require advancement. No second init or automatic recovery, even on failure.
 * Keep object separate from SDK state, graph/IO buffers and callback contexts.
 * Configuration-derived Hz is not an independently measured oscillator rate. */
int zn_native_platform_clock_xilinx_init_v1(ZnNativePlatformClockXilinxV1 *);
/* Session-compatible callback. Equal consecutive samples are allowed up to
 * MAX_STAGNANT_READS, then latch failure. Regression or frequency-table change
 * also fails. Failure/invalid output alias leaves the output untouched.
 * The callback cannot preempt a blocked MMIO access inside the SDK. */
int zn_native_platform_clock_xilinx_read_v1(void *,uint64_t *);
#endif
