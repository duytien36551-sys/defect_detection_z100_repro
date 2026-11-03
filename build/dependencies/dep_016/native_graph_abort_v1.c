#include "native_graph_abort_v1.h"

#include <string.h>

static int
zn_nga_ref_equal_v1(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
zn_nga_request_equal_v1(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index &&
           a->operation == b->operation && zn_nga_ref_equal_v1(a->ref, b->ref) &&
           a->job == b->job;
}

static int
zn_nga_command_equal_v1(const ZnNativeConvCommand *a,
                        const ZnNativeConvCommand *b)
{
    uint32_t words_a[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t words_b[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];

    return a && b &&
           zn_native_conv_command_encode_v1(a, words_a) ==
               ZN_NATIVE_CONV_COMMAND_OK &&
           zn_native_conv_command_encode_v1(b, words_b) ==
               ZN_NATIVE_CONV_COMMAND_OK &&
           memcmp(words_a, words_b, sizeof words_a) == 0;
}

static int
zn_nga_binding_equal_v1(const ZnNativeGraphConvBindingV2 *a,
                        const ZnNativeGraphConvBindingV2 *b)
{
    uint8_t index;

    if (!a || !b || a->dispatch_epoch != b->dispatch_epoch ||
        a->dispatch_tag != b->dispatch_tag || a->event_index != b->event_index ||
        a->graph_read_count != b->graph_read_count ||
        a->graph_read_count > ZN_NATIVE_GRAPH_CONV_MAX_READS_V2 ||
        !zn_nga_ref_equal_v1(a->destination_ref, b->destination_ref) ||
        a->scratch.epoch != b->scratch.epoch ||
        a->scratch.generation != b->scratch.generation ||
        a->scratch.base != b->scratch.base || a->scratch.bytes != b->scratch.bytes ||
        a->source_span.base != b->source_span.base ||
        a->source_span.bytes != b->source_span.bytes ||
        a->expected_cookie != b->expected_cookie ||
        a->expected_job_base != b->expected_job_base ||
        a->expected_token_base != b->expected_token_base ||
        a->expected_tag_base != b->expected_tag_base ||
        a->expected_tiles != b->expected_tiles ||
        memcmp(a->package_sha256, b->package_sha256,
               sizeof a->package_sha256) != 0 ||
        memcmp(a->checkpoint_sha256, b->checkpoint_sha256,
               sizeof a->checkpoint_sha256) != 0 ||
        memcmp(a->graph_sha256, b->graph_sha256,
               sizeof a->graph_sha256) != 0 ||
        !zn_nga_command_equal_v1(&a->command, &b->command))
        return 0;
    for (index = 0; index < a->graph_read_count; ++index) {
        if (!zn_nga_ref_equal_v1(a->graph_read_refs[index],
                                 b->graph_read_refs[index]))
            return 0;
    }
    return 1;
}

static int
zn_nga_driver_command_matches_v1(const ZnNativeGraphAbortV1 *adapter)
{
    uint32_t encoded[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];

    return adapter && adapter->driver &&
           adapter->driver->expected_tiles == adapter->expected_tiles_snapshot &&
           zn_nga_command_equal_v1(&adapter->driver->command,
                                   &adapter->command_snapshot) &&
           zn_native_conv_command_encode_v1(&adapter->driver->command,
                                             encoded) ==
               ZN_NATIVE_CONV_COMMAND_OK &&
           memcmp(encoded, adapter->command_words_snapshot,
                  sizeof encoded) == 0 &&
           memcmp(adapter->driver->command_words,
                  adapter->command_words_snapshot,
                  sizeof adapter->command_words_snapshot) == 0;
}

static int
zn_nga_mmio_equal_v1(const ZnNativeConvMmioOpsV2 *a,
                     const ZnNativeConvMmioOpsV2 *b)
{
    return a && b && a->context == b->context && a->read32 == b->read32 &&
           a->write32 == b->write32 && a->write_barrier == b->write_barrier;
}

static int
zn_nga_owner_equal_v1(const ZnNativeArenaOwnerV1 *a,
                      const ZnNativeArenaOwnerV1 *b)
{
    uint8_t index;
    uint16_t event_index;

    if (!a || !b || a->events != b->events || a->epoch != b->epoch ||
        a->event_count != b->event_count || a->fault != b->fault ||
        a->initialized != b->initialized || a->complete != b->complete)
        return 0;
    for (index = 0; index < ZN_NATIVE_ARENA_SLOT_COUNT_V1; ++index) {
        const ZnNativeArenaSlotV1 *x = &a->slots[index];
        const ZnNativeArenaSlotV1 *y = &b->slots[index];
        if (x->region.address != y->region.address ||
            x->region.capacity_bytes != y->region.capacity_bytes ||
            !zn_nga_ref_equal_v1(x->ref, y->ref) || x->bytes != y->bytes ||
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

static int
zn_nga_dispatch_equal_v1(const ZnDispatch *a, const ZnDispatch *b)
{
    return a && b && a->events == b->events && a->epoch == b->epoch &&
           a->next_tag == b->next_tag && a->count == b->count &&
           a->cursor == b->cursor && a->phase == b->phase &&
           a->index == b->index && a->pending == b->pending &&
           a->fault == b->fault && a->done == b->done &&
           zn_nga_request_equal_v1(&a->request, &b->request);
}

static int
zn_nga_graph_hooks_equal_v1(const ZnNativeGraphConvHooksV2 *a,
                            const ZnNativeGraphConvHooksV2 *b)
{
    return a && b && a->context == b->context &&
           a->check_leases == b->check_leases &&
           a->convert_views == b->convert_views &&
           a->clean_source == b->clean_source &&
           a->check_source_ready == b->check_source_ready &&
           a->invalidate_output == b->invalidate_output &&
           a->validate_and_publish == b->validate_and_publish &&
           a->drain_ready == b->drain_ready &&
           a->return_graph_read == b->return_graph_read &&
           a->release_scratch == b->release_scratch;
}

static int
zn_nga_conv_lifecycle_equal_v1(const ZnNativeArenaConvLifecycleV1 *a,
                               const ZnNativeArenaConvLifecycleV1 *b)
{
    return a && b && a->owner == b->owner &&
           zn_nga_graph_hooks_equal_v1(&a->runtime_hooks, &b->runtime_hooks) &&
           zn_nga_graph_hooks_equal_v1(&a->bridge.hooks, &b->bridge.hooks) &&
           zn_nga_binding_equal_v1(&a->bridge.binding, &b->bridge.binding) &&
           zn_nga_request_equal_v1(&a->bridge.run_request,
                                   &b->bridge.run_request) &&
           zn_nga_request_equal_v1(&a->bridge.return_request,
                                   &b->bridge.return_request) &&
           a->bridge.stage == b->bridge.stage &&
           a->bridge.dispatch_failure_latched ==
               b->bridge.dispatch_failure_latched &&
           a->bridge.converted == b->bridge.converted &&
           a->bridge.source_clean == b->bridge.source_clean &&
           a->bridge.return_cursor == b->bridge.return_cursor &&
           zn_nga_dispatch_equal_v1(&a->active_dispatch_snapshot,
                                    &b->active_dispatch_snapshot) &&
           zn_nga_request_equal_v1(&a->active_request, &b->active_request) &&
           zn_nga_dispatch_equal_v1(&a->last_run_dispatch_snapshot,
                                    &b->last_run_dispatch_snapshot) &&
           zn_nga_request_equal_v1(&a->last_run_request, &b->last_run_request) &&
           a->bridge_dispatch_ack_count == b->bridge_dispatch_ack_count &&
           a->owner_shadow_commit_count == b->owner_shadow_commit_count &&
           a->active == b->active && a->finishing == b->finishing &&
           a->fault == b->fault &&
           a->run_started_recorded == b->run_started_recorded &&
           a->publication_recorded == b->publication_recorded &&
           a->quiescence_recorded == b->quiescence_recorded;
}

static int
zn_nga_nonconv_lifecycle_equal_v1(const ZnNativeArenaNonConvLifecycleV1 *a,
                                  const ZnNativeArenaNonConvLifecycleV1 *b)
{
    return a && b && a->owner == b->owner && a->hooks.context == b->hooks.context &&
           a->hooks.map_source == b->hooks.map_source &&
           a->hooks.source_visible == b->hooks.source_visible &&
           a->hooks.map_output == b->hooks.map_output &&
           a->hooks.clean_output == b->hooks.clean_output &&
           a->hooks.publish_output == b->hooks.publish_output &&
           a->hooks.drain_ready == b->hooks.drain_ready &&
           a->hooks.return_graph_read == b->hooks.return_graph_read &&
           zn_nga_request_equal_v1(&a->run_request, &b->run_request) &&
           a->operator_call_count == b->operator_call_count &&
           a->active == b->active && a->mapped_mask == b->mapped_mask &&
           a->visible_mask == b->visible_mask &&
           a->output_mapped == b->output_mapped &&
           a->run_started == b->run_started && a->computed == b->computed &&
           a->output_cleaned == b->output_cleaned &&
           a->completion_recorded == b->completion_recorded &&
           a->run_acked == b->run_acked &&
           a->quiescence_recorded == b->quiescence_recorded &&
           a->fault == b->fault;
}

static int
zn_nga_executor_equal_v1(const ZnNativeGraphExecutorV1 *a,
                         const ZnNativeGraphExecutorV1 *b)
{
    return a && b && a->owner == b->owner && a->dispatch == b->dispatch &&
           a->conv_lifecycle == b->conv_lifecycle &&
           a->nonconv_lifecycle == b->nonconv_lifecycle &&
           a->resolve_conv == b->resolve_conv &&
           a->resolve_context == b->resolve_context &&
           zn_nga_request_equal_v1(&a->pending_request, &b->pending_request) &&
           zn_nga_request_equal_v1(&a->binding_run_request,
                                   &b->binding_run_request) &&
           zn_nga_binding_equal_v1(&a->binding, &b->binding) &&
           zn_nga_binding_equal_v1(&a->binding_snapshot, &b->binding_snapshot) &&
           a->terminal_code == b->terminal_code &&
           a->pending_valid == b->pending_valid &&
           a->binding_valid == b->binding_valid &&
           a->finish_pending == b->finish_pending &&
           a->terminal == b->terminal && a->complete == b->complete;
}

static uint8_t
zn_nga_read_mask_v1(uint8_t count)
{
    return count == 0 ? 0 : (uint8_t)((UINT32_C(1) << count) - 1u);
}

static int
zn_nga_initial_binding_valid_v1(const ZnNativeGraphAbortV1 *adapter)
{
    const ZnNativeGraphExecutorV1 *executor;
    const ZnNativeGraphConvBindingV2 *binding;
    const ZnRequest *request;
    const ZnEvent *event;
    const ZnNativeArenaEventStateV1 *event_state;
    uint8_t index;

    if (!adapter || !adapter->executor || !adapter->owner ||
        !adapter->dispatch || !adapter->conv_lifecycle || !adapter->bridge ||
        !adapter->driver)
        return 0;
    executor = adapter->executor;
    binding = &executor->binding;
    request = &executor->pending_request;
    if (executor->owner != adapter->owner ||
        executor->dispatch != adapter->dispatch ||
        executor->conv_lifecycle != adapter->conv_lifecycle ||
        executor->nonconv_lifecycle != adapter->nonconv_lifecycle ||
        !executor->terminal || executor->terminal_code >= 0 ||
        executor->complete || executor->finish_pending ||
        !executor->pending_valid || !executor->binding_valid ||
        !adapter->owner->initialized || !adapter->owner->fault ||
        !adapter->dispatch->fault || !adapter->dispatch->pending ||
        adapter->dispatch->done || request->operation != ZN_RUN ||
        !request->job || request->event_index >= adapter->owner->event_count ||
        adapter->dispatch->events != adapter->owner->events ||
        adapter->dispatch->epoch != adapter->owner->epoch ||
        request->epoch != adapter->owner->epoch ||
        adapter->dispatch->count != adapter->owner->event_count ||
        adapter->dispatch->cursor != request->event_index ||
        adapter->dispatch->phase != ZN_RUN ||
        request->job != &adapter->owner->events[request->event_index] ||
        !zn_nga_request_equal_v1(request, &executor->binding_run_request) ||
        !zn_nga_request_equal_v1(request, &adapter->dispatch->request) ||
        !adapter->nonconv_lifecycle ||
        adapter->nonconv_lifecycle->owner != adapter->owner ||
        adapter->conv_lifecycle->owner != adapter->owner ||
        adapter->conv_lifecycle->active ||
        !adapter->conv_lifecycle->run_started_recorded ||
        !zn_nga_request_equal_v1(request,
                                 &adapter->conv_lifecycle->active_request) ||
        !zn_nga_request_equal_v1(request,
                                 &adapter->conv_lifecycle->last_run_request) ||
        !zn_nga_dispatch_equal_v1(
            &adapter->conv_lifecycle->active_dispatch_snapshot,
            &adapter->conv_lifecycle->last_run_dispatch_snapshot) ||
        !adapter->conv_lifecycle->active_dispatch_snapshot.pending ||
        adapter->conv_lifecycle->active_dispatch_snapshot.fault ||
        adapter->conv_lifecycle->active_dispatch_snapshot.done ||
        adapter->conv_lifecycle->active_dispatch_snapshot.epoch != request->epoch ||
        adapter->conv_lifecycle->active_dispatch_snapshot.cursor !=
            request->event_index ||
        adapter->conv_lifecycle->active_dispatch_snapshot.phase != ZN_RUN ||
        !zn_nga_request_equal_v1(
            request, &adapter->conv_lifecycle->active_dispatch_snapshot.request) ||
        (adapter->bridge->stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED &&
         adapter->bridge->stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED) ||
        adapter->conv_lifecycle->publication_recorded ||
        !zn_nga_request_equal_v1(request, &adapter->bridge->run_request) ||
        !zn_nga_binding_equal_v1(binding, &executor->binding_snapshot) ||
        !zn_nga_binding_equal_v1(binding, &adapter->bridge->binding) ||
        !zn_nga_binding_equal_v1(binding, &adapter->binding_snapshot))
        return 0;

    event = request->job;
    event_state = &adapter->owner->event_state[request->event_index];
    if (event->operation != ZN_CONV || !event->has_destination ||
        event->read_count > ZN_NATIVE_GRAPH_CONV_MAX_READS_V2 ||
        event_state->run_tag != request->tag ||
        !event_state->allocated || !event_state->run_started ||
        event_state->run_completed || event_state->output_published ||
        event_state->io_quiescent || event_state->drained ||
        event_state->run_acked || event_state->acquired_mask !=
            zn_nga_read_mask_v1(event->read_count) ||
        event_state->returned_mask != 0 || event_state->retired_mask != 0 ||
        binding->dispatch_epoch != request->epoch ||
        binding->dispatch_tag != request->tag ||
        binding->event_index != request->event_index ||
        binding->graph_read_count != event->read_count ||
        !zn_nga_ref_equal_v1(binding->destination_ref,
                             event->destination.ref) ||
        binding->expected_tiles != event->tile_count ||
        binding->expected_cookie != binding->command.request_cookie ||
        binding->command.epoch != request->epoch ||
        binding->command.event != event->event ||
        binding->command.model_crc32 != ZN_NATIVE_CONV_MMIO_MODEL_CRC32 ||
        binding->command.destination_base != event->destination.address ||
        binding->command.destination_generation !=
            event->destination.ref.generation ||
        !binding->scratch.generation || binding->scratch.epoch != request->epoch ||
        binding->source_span.base != binding->scratch.base ||
        !binding->source_span.bytes ||
        binding->source_span.bytes > binding->scratch.bytes ||
        binding->command.source_base != binding->source_span.base ||
        binding->command.source_generation != binding->scratch.generation ||
        memcmp(binding->package_sha256, ZN_NATIVE_GRAPH_CONV_PACKAGE_SHA256_V2,
               sizeof binding->package_sha256) != 0 ||
        memcmp(binding->checkpoint_sha256, ZN_NATIVE_GRAPH_CONV_MODEL_SHA256_V2,
               sizeof binding->checkpoint_sha256) != 0 ||
        memcmp(binding->graph_sha256, ZN_NATIVE_GRAPH_CONV_GRAPH_SHA256_V2,
               sizeof binding->graph_sha256) != 0)
        return 0;

    for (index = 0; index < event->read_count; ++index) {
        const ZnRef ref = event->reads[index];
        const ZnNativeArenaSlotV1 *slot;
        if (!zn_nga_ref_equal_v1(ref, binding->graph_read_refs[index]) ||
            ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
            return 0;
        slot = &adapter->owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_nga_ref_equal_v1(slot->ref, ref) || !slot->reader_count ||
            !slot->io_count)
            return 0;
    }
    if (event->destination.ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return 0;
    {
        const ZnNativeArenaSlotV1 *destination =
            &adapter->owner->slots[event->destination.ref.slot];
        if (destination->state != ZN_NATIVE_ARENA_SLOT_RESERVED_V1 ||
            !zn_nga_ref_equal_v1(destination->ref,
                                 event->destination.ref) ||
            !destination->io_count)
            return 0;
    }
    return zn_nga_driver_command_matches_v1(adapter);
}

static int
zn_nga_identity_matches_v1(const ZnNativeGraphAbortV1 *adapter)
{
    const ZnNativeGraphExecutorV1 *executor;
    const ZnNativeArenaConvLifecycleV1 *lifecycle;
    const ZnNativeGraphConvBridgeV2 *bridge;

    if (!adapter || !adapter->executor || !adapter->owner ||
        !adapter->dispatch || !adapter->conv_lifecycle ||
        !adapter->nonconv_lifecycle || !adapter->bridge || !adapter->driver)
        return 0;
    executor = adapter->executor;
    lifecycle = adapter->conv_lifecycle;
    bridge = adapter->bridge;
    return zn_nga_executor_equal_v1(executor, &adapter->executor_snapshot) &&
           zn_nga_owner_equal_v1(adapter->owner,
                                 &adapter->owner_snapshot) &&
           zn_nga_dispatch_equal_v1(adapter->dispatch,
                                    &adapter->dispatch_snapshot) &&
           zn_nga_conv_lifecycle_equal_v1(lifecycle,
                                          &adapter->conv_snapshot) &&
           zn_nga_nonconv_lifecycle_equal_v1(adapter->nonconv_lifecycle,
                                             &adapter->nonconv_snapshot) &&
           bridge == &lifecycle->bridge && bridge->driver.state !=
               ZN_NATIVE_CONV_STATE_V2_UNINITIALIZED &&
           adapter->driver == &bridge->driver &&
           zn_nga_mmio_equal_v1(&adapter->driver->mmio,
                                &adapter->mmio_snapshot) &&
           zn_nga_driver_command_matches_v1(adapter);
}

static int
zn_nga_result_matches_v1(const ZnNativeGraphAbortV1 *adapter)
{
    const ZnNativeConvResultV2 *result;
    const ZnNativeGraphConvBindingV2 *binding;
    const ZnNativeConvCommand *command;

    if (!adapter || !adapter->driver || !adapter->driver->result_verified)
        return 0;
    result = &adapter->driver->result;
    binding = &adapter->binding_snapshot;
    command = &adapter->command_snapshot;
    return result->request_cookie == command->request_cookie &&
           result->epoch == command->epoch && result->event == command->event &&
           result->model_crc32 == command->model_crc32 &&
           result->job_base == command->job_base &&
           result->token_base == command->token_base &&
           result->tag_base == command->tag_base &&
           result->destination_generation == command->destination_generation &&
           result->committed_tiles == binding->expected_tiles &&
           result->source_generation == command->source_generation;
}

static int
zn_nga_success_ack_proven_v1(const ZnNativeConvDriverV2 *driver)
{
    uint32_t required = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
    uint32_t forbidden = ZN_NC_STATUS_COMMAND_PENDING |
        ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE | ZN_NC_STATUS_DONE |
        ZN_NC_STATUS_FAULT | ZN_NC_STATUS_NEEDS_DRAIN |
        ZN_NC_STATUS_RESULT_VALID | ZN_NC_STATUS_PREACCEPT_TIMEOUT;

    return driver && driver->state == ZN_NATIVE_CONV_STATE_V2_IDLE &&
           !zn_native_conv_driver_ownership_held_v2(driver) &&
           !driver->ack_sent && driver->ack_kind == 0 &&
           driver->last_bridge_error == ZN_NC_BRIDGE_ERROR_NONE &&
           driver->last_backend_fault_code == 0 &&
           (driver->last_status & required) == required &&
           (driver->last_status & forbidden) == 0;
}

static int
zn_nga_fault_ack_proven_v1(const ZnNativeConvDriverV2 *driver)
{
    uint32_t required = ZN_NC_STATUS_FAULT | ZN_NC_STATUS_DRAIN_COMPLETE;
    uint32_t forbidden = ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_ACCEPTED |
        ZN_NC_STATUS_DONE | ZN_NC_STATUS_NEEDS_DRAIN |
        ZN_NC_STATUS_RESULT_VALID | ZN_NC_STATUS_PREACCEPT_TIMEOUT |
        ZN_NC_STATUS_READY;

    return driver && driver->state == ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT &&
           !zn_native_conv_driver_ownership_held_v2(driver) &&
           !driver->ack_sent && driver->ack_kind == 0 &&
           driver->result_verified && driver->result_is_fault &&
           driver->last_bridge_error == ZN_NC_BRIDGE_ERROR_NONE &&
           (driver->last_status & required) == required &&
           (driver->last_status & forbidden) == 0;
}

static ZnNativeGraphAbortCodeV1
zn_nga_fail_v1(ZnNativeGraphAbortV1 *adapter,
               ZnNativeGraphAbortCodeV1 code)
{
    adapter->state = ZN_NATIVE_GRAPH_ABORT_STATE_V1_FAILED;
    adapter->failure_code = code;
    return code;
}

ZnNativeGraphAbortCodeV1
zn_native_graph_abort_v1_init(ZnNativeGraphAbortV1 *adapter,
                              ZnNativeGraphExecutorV1 *executor)
{
    if (!adapter || !executor || !executor->owner || !executor->dispatch ||
        !executor->conv_lifecycle || !executor->nonconv_lifecycle)
        return ZN_NATIVE_GRAPH_ABORT_V1_ARGUMENT;
    memset(adapter, 0, sizeof *adapter);
    adapter->executor = executor;
    adapter->owner = executor->owner;
    adapter->dispatch = executor->dispatch;
    adapter->conv_lifecycle = executor->conv_lifecycle;
    adapter->nonconv_lifecycle = executor->nonconv_lifecycle;
    adapter->bridge = &executor->conv_lifecycle->bridge;
    adapter->driver = &adapter->bridge->driver;
    adapter->binding_snapshot = executor->binding;
    adapter->command_snapshot = adapter->driver->command;
    adapter->mmio_snapshot = adapter->driver->mmio;
    memcpy(adapter->command_words_snapshot, adapter->driver->command_words,
           sizeof adapter->command_words_snapshot);
    adapter->expected_tiles_snapshot = adapter->driver->expected_tiles;
    adapter->terminal_code_snapshot = executor->terminal_code;
    adapter->state = ZN_NATIVE_GRAPH_ABORT_STATE_V1_ARMED;
    if (!zn_nga_initial_binding_valid_v1(adapter))
        return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY);

    adapter->executor_snapshot = *executor;
    adapter->owner_snapshot = *adapter->owner;
    adapter->dispatch_snapshot = *adapter->dispatch;
    adapter->conv_snapshot = *adapter->conv_lifecycle;
    adapter->nonconv_snapshot = *adapter->nonconv_lifecycle;
    return ZN_NATIVE_GRAPH_ABORT_V1_READY;
}

ZnNativeGraphAbortCodeV1
zn_native_graph_abort_v1_step(ZnNativeGraphAbortV1 *adapter)
{
    ZnNativeConvDriverCodeV2 driver_code;
    ZnNativeConvDriverV2 *driver;

    if (!adapter)
        return ZN_NATIVE_GRAPH_ABORT_V1_ARGUMENT;
    if (adapter->state == ZN_NATIVE_GRAPH_ABORT_STATE_V1_QUIESCENT)
        return ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED;
    if (adapter->state == ZN_NATIVE_GRAPH_ABORT_STATE_V1_FAILED)
        return (ZnNativeGraphAbortCodeV1)adapter->failure_code;
    if (adapter->state != ZN_NATIVE_GRAPH_ABORT_STATE_V1_ARMED)
        return ZN_NATIVE_GRAPH_ABORT_V1_ARGUMENT;
    if (!zn_nga_identity_matches_v1(adapter))
        return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY);

    driver = adapter->driver;
    switch (driver->state) {
    case ZN_NATIVE_CONV_STATE_V2_ACK_UNCERTAIN:
        driver_code = zn_native_conv_driver_poll_v2(driver);
        break;
    case ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT:
    case ZN_NATIVE_CONV_STATE_V2_FAULT_RESULT:
        if (!zn_nga_result_matches_v1(adapter))
            return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY);
        driver_code = zn_native_conv_driver_ack_v2(driver);
        break;
    case ZN_NATIVE_CONV_STATE_V2_LOCAL_ERROR:
        driver_code = zn_native_conv_driver_ack_v2(driver);
        break;
    case ZN_NATIVE_CONV_STATE_V2_PENDING:
    case ZN_NATIVE_CONV_STATE_V2_ACCEPTED:
    case ZN_NATIVE_CONV_STATE_V2_DRAINING:
    case ZN_NATIVE_CONV_STATE_V2_START_UNCERTAIN:
    case ZN_NATIVE_CONV_STATE_V2_POISONED:
    case ZN_NATIVE_CONV_STATE_V2_IDENTITY_REJECTED:
        driver_code = zn_native_conv_driver_timeout_v2(driver);
        break;
    case ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT:
        if (zn_nga_fault_ack_proven_v1(driver)) {
            adapter->state = ZN_NATIVE_GRAPH_ABORT_STATE_V1_QUIESCENT;
            return ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED;
        }
        return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_DRIVER);
    case ZN_NATIVE_CONV_STATE_V2_IDLE:
    case ZN_NATIVE_CONV_STATE_V2_UNINITIALIZED:
    default:
        return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_DRIVER);
    }
    adapter->last_driver_code = driver_code;

    if (!zn_nga_identity_matches_v1(adapter))
        return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY);
    if (driver_code == ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY ||
        driver_code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY) {
        if (!zn_nga_result_matches_v1(adapter) ||
            driver->result_is_fault !=
                (driver_code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY))
            return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_IDENTITY);
        return ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS;
    }
    if (driver_code == ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY ||
        driver_code == ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS)
        return ZN_NATIVE_GRAPH_ABORT_V1_IN_PROGRESS;
    if (driver_code == ZN_NATIVE_CONV_DRIVER_V2_OK ||
        driver_code == ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT) {
        if (zn_nga_success_ack_proven_v1(driver) ||
            zn_nga_fault_ack_proven_v1(driver)) {
            adapter->state = ZN_NATIVE_GRAPH_ABORT_STATE_V1_QUIESCENT;
            return ZN_NATIVE_GRAPH_ABORT_V1_QUIESCENT_OWNERSHIP_RETAINED;
        }
        return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_DRIVER);
    }
    return zn_nga_fail_v1(adapter, ZN_NATIVE_GRAPH_ABORT_V1_DRIVER);
}
