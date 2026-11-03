#ifndef Z100_NATIVE_VIEW_BINDINGS_V1_H
#define Z100_NATIVE_VIEW_BINDINGS_V1_H
#include "native_view_materialize_v1.h"
/* 0 converted; 1 direct/nonConv event; -1 invalid. No MMIO/dispatch ACK.
 * Same epoch200 graph/arena identities and fixed local generation schedule as
 * graph_plan.h. Caller supplies exact current leased sources in event read order,
 * coherent CPU data, and separate scratch. This does not create a ledger tensor. */
int zn_native_view_input_v1(const ZnRequest *,const ZnNativeViewSourceV1 *,
                          uint8_t,uint8_t *,size_t);
const ZnEvent *zn_native_view_event_v1(uint16_t);
#endif
