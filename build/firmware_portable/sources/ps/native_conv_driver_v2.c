#include "native_conv_driver_v2.h"

#include <string.h>

enum {
    ZN_NC_ACK_KIND_NONE = 0,
    ZN_NC_ACK_KIND_SUCCESS = 1,
    ZN_NC_ACK_KIND_FAULT = 2,
    ZN_NC_ACK_KIND_LOCAL = 3
};

#define ZN_NC_STATUS_STATE_MASK (ZN_NC_STATUS_COMMAND_PENDING | \
                                 ZN_NC_STATUS_ACCEPTED | \
                                 ZN_NC_STATUS_ACTIVE | \
                                 ZN_NC_STATUS_DONE | \
                                 ZN_NC_STATUS_FAULT | \
                                 ZN_NC_STATUS_NEEDS_DRAIN | \
                                 ZN_NC_STATUS_RESULT_VALID | \
                                 ZN_NC_STATUS_PREACCEPT_TIMEOUT)

static ZnNativeConvDriverCodeV2
zn_nc_poison(ZnNativeConvDriverV2 *driver, ZnNativeConvDriverCodeV2 code)
{
    if (driver && driver->state != ZN_NATIVE_CONV_STATE_V2_ACK_UNCERTAIN)
        driver->state = ZN_NATIVE_CONV_STATE_V2_POISONED;
    return code;
}

static ZnNativeConvDriverCodeV2
zn_nc_read(ZnNativeConvDriverV2 *driver, uint32_t offset, uint32_t *value)
{
    if (!driver || !value || !driver->mmio.read32)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT);
    if (driver->mmio.read32(driver->mmio.context, offset, value) != 0)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_IO);
    return ZN_NATIVE_CONV_DRIVER_V2_OK;
}

static ZnNativeConvDriverCodeV2
zn_nc_write(ZnNativeConvDriverV2 *driver, uint32_t offset, uint32_t value)
{
    if (!driver || !driver->mmio.write32)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT);
    if (driver->mmio.write32(driver->mmio.context, offset, value) != 0)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_IO);
    return ZN_NATIVE_CONV_DRIVER_V2_OK;
}

static int
zn_nc_status_shape_valid(uint32_t status)
{
    if ((status & ~UINT32_C(0x000003ff)) != 0)
        return 0;
    if ((status & (ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_ACCEPTED)) ==
        (ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_ACCEPTED))
        return 0;
    if ((status & ZN_NC_STATUS_NEEDS_DRAIN) &&
        (status & ZN_NC_STATUS_DRAIN_COMPLETE))
        return 0;
    if ((status & ZN_NC_STATUS_DONE) &&
        (!(status & ZN_NC_STATUS_RESULT_VALID) ||
         (status & ZN_NC_STATUS_FAULT)))
        return 0;
    if ((status & ZN_NC_STATUS_RESULT_VALID) &&
        !(status & ZN_NC_STATUS_ACCEPTED))
        return 0;
    if ((status & ZN_NC_STATUS_PREACCEPT_TIMEOUT) &&
        (status & (ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_ACCEPTED)))
        return 0;
    if (status & ZN_NC_STATUS_READY) {
        if (!(status & ZN_NC_STATUS_DRAIN_COMPLETE) ||
            (status & ZN_NC_STATUS_STATE_MASK))
            return 0;
    }
    return 1;
}

static ZnNativeConvDriverCodeV2
zn_nc_read_snapshot(ZnNativeConvDriverV2 *driver)
{
    ZnNativeConvDriverCodeV2 code;

    code = zn_nc_read(driver, ZN_NC_REG_STATUS, &driver->last_status);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    code = zn_nc_read(driver, ZN_NC_REG_BRIDGE_ERROR,
                      &driver->last_bridge_error);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    code = zn_nc_read(driver, ZN_NC_REG_BACKEND_FAULT_CODE,
                      &driver->last_backend_fault_code);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    if (!zn_nc_status_shape_valid(driver->last_status) ||
        (driver->last_backend_fault_code & ~UINT32_C(0x0f)) != 0)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
    return ZN_NATIVE_CONV_DRIVER_V2_OK;
}

static int
zn_nc_is_healthy_ready(const ZnNativeConvDriverV2 *driver)
{
    return driver->last_bridge_error == ZN_NC_BRIDGE_ERROR_NONE &&
           driver->last_backend_fault_code == 0 &&
           (driver->last_status & ZN_NC_STATUS_READY) != 0 &&
           (driver->last_status & ZN_NC_STATUS_DRAIN_COMPLETE) != 0 &&
           (driver->last_status & ZN_NC_STATUS_STATE_MASK) == 0;
}

static ZnNativeConvDriverCodeV2
zn_nc_check_terminal_result(ZnNativeConvDriverV2 *driver, int is_fault)
{
    static const uint32_t offsets[10] = {
        ZN_NC_REG_RESULT_COOKIE, ZN_NC_REG_RESULT_EPOCH,
        ZN_NC_REG_RESULT_EVENT, ZN_NC_REG_RESULT_MODEL_CRC,
        ZN_NC_REG_RESULT_JOB_BASE, ZN_NC_REG_RESULT_TOKEN_BASE,
        ZN_NC_REG_RESULT_TAG_BASE, ZN_NC_REG_RESULT_DEST_GEN,
        ZN_NC_REG_RESULT_TILES, ZN_NC_REG_RESULT_SOURCE_GEN
    };
    uint32_t words[10];
    uint32_t index;
    ZnNativeConvDriverCodeV2 code;

    for (index = 0; index < 10; ++index) {
        code = zn_nc_read(driver, offsets[index], &words[index]);
        if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
            return code;
    }

    code = zn_nc_read_snapshot(driver);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    if (!(driver->last_status & ZN_NC_STATUS_RESULT_VALID) ||
        !(driver->last_status & ZN_NC_STATUS_ACCEPTED) ||
        (driver->last_bridge_error != ZN_NC_BRIDGE_ERROR_NONE))
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
    if (is_fault) {
        if (!(driver->last_status & ZN_NC_STATUS_FAULT) ||
            (driver->last_status & ZN_NC_STATUS_DONE) ||
            (driver->last_status & ZN_NC_STATUS_NEEDS_DRAIN) ||
            !(driver->last_status & ZN_NC_STATUS_DRAIN_COMPLETE))
            return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
    } else if (!(driver->last_status & ZN_NC_STATUS_DONE) ||
               (driver->last_status & (ZN_NC_STATUS_FAULT |
                                       ZN_NC_STATUS_ACTIVE |
                                       ZN_NC_STATUS_NEEDS_DRAIN)) ||
               !(driver->last_status & ZN_NC_STATUS_DRAIN_COMPLETE)) {
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
    }
    if (words[0] != driver->command.request_cookie ||
        words[1] != driver->command.epoch ||
        words[2] != driver->command.event ||
        words[3] != driver->command.model_crc32 ||
        words[4] != driver->command.job_base ||
        words[5] != driver->command.token_base ||
        words[6] != driver->command.tag_base ||
        words[7] != driver->command.destination_generation ||
        /* A drained fault may stop before any/all tiles commit. Identity
         * echoes remain exact; only fault progress may be below the plan. */
        (is_fault ? words[8] > driver->expected_tiles :
                    words[8] != driver->expected_tiles) ||
        words[9] != driver->command.source_generation) {
        driver->result_verified = 0;
        driver->state = ZN_NATIVE_CONV_STATE_V2_IDENTITY_REJECTED;
        return ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL;
    }

    driver->result.request_cookie = words[0];
    driver->result.epoch = words[1];
    driver->result.event = words[2];
    driver->result.model_crc32 = words[3];
    driver->result.job_base = words[4];
    driver->result.token_base = words[5];
    driver->result.tag_base = words[6];
    driver->result.destination_generation = words[7];
    driver->result.committed_tiles = words[8];
    driver->result.source_generation = words[9];
    driver->result_verified = 1;
    driver->result_is_fault = (uint8_t)(is_fault != 0);
    driver->state = is_fault ? ZN_NATIVE_CONV_STATE_V2_FAULT_RESULT :
                               ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT;
    return is_fault ? ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY :
                      ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY;
}

static ZnNativeConvDriverCodeV2
zn_nc_reconcile_ack(ZnNativeConvDriverV2 *driver)
{
    uint32_t status;
    uint32_t error;
    uint32_t fault_code;
    ZnNativeConvDriverCodeV2 code;

    code = zn_nc_read_snapshot(driver);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    status = driver->last_status;
    error = driver->last_bridge_error;
    fault_code = driver->last_backend_fault_code;
    if (error != ZN_NC_BRIDGE_ERROR_NONE)
        return ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL;

    if (driver->ack_kind == ZN_NC_ACK_KIND_SUCCESS) {
        if (!zn_nc_is_healthy_ready(driver) || fault_code != 0)
            return ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL;
        driver->state = ZN_NATIVE_CONV_STATE_V2_IDLE;
    } else if (driver->ack_kind == ZN_NC_ACK_KIND_FAULT) {
        if ((status & ZN_NC_STATUS_FAULT) == 0 ||
            (status & ZN_NC_STATUS_DRAIN_COMPLETE) == 0 ||
            (status & (ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_ACCEPTED |
                       ZN_NC_STATUS_DONE | ZN_NC_STATUS_NEEDS_DRAIN |
                       ZN_NC_STATUS_RESULT_VALID | ZN_NC_STATUS_PREACCEPT_TIMEOUT |
                       ZN_NC_STATUS_READY)) != 0)
            return ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL;
        /* V3 may keep ACTIVE high after a fault is drained. DRAIN_COMPLETE is
         * the physical-IO release condition; FAULT keeps this core unusable. */
        driver->state = ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT;
    } else if (driver->ack_kind == ZN_NC_ACK_KIND_LOCAL) {
        if (!zn_nc_is_healthy_ready(driver) || fault_code != 0)
            return ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL;
        driver->state = ZN_NATIVE_CONV_STATE_V2_IDLE;
    } else {
        return ZN_NATIVE_CONV_DRIVER_V2_STATE;
    }

    driver->ownership_held = 0;
    driver->accepted = 0;
    driver->ack_sent = 0;
    driver->ack_kind = ZN_NC_ACK_KIND_NONE;
    return driver->state == ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT ?
           ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT : ZN_NATIVE_CONV_DRIVER_V2_OK;
}

ZnNativeConvDriverCodeV2
zn_native_conv_driver_init_v2(ZnNativeConvDriverV2 *driver,
                              const ZnNativeConvMmioOpsV2 *mmio)
{
    if (!driver || !mmio || !mmio->read32 || !mmio->write32 ||
        !mmio->write_barrier)
        return ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT;
    memset(driver, 0, sizeof *driver);
    driver->mmio = *mmio;
    driver->state = ZN_NATIVE_CONV_STATE_V2_IDLE;
    return ZN_NATIVE_CONV_DRIVER_V2_OK;
}

ZnNativeConvDriverCodeV2
zn_native_conv_driver_submit_v2(ZnNativeConvDriverV2 *driver,
                                const ZnNativeConvCommand *command,
                                uint32_t expected_tiles)
{
    uint32_t id;
    uint32_t abi;
    uint32_t capabilities;
    uint32_t index;
    ZnNativeConvCommandStatus command_status;
    ZnNativeConvDriverCodeV2 code;

    if (!driver || !command || driver->state == ZN_NATIVE_CONV_STATE_V2_UNINITIALIZED ||
        !driver->mmio.read32 || !driver->mmio.write32 ||
        !driver->mmio.write_barrier || expected_tiles == 0 || expected_tiles > 255)
        return ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT;
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT)
        return ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT;
    if (driver->state != ZN_NATIVE_CONV_STATE_V2_IDLE)
        return ZN_NATIVE_CONV_DRIVER_V2_BUSY;

    command_status = zn_native_conv_command_encode_v1(command, driver->command_words);
    if (command_status != ZN_NATIVE_CONV_COMMAND_OK)
        return ZN_NATIVE_CONV_DRIVER_V2_INVALID;
    if (command->model_crc32 != ZN_NATIVE_CONV_MMIO_MODEL_CRC32)
        return ZN_NATIVE_CONV_DRIVER_V2_INVALID;

    code = zn_nc_read(driver, ZN_NC_REG_ID, &id);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    code = zn_nc_read(driver, ZN_NC_REG_ABI_VERSION, &abi);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    code = zn_nc_read(driver, ZN_NC_REG_CAPABILITIES, &capabilities);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    if (id != ZN_NATIVE_CONV_MMIO_ID_VALUE ||
        abi != ZN_NATIVE_CONV_MMIO_ABI_VERSION ||
        capabilities != ZN_NC_CAP_VALID_MASK)
        return ZN_NATIVE_CONV_DRIVER_V2_IDENTITY;

    code = zn_nc_read_snapshot(driver);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    if ((driver->last_status & ZN_NC_STATUS_FAULT) ||
        driver->last_backend_fault_code != 0) {
        driver->state = ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT;
        return ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT;
    }
    if (!zn_nc_is_healthy_ready(driver))
        return ZN_NATIVE_CONV_DRIVER_V2_BUSY;

    driver->command = *command;
    driver->expected_tiles = expected_tiles;
    driver->accepted = 0;
    driver->ownership_held = 0;
    driver->result_verified = 0;
    driver->result_is_fault = 0;
    driver->abort_sent = 0;
    driver->cancel_sent = 0;
    driver->ack_sent = 0;
    driver->ack_kind = ZN_NC_ACK_KIND_NONE;
    memset(&driver->result, 0, sizeof driver->result);

    for (index = 0; index < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++index) {
        code = zn_nc_write(driver, ZN_NC_REG_SHADOW_COOKIE + index * 4,
                           driver->command_words[index]);
        if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
            return code;
    }
    if (driver->mmio.write_barrier(driver->mmio.context) != 0)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_IO);

    /* START callback failure is ambiguous: it may have reached the device. */
    driver->ownership_held = 1;
    driver->state = ZN_NATIVE_CONV_STATE_V2_START_UNCERTAIN;
    code = zn_nc_write(driver, ZN_NC_REG_CONTROL, ZN_NC_CONTROL_START);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    driver->state = ZN_NATIVE_CONV_STATE_V2_PENDING;
    return ZN_NATIVE_CONV_DRIVER_V2_OK;
}

ZnNativeConvDriverCodeV2
zn_native_conv_driver_poll_v2(ZnNativeConvDriverV2 *driver)
{
    uint32_t status;
    uint32_t error;
    ZnNativeConvDriverCodeV2 code;

    if (!driver || driver->state == ZN_NATIVE_CONV_STATE_V2_UNINITIALIZED)
        return ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT;
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT)
        return ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT;
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_POISONED ||
        driver->state == ZN_NATIVE_CONV_STATE_V2_IDENTITY_REJECTED)
        return ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL;
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_IDLE)
        return ZN_NATIVE_CONV_DRIVER_V2_STATE;
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_ACK_UNCERTAIN) {
        code = zn_nc_reconcile_ack(driver);
        if (code == ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL)
            return ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS;
        return code;
    }
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT)
        return ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY;
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_FAULT_RESULT)
        return ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY;
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_LOCAL_ERROR)
        return ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY;

    code = zn_nc_read_snapshot(driver);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    status = driver->last_status;
    error = driver->last_bridge_error;

    if (error != ZN_NC_BRIDGE_ERROR_NONE) {
        if (error > ZN_NC_BRIDGE_ERROR_ILLEGAL_CONTROL ||
            (status & (ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_ACCEPTED |
                       ZN_NC_STATUS_ACTIVE | ZN_NC_STATUS_FAULT |
                       ZN_NC_STATUS_RESULT_VALID | ZN_NC_STATUS_DONE)) ||
            !(status & ZN_NC_STATUS_DRAIN_COMPLETE) ||
            driver->last_backend_fault_code != 0 ||
            ((status & ZN_NC_STATUS_PREACCEPT_TIMEOUT) != 0) !=
                (error == ZN_NC_BRIDGE_ERROR_PREACCEPT_TIMEOUT))
            return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
        driver->accepted = 0;
        driver->state = ZN_NATIVE_CONV_STATE_V2_LOCAL_ERROR;
        return ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY;
    }
    if ((status & ZN_NC_STATUS_PREACCEPT_TIMEOUT) != 0)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
    if ((status & ZN_NC_STATUS_FAULT) == 0 &&
        driver->last_backend_fault_code != 0)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);

    if (status & ZN_NC_STATUS_COMMAND_PENDING) {
        if (driver->accepted ||
            (status & (ZN_NC_STATUS_ACTIVE | ZN_NC_STATUS_DONE |
                       ZN_NC_STATUS_FAULT | ZN_NC_STATUS_NEEDS_DRAIN |
                       ZN_NC_STATUS_RESULT_VALID)))
            return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
        driver->state = ZN_NATIVE_CONV_STATE_V2_PENDING;
        return ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS;
    }
    if (status & ZN_NC_STATUS_ACCEPTED) {
        driver->accepted = 1;
        driver->ownership_held = 1;
        if (status & ZN_NC_STATUS_RESULT_VALID) {
            if (status & ZN_NC_STATUS_FAULT) {
                if ((status & (ZN_NC_STATUS_NEEDS_DRAIN |
                               ZN_NC_STATUS_DRAIN_COMPLETE)) !=
                    ZN_NC_STATUS_DRAIN_COMPLETE)
                    return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
                return zn_nc_check_terminal_result(driver, 1);
            }
            if (!(status & ZN_NC_STATUS_DONE) ||
                (status & (ZN_NC_STATUS_ACTIVE | ZN_NC_STATUS_NEEDS_DRAIN)) ||
                !(status & ZN_NC_STATUS_DRAIN_COMPLETE))
                return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
            return zn_nc_check_terminal_result(driver, 0);
        }
        if (status & ZN_NC_STATUS_DONE)
            return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
        driver->state = ((status & (ZN_NC_STATUS_FAULT |
                                    ZN_NC_STATUS_NEEDS_DRAIN)) != 0) ?
                        ZN_NATIVE_CONV_STATE_V2_DRAINING :
                        ZN_NATIVE_CONV_STATE_V2_ACCEPTED;
        return ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS;
    }

    if (status & ZN_NC_STATUS_FAULT) {
        if (!(status & ZN_NC_STATUS_DRAIN_COMPLETE) ||
            (status & ZN_NC_STATUS_NEEDS_DRAIN)) {
            driver->state = ZN_NATIVE_CONV_STATE_V2_DRAINING;
            return ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS;
        }
        /* Quiet is not identity evidence after this driver submitted a job.
         * A missing ACCEPTED/result record may indicate a lost frontend
         * snapshot, so retain caller ownership and require external recovery. */
        if (driver->ownership_held || driver->accepted)
            return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
        driver->state = ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT;
        return ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT;
    }

    /* If START might have reached hardware, READY without a pending/accepted
     * record cannot prove that the command was not consumed. Never retry it. */
    return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
}

static ZnNativeConvDriverCodeV2
zn_nc_send_cancel(ZnNativeConvDriverV2 *driver)
{
    ZnNativeConvDriverCodeV2 code;
    if (driver->cancel_sent)
        return ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS;
    driver->cancel_sent = 1;
    code = zn_nc_write(driver, ZN_NC_REG_CONTROL,
                       ZN_NC_CONTROL_CANCEL_ACCEPTED);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    driver->state = ZN_NATIVE_CONV_STATE_V2_DRAINING;
    driver->ownership_held = 1;
    return zn_native_conv_driver_poll_v2(driver);
}

ZnNativeConvDriverCodeV2
zn_native_conv_driver_timeout_v2(ZnNativeConvDriverV2 *driver)
{
    ZnNativeConvDriverCodeV2 code;

    if (!driver)
        return ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT;
    code = zn_native_conv_driver_poll_v2(driver);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS)
        return code;

    if (driver->accepted) {
        if (driver->cancel_sent)
            return ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS;
        return zn_nc_send_cancel(driver);
    }
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_PENDING) {
        if (!driver->abort_sent) {
            driver->abort_sent = 1;
            code = zn_nc_write(driver, ZN_NC_REG_CONTROL,
                               ZN_NC_CONTROL_ABORT_BEFORE_ACCEPT);
            if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
                return code;
            code = zn_native_conv_driver_poll_v2(driver);
            if (code != ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS)
                return code;
            if (driver->accepted)
                return zn_nc_send_cancel(driver);
        }
        return ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS;
    }
    return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
}

ZnNativeConvDriverCodeV2
zn_native_conv_driver_ack_v2(ZnNativeConvDriverV2 *driver)
{
    uint32_t status;
    uint32_t error;
    ZnNativeConvDriverCodeV2 code;

    if (!driver)
        return ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT;
    if (driver->state == ZN_NATIVE_CONV_STATE_V2_ACK_UNCERTAIN)
        return zn_nc_reconcile_ack(driver);
    if (driver->state != ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT &&
        driver->state != ZN_NATIVE_CONV_STATE_V2_FAULT_RESULT &&
        driver->state != ZN_NATIVE_CONV_STATE_V2_LOCAL_ERROR)
        return ZN_NATIVE_CONV_DRIVER_V2_STATE;
    if ((driver->state == ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT ||
         driver->state == ZN_NATIVE_CONV_STATE_V2_FAULT_RESULT) &&
        !driver->result_verified)
        return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);

    code = zn_nc_read_snapshot(driver);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    status = driver->last_status;
    error = driver->last_bridge_error;

    if (driver->state == ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT) {
        if (error != 0 || (status & (ZN_NC_STATUS_ACCEPTED |
                                     ZN_NC_STATUS_DONE |
                                     ZN_NC_STATUS_RESULT_VALID |
                                     ZN_NC_STATUS_DRAIN_COMPLETE)) !=
                          (ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_DONE |
                           ZN_NC_STATUS_RESULT_VALID | ZN_NC_STATUS_DRAIN_COMPLETE) ||
            (status & (ZN_NC_STATUS_FAULT | ZN_NC_STATUS_ACTIVE |
                       ZN_NC_STATUS_NEEDS_DRAIN)))
            return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
        driver->ack_kind = ZN_NC_ACK_KIND_SUCCESS;
    } else if (driver->state == ZN_NATIVE_CONV_STATE_V2_FAULT_RESULT) {
        if (error != 0 || (status & (ZN_NC_STATUS_ACCEPTED |
                                     ZN_NC_STATUS_FAULT |
                                     ZN_NC_STATUS_RESULT_VALID |
                                     ZN_NC_STATUS_DRAIN_COMPLETE)) !=
                          (ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_FAULT |
                           ZN_NC_STATUS_RESULT_VALID | ZN_NC_STATUS_DRAIN_COMPLETE) ||
            (status & ZN_NC_STATUS_NEEDS_DRAIN))
            return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
        /* ACTIVE may remain set on a sticky fault after every AXI transaction
         * is quiet; DRAIN_COMPLETE, not ACTIVE, gates this diagnostic ACK. */
        driver->ack_kind = ZN_NC_ACK_KIND_FAULT;
    } else {
        if (error == 0 || error > ZN_NC_BRIDGE_ERROR_ILLEGAL_CONTROL ||
            (status & (ZN_NC_STATUS_COMMAND_PENDING | ZN_NC_STATUS_ACCEPTED |
                       ZN_NC_STATUS_ACTIVE | ZN_NC_STATUS_FAULT |
                       ZN_NC_STATUS_DONE | ZN_NC_STATUS_RESULT_VALID |
                       ZN_NC_STATUS_NEEDS_DRAIN)) ||
            !(status & ZN_NC_STATUS_DRAIN_COMPLETE) ||
            driver->last_backend_fault_code != 0)
            return zn_nc_poison(driver, ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL);
        driver->ack_kind = ZN_NC_ACK_KIND_LOCAL;
    }

    driver->ack_sent = 1;
    driver->state = ZN_NATIVE_CONV_STATE_V2_ACK_UNCERTAIN;
    code = zn_nc_write(driver, ZN_NC_REG_CONTROL, ZN_NC_CONTROL_ACK_RESULT);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return code;
    code = zn_nc_reconcile_ack(driver);
    if (code == ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL)
        return ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL;
    return code;
}

uint8_t
zn_native_conv_driver_ownership_held_v2(const ZnNativeConvDriverV2 *driver)
{
    return driver ? driver->ownership_held : 1;
}
