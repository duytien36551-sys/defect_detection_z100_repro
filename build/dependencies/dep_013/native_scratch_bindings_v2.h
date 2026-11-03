
#ifndef Z100_NATIVE_SCRATCH_BINDINGS_V2_H
#define Z100_NATIVE_SCRATCH_BINDINGS_V2_H
#include "native_graph_conv_bridge_v2.h"
typedef struct {
    uint32_t job_base, token_base, tag_base;
    uint32_t load_timeout_cycles, parameter_timeout_cycles;
    uint32_t write_timeout_cycles, preaccept_timeout_cycles;
    uint8_t first_bank;
} ZnNativeScratchIdsV2;
/* 0 bound; 1 direct/nonConv; -1 invalid. Does not reserve scratch, convert pixels,
 * clean caches, start MMIO or ACK graph requests. Rejection leaves out intact. */
int zn_native_scratch_binding_v2(const ZnRequest *,const ZnNativeScratchIdsV2 *,
    const ZnNativeGraphScratchLeaseV2 *,ZnNativeGraphConvBindingV2 *);
#endif
