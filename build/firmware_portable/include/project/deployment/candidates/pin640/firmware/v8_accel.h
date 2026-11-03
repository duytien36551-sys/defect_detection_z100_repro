#ifndef V8_ACCEL_H
#define V8_ACCEL_H

#include <stddef.h>
#include <stdint.h>

/* Input: NCHW signed int8. Weights: OIHW signed int8.
 * Bias and output: raw INT32 accumulator before requantization.
 * This interface has no board address assumptions; platform transport supplies
 * begin/tap/end callbacks. Each tap, including zero padding, is sent in order. */
typedef struct {
    uint16_t input_width, input_height, input_channels, output_channels;
    uint8_t kernel, stride, pad_left, pad_right, pad_top, pad_bottom;
} V8ConvConfig;

typedef struct {
    void *opaque;
    int (*begin)(void *opaque, uint32_t taps, int32_t bias);
    int (*tap)(void *opaque, int8_t activation, int8_t weight);
    int (*end)(void *opaque, int32_t *raw_acc);
} V8ConvBackend;

typedef struct { int64_t acc; uint32_t remaining; } V8SoftwareMac;

enum { V8_ACCEL_OK = 0, V8_ACCEL_ARGUMENT = -1, V8_ACCEL_DIMENSION = -2,
       V8_ACCEL_CAPACITY = -3, V8_ACCEL_BACKEND = -4, V8_ACCEL_OVERFLOW = -5 };

int v8_conv_output_shape(const V8ConvConfig *cfg, uint16_t *width, uint16_t *height);
int v8_conv_run(const V8ConvConfig *cfg, const int8_t *input, size_t input_bytes,
                const int8_t *weights, size_t weight_bytes,
                const int32_t *bias, size_t bias_count,
                int32_t *output, size_t output_count,
                const V8ConvBackend *backend);
V8ConvBackend v8_software_backend(V8SoftwareMac *state);

#endif
