#include "native_board_entry_v1.h"

#if !defined(SDT) || !defined(__ARM_ARCH_7A__)
#error This standalone main is for Cortex-A9 SDT only
#endif

/* A debugger may read this after failure. Never reset/clear retained graph,
 * reservation or SDK state; external recovery owns physical quiescence. */
static volatile int zn_native_board_main_stop_code_v1;
static void stop(int code)
{
    zn_native_board_main_stop_code_v1=code;
    for (;;) __asm__ volatile("wfi" ::: "memory");
}

int main(void)
{
    int code=zn_native_board_start_v1(&zn_native_board_configuration_v1);
    if (code!=ZN_NATIVE_BOARD_V1_LISTENING) stop(code);
    for (;;) {
        code=zn_native_board_step_v1();
        if (code==ZN_NATIVE_BOARD_V1_DELIVERED) {
            const ZnNativeBoardDiagnosticsV1 *d=zn_native_board_diagnostics_v1();
            if (d->epoch==UINT32_MAX) stop(ZN_NATIVE_BOARD_V1_ARGUMENT);
            code=zn_native_board_rearm_v1(d->epoch+1u);
            if (code!=ZN_NATIVE_BOARD_V1_LISTENING) stop(code);
        } else if (code!=ZN_NATIVE_BOARD_V1_LISTENING) stop(code);
    }
}
