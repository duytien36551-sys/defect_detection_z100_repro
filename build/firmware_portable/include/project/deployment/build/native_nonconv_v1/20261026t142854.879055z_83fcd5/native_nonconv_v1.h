#ifndef Z100_NATIVE_NONCONV_V1_H
#define Z100_NATIVE_NONCONV_V1_H
#include "native_view_materialize_v1.h"
#define Z100_NATIVE_NONCONV_PACKAGE_SHA256 "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c"
/* 0 actual CPU result; 1 Conv backend required; -1 invalid (output unchanged).
 * Reads are exact immutable event-order native buffers. Caller holds leases and
 * CPU cache visibility, owns output, and performs publication/drain separately.
 * ADD/Pool outputs use native word order; HEADS returns613200 logical NCHW bytes
 * (head80,head40,head20 concatenated), without transport padding. No MMIO/ACK. */
int zn_native_nonconv_run_v1(const ZnRequest *,const ZnNativeViewSourceV1 *,
                           uint8_t,uint8_t *,size_t);
const ZnEvent *zn_native_nonconv_event_v1(uint16_t);
#endif
