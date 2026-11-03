#include "v8_pipeline.h"
#include "v8_service.h"
#include "v8_tile_abi.h"
#include "v8_tile_board_dma.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    INPUT_PIXELS = 640 * 640,
    INPUT_BYTES = 3 * INPUT_PIXELS,
    HEAD_CHANNELS = 4 * 16 + 9,
    HEAD_ELEMENTS = HEAD_CHANNELS * (80 * 80 + 40 * 40 + 20 * 20),
    MAX_HEAD_PLANE = HEAD_CHANNELS * 80 * 80,
    NODE_COUNT = 3,
    MAX_PARAMS = 4096,
    PACKAGE_CAPACITY = 32 + MAX_PARAMS,
    GUARD_BYTE = 0xA7
};

_Static_assert(INPUT_BYTES == 1228800, "PIN640 RGB frame size changed");
_Static_assert(HEAD_ELEMENTS == 613200, "PIN640 head buffer size changed");
_Static_assert(V8_SERVICE_TENSOR_BYTES == INPUT_BYTES,
               "service and graph input size must agree");
_Static_assert(V8_TILE_DMA_MAX_BYTES == 262140u,
               "tile MM2S maximum changed");
_Static_assert(V8_TILE_TX_CAPACITY_BYTES == 262144u,
               "tile TX storage changed");
_Static_assert(V8_TILE_MAX_RESPONSE_BYTES == 16404u,
               "tile S2MM response changed");
_Static_assert(V8_TILE_RX_CAPACITY_BYTES == 16448u,
               "tile RX storage changed");
_Static_assert(_Alignof(V8TileBoardDma) >= 64u,
               "board DMA context must preserve cache-line alignment");
_Static_assert(INPUT_BYTES > V8_TILE_DMA_MAX_BYTES,
               "whole RGB frame must never fit one tile DMA transfer");

static V8Node nodes[NODE_COUNT];
static V8Graph graph;
static V8Runtime runtime;
static V8Pipeline pipeline;
static uint8_t params[MAX_PARAMS];
static uint8_t package[PACKAGE_CAPACITY];
static struct { uint8_t before, bytes[INPUT_BYTES], after; } rgb_guard;
static struct { uint8_t before, bytes[INPUT_BYTES], after; } input_guard;
static struct { uint8_t before, bytes[HEAD_ELEMENTS], after; } arena_guard;
static struct { int32_t before, values[MAX_HEAD_PLANE], after; } scratch_guard;
static struct { float before, values[HEAD_ELEMENTS], after; } heads_guard;
static struct {
    uint32_t before;
    V8Detection values[300];
    uint32_t after;
} detections_guard;
static unsigned conv_calls;

static void put32(uint8_t *p, uint32_t value)
{
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
    p[2] = (uint8_t)(value >> 16);
    p[3] = (uint8_t)(value >> 24);
}

static uint32_t crc32(const uint8_t *p, size_t n)
{
    uint32_t crc = ~0u;
    size_t i;
    int bit;
    for (i = 0; i < n; ++i) {
        crc ^= p[i];
        for (bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

static int guards_ok(void)
{
    return rgb_guard.before == GUARD_BYTE && rgb_guard.after == GUARD_BYTE &&
           input_guard.before == GUARD_BYTE && input_guard.after == GUARD_BYTE &&
           arena_guard.before == GUARD_BYTE && arena_guard.after == GUARD_BYTE &&
           scratch_guard.before == (int32_t)0x5A5A5A5Au &&
           scratch_guard.after == (int32_t)0x5A5A5A5Au &&
           heads_guard.before == 13579.25f && heads_guard.after == 13579.25f &&
           detections_guard.before == 0x13579BDFu &&
           detections_guard.after == 0x13579BDFu;
}

static size_t make_graph(void)
{
    static const uint32_t widths[NODE_COUNT] = {80u, 40u, 20u};
    uint32_t arena_at = 0u, param_at = 0u, i, channel;
    memset(nodes, 0, sizeof(nodes));
    memset(params, 0, sizeof(params));
    memset(&graph, 0, sizeof(graph));
    for (i = 0; i < NODE_COUNT; ++i) {
        const uint32_t width = widths[i];
        const uint32_t elements = HEAD_CHANNELS * width * width;
        double one = 1.0;
        nodes[i].op = V8_CONV;
        nodes[i].c = HEAD_CHANNELS;
        nodes[i].h = width;
        nodes[i].w = width;
        nodes[i].offset = arena_at;
        nodes[i].bytes = elements;
        nodes[i].inputs[0] = -1;
        nodes[i].count = 1u;
        nodes[i].kernel = 1u;
        nodes[i].stride = 640u / width;
        nodes[i].groups = 1u;
        nodes[i].scale = 1.0;
        nodes[i].weight = param_at;
        param_at += HEAD_CHANNELS * 3u;
        nodes[i].bias = param_at;
        param_at += HEAD_CHANNELS * 4u;
        nodes[i].multiplier = param_at;
        param_at += HEAD_CHANNELS * 8u;
        for (channel = 0; channel < HEAD_CHANNELS; ++channel)
            memcpy(params + nodes[i].multiplier + channel * 8u, &one, sizeof(one));
        graph.outputs[i] = i;
        arena_at += elements;
    }
    graph.nodes = nodes;
    graph.count = NODE_COUNT;
    graph.arena_bytes = arena_at;
    graph.param_bytes = param_at;
    graph.param_crc = crc32(params, param_at);
    graph.input_scale = 1.0 / 127.0;
    graph.classes = 9u;
    graph.reg_max = 16u;
    graph.input_size = 640u;
    return param_at;
}

static size_t make_package(size_t param_bytes)
{
    memset(package, 0, sizeof(package));
    memcpy(package, "V8PK", 4u);
    put32(package + 4u, 1u);
    put32(package + 8u, (uint32_t)param_bytes);
    put32(package + 12u, graph.param_crc);
    put32(package + 16u, graph.count);
    put32(package + 20u, graph.arena_bytes);
    put32(package + 24u, graph.classes);
    put32(package + 28u, graph.input_size);
    memcpy(package + 32u, params, param_bytes);
    return 32u + param_bytes;
}

static int package_rejected(size_t bytes)
{
    const uint8_t *payload = (const uint8_t *)1;
    return v8_package_open(package, bytes, &graph, &payload) != 0 &&
           payload == 0;
}

static void setup_runtime(void)
{
    (void)make_graph();
    memset(input_guard.bytes, 0, sizeof(input_guard.bytes));
    memset(arena_guard.bytes, 0, sizeof(arena_guard.bytes));
    memset(scratch_guard.values, 0, sizeof(scratch_guard.values));
    memset(heads_guard.values, 0, sizeof(heads_guard.values));
    memset(detections_guard.values, 0, sizeof(detections_guard.values));
    rgb_guard.before = input_guard.before = arena_guard.before = GUARD_BYTE;
    rgb_guard.after = input_guard.after = arena_guard.after = GUARD_BYTE;
    scratch_guard.before = scratch_guard.after = (int32_t)0x5A5A5A5Au;
    heads_guard.before = heads_guard.after = 13579.25f;
    detections_guard.before = detections_guard.after = 0x13579BDFu;
    memset(&runtime, 0, sizeof(runtime));
    memset(&pipeline, 0, sizeof(pipeline));
    runtime.graph = &graph;
    runtime.params = params;
    runtime.param_size = graph.param_bytes;
    runtime.arena = (int8_t *)arena_guard.bytes;
    runtime.arena_size = sizeof(arena_guard.bytes);
    runtime.scratch = scratch_guard.values;
    runtime.scratch_count = MAX_HEAD_PLANE;
    runtime.conv = 0;
    pipeline.runtime = &runtime;
    pipeline.input_nchw = (int8_t *)input_guard.bytes;
    pipeline.input_capacity = sizeof(input_guard.bytes);
    pipeline.heads_float = heads_guard.values;
    pipeline.heads_capacity = HEAD_ELEMENTS;
    pipeline.decode = (V8DecodeConfig){640, 640, 9, 16, .99f, .45f, 1, 0, 0};
    conv_calls = 0u;
}

static int conv(void *opaque, const V8Node *output, const V8Node *source,
                const int8_t *input, const int8_t *weights,
                const uint8_t *bias, int32_t *raw)
{
    size_t i, count = (size_t)output->c * output->h * output->w;
    (void)opaque;
    (void)source;
    (void)weights;
    (void)bias;
    if (!input || !raw || output->c != HEAD_CHANNELS ||
        output->w != (conv_calls == 0u ? 80u : (conv_calls == 1u ? 40u : 20u)))
        return -90;
    if (conv_calls == 0u &&
        (input[0] != 127 || input[INPUT_PIXELS] != 64 ||
         input[2u * INPUT_PIXELS] != 0))
        return -91;
    for (i = 0; i < count; ++i) raw[i] = 0;
    ++conv_calls;
    return 0;
}

static int test_tile_dma_budget(void)
{
    V8Node input = {0}, output = {0};
    V8TileConfig config;
    input.c = 4091u;
    input.h = input.w = 640u;
    output.op = V8_CONV;
    output.c = 64u;
    output.h = output.w = 80u;
    output.kernel = 1u;
    output.stride = 8u;
    output.groups = 1u;
    if (v8_tile_config_init(&output, &input, 0u, 0u, 64u, 7u, &config) !=
            V8_TILE_OK ||
        config.taps != 4091u || config.padded_taps != 4092u ||
        config.run_bytes != 261888u || config.load_bytes != 262080u ||
        config.response_bytes != 16404u)
        return 1;
    if (v8_tile_config_init(&output, &input, 0u, 0u, 65u, 7u, &config) !=
        V8_TILE_ECAPACITY)
        return 2;
    return 0;
}

int main(void)
{
    const uint8_t *payload = (const uint8_t *)1;
    size_t param_bytes = make_graph();
    size_t package_bytes = make_package(param_bytes);
    size_t count;
    int rc;

    setup_runtime();
    pipeline.runtime->conv = conv;
    if (v8_package_open(package, package_bytes, &graph, &payload) != 0 ||
        payload != package + 32u) return 1;
    if (!package_rejected(package_bytes - 1u) ||
        !package_rejected(package_bytes + 1u))
        return 2;
    put32(package + 24u, 18u);
    if (!package_rejected(package_bytes)) return 3;
    put32(package + 24u, 9u);
    put32(package + 28u, 416u);
    if (!package_rejected(package_bytes)) return 4;
    put32(package + 28u, 640u);
    package[package_bytes - 1u] ^= 1u;
    if (v8_package_open(package, package_bytes, &graph, &payload) != -2 ||
        payload != 0) return 5;
    package[package_bytes - 1u] ^= 1u;
    graph.classes = 18u;
    if (!package_rejected(package_bytes)) return 6;
    graph.classes = 9u;
    graph.input_size = 416u;
    if (!package_rejected(package_bytes)) return 7;
    graph.input_size = 640u;

    runtime.conv = conv;
    if (v8_run(&runtime, (const int8_t *)input_guard.bytes,
               3u * 416u * 416u) == 0 || conv_calls != 0u)
        return 8;
    if (v8_run(&runtime, (const int8_t *)input_guard.bytes,
               INPUT_BYTES + 1u) == 0 || conv_calls != 0u)
        return 9;

    memset(rgb_guard.bytes, 0, sizeof(rgb_guard.bytes));
    rgb_guard.bytes[0] = 255u;
    rgb_guard.bytes[1] = 128u;
    rgb_guard.bytes[2] = 0u;
    setup_runtime();
    pipeline.runtime->conv = conv;
    count = 99u;
    rc = v8_pipeline_infer(&pipeline, rgb_guard.bytes, INPUT_BYTES,
                           detections_guard.values, 300u, &count);
    if (rc != 0 || count != 0u || conv_calls != 3u ||
        runtime.completed != NODE_COUNT || heads_guard.values[0] != 0.0f ||
        heads_guard.values[HEAD_ELEMENTS - 1u] != 0.0f || !guards_ok()) {
        fprintf(stderr, "valid pipeline rc=%d count=%lu conv=%u completed=%u guards=%d\n",
                rc, (unsigned long)count, conv_calls, runtime.completed,
                guards_ok());
        return 10;
    }
    if (v8_pipeline_infer(&pipeline, rgb_guard.bytes, 3u * 416u * 416u,
                          detections_guard.values, 300u, &count) == 0 ||
        count != 0u || conv_calls != 3u)
        return 11;
    pipeline.input_capacity = INPUT_BYTES - 1u;
    if (v8_pipeline_infer(&pipeline, rgb_guard.bytes, INPUT_BYTES,
                          detections_guard.values, 300u, &count) == 0 ||
        conv_calls != 3u)
        return 12;
    pipeline.input_capacity = INPUT_BYTES;
    pipeline.heads_capacity = HEAD_ELEMENTS - 1u;
    if (v8_pipeline_infer(&pipeline, rgb_guard.bytes, INPUT_BYTES,
                          detections_guard.values, 300u, &count) != -5 ||
        conv_calls != 3u || !guards_ok())
        return 13;

    setup_runtime();
    pipeline.runtime->conv = conv;
    nodes[0].h = nodes[0].w = 40u;
    nodes[0].bytes = HEAD_CHANNELS * 40u * 40u;
    if (v8_pipeline_infer(&pipeline, rgb_guard.bytes, INPUT_BYTES,
                          detections_guard.values, 300u, &count) != -5 ||
        conv_calls != 0u)
        return 14;

    setup_runtime();
    runtime.arena_size = graph.arena_bytes - 1u;
    if (v8_run(&runtime, (const int8_t *)input_guard.bytes, INPUT_BYTES) != -2 ||
        conv_calls != 0u)
        return 15;
    setup_runtime();
    runtime.scratch_count = MAX_HEAD_PLANE - 1u;
    if (v8_run(&runtime, (const int8_t *)input_guard.bytes, INPUT_BYTES) != -2 ||
        conv_calls != 0u)
        return 16;
    setup_runtime();
    nodes[0].offset = UINT32_MAX - 4u;
    if (v8_run(&runtime, (const int8_t *)input_guard.bytes, INPUT_BYTES) != -2 ||
        conv_calls != 0u || !guards_ok())
        return 17;
    setup_runtime();
    nodes[0].weight = UINT32_MAX - 4u;
    if (v8_graph_preflight(&runtime) == 0 || !guards_ok()) return 18;

    rc = test_tile_dma_budget();
    if (rc != 0) return 18 + rc;
    if (!guards_ok()) return 21;
    puts("PIN640 runtime bounds, heads, package, and DMA contracts: PASS");
    return 0;
}
