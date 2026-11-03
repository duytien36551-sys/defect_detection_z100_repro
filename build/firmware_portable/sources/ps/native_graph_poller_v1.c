#include "native_graph_poller_v1.h"

#include <string.h>

#define ZN_NGPV1_MAGIC UINT32_C(0x4e475031)

static int
zn_ngpv1_identity(const ZnNativeGraphPollerV1 *p)
{
    const ZnNativeGraphExecutorV1 *e = p->executor;
    return e && e->owner == p->owner && e->dispatch == p->dispatch &&
        e->conv_lifecycle == p->conv && e->nonconv_lifecycle == p->nonconv &&
        e->resolve_conv == p->resolver && e->resolve_context == p->resolver_context &&
        p->conv->owner == p->owner && p->nonconv->owner == p->owner &&
        p->dispatch->events == p->events && p->owner->events == p->events &&
        p->dispatch->count == p->event_count &&
        p->owner->event_count == p->event_count &&
        p->owner->epoch == p->epoch && p->dispatch->epoch == p->epoch;
}

static ZnNativeGraphPollerCodeV1
zn_ngpv1_terminal(ZnNativeGraphPollerV1 *p, ZnNativeGraphPollerCodeV1 code)
{
    p->terminal = 1;
    p->terminal_code = code;
    return code;
}

static ZnNativeGraphPollerCodeV1
zn_ngpv1_fail(ZnNativeGraphPollerV1 *p, ZnNativeGraphPollerCodeV1 code)
{
    if (!p->executor->complete) {
        if (code == ZN_NATIVE_GRAPH_POLLER_V1_IDENTITY) {
            /* Fault only the original graph. Never follow a substituted
             * owner/dispatch pointer or run an MMIO callback on rejection. */
            p->owner->fault = 1;
            p->dispatch->fault = 1;
            p->executor->terminal = 1;
            p->executor->terminal_code = ZN_NATIVE_GRAPH_EXECUTOR_V1_STALE_REQUEST;
        } else {
            (void)zn_native_graph_executor_v1_timeout(p->executor);
        }
    }
    return zn_ngpv1_terminal(p, code);
}

static int
zn_ngpv1_sample(ZnNativeGraphPollerV1 *p)
{
    uint64_t ticks;
    if (p->read_ticks(p->clock_context, &ticks) != 0 || ticks < p->last_ticks)
        return -1;
    p->last_ticks = ticks;
    p->elapsed_ticks = ticks - p->start_ticks;
    return 0;
}

ZnNativeGraphPollerCodeV1
zn_native_graph_poller_init_v1(
    ZnNativeGraphPollerV1 *p, ZnNativeGraphExecutorV1 *e,
    ZnNativeGraphPollerTicksV1 read_ticks, void *clock_context,
    uint64_t ticks_per_second, uint64_t budget_ticks)
{
    ZnNativeGraphPollerV1 candidate;
    uint64_t ticks;
    if (!p || p->magic || !e || !read_ticks || !ticks_per_second || !budget_ticks ||
        !e->owner || !e->dispatch || !e->conv_lifecycle || !e->nonconv_lifecycle ||
        !e->resolve_conv || e->terminal || e->complete || !e->owner->initialized ||
        e->owner->fault || e->dispatch->fault || e->conv_lifecycle->fault ||
        e->nonconv_lifecycle->fault || e->conv_lifecycle->owner != e->owner ||
        e->nonconv_lifecycle->owner != e->owner ||
        e->dispatch->epoch != e->owner->epoch || !e->owner->epoch ||
        !e->owner->events || e->dispatch->events != e->owner->events ||
        e->dispatch->count != e->owner->event_count)
        return ZN_NATIVE_GRAPH_POLLER_V1_ARGUMENT;
    if (read_ticks(clock_context, &ticks) != 0)
        return ZN_NATIVE_GRAPH_POLLER_V1_CLOCK_FAILED;
    memset(&candidate, 0, sizeof candidate);
    candidate.magic = ZN_NGPV1_MAGIC;
    candidate.executor = e;
    candidate.owner = e->owner;
    candidate.dispatch = e->dispatch;
    candidate.conv = e->conv_lifecycle;
    candidate.nonconv = e->nonconv_lifecycle;
    candidate.resolver = e->resolve_conv;
    candidate.resolver_context = e->resolve_context;
    candidate.events = e->owner->events;
    candidate.event_count = e->owner->event_count;
    candidate.epoch = e->owner->epoch;
    candidate.read_ticks = read_ticks;
    candidate.clock_context = clock_context;
    candidate.ticks_per_second = ticks_per_second;
    candidate.budget_ticks = budget_ticks;
    candidate.start_ticks = ticks;
    candidate.last_ticks = ticks;
    *p = candidate;
    return ZN_NATIVE_GRAPH_POLLER_V1_YIELDED;
}

ZnNativeGraphPollerCodeV1
zn_native_graph_poller_poll_v1(ZnNativeGraphPollerV1 *p, uint32_t max_steps)
{
    uint32_t step;
    if (!p || p->magic != ZN_NGPV1_MAGIC || !max_steps ||
        max_steps > ZN_NATIVE_GRAPH_POLLER_MAX_STEPS_V1 ||
        !p->executor || !p->owner || !p->dispatch || !p->conv ||
        !p->nonconv || !p->read_ticks || !p->resolver)
        return ZN_NATIVE_GRAPH_POLLER_V1_ARGUMENT;
    if (p->terminal)
        return (ZnNativeGraphPollerCodeV1)p->terminal_code;
    if (!zn_ngpv1_identity(p))
        return zn_ngpv1_fail(p, ZN_NATIVE_GRAPH_POLLER_V1_IDENTITY);
    for (step = 0; step < max_steps; ++step) {
        ZnNativeGraphExecutorCodeV1 code;
        if (zn_ngpv1_sample(p) != 0)
            return zn_ngpv1_fail(p, ZN_NATIVE_GRAPH_POLLER_V1_CLOCK_FAILED);
        if (p->elapsed_ticks >= p->budget_ticks)
            return zn_ngpv1_fail(p, ZN_NATIVE_GRAPH_POLLER_V1_TIMED_OUT);
        code = zn_native_graph_executor_v1_step(p->executor);
        ++p->executor_calls;
        p->last_executor_code = code;
        if (code == ZN_NATIVE_GRAPH_EXECUTOR_V1_BUSY)
            ++p->busy_calls;
        else if (code == ZN_NATIVE_GRAPH_EXECUTOR_V1_ACKED)
            ++p->acked_calls;
        else if (code == ZN_NATIVE_GRAPH_EXECUTOR_V1_SCRATCH_RELEASED)
            ++p->scratch_releases;
        else if (code != ZN_NATIVE_GRAPH_EXECUTOR_V1_COMPLETE)
            return zn_ngpv1_fail(p, ZN_NATIVE_GRAPH_POLLER_V1_EXECUTOR_FAILED);
        if (zn_ngpv1_sample(p) != 0)
            return zn_ngpv1_fail(p, ZN_NATIVE_GRAPH_POLLER_V1_CLOCK_FAILED);
        if (code == ZN_NATIVE_GRAPH_EXECUTOR_V1_COMPLETE)
            return zn_ngpv1_terminal(p, p->elapsed_ticks >= p->budget_ticks ?
                ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE_LATE :
                ZN_NATIVE_GRAPH_POLLER_V1_COMPLETE);
        if (p->elapsed_ticks >= p->budget_ticks)
            return zn_ngpv1_fail(p, ZN_NATIVE_GRAPH_POLLER_V1_TIMED_OUT);
    }
    return ZN_NATIVE_GRAPH_POLLER_V1_YIELDED;
}
