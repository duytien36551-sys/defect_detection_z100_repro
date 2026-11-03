#include "v8_dma.h"
#include <stddef.h>
#include <limits.h>

#ifdef V8_XILINX_BSP
#include "xaxidma.h"
#include "xaxidma_hw.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "v8_sdt_compat.h"

#ifndef COUNTS_PER_SECOND
#define COUNTS_PER_SECOND 1000000u
#endif
#define V8_DMA_TIMEOUT_SECONDS 5u

static uint32_t poll_limit(const V8DmaContext *d)
{
    return d->timeout_polls ? d->timeout_polls : 1000000u;
}

static uint64_t read_ticks(void)
{
    XTime now;
    XTime_GetTime(&now);
    return (uint64_t)now;
}

static int dma_has_error(XAxiDma *dma)
{
    uint32_t mm2s = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_TX_OFFSET,
                                    XAXIDMA_SR_OFFSET);
    uint32_t s2mm = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                                    XAXIDMA_SR_OFFSET);
    return ((mm2s | s2mm) & XAXIDMA_ERR_ALL_MASK) != 0u;
}

static int dma_channels_halted(XAxiDma *dma)
{
    uint32_t mm2s = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_TX_OFFSET,
                                    XAXIDMA_SR_OFFSET);
    uint32_t s2mm = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                                    XAXIDMA_SR_OFFSET);
    return (mm2s & XAXIDMA_HALTED_MASK) != 0u &&
           (s2mm & XAXIDMA_HALTED_MASK) != 0u;
}

static int dma_range(const void *pointer, uint64_t bytes,
                     uintptr_t *start, uintptr_t *end)
{
    uintptr_t first = (uintptr_t)pointer;
    if (!pointer || bytes > (uint64_t)(UINTPTR_MAX - first)) return 0;
    *start = first;
    *end = first + (uintptr_t)bytes;
    return 1;
}

static int dma_buffers_separated(const V8DmaContext *d)
{
    uintptr_t taps_start, taps_end, alt_start, alt_end;
    uintptr_t result_start, result_end;
    uint64_t taps_bytes, result_bytes;
    if (!d || !d->taps || !d->taps_alt || !d->result) return 0;
    taps_bytes = (uint64_t)d->input_capacity_words * sizeof(uint32_t);
    result_bytes = (uint64_t)d->result_capacity_words * sizeof(uint32_t);
    if (!dma_range(d->taps, taps_bytes, &taps_start, &taps_end) ||
        !dma_range(d->taps_alt, taps_bytes, &alt_start, &alt_end) ||
        !dma_range(d->result, result_bytes, &result_start, &result_end))
        return 0;
    return !(taps_start < alt_end && alt_start < taps_end) &&
           !(taps_start < result_end && result_start < taps_end) &&
           !(alt_start < result_end && result_start < alt_end);
}

/* Leave the accelerator held in abort if the DMA cannot prove reset done. */
static int reset_dma_and_release(V8DmaContext *d, XAxiDma *dma)
{
    uint32_t polls = poll_limit(d);
    int reset_done = 0;

    Xil_Out32(d->ctrl_base, V8_DMA_CTRL_ABORT);
    /* Older pulse-only control cannot implement coordinated recovery. */
    if ((Xil_In32(d->ctrl_base) & V8_DMA_CTRL_ABORT) == 0u) {
        d->faulted = 1u; d->probed = 0u; d->needs_probe = 1u;
        return -1;
    }
    XAxiDma_Reset(dma);
    while (polls--) {
        if (XAxiDma_ResetIsDone(dma) &&
            dma_channels_halted(dma) &&
            !dma_has_error(dma)) {
            reset_done = 1;
            break;
        }
    }
    if (!reset_done) {
        d->faulted = 1u;
        d->probed = 0u;
        d->needs_probe = 1u;
        return -1;
    }

    /* The abort stays asserted through the DMA's acknowledged reset. */
    Xil_Out32(d->ctrl_base, 0u);
    d->faulted = 0u;
    return 0;
}

static int fail_transfer(V8DmaContext *d, XAxiDma *dma, int error)
{
    d->last_transfer_error = error;
    d->failure_mm2s_status = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_TX_OFFSET, XAXIDMA_SR_OFFSET);
    d->failure_s2mm_status = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET, XAXIDMA_SR_OFFSET);
    d->failure_rx_bytes = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET, XAXIDMA_BUFFLEN_OFFSET);
    d->probed = 0u;
    d->needs_probe = 1u;
    if (reset_dma_and_release(d, dma) != 0) d->faulted = 1u;
    return error;
}

static int rx_length_is(XAxiDma *dma, uint32_t expected)
{
    uint32_t actual = XAxiDma_ReadReg(dma->RegBase + XAXIDMA_RX_OFFSET,
                                      XAXIDMA_BUFFLEN_OFFSET);
    return actual == expected;
}

typedef struct {
    uint32_t *taps;
    uint32_t taps_per_dot, batch_dots;
    size_t output_site;
    uint32_t input_bytes, result_bytes, result_cache_bytes;
    uint64_t submitted_ticks;
} V8DmaBatch;

static uint64_t batch_timeout_ticks(void)
{
    uint64_t ticks_per_second = (uint64_t)COUNTS_PER_SECOND;
    if (ticks_per_second > UINT64_MAX / V8_DMA_TIMEOUT_SECONDS)
        return UINT64_MAX;
    return ticks_per_second * V8_DMA_TIMEOUT_SECONDS;
}

static int batch_deadline_expired(uint64_t submitted_ticks)
{
    return read_ticks() - submitted_ticks >= batch_timeout_ticks();
}

/* Queue one dot-major batch. The descriptor owns an immutable snapshot of
 * all DMA-relevant values until finish_batch has validated S2MM. */
static int submit_batch(V8DmaContext *d, V8DmaBatch *batch,
                        uint32_t *taps, uint32_t taps_per_dot,
                        uint32_t batch_dots, size_t output_site,
                        int32_t bias)
{
    XAxiDma *dma = (XAxiDma *)d->dma;
    uint32_t input_words, result_words, input_bytes, result_bytes;
    uint32_t input_cache_bytes, result_cache_bytes;

    if (!taps_per_dot || taps_per_dot > V8_DMA_MAX_TAPS ||
        !batch_dots || batch_dots > V8_DMA_MAX_BATCH ||
        (uint64_t)taps_per_dot * batch_dots > V8_DMA_MAX_TAPS)
        return -1;
    input_words = taps_per_dot * batch_dots;
    result_words = batch_dots * 2u;
    if (input_words > d->input_capacity_words ||
        result_words > d->result_capacity_words)
        return -1;
    if ((taps != d->taps && taps != d->taps_alt) ||
        ((uintptr_t)taps & 63u) || ((uintptr_t)d->result & 63u))
        return -2;
    if (XAxiDma_HasSg(dma)) return -3;

    input_bytes = input_words * (uint32_t)sizeof(uint32_t);
    result_bytes = result_words * (uint32_t)sizeof(uint32_t);
    input_cache_bytes = (input_bytes + 63u) & ~63u;
    result_cache_bytes = (result_bytes + 63u) & ~63u;
    if ((uint64_t)input_cache_bytes > (uint64_t)d->input_capacity_words * 4u ||
        (uint64_t)result_cache_bytes > (uint64_t)d->result_capacity_words * 4u)
        return -1;

    batch->taps = taps;
    batch->taps_per_dot = taps_per_dot;
    batch->batch_dots = batch_dots;
    batch->output_site = output_site;
    batch->input_bytes = input_bytes;
    batch->result_bytes = result_bytes;
    batch->result_cache_bytes = result_cache_bytes;
    d->last_transfer_error = 0;
    d->active_taps = taps_per_dot;
    d->active_batch = batch_dots;

    /* Clear START before changing the latched configuration and queue RX
     * before launching the accelerator and its one MM2S input batch. */
    Xil_Out32(d->ctrl_base, 0u);
    Xil_Out32(d->ctrl_base + 4u, taps_per_dot);
    Xil_Out32(d->ctrl_base + 8u, (uint32_t)bias);
    Xil_Out32(d->ctrl_base + 12u, batch_dots);
    Xil_DCacheFlushRange((INTPTR)taps, input_cache_bytes);
    Xil_DCacheInvalidateRange((INTPTR)d->result, result_cache_bytes);
    if (XAxiDma_SimpleTransfer(dma, (UINTPTR)d->result, result_bytes,
                               XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS)
        return fail_transfer(d, dma, -4);

    batch->submitted_ticks = read_ticks();
    Xil_Out32(d->ctrl_base, V8_DMA_CTRL_START);
    if (XAxiDma_SimpleTransfer(dma, (UINTPTR)taps, input_bytes,
                               XAXIDMA_DMA_TO_DEVICE) != XST_SUCCESS)
        return fail_transfer(d, dma, -5);
    return 0;
}

/* A completed batch remains private until DMA status, byte count, and every
 * per-dot status word pass. Deadline starts when the accelerator is started,
 * so time spent packing the next buffer is included. */
static int finish_batch(V8DmaContext *d, const V8DmaBatch *batch)
{
    XAxiDma *dma = (XAxiDma *)d->dma;
    uint32_t polls = poll_limit(d);
    uint32_t deadline_poll_count = 0u;
    uint32_t i;

    while (polls) {
        if (dma_has_error(dma)) return fail_transfer(d, dma, -8);
        if (!XAxiDma_Busy(dma, XAXIDMA_DEVICE_TO_DMA) &&
            !XAxiDma_Busy(dma, XAXIDMA_DMA_TO_DEVICE))
            break;
        /* Accept an already-completed transfer even if packing delayed this
         * observation. Only an outstanding DMA past its deadline is aborted. */
        if ((deadline_poll_count++ & 0x3fu) == 0u &&
            batch_deadline_expired(batch->submitted_ticks)) {
            if (dma_has_error(dma)) return fail_transfer(d, dma, -8);
            if (!XAxiDma_Busy(dma, XAXIDMA_DEVICE_TO_DMA) &&
                !XAxiDma_Busy(dma, XAXIDMA_DMA_TO_DEVICE))
                break;
            return fail_transfer(d, dma, -6);
        }
        --polls;
    }
    if (XAxiDma_Busy(dma, XAXIDMA_DEVICE_TO_DMA) ||
        XAxiDma_Busy(dma, XAXIDMA_DMA_TO_DEVICE))
        return fail_transfer(d, dma, -6);
    if (dma_has_error(dma)) return fail_transfer(d, dma, -8);
    if (!rx_length_is(dma, batch->result_bytes))
        return fail_transfer(d, dma, -9);

    Xil_DCacheInvalidateRange((INTPTR)d->result, batch->result_cache_bytes);
    for (i = 0u; i < batch->batch_dots; ++i) {
        if (d->result[2u * i + 1u] != V8_DMA_STATUS_MAGIC)
            return fail_transfer(d, dma, -7);
    }
    return 0;
}

static void pack_batch(uint32_t *tap_buffer, uint32_t taps_per_dot,
                       uint32_t batch_dots, size_t site, uint32_t oc,
                       const V8Node *n, const V8Node *s,
                       const int8_t *input, const int8_t *weights,
                       size_t input_spatial)
{
    uint32_t b, ic, ky, kx;
    uint32_t patch_count = n->kernel * n->kernel;
    for (b = 0u; b < batch_dots; ++b) {
        size_t current_site = site + b;
        uint32_t oy = (uint32_t)(current_site / n->w);
        uint32_t ox = (uint32_t)(current_site % n->w);
        uint32_t at = b * taps_per_dot;
        /* Geometry is shared by every input channel. Compute the small 1x1/3x3
         * patch once per output dot, preserving IC/KY/KX packet order and
         * exact zero padding. */
        if (n->kernel <= 3u) {
            size_t patch[9];
            uint32_t p = 0u;
            int all_valid = 1;
            for (ky = 0u; ky < n->kernel; ++ky) {
                int64_t iy = (int64_t)oy * n->stride + ky - n->padding;
                for (kx = 0u; kx < n->kernel; ++kx) {
                    int64_t ix = (int64_t)ox * n->stride + kx - n->padding;
                    if (iy >= 0 && ix >= 0 && iy < (int64_t)s->h &&
                        ix < (int64_t)s->w)
                        patch[p] = (size_t)iy * s->w + (size_t)ix;
                    else { patch[p] = SIZE_MAX; all_valid = 0; }
                    ++p;
                }
            }
            for (ic = 0u; ic < s->c; ++ic) {
                const int8_t *channel = input + (size_t)ic * input_spatial;
                const int8_t *channel_weights = weights +
                    (size_t)oc * taps_per_dot + (size_t)ic * patch_count;
                if (all_valid) {
                    for (p = 0u; p < patch_count; ++p)
                        tap_buffer[at++] =
                            ((uint32_t)(uint8_t)channel_weights[p] << 8) |
                            (uint8_t)channel[patch[p]];
                } else {
                    for (p = 0u; p < patch_count; ++p) {
                        int8_t a = patch[p] == SIZE_MAX ? 0 : channel[patch[p]];
                        tap_buffer[at++] =
                            ((uint32_t)(uint8_t)channel_weights[p] << 8) |
                            (uint8_t)a;
                    }
                }
            }
            continue;
        }
        for (ic = 0u; ic < s->c; ++ic) {
            for (ky = 0u; ky < n->kernel; ++ky) {
                int64_t iy = (int64_t)oy * n->stride + ky - n->padding;
                for (kx = 0u; kx < n->kernel; ++kx) {
                    int64_t ix = (int64_t)ox * n->stride + kx - n->padding;
                    int8_t a = 0;
                    size_t weight_at =
                        (((size_t)oc * s->c + ic) * n->kernel + ky) *
                        n->kernel + kx;
                    int8_t w = weights[weight_at];
                    if (iy >= 0 && ix >= 0 &&
                        iy < (int64_t)s->h && ix < (int64_t)s->w) {
                        size_t input_at =
                            ((size_t)ic * s->h + (size_t)iy) * s->w +
                            (size_t)ix;
                        a = input[input_at];
                    }
                    tap_buffer[at++] =
                        ((uint32_t)(uint8_t)w << 8) | (uint8_t)a;
                }
            }
        }
    }
}

int v8_dma_probe(V8DmaContext *d)
{
    XAxiDma *dma;
    uint32_t polls;

    if (!d || !d->dma || !d->taps || !d->taps_alt || !d->result ||
        d->input_capacity_words < 16u || (d->input_capacity_words & 15u) ||
        d->result_capacity_words < 16u || (d->result_capacity_words & 15u) ||
        ((uintptr_t)d->taps & 63u) || ((uintptr_t)d->taps_alt & 63u) ||
        ((uintptr_t)d->result & 63u) || !dma_buffers_separated(d)) return -1;
    dma = (XAxiDma *)d->dma;
    d->probed = 0u;
    d->needs_probe = 1u;
    if (XAxiDma_HasSg(dma)) return -2;

    /* Every startup and explicit recovery probe begins from coordinated reset. */
    if (reset_dma_and_release(d, dma) != 0) return -3;
    polls = poll_limit(d);
    Xil_Out32(d->ctrl_base, 0u);
    Xil_Out32(d->ctrl_base + 4u, 0u);
    Xil_Out32(d->ctrl_base + 8u, 0x18c047a5u);
    Xil_Out32(d->ctrl_base + 12u, 1u);
    Xil_DCacheInvalidateRange((INTPTR)d->result, 64u);
    if (XAxiDma_SimpleTransfer(dma, (UINTPTR)d->result, 8u,
                               XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS)
        goto transfer_failed;

    Xil_Out32(d->ctrl_base, V8_DMA_CTRL_START);
    while (polls) {
        if (dma_has_error(dma)) goto transfer_failed;
        if (!XAxiDma_Busy(dma, XAXIDMA_DEVICE_TO_DMA)) break;
        --polls;
    }
    if (XAxiDma_Busy(dma, XAXIDMA_DEVICE_TO_DMA) || dma_has_error(dma) ||
        !rx_length_is(dma, 8u)) goto transfer_failed;

    Xil_DCacheInvalidateRange((INTPTR)d->result, 64u);
    if (d->result[0] != 0x18c047a5u ||
        d->result[1] != V8_DMA_STATUS_MAGIC) {
        /* Reject older PL images whose status word has no batch contract. */
        (void)reset_dma_and_release(d, dma);
        d->faulted = 1u;
        d->probed = 0u;
        d->needs_probe = 1u;
        return -5;
    }
    Xil_Out32(d->ctrl_base, 0u);
    d->faulted = 0u;
    d->needs_probe = 0u;
    d->probed = 1u;
    return 0;

transfer_failed:
    (void)reset_dma_and_release(d, dma);
    d->faulted = 1u;
    d->probed = 0u;
    d->needs_probe = 1u;
    return -4;
}

static int32_t read_bias(const uint8_t *bias_le, size_t oc)
{
    size_t at = oc * 4u;
    uint32_t value = (uint32_t)bias_le[at] |
        ((uint32_t)bias_le[at + 1u] << 8) |
        ((uint32_t)bias_le[at + 2u] << 16) |
        ((uint32_t)bias_le[at + 3u] << 24);
    return (int32_t)value;
}

int v8_dma_conv(void *opaque, const V8Node *n, const V8Node *s,
                const int8_t *input, const int8_t *weights,
                const uint8_t *bias_le, int32_t *raw)
{
    V8DmaContext *d = (V8DmaContext *)opaque;
    uint64_t taps64;
    size_t sites, input_spatial, input_elements, raw_elements;
    size_t oc, site;
    uint32_t capacity_batch;
    uint64_t completed_dots = 0u;

    if (!d || !d->dma || !d->taps || !d->taps_alt || !d->result ||
        d->taps == d->taps_alt || !n || !s || !input ||
        !weights || !bias_le || !raw || !n->kernel || !n->stride ||
        !n->c || !n->h || !n->w || !s->c || !s->h || !s->w ||
        n->groups != 1u)
        return -10;
    if (d->input_capacity_words < 16u || (d->input_capacity_words & 15u) ||
        d->result_capacity_words < 16u || (d->result_capacity_words & 15u) ||
        ((uintptr_t)d->taps & 63u) || ((uintptr_t)d->taps_alt & 63u) ||
        ((uintptr_t)d->result & 63u) || !dma_buffers_separated(d))
        return -11;

    /* Bound shape arithmetic before creating tensor offsets on the 32-bit ARM. */
    if ((uint64_t)s->c > UINT64_MAX / n->kernel / n->kernel) return -11;
    taps64 = (uint64_t)s->c * n->kernel * n->kernel;
    if (!taps64 || taps64 > V8_DMA_MAX_TAPS ||
        taps64 > d->input_capacity_words || d->result_capacity_words < 2u)
        return -11;
    if ((size_t)n->h > SIZE_MAX / (size_t)n->w) return -10;
    sites = (size_t)n->h * (size_t)n->w;
    if ((size_t)s->h > SIZE_MAX / (size_t)s->w) return -10;
    input_spatial = (size_t)s->h * (size_t)s->w;
    if ((size_t)s->c > SIZE_MAX / input_spatial) return -10;
    input_elements = (size_t)s->c * input_spatial;
    (void)input_elements;
    if ((size_t)n->c > SIZE_MAX / sites) return -10;
    raw_elements = (size_t)n->c * sites;
    if (raw_elements > SIZE_MAX / sizeof(*raw) ||
        (uint64_t)n->c * taps64 > SIZE_MAX)
        return -10;

    d->last_conv_dots = 0u;
    d->last_conv_batches = 0u;
    d->last_conv_pack_ticks = 0u;
    d->last_conv_dma_ticks = 0u;

    /* A prior callback failure has already unwound its inference. Probe once
     * here before beginning the next caller-requested inference; never retry
     * the failed batch or hide its error from the caller. */
    if ((!d->probed || d->needs_probe || d->faulted) && v8_dma_probe(d) != 0)
        return -13;

    capacity_batch = V8_DMA_MAX_BATCH;
    if (capacity_batch > V8_DMA_MAX_TAPS / (uint32_t)taps64)
        capacity_batch = V8_DMA_MAX_TAPS / (uint32_t)taps64;
    if (capacity_batch > d->input_capacity_words / (uint32_t)taps64)
        capacity_batch = d->input_capacity_words / (uint32_t)taps64;
    if (capacity_batch > d->result_capacity_words / 2u)
        capacity_batch = d->result_capacity_words / 2u;
    if (!capacity_batch) return -11;

    for (oc = 0u; oc < (size_t)n->c; ++oc) {
        int32_t bias = read_bias(bias_le, oc);
        uint32_t *active_taps = d->taps;
        uint32_t *spare_taps = d->taps_alt;
        V8DmaBatch active;
        uint32_t active_dots;
        uint64_t pack_started;
        uint64_t elapsed;
        int rc;

        site = 0u;
        active_dots = capacity_batch;
        if ((size_t)active_dots > sites - site)
            active_dots = (uint32_t)(sites - site);
        pack_started = read_ticks();
        pack_batch(active_taps, (uint32_t)taps64, active_dots, site,
                   (uint32_t)oc, n, s, input, weights, input_spatial);
        elapsed = read_ticks() - pack_started;
        d->last_conv_pack_ticks += elapsed;
        d->total_pack_ticks += elapsed;
        rc = submit_batch(d, &active, active_taps, (uint32_t)taps64,
                          active_dots, site, bias);
        if (rc != 0) return -12;
        site += active_dots;

        for (;;) {
            V8DmaBatch next;
            uint32_t next_dots = 0u;
            uint64_t elapsed;

            /* Prepare the following spatial batch while the accelerator
             * consumes active.taps. Never cross an output-channel boundary;
             * each channel's final DMA is drained before its bias changes. */
            if (site < sites) {
                next_dots = capacity_batch;
                if ((size_t)next_dots > sites - site)
                    next_dots = (uint32_t)(sites - site);
                pack_started = read_ticks();
                pack_batch(spare_taps, (uint32_t)taps64, next_dots, site,
                           (uint32_t)oc, n, s, input, weights, input_spatial);
                elapsed = read_ticks() - pack_started;
                d->last_conv_pack_ticks += elapsed;
                d->total_pack_ticks += elapsed;
            }

            rc = finish_batch(d, &active);
            elapsed = read_ticks() - active.submitted_ticks;
            d->last_conv_dma_ticks += elapsed;
            d->total_dma_ticks += elapsed;
            if (rc != 0) return -12;

            /* No raw output is visible until the complete batch passes. */
            {
                uint32_t b;
                for (b = 0u; b < active.batch_dots; ++b)
                    raw[oc * sites + active.output_site + b] =
                        (int32_t)d->result[2u * b];
            }
            ++d->transactions;
            ++d->last_conv_batches;
            d->total_dots += active.batch_dots;
            completed_dots += active.batch_dots;
            d->last_conv_dots = completed_dots;

            if (d->progress) {
                uint64_t next_progress =
                    ((completed_dots - active.batch_dots) / 256u + 1u) * 256u;
                while (next_progress <= completed_dots) {
                    d->progress(d->progress_opaque);
                    next_progress += 256u;
                }
            }

            if (site >= sites) break;
            rc = submit_batch(d, &next, spare_taps, (uint32_t)taps64,
                              next_dots, site, bias);
            if (rc != 0) return -12;
            active = next;
            site += next_dots;
            active_taps = spare_taps;
            spare_taps = active_taps == d->taps ? d->taps_alt : d->taps;
        }
    }
    return 0;
}
#else
int v8_dma_probe(V8DmaContext *d) { (void)d; return -100; }
int v8_dma_conv(void *opaque, const V8Node *n, const V8Node *s,
                const int8_t *input, const int8_t *weights,
                const uint8_t *bias_le, int32_t *raw)
{
    (void)opaque; (void)n; (void)s; (void)input; (void)weights;
    (void)bias_le; (void)raw;
    return -100; /* no silent software fallback */
}
#endif
