#ifndef Z100_NATIVE_ROW_COMMAND_V2_H
#define Z100_NATIVE_ROW_COMMAND_V2_H
#include "native_row_command.h"
/* V2 also rejects token_base zero, matching actual RTL scheduler admission. */
int zn_native_row_command_v2(const ZnHaloGeometry *,uint16_t output_channel_first,
    uint16_t local_output_row,uint32_t epoch,uint32_t token_base,uint32_t tag_base,
    ZnRowCommand *);
#endif
