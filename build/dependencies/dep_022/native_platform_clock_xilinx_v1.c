#include "native_platform_clock_xilinx_v1.h"
#include "xiltimer.h"
#include "xcortexa9_config.h"
#include "sleep.h"
#include <stddef.h>
#include <string.h>

#if !defined(ZN_NATIVE_CLOCK_V1_HOST_MODEL) && (!defined(SDT) || !defined(__ARM_ARCH_7A__))
#error This clock adapter requires Cortex-A9 SDT
#endif
#if !defined(XTIMER_IS_DEFAULT_TIMER) || XTIMER_IS_DEFAULT_TIMER!=1 || \
    defined(XSLEEPTIMER_IS_AXITIMER) || defined(XSLEEPTIMER_IS_TTCPS) || defined(XSLEEPTIMER_IS_SCUTIMER) || \
    defined(XTIMER_DEFAULT_TIMER_IS_MB) || defined(XTIMER_DEFAULT_TIMER_IS_MB_RISCV)
#error This clock adapter requires the Cortex-A9 SDK default global sleep timer
#endif
#if !defined(XPAR_CPU_CORE_CLOCK_FREQ_HZ) || !defined(COUNTS_PER_SECOND)
#error The BSP must define CPU and global-timer configured frequencies
#endif
#if COUNTS_PER_SECOND != XPAR_CPU_CORE_CLOCK_FREQ_HZ/2
#error Global timer frequency must match the configured Cortex-A9 CPU clock / 2
#endif

#define CLOCK_MAGIC UINT32_C(0x4e434c31)
static ZnNativePlatformClockXilinxV1 *clock_owner;

static int apart(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t av=(uintptr_t)a,bv=(uintptr_t)b;
    return a && b && an<=UINTPTR_MAX-av && bn<=UINTPTR_MAX-bv && (av+an<=bv || bv+bn<=av);
}
static int fail(ZnNativePlatformClockXilinxV1 *c)
{
    c->state=ZN_NATIVE_CLOCK_V1_FAILED;
    return c->state;
}

int zn_native_platform_clock_xilinx_init_v1(ZnNativePlatformClockXilinxV1 *c)
{
    XTime baseline,now;
    uint32_t i;
    if (!c || !apart(c,sizeof *c,&TimerInst,sizeof TimerInst)) return ZN_NATIVE_CLOCK_V1_ARGUMENT;
    if (clock_owner || c->magic) return ZN_NATIVE_CLOCK_V1_STATE;
    memset(c,0,sizeof *c); c->magic=CLOCK_MAGIC; clock_owner=c;
    c->state=ZN_NATIVE_CLOCK_V1_FAILED;
    c->cpu_hz=XGet_CpuFreq();
    if (!c->cpu_hz || c->cpu_hz!=XPAR_CPU_CORE_CLOCK_FREQ_HZ || !TimerInst.XTimer_ModifyInterval)
        return fail(c);
    c->ticks_per_second=(uint64_t)COUNTS_PER_SECOND;
    if (!c->ticks_per_second) return fail(c);
    usleep(0UL);
    XTime_GetTime(&baseline);
    for (i=0;i<ZN_NATIVE_CLOCK_V1_MAX_STAGNANT_READS;++i) {
        XTime_GetTime(&now); ++c->startup_reads;
        if (now<baseline) return fail(c);
        if (now>baseline) {
            c->last_ticks=now; c->state=ZN_NATIVE_CLOCK_V1_READY;
            return c->state;
        }
    }
    return fail(c);
}

int zn_native_platform_clock_xilinx_read_v1(void *context,uint64_t *out)
{
    ZnNativePlatformClockXilinxV1 *c=context;
    XTime now;
    if (!c || c!=clock_owner || c->magic!=CLOCK_MAGIC || !out ||
        !apart(out,sizeof *out,c,sizeof *c) || !apart(out,sizeof *out,&TimerInst,sizeof TimerInst))
        return ZN_NATIVE_CLOCK_V1_ARGUMENT;
    if (c->state!=ZN_NATIVE_CLOCK_V1_READY) return ZN_NATIVE_CLOCK_V1_STATE;
    if (XGet_CpuFreq()!=c->cpu_hz) return fail(c);
    XTime_GetTime(&now);
    if (now<c->last_ticks) return fail(c);
    if (now==c->last_ticks) {
        if (++c->stagnant_reads>=ZN_NATIVE_CLOCK_V1_MAX_STAGNANT_READS) return fail(c);
    } else c->stagnant_reads=0;
    c->last_ticks=now; *out=now;
    return ZN_NATIVE_CLOCK_V1_READY;
}
