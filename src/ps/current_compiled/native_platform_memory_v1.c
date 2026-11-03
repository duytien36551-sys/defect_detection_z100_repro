#include "native_platform_memory_v1.h"

#include "v8_sha256.h"

#include <string.h>

typedef struct {
    uint64_t begin;
    uint64_t end;
} PhysicalSpan;

typedef struct {
    uintptr_t begin;
    uintptr_t end;
} CpuSpan;

static int physical_span(uint64_t begin, uint64_t bytes, PhysicalSpan *out)
{
    if (!out || !bytes || begin > UINT64_MAX - bytes ||
        begin >= ZN_NPMV1_PHYSICAL_ADDRESS_LIMIT ||
        bytes > ZN_NPMV1_PHYSICAL_ADDRESS_LIMIT - begin)
        return 0;
    out->begin = begin;
    out->end = begin + bytes;
    return 1;
}

static int cpu_span(const void *base, size_t bytes, CpuSpan *out)
{
    uintptr_t begin;
    if (!base || !bytes || !out)
        return 0;
    begin = (uintptr_t)base;
    if ((uintmax_t)bytes > (uintmax_t)(UINTPTR_MAX - begin))
        return 0;
    out->begin = begin;
    out->end = begin + (uintptr_t)bytes;
    return 1;
}

static int physical_overlap(PhysicalSpan a, PhysicalSpan b)
{
    return a.begin < b.end && b.begin < a.end;
}

static int cpu_overlap(CpuSpan a, CpuSpan b)
{
    return a.begin < b.end && b.begin < a.end;
}

static int reservation_covers(
    const ZnNativePlatformReservationV1 *reservation,
    PhysicalSpan required,
    PhysicalSpan *out)
{
    PhysicalSpan span;
    if (!reservation || !physical_span(reservation->address, reservation->bytes, &span) ||
        span.begin > required.begin || span.end < required.end)
        return 0;
    if (out)
        *out = span;
    return 1;
}

static int mapped_range(
    const ZnNativePlatformMappedSpanV1 *mapping,
    PhysicalSpan required,
    uint8_t **cpu_address,
    CpuSpan *cpu_range)
{
    PhysicalSpan mapped;
    CpuSpan whole_cpu;
    uint64_t offset64;
    size_t offset;
    uintptr_t begin;
    uintptr_t end;

    if (!mapping || !cpu_address || !cpu_range ||
        !physical_span(mapping->physical_base, mapping->bytes, &mapped) ||
        mapped.begin > required.begin || mapped.end < required.end ||
        mapping->bytes > (uint64_t)SIZE_MAX ||
        mapping->cpu_bytes < (size_t)mapping->bytes ||
        !cpu_span(mapping->cpu_base, mapping->cpu_bytes, &whole_cpu))
        return 0;

    offset64 = required.begin - mapped.begin;
    if (offset64 > (uint64_t)SIZE_MAX)
        return 0;
    offset = (size_t)offset64;
    if (required.end - required.begin > mapping->bytes - offset64 ||
        offset > mapping->cpu_bytes ||
        required.end - required.begin > (uint64_t)(mapping->cpu_bytes - offset))
        return 0;

    begin = whole_cpu.begin + (uintptr_t)offset;
    if (required.end - required.begin > (uint64_t)(UINTPTR_MAX - begin))
        return 0;
    end = begin + (uintptr_t)(required.end - required.begin);
    cpu_range->begin = begin;
    cpu_range->end = end;
    *cpu_address = (uint8_t *)begin;
    return 1;
}

static int mapped_reservation_range(
    const ZnNativePlatformMappedSpanV1 *mapping,
    PhysicalSpan required,
    CpuSpan *cpu_range)
{
    PhysicalSpan mapped;
    CpuSpan whole_cpu;
    uint64_t offset64;
    size_t offset;
    uintptr_t begin;
    uintptr_t end;

    if (!mapping || !cpu_range ||
        !physical_span(mapping->physical_base, mapping->bytes, &mapped) ||
        mapped.begin > required.begin || mapped.end < required.end ||
        mapping->bytes > (uint64_t)SIZE_MAX ||
        mapping->cpu_bytes < (size_t)mapping->bytes ||
        !cpu_span(mapping->cpu_base, mapping->cpu_bytes, &whole_cpu))
        return 0;
    offset64 = required.begin - mapped.begin;
    if (offset64 > (uint64_t)SIZE_MAX)
        return 0;
    offset = (size_t)offset64;
    if (required.end - required.begin > mapping->bytes - offset64 ||
        offset > mapping->cpu_bytes ||
        required.end - required.begin > (uint64_t)(mapping->cpu_bytes - offset))
        return 0;
    begin = whole_cpu.begin + (uintptr_t)offset;
    if (required.end - required.begin > (uint64_t)(UINTPTR_MAX - begin))
        return 0;
    end = begin + (uintptr_t)(required.end - required.begin);
    cpu_range->begin = begin;
    cpu_range->end = end;
    return 1;
}

static int source_pointer_span(const ZnNativePlatformImageV1 *image, CpuSpan *span)
{
    if (!image || image->bytes > (uint64_t)SIZE_MAX)
        return 0;
    return cpu_span(image->data, (size_t)image->bytes, span);
}

static int source_hash_matches(const ZnNativePlatformImageV1 *image, const char *expected)
{
    char actual[65];
    if (!image || !image->data || !expected || !image->sha256 ||
        strcmp(image->sha256, expected) != 0)
        return 0;
    v8_sha256_hex(image->data, (size_t)image->bytes, actual);
    return strcmp(actual, expected) == 0;
}

static int fail_state(
    ZnNativePlatformMemoryStateV1 *state,
    int result,
    uint8_t stage,
    int callback_status)
{
    state->ready = 0;
    state->stage = stage;
    state->callback_status = callback_status;
    return result;
}

static int reserve_range(
    const ZnNativePlatformMemoryOpsV1 *ops,
    void *context,
    const ZnNativePlatformReservationV1 *reservation,
    ZnNativePlatformMemoryStateV1 *state,
    uint8_t stage)
{
    int status = ops->reserve(context, reservation);
    if (status == 0)
        return ZN_NPMV1_OK;
    if (status == 1)
        return fail_state(state, ZN_NPMV1_BUSY, stage, status);
    return fail_state(state, ZN_NPMV1_RESERVATION_FAILED, stage, status);
}

static int copy_range(
    const ZnNativePlatformMemoryOpsV1 *ops,
    void *context,
    uint8_t *destination,
    const uint8_t *source,
    size_t bytes,
    ZnNativePlatformMemoryStateV1 *state,
    uint8_t stage)
{
    int status = ops->copy(context, destination, source, bytes);
    if (status != 0)
        return fail_state(state, ZN_NPMV1_COPY_FAILED, stage, status);
    return ZN_NPMV1_OK;
}

static int cache_call(
    int status,
    ZnNativePlatformMemoryStateV1 *state,
    uint8_t stage)
{
    if (status != 0)
        return fail_state(state, ZN_NPMV1_CACHE_FAILED, stage, status);
    return ZN_NPMV1_OK;
}

int zn_native_platform_memory_prepare_v1(
    const ZnNativePlatformMemoryRequestV1 *request,
    const ZnNativePlatformMemoryOpsV1 *ops,
    void *context,
    ZnNativePlatformMemoryStateV1 *state)
{
    PhysicalSpan parameter_target, directory_target;
    PhysicalSpan parameter_reserved, directory_reserved, scratch_reserved;
    CpuSpan parameter_source_cpu, directory_source_cpu;
    CpuSpan parameter_destination_cpu, directory_destination_cpu, scratch_cpu;
    uint8_t *parameter_destination, *directory_destination;
    int status;

    if (!state)
        return ZN_NPMV1_INVALID;
    state->ready = 0;
    state->stage = ZN_NPMV1_STAGE_NONE;
    state->callback_status = 0;
    if (!request || !ops || !ops->reserve || !ops->copy || !ops->cache_clean ||
        !ops->barrier || !ops->invalidate_readback)
        return fail_state(state, ZN_NPMV1_INVALID, ZN_NPMV1_STAGE_PREFLIGHT, 0);

    if (!request->package_sha256 || !request->checkpoint_sha256 || !request->graph_sha256 ||
        strcmp(request->package_sha256, ZN_NPMV1_PACKAGE_SHA256) != 0 ||
        strcmp(request->checkpoint_sha256, ZN_NPMV1_CHECKPOINT_SHA256) != 0 ||
        strcmp(request->graph_sha256, ZN_NPMV1_GRAPH_SHA256) != 0 ||
        request->directory_model_crc32 != ZN_NPMV1_DIRECTORY_MODEL_CRC32 ||
        request->parameter_image_crc32 != ZN_NPMV1_PARAMETER_IMAGE_CRC32 ||
        request->directory_model_crc32 == request->parameter_image_crc32)
        return fail_state(state, ZN_NPMV1_IDENTITY_MISMATCH, ZN_NPMV1_STAGE_PREFLIGHT, 0);

    if (request->parameter_payload.physical_address != ZN_NPMV1_PARAMETER_ADDRESS ||
        request->parameter_payload.bytes != ZN_NPMV1_PARAMETER_BYTES ||
        request->directory.physical_address != ZN_NPMV1_DIRECTORY_ADDRESS ||
        request->directory.bytes != ZN_NPMV1_DIRECTORY_BYTES ||
        !physical_span(request->parameter_payload.physical_address,
                       request->parameter_payload.bytes, &parameter_target) ||
        !physical_span(request->directory.physical_address,
                       request->directory.bytes, &directory_target) ||
        physical_overlap(parameter_target, directory_target))
        return fail_state(state, ZN_NPMV1_INVALID, ZN_NPMV1_STAGE_PREFLIGHT, 0);

    if (!reservation_covers(&request->parameter_reservation, parameter_target,
                            &parameter_reserved) ||
        !reservation_covers(&request->directory_reservation, directory_target,
                            &directory_reserved) ||
        !physical_span(request->view_scratch_reservation.address,
                       request->view_scratch_reservation.bytes, &scratch_reserved) ||
        request->view_scratch_reservation.bytes < ZN_NPMV1_VIEW_SCRATCH_MIN_BYTES ||
        request->view_scratch_reservation.address % ZN_NPMV1_VIEW_SCRATCH_ALIGNMENT != 0 ||
        physical_overlap(parameter_reserved, directory_reserved) ||
        physical_overlap(parameter_reserved, scratch_reserved) ||
        physical_overlap(directory_reserved, scratch_reserved))
        return fail_state(state, ZN_NPMV1_INVALID, ZN_NPMV1_STAGE_PREFLIGHT, 0);

    if (!source_pointer_span(&request->parameter_payload, &parameter_source_cpu) ||
        !source_pointer_span(&request->directory, &directory_source_cpu) ||
        !mapped_range(&request->parameter_mapping, parameter_target,
                      &parameter_destination, &parameter_destination_cpu) ||
        !mapped_range(&request->directory_mapping, directory_target,
                      &directory_destination, &directory_destination_cpu) ||
        !mapped_reservation_range(&request->view_scratch_mapping, scratch_reserved,
                                  &scratch_cpu))
        return fail_state(state, ZN_NPMV1_INVALID, ZN_NPMV1_STAGE_PREFLIGHT, 0);

    if (physical_overlap(parameter_target, directory_target) ||
        cpu_overlap(parameter_destination_cpu, directory_destination_cpu) ||
        cpu_overlap(parameter_destination_cpu, scratch_cpu) ||
        cpu_overlap(directory_destination_cpu, scratch_cpu) ||
        cpu_overlap(parameter_source_cpu, directory_source_cpu) ||
        cpu_overlap(parameter_source_cpu, parameter_destination_cpu) ||
        cpu_overlap(parameter_source_cpu, directory_destination_cpu) ||
        cpu_overlap(parameter_source_cpu, scratch_cpu) ||
        cpu_overlap(directory_source_cpu, parameter_destination_cpu) ||
        cpu_overlap(directory_source_cpu, directory_destination_cpu) ||
        cpu_overlap(directory_source_cpu, scratch_cpu))
        return fail_state(state, ZN_NPMV1_INVALID, ZN_NPMV1_STAGE_PREFLIGHT, 0);

    if (!request->parameter_payload.sha256 || !request->directory.sha256 ||
        strcmp(request->parameter_payload.sha256, ZN_NPMV1_PARAMETER_SHA256) != 0 ||
        strcmp(request->directory.sha256, ZN_NPMV1_DIRECTORY_SHA256) != 0)
        return fail_state(state, ZN_NPMV1_IDENTITY_MISMATCH, ZN_NPMV1_STAGE_PREFLIGHT, 0);
    if (!source_hash_matches(&request->parameter_payload, ZN_NPMV1_PARAMETER_SHA256) ||
        !source_hash_matches(&request->directory, ZN_NPMV1_DIRECTORY_SHA256))
        return fail_state(state, ZN_NPMV1_SOURCE_HASH_MISMATCH,
                          ZN_NPMV1_STAGE_SOURCE_HASH, 0);

    status = reserve_range(ops, context, &request->parameter_reservation, state,
                           ZN_NPMV1_STAGE_RESERVE_PARAMETER);
    if (status != ZN_NPMV1_OK)
        return status;
    status = reserve_range(ops, context, &request->directory_reservation, state,
                           ZN_NPMV1_STAGE_RESERVE_DIRECTORY);
    if (status != ZN_NPMV1_OK)
        return status;
    status = reserve_range(ops, context, &request->view_scratch_reservation, state,
                           ZN_NPMV1_STAGE_RESERVE_VIEW_SCRATCH);
    if (status != ZN_NPMV1_OK)
        return status;

    status = copy_range(ops, context, parameter_destination,
                        request->parameter_payload.data,
                        (size_t)request->parameter_payload.bytes, state,
                        ZN_NPMV1_STAGE_COPY_PARAMETER);
    if (status != ZN_NPMV1_OK)
        return status;
    status = copy_range(ops, context, directory_destination,
                        request->directory.data,
                        (size_t)request->directory.bytes, state,
                        ZN_NPMV1_STAGE_COPY_DIRECTORY);
    if (status != ZN_NPMV1_OK)
        return status;

    status = cache_call(ops->cache_clean(context, parameter_destination,
                                         (size_t)request->parameter_payload.bytes),
                        state, ZN_NPMV1_STAGE_CLEAN_PARAMETER);
    if (status != ZN_NPMV1_OK)
        return status;
    status = cache_call(ops->cache_clean(context, directory_destination,
                                         (size_t)request->directory.bytes),
                        state, ZN_NPMV1_STAGE_CLEAN_DIRECTORY);
    if (status != ZN_NPMV1_OK)
        return status;
    status = cache_call(ops->barrier(context), state,
                        ZN_NPMV1_STAGE_BARRIER_AFTER_CLEAN);
    if (status != ZN_NPMV1_OK)
        return status;
    status = cache_call(ops->invalidate_readback(context, parameter_destination,
                                                 (size_t)request->parameter_payload.bytes),
                        state, ZN_NPMV1_STAGE_INVALIDATE_PARAMETER);
    if (status != ZN_NPMV1_OK)
        return status;
    status = cache_call(ops->invalidate_readback(context, directory_destination,
                                                 (size_t)request->directory.bytes),
                        state, ZN_NPMV1_STAGE_INVALIDATE_DIRECTORY);
    if (status != ZN_NPMV1_OK)
        return status;
    status = cache_call(ops->barrier(context), state,
                        ZN_NPMV1_STAGE_BARRIER_AFTER_INVALIDATE);
    if (status != ZN_NPMV1_OK)
        return status;

    state->stage = ZN_NPMV1_STAGE_READBACK_HASH;
    {
        char actual[65];
        v8_sha256_hex(parameter_destination,
                      (size_t)request->parameter_payload.bytes, actual);
        if (strcmp(actual, ZN_NPMV1_PARAMETER_SHA256) != 0)
            return fail_state(state, ZN_NPMV1_READBACK_HASH_MISMATCH,
                              ZN_NPMV1_STAGE_READBACK_HASH, 0);
    }
    {
        char actual[65];
        v8_sha256_hex(directory_destination, (size_t)request->directory.bytes, actual);
        if (strcmp(actual, ZN_NPMV1_DIRECTORY_SHA256) != 0)
            return fail_state(state, ZN_NPMV1_READBACK_HASH_MISMATCH,
                              ZN_NPMV1_STAGE_READBACK_HASH, 0);
    }

    state->ready = 1;
    state->stage = ZN_NPMV1_STAGE_READY;
    state->callback_status = 0;
    return ZN_NPMV1_OK;
}
