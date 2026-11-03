
#include "native_direct_bindings_v2.h"
#include "graph_plan.h"
#include <stdio.h>
#include <string.h>

enum { RESULT_WORDS = 10, WRITE_CAPACITY = 64 };
typedef struct {
    uint32_t status, bridge_error, fault_code;
    uint32_t shadow[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    uint32_t result[RESULT_WORDS];
    uint32_t offsets[WRITE_CAPACITY], values[WRITE_CAPACITY];
    uint32_t expected_tiles;
    unsigned int write_count, barrier_count, start_count;
} MockMmio;
typedef struct {
    MockMmio *mmio;
    uint8_t read_count;
} BridgeHooks;

static unsigned int failures;
static void check(int ok, const char *name) {
    if (!ok) {
        fprintf(stderr, "FAIL %s\n", name);
        ++failures;
    }
}
static int ref_eq(ZnRef a, ZnRef b) {
    return a.slot == b.slot && a.tensor == b.tensor &&
           a.generation == b.generation;
}
static void mock_reset(MockMmio *m) {
    memset(m, 0, sizeof *m);
    m->status = ZN_NC_STATUS_READY | ZN_NC_STATUS_DRAIN_COMPLETE;
}
static int mock_read(void *context, uint32_t offset, uint32_t *value) {
    MockMmio *m = (MockMmio *)context;
    unsigned int i;
    if (!m || !value || (offset & 3u))
        return -1;
    if (offset == ZN_NC_REG_ID) *value = ZN_NATIVE_CONV_MMIO_ID_VALUE;
    else if (offset == ZN_NC_REG_ABI_VERSION)
        *value = ZN_NATIVE_CONV_MMIO_ABI_VERSION;
    else if (offset == ZN_NC_REG_CAPABILITIES) *value = ZN_NC_CAP_VALID_MASK;
    else if (offset == ZN_NC_REG_STATUS) *value = m->status;
    else if (offset == ZN_NC_REG_BRIDGE_ERROR) *value = m->bridge_error;
    else if (offset == ZN_NC_REG_BACKEND_FAULT_CODE) *value = m->fault_code;
    else if (offset >= ZN_NC_REG_RESULT_COOKIE &&
             offset <= ZN_NC_REG_RESULT_SOURCE_GEN) {
        i = (offset - ZN_NC_REG_RESULT_COOKIE) / 4u;
        if (i >= RESULT_WORDS) return -1;
        *value = m->result[i];
    } else return -1;
    return 0;
}
static int mock_write(void *context, uint32_t offset, uint32_t value) {
    MockMmio *m = (MockMmio *)context;
    unsigned int i;
    if (!m || m->write_count >= WRITE_CAPACITY) return -1;
    m->offsets[m->write_count] = offset;
    m->values[m->write_count++] = value;
    if (offset >= ZN_NC_REG_SHADOW_COOKIE &&
        offset <= ZN_NC_REG_SHADOW_ACCEPT_TIMEOUT) {
        i = (offset - ZN_NC_REG_SHADOW_COOKIE) / 4u;
        if (i >= ZN_NATIVE_CONV_COMMAND_WORD_COUNT) return -1;
        m->shadow[i] = value;
        return 0;
    }
    if (offset != ZN_NC_REG_CONTROL) return -1;
    if (value == ZN_NC_CONTROL_START) {
        ++m->start_count;
        m->status = ZN_NC_STATUS_ACCEPTED | ZN_NC_STATUS_ACTIVE |
                    ZN_NC_STATUS_DRAIN_COMPLETE;
        return 0;
    }
    return -1;
}
static int mock_barrier(void *context) {
    MockMmio *m = (MockMmio *)context;
    if (!m) return -1;
    ++m->barrier_count;
    return 0;
}
static int hook_leases(void *context, const ZnRequest *r,
                       const ZnNativeGraphConvBindingV2 *b) {
    BridgeHooks *h = (BridgeHooks *)context;
    uint8_t i;
    if (!h || !r || !b || b->graph_read_count != h->read_count ||
        b->scratch.epoch != r->epoch || !b->scratch.generation)
        return -1;
    for (i = 0; i < h->read_count; ++i)
        if (!ref_eq(b->graph_read_refs[i], r->job->reads[i]))
            return -1;
    return 0;
}
static int hook_convert(void *context, const ZnRequest *r,
                        const ZnNativeGraphConvBindingV2 *b) {
    (void)context;
    (void)r;
    return b && b->source_span.base == b->scratch.base &&
           b->source_span.bytes != 0 ? 0 : -1;
}
static int hook_clean(void *context, const ZnNativeGraphConvBindingV2 *b) {
    (void)context;
    return b && b->source_span.bytes ? 0 : -1;
}
static int hook_ready(void *context, const ZnRequest *r,
                      const ZnNativeGraphConvBindingV2 *b) {
    (void)context;
    (void)r;
    return b && b->source_span.bytes ? 0 : -1;
}
static int hook_binding(void *context, const ZnNativeGraphConvBindingV2 *b) {
    (void)context;
    return b ? 0 : -1;
}
static int hook_drain(void *context, const ZnRequest *r,
                      const ZnNativeGraphConvBindingV2 *b) {
    (void)context;
    (void)r;
    return b ? 0 : -1;
}
static int hook_return(void *context, const ZnRequest *r,
                       const ZnNativeGraphConvBindingV2 *b, uint8_t index) {
    (void)context;
    return r && b && index < b->graph_read_count &&
           ref_eq(r->ref, b->graph_read_refs[index]) ? 0 : -1;
}
static int hook_release(void *context, const ZnNativeGraphConvBindingV2 *b) {
    (void)context;
    return b ? 0 : -1;
}
static ZnNativeDirectIdsV2 ids_for_event(uint16_t i) {
    ZnNativeDirectIdsV2 ids;
    ids.job_base = 1000u + (uint32_t)i * 32u;
    ids.token_base = 100000u + (uint32_t)i * 10000u;
    ids.tag_base = 10000000u + (uint32_t)i * 100000u;
    ids.load_timeout_cycles = 1000000u;
    ids.parameter_timeout_cycles = 1000000u;
    ids.write_timeout_cycles = 1000000u;
    ids.preaccept_timeout_cycles = 1000000u;
    ids.first_bank = (uint8_t)(i & 1u);
    return ids;
}
static int dispatch_to_run(ZnDispatch *dispatch, uint16_t event_index,
                           uint32_t first_tag, ZnRequest *request) {
    unsigned int attempts;
    if (zn_dispatch_init(dispatch, z100_graph_events, 73, 200) != 0)
        return -1;
    dispatch->cursor = event_index;
    dispatch->phase = ZN_ALLOCATE;
    dispatch->index = 0;
    dispatch->next_tag = first_tag;
    for (attempts = 0; attempts < 16; ++attempts) {
        if (zn_dispatch_next(dispatch, request) != 1) return -1;
        if (request->operation == ZN_RUN) return 0;
        if (zn_dispatch_ack(dispatch, request->tag, request->operation,
                            ZN_ACK_OK) != 0) return -1;
    }
    return -1;
}
static int rejected_unchanged(const ZnRequest *r,
    const ZnNativeDirectIdsV2 *ids, const ZnNativeGraphScratchLeaseV2 *source) {
    ZnNativeGraphConvBindingV2 out, before;
    memset(&out, 0xa5, sizeof out);
    before = out;
    return zn_native_direct_binding_v2(r, ids, source, &out) == -1 &&
           memcmp(&out, &before, sizeof out) == 0;
}
static int deferred_unchanged(const ZnRequest *r,
    const ZnNativeDirectIdsV2 *ids, const ZnNativeGraphScratchLeaseV2 *source) {
    ZnNativeGraphConvBindingV2 out, before;
    memset(&out, 0xa5, sizeof out);
    before = out;
    return zn_native_direct_binding_v2(r, ids, source, &out) == 1 &&
           memcmp(&out, &before, sizeof out) == 0;
}

static const ZnNativeGraphScratchLeaseV2 source_leases[73] = {
    {200u,1u,268435456u,1638400u},
    {200u,2u,270073856u,1638400u},
    {200u,3u,268435456u,819200u},
    {0u,0u,0u,0u},
    {200u,5u,268435456u,409600u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {200u,8u,271712256u,819200u},
    {200u,9u,268435456u,409600u},
    {0u,0u,0u,0u},
    {200u,11u,268435456u,204800u},
    {0u,0u,0u,0u},
    {200u,13u,268435456u,204800u},
    {200u,14u,271712256u,204800u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {200u,17u,272531456u,409600u},
    {200u,18u,268435456u,245760u},
    {0u,0u,0u,0u},
    {200u,20u,268435456u,122880u},
    {0u,0u,0u,0u},
    {200u,22u,268435456u,122880u},
    {200u,23u,271712256u,122880u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {200u,26u,272941056u,245760u},
    {200u,27u,268435456u,163840u},
    {0u,0u,0u,0u},
    {200u,29u,268435456u,81920u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {200u,32u,271712256u,163840u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {200u,39u,270073856u,122880u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {200u,43u,271712256u,204800u},
    {0u,0u,0u,0u},
    {200u,45u,271712256u,409600u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {200u,48u,268435456u,122880u},
    {0u,0u,0u,0u},
    {200u,50u,268435456u,245760u},
    {0u,0u,0u,0u},
    {0u,0u,0u,0u},
    {200u,53u,270073856u,81920u},
    {0u,0u,0u,0u},
    {200u,45u,271712256u,409600u},
    {200u,56u,272531456u,409600u},
    {200u,57u,272941056u,409600u},
    {200u,45u,271712256u,409600u},
    {200u,59u,272941056u,409600u},
    {200u,60u,271712256u,409600u},
    {200u,50u,268435456u,245760u},
    {200u,62u,271712256u,122880u},
    {200u,63u,273350656u,122880u},
    {200u,50u,268435456u,245760u},
    {200u,65u,273350656u,122880u},
    {200u,66u,268435456u,122880u},
    {200u,55u,270073856u,163840u},
    {200u,68u,268435456u,40960u},
    {200u,69u,273473536u,40960u},
    {200u,55u,270073856u,163840u},
    {200u,71u,273473536u,40960u},
    {200u,72u,270073856u,40960u},
    {0u,0u,0u,0u},
};

static void test_generated_bindings(void) {
    unsigned int direct = 0, views = 0, nonconv = 0, rejected = 0;
    uint16_t i;
    for (i = 0; i < 73; ++i) {
        ZnDispatch dispatch;
        ZnRequest request;
        ZnNativeDirectIdsV2 ids = ids_for_event(i);
        ZnNativeGraphScratchLeaseV2 source = source_leases[i], bad_source;
        ZnNativeGraphConvBindingV2 binding;
        uint32_t words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
        unsigned int j;
        int rc;
        check(dispatch_to_run(&dispatch, i, 5000u + (uint32_t)i * 32u,
                              &request) == 0, "all graph events dispatch to RUN");
        check(request.operation == ZN_RUN && request.job == &z100_graph_events[i],
              "dispatch request identity");
        rc = zn_native_direct_binding_v2(&request, &ids, &source, &binding);
        if (rc == 1) {
            check(deferred_unchanged(&request, &ids, &source),
                  "deferred event preserves output");
            if (request.job->operation == ZN_CONV) ++views;
            else ++nonconv;
            continue;
        }
        check(rc == 0, "direct event binding succeeds");
        ++direct;
        check(binding.dispatch_epoch == request.epoch &&
              binding.dispatch_tag == request.tag &&
              binding.event_index == request.event_index &&
              binding.expected_cookie == request.tag &&
              binding.graph_read_count == request.job->read_count &&
              binding.expected_tiles == request.job->tile_count,
              "dispatch and full graph read identity");
        check(binding.graph_read_count == 1 &&
              ref_eq(binding.graph_read_refs[0], request.job->reads[0]) &&
              ref_eq(binding.destination_ref, request.job->destination.ref),
              "read and destination refs");
        check(binding.scratch.epoch == source.epoch &&
              binding.scratch.generation == source.generation &&
              binding.scratch.base == source.base &&
              binding.scratch.bytes == source.bytes &&
              binding.source_span.base == source.base &&
              binding.source_span.bytes == source.bytes,
              "source span and lease");
        check(zn_native_conv_command_encode_v1(&binding.command, words) ==
                  ZN_NATIVE_CONV_COMMAND_OK,
              "encode every generated direct command");
        printf("WORDS %u %u", i, request.tag);
        for (j = 0; j < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++j)
            printf(" %08x", words[j]);
        puts("");

        bad_source = source; ++bad_source.epoch;
        check(rejected_unchanged(&request, &ids, &bad_source),
              "invalid source epoch rejection"); ++rejected;
        bad_source = source; ++bad_source.generation;
        check(rejected_unchanged(&request, &ids, &bad_source),
              "invalid source generation rejection"); ++rejected;
        bad_source = source; bad_source.base += 64;
        check(rejected_unchanged(&request, &ids, &bad_source),
              "invalid source span base rejection"); ++rejected;
        bad_source = source; bad_source.bytes -= 64;
        check(rejected_unchanged(&request, &ids, &bad_source),
              "invalid source span size rejection"); ++rejected;
        {
            ZnRequest bad = request; bad.epoch = 0;
            check(rejected_unchanged(&bad, &ids, &source),
                  "invalid dispatch epoch rejection"); ++rejected;
            bad = request; bad.tag = 0;
            check(rejected_unchanged(&bad, &ids, &source),
                  "invalid dispatch tag rejection"); ++rejected;
            bad = request; bad.event_index = (uint16_t)((i + 1u) % 73u);
            check(rejected_unchanged(&bad, &ids, &source),
                  "invalid event identity rejection"); ++rejected;
            bad = request; bad.operation = ZN_DRAIN;
            check(rejected_unchanged(&bad, &ids, &source),
                  "invalid operation rejection"); ++rejected;
        }
        {
            ZnNativeDirectIdsV2 bad = ids; bad.first_bank = 2;
            check(rejected_unchanged(&request, &bad, &source),
                  "invalid first bank rejection"); ++rejected;
            bad = ids; bad.job_base = 0;
            check(rejected_unchanged(&request, &bad, &source),
                  "invalid job IDs rejection"); ++rejected;
            bad = ids; bad.tag_base = UINT32_MAX;
            check(rejected_unchanged(&request, &bad, &source),
                  "invalid command ID range rejection"); ++rejected;
            bad = ids; bad.load_timeout_cycles = 0;
            check(rejected_unchanged(&request, &bad, &source),
                  "invalid timeout rejection"); ++rejected;
        }
        {
            ZnRequest bad = request;
            ZnEvent changed = *request.job;
            changed.destination.width++;
            bad.job = &changed;
            check(rejected_unchanged(&bad, &ids, &source),
                  "invalid event shape rejection"); ++rejected;
            changed = *request.job;
            changed.reads[0].generation++;
            bad.job = &changed;
            check(rejected_unchanged(&bad, &ids, &source),
                  "invalid graph read generation rejection"); ++rejected;
        }
    }
    check(direct == 42 && views == 21 && nonconv == 10,
          "exact direct/deferred event coverage");
    check(rejected == 14u * 42u, "all direct invalid-input checks ran");
    printf("BINDINGS_V2_COUNTS direct=%u view_deferred=%u nonconv_deferred=%u rejections=%u\n",
           direct, views, nonconv, rejected);
}

static void test_real_bridge_submission(void) {
    MockMmio mock;
    BridgeHooks state;
    ZnNativeConvMmioOpsV2 mmio;
    ZnNativeGraphConvHooksV2 hooks;
    ZnNativeGraphConvBridgeV2 bridge;
    ZnNativeDirectIdsV2 ids = ids_for_event(0);
    ZnNativeGraphScratchLeaseV2 source = source_leases[0];
    ZnNativeGraphConvBindingV2 binding;
    ZnDispatch dispatch;
    ZnRequest request;
    uint32_t words[ZN_NATIVE_CONV_COMMAND_WORD_COUNT];
    unsigned int i;
    int rc;

    check(dispatch_to_run(&dispatch, 0, 9000, &request) == 0,
          "bridge event dispatch");
    rc = zn_native_direct_binding_v2(&request, &ids, &source, &binding);
    check(rc == 0, "bridge receives generated V2 direct binding");
    mock_reset(&mock);
    mock.expected_tiles = binding.expected_tiles;
    state.mmio = &mock;
    state.read_count = binding.graph_read_count;
    mmio.context = &mock;
    mmio.read32 = mock_read;
    mmio.write32 = mock_write;
    mmio.write_barrier = mock_barrier;
    hooks.context = &state;
    hooks.check_leases = hook_leases;
    hooks.convert_views = hook_convert;
    hooks.clean_source = hook_clean;
    hooks.check_source_ready = hook_ready;
    hooks.invalidate_output = hook_binding;
    hooks.validate_and_publish = hook_binding;
    hooks.drain_ready = hook_drain;
    hooks.return_graph_read = hook_return;
    hooks.release_scratch = hook_release;
    check(zn_native_graph_conv_bridge_init_v2(&bridge, &mmio, &hooks) ==
              ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_ACKED, "V2 bridge initializes");
    check(zn_native_graph_conv_bridge_step_v2(&bridge, &dispatch, &request,
              &binding) == ZN_NATIVE_GRAPH_CONV_BRIDGE_V2_BUSY,
          "V2 bridge validates generated binding and submits");
    check(bridge.stage == ZN_NATIVE_GRAPH_CONV_STAGE_V2_SUBMITTED &&
          mock.start_count == 1 && mock.barrier_count == 1 &&
          mock.write_count == ZN_NATIVE_CONV_COMMAND_WORD_COUNT + 1u,
          "mock MMIO observed one complete generated command submission");
    check(zn_native_conv_command_encode_v1(&binding.command, words) ==
              ZN_NATIVE_CONV_COMMAND_OK, "encode submitted generated command");
    for (i = 0; i < ZN_NATIVE_CONV_COMMAND_WORD_COUNT; ++i)
        check(mock.shadow[i] == words[i] &&
              mock.offsets[i] == ZN_NC_REG_SHADOW_COOKIE + i * 4u,
              "mock MMIO shadow words match generated binding");
    printf("BRIDGE_DIRECT_PASS event=0 words=%u starts=%u\n",
           (unsigned int)ZN_NATIVE_CONV_COMMAND_WORD_COUNT, mock.start_count);
}

int main(void) {
    test_generated_bindings();
    test_real_bridge_submission();
    if (failures) {
        fprintf(stderr, "DIRECT_BINDINGS_V2_FAIL failures=%u\n", failures);
        return 1;
    }
    puts("DIRECT_BINDINGS_V2_PASS direct=42 view_deferred=21 nonconv_deferred=10 exact_words=1134 bridge_submissions=1");
    return 0;
}
