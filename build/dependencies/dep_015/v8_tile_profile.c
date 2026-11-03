#include "v8_tile_profile.h"

V8TileProfile v8_tile_profile __attribute__((aligned(64)));

void v8_tile_profile_reset(void)
{
    v8_tile_profile = (V8TileProfile){0};
}
