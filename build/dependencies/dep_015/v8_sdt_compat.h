#ifndef V8_SDT_COMPAT_H
#define V8_SDT_COMPAT_H

#include "xil_types.h"
#include "xparameters.h"

#if defined(SDT)
#if !defined(XPAR_XAXIDMA_0_BASEADDR)
#error SDT firmware requires XPAR_XAXIDMA_0_BASEADDR
#endif
#if !defined(XPAR_XSCUGIC_0_BASEADDR)
#error SDT firmware requires XPAR_XSCUGIC_0_BASEADDR
#endif
#if !defined(XPAR_CPU_CORE_CLOCK_FREQ_HZ)
#error SDT Cortex-A9 firmware requires XPAR_CPU_CORE_CLOCK_FREQ_HZ
#endif
#define V8_DMA_CONFIG_LOOKUP_KEY XPAR_XAXIDMA_0_BASEADDR
#define V8_GIC_CONFIG_LOOKUP_KEY XPAR_XSCUGIC_0_BASEADDR
#include "xiltimer.h"
#include "sleep.h"
#if !defined(XPAR_XILTIMER_ENABLED)
#error SDT firmware requires the generated XilTimer BSP
#endif
#if !defined(XTIMER_IS_DEFAULT_TIMER) || (XTIMER_IS_DEFAULT_TIMER != 1)
#error SDT firmware requires the generated default sleep timer
#endif
#if !defined(__ARM_ARCH_7A__)
#error SDT firmware timer startup is verified only for Cortex-A9
#endif
#if defined(XSLEEPTIMER_IS_AXITIMER) || defined(XSLEEPTIMER_IS_TTCPS) || \
    defined(XSLEEPTIMER_IS_SCUTIMER) || defined(XTIMER_DEFAULT_TIMER_IS_MB) || \
    defined(XTIMER_DEFAULT_TIMER_IS_MB_RISCV)
#error SDT firmware requires the Cortex-A9 global timer default backend
#endif
#if (COUNTS_PER_SECOND) != (XPAR_CPU_CORE_CLOCK_FREQ_HZ / 2u)
#error SDT timer frequency must come from the generated Cortex-A9 default timer configuration
#endif

/* The first SDK sleep starts the Cortex-A9 global timer; the startup call is
 * intentionally one-shot because subsequent sleeps use the running timer. */
#define V8_TIMER_STARTUP_COUNTER_READ_LIMIT 1024u
static inline int v8_timer_startup_init(void)
{
    static int startup_attempted;
    static int startup_status;
    XTime before;
    XTime after;
    unsigned int reads;

    if (startup_attempted) {
        return startup_status;
    }
    startup_attempted = 1;

    usleep(1UL);
    XTime_GetTime(&before);
    for (reads = 0u; reads < V8_TIMER_STARTUP_COUNTER_READ_LIMIT; ++reads) {
        XTime_GetTime(&after);
        if (after != before) {
            startup_status = 0;
            return startup_status;
        }
    }
    startup_status = -1;
    return startup_status;
}
#else
#define V8_DMA_CONFIG_LOOKUP_KEY XPAR_AXIDMA_0_DEVICE_ID
#define V8_GIC_CONFIG_LOOKUP_KEY XPAR_SCUGIC_SINGLE_DEVICE_ID
#include "xtime_l.h"
static inline int v8_timer_startup_init(void)
{
    return 0;
}
#endif

#endif
