#ifndef Z100_NATIVE_PARAMETER_LOAD_H
#define Z100_NATIVE_PARAMETER_LOAD_H
#include <stdint.h>
enum { ZP_MAC_BEGIN=1,ZP_FACTOR_BEGIN,ZP_UNARY_BEGIN,ZP_WEIGHT,ZP_BIAS,
       ZP_FACTOR,ZP_UNARY,ZP_MAC_COMMIT,ZP_FACTOR_COMMIT,ZP_UNARY_COMMIT };
typedef struct {
    const uint8_t *weights,*bias,*factors,*unary;
    uint32_t weight_bytes,bias_bytes,factor_bytes,unary_bytes,epoch;
    uint16_t groups;
    uint8_t lanes;
} ZnParameterAssets;
typedef struct {
    const uint8_t *data;
    uint32_t epoch,tag,index;
    uint16_t groups,bytes;
    uint8_t operation,lanes;
} ZnParameterRequest;
typedef struct {
    ZnParameterAssets assets;
    ZnParameterRequest request;
    uint32_t next_tag,index;
    uint8_t phase,pending,fault,done;
} ZnParameterLoad;
/* Caller verifies package/asset hashes, keeps payload immutable, and confirms
 * engines idle before init. No hardware reset or asset authentication here.
 * Inactive factor records must be zero; active records are <IBBH,8 bytes.
 * Adapter splits factor multiplier/shift onto actual config ports; precision
 * and active are host admission metadata. Data pointers are not DDR addresses. */
int zn_parameter_init(ZnParameterLoad *,const ZnParameterAssets *);
int zn_parameter_next(ZnParameterLoad *,ZnParameterRequest *);
/* 0: accepted/completed handshake; 1: BUSY (unchanged request); other: fault.
 * Commit ACK must include child error/readiness verification from backend.
 * A fault leaves partial configuration invalid; external cancel/drain required.
 * Never permit a compute RUN until done and all engine identities agree. */
int zn_parameter_ack(ZnParameterLoad *,uint32_t tag,uint8_t operation,int status);
#endif
