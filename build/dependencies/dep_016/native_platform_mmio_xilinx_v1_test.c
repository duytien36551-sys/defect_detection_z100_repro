#include "native_platform_mmio_xilinx_v1.h"

#include <stdio.h>
#include <string.h>

typedef struct TestIo {
    uint32_t address;
    uint32_t value;
    unsigned reads;
    unsigned writes;
    unsigned barriers;
    int fail;
} TestIo;

static unsigned checks;
static unsigned failures;

static void check(int ok, const char *name)
{
    ++checks;
    if (!ok) {
        ++failures;
        (void)fprintf(stderr, "FAIL %s\n", name);
    }
}

static int host_read(void *opaque, uint32_t address, uint32_t *value)
{
    TestIo *io = (TestIo *)opaque;
    ++io->reads;
    io->address = address;
    *value = io->value;
    return io->fail;
}

static int host_write(void *opaque, uint32_t address, uint32_t value)
{
    TestIo *io = (TestIo *)opaque;
    ++io->writes;
    io->address = address;
    io->value = value;
    return io->fail;
}

static int host_barrier(void *opaque)
{
    TestIo *io = (TestIo *)opaque;
    ++io->barriers;
    return io->fail;
}

int main(void)
{
    TestIo io = {0};
    ZnNativePlatformMmioXilinxContextV1 context = {
        ZN_NPMMIO_V1_BASE, ZN_NPMMIO_V1_BYTES, &io,
        host_read, host_write, host_barrier
    };
    ZnNativePlatformMmioXilinxContextV1 bad;
    ZnNativeConvMmioOpsV2 ops;
    uint32_t offset;
    uint32_t observed;
    unsigned reads = 0u;
    unsigned writes = 0u;

    check(zn_native_platform_mmio_xilinx_ops_v1(&ops, &context) == 0,
          "bind complete host context");
    check(ops.context == &context, "bind driver context");
    for (offset = 0u; offset < ZN_NPMMIO_V1_BYTES; ++offset) {
        int allowed_read = (offset % 4u == 0u) &&
            ((offset == 0u || offset == 4u || offset == 8u) ||
             (offset >= 0x10u && offset <= 0x1cu) ||
             (offset >= 0x100u && offset <= 0x124u));
        int allowed_write = offset % 4u == 0u &&
            (offset == 0xcu || (offset >= 0x40u && offset <= 0xa8u));
        observed = UINT32_C(0xfedcba98);
        io.value = offset ^ UINT32_C(0x12345678);
        if (allowed_read) {
            ++reads;
            check(ops.read32(ops.context, offset, &observed) == 0 &&
                  io.address == ZN_NPMMIO_V1_BASE + offset &&
                  observed == io.value, "read whitelist translates address");
        } else {
            check(ops.read32(ops.context, offset, &observed) != 0 &&
                  observed == UINT32_C(0xfedcba98), "reject read without output mutation");
        }
        check(io.reads == reads, "rejected read has no IO");
        if (allowed_write) {
            ++writes;
            check(ops.write32(ops.context, offset, 1u) == 0 &&
                  io.address == ZN_NPMMIO_V1_BASE + offset && io.value == 1u,
                  "write whitelist translates address");
        } else {
            check(ops.write32(ops.context, offset, 1u) != 0, "reject write");
        }
        check(io.writes == writes, "rejected write has no IO");
    }
    check(reads == 17u && writes == 28u, "exact register coverage");
    for (offset = 0u; offset < 32u; ++offset) {
        int valid_control = offset == 1u || offset == 2u || offset == 4u || offset == 8u;
        check((ops.write32(ops.context, ZN_NC_REG_CONTROL, offset) == 0) == valid_control,
              "exactly one legal control pulse");
        if (valid_control)
            ++writes;
        check(io.writes == writes, "illegal control has no IO");
    }
    check(ops.read32(ops.context, UINT32_MAX, &observed) != 0 &&
          ops.write32(ops.context, UINT32_MAX, 1u) != 0 &&
          ops.read32(ops.context, ZN_NPMMIO_V1_BYTES, &observed) != 0 &&
          ops.write32(ops.context, ZN_NPMMIO_V1_BYTES, 1u) != 0,
          "reject outside and overflow offsets");
    check(ops.read32(NULL, 0u, &observed) != 0 &&
          ops.read32(ops.context, 0u, NULL) != 0 &&
          ops.write32(NULL, 0xcu, 1u) != 0 &&
          ops.write_barrier(NULL) != 0, "reject null callbacks");
    check(ops.write_barrier(ops.context) == 0 && io.barriers == 1u,
          "forward barrier");
    io.fail = 7;
    observed = 123u;
    check(ops.read32(ops.context, 0u, &observed) != 0 && observed == 123u,
          "failed read keeps prior value even if hook wrote");
    check(ops.write32(ops.context, 0xcu, 1u) == 7 &&
          ops.write_barrier(ops.context) == 7, "propagate ambiguous IO failures");
    io.fail = 0;
    bad = context;
    bad.base += 4u;
    check(zn_native_platform_mmio_xilinx_ops_v1(&ops, &bad) != 0 &&
          ops.context == &context, "reject wrong base without replacing binding");
    bad = context;
    bad.bytes -= 4u;
    check(zn_native_platform_mmio_xilinx_ops_v1(&ops, &bad) != 0,
          "reject wrong span");
    bad = context;
    bad.host_read32 = NULL;
    check(zn_native_platform_mmio_xilinx_ops_v1(&ops, &bad) != 0,
          "reject missing host read");
    bad = context;
    bad.host_write32 = NULL;
    check(zn_native_platform_mmio_xilinx_ops_v1(&ops, &bad) != 0,
          "reject missing host write");
    bad = context;
    bad.host_barrier = NULL;
    check(zn_native_platform_mmio_xilinx_ops_v1(&ops, &bad) != 0,
          "reject missing host barrier");
    check(zn_native_platform_mmio_xilinx_ops_v1(NULL, &context) != 0 &&
          zn_native_platform_mmio_xilinx_ops_v1(&ops, NULL) != 0, "reject null binding");
    context.base = 0xfffff000u;
    check(ops.read32(ops.context, 0u, &observed) != 0 &&
          ops.write32(ops.context, 0xcu, 1u) != 0 &&
          ops.write_barrier(ops.context) != 0, "revalidate context on every callback");
    if (failures != 0u)
        return 1;
    (void)printf("NATIVE_PLATFORM_MMIO_XILINX_V1_PASS checks=%u read_registers=17 write_registers=28 board_access=0\n", checks);
    return 0;
}
