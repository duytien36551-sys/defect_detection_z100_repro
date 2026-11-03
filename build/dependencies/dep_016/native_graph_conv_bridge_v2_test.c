#include "native_graph_conv_bridge_v2.h"

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
    uint32_t expected_tiles;
    uint32_t result_source_generation_xor;
    unsigned int write_count;
    unsigned int barrier_count;
    unsigned int start_count;
    unsigned int abort_count;
    unsigned int cancel_count;
    unsigned int ack_count;
    unsigned int result_poll_count;
    unsigned int complete_after;
    int hold_pending;
} BridgeMmio;

typedef struct HookState {
    BridgeMmio *mmio;
    int leases_code;
    int convert_code;
    int clean_code;
    int source_ready_code;
    int invalidate_code;
    int publish_code;
    int drain_code;
    int return_code;
    int release_code;
    unsigned int leases_calls;
    unsigned int convert_calls;
    unsigned int clean_calls;
    unsigned int source_ready_calls;
    unsigned int invalidate_calls;
    unsigned int publish_calls;
    unsigned int drain_calls;
    unsigned int return_calls;
    unsigned int release_calls;
    uint32_t returned_mask;
    uint8_t read_count;
    int converted;
    int cleaned;
    int output_invalidated;
    int published;
    int drain_ready_seen;
    int scratch_reserved;
    int scratch_released;
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

static int
test_ref_equal(ZnRef a, ZnRef b)
{
    return a.generation == b.generation && a.tensor == b.tensor &&
           a.slot == b.slot;
}

static void
mock_reset(BridgeMmio *mock)
{
    memset(mock, 0, sizeof *mock);
    mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
    mock->complete_after = 1;
    mock->expected_tiles = 3;
}

static void
mock_set_result(BridgeMmio *mock)
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
    mock->result[9] = mock->shadow[9] ^ mock->result_source_generation_xor;
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
                mock_set_result(mock);
                mock->status = ZN_NC_STATUS_ACCEPTED |
                               ZN_NC_STATUS_DONE |
                               ZN_NC_STATUS_DRAIN_COMPLETE |
                               ZN_NC_STATUS_RESULT_VALID;
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
    if (offset >= ZN_NC_REG_RESULT_COOKIE &&
        offset <= ZN_NC_REG_RESULT_SOURCE_GEN) {
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
        mock->bridge_error = ZN_NC_BRIDGE_ERROR_NONE;
        mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_FAULT |
                       ZN_NC_STATUS_DRAIN_COMPLETE | ZN_NC_STATUS_RESULT_VALID;
        mock_set_result(mock);
        return 0;
    }
    if (value == ZN_NC_CONTROL_ACK_RESULT) {
        ++mock->ack_count;
        if (mock->bridge_error != 0) {
            mock->bridge_error = 0;
            mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
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
hook_check_leases(void *context, const ZnRequest *request,
                  const ZnNativeGraphConvBindingV2 *binding)
{
    HookState *state = (HookState *)context;
    uint8_t index;

    ++state->leases_calls;
    if (!request || !binding || binding->graph_read_count != state->read_count ||
        binding->scratch.epoch != request->epoch ||
        binding->scratch.generation == 0 || !state->scratch_reserved)
        return -1;
    for (index = 0; index < state->read_count; ++index) {
        if (binding->graph_read_refs[index].generation == 0 ||
            binding->graph_read_refs[index].tensor != request->job->reads[index].tensor ||
            binding->graph_read_refs[index].slot != request->job->reads[index].slot ||
            binding->graph_read_refs[index].generation !=
                request->job->reads[index].generation)
            return -1;
    }
    return state->leases_code;
}

static int
hook_convert_views(void *context, const ZnRequest *request,
                   const ZnNativeGraphConvBindingV2 *binding)
{
    HookState *state = (HookState *)context;
    (void)request;
    ++state->convert_calls;
    if (!binding || binding->source_span.base != binding->scratch.base)
        return -1;
    if (state->convert_code != 0)
        return state->convert_code;
    state->converted = 1;
    return 0;
}

static int
hook_clean_source(void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    HookState *state = (HookState *)context;
    ++state->clean_calls;
    if (!binding || !state->converted)
        return -1;
    if (state->clean_code != 0)
        return state->clean_code;
    state->cleaned = 1;
    return 0;
}

static int
hook_check_source_ready(void *context, const ZnRequest *request,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    HookState *state = (HookState *)context;
    (void)request;
    ++state->source_ready_calls;
    if (!binding || !state->converted || !state->cleaned ||
        binding->source_span.bytes == 0)
        return -1;
    return state->source_ready_code;
}

static int
hook_invalidate_output(void *context,
                       const ZnNativeGraphConvBindingV2 *binding)
{
    HookState *state = (HookState *)context;
    ++state->invalidate_calls;
    if (!binding)
        return -1;
    if (state->invalidate_code != 0)
        return state->invalidate_code;
    state->output_invalidated = 1;
    return 0;
}

static int
hook_publish(void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    HookState *state = (HookState *)context;
    ++state->publish_calls;
    if (!binding || !state->output_invalidated)
        return -1;
    if (state->publish_code != 0)
        return state->publish_code;
    state->published = 1;
    return 0;
}

static int
hook_drain_ready(void *context, const ZnRequest *request,
                 const ZnNativeGraphConvBindingV2 *binding)
{
    HookState *state = (HookState *)context;
    ++state->drain_calls;
    if (!request || !binding || !state->published)
        return -1;
    if (state->drain_code != 0)
        return state->drain_code;
    state->drain_ready_seen = 1;
    return 0;
}

static int
hook_return_graph_read(void *context, const ZnRequest *request,
                       const ZnNativeGraphConvBindingV2 *binding,
                       uint8_t read_index)
{
    HookState *state = (HookState *)context;
    ++state->return_calls;
    if (!request || !binding || !state->drain_ready_seen ||
        read_index >= state->read_count ||
        request->ref.generation != binding->graph_read_refs[read_index].generation ||
        request->ref.tensor != binding->graph_read_refs[read_index].tensor ||
        request->ref.slot != binding->graph_read_refs[read_index].slot)
        return -1;
    if (state->return_code != 0)
        return state->return_code;
    state->returned_mask |= UINT32_C(1) << read_index;
    return 0;
}

static int
hook_release_scratch(void *context,
                     const ZnNativeGraphConvBindingV2 *binding)
{
    HookState *state = (HookState *)context;
    uint32_t expected_mask = (UINT32_C(1) << state->read_count) - 1u;

    ++state->release_calls;
    if (!binding || !state->scratch_reserved || !state->drain_ready_seen ||
        state->returned_mask != expected_mask || !state->mmio ||
        state->mmio->ack_count == 0)
        return -1;
    if (state->release_code != 0)
        return state->release_code;
    state->scratch_reserved = 0;
    state->scratch_released = 1;
    return 0;
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
make_hooks(HookState *state, BridgeMmio *mock, uint8_t read_count,
           ZnNativeGraphConvHooksV2 *hooks)
{
    memset(state, 0, sizeof *state);
    state->mmio = mock;
    state->read_count = read_count;
    state->scratch_reserved = 1;
    hooks->context = state;
    hooks->check_leases = hook_check_leases;
    hooks->convert_views = hook_convert_views;
    hooks->clean_source = hook_clean_source;
    hooks->check_source_ready = hook_check_source_ready;
    hooks->invalidate_output = hook_invalidate_output;
    hooks->validate_and_publish = hook_publish;
    hooks->drain_ready = hook_drain_ready;
    hooks->return_graph_read = hook_return_graph_read;
    hooks->release_scratch = hook_release_scratch;
}

static void
make_event(ZnEvent *event, uint16_t event_number, uint8_t read_count,
           uint8_t operation)
{
    uint8_t index;

    memset(event, 0, sizeof *event);
    event->event = event_number;
    event->tile_count = 3;
    event->operation = operation;
    event->read_count = read_count;
    event->retire_count = 0;
    event->has_destination = 1;
    event->destination.address = UINT32_C(0x30000000);
    event->destination.bytes = 128;
    event->destination.channels = 8;
    event->destination.height = 4;
    event->destination.width = 4;
    event->destination.ref.generation = 902;
    event->destination.ref.tensor = 900 + (int32_t)event_number;
    event->destination.ref.slot = 3;
    for (index = 0; index < read_count; ++index) {
        event->reads[index].generation = 100 + index;
        event->reads[index].tensor = index;
        event->reads[index].slot = index;
    }
}

static void
make_binding(ZnNativeGraphConvBindingV2 *binding, const ZnRequest *request)
{
    ZnNativeConvCommand *command;
    uint64_t scratch_end;

    memset(binding, 0, sizeof *binding);
    binding->dispatch_epoch = request->epoch;
    binding->dispatch_tag = request->tag;
    binding->event_index = request->event_index;
    binding->graph_read_count = request->job->read_count;
    memcpy(binding->graph_read_refs, request->job->reads,
           (size_t)binding->graph_read_count * sizeof binding->graph_read_refs[0]);
    binding->destination_ref = request->job->destination.ref;
    binding->scratch.epoch = request->epoch;
    binding->scratch.generation = 800;
    binding->scratch.base = UINT32_C(0x22000000);
    binding->scratch.bytes = 4096;
    binding->source_span.base = binding->scratch.base;
    binding->source_span.bytes = 1024;
    binding->expected_cookie = UINT32_C(0xc0decafe);
    binding->expected_job_base = 1001;
    binding->expected_token_base = 4100;
    binding->expected_tag_base = UINT32_C(0x53000000);
    binding->expected_tiles = request->job->tile_count;
    memcpy(binding->package_sha256, ZN_NATIVE_GRAPH_CONV_PACKAGE_SHA256_V2,
           sizeof binding->package_sha256);
    memcpy(binding->checkpoint_sha256, ZN_NATIVE_GRAPH_CONV_MODEL_SHA256_V2,
           sizeof binding->checkpoint_sha256);
    memcpy(binding->graph_sha256, ZN_NATIVE_GRAPH_CONV_GRAPH_SHA256_V2,
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
    command->source_base = binding->source_span.base;
    command->source_generation = binding->scratch.generation;
    command->source_lease_region_begin = binding->scratch.base;
    scratch_end = (uint64_t)binding->scratch.base + binding->scratch.bytes;
    command->source_lease_region_end.low = (uint32_t)scratch_end;
    command->source_lease_region_end.high = (uint8_t)(scratch_end >> 32);
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

static int
dispatch_to_run(ZnDispatch *dispatch, ZnEvent *events, uint16_t count,
                uint32_t epoch, ZnRequest *request)
{
    uint8_t index;

    if (zn_dispatch_init(dispatch, events, count, epoch) != 0 ||
        zn_dispatch_next(dispatch, request) != 1 ||
        request->operation != ZN_ALLOCATE ||
        zn_dispatch_ack(dispatch, request->tag, request->operation, ZN_ACK_OK) != 0)
        return -1;
    for (index = 0; index < events[0].read_count; ++index) {
        if (zn_dispatch_next(dispatch, request) != 1 ||
            request->operation != ZN_ACQUIRE ||
            !test_ref_equal(request->ref, events[0].reads[index]) ||
            zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0)
            return -1;
    }
    if (zn_dispatch_next(dispatch, request) != 1 || request->operation != ZN_RUN)
        return -1;
    return 0;
}

static int
setup_case(BridgeMmio *mock, HookState *state, ZnEvent *events, uint16_t count,
           uint32_t epoch, ZnDispatch *dispatch, ZnRequest *request,
           ZnNativeGraphConvBindingV2 *binding,
           ZnNativeConvMmioOpsV2 *mmio, ZnNativeGraphConvHooksV2 *hooks,
           ZnNativeGraphConvBridgeV2 *bridge)
{
    mock_reset(mock);
    if (dispatch_to_run(dispatch, events, count, epoch, request) != 0)
        return -1;
    make_binding(binding, request);
    mock->expected_tiles = binding->expected_tiles;
    make_ops(mock, mmio);
    make_hooks(state, mock, events[0].read_count, hooks);
    if (zn_native_graph_conv_bridge_init_v2(bridge, mmio, hooks) !=
        ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED)
        return -1;
    return 0;
}

static ZnNativeGraphConvBridgeCodeV2
submit_and_complete(ZnNativeGraphConvBridgeV2 *bridge, ZnDispatch *dispatch,
                    ZnRequest *request, ZnNativeGraphConvBindingV2 *binding,
                    BridgeMmio *mock, HookState *state)
{
    ZnNativeGraphConvBridgeCodeV2 code;

    code = zn_native_graph_conv_bridge_step_v2(bridge, dispatch, request, binding);
    if (code != ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY || mock->start_count != 1)
        return code;
    code = zn_native_graph_conv_bridge_step_v2(bridge, dispatch, request, binding);
    if (code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY &&
        bridge->stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_PUBLISH) {
        state->publish_code = 0;
        code = zn_native_graph_conv_bridge_step_v2(bridge, dispatch, request,
                                                   binding);
    }
    return code;
}

static void
check_command_words(const BridgeMmio *mock,
                    const ZnNativeGraphConvBindingV2 *binding)
{
    static const uint32_t independent_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT] = {
        UINT32_C(0xc0decafe), 200, 9, UINT32_C(0x83f6cd55), 1001, 4100,
        UINT32_C(0x53000000), 7, UINT32_C(0x22000000), 800,
        UINT32_C(0x22000000), UINT32_C(0x22001000), 0,
        UINT32_C(0x30000000), 902, UINT32_C(0x30000000),
        UINT32_C(0x30000100), 0, UINT32_C(0x21000000), 173,
        UINT32_C(0x20000000), UINT32_C(0x20001000), 0, 1000, 1000, 1000, 1000
    };
    uint32_t expected[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    unsigned int index;

    check(zn_native_conv_command_encode_v1(&binding->command, expected) ==
              ZN_NATIVE_CONV_COMMAND_OK,
          "independently encode V2 command fixture");
    for (index = 0; index < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++index) {
        check(mock->shadow[index] == expected[index],
              "real driver wrote exact V2 command word");
        check(mock->shadow[index] == independent_words[index],
              "V2 submitted command matches independent word fixture");
        check(mock->write_offsets[index] == ZN_NC_REG_SHADOW_COOKIE + index * 4u,
              "real driver wrote expected V2 shadow offset");
    }
}

static void
test_success_multi_read_no_retire_and_finish_retry(void)
{
    BridgeMmio mock;
    HookState state;
    ZnEvent events[1];
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeGraphConvBindingV2 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativeGraphConvBridgeV2 bridge;
    ZnNativeGraphConvBridgeCodeV2 code;
    uint8_t read_index;

    make_event(&events[0], 9, 3, ZN_CONV);
    check(setup_case(&mock, &state, events, 1, 200, &dispatch, &request,
                     &binding, &mmio, &hooks, &bridge) == 0,
          "prepare three-read view event with zero retire count");
    state.leases_code = 1;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && mock.start_count == 0 &&
          state.convert_calls == 0,
          "lease BUSY blocks conversion and START");
    state.leases_code = 0;
    state.convert_code = 1;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && mock.start_count == 0 &&
          state.clean_calls == 0,
          "converter BUSY blocks cache clean and START");
    state.convert_code = 0;
    state.clean_code = 1;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && mock.start_count == 0 &&
          state.converted && state.clean_calls == 1,
          "cache-clean barrier BUSY blocks START after conversion");
    state.clean_code = 0;
    state.source_ready_code = 1;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && mock.start_count == 0 &&
          state.cleaned,
          "materialized/cache-visible postcondition blocks START while BUSY");
    state.source_ready_code = 0;
    mock.complete_after = 2;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && mock.start_count == 1 &&
          mock.barrier_count == 1 && state.convert_calls == 2 &&
          state.clean_calls == 2,
          "actual V2 driver starts only after converter and clean barrier ready");
    check_command_words(&mock, &binding);
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && dispatch.pending &&
          !state.published,
          "delayed driver result stays pending");
    state.publish_code = 1;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && dispatch.pending &&
          !state.published && !zn_native_conv_driver_ownership_held_v2(&bridge.driver),
          "publication BUSY retains graph and scratch leases after driver ACK");
    state.publish_code = 0;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED && !dispatch.pending &&
          state.published && mock.start_count == 1 && mock.ack_count == 1,
          "RUN publishes once after actual driver result identity");

    check(zn_dispatch_next(&dispatch, &request) == 1 &&
          request.operation == ZN_DRAIN,
          "successful RUN advances to graph DRAIN");
    state.drain_code = 1;
    check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request, NULL) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && dispatch.pending &&
          !state.scratch_released,
          "DRAIN BUSY retains scratch and original graph refs");
    state.drain_code = 0;
    check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request, NULL) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED && !dispatch.pending,
          "DRAIN ACK follows graph IO/output-reader check");

    for (read_index = 0; read_index < binding.graph_read_count; ++read_index) {
        check(zn_dispatch_next(&dispatch, &request) == 1 &&
              request.operation == ZN_RETURN &&
              request.ref.generation == binding.graph_read_refs[read_index].generation,
              "dispatcher returns exact original graph ref order");
        if (read_index == 0) {
            state.return_code = 1;
            check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                       NULL) ==
                      ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && dispatch.pending &&
                  bridge.return_cursor == 0,
                  "RETURN BUSY retains current graph ref and cursor");
            state.return_code = 0;
        }
        code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request, NULL);
        check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED && !dispatch.pending,
              "each graph read RETURN is acknowledged by bridge");
    }
    check(bridge.stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_READS_RETURNED &&
          state.returned_mask == 7u && !state.scratch_released &&
          state.release_calls == 0,
          "all original refs return after DRAIN before scratch release");
    state.release_code = 1;
    check(zn_native_graph_conv_bridge_finish_v2(&bridge, &dispatch) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && !state.scratch_released &&
          state.return_calls == 4,
          "scratch BUSY retries release without resubmitting RETURN");
    state.release_code = 0;
    check(zn_native_graph_conv_bridge_finish_v2(&bridge, &dispatch) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_SCRATCH_RELEASED &&
          state.scratch_released && mock.start_count == 1 &&
          state.return_calls == 4,
          "finish releases scratch after terminal driver and all graph returns");
    check(zn_dispatch_next(&dispatch, &request) == 0 && dispatch.done,
          "zero-retire terminal event completes after explicit finish");
}

static void
test_finish_gates_next_event(void)
{
    BridgeMmio mock;
    HookState state;
    ZnEvent events[2];
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeGraphConvBindingV2 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativeGraphConvBridgeV2 bridge;
    ZnNativeGraphConvBridgeCodeV2 code;
    uint8_t index;

    make_event(&events[0], 9, 2, ZN_CONV);
    make_event(&events[1], 10, 0, ZN_ADD);
    events[1].has_destination = 0;
    check(setup_case(&mock, &state, events, 2, 201, &dispatch, &request,
                     &binding, &mmio, &hooks, &bridge) == 0,
          "prepare no-retire view followed by another graph event");
    check(submit_and_complete(&bridge, &dispatch, &request, &binding, &mock,
                              &state) == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED,
          "view Conv RUN reaches published success");
    check(zn_dispatch_next(&dispatch, &request) == 1 && request.operation == ZN_DRAIN &&
          zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request, NULL) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED,
          "view Conv DRAIN completes before reads return");
    for (index = 0; index < binding.graph_read_count; ++index) {
        check(zn_dispatch_next(&dispatch, &request) == 1 &&
              request.operation == ZN_RETURN,
              "next-event case reaches graph read RETURN");
        check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request, NULL) ==
                  ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED,
              "next-event case acknowledges original read RETURN");
    }
    check(zn_dispatch_next(&dispatch, &request) == 1 &&
          request.operation == ZN_RUN && request.event_index == 1,
          "zero-retire event advances directly to next event RUN");
    state.release_code = 1;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request, NULL);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY && dispatch.pending &&
          dispatch.request.tag == request.tag && !state.scratch_released,
          "next event stays unacknowledged while scratch release is BUSY");
    state.release_code = 0;
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request, NULL);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_SCRATCH_RELEASED &&
          dispatch.pending && dispatch.request.tag == request.tag &&
          state.scratch_released,
          "scratch is released before any next-event operation is acknowledged");
    check(zn_dispatch_ack(&dispatch, request.tag, request.operation, ZN_ACK_OK) == 0,
          "next event owner may proceed after scratch release handoff");
}

typedef enum InvalidKind {
    INVALID_MODEL_HASH,
    INVALID_EPOCH,
    INVALID_GRAPH_REF,
    INVALID_SCRATCH_EPOCH,
    INVALID_SCRATCH_ALIAS
} InvalidKind;

static void
test_invalid_bindings_and_requests(void)
{
    InvalidKind kind;

    for (kind = INVALID_MODEL_HASH; kind <= INVALID_SCRATCH_ALIAS; ++kind) {
        BridgeMmio mock;
        HookState state;
        ZnEvent events[1];
        ZnDispatch dispatch;
        ZnRequest request;
        ZnNativeGraphConvBindingV2 binding;
        ZnNativeConvMmioOpsV2 mmio;
        ZnNativeGraphConvHooksV2 hooks;
        ZnNativeGraphConvBridgeV2 bridge;

        make_event(&events[0], 9, 3, ZN_CONV);
        check(setup_case(&mock, &state, events, 1, 202u + (uint32_t)kind,
                         &dispatch, &request, &binding, &mmio, &hooks, &bridge) == 0,
              "prepare malformed-binding case");
        if (kind == INVALID_MODEL_HASH)
            binding.checkpoint_sha256[0] ^= 1;
        else if (kind == INVALID_EPOCH)
            ++binding.dispatch_epoch;
        else if (kind == INVALID_GRAPH_REF)
            ++binding.graph_read_refs[1].generation;
        else if (kind == INVALID_SCRATCH_EPOCH)
            ++binding.scratch.epoch;
        else {
            binding.scratch.base = events[0].destination.address;
            binding.source_span.base = binding.scratch.base;
            binding.command.source_base = binding.scratch.base;
            binding.command.source_lease_region_begin = binding.scratch.base;
            binding.command.source_lease_region_end.low =
                binding.scratch.base + binding.scratch.bytes;
        }
        check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                   &binding) ==
                  ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_INVALID_BINDING &&
              dispatch.fault && dispatch.pending && mock.write_count == 0 &&
              state.convert_calls == 0 && !state.scratch_released,
              "invalid model/epoch/ref/scratch identity rejected before conversion or START");
    }

    {
        BridgeMmio mock;
        HookState state;
        ZnEvent events[1];
        ZnDispatch dispatch;
        ZnRequest request;
        ZnRequest stale;
        ZnNativeGraphConvBindingV2 binding;
        ZnNativeConvMmioOpsV2 mmio;
        ZnNativeGraphConvHooksV2 hooks;
        ZnNativeGraphConvBridgeV2 bridge;

        make_event(&events[0], 9, 2, ZN_CONV);
        check(setup_case(&mock, &state, events, 1, 209, &dispatch, &request,
                         &binding, &mmio, &hooks, &bridge) == 0,
              "prepare stale request case");
        stale = request;
        ++stale.epoch;
        check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &stale,
                                                   &binding) ==
                  ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_STALE_REQUEST &&
              mock.write_count == 0 && state.convert_calls == 0 && !dispatch.fault,
              "stale request epoch rejected without mutating dispatcher or MMIO");
    }
}

static void
test_result_identity_and_publication_failure(void)
{
    BridgeMmio mock;
    HookState state;
    ZnEvent events[1];
    ZnDispatch dispatch;
    ZnRequest request;
    ZnNativeGraphConvBindingV2 binding;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativeGraphConvBridgeV2 bridge;
    ZnNativeGraphConvBridgeCodeV2 code;

    make_event(&events[0], 9, 2, ZN_CONV);
    check(setup_case(&mock, &state, events, 1, 210, &dispatch, &request,
                     &binding, &mmio, &hooks, &bridge) == 0,
          "prepare result-identity failure case");
    mock.result_source_generation_xor = 1;
    check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                               &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY,
          "start result-identity driver command");
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED && dispatch.fault &&
          dispatch.pending && mock.ack_count == 0 && !state.published &&
          !state.scratch_released &&
          zn_native_conv_driver_ownership_held_v2(&bridge.driver),
          "wrong scratch result generation poisons driver and retains leases");

    make_event(&events[0], 9, 2, ZN_CONV);
    check(setup_case(&mock, &state, events, 1, 211, &dispatch, &request,
                     &binding, &mmio, &hooks, &bridge) == 0,
          "prepare publication failure case");
    state.publish_code = -1;
    check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                               &binding) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY,
          "start publication failure command");
    code = zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
                                                &binding);
    check(code == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_FAILED && dispatch.fault &&
          dispatch.pending && mock.ack_count == 1 && !state.published &&
          !state.scratch_released && !zn_native_conv_driver_ownership_held_v2(&bridge.driver),
          "publication failure keeps graph and scratch leases without publishing");
}

int
main(void)
{
    test_success_multi_read_no_retire_and_finish_retry();
    test_finish_gates_next_event();
    test_invalid_bindings_and_requests();
    test_result_identity_and_publication_failure();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_GRAPH_CONV_BRIDGE_V2_HOST_FAIL count=%u\n", failures);
        return 1;
    }
    puts("NATIVE_GRAPH_CONV_BRIDGE_V2_HOST_PASS multi_read=3 no_retire=1 converter_gate=1 cache_barrier_gate=1 driver_protocol_only=1 publication_wait=1 read_return=1 scratch_finish_retry=1 next_event_gate=1 malformed_binding=5 stale_request=1 result_identity=1 publication_failure=1 arithmetic_claim=0");
    return 0;
}
