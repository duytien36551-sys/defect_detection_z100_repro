#include "v8_service.h"
#include "v8_sha256.h"

#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define RESPONSE_CAPACITY 8192u
#define INPUT_CAPACITY (V8_SERVICE_TENSOR_BYTES + 8192u)

static const char model_sha256[] =
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
static const char classes_sha256[] =
    "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789";

typedef struct {
    uint8_t *input;
    size_t input_length;
    size_t input_position;
    size_t max_read;
    int error_at_eof;
    uint8_t output[RESPONSE_CAPACITY];
    size_t output_length;
} MockWire;

typedef struct {
    unsigned calls;
} InferState;

typedef struct {
    MockWire wire;
    V8Service service;
    InferState infer;
} Fixture;

static int mock_read(void *opaque, uint8_t *destination, size_t capacity)
{
    MockWire *wire = (MockWire *)opaque;
    size_t available, count;

    if (wire->input_position == wire->input_length)
        return wire->error_at_eof ? -1 : 0;
    available = wire->input_length - wire->input_position;
    count = available < capacity ? available : capacity;
    if (wire->max_read && count > wire->max_read) count = wire->max_read;
    memcpy(destination, wire->input + wire->input_position, count);
    wire->input_position += count;
    return count > INT_MAX ? -1 : (int)count;
}

static int mock_write(void *opaque, const uint8_t *source, size_t bytes)
{
    MockWire *wire = (MockWire *)opaque;
    if (bytes > sizeof wire->output - wire->output_length || bytes > INT_MAX)
        return -1;
    memcpy(wire->output + wire->output_length, source, bytes);
    wire->output_length += bytes;
    return (int)bytes;
}

static int mock_infer(void *opaque, const uint8_t *tensor, size_t bytes,
                      V8Detection *detections, size_t capacity, size_t *count)
{
    InferState *state = (InferState *)opaque;
    if (!state || !tensor || bytes != V8_SERVICE_TENSOR_BYTES ||
        !detections || capacity == 0 || !count)
        return -1;
    ++state->calls;
    *count = 0;
    return 0;
}

static int append_bytes(MockWire *wire, const void *bytes, size_t length)
{
    if (length > INPUT_CAPACITY - wire->input_length) return -1;
    memcpy(wire->input + wire->input_length, bytes, length);
    wire->input_length += length;
    return 0;
}

static int append_frame(MockWire *wire, const char *json)
{
    size_t length = strlen(json);
    uint8_t prefix[4];
    if (!length || length > UINT32_MAX) return -1;
    prefix[0] = (uint8_t)(length >> 24);
    prefix[1] = (uint8_t)(length >> 16);
    prefix[2] = (uint8_t)(length >> 8);
    prefix[3] = (uint8_t)length;
    return append_bytes(wire, prefix, sizeof prefix) ||
           append_bytes(wire, json, length) ? -1 : 0;
}

static int fixture_init(Fixture *fixture)
{
    memset(fixture, 0, sizeof *fixture);
    fixture->wire.input = (uint8_t *)malloc(INPUT_CAPACITY);
    fixture->service.tensor = (uint8_t *)malloc(V8_SERVICE_TENSOR_BYTES);
    fixture->service.detections = (V8Detection *)calloc(1, sizeof(V8Detection));
    fixture->service.response = (char *)calloc(1, RESPONSE_CAPACITY);
    if (!fixture->wire.input || !fixture->service.tensor ||
        !fixture->service.detections || !fixture->service.response)
        return -1;

    memcpy(fixture->service.model_sha256, model_sha256, sizeof model_sha256);
    memcpy(fixture->service.classes_sha256, classes_sha256, sizeof classes_sha256);
    fixture->service.class_count = 9;
    fixture->service.class_domain = "pin";
    fixture->service.verified_identity = 1;
    fixture->service.read = mock_read;
    fixture->service.write = mock_write;
    fixture->service.transport = &fixture->wire;
    fixture->service.infer = mock_infer;
    fixture->service.inference = &fixture->infer;
    fixture->service.tensor_capacity = V8_SERVICE_TENSOR_BYTES;
    fixture->service.detection_capacity = 1;
    fixture->service.response_capacity = RESPONSE_CAPACITY;
    fixture->wire.max_read = 7;
    return 0;
}

static void fixture_dispose(Fixture *fixture)
{
    free(fixture->wire.input);
    free(fixture->service.tensor);
    free(fixture->service.detections);
    free(fixture->service.response);
}

static int append_hello(MockWire *wire)
{
    char json[256];
    int length = snprintf(json, sizeof json,
        "{\"type\":\"HELLO\",\"protocol\":\"pin9-v8/2-input640\","
        "\"model_sha256\":\"%s\",\"classes_sha256\":\"%s\"}",
        model_sha256, classes_sha256);
    return length < 0 || (size_t)length >= sizeof json ? -1 : append_frame(wire, json);
}

static int response_frame(const MockWire *wire, size_t wanted,
                          char *body, size_t body_capacity, size_t *frame_count)
{
    size_t position = 0, index = 0;
    while (position < wire->output_length) {
        size_t length;
        if (wire->output_length - position < 4) return -1;
        length = ((size_t)wire->output[position] << 24) |
                 ((size_t)wire->output[position + 1] << 16) |
                 ((size_t)wire->output[position + 2] << 8) |
                 wire->output[position + 3];
        position += 4;
        if (length > wire->output_length - position) return -1;
        if (index == wanted) {
            if (length >= body_capacity) return -1;
            memcpy(body, wire->output + position, length);
            body[length] = 0;
        }
        position += length;
        ++index;
    }
    if (frame_count) *frame_count = index;
    return wanted < index ? 0 : -1;
}

static int check_hello_reply(const MockWire *wire, size_t expected_frames)
{
    char body[RESPONSE_CAPACITY];
    size_t count = 0;
    if (response_frame(wire, 0, body, sizeof body, &count) ||
        count != expected_frames || !strstr(body, "\"type\":\"HELLO_OK\""))
        return -1;
    return 0;
}

static int test_hello_only_eof(void)
{
    Fixture fixture;
    int result;
    if (fixture_init(&fixture)) return -1;
    if (append_hello(&fixture.wire)) { fixture_dispose(&fixture); return -1; }
    result = v8_service_one(&fixture.service);
    if (result != 1 || fixture.infer.calls != 0 ||
        check_hello_reply(&fixture.wire, 1)) {
        fprintf(stderr, "HELLO-only EOF: result=%d infer_calls=%u\n",
                result, fixture.infer.calls);
        fixture_dispose(&fixture);
        return -1;
    }
    fixture_dispose(&fixture);
    return 0;
}

static int test_partial_prefix(void)
{
    Fixture fixture;
    const uint8_t partial_prefix = 0;
    int result;
    if (fixture_init(&fixture)) return -1;
    if (append_hello(&fixture.wire) ||
        append_bytes(&fixture.wire, &partial_prefix, sizeof partial_prefix)) {
        fixture_dispose(&fixture);
        return -1;
    }
    result = v8_service_one(&fixture.service);
    if (result != -5 || fixture.infer.calls != 0 ||
        check_hello_reply(&fixture.wire, 1)) {
        fprintf(stderr, "partial prefix: result=%d infer_calls=%u\n",
                result, fixture.infer.calls);
        fixture_dispose(&fixture);
        return -1;
    }
    fixture_dispose(&fixture);
    return 0;
}

static int test_partial_body(void)
{
    Fixture fixture;
    static const uint8_t partial_body[] = "{\"type\"";
    static const uint8_t prefix[] = { 0, 0, 0, 20 };
    int result;
    if (fixture_init(&fixture)) return -1;
    if (append_hello(&fixture.wire) ||
        append_bytes(&fixture.wire, prefix, sizeof prefix) ||
        append_bytes(&fixture.wire, partial_body, sizeof partial_body - 1)) {
        fixture_dispose(&fixture);
        return -1;
    }
    result = v8_service_one(&fixture.service);
    if (result != -5 || fixture.infer.calls != 0 ||
        check_hello_reply(&fixture.wire, 1)) {
        fprintf(stderr, "partial body: result=%d infer_calls=%u\n",
                result, fixture.infer.calls);
        fixture_dispose(&fixture);
        return -1;
    }
    fixture_dispose(&fixture);
    return 0;
}

static int test_transport_error(void)
{
    Fixture fixture;
    int result;
    if (fixture_init(&fixture)) return -1;
    if (append_hello(&fixture.wire)) { fixture_dispose(&fixture); return -1; }
    fixture.wire.error_at_eof = 1;
    result = v8_service_one(&fixture.service);
    if (result != -5 || fixture.infer.calls != 0 ||
        check_hello_reply(&fixture.wire, 1)) {
        fprintf(stderr, "transport error: result=%d infer_calls=%u\n",
                result, fixture.infer.calls);
        fixture_dispose(&fixture);
        return -1;
    }
    fixture_dispose(&fixture);
    return 0;
}

static int test_valid_infer(void)
{
    Fixture fixture;
    uint8_t *tensor = NULL;
    char digest[65], json[512], response[RESPONSE_CAPACITY];
    size_t frame_count = 0, i;
    int length, result;

    if (fixture_init(&fixture)) return -1;
    tensor = (uint8_t *)malloc(V8_SERVICE_TENSOR_BYTES);
    if (!tensor) { fixture_dispose(&fixture); return -1; }
    for (i = 0; i < V8_SERVICE_TENSOR_BYTES; ++i)
        tensor[i] = (uint8_t)(i * 31u + (i >> 7));
    v8_sha256_hex(tensor, V8_SERVICE_TENSOR_BYTES, digest);
    length = snprintf(json, sizeof json,
        "{\"type\":\"INFER\",\"protocol\":\"pin9-v8/2-input640\","
        "\"task\":\"pin\",\"tensor_bytes\":1228800,"
        "\"tensor_sha256\":\"%s\",\"request_id\":"
        "\"0123456789abcdef0123456789abcdef\"}", digest);
    if (length < 0 || (size_t)length >= sizeof json ||
        append_hello(&fixture.wire) || append_frame(&fixture.wire, json) ||
        append_bytes(&fixture.wire, tensor, V8_SERVICE_TENSOR_BYTES)) {
        free(tensor);
        fixture_dispose(&fixture);
        return -1;
    }
    fixture.wire.max_read = 4093;
    result = v8_service_one(&fixture.service);
    if (response_frame(&fixture.wire, 1, response, sizeof response, &frame_count) ||
        result != 0 || fixture.infer.calls != 1 || frame_count != 2 ||
        check_hello_reply(&fixture.wire, 2) ||
        !strstr(response, "\"type\":\"RESULT\"") ||
        !strstr(response, "0123456789abcdef0123456789abcdef")) {
        fprintf(stderr, "valid INFER: result=%d infer_calls=%u frames=%zu\n",
                result, fixture.infer.calls, frame_count);
        free(tensor);
        fixture_dispose(&fixture);
        return -1;
    }
    free(tensor);
    fixture_dispose(&fixture);
    return 0;
}

int main(void)
{
    if (test_hello_only_eof()) return 1;
    puts("PASS HELLO-only EOF");
    if (test_partial_prefix()) return 1;
    puts("PASS partial prefix remains an error");
    if (test_partial_body()) return 1;
    puts("PASS partial body remains an error");
    if (test_transport_error()) return 1;
    puts("PASS transport error remains an error");
    if (test_valid_infer()) return 1;
    puts("PASS valid INFER is delivered");
    return 0;
}
