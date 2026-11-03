#include "native_graph_conv_bridge_v2.h"

#include <string.h>

static uint64_t
zn_graph_conv_end_v2(const ZnNativeConvEnd33 *end)
{
    return ((uint64_t)end->high << 32) | end->low;
}

static uint64_t
zn_graph_conv_scratch_end_v2(const ZnNativeGraphScratchLeaseV2 *scratch)
{
    return (uint64_t)scratch->base + scratch->bytes;
}

static int
zn_graph_conv_ref_equal_v2(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static int
zn_graph_conv_request_equal_v2(const ZnRequest *a, const ZnRequest *b)
{
    return a && b && a->epoch == b->epoch && a->tag == b->tag &&
           a->event_index == b->event_index &&
           a->operation == b->operation &&
           zn_graph_conv_ref_equal_v2(a->ref, b->ref) && a->job == b->job;
}

static int
zn_graph_conv_pending_matches_v2(const ZnDispatch *dispatch,
                                 const ZnRequest *request,
                                 int allow_latched_fault)
{
    if (!dispatch || !request || !dispatch->events || !dispatch->pending ||
        (!allow_latched_fault && dispatch->fault) ||
        request->event_index >= dispatch->count ||
        dispatch->cursor != request->event_index ||
        request->epoch != dispatch->epoch ||
        request->job != &dispatch->events[request->event_index] ||
        !zn_graph_conv_request_equal_v2(request, &dispatch->request))
        return 0;
    return 1;
}

static int
zn_graph_conv_command_equal_v2(const ZnNativeConvCommand *a,
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
zn_graph_conv_binding_equal_v2(const ZnNativeGraphConvBindingV2 *a,
                               const ZnNativeGraphConvBindingV2 *b)
{
    uint8_t i;

    if (!a || !b || a->dispatch_epoch != b->dispatch_epoch ||
        a->dispatch_tag != b->dispatch_tag || a->event_index != b->event_index ||
        a->graph_read_count != b->graph_read_count ||
        !zn_graph_conv_ref_equal_v2(a->destination_ref, b->destination_ref) ||
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
        !zn_graph_conv_command_equal_v2(&a->command, &b->command))
        return 0;

    for (i = 0; i < a->graph_read_count; ++i) {
        if (!zn_graph_conv_ref_equal_v2(a->graph_read_refs[i], b->graph_read_refs[i]))
            return 0;
    }
    return 1;
}

static int
zn_graph_conv_range_contains_v2(uint32_t region_begin,
                                uint64_t region_end,
                                uint32_t base, uint32_t bytes)
{
    uint64_t begin = base;
    uint64_t end = begin + bytes;

    return bytes != 0 && begin >= region_begin && end <= region_end &&
           end <= UINT64_C(0x100000000);
}

static int
zn_graph_conv_ranges_overlap_v2(uint64_t a_begin, uint64_t a_end,
                                uint64_t b_begin, uint64_t b_end)
{
    return a_begin < b_end && b_begin < a_end;
}

static int
zn_graph_conv_binding_valid_v2(const ZnRequest *request,
                               const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnEvent *event;
    const ZnNativeConvCommand *command;
    uint64_t scratch_end;
    uint64_t destination_reservation_end;
    uint64_t parameter_payload_end;
    uint8_t i;

    if (!request || !binding || !request->job || request->operation != ZN_RUN)
        return 0;
    event = request->job;
    command = &binding->command;
    if (event->operation != ZN_CONV || event->read_count == 0 ||
        event->read_count > ZN_NATIVE_GRAPH_CONV_MAX_READS_V2 ||
        !event->has_destination || event->tile_count == 0 ||
        binding->dispatch_epoch != request->epoch ||
        binding->dispatch_tag != request->tag ||
        binding->event_index != request->event_index ||
        binding->graph_read_count != event->read_count ||
        !zn_graph_conv_ref_equal_v2(binding->destination_ref,
                                    event->destination.ref) ||
        binding->destination_ref.generation == 0 ||
        binding->scratch.epoch != request->epoch ||
        binding->scratch.generation == 0 || binding->scratch.bytes == 0 ||
        (binding->scratch.base & UINT32_C(0x3f)) != 0 ||
        binding->source_span.base != binding->scratch.base ||
        binding->source_span.bytes == 0 ||
        binding->source_span.bytes > binding->scratch.bytes ||
        binding->source_span.base != command->source_base ||
        binding->expected_tiles != event->tile_count ||
        binding->expected_tiles > 255 ||
        memcmp(binding->package_sha256, ZN_NATIVE_GRAPH_CONV_PACKAGE_SHA256_V2,
               sizeof binding->package_sha256) != 0 ||
        memcmp(binding->checkpoint_sha256, ZN_NATIVE_GRAPH_CONV_MODEL_SHA256_V2,
               sizeof binding->checkpoint_sha256) != 0 ||
        memcmp(binding->graph_sha256, ZN_NATIVE_GRAPH_CONV_GRAPH_SHA256_V2,
               sizeof binding->graph_sha256) != 0)
        return 0;

    for (i = 0; i < event->read_count; ++i) {
        if (!zn_graph_conv_ref_equal_v2(binding->graph_read_refs[i], event->reads[i]) ||
            binding->graph_read_refs[i].generation == 0)
            return 0;
    }

    scratch_end = zn_graph_conv_scratch_end_v2(&binding->scratch);
    if (scratch_end > UINT64_C(0x100000000) ||
        command->request_cookie != binding->expected_cookie ||
        command->epoch != request->epoch || command->event != event->event ||
        command->model_crc32 != ZN_NATIVE_CONV_MMIO_MODEL_CRC32 ||
        command->job_base != binding->expected_job_base ||
        command->token_base != binding->expected_token_base ||
        command->tag_base != binding->expected_tag_base ||
        command->source_generation != binding->scratch.generation ||
        command->source_lease_region_begin != binding->scratch.base ||
        zn_graph_conv_end_v2(&command->source_lease_region_end) != scratch_end ||
        command->destination_base != event->destination.address ||
        command->destination_generation != binding->destination_ref.generation ||
        event->destination.bytes == 0 ||
        !zn_graph_conv_range_contains_v2(binding->scratch.base, scratch_end,
                                         binding->source_span.base,
                                         binding->source_span.bytes))
        return 0;

    destination_reservation_end =
        zn_graph_conv_end_v2(&command->destination_reservation_region_end);
    parameter_payload_end = zn_graph_conv_end_v2(&command->parameter_payload_end);
    if (!zn_graph_conv_range_contains_v2(
            command->destination_reservation_region_begin,
            destination_reservation_end, event->destination.address,
            event->destination.bytes) ||
        zn_graph_conv_ranges_overlap_v2(
            binding->scratch.base, scratch_end,
            command->destination_reservation_region_begin,
            destination_reservation_end) ||
        zn_graph_conv_ranges_overlap_v2(
            binding->scratch.base, scratch_end,
            command->parameter_payload_begin, parameter_payload_end) ||
        zn_native_conv_command_validate_v1(command) != ZN_NATIVE_CONV_COMMAND_OK)
        return 0;
    return 1;
}

static int
zn_graph_conv_run_request_matches_v2(const ZnNativeGraphConvBridgeV2 *bridge,
                                     const ZnDispatch *dispatch,
                                     const ZnRequest *request)
{
    if (!bridge || !zn_graph_conv_pending_matches_v2(
                       dispatch, request, bridge->dispatch_failure_latched))
        return 0;
    return bridge->run_request.operation == ZN_RUN &&
           request->operation == ZN_RUN &&
           zn_graph_conv_request_equal_v2(&bridge->run_request, request);
}

static int
zn_graph_conv_followup_matches_v2(const ZnNativeGraphConvBridgeV2 *bridge,
                                 const ZnDispatch *dispatch,
                                 const ZnRequest *request, uint8_t operation)
{
    if (!bridge || !zn_graph_conv_pending_matches_v2(dispatch, request, 0) ||
        bridge->run_request.operation != ZN_RUN ||
        request->operation != operation ||
        request->epoch != bridge->run_request.epoch ||
        request->event_index != bridge->run_request.event_index ||
        request->job != bridge->run_request.job ||
        request->tag == bridge->run_request.tag)
        return 0;
    return 1;
}

static ZnNativeGraphConvBridgeCodeV2
zn_graph_conv_latch_failure_v2(ZnNativeGraphConvBridgeV2 *bridge,
                               ZnDispatch *dispatch,
                               const ZnRequest *request)
{
    if (bridge && dispatch && request &&
        zn_graph_conv_pending_matches_v2(dispatch, request,
                                        bridge->dispatch_failure_latched)) {
        bridge->dispatch_failure_latched = 1;
        (void)zn_dispatch_ack(dispatch, request->tag, request->operation,
                              ZN_ACK_FAILED);
    }
    if (bridge)
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED;
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED;
}

static ZnNativeGraphConvBridgeCodeV2
zn_graph_conv_publish_v2(ZnNativeGraphConvBridgeV2 *bridge,
                         ZnDispatch *dispatch, const ZnRequest *request)
{
    int callback_code;

    callback_code = bridge->hooks.check_leases(bridge->hooks.context, request,
                                                &bridge->binding);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
    if (callback_code != 0)
        return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);

    callback_code = bridge->hooks.validate_and_publish(bridge->hooks.context,
                                                         &bridge->binding);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
    if (callback_code != 0)
        return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);

    if (zn_dispatch_ack(dispatch, request->tag, request->operation, ZN_ACK_OK) != 0) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED;
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED;
    }
    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_RUN_ACKED;
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED;
}

static ZnNativeGraphConvBridgeCodeV2
zn_graph_conv_finish_run_v2(ZnNativeGraphConvBridgeV2 *bridge,
                            ZnDispatch *dispatch, const ZnRequest *request,
                            ZnNativeConvDriverCodeV2 code, int ownership_ready)
{
    ZnNativeConvDriverCodeV2 ack_code;
    int callback_code;

    if (code == ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
    if (code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY ||
        code == ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY) {
        ack_code = zn_native_conv_driver_ack_v2(&bridge->driver);
        if (code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY &&
            ack_code != ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT)
            return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
        if (code == ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY &&
            ack_code != ZN_NATIVE_CONV_DRIVER_V2_OK)
            return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
        return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
    }
    if (code != ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED;
        return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
    }

    if (bridge->dispatch_failure_latched) {
        ack_code = zn_native_conv_driver_ack_v2(&bridge->driver);
        if (ack_code != ZN_NATIVE_CONV_DRIVER_V2_OK)
            return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
        return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
    }
    if (!ownership_ready)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;

    callback_code = bridge->hooks.invalidate_output(bridge->hooks.context,
                                                     &bridge->binding);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
    if (callback_code != 0) {
        ack_code = zn_native_conv_driver_ack_v2(&bridge->driver);
        if (ack_code != ZN_NATIVE_CONV_DRIVER_V2_OK)
            return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
        return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
    }

    ack_code = zn_native_conv_driver_ack_v2(&bridge->driver);
    if (ack_code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_PUBLISH;
    return zn_graph_conv_publish_v2(bridge, dispatch, request);
}

ZnNativeGraphConvBridgeCodeV2
zn_native_graph_conv_bridge_init_v2(
    ZnNativeGraphConvBridgeV2 *bridge,
    const ZnNativeConvMmioOpsV2 *mmio,
    const ZnNativeGraphConvHooksV2 *hooks)
{
    if (!bridge || !mmio || !hooks || !hooks->check_leases ||
        !hooks->convert_views || !hooks->clean_source ||
        !hooks->check_source_ready || !hooks->invalidate_output ||
        !hooks->validate_and_publish || !hooks->drain_ready ||
        !hooks->return_graph_read || !hooks->release_scratch)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ARGUMENT;
    memset(bridge, 0, sizeof *bridge);
    bridge->hooks = *hooks;
    if (zn_native_conv_driver_init_v2(&bridge->driver, mmio) !=
        ZN_NATIVE_CONV_DRIVER_V2_OK)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ARGUMENT;
    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_IDLE;
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED;
}

ZnNativeGraphConvBridgeCodeV2
zn_native_graph_conv_bridge_step_v2(
    ZnNativeGraphConvBridgeV2 *bridge, ZnDispatch *dispatch,
    const ZnRequest *request, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeConvDriverCodeV2 driver_code;
    ZnNativeGraphConvBridgeCodeV2 bridge_code;
    int callback_code;
    int ownership_ready;

    if (!bridge || !dispatch || !request)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ARGUMENT;

    if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED) {
        if (!zn_graph_conv_pending_matches_v2(dispatch, request, 0))
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
        bridge_code = zn_native_graph_conv_bridge_finish_v2(bridge, dispatch);
        return bridge_code;
    }

    if (request->operation != ZN_RUN && request->operation != ZN_DRAIN &&
        request->operation != ZN_RETURN)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_UNSUPPORTED_OPERATION;
    if (!zn_graph_conv_pending_matches_v2(dispatch, request,
                                         bridge->dispatch_failure_latched))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
    if (!request->job || request->job->operation != ZN_CONV)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_UNSUPPORTED_OPERATION;

    if (request->operation == ZN_RUN) {
        if (!binding)
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_UNBOUND;
        if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_IDLE) {
            if (!zn_graph_conv_pending_matches_v2(dispatch, request, 0))
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
            if (!zn_graph_conv_binding_valid_v2(request, binding)) {
                (void)zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_INVALID_BINDING;
            }
            bridge->binding = *binding;
            bridge->run_request = *request;
            bridge->dispatch_failure_latched = 0;
            bridge->converted = 0;
            bridge->source_clean = 0;
            bridge->return_cursor = 0;
            bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING;
        } else if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING) {
            if (!zn_graph_conv_run_request_matches_v2(bridge, dispatch, request) ||
                !zn_graph_conv_binding_equal_v2(&bridge->binding, binding))
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
        } else if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED ||
                   bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_PUBLISH ||
                   bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED) {
            if (!zn_graph_conv_run_request_matches_v2(bridge, dispatch, request) ||
                (binding &&
                 !zn_graph_conv_binding_equal_v2(&bridge->binding, binding)))
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
        } else {
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
        }

        if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_PREPARING) {
            callback_code = bridge->hooks.check_leases(bridge->hooks.context,
                                                        request, &bridge->binding);
            if (callback_code == 1)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
            if (callback_code != 0)
                return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);

            if (!bridge->converted) {
                callback_code = bridge->hooks.convert_views(bridge->hooks.context,
                                                              request,
                                                              &bridge->binding);
                if (callback_code == 1)
                    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
                if (callback_code != 0)
                    return zn_graph_conv_latch_failure_v2(bridge, dispatch,
                                                          request);
                bridge->converted = 1;
            }
            if (!bridge->source_clean) {
                callback_code = bridge->hooks.clean_source(bridge->hooks.context,
                                                             &bridge->binding);
                if (callback_code == 1)
                    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
                if (callback_code != 0)
                    return zn_graph_conv_latch_failure_v2(bridge, dispatch,
                                                          request);
                bridge->source_clean = 1;
            }
            callback_code = bridge->hooks.check_source_ready(
                bridge->hooks.context, request, &bridge->binding);
            if (callback_code == 1)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
            if (callback_code != 0)
                return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);

            driver_code = zn_native_conv_driver_submit_v2(
                &bridge->driver, &bridge->binding.command,
                bridge->binding.expected_tiles);
            if (driver_code == ZN_NATIVE_CONV_DRIVER_V2_BUSY)
                return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
            if (driver_code != ZN_NATIVE_CONV_DRIVER_V2_OK)
                return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
            bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED;
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
        }

        if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_PUBLISH)
            return zn_graph_conv_publish_v2(bridge, dispatch, request);
        if (bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED)
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED;

        callback_code = bridge->hooks.check_leases(bridge->hooks.context,
                                                    request, &bridge->binding);
        ownership_ready = callback_code == 0;
        if (callback_code < 0 && !bridge->dispatch_failure_latched) {
            bridge->dispatch_failure_latched = 1;
            (void)zn_dispatch_ack(dispatch, request->tag, request->operation,
                                  ZN_ACK_FAILED);
            driver_code = zn_native_conv_driver_timeout_v2(&bridge->driver);
            return zn_graph_conv_finish_run_v2(bridge, dispatch, request,
                                                driver_code, 0);
        }
        driver_code = zn_native_conv_driver_poll_v2(&bridge->driver);
        return zn_graph_conv_finish_run_v2(bridge, dispatch, request,
                                            driver_code, ownership_ready);
    }

    if (request->operation == ZN_DRAIN) {
        if (!zn_graph_conv_followup_matches_v2(bridge, dispatch, request,
                                               ZN_DRAIN) ||
            bridge->stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_RUN_ACKED ||
            (binding &&
             !zn_graph_conv_binding_equal_v2(&bridge->binding, binding)))
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;

        callback_code = bridge->hooks.check_leases(bridge->hooks.context,
                                                    request, &bridge->binding);
        if (callback_code == 1)
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
        if (callback_code != 0)
            return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
        callback_code = bridge->hooks.drain_ready(bridge->hooks.context, request,
                                                   &bridge->binding);
        if (callback_code == 1)
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
        if (callback_code != 0)
            return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
        if (bridge->driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
            zn_native_conv_driver_ownership_held_v2(&bridge->driver))
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0) {
            bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED;
            return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED;
        }
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_DRAIN_ACKED;
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED;
    }

    if (!zn_graph_conv_followup_matches_v2(bridge, dispatch, request,
                                           ZN_RETURN) ||
        bridge->stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_DRAIN_ACKED ||
        bridge->return_cursor >= bridge->binding.graph_read_count ||
        !zn_graph_conv_ref_equal_v2(
            request->ref, bridge->binding.graph_read_refs[bridge->return_cursor]) ||
        (binding &&
         !zn_graph_conv_binding_equal_v2(&bridge->binding, binding)))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;

    if (bridge->return_request.tag != 0 &&
        !zn_graph_conv_request_equal_v2(&bridge->return_request, request))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
    if (bridge->return_request.tag == 0)
        bridge->return_request = *request;
    callback_code = bridge->hooks.return_graph_read(
        bridge->hooks.context, request, &bridge->binding, bridge->return_cursor);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
    if (callback_code != 0)
        return zn_graph_conv_latch_failure_v2(bridge, dispatch, request);
    if (zn_dispatch_ack(dispatch, request->tag, request->operation, ZN_ACK_OK) != 0) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED;
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED;
    }
    ++bridge->return_cursor;
    if (bridge->return_cursor == bridge->binding.graph_read_count) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED;
    } else {
        memset(&bridge->return_request, 0, sizeof bridge->return_request);
    }
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED;
}

ZnNativeGraphConvBridgeCodeV2
zn_native_graph_conv_bridge_finish_v2(
    ZnNativeGraphConvBridgeV2 *bridge, const ZnDispatch *dispatch)
{
    uint32_t expected_next_tag;
    uint32_t last_return_tag;
    int may_finish = 0;
    int callback_code;

    if (!bridge || !dispatch)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ARGUMENT;
    if (bridge->stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED ||
        bridge->return_cursor != bridge->binding.graph_read_count ||
        bridge->return_request.tag == 0 ||
        bridge->return_request.operation != ZN_RETURN ||
        dispatch->epoch != bridge->run_request.epoch ||
        !dispatch->events || bridge->run_request.event_index >= dispatch->count ||
        bridge->run_request.job != &dispatch->events[bridge->run_request.event_index])
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;
    if (dispatch->fault || bridge->driver.state != ZN_NATIVE_CONV_STATE_V2_IDLE ||
        zn_native_conv_driver_ownership_held_v2(&bridge->driver))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED;

    last_return_tag = bridge->return_request.tag;
    expected_next_tag = last_return_tag + 1u;
    if (dispatch->done) {
        may_finish = !dispatch->pending && dispatch->cursor == dispatch->count &&
                     dispatch->next_tag == expected_next_tag;
    } else if (dispatch->pending) {
        const ZnRequest *next = &dispatch->request;
        may_finish = dispatch->cursor < dispatch->count &&
                     next->epoch == dispatch->epoch &&
                     next->tag == expected_next_tag &&
                     next->event_index == dispatch->cursor &&
                     next->job == &dispatch->events[dispatch->cursor] &&
                     next->operation == dispatch->phase &&
                     dispatch->next_tag == expected_next_tag + 1u &&
                     (dispatch->cursor > bridge->run_request.event_index ||
                      (dispatch->cursor == bridge->run_request.event_index &&
                       next->operation == ZN_RETIRE &&
                       next->job == bridge->run_request.job));
    } else {
        may_finish = dispatch->cursor == bridge->run_request.event_index &&
                     dispatch->phase == ZN_RETURN &&
                     dispatch->index == bridge->binding.graph_read_count &&
                     dispatch->next_tag == expected_next_tag;
    }
    if (!may_finish)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;

    callback_code = bridge->hooks.release_scratch(bridge->hooks.context,
                                                   &bridge->binding);
    if (callback_code == 1)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY;
    if (callback_code != 0) {
        bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_POISONED;
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED;
    }

    bridge->stage = ZN_NATIVE_GRAPH_CONV_STAGE_V2_IDLE;
    bridge->dispatch_failure_latched = 0;
    bridge->converted = 0;
    bridge->source_clean = 0;
    bridge->return_cursor = 0;
    memset(&bridge->binding, 0, sizeof bridge->binding);
    memset(&bridge->run_request, 0, sizeof bridge->run_request);
    memset(&bridge->return_request, 0, sizeof bridge->return_request);
    return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_SCRATCH_RELEASED;
}

ZnNativeGraphConvBridgeCodeV2
zn_native_graph_conv_bridge_timeout_v2(
    ZnNativeGraphConvBridgeV2 *bridge, ZnDispatch *dispatch,
    const ZnRequest *request)
{
    ZnNativeConvDriverCodeV2 code;
    int ownership_ready;
    int callback_code;

    if (!bridge || !dispatch || !request)
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ARGUMENT;
    if (bridge->stage != ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED ||
        !zn_graph_conv_run_request_matches_v2(bridge, dispatch, request))
        return ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST;

    callback_code = bridge->hooks.check_leases(bridge->hooks.context, request,
                                                &bridge->binding);
    if (callback_code < 0 && !bridge->dispatch_failure_latched) {
        bridge->dispatch_failure_latched = 1;
        (void)zn_dispatch_ack(dispatch, request->tag, request->operation,
                              ZN_ACK_FAILED);
    }
    code = zn_native_conv_driver_timeout_v2(&bridge->driver);
    ownership_ready = callback_code == 0;
    return zn_graph_conv_finish_run_v2(bridge, dispatch, request, code,
                                        ownership_ready);
}
