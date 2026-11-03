#include "native_arena_conv_lifecycle_v1.h"

#include <string.h>

static int
zn_acl_ref_equal_v1(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
zn_acl_request_equal_v1(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index &&
           a->operation == b->operation &&
           zn_acl_ref_equal_v1(a->ref, b->ref) && a->job == b->job;
}

static int
zn_acl_dispatch_equal_v1(const ZnDispatch *a, const ZnDispatch *b)
{
    return a && b && a->events == b->events && a->epoch == b->epoch &&
           a->next_tag == b->next_tag && a->count == b->count &&
           a->cursor == b->cursor && a->phase == b->phase &&
           a->index == b->index && a->pending == b->pending &&
           a->fault == b->fault && a->done == b->done &&
           zn_acl_request_equal_v1(&a->request, &b->request);
}

static int
zn_acl_pending_matches_v1(const ZnDispatch *dispatch,
                          const ZnRequest *request)
{
    return dispatch && request && dispatch->events && dispatch->pending &&
           !dispatch->fault && request->event_index < dispatch->count &&
           dispatch->cursor == request->event_index &&
           dispatch->phase == request->operation &&
           request->epoch == dispatch->epoch &&
           request->job == &dispatch->events[request->event_index] &&
           zn_acl_request_equal_v1(request, &dispatch->request);
}

static uint8_t
zn_acl_read_mask_v1(uint8_t count)
{
    return count == 0 ? 0 : (uint8_t)((UINT32_C(1) << count) - 1u);
}

static int
zn_acl_binding_matches_owner_v1(const ZnNativeArenaConvLifecycleV1 *lifecycle,
                                const ZnRequest *request,
                                const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnNativeArenaOwnerV1 *owner;
    const ZnNativeArenaEventStateV1 *event_state;
    const ZnEvent *event;
    uint8_t index;

    if (!lifecycle || !lifecycle->owner || !request || !request->job ||
        !binding || request->event_index >= ZN_NATIVE_ARENA_EVENT_COUNT_V1)
        return 0;
    owner = lifecycle->owner;
    event = request->job;
    event_state = &owner->event_state[request->event_index];
    if (!lifecycle->last_run_request.job ||
        lifecycle->last_run_request.operation != ZN_RUN ||
        lifecycle->last_run_request.epoch != request->epoch ||
        lifecycle->last_run_request.event_index != request->event_index ||
        lifecycle->last_run_request.job != request->job ||
        !owner->initialized || owner->fault || !owner->events ||
        request->job != &owner->events[request->event_index] ||
        binding->dispatch_epoch != request->epoch ||
        binding->dispatch_tag != lifecycle->last_run_request.tag ||
        binding->event_index != request->event_index ||
        binding->graph_read_count != event->read_count ||
        !zn_acl_ref_equal_v1(binding->destination_ref,
                             event->destination.ref) ||
        event_state->acquired_mask != zn_acl_read_mask_v1(event->read_count))
        return 0;

    for (index = 0; index < event->read_count; ++index) {
        ZnRef ref = event->reads[index];
        const ZnNativeArenaSlotV1 *slot;
        uint8_t bit = (uint8_t)(UINT32_C(1) << index);
        if (ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1 ||
            !zn_acl_ref_equal_v1(binding->graph_read_refs[index], ref))
            return 0;
        slot = &owner->slots[ref.slot];
        if (slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_acl_ref_equal_v1(slot->ref, ref) ||
            (slot->reader_count == 0 &&
             (event_state->returned_mask & bit) == 0))
            return 0;
    }

    if (event->destination.ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1)
        return 0;
    {
        const ZnNativeArenaSlotV1 *destination =
            &owner->slots[event->destination.ref.slot];
        if (!event_state->allocated ||
            !zn_acl_ref_equal_v1(destination->ref, event->destination.ref))
            return 0;
        if (request->operation == ZN_RUN &&
            ((!event_state->output_published &&
              destination->state != ZN_NATIVE_ARENA_SLOT_RESERVED_V1) ||
             (event_state->output_published &&
              destination->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1)))
            return 0;
        if ((request->operation == ZN_DRAIN ||
             request->operation == ZN_RETURN) &&
            destination->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1)
            return 0;
    }

    if (request->operation == ZN_DRAIN &&
        (!event_state->run_acked || !event_state->run_completed ||
         event_state->io_quiescent))
        return 0;
    if (request->operation == ZN_RETURN &&
        (!event_state->drained || event_state->io_quiescent == 0))
        return 0;
    return 1;
}

static void
zn_acl_poison_owner_v1(ZnNativeArenaConvLifecycleV1 *lifecycle,
                       const ZnDispatch *snapshot,
                       const ZnRequest *request)
{
    ZnNativeArenaOwnerV1 owner_copy;
    ZnDispatch dispatch_copy;

    if (!lifecycle || !lifecycle->owner)
        return;
    if (snapshot && request && lifecycle->owner->initialized) {
        owner_copy = *lifecycle->owner;
        dispatch_copy = *snapshot;
        (void)zn_native_arena_owner_fail_v1(&owner_copy, &dispatch_copy,
                                             request);
        *lifecycle->owner = owner_copy;
    } else {
        lifecycle->owner->fault = 1;
    }
    lifecycle->fault = 1;
}

static ZnNativeArenaConvLifecycleCodeV1
zn_acl_owner_code_v1(ZnNativeArenaOwnerCodeV1 code)
{
    switch (code) {
    case ZN_NATIVE_ARENA_OWNER_V1_ACKED:
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED;
    case ZN_NATIVE_ARENA_OWNER_V1_BUSY:
    case ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND:
    case ZN_NATIVE_ARENA_OWNER_V1_NEEDS_QUIESCENCE:
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY;
    case ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST:
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_STALE_REQUEST;
    case ZN_NATIVE_ARENA_OWNER_V1_ORDER:
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ORDER;
    case ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT:
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ARGUMENT;
    case ZN_NATIVE_ARENA_OWNER_V1_INVALID:
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_INVALID;
    default:
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED;
    }
}

static int
zn_acl_hook_check_leases_v1(void *context, const ZnRequest *request,
                            const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;

    if (!lifecycle || !lifecycle->active ||
        !zn_acl_request_equal_v1(request, &lifecycle->active_request) ||
        !zn_acl_binding_matches_owner_v1(lifecycle, request, binding))
        return -1;
    return lifecycle->runtime_hooks.check_leases(
        lifecycle->runtime_hooks.context, request, binding);
}

static int
zn_acl_hook_convert_views_v1(void *context, const ZnRequest *request,
                             const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;
    if (!lifecycle || !lifecycle->active ||
        !zn_acl_request_equal_v1(request, &lifecycle->active_request))
        return -1;
    return lifecycle->runtime_hooks.convert_views(
        lifecycle->runtime_hooks.context, request, binding);
}

static int
zn_acl_hook_clean_source_v1(void *context,
                            const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;
    if (!lifecycle || !lifecycle->active)
        return -1;
    return lifecycle->runtime_hooks.clean_source(
        lifecycle->runtime_hooks.context, binding);
}

static int
zn_acl_hook_check_source_ready_v1(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;
    if (!lifecycle || !lifecycle->active ||
        !zn_acl_request_equal_v1(request, &lifecycle->active_request))
        return -1;
    return lifecycle->runtime_hooks.check_source_ready(
        lifecycle->runtime_hooks.context, request, binding);
}

static int
zn_acl_hook_invalidate_output_v1(
    void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;
    if (!lifecycle || !lifecycle->active)
        return -1;
    return lifecycle->runtime_hooks.invalidate_output(
        lifecycle->runtime_hooks.context, binding);
}

static int
zn_acl_result_matches_v1(const ZnNativeConvDriverV2 *driver,
                         const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnNativeConvResultV2 *result;
    const ZnNativeConvCommand *command;

    if (!driver || !binding || !driver->result_verified ||
        driver->result_is_fault || driver->state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(driver))
        return 0;
    result = &driver->result;
    command = &binding->command;
    return result->request_cookie == command->request_cookie &&
           result->epoch == command->epoch &&
           result->event == command->event &&
           result->model_crc32 == command->model_crc32 &&
           result->job_base == command->job_base &&
           result->token_base == command->token_base &&
           result->tag_base == command->tag_base &&
           result->destination_generation == command->destination_generation &&
           result->committed_tiles == binding->expected_tiles &&
           result->source_generation == command->source_generation;
}

static int
zn_acl_hook_validate_and_publish_v1(
    void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;
    ZnNativeArenaCompletionEvidenceV1 evidence;
    ZnNativeArenaOwnerCodeV1 code;

    if (!lifecycle || !lifecycle->active ||
        lifecycle->active_request.operation != ZN_RUN)
        return -1;
    if (!zn_acl_binding_matches_owner_v1(lifecycle,
                                          &lifecycle->active_request,
                                          binding) ||
        !zn_acl_result_matches_v1(&lifecycle->bridge.driver, binding))
        return -1;
    {
        int callback_code = lifecycle->runtime_hooks.validate_and_publish(
            lifecycle->runtime_hooks.context, binding);
        if (callback_code != 0)
            return callback_code;
    }

    memset(&evidence, 0, sizeof evidence);
    evidence.epoch = lifecycle->active_request.epoch;
    evidence.run_tag = lifecycle->active_request.tag;
    evidence.event_index = lifecycle->active_request.event_index;
    evidence.destination_ref = binding->destination_ref;
    evidence.destination_bytes = lifecycle->active_request.job->destination.bytes;
    evidence.result_identity_verified = 1;
    evidence.driver_terminal_success = 1;
    /* A READY platform publisher means identity checks and visibility completed. */
    evidence.output_cache_visible = 1;
    code = zn_native_arena_owner_publish_v1(
        lifecycle->owner, &lifecycle->active_dispatch_snapshot,
        &lifecycle->active_request, &evidence);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return -1;
    lifecycle->publication_recorded = 1;
    return 0;
}

static int
zn_acl_hook_drain_ready_v1(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;
    ZnNativeArenaQuiescenceEvidenceV1 evidence;
    ZnNativeArenaOwnerCodeV1 code;
    int callback_code;

    if (!lifecycle || !lifecycle->active ||
        !zn_acl_request_equal_v1(request, &lifecycle->active_request) ||
        request->operation != ZN_DRAIN)
        return -1;
    callback_code = lifecycle->runtime_hooks.drain_ready(
        lifecycle->runtime_hooks.context, request, binding);
    if (callback_code != 0)
        return callback_code;
    if (lifecycle->bridge.driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(&lifecycle->bridge.driver))
        return 1;

    memset(&evidence, 0, sizeof evidence);
    evidence.epoch = request->epoch;
    evidence.run_tag = lifecycle->owner->event_state[request->event_index].run_tag;
    evidence.event_index = request->event_index;
    evidence.all_read_io_quiet = 1;
    evidence.all_write_io_quiet = 1;
    evidence.driver_terminal = 1;
    code = zn_native_arena_owner_notify_quiescent_v1(
        lifecycle->owner, &lifecycle->active_dispatch_snapshot,
        request, &evidence);
    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return -1;
    lifecycle->quiescence_recorded = 1;
    return 0;
}

static int
zn_acl_hook_return_graph_read_v1(
    void *context, const ZnRequest *request,
    const ZnNativeGraphConvBindingV2 *binding, uint8_t read_index)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;

    if (!lifecycle || !lifecycle->active ||
        !zn_acl_request_equal_v1(request, &lifecycle->active_request) ||
        request->operation != ZN_RETURN ||
        !zn_acl_binding_matches_owner_v1(lifecycle, request, binding) ||
        read_index >= request->job->read_count ||
        !zn_acl_ref_equal_v1(request->ref, request->job->reads[read_index]))
        return -1;
    if (lifecycle->bridge.driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(&lifecycle->bridge.driver))
        return 1;
    return lifecycle->runtime_hooks.return_graph_read(
        lifecycle->runtime_hooks.context, request, binding, read_index);
}

static int
zn_acl_hook_release_scratch_v1(
    void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleV1 *lifecycle =
        (ZnNativeArenaConvLifecycleV1 *)context;
    const ZnRequest *run;
    const ZnNativeArenaEventStateV1 *event_state;

    if (!lifecycle || !lifecycle->finishing || !lifecycle->owner ||
        !lifecycle->last_run_request.job ||
        !zn_acl_binding_matches_owner_v1(lifecycle,
                                          &lifecycle->last_run_request,
                                          binding))
        return -1;
    run = &lifecycle->last_run_request;
    event_state = &lifecycle->owner->event_state[run->event_index];
    if (!event_state->run_acked || !event_state->drained ||
        !event_state->io_quiescent ||
        event_state->returned_mask !=
            zn_acl_read_mask_v1(run->job->read_count) ||
        lifecycle->bridge.driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(&lifecycle->bridge.driver))
        return -1;
    return lifecycle->runtime_hooks.release_scratch(
        lifecycle->runtime_hooks.context, binding);
}

ZnNativeArenaConvLifecycleCodeV1
zn_native_arena_conv_lifecycle_init_v1(
    ZnNativeArenaConvLifecycleV1 *lifecycle,
    ZnNativeArenaOwnerV1 *owner,
    const ZnNativeConvMmioOpsV2 *mmio,
    const ZnNativeGraphConvHooksV2 *runtime_hooks)
{
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativeGraphConvBridgeCodeV2 code;

    if (!lifecycle || !owner || !mmio || !runtime_hooks ||
        !runtime_hooks->check_leases || !runtime_hooks->convert_views ||
        !runtime_hooks->clean_source || !runtime_hooks->check_source_ready ||
        !runtime_hooks->invalidate_output ||
        !runtime_hooks->validate_and_publish || !runtime_hooks->drain_ready ||
        !runtime_hooks->return_graph_read || !runtime_hooks->release_scratch)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ARGUMENT;
    if (!owner->initialized || owner->fault)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_INVALID;

    memset(lifecycle, 0, sizeof *lifecycle);
    lifecycle->owner = owner;
    lifecycle->runtime_hooks = *runtime_hooks;
    hooks = *runtime_hooks;
    hooks.context = lifecycle;
    hooks.check_leases = zn_acl_hook_check_leases_v1;
    hooks.convert_views = zn_acl_hook_convert_views_v1;
    hooks.clean_source = zn_acl_hook_clean_source_v1;
    hooks.check_source_ready = zn_acl_hook_check_source_ready_v1;
    hooks.invalidate_output = zn_acl_hook_invalidate_output_v1;
    hooks.validate_and_publish = zn_acl_hook_validate_and_publish_v1;
    hooks.drain_ready = zn_acl_hook_drain_ready_v1;
    hooks.return_graph_read = zn_acl_hook_return_graph_read_v1;
    hooks.release_scratch = zn_acl_hook_release_scratch_v1;
    code = zn_native_graph_conv_bridge_init_v2(&lifecycle->bridge, mmio,
                                                &hooks);
    return code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED ?
           ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED :
           ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ARGUMENT;
}

static ZnNativeArenaConvLifecycleCodeV1
zn_acl_precheck_v1(ZnNativeArenaConvLifecycleV1 *lifecycle,
                   const ZnDispatch *snapshot, const ZnRequest *request)
{
    ZnNativeArenaOwnerV1 owner_copy;
    ZnDispatch dispatch_copy;
    ZnNativeArenaOwnerCodeV1 code;

    if (request->operation == ZN_RETURN) {
        const ZnEvent *event = request->job;
        const ZnNativeArenaEventStateV1 *event_state;
        const ZnNativeArenaSlotV1 *slot;
        uint8_t index = snapshot->index;
        uint8_t bit;

        if (!event || index >= event->read_count ||
            request->ref.slot >= ZN_NATIVE_ARENA_SLOT_COUNT_V1 ||
            !zn_acl_ref_equal_v1(request->ref, event->reads[index]))
            return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_INVALID;
        event_state = &lifecycle->owner->event_state[request->event_index];
        bit = (uint8_t)(UINT32_C(1) << index);
        slot = &lifecycle->owner->slots[request->ref.slot];
        if (!event_state->drained || !event_state->io_quiescent ||
            (event_state->acquired_mask & bit) == 0 ||
            (event_state->returned_mask & bit) != 0 ||
            slot->state != ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 ||
            !zn_acl_ref_equal_v1(slot->ref, request->ref) ||
            slot->reader_count == 0 || slot->io_count != 0)
            return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ORDER;
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED;
    }

    owner_copy = *lifecycle->owner;
    dispatch_copy = *snapshot;
    code = zn_native_arena_owner_step_v1(&owner_copy, &dispatch_copy, request);
    if (request->operation == ZN_RUN &&
        (code == ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND ||
         code == ZN_NATIVE_ARENA_OWNER_V1_BUSY))
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED;
    if (request->operation == ZN_DRAIN &&
        code == ZN_NATIVE_ARENA_OWNER_V1_BUSY)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED;
    return zn_acl_owner_code_v1(code);
}

static ZnNativeArenaConvLifecycleCodeV1
zn_acl_commit_bridge_ack_v1(ZnNativeArenaConvLifecycleV1 *lifecycle,
                            ZnDispatch *dispatch,
                            const ZnDispatch *snapshot,
                            const ZnRequest *request)
{
    ZnNativeArenaOwnerV1 owner_copy = *lifecycle->owner;
    ZnDispatch dispatch_copy = *snapshot;
    ZnNativeArenaOwnerCodeV1 code =
        zn_native_arena_owner_step_v1(&owner_copy, &dispatch_copy, request);

    if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED ||
        !zn_acl_dispatch_equal_v1(&dispatch_copy, dispatch)) {
        zn_acl_poison_owner_v1(lifecycle, snapshot, request);
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED;
    }
    *lifecycle->owner = owner_copy;
    ++lifecycle->bridge_dispatch_ack_count;
    ++lifecycle->owner_shadow_commit_count;
    return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED;
}

ZnNativeArenaConvLifecycleCodeV1
zn_native_arena_conv_lifecycle_step_v1(
    ZnNativeArenaConvLifecycleV1 *lifecycle, ZnDispatch *dispatch,
    const ZnRequest *request, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeArenaConvLifecycleCodeV1 precheck;
    ZnNativeGraphConvBridgeCodeV2 bridge_code;
    ZnNativeArenaOwnerCodeV1 owner_code;
    ZnDispatch snapshot;
    ZnNativeGraphConvBridgeStageV2 stage_before;

    if (!lifecycle || !lifecycle->owner || !dispatch || !request)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ARGUMENT;
    if (lifecycle->fault || lifecycle->owner->fault || dispatch->fault)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_POISONED;
    if (!zn_acl_pending_matches_v1(dispatch, request))
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_STALE_REQUEST;
    if (lifecycle->bridge.stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FINISH_REQUIRED;

    if (request->operation != ZN_RUN && request->operation != ZN_DRAIN &&
        request->operation != ZN_RETURN) {
        owner_code = zn_native_arena_owner_step_v1(lifecycle->owner, dispatch,
                                                    request);
        if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_ACKED &&
            (owner_code == ZN_NATIVE_ARENA_OWNER_V1_FAILED ||
             dispatch->fault || lifecycle->owner->fault))
            lifecycle->fault = 1;
        return zn_acl_owner_code_v1(owner_code);
    }
    if (!request->job || request->job->operation != ZN_CONV)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_UNSUPPORTED;
    if (request->operation == ZN_RUN && !binding)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ARGUMENT;

    snapshot = *dispatch;
    precheck = zn_acl_precheck_v1(lifecycle, &snapshot, request);
    if (precheck != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
        return precheck;

    lifecycle->active_dispatch_snapshot = snapshot;
    lifecycle->active_request = *request;
    lifecycle->active = 1;
    stage_before = lifecycle->bridge.stage;
    if (request->operation == ZN_RUN &&
        stage_before == ZN_NATIVE_GRAPH_CONV_STAGE_V2_IDLE) {
        lifecycle->last_run_dispatch_snapshot = snapshot;
        lifecycle->last_run_request = *request;
        lifecycle->run_started_recorded = 0;
        lifecycle->publication_recorded = 0;
        lifecycle->quiescence_recorded = 0;
    }

    bridge_code = zn_native_graph_conv_bridge_step_v2(
        &lifecycle->bridge, dispatch, request, binding);

    if (request->operation == ZN_RUN &&
        !lifecycle->run_started_recorded &&
        lifecycle->bridge.stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED) {
        owner_code = zn_native_arena_owner_run_started_v1(
            lifecycle->owner, &snapshot, request);
        if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_ACKED) {
            lifecycle->active = 0;
            zn_acl_poison_owner_v1(lifecycle, &snapshot, request);
            return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED;
        }
        lifecycle->run_started_recorded = 1;
    }

    lifecycle->active = 0;
    if (bridge_code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY;
    if (bridge_code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED) {
        if ((request->operation == ZN_RUN &&
             (!lifecycle->run_started_recorded ||
              !lifecycle->publication_recorded)) ||
            (request->operation == ZN_DRAIN &&
             !lifecycle->quiescence_recorded)) {
            zn_acl_poison_owner_v1(lifecycle, &snapshot, request);
            return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED;
        }
        return zn_acl_commit_bridge_ack_v1(lifecycle, dispatch, &snapshot,
                                            request);
    }
    if (bridge_code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_SCRATCH_RELEASED)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_SCRATCH_RELEASED;
    if (bridge_code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST &&
        !dispatch->fault)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_STALE_REQUEST;

    zn_acl_poison_owner_v1(lifecycle, &snapshot, request);
    return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED;
}

ZnNativeArenaConvLifecycleCodeV1
zn_native_arena_conv_lifecycle_finish_v1(
    ZnNativeArenaConvLifecycleV1 *lifecycle, const ZnDispatch *dispatch)
{
    ZnNativeGraphConvBridgeCodeV2 code;

    if (!lifecycle || !lifecycle->owner || !dispatch)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ARGUMENT;
    if (lifecycle->fault || lifecycle->owner->fault || dispatch->fault)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_POISONED;
    if (lifecycle->bridge.stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ORDER;
    lifecycle->active = 0;
    lifecycle->finishing = 1;
    code = zn_native_graph_conv_bridge_finish_v2(&lifecycle->bridge, dispatch);
    lifecycle->finishing = 0;
    if (code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY)
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY;
    if (code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_SCRATCH_RELEASED) {
        lifecycle->run_started_recorded = 0;
        lifecycle->publication_recorded = 0;
        lifecycle->quiescence_recorded = 0;
        return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_SCRATCH_RELEASED;
    }
    zn_acl_poison_owner_v1(lifecycle,
                           &lifecycle->last_run_dispatch_snapshot,
                           &lifecycle->last_run_request);
    return ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FAILED;
}
