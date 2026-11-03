#ifndef V8_PIPELINE_H
#define V8_PIPELINE_H

#include <stddef.h>
#include <stdint.h>
#include "v8_runtime.h"
#include "v8_decode.h"

#define V8_PIPELINE_DIAGNOSTIC_NODES 163u

/* Optional board-readable timing snapshot. Tick counts use the configured
 * runtime clock units. Node arrays are indexed by graph node ID; node_count
 * identifies the current request's valid prefix and trace_dropped counts
 * nodes beyond the fixed diagnostic capacity.
 */
typedef struct {
    volatile uint64_t inference_id;
    volatile int32_t rc;
    volatile uint32_t detection_count;
    volatile uint32_t node_count;
    volatile uint32_t trace_dropped;
    volatile uint64_t preprocess_ticks;
    volatile uint64_t graph_ticks;
    volatile uint64_t dequantization_ticks;
    volatile uint64_t decode_ticks;
    volatile uint64_t total_ticks;
    volatile uint32_t node_op[V8_PIPELINE_DIAGNOSTIC_NODES];
    volatile uint64_t node_ticks[V8_PIPELINE_DIAGNOSTIC_NODES];
} V8PipelineDiagnostics;

/* Board inference bridge. Caller owns all buffers. A configured convolution
 * backend is required; NULL would select the host/ARM reference in v8_run. */
typedef struct {
    V8Runtime *runtime;
    int8_t *input_nchw;
    size_t input_capacity;
    float *heads_float;
    size_t heads_capacity;
    V8DecodeConfig decode;
    V8PipelineDiagnostics *diagnostics; /* optional; NULL disables phase output */
} V8Pipeline;

/* RGB interleaved uint8 input uses /255, followed by symmetric signed INT8
 * quantization with the graph's input_scale and ties-to-even rounding. */
int v8_pipeline_infer(V8Pipeline *pipeline, const uint8_t *rgb, size_t rgb_bytes,
                      V8Detection *detections, size_t capacity, size_t *count);

#endif
