#include "native_platform_reservations_v1.h"

extern char __zn_app_begin[],__zn_app_limit[],__zn_image_end[],__zn_ddr_limit[];
extern char __zn_arena_begin[],__zn_arena_end[],__zn_heads_begin[],__zn_heads_end[];
extern char __zn_parameters_begin[],__zn_parameters_end[],__zn_directory_begin[],__zn_directory_end[];
extern char __zn_scratch_begin[],__zn_scratch_end[];

int zn_native_platform_reservations_from_linker_v1(ZnNativePlatformReservationsV1 *c)
{
    const uintptr_t starts[5]={(uintptr_t)__zn_arena_begin,(uintptr_t)__zn_heads_begin,
        (uintptr_t)__zn_parameters_begin,(uintptr_t)__zn_directory_begin,(uintptr_t)__zn_scratch_begin};
    const uintptr_t ends[5]={(uintptr_t)__zn_arena_end,(uintptr_t)__zn_heads_end,
        (uintptr_t)__zn_parameters_end,(uintptr_t)__zn_directory_end,(uintptr_t)__zn_scratch_end};
    ZnNativePlatformLinkerLayoutV1 layout;
    unsigned i;
    layout.app_begin=(uintptr_t)__zn_app_begin; layout.app_limit=(uintptr_t)__zn_app_limit;
    layout.image_end=(uintptr_t)__zn_image_end; layout.ddr_limit=(uintptr_t)__zn_ddr_limit;
    for (i=0;i<5;++i) {
        if (ends[i]<starts[i]) return -1;
        layout.ranges[i].address=starts[i]; layout.ranges[i].bytes=ends[i]-starts[i];
    }
    return zn_native_platform_reservations_init_v1(c,&layout);
}
