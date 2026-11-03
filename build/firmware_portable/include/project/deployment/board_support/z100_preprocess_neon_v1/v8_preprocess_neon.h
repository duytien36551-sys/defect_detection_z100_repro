#ifndef V8_PREPROCESS_NEON_H
#define V8_PREPROCESS_NEON_H

#include <stddef.h>
#include <stdint.h>

#define V8_PREPROCESS_NEON_INPUT_SIZE 640u
#define V8_PREPROCESS_NEON_PIXELS (V8_PREPROCESS_NEON_INPUT_SIZE * V8_PREPROCESS_NEON_INPUT_SIZE)
#define V8_PREPROCESS_NEON_PLANES 3u
#define V8_PREPROCESS_NEON_BYTES (V8_PREPROCESS_NEON_PLANES * V8_PREPROCESS_NEON_PIXELS)

enum {
    V8_PREPROCESS_NEON_OK = 0,
    V8_PREPROCESS_NEON_ERR_NULL = -1,
    V8_PREPROCESS_NEON_ERR_COUNT = -2,
    V8_PREPROCESS_NEON_ERR_CAPACITY = -3,
    V8_PREPROCESS_NEON_ERR_OVERLAP = -4,
    V8_PREPROCESS_NEON_ERR_FORMULA = -5
};

/*
 * Convert the fixed PIN640 RGB HWC uint8 input to signed INT8 CHW planes.
 * input_scale must be the active graph's input scale. Before writing output,
 * the function verifies that the exact production double formula agrees for
 * every byte value with the integer formula used by the scalar/NEON kernels.
 * All buffers are caller-owned. Any error returns before reading RGB or
 * changing the output.
 */
int v8_preprocess_neon_640(const uint8_t *rgb, size_t rgb_bytes,
                           int8_t *nchw, size_t nchw_capacity,
                           double input_scale);

/* Reports whether this compilation selected the AArch32 NEON implementation. */
int v8_preprocess_neon_has_neon(void);

#endif
