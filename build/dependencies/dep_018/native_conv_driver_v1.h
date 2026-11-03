#ifndef Z100_NATIVE_CONV_DRIVER_V1_H
#define Z100_NATIVE_CONV_DRIVER_V1_H

#include "native_conv_command_v1.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef int (*ZnNativeConvRead32)(void *context, uint32_t offset, uint32_t *value);
typedef int (*ZnNativeConvWrite32)(void *context, uint32_t offset, uint32_t value);
typedef int (*ZnNativeConvWriteBarrier)(void *context);

/* Callbacks use relative byte offsets and return zero only on completed success.
 * The platform supplies the MMIO mapping/base address and ordering semantics. */
typedef struct ZnNativeConvMmioOps {
    void *context;
    ZnNativeConvRead32 read32;
    ZnNativeConvWrite32 write32;
    ZnNativeConvWriteBarrier write_barrier;
} ZnNativeConvMmioOps;

typedef enum ZnNativeConvDriverCode {
    ZN_NATIVE_CONV_DRIVER_OK = 0,
    ZN_NATIVE_CONV_DRIVER_IN_PROGRESS = 1,
    ZN_NATIVE_CONV_DRIVER_SUCCESS_READY = 2,
    ZN_NATIVE_CONV_DRIVER_FAULT_READY = 3,
    ZN_NATIVE_CONV_DRIVER_LOCAL_ERROR_READY = 4,
    ZN_NATIVE_CONV_DRIVER_ARGUMENT = -1,
    ZN_NATIVE_CONV_DRIVER_IO = -2,
    ZN_NATIVE_CONV_DRIVER_IDENTITY = -3,
    ZN_NATIVE_CONV_DRIVER_INVALID = -4,
    ZN_NATIVE_CONV_DRIVER_BUSY = -5,
    ZN_NATIVE_CONV_DRIVER_PROTOCOL = -6,
    ZN_NATIVE_CONV_DRIVER_STICKY_FAULT = -7,
    ZN_NATIVE_CONV_DRIVER_STATE = -8
} ZnNativeConvDriverCode;

typedef enum ZnNativeConvDriverState {
    ZN_NATIVE_CONV_STATE_UNINITIALIZED = 0,
    ZN_NATIVE_CONV_STATE_IDLE = 1,
    ZN_NATIVE_CONV_STATE_PENDING = 2,
    ZN_NATIVE_CONV_STATE_ACCEPTED = 3,
    ZN_NATIVE_CONV_STATE_DRAINING = 4,
    ZN_NATIVE_CONV_STATE_SUCCESS_RESULT = 5,
    ZN_NATIVE_CONV_STATE_FAULT_RESULT = 6,
    ZN_NATIVE_CONV_STATE_LOCAL_ERROR = 7,
    ZN_NATIVE_CONV_STATE_START_UNCERTAIN = 8,
    ZN_NATIVE_CONV_STATE_ACK_UNCERTAIN = 9,
    ZN_NATIVE_CONV_STATE_IDENTITY_REJECTED = 10,
    ZN_NATIVE_CONV_STATE_POISONED = 11,
    ZN_NATIVE_CONV_STATE_STICKY_FAULT = 12
} ZnNativeConvDriverState;

typedef struct ZnNativeConvResult {
    uint32_t request_cookie;
    uint32_t epoch;
    uint32_t event;
    uint32_t model_crc32;
    uint32_t job_base;
    uint32_t token_base;
    uint32_t tag_base;
    uint32_t destination_generation;
    uint32_t committed_tiles;
    uint32_t source_generation;
} ZnNativeConvResult;

typedef struct ZnNativeConvDriver {
    ZnNativeConvMmioOps mmio;
    ZnNativeConvDriverState state;
    ZnNativeConvCommand command;
    uint32_t command_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    ZnNativeConvResult result;
    uint32_t expected_tiles;
    uint32_t last_status;
    uint32_t last_bridge_error;
    uint32_t last_backend_fault_code;
    uint8_t accepted;
    uint8_t ownership_held;
    uint8_t result_verified;
    uint8_t result_is_fault;
    uint8_t abort_sent;
    uint8_t cancel_sent;
    uint8_t ack_sent;
    uint8_t ack_kind;
} ZnNativeConvDriver;

/* No physical base is stored. Do not reinitialize an instance while a command
 * may be pending, accepted, draining, or awaiting ACK. */
ZnNativeConvDriverCode
zn_native_conv_driver_init_v1(ZnNativeConvDriver *driver,
                              const ZnNativeConvMmioOps *mmio);

/* Validates identity, frozen model CRC, command, and READY health before the
 * first write. A successful call writes 27 words, barriers, then START once. */
ZnNativeConvDriverCode
zn_native_conv_driver_submit_v1(ZnNativeConvDriver *driver,
                                const ZnNativeConvCommand *command,
                                uint32_t expected_tiles);

/* One bounded status/result poll. It never ACKs or releases ownership. */
ZnNativeConvDriverCode
zn_native_conv_driver_poll_v1(ZnNativeConvDriver *driver);

/* Call when the caller's own wait budget expires. Pending commands use ABORT;
 * accepted commands use CANCEL. The status is reread after ABORT so a same-edge
 * acceptance race is converted to CANCEL. It never ACKs or releases ownership. */
ZnNativeConvDriverCode
zn_native_conv_driver_timeout_v1(ZnNativeConvDriver *driver);

/* Explicitly ACK a checked success, drained fault, or observed local bridge
 * error. Release is reported only after readback confirms the corresponding
 * frontend bookkeeping is clear and DRAIN_COMPLETE/health rules are satisfied. */
ZnNativeConvDriverCode
zn_native_conv_driver_ack_v1(ZnNativeConvDriver *driver);

uint8_t zn_native_conv_driver_ownership_held_v1(const ZnNativeConvDriver *driver);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_CONV_DRIVER_V1_H */
