#include "native_arena_conv_lifecycle_v1.h"
#include "native_feature_cache_v1.h"
#include "graph_plan.h"

#include <stdio.h>
#include <string.h>

#define main native_graph_conv_bridge_v2_fixture_main
#include "native_graph_conv_bridge_v2_test.c"
#undef main

enum {
    CACHE_EVENT_9_INDEX = 3,
    CACHE_EVENT_34_INDEX = 15,
    CACHE_ARENA_BYTES = 5201920,
    CACHE_SOURCE_CAPACITY = 1228800,
    CACHE_TRACE_CAPACITY = 16
};

typedef enum CacheMappingMode {
    CACHE_MAPPING_NORMAL = 0,
    CACHE_MAPPING_CPU_ALIAS
} CacheMappingMode;

typedef enum CacheResultField {
    CACHE_RESULT_COOKIE = 0,
    CACHE_RESULT_EPOCH,
    CACHE_RESULT_EVENT,
    CACHE_RESULT_MODEL_CRC32,
    CACHE_RESULT_JOB_BASE,
    CACHE_RESULT_TOKEN_BASE,
    CACHE_RESULT_TAG_BASE,
    CACHE_RESULT_DESTINATION_GENERATION,
    CACHE_RESULT_COMMITTED_TILES,
    CACHE_RESULT_SOURCE_GENERATION,
    CACHE_RESULT_FIELD_COUNT
} CacheResultField;

typedef struct CacheFixture {
    BridgeMmio mock;
    HookState hooks;
    ZnNativeArenaConfigV1 config;
    ZnNativeArenaOwnerV1 owner;
    ZnDispatch dispatch;
    ZnNativeArenaConvLifecycleV1 lifecycle;
    ZnNativeGraphConvBindingV2 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 runtime_hooks;
    ZnNativeFeatureCacheV1 cache;
    ZnNativePlatformMemoryOpsV1 memory_ops;
    ZnNativePlatformMappedSpanV1 source_mapping;
    ZnNativePlatformMappedSpanV1 arena_mapping;
    CacheMappingMode mapping_mode;
    char trace[CACHE_TRACE_CAPACITY];
    unsigned int trace_count;
    unsigned int invalidate_calls;
    unsigned int fail_invalidate_call;
    unsigned int converter_calls;
    unsigned int release_calls;
    unsigned int release_busy_remaining;
    unsigned int identity_checked;
    int scratch_owned;
    int output_visible_before_driver_ack;
} CacheFixture;

_Alignas(64) static uint8_t cache_test_arena[CACHE_ARENA_BYTES];
_Alignas(64) static uint8_t cache_test_source[CACHE_SOURCE_CAPACITY];

static const ZnNativeArenaRegionV1 cache_test_regions[
    ZN_NATIVE_ARENA_SLOT_COUNT_V1] = {
    { UINT32_C(268435456), UINT32_C(1638400) },
    { UINT32_C(270073856), UINT32_C(1638400) },
    { UINT32_C(271712256), UINT32_C(819200) },
    { UINT32_C(272531456), UINT32_C(409600) },
    { UINT32_C(272941056), UINT32_C(409600) },
    { UINT32_C(273350656), UINT32_C(122880) },
    { UINT32_C(273473536), UINT32_C(163840) }
};

static size_t
cache_test_tensor_bytes(uint16_t channels, uint16_t height, uint16_t width)
{
    return (size_t)((channels + 3u) / 4u) * height *
           ((width + 15u) / 16u) * 64u;
}

static ZnNativeArenaConfigV1
cache_test_config(void)
{
    ZnNativeArenaConfigV1 config;
    memset(&config, 0, sizeof config);
    config.arena_base = UINT32_C(268435456);
    config.arena_end = UINT32_C(273637376);
    config.arena_bytes = CACHE_ARENA_BYTES;
    config.alignment = 4096;
    memcpy(config.slots, cache_test_regions, sizeof config.slots);
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
cache_test_completion(const ZnRequest *request)
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
cache_test_complete_prefix_request(ZnNativeArenaOwnerV1 *owner,
                                   ZnDispatch *dispatch,
                                   const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 code;
    if (request->operation == ZN_RUN) {
        ZnNativeArenaCompletionEvidenceV1 completion =
            cache_test_completion(request);
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
cache_test_complete_prefix(ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
                           uint16_t target_index)
{
    ZnRequest request;
    while (dispatch->cursor < target_index) {
        if (zn_dispatch_next(dispatch, &request) != 1 ||
            request.event_index != dispatch->cursor ||
            cache_test_complete_prefix_request(owner, dispatch, &request) != 0)
            return -1;
    }
    return dispatch->cursor == target_index ? 0 : -1;
}

static int
cache_test_read32(void *context, uint32_t offset, uint32_t *value)
{
    CacheFixture *fixture = (CacheFixture *)context;
    return mock_read32(&fixture->mock, offset, value);
}

static int
cache_test_write32(void *context, uint32_t offset, uint32_t value)
{
    CacheFixture *fixture = (CacheFixture *)context;
    return mock_write32(&fixture->mock, offset, value);
}

static int
cache_test_mmio_barrier(void *context)
{
    CacheFixture *fixture = (CacheFixture *)context;
    return mock_barrier(&fixture->mock);
}

static int
cache_test_trace(CacheFixture *fixture, char event)
{
    if (fixture->trace_count >= sizeof fixture->trace)
        return -1;
    fixture->trace[fixture->trace_count++] = event;
    return 0;
}

static uint8_t *
cache_test_destination_cpu(CacheFixture *fixture,
                           const ZnNativeGraphConvBindingV2 *binding)
{
    uint64_t offset = (uint64_t)binding->command.destination_base -
                      fixture->config.arena_base;
    return cache_test_arena + (size_t)offset;
}

static int
cache_test_cache_clean(void *context, void *address, size_t bytes)
{
    CacheFixture *fixture = (CacheFixture *)context;
    const ZnEvent *event = &fixture->dispatch.events[
        fixture->binding.event_index];
    if (address == fixture->source_mapping.cpu_base &&
        bytes == fixture->source_mapping.bytes)
        return cache_test_trace(fixture, 'S');
    if (address == cache_test_destination_cpu(fixture, &fixture->binding) &&
        bytes == event->destination.bytes)
        return cache_test_trace(fixture, 'D');
    return -1;
}

static int
cache_test_barrier(void *context)
{
    return cache_test_trace((CacheFixture *)context, 'B');
}

static int
cache_test_invalidate(void *context, void *address, size_t bytes)
{
    CacheFixture *fixture = (CacheFixture *)context;
    const ZnEvent *event = &fixture->dispatch.events[
        fixture->binding.event_index];
    int output_phase;

    if (address != cache_test_destination_cpu(fixture, &fixture->binding) ||
        bytes != event->destination.bytes ||
        cache_test_trace(fixture, 'I') != 0)
        return -1;
    ++fixture->invalidate_calls;
    output_phase = fixture->cache.stage ==
                   ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED;
    if (fixture->fail_invalidate_call != 0 &&
        fixture->invalidate_calls == fixture->fail_invalidate_call)
        return -1;
    if (output_phase) {
        fixture->output_visible_before_driver_ack =
            fixture->lifecycle.bridge.stage ==
                ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED &&
            fixture->lifecycle.bridge.driver.state ==
                ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT &&
            fixture->lifecycle.bridge.driver.result_verified &&
            fixture->lifecycle.bridge.driver.ownership_held &&
            fixture->mock.ack_count == 0;
    }
    return 0;
}

static int
cache_test_release_scratch(void *context,
                           const ZnNativeGraphScratchLeaseV2 *lease)
{
    CacheFixture *fixture = (CacheFixture *)context;
    ++fixture->release_calls;
    if (!lease || lease->epoch != fixture->binding.scratch.epoch ||
        lease->generation != fixture->binding.scratch.generation ||
        lease->base != fixture->binding.scratch.base ||
        lease->bytes != fixture->binding.scratch.bytes ||
        !fixture->scratch_owned || !fixture->lifecycle.finishing ||
        fixture->lifecycle.bridge.driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(
            &fixture->lifecycle.bridge.driver) ||
        !fixture->owner.event_state[fixture->binding.event_index].io_quiescent ||
        fixture->owner.event_state[fixture->binding.event_index].returned_mask !=
            (uint8_t)((UINT32_C(1) << fixture->binding.graph_read_count) - 1u))
        return -1;
    if (fixture->release_busy_remaining != 0) {
        --fixture->release_busy_remaining;
        return 1;
    }
    fixture->scratch_owned = 0;
    fixture->hooks.scratch_reserved = 0;
    fixture->hooks.scratch_released = 1;
    return 0;
}

static int
cache_test_map_mappings(CacheFixture *fixture,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnEvent *event = &fixture->dispatch.events[binding->event_index];
    uint64_t destination_offset;
    uint8_t *source_cpu = cache_test_source;

    if (event->destination.address < fixture->config.arena_base)
        return -1;
    destination_offset = (uint64_t)event->destination.address -
                         fixture->config.arena_base;
    if (destination_offset > fixture->config.arena_bytes ||
        event->destination.bytes > fixture->config.arena_bytes - destination_offset)
        return -1;
    if (fixture->mapping_mode == CACHE_MAPPING_CPU_ALIAS)
        source_cpu = cache_test_arena + (size_t)destination_offset;

    fixture->source_mapping.physical_base = binding->source_span.base;
    fixture->source_mapping.bytes = binding->source_span.bytes;
    fixture->source_mapping.cpu_base = source_cpu;
    fixture->source_mapping.cpu_bytes = binding->source_span.bytes;
    fixture->arena_mapping.physical_base = fixture->config.arena_base;
    fixture->arena_mapping.bytes = fixture->config.arena_bytes;
    fixture->arena_mapping.cpu_base = cache_test_arena;
    fixture->arena_mapping.cpu_bytes = fixture->config.arena_bytes;
    return 0;
}

static int
cache_test_callback_code(ZnNativeFeatureCacheCodeV1 code)
{
    if (code == ZN_NATIVE_FEATURE_CACHE_V1_READY)
        return 0;
    if (code == ZN_NATIVE_FEATURE_CACHE_V1_BUSY)
        return 1;
    return -1;
}

static int
cache_test_check_leases(void *context, const ZnRequest *request,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    CacheFixture *fixture = (CacheFixture *)context;
    ZnNativeFeatureCacheCodeV1 code;

    if (!request || !binding)
        return -1;
    if (fixture->cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_EMPTY) {
        if (cache_test_map_mappings(fixture, binding) != 0)
            return -1;
        code = zn_native_feature_cache_bind_v1(
            &fixture->cache, &fixture->lifecycle, &fixture->dispatch,
            request, binding, &fixture->source_mapping,
            &fixture->arena_mapping);
        if (code != ZN_NATIVE_FEATURE_CACHE_V1_READY)
            return cache_test_callback_code(code);
    }
    code = zn_native_feature_cache_check_binding_v1(
        &fixture->cache, &fixture->lifecycle, request, binding);
    if (code != ZN_NATIVE_FEATURE_CACHE_V1_READY)
        return cache_test_callback_code(code);
    return hook_check_leases(&fixture->hooks, request, binding);
}

static int
cache_test_convert(void *context, const ZnRequest *request,
                   const ZnNativeGraphConvBindingV2 *binding)
{
    CacheFixture *fixture = (CacheFixture *)context;
    (void)request;
    if (!binding || binding->source_span.bytes > sizeof cache_test_source)
        return -1;
    memset(cache_test_source, 0x5c, binding->source_span.bytes);
    ++fixture->converter_calls;
    fixture->hooks.converted = 1;
    return 0;
}

static int
cache_test_clean_source(void *context,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    CacheFixture *fixture = (CacheFixture *)context;
    ZnNativeFeatureCacheCodeV1 code;
    if (!binding || !fixture->hooks.converted)
        return -1;
    code = zn_native_feature_cache_prepare_v1(&fixture->cache, binding);
    if (code == ZN_NATIVE_FEATURE_CACHE_V1_READY)
        fixture->hooks.cleaned = 1;
    return cache_test_callback_code(code);
}

static int
cache_test_check_source_ready(void *context, const ZnRequest *request,
                              const ZnNativeGraphConvBindingV2 *binding)
{
    CacheFixture *fixture = (CacheFixture *)context;
    int code = hook_check_source_ready(&fixture->hooks, request, binding);
    if (code != 0)
        return code;
    return cache_test_callback_code(
        zn_native_feature_cache_check_source_ready_v1(
            &fixture->cache, &fixture->lifecycle, request, binding));
}

static void
cache_test_corrupt_result_field(ZnNativeConvResultV2 *result,
                                CacheResultField field)
{
    switch (field) {
    case CACHE_RESULT_COOKIE: result->request_cookie ^= 1u; break;
    case CACHE_RESULT_EPOCH: result->epoch ^= 1u; break;
    case CACHE_RESULT_EVENT: result->event ^= 1u; break;
    case CACHE_RESULT_MODEL_CRC32: result->model_crc32 ^= 1u; break;
    case CACHE_RESULT_JOB_BASE: result->job_base ^= 1u; break;
    case CACHE_RESULT_TOKEN_BASE: result->token_base ^= 1u; break;
    case CACHE_RESULT_TAG_BASE: result->tag_base ^= 1u; break;
    case CACHE_RESULT_DESTINATION_GENERATION:
        result->destination_generation ^= 1u;
        break;
    case CACHE_RESULT_COMMITTED_TILES: result->committed_tiles ^= 1u; break;
    case CACHE_RESULT_SOURCE_GENERATION: result->source_generation ^= 1u; break;
    default: break;
    }
}

static int
cache_test_invalidate_output(void *context,
                             const ZnNativeGraphConvBindingV2 *binding)
{
    CacheFixture *fixture = (CacheFixture *)context;
    ZnNativeFeatureCacheCodeV1 code;
    if (!binding)
        return -1;
    if (!fixture->identity_checked) {
        ZnNativeConvResultV2 verified = fixture->lifecycle.bridge.driver.result;
        unsigned int trace_before = fixture->trace_count;
        CacheResultField field;
        fixture->identity_checked = 1;
        for (field = CACHE_RESULT_COOKIE;
             field < CACHE_RESULT_FIELD_COUNT; ++field) {
            ZnNativeConvResultV2 corrupt = verified;
            cache_test_corrupt_result_field(&corrupt, field);
            fixture->lifecycle.bridge.driver.result = corrupt;
            code = zn_native_feature_cache_make_output_visible_v1(
                &fixture->cache, &fixture->lifecycle, binding);
            check(code == ZN_NATIVE_FEATURE_CACHE_V1_BUSY &&
                  fixture->trace_count == trace_before &&
                  fixture->mock.ack_count == 0 &&
                  fixture->cache.stage ==
                      ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED,
                  "cache adapter rejects each mismatched result identity field before invalidation");
            fixture->lifecycle.bridge.driver.result = verified;
        }
    }
    code = zn_native_feature_cache_make_output_visible_v1(
        &fixture->cache, &fixture->lifecycle, binding);
    if (code == ZN_NATIVE_FEATURE_CACHE_V1_READY)
        fixture->hooks.output_invalidated = 1;
    return cache_test_callback_code(code);
}

static int
cache_test_publish(void *context,
                   const ZnNativeGraphConvBindingV2 *binding)
{
    CacheFixture *fixture = (CacheFixture *)context;
    if (fixture->cache.stage !=
            ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE ||
        !fixture->hooks.output_invalidated || fixture->mock.ack_count != 1)
        return -1;
    return hook_publish(&fixture->hooks, binding);
}

static int
cache_test_drain_ready(void *context, const ZnRequest *request,
                       const ZnNativeGraphConvBindingV2 *binding)
{
    CacheFixture *fixture = (CacheFixture *)context;
    return hook_drain_ready(&fixture->hooks, request, binding);
}

static int
cache_test_return_read(void *context, const ZnRequest *request,
                       const ZnNativeGraphConvBindingV2 *binding,
                       uint8_t read_index)
{
    CacheFixture *fixture = (CacheFixture *)context;
    return hook_return_graph_read(&fixture->hooks, request, binding,
                                  read_index);
}

static int
cache_test_release_hook(void *context,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    CacheFixture *fixture = (CacheFixture *)context;
    ZnNativeFeatureCacheCodeV1 code =
        zn_native_feature_cache_release_scratch_v1(
            &fixture->cache, &fixture->lifecycle, binding);
    return cache_test_callback_code(code);
}

static void
cache_test_make_binding(CacheFixture *fixture, const ZnRequest *request)
{
    uint64_t destination_end;
    uint64_t scratch_end;
    size_t output_bytes;

    make_binding(&fixture->binding, request);
    output_bytes = request->event_index == CACHE_EVENT_9_INDEX ?
        cache_test_tensor_bytes(16, 160, 160) :
        cache_test_tensor_bytes(128, 80, 80);
    fixture->binding.scratch.base = UINT32_C(0x22000000);
    fixture->binding.scratch.bytes = UINT32_C(1048576);
    fixture->binding.source_span.base = fixture->binding.scratch.base;
    fixture->binding.source_span.bytes = (uint32_t)output_bytes;
    fixture->binding.command.source_base = fixture->binding.source_span.base;
    fixture->binding.command.source_generation =
        fixture->binding.scratch.generation;
    fixture->binding.command.source_lease_region_begin =
        fixture->binding.scratch.base;
    scratch_end = (uint64_t)fixture->binding.scratch.base +
                  fixture->binding.scratch.bytes;
    fixture->binding.command.source_lease_region_end.low =
        (uint32_t)scratch_end;
    fixture->binding.command.source_lease_region_end.high =
        (uint8_t)(scratch_end >> 32);
    fixture->binding.command.destination_reservation_region_begin =
        request->job->destination.address;
    destination_end = (uint64_t)request->job->destination.address +
                      request->job->destination.bytes;
    fixture->binding.command.destination_reservation_region_end.low =
        (uint32_t)destination_end;
    fixture->binding.command.destination_reservation_region_end.high =
        (uint8_t)(destination_end >> 32);
    fixture->mock.expected_tiles = fixture->binding.expected_tiles;
}

static int
cache_test_init_adapter(CacheFixture *fixture)
{
    fixture->memory_ops.cache_clean = cache_test_cache_clean;
    fixture->memory_ops.barrier = cache_test_barrier;
    fixture->memory_ops.invalidate_readback = cache_test_invalidate;
    fixture->scratch_owned = 1;
    return zn_native_feature_cache_init_v1(
        &fixture->cache, &fixture->memory_ops, fixture,
        cache_test_release_scratch, fixture) ==
            ZN_NATIVE_FEATURE_CACHE_V1_READY ? 0 : -1;
}

static int
cache_test_setup(CacheFixture *fixture, uint16_t event_index, uint32_t epoch)
{
    ZnNativeGraphConvHooksV2 unused_hooks;
    ZnRequest request;

    memset(fixture, 0, sizeof *fixture);
    memset(cache_test_arena, 0, sizeof cache_test_arena);
    memset(cache_test_source, 0, sizeof cache_test_source);
    fixture->config = cache_test_config();
    if (zn_dispatch_init(&fixture->dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, epoch) != 0 ||
        zn_native_arena_owner_init_v1(&fixture->owner, &fixture->config,
                                      &fixture->dispatch, epoch) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED ||
        cache_test_complete_prefix(&fixture->owner, &fixture->dispatch,
                                   event_index) != 0)
        return -1;

    mock_reset(&fixture->mock);
    make_hooks(&fixture->hooks, &fixture->mock,
               z100_graph_events[event_index].read_count, &unused_hooks);
    fixture->mmio.context = fixture;
    fixture->mmio.read32 = cache_test_read32;
    fixture->mmio.write32 = cache_test_write32;
    fixture->mmio.write_barrier = cache_test_mmio_barrier;
    fixture->runtime_hooks.context = fixture;
    fixture->runtime_hooks.check_leases = cache_test_check_leases;
    fixture->runtime_hooks.convert_views = cache_test_convert;
    fixture->runtime_hooks.clean_source = cache_test_clean_source;
    fixture->runtime_hooks.check_source_ready = cache_test_check_source_ready;
    fixture->runtime_hooks.invalidate_output = cache_test_invalidate_output;
    fixture->runtime_hooks.validate_and_publish = cache_test_publish;
    fixture->runtime_hooks.drain_ready = cache_test_drain_ready;
    fixture->runtime_hooks.return_graph_read = cache_test_return_read;
    fixture->runtime_hooks.release_scratch = cache_test_release_hook;
    if (zn_native_arena_conv_lifecycle_init_v1(
            &fixture->lifecycle, &fixture->owner, &fixture->mmio,
            &fixture->runtime_hooks) !=
        ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
        return -1;
    for (;;) {
        ZnNativeArenaConvLifecycleCodeV1 code;
        if (!fixture->dispatch.pending &&
            zn_dispatch_next(&fixture->dispatch, &request) != 1)
            return -1;
        request = fixture->dispatch.request;
        if (request.event_index != event_index)
            return -1;
        if (request.operation == ZN_RUN)
            break;
        code = zn_native_arena_conv_lifecycle_step_v1(
            &fixture->lifecycle, &fixture->dispatch, &request, NULL);
        if (code != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
            return -1;
    }
    cache_test_make_binding(fixture, &request);
    fixture->release_busy_remaining = 1;
    return cache_test_init_adapter(fixture);
}

static void
cache_test_corrupt_scratch_lease(ZnNativeGraphConvBindingV2 *binding,
                                uint32_t base)
{
    uint64_t end = (uint64_t)base + binding->scratch.bytes;
    binding->scratch.base = base;
    binding->source_span.base = base;
    binding->command.source_base = base;
    binding->command.source_lease_region_begin = base;
    binding->command.source_lease_region_end.low = (uint32_t)end;
    binding->command.source_lease_region_end.high = (uint8_t)(end >> 32);
}

static int
cache_test_stage_for_direct_bind(CacheFixture *fixture,
                                 const ZnRequest *request,
                                 const ZnNativeGraphConvBindingV2 *binding)
{
    fixture->lifecycle.active = 1;
    fixture->lifecycle.active_request = *request;
    fixture->lifecycle.last_run_request = *request;
    fixture->lifecycle.run_started_recorded = 0;
    fixture->lifecycle.bridge.binding = *binding;
    fixture->lifecycle.bridge.stage =
        ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING;
    return cache_test_map_mappings(fixture, binding);
}

static ZnNativeFeatureCacheCodeV1
cache_test_direct_bind(CacheFixture *fixture,
                       const ZnNativeGraphConvBindingV2 *binding)
{
    ZnRequest request = fixture->dispatch.request;
    fixture->binding = *binding;
    if (cache_test_stage_for_direct_bind(fixture, &request, binding) != 0)
        return ZN_NATIVE_FEATURE_CACHE_V1_ARGUMENT;
    return zn_native_feature_cache_bind_v1(
        &fixture->cache, &fixture->lifecycle, &fixture->dispatch,
        &request, binding, &fixture->source_mapping,
        &fixture->arena_mapping);
}

static void
test_successful_bridge_lifecycle_and_release(void)
{
    CacheFixture fixture;
    ZnRequest request;
    ZnRequest next;
    ZnNativeGraphConvBindingV2 stale;
    ZnNativeArenaConvLifecycleCodeV1 lifecycle_code;
    const ZnNativeArenaEventStateV1 *state;
    uint8_t index;
    char expected_trace[] = { 'S', 'D', 'B', 'I', 'B', 'I', 'B' };

    check(cache_test_setup(&fixture, CACHE_EVENT_34_INDEX, 321) == 0,
          "real lifecycle fixture reaches event 34 RUN");
    request = fixture.dispatch.request;
    check(request.job->event == 34 && request.job->read_count == 3 &&
          fixture.binding.source_span.bytes == 819200u,
          "event 34 fixture binds the actual three-read source and destination");
    lifecycle_code = zn_native_arena_conv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &request, &fixture.binding);
    check(lifecycle_code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.mock.start_count == 1 &&
          fixture.cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED &&
          fixture.converter_calls == 1,
          "cache preparation completes before the actual V2 driver starts");

    stale = fixture.binding;
    ++stale.graph_read_refs[0].generation;
    fixture.lifecycle.active = 1;
    fixture.lifecycle.active_request = request;
    check(zn_native_feature_cache_check_binding_v1(
              &fixture.cache, &fixture.lifecycle, &request, &stale) ==
              ZN_NATIVE_FEATURE_CACHE_V1_STALE &&
          fixture.cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED &&
          fixture.mock.start_count == 1,
          "stale read generation is rejected without changing adapter ownership");
    fixture.lifecycle.active = 0;

    check(zn_native_arena_conv_lifecycle_step_v1(
              &fixture.lifecycle, &fixture.dispatch, &request,
              &fixture.binding) == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED &&
          fixture.cache.stage ==
              ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE &&
          fixture.mock.ack_count == 1 && fixture.hooks.published &&
          fixture.output_visible_before_driver_ack &&
          fixture.identity_checked,
          "full result identity and output invalidation precede driver and dispatcher ACKs");
    check(fixture.trace_count == sizeof expected_trace &&
          memcmp(fixture.trace, expected_trace, sizeof expected_trace) == 0,
          "cache callback order is source clean, destination clean, barrier, invalidate, barrier, invalidate, barrier");

    check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
          request.operation == ZN_DRAIN &&
          zn_native_arena_conv_lifecycle_step_v1(
              &fixture.lifecycle, &fixture.dispatch, &request, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED,
          "actual DRAIN records driver and all graph-read quiescence");
    for (index = 0; index < fixture.binding.graph_read_count; ++index) {
        check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
              request.operation == ZN_RETURN &&
              test_ref_equal(request.ref,
                  fixture.binding.graph_read_refs[index]) &&
              zn_native_arena_conv_lifecycle_step_v1(
                  &fixture.lifecycle, &fixture.dispatch, &request, NULL) ==
                  ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED,
              "actual bridge ACKs each exact original graph-read RETURN");
    }
    state = &fixture.owner.event_state[CACHE_EVENT_34_INDEX];
    check(state->io_quiescent && state->returned_mask == UINT8_C(7) &&
          fixture.lifecycle.bridge.return_cursor == 3,
          "scratch stays leased until quiescence and all three RETURNs");
    check(zn_dispatch_next(&fixture.dispatch, &next) == 1 &&
          next.operation == ZN_RETIRE &&
          zn_native_arena_conv_lifecycle_step_v1(
              &fixture.lifecycle, &fixture.dispatch, &next, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FINISH_REQUIRED,
          "RETIRE remains gated behind lifecycle scratch finish");

    check(zn_native_arena_conv_lifecycle_finish_v1(
              &fixture.lifecycle, &fixture.dispatch) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.scratch_owned && fixture.release_calls == 1 &&
          fixture.mock.start_count == 1 &&
          fixture.owner.event_state[CACHE_EVENT_34_INDEX].returned_mask == 7,
          "BUSY release retains the physical lease and does not resubmit the run");
    check(zn_native_arena_conv_lifecycle_finish_v1(
              &fixture.lifecycle, &fixture.dispatch) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_SCRATCH_RELEASED &&
          !fixture.scratch_owned && fixture.release_calls == 2 &&
          fixture.cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED &&
          fixture.mock.start_count == 1,
          "release retry succeeds only after driver idle, quiescence, and all RETURNS");
    check(zn_native_arena_conv_lifecycle_step_v1(
              &fixture.lifecycle, &fixture.dispatch, &next, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED,
          "next graph RETIRE proceeds after scratch release");
}

static void
test_failure_retains_ownership(void)
{
    CacheFixture fixture;
    ZnRequest request;
    ZnRef read_ref;

    check(cache_test_setup(&fixture, CACHE_EVENT_9_INDEX, 322) == 0,
          "failure fixture reaches event 9 RUN");
    request = fixture.dispatch.request;
    read_ref = request.job->reads[0];
    fixture.fail_invalidate_call = 1;
    check(zn_native_arena_conv_lifecycle_step_v1(
              &fixture.lifecycle, &fixture.dispatch, &request,
              &fixture.binding) == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.mock.start_count == 0 && fixture.release_calls == 0 &&
          fixture.scratch_owned &&
          fixture.cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED &&
          fixture.owner.fault && fixture.dispatch.fault &&
          fixture.owner.slots[read_ref.slot].reader_count != 0,
          "cache synchronization failure poisons the transaction and retains every lease");
}

static void
test_mapping_rejections(void)
{
    CacheFixture fixture;
    ZnRequest request;
    ZnNativeGraphConvBindingV2 malformed;

    check(cache_test_setup(&fixture, CACHE_EVENT_9_INDEX, 323) == 0,
          "CPU-alias fixture reaches event 9 RUN");
    fixture.mapping_mode = CACHE_MAPPING_CPU_ALIAS;
    request = fixture.dispatch.request;
    check(zn_native_arena_conv_lifecycle_step_v1(
              &fixture.lifecycle, &fixture.dispatch, &request,
              &fixture.binding) == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.mock.start_count == 0 && fixture.scratch_owned &&
          fixture.release_calls == 0,
          "CPU source and destination aliases fail closed before START");

    check(cache_test_setup(&fixture, CACHE_EVENT_9_INDEX, 324) == 0,
          "partial-line fixture reaches event 9 RUN");
    request = fixture.dispatch.request;
    malformed = fixture.binding;
    --malformed.source_span.bytes;
    check(zn_native_arena_conv_lifecycle_step_v1(
              &fixture.lifecycle, &fixture.dispatch, &request,
              &malformed) == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.mock.start_count == 0 && fixture.scratch_owned,
          "partial cache-line source mapping is rejected before START");

    check(cache_test_setup(&fixture, CACHE_EVENT_9_INDEX, 325) == 0,
          "physical-alias fixture reaches event 9 RUN");
    request = fixture.dispatch.request;
    malformed = fixture.binding;
    cache_test_corrupt_scratch_lease(
        &malformed, request.job->destination.address);
    check(cache_test_direct_bind(&fixture, &malformed) ==
              ZN_NATIVE_FEATURE_CACHE_V1_INVALID &&
          fixture.cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED &&
          fixture.scratch_owned && fixture.release_calls == 0,
          "physical scratch and destination reservation aliases are rejected");
}

int
main(void)
{
    test_successful_bridge_lifecycle_and_release();
    test_failure_retains_ownership();
    test_mapping_rejections();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_FEATURE_CACHE_V1_HOST_FAIL count=%u\n",
                failures);
        return 1;
    }
    puts("NATIVE_FEATURE_CACHE_V1_HOST_PASS real_v2_bridge=1 real_lifecycle=1 result_identity_fields=10 output_invalidate_before_ack=1 all_returns_before_release=1 busy_release_retry=1 aliases=2 partial_line=1 failure_retention=1 board_access=0");
    return 0;
}
