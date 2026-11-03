#define Z100_ACP_ISOLATED_DIAGNOSTIC_BUILD 1
#include "native_pool_command_v1.h"
#include "native_conv_pool_mmio_v1.h"
#include "native_platform_mmio_xilinx_v1.h"
#include "acp_cache_policy_v1.h"

#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"

#include <stdint.h>
#include "acp_pool_oracle_v1.h"
#include "acp_dirty_smoke_diag_v1.h"

#if !defined(Z100_ACP_ISOLATED_DIAGNOSTIC_BUILD)
#error Build only in an isolated diagnostic firmware image
#endif
#if !defined(__ARM_ARCH_7A__) || !defined(ZN_NPMMIO_V1_USE_XILINX_BSP) || \
    defined(ZN_NPMMIO_V1_HOST_MODEL)
#error This smoke is for a Cortex-A9 board build using the Xilinx MMIO adapter
#endif

enum {
    ZN_ACP_SMOKE_EPOCH = 37000u,
    ZN_ACP_SMOKE_CASES = ZN_ACP_DIRTY_DIAG_CASES,
    ZN_ACP_SMOKE_DIAG_SLOT_BYTES = 0x80000u,
    ZN_ACP_SMOKE_DIAG_REGION_BYTES = 0x100000u,
    ZN_ACP_SMOKE_ARENA_BYTES = 5201920u,
    ZN_ACP_SMOKE_PARAMETER_BYTES = 3122432u,
    ZN_ACP_SMOKE_DIRECTORY_BYTES = 5568u,
    ZN_ACP_SMOKE_SCRATCH_BYTES = 1228800u,
    ZN_ACP_SMOKE_HEADS_BYTES = 613248u,
    ZN_ACP_SMOKE_POLL_BUDGET = 1000000u,
    ZN_ACP_SMOKE_EVICTION_LINE_BYTES = 32u
};

#define ZN_ACP_SMOKE_ARENA_BASE        UINT32_C(0x10000000)
#define ZN_ACP_SMOKE_DIAG_REGION_BASE  UINT32_C(0x18000000)
#define ZN_ACP_SMOKE_SOURCE_BASE       UINT32_C(0x18000000)
#define ZN_ACP_SMOKE_DESTINATION_BASE  UINT32_C(0x18080000)
#define ZN_ACP_SMOKE_PARAMETER_BASE    UINT32_C(0x20000000)
#define ZN_ACP_SMOKE_DIRECTORY_BASE    UINT32_C(0x21000000)
#define ZN_ACP_SMOKE_SCRATCH_BASE     UINT32_C(0x22000000)
#define ZN_ACP_SMOKE_PRESSURE_BASE    UINT32_C(0x18200000)
#define ZN_ACP_SMOKE_PARAMETER_END    UINT32_C(0x202FA500)
#define ZN_ACP_SMOKE_HEADS_BASE       UINT32_C(0x24000000)
#define ZN_ACP_SMOKE_SCU_BASE         UINT32_C(0xF8F00000)
#define ZN_ACP_SMOKE_L2_BASE          UINT32_C(0xF8F02000)
#define ZN_ACP_SMOKE_L2_CONTROL       UINT32_C(0x100)
#define ZN_ACP_SMOKE_L2_AUX_CONTROL  UINT32_C(0x104)
#define ZN_ACP_SMOKE_L2_TAG_RAM       UINT32_C(0x108)
#define ZN_ACP_SMOKE_L2_DATA_RAM      UINT32_C(0x10C)
#define ZN_ACP_SMOKE_SECTION_MASK     UINT32_C(0xFFF00000)
#define ZN_ACP_SMOKE_SECTION_ATTR     UINT32_C(0x000FFFFF)
#define ZN_ACP_SMOKE_DDR_ATTRIBUTES   UINT32_C(0x00015DE6)
#define ZN_ACP_SMOKE_PL_ATTRIBUTES    UINT32_C(0x00000C02)
#define ZN_ACP_SMOKE_DEVICE_ATTRIBUTES UINT32_C(0x00000C06)
#define ZN_ACP_SMOKE_EXPECTED_L2_AUX  UINT32_C(0x72360000)
#define ZN_ACP_SMOKE_SENTINEL         UINT8_C(0x35)
#define ZN_ACP_SMOKE_DIRTY_SENTINEL   UINT8_C(0xC7)
#define ZN_ACP_SMOKE_L1_SUPERSECTION UINT32_C(0x00040000)

_Static_assert(ZN_ACP_SMOKE_EPOCH == 37000u, "dirty smoke epoch is reserved");
_Static_assert(ZN_ACP_SMOKE_CASES == 6u, "dirty smoke preserves six cases");
_Static_assert(ZN_ACP_SMOKE_SOURCE_BASE + ZN_ACP_SMOKE_DIAG_SLOT_BYTES ==
                   ZN_ACP_SMOKE_DESTINATION_BASE,
               "diagnostic source and destination slots are adjacent");
_Static_assert(ZN_ACP_SMOKE_DESTINATION_BASE + ZN_ACP_SMOKE_DIAG_SLOT_BYTES ==
                   ZN_ACP_SMOKE_DIAG_REGION_BASE + ZN_ACP_SMOKE_DIAG_REGION_BYTES,
               "diagnostic slots fill only their isolated 1 MiB region");
_Static_assert(ZN_ACP_SMOKE_DIAG_REGION_BASE + ZN_ACP_SMOKE_DIAG_REGION_BYTES <=
                   ZN_ACP_SMOKE_PRESSURE_BASE,
               "pressure area does not overlap source/destination slots");

_Alignas(64) static volatile ZnAcpDirtySmokeDiagnostic zn_acp_smoke_diagnostic;

static void zn_acp_smoke_flush_diagnostic(void)
{
    Xil_DCacheFlushRange((INTPTR)(uintptr_t)&zn_acp_smoke_diagnostic,
                         (uint32_t)sizeof zn_acp_smoke_diagnostic);
    __asm__ volatile("dsb sy" ::: "memory");
}

static volatile ZnAcpDirtySmokeCaseDiagnostic *
zn_acp_smoke_case_diagnostic(uint32_t test_index)
{
    return &zn_acp_smoke_diagnostic.cases[test_index];
}

static void zn_acp_smoke_capture_driver(
    volatile ZnAcpDirtySmokeCaseDiagnostic *record,
    const ZnNativeConvDriverV2 *driver,
    ZnNativeConvDriverCodeV2 code,
    int software_timeout)
{
    uint32_t ownership;

    record->driver_code = (uint32_t)code;
    record->status = driver->last_status;
    record->bridge_error = driver->last_bridge_error;
    record->backend_fault_code = driver->last_backend_fault_code;
    record->ownership_flags |= ZN_ACP_DIRTY_DIAG_OWN_TERMINAL_SAMPLED;
    ownership = zn_native_conv_driver_ownership_held_v2(driver);
    if (ownership != 0u)
        record->ownership_flags |= ZN_ACP_DIRTY_DIAG_OWN_TERMINAL_HELD;
    record->drain_flags = ZN_ACP_DIRTY_DIAG_DRAIN_SAMPLED;
    if (driver->last_status & ZN_NC_STATUS_NEEDS_DRAIN)
        record->drain_flags |= ZN_ACP_DIRTY_DIAG_NEEDS_DRAIN;
    if (driver->last_status & ZN_NC_STATUS_DRAIN_COMPLETE)
        record->drain_flags |= ZN_ACP_DIRTY_DIAG_DRAIN_COMPLETE;
    if (software_timeout)
        record->ownership_flags |= ZN_ACP_DIRTY_DIAG_SOFTWARE_TIMEOUT;
    if ((code == ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY ||
         code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY) &&
        driver->result_verified) {
        record->request_cookie = driver->result.request_cookie;
        record->result_epoch = driver->result.epoch;
        record->event = driver->result.event;
        record->committed_tiles = driver->result.committed_tiles;
    }
}

static void zn_acp_smoke_capture_post_ack(
    volatile ZnAcpDirtySmokeCaseDiagnostic *record,
    const ZnNativeConvDriverV2 *driver)
{
    record->ownership_flags |= ZN_ACP_DIRTY_DIAG_OWN_POST_ACK_SAMPLED;
    if (zn_native_conv_driver_ownership_held_v2(driver) != 0u)
        record->ownership_flags |= ZN_ACP_DIRTY_DIAG_OWN_POST_ACK_HELD;
}

static int zn_acp_smoke_fail_case(uint32_t test_index,
                                  uint32_t stage,
                                  uint32_t failure_result)
{
    zn_acp_dirty_diag_fail_case(&zn_acp_smoke_diagnostic, test_index,
                                stage, failure_result);
    zn_acp_smoke_flush_diagnostic();
    return -1;
}

extern const volatile uint32_t MMUTable[];

typedef struct ZnAcpSmokeRegisters {
    uint32_t actlr;
    uint32_t sctlr;
    uint32_t clidr;
    uint32_t ttbr0;
    uint32_t ttbr1;
    uint32_t ttbcr;
    uint32_t dacr;
    uint32_t scu_control;
    uint32_t scu_configuration;
    uint32_t l2_control;
    uint32_t l2_aux_control;
    uint32_t l2_tag_ram_control;
    uint32_t l2_data_ram_control;
} ZnAcpSmokeRegisters;

static void zn_acp_smoke_read_cp15(ZnAcpSmokeRegisters *r)
{
    __asm__ volatile("mrc p15, 0, %0, c1, c0, 1" : "=r"(r->actlr));
    __asm__ volatile("mrc p15, 0, %0, c1, c0, 0" : "=r"(r->sctlr));
    __asm__ volatile("mrc p15, 1, %0, c0, c0, 1" : "=r"(r->clidr));
    __asm__ volatile("mrc p15, 0, %0, c2, c0, 0" : "=r"(r->ttbr0));
    __asm__ volatile("mrc p15, 0, %0, c2, c0, 1" : "=r"(r->ttbr1));
    __asm__ volatile("mrc p15, 0, %0, c2, c0, 2" : "=r"(r->ttbcr));
    __asm__ volatile("mrc p15, 0, %0, c3, c0, 0" : "=r"(r->dacr));
    __asm__ volatile("isb" ::: "memory");
}

static int zn_acp_smoke_read_registers(ZnAcpSmokeRegisters *r)
{
    if (!r)
        return -1;
    zn_acp_smoke_read_cp15(r);
    r->scu_control = Xil_In32(ZN_ACP_SMOKE_SCU_BASE);
    r->scu_configuration = Xil_In32(ZN_ACP_SMOKE_SCU_BASE + 4u);
    r->l2_control = Xil_In32(ZN_ACP_SMOKE_L2_BASE + ZN_ACP_SMOKE_L2_CONTROL);
    r->l2_aux_control = Xil_In32(ZN_ACP_SMOKE_L2_BASE + ZN_ACP_SMOKE_L2_AUX_CONTROL);
    r->l2_tag_ram_control = Xil_In32(ZN_ACP_SMOKE_L2_BASE + ZN_ACP_SMOKE_L2_TAG_RAM);
    r->l2_data_ram_control = Xil_In32(ZN_ACP_SMOKE_L2_BASE + ZN_ACP_SMOKE_L2_DATA_RAM);
    return 0;
}

typedef struct ZnAcpSmokeRegion {
    uint32_t base;
    uint32_t bytes;
} ZnAcpSmokeRegion;

static const ZnAcpSmokeRegion zn_acp_smoke_coherent_regions[] = {
    {ZN_ACP_SMOKE_ARENA_BASE, ZN_ACP_SMOKE_ARENA_BYTES},
    {ZN_ACP_SMOKE_DIAG_REGION_BASE, ZN_ACP_SMOKE_DIAG_REGION_BYTES},
    {ZN_ACP_SMOKE_PARAMETER_BASE, ZN_ACP_SMOKE_PARAMETER_BYTES},
    {ZN_ACP_SMOKE_DIRECTORY_BASE, ZN_ACP_SMOKE_DIRECTORY_BYTES},
    {ZN_ACP_SMOKE_SCRATCH_BASE, ZN_ACP_SMOKE_SCRATCH_BYTES},
    {ZN_ACP_SMOKE_PRESSURE_BASE, ZN_ACP_SMOKE_SCRATCH_BYTES},
    {ZN_ACP_SMOKE_HEADS_BASE, ZN_ACP_SMOKE_HEADS_BYTES}
};

static int zn_acp_smoke_is_coherent_section(uint32_t physical_base)
{
    uint32_t i;

    for (i = 0; i < sizeof zn_acp_smoke_coherent_regions /
                    sizeof zn_acp_smoke_coherent_regions[0]; ++i) {
        uint32_t first = zn_acp_smoke_coherent_regions[i].base & ZN_ACP_SMOKE_SECTION_MASK;
        uint32_t last = (zn_acp_smoke_coherent_regions[i].base +
                         zn_acp_smoke_coherent_regions[i].bytes - 1u) &
                        ZN_ACP_SMOKE_SECTION_MASK;
        if (physical_base >= first && physical_base <= last)
            return 1;
    }
    return 0;
}

static int zn_acp_smoke_check_section(uint32_t virtual_base, uint32_t attributes)
{
    uint32_t descriptor = MMUTable[virtual_base >> 20];

    if ((descriptor & 3u) != 2u ||
        (descriptor & ZN_ACP_SMOKE_L1_SUPERSECTION) != 0u ||
        (descriptor & ZN_ACP_SMOKE_SECTION_MASK) != virtual_base ||
        (descriptor & ZN_ACP_SMOKE_SECTION_ATTR) != attributes) {
        xil_printf("ACP_SMOKE MMU section fail va=0x%x descriptor=0x%x\r\n",
                   virtual_base, descriptor);
        return -1;
    }
    return 0;
}

static int zn_acp_smoke_check_no_aliases(void)
{
    uint32_t index;

    for (index = 0; index < 4096u; ++index) {
        uint32_t descriptor = MMUTable[index];
        uint32_t type = descriptor & 3u;

        if (type == 1u || type == 3u) {
            xil_printf("ACP_SMOKE MMU opaque L1 entry index=0x%x descriptor=0x%x\r\n",
                       index, descriptor);
            return -1;
        }
        if (type == 2u) {
            if ((descriptor & ZN_ACP_SMOKE_L1_SUPERSECTION) != 0u) {
                xil_printf("ACP_SMOKE MMU supersection unsupported index=0x%x descriptor=0x%x\r\n",
                           index, descriptor);
                return -1;
            }
            uint32_t physical_base = descriptor & ZN_ACP_SMOKE_SECTION_MASK;
            if (zn_acp_smoke_is_coherent_section(physical_base) &&
                index != (physical_base >> 20)) {
                xil_printf("ACP_SMOKE MMU alias va_section=0x%x pa_section=0x%x\r\n",
                           index << 20, physical_base);
                return -1;
            }
        }
    }
    return 0;
}

static int zn_acp_smoke_check_platform(void)
{
    ZnAcpSmokeRegisters r;
    uint32_t table_address = (uint32_t)(uintptr_t)MMUTable;
    uint32_t i;
    int good = 1;

    if (zn_acp_smoke_read_registers(&r) != 0)
        return -1;

    xil_printf("ACP_SMOKE ACTLR=0x%x SCTLR=0x%x CLIDR=0x%x TTBR0=0x%x TTBR1=0x%x TTBCR=0x%x DACR=0x%x\r\n",
               r.actlr, r.sctlr, r.clidr, r.ttbr0, r.ttbr1, r.ttbcr, r.dacr);
    xil_printf("ACP_SMOKE SCU_CTRL=0x%x SCU_CFG=0x%x L2_CTRL=0x%x L2_AUX=0x%x TAG=0x%x DATA=0x%x\r\n",
               r.scu_control, r.scu_configuration, r.l2_control, r.l2_aux_control,
               r.l2_tag_ram_control, r.l2_data_ram_control);
    xil_printf("ACP_SMOKE MMUTable=0x%x\r\n", table_address);

    if ((r.actlr & (UINT32_C(1) << 6)) == 0u ||
        (r.sctlr & (UINT32_C(1) << 0)) == 0u ||
        (r.sctlr & (UINT32_C(1) << 2)) == 0u ||
        (r.sctlr & (UINT32_C(1) << 25)) != 0u ||
        (r.sctlr & (UINT32_C(1) << 28)) != 0u ||
        ((r.clidr & 7u) < 2u || (r.clidr & 7u) > 4u) ||
        (r.scu_control & 1u) == 0u ||
        (r.l2_control & 1u) == 0u ||
        r.l2_aux_control != ZN_ACP_SMOKE_EXPECTED_L2_AUX ||
        (r.ttbcr & 7u) != 0u ||
        (r.ttbcr & (UINT32_C(1) << 4)) != 0u ||
        (r.ttbcr & (UINT32_C(1) << 31)) != 0u ||
        (r.ttbr0 & UINT32_C(0xFFFFC000)) !=
            (table_address & UINT32_C(0xFFFFC000)) ||
        ((r.dacr >> 30) & 3u) != 3u ||
        (table_address & UINT32_C(0x3FFF)) != 0u) {
        good = 0;
        xil_printf("ACP_SMOKE CPU/SCU/L2/MMU state is not qualified\r\n");
    }

    for (i = 0; i < sizeof zn_acp_smoke_coherent_regions /
                    sizeof zn_acp_smoke_coherent_regions[0]; ++i) {
        uint32_t section = zn_acp_smoke_coherent_regions[i].base &
                           ZN_ACP_SMOKE_SECTION_MASK;
        uint32_t last = (zn_acp_smoke_coherent_regions[i].base +
                         zn_acp_smoke_coherent_regions[i].bytes - 1u) &
                        ZN_ACP_SMOKE_SECTION_MASK;
        for (; section <= last; section += UINT32_C(0x00100000)) {
            if (zn_acp_smoke_check_section(section, ZN_ACP_SMOKE_DDR_ATTRIBUTES) != 0)
                good = 0;
        }
    }
    if (zn_acp_smoke_check_section(ZN_NPMMIO_V1_BASE & ZN_ACP_SMOKE_SECTION_MASK,
                                   ZN_ACP_SMOKE_PL_ATTRIBUTES) != 0 ||
        zn_acp_smoke_check_section(ZN_ACP_SMOKE_SCU_BASE & ZN_ACP_SMOKE_SECTION_MASK,
                                   ZN_ACP_SMOKE_DEVICE_ATTRIBUTES) != 0)
        good = 0;
    if (zn_acp_smoke_check_no_aliases() != 0)
        good = 0;

    return good ? 0 : -1;
}

int z100_acp_live_coherence_state_check_v1(void)
{
    return zn_acp_smoke_check_platform() == 0 ? 1 : 0;
}

static void zn_acp_smoke_build_command(uint32_t test_index,
                                       ZnNativeConvCommand *command)
{
    uint32_t end;

    *command = (ZnNativeConvCommand){0};
    command->request_cookie = UINT32_C(100000000) + test_index;
    command->epoch = ZN_ACP_SMOKE_EPOCH;
    command->event = 70u;
    command->model_crc32 = ZN_NATIVE_CONV_MMIO_MODEL_CRC32;
    command->job_base = UINT32_C(50000) + test_index;
    command->token_base = UINT32_C(1000000) + test_index;
    command->tag_base = UINT32_C(100000000) + test_index;
    command->flags = ZN_NC_SHADOW_SOURCE_LEASE_VALID |
                     ZN_NC_SHADOW_DEST_RESERVATION_VALID;
    command->source_base = ZN_ACP_SMOKE_SOURCE_BASE;
    command->source_generation = UINT32_C(33000) + test_index;
    command->source_lease_region_begin = ZN_ACP_SMOKE_SOURCE_BASE;
    end = ZN_ACP_SMOKE_SOURCE_BASE + ZN_ACP_SMOKE_DIAG_SLOT_BYTES;
    command->source_lease_region_end.low = end;
    command->destination_base = ZN_ACP_SMOKE_DESTINATION_BASE;
    command->destination_generation = UINT32_C(34000) + test_index;
    command->destination_reservation_region_begin = ZN_ACP_SMOKE_DESTINATION_BASE;
    end = ZN_ACP_SMOKE_DESTINATION_BASE + ZN_ACP_SMOKE_DIAG_SLOT_BYTES;
    command->destination_reservation_region_end.low = end;
    command->parameter_directory_base = ZN_ACP_SMOKE_DIRECTORY_BASE;
    command->parameter_count = ZN_NATIVE_CONV_MMIO_PARAMETER_COUNT;
    command->parameter_payload_begin = ZN_ACP_SMOKE_PARAMETER_BASE;
    command->parameter_payload_end.low = ZN_ACP_SMOKE_PARAMETER_END;
    command->load_timeout_cycles = UINT32_C(100000000);
    command->parameter_timeout_cycles = UINT32_C(100000000);
    command->write_timeout_cycles = UINT32_C(100000000);
    command->preaccept_timeout_cycles = UINT32_C(100000000);
}

static void zn_acp_smoke_fill_buffers(uint8_t input_value,
                                      volatile uint8_t *source,
                                      volatile uint8_t *destination)
{
    uint32_t offset;

    for (offset = 0; offset < ZN_ACP_SMOKE_PHYSICAL_BYTES; ++offset) {
        uint32_t word = offset / ZN_ACP_SMOKE_BUS_WORD_BYTES;
        uint32_t byte_in_word = offset % ZN_ACP_SMOKE_BUS_WORD_BYTES;
        uint32_t in_group = word % (ZN_ACP_SMOKE_HEIGHT *
                                    ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW);
        uint32_t x_word = (in_group % ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW) /
                          ZN_ACP_SMOKE_GROUP_SUBGROUPS;
        uint32_t x = x_word * 16u + byte_in_word % 16u;

        source[offset] = x < ZN_ACP_SMOKE_WIDTH ? input_value : 0u;
        destination[offset] = ZN_ACP_SMOKE_SENTINEL;
    }
}

static void zn_acp_smoke_fill_guard(volatile uint8_t *guard, uint8_t value)
{
    uint32_t offset;
    for (offset = 0; offset < ZN_ACP_SMOKE_BUS_WORD_BYTES; ++offset)
        guard[offset] = value;
}

static const uint32_t zn_acp_smoke_destination_probe_words[] = {
    16u, 32u, 48u, 64u, 80u, 96u, 112u
};

typedef enum ZnAcpSmokeCacheState {
    ZN_ACP_SMOKE_DIRTY_HOT = 0,
    ZN_ACP_SMOKE_CLEAN_HOT = 1,
    ZN_ACP_SMOKE_COLD = 2
} ZnAcpSmokeCacheState;

static void zn_acp_smoke_touch_probe_lines(volatile uint8_t *source,
                                            volatile uint8_t *destination,
                                            volatile uint8_t *guard_before,
                                            volatile uint8_t *guard_after)
{
    uint32_t i;
    uint32_t byte;

    for (i = 0; i < sizeof zn_acp_smoke_probe_words / sizeof zn_acp_smoke_probe_words[0]; ++i) {
        uint32_t source_offset = zn_acp_smoke_probe_words[i] * ZN_ACP_SMOKE_BUS_WORD_BYTES;
        source[source_offset] = UINT8_C(0x7F);
    }
    for (i = 0; i < sizeof zn_acp_smoke_destination_probe_words /
                    sizeof zn_acp_smoke_destination_probe_words[0]; ++i) {
        uint32_t destination_offset = zn_acp_smoke_destination_probe_words[i] *
                                      ZN_ACP_SMOKE_BUS_WORD_BYTES;
        for (byte = 0; byte < ZN_ACP_SMOKE_BUS_WORD_BYTES; ++byte) {
            destination[destination_offset + byte] = ZN_ACP_SMOKE_DIRTY_SENTINEL;
        }
    }
    zn_acp_smoke_fill_guard(guard_before, ZN_ACP_SMOKE_DIRTY_GUARD_BEFORE);
    zn_acp_smoke_fill_guard(guard_after, ZN_ACP_SMOKE_DIRTY_GUARD_AFTER);
}

static int zn_acp_smoke_read_probe_lines(int8_t input_value,
                                         volatile const uint8_t *source,
                                         volatile const uint8_t *destination)
{
    uint32_t i;
    uint32_t byte;

    for (i = 0; i < sizeof zn_acp_smoke_probe_words / sizeof zn_acp_smoke_probe_words[0]; ++i) {
        uint32_t source_offset = zn_acp_smoke_probe_words[i] * ZN_ACP_SMOKE_BUS_WORD_BYTES;
        for (byte = 0; byte < ZN_ACP_SMOKE_BUS_WORD_BYTES; ++byte) {
            uint32_t offset = source_offset + byte;
            if (source[offset] != zn_acp_smoke_expected_source_byte(
                                     offset, (uint8_t)input_value))
                return -1;
        }
    }
    for (i = 0; i < sizeof zn_acp_smoke_destination_probe_words /
                    sizeof zn_acp_smoke_destination_probe_words[0]; ++i) {
        uint32_t destination_offset = zn_acp_smoke_destination_probe_words[i] *
                                     ZN_ACP_SMOKE_BUS_WORD_BYTES;
        for (byte = 0; byte < ZN_ACP_SMOKE_BUS_WORD_BYTES; ++byte) {
            if (destination[destination_offset + byte] != ZN_ACP_SMOKE_DIRTY_SENTINEL)
                return -1;
        }
    }
    return 0;
}

static void zn_acp_smoke_flush_test_ranges(volatile uint8_t *source,
                                            volatile uint8_t *destination,
                                            volatile uint8_t *guard_before,
                                            volatile uint8_t *guard_after)
{
    Xil_DCacheFlushRange((INTPTR)(uintptr_t)source, ZN_ACP_SMOKE_PHYSICAL_BYTES);
    Xil_DCacheFlushRange((INTPTR)(uintptr_t)destination, ZN_ACP_SMOKE_PHYSICAL_BYTES);
    Xil_DCacheFlushRange((INTPTR)(uintptr_t)guard_before, ZN_ACP_SMOKE_BUS_WORD_BYTES);
    Xil_DCacheFlushRange((INTPTR)(uintptr_t)guard_after, ZN_ACP_SMOKE_BUS_WORD_BYTES);
    __asm__ volatile("dsb sy" ::: "memory");
}

static int zn_acp_smoke_prepare_cache_state(ZnAcpSmokeCacheState state,
                                             int8_t input_value,
                                             volatile uint8_t *source,
                                             volatile uint8_t *destination,
                                             volatile uint8_t *guard_before,
                                             volatile uint8_t *guard_after)
{
    if (state != ZN_ACP_SMOKE_DIRTY_HOT &&
        state != ZN_ACP_SMOKE_CLEAN_HOT && state != ZN_ACP_SMOKE_COLD)
        return -1;

    zn_acp_smoke_touch_probe_lines(source, destination, guard_before, guard_after);
    if (state == ZN_ACP_SMOKE_DIRTY_HOT) {
        if (zn_acp_smoke_read_probe_lines(input_value, source, destination) != 0 ||
            zn_acp_smoke_verify_guard(
                guard_before, ZN_ACP_SMOKE_DIRTY_GUARD_BEFORE) != 0 ||
            zn_acp_smoke_verify_guard(
                guard_after, ZN_ACP_SMOKE_DIRTY_GUARD_AFTER) != 0)
            return -1;
        return 0;
    }

    zn_acp_smoke_flush_test_ranges(source, destination, guard_before, guard_after);

    if (state == ZN_ACP_SMOKE_CLEAN_HOT) {
        if (zn_acp_smoke_read_probe_lines(input_value, source, destination) != 0 ||
            zn_acp_smoke_verify_guard(
                guard_before, ZN_ACP_SMOKE_DIRTY_GUARD_BEFORE) != 0 ||
            zn_acp_smoke_verify_guard(
                guard_after, ZN_ACP_SMOKE_DIRTY_GUARD_AFTER) != 0)
            return -1;
        return 0;
    }
    return state == ZN_ACP_SMOKE_COLD ? 0 : -1;
}

static int zn_acp_smoke_verify_probe_lines(volatile const uint8_t *destination,
                                            int8_t input_value,
                                            uint32_t *bad_offset)
{
    uint32_t row;
    uint32_t byte;

    for (row = 0; row < ZN_ACP_SMOKE_PROBE_OUTPUT_ROWS; ++row) {
        uint32_t word = row * ZN_ACP_SMOKE_WORDS_PER_GROUP_ROW;
        uint32_t base = word * ZN_ACP_SMOKE_BUS_WORD_BYTES;
        for (byte = 0; byte < ZN_ACP_SMOKE_BUS_WORD_BYTES; ++byte) {
            uint32_t offset = base + byte;
            if (destination[offset] != zn_acp_smoke_expected_byte(offset, input_value)) {
                *bad_offset = offset;
                return -1;
            }
        }
    }
    return 0;
}

static int zn_acp_smoke_verify_output(volatile const uint8_t *destination,
                                       int8_t input_value,
                                       uint32_t *bad_offset)
{
    uint32_t offset;

    for (offset = 0; offset < ZN_ACP_SMOKE_PHYSICAL_BYTES; ++offset) {
        if (destination[offset] != zn_acp_smoke_expected_byte(offset, input_value)) {
            *bad_offset = offset;
            return -1;
        }
    }
    return 0;
}

static void zn_acp_smoke_apply_eviction_pressure(volatile uint8_t *scratch)
{
    uint32_t pass;
    uint32_t offset;
    uint32_t byte;

    /* Scratch passes create cache pressure; they do not guarantee eviction. */
    for (pass = 0; pass < 2u; ++pass) {
        for (offset = 0; offset < ZN_ACP_SMOKE_SCRATCH_BYTES;
             offset += ZN_ACP_SMOKE_EVICTION_LINE_BYTES) {
            for (byte = 0; byte < ZN_ACP_SMOKE_EVICTION_LINE_BYTES; ++byte)
                scratch[offset + byte] = (uint8_t)(offset / ZN_ACP_SMOKE_EVICTION_LINE_BYTES +
                                                   byte + pass * 37u);
        }
        __asm__ volatile("dsb sy" ::: "memory");
    }
}

static int zn_acp_smoke_ack(
    ZnNativeConvDriverV2 *driver,
    volatile ZnAcpDirtySmokeCaseDiagnostic *record)
{
    ZnNativeConvDriverCodeV2 code = zn_native_conv_driver_ack_v2(driver);
    record->ack_code = (uint32_t)code;
    zn_acp_smoke_capture_post_ack(record, driver);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK ||
        zn_native_conv_driver_ownership_held_v2(driver) != 0u) {
        xil_printf("ACP_SMOKE ACK failed code=%d state=%d ownership=%d\r\n",
                   (int)code, (int)driver->state,
                   (int)zn_native_conv_driver_ownership_held_v2(driver));
        return -1;
    }
    return 0;
}

static ZnNativeConvDriverCodeV2
zn_acp_smoke_wait_terminal(ZnNativeConvDriverV2 *driver, int *software_timeout)
{
    uint32_t poll;
    ZnNativeConvDriverCodeV2 code = ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS;

    *software_timeout = 0;
    for (poll = 0; poll < ZN_ACP_SMOKE_POLL_BUDGET; ++poll) {
        code = zn_native_conv_driver_poll_v2(driver);
        if (code != ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS)
            return code;
    }

    *software_timeout = 1;
    code = zn_native_conv_driver_timeout_v2(driver);
    for (poll = 0; poll < ZN_ACP_SMOKE_POLL_BUDGET; ++poll) {
        if (code != ZN_NATIVE_CONV_DRIVER_V2_IN_PROGRESS)
            return code;
        code = zn_native_conv_driver_poll_v2(driver);
    }
    return code;
}

static int zn_acp_smoke_result_matches(const ZnNativeConvDriverV2 *driver,
                                       const ZnNativeConvCommand *command)
{
    const ZnNativeConvResultV2 *result = &driver->result;
    return driver->result_verified &&
           result->request_cookie == command->request_cookie &&
           result->epoch == command->epoch &&
           result->event == command->event &&
           result->model_crc32 == command->model_crc32 &&
           result->job_base == command->job_base &&
           result->token_base == command->token_base &&
           result->tag_base == command->tag_base &&
           result->destination_generation == command->destination_generation &&
           result->source_generation == command->source_generation &&
           result->committed_tiles == 1u;
}

static int zn_acp_smoke_run_case(uint32_t test_index, int8_t input_value,
                                 ZnAcpSmokeCacheState cache_state,
                                 ZnNativeConvDriverV2 *driver)
{
    ZnNativeConvCommand command;
    volatile ZnAcpDirtySmokeCaseDiagnostic *record =
        zn_acp_smoke_case_diagnostic(test_index);
    volatile uint8_t *source = (volatile uint8_t *)(uintptr_t)ZN_ACP_SMOKE_SOURCE_BASE;
    volatile uint8_t *destination = (volatile uint8_t *)(uintptr_t)ZN_ACP_SMOKE_DESTINATION_BASE;
    volatile uint8_t *guard_before = destination - ZN_ACP_SMOKE_BUS_WORD_BYTES;
    volatile uint8_t *guard_after = destination + ZN_ACP_SMOKE_PHYSICAL_BYTES;
    volatile uint8_t *scratch = (volatile uint8_t *)(uintptr_t)ZN_ACP_SMOKE_PRESSURE_BASE;
    int8_t value = input_value;
    uint32_t bad_offset = ZN_ACP_DIRTY_DIAG_NONE;
    ZnNativeConvDriverCodeV2 code;
    int software_timeout;
    int result_ok;
    int immediate_ok;
    int ack_ok;
    int ownership_released;
    int guard_before_ok;
    int guard_after_ok;
    int full_output_ok;

    if (!zn_acp_dirty_diag_begin_case(&zn_acp_smoke_diagnostic, test_index)) {
        zn_acp_dirty_diag_fail_preflight(
            &zn_acp_smoke_diagnostic, ZN_ACP_DIRTY_DIAG_FAIL_DIAGNOSTIC);
        zn_acp_smoke_flush_diagnostic();
        return -1;
    }

    zn_acp_smoke_build_command(test_index, &command);
    if (!zn_native_pool_command_valid_v1(&command)) {
        xil_printf("ACP_SMOKE command validation failed case=%d\r\n", (int)test_index);
        return zn_acp_smoke_fail_case(test_index,
                                      ZN_ACP_DIRTY_DIAG_STAGE_BUFFER_INIT,
                                      ZN_ACP_DIRTY_DIAG_FAIL_COMMAND);
    }

    xil_printf("ACP_SMOKE prepare case=%d epoch=%d state=%d input=0x%x\r\n",
               (int)test_index, (int)ZN_ACP_SMOKE_EPOCH, (int)cache_state,
               (unsigned)(uint8_t)value);
    zn_acp_smoke_fill_buffers(value, source, destination);
    zn_acp_smoke_fill_guard(guard_before, ZN_ACP_SMOKE_GUARD_BACKING_BEFORE);
    zn_acp_smoke_fill_guard(guard_after, ZN_ACP_SMOKE_GUARD_BACKING_AFTER);
    guard_before_ok = zn_acp_smoke_verify_guard(
        guard_before, ZN_ACP_SMOKE_GUARD_BACKING_BEFORE) == 0;
    guard_after_ok = zn_acp_smoke_verify_guard(
        guard_after, ZN_ACP_SMOKE_GUARD_BACKING_AFTER) == 0;
    if (guard_before_ok)
        record->guard_flags |= ZN_ACP_DIRTY_DIAG_GUARD_INITIAL_BEFORE;
    if (guard_after_ok)
        record->guard_flags |= ZN_ACP_DIRTY_DIAG_GUARD_INITIAL_AFTER;
    if (!guard_before_ok || !guard_after_ok) {
        xil_printf("ACP_SMOKE guard initialization failed\r\n");
        return zn_acp_smoke_fail_case(test_index,
                                      ZN_ACP_DIRTY_DIAG_STAGE_BUFFER_INIT,
                                      ZN_ACP_DIRTY_DIAG_FAIL_INITIAL_GUARD);
    }

    zn_acp_smoke_flush_test_ranges(source, destination, guard_before, guard_after);

    zn_acp_dirty_diag_set_stage(&zn_acp_smoke_diagnostic, test_index,
                                ZN_ACP_DIRTY_DIAG_STAGE_CACHE_PREPARED);
    if (zn_acp_smoke_prepare_cache_state(cache_state, value, source, destination,
                                         guard_before, guard_after) != 0) {
        xil_printf("ACP_SMOKE cache-state preparation failed case=%d state=%d\r\n",
                   (int)test_index, (int)cache_state);
        return zn_acp_smoke_fail_case(test_index,
                                      ZN_ACP_DIRTY_DIAG_STAGE_CACHE_PREPARED,
                                      ZN_ACP_DIRTY_DIAG_FAIL_CACHE_PREP);
    }
    if (cache_state != ZN_ACP_SMOKE_COLD)
        record->guard_flags |= ZN_ACP_DIRTY_DIAG_GUARD_PREP_CHECKED;
    __asm__ volatile("dmb sy" ::: "memory");
    code = zn_native_pool_driver_submit_v1(driver, &command);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_OK) {
        zn_acp_smoke_capture_driver(record, driver, code, 0);
        xil_printf("ACP_SMOKE submit failed code=%d state=%d ownership=%d\r\n",
                   (int)code, (int)driver->state,
                   (int)zn_native_conv_driver_ownership_held_v2(driver));
        return zn_acp_smoke_fail_case(test_index,
                                      ZN_ACP_DIRTY_DIAG_STAGE_SUBMITTED,
                                      ZN_ACP_DIRTY_DIAG_FAIL_SUBMIT);
    }
    zn_acp_dirty_diag_set_stage(&zn_acp_smoke_diagnostic, test_index,
                                ZN_ACP_DIRTY_DIAG_STAGE_SUBMITTED);

    code = zn_acp_smoke_wait_terminal(driver, &software_timeout);
    zn_acp_smoke_capture_driver(record, driver, code, software_timeout);
    zn_acp_dirty_diag_set_stage(&zn_acp_smoke_diagnostic, test_index,
                                ZN_ACP_DIRTY_DIAG_STAGE_TERMINAL);
    if (code != ZN_NATIVE_CONV_DRIVER_V2_SUCCESS_READY) {
        if (code == ZN_NATIVE_CONV_DRIVER_V2_FAULT_READY ||
            code == ZN_NATIVE_CONV_DRIVER_V2_LOCAL_ERROR_READY) {
            ack_ok = zn_acp_smoke_ack(driver, record) == 0;
            ownership_released =
                zn_native_conv_driver_ownership_held_v2(driver) == 0u;
            if (!ack_ok || !ownership_released) {
                xil_printf("ACP_SMOKE terminal ACK did not release case=%d\r\n",
                           (int)test_index);
                return zn_acp_smoke_fail_case(
                    test_index, ZN_ACP_DIRTY_DIAG_STAGE_ACKED,
                    ownership_released ? ZN_ACP_DIRTY_DIAG_FAIL_ACK :
                                         ZN_ACP_DIRTY_DIAG_FAIL_OWNERSHIP);
            }
        }
        xil_printf("ACP_SMOKE terminal failure code=%d state=%d ownership=%d timeout=%d\r\n",
                   (int)code, (int)driver->state,
                   (int)zn_native_conv_driver_ownership_held_v2(driver), software_timeout);
        return zn_acp_smoke_fail_case(
            test_index, ZN_ACP_DIRTY_DIAG_STAGE_TERMINAL,
            software_timeout ? ZN_ACP_DIRTY_DIAG_FAIL_TIMEOUT :
                               ZN_ACP_DIRTY_DIAG_FAIL_TERMINAL);
    }

    __asm__ volatile("dmb sy" ::: "memory");
    result_ok = zn_acp_smoke_result_matches(driver, &command);
    immediate_ok = zn_acp_smoke_verify_probe_lines(destination, value, &bad_offset) == 0;
    record->immediate_flags = ZN_ACP_DIRTY_DIAG_CHECKED |
        (immediate_ok ? ZN_ACP_DIRTY_DIAG_PASSED : 0u);
    if (!immediate_ok)
        record->bad_offset = bad_offset;
    zn_acp_dirty_diag_set_stage(&zn_acp_smoke_diagnostic, test_index,
                                ZN_ACP_DIRTY_DIAG_STAGE_RESULT_CHECKED);

    ack_ok = zn_acp_smoke_ack(driver, record) == 0;
    ownership_released = zn_native_conv_driver_ownership_held_v2(driver) == 0u;
    if (!ack_ok || !ownership_released) {
        return zn_acp_smoke_fail_case(
            test_index, ZN_ACP_DIRTY_DIAG_STAGE_ACKED,
            ownership_released ? ZN_ACP_DIRTY_DIAG_FAIL_ACK :
                                 ZN_ACP_DIRTY_DIAG_FAIL_OWNERSHIP);
    }
    zn_acp_dirty_diag_set_stage(&zn_acp_smoke_diagnostic, test_index,
                                ZN_ACP_DIRTY_DIAG_STAGE_ACKED);
    if (software_timeout || !result_ok || !immediate_ok) {
        xil_printf("ACP_SMOKE immediate/result check failed timeout=%d result=%d data=%d bad=0x%x\r\n",
                   software_timeout, result_ok, immediate_ok, bad_offset);
        return zn_acp_smoke_fail_case(
            test_index, ZN_ACP_DIRTY_DIAG_STAGE_RESULT_CHECKED,
            software_timeout ? ZN_ACP_DIRTY_DIAG_FAIL_TIMEOUT :
            (!result_ok ? ZN_ACP_DIRTY_DIAG_FAIL_METADATA :
                          ZN_ACP_DIRTY_DIAG_FAIL_IMMEDIATE));
    }

    zn_acp_smoke_apply_eviction_pressure(scratch);
    __asm__ volatile("dmb sy" ::: "memory");
    zn_acp_dirty_diag_set_stage(&zn_acp_smoke_diagnostic, test_index,
                                ZN_ACP_DIRTY_DIAG_STAGE_SCRATCH_CHECKED);
    full_output_ok = zn_acp_smoke_verify_output(destination, value,
                                                &bad_offset) == 0;
    record->full_output_flags = ZN_ACP_DIRTY_DIAG_CHECKED |
        (full_output_ok ? ZN_ACP_DIRTY_DIAG_PASSED : 0u);
    if (!full_output_ok) {
        record->bad_offset = bad_offset;
        xil_printf("ACP_SMOKE post-pressure data mismatch case=%d offset=0x%x got=0x%x expected=0x%x\r\n",
                   (int)test_index, bad_offset, destination[bad_offset],
                   zn_acp_smoke_expected_byte(bad_offset, value));
        return zn_acp_smoke_fail_case(
            test_index, ZN_ACP_DIRTY_DIAG_STAGE_FULL_OUTPUT_CHECKED,
            ZN_ACP_DIRTY_DIAG_FAIL_FULL_OUTPUT);
    }
    zn_acp_dirty_diag_set_stage(&zn_acp_smoke_diagnostic, test_index,
                                ZN_ACP_DIRTY_DIAG_STAGE_FULL_OUTPUT_CHECKED);
    guard_before_ok = zn_acp_smoke_verify_guard(
        guard_before, ZN_ACP_SMOKE_DIRTY_GUARD_BEFORE) == 0;
    guard_after_ok = zn_acp_smoke_verify_guard(
        guard_after, ZN_ACP_SMOKE_DIRTY_GUARD_AFTER) == 0;
    if (guard_before_ok)
        record->guard_flags |= ZN_ACP_DIRTY_DIAG_GUARD_FINAL_BEFORE;
    if (guard_after_ok)
        record->guard_flags |= ZN_ACP_DIRTY_DIAG_GUARD_FINAL_AFTER;
    if (!guard_before_ok || !guard_after_ok) {
        xil_printf("ACP_SMOKE adjacent guard mismatch case=%d\r\n", (int)test_index);
        return zn_acp_smoke_fail_case(
            test_index, ZN_ACP_DIRTY_DIAG_STAGE_GUARDS_CHECKED,
            ZN_ACP_DIRTY_DIAG_FAIL_GUARD);
    }
    zn_acp_dirty_diag_set_stage(&zn_acp_smoke_diagnostic, test_index,
                                ZN_ACP_DIRTY_DIAG_STAGE_GUARDS_CHECKED);

    if (!zn_acp_dirty_diag_complete_case(&zn_acp_smoke_diagnostic, test_index,
                                         result_ok && immediate_ok &&
                                             full_output_ok && guard_before_ok &&
                                             guard_after_ok,
                                         ack_ok, ownership_released)) {
        return zn_acp_smoke_fail_case(
            test_index, ZN_ACP_DIRTY_DIAG_STAGE_GUARDS_CHECKED,
            ZN_ACP_DIRTY_DIAG_FAIL_OWNERSHIP);
    }
    zn_acp_smoke_flush_diagnostic();

    xil_printf("ACP_SMOKE case=%d PASS immediate-probes + full-output-oracle "
               "after scratch pressure + guards\r\n",
               (int)test_index);
    return 0;
}

int z100_acp_pool_coherence_smoke_candidate(void)
{
    static const struct {
        int8_t input;
        ZnAcpSmokeCacheState cache_state;
    } cases[ZN_ACP_SMOKE_CASES] = {
        {-37, ZN_ACP_SMOKE_DIRTY_HOT},
        {-83, ZN_ACP_SMOKE_DIRTY_HOT},
        {-37, ZN_ACP_SMOKE_DIRTY_HOT},
        {-83, ZN_ACP_SMOKE_DIRTY_HOT},
        {-37, ZN_ACP_SMOKE_CLEAN_HOT},
        {-83, ZN_ACP_SMOKE_COLD}
    };
    ZnNativePlatformMmioXilinxContextV1 mmio_context = {
        ZN_NPMMIO_V1_BASE, ZN_NPMMIO_V1_BYTES, 0, 0, 0, 0
    };
    ZnNativeConvMmioOpsV2 mmio_ops;
    ZnNativeConvDriverV2 driver;
    uint32_t test_index;

    zn_acp_dirty_diag_init(
        &zn_acp_smoke_diagnostic, ZN_ACP_SMOKE_EPOCH,
        ZN_ACP_SMOKE_SOURCE_BASE, ZN_ACP_SMOKE_DESTINATION_BASE,
        ZN_ACP_SMOKE_PRESSURE_BASE, ZN_ACP_SMOKE_PHYSICAL_BYTES,
        ZN_ACP_SMOKE_PHYSICAL_BYTES, ZN_ACP_SMOKE_SCRATCH_BYTES);

    if (zn_acp_cache_policy_mode_v1() != ZN_ACP_POLICY_MODE_SMOKE_ONLY_V1) {
        xil_printf("ACP_SMOKE refused: policy mode is not smoke-only\r\n");
        zn_acp_dirty_diag_fail_preflight(&zn_acp_smoke_diagnostic,
                                         ZN_ACP_DIRTY_DIAG_FAIL_POLICY);
        zn_acp_smoke_flush_diagnostic();
        return -1;
    }
    if (z100_acp_live_coherence_state_check_v1() == 0) {
        zn_acp_dirty_diag_fail_preflight(&zn_acp_smoke_diagnostic,
                                         ZN_ACP_DIRTY_DIAG_FAIL_PLATFORM);
        zn_acp_smoke_flush_diagnostic();
        return -1;
    }
    if (zn_native_platform_mmio_xilinx_ops_v1(&mmio_ops, &mmio_context) != 0 ||
        zn_native_conv_driver_init_v2(&driver, &mmio_ops) !=
            ZN_NATIVE_CONV_DRIVER_V2_OK) {
        xil_printf("ACP_SMOKE MMIO/driver initialization failed\r\n");
        zn_acp_dirty_diag_fail_preflight(&zn_acp_smoke_diagnostic,
                                         ZN_ACP_DIRTY_DIAG_FAIL_PLATFORM);
        zn_acp_smoke_flush_diagnostic();
        return -1;
    }

    for (test_index = 0; test_index < ZN_ACP_SMOKE_CASES; ++test_index) {
        if (zn_acp_smoke_run_case(test_index, cases[test_index].input,
                                  cases[test_index].cache_state, &driver) != 0) {
            xil_printf("ACP_SMOKE STOP: do not start graph or reuse smoke buffers\r\n");
            return -1;
        }
    }

    xil_printf("ACP_SMOKE PASS destination matched software oracle after scratch pressure; no FPS claim\r\n");
    return 0;
}
