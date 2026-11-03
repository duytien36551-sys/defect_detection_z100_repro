#include "v8_service.h"
#include "v8_sha256.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GUARD_BYTES 32u
#define WIRE_CAP (V8_SERVICE_TENSOR_BYTES + 2u * V8_SERVICE_MAX_REQUEST_JSON + 512u)
#define REPLY_CAP 16384u
#define RESPONSE_CAP 8192u
#define CANARY 0xD7u

typedef struct {
    uint8_t before[GUARD_BYTES];
    uint8_t data[WIRE_CAP];
    uint8_t after[GUARD_BYTES];
} GuardedWire;

typedef struct {
    uint8_t before[GUARD_BYTES];
    uint8_t data[REPLY_CAP];
    uint8_t after[GUARD_BYTES];
} GuardedReply;

typedef struct {
    uint8_t before[GUARD_BYTES];
    uint8_t data[V8_SERVICE_TENSOR_BYTES];
    uint8_t after[GUARD_BYTES];
} GuardedTensor;

typedef struct {
    uint8_t before[GUARD_BYTES];
    V8Detection data[2];
    uint8_t after[GUARD_BYTES];
} GuardedDetections;

typedef struct {
    uint8_t before[GUARD_BYTES];
    char data[RESPONSE_CAP];
    uint8_t after[GUARD_BYTES];
} GuardedResponse;

static GuardedWire wire;
static GuardedReply reply;
static GuardedTensor tensor;
static GuardedDetections detections;
static GuardedResponse response;
static const uint8_t payload[V8_SERVICE_TENSOR_BYTES] = {0x5Au};
static size_t wire_size, wire_pos, reply_size;
static size_t read_fragment = 7u, write_fragment = 3u;
static int infer_calls, output_class;
static const char model_sha[] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static const char classes_sha[] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

static void fill_canary(uint8_t *data, size_t length) {
    memset(data, CANARY, length);
}

static int canary_ok(const uint8_t *data, size_t length) {
    size_t i;
    for (i = 0; i < length; ++i) if (data[i] != CANARY) return 0;
    return 1;
}

static void initialize_buffers(void) {
    fill_canary(wire.before, sizeof(wire.before));
    fill_canary(wire.after, sizeof(wire.after));
    fill_canary(reply.before, sizeof(reply.before));
    fill_canary(reply.after, sizeof(reply.after));
    fill_canary(tensor.before, sizeof(tensor.before));
    fill_canary(tensor.after, sizeof(tensor.after));
    fill_canary(detections.before, sizeof(detections.before));
    fill_canary(detections.after, sizeof(detections.after));
    fill_canary(response.before, sizeof(response.before));
    fill_canary(response.after, sizeof(response.after));
    wire_size = 0;
    wire_pos = 0;
    reply_size = 0;
    infer_calls = 0;
    output_class = 8;
}

static int append_bytes(const void *source, size_t length) {
    if (length > sizeof(wire.data) - wire_size) return -1;
    memcpy(wire.data + wire_size, source, length);
    wire_size += length;
    return 0;
}

static int append_prefix(uint32_t length) {
    uint8_t prefix[4];
    prefix[0] = (uint8_t)(length >> 24);
    prefix[1] = (uint8_t)(length >> 16);
    prefix[2] = (uint8_t)(length >> 8);
    prefix[3] = (uint8_t)length;
    return append_bytes(prefix, sizeof(prefix));
}

static int append_frame(const char *json) {
    size_t length = strlen(json);
    if (length > UINT32_MAX || append_prefix((uint32_t)length)) return -1;
    return append_bytes(json, length);
}

static int append_payload(size_t length) {
    return append_bytes(payload, length);
}

static int mock_read(void *opaque, uint8_t *destination, size_t capacity) {
    size_t available, count;
    (void)opaque;
    if (wire_pos >= wire_size) return 0;
    available = wire_size - wire_pos;
    count = available < capacity ? available : capacity;
    if (count > read_fragment) count = read_fragment;
    memcpy(destination, wire.data + wire_pos, count);
    wire_pos += count;
    return (int)count;
}

static int mock_write(void *opaque, const uint8_t *source, size_t length) {
    size_t count = length < write_fragment ? length : write_fragment;
    (void)opaque;
    if (count > sizeof(reply.data) - reply_size) return -1;
    memcpy(reply.data + reply_size, source, count);
    reply_size += count;
    return (int)count;
}

static int mock_infer(void *opaque, const uint8_t *rgb, size_t length,
                      V8Detection *out, size_t capacity, size_t *count) {
    (void)opaque;
    if (length != V8_SERVICE_TENSOR_BYTES || memcmp(rgb, payload, length) != 0 || capacity == 0) return -1;
    ++infer_calls;
    out[0] = (V8Detection){.x1 = 0.1f, .y1 = 0.2f, .x2 = 0.8f, .y2 = 0.9f,
                           .score = 0.75f, .class_id = output_class};
    *count = 1;
    return 0;
}

static V8Service make_service(const char *domain, uint32_t class_count) {
    V8Service service = {0};
    memcpy(service.model_sha256, model_sha, sizeof(model_sha));
    memcpy(service.classes_sha256, classes_sha, sizeof(classes_sha));
    service.class_count = class_count;
    service.class_domain = domain;
    service.verified_identity = 1;
    service.read = mock_read;
    service.write = mock_write;
    service.infer = mock_infer;
    service.tensor = tensor.data;
    service.tensor_capacity = sizeof(tensor.data);
    service.detections = detections.data;
    service.detection_capacity = 2;
    service.response = response.data;
    service.response_capacity = sizeof(response.data);
    return service;
}

static int contains_reply(const char *text) {
    size_t i, length = strlen(text);
    for (i = 0; i + length <= reply_size; ++i)
        if (memcmp(reply.data + i, text, length) == 0) return 1;
    return 0;
}

static int guards_ok(void) {
    return canary_ok(wire.before, sizeof(wire.before)) && canary_ok(wire.after, sizeof(wire.after)) &&
           canary_ok(reply.before, sizeof(reply.before)) && canary_ok(reply.after, sizeof(reply.after)) &&
           canary_ok(tensor.before, sizeof(tensor.before)) && canary_ok(tensor.after, sizeof(tensor.after)) &&
           canary_ok(detections.before, sizeof(detections.before)) && canary_ok(detections.after, sizeof(detections.after)) &&
           canary_ok(response.before, sizeof(response.before)) && canary_ok(response.after, sizeof(response.after));
}

static int append_hello(const char *protocol, const char *model, const char *classes) {
    char json[512];
    int n = snprintf(json, sizeof(json),
                     "{\"type\":\"HELLO\",\"protocol\":\"%s\",\"model_sha256\":\"%s\",\"classes_sha256\":\"%s\"}",
                     protocol, model, classes);
    if (n < 0 || (size_t)n >= sizeof(json)) return -1;
    return append_frame(json);
}

static int append_infer(const char *protocol, const char *task, const char *declared_bytes,
                        const char *digest) {
    char json[512];
    int n = snprintf(json, sizeof(json),
                     "{\"type\":\"INFER\",\"protocol\":\"%s\",\"request_id\":\"0123456789abcdef0123456789abcdef\",\"task\":\"%s\",\"tensor_bytes\":%s,\"tensor_sha256\":\"%s\"}",
                     protocol, task, declared_bytes, digest);
    if (n < 0 || (size_t)n >= sizeof(json)) return -1;
    return append_frame(json);
}

static int build_good_request(void) {
    char digest[65];
    if (append_hello("pin9-v8/2-input640", model_sha, classes_sha)) return -1;
    v8_sha256_hex(payload, sizeof(payload), digest);
    if (append_infer("pin9-v8/2-input640", "pin", "1228800", digest)) return -1;
    return append_payload(sizeof(payload));
}

typedef enum {
    FAULT_OLD_HELLO, FAULT_BAD_MODEL, FAULT_BAD_CLASSES, FAULT_BAD_INFER_PROTOCOL,
    FAULT_OLD_LENGTH, FAULT_OFF_BY_ONE_LENGTH, FAULT_TOO_LONG_LENGTH, FAULT_BAD_DIGEST, FAULT_BAD_TASK,
    FAULT_TRUNCATED_HELLO, FAULT_OVERSIZED_HELLO, FAULT_TRUNCATED_TENSOR,
    FAULT_DUPLICATE_HELLO
} Fault;

static int build_fault(Fault fault) {
    char wrong_model[65], wrong_classes[65], bad_digest[65];
    char valid_digest[65];
    const char *hello_protocol = "pin9-v8/2-input640";
    const char *hello_model = model_sha;
    const char *hello_classes = classes_sha;
    const char *request_protocol = "pin9-v8/2-input640";
    const char *task = "pin";
    const char *declared_bytes = "1228800";
    const char *digest;
    size_t payload_length = sizeof(payload);

    memset(wrong_model, 'c', 64); wrong_model[64] = 0;
    memset(wrong_classes, 'd', 64); wrong_classes[64] = 0;
    memset(bad_digest, 'e', 64); bad_digest[64] = 0;
    v8_sha256_hex(payload, sizeof(payload), valid_digest);
    digest = valid_digest;

    switch (fault) {
        case FAULT_OLD_HELLO: hello_protocol = "joint18-v8/1"; break;
        case FAULT_BAD_MODEL: hello_model = wrong_model; break;
        case FAULT_BAD_CLASSES: hello_classes = wrong_classes; break;
        case FAULT_BAD_INFER_PROTOCOL: request_protocol = "joint18-v8/1"; break;
        case FAULT_OLD_LENGTH: declared_bytes = "519168"; break;
        case FAULT_OFF_BY_ONE_LENGTH: declared_bytes = "1228799"; break;
        case FAULT_TOO_LONG_LENGTH: declared_bytes = "1228801"; break;
        case FAULT_BAD_DIGEST: digest = bad_digest; break;
        case FAULT_BAD_TASK: task = "pcb"; break;
        case FAULT_TRUNCATED_HELLO:
            if (append_prefix(32u)) return -1;
            return append_bytes("{\"type\":", 8u);
        case FAULT_OVERSIZED_HELLO:
            return append_prefix(V8_SERVICE_MAX_REQUEST_JSON + 1u);
        case FAULT_DUPLICATE_HELLO:
            return append_frame("{\"type\":\"HELLO\",\"type\":\"HELLO\"}");
        case FAULT_TRUNCATED_TENSOR:
            payload_length = sizeof(payload) - 17u;
            break;
    }
    if (append_hello(hello_protocol, hello_model, hello_classes)) return -1;
    if (fault == FAULT_OLD_HELLO || fault == FAULT_BAD_MODEL || fault == FAULT_BAD_CLASSES) return 0;
    if (append_infer(request_protocol, task, declared_bytes, digest)) return -1;
    return append_payload(payload_length);
}

static int execute_service(const char *domain, uint32_t class_count) {
    V8Service service = make_service(domain, class_count);
    return v8_service_one(&service);
}

static int run_valid(void) {
    initialize_buffers();
    if (build_good_request()) return 1;
    if (execute_service("pin", 9u) != 0 || infer_calls != 1 ||
        !contains_reply("\"type\":\"HELLO_OK\"") ||
        !contains_reply("\"type\":\"RESULT\"") ||
        !contains_reply("\"class_id\":8") || !guards_ok()) return 2;
    return 0;
}

static int run_fault_then_recover(Fault fault, int expected) {
    int rc;
    initialize_buffers();
    if (build_fault(fault)) return 10 + (int)fault;
    rc = execute_service("pin", 9u);
    if ((expected == -99 ? rc >= 0 : rc != expected) || infer_calls != 0 || !guards_ok())
        return 30 + (int)fault;
    return run_valid();
}

int main(void) {
    static const struct { Fault fault; int expected; const char *label; } cases[] = {
        {FAULT_OLD_HELLO, -3, "old protocol"},
        {FAULT_BAD_MODEL, -3, "model identity"},
        {FAULT_BAD_CLASSES, -3, "class identity"},
        {FAULT_BAD_INFER_PROTOCOL, -6, "INFER protocol"},
        {FAULT_OLD_LENGTH, -6, "old 416 byte count"},
        {FAULT_OFF_BY_ONE_LENGTH, -6, "off-by-one byte count"},
        {FAULT_TOO_LONG_LENGTH, -6, "oversized declared tensor"},
        {FAULT_BAD_DIGEST, -8, "tensor digest"},
        {FAULT_BAD_TASK, -99, "PIN class domain"},
        {FAULT_TRUNCATED_HELLO, -2, "truncated HELLO"},
        {FAULT_OVERSIZED_HELLO, -2, "oversized HELLO"},
        {FAULT_TRUNCATED_TENSOR, -7, "truncated tensor"},
        {FAULT_DUPLICATE_HELLO, -2, "duplicate JSON field"}
    };
    size_t i;
    int rc;
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        rc = run_fault_then_recover(cases[i].fault, cases[i].expected);
        if (rc) {
            fprintf(stderr, "service boundary case failed: %s (code %d)\n", cases[i].label, rc);
            return 1;
        }
    }
    initialize_buffers();
    if (build_good_request()) return 2;
    if (execute_service("pcb", 9u) != -1 || infer_calls != 0 || !guards_ok()) return 3;
    if (run_valid()) return 4;
    initialize_buffers();
    if (build_good_request()) return 5;
    if (execute_service("pin", 18u) != -1 || infer_calls != 0 || !guards_ok()) return 6;
    if (run_valid()) return 7;
    initialize_buffers();
    if (build_good_request()) return 8;
    output_class = 9;
    if (execute_service("pin", 9u) != -11 || infer_calls != 1 ||
        !contains_reply("invalid detection output") || !guards_ok()) return 9;
    if (run_valid()) return 10;
    puts("PASS PIN640 service: fragmented I/O, protocol/identity/domain/length/digest/class faults, truncation, canaries, and recovery");
    return 0;
}
