#ifndef ACP_POOL_ORACLE_V1_H
#define ACP_POOL_ORACLE_V1_H

#include <stdint.h>

enum {
    ZN_ACP_SMOKE_CHANNELS = 128u,
    ZN_ACP_SMOKE_HEIGHT = 20u,
    ZN_ACP_SMOKE_WIDTH = 20u,
    ZN_ACP_SMOKE_X_WORDS = 2u,
    ZN_ACP_SMOKE_CHANNELS_PER_GROUP = 32u,
    ZN_ACP_SMOKE_GROUP_SUBGROUPS = 8u,
    ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW = 16u,
    ZN_ACP_SMOKE_POOL_KERNEL = 5u,
    ZN_ACP_SMOKE_POOL_PADDING = 2u,
    ZN_ACP_SMOKE_PROBE_OUTPUT_ROWS = 10u,
    ZN_ACP_SMOKE_BUS_WORD_BYTES = 64u,
    ZN_ACP_SMOKE_PHYSICAL_BYTES = 81920u
};

#define ZN_ACP_SMOKE_GUARD_BACKING_BEFORE UINT8_C(0x69)
#define ZN_ACP_SMOKE_GUARD_BACKING_AFTER  UINT8_C(0x96)
#define ZN_ACP_SMOKE_DIRTY_GUARD_BEFORE   UINT8_C(0xA6)
#define ZN_ACP_SMOKE_DIRTY_GUARD_AFTER    UINT8_C(0x5A)

_Static_assert(((ZN_ACP_SMOKE_CHANNELS + 3u) / 4u) * ZN_ACP_SMOKE_HEIGHT *
               ZN_ACP_SMOKE_X_WORDS * ZN_ACP_SMOKE_BUS_WORD_BYTES ==
                   ZN_ACP_SMOKE_PHYSICAL_BYTES,
               "Pool physical extent must match the padded 64-byte output layout");
_Static_assert(ZN_ACP_SMOKE_X_WORDS == (ZN_ACP_SMOKE_WIDTH + 15u) / 16u,
               "Pool output word count must match width padding");

static const uint32_t zn_acp_smoke_probe_words[] = {
    0u, 16u, 32u, 48u, 64u, 80u, 96u, 112u
};

static uint8_t zn_acp_smoke_expected_source_byte(uint32_t offset,
                                                 uint8_t input_value)
{
    uint32_t i;
    uint32_t word = offset / ZN_ACP_SMOKE_BUS_WORD_BYTES;
    uint32_t byte_in_word = offset % ZN_ACP_SMOKE_BUS_WORD_BYTES;
    uint32_t in_group = word % (ZN_ACP_SMOKE_HEIGHT *
                                ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW);
    uint32_t x_word = (in_group % ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW) /
                      ZN_ACP_SMOKE_GROUP_SUBGROUPS;
    uint32_t x = x_word * 16u + byte_in_word % 16u;

    if (x >= ZN_ACP_SMOKE_WIDTH)
        return 0u;

    for (i = 0; i < sizeof zn_acp_smoke_probe_words /
                    sizeof zn_acp_smoke_probe_words[0]; ++i) {
        if (word == zn_acp_smoke_probe_words[i] && byte_in_word == 0u)
            return UINT8_C(0x7F);
    }
    return input_value;
}

static int zn_acp_smoke_is_probe_pixel(uint32_t channel,
                                       uint32_t row,
                                       uint32_t x)
{
    uint32_t i;
    const uint32_t group_words = ZN_ACP_SMOKE_HEIGHT *
                                 ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW;

    for (i = 0; i < sizeof zn_acp_smoke_probe_words /
                    sizeof zn_acp_smoke_probe_words[0]; ++i) {
        uint32_t word = zn_acp_smoke_probe_words[i];
        uint32_t group = word / group_words;
        uint32_t in_group = word % group_words;
        uint32_t probe_row = in_group / ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW;
        uint32_t in_row = in_group % ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW;
        uint32_t x_word = in_row / ZN_ACP_SMOKE_GROUP_SUBGROUPS;
        uint32_t subgroup = in_row % ZN_ACP_SMOKE_GROUP_SUBGROUPS;
        uint32_t probe_channel = group * ZN_ACP_SMOKE_CHANNELS_PER_GROUP +
                                 subgroup * 4u;
        uint32_t probe_x = x_word * 16u;

        if (channel == probe_channel && row == probe_row && x == probe_x)
            return 1;
    }
    return 0;
}

static uint8_t zn_acp_smoke_expected_byte(uint32_t offset, int8_t input_value)
{
    uint32_t word = offset / ZN_ACP_SMOKE_BUS_WORD_BYTES;
    uint32_t byte_in_word = offset % ZN_ACP_SMOKE_BUS_WORD_BYTES;
    const uint32_t group_words = ZN_ACP_SMOKE_HEIGHT *
                                 ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW;
    uint32_t group = word / group_words;
    uint32_t in_group = word % group_words;
    uint32_t row = in_group / ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW;
    uint32_t in_row = in_group % ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW;
    uint32_t x_word = in_row / ZN_ACP_SMOKE_GROUP_SUBGROUPS;
    uint32_t subgroup = in_row % ZN_ACP_SMOKE_GROUP_SUBGROUPS;
    uint32_t channel = group * ZN_ACP_SMOKE_CHANNELS_PER_GROUP + subgroup * 4u +
                       byte_in_word / 16u;
    uint32_t x = x_word * 16u + byte_in_word % 16u;
    int8_t maximum = input_value;
    uint32_t dy;

    if (x >= ZN_ACP_SMOKE_WIDTH)
        return 0u;

    for (dy = 0; dy < ZN_ACP_SMOKE_POOL_KERNEL; ++dy) {
        int32_t input_y = (int32_t)row + (int32_t)dy -
                          (int32_t)ZN_ACP_SMOKE_POOL_PADDING;
        uint32_t dx;

        if (input_y < 0 || input_y >= (int32_t)ZN_ACP_SMOKE_HEIGHT)
            continue;
        for (dx = 0; dx < ZN_ACP_SMOKE_POOL_KERNEL; ++dx) {
            int32_t input_x = (int32_t)x + (int32_t)dx -
                              (int32_t)ZN_ACP_SMOKE_POOL_PADDING;
            int8_t sample;

            if (input_x < 0 || input_x >= (int32_t)ZN_ACP_SMOKE_WIDTH)
                continue;
            sample = zn_acp_smoke_is_probe_pixel(channel, (uint32_t)input_y,
                                                (uint32_t)input_x) ?
                     INT8_C(127) : input_value;
            if (sample > maximum)
                maximum = sample;
        }
    }
    return (uint8_t)maximum;
}

static int zn_acp_smoke_verify_guard(volatile const uint8_t *guard,
                                      uint8_t expected)
{
    uint32_t offset;
    for (offset = 0; offset < ZN_ACP_SMOKE_BUS_WORD_BYTES; ++offset) {
        if (guard[offset] != expected)
            return -1;
    }
    return 0;
}

#endif
