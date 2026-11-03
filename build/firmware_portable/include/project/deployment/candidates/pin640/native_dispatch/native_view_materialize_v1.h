#ifndef Z100_NATIVE_VIEW_MATERIALIZE_V1_H
#define Z100_NATIVE_VIEW_MATERIALIZE_V1_H
#include "native_dispatch.h"
#include <stddef.h>

/* Portable bring-up/fallback conversion in z100-native-stream/1 word order.
 * This is actual pixel computation, not a graph/lease/publication backend.
 * The caller holds all source leases, owns separate output scratch, makes CPU
 * source reads coherent, and cleans output before passing it to PL. Immutable
 * descriptors/tables and sources must remain valid throughout the call. */
typedef struct {
    const uint8_t *data;
    size_t bytes;
    uint32_t epoch;
    ZnRef ref;
    uint16_t channels, height, width;
} ZnNativeViewSourceV1;

typedef struct {
    ZnRef expected_ref;
    uint16_t source_channel, lut_index;
    uint8_t source_index, divisor_h, divisor_w;
} ZnNativeViewChannelV1;

/* Source and output byte counts must exactly match padded native shapes.
 * LUTs map signed indices [-128..127] stored in that ascending order.
 * Returns 0 on success, -1 on invalid input. Invalid calls leave output intact.
 * Max7sources/1024channels/640x640; nearest divisors1/2/4. No IO, allocation,
 * cache maintenance, hardware publication, model admission, or dispatch ACK. */
int zn_native_view_materialize_v1(
    uint32_t epoch, const ZnNativeViewSourceV1 *sources, uint8_t source_count,
    const ZnNativeViewChannelV1 *channels, uint16_t output_channels,
    uint16_t output_height, uint16_t output_width,
    const uint8_t *tables, uint16_t table_count,
    uint8_t *output, size_t output_bytes);
#endif
