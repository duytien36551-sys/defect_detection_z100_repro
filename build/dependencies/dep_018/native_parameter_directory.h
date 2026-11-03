#ifndef Z100_NATIVE_PARAMETER_DIRECTORY_H
#define Z100_NATIVE_PARAMETER_DIRECTORY_H
#include <stdint.h>
/* Host/ARM transport metadata only. Caller verifies model/asset SHA-256,
 * reserves the immutable DDR ranges and completes cache maintenance before
 * publishing a directory to PL. The CRC field is identity, not authentication.
 * This codec never performs MMIO, starts hardware, or acknowledges configuration.
 * Output remains unchanged on failure. End is exclusive and may equal2^32. */
typedef struct {
    uint32_t weights,bias,factors,unary;
    uint16_t groups,job;
    uint8_t lanes;
} ZnParameterDirectoryRecord;
int zn_parameter_directory_encode(uint8_t out[32],
    const ZnParameterDirectoryRecord *,uint32_t model_crc,
    uint32_t payload_begin,uint64_t payload_end);
int zn_parameter_directory_decode(ZnParameterDirectoryRecord *out,
    const uint8_t record[32],uint16_t expected_job,uint32_t model_crc,
    uint32_t payload_begin,uint64_t payload_end);
#endif
