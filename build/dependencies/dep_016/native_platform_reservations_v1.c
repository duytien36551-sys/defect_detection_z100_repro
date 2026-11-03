#include "native_platform_reservations_v1.h"
#include <string.h>

#define RESERVATION_MAGIC UINT32_C(0x4e525331)
static ZnNativePlatformReservationsV1 *reservation_owner;
static const ZnNativePlatformReservationV1 expected[5]={
    {UINT64_C(0x10000000),UINT64_C(5201920)},
    {UINT64_C(0x24000000),UINT64_C(613248)},
    {ZN_NPMV1_PARAMETER_ADDRESS,ZN_NPMV1_PARAMETER_BYTES},
    {ZN_NPMV1_DIRECTORY_ADDRESS,ZN_NPMV1_DIRECTORY_BYTES},
    {ZN_NPMV1_VIEW_SCRATCH_CANDIDATE_ADDRESS,ZN_NPMV1_VIEW_SCRATCH_MIN_BYTES}
};
static int valid(const ZnNativePlatformLinkerLayoutV1 *l)
{
    unsigned i,j;
    if (l->app_begin!=UINT64_C(0x00100000) || l->app_limit!=UINT64_C(0x10000000) ||
        l->image_end<=l->app_begin || l->image_end>l->app_limit ||
        l->ddr_limit>ZN_NPMV1_PHYSICAL_ADDRESS_LIMIT) return 0;
    for (i=0;i<5;++i) {
        const ZnNativePlatformReservationV1 *r=&l->ranges[i];
        if (r->address!=expected[i].address || r->bytes!=expected[i].bytes ||
            r->address<l->app_limit || r->address+r->bytes>l->ddr_limit) return 0;
        for (j=i+1;j<5;++j) if (!(r->address+r->bytes<=l->ranges[j].address ||
            l->ranges[j].address+l->ranges[j].bytes<=r->address)) return 0;
    }
    return 1;
}
int zn_native_platform_reservations_init_v1(ZnNativePlatformReservationsV1 *c,const ZnNativePlatformLinkerLayoutV1 *l)
{
    uintptr_t a=(uintptr_t)c,b=(uintptr_t)l;
    if (!c || !l || reservation_owner || c->magic || sizeof *c>UINTPTR_MAX-a || sizeof *l>UINTPTR_MAX-b ||
        !(a+sizeof *c<=b || b+sizeof *l<=a) || !valid(l)) return -1;
    memset(c,0,sizeof *c); c->magic=RESERVATION_MAGIC; c->layout=*l; reservation_owner=c;
    return 0;
}
int zn_native_platform_reservations_reserve_v1(void *context,const ZnNativePlatformReservationV1 *r)
{
    ZnNativePlatformReservationsV1 *c=context;
    unsigned i;
    if (!c || c!=reservation_owner || c->magic!=RESERVATION_MAGIC || !r || !valid(&c->layout) || c->acquired_mask>31u) return -1;
    for (i=0;i<5;++i) if (r->address==expected[i].address && r->bytes==expected[i].bytes) {
        uint32_t bit=UINT32_C(1)<<i;
        if (c->acquired_mask & bit) return 1;
        c->acquired_mask|=bit;
        return 0;
    }
    return -1;
}
