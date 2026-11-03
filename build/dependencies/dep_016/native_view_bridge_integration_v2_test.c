#include "native_graph_conv_bridge_v2.h"
#include "native_scratch_bindings_v2.h"
#include "native_view_bindings_v1.h"
#include "graph_plan.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    RESULT_WORDS = 10,
    MAX_VIEWS = 32,
    MAX_SOURCE_NODES = 128,
    PATH_CAPACITY = 1024,
    HOST_EPOCH = 640
};

typedef struct ViewMeta {
    uint16_t event_index;
    uint16_t input_node;
    uint8_t read_count;
    size_t output_bytes;
} ViewMeta;

typedef struct SourceMeta {
    int32_t node;
    uint16_t channels;
    uint16_t height;
    uint16_t width;
    size_t bytes;
} SourceMeta;

typedef struct FixtureIndex {
    char root[PATH_CAPACITY];
    ViewMeta views[MAX_VIEWS];
    SourceMeta sources[MAX_SOURCE_NODES];
    unsigned int view_count;
    unsigned int source_count;
} FixtureIndex;

typedef struct BridgeMmio {
    uint32_t status;
    uint32_t bridge_error;
    uint32_t fault_code;
    uint32_t shadow[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t result[RESULT_WORDS];
    uint32_t expected_tiles;
    unsigned int start_count;
    unsigned int ack_count;
    unsigned int result_poll_count;
    unsigned int shadow_word_count;
    unsigned int shadow_words_total;
    unsigned int barrier_count;
} BridgeMmio;

typedef struct IntegrationTotals {
    unsigned int bound_views;
    unsigned int converted_views;
    unsigned int cache_clean_calls;
    unsigned int cache_busy_retries;
    unsigned int source_ready_checks;
    unsigned int output_invalidations;
    unsigned int publication_calls;
    unsigned int publication_busy_retries;
    unsigned int drains;
    unsigned int returned_reads;
    unsigned int scratch_releases;
    unsigned int scratch_release_busy_retries;
    unsigned int generic_run_acks;
    unsigned int command_words;
    unsigned int first_view_next_event_gated;
    uint64_t converted_bytes;
} IntegrationTotals;

typedef struct ViewContext {
    FixtureIndex *fixtures;
    IntegrationTotals *totals;
    BridgeMmio *mmio;
    ZnNativeViewSourceV1 sources[ZN_NATIVE_GRAPH_CONV_MAX_READS_V2];
    uint8_t *source_data[ZN_NATIVE_GRAPH_CONV_MAX_READS_V2];
    uint8_t *output;
    uint8_t *expected;
    size_t output_bytes;
    uint16_t input_node;
    uint16_t event_index;
    uint8_t source_count;
    uint32_t returned_mask;
    unsigned int mmio_ack_before;
    unsigned int mmio_start_before;
    unsigned int clean_busy_remaining;
    unsigned int publish_busy_remaining;
    unsigned int release_busy_remaining;
    int force_lease_failure;
    int force_publish_failure;
    int scratch_reserved;
    int scratch_released;
    int converted;
    int cleaned;
    int output_invalidated;
    int published;
    int drain_ready_seen;
    int write_actual;
} ViewContext;

static unsigned int failures;

static void
check(int condition, const char *name)
{
    if (!condition) {
        fprintf(stderr, "FAIL %s\n", name);
        ++failures;
    }
}

static int
ref_equal(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
path_join(char *output, size_t capacity, const char *root, const char *name)
{
    int length = snprintf(output, capacity, "%s/%s", root, name);
    return length >= 0 && (size_t)length < capacity;
}

static int
load_file(const char *path, uint8_t **data, size_t *bytes)
{
    FILE *stream;
    long length;
    uint8_t *buffer;

    stream = fopen(path, "rb");
    if (!stream)
        return -1;
    if (fseek(stream, 0, SEEK_END) != 0 || (length = ftell(stream)) < 0 ||
        fseek(stream, 0, SEEK_SET) != 0) {
        fclose(stream);
        return -1;
    }
    buffer = (uint8_t *)malloc((size_t)length ? (size_t)length : 1u);
    if (!buffer) {
        fclose(stream);
        return -1;
    }
    if (fread(buffer, 1, (size_t)length, stream) != (size_t)length ||
        fclose(stream) != 0) {
        free(buffer);
        return -1;
    }
    *data = buffer;
    *bytes = (size_t)length;
    return 0;
}

static int
load_fixture_index(FixtureIndex *fixtures, const char *root)
{
    char path[PATH_CAPACITY];
    FILE *stream;
    unsigned int event_index;
    unsigned int input_node;
    unsigned int read_count;
    unsigned int output_bytes;
    unsigned int node;
    unsigned int channels;
    unsigned int height;
    unsigned int width;
    unsigned int bytes;

    memset(fixtures, 0, sizeof *fixtures);
    if (strlen(root) >= sizeof fixtures->root ||
        !path_join(path, sizeof path, root, "views.tsv"))
        return -1;
    strcpy(fixtures->root, root);
    stream = fopen(path, "r");
    if (!stream)
        return -1;
    while (fscanf(stream, "%u %u %u %u", &event_index, &input_node,
                  &read_count, &output_bytes) == 4) {
        ViewMeta *meta;
        if (fixtures->view_count >= MAX_VIEWS || event_index >= 73 ||
            input_node > UINT16_MAX || read_count == 0 || read_count > 7 ||
            output_bytes == 0) {
            fclose(stream);
            return -1;
        }
        meta = &fixtures->views[fixtures->view_count++];
        meta->event_index = (uint16_t)event_index;
        meta->input_node = (uint16_t)input_node;
        meta->read_count = (uint8_t)read_count;
        meta->output_bytes = output_bytes;
    }
    if (ferror(stream) || fclose(stream) != 0)
        return -1;

    if (!path_join(path, sizeof path, root, "sources.tsv"))
        return -1;
    stream = fopen(path, "r");
    if (!stream)
        return -1;
    while (fscanf(stream, "%u %u %u %u %u", &node, &channels, &height,
                  &width, &bytes) == 5) {
        SourceMeta *meta;
        if (fixtures->source_count >= MAX_SOURCE_NODES || node > INT32_MAX ||
            channels == 0 || channels > UINT16_MAX || height == 0 ||
            height > UINT16_MAX || width == 0 || width > UINT16_MAX ||
            bytes == 0) {
            fclose(stream);
            return -1;
        }
        meta = &fixtures->sources[fixtures->source_count++];
        meta->node = (int32_t)node;
        meta->channels = (uint16_t)channels;
        meta->height = (uint16_t)height;
        meta->width = (uint16_t)width;
        meta->bytes = bytes;
    }
    if (ferror(stream) || fclose(stream) != 0)
        return -1;
    return fixtures->view_count == 21 && fixtures->source_count != 0 ? 0 : -1;
}

static const ViewMeta *
view_meta_for(const FixtureIndex *fixtures, uint16_t event_index)
{
    unsigned int index;
    for (index = 0; index < fixtures->view_count; ++index) {
        if (fixtures->views[index].event_index == event_index)
            return &fixtures->views[index];
    }
    return NULL;
}

static const SourceMeta *
source_meta_for(const FixtureIndex *fixtures, int32_t node)
{
    unsigned int index;
    for (index = 0; index < fixtures->source_count; ++index) {
        if (fixtures->sources[index].node == node)
            return &fixtures->sources[index];
    }
    return NULL;
}

static void
free_view_buffers(ViewContext *context)
{
    uint8_t index;
    if (!context)
        return;
    for (index = 0; index < ZN_NATIVE_GRAPH_CONV_MAX_READS_V2; ++index) {
        free(context->source_data[index]);
        context->source_data[index] = NULL;
        memset(&context->sources[index], 0, sizeof context->sources[index]);
    }
    free(context->output);
    free(context->expected);
    context->output = NULL;
    context->expected = NULL;
}

static int
prepare_view_context(ViewContext *context, const ZnRequest *request,
                     const ZnNativeGraphConvBindingV2 *binding)
{
    const ViewMeta *meta;
    char name[96];
    char path[PATH_CAPACITY];
    size_t bytes;
    uint8_t index;

    free_view_buffers(context);
    meta = view_meta_for(context->fixtures, request->event_index);
    if (!meta || meta->read_count != request->job->read_count ||
        meta->read_count != binding->graph_read_count ||
        meta->output_bytes != binding->source_span.bytes)
        return -1;
    context->event_index = request->event_index;
    context->input_node = meta->input_node;
    context->source_count = meta->read_count;
    context->output_bytes = meta->output_bytes;
    context->returned_mask = 0;
    context->scratch_reserved = 1;
    context->scratch_released = 0;
    context->converted = 0;
    context->cleaned = 0;
    context->output_invalidated = 0;
    context->published = 0;
    context->drain_ready_seen = 0;
    context->mmio_ack_before = context->mmio->ack_count;
    context->mmio_start_before = context->mmio->start_count;

    for (index = 0; index < context->source_count; ++index) {
        const ZnRef ref = request->job->reads[index];
        const SourceMeta *source_meta = source_meta_for(context->fixtures,
                                                         ref.tensor);
        if (!source_meta || !ref_equal(ref, binding->graph_read_refs[index]))
            return -1;
        if (snprintf(name, sizeof name, "source_%d.native.bin", ref.tensor) < 0 ||
            !path_join(path, sizeof path, context->fixtures->root, name) ||
            load_file(path, &context->source_data[index], &bytes) != 0 ||
            bytes != source_meta->bytes)
            return -1;
        context->sources[index].data = context->source_data[index];
        context->sources[index].bytes = bytes;
        context->sources[index].epoch = request->epoch;
        context->sources[index].ref = ref;
        context->sources[index].channels = source_meta->channels;
        context->sources[index].height = source_meta->height;
        context->sources[index].width = source_meta->width;
    }

    if (snprintf(name, sizeof name, "expected_%u.native.bin", meta->input_node) < 0 ||
        !path_join(path, sizeof path, context->fixtures->root, name) ||
        load_file(path, &context->expected, &bytes) != 0 ||
        bytes != context->output_bytes)
        return -1;
    context->output = (uint8_t *)malloc(context->output_bytes);
    if (!context->output)
        return -1;
    memset(context->output, 0xa5, context->output_bytes);
    return 0;
}

static int
host_ranges_overlap(const void *a, size_t a_bytes, const void *b, size_t b_bytes)
{
    uintptr_t a_begin = (uintptr_t)a;
    uintptr_t b_begin = (uintptr_t)b;
    uintptr_t a_end = a_begin + a_bytes;
    uintptr_t b_end = b_begin + b_bytes;
    return a_begin < b_end && b_begin < a_end;
}

static int
write_actual_view(ViewContext *context)
{
    char name[96];
    char path[PATH_CAPACITY];
    FILE *stream;
    int written;

    if (!context->write_actual)
        return 0;
    written = snprintf(name, sizeof name, "actual_event_%03u_node_%03u.native.bin",
                       context->event_index, context->input_node);
    if (written < 0 || (size_t)written >= sizeof name ||
        !path_join(path, sizeof path, context->fixtures->root, name))
        return -1;
    stream = fopen(path, "wb");
    if (!stream)
        return -1;
    if (fwrite(context->output, 1, context->output_bytes, stream) !=
            context->output_bytes || fclose(stream) != 0)
        return -1;
    return 0;
}

static int
hook_check_leases(void *opaque, const ZnRequest *request,
                  const ZnNativeGraphConvBindingV2 *binding)
{
    ViewContext *context = (ViewContext *)opaque;
    uint8_t index;

    if (!context || !request || !binding || context->force_lease_failure ||
        !context->scratch_reserved || context->scratch_released ||
        binding->scratch.epoch != request->epoch ||
        binding->scratch.generation != 800 ||
        binding->scratch.base != UINT32_C(0x22000000) ||
        binding->graph_read_count != context->source_count ||
        request->event_index != context->event_index)
        return -1;
    for (index = 0; index < context->source_count; ++index) {
        if (!context->source_data[index] ||
            !ref_equal(binding->graph_read_refs[index], request->job->reads[index]) ||
            !ref_equal(context->sources[index].ref, request->job->reads[index]) ||
            context->sources[index].epoch != request->epoch ||
            (context->output && host_ranges_overlap(context->source_data[index],
                    context->sources[index].bytes, context->output,
                    context->output_bytes)))
            return -1;
    }
    return 0;
}

static int
hook_convert_views(void *opaque, const ZnRequest *request,
                   const ZnNativeGraphConvBindingV2 *binding)
{
    ViewContext *context = (ViewContext *)opaque;
    int code;

    if (!context || !request || !binding || !context->output || !context->expected)
        return -1;
    code = zn_native_view_input_v1(request, context->sources,
                                   context->source_count, context->output,
                                   context->output_bytes);
    if (code != 0 || memcmp(context->output, context->expected,
                            context->output_bytes) != 0 ||
        write_actual_view(context) != 0)
        return -1;
    context->converted = 1;
    ++context->totals->converted_views;
    context->totals->converted_bytes += context->output_bytes;
    return 0;
}

static int
hook_clean_source(void *opaque, const ZnNativeGraphConvBindingV2 *binding)
{
    ViewContext *context = (ViewContext *)opaque;
    ++context->totals->cache_clean_calls;
    if (!context || !binding || !context->converted ||
        binding->source_span.bytes != context->output_bytes)
        return -1;
    if (context->clean_busy_remaining != 0) {
        --context->clean_busy_remaining;
        ++context->totals->cache_busy_retries;
        return 1;
    }
    context->cleaned = 1;
    return 0;
}

static int
hook_check_source_ready(void *opaque, const ZnRequest *request,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    ViewContext *context = (ViewContext *)opaque;
    ++context->totals->source_ready_checks;
    if (!context || !request || !binding || !context->converted ||
        !context->cleaned || !context->output || !context->expected ||
        memcmp(context->output, context->expected, context->output_bytes) != 0)
        return -1;
    return 0;
}

static int
hook_invalidate_output(void *opaque,
                       const ZnNativeGraphConvBindingV2 *binding)
{
    ViewContext *context = (ViewContext *)opaque;
    const uint32_t *result = context->mmio->result;
    ++context->totals->output_invalidations;
    if (!context || !binding ||
        !(context->mmio->status & ZN_NC_STATUS_DONE) ||
        !(context->mmio->status & ZN_NC_STATUS_RESULT_VALID) ||
        !(context->mmio->status & ZN_NC_STATUS_DRAIN_COMPLETE) ||
        result[0] != binding->command.request_cookie ||
        result[1] != binding->command.epoch ||
        result[2] != binding->command.event ||
        result[7] != binding->command.destination_generation ||
        result[8] != binding->expected_tiles ||
        result[9] != binding->scratch.generation)
        return -1;
    context->output_invalidated = 1;
    return 0;
}

static int
hook_publish(void *opaque, const ZnNativeGraphConvBindingV2 *binding)
{
    ViewContext *context = (ViewContext *)opaque;
    ++context->totals->publication_calls;
    if (!context || !binding || !context->output_invalidated ||
        context->mmio->ack_count != context->mmio_ack_before + 1u)
        return -1;
    if (context->force_publish_failure)
        return -1;
    if (context->publish_busy_remaining != 0) {
        --context->publish_busy_remaining;
        ++context->totals->publication_busy_retries;
        return 1;
    }
    context->published = 1;
    return 0;
}

static int
hook_drain_ready(void *opaque, const ZnRequest *request,
                 const ZnNativeGraphConvBindingV2 *binding)
{
    ViewContext *context = (ViewContext *)opaque;
    ++context->totals->drains;
    if (!context || !request || !binding || !context->published ||
        !context->cleaned || context->mmio->status !=
            (ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE) ||
        context->mmio->ack_count != context->mmio_ack_before + 1u)
        return -1;
    context->drain_ready_seen = 1;
    return 0;
}

static int
hook_return_graph_read(void *opaque, const ZnRequest *request,
                       const ZnNativeGraphConvBindingV2 *binding,
                       uint8_t read_index)
{
    ViewContext *context = (ViewContext *)opaque;
    if (!context || !request || !binding || !context->drain_ready_seen ||
        read_index >= context->source_count ||
        !ref_equal(request->ref, binding->graph_read_refs[read_index]))
        return -1;
    context->returned_mask |= UINT32_C(1) << read_index;
    ++context->totals->returned_reads;
    return 0;
}

static int
hook_release_scratch(void *opaque,
                     const ZnNativeGraphConvBindingV2 *binding)
{
    ViewContext *context = (ViewContext *)opaque;
    uint32_t all_reads;
    if (!context || !binding)
        return -1;
    all_reads = (UINT32_C(1) << context->source_count) - 1u;
    if (!context->scratch_reserved || !context->drain_ready_seen ||
        !context->published || context->returned_mask != all_reads ||
        context->mmio->ack_count != context->mmio_ack_before + 1u)
        return -1;
    if (context->release_busy_remaining != 0) {
        --context->release_busy_remaining;
        ++context->totals->scratch_release_busy_retries;
        return 1;
    }
    context->scratch_reserved = 0;
    context->scratch_released = 1;
    ++context->totals->scratch_releases;
    free_view_buffers(context);
    return 0;
}

static void
make_mmio_ops(BridgeMmio *mock, ZnNativeConvMmioOpsV2 *ops)
{
    ops->context = mock;
    ops->read32 = NULL;
    ops->write32 = NULL;
    ops->write_barrier = NULL;
}

static int
mock_read32(void *opaque, uint32_t offset, uint32_t *value)
{
    BridgeMmio *mock = (BridgeMmio *)opaque;
    unsigned int index;

    if (!mock || !value || (offset & 3u) != 0)
        return -1;
    if (offset == ZN_NC_REG_ID) {
        *value = ZN_NATIVE_CONV_MMIO_ID_VALUE;
        return 0;
    }
    if (offset == ZN_NC_REG_ABI_VERSION) {
        *value = ZN_NATIVE_CONV_MMIO_ABI_VERSION;
        return 0;
    }
    if (offset == ZN_NC_REG_CAPABILITIES) {
        *value = ZN_NC_CAP_VALID_MASK;
        return 0;
    }
    if (offset == ZN_NC_REG_STATUS) {
        if ((mock->status & ZN_NC_STATUS_ACCEPTED) &&
            !(mock->status & ZN_NC_STATUS_RESULT_VALID)) {
            mock->result[0] = mock->shadow[0];
            mock->result[1] = mock->shadow[1];
            mock->result[2] = mock->shadow[2];
            mock->result[3] = mock->shadow[3];
            mock->result[4] = mock->shadow[4];
            mock->result[5] = mock->shadow[5];
            mock->result[6] = mock->shadow[6];
            mock->result[7] = mock->shadow[14];
            mock->result[8] = mock->expected_tiles;
            mock->result[9] = mock->shadow[9];
            ++mock->result_poll_count;
            mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_DONE |
                           ZN_NC_STATUS_DRAIN_COMPLETE |
                           ZN_NC_STATUS_RESULT_VALID;
        }
        *value = mock->status;
        return 0;
    }
    if (offset == ZN_NC_REG_BRIDGE_ERROR) {
        *value = mock->bridge_error;
        return 0;
    }
    if (offset == ZN_NC_REG_BACKEND_FAULT_CODE) {
        *value = mock->fault_code;
        return 0;
    }
    if (offset >= ZN_NC_REG_RESULT_COOKIE &&
        offset <= ZN_NC_REG_RESULT_SOURCE_GEN) {
        index = (offset - ZN_NC_REG_RESULT_COOKIE) / 4u;
        if (index >= RESULT_WORDS)
            return -1;
        *value = mock->result[index];
        return 0;
    }
    return -1;
}

static int
mock_write32(void *opaque, uint32_t offset, uint32_t value)
{
    BridgeMmio *mock = (BridgeMmio *)opaque;
    unsigned int index;

    if (!mock)
        return -1;
    if (offset >= ZN_NC_REG_SHADOW_COOKIE &&
        offset <= ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT) {
        index = (offset - ZN_NC_REG_SHADOW_COOKIE) / 4u;
        if (index >= ZN_NATIVE_CONV_COMMAND_WORD_COUNT)
            return -1;
        mock->shadow[index] = value;
        ++mock->shadow_word_count;
        ++mock->shadow_words_total;
        return 0;
    }
    if (offset != ZN_NC_REG_CONTROL)
        return -1;
    if (value == ZN_NC_CONTROL_START) {
        if (mock->shadow_word_count != ZN_NATIVE_CONV_COMMAND_WORD_COUNT)
            return -1;
        ++mock->start_count;
        mock->result_poll_count = 0;
        mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE |
                       ZN_NC_STATUS_DRAIN_COMPLETE;
        return 0;
    }
    if (value == ZN_NC_CONTROL_ACK_RESULT) {
        ++mock->ack_count;
        mock->shadow_word_count = 0;
        mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
        return 0;
    }
    return -1;
}

static int
mock_barrier(void *opaque)
{
    BridgeMmio *mock = (BridgeMmio *)opaque;
    ++mock->barrier_count;
    return 0;
}

static void
make_hooks(ViewContext *context, ZnNativeGraphConvHooksV2 *hooks)
{
    hooks->context = context;
    hooks->check_leases = hook_check_leases;
    hooks->convert_views = hook_convert_views;
    hooks->clean_source = hook_clean_source;
    hooks->check_source_ready = hook_check_source_ready;
    hooks->invalidate_output = hook_invalidate_output;
    hooks->validate_and_publish = hook_publish;
    hooks->drain_ready = hook_drain_ready;
    hooks->return_graph_read = hook_return_graph_read;
    hooks->release_scratch = hook_release_scratch;
}

static void
reset_mmio(BridgeMmio *mock)
{
    memset(mock, 0, sizeof *mock);
    mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
}

static void
make_ids(uint16_t event_index, ZnNativeScratchIdsV2 *ids)
{
    ids->job_base = 1000u + (uint32_t)event_index * 32u;
    ids->token_base = 100000u + (uint32_t)event_index * 10000u;
    ids->tag_base = 10000000u + (uint32_t)event_index * 100000u;
    ids->load_timeout_cycles = 1000000u;
    ids->parameter_timeout_cycles = 1000000u;
    ids->write_timeout_cycles = 1000000u;
    ids->preaccept_timeout_cycles = 1000000u;
    ids->first_bank = (uint8_t)(event_index & 1u);
}

static int
make_scratch_binding(const ZnRequest *request,
                     ZnNativeGraphConvBindingV2 *binding)
{
    const ZnNativeGraphScratchLeaseV2 scratch = {
        request->epoch, 800, UINT32_C(0x22000000), UINT32_C(1228800)
    };
    ZnNativeScratchIdsV2 ids;
    make_ids(request->event_index, &ids);
    return zn_native_scratch_binding_v2(request, &ids, &scratch, binding);
}

static int
init_bridge(ViewContext *context, ZnNativeGraphConvBridgeV2 *bridge,
            ZnNativeConvMmioOpsV2 *mmio, ZnNativeGraphConvHooksV2 *hooks)
{
    make_mmio_ops(context->mmio, mmio);
    mmio->read32 = mock_read32;
    mmio->write32 = mock_write32;
    mmio->write_barrier = mock_barrier;
    make_hooks(context, hooks);
    return zn_native_graph_conv_bridge_init_v2(bridge, mmio, hooks) ==
           ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED ? 0 : -1;
}

static void
check_command_words(const BridgeMmio *mock,
                    const ZnNativeGraphConvBindingV2 *binding)
{
    uint32_t expected[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    unsigned int index;

    check(zn_native_conv_command_encode_v1(&binding->command, expected) ==
              ZN_NATIVE_CONV_COMMAND_OK,
          "encode generated scratch command fixture");
    for (index = 0; index < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++index)
        check(mock->shadow[index] == expected[index],
              "actual driver submitted generated scratch command word");
}

static ZnNativeGraphConvBridgeCodeV2
call_v2_until_ready(ViewContext *context, ZnNativeGraphConvBridgeV2 *bridge,
                    ZnDispatch *dispatch, const ZnRequest *request,
                    const ZnNativeGraphConvBindingV2 *binding,
                    unsigned int check_start)
{
    ZnNativeGraphConvBridgeCodeV2 code = ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
    unsigned int attempt;
    int checked_words = 0;

    for (attempt = 0; attempt < 32; ++attempt) {
        code = zn_native_graph_conv_bridge_step_v2(bridge, dispatch, request,
                                                   binding);
        if (check_start && !checked_words &&
            context->mmio->start_count > context->mmio_start_before) {
            check(context->mmio->shadow_word_count ==
                      ZN_NATIVE_CONV_COMMAND_WORD_COUNT,
                  "generated command starts after exactly 27 words");
            check_command_words(context->mmio, binding);
            context->mmio->shadow_word_count = 0;
            ++context->totals->command_words;
            checked_words = 1;
        }
        if (code != ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY)
            return code;
    }
    return code;
}

static int
advance_to_view_run(ZnDispatch *dispatch, uint16_t event_index,
                    ZnRequest *request, uint32_t epoch)
{
    int next;
    if (zn_dispatch_init(dispatch, z100_graph_events, 73, epoch) != 0)
        return -1;
    while ((next = zn_dispatch_next(dispatch, request)) == 1) {
        if (request->event_index == event_index && request->operation == ZN_RUN)
            return 0;
        if (request->event_index > event_index)
            return -1;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0)
            return -1;
    }
    return -1;
}

static int
prepare_error_case(FixtureIndex *fixtures, IntegrationTotals *totals,
                   ViewContext *context, ZnNativeGraphConvBridgeV2 *bridge,
                   ZnNativeConvMmioOpsV2 *mmio, ZnNativeGraphConvHooksV2 *hooks,
                   ZnDispatch *dispatch, ZnRequest *request,
                   ZnNativeGraphConvBindingV2 *binding, uint32_t epoch)
{
    int code;
    memset(context, 0, sizeof *context);
    context->fixtures = fixtures;
    context->totals = totals;
    context->mmio = (BridgeMmio *)malloc(sizeof *context->mmio);
    if (!context->mmio)
        return -1;
    reset_mmio(context->mmio);
    if (advance_to_view_run(dispatch, 3, request, epoch) != 0 ||
        make_scratch_binding(request, binding) != 0)
        return -1;
    context->write_actual = 0;
    if (prepare_view_context(context, request, binding) != 0)
        return -1;
    context->mmio->expected_tiles = binding->expected_tiles;
    code = init_bridge(context, bridge, mmio, hooks);
    return code;
}

static void
test_generated_view_lifecycles(FixtureIndex *fixtures, IntegrationTotals *totals)
{
    BridgeMmio mock;
    ViewContext context;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativeGraphConvBridgeV2 bridge;
    ZnDispatch dispatch;
    ZnRequest request;
    uint16_t active_event = UINT16_MAX;
    unsigned int selected = 0;
    unsigned int generic_runs = 0;
    unsigned int all_requests = 0;
    int next;

    memset(&context, 0, sizeof context);
    context.fixtures = fixtures;
    context.totals = totals;
    context.mmio = &mock;
    context.write_actual = 1;
    reset_mmio(&mock);
    check(init_bridge(&context, &bridge, &mmio, &hooks) == 0,
          "initialize V2 bridge against real generated binders and driver");
    check(zn_dispatch_init(&dispatch, z100_graph_events, 73, HOST_EPOCH) == 0,
          "initialize selected immutable graph plan");

    while ((next = zn_dispatch_next(&dispatch, &request)) == 1) {
        int handled = 0;
        ++all_requests;
        while (!handled) {
            if (bridge.stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED) {
                ZnNativeGraphConvBridgeCodeV2 code =
                    zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch,
                                                        &request, NULL);
                if (code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY)
                    continue;
                check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_SCRATCH_RELEASED,
                      "scratch finish precedes the next graph ACK");
                if (active_event == 3 && request.event_index == 4 &&
                    request.operation == ZN_ALLOCATE && !dispatch.pending) {
                    ++totals->first_view_next_event_gated;
                } else if (active_event == 3 && request.event_index == 4 &&
                           request.operation == ZN_ALLOCATE && dispatch.pending) {
                    ++totals->first_view_next_event_gated;
                }
                active_event = UINT16_MAX;
                handled = 1;
                break;
            }

            if (request.operation == ZN_RUN) {
                ZnNativeGraphConvBindingV2 binding;
                int bind_code = make_scratch_binding(&request, &binding);
                if (bind_code == 1) {
                    ++generic_runs;
                    ++totals->generic_run_acks;
                    check(zn_dispatch_ack(&dispatch, request.tag,
                                          request.operation, ZN_ACK_OK) == 0,
                          "non-view RUN is acknowledged only by test double");
                    handled = 1;
                    continue;
                }
                check(bind_code == 0,
                      "actual V2 scratch binder binds selected view event");
                if (bind_code != 0) {
                    handled = 1;
                    continue;
                }
                check(prepare_view_context(&context, &request, &binding) == 0,
                      "load frozen input-node fixtures for generated view");
                if (!context.output || !context.expected) {
                    handled = 1;
                    continue;
                }
                mock.expected_tiles = binding.expected_tiles;
                context.clean_busy_remaining = request.event_index == 3 ? 1u : 0u;
                context.publish_busy_remaining = request.event_index == 6 ? 1u : 0u;
                context.release_busy_remaining = request.event_index == 3 ? 1u : 0u;
                context.mmio_ack_before = mock.ack_count;
                context.mmio_start_before = mock.start_count;
                ++selected;
                ++totals->bound_views;
                check(call_v2_until_ready(&context, &bridge, &dispatch,
                                           &request, &binding, 1) ==
                          ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED,
                      "selected view RUN converts, executes driver protocol and publishes");
                active_event = request.event_index;
                handled = 1;
                continue;
            }

            if (active_event == request.event_index &&
                (request.operation == ZN_DRAIN || request.operation == ZN_RETURN)) {
                ZnNativeGraphConvBridgeCodeV2 code = call_v2_until_ready(
                    &context, &bridge, &dispatch, &request, NULL, 0);
                check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED,
                      "selected view DRAIN/RETURN waits on V2 bridge hooks");
                handled = 1;
                continue;
            }

            check(zn_dispatch_ack(&dispatch, request.tag, request.operation,
                                  ZN_ACK_OK) == 0,
                  "non-view graph control ACK is a test double");
            handled = 1;
        }
    }

    check(next == 0 && dispatch.done,
          "all 73 graph plan events finish in routing protocol model");
    check(selected == 21 && totals->bound_views == 21 &&
          totals->converted_views == 21 && totals->scratch_releases == 21,
          "all 21 generated view commands convert and release scratch");
    check(generic_runs == 52 && totals->returned_reads == 38 &&
          totals->command_words == 21 && mock.shadow_words_total == 21u * 27u,
          "event inventory is 21 actual view commands and 52 mock RUNs");
    check(totals->cache_busy_retries == 1 &&
          totals->publication_busy_retries == 1 &&
          totals->scratch_release_busy_retries == 1 &&
          totals->first_view_next_event_gated == 1,
          "cache, publication, and event9 next-work gates are exercised");
    check(mock.start_count == 21 && mock.ack_count == 21 &&
          mock.barrier_count == 21,
          "real driver submits and ACKs one command per selected view");
    free_view_buffers(&context);
}

static void
test_malformed_and_failure_cases(FixtureIndex *fixtures, IntegrationTotals *totals)
{
    ViewContext context;
    ZnNativeGraphConvBridgeV2 bridge;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 hooks;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnRequest stale;
    ZnNativeGraphConvBindingV2 binding;
    ZnNativeGraphScratchLeaseV2 bad_scratch;
    ZnNativeGraphConvBindingV2 untouched;
    ZnNativeGraphConvBindingV2 before;
    ZnNativeGraphConvBridgeCodeV2 code;

    check(prepare_error_case(fixtures, totals, &context, &bridge, &mmio, &hooks,
                             &dispatch, &request, &binding, 641) == 0,
          "prepare generated event9 error-case bridge");
    stale = request;
    ++stale.epoch;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &stale,
                                               &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST &&
          context.mmio->start_count == 0 && !context.converted && !dispatch.fault,
          "stale RUN request rejected before converter and MMIO");
    free_view_buffers(&context);
    free(context.mmio);

    check(prepare_error_case(fixtures, totals, &context, &bridge, &mmio, &hooks,
                             &dispatch, &request, &binding, 642) == 0,
          "prepare generated stale source lease case");
    ++context.sources[0].ref.generation;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                               &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED && dispatch.fault &&
          dispatch.pending && context.mmio->start_count == 0 &&
          !context.converted && context.scratch_reserved,
          "stale original source lease fails closed and keeps scratch reserved");
    free_view_buffers(&context);
    free(context.mmio);

    check(prepare_error_case(fixtures, totals, &context, &bridge, &mmio, &hooks,
                             &dispatch, &request, &binding, 643) == 0,
          "prepare actual converter input rejection case");
    ++context.sources[0].channels;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                               &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED && dispatch.fault &&
          context.mmio->start_count == 0 && !context.cleaned &&
          context.scratch_reserved,
          "actual converter rejects malformed source shape before first write");
    {
        size_t index;
        for (index = 0; index < context.output_bytes; ++index)
            check(context.output[index] == UINT8_C(0xa5),
                  "converter rejection preserves output scratch bytes");
    }
    free_view_buffers(&context);
    free(context.mmio);

    check(prepare_error_case(fixtures, totals, &context, &bridge, &mmio, &hooks,
                             &dispatch, &request, &binding, 644) == 0,
          "prepare generated scratch alias rejection case");
    bad_scratch.epoch = request.epoch;
    bad_scratch.generation = 800;
    bad_scratch.base = UINT32_C(0x20000000);
    bad_scratch.bytes = UINT32_C(1228800);
    memset(&untouched, 0x5a, sizeof untouched);
    before = untouched;
    {
        ZnNativeScratchIdsV2 ids;
        make_ids(request.event_index, &ids);
        check(zn_native_scratch_binding_v2(&request, &ids, &bad_scratch,
                                            &untouched) == -1 &&
              memcmp(&untouched, &before, sizeof untouched) == 0 &&
              context.mmio->start_count == 0,
              "scratch binder rejects parameter alias without changing output binding");
    }
    free_view_buffers(&context);
    free(context.mmio);

    check(prepare_error_case(fixtures, totals, &context, &bridge, &mmio, &hooks,
                             &dispatch, &request, &binding, 645) == 0,
          "prepare publication failure case");
    context.force_publish_failure = 1;
    code = call_v2_until_ready(&context, &bridge, &dispatch, &request,
                               &binding, 1);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED && dispatch.fault &&
          dispatch.pending && context.mmio->start_count == 1 &&
          context.mmio->ack_count == 1 && context.converted && context.cleaned &&
          !context.published && context.scratch_reserved &&
          !context.scratch_released && context.returned_mask == 0,
          "publication failure retains scratch and graph refs without ledger publish");
    free_view_buffers(&context);
    free(context.mmio);
}

int
main(int argc, char **argv)
{
    FixtureIndex fixtures;
    IntegrationTotals totals;

    memset(&totals, 0, sizeof totals);
    if (argc != 2 || load_fixture_index(&fixtures, argv[1]) != 0) {
        fprintf(stderr, "FIXTURE_INDEX_FAIL\n");
        return 2;
    }
    test_generated_view_lifecycles(&fixtures, &totals);
    test_malformed_and_failure_cases(&fixtures, &totals);
    if (failures != 0) {
        fprintf(stderr, "NATIVE_VIEW_BRIDGE_INTEGRATION_V2_HOST_FAIL count=%u\n",
                failures);
        return 1;
    }
    printf("NATIVE_VIEW_BRIDGE_INTEGRATION_V2_HOST_PASS views=%u converted=%u reads=%u words=%u bytes=%llu cache_busy=%u publish_busy=%u scratch_release=%u next_event_gate=%u stale_request=1 stale_source=1 source_shape_reject=1 scratch_alias=1 publish_fail=1 driver_protocol_only=1 arithmetic_claim=0\n",
           totals.bound_views, totals.converted_views, totals.returned_reads,
           totals.command_words * ZN_NATIVE_CONV_COMMAND_WORD_COUNT,
           (unsigned long long)totals.converted_bytes,
           totals.cache_busy_retries, totals.publication_busy_retries,
           totals.scratch_releases, totals.first_view_next_event_gated);
    return 0;
}
