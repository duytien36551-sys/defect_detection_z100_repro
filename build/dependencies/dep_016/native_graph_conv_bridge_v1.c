#include "native_graph_conv_bridge_v1.h"

#include <string.h>

static uint64_t
zn_graph_conv_end(const ZnNativeConvEnd33 *end)
{
    return ((uint64_t)end->high << 32) | end->low;
}

static int
zn_graph_conv_ref_equal(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
zn_graph_conv_request_equal(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index &&
           a->operation == b->operation && zn_graph_conv_ref_equal(a->ref, b->ref) &&
           a->job == b->job;
}

static int
zn_graph_conv_pending_matches(const ZnDispatch *dispatch,
                              const ZnRequest *request,
                              int allow_latched_fault)
{
    if (!dispatch || !request || !dispatch->events || !dispatch->pending ||
        (!allow_latched_fault && dispatch->fault) ||
        request->event_index >= dispatch->count ||
        dispatch->cursor != request->event_index ||
        request->epoch != dispatch->epoch ||
        request->job != &dispatch->events[request->event_index] ||
        !zn_graph_conv_request_equal(request, &dispatch->request))
        return 0;
    return 1;
}

static int
zn_graph_conv_command_equal(const ZnNativeConvCommand *a,
                            const ZnNativeConvCommand *b)
{
    uint32_t words_a[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t words_b[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t i;

    if (zn_native_conv_command_encode_v1(a, words_a) != ZN_NATIVE_CONV_COMMAND_OK ||
        zn_native_conv_command_encode_v1(b, words_b) != ZN_NATIVE_CONV_COMMAND_OK)
        return 0;
    for (i = 0; i < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++i) {
        if (words_a[i] != words_b[i])
            return 0;
    }
    return 1;
}

static int
zn_graph_conv_binding_equal(const ZnNativeGraphConvBindingV1 *a,
                            const ZnNativeGraphConvBindingV1 *b)
{
    return a && b && a->dispatch_epoch == b->dispatch_epoch &&
           a->dispatch_tag == b->dispatch_tag && a->event_index == b->event_index &&
           zn_graph_conv_ref_equal(a->source_ref, b->source_ref) &&
           zn_graph_conv_ref_equal(a->destination_ref, b->destination_ref) &&
           a->source_base == b->source_base && a->source_bytes == b->source_bytes &&
           a->expected_cookie == b->expected_cookie &&
           a->expected_job_base == b->expected_job_base &&
           a->expected_token_base == b->expected_token_base &&
           a->expected_tag_base == b->expected_tag_base &&
           a->expected_tiles == b->expected_tiles &&
           memcmp(a->package_sha256, b->package_sha256, sizeof a->package_sha256) == 0 &&
           memcmp(a->checkpoint_sha256, b->checkpoint_sha256,
                  sizeof a->checkpoint_sha256) == 0 &&
           memcmp(a->graph_sha256, b->graph_sha256, sizeof a->graph_sha256) == 0 &&
           zn_graph_conv_command_equal(&a->command, &b->command);
}

static int
zn_graph_conv_range_contains(uint32_t region_begin,
                             const ZnNativeConvEnd33 *region_end,
                             uint32_t base, uint32_t bytes)
{
    uint64_t begin = base;
    uint64_t end = begin + bytes;
    uint64_t bound = zn_graph_conv_end(region_end);

    return bytes != 0 && begin >= region_begin && end <= bound &&
           end <= UINT64_C(0x100000000);
}

static int
zn_graph_conv_ranges_overlap(uint32_t a_base, uint32_t a_bytes,
                             uint32_t b_base, uint32_t b_bytes)
{
    uint64_t a_end = (uint64_t)a_base + a_bytes;
    uint64_t b_end = (uint64_t)b_base + b_bytes;
    return (uint64_t)a_base < b_end && (uint64_t)b_base < a_end;
}

static int
zn_graph_conv_binding_valid(const ZnRequest *request,
                            const ZnNativeGraphConvBindingV1 *binding)
{
    const ZnEvent *event;
    const ZnNativeConvCommand *command;
    uint32_t destination_bytes;

    if (!request || !binding || !request->job || request->operation != ZN_RUN)
        return 0;
    event = request->job;
    command = &binding->command;
    if (event->operation != ZN_CONV || event->read_count != 1 ||
        !event->has_destination || event->tile_count == 0 ||
        binding->dispatch_epoch != request->epoch ||
        binding->dispatch_tag != request->tag ||
        binding->event_index != request->event_index ||
        !zn_graph_conv_ref_equal(binding->source_ref, event->reads[0]) ||
        !zn_graph_conv_ref_equal(binding->destination_ref, event->destination.ref) ||
        binding->source_ref.generation == 0 || binding->destination_ref.generation == 0 ||
        binding->source_bytes == 0 || binding->expected_tiles != event->tile_count ||
        binding->expected_tiles > 255 ||
        memcmp(binding->package_sha256, ZN_NATIVE_GRAPH_CONV_PACKAGE_SHA256_V1,
               sizeof binding->package_sha256) != 0 ||
        memcmp(binding->checkpoint_sha256, ZN_NATIVE_GRAPH_CONV_MODEL_SHA256_V1,
               sizeof binding->checkpoint_sha256) != 0 ||
        memcmp(binding->graph_sha256, ZN_NATIVE_GRAPH_CONV_GRAPH_SHA256_V1,
               sizeof binding->graph_sha256) != 0)
        return 0;

    if (command->request_cookie != binding->expected_cookie ||
        command->epoch != request->epoch || command->event != event->event ||
        command->model_crc32 != ZN_NATIVE_CONV_MMIO_MODEL_CRC32 ||
        command->job_base != binding->expected_job_base ||
        command->token_base != binding->expected_token_base ||
        command->tag_base != binding->expected_tag_base ||
        command->source_base != binding->source_base ||
        command->source_generation != binding->source_ref.generation ||
        command->destination_base != event->destination.address ||
        command->destination_generation != binding->destination_ref.generation ||
        command->destination_base % 64u != 0 || event->destination.address % 64u != 0 ||
        event->destination.bytes == 0)
        return 0;

    destination_bytes = (uint32_t)event->destination.bytes;
    if (!zn_graph_conv_range_contains(command->source_lease_region_begin,
                                      &command->source_lease_region_end,
                                      binding->source_base, binding->source_bytes) ||
        !zn_graph_conv_range_contains(command->destination_reservation_region_begin,
                                      &command->destination_reservation_region_end,
                                      command->destination_base, destination_bytes) ||
        zn_graph_conv_ranges_overlap(binding->source_base, binding->source_bytes,
                                     command->destination_base, destination_bytes) ||
        zn_native_conv_command_validate_v1(command) != ZN_NATIVE_CONV_COMMAND_OK)
        return 0;
    return 1;
}

static int
zn_graph_conv_run_request_matches(const ZnNativeGraphConvBridgeV1 *bridge,
                                  const ZnDispatch *dispatch,
                                  const ZnRequest *request)
{
    if (!bridge || !zn_graph_conv_pending_matches(
                       dispatch, request, bridge->dispatch_failure_latched))
        return 0;
    return bridge->run_request.operation == ZN_RUN &&
           request->operation == ZN_RUN &&
           zn_graph_conv_request_equal(&bridge->run_request, request);
}

static ZnNativeGraphConvBridgeCodeV1
zn_graph_conv_latch_failure(ZnNativeGraphConvBridgeV1 *bridge,
                            ZnDispatch *dispatch, const ZnRequest *request)
{
    if (bridge && dispatch && request &&
        zn_graph_conv_pending_matches(dispatch, request,
                                      bridge->dispatch_failure_latched)) {
        bridge->dispatch_failure_latched = 1;
        (void)zn_dispatch_ack(dispatch, request->tag, request->operation,
                              ZN_ACK_FAILED);
    }
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED;
}

static ZnNativeGraphConvBridgeCodeV1
zn_graph_conv_complete_fault(ZnNativeGraphConvBridgeV1 *bridge,
                             ZnDispatch *dispatch, const ZnRequest *request,
                             ZnNativeConvDriverCodeV2 code)
{
    ZnNativeConvDriverCodeV2 ack_code;

    if (code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY ||
        code == ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY) {
        ack_code = zn_native_conv_driver_ack_v2(&bridge->driver);
        if (code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY &&
            ack_code != ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT)
            return zn_graph_conv_latch_failure(bridge, dispatch, request);
        if (code == ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY &&
            ack_code != ZN_NATIVE_CONV_DRIVER_V2_OK)
            return zn_graph_conv_latch_failure(bridge, dispatch, request);
    } else {
        return zn_graph_conv_latch_failure(bridge, dispatch, request);
    }
    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
    return zn_graph_conv_latch_failure(bridge, dispatch, request);
}

static ZnNativeGraphConvBridgeCodeV1
zn_graph_conv_finish_run(ZnNativeGraphConvBridgeV1 *bridge,
                         ZnDispatch *dispatch, const ZnRequest *request,
                         ZnNativeConvDriverCodeV2 code, int ownership_ready)
{
    ZnNativeConvDriverCodeV2 ack_code;
    int callback_code;

    if (code == ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
    if (code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY ||
        code == ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY)
        return zn_graph_conv_complete_fault(bridge, dispatch, request, code);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
        return zn_graph_conv_latch_failure(bridge, dispatch, request);
    }
    if (bridge->dispatch_failure_latched)
        return zn_graph_conv_complete_fault(
            bridge, dispatch, request, ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY);
    if (!ownership_ready)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;

    callback_code = bridge->hooks.invalidate_output(bridge->hooks.context,
                                                     &bridge->binding);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
    if (callback_code != 0) {
        ack_code = zn_native_conv_driver_ack_v2(&bridge->driver);
        if (ack_code != ZN_NATIVE_CONV_DRIVER_V2_OK)
            return zn_graph_conv_latch_failure(bridge, dispatch, request);
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
        return zn_graph_conv_latch_failure(bridge, dispatch, request);
    }

    ack_code = zn_native_conv_driver_ack_v2(&bridge->driver);
    if (ack_code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return zn_graph_conv_latch_failure(bridge, dispatch, request);
    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_PUBLISH;

    callback_code = bridge->hooks.validate_and_publish(bridge->hooks.context,
                                                       &bridge->binding);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
    if (callback_code != 0) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
        return zn_graph_conv_latch_failure(bridge, dispatch, request);
    }

    if (zn_dispatch_ack(dispatch, request->tag, request->operation, ZN_ACK_OK) != 0) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED;
    }
    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_RUN_ACKED;
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED;
}

ZnNativeGraphConvBridgeCodeV1
zn_native_graph_conv_bridge_init_v1(
    ZnNativeGraphConvBridgeV1 *bridge,
    const ZnNativeConvMmioOpsV2 *mmio,
    const ZnNativeGraphConvHooksV1 *hooks)
{
    if (!bridge || !mmio || !hooks || !hooks->check_ownership ||
        !hooks->prepare_device || !hooks->invalidate_output ||
        !hooks->validate_and_publish || !hooks->drain_ready)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ARGUMENT;
    memset(bridge, 0, sizeof *bridge);
    bridge->hooks = *hooks;
    if (zn_native_conv_driver_init_v2(&bridge->driver, mmio) !=
        ZN_NATIVE_CONV_DRIVER_V2_OK)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ARGUMENT;
    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_IDLE;
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED;
}

ZnNativeGraphConvBridgeCodeV1
zn_native_graph_conv_bridge_step_v1(
    ZnNativeGraphConvBridgeV1 *bridge, ZnDispatch *dispatch,
    const ZnRequest *request, const ZnNativeGraphConvBindingV1 *binding)
{
    ZnNativeConvDriverCodeV2 driver_code;
    int callback_code;
    int ownership_ready;

    if (!bridge || !dispatch || !request)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ARGUMENT;
    if (request->operation != ZN_RUN && request->operation != ZN_DRAIN)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_UNSUPPORTED_OPERATION;
    if (!zn_graph_conv_pending_matches(dispatch, request,
                                       bridge->dispatch_failure_latched))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST;
    if (!request->job || request->job->operation != ZN_CONV)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_UNSUPPORTED_OPERATION;

    if (request->operation == ZN_RUN) {
        if (!binding)
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_UNBOUND;
        if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_IDLE) {
            if (!zn_graph_conv_pending_matches(dispatch, request, 0))
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST;
            if (!zn_graph_conv_binding_valid(request, binding)) {
                (void)zn_graph_conv_latch_failure(bridge, dispatch, request);
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_INVALID_BINDING;
            }
            bridge->binding = *binding;
            bridge->run_request = *request;
            bridge->dispatch_failure_latched = 0;
            bridge->ownership_check_busy = 0;
            bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_PREPARED;
        } else if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_PREPARED) {
            if (!zn_graph_conv_run_request_matches(bridge, dispatch, request) ||
                !zn_graph_conv_binding_equal(&bridge->binding, binding))
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST;
        } else if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_SUBMITTED ||
                   bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_INVALIDATE ||
                   bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_PUBLISH ||
                   bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED) {
            if (!zn_graph_conv_run_request_matches(bridge, dispatch, request) ||
                (binding && !zn_graph_conv_binding_equal(&bridge->binding, binding)))
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST;
        } else {
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST;
        }

        if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_PREPARED) {
            callback_code = bridge->hooks.check_ownership(bridge->hooks.context,
                                                           request, &bridge->binding);
            if (callback_code == 1)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
            if (callback_code != 0) {
                bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
                return zn_graph_conv_latch_failure(bridge, dispatch, request);
            }
            callback_code = bridge->hooks.prepare_device(bridge->hooks.context,
                                                          &bridge->binding);
            if (callback_code == 1)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
            if (callback_code != 0) {
                bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
                return zn_graph_conv_latch_failure(bridge, dispatch, request);
            }
            driver_code = zn_native_conv_driver_submit_v2(
                &bridge->driver, &bridge->binding.command,
                bridge->binding.expected_tiles);
            if (driver_code == ZN_NATIVE_CONV_DRIVER_V2_BUSY)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
            if (driver_code != ZN_NATIVE_CONV_DRIVER_V2_OK) {
                bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
                return zn_graph_conv_latch_failure(bridge, dispatch, request);
            }
            bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_SUBMITTED;
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
        }

        if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_PUBLISH) {
            callback_code = bridge->hooks.check_ownership(bridge->hooks.context,
                                                           request, &bridge->binding);
            if (callback_code == 1)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
            if (callback_code != 0) {
                bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
                return zn_graph_conv_latch_failure(bridge, dispatch, request);
            }
            callback_code = bridge->hooks.validate_and_publish(
                bridge->hooks.context, &bridge->binding);
            if (callback_code == 1)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
            if (callback_code != 0) {
                bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
                return zn_graph_conv_latch_failure(bridge, dispatch, request);
            }
            if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                                ZN_ACK_OK) != 0) {
                bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED;
            }
            bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_RUN_ACKED;
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED;
        }

        if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED)
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED;

        callback_code = bridge->hooks.check_ownership(bridge->hooks.context,
                                                       request, &bridge->binding);
        ownership_ready = callback_code == 0;
        if (callback_code < 0 && !bridge->dispatch_failure_latched) {
            bridge->dispatch_failure_latched = 1;
            (void)zn_dispatch_ack(dispatch, request->tag, request->operation,
                                  ZN_ACK_FAILED);
            driver_code = zn_native_conv_driver_timeout_v2(&bridge->driver);
            if (driver_code == ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
            return zn_graph_conv_finish_run(bridge, dispatch, request,
                                            driver_code, 0);
        }
        if (callback_code > 0)
            bridge->ownership_check_busy = 1;
        driver_code = zn_native_conv_driver_poll_v2(&bridge->driver);
        return zn_graph_conv_finish_run(bridge, dispatch, request,
                                        driver_code, ownership_ready);
    }

    if (!zn_graph_conv_pending_matches(dispatch, request, 0) ||
        bridge->stage != ZN_NATIVE_GRAPH_CONV_STAGE_V1_RUN_ACKED ||
        request->epoch != bridge->run_request.epoch ||
        request->event_index != bridge->run_request.event_index ||
        request->job != bridge->run_request.job ||
        request->tag == bridge->run_request.tag ||
        (binding && !zn_graph_conv_binding_equal(&bridge->binding, binding)))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST;

    callback_code = bridge->hooks.check_ownership(bridge->hooks.context,
                                                   request, &bridge->binding);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
    if (callback_code != 0)
        return zn_graph_conv_latch_failure(bridge, dispatch, request);
    callback_code = bridge->hooks.drain_ready(bridge->hooks.context, request,
                                               &bridge->binding);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY;
    if (callback_code != 0)
        return zn_graph_conv_latch_failure(bridge, dispatch, request);
    if (bridge->driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(&bridge->driver))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST;
    if (zn_dispatch_ack(dispatch, request->tag, request->operation, ZN_ACK_OK) != 0) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED;
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED;
    }
    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V1_IDLE;
    bridge->dispatch_failure_latched = 0;
    bridge->ownership_check_busy = 0;
    memset(&bridge->binding, 0, sizeof bridge->binding);
    memset(&bridge->run_request, 0, sizeof bridge->run_request);
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED;
}

ZnNativeGraphConvBridgeCodeV1
zn_native_graph_conv_bridge_timeout_v1(
    ZnNativeGraphConvBridgeV1 *bridge, ZnDispatch *dispatch,
    const ZnRequest *request)
{
    ZnNativeConvDriverCodeV2 code;
    int ownership_ready;

    if (!bridge || !dispatch || !request)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ARGUMENT;
    if (bridge->stage != ZN_NATIVE_GRAPH_CONV_STAGE_V1_SUBMITTED ||
        !zn_graph_conv_run_request_matches(bridge, dispatch, request))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST;
    if (bridge->hooks.check_ownership(bridge->hooks.context, request,
                                      &bridge->binding) < 0 &&
        !bridge->dispatch_failure_latched) {
        bridge->dispatch_failure_latched = 1;
        (void)zn_dispatch_ack(dispatch, request->tag, request->operation,
                              ZN_ACK_FAILED);
    }
    code = zn_native_conv_driver_timeout_v2(&bridge->driver);
    ownership_ready = bridge->hooks.check_ownership(bridge->hooks.context,
                                                     request, &bridge->binding) == 0;
    return zn_graph_conv_finish_run(bridge, dispatch, request, code,
                                    ownership_ready);
}
