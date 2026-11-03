#ifndef V8_SERVICE_H
#define V8_SERVICE_H

#include <stddef.h>
#include <stdint.h>
#include "v8_decode.h"

#define V8_SERVICE_TENSOR_BYTES (640u * 640u * 3u)
#define V8_SERVICE_MAX_REQUEST_JSON 4096u
#define V8_SERVICE_PROBE_ONLY 1 /* Validated HELLO, clean EOF before INFER. */

/* Return positive byte count, zero on EOF, negative on transport failure. */
typedef int (*V8ServiceRead)(void *opaque, uint8_t *destination, size_t capacity);
typedef int (*V8ServiceWrite)(void *opaque, const uint8_t *source, size_t bytes);
/* Callback runs the compiled V8 model and class-aware NMS. It returns the
 * model's complete class set; board task filtering is not performed here. */
typedef int (*V8ServiceInfer)(void *opaque, const uint8_t *rgb_hwc, size_t bytes,
                              V8Detection *detections, size_t capacity, size_t *count);

typedef struct {
    char model_sha256[65];
    char classes_sha256[65];
    uint32_t class_count;
    const char *class_domain; /* PIN-only class identity bound to graph/hash */
    /* Set only after checking the loaded package against its compiled graph
     * and class identity. The service rejects unverified identities. */
    int verified_identity;
    V8ServiceRead read;
    V8ServiceWrite write;
    void *transport;
    V8ServiceInfer infer;
    void *inference;
    uint8_t *tensor;
    size_t tensor_capacity;
    V8Detection *detections;
    size_t detection_capacity;
    char *response;
    size_t response_capacity;
} V8Service;

/* One HELLO and optional INFER per connection.
 * Return 0 on delivered RESULT, V8_SERVICE_PROBE_ONLY for a validated HELLO
 * followed by clean EOF before any INFER prefix byte, negative for errors.
 * This function never runs a host model or silently retries INFER. */
int v8_service_one(V8Service *service);

#endif
