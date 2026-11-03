#ifndef Z100_NATIVE_PLATFORM_MEMORY_V1_H
#define Z100_NATIVE_PLATFORM_MEMORY_V1_H

#include <stddef.h>
#include <stdint.h>

#define ZN_NPMV1_PACKAGE_SHA256 \
    "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c"
#define ZN_NPMV1_CHECKPOINT_SHA256 \
    "2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6"
#define ZN_NPMV1_GRAPH_SHA256 \
    "9d6064e37e92e61c687608d2c5e216cccb31e0b1fc9603de0c8b21eb3acbae9f"
#define ZN_NPMV1_PARAMETER_SHA256 \
    "fe129a1ee4cffc8a9183e84303c6e119690050cdcdfb40d948040d39a5c73a2b"
#define ZN_NPMV1_DIRECTORY_SHA256 \
    "fb3f36e820d5cb3fa54b9507333eb3bca1cb808f00d4949ad3634c1c090e363b"

#define ZN_NPMV1_PARAMETER_ADDRESS UINT64_C(0x20000000)
#define ZN_NPMV1_PARAMETER_BYTES UINT64_C(3122432)
#define ZN_NPMV1_DIRECTORY_ADDRESS UINT64_C(0x21000000)
#define ZN_NPMV1_DIRECTORY_BYTES UINT64_C(5568)
#define ZN_NPMV1_PHYSICAL_ADDRESS_LIMIT UINT64_C(0x100000000)
#define ZN_NPMV1_DIRECTORY_MODEL_CRC32 UINT32_C(0x83F6CD55)
#define ZN_NPMV1_PARAMETER_IMAGE_CRC32 UINT32_C(0x6EFE98E9)

#define ZN_NPMV1_VIEW_SCRATCH_MIN_BYTES UINT64_C(1228800)
#define ZN_NPMV1_VIEW_SCRATCH_ALIGNMENT UINT64_C(64)
#define ZN_NPMV1_VIEW_SCRATCH_CANDIDATE_ADDRESS UINT64_C(0x22000000)

enum {
    ZN_NPMV1_OK = 0,
    ZN_NPMV1_BUSY = 1,
    ZN_NPMV1_INVALID = -1,
    ZN_NPMV1_IDENTITY_MISMATCH = -2,
    ZN_NPMV1_SOURCE_HASH_MISMATCH = -3,
    ZN_NPMV1_RESERVATION_FAILED = -4,
    ZN_NPMV1_COPY_FAILED = -5,
    ZN_NPMV1_CACHE_FAILED = -6,
    ZN_NPMV1_READBACK_HASH_MISMATCH = -7
};

enum {
    ZN_NPMV1_STAGE_NONE = 0,
    ZN_NPMV1_STAGE_PREFLIGHT,
    ZN_NPMV1_STAGE_SOURCE_HASH,
    ZN_NPMV1_STAGE_RESERVE_PARAMETER,
    ZN_NPMV1_STAGE_RESERVE_DIRECTORY,
    ZN_NPMV1_STAGE_RESERVE_VIEW_SCRATCH,
    ZN_NPMV1_STAGE_COPY_PARAMETER,
    ZN_NPMV1_STAGE_COPY_DIRECTORY,
    ZN_NPMV1_STAGE_CLEAN_PARAMETER,
    ZN_NPMV1_STAGE_CLEAN_DIRECTORY,
    ZN_NPMV1_STAGE_BARRIER_AFTER_CLEAN,
    ZN_NPMV1_STAGE_INVALIDATE_PARAMETER,
    ZN_NPMV1_STAGE_INVALIDATE_DIRECTORY,
    ZN_NPMV1_STAGE_BARRIER_AFTER_INVALIDATE,
    ZN_NPMV1_STAGE_READBACK_HASH,
    ZN_NPMV1_STAGE_READY
};

typedef struct {
    uint64_t address;
    uint64_t bytes;
} ZnNativePlatformReservationV1;

typedef struct {
    uint64_t physical_base;
    uint64_t bytes;
    uint8_t *cpu_base;
    size_t cpu_bytes;
} ZnNativePlatformMappedSpanV1;

typedef struct {
    uint64_t physical_address;
    uint64_t bytes;
    const uint8_t *data;
    const char *sha256;
} ZnNativePlatformImageV1;

typedef struct {
    const char *package_sha256;
    const char *checkpoint_sha256;
    const char *graph_sha256;
    uint32_t directory_model_crc32;
    uint32_t parameter_image_crc32;
    ZnNativePlatformImageV1 parameter_payload;
    ZnNativePlatformImageV1 directory;
    ZnNativePlatformReservationV1 parameter_reservation;
    ZnNativePlatformReservationV1 directory_reservation;
    ZnNativePlatformReservationV1 view_scratch_reservation;
    ZnNativePlatformMappedSpanV1 parameter_mapping;
    ZnNativePlatformMappedSpanV1 directory_mapping;
    ZnNativePlatformMappedSpanV1 view_scratch_mapping;
} ZnNativePlatformMemoryRequestV1;

typedef struct {
    /* reserve: 0 ready, 1 busy, negative failure; other nonzero fails closed. */
    int (*reserve)(void *context, const ZnNativePlatformReservationV1 *range);
    /* copy may fail after a partial write; ownership must then be retained. */
    int (*copy)(void *context, uint8_t *destination, const uint8_t *source, size_t bytes);
    /* Clean to the required point of coherency and invalidate for readback. */
    int (*cache_clean)(void *context, void *address, size_t bytes);
    /* Implement the architecture-appropriate completion barrier. */
    int (*barrier)(void *context);
    int (*invalidate_readback)(void *context, void *address, size_t bytes);
} ZnNativePlatformMemoryOpsV1;

typedef struct {
    uint8_t ready;
    uint8_t stage;
    int32_t callback_status;
} ZnNativePlatformMemoryStateV1;

/*
 * The caller supplies reservation descriptors and CPU mappings. Reserve must
 * cover the complete descriptor; it returns 0 when ready, 1 when busy, and a
 * negative value on failure. All three reservations complete before either
 * image is copied. The scratch descriptor must be disjoint from both images.
 *
 * Callback order on success is reserve x3, copy x2, clean x2, barrier,
 * invalidate/readback x2, barrier, then SHA-256 of the mapped destinations.
 * The function sets state->ready only after both readback hashes match.
 * Callback failures never release ownership. Preparation is not transactional:
 * a later copy/cache/readback failure can leave bytes changed, so the caller
 * must retain reservation ownership until external recovery declares them safe.
 * The caller's state object must not alias request metadata or mapped storage.
 * This routine does not publish readiness to PL or acknowledge configuration.
 */
int zn_native_platform_memory_prepare_v1(
    const ZnNativePlatformMemoryRequestV1 *request,
    const ZnNativePlatformMemoryOpsV1 *ops,
    void *context,
    ZnNativePlatformMemoryStateV1 *state);

#endif
