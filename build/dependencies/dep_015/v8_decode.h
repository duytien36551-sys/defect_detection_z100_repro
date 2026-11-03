#ifndef V8_DECODE_H
#define V8_DECODE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* One batch=1 raw detection head, contiguous CHW float32. Regression channels
 * are [left bins, top bins, right bins, bottom bins], followed by class logits. */
typedef struct {
    const float *data;
    int width;
    int height;
    int stride;
} V8Head;

typedef struct {
    int input_width;
    int input_height;
    int classes;
    int reg_max;
    float confidence;
    float iou;
    int multi_label; /* 1: every class above its active threshold; 0: best class per cell */
    /* Optional per-class thresholds. NULL/0 keeps confidence; otherwise count
     * must equal classes and each threshold replaces the global confidence. */
    const float *class_confidence;
    size_t class_confidence_count;
} V8DecodeConfig;

/* Coordinates are normalized to the model input [0,1]. They may lie outside
 * [0,1] before image projection because raw boxes can cross the padded edge. */
typedef struct {
    float x1, y1, x2, y2;
    float score;
    int class_id;
} V8Detection;

typedef struct {
    int original_width;
    int original_height;
    int input_width;
    int input_height;
    float scale_x;
    float scale_y;
    float pad_left;
    float pad_top;
} V8Letterbox;

enum {
    V8_DECODE_OK = 0,
    V8_DECODE_INVALID = -1,
    V8_DECODE_NOMEM = -2,
    V8_DECODE_OVERFLOW = -3
};

/* Output capacity is the GLOBAL maximum after class-aware NMS. Internally all
 * candidates passing their active confidence threshold are retained, so class
 * enumeration cannot use up a per-class or pre-NMS quota. out_count is zeroed
 * on errors. */
int v8_decode_raw(const V8Head *heads, size_t head_count,
                  const V8DecodeConfig *config, V8Detection *output,
                  size_t output_capacity, size_t *out_count);

/* Apply task range after all-class NMS; keeps score order and permits in-place
 * filtering by passing the same input/output pointer. */
size_t v8_filter_classes(const V8Detection *input, size_t count,
                         int first_class, int class_count,
                         V8Detection *output);

/* Converts normalized model coordinates to clipped original-image pixels. */
int v8_project_box(const V8Detection *input, const V8Letterbox *letterbox,
                   V8Detection *output);

#ifdef __cplusplus
}
#endif
#endif
