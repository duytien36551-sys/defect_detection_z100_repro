#ifndef Z100_NATIVE_SLOT_MMIO_H
#define Z100_NATIVE_SLOT_MMIO_H
#include <stdint.h>
enum { ZN_MMIO_OK=0,ZN_MMIO_ARGUMENT=-1,ZN_MMIO_IO=-2,ZN_MMIO_IDENTITY=-3,
       ZN_MMIO_BUSY=-4,ZN_MMIO_TIMEOUT=-5,ZN_MMIO_PROTOCOL=-6 };
typedef struct {
    uint8_t opcode,slot,success;
    uint32_t tag,epoch,generation,address;
    uint16_t tensor,channels,height,width,first_row,tile_height;
} ZnSlotCommand;
typedef struct {
    /* Single owner per device; callbacks provide ordered, completed device
     * accesses and platform memory barriers. This interface maps no address. */
    void *context;
    int (*read32)(void *,uint32_t offset,uint32_t *value);
    int (*write32)(void *,uint32_t offset,uint32_t value);
} ZnSlotMmio;
int zn_slot_encode(const ZnSlotCommand *,uint32_t words[7]);
/* Writes complete command only when bridge idle and ID matches. IO errors may
 * leave submission ambiguous; caller must inspect/drain, never blindly retry. */
int zn_slot_mmio_submit(const ZnSlotMmio *,uint8_t client,const ZnSlotCommand *);
/* Timeout/foreign ACK leaves transaction retained. Can resume collection with
 * the same client/command. Success returns manager code; BUSY is not retried.
 * Does not reset hardware or fabricate publication/IO quiescence. */
int zn_slot_mmio_collect(const ZnSlotMmio *,uint8_t client,const ZnSlotCommand *,uint32_t poll_budget,uint8_t *manager_code);
#endif
