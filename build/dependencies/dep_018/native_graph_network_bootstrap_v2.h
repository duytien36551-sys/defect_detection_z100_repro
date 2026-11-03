#ifndef Z100_NATIVE_GRAPH_NETWORK_BOOTSTRAP_V2_H
#define Z100_NATIVE_GRAPH_NETWORK_BOOTSTRAP_V2_H

#include "native_graph_lwip_v2.h"
#include "native_lwip_timebase_v1.h"
#include "netif/xadapter.h"

enum {
    ZN_NATIVE_NETBOOT_V2_READY = 0,
    ZN_NATIVE_NETBOOT_V2_STARTING = 1,
    ZN_NATIVE_NETBOOT_V2_ARGUMENT = -1,
    ZN_NATIVE_NETBOOT_V2_STATE = -2,
    ZN_NATIVE_NETBOOT_V2_FAILED = -3
};
enum {
    ZN_NATIVE_NETBOOT_V2_TIMEBASE = 1,
    ZN_NATIVE_NETBOOT_V2_STACK,
    ZN_NATIVE_NETBOOT_V2_INTERFACE,
    ZN_NATIVE_NETBOOT_V2_DEFAULT_UP,
    ZN_NATIVE_NETBOOT_V2_ALLOCATE,
    ZN_NATIVE_NETBOOT_V2_BIND,
    ZN_NATIVE_NETBOOT_V2_LISTEN,
    ZN_NATIVE_NETBOOT_V2_ATTACH,
    ZN_NATIVE_NETBOOT_V2_DONE
};

typedef struct ZnNativeGraphNetworkConfigV2 {
    uint8_t address[4], netmask[4], gateway[4], mac[6];
    uint16_t port;
} ZnNativeGraphNetworkConfigV2;

/* Cold standalone Cortex-A9 SDT startup only, before other users of lwIP/GEM.
 * SDK xemac_add owns GEM/PHY and its SDT XSetupInterruptSystem path; this
 * candidate never installs a competing GIC handler or reinitializes GIC.
 * It may enable IRQs inside the SDK before returning. The matching platform,
 * initialized running tick source and exclusive SDK heap/DMA buffers must
 * already exist. Do not run on an unqualified BSP/board or live network stack.
 * All objects, buffers and callback contexts remain caller-owned and stable.
 * Zero once. No retry, teardown, graph reset/abort/ACK or reservation release.
 * Failure retains partial netif/PCB ownership for external diagnosis/recovery. */
typedef struct ZnNativeGraphNetworkBootstrapV2 {
    uint32_t magic;
    int32_t state, stage, last_code;
    ZnNativeGraphLwipV2 *network;
    ZnNativeGraphNetworkConfigV2 config;
    struct netif interface;
    struct tcp_pcb *pcb; /* active allocation, or converted listening PCB */
} ZnNativeGraphNetworkBootstrapV2;

/* Requires real lwip_bind then service_init_v2, with network still BOUND.
 * No default IP/MAC/port: caller supplies its deployment configuration.
 * timebase MUST use the session's identical tick callback/context/Hz and an
 * explicit stable context extent and sample-gap limit. Bind occurs here,
 * before lwip_init. No other timebase/sys_now owner may already be present.
 * Preflight rejects aliases/invalid IPv4 without IO or mutation. After the
 * first clock binding, failures are terminal and side effects may have occurred.
 * SDK PHY startup is synchronous and has no preemptible deadline here.
 * READY means attach succeeded; it does not prove link, IRQ delivery or peer
 * reachability. Thereafter use native_graph_lwip pump and explicit rearm. */
int zn_native_graph_network_bootstrap_v2(ZnNativeGraphNetworkBootstrapV2 *,
    ZnNativeGraphLwipV2 *, const ZnNativeGraphNetworkConfigV2 *,
    const ZnNativeLwipTimebaseConfigV1 *);

#endif
