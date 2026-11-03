#ifndef Z100_NATIVE_CONV_MMIO_V1_H
#define Z100_NATIVE_CONV_MMIO_V1_H

/*
 * Declarative relative-register ABI for the proposed native Conv V3 bridge.
 * Offsets are byte offsets from a platform-assigned peripheral base. This
 * header deliberately supplies no physical base address and no driver.
 */
#include <stdint.h>
#include <stddef.h>

#define ZN_NATIVE_CONV_MMIO_ID_VALUE          UINT32_C(0x5A4E4331) /* "ZNC1" */
#define ZN_NATIVE_CONV_MMIO_ABI_VERSION       UINT32_C(0x00010000)
#define ZN_NATIVE_CONV_MMIO_MODEL_CRC32       UINT32_C(0x83F6CD55)
#define ZN_NATIVE_CONV_MMIO_PARAMETER_COUNT   UINT32_C(173)

enum ZnNativeConvMmioRegister {
    ZN_NC_REG_ID                    = 0x000,
    ZN_NC_REG_ABI_VERSION           = 0x004,
    ZN_NC_REG_CAPABILITIES          = 0x008,
    ZN_NC_REG_CONTROL               = 0x00C,
    ZN_NC_REG_STATUS                = 0x010,
    ZN_NC_REG_BACKEND_FAULT_CODE    = 0x014,
    ZN_NC_REG_BRIDGE_ERROR          = 0x018,
    ZN_NC_REG_COMMITTED_TILES       = 0x01C,

    ZN_NC_REG_SHADOW_COOKIE         = 0x040,
    ZN_NC_REG_SHADOW_EPOCH          = 0x044,
    ZN_NC_REG_SHADOW_EVENT          = 0x048,
    ZN_NC_REG_SHADOW_MODEL_CRC      = 0x04C,
    ZN_NC_REG_SHADOW_JOB_BASE       = 0x050,
    ZN_NC_REG_SHADOW_TOKEN_BASE     = 0x054,
    ZN_NC_REG_SHADOW_TAG_BASE       = 0x058,
    ZN_NC_REG_SHADOW_FLAGS          = 0x05C,
    ZN_NC_REG_SHADOW_SOURCE_BASE    = 0x060,
    ZN_NC_REG_SHADOW_SOURCE_GEN     = 0x064,
    ZN_NC_REG_SHADOW_SOURCE_BEGIN   = 0x068,
    ZN_NC_REG_SHADOW_SOURCE_END_LO  = 0x06C,
    ZN_NC_REG_SHADOW_SOURCE_END_HI  = 0x070,
    ZN_NC_REG_SHADOW_DEST_BASE      = 0x074,
    ZN_NC_REG_SHADOW_DEST_GEN       = 0x078,
    ZN_NC_REG_SHADOW_DEST_BEGIN     = 0x07C,
    ZN_NC_REG_SHADOW_DEST_END_LO    = 0x080,
    ZN_NC_REG_SHADOW_DEST_END_HI    = 0x084,
    ZN_NC_REG_SHADOW_PARAM_DIR_BASE = 0x088,
    ZN_NC_REG_SHADOW_PARAM_COUNT    = 0x08C,
    ZN_NC_REG_SHADOW_PARAM_BEGIN    = 0x090,
    ZN_NC_REG_SHADOW_PARAM_END_LO   = 0x094,
    ZN_NC_REG_SHADOW_PARAM_END_HI   = 0x098,
    ZN_NC_REG_SHADOW_LOAD_TIMEOUT   = 0x09C,
    ZN_NC_REG_SHADOW_PARAM_TIMEOUT  = 0x0A0,
    ZN_NC_REG_SHADOW_WRITE_TIMEOUT  = 0x0A4,
    ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT = 0x0A8,

    ZN_NC_REG_RESULT_COOKIE         = 0x100,
    ZN_NC_REG_RESULT_EPOCH          = 0x104,
    ZN_NC_REG_RESULT_EVENT          = 0x108,
    ZN_NC_REG_RESULT_MODEL_CRC      = 0x10C,
    ZN_NC_REG_RESULT_JOB_BASE       = 0x110,
    ZN_NC_REG_RESULT_TOKEN_BASE     = 0x114,
    ZN_NC_REG_RESULT_TAG_BASE       = 0x118,
    ZN_NC_REG_RESULT_DEST_GEN       = 0x11C,
    ZN_NC_REG_RESULT_TILES          = 0x120,
    ZN_NC_REG_RESULT_SOURCE_GEN     = 0x124
};

/* CAPABILITIES is a fixed feature bitmap for this ABI revision. */
#define ZN_NC_CAP_COMMAND_SHADOW             (UINT32_C(1) << 0)
#define ZN_NC_CAP_CANCEL_DRAIN               (UINT32_C(1) << 1)
#define ZN_NC_CAP_RESULT_SNAPSHOT            (UINT32_C(1) << 2)
#define ZN_NC_CAP_PREACCEPT_TIMEOUT          (UINT32_C(1) << 3)
#define ZN_NC_CAP_SOURCE_GENERATION_RESULT   (UINT32_C(1) << 4)
#define ZN_NC_CAP_END33                     (UINT32_C(1) << 5)
#define ZN_NC_CAP_VALID_MASK                UINT32_C(0x0000003F)

/* CONTROL is write-one-pulse. Exactly one operation bit may be written. */
#define ZN_NC_CONTROL_START                 (UINT32_C(1) << 0)
#define ZN_NC_CONTROL_ABORT_BEFORE_ACCEPT   (UINT32_C(1) << 1)
#define ZN_NC_CONTROL_CANCEL_ACCEPTED       (UINT32_C(1) << 2)
#define ZN_NC_CONTROL_ACK_RESULT            (UINT32_C(1) << 3)
#define ZN_NC_CONTROL_VALID_MASK            UINT32_C(0x0000000F)

/* STATUS is read-only; READY is frontend idle plus a quiet, healthy backend.
 * PREACCEPT_TIMEOUT clears with ACK_RESULT; RESULT_VALID holds until ACK. */
#define ZN_NC_STATUS_READY                  (UINT32_C(1) << 0)
#define ZN_NC_STATUS_COMMAND_PENDING        (UINT32_C(1) << 1)
#define ZN_NC_STATUS_ACCEPTED                (UINT32_C(1) << 2)
#define ZN_NC_STATUS_ACTIVE                  (UINT32_C(1) << 3)
#define ZN_NC_STATUS_DONE                    (UINT32_C(1) << 4)
#define ZN_NC_STATUS_FAULT                   (UINT32_C(1) << 5)
#define ZN_NC_STATUS_NEEDS_DRAIN             (UINT32_C(1) << 6)
#define ZN_NC_STATUS_DRAIN_COMPLETE          (UINT32_C(1) << 7)
#define ZN_NC_STATUS_RESULT_VALID            (UINT32_C(1) << 8)
#define ZN_NC_STATUS_PREACCEPT_TIMEOUT       (UINT32_C(1) << 9)

/* SHADOW_FLAGS: remaining bits must be zero. */
#define ZN_NC_SHADOW_FIRST_BANK               (UINT32_C(1) << 0)
#define ZN_NC_SHADOW_SOURCE_LEASE_VALID       (UINT32_C(1) << 1)
#define ZN_NC_SHADOW_DEST_RESERVATION_VALID   (UINT32_C(1) << 2)
#define ZN_NC_SHADOW_FLAGS_VALID_MASK         UINT32_C(0x00000007)

/* Each 33-bit exclusive endpoint uses END_LO plus END_HI[0]; END_HI[31:1]=0. */
#define ZN_NC_END33_HIGH_VALID_MASK           UINT32_C(0x00000001)
#define ZN_NC_END33_LIMIT_LO                  UINT32_C(0x00000000)
#define ZN_NC_END33_LIMIT_HI                  UINT32_C(0x00000001) /* 0x1_00000000 */

/* Bridge-local errors; BACKEND_FAULT_CODE is the raw four-bit RTL code. */
#define ZN_NC_BRIDGE_ERROR_NONE               UINT32_C(0)
#define ZN_NC_BRIDGE_ERROR_INVALID_SHADOW     UINT32_C(1)
#define ZN_NC_BRIDGE_ERROR_PREACCEPT_ABORT    UINT32_C(2)
#define ZN_NC_BRIDGE_ERROR_PREACCEPT_TIMEOUT  UINT32_C(3)
#define ZN_NC_BRIDGE_ERROR_ILLEGAL_CONTROL    UINT32_C(4)

/* Logical software representation; fields are written individually by offset. */
typedef struct ZnNativeConvEnd33 {
    uint32_t low;
    uint32_t high;
} ZnNativeConvEnd33;

typedef struct ZnNativeConvCommand {
    uint32_t request_cookie;
    uint32_t epoch;
    uint32_t event;
    uint32_t model_crc32;
    uint32_t job_base;
    uint32_t token_base;
    uint32_t tag_base;
    uint32_t flags;
    uint32_t source_base;
    uint32_t source_generation;
    uint32_t source_lease_region_begin;
    ZnNativeConvEnd33 source_lease_region_end;
    uint32_t destination_base;
    uint32_t destination_generation;
    uint32_t destination_reservation_region_begin;
    ZnNativeConvEnd33 destination_reservation_region_end;
    uint32_t parameter_directory_base;
    uint32_t parameter_count;
    uint32_t parameter_payload_begin;
    ZnNativeConvEnd33 parameter_payload_end;
    uint32_t load_timeout_cycles;
    uint32_t parameter_timeout_cycles;
    uint32_t write_timeout_cycles;
    uint32_t preaccept_timeout_cycles;
} ZnNativeConvCommand;

#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
_Static_assert(sizeof(uint32_t) == 4, "MMIO ABI requires 32-bit uint32_t");
_Static_assert(sizeof(ZnNativeConvEnd33) == 8, "33-bit endpoint has two register words");
_Static_assert(sizeof(ZnNativeConvCommand) == 27 * 4, "logical command is 27 words");
_Static_assert(offsetof(ZnNativeConvCommand, source_lease_region_end) == 11 * 4,
               "source endpoint words follow source lease begin");
_Static_assert(offsetof(ZnNativeConvCommand, destination_base) == 13 * 4,
               "destination words follow source endpoint");
_Static_assert(offsetof(ZnNativeConvCommand, parameter_directory_base) == 18 * 4,
               "parameter words follow destination endpoint");
_Static_assert(offsetof(ZnNativeConvCommand, preaccept_timeout_cycles) == 26 * 4,
               "preaccept timeout is final shadow word");
_Static_assert(ZN_NC_REG_CONTROL == 0x00C, "control register offset is ABI-stable");
_Static_assert(ZN_NC_REG_SHADOW_COOKIE == 0x040, "shadow window offset is ABI-stable");
_Static_assert(ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT == 0x0A8, "shadow window end is ABI-stable");
_Static_assert(ZN_NC_REG_RESULT_COOKIE == 0x100, "result window offset is ABI-stable");
_Static_assert((ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT & 3) == 0, "registers are 32-bit aligned");
_Static_assert((ZN_NC_REG_RESULT_SOURCE_GEN & 3) == 0, "registers are 32-bit aligned");
_Static_assert(ZN_NC_REG_RESULT_SOURCE_GEN < 0x200, "register map fits 512 bytes");
_Static_assert(ZN_NC_CAP_VALID_MASK == 0x3F, "capability bitmap is ABI-stable");
#endif

#endif /* Z100_NATIVE_CONV_MMIO_V1_H */
