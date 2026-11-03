/* The validator emits an exact hash-bound copy of the existing executor test,
 * renaming only its main. Its real production dependencies are linked below. */
#include "native_graph_executor_poller_fixture.h"
#include "native_graph_poller_v1.h"

typedef struct PollerClock {
    uint64_t now;
    uint64_t increment;
    uint64_t jump_value;
    unsigned int calls;
    unsigned int fail_at;
    unsigned int jump_at;
} PollerClock;

static int poller_ticks(void *context, uint64_t *out)
{
    PollerClock *clock = context;
    ++clock->calls;
    if (clock->fail_at && clock->calls == clock->fail_at)
        return -1;
    if (clock->jump_at && clock->calls == clock->jump_at)
        clock->now = clock->jump_value;
    *out = clock->now;
    clock->now += clock->increment;
    return 0;
}

static void poller_init_fixture(ExecutorFixture *fixture,
    ZnNativeGraphPollerV1 *poller, PollerClock *clock, uint32_t epoch,
    uint64_t budget)
{
    memset(poller, 0, sizeof *poller);
    memset(clock, 0, sizeof *clock);
    clock->now = UINT64_C(100000);
    check(executor_fixture_init(fixture, epoch) == 0,
          "poller fixture uses initialized real executor");
    check(zn_native_graph_poller_init_v1(poller, &fixture->executor,
        poller_ticks, clock, UINT64_C(333333333), budget) ==
        ZN_NATIVE_GRAPH_POLLER_V1_YIELDED, "poller initialized once");
}

static ZnNativeGraphPollerCodeV1 poller_poll_fixture(
    ExecutorFixture *fixture, ZnNativeGraphPollerV1 *poller, uint32_t steps)
{
    ZnNativeGraphPollerCodeV1 code =
        zn_native_graph_poller_poll_v1(poller, steps);
    if (fixture->conv.hooks.leases_code == 1)
        fixture->conv.hooks.leases_code = 0;
    return code;
}

static void test_poller_mixed_and_complete(void)
{
    static ExecutorFixture fixture;
    ZnNativeGraphPollerV1 poller;
    PollerClock clock;
    unsigned int tries;
    uint64_t before;
    poller_init_fixture(&fixture, &poller, &clock, 310, 100000);
    clock.increment = 1;
    for (tries = 0; tries < 256; ++tries) {
        before = poller.executor_calls;
        check(poller_poll_fixture(&fixture, &poller, 1) ==
            ZN_NATIVE_GRAPH_POLLER_V1_YIELDED,
            "mixed poller yields after bounded real executor work");
        check(poller.executor_calls == before + 1,
              "single-step slice never executes extra work");
        if (fixture.conv.dispatch.cursor > EXECUTOR_SECOND_CONV_INDEX)
            break;
    }
    check(tries < 256 && fixture.resolver_calls == 2 &&
          fixture.conv.mock.start_count == 2 &&
          fixture.nonconv.lifecycle.operator_call_count == 1 &&
          poller.scratch_releases == 2 && poller.busy_calls > 0 &&
          poller.acked_calls > 0 && poller.elapsed_ticks > 0,
          "poller tracks actual Conv ADD Conv progress and release counts");
    check(executor_complete_synthetic_prefix(&fixture.conv.owner,
        &fixture.conv.dispatch, ZN_NATIVE_ARENA_EVENT_COUNT_V1) == 0,
        "remaining synthetic control flow explicitly labelled");
    check(zn_native_graph_poller_poll_v1(&poller, 64) ==
          ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE && fixture.executor.complete &&
          fixture.conv.owner.complete && !fixture.conv.owner.fault,
          "completion requires actual executor terminal owner verification");
    before = clock.calls;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE && clock.calls == before,
          "terminal completion performs no more clock or executor callbacks");
}

static void test_poller_bounded_busy(void)
{
    static ExecutorFixture fixture;
    ZnNativeGraphPollerV1 poller;
    PollerClock clock;
    uint64_t before;
    unsigned int tries;
    poller_init_fixture(&fixture, &poller, &clock, 311, 100000);
    fixture.resolver_busy_remaining = 255;
    for (tries = 0; tries < 16; ++tries) {
        check(poller_poll_fixture(&fixture, &poller, 1) ==
            ZN_NATIVE_GRAPH_POLLER_V1_YIELDED, "resolver wait yields");
        if (fixture.executor.pending_valid &&
            fixture.executor.pending_request.operation == ZN_RUN)
            break;
    }
    check(tries < 16, "bounded BUSY fixture reaches pending RUN");
    before = poller.executor_calls;
    check(zn_native_graph_poller_poll_v1(&poller, 64) ==
          ZN_NATIVE_GRAPH_POLLER_V1_YIELDED &&
          poller.executor_calls == before + 64 &&
          fixture.conv.mock.start_count == 0 && fixture.conv.dispatch.pending,
          "64-step upper bound yields during persistent resolver BUSY");
    before = poller.executor_calls;
    check(zn_native_graph_poller_poll_v1(&poller, 0) ==
          ZN_NATIVE_GRAPH_POLLER_V1_ARGUMENT &&
          zn_native_graph_poller_poll_v1(&poller, 65) ==
          ZN_NATIVE_GRAPH_POLLER_V1_ARGUMENT &&
          poller.executor_calls == before && !poller.terminal,
          "invalid slice sizes do not fault or advance graph state");
}

static void test_poller_accepted_deadline(void)
{
    static ExecutorFixture fixture;
    static ZnNativeArenaSlotV1 slots[ZN_NATIVE_ARENA_SLOT_COUNT_V1];
    static ZnNativeArenaEventStateV1 events[ZN_NATIVE_ARENA_EVENT_COUNT_V1];
    ZnNativeGraphPollerV1 poller;
    PollerClock clock;
    ZnNativeConvDriverV2 driver;
    BridgeMmio mock;
    uint64_t before;
    unsigned int tries;
    poller_init_fixture(&fixture, &poller, &clock, 312, 100);
    for (tries = 0; tries < 32; ++tries) {
        check(poller_poll_fixture(&fixture, &poller, 1) ==
            ZN_NATIVE_GRAPH_POLLER_V1_YIELDED, "accepted fixture yields");
        if (fixture.conv.mock.start_count)
            break;
    }
    check(tries < 32 && zn_native_conv_driver_ownership_held_v2(
        &fixture.conv.lifecycle.bridge.driver), "real V2 driver owns accepted work");
    memcpy(slots, fixture.conv.owner.slots, sizeof slots);
    memcpy(events, fixture.conv.owner.event_state, sizeof events);
    driver = fixture.conv.lifecycle.bridge.driver;
    mock = fixture.conv.mock;
    before = poller.executor_calls;
    clock.now = poller.start_ticks + poller.budget_ticks;
    check(zn_native_graph_poller_poll_v1(&poller, 64) ==
          ZN_NATIVE_GRAPH_POLLER_V1_TIMED_OUT && poller.executor_calls == before &&
          fixture.executor.terminal && fixture.conv.owner.fault &&
          fixture.conv.dispatch.fault,
          "deadline at exact boundary faults before another executor call");
    check(memcmp(slots, fixture.conv.owner.slots, sizeof slots) == 0 &&
          memcmp(events, fixture.conv.owner.event_state, sizeof events) == 0 &&
          memcmp(&driver, &fixture.conv.lifecycle.bridge.driver, sizeof driver) == 0 &&
          memcmp(&mock, &fixture.conv.mock, sizeof mock) == 0 &&
          fixture.conv.hooks.publish_calls == 0 &&
          fixture.conv.hooks.release_calls == 0,
          "timeout preserves graph leases driver and MMIO without publication or release");
    before = clock.calls;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_TIMED_OUT && clock.calls == before,
          "timeout is sticky and cannot resume work");
}

static void test_poller_clock_and_identity(void)
{
    static ExecutorFixture fixture;
    static ZnNativeArenaOwnerV1 replacement;
    ZnNativeGraphPollerV1 poller;
    PollerClock clock;
    poller_init_fixture(&fixture, &poller, &clock, 313, 100);
    clock.fail_at = clock.calls + 1;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_CLOCK_FAILED && poller.executor_calls == 0 &&
          fixture.conv.owner.fault && fixture.conv.mock.write_count == 0,
          "clock failure terminates without executor or device activity");
    poller_init_fixture(&fixture, &poller, &clock, 314, 100);
    --clock.now;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_CLOCK_FAILED && poller.executor_calls == 0,
          "clock rollback rejected instead of unsigned timing wrap");
    poller_init_fixture(&fixture, &poller, &clock, 315, 100);
    ++fixture.conv.dispatch.epoch;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_IDENTITY && clock.calls == 1 &&
          poller.executor_calls == 0 && fixture.conv.owner.fault,
          "frame epoch substitution rejected before clock or hardware calls");
    poller_init_fixture(&fixture, &poller, &clock, 316, 100);
    memset(&replacement, 0, sizeof replacement);
    fixture.executor.owner = &replacement;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_IDENTITY && fixture.conv.owner.fault &&
          !replacement.fault && fixture.conv.mock.write_count == 0,
          "identity rejection faults original owner without following replacement");
}

static void test_poller_complete_late_and_failures(void)
{
    static ExecutorFixture fixture;
    ZnNativeGraphPollerV1 poller;
    ZnNativeGraphPollerV1 saved;
    PollerClock clock;
    unsigned int tries;
    poller_init_fixture(&fixture, &poller, &clock, 317, 100);
    check(executor_complete_synthetic_prefix(&fixture.conv.owner,
        &fixture.conv.dispatch, ZN_NATIVE_ARENA_EVENT_COUNT_V1) == 0,
        "late completion uses explicitly synthetic complete control ledger");
    clock.jump_at = clock.calls + 2;
    clock.jump_value = poller.start_ticks + poller.budget_ticks;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE_LATE && fixture.executor.complete &&
          fixture.conv.owner.complete && !fixture.conv.owner.fault,
          "late verified completion is separate from within-budget completion");

    poller_init_fixture(&fixture, &poller, &clock, 318, 100);
    fixture.resolver_busy_remaining = 8;
    for (tries = 0; tries < 16; ++tries) {
        (void)poller_poll_fixture(&fixture, &poller, 1);
        if (fixture.executor.pending_valid &&
            fixture.executor.pending_request.operation == ZN_RUN)
            break;
    }
    ++fixture.conv.dispatch.request.tag;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_EXECUTOR_FAILED &&
          poller.last_executor_code == ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST &&
          fixture.conv.owner.fault,
          "executor identity failure is preserved as terminal failure");

    poller_init_fixture(&fixture, &poller, &clock, 319, 100);
    saved = poller;
    check(zn_native_graph_poller_init_v1(&poller, &fixture.executor,
        poller_ticks, &clock, 1, 100) == ZN_NATIVE_GRAPH_POLLER_V1_ARGUMENT &&
        memcmp(&saved, &poller, sizeof saved) == 0,
        "reinitialization cannot reset an existing frame deadline");
    poller.executor = NULL;
    check(zn_native_graph_poller_poll_v1(&poller, 1) ==
          ZN_NATIVE_GRAPH_POLLER_V1_ARGUMENT && !fixture.conv.owner.fault,
          "invalid null internal reference is rejected without a dereference");
    memset(&poller, 0, sizeof poller);
    check(zn_native_graph_poller_init_v1(&poller, &fixture.executor,
        poller_ticks, &clock, 0, 100) == ZN_NATIVE_GRAPH_POLLER_V1_ARGUMENT &&
        poller.magic == 0 && !fixture.conv.owner.fault,
        "zero timer frequency rejected without admitting or faulting graph");
    clock.fail_at = clock.calls + 1;
    check(zn_native_graph_poller_init_v1(&poller, &fixture.executor,
        poller_ticks, &clock, 1, 100) == ZN_NATIVE_GRAPH_POLLER_V1_CLOCK_FAILED &&
        poller.magic == 0 && !fixture.conv.owner.fault,
        "failed initialization clock leaves poller and graph unadmitted");
}

int main(void)
{
    (void)native_graph_executor_poller_fixture_main();
    test_poller_mixed_and_complete();
    test_poller_bounded_busy();
    test_poller_accepted_deadline();
    test_poller_clock_and_identity();
    test_poller_complete_late_and_failures();
    if (failures) {
        fprintf(stderr, "NATIVE_GRAPH_POLLER_V1_HOST_FAIL count=%u\n", failures);
        return 1;
    }
    puts("NATIVE_GRAPH_POLLER_V1_HOST_PASS bounded_slices=1 mixed_real_lifecycles=1 deadline_exact=1 accepted_leases_retained=1 clock_failure=1 clock_rollback=1 epoch_rejection=1 pointer_rejection=1 null_state_rejected=1 complete_late=1 executor_failure=1 reinit_rejected=1 physical_graph_claim=0");
    return 0;
}
