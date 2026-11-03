#ifndef V8_TILE_ABI_H
#define V8_TILE_ABI_H

#include <stddef.h>
#include <stdint.h>

#include "v8_runtime.h"

#define V8_TILE_MAGIC 0x564C0001u
#define V8_TILE_LANES 64u
#define V8_TILE_MAX_SITES 64u
#define V8_TILE_MAX_TAPS 4091u
#define V8_TILE_DMA_MAX_BYTES 262140u
#define V8_TILE_TX_CAPACITY_BYTES 262144u
#define V8_TILE_RX_CAPACITY_BYTES 16448u
#define V8_TILE_MAX_RESPONSE_BYTES \
    (5u * sizeof(uint32_t) + V8_TILE_MAX_SITES * V8_TILE_LANES * sizeof(int32_t))
#define V8_TILE_MAX_LOAD_BYTES \
    (V8_TILE_LANES * 4u + V8_TILE_LANES * V8_TILE_MAX_TAPS)

#define V8_TILE_R0_START 0x00000001u
#define V8_TILE_R0_ABORT 0x00000002u

typedef enum {
    V8_TILE_OP_PROBE = 0u,
    V8_TILE_OP_LOAD = 1u,
    V8_TILE_OP_RUN = 2u
} V8TileOpcode;

typedef enum {
    V8_TILE_OK = 0,
    V8_TILE_EINVAL = -1,
    V8_TILE_EOVERFLOW = -2,
    V8_TILE_ECAPACITY = -3,
    V8_TILE_EFRAME = -4,
    V8_TILE_EDEVICE = -5
} V8TileStatus;

/*
 * Request-side description for one output-channel tile and one spatial run.
 * LOAD uses output_channel_base/filter_id; RUN additionally uses site_base.
 * All size fields are derived by v8_tile_config_init and checked again before
 * packing or parsing.
 */
typedef struct {
    uint32_t taps;
    uint32_t lanes;
    uint32_t sites;
    uint32_t padded_taps;
    uint32_t output_channel_base;
    uint32_t site_base;
    uint32_t filter_id;
    uint32_t load_reg1;
    uint32_t reg1;
    size_t load_bytes;
    size_t run_bytes;
    size_t response_bytes;
} V8TileConfig;

/* R0 stores opcode above the low held-ABORT and START control bits. */
int v8_tile_control_word(V8TileOpcode opcode, int abort_held, int start,
                         uint32_t *word_out);

/* Build the checked R1/configuration and byte lengths for one tile request. */
int v8_tile_config_init(const V8Node *output, const V8Node *input,
                        uint32_t output_channel_base, uint32_t site_base,
                        uint32_t site_count, uint32_t filter_id,
                        V8TileConfig *config_out);

/* LOAD payload: 64 little-endian INT32 biases, then T groups of 64 INT8 weights. */
int v8_tile_pack_load(uint8_t *dst, size_t dst_capacity,
                      const V8Node *output, const V8Node *input,
                      const int8_t *weights, size_t weights_count,
                      const uint8_t *bias_le, size_t bias_bytes,
                      const V8TileConfig *config);

/* RUN payload: site-major T INT8 activations, padded to four taps with zeros. */
int v8_tile_pack_run(uint8_t *dst, size_t dst_capacity,
                     const V8Node *output, const V8Node *input,
                     const int8_t *input_nchw, size_t input_count,
                     const V8TileConfig *config);

/*
 * Validate the complete response before writing any raw output. The wire frame
 * is four LE32 header words, S*L LE32 payload words (RUN only), and one LE32
 * status trailer. Payload is transposed from site-major/lane-minor to channel-
 * major NCHW raw storage.
 */
int v8_tile_parse_run_response(const uint8_t *response, size_t response_bytes,
                               uint32_t sequence, const V8Node *output,
                               const V8TileConfig *config,
                               int32_t *raw, size_t raw_count);

#endif
