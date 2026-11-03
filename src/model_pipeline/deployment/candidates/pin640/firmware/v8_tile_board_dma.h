#ifndef V8_TILE_BOARD_DMA_H
#define V8_TILE_BOARD_DMA_H

#include <stdint.h>
#include <stddef.h>
#include "v8_tile_executor.h"
#include "v8_startup_diagnostics.h"

typedef void (*V8TileStartupDiagnosticFn)(void *opaque, uint32_t stage,
                                          uint32_t error);

typedef struct {
    uint32_t valid;
    V8TileOpcode opcode;
    uint32_t reg1;
    uint32_t sequence;
    uint32_t filter_id;
    const uint8_t *tx;
    size_t tx_bytes;
    uint8_t *rx;
    size_t response_bytes;
    size_t cache_rx_bytes;
    uint64_t started_ticks;
} V8TileDmaActive;

typedef struct {
    void *dma;
    uintptr_t control_base;
    size_t tx_capacity;
    size_t rx_capacity;
    uint32_t timeout_polls;
    uint32_t probed;
    uint32_t faulted;
    uint64_t transactions;
    void (*progress)(void *opaque);
    void *progress_opaque;
    uint32_t last_mm2s_status;
    uint32_t last_s2mm_status;
    uint32_t last_rx_bytes;
    V8TileStartupDiagnosticFn startup_diagnostic;
    void *startup_diagnostic_opaque;
    V8TileDmaActive active;
    /* Dedicated cache line; remains valid if a failed reset retains S2MM. */
    uint8_t probe_response[64] __attribute__((aligned(64)));
} V8TileBoardDma;

typedef char V8TileProbeStorageCheck[
    (offsetof(V8TileBoardDma, probe_response) % 64u == 0u &&
     sizeof(((V8TileBoardDma *)0)->probe_response) == 64u &&
     __alignof__(V8TileBoardDma) >= 64u) ? 1 : -1];

/* Contexts require 64-byte alignment and must outlive all pending DMA. Never
 * clear, free or reinitialize a faulted context to bypass the ownership lock. */

/* Call after AXI DMA initialization and before accepting TCP inference. */
int v8_tile_board_probe(V8TileBoardDma *context);

/* Transfer callback for V8TileExecutor; requires the matching tile64 bitstream. */
int v8_tile_board_transfer(void *opaque, V8TileOpcode opcode,
                           uint32_t reg1, uint32_t sequence,
                           uint32_t filter_id, const uint8_t *tx,
                           size_t tx_bytes, uint8_t *rx,
                           size_t response_bytes);

/* Optional split-transfer interface. Only one begin may be active. A failed
 * return does not necessarily release TX/RX/descriptor ownership. Reuse is
 * allowed after successful finish/cancel, or when ready() confirms quiescence.
 * On unrecoverable failure retain all storage until supported system recovery.
 * The synchronous transfer() callback has the same failure ownership rule. */
int v8_tile_board_begin(void *opaque, V8TileOpcode opcode,
                        uint32_t reg1, uint32_t sequence,
                        uint32_t filter_id, const uint8_t *tx,
                        size_t tx_bytes, uint8_t *rx,
                        size_t response_bytes);
int v8_tile_board_finish(void *opaque);
int v8_tile_board_cancel(void *opaque);
/* Returns 1 only when no transfer is active and DMA recovery is healthy. */
int v8_tile_board_ready(void *opaque);
#endif
