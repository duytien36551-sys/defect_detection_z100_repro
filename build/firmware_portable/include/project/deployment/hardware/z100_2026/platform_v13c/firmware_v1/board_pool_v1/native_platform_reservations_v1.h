#ifndef Z100_NATIVE_PLATFORM_RESERVATIONS_V1_H
#define Z100_NATIVE_PLATFORM_RESERVATIONS_V1_H
#include "native_platform_memory_v1.h"

typedef struct ZnNativePlatformLinkerLayoutV1 {
    uint64_t app_begin,app_limit,image_end,ddr_limit;
    /* Session bit order: arena, HEADS, parameters, directory, scratch. */
    ZnNativePlatformReservationV1 ranges[5];
} ZnNativePlatformLinkerLayoutV1;
typedef struct ZnNativePlatformReservationsV1 {
    uint32_t magic, acquired_mask;
    ZnNativePlatformLinkerLayoutV1 layout;
} ZnNativePlatformReservationsV1;

/* Bare-metal exclusive ownership only. Requires linker exclusion, identity
 * CPU mappings, qualified DDR/MMU/cache, and no competing core/OS/debug writer.
 * Checks exact frozen five ranges and low application boundary; no probing,
 * heap allocation, copy, MMIO or physical-ownership inference. Zero once;
 * rejection has no writes. No release/reset/automatic rollback operation. */
int zn_native_platform_reservations_init_v1(ZnNativePlatformReservationsV1 *,const ZnNativePlatformLinkerLayoutV1 *);
/* Cache reserve callback: 0 newly held, 1 already held, -1 invalid. */
int zn_native_platform_reservations_reserve_v1(void *,const ZnNativePlatformReservationV1 *);
/* Reads candidate linker symbols only; no hardware IO. */
int zn_native_platform_reservations_from_linker_v1(ZnNativePlatformReservationsV1 *);
#endif
