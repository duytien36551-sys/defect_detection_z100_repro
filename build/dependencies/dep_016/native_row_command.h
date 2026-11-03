#ifndef Z100_NATIVE_ROW_COMMAND_H
#define Z100_NATIVE_ROW_COMMAND_H
#include <stdint.h>
/* Geometry for a fully loaded halo tile; output rows remain in global space.
 * Parameter group is resident for all rows; packer order is group32,row,x20. */
typedef struct {
    uint16_t input_channels,input_height,input_width;
    uint16_t input_y,input_rows,output_y,output_rows,output_height,output_width;
    uint16_t output_channels;
    uint8_t kernel,stride,padding;
} ZnHaloGeometry;
typedef struct {
    uint32_t epoch,token_base,tag_base;
    uint16_t channels,input_width,output_width,bank_words,channel_plane_stride;
    uint64_t ky_row_bases;
    uint8_t kernel,stride,padding,lanes,y_valid;
} ZnRowCommand;
/* Configure one resident output32 group, then emit row0..output_rows-1.
 * token_base/tag_base refer to the whole tile. No MMIO or work is performed.
 * Rejects out-of-range halo, channel group, capacity and metadata wrap. */
int zn_native_row_command(const ZnHaloGeometry *,uint16_t output_channel_first,
    uint16_t local_output_row,uint32_t epoch,uint32_t token_base,uint32_t tag_base,
    ZnRowCommand *);
#endif
