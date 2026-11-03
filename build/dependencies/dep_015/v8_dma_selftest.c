/* Diagnostic ELF only: real DMA tests, no network or software inference fallback. */
#include "v8_dma.h"
#include <string.h>
typedef struct {
    volatile uint32_t stage, batch, checked, mismatches;
    volatile int32_t rc;
    volatile uint32_t expected_input_bytes, expected_output_bytes;
} V8DmaSelftestReport;
V8DmaSelftestReport v8_dma_selftest_report;
static int8_t test_input[27u*606u];
static int8_t test_weights[27];
static int32_t test_raw[606];

int v8_dma_selftest(V8DmaContext *context)
{
    static const uint32_t batches[3]={1,8,606};
    static const uint8_t bias[4]={0xf9,0xff,0xff,0xff}; /* -7 */
    V8Node n,s;
    uint32_t test,ic,site;
    memset(&n,0,sizeof(n));memset(&s,0,sizeof(s));
    n.c=1;n.h=1;n.kernel=1;n.stride=1;n.groups=1;
    s.c=27;s.h=1;
    for(ic=0;ic<27;++ic)test_weights[ic]=(int8_t)((int)(ic%7)-3);
    for(test=0;test<3;++test){
        uint32_t batch=batches[test];
        v8_dma_selftest_report.stage=test+1;
        v8_dma_selftest_report.batch=batch;
        v8_dma_selftest_report.rc=-2147483647;
        v8_dma_selftest_report.checked=0;
        v8_dma_selftest_report.mismatches=0;
        v8_dma_selftest_report.expected_input_bytes=27u*batch*4u;
        v8_dma_selftest_report.expected_output_bytes=8u*batch;
        n.w=batch;s.w=batch;
        for(ic=0;ic<27;++ic)for(site=0;site<batch;++site)
            test_input[ic*batch+site]=(int8_t)((int)((ic+site)%11)-5);
        v8_dma_selftest_report.rc=v8_dma_conv(context,&n,&s,test_input,test_weights,bias,test_raw);
        if(v8_dma_selftest_report.rc)return -1;
        for(site=0;site<batch;++site){
            int32_t expected=-7;
            for(ic=0;ic<27;++ic)expected+=(int32_t)test_input[ic*batch+site]*test_weights[ic];
            if(test_raw[site]!=expected)++v8_dma_selftest_report.mismatches;
            ++v8_dma_selftest_report.checked;
        }
        if(v8_dma_selftest_report.mismatches)return -2;
    }
    v8_dma_selftest_report.stage=4;
    return 0;
}
