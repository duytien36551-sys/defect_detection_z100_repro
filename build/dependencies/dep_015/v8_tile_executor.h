#ifndef V8_TILE_EXECUTOR_H
#define V8_TILE_EXECUTOR_H

#include <stddef.h>
#include <stdint.h>
#include "v8_tile_abi.h"

#ifndef V8_TILE_RUN_CACHE
#define V8_TILE_RUN_CACHE 0
#endif

/* A transfer owns the DMA transaction. RX must contain exactly response_bytes
 * on success. A failure invalidates any cached filter identity in the caller.
 * A failed backend may retain buffer ownership until recovery is confirmed. */
typedef int (*V8TileTransferFn)(void *opaque, V8TileOpcode opcode,
                                uint32_t reg1, uint32_t sequence,
                                uint32_t filter_id, const uint8_t *tx,
                                size_t tx_bytes, uint8_t *rx,
                                size_t response_bytes);

/* Optional split callbacks. Retain TX/RX/request storage through completion.
 * Failure does not itself release ownership; require successful completion,
 * successful cancellation, or a positive ready() gate before reuse. */
typedef int (*V8TileBeginFn)(void *opaque, V8TileOpcode opcode,
                              uint32_t reg1, uint32_t sequence,
                              uint32_t filter_id, const uint8_t *tx,
                              size_t tx_bytes, uint8_t *rx,
                              size_t response_bytes);
typedef int (*V8TileFinishFn)(void *opaque);
typedef int (*V8TileCancelFn)(void *opaque);
/* Returns nonzero only when DMA buffers may be modified. Backends that can
 * retain ownership after failure must supply this gate. Do not clear their
 * context or reuse buffers while it returns zero. */
typedef int (*V8TileReadyFn)(void *opaque);

typedef struct {
    V8TileTransferFn transfer;
    void *opaque;
    uint8_t *tx;
    size_t tx_capacity;
    uint8_t *rx;
    size_t rx_capacity;
    uint32_t sequence;
    uint32_t filter_serial;
    uint64_t loads;
    uint64_t runs;
    V8TileBeginFn begin;
    V8TileFinishFn finish;
    V8TileCancelFn cancel;
    uint8_t *tx_next;
    size_t tx_next_capacity;
    V8TileReadyFn ready;
    /* Optional per-convolution packed RUN cache. Set to NULL/0 to disable. */
    uint8_t *run_cache;
    size_t run_cache_capacity;
} V8TileExecutor;

/* V8Runtime.conv callback for the tile64 candidate. The physical DMA
 * transfer implementation is supplied separately by the board program. */
int v8_tile_execute_conv(void *opaque, const V8Node *output,
                         const V8Node *input, const int8_t *activations,
                         const int8_t *weights, const uint8_t *bias_le,
                         int32_t *raw);
#endif
