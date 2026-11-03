#ifndef V8_RUNTIME_H
#define V8_RUNTIME_H
#include <stddef.h>
#include <stdint.h>
enum { V8_CONV, V8_SILU, V8_SLICE, V8_CONCAT, V8_ADD, V8_POOL, V8_UPSAMPLE };
typedef struct {
    uint32_t op,c,h,w,offset,bytes;
    int32_t inputs[8]; uint32_t count;
    uint32_t kernel,stride,padding,groups,slice_start;
    uint32_t weight,bias,multiplier,lut;
    double scale;
} V8Node;
typedef struct {
    const V8Node *nodes; uint32_t count,arena_bytes,param_bytes,param_crc;
    uint32_t outputs[3]; double input_scale;
    uint32_t classes,reg_max,input_size;
} V8Graph;
/* Conv callback must produce exactly node c*h*w raw int32 NCHW accumulators.
   NULL callback deliberately selects host/ARM reference, never claims PL execution. */
typedef int (*V8ConvFn)(void*,const V8Node*,const V8Node*,const int8_t*,const int8_t*,const uint8_t*,int32_t*);
/* Optional diagnostics use caller supplied clock units and never change execution. */
typedef uint64_t (*V8ClockFn)(void*);
typedef void (*V8TraceFn)(void*,uint32_t node,uint32_t op,uint64_t ticks,
                          const int8_t *output,size_t output_bytes);
typedef struct {
    const V8Graph *graph; const uint8_t *params; size_t param_size;
    int8_t *arena; size_t arena_size; int32_t *scratch; size_t scratch_count;
    V8ConvFn conv; void *opaque; uint32_t completed,callback_convolutions;
    V8ClockFn clock; V8TraceFn trace; void *trace_opaque;
} V8Runtime;
int v8_package_open(const uint8_t *blob,size_t size,const V8Graph *graph,const uint8_t **params);
int v8_graph_preflight(const V8Runtime *runtime);
int v8_run(V8Runtime *runtime,const int8_t *input,size_t input_bytes);
#endif
