#ifndef V8_LWIP_H
#define V8_LWIP_H
#include "v8_service.h"
int v8_network_start(V8Service *service);
void v8_network_pump(void);
#endif
