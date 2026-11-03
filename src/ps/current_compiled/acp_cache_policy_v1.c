#include "acp_cache_policy_v1.h"

#include <limits.h>

enum {
    POLICY_UNSEEN = 0,
    POLICY_RECEIVED = 1,
    POLICY_SEALED = 2,
    POLICY_DUPLICATE = 3
};

typedef struct {
    uint32_t begin;
    uint32_t end;
} PolicyRangeV1;

static uint8_t policy_state;
static uint8_t policy_mode;
static ZnAcpBootReceiptDiagnosticV1 receipt_diagnostic;

static const PolicyRangeV1 accelerator_ranges[] = {
    {UINT32_C(0x10000000), UINT32_C(0x104F6000)},
    {UINT32_C(0x20000000), UINT32_C(0x202FA500)},
    {UINT32_C(0x21000000), UINT32_C(0x210015C0)},
    {UINT32_C(0x22000000), UINT32_C(0x2212C000)},
    {UINT32_C(0x24000000), UINT32_C(0x24095B80)}
};

#if defined(__GNUC__) || defined(__clang__)
__attribute__((weak))
#endif
int z100_acp_live_coherence_state_check_v1(void)
{
    return 0;
}

static int valid_protocol_mode(uint32_t protocol_mode, uint32_t *mode)
{
    uint32_t requested = protocol_mode & UINT32_C(0xFFFF);
    uint32_t expected = ZN_ACP_BOOT_MODE_WORD_V1(requested);

    if (protocol_mode != expected ||
        (requested != ZN_ACP_POLICY_MODE_FULL_V1 &&
         requested != ZN_ACP_POLICY_MODE_QUALIFIED_SCOPED_V1 &&
         requested != ZN_ACP_POLICY_MODE_SMOKE_ONLY_V1))
        return 0;
    *mode = requested;
    return 1;
}

int zn_acp_boot_receiver_v1(uint32_t magic, uint32_t protocol_mode,
                            uint32_t receipt_lo, uint32_t receipt_hi)
{
    uint32_t requested_mode;
    uint64_t receipt = ((uint64_t)receipt_hi << 32) | receipt_lo;
    int live_status;

    if (policy_state != POLICY_UNSEEN) {
        if (policy_state != POLICY_SEALED) {
            policy_mode = ZN_ACP_POLICY_MODE_FULL_V1;
            policy_state = POLICY_DUPLICATE;
        }
        return ZN_ACP_POLICY_ERR_LIFECYCLE_V1;
    }

    policy_state = POLICY_RECEIVED;
    policy_mode = ZN_ACP_POLICY_MODE_FULL_V1;

    if (magic != ZN_ACP_BOOT_MAGIC_V1 || receipt == 0 ||
        !valid_protocol_mode(protocol_mode, &requested_mode))
        return ZN_ACP_POLICY_OK_V1;

    receipt_diagnostic.receipt_lo = receipt_lo;
    receipt_diagnostic.receipt_hi = receipt_hi;
    receipt_diagnostic.requested_mode = requested_mode;
    receipt_diagnostic.consumed = 1u;

    if (requested_mode == ZN_ACP_POLICY_MODE_FULL_V1)
        return ZN_ACP_POLICY_OK_V1;

    live_status = z100_acp_live_coherence_state_check_v1();
    if (policy_state != POLICY_RECEIVED)
        return ZN_ACP_POLICY_ERR_LIFECYCLE_V1;
    if (live_status != 1)
        return ZN_ACP_POLICY_OK_V1;

    policy_mode = (uint8_t)requested_mode;
    return ZN_ACP_POLICY_OK_V1;
}

int zn_acp_cache_policy_seal_once_v1(void)
{
    if (policy_state == POLICY_SEALED)
        return ZN_ACP_POLICY_ERR_LIFECYCLE_V1;

    if (policy_state == POLICY_UNSEEN)
        policy_mode = ZN_ACP_POLICY_MODE_FULL_V1;
    policy_state = POLICY_SEALED;
    return ZN_ACP_POLICY_OK_V1;
}

static int valid_cache_range(uintptr_t address, size_t bytes)
{
    return address != 0u && bytes != 0u && (address & 31u) == 0u &&
           (bytes & 31u) == 0u && address <= UINT32_MAX &&
           (uintmax_t)bytes <= (uintmax_t)UINT32_MAX - (uintmax_t)address;
}

int zn_acp_cache_policy_should_skip_v1(uintptr_t address, size_t bytes)
{
    uint64_t end;
    size_t i;

    if (policy_state != POLICY_SEALED ||
        policy_mode != ZN_ACP_POLICY_MODE_QUALIFIED_SCOPED_V1 ||
        !valid_cache_range(address, bytes))
        return 0;

    end = (uint64_t)address + (uint64_t)bytes;
    for (i = 0; i < sizeof accelerator_ranges / sizeof accelerator_ranges[0]; ++i) {
        if (address >= accelerator_ranges[i].begin &&
            end <= accelerator_ranges[i].end)
            return 1;
    }
    return 0;
}

int zn_acp_cache_policy_mode_v1(void)
{
    return policy_mode;
}

int zn_acp_boot_receipt_diagnostic_v1(ZnAcpBootReceiptDiagnosticV1 *out)
{
    if (!out)
        return ZN_ACP_POLICY_ERR_ARGUMENT_V1;
    *out = receipt_diagnostic;
    return ZN_ACP_POLICY_OK_V1;
}
