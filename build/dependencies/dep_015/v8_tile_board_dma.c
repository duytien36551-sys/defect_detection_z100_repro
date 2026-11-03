#include "v8_tile_board_dma.h"
#include "v8_tile_profile.h"
#include <limits.h>

#ifdef V8_XILINX_BSP
#include "xaxidma.h"
#include "xaxidma_hw.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "v8_sdt_compat.h"

#define TILE_TIMEOUT_DEFAULT 10000000u
#define TILE_TIMEOUT_SECONDS 5u

#ifndef COUNTS_PER_SECOND
#error "COUNTS_PER_SECOND must be supplied by the Xilinx BSP"
#endif

static uint64_t board_ticks(void)
{
    XTime ticks;
    XTime_GetTime(&ticks);
    return (uint64_t)ticks;
}

static int transfer_timed_out(const V8TileDmaActive *active)
{
    uint64_t timeout_ticks = (uint64_t)COUNTS_PER_SECOND *
                             TILE_TIMEOUT_SECONDS;
    return board_ticks() - active->started_ticks >= timeout_ticks;
}

static void startup_diagnostic(V8TileBoardDma *c, uint32_t stage,
                               uint32_t error)
{
    if (c && c->startup_diagnostic)
        c->startup_diagnostic(c->startup_diagnostic_opaque, stage, error);
}

static uint32_t read_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int dma_error(XAxiDma *dma)
{
    uint32_t tx = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_TX_OFFSET,
                                  XAXIDMA_SR_OFFSET);
    uint32_t rx = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                                  XAXIDMA_SR_OFFSET);
    return ((tx | rx) & XAXIDMA_ERR_ALL_MASK) != 0u;
}

static int recover(V8TileBoardDma *c)
{
    XAxiDma *dma = (XAxiDma *)c->dma;
    uint32_t polls = c->timeout_polls ? c->timeout_polls : TILE_TIMEOUT_DEFAULT;
    c->last_mm2s_status = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_TX_OFFSET,
                                           XAXIDMA_SR_OFFSET);
    c->last_s2mm_status = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                                           XAXIDMA_SR_OFFSET);
    c->last_rx_bytes = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                                       XAXIDMA_BUFFLEN_OFFSET);
    c->probed = 0;
    Xil_Out32(c->control_base, V8_TILE_R0_ABORT);
    if (!(Xil_In32(c->control_base) & V8_TILE_R0_ABORT)) {
        c->faulted = 1;
        return -1;
    }
    XAxiDma_Reset(dma);
    while (polls--) {
        if (XAxiDma_ResetIsDone(dma) && !dma_error(dma)) {
            uint32_t tx = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_TX_OFFSET,
                                           XAXIDMA_SR_OFFSET);
            uint32_t rx = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                                           XAXIDMA_SR_OFFSET);
            if ((tx & XAXIDMA_HALTED_MASK) &&
                (rx & XAXIDMA_HALTED_MASK)) {
                Xil_Out32(c->control_base, 0);
                c->faulted = 0;
                c->active.valid = 0;
                return -1;
            }
        }
    }
    c->faulted = 1;
    return -1;
}

static int transfer_begin(V8TileBoardDma *c, V8TileOpcode opcode,
                          uint32_t reg1, uint32_t sequence,
                          uint32_t filter_id, const uint8_t *tx,
                          size_t tx_bytes, uint8_t *rx,
                          size_t response_bytes)
{
    XAxiDma *dma;
    uint32_t control, cache_tx, cache_rx;
    uintptr_t tx_start, rx_start;
    V8_TILE_PROFILE_DECLARE(profile_start);
    if (!c || !c->dma || !c->control_base || !rx ||
        c->faulted || c->active.valid || (opcode != V8_TILE_OP_PROBE &&
                       opcode != V8_TILE_OP_LOAD && opcode != V8_TILE_OP_RUN) ||
        (opcode == V8_TILE_OP_PROBE && (tx_bytes || reg1)) ||
        (opcode != V8_TILE_OP_PROBE && (!tx || !tx_bytes)) ||
        tx_bytes > V8_TILE_DMA_MAX_BYTES ||
        response_bytes < 20u || response_bytes > V8_TILE_MAX_RESPONSE_BYTES ||
        (response_bytes & 3u) || (tx_bytes & 3u) ||
        ((uintptr_t)rx & 63u) ||
        (tx_bytes && ((uintptr_t)tx & 63u))) return -1;
    tx_start = (uintptr_t)tx;
    rx_start = (uintptr_t)rx;
    cache_tx = ((uint32_t)tx_bytes + 63u) & ~63u;
    cache_rx = ((uint32_t)response_bytes + 63u) & ~63u;
    if (cache_tx > c->tx_capacity || cache_rx > c->rx_capacity)
        return -1;
    if (rx_start > UINTPTR_MAX - cache_rx) return -1;
    if (tx_bytes && (tx_start > UINTPTR_MAX - cache_tx ||
                     (tx_start < rx_start + cache_rx &&
                      rx_start < tx_start + cache_tx))) return -1;
    dma = (XAxiDma *)c->dma;
    if (XAxiDma_HasSg(dma)) return -1;
    if (v8_tile_control_word(opcode, 0, 1, &control) != V8_TILE_OK)
        return -1;

    c->active.opcode = opcode;
    c->active.reg1 = reg1;
    c->active.sequence = sequence;
    c->active.filter_id = filter_id;
    c->active.tx = tx;
    c->active.tx_bytes = tx_bytes;
    c->active.rx = rx;
    c->active.response_bytes = response_bytes;
    c->active.cache_rx_bytes = cache_rx;
    c->active.valid = 1u;

    V8_TILE_PROFILE_ADD(dma_calls, 1u);
    V8_TILE_PROFILE_ADD(dma_tx_bytes, tx_bytes);
    V8_TILE_PROFILE_ADD(dma_rx_bytes, response_bytes);
    c->active.started_ticks = board_ticks();
    V8_TILE_PROFILE_START(profile_start);
    Xil_Out32(c->control_base, 0);
    Xil_Out32(c->control_base + 4u, reg1);
    Xil_Out32(c->control_base + 8u, sequence);
    Xil_Out32(c->control_base + 12u, filter_id);
    if (tx_bytes) Xil_DCacheFlushRange((INTPTR)tx, cache_tx);
    Xil_DCacheInvalidateRange((INTPTR)rx, cache_rx);
    if (XAxiDma_SimpleTransfer(dma, (UINTPTR)rx,
                               (uint32_t)response_bytes,
                               XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS) {
        V8_TILE_PROFILE_STOP_ADD(dma_prepare_ticks, profile_start);
        return recover(c);
    }
    Xil_Out32(c->control_base, control);
    if (tx_bytes && XAxiDma_SimpleTransfer(dma, (UINTPTR)tx,
                                           (uint32_t)tx_bytes,
                                           XAXIDMA_DMA_TO_DEVICE) != XST_SUCCESS) {
        V8_TILE_PROFILE_STOP_ADD(dma_prepare_ticks, profile_start);
        return recover(c);
    }
    V8_TILE_PROFILE_STOP_ADD(dma_prepare_ticks, profile_start);
    return 0;
}

static int transfer_finish(V8TileBoardDma *c)
{
    XAxiDma *dma;
    V8TileDmaActive *active;
    uint32_t polls, n;
    int done = 0;
    V8_TILE_PROFILE_DECLARE(profile_start);
    if (!c || !c->dma || c->faulted || !c->active.valid) return -1;
    dma = (XAxiDma *)c->dma;
    active = &c->active;
    polls = c->timeout_polls ? c->timeout_polls : TILE_TIMEOUT_DEFAULT;
    V8_TILE_PROFILE_START(profile_start);
    if (c->progress) c->progress(c->progress_opaque);
    for (n = 0; n < polls; ++n) {
        if ((n & 0xfffu) == 0u && transfer_timed_out(active)) {
            V8_TILE_PROFILE_STOP_ADD(dma_poll_ticks, profile_start);
            return recover(c);
        }
        if (dma_error(dma)) {
            V8_TILE_PROFILE_STOP_ADD(dma_poll_ticks, profile_start);
            return recover(c);
        }
        if (!XAxiDma_Busy(dma, XAXIDMA_DEVICE_TO_DMA) &&
            (!active->tx_bytes ||
             !XAxiDma_Busy(dma, XAXIDMA_DMA_TO_DEVICE))) {
            done = 1;
            break;
        }
        if (c->progress && n != 0u && (n & 0xfffu) == 0u)
            c->progress(c->progress_opaque);
    }
    if (!done || dma_error(dma) ||
        XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                        XAXIDMA_BUFFLEN_OFFSET) != active->response_bytes ||
        transfer_timed_out(active)) {
        V8_TILE_PROFILE_STOP_ADD(dma_poll_ticks, profile_start);
        return recover(c);
    }
    V8_TILE_PROFILE_STOP_ADD(dma_poll_ticks, profile_start);

    V8_TILE_PROFILE_START(profile_start);
    Xil_DCacheInvalidateRange((INTPTR)active->rx,
                              active->cache_rx_bytes);
    if (read_le32(active->rx) != V8_TILE_MAGIC ||
        read_le32(active->rx + 4u) != active->sequence ||
        read_le32(active->rx + 8u) != active->filter_id ||
        read_le32(active->rx + 12u) != active->reg1 ||
        read_le32(active->rx + active->response_bytes - 4u) != 0u) {
        V8_TILE_PROFILE_STOP_ADD(dma_finalize_ticks, profile_start);
        return recover(c);
    }
    c->transactions++;
    active->valid = 0u;
    V8_TILE_PROFILE_STOP_ADD(dma_finalize_ticks, profile_start);
    return 0;
}

int v8_tile_board_probe(V8TileBoardDma *c)
{
    uint8_t *response;
    XAxiDma *dma;
    uint32_t polls;
    int reset_done = 0;
    if (!c || !c->dma || c->faulted || c->active.valid) return -1;
    response = c->probe_response;
    dma = (XAxiDma *)c->dma;
    if (XAxiDma_HasSg(dma)) return -1;
    c->probed = 0;
    startup_diagnostic(c, V8_STARTUP_DMA_RESET, V8_STARTUP_ERROR_NONE);
    Xil_Out32(c->control_base, V8_TILE_R0_ABORT);
    if (!(Xil_In32(c->control_base) & V8_TILE_R0_ABORT)) {
        c->faulted = 1;
        startup_diagnostic(c, V8_STARTUP_DMA_RESET,
                           V8_STARTUP_ERROR_ABORT_CONTROL);
        return -1;
    }
    XAxiDma_Reset(dma);
    polls = c->timeout_polls ? c->timeout_polls : TILE_TIMEOUT_DEFAULT;
    while (polls--) {
        if (XAxiDma_ResetIsDone(dma) && !dma_error(dma)) {
            uint32_t tx = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_TX_OFFSET,
                                           XAXIDMA_SR_OFFSET);
            uint32_t rx = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                                           XAXIDMA_SR_OFFSET);
            if ((tx & XAXIDMA_HALTED_MASK) &&
                (rx & XAXIDMA_HALTED_MASK)) {
                reset_done = 1;
                break;
            }
        }
    }
    if (!reset_done) {
        c->faulted = 1;
        startup_diagnostic(c, V8_STARTUP_DMA_RESET,
                           V8_STARTUP_ERROR_DMA_RESET);
        return -1;
    }
    Xil_Out32(c->control_base, 0);
    startup_diagnostic(c, V8_STARTUP_PL_PROBE, V8_STARTUP_ERROR_NONE);
    if (v8_tile_board_transfer(c, V8_TILE_OP_PROBE, 0, 0, 0,
                              0, 0, response, 20u)) {
        startup_diagnostic(c, V8_STARTUP_PL_PROBE,
                           V8_STARTUP_ERROR_PL_PROBE);
        return -1;
    }
    c->probed = 1;
    return 0;
}

int v8_tile_board_begin(void *opaque, V8TileOpcode opcode,
                        uint32_t reg1, uint32_t sequence,
                        uint32_t filter_id, const uint8_t *tx,
                        size_t tx_bytes, uint8_t *rx,
                        size_t response_bytes)
{
    V8TileBoardDma *c = (V8TileBoardDma *)opaque;
    if (!c || c->faulted) return -1;
    if (!c->probed && opcode != V8_TILE_OP_PROBE &&
        v8_tile_board_probe(c)) return -1;
    return transfer_begin(c, opcode, reg1, sequence, filter_id,
                          tx, tx_bytes, rx, response_bytes);
}

int v8_tile_board_finish(void *opaque)
{
    return transfer_finish((V8TileBoardDma *)opaque);
}

int v8_tile_board_cancel(void *opaque)
{
    V8TileBoardDma *c = (V8TileBoardDma *)opaque;
    if (!c || !c->dma || c->faulted || !c->active.valid) return -1;
    (void)recover(c);
    return c->faulted ? -1 : 0;
}

int v8_tile_board_ready(void *opaque)
{
    const V8TileBoardDma *c = (const V8TileBoardDma *)opaque;
    return c && !c->faulted && !c->active.valid;
}

int v8_tile_board_transfer(void *opaque, V8TileOpcode opcode,
                           uint32_t reg1, uint32_t sequence,
                           uint32_t filter_id, const uint8_t *tx,
                           size_t tx_bytes, uint8_t *rx,
                           size_t response_bytes)
{
    if (v8_tile_board_begin(opaque, opcode, reg1, sequence, filter_id,
                            tx, tx_bytes, rx, response_bytes)) return -1;
    return v8_tile_board_finish(opaque);
}
#else
int v8_tile_board_probe(V8TileBoardDma *context)
{
    (void)context;
    return -1;
}
int v8_tile_board_transfer(void *opaque, V8TileOpcode opcode,
                           uint32_t reg1, uint32_t sequence,
                           uint32_t filter_id, const uint8_t *tx,
                           size_t tx_bytes, uint8_t *rx,
                           size_t response_bytes)
{
    (void)opaque; (void)opcode; (void)reg1; (void)sequence;
    (void)filter_id; (void)tx; (void)tx_bytes;
    (void)rx; (void)response_bytes;
    return -1;
}
int v8_tile_board_begin(void *opaque, V8TileOpcode opcode,
                        uint32_t reg1, uint32_t sequence,
                        uint32_t filter_id, const uint8_t *tx,
                        size_t tx_bytes, uint8_t *rx,
                        size_t response_bytes)
{
    (void)opaque; (void)opcode; (void)reg1; (void)sequence;
    (void)filter_id; (void)tx; (void)tx_bytes;
    (void)rx; (void)response_bytes;
    return -1;
}
int v8_tile_board_finish(void *opaque)
{
    (void)opaque;
    return -1;
}
int v8_tile_board_cancel(void *opaque)
{
    (void)opaque;
    return -1;
}
int v8_tile_board_ready(void *opaque)
{
    (void)opaque;
    return 0;
}
#endif
