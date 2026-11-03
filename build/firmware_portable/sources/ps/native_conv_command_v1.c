#include "native_conv_command_v1.h"

#include <string.h>

static uint64_t
zn_nc_end33_value(const ZnNativeConvEnd33 *end)
{
    return ((uint64_t)end->high << 32) | (uint64_t)end->low;
}

static int
zn_nc_end33_is_valid(const ZnNativeConvEnd33 *end)
{
    uint64_t value;

    if (end->high & ~ZN_NC_END33_HIGH_VALID_MASK)
        return 0;
    value = zn_nc_end33_value(end);
    return value <= UINT64_C(0x100000000);
}

ZnNativeConvCommandStatus
zn_native_conv_command_validate_v1(const ZnNativeConvCommand *command)
{
    uint64_t source_end;
    uint64_t destination_end;
    uint64_t payload_end;
    uint64_t directory_bytes;
    uint64_t directory_end;

    if (!command)
        return ZN_NATIVE_CONV_COMMAND_NULL_ARGUMENT;

    if (command->epoch == 0 || command->job_base == 0 ||
        command->token_base == 0 || command->tag_base == 0 ||
        (command->event & UINT32_C(0xffffff00)) != 0 ||
        command->model_crc32 != ZN_NATIVE_CONV_MMIO_MODEL_CRC32 ||
        (command->flags & ~ZN_NC_SHADOW_FLAGS_VALID_MASK) != 0 ||
        (command->flags & (ZN_NC_SHADOW_SOURCE_LEASE_VALID |
                           ZN_NC_SHADOW_DEST_RESERVATION_VALID)) !=
            (ZN_NC_SHADOW_SOURCE_LEASE_VALID |
             ZN_NC_SHADOW_DEST_RESERVATION_VALID) ||
        command->source_generation == 0 || command->destination_generation == 0)
        return ZN_NATIVE_CONV_COMMAND_INVALID;

    if ((command->source_base & UINT32_C(0x3f)) != 0 ||
        (command->source_lease_region_begin & UINT32_C(0x3f)) != 0 ||
        !zn_nc_end33_is_valid(&command->source_lease_region_end) ||
        (command->source_lease_region_end.low & UINT32_C(0x3f)) != 0 ||
        (command->destination_base & UINT32_C(0x3f)) != 0 ||
        (command->destination_reservation_region_begin & UINT32_C(0x3f)) != 0 ||
        !zn_nc_end33_is_valid(&command->destination_reservation_region_end) ||
        (command->destination_reservation_region_end.low & UINT32_C(0x3f)) != 0)
        return ZN_NATIVE_CONV_COMMAND_INVALID;

    source_end = zn_nc_end33_value(&command->source_lease_region_end);
    if ((uint64_t)command->source_base < command->source_lease_region_begin ||
        (uint64_t)command->source_base >= source_end ||
        (uint64_t)command->source_lease_region_begin >= source_end)
        return ZN_NATIVE_CONV_COMMAND_INVALID;

    destination_end = zn_nc_end33_value(&command->destination_reservation_region_end);
    if ((uint64_t)command->destination_base <
            command->destination_reservation_region_begin ||
        (uint64_t)command->destination_base >= destination_end ||
        (uint64_t)command->destination_reservation_region_begin >= destination_end)
        return ZN_NATIVE_CONV_COMMAND_INVALID;

    if ((command->parameter_directory_base & UINT32_C(0x3f)) != 0 ||
        command->parameter_count == 0 ||
        command->parameter_count > ZN_NATIVE_CONV_MMIO_PARAMETER_COUNT ||
        (command->parameter_payload_begin & UINT32_C(0x3f)) != 0 ||
        !zn_nc_end33_is_valid(&command->parameter_payload_end))
        return ZN_NATIVE_CONV_COMMAND_INVALID;

    payload_end = zn_nc_end33_value(&command->parameter_payload_end);
    if (payload_end <= command->parameter_payload_begin)
        return ZN_NATIVE_CONV_COMMAND_INVALID;

    directory_bytes = (((uint64_t)command->parameter_count + UINT64_C(1)) >> 1)
                      << 6;
    directory_end = (uint64_t)command->parameter_directory_base + directory_bytes;
    if (directory_end > UINT64_C(0x100000000))
        return ZN_NATIVE_CONV_COMMAND_INVALID;

    if (command->load_timeout_cycles == 0 ||
        command->parameter_timeout_cycles == 0 ||
        command->write_timeout_cycles == 0 ||
        command->preaccept_timeout_cycles == 0)
        return ZN_NATIVE_CONV_COMMAND_INVALID;

    return ZN_NATIVE_CONV_COMMAND_OK;
}

ZnNativeConvCommandStatus
zn_native_conv_command_encode_v1(
    const ZnNativeConvCommand *command,
    uint32_t output_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT])
{
    uint32_t words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    ZnNativeConvCommandStatus status;

    if (!command || !output_words)
        return ZN_NATIVE_CONV_COMMAND_NULL_ARGUMENT;

    status = zn_native_conv_command_validate_v1(command);
    if (status != ZN_NATIVE_CONV_COMMAND_OK)
        return status;

    words[0] = command->request_cookie;
    words[1] = command->epoch;
    words[2] = command->event;
    words[3] = command->model_crc32;
    words[4] = command->job_base;
    words[5] = command->token_base;
    words[6] = command->tag_base;
    words[7] = command->flags;
    words[8] = command->source_base;
    words[9] = command->source_generation;
    words[10] = command->source_lease_region_begin;
    words[11] = command->source_lease_region_end.low;
    words[12] = command->source_lease_region_end.high;
    words[13] = command->destination_base;
    words[14] = command->destination_generation;
    words[15] = command->destination_reservation_region_begin;
    words[16] = command->destination_reservation_region_end.low;
    words[17] = command->destination_reservation_region_end.high;
    words[18] = command->parameter_directory_base;
    words[19] = command->parameter_count;
    words[20] = command->parameter_payload_begin;
    words[21] = command->parameter_payload_end.low;
    words[22] = command->parameter_payload_end.high;
    words[23] = command->load_timeout_cycles;
    words[24] = command->parameter_timeout_cycles;
    words[25] = command->write_timeout_cycles;
    words[26] = command->preaccept_timeout_cycles;

    /* Commit only once all fields are known-good; failures preserve output. */
    memcpy(output_words, words, sizeof words);
    return ZN_NATIVE_CONV_COMMAND_OK;
}
