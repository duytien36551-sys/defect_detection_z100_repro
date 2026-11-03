static int
abort_owner_mutation_prepare(AbortFixture *fixture,
                             ZnNativeGraphAbortV1 *adapter)
{
    abort_write_mode = ABORT_WRITE_NORMAL;
    if (abort_fixture_init(fixture, 1) != 0) {
        check(0, "owner-mutation fixture initializes");
        return 0;
    }
    if (abort_fixture_timeout(fixture) != 0) {
        check(0, "owner-mutation fixture reaches a terminal submitted RUN");
        return 0;
    }
    if (zn_native_graph_abort_v1_init(adapter, &fixture->executor) !=
        ZN_NATIVE_GRAPH_ABORT_V1_READY) {
        check(0, "abort adapter binds the valid submitted RUN");
        return 0;
    }
    return 1;
}

static void
test_owner_epoch_mutation_after_bind(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    BridgeMmio mock_before;
    AbortHookCounts hooks_before;
    unsigned int reads_before;

    if (!abort_owner_mutation_prepare(&fixture, &adapter))
        return;

    ++fixture.owner.epoch;
    ++fixture.dispatch.epoch;
    memcpy(&owner_before, &fixture.owner, sizeof owner_before);
    mock_before = fixture.mock;
    hooks_before = abort_hook_counts(&fixture.hook_state);
    reads_before = abort_mmio_read_count;
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY &&
          adapter.state == ZN_NATIVE_GRAPH_ABORT_STATE_V1_FAILED &&
          abort_mmio_read_count == reads_before &&
          memcmp(&mock_before, &fixture.mock, sizeof mock_before) == 0 &&
          memcmp(&owner_before, &fixture.owner, sizeof owner_before) == 0,
          "post-bind owner and dispatcher epoch mutation rejects before MMIO");
    abort_check_retained(&fixture, &owner_before, hooks_before,
                         "epoch rejection preserves the changed owner and all leases");
}

static void
test_owner_run_tag_mutation_after_bind(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    BridgeMmio mock_before;
    AbortHookCounts hooks_before;
    unsigned int reads_before;

    if (!abort_owner_mutation_prepare(&fixture, &adapter))
        return;

    ++fixture.owner.event_state[ABORT_FIRST_CONV_INDEX].run_tag;
    memcpy(&owner_before, &fixture.owner, sizeof owner_before);
    mock_before = fixture.mock;
    hooks_before = abort_hook_counts(&fixture.hook_state);
    reads_before = abort_mmio_read_count;
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY &&
          adapter.state == ZN_NATIVE_GRAPH_ABORT_STATE_V1_FAILED &&
          abort_mmio_read_count == reads_before &&
          memcmp(&mock_before, &fixture.mock, sizeof mock_before) == 0 &&
          memcmp(&owner_before, &fixture.owner, sizeof owner_before) == 0,
          "post-bind owner run-tag mutation rejects before MMIO");
    abort_check_retained(&fixture, &owner_before, hooks_before,
                         "run-tag rejection preserves the changed owner and all leases");
}

static void
test_unchanged_owner_control(void)
{
    AbortFixture fixture;
    ZnNativeGraphAbortV1 adapter;
    ZnNativeArenaOwnerV1 owner_before;
    AbortHookCounts hooks_before;
    unsigned int reads_before;

    if (!abort_owner_mutation_prepare(&fixture, &adapter))
        return;

    memcpy(&owner_before, &fixture.owner, sizeof owner_before);
    hooks_before = abort_hook_counts(&fixture.hook_state);
    reads_before = abort_mmio_read_count;
    check(zn_native_graph_abort_v1_step(&adapter) ==
              ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS &&
          fixture.mock.abort_count == 1 && fixture.mock.cancel_count == 0 &&
          fixture.mock.ack_count == 0 && abort_mmio_read_count > reads_before &&
          memcmp(&owner_before, &fixture.owner, sizeof owner_before) == 0,
          "unchanged submitted RUN follows the valid bounded abort path");
    abort_check_retained(&fixture, &owner_before, hooks_before,
                         "valid control path retains graph and scratch leases");
}

int
main(void)
{
    test_owner_epoch_mutation_after_bind();
    test_owner_run_tag_mutation_after_bind();
    test_unchanged_owner_control();
    if (failures != 0) {
        fprintf(stderr,
                "NATIVE_GRAPH_ABORT_OWNER_MUTATION_V1_HOST_FAIL count=%u\n",
                failures);
        return 1;
    }
    puts("NATIVE_GRAPH_ABORT_OWNER_MUTATION_V1_HOST_PASS "
         "epoch_after_init=1 run_tag_after_init=1 valid_control=1 "
         "no_mutation_mmio=1 owner_leases_unchanged=1 "
         "cache_hooks_unchanged=1");
    return 0;
}
