#ifndef Z100_NATIVE_POOL_COMMAND_V1_H
#define Z100_NATIVE_POOL_COMMAND_V1_H
#include "native_conv_driver_v2.h"
#define ZN_NATIVE_POOL_PHYSICAL_BYTES_V1 UINT32_C(81920)
/* Only frozen epoch200 events70/71/72 (128x20x20, 5x5/s1/p2). No MMIO on invalid input. */
int zn_native_pool_command_valid_v1(const ZnNativeConvCommand *command);
ZnNativeConvDriverCodeV2 zn_native_pool_driver_submit_v1(
    ZnNativeConvDriverV2 *driver, const ZnNativeConvCommand *command);
#endif
