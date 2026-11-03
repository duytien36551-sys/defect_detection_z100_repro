#include "native_postprocess_epoch200_v1.h"

#include "v8_decode_int8.h"

#include <string.h>

enum {
    HEAD0_BYTES = 73 * 80 * 80,
    HEAD1_BYTES = 73 * 40 * 40,
    HEAD2_BYTES = 73 * 20 * 20
};

static const V8Epoch200Identity expected_identity = {
    .package_sha256 = "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c",
    .checkpoint_sha256 = "2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6",
    .graph_sha256 = "9d6064e37e92e61c687608d2c5e216cccb31e0b1fc9603de0c8b21eb3acbae9f",
    .classes_sha256 = "d194f74601c88214c24506a910c1bac71c87ce0be7ddda213d3eb00684d43754",
    .generated_header_sha256 = "83d3a64b6deccd8ef3f54680ea5714d1ada9c2faff5c105974d0a47c338e5e2c",
    .batch = 1,
    .input_channels = 3,
    .input_width = 640,
    .input_height = 640,
    .classes = 9,
    .reg_max = 16,
    .head_count = V8_EPOCH200_HEAD_COUNT,
    .heads = {
        {140, 73, 80, 80, 8, 0.17005741690087506},
        {151, 73, 40, 40, 16, 0.13697987654077726},
        {162, 73, 20, 20, 32, 0.06606479892580529}
    }
};

static int same_string(const char *actual, const char *expected) {
    return actual && strcmp(actual, expected) == 0;
}

static int identity_matches(const V8Epoch200Identity *identity) {
    size_t i;

    if (!identity ||
        !same_string(identity->package_sha256, expected_identity.package_sha256) ||
        !same_string(identity->checkpoint_sha256, expected_identity.checkpoint_sha256) ||
        !same_string(identity->graph_sha256, expected_identity.graph_sha256) ||
        !same_string(identity->classes_sha256, expected_identity.classes_sha256) ||
        !same_string(identity->generated_header_sha256,
                     expected_identity.generated_header_sha256) ||
        identity->batch != expected_identity.batch ||
        identity->input_channels != expected_identity.input_channels ||
        identity->input_width != expected_identity.input_width ||
        identity->input_height != expected_identity.input_height ||
        identity->classes != expected_identity.classes ||
        identity->reg_max != expected_identity.reg_max ||
        identity->head_count != expected_identity.head_count)
        return 0;

    for (i = 0; i < V8_EPOCH200_HEAD_COUNT; ++i) {
        const V8Epoch200HeadIdentity *actual = &identity->heads[i];
        const V8Epoch200HeadIdentity *expected = &expected_identity.heads[i];
        if (actual->node_id != expected->node_id ||
            actual->channels != expected->channels ||
            actual->height != expected->height ||
            actual->width != expected->width ||
            actual->stride != expected->stride ||
            actual->scale != expected->scale)
            return 0;
    }
    return 1;
}

const V8Epoch200Identity *v8_epoch200_expected_identity(void) {
    return &expected_identity;
}

int v8_native_postprocess_epoch200_v1(
    const int8_t *raw_heads, size_t raw_bytes,
    const V8Epoch200Identity *identity,
    const V8DecodeConfig *config,
    V8Detection *output, size_t output_capacity, size_t *out_count) {
    static const size_t head_bytes[V8_EPOCH200_HEAD_COUNT] = {
        HEAD0_BYTES, HEAD1_BYTES, HEAD2_BYTES
    };
    V8Int8Head heads[V8_EPOCH200_HEAD_COUNT];
    size_t offset = 0;
    size_t decoded_count = 0;
    size_t i;
    int status;

    if (!raw_heads || raw_bytes != V8_EPOCH200_RAW_BYTES ||
        !identity_matches(identity) || !config || !output ||
        !output_capacity || !out_count ||
        config->input_width != expected_identity.input_width ||
        config->input_height != expected_identity.input_height ||
        config->classes != expected_identity.classes ||
        config->reg_max != expected_identity.reg_max)
        return V8_DECODE_INVALID;

    for (i = 0; i < V8_EPOCH200_HEAD_COUNT; ++i) {
        const V8Epoch200HeadIdentity *shape = &expected_identity.heads[i];
        heads[i].data = raw_heads + offset;
        heads[i].data_bytes = head_bytes[i];
        heads[i].width = shape->width;
        heads[i].height = shape->height;
        heads[i].stride = shape->stride;
        heads[i].scale = shape->scale;
        offset += head_bytes[i];
    }
    if (offset != raw_bytes) return V8_DECODE_INVALID;

    status = v8_decode_int8(heads, V8_EPOCH200_HEAD_COUNT, config, output,
                            output_capacity, &decoded_count);
    if (status == V8_DECODE_OK) *out_count = decoded_count;
    return status;
}
