#include "native_platform_memory_v1.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    EV_RESERVE_PARAMETER = 1,
    EV_RESERVE_DIRECTORY,
    EV_RESERVE_SCRATCH,
    EV_COPY_PARAMETER,
    EV_COPY_DIRECTORY,
    EV_CLEAN_PARAMETER,
    EV_CLEAN_DIRECTORY,
    EV_BARRIER_AFTER_CLEAN,
    EV_INVALIDATE_PARAMETER,
    EV_INVALIDATE_DIRECTORY,
    EV_BARRIER_AFTER_INVALIDATE,
    EVENT_CAPACITY = 32
};

typedef struct {
    int events[EVENT_CAPACITY];
    unsigned event_count;
    unsigned reserve_calls;
    unsigned barrier_calls;
    int reserve_status[3];
    int fail_event;
    int fail_status;
    int partial_copy_event;
    int corrupt_parameter_on_invalidate;
    int corrupt_directory_on_invalidate;
    uint8_t *parameter_destination;
    uint8_t *directory_destination;
} Mock;

typedef struct {
    ZnNativePlatformMemoryRequestV1 request;
    ZnNativePlatformMemoryOpsV1 ops;
    ZnNativePlatformMemoryStateV1 state;
    Mock mock;
    uint8_t *parameter_destination;
    uint8_t *directory_destination;
    uint8_t *scratch;
} Fixture;

static unsigned failures;
static unsigned checks;
static const uint8_t *parameter_file;
static const uint8_t *directory_file;

static void check(int condition, const char *name)
{
    ++checks;
    if (!condition) {
        fprintf(stderr, "FAIL %s\n", name);
        ++failures;
    }
}

static uint8_t *read_asset(const char *path, size_t expected_bytes)
{
    FILE *file;
    long length;
    uint8_t *data;
    size_t got;

    file = fopen(path, "rb");
    if (!file)
        return NULL;
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return NULL;
    }
    length = ftell(file);
    if (length < 0 || (uint64_t)length != (uint64_t)expected_bytes ||
        fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return NULL;
    }
    data = (uint8_t *)malloc(expected_bytes);
    if (!data) {
        fclose(file);
        return NULL;
    }
    got = fread(data, 1, expected_bytes, file);
    if (fclose(file) != 0 || got != expected_bytes) {
        free(data);
        return NULL;
    }
    return data;
}

static int record_event(Mock *mock, int event)
{
    if (mock->event_count >= EVENT_CAPACITY)
        return -90;
    mock->events[mock->event_count++] = event;
    return event == mock->fail_event ? mock->fail_status : 0;
}

static int mock_reserve(void *context, const ZnNativePlatformReservationV1 *range)
{
    Mock *mock = (Mock *)context;
    unsigned index = mock->reserve_calls++;
    int event;
    int status;
    static const uint64_t expected_address[3] = {
        ZN_NPMV1_PARAMETER_ADDRESS,
        ZN_NPMV1_DIRECTORY_ADDRESS,
        ZN_NPMV1_VIEW_SCRATCH_CANDIDATE_ADDRESS
    };
    static const uint64_t expected_bytes[3] = {
        ZN_NPMV1_PARAMETER_BYTES,
        ZN_NPMV1_DIRECTORY_BYTES,
        ZN_NPMV1_VIEW_SCRATCH_MIN_BYTES
    };

    if (index == 0)
        event = EV_RESERVE_PARAMETER;
    else if (index == 1)
        event = EV_RESERVE_DIRECTORY;
    else if (index == 2)
        event = EV_RESERVE_SCRATCH;
    else
        return -91;

    status = record_event(mock, event);
    if (status != 0)
        return status;
    if (!range || range->address != expected_address[index] ||
        range->bytes < expected_bytes[index])
        return -92;
    return mock->reserve_status[index];
}

static int mock_copy(void *context, uint8_t *destination,
                     const uint8_t *source, size_t bytes)
{
    Mock *mock = (Mock *)context;
    int event = destination == mock->parameter_destination ?
        EV_COPY_PARAMETER : EV_COPY_DIRECTORY;
    int status = record_event(mock, event);

    if (status != 0) {
        if (mock->partial_copy_event == event && bytes > 1)
            memcpy(destination, source, bytes / 2u);
        return status;
    }
    memcpy(destination, source, bytes);
    return 0;
}

static int mock_cache_clean(void *context, void *address, size_t bytes)
{
    Mock *mock = (Mock *)context;
    int event = address == mock->parameter_destination ?
        EV_CLEAN_PARAMETER : EV_CLEAN_DIRECTORY;
    if (!bytes)
        return -93;
    return record_event(mock, event);
}

static int mock_barrier(void *context)
{
    Mock *mock = (Mock *)context;
    int event = mock->barrier_calls++ == 0 ?
        EV_BARRIER_AFTER_CLEAN : EV_BARRIER_AFTER_INVALIDATE;
    return record_event(mock, event);
}

static int mock_invalidate(void *context, void *address, size_t bytes)
{
    Mock *mock = (Mock *)context;
    int event = address == mock->parameter_destination ?
        EV_INVALIDATE_PARAMETER : EV_INVALIDATE_DIRECTORY;
    int status;

    if (!bytes)
        return -94;
    status = record_event(mock, event);
    if (status == 0 && event == EV_INVALIDATE_PARAMETER &&
        mock->corrupt_parameter_on_invalidate) {
        mock->parameter_destination[0] ^= UINT8_C(1);
    }
    if (status == 0 && event == EV_INVALIDATE_DIRECTORY &&
        mock->corrupt_directory_on_invalidate) {
        mock->directory_destination[0] ^= UINT8_C(1);
    }
    return status;
}

static int fixture_init(Fixture *fixture)
{
    size_t parameter_bytes = (size_t)ZN_NPMV1_PARAMETER_BYTES;
    size_t directory_bytes = (size_t)ZN_NPMV1_DIRECTORY_BYTES;
    size_t scratch_bytes = (size_t)ZN_NPMV1_VIEW_SCRATCH_MIN_BYTES;

    memset(fixture, 0, sizeof(*fixture));
    fixture->parameter_destination = (uint8_t *)malloc(parameter_bytes);
    fixture->directory_destination = (uint8_t *)malloc(directory_bytes);
    fixture->scratch = (uint8_t *)malloc(scratch_bytes);
    if (!fixture->parameter_destination || !fixture->directory_destination ||
        !fixture->scratch)
        return 0;

    memset(fixture->parameter_destination, 0xa5, parameter_bytes);
    memset(fixture->directory_destination, 0x5a, directory_bytes);
    memset(fixture->scratch, 0xc3, scratch_bytes);

    fixture->request.package_sha256 = ZN_NPMV1_PACKAGE_SHA256;
    fixture->request.checkpoint_sha256 = ZN_NPMV1_CHECKPOINT_SHA256;
    fixture->request.graph_sha256 = ZN_NPMV1_GRAPH_SHA256;
    fixture->request.directory_model_crc32 = ZN_NPMV1_DIRECTORY_MODEL_CRC32;
    fixture->request.parameter_image_crc32 = ZN_NPMV1_PARAMETER_IMAGE_CRC32;
    fixture->request.parameter_payload.physical_address = ZN_NPMV1_PARAMETER_ADDRESS;
    fixture->request.parameter_payload.bytes = ZN_NPMV1_PARAMETER_BYTES;
    fixture->request.parameter_payload.data = parameter_file;
    fixture->request.parameter_payload.sha256 = ZN_NPMV1_PARAMETER_SHA256;
    fixture->request.directory.physical_address = ZN_NPMV1_DIRECTORY_ADDRESS;
    fixture->request.directory.bytes = ZN_NPMV1_DIRECTORY_BYTES;
    fixture->request.directory.data = directory_file;
    fixture->request.directory.sha256 = ZN_NPMV1_DIRECTORY_SHA256;
    fixture->request.parameter_reservation.address = ZN_NPMV1_PARAMETER_ADDRESS;
    fixture->request.parameter_reservation.bytes = ZN_NPMV1_PARAMETER_BYTES;
    fixture->request.directory_reservation.address = ZN_NPMV1_DIRECTORY_ADDRESS;
    fixture->request.directory_reservation.bytes = ZN_NPMV1_DIRECTORY_BYTES;
    fixture->request.view_scratch_reservation.address =
        ZN_NPMV1_VIEW_SCRATCH_CANDIDATE_ADDRESS;
    fixture->request.view_scratch_reservation.bytes =
        ZN_NPMV1_VIEW_SCRATCH_MIN_BYTES;
    fixture->request.parameter_mapping.physical_base = ZN_NPMV1_PARAMETER_ADDRESS;
    fixture->request.parameter_mapping.bytes = ZN_NPMV1_PARAMETER_BYTES;
    fixture->request.parameter_mapping.cpu_base = fixture->parameter_destination;
    fixture->request.parameter_mapping.cpu_bytes = parameter_bytes;
    fixture->request.directory_mapping.physical_base = ZN_NPMV1_DIRECTORY_ADDRESS;
    fixture->request.directory_mapping.bytes = ZN_NPMV1_DIRECTORY_BYTES;
    fixture->request.directory_mapping.cpu_base = fixture->directory_destination;
    fixture->request.directory_mapping.cpu_bytes = directory_bytes;
    fixture->request.view_scratch_mapping.physical_base =
        ZN_NPMV1_VIEW_SCRATCH_CANDIDATE_ADDRESS;
    fixture->request.view_scratch_mapping.bytes =
        ZN_NPMV1_VIEW_SCRATCH_MIN_BYTES;
    fixture->request.view_scratch_mapping.cpu_base = fixture->scratch;
    fixture->request.view_scratch_mapping.cpu_bytes = scratch_bytes;

    fixture->mock.parameter_destination = fixture->parameter_destination;
    fixture->mock.directory_destination = fixture->directory_destination;
    fixture->ops.reserve = mock_reserve;
    fixture->ops.copy = mock_copy;
    fixture->ops.cache_clean = mock_cache_clean;
    fixture->ops.barrier = mock_barrier;
    fixture->ops.invalidate_readback = mock_invalidate;
    fixture->state.ready = 1;
    return 1;
}

static void fixture_destroy(Fixture *fixture)
{
    free(fixture->parameter_destination);
    free(fixture->directory_destination);
    free(fixture->scratch);
}

static int prepare(Fixture *fixture)
{
    return zn_native_platform_memory_prepare_v1(
        &fixture->request, &fixture->ops, &fixture->mock, &fixture->state);
}

static int destination_markers_intact(const Fixture *fixture)
{
    size_t parameter_bytes = (size_t)ZN_NPMV1_PARAMETER_BYTES;
    size_t directory_bytes = (size_t)ZN_NPMV1_DIRECTORY_BYTES;
    return fixture->parameter_destination[0] == UINT8_C(0xa5) &&
        fixture->parameter_destination[parameter_bytes / 2u] == UINT8_C(0xa5) &&
        fixture->parameter_destination[parameter_bytes - 1u] == UINT8_C(0xa5) &&
        fixture->directory_destination[0] == UINT8_C(0x5a) &&
        fixture->directory_destination[directory_bytes / 2u] == UINT8_C(0x5a) &&
        fixture->directory_destination[directory_bytes - 1u] == UINT8_C(0x5a);
}

static void expect_preflight_reject(Fixture *fixture, int expected, const char *name)
{
    int result = prepare(fixture);
    check(result == expected, name);
    check(fixture->state.ready == 0, "preflight rejection keeps output unready");
    check(fixture->mock.event_count == 0, "preflight rejection calls no callbacks");
    check(destination_markers_intact(fixture), "preflight rejection copies no bytes");
}

static void test_success_and_order(void)
{
    static const int expected[] = {
        EV_RESERVE_PARAMETER, EV_RESERVE_DIRECTORY, EV_RESERVE_SCRATCH,
        EV_COPY_PARAMETER, EV_COPY_DIRECTORY,
        EV_CLEAN_PARAMETER, EV_CLEAN_DIRECTORY, EV_BARRIER_AFTER_CLEAN,
        EV_INVALIDATE_PARAMETER, EV_INVALIDATE_DIRECTORY,
        EV_BARRIER_AFTER_INVALIDATE
    };
    Fixture fixture;
    int result;

    if (!fixture_init(&fixture)) {
        check(0, "success fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    result = prepare(&fixture);
    check(result == ZN_NPMV1_OK, "successful preparation result");
    check(fixture.state.ready == 1 && fixture.state.stage == ZN_NPMV1_STAGE_READY,
          "success publishes ready after readback");
    check(fixture.mock.event_count == sizeof(expected) / sizeof(expected[0]),
          "success callback count");
    if (fixture.mock.event_count == sizeof(expected) / sizeof(expected[0])) {
        unsigned i;
        for (i = 0; i < fixture.mock.event_count; ++i)
            check(fixture.mock.events[i] == expected[i], "success callback ordering");
    }
    check(memcmp(fixture.parameter_destination, parameter_file,
                 (size_t)ZN_NPMV1_PARAMETER_BYTES) == 0,
          "parameter image copied exactly");
    check(memcmp(fixture.directory_destination, directory_file,
                 (size_t)ZN_NPMV1_DIRECTORY_BYTES) == 0,
          "directory image copied exactly");
    check(fixture.mock.reserve_calls == 3, "all reservations precede copies");
    fixture_destroy(&fixture);
}

static void test_identity_and_metadata_rejections(void)
{
    Fixture fixture;

    if (!fixture_init(&fixture)) {
        check(0, "identity fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.package_sha256 = "wrong";
    expect_preflight_reject(&fixture, ZN_NPMV1_IDENTITY_MISMATCH, "package identity rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "checkpoint fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.checkpoint_sha256 = "wrong";
    expect_preflight_reject(&fixture, ZN_NPMV1_IDENTITY_MISMATCH, "checkpoint identity rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "graph fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.graph_sha256 = "wrong";
    expect_preflight_reject(&fixture, ZN_NPMV1_IDENTITY_MISMATCH, "graph identity rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "CRC fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.parameter_image_crc32 = fixture.request.directory_model_crc32;
    expect_preflight_reject(&fixture, ZN_NPMV1_IDENTITY_MISMATCH,
                            "model CRC cannot replace parameter image CRC");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "length fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    --fixture.request.parameter_payload.bytes;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID, "parameter length pinned");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "directory length fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    --fixture.request.directory.bytes;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID, "directory length pinned");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "address fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    ++fixture.request.directory.physical_address;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID, "directory address pinned");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "sha metadata fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.directory.sha256 = ZN_NPMV1_PARAMETER_SHA256;
    expect_preflight_reject(&fixture, ZN_NPMV1_IDENTITY_MISMATCH,
                            "asset SHA metadata pinned");
    fixture_destroy(&fixture);
}

static void test_ranges_and_overlaps(void)
{
    Fixture fixture;

    if (!fixture_init(&fixture)) {
        check(0, "reservation fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    --fixture.request.parameter_reservation.bytes;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "reservation must contain complete payload range");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "reservation overflow fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.parameter_reservation.address = UINT64_MAX - UINT64_C(63);
    fixture.request.parameter_reservation.bytes = UINT64_C(128);
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "physical reservation overflow rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "physical overlap fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.parameter_reservation.address = UINT64_C(0x1ffff000);
    fixture.request.parameter_reservation.bytes = UINT64_C(0x01002000);
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "overlapping physical reservations rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "scratch overlap fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.view_scratch_reservation.address = ZN_NPMV1_PARAMETER_ADDRESS;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "scratch must be physically disjoint");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "scratch size fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    --fixture.request.view_scratch_reservation.bytes;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "scratch capacity minimum enforced");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "scratch alignment fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    ++fixture.request.view_scratch_reservation.address;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "scratch physical alignment enforced");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "scratch overflow fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.view_scratch_reservation.address = UINT64_MAX - UINT64_C(63);
    fixture.request.view_scratch_reservation.bytes = UINT64_C(128);
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "scratch physical overflow rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "mapping bounds fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    --fixture.request.directory_mapping.bytes;
    --fixture.request.directory_mapping.cpu_bytes;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "mapped CPU span bounds enforced");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "mapping overlap fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.directory_mapping.cpu_base = fixture.parameter_destination;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "mapped destination CPU overlap rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "scratch mapping bounds fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    --fixture.request.view_scratch_mapping.cpu_bytes;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "scratch mapped span covers full reservation");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "scratch CPU overlap fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.view_scratch_mapping.cpu_base = fixture.parameter_destination;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "scratch mapped CPU span is disjoint");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "pointer overflow fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.parameter_mapping.cpu_base =
        (uint8_t *)(uintptr_t)(UINTPTR_MAX - (uintptr_t)7);
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "CPU pointer arithmetic overflow rejected");
    fixture_destroy(&fixture);
}

static void test_source_hash_and_alias_rejections(void)
{
    Fixture fixture;
    uint8_t *changed;

    if (!fixture_init(&fixture)) {
        check(0, "source overflow fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.parameter_payload.data =
        (const uint8_t *)(uintptr_t)(UINTPTR_MAX - (uintptr_t)7);
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "source pointer arithmetic overflow rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "source hash fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    changed = (uint8_t *)malloc((size_t)ZN_NPMV1_PARAMETER_BYTES);
    check(changed != NULL, "changed source allocation");
    if (changed) {
        memcpy(changed, parameter_file, (size_t)ZN_NPMV1_PARAMETER_BYTES);
        changed[0] ^= UINT8_C(1);
        fixture.request.parameter_payload.data = changed;
        expect_preflight_reject(&fixture, ZN_NPMV1_SOURCE_HASH_MISMATCH,
                                "source bytes checked before reservation");
        free(changed);
    }
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "source alias fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.parameter_payload.data = fixture.parameter_destination;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "source and destination alias rejected");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "source source overlap fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.request.directory.data = parameter_file;
    expect_preflight_reject(&fixture, ZN_NPMV1_INVALID,
                            "source image spans must be disjoint");
    fixture_destroy(&fixture);
}

static void test_reservation_failures(void)
{
    Fixture fixture;

    if (!fixture_init(&fixture)) {
        check(0, "busy reservation fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.mock.reserve_status[0] = 1;
    check(prepare(&fixture) == ZN_NPMV1_BUSY, "busy reservation result preserved");
    check(fixture.state.ready == 0 && fixture.state.callback_status == 1,
          "busy reservation leaves output unready");
    check(fixture.mock.event_count == 1 && fixture.mock.reserve_calls == 1,
          "busy reservation stops before later reservations and copies");
    check(destination_markers_intact(&fixture), "busy reservation copies no bytes");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "later busy reservation fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.mock.reserve_status[1] = 1;
    check(prepare(&fixture) == ZN_NPMV1_BUSY,
          "later reservation busy result preserved");
    check(fixture.state.ready == 0 && fixture.state.callback_status == 1,
          "later busy reservation leaves output unready");
    check(fixture.mock.event_count == 2 && fixture.mock.reserve_calls == 2,
          "later busy reservation precedes every copy");
    check(destination_markers_intact(&fixture),
          "later busy reservation leaves both images untouched");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "failed reservation fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.mock.reserve_status[1] = -17;
    check(prepare(&fixture) == ZN_NPMV1_RESERVATION_FAILED,
          "reservation failure returned");
    check(fixture.state.ready == 0 && fixture.state.callback_status == -17,
          "reservation failure preserves callback status and unready output");
    check(fixture.mock.event_count == 2 && fixture.mock.reserve_calls == 2,
          "partial reservation failure precedes every copy");
    check(destination_markers_intact(&fixture), "partial reservation failure copies no bytes");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "scratch busy fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.mock.reserve_status[2] = 1;
    check(prepare(&fixture) == ZN_NPMV1_BUSY, "scratch reservation busy returned");
    check(fixture.mock.event_count == 3 && fixture.mock.reserve_calls == 3,
          "scratch reservation checked before first copy");
    check(destination_markers_intact(&fixture), "scratch busy copies no parameter bytes");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "unexpected reservation result fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.mock.reserve_status[2] = 2;
    check(prepare(&fixture) == ZN_NPMV1_RESERVATION_FAILED,
          "unexpected positive reservation result fails closed");
    check(fixture.state.ready == 0 && fixture.state.callback_status == 2,
          "unexpected reservation result leaves output unready");
    check(destination_markers_intact(&fixture),
          "unexpected reservation result occurs before copies");
    fixture_destroy(&fixture);
}

static void test_copy_and_cache_failures(void)
{
    static const struct {
        int event;
        uint8_t stage;
    } cache_failures[] = {
        { EV_CLEAN_PARAMETER, ZN_NPMV1_STAGE_CLEAN_PARAMETER },
        { EV_CLEAN_DIRECTORY, ZN_NPMV1_STAGE_CLEAN_DIRECTORY },
        { EV_BARRIER_AFTER_CLEAN, ZN_NPMV1_STAGE_BARRIER_AFTER_CLEAN },
        { EV_INVALIDATE_PARAMETER, ZN_NPMV1_STAGE_INVALIDATE_PARAMETER },
        { EV_INVALIDATE_DIRECTORY, ZN_NPMV1_STAGE_INVALIDATE_DIRECTORY },
        { EV_BARRIER_AFTER_INVALIDATE, ZN_NPMV1_STAGE_BARRIER_AFTER_INVALIDATE }
    };
    Fixture fixture;
    unsigned i;

    if (!fixture_init(&fixture)) {
        check(0, "copy failure fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.mock.fail_event = EV_COPY_DIRECTORY;
    fixture.mock.fail_status = -23;
    fixture.mock.partial_copy_event = EV_COPY_DIRECTORY;
    check(prepare(&fixture) == ZN_NPMV1_COPY_FAILED, "copy failure returned");
    check(fixture.state.ready == 0 && fixture.state.callback_status == -23,
          "copy failure leaves output unready");
    {
        size_t tail_index;
        int tail_untouched = 1;
        size_t half = (size_t)ZN_NPMV1_DIRECTORY_BYTES / 2u;
        for (tail_index = half; tail_index < (size_t)ZN_NPMV1_DIRECTORY_BYTES;
             ++tail_index)
            if (fixture.directory_destination[tail_index] != UINT8_C(0x5a))
                tail_untouched = 0;
        check(memcmp(fixture.directory_destination, directory_file, half) == 0 &&
              tail_untouched, "partial copy may leave destination bytes changed");
    }
    check(fixture.mock.event_count != 0 &&
          fixture.mock.events[fixture.mock.event_count - 1u] == EV_COPY_DIRECTORY,
          "copy failure stops before cache maintenance");
    fixture_destroy(&fixture);

    for (i = 0; i < sizeof(cache_failures) / sizeof(cache_failures[0]); ++i) {
        char name[64];
        if (!fixture_init(&fixture)) {
            check(0, "cache failure fixture allocation");
            fixture_destroy(&fixture);
            return;
        }
        fixture.mock.fail_event = cache_failures[i].event;
        fixture.mock.fail_status = -31;
        check(prepare(&fixture) == ZN_NPMV1_CACHE_FAILED,
              "cache callback failure returned");
        check(fixture.state.ready == 0 && fixture.state.callback_status == -31,
              "cache callback failure leaves output unready");
        (void)snprintf(name, sizeof(name), "cache failure stage %u", i);
        check(fixture.state.stage == cache_failures[i].stage, name);
        check(fixture.mock.event_count != 0 &&
              fixture.mock.events[fixture.mock.event_count - 1u] ==
              cache_failures[i].event, "cache failure stops at failed callback");
        fixture_destroy(&fixture);
    }
}

static void test_readback_corruption(void)
{
    Fixture fixture;

    if (!fixture_init(&fixture)) {
        check(0, "readback corruption fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.mock.corrupt_parameter_on_invalidate = 1;
    check(prepare(&fixture) == ZN_NPMV1_READBACK_HASH_MISMATCH,
          "readback corruption rejected");
    check(fixture.state.ready == 0 &&
          fixture.state.stage == ZN_NPMV1_STAGE_READBACK_HASH,
          "readback failure remains unready");
    check(fixture.mock.event_count != 0 &&
          fixture.mock.events[fixture.mock.event_count - 1u] ==
          EV_BARRIER_AFTER_INVALIDATE,
          "readback hash follows invalidate and final barrier");
    fixture_destroy(&fixture);

    if (!fixture_init(&fixture)) {
        check(0, "directory readback corruption fixture allocation");
        fixture_destroy(&fixture);
        return;
    }
    fixture.mock.corrupt_directory_on_invalidate = 1;
    check(prepare(&fixture) == ZN_NPMV1_READBACK_HASH_MISMATCH,
          "directory readback corruption rejected");
    check(fixture.state.ready == 0 &&
          fixture.state.stage == ZN_NPMV1_STAGE_READBACK_HASH,
          "directory readback failure remains unready");
    fixture_destroy(&fixture);
}

int main(int argc, char **argv)
{
    uint8_t *parameter_data;
    uint8_t *directory_data;

    if (argc != 3) {
        fprintf(stderr, "usage: %s native_parameters.bin native_directory.bin\n", argv[0]);
        return 2;
    }
    parameter_data = read_asset(argv[1], (size_t)ZN_NPMV1_PARAMETER_BYTES);
    directory_data = read_asset(argv[2], (size_t)ZN_NPMV1_DIRECTORY_BYTES);
    if (!parameter_data || !directory_data) {
        fprintf(stderr, "could not read exact pinned host fixture assets\n");
        free(parameter_data);
        free(directory_data);
        return 2;
    }
    parameter_file = parameter_data;
    directory_file = directory_data;

    test_success_and_order();
    test_identity_and_metadata_rejections();
    test_ranges_and_overlaps();
    test_source_hash_and_alias_rejections();
    test_reservation_failures();
    test_copy_and_cache_failures();
    test_readback_corruption();

    free(parameter_data);
    free(directory_data);
    if (failures) {
        fprintf(stderr, "NATIVE_PLATFORM_MEMORY_V1_FAIL failures=%u checks=%u\n",
                failures, checks);
        return 1;
    }
    printf("NATIVE_PLATFORM_MEMORY_V1_PASS checks=%u host_mocks_only=1 board_access=0\n",
           checks);
    return 0;
}
