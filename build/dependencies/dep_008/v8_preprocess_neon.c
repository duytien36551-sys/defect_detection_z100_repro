#include "v8_preprocess_neon.h"

#include <math.h>
#include <stdint.h>

#if defined(__ARM_NEON) || defined(__ARM_NEON__)
#include <arm_neon.h>
#define V8_PREPROCESS_USE_NEON 1
#else
#define V8_PREPROCESS_USE_NEON 0
#endif

static int8_t quant_input_reference(double value)
{
    double lo = floor(value), fraction = value - lo;
    double rounded = (fraction > .5 || (fraction == .5 && fmod(lo, 2.0) != 0.0)) ? lo + 1.0 : lo;
    if (rounded > 127.0) rounded = 127.0;
    if (rounded < -127.0) rounded = -127.0;
    return (int8_t)rounded;
}

static uint8_t quant_input_integer(uint8_t code)
{
    const uint32_t x = (uint32_t)code * 127u + 127u;
    return (uint8_t)((x + 1u + (x >> 8)) >> 8);
}

static int formula_matches_scale(double input_scale)
{
    unsigned code;

    if (!isfinite(input_scale) || input_scale <= 0.0)
        return 0;
    for (code = 0; code < 256u; ++code) {
        const double value = ((double)code / 255.0) / input_scale;
        int8_t exact;
        if (!isfinite(value))
            return 0;
        exact = quant_input_reference(value);
        if (exact < 0 || (uint8_t)exact != quant_input_integer((uint8_t)code))
            return 0;
    }
    return 1;
}

static int ranges_overlap_or_overflow(const uint8_t *rgb, const int8_t *nchw)
{
    const uintptr_t rgb_begin = (uintptr_t)rgb;
    const uintptr_t nchw_begin = (uintptr_t)nchw;
    const uintptr_t bytes = (uintptr_t)V8_PREPROCESS_NEON_BYTES;
    uintptr_t rgb_end, nchw_end;

    if (bytes > UINTPTR_MAX - rgb_begin || bytes > UINTPTR_MAX - nchw_begin)
        return 1;
    rgb_end = rgb_begin + bytes;
    nchw_end = nchw_begin + bytes;
    return rgb_begin < nchw_end && nchw_begin < rgb_end;
}

#if V8_PREPROCESS_USE_NEON
static uint8x8_t quantize_eight_neon(uint8x8_t values)
{
    const uint16x8_t product = vmull_u8(values, vdup_n_u8(127u));
    const uint16x8_t x = vaddq_u16(product, vdupq_n_u16(127u));
    const uint16x8_t quotient = vshrq_n_u16(
        vaddq_u16(vaddq_u16(x, vdupq_n_u16(1u)), vshrq_n_u16(x, 8)), 8);
    return vmovn_u16(quotient);
}

static void quantize_store_sixteen(int8_t *destination, uint8x16_t values)
{
    const uint8x8_t low = quantize_eight_neon(vget_low_u8(values));
    const uint8x8_t high = quantize_eight_neon(vget_high_u8(values));
    vst1_s8(destination, vreinterpret_s8_u8(low));
    vst1_s8(destination + 8, vreinterpret_s8_u8(high));
}
#endif

int v8_preprocess_neon_640(const uint8_t *rgb, size_t rgb_bytes,
                           int8_t *nchw, size_t nchw_capacity,
                           double input_scale)
{
    size_t pixel;
    int8_t *red, *green, *blue;

    if (!rgb || !nchw)
        return V8_PREPROCESS_NEON_ERR_NULL;
    if (rgb_bytes != V8_PREPROCESS_NEON_BYTES)
        return V8_PREPROCESS_NEON_ERR_COUNT;
    if (nchw_capacity < V8_PREPROCESS_NEON_BYTES)
        return V8_PREPROCESS_NEON_ERR_CAPACITY;
    if (ranges_overlap_or_overflow(rgb, nchw))
        return V8_PREPROCESS_NEON_ERR_OVERLAP;
    if (!formula_matches_scale(input_scale))
        return V8_PREPROCESS_NEON_ERR_FORMULA;

    red = nchw;
    green = nchw + V8_PREPROCESS_NEON_PIXELS;
    blue = nchw + (2u * V8_PREPROCESS_NEON_PIXELS);
#if V8_PREPROCESS_USE_NEON
    for (pixel = 0; pixel < V8_PREPROCESS_NEON_PIXELS; pixel += 16u) {
        const uint8x16x3_t rgb_values = vld3q_u8(rgb + 3u * pixel);
        quantize_store_sixteen(red + pixel, rgb_values.val[0]);
        quantize_store_sixteen(green + pixel, rgb_values.val[1]);
        quantize_store_sixteen(blue + pixel, rgb_values.val[2]);
    }
#else
    for (pixel = 0; pixel < V8_PREPROCESS_NEON_PIXELS; ++pixel) {
        red[pixel] = (int8_t)quant_input_integer(rgb[3u * pixel]);
        green[pixel] = (int8_t)quant_input_integer(rgb[3u * pixel + 1u]);
        blue[pixel] = (int8_t)quant_input_integer(rgb[3u * pixel + 2u]);
    }
#endif
    return V8_PREPROCESS_NEON_OK;
}

int v8_preprocess_neon_has_neon(void)
{
    return V8_PREPROCESS_USE_NEON;
}
