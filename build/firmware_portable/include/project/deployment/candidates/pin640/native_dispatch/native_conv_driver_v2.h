#ifndef Z100_NATIVE_CONV_DRIVER_V2_H
#define Z100_NATIVE_CONV_DRIVER_V2_H

#include "native_conv_command_v1.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef int (*ZnNativeConvRead32V2)(void *context, uint32_t offset, uint32_t *value);
typedef int (*ZnNativeConvWrite32V2)(void *context, uint32_t offset, uint32_t value);
typedef int (*ZnNativeConvWriteBarrierV2)(void *context);

/* Callbacks use relative byte offsets and return zero only on completed success.
 * The platform supplies the MMIO mapping/base address and ordering semantics. */
typedef struct ZnNativeConvMmioOpsV2 {
    void *context;
    ZnNativeConvRead32V2 read32;
    ZnNativeConvWrite32V2 write32;
    ZnNativeConvWriteBarrierV2 write_barrier;
} ZnNativeConvMmioOpsV2;

typedef enum ZnNativeConvDriverCodeV2 {
    ZN_NATIVE_CONV_DRIVER_V2_OK = 0,
    ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS = 1,
    ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY = 2,
    ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY = 3,
    ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY = 4,
    ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT = -1,
    ZN_NATIVE_CONV_DRIVER_V2_IO = -2,
    ZN_NATIVE_CONV_DRIVER_V2_IDENTITY = -3,
    ZN_NATIVE_CONV_DRIVER_V2_INVALID = -4,
    ZN_NATIVE_CONV_DRIVER_V2_BUSY = -5,
    ZN_NATIVE_CONV_DRIVER_V2_PROTOCOL = -6,
    ZN_NATIVE_CONV_DRIVER_V2_STICKY_FAULT = -7,
    ZN_NATIVE_CONV_DRIVER_V2_STATE = -8
} ZnNativeConvDriverCodeV2;

typedef enum ZnNativeConvDriverStateV2 {
    ZN_NATIVE_CONV_STATE_V2_UNINITIALIZED = 0,
    ZN_NATIVE_CONV_STATE_V2_IDLE = 1,
    ZN_NATIVE_CONV_STATE_V2_PENDING = 2,
    ZN_NATIVE_CONV_STATE_V2_ACCEPTED = 3,
    ZN_NATIVE_CONV_STATE_V2_DRAINING = 4,
    ZN_NATIVE_CONV_STATE_V2_SUCCESS_RESULT = 5,
    ZN_NATIVE_CONV_STATE_V2_FAULT_RESULT = 6,
    ZN_NATIVE_CONV_STATE_V2_LOCAL_ERROR = 7,
    ZN_NATIVE_CONV_STATE_V2_START_UNCERTAIN = 8,
    ZN_NATIVE_CONV_STATE_V2_ACK_UNCERTAIN = 9,
    ZN_NATIVE_CONV_STATE_V2_IDENTITY_REJECTED = 10,
    ZN_NATIVE_CONV_STATE_V2_POISONED = 11,
    ZN_NATIVE_CONV_STATE_V2_STICKY_FAULT = 12
} ZnNativeConvDriverStateV2;

typedef struct ZnNativeConvResultV2 {
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
} ZnNativeConvResultV2;

typedef struct ZnNativeConvDriverV2 {
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeConvDriverStateV2 state;
    ZnNativeConvCommand command;
    uint32_t command_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    ZnNativeConvResultV2 result;
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
} ZnNativeConvDriverV2;

/* No physical base is stored. Do not reinitialize an instance while a command
 * may be pending, accepted, draining, or awaiting ACK. */
ZnNativeConvDriverCodeV2
zn_native_conv_driver_init_v2(ZnNativeConvDriverV2 *driver,
                              const ZnNativeConvMmioOpsV2 *mmio);

/* Validates identity, frozen model CRC, command, and READY health before the
 * first write. A successful call writes 27 words, barriers, then START once. */
ZnNativeConvDriverCodeV2
zn_native_conv_driver_submit_v2(ZnNativeConvDriverV2 *driver,
                                const ZnNativeConvCommand *command,
                                uint32_t expected_tiles);

/* One bounded status/result poll. It never ACKs or releases ownership. */
ZnNativeConvDriverCodeV2
zn_native_conv_driver_poll_v2(ZnNativeConvDriverV2 *driver);

/* Call when the caller's own wait budget expires. Pending commands use ABORT;
 * accepted commands use CANCEL. The status is reread after ABORT so a same-edge
 * acceptance race is converted to CANCEL. It never ACKs or releases ownership. */
ZnNativeConvDriverCodeV2
zn_native_conv_driver_timeout_v2(ZnNativeConvDriverV2 *driver);

/* Explicitly ACK a checked success, drained fault, or observed local bridge
 * error. Release is reported only after readback confirms the corresponding
 * frontend bookkeeping is clear and DRAIN_COMPLETE/health rules are satisfied. */
ZnNativeConvDriverCodeV2
zn_native_conv_driver_ack_v2(ZnNativeConvDriverV2 *driver);

uint8_t zn_native_conv_driver_ownership_held_v2(const ZnNativeConvDriverV2 *driver);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_CONV_DRIVER_V2_H */
