#ifndef ACP_DIRTY_SMOKE_DIAG_V1_H
#define ACP_DIRTY_SMOKE_DIAG_V1_H

#include <stddef.h>
#include <stdint.h>

enum {
    ZN_ACP_DIRTY_DIAG_CASES = 6u,
    ZN_ACP_DIRTY_DIAG_VERSION = 1u,
    ZN_ACP_DIRTY_DIAG_STAGE_IDLE = 0u,
    ZN_ACP_DIRTY_DIAG_STAGE_PREFLIGHT = 1u,
    ZN_ACP_DIRTY_DIAG_STAGE_BUFFER_INIT = 2u,
    ZN_ACP_DIRTY_DIAG_STAGE_CACHE_PREPARED = 3u,
    ZN_ACP_DIRTY_DIAG_STAGE_SUBMITTED = 4u,
    ZN_ACP_DIRTY_DIAG_STAGE_TERMINAL = 5u,
    ZN_ACP_DIRTY_DIAG_STAGE_RESULT_CHECKED = 6u,
    ZN_ACP_DIRTY_DIAG_STAGE_ACKED = 7u,
    ZN_ACP_DIRTY_DIAG_STAGE_SCRATCH_CHECKED = 8u,
    ZN_ACP_DIRTY_DIAG_STAGE_FULL_OUTPUT_CHECKED = 9u,
    ZN_ACP_DIRTY_DIAG_STAGE_GUARDS_CHECKED = 10u,
    ZN_ACP_DIRTY_DIAG_STAGE_COMPLETE = 11u,
    ZN_ACP_DIRTY_DIAG_STAGE_FAILED = 255u,
    ZN_ACP_DIRTY_DIAG_RESULT_NOT_RUN = 0u,
    ZN_ACP_DIRTY_DIAG_RESULT_RUNNING = 1u,
    ZN_ACP_DIRTY_DIAG_RESULT_PASS = 2u,
    ZN_ACP_DIRTY_DIAG_FAIL_POLICY = 16u,
    ZN_ACP_DIRTY_DIAG_FAIL_PLATFORM = 17u,
    ZN_ACP_DIRTY_DIAG_FAIL_COMMAND = 18u,
    ZN_ACP_DIRTY_DIAG_FAIL_INITIAL_GUARD = 19u,
    ZN_ACP_DIRTY_DIAG_FAIL_CACHE_PREP = 20u,
    ZN_ACP_DIRTY_DIAG_FAIL_SUBMIT = 21u,
    ZN_ACP_DIRTY_DIAG_FAIL_TERMINAL = 22u,
    ZN_ACP_DIRTY_DIAG_FAIL_TIMEOUT = 23u,
    ZN_ACP_DIRTY_DIAG_FAIL_METADATA = 24u,
    ZN_ACP_DIRTY_DIAG_FAIL_IMMEDIATE = 25u,
    ZN_ACP_DIRTY_DIAG_FAIL_ACK = 26u,
    ZN_ACP_DIRTY_DIAG_FAIL_OWNERSHIP = 27u,
    ZN_ACP_DIRTY_DIAG_FAIL_FULL_OUTPUT = 28u,
    ZN_ACP_DIRTY_DIAG_FAIL_GUARD = 29u,
    ZN_ACP_DIRTY_DIAG_FAIL_DIAGNOSTIC = 30u,
    ZN_ACP_DIRTY_DIAG_OVERALL_NOT_RUN = 0u,
    ZN_ACP_DIRTY_DIAG_OVERALL_RUNNING = 1u,
    ZN_ACP_DIRTY_DIAG_OVERALL_PASS = 2u,
    ZN_ACP_DIRTY_DIAG_OVERALL_FAIL = 3u
};

#define ZN_ACP_DIRTY_DIAG_MAGIC UINT32_C(0x41435037)
#define ZN_ACP_DIRTY_DIAG_NONE UINT32_MAX
#define ZN_ACP_DIRTY_DIAG_STAGE_RESULT(stage, result) \
    (((uint32_t)(stage) & UINT32_C(0xff)) | \
     (((uint32_t)(result) & UINT32_C(0xff)) << 8))
#define ZN_ACP_DIRTY_DIAG_STAGE_OF(value) ((uint32_t)(value) & UINT32_C(0xff))
#define ZN_ACP_DIRTY_DIAG_RESULT_OF(value) (((uint32_t)(value) >> 8) & UINT32_C(0xff))

#define ZN_ACP_DIRTY_DIAG_OWN_TERMINAL_SAMPLED UINT32_C(0x01)
#define ZN_ACP_DIRTY_DIAG_OWN_TERMINAL_HELD UINT32_C(0x02)
#define ZN_ACP_DIRTY_DIAG_OWN_POST_ACK_SAMPLED UINT32_C(0x04)
#define ZN_ACP_DIRTY_DIAG_OWN_POST_ACK_HELD UINT32_C(0x08)
#define ZN_ACP_DIRTY_DIAG_SOFTWARE_TIMEOUT UINT32_C(0x10)

#define ZN_ACP_DIRTY_DIAG_DRAIN_SAMPLED UINT32_C(0x01)
#define ZN_ACP_DIRTY_DIAG_NEEDS_DRAIN UINT32_C(0x02)
#define ZN_ACP_DIRTY_DIAG_DRAIN_COMPLETE UINT32_C(0x04)

#define ZN_ACP_DIRTY_DIAG_GUARD_INITIAL_BEFORE UINT32_C(0x01)
#define ZN_ACP_DIRTY_DIAG_GUARD_INITIAL_AFTER UINT32_C(0x02)
#define ZN_ACP_DIRTY_DIAG_GUARD_PREP_CHECKED UINT32_C(0x04)
#define ZN_ACP_DIRTY_DIAG_GUARD_FINAL_BEFORE UINT32_C(0x08)
#define ZN_ACP_DIRTY_DIAG_GUARD_FINAL_AFTER UINT32_C(0x10)

#define ZN_ACP_DIRTY_DIAG_CHECKED UINT32_C(0x01)
#define ZN_ACP_DIRTY_DIAG_PASSED UINT32_C(0x02)

typedef struct ZnAcpDirtySmokeCaseDiagnostic {
    uint32_t stage_result;
    uint32_t driver_code;
    uint32_t status;
    uint32_t bridge_error;
    uint32_t backend_fault_code;
    uint32_t request_cookie;
    uint32_t result_epoch;
    uint32_t event;
    uint32_t committed_tiles;
    uint32_t ownership_flags;
    uint32_t drain_flags;
    uint32_t bad_offset;
    uint32_t guard_flags;
    uint32_t immediate_flags;
    uint32_t full_output_flags;
    uint32_t ack_code;
} ZnAcpDirtySmokeCaseDiagnostic;

typedef struct ZnAcpDirtySmokeDiagnostic {
    uint32_t magic;
    uint32_t version;
    uint32_t bytes;
    uint32_t epoch;
    uint32_t attempted_mask;
    uint32_t completed_mask;
    uint32_t overall_result;
    uint32_t failure_case;
    uint32_t source_base;
    uint32_t destination_base;
    uint32_t scratch_base;
    uint32_t source_bytes;
    uint32_t destination_bytes;
    uint32_t scratch_bytes;
    uint32_t case_count;
    uint32_t failure_result;
    ZnAcpDirtySmokeCaseDiagnostic cases[ZN_ACP_DIRTY_DIAG_CASES];
} ZnAcpDirtySmokeDiagnostic;

_Static_assert(sizeof(ZnAcpDirtySmokeCaseDiagnostic) == 64u,
               "each case record occupies one 64-byte cache line");
_Static_assert(offsetof(ZnAcpDirtySmokeDiagnostic, cases) == 64u,
               "diagnostic header occupies one cache line");
_Static_assert(sizeof(ZnAcpDirtySmokeDiagnostic) == 448u,
               "diagnostic layout is stable and cache-line sized");
_Static_assert((sizeof(ZnAcpDirtySmokeDiagnostic) % 64u) == 0u,
               "diagnostic flush extent is cache-line sized");

static inline void zn_acp_dirty_diag_init(
    volatile ZnAcpDirtySmokeDiagnostic *diag,
    uint32_t epoch,
    uint32_t source_base,
    uint32_t destination_base,
    uint32_t scratch_base,
    uint32_t source_bytes,
    uint32_t destination_bytes,
    uint32_t scratch_bytes)
{
    uint32_t i;

    diag->magic = ZN_ACP_DIRTY_DIAG_MAGIC;
    diag->version = ZN_ACP_DIRTY_DIAG_VERSION;
    diag->bytes = (uint32_t)sizeof *diag;
    diag->epoch = epoch;
    diag->attempted_mask = 0u;
    diag->completed_mask = 0u;
    diag->overall_result = ZN_ACP_DIRTY_DIAG_OVERALL_RUNNING;
    diag->failure_case = ZN_ACP_DIRTY_DIAG_NONE;
    diag->source_base = source_base;
    diag->destination_base = destination_base;
    diag->scratch_base = scratch_base;
    diag->source_bytes = source_bytes;
    diag->destination_bytes = destination_bytes;
    diag->scratch_bytes = scratch_bytes;
    diag->case_count = ZN_ACP_DIRTY_DIAG_CASES;
    diag->failure_result = ZN_ACP_DIRTY_DIAG_RESULT_NOT_RUN;
    for (i = 0u; i < ZN_ACP_DIRTY_DIAG_CASES; ++i) {
        volatile ZnAcpDirtySmokeCaseDiagnostic *record = &diag->cases[i];
        record->stage_result = ZN_ACP_DIRTY_DIAG_STAGE_RESULT(
            ZN_ACP_DIRTY_DIAG_STAGE_IDLE, ZN_ACP_DIRTY_DIAG_RESULT_NOT_RUN);
        record->driver_code = ZN_ACP_DIRTY_DIAG_NONE;
        record->status = 0u;
        record->bridge_error = 0u;
        record->backend_fault_code = 0u;
        record->request_cookie = 0u;
        record->result_epoch = 0u;
        record->event = 0u;
        record->committed_tiles = 0u;
        record->ownership_flags = 0u;
        record->drain_flags = 0u;
        record->bad_offset = ZN_ACP_DIRTY_DIAG_NONE;
        record->guard_flags = 0u;
        record->immediate_flags = 0u;
        record->full_output_flags = 0u;
        record->ack_code = ZN_ACP_DIRTY_DIAG_NONE;
    }
}

static inline int zn_acp_dirty_diag_begin_case(
    volatile ZnAcpDirtySmokeDiagnostic *diag,
    uint32_t case_index)
{
    volatile ZnAcpDirtySmokeCaseDiagnostic *record;
    uint32_t bit;

    if (case_index >= diag->case_count ||
        diag->overall_result != ZN_ACP_DIRTY_DIAG_OVERALL_RUNNING)
        return 0;
    bit = UINT32_C(1) << case_index;
    if (diag->attempted_mask & bit)
        return 0;
    diag->attempted_mask |= bit;
    record = &diag->cases[case_index];
    record->stage_result = ZN_ACP_DIRTY_DIAG_STAGE_RESULT(
        ZN_ACP_DIRTY_DIAG_STAGE_BUFFER_INIT, ZN_ACP_DIRTY_DIAG_RESULT_RUNNING);
    return 1;
}

static inline void zn_acp_dirty_diag_set_stage(
    volatile ZnAcpDirtySmokeDiagnostic *diag,
    uint32_t case_index,
    uint32_t stage)
{
    volatile ZnAcpDirtySmokeCaseDiagnostic *record = &diag->cases[case_index];
    record->stage_result = ZN_ACP_DIRTY_DIAG_STAGE_RESULT(
        stage, ZN_ACP_DIRTY_DIAG_RESULT_OF(record->stage_result));
}

static inline void zn_acp_dirty_diag_fail_case(
    volatile ZnAcpDirtySmokeDiagnostic *diag,
    uint32_t case_index,
    uint32_t stage,
    uint32_t failure_result)
{
    if (case_index >= diag->case_count ||
        !(diag->attempted_mask & (UINT32_C(1) << case_index)))
        return;
    diag->cases[case_index].stage_result = ZN_ACP_DIRTY_DIAG_STAGE_RESULT(
        stage, failure_result);
    diag->overall_result = ZN_ACP_DIRTY_DIAG_OVERALL_FAIL;
    diag->failure_case = case_index;
    diag->failure_result = failure_result;
}

static inline void zn_acp_dirty_diag_fail_preflight(
    volatile ZnAcpDirtySmokeDiagnostic *diag,
    uint32_t failure_result)
{
    diag->overall_result = ZN_ACP_DIRTY_DIAG_OVERALL_FAIL;
    diag->failure_case = ZN_ACP_DIRTY_DIAG_NONE;
    diag->failure_result = failure_result;
}

static inline int zn_acp_dirty_diag_complete_case(
    volatile ZnAcpDirtySmokeDiagnostic *diag,
    uint32_t case_index,
    int checks_passed,
    int ack_succeeded,
    int ownership_released)
{
    uint32_t bit;

    if (case_index >= diag->case_count || !checks_passed ||
        !ack_succeeded || !ownership_released ||
        diag->overall_result != ZN_ACP_DIRTY_DIAG_OVERALL_RUNNING)
        return 0;
    bit = UINT32_C(1) << case_index;
    if (!(diag->attempted_mask & bit) || (diag->completed_mask & bit) ||
        ZN_ACP_DIRTY_DIAG_RESULT_OF(diag->cases[case_index].stage_result) !=
            ZN_ACP_DIRTY_DIAG_RESULT_RUNNING)
        return 0;
    diag->cases[case_index].stage_result = ZN_ACP_DIRTY_DIAG_STAGE_RESULT(
        ZN_ACP_DIRTY_DIAG_STAGE_COMPLETE, ZN_ACP_DIRTY_DIAG_RESULT_PASS);
    diag->completed_mask |= bit;
    if (diag->completed_mask ==
        ((UINT32_C(1) << diag->case_count) - UINT32_C(1)))
        diag->overall_result = ZN_ACP_DIRTY_DIAG_OVERALL_PASS;
    return 1;
}

#endif
