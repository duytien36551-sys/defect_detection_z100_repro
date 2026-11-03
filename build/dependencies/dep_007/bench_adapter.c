/* Fixture-only adapter for the already reviewed warm-overlay benchmark ABI.
 * It consumes the captured INT8 fixture; the float heads remain the baseline.
 * Production integration must use V8Int8Head directly and bind its model scale.
 */
#include "source_project/deployment/board_support/z100_decode_int8_v1/v8_decode_int8.c"
#include "z100_decode_prefilter_bench_scales.h"
extern const uint8_t _binary_raw_heads_bin_start[];
extern const uint8_t _binary_raw_heads_bin_end[];

int v8_decode_raw(const V8Head *heads, size_t head_count,
                  const V8DecodeConfig *config, V8Detection *output,
                  size_t capacity, size_t *count) {
    static const size_t sizes[3]={467200,116800,29200};
    static const int widths[3]={80,40,20}, strides[3]={8,16,32};
    const double scales[3]={Z100_DECODE_BENCH_SCALE_140,
        Z100_DECODE_BENCH_SCALE_151,Z100_DECODE_BENCH_SCALE_162};
    V8Int8Head quantized[3];
    size_t at=0;
    if (count) *count=0;
    if (!heads || head_count!=3 || !config || config->classes!=9 || config->reg_max!=16 ||
        (uintptr_t)_binary_raw_heads_bin_end-(uintptr_t)_binary_raw_heads_bin_start!=613248)
        return V8_DECODE_INVALID;
    for (size_t i=0;i<3;i++) {
        if (heads[i].width!=widths[i] || heads[i].height!=widths[i] || heads[i].stride!=strides[i])
            return V8_DECODE_INVALID;
        quantized[i]=(V8Int8Head){(const int8_t*)_binary_raw_heads_bin_start+at,
            sizes[i],widths[i],widths[i],strides[i],scales[i]};
        at+=sizes[i];
    }
    return v8_decode_int8(quantized,3,config,output,capacity,count);
}
