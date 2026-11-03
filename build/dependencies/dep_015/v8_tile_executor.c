#include "v8_tile_executor.h"
#include "v8_tile_profile.h"
#include <limits.h>

static uint32_t read_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int product_size(size_t a, size_t b, size_t *out)
{
    if (!out || (a && b > SIZE_MAX / a)) return 0;
    *out = a * b;
    return 1;
}

static int next_sequence(V8TileExecutor *e, uint32_t *sequence)
{
    if (!e || !sequence || e->sequence == UINT32_MAX) return -1;
    *sequence = ++e->sequence;
    return 0;
}

static int transfer_load(V8TileExecutor *e, const V8TileConfig *c)
{
    uint32_t sequence;
    int transfer_status;
    V8_TILE_PROFILE_DECLARE(profile_start);
    if (next_sequence(e, &sequence) || c->load_bytes > e->tx_capacity ||
        e->rx_capacity < 20u) return -1;
    V8_TILE_PROFILE_ADD(load_calls, 1u);
    V8_TILE_PROFILE_ADD(load_bytes, c->load_bytes);
    V8_TILE_PROFILE_START(profile_start);
    transfer_status = e->transfer(e->opaque, V8_TILE_OP_LOAD, c->load_reg1,
                                  sequence, c->filter_id, e->tx,
                                  c->load_bytes, e->rx, 20u);
    V8_TILE_PROFILE_STOP_ADD(load_transfer_ticks, profile_start);
    if (transfer_status) return -1;
    if (read_le32(e->rx) != V8_TILE_MAGIC ||
        read_le32(e->rx + 4u) != sequence ||
        read_le32(e->rx + 8u) != c->filter_id ||
        read_le32(e->rx + 12u) != c->load_reg1 ||
        read_le32(e->rx + 16u) != 0u) return -1;
    ++e->loads;
    return 0;
}

static int prepare_run(V8TileExecutor *e, const V8TileConfig *c,
                       size_t tx_capacity, uint32_t *sequence)
{
    if (next_sequence(e, sequence) || c->run_bytes > tx_capacity ||
        c->response_bytes > e->rx_capacity) return -1;
    V8_TILE_PROFILE_ADD(run_calls, 1u);
    V8_TILE_PROFILE_ADD(run_bytes, c->run_bytes);
    return 0;
}

static int parse_run(V8TileExecutor *e, const V8Node *output,
                     const V8TileConfig *c, uint32_t sequence, int32_t *raw,
                     size_t raw_count)
{
    V8TileStatus parse_status;
    V8_TILE_PROFILE_DECLARE(parse_start);
    V8_TILE_PROFILE_START(parse_start);
    parse_status = v8_tile_parse_run_response(e->rx, c->response_bytes,
                                              sequence, output, c, raw,
                                              raw_count);
    V8_TILE_PROFILE_STOP_ADD(response_parse_ticks, parse_start);
    if (parse_status != V8_TILE_OK) return -1;
    ++e->runs;
    return 0;
}

static int transfer_run(V8TileExecutor *e, const V8Node *output,
                        const V8TileConfig *c, int32_t *raw,
                        size_t raw_count)
{
    uint32_t sequence;
    int transfer_status;
    V8_TILE_PROFILE_DECLARE(profile_start);
    if (prepare_run(e, c, e->tx_capacity, &sequence)) return -1;
    V8_TILE_PROFILE_START(profile_start);
    transfer_status = e->transfer(e->opaque, V8_TILE_OP_RUN, c->reg1,
                                  sequence, c->filter_id, e->tx,
                                  c->run_bytes, e->rx, c->response_bytes);
    V8_TILE_PROFILE_STOP_ADD(run_transfer_ticks, profile_start);
    if (transfer_status) return -1;
    return parse_run(e, output, c, sequence, raw, raw_count);
}

static int ranges_disjoint(const void *a, size_t a_bytes,
                           const void *b, size_t b_bytes)
{
    uintptr_t a_start = (uintptr_t)a, b_start = (uintptr_t)b;
    if (!a || !b || a_start > UINTPTR_MAX - a_bytes ||
        b_start > UINTPTR_MAX - b_bytes) return 0;
    return a_start + a_bytes <= b_start || b_start + b_bytes <= a_start;
}

#if V8_TILE_RUN_CACHE
typedef enum {
    V8_TILE_RUN_CACHE_MODE_OFF = 0,
    V8_TILE_RUN_CACHE_MODE_FILL = 1,
    V8_TILE_RUN_CACHE_MODE_REUSE = 2
} V8TileRunCacheMode;

static int round_up_64(size_t bytes, size_t *rounded)
{
    if (!rounded || bytes > SIZE_MAX - 63u) return 0;
    *rounded = (bytes + 63u) & ~(size_t)63u;
    return 1;
}

static int run_cache_eligible(const V8TileExecutor *e,
                              const V8Node *output,
                              const int8_t *activations,
                              const int8_t *weights,
                              const uint8_t *bias_le, const int32_t *raw,
                              size_t spatial, size_t input_count,
                              size_t raw_count, size_t weight_count,
                              size_t bias_bytes, size_t padded_taps,
                              size_t max_sites)
{
    size_t packed_bytes, required_bytes, tile_step_bytes, raw_bytes;
    size_t max_run_sites, max_run_bytes, max_run_rounded_bytes;
    if (!e || !output || output->c <= V8_TILE_LANES || !e->run_cache ||
        !e->run_cache_capacity || ((uintptr_t)e->run_cache & 63u) ||
        !padded_taps || !max_sites ||
        !product_size(spatial, padded_taps, &packed_bytes) ||
        !round_up_64(packed_bytes, &required_bytes) ||
        required_bytes > e->run_cache_capacity ||
        !product_size(max_sites, padded_taps, &tile_step_bytes) ||
        (tile_step_bytes & 63u) ||
        !product_size(raw_count, sizeof(*raw), &raw_bytes))
        return 0;

    max_run_sites = spatial < max_sites ? spatial : max_sites;
    if (!product_size(max_run_sites, padded_taps, &max_run_bytes) ||
        !round_up_64(max_run_bytes, &max_run_rounded_bytes) ||
        max_run_rounded_bytes > e->tx_capacity)
        return 0;

    return ranges_disjoint(e->run_cache, e->run_cache_capacity,
                           e->tx, e->tx_capacity) &&
           ranges_disjoint(e->run_cache, e->run_cache_capacity,
                           e->tx_next, e->tx_next_capacity) &&
           ranges_disjoint(e->run_cache, e->run_cache_capacity,
                           e->rx, e->rx_capacity) &&
           ranges_disjoint(e->run_cache, e->run_cache_capacity,
                           activations, input_count) &&
           ranges_disjoint(e->run_cache, e->run_cache_capacity,
                           raw, raw_bytes) &&
           ranges_disjoint(e->run_cache, e->run_cache_capacity,
                           weights, weight_count) &&
           ranges_disjoint(e->run_cache, e->run_cache_capacity,
                           bias_le, bias_bytes);
}

static int run_cache_slice(V8TileExecutor *e, const V8TileConfig *config,
                           uint8_t **slice, size_t *slice_capacity)
{
    size_t offset, remaining, effective_capacity, rounded_bytes;
    if (!e || !config || !slice || !slice_capacity ||
        !product_size((size_t)config->site_base,
                      (size_t)config->padded_taps, &offset) ||
        offset > e->run_cache_capacity ||
        !round_up_64(config->run_bytes, &rounded_bytes))
        return 0;
    remaining = e->run_cache_capacity - offset;
    effective_capacity = remaining < e->tx_capacity ?
        remaining : e->tx_capacity;
    if (config->run_bytes > effective_capacity ||
        rounded_bytes > effective_capacity || rounded_bytes > remaining ||
        (((uintptr_t)(e->run_cache + offset)) & 63u))
        return 0;
    *slice = e->run_cache + offset;
    *slice_capacity = effective_capacity;
    return 1;
}
#endif

static int overlap_buffers_safe(const V8TileExecutor *e,
                                const int8_t *activations,
                                size_t input_count)
{
    if (!e->begin || !e->finish || !e->cancel || !e->tx_next ||
        !e->tx_next_capacity || !e->tx_capacity || !e->rx_capacity ||
        ((uintptr_t)e->tx & 63u) || ((uintptr_t)e->tx_next & 63u) ||
        ((uintptr_t)e->rx & 63u)) return 0;
    return ranges_disjoint(e->tx, e->tx_capacity, e->tx_next,
                           e->tx_next_capacity) &&
           ranges_disjoint(e->tx, e->tx_capacity, e->rx, e->rx_capacity) &&
           ranges_disjoint(e->tx_next, e->tx_next_capacity,
                           e->rx, e->rx_capacity) &&
           ranges_disjoint(e->tx, e->tx_capacity, activations,
                           input_count) &&
           ranges_disjoint(e->tx_next, e->tx_next_capacity, activations,
                           input_count) &&
           ranges_disjoint(e->rx, e->rx_capacity, activations,
                           input_count);
}

static int execute_overlap_group(V8TileExecutor *e, const V8Node *output,
                                 const V8Node *input,
                                 const int8_t *activations,
                                 size_t input_count, int32_t *raw,
                                 size_t raw_count, uint32_t channel_base,
                                 uint32_t filter_id, size_t spatial,
                                 size_t max_sites,
                                 const V8TileConfig *initial_config
#if V8_TILE_RUN_CACHE
                                 , V8TileRunCacheMode cache_mode
#endif
                                 )
{
    V8TileConfig current_config = *initial_config, next_config;
    uint8_t *current_tx = e->tx, *next_tx = e->tx_next;
    size_t current_capacity = e->tx_capacity;
    size_t next_capacity = e->tx_next_capacity;
    uint32_t current_sequence;
    int current_packed = 0;
#if V8_TILE_RUN_CACHE
    if (cache_mode &&
        !run_cache_slice(e, &current_config, &current_tx,
                         &current_capacity))
        return -1;
    if (cache_mode == V8_TILE_RUN_CACHE_MODE_REUSE) current_packed = 1;
#endif
    V8_TILE_PROFILE_DECLARE(pack_start);
    V8_TILE_PROFILE_DECLARE(transfer_start);

    for (;;) {
        int transfer_status;
        if (!current_packed) {
            V8TileStatus pack_status;
            V8_TILE_PROFILE_START(pack_start);
            pack_status = v8_tile_pack_run(current_tx, current_capacity,
                                           output, input, activations,
                                           input_count, &current_config);
            V8_TILE_PROFILE_STOP_ADD(run_pack_ticks, pack_start);
            if (pack_status != V8_TILE_OK) return -1;
        }
        current_packed = 0;
        if (prepare_run(e, &current_config, current_capacity,
                        &current_sequence)) return -1;
        V8_TILE_PROFILE_START(transfer_start);
        transfer_status = e->begin(e->opaque, V8_TILE_OP_RUN,
                                   current_config.reg1, current_sequence,
                                   current_config.filter_id, current_tx,
                                   current_config.run_bytes, e->rx,
                                   current_config.response_bytes);
        if (transfer_status) {
            V8_TILE_PROFILE_STOP_ADD(run_transfer_ticks, transfer_start);
            return -1;
        }

        for (;;) {
            uint32_t next_site = current_config.site_base +
                                 current_config.sites;
            uint32_t next_sites = 0u;
            int have_next = (size_t)next_site < spatial;
            if (have_next) {
                next_sites = (spatial - next_site) < max_sites ?
                    (uint32_t)(spatial - next_site) : (uint32_t)max_sites;
                if (v8_tile_config_init(output, input, channel_base,
                                        next_site, next_sites, filter_id,
                                        &next_config) != V8_TILE_OK) {
                    (void)e->cancel(e->opaque);
                    V8_TILE_PROFILE_STOP_ADD(run_transfer_ticks,
                                             transfer_start);
                    return -1;
                }
#if V8_TILE_RUN_CACHE
                if (cache_mode) {
                    if (!run_cache_slice(e, &next_config, &next_tx,
                                         &next_capacity) ||
                        (cache_mode == V8_TILE_RUN_CACHE_MODE_FILL &&
                         !ranges_disjoint(current_tx,
                                          (current_config.run_bytes + 63u) &
                                              ~(size_t)63u,
                                          next_tx,
                                          (next_config.run_bytes + 63u) &
                                              ~(size_t)63u))) {
                        (void)e->cancel(e->opaque);
                        V8_TILE_PROFILE_STOP_ADD(run_transfer_ticks,
                                                 transfer_start);
                        return -1;
                    }
                }
#endif
#if V8_TILE_RUN_CACHE
                if (cache_mode != V8_TILE_RUN_CACHE_MODE_REUSE) {
#endif
                {
                    V8TileStatus pack_status;
                    V8_TILE_PROFILE_START(pack_start);
                    pack_status = v8_tile_pack_run(next_tx, next_capacity,
                                                   output, input, activations,
                                                   input_count, &next_config);
                    V8_TILE_PROFILE_STOP_ADD(run_pack_ticks, pack_start);
                    if (pack_status != V8_TILE_OK) {
                        (void)e->cancel(e->opaque);
                        V8_TILE_PROFILE_STOP_ADD(run_transfer_ticks,
                                                 transfer_start);
                        return -1;
                    }
                }
#if V8_TILE_RUN_CACHE
                }
#endif
            }

            transfer_status = e->finish(e->opaque);
            V8_TILE_PROFILE_STOP_ADD(run_transfer_ticks, transfer_start);
            if (transfer_status ||
                parse_run(e, output, &current_config, current_sequence,
                          raw, raw_count)) return -1;
            if (!have_next) return 0;

            {
                uint8_t *tx_swap = current_tx;
                size_t capacity_swap = current_capacity;
                current_tx = next_tx;
                current_capacity = next_capacity;
                next_tx = tx_swap;
                next_capacity = capacity_swap;
            }
            current_config = next_config;
            current_packed = 1;
            break;
        }
    }
}

int v8_tile_execute_conv(void *opaque, const V8Node *output,
                         const V8Node *input, const int8_t *activations,
                         const int8_t *weights, const uint8_t *bias_le,
                         int32_t *raw)
{
    V8TileExecutor *e = (V8TileExecutor *)opaque;
    V8TileConfig c;
    size_t spatial, input_count, raw_count, taps, weight_count, bias_bytes;
    size_t padded_taps, max_sites;
    uint32_t channel_base, site_base, filter_id;
    int use_overlap;
#if V8_TILE_RUN_CACHE
    int use_run_cache = 0, run_cache_complete = 0;
#endif

    if (!e || !e->transfer || !e->tx || !e->rx || !output || !input ||
        !activations || !weights || !bias_le || !raw || !output->c ||
        !output->h || !output->w || !input->c || !input->h || !input->w ||
        !output->kernel || output->groups != 1u ||
        !product_size(output->h, output->w, &spatial) ||
        !product_size(output->c, spatial, &raw_count) ||
        !product_size(input->h, input->w, &input_count) ||
        !product_size(input->c, input_count, &input_count) ||
        !product_size(output->kernel, output->kernel, &taps) ||
        !product_size(input->c, taps, &taps) ||
        !product_size(output->c, taps, &weight_count) ||
        !product_size(output->c, 4u, &bias_bytes) ||
        !taps || taps > V8_TILE_MAX_TAPS || spatial > UINT32_MAX ||
        raw_count > SIZE_MAX / sizeof(int32_t) ||
        e->tx_capacity < (size_t)V8_TILE_LANES * 4u +
                              (size_t)V8_TILE_LANES * taps ||
        e->rx_capacity < 20u)
        return -1;
    (void)weight_count;
    (void)bias_bytes;
    padded_taps = (taps + 3u) & ~(size_t)3u;
    max_sites = V8_TILE_DMA_MAX_BYTES / padded_taps;
    if (max_sites > V8_TILE_MAX_SITES) max_sites = V8_TILE_MAX_SITES;
    if (!max_sites) return -1;
    use_overlap = overlap_buffers_safe(e, activations, input_count);
#if V8_TILE_RUN_CACHE
    if (use_overlap &&
        run_cache_eligible(e, output, activations, weights, bias_le, raw,
                           spatial, input_count, raw_count, weight_count,
                           bias_bytes, padded_taps, max_sites))
        use_run_cache = 1;
#endif
    if (e->ready && !e->ready(e->opaque)) return -1;

    for (channel_base = 0; channel_base < output->c;
         channel_base += V8_TILE_LANES) {
        uint32_t first_sites = spatial < max_sites ?
            (uint32_t)spatial : (uint32_t)max_sites;
        if (e->filter_serial == UINT32_MAX) return -1;
        filter_id = ++e->filter_serial;
        if (v8_tile_config_init(output, input, channel_base, 0u,
                                first_sites, filter_id, &c) != V8_TILE_OK)
            return -1;
        {
            V8TileStatus pack_status;
            V8_TILE_PROFILE_DECLARE(profile_start);
            V8_TILE_PROFILE_START(profile_start);
            pack_status = v8_tile_pack_load(e->tx, e->tx_capacity, output,
                                            input, weights, weight_count,
                                            bias_le, bias_bytes, &c);
            V8_TILE_PROFILE_STOP_ADD(load_pack_ticks, profile_start);
            if (pack_status != V8_TILE_OK || transfer_load(e, &c)) return -1;
        }

        if (use_overlap) {
            if (execute_overlap_group(e, output, input, activations,
                                      input_count, raw, raw_count,
                                      channel_base, filter_id, spatial,
                                      max_sites, &c
#if V8_TILE_RUN_CACHE
                                      , use_run_cache ?
                                            (run_cache_complete ?
                                             V8_TILE_RUN_CACHE_MODE_REUSE :
                                             V8_TILE_RUN_CACHE_MODE_FILL) :
                                            V8_TILE_RUN_CACHE_MODE_OFF
#endif
                                      )) return -1;
#if V8_TILE_RUN_CACHE
            if (use_run_cache && !run_cache_complete)
                run_cache_complete = 1;
#endif
        } else {
            for (site_base = 0; site_base < spatial;) {
                uint32_t sites = (spatial - site_base) < max_sites ?
                    (uint32_t)(spatial - site_base) : (uint32_t)max_sites;
                if (v8_tile_config_init(output, input, channel_base,
                                        site_base, sites, filter_id, &c) !=
                    V8_TILE_OK)
                    return -1;
                {
                    V8TileStatus pack_status;
                    V8_TILE_PROFILE_DECLARE(profile_start);
                    V8_TILE_PROFILE_START(profile_start);
                    pack_status = v8_tile_pack_run(e->tx, e->tx_capacity,
                                                   output, input, activations,
                                                   input_count, &c);
                    V8_TILE_PROFILE_STOP_ADD(run_pack_ticks, profile_start);
                    if (pack_status != V8_TILE_OK ||
                        transfer_run(e, output, &c, raw, raw_count)) return -1;
                }
                site_base += sites;
            }
        }
    }
    return 0;
}
