
#ifndef Z100_NATIVE_DIRECT_BINDINGS_V2_H
#define Z100_NATIVE_DIRECT_BINDINGS_V2_H
#include "native_graph_conv_bridge_v2.h"
typedef struct {
    uint32_t job_base, token_base, tag_base;
    uint32_t load_timeout_cycles, parameter_timeout_cycles;
    uint32_t write_timeout_cycles, preaccept_timeout_cycles;
    uint8_t first_bank;
} ZnNativeDirectIdsV2;
/* 0 binds a direct materialized Conv; 1 explicitly defers views/non-Conv.
 * The source lease is caller supplied and must match the exact graph read.
 * This function does not acquire leases, convert data, clean caches or issue IO.
 * Every rejection leaves out unchanged. */
int zn_native_direct_binding_v2(const ZnRequest *,
    const ZnNativeDirectIdsV2 *, const ZnNativeGraphScratchLeaseV2 *,
    ZnNativeGraphConvBindingV2 *);
#endif
