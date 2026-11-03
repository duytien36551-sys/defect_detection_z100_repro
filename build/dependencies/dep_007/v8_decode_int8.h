#ifndef V8_DECODE_INT8_PRIVATE_H
#define V8_DECODE_INT8_PRIVATE_H
#include <stdint.h>
#include "v8_decode.h"

/* Private candidate: immutable INT8 CHW heads and exact binary64 graph scales.
 * Conversion follows production (float)((double)code*scale), then the existing
 * sigmoid/DFL/NMS expressions. No global float-head buffer is constructed. */
typedef struct {
    const int8_t *data;
    size_t data_bytes;
    int width, height, stride;
    double scale;
} V8Int8Head;

int v8_decode_int8(const V8Int8Head *heads, size_t head_count,
                   const V8DecodeConfig *config, V8Detection *output,
                   size_t output_capacity, size_t *out_count);
#endif
