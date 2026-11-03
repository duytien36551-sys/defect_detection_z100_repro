#include "v8_pipeline.h"
#ifdef V8_TILE_PROFILE
#include "v8_tile_profile.h"
#endif

#include <math.h>
#include <string.h>
#include <limits.h>

#define V8_INPUT_PIXELS (640u * 640u)
#define V8_INPUT_BYTES (3u * V8_INPUT_PIXELS)
#define V8_PIN640_HEAD_CHANNELS (4u * 16u + 9u)
#define V8_PIN640_HEAD_ELEMENTS \
    (V8_PIN640_HEAD_CHANNELS * (80u * 80u + 40u * 40u + 20u * 20u))

static int pipeline_heads_preflight(const V8Pipeline *pipeline,
                                    const V8Graph *graph) {
    static const uint32_t expected_widths[3] = {80u, 40u, 20u};
    size_t total = 0u;
    size_t i;

    if (!pipeline || !pipeline->runtime || !pipeline->runtime->arena ||
        !graph || !graph->nodes || !graph->count ||
        pipeline->heads_capacity < V8_PIN640_HEAD_ELEMENTS)
        return -5;
    for (i = 0; i < 3u; ++i) {
        uint32_t id = graph->outputs[i];
        const V8Node *node;
        size_t elements;
        if (id >= graph->count)
            return -4;
        node = graph->nodes + id;
        elements = (size_t)V8_PIN640_HEAD_CHANNELS * expected_widths[i] *
                   expected_widths[i];
        if (node->c != V8_PIN640_HEAD_CHANNELS ||
            node->h != expected_widths[i] || node->w != expected_widths[i] ||
            node->bytes != elements || !isfinite(node->scale) ||
            node->scale <= 0.0 || node->offset > pipeline->runtime->arena_size ||
            elements > pipeline->runtime->arena_size - node->offset ||
            total > pipeline->heads_capacity ||
            elements > pipeline->heads_capacity - total)
            return -5;
        total += elements;
    }
    return total == V8_PIN640_HEAD_ELEMENTS ? 0 : -5;
}

static int8_t quant_input(double value) {
    double lo = floor(value), fraction = value - lo;
    double rounded = (fraction > .5 || (fraction == .5 && fmod(lo, 2.0) != 0.0)) ? lo + 1.0 : lo;
    if (rounded > 127.0) rounded = 127.0;
    if (rounded < -127.0) rounded = -127.0;
    return (int8_t)rounded;
}

static uint64_t pipeline_ticks(const V8Pipeline *pipeline)
{
    if (!pipeline || !pipeline->diagnostics || !pipeline->runtime ||
        !pipeline->runtime->clock)
        return 0u;
    return pipeline->runtime->clock(pipeline->runtime->trace_opaque);
}

int v8_pipeline_infer(V8Pipeline *pipeline, const uint8_t *rgb, size_t rgb_bytes,
                      V8Detection *detections, size_t capacity, size_t *count) {
#ifdef V8_TILE_PROFILE
    v8_tile_profile_reset();
#endif
    const V8Graph *graph;
    V8Head heads[3];
    int8_t input_lut[256];
    size_t at = 0, i, k;
    int rc = 0;
    V8PipelineDiagnostics *diagnostics = pipeline ? pipeline->diagnostics : NULL;
    uint64_t total_started = 0u, phase_started = 0u;

    if (diagnostics) {
        total_started = pipeline_ticks(pipeline);
        diagnostics->inference_id = diagnostics->inference_id + 1u;
        diagnostics->rc = INT32_MIN;
        diagnostics->detection_count = 0u;
        diagnostics->node_count = 0u;
        diagnostics->trace_dropped = 0u;
        diagnostics->preprocess_ticks = 0u;
        diagnostics->graph_ticks = 0u;
        diagnostics->dequantization_ticks = 0u;
        diagnostics->decode_ticks = 0u;
        diagnostics->total_ticks = 0u;
    }
    if (count) *count = 0;
    if (!pipeline || !pipeline->runtime || !rgb || !detections || !count ||
        !pipeline->input_nchw || !pipeline->heads_float ||
        rgb_bytes != V8_INPUT_BYTES || pipeline->input_capacity < V8_INPUT_BYTES ||
        !pipeline->runtime->conv || capacity == 0) {
        rc = -1;
        goto finish;
    }
    graph = pipeline->runtime->graph;
    if (!graph || !isfinite(graph->input_scale) || graph->input_scale <= 0.0 ||
        graph->classes != 9u || graph->reg_max != 16u ||
        graph->input_size != 640u || pipeline->decode.input_width != (int)graph->input_size ||
        pipeline->decode.input_height != (int)graph->input_size ||
        pipeline->decode.classes != (int)graph->classes ||
        pipeline->decode.reg_max != (int)graph->reg_max) {
        rc = -2;
        goto finish;
    }
    rc = pipeline_heads_preflight(pipeline, graph);
    if (rc) goto finish;

    if (diagnostics) phase_started = pipeline_ticks(pipeline);
    /* Evaluate the original expression for every possible RGB byte. This
     * retains its operation order and ties-to-even rule, then reuses it. */
    for (i = 0; i < 256u; ++i)
        input_lut[i] = quant_input(((double)i / 255.0) / graph->input_scale);
    for (i = 0; i < V8_INPUT_PIXELS; ++i)
        for (k = 0; k < 3; ++k)
            pipeline->input_nchw[k * V8_INPUT_PIXELS + i] =
                input_lut[rgb[3 * i + k]];
    if (diagnostics)
        diagnostics->preprocess_ticks = pipeline_ticks(pipeline) - phase_started;

    if (diagnostics) phase_started = pipeline_ticks(pipeline);
    rc = v8_run(pipeline->runtime, pipeline->input_nchw, V8_INPUT_BYTES);
    if (diagnostics)
        diagnostics->graph_ticks = pipeline_ticks(pipeline) - phase_started;
    if (rc) goto finish;

    if (diagnostics) phase_started = pipeline_ticks(pipeline);
    for (i = 0; i < 3; ++i) {
        uint32_t id = graph->outputs[i];
        const V8Node *node;
        size_t elements;
        if (id >= graph->count) {
            rc = -4;
            break;
        }
        node = graph->nodes + id;
        elements = node->bytes;
        if (node->c != V8_PIN640_HEAD_CHANNELS ||
            node->w != (i == 0u ? 80u : (i == 1u ? 40u : 20u)) ||
            node->h != node->w || elements > pipeline->heads_capacity - at ||
            node->offset > pipeline->runtime->arena_size ||
            elements > pipeline->runtime->arena_size - node->offset) {
            rc = -5;
            break;
        }
        heads[i].data = pipeline->heads_float + at;
        heads[i].width = (int)node->w;
        heads[i].height = (int)node->h;
        heads[i].stride = (int)(graph->input_size / node->w);
        for (k = 0; k < elements; ++k)
            pipeline->heads_float[at + k] =
                (float)((double)pipeline->runtime->arena[node->offset + k] * node->scale);
        at += elements;
    }
    if (diagnostics)
        diagnostics->dequantization_ticks = pipeline_ticks(pipeline) - phase_started;
    if (rc) goto finish;

    if (diagnostics) phase_started = pipeline_ticks(pipeline);
    rc = v8_decode_raw(heads, 3, &pipeline->decode, detections, capacity, count);
    if (diagnostics)
        diagnostics->decode_ticks = pipeline_ticks(pipeline) - phase_started;

finish:
    if (diagnostics) {
        diagnostics->rc = rc;
        diagnostics->detection_count = count ? (uint32_t)*count : 0u;
        diagnostics->total_ticks = pipeline_ticks(pipeline) - total_started;
    }
    return rc;
}
