#ifndef Z100_NATIVE_GRAPH_NETWORK_BOOTSTRAP_V1_H
#define Z100_NATIVE_GRAPH_NETWORK_BOOTSTRAP_V1_H

#include "native_graph_lwip_v1.h"
#include "netif/xadapter.h"

enum {
    ZN_NATIVE_NETBOOT_V1_READY = 0,
    ZN_NATIVE_NETBOOT_V1_STARTING = 1,
    ZN_NATIVE_NETBOOT_V1_ARGUMENT = -1,
    ZN_NATIVE_NETBOOT_V1_STATE = -2,
    ZN_NATIVE_NETBOOT_V1_FAILED = -3
};
enum {
    ZN_NATIVE_NETBOOT_V1_STACK = 1,
    ZN_NATIVE_NETBOOT_V1_INTERFACE,
    ZN_NATIVE_NETBOOT_V1_DEFAULT_UP,
    ZN_NATIVE_NETBOOT_V1_ALLOCATE,
    ZN_NATIVE_NETBOOT_V1_BIND,
    ZN_NATIVE_NETBOOT_V1_LISTEN,
    ZN_NATIVE_NETBOOT_V1_ATTACH,
    ZN_NATIVE_NETBOOT_V1_DONE
};

typedef struct ZnNativeGraphNetworkConfigV1 {
    uint8_t address[4], netmask[4], gateway[4], mac[6];
    uint16_t port;
} ZnNativeGraphNetworkConfigV1;

/* Cold standalone Cortex-A9 SDT startup only, before other users of lwIP/GEM.
 * SDK xemac_add owns GEM/PHY and its SDT XSetupInterruptSystem path; this
 * candidate never installs a competing GIC handler or reinitializes GIC.
 * It may enable IRQs inside the SDK before returning. The matching platform,
 * initialized running tick source and exclusive SDK heap/DMA buffers must
 * already exist. Do not run on an unqualified BSP/board or live network stack.
 * All objects, buffers and callback contexts remain caller-owned and stable.
 * Zero once. No retry, teardown, graph reset/abort/ACK or reservation release.
 * Failure retains partial netif/PCB ownership for external diagnosis/recovery. */
typedef struct ZnNativeGraphNetworkBootstrapV1 {
    uint32_t magic;
    int32_t state, stage, last_code;
    ZnNativeGraphLwipV1 *network;
    ZnNativeGraphNetworkConfigV1 config;
    struct netif interface;
    struct tcp_pcb *pcb; /* active allocation, or converted listening PCB */
} ZnNativeGraphNetworkBootstrapV1;

/* Requires real lwip_bind then service_init_v2, with network still BOUND.
 * No default IP/MAC/port: caller supplies its deployment configuration.
 * Preflight rejects aliases/invalid IPv4 without IO or mutation. After the
 * first SDK call, failures are terminal and side effects may have occurred.
 * SDK PHY startup is synchronous and has no preemptible deadline here.
 * READY means attach succeeded; it does not prove link, IRQ delivery or peer
 * reachability. Thereafter use native_graph_lwip pump and explicit rearm. */
int zn_native_graph_network_bootstrap_v1(ZnNativeGraphNetworkBootstrapV1 *,
    ZnNativeGraphLwipV1 *, const ZnNativeGraphNetworkConfigV1 *);

#endif
