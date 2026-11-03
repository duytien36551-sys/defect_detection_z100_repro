#include "native_arena_nonconv_lifecycle_v1.h"
#include "native_nonconv_v1.h"
#include "graph_plan.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

enum {
    SOURCE_CAPACITY = 819200,
    OUTPUT_CAPACITY = 819200,
    ADD_EVENT_INDEX = 5,
    POOL_EVENT_INDEX = 32,
    HEADS_EVENT_INDEX = 72,
    MAX_SOURCES = 6
};

typedef struct SourceFixture {
    uint16_t node;
    uint16_t channels;
    uint16_t height;
    uint16_t width;
    const char *path;
} SourceFixture;

typedef struct TargetFixture {
    uint16_t event_index;
    uint16_t event_id;
    uint8_t source_count;
    const SourceFixture *sources;
    const char *expected_path;
    uint16_t output_channels;
    uint16_t output_height;
    uint16_t output_width;
    size_t output_bytes;
    uint8_t destinationless;
} TargetFixture;

typedef struct LifecycleFixture {
    ZnNativeArenaConfigV1 config;
    ZnNativeArenaOwnerV1 owner;
    ZnDispatch dispatch;
    ZnNativeArenaNonConvLifecycleV1 lifecycle;
    ZnNativeArenaNonConvHooksV1 hooks;
    const TargetFixture *target;
    uint8_t map_busy_index;
    uint8_t map_busy_remaining;
    uint8_t visible_busy_index;
    uint8_t visible_busy_remaining;
    uint8_t output_map_busy_remaining;
    uint8_t output_clean_busy_remaining;
    uint8_t publish_busy_remaining;
    uint8_t drain_busy_remaining;
    uint8_t return_busy_index;
    uint8_t return_busy_remaining;
    int corrupt_source_ref_index;
    int corrupt_source_address_index;
    uint8_t wrong_output_address;
    uint8_t fail_source_visible;
    uint8_t fail_output_clean;
    uint8_t fail_publish;
    uint8_t fail_drain;
    uint8_t fail_return;
    uint8_t published;
    uint8_t returned_mask;
    uint32_t map_source_calls;
    uint32_t source_visible_calls;
    uint32_t map_output_calls;
    uint32_t output_clean_calls;
    uint32_t publish_calls;
    uint32_t drain_calls;
    uint32_t return_calls;
    uint32_t callback_order_errors;
} LifecycleFixture;

static const SourceFixture add_sources[] = {
    { 5, 32, 160, 160,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_005_silu_nchw_int8.bin" },
    { 11, 16, 160, 160,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_011_silu_nchw_int8.bin" }
};

static const SourceFixture pool_sources[] = {
    { 69, 128, 20, 20,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_069_silu_nchw_int8.bin" }
};

static const SourceFixture heads_sources[] = {
    { 134, 64, 80, 80,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_134_conv_nchw_int8.bin" },
    { 139, 9, 80, 80,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_139_conv_nchw_int8.bin" },
    { 145, 64, 40, 40,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_145_conv_nchw_int8.bin" },
    { 150, 9, 40, 40,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_150_conv_nchw_int8.bin" },
    { 156, 64, 20, 20,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_156_conv_nchw_int8.bin" },
    { 161, 9, 20, 20,
      "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_161_conv_nchw_int8.bin" }
};

static const TargetFixture targets[] = {
    {
        ADD_EVENT_INDEX, 12, 2, add_sources,
        "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_012_add_nchw_int8.bin",
        16, 160, 160, 409600, 0
    },
    {
        POOL_EVENT_INDEX, 70, 1, pool_sources,
        "deployment/build/z100_native_graph_goldens/20261026T020836.911372Z/graph_outputs/node_070_maxpool_nchw_int8.bin",
        128, 20, 20, 81920, 0
    },
    {
        HEADS_EVENT_INDEX, 163, 6, heads_sources,
        "validation/board_z100/pin640_epoch200_headconcat_host/20261024T104121.305479Z/expected_heads_int8.bin",
        0, 0, 0, ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1, 1
    }
};

static const ZnNativeArenaRegionV1 arena_regions[
    ZN_NATIVE_ARENA_SLOT_COUNT_V1] = {
    { UINT32_C(268435456), UINT32_C(1638400) },
    { UINT32_C(270073856), UINT32_C(1638400) },
    { UINT32_C(271712256), UINT32_C(819200) },
    { UINT32_C(272531456), UINT32_C(409600) },
    { UINT32_C(272941056), UINT32_C(409600) },
    { UINT32_C(273350656), UINT32_C(122880) },
    { UINT32_C(273473536), UINT32_C(163840) }
};

static uint8_t source_nchw[MAX_SOURCES][SOURCE_CAPACITY];
static uint8_t source_native[MAX_SOURCES][SOURCE_CAPACITY];
static uint8_t expected_nchw[OUTPUT_CAPACITY];
static uint8_t expected_native[OUTPUT_CAPACITY];
static uint8_t output_storage[OUTPUT_CAPACITY];
static const char *actual_output_dir;
static unsigned int failures;

static void
check(int condition, const char *message)
{
    if (!condition) {
        ++failures;
        fprintf(stderr, "FAIL: %s\n", message);
    }
}

static int
ref_equal(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static size_t
packed_bytes(uint16_t channels, uint16_t height, uint16_t width)
{
    return (size_t)((channels + 3u) / 4u) * height *
           ((width + 15u) / 16u) * 64u;
}

static size_t
native_offset(uint16_t channels, uint16_t height, uint16_t width,
              uint16_t channel, uint16_t y, uint16_t x)
{
    size_t xwords = (width + 15u) / 16u;
    size_t group_first = channel / 32u * 32u;
    size_t group_channels = channels - group_first < 32u ?
        channels - group_first : 32u;
    size_t groups = (group_channels + 3u) / 4u;

    return ((group_first / 4u) * height * xwords +
            ((size_t)y * xwords + x / 16u) * groups +
            (channel % 32u) / 4u) * 64u +
           (channel % 4u) * 16u + x % 16u;
}

static int
read_exact_file(const char *path, uint8_t *output, size_t expected_bytes)
{
    FILE *stream = fopen(path, "rb");
    size_t read_bytes;
    int extra;

    if (!stream)
        return -1;
    read_bytes = fread(output, 1, expected_bytes, stream);
    extra = fgetc(stream);
    fclose(stream);
    return read_bytes == expected_bytes && extra == EOF ? 0 : -1;
}

static int
load_nchw_and_pack(const char *path, uint16_t channels, uint16_t height,
                   uint16_t width, uint8_t *nchw, uint8_t *native,
                   size_t native_capacity, size_t *native_size)
{
    size_t nchw_bytes = (size_t)channels * height * width;
    size_t bytes = packed_bytes(channels, height, width);
    uint16_t channel;
    uint16_t y;
    uint16_t x;

    if (bytes == 0 || bytes > native_capacity ||
        read_exact_file(path, nchw, nchw_bytes) != 0)
        return -1;
    memset(native, 0, bytes);
    for (channel = 0; channel < channels; ++channel) {
        for (y = 0; y < height; ++y) {
            for (x = 0; x < width; ++x) {
                size_t input_index =
                    ((size_t)channel * height + y) * width + x;
                native[native_offset(channels, height, width,
                                     channel, y, x)] = nchw[input_index];
            }
        }
    }
    *native_size = bytes;
    return 0;
}

static uint64_t
fnv64(const uint8_t *bytes, size_t count)
{
    uint64_t hash = UINT64_C(1469598103934665603);
    size_t index;

    for (index = 0; index < count; ++index) {
        hash ^= bytes[index];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static ZnNativeArenaConfigV1
make_config(void)
{
    ZnNativeArenaConfigV1 config;
    memset(&config, 0, sizeof config);
    config.arena_base = UINT32_C(268435456);
    config.arena_end = UINT32_C(273637376);
    config.arena_bytes = UINT32_C(5201920);
    config.alignment = 4096;
    memcpy(config.slots, arena_regions, sizeof arena_regions);
    memcpy(config.package_sha256, ZN_NATIVE_ARENA_PACKAGE_SHA256_V1,
           sizeof config.package_sha256);
    memcpy(config.graph_sha256, ZN_NATIVE_ARENA_GRAPH_SHA256_V1,
           sizeof config.graph_sha256);
    memcpy(config.plan_sha256, ZN_NATIVE_ARENA_PLAN_SHA256_V1,
           sizeof config.plan_sha256);
    memcpy(config.manifest_sha256, ZN_NATIVE_ARENA_MANIFEST_SHA256_V1,
           sizeof config.manifest_sha256);
    return config;
}

static ZnNativeArenaCompletionEvidenceV1
synthetic_completion(const ZnRequest *request)
{
    ZnNativeArenaCompletionEvidenceV1 evidence;
    memset(&evidence, 0, sizeof evidence);
    evidence.epoch = request->epoch;
    evidence.run_tag = request->tag;
    evidence.event_index = request->event_index;
    evidence.result_identity_verified = 1;
    evidence.driver_terminal_success = 1;
    if (request->job->has_destination) {
        evidence.destination_ref = request->job->destination.ref;
        evidence.destination_bytes = request->job->destination.bytes;
        evidence.output_cache_visible = 1;
    }
    return evidence;
}

static int
complete_synthetic_prefix_request(ZnNativeArenaOwnerV1 *owner,
                                  ZnDispatch *dispatch,
                                  const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 code;

    if (request->operation == ZN_RUN) {
        ZnNativeArenaCompletionEvidenceV1 completion =
            synthetic_completion(request);
        code = zn_native_arena_owner_step_v1(owner, dispatch, request);
        if (code != ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND ||
            zn_native_arena_owner_run_started_v1(owner, dispatch, request) !=
                ZN_NATIVE_ARENA_OWNER_V1_ACKED)
            return -1;
        code = request->job->has_destination ?
            zn_native_arena_owner_publish_v1(owner, dispatch, request,
                                               &completion) :
            zn_native_arena_owner_complete_without_output_v1(
                owner, dispatch, request, &completion);
        if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
            return -1;
        return zn_native_arena_owner_step_v1(owner, dispatch, request) ==
                       ZN_NATIVE_ARENA_OWNER_V1_ACKED ? 0 : -1;
    }
    if (request->operation == ZN_DRAIN) {
        ZnNativeArenaQuiescenceEvidenceV1 evidence;
        memset(&evidence, 0, sizeof evidence);
        evidence.epoch = request->epoch;
        evidence.run_tag = owner->event_state[request->event_index].run_tag;
        evidence.event_index = request->event_index;
        evidence.all_read_io_quiet = 1;
        evidence.all_write_io_quiet = 1;
        evidence.driver_terminal = 1;
        if (zn_native_arena_owner_step_v1(owner, dispatch, request) !=
                ZN_NATIVE_ARENA_OWNER_V1_BUSY ||
            zn_native_arena_owner_notify_quiescent_v1(
                owner, dispatch, request, &evidence) !=
                ZN_NATIVE_ARENA_OWNER_V1_ACKED)
            return -1;
    }
    return zn_native_arena_owner_step_v1(owner, dispatch, request) ==
                   ZN_NATIVE_ARENA_OWNER_V1_ACKED ? 0 : -1;
}

static int
complete_synthetic_prefix(ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
                          uint16_t target_index)
{
    ZnRequest request;

    while (dispatch->cursor < target_index) {
        if (zn_dispatch_next(dispatch, &request) != 1 ||
            request.event_index != dispatch->cursor ||
            complete_synthetic_prefix_request(owner, dispatch, &request) != 0)
            return -1;
    }
    return dispatch->cursor == target_index ? 0 : -1;
}

static int
map_source(void *context, const ZnRequest *request, uint8_t read_index,
           uint32_t expected_address, uint32_t expected_bytes,
           ZnNativeArenaNonConvSourceV1 *source)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    const SourceFixture *source_fixture;
    size_t native_size;

    if (!fixture || !request || !source ||
        read_index >= fixture->target->source_count) {
        if (fixture)
            ++fixture->callback_order_errors;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    }
    ++fixture->map_source_calls;
    source_fixture = &fixture->target->sources[read_index];
    if (request->job->reads[read_index].tensor != source_fixture->node ||
        !ref_equal(request->job->reads[read_index],
                   fixture->owner.events[request->event_index].reads[read_index]))
        ++fixture->callback_order_errors;
    if (fixture->map_busy_remaining != 0 &&
        fixture->map_busy_index == read_index) {
        --fixture->map_busy_remaining;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    if (load_nchw_and_pack(source_fixture->path, source_fixture->channels,
                           source_fixture->height, source_fixture->width,
                           source_nchw[read_index], source_native[read_index],
                           sizeof source_native[read_index], &native_size) != 0 ||
        native_size != expected_bytes)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;

    source->physical_address = expected_address;
    source->view.data = source_native[read_index];
    source->view.bytes = native_size;
    source->view.epoch = request->epoch;
    source->view.ref = request->job->reads[read_index];
    source->view.channels = source_fixture->channels;
    source->view.height = source_fixture->height;
    source->view.width = source_fixture->width;
    if (fixture->corrupt_source_ref_index == read_index)
        ++source->view.ref.generation;
    if (fixture->corrupt_source_address_index == read_index)
        source->physical_address += 64;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
source_visible(void *context, const ZnRequest *request, uint8_t read_index,
               const ZnNativeArenaNonConvSourceV1 *source)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    (void)request;
    (void)source;
    ++fixture->source_visible_calls;
    if (fixture->visible_busy_remaining != 0 &&
        fixture->visible_busy_index == read_index) {
        --fixture->visible_busy_remaining;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    if (fixture->fail_source_visible)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
map_output(void *context, const ZnRequest *request, uint32_t expected_address,
           uint32_t output_bytes, ZnNativeArenaNonConvOutputV1 *output)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    (void)request;
    ++fixture->map_output_calls;
    if (fixture->output_map_busy_remaining != 0) {
        --fixture->output_map_busy_remaining;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    output->physical_address = expected_address;
    if (fixture->wrong_output_address)
        output->physical_address += 64;
    output->data = output_storage;
    output->capacity_bytes = output_bytes;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
clean_output(void *context, const ZnRequest *request,
             const ZnNativeArenaNonConvOutputV1 *output,
             uint32_t output_bytes)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    (void)request;
    (void)output;
    (void)output_bytes;
    ++fixture->output_clean_calls;
    if (fixture->output_clean_busy_remaining != 0) {
        --fixture->output_clean_busy_remaining;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    return fixture->fail_output_clean ?
        ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1 :
        ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
publish_output(void *context, const ZnRequest *request,
               const ZnNativeArenaNonConvOutputV1 *output,
               uint32_t output_bytes)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    (void)request;
    (void)output;
    (void)output_bytes;
    ++fixture->publish_calls;
    if (fixture->publish_busy_remaining != 0) {
        --fixture->publish_busy_remaining;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    if (fixture->fail_publish)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    fixture->published = 1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
drain_ready(void *context, const ZnRequest *request,
            ZnNativeArenaQuiescenceEvidenceV1 *evidence)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    ++fixture->drain_calls;
    if (fixture->drain_busy_remaining != 0) {
        --fixture->drain_busy_remaining;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    if (fixture->fail_drain)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    evidence->epoch = request->epoch;
    evidence->run_tag = fixture->owner.event_state[request->event_index].run_tag;
    evidence->event_index = request->event_index;
    evidence->all_read_io_quiet = 1;
    evidence->all_write_io_quiet = 1;
    evidence->driver_terminal = 1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
return_graph_read(void *context, const ZnRequest *request, uint8_t read_index,
                  uint32_t physical_address, ZnRef ref)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    const ZnNativeArenaSlotV1 *slot;
    ++fixture->return_calls;
    if (read_index >= request->job->read_count ||
        !ref_equal(ref, request->job->reads[read_index])) {
        ++fixture->callback_order_errors;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    }
    if (ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1) {
        ++fixture->callback_order_errors;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    }
    slot = &fixture->owner.slots[ref.slot];
    if (slot->region.address != physical_address)
        ++fixture->callback_order_errors;
    if (fixture->return_busy_remaining != 0 &&
        fixture->return_busy_index == read_index) {
        --fixture->return_busy_remaining;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    if (fixture->fail_return)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    fixture->returned_mask |= (uint8_t)(UINT32_C(1) << read_index);
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
load_target_fixtures(const TargetFixture *target)
{
    uint8_t index;
    size_t expected_native_size;

    if (!target || target->source_count > MAX_SOURCES)
        return -1;
    memset(source_nchw, 0, sizeof source_nchw);
    memset(source_native, 0, sizeof source_native);
    memset(expected_nchw, 0, sizeof expected_nchw);
    memset(expected_native, 0, sizeof expected_native);
    memset(output_storage, 0, sizeof output_storage);
    for (index = 0; index < target->source_count; ++index) {
        const SourceFixture *source = &target->sources[index];
        size_t native_size;
        if (load_nchw_and_pack(source->path, source->channels,
                               source->height, source->width,
                               source_nchw[index], source_native[index],
                               sizeof source_native[index], &native_size) != 0)
            return -1;
    }
    if (target->destinationless) {
        if (read_exact_file(target->expected_path, expected_nchw,
                            target->output_bytes) != 0)
            return -1;
        return 0;
    }
    if (load_nchw_and_pack(target->expected_path, target->output_channels,
                           target->output_height, target->output_width,
                           expected_nchw, expected_native,
                           sizeof expected_native,
                           &expected_native_size) != 0 ||
        expected_native_size != target->output_bytes)
        return -1;
    return 0;
}

static int
setup_fixture(LifecycleFixture *fixture, const TargetFixture *target,
              uint32_t epoch)
{
    memset(fixture, 0, sizeof *fixture);
    fixture->target = target;
    fixture->corrupt_source_ref_index = -1;
    fixture->corrupt_source_address_index = -1;
    fixture->return_busy_index = UINT8_MAX;
    fixture->config = make_config();
    if (load_target_fixtures(target) != 0 ||
        zn_dispatch_init(&fixture->dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, epoch) != 0 ||
        zn_native_arena_owner_init_v1(&fixture->owner, &fixture->config,
                                      &fixture->dispatch, epoch) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED ||
        complete_synthetic_prefix(&fixture->owner, &fixture->dispatch,
                                  target->event_index) != 0)
        return -1;

    fixture->hooks.context = fixture;
    fixture->hooks.map_source = map_source;
    fixture->hooks.source_visible = source_visible;
    fixture->hooks.map_output = map_output;
    fixture->hooks.clean_output = clean_output;
    fixture->hooks.publish_output = publish_output;
    fixture->hooks.drain_ready = drain_ready;
    fixture->hooks.return_graph_read = return_graph_read;
    if (zn_native_arena_nonconv_lifecycle_init_v1(
            &fixture->lifecycle, &fixture->owner, &fixture->hooks) !=
        ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED)
        return -1;
    return 0;
}

static int
next_request(ZnDispatch *dispatch, ZnRequest *request)
{
    int result = zn_dispatch_next(dispatch, request);
    return result == 1 ? 0 : -1;
}

static int
advance_to_run(LifecycleFixture *fixture, ZnRequest *run_request)
{
    ZnRequest request;

    while (fixture->dispatch.cursor == fixture->target->event_index) {
        ZnNativeArenaNonConvLifecycleCodeV1 code;
        if (next_request(&fixture->dispatch, &request) != 0)
            return -1;
        if (request.operation == ZN_RUN) {
            *run_request = request;
            return 0;
        }
        code = zn_native_arena_nonconv_lifecycle_step_v1(
            &fixture->lifecycle, &fixture->dispatch, &request);
        if (code != ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED)
            return -1;
    }
    return -1;
}

static int
step_until_not_busy(LifecycleFixture *fixture, const ZnRequest *request,
                    ZnNativeArenaNonConvLifecycleCodeV1 *final_code)
{
    unsigned int attempt;

    for (attempt = 0; attempt < 64; ++attempt) {
        *final_code = zn_native_arena_nonconv_lifecycle_step_v1(
            &fixture->lifecycle, &fixture->dispatch, request);
        if (*final_code != ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY)
            return 0;
    }
    return -1;
}

static int
drive_target(LifecycleFixture *fixture)
{
    unsigned int requests = 0;

    while (fixture->dispatch.cursor == fixture->target->event_index) {
        ZnRequest request;
        ZnNativeArenaNonConvLifecycleCodeV1 code;
        int next_result;
        if (++requests > 64)
            return -1;
        next_result = zn_dispatch_next(&fixture->dispatch, &request);
        if (next_result == 0)
            break;
        if (next_result != 1 ||
            request.event_index != fixture->target->event_index)
            break;
        if (step_until_not_busy(fixture, &request, &code) != 0 ||
            code != ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED)
            return -1;
    }
    return fixture->dispatch.cursor == fixture->target->event_index + 1u ?
        0 : -1;
}

static int
write_actual_output(uint16_t event_id, const uint8_t *bytes, size_t count)
{
    char path[1024];
    FILE *stream;
    int length = snprintf(path, sizeof path, "%s/event_%u.bin",
                          actual_output_dir, event_id);

    if (length <= 0 || (size_t)length >= sizeof path)
        return -1;
    stream = fopen(path, "wb");
    if (!stream)
        return -1;
    if (fwrite(bytes, 1, count, stream) != count) {
        fclose(stream);
        return -1;
    }
    return fclose(stream) == 0 ? 0 : -1;
}

static const ZnNativeArenaSlotV1 *
target_destination_slot(const LifecycleFixture *fixture)
{
    const ZnEvent *event = &z100_graph_events[fixture->target->event_index];
    if (!event->has_destination ||
        event->destination.ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return NULL;
    return &fixture->owner.slots[event->destination.ref.slot];
}

static int
test_add_retry_and_publication(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    ZnNativeArenaNonConvLifecycleCodeV1 code;

    if (setup_fixture(&fixture, &targets[0], 301) != 0) {
        check(0, "ADD lifecycle fixture initializes with captured assertions");
        return -1;
    }
    fixture.map_busy_index = 0;
    fixture.map_busy_remaining = 1;
    fixture.visible_busy_index = 1;
    fixture.visible_busy_remaining = 1;
    fixture.output_map_busy_remaining = 1;
    fixture.output_clean_busy_remaining = 1;
    fixture.publish_busy_remaining = 1;
    fixture.drain_busy_remaining = 1;
    fixture.return_busy_index = 0;
    fixture.return_busy_remaining = 1;
    check(advance_to_run(&fixture, &request) == 0 &&
          request.event_index == ADD_EVENT_INDEX && request.job->event == 12,
          "event 12 reaches its exact owner RUN request");
    code = zn_native_arena_nonconv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &request);
    check(code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY,
          "event 12 mapping BUSY preserves its RUN request");
    check(step_until_not_busy(&fixture, &request, &code) == 0 &&
          code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED,
          "event 12 computes, cleans, publishes, and acknowledges once");
    check(fixture.lifecycle.operator_call_count == 1 &&
          fixture.publish_calls == 2 && fixture.output_clean_calls == 2 &&
          fixture.map_output_calls == 2,
          "event 12 BUSY retries do not rerun compute or cleaning");
    check(drive_target(&fixture) == 0 && fixture.dispatch.cursor == 6,
          "event 12 DRAIN, ordered RETURN, and RETIRE complete");
    check(fixture.owner.event_state[ADD_EVENT_INDEX].output_published &&
          fixture.owner.event_state[ADD_EVENT_INDEX].drained &&
          fixture.owner.event_state[ADD_EVENT_INDEX].returned_mask == 3 &&
          fixture.owner.event_state[ADD_EVENT_INDEX].retired_mask == 1 &&
          fixture.returned_mask == 3 && fixture.callback_order_errors == 0,
          "event 12 exact owner refs and retirement are recorded");
    check(memcmp(output_storage, expected_native, targets[0].output_bytes) == 0,
          "event 12 native output matches its captured assertion after packing");
    check(write_actual_output(12, output_storage, targets[0].output_bytes) == 0,
          "event 12 output artifact is written for SHA validation");
    printf("NATIVE_ARENA_NONCONV_LIFECYCLE_OUTPUT_PASS event=12 name=add bytes=%zu fnv64=%016" PRIx64 "\n",
           targets[0].output_bytes, fnv64(output_storage,
                                          targets[0].output_bytes));
    return 0;
}

static int
test_pool_event(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    ZnNativeArenaNonConvLifecycleCodeV1 code;

    if (setup_fixture(&fixture, &targets[1], 302) != 0) {
        check(0, "Pool lifecycle fixture initializes with captured assertions");
        return -1;
    }
    check(advance_to_run(&fixture, &request) == 0 &&
          request.event_index == POOL_EVENT_INDEX && request.job->event == 70 &&
          request.job->read_count == 1 &&
          ref_equal(request.job->reads[0], (ZnRef){ 33, 69, 0 }),
          "event 70 uses its exact one-read generation");
    check(step_until_not_busy(&fixture, &request, &code) == 0 &&
          code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED,
          "event 70 frozen Pool operator completes");
    check(drive_target(&fixture) == 0 &&
          fixture.owner.event_state[POOL_EVENT_INDEX].returned_mask == 1 &&
          fixture.owner.event_state[POOL_EVENT_INDEX].drained &&
          fixture.lifecycle.operator_call_count == 1 &&
          fixture.callback_order_errors == 0,
          "event 70 drains and returns its exact source");
    check(memcmp(output_storage, expected_native, targets[1].output_bytes) == 0,
          "event 70 native output matches its captured assertion after packing");
    check(write_actual_output(70, output_storage, targets[1].output_bytes) == 0,
          "event 70 output artifact is written for SHA validation");
    printf("NATIVE_ARENA_NONCONV_LIFECYCLE_OUTPUT_PASS event=70 name=pool bytes=%zu fnv64=%016" PRIx64 "\n",
           targets[1].output_bytes, fnv64(output_storage,
                                          targets[1].output_bytes));
    return 0;
}

static int
test_heads_destinationless(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    ZnNativeArenaNonConvLifecycleCodeV1 code;
    int drive_result;

    if (setup_fixture(&fixture, &targets[2], 303) != 0) {
        check(0, "HEADS lifecycle fixture initializes with captured assertions");
        return -1;
    }
    fixture.drain_busy_remaining = 1;
    fixture.return_busy_index = 4;
    fixture.return_busy_remaining = 1;
    check(advance_to_run(&fixture, &request) == 0 &&
          request.event_index == HEADS_EVENT_INDEX && request.job->event == 163 &&
          request.job->read_count == 6 && !request.job->has_destination,
          "event 163 reaches its destinationless six-read RUN request");
    check(step_until_not_busy(&fixture, &request, &code) == 0 &&
          code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED,
          "event 163 frozen HEADS operator completes without publication");
    check(!fixture.published && fixture.publish_calls == 0 &&
          fixture.output_clean_calls == 0 &&
          fixture.owner.event_state[HEADS_EVENT_INDEX].run_completed &&
          fixture.owner.event_state[HEADS_EVENT_INDEX].output_published == 0,
          "HEADS uses complete_without_output with no destination publication");
    drive_result = drive_target(&fixture);
    check(drive_result == 0,
          "event 163 DRAIN, six RETURNs, and RETIREs complete");
    check(fixture.returned_mask == 0x3f,
          "event 163 runtime read returns cover all six ordered inputs");
    check(fixture.owner.event_state[HEADS_EVENT_INDEX].drained,
          "event 163 owner records DRAIN quiescence");
    check(fixture.lifecycle.operator_call_count == 1,
          "event 163 operator executes exactly once");
    check(fixture.callback_order_errors == 0,
          "event 163 runtime callbacks see exact read order and addresses");
    check(memcmp(output_storage, expected_nchw, targets[2].output_bytes) == 0,
          "event 163 logical head bytes match the captured head assertion");
    check(write_actual_output(163, output_storage,
                              targets[2].output_bytes) == 0,
          "event 163 output artifact is written for SHA validation");
    printf("NATIVE_ARENA_NONCONV_LIFECYCLE_OUTPUT_PASS event=163 name=heads bytes=%zu fnv64=%016" PRIx64 " output_published=0\n",
           targets[2].output_bytes, fnv64(output_storage,
                                          targets[2].output_bytes));
    return 0;
}

static int
test_stale_source_reference(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    const ZnEvent *event = &z100_graph_events[ADD_EVENT_INDEX];
    ZnNativeArenaNonConvLifecycleCodeV1 code;

    if (setup_fixture(&fixture, &targets[0], 304) != 0) {
        check(0, "stale source fixture initializes");
        return -1;
    }
    fixture.corrupt_source_ref_index = 0;
    check(advance_to_run(&fixture, &request) == 0,
          "stale source fixture reaches RUN");
    code = zn_native_arena_nonconv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &request);
    check(code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED &&
          fixture.owner.fault && fixture.dispatch.fault &&
          fixture.lifecycle.operator_call_count == 0,
          "stale mapped ref fails before compute and faults the pending RUN");
    check(fixture.owner.slots[event->reads[0].slot].reader_count != 0 &&
          fixture.owner.slots[event->destination.ref.slot].state ==
              ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
          !fixture.owner.event_state[ADD_EVENT_INDEX].output_published,
          "stale source failure retains reader lease and destination reservation");
    return 0;
}

static int
test_bad_physical_mapping(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    const ZnEvent *event = &z100_graph_events[ADD_EVENT_INDEX];
    ZnNativeArenaNonConvLifecycleCodeV1 code;

    if (setup_fixture(&fixture, &targets[0], 305) != 0) {
        check(0, "physical mapping fixture initializes");
        return -1;
    }
    fixture.wrong_output_address = 1;
    check(advance_to_run(&fixture, &request) == 0,
          "physical mapping fixture reaches RUN");
    code = zn_native_arena_nonconv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &request);
    check(code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED &&
          fixture.lifecycle.operator_call_count == 0 && fixture.owner.fault &&
          fixture.dispatch.fault,
          "output mapping at the wrong physical address is rejected pre-compute");
    check(fixture.owner.slots[event->reads[0].slot].reader_count != 0 &&
          fixture.owner.slots[event->destination.ref.slot].state ==
              ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
          fixture.owner.slots[event->destination.ref.slot].io_count == 0,
          "bad output address preserves acquired readers and reserved output");
    return 0;
}

static int
test_output_clean_failure(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    const ZnEvent *event = &z100_graph_events[ADD_EVENT_INDEX];
    const ZnNativeArenaSlotV1 *destination;
    ZnNativeArenaNonConvLifecycleCodeV1 code;

    if (setup_fixture(&fixture, &targets[0], 306) != 0) {
        check(0, "output clean failure fixture initializes");
        return -1;
    }
    fixture.fail_output_clean = 1;
    check(advance_to_run(&fixture, &request) == 0,
          "output clean failure fixture reaches RUN");
    code = zn_native_arena_nonconv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &request);
    destination = target_destination_slot(&fixture);
    check(code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED &&
          fixture.lifecycle.operator_call_count == 1 && fixture.owner.fault &&
          fixture.dispatch.fault && !fixture.owner.event_state[ADD_EVENT_INDEX].output_published,
          "output clean failure retains the completed but unpublished RUN");
    check(destination && destination->state == ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
          destination->io_count != 0 &&
          fixture.owner.slots[event->reads[0].slot].reader_count != 0,
          "output clean failure retains destination IO and source reader ownership");
    return 0;
}

static int
test_publication_failure(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    const ZnEvent *event = &z100_graph_events[ADD_EVENT_INDEX];
    const ZnNativeArenaSlotV1 *destination;
    ZnNativeArenaNonConvLifecycleCodeV1 code;

    if (setup_fixture(&fixture, &targets[0], 307) != 0) {
        check(0, "publication failure fixture initializes");
        return -1;
    }
    fixture.fail_publish = 1;
    check(advance_to_run(&fixture, &request) == 0,
          "publication failure fixture reaches RUN");
    code = zn_native_arena_nonconv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &request);
    destination = target_destination_slot(&fixture);
    check(code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED &&
          fixture.lifecycle.operator_call_count == 1 && fixture.owner.fault &&
          fixture.dispatch.fault && !fixture.published &&
          !fixture.owner.event_state[ADD_EVENT_INDEX].output_published,
          "publication failure never marks output visible in the owner");
    check(destination && destination->state == ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
          destination->io_count != 0 &&
          fixture.owner.slots[event->reads[0].slot].reader_count != 0,
          "publication failure retains destination IO and source reader ownership");
    return 0;
}

static int
test_cache_visibility_failure(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    const ZnEvent *event = &z100_graph_events[ADD_EVENT_INDEX];
    ZnNativeArenaNonConvLifecycleCodeV1 code;

    if (setup_fixture(&fixture, &targets[0], 308) != 0) {
        check(0, "source visibility failure fixture initializes");
        return -1;
    }
    fixture.fail_source_visible = 1;
    check(advance_to_run(&fixture, &request) == 0,
          "source visibility failure fixture reaches RUN");
    code = zn_native_arena_nonconv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &request);
    check(code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED &&
          fixture.lifecycle.operator_call_count == 0 && fixture.owner.fault &&
          fixture.dispatch.fault &&
          !fixture.owner.event_state[ADD_EVENT_INDEX].run_started,
          "source cache visibility failure prevents backend start and compute");
    check(fixture.owner.slots[event->reads[0].slot].reader_count != 0 &&
          fixture.owner.slots[event->destination.ref.slot].state ==
              ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
          fixture.owner.slots[event->destination.ref.slot].io_count == 0,
          "visibility failure retains readers and reservation without IO ownership");
    return 0;
}

int
main(int argc, char **argv)
{
    if (argc != 2 || !argv[1] || argv[1][0] == '\0') {
        fprintf(stderr, "usage: native_arena_nonconv_lifecycle_v1_test <output-dir>\n");
        return 2;
    }
    actual_output_dir = argv[1];
    test_add_retry_and_publication();
    test_pool_event();
    test_heads_destinationless();
    test_stale_source_reference();
    test_bad_physical_mapping();
    test_output_clean_failure();
    test_publication_failure();
    test_cache_visibility_failure();
    if (failures != 0) {
        fprintf(stderr,
                "NATIVE_ARENA_NONCONV_LIFECYCLE_HOST_FAIL count=%u\n",
                failures);
        return 1;
    }
    printf("NATIVE_ARENA_NONCONV_LIFECYCLE_HOST_PASS events=3 operator_calls=3 source_map_busy=1 source_visible_busy=1 output_map_busy=1 output_clean_busy=1 publication_busy=1 drain_wait=1 return_busy=1 stale_source_ref=1 bad_output_address=1 cache_visibility_failure=1 output_clean_failure=1 publication_failure=1 heads_destinationless=1 synthetic_prefix=1 physical_arena_claim=0\n");
    return 0;
}
