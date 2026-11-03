#include "native_direct_bindings_v1.h"
#include "native_graph_conv_bridge_v1.h"
#include "native_conv_mmio_v1.h"
#include "native_dispatch.h"
#include "graph_plan.h"

#include <stdio.h>
#include <string.h>

enum { RESULT_WORDS = 10, SHADOW_WORDS = 27, WRITE_CAPACITY = 64 };

typedef struct DirectBridgeMmio {
    uint32_t status;
    uint32_t bridge_error;
    uint32_t fault_code;
    uint32_t shadow[SHADOW_WORDS];
    uint32_t result[RESULT_WORDS];
    uint32_t write_offsets[WRITE_CAPACITY];
    uint32_t write_values[WRITE_CAPACITY];
    uint32_t expected_tiles;
    unsigned int write_count;
    unsigned int shadow_write_count;
    unsigned int start_count;
    unsigned int abort_count;
    unsigned int cancel_count;
    unsigned int ack_count;
    unsigned int poll_count;
    unsigned int delay_polls;
    unsigned int result_fault_word;
    uint32_t result_fault_mask;
    int terminal_fault;
    int hold_pending;
} DirectBridgeMmio;

typedef struct DirectBridgeHooks {
    DirectBridgeMmio *mmio;
    int ownership_code;
    int prepare_code;
    int invalidate_code;
    int drain_code;
    unsigned int publish_busy_remaining;
    unsigned int ownership_calls;
    unsigned int prepare_calls;
    unsigned int invalidate_calls;
    unsigned int publish_calls;
    unsigned int drain_calls;
    unsigned int publish_callbacks_ready;
    unsigned int callback_order_errors;
} DirectBridgeHooks;

static unsigned int failures;

static void
check(int condition, const char *name)
{
    if (!condition) {
        fprintf(stderr, "FAIL %s\n", name);
        ++failures;
    }
}

static void
mmio_reset(DirectBridgeMmio *mock)
{
    memset(mock, 0, sizeof *mock);
    mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
    mock->delay_polls = 2;
}

static void
mmio_set_result(DirectBridgeMmio *mock)
{
    mock->result[0] = mock->shadow[0];
    mock->result[1] = mock->shadow[1];
    mock->result[2] = mock->shadow[2];
    mock->result[3] = mock->shadow[3];
    mock->result[4] = mock->shadow[4];
    mock->result[5] = mock->shadow[5];
    mock->result[6] = mock->shadow[6];
    mock->result[7] = mock->shadow[14];
    mock->result[8] = mock->expected_tiles;
    mock->result[9] = mock->shadow[9];
    if (mock->result_fault_word < RESULT_WORDS)
        mock->result[mock->result_fault_word] ^= mock->result_fault_mask;
}

static int
mmio_read32(void *context, uint32_t offset, uint32_t *value)
{
    DirectBridgeMmio *mock = (DirectBridgeMmio *)context;
    unsigned int index;

    if (!mock || !value || (offset & 3u) != 0)
        return -1;
    if (offset == ZN_NC_REG_ID) {
        *value = ZN_NATIVE_CONV_MMIO_ID_VALUE;
        return 0;
    }
    if (offset == ZN_NC_REG_ABI_VERSION) {
        *value = ZN_NATIVE_CONV_MMIO_ABI_VERSION;
        return 0;
    }
    if (offset == ZN_NC_REG_CAPABILITIES) {
        *value = ZN_NC_CAP_VALID_MASK;
        return 0;
    }
    if (offset == ZN_NC_REG_STATUS) {
        if (mock->start_count && !mock->hold_pending &&
            (mock->status & ZN_NC_STATUS_ACCEPTED) &&
            !(mock->status & ZN_NC_STATUS_RESULT_VALID)) {
            ++mock->poll_count;
            if (mock->poll_count >= mock->delay_polls) {
                mmio_set_result(mock);
                mock->status = ZN_NC_STATUS_ACCEPTED |
                               ZN_NC_STATUS_DRAIN_COMPLETE |
                               ZN_NC_STATUS_RESULT_VALID;
                if (mock->terminal_fault)
                    mock->status |= ZN_NC_STATUS_FAULT;
                else
                    mock->status |= ZN_NC_STATUS_DONE;
            }
        }
        *value = mock->status;
        return 0;
    }
    if (offset == ZN_NC_REG_BRIDGE_ERROR) {
        *value = mock->bridge_error;
        return 0;
    }
    if (offset == ZN_NC_REG_BACKEND_FAULT_CODE) {
        *value = mock->fault_code;
        return 0;
    }
    if (offset >= ZN_NC_REG_RESULT_COOKIE && offset <= ZN_NC_REG_RESULT_SOURCE_GEN) {
        index = (offset - ZN_NC_REG_RESULT_COOKIE) / 4u;
        if (index >= RESULT_WORDS)
            return -1;
        *value = mock->result[index];
        return 0;
    }
    return -1;
}

static int
mmio_write32(void *context, uint32_t offset, uint32_t value)
{
    DirectBridgeMmio *mock = (DirectBridgeMmio *)context;
    unsigned int index;

    if (!mock || mock->write_count >= WRITE_CAPACITY)
        return -1;
    mock->write_offsets[mock->write_count] = offset;
    mock->write_values[mock->write_count] = value;
    ++mock->write_count;
    if (offset >= ZN_NC_REG_SHADOW_COOKIE && offset <= ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT) {
        index = (offset - ZN_NC_REG_SHADOW_COOKIE) / 4u;
        if (index >= SHADOW_WORDS)
            return -1;
        mock->shadow[index] = value;
        ++mock->shadow_write_count;
        return 0;
    }
    if (offset != ZN_NC_REG_CONTROL)
        return -1;
    if (value == ZN_NC_CONTROL_START) {
        ++mock->start_count;
        mock->status = mock->hold_pending ?
            ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_DRAIN_COMPLETE :
            ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE |
                ZN_NC_STATUS_DRAIN_COMPLETE;
        return 0;
    }
    if (value == ZN_NC_CONTROL_ABORT_BEFORE_ACCEPT) {
        ++mock->abort_count;
        mock->bridge_error = ZN_NC_BRIDGE_ERROR_PREACCEPT_ABORT;
        mock->status = ZN_NC_STATUS_DRAIN_COMPLETE;
        return 0;
    }
    if (value == ZN_NC_CONTROL_CANCEL_ACCEPTED) {
        ++mock->cancel_count;
        mock->terminal_fault = 1;
        mock->hold_pending = 0;
        mmio_set_result(mock);
        mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_FAULT |
                       ZN_NC_STATUS_DRAIN_COMPLETE | ZN_NC_STATUS_RESULT_VALID;
        return 0;
    }
    if (value == ZN_NC_CONTROL_ACK_RESULT) {
        ++mock->ack_count;
        if (mock->bridge_error != 0) {
            mock->bridge_error = 0;
            mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
        } else if (mock->terminal_fault) {
            mock->status = ZN_NC_STATUS_FAULT | ZN_NC_STATUS_ACTIVE |
                           ZN_NC_STATUS_DRAIN_COMPLETE;
        } else {
            mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
        }
        return 0;
    }
    return -1;
}

static int
mmio_write_barrier(void *context)
{
    return context ? 0 : -1;
}

static int
hook_check_ownership(void *context, const ZnRequest *request,
                     const ZnNativeGraphConvBindingV1 *binding)
{
    DirectBridgeHooks *hooks = (DirectBridgeHooks *)context;
    if (!hooks || !request || !binding)
        return -1;
    ++hooks->ownership_calls;
    if (binding->dispatch_epoch != request->epoch ||
        binding->event_index != request->event_index ||
        (request->operation == ZN_RUN && binding->dispatch_tag != request->tag) ||
        (request->operation == ZN_DRAIN && binding->dispatch_tag == request->tag) ||
        (request->operation != ZN_RUN && request->operation != ZN_DRAIN))
        return -1;
    return hooks->ownership_code;
}

static int
hook_prepare_device(void *context, const ZnNativeGraphConvBindingV1 *binding)
{
    DirectBridgeHooks *hooks = (DirectBridgeHooks *)context;
    if (!hooks || !binding || hooks->mmio->start_count != 0)
        return -1;
    ++hooks->prepare_calls;
    return hooks->prepare_code;
}

static int
hook_invalidate_output(void *context, const ZnNativeGraphConvBindingV1 *binding)
{
    DirectBridgeHooks *hooks = (DirectBridgeHooks *)context;
    if (!hooks || !binding || hooks->mmio->ack_count != 0 ||
        (hooks->mmio->status & (ZN_NC_STATUS_RESULT_VALID |
                                ZN_NC_STATUS_DRAIN_COMPLETE)) !=
            (ZN_NC_STATUS_RESULT_VALID | ZN_NC_STATUS_DRAIN_COMPLETE) ||
        (hooks->mmio->status & ZN_NC_STATUS_FAULT)) {
        if (hooks)
            ++hooks->callback_order_errors;
        return -1;
    }
    ++hooks->invalidate_calls;
    return hooks->invalidate_code;
}

static int
hook_validate_publish(void *context, const ZnNativeGraphConvBindingV1 *binding)
{
    DirectBridgeHooks *hooks = (DirectBridgeHooks *)context;
    if (!hooks || !binding || hooks->mmio->ack_count != 1 ||
        (hooks->mmio->status & (ZN_NC_STATUS_READY |
                                ZN_NC_STATUS_DRAIN_COMPLETE)) !=
            (ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE)) {
        if (hooks)
            ++hooks->callback_order_errors;
        return -1;
    }
    ++hooks->publish_calls;
    if (hooks->publish_busy_remaining != 0) {
        --hooks->publish_busy_remaining;
        return 1;
    }
    ++hooks->publish_callbacks_ready;
    return 0;
}

static int
hook_drain_ready(void *context, const ZnRequest *request,
                 const ZnNativeGraphConvBindingV1 *binding)
{
    DirectBridgeHooks *hooks = (DirectBridgeHooks *)context;
    if (!hooks || !request || !binding)
        return -1;
    ++hooks->drain_calls;
    return hooks->drain_code;
}

static void
make_mmio_ops(DirectBridgeMmio *mock, ZnNativeConvMmioOpsV2 *ops)
{
    ops->context = mock;
    ops->read32 = mmio_read32;
    ops->write32 = mmio_write32;
    ops->write_barrier = mmio_write_barrier;
}

static void
make_bridge_hooks(DirectBridgeHooks *state, DirectBridgeMmio *mock,
                  ZnNativeGraphConvHooksV1 *hooks)
{
    memset(state, 0, sizeof *state);
    state->mmio = mock;
    hooks->context = state;
    hooks->check_ownership = hook_check_ownership;
    hooks->prepare_device = hook_prepare_device;
    hooks->invalidate_output = hook_invalidate_output;
    hooks->validate_and_publish = hook_validate_publish;
    hooks->drain_ready = hook_drain_ready;
}

static int
dispatch_to_event_run(ZnDispatch *dispatch, uint16_t event_index,
                      uint32_t first_tag, ZnRequest *request)
{
    unsigned int attempts;

    if (zn_dispatch_init(dispatch, z100_graph_events, 73, 200) != 0)
        return -1;
    dispatch->cursor = event_index;
    dispatch->phase = ZN_ALLOCATE;
    dispatch->index = 0;
    dispatch->next_tag = first_tag;
    for (attempts = 0; attempts < 16; ++attempts) {
        int next = zn_dispatch_next(dispatch, request);
        if (next != 1)
            return -1;
        if (request->operation == ZN_RUN)
            return 0;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0)
            return -1;
    }
    return -1;
}

static ZnNativeDirectIdsV1
ids_for_event(uint16_t event_index)
{
    ZnNativeDirectIdsV1 ids;
    if (event_index == 0) {
        ids.job_base = 1000;
        ids.token_base = 100000;
        ids.tag_base = 10000000;
        ids.first_bank = 0;
    } else {
        ids.job_base = 1000u + (uint32_t)event_index * 32u;
        ids.token_base = 100000u + (uint32_t)event_index * 10000u;
        ids.tag_base = 10000000u + (uint32_t)event_index * 100000u;
        ids.first_bank = (uint8_t)(event_index & 1u);
    }
    ids.load_timeout_cycles = 1000000;
    ids.parameter_timeout_cycles = 1000000;
    ids.write_timeout_cycles = 1000000;
    ids.preaccept_timeout_cycles = 1000000;
    return ids;
}

static int
make_direct_run(uint16_t event_index, ZnDispatch *dispatch, ZnRequest *request,
                ZnNativeDirectIdsV1 *ids,
                ZnNativeGraphConvBindingV1 *binding)
{
    uint32_t tag_base = event_index == 0 ? 98u : 2000u + event_index * 16u;
    if (dispatch_to_event_run(dispatch, event_index, tag_base, request) != 0)
        return -1;
    *ids = ids_for_event(event_index);
    return zn_native_direct_binding_v1(request, ids, binding);
}

static int
direct_event_fail(uint16_t event_index, const char *where,
                  ZnNativeGraphConvBridgeCodeV1 code,
                  const DirectBridgeMmio *mock, const DirectBridgeHooks *state,
                  const ZnDispatch *dispatch)
{
    fprintf(stderr,
            "DIRECT_EVENT_FAIL event=%u where=%s code=%d status=%08x pending=%u phase=%u writes=%u starts=%u ack=%u polls=%u invalidate=%u publish=%u order=%u\n",
            event_index, where, (int)code, mock->status,
            dispatch ? dispatch->pending : 0,
            dispatch ? dispatch->phase : 0, mock->write_count,
            mock->start_count, mock->ack_count,
            mock->poll_count, state->invalidate_calls, state->publish_calls,
            state->callback_order_errors);
    return -1;
}

static int
run_direct_event(uint16_t event_index, DirectBridgeMmio *mock,
                 DirectBridgeHooks *state, ZnNativeGraphConvBridgeV1 *bridge,
                 ZnNativeConvMmioOpsV2 *mmio, ZnNativeGraphConvHooksV1 *hooks,
                 int inject_publish_busy, unsigned int *words_written)
{
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeDirectIdsV1 ids;
    ZnNativeGraphConvBindingV1 binding;
    ZnNativeGraphConvBridgeCodeV1 code;
    uint32_t encoded_words[SHADOW_WORDS];
    unsigned int word;

    mmio_reset(mock);
    make_bridge_hooks(state, mock, hooks);
    make_mmio_ops(mock, mmio);
    if (zn_native_graph_conv_bridge_init_v1(bridge, mmio, hooks) !=
        ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED)
        return direct_event_fail(event_index, "init", ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ARGUMENT,
                                 mock, state, NULL);
    if (make_direct_run(event_index, &dispatch, &request, &ids, &binding) != 0)
        return direct_event_fail(event_index, "bind", ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_INVALID_BINDING,
                                 mock, state, &dispatch);
    mock->expected_tiles = binding.expected_tiles;
    if (inject_publish_busy)
        state->publish_busy_remaining = 1;

    code = zn_native_graph_conv_bridge_step_v1(bridge, &dispatch, &request, &binding);
    if (code != ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY || mock->start_count != 1 ||
        mock->shadow_write_count != SHADOW_WORDS || dispatch.request.operation != ZN_RUN)
        return direct_event_fail(event_index, "submit", code, mock, state, &dispatch);
    if (zn_native_conv_command_encode_v1(&binding.command, encoded_words) !=
        ZN_NATIVE_CONV_COMMAND_OK)
        return direct_event_fail(event_index, "encode_expected", code, mock, state, &dispatch);
    for (word = 0; word < SHADOW_WORDS; ++word) {
        if (mock->shadow[word] != encoded_words[word])
            return direct_event_fail(event_index, "shadow_word_mismatch", code,
                                     mock, state, &dispatch);
    }
    *words_written += mock->shadow_write_count;

    code = zn_native_graph_conv_bridge_step_v1(bridge, &dispatch, &request, &binding);
    if (code != ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY)
        return direct_event_fail(event_index, "first_poll", code, mock, state, &dispatch);
    code = zn_native_graph_conv_bridge_step_v1(bridge, &dispatch, &request, &binding);
    if (code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY) {
        if (!dispatch.pending || dispatch.request.operation != ZN_RUN ||
            mock->ack_count != 1 || state->callback_order_errors != 0)
            return direct_event_fail(event_index, "publication_wait", code, mock, state, &dispatch);
        code = zn_native_graph_conv_bridge_step_v1(bridge, &dispatch, &request,
                                                  &binding);
    }
    if (code != ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED || dispatch.pending ||
        dispatch.phase != ZN_DRAIN || state->callback_order_errors != 0 ||
        state->publish_callbacks_ready != 1)
        return direct_event_fail(event_index, "run_ack", code, mock, state, &dispatch);

    if (event_index == 0)
        state->drain_code = 1;
    if (zn_dispatch_next(&dispatch, &request) != 1 || request.operation != ZN_DRAIN)
        return direct_event_fail(event_index, "next_drain", code, mock, state, &dispatch);
    code = zn_native_graph_conv_bridge_step_v1(bridge, &dispatch, &request, NULL);
    if (event_index == 0) {
        if (code != ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY || !dispatch.pending)
            return direct_event_fail(event_index, "drain_wait", code, mock, state, &dispatch);
        state->drain_code = 0;
        code = zn_native_graph_conv_bridge_step_v1(bridge, &dispatch, &request, NULL);
    }
    if (code != ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED || dispatch.pending ||
        mock->start_count != 1 || mock->ack_count != 1 ||
        state->invalidate_calls != 1 || state->drain_calls == 0)
        return direct_event_fail(event_index, "drain_ack", code, mock, state, &dispatch);
    return 0;
}

static void
check_event0_words(const DirectBridgeMmio *mock)
{
    static const uint32_t expected[SHADOW_WORDS] = {
        UINT32_C(0x00000064), UINT32_C(0x000000c8), UINT32_C(0x00000001),
        UINT32_C(0x83f6cd55), UINT32_C(0x000003e8), UINT32_C(0x000186a0),
        UINT32_C(0x00989680), UINT32_C(0x00000006), UINT32_C(0x10000000),
        UINT32_C(0x00000001), UINT32_C(0x10000000), UINT32_C(0x10190000),
        0, UINT32_C(0x10190000), UINT32_C(0x00000002), UINT32_C(0x10190000),
        UINT32_C(0x10320000), 0, UINT32_C(0x21000000), UINT32_C(0x000000ad),
        UINT32_C(0x20000000), UINT32_C(0x202fa500), 0, UINT32_C(0x000f4240),
        UINT32_C(0x000f4240), UINT32_C(0x000f4240), UINT32_C(0x000f4240)
    };
    unsigned int i;
    for (i = 0; i < SHADOW_WORDS; ++i)
        check(mock->shadow[i] == expected[i], "event zero independent direct command words");
}

static void
test_all_generated_events(void)
{
    DirectBridgeMmio mock;
    DirectBridgeHooks state;
    ZnNativeGraphConvBridgeV1 bridge;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    unsigned int direct_count = 0;
    unsigned int view_count = 0;
    unsigned int nonconv_count = 0;
    unsigned int words_written = 0;
    uint16_t i;

    for (i = 0; i < 73; ++i) {
        ZnDispatch dispatch;
        ZnRequest request;
        ZnNativeDirectIdsV1 ids = ids_for_event(i);
        ZnNativeGraphConvBindingV1 binding;
        int bind_code;

        check(dispatch_to_event_run(&dispatch, i, 5000u + (uint32_t)i * 16u,
                                    &request) == 0,
              "generated event reaches RUN");
        bind_code = zn_native_direct_binding_v1(&request, &ids, &binding);
        if (bind_code == 1) {
            mmio_reset(&mock);
            make_bridge_hooks(&state, &mock, &hooks);
            make_mmio_ops(&mock, &mmio);
            check(zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks) ==
                      ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED,
                  "unsupported event adapter init");
            if (request.job->operation == ZN_CONV) {
                ++view_count;
                check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch,
                      &request, NULL) == ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_UNBOUND,
                      "deferred Conv view remains unbound");
            } else {
                ++nonconv_count;
                check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch,
                      &request, NULL) == ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_UNSUPPORTED_OPERATION,
                      "non-Conv event remains unsupported");
            }
            check(dispatch.pending && !dispatch.fault && mock.write_count == 0,
                  "unsupported event receives no graph ACK or MMIO writes");
            continue;
        }
        check(bind_code == 0, "generated direct binding exists");
        ++direct_count;
        check(run_direct_event(i, &mock, &state, &bridge, &mmio, &hooks,
                               i == 0, &words_written) == 0,
              "generated direct binding completes RUN and DRAIN lifecycle");
        if (i == 0)
            check_event0_words(&mock);
    }
    check(direct_count == 42 && view_count == 21 && nonconv_count == 10,
          "73-event direct/view/nonconv inventory");
    check(words_written == 42u * SHADOW_WORDS,
          "42 generated direct commands submit 1134 actual driver words");
}

static void
test_stale_requests_and_invalid_bindings(void)
{
    DirectBridgeMmio mock;
    DirectBridgeHooks state;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnRequest stale;
    ZnNativeDirectIdsV1 ids;
    ZnNativeGraphConvBindingV1 binding;
    ZnEvent wrong_job;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBridgeV1 bridge;

    mmio_reset(&mock);
    make_mmio_ops(&mock, &mmio);
    make_bridge_hooks(&state, &mock, &hooks);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(make_direct_run(0, &dispatch, &request, &ids, &binding) == 0,
          "build event zero binding for stale request checks");
    stale = request;
    ++stale.epoch;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &stale, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST && mock.write_count == 0,
          "integration stale epoch rejected");
    wrong_job = *request.job;
    stale = request;
    stale.job = &wrong_job;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &stale, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST && mock.write_count == 0,
          "integration stale job rejected");
    stale = request;
    ++stale.ref.generation;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &stale, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST && mock.write_count == 0,
          "integration stale request ref rejected");

    binding.command.model_crc32 ^= 1u;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_INVALID_BINDING && mock.write_count == 0 &&
          dispatch.fault,
          "generated direct command model mismatch fails before START");

    mmio_reset(&mock);
    make_bridge_hooks(&state, &mock, &hooks);
    make_mmio_ops(&mock, &mmio);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(make_direct_run(0, &dispatch, &request, &ids, &binding) == 0,
          "rebuild event zero for alias rejection");
    binding.source_base = binding.command.destination_base;
    binding.command.source_base = binding.command.destination_base;
    binding.command.source_lease_region_begin = binding.command.destination_base;
    binding.command.source_lease_region_end.low =
        binding.command.destination_base + binding.source_bytes;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_INVALID_BINDING && mock.write_count == 0,
          "generated direct source destination alias fails before START");
}

static void
test_pending_binding_mutation_and_faults(void)
{
    DirectBridgeMmio mock;
    DirectBridgeHooks state;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeDirectIdsV1 ids;
    ZnNativeGraphConvBindingV1 binding;
    ZnNativeGraphConvBindingV1 changed;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBridgeV1 bridge;
    ZnNativeGraphConvBridgeCodeV1 code;

    mmio_reset(&mock);
    make_bridge_hooks(&state, &mock, &hooks);
    make_mmio_ops(&mock, &mmio);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(make_direct_run(0, &dispatch, &request, &ids, &binding) == 0,
          "build event zero binding for immutable snapshot");
    mock.expected_tiles = binding.expected_tiles;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY && mock.start_count == 1,
          "generated command starts exactly once");
    changed = binding;
    ++changed.command.destination_generation;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &changed) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST && mock.start_count == 1 &&
          dispatch.pending && !dispatch.fault,
          "caller cannot mutate submitted generated binding");
    (void)zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    code = zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    if (code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY)
        code = zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED && mock.start_count == 1,
          "original immutable command can complete after rejected mutation");
    if (code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED &&
        zn_dispatch_next(&dispatch, &request) == 1) {
        check(request.operation == ZN_DRAIN &&
              zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, NULL) ==
                  ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED,
              "mutated-command rejection retains successful graph DRAIN path");
    } else {
        check(0, "mutated-command test advances to DRAIN");
    }

    mmio_reset(&mock);
    mock.terminal_fault = 1;
    make_bridge_hooks(&state, &mock, &hooks);
    make_mmio_ops(&mock, &mmio);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(make_direct_run(0, &dispatch, &request, &ids, &binding) == 0,
          "build event zero binding for terminal hardware fault");
    mock.expected_tiles = binding.expected_tiles;
    (void)zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    (void)zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    code = zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED && dispatch.fault &&
          state.publish_callbacks_ready == 0 && mock.ack_count == 1,
          "drained MMIO fault never invokes publication callback");

    mmio_reset(&mock);
    mock.result_fault_word = 1;
    mock.result_fault_mask = 1;
    make_bridge_hooks(&state, &mock, &hooks);
    make_mmio_ops(&mock, &mmio);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(make_direct_run(0, &dispatch, &request, &ids, &binding) == 0,
          "build event zero binding for result identity mismatch");
    mock.expected_tiles = binding.expected_tiles;
    (void)zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    (void)zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    code = zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED && dispatch.fault &&
          state.publish_callbacks_ready == 0 && mock.ack_count == 0 &&
          zn_native_conv_driver_ownership_held_v2(&bridge.driver),
          "mismatched result identity poisons driver and retains graph ownership");
}

static void
test_preaccept_abort_with_generated_binding(void)
{
    DirectBridgeMmio mock;
    DirectBridgeHooks state;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeDirectIdsV1 ids;
    ZnNativeGraphConvBindingV1 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBridgeV1 bridge;

    mmio_reset(&mock);
    mock.hold_pending = 1;
    make_bridge_hooks(&state, &mock, &hooks);
    make_mmio_ops(&mock, &mmio);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(make_direct_run(0, &dispatch, &request, &ids, &binding) == 0,
          "build event zero binding for preaccept abort");
    mock.expected_tiles = binding.expected_tiles;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY,
          "generated binding starts pending acceptance");
    check(zn_native_graph_conv_bridge_timeout_v1(&bridge, &dispatch, &request) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED && mock.abort_count == 1 &&
          mock.cancel_count == 0 && mock.ack_count == 1 && dispatch.fault &&
          state.publish_callbacks_ready == 0,
          "preaccept ABORT fails graph request without publication");
}

int
main(void)
{
    test_all_generated_events();
    test_stale_requests_and_invalid_bindings();
    test_pending_binding_mutation_and_faults();
    test_preaccept_abort_with_generated_binding();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_DIRECT_BRIDGE_INTEGRATION_V1_HOST_FAIL count=%u\n", failures);
        return 1;
    }
    puts("NATIVE_DIRECT_BRIDGE_INTEGRATION_V1_HOST_PASS direct=42 deferred_conv_views=21 nonconv=10 command_words=1134 delayed_result=42 cache_callbacks=42 publication_wait=1 drain_wait=1 fault=1 result_identity=1 abort=1");
    return 0;
}
