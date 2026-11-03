#include "native_arena_owner_v1.h"
#include "graph_plan.h"

#include <stdio.h>
#include <string.h>

static const ZnNativeArenaRegionV1 test_regions[ZN_NATIVE_ARENA_SLOT_COUNT_V1] = {
    { UINT32_C(268435456), UINT32_C(1638400) },
    { UINT32_C(270073856), UINT32_C(1638400) },
    { UINT32_C(271712256), UINT32_C(819200) },
    { UINT32_C(272531456), UINT32_C(409600) },
    { UINT32_C(272941056), UINT32_C(409600) },
    { UINT32_C(273350656), UINT32_C(122880) },
    { UINT32_C(273473536), UINT32_C(163840) }
};

typedef struct Counts {
    unsigned int operations[7];
    unsigned int requests;
    unsigned int run_started;
    unsigned int publications;
    unsigned int quiescence;
    unsigned int duplicate_ack_rejections;
    unsigned int quiescence_gate_checks;
    unsigned int retirements;
    unsigned int stale_request_rejections;
    unsigned int stale_ref_rejections;
    unsigned int alias_rejections;
    unsigned int generation_rejections;
    unsigned int order_rejections;
    unsigned int failure_retention;
} Counts;

static unsigned int failures;

static void
check(int condition, const char *name)
{
    if (!condition) {
        if (failures < 40)
            fprintf(stderr, "FAIL %s\n", name);
        ++failures;
    }
}

static ZnNativeArenaConfigV1
make_config(void)
{
    ZnNativeArenaConfigV1 config;
    memset(&config, 0, sizeof config);
    config.arena_base = UINT32_C(268435456);
    config.arena_end = UINT32_C(273637376);
    config.arena_bytes = UINT32_C(5201920);
    config.alignment = 4096;
    memcpy(config.slots, test_regions, sizeof test_regions);
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

static int
init_case(ZnNativeArenaOwnerV1 *owner, ZnNativeArenaConfigV1 *config,
          ZnDispatch *dispatch, uint32_t epoch)
{
    if (zn_dispatch_init(dispatch, z100_graph_events,
                         ZN_NATIVE_ARENA_EVENT_COUNT_V1, epoch) != 0)
        return -1;
    return zn_native_arena_owner_init_v1(owner, config, dispatch, epoch) ==
           ZN_NATIVE_ARENA_OWNER_V1_ACKED ? 0 : -1;
}

static ZnNativeArenaCompletionEvidenceV1
completion_for(const ZnRequest *request)
{
    ZnNativeArenaCompletionEvidenceV1 evidence;
    memset(&evidence, 0, sizeof evidence);
    evidence.epoch = request->epoch;
    evidence.run_tag = request->tag;
    evidence.event_index = request->event_index;
    evidence.result_identity_verified = 1;
    evidence.driver_terminal_success = 1;
    if (request->job->has_destination) {
        evidence.destination_ref = request->job->destination.ref;
        evidence.destination_bytes = request->job->destination.bytes;
        evidence.output_cache_visible = 1;
    }
    return evidence;
}

static ZnNativeArenaQuiescenceEvidenceV1
quiescence_for(const ZnRequest *run_request)
{
    ZnNativeArenaQuiescenceEvidenceV1 evidence;
    memset(&evidence, 0, sizeof evidence);
    evidence.epoch = run_request->epoch;
    evidence.run_tag = run_request->tag;
    evidence.event_index = run_request->event_index;
    evidence.all_read_io_quiet = 1;
    evidence.all_write_io_quiet = 1;
    evidence.driver_terminal = 1;
    return evidence;
}

static void
test_full_graph_lifecycle(Counts *counts)
{
    ZnNativeArenaOwnerV1 owner = { 0 };
    ZnNativeArenaConfigV1 config = make_config();
    ZnDispatch dispatch;
    ZnRequest request;
    ZnRequest saved_retire;
    uint32_t saved_retire_generation_high = 0;
    int saved_retire_valid = 0;
    int saved_retire_checked = 0;
    int next;
    unsigned int iterations = 0;

    check(init_case(&owner, &config, &dispatch, 200) == 0,
          "owner binds exact frozen plan and arena at epoch 200");
    check(owner.slots[0].state == ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 &&
          owner.slots[0].ref.generation == 1 && owner.slots[0].ref.tensor == -1 &&
          owner.slots[0].ref.slot == 0,
          "input tensor is seeded as published slot0 generation1");

    while ((next = zn_dispatch_next(&dispatch, &request)) == 1 &&
           iterations++ < 600u) {
        ZnNativeArenaOwnerCodeV1 code;
        ++counts->requests;
        if (request.operation <= ZN_RETIRE)
            ++counts->operations[request.operation];

        if (request.operation == ZN_RUN) {
            ZnNativeArenaCompletionEvidenceV1 completion;
            ZnNativeArenaEventStateV1 *event_state =
                &owner.event_state[request.event_index];
            uint8_t index;

            code = zn_native_arena_owner_step_v1(&owner, &dispatch, &request);
            if (code != ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND)
                fprintf(stderr, "RUN_GATE event=%u operation=%u code=%d fault=%u phase=%u index=%u acquired=%02x allocated=%u\n",
                        request.event_index, request.operation, (int)code,
                        owner.fault, dispatch.phase, dispatch.index,
                        event_state->acquired_mask, event_state->allocated);
            check(code == ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND &&
                  dispatch.pending,
                  "RUN is not acknowledged before an explicit backend start");
            if (code != ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND)
                return;
            code = zn_native_arena_owner_run_started_v1(&owner, &dispatch,
                                                        &request);
            if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
                fprintf(stderr, "RUN_START event=%u code=%d\n",
                        request.event_index, (int)code);
            check(code == ZN_NATIVE_ARENA_OWNER_V1_ACKED,
                  "backend start requires all exact source leases");
            if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
                return;
            ++counts->run_started;
            code = zn_native_arena_owner_step_v1(&owner, &dispatch, &request);
            check(code == ZN_NATIVE_ARENA_OWNER_V1_BUSY && dispatch.pending &&
                  !event_state->run_completed && !event_state->output_published &&
                  (!request.job->has_destination ||
                   owner.slots[request.job->destination.ref.slot].state ==
                       ZN_NATIVE_ARENA_SLOT_RESERVED_V1),
                  "RUN submission alone neither completes nor publishes output");
            for (index = 0; index < request.job->read_count; ++index) {
                ZnNativeArenaSlotV1 *slot =
                    &owner.slots[request.job->reads[index].slot];
                check(slot->io_count != 0 && slot->reader_count != 0,
                      "RUN start holds each source lease and IO reference");
            }

            completion = completion_for(&request);
            if (request.job->has_destination) {
                ZnNativeArenaSlotV1 *destination =
                    &owner.slots[request.job->destination.ref.slot];
                check(destination->state == ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
                      destination->io_count != 0,
                      "destination remains reserved during submitted compute");
                code = zn_native_arena_owner_publish_v1(&owner, &dispatch,
                                                        &request, &completion);
                if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
                    fprintf(stderr, "PUBLISH event=%u code=%d started=%u dest_state=%u dest_gen=%u evidence_gen=%u tags=%u/%u bytes=%u/%u\n",
                            request.event_index, (int)code,
                            event_state->run_started, destination->state,
                            destination->ref.generation,
                            completion.destination_ref.generation,
                            event_state->run_tag, completion.run_tag,
                            destination->bytes, completion.destination_bytes);
                check(code == ZN_NATIVE_ARENA_OWNER_V1_ACKED,
                      "verified result and visible output explicitly publish destination");
                if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
                    return;
                check(destination->state == ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 &&
                      dispatch.pending && !event_state->run_acked,
                      "publication occurs before RUN ACK and before DRAIN");
                ++counts->publications;
            } else {
                code = zn_native_arena_owner_complete_without_output_v1(
                          &owner, &dispatch, &request, &completion);
                check(code == ZN_NATIVE_ARENA_OWNER_V1_ACKED,
                      "destinationless final work completes without fake slot publication");
                if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
                    return;
            }
            code = zn_native_arena_owner_step_v1(&owner, &dispatch, &request);
            if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED)
                fprintf(stderr, "RUN_ACK event=%u code=%d fault=%u pending=%u completed=%u published=%u runacked=%u\n",
                        request.event_index, (int)code, owner.fault,
                        dispatch.pending, event_state->run_completed,
                        event_state->output_published, event_state->run_acked);
            check(code == ZN_NATIVE_ARENA_OWNER_V1_ACKED && !dispatch.pending,
                  "RUN ACK follows explicit completion and publication");
            if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED || dispatch.pending)
                return;
            check(zn_native_arena_owner_step_v1(&owner, &dispatch, &request) ==
                      ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST,
                  "duplicate RUN ACK request is rejected");
            ++counts->duplicate_ack_rejections;
            continue;
        }

        if (request.operation == ZN_DRAIN) {
            ZnNativeArenaQuiescenceEvidenceV1 evidence;
            uint8_t index;

            code = zn_native_arena_owner_step_v1(&owner, &dispatch, &request);
            check(code == ZN_NATIVE_ARENA_OWNER_V1_BUSY && dispatch.pending,
                  "DRAIN waits for independent physical-quiescence notification");
            ++counts->quiescence_gate_checks;
            if (request.event_index == 3) {
                const ZnNativeArenaSlotV1 *source = &owner.slots[1];
                const ZnNativeArenaSlotV1 *destination = &owner.slots[0];
                const ZnNativeArenaEventStateV1 *event_state =
                    &owner.event_state[request.event_index];
                check(request.job->event == 9 && request.job->read_count == 1 &&
                      request.job->reads[0].tensor == 5 &&
                      request.job->reads[0].slot == 1 &&
                      request.job->reads[0].generation == 4 &&
                      request.job->has_destination &&
                      request.job->destination.ref.tensor == 9 &&
                      request.job->destination.ref.slot == 0 &&
                      request.job->destination.ref.generation == 5 &&
                      source->state == ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 &&
                      source->reader_count == 1 && source->io_count == 1 &&
                      destination->state == ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 &&
                      destination->io_count == 1 && event_state->run_acked &&
                      event_state->run_completed && !event_state->io_quiescent,
                      "event9 DRAIN waits while its published output remains IO-owned");
            }
            evidence = quiescence_for(
                &(ZnRequest){ .epoch = owner.epoch,
                              .tag = owner.event_state[request.event_index].run_tag,
                              .event_index = request.event_index,
                              .operation = ZN_RUN,
                              .job = request.job });
            evidence.driver_terminal = 0;
            check(zn_native_arena_owner_notify_quiescent_v1(
                      &owner, &dispatch, &request, &evidence) ==
                      ZN_NATIVE_ARENA_OWNER_V1_INVALID && dispatch.pending,
                  "failed quiescence evidence cannot decrement IO ownership");
            evidence.driver_terminal = 1;
            check(zn_native_arena_owner_notify_quiescent_v1(
                      &owner, &dispatch, &request, &evidence) ==
                      ZN_NATIVE_ARENA_OWNER_V1_ACKED,
                  "successful physical-quiescence evidence clears IO counts");
            ++counts->quiescence;
            for (index = 0; index < request.job->read_count; ++index)
                check(owner.slots[request.job->reads[index].slot].io_count == 0,
                      "quiescence clears physical read IO only");
            if (request.job->has_destination)
                check(owner.slots[request.job->destination.ref.slot].io_count == 0,
                      "quiescence clears physical write IO");
            check(zn_native_arena_owner_step_v1(&owner, &dispatch, &request) ==
                      ZN_NATIVE_ARENA_OWNER_V1_ACKED && !dispatch.pending,
                  "DRAIN ACK follows completion and quiescence");
            if (dispatch.pending)
                return;
            continue;
        }

        if (request.operation == ZN_RETIRE && !saved_retire_valid) {
            saved_retire = request;
            saved_retire_generation_high =
                owner.slots[request.ref.slot].generation_high_water;
            saved_retire_valid = 1;
        }
        code = zn_native_arena_owner_step_v1(&owner, &dispatch, &request);
        check(code == ZN_NATIVE_ARENA_OWNER_V1_ACKED && !dispatch.pending,
              "graph slot transition ACKs exact pending operation");
        if (code != ZN_NATIVE_ARENA_OWNER_V1_ACKED || dispatch.pending)
            return;
        if (request.operation == ZN_RETURN && request.event_index == 3) {
            const ZnNativeArenaSlotV1 *source = &owner.slots[1];
            check(request.job->event == 9 && request.ref.tensor == 5 &&
                  request.ref.slot == 1 && request.ref.generation == 4 &&
                  request.job->retire_count == 0 &&
                  owner.event_state[3].retired_mask == 0 &&
                  source->state == ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 &&
                  source->ref.tensor == 5 && source->ref.slot == 1 &&
                  source->ref.generation == 4 && source->reader_count == 0 &&
                  source->io_count == 0,
                  "event9 RETURN drops its reader but keeps tensor5 generation4 published");
        }
        if (request.operation == ZN_RETIRE && !saved_retire_checked) {
            check(zn_native_arena_owner_step_v1(&owner, &dispatch, &saved_retire) ==
                      ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST &&
                  owner.slots[saved_retire.ref.slot].state ==
                      ZN_NATIVE_ARENA_SLOT_EMPTY_V1 &&
                  owner.slots[saved_retire.ref.slot].generation_high_water ==
                      saved_retire_generation_high,
                  "duplicate RETIRE is rejected and generation high-water is preserved");
            ++counts->duplicate_ack_rejections;
            saved_retire_checked = 1;
        }
        if (request.operation == ZN_RETIRE)
            ++counts->retirements;
    }

    check(iterations <= 600u && next == 0 && dispatch.done && !dispatch.fault,
          "all frozen plan requests reach normal dispatcher completion");
    check(counts->requests == 493 && counts->operations[ZN_ALLOCATE] == 72 &&
          counts->operations[ZN_ACQUIRE] == 101 && counts->operations[ZN_RUN] == 73 &&
          counts->operations[ZN_DRAIN] == 73 && counts->operations[ZN_RETURN] == 101 &&
          counts->operations[ZN_RETIRE] == 73,
          "all 493 frozen graph requests are observed with exact operation totals");
    check(counts->run_started == 73 && counts->publications == 72 &&
          counts->quiescence == 73 && counts->retirements == 73,
          "separate backend completion, publication, quiescence and retirement counts");
    check(owner.event_state[3].run_completed && owner.event_state[3].drained &&
          owner.event_state[3].retired_mask == 0 &&
          owner.slots[1].generation_high_water >= 2,
          "event9 keeps its output live without a retire request");
    check(saved_retire_valid && saved_retire_checked &&
          counts->duplicate_ack_rejections >= 3,
          "duplicate allocation/run/retire request attempts were rejected");
    check(zn_native_arena_owner_verify_complete_v1(&owner, &dispatch) ==
              ZN_NATIVE_ARENA_OWNER_V1_ACKED && owner.complete,
          "complete frame has no live slots, readers, or IO counts");
}

static void
test_configuration_and_foreign_request_rejection(Counts *counts)
{
    ZnNativeArenaConfigV1 config = make_config();
    ZnNativeArenaOwnerV1 owner = { 0 };
    ZnDispatch dispatch;
    ZnRequest request;
    ZnRequest stale;

    check(zn_dispatch_init(&dispatch, z100_graph_events,
                           ZN_NATIVE_ARENA_EVENT_COUNT_V1, 300) == 0,
          "initialize overlap config dispatcher");
    config.slots[1].address = config.slots[0].address;
    check(zn_native_arena_owner_init_v1(&owner, &config, &dispatch, 300) ==
              ZN_NATIVE_ARENA_OWNER_V1_INVALID && !owner.initialized,
          "overlapping slot regions are rejected at initialization");

    config = make_config();
    config.graph_sha256[0] ^= 1;
    memset(&owner, 0, sizeof owner);
    check(zn_native_arena_owner_init_v1(&owner, &config, &dispatch, 300) ==
              ZN_NATIVE_ARENA_OWNER_V1_INVALID && !owner.initialized,
          "wrong frozen graph identity is rejected");

    config = make_config();
    {
        ZnEvent changed[ZN_NATIVE_ARENA_EVENT_COUNT_V1];
        ZnDispatch changed_dispatch;
        ZnNativeArenaOwnerV1 changed_owner = { 0 };
        memcpy(changed, z100_graph_events, sizeof changed);
        ++changed[0].destination.address;
        check(zn_dispatch_init(&changed_dispatch, changed,
                               ZN_NATIVE_ARENA_EVENT_COUNT_V1, 301) == 0 &&
              zn_native_arena_owner_init_v1(&changed_owner, &config,
                                             &changed_dispatch, 301) ==
                  ZN_NATIVE_ARENA_OWNER_V1_INVALID && !changed_owner.initialized,
              "altered plan cannot bind under the frozen plan identity");
    }

    memset(&owner, 0, sizeof owner);
    check(init_case(&owner, &config, &dispatch, 302) == 0 &&
          zn_dispatch_next(&dispatch, &request) == 1 &&
          request.operation == ZN_ALLOCATE,
          "prepare exact pending allocation for stale request checks");
    stale = request;
    ++stale.epoch;
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &stale) ==
              ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST && dispatch.pending &&
          !dispatch.fault && owner.slots[1].state == ZN_NATIVE_ARENA_SLOT_EMPTY_V1,
          "foreign epoch does not advance dispatcher or arena metadata");
    ++counts->stale_request_rejections;
    stale = request;
    ++stale.ref.generation;
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &stale) ==
              ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST && dispatch.pending &&
          owner.slots[1].state == ZN_NATIVE_ARENA_SLOT_EMPTY_V1,
          "foreign pending reference does not reserve its slot");
    ++counts->stale_ref_rejections;

    dispatch.request = stale;
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &stale) ==
              ZN_NATIVE_ARENA_OWNER_V1_INVALID && dispatch.pending &&
          owner.slots[1].state == ZN_NATIVE_ARENA_SLOT_EMPTY_V1 &&
          owner.slots[1].generation_high_water == 0,
          "matching but wrong destination generation is rejected without reservation");
    ++counts->generation_rejections;
    stale = request;
    stale.ref.generation = 1;
    stale.ref.tensor = -1;
    stale.ref.slot = 0;
    dispatch.request = stale;
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &stale) ==
              ZN_NATIVE_ARENA_OWNER_V1_INVALID &&
          owner.slots[0].state == ZN_NATIVE_ARENA_SLOT_PUBLISHED_V1 &&
          owner.slots[0].ref.generation == 1 && owner.slots[0].ref.tensor == -1 &&
          owner.slots[0].ref.slot == 0 && owner.slots[1].state ==
              ZN_NATIVE_ARENA_SLOT_EMPTY_V1 &&
          owner.slots[1].generation_high_water == 0,
          "allocation alias cannot claim the already-published input slot");
    ++counts->alias_rejections;
    dispatch.request = request;
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_ACKED,
          "valid allocation succeeds after rejected foreign generation");
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_STALE_REQUEST &&
          owner.slots[1].generation_high_water == 2 &&
          owner.slots[1].state == ZN_NATIVE_ARENA_SLOT_RESERVED_V1,
          "duplicate ALLOCATE ACK cannot alter generation or slot state");
}

static void
test_acquire_generation_and_failure_retention(Counts *counts)
{
    ZnNativeArenaConfigV1 config = make_config();
    ZnNativeArenaOwnerV1 owner = { 0 };
    ZnDispatch dispatch;
    ZnRequest request;
    ZnRequest changed;
    ZnNativeArenaSlotV1 source_before;
    ZnNativeArenaSlotV1 destination_before;

    check(init_case(&owner, &config, &dispatch, 400) == 0 &&
          zn_dispatch_next(&dispatch, &request) == 1 &&
          zn_native_arena_owner_step_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_ACKED,
          "prepare seeded source and reserved destination");
    check(zn_dispatch_next(&dispatch, &request) == 1 &&
          request.operation == ZN_ACQUIRE,
          "dispatcher exposes first source acquire");
    changed = request;
    ++changed.ref.generation;
    dispatch.request = changed;
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &changed) ==
              ZN_NATIVE_ARENA_OWNER_V1_INVALID &&
          owner.slots[0].reader_count == 0 && dispatch.pending,
          "wrong acquire generation does not create a reader lease");
    ++counts->generation_rejections;
    dispatch.request = request;
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_ACKED &&
          owner.slots[0].reader_count == 1,
          "correct exact source generation can then be acquired");

    check(zn_dispatch_next(&dispatch, &request) == 1 && request.operation == ZN_RUN &&
          zn_native_arena_owner_step_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_NEEDS_BACKEND &&
          zn_native_arena_owner_run_started_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_ACKED,
          "failure case starts backend while retaining source and destination");
    check(zn_native_arena_owner_run_started_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_ORDER &&
          owner.slots[0].reader_count == 1 && owner.slots[0].io_count == 1 &&
          owner.slots[1].io_count == 1,
          "duplicate RUN start is rejected without double-counting IO");
    ++counts->order_rejections;
    source_before = owner.slots[0];
    destination_before = owner.slots[1];
    check(source_before.reader_count == 1 && source_before.io_count == 1 &&
          destination_before.state == ZN_NATIVE_ARENA_SLOT_RESERVED_V1 &&
          destination_before.io_count == 1,
          "running failure fixture owns both leases and in-flight IO counts");
    check(zn_native_arena_owner_fail_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_FAILED && dispatch.fault && dispatch.pending,
          "backend failure latches graph fault without ACK or release");
    check(owner.fault && owner.slots[0].reader_count == source_before.reader_count &&
          owner.slots[0].io_count == source_before.io_count &&
          owner.slots[1].state == destination_before.state &&
          owner.slots[1].io_count == destination_before.io_count &&
          owner.slots[1].generation_high_water ==
              destination_before.generation_high_water,
          "failure retains source lease, IO, reservation, and generation high-water");
    check(zn_native_arena_owner_step_v1(&owner, &dispatch, &request) ==
              ZN_NATIVE_ARENA_OWNER_V1_POISONED &&
          zn_native_arena_owner_verify_complete_v1(&owner, &dispatch) ==
              ZN_NATIVE_ARENA_OWNER_V1_POISONED,
          "poisoned owner cannot progress or claim completion");
    ++counts->failure_retention;
}

int
main(void)
{
    Counts counts;
    memset(&counts, 0, sizeof counts);
    test_full_graph_lifecycle(&counts);
    test_configuration_and_foreign_request_rejection(&counts);
    test_acquire_generation_and_failure_retention(&counts);
    if (failures != 0) {
        fprintf(stderr, "NATIVE_ARENA_OWNER_V1_HOST_FAIL count=%u\n", failures);
        return 1;
    }
    printf("NATIVE_ARENA_OWNER_V1_HOST_PASS requests=%u allocate=%u acquire=%u run=%u drain=%u return=%u retire=%u run_started=%u published=%u quiescent=%u duplicate_rejections=%u quiescence_gates=%u stale_requests=%u stale_refs=%u alias_rejections=%u generation_rejections=%u order_rejections=%u failure_retention=%u synthetic_backend=1 hardware_ledger_claim=0 physical_ddr_claim=0\n",
           counts.requests, counts.operations[ZN_ALLOCATE],
           counts.operations[ZN_ACQUIRE], counts.operations[ZN_RUN],
           counts.operations[ZN_DRAIN], counts.operations[ZN_RETURN],
           counts.operations[ZN_RETIRE], counts.run_started,
           counts.publications, counts.quiescence,
           counts.duplicate_ack_rejections, counts.quiescence_gate_checks,
           counts.stale_request_rejections, counts.stale_ref_rejections,
           counts.alias_rejections, counts.generation_rejections,
           counts.order_rejections,
           counts.failure_retention);
    return 0;
}
