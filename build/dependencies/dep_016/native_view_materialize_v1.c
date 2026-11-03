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
    memset(output,0,output_bytes);

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
                        for(i=0;i<64u;i++) dp[i]=lut[sp[i]^128u];
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
