#ifndef Z100_NATIVE_RUNTIME_MAPS_V1_H
#define Z100_NATIVE_RUNTIME_MAPS_V1_H

#include "native_arena_owner_v1.h"
#include "native_platform_memory_v1.h"
#include "native_view_materialize_v1.h"

/* Borrow an exclusively reserved, coherent CPU mapping of the frozen arena.
 * These functions validate software leases and offsets only. They neither
 * reserve DDR nor perform cache maintenance, publish output, or ACK requests.
 * On rejection the output object is unchanged. Caller serializes the owner,
 * dispatch and mapping and keeps them immutable during every call. The output
 * object must not alias those metadata objects. Returned pointers do not grant
 * CPU write permission to a read lease or bypass cache ownership.
 * A read is returned in original graph read order, with the producer's actual
 * shape, not the consumer's shape (important for views/concatenation).
 */
typedef struct ZnNativeRuntimeTensorMapV1 {
    uint32_t physical_address;
    uint8_t *cpu_address;
    ZnNativeViewSourceV1 view;
} ZnNativeRuntimeTensorMapV1;

int zn_native_runtime_map_read_v1(
    const ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request, uint8_t read_index,
    const ZnNativePlatformMappedSpanV1 *arena,
    ZnNativeRuntimeTensorMapV1 *out);

int zn_native_runtime_map_destination_v1(
    const ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request, const ZnNativePlatformMappedSpanV1 *arena,
    ZnNativeRuntimeTensorMapV1 *out);

#endif
