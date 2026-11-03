#define main native_graph_abort_embedded_bridge_test_main
#include "native_graph_conv_bridge_v2_test.c"
#undef main

#include "native_graph_abort_v1.h"
#include "graph_plan.h"

#include <stdio.h>

enum {
    ABORT_FIRST_CONV_INDEX = 4,
    ABORT_SOURCE_CAPACITY = 819200,
    ABORT_OUTPUT_CAPACITY = 409600
};

typedef enum AbortWriteMode {
    ABORT_WRITE_NORMAL = 0,
    ABORT_WRITE_ACCEPT_ON_ABORT = 1,
    ABORT_WRITE_CANCEL_DRAINING = 2,
    ABORT_WRITE_START_UNCERTAIN = 3,
    ABORT_WRITE_ACK_UNCERTAIN = 4
} AbortWriteMode;

typedef struct AbortFixture {
    ZnNativeArenaConfigV1 config;
    ZnNativeArenaOwnerV1 owner;
    ZnDispatch dispatch;
    ZnNativeArenaConvLifecycleV1 conv_lifecycle;
    ZnNativeArenaNonConvLifecycleV1 nonconv_lifecycle;
    ZnNativeGraphExecutorV1 executor;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 runtime_hooks;
    ZnNativeArenaNonConvHooksV1 nonconv_hooks;
    BridgeMmio mock;
    HookState hook_state;
    uint32_t resolver_calls;
    uint8_t source_data[ABORT_SOURCE_CAPACITY];
    uint8_t output_data[ABORT_OUTPUT_CAPACITY];
} AbortFixture;

typedef struct AbortHookCounts {
    unsigned int leases;
    unsigned int convert;
    unsigned int clean;
    unsigned int source_ready;
    unsigned int invalidate;
    unsigned int publish;
    unsigned int drain;
    unsigned int returns;
    unsigned int release;
    int scratch_reserved;
    int scratch_released;
} AbortHookCounts;

static AbortWriteMode abort_write_mode;
static unsigned int abort_mmio_read_count;

static const ZnNativeArenaRegionV1 abort_regions[
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
abort_make_config(void)
{
    ZnNativeArenaConfigV1 config;
    memset(&config, 0, sizeof config);
    config.arena_base = UINT32_C(268435456);
    config.arena_end = UINT32_C(273637376);
    config.arena_bytes = UINT32_C(5201920);
    config.alignment = 4096;
    memcpy(config.slots, abort_regions, sizeof abort_regions);
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

static void
abort_set_end(ZnNativeConvEnd33 *end, uint64_t value)
{
    end->low = (uint32_t)value;
    end->high = (uint8_t)(value >> 32);
}

static int
abort_synthetic_request(ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
                        const ZnRequest *request)
{
    ZnNativeArenaOwnerCodeV1 code;

    if (request->operation == ZN_RUN) {
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
        if (zn_native_arena_owner_step_v1(owner, dispatch, request) !=
                ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND ||
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
abort_complete_prefix(ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
                      uint16_t target)
{
    ZnRequest request;

    while (dispatch->cursor < target) {
        if (zn_dispatch_next(dispatch, &request) != 1 ||
            request.event_index != dispatch->cursor ||
            abort_synthetic_request(owner, dispatch, &request) != 0)
            return -1;
    }
    return dispatch->cursor == target ? 0 : -1;
}

static int
abort_noop_map_source(void *context, const ZnRequest *request,
                      uint8_t read_index, uint32_t expected_address,
                      uint32_t expected_bytes,
                      ZnNativeArenaNonConvSourceV1 *source)
{
    (void)context; (void)request; (void)read_index;
    (void)expected_address; (void)expected_bytes; (void)source;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int
abort_noop_source_visible(void *context, const ZnRequest *request,
                          uint8_t read_index,
                          const ZnNativeArenaNonConvSourceV1 *source)
{
    (void)context; (void)request; (void)read_index; (void)source;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int
abort_noop_map_output(void *context, const ZnRequest *request,
                      uint32_t expected_address, uint32_t output_bytes,
                      ZnNativeArenaNonConvOutputV1 *output)
{
    (void)context; (void)request; (void)expected_address;
    (void)output_bytes; (void)output;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int
abort_noop_clean_output(void *context, const ZnRequest *request,
                        const ZnNativeArenaNonConvOutputV1 *output,
                        uint32_t output_bytes)
{
    (void)context; (void)request; (void)output; (void)output_bytes;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int
abort_noop_publish_output(void *context, const ZnRequest *request,
                          const ZnNativeArenaNonConvOutputV1 *output,
                          uint32_t output_bytes)
{
    (void)context; (void)request; (void)output; (void)output_bytes;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int
abort_noop_nonconv_drain(void *context, const ZnRequest *request,
                         ZnNativeArenaQuiescenceEvidenceV1 *evidence)
{
    (void)context; (void)request; (void)evidence;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int
abort_noop_return(void *context, const ZnRequest *request,
                  uint8_t read_index, uint32_t physical_address, ZnRef ref)
{
    (void)context; (void)request; (void)read_index;
    (void)physical_address; (void)ref;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int
abort_resolve_conv(void *context, const ZnRequest *request,
                   ZnNativeGraphConvBindingV2 *binding)
{
    AbortFixture *fixture = (AbortFixture *)context;
    uint64_t source_end;
    uint64_t destination_end;

    if (!fixture || !request || !request->job || !binding ||
        request->operation != ZN_RUN ||
        request->event_index != ABORT_FIRST_CONV_INDEX)
        return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_FAILED_V1;
    ++fixture->resolver_calls;
    make_binding(binding, request);
    binding->scratch.generation = 800u + fixture->resolver_calls;
    binding->source_span.base = binding->scratch.base;
    binding->command.source_base = binding->source_span.base;
    binding->command.source_generation = binding->scratch.generation;
    binding->command.source_lease_region_begin = binding->scratch.base;
    source_end = (uint64_t)binding->scratch.base + binding->scratch.bytes;
    abort_set_end(&binding->command.source_lease_region_end, source_end);
    binding->command.destination_reservation_region_begin =
        request->job->destination.address;
    destination_end = (uint64_t)request->job->destination.address +
                      request->job->destination.bytes;
    abort_set_end(&binding->command.destination_reservation_region_end,
                  destination_end);
    fixture->mock.expected_tiles = binding->expected_tiles;
    return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_READY_V1;
}

static int
abort_write32(void *context, uint32_t offset, uint32_t value)
{
    BridgeMmio *mock = (BridgeMmio *)context;
    int code;

    if (abort_write_mode == ABORT_WRITE_ACCEPT_ON_ABORT &&
        offset == ZN_NC_REG_CONTROL &&
        value == ZN_NC_CONTROL_ABORT_BEFORE_ACCEPT) {
        if (!mock || mock->write_count >= WRITE_CAPACITY)
            return -1;
        mock->write_offsets[mock->write_count] = offset;
        mock->write_values[mock->write_count++] = value;
        ++mock->abort_count;
        mock->bridge_error = ZN_NC_BRIDGE_ERROR_NONE;
        mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE |
                       ZN_NC_STATUS_DRAIN_COMPLETE;
        return 0;
    }
    if (abort_write_mode == ABORT_WRITE_CANCEL_DRAINING &&
        offset == ZN_NC_REG_CONTROL &&
        value == ZN_NC_CONTROL_CANCEL_ACCEPTED) {
        if (!mock || mock->write_count >= WRITE_CAPACITY)
            return -1;
        mock->write_offsets[mock->write_count] = offset;
        mock->write_values[mock->write_count++] = value;
        ++mock->cancel_count;
        mock->bridge_error = ZN_NC_BRIDGE_ERROR_NONE;
        mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE |
                       ZN_NC_STATUS_FAULT | ZN_NC_STATUS_NEEDS_DRAIN;
        return 0;
    }
    if (abort_write_mode == ABORT_WRITE_START_UNCERTAIN &&
        offset == ZN_NC_REG_CONTROL && value == ZN_NC_CONTROL_START) {
        abort_write_mode = ABORT_WRITE_NORMAL;
        code = mock_write32(context, offset, value);
        return code == 0 ? -1 : code;
    }
    if (abort_write_mode == ABORT_WRITE_ACK_UNCERTAIN &&
        offset == ZN_NC_REG_CONTROL && value == ZN_NC_CONTROL_ACK_RESULT) {
        abort_write_mode = ABORT_WRITE_NORMAL;
        code = mock_write32(context, offset, value);
        return code == 0 ? -1 : code;
    }
    if (offset == ZN_NC_REG_CONTROL && value == ZN_NC_CONTROL_ACK_RESULT &&
        mock && (mock->status & ZN_NC_STATUS_FAULT)) {
        if (mock->write_count >= WRITE_CAPACITY)
            return -1;
        mock->write_offsets[mock->write_count] = offset;
        mock->write_values[mock->write_count++] = value;
        ++mock->ack_count;
        mock->status = ZN_NC_STATUS_FAULT | ZN_NC_STATUS_DRAIN_COMPLETE;
        return 0;
    }
    return mock_write32(context, offset, value);
}

static int
abort_read32(void *context, uint32_t offset, uint32_t *value)
{
    ++abort_mmio_read_count;
    return mock_read32(context, offset, value);
}

static int
abort_fixture_init(AbortFixture *fixture, int hold_pending)
{
    unsigned int attempts;
    ZnNativeGraphExecutorCodeV1 code;

    memset(fixture, 0, sizeof *fixture);
    fixture->config = abort_make_config();
    if (zn_dispatch_init(&fixture->dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, 240) != 0 ||
        zn_native_arena_owner_init_v1(&fixture->owner, &fixture->config,
                                      &fixture->dispatch, 240) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED ||
        abort_complete_prefix(&fixture->owner, &fixture->dispatch,
                              ABORT_FIRST_CONV_INDEX) != 0)
        return -1;

    mock_reset(&fixture->mock);
    fixture->mock.hold_pending = hold_pending;
    fixture->mock.complete_after = UINT32_MAX;
    abort_mmio_read_count = 0;
    make_hooks(&fixture->hook_state, &fixture->mock,
               z100_graph_events[ABORT_FIRST_CONV_INDEX].read_count,
               &fixture->runtime_hooks);
    make_ops(&fixture->mock, &fixture->mmio);
    fixture->mmio.read32 = abort_read32;
    fixture->mmio.write32 = abort_write32;
    if (zn_native_arena_conv_lifecycle_init_v1(
            &fixture->conv_lifecycle, &fixture->owner, &fixture->mmio,
            &fixture->runtime_hooks) !=
        ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
        return -1;

    fixture->nonconv_hooks.context = fixture;
    fixture->nonconv_hooks.map_source = abort_noop_map_source;
    fixture->nonconv_hooks.source_visible = abort_noop_source_visible;
    fixture->nonconv_hooks.map_output = abort_noop_map_output;
    fixture->nonconv_hooks.clean_output = abort_noop_clean_output;
    fixture->nonconv_hooks.publish_output = abort_noop_publish_output;
    fixture->nonconv_hooks.drain_ready = abort_noop_nonconv_drain;
    fixture->nonconv_hooks.return_graph_read = abort_noop_return;
    if (zn_native_arena_nonconv_lifecycle_init_v1(
            &fixture->nonconv_lifecycle, &fixture->owner,
            &fixture->nonconv_hooks) !=
        ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED ||
        zn_native_graph_executor_v1_init(
            &fixture->executor, &fixture->owner, &fixture->dispatch,
            &fixture->conv_lifecycle, &fixture->nonconv_lifecycle,
            abort_resolve_conv, fixture) !=
            ZN_NATIVE_GRAPH_EXECUTOR_V1_ACKED)
        return -1;

    for (attempts = 0; attempts < 32; ++attempts) {
        code = zn_native_graph_executor_v1_step(&fixture->executor);
        if (fixture->mock.start_count != 0)
            break;
        if (code < 0)
            return -1;
    }
    return attempts < 32 && fixture->executor.binding_valid &&
           fixture->executor.pending_valid ? 0 : -1;
}

static int
abort_fixture_timeout(AbortFixture *fixture)
{
    return zn_native_graph_executor_v1_timeout(&fixture->executor) ==
               ZN_NATIVE_GRAPH_EXECUTOR_V1_TIMED_OUT &&
           fixture->owner.fault && fixture->dispatch.fault &&
           fixture->dispatch.pending && fixture->executor.terminal ? 0 : -1;
}

static int
abort_ref_equal(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
abort_owner_equal(const ZnNativeArenaOwnerV1 *a,
                  const ZnNativeArenaOwnerV1 *b)
{
    uint8_t slot_index;
    uint16_t event_index;

    if (a->events != b->events || a->epoch != b->epoch ||
        a->event_count != b->event_count || a->fault != b->fault ||
        a->initialized != b->initialized || a->complete != b->complete)
        return 0;
    for (slot_index = 0; slot_index < ZN_NATIVE_ARENA_SLOT_COUNT_V1;
         ++slot_index) {
        const ZnNativeArenaSlotV1 *x = &a->slots[slot_index];
        const ZnNativeArenaSlotV1 *y = &b->slots[slot_index];
        if (x->region.address != y->region.address ||
            x->region.capacity_bytes != y->region.capacity_bytes ||
            !abort_ref_equal(x->ref, y->ref) || x->bytes != y->bytes ||
            x->generation_high_water != y->generation_high_water ||
            x->reader_count != y->reader_count || x->io_count != y->io_count ||
            x->state != y->state)
            return 0;
    }
    for (event_index = 0; event_index < ZN_NATIVE_ARENA_EVENT_COUNT_V1;
         ++event_index) {
        const ZnNativeArenaEventStateV1 *x = &a->event_state[event_index];
        const ZnNativeArenaEventStateV1 *y = &b->event_state[event_index];
        if (x->run_tag != y->run_tag || x->allocated != y->allocated ||
            x->run_started != y->run_started ||
            x->run_completed != y->run_completed ||
            x->output_published != y->output_published ||
            x->io_quiescent != y->io_quiescent || x->drained != y->drained ||
            x->run_acked != y->run_acked ||
            x->acquired_mask != y->acquired_mask ||
            x->returned_mask != y->returned_mask ||
            x->retired_mask != y->retired_mask)
            return 0;
    }
    return 1;
}

static AbortHookCounts
abort_hook_counts(const HookState *state)
{
    AbortHookCounts counts;
    counts.leases = state->leases_calls;
    counts.convert = state->convert_calls;
    counts.clean = state->clean_calls;
    counts.source_ready = state->source_ready_calls;
    counts.invalidate = state->invalidate_calls;
    counts.publish = state->publish_calls;
    counts.drain = state->drain_calls;
    counts.returns = state->return_calls;
    counts.release = state->release_calls;
    counts.scratch_reserved = state->scratch_reserved;
    counts.scratch_released = state->scratch_released;
    return counts;
}

static int
abort_hook_counts_equal(AbortHookCounts a, AbortHookCounts b)
{
    return a.leases == b.leases && a.convert == b.convert &&
           a.clean == b.clean && a.source_ready == b.source_ready &&
           a.invalidate == b.invalidate && a.publish == b.publish &&
           a.drain == b.drain && a.returns == b.returns &&
           a.release == b.release && a.scratch_reserved == b.scratch_reserved &&
           a.scratch_released == b.scratch_released;
}

static void
abort_check_retained(AbortFixture *fixture,
                     const ZnNativeArenaOwnerV1 *owner_before,
                     AbortHookCounts counts_before, const char *name)
{
    check(abort_owner_equal(&fixture->owner, owner_before), name);
    check(abort_hook_counts_equal(abort_hook_counts(&fixture->hook_state),
                                  counts_before),
          "abort adapter invokes no graph, cache, publication, RETURN, or release hook");
    check(fixture->owner.event_state[ABORT_FIRST_CONV_INDEX].acquired_mask ==
              (uint8_t)((UINT32_C(1) <<
                         fixture->owner.events[ABORT_FIRST_CONV_INDEX].read_count) - 1u) &&
          fixture->owner.event_state[ABORT_FIRST_CONV_INDEX].returned_mask == 0 &&
          !fixture->owner.event_state[ABORT_FIRST_CONV_INDEX].output_published &&
          fixture->hook_state.scratch_reserved &&
          !fixture->hook_state.scratch_released,
          "graph and scratch leases remain held after abort work");
}

static void
test_preaccept_abort(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts counts_before;

    check(abort_fixture_init(&fixture, 1) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "preaccept fixture reaches a faulted terminal executor");
    owner_before = fixture.owner;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY,
          "preaccept adapter binds the exact timed out RUN");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS &&
          fixture.mock.abort_count == 1 && fixture.mock.cancel_count == 0 &&
          fixture.mock.ack_count == 0,
          "pending command sends ABORT and waits for checked ACK");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "preaccept abort preserves every arena slot and event ledger field");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED &&
          fixture.mock.ack_count == 1 &&
          fixture.conv_lifecycle.bridge.driver.state ==
              ZN_NATIVE_CONV_STATE_V2_IDLE,
          "preaccept bridge error is checked and ACK readback proves quiescence");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "preaccept ACK keeps graph ownership and publication state unchanged");
}

static void
test_same_edge_acceptance_race(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts counts_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 1) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "same-edge fixture starts pending and latches executor timeout");
    owner_before = fixture.owner;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY,
          "same-edge adapter binds the submitted command");
    abort_write_mode = ABORT_WRITE_ACCEPT_ON_ABORT;
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS &&
          fixture.mock.abort_count == 1 && fixture.mock.cancel_count == 1,
          "ABORT status reread sees same-edge acceptance and issues CANCEL");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "acceptance-race cancellation retains all graph references");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED &&
          fixture.mock.ack_count == 1 &&
          fixture.conv_lifecycle.bridge.driver.state ==
              ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT,
          "accepted cancellation ACK preserves the driver's sticky fault");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "accepted fault ACK does not publish or release graph ownership");
}

static void
test_accepted_cancel(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts counts_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 0) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "accepted fixture reaches terminal timeout with device ownership");
    owner_before = fixture.owner;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY,
          "accepted adapter binds driver and lifecycle identities");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS &&
          fixture.mock.cancel_count == 1 && fixture.mock.ack_count == 0,
          "accepted command sends one CANCEL and retains leases while draining");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "CANCEL drain phase preserves arena masks and slot references");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED &&
          fixture.mock.ack_count == 1 &&
          fixture.conv_lifecycle.bridge.driver.result_is_fault,
          "checked fault result ACK proves quiet and retains sticky-fault state");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "accepted fault result remains unpublished and leased");
}

static void
test_draining_fault(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts counts_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 0) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "draining-fault fixture starts from a faulted submitted RUN");
    owner_before = fixture.owner;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY,
          "draining-fault adapter binds the RUN command");
    abort_write_mode = ABORT_WRITE_CANCEL_DRAINING;
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS &&
          fixture.mock.cancel_count == 1 && fixture.mock.ack_count == 0,
          "cancelled device fault remains in drain until terminal result appears");
    mock_set_result(&fixture.mock);
    fixture.mock.status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_FAULT |
                          ZN_NC_STATUS_DRAIN_COMPLETE |
                          ZN_NC_STATUS_RESULT_VALID;
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS && fixture.mock.ack_count == 0,
          "draining fault is polled once until checked terminal result");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "fault drain poll leaves graph and scratch leases untouched");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED &&
          fixture.mock.ack_count == 1,
          "drained fault is ACKed only after result identity verification");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "drained fault ACK retains all owner state");
}

static void
test_late_success_is_consumed_without_publish(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts counts_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 0) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "late-success fixture holds the terminal executor fault");
    mock_set_result(&fixture.mock);
    fixture.mock.status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_DONE |
                          ZN_NC_STATUS_DRAIN_COMPLETE |
                          ZN_NC_STATUS_RESULT_VALID;
    owner_before = fixture.owner;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY,
          "late success attaches to the frozen command identity");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS &&
          fixture.conv_lifecycle.bridge.driver.state ==
              ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT,
          "late SUCCESS is consumed by the driver without entering bridge finish");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED &&
          fixture.mock.ack_count == 1 && fixture.hook_state.publish_calls == 0 &&
          fixture.hook_state.invalidate_calls == 0,
          "late SUCCESS ACK proves quiescence without cache or publication callbacks");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "late SUCCESS leaves masks, slots, and scratch reservation unchanged");
}

static void
test_uncertain_ack_reconciles(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts counts_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 0) == 0,
          "uncertain-ACK fixture reaches submitted RUN");
    mock_set_result(&fixture.mock);
    fixture.mock.status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_DONE |
                          ZN_NC_STATUS_DRAIN_COMPLETE |
                          ZN_NC_STATUS_RESULT_VALID;
    abort_write_mode = ABORT_WRITE_ACK_UNCERTAIN;
    check(zn_native_graph_executor_v1_step(&fixture.executor) < 0 &&
          fixture.executor.terminal && fixture.dispatch.fault &&
          fixture.conv_lifecycle.bridge.driver.state ==
              ZN_NATIVE_CONV_STATE_V2_ACK_UNCERTAIN,
          "real executor records terminal failure after ambiguous hardware ACK");
    owner_before = fixture.owner;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY,
          "ACK reconciliation binds the exact failed executor and command");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED &&
          fixture.conv_lifecycle.bridge.driver.state ==
              ZN_NATIVE_CONV_STATE_V2_IDLE &&
          !zn_native_conv_driver_ownership_held_v2(
              &fixture.conv_lifecycle.bridge.driver) &&
          fixture.hook_state.publish_calls == 0,
          "ACK readback reconciles hardware success without graph publication");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "reconciled ACK retains arena references and scratch reservation");
}

static void
test_uncertain_start_fails_closed(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts counts_before;
    const ZnEvent *event;
    const ZnNativeArenaEventStateV1 *event_state;
    unsigned int reads_before;
    unsigned int writes_before;
    uint8_t index;
    int no_run_io_lease;

    abort_write_mode = ABORT_WRITE_NORMAL;
    abort_write_mode = ABORT_WRITE_START_UNCERTAIN;
    check(abort_fixture_init(&fixture, 0) == 0 &&
          fixture.executor.terminal && fixture.owner.fault &&
          fixture.conv_lifecycle.bridge.driver.state ==
              ZN_NATIVE_CONV_STATE_V2_POISONED &&
          zn_native_conv_driver_ownership_held_v2(
              &fixture.conv_lifecycle.bridge.driver),
          "START write failure is represented as ambiguous and ownership-held");
    owner_before = fixture.owner;
    counts_before = abort_hook_counts(&fixture.hook_state);
    event = &fixture.owner.events[ABORT_FIRST_CONV_INDEX];
    event_state = &fixture.owner.event_state[ABORT_FIRST_CONV_INDEX];
    no_run_io_lease = !event_state->run_started;
    for (index = 0; index < event->read_count; ++index) {
        if (fixture.owner.slots[event->reads[index].slot].io_count != 0)
            no_run_io_lease = 0;
    }
    if (fixture.owner.slots[event->destination.ref.slot].io_count != 0)
        no_run_io_lease = 0;
    reads_before = abort_mmio_read_count;
    writes_before = fixture.mock.write_count;
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY &&
          adapter.state == ZN_NATIVE_GRAPH_ABORT_STATE_V1_FAILED &&
          abort_mmio_read_count == reads_before &&
          fixture.mock.write_count == writes_before && no_run_io_lease &&
          zn_native_conv_driver_ownership_held_v2(
              &fixture.conv_lifecycle.bridge.driver),
          "ambiguous START without owner IO proof is rejected before MMIO");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "uncertain START rejection preserves owner state and scratch lease");
}

static void
test_wrong_result_identity_fails_closed(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts counts_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 0) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "wrong-result fixture starts with an accepted command");
    fixture.mock.result_source_generation_xor = 1;
    mock_set_result(&fixture.mock);
    fixture.mock.status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_DONE |
                          ZN_NC_STATUS_DRAIN_COMPLETE |
                          ZN_NC_STATUS_RESULT_VALID;
    owner_before = fixture.owner;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY,
          "wrong-result adapter remains bound to original command identity");
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_DRIVER && fixture.mock.ack_count == 0 &&
          fixture.conv_lifecycle.bridge.driver.state ==
              ZN_NATIVE_CONV_STATE_V2_IDENTITY_REJECTED &&
          zn_native_conv_driver_ownership_held_v2(
              &fixture.conv_lifecycle.bridge.driver),
          "driver rejects wrong result identity and adapter refuses ACK");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "wrong result identity retains all graph and scratch leases");
}

static void
test_intervening_binding_change_is_rejected(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    unsigned int writes_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 0) == 0 &&
          abort_fixture_timeout(&fixture) == 0 &&
          zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY,
          "identity-change fixture binds a valid terminal RUN");
    writes_before = fixture.mock.write_count;
    ++fixture.executor.binding.dispatch_tag;
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY &&
          fixture.mock.write_count == writes_before &&
          zn_native_conv_driver_ownership_held_v2(
              &fixture.conv_lifecycle.bridge.driver),
          "changed executor binding is rejected before MMIO");
}

static void
test_initial_owner_identity_is_rejected(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    BridgeMmio mock_before;
    AbortHookCounts counts_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 0) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "initial run-tag fixture has terminal submitted work");
    ++fixture.owner.event_state[ABORT_FIRST_CONV_INDEX].run_tag;
    owner_before = fixture.owner;
    mock_before = fixture.mock;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
          ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY &&
          memcmp(&mock_before, &fixture.mock, sizeof mock_before) == 0,
          "stale initial owner run tag rejects before any MMIO");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "run-tag rejection preserves every lease and owner field");

    check(abort_fixture_init(&fixture, 0) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "initial epoch fixture has terminal submitted work");
    ++fixture.owner.epoch;
    ++fixture.dispatch.epoch;
    owner_before = fixture.owner;
    mock_before = fixture.mock;
    counts_before = abort_hook_counts(&fixture.hook_state);
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
          ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY &&
          memcmp(&mock_before, &fixture.mock, sizeof mock_before) == 0,
          "matching owner/dispatch epoch cannot substitute the submitted request epoch");
    abort_check_retained(&fixture, &owner_before, counts_before,
                         "epoch rejection preserves the failed graph and scratch ownership");
}

static void
test_caller_may_stop_before_work(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    unsigned int writes_before;

    abort_write_mode = ABORT_WRITE_NORMAL;
    check(abort_fixture_init(&fixture, 1) == 0 &&
          abort_fixture_timeout(&fixture) == 0,
          "deadline fixture retains a pending START record");
    writes_before = fixture.mock.write_count;
    check(zn_native_graph_abort_v1_init(&adapter, &fixture.executor) ==
              ZN_NATIVE_GRAPH_ABORT_V1_READY &&
          adapter.state == ZN_NATIVE_GRAPH_ABORT_STATE_V1_ARMED &&
          fixture.mock.write_count == writes_before,
          "caller deadline can stop before adapter work without a recovery claim");
}

int
main(void)
{
    int bridge_result = native_graph_abort_embedded_bridge_test_main();
    if (bridge_result != 0)
        ++failures;
    test_preaccept_abort();
    test_same_edge_acceptance_race();
    test_accepted_cancel();
    test_draining_fault();
    test_late_success_is_consumed_without_publish();
    test_uncertain_ack_reconciles();
    test_uncertain_start_fails_closed();
    test_wrong_result_identity_fails_closed();
    test_intervening_binding_change_is_rejected();
    test_initial_owner_identity_is_rejected();
    test_caller_may_stop_before_work();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_GRAPH_ABORT_V1_HOST_FAIL count=%u\n", failures);
        return 1;
    }
    puts("NATIVE_GRAPH_ABORT_V1_HOST_PASS pending_abort=1 accepted_cancel=1 same_edge_race=1 late_success_no_publish=1 drain_fault=1 uncertain_start_retained=1 uncertain_ack_reconciled=1 wrong_result_retained=1 identity_guard=1 initial_owner_identity=1 leases_unchanged=1 caller_deadline=1");
    return 0;
}
