#include "native_graph_executor_v1.h"

#include <string.h>

static int
zn_nge_ref_equal_v1(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
zn_nge_request_equal_v1(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index &&
           a->operation == b->operation &&
           zn_nge_ref_equal_v1(a->ref, b->ref) && a->job == b->job;
}

static int
zn_nge_binding_equal_v1(const ZnNativeGraphConvBindingV2 *a,
                        const ZnNativeGraphConvBindingV2 *b)
{
    uint32_t words_a[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t words_b[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint8_t index;

    if (!a || !b || a->dispatch_epoch != b->dispatch_epoch ||
        a->dispatch_tag != b->dispatch_tag || a->event_index != b->event_index ||
        a->graph_read_count != b->graph_read_count ||
        a->graph_read_count > ZN_NATIVE_GRAPH_CONV_MAX_READS_V2 ||
        !zn_nge_ref_equal_v1(a->destination_ref, b->destination_ref) ||
        a->scratch.epoch != b->scratch.epoch ||
        a->scratch.generation != b->scratch.generation ||
        a->scratch.base != b->scratch.base ||
        a->scratch.bytes != b->scratch.bytes ||
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
        zn_native_conv_command_encode_v1(&a->command, words_a) !=
            ZN_NATIVE_CONV_COMMAND_OK ||
        zn_native_conv_command_encode_v1(&b->command, words_b) !=
            ZN_NATIVE_CONV_COMMAND_OK ||
        memcmp(words_a, words_b, sizeof words_a) != 0)
        return 0;
    for (index = 0; index < a->graph_read_count; ++index) {
        if (!zn_nge_ref_equal_v1(a->graph_read_refs[index],
                                 b->graph_read_refs[index]))
            return 0;
    }
    return 1;
}

static int
zn_nge_dispatch_request_valid_v1(const ZnNativeGraphExecutorV1 *executor,
                                 const ZnRequest *request)
{
    const ZnDispatch *dispatch;

    if (!executor || !request || !executor->dispatch)
        return 0;
    dispatch = executor->dispatch;
    return dispatch->events == executor->owner->events &&
           dispatch->epoch == executor->owner->epoch &&
           dispatch->count == executor->owner->event_count &&
           dispatch->pending && !dispatch->fault &&
           request->epoch == dispatch->epoch &&
           request->event_index < dispatch->count &&
           dispatch->cursor == request->event_index &&
           dispatch->phase == request->operation &&
           request->job == &dispatch->events[request->event_index] &&
           zn_nge_request_equal_v1(request, &dispatch->request);
}

static int
zn_nge_binding_matches_run_v1(const ZnNativeGraphConvBindingV2 *binding,
                              const ZnRequest *request)
{
    const ZnEvent *event;
    uint8_t index;

    if (!binding || !request || !request->job ||
        request->operation != ZN_RUN || request->job->operation != ZN_CONV ||
        !request->job->has_destination || request->job->read_count >
            ZN_NATIVE_GRAPH_CONV_MAX_READS_V2)
        return 0;
    event = request->job;
    if (binding->dispatch_epoch != request->epoch ||
        binding->dispatch_tag != request->tag ||
        binding->event_index != request->event_index ||
        binding->graph_read_count != event->read_count ||
        !zn_nge_ref_equal_v1(binding->destination_ref,
                             event->destination.ref) ||
        binding->expected_tiles != event->tile_count ||
        binding->expected_cookie != binding->command.request_cookie ||
        binding->command.epoch != request->epoch ||
        binding->command.event != event->event ||
        binding->command.destination_base != event->destination.address ||
        binding->command.destination_generation !=
            event->destination.ref.generation ||
        !binding->scratch.generation ||
        binding->scratch.epoch != request->epoch ||
        binding->source_span.base != binding->scratch.base ||
        !binding->source_span.bytes ||
        binding->source_span.bytes > binding->scratch.bytes ||
        binding->command.source_base != binding->source_span.base ||
        binding->command.source_generation != binding->scratch.generation)
        return 0;
    for (index = 0; index < event->read_count; ++index) {
        if (!zn_nge_ref_equal_v1(binding->graph_read_refs[index],
                                 event->reads[index]))
            return 0;
    }
    return 1;
}

static int
zn_nge_binding_matches_event_v1(const ZnNativeGraphExecutorV1 *executor,
                                const ZnRequest *request)
{
    const ZnRequest *run;

    if (!executor || !executor->binding_valid || !request ||
        !request->job || request->job->read_count >
            ZN_NATIVE_GRAPH_CONV_MAX_READS_V2 ||
        !executor->pending_valid || !executor->pending_request.job ||
        !executor->binding_run_request.job ||
        !zn_nge_binding_equal_v1(&executor->binding,
                                 &executor->binding_snapshot))
        return 0;
    run = &executor->binding_run_request;
    if (run->operation != ZN_RUN || run->epoch != request->epoch ||
        run->event_index != request->event_index ||
        run->job != request->job ||
        executor->binding.dispatch_epoch != run->epoch ||
        executor->binding.dispatch_tag != run->tag ||
        executor->binding.event_index != run->event_index ||
        executor->binding.graph_read_count != request->job->read_count ||
        !zn_nge_ref_equal_v1(executor->binding.destination_ref,
                             request->job->destination.ref))
        return 0;
    return 1;
}

static ZnNativeGraphExecutorCodeV1
zn_nge_latch_v1(ZnNativeGraphExecutorV1 *executor,
                ZnNativeGraphExecutorCodeV1 code)
{
    if (!executor)
        return ZN_NATIVE_GRAPH_EXECUTOR_V1_ARGUMENT;
    if (executor->pending_valid &&
        zn_nge_dispatch_request_valid_v1(executor,
                                         &executor->pending_request))
        (void)zn_native_arena_owner_fail_v1(
            executor->owner, executor->dispatch, &executor->pending_request);
    executor->owner->fault = 1;
    executor->dispatch->fault = 1;
    executor->terminal = 1;
    executor->terminal_code = code;
    return code;
}

static ZnNativeGraphExecutorCodeV1
zn_nge_finish_v1(ZnNativeGraphExecutorV1 *executor)
{
    ZnNativeArenaConvLifecycleCodeV1 code;

    if (!executor->binding_valid ||
        executor->conv_lifecycle->bridge.stage !=
            ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED ||
        !zn_nge_binding_equal_v1(
            &executor->binding,
            &executor->conv_lifecycle->bridge.binding))
        return zn_nge_latch_v1(executor,
                               ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST);

    executor->finish_pending = 1;
    code = zn_native_arena_conv_lifecycle_finish_v1(
        executor->conv_lifecycle, executor->dispatch);
    if (code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY)
        return ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY;
    if (code != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_SCRATCH_RELEASED)
        return zn_nge_latch_v1(
            executor, code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_POISONED ?
                ZN_NATIVE_GRAPH_EXECUTOR_V1_POISONED :
                ZN_NATIVE_GRAPH_EXECUTOR_V1_FAILED);

    executor->finish_pending = 0;
    executor->binding_valid = 0;
    memset(&executor->binding, 0, sizeof executor->binding);
    memset(&executor->binding_snapshot, 0,
           sizeof executor->binding_snapshot);
    memset(&executor->binding_run_request, 0,
           sizeof executor->binding_run_request);
    return ZN_NATIVE_GRAPH_EXECUTOR_V1_SCRATCH_RELEASED;
}

ZnNativeGraphExecutorCodeV1
zn_native_graph_executor_v1_init(
    ZnNativeGraphExecutorV1 *executor, ZnNativeArenaOwnerV1 *owner,
    ZnDispatch *dispatch, ZnNativeArenaConvLifecycleV1 *conv_lifecycle,
    ZnNativeArenaNonConvLifecycleV1 *nonconv_lifecycle,
    ZnNativeGraphExecutorResolveConvV1 resolve_conv, void *resolve_context)
{
    if (!executor || !owner || !dispatch || !conv_lifecycle ||
        !nonconv_lifecycle || !resolve_conv)
        return ZN_NATIVE_GRAPH_EXECUTOR_V1_ARGUMENT;
    if (!owner->initialized || owner->fault || dispatch->fault ||
        dispatch->events != owner->events || dispatch->count != owner->event_count ||
        dispatch->epoch != owner->epoch || conv_lifecycle->owner != owner ||
        nonconv_lifecycle->owner != owner || conv_lifecycle->fault ||
        nonconv_lifecycle->fault || conv_lifecycle->active ||
        nonconv_lifecycle->active ||
        conv_lifecycle->bridge.stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_IDLE ||
        conv_lifecycle->bridge.driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(
            &conv_lifecycle->bridge.driver))
        return ZN_NATIVE_GRAPH_EXECUTOR_V1_INVALID;

    memset(executor, 0, sizeof *executor);
    executor->owner = owner;
    executor->dispatch = dispatch;
    executor->conv_lifecycle = conv_lifecycle;
    executor->nonconv_lifecycle = nonconv_lifecycle;
    executor->resolve_conv = resolve_conv;
    executor->resolve_context = resolve_context;
    return ZN_NATIVE_GRAPH_EXECUTOR_V1_ACKED;
}

ZnNativeGraphExecutorCodeV1
zn_native_graph_executor_v1_step(ZnNativeGraphExecutorV1 *executor)
{
    ZnNativeGraphExecutorCodeV1 result;
    ZnNativeArenaConvLifecycleCodeV1 conv_code;
    ZnNativeArenaNonConvLifecycleCodeV1 nonconv_code;
    const ZnNativeGraphConvBindingV2 *binding = NULL;
    ZnRequest request;
    int next_code;

    if (!executor || !executor->owner || !executor->dispatch ||
        !executor->conv_lifecycle || !executor->nonconv_lifecycle ||
        !executor->resolve_conv)
        return ZN_NATIVE_GRAPH_EXECUTOR_V1_ARGUMENT;
    if (executor->terminal)
        return (ZnNativeGraphExecutorCodeV1)executor->terminal_code;
    if (executor->complete)
        return ZN_NATIVE_GRAPH_EXECUTOR_V1_COMPLETE;
    if (executor->owner->fault || executor->dispatch->fault ||
        executor->conv_lifecycle->fault || executor->nonconv_lifecycle->fault)
        return zn_nge_latch_v1(executor,
                               ZN_NATIVE_GRAPH_EXECUTOR_V1_POISONED);

    if (executor->finish_pending ||
        executor->conv_lifecycle->bridge.stage ==
            ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED)
        return zn_nge_finish_v1(executor);

    if (executor->pending_valid) {
        if (!zn_nge_dispatch_request_valid_v1(executor,
                                             &executor->pending_request))
            return zn_nge_latch_v1(
                executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST);
        request = executor->pending_request;
    } else {
        next_code = zn_dispatch_next(executor->dispatch, &request);
        if (next_code < 0)
            return zn_nge_latch_v1(
                executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_POISONED);
        if (next_code == 0) {
            ZnNativeArenaOwnerCodeV1 owner_code =
                zn_native_arena_owner_verify_complete_v1(
                    executor->owner, executor->dispatch);
            if (owner_code == ZN_NATIVE_ARENA_OWNER_V1_BUSY)
                return ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY;
            if (owner_code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
                return zn_nge_latch_v1(
                    executor, owner_code == ZN_NATIVE_ARENA_OWNER_V1_POISONED ?
                        ZN_NATIVE_GRAPH_EXECUTOR_V1_POISONED :
                        ZN_NATIVE_GRAPH_EXECUTOR_V1_FAILED);
            executor->complete = 1;
            return ZN_NATIVE_GRAPH_EXECUTOR_V1_COMPLETE;
        }
        executor->pending_request = request;
        executor->pending_valid = 1;
    }

    if (!zn_nge_dispatch_request_valid_v1(executor, &request))
        return zn_nge_latch_v1(
            executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST);

    if (request.job->operation == ZN_CONV) {
        if (request.operation == ZN_RUN) {
            if (executor->binding_valid) {
                if (!zn_nge_binding_matches_event_v1(executor, &request))
                    return zn_nge_latch_v1(
                        executor,
                        ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST);
            } else {
                ZnNativeGraphConvBindingV2 candidate;
                int resolve_code;

                memset(&candidate, 0, sizeof candidate);
                resolve_code = executor->resolve_conv(
                    executor->resolve_context, &request, &candidate);
                if (resolve_code == ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_BUSY_V1)
                    return ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY;
                if (resolve_code ==
                    ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_UNSUPPORTED_V1)
                    return zn_nge_latch_v1(
                        executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_UNSUPPORTED);
                if (resolve_code != ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_READY_V1)
                    return zn_nge_latch_v1(
                        executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_FAILED);
                if (!zn_nge_binding_matches_run_v1(&candidate, &request))
                    return zn_nge_latch_v1(
                        executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_INVALID);
                memcpy(&executor->binding, &candidate,
                       sizeof executor->binding);
                memcpy(&executor->binding_snapshot, &candidate,
                       sizeof executor->binding_snapshot);
                executor->binding_run_request = request;
                executor->binding_valid = 1;
            }
            binding = &executor->binding;
        } else if (request.operation == ZN_DRAIN ||
                   request.operation == ZN_RETURN) {
            if (!zn_nge_binding_matches_event_v1(executor, &request))
                return zn_nge_latch_v1(
                    executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST);
            binding = &executor->binding;
        }

        conv_code = zn_native_arena_conv_lifecycle_step_v1(
            executor->conv_lifecycle, executor->dispatch, &request, binding);
        if (conv_code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_BUSY)
            return ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY;
        if (conv_code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_FINISH_REQUIRED) {
            executor->finish_pending = 1;
            return ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY;
        }
        if (conv_code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_UNSUPPORTED)
            return zn_nge_latch_v1(
                executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_UNSUPPORTED);
        if (conv_code != ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
            return zn_nge_latch_v1(
                executor, conv_code ==
                    ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_STALE_REQUEST ?
                    ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST :
                    conv_code == ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_POISONED ?
                    ZN_NATIVE_GRAPH_EXECUTOR_V1_POISONED :
                    ZN_NATIVE_GRAPH_EXECUTOR_V1_FAILED);
    } else {
        nonconv_code = zn_native_arena_nonconv_lifecycle_step_v1(
            executor->nonconv_lifecycle, executor->dispatch, &request);
        if (nonconv_code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_BUSY)
            return ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY;
        if (nonconv_code == ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_UNSUPPORTED)
            return zn_nge_latch_v1(
                executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_UNSUPPORTED);
        if (nonconv_code != ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED)
            return zn_nge_latch_v1(
                executor, nonconv_code ==
                    ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_STALE_REQUEST ?
                    ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST :
                    nonconv_code ==
                        ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_POISONED ?
                    ZN_NATIVE_GRAPH_EXECUTOR_V1_POISONED :
                    ZN_NATIVE_GRAPH_EXECUTOR_V1_FAILED);
    }

    if (executor->dispatch->pending)
        return zn_nge_latch_v1(
            executor, ZN_NATIVE_GRAPH_EXECUTOR_V1_FAILED);
    memset(&executor->pending_request, 0, sizeof executor->pending_request);
    executor->pending_valid = 0;
    result = ZN_NATIVE_GRAPH_EXECUTOR_V1_ACKED;
    return result;
}

ZnNativeGraphExecutorCodeV1
zn_native_graph_executor_v1_timeout(ZnNativeGraphExecutorV1 *executor)
{
    if (!executor || !executor->owner || !executor->dispatch)
        return ZN_NATIVE_GRAPH_EXECUTOR_V1_ARGUMENT;
    if (executor->terminal)
        return (ZnNativeGraphExecutorCodeV1)executor->terminal_code;
    if (executor->complete)
        return ZN_NATIVE_GRAPH_EXECUTOR_V1_INVALID;

    if (executor->pending_valid &&
        zn_nge_dispatch_request_valid_v1(executor,
                                         &executor->pending_request)) {
        (void)zn_native_arena_owner_fail_v1(
            executor->owner, executor->dispatch, &executor->pending_request);
    } else {
        executor->owner->fault = 1;
        executor->dispatch->fault = 1;
    }
    executor->owner->fault = 1;
    executor->dispatch->fault = 1;
    executor->terminal = 1;
    executor->terminal_code = ZN_NATIVE_GRAPH_EXECUTOR_V1_TIMED_OUT;
    return ZN_NATIVE_GRAPH_EXECUTOR_V1_TIMED_OUT;
}
