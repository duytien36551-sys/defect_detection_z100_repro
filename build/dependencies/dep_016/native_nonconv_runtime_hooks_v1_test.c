#define main retained_nonconv_lifecycle_test_main
#include "native_arena_nonconv_lifecycle_v1_test.c"
#undef main

#include "native_nonconv_runtime_hooks_v1.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    RUNTIME_ARENA_BYTES = 5201920,
    RUNTIME_HEADS_CACHE_BYTES = ZN_NATIVE_NONCONV_HEADS_CACHE_BYTES_V1,
    CACHE_RECORD_COUNT = 32
};

typedef struct RuntimeCacheProbe {
    ZnNativeNonConvRuntimeHooksV1 *runtime;
    void *invalidated_addresses[CACHE_RECORD_COUNT];
    size_t invalidated_bytes[CACHE_RECORD_COUNT];
    void *cleaned_addresses[CACHE_RECORD_COUNT];
    size_t cleaned_bytes[CACHE_RECORD_COUNT];
    uint16_t clean_event_index[CACHE_RECORD_COUNT];
    uint8_t clean_phase[CACHE_RECORD_COUNT];
    uint32_t invalidate_calls;
    uint32_t clean_calls;
    uint32_t barrier_calls;
    uint8_t fail_invalidate;
    uint8_t fail_clean;
    uint8_t fail_barrier;
} RuntimeCacheProbe;

typedef struct RuntimeHookWrapper {
    ZnNativeNonConvRuntimeHooksV1 runtime;
    ZnNativeArenaNonConvHooksV1 delegates;
    uint8_t source_visible_busy_once;
} RuntimeHookWrapper;

typedef struct RuntimeFixture {
    ZnNativeArenaConfigV1 config;
    ZnNativeArenaOwnerV1 owner;
    ZnDispatch dispatch;
    ZnNativeArenaNonConvLifecycleV1 lifecycle;
    ZnNativeArenaNonConvHooksV1 hooks;
    ZnNativePlatformMemoryOpsV1 cache_ops;
    ZnNativePlatformMappedSpanV1 arena_mapping;
    ZnNativePlatformMappedSpanV1 heads_mapping;
    RuntimeHookWrapper hook_wrapper;
    RuntimeCacheProbe cache;
    const TargetFixture *target;
} RuntimeFixture;

_Alignas(64) static uint8_t runtime_arena[RUNTIME_ARENA_BYTES];
_Alignas(64) static uint8_t runtime_heads[RUNTIME_HEADS_CACHE_BYTES];

static int
runtime_cache_invalidate(void *opaque, void *address, size_t bytes)
{
    RuntimeCacheProbe *probe = opaque;
    uint32_t index;

    if (!probe || !address || bytes == 0)
        return -1;
    index = probe->invalidate_calls++;
    if (index < CACHE_RECORD_COUNT) {
        probe->invalidated_addresses[index] = address;
        probe->invalidated_bytes[index] = bytes;
    }
    return probe->fail_invalidate ? -1 : 0;
}

static int
runtime_cache_clean(void *opaque, void *address, size_t bytes)
{
    RuntimeCacheProbe *probe = opaque;
    uint32_t index;

    if (!probe || !address || bytes == 0)
        return -1;
    index = probe->clean_calls++;
    if (index < CACHE_RECORD_COUNT) {
        probe->cleaned_addresses[index] = address;
        probe->cleaned_bytes[index] = bytes;
        if (probe->runtime && probe->runtime->dispatch) {
            probe->clean_event_index[index] =
                probe->runtime->dispatch->cursor;
            probe->clean_phase[index] = probe->runtime->dispatch->phase;
        }
    }
    return probe->fail_clean ? -1 : 0;
}

static int
runtime_cache_barrier(void *opaque)
{
    RuntimeCacheProbe *probe = opaque;
    if (!probe)
        return -1;
    ++probe->barrier_calls;
    return probe->fail_barrier ? -1 : 0;
}

static int
runtime_source_visible_busy_once(
    void *opaque, const ZnRequest *request, uint8_t read_index,
    const ZnNativeArenaNonConvSourceV1 *source)
{
    RuntimeHookWrapper *wrapper = (RuntimeHookWrapper *)opaque;
    if (!wrapper)
        return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
    if (wrapper->source_visible_busy_once) {
        wrapper->source_visible_busy_once = 0;
        return ZN_NATIVE_ARENA_NONCONV_HOOK_BUSY_V1;
    }
    return wrapper->delegates.source_visible(
        &wrapper->runtime, request, read_index, source);
}

static int
runtime_fixture_init(RuntimeFixture *fixture, uint32_t epoch,
                     uint8_t busy_once)
{
    memset(fixture, 0, sizeof *fixture);
    memset(runtime_arena, 0, sizeof runtime_arena);
    memset(runtime_heads, 0, sizeof runtime_heads);
    fixture->config = make_config();
    fixture->arena_mapping.physical_base = UINT64_C(0x10000000);
    fixture->arena_mapping.bytes = RUNTIME_ARENA_BYTES;
    fixture->arena_mapping.cpu_base = runtime_arena;
    fixture->arena_mapping.cpu_bytes = sizeof runtime_arena;
    fixture->heads_mapping.physical_base = UINT64_C(0x30000000);
    fixture->heads_mapping.bytes = sizeof runtime_heads;
    fixture->heads_mapping.cpu_base = runtime_heads;
    fixture->heads_mapping.cpu_bytes = sizeof runtime_heads;
    fixture->cache_ops.invalidate_readback = runtime_cache_invalidate;
    fixture->cache_ops.cache_clean = runtime_cache_clean;
    fixture->cache_ops.barrier = runtime_cache_barrier;
    if (zn_dispatch_init(&fixture->dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, epoch) != 0 ||
        zn_native_arena_owner_init_v1(&fixture->owner, &fixture->config,
                                      &fixture->dispatch, epoch) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return -1;
    fixture->cache.runtime = &fixture->hook_wrapper.runtime;
    if (zn_native_nonconv_runtime_hooks_init_v1(
            &fixture->hook_wrapper.runtime, &fixture->owner,
            &fixture->dispatch, &fixture->lifecycle,
            &fixture->arena_mapping, &fixture->heads_mapping, 1,
            &fixture->cache_ops, &fixture->cache, &fixture->hooks) != 0)
        return -1;
    if (busy_once) {
        fixture->hook_wrapper.delegates = fixture->hooks;
        fixture->hook_wrapper.source_visible_busy_once = 1;
        fixture->hooks.context = &fixture->hook_wrapper.runtime;
        fixture->hooks.source_visible = runtime_source_visible_busy_once;
    }
    return zn_native_arena_nonconv_lifecycle_init_v1(
               &fixture->lifecycle, &fixture->owner, &fixture->hooks) ==
            ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED ? 0 : -1;
}

static void
runtime_cache_probe_reset(RuntimeCacheProbe *probe)
{
    probe->invalidate_calls = 0;
    probe->clean_calls = 0;
    probe->barrier_calls = 0;
    memset(probe->invalidated_addresses, 0,
           sizeof probe->invalidated_addresses);
    memset(probe->invalidated_bytes, 0, sizeof probe->invalidated_bytes);
    memset(probe->cleaned_addresses, 0, sizeof probe->cleaned_addresses);
    memset(probe->cleaned_bytes, 0, sizeof probe->cleaned_bytes);
    memset(probe->clean_event_index, 0, sizeof probe->clean_event_index);
    memset(probe->clean_phase, 0, sizeof probe->clean_phase);
}

static int
runtime_prepare_target(RuntimeFixture *fixture, const TargetFixture *target)
{
    uint8_t read_index;
    const ZnEvent *event;

    if (!fixture || !target ||
        complete_synthetic_prefix(&fixture->owner, &fixture->dispatch,
                                  target->event_index) != 0 ||
        load_target_fixtures(target) != 0)
        return -1;
    fixture->target = target;
    event = &z100_graph_events[target->event_index];
    if (event->read_count != target->source_count)
        return -1;
    for (read_index = 0; read_index < event->read_count; ++read_index) {
        ZnRef ref = event->reads[read_index];
        ZnNativeArenaSlotV1 *slot;
        size_t offset;
        uint8_t *destination;
        if (ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
            return -1;
        slot = &fixture->owner.slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !ref_equal(slot->ref, ref) || slot->bytes == 0 ||
            packed_bytes(target->sources[read_index].channels,
                         target->sources[read_index].height,
                         target->sources[read_index].width) != slot->bytes ||
            slot->bytes > slot->region.capacity_bytes)
            return -1;
        offset = (size_t)(slot->region.address - UINT32_C(0x10000000));
        if (offset > sizeof runtime_arena ||
            slot->region.capacity_bytes > sizeof runtime_arena - offset)
            return -1;
        destination = runtime_arena + offset;
        memset(destination, 0, slot->region.capacity_bytes);
        memcpy(destination, source_native[read_index], slot->bytes);
        if (runtime_cache_clean(&fixture->cache, destination,
                                slot->region.capacity_bytes) != 0 ||
            runtime_cache_barrier(&fixture->cache) != 0)
            return -1;
    }
    runtime_cache_probe_reset(&fixture->cache);
    return 0;
}

static int
runtime_advance_to_run(RuntimeFixture *fixture, ZnRequest *run_request)
{
    unsigned int attempts = 0;

    if (!fixture || !fixture->target || !run_request)
        return -1;
    while (fixture->dispatch.cursor == fixture->target->event_index) {
        ZnRequest request;
        int next_result = zn_dispatch_next(&fixture->dispatch, &request);
        ZnNativeArenaNonConvLifecycleCodeV1 code;
        if (next_result != 1 || request.event_index != fixture->target->event_index)
            return -1;
        if (request.operation == ZN_RUN) {
            *run_request = request;
            return 0;
        }
        code = zn_native_arena_nonconv_lifecycle_step_v1(
            &fixture->lifecycle, &fixture->dispatch, &request);
        if (code != ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED ||
            ++attempts > 16)
            return -1;
    }
    return -1;
}

static int
runtime_step_until_not_busy(RuntimeFixture *fixture, const ZnRequest *request,
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
runtime_drive_target(RuntimeFixture *fixture, uint8_t inspect_return)
{
    uint8_t inspected = 0;
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
        if (next_result != 1)
            return -1;
        if (request.event_index != fixture->target->event_index)
            break;
        if (inspect_return && !inspected && request.operation == ZN_RETURN) {
            uint8_t index = fixture->dispatch.index;
            uint8_t before = fixture->owner.event_state[
                request.event_index].returned_mask;
            int hook_result = fixture->hooks.return_graph_read(
                fixture->hooks.context, &request, index,
                fixture->owner.slots[request.ref.slot].region.address,
                request.ref);
            check(hook_result == ZN_NATIVE_ARENA_NONCONV_HOOK_READY_V1 &&
                  fixture->owner.event_state[request.event_index].returned_mask ==
                      before && fixture->dispatch.pending,
                  "RETURN callback validates the lease without ACKing or mutating owner state");
            inspected = 1;
        }
        if (runtime_step_until_not_busy(fixture, &request, &code) != 0 ||
            code != ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED)
            return -1;
    }
    return fixture->dispatch.cursor == fixture->target->event_index + 1u &&
           (!inspect_return || inspected) ? 0 : -1;
}

static uint8_t *
runtime_target_output(RuntimeFixture *fixture)
{
    const ZnEvent *event;
    if (!fixture || !fixture->target)
        return NULL;
    event = &z100_graph_events[fixture->target->event_index];
    if (!event->has_destination)
        return runtime_heads;
    if (event->destination.address < UINT32_C(0x10000000))
        return NULL;
    return runtime_arena +
        (size_t)(event->destination.address - UINT32_C(0x10000000));
}

static int
runtime_save_and_compare_output(RuntimeFixture *fixture)
{
    const TargetFixture *target = fixture->target;
    const uint8_t *output;
    const uint8_t *expected;

    if (!target)
        return -1;
    if (target->destinationless) {
        size_t logical_bytes = 0;
        if (zn_native_nonconv_runtime_heads_result_v1(
                &fixture->hook_wrapper.runtime, &output, &logical_bytes) != 0 ||
            logical_bytes != target->output_bytes)
            return -1;
    } else {
        output = runtime_target_output(fixture);
        if (!output)
            return -1;
    }
    expected = target->destinationless ? expected_nchw : expected_native;
    check(memcmp(output, expected, target->output_bytes) == 0,
          "runtime callback output matches the captured native assertion");
    check(write_actual_output(target->event_id, output,
                              target->output_bytes) == 0,
          "runtime callback output artifact is written for SHA validation");
    printf("NATIVE_NONCONV_RUNTIME_OUTPUT_PASS event=%u bytes=%zu fnv64=%016" PRIx64 " output_published=%u\n",
           target->event_id, target->output_bytes,
           fnv64(output, target->output_bytes),
           target->destinationless ? 0u : 1u);
    return 0;
}

static int
runtime_test_sequential_events_and_retries(void)
{
    RuntimeFixture fixture;
    ZnRequest request;
    ZnRequest done_request;
    ZnNativeArenaNonConvLifecycleCodeV1 code;
    const ZnEvent *add_event = &z100_graph_events[ADD_EVENT_INDEX];
    uint8_t *add_output;
    uint8_t read_index;
    ZnRequest stale_request;

    if (runtime_fixture_init(&fixture, 701, 1) != 0 ||
        runtime_prepare_target(&fixture, &targets[0]) != 0 ||
        runtime_advance_to_run(&fixture, &request) != 0) {
        check(0, "runtime ADD fixture initializes and reaches its exact RUN");
        return -1;
    }
    check(request.event_index == ADD_EVENT_INDEX && request.job->event == 12,
          "runtime ADD starts on event 12");
    code = zn_native_arena_nonconv_lifecycle_step_v1(
        &fixture.lifecycle, &fixture.dispatch, &request);
    check(code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY &&
          fixture.lifecycle.operator_call_count == 0 &&
          fixture.cache.invalidate_calls == 0,
          "test-only one-shot source visibility wrapper yields BUSY before cache invalidation");
    stale_request = request;
    ++stale_request.epoch;
    check(fixture.hooks.source_visible(
              fixture.hooks.context, &stale_request, 0,
              &fixture.lifecycle.sources[0]) ==
              ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1 &&
          fixture.dispatch.pending && !fixture.owner.fault,
          "stale epoch is rejected without changing the exact pending RUN");
    {
        int step_result = runtime_step_until_not_busy(&fixture, &request, &code);
        check(step_result == 0 &&
          code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED &&
          fixture.lifecycle.operator_call_count == 1,
          "source BUSY retry computes ADD once and publishes only after cache clean");
    }
    check(fixture.cache.invalidate_calls == add_event->read_count &&
          fixture.cache.clean_calls == 1 && fixture.cache.barrier_calls == 3,
          "ADD invalidates each source capacity and cleans the destination capacity");
    for (read_index = 0; read_index < add_event->read_count; ++read_index) {
        const ZnNativeArenaSlotV1 *slot =
            &fixture.owner.slots[add_event->reads[read_index].slot];
        size_t offset = slot->region.address - UINT32_C(0x10000000);
        check(fixture.cache.invalidated_addresses[read_index] ==
                  runtime_arena + offset &&
              fixture.cache.invalidated_bytes[read_index] ==
                  slot->region.capacity_bytes,
              "source invalidation uses the full owned slot capacity");
    }
    add_output = runtime_target_output(&fixture);
    check(add_output &&
          fixture.cache.cleaned_addresses[0] == add_output &&
          fixture.cache.cleaned_bytes[0] ==
              fixture.owner.slots[add_event->destination.ref.slot].region.capacity_bytes,
          "destination cleaning uses the full owned slot capacity");
    {
        int drive_result = runtime_drive_target(&fixture, 1);
        check(drive_result == 0 &&
          fixture.owner.event_state[ADD_EVENT_INDEX].returned_mask == 3 &&
          fixture.lifecycle.operator_call_count == 1,
          "ADD DRAIN, non-ACKing callback RETURNs, and RETIRE complete");
    }
    runtime_save_and_compare_output(&fixture);

    if (runtime_prepare_target(&fixture, &targets[1]) != 0 ||
        runtime_advance_to_run(&fixture, &request) != 0 ||
        runtime_step_until_not_busy(&fixture, &request, &code) != 0 ||
        code != ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED ||
        fixture.lifecycle.operator_call_count != 2 ||
        runtime_drive_target(&fixture, 0) != 0) {
        check(0, "runtime POOL follows ADD in the same owner and lifecycle");
        return -1;
    }
    check(request.event_index == POOL_EVENT_INDEX && request.job->event == 70 &&
          fixture.lifecycle.operator_call_count == 2,
          "POOL gets its own RUN baseline while call count remains cumulative");
    check(fixture.cache.invalidate_calls == 1 && fixture.cache.clean_calls == 1 &&
          fixture.cache.cleaned_bytes[0] == fixture.owner.slots[
              request.job->destination.ref.slot].region.capacity_bytes,
          "POOL uses its source and destination slot capacities");
    runtime_save_and_compare_output(&fixture);

    if (runtime_prepare_target(&fixture, &targets[2]) != 0 ||
        runtime_advance_to_run(&fixture, &request) != 0 ||
        runtime_step_until_not_busy(&fixture, &request, &code) != 0 ||
        code != ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED ||
        fixture.lifecycle.operator_call_count != 3 ||
        runtime_drive_target(&fixture, 0) != 0) {
        check(0, "runtime HEADS follows POOL in the same owner and lifecycle");
        return -1;
    }
    check(request.event_index == HEADS_EVENT_INDEX && request.job->event == 163 &&
          !request.job->has_destination && fixture.lifecycle.operator_call_count == 3,
          "HEADS retains physical address zero and the cumulative call count is three");
    check(!fixture.owner.event_state[HEADS_EVENT_INDEX].output_published &&
          fixture.owner.event_state[HEADS_EVENT_INDEX].drained &&
          fixture.cache.clean_calls == 1 &&
          fixture.cache.cleaned_addresses[0] == runtime_heads &&
          fixture.cache.cleaned_bytes[0] == RUNTIME_HEADS_CACHE_BYTES &&
          fixture.cache.clean_event_index[0] == HEADS_EVENT_INDEX &&
          fixture.cache.clean_phase[0] == ZN_DRAIN,
          "HEADS cleans its separate aligned cache span only during completed DRAIN");
    check(runtime_drive_target(&fixture, 0) == 0,
          "HEADS ordered read returns and retirements complete");
    {
        const uint8_t *sentinel = expected_nchw;
        const uint8_t *heads_result = sentinel;
        size_t logical_bytes = 77;
        check(zn_native_nonconv_runtime_heads_result_v1(
                  &fixture.hook_wrapper.runtime, &heads_result,
                  &logical_bytes) != 0 &&
              heads_result == sentinel &&
              logical_bytes == 77,
              "HEADS bytes stay unavailable before final dispatcher and owner completion");
        check(zn_dispatch_next(&fixture.dispatch, &done_request) == 0 &&
              fixture.dispatch.done &&
              zn_native_arena_owner_verify_complete_v1(
                  &fixture.owner, &fixture.dispatch) ==
                  ZN_NATIVE_ARENA_OWNER_V1_ACKED,
              "final dispatcher and owner completion are independently verified");
        {
            uint32_t saved_dispatch_epoch = fixture.dispatch.epoch;
            uint32_t saved_run_tag =
                fixture.owner.event_state[HEADS_EVENT_INDEX].run_tag;
            uint8_t saved_returned_mask =
                fixture.owner.event_state[HEADS_EVENT_INDEX].returned_mask;

            fixture.dispatch.epoch = saved_dispatch_epoch + 1u;
            heads_result = sentinel;
            logical_bytes = 77;
            check(zn_native_nonconv_runtime_heads_result_v1(
                      &fixture.hook_wrapper.runtime, &heads_result,
                      &logical_bytes) != 0 && heads_result == sentinel &&
                  logical_bytes == 77,
                  "HEADS remains unavailable when completed dispatcher epoch differs from owner epoch");
            fixture.dispatch.epoch = saved_dispatch_epoch;

            fixture.owner.event_state[HEADS_EVENT_INDEX].run_tag =
                saved_run_tag + 1u;
            heads_result = sentinel;
            logical_bytes = 77;
            check(zn_native_nonconv_runtime_heads_result_v1(
                      &fixture.hook_wrapper.runtime, &heads_result,
                      &logical_bytes) != 0 && heads_result == sentinel &&
                  logical_bytes == 77,
                  "HEADS remains unavailable when completed event RUN tag changes");
            fixture.owner.event_state[HEADS_EVENT_INDEX].run_tag = saved_run_tag;

            fixture.owner.event_state[HEADS_EVENT_INDEX].returned_mask =
                (uint8_t)(saved_returned_mask & (uint8_t)~UINT8_C(1));
            heads_result = sentinel;
            logical_bytes = 77;
            check(zn_native_nonconv_runtime_heads_result_v1(
                      &fixture.hook_wrapper.runtime, &heads_result,
                      &logical_bytes) != 0 && heads_result == sentinel &&
                  logical_bytes == 77,
                  "HEADS remains unavailable when a final graph read return is missing");
            fixture.owner.event_state[HEADS_EVENT_INDEX].returned_mask =
                saved_returned_mask;
        }
        heads_result = sentinel;
        logical_bytes = 77;
        check(zn_native_nonconv_runtime_heads_result_v1(
                  &fixture.hook_wrapper.runtime, &heads_result,
                  &logical_bytes) == 0 && heads_result == runtime_heads &&
              logical_bytes == ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1,
              "HEADS exposes exactly 613200 bytes after final completion");
    }
    runtime_save_and_compare_output(&fixture);
    check(fixture.dispatch.cursor == HEADS_EVENT_INDEX + 1u &&
          fixture.lifecycle.operator_call_count == 3,
          "sequential non-conv lifecycle completes three RUNs without resetting cumulative calls");
    return 0;
}

static int
runtime_failure_fixture(RuntimeFixture *fixture, uint32_t epoch,
                        uint8_t fail_invalidate, uint8_t fail_clean,
                        uint8_t fail_barrier)
{
    ZnRequest request;
    if (runtime_fixture_init(fixture, epoch, 0) != 0 ||
        runtime_prepare_target(fixture, &targets[0]) != 0 ||
        runtime_advance_to_run(fixture, &request) != 0)
        return -1;
    fixture->cache.fail_invalidate = fail_invalidate;
    fixture->cache.fail_clean = fail_clean;
    fixture->cache.fail_barrier = fail_barrier;
    return zn_native_arena_nonconv_lifecycle_step_v1(
               &fixture->lifecycle, &fixture->dispatch, &request) ==
            ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_FAILED ? 0 : -1;
}

static int
runtime_test_cache_failures_and_heads_bounds(void)
{
    RuntimeFixture fixture;
    ZnNativeNonConvRuntimeHooksV1 rejected_runtime;
    ZnNativeArenaNonConvHooksV1 rejected_hooks;
    ZnNativePlatformMappedSpanV1 bad_heads;
    const ZnEvent *event = &z100_graph_events[ADD_EVENT_INDEX];
    ZnNativeArenaSlotV1 *destination;

    if (runtime_fixture_init(&fixture, 704, 0) != 0) {
        check(0, "runtime invalid HEADS fixture initializes");
        return -1;
    }
    bad_heads = fixture.heads_mapping;
    bad_heads.cpu_base = fixture.arena_mapping.cpu_base + 4096;
    check(zn_native_nonconv_runtime_hooks_init_v1(
              &rejected_runtime, &fixture.owner, &fixture.dispatch,
              &fixture.lifecycle, &fixture.arena_mapping, &bad_heads, 1,
              &fixture.cache_ops, &fixture.cache, &rejected_hooks) != 0,
          "HEADS CPU alias with the arena is rejected");
    bad_heads = fixture.heads_mapping;
    bad_heads.physical_base = fixture.arena_mapping.physical_base + 64;
    check(zn_native_nonconv_runtime_hooks_init_v1(
              &rejected_runtime, &fixture.owner, &fixture.dispatch,
              &fixture.lifecycle, &fixture.arena_mapping, &bad_heads, 1,
              &fixture.cache_ops, &fixture.cache, &rejected_hooks) != 0,
          "HEADS physical alias with the arena is rejected");
    bad_heads = fixture.heads_mapping;
    bad_heads.bytes = ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1;
    bad_heads.cpu_bytes = ZN_NATIVE_ARENA_NONCONV_HEADS_BYTES_V1;
    check(zn_native_nonconv_runtime_hooks_init_v1(
              &rejected_runtime, &fixture.owner, &fixture.dispatch,
              &fixture.lifecycle, &fixture.arena_mapping, &bad_heads, 1,
              &fixture.cache_ops, &fixture.cache, &rejected_hooks) != 0,
          "HEADS cache mapping shorter than 613248 bytes is rejected");
    bad_heads = fixture.heads_mapping;
    bad_heads.physical_base += 1;
    check(zn_native_nonconv_runtime_hooks_init_v1(
              &rejected_runtime, &fixture.owner, &fixture.dispatch,
              &fixture.lifecycle, &fixture.arena_mapping, &bad_heads, 1,
              &fixture.cache_ops, &fixture.cache, &rejected_hooks) != 0,
          "unaligned HEADS physical mapping is rejected");

    check(runtime_failure_fixture(&fixture, 702, 1, 0, 0) == 0 &&
          fixture.lifecycle.operator_call_count == 0 && fixture.owner.fault &&
          fixture.dispatch.fault &&
          fixture.owner.slots[event->reads[0].slot].reader_count != 0 &&
          fixture.owner.slots[event->destination.ref.slot].state ==
              ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
          fixture.owner.slots[event->destination.ref.slot].io_count == 0 &&
          !fixture.owner.event_state[ADD_EVENT_INDEX].output_published,
          "failed source invalidation prevents compute and preserves acquired leases");

    check(runtime_failure_fixture(&fixture, 703, 0, 0, 1) == 0 &&
          fixture.lifecycle.operator_call_count == 0 && fixture.owner.fault &&
          fixture.dispatch.fault && fixture.cache.invalidate_calls == 1 &&
          fixture.cache.barrier_calls == 1 &&
          fixture.owner.slots[event->reads[0].slot].reader_count != 0 &&
          fixture.owner.slots[event->destination.ref.slot].state ==
              ZN_NATIVE_ARENA_SLOT_RESERVED_V1,
          "failed visibility barrier prevents compute and preserves leases");

    check(runtime_failure_fixture(&fixture, 705, 0, 1, 0) == 0 &&
          fixture.lifecycle.operator_call_count == 1 && fixture.owner.fault &&
          fixture.dispatch.fault &&
          fixture.lifecycle.computed &&
          !fixture.owner.event_state[ADD_EVENT_INDEX].output_published,
          "failed output cleaning keeps completed ADD unpublished");
    destination = &fixture.owner.slots[event->destination.ref.slot];
    check(destination->state == ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
          destination->io_count != 0 &&
          fixture.owner.slots[event->reads[0].slot].reader_count != 0,
          "failed output cleaning retains destination IO and input reader leases");
    return 0;
}

int
main(int argc, char **argv)
{
    if (argc != 2 || !argv[1] || argv[1][0] == '\0') {
        fprintf(stderr,
                "usage: native_nonconv_runtime_hooks_v1_test <output-dir>\n");
        return 2;
    }
    actual_output_dir = argv[1];
    runtime_test_sequential_events_and_retries();
    runtime_test_cache_failures_and_heads_bounds();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_NONCONV_RUNTIME_HOOKS_HOST_FAIL count=%u\n",
                failures);
        return 1;
    }
    printf("NATIVE_NONCONV_RUNTIME_HOOKS_HOST_PASS events=3 operator_calls=3 sequential_runs=1 source_capacity_invalidation=1 destination_capacity_clean=1 heads_drain_clean=1 heads_final_completion_gate=1 heads_epoch_gate=1 heads_run_tag_gate=1 heads_return_mask_gate=1 one_shot_busy=1 stale_epoch=1 alias_rejection=1 bounds_rejection=1 barrier_failure=1 lease_preservation=1 ordered_return=1 physical_arena_claim=0\n");
    return 0;
}
