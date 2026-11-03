#ifndef NATIVE_POSTPROCESS_EPOCH200_V1_H
#define NATIVE_POSTPROCESS_EPOCH200_V1_H

#include <stddef.h>
#include <stdint.h>

#include "../firmware/v8_decode.h"

#define V8_EPOCH200_HEAD_COUNT 3u
#define V8_EPOCH200_RAW_BYTES 613200u

typedef struct {
    int node_id;
    int channels;
    int height;
    int width;
    int stride;
    double scale;
} V8Epoch200HeadIdentity;

typedef struct {
    const char *package_sha256;
    const char *checkpoint_sha256;
    const char *graph_sha256;
    const char *classes_sha256;
    const char *generated_header_sha256;
    int batch;
    int input_channels;
    int input_width;
    int input_height;
    int classes;
    int reg_max;
    size_t head_count;
    V8Epoch200HeadIdentity heads[V8_EPOCH200_HEAD_COUNT];
} V8Epoch200Identity;

/* The returned identity is immutable and describes the only accepted graph. */
const V8Epoch200Identity *v8_epoch200_expected_identity(void);

/* Decode the three contiguous NCHW int8 heads emitted by the selected epoch200
 * graph. The caller must pass the independently verified model identity.
 * Identity, graph-shape, configuration-shape, and byte-length failures leave
 * output and out_count untouched. out_count is committed only on success. */
int v8_native_postprocess_epoch200_v1(
    const int8_t *raw_heads, size_t raw_bytes,
    const V8Epoch200Identity *identity,
    const V8DecodeConfig *config,
    V8Detection *output, size_t output_capacity, size_t *out_count);

#endif
