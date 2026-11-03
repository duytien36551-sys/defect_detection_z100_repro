#include "v8_accel.h"
#include <limits.h>

static int software_begin(void *opaque, uint32_t taps, int32_t bias)
{
    V8SoftwareMac *s = (V8SoftwareMac *)opaque;
    if (!s || !taps) return V8_ACCEL_ARGUMENT;
    s->acc = bias;
    s->remaining = taps;
    return V8_ACCEL_OK;
}

static int software_tap(void *opaque, int8_t activation, int8_t weight)
{
    V8SoftwareMac *s = (V8SoftwareMac *)opaque;
    if (!s || !s->remaining) return V8_ACCEL_BACKEND;
    s->acc += (int32_t)activation * (int32_t)weight;
    --s->remaining;
    return V8_ACCEL_OK;
}

static int software_end(void *opaque, int32_t *raw_acc)
{
    V8SoftwareMac *s = (V8SoftwareMac *)opaque;
    if (!s || !raw_acc || s->remaining) return V8_ACCEL_BACKEND;
    if (s->acc > INT32_MAX || s->acc < INT32_MIN) return V8_ACCEL_OVERFLOW;
    *raw_acc = (int32_t)s->acc;
    return V8_ACCEL_OK;
}

V8ConvBackend v8_software_backend(V8SoftwareMac *state)
{
    V8ConvBackend b = { state, software_begin, software_tap, software_end };
    return b;
}

int v8_conv_output_shape(const V8ConvConfig *cfg, uint16_t *width, uint16_t *height)
{
    uint32_t padded_w, padded_h, ow, oh;
    if (!cfg || !width || !height || !cfg->input_width || !cfg->input_height ||
        !cfg->input_channels || !cfg->output_channels || !cfg->kernel || !cfg->stride)
        return V8_ACCEL_ARGUMENT;
    padded_w = (uint32_t)cfg->input_width + cfg->pad_left + cfg->pad_right;
    padded_h = (uint32_t)cfg->input_height + cfg->pad_top + cfg->pad_bottom;
    if (padded_w < cfg->kernel || padded_h < cfg->kernel) return V8_ACCEL_DIMENSION;
    ow = (padded_w - cfg->kernel) / cfg->stride + 1;
    oh = (padded_h - cfg->kernel) / cfg->stride + 1;
    if (!ow || !oh || ow > UINT16_MAX || oh > UINT16_MAX) return V8_ACCEL_DIMENSION;
    *width = (uint16_t)ow;
    *height = (uint16_t)oh;
    return V8_ACCEL_OK;
}

int v8_conv_run(const V8ConvConfig *cfg, const int8_t *input, size_t input_bytes,
                const int8_t *weights, size_t weight_bytes,
                const int32_t *bias, size_t bias_count,
                int32_t *output, size_t output_count,
                const V8ConvBackend *backend)
{
    uint16_t ow, oh;
    uint64_t need_input, need_weights, need_output, taps;
    uint32_t oy, ox, oc, ky, kx, ic;
    int status;
    if (!cfg || !input || !weights || !bias || !output || !backend ||
        !backend->begin || !backend->tap || !backend->end) return V8_ACCEL_ARGUMENT;
    status = v8_conv_output_shape(cfg, &ow, &oh);
    if (status) return status;
    taps = (uint64_t)cfg->kernel * cfg->kernel * cfg->input_channels;
    need_input = (uint64_t)cfg->input_width * cfg->input_height * cfg->input_channels;
    need_weights = taps * cfg->output_channels;
    need_output = (uint64_t)ow * oh * cfg->output_channels;
    if (taps > UINT32_MAX || need_input > SIZE_MAX || need_weights > SIZE_MAX ||
        need_output > SIZE_MAX) return V8_ACCEL_DIMENSION;
    if (input_bytes < need_input || weight_bytes < need_weights ||
        bias_count < cfg->output_channels || output_count < need_output)
        return V8_ACCEL_CAPACITY;
    for (oy = 0; oy < oh; ++oy) for (ox = 0; ox < ow; ++ox)
    for (oc = 0; oc < cfg->output_channels; ++oc) {
        status = backend->begin(backend->opaque, (uint32_t)taps, bias[oc]);
        if (status) return status;
        for (ic = 0; ic < cfg->input_channels; ++ic)
        for (ky = 0; ky < cfg->kernel; ++ky) for (kx = 0; kx < cfg->kernel; ++kx) {
            int32_t iy = (int32_t)oy * cfg->stride + ky - cfg->pad_top;
            int32_t ix = (int32_t)ox * cfg->stride + kx - cfg->pad_left;
            size_t wi = (((size_t)oc * cfg->input_channels + ic) * cfg->kernel +
                         ky) * cfg->kernel + kx;
            int8_t activation = (ix < 0 || iy < 0 || ix >= cfg->input_width ||
                                 iy >= cfg->input_height) ? 0 :
                                input[((size_t)ic * cfg->input_height + iy) *
                                      cfg->input_width + ix];
            status = backend->tap(backend->opaque, activation, weights[wi]);
            if (status) return status;
        }
        status = backend->end(backend->opaque,
                              &output[((size_t)oc * oh + oy) * ow + ox]);
        if (status) return status;
    }
    return V8_ACCEL_OK;
}
