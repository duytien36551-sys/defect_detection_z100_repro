#include "v8_decode.h"

#include <math.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct {
    float x1, y1, x2, y2, score;
    int class_id;
    size_t sequence;
} Candidate;

static float sigmoid_f(float value) {
    if (value >= 0.0f) {
        float z = expf(-value);
        return 1.0f / (1.0f + z);
    }
    float z = expf(value);
    return z / (1.0f + z);
}

static float clip_f(float value, float low, float high) {
    return fminf(fmaxf(value, low), high);
}

static int candidate_compare(const void *left, const void *right) {
    const Candidate *a = (const Candidate *)left;
    const Candidate *b = (const Candidate *)right;
    if (a->score > b->score) return -1;
    if (a->score < b->score) return 1;
    if (a->sequence < b->sequence) return -1;
    if (a->sequence > b->sequence) return 1;
    return 0;
}

static float overlap(const Candidate *a, const Candidate *b) {
    float left = fmaxf(a->x1, b->x1), top = fmaxf(a->y1, b->y1);
    float right = fminf(a->x2, b->x2), bottom = fminf(a->y2, b->y2);
    float intersection = fmaxf(0.0f, right - left) * fmaxf(0.0f, bottom - top);
    float area_a = (a->x2 - a->x1) * (a->y2 - a->y1);
    float area_b = (b->x2 - b->x1) * (b->y2 - b->y1);
    float denom = area_a + area_b - intersection;
    return denom > 0.0f ? intersection / denom : 0.0f;
}

static int dfl_side(const float *data, size_t cells, size_t cell,
                    int first_channel, int reg_max, float *distance) {
    float maximum = -INFINITY;
    for (int bin = 0; bin < reg_max; ++bin) {
        float value = data[((size_t)first_channel + (size_t)bin) * cells + cell];
        if (!isfinite(value)) return 0;
        if (value > maximum) maximum = value;
    }
    double total = 0.0, weighted = 0.0;
    for (int bin = 0; bin < reg_max; ++bin) {
        float value = data[((size_t)first_channel + (size_t)bin) * cells + cell];
        double weight = exp((double)value - (double)maximum);
        total += weight;
        weighted += (double)bin * weight;
    }
    if (!(total > 0.0)) return 0;
    *distance = (float)(weighted / total);
    return 1;
}

int v8_decode_raw(const V8Head *heads, size_t head_count,
                  const V8DecodeConfig *config, V8Detection *output,
                  size_t output_capacity, size_t *out_count) {
    if (!out_count) return V8_DECODE_INVALID;
    *out_count = 0;
    if (!heads || !config || !output || !head_count || !output_capacity ||
        config->input_width <= 0 || config->input_height <= 0 ||
        config->classes <= 0 || config->classes > 1024 ||
        config->reg_max <= 1 || config->reg_max > 64 ||
        !isfinite(config->confidence) || config->confidence < 0.0f ||
        config->confidence > 1.0f || !isfinite(config->iou) ||
        config->iou < 0.0f || config->iou > 1.0f ||
        (config->multi_label != 0 && config->multi_label != 1) ||
        ((!config->class_confidence && config->class_confidence_count != 0) ||
         (config->class_confidence &&
          config->class_confidence_count != (size_t)config->classes)))
        return V8_DECODE_INVALID;
    if (config->class_confidence) {
        for (int cls = 0; cls < config->classes; ++cls) {
            float threshold = config->class_confidence[cls];
            if (!isfinite(threshold) || threshold < 0.0f || threshold > 1.0f)
                return V8_DECODE_INVALID;
        }
    }

    size_t max_candidates = 0;
    for (size_t i = 0; i < head_count; ++i) {
        const V8Head *head = &heads[i];
        if (!head->data || head->width <= 0 || head->height <= 0 || head->stride <= 0 ||
            (int64_t)head->width * head->stride != config->input_width ||
            (int64_t)head->height * head->stride != config->input_height)
            return V8_DECODE_INVALID;
        size_t cells = (size_t)head->width * (size_t)head->height;
        size_t multiplier = config->multi_label ? (size_t)config->classes : 1u;
        if (cells > SIZE_MAX / multiplier ||
            max_candidates > SIZE_MAX - cells * multiplier)
            return V8_DECODE_OVERFLOW;
        max_candidates += cells * multiplier;
    }
    if (max_candidates > SIZE_MAX / sizeof(Candidate)) return V8_DECODE_OVERFLOW;
    Candidate *candidates = (Candidate *)malloc(max_candidates * sizeof(Candidate));
    if (!candidates) return V8_DECODE_NOMEM;
    size_t count = 0, sequence = 0;
    for (size_t level = 0; level < head_count; ++level) {
        const V8Head *head = &heads[level];
        size_t cells = (size_t)head->width * (size_t)head->height;
        for (size_t cell = 0; cell < cells; ++cell) {
            float sides[4];
            int valid = 1;
            for (int side = 0; side < 4; ++side)
                if (!dfl_side(head->data, cells, cell, side * config->reg_max,
                              config->reg_max, &sides[side])) valid = 0;
            if (!valid) continue;
            float anchor_x = ((float)(cell % (size_t)head->width) + 0.5f) * head->stride;
            float anchor_y = ((float)(cell / (size_t)head->width) + 0.5f) * head->stride;
            Candidate box = {
                anchor_x - sides[0] * head->stride,
                anchor_y - sides[1] * head->stride,
                anchor_x + sides[2] * head->stride,
                anchor_y + sides[3] * head->stride,
                0.0f, -1, 0
            };
            if (!(box.x2 > box.x1 && box.y2 > box.y1)) continue;
            int best_class = -1;
            float best_score = config->class_confidence ? -1.0f : config->confidence;
            for (int cls = 0; cls < config->classes; ++cls) {
                float logit = head->data[((size_t)4 * config->reg_max + (size_t)cls) * cells + cell];
                if (!isfinite(logit)) continue;
                float score = sigmoid_f(logit);
                if (config->multi_label) {
                    float threshold = config->class_confidence
                        ? config->class_confidence[cls] : config->confidence;
                    if (score < threshold) continue;
                    box.score = score;
                    box.class_id = cls;
                    box.sequence = sequence++;
                    candidates[count++] = box;
                } else if (score >= best_score &&
                           (score > best_score || best_class < 0)) {
                    best_score = score;
                    best_class = cls;
                }
            }
            if (!config->multi_label && best_class >= 0 &&
                best_score >= (config->class_confidence
                    ? config->class_confidence[best_class] : config->confidence)) {
                box.score = best_score;
                box.class_id = best_class;
                box.sequence = sequence++;
                candidates[count++] = box;
            }
        }
    }
    qsort(candidates, count, sizeof(Candidate), candidate_compare);
    size_t selected_capacity = output_capacity < count ? output_capacity : count;
    size_t *selected = (size_t *)malloc(selected_capacity * sizeof(size_t));
    if (!selected && selected_capacity) {
        free(candidates);
        return V8_DECODE_NOMEM;
    }
    /* A selected candidate's raw pixel box is kept for IoU. output is only
     * normalized on write, after all class-aware suppression decisions. */
    for (size_t i = 0; i < count && *out_count < output_capacity; ++i) {
        Candidate *candidate = &candidates[i];
        int suppressed = 0;
        for (size_t j = 0; j < *out_count; ++j) {
            Candidate *prior = &candidates[selected[j]];
            if (prior->class_id == candidate->class_id &&
                overlap(prior, candidate) > config->iou) {
                suppressed = 1;
                break;
            }
        }
        if (suppressed) continue;
        selected[*out_count] = i;
        output[*out_count] = (V8Detection){
            candidate->x1 / config->input_width,
            candidate->y1 / config->input_height,
            candidate->x2 / config->input_width,
            candidate->y2 / config->input_height,
            candidate->score,
            candidate->class_id
        };
        ++*out_count;
    }
    free(selected);
    free(candidates);
    return V8_DECODE_OK;
}

size_t v8_filter_classes(const V8Detection *input, size_t count,
                         int first_class, int class_count,
                         V8Detection *output) {
    if (!input || !output || first_class < 0 || class_count <= 0 ||
        first_class > INT32_MAX - class_count) return 0;
    size_t kept = 0;
    for (size_t i = 0; i < count; ++i)
        if (input[i].class_id >= first_class &&
            input[i].class_id < first_class + class_count)
            output[kept++] = input[i];
    return kept;
}

int v8_project_box(const V8Detection *input, const V8Letterbox *letterbox,
                   V8Detection *output) {
    if (!input || !letterbox || !output || letterbox->original_width <= 0 ||
        letterbox->original_height <= 0 || letterbox->input_width <= 0 ||
        letterbox->input_height <= 0 || !(letterbox->scale_x > 0.0f) ||
        !(letterbox->scale_y > 0.0f) || !isfinite(letterbox->scale_x) ||
        !isfinite(letterbox->scale_y) || !isfinite(letterbox->pad_left) ||
        !isfinite(letterbox->pad_top) || !isfinite(input->x1) ||
        !isfinite(input->y1) || !isfinite(input->x2) ||
        !isfinite(input->y2)) return V8_DECODE_INVALID;
    V8Detection projected = *input;
    projected.x1 = clip_f((input->x1 * letterbox->input_width - letterbox->pad_left) /
                          letterbox->scale_x, 0.0f, (float)letterbox->original_width);
    projected.x2 = clip_f((input->x2 * letterbox->input_width - letterbox->pad_left) /
                          letterbox->scale_x, 0.0f, (float)letterbox->original_width);
    projected.y1 = clip_f((input->y1 * letterbox->input_height - letterbox->pad_top) /
                          letterbox->scale_y, 0.0f, (float)letterbox->original_height);
    projected.y2 = clip_f((input->y2 * letterbox->input_height - letterbox->pad_top) /
                          letterbox->scale_y, 0.0f, (float)letterbox->original_height);
    *output = projected;
    return V8_DECODE_OK;
}
