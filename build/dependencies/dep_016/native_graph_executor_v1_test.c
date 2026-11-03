#define main native_graph_executor_embedded_bridge_test_main
#include "native_graph_conv_bridge_v2_test.c"
#undef main

#include "native_graph_executor_v1.h"
#include "native_nonconv_v1.h"
#include "graph_plan.h"

enum {
    EXECUTOR_ADD_EVENT_INDEX = 5,
    EXECUTOR_FIRST_CONV_INDEX = 4,
    EXECUTOR_SECOND_CONV_INDEX = 6,
    EXECUTOR_SOURCE_CAPACITY = 819200,
    EXECUTOR_OUTPUT_CAPACITY = 409600
};

typedef struct ExecutorFixture ExecutorFixture;

typedef struct ExecutorConvFixture {
    ZnNativeArenaConfigV1 config;
    ZnNativeArenaOwnerV1 owner;
    ZnDispatch dispatch;
    ZnNativeArenaConvLifecycleV1 lifecycle;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 runtime_hooks;
    BridgeMmio mock;
    HookState hooks;
} ExecutorConvFixture;

typedef struct ExecutorNonConvFixture {
    ZnNativeArenaNonConvLifecycleV1 lifecycle;
    ZnNativeArenaNonConvHooksV1 hooks;
    uint8_t source_data[2][EXECUTOR_SOURCE_CAPACITY];
    uint8_t output_data[EXECUTOR_OUTPUT_CAPACITY];
    uint32_t map_calls;
    uint32_t visible_calls;
    uint32_t output_map_calls;
    uint32_t clean_calls;
    uint32_t publish_calls;
    uint32_t drain_calls;
    uint32_t return_calls;
    uint8_t map_busy_remaining;
    uint8_t returned_mask;
} ExecutorNonConvFixture;

struct ExecutorFixture {
    ExecutorConvFixture conv;
    ExecutorNonConvFixture nonconv;
    ZnNativeGraphExecutorV1 executor;
    uint32_t resolver_calls;
    uint32_t converter_calls;
    uint8_t resolver_busy_remaining;
};

static const ZnNativeArenaRegionV1 executor_regions[
    ZN_NATIVE_ARENA_SLOT_COUNT_V1] = {
    { UINT32_C(268435456), UINT32_C(1638400) },
    { UINT32_C(270073856), UINT32_C(1638400) },
    { UINT32_C(271712256), UINT32_C(819200) },
    { UINT32_C(272531456), UINT32_C(409600) },
    { UINT32_C(272941056), UINT32_C(409600) },
    { UINT32_C(273350656), UINT32_C(122880) },
    { UINT32_C(273473536), UINT32_C(163840) }
};

static ZnNativeArenaConfigV1
executor_make_config(void)
{
    ZnNativeArenaConfigV1 config;
    memset(&config, 0, sizeof config);
    config.arena_base = UINT32_C(268435456);
    config.arena_end = UINT32_C(273637376);
    config.arena_bytes = UINT32_C(5201920);
    config.alignment = 4096;
    memcpy(config.slots, executor_regions, sizeof executor_regions);
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
executor_synthetic_completion(const ZnRequest *request)
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
executor_complete_synthetic_request(ZnNativeArenaOwnerV1 *owner,
                                    ZnDispatch *dispatch,
                                    const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 code;

    if (request->operation == ZN_RUN) {
        ZnNativeArenaCompletionEvidenceV1 evidence =
            executor_synthetic_completion(request);
        code = zn_native_arena_owner_step_v1(owner, dispatch, request);
        if (code != ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND ||
            zn_native_arena_owner_run_started_v1(owner, dispatch, request) !=
                ZN_NATIVE_ARENA_OWNER_V1_ACKED)
            return -1;
        code = request->job->has_destination ?
            zn_native_arena_owner_publish_v1(owner, dispatch, request,
                                              &evidence) :
            zn_native_arena_owner_complete_without_output_v1(
                owner, dispatch, request, &evidence);
        if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
            return -1;
    } else if (request->operation == ZN_DRAIN) {
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
executor_complete_synthetic_prefix(ZnNativeArenaOwnerV1 *owner,
                                   ZnDispatch *dispatch, uint16_t target)
{
    ZnRequest request;
    while (dispatch->cursor < target) {
        int next = zn_dispatch_next(dispatch, &request);
        if (next == 0 && target == dispatch->count && dispatch->done &&
            dispatch->cursor == target)
            return 0;
        if (next != 1)
            return -1;
        if (request.event_index != dispatch->cursor ||
            executor_complete_synthetic_request(owner, dispatch,
                                                &request) != 0)
            return -1;
    }
    if (target == dispatch->count && !dispatch->done &&
        (zn_dispatch_next(dispatch, &request) != 0 || !dispatch->done))
        return -1;
    return dispatch->cursor == target ? 0 : -1;
}

static size_t
executor_packed_bytes(uint16_t channels, uint16_t height, uint16_t width)
{
    return (size_t)((channels + 3u) / 4u) * height *
           ((width + 15u) / 16u) * 64u;
}

static void
executor_set_end(ZnNativeConvEnd33 *end, uint64_t value)
{
    end->low = (uint32_t)value;
    end->high = (uint8_t)(value >> 32);
}

static int
executor_resolve_conv(void *context, const ZnRequest *request,
                      ZnNativeGraphConvBindingV2 *binding)
{
    ExecutorFixture *fixture = (ExecutorFixture *)context;
    uint64_t destination_end;
    uint64_t source_end;

    if (!fixture || !request || !binding || !request->job ||
        request->operation != ZN_RUN ||
        (request->event_index != EXECUTOR_FIRST_CONV_INDEX &&
         request->event_index != EXECUTOR_SECOND_CONV_INDEX))
        return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
    ++fixture->resolver_calls;
    if (fixture->resolver_busy_remaining != 0) {
        --fixture->resolver_busy_remaining;
        return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_BUSY_V1;
    }

    fixture->conv.hooks.read_count = request->job->read_count;
    fixture->conv.hooks.scratch_reserved = 1;
    fixture->conv.hooks.leases_code = 1;
    fixture->conv.hooks.converted = 0;
    fixture->conv.hooks.cleaned = 0;
    fixture->conv.hooks.output_invalidated = 0;
    fixture->conv.hooks.published = 0;
    fixture->conv.hooks.drain_ready_seen = 0;
    fixture->conv.hooks.scratch_released = 0;
    fixture->conv.hooks.returned_mask = 0;

    make_binding(binding, request);
    binding->scratch.generation = 800u + fixture->resolver_calls;
    binding->source_span.base = binding->scratch.base;
    binding->command.source_base = binding->source_span.base;
    binding->command.source_generation = binding->scratch.generation;
    binding->command.source_lease_region_begin = binding->scratch.base;
    source_end = (uint64_t)binding->scratch.base + binding->scratch.bytes;
    executor_set_end(&binding->command.source_lease_region_end, source_end);
    binding->command.destination_reservation_region_begin =
        request->job->destination.address;
    destination_end = (uint64_t)request->job->destination.address +
                      request->job->destination.bytes;
    executor_set_end(&binding->command.destination_reservation_region_end,
                     destination_end);
    fixture->conv.mock.expected_tiles = binding->expected_tiles;
    return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_READY_V1;
}

static int
executor_map_source(void *context, const ZnRequest *request,
                    uint8_t read_index, uint32_t expected_address,
                    uint32_t expected_bytes,
                    ZnNativeArenaNonConvSourceV1 *source)
{
    ExecutorNonConvFixture *fixture =
        (ExecutorNonConvFixture *)context;
    uint16_t channels;

    if (!fixture || !request || !source || request->event_index !=
            EXECUTOR_ADD_EVENT_INDEX || read_index >= 2)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    ++fixture->map_calls;
    if (fixture->map_busy_remaining != 0) {
        --fixture->map_busy_remaining;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    channels = read_index == 0 ? 32u : 16u;
    if (expected_bytes != executor_packed_bytes(channels, 160, 160))
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    memset(source, 0, sizeof *source);
    source->physical_address = expected_address;
    source->view.data = fixture->source_data[read_index];
    source->view.bytes = expected_bytes;
    source->view.epoch = request->epoch;
    source->view.ref = request->job->reads[read_index];
    source->view.channels = channels;
    source->view.height = 160;
    source->view.width = 160;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
executor_source_visible(void *context, const ZnRequest *request,
                        uint8_t read_index,
                        const ZnNativeArenaNonConvSourceV1 *source)
{
    ExecutorNonConvFixture *fixture =
        (ExecutorNonConvFixture *)context;
    if (!fixture || !request || !source || read_index >= 2)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    ++fixture->visible_calls;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
executor_map_output(void *context, const ZnRequest *request,
                    uint32_t expected_address, uint32_t output_bytes,
                    ZnNativeArenaNonConvOutputV1 *output)
{
    ExecutorNonConvFixture *fixture =
        (ExecutorNonConvFixture *)context;
    if (!fixture || !request || !output || request->event_index !=
            EXECUTOR_ADD_EVENT_INDEX ||
        output_bytes != EXECUTOR_OUTPUT_CAPACITY)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    ++fixture->output_map_calls;
    output->physical_address = expected_address;
    output->data = fixture->output_data;
    output->capacity_bytes = sizeof fixture->output_data;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
executor_clean_output(void *context, const ZnRequest *request,
                      const ZnNativeArenaNonConvOutputV1 *output,
                      uint32_t output_bytes)
{
    ExecutorNonConvFixture *fixture =
        (ExecutorNonConvFixture *)context;
    if (!fixture || !request || !output || output->data != fixture->output_data ||
        output_bytes > output->capacity_bytes)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    ++fixture->clean_calls;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
executor_publish_output(void *context, const ZnRequest *request,
                        const ZnNativeArenaNonConvOutputV1 *output,
                        uint32_t output_bytes)
{
    ExecutorNonConvFixture *fixture =
        (ExecutorNonConvFixture *)context;
    if (!fixture || !request || !output || output->data != fixture->output_data ||
        output_bytes > output->capacity_bytes)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    ++fixture->publish_calls;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
executor_drain_ready(void *context, const ZnRequest *request,
                     ZnNativeArenaQuiescenceEvidenceV1 *evidence)
{
    ExecutorNonConvFixture *fixture =
        (ExecutorNonConvFixture *)context;
    if (!fixture || !request || !evidence || !fixture->lifecycle.run_request.job)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    ++fixture->drain_calls;
    memset(evidence, 0, sizeof *evidence);
    evidence->epoch = request->epoch;
    evidence->run_tag = fixture->lifecycle.run_request.tag;
    evidence->event_index = request->event_index;
    evidence->all_read_io_quiet = 1;
    evidence->all_write_io_quiet = 1;
    evidence->driver_terminal = 1;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
executor_return_read(void *context, const ZnRequest *request,
                     uint8_t read_index, uint32_t physical_address,
                     ZnRef ref)
{
    ExecutorNonConvFixture *fixture =
        (ExecutorNonConvFixture *)context;
    if (!fixture || !request || !request->job || read_index >= 2 ||
        !test_ref_equal(ref, request->job->reads[read_index]))
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    if (physical_address !=
        fixture->lifecycle.owner->slots[ref.slot].region.address)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    ++fixture->return_calls;
    fixture->returned_mask |= (uint8_t)(UINT32_C(1) << read_index);
    return ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1;
}

static int
executor_fixture_init(ExecutorFixture *fixture, uint32_t epoch)
{
    ExecutorConvFixture *conv = &fixture->conv;
    ExecutorNonConvFixture *nonconv = &fixture->nonconv;
    ZnNativeGraphConvHooksV2 unused_hooks;
    unsigned int index;

    memset(fixture, 0, sizeof *fixture);
    conv->config = executor_make_config();
    if (zn_dispatch_init(&conv->dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, epoch) != 0 ||
        zn_native_arena_owner_init_v1(&conv->owner, &conv->config,
                                      &conv->dispatch, epoch) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED ||
        executor_complete_synthetic_prefix(&conv->owner, &conv->dispatch,
                                            EXECUTOR_FIRST_CONV_INDEX) != 0)
        return -1;

    mock_reset(&conv->mock);
    make_hooks(&conv->hooks, &conv->mock,
               z100_graph_events[EXECUTOR_FIRST_CONV_INDEX].read_count,
               &unused_hooks);
    make_ops(&conv->mock, &conv->mmio);
    conv->runtime_hooks = unused_hooks;
    if (zn_native_arena_conv_lifecycle_init_v1(
            &conv->lifecycle, &conv->owner, &conv->mmio,
            &conv->runtime_hooks) !=
        ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
        return -1;

    for (index = 0; index < sizeof nonconv->source_data; ++index)
        ((uint8_t *)nonconv->source_data)[index] =
            (uint8_t)(index * 13u + 7u);
    nonconv->hooks.context = nonconv;
    nonconv->hooks.map_source = executor_map_source;
    nonconv->hooks.source_visible = executor_source_visible;
    nonconv->hooks.map_output = executor_map_output;
    nonconv->hooks.clean_output = executor_clean_output;
    nonconv->hooks.publish_output = executor_publish_output;
    nonconv->hooks.drain_ready = executor_drain_ready;
    nonconv->hooks.return_graph_read = executor_return_read;
    nonconv->map_busy_remaining = 1;
    if (zn_native_arena_nonconv_lifecycle_init_v1(
            &nonconv->lifecycle, &conv->owner, &nonconv->hooks) !=
        ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED)
        return -1;

    return zn_native_graph_executor_v1_init(
        &fixture->executor, &conv->owner, &conv->dispatch,
        &conv->lifecycle, &nonconv->lifecycle,
        executor_resolve_conv, fixture) == ZN_NATIVE_GRAPH_EXECUTOR_V1_ACKED ?
        0 : -1;
}

static ZnNativeGraphExecutorCodeV1
executor_poll(ExecutorFixture *fixture)
{
    ZnNativeGraphExecutorCodeV1 code =
        zn_native_graph_executor_v1_step(&fixture->executor);
    if (fixture->conv.hooks.leases_code == 1)
        fixture->conv.hooks.leases_code = 0;
    return code;
}

static void
test_mixed_conv_add_conv(void)
{
    ExecutorFixture fixture;
    ZnNativeGraphExecutorCodeV1 code;
    unsigned int attempts = 0;
    unsigned int starts_before_finish;

    check(executor_fixture_init(&fixture, 210) == 0,
          "mixed executor fixture reaches event 11 after synthetic prefix");
    check(fixture.conv.dispatch.cursor == EXECUTOR_FIRST_CONV_INDEX &&
          z100_graph_events[EXECUTOR_FIRST_CONV_INDEX].event == 11 &&
          z100_graph_events[EXECUTOR_ADD_EVENT_INDEX].event == 12 &&
          z100_graph_events[EXECUTOR_SECOND_CONV_INDEX].event == 15,
          "mixed fixture selects Conv, ADD, and view-deferred Conv events");

    while (fixture.conv.dispatch.cursor == EXECUTOR_FIRST_CONV_INDEX &&
           fixture.conv.lifecycle.bridge.stage !=
               ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED) {
        if (++attempts > 96)
            break;
        code = executor_poll(&fixture);
        check(code >= 0, "first Conv request advances or remains BUSY");
        if (!fixture.conv.dispatch.pending &&
            fixture.conv.lifecycle.bridge.stage ==
                ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED)
            break;
    }
    check(fixture.resolver_calls == 1 && fixture.conv.mock.start_count == 1 &&
          fixture.conv.dispatch.cursor == EXECUTOR_FIRST_CONV_INDEX &&
          fixture.conv.lifecycle.bridge.stage ==
              ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED,
          "first Conv resolves once and acknowledges its final RETURN");

    fixture.conv.hooks.release_code = 1;
    starts_before_finish = fixture.conv.mock.start_count;
    code = executor_poll(&fixture);
    check(code == ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY &&
          fixture.executor.finish_pending && !fixture.conv.dispatch.pending &&
          fixture.conv.hooks.release_calls == 1,
          "scratch finish BUSY leaves no later dispatcher request pending");
    code = executor_poll(&fixture);
    check(code == ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY &&
          fixture.conv.hooks.release_calls == 2 &&
          fixture.conv.mock.start_count == starts_before_finish &&
          !fixture.conv.dispatch.pending,
          "finish BUSY retries only scratch release");
    fixture.conv.hooks.release_code = 0;
    check(executor_poll(&fixture) ==
              ZN_NATIVE_GRAPH_EXECUTOR_V1_SCRATCH_RELEASED &&
          !fixture.executor.binding_valid &&
          fixture.conv.lifecycle.bridge.stage ==
              ZN_NATIVE_GRAPH_CONV_STAGE_V2_IDLE,
          "scratch is released before the ADD request is fetched");

    attempts = 0;
    while (fixture.conv.dispatch.cursor <= EXECUTOR_SECOND_CONV_INDEX) {
        if (++attempts > 192)
            break;
        code = executor_poll(&fixture);
        check(code >= 0, "mixed ADD and second Conv requests make progress");
        if (fixture.conv.dispatch.cursor > EXECUTOR_SECOND_CONV_INDEX)
            break;
    }
    check(fixture.conv.dispatch.cursor == EXECUTOR_SECOND_CONV_INDEX + 1u &&
          fixture.resolver_calls == 2 &&
          fixture.nonconv.lifecycle.operator_call_count == 1 &&
          fixture.nonconv.returned_mask == 3 &&
          fixture.conv.owner.event_state[EXECUTOR_FIRST_CONV_INDEX].retired_mask == 1 &&
          fixture.conv.owner.event_state[EXECUTOR_ADD_EVENT_INDEX].retired_mask == 1 &&
          fixture.conv.owner.event_state[EXECUTOR_SECOND_CONV_INDEX].retired_mask == 3,
          "Conv -> ADD -> Conv routes through each lifecycle and retains binding");

    check(executor_complete_synthetic_prefix(&fixture.conv.owner,
                                             &fixture.conv.dispatch,
                                             ZN_NATIVE_ARENA_EVENT_COUNT_V1) == 0,
          "remaining graph control flow completes with labelled synthetic evidence");
    check(zn_native_graph_executor_v1_step(&fixture.executor) ==
              ZN_NATIVE_GRAPH_EXECUTOR_V1_COMPLETE &&
          fixture.conv.owner.complete && !fixture.conv.owner.fault,
          "executor verifies terminal dispatcher and owner state");
}

static void
test_stale_pending_and_binding(void)
{
    ExecutorFixture fixture;
    ZnNativeGraphExecutorCodeV1 code;
    unsigned int attempts;

    check(executor_fixture_init(&fixture, 211) == 0,
          "stale pending fixture initializes");
    fixture.resolver_busy_remaining = 1;
    for (attempts = 0; attempts < 16; ++attempts) {
        code = executor_poll(&fixture);
        if (code == ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY &&
            fixture.executor.pending_valid &&
            fixture.executor.pending_request.operation == ZN_RUN)
            break;
    }
    check(attempts < 16 && fixture.conv.dispatch.pending &&
          fixture.resolver_calls == 1,
          "resolver BUSY retains the exact RUN request");
    ++fixture.conv.dispatch.request.tag;
    check(zn_native_graph_executor_v1_step(&fixture.executor) ==
              ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST &&
          fixture.conv.owner.fault && fixture.conv.dispatch.fault &&
          fixture.conv.owner.slots[0].reader_count != 0 &&
          fixture.conv.mock.start_count == 0,
          "stale pending identity faults without releasing graph ownership");

    check(executor_fixture_init(&fixture, 212) == 0,
          "stale binding fixture initializes");
    for (attempts = 0; attempts < 16; ++attempts) {
        code = executor_poll(&fixture);
        if (code == ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY &&
            fixture.executor.binding_valid)
            break;
    }
    check(attempts < 16 && fixture.executor.pending_valid &&
          fixture.executor.pending_request.operation == ZN_RUN,
          "binding fixture has resolved a pending Conv RUN");
    ++fixture.executor.binding.dispatch_tag;
    check(zn_native_graph_executor_v1_step(&fixture.executor) ==
              ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST &&
          fixture.conv.owner.fault && fixture.conv.dispatch.fault &&
          fixture.conv.mock.start_count == 0 &&
          fixture.conv.owner.slots[0].reader_count != 0,
          "stale binding snapshot is rejected before hardware START");
}

static void
test_timeout_retains_ownership(void)
{
    ExecutorFixture fixture;
    ZnNativeGraphExecutorCodeV1 code;
    unsigned int attempts;
    ZnRef source_ref;

    check(executor_fixture_init(&fixture, 213) == 0,
          "timeout fixture initializes");
    for (attempts = 0; attempts < 32; ++attempts) {
        code = executor_poll(&fixture);
        if (code == ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY &&
            fixture.conv.mock.start_count != 0)
            break;
    }
    source_ref = z100_graph_events[EXECUTOR_FIRST_CONV_INDEX].reads[0];
    check(attempts < 32 && fixture.executor.binding_valid &&
          fixture.conv.lifecycle.bridge.stage ==
              ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED &&
          zn_native_conv_driver_ownership_held_v2(
              &fixture.conv.lifecycle.bridge.driver),
          "timeout fixture holds an accepted Conv and its graph read");
    check(zn_native_graph_executor_v1_timeout(&fixture.executor) ==
              ZN_NATIVE_GRAPH_EXECUTOR_V1_TIMED_OUT &&
          fixture.conv.owner.fault && fixture.conv.dispatch.fault &&
          !fixture.conv.owner.complete &&
          fixture.conv.owner.slots[source_ref.slot].reader_count != 0 &&
          fixture.conv.hooks.release_calls == 0 &&
          zn_native_graph_executor_v1_step(&fixture.executor) ==
              ZN_NATIVE_GRAPH_EXECUTOR_V1_TIMED_OUT,
          "timeout blocks resumption and preserves graph and scratch ownership");
}

int
main(void)
{
    test_mixed_conv_add_conv();
    test_stale_pending_and_binding();
    test_timeout_retains_ownership();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_GRAPH_EXECUTOR_V1_HOST_FAIL count=%u\n",
                failures);
        return 1;
    }
    printf("NATIVE_GRAPH_EXECUTOR_V1_HOST_PASS mixed_conv_add_conv=1 resolver_reuse=1 finish_busy=1 stale_pending=1 stale_binding=1 timeout_retains=1 control_flow_events=73 synthetic_events=70 physical_arena_claim=0\n");
    return 0;
}
