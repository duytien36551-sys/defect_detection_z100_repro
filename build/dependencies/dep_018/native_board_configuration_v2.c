/* Explicit offline candidate. No board/hardware qualification. */
#include "native_board_entry_v2.h"
#include <stddef.h>
_Static_assert(sizeof(ZnNativeBoardConfigV2)==120,"board-v2 A9 ABI");
_Static_assert(offsetof(ZnNativeBoardConfigV2,network)==0,"network offset");
_Static_assert(offsetof(ZnNativeBoardConfigV2,ids)==20,"ids offset");
_Static_assert(offsetof(ZnNativeBoardConfigV2,initial_epoch)==52,"initial_epoch offset");
_Static_assert(offsetof(ZnNativeBoardConfigV2,poll_steps)==56,"poll_steps offset");
_Static_assert(offsetof(ZnNativeBoardConfigV2,graph_timeout_us)==64,"graph_timeout_us offset");
_Static_assert(offsetof(ZnNativeBoardConfigV2,connection_timeout_us)==72,"connection_timeout_us offset");
_Static_assert(offsetof(ZnNativeBoardConfigV2,network_max_sample_gap_ms)==80,"network_max_sample_gap_ms offset");
_Static_assert(offsetof(ZnNativeBoardConfigV2,pool_ids)==84,"Pool config offset");
const ZnNativeBoardConfigV2 zn_native_board_configuration_v2 = {
    .network = {
        .address = {192,168,10,2},
        .netmask = {255,255,255,0},
        .gateway = {0,0,0,0},
        .mac = {2,10,53,0,1,8},
        .port = 5001
    },
    .ids = {
        .job_base = UINT32_C(1000),
        .token_base = UINT32_C(100000),
        .tag_base = UINT32_C(10000000),
        .load_timeout_cycles = UINT32_C(100000000),
        .parameter_timeout_cycles = UINT32_C(100000000),
        .write_timeout_cycles = UINT32_C(100000000),
        .preaccept_timeout_cycles = UINT32_C(100000000),
        .first_bank = UINT32_C(0),
    },
    .initial_epoch = UINT32_C(1),
    .poll_steps = UINT32_C(64),
    .graph_timeout_us = UINT64_C(30000000),
    .connection_timeout_us = UINT64_C(60000000),
    .network_max_sample_gap_ms = UINT32_C(60000),
    .pool_ids = {
        .job_base=50000u,.token_base=1000000u,.tag_base=100000000u,
        .load_timeout=100000000u,.compute_timeout=100000000u,
        .write_timeout=100000000u,.preaccept_timeout=100000000u,.first_bank=0
    },
};
