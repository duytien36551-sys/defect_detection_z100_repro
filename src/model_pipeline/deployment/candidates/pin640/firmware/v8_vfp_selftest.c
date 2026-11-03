#include "v8_vfp_requant.h"

#include <math.h>
#include <string.h>

#define V8_VFP_UNIFORM_SAMPLES 1000000u
#define V8_VFP_MODEL_RANDOM_SAMPLES 100000u
#define V8_VFP_MODEL_BOUNDARY_ROUNDS 8u
#define V8_VFP_MODEL_BOUNDARY_MIN_COMPARISONS 100000u

uint32_t v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_WORDS]
    __attribute__((aligned(64)));

static int8_t reference_quant(double x)
{
    double lo = floor(x);
    double fraction = x - lo;
    double value = (fraction > 0.5 ||
                    (fraction == 0.5 && fmod(lo, 2.0) != 0.0))
                       ? lo + 1.0 : lo;
    if (value > 127.0) value = 127.0;
    if (value < -127.0) value = -127.0;
    return (int8_t)value;
}

/* This matches the runtime's fallback for values outside the VCVTR-safe set. */
static int8_t conv_quant_fallback(double x)
{
    int32_t whole;
    double fraction;
    if (x >= 127.0) return 127;
    if (x <= -127.0) return -127;
    if (!isfinite(x)) return reference_quant(x);
    whole = (int32_t)x;
    fraction = x - whole;
    if (fraction > 0.5 || (fraction == 0.5 && whole % 2 != 0)) whole++;
    else if (fraction < -0.5 ||
             (fraction == -0.5 && whole % 2 != 0)) whole--;
    return (int8_t)whole;
}

static int8_t candidate_quant(double x)
{
    if (!isfinite(x)) return conv_quant_fallback(x);
    return v8_vfp_requant_round_saturated_finite(x);
}

static void compare_value(double x, uint32_t *comparisons,
                          uint32_t *mismatches, uint32_t *nonfinite)
{
    int8_t expected = reference_quant(x);
    int8_t actual = candidate_quant(x);
    if (*comparisons != UINT32_MAX) ++*comparisons;
    if (!isfinite(x) && *nonfinite != UINT32_MAX) ++*nonfinite;
    if (actual != expected && *mismatches != UINT32_MAX) ++*mismatches;
}

static uint32_t next_u32(uint32_t *state)
{
    uint32_t value = *state;
    value ^= value << 13;
    value ^= value >> 17;
    value ^= value << 5;
    *state = value;
    return value;
}

static double model_f64(const uint8_t *bytes)
{
    double value;
    memcpy(&value, bytes, sizeof(value));
    return value;
}

static void record_status(uint32_t fpscr_initial, int safe,
                          uint32_t comparisons, uint32_t mismatches,
                          uint32_t half_comparisons,
                          uint32_t uniform_comparisons,
                          uint32_t model_boundary_comparisons,
                          uint32_t model_random_comparisons,
                          uint32_t model_multipliers,
                          uint32_t nonfinite_comparisons, uint32_t error)
{
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_MAGIC] =
        V8_VFP_SELFTEST_MAGIC;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_FPSCR_INITIAL] =
        fpscr_initial;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_SAFE] = (uint32_t)safe;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_MISMATCHES] = mismatches;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_COMPARISONS] = comparisons;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_HALF_COMPARISONS] =
        half_comparisons;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_UNIFORM_COMPARISONS] =
        uniform_comparisons;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_MODEL_BOUNDARY_COMPARISONS] =
        model_boundary_comparisons;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_MODEL_RANDOM_COMPARISONS] =
        model_random_comparisons;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_MODEL_MULTIPLIERS] =
        model_multipliers;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_ERROR] = error;
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_FPSCR_FINAL] =
        v8_vfp_requant_read_fpscr();
    v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_NONFINITE_COMPARISONS] =
        nonfinite_comparisons;
}

static int model_channel_count(const V8Graph *graph, size_t param_size,
                               uint32_t *count_out)
{
    uint32_t node_id;
    uint32_t total = 0u;
    for (node_id = 0u; node_id < graph->count; ++node_id) {
        const V8Node *node = &graph->nodes[node_id];
        size_t multiplier_bytes;
        if (node->op != V8_CONV) continue;
        if (!node->c || (size_t)node->c > SIZE_MAX / sizeof(double)) return -1;
        multiplier_bytes = (size_t)node->c * sizeof(double);
        if ((size_t)node->multiplier > param_size ||
            multiplier_bytes > param_size - (size_t)node->multiplier ||
            node->c > UINT32_MAX - total) return -1;
        total += node->c;
    }
    if (!total) return -1;
    *count_out = total;
    return 0;
}

int v8_vfp_requant_selftest(const V8Graph *graph, const uint8_t *params,
                            size_t param_size)
{
    uint32_t fpscr_initial;
    uint32_t comparisons = 0u;
    uint32_t mismatches = 0u;
    uint32_t half_comparisons = 0u;
    uint32_t uniform_comparisons = 0u;
    uint32_t model_boundary_comparisons = 0u;
    uint32_t model_random_comparisons = 0u;
    uint32_t model_multipliers = 0u;
    uint32_t nonfinite_comparisons = 0u;
    uint32_t random_state = 0x6d2b79f5u;
    uint32_t model_channels = 0u;
    uint32_t node_id;
    uint32_t error = 0u;
    int safe;

    memset(v8_vfp_selftest_status, 0, sizeof(v8_vfp_selftest_status));
    fpscr_initial = v8_vfp_requant_read_fpscr();
    safe = v8_vfp_requant_fpscr_is_safe(fpscr_initial);
    if (!safe) {
        error = 1u;
        record_status(fpscr_initial, safe, comparisons, mismatches,
                      half_comparisons, uniform_comparisons,
                      model_boundary_comparisons, model_random_comparisons,
                      model_multipliers, nonfinite_comparisons, error);
        return -(int)error;
    }
    if (!graph || !graph->nodes || !params || param_size != graph->param_bytes ||
        model_channel_count(graph, param_size, &model_channels)) {
        error = 2u;
        record_status(fpscr_initial, safe, comparisons, mismatches,
                      half_comparisons, uniform_comparisons,
                      model_boundary_comparisons, model_random_comparisons,
                      model_multipliers, nonfinite_comparisons, error);
        return -(int)error;
    }

    /* All half integers in the output neighborhood and their adjacent doubles. */
    {
        int32_t whole;
        for (whole = -128; whole < 128; ++whole) {
            double half = (double)whole + 0.5;
            compare_value(nextafter(half, -INFINITY), &comparisons,
                          &mismatches, &nonfinite_comparisons);
            compare_value(half, &comparisons, &mismatches,
                          &nonfinite_comparisons);
            compare_value(nextafter(half, INFINITY), &comparisons,
                          &mismatches, &nonfinite_comparisons);
            half_comparisons += 3u;
        }
        {
            const double edges[] = {
                -INFINITY, -128.0, nextafter(-127.0, -INFINITY), -127.0,
                nextafter(-127.0, INFINITY), -0.0, 0.0,
                nextafter(127.0, -INFINITY), 127.0,
                nextafter(127.0, INFINITY), 128.0, INFINITY
            };
            size_t edge;
            for (edge = 0u; edge < sizeof(edges) / sizeof(edges[0]); ++edge) {
                compare_value(edges[edge], &comparisons, &mismatches,
                              &nonfinite_comparisons);
                half_comparisons++;
            }
        }
    }

    /* Exact 32-bit PRNG mapping to a uniform 2^-24 grid in [-128, 128). */
    {
        uint32_t sample;
        for (sample = 0u; sample < V8_VFP_UNIFORM_SAMPLES; ++sample) {
            double value = (double)next_u32(&random_state) * 0x1p-24 - 128.0;
            compare_value(value, &comparisons, &mismatches,
                          &nonfinite_comparisons);
            uniform_comparisons++;
        }
    }

    /* For each model multiplier, compare raw accumulators nearest several
     * randomized (k + 0.5) / multiplier thresholds. */
    {
        uint32_t random_remaining = V8_VFP_MODEL_RANDOM_SAMPLES;
        for (node_id = 0u; node_id < graph->count; ++node_id) {
            const V8Node *node = &graph->nodes[node_id];
            uint32_t channel;
            if (node->op != V8_CONV) continue;
            for (channel = 0u; channel < node->c; ++channel) {
                const uint8_t *multiplier_bytes =
                    params + node->multiplier + (size_t)channel * sizeof(double);
                double multiplier = model_f64(multiplier_bytes);
                uint32_t round;
                uint32_t channel_random =
                    V8_VFP_MODEL_RANDOM_SAMPLES / model_channels +
                    ((V8_VFP_MODEL_RANDOM_SAMPLES % model_channels) != 0u);
                if (!isfinite(multiplier) || multiplier <= 0.0) {
                    error = 3u;
                    break;
                }
                model_multipliers++;
                for (round = 0u; round < V8_VFP_MODEL_BOUNDARY_ROUNDS; ++round) {
                    int32_t k = (int32_t)(next_u32(&random_state) & 0xffu) - 128;
                    double threshold = ((double)k + 0.5) / multiplier;
                    if (isfinite(threshold) &&
                        threshold >= (double)INT32_MIN + 1.0 &&
                        threshold <= (double)INT32_MAX - 1.0) {
                        int64_t base = (int64_t)floor(threshold);
                        int32_t delta;
                        for (delta = -1; delta <= 1; ++delta) {
                            int64_t raw64 = base + delta;
                            int32_t raw;
                            double product;
                            if (raw64 < INT32_MIN || raw64 > INT32_MAX) continue;
                            raw = (int32_t)raw64;
                            product = (double)raw * multiplier;
                            compare_value(product, &comparisons, &mismatches,
                                          &nonfinite_comparisons);
                            model_boundary_comparisons++;
                        }
                    }
                }
                while (random_remaining && channel_random > 0u) {
                    uint32_t bits = next_u32(&random_state);
                    int32_t raw;
                    double product;
                    memcpy(&raw, &bits, sizeof(raw));
                    product = (double)raw * multiplier;
                    compare_value(product, &comparisons, &mismatches,
                                  &nonfinite_comparisons);
                    model_random_comparisons++;
                    random_remaining--;
                    channel_random--;
                }
            }
            if (error) break;
        }
        if (!error && (random_remaining != 0u ||
                       model_boundary_comparisons <
                           V8_VFP_MODEL_BOUNDARY_MIN_COMPARISONS)) error = 4u;
    }

    if (!error && mismatches) error = 5u;
    record_status(fpscr_initial, safe, comparisons, mismatches,
                  half_comparisons, uniform_comparisons,
                  model_boundary_comparisons, model_random_comparisons,
                  model_multipliers, nonfinite_comparisons, error);
    return error ? -(int)error : 0;
}
