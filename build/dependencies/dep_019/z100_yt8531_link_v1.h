#ifndef Z100_YT8531_LINK_V1_H
#define Z100_YT8531_LINK_V1_H
#include <stdint.h>
typedef struct {
    void *context;
    int (*read)(void *, uint8_t phy, uint8_t reg, uint16_t *value);
    void (*delay_ms)(void *, unsigned ms);
} ZnYt8531LinkOpsV1;
/* Read-only exact-ID/auto-negotiation observer. Never resets PHY or changes
 * advertisement/RGMII delays. Caller owns exclusive serialized MDIO access.
 * Returns full-duplex 10/100/1000, or -1 on ID/IO/config/timeout/unsupported.
 * Existing straps/delay setup must be physically qualified separately. */
int zn_yt8531_link_speed_v1(const ZnYt8531LinkOpsV1 *, uint8_t phy);
#endif
