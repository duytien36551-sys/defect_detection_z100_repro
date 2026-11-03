#include "native_pool_command_v1.h"
static uint64_t end_value(ZnNativeConvEnd33 end) {
    return ((uint64_t)end.high << 32) | end.low;
}
int zn_native_pool_command_valid_v1(const ZnNativeConvCommand *c) {
    uint64_t se, de, source_end, destination_end, parameter_end, directory_end;
    if (!c || zn_native_conv_command_validate_v1(c) != ZN_NATIVE_CONV_COMMAND_OK)
        return 0;
    if (c->event != 70 && c->event != 71 && c->event != 72)
        return 0;
    se = (uint64_t)c->source_base + ZN_NATIVE_POOL_PHYSICAL_BYTES_V1;
    de = (uint64_t)c->destination_base + ZN_NATIVE_POOL_PHYSICAL_BYTES_V1;
    source_end = end_value(c->source_lease_region_end);
    destination_end = end_value(c->destination_reservation_region_end);
    parameter_end = end_value(c->parameter_payload_end);
    directory_end = (uint64_t)c->parameter_directory_base +
                    (((uint64_t)c->parameter_count + 1) / 2) * 64;
    if (source_end > UINT64_C(0x40000000) || destination_end > UINT64_C(0x40000000) ||
        se > source_end || de > destination_end ||
        ((uint64_t)c->source_base < de && (uint64_t)c->destination_base < se) ||
        ((uint64_t)c->destination_base < parameter_end && (uint64_t)c->parameter_payload_begin < de) ||
        ((uint64_t)c->destination_base < directory_end && (uint64_t)c->parameter_directory_base < de))
        return 0;
    return 1;
}
ZnNativeConvDriverCodeV2 zn_native_pool_driver_submit_v1(
    ZnNativeConvDriverV2 *driver, const ZnNativeConvCommand *command) {
    if (!driver || !command) return ZN_NATIVE_CONV_DRIVER_V2_ARGUMENT;
    if (!zn_native_pool_command_valid_v1(command)) return ZN_NATIVE_CONV_DRIVER_V2_INVALID;
    /* parameter_timeout_cycles is the Pool compute watchdog. There is no parameter load. */
    return zn_native_conv_driver_submit_v2(driver, command, 1);
}
