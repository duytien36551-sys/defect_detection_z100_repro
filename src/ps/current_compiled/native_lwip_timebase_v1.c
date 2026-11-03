#include "native_lwip_timebase_v1.h"
#include "lwip/opt.h"
#include "lwip/sys.h"
#include "lwip/timeouts.h"

#if NO_SYS != 1 || LWIP_TIMERS != 1 || LWIP_TIMERS_CUSTOM != 0 || \
    (defined(NO_SYS_NO_TIMERS) && NO_SYS_NO_TIMERS != 0)
#error This timebase requires raw lwIP with the standard timeout scheduler
#endif

typedef struct NativeTimebaseOwnerV1 {
    ZnNativeLwipTimebaseConfigV1 config;
    uint64_t last_ticks, fraction, max_gap_ticks;
    uint32_t milliseconds;
    int state;
    unsigned sampling, servicing;
} NativeTimebaseOwnerV1;

static NativeTimebaseOwnerV1 owner;

static int apart(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t av = (uintptr_t)a, bv = (uintptr_t)b;
    return a && b && an && bn && an <= UINTPTR_MAX-av && bn <= UINTPTR_MAX-bv &&
        (av+an <= bv || bv+bn <= av);
}

static int fail(void)
{
    owner.state = ZN_NATIVE_LWIP_TIMEBASE_V1_FAILED;
    return owner.state;
}

static int sample(int initial)
{
    uint64_t ticks = 0, delta, numerator;
    int code;
    if (owner.state != ZN_NATIVE_LWIP_TIMEBASE_V1_READY) return owner.state;
    if (owner.sampling) return fail();
    owner.sampling = 1;
    code = owner.config.read_ticks(owner.config.clock_context, &ticks);
    owner.sampling = 0;
    if (code || owner.state != ZN_NATIVE_LWIP_TIMEBASE_V1_READY) return fail();
    if (!initial) {
        if (ticks < owner.last_ticks) return fail();
        delta = ticks-owner.last_ticks;
        if (delta > owner.max_gap_ticks) return fail();
        /* Hz <= UINT32_MAX, gap <= 60 seconds, fraction < Hz: no uint64
         * multiplication/addition overflow. Fraction survives EVERY sample,
         * so frequent sub-ms sys_now/check calls cannot slow the clock. */
        numerator = delta*UINT64_C(1000)+owner.fraction;
        owner.milliseconds += (uint32_t)(numerator/owner.config.ticks_per_second);
        owner.fraction = numerator%owner.config.ticks_per_second;
    }
    owner.last_ticks = ticks;
    return owner.state;
}

int zn_native_lwip_timebase_bind_v1(const ZnNativeLwipTimebaseConfigV1 *config)
{
    if (!config || !apart(config, sizeof *config, &owner, sizeof owner))
        return ZN_NATIVE_LWIP_TIMEBASE_V1_ARGUMENT;
    if (owner.state) return ZN_NATIVE_LWIP_TIMEBASE_V1_STATE;
    if (!config->read_ticks || !config->clock_context || !config->clock_context_bytes ||
        !apart(config->clock_context, config->clock_context_bytes, &owner, sizeof owner) ||
        !apart(config->clock_context, config->clock_context_bytes, config, sizeof *config) ||
        config->ticks_per_second < UINT64_C(1000) || config->ticks_per_second > UINT32_MAX ||
        !config->max_sample_gap_ms || config->max_sample_gap_ms > UINT32_C(60000))
        return ZN_NATIVE_LWIP_TIMEBASE_V1_ARGUMENT;
    owner.config = *config;
    owner.max_gap_ticks = (config->ticks_per_second*config->max_sample_gap_ms)/UINT64_C(1000);
    owner.state = ZN_NATIVE_LWIP_TIMEBASE_V1_READY;
    return sample(1);
}

int zn_native_lwip_timebase_check_v1(void)
{
    if (!owner.state) return ZN_NATIVE_LWIP_TIMEBASE_V1_STATE;
    return sample(0);
}

int zn_native_lwip_timebase_status_v1(void)
{
    return owner.state ? owner.state : ZN_NATIVE_LWIP_TIMEBASE_V1_STATE;
}

u32_t sys_now(void)
{
    if (!owner.state) (void)fail();
    else (void)sample(0);
    return (u32_t)owner.milliseconds;
}

int zn_native_lwip_timeouts_poll_v1(void)
{
    int code;
    if (owner.servicing) return fail();
    code = zn_native_lwip_timebase_check_v1();
    if (code != ZN_NATIVE_LWIP_TIMEBASE_V1_READY) return code;
    owner.servicing = 1;
    sys_check_timeouts();
    owner.servicing = 0;
    return zn_native_lwip_timebase_check_v1();
}
