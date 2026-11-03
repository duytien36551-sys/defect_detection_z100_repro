#ifndef V8_VFP_REQUANT_H
#define V8_VFP_REQUANT_H

#include <stddef.h>
#include <stdint.h>

#include "v8_runtime.h"

#define V8_VFP_SELFTEST_MAGIC 0x56385251u
#define V8_VFP_SELFTEST_STATUS_WORDS 16u

enum {
    V8_VFP_SELFTEST_STATUS_MAGIC = 0,
    V8_VFP_SELFTEST_STATUS_FPSCR_INITIAL = 1,
    V8_VFP_SELFTEST_STATUS_SAFE = 2,
    V8_VFP_SELFTEST_STATUS_MISMATCHES = 3,
    V8_VFP_SELFTEST_STATUS_COMPARISONS = 4,
    V8_VFP_SELFTEST_STATUS_HALF_COMPARISONS = 5,
    V8_VFP_SELFTEST_STATUS_UNIFORM_COMPARISONS = 6,
    V8_VFP_SELFTEST_STATUS_MODEL_BOUNDARY_COMPARISONS = 7,
    V8_VFP_SELFTEST_STATUS_MODEL_RANDOM_COMPARISONS = 8,
    V8_VFP_SELFTEST_STATUS_MODEL_MULTIPLIERS = 9,
    V8_VFP_SELFTEST_STATUS_ERROR = 10,
    V8_VFP_SELFTEST_STATUS_FPSCR_FINAL = 11,
    V8_VFP_SELFTEST_STATUS_NONFINITE_COMPARISONS = 12,
    V8_VFP_SELFTEST_STATUS_VBAR = 13,
    V8_VFP_SELFTEST_STATUS_SCTLR = 14,
    V8_VFP_SELFTEST_STATUS_CPSR = 15
};

extern uint32_t v8_vfp_selftest_status[V8_VFP_SELFTEST_STATUS_WORDS];

/* Compare the optimized conversion against the loaded model's multipliers. */
int v8_vfp_requant_selftest(const V8Graph *graph, const uint8_t *params,
                            size_t param_size);

#if defined(V8_TILE_VFP_REQUANT)
#if !defined(__arm__)
#error "V8_TILE_VFP_REQUANT requires an ARM VFP target"
#endif

/* FPSCR exception-enable bits: IDE, IXE, UFE, OFE, DZE and IOE. */
#define V8_VFP_FPSCR_TRAP_ENABLES 0x00009f00u
#define V8_VFP_FPSCR_RMODE_MASK   0x00c00000u

static inline uint32_t v8_vfp_requant_read_fpscr(void)
{
    uint32_t fpscr;
    __asm__ volatile("vmrs %0, fpscr" : "=r"(fpscr) : : "memory");
    return fpscr;
}

static inline int v8_vfp_requant_fpscr_is_safe(uint32_t fpscr)
{
    return (fpscr & (V8_VFP_FPSCR_RMODE_MASK |
                     V8_VFP_FPSCR_TRAP_ENABLES)) == 0u;
}

/* VCVTR obeys FPSCR. The caller must first verify RN/traps-disabled and clamp
 * finite inputs to [-127, 127]. This function never writes FPSCR. */
static inline int32_t v8_vfp_requant_round_f64_to_i32(double value)
{
    int32_t result;
    float vfp_word;
    __asm__ volatile("vcvtr.s32.f64 %1, %P2\n\t"
                     "vmov %0, %1"
                     : "=&r"(result), "=&t"(vfp_word)
                     : "w"(value)
                     : "memory");
    return result;
}

static inline int8_t v8_vfp_requant_round_saturated_finite(double value)
{
    if (value >= 127.0) return 127;
    if (value <= -127.0) return -127;
    return (int8_t)v8_vfp_requant_round_f64_to_i32(value);
}
#endif

#endif
