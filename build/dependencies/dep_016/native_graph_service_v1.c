#include "native_graph_service_v1.h"
#include "native_postprocess_epoch200_v1.h"
#include "v8_preprocess_neon.h"

#include <string.h>

#define SERVICE_MAGIC UINT32_C(0x4e475356)
#define INPUT_SCALE 0.007874015748031496

static int apart(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t av = (uintptr_t)a, bv = (uintptr_t)b;
    return a && b && an && bn && an <= UINTPTR_MAX-av && bn <= UINTPTR_MAX-bv &&
        (av+an <= bv || bv+bn <= av);
}

static int outside_model(const ZnNativeGraphSessionV1 *s, const void *p, size_t bytes)
{
    const ZnNativePlatformMappedSpanV1 *maps[5] = {&s->frame.config.arena,&s->frame.config.scratch,
        &s->frame.config.heads,&s->model.parameter_mapping,&s->model.directory_mapping};
    unsigned i;
    if (!apart(p,bytes,s,sizeof *s) ||
        !apart(p,bytes,s->model.parameter_payload.data,(size_t)ZN_NPMV1_PARAMETER_BYTES) ||
        !apart(p,bytes,s->model.directory.data,(size_t)ZN_NPMV1_DIRECTORY_BYTES) ||
        !apart(p,bytes,s->model.package_sha256,65) || !apart(p,bytes,s->model.checkpoint_sha256,65) ||
        !apart(p,bytes,s->model.graph_sha256,65) || !apart(p,bytes,s->model.parameter_payload.sha256,65) ||
        !apart(p,bytes,s->model.directory.sha256,65)) return 0;
    for (i = 0; i < 5; ++i) if (!apart(p,bytes,maps[i]->cpu_base,maps[i]->cpu_bytes)) return 0;
    return 1;
}

static int fail(ZnNativeGraphServiceV1 *a)
{
    a->state = ZN_NATIVE_SERVICE_V1_FAILED;
    return a->state;
}

static int sample(ZnNativeGraphServiceV1 *a, uint64_t *out)
{
    uint64_t now;
    if (a->session->frame.config.read_ticks(a->session->frame.config.clock_context,&now) || now < a->last_ticks) {
        a->timing.clock_valid = 0;
        return -1;
    }
    a->last_ticks = now; *out = now;
    return 0;
}

static int infer(void *context, const uint8_t *rgb, size_t bytes,
                 V8Detection *boxes, size_t capacity, size_t *count)
{
    ZnNativeGraphServiceV1 *a = context;
    const uint8_t *heads = NULL;
    size_t head_bytes = 0, decoded = SIZE_MAX;
    V8DecodeConfig decode = {640,640,9,16,0.25f,0.45f,1,NULL,0};
    int code;
    if (!a || a->magic != SERVICE_MAGIC || a->state != ZN_NATIVE_SERVICE_V1_SERVING || !count ||
        rgb != a->wire->tensor || bytes != V8_SERVICE_TENSOR_BYTES || boxes != a->wire->detections ||
        capacity != 300 || !outside_model(a->session,count,sizeof *count) ||
        !apart(count,sizeof *count,a,sizeof *a) || !apart(count,sizeof *count,a->wire,sizeof *a->wire) ||
        !apart(count,sizeof *count,a->input_nchw,a->input_bytes) ||
        !apart(count,sizeof *count,rgb,bytes) || !apart(count,sizeof *count,boxes,capacity*sizeof *boxes) ||
        !apart(count,sizeof *count,a->wire->response,a->wire->response_capacity)) return -1;
    if (sample(a,&a->timing.infer_start)) return fail(a);
    if (v8_preprocess_neon_640(rgb,bytes,a->input_nchw,a->input_bytes,INPUT_SCALE) ||
        sample(a,&a->timing.preprocess_end)) return fail(a);
    a->timing.preprocess_ticks = a->timing.preprocess_end-a->timing.infer_start;
    code = zn_native_graph_session_start_v1(a->session,(const uint8_t *)a->input_nchw,a->input_bytes);
    if (code != ZN_NATIVE_FRAME_V1_YIELDED) { a->timing.frame_code = code; return fail(a); }
    do { code = zn_native_graph_session_poll_v1(a->session,64); }
    while (code == ZN_NATIVE_FRAME_V1_YIELDED);
    a->timing.frame_code = code;
    if ((code != ZN_NATIVE_FRAME_V1_COMPLETE && code != ZN_NATIVE_FRAME_V1_COMPLETE_LATE) ||
        sample(a,&a->timing.graph_end) || zn_native_graph_session_heads_v1(a->session,&heads,&head_bytes)) return fail(a);
    a->timing.graph_complete_late = (uint8_t)(code == ZN_NATIVE_FRAME_V1_COMPLETE_LATE);
    a->timing.graph_ticks = a->timing.graph_end-a->timing.preprocess_end;
    a->timing.decode_code = v8_native_postprocess_epoch200_v1((const int8_t *)heads,head_bytes,
        v8_epoch200_expected_identity(),&decode,boxes,capacity,&decoded);
    if (a->timing.decode_code || sample(a,&a->timing.decode_end)) return fail(a);
    a->timing.decode_ticks = a->timing.decode_end-a->timing.graph_end;
    a->timing.infer_ticks = a->timing.decode_end-a->timing.infer_start;
    a->timing.detections = decoded;
    a->timing.inference_completed = 1;
    a->state = ZN_NATIVE_SERVICE_V1_RESULT_PENDING;
    *count = decoded;
    return 0;
}

int zn_native_graph_service_init_v1(ZnNativeGraphServiceV1 *a, ZnNativeGraphSessionV1 *s,
                                   V8Service *w, int8_t *nchw, size_t bytes)
{
    const V8Epoch200Identity *id = v8_epoch200_expected_identity();
    const void *regions[6]; size_t lengths[6]; unsigned i,j;
    if (!a || !s || !w || a->magic || s->state != ZN_NATIVE_SESSION_V1_READY || !s->model_state.ready ||
        s->reserved != 31 || s->frame.state != ZN_NATIVE_FRAME_V1_READY ||
        !s->frame.config.read_ticks || !s->frame.config.ticks_per_second ||
        !w->verified_identity || memcmp(w->model_sha256,id->package_sha256,65) ||
        memcmp(w->classes_sha256,id->classes_sha256,65) || !w->class_domain || strncmp(w->class_domain,"pin",4) ||
        w->class_count != 9 || !w->read || !w->write || w->infer || w->inference ||
        bytes != ZN_NATIVE_FRAME_INPUT_BYTES_V1 || w->tensor_capacity != V8_SERVICE_TENSOR_BYTES ||
        w->detection_capacity != 300 || w->response_capacity < 65536) return ZN_NATIVE_SERVICE_V1_ARGUMENT;
    regions[0]=a; lengths[0]=sizeof *a; regions[1]=w; lengths[1]=sizeof *w;
    regions[2]=nchw; lengths[2]=bytes; regions[3]=w->tensor; lengths[3]=w->tensor_capacity;
    regions[4]=w->detections; lengths[4]=w->detection_capacity*sizeof *w->detections;
    regions[5]=w->response; lengths[5]=w->response_capacity;
    for (i=0;i<6;++i) {
        if (!outside_model(s,regions[i],lengths[i])) return ZN_NATIVE_SERVICE_V1_ARGUMENT;
        for (j=i+1;j<6;++j) if (!apart(regions[i],lengths[i],regions[j],lengths[j])) return ZN_NATIVE_SERVICE_V1_ARGUMENT;
    }
    /* class_domain remains an external immutable string. Protect it from every
     * writable range before storing state or changing the service callbacks. */
    if (!outside_model(s,w->class_domain,4)) return ZN_NATIVE_SERVICE_V1_ARGUMENT;
    for (i=0;i<6;++i) if (!apart(regions[i],lengths[i],w->class_domain,4)) return ZN_NATIVE_SERVICE_V1_ARGUMENT;
    memset(a,0,sizeof *a);
    a->magic=SERVICE_MAGIC; a->session=s; a->wire=w; a->input_nchw=nchw; a->input_bytes=bytes;
    a->read=w->read; a->write=w->write; a->transport=w->transport;
    w->infer=infer; w->inference=a;
    a->timing.epoch=s->frame.config.epoch; a->timing.ticks_per_second=s->frame.config.ticks_per_second;
    return ZN_NATIVE_SERVICE_V1_READY;
}

int zn_native_graph_service_one_v1(ZnNativeGraphServiceV1 *a)
{
    int code;
    if (!a || a->magic != SERVICE_MAGIC) return ZN_NATIVE_SERVICE_V1_ARGUMENT;
    if (a->state != ZN_NATIVE_SERVICE_V1_READY) return ZN_NATIVE_SERVICE_V1_STATE;
    if (a->wire->infer != infer || a->wire->inference != a || a->wire->read != a->read ||
        a->wire->write != a->write || a->wire->transport != a->transport) return fail(a);
    a->timing.clock_valid=1;
    if (sample(a,&a->timing.connection_start)) return fail(a);
    a->state=ZN_NATIVE_SERVICE_V1_SERVING;
    code=v8_service_one(a->wire); a->timing.wire_code=code;
    if (sample(a,&a->timing.connection_end)) return fail(a);
    a->timing.connection_ticks=a->timing.connection_end-a->timing.connection_start;
    if (code || a->state != ZN_NATIVE_SERVICE_V1_RESULT_PENDING || !a->timing.inference_completed) return fail(a);
    a->timing.result_delivered=1; a->state=ZN_NATIVE_SERVICE_V1_DELIVERED;
    return ZN_NATIVE_SERVICE_V1_DELIVERED;
}

int zn_native_graph_service_rearm_v1(ZnNativeGraphServiceV1 *a, uint32_t epoch)
{
    int code;
    if (!a || a->magic != SERVICE_MAGIC) return ZN_NATIVE_SERVICE_V1_ARGUMENT;
    if (a->state != ZN_NATIVE_SERVICE_V1_DELIVERED || !a->timing.result_delivered) return ZN_NATIVE_SERVICE_V1_STATE;
    code=zn_native_graph_session_rearm_v1(a->session,epoch);
    if (code != ZN_NATIVE_FRAME_V1_READY) return code == ZN_NATIVE_FRAME_V1_FAILED ? fail(a) : ZN_NATIVE_SERVICE_V1_STATE;
    memset(&a->timing,0,sizeof a->timing);
    a->timing.epoch=epoch; a->timing.ticks_per_second=a->session->frame.config.ticks_per_second;
    a->state=ZN_NATIVE_SERVICE_V1_READY;
    return ZN_NATIVE_SERVICE_V1_READY;
}
