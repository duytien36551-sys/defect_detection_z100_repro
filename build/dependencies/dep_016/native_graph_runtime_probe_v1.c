#include "graph_plan.h"
#include "native_arena_owner_v1.h"
#include "native_arena_conv_lifecycle_v1.h"
#include "native_arena_nonconv_lifecycle_v1.h"
#include "native_feature_cache_v1.h"
#include "native_graph_executor_v1.h"
#include "native_nonconv_runtime_hooks_v1.h"
#include "native_platform_memory_v1.h"
#include "native_view_conv_runtime_hooks_v1.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    PROBE_EPOCH = 640,
    PROBE_ARENA_BASE = 0x10000000,
    PROBE_ARENA_BYTES = 5201920,
    PROBE_SCRATCH_BASE = 0x22000000,
    PROBE_SCRATCH_BYTES = 1228800,
    PROBE_HEADS_BASE = 0x24000000,
    PROBE_HEADS_BYTES = 613248
};

_Alignas(64) static uint8_t arena_storage[PROBE_ARENA_BYTES];
_Alignas(64) static uint8_t scratch_storage[PROBE_SCRATCH_BYTES];
_Alignas(64) static uint8_t heads_storage[PROBE_HEADS_BYTES];

typedef struct ProbeState {
    uint32_t release_count;
} ProbeState;

static int probe_clean(void *context, void *address, size_t bytes)
{
    (void)context;
    return address != NULL && bytes != 0u ? 0 : -1;
}

static int probe_barrier(void *context)
{
    (void)context;
    return 0;
}

static int probe_invalidate(void *context, void *address, size_t bytes)
{
    (void)context;
    return address != NULL && bytes != 0u ? 0 : -1;
}

static int probe_release(void *context,
                         const ZnNativeGraphScratchLeaseV2 *lease)
{
    ProbeState *state = (ProbeState *)context;
    if (!state || !lease)
        return -1;
    ++state->release_count;
    return 0;
}

static int probe_mmio_read(void *context, uint32_t offset, uint32_t *value)
{
    (void)context;
    (void)offset;
    if (!value)
        return -1;
    *value = 0u;
    return 0;
}

static int probe_mmio_write(void *context, uint32_t offset, uint32_t value)
{
    (void)context;
    (void)offset;
    (void)value;
    return 0;
}

static int probe_mmio_barrier(void *context)
{
    (void)context;
    return 0;
}

static int probe_nonconv_map_source(
    void *context, const ZnRequest *request, uint8_t read_index,
    uint32_t expected_address, uint32_t expected_bytes,
    ZnNativeArenaNonConvSourceV1 *source)
{
    (void)context;
    (void)request;
    (void)read_index;
    (void)expected_address;
    (void)expected_bytes;
    (void)source;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int probe_nonconv_source_visible(
    void *context, const ZnRequest *request, uint8_t read_index,
    const ZnNativeArenaNonConvSourceV1 *source)
{
    (void)context;
    (void)request;
    (void)read_index;
    (void)source;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int probe_nonconv_map_output(
    void *context, const ZnRequest *request, uint32_t expected_address,
    uint32_t output_bytes, ZnNativeArenaNonConvOutputV1 *output)
{
    (void)context;
    (void)request;
    (void)expected_address;
    (void)output_bytes;
    (void)output;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int probe_nonconv_clean_output(
    void *context, const ZnRequest *request,
    const ZnNativeArenaNonConvOutputV1 *output, uint32_t output_bytes)
{
    (void)context;
    (void)request;
    (void)output;
    (void)output_bytes;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int probe_nonconv_publish_output(
    void *context, const ZnRequest *request,
    const ZnNativeArenaNonConvOutputV1 *output, uint32_t output_bytes)
{
    (void)context;
    (void)request;
    (void)output;
    (void)output_bytes;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int probe_nonconv_drain_ready(
    void *context, const ZnRequest *request,
    ZnNativeArenaQuiescenceEvidenceV1 *evidence)
{
    (void)context;
    (void)request;
    (void)evidence;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int probe_nonconv_return_graph_read(
    void *context, const ZnRequest *request, uint8_t read_index,
    uint32_t physical_address, ZnRef ref)
{
    (void)context;
    (void)request;
    (void)read_index;
    (void)physical_address;
    (void)ref;
    return ZN_NATIVE_ARENA_NONCONV_HOOK_FAILED_V1;
}

static int probe_resolve_conv(void *context, const ZnRequest *request,
                              ZnNativeGraphConvBindingV2 *binding)
{
    (void)context;
    (void)request;
    (void)binding;
    return ZN_NATIVE_GRAPH_EXECUTOR_RESOLVER_UNSUPPORTED_V1;
}

static ZnNativeArenaConfigV1 probe_config(void)
{
    ZnNativeArenaConfigV1 config;
    const ZnNativeArenaRegionV1 regions[ZN_NATIVE_ARENA_SLOT_COUNT_V1] = {
        { 268435456u, 1638400u }, { 270073856u, 1638400u },
        { 271712256u, 819200u }, { 272531456u, 409600u },
        { 272941056u, 409600u }, { 273350656u, 122880u },
        { 273473536u, 163840u }
    };
    memset(&config, 0, sizeof config);
    config.arena_base = PROBE_ARENA_BASE;
    config.arena_end = PROBE_ARENA_BASE + PROBE_ARENA_BYTES;
    config.arena_bytes = PROBE_ARENA_BYTES;
    config.alignment = 4096u;
    memcpy(config.slots, regions, sizeof regions);
    memcpy(config.package_sha256, ZN_NATIVE_ARENA_PACKAGE_SHA256_V1,
           sizeof config.package_sha256);
    memcpy(config.graph_sha256, ZN_NATIVE_ARENA_GRAPH_SHA256_V1,
           sizeof config.graph_sha256);
    memcpy(config.plan_sha256, ZN_NATIVE_ARENA_PLAN_SHA256_V1,
           sizeof config.plan_sha256);
    memcpy(config.manifest_sha256, ZN_NATIVE_ARENA_MANIFEST_SHA256_V1,
           sizeof config.manifest_sha256);
    return config;
}

static ZnNativePlatformMappedSpanV1 probe_mapping(
    uint64_t physical_base, void *cpu_base, size_t bytes)
{
    ZnNativePlatformMappedSpanV1 mapping;
    mapping.physical_base = physical_base;
    mapping.bytes = bytes;
    mapping.cpu_base = cpu_base;
    mapping.cpu_bytes = bytes;
    return mapping;
}

int main(void)
{
    ZnNativeArenaConfigV1 config = probe_config();
    ZnDispatch dispatch;
    ZnNativeArenaOwnerV1 owner;
    ZnNativeArenaConvLifecycleV1 conv;
    ZnNativeArenaNonConvLifecycleV1 nonconv;
    ZnNativeFeatureCacheV1 cache;
    ZnNativeViewConvRuntimeV1 view_runtime;
    ZnNativeNonConvRuntimeHooksV1 nonconv_runtime;
    ZnNativeGraphExecutorV1 executor;
    ZnNativeGraphConvHooksV2 view_hooks;
    ZnNativeArenaNonConvHooksV1 nonconv_hooks;
    ZnNativePlatformMemoryOpsV1 memory_ops;
    ZnNativeConvMmioOpsV2 mmio_ops;
    ZnNativePlatformMappedSpanV1 arena_mapping;
    ZnNativePlatformMappedSpanV1 scratch_mapping;
    ZnNativePlatformMappedSpanV1 heads_mapping;
    ProbeState state;

    memset(&dispatch, 0, sizeof dispatch);
    memset(&owner, 0, sizeof owner);
    memset(&conv, 0, sizeof conv);
    memset(&nonconv, 0, sizeof nonconv);
    memset(&cache, 0, sizeof cache);
    memset(&view_runtime, 0, sizeof view_runtime);
    memset(&nonconv_runtime, 0, sizeof nonconv_runtime);
    memset(&executor, 0, sizeof executor);
    memset(&view_hooks, 0, sizeof view_hooks);
    memset(&nonconv_hooks, 0, sizeof nonconv_hooks);
    memset(&state, 0, sizeof state);

    if (zn_dispatch_init(&dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, PROBE_EPOCH) != 0 ||
        zn_native_arena_owner_init_v1(&owner, &config, &dispatch,
                                      PROBE_EPOCH) !=
            ZN_NATIVE_ARENA_OWNER_V1_ACKED)
        return 2;

    memory_ops.cache_clean = probe_clean;
    memory_ops.barrier = probe_barrier;
    memory_ops.invalidate_readback = probe_invalidate;
    mmio_ops.context = NULL;
    mmio_ops.read32 = probe_mmio_read;
    mmio_ops.write32 = probe_mmio_write;
    mmio_ops.write_barrier = probe_mmio_barrier;
    arena_mapping = probe_mapping(PROBE_ARENA_BASE, arena_storage,
                                  sizeof arena_storage);
    scratch_mapping = probe_mapping(PROBE_SCRATCH_BASE, scratch_storage,
                                    sizeof scratch_storage);
    heads_mapping = probe_mapping(PROBE_HEADS_BASE, heads_storage,
                                  sizeof heads_storage);

    if (zn_native_feature_cache_init_v1(&cache, &memory_ops, &state,
                                        probe_release, &state) !=
            ZN_NATIVE_FEATURE_CACHE_V1_READY ||
        zn_native_view_conv_runtime_hooks_init_v1(
            &view_runtime, &conv, &cache, &arena_mapping, &scratch_mapping,
            &view_hooks) != ZN_NATIVE_VIEW_CONV_RUNTIME_V1_READY ||
        zn_native_arena_conv_lifecycle_init_v1(
            &conv, &owner, &mmio_ops, &view_hooks) !=
            ZN_NATIVE_ARENA_CONV_LIFECYCLE_V1_ACKED)
        return 3;

    nonconv_hooks.context = NULL;
    nonconv_hooks.map_source = probe_nonconv_map_source;
    nonconv_hooks.source_visible = probe_nonconv_source_visible;
    nonconv_hooks.map_output = probe_nonconv_map_output;
    nonconv_hooks.clean_output = probe_nonconv_clean_output;
    nonconv_hooks.publish_output = probe_nonconv_publish_output;
    nonconv_hooks.drain_ready = probe_nonconv_drain_ready;
    nonconv_hooks.return_graph_read = probe_nonconv_return_graph_read;
    if (zn_native_nonconv_runtime_hooks_init_v1(
            &nonconv_runtime, &owner, &dispatch, &nonconv, &arena_mapping,
            &heads_mapping, 1u, &memory_ops, &state, &nonconv_hooks) != 0 ||
        zn_native_arena_nonconv_lifecycle_init_v1(
            &nonconv, &owner, &nonconv_hooks) !=
            ZN_NATIVE_ARENA_NONCONV_LIFECYCLE_V1_ACKED ||
        zn_native_graph_executor_v1_init(
            &executor, &owner, &dispatch, &conv, &nonconv,
            probe_resolve_conv, NULL) != ZN_NATIVE_GRAPH_EXECUTOR_V1_ACKED)
        return 4;

    printf("NATIVE_GRAPH_RUNTIME_PROBE_PASS events=%u view_hooks=1 nonconv_hooks=1 executor=1 physical_mmio=0 board_access=0 throughput_claim=0\n",
           (unsigned)ZN_NATIVE_ARENA_EVENT_COUNT_V1);
    return 0;
}
