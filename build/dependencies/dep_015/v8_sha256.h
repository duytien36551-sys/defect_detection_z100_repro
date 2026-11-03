#ifndef V8_SHA256_H
#define V8_SHA256_H
#include <stddef.h>
#include <stdint.h>
void v8_sha256_hex(const uint8_t *data, size_t length, char hex[65]);
#endif
