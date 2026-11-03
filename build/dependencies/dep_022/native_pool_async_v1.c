#include "native_pool_async_v1.h"
#include <stdint.h>

static int fail(ZnPoolAsyncV1 *p) {
    p->state = ZN_POOL_ASYNC_FAILED;
    return ZN_POOL_ASYNC_ERROR;
}

static int mapping_valid(const ZnPoolMappingV1 *m, uint32_t address) {
    return m && m->cpu_address && m->physical_address == address &&
        m->bytes == ZN_NATIVE_POOL_PHYSICAL_BYTES_V1 &&
        ((uintptr_t)m->cpu_address & 63u) == 0 &&
        (address & 63u) == 0 &&
        (uintptr_t)m->cpu_address <= UINTPTR_MAX - m->bytes;
}

int zn_pool_async_begin_v1(ZnPoolAsyncV1 *p, ZnNativeConvDriverV2 *driver,
    const ZnNativeConvCommand *command, const ZnPoolMappingV1 *source,
    const ZnPoolMappingV1 *destination, const ZnPoolCacheOpsV1 *cache) {
    uintptr_t src, dst;
    if (!p || !driver || !command || !cache || !cache->clean ||
        !cache->invalidate || !cache->barrier ||
        (p->state != ZN_POOL_ASYNC_IDLE && p->state != ZN_POOL_ASYNC_COMPLETE) ||
        driver->state != ZN_NATIVE_CONV_STATE_V2_IDLE || driver->ownership_held ||
        !zn_native_pool_command_valid_v1(command) ||
        !mapping_valid(source, command->source_base) ||
        !mapping_valid(destination, command->destination_base))
        return ZN_POOL_ASYNC_ERROR;
    src = (uintptr_t)source->cpu_address;
    dst = (uintptr_t)destination->cpu_address;
    if (src < dst + destination->bytes && dst < src + source->bytes)
        return ZN_POOL_ASYNC_ERROR;
    p->driver = driver;
    p->cache = *cache;
    p->source = *source;
    p->destination = *destination;
    p->cancelled = 0;
    /* Before any START: publish CPU source writes, preserve unrelated dirty
     * destination data, then discard destination cache lines. Both spans are
     * exclusive and exactly cache-line aligned. */
    if (cache->clean(cache->context, source->cpu_address, source->bytes) ||
        cache->clean(cache->context, destination->cpu_address, destination->bytes) ||
        cache->barrier(cache->context) ||
        cache->invalidate(cache->context, destination->cpu_address, destination->bytes) ||
        cache->barrier(cache->context))
        return fail(p);
    /* Treat uncertain START/IO errors as terminal here. The underlying driver
     * retains any possible hardware ownership and must not be reinitialized. */
    if (zn_native_pool_driver_submit_v1(driver, command) != ZN_NATIVE_CONV_DRIVER_V2_OK)
        return fail(p);
    p->state = ZN_POOL_ASYNC_RUNNING;
    return ZN_POOL_ASYNC_BUSY;
}

int zn_pool_async_poll_v1(ZnPoolAsyncV1 *p) {
    ZnNativeConvDriverCodeV2 code;
    if (!p || !p->driver) return ZN_POOL_ASYNC_ERROR;
    if (p->state == ZN_POOL_ASYNC_COMPLETE) return ZN_POOL_ASYNC_DONE;
    if (p->state != ZN_POOL_ASYNC_RUNNING) return ZN_POOL_ASYNC_ERROR;
    code = zn_native_conv_driver_poll_v2(p->driver);
    if (code == ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS) return ZN_POOL_ASYNC_BUSY;
    if (code != ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY || p->cancelled)
        return fail(p);
    if (!p->driver->result_verified || !p->driver->ownership_held ||
        /* Matched Xilinx clean callback performs clean+invalidate. */
        p->cache.clean(p->cache.context, p->destination.cpu_address,
                            p->destination.bytes) ||
        p->cache.barrier(p->cache.context))
        return fail(p);
    if (zn_native_conv_driver_ack_v2(p->driver) != ZN_NATIVE_CONV_DRIVER_V2_OK ||
        zn_native_conv_driver_ownership_held_v2(p->driver))
        return fail(p);
    p->state = ZN_POOL_ASYNC_COMPLETE;
    return ZN_POOL_ASYNC_DONE;
}

int zn_pool_async_cancel_v1(ZnPoolAsyncV1 *p) {
    ZnNativeConvDriverCodeV2 code;
    if (!p || !p->driver || p->state != ZN_POOL_ASYNC_RUNNING)
        return ZN_POOL_ASYNC_ERROR;
    p->cancelled = 1;
    code = zn_native_conv_driver_timeout_v2(p->driver);
    if (code == ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS ||
        code == ZN_NATIVE_CONV_DRIVER_V2_OK)
        return ZN_POOL_ASYNC_BUSY;
    return fail(p);
}

int zn_pool_async_abort_drain_v1(ZnPoolAsyncV1 *p) {
    ZnNativeConvDriverCodeV2 code;
    if (!p || !p->driver || p->state==ZN_POOL_ASYNC_IDLE ||
        p->state==ZN_POOL_ASYNC_COMPLETE) return ZN_POOL_ASYNC_ERROR;
    p->cancelled=1;
    p->state=ZN_POOL_ASYNC_FAILED;
    code=zn_native_conv_driver_timeout_v2(p->driver);
    if (code==ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS) return ZN_POOL_ASYNC_BUSY;
    if (code==ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY ||
        code==ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY ||
        code==ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY) return 2;
    return ZN_POOL_ASYNC_ERROR;
}
