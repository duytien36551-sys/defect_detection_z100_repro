#ifndef V8_DMA_H
#define V8_DMA_H
#include <stdint.h>
#include "v8_runtime.h"

/* V8 batch ABI, implemented by the matching V8 accelerator bitstream.
 * CTRL[0]: START bit 0, ABORT bit 1; CTRL[1]: taps per dot T;
 * CTRL[2]: signed accumulator bias; CTRL[3]: spatial dots per batch B.
 * Valid work has 1 <= T <= 16383, 1 <= B <= 1024, and T*B <= 16383.
 * Startup probe is T=0, B=1 and returns bias/status in the two-word result.
 * MM2S input is dot-major (T packed weight/activation words per dot).
 * S2MM output is dot-major raw/status word pairs, with one pair per dot.
 */
#define V8_DMA_STATUS_MAGIC 0x563A0000u
#define V8_DMA_CTRL_START 0x00000001u
#define V8_DMA_CTRL_ABORT 0x00000002u
#define V8_DMA_MAX_TAPS 16383u
#define V8_DMA_MAX_BATCH 1024u

/* Caller supplies two 64-byte aligned tap buffers and one aligned result
 * buffer. Each tap buffer has input_capacity_words; the result buffer holds
 * two words per output dot. Capacities are cache-line multiples (at least
 * 16 words). Only one DMA batch is active at a time; the alternate tap buffer
 * may be packed while the active buffer is consumed by MM2S.
 * Diagnostic tick values are raw XTime counter ticks, not converted units.
 */
typedef struct {
    void *dma;
    uintptr_t ctrl_base;
    uint32_t *taps;
    uint32_t *taps_alt;
    uint32_t input_capacity_words;
    uint32_t *result;
    uint32_t result_capacity_words;
    uint32_t timeout_polls;
    uint32_t probed, needs_probe, faulted;
    uint64_t transactions; /* successfully completed DMA batches */
    uint64_t total_dots;   /* successfully returned output dots */
    uint64_t last_conv_dots;
    uint64_t last_conv_batches;
    uint64_t last_conv_pack_ticks;
    uint64_t last_conv_dma_ticks; /* submit-to-complete; overlaps pack ticks */
    uint64_t total_pack_ticks;
    uint64_t total_dma_ticks;
    void (*progress)(void *opaque);
    void *progress_opaque;
    int32_t last_transfer_error;
    uint32_t failure_mm2s_status, failure_s2mm_status, failure_rx_bytes;
    uint32_t active_taps, active_batch;
} V8DmaContext;

/* Connect to V8Runtime.conv. Requires V8_XILINX_BSP and simple-mode AXI DMA. */
int v8_dma_probe(V8DmaContext *context);
/* Following a failed inference, the next call probes before starting new work. */
int v8_dma_conv(void *opaque, const V8Node *node, const V8Node *source,
                const int8_t *input, const int8_t *weights,
                const uint8_t *bias_le, int32_t *raw);
#endif
