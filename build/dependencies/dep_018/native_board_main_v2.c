#include "native_board_entry_v2.h"

#if !defined(SDT) || !defined(__ARM_ARCH_7A__)
#error This standalone main is for Cortex-A9 SDT only
#endif

/* A debugger may read this after failure. Never reset/clear retained graph,
 * reservation or SDK state; external recovery owns physical quiescence. */
static volatile int zn_native_board_main_stop_code_v2;
static void stop(int code)
{
    zn_native_board_main_stop_code_v2=code;
    for (;;) {
        int drain=zn_native_board_fault_poll_v2();
        /* Keep progressing active physical drain. Once quiet or unprovable,
         * sleep for the next IRQ/debugger inspection; never reset or rearm. */
        if(drain!=1) __asm__ volatile("wfi" ::: "memory");
    }
}

int main(void)
{
    int code=zn_native_board_start_v2(&zn_native_board_configuration_v2);
    if (code!=ZN_NATIVE_BOARD_V2_LISTENING) stop(code);
    for (;;) {
        code=zn_native_board_step_v2();
        if (code==ZN_NATIVE_BOARD_V2_DELIVERED) {
            const ZnNativeBoardDiagnosticsV2 *d=zn_native_board_diagnostics_v2();
            if (d->epoch==UINT32_MAX) stop(ZN_NATIVE_BOARD_V2_ARGUMENT);
            code=zn_native_board_rearm_v2(d->epoch+1u);
            if (code!=ZN_NATIVE_BOARD_V2_LISTENING) stop(code);
        } else if (code!=ZN_NATIVE_BOARD_V2_LISTENING) stop(code);
    }
}
