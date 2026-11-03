#ifndef Z100_NATIVE_ARENA_OWNER_V1_H
#define Z100_NATIVE_ARENA_OWNER_V1_H

#include "native_dispatch.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZN_NATIVE_ARENA_SLOT_COUNT_V1 7u
#define ZN_NATIVE_ARENA_EVENT_COUNT_V1 73u

#define ZN_NATIVE_ARENA_PACKAGE_SHA256_V1 \
    "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c"
#define ZN_NATIVE_ARENA_GRAPH_SHA256_V1 \
    "9d6064e37e92e61c687608d2c5e216cccb31e0b1fc9603de0c8b21eb3acbae9f"
#define ZN_NATIVE_ARENA_PLAN_SHA256_V1 \
    "4f4c15666562330cacf0ea1ad4d05cd62d79a7017972ec73a502be36a60e6f92"
#define ZN_NATIVE_ARENA_MANIFEST_SHA256_V1 \
    "601bc0ac09ebf430ab1e510aec6018f099e1b0a7a93853c69c5ea991344bbad5"

typedef struct ZnNativeArenaRegionV1 {
    uint32_t address;
    uint32_t capacity_bytes;
} ZnNativeArenaRegionV1;

typedef struct ZnNativeArenaConfigV1 {
    uint32_t arena_base;
    uint32_t arena_end;
    uint32_t arena_bytes;
    uint32_t alignment;
    ZnNativeArenaRegionV1 slots[ZN_NATIVE_ARENA_SLOT_COUNT_V1];
    char package_sha256[65];
    char graph_sha256[65];
    char plan_sha256[65];
    char manifest_sha256[65];
} ZnNativeArenaConfigV1;

typedef enum ZnNativeArenaSlotStateV1 {
    ZN_NATIVE_ARENA_SLOT_EMPTY_V1 = 0,
    ZN_NATIVE_ARENA_SLOT_RESERVED_V1 = 1,
    ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 = 2
} ZnNativeArenaSlotStateV1;

typedef struct ZnNativeArenaSlotV1 {
    ZnNativeArenaRegionV1 region;
    ZnRef ref;
    uint32_t bytes;
    uint32_t generation_high_water;
    uint16_t reader_count;
    uint16_t io_count;
    uint8_t state;
} ZnNativeArenaSlotV1;

typedef struct ZnNativeArenaEventStateV1 {
    uint32_t run_tag;
    uint8_t allocated;
    uint8_t run_started;
    uint8_t run_completed;
    uint8_t output_published;
    uint8_t io_quiescent;
    uint8_t drained;
    uint8_t run_acked;
    uint8_t acquired_mask;
    uint8_t returned_mask;
    uint8_t retired_mask;
} ZnNativeArenaEventStateV1;

typedef struct ZnNativeArenaOwnerV1 {
    const ZnEvent *events;
    uint32_t epoch;
    uint16_t event_count;
    uint8_t fault;
    uint8_t initialized;
    uint8_t complete;
    ZnNativeArenaSlotV1 slots[ZN_NATIVE_ARENA_SLOT_COUNT_V1];
    ZnNativeArenaEventStateV1 event_state[ZN_NATIVE_ARENA_EVENT_COUNT_V1];
} ZnNativeArenaOwnerV1;

typedef struct ZnNativeArenaCompletionEvidenceV1 {
    uint32_t epoch;
    uint32_t run_tag;
    uint16_t event_index;
    ZnRef destination_ref;
    uint32_t destination_bytes;
    uint8_t result_identity_verified;
    uint8_t driver_terminal_success;
    uint8_t output_cache_visible;
} ZnNativeArenaCompletionEvidenceV1;

typedef struct ZnNativeArenaQuiescenceEvidenceV1 {
    uint32_t epoch;
    uint32_t run_tag;
    uint16_t event_index;
    uint8_t all_read_io_quiet;
    uint8_t all_write_io_quiet;
    uint8_t driver_terminal;
} ZnNativeArenaQuiescenceEvidenceV1;

typedef enum ZnNativeArenaOwnerCodeV1 {
    ZN_NATIVE_ARENA_OWNER_V1_ACKED = 0,
    ZN_NATIVE_ARENA_OWNER_V1_BUSY = 1,
    ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND = 2,
    ZN_NATIVE_ARENA_OWNER_V1_NEEDS_QUIESCENCE = 3,
    ZN_NATIVE_ARENA_OWNER_V1_ARGUMENT = -1,
    ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST = -2,
    ZN_NATIVE_ARENA_OWNER_V1_INVALID = -3,
    ZN_NATIVE_ARENA_OWNER_V1_ORDER = -4,
    ZN_NATIVE_ARENA_OWNER_V1_OVERFLOW = -5,
    ZN_NATIVE_ARENA_OWNER_V1_FAILED = -6,
    ZN_NATIVE_ARENA_OWNER_V1_POISONED = -7
} ZnNativeArenaOwnerCodeV1;

/* The caller zero-initializes owner, initializes dispatch first, and provides
 * the independently verified frozen address/hash configuration. This binds
 * the exact compiled 73-event plan; it does not reserve physical DDR. */
ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_init_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnNativeArenaConfigV1 *config,
    const ZnDispatch *dispatch, uint32_t epoch);

/* ALLOCATE/ACQUIRE/RETURN/RETIRE are acknowledged only after their ledger
 * transition validates. RUN returns NEEDS_BACKEND until separately started
 * and completed/published. DRAIN returns BUSY until physical quiescence. */
ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_step_v1(
    ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
    const ZnRequest *request);

/* Call only after the backend actually submits compute with all graph leases
 * held. Submission does not publish the destination. */
ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_run_started_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request);

/* Successful compute, verified driver result, and visible output are required
 * before this explicit publication notification. */
ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_publish_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request,
    const ZnNativeArenaCompletionEvidenceV1 *evidence);

/* Completes destinationless graph work, such as final head assembly. */
ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_complete_without_output_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request,
    const ZnNativeArenaCompletionEvidenceV1 *evidence);

/* Separately attest successful physical IO quiescence. A failed result uses
 * fail_v1 instead and keeps every outstanding reference and IO count. */
ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_notify_quiescent_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch,
    const ZnRequest *request,
    const ZnNativeArenaQuiescenceEvidenceV1 *evidence);

/* Latches failure without retiring, freeing, or publishing anything. */
ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_fail_v1(
    ZnNativeArenaOwnerV1 *owner, ZnDispatch *dispatch,
    const ZnRequest *request);

/* Succeeds only at dispatcher completion with every slot retired and quiet. */
ZnNativeArenaOwnerCodeV1
zn_native_arena_owner_verify_complete_v1(
    ZnNativeArenaOwnerV1 *owner, const ZnDispatch *dispatch);

#ifdef __cplusplus
}
#endif

#endif /* Z100_NATIVE_ARENA_OWNER_V1_H */
