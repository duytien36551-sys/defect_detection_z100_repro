#include "native_graph_conv_bridge_v1.h"

#include <stdio.h>
#include <string.h>

enum { RESULT_WORDS = 10, WRITE_CAPACITY = 64 };

typedef struct BridgeMmio {
    uint32_t status;
    uint32_t bridge_error;
    uint32_t fault_code;
    uint32_t shadow[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t result[RESULT_WORDS];
    uint32_t write_offsets[WRITE_CAPACITY];
    uint32_t write_values[WRITE_CAPACITY];
    unsigned int write_count;
    unsigned int barrier_count;
    unsigned int start_count;
    unsigned int abort_count;
    unsigned int cancel_count;
    unsigned int ack_count;
    unsigned int result_poll_count;
    unsigned int complete_after;
    int hold_pending;
    int terminal_fault;
} BridgeMmio;

typedef struct HookState {
    int ownership_code;
    int prepare_code;
    int invalidate_code;
    int publish_code;
    int drain_code;
    unsigned int ownership_calls;
    unsigned int prepare_calls;
    unsigned int invalidate_calls;
    unsigned int publish_calls;
    unsigned int drain_calls;
    unsigned int published;
} HookState;

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
mock_reset(BridgeMmio *mock)
{
    memset(mock, 0, sizeof *mock);
    mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
    mock->complete_after = 1;
}

static void
mock_set_result(BridgeMmio *mock, const uint32_t *words)
{
    mock->result[0] = words[0];
    mock->result[1] = words[1];
    mock->result[2] = words[2];
    mock->result[3] = words[3];
    mock->result[4] = words[4];
    mock->result[5] = words[5];
    mock->result[6] = words[6];
    mock->result[7] = words[14];
    mock->result[8] = 2u;
    mock->result[9] = words[9];
}

static int
mock_read32(void *context, uint32_t offset, uint32_t *value)
{
    BridgeMmio *mock = (BridgeMmio *)context;
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
            ++mock->result_poll_count;
            if (mock->result_poll_count >= mock->complete_after) {
                mock_set_result(mock, mock->shadow);
                mock->status = ZN_NC_STATUS_ACCEPTED |
                               ZN_NC_STATUS_DRAIN_COMPLETE |
                               ZN_NC_STATUS_RESULT_VALID;
                if (mock->terminal_fault) {
                    mock->status |= ZN_NC_STATUS_FAULT;
                } else {
                    mock->status |= ZN_NC_STATUS_DONE;
                }
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
mock_write32(void *context, uint32_t offset, uint32_t value)
{
    BridgeMmio *mock = (BridgeMmio *)context;
    unsigned int index;

    if (!mock || mock->write_count >= WRITE_CAPACITY)
        return -1;
    mock->write_offsets[mock->write_count] = offset;
    mock->write_values[mock->write_count] = value;
    ++mock->write_count;

    if (offset >= ZN_NC_REG_SHADOW_COOKIE &&
        offset <= ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT) {
        index = (offset - ZN_NC_REG_SHADOW_COOKIE) / 4u;
        if (index >= ZN_NATIVE_CONV_COMMAND_WORD_COUNT)
            return -1;
        mock->shadow[index] = value;
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
        mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_FAULT |
                       ZN_NC_STATUS_DRAIN_COMPLETE | ZN_NC_STATUS_RESULT_VALID;
        mock_set_result(mock, mock->shadow);
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
mock_barrier(void *context)
{
    BridgeMmio *mock = (BridgeMmio *)context;
    ++mock->barrier_count;
    return 0;
}

static int
hook_ownership(void *context, const ZnRequest *request,
               const ZnNativeGraphConvBindingV1 *binding)
{
    HookState *hooks = (HookState *)context;
    (void)request;
    (void)binding;
    ++hooks->ownership_calls;
    return hooks->ownership_code;
}

static int
hook_prepare(void *context, const ZnNativeGraphConvBindingV1 *binding)
{
    HookState *hooks = (HookState *)context;
    (void)binding;
    ++hooks->prepare_calls;
    return hooks->prepare_code;
}

static int
hook_invalidate(void *context, const ZnNativeGraphConvBindingV1 *binding)
{
    HookState *hooks = (HookState *)context;
    (void)binding;
    ++hooks->invalidate_calls;
    return hooks->invalidate_code;
}

static int
hook_publish(void *context, const ZnNativeGraphConvBindingV1 *binding)
{
    HookState *hooks = (HookState *)context;
    (void)binding;
    ++hooks->publish_calls;
    if (hooks->publish_code == 0)
        ++hooks->published;
    return hooks->publish_code;
}

static int
hook_drain(void *context, const ZnRequest *request,
           const ZnNativeGraphConvBindingV1 *binding)
{
    HookState *hooks = (HookState *)context;
    (void)request;
    (void)binding;
    ++hooks->drain_calls;
    return hooks->drain_code;
}

static void
make_event(ZnEvent *event, uint8_t operation)
{
    memset(event, 0, sizeof *event);
    event->event = 1;
    event->tile_count = 2;
    event->compute_node = 0;
    event->operation = operation;
    event->read_count = 1;
    event->retire_count = 1;
    event->has_destination = 1;
    event->destination.address = UINT32_C(0x30000000);
    event->destination.bytes = 64;
    event->destination.channels = 4;
    event->destination.height = 4;
    event->destination.width = 4;
    event->destination.ref.generation = 8;
    event->destination.ref.tensor = 1;
    event->destination.ref.slot = 1;
    event->reads[0].generation = 7;
    event->reads[0].tensor = 0;
    event->reads[0].slot = 0;
    event->retired[0] = event->reads[0];
}

static void
make_binding(ZnNativeGraphConvBindingV1 *binding, const ZnRequest *request)
{
    ZnNativeConvCommand *command;
    memset(binding, 0, sizeof *binding);
    binding->dispatch_epoch = request->epoch;
    binding->dispatch_tag = request->tag;
    binding->event_index = request->event_index;
    binding->source_ref = request->job->reads[0];
    binding->destination_ref = request->job->destination.ref;
    binding->source_base = UINT32_C(0x10000000);
    binding->source_bytes = 64;
    binding->expected_cookie = UINT32_C(0xc0decafe);
    binding->expected_job_base = 1;
    binding->expected_token_base = 4100;
    binding->expected_tag_base = UINT32_C(0x53000000);
    binding->expected_tiles = request->job->tile_count;
    memcpy(binding->package_sha256, ZN_NATIVE_GRAPH_CONV_PACKAGE_SHA256_V1,
           sizeof binding->package_sha256);
    memcpy(binding->checkpoint_sha256, ZN_NATIVE_GRAPH_CONV_MODEL_SHA256_V1,
           sizeof binding->checkpoint_sha256);
    memcpy(binding->graph_sha256, ZN_NATIVE_GRAPH_CONV_GRAPH_SHA256_V1,
           sizeof binding->graph_sha256);

    command = &binding->command;
    command->request_cookie = binding->expected_cookie;
    command->epoch = request->epoch;
    command->event = request->job->event;
    command->model_crc32 = ZN_NATIVE_CONV_MMIO_MODEL_CRC32;
    command->job_base = binding->expected_job_base;
    command->token_base = binding->expected_token_base;
    command->tag_base = binding->expected_tag_base;
    command->flags = ZN_NC_SHADOW_FLAGS_VALID_MASK;
    command->source_base = binding->source_base;
    command->source_generation = binding->source_ref.generation;
    command->source_lease_region_begin = UINT32_C(0x10000000);
    command->source_lease_region_end.low = UINT32_C(0x10000100);
    command->destination_base = request->job->destination.address;
    command->destination_generation = binding->destination_ref.generation;
    command->destination_reservation_region_begin = UINT32_C(0x30000000);
    command->destination_reservation_region_end.low = UINT32_C(0x30000100);
    command->parameter_directory_base = UINT32_C(0x21000000);
    command->parameter_count = ZN_NATIVE_CONV_MMIO_PARAMETER_COUNT;
    command->parameter_payload_begin = UINT32_C(0x20000000);
    command->parameter_payload_end.low = UINT32_C(0x20001000);
    command->load_timeout_cycles = 1000;
    command->parameter_timeout_cycles = 1000;
    command->write_timeout_cycles = 1000;
    command->preaccept_timeout_cycles = 1000;
}

static void
make_ops(BridgeMmio *mock, ZnNativeConvMmioOpsV2 *ops)
{
    ops->context = mock;
    ops->read32 = mock_read32;
    ops->write32 = mock_write32;
    ops->write_barrier = mock_barrier;
}

static void
make_hooks(HookState *state, ZnNativeGraphConvHooksV1 *hooks)
{
    memset(state, 0, sizeof *state);
    hooks->context = state;
    hooks->check_ownership = hook_ownership;
    hooks->prepare_device = hook_prepare;
    hooks->invalidate_output = hook_invalidate;
    hooks->validate_and_publish = hook_publish;
    hooks->drain_ready = hook_drain;
}

static int
dispatch_to_run(ZnDispatch *dispatch, ZnEvent *event, ZnRequest *request)
{
    if (zn_dispatch_init(dispatch, event, 1, 200) != 0 ||
        zn_dispatch_next(dispatch, request) != 1 ||
        request->operation != ZN_ALLOCATE ||
        zn_dispatch_ack(dispatch, request->tag, request->operation, ZN_ACK_OK) != 0 ||
        zn_dispatch_next(dispatch, request) != 1 ||
        request->operation != ZN_ACQUIRE ||
        zn_dispatch_ack(dispatch, request->tag, request->operation, ZN_ACK_OK) != 0 ||
        zn_dispatch_next(dispatch, request) != 1 || request->operation != ZN_RUN)
        return -1;
    return 0;
}

static void
test_success_delayed_publish_and_drain(void)
{
    static const uint32_t expected[ZN_NATIVE_CONV_COMMAND_WORD_COUNT] = {
        UINT32_C(0xc0decafe), 200, 1, UINT32_C(0x83f6cd55), 1, 4100,
        UINT32_C(0x53000000), 7, UINT32_C(0x10000000), 7,
        UINT32_C(0x10000000), UINT32_C(0x10000100), 0,
        UINT32_C(0x30000000), 8, UINT32_C(0x30000000), UINT32_C(0x30000100), 0,
        UINT32_C(0x21000000), 173, UINT32_C(0x20000000), UINT32_C(0x20001000), 0,
        1000, 1000, 1000, 1000
    };
    BridgeMmio mock;
    HookState state;
    ZnEvent event;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeGraphConvBindingV1 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBridgeV1 bridge;
    unsigned int i;

    mock_reset(&mock);
    mock.complete_after = 2;
    make_event(&event, ZN_CONV);
    check(dispatch_to_run(&dispatch, &event, &request) == 0,
          "prepare selected Conv RUN request");
    make_binding(&binding, &request);
    make_ops(&mock, &mmio);
    make_hooks(&state, &hooks);
    check(zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED,
          "bridge init");
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY,
          "RUN submits actual v2 driver and remains pending");
    check(mock.start_count == 1 && mock.barrier_count == 1 && mock.write_count == 28,
          "driver submits one command after one barrier");
    for (i = 0; i < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++i) {
        check(mock.write_offsets[i] == ZN_NC_REG_SHADOW_COOKIE + 4u * i,
              "shadow register offset fixture");
        check(mock.write_values[i] == expected[i], "independent 27-word fixture");
    }
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY,
          "first physical poll remains busy");
    state.publish_code = 1;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY,
          "success result waits for atomic ledger publication");
    check(dispatch.pending && dispatch.request.operation == ZN_RUN &&
          !state.published && mock.ack_count == 1,
          "publication BUSY retains graph RUN and no ledger publication");
    state.publish_code = 0;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED,
          "RUN is acknowledged after result, quiet, cache and publication gates");
    check(dispatch.pending == 0 && state.published == 1 && mock.start_count == 1,
          "successful RUN publishes once and starts once");
    check(zn_dispatch_next(&dispatch, &request) == 1 && request.operation == ZN_DRAIN,
          "dispatcher advances to graph DRAIN");
    state.drain_code = 1;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, NULL) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_BUSY && dispatch.pending,
          "DRAIN waits for graph readers");
    state.drain_code = 0;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, NULL) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_ACKED,
          "DRAIN is acknowledged after reader and IO check");
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch,
              &(ZnRequest){ .epoch = 200, .tag = 3, .event_index = 0,
                            .operation = ZN_RUN, .job = &event }, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST,
          "replayed RUN is rejected after DRAIN");
}

static void
test_fault_no_publish(void)
{
    BridgeMmio mock;
    HookState state;
    ZnEvent event;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeGraphConvBindingV1 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBridgeV1 bridge;

    mock_reset(&mock);
    mock.terminal_fault = 1;
    make_event(&event, ZN_CONV);
    check(dispatch_to_run(&dispatch, &event, &request) == 0,
          "prepare fault RUN request");
    make_binding(&binding, &request);
    make_ops(&mock, &mmio);
    make_hooks(&state, &hooks);
    check(zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks) == 0,
          "fault bridge init");
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) == 1,
          "fault RUN submitted");
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED,
          "drained Conv fault fails graph RUN");
    check(dispatch.fault && dispatch.pending && state.published == 0 &&
          mock.ack_count == 1 && bridge.stage == ZN_NATIVE_GRAPH_CONV_STAGE_V1_POISONED,
          "fault ACKs only diagnostic MMIO result and never publishes ledger");
}

static void
test_preaccept_abort(void)
{
    BridgeMmio mock;
    HookState state;
    ZnEvent event;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeGraphConvBindingV1 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBridgeV1 bridge;

    mock_reset(&mock);
    mock.hold_pending = 1;
    make_event(&event, ZN_CONV);
    check(dispatch_to_run(&dispatch, &event, &request) == 0,
          "prepare abort RUN request");
    make_binding(&binding, &request);
    make_ops(&mock, &mmio);
    make_hooks(&state, &hooks);
    check(zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks) == 0,
          "abort bridge init");
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) == 1,
          "abort RUN submitted pending acceptance");
    check(zn_native_graph_conv_bridge_timeout_v1(&bridge, &dispatch, &request) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_FAILED,
          "preaccept timeout reports graph failure");
    check(mock.abort_count == 1 && mock.cancel_count == 0 && mock.ack_count == 1 &&
          dispatch.fault && dispatch.pending && state.published == 0,
          "ABORT path drains local error without CANCEL or ledger publication");
}

static void
test_bad_bindings_and_stale_requests(void)
{
    BridgeMmio mock;
    HookState state;
    ZnEvent event;
    ZnEvent other_event;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnRequest stale;
    ZnNativeGraphConvBindingV1 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBridgeV1 bridge;

    mock_reset(&mock);
    make_event(&event, ZN_CONV);
    (void)dispatch_to_run(&dispatch, &event, &request);
    make_binding(&binding, &request);
    make_ops(&mock, &mmio);
    make_hooks(&state, &hooks);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    stale = request;
    ++stale.epoch;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &stale, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST && mock.write_count == 0 &&
          !dispatch.fault,
          "stale epoch is rejected without MMIO or dispatch mutation");
    make_event(&other_event, ZN_CONV);
    stale = request;
    stale.job = &other_event;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &stale, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST && mock.write_count == 0 &&
          !dispatch.fault,
          "stale job pointer is rejected without MMIO or dispatch mutation");
    stale = request;
    stale.ref.generation++;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &stale, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST && mock.write_count == 0 &&
          !dispatch.fault,
          "stale request reference is rejected without MMIO or dispatch mutation");

    make_binding(&binding, &request);
    binding.source_ref.generation++;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_INVALID_BINDING && mock.write_count == 0 &&
          dispatch.fault,
          "stale source reference fails closed before START");

    mock_reset(&mock);
    (void)dispatch_to_run(&dispatch, &event, &request);
    make_binding(&binding, &request);
    binding.command.model_crc32 ^= 1u;
    make_ops(&mock, &mmio);
    make_hooks(&state, &hooks);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_INVALID_BINDING && mock.write_count == 0,
          "bad model command rejected before START");

    mock_reset(&mock);
    (void)dispatch_to_run(&dispatch, &event, &request);
    make_binding(&binding, &request);
    binding.source_base = UINT32_C(0x30000000);
    binding.command.source_base = UINT32_C(0x30000000);
    binding.command.source_lease_region_begin = UINT32_C(0x30000000);
    binding.command.source_lease_region_end.low = UINT32_C(0x30000100);
    make_ops(&mock, &mmio);
    make_hooks(&state, &hooks);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_INVALID_BINDING && mock.write_count == 0,
          "source destination alias is rejected before START");
}

static void
test_unsupported_nonconv_and_mutated_pending_binding(void)
{
    BridgeMmio mock;
    HookState state;
    ZnEvent event;
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeGraphConvBindingV1 binding;
    ZnNativeGraphConvBindingV1 changed;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV1 hooks;
    ZnNativeGraphConvBridgeV1 bridge;

    mock_reset(&mock);
    make_event(&event, ZN_ADD);
    (void)dispatch_to_run(&dispatch, &event, &request);
    make_ops(&mock, &mmio);
    make_hooks(&state, &hooks);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, NULL) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_UNSUPPORTED_OPERATION && mock.write_count == 0 &&
          dispatch.pending && !dispatch.fault,
          "non-Conv operation is distinctly unsupported");

    mock_reset(&mock);
    make_event(&event, ZN_CONV);
    (void)dispatch_to_run(&dispatch, &event, &request);
    make_binding(&binding, &request);
    make_ops(&mock, &mmio);
    make_hooks(&state, &hooks);
    (void)zn_native_graph_conv_bridge_init_v1(&bridge, &mmio, &hooks);
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &binding) == 1,
          "mutation test submit");
    changed = binding;
    ++changed.command.destination_generation;
    check(zn_native_graph_conv_bridge_step_v1(&bridge, &dispatch, &request, &changed) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V1_STALE_REQUEST && mock.start_count == 1 &&
          dispatch.pending && !dispatch.fault,
          "caller mutation cannot replace the immutable pending binding");
}

int
main(void)
{
    test_success_delayed_publish_and_drain();
    test_fault_no_publish();
    test_preaccept_abort();
    test_bad_bindings_and_stale_requests();
    test_unsupported_nonconv_and_mutated_pending_binding();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_GRAPH_CONV_BRIDGE_V1_HOST_FAIL count=%u\n", failures);
        return 1;
    }
    puts("NATIVE_GRAPH_CONV_BRIDGE_V1_HOST_PASS delayed=1 fault=1 abort=1 stale=1 alias=1 replay=1 binding_snapshot=1 unsupported=1 independent_words=27");
    return 0;
}
