#ifndef V8_SHA256_H
#define V8_SHA256_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t state[8];
    uint64_t total_bytes;
    uint8_t block[64];
    size_t block_bytes;
    uint32_t magic;
    uint32_t finalized;
} V8Sha256Context;

int v8_sha256_init(V8Sha256Context *context);
int v8_sha256_update(V8Sha256Context *context, const uint8_t *data, size_t length);
int v8_sha256_final_hex(V8Sha256Context *context, char hex[65]);
void v8_sha256_hex(const uint8_t *data, size_t length, char hex[65]);
#endif
