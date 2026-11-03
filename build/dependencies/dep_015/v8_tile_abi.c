#include "v8_tile_abi.h"

#include <limits.h>
#include <string.h>

static int size_mul(size_t a, size_t b, size_t *out)
{
    if (!out || (b != 0u && a > SIZE_MAX / b)) return 0;
    *out = a * b;
    return 1;
}

static int node_tensor_sizes(const V8Node *node, size_t *spatial,
                             size_t *elements)
{
    size_t hw;
    if (!node || !spatial || !elements || !node->c || !node->h || !node->w)
        return 0;
    if (!size_mul((size_t)node->h, (size_t)node->w, &hw) ||
        !size_mul((size_t)node->c, hw, elements)) return 0;
    *spatial = hw;
    return 1;
}

static int coordinate_math_fits(uint32_t output_extent, uint32_t stride,
                                uint32_t kernel, uint32_t padding)
{
    uint64_t base;
    uint64_t max_coordinate;
    if (!output_extent || !stride || !kernel) return 0;
    base = (uint64_t)(output_extent - 1u) * (uint64_t)stride;
    if (base > UINT64_MAX - (uint64_t)(kernel - 1u)) return 0;
    max_coordinate = base + (uint64_t)(kernel - 1u);
    return max_coordinate <= (uint64_t)INT64_MAX - (uint64_t)padding;
}

static uint32_t config_word(uint32_t taps, uint32_t lanes, uint32_t sites)
{
    /* R1: taps[15:0], lanes[22:16], reserved bit 23, sites[30:24], bit 31 zero. */
    return (taps & 0xffffu) | ((lanes & 0x7fu) << 16) |
           ((sites & 0x7fu) << 24);
}

int v8_tile_control_word(V8TileOpcode opcode, int abort_held, int start,
                         uint32_t *word_out)
{
    uint32_t word;
    if (!word_out || (opcode != V8_TILE_OP_PROBE &&
                      opcode != V8_TILE_OP_LOAD && opcode != V8_TILE_OP_RUN) ||
        (abort_held != 0 && abort_held != 1) ||
        (start != 0 && start != 1)) return V8_TILE_EINVAL;
    word = ((uint32_t)opcode << 4) |
           (abort_held ? V8_TILE_R0_ABORT : 0u) |
           (start ? V8_TILE_R0_START : 0u);
    *word_out = word;
    return V8_TILE_OK;
}

int v8_tile_config_init(const V8Node *output, const V8Node *input,
                        uint32_t output_channel_base, uint32_t site_base,
                        uint32_t site_count, uint32_t filter_id,
                        V8TileConfig *config_out)
{
    V8TileConfig config;
    size_t output_spatial, output_elements;
    size_t input_spatial, input_elements;
    size_t kernel_area, taps, padded_taps, max_sites;
    size_t weight_count, bias_bytes;
    uint64_t max_sites_by_dma;

    if (!output || !input || !config_out || output->op != V8_CONV ||
        !output->c || !output->h || !output->w || !input->c || !input->h ||
        !input->w || !output->kernel || !output->stride ||
        output->groups != 1u || !site_count ||
        output_channel_base >= output->c ||
        !node_tensor_sizes(output, &output_spatial, &output_elements) ||
        !node_tensor_sizes(input, &input_spatial, &input_elements) ||
        !coordinate_math_fits(output->h, output->stride, output->kernel,
                              output->padding) ||
        !coordinate_math_fits(output->w, output->stride, output->kernel,
                              output->padding)) return V8_TILE_EINVAL;
    (void)input_spatial;
    (void)input_elements;
    (void)output_elements;

    if ((uint64_t)site_base + (uint64_t)site_count >
        (uint64_t)output_spatial) return V8_TILE_EINVAL;
    if (!size_mul((size_t)output->kernel, (size_t)output->kernel,
                  &kernel_area) ||
        !size_mul((size_t)input->c, kernel_area, &taps))
        return V8_TILE_EOVERFLOW;
    if (!taps || taps > V8_TILE_MAX_TAPS) return V8_TILE_ECAPACITY;
    padded_taps = (taps + 3u) & ~(size_t)3u;
    max_sites_by_dma = V8_TILE_DMA_MAX_BYTES / padded_taps;
    max_sites = max_sites_by_dma < V8_TILE_MAX_SITES
                    ? (size_t)max_sites_by_dma : V8_TILE_MAX_SITES;
    if ((size_t)site_count > max_sites) return V8_TILE_ECAPACITY;

    memset(&config, 0, sizeof(config));
    config.taps = (uint32_t)taps;
    config.lanes = output->c - output_channel_base;
    if (config.lanes > V8_TILE_LANES) config.lanes = V8_TILE_LANES;
    config.sites = site_count;
    config.padded_taps = (uint32_t)padded_taps;
    config.output_channel_base = output_channel_base;
    config.site_base = site_base;
    config.filter_id = filter_id;
    config.load_reg1 = config_word(config.taps, config.lanes, 0u);
    config.reg1 = config_word(config.taps, config.lanes, config.sites);

    if (!size_mul((size_t)output->c, taps, &weight_count) ||
        !size_mul((size_t)output->c, 4u, &bias_bytes))
        return V8_TILE_EOVERFLOW;
    (void)weight_count;
    config.load_bytes = V8_TILE_LANES * 4u + V8_TILE_LANES * taps;
    if (!size_mul(padded_taps, (size_t)site_count, &config.run_bytes))
        return V8_TILE_EOVERFLOW;
    if (config.run_bytes > V8_TILE_DMA_MAX_BYTES ||
        !size_mul((size_t)site_count, (size_t)config.lanes,
                  &config.response_bytes) ||
        !size_mul(config.response_bytes + 5u, 4u, &config.response_bytes))
        return V8_TILE_EOVERFLOW;
    (void)bias_bytes;
    if (config.load_bytes > V8_TILE_DMA_MAX_BYTES)
        return V8_TILE_ECAPACITY;

    *config_out = config;
    return V8_TILE_OK;
}

static int config_matches_nodes(const V8Node *output, const V8Node *input,
                                const V8TileConfig *config)
{
    V8TileConfig expected;
    if (!config || v8_tile_config_init(output, input,
                                       config->output_channel_base,
                                       config->site_base, config->sites,
                                       config->filter_id, &expected) !=
                       V8_TILE_OK) return 0;
    return config->taps == expected.taps &&
           config->lanes == expected.lanes &&
           config->sites == expected.sites &&
           config->padded_taps == expected.padded_taps &&
           config->output_channel_base == expected.output_channel_base &&
           config->site_base == expected.site_base &&
           config->filter_id == expected.filter_id &&
           config->load_reg1 == expected.load_reg1 &&
           config->reg1 == expected.reg1 &&
           config->load_bytes == expected.load_bytes &&
           config->run_bytes == expected.run_bytes &&
           config->response_bytes == expected.response_bytes;
}

int v8_tile_pack_load(uint8_t *dst, size_t dst_capacity,
                      const V8Node *output, const V8Node *input,
                      const int8_t *weights, size_t weights_count,
                      const uint8_t *bias_le, size_t bias_bytes,
                      const V8TileConfig *config)
{
    size_t required_weights, required_bias;
    uint32_t lane, tap;
    if (!dst || !output || !input || !weights || !bias_le || !config ||
        !config_matches_nodes(output, input, config)) return V8_TILE_EINVAL;
    if (!size_mul((size_t)output->c, (size_t)config->taps,
                  &required_weights) ||
        !size_mul((size_t)output->c, 4u, &required_bias))
        return V8_TILE_EOVERFLOW;
    if (weights_count < required_weights || bias_bytes < required_bias)
        return V8_TILE_ECAPACITY;
    if (dst_capacity < config->load_bytes) return V8_TILE_ECAPACITY;

    memset(dst, 0, config->load_bytes);
    for (lane = 0u; lane < config->lanes; ++lane) {
        uint32_t channel = config->output_channel_base + lane;
        memcpy(dst + 4u * lane, bias_le + 4u * channel, 4u);
    }
    for (tap = 0u; tap < config->taps; ++tap) {
        uint32_t lane_index;
        size_t row = V8_TILE_LANES * 4u + (size_t)tap * V8_TILE_LANES;
        for (lane_index = 0u; lane_index < config->lanes; ++lane_index) {
            size_t weight_at =
                (size_t)(config->output_channel_base + lane_index) *
                    config->taps + tap;
            dst[row + lane_index] = (uint8_t)weights[weight_at];
        }
    }
    return V8_TILE_OK;
}

int v8_tile_pack_run(uint8_t *dst, size_t dst_capacity,
                     const V8Node *output, const V8Node *input,
                     const int8_t *input_nchw, size_t input_count,
                     const V8TileConfig *config)
{
    size_t input_spatial, input_elements, output_spatial, output_elements;
    uint32_t site_offset;
    if (!dst || !output || !input || !input_nchw || !config ||
        !config_matches_nodes(output, input, config)) return V8_TILE_EINVAL;
    if (!node_tensor_sizes(input, &input_spatial, &input_elements) ||
        !node_tensor_sizes(output, &output_spatial, &output_elements))
        return V8_TILE_EOVERFLOW;
    (void)output_elements;
    if (input_count < input_elements) return V8_TILE_ECAPACITY;
    if (dst_capacity < config->run_bytes) return V8_TILE_ECAPACITY;

    /* YOLOv8's 1x1 convolutions dominate the activation pack volume. Keep
     * channel-major gathers simple when no coordinate clipping is needed. */
    if (output->kernel == 1u && output->stride == 1u &&
        output->padding == 0u && input->h == output->h &&
        input->w == output->w) {
#if defined(V8_TILE_PACK_LOCALITY) && V8_TILE_PACK_LOCALITY
        uint32_t block_start;
        for (block_start = 0u; block_start < config->sites;
             block_start += 4u) {
            uint32_t active_sites = config->sites - block_start;
            uint32_t block_site, ic;
            if (active_sites > 4u) active_sites = 4u;
            for (block_site = 0u; block_site < active_sites; ++block_site) {
                size_t row = (size_t)(block_start + block_site) *
                             config->padded_taps;
                if (config->padded_taps > input->c)
                    memset(dst + row + input->c, 0,
                           config->padded_taps - input->c);
            }
            for (ic = 0u; ic < input->c; ++ic) {
                size_t channel_base = (size_t)ic * input_spatial;
                for (block_site = 0u; block_site < active_sites;
                     ++block_site) {
                    size_t site_offset = (size_t)block_start + block_site;
                    size_t site = (size_t)config->site_base + site_offset;
                    size_t row = site_offset * config->padded_taps;
                    dst[row + ic] = (uint8_t)input_nchw[channel_base + site];
                }
            }
        }
#else
        for (site_offset = 0u; site_offset < config->sites; ++site_offset) {
            size_t site = (size_t)config->site_base + site_offset;
            size_t at = (size_t)site_offset * config->padded_taps;
            uint32_t ic;
            for (ic = 0u; ic < input->c; ++ic)
                dst[at + ic] = (uint8_t)input_nchw[(size_t)ic *
                                                   input_spatial + site];
            for (ic = input->c; ic < config->padded_taps; ++ic)
                dst[at + ic] = 0;
        }
#endif
        return V8_TILE_OK;
    }

    /* Calculate edge clipping once per site, then reuse the nine source
     * positions across all channels. This avoids repeated 64-bit coordinate
     * arithmetic in the inner tap loop of every 3x3 convolution. */
    if (output->kernel == 3u) {
#if defined(V8_TILE_PACK_3X3_INTERIOR) && V8_TILE_PACK_3X3_INTERIOR
        if (output->stride == 1u && output->padding == 1u &&
            input->h == output->h && input->w == output->w) {
            for (site_offset = 0u; site_offset < config->sites;
                 ++site_offset) {
                size_t output_site = (size_t)config->site_base + site_offset;
                uint32_t oy = (uint32_t)(output_site / output->w);
                uint32_t ox = (uint32_t)(output_site % output->w);
                size_t at = (size_t)site_offset * config->padded_taps;
                uint32_t ic;
                if (oy != 0u && oy < input->h - 1u && ox != 0u &&
                    ox < input->w - 1u) {
                    size_t source_site = output_site - input->w - 1u;
                    uint8_t *packed = dst + at;
                    for (ic = 0u; ic < input->c; ++ic) {
                        const int8_t *source = input_nchw +
                            (size_t)ic * input_spatial + source_site;
                        *packed++ = (uint8_t)source[0];
                        *packed++ = (uint8_t)source[1];
                        *packed++ = (uint8_t)source[2];
                        source += input->w;
                        *packed++ = (uint8_t)source[0];
                        *packed++ = (uint8_t)source[1];
                        *packed++ = (uint8_t)source[2];
                        source += input->w;
                        *packed++ = (uint8_t)source[0];
                        *packed++ = (uint8_t)source[1];
                        *packed++ = (uint8_t)source[2];
                    }
                    for (ic = config->taps; ic < config->padded_taps; ++ic)
                        *packed++ = 0u;
                    continue;
                }

                /* Keep border sites on the original clipped-coordinate path. */
                {
                    int64_t base_y = (int64_t)oy * output->stride -
                                     output->padding;
                    int64_t base_x = (int64_t)ox * output->stride -
                                     output->padding;
                    size_t source_offset[9];
                    uint8_t in_bounds[9];
                    uint32_t ky, kx, tap;
                    for (ky = 0u; ky < 3u; ++ky)
                        for (kx = 0u; kx < 3u; ++kx) {
                            int64_t y = base_y + ky, x = base_x + kx;
                            tap = ky * 3u + kx;
                            in_bounds[tap] = y >= 0 && x >= 0 &&
                                y < (int64_t)input->h &&
                                x < (int64_t)input->w;
                            source_offset[tap] = in_bounds[tap] ?
                                (size_t)y * input->w + (size_t)x : 0u;
                        }
                    for (ic = 0u; ic < input->c; ++ic) {
                        size_t channel_base = (size_t)ic * input_spatial;
                        uint32_t tap;
                        for (tap = 0u; tap < 9u; ++tap)
                            dst[at++] = in_bounds[tap] ?
                                (uint8_t)input_nchw[channel_base +
                                                   source_offset[tap]] : 0u;
                    }
                    while (at < (size_t)(site_offset + 1u) *
                                    config->padded_taps)
                        dst[at++] = 0u;
                }
            }
            return V8_TILE_OK;
        }
#endif
#if defined(V8_TILE_PACK_3X3_STRIDE2) && V8_TILE_PACK_3X3_STRIDE2
        if (output->stride == 2u && output->padding == 1u) {
            for (site_offset = 0u; site_offset < config->sites;
                 ++site_offset) {
                size_t output_site = (size_t)config->site_base + site_offset;
                uint32_t oy = (uint32_t)(output_site / output->w);
                uint32_t ox = (uint32_t)(output_site % output->w);
                int64_t base_y = (int64_t)oy * output->stride -
                                 output->padding;
                int64_t base_x = (int64_t)ox * output->stride -
                                 output->padding;
                size_t at = (size_t)site_offset * config->padded_taps;
                uint32_t ic;
                if (base_y >= 0 && base_x >= 0 &&
                    base_y + 2 < (int64_t)input->h &&
                    base_x + 2 < (int64_t)input->w) {
                    size_t source_site = (size_t)base_y * input->w +
                                         (size_t)base_x;
                    uint8_t *packed = dst + at;
                    for (ic = 0u; ic < input->c; ++ic) {
                        const int8_t *source = input_nchw +
                            (size_t)ic * input_spatial + source_site;
                        *packed++ = (uint8_t)source[0];
                        *packed++ = (uint8_t)source[1];
                        *packed++ = (uint8_t)source[2];
                        source += input->w;
                        *packed++ = (uint8_t)source[0];
                        *packed++ = (uint8_t)source[1];
                        *packed++ = (uint8_t)source[2];
                        source += input->w;
                        *packed++ = (uint8_t)source[0];
                        *packed++ = (uint8_t)source[1];
                        *packed++ = (uint8_t)source[2];
                    }
                    for (ic = config->taps; ic < config->padded_taps; ++ic)
                        *packed++ = 0u;
                    continue;
                }

                /* Keep border sites on the original clipped-coordinate path. */
                {
                    size_t source_offset[9];
                    uint8_t in_bounds[9];
                    uint32_t ky, kx, tap;
                    for (ky = 0u; ky < 3u; ++ky)
                        for (kx = 0u; kx < 3u; ++kx) {
                            int64_t y = base_y + ky, x = base_x + kx;
                            tap = ky * 3u + kx;
                            in_bounds[tap] = y >= 0 && x >= 0 &&
                                y < (int64_t)input->h &&
                                x < (int64_t)input->w;
                            source_offset[tap] = in_bounds[tap] ?
                                (size_t)y * input->w + (size_t)x : 0u;
                        }
                    for (ic = 0u; ic < input->c; ++ic) {
                        size_t channel_base = (size_t)ic * input_spatial;
                        uint32_t tap;
                        for (tap = 0u; tap < 9u; ++tap)
                            dst[at++] = in_bounds[tap] ?
                                (uint8_t)input_nchw[channel_base +
                                                   source_offset[tap]] : 0u;
                    }
                    while (at < (size_t)(site_offset + 1u) *
                                    config->padded_taps)
                        dst[at++] = 0u;
                }
            }
            return V8_TILE_OK;
        }
#endif
#if defined(V8_TILE_PACK_LOCALITY) && V8_TILE_PACK_LOCALITY
        uint32_t block_start;
        for (block_start = 0u; block_start < config->sites;
             block_start += 4u) {
            size_t source_offset[4][9];
            uint8_t in_bounds[4][9];
            uint32_t active_sites = config->sites - block_start;
            uint32_t block_site, ky, kx, ic, tap;
            if (active_sites > 4u) active_sites = 4u;
            for (block_site = 0u; block_site < active_sites; ++block_site) {
                size_t output_site = (size_t)config->site_base +
                                     block_start + block_site;
                uint32_t oy = (uint32_t)(output_site / output->w);
                uint32_t ox = (uint32_t)(output_site % output->w);
                int64_t base_y = (int64_t)oy * output->stride -
                                 output->padding;
                int64_t base_x = (int64_t)ox * output->stride -
                                 output->padding;
                for (ky = 0u; ky < 3u; ++ky)
                    for (kx = 0u; kx < 3u; ++kx) {
                        int64_t y = base_y + ky, x = base_x + kx;
                        tap = ky * 3u + kx;
                        in_bounds[block_site][tap] =
                            y >= 0 && x >= 0 && y < (int64_t)input->h &&
                            x < (int64_t)input->w;
                        source_offset[block_site][tap] =
                            in_bounds[block_site][tap] ?
                                (size_t)y * input->w + (size_t)x : 0u;
                    }
            }
            for (ic = 0u; ic < input->c; ++ic) {
                size_t channel_base = (size_t)ic * input_spatial;
                for (block_site = 0u; block_site < active_sites;
                     ++block_site) {
                    size_t row =
                        ((size_t)block_start + block_site) *
                        config->padded_taps + (size_t)ic * 9u;
                    for (tap = 0u; tap < 9u; ++tap)
                        dst[row + tap] = in_bounds[block_site][tap] ?
                            (uint8_t)input_nchw[
                                channel_base +
                                source_offset[block_site][tap]] : 0u;
                }
            }
            for (block_site = 0u; block_site < active_sites; ++block_site) {
                size_t row = ((size_t)block_start + block_site) *
                             config->padded_taps;
                if (config->padded_taps > config->taps)
                    memset(dst + row + config->taps, 0,
                           config->padded_taps - config->taps);
            }
        }
#else
        for (site_offset = 0u; site_offset < config->sites; ++site_offset) {
            size_t output_site = (size_t)config->site_base + site_offset;
            uint32_t oy = (uint32_t)(output_site / output->w);
            uint32_t ox = (uint32_t)(output_site % output->w);
            int64_t base_y = (int64_t)oy * output->stride - output->padding;
            int64_t base_x = (int64_t)ox * output->stride - output->padding;
            size_t source_offset[9];
            uint8_t in_bounds[9];
            size_t at = (size_t)site_offset * config->padded_taps;
            uint32_t ky, kx, ic, tap;
            for (ky = 0; ky < 3u; ++ky)
                for (kx = 0; kx < 3u; ++kx) {
                    int64_t y = base_y + ky, x = base_x + kx;
                    tap = ky * 3u + kx;
                    in_bounds[tap] = y >= 0 && x >= 0 &&
                        y < (int64_t)input->h && x < (int64_t)input->w;
                    source_offset[tap] = in_bounds[tap] ?
                        (size_t)y * input->w + (size_t)x : 0u;
                }
            for (ic = 0u; ic < input->c; ++ic) {
                size_t channel_base = (size_t)ic * input_spatial;
                for (tap = 0u; tap < 9u; ++tap)
                    dst[at++] = in_bounds[tap] ?
                        (uint8_t)input_nchw[channel_base +
                                             source_offset[tap]] : 0u;
            }
            while (at < (size_t)(site_offset + 1u) * config->padded_taps)
                dst[at++] = 0;
        }
#endif
        return V8_TILE_OK;
    }

    for (site_offset = 0u; site_offset < config->sites; ++site_offset) {
        size_t output_site = (size_t)config->site_base + site_offset;
        uint32_t oy = (uint32_t)(output_site / output->w);
        uint32_t ox = (uint32_t)(output_site % output->w);
        size_t at = (size_t)site_offset * config->padded_taps;
        uint32_t ic, ky, kx;
        memset(dst + at, 0, config->padded_taps);
        for (ic = 0u; ic < input->c; ++ic) {
            for (ky = 0u; ky < output->kernel; ++ky) {
                int64_t iy = (int64_t)oy * output->stride + ky -
                             (int64_t)output->padding;
                for (kx = 0u; kx < output->kernel; ++kx) {
                    int64_t ix = (int64_t)ox * output->stride + kx -
                                 (int64_t)output->padding;
                    int8_t activation = 0;
                    if (iy >= 0 && ix >= 0 && iy < (int64_t)input->h &&
                        ix < (int64_t)input->w) {
                        size_t input_at =
                            (size_t)ic * input_spatial +
                            (size_t)iy * input->w + (size_t)ix;
                        activation = input_nchw[input_at];
                    }
                    dst[at++] = (uint8_t)activation;
                }
            }
        }
    }
    return V8_TILE_OK;
}

static uint32_t read_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int32_t signed_from_u32(uint32_t value)
{
    if (value <= (uint32_t)INT32_MAX) return (int32_t)value;
    return -1 - (int32_t)(UINT32_MAX - value);
}

static int config_is_valid_for_output(const V8TileConfig *config,
                                      const V8Node *output,
                                      size_t *spatial_out,
                                      size_t *raw_count_out)
{
    size_t spatial, raw_count, payload_words, expected_response;
    size_t padded;
    uint64_t site_end;
    if (!config || !output || output->op != V8_CONV || !output->c ||
        !output->h || !output->w || !config->taps ||
        config->taps > V8_TILE_MAX_TAPS || !config->lanes ||
        config->lanes > V8_TILE_LANES || !config->sites ||
        config->sites > V8_TILE_MAX_SITES ||
        config->output_channel_base >= output->c) return 0;
    padded = ((size_t)config->taps + 3u) & ~(size_t)3u;
    if (config->padded_taps != padded ||
        config->lanes > output->c - config->output_channel_base ||
        config->reg1 != config_word(config->taps, config->lanes,
                                    config->sites) ||
        config->load_reg1 != config_word(config->taps, config->lanes, 0u) ||
        config->load_bytes != (size_t)V8_TILE_LANES * 4u +
                                  (size_t)V8_TILE_LANES * config->taps ||
        !size_mul(padded, (size_t)config->sites, &payload_words) ||
        config->run_bytes != payload_words ||
        config->run_bytes > V8_TILE_DMA_MAX_BYTES ||
        !size_mul((size_t)config->sites, (size_t)config->lanes,
                  &payload_words) ||
        !size_mul(payload_words + 5u, 4u, &expected_response) ||
        config->response_bytes != expected_response ||
        !node_tensor_sizes(output, &spatial, &raw_count)) return 0;
    site_end = (uint64_t)config->site_base + config->sites;
    if (site_end > (uint64_t)spatial) return 0;
    if (config->load_bytes > V8_TILE_DMA_MAX_BYTES) return 0;
    *spatial_out = spatial;
    *raw_count_out = raw_count;
    return 1;
}

int v8_tile_parse_run_response(const uint8_t *response, size_t response_bytes,
                               uint32_t sequence, const V8Node *output,
                               const V8TileConfig *config,
                               int32_t *raw, size_t raw_count)
{
    size_t spatial, expected_raw_count, payload_words;
    size_t payload_offset = 16u;
    size_t trailer_offset;
    uint32_t site, lane;
    if (!response || !output || !config || !raw) return V8_TILE_EINVAL;
    if (!config_is_valid_for_output(config, output, &spatial,
                                    &expected_raw_count))
        return V8_TILE_EINVAL;
    if (raw_count < expected_raw_count) return V8_TILE_ECAPACITY;
    if (response_bytes != config->response_bytes) return V8_TILE_EFRAME;
    if (read_le32(response) != V8_TILE_MAGIC ||
        read_le32(response + 4u) != sequence ||
        read_le32(response + 8u) != config->filter_id ||
        read_le32(response + 12u) != config->reg1)
        return V8_TILE_EFRAME;
    payload_words = (size_t)config->sites * config->lanes;
    trailer_offset = payload_offset + payload_words * 4u;
    if (trailer_offset + 4u != response_bytes) return V8_TILE_EFRAME;
    if (read_le32(response + trailer_offset) != 0u) return V8_TILE_EDEVICE;

    /* All protocol, bounds, and status checks are complete before this loop. */
#if defined(V8_TILE_PARSE_CHANNEL) && V8_TILE_PARSE_CHANNEL
    for (lane = 0u; lane < config->lanes; ++lane) {
        size_t raw_index =
            ((size_t)config->output_channel_base + lane) * spatial +
            config->site_base;
        const uint8_t *payload = response + payload_offset +
            (size_t)lane * sizeof(uint32_t);
        for (site = 0u; site < config->sites; ++site) {
            raw[raw_index] = signed_from_u32(read_le32(payload));
            ++raw_index;
            /* Do not form a pointer beyond the response on the final site. */
            if (site + 1u < config->sites)
                payload += (size_t)config->lanes * sizeof(uint32_t);
        }
    }
#elif defined(V8_TILE_PARSE_WALK) && V8_TILE_PARSE_WALK
    {
        size_t first_channel =
            (size_t)config->output_channel_base * spatial;
        for (site = 0u; site < config->sites; ++site) {
            size_t raw_index = first_channel + config->site_base + site;
            const uint8_t *payload = response + payload_offset +
                (size_t)site * config->lanes * sizeof(uint32_t);
            for (lane = 0u; lane < config->lanes; ++lane) {
                raw[raw_index] = signed_from_u32(read_le32(payload));
                payload += sizeof(uint32_t);
                raw_index += spatial;
            }
        }
    }
#else
    for (site = 0u; site < config->sites; ++site) {
        for (lane = 0u; lane < config->lanes; ++lane) {
            size_t word_index = (size_t)site * config->lanes + lane;
            size_t raw_index =
                ((size_t)(config->output_channel_base + lane) * spatial) +
                config->site_base + site;
            uint32_t bits = read_le32(response + payload_offset +
                                      word_index * 4u);
            raw[raw_index] = signed_from_u32(bits);
        }
    }
#endif
    return V8_TILE_OK;
}
