#include "native_board_entry_v2.h"

#include "acp_cache_policy_v1.h"
#include "xil_cache.h"

/* CPU-owned diagnostics only. Nothing reads these words to arm a policy.
 * Full cache-line allocation and explicit publication make debugger reads
 * meaningful at the observation breakpoint. */
volatile uint32_t zn_acp_boot_publication_v1[16]
    __attribute__((aligned(64)));

__attribute__((noinline, used)) void zn_acp_boot_observed_v1(void)
{
    __asm__ volatile("nop" ::: "memory");
}

__attribute__((noinline, used)) void zn_acp_smoke_finished_v1(void)
{
    __asm__ volatile("nop" ::: "memory");
}

static void acp_publish(uint32_t stage, int code)
{
    ZnAcpBootReceiptDiagnosticV1 receipt;
    unsigned i;
    for (i = 0; i < 16u; ++i) zn_acp_boot_publication_v1[i] = 0u;
    if (zn_acp_boot_receipt_diagnostic_v1(&receipt) != 0) {
        for (;;) __asm__ volatile("wfi" ::: "memory");
    }
    zn_acp_boot_publication_v1[0] = UINT32_C(0x41504344);
    zn_acp_boot_publication_v1[1] = 1u;
    zn_acp_boot_publication_v1[2] = stage;
    zn_acp_boot_publication_v1[3] = (uint32_t)code;
    zn_acp_boot_publication_v1[4] = receipt.receipt_lo;
    zn_acp_boot_publication_v1[5] = receipt.receipt_hi;
    zn_acp_boot_publication_v1[6] = receipt.requested_mode;
    zn_acp_boot_publication_v1[7] = receipt.consumed;
    zn_acp_boot_publication_v1[8] = (uint32_t)zn_acp_cache_policy_mode_v1();
    Xil_DCacheFlushRange((INTPTR)(uintptr_t)zn_acp_boot_publication_v1,
                         sizeof zn_acp_boot_publication_v1);
    __asm__ volatile("dsb sy" ::: "memory");
}


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
    int code=zn_acp_boot_handoff_v1();
    acp_publish(1u, code);
    zn_acp_boot_observed_v1();
    if (code != 0) {
        for (;;) __asm__ volatile("wfi" ::: "memory");
    }
    if (zn_acp_cache_policy_mode_v1() == ZN_ACP_POLICY_MODE_SMOKE_ONLY_V1) {
        for (;;) __asm__ volatile("wfi" ::: "memory");
    }
    code=zn_native_board_start_v2(&zn_native_board_configuration_v2);
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
