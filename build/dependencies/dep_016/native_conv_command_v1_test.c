#include "native_conv_command_v1.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct BadFieldCase {
    unsigned int case_id;
    unsigned int word_index;
    uint32_t value;
};

static const struct BadFieldCase bad_fields[] = {
    {1, 1, 0}, {2, 4, 0}, {3, 5, 0}, {4, 6, 0},
    {5, 2, UINT32_C(0x00000100)}, {6, 3, UINT32_C(0x83f6cd54)},
    {7, 7, UINT32_C(0x0000000f)}, {8, 7, UINT32_C(0x00000005)},
    {9, 7, UINT32_C(0x00000003)}, {10, 9, 0}, {11, 14, 0},
    {12, 8, UINT32_C(0x00100001)}, {13, 10, UINT32_C(0x00100001)},
    {14, 11, UINT32_C(0x00110001)}, {15, 11, UINT32_C(0x00100000)},
    {16, 8, UINT32_C(0x00110000)}, {17, 13, UINT32_C(0x00200001)},
    {18, 15, UINT32_C(0x00200001)}, {19, 16, UINT32_C(0x00220001)},
    {20, 16, UINT32_C(0x00200000)}, {21, 13, UINT32_C(0x00220000)},
    {22, 12, UINT32_C(0x00000002)}, {23, 12, UINT32_C(0x00000001)},
    {24, 17, UINT32_C(0x00000002)}, {25, 17, UINT32_C(0x00000001)},
    {26, 18, UINT32_C(0x00300001)}, {27, 19, 0},
    {28, 19, UINT32_C(174)}, {29, 19, UINT32_C(0x000100ad)},
    {30, 18, UINT32_C(0xffffea80)}, {31, 20, UINT32_C(0x00310001)},
    {32, 21, UINT32_C(0x00310000)}, {33, 22, UINT32_C(0x00000002)},
    {34, 22, UINT32_C(0x00000001)}, {35, 23, 0}, {36, 24, 0},
    {37, 25, 0}, {38, 26, 0},
};

static int
set_command_word(ZnNativeConvCommand *command, unsigned int index, uint32_t value)
{
    switch (index) {
    case 0: command->request_cookie = value; break;
    case 1: command->epoch = value; break;
    case 2: command->event = value; break;
    case 3: command->model_crc32 = value; break;
    case 4: command->job_base = value; break;
    case 5: command->token_base = value; break;
    case 6: command->tag_base = value; break;
    case 7: command->flags = value; break;
    case 8: command->source_base = value; break;
    case 9: command->source_generation = value; break;
    case 10: command->source_lease_region_begin = value; break;
    case 11: command->source_lease_region_end.low = value; break;
    case 12: command->source_lease_region_end.high = value; break;
    case 13: command->destination_base = value; break;
    case 14: command->destination_generation = value; break;
    case 15: command->destination_reservation_region_begin = value; break;
    case 16: command->destination_reservation_region_end.low = value; break;
    case 17: command->destination_reservation_region_end.high = value; break;
    case 18: command->parameter_directory_base = value; break;
    case 19: command->parameter_count = value; break;
    case 20: command->parameter_payload_begin = value; break;
    case 21: command->parameter_payload_end.low = value; break;
    case 22: command->parameter_payload_end.high = value; break;
    case 23: command->load_timeout_cycles = value; break;
    case 24: command->parameter_timeout_cycles = value; break;
    case 25: command->write_timeout_cycles = value; break;
    case 26: command->preaccept_timeout_cycles = value; break;
    default: return 0;
    }
    return 1;
}

static int
command_from_words(const uint32_t words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT],
                   ZnNativeConvCommand *command)
{
    unsigned int index;
    memset(command, 0, sizeof *command);
    for (index = 0; index < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++index) {
        if (!set_command_word(command, index, words[index]))
            return 0;
    }
    return 1;
}

static void
make_valid_command(ZnNativeConvCommand *command)
{
    memset(command, 0, sizeof *command);
    command->epoch = 200;
    command->event = 1;
    command->model_crc32 = ZN_NATIVE_CONV_MMIO_MODEL_CRC32;
    command->job_base = UINT32_C(0x00001000);
    command->token_base = UINT32_C(0x00002000);
    command->tag_base = UINT32_C(0x00003000);
    command->flags = ZN_NC_SHADOW_FLAGS_VALID_MASK;
    command->source_base = UINT32_C(0x00100000);
    command->source_generation = 3;
    command->source_lease_region_begin = UINT32_C(0x00100000);
    command->source_lease_region_end.low = UINT32_C(0x00110000);
    command->destination_base = UINT32_C(0x00200000);
    command->destination_generation = 4;
    command->destination_reservation_region_begin = UINT32_C(0x00200000);
    command->destination_reservation_region_end.low = UINT32_C(0x00220000);
    command->parameter_directory_base = UINT32_C(0x00300000);
    command->parameter_count = ZN_NATIVE_CONV_MMIO_PARAMETER_COUNT;
    command->parameter_payload_begin = UINT32_C(0x00310000);
    command->parameter_payload_end.low = UINT32_C(0x00320000);
    command->load_timeout_cycles = 100;
    command->parameter_timeout_cycles = 200;
    command->write_timeout_cycles = 300;
    command->preaccept_timeout_cycles = 100;
}

static int
parse_words_line(char *line, uint32_t words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT])
{
    char *cursor = line;
    unsigned int index;

    for (index = 0; index < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++index) {
        char *end = NULL;
        unsigned long long value;
        while (*cursor == ' ' || *cursor == '\t')
            ++cursor;
        if (*cursor == '\0' || *cursor == '\r' || *cursor == '\n')
            return 0;
        value = strtoull(cursor, &end, 16);
        if (end == cursor || value > UINT32_MAX)
            return 0;
        words[index] = (uint32_t)value;
        cursor = end;
    }
    while (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n')
        ++cursor;
    return *cursor == '\0';
}

static int
run_batch(void)
{
    char line[1024];
    while (fgets(line, sizeof line, stdin)) {
        uint32_t input_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
        uint32_t output_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
        ZnNativeConvCommand command;
        ZnNativeConvCommandStatus status;
        unsigned int index;
        if (!parse_words_line(line, input_words) || !command_from_words(input_words, &command)) {
            puts("PARSE_ERROR");
            return 2;
        }
        status = zn_native_conv_command_encode_v1(&command, output_words);
        if (status != ZN_NATIVE_CONV_COMMAND_OK) {
            printf("INVALID %u\n", (unsigned int)status);
            continue;
        }
        fputs("VALID", stdout);
        for (index = 0; index < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++index)
            printf(" %08" PRIx32, output_words[index]);
        putchar('\n');
    }
    return ferror(stdin) ? 3 : 0;
}

static int
run_self_tests(void)
{
    static const uint32_t expected_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT] = {
        0, 200, 1, UINT32_C(0x83f6cd55), UINT32_C(0x00001000),
        UINT32_C(0x00002000), UINT32_C(0x00003000), UINT32_C(0x00000007),
        UINT32_C(0x00100000), 3, UINT32_C(0x00100000), UINT32_C(0x00110000), 0,
        UINT32_C(0x00200000), 4, UINT32_C(0x00200000), UINT32_C(0x00220000), 0,
        UINT32_C(0x00300000), 173, UINT32_C(0x00310000), UINT32_C(0x00320000), 0,
        100, 200, 300, 100
    };
    ZnNativeConvCommand command;
    uint32_t output_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t sentinel_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    size_t index;

    if (sizeof expected_words / sizeof expected_words[0] != 27u ||
        sizeof(ZnNativeConvCommand) != 27u * sizeof(uint32_t) ||
        offsetof(ZnNativeConvCommand, source_lease_region_end) != 11u * sizeof(uint32_t) ||
        offsetof(ZnNativeConvCommand, destination_base) != 13u * sizeof(uint32_t) ||
        offsetof(ZnNativeConvCommand, parameter_directory_base) != 18u * sizeof(uint32_t) ||
        offsetof(ZnNativeConvCommand, preaccept_timeout_cycles) != 26u * sizeof(uint32_t)) {
        fputs("FAIL layout differs from frozen 27-word ABI\n", stderr);
        return 1;
    }

    make_valid_command(&command);
    if (zn_native_conv_command_validate_v1(&command) != ZN_NATIVE_CONV_COMMAND_OK ||
        zn_native_conv_command_encode_v1(&command, output_words) != ZN_NATIVE_CONV_COMMAND_OK ||
        memcmp(output_words, expected_words, sizeof expected_words) != 0) {
        fputs("FAIL valid command encoding differs from independent word vector\n", stderr);
        return 1;
    }

    /* The ABI and RTL do not constrain the cookie or first-bank selection. */
    command.flags = ZN_NC_SHADOW_SOURCE_LEASE_VALID |
                    ZN_NC_SHADOW_DEST_RESERVATION_VALID;
    if (zn_native_conv_command_encode_v1(&command, output_words) != ZN_NATIVE_CONV_COMMAND_OK ||
        output_words[0] != 0 || output_words[7] != 6) {
        fputs("FAIL cookie-zero / first-bank-zero command gained an extra restriction\n", stderr);
        return 1;
    }

    memcpy(sentinel_words, expected_words, sizeof sentinel_words);
    for (index = 0; index < sizeof bad_fields / sizeof bad_fields[0]; ++index) {
        make_valid_command(&command);
        if (!set_command_word(&command, bad_fields[index].word_index, bad_fields[index].value)) {
            fputs("FAIL invalid test matrix word index\n", stderr);
            return 1;
        }
        memset(output_words, 0xa5, sizeof output_words);
        memcpy(sentinel_words, output_words, sizeof sentinel_words);
        if (zn_native_conv_command_validate_v1(&command) != ZN_NATIVE_CONV_COMMAND_INVALID ||
            zn_native_conv_command_encode_v1(&command, output_words) != ZN_NATIVE_CONV_COMMAND_INVALID ||
            memcmp(output_words, sentinel_words, sizeof output_words) != 0) {
            fprintf(stderr, "FAIL invalid field case %u (word %u)\n",
                    bad_fields[index].case_id, bad_fields[index].word_index);
            return 1;
        }
    }

    make_valid_command(&command);
    command.source_base = UINT32_C(0xfffff000);
    command.source_lease_region_begin = UINT32_C(0xfffff000);
    command.source_lease_region_end.low = 0;
    command.source_lease_region_end.high = 1;
    command.destination_base = UINT32_C(0xffffe000);
    command.destination_reservation_region_begin = UINT32_C(0xffffe000);
    command.destination_reservation_region_end.low = 0;
    command.destination_reservation_region_end.high = 1;
    command.parameter_directory_base = UINT32_C(0xffffea40);
    command.parameter_payload_begin = UINT32_C(0xfffff000);
    command.parameter_payload_end.low = 0;
    command.parameter_payload_end.high = 1;
    if (zn_native_conv_command_encode_v1(&command, output_words) != ZN_NATIVE_CONV_COMMAND_OK ||
        output_words[11] != 0 || output_words[12] != 1 ||
        output_words[16] != 0 || output_words[17] != 1 ||
        output_words[18] != UINT32_C(0xffffea40) ||
        output_words[21] != 0 || output_words[22] != 1) {
        fputs("FAIL exact 4 GiB exclusive-end / rounded-directory boundary\n", stderr);
        return 1;
    }

    command.source_lease_region_end.low = UINT32_C(0x40);
    if (zn_native_conv_command_validate_v1(&command) != ZN_NATIVE_CONV_COMMAND_INVALID) {
        fputs("FAIL source end above 4 GiB was accepted\n", stderr);
        return 1;
    }
    command.source_lease_region_end.low = 0;
    command.parameter_payload_end.low = UINT32_C(0x40);
    if (zn_native_conv_command_validate_v1(&command) != ZN_NATIVE_CONV_COMMAND_INVALID) {
        fputs("FAIL payload end above 4 GiB was accepted\n", stderr);
        return 1;
    }

    make_valid_command(&command);
    if (zn_native_conv_command_validate_v1(NULL) != ZN_NATIVE_CONV_COMMAND_NULL_ARGUMENT ||
        zn_native_conv_command_encode_v1(NULL, output_words) != ZN_NATIVE_CONV_COMMAND_NULL_ARGUMENT ||
        zn_native_conv_command_encode_v1(&command, NULL) != ZN_NATIVE_CONV_COMMAND_NULL_ARGUMENT) {
        fputs("FAIL null-argument contract\n", stderr);
        return 1;
    }

    command.parameter_payload_end.low += 1;
    if (zn_native_conv_command_validate_v1(&command) != ZN_NATIVE_CONV_COMMAND_OK ||
        zn_native_conv_command_encode_v1(&command, output_words) != ZN_NATIVE_CONV_COMMAND_OK ||
        output_words[21] != UINT32_C(0x00320001)) {
        fputs("FAIL frontend-compatible unaligned exclusive payload end\n", stderr);
        return 1;
    }

    printf("COMMAND_C_SELFTEST_PASS bad_fields=%zu exact_4g_end=1 above_4g_rejects=2 null_args=3 payload_end_unaligned=1 layout_words=27\n",
           sizeof bad_fields / sizeof bad_fields[0]);
    return 0;
}

int
main(int argc, char **argv)
{
    if (argc == 1)
        return run_self_tests();
    if (argc == 2 && strcmp(argv[1], "--batch-words") == 0)
        return run_batch();
    fputs("usage: native_conv_command_v1_test [--batch-words]\n", stderr);
    return 64;
}
