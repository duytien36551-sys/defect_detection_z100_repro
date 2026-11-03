#include "native_conv_driver_v1.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

enum { RESULT_WORDS = 10, WRITE_LOG_CAPACITY = 64 };

typedef struct MockDevice {
    uint32_t id;
    uint32_t abi;
    uint32_t capabilities;
    uint32_t status;
    uint32_t bridge_error;
    uint32_t fault_code;
    uint32_t shadow[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t result[RESULT_WORDS];
    uint32_t write_offsets[WRITE_LOG_CAPACITY];
    uint32_t write_values[WRITE_LOG_CAPACITY];
    unsigned int write_count;
    unsigned int read_count;
    unsigned int barrier_count;
    unsigned int start_count;
    unsigned int abort_count;
    unsigned int cancel_count;
    unsigned int ack_count;
    unsigned int fail_read_call;
    unsigned int fail_write_call;
    int fail_barrier;
    int fail_start_after_apply;
    int fail_ack_after_apply;
    int abort_accept_race;
} MockDevice;

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
mock_reset(MockDevice *mock)
{
    memset(mock, 0, sizeof *mock);
    mock->id = ZN_NATIVE_CONV_MMIO_ID_VALUE;
    mock->abi = ZN_NATIVE_CONV_MMIO_ABI_VERSION;
    mock->capabilities = ZN_NC_CAP_VALID_MASK;
    mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
}

static int
mock_read32(void *context, uint32_t offset, uint32_t *value)
{
    MockDevice *mock = (MockDevice *)context;
    unsigned int index;

    ++mock->read_count;
    if (mock->fail_read_call != 0 && mock->read_count == mock->fail_read_call)
        return -1;
    if (!value || (offset & 3u) != 0)
        return -1;

    switch (offset) {
    case ZN_NC_REG_ID: *value = mock->id; return 0;
    case ZN_NC_REG_ABI_VERSION: *value = mock->abi; return 0;
    case ZN_NC_REG_CAPABILITIES: *value = mock->capabilities; return 0;
    case ZN_NC_REG_STATUS: *value = mock->status; return 0;
    case ZN_NC_REG_BACKEND_FAULT_CODE: *value = mock->fault_code; return 0;
    case ZN_NC_REG_BRIDGE_ERROR: *value = mock->bridge_error; return 0;
    default:
        if (offset >= ZN_NC_REG_RESULT_COOKIE && offset <= ZN_NC_REG_RESULT_SOURCE_GEN) {
            index = (offset - ZN_NC_REG_RESULT_COOKIE) / 4u;
            if (index >= RESULT_WORDS)
                return -1;
            *value = mock->result[index];
            return 0;
        }
        return -1;
    }
}

static int
mock_write32(void *context, uint32_t offset, uint32_t value)
{
    MockDevice *mock = (MockDevice *)context;
    unsigned int call = mock->write_count + 1u;
    unsigned int index;
    int fail_after_apply = 0;

    if (mock->fail_write_call != 0 && call == mock->fail_write_call)
        return -1;
    if (mock->write_count >= WRITE_LOG_CAPACITY)
        return -1;
    mock->write_offsets[mock->write_count] = offset;
    mock->write_values[mock->write_count] = value;
    ++mock->write_count;

    if (offset >= ZN_NC_REG_SHADOW_COOKIE && offset <= ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT) {
        index = (offset - ZN_NC_REG_SHADOW_COOKIE) / 4u;
        if (index >= ZN_NATIVE_CONV_COMMAND_WORD_COUNT)
            return -1;
        mock->shadow[index] = value;
        return 0;
    }
    if (offset != ZN_NC_REG_CONTROL)
        return -1;

    switch (value) {
    case ZN_NC_CONTROL_START:
        ++mock->start_count;
        mock->status = ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_DRAIN_COMPLETE;
        fail_after_apply = mock->fail_start_after_apply;
        break;
    case ZN_NC_CONTROL_ABORT_BEFORE_ACCEPT:
        ++mock->abort_count;
        if (mock->abort_accept_race) {
            mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE |
                           ZN_NC_STATUS_DRAIN_COMPLETE;
        } else {
            mock->bridge_error = ZN_NC_BRIDGE_ERROR_PREACCEPT_ABORT;
            mock->status = ZN_NC_STATUS_DRAIN_COMPLETE;
        }
        break;
    case ZN_NC_CONTROL_CANCEL_ACCEPTED:
        ++mock->cancel_count;
        mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE |
                       ZN_NC_STATUS_FAULT | ZN_NC_STATUS_NEEDS_DRAIN;
        break;
    case ZN_NC_CONTROL_ACK_RESULT:
        ++mock->ack_count;
        if (mock->bridge_error != ZN_NC_BRIDGE_ERROR_NONE) {
            mock->bridge_error = ZN_NC_BRIDGE_ERROR_NONE;
            mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
            mock->fault_code = 0;
        } else if (mock->status & ZN_NC_STATUS_FAULT) {
            mock->status = ZN_NC_STATUS_FAULT | ZN_NC_STATUS_ACTIVE |
                           ZN_NC_STATUS_DRAIN_COMPLETE;
        } else {
            mock->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
        }
        fail_after_apply = mock->fail_ack_after_apply;
        break;
    default:
        return -1;
    }
    return fail_after_apply ? -1 : 0;
}

static int
mock_barrier(void *context)
{
    MockDevice *mock = (MockDevice *)context;
    ++mock->barrier_count;
    return mock->fail_barrier ? -1 : 0;
}

static ZnNativeConvMmioOps
mock_ops(MockDevice *mock)
{
    ZnNativeConvMmioOps ops;
    ops.context = mock;
    ops.read32 = mock_read32;
    ops.write32 = mock_write32;
    ops.write_barrier = mock_barrier;
    return ops;
}

static void
make_command(ZnNativeConvCommand *command)
{
    memset(command, 0, sizeof *command);
    command->request_cookie = UINT32_C(0xc0decafe);
    command->epoch = 200;
    command->event = 1;
    command->model_crc32 = ZN_NATIVE_CONV_MMIO_MODEL_CRC32;
    command->job_base = 1;
    command->token_base = 4100;
    command->tag_base = UINT32_C(0x53000000);
    command->flags = ZN_NC_SHADOW_FLAGS_VALID_MASK;
    command->source_base = UINT32_C(0x10000000);
    command->source_generation = 6901;
    command->source_lease_region_begin = UINT32_C(0x10000000);
    command->source_lease_region_end.low = UINT32_C(0x10190000);
    command->destination_base = UINT32_C(0x30000000);
    command->destination_generation = 8201;
    command->destination_reservation_region_begin = UINT32_C(0x30000000);
    command->destination_reservation_region_end.low = UINT32_C(0x30200000);
    command->parameter_directory_base = UINT32_C(0x21000000);
    command->parameter_count = 173;
    command->parameter_payload_begin = UINT32_C(0x20000000);
    command->parameter_payload_end.low = UINT32_C(0x202fa500);
    command->load_timeout_cycles = 5000000;
    command->parameter_timeout_cycles = 5000000;
    command->write_timeout_cycles = 1000000;
    command->preaccept_timeout_cycles = 5000000;
}

static void
set_success_result(MockDevice *mock, const ZnNativeConvCommand *command,
                   uint32_t tiles)
{
    mock->result[0] = command->request_cookie;
    mock->result[1] = command->epoch;
    mock->result[2] = command->event;
    mock->result[3] = command->model_crc32;
    mock->result[4] = command->job_base;
    mock->result[5] = command->token_base;
    mock->result[6] = command->tag_base;
    mock->result[7] = command->destination_generation;
    mock->result[8] = tiles;
    mock->result[9] = command->source_generation;
}

static void
set_success_terminal(MockDevice *mock, const ZnNativeConvCommand *command)
{
    set_success_result(mock, command, 16);
    mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_DONE |
                   ZN_NC_STATUS_DRAIN_COMPLETE | ZN_NC_STATUS_RESULT_VALID;
    mock->bridge_error = 0;
    mock->fault_code = 0;
}

static void
set_fault_terminal(MockDevice *mock, const ZnNativeConvCommand *command,
                   int active)
{
    set_success_result(mock, command, 16);
    mock->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_FAULT |
                   ZN_NC_STATUS_DRAIN_COMPLETE | ZN_NC_STATUS_RESULT_VALID;
    if (active)
        mock->status |= ZN_NC_STATUS_ACTIVE;
    mock->bridge_error = 0;
    mock->fault_code = 0; /* STATUS.FAULT remains authoritative. */
}

static void
init_driver(MockDevice *mock, ZnNativeConvDriver *driver)
{
    ZnNativeConvMmioOps ops = mock_ops(mock);
    check(zn_native_conv_driver_init_v1(driver, &ops) == ZN_NATIVE_CONV_DRIVER_OK,
          "driver initialization");
}

static void
test_normal_order_result_ack(void)
{
    MockDevice mock;
    ZnNativeConvDriver driver;
    ZnNativeConvCommand command;
    uint32_t expected[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    unsigned int index;

    mock_reset(&mock);
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) == ZN_NATIVE_CONV_DRIVER_OK,
          "normal submit succeeds");
    check(mock.write_count == 28 && mock.start_count == 1 && mock.barrier_count == 1,
          "27 shadow writes, one barrier, one START");
    check(zn_native_conv_command_encode_v1(&command, expected) == ZN_NATIVE_CONV_COMMAND_OK,
          "expected command encoding");
    for (index = 0; index < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++index) {
        check(mock.write_offsets[index] == ZN_NC_REG_SHADOW_COOKIE + index * 4u,
              "shadow offsets are ordered and contiguous");
        check(mock.write_values[index] == expected[index],
              "shadow data matches validated command");
    }
    check(mock.write_offsets[27] == ZN_NC_REG_CONTROL &&
          mock.write_values[27] == ZN_NC_CONTROL_START,
          "START follows barrier and all shadow words");
    check(zn_native_conv_driver_ownership_held_v1(&driver) == 1,
          "ownership held once START may have been issued");

    set_success_terminal(&mock, &command);
    check(zn_native_conv_driver_poll_v1(&driver) == ZN_NATIVE_CONV_DRIVER_SUCCESS_READY,
          "normal result identity accepted");
    check(driver.result_verified && driver.result.committed_tiles == 16,
          "complete result is captured");
    check(zn_native_conv_driver_ownership_held_v1(&driver) == 1 && mock.ack_count == 0,
          "poll does not release or auto-ACK");
    check(zn_native_conv_driver_ack_v1(&driver) == ZN_NATIVE_CONV_DRIVER_OK,
          "explicit success ACK and readback");
    check(zn_native_conv_driver_ownership_held_v1(&driver) == 0 &&
          driver.state == ZN_NATIVE_CONV_STATE_IDLE && mock.ack_count == 1,
          "release only after ACK readback confirms READY");
    check(mock.write_count == 29, "normal callchain writes exactly one ACK");
}

static void
test_identity_and_invalid_command_no_writes(void)
{
    MockDevice mock;
    ZnNativeConvDriver driver;
    ZnNativeConvCommand command;

    mock_reset(&mock);
    mock.id ^= UINT32_C(1);
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_IDENTITY, "wrong device ID rejected");
    check(mock.write_count == 0 && mock.barrier_count == 0,
          "wrong identity performs no writes");

    mock_reset(&mock);
    mock.abi ^= UINT32_C(1);
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_IDENTITY, "wrong ABI rejected");
    check(mock.write_count == 0 && mock.barrier_count == 0,
          "wrong ABI performs no writes");

    mock_reset(&mock);
    mock.capabilities ^= UINT32_C(1);
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_IDENTITY, "wrong capabilities rejected");
    check(mock.write_count == 0 && mock.barrier_count == 0,
          "wrong capabilities perform no writes");

    mock_reset(&mock);
    make_command(&command);
    command.event = UINT32_C(0x101);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_INVALID, "invalid command rejected locally");
    check(mock.write_count == 0 && mock.read_count == 0 && mock.barrier_count == 0,
          "invalid command performs no MMIO");

    mock_reset(&mock);
    make_command(&command);
    command.model_crc32 ^= UINT32_C(1);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_INVALID, "wrong model CRC rejected");
    check(mock.write_count == 0 && mock.read_count == 0 && mock.barrier_count == 0,
          "wrong model CRC performs no MMIO");

    mock_reset(&mock);
    make_command(&command);
    mock.status = ZN_NC_STATUS_DRAIN_COMPLETE;
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_BUSY, "unready backend rejected");
    check(mock.write_count == 0 && mock.barrier_count == 0,
          "unready backend performs no writes");

    mock_reset(&mock);
    make_command(&command);
    mock.status = ZN_NC_STATUS_FAULT | ZN_NC_STATUS_DRAIN_COMPLETE;
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_STICKY_FAULT, "sticky backend fault blocks START");
    check(mock.write_count == 0, "sticky fault performs no writes");
}

static void
test_preaccept_abort(void)
{
    MockDevice mock;
    ZnNativeConvDriver driver;
    ZnNativeConvCommand command;
    ZnNativeConvDriverCode code;

    mock_reset(&mock);
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) == ZN_NATIVE_CONV_DRIVER_OK,
          "preaccept abort setup");
    code = zn_native_conv_driver_timeout_v1(&driver);
    check(code == ZN_NATIVE_CONV_DRIVER_LOCAL_ERROR_READY,
          "pending timeout uses preaccept ABORT");
    check(mock.abort_count == 1 && mock.cancel_count == 0 && mock.ack_count == 0,
          "preaccept abort does not CANCEL or auto-ACK");
    check(zn_native_conv_driver_ownership_held_v1(&driver) == 1,
          "local abort error retains caller ownership until ACK");
    check(driver.last_bridge_error == ZN_NC_BRIDGE_ERROR_PREACCEPT_ABORT,
          "preaccept abort bridge error observed");
    check(zn_native_conv_driver_ack_v1(&driver) == ZN_NATIVE_CONV_DRIVER_OK,
          "explicit preaccept error ACK and READY readback");
    check(zn_native_conv_driver_ownership_held_v1(&driver) == 0,
          "unconsumed ownership released only after error ACK/readback");
}

static void
test_acceptance_race_then_cancel(void)
{
    MockDevice mock;
    ZnNativeConvDriver driver;
    ZnNativeConvCommand command;
    ZnNativeConvDriverCode code;

    mock_reset(&mock);
    mock.abort_accept_race = 1;
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) == ZN_NATIVE_CONV_DRIVER_OK,
          "accept race setup");
    code = zn_native_conv_driver_timeout_v1(&driver);
    check(code == ZN_NATIVE_CONV_DRIVER_IN_PROGRESS,
          "same-edge acceptance wins ABORT and enters drain");
    check(mock.abort_count == 1 && mock.cancel_count == 1 && mock.ack_count == 0,
          "acceptance race sends ABORT once then CANCEL once");
    check(driver.accepted && driver.cancel_sent &&
          zn_native_conv_driver_ownership_held_v1(&driver) == 1,
          "race keeps accepted command and memory ownership");

    set_fault_terminal(&mock, &command, 1);
    check(zn_native_conv_driver_poll_v1(&driver) == ZN_NATIVE_CONV_DRIVER_FAULT_READY,
          "drained fault result accepted with ACTIVE still set");
    check((driver.last_status & ZN_NC_STATUS_ACTIVE) != 0 &&
          (driver.last_status & ZN_NC_STATUS_DRAIN_COMPLETE) != 0 &&
          zn_native_conv_driver_ownership_held_v1(&driver) == 1,
          "fault drain result remains owned until explicit ACK");
    check(zn_native_conv_driver_ack_v1(&driver) == ZN_NATIVE_CONV_DRIVER_STICKY_FAULT,
          "fault ACK clears frontend snapshot but preserves backend sticky fault");
    check(driver.state == ZN_NATIVE_CONV_STATE_STICKY_FAULT &&
          zn_native_conv_driver_ownership_held_v1(&driver) == 0,
          "drained fault releases memory but prevents core reuse");
    {
        unsigned int writes_before = mock.write_count;
        check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
              ZN_NATIVE_CONV_DRIVER_STICKY_FAULT,
              "post-fault command rejected without reset");
        check(mock.write_count == writes_before, "sticky-fault re-submit emits no writes");
    }
}

static void
test_fault_drain_requires_quiet(void)
{
    MockDevice mock;
    ZnNativeConvDriver driver;
    ZnNativeConvCommand command;

    mock_reset(&mock);
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) == ZN_NATIVE_CONV_DRIVER_OK,
          "fault-drain setup");
    mock.status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE |
                  ZN_NC_STATUS_FAULT | ZN_NC_STATUS_NEEDS_DRAIN;
    check(zn_native_conv_driver_poll_v1(&driver) == ZN_NATIVE_CONV_DRIVER_IN_PROGRESS,
          "fault without quiet drain remains in progress");
    check(zn_native_conv_driver_ownership_held_v1(&driver) == 1 && mock.ack_count == 0,
          "nonquiet fault cannot release or ACK");

    set_fault_terminal(&mock, &command, 1);
    check(zn_native_conv_driver_poll_v1(&driver) == ZN_NATIVE_CONV_DRIVER_FAULT_READY,
          "quiet drained fault snapshot is observable despite ACTIVE=1");
    check(zn_native_conv_driver_ownership_held_v1(&driver) == 1,
          "ownership remains until fault result is acknowledged");
}

static void
test_each_result_identity_mutation(void)
{
    unsigned int field;
    for (field = 0; field < RESULT_WORDS; ++field) {
        MockDevice mock;
        ZnNativeConvDriver driver;
        ZnNativeConvCommand command;
        ZnNativeConvDriverCode code;

        mock_reset(&mock);
        make_command(&command);
        init_driver(&mock, &driver);
        check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
              ZN_NATIVE_CONV_DRIVER_OK, "identity-mutation setup");
        set_success_terminal(&mock, &command);
        mock.result[field] ^= UINT32_C(1);
        code = zn_native_conv_driver_poll_v1(&driver);
        check(code == ZN_NATIVE_CONV_DRIVER_PROTOCOL &&
              driver.state == ZN_NATIVE_CONV_STATE_IDENTITY_REJECTED,
              "each of ten result fields is checked");
        check(zn_native_conv_driver_ownership_held_v1(&driver) == 1 &&
              mock.ack_count == 0,
              "identity mismatch cannot ACK or release ownership");
        if (field == 1) {
            check(mock.result[0] == command.request_cookie &&
                  mock.result[1] != command.epoch,
                  "same cookie with a different epoch is rejected");
        }
    }
}

static void
test_callback_failures_fail_closed(void)
{
    MockDevice mock;
    ZnNativeConvDriver driver;
    ZnNativeConvCommand command;
    unsigned int writes_before;

    mock_reset(&mock);
    mock.fail_read_call = 1;
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_IO && mock.write_count == 0,
          "read callback failure fails closed before writes");

    mock_reset(&mock);
    mock.fail_write_call = 5;
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_IO && mock.start_count == 0 &&
          zn_native_conv_driver_ownership_held_v1(&driver) == 0,
          "shadow callback failure cannot reach START");

    mock_reset(&mock);
    mock.fail_barrier = 1;
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_IO && mock.start_count == 0,
          "barrier failure prevents START");

    mock_reset(&mock);
    mock.fail_start_after_apply = 1;
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_IO && mock.start_count == 1 &&
          zn_native_conv_driver_ownership_held_v1(&driver) == 1,
          "ambiguous START callback failure retains ownership and is not retried");
    writes_before = mock.write_count;
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) ==
          ZN_NATIVE_CONV_DRIVER_BUSY && mock.write_count == writes_before,
          "ambiguous START cannot be duplicated");

    mock_reset(&mock);
    make_command(&command);
    init_driver(&mock, &driver);
    check(zn_native_conv_driver_submit_v1(&driver, &command, 16) == ZN_NATIVE_CONV_DRIVER_OK,
          "ambiguous ACK setup");
    set_success_terminal(&mock, &command);
    check(zn_native_conv_driver_poll_v1(&driver) == ZN_NATIVE_CONV_DRIVER_SUCCESS_READY,
          "ambiguous ACK result ready");
    mock.fail_ack_after_apply = 1;
    check(zn_native_conv_driver_ack_v1(&driver) == ZN_NATIVE_CONV_DRIVER_IO &&
          zn_native_conv_driver_ownership_held_v1(&driver) == 1,
          "ambiguous ACK retains ownership until readback");
    check(zn_native_conv_driver_poll_v1(&driver) == ZN_NATIVE_CONV_DRIVER_OK &&
          zn_native_conv_driver_ownership_held_v1(&driver) == 0,
          "ACK uncertainty resolves only by safe readback");
}

int
main(void)
{
    test_normal_order_result_ack();
    test_identity_and_invalid_command_no_writes();
    test_preaccept_abort();
    test_acceptance_race_then_cancel();
    test_fault_drain_requires_quiet();
    test_each_result_identity_mutation();
    test_callback_failures_fail_closed();
    if (failures != 0) {
        fprintf(stderr, "NATIVE_CONV_DRIVER_HOST_FAIL failures=%u\n", failures);
        return 1;
    }
    puts("NATIVE_CONV_DRIVER_HOST_PASS normal=1 no_write_gates=7 abort_pending=1 accept_race_cancel=1 fault_active_drain=1 quiet_gate=1 result_mutations=10 same_cookie_epoch=1 sticky_fault=1 callback_failclosed=5");
    return 0;
}
