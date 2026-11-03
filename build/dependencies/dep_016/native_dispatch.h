#ifndef Z100_NATIVE_DISPATCH_H
#define Z100_NATIVE_DISPATCH_H
#include <stdint.h>

/* Portable transactional graph control. No MMIO, AXI driver or pixel compute.
 * Backends must acknowledge actual hardware completion, never submission.
 * RUN success means destination fully published (all successful B responses);
 * DRAIN success means all graph-job reads/writes and output readers drained.
 * Faults retain outstanding leases/allocations for external recovery. */
enum { ZN_ALLOCATE=1, ZN_ACQUIRE, ZN_RUN, ZN_DRAIN, ZN_RETURN, ZN_RETIRE };
enum { ZN_ACK_OK=0, ZN_ACK_BUSY=1, ZN_ACK_FAILED=2 };
enum { ZN_CONV=1, ZN_ADD, ZN_POOL, ZN_HEADS };
typedef struct { uint32_t generation; int32_t tensor; uint8_t slot; } ZnRef;
typedef struct {
    uint32_t address, bytes;
    uint16_t channels, height, width;
    ZnRef ref;
} ZnDestination;
typedef struct {
    uint16_t event, tile_first, tile_count;
    int16_t compute_node;
    uint8_t operation, read_count, retire_count, has_destination;
    ZnDestination destination;
    ZnRef reads[7], retired[7];
} ZnEvent;
typedef struct {
    uint32_t epoch, tag;
    uint16_t event_index;
    uint8_t operation;
    ZnRef ref;
    const ZnEvent *job;
} ZnRequest;
typedef struct {
    const ZnEvent *events;
    uint32_t epoch, next_tag;
    uint16_t count, cursor;
    uint8_t phase, index, pending, fault, done;
    ZnRequest request;
} ZnDispatch;

/* Input tensor -1/slot0/generation1 must already be published. Epoch must
 * exceed every prior frame epoch in the hardware ledgers; no wrap allowed.
 * Caller validates plan/model hashes and reserves DDR before initialization. */
int zn_dispatch_init(ZnDispatch *, const ZnEvent *, uint16_t, uint32_t epoch);
/* 1: stable request, 0: complete, -1: latched fault. No work starts here. */
int zn_dispatch_next(ZnDispatch *, ZnRequest *);
/* BUSY preserves identical request/tag. Unexpected ACK latches a fault. */
int zn_dispatch_ack(ZnDispatch *, uint32_t tag, uint8_t operation, int status);
#endif
