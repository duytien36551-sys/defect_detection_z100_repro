#define ZN_NATIVE_VIEW_NEON_TEST 1
/* Faster equivalent of the portable view materialiser.
 *
 * The original called native_offset() twice per output byte, i.e. repeated layout
 * index arithmetic per byte. Constant power-of-two divisions can compile to
 * shifts; this optimization does not assume software division calls. Here the native word layout is walked with pointer
 * arithmetic, so the pixel loop contains no division or modulo at all: within
 * one 64-byte word a channel owns 16 contiguous x positions, and the stride
 * from one 16-wide x block to the next is groups*64 bytes.
 *
 * Output bytes are identical to the original, including the literal zero in
 * partial 16-wide tails and in unused channel slots of the last 4-lane group,
 * because the buffer is still zeroed first and only x < width is written.
 *
 * Guards, argument checks and return codes are unchanged, and every check
 * still precedes the first output write. */
#include "native_view_materialize_v1.h"
#include <string.h>

#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif

typedef struct {
    uint16_t lut_index;
    uint16_t multiplier;
    uint8_t shift;
    uint8_t cap;
} ZnViewFormula;

#if defined(__ARM_NEON) || defined(ZN_NATIVE_VIEW_NEON_TEST)
static const ZnViewFormula zn_view_formulas[] = {
    {1, 1, 0, 127}, {2, 8365, 13, 127}, {5, 2977, 11, 127},
    {8, 341, 9, 127}, {9, 981, 9, 127}, {10, 2669, 12, 127},
    {12, 4893, 13, 127}, {13, 1751, 10, 127}, {16, 847, 10, 127},
    {17, 1055, 10, 127}, {19, 825, 10, 127}, {21, 1589, 10, 127},
    {24, 761, 10, 127}, {25, 639, 9, 127}, {28, 1975, 11, 127},
    {29, 8901, 13, 127}, {31, 5249, 13, 127},
    {3, 573, 10, 71}, {6, 1611, 11, 100}, {14, 451, 9, 112},
    {18, 1, 0, 123}, {20, 8139, 13, 126}, {22, 3975, 12, 123},
    {26, 829, 10, 103}, {30, 1, 0, 117}
};

#define ZN_VIEW_FORMULA_COUNT \
    ((unsigned)(sizeof zn_view_formulas / sizeof zn_view_formulas[0]))
#endif

#ifdef ZN_NATIVE_VIEW_NEON_TEST
uint32_t g_zn_view_neon_qualified_luts;
uint32_t g_zn_view_neon_fallback_luts;
uint32_t g_zn_view_neon_vector_blocks;
uint32_t g_zn_view_neon_scalar_emulated_blocks;
uint32_t g_zn_view_neon_lut_blocks;
#endif

#if defined(__ARM_NEON) || defined(ZN_NATIVE_VIEW_NEON_TEST)
static const ZnViewFormula *zn_view_formula_by_id(unsigned formula_id) {
    return formula_id && formula_id<=ZN_VIEW_FORMULA_COUNT
        ? &zn_view_formulas[formula_id-1u] : (const ZnViewFormula *)0;
}
#endif

#if defined(__ARM_NEON) || defined(ZN_NATIVE_VIEW_NEON_TEST)
#if defined(ZN_NATIVE_VIEW_NEON_TEST) && !defined(__ARM_NEON)
static int32_t zn_view_formula_value(int8_t input, const ZnViewFormula *f) {
    int32_t product=(int32_t)input*(int32_t)f->multiplier;
    int32_t rounded=product;
    if(f->shift) {
        int32_t floor_quotient=product>>f->shift;
        uint32_t odd=((uint32_t)floor_quotient)&1u;
        int32_t bias=(int32_t)((1u<<(f->shift-1u))-1u+odd);
        rounded=(product+bias)>>f->shift;
    }
    if(rounded>(int32_t)f->cap) rounded=(int32_t)f->cap;
    if(rounded< -(int32_t)f->cap) rounded= -(int32_t)f->cap;
    return rounded;
}
#endif

#if defined(__ARM_NEON)
static int32x4_t zn_view_round_even_s32(int32x4_t product, unsigned shift) {
    int32x4_t floor_quotient, bias;
    if(!shift) return product;
    floor_quotient=vshlq_s32(product,vdupq_n_s32(-(int)shift));
    bias=vaddq_s32(vdupq_n_s32((int32_t)((1u<<(shift-1u))-1u)),
                   vandq_s32(floor_quotient,vdupq_n_s32(1)));
    return vshlq_s32(vaddq_s32(product,bias),
                     vdupq_n_s32(-(int)shift));
}

static int32x4_t zn_view_formula_four(int16x4_t input,
                                      const ZnViewFormula *f) {
    int32x4_t widened=vmovl_s16(input);
    int32x4_t product=vmulq_s32(widened,vdupq_n_s32((int32_t)f->multiplier));
    return zn_view_round_even_s32(product,f->shift);
}
#endif

static void zn_view_formula_16(const uint8_t *src, uint8_t *dst,
                               const ZnViewFormula *f) {
#if defined(__ARM_NEON)
    int8x16_t bytes=vld1q_s8((const int8_t *)src);
    if(!f->shift) {
        if(f->cap<127u) {
            bytes=vmaxq_s8(bytes,vdupq_n_s8(-(int8_t)f->cap));
            bytes=vminq_s8(bytes,vdupq_n_s8((int8_t)f->cap));
        } else {
            bytes=vmaxq_s8(bytes,vdupq_n_s8(-127));
        }
        vst1q_u8(dst,vreinterpretq_u8_s8(bytes));
        return;
    }
    int16x8_t lo=vmovl_s8(vget_low_s8(bytes));
    int16x8_t hi=vmovl_s8(vget_high_s8(bytes));
    int32x4_t q0=zn_view_formula_four(vget_low_s16(lo),f);
    int32x4_t q1=zn_view_formula_four(vget_high_s16(lo),f);
    int32x4_t q2=zn_view_formula_four(vget_low_s16(hi),f);
    int32x4_t q3=zn_view_formula_four(vget_high_s16(hi),f);
    int16x8_t qlo=vcombine_s16(vqmovn_s32(q0),vqmovn_s32(q1));
    int16x8_t qhi=vcombine_s16(vqmovn_s32(q2),vqmovn_s32(q3));
    int8x8_t blo=vqmovn_s16(qlo);
    int8x8_t bhi=vqmovn_s16(qhi);
    if(f->cap<127u) {
        blo=vmax_s8(blo,vdup_n_s8(-(int8_t)f->cap));
        bhi=vmax_s8(bhi,vdup_n_s8(-(int8_t)f->cap));
        blo=vmin_s8(blo,vdup_n_s8((int8_t)f->cap));
        bhi=vmin_s8(bhi,vdup_n_s8((int8_t)f->cap));
    } else {
        blo=vmax_s8(blo,vdup_n_s8(-127));
        bhi=vmax_s8(bhi,vdup_n_s8(-127));
    }
    vst1q_u8(dst,vreinterpretq_u8_s8(vcombine_s8(blo,bhi)));
#else
    unsigned i;
    for(i=0;i<16u;i++)
        dst[i]=(uint8_t)zn_view_formula_value((int8_t)src[i],f);
#endif
}

static void zn_view_formula_64(const uint8_t *src, uint8_t *dst,
                               const ZnViewFormula *f) {
    unsigned i;
    for(i=0;i<64u;i+=16u) zn_view_formula_16(src+i,dst+i,f);
}

typedef struct {
    uint16_t lut_index;
    uint8_t formula_id;
} ZnViewFormulaCacheEntry;

#define ZN_VIEW_FORMULA_CACHE_CAPACITY 256u

static uint8_t zn_view_qualify_formula(
    uint16_t lut_index, const uint8_t *lut,
    ZnViewFormulaCacheEntry *cache, unsigned *cache_count) {
    unsigned i, x, formula_id=0;
    for(i=0;i<*cache_count;i++)
        if(cache[i].lut_index==lut_index) return cache[i].formula_id;
    for(i=0;i<ZN_VIEW_FORMULA_COUNT;i++) {
        const ZnViewFormula *f=&zn_view_formulas[i];
        unsigned matches=1;
        if(f->lut_index!=lut_index) continue;
        for(x=0;x<256u;x+=16u) {
            uint8_t input[16], predicted[16];
            unsigned j;
            for(j=0;j<16u;j++) input[j]=(uint8_t)((x+j)^128u);
            zn_view_formula_16(input,predicted,f);
            if(memcmp(predicted,lut+x,16u)!=0) matches=0;
        }
        if(matches) formula_id=i+1u;
    }
    if(*cache_count<ZN_VIEW_FORMULA_CACHE_CAPACITY) {
        cache[*cache_count].lut_index=lut_index;
        cache[*cache_count].formula_id=(uint8_t)formula_id;
        ++*cache_count;
    }
#ifdef ZN_NATIVE_VIEW_NEON_TEST
    if(formula_id) ++g_zn_view_neon_qualified_luts;
    else ++g_zn_view_neon_fallback_luts;
#endif
    return (uint8_t)formula_id;
}

#ifdef ZN_NATIVE_VIEW_NEON_TEST
int zn_native_view_neon_test_apply_formula(uint8_t formula_id,
                                           const uint8_t input[256],
                                           uint8_t output[256]) {
    const ZnViewFormula *f=zn_view_formula_by_id(formula_id);
    unsigned i;
    if(!f || !input || !output) return -1;
    for(i=0;i<256u;i+=16u) zn_view_formula_16(input+i,output+i,f);
    return 0;
}
#endif
#endif

static size_t native_bytes(uint16_t c, uint16_t h, uint16_t w) {
    return (size_t)((c+3u)/4u)*h*((w+15u)/16u)*64u;
}
static int shape_valid(uint16_t c, uint16_t h, uint16_t w) {
    return c && c<=1024 && h && h<=640 && w && w<=640;
}
static int ref_equal(ZnRef a, ZnRef b) {
    return a.slot==b.slot && a.tensor==b.tensor && a.generation==b.generation;
}
static int valid_span(const void *p, size_t bytes) {
    return p && bytes && bytes<=UINTPTR_MAX-(uintptr_t)p;
}
static int overlap(const void *a, size_t na, const void *b, size_t nb) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<y+nb && y<x+na;
}

/* Native word layout for one 32-channel slice:
 *   word = (c32/4)*height*xwords + (y*xwords + x/16)*groups + (c%32)/4
 *   byte = word*64 + (c%4)*16 + x%16
 * groups is the number of 4-channel words stored per 16-wide x block. */
static size_t slice_groups(uint16_t channels, unsigned c) {
    unsigned c32=c/32u*32u;
    unsigned g=channels-c32;
    return ((g<32u?g:32u)+3u)/4u;
}
/* Byte offset of (c, y=0, x block 0), i.e. the base for this channel.
 * Every 32-channel slice before this one is complete, so the preceding slices
 * always contribute (c32/4)*height*xwords words; the channel count only enters
 * the per-row stride, which slice_groups() provides. */
static size_t channel_base(uint16_t height, uint16_t width, unsigned c) {
    size_t xwords=(width+15u)/16u;
    unsigned c32=c/32u*32u;
    return (((size_t)(c32/4u)*(size_t)height*xwords+(size_t)((c%32u)/4u))*64u
            +(size_t)(c%4u)*16u);
}

#ifdef ZN_NATIVE_VIEW_BLOCK64_TEST
uint32_t zn_native_view_block64_test_hits;
uint32_t zn_native_view_block64_tail_test_hits;
uint32_t zn_native_view_dense_clear_test_skips;
#endif

static int block64_group_matches(const ZnNativeViewChannelV1 *channels,
                                 unsigned output_channels,
                                 unsigned output_channel) {
    const ZnNativeViewChannelV1 *first;
    unsigned lane;
    if((output_channel&3u) || output_channels-output_channel<4u) return 0;
    first=&channels[output_channel];
    if((first->source_channel&3u) || first->divisor_h!=1u ||
       first->divisor_w!=1u) return 0;
    for(lane=1;lane<4u;lane++) {
        const ZnNativeViewChannelV1 *m=&channels[output_channel+lane];
        if(m->source_index!=first->source_index ||
           (unsigned)m->source_channel!=(unsigned)first->source_channel+lane ||
           m->lut_index!=first->lut_index ||
           m->divisor_h!=1u || m->divisor_w!=1u) return 0;
    }
    return 1;
}

/* Advance the source by 16/DW bytes per output block. Cross the native
 * groups*64 stride only after consuming all 16 source pixels.
 * Emit one row of one output channel. dw must be 1, 2 or 4 as a compile-time
 * constant at every call site so the shifts fold away. */
#define Z100_VIEW_ROW(DW, DH)                                                  \
    do {                                                                       \
        const unsigned per_block=16u/(DW);                                     \
        unsigned xb, source_x=0;                                               \
        uint8_t *p=dp;                                                         \
        const uint8_t *q=sp;                                                   \
        for(xb=0;xb<full_out;xb++) {                                           \
            unsigned k;                                                        \
            if((DW)==1u) {                                                     \
                for(k=0;k<per_block;k++) p[k]=lut[q[k]^128u];                  \
            } else if((DW)==2u) {                                              \
                for(k=0;k<per_block;k++) {                                     \
                    uint8_t v=lut[q[k]^128u];                                  \
                    p[2u*k]=v; p[2u*k+1u]=v;                                   \
                }                                                              \
            } else {                                                           \
                for(k=0;k<per_block;k++) {                                     \
                    uint8_t v=lut[q[k]^128u];                                  \
                    p[4u*k]=v; p[4u*k+1u]=v;                                   \
                    p[4u*k+2u]=v; p[4u*k+3u]=v;                                \
                }                                                              \
            }                                                                  \
            if(xb+1u<full_out || tail) {                                       \
                source_x+=per_block;                                           \
                if(source_x==16u) {                                            \
                    q+=(size_t)src_groups*64u-(16u-per_block);                   \
                    source_x=0;                                                \
                } else q+=per_block;                                           \
                p+=(size_t)out_groups*64u;                                      \
            }                                                                  \
        }                                                                      \
        if(tail) {                                                             \
            unsigned j;                                                        \
            for(j=0;j<tail;j++) p[j]=lut[q[j/(DW)]^128u];                      \
        }                                                                      \
    } while(0)

int zn_native_view_materialize_v1(
    uint32_t epoch, const ZnNativeViewSourceV1 *sources, uint8_t source_count,
    const ZnNativeViewChannelV1 *channels, uint16_t output_channels,
    uint16_t output_height, uint16_t output_width,
    const uint8_t *tables, uint16_t table_count,
    uint8_t *output, size_t output_bytes) {
    unsigned c;
    size_t source_metadata=(size_t)source_count*sizeof *sources;
    size_t channel_metadata=(size_t)output_channels*sizeof *channels;
    size_t table_bytes=(size_t)table_count*256u;
#if defined(__ARM_NEON) || defined(ZN_NATIVE_VIEW_NEON_TEST)
    ZnViewFormulaCacheEntry formula_cache[ZN_VIEW_FORMULA_CACHE_CAPACITY];
    unsigned formula_cache_count=0;
#endif
    if(!epoch || !source_count || source_count>7 || !table_count ||
       !shape_valid(output_channels,output_height,output_width) ||
       output_bytes!=native_bytes(output_channels,output_height,output_width) ||
       !valid_span(output,output_bytes) || !valid_span(sources,source_metadata) ||
       !valid_span(channels,channel_metadata) || !valid_span(tables,table_bytes) ||
       overlap(output,output_bytes,sources,source_metadata) ||
       overlap(output,output_bytes,channels,channel_metadata) ||
       overlap(output,output_bytes,tables,table_bytes)) return -1;
    {
        unsigned i;
        for(i=0;i<source_count;i++) {
            const ZnNativeViewSourceV1 *s=&sources[i];
            unsigned j;
            if(s->epoch!=epoch || s->ref.slot>=7 || !s->ref.generation ||
               s->ref.tensor< -1 || s->ref.tensor>65535 ||
               !shape_valid(s->channels,s->height,s->width) ||
               s->bytes!=native_bytes(s->channels,s->height,s->width) ||
               !valid_span(s->data,s->bytes) ||
               overlap(output,output_bytes,s->data,s->bytes)) return -1;
            for(j=0;j<i;j++) if(s->ref.slot==sources[j].ref.slot) return -1;
        }
    }
    for(c=0;c<output_channels;c++) {
        const ZnNativeViewChannelV1 *m=&channels[c];
        const ZnNativeViewSourceV1 *s;
        if(m->source_index>=source_count || m->lut_index>=table_count ||
           (m->divisor_h!=1 && m->divisor_h!=2 && m->divisor_h!=4) ||
           (m->divisor_w!=1 && m->divisor_w!=2 && m->divisor_w!=4)) return -1;
        s=&sources[m->source_index];
        if(!ref_equal(s->ref,m->expected_ref) || m->source_channel>=s->channels ||
           (unsigned)s->height*m->divisor_h!=output_height ||
           (unsigned)s->width*m->divisor_w!=output_width) return -1;
    }
    /* Every guard precedes the first output write. Tails are literal zero,
     * matching FeatureLayout; applying the LUT to padding would be incorrect. */
    /* Whole channel groups and x words have no padding and are fully written. */
    if((output_channels&3u)!=0u || (output_width&15u)!=0u)
        memset(output,0,output_bytes);
#ifdef ZN_NATIVE_VIEW_BLOCK64_TEST
    else
        ++zn_native_view_dense_clear_test_skips;
#endif

    {
        const size_t out_xwords=((size_t)output_width+15u)/16u;
        size_t out_groups=slice_groups(output_channels,0);
        size_t out_row_stride=out_xwords*out_groups*64u;
        unsigned oprev=0;
        for(c=0;c<output_channels;c++) {
            if(block64_group_matches(channels,output_channels,c)) {
                const ZnNativeViewChannelV1 *m=&channels[c];
                const ZnNativeViewSourceV1 *s=&sources[m->source_index];
                const uint8_t *lut=tables+(size_t)m->lut_index*256u;
#if defined(__ARM_NEON) || defined(ZN_NATIVE_VIEW_NEON_TEST)
                uint8_t formula_id=output_width>=16u
                    ? zn_view_qualify_formula(m->lut_index,lut,formula_cache,
                                              &formula_cache_count)
                    : 0u;
                const ZnViewFormula *formula=zn_view_formula_by_id(formula_id);
#endif
                const size_t src_groups=slice_groups(s->channels,m->source_channel);
                const size_t src_row_stride=
                    (((size_t)s->width+15u)/16u)*src_groups*64u;
                const size_t group_out=slice_groups(output_channels,c);
                const size_t group_out_row_stride=out_xwords*group_out*64u;
                size_t sb=channel_base(s->height,s->width,m->source_channel);
                size_t db=channel_base(output_height,output_width,c);
                unsigned y;
                for(y=0;y<output_height;y++) {
                    const uint8_t *sp=(const uint8_t *)s->data+sb;
                    uint8_t *dp=output+db;
                    size_t xb;
                    for(xb=0;xb<(size_t)output_width/16u;xb++) {
                        unsigned i;
#if defined(__ARM_NEON) || defined(ZN_NATIVE_VIEW_NEON_TEST)
                        if(formula) {
                            zn_view_formula_64(sp,dp,formula);
#ifdef ZN_NATIVE_VIEW_NEON_TEST
#if defined(__ARM_NEON)
                            ++g_zn_view_neon_vector_blocks;
#else
                            ++g_zn_view_neon_scalar_emulated_blocks;
#endif
#endif
                        } else {
                            for(i=0;i<64u;i++) dp[i]=lut[sp[i]^128u];
#ifdef ZN_NATIVE_VIEW_NEON_TEST
                            ++g_zn_view_neon_lut_blocks;
#endif
                        }
#else
                        for(i=0;i<64u;i++) dp[i]=lut[sp[i]^128u];
#endif
#ifdef ZN_NATIVE_VIEW_BLOCK64_TEST
                        ++zn_native_view_block64_test_hits;
#endif
                        if(xb+1u<(size_t)output_width/16u || (output_width&15u)) {
                            sp+=src_groups*64u;
                            dp+=group_out*64u;
                        }
                    }
                    if(output_width&15u) {
                        unsigned lane, x;
                        /* Padding remains literal zero from the full memset;
                         * LUT transforms only the valid pixels in each lane. */
                        for(lane=0;lane<4u;lane++)
                            for(x=0;x<(output_width&15u);x++)
                                dp[lane*16u+x]=lut[sp[lane*16u+x]^128u];
#ifdef ZN_NATIVE_VIEW_BLOCK64_TEST
                        ++zn_native_view_block64_tail_test_hits;
#endif
                    }
                    sb+=src_row_stride;
                    db+=group_out_row_stride;
                }
                c+=3u;
                continue;
            }
            const ZnNativeViewChannelV1 *m=&channels[c];
            const ZnNativeViewSourceV1 *s=&sources[m->source_index];
            const uint8_t *lut=tables+(size_t)m->lut_index*256u;
            const unsigned sc=m->source_channel;
            const unsigned dh=m->divisor_h, dw=m->divisor_w;
            const size_t src_groups=slice_groups(s->channels,sc);
            const size_t src_row_stride=
                (((size_t)s->width+15u)/16u)*src_groups*64u;
            const size_t full_out=(size_t)output_width/16u;
            const unsigned tail=(unsigned)((size_t)output_width%16u);
            size_t db, sb;
            unsigned y, yacc=0;
            if(c/32u!=oprev) {
                oprev=c/32u; out_groups=slice_groups(output_channels,c);
                out_row_stride=out_xwords*out_groups*64u;
            }
            db=channel_base(output_height,output_width,c);
            sb=channel_base(s->height,s->width,sc);
            for(y=0;y<output_height;y++) {
                const uint8_t *sp=(const uint8_t *)s->data+sb;
                uint8_t *dp=output+db;
                switch((dh<<4)|dw) {
                case 0x11: Z100_VIEW_ROW(1u,1u); break;
                case 0x12: Z100_VIEW_ROW(2u,1u); break;
                case 0x14: Z100_VIEW_ROW(4u,1u); break;
                case 0x21: Z100_VIEW_ROW(1u,2u); break;
                case 0x22: Z100_VIEW_ROW(2u,2u); break;
                case 0x24: Z100_VIEW_ROW(4u,2u); break;
                case 0x41: Z100_VIEW_ROW(1u,4u); break;
                case 0x42: Z100_VIEW_ROW(2u,4u); break;
                default:   Z100_VIEW_ROW(4u,4u); break;
                }
                db+=out_row_stride;
                if(++yacc==dh) { yacc=0; sb+=src_row_stride; }
            }
        }
    }
    return 0;
}
