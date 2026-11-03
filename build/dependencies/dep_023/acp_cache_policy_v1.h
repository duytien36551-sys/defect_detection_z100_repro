#ifndef ZN_ACP_CACHE_POLICY_V1_H
#define ZN_ACP_CACHE_POLICY_V1_H

#include <stddef.h>
#include <stdint.h>

#define ZN_ACP_BOOT_MAGIC_V1 UINT32_C(0x5A414350)
#define ZN_ACP_BOOT_PROTOCOL_VERSION_V1 UINT32_C(1)
#define ZN_ACP_BOOT_MODE_WORD_V1(mode) \
    ((ZN_ACP_BOOT_PROTOCOL_VERSION_V1 << 16) | (uint32_t)(mode))

enum {
    ZN_ACP_POLICY_MODE_FULL_V1 = 0,
    ZN_ACP_POLICY_MODE_QUALIFIED_SCOPED_V1 = 1,
    ZN_ACP_POLICY_MODE_SMOKE_ONLY_V1 = 2
};

enum {
    ZN_ACP_POLICY_OK_V1 = 0,
    ZN_ACP_POLICY_ERR_ARGUMENT_V1 = -1,
    ZN_ACP_POLICY_ERR_LIFECYCLE_V1 = -2
};

typedef struct {
    uint32_t receipt_lo;
    uint32_t receipt_hi;
    uint32_t requested_mode;
    uint32_t consumed;
} ZnAcpBootReceiptDiagnosticV1;

/* Assembly entry and exact READY breakpoint symbol for the paired downloader. */
int zn_acp_boot_handoff_v1(void);
void zn_acp_boot_handoff_ready_v1(void);

/* AAPCS receiver reached by a tail branch from the assembly handoff. */
int zn_acp_boot_receiver_v1(uint32_t magic, uint32_t protocol_mode,
                            uint32_t receipt_lo, uint32_t receipt_hi);

/* Strong platform implementation must return exactly 1 only when live state passes. */
int z100_acp_live_coherence_state_check_v1(void);

/* The adapter seals once before publishing cache callbacks. */
int zn_acp_cache_policy_seal_once_v1(void);

/* Returns 1 only for a complete allowlisted range in sealed SCOPED mode. */
int zn_acp_cache_policy_should_skip_v1(uintptr_t address, size_t bytes);

/* Read-only effective mode. Unseen, invalid, or rejected handoff is FULL. */
int zn_acp_cache_policy_mode_v1(void);

/* Audit only: consumed receipt values never authorize or re-arm a policy. */
int zn_acp_boot_receipt_diagnostic_v1(ZnAcpBootReceiptDiagnosticV1 *out);

#endif
