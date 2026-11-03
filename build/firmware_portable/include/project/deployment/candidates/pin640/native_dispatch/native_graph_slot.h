#ifndef Z100_NATIVE_GRAPH_SLOT_H
#define Z100_NATIVE_GRAPH_SLOT_H
#include "native_dispatch.h"
#include "native_slot_mmio.h"
/* 0: graph client0 slot command; 1: RUN/DRAIN needs real compute/IO backend;
 * -1: malformed request. Does not submit, allocate physical DDR or execute IO. */
int zn_graph_slot_command(const ZnRequest *,ZnSlotCommand *,uint8_t *client);
/* Only after successful MMIO collect/identity validation. Native BUSY keeps the
 * same graph request pending; native errors latch graph fault, retain leases.
 * RUN/DRAIN cannot be acknowledged by this slot-management adapter. */
int zn_graph_slot_complete(ZnDispatch *,const ZnRequest *,uint8_t native_code);
#endif
