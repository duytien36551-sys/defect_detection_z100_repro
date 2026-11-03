#include "native_direct_conv_runtime_hooks_v1.h"
#include "native_direct_bindings_v2.h"
#include "native_conv_command_v1.h"

#include <limits.h>
#include <string.h>

static int ref_equal(ZnRef a, ZnRef b)
{
    return a.slot == b.slot && a.tensor == b.tensor && a.generation == b.generation;
}

static int callback_code(ZnNativeFeatureCacheCodeV1 code)
{
    return code == ZN_NATIVE_FEATURE_CACHE_V1_READY ? 0 :
           code == ZN_NATIVE_FEATURE_CACHE_V1_BUSY ? 1 : -1;
}

static int cpu_disjoint(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t ab = (uintptr_t)a, bb = (uintptr_t)b;
    if (!a || !b || !an || !bn || an > UINTPTR_MAX - ab || bn > UINTPTR_MAX - bb)
        return 0;
    return ab + an <= bb || bb + bn <= ab;
}

/* Reconstruct the generated binding, rather than trusting a caller's claim
 * that this is a direct event. The generator rejects views and stale plans. */
static int canonical_binding(const ZnRequest *request, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeDirectIdsV2 ids;
    ZnNativeGraphConvBindingV2 expected;
    uint32_t actual_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t expected_words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    if (!request || !binding) return 0;
    memset(&ids, 0, sizeof ids);
    ids.job_base = binding->expected_job_base;
    ids.token_base = binding->expected_token_base;
    ids.tag_base = binding->expected_tag_base;
    ids.load_timeout_cycles = binding->command.load_timeout_cycles;
    ids.parameter_timeout_cycles = binding->command.parameter_timeout_cycles;
    ids.write_timeout_cycles = binding->command.write_timeout_cycles;
    ids.preaccept_timeout_cycles = binding->command.preaccept_timeout_cycles;
    ids.first_bank = (binding->command.flags & ZN_NC_SHADOW_FIRST_BANK) != 0u;
    if (zn_native_direct_binding_v2(request, &ids, &binding->scratch, &expected) != 0 ||
        binding->dispatch_epoch != expected.dispatch_epoch ||
        binding->dispatch_tag != expected.dispatch_tag || binding->event_index != expected.event_index ||
        binding->graph_read_count != 1 || expected.graph_read_count != 1 ||
        !ref_equal(binding->graph_read_refs[0], expected.graph_read_refs[0]) ||
        !ref_equal(binding->destination_ref, expected.destination_ref) ||
        binding->source_span.base != expected.source_span.base || binding->source_span.bytes != expected.source_span.bytes ||
        binding->expected_cookie != expected.expected_cookie || binding->expected_tiles != expected.expected_tiles ||
        memcmp(binding->package_sha256, expected.package_sha256, 65) ||
        memcmp(binding->checkpoint_sha256, expected.checkpoint_sha256, 65) ||
        memcmp(binding->graph_sha256, expected.graph_sha256, 65) ||
        zn_native_conv_command_encode_v1(&binding->command, actual_words) != ZN_NATIVE_CONV_COMMAND_OK ||
        zn_native_conv_command_encode_v1(&expected.command, expected_words) != ZN_NATIVE_CONV_COMMAND_OK)
        return 0;
    return memcmp(actual_words, expected_words, sizeof actual_words) == 0;
}

static int check_active(ZnNativeDirectConvRuntimeV1 *runtime, const ZnRequest *request,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    const ZnNativePlatformMappedSpanV1 *saved;
    if (!runtime || !runtime->active || !runtime->lifecycle) return -1;
    saved = &runtime->cache.arena_mapping;
    if (saved->physical_base != runtime->arena.physical_base || saved->bytes != runtime->arena.bytes ||
        saved->cpu_base != runtime->arena.cpu_base || saved->cpu_bytes != runtime->arena.cpu_bytes)
        return -1;
    return callback_code(zn_native_feature_cache_check_binding_v1(
        &runtime->cache, runtime->lifecycle, request, binding));
}

static int check_leases(void *context, const ZnRequest *request,
                         const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeDirectConvRuntimeV1 *runtime = context;
    ZnNativeRuntimeTensorMapV1 source;
    ZnNativePlatformMappedSpanV1 mapping;
    ZnNativeFeatureCacheCodeV1 code;
    if (!runtime || !runtime->lifecycle || !request || !binding) return -1;
    if (runtime->active) return check_active(runtime, request, binding);
    if (request->operation != ZN_RUN || !canonical_binding(request, binding) ||
        zn_native_runtime_map_read_v1(runtime->lifecycle->owner,
            &runtime->lifecycle->active_dispatch_snapshot, request, 0, &runtime->arena, &source) != 0 ||
        !ref_equal(source.view.ref, binding->graph_read_refs[0]) ||
        source.physical_address != binding->source_span.base || source.view.bytes != binding->source_span.bytes ||
        !cpu_disjoint(runtime, sizeof *runtime, source.cpu_address, source.view.bytes))
        return -1;
    mapping.physical_base = source.physical_address;
    mapping.bytes = source.view.bytes;
    mapping.cpu_base = source.cpu_address;
    mapping.cpu_bytes = source.view.bytes;
    code = zn_native_feature_cache_bind_v1(&runtime->cache, runtime->lifecycle,
        &runtime->lifecycle->active_dispatch_snapshot, request, binding, &mapping, &runtime->arena);
    if (code != ZN_NATIVE_FEATURE_CACHE_V1_READY) return callback_code(code);
    runtime->source_checked = 0;
    runtime->active = 1;
    return 0;
}

static int convert_views(void *context, const ZnRequest *request,
                          const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeDirectConvRuntimeV1 *runtime = context;
    int code = check_active(runtime, request, binding);
    if (code != 0 || request->operation != ZN_RUN) return code != 0 ? code : -1;
    /* Direct source is already in native layout. Never copy or modify it. */
    runtime->source_checked = 1;
    return 0;
}

static int clean_source(void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeDirectConvRuntimeV1 *runtime = context;
    if (!runtime || !runtime->lifecycle || !runtime->source_checked ||
        check_active(runtime, &runtime->lifecycle->active_request, binding) != 0) return -1;
    return callback_code(
        zn_native_feature_cache_prepare_direct_source_candidate_v1(
            &runtime->cache, binding));
}

static int source_ready(void *context, const ZnRequest *request,
                         const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeDirectConvRuntimeV1 *runtime = context;
    if (!runtime || !runtime->source_checked || check_active(runtime, request, binding) != 0) return -1;
    return callback_code(zn_native_feature_cache_check_source_ready_v1(
        &runtime->cache, runtime->lifecycle, request, binding));
}

static int invalidate_output(void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeDirectConvRuntimeV1 *runtime = context;
    if (!runtime || !runtime->active) return -1;
    return callback_code(zn_native_feature_cache_make_output_visible_v1(
        &runtime->cache, runtime->lifecycle, binding));
}

static int publish_output(void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeDirectConvRuntimeV1 *runtime = context;
    if (!runtime || !runtime->lifecycle ||
        runtime->cache.stage != ZN_NATIVE_FEATURE_CACHE_STAGE_V1_OUTPUT_VISIBLE) return -1;
    return check_active(runtime, &runtime->lifecycle->active_request, binding);
}

static int drain_ready(void *context, const ZnRequest *request,
                        const ZnNativeGraphConvBindingV2 *binding)
{
    return check_active(context, request, binding);
}

static int return_read(void *context, const ZnRequest *request,
                        const ZnNativeGraphConvBindingV2 *binding, uint8_t index)
{
    if (!request || !request->job || index != 0 || request->job->read_count != 1 ||
        !ref_equal(request->ref, request->job->reads[0])) return -1;
    return check_active(context, request, binding);
}

static int close_borrowed_source(void *context, const ZnNativeGraphScratchLeaseV2 *lease)
{
    ZnNativeDirectConvRuntimeV1 *runtime = context;
    const ZnNativeGraphScratchLeaseV2 *expected;
    if (!runtime || !runtime->active || !lease || runtime->closed_transactions == UINT32_MAX) return -1;
    expected = &runtime->cache.binding.scratch;
    if (lease->epoch != expected->epoch || lease->generation != expected->generation ||
        lease->base != expected->base || lease->bytes != expected->bytes) return -1;
    /* feature_cache has verified terminal success, drain and every graph RETURN.
     * The arena source remains owned by arena_owner; no allocator callback. */
    ++runtime->closed_transactions;
    return 0;
}

static int finish_source(void *context, const ZnNativeGraphConvBindingV2 *binding)
{
    ZnNativeDirectConvRuntimeV1 *runtime = context;
    ZnNativeFeatureCacheCodeV1 code;
    if (!runtime || !runtime->active || !runtime->lifecycle || !runtime->lifecycle->finishing) return -1;
    code = zn_native_feature_cache_release_scratch_v1(&runtime->cache, runtime->lifecycle, binding);
    if (code != ZN_NATIVE_FEATURE_CACHE_V1_READY) return callback_code(code);
    runtime->active = 0;
    runtime->source_checked = 0;
    return 0;
}

int zn_native_direct_conv_runtime_hooks_init_v1(
    ZnNativeDirectConvRuntimeV1 *runtime, ZnNativeArenaConvLifecycleV1 *lifecycle,
    const ZnNativePlatformMappedSpanV1 *arena,
    const ZnNativePlatformMemoryOpsV1 *memory, void *memory_context,
    ZnNativeGraphConvHooksV2 *hooks)
{
    ZnNativePlatformMappedSpanV1 mapping;
    ZnNativePlatformMemoryOpsV1 ops;
    if (!runtime || !lifecycle || !arena || !memory || !hooks || runtime->cache.magic != 0 ||
        !arena->cpu_base || !arena->bytes || arena->bytes != arena->cpu_bytes ||
        arena->physical_base >= UINT64_C(0x40000000) ||
        arena->bytes > UINT64_C(0x40000000) - arena->physical_base ||
        (arena->physical_base & 63u) || (arena->bytes & 63u) || ((uintptr_t)arena->cpu_base & 63u) ||
        !memory->cache_clean || !memory->barrier || !memory->invalidate_readback ||
        !cpu_disjoint(runtime, sizeof *runtime, arena->cpu_base, arena->cpu_bytes) ||
        !cpu_disjoint(lifecycle, sizeof *lifecycle, arena->cpu_base, arena->cpu_bytes) ||
        !cpu_disjoint(hooks, sizeof *hooks, arena->cpu_base, arena->cpu_bytes) ||
        !cpu_disjoint(runtime, sizeof *runtime, lifecycle, sizeof *lifecycle) ||
        !cpu_disjoint(runtime, sizeof *runtime, hooks, sizeof *hooks) ||
        !cpu_disjoint(lifecycle, sizeof *lifecycle, hooks, sizeof *hooks)) return -1;
    mapping = *arena;
    ops = *memory;
    memset(runtime, 0, sizeof *runtime);
    runtime->arena = mapping;
    runtime->lifecycle = lifecycle;
    if (zn_native_feature_cache_init_v1(&runtime->cache, &ops, memory_context,
            close_borrowed_source, runtime) != ZN_NATIVE_FEATURE_CACHE_V1_READY) return -1;
    memset(hooks, 0, sizeof *hooks);
    hooks->context = runtime;
    hooks->check_leases = check_leases;
    hooks->convert_views = convert_views;
    hooks->clean_source = clean_source;
    hooks->check_source_ready = source_ready;
    hooks->invalidate_output = invalidate_output;
    hooks->validate_and_publish = publish_output;
    hooks->drain_ready = drain_ready;
    hooks->return_graph_read = return_read;
    hooks->release_scratch = finish_source;
    return 0;
}
