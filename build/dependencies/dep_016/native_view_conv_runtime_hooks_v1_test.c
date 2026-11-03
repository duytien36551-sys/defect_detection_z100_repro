#define main native_view_bridge_integration_v2_fixture_main
#include "native_view_bridge_integration_v2_test.c"
#undef main

#include "native_arena_conv_lifecycle_v1.h"
#include "native_arena_owner_v1.h"
#include "native_feature_cache_v1.h"
#include "native_runtime_maps_v1.h"
#include "native_scratch_bindings_v2.h"
#include "native_view_conv_runtime_hooks_v1.h"

#include <stdint.h>

enum {
    TEST_ARENA_BASE = 268435456,
    TEST_ARENA_BYTES = 5201920,
    TEST_SCRATCH_BASE = 570425344,
    TEST_SCRATCH_BYTES = 1228800,
    FIRST_VIEW_INDEX = 3,
    SECOND_VIEW_INDEX = 6
};

_Alignas(64) static uint8_t arena_storage[TEST_ARENA_BYTES];
_Alignas(64) static uint8_t scratch_storage[TEST_SCRATCH_BYTES];

typedef struct RuntimeMemory {
    unsigned int clean_calls;
    unsigned int barrier_calls;
    unsigned int invalidate_calls;
    unsigned int release_calls;
    unsigned int release_busy_remaining;
    unsigned int fail_clean_at;
    ZnNativeGraphScratchLeaseV2 last_released;
} RuntimeMemory;

typedef struct RuntimeFixture {
    ZnNativeArenaConfigV1 config;
    ZnNativeArenaOwnerV1 owner;
    ZnDispatch dispatch;
    ZnNativeArenaConvLifecycleV1 lifecycle;
    ZnNativeFeatureCacheV1 cache;
    ZnNativeViewConvRuntimeV1 runtime;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativeConvMmioOpsV2 mmio_ops;
    ZnNativePlatformMemoryOpsV1 memory_ops;
    ZnNativePlatformMappedSpanV1 arena_mapping;
    ZnNativePlatformMappedSpanV1 scratch_mapping;
    ZnNativeGraphConvBindingV2 binding;
    ZnRequest request;
    RuntimeMemory memory;
    BridgeMmio mmio;
} RuntimeFixture;

static const ZnNativeArenaRegionV1 test_regions[ZN_NATIVE_ARENA_SLOT_COUNT_V1] = {
    { UINT32_C(268435456), UINT32_C(1638400) },
    { UINT32_C(270073856), UINT32_C(1638400) },
    { UINT32_C(271712256), UINT32_C(819200) },
    { UINT32_C(272531456), UINT32_C(409600) },
    { UINT32_C(272941056), UINT32_C(409600) },
    { UINT32_C(273350656), UINT32_C(122880) },
    { UINT32_C(273473536), UINT32_C(163840) }
};

static ZnNativeArenaConfigV1
test_config(void)
{
    ZnNativeArenaConfigV1 config;
    memset(&config, 0, sizeof config);
    config.arena_base = (uint32_t)TEST_ARENA_BASE;
    config.arena_end = (uint32_t)(TEST_ARENA_BASE + TEST_ARENA_BYTES);
    config.arena_bytes = (uint32_t)TEST_ARENA_BYTES;
    config.alignment = 4096;
    memcpy(config.slots, test_regions, sizeof test_regions);
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
test_completion(const ZnRequest *request)
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
test_prefix_request(ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
                    const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 code;
    if (request->operation == ZN_RUN) {
        ZnNativeArenaCompletionEvidenceV1 completion =
            test_completion(request);
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
test_advance_owner_to(ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
                      uint16_t target)
{
    ZnRequest request;
    while (dispatch->cursor < target) {
        if (zn_dispatch_next(dispatch, &request) != 1 ||
            request.event_index != dispatch->cursor ||
            test_prefix_request(owner, dispatch, &request) != 0)
            return -1;
    }
    return dispatch->cursor == target ? 0 : -1;
}

static int
memory_cache_clean(void *context, void *address, size_t bytes)
{
    RuntimeMemory *memory = (RuntimeMemory *)context;
    ++memory->clean_calls;
    if (!address || bytes == 0)
        return -1;
    return memory->fail_clean_at == memory->clean_calls ? -7 : 0;
}

static int
memory_barrier(void *context)
{
    RuntimeMemory *memory = (RuntimeMemory *)context;
    ++memory->barrier_calls;
    return 0;
}

static int
memory_invalidate(void *context, void *address, size_t bytes)
{
    RuntimeMemory *memory = (RuntimeMemory *)context;
    ++memory->invalidate_calls;
    return address && bytes != 0 ? 0 : -1;
}

static int
memory_release(void *context, const ZnNativeGraphScratchLeaseV2 *lease)
{
    RuntimeMemory *memory = (RuntimeMemory *)context;
    if (!lease)
        return -1;
    ++memory->release_calls;
    memory->last_released = *lease;
    if (memory->release_busy_remaining != 0) {
        --memory->release_busy_remaining;
        return 1;
    }
    return 0;
}

static void
test_make_mapping(ZnNativePlatformMappedSpanV1 *mapping, uint64_t physical,
                  uint8_t *cpu, size_t bytes)
{
    mapping->physical_base = physical;
    mapping->bytes = bytes;
    mapping->cpu_base = cpu;
    mapping->cpu_bytes = bytes;
}

static int
test_init_runtime(RuntimeFixture *fixture, size_t scratch_bytes)
{
    ZnNativeViewConvRuntimeCodeV1 code;
    memset(fixture, 0, sizeof *fixture);
    memset(arena_storage, 0, sizeof arena_storage);
    memset(scratch_storage, 0, sizeof scratch_storage);

    fixture->config = test_config();
    if (zn_dispatch_init(&fixture->dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, HOST_EPOCH) != 0 ||
        zn_native_arena_owner_init_v1(&fixture->owner, &fixture->config,
                                      &fixture->dispatch, HOST_EPOCH) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return -1;

    reset_mmio(&fixture->mmio);
    fixture->mmio_ops.context = &fixture->mmio;
    fixture->mmio_ops.read32 = mock_read32;
    fixture->mmio_ops.write32 = mock_write32;
    fixture->mmio_ops.write_barrier = mock_barrier;
    fixture->memory_ops.cache_clean = memory_cache_clean;
    fixture->memory_ops.barrier = memory_barrier;
    fixture->memory_ops.invalidate_readback = memory_invalidate;
    if (zn_native_feature_cache_init_v1(
            &fixture->cache, &fixture->memory_ops, &fixture->memory,
            memory_release, &fixture->memory) !=
        ZN_NATIVE_FEATURE_CACHE_V1_READY)
        return -1;

    test_make_mapping(&fixture->arena_mapping, TEST_ARENA_BASE, arena_storage,
                      TEST_ARENA_BYTES);
    test_make_mapping(&fixture->scratch_mapping, TEST_SCRATCH_BASE,
                      scratch_storage, scratch_bytes);
    code = zn_native_view_conv_runtime_hooks_init_v1(
        &fixture->runtime, &fixture->lifecycle, &fixture->cache,
        &fixture->arena_mapping, &fixture->scratch_mapping, &fixture->hooks);
    if (code != ZN_NATIVE_VIEW_CONV_RUNTIME_V1_READY ||
        zn_native_arena_conv_lifecycle_init_v1(
            &fixture->lifecycle, &fixture->owner, &fixture->mmio_ops,
            &fixture->hooks) != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
        return -1;
    return 0;
}

static int
test_reach_run(RuntimeFixture *fixture, uint16_t event_index)
{
    ZnNativeGraphScratchLeaseV2 scratch;
    ZnNativeScratchIdsV2 ids;
    unsigned int next;

    if (test_advance_owner_to(&fixture->owner, &fixture->dispatch,
                              event_index) != 0)
        return -1;
    for (;;) {
        if (!fixture->dispatch.pending) {
            next = (unsigned int)zn_dispatch_next(&fixture->dispatch,
                                                   &fixture->request);
            if (next != 1u)
                return -1;
        }
        fixture->request = fixture->dispatch.request;
        if (fixture->request.event_index != event_index)
            return -1;
        if (fixture->request.operation == ZN_RUN)
            break;
        if (zn_native_arena_conv_lifecycle_step_v1(
                &fixture->lifecycle, &fixture->dispatch, &fixture->request,
                NULL) != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
            return -1;
    }

    scratch.epoch = fixture->request.epoch;
    scratch.generation = UINT32_C(800) + event_index;
    scratch.base = (uint32_t)TEST_SCRATCH_BASE;
    scratch.bytes = TEST_SCRATCH_BYTES;
    make_ids(event_index, &ids);
    if (zn_native_scratch_binding_v2(&fixture->request, &ids, &scratch,
                                     &fixture->binding) != 0)
        return -1;
    fixture->mmio.expected_tiles = fixture->binding.expected_tiles;
    return 0;
}

static int
test_prepare_view_sources(RuntimeFixture *fixture, FixtureIndex *fixtures,
                          ViewContext *context)
{
    uint8_t index;
    memset(context, 0, sizeof *context);
    context->fixtures = fixtures;
    context->totals = (IntegrationTotals *)calloc(1, sizeof *context->totals);
    context->mmio = &fixture->mmio;
    context->write_actual = 1;
    if (!context->totals ||
        prepare_view_context(context, &fixture->request,
                             &fixture->binding) != 0 ||
        context->source_count != fixture->request.job->read_count)
        return -1;
    for (index = 0; index < context->source_count; ++index) {
        ZnRef ref = fixture->request.job->reads[index];
        const ZnNativeArenaSlotV1 *slot;
        uint64_t offset;
        if (ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
            return -1;
        slot = &fixture->owner.slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            slot->ref.generation != ref.generation ||
            slot->ref.tensor != ref.tensor || slot->ref.slot != ref.slot ||
            slot->bytes != (uint32_t)context->sources[index].bytes ||
            slot->region.address < TEST_ARENA_BASE)
            return -1;
        offset = (uint64_t)slot->region.address - TEST_ARENA_BASE;
        if (offset > sizeof arena_storage ||
            context->sources[index].bytes > sizeof arena_storage - offset)
            return -1;
        memcpy(arena_storage + (size_t)offset,
               context->source_data[index], context->sources[index].bytes);
    }
    return 0;
}

static int
test_run_until_acked(RuntimeFixture *fixture, const ZnRequest *request,
                     const ZnNativeGraphConvBindingV2 *binding)
{
    unsigned int attempt;
    for (attempt = 0; attempt < 32u; ++attempt) {
        ZnNativeArenaConvLifecycleCodeV1 code =
            zn_native_arena_conv_lifecycle_step_v1(
                &fixture->lifecycle, &fixture->dispatch, request, binding);
        if (code != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY)
            return code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED ? 0 : -1;
    }
    return -1;
}

static int
test_finish_event(RuntimeFixture *fixture, int expect_release_busy)
{
    ZnRequest request;
    uint8_t index;
    unsigned int clean_before;
    unsigned int barrier_before;
    unsigned int invalidate_before;
    ZnNativeArenaConvLifecycleCodeV1 code;

    if (zn_dispatch_next(&fixture->dispatch, &request) != 1 ||
        request.operation != ZN_DRAIN ||
        zn_native_arena_conv_lifecycle_step_v1(
            &fixture->lifecycle, &fixture->dispatch, &request, NULL) !=
            ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
        return -1;
    clean_before = fixture->memory.clean_calls;
    barrier_before = fixture->memory.barrier_calls;
    invalidate_before = fixture->memory.invalidate_calls;

    for (index = 0; index < fixture->binding.graph_read_count; ++index) {
        if (zn_dispatch_next(&fixture->dispatch, &request) != 1 ||
            request.operation != ZN_RETURN ||
            zn_native_arena_conv_lifecycle_step_v1(
                &fixture->lifecycle, &fixture->dispatch, &request, NULL) !=
                ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
            return -1;
    }
    if (fixture->memory.clean_calls != clean_before ||
        fixture->memory.barrier_calls != barrier_before ||
        fixture->memory.invalidate_calls != invalidate_before ||
        fixture->owner.event_state[fixture->binding.event_index].returned_mask !=
            (uint8_t)((UINT32_C(1) << fixture->binding.graph_read_count) - 1u))
        return -1;

    code = zn_native_arena_conv_lifecycle_finish_v1(&fixture->lifecycle,
                                                     &fixture->dispatch);
    if (expect_release_busy) {
        if (code != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY ||
            fixture->cache.stage !=
                ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE ||
            !fixture->runtime.active)
            return -1;
        code = zn_native_arena_conv_lifecycle_finish_v1(&fixture->lifecycle,
                                                        &fixture->dispatch);
    }
    return code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_SCRATCH_RELEASED &&
           !fixture->runtime.active &&
           fixture->cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED ?
        0 : -1;
}

static int
test_run_output(RuntimeFixture *fixture, ViewContext *context)
{
    ZnNativeArenaConvLifecycleCodeV1 code;
    ZnNativeGraphConvBindingV2 stale_binding;
    unsigned int clean_before;
    unsigned int source_maps_before;
    unsigned int release_before;

    release_before = fixture->memory.release_calls;
    code = zn_native_arena_conv_lifecycle_step_v1(
        &fixture->lifecycle, &fixture->dispatch, &fixture->request,
        &fixture->binding);
    if (code != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY ||
        !fixture->runtime.active || !fixture->runtime.converted ||
        fixture->runtime.source_count != fixture->binding.graph_read_count ||
        fixture->cache.stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_PREPARED ||
         fixture->memory.release_calls != release_before ||
        memcmp(fixture->cache.source_mapping.cpu_base, context->expected,
               fixture->cache.source_mapping.bytes) != 0)
        return -1;

    if (context->output_bytes != fixture->cache.source_mapping.bytes)
        return -1;
    memcpy(context->output, fixture->cache.source_mapping.cpu_base,
           fixture->cache.source_mapping.bytes);
    if (write_actual_view(context) != 0)
        return -1;

    clean_before = fixture->memory.clean_calls;
    source_maps_before = fixture->runtime.source_count;
    fixture->runtime.arena_mapping.cpu_base = NULL;
    stale_binding = fixture->binding;
    ++stale_binding.dispatch_tag;
    code = zn_native_arena_conv_lifecycle_step_v1(
        &fixture->lifecycle, &fixture->dispatch, &fixture->request,
        &stale_binding);
    if (code != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_STALE_REQUEST ||
        fixture->memory.clean_calls != clean_before ||
        fixture->runtime.source_count != source_maps_before) {
        return -1;
    }

    if (test_run_until_acked(fixture, &fixture->request,
                             &fixture->binding) != 0 ||
        fixture->memory.clean_calls != clean_before ||
        fixture->cache.stage !=
            ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE ||
        !fixture->owner.event_state[fixture->binding.event_index].output_published) {
        return -1;
    }
    return 0;
}

static void
test_alias_and_bounds(FixtureIndex *fixtures)
{
    ZnNativeArenaConvLifecycleV1 lifecycle;
    ZnNativeFeatureCacheV1 cache;
    ZnNativeViewConvRuntimeV1 runtime;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativePlatformMemoryOpsV1 memory_ops;
    ZnNativePlatformMappedSpanV1 arena_mapping;
    ZnNativePlatformMappedSpanV1 scratch_mapping;
    RuntimeMemory memory;
    RuntimeFixture fixture;
    ViewContext context;
    ZnNativeViewConvRuntimeCodeV1 init_code;
    ZnNativeArenaConvLifecycleCodeV1 step_code;

    memset(&lifecycle, 0, sizeof lifecycle);
    memset(&cache, 0, sizeof cache);
    memset(&runtime, 0, sizeof runtime);
    memset(&hooks, 0, sizeof hooks);
    memset(&memory, 0, sizeof memory);
    memset(&memory_ops, 0, sizeof memory_ops);
    memory_ops.cache_clean = memory_cache_clean;
    memory_ops.barrier = memory_barrier;
    memory_ops.invalidate_readback = memory_invalidate;
    test_make_mapping(&arena_mapping, TEST_ARENA_BASE, arena_storage,
                      TEST_ARENA_BYTES);
    check(zn_native_feature_cache_init_v1(&cache, &memory_ops, &memory,
                                          memory_release, &memory) ==
              ZN_NATIVE_FEATURE_CACHE_V1_READY,
          "initialize cache for mapping rejection checks");

    test_make_mapping(&scratch_mapping, TEST_SCRATCH_BASE, arena_storage + 64,
                      TEST_SCRATCH_BYTES);
    init_code = zn_native_view_conv_runtime_hooks_init_v1(
        &runtime, &lifecycle, &cache, &arena_mapping, &scratch_mapping, &hooks);
    check(init_code == ZN_NATIVE_VIEW_CONV_RUNTIME_V1_INVALID,
          "runtime init rejects CPU alias between arena and scratch spans");

    memset(&runtime, 0, sizeof runtime);
    test_make_mapping(&scratch_mapping, TEST_ARENA_BASE + UINT64_C(0x600000),
                      scratch_storage, TEST_SCRATCH_BYTES);
    init_code = zn_native_view_conv_runtime_hooks_init_v1(
        &runtime, &lifecycle, &cache, &arena_mapping, &scratch_mapping, &hooks);
    check(init_code == ZN_NATIVE_VIEW_CONV_RUNTIME_V1_READY,
          "runtime accepts a disjoint caller scratch mapping");

    if (test_init_runtime(&fixture, TEST_SCRATCH_BYTES - 64u) != 0 ||
        test_reach_run(&fixture, FIRST_VIEW_INDEX) != 0 ||
        test_prepare_view_sources(&fixture, fixtures, &context) != 0) {
        check(0, "prepare scratch bounds rejection fixture");
        return;
    }
    step_code = zn_native_arena_conv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &fixture.request,
        &fixture.binding);
    check(step_code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.owner.fault && fixture.dispatch.fault &&
          fixture.owner.slots[fixture.request.job->reads[0].slot].reader_count != 0 &&
          fixture.memory.release_calls == 0 &&
          fixture.cache.transaction_count == 0,
          "out-of-bounds scratch lease fails before mapping or release");
    free_view_buffers(&context);
    free(context.totals);
}

static void
test_positive_nonview_status_is_not_busy(void)
{
    ZnNativeArenaConvLifecycleV1 lifecycle;
    ZnNativeArenaOwnerV1 owner;
    ZnNativeFeatureCacheV1 cache;
    ZnNativeViewConvRuntimeV1 runtime;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativePlatformMemoryOpsV1 memory_ops;
    ZnNativePlatformMappedSpanV1 arena_mapping;
    ZnNativePlatformMappedSpanV1 scratch_mapping;
    ZnNativeGraphConvBindingV2 binding;
    ZnRequest request;
    RuntimeMemory memory;
    ZnNativeViewConvRuntimeCodeV1 init_code;
    int callback_code;

    memset(&lifecycle, 0, sizeof lifecycle);
    memset(&owner, 0, sizeof owner);
    memset(&cache, 0, sizeof cache);
    memset(&runtime, 0, sizeof runtime);
    memset(&hooks, 0, sizeof hooks);
    memset(&binding, 0, sizeof binding);
    memset(&request, 0, sizeof request);
    memset(&memory, 0, sizeof memory);
    memset(&memory_ops, 0, sizeof memory_ops);
    memory_ops.cache_clean = memory_cache_clean;
    memory_ops.barrier = memory_barrier;
    memory_ops.invalidate_readback = memory_invalidate;
    test_make_mapping(&arena_mapping, TEST_ARENA_BASE, arena_storage,
                      TEST_ARENA_BYTES);
    test_make_mapping(&scratch_mapping, TEST_SCRATCH_BASE, scratch_storage,
                      TEST_SCRATCH_BYTES);
    check(zn_native_feature_cache_init_v1(&cache, &memory_ops, &memory,
                                          memory_release, &memory) ==
              ZN_NATIVE_FEATURE_CACHE_V1_READY,
          "initialize cache for non-view status check");
    init_code = zn_native_view_conv_runtime_hooks_init_v1(
        &runtime, &lifecycle, &cache, &arena_mapping, &scratch_mapping, &hooks);
    request.epoch = HOST_EPOCH;
    request.tag = 77;
    request.event_index = 1;
    request.operation = ZN_RUN;
    request.job = &z100_graph_events[1];
    request.ref = request.job->reads[0];
    lifecycle.owner = &owner;
    lifecycle.active_request = request;
    lifecycle.active = 1;
    binding.graph_read_count = request.job->read_count;
    callback_code = init_code == ZN_NATIVE_VIEW_CONV_RUNTIME_V1_READY ?
        hooks.check_leases(hooks.context, &request, &binding) : 1;
    check(init_code == ZN_NATIVE_VIEW_CONV_RUNTIME_V1_READY &&
          callback_code < 0 && callback_code != 1 && !runtime.active &&
          cache.transaction_count == 0,
          "generated converter status 1 rejects a direct event instead of BUSY");
}

static void
test_cache_failure_retains_leases(FixtureIndex *fixtures)
{
    RuntimeFixture fixture;
    ViewContext context;
    ZnNativeArenaConvLifecycleCodeV1 code;

    if (test_init_runtime(&fixture, TEST_SCRATCH_BYTES) != 0 ||
        test_reach_run(&fixture, FIRST_VIEW_INDEX) != 0 ||
        test_prepare_view_sources(&fixture, fixtures, &context) != 0) {
        check(0, "prepare cache failure fixture");
        return;
    }
    fixture.memory.fail_clean_at = 1;
    code = zn_native_arena_conv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &fixture.request,
        &fixture.binding);
    check(code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.owner.fault && fixture.dispatch.fault &&
          fixture.owner.slots[fixture.request.job->reads[0].slot].reader_count != 0 &&
          fixture.memory.release_calls == 0 &&
          fixture.cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_POISONED,
          "cache failure poisons the transaction and retains graph and scratch leases");
    free_view_buffers(&context);
    free(context.totals);
}

static void
test_two_sequential_view_events(FixtureIndex *fixtures)
{
    RuntimeFixture fixture;
    ViewContext context;
    uint16_t event_index;
    unsigned int reads;

    if (test_init_runtime(&fixture, TEST_SCRATCH_BYTES) != 0 ||
        test_reach_run(&fixture, FIRST_VIEW_INDEX) != 0 ||
        test_prepare_view_sources(&fixture, fixtures, &context) != 0) {
        check(0, "prepare first sequential view event");
        return;
    }
    fixture.memory.release_busy_remaining = 1;
    event_index = fixture.binding.event_index;
    reads = fixture.binding.graph_read_count;
    if (test_run_output(&fixture, &context) != 0 ||
        test_finish_event(&fixture, 1) != 0 ||
        fixture.memory.release_calls != 2 ||
        fixture.memory.last_released.generation != fixture.binding.scratch.generation) {
        check(0, "complete first view event with delayed scratch release");
        free_view_buffers(&context);
        free(context.totals);
        return;
    }
    check(event_index == FIRST_VIEW_INDEX && reads == 1,
          "first selected view event has one ordered graph read");
    free_view_buffers(&context);
    free(context.totals);
    fixture.runtime.arena_mapping = fixture.arena_mapping;

    if (test_reach_run(&fixture, SECOND_VIEW_INDEX) != 0 ||
        test_prepare_view_sources(&fixture, fixtures, &context) != 0) {
        check(0, "prepare second sequential view event");
        return;
    }
    event_index = fixture.binding.event_index;
    reads = fixture.binding.graph_read_count;
    {
        int run_rc = test_run_output(&fixture, &context);
        int finish_rc = run_rc == 0 ? test_finish_event(&fixture, 0) : -1;
        if (run_rc != 0 || finish_rc != 0) {
        check(0, "complete second view event with multiple reads");
        free_view_buffers(&context);
        free(context.totals);
        return;
        }
    }
    check(event_index == SECOND_VIEW_INDEX && reads == 2,
          "second selected view event maps both reads in graph order");
    check(fixture.memory.release_calls == 3 &&
          fixture.cache.transaction_count == 2 &&
          fixture.cache.stage == ZN_NATIVE_FEATURE_CACHE_STAGE_V1_RELEASED &&
          fixture.owner.event_state[SECOND_VIEW_INDEX].returned_mask == 3,
          "sequential cache transactions finish only after every graph RETURN");
    free_view_buffers(&context);
    free(context.totals);
}

int
main(int argc, char **argv)
{
    FixtureIndex fixtures;
    if (argc != 2 || load_fixture_index(&fixtures, argv[1]) != 0) {
        fprintf(stderr, "expected selected frozen view fixtures\n");
        return 2;
    }

    test_alias_and_bounds(&fixtures);
    test_positive_nonview_status_is_not_busy();
    test_cache_failure_retains_leases(&fixtures);
    test_two_sequential_view_events(&fixtures);
    if (failures != 0) {
        fprintf(stderr, "NATIVE_VIEW_CONV_RUNTIME_HOOKS_V1_HOST_FAIL count=%u\n",
                failures);
        return 1;
    }
    printf("NATIVE_VIEW_CONV_RUNTIME_HOOKS_V1_HOST_PASS events=2 reads=3 captured_outputs=2 board_access=0 throughput_claim=0\n");
    return 0;
}
