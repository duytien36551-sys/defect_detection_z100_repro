#include "native_arena_conv_lifecycle_v1.h"
#include "graph_plan.h"
#include "native_view_bindings_v1.h"

#define main native_graph_conv_bridge_v2_fixture_main
#include "native_graph_conv_bridge_v2_test.c"
#undef main

#include <inttypes.h>
#include <stdio.h>

enum {
    VIEW_SOURCE_CAPACITY = 819200,
    VIEW_OUTPUT_CAPACITY = 819200,
    TARGET_EVENT_9_INDEX = 3,
    TARGET_EVENT_34_INDEX = 15
};

typedef struct LifecycleFixture {
    BridgeMmio mock;
    HookState hooks;
    ZnNativeGraphConvHooksV2 runtime_hooks;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeArenaConfigV1 config;
    ZnNativeArenaOwnerV1 owner;
    ZnDispatch dispatch;
    ZnNativeArenaConvLifecycleV1 lifecycle;
    ZnNativeGraphConvBindingV2 binding;
    ZnNativeViewSourceV1 sources[3];
    uint8_t source_count;
    size_t output_bytes;
    uint64_t output_hash;
    unsigned int converter_calls;
    unsigned int clean_calls;
    unsigned int source_ready_calls;
    unsigned int publish_result_verified;
    uint8_t uncertain_start;
    uint8_t corrupt_dispatch_before_ack;
} LifecycleFixture;

static uint8_t view_source_storage[3][VIEW_SOURCE_CAPACITY];
static uint8_t view_output_storage[VIEW_OUTPUT_CAPACITY];
static unsigned int generated_converter_executions;

static const ZnNativeArenaRegionV1 lifecycle_regions[
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
native_tensor_bytes(uint16_t channels, uint16_t height, uint16_t width)
{
    return (size_t)((channels + 3u) / 4u) * height *
           ((width + 15u) / 16u) * 64u;
}

static uint64_t
hash_bytes(const uint8_t *bytes, size_t count)
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
make_lifecycle_config(void)
{
    ZnNativeArenaConfigV1 config;
    memset(&config, 0, sizeof config);
    config.arena_base = UINT32_C(268435456);
    config.arena_end = UINT32_C(273637376);
    config.arena_bytes = UINT32_C(5201920);
    config.alignment = 4096;
    memcpy(config.slots, lifecycle_regions, sizeof lifecycle_regions);
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
fixture_read32(void *context, uint32_t offset, uint32_t *value)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    return mock_read32(&fixture->mock, offset, value);
}

static int
fixture_write32(void *context, uint32_t offset, uint32_t value)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    int code = mock_write32(&fixture->mock, offset, value);
    if (code == 0 && fixture->uncertain_start &&
        offset == ZN_NC_REG_CONTROL && value == ZN_NC_CONTROL_START)
        return -1;
    return code;
}

static int
fixture_barrier(void *context)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    return mock_barrier(&fixture->mock);
}

static int
fixture_check_leases(void *context, const ZnRequest *request,
                     const ZnNativeGraphConvBindingV2 *binding)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    return hook_check_leases(&fixture->hooks, request, binding);
}

static int
fixture_prepare_sources(LifecycleFixture *fixture, const ZnRequest *request)
{
    uint8_t index;
    fixture->source_count = request->job->read_count;
    fixture->output_bytes = request->event_index == TARGET_EVENT_9_INDEX ?
        native_tensor_bytes(16, 160, 160) :
        native_tensor_bytes(128, 80, 80);
    if (request->event_index != TARGET_EVENT_9_INDEX &&
        request->event_index != TARGET_EVENT_34_INDEX)
        return -1;
    for (index = 0; index < fixture->source_count; ++index) {
        ZnNativeViewSourceV1 *source = &fixture->sources[index];
        uint16_t channels;
        uint16_t height;
        uint16_t width;
        size_t byte_index;
        if (request->event_index == TARGET_EVENT_9_INDEX) {
            channels = 32;
            height = 160;
            width = 160;
        } else if (index == 0) {
            channels = 64;
            height = 80;
            width = 80;
        } else {
            channels = 32;
            height = 80;
            width = 80;
        }
        memset(source, 0, sizeof *source);
        source->data = view_source_storage[index];
        source->bytes = native_tensor_bytes(channels, height, width);
        source->epoch = request->epoch;
        source->ref = request->job->reads[index];
        source->channels = channels;
        source->height = height;
        source->width = width;
        for (byte_index = 0; byte_index < source->bytes; ++byte_index)
            view_source_storage[index][byte_index] =
                (uint8_t)(byte_index * 17u + index * 41u +
                          (unsigned int)(source->ref.tensor + 1));
    }
    return 0;
}

static int
fixture_convert_views(void *context, const ZnRequest *request,
                      const ZnNativeGraphConvBindingV2 *binding)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    int code;
    uint64_t before_hash;
    ++fixture->hooks.convert_calls;
    if (!request || !binding ||
        binding->source_span.base != binding->scratch.base ||
        binding->source_span.bytes > binding->scratch.bytes)
        return -1;
    if (fixture->hooks.convert_code != 0)
        return fixture->hooks.convert_code;
    if (fixture_prepare_sources(fixture, request) != 0 ||
        binding->source_span.bytes != fixture->output_bytes ||
        fixture->output_bytes > sizeof view_output_storage)
        return -1;
    memset(view_output_storage, 0xa5, fixture->output_bytes);
    before_hash = hash_bytes(view_output_storage, fixture->output_bytes);
    ++fixture->converter_calls;
    code = zn_native_view_input_v1(
        request, fixture->sources, fixture->source_count,
        view_output_storage, fixture->output_bytes);
    if (code != 0)
        return -1;
    fixture->output_hash = hash_bytes(view_output_storage,
                                      fixture->output_bytes);
    if (fixture->output_hash == before_hash)
        return -1;
    ++generated_converter_executions;
    fixture->hooks.converted = 1;
    return 0;
}

static int
fixture_clean_source(void *context,
                     const ZnNativeGraphConvBindingV2 *binding)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    int code;
    ++fixture->clean_calls;
    code = hook_clean_source(&fixture->hooks, binding);
    return code;
}

static int
fixture_check_source_ready(void *context, const ZnRequest *request,
                           const ZnNativeGraphConvBindingV2 *binding)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    ++fixture->source_ready_calls;
    return hook_check_source_ready(&fixture->hooks, request, binding);
}

static int
fixture_invalidate_output(void *context,
                          const ZnNativeGraphConvBindingV2 *binding)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    return hook_invalidate_output(&fixture->hooks, binding);
}

static int
fixture_publish(void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    int code = hook_publish(&fixture->hooks, binding);
    if (code == 0 && fixture->lifecycle.bridge.driver.result_verified &&
        fixture->lifecycle.bridge.driver.result.source_generation ==
            binding->command.source_generation)
        fixture->publish_result_verified = 1;
    if (code == 0 && fixture->corrupt_dispatch_before_ack)
        fixture->dispatch.request.tag ^= UINT32_C(0x80000000);
    return code;
}

static int
fixture_drain_ready(void *context, const ZnRequest *request,
                    const ZnNativeGraphConvBindingV2 *binding)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    return hook_drain_ready(&fixture->hooks, request, binding);
}

static int
fixture_return_read(void *context, const ZnRequest *request,
                    const ZnNativeGraphConvBindingV2 *binding,
                    uint8_t read_index)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    return hook_return_graph_read(&fixture->hooks, request, binding,
                                  read_index);
}

static int
fixture_release_scratch(void *context,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    LifecycleFixture *fixture = (LifecycleFixture *)context;
    return hook_release_scratch(&fixture->hooks, binding);
}

static void
make_lifecycle_binding(LifecycleFixture *fixture, const ZnRequest *request)
{
    uint64_t destination_end;
    uint64_t scratch_end;
    make_binding(&fixture->binding, request);
    fixture->output_bytes = request->event_index == TARGET_EVENT_9_INDEX ?
        native_tensor_bytes(16, 160, 160) :
        native_tensor_bytes(128, 80, 80);
    fixture->binding.scratch.base = UINT32_C(0x22000000);
    fixture->binding.scratch.bytes = UINT32_C(1048576);
    fixture->binding.source_span.base = fixture->binding.scratch.base;
    fixture->binding.source_span.bytes = (uint32_t)fixture->output_bytes;
    fixture->binding.command.source_base = fixture->binding.source_span.base;
    fixture->binding.command.source_lease_region_begin =
        fixture->binding.scratch.base;
    scratch_end = (uint64_t)fixture->binding.scratch.base +
                  fixture->binding.scratch.bytes;
    fixture->binding.command.source_lease_region_end.low = (uint32_t)scratch_end;
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
setup_lifecycle_fixture(LifecycleFixture *fixture, uint16_t event_index,
                        uint32_t epoch)
{
    ZnNativeGraphConvHooksV2 unused_hooks;
    ZnRequest request;
    memset(fixture, 0, sizeof *fixture);
    fixture->config = make_lifecycle_config();
    if (zn_dispatch_init(&fixture->dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, epoch) != 0 ||
        zn_native_arena_owner_init_v1(&fixture->owner, &fixture->config,
                                      &fixture->dispatch, epoch) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED ||
        complete_synthetic_prefix(&fixture->owner, &fixture->dispatch,
                                  event_index) != 0)
        return -1;

    mock_reset(&fixture->mock);
    make_hooks(&fixture->hooks, &fixture->mock,
               z100_graph_events[event_index].read_count, &unused_hooks);
    fixture->mmio.context = fixture;
    fixture->mmio.read32 = fixture_read32;
    fixture->mmio.write32 = fixture_write32;
    fixture->mmio.write_barrier = fixture_barrier;
    fixture->runtime_hooks.context = fixture;
    fixture->runtime_hooks.check_leases = fixture_check_leases;
    fixture->runtime_hooks.convert_views = fixture_convert_views;
    fixture->runtime_hooks.clean_source = fixture_clean_source;
    fixture->runtime_hooks.check_source_ready = fixture_check_source_ready;
    fixture->runtime_hooks.invalidate_output = fixture_invalidate_output;
    fixture->runtime_hooks.validate_and_publish = fixture_publish;
    fixture->runtime_hooks.drain_ready = fixture_drain_ready;
    fixture->runtime_hooks.return_graph_read = fixture_return_read;
    fixture->runtime_hooks.release_scratch = fixture_release_scratch;
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
    make_lifecycle_binding(fixture, &request);
    return 0;
}

static ZnNativeArenaConvLifecycleCodeV1
step_request(LifecycleFixture *fixture, const ZnRequest *request,
             const ZnNativeGraphConvBindingV2 *binding)
{
    return zn_native_arena_conv_lifecycle_step_v1(
        &fixture->lifecycle, &fixture->dispatch, request, binding);
}

static void
test_event9_single_read_no_retire_and_busy_gates(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    ZnRequest stale;
    ZnNativeArenaConvLifecycleCodeV1 code;
    const ZnEvent *event;

    check(setup_lifecycle_fixture(&fixture, TARGET_EVENT_9_INDEX, 200) == 0,
          "event 9 prefix fixture reaches real plan RUN");
    event = &z100_graph_events[TARGET_EVENT_9_INDEX];
    check(event->event == 9 && event->read_count == 1 &&
          event->retire_count == 0,
          "event 9 is one-read and has no RETIRE");
    request = fixture.dispatch.request;
    stale = request;
    ++stale.epoch;
    check(step_request(&fixture, &stale, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_STALE_REQUEST &&
          !fixture.owner.fault && fixture.mock.start_count == 0,
          "stale RUN identity is rejected without side effects");

    fixture.hooks.leases_code = 1;
    code = step_request(&fixture, &request, &fixture.binding);
    check(code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.mock.start_count == 0 && fixture.converter_calls == 0 &&
          !fixture.owner.event_state[TARGET_EVENT_9_INDEX].run_started,
          "lease BUSY retries before converter and START");
    fixture.hooks.leases_code = 0;
    fixture.hooks.convert_code = 1;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.mock.start_count == 0,
          "generated converter callback BUSY retains pending RUN");
    fixture.hooks.convert_code = 0;
    fixture.hooks.clean_code = 1;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.converter_calls == 1 && fixture.mock.start_count == 0,
          "actual event 9 view conversion completes before cache clean retry");
    fixture.hooks.clean_code = 0;
    fixture.hooks.source_ready_code = 1;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.mock.start_count == 0,
          "source visibility BUSY blocks START");
    fixture.hooks.source_ready_code = 0;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.mock.start_count == 1 && fixture.lifecycle.run_started_recorded &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].run_started &&
          !fixture.owner.event_state[TARGET_EVENT_9_INDEX].output_published,
          "RUN submission is recorded without publishing output");
    check(fixture.output_hash != 0 && fixture.converter_calls == 1,
          "generated event 9 converter materializes deterministic output bytes");

    check(fixture.publish_result_verified == 0,
          "publication has not run while driver result is pending");
    fixture.hooks.publish_code = 1;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.mock.ack_count == 1 && fixture.hooks.publish_calls == 1 &&
          !fixture.owner.event_state[TARGET_EVENT_9_INDEX].output_published &&
          fixture.dispatch.pending,
          "publication BUSY retains RUN and destination reservation");
    fixture.hooks.publish_code = 0;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].output_published &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].run_acked &&
          !fixture.dispatch.pending,
          "verified result and successful publish precede real RUN ACK mirror");
    check(fixture.lifecycle.bridge_dispatch_ack_count == 1 &&
          fixture.lifecycle.owner_shadow_commit_count == 1,
          "RUN dispatcher ACK and owner shadow commit counts agree");

    check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
          request.operation == ZN_DRAIN,
          "event 9 advances to DRAIN");
    fixture.hooks.drain_code = 1;
    code = step_request(&fixture, &request, NULL);
    check(code ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.dispatch.pending &&
          !fixture.owner.event_state[TARGET_EVENT_9_INDEX].io_quiescent &&
          fixture.owner.slots[event->reads[0].slot].io_count != 0,
          "unquiescent DRAIN holds IO references and dispatcher ACK");
    fixture.hooks.drain_code = 0;
    code = step_request(&fixture, &request, NULL);
    check(code ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].io_quiescent &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].drained,
          "runtime ready plus idle driver permits DRAIN quiescence and ACK");

    check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
          request.operation == ZN_RETURN &&
          test_ref_equal(request.ref, event->reads[0]),
          "event 9 returns its exact single graph read");
    fixture.hooks.return_code = 1;
    check(step_request(&fixture, &request, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.lifecycle.bridge.return_cursor == 0 &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].returned_mask == 0,
          "RETURN BUSY retains original graph reference");
    fixture.hooks.return_code = 0;
    check(step_request(&fixture, &request, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].returned_mask == 1,
          "one-read RETURN commits to owner only after bridge ACK");
    check(fixture.lifecycle.bridge_dispatch_ack_count == 3 &&
          fixture.lifecycle.owner_shadow_commit_count == 3 &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].retired_mask == 0,
          "event 9 has three mirrored bridge ACKs and no retirement");

    check(fixture.publish_result_verified == 1,
          "runtime publication callback observes verified driver result identity");
    printf("NATIVE_ARENA_CONV_VIEW_EVENT_PASS event=9 reads=1 output_bytes=%zu output_fnv64=%016" PRIx64 "\n",
           fixture.output_bytes, fixture.output_hash);
    check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
          request.event_index == 4 && request.operation == ZN_ALLOCATE &&
          request.job->event == 11,
          "event 9 no-retire path reaches event 11 allocation");
    check(step_request(&fixture, &request, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FINISH_REQUIRED &&
          fixture.dispatch.pending,
          "later graph ACK is blocked until scratch finish");
    fixture.hooks.release_code = 1;
    check(zn_native_arena_conv_lifecycle_finish_v1(
              &fixture.lifecycle, &fixture.dispatch) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.dispatch.pending && fixture.mock.start_count == 1,
          "BUSY finish retries release without resubmitting Conv");
    check(step_request(&fixture, &request, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FINISH_REQUIRED,
          "finish BUSY continues to gate the next graph ACK");
    fixture.hooks.release_code = 0;
    check(zn_native_arena_conv_lifecycle_finish_v1(
              &fixture.lifecycle, &fixture.dispatch) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_SCRATCH_RELEASED &&
          fixture.hooks.scratch_released && fixture.mock.start_count == 1,
          "scratch finish succeeds before next graph allocation ACK");
    check(step_request(&fixture, &request, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED &&
          !fixture.dispatch.pending,
          "event 11 allocation proceeds after scratch release");
}

static void
test_event34_three_reads_and_retire(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    uint8_t index;

    check(setup_lifecycle_fixture(&fixture, TARGET_EVENT_34_INDEX, 201) == 0,
          "event 34 prefix fixture reaches generated three-read RUN");
    check(z100_graph_events[TARGET_EVENT_34_INDEX].event == 34 &&
          z100_graph_events[TARGET_EVENT_34_INDEX].read_count == 3 &&
          z100_graph_events[TARGET_EVENT_34_INDEX].retire_count == 3,
          "event 34 fixture has three graph reads and three retires");
    request = fixture.dispatch.request;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
          fixture.converter_calls == 1 && fixture.output_bytes == 819200 &&
          fixture.output_hash != 0,
          "generated event 34 view converter executes for all three sources");
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED &&
          fixture.owner.event_state[TARGET_EVENT_34_INDEX].output_published,
          "event 34 publishes after verified driver result");
    check(fixture.publish_result_verified == 1,
          "event 34 publisher receives exact verified driver result");
    printf("NATIVE_ARENA_CONV_VIEW_EVENT_PASS event=34 reads=3 output_bytes=%zu output_fnv64=%016" PRIx64 "\n",
           fixture.output_bytes, fixture.output_hash);
    check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
          request.operation == ZN_DRAIN &&
          step_request(&fixture, &request, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED,
          "event 34 drain completes after synthetic runtime readiness");

    for (index = 0; index < 3; ++index) {
        check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
              request.operation == ZN_RETURN && request.event_index == 15 &&
              test_ref_equal(request.ref,
                             z100_graph_events[TARGET_EVENT_34_INDEX].reads[index]),
              "event 34 exposes exact ordered RETURN ref");
        if (index == 1) {
            fixture.hooks.return_code = 1;
            check(step_request(&fixture, &request, NULL) ==
                      ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY &&
                  fixture.lifecycle.bridge.return_cursor == index,
                  "three-read RETURN BUSY does not advance bridge cursor");
            fixture.hooks.return_code = 0;
        }
        check(step_request(&fixture, &request, NULL) ==
                  ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED,
              "event 34 original read RETURN is bridge ACK mirrored");
    }
    check(fixture.owner.event_state[TARGET_EVENT_34_INDEX].returned_mask == 7 &&
          fixture.owner.event_state[TARGET_EVENT_34_INDEX].retired_mask == 0 &&
          fixture.lifecycle.bridge_dispatch_ack_count == 5 &&
          fixture.lifecycle.owner_shadow_commit_count == 5,
          "all three returns commit after bridge ACK with no early retire");
    check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
          request.operation == ZN_RETIRE && request.event_index == 15,
          "event 34 retirement waits behind explicit scratch finish");
    check(step_request(&fixture, &request, NULL) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FINISH_REQUIRED &&
          fixture.owner.event_state[TARGET_EVENT_34_INDEX].retired_mask == 0,
          "RETIRE cannot ACK before scratch finish");
    check(zn_native_arena_conv_lifecycle_finish_v1(
              &fixture.lifecycle, &fixture.dispatch) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_SCRATCH_RELEASED,
          "event 34 scratch is released after three returns");
    for (index = 0; index < 3; ++index) {
        if (index != 0)
            check(zn_dispatch_next(&fixture.dispatch, &request) == 1 &&
                  request.operation == ZN_RETIRE && request.event_index == 15,
                  "event 34 next RETIRE follows owner ACK");
        check(step_request(&fixture, &request, NULL) ==
                  ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED,
              "event 34 RETIRE advances only after successful finish");
    }
    check(fixture.owner.event_state[TARGET_EVENT_34_INDEX].retired_mask == 7 &&
          fixture.mock.start_count == 1 && fixture.hooks.release_calls == 1,
          "three-read event retires after one START and one scratch release");
}

static void
test_failures_and_uncertain_ack(void)
{
    LifecycleFixture fixture;
    ZnRequest request;
    ZnRef read_ref;

    check(setup_lifecycle_fixture(&fixture, TARGET_EVENT_9_INDEX, 202) == 0,
          "result identity failure fixture initialized");
    request = fixture.dispatch.request;
    read_ref = request.job->reads[0];
    ++fixture.binding.graph_read_refs[0].generation;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.owner.fault && fixture.dispatch.fault &&
          fixture.mock.start_count == 0 &&
          fixture.owner.slots[read_ref.slot].reader_count != 0,
          "stale binding ref poisons owner and retains graph reader");

    check(setup_lifecycle_fixture(&fixture, TARGET_EVENT_9_INDEX, 203) == 0,
          "result mismatch fixture initialized");
    request = fixture.dispatch.request;
    read_ref = request.job->reads[0];
    fixture.mock.result_source_generation_xor = 1;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY,
          "result mismatch fixture submits one RUN");
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.owner.fault && fixture.dispatch.fault &&
          fixture.hooks.publish_calls == 0 &&
          fixture.owner.slots[read_ref.slot].reader_count != 0,
          "unverified driver result never calls publication and retains refs");

    check(setup_lifecycle_fixture(&fixture, TARGET_EVENT_9_INDEX, 204) == 0,
          "runtime publish failure fixture initialized");
    request = fixture.dispatch.request;
    read_ref = request.job->reads[0];
    fixture.hooks.publish_code = -1;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY,
          "runtime publish failure fixture submits one RUN");
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.owner.fault && fixture.dispatch.fault &&
          fixture.hooks.publish_calls == 1 && !fixture.hooks.published &&
          !fixture.owner.event_state[TARGET_EVENT_9_INDEX].output_published &&
          fixture.owner.slots[read_ref.slot].reader_count != 0,
          "runtime publication failure faults owner without releasing refs");

    check(setup_lifecycle_fixture(&fixture, TARGET_EVENT_9_INDEX, 205) == 0,
          "uncertain START fixture initialized");
    request = fixture.dispatch.request;
    read_ref = request.job->reads[0];
    fixture.uncertain_start = 1;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.mock.start_count == 1 && fixture.owner.fault &&
          fixture.dispatch.fault &&
          zn_native_conv_driver_ownership_held_v2(&fixture.lifecycle.bridge.driver) &&
          fixture.owner.slots[read_ref.slot].reader_count != 0 &&
          fixture.hooks.release_calls == 0,
          "uncertain START faults owner and retains input and scratch ownership");

    check(setup_lifecycle_fixture(&fixture, TARGET_EVENT_9_INDEX, 206) == 0,
          "uncertain dispatcher ACK fixture initialized");
    request = fixture.dispatch.request;
    read_ref = request.job->reads[0];
    fixture.corrupt_dispatch_before_ack = 1;
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY,
          "uncertain ACK fixture submits one RUN");
    check(step_request(&fixture, &request, &fixture.binding) ==
              ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED &&
          fixture.owner.fault && fixture.dispatch.fault &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].run_started &&
          fixture.owner.slots[read_ref.slot].reader_count != 0 &&
          fixture.owner.event_state[TARGET_EVENT_9_INDEX].output_published,
          "uncertain dispatcher ACK faults owner and preserves graph references");
}

int
main(void)
{
    if (native_graph_conv_bridge_v2_fixture_main() != 0)
        ++failures;
    test_event9_single_read_no_retire_and_busy_gates();
    test_event34_three_reads_and_retire();
    test_failures_and_uncertain_ack();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_ARENA_CONV_LIFECYCLE_V1_HOST_FAIL count=%u\n",
                failures);
        return 1;
    }
    printf("NATIVE_ARENA_CONV_LIFECYCLE_V1_HOST_PASS event9_reads=1 event9_retires=0 event34_reads=3 event34_retires=3 generated_converter_event_cases=2 generated_converter_executions=%u bridge_acks=8 owner_shadow_commits=8 busy_retry_coverage=1 stale_request=1 stale_ref=1 result_identity_failure=1 publication_failure=1 uncertain_start=1 uncertain_ack=1 synthetic_prefix=1 physical_arena_claim=0\n",
           generated_converter_executions);
    return 0;
}
