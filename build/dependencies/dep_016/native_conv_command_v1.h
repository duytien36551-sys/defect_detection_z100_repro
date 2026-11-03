#ifndef Z100_NATIVE_CONV_COMMAND_V1_H
#define Z100_NATIVE_CONV_COMMAND_V1_H

/* Pure command validation/encoding. This API performs no MMIO or ownership IO. */
#include "native_conv_mmio_v1.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_CONV_COMMAND_WORD_COUNT 27u

typedef enum ZnNativeConvCommandStatus {
    ZN_NATIVE_CONV_COMMAND_OK = 0,
    ZN_NATIVE_CONV_COMMAND_INVALID = 1,
    ZN_NATIVE_CONV_COMMAND_NULL_ARGUMENT = 2
} ZnNativeConvCommandStatus;

/*
 * Match the V2 frontend's command-shadow admissibility checks. Source and
 * destination overlap, DDR mapping, and actual execution remain backend/system
 * responsibilities and are deliberately not checked here.
 */
ZnNativeConvCommandStatus
zn_native_conv_command_validate_v1(const ZnNativeConvCommand *command);

/*
 * Encode as 27 numeric 32-bit shadow words in ABI order. This is endian
 * independent and does not serialize the C struct representation. On error,
 * output_words is left byte-for-byte unchanged.
 */
ZnNativeConvCommandStatus
zn_native_conv_command_encode_v1(const ZnNativeConvCommand *command,
                                 uint32_t output_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT]);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_CONV_COMMAND_V1_H */
