#ifndef V8_TILE_PROFILE_H
#define V8_TILE_PROFILE_H

#include <stdint.h>

/* All counters are cumulative for one inference after reset. Tick values use
 * the ARM global timer returned by XTime_GetTime. Logical LOAD/RUN byte
 * counts are packed TX payload sizes; DMA byte counts include TX and RX. */
typedef struct {
    uint64_t load_pack_ticks;
    uint64_t run_pack_ticks;
    uint64_t load_transfer_ticks;
    uint64_t run_transfer_ticks;
    uint64_t dma_prepare_ticks;
    uint64_t dma_poll_ticks;
    uint64_t dma_finalize_ticks;
    uint64_t load_bytes;
    uint64_t run_bytes;
    uint64_t load_calls;
    uint64_t run_calls;
    uint64_t dma_tx_bytes;
    uint64_t dma_rx_bytes;
    uint64_t dma_calls;
    uint64_t response_parse_ticks;
    uint64_t conv_requant_ticks;
} V8TileProfile;

extern V8TileProfile v8_tile_profile;

/* The caller resets once per inference. This is available only in builds
 * that include v8_tile_profile.c; profiling call sites compile away unless
 * both V8_XILINX_BSP and V8_TILE_PROFILE are defined. */
void v8_tile_profile_reset(void);

#if defined(V8_XILINX_BSP) && defined(V8_TILE_PROFILE)
#include "v8_sdt_compat.h"
#define V8_TILE_PROFILE_DECLARE(name) XTime name
#define V8_TILE_PROFILE_START(name) XTime_GetTime(&(name))
#define V8_TILE_PROFILE_STOP_ADD(field, name) \
    do { \
        XTime v8_tile_profile_end_; \
        XTime_GetTime(&v8_tile_profile_end_); \
        v8_tile_profile.field += (uint64_t)(v8_tile_profile_end_ - (name)); \
    } while (0)
#define V8_TILE_PROFILE_ADD(field, amount) \
    do { v8_tile_profile.field += (uint64_t)(amount); } while (0)
#else
#define V8_TILE_PROFILE_DECLARE(name)
#define V8_TILE_PROFILE_START(name) ((void)0)
#define V8_TILE_PROFILE_STOP_ADD(field, name) ((void)0)
#define V8_TILE_PROFILE_ADD(field, amount) ((void)0)
#endif

#endif
